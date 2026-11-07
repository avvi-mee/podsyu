from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.core.config import DEFAULT_SETTINGS, RESOLUTIONS
from app.database.db import session
from app.models.models import Setting

CHOICES = {
    "whisper_model": ["tiny", "base", "small", "medium", "large-v3-turbo", "large-v3"],
    "whisper_device": ["auto", "cuda", "cpu"],
    "encoder": ["auto", "gpu", "cpu"],
    "output_resolution": list(RESOLUTIONS),
    "default_privacy": ["private", "unlisted", "public"],
}
INT_RANGES = {"min_duration": (10, 180), "max_duration": (15, 180), "num_shorts": (1, 30), "ollama_num_ctx": (2048, 32768)}


def get_settings() -> dict:
    with session() as s:
        stored = {row.key: row.value for row in s.query(Setting).all()}
    return {**DEFAULT_SETTINGS, **{k: v for k, v in stored.items() if k in DEFAULT_SETTINGS}}


def validate(updates: dict) -> dict:
    clean = {}
    for k, v in updates.items():
        if k not in DEFAULT_SETTINGS:
            raise ValueError(f"Unknown setting: {k}")
        if k in CHOICES and v not in CHOICES[k]:
            raise ValueError(f"{k} must be one of {CHOICES[k]}")
        if k in INT_RANGES:
            lo, hi = INT_RANGES[k]
            if not isinstance(v, int) or not lo <= v <= hi:
                raise ValueError(f"{k} must be an integer between {lo} and {hi}")
        if k == "timezone":
            try:
                ZoneInfo(v)
            except (ZoneInfoNotFoundError, ValueError):
                raise ValueError(f"Unknown timezone: {v}")
        if isinstance(DEFAULT_SETTINGS[k], bool) and not isinstance(v, bool):
            raise ValueError(f"{k} must be true/false")
        if isinstance(DEFAULT_SETTINGS[k], str) and not isinstance(v, str):
            raise ValueError(f"{k} must be text")
        clean[k] = v
    merged = {**get_settings(), **clean}
    if merged["min_duration"] >= merged["max_duration"]:
        raise ValueError("Minimum duration must be lower than maximum duration")
    return clean


def update_settings(updates: dict) -> dict:
    clean = validate(updates)
    with session() as s:
        for k, v in clean.items():
            s.merge(Setting(key=k, value=v))
    return get_settings()
