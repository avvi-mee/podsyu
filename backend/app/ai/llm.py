"""Local LLM (Ollama) calls: podcast moment detection and short metadata."""
import json
import logging
import math
import re

import httpx

log = logging.getLogger(__name__)

CATEGORIES = ["hook", "opinion", "controversial", "surprising fact", "emotional", "educational",
              "funny", "inspirational", "story", "advice"]
STRATEGIES = {
    "balanced": "Balance all qualities; pick the moments most likely to keep a viewer watching to the end.",
    "hooks": "Prioritise moments whose very first sentence is an irresistible hook.",
    "viral": "Prioritise bold, controversial, surprising or emotional moments with high share potential.",
    "educational": "Prioritise clear explanations, insights and actionable advice a viewer can learn from.",
    "story": "Prioritise complete stories and anecdotes with a setup and a payoff.",
}
# A clip should not open with a word that only makes sense after earlier context.
DANGLING = re.compile(r"^(and|but|so|because|or|which|that's why|that is why|also|then|plus|anyway|yeah|"
                      r"he|she|they|them|it|its|it's|this|that|those|these|exactly|right|here's|another|"
                      r"second(ly)?|third(ly)?|finally|the other)\b", re.I)
INTERJECTION = re.compile(r"^(hmm+|um+|uh+|oh|ah+|mm+|er+)\b", re.I)
# The host's set-up for the NEXT question ("You said ... ." then "What do you...?") is not a clip ending.
REFERS_BACK = re.compile(r"(^(one|the first|the second|the other( one)?|the next) (is|was|thing)\b)|(\b(either|as well)\W*$)", re.I)


def needs_context(text: str) -> bool:
    """Opening line that only makes sense after something earlier ("And...", "One is...", "...either.")."""
    return bool(DANGLING.match(text) or REFERS_BACK.search(text.strip()))


HOST_SETUP = re.compile(r"^(so,? )?you (said|mentioned|talked|told|wrote|were|have|'ve|once|also)\b", re.I)


class LLMError(RuntimeError):
    pass


def _url(settings) -> str:
    return settings["ollama_url"].rstrip("/")


def status(settings) -> dict:
    try:
        r = httpx.get(f"{_url(settings)}/api/tags", timeout=4)
        r.raise_for_status()
        return {"available": True, "models": [m["name"] for m in r.json().get("models", [])]}
    except Exception as e:
        return {"available": False, "models": [], "error": str(e)}


def dedupe_sentences(text: str) -> str:
    """Cut a text at the first sentence that repeats an earlier one (small models can loop forever)."""
    seen, out = set(), []
    for sent in re.split(r"(?<=[.!?])\s+", text.strip()):
        key = re.sub(r"\W+", " ", sent.lower()).strip()
        if key and key in seen:
            break
        seen.add(key)
        out.append(sent)
    return " ".join(out).strip()


def _salvage(content: str, schema: dict) -> dict | None:
    """Recover string/integer fields from a truncated or slightly broken JSON answer."""
    props, out = schema.get("properties", {}), {}
    for k, spec in props.items():
        if spec.get("type") == "string":
            m = re.search(rf'"{k}"\s*:\s*"((?:[^"\\]|\\.)*)"', content, re.S)
            if m:
                out[k] = json.loads(f'"{m.group(1)}"')
            else:  # unterminated string (cut off by the length cap): keep what's there, minus any loop
                m = re.search(rf'"{k}"\s*:\s*"((?:[^"\\]|\\.)*)$', content, re.S)
                if m:
                    out[k] = dedupe_sentences(m.group(1).replace('\\"', '"').replace("\\n", " "))
        elif spec.get("type") == "integer":
            m = re.search(rf'"{k}"\s*:\s*(-?\d+)', content)
            if m:
                out[k] = int(m.group(1))
    required = schema.get("required", [])
    if any(props.get(k, {}).get("type") not in ("string", "integer") for k in required):
        return None  # arrays/objects can't be salvaged reliably
    return out if all(k in out for k in required[:1]) else None


def chat_json(settings: dict, system: str, prompt: str, schema: dict, temperature: float = 0.4,
              max_tokens: int = 1500, long_text: bool = False) -> dict:
    """JSON-constrained chat. Output is capped (`max_tokens`): small models can otherwise loop (or emit endless
    whitespace inside the JSON grammar) until the context fills. Broken answers are salvaged or retried once.
    long_text=True adds a repetition penalty for prose (stories, scripts)."""
    for attempt in range(2):
        options = {"temperature": temperature + 0.15 * attempt, "num_ctx": int(settings.get("ollama_num_ctx", 8192)),
                   "num_predict": max_tokens}
        if long_text:
            options.update(repeat_penalty=1.18, repeat_last_n=256)
        body = {
            "model": settings["ollama_model"],
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": prompt}],
            "format": schema, "stream": False, "keep_alive": "10m", "options": options,
        }
        try:
            r = httpx.post(f"{_url(settings)}/api/chat", json=body, timeout=600)
        except httpx.ConnectError:
            raise LLMError(f"Cannot reach Ollama at {settings['ollama_url']}. Start Ollama (run 'ollama serve') and retry.")
        if r.status_code == 404 and "not found" in r.text:
            raise LLMError(f"Ollama model '{settings['ollama_model']}' is not installed. Run: ollama pull {settings['ollama_model']}")
        if r.status_code != 200:
            raise LLMError(f"Ollama error {r.status_code}: {r.text[:300]}")
        content = r.json().get("message", {}).get("content", "")
        try:
            return json.loads(content)
        except json.JSONDecodeError:
            m = re.search(r"\{.*\}", content, re.S)
            if m:
                try:
                    return json.loads(m.group(0))
                except json.JSONDecodeError:
                    pass
            saved = _salvage(content, schema)
            if saved:
                log.warning("Salvaged a truncated/looping model answer (%d chars)", len(content))
                return saved
            log.warning("Model returned unusable JSON (attempt %d): %s", attempt + 1, content[:120].replace("\n", " "))
    raise ValueError("The local AI returned an unusable answer twice - try again or use a larger model.")


def unload(settings):
    """Free VRAM held by Ollama before GPU-heavy rendering."""
    try:
        httpx.post(f"{_url(settings)}/api/generate", json={"model": settings["ollama_model"], "keep_alive": 0}, timeout=15)
    except Exception:
        pass


def _fmt(t: float) -> str:
    return f"{int(t // 60)}:{int(t % 60):02d}"


MOMENT_SCHEMA = {
    "type": "object",
    "properties": {"moments": {"type": "array", "items": {"type": "object", "properties": {
        "start_index": {"type": "integer"}, "end_index": {"type": "integer"},
        "hook": {"type": "string"}, "title": {"type": "string"},
        "category": {"type": "string", "enum": CATEGORIES}, "reason": {"type": "string"},
        "score": {"type": "integer", "minimum": 1, "maximum": 100},
    }, "required": ["start_index", "end_index", "hook", "title", "category", "reason", "score"]}}},
    "required": ["moments"],
}

SYSTEM_MOMENTS = ("You are a senior short-form video editor. You find self-contained, highly engaging moments in "
                  "podcast transcripts that work as standalone YouTube Shorts. You answer only with JSON.")


def _windows(sentences: list[dict], max_words=1400, overlap=8) -> list[list[dict]]:
    wins, cur, words = [], [], 0
    for s in sentences:
        cur.append(s)
        words += len(s["text"].split())
        if words >= max_words:
            wins.append(cur)
            cur = cur[-overlap:]
            words = sum(len(x["text"].split()) for x in cur)
    if cur and (not wins or len(cur) > overlap):
        wins.append(cur)
    return wins


FILLER = re.compile(r"^(okay|ok|yeah|yes|yep|right|so|well|um+|uh+|hmm+|mm+|interesting|great|good|nice|cool|sure|"
                    r"exactly|absolutely|totally|wow|amazing|correct|true|fair|thanks|thank you|let's do it|"
                    r"good question|great question|that's a good question)\b[\s\w,']{0,25}[.!?]*$", re.I)
JUNK = re.compile(r"\b(sponsor\w*|partner for this episode|styling partner|brought to you by|subscribe|hit the bell|"
                  r"comments? (below|section)|in the comments|link in (the )?description|use (the )?code|discount code|"
                  r"watch this episode|enjoy the (show|episode|conversation)|this episode is|today's episode|in this episode|by the end of (this|the) (episode|podcast|video)|"
                  r"welcome (back )?to (the|my|our) (show|podcast|channel))\b", re.I)
# A sentence that wraps up the thought: if it directly follows the chosen end, the clip should include it.
CONCLUDE = re.compile(r"^(so,? (i think|that's|basically|yeah)|that's (why|how|the (point|thing|reason))|which is why|"
                      r"the (point|lesson|key|reason|answer) is|and that's (why|how)|in the end|at the end of the day|"
                      r"bottom line|long story short)\b", re.I)
TERMINAL = (".", "!", "?", '."', '!"', '?"')

REFINE_SCHEMA = {
    "type": "object",
    "properties": {"start_index": {"type": "integer"}, "end_index": {"type": "integer"},
                   "hook": {"type": "integer", "minimum": 1, "maximum": 10},
                   "standalone": {"type": "integer", "minimum": 1, "maximum": 10},
                   "payoff": {"type": "integer", "minimum": 1, "maximum": 10},
                   "payoff_index": {"type": "integer"},
                   "keep": {"type": "boolean"}, "reason": {"type": "string"}},
    "required": ["start_index", "payoff_index", "end_index", "hook", "standalone", "payoff", "keep", "reason"],
}


def find_moments(sentences: list[dict], opts: dict, meta: dict, settings: dict, progress=None) -> list[dict]:
    """Pass 1 scans the transcript for rough candidates. Pass 2 refines each candidate's exact start/end and
    scores hook, standalone-ness and payoff. select_clips then enforces sentence/duration rules in code."""
    lo, hi, n = opts["min_duration"], opts["max_duration"], opts["num_shorts"]
    wins = _windows(sentences)
    per_win = max(3, math.ceil(n * 2.5 / len(wins)))
    strategy = STRATEGIES.get(opts.get("strategy", "balanced"), STRATEGIES["balanced"])
    category = opts.get("category") or "any"
    say = progress or (lambda f, m: None)
    candidates = []
    for wi, win in enumerate(wins):
        say(0.5 * wi / len(wins), f"AI is scanning transcript part {wi + 1}/{len(wins)}")
        lines = "\n".join(f"[{s['i']}] ({_fmt(s['start'])}, {s['end'] - s['start']:.0f}s) {s['text']}" for s in win)
        prompt = f"""Podcast: "{meta.get('title', '')}" {('by ' + meta['channel']) if meta.get('channel') else ''}
Preferred content: {category}. Strategy: {strategy}

Each transcript line is one sentence: [index] (start time, sentence length) text.
Find up to {per_win} of the BEST moments for standalone YouTube Shorts lasting {lo}-{hi} seconds.

Rules:
- A moment is a continuous range of sentences from start_index to end_index (inclusive). Add up the sentence lengths: the total must be {lo}-{hi} seconds.
- start_index must be the HOOK: the single most gripping line (bold claim, surprising fact, strong opinion, or a question the clip then answers) that a stranger understands with zero prior context. Never start on filler ("okay", "so yeah"), small talk, or a sentence that refers back ("And", "That's why", "He", "It").
- end_index must be the PAYOFF: the conclusion, punchline or final point. Never end on a new question, filler, or mid-thought.
- Prefer: surprising facts, bold or controversial opinions, emotional or funny moments, complete stories, actionable advice, clear explanations.
- Never pick ads, sponsor reads, intros/outros, "subscribe/comment" requests or greetings. Returning fewer moments is fine.
- "hook": copy the start sentence. "title": a punchy short title. "reason": why it works. "score": 1-100, be critical and use the full range.

Transcript:
{lines}"""
        try:  # connection/model errors (LLMError) abort; a bad answer for one window is skipped
            data = chat_json(settings, SYSTEM_MOMENTS, prompt, MOMENT_SCHEMA, temperature=0.3)
        except (ValueError, KeyError, TypeError) as e:
            log.warning("Moment detection returned unusable output for window %d: %s", wi, e)
            continue
        ids = {s["i"] for s in win}
        candidates += [m for m in data.get("moments", []) if m.get("start_index") in ids and m.get("end_index") in ids]

    # Refine the most promising distinct candidates (one focused LLM call each).
    candidates.sort(key=lambda c: c.get("score") or 0, reverse=True)
    distinct = []
    for c in candidates:
        a, b = sorted((c["start_index"], c["end_index"]))
        if not any(min(b, d["_b"]) - max(a, d["_a"]) > 0.6 * (b - a + 1) for d in distinct):
            distinct.append({**c, "_a": a, "_b": b})
    distinct = distinct[:max(6, n * 3)]
    refined = []
    for k, c in enumerate(distinct):
        say(0.5 + 0.5 * k / max(1, len(distinct)), f"AI is fine-tuning hook & ending {k + 1}/{len(distinct)}")
        r = _refine(sentences, c, lo, hi, meta, settings)
        if r:
            refined.append(r)
    return select_clips(refined, sentences, lo, hi, n, content_bounds(sentences))


def content_bounds(S: list[dict]) -> tuple[float, float]:
    """Time range of the actual conversation: after the intro/teaser (which ends with 'comment below', sponsor,
    'today's episode'... lines in the first 15%) and before the outro (same kind of lines in the last 10%)."""
    if not S:
        return 0.0, 0.0
    total = S[-1]["end"]
    intro = [s["end"] for s in S if s["start"] < 0.15 * total and JUNK.search(s["text"])]
    outro = [s["start"] for s in S if s["start"] > 0.9 * total and JUNK.search(s["text"])]
    return (max(intro) if intro else 0.0), (min(outro) if outro else total + 1)


def _refine(S: list[dict], c: dict, lo: float, hi: float, meta: dict, settings: dict) -> dict | None:
    a, b = c["_a"], c["_b"]
    i0, i1 = max(0, a - 10), min(len(S) - 1, b + 10)
    lines = "\n".join(f"{'>>' if a <= i <= b else '  '} [{i}] ({S[i]['end'] - S[i]['start']:.0f}s) {S[i]['text']}"
                      for i in range(i0, i1 + 1))
    prompt = f"""You are cutting ONE YouTube Short ({lo}-{hi} seconds) from the podcast "{meta.get('title', '')}".
Lines are sentences: [index] (length) text. A rough pick is marked with >>. Choose the exact best start_index and end_index.

- START on the most gripping line a stranger understands with zero context: a bold claim, surprising fact, strong opinion, or a question the clip then answers. Skip filler, throat-clearing, host small talk and lines that refer back to earlier context.
- payoff_index: the sentence that delivers the answer, conclusion or punchline of this clip.
- END at or right after payoff_index. Never end on a setup ("...and it sounded so convincing.") when the next lines explain it, never on a new question, filler, or mid-thought. If the next sentence starts with "So I think", "That's why", "The point is", it is the conclusion - include it.
- Sum of sentence lengths from start to end must be {lo}-{hi}s. You may move outside the >> lines.
- Rate honestly 1-10: hook (do the first 3 seconds grab attention?), standalone (makes sense with zero context?), payoff (satisfying ending?).
- keep=false if this is an ad/sponsor/intro/outro/episode teaser or has no strong self-contained moment.
- reason: one sentence about THIS clip only.

{lines}"""
    try:
        r = chat_json(settings, SYSTEM_MOMENTS, prompt, REFINE_SCHEMA, temperature=0.2)
    except (ValueError, KeyError, TypeError) as e:
        log.warning("Refinement failed, keeping rough pick: %s", e)
        return {**c, "start_index": a, "end_index": b, "score": int((c.get("score") or 50) * 0.8)}
    if not r.get("keep", True):
        return None
    si, ei, pi = r.get("start_index"), r.get("end_index"), r.get("payoff_index")
    if not (isinstance(si, int) and isinstance(ei, int) and i0 <= si <= ei <= i1):
        si, ei = a, b
    if isinstance(pi, int) and si <= pi <= i1:
        ei = max(ei, pi)  # the clip must contain its payoff
    hook, alone, pay = (max(1, min(10, int(r.get(k) or 5))) for k in ("hook", "standalone", "payoff"))
    if alone < 5 or hook < 4:
        return None
    return {**c, "start_index": si, "end_index": ei, "score": 4 * hook + 3 * alone + 3 * pay,
            "reason": r.get("reason") or c.get("reason", "")}


def _is_start(S: list[dict], i: int) -> bool:
    t = S[i]["text"].lstrip("\"'([ ")
    weak = len(t.split()) < 6 and not t.rstrip().endswith("?")  # "Something I want to do." can't hook anyone
    return ((i == 0 or S[i - 1]["text"].rstrip().endswith(TERMINAL)) and bool(t) and (t[0].isupper() or t[0].isdigit())
            and not weak and not INTERJECTION.match(t) and not FILLER.match(S[i]["text"])
            and not JUNK.search(S[i]["text"]))


def _is_end(S: list[dict], i: int) -> bool:
    t = S[i]["text"].rstrip()
    host_setup = HOST_SETUP.match(t) and i + 1 < len(S) and S[i + 1]["text"].rstrip().endswith("?")
    return (t.endswith((".", "!", '."', '!"')) and not t.endswith("...") and not FILLER.match(t)
            and not JUNK.search(t) and not host_setup)


def _snap(S: list[dict], a: int, b: int, lo: float, hi: float) -> tuple[int, int] | None:
    """Nearest valid (start, end): a real sentence start that isn't filler, and a completed statement (not a
    question/filler) as close as possible to the chosen payoff, with the total length inside [lo, hi]."""
    order = (a - 1, a - 2, a, a + 1, a + 2, a + 3) if needs_context(S[a]["text"]) else (a, a + 1, a + 2, a + 3, a - 1, a - 2)
    for i in order:
        if not (0 <= i < len(S)) or not _is_start(S, i):
            continue
        ends = [j for j in range(i, len(S)) if lo <= S[j]["end"] - S[i]["start"] <= hi and _is_end(S, j)
                and (j == i or not (S[j - 1]["text"].rstrip().endswith("?") or FILLER.match(S[j - 1]["text"])))]
        if not ends:
            continue
        j = min(ends, key=lambda j: (j < b, abs(j - b)))  # prefer ending at/after the payoff, never before if avoidable
        # Pull in a directly following wrap-up sentence ("So I think...", "That's why...") when it fits.
        while j + 1 < len(S) and CONCLUDE.match(S[j + 1]["text"]):
            nxt = [k for k in ends if j < k <= j + 3]
            if not nxt:
                break
            j = nxt[0]
        return i, j
    return None


def select_clips(candidates: list[dict], sentences: list[dict], lo: float, hi: float, n: int,
                 bounds: tuple[float, float] | None = None) -> list[dict]:
    """Enforce clean boundaries and duration, drop ads/intros, dedupe overlaps and rank."""
    S = sentences
    first, last = bounds or (0.0, float("inf"))
    fixed = []
    for c in candidates:
        span = _snap(S, *sorted((int(c["start_index"]), int(c["end_index"]))), lo, hi)
        if not span:
            continue
        a, b = span
        text = " ".join(s["text"] for s in S[a:b + 1])
        if JUNK.search(text) or S[a]["start"] < first or S[b]["end"] > last:
            continue  # sponsor read / intro teaser / outro / call-to-action
        penalty = 15 if needs_context(S[a]["text"]) else 0  # opening still leans on earlier context
        hook = S[a]["text"] if len(S[a]["text"].split()) >= 6 or a == b else f"{S[a]['text']} {S[a + 1]['text']}"
        start = max(S[a]["start"] - 0.15, S[a - 1]["end"] if a else 0.0, 0.0)
        end = min(S[b]["end"] + 0.35, S[b + 1]["start"] if b + 1 < len(S) else S[b]["end"] + 0.35)
        fixed.append({**c, "a": a, "b": b, "start": round(start, 3), "end": round(end, 3), "transcript": text,
                      "hook": hook, "score": max(1, min(100, int(c.get("score") or 50) - penalty))})
    fixed.sort(key=lambda c: c["score"], reverse=True)
    chosen = []
    for c in fixed:
        overlap = any(min(c["end"], o["end"]) - max(c["start"], o["start"]) > 0.3 * (c["end"] - c["start"]) for o in chosen)
        if not overlap:
            chosen.append(c)
        if len(chosen) >= n:
            break
    return chosen


META_SCHEMA = {
    "type": "object",
    "properties": {"title": {"type": "string"}, "description": {"type": "string"},
                   "hashtags": {"type": "array", "items": {"type": "string"}}},
    "required": ["title", "description", "hashtags"],
}


KINDS = {  # engine -> (what the text is, what the description should do, fixed hashtags)
    "podcast": ("clip from the podcast", "describing what the speaker says", "#Shorts and #Podcast"),
    "creator": ("entertaining clip from the video", "describing the funny/surprising moment", "#Shorts and #Funny"),
    "story": ("narrated story short titled", "teasing the story without spoiling the ending", "#Shorts and #StoryTime"),
    "cutting": ("satisfying 3D ASMR knife-cutting video", "describing what gets sliced and the satisfying ending", "#Shorts and #ASMR"),
}


def generate_metadata(transcript: str, meta: dict, settings: dict, temperature=0.5, kind: str = "podcast") -> dict:
    what, desc_rule, fixed = KINDS.get(kind, KINDS["podcast"])
    prompt = f"""Write YouTube Shorts metadata for this {what} "{meta.get('title', '')}"{(' by ' + meta['channel']) if meta.get('channel') else ''}.

Transcript:
\"\"\"{transcript[:4000]}\"\"\"

- title: max 70 characters, normal words separated by spaces (never CamelCase), punchy and curiosity-driven, strictly accurate to what is actually said (do not reinterpret the topic), never include the source video or file name, no hashtags, at most one emoji.
- description: 1-2 sentences {desc_rule}. Use a person's name only if it is clear from the transcript or title.
- hashtags: 5-8 hashtags specific to the actual topics, people and ideas (CamelCase, never ALL CAPS, no spaces, names spelled exactly as in the transcript), plus {fixed}."""
    data = chat_json(settings, "You are a YouTube growth expert who writes accurate, engaging metadata. Answer only with JSON.",
                     prompt, META_SCHEMA, temperature)
    title = re.sub(r"\s*#\w+", "", data.get("title", "")).strip().strip('"')
    if " " not in title and len(title) > 15:  # model squashed it into CamelCase: split the words again
        title = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", title)
    return {"title": title[:100],
            "description": re.sub(r"\s*#\w+", "", data.get("description", "")).strip()[:4500],  # tags are added separately
            "hashtags": clean_hashtags(data.get("hashtags", []))}


def clean_hashtags(tags) -> str:
    if isinstance(tags, str):
        tags = tags.replace(",", " ").split()
    out = []
    for t in tags:
        t = "#" + re.sub(r"[^\w]", "", str(t))
        if len(t) > 1 and t.lower() not in {o.lower() for o in out}:
            out.append(t)
    return " ".join(out[:12])
