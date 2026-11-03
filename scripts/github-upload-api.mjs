#!/usr/bin/env node
/**
 * Upload the current tracked tree to an empty GitHub repository through the
 * REST Git Data API. This avoids the blocked github.com:443 git endpoint.
 *
 * Usage:
 *   set GITHUB_TOKEN=...            (or put token in .github-token)
 *   node scripts/github-upload-api.mjs --owner jiygfu --repo EmotionCoreForDSH-surfcore
 *
 * This creates ONE snapshot commit. Local history stays in the local repo.
 */
import { execFileSync } from 'node:child_process';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const API = 'https://api.github.com';

function arg(name, fallback = '') {
  const i = process.argv.indexOf(`--${name}`);
  return i >= 0 && process.argv[i + 1] ? process.argv[i + 1] : fallback;
}

const owner = arg('owner', 'jiygfu');
const repo = arg('repo', 'EmotionCoreForDSH-surfcore');
const branch = arg('branch', 'main');
const message = arg('message', `Upload ${new Date().toISOString().slice(0, 10)} snapshot`);

const token = process.env.GITHUB_TOKEN
  || (fs.existsSync(path.join(ROOT, '.github-token'))
    ? fs.readFileSync(path.join(ROOT, '.github-token'), 'utf8').trim()
    : '');
if (!token && !process.argv.includes('--dry-run')) {
  console.error('缺少 GITHUB_TOKEN（或仓库根目录的 .github-token）');
  process.exit(2);
}

const headers = {
  Authorization: `Bearer ${token}`,
  Accept: 'application/vnd.github+json',
  'X-GitHub-Api-Version': '2022-11-28',
  'User-Agent': 'emotioncore-upload',
  'Content-Type': 'application/json',
};

async function api(method, route, body) {
  const res = await fetch(`${API}${route}`, {
    method,
    headers,
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const text = await res.text();
  let data = null;
  try { data = text ? JSON.parse(text) : null; } catch { data = text; }
  if (!res.ok) {
    throw new Error(`${method} ${route} -> ${res.status}: ${text.slice(0, 500)}`);
  }
  return data;
}

function trackedFiles() {
  const out = execFileSync('git', ['-C', ROOT, 'ls-files', '-z'], { encoding: 'utf8' });
  return out.split('\0').filter(Boolean);
}

function modeFor(file) {
  try {
    const out = execFileSync('git', ['-C', ROOT, 'ls-files', '-s', '--', file], { encoding: 'utf8' });
    return out.startsWith('100755') ? '100755' : '100644';
  } catch {
    return '100644';
  }
}

async function main() {
  const files = trackedFiles();
  console.log(`repo=${owner}/${repo} branch=${branch} files=${files.length}`);
  if (process.argv.includes('--dry-run')) {
    console.log(files.slice(0, 20).join('\n'));
    return;
  }

  // Get existing ref (empty repo => 404).
  let parent = null;
  try {
    const ref = await api('GET', `/repos/${owner}/${repo}/git/ref/heads/${branch}`);
    parent = ref.object?.sha || null;
  } catch (err) {
    if (!String(err.message).includes('404')) throw err;
  }

  const tree = [];
  let done = 0;
  for (const file of files) {
    const buf = fs.readFileSync(path.join(ROOT, file));
    const blob = await api('POST', `/repos/${owner}/${repo}/git/blobs`, {
      content: buf.toString('base64'),
      encoding: 'base64',
    });
    tree.push({ path: file.replaceAll('\\', '/'), mode: modeFor(file), type: 'blob', sha: blob.sha });
    done += 1;
    if (done % 20 === 0 || done === files.length) console.log(`blobs ${done}/${files.length}`);
  }

  const treeObj = await api('POST', `/repos/${owner}/${repo}/git/trees`, {
    tree,
    ...(parent ? {} : {}),
  });
  const commit = await api('POST', `/repos/${owner}/${repo}/git/commits`, {
    message,
    tree: treeObj.sha,
    parents: parent ? [parent] : [],
  });
  if (parent) {
    await api('PATCH', `/repos/${owner}/${repo}/git/refs/heads/${branch}`, {
      sha: commit.sha,
      force: false,
    });
  } else {
    await api('POST', `/repos/${owner}/${repo}/git/refs`, {
      ref: `refs/heads/${branch}`,
      sha: commit.sha,
    });
  }
  console.log(`OK commit=${commit.sha}`);
  console.log(`https://github.com/${owner}/${repo}/commit/${commit.sha}`);
}

main().catch((err) => {
  console.error(err.stack || err.message);
  process.exit(1);
});
