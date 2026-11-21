"""通用小工具：缓存键、文件时间、数值钳制、业务异常。"""

import hashlib
import os
import sys

# Windows 下让子进程（ffmpeg / ffprobe / python 对话框）不弹控制台黑框；
# 非 Windows 平台为 0，传了也无副作用，保证跨平台安全。
CREATE_NO_WINDOW = 0x08000000 if sys.platform == 'win32' else 0


class HttpError(Exception):
    """业务校验失败；由路由层统一转成 {"error": ...} JSON 响应。"""

    def __init__(self, message, status_code=400):
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def _cache_key(*parts):
    """把任意参数拼成稳定的缓存文件名"""
    raw = "|".join(str(p) for p in parts)
    return hashlib.md5(raw.encode()).hexdigest()


def _file_mtime(path):
    """文件修改时间；文件不存在时返回 0，便于参与缓存键"""
    try:
        return os.path.getmtime(path)
    except OSError:
        return 0


def _clamp(v, lo, hi):
    return max(lo, min(hi, v))


def _even(v):
    """向下取偶数，最小为 2"""
    return max(2, v - v % 2)
