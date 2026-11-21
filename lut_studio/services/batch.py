"""批量转换：任务创建、逐文件转码、进度与停止 / 暂停处理。"""

import ctypes
import os
import signal
import subprocess
import threading
import time
import uuid

from helper import get_video_fps

from .. import state
from ..utils import CREATE_NO_WINDOW, HttpError, _even
from .ffmpeg import audio_out_args, get_video_duration, probe_video
from .grading import is_neutral_grading
from .mask import active_masks, ensure_mask_layers
from .render import build_filter_graph, mask_render_list, prepare_adjustments


def target_size(width, height, resolution='original'):
    """按导出分辨率换算目标宽高（保持比例，宽度取偶数）；无需缩放时返回 None"""
    if not width or not height:
        return None
    if resolution in ('1080p', '720p'):
        h = 1080 if resolution == '1080p' else 720
        if height > h:
            return (max(2, int(round(width * h / float(height) / 2)) * 2), h)
    if width % 2 == 0 and height % 2 == 0:
        return None
    return (_even(width), _even(height))


def _normalize_files(raw_files, defaults):
    """把 files 归一化为 [(path, LUT 参数)]。

    元素可以是字符串（沿用请求顶层的全局 LUT，兼容旧调用），
    也可以是对象（每个素材各自的 LUT，前端新格式）。
    """
    out = []
    for entry in raw_files:
        if isinstance(entry, dict):
            path = str(entry.get('path') or '').strip().strip('"')

            def pick(key):
                v = entry.get(key)
                return defaults[key] if v is None else v

            params = {
                'lut_path': str(pick('lut_path')).strip().strip('"'),
                'lut_path2': str(pick('lut_path2')).strip().strip('"'),
                'lut_strength': max(0, min(100, int(pick('lut_strength')))),
                'lut_strength2': max(0, min(100, int(pick('lut_strength2')))),
                'lut_label': str(entry.get('lut_label') or ''),
                'graded': bool(entry.get('graded')),
            }
        else:
            path = str(entry or '').strip().strip('"')
            params = dict(defaults, lut_label='', graded=False)
        if path:
            out.append((path, params))
    return out


def start_convert(data):
    """创建批次并启动后台转换线程，返回 batch_id（参数不合法时抛 HttpError）"""
    defaults = {
        'lut_path': str(data.get('lut_path') or '').strip().strip('"'),
        'lut_path2': str(data.get('lut_path2') or '').strip().strip('"'),
        'lut_strength': max(0, min(100, int(data.get('lut_strength') or 100))),
        'lut_strength2': max(0, min(100, int(data.get('lut_strength2') or 100))),
        'lut_label': '',
        'graded': bool(data.get('graded')),
    }
    output_mode = data.get('output_mode', 'subfolder')
    custom_dir = data.get('custom_dir', '').strip().strip('"')
    use_gpu = bool(data.get('use_gpu', True))
    quality = int(data.get('quality', 20))
    bit_depth = 10 if int(data.get('bit_depth', 8)) == 10 else 8
    resolution = data.get('resolution', 'original')
    if resolution not in ('original', '1080p', '720p'):
        resolution = 'original'

    files = _normalize_files(data.get('files', []), defaults)
    if not files:
        raise HttpError("未选择文件", 400)
    # 每个文件的 LUT 都单独校验，避免一个坏路径拖垮整批
    for _, params in files:
        if params['lut_path'] and not os.path.isfile(params['lut_path']):
            raise HttpError("LUT 文件不存在", 400)
        if params['lut_path2'] and not os.path.isfile(params['lut_path2']):
            raise HttpError("第二个 LUT 文件不存在", 400)
    if output_mode == 'custom' and not custom_dir:
        raise HttpError("请填写自定义输出目录", 400)
    if use_gpu and not state.NVENC_OK:
        raise HttpError(f"GPU 编码不可用：{state.NVENC_MSG}。请改用 CPU 模式，或升级 NVIDIA 驱动后重启本服务。", 400)

    grading, masks = prepare_adjustments(data)
    # 整批都没有任何调整时直接拒绝；单个文件无调整会在 run_batch 中标记跳过
    if all(not p['lut_path'] and not p['lut_path2'] for _, p in files) and \
            is_neutral_grading(grading) and not active_masks(masks):
        raise HttpError("未选择 LUT，且调色参数均为默认值，没有可导出的调整", 400)

    state.stop_event.clear()  # 新任务开始前清除停止标志
    batch_id = uuid.uuid4().hex[:8]
    items = []
    for input_path, params in files:
        input_dir = os.path.dirname(input_path)
        filename = os.path.basename(input_path)
        if output_mode == 'prefix':
            output_path = os.path.join(input_dir, f"converted_{filename}")
        elif output_mode == 'custom':
            os.makedirs(custom_dir, exist_ok=True)
            output_path = os.path.join(custom_dir, filename)
        else:
            out_dir = os.path.join(input_dir, 'converted')
            os.makedirs(out_dir, exist_ok=True)
            output_path = os.path.join(out_dir, filename)
        item = {
            "id": uuid.uuid4().hex[:8],
            "name": filename,
            "input": input_path,
            "output": output_path,
            "status": "pending",
            "progress": 0,
            "paused": False,
            "error": None,
            **params,
        }
        # 输出与输入同路径时 ffmpeg 会因文件占用报 Permission denied
        if os.path.abspath(output_path) == os.path.abspath(input_path):
            item["status"] = "error"
            item["error"] = "输出路径与输入文件相同。请改用前缀/子目录模式，或选择其他输出目录。"
        items.append(item)

    with state.batches_lock:
        state.batches[batch_id] = {"id": batch_id, "items": items, "status": "running"}

    threading.Thread(target=run_batch,
                     args=(batch_id, use_gpu, quality, bit_depth, resolution,
                           grading, masks),
                     daemon=True).start()
    return batch_id


def suspend_proc(proc):
    """挂起 ffmpeg 进程（Windows 用 NtSuspendProcess，其他平台用 SIGSTOP）"""
    try:
        if os.name == 'nt':
            ctypes.windll.ntdll.NtSuspendProcess(ctypes.c_void_p(int(proc._handle)))
        else:
            os.kill(proc.pid, signal.SIGSTOP)
        return True
    except Exception:
        return False


def resume_proc(proc):
    """恢复被挂起的 ffmpeg 进程"""
    try:
        if os.name == 'nt':
            ctypes.windll.ntdll.NtResumeProcess(ctypes.c_void_p(int(proc._handle)))
        else:
            os.kill(proc.pid, signal.SIGCONT)
        return True
    except Exception:
        return False


def run_batch(batch_id, use_gpu, quality, bit_depth,
              resolution='original', grading=None, masks=None):
    """依次转换批次内文件；每个文件使用自己的 LUT；暂停的条目原地等待，取消的条目跳过"""
    batch = state.batches.get(batch_id)
    if not batch:
        return
    # 快照遍历：条目可能在转换过程中被用户删除，不能直接改正在遍历的列表
    for item in list(batch['items']):
        if item not in batch['items']:
            continue
        # 排队中的条目被暂停：等待继续或取消，而不是直接标记为取消
        while item.get('paused') and item['status'] == 'pending':
            if state.stop_event.wait(0.2) or item not in batch['items']:
                break
        if item not in batch['items']:
            continue
        if state.stop_event.is_set():
            if item['status'] == 'pending':
                item['status'] = 'cancelled'
            continue
        if item['status'] != 'pending':
            continue
        # 该素材既没有 LUT，全局调色 / 蒙版也是中性的：导出结果与原片一致，标记跳过
        if not item.get('lut_path') and not item.get('lut_path2') and \
                is_neutral_grading(grading) and not active_masks(masks):
            item['status'] = 'error'
            item['error'] = '未选择 LUT，已跳过'
            item['progress'] = 100
            continue
        if os.path.exists(item['output']):
            item['status'] = 'skipped'
            item['progress'] = 100
            continue
        # 防止与其他并发任务写同一输出文件
        with state.active_lock:
            if item['output'] in state.active_outputs:
                item['status'] = 'error'
                item['error'] = "该文件正在另一个转换任务中处理，请勿重复提交。"
                continue
            state.active_outputs.add(item['output'])
        try:
            item['status'] = 'converting'
            # Permission denied 多为临时文件锁定（如残留的 ffmpeg 进程、播放器占用），自动重试
            last_err = None
            for attempt in range(3):
                try:
                    convert_one(item, use_gpu, quality, bit_depth,
                                resolution, grading, masks)
                    last_err = None
                    break
                except InterruptedError:
                    raise
                except Exception as e:
                    last_err = e
                    if "Permission denied" in str(e) and attempt < 2:
                        if state.stop_event.wait(3):  # 等待期间可被停止指令打断
                            raise InterruptedError("用户停止了转换")
                        continue
                    raise
            if last_err:
                raise last_err
            item['status'] = 'done'
            item['progress'] = 100
        except InterruptedError:
            item['status'] = 'cancelled'
            # 删除中断产生的半成品文件（无 moov 无法播放，且避免下次被“已存在”跳过）
            try:
                os.remove(item['output'])
            except OSError:
                pass
        except Exception as e:
            item['status'] = 'error'
            item['error'] = str(e)
            # 删除失败留下的残缺文件（如 0 字节文件），避免下次被误判为已转换
            try:
                os.remove(item['output'])
            except OSError:
                pass
        finally:
            with state.active_lock:
                state.active_outputs.discard(item['output'])
    batch['status'] = 'stopped' if state.stop_event.is_set() else 'done'


def convert_one(item, use_gpu, quality, bit_depth,
                resolution='original', grading=None, masks=None):
    """转换单个文件：用该文件自己的 LUT 构建滤镜图 → 启动 ffmpeg → 实时更新进度"""
    input_path = item['input']
    output_path = item['output']
    fps = get_video_fps(input_path)
    duration = get_video_duration(input_path)
    info = probe_video(input_path)

    lut_path = item.get('lut_path') or ''
    lut_path2 = item.get('lut_path2') or ''
    stages = [(lut_path, item.get('lut_strength', 100))]
    if lut_path2:
        stages.append((lut_path2, item.get('lut_strength2', 100)))
    # 内部处理统一用 10bit 平面 RGB（gbrp10le）：即使最终输出 8bit，调色 / 曲线 / LUT
    # 也在 10bit 精度下计算，避免多次 8bit 量化误差累积产生色带；最后再降到目标色深。
    fmt_in = 'gbrp10le'
    fmt_out = 'yuv420p10le' if bit_depth == 10 else 'yuv420p'
    # 10bit 内部处理后降到 8bit 输出时加抖动，消除天空 / 肤色等平滑渐变的截断阶梯
    need_dither = (bit_depth == 8)
    size = target_size(info["width"], info["height"], resolution)
    layers = mask_render_list(masks) if info["width"] and info["height"] else []
    if layers:
        mw, mh = size if size else (info["width"], info["height"])
        ensure_mask_layers(layers, mw, mh)
    filter_complex = build_filter_graph(stages, fmt_in, fmt_out,
                                        size=size, grading=grading, mask_layers=layers,
                                        dither=need_dither)
    pix_fmt = fmt_out

    cmd = [
        "ffmpeg", "-y",
        "-fflags", "+genpts",
        "-i", input_path,
    ]
    for layer in layers:
        # 蒙版为无限循环的静态图，按原片时长封顶，避免源无帧时无限编码
        cmd += ["-loop", "1", "-framerate", str(fps)]
        if duration:
            cmd += ["-t", f"{duration + 10:.1f}"]
        cmd += ["-i", layer["png"]]
    cmd += [
        "-filter_complex", filter_complex,
        "-map", "[vo]",
        "-map", "0:a?",  # 保留原音轨；无音轨时自动忽略
        "-r", str(fps),
        "-fps_mode", "cfr",
    ]
    if use_gpu:
        # 10bit 使用 HEVC（H.264 10bit 兼容性差）
        encoder = "hevc_nvenc" if bit_depth == 10 else "h264_nvenc"
        cmd += [
            "-c:v", encoder,
            "-preset", "p6",
            "-tune", "hq",
            "-rc", "vbr",
            "-cq", str(quality),
            "-b:v", "0",
            "-multipass", "fullres",
        ]
    elif bit_depth == 10:
        cmd += [
            "-c:v", "libx265",
            "-crf", str(quality),
            "-preset", "medium",
        ]
    else:
        cmd += [
            "-c:v", "libx264",
            "-crf", str(quality),
            "-preset", "medium",
        ]
    # 注意：不指定 -level，由编码器按分辨率/帧率自动选择（4K 需要 level 5.x）
    cmd += ["-pix_fmt", pix_fmt]
    # 写入 Rec.709 色彩空间标记：-color_* 写容器层；再用 bsf 写码流 VUI。
    # 实测仅靠 -color_* 时，x264 / x265 / nvenc 都只会写 colorspace，
    # color_primaries 与 color_trc 仍为 unknown，必须由 bsf 补全（1 = BT.709）。
    cmd += ["-color_primaries", "bt709", "-color_trc", "bt709", "-colorspace", "bt709"]
    color_bsf = ('hevc_metadata' if bit_depth == 10 else 'h264_metadata') + \
        '=colour_primaries=1:transfer_characteristics=1:matrix_coefficients=1'
    cmd += ["-bsf:v", color_bsf]
    if bit_depth == 10:
        cmd += ["-tag:v", "hvc1"]  # 提升 HEVC 在 QuickTime/苹果设备的兼容性
        if use_gpu:
            cmd += ["-profile:v", "main10"]
    else:
        cmd += ["-profile:v", "high"]
    cmd += [
        # 音频：MP4 能装的编码直接 copy；PCM 等不兼容编码转 AAC
        *audio_out_args(input_path),
        "-progress", "pipe:1",
        "-nostats",
        output_path,
    ]

    # 暂停期间不启动新的 ffmpeg；取消则直接退出
    while item.get('paused'):
        if item['status'] == 'cancelled':
            raise InterruptedError("用户取消了该任务")
        time.sleep(0.2)

    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            text=True, encoding='utf-8', errors='replace',
                            creationflags=CREATE_NO_WINDOW)

    # 单独线程收集 stderr，防止管道缓冲区写满造成死锁
    stderr_lines = []

    def read_stderr():
        for line in proc.stderr:
            stderr_lines.append(line)

    t = threading.Thread(target=read_stderr, daemon=True)
    t.start()

    with state.procs_lock:
        state.current_procs[item['input']] = proc
    # 进程刚创建时若已请求暂停，立即挂起（避免暂停指令与启动竞争）
    if item.get('paused'):
        suspend_proc(proc)
    try:
        for line in proc.stdout:
            line = line.strip()
            # FFmpeg 5.x+ 字段为 out_time_us，旧版为 out_time_ms，单位均为微秒
            if (line.startswith("out_time_us=") or line.startswith("out_time_ms=")) and duration:
                try:
                    us = int(line.split('=', 1)[1])
                    item['progress'] = min(99, round(us / 1e6 / duration * 100, 1))
                except ValueError:
                    pass
        proc.wait()
        t.join(timeout=2)
    finally:
        with state.procs_lock:
            state.current_procs.pop(item['input'], None)

    # 全局停止或单条取消都会让进程被 kill，统一按中断处理
    if item['status'] == 'cancelled' or state.stop_event.is_set():
        raise InterruptedError("用户取消了该任务")

    if proc.returncode != 0:
        tail = "".join(stderr_lines[-12:]).strip()
        msg = tail[-800:] if tail else f"FFmpeg 退出码 {proc.returncode}"
        if "Permission denied" in msg:
            msg += ("\n\n排查建议：1) 输出目录不要与源目录相同；2) 不要重复点击“开始转换”；"
                    "3) 若输出到桌面/文档等受保护目录，检查 Windows 安全中心 → 勒索软件防护 → "
                    "受控文件夹访问 是否拦截了 ffmpeg；4) 确认没有播放器正在占用同名输出文件。")
        raise RuntimeError(msg)
