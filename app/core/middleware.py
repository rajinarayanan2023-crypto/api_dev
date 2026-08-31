from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Defense-in-depth headers. HSTS/CSP only make sense once the app is
    actually served over HTTPS (typically terminated at a reverse proxy) —
    enable strict_transport there.
    """

    def __init__(self, app, strict_transport: bool = False):
        super().__init__(app)
        self.strict_transport = strict_transport

    async def dispatch(self, request: Request, call_next) -> Response:
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = "geolocation=(), camera=(), microphone=()"
        response.headers["Cache-Control"] = "no-store"
        if self.strict_transport:
            response.headers["Strict-Transport-Security"] = "max-age=63072000; includeSubDomains"
        return response
