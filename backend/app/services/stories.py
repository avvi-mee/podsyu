"""Story sources for the ASMR engine: Reddit (official OAuth API), the user's own stories, and original
AI-written fiction. Every story records where it came from and whether it may be used."""
import re
import time
from datetime import datetime, timezone

import httpx

from app.ai import llm
from app.core import secure

CATEGORIES = {
    "dark": "dark, unsettling true-to-life story", "dark_humour": "darkly funny story with an absurd twist",
    "funny": "funny, relatable story with a great punchline", "scary": "scary story that builds dread",
    "relationship": "relationship / dating drama story", "confession": "confession someone has never told anyone",
    "mystery": "mysterious story with an unexplained ending", "life": "interesting real-life style experience",
    "unexpected": "story with a completely unexpected ending",
}
SUBREDDITS = {"dark": ["TrueOffMyChest", "confessions"], "dark_humour": ["tifu"], "funny": ["tifu", "AskReddit"],
              "scary": ["nosleep", "LetsNotMeet"], "relationship": ["AmItheAsshole", "relationship_advice"],
              "confession": ["confessions", "TrueOffMyChest"], "mystery": ["UnresolvedMysteries", "Glitch_in_the_Matrix"],
              "life": ["AskReddit", "tifu"], "unexpected": ["tifu", "AmItheAsshole"]}
SENSITIVE = re.compile(r"\b(suicid\w*|self[- ]harm|rape\w*|molest\w*|child abuse|overdos\w*)\b", re.I)
UA = "windows:podsyu-shorts-factory:v2.0 (local app)"
_token: dict = {}


class StoryError(RuntimeError):
    pass


def suitability(title: str, body: str, nsfw: bool = False) -> str:
    if nsfw:
        return "nsfw"
    if SENSITIVE.search(f"{title} {body}"):
        return "sensitive"
    if len(body.split()) < 80:
        return "too short"
    return "ok"


# ---------- Reddit (official API, app-only OAuth) ----------

def reddit_configured() -> bool:
    return bool(secure.get_key("reddit_client_id") and secure.get_key("reddit_client_secret"))


def _reddit_token() -> str:
    if _token.get("exp", 0) > time.time() + 60:
        return _token["access_token"]
    cid, secret = secure.get_key("reddit_client_id"), secure.get_key("reddit_client_secret")
    if not (cid and secret):
        raise StoryError("Reddit API is not connected. Add your free Reddit app's client ID and secret in Settings "
                         "(reddit.com/prefs/apps -> create app -> 'script').")
    r = httpx.post("https://www.reddit.com/api/v1/access_token", auth=(cid, secret), headers={"User-Agent": UA},
                   data={"grant_type": "client_credentials"}, timeout=20)
    if r.status_code != 200 or "access_token" not in r.json():
        raise StoryError(f"Reddit rejected the API credentials ({r.status_code}). Check the client ID/secret in Settings.")
    _token.update(r.json(), exp=time.time() + r.json().get("expires_in", 3600))
    return _token["access_token"]


def discover(subreddit: str = "", keyword: str = "", category: str = "", sort: str = "top", period: str = "week",
             min_score: int = 0, min_comments: int = 0, limit: int = 40) -> list[dict]:
    """Text posts from Reddit's API with real score/comment counts. Nothing is invented."""
    if sort not in ("hot", "top", "new"):
        raise ValueError("sort must be hot, top or new")
    if period not in ("hour", "day", "week", "month", "year", "all"):
        raise ValueError("period must be hour, day, week, month, year or all")
    subs = [subreddit.strip().removeprefix("r/")] if subreddit.strip() else SUBREDDITS.get(category, ["AskReddit"])
    if not all(re.fullmatch(r"\w{2,21}", s) for s in subs):
        raise ValueError("Invalid subreddit name")
    headers = {"Authorization": f"bearer {_reddit_token()}", "User-Agent": UA}
    out = []
    for sub in subs:
        if keyword.strip():
            url, params = f"https://oauth.reddit.com/r/{sub}/search", {"q": keyword.strip()[:100], "restrict_sr": 1,
                                                                        "sort": "top" if sort == "top" else sort, "t": period}
        else:
            url, params = f"https://oauth.reddit.com/r/{sub}/{sort}", {"t": period}
        r = httpx.get(url, params={**params, "limit": min(100, limit)}, headers=headers, timeout=30)
        if r.status_code == 429:
            raise StoryError("Reddit API rate limit reached - wait a minute and try again.")
        if r.status_code != 200:
            raise StoryError(f"Reddit API error {r.status_code} for r/{sub}")
        for c in r.json().get("data", {}).get("children", []):
            d = c.get("data", {})
            body = (d.get("selftext") or "").strip()
            if not d.get("is_self") or not body or body in ("[removed]", "[deleted]"):
                continue
            if (d.get("score") or 0) < min_score or (d.get("num_comments") or 0) < min_comments:
                continue
            out.append({"source_type": "reddit", "title": d.get("title", "")[:300], "body": body[:20000],
                        "subreddit": d.get("subreddit"), "author": d.get("author"),
                        "url": "https://www.reddit.com" + d.get("permalink", ""), "score": d.get("score"),
                        "num_comments": d.get("num_comments"), "nsfw": bool(d.get("over_18")),
                        "posted_at": datetime.fromtimestamp(d.get("created_utc", 0), timezone.utc).replace(tzinfo=None),
                        "category": category or "life", "permission": "needs_permission",
                        "attribution": f"Story by u/{d.get('author')} on r/{d.get('subreddit')}"})
    return out


# ---------- LLM: original stories and short-form scripts ----------

STORY_SCHEMA = {"type": "object", "properties": {"title": {"type": "string"}, "story": {"type": "string"}},
                "required": ["title", "story"]}
SCRIPT_SCHEMA = {"type": "object", "properties": {"script": {"type": "string"}, "hook": {"type": "string"}},
                 "required": ["script", "hook"]}


def write_original(category: str, idea: str, settings: dict) -> dict:
    """An ORIGINAL fictional story (not copied from anyone), optionally inspired by the user's idea/theme."""
    kind = CATEGORIES.get(category, "interesting story")
    prompt = f"""Write an ORIGINAL first-person short story: a {kind}.
{('Inspiration / theme from the user: ' + idea.strip()[:600]) if idea.strip() else 'Pick a fresh, specific situation.'}

Rules: completely original fiction (do not retell a known story or real event), no real people's names, 220-350 words,
concrete details, a strong first line, rising tension, and a memorable ending or twist. Plain conversational English.
Return a short catchy title and the story."""
    data = llm.chat_json(settings, "You are a gifted short-story writer for viral storytelling videos. Answer only with JSON.",
                         prompt, STORY_SCHEMA, temperature=0.9, max_tokens=900, long_text=True)
    story = llm.dedupe_sentences((data.get("story") or "").strip())
    for _ in range(2):  # small local models often stop early: ask them to expand, keeping the same plot
        if len(story.split()) >= 180:
            break
        expand = (f"Expand this story to 260-340 words. Keep the same plot, narrator and ending; add concrete "
                  f"sensory details and tension.\n\nTitle: {data.get('title')}\nStory:\n{story}")
        more = llm.chat_json(settings, "You are a gifted short-story writer. Answer only with JSON.", expand,
                             STORY_SCHEMA, temperature=0.7, max_tokens=900, long_text=True)
        if len((more.get("story") or "").split()) > len(story.split()):
            story = llm.dedupe_sentences(more["story"].strip())
    if len(story.split()) < 80:
        raise StoryError("The AI returned a story that was too short - try again.")
    return {"source_type": "ai_original", "title": (data.get("title") or "Untitled story").strip()[:200], "body": story,
            "category": category, "permission": "not_required", "attribution": "Original story written with local AI (fiction)"}


STAGE = re.compile(r"^\W*(\[.*?\]|\(.*?\)|the end\b|fade (out|in|to)\b|cut to\b|credits roll|scene \d+|narrator:)", re.I)


def clean_script(text: str, target_words: int) -> str:
    """Narration only: drop stage directions/timestamps, stop at any repetition loop, and trim overlong
    scripts at a sentence boundary (max ~130% of the target length)."""
    text = re.sub(r"\[[^\]]*\]", " ", text)  # [0s-5s] style markers anywhere
    sentences = [x for x in re.split(r"(?<=[.!?])\s+", llm.dedupe_sentences(re.sub(r"\s+", " ", text)))
                 if x.strip() and not STAGE.match(x)]
    out, count = [], 0
    for sent in sentences:
        n = len(sent.split())
        if out and count + n > target_words * 1.3:
            break
        out.append(sent.strip())
        count += n
    return " ".join(out)


def adapt(title: str, body: str, seconds: int, settings: dict) -> dict:
    """Short-form narration script: hook -> setup -> incident -> escalation -> twist/ending."""
    words = int(seconds * 2.6)
    prompt = f"""Turn this story into a narration script for a {seconds}-second vertical video (about {words} words, +-10%).

Structure: 1) a gripping first sentence (hook) 2) quick setup 3) the main incident 4) escalation 5) twist or memorable ending.
Rules: first person, natural spoken English, short sentences, no greetings or "today I'll tell you", no hashtags or emojis,
no stage directions or timestamps (never "cut to", "fade out", "the end", "[0s-5s]") - only the words the narrator says,
remove repetition, keep the important facts and meaning, do not add new events or present invented details as fact.
"hook" = the first sentence of the script.

Title: {title}
Story:
\"\"\"{body[:6000]}\"\"\""""
    data = llm.chat_json(settings, "You adapt stories into tight, gripping short-form narration. Answer only with JSON.",
                         prompt, SCRIPT_SCHEMA, temperature=0.5, max_tokens=600, long_text=True)
    script = clean_script(data.get("script") or "", words)
    if len(script.split()) < max(25, words // 3):
        raise StoryError("The AI returned a script that was too short - try again.")
    return {"script": script, "hook": (data.get("hook") or script.split(".")[0]).strip()}
