// 只读 Web Search / Fetch MCP server（stdio，JSON-RPC over newline）。
//
// 迁自 surfcore/src/mcp-web-search-safe.js：行为一致，但**不依赖 @modelcontextprotocol/sdk**，
// 只保留 js-yaml（web-search.js 用来读 ~/.dsh/.credentials.yaml）。少 20 MB 的 node_modules。
//
// 安全设计（与原件相同）：
// - 只暴露只读工具；不暴露本地文件、命令执行、写操作。
// - 查询词去 CQ 码/控制字符、截断 120 字。
// - web_fetch 仅允许 http(s)，禁内网/环回，逐跳校验重定向。
// - 日志只写 stderr —— stdout 是协议流，写脏会直接让 MCP 客户端断连。

import path from 'node:path';
import readline from 'node:readline';
import { fileURLToPath } from 'node:url';
import { safeFetch } from './safe-fetch.js';
import { webSearch } from './web-search.js';

const HERE = path.dirname(fileURLToPath(import.meta.url));
// soulproject/ 根：用于读 config.json 的 webSearch 段（不存在就用默认值/凭据文件）。
const ROOT = path.resolve(HERE, '..', '..');

const SERVER_INFO = { name: 'web-search-safe', version: '0.3.0-local' };
const DEFAULT_PROTOCOL = '2024-11-05';

function log(msg) {
  try {
    process.stderr.write(`[web-search-mcp] ${msg}\n`);
  } catch {}
}

function sanitizeQuery(query) {
  return String(query ?? '')
    .replace(/\[CQ:[^\]]*\]/gi, ' ')
    .replace(/[\u0000-\u001f\u007f]/g, ' ')
    .replace(/\s+/g, ' ')
    .trim()
    .slice(0, 120);
}

const TOOLS = [
  {
    name: 'web_search',
    description:
      '只读联网搜索：优先使用与 DSH 相同的 DeepSeek 联网搜索（结果更准、不把群里的词发给搜索引擎广告网络），不可用时自动回退 Bing。返回标题/URL/摘要，不执行任何本地操作。适合查网络用语、梗、事实性问题和热点。',
    inputSchema: {
      type: 'object',
      properties: { query: { type: 'string', description: '要搜索确认的网络用语/黑话/梗/事实性问题' } },
      required: ['query'],
    },
  },
  {
    name: 'web_fetch',
    description:
      '只读抓取 HTTP(S) 网页正文，返回纯文本/HTML 前 50000 字符。禁止访问内网/本机地址，不执行任何本地操作。',
    inputSchema: {
      type: 'object',
      properties: { url: { type: 'string', description: '要抓取的 http(s) URL' } },
      required: ['url'],
    },
  },
];

async function callTool(name, args) {
  if (name === 'web_search') {
    const clean = sanitizeQuery(args?.query);
    if (!clean) return { content: [{ type: 'text', text: '查询词为空，已拒绝。' }], isError: true };
    try {
      const result = await webSearch(clean, { root: ROOT });
      return { content: [{ type: 'text', text: JSON.stringify(result, null, 2) }] };
    } catch (error) {
      return { content: [{ type: 'text', text: `搜索失败：${error?.message ?? error}` }], isError: true };
    }
  }
  if (name === 'web_fetch') {
    try {
      const result = await safeFetch(String(args?.url ?? ''));
      return { content: [{ type: 'text', text: JSON.stringify(result, null, 2) }] };
    } catch (error) {
      return { content: [{ type: 'text', text: `抓取失败：${error?.message ?? error}` }], isError: true };
    }
  }
  return { content: [{ type: 'text', text: `未知工具：${name}` }], isError: true };
}

function send(message) {
  process.stdout.write(JSON.stringify(message) + '\n');
}

async function handle(msg) {
  const { id, method, params } = msg || {};
  const isRequest = id !== undefined && id !== null;

  if (method === 'initialize') {
    const asked = String(params?.protocolVersion ?? '');
    send({
      jsonrpc: '2.0',
      id,
      result: {
        protocolVersion: asked || DEFAULT_PROTOCOL,
        capabilities: { tools: {} },
        serverInfo: SERVER_INFO,
      },
    });
    return;
  }
  if (method === 'notifications/initialized' || method === 'initialized') return;
  if (method === 'ping') {
    if (isRequest) send({ jsonrpc: '2.0', id, result: {} });
    return;
  }
  if (method === 'tools/list') {
    send({ jsonrpc: '2.0', id, result: { tools: TOOLS } });
    return;
  }
  if (method === 'tools/call') {
    const result = await callTool(String(params?.name ?? ''), params?.arguments ?? {});
    send({ jsonrpc: '2.0', id, result });
    return;
  }
  if (isRequest) {
    send({ jsonrpc: '2.0', id, error: { code: -32601, message: `Method not found: ${method}` } });
  }
}

const rl = readline.createInterface({ input: process.stdin, terminal: false });

// stdin 关闭时不能立刻 exit：web_search 是异步的，管道喂完就退会吞掉正在跑的结果。
let pending = 0;
let closed = false;
function maybeExit() {
  if (closed && pending === 0) process.exit(0);
}

rl.on('line', (line) => {
  const text = line.trim();
  if (!text) return;
  let msg;
  try {
    msg = JSON.parse(text);
  } catch (e) {
    log(`bad json: ${e.message}`);
    return;
  }
  pending += 1;
  handle(msg)
    .catch((e) => {
      log(`handler failed: ${e?.stack || e}`);
      if (msg?.id !== undefined) {
        send({ jsonrpc: '2.0', id: msg.id, error: { code: -32603, message: String(e?.message || e) } });
      }
    })
    .finally(() => {
      pending -= 1;
      maybeExit();
    });
});
rl.on('close', () => {
  closed = true;
  maybeExit();
});
log(`ready root=${ROOT}`);
