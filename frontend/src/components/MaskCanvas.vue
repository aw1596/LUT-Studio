<script setup>
// 画笔 / 钢笔蒙版叠加层：canvas 绘制 + 指针交互
import { inject, ref, watch, onMounted, onBeforeUnmount } from 'vue'

const app = inject('app')
const cv = ref(null)

function paint() {
  const el = cv.value
  const box = app.maskBox
  if (!el || !box || !box.width || !box.height) return
  const dpr = window.devicePixelRatio || 1
  const w = box.width
  const h = box.height
  const pw = Math.max(1, Math.round(w * dpr))
  const ph = Math.max(1, Math.round(h * dpr))
  if (el.width !== pw || el.height !== ph) { el.width = pw; el.height = ph }
  const ctx = el.getContext('2d')
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
  ctx.clearRect(0, 0, w, h)

  if (app.activeNode.shape === 'brush') {
    const radius = Math.max(2, app.activeNode.brush_size * Math.min(w, h))
    ctx.lineJoin = 'round'
    ctx.lineCap = 'round'
    for (const stroke of app.activeNode.strokes) {
      if (!stroke.length) continue
      ctx.beginPath()
      ctx.moveTo(stroke[0].x * w, stroke[0].y * h)
      for (let i = 1; i < stroke.length; i++) ctx.lineTo(stroke[i].x * w, stroke[i].y * h)
      ctx.strokeStyle = 'rgba(61,126,255,.34)'
      ctx.lineWidth = radius
      ctx.stroke()
      ctx.strokeStyle = 'rgba(255,255,255,.75)'
      ctx.lineWidth = 1
      ctx.stroke()
    }
  } else {
    const pts = app.activeNode.pen_points
    if (pts.length) {
      ctx.beginPath()
      ctx.moveTo(pts[0].x * w, pts[0].y * h)
      for (let i = 1; i < pts.length; i++) ctx.lineTo(pts[i].x * w, pts[i].y * h)
      if (pts.length >= 3) {
        ctx.closePath()
        ctx.fillStyle = 'rgba(61,126,255,.22)'
        ctx.fill()
      }
      ctx.strokeStyle = 'rgba(255,255,255,.85)'
      ctx.lineWidth = 1.4
      ctx.stroke()
      for (const [i, p] of pts.entries()) {
        const active = i === app.penDragIndex
        ctx.beginPath()
        ctx.arc(p.x * w, p.y * h, active ? 5.5 : 3.2, 0, Math.PI * 2)
        ctx.fillStyle = active ? 'rgba(61,126,255,.85)' : '#fff'
        ctx.fill()
      }
    }
  }
}

function norm(ev) {
  const el = cv.value
  if (!el) return null
  const r = el.getBoundingClientRect()
  if (!r.width || !r.height) return null
  return {
    x: Math.min(1, Math.max(0, (ev.clientX - r.left) / r.width)),
    y: Math.min(1, Math.max(0, (ev.clientY - r.top) / r.height)),
  }
}

function onDown(ev) {
  const p = norm(ev)
  if (!p) return
  if (ev.currentTarget.setPointerCapture) {
    try { ev.currentTarget.setPointerCapture(ev.pointerId) } catch {}
  }
  app.maskPaintStart(p.x, p.y)
  paint()
}

function onMove(ev) {
  const p = norm(ev)
  if (!p) return
  app.maskPaintMove(p.x, p.y)
  paint()
}

function onUp() {
  app.maskPaintEnd()
  paint()
}

watch(() => app.mask, paint, { deep: true })
watch(() => app.maskBox, paint)
watch(() => app.activeNode.id, paint)

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
