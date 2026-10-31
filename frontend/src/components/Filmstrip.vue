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
      <span>{{ app.files.length }} 个 · 已选 {{ app.sel.length }}</span>
      <span class="spacer"></span>
      <el-button size="small" text :disabled="!app.files.length" @click="app.selectAll">全选</el-button>
      <el-button size="small" text :disabled="!app.sel.length" @click="app.sel = []">清空</el-button>
    </div>
    <div class="bin-body">
      <div class="bin-strip" :ref="el => (app.binStrip = el)" @wheel="app.onBinWheel" @scroll="app.updateBinNav">
        <div class="empty-line" style="width:100%" v-if="!pickedFiles.length">
          在右侧素材界面中勾选素材后，会以胶片条形式显示在这里
        </div>
        <div class="clip" v-for="f in pickedFiles" :key="f.path" :style="clipStyle"
             :class="{ current: app.currentPath === f.path }"
             @click="app.focusClip(f)">
          <img class="cover" :style="coverStyle" :src="app.thumbUrl({ path: f.path, w: 220 })" loading="lazy" alt="">
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
