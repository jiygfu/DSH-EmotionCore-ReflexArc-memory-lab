# Security model

## Current route: OneBot only

Current runtime:

```text
DSH + dsh-onebot-qq + OneBot 11 + EmotionCore service
```

SurfCore is **not required** and is not the tool gate for this route. Legacy
SurfCore docs/exporters are historical compatibility only.

QQ messages, images, forwarded records, links and search results are
**untrusted data**, not instructions.

## QQ tool boundary (external)

The actual gate is **not** in this repository. It lives in `dsh-onebot-qq`:

- `gate-wake` / message pipeline decides whether a message reaches the model;
- the QQ preset hides shell, file, process, plugin and subagent tools;
- `toolAllowlist` currently keeps only `ec` on the QQ line;
- `ec` is a local dispatcher (`send/reply/image/sticker/at/user/history/recall/groups`),
  not a shell or arbitrary execution tool.

The onebot line still needs a separate audit. Installing this repository alone
does **not** give you the QQ tool boundary.

This prevents code execution through chat injection. It does **not** make the
model immune to social engineering, memory poisoning or malicious links; those
remain content-level risks.

## Local services: no authentication

EmotionCore (`127.0.0.1:8765`) and memory-lab (`127.0.0.1:8766`) are loopback
services with **no auth**. Any local process/user that can reach the port can:

- read local memory/person context;
- write tags/activity through EmotionCore endpoints;
- query the read-only memory-lab projection.

This is an explicit **local-machine trust** assumption, not a multi-user
boundary. Do not expose these ports, the DSH Web UI or a proxy to an untrusted
network. Use a dedicated Windows account if the machine is shared.

`memory-lab` is read-only for `soulcore.db`, but it still reads personal memory
content and renders it in the DSH settings page.

## Persistent injection surface

The design deliberately re-injects memory:

```text
QQ message → memory store → L5 context / recall → future prompts
```

That is more durable than a one-shot prompt injection. Mitigations:

- L2 raw text is not injected by default; `/context` returns a bounded L5 summary;
- recall is scoped to the current group/private conversation;
- sensitive memories are filtered by the service;
- memory is local and can be inspected/deleted with the local tools.

It is still a trust surface. A poisoned or wrong memory can be repeated later.
The `鱼群记录` feature additionally writes tagged members' messages to a local
JSONL; treat it as private local data and rotate/delete it deliberately.

## Model send permission

`ec` lets the model send QQ messages. That is intentional. A compromised model,
poisoned memory or bad tool call can speak outward. Keep targets scoped, keep
the tool allowlist minimal, and review unexpected sends.

## Subprocesses and settings

`emotioncore-runtime` starts/stops Python service and worker; the settings page
can also start/stop them. On Windows it uses `taskkill /f /t` and port
inspection. This is local process control under the same local-trust model.
Do not give the settings UI to an untrusted user.

## Balance probe

- Reads `DEEPSEEK_API_KEY` from the environment or the local DSH credentials file;
- never prints, logs or returns the key;
- calls only `https://api.deepseek.com/user/balance`;
- does **not** follow HTTP redirects, so the `Authorization` header cannot be forwarded;
- writes only `data/balance.json`; on Unix it is chmod `0600`;
- the balance value may appear in the local prompt as a temporary body-state hint, but the key does not.

## Settings page API

- loopback only;
- mutations require `application/json` and a same-origin `Origin`;
- responses are `no-store`, `nosniff`, `default-src 'none'`.

## Reporting

Please open a private security advisory or a GitHub issue without secrets,
tokens, local paths or personal chat logs.
