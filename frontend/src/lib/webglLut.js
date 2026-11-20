// WebGL2 实时预览：一级调色（色温/色调/曝光/对比度/饱和/高光/阴影/白点/黑点/
// 自然饱和度/RGB 曲线）+ 3D LUT（四面体插值）。
// 逐项对齐 ffmpeg：colortemperature → curves(tint) → exposure → eq → curves(tonal)
// → lut3d(vibrance) → curves(user) → lut3d(LUT1/LUT2)。
// 只负责画，不管业务状态。

const VERT = `#version 300 es
in vec2 aPos;
out vec2 vUV;
void main() {
  vUV = vec2(aPos.x * 0.5 + 0.5, 0.5 - aPos.y * 0.5);
  gl_Position = vec4(aPos, 0.0, 1.0);
}`

const FRAG = `#version 300 es
precision highp float;
precision highp sampler3D;
in vec2 vUV;
uniform sampler2D uSrc;
uniform sampler3D uLut1;
uniform sampler3D uLut2;
uniform float uSize1;
uniform float uSize2;
uniform vec3 uMin1;
uniform vec3 uMax1;
uniform vec3 uMin2;
uniform vec3 uMax2;
uniform float uStr1;
uniform float uStr2;
uniform bool uHas2;

uniform sampler2D uCurves;   // 256×4：行 0 tint / 1 tonal / 2 user
uniform sampler3D uVib;      // 自然饱和度 25³ LUT
uniform float uVibSize;
uniform float uTempOn;
uniform vec3 uKelvinRgb;
uniform float uTintOn;
uniform float uExpOn;
uniform float uExposure;
uniform float uEqCOn;
uniform float uEqSOn;
uniform float uEqC;
uniform float uEqS;
uniform float uTonalOn;
uniform float uUserOn;
uniform float uVibOn;
out vec4 outColor;

const float INV255 = 1.0 / 255.0;

vec3 fetch3(sampler3D lut, ivec3 p, int n) {
  return texelFetch(lut, clamp(p, ivec3(0), ivec3(n)), 0).rgb;
}

// 四面体插值：把立方体切成 6 个四面体，按主轴分情况线性插值
vec3 lutTetra(sampler3D lut, float size, vec3 c) {
  c = clamp(c, 0.0, 1.0);
  float n = size - 1.0;
  vec3 f = c * n;
  ivec3 b = ivec3(floor(f));
  vec3 fr = f - vec3(b);
  int ni = int(n);
  vec3 c000 = fetch3(lut, b, ni);
  vec3 c111 = fetch3(lut, b + ivec3(1, 1, 1), ni);
  vec3 c100 = fetch3(lut, b + ivec3(1, 0, 0), ni);
  vec3 c010 = fetch3(lut, b + ivec3(0, 1, 0), ni);
  vec3 c001 = fetch3(lut, b + ivec3(0, 0, 1), ni);
  vec3 c110 = fetch3(lut, b + ivec3(1, 1, 0), ni);
  vec3 c101 = fetch3(lut, b + ivec3(1, 0, 1), ni);
  vec3 c011 = fetch3(lut, b + ivec3(0, 1, 1), ni);
  if (fr.x >= fr.y) {
    if (fr.y >= fr.z) return c000 + fr.x * (c100 - c000) + fr.y * (c110 - c100) + fr.z * (c111 - c110);
    if (fr.x >= fr.z) return c000 + fr.x * (c100 - c000) + fr.z * (c101 - c100) + fr.y * (c111 - c101);
    return c000 + fr.z * (c001 - c000) + fr.x * (c101 - c001) + fr.y * (c111 - c101);
  }
  if (fr.z >= fr.y) return c000 + fr.z * (c001 - c000) + fr.y * (c011 - c001) + fr.x * (c111 - c011);
  if (fr.z >= fr.x) return c000 + fr.y * (c010 - c000) + fr.z * (c011 - c010) + fr.x * (c111 - c011);
  return c000 + fr.y * (c010 - c000) + fr.x * (c110 - c010) + fr.z * (c111 - c110);
}

vec3 applyLut(sampler3D lut, float size, vec3 mn, vec3 mx, float strength, vec3 c) {
  if (strength <= 0.0) return c;
  vec3 t = lutTetra(lut, size, (c - mn) / max(mx - mn, vec3(1e-6)));
  return mix(c, t, strength);
}

// 8bit 帧之间的取整：ffmpeg 各滤镜在 gbrp 上逐级落地
vec3 qRound(vec3 c) {
  return floor(clamp(c, 0.0, 1.0) * 255.0 + 0.5) * INV255;
}
vec3 qTrunc(vec3 c) {
  return floor(clamp(c, 0.0, 1.0) * 255.0) * INV255;
}

vec3 curveLookup(vec3 c, int row) {
  ivec3 idx = ivec3(clamp(floor(c * 255.0 + 0.5), 0.0, 255.0));
  float r = texelFetch(uCurves, ivec2(idx.r, row), 0).r;
  float g = texelFetch(uCurves, ivec2(idx.g, row), 0).g;
  float b = texelFetch(uCurves, ivec2(idx.b, row), 0).b;
  return vec3(r, g, b);
}

// eq 滤镜自动插入 gbrp → yuv444p（limited BT.601），与 swscale 的整数公式一致
vec3 rgb2yuv(vec3 c) {
  float R = c.r * 255.0;
  float G = c.g * 255.0;
  float B = c.b * 255.0;
  float y = floor((66.0 * R + 129.0 * G + 25.0 * B + 128.0) / 256.0) + 16.0;
  float u = floor((-38.0 * R - 74.0 * G + 112.0 * B + 128.0) / 256.0) + 128.0;
  float v = floor((112.0 * R - 94.0 * G - 18.0 * B + 128.0) / 256.0) + 128.0;
  return vec3(y, u, v);
}

float eqPlane(float p, float cf) {
  float bf = 127.0 - floor(cf / 32.0);
  return clamp(floor(p * cf / 4096.0) + bf, 0.0, 255.0);
}

vec3 yuv2rgb(vec3 t) {
  float y = t.x - 16.0;
  float u = t.y - 128.0;
  float v = t.z - 128.0;
  float r = floor(1.1644 * y + 1.5960 * v + 0.5);
  float g = floor(1.1644 * y - 0.3917 * u - 0.8130 * v + 0.5);
  float b = floor(1.1644 * y + 2.0172 * u + 0.5);
  return clamp(vec3(r, g, b), 0.0, 255.0) * INV255;
}

void main() {
  vec3 c = texture(uSrc, vUV).rgb;
  if (uTempOn > 0.5) c = qTrunc(c * uKelvinRgb);
  if (uTintOn > 0.5) c = curveLookup(c, 0);
  if (uExpOn > 0.5) c = qRound(c * uExposure);
  if (uEqCOn > 0.5 || uEqSOn > 0.5) {
    vec3 yuv = rgb2yuv(c);
    if (uEqCOn > 0.5) yuv.x = eqPlane(yuv.x, uEqC);
    if (uEqSOn > 0.5) {
      yuv.y = eqPlane(yuv.y, uEqS);
      yuv.z = eqPlane(yuv.z, uEqS);
    }
    c = yuv2rgb(yuv);
  }
  if (uTonalOn > 0.5) c = curveLookup(c, 1);
  if (uVibOn > 0.5) c = qRound(lutTetra(uVib, uVibSize, c));
  if (uUserOn > 0.5) c = curveLookup(c, 2);
  c = applyLut(uLut1, uSize1, uMin1, uMax1, uStr1, c);
  if (uHas2) c = applyLut(uLut2, uSize2, uMin2, uMax2, uStr2, c);
  outColor = vec4(c, 1.0);
}`

function compile(gl, type, src) {
  const sh = gl.createShader(type)
  gl.shaderSource(sh, src)
  gl.compileShader(sh)
  if (!gl.getShaderParameter(sh, gl.COMPILE_STATUS)) {
    const log = gl.getShaderInfoLog(sh)
    gl.deleteShader(sh)
    throw new Error('着色器编译失败：' + log)
  }
  return sh
}

export class LutRenderer {
  constructor(canvas) {
    const gl = canvas.getContext('webgl2', {
      alpha: false, antialias: false, depth: false, stencil: false,
      premultipliedAlpha: false, preserveDrawingBuffer: false,
      powerPreference: 'high-performance',
    })
    if (!gl) throw new Error('浏览器不支持 WebGL2')
    this.gl = gl
    this.canvas = canvas
    this.width = 0
    this.height = 0
    this.slots = [
      { lut: null, tex: null, strength: 0 },
      { lut: null, tex: null, strength: 0 },
    ]
    this.gradeSig = null
    this.vibData = null

    const prog = gl.createProgram()
    gl.attachShader(prog, compile(gl, gl.VERTEX_SHADER, VERT))
    gl.attachShader(prog, compile(gl, gl.FRAGMENT_SHADER, FRAG))
    gl.linkProgram(prog)
    if (!gl.getProgramParameter(prog, gl.LINK_STATUS)) {
      throw new Error('着色器链接失败：' + gl.getProgramInfoLog(prog))
    }
    this.prog = prog
    this.u = {
      src: gl.getUniformLocation(prog, 'uSrc'),
      lut1: gl.getUniformLocation(prog, 'uLut1'),
      lut2: gl.getUniformLocation(prog, 'uLut2'),
      size1: gl.getUniformLocation(prog, 'uSize1'),
      size2: gl.getUniformLocation(prog, 'uSize2'),
      min1: gl.getUniformLocation(prog, 'uMin1'),
      max1: gl.getUniformLocation(prog, 'uMax1'),
      min2: gl.getUniformLocation(prog, 'uMin2'),
      max2: gl.getUniformLocation(prog, 'uMax2'),
      str1: gl.getUniformLocation(prog, 'uStr1'),
      str2: gl.getUniformLocation(prog, 'uStr2'),
      has2: gl.getUniformLocation(prog, 'uHas2'),
      curves: gl.getUniformLocation(prog, 'uCurves'),
      vib: gl.getUniformLocation(prog, 'uVib'),
      vibSize: gl.getUniformLocation(prog, 'uVibSize'),
      tempOn: gl.getUniformLocation(prog, 'uTempOn'),
      kelvinRgb: gl.getUniformLocation(prog, 'uKelvinRgb'),
      tintOn: gl.getUniformLocation(prog, 'uTintOn'),
      expOn: gl.getUniformLocation(prog, 'uExpOn'),
      exposure: gl.getUniformLocation(prog, 'uExposure'),
      eqCOn: gl.getUniformLocation(prog, 'uEqCOn'),
      eqSOn: gl.getUniformLocation(prog, 'uEqSOn'),
      eqC: gl.getUniformLocation(prog, 'uEqC'),
      eqS: gl.getUniformLocation(prog, 'uEqS'),
      tonalOn: gl.getUniformLocation(prog, 'uTonalOn'),
      userOn: gl.getUniformLocation(prog, 'uUserOn'),
      vibOn: gl.getUniformLocation(prog, 'uVibOn'),
    }

    // 全屏四边形
    this.vao = gl.createVertexArray()
    gl.bindVertexArray(this.vao)
    this.vbo = gl.createBuffer()
    gl.bindBuffer(gl.ARRAY_BUFFER, this.vbo)
    gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1, -1, 1, -1, -1, 1, 1, 1]), gl.STATIC_DRAW)
    const loc = gl.getAttribLocation(prog, 'aPos')
    gl.enableVertexAttribArray(loc)
    gl.vertexAttribPointer(loc, 2, gl.FLOAT, false, 0, 0)
    gl.bindVertexArray(null)

    // 源画面纹理：不自动做 sRGB 转换，保证与 ffmpeg 解码出的数值一致
    this.srcTex = gl.createTexture()
    gl.bindTexture(gl.TEXTURE_2D, this.srcTex)
    // 线性过滤：基底帧通常大于画布，缩放时比最近邻更平滑
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR)
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.LINEAR)
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE)
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE)
    gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, 1, 1, 0, gl.RGBA, gl.UNSIGNED_BYTE,
                  new Uint8Array([0, 0, 0, 255]))

    // 曲线表：256×4 RGBA8
    this.curveTex = gl.createTexture()
    gl.bindTexture(gl.TEXTURE_2D, this.curveTex)
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.NEAREST)
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.NEAREST)
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE)
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE)
    gl.pixelStorei(gl.UNPACK_ALIGNMENT, 1)
    this._identityCurves()

    // 占位 3D 纹理：没有 LUT 时也保持纹理完整，避免采样报错
    for (const i of [0, 1]) {
      this.slots[i].tex = this._dummyLut()
    }
    this.vibTex = this._dummyLut()
    gl.clearColor(0, 0, 0, 1)
  }

  _identityCurves() {
    const gl = this.gl
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
    gl.bindTexture(gl.TEXTURE_2D, this.curveTex)
    gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, 256, 4, 0, gl.RGBA, gl.UNSIGNED_BYTE, data)
  }

  setCurves(data) {
    const gl = this.gl
    gl.bindTexture(gl.TEXTURE_2D, this.curveTex)
    gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, 256, 4, 0, gl.RGBA, gl.UNSIGNED_BYTE, data)
  }

  _dummyLut() {
    const gl = this.gl
    const tex = gl.createTexture()
    gl.bindTexture(gl.TEXTURE_3D, tex)
    gl.texParameteri(gl.TEXTURE_3D, gl.TEXTURE_MIN_FILTER, gl.NEAREST)
    gl.texParameteri(gl.TEXTURE_3D, gl.TEXTURE_MAG_FILTER, gl.NEAREST)
    gl.texParameteri(gl.TEXTURE_3D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE)
    gl.texParameteri(gl.TEXTURE_3D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE)
    gl.texParameteri(gl.TEXTURE_3D, gl.TEXTURE_WRAP_R, gl.CLAMP_TO_EDGE)
    const data = new Float32Array(2 * 2 * 2 * 4).fill(1)
    gl.texImage3D(gl.TEXTURE_3D, 0, gl.RGBA16F, 2, 2, 2, 0, gl.RGBA, gl.FLOAT, data)
    return tex
  }

  setLut(slot, lut) {
    const gl = this.gl
    const s = this.slots[slot]
    if (!s || s.lut === lut) return
    s.lut = lut
    if (lut) {
      const tex = gl.createTexture()
      gl.bindTexture(gl.TEXTURE_3D, tex)
      gl.texParameteri(gl.TEXTURE_3D, gl.TEXTURE_MIN_FILTER, gl.NEAREST)
      gl.texParameteri(gl.TEXTURE_3D, gl.TEXTURE_MAG_FILTER, gl.NEAREST)
      gl.texParameteri(gl.TEXTURE_3D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE)
      gl.texParameteri(gl.TEXTURE_3D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE)
      gl.texParameteri(gl.TEXTURE_3D, gl.TEXTURE_WRAP_R, gl.CLAMP_TO_EDGE)
      gl.pixelStorei(gl.UNPACK_ALIGNMENT, 1)
      gl.texImage3D(gl.TEXTURE_3D, 0, gl.RGBA16F, lut.size, lut.size, lut.size,
                    0, gl.RGBA, gl.FLOAT, lut.rgba)
      if (s.tex) gl.deleteTexture(s.tex)
      s.tex = tex
    } else if (s.tex) {
      gl.deleteTexture(s.tex)
      s.tex = this._dummyLut()
    }
    this.slots[slot] = s
  }

  /**
   * 更新一级调色。model 由 lib/gradeLut.js 的 buildGradeModel 生成。
   * 模型没变化时直接跳过，避免拖动 LUT / 蒙版相关参数时重复上传纹理。
   */
  setGrade(model, curveData) {
    const gl = this.gl
    const sig = model ? model.sig : ''
    if (sig === this.gradeSig) return
    this.gradeSig = sig
    gl.useProgram(this.prog)
    if (curveData) this.setCurves(curveData)

    const u = this.u
    const m = model || {}
    gl.uniform1f(u.tempOn, m.tempOn ? 1 : 0)
    gl.uniform3fv(u.kelvinRgb, m.kelvinRgb || [1, 1, 1])
    gl.uniform1f(u.tintOn, m.tintOn ? 1 : 0)
    gl.uniform1f(u.expOn, m.expOn ? 1 : 0)
    gl.uniform1f(u.exposure, m.exposure || 1)
    gl.uniform1f(u.eqCOn, m.eqCOn ? 1 : 0)
    gl.uniform1f(u.eqSOn, m.eqSOn ? 1 : 0)
    gl.uniform1f(u.eqC, m.eqC || 4096)
    gl.uniform1f(u.eqS, m.eqS || 4096)
    gl.uniform1f(u.tonalOn, m.tonalOn ? 1 : 0)
    gl.uniform1f(u.userOn, m.userOn ? 1 : 0)
    gl.uniform1f(u.vibOn, m.vibOn ? 1 : 0)
    gl.uniform1f(u.vibSize, m.vibSize || 25)
    gl.uniform1i(u.curves, 3)
    gl.uniform1i(u.vib, 4)

    if (m.vibOn && m.vib && m.vib !== this.vibData) {
      this.vibData = m.vib
      const size = m.vibSize || 25
      gl.activeTexture(gl.TEXTURE4)
      gl.bindTexture(gl.TEXTURE_3D, this.vibTex)
      gl.texParameteri(gl.TEXTURE_3D, gl.TEXTURE_MIN_FILTER, gl.NEAREST)
      gl.texParameteri(gl.TEXTURE_3D, gl.TEXTURE_MAG_FILTER, gl.NEAREST)
      gl.texParameteri(gl.TEXTURE_3D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE)
      gl.texParameteri(gl.TEXTURE_3D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE)
      gl.texParameteri(gl.TEXTURE_3D, gl.TEXTURE_WRAP_R, gl.CLAMP_TO_EDGE)
      gl.pixelStorei(gl.UNPACK_ALIGNMENT, 1)
      gl.texImage3D(gl.TEXTURE_3D, 0, gl.RGBA16F, size, size, size, 0, gl.RGBA, gl.FLOAT, m.vib)
    }
  }

  setStrengths(s1, s2) {
    this.slots[0].strength = s1 / 100
    this.slots[1].strength = s2 / 100
  }

  resize(cssW, cssH, dpr = 1) {
    const w = Math.max(1, Math.round(cssW * dpr))
    const h = Math.max(1, Math.round(cssH * dpr))
    if (this.canvas.width !== w || this.canvas.height !== h) {
      this.canvas.width = w
      this.canvas.height = h
    }
    this.width = w
    this.height = h
  }

  render(media) {
    const gl = this.gl
    if (!this.width || !this.height) return
    gl.viewport(0, 0, this.width, this.height)
    gl.clear(gl.COLOR_BUFFER_BIT)
    gl.useProgram(this.prog)
    gl.bindVertexArray(this.vao)

    gl.activeTexture(gl.TEXTURE0)
    gl.bindTexture(gl.TEXTURE_2D, this.srcTex)
    // 显式关闭浏览器的色彩空间转换：画面数值必须与 ffmpeg 解码结果一致
    gl.pixelStorei(gl.UNPACK_COLORSPACE_CONVERSION_WEBGL, gl.NONE)
    gl.pixelStorei(gl.UNPACK_FLIP_Y_WEBGL, false)
    gl.pixelStorei(gl.UNPACK_PREMULTIPLY_ALPHA_WEBGL, false)
    try {
      gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, gl.RGBA, gl.UNSIGNED_BYTE, media)
    } catch (e) {
      return  // 视频尚未解出有效帧
    }
    gl.uniform1i(this.u.src, 0)

    const s1 = this.slots[0]
    const s2 = this.slots[1]
    gl.activeTexture(gl.TEXTURE1)
    gl.bindTexture(gl.TEXTURE_3D, s1.tex)
    gl.uniform1i(this.u.lut1, 1)
    gl.uniform1f(this.u.size1, s1.lut ? s1.lut.size : 2)
    gl.uniform3fv(this.u.min1, s1.lut ? s1.lut.domainMin : [0, 0, 0])
    gl.uniform3fv(this.u.max1, s1.lut ? s1.lut.domainMax : [1, 1, 1])
    gl.uniform1f(this.u.str1, s1.lut ? s1.strength : 0)

    const has2 = !!s2.lut
    gl.activeTexture(gl.TEXTURE2)
    gl.bindTexture(gl.TEXTURE_3D, s2.tex)
    gl.uniform1i(this.u.lut2, 2)
    gl.uniform1f(this.u.size2, has2 ? s2.lut.size : 2)
    gl.uniform3fv(this.u.min2, has2 ? s2.lut.domainMin : [0, 0, 0])
    gl.uniform3fv(this.u.max2, has2 ? s2.lut.domainMax : [1, 1, 1])
    gl.uniform1f(this.u.str2, has2 ? s2.strength : 0)
    gl.uniform1i(this.u.has2, has2 ? 1 : 0)

    gl.activeTexture(gl.TEXTURE3)
    gl.bindTexture(gl.TEXTURE_2D, this.curveTex)
    gl.activeTexture(gl.TEXTURE4)
    gl.bindTexture(gl.TEXTURE_3D, this.vibTex)

    gl.drawArrays(gl.TRIANGLE_STRIP, 0, 4)
  }

  dispose() {
    const gl = this.gl
    for (const s of this.slots) {
      if (s.tex) gl.deleteTexture(s.tex)
    }
    if (this.srcTex) gl.deleteTexture(this.srcTex)
    if (this.curveTex) gl.deleteTexture(this.curveTex)
    if (this.vibTex) gl.deleteTexture(this.vibTex)
    if (this.vbo) gl.deleteBuffer(this.vbo)
    if (this.vao) gl.deleteVertexArray(this.vao)
    if (this.prog) gl.deleteProgram(this.prog)
    this.slots = [{ lut: null, tex: null, strength: 0 }, { lut: null, tex: null, strength: 0 }]
  }
}
