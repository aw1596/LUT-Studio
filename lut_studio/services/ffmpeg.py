"""FFmpeg / FFprobe 基础封装：编码器探测、媒体信息读取、音频参数。"""

import json
import subprocess

from .. import state
from ..utils import _file_mtime

# MP4 容器能直接封装的音频编码；DJI 等机型常见 PCM，直接 copy 会让 MP4 打不开
MP4_AUDIO_OK = {"aac", "mp3", "ac3", "eac3", "alac"}


def check_nvenc():
    """启动时检测 NVENC 是否可用（驱动过旧会失败），结果写入 state"""
    try:
        r = subprocess.run(
            ["ffmpeg", "-hide_banner", "-loglevel", "error",
             "-f", "lavfi", "-i", "testsrc=duration=0.1:size=640x360:rate=30",
             "-c:v", "h264_nvenc", "-f", "null", "-"],
            capture_output=True, text=True, timeout=30)
        if r.returncode == 0:
            state.NVENC_OK, state.NVENC_MSG = True, ""
        else:
            lines = [l for l in r.stderr.strip().splitlines() if l]
            state.NVENC_OK, state.NVENC_MSG = False, (lines[0] if lines else "NVENC 初始化失败")
    except Exception as e:
        state.NVENC_OK, state.NVENC_MSG = False, str(e)
    state.PREVIEW_GPU_OK = state.NVENC_OK


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


def get_audio_codec(path):
    """用 ffprobe 获取首条音轨编码；无音轨返回空串"""
    try:
        result = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "a:0",
             "-show_entries", "stream=codec_name",
             "-of", "default=noprint_wrappers=1:nokey=1", path],
            capture_output=True, text=True, check=True)
        return result.stdout.strip().lower()
    except Exception:
        return ""


def audio_out_args(src):
    """音频输出参数：能 copy 就 copy，PCM 等不兼容编码转 AAC"""
    codec = get_audio_codec(src)
    if not codec:
        return ["-an"]
    if codec in MP4_AUDIO_OK:
        return ["-c:a", "copy"]
    return ["-c:a", "aac", "-b:a", "256k", "-ac", "2"]


def probe_video(path):
    """一次 ffprobe 获取宽高/时长/帧率/编码，按路径 + 修改时间缓存"""
    key = (path, _file_mtime(path))
    with state._probe_lock:
        hit = state._probe_cache.get(key)
    if hit is not None:
        return hit
    info = {"width": 0, "height": 0, "duration": None, "fps": 30.0, "codec": "", "pix_fmt": ""}
    try:
        r = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "v:0",
             "-show_entries", "stream=width,height,avg_frame_rate,codec_name,pix_fmt",
             "-show_entries", "format=duration", "-of", "json", path],
            capture_output=True, text=True, encoding='utf-8', errors='replace')
        d = json.loads(r.stdout or "{}")
        st = (d.get("streams") or [{}])[0]
        info["width"] = int(st.get("width") or 0)
        info["height"] = int(st.get("height") or 0)
        info["codec"] = str(st.get("codec_name") or "").lower()
        info["pix_fmt"] = str(st.get("pix_fmt") or "").lower()
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
    with state._probe_lock:
        state._probe_cache[key] = info
    return info


def _pixel_rate(info):
    """素材的像素吞吐（宽 × 高 × 帧率），用于判断是否值得走硬件解码"""
    return (info.get("width") or 0) * (info.get("height") or 0) * (info.get("fps") or 0)
