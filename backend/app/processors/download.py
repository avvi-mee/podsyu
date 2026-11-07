"""Authorized YouTube video acquisition via yt-dlp (metadata preview + download)."""
import logging
import re
import shutil
from pathlib import Path

log = logging.getLogger(__name__)
YT_RE = re.compile(r"^https?://(www\.|m\.|music\.)?(youtube\.com/(watch\?.*v=|shorts/|live/)|youtu\.be/)[\w-]{11}")


def video_id(url: str | None) -> str | None:
    """The 11-character YouTube video id (used for the official embedded player), or None."""
    m = YT_RE.match(url or "")
    return m.group(0)[-11:] if m else None


class DownloadError(RuntimeError):
    pass


def validate_url(url: str) -> str:
    url = (url or "").strip()
    if not YT_RE.match(url):
        raise ValueError("Enter a single YouTube video URL (youtube.com/watch?v=..., youtu.be/..., or /shorts/...).")
    return url


def _friendly(e: Exception) -> str:
    m = str(e)
    rules = [
        (("not a bot",), "YouTube is temporarily blocking downloads from this network (\"confirm you're not a bot\"). "
                         "This usually clears after a few hours."),
        (("private video", "sign in", "members-only", "join this channel"), "This video is private, members-only or requires sign-in."),
        (("age",), "This video is age-restricted and cannot be downloaded without signing in."),
        (("drm",), "This video is DRM-protected and cannot be downloaded."),
        (("unavailable", "removed", "terminated"), "This video is unavailable."),
        (("javascript", "js runtime", "n challenge", "signature"), "yt-dlp could not decode YouTube's player. Update it: backend\\.venv\\Scripts\\python -m pip install -U yt-dlp"),
        (("http error 429", "too many requests"), "YouTube is rate-limiting downloads from this network. Try again later."),
    ]
    low = m.lower()
    for keys, msg in rules:
        if any(k in low for k in keys):
            return f"{msg} If you own this video, download it from YouTube Studio and use 'Upload local file' instead."
    return f"Download failed: {m[-300:]}. If you own this video you can upload the file directly instead."


def _opts(extra: dict) -> dict:
    opts = {"quiet": True, "no_warnings": True, "noprogress": True, "noplaylist": True, "socket_timeout": 30}
    if shutil.which("node"):  # newer yt-dlp needs a JavaScript runtime for YouTube; Node.js is already required
        opts["js_runtimes"] = {"node": {}}
    return {**opts, **extra}


def fetch_info(url: str, with_captions: bool = False) -> dict:
    import yt_dlp

    url = validate_url(url)
    try:
        with yt_dlp.YoutubeDL(_opts({"skip_download": True})) as ydl:
            info = ydl.extract_info(url, download=False)
    except Exception as e:
        raise DownloadError(_friendly(e))
    if info.get("is_live"):
        raise DownloadError("Live streams can't be processed until the stream has ended.")
    return {"id": info.get("id"), "title": info.get("title"), "channel": info.get("channel") or info.get("uploader"),
            "duration": info.get("duration"), "thumbnail": info.get("thumbnail"), "url": info.get("webpage_url") or url,
            "height": info.get("height"),
            **({"captions": any(k.startswith("en") for k in {**(info.get("automatic_captions") or {}), **(info.get("subtitles") or {})}),
                "manual_captions": any(k.startswith("en") for k in (info.get("subtitles") or {}))} if with_captions else {})}


def download(url: str, dest_dir: Path, progress=None) -> Path:
    import yt_dlp

    url = validate_url(url)

    def hook(d):
        if progress and d.get("status") == "downloading":
            total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
            if total:
                speed = d.get("speed") or 0
                progress(d.get("downloaded_bytes", 0) / total, f"Downloading {d.get('downloaded_bytes', 0) / 2**20:.0f}/{total / 2**20:.0f} MB"
                         + (f" at {speed / 2**20:.1f} MB/s" if speed else ""))

    opts = _opts({
        "format": "bv*[height<=1080][ext=mp4]+ba[ext=m4a]/bv*[height<=1080]+ba/b[height<=1080]/b",
        "format_sort": ["res:1080", "vcodec:h264", "acodec:m4a"],  # H.264 decodes fast everywhere (AV1 can be slow)
        "merge_output_format": "mp4", "outtmpl": str(dest_dir / "source.%(ext)s"),
        "progress_hooks": [hook], "concurrent_fragment_downloads": 4, "retries": 5,
    })
    from app.services.jobs import Cancelled

    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=True)
            path = Path(ydl.prepare_filename(info)).with_suffix(".mp4")
    except Cancelled:
        raise
    except Exception as e:
        if isinstance(e.__context__, Cancelled) or "Cancelled" in type(e).__name__:
            raise Cancelled() from e  # yt-dlp may wrap exceptions raised by our progress hook
        raise DownloadError(_friendly(e))
    if not path.exists():
        found = sorted(dest_dir.glob("source.*"), key=lambda p: p.stat().st_size, reverse=True)
        if not found:
            raise DownloadError("Download finished but the video file was not found.")
        path = found[0]
    return path
