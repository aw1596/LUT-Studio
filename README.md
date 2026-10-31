# LUT Studio

> Log 还原 + 3D LUT 批量调色工具｜Log restoration and batch 3D LUT grading

[![GitHub](https://img.shields.io/badge/GitHub-aw1596%2FLUT--Studio-181717?logo=github&style=flat-square)](https://github.com/aw1596/LUT-Studio)
![License](https://img.shields.io/badge/license-MIT-blue?style=flat-square)
[![Python](https://img.shields.io/badge/Python-3.7%2B-3776AB?logo=python&style=flat-square)](https://www.python.org)
[![FFmpeg](https://img.shields.io/badge/FFmpeg-required-007808?style=flat-square)](https://ffmpeg.org)

仓库地址：<https://github.com/aw1596/LUT-Studio>

[中文](#中文) | [English](#english)

---

## 中文

LUT Studio 把 Log 视频还原为 Rec.709，并对普通视频做 **3D LUT 批量调色 + 一级调色 + 蒙版局部调色**。它提供一个桌面端风格的网页界面（深色主题、预览台、素材胶片条、导出队列）和一套命令行入口，内置 53 个 LUT（Log 还原、Log 直转风格化、Rec.709 风格 LUT）。

技术栈：Python + Flask + FFmpeg；前端为 Vue 3 + Vite 工程，构建产物由 Flask 直接托管。

### 功能

**网页界面**（`server.py` + `frontend/`）

- 桌面端布局：左侧功能栏、中央预览台、右侧属性面板、底部素材胶片条；面板宽度 / 胶片条高度可拖动调整
- 预览缩放：滚轮以光标为中心缩放（1×–8×），放大后可拖动平移，双击复位
- 五个面板：素材 / 滤镜 / 调色 / 导出 / 任务
- 素材扫描：填写文件夹即可列出视频（缩略图、时长、大小），支持全选 / 清空；路径可点「选择…」调用系统文件夹对话框
- 素材导入：把视频拖进窗口任意位置，或复制文件后在页面按 Ctrl+V 粘贴，即可加入素材列表（文件会复制到项目 `_imports/`，支持多文件与同名自动编号）
- 胶片条：左右箭头 + 滚轮横向滚动
- 滤镜画廊分三组：灰片还原 LUT（一级）、Log 转风格化 LUT（一级）、个性化 LUT（二级叠加）
- 每张滤镜卡片实时渲染「当前素材套用该 LUT 后」的画面（服务端渲染并缓存）
- 还原强度 / 二级强度各 0–100%，两级独立
- **一级调色**：色温、色调、曝光、对比度、高光、阴影、白色、黑色、饱和度、自然饱和度、锐化
- **色轮**：暗部 / 中间调 / 高光三段染色，双击归零
- **色调曲线**：RGB 主通道 + R / G / B 四通道，Catmull-Rom 平滑；另有暗部 / 中间调 / 高光区域调整
- **HSL / 颜色**：8 个色相区间分别调节色相 / 饱和度 / 明度（按参数动态生成 3D LUT）
- **分离色调**：阴影与高光各自设定色相 / 饱和度，`balance` 控制分界
- **校准**：红 / 绿 / 蓝三原色的色相与饱和度
- **蒙版**：线性 / 圆形 / 矩形 / 画笔 / 钢笔五种，可叠加多个；可启用 / 停用 / 删除，支持羽化、反转、撤销顶点
- **蒙版独立调色**：每个蒙版拥有完整的一套调色参数（一级、色轮、曲线、HSL、校准、分离色调）
- 「调色」面板按折叠分组组织，每组可单独重置
- 按住「对比原片」即时查看调色前后差异
- 播放调色预览 / 原片（HEVC 自动生成 720p 代理）
- 导出设置：输出位置（前缀 / 子目录 / 自定义目录）、分辨率（原始 / 1080p / 720p）、画质、色深（8bit / 10bit）、编码器（GPU / CPU）
- 导出队列：逐文件真实进度、错误信息、一键暂停

**处理管线**

- 调色在 LUT **之前**生效，锐化在 LUT **之后**，便于「先还原、再风格化」
- 10bit 走 `gbrp10le` 平面 RGB 管线，输出 `yuv420p10le`（HEVC + `hvc1`）
- 蒙版以 `split` + `alphamerge` + `overlay` 在平面 RGB 空间混合；多层按列表顺序叠加，每层独立调色链；几何蒙版由 `geq` 生成，画笔 / 钢笔由 numpy 栅格化为 PGM，按键值缓存
- 曲线、区域调整、分离色调、高光 / 阴影 / 白色 / 黑色用 `curves`；HSL 与自然饱和度合并生成 25³ 3D LUT 交给 `lut3d`；校准用 `colorchannelmixer`
- LUT 强度通过「原图 + 调色结果」透明度 blend 实现，100% 时无额外开销
- 保持原始帧率（`ffprobe` 检测）
- 编码：8bit → `h264_nvenc` / `libx264`；10bit → `hevc_nvenc` / `libx265`
- 自动跳过已存在的输出文件；输出路径等于源文件时拒绝执行
- `Permission denied` 自动重试 3 次；失败或中断时删除残缺文件；服务退出时清理残留 FFmpeg 子进程

### 环境要求

- Python 3.7+
- FFmpeg 与 FFprobe（需加入系统 `PATH`）
- Flask 与 numpy：`pip install flask numpy`
  （numpy 仅用于画笔 / 钢笔蒙版栅格化；未安装时这两种蒙版不可用，其余功能不受影响）
- 可选：NVIDIA GPU（NVENC 硬件编码）

> GPU 编码需要驱动满足 FFmpeg 的 NVENC API 版本（FFmpeg 9 要求 API 13.1 / 驱动 610.00+）。不满足时程序不会中断：界面会提示原因并自动改用 CPU 编码。

### 快速开始

```bash
git clone https://github.com/aw1596/LUT-Studio.git
cd LUT-Studio
pip install flask numpy

python server.py
```

浏览器打开 <http://127.0.0.1:5000>（服务固定监听 `127.0.0.1:5000`）。

使用流程：

1. 「素材」里填写视频文件夹路径（如 `E:\DCIM\DJI_001`），点击扫描
2. 在底部胶片条勾选要处理的视频（默认全选）
3. 「滤镜」里选择 LUT 并调整强度；需要时启用二级 LUT
4. 「调色」里调色温 / 曝光 / 对比等，或拖色轮、拉曲线、调 HSL / 分离色调 / 校准；需要局部调色时新建蒙版，绘制后点「确认」加入列表，再对每个蒙版单独调色
5. 「导出」里选择输出位置、分辨率、色深、编码器，点击「开始导出」
6. 「任务」里查看每个文件的进度与错误

### 前端开发与构建

前端是独立的 Vue 3 + Vite 工程，源码在 `frontend/`，构建产物输出到 `web/`（Flask 只托管 `web/`）：

```bash
cd frontend
npm install         # 首次
npm run dev         # http://127.0.0.1:5173，/api 自动代理到 Flask 的 5000
npm run build       # 打包到 ../web，之后刷新 http://127.0.0.1:5000
```

- 只改后端不需要 Node：`web/` 已包含打包后的静态文件，`python server.py` 可直接运行
- 修改 `frontend/src/**` 后必须重新 `npm run build`，否则 Flask 仍托管旧产物

### LUT 管理

页面按目录自动分组，刷新即可显示新增文件，无需改代码或重启。

**灰片还原 LUT（一级）** — `luts/restore/`，仓库内置 9 个：

| 文件 | 页面显示 |
| --- | --- |
| `DJI DLogM To Rec.709.cube` | DJI D-Log-M → Rec.709 |
| `DJI OSMO Pocket 4 D-Log to Rec.709.cube` | DJI Pocket 4 D-Log → Rec.709 |
| `DJI OSMO Pocket 4P D-Log2 to Rec.709.cube` | DJI Pocket 4P D-Log2 → Rec.709 |
| `Apple Log To Rec.709.cube` | Apple Log → Rec.709 |
| `Apple Log To Rec.709 Fix.cube` | Apple Log → Rec.709 (Fix) |
| `Apple Log2 To Rec.709.cube` | Apple Log 2 → Rec.709 |
| `ViVO Log To Rec.709.cube` | ViVO Log → Rec.709 |
| `O Log To Rec.709.cube` | O-Log → Rec.709 |
| `O Log2 To Rec709.cube` | O-Log 2 → Rec.709 |

**Log 转 风格化 LUT（一级）** — `luts/log_style/`，以 Log 素材为输入，一次完成还原 + 风格化（输出 Rec.709），选中后无需再叠加还原 LUT。仓库内置 23 个：

- Apple Log 专用：`Apple Log - 赐福司影调`、`Apple Log - 风格化1/2/3`、`Apple Log2 - 赐福司影调`、`Apple Log2 - 风格化`
- `Log -  ANALOGICAKDK2383 D55 / D60 / D65`
- `Log -  Color Plus 200`、`EKTACHROME`、`Ektachrome E100`、`Elite Chrome 200`、`Gold 200`、`Kodak Ektar 100`、`Portra 160 / 400 / 800`、`Ultramax 400`、`VISION3 200T Color / 250D Color / 500T / 50D`

**个性化 LUT（二级叠加）** — `luts/creative/`，输入为 Rec.709；「滤镜」面板上传的 LUT 也保存到这里。仓库内置 21 个：

- `ANALOGICAKDK2383 D55 / D60 / D65`
- DJI Pocket 3 四季 Pro：`Autumn Pro`、`Spring Pro`、`Summer Pro`、`Winter Pro`
- `Color Plus 200`、`EKTACHROME`、`Ektachrome E100`、`Elite Chrome 200`、`Gold 200`、`Kodak Ektar 100`、`Portra 160 / 400 / 800`、`Ultramax 400`、`VISION3 200T Color / 250D Color / 500T / 50D`

补充说明：

- 页面按文件名展示；`luts/restore/` 里上述 9 个还原 LUT 都有中文显示名，其余显示原始文件名
- 个性化卡片缩略图显示「当前还原 LUT + 该风格 LUT」的组合效果
- 带 `Log -` 前缀的 LUT 以 Log 素材为输入（统一放在 `luts/log_style/`）；`creative/` 里的同名 LUT 以 Rec.709 素材为输入。套用 Log 风格化 LUT 后无需再加还原 LUT；已还原的画面叠加风格 LUT 时请选 `creative/` 版本

### 项目结构

```
LUT-Studio/
├── server.py                  # Web 服务、调色/蒙版滤镜链、转换逻辑
├── helper.py                  # CLI 共用工具：FFmpeg 调用、FPS 检测、LUT 下载
├── main.py                    # 交互式命令行入口
├── convert_batch_basic.py     # 早期批量脚本（硬编码路径）
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
├── luts/
│   ├── restore/               # 灰片还原 LUT（一级）
│   ├── log_style/             # Log 直转风格化 LUT（一级，输入 Log）
│   └── creative/              # 个性化风格 LUT（二级叠加，输入 Rec.709）
└── .gitignore                 # 忽略 node_modules、__pycache__ 与各类缓存
```

运行时会在项目根目录生成 `_thumb_cache/`、`_base_cache/`、`_mask_cache/`、`_grading_cache/`、`_preview_cache/` 五个缓存目录；拖拽 / 粘贴导入的视频副本存放在 `_imports/`。以上均已加入 `.gitignore`，缓存可随时删除，程序按需重建。

### HTTP 接口

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/` | 单页界面 |
| GET | `/api/gpu_status` | NVENC 是否可用及原因 |
| GET | `/api/list_videos?dir=` | 列出目录内视频 |
| POST | `/api/import_files` | 拖拽 / 粘贴导入：接收 multipart `files`，复制到 `_imports/` 并返回素材信息 |
| GET | `/api/luts` | LUT 列表（含 `kind`: `restore` / `log` / `creative`） |
| POST | `/api/upload_lut` | 上传 `.cube` 到 `luts/creative/` |
| POST | `/api/preview/ensure` | 获取可播放预览地址（HEVC 走 720p 代理） |
| GET | `/api/preview_file?path=` | 支持 Range 的视频流 |
| GET | `/api/thumb` | 单帧缩略图，支持 `lut` / `lut2` / `strength` / `grading` / `masks` |
| POST | `/api/pick_dir` | 弹出系统文件夹选择框，返回所选路径（`{title, initial}`） |
| POST | `/api/preview_graded` | 生成 8 秒 720p 调色预览片段 |
| POST | `/api/convert` | 提交批量转换，返回 `batch_id` |
| GET | `/api/batches` | 所有批次与逐文件状态 |
| POST | `/api/stop_all` | 停止全部转换 |
| GET | `/api/write_test?path=` | 诊断：测试服务进程对指定路径的写权限 |

`grading` 与 `masks` 既可传 JSON 字符串（`/api/thumb` 的 query），也可直接传对象（POST body）。单蒙版的旧参数 `mask` 仍然兼容。

`grading` 字段：

- `temperature`、`tint`、`contrast`、`saturation`、`highlights`、`shadows`、`whites`、`blacks`、`vibrance`：-100 ~ 100
- `exposure`：-3 ~ 3；`sharpness`：0 ~ 100
- `lift` / `gamma` / `gain`：各为 `{x, y}`（-1 ~ 1，对应暗部 / 中间调 / 高光色轮）
- `curve`：`{master, r, g, b}`，每项是 `[{x, y}, ...]`（0 ~ 1 控制点，至少两个）
- `curve_regions`：`{shadows, midtones, highlights}`（各 -100 ~ 100）
- `hsl`：8 个色相区间的 `{h, s, l}`（`reds` / `oranges` / `yellows` / `greens` / `aquas` / `blues` / `purples` / `magentas`，各 ±100）
- `split`：`{shadow_hue, shadow_sat, highlight_hue, highlight_sat, balance}`（色相 0 ~ 360，饱和 0 ~ 100，平衡 -100 ~ 100）
- `calibration`：`{red_hue, red_sat, green_hue, green_sat, blue_hue, blue_sat}`（各 ±100）

`masks` 数组（最多 16 项），按顺序逐层叠加，每项包含：

- `name`：蒙版名称，仅用于界面标识
- `enabled`：是否参与渲染
- 形状与几何：`shape`（`linear` / `radial` / `rect` / `brush` / `pen`）、`cx` / `cy`（0 ~ 1）、`size`、`aspect`、`angle`、`feather`、`invert`；`brush` / `pen` 另需 `brush_size`（0.01 ~ 0.5）与 `strokes`（每条是 `{x, y}` 点数组，最多 64 条）或 `pen_points`（最多 256 个 `{x, y}` 顶点）
- `grading`：该蒙版独立的调色参数，字段与全局 `grading` 完全一致；全部中性时该层不参与渲染

### 实现备注

- **色调与色轮用 `curves`**：FFmpeg 9.0.2 的 `colorbalance` 在本项目环境下不生效，因此 `tint` 与 `lift/gamma/gain` 改为单通道三点曲线（黑场→lift、中调→gamma、白场→gain）
- 色轮方向与界面渐变一致：正上方为绿，顺时针依次 黄 → 红 → 品红 → 蓝 → 青
- **高光 / 阴影 / 白色 / 黑色与曲线区域调整**同样编译成一条 6 锚点主曲线（0、0.2、0.5、0.8、0.92、1.0），再强制 y 单调递增以避免曲线回折
- **自然饱和度并入 HSL 的 3D LUT**：`eq` 的饱和度只能线性缩放，因此把自然饱和度写进同一张 25³ LUT（参数按 5 的台阶量化并缓存）
- **HSL 用动态生成的 3D LUT**：`huesaturation` 只能全局调节，按 8 个色相区间生成 25³ `.cube`（缓存在 `_grading_cache/`）
- **多蒙版按列表顺序链式叠加**：全局调色与全局 LUT 先执行，再对每个蒙版 `split` 两份，一份走该蒙版调色链、另一份取 `format=gray` 灰度图做 `alphamerge`，最后 `overlay` 回主画面
- **画笔 / 钢笔蒙版**由 numpy 栅格化为 PGM：画笔画软边圆点、钢笔扫描线填充 + 三次盒式模糊羽化，不依赖 Pillow
- **缩略图复用缓存的源帧**：首次预览把目标时间点解码并缩放成 `_base_cache/` 下的 PNG，之后改参数只重跑滤镜链（单帧约 0.07 秒，带蒙版约 0.09 秒）

### 常见问题

**GPU 显示不可用**
: 升级 NVIDIA 驱动到 610.00 以上并重启服务，或直接使用 CPU 模式。任务管理器 GPU 的 "Video Encode" 占用可确认硬件编码是否生效。

**转换失败：Permission denied**
: 多为文件锁（残留 FFmpeg 进程、播放器或剪辑软件占用同名文件）。程序会自动重试 3 次；仍失败时关闭占用该文件的软件后重试。

**10bit 输出无法播放**
: 10bit 必须使用 HEVC（H.264 10bit 兼容性极差）。旧播放器可能不支持，剪映、DaVinci Resolve、Premiere 及 Windows 11 均可正常读取。

**预览一直显示"正在生成"**
: HEVC 素材首次预览需要转码 720p 代理，稍等即可；之后命中缓存秒开。

**调了参数但画面没变化**
: 先确认「调色」面板里的值已改动（左侧栏该面板会显示小圆点），再确认强度未调到 0；若启用了蒙版，检查蒙版是否覆盖了想调的区域。

### 命令行版本

```bash
python main.py
```

```
1) Convert DJI Osmo Pocket 3 D-Log-M to Rec.709
2) Batch Convert DJI Osmo Pocket 3 D-Log-M to Rec.709
3) Convert General Video (with your own LUT)
4) Batch Convert General Videos (with your own LUT)
0) Exit
```

首次使用会自动下载 DJI 官方 D-Log-M → Rec.709 LUT 到 `luts/restore/`。`convert_batch_basic.py` 是早期独立脚本，路径硬编码在文件内。

### 使用建议

- 大批量只做 Log 还原、不需要逐条细调时，直接用命令行版本（`python main.py`）更省事
- 顺序：先「D-Log-M → Rec.709」全量还原，再从 `creative/` 套用风格 LUT 并降低强度（如 30–50%）
- Log 素材也可以直接用 `log_style/` 的 LUT，一步完成还原 + 风格化
- `creative/` 里的 LUT 面向 **Rec.709 输入**，直接套在 Log 原片上色彩会失真
- 10bit 素材建议保持 10bit 输出（HEVC），避免色深损失
- 局部调色时把羽化调大一些，过渡更自然；蒙版外的画面完全不受影响

### 许可与致谢

MIT License

- 官方 LUT：DJI（Pocket 3 / 4 / 4P）、Apple、ViVO、O-Log
- 视频处理：[FFmpeg](https://ffmpeg.org)

---

## English

LUT Studio restores Log footage to Rec.709 and **batch-grades videos with 3D LUTs, Lightroom-style primary grading, color wheels, curves and multi-layer masks**. It ships a desktop-style web UI (dark theme, preview stage, media filmstrip, export queue) plus a CLI, and bundles 53 LUTs (Log restoration, Log-to-look, and Rec.709 look LUTs).

Stack: Python + Flask + FFmpeg; the frontend is a Vue 3 + Vite project whose build output is served by Flask.

Repository: <https://github.com/aw1596/LUT-Studio>

### Features

**Web UI** (`server.py` + `frontend/`)

- Desktop layout: left tool rail, center preview stage, right inspector, bottom filmstrip; resizable inspector width and filmstrip height
- Preview zoom: wheel zooms around the cursor (1×–8×), drag to pan, double-click to reset
- Five panels: Media / Filter / Color / Export / Tasks
- Media scanning: point at a folder, clips are listed with thumbnail, duration and size; select all / clear; native folder picker
- Media import: drop videos anywhere in the window, or copy files and press Ctrl+V — they are copied into `_imports/` and added to the list (multi-file, auto-numbered on name clashes)
- Filmstrip navigation: arrow buttons plus horizontal wheel scrolling
- Filter gallery in three groups: restoration LUTs (primary), Log-to-look LUTs (primary), creative LUTs (secondary stack)
- Every filter card shows the actual current clip with that LUT applied (rendered and cached server-side)
- Restoration strength and secondary strength, each 0–100%, independent of each other
- **Primary grading**: temperature, tint, exposure, contrast, highlights, shadows, whites, blacks, saturation, vibrance, sharpness
- **Color wheels**: shadows / midtones / highlights, double-click to reset
- **Tone curves**: master + R / G / B channels, Catmull-Rom smoothing, plus shadows / midtones / highlights region sliders
- **HSL**: eight hue ranges with per-range hue / saturation / lightness, compiled into a 3D LUT on the fly
- **Split toning**: separate hue / saturation for shadows and highlights with a balance control
- **Calibration**: hue and saturation for the red / green / blue primaries
- **Masks**: linear / radial / rect / brush / pen, stackable, with enable / disable / delete, feather, invert and vertex undo
- **Per-mask grading**: each mask carries its own full grading set (primary, wheels, curves, HSL, calibration, split toning)
- Color panel grouped into collapsible sections, each with its own reset
- "Hold to compare" against the ungraded original
- Play graded preview / source (HEVC sources get a 720p proxy automatically)
- Export options: output location (prefix / subfolder / custom dir), resolution (original / 1080p / 720p), quality, bit depth (8bit / 10bit), encoder (GPU / CPU)
- Export queue with per-file progress, real errors and stop-all

**Processing pipeline**

- Grading runs **before** the LUT; sharpening runs **after** it
- 10bit uses a planar-RGB `gbrp10le` pipeline and outputs `yuv420p10le` (HEVC + `hvc1`)
- Masks blend in planar RGB with `split` + `alphamerge` + `overlay`; geometric mattes come from `geq`, brush / pen mattes are rasterized with numpy into PGM, both cached by parameter hash. Masks stack in list order, each with its own chain
- Curves, curve regions, split toning, highlights / shadows / whites / blacks use `curves`; HSL and vibrance are compiled into one 25³ 3D LUT; calibration uses `colorchannelmixer`
- LUT strength blends with the original; 100% adds no overhead
- Original frame rate preserved via `ffprobe`
- Encoding: 8bit → `h264_nvenc` / `libx264`; 10bit → `hevc_nvenc` / `libx265`
- Existing outputs are skipped; writing to the source path is refused
- 3× retry on `Permission denied`; partial files removed on failure; orphan FFmpeg children cleaned up on exit

### Requirements

- Python 3.7+
- FFmpeg and FFprobe on your `PATH`
- Flask and numpy: `pip install flask numpy`
  (numpy is only used to rasterize brush / pen masks; without it those two mask types are unavailable)
- Optional: NVIDIA GPU (NVENC)

> GPU encoding requires a driver satisfying FFmpeg's NVENC API version (FFmpeg 9 wants API 13.1 / driver 610.00+). If unavailable, the app keeps working and falls back to CPU.

### Quick start

```bash
git clone https://github.com/aw1596/LUT-Studio.git
cd LUT-Studio
pip install flask numpy

python server.py
```

Open <http://127.0.0.1:5000> (the server listens on `127.0.0.1:5000`).

Workflow:

1. In **Media**, enter a folder (e.g. `E:\DCIM\DJI_001`) and click Scan
2. Select clips in the filmstrip (all selected by default)
3. In **Filter**, pick a LUT and adjust strength; enable a second LUT if needed
4. In **Color**, tune temperature / exposure / contrast, drag the wheels, shape curves, or adjust HSL / split toning / calibration. For local grading, draw a mask, hit **Confirm** to add it, then grade each mask separately
5. In **Export**, choose location, resolution, bit depth and encoder, then start
6. Watch per-file progress and errors in **Tasks**

### Frontend dev & build

```bash
cd frontend
npm install         # first time only
npm run dev         # http://127.0.0.1:5173, /api proxied to Flask on 5000
npm run build       # bundles into ../web
```

- Backend-only changes need no Node: `web/` already contains built assets
- After editing `frontend/src/**` you must re-run `npm run build`

### Managing LUTs

Directories drive the groups; new files show up after a page refresh, no code change or restart needed.

**Restoration LUTs (primary)** — `luts/restore/`, 9 bundled:

| File | Display name |
| --- | --- |
| `DJI DLogM To Rec.709.cube` | DJI D-Log-M → Rec.709 |
| `DJI OSMO Pocket 4 D-Log to Rec.709.cube` | DJI Pocket 4 D-Log → Rec.709 |
| `DJI OSMO Pocket 4P D-Log2 to Rec.709.cube` | DJI Pocket 4P D-Log2 → Rec.709 |
| `Apple Log To Rec.709.cube` | Apple Log → Rec.709 |
| `Apple Log To Rec.709 Fix.cube` | Apple Log → Rec.709 (Fix) |
| `Apple Log2 To Rec.709.cube` | Apple Log 2 → Rec.709 |
| `ViVO Log To Rec.709.cube` | ViVO Log → Rec.709 |
| `O Log To Rec.709.cube` | O-Log → Rec.709 |
| `O Log2 To Rec709.cube` | O-Log 2 → Rec.709 |

**Log-to-look LUTs (primary)** — `luts/log_style/`; they take Log input and output Rec.709 + the look in one step, so no separate restoration LUT is needed. 23 bundled:

- Apple Log: `Apple Log - 赐福司影调`, `Apple Log - 风格化1/2/3`, `Apple Log2 - 赐福司影调`, `Apple Log2 - 风格化`
- `Log -  ANALOGICAKDK2383 D55 / D60 / D65`
- `Log -  Color Plus 200`, `EKTACHROME`, `Ektachrome E100`, `Elite Chrome 200`, `Gold 200`, `Kodak Ektar 100`, `Portra 160 / 400 / 800`, `Ultramax 400`, `VISION3 200T Color / 250D Color / 500T / 50D`

**Creative LUTs (secondary stack)** — `luts/creative/`, expect Rec.709 input; LUTs uploaded from the Filter panel are saved here too. 21 bundled:

- `ANALOGICAKDK2383 D55 / D60 / D65`
- DJI Pocket 3 seasonal Pro: `Autumn Pro`, `Spring Pro`, `Summer Pro`, `Winter Pro`
- `Color Plus 200`, `EKTACHROME`, `Ektachrome E100`, `Elite Chrome 200`, `Gold 200`, `Kodak Ektar 100`, `Portra 160 / 400 / 800`, `Ultramax 400`, `VISION3 200T Color / 250D Color / 500T / 50D`

Notes:

- Cards are labelled from filenames; the nine restoration LUTs above have Chinese display names, everything else uses the raw stem
- Creative thumbnails preview "current restoration LUT + that look LUT"
- LUTs prefixed `Log -` expect Log input (all kept in `luts/log_style/`); same-named LUTs in `creative/` expect Rec.709 input. A Log-to-look LUT needs no separate restoration LUT; when stacking a look on already-restored footage, pick the `creative/` version

### Project structure

```
LUT-Studio/
├── server.py                  # Flask server, grading/mask filter graph, conversion engine
├── helper.py                  # Shared CLI helpers: FFmpeg wrapper, FPS probe, LUT download
├── main.py                    # Interactive CLI entry point
├── convert_batch_basic.py     # Legacy batch script (hard-coded paths)
├── frontend/                  # Frontend source (Vue 3 + Vite + Element Plus)
│   ├── index.html             # Vite entry
│   ├── vite.config.js         # Builds into ../web; proxies /api to Flask in dev
│   └── src/
│       ├── App.vue            # State and business logic
│       ├── styles.css         # Global styles
│       └── components/        # Top bar, rail, player, filmstrip, feature panels
├── web/                       # Build output served by Flask
│   ├── index.html
│   └── assets/
├── luts/
│   ├── restore/               # Restoration LUTs (primary)
│   ├── log_style/             # Log-to-look LUTs (primary, Log input)
│   └── creative/              # Creative look LUTs (secondary stack, Rec.709 input)
└── .gitignore                 # Ignores node_modules, __pycache__ and caches
```

At runtime the app creates `_thumb_cache/`, `_base_cache/`, `_mask_cache/`, `_grading_cache/` and `_preview_cache/` in the project root; dropped / pasted videos are copied into `_imports/`. All of them are git-ignored, and caches are safe to delete.

### HTTP API

| Method | Path | Description |
| --- | --- | --- |
| GET | `/` | Single-page UI |
| GET | `/api/gpu_status` | Whether NVENC is usable, and why not |
| GET | `/api/list_videos?dir=` | List videos in a folder |
| POST | `/api/import_files` | Drag / paste import: accepts multipart `files`, copies into `_imports/` and returns clip metadata |
| GET | `/api/luts` | LUT list with `kind`: `restore` / `log` / `creative` |
| POST | `/api/upload_lut` | Upload a `.cube` into `luts/creative/` |
| POST | `/api/preview/ensure` | Playable preview URL (HEVC gets a 720p proxy) |
| GET | `/api/preview_file?path=` | Range-capable video stream |
| GET | `/api/thumb` | Single-frame thumbnail; accepts `lut` / `lut2` / `strength` / `grading` / `masks` |
| POST | `/api/pick_dir` | Native folder picker, returns `{title, initial}` |
| POST | `/api/preview_graded` | Render an 8-second 720p graded preview |
| POST | `/api/convert` | Submit a batch, returns `batch_id` |
| GET | `/api/batches` | All batches and per-file status |
| POST | `/api/stop_all` | Stop all conversions |
| GET | `/api/write_test?path=` | Diagnostics: test write access from the server process |

`grading` and `masks` can be JSON strings (query params for `/api/thumb`) or plain objects (POST body). The legacy single-mask `mask` parameter is still accepted.

`grading` fields:

- `temperature`, `tint`, `contrast`, `saturation`, `highlights`, `shadows`, `whites`, `blacks`, `vibrance`: -100…100
- `exposure`: -3…3; `sharpness`: 0…100
- `lift` / `gamma` / `gain`: each `{x, y}` (-1…1, the shadows / midtones / highlights wheels)
- `curve`: `{master, r, g, b}`, each entry `[{x, y}, …]` (0…1 points, at least two)
- `curve_regions`: `{shadows, midtones, highlights}` (each -100…100)
- `hsl`: eight hue ranges with `{h, s, l}` (`reds` / `oranges` / `yellows` / `greens` / `aquas` / `blues` / `purples` / `magentas`, each ±100)
- `split`: `{shadow_hue, shadow_sat, highlight_hue, highlight_sat, balance}` (hue 0…360, saturation 0…100, balance -100…100)
- `calibration`: `{red_hue, red_sat, green_hue, green_sat, blue_hue, blue_sat}` (each ±100)

`masks` is an array (up to 16 entries) applied in order, each entry containing:

- `name`: label for the UI only
- `enabled`: whether it takes part in rendering
- Shape and geometry: `shape` (`linear` / `radial` / `rect` / `brush` / `pen`), `cx` / `cy` (0…1), `size`, `aspect`, `angle`, `feather`, `invert`; `brush` / `pen` additionally need `brush_size` (0.01…0.5) and `strokes` (arrays of `{x, y}` points, up to 64) or `pen_points` (up to 256 `{x, y}` vertices)
- `grading`: the mask's own grading with the same fields as the global one; a fully neutral mask is skipped at render time

### Implementation notes

- **Tint and color wheels use `curves`**: `colorbalance` is a no-op in FFmpeg 9.0.2 here, so they are built as per-channel three-point curves (black → lift, mid → gamma, white → gain)
- Wheel directions match the on-screen gradient: green at the top, then clockwise yellow → red → magenta → blue → cyan
- **Highlights / shadows / whites / blacks and curve regions** are compiled into one six-anchor master curve (0, 0.2, 0.5, 0.8, 0.92, 1.0), forced monotonically increasing
- **Vibrance is folded into the HSL 3D LUT**: `eq` saturation is a plain linear scale, so vibrance is written into the same 25³ LUT as a per-lattice transform (quantized to steps of 5 and cached)
- **HSL is a generated 3D LUT**: `huesaturation` only works globally, so eight hue ranges are compiled into a 25³ `.cube` under `_grading_cache/`
- **Masks stack in list order**: global grading and the global LUT run first, then each mask does `split`, grades one copy, turns the other into a `format=gray` matte for `alphamerge`, and `overlay`s back — later masks act on earlier results
- **Brush / pen mattes** are rasterized with numpy to PGM: brush stamps soft dots, pen scan-fills a polygon and feathers with three box blurs (no Pillow needed)
- **Thumbnails reuse a cached source frame**: about 70 ms per frame (90 ms with masks) instead of roughly 400 ms

### Troubleshooting

**GPU shown as unavailable**
: Update the NVIDIA driver to 610.00+ and restart, or use CPU mode. Check GPU "Video Encode" usage in Task Manager.

**Conversion fails with `Permission denied`**
: Usually a file lock from an orphan FFmpeg process, a player or editing software. The app retries three times; close whatever holds the file and retry.

**10bit output won't play**
: 10bit requires HEVC (H.264 10bit is poorly supported). CapCut, DaVinci Resolve, Premiere and Windows 11 handle it fine.

**Preview stuck on "generating"**
: The first HEVC preview needs a 720p proxy transcode; later previews hit the cache instantly.

**Parameters changed but the image looks the same**
: Make sure the values actually moved, LUT strength is not 0, and — if a mask is on — that it covers the area you are grading.

### Command-line usage

```bash
python main.py
```

```
1) Convert DJI Osmo Pocket 3 D-Log-M to Rec.709
2) Batch Convert DJI Osmo Pocket 3 D-Log-M to Rec.709
3) Convert General Video (with your own LUT)
4) Batch Convert General Videos (with your own LUT)
0) Exit
```

On first run the official DJI D-Log-M → Rec.709 LUT is downloaded into `luts/restore/`. `convert_batch_basic.py` is an older standalone script with hard-coded paths.

### Recommended workflow

- Bulk log-restoration only? Run the CLI (`python main.py`) instead
- Chain order: «D-Log-M → Rec.709» at full strength first, then a look LUT from `creative/` at reduced strength (e.g. 30–50%)
- Log footage can also use a `log_style/` LUT directly to do restoration + look in one step
- LUTs in `creative/` expect **Rec.709 input**; applying them to Log footage shifts colors incorrectly
- Keep 10bit footage at 10bit (HEVC) output to avoid losing color depth
- For local grading, raise the feather a little for a smoother falloff

### License & credits

MIT License

- Official LUTs: DJI (Pocket 3 / 4 / 4P), Apple, ViVO, O-Log
- Video processing: [FFmpeg](https://ffmpeg.org)
