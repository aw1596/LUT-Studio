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


def _user_log_dir():
    """日志目录：打包后写到用户可写的 LOCALAPPDATA，避免无控制台时日志丢失"""
    base = os.environ.get('LOCALAPPDATA') or os.path.expanduser('~')
    d = os.path.join(base, 'LUT Studio', 'logs')
    os.makedirs(d, exist_ok=True)
    return d


def _redirect_stdio_to_log():
    """windowed（无控制台）打包后 sys.stdout / stderr 为 None；重定向到日志文件，
    既保留 uvicorn / 业务日志便于排查，也避免向 None 写入报错。"""
    if not FROZEN:
        return
    log_path = os.path.join(_user_log_dir(), 'app.log')
    try:
        if os.path.isfile(log_path) and os.path.getsize(log_path) > 2_000_000:
            os.replace(log_path, log_path + '.old')
    except OSError:
        pass
    f = open(log_path, 'a', encoding='utf-8')
    sys.stdout = f
    sys.stderr = f


def _prepare_runtime():
    """打包运行时：使用自带的 ffmpeg / ffprobe，并重定向日志到文件"""
    if not FROZEN:
        return
    _redirect_stdio_to_log()
    bin_dir = os.path.join(BASE_DIR, 'bin')
    if os.path.isdir(bin_dir):
        os.environ['PATH'] = bin_dir + os.pathsep + os.environ.get('PATH', '')
    # windowed 模式无控制台：os.system('title ...') 会闪一下 cmd 窗口，故不再设置


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

    @app.post('/api/shutdown')
    def _shutdown():
        """退出程序：windowed 打包无控制台可关，由前端「退出」按钮触发"""
        import threading
        # 延迟退出，让本响应先返回前端；本地单机应用直接结束进程即可
        threading.Timer(0.5, lambda: os._exit(0)).start()
        return {'ok': True}

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
