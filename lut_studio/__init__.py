"""LUT Studio 后端包。

分层约定：
- routers/  只做请求解析与响应返回
- services/ 纯业务逻辑（FFmpeg、调色、渲染、批量转换），不依赖 FastAPI
- config / state / utils 为最底层共享模块
"""
