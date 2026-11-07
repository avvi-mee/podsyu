"""YouTube Data API v3: OAuth 2.0 account connection, resumable uploads, scheduling and status checks."""
import json
import logging
import os
import random
import time
from datetime import datetime

from app.core import secure
from app.core.config import CLIENT_SECRET_PATH
from app.database.db import session
from app.models.models import YouTubeAccount

os.environ.setdefault("OAUTHLIB_INSECURE_TRANSPORT", "1")  # redirect is http://localhost (never leaves this PC)
os.environ.setdefault("OAUTHLIB_RELAX_TOKEN_SCOPE", "1")
log = logging.getLogger(__name__)
SCOPES = ["https://www.googleapis.com/auth/youtube.upload", "https://www.googleapis.com/auth/youtube"]
_pending_flows: dict = {}  # state -> Flow (keeps the PKCE verifier between /start and /callback)


class PublishError(RuntimeError):
    pass


def client_config_status() -> dict:
    if not CLIENT_SECRET_PATH.exists():
        return {"configured": False}
    try:
        cfg = json.loads(CLIENT_SECRET_PATH.read_text("utf-8"))
        kind = "web" if "web" in cfg else "installed"
        cid = cfg[kind]["client_id"]
        return {"configured": True, "client_type": kind, "client_id_hint": cid[:12] + "..." + cid[-28:]}
    except Exception as e:
        return {"configured": False, "error": f"client_secret.json is invalid: {e}"}


def save_client_config(raw: str):
    try:
        cfg = json.loads(raw)
        kind = "web" if "web" in cfg else "installed" if "installed" in cfg else None
        if not kind or not cfg[kind].get("client_id") or not cfg[kind].get("client_secret"):
            raise ValueError
    except ValueError:
        raise ValueError("That is not a Google OAuth client JSON. Download it from Google Cloud Console > Credentials.")
    CLIENT_SECRET_PATH.write_text(json.dumps(cfg), "utf-8")


def start_auth(redirect_uri: str) -> str:
    from google_auth_oauthlib.flow import Flow

    if not CLIENT_SECRET_PATH.exists():
        raise PublishError("Upload your Google OAuth client JSON first (YouTube Accounts > API setup).")
    flow = Flow.from_client_secrets_file(str(CLIENT_SECRET_PATH), scopes=SCOPES, redirect_uri=redirect_uri)
    url, state = flow.authorization_url(access_type="offline", prompt="consent", include_granted_scopes="true")
    _pending_flows[state] = flow
    return url


def finish_auth(state: str, code: str) -> dict:
    flow = _pending_flows.pop(state, None)
    if not flow:
        raise PublishError("OAuth session expired or unknown. Click 'Connect YouTube account' again.")
    flow.fetch_token(code=code)
    creds = flow.credentials
    yt = _client(creds)
    items = yt.channels().list(part="snippet", mine=True).execute().get("items", [])
    if not items:
        raise PublishError("This Google account has no YouTube channel. Create a channel on youtube.com first.")
    ch = items[0]
    with session() as s:
        acc = s.query(YouTubeAccount).filter_by(channel_id=ch["id"]).first() or YouTubeAccount(channel_id=ch["id"])
        acc.channel_title = ch["snippet"]["title"]
        acc.thumbnail_url = ch["snippet"].get("thumbnails", {}).get("default", {}).get("url")
        acc.token = secure.encrypt(creds.to_json().encode())
        s.add(acc)
        s.flush()
        return acc.to_dict()


def _client(creds):
    from googleapiclient.discovery import build

    return build("youtube", "v3", credentials=creds, cache_discovery=False)


def _credentials(account_id: int):
    from google.auth.exceptions import RefreshError
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials

    with session() as s:
        acc = s.get(YouTubeAccount, account_id)
        if not acc:
            raise PublishError("YouTube account was disconnected.")
        creds = Credentials.from_authorized_user_info(json.loads(secure.decrypt(acc.token)), SCOPES)
    if not creds.valid:
        try:
            creds.refresh(Request())
        except RefreshError as e:
            raise PublishError("YouTube authorization expired or was revoked - reconnect this account in YouTube Accounts. "
                               "(Google expires tokens after 7 days while the OAuth app is in 'Testing' mode.) " + str(e)[:120])
        with session() as s:
            s.get(YouTubeAccount, account_id).token = secure.encrypt(creds.to_json().encode())
    return creds


def explain_http_error(e) -> str:
    try:
        err = json.loads(e.content.decode())["error"]
        reason = (err.get("errors") or [{}])[0].get("reason", "")
        msg = err.get("message", "")
    except Exception:
        reason, msg = "", str(e)
    hints = {
        "quotaExceeded": "Daily YouTube API quota exhausted (default 10,000 units/day, an upload costs ~1,600). "
                         "Quota resets at midnight Pacific Time.",
        "uploadLimitExceeded": "This channel has hit YouTube's upload limit. Try again in 24 hours.",
        "invalidPublishAt": "Scheduled time is invalid - it must be in the future.",
        "youtubeSignupRequired": "This Google account has no YouTube channel.",
        "insufficientPermissions": "Missing permissions - reconnect the account and approve all requested YouTube access.",
        "forbidden": "YouTube refused the request. The account may not be allowed to upload, or the API project lacks access.",
        "accessNotConfigured": "YouTube Data API v3 is not enabled for your Google Cloud project. Enable it in the API Library.",
        "uploadRateLimitExceeded": "Uploading too fast - wait a few minutes.",
    }
    return f"{hints.get(reason, 'YouTube API error')} [{reason or e.resp.status}] {msg}".strip()


def upload(account_id: int, video_path: str, title: str, description: str, tags: list[str], privacy: str,
           publish_at: datetime | None, made_for_kids: bool, progress=None) -> dict:
    from googleapiclient.errors import HttpError
    from googleapiclient.http import MediaFileUpload

    yt = _client(_credentials(account_id))
    status = {"privacyStatus": "private" if publish_at else privacy, "selfDeclaredMadeForKids": made_for_kids}
    if publish_at:
        status["publishAt"] = publish_at.strftime("%Y-%m-%dT%H:%M:%S.000Z")
    body = {"snippet": {"title": title[:100], "description": description[:5000], "tags": tags, "categoryId": "22"},
            "status": status}
    media = MediaFileUpload(video_path, mimetype="video/mp4", chunksize=8 * 1024 * 1024, resumable=True)
    req = yt.videos().insert(part="snippet,status", body=body, media_body=media)
    response, retries = None, 0
    while response is None:
        try:
            st, response = req.next_chunk()
            if st and progress:
                progress(st.progress())
            retries = 0
        except HttpError as e:
            if e.resp.status in (500, 502, 503, 504) and retries < 6:
                retries += 1
                time.sleep(min(60, 2 ** retries + random.random()))
                continue
            raise PublishError(explain_http_error(e))
        except (ConnectionError, TimeoutError, OSError) as e:
            if retries < 6:
                retries += 1
                time.sleep(min(60, 2 ** retries + random.random()))
                continue
            raise PublishError(f"Network error during upload: {e}")
    if "id" not in response:
        raise PublishError(f"Upload finished without a video id: {response}")
    return response


def video_status(account_id: int, video_id: str) -> dict | None:
    from googleapiclient.errors import HttpError

    try:
        items = _client(_credentials(account_id)).videos().list(part="status", id=video_id).execute().get("items", [])
    except HttpError as e:
        raise PublishError(explain_http_error(e))
    return items[0]["status"] if items else None


def update_schedule(account_id: int, video_id: str, publish_at: datetime | None, made_for_kids: bool):
    """Reschedule (publish_at) or cancel (None -> stays private) a YouTube-managed scheduled video."""
    from googleapiclient.errors import HttpError

    status = {"privacyStatus": "private", "selfDeclaredMadeForKids": made_for_kids}
    if publish_at:
        status["publishAt"] = publish_at.strftime("%Y-%m-%dT%H:%M:%S.000Z")
    try:
        _client(_credentials(account_id)).videos().update(part="status", body={"id": video_id, "status": status}).execute()
    except HttpError as e:
        raise PublishError(explain_http_error(e))
