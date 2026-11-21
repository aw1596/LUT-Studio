"""预览代理：给重素材（4K、HEVC、10-bit 等）做一份轻量 H.264 副本。

参考 openfilm 的 proxies：代理用硬解 + 硬编生成（不可用时回落 x264），
关键帧每 0.5 秒一个，+faststart，在后台单线程逐个生成；
播放、调色预览与缩略图优先读代理，导出始终用原片。
"""

import hashlib
import os
import subprocess
import threading

from .. import state
from ..config import PROXY_CACHE_DIR
from .ffmpeg import probe_video

PROXY_VERSION = 2  # 改变代理生成方式时递增，使旧缓存失效
PROXY_HEIGHT = 1080  # 代理短边像素（兼顾播放流畅与预览清晰度）
PROXY_LIGHT_CODECS = ('h264', 'vp8', 'vp9', 'av1')
PROXY_LIGHT_PIXFMTS = ('yuv420p', 'yuvj420p')
PROXY_PLAYABLE_EXTS = ('.mp4', '.mov', '.m4v', '.webm')


def is_heavy_video(info):
    """是否为播放/解码吃力的素材：超过 1080p，或不是 8-bit H.264/VP8/VP9/AV1 4:2:0"""
    w, h = int(info.get("width") or 0), int(info.get("height") or 0)
    if not (w > 0 and h > 0):
        return False
    return (max(w, h) > 1920 or min(w, h) > 1080
            or (info.get("codec") or '') not in PROXY_LIGHT_CODECS
            or (info.get("pix_fmt") or '') not in PROXY_LIGHT_PIXFMTS)


def needs_proxy(path):
    """是否需要代理：浏览器不能直接播的容器，或解码吃力的编码"""
    if os.path.splitext(path)[1].lower() not in PROXY_PLAYABLE_EXTS:
        return True
    return is_heavy_video(probe_video(path))


def proxy_size(w, h):
    """代理尺寸：短边缩到 PROXY_HEIGHT，保持长宽比且为偶数，不放大"""
    short = min(w, h)
    k = min(1.0, PROXY_HEIGHT / float(short)) if short else 1.0
    even = lambda n: max(2, int(round(n / 2.0)) * 2)
    return even(w * k), even(h * k)


def proxy_target(path):
    """代理缓存路径：按文件路径 + 大小 + 修改时间 + 版本命名，源文件一变就重新生成"""
    st = os.stat(path)
    raw = "|".join(str(x) for x in (PROXY_VERSION, os.path.abspath(path), st.st_size,
                                    int(st.st_mtime), PROXY_HEIGHT))
    return os.path.join(PROXY_CACHE_DIR, hashlib.md5(raw.encode('utf-8')).hexdigest() + ".mp4")


def ready_proxy(path):
    """已生成好的代理路径；素材轻量或代理未就绪时返回 None"""
    try:
        if not needs_proxy(path):
            return None
        out = proxy_target(path)
    except OSError:
        return None
    return out if os.path.isfile(out) else None


def proxy_state(path):
    """代理状态：None=无需代理，waiting / making / ready / failed"""
    try:
        if not needs_proxy(path):
            return None
        out = proxy_target(path)
    except OSError:
        return None
    if os.path.isfile(out):
        return "ready"
    with state._proxy_lock:
        job = state._proxy_jobs.get(out)
        return job["state"] if job else None


def ensure_proxy(path):
    """把重素材排进代理队列（已在队列或已就绪则跳过），返回当前状态"""
    try:
        if not needs_proxy(path):
            return None
        out = proxy_target(path)
    except OSError:
        return None
    if os.path.isfile(out):
        return "ready"
    with state._proxy_lock:
        job = state._proxy_jobs.get(out)
        if job is None:
            job = {"state": "waiting", "ratio": 0.0, "src": path, "error": None}
            state._proxy_jobs[out] = job
            state._proxy_queue.append(out)
        current = job["state"]
        start = not state._proxy_running and state._proxy_queue
        if start:
            state._proxy_running = True
    if start:
        threading.Thread(target=_proxy_drain, daemon=True).start()
    return current


def _proxy_drain():
    """后台单线程：一次生成一个代理，避免多个 4K 任务互相抢解码器"""
    while True:
        with state._proxy_lock:
            if not state._proxy_queue:
                state._proxy_running = False
                return
            out = state._proxy_queue.pop(0)
            job = state._proxy_jobs.get(out)
            if job is None:
                continue
            job["state"] = "making"
            job["ratio"] = 0.0
        try:
            _make_proxy(job["src"], out, job)
            job["state"] = "ready"
            job["ratio"] = 1.0
        except Exception as e:  # 生成失败时保留状态，前端回退原片
            job["state"] = "failed"
            job["error"] = str(e)[-300:]


def warm_proxies(paths):
    """后台预热素材代理：导入 / 扫描后立刻排队，用户点播放时通常已就绪"""
    def run():
        for path in paths:
            try:
                ensure_proxy(path)
            except Exception:
                pass
    threading.Thread(target=run, daemon=True).start()


def _proxy_attempts():
    """解码/编码组合，按优先级：硬解+硬编 → 软解+硬编 → 软解+软编"""

    def enc_hw():
        return ["-c:v", "h264_nvenc", "-preset", "p5", "-tune", "hq",
                "-rc", "vbr", "-cq", "20", "-b:v", "0"]

    def enc_sw():
        return ["-c:v", "libx264", "-preset", "veryfast", "-crf", "21"]

    attempts = []
    if state.NVENC_OK:
        if state._proxy_hw_decode:
            attempts.append((["-hwaccel", "cuda"], enc_hw()))  # NVDEC 解码 + NVENC 编码
        attempts.append(([], enc_hw()))
    else:
        # 没有 NVENC 时仍可尝试 D3D11 硬解，编码交给 x264
        if state._proxy_hw_decode:
            attempts.append((["-hwaccel", "d3d11va"], enc_sw()))
    attempts.append(([], enc_sw()))
    return attempts


def _make_proxy(src, out, job):
    """按尝试序列生成代理，进度写入 job["ratio"]"""
    info = probe_video(src)
    w, h = int(info.get("width") or 0), int(info.get("height") or 0)
    if not (w and h):
        raise RuntimeError("无法读取视频尺寸")
    size = proxy_size(w, h)
    fps = info.get("fps") or 30.0
    gop = max(1, int(round(fps * 0.5)))  # 每 0.5 秒一个关键帧，拖动进度条即时定位
    duration = info.get("duration") or 0
    os.makedirs(os.path.dirname(out), exist_ok=True)
    tmp = out + ".part.mp4"
    tail = ""
    for decode, encoder in _proxy_attempts():
        if os.path.exists(tmp):
            os.remove(tmp)
        cmd = (["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-nostdin"]
               + decode
               + ["-i", src, "-map", "0:v:0", "-map", "0:a?", "-sn", "-dn",
                  "-fps_mode", "passthrough",
                  "-vf", "scale=%d:%d:flags=lanczos" % size]
               + encoder
               + ["-g", str(gop), "-keyint_min", str(gop), "-pix_fmt", "yuv420p",
                  "-c:a", "aac", "-b:a", "96k", "-ac", "2",
                  "-movflags", "+faststart", "-progress", "pipe:1", "-nostats", tmp])
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                text=True, encoding='utf-8', errors='replace', bufsize=1)
        lines = []
        for line in proc.stdout:
            lines.append(line)
            if line.startswith("out_time_us=") and duration > 0:
                try:
                    job["ratio"] = max(0.0, min(0.99, int(line.split("=", 1)[1]) / 1e6 / duration))
                except ValueError:
                    pass
        proc.wait()
        if proc.returncode == 0 and os.path.isfile(tmp) and os.path.getsize(tmp) > 0:
            os.replace(tmp, out)
            return
        tail = "".join(lines[-6:]).strip()[-400:]
        if decode:
            state._proxy_hw_decode = False  # 硬件解码在这台机器上不可用，本进程不再尝试
    if os.path.exists(tmp):
        os.remove(tmp)
    raise RuntimeError(tail or "ffmpeg 生成代理失败")
