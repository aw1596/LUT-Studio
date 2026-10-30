<script setup>
import { inject } from 'vue'

const app = inject('app')
</script>

<template>
  <div class="panel-body">
    <div class="group-title">视频文件夹</div>
    <div class="row">
      <el-input v-model="app.inputDir" placeholder="例如 E:\DCIM\DJI_001" clearable
                @keyup.enter="app.scanDir"></el-input>
      <el-button :loading="app.pickingDir" @click="app.pickDir('input', '选择视频文件夹')">选择…</el-button>
      <el-button type="primary" :loading="app.scanning" @click="app.scanDir">扫描</el-button>
    </div>
    <div class="hint">支持 mp4 / mov / mkv / avi / mxf / webm。扫描后可点击底部素材卡片勾选。</div>

    <div class="group-title">已导入</div>
    <div class="hint" v-if="!app.files.length">暂无素材。填写路径后点击扫描。</div>
    <template v-else>
      <div class="row" style="justify-content: space-between;">
        <span class="hint" style="margin:0">共 {{ app.files.length }} 个 · 已选 {{ app.sel.length }} 个</span>
        <span class="row" style="gap:6px;">
          <el-button size="small" text @click="app.selectAll">全选</el-button>
          <el-button size="small" text @click="app.sel = []">清空</el-button>
        </span>
      </div>
      <div class="task" v-for="f in app.files" :key="f.path">
        <div class="task-top">
          <span class="task-name" :style="{ color: app.sel.includes(f.path) ? 'var(--text)' : 'var(--sub)' }">{{ f.name }}</span>
          <el-tag size="small" :type="app.sel.includes(f.path) ? 'primary' : 'info'">
            {{ app.sel.includes(f.path) ? '已选' : '未选' }}
          </el-tag>
        </div>
        <div class="hint">{{ app.fmtSize(f.size) }} · {{ app.fmtDur(f.duration) }}</div>
      </div>
    </template>
  </div>
</template>
