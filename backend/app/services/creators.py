"""Famous Creators Clipper: find complete entertaining scenes, then the best 10-30 s moments inside them.

Signals: transcript (LLM), audio reaction peaks (loud laughs/screams/hype) and visual activity (cuts, motion,
faces) when authorized media is available. Without media it falls back to the video's published captions and
says so - transcript-only analysis can't see facial expressions or visual jokes."""
import html
import json
import logging
import re
import subprocess
import tempfile
from pathlib import Path

import numpy as np

from app.ai import llm
from app.ai.transcribe import sentences_from_segments, transcribe
from app.database.db import session
from app.models.models import Project, Publication, Short
from app.processors import download, media
from app.processors.render import project_dir
from app.services.jobs import JobContext
from app.services.pipeline import delete_short_files
from app.services.settings import get_settings

log = logging.getLogger(__name__)
MOMENT_CATEGORIES = ["funniest moment", "unexpected reaction", "funny facial expression", "gaming reaction",
                     "unexpected fail", "surprising moment", "crazy situation", "emotional reaction", "exciting moment",
                     "memorable quote"]
LENGTHS = {10: (8, 13), 15: (12, 18), 20: (16, 24), 30: (24, 34)}  # target -> allowed range (s)


def _set(model, id_, **fields):
    with session() as s:
        obj = s.get(model, id_)
        for k, v in fields.items():
            setattr(obj, k, v)
        return obj


# ---------------- signals ----------------

def audio_peaks(wav: Path) -> np.ndarray:
    """Per-second reaction intensity 0..1 (loudness well above the video's typical level)."""
    import wave

    with wave.open(str(wav), "rb") as w:
        sr = w.getframerate()
        a = np.frombuffer(w.readframes(w.getnframes()), np.int16).astype(np.float32) / 32768
    secs = len(a) // sr
    rms = np.array([np.sqrt(np.mean(a[i * sr:(i + 1) * sr] ** 2)) + 1e-6 for i in range(secs)])
    db = 20 * np.log10(rms)
    base, spread = np.median(db), np.percentile(db, 90) - np.median(db) + 1e-6
    return np.clip((db - base) / (spread * 1.6), 0, 1)


def visual_activity(src: str, duration: float, fps: float = 2) -> tuple[np.ndarray, np.ndarray]:
    """Per-second motion (0..1) and camera-cut flags, from a tiny low-res decode of the video."""
    w, h = 96, 54
    cmd = ["ffmpeg", "-v", "error", "-i", src, "-vf", f"fps={fps},scale={w}:{h},format=gray", "-f", "rawvideo", "-"]
    proc = subprocess.run(cmd, capture_output=True, creationflags=media.NO_WINDOW)
    frames = np.frombuffer(proc.stdout, np.uint8)[: (len(proc.stdout) // (w * h)) * w * h].reshape(-1, h, w).astype(np.int16)
    secs = int(duration) + 1
    motion, cuts = np.zeros(secs), np.zeros(secs)
    if len(frames) > 1:
        diffs = np.abs(np.diff(frames, axis=0)).mean(axis=(1, 2))
        for i, d in enumerate(diffs):
            sec = min(secs - 1, int((i + 1) / fps))
            motion[sec] = max(motion[sec], d)
            cuts[sec] = max(cuts[sec], float(d > 32))
        motion = np.clip(motion / (np.percentile(motion, 95) + 1e-6), 0, 1)
    return motion, cuts


# ---------------- transcripts ----------------

def captions_transcript(url: str, dest: Path) -> list[dict]:
    """Words from the video's published captions (no media download). Cue-level timing is spread over words."""
    import yt_dlp

    opts = {**download._opts({}), "skip_download": True, "writesubtitles": True, "writeautomaticsub": True,
            "subtitleslangs": ["en", "en-orig", "en-US"], "subtitlesformat": "vtt", "outtmpl": str(dest / "captions")}
    with yt_dlp.YoutubeDL(opts) as ydl:
        ydl.extract_info(download.validate_url(url), download=True)
    files = sorted(dest.glob("captions*.vtt"))
    if not files:
        raise FileNotFoundError("This video has no accessible captions. Upload an authorized copy of the video instead.")
    words, seen = [], set()
    ts = re.compile(r"(\d+):(\d+):(\d+\.\d+) --> (\d+):(\d+):(\d+\.\d+)")
    to_s = lambda h, m, s: int(h) * 3600 + int(m) * 60 + float(s)  # noqa: E731
    cue = None
    for line in files[0].read_text("utf-8", errors="replace").splitlines():
        m = ts.match(line)
        if m:
            cue = (to_s(*m.groups()[:3]), to_s(*m.groups()[3:]))
            continue
        # strip timing tags, decode &gt; etc., and drop ">>" speaker-change markers
        text = html.unescape(re.sub(r"<[^>]+>", "", line)).replace(">>", " ").strip()
        text = re.sub(r"\s+", " ", text)
        if cue and text and text not in seen:  # auto-captions repeat the previous line; keep new text only
            seen.add(text)
            toks = text.split()
            step = (cue[1] - cue[0]) / max(1, len(toks))
            words += [{"w": t, "s": round(cue[0] + i * step, 2), "e": round(cue[0] + (i + 1) * step, 2), "p": 1.0}
                      for i, t in enumerate(toks)]
    if not words:
        raise FileNotFoundError("The captions were empty.")
    return [{"start": words[0]["s"], "end": words[-1]["e"], "text": " ".join(w["w"] for w in words), "words": words}]


# ---------------- LLM passes ----------------

SCENE_SCHEMA = {"type": "object", "properties": {"scenes": {"type": "array", "items": {"type": "object", "properties": {
    "start_index": {"type": "integer"}, "end_index": {"type": "integer"}, "name": {"type": "string"},
    "category": {"type": "string", "enum": MOMENT_CATEGORIES}, "score": {"type": "integer"}},
    "required": ["start_index", "end_index", "name", "category", "score"]}}}, "required": ["scenes"]}
MOMENT_SCHEMA = {"type": "object", "properties": {"moments": {"type": "array", "items": {"type": "object", "properties": {
    "start_index": {"type": "integer"}, "end_index": {"type": "integer"}, "title": {"type": "string"},
    "category": {"type": "string", "enum": MOMENT_CATEGORIES}, "why": {"type": "string"},
    "humor": {"type": "integer"}, "surprise": {"type": "integer"}, "reaction": {"type": "integer"},
    "hook": {"type": "integer"}, "completeness": {"type": "integer"}, "context": {"type": "integer"}},
    "required": ["start_index", "end_index", "title", "category", "why", "humor", "surprise", "reaction", "hook",
                 "completeness", "context"]}}}, "required": ["moments"]}
SYSTEM = "You are a viral short-form editor for entertainment, gaming and streamer content. Answer only with JSON."


def _line(s: dict, peaks: np.ndarray | None) -> str:
    tag = ""
    if peaks is not None and len(peaks):
        seg = peaks[int(s["start"]):int(s["end"]) + 1]
        if len(seg) and seg.max() > 0.75:
            tag = " [LOUD REACTION]"
    return f"[{s['i']}] ({s['start']:.0f}s){tag} {s['text']}"


def find_scenes(S: list[dict], meta: dict, settings: dict, peaks, say) -> list[dict]:
    scenes, win, words = [], [], 0
    windows = []
    for s in S:
        win.append(s)
        words += len(s["text"].split())
        if words > 1200:
            windows.append(win)
            win, words = win[-5:], 0
    if win:
        windows.append(win)
    for k, w in enumerate(windows):
        say(0.4 * k / len(windows), f"AI is watching for entertaining scenes {k + 1}/{len(windows)}")
        prompt = f"""Video: "{meta['title']}" by {meta['creator'] or 'a creator'} (category: {meta['category'] or 'entertainment'}).
Lines are speech: [index] (time) text. [LOUD REACTION] marks screaming/laughing/hype in the audio.
Find up to 4 complete entertaining SCENES (20-120 seconds each): funny bits, wild reactions, fails, surprises,
crazy situations, hype moments, memorable quotes. Skip intros, sponsor reads and dead air. score 1-100, be critical.

{chr(10).join(_line(s, peaks) for s in w)}"""
        try:
            data = llm.chat_json(settings, SYSTEM, prompt, SCENE_SCHEMA, temperature=0.3)
        except (ValueError, KeyError, TypeError):
            continue
        ids = {s["i"] for s in w}
        scenes += [x for x in data.get("scenes", []) if x.get("start_index") in ids and x.get("end_index") in ids]
    scenes.sort(key=lambda x: x.get("score", 0), reverse=True)
    out = []
    for sc in scenes:  # drop overlapping duplicates
        a, b = sorted((sc["start_index"], sc["end_index"]))
        if not any(min(b, o["b"]) - max(a, o["a"]) > 0.5 * (b - a + 1) for o in out):
            out.append({**sc, "a": a, "b": b})
    return out[:8]


def moments_in_scene(S, scene, meta, settings, peaks, lo, hi) -> list[dict]:
    a, b = max(0, scene["a"] - 2), min(len(S) - 1, scene["b"] + 2)
    prompt = f"""Scene "{scene['name']}" from "{meta['title']}". Pick the 1-3 BEST individual moments inside it for
{lo}-{hi} second Shorts. Do NOT just split the scene into equal parts - choose the strongest beats.
Each moment: a clear hook in the first second, the entertaining payoff, and enough context to make sense alone.
No broken sentences, no dead air. Rate 1-10: humor, surprise, reaction (intensity), hook, completeness,
context (understandable alone). Lines: [index] (time) text; [LOUD REACTION] = audio spike.

{chr(10).join(_line(s, peaks) for s in S[a:b + 1])}"""
    try:
        data = llm.chat_json(settings, SYSTEM, prompt, MOMENT_SCHEMA, temperature=0.3)
    except (ValueError, KeyError, TypeError):
        return []
    return [m for m in data.get("moments", []) if a <= m.get("start_index", -1) <= m.get("end_index", -1) <= b]


def snap(S, m, lo, hi) -> tuple[float, float] | None:
    """Clip times on speech boundaries within [lo, hi]: start on a sentence start, end on a sentence end."""
    a, b = m["start_index"], m["end_index"]
    starts = [i for i in (a, a - 1, a + 1) if 0 <= i < len(S)]
    for i in starts:
        ends = [j for j in range(i, min(len(S), i + 40)) if lo <= S[j]["end"] - S[i]["start"] <= hi]
        if ends:
            j = min(ends, key=lambda j: abs(j - b))
            start = max(0.0, S[i]["start"] - 0.25, S[i - 1]["end"] if i else 0.0)
            end = min(S[j]["end"] + 0.4, S[j + 1]["start"] if j + 1 < len(S) else S[j]["end"] + 0.4)
            return round(start, 2), round(end, 2)
    return None


def score(m: dict, peak: float) -> int:
    v = {k: max(1, min(10, int(m.get(k) or 5))) for k in ("humor", "surprise", "reaction", "hook", "completeness", "context")}
    reaction = 0.5 * v["reaction"] + 0.5 * (10 * peak) if peak >= 0 else v["reaction"]
    total = (0.25 * v["humor"] + 0.15 * v["surprise"] + 0.2 * reaction + 0.15 * v["hook"]
             + 0.15 * v["completeness"] + 0.1 * v["context"])
    return int(round(total * 10))


# ---------------- job ----------------

def describe_candidates(p: Project, settings: dict, progress=None):
    """Description + hashtags for candidates that have none (the scene analysis already wrote their titles)."""
    with session() as s:
        todo = [(sh.id, sh.transcript) for sh in s.query(Short).filter_by(project_id=p.id, status="candidate") if not sh.description]
    meta = {"title": p.title, "channel": (p.options or {}).get("creator") or p.channel}
    for k, (sid, text) in enumerate(todo):
        if progress:
            progress(k / len(todo), f"Writing description & hashtags {k + 1}/{len(todo)}")
        try:
            md = llm.generate_metadata(text, meta, settings, kind="creator")
            _set(Short, sid, description=md["description"], hashtags=md["hashtags"])
        except (ValueError, KeyError) as e:  # a bad LLM reply or a deleted candidate shouldn't fail the analysis
            log.warning("Candidate %s metadata failed: %s", sid, e)


def analyze(ctx: JobContext, job):
    settings = get_settings()
    p = _set(Project, job.project_id, status="processing", error=None)
    opts = p.options or {}
    lo, hi = LENGTHS.get(int(opts.get("clip_seconds", 15)), LENGTHS[15])
    pdir = project_dir(p.id)
    meta = {"title": p.title, "creator": opts.get("creator") or p.channel, "category": opts.get("video_category")}

    src = Path(p.source_path) if p.source_path else None
    if (not src or not src.exists()) and p.source_type == "youtube" and opts.get("authorized"):
        src = download.download(p.source_url, pdir, ctx.phase("downloading authorized media", 0.0, 0.12))
        p = _set(Project, p.id, source_path=str(src), source_deleted=False)
    have_media = bool(src and src.exists())

    tpath = pdir / "transcript.json"
    peaks = None
    motion = cuts = None
    if have_media:
        info = media.probe(src)
        p = _set(Project, p.id, **info)
        audio = pdir / "audio.wav"
        if not audio.exists():
            media.extract_audio(src, audio, info["duration"], ctx.phase("extracting audio", 0.12, 0.16))
        if not tpath.exists():
            res = transcribe(audio, settings, ctx.phase("transcribing", 0.16, 0.4), initial_prompt=f"{p.title}.",
                             total_duration=info["duration"])
            tpath.write_text(json.dumps(res), "utf-8")
        ctx.update(0.4, "Measuring reactions and on-screen action", stage="analysing audio & video", force=True)
        peaks = audio_peaks(audio)
        motion, cuts = visual_activity(str(src), info["duration"])
        mode = "media"
    else:
        if not tpath.exists():
            ctx.update(0.1, "Fetching the video's published captions", stage="reading captions", force=True)
            with tempfile.TemporaryDirectory() as tmp:
                segs = captions_transcript(p.source_url, Path(tmp))
            tpath.write_text(json.dumps({"language": "en", "device": "captions", "segments": segs}), "utf-8")
        mode = "transcript-only"
    segments = json.loads(tpath.read_text("utf-8"))["segments"]
    S = sentences_from_segments(segments)
    if len(S) < 3:
        raise ValueError("Not enough speech to analyse. Gaming/reaction videos with little talking need the media file.")

    cb = ctx.phase("finding entertaining scenes", 0.45, 0.85)
    scenes = find_scenes(S, meta, settings, peaks, cb)
    if not scenes:
        raise ValueError("The AI found no entertaining scenes in this video.")
    cands = []
    for k, sc in enumerate(scenes):
        cb(0.4 + 0.6 * k / len(scenes), f"Picking the best {lo}-{hi}s moments in scene {k + 1}/{len(scenes)}")
        for m in moments_in_scene(S, sc, meta, settings, peaks, lo, hi):
            span = snap(S, m, lo, hi)
            if not span:
                continue
            a, b = span
            pk = float(peaks[int(a):int(b) + 1].max()) if peaks is not None and len(peaks[int(a):int(b) + 1]) else -1.0
            text = " ".join(s["text"] for s in S if s["end"] > a and s["start"] < b)
            signals = {"audio_peak": round(pk, 2) if pk >= 0 else None}
            if motion is not None:
                signals["motion"] = round(float(motion[int(a):int(b) + 1].mean()), 2)
                signals["cuts"] = int(cuts[int(a):int(b) + 1].sum())
            cands.append({"start": a, "end": b, "text": text, "title": m.get("title", "")[:100], "category": m.get("category", ""),
                          "why": m.get("why", ""), "score": score(m, pk), "scene": sc["name"],
                          "scores": {k: m.get(k) for k in ("humor", "surprise", "reaction", "hook", "completeness", "context")},
                          "signals": signals})
    # rank with a repetition penalty for near-duplicate moments
    cands.sort(key=lambda c: c["score"], reverse=True)
    chosen = []
    for c in cands:
        words = set(c["text"].lower().split())
        overlap = any(min(c["end"], o["end"]) - max(c["start"], o["start"]) > 0.5 * (c["end"] - c["start"]) for o in chosen)
        similar = any(len(words & set(o["text"].lower().split())) / max(1, len(words)) > 0.6 for o in chosen)
        if overlap:
            continue
        if similar:
            c["score"] = max(1, c["score"] - 15)
        chosen.append(c)
    chosen = chosen[: int(opts.get("max_candidates", 15))]
    if not chosen:
        raise ValueError(f"No complete {lo}-{hi}s moments found. Try a longer clip length.")
    with session() as s:
        for old in s.query(Short).filter_by(project_id=p.id).all():
            if old.status == "candidate" or not s.query(Publication).filter_by(short_id=old.id).first():
                delete_short_files(old)
                s.delete(old)
        for rank, c in enumerate(sorted(chosen, key=lambda c: c["score"], reverse=True)):
            s.add(Short(project_id=p.id, rank=rank, start=c["start"], end=c["end"], transcript=c["text"],
                        hook=c["text"].split(".")[0][:200], title=c["title"], category=c["category"], reason=c["why"],
                        score=c["score"], status="candidate",
                        details={"scene": c["scene"], "scores": c["scores"], "signals": c["signals"], "analysis": mode}))
    describe_candidates(p, settings, ctx.phase("writing descriptions & hashtags", 0.85, 1.0))
    llm.unload(settings)
    _set(Project, p.id, status="completed", error=None)
    ctx.update(1.0, f"Done - {len(chosen)} clip candidates ({mode} analysis)", force=True)
