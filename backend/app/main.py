import logging
from contextlib import asynccontextmanager
from logging.handlers import RotatingFileHandler

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.core.config import FRONTEND_PORT, FRONTEND_URL, LOG_DIR

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    handlers=[logging.StreamHandler(), RotatingFileHandler(LOG_DIR / "app.log", maxBytes=5_000_000, backupCount=3, encoding="utf-8")],
)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("googleapiclient.discovery_cache").setLevel(logging.ERROR)

from app.api import asmr, creators, cutting, media, music, projects, publishing, shorts, system  # noqa: E402
from app.database.db import init_db  # noqa: E402
from app.scheduler import scheduler  # noqa: E402
from app.services import jobs  # noqa: E402

ALLOWED_ORIGINS = {FRONTEND_URL, f"http://localhost:{FRONTEND_PORT}", f"http://127.0.0.1:{FRONTEND_PORT}"}


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    jobs.start_worker()
    scheduler.start()
    logging.getLogger(__name__).info("Backend ready")
    yield
    jobs.stop_worker()
    scheduler.stop()
    from app.ai.transcribe import kill_children

    kill_children()


app = FastAPI(title="Podcast Shorts Factory", lifespan=lifespan)


@app.middleware("http")
async def block_cross_site_writes(request: Request, call_next):
    """The API has no login (localhost only), so refuse state-changing requests from other websites."""
    origin = request.headers.get("origin")
    if request.method not in ("GET", "HEAD", "OPTIONS") and origin and origin not in ALLOWED_ORIGINS:
        return JSONResponse({"detail": "Cross-site request blocked"}, status_code=403)
    return await call_next(request)


app.add_middleware(CORSMiddleware, allow_origins=list(ALLOWED_ORIGINS), allow_methods=["*"], allow_headers=["*"])


@app.exception_handler(ValueError)
async def value_error(_, exc: ValueError):
    return JSONResponse({"detail": str(exc)}, status_code=400)


@app.exception_handler(KeyError)
async def key_error(_, exc: KeyError):
    return JSONResponse({"detail": str(exc).strip("'\"")}, status_code=404)


def _user_error(_, exc: Exception):
    """Domain errors carry a message written for the user - show it instead of a bare 500."""
    return JSONResponse({"detail": str(exc)}, status_code=400)


from app.ai.llm import LLMError  # noqa: E402
from app.processors.download import DownloadError  # noqa: E402
from app.processors.media import MediaError  # noqa: E402
from app.publishing.youtube import PublishError  # noqa: E402

for _exc in (PublishError, DownloadError, MediaError, LLMError, FileNotFoundError):
    app.add_exception_handler(_exc, _user_error)


for r in (system.router, projects.router, shorts.router, publishing.router, music.router, media.router, asmr.router,
          creators.router, cutting.router):
    app.include_router(r)
