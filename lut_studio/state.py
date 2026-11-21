"""进程级共享状态：批次表、锁、信号量、GPU 探测结果、代理任务队列。

注意：其他模块必须通过 `state.XXX` 读写这些可变量（不能 from ... import 变量），
否则会拿到导入瞬间的旧值。
"""

import atexit
import threading

# === 批量转换 ===
batches = {}
batches_lock = threading.Lock()
active_outputs = set()            # 正在写入的输出路径，防止并发任务写同一文件
active_lock = threading.Lock()
stop_event = threading.Event()    # 置位后所有任务停止
current_procs = {}                # 正在运行的 ffmpeg 进程：input_path -> Popen
procs_lock = threading.Lock()
# 文件多选框选中的素材：下一次 list_videos 只返回这些文件（消费后清空）
picked_selection = None
picked_lock = threading.Lock()

# 并发闸门：避免多个 4K 解码抢资源；调色交互用的单帧渲染单独排队
gen_sem = threading.Semaphore(2)
thumb_sem = threading.Semaphore(4)
base_sem = threading.Semaphore(2)


def _cleanup_procs():
    """服务退出时杀掉所有残留 ffmpeg 子进程，防止孤儿进程锁定输出文件"""
    with procs_lock:
        procs = list(current_procs.values())
    for p in procs:
        try:
            p.kill()
        except Exception:
            pass


atexit.register(_cleanup_procs)

# === GPU 能力探测（启动时由 services.ffmpeg.check_nvenc 填充）===
NVENC_OK = False
NVENC_MSG = ""
PREVIEW_GPU_OK = False  # 预览走 GPU 解码 + NVENC；运行失败时回退 CPU 并置 False
PREVIEW_HW_OK = None    # 预览能否用 NVDEC 硬解；None=未验证，失败后置 False 不再尝试

# === 视频探测缓存（避免同一文件反复 ffprobe）===
_probe_cache = {}
_probe_lock = threading.Lock()

# === 预览代理后台队列 ===
_proxy_jobs = {}      # 代理输出路径 -> {"state", "ratio", "src", "error"}
_proxy_queue = []
_proxy_running = False
_proxy_lock = threading.Lock()
_proxy_hw_decode = True  # 硬件解码失败一次后置 False，本进程不再尝试
