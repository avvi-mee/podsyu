"""Famous Creators Clipper API. Media is only downloaded when you confirm you're authorized; otherwise analysis
uses the video's published captions and rendering waits until you supply an authorized file."""
from fastapi import APIRouter

from app.database.db import session
from app.models.models import Job, Project, Short
from app.processors import captions, download
from app.services import jobs, creators

router = APIRouter(prefix="/api/creators")


def clean_opts(body: dict, old: dict | None = None) -> dict:
    o = {**(old or {}), **{k: body[k] for k in ("creator", "video_category", "clip_seconds", "layout", "max_candidates", "authorized")
                           if k in body}}
    o["clip_seconds"] = int(o.get("clip_seconds", 15))
    if o["clip_seconds"] not in creators.LENGTHS:
        raise ValueError(f"clip_seconds must be one of {list(creators.LENGTHS)}")
    if o.get("layout", "auto") not in ("auto", "full"):
        raise ValueError("layout must be auto or full")
    o["max_candidates"] = int(min(30, max(3, int(o.get("max_candidates", 15)))))
    o["creator"] = str(o.get("creator") or "")[:80]
    o["video_category"] = str(o.get("video_category") or "")[:40]
    o["authorized"] = o.get("authorized") is True
    return o


@router.post("/inspect")
def inspect(body: dict):
    """Metadata + whether captions are available (no media download)."""
    return download.fetch_info(body.get("url", ""), with_captions=True)


@router.post("/projects")
def create(body: dict):
    url = download.validate_url(body.get("url", ""))
    info = body.get("info") or download.fetch_info(url, with_captions=True)
    opts = clean_opts(body)
    with session() as s:
        p = Project(title=(info.get("title") or "Creator video")[:200], source_type="youtube", engine="creator",
                    source_url=url, channel=info.get("channel"), thumbnail_url=info.get("thumbnail"),
                    duration=info.get("duration"), options=opts, status="queued",
                    caption_style=captions.resolve_style({"preset": "hormozi"}))
        s.add(p)
        s.flush()
        pid = p.id
    jobs.enqueue("creator_analyze", project_id=pid)
    return {"project_id": pid}


@router.post("/projects/{pid}/analyze")
def analyze(pid: int, body: dict | None = None):
    """(Re)analyse - e.g. after uploading the authorized video file for a creator project."""
    with session() as s:
        p = s.get(Project, pid)
        if not p:
            raise KeyError("Project not found")
        if s.query(Job).filter(Job.project_id == pid, Job.status.in_(["queued", "running"])).first():
            raise ValueError("This video is already being analysed.")
        p.engine = "creator"
        p.options = clean_opts(body or {}, p.options)
        p.status = "queued"
        if body and body.get("fresh"):  # new media / settings: drop the old transcript-only analysis
            from app.processors.render import project_dir

            (project_dir(pid) / "transcript.json").unlink(missing_ok=True)
        p.caption_style = p.caption_style or captions.resolve_style({"preset": "hormozi"})
    jobs.enqueue("creator_analyze", project_id=pid)
    return {"ok": True}


@router.post("/projects/{pid}/render")
def render_selected(pid: int, body: dict):
    """Render the approved candidates (ids) of a creator project."""
    ids = [int(i) for i in body.get("ids") or []]
    with session() as s:
        p = s.get(Project, pid)
        if not p:
            raise KeyError("Project not found")
        from pathlib import Path

        if not (p.source_path and Path(p.source_path).exists()):
            if p.source_type == "youtube" and (body.get("authorized") is True or (p.options or {}).get("authorized")):
                p.options = {**(p.options or {}), "authorized": True}  # the first render job downloads it
            else:
                raise ValueError("Rendering needs the video file. Upload an authorized copy of this video, or confirm "
                                 "you own it / have the rights holder's permission so it can be downloaded.")
        shorts = [sh for sh in s.query(Short).filter(Short.project_id == pid, Short.id.in_(ids))]
        for sh in shorts:
            sh.review = "approved"
            if sh.status == "candidate":
                sh.status = "pending"
    for sh in shorts:
        jobs.enqueue("render", project_id=pid, short_id=sh.id)
    return {"queued": len(shorts)}


@router.get("/projects")
def creator_projects():
    with session() as s:
        out = []
        for p in s.query(Project).filter_by(engine="creator").order_by(Project.id.desc()).limit(100):
            d = p.to_dict()
            d["candidates"] = s.query(Short).filter_by(project_id=p.id).count()
            d["rendered"] = s.query(Short).filter_by(project_id=p.id, status="ready").count()
            out.append(d)
        return out
