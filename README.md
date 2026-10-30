# LUT Studio · Log 还原与 3D LUT 批量调色工具

[中文](#中文) | [English](#english)

---

## 中文

面向所拍摄的 Log 视频还原为 Rec.709，以及普通视频的 **3D LUT 批量调色 + 一级调色 + 蒙版** 工具（内置 DJI D-Log-M、Apple Log 等还原 LUT）。带一个桌面端网页界面（深色主题、预览台、素材胶片条、导出队列）和一套命令行入口。技术栈为 Python + Flask + FFmpeg，前端为 Vue 3 + Vite 工程（构建产物由 Flask 直接托管）。

### 功能

**网页界面（`server.py` + `frontend/` 的 Vue 3 工程）**

- 桌面端网页布局：左侧功能栏、中央预览台、右侧属性面板、底部素材胶片条
- 可拖动布局：拖动右侧面板边界左右调整面板宽度，拖动底部素材条边界上下调整高度，缩略图等比放大
- 预览缩放：鼠标滚轮在画面上以光标为中心局部放大 / 缩小（1×–8×），放大后拖动平移，双击或点「缩放 100%」复位
- 五个面板：素材 / 滤镜 / 调色 / 导出 / 任务
- 素材扫描：填写文件夹即可列出视频，显示缩略图、时长、大小，支持全选 / 清空；路径可点「选择…」弹出系统文件夹对话框选取，无需手动粘贴
- 胶片条浏览：左右箭头按钮 + 鼠标滚轮横向滚动，素材较多时也能快速翻到后面的片段
- 滤镜画廊：每个卡片实时显示「当前素材套用该 LUT 后」的真实画面（服务端渲染并缓存）
- 滤镜强度 0–100%，二级 LUT 叠加（两级各自独立强度）
- **一级调色（Lightroom 风格）**：色温、色调、曝光、对比度、高光、阴影、白色、黑色、饱和度、自然饱和度、锐化
- **色轮**：暗部 / 中间调 / 高光，拖动圆点分别给三段色调染色，双击归零
- **色调曲线**：RGB 主通道 + R / G / B 四通道，点击新增控制点、拖动调整、双击删除，曲线用 Catmull-Rom 平滑；另有「区域调整」的暗部 / 中间调 / 高光滑杆
- **HSL / 颜色**：红、橙、黄、绿、青、蓝、紫、品红 8 个色相区间，分别调节色相 / 饱和 / 明度（按参数动态生成 3D LUT）
- **分离色调**：阴影与高光各自设定色相 / 饱和度，另有平衡参数控制分界点
- **校准**：红 / 绿 / 蓝三原色的色相与饱和度，模拟相机原色校准
- **蒙版工具**：线性 / 圆形 / 矩形 / 画笔 / 钢笔五种；支持叠加多个蒙版，绘制后「确认」加入蒙版列表，可随时勾选启用 / 停用或删除；几何蒙版可在画面拖动定位，画笔直接涂抹，钢笔点选顶点生成多边形填充、相邻顶点自动连线，落点后可继续按住拖动调整顶点位置；均可调羽化与反转，支持撤销顶点、清空绘制
- **蒙版独立调色**：每个蒙版单独调节色温、色调、曝光、白色、黑色、高光、阴影、饱和度、对比度、自然饱和度，以及暗部 / 中间调 / 高光色轮、色调曲线（含区域调整）、HSL / 颜色、校准、分离色调
- 「调色」面板按折叠分组组织：一级调色 / 色调曲线 / HSL / 分离色调 / 校准 / 蒙版，每组可单独重置（蒙版内的调色分组同样独立重置）
- 按住「对比原片」即时查看调色前后差异
- 播放调色预览 / 播放原片（HEVC 素材自动生成 720p 代理）
- 导出设置：输出位置（前缀 / 子目录 / 自定义目录，自定义目录可点「选择…」从系统对话框选取）、分辨率（原始 / 1080p / 720p）、画质、色深（8bit / 10bit）、编码器（GPU / CPU）
- 导出队列：逐文件真实进度、错误信息、一键暂停全部

**处理管线**

- 调色一律在 LUT **之前**生效，锐化在 LUT **之后**，便于「先还原、再风格化」
- 10bit 全程走 `gbrp10le` 平面 RGB 管线，输出 `yuv420p10le`（HEVC + `hvc1`）
- 蒙版以 `split` + `alphamerge` + `overlay` 在平面 RGB 空间混合；多个蒙版按列表顺序逐层叠加，每层都有独立的调色链；几何蒙版由 `geq` 按参数生成灰度图，画笔 / 钢笔由 numpy 栅格化为 PGM，均按键值缓存
- 调色模块对应滤镜：曲线、分离色调、高光 / 阴影 / 白色 / 黑色与曲线区域用 `curves`，HSL 与自然饱和度由 Python 合并生成 25³ 3D LUT 交给 `lut3d`，校准用 `colorchannelmixer`
- LUT 强度通过「原图 + 调色结果」按透明度 blend 实现；强度 100% 时不产生额外开销
- 保持原始帧率（`ffprobe` 检测）
- 输出编码：
  - 8bit：`h264_nvenc` / `libx264`
  - 10bit：`hevc_nvenc` / `libx265`
- 自动跳过已存在的输出文件；输出路径与源文件相同时拒绝执行
- `Permission denied` 自动重试 3 次；失败或中断时删除残缺文件
- 服务退出时自动清理残留 FFmpeg 子进程

### 环境要求

- Python 3.7+
- FFmpeg 与 FFprobe，需加入系统 `PATH`
- Flask 与 numpy：`pip install flask numpy`（numpy 仅用于画笔 / 钢笔蒙版的栅格化；未安装时这两种蒙版不可用，其余功能不受影响）
- 可选：NVIDIA GPU（NVENC 硬件编码）

> GPU 编码要求驱动满足 FFmpeg 的 NVENC API 版本（FFmpeg 9 要求 API 13.1 / 驱动 610.00+）。不满足时程序不会中断：页面会提示原因并自动改用 CPU 编码。

### 快速开始

```bash
git clone https://github.com/aw1596/dji_osmo_batch_convert_LUT.git
cd dji_osmo_batch_convert_LUT
pip install flask numpy

python server.py
```

浏览器打开 <http://127.0.0.1:5000>。

使用流程：

1. 「素材」里填写视频文件夹路径（如 `E:\DCIM\DJI_001`）并点击扫描
2. 在底部胶片条点击卡片勾选要处理的视频（默认全选）
3. 「滤镜」里点击选择 LUT，拖动强度；需要时启用二级 LUT
4. 「调色」里调色温/曝光/对比等，或拖色轮、拉色调曲线、调 HSL / 分离色调 / 校准；需要局部调色时在「蒙版」里新建线性/圆形/矩形/画笔/钢笔蒙版，绘制后点「确认」加入蒙版列表，再对每个蒙版单独调色；可继续叠加更多蒙版
5. 「导出」里选择输出位置、分辨率、色深、编码器，点击「开始导出」
6. 「任务」里查看每个文件的进度与错误

### HTTP 接口

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/` | 单页界面 |
| GET | `/api/gpu_status` | NVENC 是否可用及原因 |
| GET | `/api/list_videos?dir=` | 列出目录内视频 |
| GET | `/api/luts` | 内置与自定义 LUT 列表 |
| POST | `/api/upload_lut` | 上传 `.cube` 到 `luts/` |
| POST | `/api/preview/ensure` | 获取可播放预览地址（HEVC 走 720p 代理） |
| GET | `/api/preview_file?path=` | 支持 Range 的视频流 |
| GET | `/api/thumb` | 单帧缩略图，支持 `lut` / `lut2` / `strength` / `grading` / `masks` |
| POST | `/api/pick_dir` | 弹出系统文件夹选择框，返回所选路径（`{title, initial}`） |
| POST | `/api/preview_graded` | 生成 8 秒 720p 调色预览片段 |
| POST | `/api/convert` | 提交批量转换，返回 `batch_id` |
| GET | `/api/batches` | 所有批次与逐文件状态 |
| POST | `/api/stop_all` | 停止全部转换 |

`grading` 与 `masks` 既可传 JSON 字符串（`/api/thumb` 的 query），也可直接传对象（POST body）。单蒙版的旧参数 `mask` 仍然兼容。

`grading` 字段：`temperature`、`tint`、`contrast`、`saturation`、`highlights`、`shadows`、`whites`、`blacks`、`vibrance`（-100 ~ 100），`exposure`（-3 ~ 3），`sharpness`（0 ~ 100），`lift` / `gamma` / `gain` 各为 `{x, y}`（-1 ~ 1，对应暗部 / 中间调 / 高光色轮）；`curve` 为 `{master, r, g, b}`，每项是 `[{x, y}, ...]`（0 ~ 1 的控制点，至少两个）；`curve_regions` 为 `{shadows, midtones, highlights}`（各 -100 ~ 100，曲线区域调整）；`hsl` 为 8 个色相区间的 `{h, s, l}`（`reds` / `oranges` / `yellows` / `greens` / `aquas` / `blues` / `purples` / `magentas`，各 ±100）；`split` 为 `{shadow_hue, shadow_sat, highlight_hue, highlight_sat, balance}`（色相 0 ~ 360，饱和 0 ~ 100，平衡 -100 ~ 100）；`calibration` 为 `{red_hue, red_sat, green_hue, green_sat, blue_hue, blue_sat}`（各 ±100）。

`masks` 是一个数组（最多 16 项），按顺序逐层叠加，每项包含：

- `name`：蒙版名称，仅用于界面标识
- `enabled`：是否参与渲染
- 形状与几何：`shape`（`linear` / `radial` / `rect` / `brush` / `pen`）、`cx` / `cy`（0 ~ 1）、`size`、`aspect`、`angle`、`feather`、`invert`；`brush` / `pen` 另需 `brush_size`（0.01 ~ 0.5）与 `strokes`（每条是 `{x, y}` 点数组，最多 64 条）或 `pen_points`（最多 256 个 `{x, y}` 顶点）
- `grading`：该蒙版独立的调色参数，字段与全局 `grading` 完全一致（一级调色、色轮、曲线、HSL、分离色调、校准）；全部为中性时该层不参与渲染

### 项目结构

```
dji_osmo_batch_convert_LUT/
├── server.py                  # Web 服务、调色/蒙版滤镜链、转换逻辑
├── frontend/                  # 前端源码（Vue 3 + Vite + Element Plus）
│   ├── index.html             # Vite 入口
│   ├── vite.config.js         # 构建输出到 ../web；dev 时 /api 代理到 Flask
│   └── src/
│       ├── App.vue            # 状态与业务逻辑（provide 给各组件）
│       ├── styles.css         # 全局样式
│       └── components/        # 顶栏、左侧栏、播放器、胶片条、各功能面板
├── web/                       # 构建产物（npm run build 生成，Flask 直接托管）
│   ├── index.html
│   └── assets/
├── helper.py                  # CLI 共用工具：FFmpeg 调用、FPS 检测、LUT 下载
├── main.py                    # 交互式命令行入口
├── convert_batch_basic.py     # 早期批量脚本（硬编码路径）
├── luts/                      # LUT 根目录
│   ├── restore/               # 灰片还原 LUT（D-Log-M / Apple Log 等，拷进来即显示）
│   └── creative/              # 个性化风格 LUT（页面上传的也放这里）
├── _thumb_cache/              # 缩略图缓存（可删除）
├── _preview_cache/            # 预览代理与调色片段缓存（可删除）
├── _mask_cache/               # 蒙版灰度图缓存（可删除）
├── _base_cache/               # 缩略图复用的原片单帧缓存（可删除）
└── _grading_cache/            # HSL 生成的 3D LUT 缓存（可删除）
```

五个缓存目录都可随时删除，程序会按需重建。

### 前端开发与构建

前端是独立的 Vue 3 + Vite 工程，源码在 `frontend/`，构建产物输出到 `web/`（Flask 只托管 `web/`）：

```bash
cd frontend
npm install         # 首次
npm run dev         # 开发服务器 http://127.0.0.1:5173，/api 自动代理到 Flask 的 5000
npm run build       # 打包到 ../web，之后刷新 http://127.0.0.1:5000 即可看到最新界面
```

- 只想改后端时不需要 Node：`web/` 里已有打包好的静态文件，`python server.py` 可直接运行
- 改了 `frontend/src/**` 之后必须重新 `npm run build`，否则 Flask 服务的仍是旧产物
- 运行服务端口可用 `python server.py <port>` 指定；dev 代理默认指向 5000

### LUT 管理

- 灰片还原 LUT：把 `.cube` 直接拷进 `luts/restore/`（已带 `DJI_DLogM_to_Rec709.cube`、`AppleLogToRec709-v1.0.cube`）。刷新页面即自动出现在「灰片还原 LUT（一级）」区，无需改代码或重启服务。
- 个性化 LUT：把 `.cube` 拷进 `luts/creative/`，或在「滤镜」面板上传（上传文件也保存到该目录）。刷新后出现在「二级调色 · 个性化 LUT」区。
- 页面按文件名展示；`DJI OSMO Pocket 3 xxx.cube` 会显示为 `xxx（Pocket 3 调色）`
- 个性化卡片缩略图显示「当前还原 LUT + 该风格 LUT」的组合效果；`luts/` 根目录下遗留的 `.cube` 仍会按个性化 LUT 显示，便于从旧版本迁移

### 实现备注

- **色调与色轮用 `curves` 实现**：FFmpeg 9.0.2 的 `colorbalance` 滤镜在本项目环境下完全不生效（RGB / YUV 均无像素变化），因此 `tint` 与 `lift/gamma/gain` 改为单通道三点曲线（黑场→lift、中调→gamma、白场→gain）
- 色轮方向与界面色轮渐变一致：正上方为绿，顺时针依次 黄 → 红 → 品红 → 蓝 → 青
- **高光 / 阴影 / 白色 / 黑色与曲线区域调整用 `curves` 实现**：这几个参数没有对应的原生滤镜，统一编译成一条 6 锚点的主曲线（黑场 0、0.2、0.5、0.8、0.92、白场 1.0），锚点偏移由各参数加权叠加，再强制 y 单调递增以避免曲线回折
- **自然饱和度并入 HSL 的 3D LUT**：`eq` 的饱和度只能线性缩放，无法实现「低饱和像素多提、高饱和像素少提」的行为，因此把自然饱和度作为每个颜色格点的饱和度变换写进同一张 25³ LUT（参数按 5 的台阶量化并缓存，命中率高）
- **多蒙版按列表顺序链式叠加**：先做全局一级调色与全局 LUT，再对每个蒙版 `split` 出两份，一份按该蒙版的调色链处理，另一份取 `format=gray` 的灰度蒙版做 `alphamerge`，最后 `overlay` 回主画面；因此多层叠加时后一层作用在前一层的结果上
- **HSL 用动态生成的 3D LUT**：`huesaturation` 只能全局调节，无法按色相区间分别处理，因此按 8 个色相区间在 Python 里生成 25³ `.cube`（缓存在 `_grading_cache/`）再交给 `lut3d`
- **分离色调**同样基于 `curves`：暗部与高光两段曲线分别染色，`balance` 决定两段的分界位置
- **校准**用 `colorchannelmixer` 的 3×3 混合矩阵近似三原色的色相 / 饱和度偏移
- **画笔 / 钢笔蒙版**由 numpy 栅格化为 PGM：画笔画按路径间距叠加软边圆点，钢笔用扫描线填充多边形后做三次盒式模糊羽化，因此不需要 Pillow
- **蒙版在缩放后的目标分辨率上生成**，保证与画面像素一一对应
- **缩略图复用缓存的源帧**：首次预览把目标时间点解码并缩放成 `_base_cache/` 里的 PNG，之后改参数只重跑滤镜链，不再解码原片；单帧刷新从约 0.4 秒降到约 0.07 秒（带蒙版约 0.09 秒）

### 常见问题

**GPU 显示不可用**
：升级 NVIDIA 驱动到 610.00 以上并重启服务，或直接使用 CPU 模式。任务管理器 GPU 的 “Video Encode” 占用可确认硬件编码是否生效。

**转换失败：Permission denied**
：多为文件锁（残留 FFmpeg 进程、播放器或剪辑软件占用同名文件）。程序会自动重试 3 次；仍失败时关闭占用该文件的软件后重试。

**10bit 输出无法播放**
：10bit 必须使用 HEVC（H.264 10bit 兼容性极差）。旧播放器可能不支持，剪映、DaVinci Resolve、Premiere 及 Windows 11 均可正常读取。

**预览一直显示“正在生成”**
：HEVC 素材首次预览需要转码 720p 代理，稍等即可；之后命中缓存秒开。

**调了参数但画面没变化**
：先确认「调色」面板里的值已改动（左侧栏该面板会显示小圆点），再确认没有把强度调到 0；若启用了蒙版，检查蒙版是否覆盖了想调的区域。

### 命令行版本

```bash
python main.py
```

交互菜单：

```
1) Convert DJI Osmo Pocket 3 D-Log-M to Rec.709
2) Batch Convert DJI Osmo Pocket 3 D-Log-M to Rec.709
3) Convert General Video (with your own LUT)
4) Batch Convert General Videos (with your own LUT)
0) Exit
```

首次使用会自动下载 DJI 官方 D-Log-M → Rec.709 LUT 到 `luts/restore/`。

`convert_batch_basic.py` 是早期独立脚本，路径硬编码在文件内，适合一次性任务自行修改后运行。

### 使用建议

- 如果大批量只做 Log 还原、不需要逐条筛选和细调，并且有一点代码基础，直接用命令行版本（`python main.py`）批量跑会更省事
- 顺序：先「D-Log-M → Rec.709」全量还原，再用风格 LUT 并降低强度（如 30–50%）
- 四季 Pro 系列 LUT 面向 **Rec.709 输入**，直接套在 D-Log-M 原片上色彩会失真
- 10bit 素材建议保持 10bit 输出（HEVC），避免色深损失
- 局部调色时把羽化调大一些，过渡更自然；蒙版外的画面完全不受影响
- 需要看清细节时用鼠标滚轮在画面上定位放大，放大后可拖动平移，双击复位；调蒙版前先放大更容易对准

### 许可与致谢

MIT License

- DJI Osmo Pocket 3 官方 LUT：[DJI](https://www.dji.com)
- 视频处理：[FFmpeg](https://ffmpeg.org)

---

## English

A **3D LUT batch grading tool that restores Log footage to Rec.709 and grades general videos, with Lightroom-style primary grading, color wheels, curves and multi-layer masks** (bundled DJI D-Log-M and Apple Log restoration LUTs). It ships a desktop web UI (dark theme, preview stage, media filmstrip, export queue) plus a CLI. Built on Python + Flask + FFmpeg — the frontend is a Vue 3 + Vite project whose build output is served by Flask.

### Features

**Web UI (`server.py` + the Vue 3 project in `frontend/`)**

- Desktop web layout: left tool rail, center preview stage, right inspector, bottom filmstrip
- Resizable layout: drag the inspector's left edge to change its width, drag the filmstrip's top edge to change its height (thumbnails scale proportionally)
- Preview zoom: wheel over the frame zooms around the cursor (1×–8×); drag to pan when zoomed; double-click or click “缩放 100%” to reset
- Five panels: Media / Filter / Color / Export / Tasks
- Media scanning: point at a folder, clips are listed with thumbnail, duration and size; select all / clear. The path can be picked from a native folder dialog via the “选择…” button instead of pasting it
- Filmstrip navigation: left/right arrow buttons plus horizontal mouse-wheel scrolling, so long clip lists stay browsable
- Filter gallery: every card shows the **actual current clip with that LUT applied** (rendered and cached server-side)
- Filter strength 0–100% plus a secondary chained LUT with its own strength
- **Primary grading (Lightroom-style)**: temperature, tint, exposure, contrast, highlights, shadows, whites, blacks, saturation, vibrance, sharpness
- **Color wheels**: shadows / midtones / highlights — drag the dot to tint each tonal range, double-click to reset
- **Tone curves**: master plus R / G / B channels; click to add a control point, drag to move, double-click to delete, smoothed with Catmull-Rom; a separate “region” section offers shadows / midtones / highlights sliders
- **HSL / color**: eight hue ranges (red, orange, yellow, green, aqua, blue, purple, magenta) with per-range hue / saturation / lightness (generated as a 3D LUT on the fly)
- **Split toning**: separate hue / saturation for shadows and highlights, plus a balance control for the crossover
- **Calibration**: hue and saturation for the red / green / blue primaries, mimicking camera primary calibration
- **Mask tool**: linear / radial / rect / brush / pen. Masks stack in a list: draw one, hit Confirm to add it, enable / disable or delete any entry, and add as many as you need. Geometric masks are positioned by dragging on the preview, the brush paints freely, and the pen fills a polygon from clicked vertices — each click connects to the previous one and any placed vertex can be dragged again to reposition it; all support feather and invert, with vertex undo and clear
- **Per-mask grading**: every mask carries its own temperature, tint, exposure, whites, blacks, highlights, shadows, saturation, contrast, vibrance, shadows / midtones / highlights wheels, tone curves (with region adjustment), HSL, calibration and split toning
- The Color panel is grouped in collapsible sections (primary / curves / HSL / split toning / calibration / mask), each with its own reset; the grading sections inside a mask reset independently too
- “Hold to compare” against the ungraded original
- Play graded preview / play source (HEVC sources get a 720p proxy automatically)
- Export options: output location (prefix / subfolder / custom dir — the custom dir can be picked from a native folder dialog), resolution (original / 1080p / 720p), quality, bit depth (8bit / 10bit), encoder (GPU / CPU)
- Export queue with per-file progress, real error messages, and stop-all

**Processing pipeline**

- Grading always runs **before** the LUT; sharpening runs **after** it, so you can restore first and stylize second
- 10bit goes through a planar-RGB `gbrp10le` pipeline and outputs `yuv420p10le` (HEVC + `hvc1`)
- Masks are blended in planar RGB with `split` + `alphamerge` + `overlay`; geometric mattes come from `geq`, while brush / pen mattes are rasterized with numpy into PGM — both cached by parameter hash. Multiple masks stack in list order, each with its own grading chain
- Grading modules map to filters: tone curves, split toning, highlights / shadows / whites / blacks and curve regions use `curves`; HSL and vibrance are compiled by Python into a single 25³ 3D LUT fed to `lut3d`; calibration uses `colorchannelmixer`
- LUT strength blends the graded result with the original; at 100% no extra work is added
- Original frame rate preserved via `ffprobe`
- Encoding:
  - 8bit → `h264_nvenc` / `libx264`
  - 10bit → `hevc_nvenc` / `libx265`
- Existing outputs are skipped; writing to the source path is refused
- Automatic 3× retry on `Permission denied`; partial files removed on failure or cancellation
- Orphan FFmpeg children are cleaned up when the service exits

### Requirements

- Python 3.7+
- FFmpeg and FFprobe on your system `PATH`
- Flask and numpy: `pip install flask numpy` (numpy is only used to rasterize brush / pen masks; without it those two mask types are unavailable and everything else keeps working)
- Optional: NVIDIA GPU (NVENC hardware encoding)

> GPU encoding requires a driver that satisfies FFmpeg's NVENC API version (FFmpeg 9 wants API 13.1 / driver 610.00+). If unavailable the app keeps working: the UI shows the reason and falls back to CPU encoding.

### Quick start

```bash
git clone https://github.com/aw1596/dji_osmo_batch_convert_LUT.git
cd dji_osmo_batch_convert_LUT
pip install flask numpy

python server.py
```

Open <http://127.0.0.1:5000>.

Typical workflow:

1. In **Media**, enter your footage folder (e.g. `E:\DCIM\DJI_001`) and click Scan
2. Click clips in the filmstrip to select them (all selected by default)
3. In **Filter**, pick a LUT and adjust strength; enable a second LUT if needed
4. In **Color**, tune temperature / exposure / contrast / highlights / shadows / whites / blacks / saturation / vibrance, drag the wheels, shape the tone curve, or adjust HSL / split toning / calibration. For local grading, create a linear / radial / rect / brush / pen mask, draw it, hit **Confirm** to add it to the mask list, then grade each mask on its own; stack as many masks as you need
5. In **Export**, choose location, resolution, bit depth and encoder, then click Start Export
6. Watch per-file progress and errors in **Tasks**

### HTTP API

| Method | Path | Description |
| --- | --- | --- |
| GET | `/` | Single-page UI |
| GET | `/api/gpu_status` | Whether NVENC is usable, and why not |
| GET | `/api/list_videos?dir=` | List videos in a folder |
| GET | `/api/luts` | Built-in and custom LUTs |
| POST | `/api/upload_lut` | Upload a `.cube` into `luts/` |
| POST | `/api/preview/ensure` | Playable preview URL (HEVC gets a 720p proxy) |
| GET | `/api/preview_file?path=` | Range-capable video stream |
| GET | `/api/thumb` | Single-frame thumbnail; accepts `lut` / `lut2` / `strength` / `grading` / `masks` |
| POST | `/api/pick_dir` | Native folder picker, returns the chosen path (`{title, initial}`) |
| POST | `/api/preview_graded` | Render an 8-second 720p graded preview |
| POST | `/api/convert` | Submit a batch, returns `batch_id` |
| GET | `/api/batches` | All batches and per-file status |
| POST | `/api/stop_all` | Stop all conversions |

`grading` and `masks` can be JSON strings (query params for `/api/thumb`) or plain objects (POST body). The legacy single-mask `mask` parameter is still accepted.

`grading` fields: `temperature`, `tint`, `contrast`, `saturation`, `highlights`, `shadows`, `whites`, `blacks`, `vibrance` (-100…100), `exposure` (-3…3), `sharpness` (0…100), and `lift` / `gamma` / `gain` each as `{x, y}` (-1…1, i.e. the shadows / midtones / highlights wheels); `curve` as `{master, r, g, b}` where each entry is `[{x, y}, …]` (0…1 control points, at least two); `curve_regions` as `{shadows, midtones, highlights}` (each -100…100); `hsl` as eight hue ranges with `{h, s, l}` (`reds` / `oranges` / `yellows` / `greens` / `aquas` / `blues` / `purples` / `magentas`, each ±100); `split` as `{shadow_hue, shadow_sat, highlight_hue, highlight_sat, balance}` (hue 0…360, saturation 0…100, balance -100…100); `calibration` as `{red_hue, red_sat, green_hue, green_sat, blue_hue, blue_sat}` (each ±100).

`masks` is an array (up to 16 entries) applied in order, each entry containing:

- `name`: label for the UI only
- `enabled`: whether it takes part in rendering
- Shape and geometry: `shape` (`linear` / `radial` / `rect` / `brush` / `pen`), `cx` / `cy` (0…1), `size`, `aspect`, `angle`, `feather`, `invert`; `brush` / `pen` additionally need `brush_size` (0.01…0.5) and `strokes` (arrays of `{x, y}` points, up to 64 strokes) or `pen_points` (up to 256 `{x, y}` vertices)
- `grading`: the mask's own grading, with exactly the same fields as the global `grading` (primary, wheels, curves, HSL, split toning, calibration); a fully neutral mask is skipped at render time

### Project structure

```
dji_osmo_batch_convert_LUT/
├── server.py                  # Flask server, grading/mask filter graph, conversion engine
├── frontend/                  # Frontend source (Vue 3 + Vite + Element Plus)
│   ├── index.html             # Vite entry
│   ├── vite.config.js         # Builds into ../web; proxies /api to Flask in dev
│   └── src/
│       ├── App.vue            # State and business logic (provided to components)
│       ├── styles.css         # Global styles
│       └── components/        # Top bar, rail, player, filmstrip, feature panels
├── web/                       # Build output (produced by npm run build, served by Flask)
│   ├── index.html
│   └── assets/
├── helper.py                  # Shared CLI helpers: FFmpeg wrapper, FPS probe, LUT download
├── main.py                    # Interactive CLI entry point
├── convert_batch_basic.py     # Legacy batch script (hard-coded paths)
├── luts/                      # LUT root
│   ├── restore/               # Log-restoration LUTs (D-Log-M / Apple Log; drop files here to show up)
│   └── creative/              # Creative look LUTs (UI uploads land here too)
├── _thumb_cache/              # Thumbnail cache (safe to delete)
├── _preview_cache/            # Proxy / graded preview cache (safe to delete)
├── _mask_cache/               # Mask matte cache (safe to delete)
├── _base_cache/               # Cached source frame reused by thumbnails (safe to delete)
└── _grading_cache/            # 3D LUTs generated for HSL (safe to delete)
```

All five cache folders can be deleted at any time; they are rebuilt on demand.

### Frontend dev & build

The frontend is a standalone Vue 3 + Vite project. Source lives in `frontend/`; the build output goes to `web/` (the only folder Flask serves):

```bash
cd frontend
npm install         # first time only
npm run dev         # dev server at http://127.0.0.1:5173, /api proxied to Flask on 5000
npm run build       # bundles into ../web; refresh http://127.0.0.1:5000 to see the result
```

- Backend-only changes need no Node: `web/` already contains the built assets, so `python server.py` just works
- After editing anything under `frontend/src/**` you must re-run `npm run build`, otherwise Flask keeps serving the old bundle
- The dev proxy targets port 5000 by default

### Managing LUTs

- Log-restoration LUTs: copy `.cube` files into `luts/restore/` (already contains `DJI_DLogM_to_Rec709.cube` and `AppleLogToRec709-v1.0.cube`). Refresh the page and they show up in the "Log restoration LUT" section — no code change or restart needed.
- Creative LUTs: copy files into `luts/creative/`, or upload them from the Filter panel (uploads are saved there). Refresh to see them in the "Secondary / creative LUT" section.
- Cards are labelled from filenames; `DJI OSMO Pocket 3 xxx.cube` is shown as `xxx (Pocket 3 look)`
- Creative thumbnails preview "current restoration LUT + that look LUT"; any `.cube` left in the `luts/` root is still listed as a creative LUT for easy migration

### Implementation notes

- **Tint and color wheels use `curves`**: `colorbalance` is a no-op in FFmpeg 9.0.2 in this environment (no pixel change in either RGB or YUV), so `tint` and `lift/gamma/gain` are built as per-channel three-point curves (black → lift, mid → gamma, white → gain)
- Wheel directions match the on-screen gradient: green at the top, then clockwise yellow → red → magenta → blue → cyan
- **Highlights / shadows / whites / blacks and curve regions use `curves`**: none of them has a native filter, so they are compiled into one six-anchor master curve (0, 0.2, 0.5, 0.8, 0.92, 1.0) whose offsets are summed from these parameters, then forced monotonically increasing to avoid a folded curve
- **Vibrance is folded into the HSL 3D LUT**: `eq` saturation is a plain linear scale, so the “lift low-saturation pixels more, high-saturation pixels less” behaviour is written into the same 25³ LUT as a per-lattice saturation transform (parameters quantized to steps of 5 and cached, giving a high hit rate)
- **Multiple masks stack in list order**: global primary grading and the global LUT run first, then each mask does `split` into two copies — one graded with that mask's own chain, the other a `format=gray` matte fed to `alphamerge` — and is `overlay`ed back onto the frame, so later masks act on the result of earlier ones
- **HSL is a generated 3D LUT**: `huesaturation` only works globally, so eight hue ranges are compiled into a 25³ `.cube` in Python (cached under `_grading_cache/`) and applied with `lut3d`
- **Split toning** also uses `curves`: one curve for shadows and one for highlights, with `balance` moving the crossover
- **Calibration** uses the 3×3 `colorchannelmixer` matrix to approximate hue / saturation shifts of the three primaries
- **Brush / pen mattes** are rasterized with numpy to PGM: the brush stamps soft dots along each stroke, the pen scan-fills a polygon and feathers it with three box blurs — no Pillow needed
- The matte is generated at the scaled output resolution, so it maps 1:1 onto pixels
- **Thumbnails reuse a cached source frame**: the first preview decodes and scales the target frame into `_base_cache/`, so later parameter tweaks only re-run the filter chain instead of decoding the clip again — about 70 ms per frame (90 ms with masks) instead of roughly 400 ms

### Troubleshooting

**GPU shown as unavailable**
: Update the NVIDIA driver to 610.00+ and restart, or just use CPU mode. Check GPU “Video Encode” usage in Task Manager to confirm hardware encoding.

**Conversion fails with `Permission denied`**
: Usually a file lock from an orphan FFmpeg process, a player, or editing software. The app retries three times; if it still fails, close whatever holds the file and retry.

**10bit output won't play**
: 10bit requires HEVC (H.264 10bit is poorly supported). Very old players may fail; CapCut, DaVinci Resolve, Premiere and Windows 11 handle it fine.

**Preview stuck on “generating”**
: The first HEVC preview needs a 720p proxy transcode — wait a few seconds; later previews hit the cache instantly.

**Parameters changed but the image looks the same**
: Make sure the values actually moved (the Color rail item shows a dot when grading is active), that LUT strength is not 0, and — if a mask is on — that it covers the area you are grading.

### Command-line usage

```bash
python main.py
```

Menu:

```
1) Convert DJI Osmo Pocket 3 D-Log-M to Rec.709
2) Batch Convert DJI Osmo Pocket 3 D-Log-M to Rec.709
3) Convert General Video (with your own LUT)
4) Batch Convert General Videos (with your own LUT)
0) Exit
```

On first run the official DJI D-Log-M → Rec.709 LUT is downloaded into `luts/restore/`.

`convert_batch_basic.py` is an older standalone script with hard-coded paths — edit it directly for one-off jobs.

### Recommended workflow

- Bulk log-restoration only, no per-clip picking and little need for fine tuning? With basic coding skills, run the command-line version (`python main.py`) instead
- Chain order: apply «D-Log-M → Rec.709» at full strength first, then a look LUT at reduced strength (e.g. 30–50%)
- The seasonal Pro LUTs expect **Rec.709 input**; applying them straight to D-Log-M will shift colors incorrectly
- Keep 10bit footage at 10bit (HEVC) output to avoid losing color depth
- For local grading, raise the feather a little for a smoother falloff; everything outside the mask is untouched
- To inspect detail, wheel-zoom around the cursor, drag to pan, double-click to reset; zoom in before drawing a mask for better precision

### License & credits

MIT License

- DJI Osmo Pocket 3 LUT: [DJI](https://www.dji.com)
- Video processing: [FFmpeg](https://ffmpeg.org)
