"""素材模块：GPU 状态、视频列表、导入、预览流、代理、目录选择、缩略图。"""

import os
import shutil
import subprocess
import sys
import uuid

from fastapi import APIRouter, Body, File, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse

from .. import state
from ..config import BASE_DIR, IMPORT_DIR, VIDEO_EXTS
from ..services.ffmpeg import get_video_duration
from ..services.proxy import (ensure_proxy, needs_proxy, proxy_state,
                              proxy_target, warm_proxies)
from ..services.render import render_thumb
from ..utils import HttpError

router = APIRouter()


@router.get('/api/gpu_status')
def gpu_status(request: Request):
    return JSONResponse({"available": state.NVENC_OK, "message": state.NVENC_MSG})


@router.get('/api/list_videos')
def list_videos(request: Request):
    directory = request.query_params.get('dir', '').strip().strip('"')
    if not os.path.isdir(directory):
        return JSONResponse({"error": "目录不存在"}, status_code=400)
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
    warm_proxies([f["path"] for f in files])
    return JSONResponse({"files": files})


@router.post('/api/import_files')
def import_files(files: list[UploadFile] = File(...)):
    """拖拽 / 粘贴导入：浏览器只能拿到文件内容、拿不到原始路径，因此复制一份到 _imports/ 后返回路径"""
    uploads = files
    if not uploads:
        return JSONResponse({"error": "没有收到文件"}, status_code=400)
    results = []
    for f in uploads:
        name = os.path.basename(f.filename or '')
        if not name.lower().endswith(VIDEO_EXTS):
            continue
        tmp = os.path.join(IMPORT_DIR, ".tmp-" + uuid.uuid4().hex)
        with open(tmp, 'wb') as dst:
            shutil.copyfileobj(f.file, dst)
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
        return JSONResponse({"error": "仅支持 mp4 / mov / mkv / avi / mxf / webm 视频"}, status_code=400)
    warm_proxies([f["path"] for f in results])
    return JSONResponse({"files": results})


@router.post('/api/preview/ensure')
def preview_ensure(data: dict = Body(...)):
    """准备可播放的预览流。

    轻量素材（≤1080p 的 8-bit H.264 等）直接播原文件；重素材播后台生成的轻量代理：
    代理已就绪返回代理地址，未就绪返回状态与进度供前端轮询（在此之前可先播原片）。
    """
    path = (data.get('path') or '').strip().strip('"')
    if not os.path.isfile(path):
        return JSONResponse({"error": "文件不存在"}, status_code=404)

    # 浏览器能直接播的容器 + 轻量编码才播原文件，其余一律走代理
    if not needs_proxy(path):
        return JSONResponse({"url": "/api/preview_file?path=" + path, "proxied": False, "state": None})

    try:
        out = proxy_target(path)
    except OSError:
        return JSONResponse({"url": "/api/preview_file?path=" + path, "proxied": False, "state": None})
    ready = os.path.isfile(out)
    state_now = ensure_proxy(path)
    return JSONResponse({
        # 代理未就绪时不给地址（HEVC 原片浏览器放不了），前端显示生成进度
        "url": "/api/preview_file?path=" + out if ready else "",
        "proxy_url": "/api/preview_file?path=" + out,
        "proxied": ready,
        "state": state_now,
    })


@router.get('/api/preview_file')
def preview_file(request: Request):
    """以支持 Range 的方式发送视频流（浏览器可拖动进度条）"""
    path = request.query_params.get('path', '')
    if not os.path.isfile(path):
        return PlainTextResponse("Not found", status_code=404)
    return FileResponse(path)


@router.post('/api/proxy/states')
def proxy_states(data: dict = Body(None)):
    """批量查询代理状态（素材界面显示生成进度）"""
    data = data or {}
    paths = [str(p) for p in (data.get('paths') or []) if p]
    states = {}
    for path in paths:
        st = proxy_state(path)
        if st is None:
            states[path] = None
            continue
        info = {"state": st, "progress": 0.0}
        if st in ("waiting", "making"):
            try:
                out = proxy_target(path)
                with state._proxy_lock:
                    job = state._proxy_jobs.get(out) or {}
                info["progress"] = round(float(job.get("ratio") or 0.0), 3)
            except OSError:
                pass
        if st == "ready":
            info["progress"] = 1.0
        states[path] = info
    return JSONResponse({"states": states})


@router.post('/api/proxy/ensure')
def proxy_ensure(data: dict = Body(None)):
    """立刻把素材排进代理队列"""
    data = data or {}
    path = str(data.get('path') or '').strip().strip('"')
    if not os.path.isfile(path):
        return JSONResponse({"error": "文件不存在"}, status_code=404)
    return JSONResponse({"state": ensure_proxy(path)})


@router.post('/api/pick_dir')
def pick_dir(data: dict = Body(None)):
    """弹出系统选择框（本工具为本地单机应用，选择框由服务端所在的桌面弹出）

    mode=file：文件选择框，框内直接列出视频文件；返回所选文件所在目录
    mode=dir ：文件夹选择框
    """
    data = data or {}
    title = str(data.get('title') or '选择文件夹')
    initial = str(data.get('initial') or '').strip().strip('"')
    mode = str(data.get('mode') or '').strip().lower()
    if not os.path.isdir(initial):
        initial = BASE_DIR
    if getattr(sys, 'frozen', False):
        # 打包后 sys.executable 是主程序本身：用 --pick-dialog 让它以子进程弹出选择框
        cmd = [sys.executable, '--pick-dialog', mode or 'dir', title, initial]
    elif mode == 'file':
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
        cmd = [sys.executable, "-c", script]
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
        cmd = [sys.executable, "-c", script]
    try:
        env = dict(os.environ, PYTHONIOENCODING='utf-8')
        r = subprocess.run(cmd, capture_output=True, text=True, env=env,
                           encoding='utf-8', errors='replace', timeout=600)
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)
    lines = [l for l in (r.stdout or '').splitlines() if l.strip()]
    path = lines[-1].strip() if lines else ''
    if path and mode == 'file':
        path = os.path.dirname(path)
    return JSONResponse({"path": path})


@router.get('/api/thumb')
def thumb(request: Request):
    """生成带 LUT（可含强度 / 二级 LUT）的单帧缩略图，用于滤镜卡片实时预览"""
    q = request.query_params
    video = q.get('path', '').strip().strip('"')
    lut = q.get('lut', '').strip().strip('"')
    lut2 = q.get('lut2', '').strip().strip('"')
    first = str(q.get('first') or '').lower() in ('1', 'true', 'yes')
    s1 = max(0, min(100, int(q.get('strength', 100))))
    s2 = max(0, min(100, int(q.get('strength2', 100))))
    # 浏览器端着色器的校准结果用 PNG：1280 宽且无色度抽样 / JPEG 压缩损失
    png = str(q.get('png') or '').lower() in ('1', 'true', 'yes')
    w = max(160, min(1280 if png else 720, int(q.get('w', 320))))
    raw = {"grading": q.get('grading'), "masks": q.get('masks'), "mask": q.get('mask')}
    try:
        out, media_type = render_thumb(video, lut, lut2, first, s1, s2, png, w, raw)
    except HttpError as e:
        return JSONResponse({"error": e.message}, status_code=e.status_code)
    return FileResponse(out, media_type=media_type)
