<script setup>
// 色调曲线编辑器：拖动控制点调整曲线，空白处单击新增点，双击点删除
import { ref, computed } from 'vue'

const props = defineProps({
  modelValue: { type: Array, default: () => [] },
  color: { type: String, default: '#ffffff' },
})
const emit = defineEmits(['update:modelValue'])

const svgEl = ref(null)
const dragIdx = ref(-1)

const pts = computed(() => (props.modelValue && props.modelValue.length >= 2
  ? props.modelValue
  : [{ x: 0, y: 0 }, { x: 1, y: 1 }]))

// Catmull-Rom → 三次贝塞尔，得到平滑曲线
const pathD = computed(() => {
  const p = pts.value
  const sx = (v) => (v * 100).toFixed(2)
  const sy = (v) => ((1 - v) * 100).toFixed(2)
  let d = `M${sx(p[0].x)},${sy(p[0].y)}`
  for (let i = 0; i < p.length - 1; i++) {
    const p0 = p[i - 1] || p[i]
    const p1 = p[i]
    const p2 = p[i + 1]
    const p3 = p[i + 2] || p2
    const c1x = p1.x + (p2.x - p0.x) / 6
    const c1y = p1.y + (p2.y - p0.y) / 6
    const c2x = p2.x - (p3.x - p1.x) / 6
    const c2y = p2.y - (p3.y - p1.y) / 6
    d += ` C${sx(c1x)},${sy(Math.min(1, Math.max(0, c1y)))} ${sx(c2x)},${sy(Math.min(1, Math.max(0, c2y)))} ${sx(p2.x)},${sy(p2.y)}`
  }
  return d
})

function localPoint(ev) {
  const r = svgEl.value.getBoundingClientRect()
  if (!r.width || !r.height) return null
  return {
    x: Math.min(1, Math.max(0, (ev.clientX - r.left) / r.width)),
    y: Math.min(1, Math.max(0, 1 - (ev.clientY - r.top) / r.height)),
  }
}

function nearest(p) {
  let best = -1
  let dist = 0.09
  pts.value.forEach((q, i) => {
    const d = Math.hypot(q.x - p.x, q.y - p.y)
    if (d < dist) { dist = d; best = i }
  })
  return best
}

function commit(next) {
  emit('update:modelValue', next.map(q => ({ x: q.x, y: q.y })))
}

function onDown(ev) {
  const p = localPoint(ev)
  if (!p) return
  let idx = nearest(p)
  let list = pts.value.map(q => ({ x: q.x, y: q.y }))
  if (idx < 0) {
    list.push(p)
    list.sort((a, b) => a.x - b.x)
    idx = list.findIndex(q => q.x === p.x && q.y === p.y)
  }
  dragIdx.value = idx
  commit(list)
  if (ev.currentTarget.setPointerCapture) ev.currentTarget.setPointerCapture(ev.pointerId)
}

function onMove(ev) {
  if (dragIdx.value < 0) return
  const p = localPoint(ev)
  if (!p) return
  const list = pts.value.map(q => ({ x: q.x, y: q.y }))
  const i = dragIdx.value
  if (i === 0) { list[0] = { x: 0, y: p.y }; }
  else if (i === list.length - 1) { list[i] = { x: 1, y: p.y }; }
  else {
    const lo = list[i - 1].x + 0.01
    const hi = list[i + 1].x - 0.01
    list[i] = { x: Math.min(hi, Math.max(lo, p.x)), y: p.y }
  }
  commit(list)
}

function onUp() { dragIdx.value = -1 }

function onDblClick(ev) {
  const p = localPoint(ev)
  if (!p) return
  const idx = nearest(p)
  if (idx <= 0 || idx >= pts.value.length - 1) return
  commit(pts.value.filter((_, i) => i !== idx))
}
</script>

<template>
  <div class="curve-box">
    <svg ref="svgEl" viewBox="0 0 100 100" preserveAspectRatio="none"
         @pointerdown="onDown" @pointermove="onMove" @pointerup="onUp"
         @pointercancel="onUp" @dblclick="onDblClick">
      <line x1="0" y1="100" x2="100" y2="0" stroke="rgba(255,255,255,.14)"
            stroke-width="1" stroke-dasharray="3 3" vector-effect="non-scaling-stroke"></line>
      <line v-for="g in [25, 50, 75]" :key="'v' + g" :x1="g" y1="0" :x2="g" y2="100"
            stroke="rgba(255,255,255,.07)" stroke-width="1" vector-effect="non-scaling-stroke"></line>
      <line v-for="g in [25, 50, 75]" :key="'h' + g" x1="0" :y1="g" x2="100" :y2="g"
            stroke="rgba(255,255,255,.07)" stroke-width="1" vector-effect="non-scaling-stroke"></line>
      <path :d="pathD" fill="none" :stroke="color" stroke-width="1.6"
            vector-effect="non-scaling-stroke"></path>
      <circle v-for="(p, i) in pts" :key="i" :cx="p.x * 100" :cy="(1 - p.y) * 100" r="2.4"
              :fill="i === dragIdx ? color : '#111117'" :stroke="color" stroke-width="1.4"
              vector-effect="non-scaling-stroke"></circle>
    </svg>
  </div>
</template>
