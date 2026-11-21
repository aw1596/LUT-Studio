"""路径与常量配置：源码运行时目录位于仓库根，打包后位于 exe 所在目录。"""

import os
import sys

_FROZEN = bool(getattr(sys, 'frozen', False))

# 可写数据目录（缓存 / LUT / 导入副本）：打包后是 exe 所在目录，源码运行是仓库根
BASE_DIR = os.path.dirname(os.path.abspath(sys.executable)) if _FROZEN else \
    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# 前端静态文件随程序打包在 PyInstaller 的资源目录中
WEB_DIR = os.path.join(getattr(sys, '_MEIPASS', BASE_DIR), "web")
LUTS_DIR = os.path.join(BASE_DIR, "luts")
RESTORE_LUTS_DIR = os.path.join(LUTS_DIR, "restore")      # 官方灰片还原 LUT，放进来即自动显示
LOG_STYLE_LUTS_DIR = os.path.join(LUTS_DIR, "log_style")  # Log 直转风格化 LUT
CREATIVE_LUTS_DIR = os.path.join(LUTS_DIR, "creative")    # 个性化 / 风格 LUT

PREVIEW_CACHE_DIR = os.path.join(BASE_DIR, "_preview_cache")
PROXY_CACHE_DIR = os.path.join(BASE_DIR, "_proxy_cache")  # 重素材的轻量播放 / 渲染代理
THUMB_CACHE_DIR = os.path.join(BASE_DIR, "_thumb_cache")
MASK_CACHE_DIR = os.path.join(BASE_DIR, "_mask_cache")
GRADING_CACHE_DIR = os.path.join(BASE_DIR, "_grading_cache")
BASE_CACHE_DIR = os.path.join(BASE_DIR, "_base_cache")    # 解码后的单帧原图，调参时复用
IMPORT_DIR = os.path.join(BASE_DIR, "_imports")           # 拖拽 / 粘贴导入的视频副本

# 所有需要自动创建的工作目录
DIRS = (
    LUTS_DIR,
    RESTORE_LUTS_DIR,
    LOG_STYLE_LUTS_DIR,
    CREATIVE_LUTS_DIR,
    PREVIEW_CACHE_DIR,
    PROXY_CACHE_DIR,
    THUMB_CACHE_DIR,
    MASK_CACHE_DIR,
    GRADING_CACHE_DIR,
    BASE_CACHE_DIR,
    IMPORT_DIR,
)

VIDEO_EXTS = ('.mp4', '.mov', '.mkv', '.avi', '.mxf', '.webm')


def init_dirs():
    """创建全部工作目录，并把进程工作目录切到仓库根（保证 helper 的相对路径行为一致）"""
    for directory in DIRS:
        os.makedirs(directory, exist_ok=True)
    os.chdir(BASE_DIR)
