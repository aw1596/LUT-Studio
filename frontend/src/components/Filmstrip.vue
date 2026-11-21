<script setup>
import { computed, inject } from 'vue'

const app = inject('app')

// 素材条高度变化时，缩略图与卡片等比放大（基准高度 176px）
const scale = computed(() => Math.max(1, app.layout.bin / 176))
const clipStyle = computed(() => ({ width: (148 * scale.value).toFixed(1) + 'px' }))
const coverStyle = computed(() => ({ height: (80 * scale.value).toFixed(1) + 'px' }))
// 胶片条只显示已选中的素材，导入的全部素材在右侧素材界面查看
const pickedFiles = computed(() => app.files.filter(f => app.sel.includes(f.path)))
</script>

<template>
  <footer class="bin" :style="{ height: app.layout.bin + 'px' }">
    <div class="bin-head">
      <span class="title">素材</span>
      <span>{{ app.sel.length }} 个 · 调色 {{ app.gradeSel.length }}</span>
      <span class="spacer"></span>
      <el-button size="small" text :disabled="!app.sel.length" @click="app.selectAllGrade">全选</el-button>
      <el-button size="small" text :disabled="!app.gradeSel.length" @click="app.clearGradeSel">清空</el-button>
    </div>
    <div class="bin-body">
      <div class="bin-strip" :ref="el => (app.binStrip = el)" @wheel="app.onBinWheel" @scroll="app.updateBinNav">
        <div class="empty-line" style="width:100%" v-if="!pickedFiles.length">
          在右侧素材界面中勾选素材后，会以胶片条形式显示在这里
        </div>
        <div class="clip" v-for="f in pickedFiles" :key="f.path" :style="clipStyle"
             :class="{ current: app.currentPath === f.path }"
             @click="app.focusClip(f)">
          <span class="pick" :class="{ on: app.gradeSel.includes(f.path) }"
                :title="app.gradeSel.includes(f.path) ? '取消参与调色' : '参与调色'"
                @click.stop="app.toggleGrade(f)">✓</span>
          <img class="cover" draggable="false" :style="coverStyle" :src="app.thumbUrl({ path: f.path, w: 220 })" loading="lazy" alt="">
          <span class="lut-tag" :class="{ none: !app.lutParamsFor(f.path).lut }"
                :title="app.lutLabelFor(f.path)">{{ app.lutShortName(f.path) }}</span>
          <span class="dur">{{ app.fmtDur(f.duration) }}</span>
          <div class="meta">
            <div class="cname">{{ f.name }}</div>
            {{ app.fmtSize(f.size) }}
          </div>
        </div>
      </div>
      <div class="bin-nav left" v-show="app.binNav.left" @click="app.scrollBin(-1)">‹</div>
      <div class="bin-nav right" v-show="app.binNav.right" @click="app.scrollBin(1)">›</div>
    </div>
  </footer>
</template>

<style scoped>
.pick {
  position: absolute; top: 6px; left: 6px; z-index: 2;
  width: 18px; height: 18px; border-radius: 50%;
  display: flex; align-items: center; justify-content: center;
  background: rgba(0, 0, 0, .55); border: 1px solid rgba(255, 255, 255, .5);
  color: transparent; font-size: 11px; cursor: pointer;
}
.pick.on { background: var(--accent); border-color: var(--accent); color: #fff; }
/* 当前套用的 LUT：与时长标签同一水平线，半透明底不抢画面 */
.lut-tag {
  position: absolute; left: 6px; bottom: 34px; max-width: calc(100% - 62px);
  padding: 1px 6px; border-radius: 4px; font-size: 10px; line-height: 14px;
  color: #d3d6de; background: rgba(10, 10, 14, .58); border: 1px solid rgba(255, 255, 255, .07);
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
  backdrop-filter: blur(4px); pointer-events: none;
}
.lut-tag.none { color: #8c8c98; }
</style>
