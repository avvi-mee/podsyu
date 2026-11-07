"""Render one vertical short: cut + reframe + burned captions, plus a thumbnail."""
import json
from pathlib import Path

from app.core.config import MUSIC_DIR, PROJECTS_DIR, RESOLUTIONS
from app.processors import captions, media, reframe


def project_dir(project_id: int) -> Path:
    d = PROJECTS_DIR / str(project_id)
    d.mkdir(parents=True, exist_ok=True)
    return d


def load_words(project_id: int) -> list[dict]:
    path = project_dir(project_id) / "transcript.json"
    if not path.exists():
        raise FileNotFoundError("Transcript not found for this project - re-run processing.")
    data = json.loads(path.read_text("utf-8"))
    return [w for seg in data["segments"] for w in seg["words"]]


def clip_words(short, project_id: int) -> list[dict]:
    words = short.words or load_words(project_id)
    return [w for w in words if w["e"] > short.start and w["s"] < short.end]


def video_filter(project, short, out_w: int, out_h: int, steps=None) -> tuple[str, str]:
    """Return (crop+scale filter, framing description) for this short."""
    W, H = project.width, project.height
    cw = reframe.crop_width(W, H)
    if cw >= W - 2:  # already vertical/narrow: fit and pad
        return (f"scale={out_w}:{out_h}:force_original_aspect_ratio=decrease,"
                f"pad={out_w}:{out_h}:(ow-iw)/2:(oh-ih)/2,setsar=1"), "fit (source not landscape)"
    if (project.options or {}).get("layout") == "full":  # gaming/on-screen info: whole frame over a blurred fill
        return (f"split=2[fillsrc][fg0];[fillsrc]scale={out_w}:{out_h}:force_original_aspect_ratio=increase,"
                f"crop={out_w}:{out_h},boxblur=20:3[fill];[fg0]scale={out_w}:-2[fg];[fill][fg]overlay=(W-w)/2:(H-h)/2,"
                f"setsar=1"), "full frame (gameplay kept, blurred fill)"
    if short.crop_mode == "manual":
        steps, desc = [(0.0, round(short.crop_x * (W - cw)))], f"manual crop at {short.crop_x:.0%}"
    elif steps is None:
        steps, desc = reframe.plan(project.source_path, short.start, short.end, W, H)
    else:
        desc = short.framing or "auto"
    return f"crop={cw}:{H}:{reframe.crop_x_expr(steps)}:0,scale={out_w}:{out_h}:flags=lanczos,setsar=1", desc


def render_short(project, short, settings: dict, progress=None) -> dict:
    if not project.source_path or not Path(project.source_path).exists():
        raise FileNotFoundError("Source video was deleted - re-import the video to re-render this short.")
    out_w, out_h = RESOLUTIONS.get(settings["output_resolution"], (1080, 1920))
    style = captions.resolve_style(short.caption_style or project.caption_style, settings["default_caption_preset"])
    pdir = project_dir(project.id)
    out_dir = Path(settings["output_dir"]) / str(project.id)
    out_dir.mkdir(parents=True, exist_ok=True)

    if progress:
        progress(0.02, "Finding speakers for vertical framing")
    vf_crop, framing = video_filter(project, short, out_w, out_h)
    ass_name = f"short_{short.id}.ass"
    (pdir / ass_name).write_text(captions.build_ass(clip_words(short, project.id), style, short.start, short.end, out_w, out_h), "utf-8")

    duration = short.end - short.start
    out = out_dir / f"short_{short.id}.mp4"
    track = music_track(project, short)
    volume = short.music_volume if short.music_volume is not None else (project.music_volume or DEFAULT_MUSIC_VOLUME)
    fades = f"fade=t=in:st=0:d={media.FADE},fade=t=out:st={max(0.0, duration - media.FADE):.3f}:d={media.FADE}"
    # cwd=pdir so the subtitles filter gets a plain relative path (no Windows drive-colon escaping)
    encoder = media.encode(["-ss", f"{short.start:.3f}", "-t", f"{duration:.3f}", "-i", project.source_path],
                           f"{vf_crop},subtitles={ass_name},{fades}", out, duration, settings["encoder"],
                           (lambda f: progress(0.1 + 0.85 * f, "Rendering video")) if progress else None, cwd=pdir,
                           music=music_file(track, duration), music_volume=volume)
    thumb = pdir / f"short_{short.id}.jpg"
    media.frame_jpeg(["-ss", f"{min(1.5, duration / 3):.2f}", "-i", str(out)], "scale=360:-2", thumb)
    music_note = f"; music: {track['title']} ({volume:.0%})" if track else ""
    return {"video_path": str(out), "thumb_path": str(thumb), "framing": f"{framing}; {encoder}{music_note}"}


DEFAULT_MUSIC_VOLUME = 0.10  # background music sits low under the voice (and ducks further while people talk)


def music_track(project, short) -> dict | None:
    """The background track for this short: its own choice, else the project's. None = no music."""
    from app.database.db import session
    from app.models.models import MusicTrack

    choice = short.music if short.music is not None else project.music
    if not choice or choice == "none" or not str(choice).isdigit():
        return None
    with session() as s:
        t = s.get(MusicTrack, int(choice))
        if not t or not (MUSIC_DIR / t.filename).exists():
            return None  # track was deleted: render without music rather than fail
        play = t
        if t.parent_id is None:  # a full track: use its catchiest snippet, looped to fit, when one exists
            snip = (s.query(MusicTrack).filter_by(parent_id=t.id).order_by(MusicTrack.duration).all())
            play = next((x for x in snip if 19 <= x.duration <= 21 and (MUSIC_DIR / x.filename).exists()), t)
        parent = s.get(MusicTrack, t.parent_id) if t.parent_id else t
        return {"path": MUSIC_DIR / play.filename, "title": play.title, "credit": t.credit or (parent.credit if parent else "")}


def music_file(track: dict | None, duration: float) -> str | None:
    """Path to music at least `duration` long (short snippets are looped with crossfades)."""
    if not track:
        return None
    from app.processors.audio import extend_to

    return extend_to(track["path"], duration)


def caption_preview(project, short, style: dict, settings: dict, out: Path):
    """Single frame with captions burned exactly as the renderer would."""
    out_w, out_h = RESOLUTIONS.get(settings["output_resolution"], (1080, 1920))
    out.parent.mkdir(parents=True, exist_ok=True)
    style = {**style, "animation": "none"}  # a still frame at t=0 would catch fade/pop at their first frame
    if project is None or short is None or not project.source_path or not Path(project.source_path).exists():
        sample = "This is how your captions will look on every short you generate".split()
        words = [{"w": w, "s": 0.3 * i, "e": 0.3 * i + 0.28} for i, w in enumerate(sample)]
        t = words[2]["s"] + 0.01
        ass = captions.build_ass(words, style, t, t + 10, out_w, out_h)
        (out.parent / "preview.ass").write_text(ass, "utf-8")
        media.frame_jpeg(["-f", "lavfi", "-i", f"gradients=s={out_w}x{out_h}:c0=0x1d1530:c1=0x0b2a24:x0=0:y0=0:x1={out_w}:y1={out_h}"],
                         "subtitles=preview.ass", out, cwd=out.parent)
        return
    words = clip_words(short, project.id)
    pick = words[min(len(words) - 1, 4)] if words else {"s": short.start + 1}
    t = pick["s"] + 0.01
    steps = None
    if short.crop_mode != "manual":  # frame only the previewed moment instead of analysing the whole clip
        found, _ = reframe.plan(project.source_path, t, t + 1.5, project.width, project.height)
        steps = [(0.0, found[0][1])]
    vf_crop, _ = video_filter(project, short, out_w, out_h, steps=steps)
    ass = captions.build_ass(words, style, t, short.end, out_w, out_h)
    (out.parent / "preview.ass").write_text(ass, "utf-8")
    media.frame_jpeg(["-ss", f"{t:.3f}", "-i", project.source_path], f"{vf_crop},subtitles=preview.ass", out, cwd=out.parent)
