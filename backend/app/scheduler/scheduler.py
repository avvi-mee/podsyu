"""Local publishing scheduler. Runs inside the backend: the app must be running for 'local' schedules to fire."""
import logging
import threading
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from pathlib import Path

from app.database.db import session, utcnow
from app.models.models import Publication, Short
from app.publishing import youtube

log = logging.getLogger(__name__)
_wake = threading.Event()
_stop = threading.Event()
TICK = 15


def wake():
    _wake.set()


def _set(pid: int, **fields):
    with session() as s:
        pub = s.get(Publication, pid)
        if pub:
            for k, v in fields.items():
                setattr(pub, k, v)


def quota_reset() -> datetime:
    """YouTube API quota resets at midnight Pacific Time; returns that moment (+10 min) as naive UTC."""
    pt = datetime.now(ZoneInfo("America/Los_Angeles"))
    nxt = (pt + timedelta(days=1)).replace(hour=0, minute=10, second=0, microsecond=0)
    return nxt.astimezone(timezone.utc).replace(tzinfo=None)


def _due() -> list[int]:
    now = utcnow()
    with session() as s:
        rows = s.query(Publication).filter(Publication.status == "pending").all()
        return [p.id for p in rows if not (p.retry_at and p.retry_at > now)
                and (p.mode != "local" or (p.publish_at and p.publish_at <= now))]


def _publish(pid: int):
    with session() as s:
        pub = s.get(Publication, pid)
        if not pub or pub.status != "pending":
            return
        short = s.get(Short, pub.short_id)
        pub.status, pub.progress, pub.error, pub.attempts = "uploading", 0.0, None, pub.attempts + 1
        pub.message = "Uploading to YouTube"
        p = pub.to_dict()
    if not short or not short.video_path or not Path(short.video_path).exists():
        _set(pid, status="failed", error="Rendered video file not found - re-render the short and retry.")
        return
    youtube_schedule = p["mode"] == "youtube" and p["publish_at"]
    publish_at = pub.publish_at if youtube_schedule else None
    if youtube_schedule and publish_at <= utcnow() + timedelta(minutes=2):
        publish_at = None  # time already passed: publish now with requested privacy
    last = [0.0]

    def prog(f):
        if f - last[0] >= 0.02:
            last[0] = f
            _set(pid, progress=round(f, 3), message=f"Uploading {f:.0%}")

    try:
        res = youtube.upload(p["account_id"], short.video_path, p["title"], p["description"], p["tags"], p["privacy"],
                             publish_at, p["made_for_kids"], prog)
    except Exception as e:
        log.warning("Upload of publication %s failed: %s", pid, e)
        if "[quotaExceeded]" in str(e) or "[uploadLimitExceeded]" in str(e):  # wait for the daily reset, then retry
            at = quota_reset() if "[quotaExceeded]" in str(e) else utcnow() + timedelta(hours=24)
            _set(pid, status="pending", progress=0.0, retry_at=at, message=(
                f"YouTube's daily upload limit is used up - retrying automatically after {at:%d %b %H:%M} UTC "
                "(keep the app running)."))
            return
        _set(pid, status="failed", error=str(e), message="Upload failed")
        return
    vid = res["id"]
    got = (res.get("status") or {}).get("privacyStatus")
    if publish_at:
        _set(pid, status="scheduled", progress=1.0, youtube_video_id=vid,
             message="Uploaded as private; YouTube will make it public at the scheduled time.")
        return
    _set(pid, youtube_video_id=vid, progress=1.0)
    _confirm(pid, vid, p["account_id"], p["privacy"], got)


def _confirm(pid: int, vid: str, account_id: int, wanted: str, got: str | None = None):
    """Only mark 'published' once the API reports the video as public."""
    try:
        st = youtube.video_status(account_id, vid) or {}
    except Exception as e:
        st = {}
        log.warning("Status check failed for %s: %s", vid, e)
    privacy = st.get("privacyStatus") or got
    if st.get("uploadStatus") in ("rejected", "failed"):
        _set(pid, status="failed", error=f"YouTube {st['uploadStatus']} the video: {st.get('rejectionReason') or st.get('failureReason')}")
    elif wanted == "public" and privacy == "public":
        _set(pid, status="published", message="Published - confirmed public by the YouTube API.")
    elif wanted == "public":
        _set(pid, status="uploaded", message=(
            f"Uploaded, but YouTube reports it as '{privacy}'. Uploads from unverified Google Cloud projects are locked to "
            "private - see README > 'Publishing publicly'."))
    else:
        _set(pid, status="uploaded", message=f"Uploaded as {privacy or wanted}.")


def _check_scheduled():
    """YouTube-managed schedules: confirm they actually went public after publishAt."""
    now = utcnow()
    with session() as s:
        rows = s.query(Publication).filter(Publication.status == "scheduled", Publication.publish_at <= now - timedelta(minutes=2),
                                           Publication.updated_at <= now - timedelta(minutes=5)).all()
        items = [(p.id, p.youtube_video_id, p.account_id) for p in rows]
    for pid, vid, acc in items:
        try:
            st = youtube.video_status(acc, vid)
        except Exception as e:
            _set(pid, message=f"Could not check status: {e}")
            continue
        if st is None:
            _set(pid, status="failed", error="Video no longer exists on YouTube.")
        elif st.get("privacyStatus") == "public":
            _set(pid, status="published", message="Published by YouTube at the scheduled time (confirmed via API).")
        else:
            _set(pid, message=f"Past scheduled time but YouTube still reports '{st.get('privacyStatus')}' "
                              f"(checked {utcnow():%H:%M} UTC). Checking again in 5 minutes.")


def _loop():
    while not _stop.is_set():
        try:
            for pid in _due():
                _publish(pid)
            _check_scheduled()
        except Exception:
            log.exception("Scheduler tick failed")
        _wake.wait(TICK)
        _wake.clear()


def start():
    with session() as s:  # uploads interrupted by a restart start over
        s.query(Publication).filter(Publication.status == "uploading").update({"status": "pending", "progress": 0.0})
    threading.Thread(target=_loop, name="publish-scheduler", daemon=True).start()


def stop():
    _stop.set()
    _wake.set()
