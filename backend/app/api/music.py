"""BGM library: files live in data/music, metadata (title, credit, licence, category) in the database.
Snippets are short loopable cuts of a full track (parent_id), created from its catchiest section."""
import random
import re
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import FileResponse

from app.core.config import MUSIC_DIR
from app.database.db import session
from app.models.models import MusicTrack, Project, Short
from app.processors import audio, media

router = APIRouter(prefix="/api")
AUDIO_EXTS = {".mp3", ".wav", ".m4a", ".aac", ".ogg", ".flac"}
VIDEO_EXTS = {".mp4", ".mov", ".mkv", ".webm"}
CATEGORIES = ["funny", "suspense", "dark", "horror", "relaxing", "emotional", "cinematic", "mysterious", "inspirational"]


def _sync():
    """Register audio files dropped into data/music by hand (e.g. from the YouTube Audio Library)."""
    with session() as s:
        known = {t.filename for t in s.query(MusicTrack)}
        for f in sorted(MUSIC_DIR.iterdir()):
            if f.is_file() and f.suffix.lower() in AUDIO_EXTS and f.name not in known:
                try:
                    dur = media.audio_duration(f)
                except media.MediaError:
                    continue
                s.add(MusicTrack(filename=f.name, title=f.stem.replace("_", " "), duration=round(dur, 1)))


@router.get("/music")
def list_music():
    _sync()
    with session() as s:
        return [t.to_dict() for t in s.query(MusicTrack).order_by(MusicTrack.title)]


def _unique(stem: str, ext: str) -> Path:
    dest, n = MUSIC_DIR / f"{stem}{ext}", 1
    while dest.exists():
        n += 1
        dest = MUSIC_DIR / f"{stem} ({n}){ext}"
    return dest


@router.post("/music/upload")
async def upload_music(request: Request, filename: str, license: str = "", source_url: str = ""):
    """Add audio you own or are licensed to use. Video files are accepted: their audio track is extracted."""
    ext = Path(filename).suffix.lower()
    if ext not in AUDIO_EXTS | VIDEO_EXTS:
        raise ValueError("Use an audio file (MP3, WAV, M4A, AAC, OGG, FLAC) or a video to extract audio from.")
    stem = re.sub(r"[^\w\- ]", "", Path(filename).stem).strip()[:80] or "track"
    raw = _unique(stem, ext if ext in AUDIO_EXTS else ext + ".src")
    with open(raw, "wb") as f:
        async for chunk in request.stream():
            f.write(chunk)
    dest = raw
    try:
        if ext in VIDEO_EXTS:
            dest = _unique(stem, ".mp3")
            media.run_ffmpeg(["-i", str(raw), "-vn", "-c:a", "libmp3lame", "-q:a", "2", str(dest)])
            raw.unlink(missing_ok=True)
        dur = media.audio_duration(dest)
    except media.MediaError:
        raw.unlink(missing_ok=True)
        dest.unlink(missing_ok=True)
        raise ValueError("No usable audio found in that file.")
    with session() as s:
        t = MusicTrack(filename=dest.name, title=stem.replace("_", " "), duration=round(dur, 1),
                       license=license[:200] or None, source_url=source_url[:500] or None)
        s.add(t)
        s.flush()
        return t.to_dict()


@router.patch("/music/{tid}")
def update_music(tid: int, body: dict):
    with session() as s:
        t = s.get(MusicTrack, tid)
        if not t:
            raise KeyError("Track not found")
        for k, n in (("title", 100), ("credit", 500), ("license", 200), ("source_url", 500)):
            if k in body:
                v = str(body[k] or "").strip()[:n]
                setattr(t, k, v or (t.title if k == "title" else None if k != "credit" else ""))
        if "category" in body:
            if body["category"] not in CATEGORIES + [None, ""]:
                raise ValueError(f"category must be one of {CATEGORIES}")
            t.category = body["category"] or None
        if "favourite" in body:
            t.favourite = bool(body["favourite"])
        if "clip_start" in body or "length" in body:  # trim a snippet: re-cut it from its parent
            if t.parent_id is None:
                raise ValueError("Only snippets can be trimmed")
            parent = s.get(MusicTrack, t.parent_id)
            start = float(body.get("clip_start", t.clip_start or 0))
            length = float(body.get("length", t.duration))
            if not (15 <= length <= 30) or not (0 <= start <= max(0.0, parent.duration - length)):
                raise ValueError("Snippets must be 15-30 s long and inside the track")
            audio.cut_snippet(MUSIC_DIR / parent.filename, start, length, MUSIC_DIR / t.filename)
            t.clip_start, t.duration = round(start, 2), round(length, 2)
        return t.to_dict()


@router.post("/music/{tid}/snippets")
def make_snippets(tid: int):
    """Detect the catchiest part of a track and save 15 / 20 / 30 s loopable snippets of it."""
    with session() as s:
        t = s.get(MusicTrack, tid)
        if not t or t.parent_id is not None:
            raise KeyError("Track not found")
        src, info = MUSIC_DIR / t.filename, t.to_dict()
        for old in s.query(MusicTrack).filter_by(parent_id=tid).all():  # replace earlier snippets
            (MUSIC_DIR / old.filename).unlink(missing_ok=True)
            s.delete(old)
    if info["duration"] < 16:
        raise ValueError("Track is too short to cut 15 s+ snippets from")
    out = []
    for length in audio.SNIPPET_LENGTHS:
        if length > info["duration"] - 1:
            continue
        start, score = audio.catchy_start(src, length)
        dest = _unique(f"{Path(info['filename']).stem}_hook{length}s", ".mp3")
        audio.cut_snippet(src, start, length, dest)
        out.append(MusicTrack(filename=dest.name, title=f"{info['title']} - hook {length}s", duration=float(length),
                              credit=info["credit"], category=info["category"], license=info["license"],
                              source_url=info["source_url"], parent_id=tid, clip_start=start))
    with session() as s:
        s.add_all(out)
        s.flush()
        return [t.to_dict() for t in out]


@router.delete("/music/{tid}")
def delete_music(tid: int):
    with session() as s:
        t = s.get(MusicTrack, tid)
        if not t:
            raise KeyError("Track not found")
        doomed = [t] + s.query(MusicTrack).filter_by(parent_id=tid).all()
        files = [x.filename for x in doomed]
        for x in doomed:
            for model in (Project, Short):  # anything using it goes back to "no music"
                s.query(model).filter(model.music == str(x.id)).update({"music": None})
            s.delete(x)
    for f in files:
        (MUSIC_DIR / f).unlink(missing_ok=True)
    return {"ok": True}


@router.get("/music/{tid}/file")
def music_file(tid: int):
    with session() as s:
        t = s.get(MusicTrack, tid)
        if not t or not (MUSIC_DIR / t.filename).exists():
            raise KeyError("Track not found")
        return FileResponse(MUSIC_DIR / t.filename)


def pick_for_category(category: str | None) -> str | None:
    """Auto-select BGM for a story category: favourites first, then any track tagged with the category."""
    mood = {"dark": ["dark", "suspense", "horror"], "scary": ["horror", "dark", "suspense"], "horror": ["horror", "dark"],
            "funny": ["funny"], "dark_humour": ["funny", "mysterious"], "relationship": ["emotional", "relaxing"],
            "confession": ["emotional", "mysterious"], "mystery": ["mysterious", "suspense"],
            "life": ["inspirational", "relaxing", "emotional"]}.get(category or "", [category or ""])
    _sync()
    with session() as s:
        tracks = [t for t in s.query(MusicTrack).filter(MusicTrack.parent_id.is_(None)) if t.category in mood
                  and (MUSIC_DIR / t.filename).exists()]
    if not tracks:
        return None
    favs = [t for t in tracks if t.favourite]
    return str(random.choice(favs or tracks).id)


def validate_choice(value) -> str | None:
    """'none' / None / a track id (as text)."""
    if value is None or value == "none":
        return value
    with session() as s:
        if not str(value).isdigit() or not s.get(MusicTrack, int(value)):
            raise ValueError("Unknown music track")
    return str(value)


def validate_volume(value) -> float | None:
    if value is None:
        return None
    v = float(value)
    if not 0 <= v <= 0.6:
        raise ValueError("Music volume must be between 0 and 0.6")
    return v
