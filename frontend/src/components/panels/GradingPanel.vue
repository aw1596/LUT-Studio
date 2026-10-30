<script setup>
import { ref, inject } from 'vue'
import ColorAdjustments from '../ColorAdjustments.vue'

const app = inject('app')
const open = ref(['mask'])

const shapes = [
  { key: 'linear', label: '线性' },
  { key: 'radial', label: '圆形' },
  { key: 'rect', label: '矩形' },
  { key: 'brush', label: '画笔' },
  { key: 'pen', label: '钢笔' },
]
const shapeLabel = (s) => (shapes.find(x => x.key === s) || {}).label || s
</script>

<template>
  <div class="panel-body">
    <!-- 全局一级调色：与蒙版共用同一套控件 -->
    <ColorAdjustments :g="app.grading"></ColorAdjustments>

    <el-collapse v-model="open" class="grading-collapse">
      <el-collapse-item name="mask" title="蒙版">
        <div class="seg seg5">
          <button v-for="s in shapes" :key="s.key" @click="app.newMask(s.key)">{{ s.label }}</button>
        </div>
        <div class="hint">选择形状新建蒙版，在画面上绘制/移动后「确认」加入列表；可叠加多个蒙版。</div>

        <template v-if="app.masks.length || app.maskDraft">
          <div class="group-title">蒙版列表</div>
          <div class="mask-list">
            <div v-if="app.maskDraft" class="mask-item draft on">
              <span class="mask-name">{{ app.maskDraft.name }}（未确认）</span>
              <span class="mask-shape">{{ shapeLabel(app.maskDraft.shape) }}</span>
              <el-button size="small" text type="primary" @click="app.confirmMask">确认</el-button>
              <el-button size="small" text @click="app.deleteMask(app.maskDraft)">删除</el-button>
            </div>
            <div v-for="m in app.masks" :key="m.id" class="mask-item"
                 :class="{ on: app.maskId === m.id }" @click="app.selectMask(m)">
              <el-checkbox v-model="m.enabled" size="small" @click.stop></el-checkbox>
              <span class="mask-name">{{ m.name }}</span>
              <span class="mask-shape">{{ shapeLabel(m.shape) }}</span>
              <span v-if="app.gradingUsed(m.grading)" class="mask-state">已调色</span>
              <el-button size="small" text @click.stop="app.deleteMask(m)">删除</el-button>
            </div>
          </div>
        </template>

        <!-- 当前蒙版的形状参数 + 独立调色 -->
        <template v-if="app.maskEditing">
          <div class="group-title">编辑 · {{ app.mask.name }}</div>

          <template v-if="app.mask.shape === 'brush'">
            <div class="slider-row">
              <span>笔刷大小</span>
              <el-slider v-model="app.mask.brush_size" :min="0.02" :max="0.4" :step="0.01" :show-tooltip="false"></el-slider>
              <b>{{ app.fmtNum(app.mask.brush_size, 2) }}</b>
            </div>
            <div class="slider-row">
              <span>边缘柔和</span>
              <el-slider v-model="app.mask.feather" :min="0.05" :max="1" :step="0.01" :show-tooltip="false"></el-slider>
              <b>{{ app.fmtNum(app.mask.feather, 2) }}</b>
            </div>
            <div class="hint">在预览画面上按住拖动即可涂抹；同一笔画内可来回涂抹。</div>
          </template>

          <template v-else-if="app.mask.shape === 'pen'">
            <div class="slider-row">
              <span>羽化</span>
              <el-slider v-model="app.mask.feather" :min="0.05" :max="1" :step="0.01" :show-tooltip="false"></el-slider>
              <b>{{ app.fmtNum(app.mask.feather, 2) }}</b>
            </div>
            <div class="hint">在画面上逐点单击勾勒多边形，3 点以上自动闭合填充。</div>
          </template>

          <template v-else>
            <div class="slider-row">
              <span>大小</span>
              <el-slider v-model="app.mask.size" :min="0.05" :max="1.5" :step="0.01" :show-tooltip="false"></el-slider>
              <b>{{ app.fmtNum(app.mask.size, 2) }}</b>
            </div>
            <div class="slider-row">
              <span>羽化</span>
              <el-slider v-model="app.mask.feather" :min="0.02" :max="1" :step="0.01" :show-tooltip="false"></el-slider>
              <b>{{ app.fmtNum(app.mask.feather, 2) }}</b>
            </div>
            <div class="slider-row" v-if="app.mask.shape === 'rect'">
              <span>宽高比</span>
              <el-slider v-model="app.mask.aspect" :min="0.1" :max="3" :step="0.05" :show-tooltip="false"></el-slider>
              <b>{{ app.fmtNum(app.mask.aspect, 2) }}</b>
            </div>
            <div class="slider-row" v-if="app.mask.shape === 'linear'">
              <span>角度</span>
              <el-slider v-model="app.mask.angle" :min="-180" :max="180" :step="1" :show-tooltip="false"></el-slider>
              <b>{{ app.fmtNum(app.mask.angle, 0) }}°</b>
            </div>
            <div class="hint">在预览画面上拖动即可移动蒙版中心。</div>
          </template>

          <div class="row mt" style="justify-content: space-between;">
            <el-checkbox v-model="app.mask.invert" size="small">反转蒙版</el-checkbox>
            <div class="row">
              <el-button v-if="app.mask.shape === 'pen'" size="small" text @click="app.penUndo">撤销顶点</el-button>
              <el-button v-if="app.isDrawnMask" size="small" text @click="app.clearMaskPath">清空绘制</el-button>
              <el-button size="small" text @click="app.resetMask">重置形状</el-button>
            </div>
          </div>

          <div class="group-title">蒙版独立调色</div>
          <ColorAdjustments :g="app.mask.grading" :show-sharpen="false"></ColorAdjustments>
        </template>
        <div class="hint" v-else>新建或选中一个蒙版后，可调整它的范围与独立调色。</div>
      </el-collapse-item>
    </el-collapse>
  </div>
</template>
