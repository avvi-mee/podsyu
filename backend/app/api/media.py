"""Media Library: background footage for story shorts (+ API keys for licensed sources)."""
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import FileResponse

from app.core import secure
from app.core.config import DATA_DIR, MEDIA_DIR
from app.database.db import session
from app.models.models import BackgroundMedia
from app.processors import backgrounds, media
from app.services import jobs, stories

router = APIRouter(prefix="/api")
VIDEO_EXTS = {".mp4", ".mov", ".mkv", ".webm"}


@router.get("/media")
def list_media():
    with session() as s:
        items = [m.to_dict() for m in s.query(BackgroundMedia).order_by(BackgroundMedia.favourite.desc(), BackgroundMedia.id.desc())]
    return {"items": [i for i in items if (MEDIA_DIR / i["filename"]).exists()],
            "categories": backgrounds.MEDIA_CATEGORIES,
            "presets": {k: {"title": v[0], "category": v[1]} for k, v in backgrounds.PRESETS.items()}}


@router.post("/media/upload")
async def upload_media(request: Request, filename: str, category: str = "satisfying"):
    ext = Path(filename).suffix.lower()
    if ext not in VIDEO_EXTS:
        raise ValueError("Use MP4, MOV, MKV or WEBM.")
    if category not in backgrounds.MEDIA_CATEGORIES:
        raise ValueError(f"category must be one of {backgrounds.MEDIA_CATEGORIES}")
    dest = backgrounds.unique_path(Path(filename).stem, ext)
    with open(dest, "wb") as f:
        async for chunk in request.stream():
            f.write(chunk)
    try:
        return backgrounds.register(dest, Path(filename).stem[:100], category, source="upload", license="Own footage")
    except media.MediaError:
        dest.unlink(missing_ok=True)
        raise


@router.patch("/media/{mid}")
def update_media(mid: int, body: dict):
    with session() as s:
        m = s.get(BackgroundMedia, mid)
        if not m:
            raise KeyError("Media not found")
        if "title" in body:
            m.title = str(body["title"]).strip()[:120] or m.title
        if "category" in body:
            if body["category"] not in backgrounds.MEDIA_CATEGORIES:
                raise ValueError(f"category must be one of {backgrounds.MEDIA_CATEGORIES}")
            m.category = body["category"]
        if "favourite" in body:
            m.favourite = bool(body["favourite"])
        return m.to_dict()


@router.delete("/media/{mid}")
def delete_media(mid: int):
    with session() as s:
        m = s.get(BackgroundMedia, mid)
        if not m:
            raise KeyError("Media not found")
        name = m.filename
        s.delete(m)
    (MEDIA_DIR / name).unlink(missing_ok=True)
    (DATA_DIR / "tmp" / f"media_{mid}.jpg").unlink(missing_ok=True)
    return {"ok": True}


@router.get("/media/{mid}/file")
def media_file(mid: int):
    with session() as s:
        m = s.get(BackgroundMedia, mid)
        if not m or not (MEDIA_DIR / m.filename).exists():
            raise KeyError("Media not found")
        return FileResponse(MEDIA_DIR / m.filename, media_type="video/mp4")


@router.get("/media/{mid}/thumbnail")
def media_thumb(mid: int):
    with session() as s:
        m = s.get(BackgroundMedia, mid)
        if not m:
            raise KeyError("Media not found")
    thumb = DATA_DIR / "tmp" / f"media_{mid}.jpg"
    if not thumb.exists():
        thumb.parent.mkdir(exist_ok=True)
        media.frame_jpeg(["-ss", f"{min(2.0, m.duration / 2):.1f}", "-i", str(MEDIA_DIR / m.filename)], "scale=270:-2", thumb)
    return FileResponse(thumb, media_type="image/jpeg")


@router.post("/media/generate")
def generate_media(body: dict):
    preset = body.get("preset")
    if preset not in backgrounds.PRESETS:
        raise ValueError(f"preset must be one of {list(backgrounds.PRESETS)}")
    return jobs.enqueue("media", payload={"generate": preset, "seconds": int(body.get("seconds", 75))})


@router.get("/media/pexels/search")
def pexels_search(q: str, page: int = 1):
    return backgrounds.pexels_search(q, page)


@router.post("/media/pexels/import")
def pexels_import(body: dict):
    item, category = body.get("item") or {}, body.get("category", "satisfying")
    if category not in backgrounds.MEDIA_CATEGORIES:
        raise ValueError(f"category must be one of {backgrounds.MEDIA_CATEGORIES}")
    return jobs.enqueue("media", payload={"pexels": item, "category": category})


# ---- API keys for licensed sources (stored encrypted, never sent back to the browser) ----

KEYS = ("reddit_client_id", "reddit_client_secret", "pexels_api_key")


@router.get("/keys")
def keys_status():
    return {k: bool(secure.get_key(k)) for k in KEYS}


@router.put("/keys")
def set_keys(body: dict):
    for k in KEYS:
        if k in body:
            secure.set_key(k, str(body[k] or "").strip()[:200])
    stories._token.clear()  # force a fresh Reddit token with the new credentials
    return keys_status()
