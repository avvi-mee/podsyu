"""Autopilot: when a project's shorts are rendered, post or schedule each one by the per-clip plan chosen up front.
Plan row i applies to the i-th best clip (by AI score)."""
import logging
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from app.database.db import session, utcnow
from app.models.models import Project, Publication, Short, YouTubeAccount

log = logging.getLogger(__name__)
MODES = ("now", "schedule", "skip")


def _utc(local: str, tz: str) -> datetime:
    dt = datetime.fromisoformat(local)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=ZoneInfo(tz))
    return dt.astimezone(timezone.utc).replace(tzinfo=None)


def _summary(plan: list[dict]) -> str:
    n = {m: sum(r["mode"] == m for r in plan) for m in MODES}
    return f"{n['now']} post immediately, {n['schedule']} scheduled, {n['skip']} not posted"


def clean(cfg: dict | None, tz: str) -> dict | None:
    """Validate the form. Scheduled times are local date-times in the app's timezone; stored as naive UTC."""
    if not cfg or not cfg.get("enabled"):
        return None
    if cfg.get("status"):  # already validated (re-processing keeps the original plan)
        return cfg
    with session() as s:
        acc = s.get(YouTubeAccount, int(cfg.get("account_id") or 0))
        if not acc:
            raise ValueError("Autopilot: pick the YouTube channel to post to")
        channel = acc.channel_title
    rows = cfg.get("plan") or []
    if not 1 <= len(rows) <= 30:
        raise ValueError("Autopilot: plan 1-30 clips")
    plan = []
    for i, row in enumerate(rows, 1):
        mode = (row or {}).get("mode")
        if mode not in MODES:
            raise ValueError(f"Autopilot: clip {i} - choose post immediately, schedule or don't post")
        at = None
        if mode == "schedule":
            try:
                at = _utc(str(row.get("at") or ""), tz)
            except ValueError:
                raise ValueError(f"Autopilot: clip {i} needs a date and time")
            if at < utcnow() + timedelta(minutes=5):
                raise ValueError(f"Autopilot: clip {i}'s time must be in the future")
        plan.append({"mode": mode, "at": at.isoformat() if at else None})
    if all(r["mode"] == "skip" for r in plan):
        raise ValueError("Autopilot: every clip is set to 'Don't post'")
    return {"enabled": True, "account_id": int(cfg["account_id"]), "channel": channel, "plan": plan, "status": "waiting",
            "message": f"When the shorts are ready: {_summary(plan)} on {channel}."}


def resolve(plan: list[dict], now: datetime) -> list[datetime | None | str]:
    """Per plan row: 'skip', None (post now) or the UTC time. A time that passed while processing posts now."""
    out = []
    for r in plan:
        at = datetime.fromisoformat(r["at"]) if r["mode"] == "schedule" else None
        out.append("skip" if r["mode"] == "skip" else (at if at and at > now + timedelta(minutes=3) else None))
    return out


def run(project_id: int):
    """Called when processing completes. Acts once; later re-renders don't post again."""
    from app.api.publishing import create_publication  # api layer holds the validated publish logic
    from app.services.settings import get_settings

    with session() as s:
        p = s.get(Project, project_id)
        cfg = dict((p.options or {}).get("autopilot") or {})
        if cfg.get("status") != "waiting":
            return
        taken = {x.short_id for x in s.query(Publication).join(Short).filter(Short.project_id == project_id)}
        picks = [sh.id for sh in s.query(Short).filter(Short.project_id == project_id, Short.status == "ready",
                                                         Short.review != "rejected").order_by(Short.score.desc())
                 if sh.id not in taken]
    tz = ZoneInfo(get_settings()["timezone"])
    now_n = sched_n = 0
    errors = []
    for sid, at in zip(picks, resolve(cfg["plan"], utcnow())):
        if at == "skip":
            continue
        body = {"short_id": sid, "account_id": cfg["account_id"], "privacy": "public", "mode": "youtube" if at else "now"}
        if at:
            body["publish_at"] = at.isoformat() + "+00:00"
        try:
            create_publication(body)
            with session() as s:
                s.get(Short, sid).review = "approved"
            sched_n += bool(at)
            now_n += not at
        except (ValueError, KeyError) as e:
            log.warning("Autopilot could not post short %s: %s", sid, e)
            errors.append(str(e))
    if now_n or sched_n:
        cfg["status"] = "scheduled"
        cfg["message"] = (f"{now_n} posting now, {sched_n} scheduled on {cfg['channel']}"
                          f" ({len(picks)} clip(s) were ready at {datetime.now(tz):%d %b %I:%M %p})."
                          + (f" {len(errors)} failed: {errors[0]}" if errors else ""))
    else:
        cfg["status"] = "failed"
        cfg["message"] = "Autopilot posted nothing: " + (errors[0] if errors else "no rendered shorts were ready.")
    with session() as s:
        p = s.get(Project, project_id)
        p.options = {**(p.options or {}), "autopilot": cfg}
