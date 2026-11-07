"""Caption presets and ASS subtitle generation with word-level highlighting."""
import re

PRESETS: dict[str, dict] = {
    "hormozi": {"name": "Hormozi Style", "font": "Arial Black", "font_size": 84, "bold": True, "italic": False,
                "uppercase": True, "text_color": "#FFFFFF", "highlight_color": "#FFE600", "highlight": True,
                "outline_color": "#000000", "outline_width": 7, "shadow": 0, "position": "lower",
                "words_per_line": 3, "animation": "pop", "background": "none", "background_color": "#000000",
                "letter_spacing": 0},
    "podcast_premium": {"name": "Podcast Premium", "font": "Segoe UI Semibold", "font_size": 64, "bold": False,
                        "italic": False, "uppercase": False, "text_color": "#FFFFFF", "highlight_color": "#C4B5FD",
                        "highlight": True, "outline_color": "#111111", "outline_width": 2.5, "shadow": 4,
                        "position": "lower", "words_per_line": 5, "animation": "fade", "background": "none",
                        "background_color": "#000000", "letter_spacing": 0},
    "mrbeast": {"name": "MrBeast Inspired", "font": "Impact", "font_size": 104, "bold": False, "italic": False,
                "uppercase": True, "text_color": "#FFFFFF", "highlight_color": "#22FF5A", "highlight": True,
                "outline_color": "#000000", "outline_width": 9, "shadow": 5, "position": "middle",
                "words_per_line": 2, "animation": "pop", "background": "none", "background_color": "#000000",
                "letter_spacing": 1},
    "minimal": {"name": "Minimal", "font": "Segoe UI", "font_size": 54, "bold": True, "italic": False,
                "uppercase": False, "text_color": "#FFFFFF", "highlight_color": "#FFFFFF", "highlight": False,
                "outline_color": "#000000", "outline_width": 0, "shadow": 0, "position": "lower",
                "words_per_line": 6, "animation": "none", "background": "box", "background_color": "#000000",
                "letter_spacing": 0},
    "cinematic": {"name": "Cinematic", "font": "Georgia", "font_size": 50, "bold": False, "italic": True,
                  "uppercase": False, "text_color": "#F5F5F0", "highlight_color": "#F5D58A", "highlight": True,
                  "outline_color": "#000000", "outline_width": 1.5, "shadow": 3, "position": "bottom",
                  "words_per_line": 6, "animation": "fade", "background": "none", "background_color": "#000000",
                  "letter_spacing": 2},
}
FONTS = ["Arial", "Arial Black", "Impact", "Segoe UI", "Segoe UI Semibold", "Segoe UI Black", "Bahnschrift",
         "Verdana", "Tahoma", "Trebuchet MS", "Georgia", "Cambria", "Calibri", "Comic Sans MS", "Consolas"]
POSITIONS = {"top": 0.20, "middle": 0.50, "lower": 0.66, "bottom": 0.74}  # caption centre as fraction of height
ANIMATIONS = ["none", "pop", "fade"]
HEX = re.compile(r"^#[0-9a-fA-F]{6}$")


def resolve_style(style: dict | None, default_preset: str = "hormozi") -> dict:
    style = style or {}
    base = PRESETS.get(style.get("preset") or default_preset, PRESETS["hormozi"])
    merged = {**base, **{k: v for k, v in style.items() if v is not None}}
    merged["preset"] = style.get("preset") or default_preset
    return validate_style(merged)


def validate_style(s: dict) -> dict:
    for k in ("text_color", "highlight_color", "outline_color", "background_color"):
        if not HEX.match(str(s.get(k, ""))):
            raise ValueError(f"{k} must be a #RRGGBB colour")
    s["font_size"] = int(min(160, max(24, int(s["font_size"]))))
    s["outline_width"] = float(min(15, max(0, float(s["outline_width"]))))
    s["shadow"] = float(min(10, max(0, float(s["shadow"]))))
    s["words_per_line"] = int(min(8, max(1, int(s["words_per_line"]))))
    s["letter_spacing"] = float(min(10, max(0, float(s.get("letter_spacing", 0)))))
    if s["position"] not in POSITIONS:
        raise ValueError(f"position must be one of {list(POSITIONS)}")
    if s["animation"] not in ANIMATIONS:
        raise ValueError(f"animation must be one of {ANIMATIONS}")
    if s["background"] not in ("none", "box"):
        raise ValueError("background must be none or box")
    s["font"] = re.sub(r"[,{}\\]", "", str(s["font"]))[:60] or "Arial"
    return s


def _ass_color(hex_color: str, alpha: int = 0) -> str:
    r, g, b = hex_color[1:3], hex_color[3:5], hex_color[5:7]
    return f"&H{alpha:02X}{b}{g}{r}".upper()


def _ts(t: float) -> str:
    t = max(0.0, t)
    cs = int(round(t * 100))
    return f"{cs // 360000}:{cs // 6000 % 60:02d}:{cs // 100 % 60:02d}.{cs % 100:02d}"


def _clean(word: str, upper: bool) -> str:
    word = word.replace("{", "(").replace("}", ")").replace("\\", "")
    return word.upper() if upper else word


def chunk_words(words: list[dict], style: dict, width: int) -> list[list[list[dict]]]:
    """Group words into caption chunks of at most 2 lines; returns chunks -> lines -> words."""
    scale = width / 1080
    fs = style["font_size"] * scale
    char_w = fs * (0.66 if style["uppercase"] or style["bold"] else 0.54) + style["letter_spacing"] * scale
    max_chars = max(6, int((width - 2 * 110 * scale) / char_w))
    chunks, lines, line = [], [], []

    def flush_line():
        nonlocal line
        if line:
            lines.append(line)
            line = []

    def flush_chunk():
        nonlocal lines
        flush_line()
        if lines:
            chunks.append(lines)
            lines = []

    for i, w in enumerate(words):
        if line or lines:
            prev = line[-1] if line else lines[-1][-1]
            if w["s"] - prev["e"] > 0.7:
                flush_chunk()
        text_len = sum(len(x["w"]) + 1 for x in line) + len(w["w"])
        if line and (len(line) >= style["words_per_line"] or text_len > max_chars):
            flush_line()
            if len(lines) >= 2:
                flush_chunk()
        line.append(w)
        if w["w"].endswith((".", "?", "!")):
            flush_chunk()
    flush_chunk()
    return chunks


def build_ass(words: list[dict], style: dict, clip_start: float, clip_end: float, width: int, height: int) -> str:
    """ASS subtitle file. Word times are absolute source times; events are relative to clip_start."""
    s = style
    scale = width / 1080
    words = [w for w in words if w["e"] > clip_start and w["s"] < clip_end]
    words = [{**w, "s": max(0.0, w["s"] - clip_start), "e": min(clip_end, w["e"]) - clip_start} for w in words]
    clip_len = clip_end - clip_start
    box = s["background"] == "box"
    primary = _ass_color(s["text_color"])
    outline_col = _ass_color(s["background_color"], 0x60) if box else _ass_color(s["outline_color"])
    outline = (14 if box else s["outline_width"]) * scale
    back = _ass_color("#000000", 0x80)
    y = int(height * POSITIONS[s["position"]])
    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {width}
PlayResY: {height}
WrapStyle: 0
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Cap,{s['font']},{s['font_size'] * scale:.0f},{primary},{primary},{outline_col},{back},{-1 if s['bold'] else 0},{-1 if s['italic'] else 0},0,0,100,100,{s['letter_spacing'] * scale:.1f},0,{3 if box else 1},{outline:.1f},{s['shadow'] * scale:.1f},5,{int(100 * scale)},{int(100 * scale)},0,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    hl = "{\\c" + _ass_color(s["highlight_color"]) + "&}"
    pop = "{\\fscx112\\fscy112\\t(0,90,\\fscx100\\fscy100)}" if s["animation"] == "pop" else ""
    pos = f"{{\\an5\\pos({width // 2},{y})}}"
    events = []
    chunks = chunk_words(words, s, width)
    for ci, lines in enumerate(chunks):
        flat = [w for line in lines for w in line]
        c_start = flat[0]["s"]
        nxt = chunks[ci + 1][0][0]["s"] if ci + 1 < len(chunks) else clip_len
        c_end = min(nxt, flat[-1]["e"] + 0.6, clip_len)
        fade = "{\\fad(120,0)}" if s["animation"] == "fade" else ""

        def render(active: int | None) -> str:
            out_lines, k = [], 0
            for line in lines:
                parts = []
                for w in line:
                    t = _clean(w["w"], s["uppercase"])
                    parts.append(f"{hl}{pop}{t}{{\\r}}" if k == active else t)
                    k += 1
                out_lines.append(" ".join(parts))
            return pos + "\\N".join(out_lines)

        if not s["highlight"]:
            events.append((c_start, c_end, fade + render(None)))
            continue
        for i, w in enumerate(flat):
            e_start = c_start if i == 0 else w["s"]
            e_end = flat[i + 1]["s"] if i + 1 < len(flat) else c_end
            if e_end - e_start < 0.01:
                continue
            events.append((e_start, e_end, (fade if i == 0 else "") + render(i)))
    body = "".join(f"Dialogue: 0,{_ts(a)},{_ts(b)},Cap,,0,0,0,,{t}\n" for a, b, t in events if b > 0)
    return header + body
