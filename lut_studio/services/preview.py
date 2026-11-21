"""调色预览片段：生成一段 8 秒、带 LUT / 调色 / 蒙版的 MP4。"""

import json
import os
import subprocess

from .. import state
from ..config import PREVIEW_CACHE_DIR
from ..utils import HttpError, _cache_key, _file_mtime
from .ffmpeg import _pixel_rate, probe_video
from .mask import ensure_mask_layers
from .proxy import ensure_proxy, ready_proxy
from .render import build_filter_graph, mask_render_list, prepare_adjustments


def preview_graded(data):
    """生成调色预览片段，返回缓存文件路径。

    quality=high：720p/30fps，用于正式预览与播放调色预览；
    quality=low：540p/24fps，用于调参时的快速低画质预览（可被前端预渲染缓存）。
    """
    video = (data.get('path') or '').strip().strip('"')
    if not os.path.isfile(video):
        raise HttpError("文件不存在", 404)
    lut = (data.get('lut_path') or '').strip().strip('"')
    lut2 = (data.get('lut_path2') or '').strip().strip('"')
    s1 = max(0, min(100, int(data.get('lut_strength', 100))))
    s2 = max(0, min(100, int(data.get('lut_strength2', 100))))
    if lut and not os.path.isfile(lut):
        raise HttpError("LUT 不存在", 404)
    if lut2 and not os.path.isfile(lut2):
        raise HttpError("第二个 LUT 不存在", 404)
    quality = 'low' if str(data.get('quality') or '').lower() == 'low' else 'high'

    grading, masks = prepare_adjustments(data)
    info = probe_video(video)
    size = None
    fps_cap = 30
    if info["width"] and info["height"]:
        # 预览用于屏幕上看效果（播放器区域约 700–900px 宽）：
        # 正式预览 720p；快速预览 540p + 24fps，耗时再降一半以上
        ph = min(540 if quality == 'low' else 720, info["height"])
        fps_cap = 24 if quality == 'low' else 30
        size = (max(2, int(round(info["width"] * ph / float(info["height"]) / 2)) * 2), ph)
    layers = mask_render_list(masks) if size else []
    try:
        if layers:
            ensure_mask_layers(layers, size[0], size[1])
    except RuntimeError as e:
        raise HttpError(str(e), 500)
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
                                   scale_flags='lanczos', fps_cap=fps_cap)
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
        # 重素材优先用后台代理当渲染源；没有代理时顺手排队生成，本次仍用原片
        render_src = ready_proxy(video) or video
        if render_src == video:
            ensure_proxy(video)
        else:
            heavy = False  # 代理本身是 720p H.264，不需要再硬解

        def run_preview(mode):
            cmd = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error"]
            if mode == 'hw':
                cmd += ["-hwaccel", "cuda"]
            # 重素材已有代理时以代理为输入，4K 解码与缩放的开销都省掉
            cmd += ["-i", render_src] + mask_inputs
            if mode in ('hw', 'gpu'):
                # 编码交由显卡（NVENC）；滤镜仍走 CPU，避免帧回读带来的额外开销
                preset, cq = ('p1', '28') if quality == 'low' else ('p4', '21')
                cmd += ["-c:v", "h264_nvenc", "-preset", preset, "-tune", "hq",
                        "-rc", "vbr", "-cq", cq, "-b:v", "0"]
            else:
                if quality == 'low':
                    cmd += ["-c:v", "libx264", "-preset", "ultrafast", "-crf", "28"]
                else:
                    cmd += ["-c:v", "libx264", "-preset", "veryfast", "-crf", "22"]
            return subprocess.run(cmd + body, capture_output=True, text=True,
                                  encoding='utf-8', errors='replace', timeout=300)

        # 用户在主界面选择的渲染方式：GPU（硬解+NVENC）或纯 CPU；
        # 选 GPU 但驱动不可用时仍会回退 CPU，保证没有显卡的设备也能正常预览
        want_gpu = bool(data.get('render_gpu', True))
        modes = []
        if want_gpu and state.PREVIEW_GPU_OK:
            if heavy and state.PREVIEW_HW_OK is not False:
                modes.append('hw')
            modes.append('gpu')
        modes.append('cpu')
        with state.gen_sem:
            r = None
            for mode in modes:
                try:
                    r = run_preview(mode)
                except subprocess.TimeoutExpired:
                    raise HttpError("调色预览生成超时（300 秒）", 500)
                if r.returncode == 0 and os.path.isfile(out):
                    break
                # 记录失效的路径，避免每次预览都重复踩同一个坑
                if mode == 'hw':
                    state.PREVIEW_HW_OK = False
                elif mode == 'gpu':
                    state.PREVIEW_GPU_OK = False
                if os.path.exists(out):
                    os.remove(out)
        if r.returncode != 0 or not os.path.isfile(out):
            tail = "\n".join((r.stderr or '').strip().splitlines()[-5:])
            raise HttpError("调色预览生成失败：" + tail[-400:], 500)
    return out
