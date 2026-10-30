<script setup>
import { inject } from 'vue'

const app = inject('app')
</script>

<template>
  <div class="panel-body">
    <div class="row" style="justify-content: space-between;">
      <span class="group-title" style="margin:0">导出队列</span>
      <el-button v-if="app.hasRunning" size="small" type="danger" plain @click="app.stopAll">暂停全部</el-button>
    </div>
    <div class="empty-line" v-if="!app.batches.length">暂无导出任务</div>
    <div v-for="b in app.batchesReversed" :key="b.id">
      <div class="task" v-for="it in b.items" :key="it.input">
        <div class="task-top">
          <span class="task-name">{{ it.name }}</span>
          <el-tag size="small" :type="app.tagType(it.status)">{{ app.statusText(it.status) }}</el-tag>
        </div>
        <el-progress :percentage="Math.floor(it.progress)" :status="app.progStatus(it.status)"
                     :stroke-width="6" style="margin-top:6px"></el-progress>
        <div class="error-box" v-if="it.error">{{ it.error }}</div>
        <div class="hint" v-if="it.status === 'done'">{{ it.output }}</div>
      </div>
    </div>
  </div>
</template>
