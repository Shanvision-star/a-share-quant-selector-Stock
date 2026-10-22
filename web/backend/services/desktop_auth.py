"""仅桌面实例启用的回环认证，不改变既有网页部署的认证约定。"""

import hmac
import os

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse


class DesktopAuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        token = os.environ.get("QUANT_DESKTOP_TOKEN")
        if token and request.url.path.startswith("/api/"):
            supplied = request.headers.get("x-quant-token", "")
            if not hmac.compare_digest(supplied.encode(), token.encode()):
                return JSONResponse({"detail": "桌面实例认证失败，请通过桌面客户端或已配置的本地工具连接"}, status_code=401)
        return await call_next(request)
