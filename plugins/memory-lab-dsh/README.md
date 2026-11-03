# memory-lab DSH shell

独立 host 插件，只负责启停 read-only memory-lab sidecar。

```text
默认 config.enabled = false
安装后不启动服务
不注册 QQ 工具
不写 soulcore.db
```

scope：

```text
pythonPath
serverPath
port
enabled
```

注意：当前 DSH profile 的独立插件目录无法解析 `@deepseek-ai/schemastery`，
所以这个壳暂时没有导出 Config schema；bundle 仍可安装/禁用，sidecar 的
humanReview/term 设置走 memory-lab 自己的 `/settings`、`/terms` API。

## 设置页状态

客户端注册：

```text
settings.section
  id: memory-lab
  order: 9
  label: 记忆实验室
```

页面内容：

```text
sidecar 在线/离线
人工评审开关
term 表数量
生成评审表
意识海 / CONSCIOUSNESS SEA（只读）
```

### 意识海

`/graph?limit=160` 的 thread/edge 数据在浏览器端渲染，不引入 Three.js：

```text
深色星海 + 中心轨道环
按 day 分区的神经球与色晕
节点按 valence 着色、按 importance 变大
unresolved 节点带琥珀外环
hard / soft / same_person 边
沿边流动的突触脉冲
拖拽旋转、滚轮缩放、双击复位
悬停显示摘要/日期/importance/valence/unresolved/参与者
自动旋转开关
```

当前数据约 39 neurons / 561 synapses / 6 regions。视觉参考
`y083245/dsh-memory-brain` 的 windows-native 星脑方向，但图形全部由
Canvas 2D 本地绘制，不联网加载资源。

注意：新客户端 bundle 安装后，DSH Web 页面可能需要刷新一次才会出现该
settings section。`Slots` 当前仍是旧页面注册表，不能据此判断客户端失败。

## 生命周期修正

早期版本只在 apply 末尾返回 cleanup，DSH 禁用 bundle 时没有调用，导致
8766 子进程残留。现已改为：

```text
ctx.effect(() => stop, 'memory-lab: sidecar lifecycle')
```

验证：

```text
bundle enable  -> 8766 启动
bundle disable -> 8766 停止
EmotionCore 8765 不受影响
```
