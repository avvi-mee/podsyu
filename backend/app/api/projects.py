import json
import re
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import FileResponse, RedirectResponse

from app.ai.llm import CATEGORIES, STRATEGIES
from app.api import music
from app.database.db import session
from app.models.models import Job, Project, Publication, Short
from app.processors import captions, download, media
from app.processors.render import project_dir
from app.services import autopilot, jobs, pipeline
from app.services.settings import get_settings

router = APIRouter(prefix="/api")
VIDEO_EXTS = {".mp4", ".mov", ".mkv", ".webm"}


def clean_options(o: dict | None) -> dict:
    s, o = get_settings(), o or {}
    out = {
        "min_duration": int(o.get("min_duration", s["min_duration"])),
        "max_duration": int(o.get("max_duration", s["max_duration"])),
        "num_shorts": int(o.get("num_shorts", s["num_shorts"])),
        "category": o.get("category") or "any",
        "strategy": o.get("strategy") or "balanced",
        "auto_delete_source": bool(o.get("auto_delete_source", s["auto_cleanup_source"])),
    }
    if not 10 <= out["min_duration"] < out["max_duration"] <= 180:
        raise ValueError("Durations must satisfy 10 <= min < max <= 180 seconds")
    if not 1 <= out["num_shorts"] <= 30:
        raise ValueError("Number of shorts must be 1-30")
    if out["category"] not in CATEGORIES + ["any"]:
        raise ValueError(f"category must be one of {['any'] + CATEGORIES}")
    if out["strategy"] not in STRATEGIES:
        raise ValueError(f"strategy must be one of {list(STRATEGIES)}")
    if ap := autopilot.clean(o.get("autopilot"), s["timezone"]):
        out["autopilot"] = ap
    return out


def _queue_process(project_id: int, options: dict | None = None, **payload) -> dict:
    with session() as s:
        p = s.get(Project, project_id)
        if not p:
            raise KeyError("Project not found")
        if options is not None:
            p.options = clean_options({**(p.options or {}), **options})  # keep earlier choices, e.g. auto-delete
            if options.get("caption_style"):
                p.caption_style = captions.resolve_style(options["caption_style"], get_settings()["default_caption_preset"])
            if "music" in options:
                p.music = music.validate_choice(options["music"])
                p.music_volume = music.validate_volume(options.get("music_volume"))
        p.status, p.error = "queued", None
    return jobs.enqueue("process", project_id=project_id, payload=payload)


@router.get("/meta/options")
def meta_options():
    return {"categories": CATEGORIES, "strategies": STRATEGIES, "presets": captions.PRESETS, "fonts": captions.FONTS,
            "positions": list(captions.POSITIONS), "animations": captions.ANIMATIONS}


@router.post("/import/youtube/preview")
def youtube_preview(body: dict):
    return download.fetch_info(body.get("url", ""))


@router.post("/projects/youtube")
def create_youtube(body: dict):
    if body.get("authorized") is not True:
        raise ValueError("Confirm that you own this video or are authorized to download and process it.")
    url = download.validate_url(body.get("url", ""))
    info = body.get("info") or download.fetch_info(url)
    if info.get("duration") and info["duration"] > 4 * 3600:
        raise ValueError("Videos longer than 4 hours are not supported.")
    options = clean_options(body.get("options"))
    with session() as s:
        p = Project(title=(info.get("title") or "YouTube video")[:200], source_type="youtube", source_url=url,
                    channel=info.get("channel"), thumbnail_url=info.get("thumbnail"), duration=info.get("duration"),
                    options=options)
        s.add(p)
        s.flush()
        pid = p.id
    _queue_process(pid, body.get("options"))
    return get_project(pid)


@router.post("/projects/upload")
async def upload_local(request: Request, filename: str, engine: str = "podcast", project_id: int | None = None):
    ext = Path(filename).suffix.lower()
    if ext not in VIDEO_EXTS:
        raise ValueError(f"Unsupported file type '{ext}'. Use MP4, MOV, MKV or WEBM.")
    title = re.sub(r"[_\-]+", " ", Path(filename).stem).strip()[:200] or "Uploaded video"
    if engine not in ("podcast", "creator"):
        raise ValueError("engine must be podcast or creator")
    with session() as s:
        if project_id:  # attach an authorized file to an existing (e.g. transcript-only creator) project
            p = s.get(Project, project_id)
            if not p:
                raise KeyError("Project not found")
            p.source_type = "local" if p.source_type != "youtube" else p.source_type
        else:
            p = Project(title=title, source_type="local", engine=engine)
            s.add(p)
            s.flush()
        pid = p.id
    dest = project_dir(pid) / f"source{ext}"
    size = 0
    try:
        with open(dest, "wb") as f:
            async for chunk in request.stream():
                f.write(chunk)
                size += len(chunk)
        if size == 0:
            raise ValueError("The uploaded file is empty.")
        info = media.probe(dest)
    except Exception as e:
        if project_id:  # attaching to an existing project: only remove the bad file, keep the project
            dest.unlink(missing_ok=True)
        else:
            pipeline.delete_project_files(pid, get_settings()["output_dir"])
            with session() as s:
                s.delete(s.get(Project, pid))
        raise ValueError(str(e))
    with session() as s:
        p = s.get(Project, pid)
        p.source_path, p.source_deleted = str(dest), False
        for k, v in info.items():
            setattr(p, k, v)
    return get_project(pid)


@router.post("/projects/{pid}/process")
def process(pid: int, body: dict | None = None):
    body = body or {}
    return _queue_process(pid, body.get("options"), reanalyze=bool(body.get("reanalyze")), rerender=bool(body.get("rerender")))


@router.get("/projects")
def list_projects():
    with session() as s:
        out = []
        for p in s.query(Project).order_by(Project.id.desc()).all():
            d = p.to_dict()
            d["shorts_total"] = s.query(Short).filter_by(project_id=p.id).count()
            d["shorts_ready"] = s.query(Short).filter_by(project_id=p.id, status="ready").count()
            out.append(d)
        return out


@router.get("/projects/{pid}")
def get_project(pid: int):
    with session() as s:
        p = s.get(Project, pid)
        if not p:
            raise KeyError("Project not found")
        shorts = s.query(Short).filter_by(project_id=pid).order_by(Short.rank).all()
        ids = [sh.id for sh in shorts]
        yid = download.video_id(p.source_url) if p.source_type == "youtube" else None
        return {
            **p.to_dict(),
            "source_available": bool(p.source_path and Path(p.source_path).exists()),
            "transcript_available": (project_dir(pid) / "transcript.json").exists(),
            "shorts": [sh.to_dict() | {"words": None, "youtube_id": yid} for sh in shorts],
            "jobs": [j.to_dict() for j in s.query(Job).filter_by(project_id=pid).order_by(Job.id.desc()).limit(20)],
            "publications": [x.to_dict() for x in s.query(Publication).filter(Publication.short_id.in_(ids)).order_by(Publication.id.desc())],
        }


@router.patch("/projects/{pid}")
def update_project(pid: int, body: dict):
    """Change per-project options while it is processing (read again by the pipeline when it finishes)."""
    if not isinstance(body.get("auto_delete_source"), bool):
        raise ValueError("auto_delete_source must be true or false")
    with session() as s:
        p = s.get(Project, pid)
        if not p:
            raise KeyError("Project not found")
        p.options = {**(p.options or {}), "auto_delete_source": body["auto_delete_source"]}
    return get_project(pid)


@router.get("/projects/{pid}/transcript")
def transcript(pid: int):
    path = project_dir(pid) / "transcript.json"
    if not path.exists():
        raise KeyError("Transcript not available yet")
    data = json.loads(path.read_text("utf-8"))
    return {"language": data.get("language"), "device": data.get("device"),
            "segments": [{"start": s["start"], "end": s["end"], "text": s["text"]} for s in data["segments"]]}


@router.get("/projects/{pid}/thumbnail")
def project_thumbnail(pid: int):
    with session() as s:
        p = s.get(Project, pid)
        if not p:
            raise KeyError("Project not found")
    thumb = project_dir(pid) / "thumb.jpg"
    if not thumb.exists() and p.source_path and Path(p.source_path).exists():
        try:
            media.frame_jpeg(["-ss", f"{(p.duration or 10) * 0.1:.1f}", "-i", p.source_path], "scale=480:-2", thumb)
        except media.MediaError:
            pass
    if thumb.exists():
        return FileResponse(thumb, media_type="image/jpeg")
    if p.thumbnail_url:
        return RedirectResponse(p.thumbnail_url)
    raise KeyError("No thumbnail")


@router.put("/projects/{pid}/music")
def apply_music(pid: int, body: dict):
    """Use one background track (or none) for every short in the project and re-render them."""
    choice, volume = music.validate_choice(body.get("music")), music.validate_volume(body.get("music_volume"))
    with session() as s:
        p = s.get(Project, pid)
        if not p:
            raise KeyError("Project not found")
        p.music, p.music_volume = choice, volume
        shorts = s.query(Short).filter_by(project_id=pid).all()
        for sh in shorts:
            sh.music, sh.music_volume = None, None  # follow the project
        ids = [sh.id for sh in shorts if sh.status in ("ready", "failed")]
    if body.get("rerender", True):
        for sid in ids:
            jobs.enqueue("render", project_id=pid, short_id=sid)
    return {"queued": len(ids)}


@router.put("/projects/{pid}/caption-style")
def apply_caption_style(pid: int, body: dict):
    """Apply one caption style to every short in the project and re-render them."""
    style = captions.resolve_style(body.get("style"), get_settings()["default_caption_preset"])
    with session() as s:
        p = s.get(Project, pid)
        if not p:
            raise KeyError("Project not found")
        p.caption_style = style
        shorts = s.query(Short).filter_by(project_id=pid).all()
        for sh in shorts:
            sh.caption_style = None
        ids = [sh.id for sh in shorts if sh.status in ("ready", "failed")]
    if body.get("rerender", True):
        for sid in ids:
            jobs.enqueue("render", project_id=pid, short_id=sid)
    return {"queued": len(ids)}


@router.post("/projects/{pid}/delete-source")
def delete_source(pid: int):
    with session() as s:
        if s.query(Job).filter(Job.project_id == pid, Job.status.in_(["queued", "running"])).first():
            raise ValueError("Wait for processing to finish before deleting the source video.")
    pipeline.delete_source(pid)
    return {"ok": True}


@router.delete("/projects/{pid}")
def delete_project(pid: int):
    with session() as s:
        p = s.get(Project, pid)
        if not p:
            raise KeyError("Project not found")
        if s.query(Job).filter(Job.project_id == pid, Job.status == "running").first():
            raise ValueError("This project is processing. Cancel the job first.")
        ids = [sh.id for sh in s.query(Short).filter_by(project_id=pid)]
        live = s.query(Publication).filter(Publication.short_id.in_(ids), Publication.status.in_(["pending", "uploading", "scheduled"])).first()
        if live:
            raise ValueError(f"'{live.title}' has a {live.status} YouTube upload/schedule. Cancel it in the Publishing Calendar first.")
        s.query(Job).filter(Job.project_id == pid).delete()
        s.delete(p)
    pipeline.delete_project_files(pid, get_settings()["output_dir"])
    return {"ok": True}
