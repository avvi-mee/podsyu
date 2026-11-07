"""DB-backed job queue processed by one background worker (GPU work is serialised on purpose)."""
import logging
import threading
import time
import traceback

from app.database.db import session, utcnow
from app.models.models import Job, Project, Short

log = logging.getLogger(__name__)
_wake = threading.Event()
_stop = threading.Event()


class Cancelled(Exception):
    pass


class JobContext:
    def __init__(self, job: Job):
        self.job = job
        self._last = 0.0

    def update(self, progress: float | None = None, message: str | None = None, stage: str | None = None, force=False):
        now = time.monotonic()
        if not force and now - self._last < 0.5:
            return
        self._last = now
        with session() as s:
            j = s.get(Job, self.job.id)
            if j is None or j.cancel_requested:  # row gone = its project/short was deleted
                raise Cancelled()
            if progress is not None:
                j.progress = round(min(1.0, max(0.0, progress)), 4)
            if message is not None:
                j.message = message[:500]
            if stage is not None:
                j.stage = stage

    def phase(self, stage: str, lo: float, hi: float):
        """Progress callback mapping a stage-local fraction onto [lo, hi] of the job."""
        self.update(lo, stage=stage, message=stage.capitalize() + "...", force=True)
        return lambda f, msg=None: self.update(lo + (hi - lo) * f, msg)


def enqueue(type_: str, project_id: int | None = None, short_id: int | None = None, payload: dict | None = None) -> dict:
    with session() as s:
        if project_id and type_ == "process":
            busy = s.query(Job).filter(Job.project_id == project_id, Job.type == "process",
                                       Job.status.in_(["queued", "running"])).first()
            if busy:
                raise ValueError("This project is already being processed.")
        job = Job(type=type_, project_id=project_id, short_id=short_id, payload=payload or {}, message="Waiting in queue")
        s.add(job)
        s.flush()
        out = job.to_dict()
    _wake.set()
    return out


def cancel(job_id: int):
    with session() as s:
        j = s.get(Job, job_id)
        if not j:
            raise KeyError("Job not found")
        if j.status == "queued":
            j.status, j.finished_at, j.message = "cancelled", utcnow(), "Cancelled"
            _mark_owner_failed(s, j, "Cancelled")
        elif j.status == "running":
            j.cancel_requested = True


def _mark_owner_failed(s, job: Job, error: str):
    if job.type in ("process", "creator_analyze", "asmr", "cutting") and job.project_id:
        p = s.get(Project, job.project_id)
        if p:
            p.status, p.error = "failed", error
    if job.short_id:
        sh = s.get(Short, job.short_id)
        if sh and sh.status == "rendering":
            sh.status, sh.error = ("ready" if sh.video_path else "failed"), error


def recover_interrupted():
    """On startup, jobs that were running when the app stopped go back to the queue (pipeline stages are resumable)."""
    with session() as s:
        for j in s.query(Job).filter(Job.status == "running", Job.cancel_requested.is_(True)).all():
            j.status, j.finished_at, j.message = "cancelled", utcnow(), "Cancelled by user"
            _mark_owner_failed(s, j, "Cancelled by user")
        n = s.query(Job).filter(Job.status == "running").update({"status": "queued", "message": "Resuming after restart"})
        s.query(Short).filter(Short.status == "rendering").update({"status": "pending"})
    if n:
        log.info("Re-queued %d interrupted job(s)", n)


def _claim() -> Job | None:
    with session() as s:
        j = s.query(Job).filter(Job.status == "queued").order_by(Job.id).first()
        if j:
            j.status, j.started_at, j.error = "running", utcnow(), None
        return j


def _run(job: Job):
    from app.services import pipeline

    from app.services import asmr, creators, cutting, media_jobs

    handlers = {"process": pipeline.process_project, "render": pipeline.render_one,
                "recaption": pipeline.recaption, "metadata": pipeline.regenerate_metadata,
                "creator_analyze": creators.analyze, "asmr": asmr.generate, "media": media_jobs.run,
                "cutting": cutting.generate}
    ctx = JobContext(job)
    try:
        handlers[job.type](ctx, job)
        with session() as s:
            j = s.get(Job, job.id)
            if j:
                j.status, j.progress, j.finished_at = "done", 1.0, utcnow()
                j.message = j.message if job.type == "process" else "Done"
    except Cancelled:
        with session() as s:
            j = s.get(Job, job.id)
            if j:
                j.status, j.finished_at, j.message = "cancelled", utcnow(), "Cancelled by user"
                _mark_owner_failed(s, j, "Cancelled by user")
    except Exception as e:
        log.error("Job %s (%s) failed: %s\n%s", job.id, job.type, e, traceback.format_exc())
        msg = str(e) or e.__class__.__name__
        with session() as s:
            j = s.get(Job, job.id)
            if j:
                j.status, j.error, j.finished_at, j.message = "failed", msg, utcnow(), "Failed"
                _mark_owner_failed(s, j, msg)


def _loop():
    while not _stop.is_set():
        job = None
        try:
            job = _claim()
        except Exception as e:
            log.error("Job queue error: %s", e)
        if job is None:
            _wake.wait(2)
            _wake.clear()
            continue
        try:
            _run(job)
        except Exception:  # never let one broken job (e.g. its row was deleted) kill the worker thread
            log.exception("Job %s crashed outside its handler", job.id)


def start_worker():
    recover_interrupted()
    threading.Thread(target=_loop, name="job-worker", daemon=True).start()


def stop_worker():
    _stop.set()
    _wake.set()
