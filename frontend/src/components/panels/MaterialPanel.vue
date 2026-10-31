<script setup>
import { inject } from 'vue'

const app = inject('app')
</script>

<template>
  <div class="panel-body">
    <div class="group-title">视频文件夹</div>
    <el-input v-model="app.inputDir" placeholder="输入或选择文件路径，导入素材" clearable
              @keyup.enter="app.scanDir">
      <template #append>
        <el-button :loading="app.pickingDir" @click="app.pickDir('input', '选择视频文件（导入所在文件夹）')">选择…</el-button>
      </template>
    </el-input>
    <div class="hint">支持 mp4 / mov / mkv / avi / mxf / webm。点「选择…」的系统对话框会直接列出视频文件，选中任意一个即导入它所在的文件夹；也可输入路径后按回车，或直接拖拽 / 粘贴视频文件（拖拽 / 粘贴会复制到项目 <code>_imports/</code> 目录）。</div>

    <div class="group-title">已导入</div>
    <div class="hint" v-if="!app.files.length">暂无素材。在上方输入或选择文件夹路径，按回车导入素材，也可直接拖拽 / 粘贴视频文件。</div>
    <template v-else>
      <div class="row" style="justify-content: space-between;">
        <span class="hint" style="margin:0">共 {{ app.files.length }} 个 · 已选 {{ app.sel.length }} 个</span>
        <span class="row" style="gap:6px;">
          <el-button size="small" text @click="app.selectAll">全选</el-button>
          <el-button size="small" text @click="app.sel = []">清空</el-button>
        </span>
      </div>
      <div class="media-grid">
        <div class="media-card" v-for="f in app.files" :key="f.path"
             :class="{ on: app.sel.includes(f.path), cur: app.currentPath === f.path }"
             @click="app.toggleClip(f)">
          <img class="media-cover" :src="app.thumbUrl({ path: f.path, w: 240, first: 1 })" loading="lazy" alt="">
          <span class="media-check">✓</span>
          <div class="media-meta">
            <div class="media-name" :title="f.name">{{ f.name }}</div>
            <div class="media-sub">{{ app.fmtSize(f.size) }} · {{ app.fmtDur(f.duration) }}</div>
          </div>
        </div>
      </div>
    </template>
  </div>
</template>

<style scoped>
.media-grid {
  display: grid; grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 8px; margin-top: 8px;
}
.media-card {
  position: relative; border: 1px solid var(--line); border-radius: 6px;
  background: #15151c; overflow: hidden; cursor: pointer; transition: .15s;
}
.media-card:hover { border-color: #3a3a48; }
.media-card.on { border-color: var(--accent); }
.media-card.cur { box-shadow: 0 0 0 1px var(--accent); }
.media-cover {
  width: 100%; aspect-ratio: 16 / 9; object-fit: cover;
  display: block; background: #0d0d12;
}
.media-check {
  position: absolute; top: 5px; right: 5px; width: 16px; height: 16px;
  line-height: 16px; text-align: center; border-radius: 50%;
  background: var(--accent); color: #fff; font-size: 11px;
  opacity: 0; transition: .15s;
}
.media-card.on .media-check { opacity: 1; }
.media-meta { padding: 4px 6px 6px; }
.media-name {
  font-size: 11px; color: #c9c9d2;
  white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
}
.media-sub { font-size: 10px; color: var(--sub); }
</style>
