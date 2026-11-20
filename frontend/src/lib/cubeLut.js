// .cube 解析：浏览器端把 LUT 解成 3D 纹理数据，用于实时套 LUT
// 只支持 3D LUT（LUT_3D_SIZE）；1D LUT 交给服务端渲染

const cache = new Map()

export function parseCube(text) {
  let size = 0
  let domainMin = [0, 0, 0]
  let domainMax = [1, 1, 1]
  let is1d = false
  const vals = []
  for (const raw of text.split(/\r?\n/)) {
    const line = raw.trim()
    if (!line || line.startsWith('#')) continue
    const head = line.split(/\s+/)
    const key = head[0].toUpperCase()
    if (key === 'TITLE') continue
    if (key === 'LUT_3D_SIZE') { size = parseInt(head[1], 10) || 0; continue }
    if (key === 'LUT_1D_SIZE') { is1d = true; continue }
    if (key === 'DOMAIN_MIN' || key === 'DOMAIN_MAX') {
      const v = head.slice(1, 4).map(Number)
      if (v.length === 3 && v.every(Number.isFinite)) {
        if (key === 'DOMAIN_MIN') domainMin = v
        else domainMax = v
      }
      continue
    }
    const p = head.map(Number)
    if (p.length === 3 && p.every(Number.isFinite)) vals.push(p[0], p[1], p[2])
  }
  if (is1d) throw new Error('1D LUT 不支持浏览器渲染')
  if (!size) throw new Error('缺少 LUT_3D_SIZE')
  if (vals.length !== size * size * size * 3) throw new Error('LUT 数据不完整')
  // WebGL 纹理用 RGBA 上传，这里补 alpha 通道，避免每次渲染再转一次
  const rgba = new Float32Array(size * size * size * 4)
  for (let i = 0, j = 0; i < vals.length; i += 3, j += 4) {
    rgba[j] = vals[i]
    rgba[j + 1] = vals[i + 1]
    rgba[j + 2] = vals[i + 2]
    rgba[j + 3] = 1
  }
  return { size, rgba, domainMin, domainMax }
}

export function loadCube(path) {
  if (cache.has(path)) return cache.get(path)
  const task = fetch('/api/lut_file?path=' + encodeURIComponent(path))
    .then(r => {
      if (!r.ok) throw new Error('LUT 读取失败')
      return r.text()
    })
    .then(parseCube)
    .catch(err => {
      cache.delete(path)  // 失败不缓存，下次还能重试
      throw err
    })
  cache.set(path, task)
  return task
}
