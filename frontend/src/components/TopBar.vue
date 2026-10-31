<script setup>
import { inject } from 'vue'

const app = inject('app')
</script>

<template>
  <header class="topbar">
    <span class="logo">LUT</span>
    <span class="brand">LUT Studio<span class="brand-sub">Log 还原 · 批量调色 · 蒙版</span></span>
    <div class="spacer"></div>
    <div class="chip render-select" v-if="app.gpuChecked"
         :title="app.gpuOk ? 'GPU：显卡解码 + 编码，速度更快' : (app.gpuMsg || '未检测到可用的 NVIDIA GPU，将使用 CPU 渲染')">
      <span class="dot" :class="{ ok: app.gpuOk }"></span>
      <span class="render-label">渲染</span>
      <span class="seg">
        <button type="button" class="seg-btn" :class="{ on: app.gpuOk && app.useGpu }"
                :disabled="!app.gpuOk" @click="app.setRenderGpu(true)">GPU</button>
        <button type="button" class="seg-btn" :class="{ on: !app.gpuOk || !app.useGpu }"
                @click="app.setRenderGpu(false)">CPU</button>
      </span>
    </div>
    <el-button v-if="app.hasRunning" type="danger" plain size="small" @click="app.stopAll">暂停全部</el-button>
    <el-button type="primary" class="export-btn" :disabled="!app.canStart" @click="app.start">
      导出{{ app.sel.length ? `（${app.sel.length}）` : '' }}
    </el-button>
  </header>
</template>

<style scoped>
.render-label { color: var(--sub); }
.seg { display: inline-flex; border-radius: 12px; overflow: hidden; background: #101016; border: 1px solid var(--line); }
.seg-btn {
  border: none; background: transparent; color: var(--sub); cursor: pointer;
  font-size: 11px; font-weight: 600; padding: 2px 9px; line-height: 16px; transition: .15s;
}
.seg-btn:hover:not(:disabled) { color: var(--text); }
.seg-btn.on { background: var(--accent); color: #fff; }
.seg-btn:disabled { opacity: .45; cursor: not-allowed; }
.render-select .dot.ok { background: #37d67a; }
</style>
