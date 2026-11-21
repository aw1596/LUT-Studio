"""LUT 模块：列表、上传、读取 .cube 原文。"""

import os
import shutil

from fastapi import APIRouter, File, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse

from ..config import CREATIVE_LUTS_DIR, LUTS_DIR
from ..services.lut import scan_all_luts

router = APIRouter()


@router.get('/api/luts')
def list_luts(request: Request):
    return JSONResponse({"luts": scan_all_luts()})


@router.post('/api/upload_lut')
def upload_lut(file: UploadFile = File(None)):
    f = file
    if not f or not (f.filename or '').lower().endswith('.cube'):
        return JSONResponse({"error": "仅支持 .cube 文件"}, status_code=400)
    # 上传的 LUT 归入个性化目录；官方还原 LUT 直接拷进 luts/restore/ 即可
    save_path = os.path.join(CREATIVE_LUTS_DIR, os.path.basename(f.filename))
    with open(save_path, 'wb') as dst:
        shutil.copyfileobj(f.file, dst)
    return JSONResponse({"ok": True, "path": save_path, "name": f.filename})


@router.get('/api/lut_file')
def lut_file(request: Request):
    """把 .cube 原文交给前端：浏览器端解析成 3D 纹理做实时套 LUT"""
    path = (request.query_params.get('path') or '').strip().strip('"')
    if not path.lower().endswith('.cube') or not os.path.isfile(path):
        return JSONResponse({"error": "LUT 不存在"}, status_code=404)
    root = os.path.realpath(LUTS_DIR).lower() + os.sep
    if not os.path.realpath(path).lower().startswith(root):
        return JSONResponse({"error": "仅允许读取 luts 目录内的文件"}, status_code=403)
    return FileResponse(path, media_type='text/plain')
