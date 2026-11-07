"""Background-media jobs: generate an original loop, or import a licensed Pexels clip."""
from app.processors import backgrounds
from app.services.jobs import JobContext
from app.services.settings import get_settings


def run(ctx: JobContext, job):
    p = job.payload or {}
    if p.get("generate"):
        seconds = int(min(180, max(20, int(p.get("seconds", 75)))))
        m = backgrounds.generate(p["generate"], seconds, get_settings()["encoder"], ctx.phase("generating footage", 0.0, 1.0))
    elif p.get("pexels"):
        m = backgrounds.pexels_import(p["pexels"], p.get("category", "satisfying"), ctx.phase("downloading from Pexels", 0.0, 1.0))
    else:
        raise ValueError("Unknown media job")
    ctx.update(1.0, f"Added '{m['title']}' to the media library", force=True)
