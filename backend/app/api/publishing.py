import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

import httpx
from fastapi import APIRouter
from fastapi.responses import RedirectResponse

from app.core import secure
from app.core.config import FRONTEND_URL
from app.database.db import session, utcnow
from app.models.models import Project, Publication, Short, YouTubeAccount
from app.processors.render import music_track
from app.publishing import youtube
from app.scheduler import scheduler
from app.services.settings import get_settings

router = APIRouter(prefix="/api")


@router.get("/youtube/config")
def get_config():
    return {**youtube.client_config_status(), "redirect_uri": get_settings()["youtube_redirect_uri"]}


@router.post("/youtube/config")
def set_config(body: dict):
    youtube.save_client_config(body.get("json", ""))
    return get_config()


@router.get("/youtube/oauth/start")
def oauth_start():
    return {"url": youtube.start_auth(get_settings()["youtube_redirect_uri"])}


@router.get("/youtube/oauth/callback")
def oauth_callback(state: str = "", code: str = "", error: str = ""):
    if error:
        return RedirectResponse(f"{FRONTEND_URL}/accounts?{urlencode({'error': error})}")
    try:
        acc = youtube.finish_auth(state, code)
    except Exception as e:
        return RedirectResponse(f"{FRONTEND_URL}/accounts?{urlencode({'error': str(e)[:300]})}")
    return RedirectResponse(f"{FRONTEND_URL}/accounts?{urlencode({'connected': acc['channel_title']})}")


@router.get("/youtube/accounts")
def accounts():
    with session() as s:
        return [a.to_dict() for a in s.query(YouTubeAccount).order_by(YouTubeAccount.id)]


@router.delete("/youtube/accounts/{aid}")
def disconnect(aid: int):
    with session() as s:
        acc = s.get(YouTubeAccount, aid)
        if not acc:
            raise KeyError("Account not found")
        try:  # revoke the grant at Google too (best effort)
            tok = json.loads(secure.decrypt(acc.token))
            httpx.post("https://oauth2.googleapis.com/revoke", params={"token": tok.get("refresh_token") or tok.get("token")}, timeout=10)
        except Exception:
            pass
        s.delete(acc)
    return {"ok": True}


def _to_utc(local: str, tz: str) -> datetime:
    try:
        dt = datetime.fromisoformat(local)
    except ValueError:
        raise ValueError("Invalid date/time")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=ZoneInfo(tz))
    return dt.astimezone(timezone.utc).replace(tzinfo=None)


def _pub_dict(s, pub: Publication) -> dict:
    sh = s.get(Short, pub.short_id)
    acc = s.get(YouTubeAccount, pub.account_id)
    return {**pub.to_dict(), "short_title": sh.title if sh else "", "project_id": sh.project_id if sh else None,
            "channel_title": acc.channel_title if acc else "(disconnected)"}


@router.post("/publications")
def create_publication(body: dict):
    settings = get_settings()
    mode = body.get("mode", "now")
    privacy = body.get("privacy", settings["default_privacy"])
    if mode not in ("now", "youtube", "local"):
        raise ValueError("mode must be now, youtube or local")
    if privacy not in ("public", "private", "unlisted"):
        raise ValueError("privacy must be public, private or unlisted")
    publish_at = None
    if mode != "now":
        publish_at = _to_utc(body.get("publish_at", ""), body.get("timezone") or settings["timezone"])
        if publish_at < utcnow() + timedelta(minutes=2):
            raise ValueError("Scheduled time must be at least 2 minutes in the future")
        if mode == "youtube":
            privacy = "public"  # YouTube's publishAt flow: private until publish time, then public
    with session() as s:
        sh = s.get(Short, int(body.get("short_id", 0)))
        if not sh or sh.status != "ready" or not sh.video_path or not Path(sh.video_path).exists():
            raise ValueError("This short has no rendered video yet")
        if not s.get(YouTubeAccount, int(body.get("account_id", 0))):
            raise ValueError("Select a connected YouTube account")
        title = str(body.get("title") or sh.title).strip()
        if not 1 <= len(title) <= 100 or "<" in title or ">" in title:
            raise ValueError("Title must be 1-100 characters and cannot contain < or >")
        hashtags = str(body.get("hashtags", sh.hashtags) or "")
        desc = str(body.get("description", sh.description) or "").replace("<", "").replace(">", "")
        track = music_track(s.get(Project, sh.project_id), sh)
        if track and track["credit"] and track["credit"] not in desc:  # CC BY music needs attribution
            desc += f"\n\nMusic: {track['credit']}"
        full_desc = (desc + "\n\n" + hashtags).strip()
        tags, total = [], 0
        for t in hashtags.split():
            t = t.lstrip("#")
            if t and total + len(t) + 1 <= 450:
                tags.append(t)
                total += len(t) + 1
        pub = Publication(short_id=sh.id, account_id=int(body["account_id"]), title=title, description=full_desc[:5000],
                          tags=tags, privacy=privacy, mode=mode, publish_at=publish_at,
                          made_for_kids=bool(body.get("made_for_kids", False)),
                          message="Queued for upload" if mode != "local" else "Waiting for scheduled time (app must be running)")
        s.add(pub)
        s.flush()
        out = _pub_dict(s, pub)
    scheduler.wake()
    return out


@router.get("/publications")
def list_publications():
    with session() as s:
        return [_pub_dict(s, p) for p in s.query(Publication).order_by(Publication.id.desc()).all()]


@router.patch("/publications/{pid}")
def reschedule(pid: int, body: dict):
    settings = get_settings()
    at = _to_utc(body.get("publish_at", ""), body.get("timezone") or settings["timezone"])
    if at < utcnow() + timedelta(minutes=2):
        raise ValueError("New time must be at least 2 minutes in the future")
    with session() as s:
        pub = s.get(Publication, pid)
        if not pub:
            raise KeyError("Publication not found")
        if pub.status == "scheduled" and pub.youtube_video_id:
            youtube.update_schedule(pub.account_id, pub.youtube_video_id, at, pub.made_for_kids)
            pub.message = "Rescheduled on YouTube"
        elif pub.status in ("pending", "failed"):
            if pub.mode == "now":
                pub.mode = "local"
            pub.status, pub.error = "pending", None
            pub.message = "Rescheduled"
        else:
            raise ValueError(f"A {pub.status} video can't be rescheduled")
        pub.publish_at = at
        out = _pub_dict(s, pub)
    scheduler.wake()
    return out


@router.post("/publications/{pid}/retry")
def retry(pid: int):
    with session() as s:
        pub = s.get(Publication, pid)
        if not pub or pub.status != "failed":
            raise ValueError("Only failed uploads can be retried")
        if pub.mode != "now" and pub.publish_at and pub.publish_at < utcnow() + timedelta(minutes=2):
            pub.mode, pub.publish_at = "now", None  # schedule time has passed - publish now
        pub.status, pub.error, pub.progress, pub.youtube_video_id, pub.retry_at = "pending", None, 0.0, None, None
        pub.message = "Retrying"
    scheduler.wake()
    return {"ok": True}


@router.delete("/publications/{pid}")
def cancel(pid: int):
    with session() as s:
        pub = s.get(Publication, pid)
        if not pub:
            raise KeyError("Publication not found")
        if pub.status == "uploading":
            raise ValueError("Upload in progress - wait for it to finish")
        if pub.status == "scheduled" and pub.youtube_video_id:
            youtube.update_schedule(pub.account_id, pub.youtube_video_id, None, pub.made_for_kids)
            pub.status, pub.publish_at = "cancelled", None
            pub.message = "Schedule cancelled - the video stays private on your channel (delete it in YouTube Studio if unwanted)."
            return {"ok": True, "kept": True}
        s.delete(pub)
    return {"ok": True}
