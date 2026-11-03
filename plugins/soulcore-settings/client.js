window.__ModuleLoader__.load({
  id: '@soulproject/soulcore-settings',
  factory(require) {
    const React = require('react')
    const h = React.createElement

    const C = {
      bg: 'var(--dsw-alias-bg-base)',
      layer: 'var(--dsw-alias-bg-layer-1)',
      layer2: 'var(--dsw-alias-bg-layer-2)',
      border: 'var(--dsw-alias-border-l1)',
      text: 'var(--dsw-alias-label-primary)',
      muted: 'var(--dsw-alias-label-secondary)',
      accent: 'var(--dsw-alias-brand-primary)',
      ok: 'var(--dsw-alias-state-success-primary)',
      warn: 'var(--dsw-alias-state-warn-primary)',
      err: 'var(--dsw-alias-state-error-primary)',
    }

    const styles = {
      page: { color: C.text, fontSize: 13, lineHeight: 1.55, padding: '2px 0 28px' },
      hero: { display: 'flex', alignItems: 'baseline', justifyContent: 'space-between', gap: 12, marginBottom: 4 },
      title: { fontSize: 18, fontWeight: 650, letterSpacing: '-0.01em' },
      subtitle: { color: C.muted, fontSize: 12.5, marginBottom: 18 },
      grid: { display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(150px, 1fr))', gap: 8, marginBottom: 18 },
      card: { background: C.layer, border: `1px solid ${C.border}`, borderRadius: 10, padding: '10px 12px', minHeight: 62 },
      label: { color: C.muted, fontSize: 11, marginBottom: 5 },
      value: { fontSize: 16, fontWeight: 600, fontVariantNumeric: 'tabular-nums' },
      section: { background: C.layer, border: `1px solid ${C.border}`, borderRadius: 12, padding: '14px 16px', marginBottom: 12 },
      sectionTitle: { fontSize: 13, fontWeight: 650, marginBottom: 2 },
      sectionHint: { color: C.muted, fontSize: 12, marginBottom: 12 },
      row: { display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 16, padding: '10px 0', borderTop: `1px solid ${C.border}` },
      rowFirst: { borderTop: 'none', paddingTop: 2 },
      rowText: { minWidth: 0 },
      rowName: { fontSize: 13 },
      rowDesc: { color: C.muted, fontSize: 11.5, marginTop: 2 },
      input: { width: 260, maxWidth: '100%', background: C.layer2, color: C.text, border: `1px solid ${C.border}`, borderRadius: 7, padding: '6px 8px', fontSize: 12, fontFamily: 'inherit' },
      button: { background: C.accent, color: '#fff', border: 'none', borderRadius: 7, padding: '7px 12px', fontSize: 12, fontWeight: 550, cursor: 'pointer' },
      button2: { background: C.layer2, color: C.text, border: `1px solid ${C.border}`, borderRadius: 7, padding: '7px 12px', fontSize: 12, cursor: 'pointer' },
      buttonRow: { display: 'flex', flexWrap: 'wrap', gap: 8, marginTop: 12 },
      badge: { display: 'inline-flex', alignItems: 'center', gap: 5, fontSize: 11, color: C.muted },
      dot: (color) => ({ width: 7, height: 7, borderRadius: 99, background: color, display: 'inline-block' }),
      pre: { background: C.layer2, border: `1px solid ${C.border}`, borderRadius: 8, padding: 10, maxHeight: 220, overflow: 'auto', whiteSpace: 'pre-wrap', fontSize: 11.5, color: C.muted },
      table: { width: '100%', borderCollapse: 'collapse', fontSize: 11.5 },
      th: { textAlign: 'left', color: C.muted, fontWeight: 500, padding: '6px 6px 6px 0', borderBottom: `1px solid ${C.border}` },
      td: { padding: '6px 6px 6px 0', borderBottom: `1px solid ${C.border}`, verticalAlign: 'top' },
      err: { color: C.err, fontSize: 12, marginTop: 8 },
      ok: { color: C.ok, fontSize: 12, marginTop: 8 },
    }

    async function request(path, options) {
      const res = await fetch(`/soulcore-settings/api/${path}`, {
        cache: 'no-store',
        headers: { 'content-type': 'application/json' },
        ...options,
      })
      const body = await res.json().catch(() => ({ ok: false, error: `HTTP ${res.status}` }))
      if (!res.ok) throw new Error(body?.error || `HTTP ${res.status}`)
      return body
    }

    function Toggle(props) {
      return h('input', {
        type: 'checkbox',
        checked: props.checked === true,
        disabled: props.disabled,
        onChange: (event) => props.onChange(event.target.checked),
        style: { width: 16, height: 16, cursor: props.disabled ? 'default' : 'pointer', accentColor: C.accent },
      })
    }

    function Row(props) {
      return h('div', { style: { ...styles.row, ...(props.first ? styles.rowFirst : {}) } },
        h('div', { style: styles.rowText },
          h('div', { style: styles.rowName }, props.name),
          props.desc ? h('div', { style: styles.rowDesc }, props.desc) : null,
        ),
        props.children,
      )
    }

    function Section(props) {
      const [data, setData] = React.useState(null)
      const [draft, setDraft] = React.useState({})
      const [busy, setBusy] = React.useState('')
      const [notice, setNotice] = React.useState({ kind: '', text: '' })
      const [query, setQuery] = React.useState('AI')
      const [layerFilter, setLayerFilter] = React.useState('all')
      const [layerQuery, setLayerQuery] = React.useState('跑团')
      const [episodeId, setEpisodeId] = React.useState('')
      const [memoryId, setMemoryId] = React.useState('')
      const [personQq, setPersonQq] = React.useState('')

      const refresh = React.useCallback(async () => {
        setBusy('refresh')
        try {
          const next = await request('state')
          setData(next)
          setDraft(next.settings || {})
        } catch (error) {
          setNotice({ kind: 'err', text: String(error?.message || error) })
        } finally {
          setBusy('')
        }
      }, [])

      React.useEffect(() => { void refresh() }, [refresh])

      const set = (key, value) => setDraft((prev) => ({ ...prev, [key]: value }))

      async function doAction(action, extra = {}) {
        setBusy(action)
        setNotice({ kind: '', text: '' })
        try {
          const result = await request('action', {
            method: 'POST',
            body: JSON.stringify({ action, ...extra }),
          })
          if (result.settings) {
            setDraft(result.settings)
            setData((prev) => prev ? { ...prev, settings: result.settings } : prev)
          }
          if (action !== 'save') await refresh()
          setNotice({ kind: 'ok', text: result.message || '完成' })
          if (result.output) setData((prev) => prev ? { ...prev, lastOutput: result.output } : prev)
        } catch (error) {
          setNotice({ kind: 'err', text: String(error?.message || error) })
        } finally {
          setBusy('')
        }
      }

      const settings = draft
      const status = data
      const toolOk = status?.toolRegistered === true
      const dbOk = status?.db?.exists === true
      const sidecar = status?.sidecar || {}
      const fish = status?.fish || {}
      const fishOn = settings.fishRunner === true
      const memory = status?.memory || {}
      const caps = status?.capabilities || {}
      const body = status?.body || {}
      const bodyRaw = body.raw || {}
      const balance = status?.balance || {}
      const ftsOk = Number(memory.fts_rows || 0) > 0
      const l2Ok = status?.episodeIndex?.exists === true
      const memCount = Number(memory.memories || 0)
      const episodeCount = Number(memory.episodes || 0)
      const layerCalls = Array.isArray(status?.layerCalls) ? status.layerCalls : []
      const legacyCalls = layerCalls.length
        ? []
        : (Array.isArray(status?.calls) ? status.calls : []).map((c) => ({ ...c, layer: '旧工具', op: c.mode || 'memory_tool' }))
      const allLayerCalls = layerCalls.length ? layerCalls : legacyCalls
      const visibleCalls = layerFilter === 'all'
        ? allLayerCalls
        : allLayerCalls.filter((c) => String(c.layer || '') === layerFilter)

      return h('div', { style: styles.page },
        h('div', { style: styles.hero },
          h('div', { style: styles.title }, 'EmotionCore 记忆与潜意识'),
          h('div', { style: styles.badge },
            h('span', { style: styles.dot(toolOk ? C.ok : C.warn) }),
            toolOk ? '记忆工具在线' : '记忆工具未注册',
          ),
        ),
        h('div', { style: styles.subtitle }, `EmotionCore for DSH / SurfCore · v${status?.version || '0.3.1'}：本地记忆、评价、L2 事件索引与系统状态。原文由 SurfCore 保存，EmotionCore 只做增强；内部兼容 ID 仍为 soulcore。`),

        h('div', { style: styles.section, key: 'startup-chain' },
          h('div', { style: styles.sectionTitle }, '启动链 / 运行与睡眠'),
          h('div', { style: styles.sectionHint }, '按从协议端到本地记忆的顺序排列。绿色=在线；停止会真的结束进程。QQ 侧的 OneBot 连接由「QQ 控制台」管理。'),
          h(Row, { first: true, name: 'SnowLuma 协议端', desc: `HTTP ${status?.runtime?.protocol?.httpPort || 3000} · WS ${status?.runtime?.protocol?.wsPort || 3001} · ${status?.runtime?.protocol?.root || '未配置目录'}` },
            h('span', { style: { ...styles.badge, color: status?.runtime?.protocol?.running ? C.ok : C.muted } },
              h('span', { style: styles.dot(status?.runtime?.protocol?.running ? C.ok : C.err) }),
              status?.runtime?.protocol?.running
                ? (status?.runtime?.protocol?.online ? '运行中 · QQ 在线' : '运行中 · QQ 未登录')
                : '未运行'),
            h('button', {
              style: styles.button2, disabled: !!busy,
              onClick: () => {
                const on = !status?.runtime?.protocol?.running
                if (!on && !window.confirm('停止 SnowLuma？QQ 会立刻收发不到消息。')) return
                void doAction('snowluma', { on })
              },
            }, busy === 'snowluma' ? '处理中…' : (status?.runtime?.protocol?.running ? '停止' : '启动'))),

          h(Row, { name: 'DSH OneBot 连接', desc: '入站消息从 SnowLuma WS 进入 DSH；断开时先看 QQ 控制台的 OneBot 页。' },
            h('span', { style: { ...styles.badge, color: status?.runtime?.onebot?.linked ? C.ok : C.muted } },
              h('span', { style: styles.dot(status?.runtime?.onebot?.linked ? C.ok : C.err) }),
              status?.runtime?.onebot?.linked ? '已连接' : '未连接'),
            h('span', { style: { ...styles.badge, color: status?.runtime?.onebot?.qqLoggedIn === false ? C.err : C.muted } },
              status?.runtime?.onebot?.qqLoggedIn === true ? 'QQ 已登录' : status?.runtime?.onebot?.qqLoggedIn === false ? 'QQ 未登录' : 'QQ 未知')),

          h(Row, { name: 'EmotionCore 服务', desc: `自动启动 · 127.0.0.1:${status?.runtime?.emotioncore?.port || 8765} · worker ${status?.runtime?.emotioncore?.worker?.pid ? `pid ${status.runtime.emotioncore.worker.pid}` : '未运行'}` },
            h('span', { style: { ...styles.badge, color: status?.runtime?.emotioncore?.service?.healthy ? C.ok : C.err } },
              h('span', { style: styles.dot(status?.runtime?.emotioncore?.service?.healthy ? C.ok : C.err) }),
              status?.runtime?.emotioncore?.service?.healthy ? 'healthy' : 'down'),
            h('div', { style: { display: 'flex', gap: 6 } },
              h('button', {
                style: styles.button2, disabled: !!busy,
                onClick: () => {
                  const healthy = status?.runtime?.emotioncore?.service?.healthy
                  if (healthy && !window.confirm('停止 EmotionCore 服务？聊天上下文会暂时不可用。')) return
                  void doAction('runtime', { target: 'service', op: healthy ? 'stop' : 'start' })
                },
              }, busy === 'runtime' ? '处理中…' : (status?.runtime?.emotioncore?.service?.healthy ? '停止' : '启动')),
              h('button', {
                style: styles.button2, disabled: !!busy,
                onClick: () => { if (!window.confirm('重启 EmotionCore 服务？')) return; void doAction('runtime', { target: 'service', op: 'restart' }) },
              }, '重启'))),

          h(Row, { name: 'EmotionCore 维护 worker', desc: '自动启动；负责每日睡眠整理、评价、事件与线程收尾，按下面的时间跑。' },
            h('span', { style: { ...styles.badge, color: status?.runtime?.emotioncore?.worker?.alive ? C.ok : C.err } },
              h('span', { style: styles.dot(status?.runtime?.emotioncore?.worker?.alive ? C.ok : C.err) }),
              status?.runtime?.emotioncore?.worker?.alive ? `运行中 · pid ${status.runtime.emotioncore.worker.pid}` : '未运行'),
            h('button', {
              style: styles.button2, disabled: !!busy,
              onClick: () => {
                const alive = status?.runtime?.emotioncore?.worker?.alive
                if (alive && !window.confirm('停止维护 worker？自动睡眠整理会暂停。')) return
                void doAction('runtime', { target: 'worker', op: alive ? 'stop' : 'start' })
              },
            }, busy === 'runtime' ? '处理中…' : (status?.runtime?.emotioncore?.worker?.alive ? '停止' : '启动'))),

          h(Row, { name: 'memory-lab', desc: '只读实验 sidecar；不影响 QQ 主链，也不写 soulcore.db。' },
            h('span', { style: { ...styles.badge, color: status?.runtime?.memoryLab?.healthy ? C.ok : C.muted } },
              h('span', { style: styles.dot(status?.runtime?.memoryLab?.healthy ? C.ok : C.err) }),
              status?.runtime?.memoryLab?.healthy ? '在线' : '离线')),

          h(Row, { name: 'DSH 启动时自动拉起 SnowLuma', desc: '只在本机 3000 未响应时启动；SnowLuma 自身会脱离 DSH 进程，DSH 退出不会带走它。' },
            h(Toggle, {
              checked: settings.snowlumaAutoStart !== false, disabled: !!busy,
              onChange: (v) => { set('snowlumaAutoStart', v); void doAction('save', { settings: { ...settings, snowlumaAutoStart: v } }) },
            })),

          h('div', { style: { borderTop: `1px solid ${C.border}`, marginTop: 10, paddingTop: 10 } },
            h('div', { style: { ...styles.sectionTitle, marginBottom: 2 } }, '睡眠整理'),
            h('div', { style: { ...styles.sectionHint, marginBottom: 8 } }, '自动睡眠由 worker 做纯本地 daily_cycle，不告别、不轮换。手动「日结 daily」和「完整睡眠 sleep」都会走现有流程，可能触发告别/轮换，执行前会确认。'),
            h(Row, { first: true, name: '自动睡眠整理', desc: `每天 ${String(settings.sleepHour ?? 4).padStart(2, '0')}:00 由维护 worker 执行纯本地整理；关闭后仍可手动整理。` },
              h(Toggle, {
                checked: settings.sleepAuto !== false, disabled: !!busy,
                onChange: (v) => { set('sleepAuto', v); void doAction('sleep-schedule', { auto: v, hour: Number(settings.sleepHour ?? 4) }) },
              })),
            h(Row, { name: '执行时间', desc: '0–23 点，本地时区。' },
              h('input', {
                type: 'number', min: 0, max: 23, value: settings.sleepHour ?? 4,
                style: { ...styles.input, width: 72 }, disabled: !!busy,
                onChange: (e) => set('sleepHour', Number(e.target.value)),
              }),
              h('button', {
                style: styles.button2, disabled: !!busy,
                onClick: () => void doAction('sleep-schedule', { auto: settings.sleepAuto !== false, hour: Number(settings.sleepHour ?? 4) }),
              }, '保存时间')),
            h(Row, { name: '最近一次完整睡眠', desc: status?.lastSleep ? `${status.lastSleep.day || ''} · ${status.lastSleep.generatedAt || ''}` : '还没有睡眠记录' },
              h('span', { style: styles.badge }, `今天 ${memory.sleep_runs_today ?? 0} 次`)),
            h('div', { style: styles.buttonRow },
              h('button', {
                style: styles.button2, disabled: !!busy,
                onClick: () => { if (!window.confirm('执行日结 daily？会走现有告别/轮换逻辑。')) return; void doAction('sleep', { mode: 'daily' }) },
              }, busy === 'sleep' ? '整理中…' : '日结 daily'),
              h('button', {
                style: styles.button2, disabled: !!busy,
                onClick: () => { if (!window.confirm('执行完整睡眠整理？会走告别与会话轮换。')) return; void doAction('sleep', { mode: 'full' }) },
              }, busy === 'sleep' ? '整理中…' : '完整睡眠整理'))),
        ),

        h('div', { style: styles.grid },
          h('div', { style: styles.card }, h('div', { style: styles.label }, '长期记忆'), h('div', { style: { ...styles.value, color: memCount ? C.ok : C.warn } }, memCount ? `${memCount} 条` : '—')),
          h('div', { style: styles.card }, h('div', { style: styles.label }, 'FTS5 索引'), h('div', { style: { ...styles.value, color: ftsOk ? C.ok : C.warn } }, ftsOk ? `${memory.fts_rows} 条` : '未建立')),
          h('div', { style: styles.card }, h('div', { style: styles.label }, '事件索引'), h('div', { style: styles.value }, `${episodeCount} 个`)),
          h('div', { style: styles.card }, h('div', { style: styles.label }, 'L2 事件卡'), h('div', { style: { ...styles.value, color: l2Ok ? C.ok : C.muted } }, l2Ok ? '已生成' : '未生成')),
          h('div', { style: styles.card }, h('div', { style: styles.label }, 'API 余额'), h('div', { style: styles.value }, balance.balance == null ? '—' : `${balance.balance} ${balance.currency || 'CNY'}`)),
          h('div', { style: styles.card }, h('div', { style: styles.label }, '鱼鱼找鸡'), h('div', { style: { ...styles.value, color: fish.running ? C.ok : C.muted } }, fish.running ? '运行中' : '未运行')),
        ),

        h('div', { style: styles.section },
          h('div', { style: styles.sectionTitle }, '运行状态'),
          h('div', { style: styles.sectionHint }, '本地库与系统状态；私聊/群聊共用同一套长期记忆，会话窗口分开只是聊天记录分开。'),
          h(Row, { first: true, name: '记忆分布', desc: `private ${memory.by_scope?.private || 0} · group ${memory.by_scope?.group || 0} · pet ${memory.by_scope?.pet || 0} · 其他 ${Math.max(0, memCount - (memory.by_scope?.private || 0) - (memory.by_scope?.group || 0) - (memory.by_scope?.pet || 0))}` },
            h('span', { style: styles.badge }, `status: ${memory.by_status?.active || 0} active`)),
          h(Row, { name: '记忆索引', desc: 'FTS5 全文索引，纯 SQLite；不调用模型。' },
            h('div', { style: { display: 'flex', gap: 8, alignItems: 'center' } },
              h('span', { style: styles.badge }, ftsOk ? '可用' : '缺失'),
              h('button', { style: styles.button2, disabled: !!busy, onClick: () => void doAction('rebuild-fts') }, busy === 'rebuild-fts' ? '重建中…' : '重建 FTS'))),
          h(Row, { name: 'L2 事件索引', desc: '按天生成 episode 索引；静态卡会保留私聊/群聊各至少一张。' },
            h('div', { style: { display: 'flex', gap: 8, alignItems: 'center' } },
              h('span', { style: styles.badge }, l2Ok ? `${Math.round((status.episodeIndex.bytes || 0) / 1024)} KB` : '未生成'),
              h('button', { style: styles.button2, disabled: !!busy, onClick: () => void doAction('episode-cards') }, busy === 'episode-cards' ? '生成中…' : '重建 L2'))),
          h(Row, { name: '技能清单', desc: status?.skillManifest?.exists ? '本会话首次唤醒注入一次；之后按需打开，不重复占预算。' : '未生成' },
            h('span', { style: styles.badge }, status?.skillManifest?.exists ? `${Math.round((status.skillManifest.bytes || 0) / 1024)} KB` : '未生成')),
          h(Row, { name: '评价/问题队列', desc: `待评价 ${memory.pending_appraisals ?? 0} 条 · 待确认问题 ${memory.pending_questions ?? 0} 个` },
            h('span', { style: styles.badge }, (memory.pending_appraisals || memory.pending_questions) ? '有待处理' : '已清空')),
          h(Row, { name: '睡醒交接', desc: status?.handoff?.exists ? 'bootstrap 读取的确定性交接简报；不是新摘要。' : '尚未生成；下次 sleep/daily 后写入。' },
            h('span', { style: styles.badge }, status?.handoff?.exists ? `${Math.round((status.handoff.bytes || 0) / 1024)} KB` : '未生成')),
          h(Row, { name: '睡眠次数', desc: `今天已记录 ${memory.sleep_runs_today ?? 0} 次睡眠；下次 sleep/daily 会累加。` },
            h('span', { style: styles.badge }, (memory.sleep_runs_today || 0) ? `${memory.sleep_runs_today} 次` : '今天还没有')),
          h(Row, { name: '身体状态（临时）', desc: `CPU ${bodyRaw.cpu_pct ?? '—'}% · 内存 ${bodyRaw.mem_pct ?? '—'}% · 余额 ${bodyRaw.balance ?? '—'}` },
            h('span', { style: styles.badge }, body.temporary_only ? '只影响语气，不写 P' : '未刷新')),
          h(Row, { name: '睡眠收尾', desc: status?.sleep?.enabled ? String(status.sleep.message || '已启用') : '未启用' },
            h('span', { style: styles.badge }, status?.sleep?.enabled ? '睡前说一句' : '关闭')),
          h(Row, { name: '会话预算', desc: status?.budget?.enabled ? `cacheHit > ${status.budget.maxCacheHit || '—'} 时轮换；每 ${Math.round((status.budget.intervalMs || 0) / 60000)} 分钟检查` : '未启用' },
            h('span', { style: styles.badge }, status?.budget?.enabled ? '轮换中' : '关闭')),
          h(Row, { name: '本地数据库', desc: status?.db?.exists ? `${(status.db.bytes / 1024).toFixed(0)} KB · ${status.settingsPath}` : '未找到' },
            h('span', { style: styles.badge }, dbOk ? '已连接' : '缺失')),
        ),

        h('div', { style: styles.section },
          h('div', { style: styles.sectionTitle }, '上下文与能力'),
          h('div', { style: styles.sectionHint }, '改完保存或直接切换；Soul-Bridge 下一次读取即生效。L2/inject 关闭后不注入对应内容。'),
          h(Row, { first: true, name: 'L2 事件卡注入', desc: '睡眠后首次唤醒注入事件索引；关闭则只保留记忆卡回退。' },
            h(Toggle, { checked: caps.l2 === true, disabled: !!busy, onChange: (v) => void doAction('capability', { key: 'l2', value: v }) })),
          h(Row, { name: 'EmotionCore 上下文注入', desc: 'P、身体状态、技能清单等系统上下文；关闭后不注入。' },
            h(Toggle, { checked: caps.inject === true, disabled: !!busy, onChange: (v) => void doAction('capability', { key: 'inject', value: v }) })),
          h(Row, { name: '记忆卡回退', desc: 'L2 没有可用卡时，回退到 SurfCore 的完整记忆卡。' },
            h(Toggle, { checked: caps.memory_prompt === true, disabled: !!busy, onChange: (v) => void doAction('capability', { key: 'memory_prompt', value: v }) })),
          h(Row, { name: 'QQ 能力', desc: 'QQ 桥接/群聊/私聊能力开关。' },
            h(Toggle, { checked: caps.qq === true, disabled: !!busy, onChange: (v) => void doAction('capability', { key: 'qq', value: v }) })),
          h(Row, { name: '桌宠能力', desc: '桌宠 UI；当前未启用时不注入相关 prompt。' },
            h(Toggle, { checked: caps.pet === true, disabled: !!busy, onChange: (v) => void doAction('capability', { key: 'pet', value: v }) })),
          h(Row, { name: 'B 站能力', desc: 'B 站观察/记忆；关闭时不注入 B 站 prompt。' },
            h(Toggle, { checked: caps.bili === true, disabled: !!busy, onChange: (v) => void doAction('capability', { key: 'bili', value: v }) })),
        ),

        h('div', { style: styles.section },
          h('div', { style: styles.sectionTitle }, '功能开关'),
          h('div', { style: styles.sectionHint }, '改完保存，Soul-Bridge 下一次调用即读取新值；记忆查询默认跨私聊/群聊。'),
          h(Row, { first: true, name: '记忆查询工具', desc: '允许 agent 调用 soulcore_memory 查本地长期记忆（默认全局库）。' },
            h(Toggle, { checked: settings.memoryTool !== false, onChange: (v) => set('memoryTool', v) })),
          h(Row, { name: '允许模型写修正记忆', desc: '旧 resolve 入口；新 EmotionCore 默认不向 QQ 暴露写修正。' },
            h(Toggle, { checked: settings.memoryResolve === true, onChange: (v) => set('memoryResolve', v) })),
          h(Row, { name: '调试：overview 总览', desc: '仅在重载 soul-bridge 后把 overview 暴露给模型；默认关闭。普通聊天不需要它。' },
            h(Toggle, { checked: settings.memoryOverview === true, onChange: (v) => set('memoryOverview', v) })),
          h(Row, { name: '影子检索日志', desc: '监听模型请求，把本地召回与 P 写入 shadow 日志；不改写请求。' },
            h(Toggle, { checked: settings.shadowEnabled !== false, onChange: (v) => set('shadowEnabled', v) })),
          h(Row, { name: '影子检索写回标记', desc: '命中时更新 familiarity / trigger；默认关闭。' },
            h(Toggle, { checked: settings.mark === true, onChange: (v) => set('mark', v) })),
        ),

        h('div', { style: styles.section },
          h('div', { style: styles.sectionTitle }, '运行参数'),
          h('div', { style: styles.sectionHint }, '路径和超时只影响本机 EmotionCore；不会发到 QQ。'),
          h(Row, { first: true, name: 'Python 路径', desc: '用于记忆查询、评价和 sidecar 导出。' },
            h('input', { style: styles.input, value: settings.pythonPath || '', onChange: (e) => set('pythonPath', e.target.value) })),
          h(Row, { name: 'SQLite 路径', desc: '本地索引与评价库。' },
            h('input', { style: styles.input, value: settings.dbPath || '', onChange: (e) => set('dbPath', e.target.value) })),
          h(Row, { name: 'Node 路径', desc: '仅 mode=surfcore 的显式兼容召回会用到；默认检索不经过 SurfCore 内置记忆。' },
            h('input', { style: styles.input, value: settings.nodePath || 'node', onChange: (e) => set('nodePath', e.target.value) })),
          h(Row, { name: '单次超时（ms）', desc: '工具/影子调用的上限。' },
            h('input', { style: { ...styles.input, width: 120 }, type: 'number', min: 1000, max: 120000, value: settings.timeoutMs || 4000, onChange: (e) => set('timeoutMs', Number(e.target.value)) })),
          h(Row, { name: '影子最大并发', desc: '同时运行的影子检索数量。' },
            h('input', { style: { ...styles.input, width: 100 }, type: 'number', min: 1, max: 8, value: settings.maxInflight || 2, onChange: (e) => set('maxInflight', Number(e.target.value)) })),
        ),

        h('div', { style: styles.section },
          h('div', { style: styles.sectionTitle }, '鱼鱼找鸡（QQ 反查）'),
          h('div', { style: styles.sectionHint }, '随 EmotionCore / SurfCore 一起启停。它只连 SnowLuma 的 OneBot，只理 SurfCore 白名单里的群和私聊。用法：引用一张图，发「鱼鱼找鸡」。'),
          h(Row, { first: true, name: '运行器随 EmotionCore 启停', desc: fish.running ? `运行中 · pid ${fish.pid}` : '未运行（关掉开关或退出 DSH 就会停）' },
            h(Toggle, {
              checked: fishOn,
              disabled: !!busy,
              onChange: (value) => void doAction('fish', { on: value }),
            })),
          h('div', { style: { display: 'flex', gap: 8, marginTop: 10, alignItems: 'center' } },
            h('button', { style: styles.button2, disabled: !!busy, onClick: () => void refresh() }, '刷新状态'),
            h('span', { style: styles.badge },
              h('span', { style: styles.dot(fish.running ? C.ok : C.muted) }),
              fish.running ? `运行中 · pid ${fish.pid}` : '未运行'),
          ),
          fish.logTail ? h('pre', { style: styles.pre }, fish.logTail) : null,
        ),

        h('div', { style: styles.section },
          h('div', { style: styles.sectionTitle }, '运行与测试'),
          h('div', { style: styles.sectionHint }, '这些按钮执行本机 Python，不经过 QQ API。评价可能较慢。'),
          h('div', { style: styles.buttonRow },
            h('button', { style: styles.button, disabled: !!busy, onClick: () => void doAction('save') }, busy === 'save' ? '保存中…' : '保存设置'),
            h('button', { style: styles.button2, disabled: !!busy, onClick: () => void doAction('export') }, busy === 'export' ? '导出中…' : '导出增强 sidecar'),
            h('button', { style: styles.button2, disabled: !!busy, onClick: () => void doAction('appraise', { limit: 1 }) }, busy === 'appraise' ? '评价中…' : '运行一次评价'),
            h('button', { style: styles.button2, disabled: !!busy, onClick: () => void doAction('repair') }, busy === 'repair' ? '回填中…' : '修复旧身份'),
            h('button', { style: styles.button2, disabled: !!busy, onClick: () => void refresh() }, '刷新状态'),
          ),
          h('div', { style: { display: 'flex', gap: 8, marginTop: 10 } },
            h('input', { style: { ...styles.input, width: 220 }, value: query, onChange: (e) => setQuery(e.target.value), placeholder: '测试查询关键词' }),
            h('button', { style: styles.button2, disabled: !!busy, onClick: () => void doAction('test', { query }) }, busy === 'test' ? '查询中…' : '测试记忆查询'),
          ),
          notice.text ? h('div', { style: notice.kind === 'err' ? styles.err : styles.ok }, notice.text) : null,
          data?.lastOutput ? h('pre', { style: styles.pre }, data.lastOutput) : null,
        ),

        h('div', { style: styles.section },
          h('div', { style: styles.sectionTitle }, '记忆调用记录（分层）'),
          h('div', { style: styles.sectionHint }, 'L5=唤醒组装（每轮自动 /context）；L3=事件索引（recall query）；L2=单条原文/事件详情；L4=人物关系。'
            + '旧记录只来自 soulcore_memory，所以以前只看到 recall 不代表没有自动记忆注入。'),
          h('div', { style: styles.buttonRow },
            ...[['all', '全部'], ['L5', 'L5 唤醒'], ['L4', 'L4 人物'], ['L3', 'L3 索引'], ['L2', 'L2 原文']].map(([value, label]) =>
              h('button', {
                key: value,
                style: { ...styles.button2, borderColor: layerFilter === value ? C.accent : C.border, color: layerFilter === value ? C.accent : C.text },
                onClick: () => setLayerFilter(value),
              }, label)),
            h('span', { style: styles.rowDesc }, `共 ${allLayerCalls.length} 条`),
          ),
          h('div', { style: { ...styles.buttonRow, marginTop: 10 } },
            h('input', { style: { ...styles.input, width: 220 }, value: layerQuery, onChange: (e) => setLayerQuery(e.target.value), placeholder: 'L3 查询关键词' }),
            h('button', { style: styles.button2, disabled: !!busy, onClick: () => void doAction('layer-call', { layer: 'L3', query: layerQuery }) }, '调 L3 索引'),
            h('button', { style: styles.button2, disabled: !!busy, onClick: () => void doAction('layer-call', { layer: 'L5', text: layerQuery }) }, '调 L5 唤醒'),
            h('button', { style: styles.button2, disabled: !!busy, onClick: () => void doAction('layer-call', { layer: 'L4', qq: personQq }) }, '调 L4 人物'),
            h('input', { style: { ...styles.input, width: 140 }, value: personQq, onChange: (e) => setPersonQq(e.target.value), placeholder: '人物 QQ' }),
          ),
          h('div', { style: { ...styles.buttonRow, marginTop: 8 } },
            h('input', { style: { ...styles.input, width: 220 }, value: episodeId, onChange: (e) => setEpisodeId(e.target.value), placeholder: 'episode_id（L3 详情）' }),
            h('button', { style: styles.button2, disabled: !!busy, onClick: () => void doAction('layer-call', { layer: 'L2', episode_id: episodeId }) }, '调 L2 事件详情'),
            h('input', { style: { ...styles.input, width: 220 }, value: memoryId, onChange: (e) => setMemoryId(e.target.value), placeholder: 'memory_id（L2 原文）' }),
            h('button', { style: styles.button2, disabled: !!busy, onClick: () => void doAction('layer-call', { layer: 'L2', memory_id: memoryId }) }, '调 L2 原文'),
          ),
          visibleCalls.length === 0
            ? h('div', { style: styles.rowDesc }, '还没有分层调用记录；等下一轮 /context 或点上面的按钮。')
            : h('table', { style: styles.table },
              h('thead', null, h('tr', null,
                h('th', { style: styles.th }, '时间'),
                h('th', { style: styles.th }, '层级'),
                h('th', { style: styles.th }, '入口'),
                h('th', { style: styles.th }, '范围 / id'),
                h('th', { style: styles.th }, '结果'),
                h('th', { style: styles.th }, '字符'),
              )),
              h('tbody', null, visibleCalls.map((c, i) => h('tr', { key: i },
                h('td', { style: styles.td }, String(c.at || '').replace('T', ' ').slice(0, 19)),
                h('td', { style: styles.td }, h('span', { style: { color: C.accent, fontWeight: 600 } }, c.layer || '—')),
                h('td', { style: styles.td }, `${c.op || '—'}${c.source ? ` / ${c.source}` : ''}`),
                h('td', { style: styles.td }, [c.scope, c.groupId, c.episode_id, c.memory_id, c.query].filter(Boolean).join(' · ') || '—'),
                h('td', { style: styles.td }, c.result_count == null ? (c.ok === false ? 'fail' : 'ok') : String(c.result_count)),
                h('td', { style: styles.td }, c.chars == null ? '—' : String(c.chars)),
              ))),
            ),
        ),
      )
    }

    return {
      inject: ['slots'],
      apply(ctx) {
        ctx.slots.inject('settings.section', () => ctx.slots.register({
          name: 'settings.section',
          id: 'soulcore',
          order: 8,
          label: 'EmotionCore',
        }, Section))
      },
    }
  },
})
