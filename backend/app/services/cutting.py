"""ASMR Cutting Studio engine: object + number of cuts -> Blender scene -> chop soundtrack -> vertical MP4.

The studio itself lives in its own folder (ASMR_CUTTING_DIR, default D:\\asmr cutting); this runs its CLI
(`studio.py make --progress`), streams the progress into the job and registers the finished MP4 as a short.
"""
import json
import logging
import os
import shutil
import subprocess
import sys
from pathlib import Path

from app.database.db import session
from app.models.models import Project, Short
from app.processors import media
from app.processors.render import project_dir
from app.services.jobs import JobContext
from app.services.settings import get_settings

log = logging.getLogger(__name__)
STUDIO_DIR = Path(os.getenv("ASMR_CUTTING_DIR", r"D:\asmr cutting"))
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def _studio() -> Path:
    script = STUDIO_DIR / "studio.py"
    if not script.exists():
        raise FileNotFoundError(f"ASMR cutting studio not found at {STUDIO_DIR}. Set ASMR_CUTTING_DIR in .env.")
    return script


def status() -> dict:
    """Tool paths/versions, presets and the studio's default config (fast: no rendering)."""
    try:
        r = subprocess.run([sys.executable, str(_studio()), "tools", "--json"], cwd=STUDIO_DIR, capture_output=True,
                           text=True, timeout=90, creationflags=NO_WINDOW)
        data = json.loads(r.stdout)
    except FileNotFoundError as e:
        return {"ok": False, "error": str(e), "studio_dir": str(STUDIO_DIR)}
    except (subprocess.TimeoutExpired, json.JSONDecodeError, OSError) as e:
        return {"ok": False, "error": f"Studio check failed: {e}", "studio_dir": str(STUDIO_DIR)}
    data["ok"] = all(data["versions"].values())
    data["studio_dir"] = str(STUDIO_DIR)
    return data


def _set(model, id_, **fields):
    with session() as s:
        obj = s.get(model, id_)
        for k, v in fields.items():
            setattr(obj, k, v)


def _kill_tree(proc: subprocess.Popen):
    """Stop the studio and the Blender/FFmpeg it started (Windows doesn't kill children with the parent)."""
    if proc.poll() is None:
        subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)], capture_output=True, creationflags=NO_WINDOW)


def metadata(obj: str, cuts: int, result: dict) -> dict:
    name = obj.strip()
    tag = "#" + "".join(w.capitalize() for w in name.split() if w.isalnum())
    split = result.get("pattern") == "split"
    how = ("split down the middle, then sliced across both halves at wonky angles" if split
           else "sliced into thin pieces at wonky angles")
    return {
        "title": f"{name.title()} vs {cuts} knife cuts 🔪 satisfying ASMR"[:100],
        "description": f"A {name.lower()} {how} with {cuts} knife strokes. Count every cut and wait for the slices to fall. "
                       "Headphones on for the chop sounds.",
        "hashtags": " ".join(dict.fromkeys(["#Shorts", "#ASMR", "#Satisfying", "#ASMRCutting", "#KnifeSkills", tag])),
        "transcript": f"3D ASMR cutting video: a {name} on a wooden board is {how} with {cuts} knife strokes. "
                      f"A counter goes from 0/{cuts} to {cuts}/{cuts}, then {result.get('pieces')} slices fall onto the board. "
                      "Each cut has a chop sound.",
    }


def generate(ctx: JobContext, job):
    with session() as s:
        p = s.get(Project, job.project_id)
        sh = s.query(Short).filter_by(project_id=p.id).first()
        p.status, p.error = "processing", None
        opts = dict(p.options or {})
        pid, sid = p.id, sh.id
    _set(Short, sid, status="rendering", error=None)
    cmd = [sys.executable, "-u", str(_studio()), "make", "--object", opts["object"], "--cuts", str(opts["cuts"]),
           "--watermark", opts.get("watermark") or "", "--progress"]
    ctx.update(0.0, f"Starting Blender for {opts['object']} x {opts['cuts']} cuts", stage="building scene", force=True)
    result, tail = None, []
    proc = subprocess.Popen(cmd, cwd=STUDIO_DIR, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                            encoding="utf-8", errors="replace", creationflags=NO_WINDOW)
    try:
        for line in proc.stdout:
            line = line.rstrip()
            if line.startswith("PROGRESS "):
                _, frac, msg = (line.split(" ", 2) + [""])[:3]
                stage = "rendering frames" if "frame" in msg.lower() else "exporting" if "MP4" in msg else "building scene"
                ctx.update(float(frac) * 0.97, msg, stage=stage)
            elif line.startswith("RESULT "):
                result = json.loads(line[7:])
            elif line:
                tail = (tail + [line])[-15:]
        proc.wait()
    except BaseException:  # cancelled or crashed: don't leave Blender rendering in the background
        _kill_tree(proc)
        _set(Short, sid, status="failed", error="Stopped")
        raise
    if proc.returncode or not result:
        err = next((ln[6:] for ln in reversed(tail) if ln.startswith("ERROR ")), "\n".join(tail[-5:]) or "studio failed")
        _set(Short, sid, status="failed", error=err[:1000])
        raise RuntimeError(err[:1000])

    ctx.update(0.98, "Adding the video to Generated Shorts", stage="finishing", force=True)
    out_dir = Path(get_settings()["output_dir"]) / str(pid)
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"short_{sid}.mp4"
    shutil.copy2(result["mp4"], out)  # the run folder keeps its own copy + scene.blend for editing
    thumb = project_dir(pid) / f"short_{sid}.jpg"
    media.frame_jpeg(["-ss", f"{min(5.0, result['duration'] / 3):.2f}", "-i", str(out)], "scale=360:-2", thumb)
    shutil.copy2(thumb, project_dir(pid) / "thumb.jpg")
    md = metadata(opts["object"], opts["cuts"], result)
    w, h = (int(x) for x in result["checks"]["size"].split("x"))
    _set(Short, sid, status="ready", video_path=str(out), thumb_path=str(thumb), start=0.0, end=round(result["duration"], 2),
         framing=f"Blender {result['pattern']} cut · {result['pieces']} pieces · {result['checks']['audio']}",
         details={"run": result["run"], "blend": result["blend"], "previews": result["previews"], "pieces": result["pieces"],
                  "pattern": result["pattern"]}, **md)
    _set(Project, pid, status="completed", error=None, duration=result["duration"], width=w, height=h, fps=24.0)
    ctx.update(1.0, "Done - cutting short ready", force=True)
