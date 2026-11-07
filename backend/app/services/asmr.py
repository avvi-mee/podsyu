"""ASMR Stories engine: story -> script -> local voice -> captions -> background + BGM -> vertical short."""
import logging
from pathlib import Path

from app.ai import llm, tts
from app.ai.transcribe import transcribe
from app.core.config import MEDIA_DIR, RESOLUTIONS
from app.database.db import session
from app.models.models import BackgroundMedia, Project, Short, Story
from app.processors import backgrounds, captions, media
from app.processors.render import DEFAULT_MUSIC_VOLUME, music_file, music_track, project_dir
from app.services import stories
from app.services.jobs import JobContext
from app.services.settings import get_settings

log = logging.getLogger(__name__)


def _set(model, id_, **fields):
    with session() as s:
        obj = s.get(model, id_)
        for k, v in fields.items():
            setattr(obj, k, v)
        return obj


def _merge_options(pid: int, **kv):
    """Update project options from a fresh read (never from a stale copy that would drop other keys)."""
    with session() as s:
        p = s.get(Project, pid)
        p.options = {**(p.options or {}), **kv}


def generate(ctx: JobContext, job):
    """Full one-tap pipeline. payload.redo: 'all' (default) | 'voice' (new narration) | 'render' (re-render only)."""
    settings = get_settings()
    redo = (job.payload or {}).get("redo", "all")
    with session() as s:
        p = s.get(Project, job.project_id)
        sh = s.query(Short).filter_by(project_id=p.id).first()
        story = s.get(Story, (p.options or {}).get("story_id"))
        if not story:
            raise ValueError("The story for this short was deleted.")
        p.status, p.error = "processing", None
    opts = p.options or {}
    pdir = project_dir(p.id)
    narration = pdir / "narration.wav"
    if story.permission not in ("granted", "not_required"):
        raise PermissionError("This story needs the author's permission before it can be published as a video. "
                              "Mark permission as granted, or create an original AI story inspired by it.")

    # 1. Script
    script = opts.get("script") or story.script
    if not script:
        ctx.update(0.03, "Adapting the story into a short script", stage="writing script", force=True)
        script = stories.adapt(story.title, story.body, int(opts.get("seconds", 45)), settings)["script"]
        _set(Story, story.id, script=script)
        _merge_options(p.id, script=script)

    # 2. Voice (local Kokoro TTS)
    if redo in ("all", "voice") or not narration.exists():
        cb = ctx.phase("generating voice", 0.08, 0.45)
        tts.synthesize(script, opts.get("voice"), narration, cb)
    duration = media.audio_duration(narration)

    # 3. Word timings for captions (Whisper on the clean narration = exact sync)
    if redo in ("all", "voice") or not sh.words:
        cb = ctx.phase("syncing captions", 0.45, 0.6)
        res = transcribe(narration, settings, cb, initial_prompt=script[:400], total_duration=duration, vad=False)
        words = [w for seg in res["segments"] for w in seg["words"]]
        if not words:
            raise ValueError("Could not time the captions to the narration.")
        _set(Short, sh.id, words=words, transcript=script, start=0.0, end=round(duration + 0.6, 2))

    # 4. Background footage + BGM
    ctx.update(0.62, "Choosing background video and music", stage="choosing media", force=True)
    bg_id = opts.get("background_id")
    with session() as s:
        bg = s.get(BackgroundMedia, bg_id) if bg_id else None
        bg = bg.to_dict() if bg and (MEDIA_DIR / bg.filename).exists() else None
    bg = bg or backgrounds.pick_for_story(story.category)
    if not bg:
        raise FileNotFoundError("No background videos yet. Add one in Media Library (upload, generate or import).")
    if opts.get("background_id") != bg["id"]:
        _merge_options(p.id, background_id=bg["id"])

    # 5. Render
    with session() as s:
        p, sh = s.get(Project, p.id), s.get(Short, sh.id)
    _set(Short, sh.id, status="rendering", error=None)
    try:
        res = render_story(p, sh, bg, narration, settings, ctx.phase("rendering", 0.66, 0.95))
    except Exception as e:
        _set(Short, sh.id, status="failed", error=str(e))
        raise
    _set(Short, sh.id, status="ready", **res)

    # 6. Title / description / hashtags
    if not sh.description:
        ctx.update(0.96, "Writing title & hashtags", stage="writing metadata", force=True)
        try:
            md = llm.generate_metadata(script, {"title": story.title}, settings, kind="story")
            _set(Short, sh.id, title=md["title"] or story.title[:100], description=md["description"], hashtags=md["hashtags"])
        except (ValueError, KeyError) as e:
            log.warning("Story metadata failed: %s", e)
        llm.unload(settings)
    _set(Story, story.id, status="used")
    _set(Project, p.id, status="completed", error=None)
    ctx.update(1.0, "Done - story short ready", force=True)


def render_story(project, short, bg: dict, narration: Path, settings: dict, progress=None) -> dict:
    out_w, out_h = RESOLUTIONS.get(settings["output_resolution"], (1080, 1920))
    pdir = project_dir(project.id)
    out_dir = Path(settings["output_dir"]) / str(project.id)
    out_dir.mkdir(parents=True, exist_ok=True)
    style = captions.resolve_style(short.caption_style or project.caption_style, "hormozi")
    duration = short.end
    (pdir / "story.ass").write_text(captions.build_ass(short.words or [], style, 0.0, duration, out_w, out_h), "utf-8")
    # start somewhere different in long footage so repeated stories don't look identical
    offset = (short.id * 37.0) % max(1.0, bg["duration"] - duration) if bg["duration"] > duration + 2 else 0.0
    fades = f"fade=t=in:st=0:d={media.FADE},fade=t=out:st={max(0.0, duration - media.FADE):.3f}:d={media.FADE}"
    vf = (f"scale={out_w}:{out_h}:force_original_aspect_ratio=increase,crop={out_w}:{out_h},setsar=1,"
          f"subtitles=story.ass,{fades}")
    track = music_track(project, short)
    volume = short.music_volume if short.music_volume is not None else (project.music_volume or DEFAULT_MUSIC_VOLUME)
    out = out_dir / f"short_{short.id}.mp4"
    encoder = media.encode(["-stream_loop", "-1", "-ss", f"{offset:.2f}", "-t", f"{duration:.3f}", "-i", str(MEDIA_DIR / bg["filename"]),
                            "-i", str(narration)], vf, out, duration, settings["encoder"], progress, cwd=pdir,
                           music=music_file(track, duration), music_volume=volume, voice_input=1)
    thumb = pdir / f"short_{short.id}.jpg"
    media.frame_jpeg(["-ss", f"{min(1.5, duration / 3):.2f}", "-i", str(out)], "scale=360:-2", thumb)
    note = f"story: {bg['title']}" + (f"; music: {track['title']} ({volume:.0%})" if track else "")
    return {"video_path": str(out), "thumb_path": str(thumb), "framing": f"{note}; {encoder}",
            "details": {**(short.details or {}), "background": bg["title"], "background_id": bg["id"]}}


def rerender(project, short, settings, progress=None) -> dict:
    """Re-render after caption/music changes, reusing the existing narration."""
    narration = project_dir(project.id) / "narration.wav"
    if not narration.exists() or not short.words:
        raise FileNotFoundError("Narration missing - use 'Regenerate voice' first.")
    bg_id = (project.options or {}).get("background_id")
    with session() as s:
        bg = s.get(BackgroundMedia, bg_id) if bg_id else None
        bg = bg.to_dict() if bg and (MEDIA_DIR / bg.filename).exists() else None
    bg = bg or backgrounds.pick_for_story((project.options or {}).get("category", "life"))
    if not bg:
        raise FileNotFoundError("No background videos available.")
    return render_story(project, short, bg, narration, settings, progress)
