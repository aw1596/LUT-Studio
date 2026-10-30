<script setup>
import { inject } from 'vue'

const app = inject('app')
</script>

<template>
  <div class="panel-body">
    <div class="group-title">输出位置</div>
    <el-radio-group v-model="app.outputMode">
      <el-radio value="prefix">原目录 + converted_ 前缀</el-radio>
      <el-radio value="subfolder">原目录下 converted 子目录</el-radio>
      <el-radio value="custom">自定义输出目录</el-radio>
    </el-radio-group>
    <div v-if="app.outputMode === 'custom'" class="row mt">
      <el-input v-model="app.customDir" placeholder="例如 D:\DaVinci\dji moves" clearable></el-input>
      <el-button :loading="app.pickingDir" @click="app.pickDir('custom', '选择输出文件夹')">选择…</el-button>
    </div>

    <div class="group-title">分辨率</div>
    <el-radio-group v-model="app.resolution">
      <el-radio-button value="original">原始</el-radio-button>
      <el-radio-button value="1080p">1080p</el-radio-button>
      <el-radio-button value="720p">720p</el-radio-button>
    </el-radio-group>

    <div class="group-title">画质（值越小越清晰）</div>
    <el-slider v-model="app.quality" :min="16" :max="28" :marks="{16:'16',20:'20',24:'24',28:'28'}"></el-slider>

    <div class="group-title">色彩深度</div>
    <el-radio-group v-model="app.bitDepth">
      <el-radio-button :value="8">8bit · H.264</el-radio-button>
      <el-radio-button :value="10">10bit · HEVC</el-radio-button>
    </el-radio-group>
    <div class="hint" v-if="app.bitDepth === 10">保留原素材色深；旧播放器可能不支持 HEVC 10bit。</div>

    <div class="group-title">编码器</div>
    <el-radio-group v-model="app.useGpu">
      <el-radio-button :value="true" :disabled="app.gpuChecked && !app.gpuOk">GPU（NVENC）</el-radio-button>
      <el-radio-button :value="false">CPU</el-radio-button>
    </el-radio-group>
    <div class="hint" v-if="app.gpuChecked && !app.gpuOk">{{ app.gpuMsg }}</div>

    <div class="group-title">本次导出</div>
    <div class="hint">已选 {{ app.sel.length }} 个素材 · {{ app.lutLabel }} · {{ app.resolutionText }}</div>
    <el-button type="primary" class="mt" style="width:100%" :disabled="!app.canStart" @click="app.start">
      开始导出
    </el-button>
  </div>
</template>
