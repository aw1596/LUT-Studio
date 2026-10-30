<script setup>
import { ref, computed, inject } from 'vue'
import ColorWheel from './ColorWheel.vue'
import CurveEditor from './CurveEditor.vue'

// 通用调色控件：既用于全局「一级调色」，也用于每个蒙版的独立调色
const props = defineProps({
  g: { type: Object, required: true },
  showSharpen: { type: Boolean, default: true },
})

const app = inject('app')
const open = ref(['base'])
const curveChannel = ref('master')
const hslPick = ref('reds')

const hslColors = [
  { key: 'reds', label: '红', css: '#ff4d4d' },
  { key: 'oranges', label: '橙', css: '#ff9a2e' },
  { key: 'yellows', label: '黄', css: '#ffdc35' },
  { key: 'greens', label: '绿', css: '#43d17a' },
  { key: 'aquas', label: '青', css: '#31d7d7' },
  { key: 'blues', label: '蓝', css: '#3d7eff' },
  { key: 'purples', label: '紫', css: '#9a6bff' },
  { key: 'magentas', label: '洋红', css: '#de5fe0' },
]

const curveChannels = [
  { key: 'master', label: 'RGB', css: '#ffffff' },
  { key: 'r', label: 'R', css: '#ff6b6b' },
  { key: 'g', label: 'G', css: '#4ade80' },
  { key: 'b', label: 'B', css: '#6a9cff' },
]

const currentCurve = computed({
  get: () => props.g.curve[curveChannel.value],
  set: (v) => { props.g.curve[curveChannel.value] = v },
})
const curveColor = computed(() => (curveChannels.find(c => c.key === curveChannel.value) || {}).css || '#fff')

function hueCss(h) {
  return `hsl(${Math.round(h)}, 85%, 55%)`
}

// 重置：只动本组参数，避免影响其他分组
const blankCurve = () => [{ x: 0, y: 0 }, { x: 1, y: 1 }]
const blankHsl = () => ({
  reds: { h: 0, s: 0, l: 0 }, oranges: { h: 0, s: 0, l: 0 },
  yellows: { h: 0, s: 0, l: 0 }, greens: { h: 0, s: 0, l: 0 },
  aquas: { h: 0, s: 0, l: 0 }, blues: { h: 0, s: 0, l: 0 },
  purples: { h: 0, s: 0, l: 0 }, magentas: { h: 0, s: 0, l: 0 },
})

function resetBase() {
  Object.assign(props.g, {
    temperature: 0, tint: 0, exposure: 0, contrast: 0,
    highlights: 0, shadows: 0, whites: 0, blacks: 0,
    saturation: 0, vibrance: 0,
    lift: { x: 0, y: 0 }, gamma: { x: 0, y: 0 }, gain: { x: 0, y: 0 },
  })
  if (props.showSharpen) props.g.sharpness = 0
}
function resetCurveGroup() {
  props.g.curve = { master: blankCurve(), r: blankCurve(), g: blankCurve(), b: blankCurve() }
  props.g.curve_regions = { shadows: 0, midtones: 0, highlights: 0 }
}
function resetHsl() { props.g.hsl = blankHsl() }
function resetSplit() {
  props.g.split = { shadow_hue: 40, shadow_sat: 0, highlight_hue: 210, highlight_sat: 0, balance: 0 }
}
function resetCalibration() {
  props.g.calibration = { red_hue: 0, red_sat: 0, green_hue: 0, green_sat: 0, blue_hue: 0, blue_sat: 0 }
}
</script>

<template>
  <el-collapse v-model="open" class="grading-collapse">
    <!-- 一级调色 -->
    <el-collapse-item name="base" title="一级调色">
      <div class="slider-row">
        <span>色温</span>
        <el-slider v-model="g.temperature" :min="-100" :max="100" :step="1" :show-tooltip="false" @change="app.refreshPreview(true)"></el-slider>
        <b>{{ app.fmtNum(g.temperature, 0) }}</b>
      </div>
      <div class="slider-row">
        <span>色调</span>
        <el-slider v-model="g.tint" :min="-100" :max="100" :step="1" :show-tooltip="false" @change="app.refreshPreview(true)"></el-slider>
        <b>{{ app.fmtNum(g.tint, 0) }}</b>
      </div>
      <div class="slider-row">
        <span>曝光</span>
        <el-slider v-model="g.exposure" :min="-3" :max="3" :step="0.05" :show-tooltip="false" @change="app.refreshPreview(true)"></el-slider>
        <b>{{ app.fmtNum(g.exposure, 2) }}</b>
      </div>
      <div class="slider-row">
        <span>对比度</span>
        <el-slider v-model="g.contrast" :min="-100" :max="100" :step="1" :show-tooltip="false" @change="app.refreshPreview(true)"></el-slider>
        <b>{{ app.fmtNum(g.contrast, 0) }}</b>
      </div>
      <div class="slider-row">
        <span>高光</span>
        <el-slider v-model="g.highlights" :min="-100" :max="100" :step="1" :show-tooltip="false" @change="app.refreshPreview(true)"></el-slider>
        <b>{{ app.fmtNum(g.highlights, 0) }}</b>
      </div>
      <div class="slider-row">
        <span>阴影</span>
        <el-slider v-model="g.shadows" :min="-100" :max="100" :step="1" :show-tooltip="false" @change="app.refreshPreview(true)"></el-slider>
        <b>{{ app.fmtNum(g.shadows, 0) }}</b>
      </div>
      <div class="slider-row">
        <span>白色</span>
        <el-slider v-model="g.whites" :min="-100" :max="100" :step="1" :show-tooltip="false" @change="app.refreshPreview(true)"></el-slider>
        <b>{{ app.fmtNum(g.whites, 0) }}</b>
      </div>
      <div class="slider-row">
        <span>黑色</span>
        <el-slider v-model="g.blacks" :min="-100" :max="100" :step="1" :show-tooltip="false" @change="app.refreshPreview(true)"></el-slider>
        <b>{{ app.fmtNum(g.blacks, 0) }}</b>
      </div>
      <div class="slider-row">
        <span>饱和度</span>
        <el-slider v-model="g.saturation" :min="-100" :max="100" :step="1" :show-tooltip="false" @change="app.refreshPreview(true)"></el-slider>
        <b>{{ app.fmtNum(g.saturation, 0) }}</b>
      </div>
      <div class="slider-row">
        <span>自然饱和度</span>
        <el-slider v-model="g.vibrance" :min="-100" :max="100" :step="1" :show-tooltip="false" @change="app.refreshPreview(true)"></el-slider>
        <b>{{ app.fmtNum(g.vibrance, 0) }}</b>
      </div>
      <div class="slider-row" v-if="showSharpen">
        <span>锐化</span>
        <el-slider v-model="g.sharpness" :min="0" :max="100" :step="1" :show-tooltip="false" @change="app.refreshPreview(true)"></el-slider>
        <b>{{ app.fmtNum(g.sharpness, 0) }}</b>
      </div>

      <div class="group-title">色轮 · 暗部 / 中间调 / 高光</div>
      <div class="wheels">
        <ColorWheel v-model="g.lift" label="暗部"></ColorWheel>
        <ColorWheel v-model="g.gamma" label="中间调"></ColorWheel>
        <ColorWheel v-model="g.gain" label="高光"></ColorWheel>
      </div>
      <div class="hint">拖动圆点给暗部 / 中间调 / 高光染色，双击色轮归零。</div>

      <div class="row mt" style="justify-content: space-between;">
        <span class="hint" style="margin:0">调色在 LUT 之前生效。</span>
        <el-button size="small" text @click="resetBase">重置一级调色</el-button>
      </div>
    </el-collapse-item>

    <!-- 色调曲线 -->
    <el-collapse-item name="curve" title="色调曲线">
      <div class="seg">
        <button v-for="c in curveChannels" :key="c.key"
                :class="{ on: curveChannel === c.key }"
                :style="curveChannel === c.key ? { borderColor: c.css, color: c.css } : {}"
                @click="curveChannel = c.key">{{ c.label }}</button>
      </div>
      <CurveEditor v-model="currentCurve" :color="curveColor" class="mt-curve"></CurveEditor>

      <div class="group-title">区域调整</div>
      <div class="slider-row">
        <span>暗部</span>
        <el-slider v-model="g.curve_regions.shadows" :min="-100" :max="100" :step="1" :show-tooltip="false" @change="app.refreshPreview(true)"></el-slider>
        <b>{{ app.fmtNum(g.curve_regions.shadows, 0) }}</b>
      </div>
      <div class="slider-row">
        <span>中间调</span>
        <el-slider v-model="g.curve_regions.midtones" :min="-100" :max="100" :step="1" :show-tooltip="false" @change="app.refreshPreview(true)"></el-slider>
        <b>{{ app.fmtNum(g.curve_regions.midtones, 0) }}</b>
      </div>
      <div class="slider-row">
        <span>高光</span>
        <el-slider v-model="g.curve_regions.highlights" :min="-100" :max="100" :step="1" :show-tooltip="false" @change="app.refreshPreview(true)"></el-slider>
        <b>{{ app.fmtNum(g.curve_regions.highlights, 0) }}</b>
      </div>

      <div class="row mt" style="justify-content: space-between;">
        <span class="hint" style="margin:0">单击空白新增点，拖动调整，双击点删除。</span>
        <el-button size="small" text @click="resetCurveGroup">重置曲线</el-button>
      </div>
    </el-collapse-item>

    <!-- HSL / 颜色 -->
    <el-collapse-item name="hsl" title="HSL / 颜色">
      <div class="hsl-chips">
        <button v-for="c in hslColors" :key="c.key" class="hsl-chip"
                :class="{ on: hslPick === c.key }" :style="{ background: c.css }"
                :title="c.label" @click="hslPick = c.key"></button>
      </div>
      <div class="slider-row mt">
        <span>色相</span>
        <el-slider v-model="g.hsl[hslPick].h" :min="-100" :max="100" :step="1" :show-tooltip="false" @change="app.refreshPreview(true)"></el-slider>
        <b>{{ app.fmtNum(g.hsl[hslPick].h, 0) }}</b>
      </div>
      <div class="slider-row">
        <span>饱和度</span>
        <el-slider v-model="g.hsl[hslPick].s" :min="-100" :max="100" :step="1" :show-tooltip="false" @change="app.refreshPreview(true)"></el-slider>
        <b>{{ app.fmtNum(g.hsl[hslPick].s, 0) }}</b>
      </div>
      <div class="slider-row">
        <span>明度</span>
        <el-slider v-model="g.hsl[hslPick].l" :min="-100" :max="100" :step="1" :show-tooltip="false" @change="app.refreshPreview(true)"></el-slider>
        <b>{{ app.fmtNum(g.hsl[hslPick].l, 0) }}</b>
      </div>
      <div class="row mt" style="justify-content: space-between;">
        <span class="hint" style="margin:0">先选中颜色，再调整它专属的色相 / 饱和 / 明度。</span>
        <el-button size="small" text @click="resetHsl">重置</el-button>
      </div>
    </el-collapse-item>

    <!-- 分离色调 -->
    <el-collapse-item name="split" title="分离色调">
      <div class="slider-row">
        <span><i class="swatch" :style="{ background: hueCss(g.split.shadow_hue) }"></i>阴影色相</span>
        <el-slider v-model="g.split.shadow_hue" :min="0" :max="359" :step="1" :show-tooltip="false" @change="app.refreshPreview(true)"></el-slider>
        <b>{{ app.fmtNum(g.split.shadow_hue, 0) }}°</b>
      </div>
      <div class="slider-row">
        <span>阴影饱和</span>
        <el-slider v-model="g.split.shadow_sat" :min="0" :max="100" :step="1" :show-tooltip="false" @change="app.refreshPreview(true)"></el-slider>
        <b>{{ app.fmtNum(g.split.shadow_sat, 0) }}</b>
      </div>
      <div class="slider-row">
        <span><i class="swatch" :style="{ background: hueCss(g.split.highlight_hue) }"></i>高光色相</span>
        <el-slider v-model="g.split.highlight_hue" :min="0" :max="359" :step="1" :show-tooltip="false" @change="app.refreshPreview(true)"></el-slider>
        <b>{{ app.fmtNum(g.split.highlight_hue, 0) }}°</b>
      </div>
      <div class="slider-row">
        <span>高光饱和</span>
        <el-slider v-model="g.split.highlight_sat" :min="0" :max="100" :step="1" :show-tooltip="false" @change="app.refreshPreview(true)"></el-slider>
        <b>{{ app.fmtNum(g.split.highlight_sat, 0) }}</b>
      </div>
      <div class="slider-row">
        <span>平衡</span>
        <el-slider v-model="g.split.balance" :min="-100" :max="100" :step="1" :show-tooltip="false" @change="app.refreshPreview(true)"></el-slider>
        <b>{{ app.fmtNum(g.split.balance, 0) }}</b>
      </div>
      <div class="row mt" style="justify-content: space-between;">
        <span class="hint" style="margin:0">给暗部与高光分别染色，平衡控制交界位置。</span>
        <el-button size="small" text @click="resetSplit">重置</el-button>
      </div>
    </el-collapse-item>

    <!-- 校准 -->
    <el-collapse-item name="cal" title="校准">
      <div class="group-title" style="margin-top:2px">红原色</div>
      <div class="slider-row">
        <span>色相</span>
        <el-slider v-model="g.calibration.red_hue" :min="-100" :max="100" :step="1" :show-tooltip="false" @change="app.refreshPreview(true)"></el-slider>
        <b>{{ app.fmtNum(g.calibration.red_hue, 0) }}</b>
      </div>
      <div class="slider-row">
        <span>饱和度</span>
        <el-slider v-model="g.calibration.red_sat" :min="-100" :max="100" :step="1" :show-tooltip="false" @change="app.refreshPreview(true)"></el-slider>
        <b>{{ app.fmtNum(g.calibration.red_sat, 0) }}</b>
      </div>
      <div class="group-title">绿原色</div>
      <div class="slider-row">
        <span>色相</span>
        <el-slider v-model="g.calibration.green_hue" :min="-100" :max="100" :step="1" :show-tooltip="false" @change="app.refreshPreview(true)"></el-slider>
        <b>{{ app.fmtNum(g.calibration.green_hue, 0) }}</b>
      </div>
      <div class="slider-row">
        <span>饱和度</span>
        <el-slider v-model="g.calibration.green_sat" :min="-100" :max="100" :step="1" :show-tooltip="false" @change="app.refreshPreview(true)"></el-slider>
        <b>{{ app.fmtNum(g.calibration.green_sat, 0) }}</b>
      </div>
      <div class="group-title">蓝原色</div>
      <div class="slider-row">
        <span>色相</span>
        <el-slider v-model="g.calibration.blue_hue" :min="-100" :max="100" :step="1" :show-tooltip="false" @change="app.refreshPreview(true)"></el-slider>
        <b>{{ app.fmtNum(g.calibration.blue_hue, 0) }}</b>
      </div>
      <div class="slider-row">
        <span>饱和度</span>
        <el-slider v-model="g.calibration.blue_sat" :min="-100" :max="100" :step="1" :show-tooltip="false" @change="app.refreshPreview(true)"></el-slider>
        <b>{{ app.fmtNum(g.calibration.blue_sat, 0) }}</b>
      </div>
      <div class="row mt" style="justify-content: space-between;">
        <span class="hint" style="margin:0">模拟照片风格的色彩校准，用通道矩阵实现。</span>
        <el-button size="small" text @click="resetCalibration">重置</el-button>
      </div>
    </el-collapse-item>
  </el-collapse>
</template>
