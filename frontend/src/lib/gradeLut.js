// 把一级调色参数（曝光/对比度/高光/阴影/白点/黑点/饱和/自然饱和/色温/色调/曲线）
// 编译成着色器可直接使用的查表数据。
// 所有曲线与 _hsl_lut 的算法都与 server.py / ffmpeg 的 curves、lut3d 逐项对齐：
// curves 用自然三次样条在 256 级上取整（截断），自然饱和度用 25³ LUT + 四面体插值。

const clamp = (x, lo, hi) => (x < lo ? lo : (x > hi ? hi : x))

// C 的 double → int 是向零截断，之后再 clip 到 0..255
const clipU8 = (v) => {
  const i = Math.trunc(v)
  return i < 0 ? 0 : (i > 255 ? 255 : i)
}

const f4 = (x) => Number(x.toFixed(4))

// Python round()（银行家舍入），与服务端生成参数时保持一致
const pyRound = (x) => {
  const fl = Math.floor(x)
  const d = x - fl
  if (d < 0.5) return fl
  if (d > 0.5) return fl + 1
  return fl % 2 === 0 ? fl : fl + 1
}

// ffmpeg vf_curves 的 natural 三次样条：控制点 → 256 级查找表
export function interpolate(points) {
  const scale = 255
  const n = points.length
  const lut = new Uint8Array(256)
  if (n === 0) {
    for (let i = 0; i < 256; i++) lut[i] = i
    return lut
  }
  if (n === 1) {
    lut.fill(clipU8(points[0][1] * scale))
    return lut
  }
  const xs = points.map(p => p[0])
  const ys = points.map(p => p[1])
  const h = new Float64Array(n - 1)
  for (let i = 0; i < n - 1; i++) h[i] = xs[i + 1] - xs[i]
  const r = new Float64Array(n)
  for (let i = 1; i < n - 1; i++) {
    r[i] = 6 * ((ys[i + 1] - ys[i]) / h[i] - (ys[i] - ys[i - 1]) / h[i - 1])
  }
  const bd = new Float64Array(n)
  const md = new Float64Array(n)
  const ad = new Float64Array(n)
  md[0] = md[n - 1] = 1
  for (let i = 1; i < n - 1; i++) {
    bd[i] = h[i - 1]
    md[i] = 2 * (h[i - 1] + h[i])
    ad[i] = h[i]
  }
  for (let i = 1; i < n; i++) {
    const den = md[i] - bd[i] * ad[i - 1]
    const k = den ? 1 / den : 1
    ad[i] *= k
    r[i] = (r[i] - bd[i] * r[i - 1]) * k
  }
  for (let i = n - 2; i >= 0; i--) r[i] -= ad[i] * r[i + 1]

  const x0 = Math.trunc(xs[0] * scale)
  for (let i = 0; i < x0; i++) lut[i] = clipU8(ys[0] * scale)
  for (let i = 0; i < n - 1; i++) {
    const a = ys[i]
    const b = (ys[i + 1] - ys[i]) / h[i] - h[i] * r[i] / 2 - h[i] * (r[i + 1] - r[i]) / 6
    const c = r[i] / 2
    const d = (r[i + 1] - r[i]) / (6 * h[i])
    const xStart = Math.trunc(xs[i] * scale)
    const xEnd = Math.trunc(xs[i + 1] * scale)
    for (let x = xStart; x <= xEnd; x++) {
      const xx = (x - xStart) / scale
      const yy = a + b * xx + c * xx * xx + d * xx * xx * xx
      lut[x] = clipU8(yy * scale)
    }
  }
  const xl = Math.trunc(xs[n - 1] * scale)
  for (let i = xl; i < 256; i++) lut[i] = clipU8(ys[n - 1] * scale)
  return lut
}

const identity = () => {
  const lut = new Uint8Array(256)
  for (let i = 0; i < 256; i++) lut[i] = i
  return lut
}

const threePoint = (lo, mid, hi) => [
  [0, clamp(lo, 0, 0.95)],
  [0.5, clamp(mid, 0.02, 0.98)],
  [1, clamp(hi, 0.05, 1)],
].map(([x, y]) => [f4(x), f4(y)])

const isLinear = (pts) => pts.every(p => Math.abs(p.x - p.y) < 0.005)

// 色温：与 vf_colortemperature 的 kelvin2rgb 完全一致
function kelvin2rgb(kelvinK) {
  const k = kelvinK / 100
  let r, g, b
  if (k <= 66) {
    r = 1
    g = clamp(0.3900815787690196 * Math.log(k) - 0.6318414437886275, 0, 1)
  } else {
    const t = Math.max(k - 60, 0)
    r = clamp(1.292936186062745 * Math.pow(t, -0.1332047592), 0, 1)
    g = clamp(1.1298908608952941 * Math.pow(t, -0.0755148492), 0, 1)
  }
  if (k >= 66) b = 1
  else if (k <= 19) b = 0
  else b = clamp(0.5432067891101961 * Math.log(k - 10) - 1.19625408914, 0, 1)
  return [r, g, b]
}

// 与服务端 _rgb_to_hsv / _hsv_to_rgb 一致
function rgbToHsv(r, g, b) {
  const mx = Math.max(r, g, b)
  const mn = Math.min(r, g, b)
  const d = mx - mn
  if (mx <= 1e-9) return [0, 0, 0]
  const s = d / mx
  if (s <= 1e-9) return [0, 0, mx]
  let h
  if (mx === r) h = ((g - b) / d) % 6
  else if (mx === g) h = (b - r) / d + 2
  else h = (r - g) / d + 4
  return [h / 6, s, mx]
}

function hsvToRgb(h, s, v) {
  if (s <= 1e-9) return [v, v, v]
  const h6 = ((h % 1) + 1) % 1 * 6
  const i = Math.trunc(h6)
  const f = h6 - i
  const p = v * (1 - s)
  const q = v * (1 - s * f)
  const t = v * (1 - s * (1 - f))
  return [[v, t, p], [q, v, p], [p, v, t], [p, q, v], [t, p, v], [v, p, q]][i % 6]
}

const VIB_SIZE = 25

// 自然饱和度 → 25³ LUT（FFmpeg lut3d 的输入/输出都是 8bit，网格大小与服务端一致）
function buildVibranceLut(vibrance) {
  const vib = pyRound(vibrance / 5) * 5 / 100
  if (Math.abs(vib) < 0.01) return null
  const data = new Float32Array(VIB_SIZE * VIB_SIZE * VIB_SIZE * 4)
  const step = 1 / (VIB_SIZE - 1)
  let o = 0
  for (let bi = 0; bi < VIB_SIZE; bi++) {
    const b = bi * step
    for (let gi = 0; gi < VIB_SIZE; gi++) {
      const g = gi * step
      for (let ri = 0; ri < VIB_SIZE; ri++) {
        const r = ri * step
        let [h, s, v] = rgbToHsv(r, g, b)
        if (s > 0.01) {
          if (vib > 0) s = clamp(s + vib * 0.5 * (1 - s), 0, 1)
          else s = clamp(s * (1 + vib * 0.6), 0, 1)
        }
        const [rr, gg, bb] = hsvToRgb(h, s, v)
        data[o++] = rr
        data[o++] = gg
        data[o++] = bb
        data[o++] = 1
      }
    }
  }
  return data
}

const vibCache = new Map()

function vibranceLut(vibrance) {
  const key = pyRound(vibrance / 5) * 5
  if (!vibCache.has(key)) {
    if (vibCache.size > 12) vibCache.clear()
    vibCache.set(key, buildVibranceLut(key))
  }
  return vibCache.get(key)
}

// 单通道曲线：master(channel(x))，与 ffmpeg 同一滤镜内的合成顺序一致
function composeUserCurves(curve) {
  const raw = {}
  for (const ch of ['master', 'r', 'g', 'b']) {
    const pts = (curve && curve[ch]) || []
    raw[ch] = (pts.length >= 2 && !isLinear(pts))
      ? interpolate(pts.map(p => [f4(p.x), f4(p.y)]))
      : null
  }
  const rows = []
  for (const ch of ['r', 'g', 'b']) {
    const chan = raw[ch]
    const master = raw.master
    if (!chan && !master) { rows.push(null); continue }
    const out = new Uint8Array(256)
    for (let i = 0; i < 256; i++) {
      const v = chan ? chan[i] : i
      out[i] = master ? master[v] : v
    }
    rows.push(out)
  }
  const on = rows.some(Boolean)
  return { on, rows: on ? rows : null }
}

/**
 * 编译一组调色参数。返回着色器 uniform 需要的数值与三行曲线表。
 * rows 顺序：0 = 色温色调（tint）曲线，1 = 一级色调曲线，2 = 用户 RGB 曲线
 */
export function buildGradeModel(g) {
  if (!g) return null
  const sig = JSON.stringify([
    g.temperature, g.tint, g.exposure, g.contrast, g.saturation,
    g.highlights, g.shadows, g.whites, g.blacks, g.vibrance,
    g.curve && g.curve.master, g.curve && g.curve.r, g.curve && g.curve.g, g.curve && g.curve.b,
  ])

  const tempOn = Math.abs(g.temperature || 0) >= 0.5
  const kelvin = clamp(pyRound(6500 - (g.temperature || 0) * 25), 1000, 40000)

  // 色调：与 _curve_points(0, 0.5 ∓ t, 1) 相同（R 通道恒等）
  let tintOn = Math.abs(g.tint || 0) >= 0.5
  let tintRows = null
  if (tintOn) {
    const t = (g.tint || 0) / 100 * 0.12
    tintRows = [
      interpolate(threePoint(0, 0.5, 1)),
      interpolate(threePoint(0, 0.5 - t, 1)),
      interpolate(threePoint(0, 0.5 + t, 1)),
    ]
  }

  // 一级区域曲线：与 _tonal_curve_filter 完全一致
  let tonalOn = [g.blacks, g.shadows, g.highlights, g.whites]
    .some(v => Math.abs(v || 0) >= 1)
  let tonalRows = null
  if (tonalOn) {
    const xs = [0, 0.2, 0.5, 0.8, 0.92, 1]
    const ys = [
      clamp((g.blacks || 0) / 100 * 0.12, -0.14, 0.18),
      clamp(0.2 + (g.shadows || 0) / 100 * 0.15, 0.02, 0.42),
      0.5,
      clamp(0.8 + (g.highlights || 0) / 100 * 0.16, 0.5, 0.99),
      clamp(0.92 + (g.whites || 0) / 100 * 0.08, 0.7, 1),
      1,
    ]
    ys[0] = clamp(ys[0], 0, 0.98)
    for (let i = 1; i < ys.length; i++) ys[i] = Math.max(ys[i], ys[i - 1] + 0.005)
    ys[ys.length - 1] = clamp(ys[ys.length - 1], 0, 1)
    const lut = interpolate(xs.map((x, i) => [f4(x), f4(ys[i])]))
    tonalRows = [lut, lut, lut]
  }

  const user = composeUserCurves(g.curve)

  const expOn = Math.abs(g.exposure || 0) >= 0.01
  const eqCOn = Math.abs(g.contrast || 0) >= 0.5
  const eqSOn = Math.abs(g.saturation || 0) >= 0.5
  // 与 ffmpeg eq 的 process_c 一致：参数先按 3 位小数解析，再放大 4096 倍取整
  const eqC = Math.trunc(pyRound((1 + (g.contrast || 0) / 200) * 1000) / 1000 * 4096)
  const eqS = Math.trunc(pyRound((1 + (g.saturation || 0) / 100) * 1000) / 1000 * 4096)

  const vib = vibranceLut(g.vibrance || 0)

  return {
    sig,
    tempOn,
    kelvin,
    tintOn,
    tintRows,
    tonalOn,
    tonalRows,
    userOn: user.on,
    userRows: user.rows,
    expOn,
    exposure: Math.pow(2, pyRound((g.exposure || 0) * 100) / 100),
    eqCOn,
    eqSOn,
    eqC,
    eqS,
    vibOn: !!vib,
    vib,
    vibSize: VIB_SIZE,
    kelvinRgb: tempOn ? kelvin2rgb(kelvin) : [1, 1, 1],
  }
}

// 256×4 曲线纹理：EXR 行 0..2 分别对应 tint / tonal / user
export function curveTextureData(model) {
  const data = new Uint8Array(256 * 4 * 4)
  for (let r = 0; r < 4; r++) {
    for (let i = 0; i < 256; i++) {
      const o = (r * 256 + i) * 4
      data[o] = i
      data[o + 1] = i
      data[o + 2] = i
      data[o + 3] = 255
    }
  }
  const rows = [model && model.tintRows, model && model.tonalRows, model && model.userRows]
  rows.forEach((row, r) => {
    if (!row) return
    for (let ch = 0; ch < 3; ch++) {
      const lut = row[ch]
      if (!lut) continue
      for (let i = 0; i < 256; i++) data[(r * 256 + i) * 4 + ch] = lut[i]
    }
  })
  return data
}
