import re
import shutil
import uuid
from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import FileResponse, Response

from app.ai.llm import clean_hashtags
from app.api import music
from app.core.config import DATA_DIR
from app.database.db import session
from app.models.models import CaptionTemplate, Job, Project, Publication, Short
from app.processors import captions
from app.processors.download import video_id
from app.processors.render import caption_preview, load_words
from app.services import jobs, pipeline
from app.services.settings import get_settings

router = APIRouter(prefix="/api")


def _short(s, sid: int) -> Short:
    sh = s.get(Short, sid)
    if not sh:
        raise KeyError("Short not found")
    return sh


def _with_project(s, sh: Short) -> dict:
    p = s.get(Project, sh.project_id)
    d = sh.to_dict()
    d.pop("words")
    d["project_title"] = p.title if p else ""
    d["engine"] = (p.engine if p else None) or "podcast"
    d["source_available"] = bool(p and p.source_path and Path(p.source_path).exists())
    d["youtube_id"] = video_id(p.source_url) if p and p.source_type == "youtube" else None
    d["publications"] = [x.to_dict() for x in s.query(Publication).filter_by(short_id=sh.id).order_by(Publication.id.desc())]
    d["busy"] = s.query(Job).filter(Job.short_id == sh.id, Job.status.in_(["queued", "running"])).first() is not None
    return d


@router.get("/shorts")
def list_shorts(project_id: int | None = None, status: str | None = None, review: str | None = None):
    with session() as s:
        q = s.query(Short)
        if project_id:
            q = q.filter_by(project_id=project_id)
        if status:
            q = q.filter_by(status=status)
        if review:
            q = q.filter_by(review=review)
        return [_with_project(s, sh) for sh in q.order_by(Short.project_id.desc(), Short.rank).all()]


@router.get("/shorts/{sid}")
def get_short(sid: int):
    with session() as s:
        return _with_project(s, _short(s, sid))


@router.patch("/shorts/{sid}")
def update_short(sid: int, body: dict):
    rerender = False
    with session() as s:
        sh = _short(s, sid)
        p = s.get(Project, sh.project_id)
        for k in ("title", "description"):
            if k in body:
                v = str(body[k]).strip()
                if k == "title" and not 1 <= len(v) <= 100:
                    raise ValueError("Title must be 1-100 characters (YouTube limit)")
                if k == "description" and len(v) > 4500:
                    raise ValueError("Description is too long")
                setattr(sh, k, v)
        if "hashtags" in body:
            sh.hashtags = clean_hashtags(body["hashtags"])
        if "review" in body:
            if body["review"] not in ("none", "approved", "rejected"):
                raise ValueError("review must be none, approved or rejected")
            sh.review = body["review"]
        if "caption_style" in body:
            sh.caption_style = captions.resolve_style(body["caption_style"], get_settings()["default_caption_preset"]) if body["caption_style"] else None
            rerender = True
        if "crop_mode" in body or "crop_x" in body:
            mode = body.get("crop_mode", sh.crop_mode)
            x = float(body.get("crop_x", sh.crop_x))
            if mode not in ("auto", "manual") or not 0 <= x <= 1:
                raise ValueError("crop_mode must be auto/manual and crop_x between 0 and 1")
            sh.crop_mode, sh.crop_x = mode, x
            rerender = True
        if "music" in body or "music_volume" in body:  # music None = follow the project, "none" = off
            new = (music.validate_choice(body.get("music", sh.music)), music.validate_volume(body.get("music_volume", sh.music_volume)))
            rerender |= new != (sh.music, sh.music_volume)
            sh.music, sh.music_volume = new
        if "start" in body or "end" in body:
            a, b = float(body.get("start", sh.start)), float(body.get("end", sh.end))
            if not (0 <= a < b <= (p.duration or b)) or not 5 <= b - a <= 180:
                raise ValueError("Start/end must be inside the video and 5-180 seconds apart")
            sh.start, sh.end = a, b
            if sh.words and not (sh.words[0]["s"] <= a + 1 and sh.words[-1]["e"] >= b - 1):
                sh.words = None  # clip-level re-transcription no longer covers the new range
            sh.transcript = " ".join(w["w"] for w in (sh.words or load_words(sh.project_id)) if w["e"] > a and w["s"] < b)
            rerender = True
    if rerender and body.get("rerender", True):
        jobs.enqueue("render", project_id=sh.project_id, short_id=sid)
    return get_short(sid)


@router.post("/shorts/bulk")
def bulk(body: dict):
    ids, action = body.get("ids") or [], body.get("action")
    if action not in ("approve", "reject", "delete", "reset"):
        raise ValueError("action must be approve, reject, reset or delete")
    doomed = []
    with session() as s:
        for sid in ids:
            sh = s.get(Short, int(sid))
            if not sh:
                continue
            if action == "delete":
                _check_deletable(s, [sh.id])
                doomed.append(sh)
                s.delete(sh)
            else:
                sh.review = {"approve": "approved", "reject": "rejected", "reset": "none"}[action]
    for sh in doomed:  # after the commit, so a locked file can't leave rows pointing at deleted videos
        pipeline.delete_short_files(sh)
    return {"ok": True, "count": len(ids)}


def _check_deletable(s, short_ids: list[int]):
    """Refuse deletes that would orphan a running job or a live YouTube upload/schedule."""
    if s.query(Job).filter(Job.short_id.in_(short_ids), Job.status.in_(["queued", "running"])).first():
        raise ValueError("A short has a job in progress - wait for it or cancel it first.")
    pub = s.query(Publication).filter(Publication.short_id.in_(short_ids),
                                      Publication.status.in_(["pending", "uploading", "scheduled"])).first()
    if pub:
        raise ValueError(f"'{pub.title}' has a {pub.status} YouTube upload/schedule. Cancel it in the Publishing Calendar first.")


@router.delete("/shorts/{sid}")
def delete_short(sid: int):
    return bulk({"ids": [sid], "action": "delete"})


def _enqueue_for(sid: int, type_: str, payload=None):
    with session() as s:
        sh = _short(s, sid)
        if s.query(Job).filter(Job.short_id == sid, Job.status.in_(["queued", "running"])).first():
            raise ValueError("This short already has a job in progress.")
    return jobs.enqueue(type_, project_id=sh.project_id, short_id=sid, payload=payload)


@router.post("/shorts/{sid}/render")
def rerender(sid: int):
    return _enqueue_for(sid, "render")


@router.post("/shorts/{sid}/recaption")
def recaption(sid: int):
    return _enqueue_for(sid, "recaption")


@router.post("/shorts/{sid}/regenerate")
def regenerate(sid: int, body: dict):
    field = body.get("field", "all")
    if field not in ("title", "description", "hashtags", "all"):
        raise ValueError("field must be title, description, hashtags or all")
    return _enqueue_for(sid, "metadata", {"field": field})


def _file(path: str | None, media_type: str, filename: str | None = None):
    if not path or not Path(path).exists():
        raise KeyError("File not found - the short may need to be rendered")
    return FileResponse(path, media_type=media_type, filename=filename)


@router.get("/shorts/{sid}/video")
def video(sid: int):
    with session() as s:
        return _file(_short(s, sid).video_path, "video/mp4")


@router.get("/shorts/{sid}/download")
def download(sid: int):
    with session() as s:
        sh = _short(s, sid)
        name = re.sub(r"[^\w\- ]", "", sh.title or f"short-{sid}").strip()[:80] or f"short-{sid}"
        return _file(sh.video_path, "video/mp4", f"{name}.mp4")


@router.get("/shorts/{sid}/thumbnail")
def thumbnail(sid: int):
    with session() as s:
        return _file(_short(s, sid).thumb_path, "image/jpeg")


@router.post("/captions/preview")
def preview(body: dict):
    """Render one real frame with the given caption style burned in (exactly like the final render)."""
    settings = get_settings()
    style = captions.resolve_style(body.get("style"), settings["default_caption_preset"])
    p = sh = None
    with session() as s:
        if body.get("short_id"):
            sh = _short(s, int(body["short_id"]))
            p = s.get(Project, sh.project_id)
    tmp = DATA_DIR / "tmp" / uuid.uuid4().hex
    out = tmp / "preview.jpg"
    try:
        caption_preview(p, sh, style, settings, out)
        data = out.read_bytes()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return Response(data, media_type="image/jpeg", headers={"Cache-Control": "no-store"})


@router.get("/caption-templates")
def list_templates():
    with session() as s:
        custom = [t.to_dict() for t in s.query(CaptionTemplate).order_by(CaptionTemplate.id)]
    return {"presets": captions.PRESETS, "custom": custom, "default": get_settings()["default_caption_preset"]}


@router.post("/caption-templates")
def save_template(body: dict):
    name = str(body.get("name", "")).strip()[:60]
    if not name:
        raise ValueError("Template name is required")
    style = captions.resolve_style(body.get("style"))
    with session() as s:
        t = s.get(CaptionTemplate, int(body["id"])) if body.get("id") else None
        if t is None:
            t = CaptionTemplate(name=name, style=style)
            s.add(t)
        else:
            t.name, t.style = name, style
        s.flush()
        return t.to_dict()


@router.delete("/caption-templates/{tid}")
def delete_template(tid: int):
    with session() as s:
        t = s.get(CaptionTemplate, tid)
        if not t:
            raise KeyError("Template not found")
        s.delete(t)
    return {"ok": True}
