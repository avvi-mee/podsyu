"""ASMR Stories Factory API: stories (discover / write / upload), script adaptation, voice preview, one-tap generation."""
import uuid

from fastapi import APIRouter
from fastapi.responses import FileResponse

from app.ai import tts
from app.api import music as music_api
from app.core.config import DATA_DIR
from app.database.db import session
from app.models.models import BackgroundMedia, Job, Project, Publication, Short, Story
from app.processors import captions
from app.services import jobs, stories
from app.services.settings import get_settings

router = APIRouter(prefix="/api/asmr")
SECONDS = (15, 30, 45, 60, 90)


def _story(s, sid: int) -> Story:
    st = s.get(Story, sid)
    if not st:
        raise KeyError("Story not found")
    return st


def _out(st: Story) -> dict:
    d = st.to_dict()
    d["suitability"] = stories.suitability(st.title, st.body, st.nsfw)
    d["words"] = len(st.body.split())
    return d


@router.get("/status")
def status():
    return {"tts": tts.available(), "reddit": stories.reddit_configured(), "categories": stories.CATEGORIES,
            "profiles": list(tts.PROFILES), "emotions": list(tts.EMOTIONS), "default_voice": tts.DEFAULT_VOICE,
            "seconds": SECONDS}


@router.get("/stories")
def list_stories(status: str | None = None, category: str | None = None):
    with session() as s:
        q = s.query(Story)
        if status:
            q = q.filter_by(status=status)
        if category:
            q = q.filter_by(category=category)
        return [_out(st) for st in q.order_by(Story.id.desc()).limit(300)]


@router.post("/discover")
def discover(body: dict):
    """Find text stories on Reddit via the official API and save them (marked 'needs permission')."""
    found = stories.discover(body.get("subreddit", ""), body.get("keyword", ""), body.get("category", ""),
                             body.get("sort", "top"), body.get("period", "week"), int(body.get("min_score", 0)),
                             int(body.get("min_comments", 0)))
    with session() as s:
        known = {u for (u,) in s.query(Story.url).filter(Story.url.isnot(None))}
        new = [Story(**f) for f in found if f["url"] not in known]
        s.add_all(new)
        s.flush()
        return {"found": len(found), "added": len(new), "stories": [_out(x) for x in new]}


@router.post("/stories")
def add_story(body: dict):
    """Upload my own story (source_type user) or a licensed one."""
    title, text = str(body.get("title", "")).strip()[:200], str(body.get("body", "")).strip()
    if not title or len(text.split()) < 30:
        raise ValueError("Give the story a title and at least 30 words.")
    src = body.get("source_type", "user")
    if src not in ("user", "licensed"):
        raise ValueError("source_type must be user or licensed")
    with session() as s:
        st = Story(source_type=src, title=title, body=text[:20000], category=body.get("category") or "life",
                   permission="not_required" if src == "user" else "granted",
                   attribution=str(body.get("attribution") or ("Own story" if src == "user" else ""))[:500] or None,
                   url=str(body.get("url") or "")[:500] or None)
        s.add(st)
        s.flush()
        return _out(st)


@router.post("/stories/generate")
def generate_story(body: dict):
    """Original AI fiction for a category, optionally from my idea or inspired by a saved story's theme."""
    idea = str(body.get("idea", ""))
    if body.get("inspired_by"):
        with session() as s:
            src = _story(s, int(body["inspired_by"]))
            idea = f"General theme only (write a NEW story, do not retell it): {src.title}"
    category = body.get("category") or "life"
    data = stories.write_original(category, idea, get_settings())
    with session() as s:
        st = Story(**data)
        s.add(st)
        s.flush()
        return _out(st)


@router.patch("/stories/{sid}")
def update_story(sid: int, body: dict):
    with session() as s:
        st = _story(s, sid)
        if "status" in body:
            if body["status"] not in ("new", "selected", "rejected", "used"):
                raise ValueError("Invalid status")
            st.status = body["status"]
        if "permission" in body:
            if body["permission"] not in ("unknown", "needs_permission", "granted", "not_required"):
                raise ValueError("Invalid permission value")
            if body["permission"] == "not_required" and st.source_type == "reddit":
                raise ValueError("Reddit stories belong to their authors - mark 'granted' once you have permission.")
            st.permission = body["permission"]
        for k in ("script", "title", "category"):
            if k in body:
                setattr(st, k, str(body[k] or "").strip()[: 20000 if k == "script" else 200] or None)
        return _out(st)


@router.delete("/stories/{sid}")
def delete_story(sid: int):
    with session() as s:
        s.delete(_story(s, sid))
    return {"ok": True}


@router.post("/stories/{sid}/adapt")
def adapt(sid: int, body: dict):
    seconds = int(body.get("seconds", 45))
    if seconds not in SECONDS:
        raise ValueError(f"seconds must be one of {SECONDS}")
    with session() as s:
        st = _story(s, sid)
        title, text = st.title, st.body
    res = stories.adapt(title, text, seconds, get_settings())
    with session() as s:
        _story(s, sid).script = res["script"]
    return {**res, "estimated_seconds": round(len(res["script"].split()) / 2.6)}


@router.post("/voice-preview")
def voice_preview(body: dict):
    text = str(body.get("text", "")).strip()[:1500] or "This is how your story will sound. Pretty good, right?"
    out = DATA_DIR / "tmp" / f"voice_{uuid.uuid4().hex}.wav"
    out.parent.mkdir(exist_ok=True)
    dur = tts.synthesize(text, body.get("voice"), out)
    return {"url": f"/api/asmr/voice-preview/{out.name}", "seconds": round(dur, 1)}


@router.get("/voice-preview/{name}")
def voice_preview_file(name: str):
    if not name.startswith("voice_") or "/" in name or "\\" in name:
        raise KeyError("Not found")
    path = DATA_DIR / "tmp" / name
    if not path.exists():
        raise KeyError("Preview expired")
    return FileResponse(path, media_type="audio/wav")


@router.post("/generate")
def generate_short(body: dict):
    """One tap: story -> script -> voice -> captions -> background -> BGM -> rendered short."""
    sid = int(body.get("story_id", 0))
    voice = tts.clean_settings(body.get("voice"))
    seconds = int(body.get("seconds", 45))
    if seconds not in SECONDS:
        raise ValueError(f"seconds must be one of {SECONDS}")
    with session() as s:
        st = _story(s, sid)
        if st.permission not in ("granted", "not_required"):
            raise ValueError("This Reddit story needs the author's permission first. Mark permission as granted, or "
                             "click 'Write original inspired by this' to make a new story with the same theme.")
        bg = body.get("background_id")
        if bg and not s.get(BackgroundMedia, int(bg)):
            raise ValueError("Unknown background video")
        music = body.get("music", "auto")
        music = music_api.pick_for_category(st.category) if music == "auto" else music_api.validate_choice(music)
        script = str(body.get("script") or st.script or "").strip() or None
        if script:
            st.script = script
        p = Project(title=st.title[:200], source_type="story", engine="asmr", status="queued",
                    options={"story_id": st.id, "category": st.category, "seconds": seconds, "voice": voice,
                             "script": script, "background_id": int(bg) if bg else None},
                    caption_style=captions.resolve_style(body.get("caption_style") or {"preset": "hormozi"}),
                    music=music or "none", music_volume=music_api.validate_volume(body.get("music_volume", 0.1)))
        s.add(p)
        s.flush()
        sh = Short(project_id=p.id, start=0, end=1, title=st.title[:100], category=st.category, status="pending",
                   hook=(script or st.body).split(".")[0][:200],
                   reason=st.attribution or "", details={"story_id": st.id, "source": st.source_type, "url": st.url})
        s.add(sh)
        s.flush()
        st.status = "selected"
        pid = p.id
    jobs.enqueue("asmr", project_id=pid)
    return {"project_id": pid}


@router.post("/projects/{pid}/regenerate")
def regenerate(pid: int, body: dict):
    """Regenerate voice (new narration with the given voice settings) or just re-render."""
    redo = body.get("redo", "voice")
    if redo not in ("voice", "render", "all"):
        raise ValueError("redo must be voice, render or all")
    with session() as s:
        p = s.get(Project, pid)
        if not p or p.engine != "asmr":
            raise KeyError("Story project not found")
        if s.query(Job).filter(Job.project_id == pid, Job.status.in_(["queued", "running"])).first():
            raise ValueError("This story short is already being generated.")
        if body.get("voice"):
            p.options = {**p.options, "voice": tts.clean_settings(body["voice"])}
        if "background_id" in body:
            p.options = {**p.options, "background_id": int(body["background_id"]) if body["background_id"] else None}
        if body.get("script"):
            p.options = {**p.options, "script": str(body["script"]).strip()[:20000]}
        p.status = "queued"
        if redo == "voice":
            s.query(Short).filter_by(project_id=pid).update({"words": None})
    jobs.enqueue("asmr", project_id=pid, payload={"redo": redo})
    return {"ok": True}


@router.get("/projects")
def story_projects():
    with session() as s:
        out = []
        for p in s.query(Project).filter_by(engine="asmr").order_by(Project.id.desc()).limit(100):
            sh = s.query(Short).filter_by(project_id=p.id).first()
            d = p.to_dict()
            d["short"] = {k: v for k, v in sh.to_dict().items() if k != "words"} if sh else None
            if sh:
                d["short"]["publications"] = [x.to_dict() for x in s.query(Publication).filter_by(short_id=sh.id)]
            out.append(d)
        return out
