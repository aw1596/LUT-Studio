"""导出模块：发起批量转换、写权限诊断。"""

import os

from fastapi import APIRouter, Body, Request
from fastapi.responses import JSONResponse

from ..services.batch import start_convert
from ..utils import HttpError

router = APIRouter()


@router.post('/api/convert')
def convert(data: dict = Body(...)):
    try:
        batch_id = start_convert(data)
    except HttpError as e:
        return JSONResponse({"error": e.message}, status_code=e.status_code)
    return JSONResponse({"batch_id": batch_id})


@router.get('/api/write_test')
def write_test(request: Request):
    """诊断：测试 server 进程自身对指定路径的写权限"""
    path = request.query_params.get('path', '')
    if not path:
        return JSONResponse({"error": "缺少 path 参数"}, status_code=400)
    try:
        with open(path, 'wb') as f:
            f.write(b'ok')
        os.remove(path)
        return JSONResponse({"ok": True, "msg": f"server 进程可写: {path}"})
    except Exception as e:
        return JSONResponse({"ok": False, "error": f"{type(e).__name__}: {e}"})
