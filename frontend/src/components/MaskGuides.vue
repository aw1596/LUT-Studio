<script setup>
// 几何蒙版（线性 / 圆形 / 矩形）的交互引导层：canvas 绘制 + 手柄拖拽
// - 边缘箭头标尺：拖动改变大小
// - 圆形箭头：拖动旋转
// - 内侧虚线环 / 框：拖动改变羽化
// - 形状内部：拖动移动选区中心
import { inject, ref, watch, onMounted, onBeforeUnmount } from 'vue'

const app = inject('app')
const cv = ref(null)

let drag = null
let moved = false

const HIT = 11  // 手柄命中半径（像素）
const clamp = (v, lo, hi) => Math.min(hi, Math.max(lo, v))
const normDeg = (d) => (d > 180 ? d - 360 : (d < -180 ? d + 360 : d))

function boxOf() {
  const b = app.maskBox
  return b && b.width > 1 && b.height > 1 ? b : null
}

// 当前选区的像素几何（与后端 _geom_mask_array 的坐标语义保持一致）
function geom() {
  const b = boxOf()
  if (!b) return null
  const n = app.activeNode
  const W = b.width, H = b.height
  const cx = n.cx * W, cy = n.cy * H
  const size = Math.max(0.02, n.size)
  if (n.shape === 'radial') {
    const r = size * W
    return { type: 'radial', W, H, cx, cy, r, fade: clamp((size - n.feather) / size, 0.03, 0.97) }
  }
  if (n.shape === 'rect') {
    const a = (n.angle || 0) * Math.PI / 180
    return {
      type: 'rect', W, H, cx, cy, a,
      hw: size * W,
      hh: size * (n.aspect || 1) * W,
      fade: clamp(1 - n.feather, 0.03, 0.97),
    }
  }
  const a = (n.angle || 0) * Math.PI / 180
  const g = { x: Math.cos(a), y: Math.sin(a) }   // 渐变方向
  const p = { x: -Math.sin(a), y: Math.cos(a) }  // 分界线方向
  const off = size / 2
  const pcx = n.cx * 100, pcy = n.cy * 100, L = 150
  const toPx = (xp, yp) => ({ x: xp / 100 * W, y: yp / 100 * H })
  const l1 = toPx(pcx - p.x * L, pcy - p.y * L)
  const l2 = toPx(pcx + p.x * L, pcy + p.y * L)
  const s1 = toPx(pcx - p.x * L + g.x * off * 100, pcy - p.y * L + g.y * off * 100)
  const s2 = toPx(pcx + p.x * L + g.x * off * 100, pcy + p.y * L + g.y * off * 100)
  return {
    type: 'linear', W, H, cx, cy, g, p, off,
    l1, l2, s1, s2,
    rot: { x: (n.cx + p.x * 0.12) * W, y: (n.cy + p.y * 0.12) * H },
    width: { x: (n.cx + g.x * off) * W, y: (n.cy + g.y * off) * H },
    width2: { x: (n.cx - g.x * off) * W, y: (n.cy - g.y * off) * H },
  }
}

// ---------- 绘制 ----------
const FILL = 'rgba(61,126,255,.12)'
const LINE = 'rgba(255,255,255,.9)'

function gripArrow(ctx, x, y, angle, len = 20) {
  ctx.save()
  ctx.translate(x, y)
  ctx.rotate(angle)
  ctx.strokeStyle = '#fff'
  ctx.lineWidth = 1.4
  ctx.lineCap = 'round'
  ctx.beginPath()
  ctx.moveTo(-len / 2, 0); ctx.lineTo(len / 2, 0)
  ctx.moveTo(-len / 2, 0); ctx.lineTo(-len / 2 + 4.5, -3.4)
  ctx.moveTo(-len / 2, 0); ctx.lineTo(-len / 2 + 4.5, 3.4)
  ctx.moveTo(len / 2, 0); ctx.lineTo(len / 2 - 4.5, -3.4)
  ctx.moveTo(len / 2, 0); ctx.lineTo(len / 2 - 4.5, 3.4)
  ctx.stroke()
  ctx.restore()
}

function gripRotate(ctx, x, y) {
  ctx.save()
  ctx.translate(x, y)
  ctx.beginPath(); ctx.arc(0, 0, 8, 0, Math.PI * 2)
  ctx.fillStyle = 'rgba(10,10,16,.85)'; ctx.fill()
  ctx.strokeStyle = '#fff'; ctx.lineWidth = 1.3; ctx.stroke()
  ctx.beginPath(); ctx.arc(0, 0, 4.4, -Math.PI * 0.85, Math.PI * 0.42)
  ctx.lineWidth = 1.5; ctx.stroke()
  const ax = 4.4 * Math.cos(Math.PI * 0.42), ay = 4.4 * Math.sin(Math.PI * 0.42)
  ctx.beginPath()
  ctx.moveTo(ax, ay); ctx.lineTo(ax - 3.8, ay - 0.8)
  ctx.moveTo(ax, ay); ctx.lineTo(ax - 0.4, ay - 4.2)
  ctx.stroke()
  ctx.restore()
}

function gripBox(ctx, x, y, s = 7) {
  ctx.fillStyle = '#fff'
  ctx.strokeStyle = 'rgba(10,10,16,.85)'
  ctx.lineWidth = 1
  ctx.beginPath(); ctx.rect(x - s / 2, y - s / 2, s, s); ctx.fill(); ctx.stroke()
}

function gripRing(ctx, x, y) {
  ctx.beginPath(); ctx.arc(x, y, 6.5, 0, Math.PI * 2)
  ctx.fillStyle = 'rgba(10,10,16,.7)'; ctx.fill()
  ctx.strokeStyle = '#fff'; ctx.lineWidth = 1.4; ctx.stroke()
  ctx.beginPath(); ctx.arc(x, y, 2, 0, Math.PI * 2)
  ctx.fillStyle = '#fff'; ctx.fill()
}

function paint() {
  const el = cv.value
  const b = boxOf()
  if (!el || !b) return
  const dpr = window.devicePixelRatio || 1
  const pw = Math.max(1, Math.round(b.width * dpr))
  const ph = Math.max(1, Math.round(b.height * dpr))
  if (el.width !== pw || el.height !== ph) { el.width = pw; el.height = ph }
  const ctx = el.getContext('2d')
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
  ctx.clearRect(0, 0, b.width, b.height)
  const g = geom()
  if (!g) return
  if (g.type === 'radial') paintRadial(ctx, g)
  else if (g.type === 'rect') paintRect(ctx, g)
  else paintLinear(ctx, g)
}

function paintCenter(ctx, x, y) {
  ctx.strokeStyle = 'rgba(255,255,255,.9)'
  ctx.lineWidth = 1
  ctx.beginPath()
  ctx.moveTo(x - 5, y); ctx.lineTo(x + 5, y)
  ctx.moveTo(x, y - 5); ctx.lineTo(x, y + 5)
  ctx.stroke()
}

function paintRadial(ctx, g) {
  ctx.beginPath(); ctx.arc(g.cx, g.cy, g.r, 0, Math.PI * 2)
  ctx.fillStyle = FILL; ctx.fill()
  ctx.strokeStyle = LINE; ctx.lineWidth = 1.2; ctx.stroke()

  ctx.beginPath(); ctx.arc(g.cx, g.cy, Math.max(2, g.r * g.fade), 0, Math.PI * 2)
  ctx.setLineDash([4, 3]); ctx.lineWidth = 1
  ctx.strokeStyle = 'rgba(255,255,255,.45)'; ctx.stroke()
  ctx.setLineDash([])

  for (const [dx, dy] of [[1, 0], [-1, 0], [0, 1], [0, -1]]) {
    gripArrow(ctx, g.cx + dx * g.r, g.cy + dy * g.r, dy ? Math.PI / 2 : 0)
  }
  const fd = g.r * g.fade * Math.SQRT1_2
  gripRing(ctx, g.cx + fd, g.cy + fd)
  paintCenter(ctx, g.cx, g.cy)
}

function paintRect(ctx, g) {
  ctx.save()
  ctx.translate(g.cx, g.cy)
  ctx.rotate(g.a)
  ctx.beginPath(); ctx.rect(-g.hw, -g.hh, g.hw * 2, g.hh * 2)
  ctx.fillStyle = FILL; ctx.fill()
  ctx.strokeStyle = LINE; ctx.lineWidth = 1.2; ctx.stroke()

  ctx.beginPath(); ctx.rect(-g.hw * g.fade, -g.hh * g.fade, g.hw * 2 * g.fade, g.hh * 2 * g.fade)
  ctx.setLineDash([4, 3]); ctx.lineWidth = 1
  ctx.strokeStyle = 'rgba(255,255,255,.45)'; ctx.stroke()
  ctx.setLineDash([])

  for (const [sx, sy] of [[-1, -1], [-1, 1], [1, -1], [1, 1]]) gripBox(ctx, sx * g.hw, sy * g.hh)
  gripArrow(ctx, 0, -g.hh, Math.PI / 2)
  gripArrow(ctx, 0, g.hh, Math.PI / 2)
  gripArrow(ctx, -g.hw, 0, 0)
  gripArrow(ctx, g.hw, 0, 0)
  gripRing(ctx, g.hw * g.fade, g.hh * g.fade)
  ctx.restore()

  // 旋转手柄：沿形状顶部外侧方向摆放
  const ox = Math.sin(g.a), oy = -Math.cos(g.a)
  const d = g.hh + 26
  const hx = g.cx + ox * d, hy = g.cy + oy * d
  ctx.beginPath()
  ctx.moveTo(g.cx + ox * g.hh, g.cy + oy * g.hh); ctx.lineTo(hx, hy)
  ctx.strokeStyle = 'rgba(255,255,255,.5)'; ctx.lineWidth = 1; ctx.stroke()
  gripRotate(ctx, hx, hy)
  paintCenter(ctx, g.cx, g.cy)
}

function paintLinear(ctx, g) {
  ctx.beginPath(); ctx.moveTo(g.l1.x, g.l1.y); ctx.lineTo(g.l2.x, g.l2.y)
  ctx.strokeStyle = LINE; ctx.lineWidth = 1.2; ctx.stroke()
  ctx.beginPath(); ctx.moveTo(g.s1.x, g.s1.y); ctx.lineTo(g.s2.x, g.s2.y)
  ctx.setLineDash([4, 3]); ctx.strokeStyle = 'rgba(255,255,255,.45)'; ctx.lineWidth = 1; ctx.stroke()
  ctx.setLineDash([])

  ctx.beginPath(); ctx.moveTo(g.cx, g.cy); ctx.lineTo(g.rot.x, g.rot.y)
  ctx.strokeStyle = 'rgba(255,255,255,.5)'; ctx.lineWidth = 1; ctx.stroke()
  gripRotate(ctx, g.rot.x, g.rot.y)
  gripArrow(ctx, g.width.x, g.width.y, Math.atan2(g.g.y * g.H, g.g.x * g.W))
  gripArrow(ctx, g.width2.x, g.width2.y, Math.atan2(g.g.y * g.H, g.g.x * g.W))
  paintCenter(ctx, g.cx, g.cy)
}

// ---------- 命中测试 ----------
function hitTest(px, py) {
  const g = geom()
  if (!g) return null
  const near = (x, y, r = HIT) => Math.hypot(px - x, py - y) <= r
  if (g.type === 'radial') {
    const fd = g.r * g.fade * Math.SQRT1_2
    if (near(g.cx + fd, g.cy + fd)) return { mode: 'radial-feather' }
    for (const [dx, dy] of [[1, 0], [-1, 0], [0, 1], [0, -1]]) {
      if (near(g.cx + dx * g.r, g.cy + dy * g.r)) return { mode: 'radial-size', axis: dx ? 'x' : 'y' }
    }
    if (Math.hypot(px - g.cx, py - g.cy) <= g.r) return moveHit(px, py)
  } else if (g.type === 'rect') {
    const c = Math.cos(g.a), s = Math.sin(g.a)
    const vx = px - g.cx, vy = py - g.cy
    const lx = vx * c + vy * s, ly = -vx * s + vy * c
    const nearL = (x, y, r = HIT) => Math.hypot(lx - x, ly - y) <= r
    if (nearL(g.hw * g.fade, g.hh * g.fade)) return { mode: 'rect-feather' }
    const d = g.hh + 26
    if (near(g.cx + Math.sin(g.a) * d, g.cy - Math.cos(g.a) * d)) return { mode: 'rect-rotate' }
    for (const [sx, sy] of [[-1, -1], [-1, 1], [1, -1], [1, 1]]) {
      if (nearL(sx * g.hw, sy * g.hh)) return { mode: 'rect-size', hx: true, hy: true }
    }
    if (nearL(0, -g.hh) || nearL(0, g.hh)) return { mode: 'rect-size', hx: false, hy: true }
    if (nearL(-g.hw, 0) || nearL(g.hw, 0)) return { mode: 'rect-size', hx: true, hy: false }
    if (Math.abs(lx) <= g.hw && Math.abs(ly) <= g.hh) return moveHit(px, py)
  } else {
    if (near(g.rot.x, g.rot.y)) return { mode: 'linear-rotate' }
    if (near(g.width.x, g.width.y) || near(g.width2.x, g.width2.y)) return { mode: 'linear-width' }
    if (near(g.cx, g.cy, 26)) return moveHit(px, py)
  }
  return null
}

function moveHit(px, py) {
  const n = app.activeNode
  return { mode: 'move', x0: px, y0: py, cx0: n.cx, cy0: n.cy }
}

// ---------- 拖拽 ----------
function apply(px, py) {
  if (!drag) return
  const b = boxOf()
  if (!b) return
  const n = app.activeNode
  const W = b.width, H = b.height
  const size = Math.max(0.02, n.size)
  const a = (n.angle || 0) * Math.PI / 180
  moved = true

  if (drag.mode === 'move') {
    n.cx = clamp(drag.cx0 + (px - drag.x0) / W, 0, 1)
    n.cy = clamp(drag.cy0 + (py - drag.y0) / H, 0, 1)
  } else if (drag.mode === 'radial-size') {
    const dxp = px - n.cx * W, dyp = py - n.cy * H
    n.size = clamp((drag.axis === 'x' ? Math.abs(dxp) : Math.abs(dyp)) / W, 0.05, 1.5)
  } else if (drag.mode === 'radial-feather') {
    const r = size * W
    const fade = clamp(Math.hypot(px - n.cx * W, py - n.cy * H) / r, 0.03, 0.97)
    n.feather = clamp(size * (1 - fade), 0.02, 1)
  } else if (drag.mode === 'rect-rotate') {
    n.angle = normDeg(Math.round(Math.atan2(px - n.cx * W, -(py - n.cy * H)) * 180 / Math.PI))
  } else if (drag.mode === 'rect-size') {
    const vx = px - n.cx * W, vy = py - n.cy * H
    const lx = vx * Math.cos(a) + vy * Math.sin(a)
    const ly = -vx * Math.sin(a) + vy * Math.cos(a)
    const hw = size * W
    const hh = size * (n.aspect || 1) * W
    if (drag.hx) {
      const s2 = clamp(Math.abs(lx) / W, 0.05, 1.5)
      n.size = s2
      const targetH = drag.hy ? Math.abs(ly) : hh  // 只拖左右边时高度保持不变
      n.aspect = clamp(targetH / (s2 * W), 0.1, 3)
    } else {
      n.aspect = clamp(Math.abs(ly) / hw, 0.1, 3)
    }
  } else if (drag.mode === 'rect-feather') {
    const vx = px - n.cx * W, vy = py - n.cy * H
    const lx = vx * Math.cos(a) + vy * Math.sin(a)
    const ly = -vx * Math.sin(a) + vy * Math.cos(a)
    const m = Math.max(Math.abs(lx) / (size * W), Math.abs(ly) / (size * (n.aspect || 1) * W))
    n.feather = clamp(1 - m, 0.02, 1)
  } else if (drag.mode === 'linear-rotate') {
    const vx = px / W - n.cx, vy = py / H - n.cy
    n.angle = normDeg(Math.round(Math.atan2(-vx, vy) * 180 / Math.PI))
  } else if (drag.mode === 'linear-width') {
    const vx = px / W - n.cx, vy = py / H - n.cy
    n.size = clamp(2 * Math.abs(vx * Math.cos(a) + vy * Math.sin(a)), 0.05, 1.5)
  }
  paint()
}

function localPoint(ev) {
  const el = cv.value
  const r = el.getBoundingClientRect()
  return { px: ev.clientX - r.left, py: ev.clientY - r.top }
}

function onDown(ev) {
  const p = localPoint(ev)
  const hit = hitTest(p.px, p.py)
  if (!hit) return
  drag = hit
  moved = false
  app.maskDragging = true
  if (cv.value.setPointerCapture) {
    try { cv.value.setPointerCapture(ev.pointerId) } catch {}
  }
}

function onMove(ev) {
  const p = localPoint(ev)
  if (drag) { apply(p.px, p.py); return }
  const hit = hitTest(p.px, p.py)
  cv.value.style.cursor = !hit ? 'crosshair'
    : (hit.mode === 'rect-rotate' || hit.mode === 'linear-rotate') ? 'grab'
      : hit.mode.includes('feather') ? 'pointer'
        : hit.mode.includes('size') ? 'crosshair'
          : 'move'
}

function onUp() {
  if (!drag) return
  drag = null
  app.maskDragging = false
  if (moved) app.refreshPreview(true)
  moved = false
}

watch(() => app.mask, paint, { deep: true })
watch(() => app.maskBox, paint)
watch(() => app.activeNode.id, paint)
watch(() => app.zoom.scale, paint)

onMounted(() => {
  paint()
  window.addEventListener('resize', paint)
})
onBeforeUnmount(() => window.removeEventListener('resize', paint))
</script>

<template>
  <canvas ref="cv" class="mask-canvas" :style="app.maskStyle"
          @pointerdown="onDown" @pointermove="onMove" @pointerup="onUp" @pointercancel="onUp"></canvas>
</template>
