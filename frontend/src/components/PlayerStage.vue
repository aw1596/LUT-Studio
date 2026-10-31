<script setup>
import { inject } from 'vue'
import MaskCanvas from './MaskCanvas.vue'

const app = inject('app')
</script>

<template>
  <section class="stage">
    <div class="player" :ref="el => (app.playerEl = el)" :class="{ zoomed: app.zoom.scale > 1.001 }"
         @wheel="app.onZoomWheel" @dragstart.prevent>
      <div class="player-tag" v-if="app.currentClip">
        <span class="name">{{ app.currentClip.name }}</span>
        <span v-if="app.previewingLut" style="color:var(--accent-2)">LUT 预览</span>
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

      <!-- 蒙版引导层：与画面区域严格对齐 -->
      <svg v-if="app.maskEditing && !app.isDrawnMask && (app.playUrl || app.mainThumbUrl)" class="mask-svg"
           :style="app.maskStyle" viewBox="0 0 100 100" preserveAspectRatio="none"
           @pointerdown="app.maskDown" @pointermove="app.maskMove"
           @pointerup="app.maskUp" @pointercancel="app.maskUp">
        <template v-if="app.maskGeo.type === 'radial'">
          <ellipse :cx="app.maskGeo.cx" :cy="app.maskGeo.cy" :rx="app.maskGeo.rx" :ry="app.maskGeo.ry"
                   fill="rgba(61,126,255,.10)" stroke="rgba(255,255,255,.85)"
                   stroke-width="1.2" vector-effect="non-scaling-stroke"></ellipse>
          <ellipse :cx="app.maskGeo.cx" :cy="app.maskGeo.cy" :rx="app.maskGeo.rx * app.maskGeo.fade" :ry="app.maskGeo.ry * app.maskGeo.fade"
                   fill="none" stroke="rgba(255,255,255,.35)" stroke-dasharray="4 3"
                   stroke-width="1" vector-effect="non-scaling-stroke"></ellipse>
        </template>
        <template v-else-if="app.maskGeo.type === 'rect'">
          <rect :x="app.maskGeo.x" :y="app.maskGeo.y" :width="app.maskGeo.w" :height="app.maskGeo.h"
                fill="rgba(61,126,255,.10)" stroke="rgba(255,255,255,.85)"
                stroke-width="1.2" vector-effect="non-scaling-stroke"></rect>
        </template>
        <template v-else>
          <line :x1="app.maskGeo.x1" :y1="app.maskGeo.y1" :x2="app.maskGeo.x2" :y2="app.maskGeo.y2"
                stroke="rgba(255,255,255,.85)" stroke-width="1.2" vector-effect="non-scaling-stroke"></line>
          <line :x1="app.maskGeo.x1b" :y1="app.maskGeo.y1b" :x2="app.maskGeo.x2b" :y2="app.maskGeo.y2b"
                stroke="rgba(255,255,255,.3)" stroke-dasharray="4 3"
                stroke-width="1" vector-effect="non-scaling-stroke"></line>
        </template>
        <circle :cx="app.maskGeo.cx" :cy="app.maskGeo.cy" r="3"
                fill="none" stroke="#fff" stroke-width="1.4" vector-effect="non-scaling-stroke"></circle>
        <line :x1="app.maskGeo.cx - 5" :y1="app.maskGeo.cy" :x2="app.maskGeo.cx + 5" :y2="app.maskGeo.cy"
              stroke="#fff" stroke-width="1" vector-effect="non-scaling-stroke"></line>
        <line :x1="app.maskGeo.cx" :y1="app.maskGeo.cy - 5" :x2="app.maskGeo.cx" :y2="app.maskGeo.cy + 5"
              stroke="#fff" stroke-width="1" vector-effect="non-scaling-stroke"></line>
      </svg>

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
      <el-button size="small" :disabled="!app.currentClip || !app.lutPath" @click="app.playGraded" :loading="app.previewLoading">
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
