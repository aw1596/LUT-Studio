import atexit
import hashlib
import json
import math
import os
import subprocess
import sys
import threading
import uuid

from flask import Flask, request, jsonify, send_from_directory, send_file

from helper import to_ffmpeg_lut_path, get_video_fps, download_dji_lut_if_needed

try:
    import numpy as np
except ImportError:  # 画笔 / 钢笔蒙版需要 numpy
    np = None

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
WEB_DIR = os.path.join(BASE_DIR, "web")
LUTS_DIR = os.path.join(BASE_DIR, "luts")
RESTORE_LUTS_DIR = os.path.join(LUTS_DIR, "restore")  # 官方灰片还原 LUT，放进来即自动显示
LOG_STYLE_LUTS_DIR = os.path.join(LUTS_DIR, "log_style")  # Log 直转风格化 LUT（输入为 Log，输出 Rec.709 + 风格）
CREATIVE_LUTS_DIR = os.path.join(LUTS_DIR, "creative")  # 个性化 / 风格 LUT（输入为 Rec.709）
PREVIEW_CACHE_DIR = os.path.join(BASE_DIR, "_preview_cache")
THUMB_CACHE_DIR = os.path.join(BASE_DIR, "_thumb_cache")
MASK_CACHE_DIR = os.path.join(BASE_DIR, "_mask_cache")
GRADING_CACHE_DIR = os.path.join(BASE_DIR, "_grading_cache")
BASE_CACHE_DIR = os.path.join(BASE_DIR, "_base_cache")  # 解码后的单帧原图，调参时复用
IMPORT_DIR = os.path.join(BASE_DIR, "_imports")  # 拖拽 / 粘贴导入的视频副本
os.makedirs(LUTS_DIR, exist_ok=True)
os.makedirs(RESTORE_LUTS_DIR, exist_ok=True)
os.makedirs(LOG_STYLE_LUTS_DIR, exist_ok=True)
os.makedirs(CREATIVE_LUTS_DIR, exist_ok=True)
os.makedirs(PREVIEW_CACHE_DIR, exist_ok=True)
os.makedirs(THUMB_CACHE_DIR, exist_ok=True)
os.makedirs(MASK_CACHE_DIR, exist_ok=True)
os.makedirs(GRADING_CACHE_DIR, exist_ok=True)
os.makedirs(BASE_CACHE_DIR, exist_ok=True)
os.makedirs(IMPORT_DIR, exist_ok=True)
os.chdir(BASE_DIR)  # 保证 helper 中的相对路径行为一致

VIDEO_EXTS = ('.mp4', '.mov', '.mkv', '.avi', '.mxf', '.webm')

app = Flask(__name__, static_folder=WEB_DIR, static_url_path='')

batches = {}
batches_lock = threading.Lock()
active_outputs = set()  # 正在写入的输出路径，防止并发任务写同一文件
active_lock = threading.Lock()
stop_event = threading.Event()  # 置位后所有任务停止
current_procs = {}  # 正在运行的 ffmpeg 进程：input_path -> Popen
procs_lock = threading.Lock()
gen_sem = threading.Semaphore(2)  # 限制同时生成的缩略图/预览数量，避免多个 4K 解码抢资源


def _cleanup_procs():
    """服务退出时杀掉所有残留 ffmpeg 子进程，防止孤儿进程锁定输出文件"""
    with procs_lock:
        procs = list(current_procs.values())
    for p in procs:
        try:
            p.kill()
        except Exception:
            pass


atexit.register(_cleanup_procs)

# 启动时检测 NVENC 是否可用（驱动过旧会失败）
NVENC_OK = False
NVENC_MSG = ""
PREVIEW_GPU_OK = False  # 预览走 GPU 解码 + NVENC；运行失败时回退 CPU 并置 False
PREVIEW_HW_OK = None  # 预览能否用 NVDEC 硬解；None=未验证，失败后置 False 不再尝试


def check_nvenc():
    global NVENC_OK, NVENC_MSG, PREVIEW_GPU_OK
    try:
        r = subprocess.run(
            ["ffmpeg", "-hide_banner", "-loglevel", "error",
             "-f", "lavfi", "-i", "testsrc=duration=0.1:size=640x360:rate=30",
             "-c:v", "h264_nvenc", "-f", "null", "-"],
            capture_output=True, text=True, timeout=30)
        if r.returncode == 0:
            NVENC_OK, NVENC_MSG = True, ""
        else:
            lines = [l for l in r.stderr.strip().splitlines() if l]
            NVENC_OK, NVENC_MSG = False, (lines[0] if lines else "NVENC 初始化失败")
    except Exception as e:
        NVENC_OK, NVENC_MSG = False, str(e)
    PREVIEW_GPU_OK = NVENC_OK


@app.route('/')
def index():
    return send_from_directory(WEB_DIR, 'index.html')


@app.route('/api/gpu_status')
def gpu_status():
    return jsonify({"available": NVENC_OK, "message": NVENC_MSG})


def get_video_duration(path):
    """用 ffprobe 获取视频总时长（秒）"""
    try:
        result = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", path],
            capture_output=True, text=True, check=True)
        return float(result.stdout.strip())
    except Exception:
        return None


def get_video_codec(path):
    """用 ffprobe 获取视频编码格式"""
    try:
        result = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "v:0",
             "-show_entries", "stream=codec_name",
             "-of", "default=noprint_wrappers=1:nokey=1", path],
            capture_output=True, text=True, check=True)
        return result.stdout.strip().lower()
    except Exception:
        return ""


@app.route('/api/list_videos')
def list_videos():
    directory = request.args.get('dir', '').strip().strip('"')
    if not os.path.isdir(directory):
        return jsonify({"error": "目录不存在"}), 400
    files = []
    for name in sorted(os.listdir(directory)):
        if name.lower().endswith(VIDEO_EXTS):
            full = os.path.join(directory, name)
            files.append({
                "name": name,
                "path": full,
                "size": os.path.getsize(full),
                "duration": get_video_duration(full),
            })
    return jsonify({"files": files})


@app.route('/api/import_files', methods=['POST'])
def import_files():
    """拖拽 / 粘贴导入：浏览器只能拿到文件内容、拿不到原始路径，因此复制一份到 _imports/ 后返回路径"""
    uploads = request.files.getlist('files')
    if not uploads:
        return jsonify({"error": "没有收到文件"}), 400
    results = []
    for f in uploads:
        name = os.path.basename(f.filename or '')
        if not name.lower().endswith(VIDEO_EXTS):
            continue
        tmp = os.path.join(IMPORT_DIR, ".tmp-" + uuid.uuid4().hex)
        f.save(tmp)
        size = os.path.getsize(tmp)
        dest = os.path.join(IMPORT_DIR, name)
        if os.path.exists(dest) and os.path.getsize(dest) == size:
            os.remove(tmp)  # 同名同大小视为同一文件，避免重复占用磁盘
        elif os.path.exists(dest):
            stem, ext = os.path.splitext(name)
            i = 1
            while os.path.exists(dest):
                dest = os.path.join(IMPORT_DIR, f"{stem} ({i}){ext}")
                i += 1
            os.replace(tmp, dest)
        else:
            os.replace(tmp, dest)
        results.append({
            "name": os.path.basename(dest),
            "path": dest,
            "size": size,
            "duration": get_video_duration(dest),
        })
    if not results:
        return jsonify({"error": "仅支持 mp4 / mov / mkv / avi / mxf / webm 视频"}), 400
    return jsonify({"files": results})


LUT_DISPLAY_NAMES = {
    "DJI DLogM To Rec.709": "DJI D-Log-M → Rec.709",
    "DJI OSMO Pocket 4 D-Log to Rec.709": "DJI Pocket 4 D-Log → Rec.709",
    "DJI OSMO Pocket 4P D-Log2 to Rec.709": "DJI Pocket 4P D-Log2 → Rec.709",
    "Apple Log To Rec.709": "Apple Log → Rec.709",
    "Apple Log To Rec.709 Fix": "Apple Log → Rec.709 (Fix)",
    "Apple Log2 To Rec.709": "Apple Log 2 → Rec.709",
    "O Log To Rec.709": "O-Log → Rec.709",
    "O Log2 To Rec709": "O-Log 2 → Rec.709",
    "ViVO Log To Rec.709": "ViVO Log → Rec.709",
}


def lut_display_name(filename):
    # 兼容被重复改名成 xxx.cube.cube 的文件：剥掉所有 .cube 后缀再显示
    stem = filename
    while stem.lower().endswith('.cube'):
        stem = stem[:-5]
    return LUT_DISPLAY_NAMES.get(stem, stem)


def _scan_lut_dir(directory, kind):
    """扫描目录里的 .cube；新增文件无需改代码，刷新页面即可显示"""
    items = []
    if not os.path.isdir(directory):
        return items
    for name in sorted(os.listdir(directory)):
        if name.lower().endswith('.cube'):
            items.append({"name": lut_display_name(name),
                          "path": os.path.join(directory, name),
                          "kind": kind})
    # 还原目录把 DJI 的 LUT 排在最前，作为默认选项（本工具主要面向 Osmo 素材）
    if kind == 'restore':
        items.sort(key=lambda it: (0 if os.path.basename(it["path"]).startswith("DJI") else 1, it["name"]))
    return items


@app.route('/api/luts')
def list_luts():
    # restore 目录优先；luts/ 根目录保留兼容旧文件，一并按个性化处理
    luts = (_scan_lut_dir(RESTORE_LUTS_DIR, 'restore')
            + _scan_lut_dir(LOG_STYLE_LUTS_DIR, 'log')
            + _scan_lut_dir(CREATIVE_LUTS_DIR, 'creative')
            + _scan_lut_dir(LUTS_DIR, 'creative'))
    return jsonify({"luts": luts})


@app.route('/api/upload_lut', methods=['POST'])
def upload_lut():
    f = request.files.get('file')
    if not f or not f.filename.lower().endswith('.cube'):
        return jsonify({"error": "仅支持 .cube 文件"}), 400
    # 上传的 LUT 归入个性化目录；官方还原 LUT 直接拷进 luts/restore/ 即可
    save_path = os.path.join(CREATIVE_LUTS_DIR, os.path.basename(f.filename))
    f.save(save_path)
    return jsonify({"ok": True, "path": save_path, "name": f.filename})


# === 视频预览 ===

@app.route('/api/preview/ensure', methods=['POST'])
def preview_ensure():
    """确保有可播放的预览流。H.264 的 mp4/mov 直接播原文件；HEVC 等格式生成 720p 代理。"""
    path = (request.get_json(force=True).get('path') or '').strip().strip('"')
    if not os.path.isfile(path):
        return jsonify({"error": "文件不存在"}), 404

    codec = get_video_codec(path)
    ext = os.path.splitext(path)[1].lower()
    if codec == 'h264' and ext in ('.mp4', '.mov', '.m4v'):
        return jsonify({"url": "/api/preview_file?path=" + path, "proxied": False})

    # 生成预览代理（缓存按路径+修改时间命名）
    key = hashlib.md5((path + str(os.path.getmtime(path))).encode()).hexdigest()
    cache_path = os.path.join(PREVIEW_CACHE_DIR, key + ".mp4")
    if not os.path.isfile(cache_path):
        cmd = [
            "ffmpeg", "-y", "-i", path,
            "-vf", "scale=-2:720",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "28",
            "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "128k",
            "-movflags", "+faststart",
            cache_path,
        ]
        r = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8', errors='replace')
        if r.returncode != 0 or not os.path.isfile(cache_path):
            tail = "\n".join(r.stderr.strip().splitlines()[-8:])
            return jsonify({"error": "预览生成失败：" + tail[-500:]}), 500
    return jsonify({"url": "/api/preview_file?path=" + cache_path, "proxied": True})


@app.route('/api/preview_file')
def preview_file():
    """以支持 Range 的方式发送视频流（浏览器可拖动进度条）"""
    path = request.args.get('path', '')
    if not os.path.isfile(path):
        return "Not found", 404
    return send_file(path, conditional=True)


def _cache_key(*parts):
    raw = "|".join(str(p) for p in parts)
    return hashlib.md5(raw.encode()).hexdigest()


def _file_mtime(path):
    try:
        return os.path.getmtime(path)
    except OSError:
        return 0


# === 视频探测（带缓存，避免同一文件反复 ffprobe） ===

_probe_cache = {}
_probe_lock = threading.Lock()


def probe_video(path):
    """一次 ffprobe 获取宽高/时长/帧率，按路径 + 修改时间缓存"""
    key = (path, _file_mtime(path))
    with _probe_lock:
        hit = _probe_cache.get(key)
    if hit is not None:
        return hit
    info = {"width": 0, "height": 0, "duration": None, "fps": 30.0}
    try:
        r = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "v:0",
             "-show_entries", "stream=width,height,avg_frame_rate",
             "-show_entries", "format=duration", "-of", "json", path],
            capture_output=True, text=True, encoding='utf-8', errors='replace')
        d = json.loads(r.stdout or "{}")
        st = (d.get("streams") or [{}])[0]
        info["width"] = int(st.get("width") or 0)
        info["height"] = int(st.get("height") or 0)
        num, _, den = str(st.get("avg_frame_rate") or "0/0").partition("/")
        try:
            fps = float(num) / float(den or 1)
            info["fps"] = fps if 0 < fps < 1000 else 30.0
        except (ValueError, ZeroDivisionError):
            info["fps"] = 30.0
        dur = (d.get("format") or {}).get("duration")
        info["duration"] = float(dur) if dur else None
    except Exception:
        pass
    with _probe_lock:
        _probe_cache[key] = info
    return info


def _clamp(v, lo, hi):
    return max(lo, min(hi, v))


def _pixel_rate(info):
    """素材的像素吞吐（宽 × 高 × 帧率），用于判断是否值得走硬件解码"""
    return (info.get("width") or 0) * (info.get("height") or 0) * (info.get("fps") or 0)


def _parse_curve_regions(raw):
    """曲线区域滑块：暗部 / 中间调 / 高光（-100 ~ 100）"""
    raw = raw if isinstance(raw, dict) else {}
    return {
        k: _clamp(float(raw.get(k, 0) or 0), -100, 100)
        for k in ("shadows", "midtones", "highlights")
    }


# === 调色（仿 DaVinci 一级调色） ===

def parse_grading(data):
    """从请求中解析调色参数：白平衡/曝光/对比/饱和/锐化 + 色轮 + 曲线 + HSL + 分离色调 + 校准"""
    raw = data.get("grading") or {}
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except ValueError:
            raw = {}
    if not isinstance(raw, dict):
        raw = {}
    g = {
        "temperature": _clamp(float(raw.get("temperature", 0) or 0), -100, 100),
        "tint": _clamp(float(raw.get("tint", 0) or 0), -100, 100),
        "exposure": _clamp(float(raw.get("exposure", 0) or 0), -3, 3),
        "contrast": _clamp(float(raw.get("contrast", 0) or 0), -100, 100),
        "highlights": _clamp(float(raw.get("highlights", 0) or 0), -100, 100),
        "shadows": _clamp(float(raw.get("shadows", 0) or 0), -100, 100),
        "whites": _clamp(float(raw.get("whites", 0) or 0), -100, 100),
        "blacks": _clamp(float(raw.get("blacks", 0) or 0), -100, 100),
        "saturation": _clamp(float(raw.get("saturation", 0) or 0), -100, 100),
        "vibrance": _clamp(float(raw.get("vibrance", 0) or 0), -100, 100),
        "sharpness": _clamp(float(raw.get("sharpness", 0) or 0), 0, 100),
    }
    g["curve_regions"] = _parse_curve_regions(raw.get("curve_regions"))
    for key in ("lift", "gamma", "gain"):
        w = raw.get(key) or {}
        if not isinstance(w, dict):
            w = {}
        g[key] = {
            "x": _clamp(float(w.get("x", 0) or 0), -1, 1),
            "y": _clamp(float(w.get("y", 0) or 0), -1, 1),
        }
    g["curve"] = _parse_curve(raw.get("curve"))
    g["hsl"] = _parse_hsl(raw.get("hsl"))
    sp = raw.get("split") or {}
    if not isinstance(sp, dict):
        sp = {}
    g["split"] = {
        "shadow_hue": float(sp.get("shadow_hue", 40) or 0) % 360,
        "shadow_sat": _clamp(float(sp.get("shadow_sat", 0) or 0), 0, 100),
        "highlight_hue": float(sp.get("highlight_hue", 210) or 0) % 360,
        "highlight_sat": _clamp(float(sp.get("highlight_sat", 0) or 0), 0, 100),
        "balance": _clamp(float(sp.get("balance", 0) or 0), -100, 100),
    }
    cal = raw.get("calibration") or {}
    if not isinstance(cal, dict):
        cal = {}
    g["calibration"] = {
        k: _clamp(float(cal.get(k, 0) or 0), -100, 100)
        for k in ("red_hue", "red_sat", "green_hue", "green_sat", "blue_hue", "blue_sat")
    }
    return g


CURVE_CHANNELS = ("master", "r", "g", "b")


def _parse_curve(raw):
    """曲线控制点 → {通道: [(x, y), ...]}；少于两点视为未启用"""
    out = {}
    raw = raw if isinstance(raw, dict) else {}
    for ch in CURVE_CHANNELS:
        pts = raw.get(ch)
        clean = []
        if isinstance(pts, list):
            for p in pts[:16]:
                if not isinstance(p, dict):
                    continue
                try:
                    x = _clamp(float(p.get("x", 0) or 0), 0, 1)
                    y = _clamp(float(p.get("y", 0) or 0), 0, 1)
                except (TypeError, ValueError):
                    continue
                clean.append((x, y))
        clean.sort()
        dedup = []
        for x, y in clean:
            if dedup and abs(dedup[-1][0] - x) < 1e-4:
                dedup[-1] = (x, y)
            else:
                dedup.append((x, y))
        out[ch] = dedup if len(dedup) >= 2 else []
    return out


HSL_KEYS = ("reds", "oranges", "yellows", "greens", "aquas", "blues", "purples", "magentas")
HSL_CENTERS = {"reds": 0.0, "oranges": 30.0, "yellows": 60.0, "greens": 120.0,
               "aquas": 180.0, "blues": 240.0, "purples": 280.0, "magentas": 320.0}


def _parse_hsl(raw):
    raw = raw if isinstance(raw, dict) else {}
    out = {}
    for k in HSL_KEYS:
        w = raw.get(k)
        w = w if isinstance(w, dict) else {}
        out[k] = {
            "h": _clamp(float(w.get("h", 0) or 0), -100, 100),
            "s": _clamp(float(w.get("s", 0) or 0), -100, 100),
            "l": _clamp(float(w.get("l", 0) or 0), -100, 100),
        }
    return out


def _curve_is_linear(pts):
    return all(abs(x - y) < 0.005 for x, y in pts)


def is_neutral_grading(g):
    if not g:
        return True
    wheels_zero = all(abs(g[k]["x"]) < 0.02 and abs(g[k]["y"]) < 0.02
                      for k in ("lift", "gamma", "gain"))
    curve_used = any(pts and not _curve_is_linear(pts) for pts in g["curve"].values())
    regions_used = any(abs(v) >= 1 for v in g["curve_regions"].values())
    hsl_used = any(abs(v[k]) >= 1 for v in g["hsl"].values() for k in ("h", "s", "l"))
    split = g["split"]
    split_used = split["shadow_sat"] >= 2 or split["highlight_sat"] >= 2
    cal_used = any(abs(v) >= 1 for v in g["calibration"].values())
    tone_used = any(abs(g[k]) >= 1 for k in
                    ("highlights", "shadows", "whites", "blacks", "vibrance"))
    return (abs(g["temperature"]) < 0.5 and abs(g["tint"]) < 0.5
            and abs(g["exposure"]) < 0.01 and abs(g["contrast"]) < 0.5
            and abs(g["saturation"]) < 0.5 and g["sharpness"] < 1 and wheels_zero
            and not tone_used and not curve_used and not regions_used
            and not hsl_used and not split_used and not cal_used)



def _hsv_rgb(hue):
    """HSV(hue, 1, 1) → RGB 三元组（色相环上最饱和的颜色）"""
    h = (hue % 360.0) / 60.0
    i = int(h) % 6
    f = h - int(h)
    return [
        (1.0, f, 0.0), (1.0 - f, 1.0, 0.0), (0.0, 1.0, f),
        (0.0, 1.0 - f, 1.0), (f, 0.0, 1.0), (1.0, 0.0, 1.0 - f),
    ][i]


def _wheel_rgb(w, strength=0.35):
    """色轮坐标 (x, y) → RGB 偏移量；x 右为正、y 上为正。

    与前端色轮渐变保持一致：正上方为绿，顺时针依次为 黄 → 红 → 品红 → 蓝 → 青。
    """
    x, y = w["x"], w["y"]
    dist = math.hypot(x, y)
    if dist < 0.02:
        return (0.0, 0.0, 0.0)
    ang = math.degrees(math.atan2(x, y)) % 360.0  # 0° 在正上方，顺时针递增
    rgb = _hsv_rgb(120.0 - ang)  # 正上方(0°)对应 HSV 120°（绿）
    mean = sum(rgb) / 3.0
    amp = min(dist, 1.0) * strength
    return tuple((c - mean) * amp for c in rgb)


def _curve_points(lo, mid, hi):
    """黑/中/白三个输出锚点 → curves 控制点字符串"""
    return (f"0/{_clamp(lo, 0.0, 0.95):.4f} "
            f"0.5/{_clamp(mid, 0.02, 0.98):.4f} "
            f"1/{_clamp(hi, 0.05, 1.0):.4f}")


def _channel_curve(lift, gamma, gain):
    """单通道的 lift/gamma/gain 偏移 → curves 三点曲线"""
    lo = _clamp(lift * 0.32, 0.0, 0.30)
    mid = _clamp(0.5 + gamma * 0.35 + lift * 0.12, 0.05, 0.95)
    hi = _clamp(1.0 + gain * 0.45 + lift * 0.20, 0.55, 1.0)
    return _curve_points(lo, mid, hi)


def _curves_filter(r, g, b):
    return f"curves=r='{r}':g='{g}':b='{b}'"


def _rgb_to_hsv(r, g, b):
    mx = max(r, g, b)
    mn = min(r, g, b)
    d = mx - mn
    if mx <= 1e-9:
        return 0.0, 0.0, 0.0
    s = d / mx
    if s <= 1e-9:
        return 0.0, 0.0, mx
    if mx == r:
        h = ((g - b) / d) % 6.0
    elif mx == g:
        h = (b - r) / d + 2.0
    else:
        h = (r - g) / d + 4.0
    return h / 6.0, s, mx


def _hsv_to_rgb(h, s, v):
    if s <= 1e-9:
        return v, v, v
    h6 = (h % 1.0) * 6.0
    i = int(h6)
    f = h6 - i
    p = v * (1 - s)
    q = v * (1 - s * f)
    t = v * (1 - s * (1 - f))
    return [(v, t, p), (q, v, p), (p, v, t), (p, q, v), (t, p, v), (v, p, q)][i % 6]


def _hue_dist(a, b):
    d = abs(a - b) % 360.0
    return d if d <= 180 else 360 - d


def _hsl_lut(hsl, vibrance=0, size=25):
    """按 8 个色相区间做 HSL 微调，并叠加自然饱和度，生成 3D LUT（.cube）并缓存。

    ffmpeg 的 huesaturation 只能对所有色相做统一偏移，无法按颜色区分，
    也没有自然饱和度，因此这里用 Python 生成一张 3D LUT，再交给 lut3d 应用。
    """
    # 量化到 5 的倍数，避免拖动滑杆时生成大量近似 LUT
    q = {k: {kk: int(round(v[kk] / 5.0) * 5) for kk in ("h", "s", "l")}
         for k, v in hsl.items()}
    active = [(HSL_CENTERS[k], q[k]) for k in HSL_KEYS
              if abs(q[k]["h"]) >= 1 or abs(q[k]["s"]) >= 1 or abs(q[k]["l"]) >= 1]
    vib = int(round(vibrance / 5.0) * 5) / 100.0
    if not active and abs(vib) < 0.01:
        return None
    key = _cache_key("hsl", json.dumps(q, sort_keys=True), vib, size)
    out = os.path.join(GRADING_CACHE_DIR, key + ".cube")
    if os.path.isfile(out):
        return out

    step = 1.0 / (size - 1)
    rows = ["LUT_3D_SIZE %d" % size, "DOMAIN_MIN 0 0 0", "DOMAIN_MAX 1 1 1"]
    for bi in range(size):
        b = bi * step
        for gi in range(size):
            g = gi * step
            for ri in range(size):
                r = ri * step
                h, s, v = _rgb_to_hsv(r, g, b)
                if s > 0.01:
                    wsum = dh = ds = dl = 0.0
                    hue_deg = h * 360.0
                    for center, adj in active:
                        w = 1.0 - _hue_dist(hue_deg, center) / 45.0
                        if w <= 0:
                            continue
                        wsum += w
                        dh += w * adj["h"] * 0.30      # ±100 → ±30°
                        ds += w * adj["s"] / 100.0
                        dl += w * adj["l"] / 100.0
                    if wsum > 0:
                        h = (h + (dh / wsum) / 360.0) % 1.0
                        s = _clamp(s * (1.0 + ds / wsum), 0.0, 1.0)
                        v = _clamp(v * (1.0 + dl / wsum * 0.6), 0.0, 1.0)
                    if abs(vib) >= 0.01:
                        # 自然饱和度：低饱和像素提升更多，高饱和像素基本不动
                        if vib > 0:
                            s = _clamp(s + vib * 0.5 * (1.0 - s), 0.0, 1.0)
                        else:
                            s = _clamp(s * (1.0 + vib * 0.6), 0.0, 1.0)
                rr, gg, bb = _hsv_to_rgb(h, s, v)
                rows.append(f"{rr:.6f} {gg:.6f} {bb:.6f}")

    tmp = out + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write("\n".join(rows) + "\n")
    os.replace(tmp, out)
    return out


def _tonal_curve_filter(blacks=0, shadows=0, midtones=0, highlights=0, whites=0):
    """色调区域 → master 曲线：黑色 / 阴影 / 中间调 / 高光 / 白色"""
    if all(abs(v) < 1 for v in (blacks, shadows, midtones, highlights, whites)):
        return None
    xs = (0.0, 0.2, 0.5, 0.8, 0.92, 1.0)
    ys = [
        _clamp(blacks / 100.0 * 0.12, -0.14, 0.18),
        _clamp(0.2 + shadows / 100.0 * 0.15, 0.02, 0.42),
        _clamp(0.5 + midtones / 100.0 * 0.14, 0.25, 0.75),
        _clamp(0.8 + highlights / 100.0 * 0.16, 0.5, 0.99),
        _clamp(0.92 + whites / 100.0 * 0.08, 0.7, 1.0),
        1.0,
    ]
    ys[0] = _clamp(ys[0], 0.0, 0.98)
    # 保证曲线单调递增，避免 ffmpeg curves 报错
    for i in range(1, len(ys)):
        ys[i] = max(ys[i], ys[i - 1] + 0.005)
    ys[-1] = _clamp(ys[-1], 0.0, 1.0)
    coords = " ".join(f"{x:.4f}/{y:.4f}" for x, y in zip(xs, ys))
    return f"curves=master='{coords}'"


def _tone_curve_filter(curve):
    """用户色调曲线 → curves 滤镜（支持主通道与 R/G/B）"""
    parts = []
    for ch in CURVE_CHANNELS:
        pts = curve.get(ch) or []
        if len(pts) < 2 or _curve_is_linear(pts):
            continue
        name = "master" if ch == "master" else ch
        coords = " ".join(f"{x:.4f}/{y:.4f}" for x, y in pts)
        parts.append(f"{name}='{coords}'")
    return "curves=" + ":".join(parts) if parts else None


def _split_toning_filter(split):
    """分离色调：暗部/高光分别按色相上色，balance 移动交界点"""
    ss = split["shadow_sat"] / 100.0
    hs = split["highlight_sat"] / 100.0
    if ss < 0.02 and hs < 0.02:
        return None
    sc = _hsv_rgb(split["shadow_hue"])
    hc = _hsv_rgb(split["highlight_hue"])
    mid = _clamp(0.5 + split["balance"] / 100.0 * 0.35, 0.2, 0.8)
    chrones = []
    for i in range(3):
        lo = sum(sc) / 3.0
        hi = sum(hc) / 3.0
        y_lo = _clamp((sc[i] - lo) * ss * 0.45, 0.0, 0.45)
        y_hi = _clamp(1.0 + (hc[i] - hi) * hs * 0.45, 0.55, 1.0)
        chrones.append(f"0/{y_lo:.4f} {mid:.4f}/0.5000 1/{y_hi:.4f}")
    return f"curves=r='{chrones[0]}':g='{chrones[1]}':b='{chrones[2]}'"


def _calibration_filter(cal):
    """校准：用 3x3 通道矩阵近似主色相旋转与饱和度增益"""
    if all(abs(v) < 1.0 for v in cal.values()):
        return None
    m = [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]]
    # (通道下标, 顺时针方向的下一个通道, 上一个通道, 色相, 饱和度)
    for idx, nxt, prv, hue, sat in (
        (0, 1, 2, cal["red_hue"], cal["red_sat"]),
        (1, 2, 0, cal["green_hue"], cal["green_sat"]),
        (2, 0, 1, cal["blue_hue"], cal["blue_sat"]),
    ):
        h = hue / 100.0 * 0.25
        s = sat / 100.0
        m[idx][idx] += s * 0.35
        m[idx][nxt] += h * 0.35
        m[prv][idx] -= h * 0.15
    names = ("rr", "rg", "rb", "gr", "gg", "gb", "br", "bg", "bb")
    vals = [m[i][j] for i in range(3) for j in range(3)]
    return "colorchannelmixer=" + ":".join(f"{n}={v:.4f}" for n, v in zip(names, vals))


def grading_steps(g, sharpen=True):
    """返回 (LUT 前滤镜, LUT 后滤镜)：白平衡 → 曝光 → 对比/饱和 → 高光/阴影/白色/黑色
    → 色轮 → 校准 → HSL/自然饱和度 → 曲线 → 分离色调 → LUT → 锐化

    注意：ffmpeg 9.0.2 的 colorbalance 滤镜完全不生效（RGB/YUV 均无输出变化），
    因此色调与色轮改用 curves 的三锚点曲线实现。
    """
    pre, post = [], []
    if not g:
        return pre, post
    if abs(g["temperature"]) >= 0.5:
        # colortemperature 的 temperature 越低画面越暖，因此正值（向右拖）要往下调色温
        kelvin = int(round(6500 - g["temperature"] * 25))  # -100 → 9000K（冷），+100 → 4000K（暖）
        pre.append(f"colortemperature=temperature={_clamp(kelvin, 1000, 40000)}:mix=1")
    if abs(g["tint"]) >= 0.5:
        # 正值偏品红：绿中间调下压、蓝中间调上提
        t = g["tint"] / 100 * 0.12
        pre.append(_curves_filter(
            _curve_points(0, 0.5, 1),
            _curve_points(0, 0.5 - t, 1),
            _curve_points(0, 0.5 + t, 1),
        ))
    if abs(g["exposure"]) >= 0.01:
        pre.append(f"exposure=exposure={g['exposure']:.2f}")
    if abs(g["contrast"]) >= 0.5 or abs(g["saturation"]) >= 0.5:
        c = 1 + g["contrast"] / 200.0
        s = 1 + g["saturation"] / 100.0
        pre.append(f"eq=contrast={c:.3f}:saturation={s:.3f}")
    # 一级调色：高光 / 阴影 / 白色 / 黑色（区域色调曲线）
    tone_filter = _tonal_curve_filter(g["blacks"], g["shadows"], 0,
                                      g["highlights"], g["whites"])
    if tone_filter:
        pre.append(tone_filter)
    lift = _wheel_rgb(g["lift"])
    gam = _wheel_rgb(g["gamma"])
    gain = _wheel_rgb(g["gain"])
    if any(abs(v) > 0.001 for v in lift + gam + gain):
        pre.append(_curves_filter(
            _channel_curve(lift[0], gam[0], gain[0]),
            _channel_curve(lift[1], gam[1], gain[1]),
            _channel_curve(lift[2], gam[2], gain[2]),
        ))
    cal_filter = _calibration_filter(g["calibration"])
    if cal_filter:
        pre.append(cal_filter)
    reg = g["curve_regions"]
    region_filter = _tonal_curve_filter(0, reg["shadows"], reg["midtones"],
                                        reg["highlights"], 0)
    if region_filter:
        pre.append(region_filter)
    hsl_lut = _hsl_lut(g["hsl"], g["vibrance"])
    if hsl_lut:
        pre.append(f"lut3d={to_ffmpeg_lut_path(hsl_lut)}")
    curve_filter = _tone_curve_filter(g["curve"])
    if curve_filter:
        pre.append(curve_filter)
    split_filter = _split_toning_filter(g["split"])
    if split_filter:
        pre.append(split_filter)
    if sharpen and g["sharpness"] >= 1:
        post.append(f"unsharp=5:5:{g['sharpness'] / 50:.2f}")
    return pre, post


# === 蒙版 ===

def _parse_points(raw, limit=2000):
    """归一化点列表 → [{'x':..,'y':..}]"""
    pts = []
    if isinstance(raw, list):
        for p in raw[:limit]:
            if not isinstance(p, dict):
                continue
            try:
                pts.append({"x": _clamp(float(p.get("x")), 0, 1),
                            "y": _clamp(float(p.get("y")), 0, 1)})
            except (TypeError, ValueError):
                continue
    return pts


SHAPES = ("linear", "radial", "rect", "brush", "pen")
OPS = ("add", "subtract", "intersect")
CROP_AREA_LIMIT = 0.55  # 蒙版包围盒占画面比例低于此值时，只在该区域做局部调色


def parse_node(raw, index=0):
    """解析组合树中的一个原始选区节点"""
    if not isinstance(raw, dict):
        raw = {}
    shape = raw.get("shape")
    if shape not in SHAPES:
        shape = "radial"
    op = raw.get("op")
    if op not in OPS:
        op = "add"
    strokes = []
    raw_strokes = raw.get("strokes")
    if isinstance(raw_strokes, list):
        for s in raw_strokes[:64]:
            pts = _parse_points(s, 2000)
            if pts:
                strokes.append(pts)
    return {
        "id": str(raw.get("id") or "n%d" % (index + 1))[:24],
        "name": str(raw.get("name") or "选区 %d" % (index + 1))[:40],
        "op": op,
        "enabled": raw.get("enabled", True) is not False,
        "shape": shape,
        "cx": _clamp(float(raw.get("cx", 0.5) or 0), 0, 1),
        "cy": _clamp(float(raw.get("cy", 0.5) or 0), 0, 1),
        "angle": float(raw.get("angle", 0) or 0),
        "size": _clamp(float(raw.get("size", 0.35) or 0), 0.02, 2.0),
        "aspect": _clamp(float(raw.get("aspect", 0.6) or 0), 0.05, 3.0),
        "feather": _clamp(float(raw.get("feather", 0.25) or 0), 0.01, 1.0),
        "invert": bool(raw.get("invert")),
        "brush_size": _clamp(float(raw.get("brush_size", 0.12) or 0), 0.01, 0.5),
        "strokes": strokes,
        "pen_points": _parse_points(raw.get("pen_points"), 256),
    }


def parse_mask(data):
    raw = data.get("mask") or {}
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except ValueError:
            raw = {}
    if not isinstance(raw, dict):
        raw = {}
    # 组合树：新数据带 nodes；旧数据以顶层形状作为唯一节点
    raw_nodes = raw.get("nodes")
    if isinstance(raw_nodes, list) and raw_nodes:
        nodes = [parse_node(n, i) for i, n in enumerate(raw_nodes[:16])]
        invert_all = bool(raw.get("invert"))
    else:
        nodes = [parse_node(raw, 0)]
        invert_all = False  # 旧数据的反转已挂在唯一节点上，避免二次反转
    mask = dict(nodes[0])  # 顶层保留首个节点几何，兼容旧调用
    mask.update({
        "enabled": bool(raw.get("enabled")),
        "invert": invert_all,
        "nodes": nodes,
    })
    return mask


def _box_blur(a, radius, axis):
    """沿单个轴做 box 模糊（累计和实现，零填充边缘）"""
    if radius < 1:
        return a
    pad = [(radius, radius) if i == axis else (0, 0) for i in range(a.ndim)]
    p = np.pad(a, pad, mode="edge")
    c = np.cumsum(p, axis=axis, dtype=np.float32)
    zero_shape = list(c.shape)
    zero_shape[axis] = 1
    c = np.concatenate([np.zeros(zero_shape, dtype=np.float32), c], axis=axis)
    n = 2 * radius + 1
    hi = np.take(c, np.arange(n, c.shape[axis]), axis=axis)
    lo = np.take(c, np.arange(0, c.shape[axis] - n), axis=axis)
    return (hi - lo) / n


def _blur2d(a, radius, passes=3):
    for _ in range(passes):
        a = _box_blur(a, radius, 1)
        a = _box_blur(a, radius, 0)
    return a


def _fill_polygon(pts, w, h):
    """扫描线填充多边形（pts 为像素坐标）"""
    out = np.zeros((h, w), dtype=np.float32)
    n = len(pts)
    for y in range(h):
        yc = y + 0.5
        xs = []
        for i in range(n):
            x1, y1 = pts[i]
            x2, y2 = pts[(i + 1) % n]
            if (y1 <= yc < y2) or (y2 <= yc < y1):
                xs.append(x1 + (x2 - x1) * (yc - y1) / (y2 - y1))
        if len(xs) < 2:
            continue
        xs.sort()
        for a, b in zip(xs[0::2], xs[1::2]):
            ia = max(0, int(math.ceil(a - 0.5)))
            ib = min(w, int(math.ceil(b - 0.5)))
            if ia < ib:
                out[y, ia:ib] = 1.0
    return out


def _drawn_mask_array(m, w, h):
    """画笔 / 钢笔蒙版 → 灰度数组（0~1）"""
    if np is None:
        raise RuntimeError("画笔 / 钢笔蒙版需要 numpy，请先执行 pip install numpy")
    mask = np.zeros((h, w), dtype=np.float32)
    if m["shape"] == "brush":
        radius = max(1.0, m["brush_size"] * min(w, h))
        inner = radius * (1.0 - _clamp(m["feather"], 0.0, 1.0) * 0.95)
        falloff = max(1.0, radius - inner)
        gap = max(1.0, radius * 0.25)
        for stroke in m["strokes"]:
            pts = [(p["x"] * w, p["y"] * h) for p in stroke]
            if not pts:
                continue
            if len(pts) == 1:
                pts = pts * 2
            stamps = []
            for (x1, y1), (x2, y2) in zip(pts, pts[1:]):
                dist = math.hypot(x2 - x1, y2 - y1)
                steps = max(1, int(dist / gap))
                for i in range(steps + 1):
                    t = i / float(steps)
                    stamps.append((x1 + (x2 - x1) * t, y1 + (y2 - y1) * t))
            for sx, sy in stamps:
                x0 = max(0, int(sx - radius) - 1)
                x1 = min(w, int(sx + radius) + 2)
                y0 = max(0, int(sy - radius) - 1)
                y1 = min(h, int(sy + radius) + 2)
                if x0 >= x1 or y0 >= y1:
                    continue
                yy = np.arange(y0, y1, dtype=np.float32)[:, None]
                xx = np.arange(x0, x1, dtype=np.float32)[None, :]
                d = np.sqrt((xx - sx) ** 2 + (yy - sy) ** 2)
                a = np.clip((radius - d) / falloff, 0.0, 1.0)
                region = mask[y0:y1, x0:x1]
                np.maximum(region, a, out=region)
    else:  # pen
        pts = [(p["x"] * w, p["y"] * h) for p in m["pen_points"]]
        if len(pts) >= 3:
            mask = _fill_polygon(pts, w, h)
            r = int(round(m["feather"] * min(w, h) * 0.25))
            if r >= 1:
                mask = _blur2d(mask, r)
    return mask


def _geom_mask_array(node, w, h):
    """单个几何节点 → 灰度数组（0~1），与旧 geq 表达式语义一致"""
    if node["shape"] in ("brush", "pen"):
        return _drawn_mask_array(node, w, h)
    x = (np.arange(w, dtype=np.float32) + 0.5) / max(1, w)
    y = (np.arange(h, dtype=np.float32) + 0.5) / max(1, h)
    dx = x[None, :] - node["cx"]
    dy = y[:, None] - node["cy"]
    size, feather = node["size"], node["feather"]
    if node["shape"] == "linear":
        a = math.radians(node["angle"])
        v = 0.5 + (dx * math.cos(a) + dy * math.sin(a)) / size
    elif node["shape"] == "radial":
        ratio = (h / w) if w else 1.0
        v = (size - np.sqrt(dx * dx + (dy * ratio) ** 2)) / feather
    else:  # rect：高宽比按画面像素计算，并支持旋转（画面上是真实的角度）
        ratio = (h / w) if w else 1.0
        a = math.radians(node["angle"])
        ca, sa = math.cos(a), math.sin(a)
        ux = dx * ca + dy * ratio * sa
        uy = dy * ratio * ca - dx * sa
        v = (1.0 - np.maximum(np.abs(ux) / size, np.abs(uy) / (size * node["aspect"]))) / feather
    return np.clip(v, 0.0, 1.0).astype(np.float32)


def _nodes_mask_array(mask, w, h):
    """按组合树求值：添加=并集、减去=差集、交叉=交集，最后应用蒙版级反转"""
    acc = None
    for node in mask.get("nodes") or []:
        if not node.get("enabled", True):
            continue
        a = _geom_mask_array(node, w, h)
        if node.get("invert"):
            a = 1.0 - a
        if acc is None:
            acc = a
        elif node["op"] == "subtract":
            acc = acc * (1.0 - a)
        elif node["op"] == "intersect":
            acc = acc * a
        else:
            acc = np.maximum(acc, a)
    if acc is None:
        acc = np.zeros((h, w), dtype=np.float32)
    if mask.get("invert"):
        acc = 1.0 - acc
    return acc.astype(np.float32)


def _write_pgm(path, arr):
    """灰度数组 → PGM（ffmpeg 可直接作为图片输入读取）"""
    h, w = arr.shape
    data = (np.clip(arr, 0.0, 1.0) * 255.0).astype(np.uint8)
    with open(path, "wb") as f:
        f.write(b"P5\n%d %d\n255\n" % (w, h))
        f.write(data.tobytes())


def ensure_mask_png(m, w, h):
    """按组合树生成灰度蒙版图（PGM）并缓存；节点运算结果即为最终选区"""
    if np is None:
        raise RuntimeError("蒙版需要 numpy，请先执行 pip install numpy")
    geo = {"nodes": m.get("nodes"), "invert": bool(m.get("invert"))}
    out = os.path.join(MASK_CACHE_DIR,
                       _cache_key("mask", json.dumps(geo, sort_keys=True), w, h) + ".pgm")
    if os.path.isfile(out):
        return out
    arr = _nodes_mask_array(m, w, h)
    tmp = out + ".tmp"
    _write_pgm(tmp, arr)
    os.replace(tmp, out)
    return out


def mask_bbox(pgm_path):
    """蒙版有效像素包围盒 → (x, y, w, h, 面积占比)

    逐个蒙版做整帧调色的开销最大；知道蒙版只覆盖画面一小块时，
    只对这块区域跑调色滤镜，再把结果叠回原位，结果完全一致但快很多。
    包围盒结果写在 PGM 旁边的 .json 里，避免每次重新扫描大图。
    """
    side = pgm_path + ".bbox2.json"
    try:
        with open(side, "r", encoding="utf-8") as f:
            data = json.load(f)
        box = data["box"]
        return (tuple(box) if box else None), float(data["area"])
    except (OSError, ValueError, TypeError, KeyError):
        pass
    if np is None:
        return None, 1.0
    box, area = None, 1.0
    try:
        with open(pgm_path, "rb") as f:
            f.read(2)
            f.readline()
            w, h = [int(v) for v in f.readline().split()[:2]]
            f.readline()
            arr = np.frombuffer(f.read(), dtype=np.uint8).reshape(h, w)
    except Exception:
        return None, 1.0
    ys, xs = np.where(arr > 2)
    count = len(xs)  # 非有效像素视为透明，bbox 取有效像素外接矩形
    if count and count < w * h:
        pad = 2
        x0 = (max(0, int(xs.min()) - pad) // 2) * 2
        y0 = (max(0, int(ys.min()) - pad) // 2) * 2
        x1 = min(w, ((int(xs.max()) + 1 + pad + 1) // 2) * 2)
        y1 = min(h, ((int(ys.max()) + 1 + pad + 1) // 2) * 2)
        bw, bh = x1 - x0, y1 - y0
        # 宽高取偶数：部分滤镜（如 colortemperature）会在内部转成 4:2:0，奇数尺寸会丢一行
        bw -= bw % 2
        bh -= bh % 2
        if bw >= 2 and bh >= 2:
            box = [x0, y0, bw, bh]
            area = bw * bh / float(w * h)
    try:
        with open(side, "w", encoding="utf-8") as f:
            json.dump({"box": box, "area": area}, f)
    except OSError:
        pass
    return (tuple(box) if box else None), area


def ensure_mask_layers(layers, w, h):
    """为每层蒙版准备灰度图与包围盒（渲染用）"""
    for layer in layers:
        png = ensure_mask_png(layer["mask"], w, h)
        layer["png"] = png
        layer["bbox"], layer["bbox_area"] = mask_bbox(png)


def parse_masks(data):
    """解析多蒙版列表；每个蒙版带自己的完整调色参数"""
    raw = data.get("masks")
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except ValueError:
            raw = []
    items = raw if isinstance(raw, list) else []
    if not items:
        single = data.get("mask")  # 兼容旧的单蒙版调用
        if single:
            items = [single]
    out = []
    for i, m in enumerate(items[:16]):
        if isinstance(m, str):
            try:
                m = json.loads(m)
            except ValueError:
                continue
        if not isinstance(m, dict):
            continue
        mask = parse_mask({"mask": m})
        mask["grading"] = parse_grading({"grading": m.get("grading")})
        mask["name"] = str(m.get("name") or "蒙版 %d" % (i + 1))[:40]
        out.append(mask)
    return out


def active_masks(masks):
    """真正需要参与渲染的蒙版：已启用且调色参数非中性"""
    return [m for m in (masks or [])
            if m["enabled"] and not is_neutral_grading(m["grading"])]


def prepare_adjustments(data):
    """统一解析调色 / 蒙版，返回 (grading, masks)"""
    return parse_grading(data), parse_masks(data)


def ensure_base_frame(video, seek, size):
    """解码指定时间点的单帧并缩放成 PNG 缓存；调参时直接复用，省掉重复解码原片的开销"""
    key = _cache_key('base', video, _file_mtime(video), round(seek, 2), size)
    out = os.path.join(BASE_CACHE_DIR, key + ".png")
    if os.path.isfile(out):
        return out
    tmp = out + ".part.png"
    cmd = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
           "-ss", f"{seek:.2f}", "-i", video, "-frames:v", "1",
           "-vf", f"scale={size[0]}:{size[1]}:flags=lanczos",
           "-pix_fmt", "rgb24", tmp]
    with gen_sem:
        try:
            r = subprocess.run(cmd, capture_output=True, text=True,
                               encoding='utf-8', errors='replace', timeout=90)
        except subprocess.TimeoutExpired:
            raise RuntimeError("解码原片超时")
    if r.returncode != 0 or not os.path.isfile(tmp):
        raise RuntimeError("\n".join((r.stderr or '').strip().splitlines()[-3:])[-300:])
    os.replace(tmp, out)
    return out


@app.route('/api/pick_dir', methods=['POST'])
def pick_dir():
    """弹出系统选择框（本工具为本地单机应用，选择框由服务端所在的桌面弹出）

    mode=file：文件选择框，框内直接列出视频文件；返回所选文件所在目录
    mode=dir ：文件夹选择框
    """
    data = request.get_json(force=True, silent=True) or {}
    title = str(data.get('title') or '选择文件夹')
    initial = str(data.get('initial') or '').strip().strip('"')
    mode = str(data.get('mode') or '').strip().lower()
    if not os.path.isdir(initial):
        initial = BASE_DIR
    if mode == 'file':
        script = (
            "import tkinter as tk\n"
            "from tkinter import filedialog\n"
            "root = tk.Tk()\n"
            "root.withdraw()\n"
            "root.attributes('-topmost', True)\n"
            "root.update()\n"
            "p = filedialog.askopenfilename(parent=root, title=%r, initialdir=%r, "
            "filetypes=[('视频文件', '*.mp4 *.mov *.mkv *.avi *.mxf *.webm'), ('所有文件', '*.*')])\n"
            "print(p or '')\n" % (title, initial)
        )
    else:
        script = (
            "import tkinter as tk\n"
            "from tkinter import filedialog\n"
            "root = tk.Tk()\n"
            "root.withdraw()\n"
            "root.attributes('-topmost', True)\n"
            "root.update()\n"
            "p = filedialog.askdirectory(parent=root, title=%r, initialdir=%r)\n"
            "print(p or '')\n" % (title, initial)
        )
    try:
        r = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True,
                           encoding='utf-8', errors='replace', timeout=600)
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    lines = [l for l in (r.stdout or '').splitlines() if l.strip()]
    path = lines[-1].strip() if lines else ''
    if path and mode == 'file':
        path = os.path.dirname(path)
    return jsonify({"path": path})


@app.route('/api/thumb')
def thumb():
    """生成带 LUT（可含强度/二级 LUT）的单帧缩略图，用于滤镜卡片实时预览"""
    video = request.args.get('path', '').strip().strip('"')
    if not os.path.isfile(video):
        return jsonify({"error": "文件不存在"}), 404
    lut = request.args.get('lut', '').strip().strip('"')
    lut2 = request.args.get('lut2', '').strip().strip('"')
    first = str(request.args.get('first') or '').lower() in ('1', 'true', 'yes')
    s1 = max(0, min(100, int(request.args.get('strength', 100))))
    s2 = max(0, min(100, int(request.args.get('strength2', 100))))
    w = max(160, min(720, int(request.args.get('w', 320))))
    if lut and not os.path.isfile(lut):
        return jsonify({"error": "LUT 不存在"}), 404
    if lut2 and not os.path.isfile(lut2):
        return jsonify({"error": "第二个 LUT 不存在"}), 404

    grading, masks = prepare_adjustments({
        "grading": request.args.get('grading'),
        "masks": request.args.get('masks'),
        "mask": request.args.get('mask')})
    info = probe_video(video)
    size = None
    if info["width"] and info["height"]:
        size = (w, max(2, int(round(info["height"] * w / float(info["width"]) / 2)) * 2))
    layers = mask_render_list(masks) if size else []
    try:
        if layers:
            ensure_mask_layers(layers, size[0], size[1])
    except RuntimeError as e:
        return jsonify({"error": str(e)}), 500

    key = _cache_key('thumb', video, _file_mtime(video), lut, _file_mtime(lut),
                     lut2, _file_mtime(lut2), s1, s2, w, size, first,
                     json.dumps(grading, sort_keys=True),
                     json.dumps(masks, sort_keys=True) if layers else '')
    out = os.path.join(THUMB_CACHE_DIR, key + ".jpg")
    if not os.path.isfile(out):
        stages = []
        if lut:
            stages.append((lut, s1))
        if lut2:
            stages.append((lut2, s2))
        graph = build_filter_graph(stages, 'gbrp', 'yuvj420p',
                                   size=size, grading=grading, mask_layers=layers)
        seek = 0.0
        if size:
            dur = info["duration"] or 0
            # first=1 时取第一帧，用于素材列表的封面
            seek = 0.0 if first else (min(3.0, dur * 0.3) if dur > 2 else 0.0)
            try:
                # 先取一张缓存好的原片帧，后续调参只需要重跑滤镜，不用再解码视频
                src = ensure_base_frame(video, seek, size)
            except RuntimeError as e:
                return jsonify({"error": "缩略图生成失败：" + str(e)}), 500
            cmd = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", src]
        else:
            cmd = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
                   "-ss", "0.00", "-i", video]
        for layer in layers:
            # 蒙版为静态图，限制读取时长，避免源画面无帧时无限循环
            cmd += ["-loop", "1", "-framerate", "1", "-t", f"{seek + 5:.1f}", "-i", layer["png"]]
        cmd += ["-filter_complex", graph, "-map", "[vo]",
                "-frames:v", "1", "-q:v", "4", out]
        with gen_sem:
            try:
                r = subprocess.run(cmd, capture_output=True, text=True,
                                   encoding='utf-8', errors='replace', timeout=90)
            except subprocess.TimeoutExpired:
                return jsonify({"error": "缩略图生成超时（90 秒）"}), 500
        if r.returncode != 0 or not os.path.isfile(out):
            tail = "\n".join((r.stderr or '').strip().splitlines()[-5:])
            return jsonify({"error": "缩略图生成失败：" + tail[-400:]}), 500
    return send_file(out, mimetype='image/jpeg', conditional=True)


@app.route('/api/preview_graded', methods=['POST'])
def preview_graded():
    """生成一段 8 秒的调色预览片段（含强度/双 LUT）。

    quality=high：540p/30fps，用于正式预览；
    quality=low：360p/24fps，用于播放时的快速低画质预览（可被前端预渲染缓存）。
    """
    data = request.get_json(force=True)
    video = (data.get('path') or '').strip().strip('"')
    if not os.path.isfile(video):
        return jsonify({"error": "文件不存在"}), 404
    lut = (data.get('lut_path') or '').strip().strip('"')
    lut2 = (data.get('lut_path2') or '').strip().strip('"')
    s1 = max(0, min(100, int(data.get('lut_strength', 100))))
    s2 = max(0, min(100, int(data.get('lut_strength2', 100))))
    if lut and not os.path.isfile(lut):
        return jsonify({"error": "LUT 不存在"}), 404
    if lut2 and not os.path.isfile(lut2):
        return jsonify({"error": "第二个 LUT 不存在"}), 404
    quality = 'low' if str(data.get('quality') or '').lower() == 'low' else 'high'

    grading, masks = prepare_adjustments(data)
    info = probe_video(video)
    size = None
    fps_cap = 30
    if info["width"] and info["height"]:
        # 预览只用于屏幕上看效果（播放器区域约 700px 宽）：
        # 正式预览 540p；快速预览 360p + 24fps，耗时再降一半以上
        ph = min(360 if quality == 'low' else 540, info["height"])
        fps_cap = 24 if quality == 'low' else 30
        size = (max(2, int(round(info["width"] * ph / float(info["height"]) / 2)) * 2), ph)
    layers = mask_render_list(masks) if size else []
    try:
        if layers:
            ensure_mask_layers(layers, size[0], size[1])
    except RuntimeError as e:
        return jsonify({"error": str(e)}), 500
    key = _cache_key('graded', video, _file_mtime(video), lut, _file_mtime(lut),
                     lut2, _file_mtime(lut2), s1, s2, size, fps_cap,
                     json.dumps(grading, sort_keys=True),
                     json.dumps(masks, sort_keys=True) if layers else '')
    out = os.path.join(PREVIEW_CACHE_DIR, key + ".mp4")
    if not os.path.isfile(out):
        stages = []
        if lut:
            stages.append((lut, s1))
        if lut2:
            stages.append((lut2, s2))
        graph = build_filter_graph(stages, 'gbrp', 'yuv420p',
                                   size=size, grading=grading, mask_layers=layers,
                                   scale_flags='bilinear', fps_cap=fps_cap)
        mask_inputs = []
        for layer in layers:
            # 预览最长 8 秒，蒙版读取上限 20 秒即可，避免源无帧时死循环
            mask_inputs += ["-loop", "1", "-framerate", str(info["fps"]), "-t", "20",
                            "-i", layer["png"]]
        body = ["-t", "8",
                "-filter_complex", graph, "-map", "[vo]", "-map", "0:a?", "-g", "15",
                "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "96k",
                "-movflags", "+faststart", out]
        # 4K / 高帧率素材单靠 CPU 解码就要十几秒，用 NVDEC 硬解能省掉大半；
        # 1080p 及以下解码本身就快，硬解的显存拷贝反而拖慢，因此按像素率判断
        heavy = _pixel_rate(info) >= 2.0e8

        def run_preview(mode):
            cmd = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error"]
            if mode == 'hw':
                cmd += ["-hwaccel", "cuda"]
            cmd += ["-i", video] + mask_inputs
            if mode in ('hw', 'gpu'):
                # 编码交由显卡（NVENC）；滤镜仍走 CPU，避免帧回读带来的额外开销
                preset, cq = ('p1', '30') if quality == 'low' else ('p2', '23')
                cmd += ["-c:v", "h264_nvenc", "-preset", preset, "-tune", "hq",
                        "-rc", "vbr", "-cq", cq, "-b:v", "0"]
            else:
                if quality == 'low':
                    cmd += ["-c:v", "libx264", "-preset", "ultrafast", "-crf", "32"]
                else:
                    cmd += ["-c:v", "libx264", "-preset", "ultrafast", "-crf", "28"]
            return subprocess.run(cmd + body, capture_output=True, text=True,
                                  encoding='utf-8', errors='replace', timeout=300)

        global PREVIEW_GPU_OK, PREVIEW_HW_OK
        # 用户在主界面选择的渲染方式：GPU（硬解+NVENC）或纯 CPU；
        # 选 GPU 但驱动不可用时仍会回退 CPU，保证没有显卡的设备也能正常预览
        want_gpu = bool(data.get('render_gpu', True))
        modes = []
        if want_gpu and PREVIEW_GPU_OK:
            if heavy and PREVIEW_HW_OK is not False:
                modes.append('hw')
            modes.append('gpu')
        modes.append('cpu')
        with gen_sem:
            r = None
            for mode in modes:
                try:
                    r = run_preview(mode)
                except subprocess.TimeoutExpired:
                    return jsonify({"error": "调色预览生成超时（300 秒）"}), 500
                if r.returncode == 0 and os.path.isfile(out):
                    break
                # 记录失效的路径，避免每次预览都重复踩同一个坑
                if mode == 'hw':
                    PREVIEW_HW_OK = False
                elif mode == 'gpu':
                    PREVIEW_GPU_OK = False
                if os.path.exists(out):
                    os.remove(out)
        if r.returncode != 0 or not os.path.isfile(out):
            tail = "\n".join((r.stderr or '').strip().splitlines()[-5:])
            return jsonify({"error": "调色预览生成失败：" + tail[-400:]}), 500
    return jsonify({"url": "/api/preview_file?path=" + out})


# === 转换任务 ===

@app.route('/api/convert', methods=['POST'])
def convert():
    data = request.get_json(force=True)
    files = data.get('files', [])
    lut_path = data.get('lut_path', '').strip().strip('"')
    lut_path2 = data.get('lut_path2', '').strip().strip('"')
    lut_strength = max(0, min(100, int(data.get('lut_strength', 100))))
    lut_strength2 = max(0, min(100, int(data.get('lut_strength2', 100))))
    output_mode = data.get('output_mode', 'subfolder')
    custom_dir = data.get('custom_dir', '').strip().strip('"')
    use_gpu = bool(data.get('use_gpu', True))
    quality = int(data.get('quality', 20))
    bit_depth = 10 if int(data.get('bit_depth', 8)) == 10 else 8
    resolution = data.get('resolution', 'original')
    if resolution not in ('original', '1080p', '720p'):
        resolution = 'original'

    if not files:
        return jsonify({"error": "未选择文件"}), 400
    if lut_path and not os.path.isfile(lut_path):
        return jsonify({"error": "LUT 文件不存在"}), 400
    if lut_path2 and not os.path.isfile(lut_path2):
        return jsonify({"error": "第二个 LUT 文件不存在"}), 400
    if output_mode == 'custom' and not custom_dir:
        return jsonify({"error": "请填写自定义输出目录"}), 400
    if use_gpu and not NVENC_OK:
        return jsonify({"error": f"GPU 编码不可用：{NVENC_MSG}。请改用 CPU 模式，或升级 NVIDIA 驱动后重启本服务。"}), 400

    grading, masks = prepare_adjustments(data)
    # 不套用 LUT 时，至少要有调色/蒙版调整，否则导出没有意义
    if not lut_path and not lut_path2 and is_neutral_grading(grading) and not active_masks(masks):
        return jsonify({"error": "未选择 LUT，且调色参数均为默认值，没有可导出的调整"}), 400

    stop_event.clear()  # 新任务开始前清除停止标志
    batch_id = uuid.uuid4().hex[:8]
    items = []
    for input_path in files:
        input_dir = os.path.dirname(input_path)
        filename = os.path.basename(input_path)
        if output_mode == 'prefix':
            output_path = os.path.join(input_dir, f"converted_{filename}")
        elif output_mode == 'custom':
            os.makedirs(custom_dir, exist_ok=True)
            output_path = os.path.join(custom_dir, filename)
        else:
            out_dir = os.path.join(input_dir, 'converted')
            os.makedirs(out_dir, exist_ok=True)
            output_path = os.path.join(out_dir, filename)
        item = {
            "name": filename,
            "input": input_path,
            "output": output_path,
            "status": "pending",
            "progress": 0,
            "error": None,
        }
        # 输出与输入同路径时 ffmpeg 会因文件占用报 Permission denied
        if os.path.abspath(output_path) == os.path.abspath(input_path):
            item["status"] = "error"
            item["error"] = "输出路径与输入文件相同。请改用前缀/子目录模式，或选择其他输出目录。"
        items.append(item)

    with batches_lock:
        batches[batch_id] = {"id": batch_id, "items": items, "status": "running"}

    threading.Thread(target=run_batch,
                     args=(batch_id, lut_path, use_gpu, quality, bit_depth,
                           lut_path2, lut_strength, lut_strength2, resolution,
                           grading, masks),
                     daemon=True).start()
    return jsonify({"batch_id": batch_id})


@app.route('/api/batches')
def list_batches():
    with batches_lock:
        return jsonify({"batches": list(batches.values())})


@app.route('/api/stop_all', methods=['POST'])
def stop_all():
    """停止全部转换：终止当前 ffmpeg 进程，队列中剩余文件标记为已取消"""
    stop_event.set()
    with procs_lock:
        procs = list(current_procs.values())
    for p in procs:
        try:
            p.kill()
        except Exception:
            pass
    return jsonify({"ok": True})


@app.route('/api/write_test')
def write_test():
    """诊断：测试 server 进程自身对指定路径的写权限"""
    path = request.args.get('path', '')
    if not path:
        return jsonify({"error": "缺少 path 参数"}), 400
    try:
        with open(path, 'wb') as f:
            f.write(b'ok')
        os.remove(path)
        return jsonify({"ok": True, "msg": f"server 进程可写: {path}"})
    except Exception as e:
        return jsonify({"ok": False, "error": f"{type(e).__name__}: {e}"})


def run_batch(batch_id, lut_path, use_gpu, quality, bit_depth,
              lut_path2='', lut_strength=100, lut_strength2=100, resolution='original',
              grading=None, masks=None):
    batch = batches[batch_id]
    for item in batch['items']:
        if stop_event.is_set():
            if item['status'] == 'pending':
                item['status'] = 'cancelled'
            continue
        if item['status'] != 'pending':
            continue
        if os.path.exists(item['output']):
            item['status'] = 'skipped'
            item['progress'] = 100
            continue
        # 防止与其他并发任务写同一输出文件
        with active_lock:
            if item['output'] in active_outputs:
                item['status'] = 'error'
                item['error'] = "该文件正在另一个转换任务中处理，请勿重复提交。"
                continue
            active_outputs.add(item['output'])
        try:
            item['status'] = 'converting'
            # Permission denied 多为临时文件锁定（如残留的 ffmpeg 进程、播放器占用），自动重试
            last_err = None
            for attempt in range(3):
                try:
                    convert_one(item, lut_path, use_gpu, quality, bit_depth,
                                lut_path2, lut_strength, lut_strength2, resolution,
                                grading, masks)
                    last_err = None
                    break
                except InterruptedError:
                    raise
                except Exception as e:
                    last_err = e
                    if "Permission denied" in str(e) and attempt < 2:
                        if stop_event.wait(3):  # 等待期间可被停止指令打断
                            raise InterruptedError("用户停止了转换")
                        continue
                    raise
            if last_err:
                raise last_err
            item['status'] = 'done'
            item['progress'] = 100
        except InterruptedError:
            item['status'] = 'cancelled'
            # 删除中断产生的半成品文件（无 moov 无法播放，且避免下次被“已存在”跳过）
            try:
                os.remove(item['output'])
            except OSError:
                pass
        except Exception as e:
            item['status'] = 'error'
            item['error'] = str(e)
            # 删除失败留下的残缺文件（如 0 字节文件），避免下次被误判为已转换
            try:
                os.remove(item['output'])
            except OSError:
                pass
        finally:
            with active_lock:
                active_outputs.discard(item['output'])
    batch['status'] = 'stopped' if stop_event.is_set() else 'done'


def _even(v):
    return max(2, v - v % 2)


def target_size(width, height, resolution='original'):
    """按导出分辨率换算目标宽高（保持比例，宽度取偶数）；无需缩放时返回 None"""
    if not width or not height:
        return None
    if resolution in ('1080p', '720p'):
        h = 1080 if resolution == '1080p' else 720
        if height > h:
            return (max(2, int(round(width * h / float(height) / 2)) * 2), h)
    if width % 2 == 0 and height % 2 == 0:
        return None
    return (_even(width), _even(height))


def mask_render_list(masks):
    """把蒙版解析成可渲染层：过滤掉禁用 / 中性参数的蒙版，并生成各自的调色滤镜"""
    layers = []
    for m in active_masks(masks):
        pre, _ = grading_steps(m["grading"], sharpen=False)
        if pre:
            layers.append({"mask": m, "filters": pre})
    return layers


def build_filter_graph(stages, fmt_in, fmt_out, size=None, grading=None, mask_layers=None,
                       scale_flags='lanczos', fps_cap=None):
    """构建滤镜图：缩放 → 格式 → 全局调色/多级 LUT → 逐个蒙版叠加局部调色 → 输出格式。

    stages: [(LUT 路径, 强度)]，强度 0 跳过、100 全量、中间值用 blend 插值
    size: (宽, 高)；先缩放再转平面 RGB，避免在原始分辨率上做整帧格式转换
    grading: parse_grading() 结果
    mask_layers: mask_render_list() 结果，每层的蒙版图按顺序作为输入 1..N
    fps_cap: 最高输出帧率；预览用 30 帧，减少高帧率素材的滤镜计算量
    """
    pre, post = grading_steps(grading)
    layers = mask_layers or []
    parts = []
    counter = [0]

    def emit(ins, filt):
        counter[0] += 1
        label = f'v{counter[0]}'
        parts.append(f'{ins}{filt}[{label}]')
        return label

    def apply_luts(start):
        cur = start
        for lut_path, strength in stages:
            if not lut_path or strength <= 0:
                continue
            path = to_ffmpeg_lut_path(lut_path)
            if strength >= 100:
                cur = emit(f'[{cur}]', f'lut3d={path}')
            else:
                # split 出原始画面，与套用 LUT 后的结果按透明度混合，实现强度调节
                counter[0] += 1
                tag = counter[0]
                parts.append(f'[{cur}]split=2[b{tag}][g{tag}]')
                parts.append(f'[g{tag}]lut3d={path}[s{tag}]')
                cur = emit(f'[b{tag}][s{tag}]',
                           f'blend=all_mode=normal:all_opacity={strength / 100.0:.3f}')
        return cur

    head = [f'fps={fps_cap}'] if fps_cap else []
    if size:
        base = emit('[0:v]', ','.join(head + [f'scale={size[0]}:{size[1]}:flags={scale_flags}']))
        base = emit(f'[{base}]', f'format={fmt_in}')
    else:
        base = emit('[0:v]', ','.join(head + [f'format={fmt_in}']))

    cur = base
    for f in pre:
        cur = emit(f'[{cur}]', f)
    cur = apply_luts(cur)

    # 蒙版：每层拆出「当前画面」与「该蒙版调色后的画面」，用灰度蒙版作 alpha 叠加回去
    # 蒙版只覆盖一小块画面时，调色只在包围盒内做，再叠回原位：结果一致但计算量大幅下降
    mask_fmt = 'gray10le' if fmt_in.endswith('10le') else 'gray'
    for idx, layer in enumerate(layers, start=1):
        counter[0] += 1
        tag = counter[0]
        parts.append(f'[{cur}]split=2[base{tag}][grade{tag}]')
        box = layer.get("bbox")
        if box and layer.get("bbox_area", 1.0) <= CROP_AREA_LIMIT:
            x, y, bw, bh = box
            gc = emit(f'[grade{tag}]', f'crop={bw}:{bh}:{x}:{y}')
            for f in layer["filters"]:
                gc = emit(f'[{gc}]', f)
            parts.append(f'[{idx}:v]crop={bw}:{bh}:{x}:{y},format={mask_fmt}[mask{tag}]')
            merged = emit(f'[{gc}][mask{tag}]', 'alphamerge')
            cur = emit(f'[base{tag}][{merged}]', f'overlay=x={x}:y={y}:shortest=1')
            continue
        mc = f'grade{tag}'
        for f in layer["filters"]:
            mc = emit(f'[{mc}]', f)
        parts.append(f'[{idx}:v]format={mask_fmt}[mask{tag}]')
        merged = emit(f'[{mc}][mask{tag}]', 'alphamerge')
        cur = emit(f'[base{tag}][{merged}]', 'overlay=shortest=1')

    for f in post:
        cur = emit(f'[{cur}]', f)
    parts.append(f'[{cur}]format={fmt_out}[vo]')
    return ';'.join(parts)


def convert_one(item, lut_path, use_gpu, quality, bit_depth,
                lut_path2='', lut_strength=100, lut_strength2=100,
                resolution='original', grading=None, masks=None):
    input_path = item['input']
    output_path = item['output']
    fps = get_video_fps(input_path)
    duration = get_video_duration(input_path)
    info = probe_video(input_path)

    stages = [(lut_path, lut_strength)]
    if lut_path2:
        stages.append((lut_path2, lut_strength2))
    fmt_in = 'gbrp10le' if bit_depth == 10 else 'gbrp'
    fmt_out = 'yuv420p10le' if bit_depth == 10 else 'yuv420p'
    size = target_size(info["width"], info["height"], resolution)
    layers = mask_render_list(masks) if info["width"] and info["height"] else []
    if layers:
        mw, mh = size if size else (info["width"], info["height"])
        ensure_mask_layers(layers, mw, mh)
    filter_complex = build_filter_graph(stages, fmt_in, fmt_out,
                                        size=size, grading=grading, mask_layers=layers)
    pix_fmt = fmt_out

    cmd = [
        "ffmpeg", "-y",
        "-fflags", "+genpts",
        "-i", input_path,
    ]
    for layer in layers:
        # 蒙版为无限循环的静态图，按原片时长封顶，避免源无帧时无限编码
        cmd += ["-loop", "1", "-framerate", str(fps)]
        if duration:
            cmd += ["-t", f"{duration + 10:.1f}"]
        cmd += ["-i", layer["png"]]
    cmd += [
        "-filter_complex", filter_complex,
        "-map", "[vo]",
        "-map", "0:a?",  # 保留原音轨；无音轨时自动忽略
        "-r", str(fps),
        "-fps_mode", "cfr",
    ]
    if use_gpu:
        # 10bit 使用 HEVC（H.264 10bit 兼容性差）
        encoder = "hevc_nvenc" if bit_depth == 10 else "h264_nvenc"
        cmd += [
            "-c:v", encoder,
            "-preset", "p6",
            "-tune", "hq",
            "-rc", "vbr",
            "-cq", str(quality),
            "-b:v", "0",
            "-multipass", "fullres",
        ]
    elif bit_depth == 10:
        cmd += [
            "-c:v", "libx265",
            "-crf", str(quality),
            "-preset", "medium",
        ]
    else:
        cmd += [
            "-c:v", "libx264",
            "-crf", str(quality),
            "-preset", "medium",
        ]
    # 注意：不指定 -level，由编码器按分辨率/帧率自动选择（4K 需要 level 5.x）
    cmd += ["-pix_fmt", pix_fmt]
    if bit_depth == 10:
        cmd += ["-tag:v", "hvc1"]  # 提升 HEVC 在 QuickTime/苹果设备的兼容性
        if use_gpu:
            cmd += ["-profile:v", "main10"]
    else:
        cmd += ["-profile:v", "high"]
    cmd += [
        "-c:a", "copy",
        "-progress", "pipe:1",
        "-nostats",
        output_path,
    ]

    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            text=True, encoding='utf-8', errors='replace')

    # 单独线程收集 stderr，防止管道缓冲区写满造成死锁
    stderr_lines = []
    def read_stderr():
        for line in proc.stderr:
            stderr_lines.append(line)
    t = threading.Thread(target=read_stderr, daemon=True)
    t.start()

    with procs_lock:
        current_procs[item['input']] = proc
    try:
        for line in proc.stdout:
            line = line.strip()
            # FFmpeg 5.x+ 字段为 out_time_us，旧版为 out_time_ms，单位均为微秒
            if (line.startswith("out_time_us=") or line.startswith("out_time_ms=")) and duration:
                try:
                    us = int(line.split('=', 1)[1])
                    item['progress'] = min(99, round(us / 1e6 / duration * 100, 1))
                except ValueError:
                    pass
        proc.wait()
        t.join(timeout=2)
    finally:
        with procs_lock:
            current_procs.pop(item['input'], None)

    if stop_event.is_set():
        raise InterruptedError("用户停止了转换")

    if proc.returncode != 0:
        tail = "".join(stderr_lines[-12:]).strip()
        msg = tail[-800:] if tail else f"FFmpeg 退出码 {proc.returncode}"
        if "Permission denied" in msg:
            msg += ("\n\n排查建议：1) 输出目录不要与源目录相同；2) 不要重复点击“开始转换”；"
                    "3) 若输出到桌面/文档等受保护目录，检查 Windows 安全中心 → 勒索软件防护 → "
                    "受控文件夹访问 是否拦截了 ffmpeg；4) 确认没有播放器正在占用同名输出文件。")
        raise RuntimeError(msg)


if __name__ == '__main__':
    download_dji_lut_if_needed()  # 启动时确保内置 LUT 存在
    print("检测 GPU 编码器 (NVENC)...")
    check_nvenc()
    if NVENC_OK:
        print("  NVENC 可用，可使用 GPU 加速。")
    else:
        print(f"  NVENC 不可用: {NVENC_MSG}")
        print("  可升级 NVIDIA 驱动至 610.00+，或使用 CPU 模式。")
    print("\n  Web UI 已启动: http://127.0.0.1:5000\n")
    app.run(host='127.0.0.1', port=5000, threaded=True)
