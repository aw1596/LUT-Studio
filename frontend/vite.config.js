import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

export default defineConfig({
  plugins: [vue()],
  base: '/',
  server: {
    port: 5173,
    // 开发时把 /api 转发到本地 Flask 服务
    proxy: {
      '/api': 'http://127.0.0.1:5000',
    },
  },
  build: {
    outDir: '../web',
    emptyOutDir: true,
    target: 'es2020',
  },
})
