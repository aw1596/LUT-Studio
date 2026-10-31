<script setup>
import { inject } from 'vue'
import MaskCanvas from './MaskCanvas.vue'
import MaskGuides from './MaskGuides.vue'

const app = inject('app')
</script>

<template>
  <section class="stage">
    <div class="player" :ref="el => (app.playerEl = el)" :class="{ zoomed: app.zoom.scale > 1.001 }"
         @wheel="app.onZoomWheel" @dragstart.prevent>
      <div class="player-tag" v-if="app.currentClip">
        <span class="name">{{ app.currentClip.name }}</span>
        <span v-if="app.previewingLut" style="color:var(--accent-2)">LUT 预览</span>
        <span v-if="app.previewLow && app.playUrl" style="color:#e6a23c">快速预览</span>
        <span v-if="app.hasAdjust" style="color:var(--accent)">已调色</span>
      </div>
      <div class="compare-hold" v-if="app.currentClip && app.showThumb"
           :class="{ on: app.compare }"
           @mouseenter="app.compare = true" @mouseleave="app.compare = false">按住对比原片</div>

      <video v-if="app.playUrl" :ref="el => (app.mediaEl = el)" :src="app.playUrl" autoplay draggable="false"
             :style="app.zoomStyle"
             @loadedmetadata="app.onMediaMeta" @timeupdate="app.onTimeUpdate"
             @play="app.playing = true" @pause="app.playing = false"
             @error="app.onPlayError" @ended="app.onPlayEnded"
             @dblclick="app.resetZoom"
             @pointerdown="app.zoomPanStart" @pointermove="app.zoomPanMove"
             @pointerup="app.zoomPanEnd" @pointercancel="app.zoomPanEnd"></video>
      <img v-else-if="app.mainThumbUrl" :ref="el => (app.mediaEl = el)" :src="app.mainThumbUrl" draggable="false"
           :style="app.zoomStyle"
           @load="app.onThumbLoad" @error="app.onThumbError"
           @dblclick="app.resetZoom"
           @pointerdown="app.zoomPanStart" @pointermove="app.zoomPanMove"
           @pointerup="app.zoomPanEnd" @pointercancel="app.zoomPanEnd">
      <div class="player-empty" v-else>
        <b>{{ app.files.length ? '选择一个素材开始调色' : '扫描文件夹导入素材' }}</b>
        在右侧「素材」中填写路径并扫描，素材会出现在底部素材条
      </div>

      <!-- 几何蒙版引导层：可拖拽边缘缩放、圆形箭头旋转、内侧虚线调羽化 -->
      <MaskGuides v-if="app.maskEditing && !app.isDrawnMask && (app.playUrl || app.mainThumbUrl)" />

      <!-- 画笔 / 钢笔蒙版：canvas 叠加层 -->
      <MaskCanvas v-if="app.maskEditing && app.isDrawnMask && (app.playUrl || app.mainThumbUrl)" />

      <div class="play-overlay" v-if="(app.previewLoading || app.thumbLoading) && !app.maskDragging">
        <div class="spinner"></div>
        <span>{{ app.previewLoading ? app.previewText : '正在生成调色预览…' }}</span>
      </div>

      <!-- 播放时间轴：播放/暂停、后退、快进、拖动定位 -->
      <div class="tl-bar" v-if="app.playUrl">
        <button class="tl-btn" :title="app.playing ? '暂停' : '播放'" @click="app.togglePlay">{{ app.playing ? '❚❚' : '▶' }}</button>
        <button class="tl-btn wide" title="后退 5 秒" @click="app.skip(-5)">-5s</button>
        <button class="tl-btn wide" title="快进 5 秒" @click="app.skip(5)">+5s</button>
        <span class="tl-time">{{ app.fmtDur(app.playTime) }}</span>
        <el-slider class="tl-slider" :min="0" :max="app.playDuration || 1" :step="0.05"
                   :show-tooltip="false" v-model="app.playTime" @input="app.seekTo"></el-slider>
        <span class="tl-time">{{ app.fmtDur(app.playDuration) }}</span>
      </div>
    </div>

    <div class="player-bar">
      <el-button size="small" :disabled="!app.currentClip || !app.canPreview" @click="app.playGraded" :loading="app.previewLoading">
        播放调色预览
      </el-button>
      <el-button size="small" :disabled="!app.currentClip" @click="app.playOriginal">播放原片</el-button>
      <el-button size="small" :disabled="!app.playUrl" @click="app.stopPlay">停止</el-button>
      <el-button size="small" text :disabled="app.zoom.scale <= 1.001" @click="app.resetZoom">
        缩放 {{ Math.round(app.zoom.scale * 100) }}%
      </el-button>
      <span class="hint" style="margin:0">滚轮定位放大 · 拖动平移 · 双击复位</span>
      <div class="sep"></div>
      <span>{{ app.lutLabel }}</span>
      <div class="spacer"></div>
      <span v-if="app.currentClip">{{ app.fmtSize(app.currentClip.size) }} · {{ app.fmtDur(app.currentClip.duration) }}</span>
    </div>
  </section>
</template>
