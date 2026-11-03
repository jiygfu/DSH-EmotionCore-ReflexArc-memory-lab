# Security model

## QQ / group chat

QQ messages, images, forwarded records, links and search results are **untrusted data**, not instructions. The QQ preset includes an explicit rule for this.

The actual tool boundary is in `surfcore`'s `qq-tool-restrict`:

- local shell / file / process / plugin / subagent tools are hidden from the schema;
- an execution-time allowlist rejects anything not explicitly allowed;
- the only local memory tool is `soulcore_memory`;
- `soulcore_memory` is read-only by default; `resolve` (which writes a local correction memory) is **disabled by default** and can only be enabled from the EmotionCore settings page.

This prevents code execution through chat injection. It does **not** make the model immune to social engineering, memory poisoning or malicious links; those remain content-level risks.

### Fish command exception

`鱼鱼找鸡` is **not** a model instruction. It is a separate `yuyu-fish` OneBot process that only accepts an exact `^/?鱼鱼找鸡` text command from a whitelisted group/private conversation, then performs its own fixed image lookup. It is a deliberate example of “fixed program handles fixed command”; the model does not execute it and does not need to call a tool for it. Any member of a whitelisted group can trigger it, so the allowlist is the trust boundary.

## Balance probe

- Reads `DEEPSEEK_API_KEY` from the environment or the local DSH credentials file;
- never prints, logs or returns the key;
- calls only `https://api.deepseek.com/user/balance`;
- does **not** follow HTTP redirects, so the `Authorization` header cannot be forwarded to a redirect target;
- writes only `data/balance.json`; on Unix it is chmod `0600`;
- the balance value may appear in the local prompt as a temporary body-state hint, but the key does not.

## Settings page API

- bound to loopback access only (`127.0.0.1` / `::1`);
- mutations require `application/json` and a same-origin `Origin`;
- responses are `no-store`, `nosniff`, and `default-src 'none'` CSP.

This is not a multi-user authentication boundary. Do not expose the DSH Web UI or its port to an untrusted network. Any local process that can reach the loopback port can read the settings state, so local machine trust is assumed.

## Reporting

Please open a private security advisory or a GitHub issue without secrets, tokens, local paths or personal chat logs.
