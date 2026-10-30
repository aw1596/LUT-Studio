<script setup>
import { inject } from 'vue'

const app = inject('app')
</script>

<template>
  <nav class="rail">
    <div class="rail-item" :class="{ active: app.tab === 'media' }" @click="app.tab = 'media'">
      <i class="ico">▤</i><span>素材</span>
    </div>
    <div class="rail-item" :class="{ active: app.tab === 'filter' }" @click="app.tab = 'filter'">
      <i class="ico">◐</i><span>滤镜</span>
      <span class="rail-dot" v-if="app.lutPath"></span>
    </div>
    <div class="rail-item" :class="{ active: app.tab === 'color' }" @click="app.tab = 'color'">
      <i class="ico">◑</i><span>调色</span>
      <span class="rail-dot" v-if="app.hasAdjust"></span>
    </div>
    <div class="rail-item" :class="{ active: app.tab === 'export' }" @click="app.tab = 'export'">
      <i class="ico">⤒</i><span>导出</span>
    </div>
    <div class="rail-item" :class="{ active: app.tab === 'tasks' }" @click="app.tab = 'tasks'">
      <i class="ico">≡</i><span>任务</span>
      <span class="rail-dot" v-if="app.hasRunning"></span>
    </div>
  </nav>
</template>
