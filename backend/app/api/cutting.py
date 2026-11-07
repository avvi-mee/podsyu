"""ASMR Cutting Studio API: object + cuts -> Blender-rendered knife-cutting short."""
from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import FileResponse

from app.database.db import session
from app.models.models import Project, Publication, Short
from app.services import cutting, jobs

router = APIRouter(prefix="/api/cutting")
PREVIEWS = ("opening", "middle_cut", "fall")


@router.get("/status")
def status():
    return cutting.status()


@router.post("/generate")
def generate(body: dict):
    obj = str(body.get("object", "")).strip()[:60]
    if not obj:
        raise ValueError("Type the object to cut, e.g. Papaya")
    cuts = body.get("cuts")
    if isinstance(cuts, bool) or not str(cuts).isdigit() or not 1 <= int(cuts) <= 200:
        raise ValueError("Cuts must be a whole number from 1 to 200")
    cuts = int(cuts)
    watermark = str(body.get("watermark") or "").strip()[:40]
    with session() as s:
        p = Project(title=f"{obj} · {cuts} cuts", source_type="cutting", engine="cutting", status="queued",
                    options={"object": obj, "cuts": cuts, "watermark": watermark})
        s.add(p)
        s.flush()
        s.add(Short(project_id=p.id, start=0, end=1, title=f"{obj} vs {cuts} knife cuts"[:100], category="asmr",
                    status="pending", hook=f"0/{cuts} -> {cuts}/{cuts} cuts"))
        pid = p.id
    jobs.enqueue("cutting", project_id=pid)
    return {"project_id": pid}


@router.get("/projects")
def projects():
    with session() as s:
        out = []
        for p in s.query(Project).filter_by(engine="cutting").order_by(Project.id.desc()).limit(100):
            sh = s.query(Short).filter_by(project_id=p.id).first()
            d = p.to_dict()
            d["short"] = {k: v for k, v in sh.to_dict().items() if k != "words"} if sh else None
            if sh:
                d["short"]["publications"] = [x.to_dict() for x in s.query(Publication).filter_by(short_id=sh.id)]
            out.append(d)
        return out


@router.get("/projects/{pid}/preview/{name}")
def preview(pid: int, name: str):
    """The guide's three check frames (opening, middle cut, fall) from the Blender run."""
    if name not in PREVIEWS:
        raise KeyError("Unknown preview")
    with session() as s:
        sh = s.query(Short).filter_by(project_id=pid).first()
        path = ((sh.details or {}).get("previews") or {}).get(name) if sh else None
    if not path or not Path(path).exists():
        raise KeyError("Preview not available")
    return FileResponse(path, media_type="image/png")
