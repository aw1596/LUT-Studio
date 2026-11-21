"""调色模块：基底帧、调色预览片段。"""

import os

from fastapi import APIRouter, Body, Request
from fastapi.responses import FileResponse, JSONResponse

from ..services.ffmpeg import probe_video
from ..services.preview import preview_graded as render_preview
from ..services.render import ensure_base_frame
from ..utils import HttpError, _clamp

router = APIRouter()


@router.get('/api/base_frame')
def base_frame(request: Request):
    """返回不带 LUT / 调色的基底帧（PNG），供浏览器端 WebGL 实时套 LUT"""
    video = (request.query_params.get('path') or '').strip().strip('"')
    if not os.path.isfile(video):
        return JSONResponse({"error": "文件不存在"}, status_code=404)
    info = probe_video(video)
    if not (info["width"] and info["height"]):
        return JSONResponse({"error": "无法读取视频尺寸"}, status_code=400)
    try:
        w = int(request.query_params.get('w') or 1280)
        seek = float(request.query_params.get('seek') or 0)
    except ValueError:
        return JSONResponse({"error": "参数无效"}, status_code=400)
    w = _clamp(w, 320, 1920)
    h = max(2, int(round(info["height"] * w / float(info["width"]) / 2)) * 2)
    dur = info["duration"] or 0
    if dur > 0:
        seek = _clamp(seek, 0, max(0.0, dur - 0.05))
    try:
        png = ensure_base_frame(video, seek, (w, h))
    except RuntimeError as e:
        return JSONResponse({"error": "基底帧生成失败：" + str(e)}, status_code=500)
    return FileResponse(png, media_type='image/png')


@router.post('/api/preview_graded')
def preview_graded(data: dict = Body(...)):
    """生成一段 8 秒的调色预览片段（含强度 / 双 LUT）"""
    try:
        out = render_preview(data)
    except HttpError as e:
        return JSONResponse({"error": e.message}, status_code=e.status_code)
    return JSONResponse({"url": "/api/preview_file?path=" + out})
