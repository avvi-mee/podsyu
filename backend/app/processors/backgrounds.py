"""Background footage for story shorts: generated loops (original, no licence issues), Pexels imports
(free licence, recorded), and the user's own uploads. Plus mood-based auto-selection."""
import random
import urllib.request
from pathlib import Path

import httpx

from app.core import secure
from app.core.config import MEDIA_DIR
from app.database.db import session
from app.models.models import BackgroundMedia
from app.processors import media

MEDIA_CATEGORIES = ["gameplay", "parkour", "satisfying", "slime", "cleaning", "cooking", "nature", "water", "calm",
                    "dark", "cinematic", "abstract"]
# Original procedural footage, rendered small then upscaled (these patterns are smooth, so it looks fine).
PRESETS = {
    "neon_plasma": ("Neon plasma", "abstract",
                    "nullsrc=s=270x480:r=30,geq=r='45+40*sin(X/23+T*1.1)+20*sin(Y/17-T*0.5)':g='18+16*sin(Y/31-T*0.9)':"
                    "b='95+70*sin((X+Y)/41+T*0.7)',scale=1080:1920:flags=bicubic,format=yuv420p"),
    "game_of_life": ("Game of Life", "satisfying",
                     "life=s=270x480:r=15:ratio=0.12:mold=10:life_color=#ffd400:death_color=#1b1240:mold_color=#3a2a80,"
                     "scale=1080:1920:flags=neighbor,fps=30,format=yuv420p"),
    "mandelbrot_zoom": ("Mandelbrot zoom", "satisfying",
                        "mandelbrot=s=540x960:rate=30:start_scale=3:end_scale=0.0005:end_pts=2400,"
                        "scale=1080:1920:flags=bicubic,format=yuv420p"),
    "dark_mist": ("Dark mist", "dark",
                  "gradients=s=540x960:r=30:c0=0x05040aff:c1=0x2a1838ff:c2=0x0b1a2aff:n=3:speed=0.004,format=yuv420p,"
                  "noise=alls=10:allf=t,gblur=sigma=6,scale=1080:1920"),
    "calm_gradient": ("Calm gradient", "calm",
                      "gradients=s=540x960:r=30:c0=0x1d3557ff:c1=0x457b9dff:c2=0xa8dadcff:c3=0xf1c0b9ff:n=4:speed=0.003,"
                      "format=yuv420p,gblur=sigma=4,scale=1080:1920"),
}
STORY_MOODS = {  # story category -> preferred footage categories
    "dark": ["dark", "cinematic", "abstract"], "scary": ["dark", "cinematic"], "mystery": ["dark", "abstract", "cinematic"],
    "funny": ["gameplay", "parkour", "satisfying", "slime"], "dark_humour": ["gameplay", "parkour", "satisfying"],
    "relationship": ["calm", "nature", "water", "cooking"], "confession": ["calm", "nature", "satisfying"],
    "life": ["satisfying", "cleaning", "cooking", "gameplay"], "unexpected": ["gameplay", "parkour", "satisfying"],
}


def register(path: Path, title: str, category: str, **extra) -> dict:
    info = media.probe(path) if extra.pop("has_audio", False) else _probe_video(path)
    with session() as s:
        m = BackgroundMedia(filename=path.name, title=title[:120], category=category, duration=round(info["duration"], 1),
                            width=info["width"], height=info["height"], **extra)
        s.add(m)
        s.flush()
        return m.to_dict()


def _probe_video(path: Path) -> dict:
    """Like media.probe but footage may have no audio track."""
    import json
    import subprocess

    r = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                        "stream=width,height:format=duration", "-of", "json", str(path)],
                       capture_output=True, text=True, creationflags=media.NO_WINDOW)
    info = json.loads(r.stdout or "{}") if r.returncode == 0 else {}
    if not info.get("streams"):
        raise media.MediaError("Not a playable video file.")
    st = info["streams"][0]
    return {"duration": float(info.get("format", {}).get("duration") or 0), "width": int(st["width"]), "height": int(st["height"])}


def unique_path(stem: str, ext: str) -> Path:
    stem = "".join(c for c in stem if c.isalnum() or c in " -_").strip()[:60] or "clip"
    dest, n = MEDIA_DIR / f"{stem}{ext}", 1
    while dest.exists():
        n += 1
        dest = MEDIA_DIR / f"{stem} ({n}){ext}"
    return dest


def generate(preset: str, seconds: int, encoder: str, progress=None) -> dict:
    if preset not in PRESETS:
        raise ValueError(f"preset must be one of {list(PRESETS)}")
    title, category, graph = PRESETS[preset]
    dest = unique_path(f"generated_{preset}", ".mp4")
    enc = media.video_encoder_args(encoder)[0]  # NVENC when available, else x264
    media.run_ffmpeg(["-f", "lavfi", "-t", str(seconds), "-i", graph, *enc, "-an", str(dest)], seconds, progress)
    return register(dest, f"{title} (generated)", category, source="generated", license="Original - generated locally",
                    attribution=None)


# ---------- Pexels (free licence: use without attribution, recorded anyway) ----------

def pexels_search(query: str, page: int = 1) -> list[dict]:
    key = secure.get_key("pexels_api_key")
    if not key:
        raise ValueError("Add your free Pexels API key in Settings (pexels.com/api) to search licensed stock videos.")
    r = httpx.get("https://api.pexels.com/videos/search", headers={"Authorization": key}, timeout=30,
                  params={"query": query[:80], "orientation": "portrait", "per_page": 15, "page": page})
    if r.status_code in (401, 403):
        raise ValueError("Pexels rejected the API key - check it in Settings.")
    r.raise_for_status()
    out = []
    for v in r.json().get("videos", []):
        files = [f for f in v.get("video_files", []) if f.get("file_type") == "video/mp4" and (f.get("height") or 0) >= (f.get("width") or 0)]
        files.sort(key=lambda f: abs((f.get("height") or 0) - 1920))
        if files:
            out.append({"id": v["id"], "url": v.get("url"), "image": v.get("image"), "duration": v.get("duration"),
                        "creator": (v.get("user") or {}).get("name"), "creator_url": (v.get("user") or {}).get("url"),
                        "file": files[0]["link"], "width": files[0].get("width"), "height": files[0].get("height")})
    return out


def pexels_import(item: dict, category: str, progress=None) -> dict:
    if not str(item.get("file", "")).startswith("https://"):
        raise ValueError("Invalid Pexels file link")
    dest = unique_path(f"pexels_{item.get('id')}", ".mp4")
    req = urllib.request.Request(item["file"], headers={"User-Agent": "podsyu"})
    with urllib.request.urlopen(req, timeout=120) as r, open(dest, "wb") as f:
        total, done = int(r.headers.get("Content-Length") or 0), 0
        while chunk := r.read(1 << 20):
            f.write(chunk)
            done += len(chunk)
            if progress and total:
                progress(done / total, f"Downloading {done / 2**20:.0f}/{total / 2**20:.0f} MB")
    return register(dest, f"Pexels #{item.get('id')} by {item.get('creator') or 'unknown'}", category, source="pexels",
                    source_url=item.get("url"), creator=item.get("creator"),
                    license="Pexels License (free to use, attribution not required)",
                    attribution=f"Video by {item.get('creator')} on Pexels" if item.get("creator") else None)


def pick_for_story(category: str) -> dict | None:
    moods = STORY_MOODS.get(category, ["satisfying", "gameplay"])
    with session() as s:
        items = [m.to_dict() for m in s.query(BackgroundMedia).all() if (MEDIA_DIR / m.filename).exists()]
    if not items:
        return None
    for mood in moods:
        hits = [m for m in items if m["category"] == mood]
        if hits:
            favs = [m for m in hits if m["favourite"]]
            return random.choice(favs or hits)
    favs = [m for m in items if m["favourite"]]
    return random.choice(favs or items)
