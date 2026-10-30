<script setup>
import { inject } from 'vue'

const app = inject('app')
</script>

<template>
  <header class="topbar">
    <span class="logo">LUT</span>
    <span class="brand">LUT Studio<span class="brand-sub">Log 还原 · 批量调色 · 蒙版</span></span>
    <div class="spacer"></div>
    <div class="chip" v-if="app.gpuChecked" :title="app.gpuMsg">
      <span class="dot" :class="{ ok: app.gpuOk }"></span>
      {{ app.gpuOk ? 'GPU 编码可用（NVENC）' : 'GPU 不可用 · 使用 CPU 编码' }}
    </div>
    <el-button v-if="app.hasRunning" type="danger" plain size="small" @click="app.stopAll">暂停全部</el-button>
    <el-button type="primary" class="export-btn" :disabled="!app.canStart" @click="app.start">
      导出{{ app.sel.length ? `（${app.sel.length}）` : '' }}
    </el-button>
  </header>
</template>
