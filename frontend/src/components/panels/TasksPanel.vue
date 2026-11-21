<script setup>
import { inject, ref, computed, watch } from 'vue'

const app = inject('app')

// 勾选状态用 "批次id:条目id" 记录，轮询刷新后依然保留
const selected = ref([])
const keyOf = (b, it) => `${b.id}:${it.id}`
const isChecked = (b, it) => selected.value.includes(keyOf(b, it))
const toggle = (b, it) => {
  const k = keyOf(b, it)
  selected.value = isChecked(b, it)
    ? selected.value.filter(x => x !== k)
    : [...selected.value, k]
}
const selectedPairs = computed(() => {
  const out = []
  for (const b of app.batches) {
    for (const it of b.items) {
      if (isChecked(b, it)) out.push({ b, it })
    }
  }
  return out
})
// 条目被删除 / 批次结束后清理勾选，避免残留
watch(() => app.batches, () => {
  const valid = new Set()
  for (const b of app.batches) {
    for (const it of b.items) valid.add(keyOf(b, it))
  }
  selected.value = selected.value.filter(k => valid.has(k))
}, { deep: true })

const removeSelected = async () => {
  if (!selectedPairs.value.length) return
  await app.deleteItems(selectedPairs.value)
  selected.value = []
}
</script>

<template>
  <div class="panel-body">
    <div class="row" style="justify-content: space-between; gap:8px; flex-wrap:wrap;">
      <span class="group-title" style="margin:0">导出队列</span>
      <div style="display:flex; gap:6px; flex-wrap:wrap;">
        <el-button v-if="app.hasPaused" size="small" plain @click="app.resumeAll">继续全部</el-button>
        <el-button v-if="app.hasActive" size="small" plain @click="app.pauseAll">暂停全部</el-button>
        <el-button v-if="selectedPairs.length" size="small" type="danger" plain @click="removeSelected">
          删除所选 ({{ selectedPairs.length }})
        </el-button>
      </div>
    </div>
    <div class="empty-line" v-if="!app.batches.length">暂无导出任务</div>
    <div v-for="b in app.batchesReversed" :key="b.id">
      <div class="task" v-for="it in b.items" :key="it.id">
        <div class="task-top">
          <el-checkbox class="task-check" size="small" :model-value="isChecked(b, it)"
                       @change="toggle(b, it)"></el-checkbox>
          <span class="task-name">{{ it.name }}</span>
          <el-tag size="small" :type="app.taskTagType(it)">{{ app.taskStatusText(it) }}</el-tag>
        </div>
        <el-progress :percentage="Math.floor(it.progress)" :status="app.progStatus(it.status)"
                     :stroke-width="6" style="margin-top:6px"></el-progress>
        <div class="error-box" v-if="it.error">{{ it.error }}</div>
        <div class="hint" v-if="it.status === 'done'">{{ it.output }}</div>
        <div class="task-actions">
          <el-button v-if="app.taskActive(it)" size="small" text
                     @click="app.togglePause(b, it)">{{ app.taskPaused(it) ? '继续' : '暂停' }}</el-button>
          <el-button v-if="app.taskActive(it)" size="small" text type="danger"
                     @click="app.cancelItem(b, it)">取消</el-button>
          <el-button size="small" text @click="app.deleteItem(b, it)">删除</el-button>
        </div>
      </div>
    </div>
  </div>
</template>
