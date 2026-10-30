<script setup>
import { ref, computed } from 'vue'

defineProps({
  label: { type: String, default: '' },
})
const modelValue = defineModel({ type: Object, default: () => ({ x: 0, y: 0 }) })

const dragging = ref(false)
const wheel = ref(null)

const dotStyle = computed(() => {
  const v = modelValue.value || { x: 0, y: 0 }
  return { left: (50 + v.x * 50) + '%', top: (50 - v.y * 50) + '%' }
})

function setPoint(ev) {
  const r = wheel.value.getBoundingClientRect()
  if (!r.width || !r.height) return
  let x = ((ev.clientX - r.left) / r.width) * 2 - 1
  let y = 1 - ((ev.clientY - r.top) / r.height) * 2
  const d = Math.hypot(x, y)
  if (d > 1) { x /= d; y /= d }
  modelValue.value = {
    x: Math.round(x * 100) / 100,
    y: Math.round(y * 100) / 100,
  }
}

function down(ev) {
  dragging.value = true
  setPoint(ev)
  if (ev.currentTarget.setPointerCapture) ev.currentTarget.setPointerCapture(ev.pointerId)
}

function move(ev) { if (dragging.value) setPoint(ev) }
function up() { dragging.value = false }
function reset() { modelValue.value = { x: 0, y: 0 } }
</script>

<template>
  <div class="wheel-box">
    <div class="wheel" ref="wheel" @pointerdown="down" @pointermove="move"
         @pointerup="up" @pointercancel="up" @dblclick="reset">
      <span class="wheel-dot" :style="dotStyle"></span>
    </div>
    <div class="wheel-label">{{ label }}</div>
  </div>
</template>
