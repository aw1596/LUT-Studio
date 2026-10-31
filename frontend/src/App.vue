<script setup>
import { reactive, computed, watch, nextTick, provide, onMounted, onBeforeUnmount } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'

import TopBar from './components/TopBar.vue'
import LeftRail from './components/LeftRail.vue'
import PlayerStage from './components/PlayerStage.vue'
import Filmstrip from './components/Filmstrip.vue'
import MaterialPanel from './components/panels/MaterialPanel.vue'
import FiltersPanel from './components/panels/FiltersPanel.vue'
import GradingPanel from './components/panels/GradingPanel.vue'
import ExportPanel from './components/panels/ExportPanel.vue'
import TasksPanel from './components/panels/TasksPanel.vue'

// ---------- 调色 / 蒙版的数据工厂 ----------
// 同一套调色参数既用于全局一级调色，也用于每个蒙版的独立调色
let maskSeq = 0
let nodeSeq = 0

const blankCurve = () => [{ x: 0, y: 0 }, { x: 1, y: 1 }]
const blankHsl = () => ({
  reds: { h: 0, s: 0, l: 0 }, oranges: { h: 0, s: 0, l: 0 },
  yellows: { h: 0, s: 0, l: 0 }, greens: { h: 0, s: 0, l: 0 },
  aquas: { h: 0, s: 0, l: 0 }, blues: { h: 0, s: 0, l: 0 },
  purples: { h: 0, s: 0, l: 0 }, magentas: { h: 0, s: 0, l: 0 },
})
const blankSplit = () => ({ shadow_hue: 40, shadow_sat: 0, highlight_hue: 210, highlight_sat: 0, balance: 0 })
const blankCalibration = () => ({ red_hue: 0, red_sat: 0, green_hue: 0, green_sat: 0, blue_hue: 0, blue_sat: 0 })

function makeGrading() {
  return {
    // 一级调色
    temperature: 0, tint: 0, exposure: 0,
    highlights: 0, shadows: 0, whites: 0, blacks: 0,
    contrast: 0, saturation: 0, vibrance: 0, sharpness: 0,
    // 色轮：暗部 / 中间调 / 高光
    lift: { x: 0, y: 0 }, gamma: { x: 0, y: 0 }, gain: { x: 0, y: 0 },
    // 色调曲线（RGB + R/G/B）与曲线区域调整
    curve: {
      master: blankCurve(), r: blankCurve(), g: blankCurve(), b: blankCurve(),
    },
    curve_regions: { shadows: 0, midtones: 0, highlights: 0 },
    hsl: blankHsl(),
    split: blankSplit(),
    calibration: blankCalibration(),
  }
}

const SHAPE_LABELS = { linear: '线性', radial: '圆形', rect: '矩形', brush: '画笔', pen: '钢笔' }

// 组合树中的原始选区节点：一次工具操作的产物
function makeNode(shape = 'radial', op = 'add') {
  nodeSeq += 1
  return {
    id: 'n' + nodeSeq,
    name: `${SHAPE_LABELS[shape] || '选区'} ${nodeSeq}`,
    op, enabled: true, shape,
    cx: 0.5, cy: 0.5, angle: 0,
    size: 0.35, aspect: 0.6, feather: 0.25, invert: false,
    brush_size: 0.12, strokes: [], pen_points: [],
  }
}

// 蒙版 = 组合树（nodes + 运算）+ 一组作用于最终合成选区的调色参数
function makeMask(shape = 'radial') {
  maskSeq += 1
  const node = makeNode(shape)
  return {
    id: 'm' + maskSeq,
    name: `蒙版 ${maskSeq}`,
    enabled: true,
    nodes: [node],
    activeNodeId: node.id,
    invert: false,
    grading: makeGrading(),
  }
}

// 未选中任何蒙版时的占位对象，保证模板里的 app.mask / app.activeNode 始终可读
const idleMask = {
  id: 'idle', name: '未选择蒙版', enabled: false,
  nodes: [{
    id: 'idle-node', name: '未选择选区', op: 'add', enabled: false, shape: 'radial',
    cx: 0.5, cy: 0.5, angle: 0, size: 0.35, aspect: 0.6, feather: 0.25,
    invert: false, brush_size: 0.12, strokes: [], pen_points: [],
  }],
  activeNodeId: 'idle-node',
  invert: false,
  grading: makeGrading(),
}

// 单一状态对象：原 data 的全部字段 + 子组件挂载后写入的 DOM 引用
const app = reactive({
  tab: 'media',
  inputDir: '',
  scanning: false,
  importing: false,
  importPct: 0,
  dragOver: false,
  files: [],
  currentPath: '',
  sel: [],
  binNav: { left: false, right: false },
  luts: [],
  lutPath: '',
  lut2Path: '',
  useSecondLut: false,
  lutStrength: 100,
  lutStrength2: 100,
  customLut: '',
  outputMode: 'subfolder',
  customDir: '',
  resolution: 'original',
  quality: 20,
  bitDepth: 10,
  useGpu: true,
  batches: [],
  timer: null,
  gpuChecked: false,
  gpuOk: false,
  gpuMsg: '',
  playUrl: '',
  playTime: 0,
  playDuration: 0,
  playing: false,
  previewingLut: false,
  previewLoading: false,
  previewText: '正在生成调色预览…',
  thumbLoading: false,
  mainThumbUrl: '',
  compare: false,
  thumbTimer: null,
  thumbVersion: 0,
  lastThumbAt: 0,
  pickingDir: false,
  // 可拖动的界面尺寸：右侧属性面板宽度、底部素材条高度
  layout: { inspector: 348, bin: 176 },
  // 预览画面缩放：滚轮以光标为中心缩放，放大后可拖动平移
  zoom: { scale: 1, x: 0, y: 0 },
  zoomDragging: false,
  zoomStart: null,
  // 调色（仿 Lightroom）：全局一级调色，含色轮 / 曲线 / HSL / 分离色调 / 校准
  grading: makeGrading(),
  // 蒙版：masks 为已确认的蒙版，maskDraft 为绘制中待确认的蒙版，maskId 为当前选中的蒙版
  masks: [],
  maskId: '',
  maskDraft: null,
  idleMask,
  maskBox: null,
  maskDragging: false,
  penDragIndex: -1,
  mediaAspect: 16 / 9,
  // DOM 引用：playerEl（预览容器）、mediaEl（video/img）、binStrip（素材条）
  playerEl: null,
  mediaEl: null,
  binStrip: null,
})

// ---------- computed ----------
app.currentClip = computed(() => app.files.find(f => f.path === app.currentPath) || null)
app.tabTitle = computed(() => ({ media: '素材', filter: '滤镜', color: '调色', export: '导出', tasks: '任务' }[app.tab]))
const isLinearCurve = (pts) => (pts || []).every(p => Math.abs(p.x - p.y) < 0.005)
// 任意一组调色参数是否偏离中性（全局与每个蒙版共用）
const gradingUsed = (g) => {
  if (!g) return false
  const w = g.lift.x || g.lift.y || g.gamma.x || g.gamma.y || g.gain.x || g.gain.y
  const curve = Object.values(g.curve).some(pts => pts.length > 2 || !isLinearCurve(pts))
  const reg = g.curve_regions
    ? (g.curve_regions.shadows || g.curve_regions.midtones || g.curve_regions.highlights) : 0
  const hsl = Object.values(g.hsl).some(v => v.h || v.s || v.l)
  const split = g.split.shadow_sat || g.split.highlight_sat
  const cal = Object.values(g.calibration).some(v => v)
  return !!(g.temperature || g.tint || g.exposure || g.contrast || g.saturation ||
    g.highlights || g.shadows || g.whites || g.blacks || g.vibrance ||
    g.sharpness || w || reg || curve || hsl || split || cal)
}
app.gradingUsed = gradingUsed
app.hasGrading = computed(() => gradingUsed(app.grading))
// 当前正在编辑的蒙版：草稿优先，其次是列表中被选中的蒙版
app.maskEditing = computed(() =>
  !!(app.maskDraft || app.masks.some(m => m.id === app.maskId)))
app.mask = computed(() =>
  app.maskDraft || app.masks.find(m => m.id === app.maskId) || idleMask)
// 当前编辑的原始选区节点（组合树叶子）；所有形状 / 绘制操作都作用于它
app.activeNode = computed(() => {
  const m = app.mask
  const nodes = m.nodes || []
  return nodes.find(n => n.id === m.activeNodeId) || nodes[0] || idleMask.nodes[0]
})
app.isDrawnMask = computed(() =>
  app.activeNode.shape === 'brush' || app.activeNode.shape === 'pen')
app.hasAdjust = computed(() =>
  app.hasGrading || app.masks.some(m => m.enabled && gradingUsed(m.grading)))
app.maskStyle = computed(() => {
  const b = app.maskBox
  if (!b) return { display: 'none' }
  return {
    left: b.left + 'px', top: b.top + 'px',
    width: b.width + 'px', height: b.height + 'px',
  }
})
// 预览画面缩放 / 平移（滚轮以光标为中心放大，拖动平移）
app.zoomStyle = computed(() => ({
  transform: `translate(${app.zoom.x}px, ${app.zoom.y}px) scale(${app.zoom.scale})`,
  cursor: app.zoom.scale > 1.001 ? (app.zoomDragging ? 'grabbing' : 'grab') : 'default',
}))
// LUT 分三类：内置的灰片还原 LUT（一级）、Log 直转风格化 LUT（一级）与 luts/ 里的个性化 LUT（二级叠加）
app.restoreLuts = computed(() => app.luts.filter(l => l.kind === 'restore'))
app.logStyleLuts = computed(() => app.luts.filter(l => l.kind === 'log'))
app.creativeLuts = computed(() => app.luts.filter(l => l.kind === 'creative'))
app.lutLabel = computed(() => {
  const l = app.luts.find(x => x.path === app.lutPath)
  if (!l) return '未选择滤镜'
  let label = `滤镜：${l.name} · ${app.lutStrength}%`
  const l2 = app.luts.find(x => x.path === app.lut2Path)
  if (app.useSecondLut && l2) label += ` + ${l2.name} · ${app.lutStrength2}%`
  return label
})
app.resolutionText = computed(() => ({ original: '原始分辨率', '1080p': '1080p', '720p': '720p' }[app.resolution]))
app.canStart = computed(() => app.sel.length > 0 && (app.customLut || app.lutPath) &&
  (!app.useSecondLut || app.lut2Path) &&
  (app.outputMode !== 'custom' || app.customDir))
app.batchesReversed = computed(() => [...app.batches].reverse())
app.hasRunning = computed(() => app.batches.some(b => b.status === 'running'))
app.showThumb = computed(() => !app.playUrl && !!app.mainThumbUrl)

// ---------- 工具方法 ----------
app.fmtSize = (b) => (b / 1024 / 1024).toFixed(1) + ' MB'
app.fmtNum = (v, d) => (Number(v) || 0).toFixed(d)
app.fmtDur = (s) => {
  if (!s) return '-'
  const m = Math.floor(s / 60), ss = Math.round(s % 60)
  return `${m}:${String(ss).padStart(2, '0')}`
}

// ---------- 底部素材条 ----------
app.scrollBin = (dir) => {
  const el = app.binStrip
  if (!el) return
  const step = Math.max(240, el.clientWidth - 180)
  el.scrollBy({ left: dir * step, behavior: 'smooth' })
}

app.onBinWheel = (e) => {
  const el = app.binStrip
  if (!el) return
  if (Math.abs(e.deltaY) <= Math.abs(e.deltaX)) return
  if (el.scrollWidth <= el.clientWidth) return
  e.preventDefault()
  el.scrollLeft += e.deltaY
  app.updateBinNav()
}

app.updateBinNav = () => {
  const el = app.binStrip
  if (!el) { app.binNav.left = app.binNav.right = false; return }
  app.binNav.left = el.scrollLeft > 4
  app.binNav.right = el.scrollLeft + el.clientWidth < el.scrollWidth - 4
}

// ---------- 界面尺寸拖动 ----------
// 拖动右侧面板左边界（左右）或素材条上边界（上下），实时改变预览区大小
app.startResize = (which, ev) => {
  ev.preventDefault()
  const startX = ev.clientX
  const startY = ev.clientY
  const base = which === 'inspector' ? app.layout.inspector : app.layout.bin
  const move = (e) => {
    if (which === 'inspector') {
      const max = Math.max(320, window.innerWidth - 430)
      app.layout.inspector = Math.min(max, Math.max(260, base + (startX - e.clientX)))
    } else {
      const max = Math.max(200, window.innerHeight - 230)
      app.layout.bin = Math.min(max, Math.max(150, base + (startY - e.clientY)))
    }
    app.updateMaskBox()
    app.updateBinNav()
  }
  const up = () => {
    window.removeEventListener('pointermove', move)
    window.removeEventListener('pointerup', up)
    document.body.style.cursor = ''
  }
  window.addEventListener('pointermove', move)
  window.addEventListener('pointerup', up)
  document.body.style.cursor = which === 'inspector' ? 'col-resize' : 'row-resize'
}

// ---------- 预览缩放 ----------
app.resetZoom = () => {
  app.zoom = { scale: 1, x: 0, y: 0 }
  nextTick(app.updateMaskBox)
}

app.onZoomWheel = (ev) => {
  const host = app.playerEl
  if (!host || !app.mediaEl) return
  if (ev.target.closest && ev.target.closest('.tl-bar')) return
  ev.preventDefault()
  const r = host.getBoundingClientRect()
  const dx = ev.clientX - (r.left + r.width / 2)
  const dy = ev.clientY - (r.top + r.height / 2)
  const s0 = app.zoom.scale
  const s1 = Math.min(8, Math.max(1, s0 * Math.exp(-ev.deltaY * 0.0022)))
  // 保持光标下的像素不动：t' = d - (s'/s) * (d - t)
  const k = s1 / s0
  let x = dx - k * (dx - app.zoom.x)
  let y = dy - k * (dy - app.zoom.y)
  if (s1 <= 1.001) {
    x = 0
    y = 0
  } else {
    const limX = (r.width * (s1 - 1)) / 2
    const limY = (r.height * (s1 - 1)) / 2
    x = Math.max(-limX, Math.min(limX, x))
    y = Math.max(-limY, Math.min(limY, y))
  }
  app.zoom = { scale: s1, x, y }
  nextTick(app.updateMaskBox)
}

app.zoomPanStart = (ev) => {
  if (ev.button !== 0 || app.zoom.scale <= 1.001 || app.maskEditing) return
  ev.preventDefault()  // 阻止浏览器把画面当作图片拖拽，否则会打断平移并触发导入提示
  app.zoomDragging = true
  app.zoomStart = { x: ev.clientX, y: ev.clientY, tx: app.zoom.x, ty: app.zoom.y }
  try { ev.currentTarget.setPointerCapture(ev.pointerId) } catch (e) { /* 合成事件可能没有真实 pointerId */ }
}

app.zoomPanMove = (ev) => {
  if (!app.zoomDragging || !app.zoomStart) return
  app.zoom = {
    ...app.zoom,
    x: app.zoomStart.tx + (ev.clientX - app.zoomStart.x),
    y: app.zoomStart.ty + (ev.clientY - app.zoomStart.y),
  }
  app.updateMaskBox()
}

app.zoomPanEnd = (ev) => {
  app.zoomDragging = false
  try { ev.currentTarget.releasePointerCapture(ev.pointerId) } catch (e) { /* 同上 */ }
}

// ---------- 调色 / 蒙版 ----------
app.resetGrading = () => { Object.assign(app.grading, makeGrading()) }

// 参与渲染 / 导出的蒙版：已启用的列表项 + 正在绘制的草稿
app.allMasks = () => {
  const list = app.masks.filter(m => m.enabled)
  if (app.maskDraft && app.maskDraft.enabled) list.push(app.maskDraft)
  return list
}

// 传给后端（URL 查询串）时压缩点数，避免缩略图 URL 过长
app.masksParam = () => {
  const q = (v) => Math.round(v * 10000) / 10000
  const point = (p) => ({ x: q(p.x), y: q(p.y) })
  return JSON.stringify(app.allMasks().map(m => ({
    name: m.name, enabled: m.enabled, invert: !!m.invert,
    nodes: (m.nodes || []).map(n => ({
      name: n.name, op: n.op, enabled: n.enabled, shape: n.shape,
      cx: q(n.cx), cy: q(n.cy), angle: q(n.angle), size: q(n.size),
      aspect: q(n.aspect), feather: q(n.feather), invert: n.invert,
      brush_size: q(n.brush_size),
      strokes: (n.strokes || []).map(s => s.map(point)),
      pen_points: (n.pen_points || []).map(point),
    })),
    grading: m.grading,
  })))
}

// 新建蒙版：未在编辑时创建草稿；已在编辑时把该形状作为新选区节点加入当前蒙版
app.newMask = (shape) => {
  if (app.maskEditing) { app.addNode(shape); return }
  app.maskId = ''
  app.maskDraft = makeMask(shape)
}

// 显式新建：始终创建一张新蒙版（默认圆形选区）
app.createMask = () => {
  app.maskId = ''
  app.maskDraft = makeMask('radial')
}

// 向当前蒙版追加选区节点，并切换为它的编辑状态
app.addNode = (shape = 'radial', op = 'add') => {
  const m = app.mask
  if (!m || !m.nodes) return
  if (m.nodes.length >= 12) return
  const node = makeNode(shape, op)
  m.nodes.push(node)
  m.activeNodeId = node.id
}

app.selectNode = (node) => {
  if (!node || !app.mask.nodes) return
  app.mask.activeNodeId = node.id
}

// 删除节点；仅剩一个节点时改为重置几何，保证蒙版始终可用
app.removeNode = (node) => {
  const m = app.mask
  if (!m || !m.nodes || !node) return
  const i = m.nodes.findIndex(n => n.id === node.id)
  if (i < 0) return
  if (m.nodes.length <= 1) {
    app.resetNodeGeo(node)
    return
  }
  m.nodes.splice(i, 1)
  if (m.activeNodeId === node.id) {
    m.activeNodeId = m.nodes[Math.min(i, m.nodes.length - 1)].id
  }
}

// 选中已确认的蒙版继续编辑；再次点击取消选中
app.selectMask = (m) => {
  if (!m) return
  app.maskDraft = null
  app.maskId = app.maskId === m.id ? '' : m.id
}

app.confirmMask = () => {
  const d = app.maskDraft
  if (!d) return
  app.masks.push(d)
  app.maskDraft = null
  app.maskId = d.id
}

app.deleteMask = (m) => {
  if (!m) return
  if (app.maskDraft && m.id === app.maskDraft.id) { app.maskDraft = null; return }
  const i = app.masks.findIndex(x => x.id === m.id)
  if (i >= 0) app.masks.splice(i, 1)
  if (app.maskId === m.id) app.maskId = ''
}

// 只重置当前节点的几何，保留组合结构与蒙版调色参数
app.resetNodeGeo = (node) => {
  const n = node || app.activeNode
  Object.assign(n, {
    shape: n.shape, cx: 0.5, cy: 0.5, angle: 0,
    size: 0.35, aspect: 0.6, feather: 0.25, invert: false,
  })
  n.strokes = []
  n.pen_points = []
}

app.resetMaskGeo = (shape) => {
  const n = app.activeNode
  if (shape) n.shape = shape
  app.resetNodeGeo(n)
}

app.resetMask = () => app.resetMaskGeo()

// 钢笔：点中已有顶点则拖动该点，否则新增顶点（新增后按住即可继续拖动调整）
const PEN_HIT = 0.02
const penHitIndex = (x, y) => {
  let best = -1
  let bestD = PEN_HIT
  app.activeNode.pen_points.forEach((p, i) => {
    const d = Math.hypot(p.x - x, p.y - y)
    if (d < bestD) { bestD = d; best = i }
  })
  return best
}

app.maskPaintStart = (x, y) => {
  const n = app.activeNode
  if (n.shape === 'brush') {
    n.strokes.push([{ x, y }])
    app.maskDragging = true
  } else if (n.shape === 'pen') {
    const hit = penHitIndex(x, y)
    if (hit >= 0) {
      app.penDragIndex = hit
    } else {
      n.pen_points.push({ x, y })
      app.penDragIndex = n.pen_points.length - 1
    }
  }
}

app.maskPaintMove = (x, y) => {
  const n = app.activeNode
  if (n.shape === 'pen' && app.penDragIndex >= 0) {
    const p = n.pen_points[app.penDragIndex]
    if (p) { p.x = x; p.y = y }
    return
  }
  if (!app.maskDragging || n.shape !== 'brush') return
  const stroke = n.strokes[n.strokes.length - 1]
  if (!stroke) return
  const last = stroke[stroke.length - 1]
  if (last && Math.hypot(last.x - x, last.y - y) < 0.003) return
  stroke.push({ x, y })
}

app.maskPaintEnd = () => {
  app.maskDragging = false
  app.penDragIndex = -1
}

app.clearMaskPath = () => {
  app.activeNode.strokes = []
  app.activeNode.pen_points = []
}

app.penUndo = () => { app.activeNode.pen_points.pop() }

// 蒙版引导层与画面实际显示区域对齐
app.updateMaskBox = () => {
  const host = app.playerEl, el = app.mediaEl
  if (!host || !el || !el.getBoundingClientRect) { app.maskBox = null; return }
  const r = el.getBoundingClientRect(), h = host.getBoundingClientRect()
  if (!r.width || !r.height) { app.maskBox = null; return }
  app.maskBox = {
    left: r.left - h.left, top: r.top - h.top,
    width: r.width, height: r.height,
  }
}

// ---------- 预览 ----------
app.onThumbLoad = (ev) => {
  app.thumbLoading = false
  const el = ev.target
  if (el.naturalWidth && el.naturalHeight) app.mediaAspect = el.naturalWidth / el.naturalHeight
  nextTick(app.updateMaskBox)
}

app.onMediaMeta = (ev) => {
  const el = ev.target
  if (el.videoWidth && el.videoHeight) app.mediaAspect = el.videoWidth / el.videoHeight
  if (el.duration) app.playDuration = el.duration
  app.playTime = 0
  app.playing = !el.paused
  nextTick(app.updateMaskBox)
}

app.thumbUrl = (opts) => {
  const o = Object.assign({ path: app.currentPath, w: 480 }, opts || {})
  if (!o.path) return ''
  const q = new URLSearchParams({ path: o.path, w: o.w })
  if (o.lut) {
    q.set('lut', o.lut)
    q.set('strength', o.strength !== undefined ? o.strength : 100)
    if (o.lut2) {
      // 卡片预览时直接指定叠加的个性化 LUT，不依赖当前是否已启用二级调色
      q.set('lut2', o.lut2)
      q.set('strength2', o.strength2 !== undefined ? o.strength2 : 100)
    } else if (!o.noSecond && app.useSecondLut && app.lut2Path) {
      q.set('lut2', app.lut2Path)
      q.set('strength2', app.lutStrength2)
    }
  }
  // 主预览需要体现当前调色与蒙版；滤镜卡片保持纯 LUT 效果，避免批量重渲染
  if (o.full) {
    if (app.hasGrading) q.set('grading', JSON.stringify(app.grading))
    if (app.allMasks().length) q.set('masks', app.masksParam())
  }
  return '/api/thumb?' + q.toString()
}

app.activeLutPath = () => app.customLut || app.lutPath

app.setCurrentThumb = () => {
  const lut = app.activeLutPath()
  app.mainThumbUrl = lut
    ? app.thumbUrl({ lut, strength: app.lutStrength, w: 560, full: true })
    : app.thumbUrl({ w: 560, full: true })
  app.previewingLut = !!lut
}

app.setOriginalThumb = () => {
  if (!app.currentPath) return
  app.mainThumbUrl = app.thumbUrl({ w: 560 })
  app.previewingLut = false
}

app.refreshPreview = (immediate) => {
  app.stopPlay()
  if (!app.currentPath) return
  clearTimeout(app.thumbTimer)
  app.thumbLoading = true
  // 拖动滑杆时按最短间隔节流刷新，松手（immediate）立即出图
  const wait = immediate ? 0 : Math.max(0, 250 - (Date.now() - (app.lastThumbAt || 0)))
  app.thumbTimer = setTimeout(() => {
    app.lastThumbAt = Date.now()
    if (app.compare) app.setOriginalThumb()
    else app.setCurrentThumb()
    if (!app.currentPath) app.thumbLoading = false
  }, wait)
}

// 调用系统文件夹选择框（服务端弹窗），结果写回输入框
app.pickDir = async (target, title) => {
  const initial = target === 'input' ? app.inputDir : app.customDir
  app.pickingDir = true
  try {
    const r = await fetch('/api/pick_dir', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ title, initial }),
    })
    const d = await r.json().catch(() => ({}))
    if (!r.ok) return ElMessage.error(d.error || '打开选择框失败')
    const p = (d.path || '').trim()
    if (!p) return
    if (target === 'input') app.inputDir = p
    else app.customDir = p
  } catch (e) {
    ElMessage.error('打开选择框失败：' + e.message)
  } finally {
    app.pickingDir = false
  }
}

app.onThumbError = () => { app.thumbLoading = false }

app.onPlayError = () => {
  app.previewLoading = false
  app.playUrl = ''
  ElMessage.error('浏览器无法播放该预览')
}

// ---------- 扫描 / LUT / GPU ----------
app.scanDir = async () => {
  const dir = (app.inputDir || '').trim().replace(/^"|"$/g, '')
  if (!dir) return ElMessage.warning('请先填写视频文件夹路径')
  app.scanning = true
  try {
    const r = await fetch('/api/list_videos?dir=' + encodeURIComponent(dir))
    const d = await r.json()
    if (d.error) { ElMessage.error(d.error); app.files = [] }
    else {
      app.files = d.files
      app.sel = d.files.map(f => f.path)
      if (d.files.length) { app.currentPath = d.files[0].path; app.refreshPreview() }
      ElMessage.success(`扫描完成，共 ${d.files.length} 个视频`)
    }
    localStorage.setItem('osmo.lastDir', dir)
  } finally {
    app.scanning = false
    nextTick(app.updateBinNav)
  }
}

// ---------- 拖拽 / 粘贴导入 ----------
const VIDEO_RE = /\.(mp4|mov|mkv|avi|mxf|webm)$/i

const uploadFiles = (form) => new Promise((resolve, reject) => {
  const xhr = new XMLHttpRequest()
  xhr.open('POST', '/api/import_files')
  xhr.upload.onprogress = (e) => {
    if (e.lengthComputable) app.importPct = Math.round((e.loaded / e.total) * 100)
  }
  xhr.onload = () => {
    let d = {}
    try { d = JSON.parse(xhr.responseText || '{}') } catch (e) { /* 非 JSON 响应 */ }
    if (xhr.status >= 200 && xhr.status < 300) resolve(d)
    else reject(new Error(d.error || `HTTP ${xhr.status}`))
  }
  xhr.onerror = () => reject(new Error('网络错误'))
  xhr.send(form)
})

// 浏览器只给文件内容、拿不到原始路径，所以统一复制到 _imports/ 后再加入素材列表
app.importFiles = async (fileList, source) => {
  if (app.importing) return
  const files = Array.from(fileList || []).filter(f => VIDEO_RE.test(f.name))
  if (!files.length) return ElMessage.warning('仅支持视频文件：mp4 / mov / mkv / avi / mxf / webm')
  app.importing = true
  app.importPct = 0
  const form = new FormData()
  files.forEach(f => form.append('files', f, f.name))
  try {
    const d = await uploadFiles(form)
    const added = d.files || []
    if (!added.length) return ElMessage.warning('没有可导入的视频文件')
    let first = ''
    added.forEach(f => {
      if (app.files.some(x => x.path === f.path)) return
      app.files.push(f)
      app.sel.push(f.path)
      if (!first) first = f.path
    })
    if (!app.currentPath && first) app.currentPath = first
    ElMessage.success(`${source}导入 ${added.length} 个视频（已复制到 _imports/）`)
    app.refreshPreview()
    nextTick(app.updateBinNav)
  } catch (e) {
    ElMessage.error('导入失败：' + e.message)
  } finally {
    app.importing = false
    app.importPct = 0
  }
}

app.onWindowDragOver = (e) => {
  if (app.zoomDragging) return  // 正在拖动平移画面，不当作文件导入
  if (!e.dataTransfer || !Array.from(e.dataTransfer.types || []).includes('Files')) return
  e.preventDefault()
  e.dataTransfer.dropEffect = 'copy'
  app.dragOver = true
}

// 只有真正离开窗口时才收起提示，避免掠过子元素时闪烁
app.onWindowDragLeave = (e) => {
  if (e.clientX <= 0 || e.clientY <= 0 || e.clientX >= window.innerWidth || e.clientY >= window.innerHeight) {
    app.dragOver = false
  }
}

app.onWindowDrop = (e) => {
  if (app.zoomDragging) return
  if (!e.dataTransfer || !e.dataTransfer.files || !e.dataTransfer.files.length) return
  e.preventDefault()
  app.dragOver = false
  app.importFiles(e.dataTransfer.files, '拖拽')
}

app.onWindowPaste = (e) => {
  const cd = e.clipboardData
  const files = Array.from((cd && cd.files) || [])
  if (!files.some(f => VIDEO_RE.test(f.name))) return
  e.preventDefault()
  app.importFiles(files, '粘贴')
}

app.toggleClip = (f) => {
  app.currentPath = f.path
  const i = app.sel.indexOf(f.path)
  if (i >= 0) app.sel.splice(i, 1); else app.sel.push(f.path)
  app.refreshPreview()
}

app.selectAll = () => { app.sel = app.files.map(f => f.path) }

app.loadLuts = async () => {
  const r = await fetch('/api/luts')
  const d = await r.json()
  app.luts = d.luts
  if (!app.lutPath && app.luts.length) app.lutPath = app.luts[0].path
}

app.loadGpuStatus = async () => {
  try {
    const r = await fetch('/api/gpu_status')
    const d = await r.json()
    app.gpuOk = d.available
    app.gpuMsg = d.message || ''
    app.gpuChecked = true
    if (!app.gpuOk) app.useGpu = false
  } catch (e) { app.gpuChecked = true; app.useGpu = false }
  if (!app.gpuOk) ElMessage.warning('未检测到可用的 GPU，已切换为 CPU 渲染（功能完整，速度较慢）')
}

// 主界面的渲染方式：GPU 走显卡解码/编码，CPU 兼容没有显卡的设备
app.setRenderGpu = (gpu) => {
  if (gpu && !app.gpuOk) {
    ElMessage.warning('当前设备没有可用的 NVIDIA GPU，继续使用 CPU 渲染')
    return
  }
  if (app.useGpu === gpu) return
  app.useGpu = gpu
  app.stopPlay()  // 旧的预览片段是用另一种方式生成的，切换后重新生成
}

// 点击个性化 LUT 卡片：作为二级叠加应用
app.applyLookLut = (path) => {
  app.lut2Path = path
  app.useSecondLut = true
  app.refreshPreview()
}
app.onLutUploaded = (resp) => {
  ElMessage.success('LUT 上传成功：' + resp.name)
  app.loadLuts().then(() => app.applyLookLut(resp.path))
}

app.onLutUploadError = () => { ElMessage.error('LUT 上传失败，仅支持 .cube 文件') }

// ---------- 播放 ----------
app.playGraded = async () => {
  if (!app.currentPath) return
  app.previewLoading = true
  app.previewText = '正在生成调色预览（首次需几秒）…'
  try {
    const r = await fetch('/api/preview_graded', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        path: app.currentPath,
        lut_path: app.activeLutPath(),
        lut_strength: app.lutStrength,
        lut_path2: app.useSecondLut ? app.lut2Path : '',
        lut_strength2: app.lutStrength2,
        grading: app.grading,
        masks: app.allMasks(),
        render_gpu: app.useGpu,
      }),
    })
    const d = await r.json()
    if (d.error) { ElMessage.error(d.error); return }
    app.playTime = 0
    app.playDuration = 0
    app.playUrl = d.url
    app.previewingLut = true
  } catch (e) {
    ElMessage.error('预览请求失败：' + e)
  } finally {
    app.previewLoading = false
  }
}

app.playOriginal = async () => {
  if (!app.currentPath) return
  app.previewLoading = true
  app.previewText = '正在准备原片预览（HEVC 首次需转码）…'
  try {
    const r = await fetch('/api/preview/ensure', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ path: app.currentPath }),
    })
    const d = await r.json()
    if (d.error) { ElMessage.error(d.error); return }
    app.playTime = 0
    app.playDuration = 0
    app.playUrl = d.url
    app.previewingLut = false
  } catch (e) {
    ElMessage.error('预览请求失败：' + e)
  } finally {
    app.previewLoading = false
  }
}

app.stopPlay = () => {
  app.playUrl = ''
  app.playTime = 0
  app.playDuration = 0
  app.playing = false
}

app.onPlayEnded = () => {
  app.playing = false
  app.playTime = app.playDuration
}

app.onTimeUpdate = () => {
  const el = app.mediaEl
  if (!el || !el.duration) return
  app.playDuration = el.duration
  app.playTime = el.currentTime
}

app.seekTo = (v) => {
  const el = app.mediaEl
  if (!el || !el.duration) return
  el.currentTime = Math.min(el.duration, Math.max(0, Number(v) || 0))
  app.playTime = el.currentTime
}

app.togglePlay = () => {
  const el = app.mediaEl
  if (!el) return
  if (el.paused) el.play(); else el.pause()
}

app.skip = (sec) => {
  const el = app.mediaEl
  if (!el || !el.duration) return
  el.currentTime = Math.min(el.duration, Math.max(0, el.currentTime + sec))
  app.playTime = el.currentTime
}

// ---------- 导出 / 任务 ----------
app.start = async () => {
  const r = await fetch('/api/convert', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      files: app.sel,
      lut_path: app.activeLutPath(),
      lut_path2: app.useSecondLut ? app.lut2Path : '',
      lut_strength: app.lutStrength,
      lut_strength2: app.lutStrength2,
      output_mode: app.outputMode,
      custom_dir: app.customDir,
      resolution: app.resolution,
      use_gpu: app.useGpu,
      quality: app.quality,
      bit_depth: app.bitDepth,
      grading: app.grading,
      masks: app.allMasks(),
    }),
  })
  const d = await r.json()
  if (d.error) { ElMessage.error(d.error); return }
  ElMessage.success('导出任务已开始')
  app.tab = 'tasks'
  app.poll()
}

app.poll = async () => {
  try {
    const r = await fetch('/api/batches')
    const d = await r.json()
    app.batches = d.batches
    const running = app.batches.some(b => b.status === 'running')
    clearTimeout(app.timer)
    if (running) app.timer = setTimeout(app.poll, 1000)
  } catch (e) { /* 忽略 */ }
}

app.stopAll = async () => {
  try {
    await ElMessageBox.confirm(
      '将终止正在转换的文件并清空等待队列，未完成的半成品会被删除（已完成的保留）。',
      '暂停全部导出',
      { confirmButtonText: '暂停全部', cancelButtonText: '取消', type: 'warning' }
    )
  } catch (e) { return }
  await fetch('/api/stop_all', { method: 'POST' })
  ElMessage.info('已暂停全部导出')
  app.poll()
}

app.tagType = (s) => ({ pending: 'info', converting: 'warning', done: 'success', error: 'danger', skipped: 'info', cancelled: 'info' }[s] || 'info')
app.statusText = (s) => ({ pending: '等待', converting: '转换中', done: '完成', error: '失败', skipped: '已存在', cancelled: '已取消' }[s] || s)
app.progStatus = (s) => s === 'done' ? 'success' : (s === 'error' ? 'exception' : undefined)

// ---------- watchers ----------
watch(() => app.files, () => nextTick(app.updateBinNav))
watch(() => app.lutPath, (v, old) => {
  // LUT 列表首次加载会赋值 lutPath，此时只刷新缩略图，避免打断正在播放的预览
  if (!old && app.playUrl) { app.setCurrentThumb(); return }
  app.refreshPreview()
})
watch(() => app.lutStrength, () => app.refreshPreview())
watch(() => app.lut2Path, () => app.refreshPreview())
watch(() => app.lutStrength2, () => app.refreshPreview())
watch(() => app.useSecondLut, () => app.refreshPreview())
watch(() => app.customLut, () => app.refreshPreview())
watch(() => app.grading, () => app.refreshPreview(), { deep: true })
watch(() => app.masks, () => {
  nextTick(app.updateMaskBox)
  app.refreshPreview()
}, { deep: true })
watch(() => app.maskDraft, () => {
  nextTick(app.updateMaskBox)
  app.refreshPreview()
}, { deep: true })
watch(() => app.mainThumbUrl, () => nextTick(app.updateMaskBox))
watch(() => app.playUrl, () => nextTick(app.updateMaskBox))
watch(() => app.tab, () => nextTick(app.updateMaskBox))
watch(() => app.currentPath, () => app.resetZoom())
watch(() => app.compare, (v) => {
  if (v) app.setOriginalThumb()
  else app.setCurrentThumb()
})

provide('app', app)

onMounted(() => {
  const last = localStorage.getItem('osmo.lastDir')
  if (last) app.inputDir = last
  app.loadLuts()
  app.loadGpuStatus()
  app.poll()
  if (last) app.scanDir()
  window.addEventListener('resize', app.updateMaskBox)
  window.addEventListener('resize', app.updateBinNav)
  window.addEventListener('dragover', app.onWindowDragOver)
  window.addEventListener('dragleave', app.onWindowDragLeave)
  window.addEventListener('drop', app.onWindowDrop)
  window.addEventListener('paste', app.onWindowPaste)
})

onBeforeUnmount(() => {
  window.removeEventListener('resize', app.updateMaskBox)
  window.removeEventListener('resize', app.updateBinNav)
  window.removeEventListener('dragover', app.onWindowDragOver)
  window.removeEventListener('dragleave', app.onWindowDragLeave)
  window.removeEventListener('drop', app.onWindowDrop)
  window.removeEventListener('paste', app.onWindowPaste)
})
</script>

<template>
  <!-- 顶栏 -->
  <TopBar />

  <div class="main">
    <!-- 左侧栏 -->
    <LeftRail />

    <!-- 预览区 -->
    <PlayerStage />

    <!-- 左右拖动：调整右侧属性面板宽度 -->
    <div class="resizer v" title="拖动调整面板宽度" @pointerdown="app.startResize('inspector', $event)"></div>

    <!-- 右侧属性面板 -->
    <aside class="inspector" :style="{ width: app.layout.inspector + 'px' }">
      <div class="panel-head">{{ app.tabTitle }}</div>

      <MaterialPanel v-show="app.tab === 'media'" />
      <FiltersPanel v-show="app.tab === 'filter'" />
      <GradingPanel v-show="app.tab === 'color'" />
      <ExportPanel v-show="app.tab === 'export'" />
      <TasksPanel v-show="app.tab === 'tasks'" />
    </aside>
  </div>

  <!-- 上下拖动：调整素材条高度（缩略图等比放大） -->
  <div class="resizer h" title="拖动调整素材条高度" @pointerdown="app.startResize('bin', $event)"></div>

  <!-- 底部素材条 -->
  <Filmstrip />

  <!-- 拖拽 / 粘贴导入提示 -->
  <div v-if="app.dragOver || app.importing" class="drop-overlay">
    <div class="drop-card">
      <div class="drop-title">{{ app.importing ? '正在导入视频…' : '松开鼠标导入视频' }}</div>
      <div class="drop-sub">
        {{ app.importing ? app.importPct + '%' : '支持 mp4 / mov / mkv / avi / mxf / webm，可一次拖入多个文件' }}
      </div>
      <el-progress v-if="app.importing" :percentage="app.importPct" :stroke-width="6" :show-text="false" />
    </div>
  </div>
</template>
