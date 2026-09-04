import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request, status
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from sqlalchemy import text
from starlette.middleware.trustedhost import TrustedHostMiddleware

from app.api.v1.router import api_router
from app.core.config import get_settings
from app.core.database import AsyncSessionLocal
from app.core.exceptions import AppError
from app.core.middleware import SecurityHeadersMiddleware
from app.core.rate_limit import limiter

settings = get_settings()
logger = logging.getLogger("app")

# Neon (and similar serverless Postgres) suspends its compute after a few
# minutes idle — the next real request then pays a multi-second cold-start
# wake-up cost. Pinging on an interval well under that keeps the compute
# permanently warm so users never see that delay, at the cost of the tiny
# amount of compute time this trivial query itself uses.
DB_KEEPALIVE_INTERVAL_SECONDS = 180


async def _db_keepalive_loop() -> None:
    while True:
        try:
            async with AsyncSessionLocal() as session:
                await session.execute(text("SELECT 1"))
        except Exception:
            logger.exception("DB keep-alive ping failed")
        await asyncio.sleep(DB_KEEPALIVE_INTERVAL_SECONDS)


@asynccontextmanager
async def lifespan(app: FastAPI):
    task = asyncio.create_task(_db_keepalive_loop())
    try:
        yield
    finally:
        task.cancel()


app = FastAPI(
    title=settings.app_name,
    debug=settings.debug,
    # Hide interactive docs in production so the full schema/route map isn't
    # handed to anyone who finds the URL.
    docs_url="/docs" if settings.environment != "production" else None,
    redoc_url="/redoc" if settings.environment != "production" else None,
    openapi_url="/openapi.json" if settings.environment != "production" else None,
    lifespan=lifespan,
)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.add_middleware(SlowAPIMiddleware)

app.add_middleware(
    TrustedHostMiddleware,
    allowed_hosts=settings.allowed_hosts_list or ["*"],
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
    allow_headers=["Authorization", "Content-Type"],
)

app.add_middleware(SecurityHeadersMiddleware, strict_transport=settings.environment == "production")


@app.exception_handler(AppError)
async def app_error_handler(request: Request, exc: AppError) -> JSONResponse:
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})


@app.exception_handler(RequestValidationError)
async def validation_error_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    # exc.errors() can include the raw invalid input value (e.g. a Decimal or
    # UUID) in its "input" key, which plain JSONResponse can't serialize —
    # jsonable_encoder converts anything odd to a JSON-safe form first,
    # rather than this handler itself crashing (which then looks like a CORS
    # failure to the browser, since the response never gets sent at all).
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content=jsonable_encoder({"detail": "Validation error.", "errors": exc.errors()}),
    )


@app.exception_handler(Exception)
async def unhandled_error_handler(request: Request, exc: Exception) -> JSONResponse:
    # Never leak internals (stack traces, SQL, file paths) to the client —
    # log the real error server-side and return a generic message.
    logger.exception("Unhandled error while processing %s %s", request.method, request.url.path)
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={"detail": "Internal server error."},
    )


app.include_router(api_router, prefix=settings.api_v1_prefix)

# Every new bill/document upload now goes straight to Cloudflare R2 (see
# app/core/s3.py, upload_controller.py) — this mount only still serves files
# written here before that move, back out at /uploads/<filename>. Created
# eagerly so StaticFiles doesn't fail to mount on a machine that's never
# received a local upload.
Path(settings.upload_dir).mkdir(parents=True, exist_ok=True)
app.mount("/uploads", StaticFiles(directory=settings.upload_dir), name="uploads")


@app.get("/health", tags=["health"])
async def health_check() -> dict[str, str]:
    return {"status": "ok"}
