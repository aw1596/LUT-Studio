"""任务模块：批次查询，以及单个条目的暂停 / 继续 / 取消 / 删除，和全部暂停 / 继续。"""

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from .. import state
from ..services.batch import resume_proc, suspend_proc

router = APIRouter()

ACTIVE = ('pending', 'converting')


def _find(batch_id, item_id):
    """在批次中按 id 查找条目，返回 (batch, item)；不存在时返回 (None, None)"""
    batch = state.batches.get(batch_id)
    if not batch:
        return None, None
    for item in batch['items']:
        if item.get('id') == item_id:
            return batch, item
    return batch, None


def _running_proc(item):
    """取出条目对应的 ffmpeg 进程（可能尚未创建）"""
    with state.procs_lock:
        return state.current_procs.get(item['input'])


@router.get('/api/batches')
def list_batches(request: Request):
    with state.batches_lock:
        return JSONResponse({"batches": list(state.batches.values())})


@router.post('/api/stop_all')
def stop_all(request: Request):
    """取消全部转换：终止当前 ffmpeg 进程，队列中剩余文件标记为已取消"""
    state.stop_event.set()
    with state.procs_lock:
        procs = list(state.current_procs.values())
    for p in procs:
        try:
            p.kill()
        except Exception:
            pass
    return JSONResponse({"ok": True})


@router.post('/api/pause_all')
def pause_all(request: Request):
    """暂停全部：挂起正在转换的进程，并让排队中的条目暂停启动"""
    procs = []
    with state.batches_lock:
        for batch in state.batches.values():
            for item in batch['items']:
                if item['status'] not in ACTIVE:
                    continue
                item['paused'] = True
                if item['status'] == 'converting':
                    proc = _running_proc(item)
                    if proc:
                        procs.append(proc)
    for proc in procs:
        suspend_proc(proc)
    return JSONResponse({"ok": True})


@router.post('/api/resume_all')
def resume_all(request: Request):
    """继续全部：恢复暂停中的条目"""
    procs = []
    with state.batches_lock:
        for batch in state.batches.values():
            for item in batch['items']:
                if not item.get('paused'):
                    continue
                item['paused'] = False
                if item['status'] == 'converting':
                    proc = _running_proc(item)
                    if proc:
                        procs.append(proc)
    for proc in procs:
        resume_proc(proc)
    return JSONResponse({"ok": True})


@router.post('/api/tasks/{batch_id}/{item_id}/pause')
def pause_item(batch_id: str, item_id: str):
    with state.batches_lock:
        batch, item = _find(batch_id, item_id)
        if not item:
            return JSONResponse({"error": "任务不存在"}, status_code=404)
        if item['status'] not in ACTIVE:
            return JSONResponse({"error": "该任务已结束，无法暂停"}, status_code=400)
        item['paused'] = True
        status = item['status']
    # 排队中的条目由 run_batch 在启动前等待；转换中的条目直接挂起 ffmpeg
    if status == 'converting':
        proc = _running_proc(item)
        if proc:
            suspend_proc(proc)
    return JSONResponse({"ok": True})


@router.post('/api/tasks/{batch_id}/{item_id}/resume')
def resume_item(batch_id: str, item_id: str):
    with state.batches_lock:
        batch, item = _find(batch_id, item_id)
        if not item:
            return JSONResponse({"error": "任务不存在"}, status_code=404)
        if item['status'] not in ACTIVE:
            return JSONResponse({"error": "该任务已结束，无法继续"}, status_code=400)
        item['paused'] = False
        status = item['status']
    if status == 'converting':
        proc = _running_proc(item)
        if proc:
            resume_proc(proc)
    return JSONResponse({"ok": True})


@router.post('/api/tasks/{batch_id}/{item_id}/cancel')
def cancel_item(batch_id: str, item_id: str):
    """取消单个条目：终止它自己的 ffmpeg，不影响同批其他文件"""
    with state.batches_lock:
        batch, item = _find(batch_id, item_id)
        if not item:
            return JSONResponse({"error": "任务不存在"}, status_code=404)
        if item['status'] not in ACTIVE:
            return JSONResponse({"error": "该任务已结束，无法取消"}, status_code=400)
        item['status'] = 'cancelled'
        item['paused'] = False
    # 排队中的条目由 run_batch 直接跳过；转换中的需要立刻杀掉给它自己的 ffmpeg
    proc = _running_proc(item)
    if proc:
        try:
            proc.kill()
        except Exception:
            pass
    return JSONResponse({"ok": True})


@router.delete('/api/tasks/{batch_id}/{item_id}')
def delete_item(batch_id: str, item_id: str):
    """从队列移除条目；正在转换的先终止，避免条目消失后进程还在写文件"""
    with state.batches_lock:
        batch, item = _find(batch_id, item_id)
        if not item:
            return JSONResponse({"error": "任务不存在"}, status_code=404)
        converting = item['status'] == 'converting'
        if converting:
            item['status'] = 'cancelled'
            item['paused'] = False
        batch['items'].remove(item)
        if not batch['items']:
            state.batches.pop(batch_id, None)
    if converting:
        proc = _running_proc(item)
        if proc:
            try:
                proc.kill()
            except Exception:
                pass
    return JSONResponse({"ok": True})
