"""Processing pipeline. Every stage skips work that already exists, so retries resume where they failed."""
import json
import logging
import shutil
from pathlib import Path

from app.ai import llm
from app.ai.transcribe import sentences_from_segments, transcribe
from app.database.db import session
from app.models.models import Project, Publication, Short
from app.processors import download, media
from app.processors.render import load_words, project_dir, render_short
from app.services.jobs import Cancelled, JobContext
from app.services.settings import get_settings

log = logging.getLogger(__name__)


def _set(model, id_, **fields):
    with session() as s:
        obj = s.get(model, id_)
        if obj is None:
            raise ValueError(f"{model.__name__} {id_} was deleted")
        for k, v in fields.items():
            setattr(obj, k, v)
        return obj


def project_options(p: Project, settings: dict) -> dict:
    return {"min_duration": settings["min_duration"], "max_duration": settings["max_duration"],
            "num_shorts": settings["num_shorts"], "category": "any", "strategy": "balanced",
            "auto_delete_source": settings["auto_cleanup_source"], **(p.options or {})}


def delete_short_files(sh: Short):
    for f in (sh.video_path, sh.thumb_path):
        if f:
            Path(f).unlink(missing_ok=True)


def process_project(ctx: JobContext, job):
    settings = get_settings()
    payload = job.payload or {}
    p = _set(Project, job.project_id, status="processing", error=None)
    pdir = project_dir(p.id)

    # 1-2. Acquire the source video
    src = Path(p.source_path) if p.source_path else None
    if not src or not src.exists():
        if p.source_type == "youtube" and p.source_url:
            src = download.download(p.source_url, pdir, ctx.phase("downloading", 0.0, 0.15))
            p = _set(Project, p.id, source_path=str(src), source_deleted=False)
        else:
            raise FileNotFoundError("The source video file is missing. Upload the video again.")
    ctx.update(0.15, "Validating video file", stage="validating", force=True)
    info = media.probe(src)
    if info["duration"] < 20:
        raise ValueError("Video is shorter than 20 seconds - nothing to cut.")
    p = _set(Project, p.id, **info)

    # 3-4. Audio + transcript
    tpath = pdir / "transcript.json"
    if not tpath.exists():
        audio = pdir / "audio.wav"
        if not audio.exists():
            media.extract_audio(src, audio, info["duration"], ctx.phase("extracting audio", 0.15, 0.2))
        cb = ctx.phase("transcribing", 0.2, 0.5)
        prompt = f"{p.title}." + (f" {p.channel}." if p.channel else "")
        result = transcribe(audio, settings, cb, initial_prompt=prompt, total_duration=info["duration"])
        if not result["segments"]:
            raise ValueError("No speech was detected in this video.")
        tpath.write_text(json.dumps(result), "utf-8")
        audio.unlink(missing_ok=True)  # 16 kHz WAV is only needed for transcription
        p = _set(Project, p.id, language=result["language"])
    transcript = json.loads(tpath.read_text("utf-8"))
    sentences = sentences_from_segments(transcript["segments"])
    meta = {"title": p.title, "channel": p.channel}

    # 5-7. AI moment detection, validation and ranking
    with session() as s:
        existing = s.query(Short).filter_by(project_id=p.id).count()
    if payload.get("reanalyze") or existing == 0:
        opts = project_options(p, settings)
        clips = llm.find_moments(sentences, opts, meta, settings, ctx.phase("finding best moments", 0.5, 0.64))
        if not clips:
            raise ValueError(f"The AI found no self-contained moments of {opts['min_duration']}-{opts['max_duration']}s. "
                             "Try a wider duration range, another strategy, or a larger Ollama model.")
        with session() as s:
            for old in s.query(Short).filter_by(project_id=p.id).all():
                if not s.query(Publication).filter_by(short_id=old.id).first():
                    delete_short_files(old)
                    s.delete(old)
            for rank, c in enumerate(clips):
                s.add(Short(project_id=p.id, rank=rank, start=c["start"], end=c["end"], transcript=c["transcript"],
                            hook=c.get("hook", ""), title=c.get("title", "")[:100], category=c.get("category", ""),
                            reason=c.get("reason", ""), score=c["score"]))

    # 11. Titles, descriptions, hashtags (done while the LLM is loaded, before GPU rendering)
    with session() as s:
        todo = s.query(Short).filter_by(project_id=p.id, description="").order_by(Short.rank).all()
    cb = ctx.phase("writing titles & hashtags", 0.64, 0.72)
    for i, sh in enumerate(todo):
        cb(i / len(todo), f"Writing metadata for short {i + 1}/{len(todo)}")
        try:
            md = llm.generate_metadata(sh.transcript, meta, settings)
            _set(Short, sh.id, title=md["title"] or sh.title, description=md["description"], hashtags=md["hashtags"])
        except (ValueError, KeyError) as e:
            log.warning("Metadata generation failed for short %s: %s", sh.id, e)
    llm.unload(settings)  # free VRAM for NVENC / next transcription

    # 8-10, 12. Cut, reframe, caption and save each short
    with session() as s:
        q = s.query(Short).filter_by(project_id=p.id).order_by(Short.rank)
        shorts = q.all() if payload.get("rerender") else q.filter(Short.status != "ready").all()
    failed = []
    for i, sh in enumerate(shorts):
        lo = 0.72 + 0.28 * i / len(shorts)
        cb = ctx.phase(f"rendering short {i + 1}/{len(shorts)}", lo, lo + 0.28 / len(shorts))
        try:
            render_and_save(p, sh.id, settings, cb)
        except Cancelled:
            raise
        except Exception as e:
            failed.append(f"#{i + 1}: {e}")
    if shorts and len(failed) == len(shorts):
        raise RuntimeError("All shorts failed to render. " + failed[0])

    with session() as s:  # re-read: the user may have toggled auto-delete while this job was running
        auto_delete = project_options(s.get(Project, p.id), settings)["auto_delete_source"]
    if auto_delete and not failed:  # keep the source if anything failed, so it can be retried
        delete_source(p.id)
    _set(Project, p.id, status="completed", error=("Some shorts failed: " + "; ".join(failed)) if failed else None)
    try:
        from app.services import autopilot

        autopilot.run(p.id)
    except Exception:  # never fail a finished project because scheduling failed; the plan shows the error
        log.exception("Autopilot failed for project %s", p.id)
    with session() as s:
        n = s.query(Short).filter_by(project_id=p.id, status="ready").count()
    ctx.update(1.0, f"Done - {n} shorts ready" + (" (source video deleted)" if auto_delete and not failed else ""), force=True)


def render_and_save(project: Project, short_id: int, settings: dict, progress=None):
    sh = _set(Short, short_id, status="rendering", error=None)
    try:
        res = render_short(project, sh, settings, progress)
    except Cancelled:
        _set(Short, short_id, status="ready" if sh.video_path else "pending")
        raise
    except Exception as e:
        log.exception("Render failed for short %s", short_id)
        _set(Short, short_id, status="failed", error=str(e))
        raise
    _set(Short, short_id, status="ready", **res)


def _project_and_short(job):
    with session() as s:
        sh = s.get(Short, job.short_id)
        if not sh:
            raise ValueError("Short was deleted")
        return s.get(Project, sh.project_id), sh


def render_one(ctx: JobContext, job):
    p, sh = _project_and_short(job)
    settings = get_settings()
    if p.engine == "asmr":  # story shorts re-render from their narration + background
        from app.services import asmr

        _set(Short, sh.id, status="rendering", error=None)
        try:
            res = asmr.rerender(p, sh, settings, ctx.phase("rendering", 0.0, 1.0))
        except Exception as e:
            _set(Short, sh.id, status="failed", error=str(e))
            raise
        _set(Short, sh.id, status="ready", **res)
        return
    if p.engine == "creator" and not (p.source_path and Path(p.source_path).exists()):
        if not (p.source_type == "youtube" and (p.options or {}).get("authorized")):
            raise FileNotFoundError("Rendering needs the authorized video file.")
        src = download.download(p.source_url, project_dir(p.id), ctx.phase("downloading authorized media", 0.0, 0.3))
        p = _set(Project, p.id, source_path=str(src), source_deleted=False, **media.probe(src))
    if p.engine == "creator" and (sh.details or {}).get("analysis") == "transcript-only" and not sh.words:
        recaption(ctx, job)  # published captions only have cue-level timing: Whisper the clip for word-synced captions
    else:
        render_and_save(p, sh.id, settings, ctx.phase("rendering", 0.0, 0.92))
    if p.engine == "creator" and not sh.description:  # candidates get titles/hashtags once approved & rendered
        ctx.update(0.95, "Writing title & hashtags", force=True)
        try:
            md = llm.generate_metadata(sh.transcript, {"title": p.title, "channel": (p.options or {}).get("creator") or p.channel},
                                       settings, kind="creator")
            _set(Short, sh.id, title=md["title"] or sh.title, description=md["description"], hashtags=md["hashtags"])
        except (ValueError, KeyError) as e:
            log.warning("Creator metadata failed: %s", e)


def recaption(ctx: JobContext, job):
    """Re-transcribe just this clip for the most accurate captions, then re-render."""
    settings = get_settings()
    p, sh = _project_and_short(job)
    if not p.source_path or not Path(p.source_path).exists():
        raise FileNotFoundError("Source video was deleted - captions can't be regenerated.")
    pad = 1.0
    a, b = max(0.0, sh.start - pad), sh.end + pad
    wav = project_dir(p.id) / f"clip_{sh.id}.wav"
    ctx.update(0.02, "Extracting clip audio", stage="regenerating captions", force=True)
    media.run_ffmpeg(["-ss", f"{a:.3f}", "-t", f"{b - a:.3f}", "-i", p.source_path, "-vn", "-ac", "1", "-ar", "16000", str(wav)])
    try:
        cb = ctx.phase("transcribing clip", 0.05, 0.45)
        # No VAD: on a short, speech-dense excerpt it can drop quieter voices (e.g. a remote interviewer).
        # Title only as the prompt: giving Whisper the clip's own transcript makes it skip most of the speech.
        res = transcribe(wav, settings, cb, initial_prompt=f"{p.title}.", total_duration=b - a, offset=a, vad=False)
    finally:
        wav.unlink(missing_ok=True)
    words = [w for seg in res["segments"] for w in seg["words"]]
    if not words:
        raise ValueError("No speech detected in this clip.")
    inside = [w for w in words if w["e"] > sh.start and w["s"] < sh.end]
    before = [w for w in load_words(p.id) if w["e"] > sh.start and w["s"] < sh.end]
    # The new pass lost speech: keep the original captions. Words from published captions only have cue-spread timing,
    # so Whisper's real timing wins unless it heard much less.
    keep = 0.6 if (sh.details or {}).get("analysis") == "transcript-only" else 0.8
    if len(inside) < keep * len(before):
        ctx.update(0.45, f"New transcription found fewer words ({len(inside)} vs {len(before)}); kept original captions", force=True)
        _set(Short, sh.id, words=None)
    else:
        _set(Short, sh.id, words=words, transcript=" ".join(w["w"] for w in inside))
    render_and_save(p, sh.id, settings, ctx.phase("rendering", 0.45, 1.0))


def regenerate_metadata(ctx: JobContext, job):
    settings = get_settings()
    p, sh = _project_and_short(job)
    field = (job.payload or {}).get("field", "all")
    ctx.update(0.1, f"Generating new {field}", stage="writing metadata", force=True)
    kind = {"creator": "creator", "asmr": "story", "cutting": "cutting"}.get(p.engine or "", "podcast")
    md = llm.generate_metadata(sh.transcript, {"title": p.title, "channel": p.channel}, settings, temperature=0.75, kind=kind)
    fields = ["title", "description", "hashtags"] if field == "all" else [field]
    _set(Short, sh.id, **{f: md[f] for f in fields if md.get(f)})


def delete_source(project_id: int):
    """Remove the large source video + intermediate audio; transcript and finished shorts are kept."""
    with session() as s:
        p = s.get(Project, project_id)
        if p.source_path:
            Path(p.source_path).unlink(missing_ok=True)
        p.source_deleted = True
    d = project_dir(project_id)
    for f in d.glob("*.wav"):
        f.unlink(missing_ok=True)
    for f in d.glob("source.*"):
        f.unlink(missing_ok=True)


def delete_project_files(project_id: int, output_dir: str):
    shutil.rmtree(project_dir(project_id), ignore_errors=True)
    shutil.rmtree(Path(output_dir) / str(project_id), ignore_errors=True)
