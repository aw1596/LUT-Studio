"""应用组装与启动入口。

`python server.py`（或 `python -m lut_studio.main`）都会走到这里。
"""

import os
import socket
import sys
import threading
import webbrowser

import uvicorn
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from helper import download_dji_lut_if_needed

from . import state
from .config import BASE_DIR, WEB_DIR, init_dirs
from .routers import export, grading, lut, material, task
from .services.ffmpeg import check_nvenc

FROZEN = bool(getattr(sys, 'frozen', False))


def _prepare_runtime():
    """打包运行时：使用自带的 ffmpeg / ffprobe，并设置控制台标题"""
    if not FROZEN:
        return
    bin_dir = os.path.join(BASE_DIR, 'bin')
    if os.path.isdir(bin_dir):
        os.environ['PATH'] = bin_dir + os.pathsep + os.environ.get('PATH', '')
    os.system('title LUT Studio - 关闭此窗口即可退出')


def _pick_port(start=5000):
    """从 start 开始找一个可用端口，避免与用户机器上的其他服务冲突"""
    for port in range(start, start + 20):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(('127.0.0.1', port))
                return port
            except OSError:
                continue
    return start



def create_app():
    """创建 app：注册路由，最后挂载静态文件（否则 '/' 会吞掉所有 API）"""
    init_dirs()
    app = FastAPI(title='LUT Studio')
    for router in (material.router, lut.router, grading.router,
                   export.router, task.router):
        app.include_router(router)
    app.mount('/', StaticFiles(directory=WEB_DIR, html=True), name='web')
    return app


app = create_app()


def main():
    _prepare_runtime()
    download_dji_lut_if_needed()  # 启动时确保内置 LUT 存在
    print("检测 GPU 编码器 (NVENC)...")
    check_nvenc()
    if state.NVENC_OK:
        print("  NVENC 可用，可使用 GPU 加速。")
    else:
        print(f"  NVENC 不可用: {state.NVENC_MSG}")
        print("  可升级 NVIDIA 驱动至 610.00+，或使用 CPU 模式。")
    port = _pick_port()
    url = f"http://127.0.0.1:{port}"
    print(f"\n  Web UI 已启动: {url}\n")
    if FROZEN and not os.environ.get('LUT_NO_BROWSER'):
        threading.Timer(1.5, lambda: webbrowser.open(url)).start()
    uvicorn.run(app, host='127.0.0.1', port=port, log_level='info')


if __name__ == '__main__':
    main()
