import asyncio
import shutil
import subprocess
from datetime import timedelta
from functools import lru_cache
from pathlib import Path

from fastapi import APIRouter, Request, WebSocket, WebSocketDisconnect
from fastapi.concurrency import run_in_threadpool

from app.ai import llm
from app.core.config import DATA_DIR
from app.database.db import session, utcnow
from app.models.models import Job, Project, Publication, Short
from app.processors.media import NO_WINDOW
from app.processors.reframe import YUNET_PATH
from app.publishing.youtube import client_config_status
from app.services import jobs
from app.services.settings import CHOICES, get_settings, update_settings

router = APIRouter(prefix="/api")


@lru_cache(maxsize=1)
def _whisper_cuda() -> bool:
    from app.ai.transcribe import cuda_available

    return cuda_available()


def _gpu() -> dict | None:
    if not shutil.which("nvidia-smi"):
        return None
    try:
        out = subprocess.run(["nvidia-smi", "--query-gpu=name,memory.total,memory.used,utilization.gpu,driver_version",
                              "--format=csv,noheader,nounits"], capture_output=True, text=True, timeout=5,
                             creationflags=NO_WINDOW).stdout.strip().splitlines()[0]
        name, total, used, util, driver = [x.strip() for x in out.split(",")]
        return {"name": name, "vram_total_mb": int(total), "vram_used_mb": int(used), "utilization": int(util), "driver": driver}
    except Exception:
        return None


@router.get("/system/status")
def system_status():
    s = get_settings()
    try:
        import yt_dlp.version

        ytdlp = yt_dlp.version.__version__
    except Exception:
        ytdlp = None
    disk = shutil.disk_usage(DATA_DIR)
    return {
        "ffmpeg": bool(shutil.which("ffmpeg") and shutil.which("ffprobe")),
        "gpu": _gpu(), "whisper_cuda": _whisper_cuda(), "ollama": llm.status(s), "ollama_model": s["ollama_model"],
        "yt_dlp": ytdlp, "face_model": YUNET_PATH.exists(), "youtube": client_config_status(),
        "disk": {"free_gb": round(disk.free / 2**30, 1), "total_gb": round(disk.total / 2**30, 1)},
    }


@router.get("/settings")
def read_settings():
    return {"settings": get_settings(), "choices": CHOICES}


@router.put("/settings")
def write_settings(body: dict):
    return {"settings": update_settings(body), "choices": CHOICES}


@router.get("/stats")
def stats():
    now = utcnow()
    with session() as s:
        published_ids = {p.short_id for p in s.query(Publication).filter(Publication.status.in_(["published", "uploaded", "scheduled", "pending", "uploading"]))}
        ready = s.query(Short).filter(Short.status == "ready", Short.review != "rejected").all()
        return {
            "videos_processed": s.query(Project).filter_by(status="completed").count(),
            "projects": s.query(Project).count(),
            "shorts_generated": s.query(Short).filter_by(status="ready").count(),
            "ready_to_publish": sum(1 for sh in ready if sh.id not in published_ids),
            "published": s.query(Publication).filter(Publication.status.in_(["published", "uploaded"])).count(),
            "scheduled": s.query(Publication).filter(Publication.status.in_(["scheduled", "pending"]),
                                                     Publication.publish_at > now).count(),
            "failed_uploads": s.query(Publication).filter_by(status="failed").count(),
            "recent_projects": [p.to_dict() for p in s.query(Project).order_by(Project.id.desc()).limit(6)],
            "by_engine": {e: s.query(Short).join(Project, Short.project_id == Project.id).filter(
                Short.status == "ready", (Project.engine == e) if e != "podcast" else (Project.engine.is_(None) | (Project.engine == "podcast"))).count()
                for e in ("podcast", "creator", "asmr", "cutting")},
        }


def _size(path: Path) -> int:
    return sum(f.stat().st_size for f in path.rglob("*") if f.is_file()) if path.exists() else 0


@router.get("/storage")
def storage():
    out_dir = Path(get_settings()["output_dir"])
    with session() as s:
        projects = s.query(Project).order_by(Project.id.desc()).all()
    rows = []
    for p in projects:
        src = Path(p.source_path) if p.source_path else None
        rows.append({"id": p.id, "title": p.title, "status": p.status,
                     "source_bytes": src.stat().st_size if src and src.exists() else 0,
                     "project_bytes": _size(DATA_DIR / "projects" / str(p.id)),
                     "exports_bytes": _size(out_dir / str(p.id))})
    return {"projects": rows, "data_dir": str(DATA_DIR), "output_dir": str(out_dir)}


@router.post("/jobs/{job_id}/cancel")
def cancel_job(job_id: int):
    jobs.cancel(job_id)
    return {"ok": True}


@router.post("/jobs/{job_id}/retry")
def retry_job(job_id: int):
    with session() as s:
        j = s.get(Job, job_id)
        if not j or j.status not in ("failed", "cancelled"):
            raise ValueError("Only failed or cancelled jobs can be retried")
        if j.project_id and j.type == "process":
            s.get(Project, j.project_id).status = "queued"
        j.status, j.error, j.progress, j.message, j.cancel_requested = "queued", None, 0.0, "Waiting in queue (retry)", False
    jobs._wake.set()
    return {"ok": True}


@router.post("/system/shutdown")
def shutdown(request: Request):
    if request.client and request.client.host not in ("127.0.0.1", "::1", "localhost"):
        raise ValueError("Shutdown is only allowed from this computer")
    server = getattr(request.app.state, "server", None)
    if server:
        server.should_exit = True
    return {"ok": bool(server)}


def snapshot() -> dict:
    recent = utcnow() - timedelta(minutes=15)
    with session() as s:
        js = (s.query(Job).filter((Job.status.in_(["queued", "running"])) | (Job.finished_at > recent))
              .order_by(Job.id.desc()).limit(30).all())
        titles = {p.id: p.title for p in s.query(Project).filter(Project.id.in_({j.project_id for j in js if j.project_id}))}
        shorts = {sh.id: (sh.project_id, sh.title) for sh in s.query(Short).filter(Short.id.in_({j.short_id for j in js if j.short_id}))}
        pubs = s.query(Publication).filter(Publication.status.in_(["pending", "uploading"]) | (Publication.updated_at > recent)).all()
        job_list = []
        for j in js:
            d = j.to_dict()
            pid = j.project_id or shorts.get(j.short_id, (None,))[0]
            d["project_id"] = pid
            d["label"] = shorts[j.short_id][1] if j.short_id in shorts else titles.get(pid, "")
            job_list.append(d)
        return {"jobs": job_list, "publications": [p.to_dict() for p in pubs]}


@router.websocket("/ws")
async def ws(websocket: WebSocket):
    from app.main import ALLOWED_ORIGINS

    if websocket.headers.get("origin") not in ALLOWED_ORIGINS:
        await websocket.close(code=1008)
        return
    await websocket.accept()
    last = None
    try:
        while True:
            snap = await run_in_threadpool(snapshot)
            if snap != last:
                await websocket.send_json(snap)
                last = snap
            await asyncio.sleep(1)
    except (WebSocketDisconnect, RuntimeError):
        pass
