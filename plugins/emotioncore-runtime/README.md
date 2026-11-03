# EmotionCore Runtime

DSH host bundle that starts and supervises the local EmotionCore service and
maintenance worker.

```text
id: @soulproject/emotioncore-runtime
type: DSH host bundle
service: emotioncoreRuntime
```

## 职责

```text
启动  plugins/emotioncore-service/server.py  :8765
启动  plugins/emotioncore-service/worker.py
每 20 秒检查一次；service/worker 掉了自动拉起
禁用 bundle / 退出 DSH 时结束子进程
```

它不读写 `soulcore.db`，也不注册模型工具。所有记忆逻辑仍在
`plugins/emotioncore-service` 和 `soulcore/` 里。

## 配置

`cordis.patch.yml`：

```yaml
- insert:
    - id: emotioncore-runtime
      name: '@soulproject/emotioncore-runtime'
      config:
        enabled: true
        port: 8765
        pythonPath: python
```

| 字段 | 默认 | 说明 |
| --- | --- | --- |
| `enabled` | `true` | 关闭后 supervisor 不启动任何子进程 |
| `port` | `8765` | EmotionCore HTTP 端口 |
| `pythonPath` | `python` | Python 解释器；也可用 `SOULCORE_PYTHON` |

不要把机器专用 Python 绝对路径提交进仓库；安装时改成自己的路径即可。

## 运行产物

```text
logs/emotioncore-service.out.log
logs/emotioncore-service.err.log
logs/emotioncore-worker.out.log
logs/emotioncore-worker.err.log
data/emotioncore-worker.pid
```

## 常用操作

- 设置页「EmotionCore → 启动链」可以看到 service/worker 状态并重启。
- 代码接口：`service.status()`、`service.restart('service'|'worker'|'all')`。
- 停止 service 时会先结束记录的子进程，再按端口清理旧 supervisor 留下的进程。

## 边界

- 只负责进程生命周期，不负责记忆内容。
- 不做端口转发；QQ 与记忆的 HTTP 调用仍走 `127.0.0.1`。
- 不把 service 暴露到局域网。
