<script setup>
import { inject } from 'vue'

const app = inject('app')
</script>

<template>
  <div class="panel-body">
    <!-- 一级：灰片还原 -->
    <div class="group-title">灰片还原 LUT（一级）</div>
    <div class="filters">
      <div class="filter-card" :class="{ active: !app.lutPath }" @click="app.lutPath = ''">
        <img v-if="app.currentClip" class="thumb" :src="app.thumbUrl({ w: 200 })" loading="lazy">
        <div v-else class="ph"></div>
        <div class="label">原始</div>
      </div>
      <div class="filter-card" v-for="l in app.restoreLuts" :key="l.path"
           :class="{ active: app.lutPath === l.path }" @click="app.lutPath = l.path">
        <img v-if="app.currentClip" class="thumb" :src="app.thumbUrl({ lut: l.path, w: 200, strength: 100, noSecond: true })" loading="lazy">
        <div v-else class="ph"></div>
        <div class="label">{{ l.name }}</div>
      </div>
    </div>
    <div class="strength-row mt"><span>还原强度</span><b>{{ app.lutStrength }}%</b></div>
    <el-slider v-model="app.lutStrength" :min="0" :max="100" :step="5" :disabled="!app.lutPath"></el-slider>
    <div class="hint">把 D-Log-M / Apple Log 等灰片还原成 Rec.709，缩略图为 100% 强度效果。</div>

    <!-- 二级：个性化风格 -->
    <div class="group-title">二级调色 · 个性化 LUT</div>
    <div class="filters">
      <div class="filter-card" :class="{ active: !app.useSecondLut || !app.lut2Path }"
           @click="app.useSecondLut = false">
        <img v-if="app.currentClip" class="thumb"
             :src="app.lutPath ? app.thumbUrl({ lut: app.lutPath, w: 200, strength: 100, noSecond: true }) : app.thumbUrl({ w: 200 })" loading="lazy">
        <div v-else class="ph"></div>
        <div class="label">不叠加</div>
      </div>
      <div class="filter-card" v-for="l in app.creativeLuts" :key="l.path"
           :class="{ active: app.useSecondLut && app.lut2Path === l.path }"
           @click="app.applyLookLut(l.path)">
        <img v-if="app.currentClip" class="thumb"
             :src="app.lutPath ? app.thumbUrl({ lut: app.lutPath, lut2: l.path, w: 200, strength: 100, strength2: 100, noSecond: true }) : app.thumbUrl({ lut: l.path, w: 200, strength: 100, noSecond: true })"
             loading="lazy">
        <div v-else class="ph"></div>
        <div class="label">{{ l.name }}</div>
      </div>
    </div>
    <div class="strength-row mt"><span>二级强度</span><b>{{ app.lutStrength2 }}%</b></div>
    <el-slider v-model="app.lutStrength2" :min="0" :max="100" :step="5" :disabled="!app.useSecondLut || !app.lut2Path"></el-slider>
    <div class="hint">在还原结果上叠加风格 LUT；缩略图显示的是「当前还原 LUT + 该风格 LUT」的组合效果。</div>

    <div class="group-title">上传 / 自定义 LUT</div>
    <div class="row">
      <el-upload :show-file-list="false" action="/api/upload_lut" accept=".cube"
                 :on-success="app.onLutUploaded" :on-error="app.onLutUploadError">
        <el-button size="small">上传 .cube</el-button>
      </el-upload>
      <el-input v-model="app.customLut" size="small" placeholder="或填写还原 LUT 的 .cube 完整路径" clearable></el-input>
    </div>
  </div>
</template>
