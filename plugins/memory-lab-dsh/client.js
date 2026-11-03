window.__ModuleLoader__.load({
  id: '@soulproject/memory-lab',
  factory(require) {
    const React = require('react')
    const h = React.createElement
    const { useEffect, useRef, useState } = React
    const BASE = 'http://127.0.0.1:8766'
    const TAU = Math.PI * 2

    const styles = {
      wrap: { padding: '16px 18px', display: 'flex', flexDirection: 'column', gap: '12px', color: 'var(--dsh-text, #dbe9ff)' },
      card: { border: '1px solid var(--dsh-border, #2a3a55)', borderRadius: '10px', padding: '12px 14px', background: 'var(--dsh-panel, rgba(20,32,51,.55))' },
      row: { display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: '12px', padding: '5px 0' },
      muted: { opacity: 0.65, fontSize: '12px' },
      btn: { border: '1px solid var(--dsh-border, #2a3a55)', borderRadius: '7px', padding: '5px 10px', background: 'transparent', color: 'inherit', cursor: 'pointer' },
      code: { fontFamily: 'monospace', fontSize: '12px', opacity: 0.8, wordBreak: 'break-all' },
      brain: {
        position: 'relative', overflow: 'hidden', borderRadius: 16,
        border: '1px solid rgba(93,160,255,.28)',
        background: 'radial-gradient(ellipse at 50% 40%, #0b1b35 0%, #050b18 55%, #02040a 100%)',
        boxShadow: 'inset 0 0 80px rgba(46,116,255,.12), 0 12px 42px rgba(0,0,0,.28)',
        minHeight: 420, height: 'clamp(400px, 58vh, 560px)',
        userSelect: 'none', touchAction: 'none',
      },
      canvas: { display: 'block', width: '100%', height: '100%', cursor: 'grab' },
      hud: { position: 'absolute', top: 12, left: 14, right: 14, display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: 10, pointerEvents: 'none' },
      hudTitle: { display: 'flex', flexDirection: 'column', gap: 4, pointerEvents: 'none' },
      hudName: { fontSize: 13, fontWeight: 650, letterSpacing: '.08em', color: '#cfe7ff', textShadow: '0 0 18px rgba(91,214,255,.45)' },
      hudSub: { fontSize: 11, color: 'rgba(174,208,255,.58)', letterSpacing: '.04em' },
      hudChips: { display: 'flex', gap: 6, flexWrap: 'wrap', justifyContent: 'flex-end', pointerEvents: 'none' },
      chip: { padding: '3px 8px', borderRadius: 999, fontSize: 10.5, color: 'rgba(194,225,255,.82)', background: 'rgba(18,44,82,.55)', border: '1px solid rgba(96,158,255,.22)' },
      controls: { position: 'absolute', right: 12, bottom: 12, display: 'flex', gap: 7, alignItems: 'center', zIndex: 2 },
      ctl: { padding: '5px 9px', borderRadius: 8, border: '1px solid rgba(108,170,255,.28)', background: 'rgba(8,20,42,.72)', color: 'rgba(207,231,255,.9)', fontSize: 11, cursor: 'pointer', backdropFilter: 'blur(6px)' },
      tip: { position: 'absolute', zIndex: 5, maxWidth: 300, padding: '10px 12px', borderRadius: 10, background: 'rgba(5,13,28,.92)', border: '1px solid rgba(110,185,255,.32)', boxShadow: '0 12px 32px rgba(0,0,0,.45)', pointerEvents: 'none', backdropFilter: 'blur(10px)' },
      tipTitle: { fontSize: 12, fontWeight: 650, color: '#dff1ff', lineHeight: 1.45, marginBottom: 5 },
      tipMeta: { fontSize: 11, color: 'rgba(168,204,245,.65)', lineHeight: 1.55 },
      empty: { position: 'absolute', inset: 0, display: 'flex', alignItems: 'center', justifyContent: 'center', flexDirection: 'column', gap: 8, color: 'rgba(170,207,255,.55)', fontSize: 12, pointerEvents: 'none' },
    }

    async function call(path, op) {
      const res = await fetch(BASE + path, { ...op, headers: { 'content-type': 'application/json' } })
      const data = await res.json().catch(() => ({}))
      if (!res.ok) throw new Error(data.error || `HTTP ${res.status}`)
      return data
    }

    function hashOf(text) {
      let h = 2166136261
      const s = String(text || '')
      for (let i = 0; i < s.length; i += 1) {
        h ^= s.charCodeAt(i)
        h = Math.imul(h, 16777619)
      }
      return Math.abs(h)
    }

    function clamp(v, a, b) { return Math.max(a, Math.min(b, v)) }
    function rgba(color, a) {
      const src = String(color || '#6fd3ff').trim()
      if (src.startsWith('hsl(')) {
        const parts = src.slice(4, -1).replace(/%/g, '').split(/[\s,]+/).filter(Boolean)
        if (parts.length >= 3) return `hsla(${parts[0]},${parts[1]}%,${parts[2]}%,${a})`
      }
      const s = src.replace('#', '')
      const n = s.length === 3 ? s.split('').map((x) => x + x).join('') : s
      const num = parseInt(n.slice(0, 6), 16)
      if (!Number.isFinite(num)) return `rgba(111,211,255,${a})`
      return `rgba(${(num >> 16) & 255},${(num >> 8) & 255},${num & 255},${a})`
    }

    function nodeColor(n) {
      const v = Number(n.valence) || 0
      const a = Number(n.arousal) || 0
      const hue = v >= 0.06 ? 188 + (1 - clamp(v, 0, .5) / .5) * 14 : (v <= -0.06 ? 338 : 258)
      const light = 62 + clamp(a, 0, 1) * 10
      return `hsl(${hue} 92% ${light}%)`
    }

    const REGION_COLORS = ['#65d9ff', '#a68cff', '#ff8fbe', '#7ee7b0', '#ffd166', '#75b8ff', '#e0a6ff', '#8de7e0']

    function buildScene(data) {
      const rawNodes = Array.isArray(data?.nodes) ? data.nodes : []
      const rawEdges = Array.isArray(data?.edges) ? data.edges : []
      if (!rawNodes.length) return { nodes: [], links: [], regions: [], byId: new Map(), stars: [], t: 0, pulses: [] }
      const days = [...new Set(rawNodes.map((n) => String(n.day || '未知')))]
      days.sort((a, b) => String(a).localeCompare(String(b)))
      const regions = days.map((day, i) => {
        const a = (i / Math.max(1, days.length)) * TAU - Math.PI / 2
        const ring = days.length > 7 ? (i % 2 ? 300 : 235) : 275
        return {
          day,
          color: REGION_COLORS[i % REGION_COLORS.length],
          hub: { x: Math.cos(a) * ring, y: (i % 3 - 1) * 58, z: Math.sin(a) * ring },
          count: 0,
        }
      })
      const byDay = new Map(regions.map((r) => [r.day, r]))
      const nodes = rawNodes.map((n) => {
        const day = String(n.day || '未知')
        const region = byDay.get(day) || regions[0]
        const hsh = hashOf(n.id)
        const ph = ((hsh % 360) / 360) * TAU
        const spread = 36 + (hsh % 74)
        const lift = ((hsh >> 5) % 72) - 36
        region.count += 1
        return {
          data: n,
          id: String(n.id),
          region,
          x: region.hub.x + Math.cos(ph) * spread,
          y: region.hub.y + lift,
          z: region.hub.z + Math.sin(ph) * spread,
          phase: ((hsh >> 9) % 1000) / 1000 * TAU,
          r: 2.8 + clamp(Number(n.importance) || 0, 0, 1) * 7 + Math.min(4, Math.sqrt(Number(n.count) || 1) * 1.35),
          color: nodeColor(n),
          unresolved: clamp(Number(n.unresolved) || 0, 0, 1),
          importance: clamp(Number(n.importance) || 0, 0, 1),
        }
      })
      const byId = new Map(nodes.map((n) => [n.id, n]))
      const links = rawEdges
        .map((e) => ({ ...e, source: String(e.source), target: String(e.target) }))
        .filter((e) => byId.has(e.source) && byId.has(e.target))
        .sort((a, b) => Number(b.weight || 0) - Number(a.weight || 0))
        .slice(0, 360)
        .map((e, i) => ({ ...e, key: `${e.source}:${e.target}:${i}`, a: byId.get(e.source), b: byId.get(e.target) }))
      const strokes = []
      for (let i = 0; i < 150; i += 1) {
        strokes.push({
          x: ((hashOf(`sx${i}`) % 2000) / 1000 - 1),
          y: ((hashOf(`sy${i}`) % 2000) / 1000 - 1),
          z: (hashOf(`sz${i}`) % 1000) / 1000,
          a: (hashOf(`sa${i}`) % 100) / 100,
        })
      }
      return {
        nodes,
        links,
        regions: regions.filter((r) => r.count > 0),
        byId,
        stars: strokes,
        t: 0,
        pulses: links
          .filter((_, i) => i % 6 === 0)
          .slice(0, 48)
          .map((e, i) => ({ edge: e, p: (i % 11) / 11, speed: 0.0011 + (i % 5) * 0.00022 })),
      }
    }

    function project(p, view, w, h) {
      const ca = Math.cos(view.angle)
      const sa = Math.sin(view.angle)
      const ct = Math.cos(view.tilt)
      const st = Math.sin(view.tilt)
      const x1 = p.x * ca - p.z * sa
      const z1 = p.x * sa + p.z * ca
      const y1 = p.y * ct - z1 * st
      const z2 = p.y * st + z1 * ct
      const focal = 760
      const scale = (focal / Math.max(180, z2 + 760)) * view.zoom
      return {
        x: w / 2 + x1 * scale,
        y: h / 2 + y1 * scale,
        s: scale,
        z: z2,
      }
    }

    function drawScene(ctx, scene, view, w, h, hoverId) {
      ctx.setTransform(view.dpr, 0, 0, view.dpr, 0, 0)
      ctx.clearRect(0, 0, w, h)

      const bg = ctx.createRadialGradient(w * .5, h * .42, 8, w * .5, h * .5, Math.max(w, h) * .74)
      bg.addColorStop(0, '#0b1a33')
      bg.addColorStop(.46, '#050d1c')
      bg.addColorStop(1, '#010207')
      ctx.fillStyle = bg
      ctx.fillRect(0, 0, w, h)

      // faint orbital rings, like a brain stem / memory shell
      ctx.save()
      ctx.translate(w / 2, h / 2)
      ctx.rotate(view.angle * .16)
      for (let i = 1; i <= 4; i += 1) {
        ctx.beginPath()
        ctx.ellipse(0, 0, 84 * i, 32 * i, 0, 0, TAU)
        ctx.strokeStyle = `rgba(78,150,255,${0.055 - i * 0.009})`
        ctx.lineWidth = 1
        ctx.stroke()
      }
      ctx.restore()

      // star dust with parallax
      for (const s of scene.stars) {
        const px = w / 2 + ((s.x * w * .62 + view.angle * 24 * (0.3 + s.a)) % (w * 1.1)) - w * .05
        const py = h / 2 + s.y * h * .58 + Math.sin(scene.t * .18 + s.a * 9) * 2
        const alpha = .10 + s.a * .34
        ctx.fillStyle = `rgba(150,205,255,${alpha})`
        ctx.fillRect(px, py, s.z > .7 ? 1.6 : 1, s.z > .7 ? 1.6 : 1)
      }

      const projected = new Map()
      for (const n of scene.nodes) {
        const bob = Math.sin(scene.t * .65 + n.phase) * 2.4
        projected.set(n.id, project({ ...n, y: n.y + bob }, view, w, h))
      }
      const regionProjected = scene.regions.map((r) => ({ ...r, p: project(r.hub, view, w, h) }))

      // region auras
      ctx.globalCompositeOperation = 'lighter'
      for (const r of regionProjected) {
        if (!Number.isFinite(r.p.x)) continue
        const radius = 62 * r.p.s
        const g = ctx.createRadialGradient(r.p.x, r.p.y, 2, r.p.x, r.p.y, radius)
        g.addColorStop(0, rgba(r.color, .085))
        g.addColorStop(.55, rgba(r.color, .026))
        g.addColorStop(1, rgba(r.color, 0))
        ctx.fillStyle = g
        ctx.beginPath()
        ctx.arc(r.p.x, r.p.y, radius, 0, TAU)
        ctx.fill()
      }

      // links
      for (const e of scene.links) {
        const a = projected.get(e.a.id)
        const b = projected.get(e.b.id)
        if (!a || !b) continue
        const weight = clamp(Number(e.weight) || 0, 0, 1)
        const hard = e.decision === 'hard'
        const alpha = .035 + weight * .20
        const mx = (a.x + b.x) / 2 + (b.y - a.y) * .055
        const my = (a.y + b.y) / 2 - (b.x - a.x) * .035
        ctx.beginPath()
        ctx.moveTo(a.x, a.y)
        ctx.quadraticCurveTo(mx, my, b.x, b.y)
        ctx.strokeStyle = hard ? `rgba(101,217,255,${alpha})` : `rgba(178,151,255,${alpha * .8})`
        ctx.lineWidth = .45 + weight * 1.25
        ctx.stroke()
      }

      // traveling synaptic pulses
      for (const pulse of scene.pulses) {
        const a = projected.get(pulse.edge.a.id)
        const b = projected.get(pulse.edge.b.id)
        if (!a || !b) continue
        pulse.p += pulse.speed * (view.auto ? 1 : .72)
        if (pulse.p > 1) pulse.p = 0
        const mx = (a.x + b.x) / 2 + (b.y - a.y) * .055
        const my = (a.y + b.y) / 2 - (b.x - a.x) * .035
        const t = pulse.p
        const x = (1 - t) * (1 - t) * a.x + 2 * (1 - t) * t * mx + t * t * b.x
        const y = (1 - t) * (1 - t) * a.y + 2 * (1 - t) * t * my + t * t * b.y
        const g = ctx.createRadialGradient(x, y, 0, x, y, 7)
        g.addColorStop(0, 'rgba(225,248,255,.95)')
        g.addColorStop(.25, 'rgba(100,220,255,.55)')
        g.addColorStop(1, 'rgba(80,180,255,0)')
        ctx.fillStyle = g
        ctx.beginPath()
        ctx.arc(x, y, 7, 0, TAU)
        ctx.fill()
      }
      ctx.globalCompositeOperation = 'source-over'

      // region labels
      for (const r of regionProjected) {
        if (!Number.isFinite(r.p.x)) continue
        ctx.fillStyle = rgba(r.color, .58)
        ctx.font = '10px ui-monospace, Menlo, Consolas, monospace'
        ctx.fillText(`${r.day.slice(5)} · ${r.count}`, r.p.x + 12, r.p.y - 10)
        ctx.beginPath()
        ctx.arc(r.p.x, r.p.y, 2.2, 0, TAU)
        ctx.fillStyle = rgba(r.color, .8)
        ctx.fill()
      }

      // neurons, sorted by depth
      const ordered = [...scene.nodes].sort((a, b) => (projected.get(a.id)?.z || 0) - (projected.get(b.id)?.z || 0))
      for (const n of ordered) {
        const p = projected.get(n.id)
        if (!p || !Number.isFinite(p.x)) continue
        const hovered = hoverId === n.id
        const r = Math.max(1.4, n.r * p.s * (hovered ? 1.45 : 1))
        const glowR = r * (hovered ? 6.5 : 4.2)
        const glow = ctx.createRadialGradient(p.x, p.y, 0, p.x, p.y, glowR)
        glow.addColorStop(0, rgba(n.color, hovered ? .55 : .34))
        glow.addColorStop(.32, rgba(n.color, hovered ? .22 : .12))
        glow.addColorStop(1, rgba(n.color, 0))
        ctx.fillStyle = glow
        ctx.beginPath()
        ctx.arc(p.x, p.y, glowR, 0, TAU)
        ctx.fill()

        ctx.beginPath()
        ctx.arc(p.x, p.y, r, 0, TAU)
        ctx.fillStyle = n.color
        ctx.globalAlpha = .86
        ctx.fill()
        ctx.globalAlpha = 1

        if (n.unresolved > .42) {
          ctx.beginPath()
          ctx.arc(p.x, p.y, r + 3 + n.unresolved * 3, 0, TAU)
          ctx.strokeStyle = rgba('#ffd166', .18 + n.unresolved * .45)
          ctx.lineWidth = .8
          ctx.stroke()
        }
        if (hovered) {
          ctx.beginPath()
          ctx.arc(p.x, p.y, r + 8, 0, TAU)
          ctx.strokeStyle = 'rgba(230,248,255,.72)'
          ctx.lineWidth = 1
          ctx.stroke()
        }
      }

      // a few labels for the brightest thoughts
      const labeled = [...scene.nodes]
        .filter((n) => n.importance >= .55)
        .sort((a, b) => b.importance - a.importance)
        .slice(0, 6)
      ctx.font = '10px ui-monospace, Menlo, Consolas, monospace'
      for (const n of labeled) {
        const p = projected.get(n.id)
        if (!p) continue
        const label = String(n.data.label || '').slice(0, 22)
        if (!label) continue
        ctx.fillStyle = 'rgba(193,224,255,.48)'
        ctx.fillText(label, p.x + 9, p.y + 3)
      }
    }

    function Graph() {
      const wrapRef = useRef(null)
      const canvasRef = useRef(null)
      const [data, setData] = useState(null)
      const [err, setErr] = useState('')
      const [auto, setAuto] = useState(true)
      const [hover, setHover] = useState(null)
      const view = useRef({
        angle: .34, tilt: -.18, zoom: 1, auto: true, drag: null,
        dpr: 1, w: 0, h: 0, scene: null, hoverId: null, t: 0,
      })

      async function load() {
        try {
          const g = await call('/graph?limit=160')
          setData(g)
          setErr('')
        } catch (e) {
          setErr(e.message)
        }
      }
      useEffect(() => { void load() }, [])
      useEffect(() => { view.current.auto = auto }, [auto])

      useEffect(() => {
        if (!data) return undefined
        const wrap = wrapRef.current
        const canvas = canvasRef.current
        if (!wrap || !canvas) return undefined
        const ctx = canvas.getContext('2d')
        if (!ctx) return undefined
        const scene = buildScene(data)
        view.current.scene = scene
        let raf = 0
        let last = performance.now()

        function resize() {
          const rect = wrap.getBoundingClientRect()
          const dpr = Math.min(2, window.devicePixelRatio || 1)
          const w = Math.max(320, Math.round(rect.width))
          const h = Math.max(300, Math.round(rect.height))
          canvas.width = Math.round(w * dpr)
          canvas.height = Math.round(h * dpr)
          canvas.style.width = '100%'
          canvas.style.height = '100%'
          view.current.w = w
          view.current.h = h
          view.current.dpr = dpr
        }

        const ro = new ResizeObserver(resize)
        ro.observe(wrap)
        resize()

        function frame(now) {
          const v = view.current
          const dt = Math.min(40, now - last)
          last = now
          v.t += dt / 1000
          scene.t = v.t
          if (v.auto && !v.drag) v.angle += dt * 0.000085
          drawScene(ctx, scene, v, v.w, v.h, v.hoverId)
          raf = requestAnimationFrame(frame)
        }
        raf = requestAnimationFrame(frame)
        return () => {
          cancelAnimationFrame(raf)
          ro.disconnect()
          view.current.scene = null
        }
      }, [data])

      function hitTest(clientX, clientY) {
        const wrap = wrapRef.current
        const v = view.current
        if (!wrap || !v.scene || !v.w || !v.h) return null
        const rect = wrap.getBoundingClientRect()
        const mx = clientX - rect.left
        const my = clientY - rect.top
        let best = null
        for (const n of v.scene.nodes) {
          const p = project({ ...n, y: n.y + Math.sin(v.t * .65 + n.phase) * 2.4 }, v, v.w, v.h)
          const r = Math.max(4, n.r * p.s * 1.8)
          const d = Math.hypot(mx - p.x, my - p.y)
          if (d <= r + 7 && (!best || d < best.d)) best = { node: n, d }
        }
        return best ? { ...best, mx, my } : null
      }

      function down(e) {
        const v = view.current
        v.drag = { x: e.clientX, y: e.clientY, angle: v.angle, tilt: v.tilt }
        e.currentTarget.setPointerCapture?.(e.pointerId)
      }

      function move(e) {
        const v = view.current
        if (v.drag) {
          v.angle = v.drag.angle + (e.clientX - v.drag.x) * .007
          v.tilt = clamp(v.drag.tilt + (e.clientY - v.drag.y) * .0045, -.9, .9)
          v.hoverId = null
          setHover((prev) => (prev ? null : prev))
          return
        }
        const hit = hitTest(e.clientX, e.clientY)
        const id = hit?.node?.id || null
        if (id !== v.hoverId) {
          v.hoverId = id
          setHover(hit ? {
            id,
            x: hit.mx,
            y: hit.my,
            node: hit.node.data,
          } : null)
        }
      }

      function up() { view.current.drag = null }
      function leave() {
        view.current.drag = null
        view.current.hoverId = null
        setHover(null)
      }
      function reset() {
        const v = view.current
        v.angle = .34; v.tilt = -.18; v.zoom = 1
      }

      return h('div', { style: styles.brain, ref: wrapRef },
        h('canvas', {
          ref: canvasRef,
          style: styles.canvas,
          onPointerDown: down,
          onPointerMove: move,
          onPointerUp: up,
          onPointerLeave: leave,
          onDoubleClick: reset,
          onWheel: (e) => {
            e.preventDefault()
            view.current.zoom = clamp(view.current.zoom * (e.deltaY > 0 ? .92 : 1.08), .55, 1.9)
          },
        }),
        h('div', { style: styles.hud },
          h('div', { style: styles.hudTitle },
            h('div', { style: styles.hudName }, '意识海 / CONSCIOUSNESS SEA'),
            h('div', { style: styles.hudSub }, err ? `离线：${err}` : '拖拽旋转 · 滚轮缩放 · 双击复位'),
          ),
          h('div', { style: styles.hudChips },
            h('span', { style: styles.chip }, `NEURONS ${data?.nodes?.length || 0}`),
            h('span', { style: styles.chip }, `SYNAPSES ${data?.edges?.length || 0}`),
            h('span', { style: styles.chip }, `THREADS ${data?.threads || 0}`),
          ),
        ),
        !data && !err ? h('div', { style: styles.empty }, '正在唤醒意识海…') : null,
        err ? h('div', { style: styles.empty }, `未加载：${err}`) : null,
        h('div', { style: styles.controls },
          h('button', { style: styles.ctl, onClick: () => setAuto((v) => !v) }, auto ? '自动旋转 · 开' : '自动旋转 · 关'),
          h('button', { style: styles.ctl, onClick: reset }, '复位'),
          h('button', { style: styles.ctl, onClick: () => void load() }, '刷新'),
        ),
        hover ? h('div', {
          style: { ...styles.tip, left: Math.min(hover.x + 16, (view.current.w || 600) - 280), top: Math.max(12, hover.y - 90) },
        },
        h('div', { style: styles.tipTitle }, hover.node?.label || '未命名事件'),
        h('div', { style: styles.tipMeta },
          `${hover.node?.day || '—'} · ${hover.node?.count || 1} 条 · importance ${Number(hover.node?.importance || 0).toFixed(2)}`,
          h('br'),
          `valence ${Number(hover.node?.valence || 0).toFixed(2)} · unresolved ${Number(hover.node?.unresolved || 0).toFixed(2)}`,
          hover.node?.participants?.length ? h('br') : null,
          hover.node?.participants?.length ? `参与者：${hover.node.participants.slice(0, 4).join('、')}` : null,
        )) : null,
      )
    }

    function Section() {
      const [online, setOnline] = useState(false)
      const [settings, setSettings] = useState({ humanReview: false, reviewLimit: 8 })
      const [terms, setTerms] = useState(0)
      const [msg, setMsg] = useState('')

      async function refresh() {
        try {
          const s = await call('/settings')
          const t = await call('/terms')
          setSettings(s.settings || {})
          setTerms((t.terms || []).length)
          setOnline(true)
          setMsg('')
        } catch (e) {
          setOnline(false)
          setMsg(`sidecar 未启动：${e.message}`)
        }
      }
      useEffect(() => { void refresh() }, [])

      async function toggleReview(v) {
        try {
          const s = await call('/settings', { method: 'POST', body: JSON.stringify({ humanReview: v }) })
          setSettings(s.settings || settings)
          setMsg(v ? '人工评审已开：仅调试用' : '人工评审已关')
        } catch (e) { setMsg(e.message) }
      }
      async function makeReview() {
        try {
          const r = await call('/review', { method: 'POST', body: '{}' })
          setMsg(`评审表：${r.path}`)
        } catch (e) { setMsg(e.message) }
      }

      return h('div', { style: styles.wrap },
        h('div', { style: styles.card },
          h('div', { style: styles.row },
            h('strong', null, '记忆实验室 / memory-lab'),
            h('span', { style: { ...styles.muted, color: online ? '#67e8a0' : '#ffb4a2' } }, online ? 'sidecar 在线' : 'sidecar 离线')),
          h('div', { style: styles.muted }, '只读多轴实验：RRF、term 表、软边；不接入 QQ 主链，不写 soulcore.db。'),
          h('div', { style: styles.row },
            h('span', null, '人工评审（调试）'),
            h('input', { type: 'checkbox', checked: settings.humanReview === true, onChange: (e) => void toggleReview(e.target.checked) })),
          h('div', { style: styles.row },
            h('span', null, `term 表：${terms} 条`),
            h('button', { style: styles.btn, onClick: () => void refresh() }, '刷新')),
          h('div', { style: styles.row },
            h('button', { style: styles.btn, onClick: () => void makeReview() }, '生成评审表')),
          msg ? h('div', { style: styles.code }, msg) : null,
        ),
        h(Graph, null),
      )
    }

    return {
      inject: ['slots'],
      apply(ctx) {
        ctx.slots.inject('settings.section', () => ctx.slots.register({
          name: 'settings.section',
          id: 'memory-lab',
          order: 9,
          label: '记忆实验室',
        }, Section))
      },
    }
  },
})
