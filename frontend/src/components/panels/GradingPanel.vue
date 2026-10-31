<script setup>
import { ref, inject, computed } from 'vue'
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

// 蒙版列表的选区摘要，如「圆形 ＋ 线性」
const opSymbol = { add: '＋', subtract: '−', intersect: '∩' }
const maskSummary = (m) => (m.nodes || [])
  .map((n, i) => (i ? ` ${opSymbol[n.op] || '＋'} ` : '') + shapeLabel(n.shape))
  .join('')

const emptyComposition = computed(() =>
  !!app.maskEditing && !(app.mask.nodes || []).some(n => n.enabled))

const moveNode = (i, dir) => {
  const nodes = app.mask.nodes || []
  const j = i + dir
  if (j < 0 || j >= nodes.length) return
  const tmp = nodes[i]
  nodes[i] = nodes[j]
  nodes[j] = tmp
}
</script>

<template>
  <div class="panel-body">
    <!-- 全局一级调色：与蒙版共用同一套控件 -->
    <div class="group-title">全局调色 · 作用于整个画面</div>
    <ColorAdjustments :g="app.grading"></ColorAdjustments>

    <el-collapse v-model="open" class="grading-collapse">
      <el-collapse-item name="mask" title="蒙版">
        <div class="row" style="justify-content: space-between; align-items: center;">
          <span class="hint" style="margin: 0;">蒙版是选区容器，调色作用于最终合成选区。</span>
          <el-button size="small" type="primary" plain @click="app.createMask">＋ 新建</el-button>
        </div>

        <template v-if="app.masks.length || app.maskDraft">
          <div class="group-title">蒙版列表</div>
          <div class="mask-list">
            <div v-if="app.maskDraft" class="mask-item draft on">
              <span class="mask-name">{{ app.maskDraft.name }}（未确认）</span>
              <span class="mask-shape">{{ maskSummary(app.maskDraft) }}</span>
              <el-button size="small" text type="primary" @click="app.confirmMask">确认</el-button>
              <el-button size="small" text @click="app.deleteMask(app.maskDraft)">删除</el-button>
            </div>
            <div v-for="m in app.masks" :key="m.id" class="mask-item"
                 :class="{ on: app.maskId === m.id }" @click="app.selectMask(m)">
              <el-checkbox v-model="m.enabled" size="small" @click.stop></el-checkbox>
              <span class="mask-name">{{ m.name }}</span>
              <span class="mask-shape">{{ maskSummary(m) }}</span>
              <span v-if="app.gradingUsed(m.grading)" class="mask-state">已调色</span>
              <el-button size="small" text @click.stop="app.deleteMask(m)">删除</el-button>
            </div>
          </div>
        </template>

        <!-- 选区工具：未在编辑时新建蒙版，否则向当前蒙版追加选区节点 -->
        <div class="group-title">添加选区</div>
        <div class="seg seg5">
          <button v-for="s in shapes" :key="s.key" @click="app.newMask(s.key)">{{ s.label }}</button>
        </div>

        <template v-if="app.maskEditing">
          <div class="group-title">组合 · {{ app.mask.name }}</div>
          <div class="node-list">
            <div v-for="(n, i) in app.mask.nodes" :key="n.id" class="node-card"
                 :class="{ on: app.activeNode.id === n.id }" @click="app.selectNode(n)">
              <div class="node-head">
                <el-checkbox v-model="n.enabled" size="small" @click.stop></el-checkbox>
                <span class="mask-name">{{ n.name }}</span>
                <span class="mask-shape">{{ shapeLabel(n.shape) }}</span>
              </div>
              <div class="node-ops">
                <el-select v-if="i > 0" v-model="n.op" size="small" class="node-op" @click.stop>
                  <el-option value="add" label="＋ 添加"></el-option>
                  <el-option value="subtract" label="− 减去"></el-option>
                  <el-option value="intersect" label="∩ 交叉"></el-option>
                </el-select>
                <el-checkbox v-model="n.invert" size="small" @click.stop>反转</el-checkbox>
                <el-button v-if="i > 0" size="small" text @click.stop="moveNode(i, -1)">上移</el-button>
                <el-button v-if="i < app.mask.nodes.length - 1" size="small" text @click.stop="moveNode(i, 1)">下移</el-button>
                <el-button v-if="app.mask.nodes.length > 1" size="small" text @click.stop="app.removeNode(n)">删除</el-button>
              </div>
            </div>
          </div>
          <el-checkbox v-model="app.mask.invert" size="small" class="mt">反转最终选区</el-checkbox>
          <div v-if="emptyComposition" class="empty-warn">当前所有选区节点均已停用，合成结果为空，调色不会生效。</div>

          <!-- 当前节点工具参数 -->
          <div class="group-title">当前选区 · {{ app.activeNode.name }}</div>
          <el-input v-model="app.activeNode.name" size="small" maxlength="40"
                    placeholder="选区名称"></el-input>

          <template v-if="app.activeNode.shape === 'brush'">
            <div class="slider-row">
              <span>笔刷大小</span>
              <el-slider v-model="app.activeNode.brush_size" :min="0.02" :max="0.4" :step="0.01" :show-tooltip="false"></el-slider>
              <b>{{ app.fmtNum(app.activeNode.brush_size, 2) }}</b>
            </div>
            <div class="slider-row">
              <span>边缘柔和</span>
              <el-slider v-model="app.activeNode.feather" :min="0.05" :max="1" :step="0.01" :show-tooltip="false"></el-slider>
              <b>{{ app.fmtNum(app.activeNode.feather, 2) }}</b>
            </div>
            <div class="hint">在预览画面上按住拖动即可涂抹；同一笔画内可来回涂抹。</div>
          </template>

          <template v-else-if="app.activeNode.shape === 'pen'">
            <div class="slider-row">
              <span>羽化</span>
              <el-slider v-model="app.activeNode.feather" :min="0.05" :max="1" :step="0.01" :show-tooltip="false"></el-slider>
              <b>{{ app.fmtNum(app.activeNode.feather, 2) }}</b>
            </div>
            <div class="hint">在画面上逐点单击勾勒多边形，3 点以上自动闭合填充。</div>
          </template>

          <template v-else>
            <div class="slider-row">
              <span>大小</span>
              <el-slider v-model="app.activeNode.size" :min="0.05" :max="1.5" :step="0.01" :show-tooltip="false"></el-slider>
              <b>{{ app.fmtNum(app.activeNode.size, 2) }}</b>
            </div>
            <div class="slider-row">
              <span>羽化</span>
              <el-slider v-model="app.activeNode.feather" :min="0.02" :max="1" :step="0.01" :show-tooltip="false"></el-slider>
              <b>{{ app.fmtNum(app.activeNode.feather, 2) }}</b>
            </div>
            <div class="slider-row" v-if="app.activeNode.shape === 'rect'">
              <span>宽高比</span>
              <el-slider v-model="app.activeNode.aspect" :min="0.1" :max="3" :step="0.05" :show-tooltip="false"></el-slider>
              <b>{{ app.fmtNum(app.activeNode.aspect, 2) }}</b>
            </div>
            <div class="slider-row" v-if="app.activeNode.shape === 'linear' || app.activeNode.shape === 'rect'">
              <span>角度</span>
              <el-slider v-model="app.activeNode.angle" :min="-180" :max="180" :step="1" :show-tooltip="false"></el-slider>
              <b>{{ app.fmtNum(app.activeNode.angle, 0) }}°</b>
            </div>
            <div class="hint">在画面上拖动箭头标尺可缩放，拖动圆形箭头可旋转，拖动内侧虚线可调羽化，拖动形状内部可移动。</div>
          </template>

          <div class="row mt" style="justify-content: space-between;">
            <span class="hint" style="margin: 0;">调整组合不影响已调参数</span>
            <div class="row">
              <el-button v-if="app.activeNode.shape === 'pen'" size="small" text @click="app.penUndo">撤销顶点</el-button>
              <el-button v-if="app.isDrawnMask" size="small" text @click="app.clearMaskPath">清空绘制</el-button>
              <el-button size="small" text @click="app.resetMask">重置选区</el-button>
            </div>
          </div>

          <div class="group-title">蒙版「{{ app.mask.name }}」· 独立调色</div>
          <div class="hint" style="margin: -2px 0 4px;">每张蒙版的调色参数各自独立，只作用在自己的选区内，互不影响。</div>
          <ColorAdjustments :g="app.mask.grading" :show-sharpen="false"></ColorAdjustments>
        </template>
        <div class="hint" v-else>新建或选中一个蒙版后，可组合选区并调整蒙版参数。</div>
      </el-collapse-item>
    </el-collapse>
  </div>
</template>

<style scoped>
.node-list { display: flex; flex-direction: column; gap: 4px; }
.node-card {
  display: flex; flex-direction: column; gap: 2px;
  padding: 4px 6px; border-radius: 6px;
  border: 1px solid transparent; cursor: pointer;
  font-size: 12px; color: var(--sub); transition: .15s;
}
.node-card:hover { background: #1b1b22; }
.node-card.on { border-color: var(--accent); background: #202a3c; color: var(--text); }
.node-head { display: flex; align-items: center; gap: 6px; }
.node-head .mask-name { flex: 1; min-width: 0; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.node-ops { display: flex; align-items: center; gap: 4px; padding-left: 22px; flex-wrap: wrap; }
.node-op { width: 84px; }
.node-ops .el-checkbox { margin-right: 0; font-size: 11px; }
.node-ops .el-button { padding: 2px 4px; font-size: 11px; }
.empty-warn { margin-top: 6px; font-size: 11px; color: #e6a23c; }
.mt { margin-top: 8px; }
</style>
