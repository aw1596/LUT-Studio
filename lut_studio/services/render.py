"""渲染相关：滤镜图构建、基底帧缓存、缩略图生成。"""

import json
import os
import subprocess

from helper import to_ffmpeg_lut_path

from .. import state
from ..config import BASE_CACHE_DIR, THUMB_CACHE_DIR
from ..utils import HttpError, _cache_key, _file_mtime
from .ffmpeg import probe_video
from .grading import grading_steps, parse_grading
from .mask import (CROP_AREA_LIMIT, active_masks, ensure_mask_layers,
                   parse_masks)
from .proxy import ready_proxy


def prepare_adjustments(data):
    """统一解析调色 / 蒙版，返回 (grading, masks)"""
    return parse_grading(data), parse_masks(data)


def mask_render_list(masks):
    """把蒙版解析成可渲染层：过滤掉禁用 / 中性参数的蒙版，并生成各自的调色滤镜"""
    layers = []
    for m in active_masks(masks):
        pre, _ = grading_steps(m["grading"], sharpen=False)
        if pre:
            layers.append({"mask": m, "filters": pre})
    return layers


def ensure_base_frame(video, seek, size):
    """解码指定时间点的单帧并缩放成 PNG 缓存；调参时直接复用，省掉重复解码原片的开销"""
    key = _cache_key('base', video, _file_mtime(video), round(seek, 2), size)
    out = os.path.join(BASE_CACHE_DIR, key + ".png")
    if os.path.isfile(out):
        return out
    # 重素材已有代理时从代理取帧，省掉 4K 解码
    src = ready_proxy(video) or video
    tmp = out + ".part.png"
    cmd = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
           "-ss", f"{seek:.2f}", "-i", src, "-frames:v", "1",
           "-vf", f"scale={size[0]}:{size[1]}:flags=lanczos",
           "-pix_fmt", "rgb24", tmp]
    with state.base_sem:
        try:
            r = subprocess.run(cmd, capture_output=True, text=True,
                               encoding='utf-8', errors='replace', timeout=90)
        except subprocess.TimeoutExpired:
            raise RuntimeError("解码原片超时")
    if r.returncode != 0 or not os.path.isfile(tmp):
        raise RuntimeError("\n".join((r.stderr or '').strip().splitlines()[-3:])[-300:])
    os.replace(tmp, out)
    return out


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


def render_thumb(video, lut, lut2, first, s1, s2, png, w, raw):
    """生成带 LUT（可含强度 / 二级 LUT）的单帧缩略图，返回 (文件路径, MIME)。

    raw: {'grading': ..., 'masks': ..., 'mask': ...}，来自查询参数原值
    """
    if not os.path.isfile(video):
        raise HttpError("文件不存在", 404)
    if lut and not os.path.isfile(lut):
        raise HttpError("LUT 不存在", 404)
    if lut2 and not os.path.isfile(lut2):
        raise HttpError("第二个 LUT 不存在", 404)

    grading, masks = prepare_adjustments(raw)
    info = probe_video(video)
    size = None
    if info["width"] and info["height"]:
        size = (w, max(2, int(round(info["height"] * w / float(info["width"]) / 2)) * 2))
    layers = mask_render_list(masks) if size else []
    try:
        if layers:
            ensure_mask_layers(layers, size[0], size[1])
    except RuntimeError as e:
        raise HttpError(str(e), 500)

    key = _cache_key('thumb', video, _file_mtime(video), lut, _file_mtime(lut),
                     lut2, _file_mtime(lut2), s1, s2, w, size, first,
                     'png' if png else 'jpg',
                     json.dumps(grading, sort_keys=True),
                     json.dumps(masks, sort_keys=True) if layers else '')
    out = os.path.join(THUMB_CACHE_DIR, key + (".png" if png else ".jpg"))
    if not os.path.isfile(out):
        stages = []
        if lut:
            stages.append((lut, s1))
        if lut2:
            stages.append((lut2, s2))
        graph = build_filter_graph(stages, 'gbrp', 'rgb24' if png else 'yuvj420p',
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
                raise HttpError("缩略图生成失败：" + str(e), 500)
            cmd = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", src]
        else:
            cmd = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
                   "-ss", "0.00", "-i", video]
        for layer in layers:
            # 蒙版为静态图，限制读取时长，避免源画面无帧时无限循环
            cmd += ["-loop", "1", "-framerate", "1", "-t", f"{seek + 5:.1f}", "-i", layer["png"]]
        cmd += ["-filter_complex", graph, "-map", "[vo]", "-frames:v", "1"]
        if png:
            cmd += ["-pix_fmt", "rgb24"]
        else:
            cmd += ["-q:v", "4"]
        cmd.append(out)
        with state.thumb_sem:
            try:
                r = subprocess.run(cmd, capture_output=True, text=True,
                                   encoding='utf-8', errors='replace', timeout=90)
            except subprocess.TimeoutExpired:
                raise HttpError("缩略图生成超时（90 秒）", 500)
        if r.returncode != 0 or not os.path.isfile(out):
            tail = "\n".join((r.stderr or '').strip().splitlines()[-5:])
            raise HttpError("缩略图生成失败：" + tail[-400:], 500)
    return out, ('image/png' if png else 'image/jpeg')
