"""Local text-to-speech with Kokoro (82M, Apache-2.0) via onnxruntime: runs on the CPU, no paid API.

Voices are Kokoro's built-in speakers (no cloning of real people). Pitch, volume and pauses are applied
with FFmpeg (rubberband keeps pitch shifts natural)."""
import logging
import re
import threading
from pathlib import Path

import numpy as np

from app.core.config import TTS_DIR
from app.processors.media import run_ffmpeg

log = logging.getLogger(__name__)
MODEL, VOICES = TTS_DIR / "kokoro-v1.0.onnx", TTS_DIR / "voices-v1.0.bin"
_engine = None
_lock = threading.Lock()

# Voice profiles -> (Kokoro voice, base pitch in semitones, base speed)
PROFILES = {
    "expressive": ("af_heart", 1.0, 1.05),  # default: slightly higher, clear, warm, conversational
    "female": ("af_bella", 0.0, 1.0),
    "male": ("am_michael", 0.0, 1.0),
    "neutral": ("af_sky", 0.0, 1.0),
    "deep": ("am_onyx", -1.5, 0.95),
    "youthful": ("af_nova", 1.5, 1.08),
    "storyteller": ("bm_fable", 0.0, 0.97),
    "whisper": ("af_nicole", 0.0, 0.95),  # soft, close-mic ASMR feel
}
EMOTIONS = {  # (speed multiplier, pause multiplier, extra pitch)
    "calm": (0.93, 1.3, -0.3), "neutral": (1.0, 1.0, 0.0), "excited": (1.08, 0.75, 0.5), "dramatic": (0.92, 1.5, 0.0),
}
DEFAULT_VOICE = {"profile": "expressive", "pitch": 0.0, "speed": 1.0, "volume": 0.0, "emotion": "neutral",
                 "pause": 0.35, "pronunciation": ""}


def available() -> bool:
    return MODEL.exists() and VOICES.exists()


def _get():
    global _engine
    if _engine is None:
        if not available():
            raise RuntimeError(f"Kokoro voice model not found in {TTS_DIR}. Run scripts\\setup.bat (downloads ~350 MB).")
        from kokoro_onnx import Kokoro

        _engine = Kokoro(str(MODEL), str(VOICES))
    return _engine


def clean_settings(v: dict | None) -> dict:
    v = {**DEFAULT_VOICE, **(v or {})}
    if v["profile"] not in PROFILES:
        raise ValueError(f"voice profile must be one of {list(PROFILES)}")
    if v["emotion"] not in EMOTIONS:
        raise ValueError(f"emotion must be one of {list(EMOTIONS)}")
    v["pitch"] = float(min(4, max(-4, float(v["pitch"]))))
    v["speed"] = float(min(1.5, max(0.6, float(v["speed"]))))
    v["volume"] = float(min(6, max(-12, float(v["volume"]))))
    v["pause"] = float(min(1.5, max(0.05, float(v["pause"]))))
    v["pronunciation"] = str(v.get("pronunciation") or "")[:2000]
    return v


def _apply_pronunciation(text: str, rules: str) -> str:
    """Lines like `GIF = jif` replace whole words before synthesis (fixes names/acronyms)."""
    for line in rules.splitlines():
        if "=" in line:
            word, say = (x.strip() for x in line.split("=", 1))
            if word and say:
                text = re.sub(rf"(?<!\w){re.escape(word)}(?!\w)", say, text, flags=re.I)
    return text


def split_sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[.!?…])\s+|\n+", text.strip())
    return [p.strip() for p in parts if p.strip()]


def synthesize(text: str, voice: dict, out_wav: Path, progress=None) -> float:
    """Render narration to `out_wav` (48 kHz mono). Returns duration in seconds."""
    v = clean_settings(voice)
    name, base_pitch, base_speed = PROFILES[v["profile"]]
    speed_mul, pause_mul, emo_pitch = EMOTIONS[v["emotion"]]
    speed = max(0.5, min(2.0, base_speed * v["speed"] * speed_mul))
    sentences = split_sentences(_apply_pronunciation(text, v["pronunciation"]))
    if not sentences:
        raise ValueError("The script is empty.")
    with _lock:  # one synthesis at a time (onnxruntime already uses all cores)
        engine = _get()
        chunks, sr = [], 24000
        for i, sent in enumerate(sentences):
            audio, sr = engine.create(sent, voice=name, speed=speed, lang="en-gb" if name.startswith("b") else "en-us")
            chunks.append(np.asarray(audio, dtype=np.float32))
            pause = v["pause"] * pause_mul * (1.6 if sent.endswith(("?", "!", "…")) else 1.0)
            chunks.append(np.zeros(int(sr * pause), dtype=np.float32))
            if progress:
                progress((i + 1) / len(sentences), f"Voicing sentence {i + 1}/{len(sentences)}")
    raw = out_wav.with_suffix(".raw.wav")
    _write_wav(raw, np.concatenate(chunks), sr)
    pitch = base_pitch + v["pitch"] + emo_pitch
    filters = [f"rubberband=pitch={2 ** (pitch / 12):.4f}:formant=preserved"] if abs(pitch) > 0.05 else []
    filters += [f"volume={v['volume']:.1f}dB", "aresample=48000"]
    run_ffmpeg(["-i", str(raw), "-af", ",".join(filters), "-ac", "1", "-c:a", "pcm_s16le", str(out_wav)])
    raw.unlink(missing_ok=True)
    return sum(len(c) for c in chunks) / sr


def _write_wav(path: Path, samples: np.ndarray, sr: int):
    import wave

    pcm = (np.clip(samples, -1, 1) * 32767).astype(np.int16)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(pcm.tobytes())


def voices() -> list[str]:
    return sorted(_get().get_voices()) if available() else []
