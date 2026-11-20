# 方案：LUT Studio 桌面版本地工具

> 本文档替代此前的移动端方案。已确认：不做移动端，不做服务器 / 多用户 / 账号体系；形态是**单机本地工具**，通过 GitHub 分发给朋友，朋友**不需要安装 Python**。

## Context

现状：Flask（`server.py`，约 1900 行）提供接口并托管 `web/`；前端为 Vue3 + Element Plus；所有渲染走 ffmpeg CLI。已具备 1080p 代理、预览 720p、Range 流式、缩略图 / 蒙版 / 基底帧缓存。

核心痛点：每次预览或静帧都要 ffmpeg 重新解码 + 滤镜 + 编码，切换 LUT 约 2s。

优先级：**画质不损失 > 速度快 > 省性能**。

已明确否掉：Java 三段式管线、Redis 预览缓存（瓶颈在计算与编解码，不在存储）、移动端离线 App。

## 范围

保留并继续完善：

* 素材：扫描目录、拖拽 / 粘贴导入、代理播放、缩略图、底部素材条。
* 滤镜：灰片还原 LUT、Log 直转风格 LUT、个性化 LUT，双 LUT 叠加与强度。
* 调色：一级调色（曝光 / 色温 / 曲线 / 色轮 / HSL / 分离色调 / 校准）。
* 蒙版：几何（线性 / 圆形 / 矩形）、画笔、钢笔，组合树与独立调色。
* 导出：原规格 / 指定分辨率、NVENC 优先、10-bit。

不做：账号、云端、跨设备同步、多用户并发、移动端、App Store / TestFlight 分发。

## 分发形态（GitHub）

朋友没装 Python，因此不靠「装环境再 `python server.py`」。

* **主路径**：GitHub Releases 提供 Windows 免安装包（PyInstaller `onedir` 打包）。解压后双击启动器，自动起本地服务并打开浏览器。不依赖 Python、git、pip。
* **开发路径**：仓库源码 + 启动脚本，供自己或会装环境的人使用。
* 首版仅 Windows；macOS 等确认有需求再做。
* 端口固定 5000，被占用时顺延探测 5001–5099，并把实际地址打印到控制台与启动器窗口。
* 浏览器界面不变，仍是 `http://127.0.0.1:<port>`，只绑本机地址，不对外网开放。

### 打包带来的前置改造

1. **可写目录分离**：现在所有缓存 / 导入副本都写在 `BASE_DIR`。安装到 `Program Files` 等只读位置会失败。改为：
   * 只读资源（`web/`、内置 LUT）随包；
   * 可写数据（`_preview_cache`、`_proxy_cache`、`_thumb_cache`、`_mask_cache`、`_grading_cache`、`_base_cache`、`_imports`）落到 `%LOCALAPPDATA%\LUT Studio`；若程序目录可写且存在 `portable.txt`，则优先用程序目录旁的 `data/`（便携模式）。
2. **ffmpeg 内嵌**：`bin/ffmpeg.exe`、`bin/ffprobe.exe` 随包，启动时优先用包内路径，找不到再回退 `PATH`。NVENC 检测逻辑不变。
3. **路径解析**：PyInstaller 下 `sys._MEIPASS` 与 `onedir` 目录行为不同，统一封装一个 `resource_path()`，避免写死 `os.path.dirname(__file__)`。
4. **LUT 随包策略**：现有 53 个 `.cube`（61.5MB）**全部随包**，不删减、不区分来源，保证朋友装完即可用。仓库直接包含 `luts/` 全量文件。如需减少 git 体积，改用 Git LFS 存放大文件，但发布包仍包含全部 LUT。

### 体积估算（待实测确认）

| 组成                            | 估算          |
| ----------------------------- | ----------- |
| Python 运行时 + Flask + 依赖       | 30–45MB     |
| ffmpeg + ffprobe（含 nvenc 的构建） | 120–160MB   |
| 前端 `web/` 构建产物                | 3–6MB       |
| 全部 LUT（53 个 cube）             | 61.5MB      |
| 合计（解压后）                       | 约 260–330MB |

发布包为 zip，压缩后大致 130–180MB，走 Releases 附件下载。若体积需要压缩，优先换更小的 ffmpeg 构建（去掉不用的编码器），LUT 与功能都不砍。

## 优化主线

### ① 渲染耗时基准测量

同一段素材，分别渲染 1 帧 / 1 秒 / 8 秒，拆出「进程启动 + 解码 + 滤镜 + 编码 + 落盘」各段耗时（`-benchmark` 或分段计时）。

目的：确认 2s 延迟里固定开销（进程启动、解码 GOP 定位）与线性成本（逐帧编码）各占多少，避免优化错方向。

**实测结果**（RTX 3060 Laptop + NVENC 可用；素材 3840×2160 HEVC 10-bit 59.94fps 110Mbps，时长 11.9s；预览档 1280×720 / 30fps）：

| 项目 | 耗时 |
| --- | --- |
| 空进程固定开销 | 0.05s |
| 单帧 PNG 720p（1080p 代理输入） | 0.32s |
| 单帧 PNG 720p（4K 原片输入） | 1.49s |
| 单帧 JPEG + LUT（代理输入） | 0.11s |
| 1 帧视频 LUT + NVENC（代理） | 0.44s |
| 1 秒视频 LUT + NVENC（代理） | 0.70s |
| 8 秒视频 LUT + NVENC（代理） | 2.48s |
| 8 秒视频 无 LUT + NVENC（代理） | 1.80s |
| 8 秒视频 LUT + NVENC（4K 原片，CPU 解码） | 13.20s |
| 8 秒视频 LUT + NVENC（4K 原片，NVDEC） | 4.64s |
| 8 秒纯解码（代理） | 1.10s |
| 8 秒纯解码（4K 原片） | 11.01s |
| 代理生成（12s 素材 → 1080p） | 8.36s |

结论：

* **固定开销约 0.45s**，其中进程启动仅 0.05s，NVENC 初始化占大头。即使只出 1 帧视频也要 0.44s，所以「切 LUT 出单帧」必须绕过编码。
* 代理输入下 8s 预览 2.48s，去掉固定开销后约 **8.5ms/帧**；其中 `lut3d` 约 **2.8ms/帧**（240 帧共 0.68s），占预览耗时 27%。
* 4K 原片纯解码 8s 就要 11s（慢于实时），**预览必须走代理**；走代理后快 5 倍。
* 代理生成是一次性 8.4s，可接受；单帧解码 0.32s 是 WebGL 方案下唯一还会等的环节。
* 因此 ② 的收益明确：切 LUT 由当前约 2.4s（8s 片段）降到 0；换时间点只花 0.32s 取基底帧。

### ② 浏览器 WebGL2 LUT 即时预览

服务端只产出**无 LUT 基底**，浏览器端套 LUT：

```
ffmpeg: 解码 → 一级调色（可选）→ 输出基底帧/流（不含 LUT）
浏览器: 基底 → WebGL2 纹理 → 3D LUT 纹理（16-bit）→ 四面体插值 → 画面
```

* 插值算法与 ffmpeg `lut3d` 默认一致，保证预览与导出同观感。
* 切换 LUT 只换纹理与强度 uniform，不重新解码，延迟降到一帧内。
* LUT 纹理按需上传并缓存（33³ ≈ 288KB，65³ ≈ 2.2MB，16-bit）。
* **回退**：蒙版内含调色、或浏览器无 WebGL2 时，仍走服务端 ffmpeg 渲染，行为与现在一致。
* 导出链完全不变，仍是 ffmpeg 的 `lut3d`，画质基准不受影响。

**实现状态（已完成）**：

| 端 | 内容 |
| --- | --- |
| 后端 | `GET /api/base_frame`（不含 LUT 的基底帧，走 `_base_cache`）、`GET /api/lut_file`（仅允许读 `luts/` 内的 `.cube`） |
| 前端 | `src/lib/cubeLut.js` 解析、`src/lib/webglLut.js` 渲染器、`src/components/LutCanvas.vue` 覆盖层 |
| 接入 | 仅 LUT（无调色 / 无蒙版）时切 LUT 只重绘画布；播放走原片 / 代理 + 着色器；一旦有调色或蒙版立即回退服务端，并停掉着色器播放，避免重复套 LUT |

验收结果：

* 切 LUT、播放中切 LUT 均即时生效，服务端 `preview_graded` 请求数为 0。
* 调色面板加减曝光时正确回退到服务端单帧渲染，处理完自动恢复着色器预览。
* 色彩一致性：同一张基底帧，四面体插值结果与 ffmpeg `lut3d` 对比，整帧平均偏差 0.50/255、最大 1.0/255（8-bit 量化级）；随机色域网格平均 0.50/255、P99 1.68/255。

### ③ 缓存治理

现有 `_preview_cache` 无淘汰策略（曾累积 270MB / 91 个文件，项目总大小约 815MB）。

* 各缓存目录统一走 LRU + 总量上限（默认 2GB，可配置），启动时与写入后按需清理。
* 代理缓存单独配额，避免把预览缓存挤掉。

可与 ② 一起做，因为基底帧缓存会复用同一套策略。

### ④ 结构整理（可选，最后做）

`server.py` 拆分：`preview` / `export` / `masks` / `luts` / `paths` 模块，路由注册集中。纯整理，不改行为。

## 实施顺序

| 阶段 | 内容                                          | 产出            |
| -- | ------------------------------------------- | ------------- |
| M0 ✅ | 渲染基准测量                                      | 分段耗时数据（固定开销约 0.45s，LUT 约 2.8ms/帧） |
| M1 ✅ | 浏览器 WebGL2 LUT 预览（含回退）                      | 切 LUT 近实时，播放中切 LUT 即时生效     |
| M2 | 路径可写化 + 缓存 LRU / 配额                         | 缓存不再膨胀，为打包铺路  |
| M3 | PyInstaller 打包 + 内嵌 ffmpeg + 启动器 + Releases | 朋友双击即用        |
| M4 | `server.py` 模块拆分（可选）                        | 可维护性          |

M2 必须在 M3 之前，否则安装到只读目录会写失败。

## 风险

* **打包兼容性**：PyInstaller 对动态导入与静态资源路径敏感，需在干净机器（无 Python）上验证一次完整流程。
* **杀软误报**：未签名 exe 可能被误判，必要时提供 zip + 说明。
* **体积偏大**：ffmpeg 占大头，属可接受成本；不下滑到要求朋友装环境。
* **WebGL 色彩偏差**：浏览器默认按 sRGB 处理画面，需显式关闭色彩管理 / 使用 `drawingBufferColorSpace`，并与 ffmpeg 输出做逐像素比对验收。
* **LUT 分发**：全部 LUT 随包，含厂商官方文件；仓库公开时这些文件会一并可见，需确认可接受。
* **端口冲突**：固定端口顺延探测，启动器显示实际地址。

## 关键文件

* 后端主入口：[server.py](file:///d:/aw/Desktop/learn/LUT%20Studio/server.py)
* 前端入口：[App.vue](file:///d:/aw/Desktop/learn/LUT%20Studio/frontend/src/App.vue)
* 播放舞台：[PlayerStage.vue](file:///d:/aw/Desktop/learn/LUT%20Studio/frontend/src/components/PlayerStage.vue)
* 内置 / 用户 LUT：[luts/](file:///d:/aw/Desktop/learn/LUT%20Studio/luts)
* 打包相关为新增内容（启动器、ffmpeg 目录、PyInstaller spec），本次不改代码。
