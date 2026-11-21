<script setup>
import { inject, onMounted, onBeforeUnmount, ref, watch } from 'vue'
import { LutRenderer } from '../lib/webglLut'
import { loadCube } from '../lib/cubeLut'
import { buildGradeModel, curveTextureData } from '../lib/gradeLut'

// 覆盖在 video / img 上的 WebGL 画布：一级调色子集 + LUT，蒙版仍由服务端渲染
const app = inject('app')
const cv = ref(null)
const box = ref({ display: 'none' })

let renderer = null
let raf = 0
let ro = null
let disposed = false
let boundEl = null
let boundEvents = []
const slots = [
  { path: '', lut: null, strength: 0 },
  { path: '', lut: null, strength: 0 },
]

function enabled() {
  // 服务端已渲染好的调色片段 / 已校准的画面都不能再叠一层着色器
  return app.clientShade
}

// 调色参数 → 着色器 uniform + 曲线表（与 ffmpeg 逐项对齐）
function syncGrade() {
  if (!renderer) return
  const model = app.hasGrading ? buildGradeModel(app.grading) : null
  renderer.setGrade(model, model ? curveTextureData(model) : null)
}

// 画布与媒体元素同框（offset* 不受缩放影响），再套同一份缩放变换
function measure() {
  const m = app.mediaEl
  if (!m) return false
  const w = m.offsetWidth
  const h = m.offsetHeight
  if (!w || !h) return false
  box.value = {
    display: 'block',
    left: m.offsetLeft + 'px',
    top: m.offsetTop + 'px',
    width: w + 'px',
    height: h + 'px',
    ...app.zoomStyle,
  }
  renderer.resize(w, h, Math.min(2, window.devicePixelRatio || 1))
  return true
}

function syncLuts() {
  const want = [
    [app.activeLutPath(), app.activeLutStrength()],
    [app.secondLutPath(), app.lutStrength2],
  ]
  renderer.setStrengths(want[0][1], want[1][1])
  let pending = false
  for (let i = 0; i < 2; i++) {
    const path = want[i][0]
    const s = slots[i]
    s.strength = want[i][1]
    if (path === s.path) continue
    s.path = path
    s.lut = null
    renderer.setLut(i, null)
    if (!path) continue
    pending = true
    loadCube(path).then(lut => {
      if (disposed || slots[i].path !== path) return
      s.lut = lut
      renderer.setLut(i, lut)
      draw()
    }).catch(err => {
      // 解析不了就彻底回退到服务端渲染，避免反复失败
      console.warn('LUT 着色器回退：', err)
      app.webglOk = false
    })
  }
  return pending
}

function draw() {
  if (!renderer || disposed) return
  const media = app.mediaEl
  if (!media || !enabled()) {
    box.value = { display: 'none' }
    return
  }
  if (!measure()) return
  if (media.tagName === 'VIDEO') {
    if (media.readyState < 2) return
  } else if (!media.complete || !media.naturalWidth) {
    return
  }
  // LUT 还没解析完：先隐藏画布，露出底下的原始画面，避免闪一帧错色
  if (syncLuts()) {
    box.value = { display: 'none' }
    return
  }
  renderer.render(media)
}

function loop() {
  raf = 0
  draw()
  const m = app.mediaEl
  if (m && m.tagName === 'VIDEO' && !m.paused) raf = requestAnimationFrame(loop)
}

function kick() {
  if (!raf) raf = requestAnimationFrame(loop)
}

function unbind() {
  if (ro) { ro.disconnect(); ro = null }
  if (boundEl) boundEvents.forEach(ev => boundEl.removeEventListener(ev, kick))
  boundEl = null
  boundEvents = []
}

function bind() {
  unbind()
  const m = app.mediaEl
  if (!m) return
  ro = new ResizeObserver(() => kick())
  ro.observe(m)
  boundEvents = m.tagName === 'VIDEO'
    ? ['loadeddata', 'seeked', 'play', 'pause', 'timeupdate', 'resize']
    : ['load']
  boundEvents.forEach(ev => m.addEventListener(ev, kick))
  boundEl = m
  kick()
}

onMounted(() => {
  try {
    renderer = new LutRenderer(cv.value)
  } catch (err) {
    console.warn('WebGL 初始化失败，回退服务端渲染：', err)
    app.webglOk = false
    return
  }
  syncGrade()
  bind()
})

watch(() => app.mediaEl, bind)
watch(() => [app.playUrl, app.mainThumbUrl, app.previewingLut, app.clientShade, app.zoom.scale], kick)
watch(() => [app.lutPath, app.customLut, app.lutStrength,
             app.lut2Path, app.lutStrength2, app.useSecondLut], kick)
watch(() => app.grading, () => {
  syncGrade()
  kick()
}, { deep: true })

onBeforeUnmount(() => {
  disposed = true
  if (raf) cancelAnimationFrame(raf)
  raf = 0
  unbind()
  if (renderer) renderer.dispose()
  renderer = null
})
</script>

<template>
  <canvas ref="cv" class="lut-canvas" :style="box"></canvas>
</template>
