"""Music analysis for the BGM library: catchy-segment detection, snippet cutting and seamless looping."""
import hashlib
import math
import subprocess
from pathlib import Path

import numpy as np

from app.core.config import MUSIC_DIR
from app.processors.media import NO_WINDOW, run_ffmpeg

SR = 11025
HOP = 0.5  # analysis resolution (seconds)
SNIPPET_LENGTHS = (15, 20, 30)  # min, preferred, max
PREFERRED = 20


def load_mono(path: str | Path, sr: int = SR) -> np.ndarray:
    r = subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-ac", "1", "-ar", str(sr), "-f", "f32le", "-"],
                       capture_output=True, creationflags=NO_WINDOW)
    if r.returncode != 0:
        raise RuntimeError("Could not decode audio: " + r.stderr.decode(errors="replace")[-200:])
    return np.frombuffer(r.stdout, np.float32)


def _features(y: np.ndarray, sr: int = SR) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Per-hop loudness, onset strength (spectral flux) and a 16-band spectral fingerprint."""
    hop, n = int(sr * HOP), 2048
    frames = [y[i:i + n] for i in range(0, max(1, len(y) - n), hop)]
    if not frames:
        return np.zeros(1), np.zeros(1), np.zeros((1, 16))
    win = np.hanning(n)
    spec = np.array([np.abs(np.fft.rfft(f * win)) if len(f) == n else np.zeros(n // 2 + 1) for f in frames])
    rms = np.sqrt(np.mean(np.array([f for f in frames if len(f) == n] or [np.zeros(n)]) ** 2, axis=1))
    rms = np.pad(rms, (0, len(spec) - len(rms)))
    flux = np.concatenate([[0], np.maximum(0, np.diff(spec, axis=0)).sum(axis=1)])
    edges = np.unique(np.geomspace(2, spec.shape[1] - 1, 17).astype(int))
    bands = np.array([[s[a:b].sum() for a, b in zip(edges, edges[1:])] for s in spec])
    bands = np.log1p(bands)
    return rms, flux, bands


def _norm(x: np.ndarray) -> np.ndarray:
    lo, hi = np.percentile(x, 5), np.percentile(x, 95)
    return np.clip((x - lo) / (hi - lo + 1e-9), 0, 1)


def catchy_start(path: str | Path, length: float = PREFERRED) -> tuple[float, float]:
    """(start_seconds, score 0..1) of the most hook-like `length`-second window: loud, punchy and repeated
    elsewhere in the track (choruses repeat). Skips the first/last 3 s."""
    y = load_mono(path)
    total = len(y) / SR
    if total <= length + 1:
        return 0.0, 0.0
    rms, flux, bands = _features(y)
    w = max(1, int(length / HOP))
    loud, punch = _norm(rms), _norm(np.convolve(flux, np.ones(4) / 4, mode="same"))
    unit = bands / (np.linalg.norm(bands, axis=1, keepdims=True) + 1e-9)

    def window_means(x):  # mean over every w-long window, via cumulative sums
        cs = np.concatenate([np.zeros((1,) + x.shape[1:]), np.cumsum(x, axis=0)])
        return (cs[w:] - cs[:-w]) / w

    sig, loud_w, punch_w = window_means(unit), window_means(loud), window_means(punch)
    sig = sig / (np.linalg.norm(sig, axis=1, keepdims=True) + 1e-9)
    first, last = int(3 / HOP), max(int(3 / HOP), len(rms) - w - int(3 / HOP))
    last = min(last, len(sig) - 1)
    others = np.arange(first, last + 1, 4)
    best, best_score = first, -1.0
    for i in range(first, last + 1, 2):
        far = others[np.abs(others - i) >= w]  # repetition: best match with a non-overlapping window
        rep = float((sig[far] @ sig[i]).max()) if len(far) else 0.0
        score = 0.5 * loud_w[i] + 0.3 * punch_w[i] + 0.2 * rep
        if score > best_score:
            best, best_score = i, score
    # nudge the start to a quiet point just before the section (phrase boundary), within 1.5 s
    lo = max(0, best - 3)
    start_i = lo + int(np.argmin(rms[lo:best + 1])) if best > 0 else best
    return round(start_i * HOP, 2), round(float(best_score), 3)


def cut_snippet(src: str | Path, start: float, length: float, dest: Path):
    """Cut a snippet with soft edges so it loops cleanly."""
    run_ffmpeg(["-ss", f"{start:.2f}", "-t", f"{length:.2f}", "-i", str(src), "-vn",
                "-af", f"afade=t=in:d=0.4,afade=t=out:st={max(0, length - 0.8):.2f}:d=0.8", "-c:a", "libmp3lame",
                "-q:a", "2", str(dest)])


def extend_to(path: str | Path, duration: float) -> str:
    """Return a file at least `duration` long: the track itself, or a seamless crossfaded loop of it (cached)."""
    path = Path(path)
    from app.processors.media import audio_duration

    length = audio_duration(path)
    if length >= duration + 0.5 or length < 3:
        return str(path)
    xf = min(1.5, length / 4)
    copies = max(2, math.ceil((duration + 1) / (length - xf)))
    cache = MUSIC_DIR / ".cache"
    cache.mkdir(exist_ok=True)
    key = hashlib.md5(f"{path.name}{path.stat().st_mtime}{copies}".encode()).hexdigest()[:12]
    out = cache / f"{path.stem}_{key}.m4a"
    if not out.exists():
        chain = "".join(f"[a{i}]" for i in range(copies))
        graph = f"[0:a]asplit={copies}{chain};[a0][a1]acrossfade=d={xf:.2f}[x1]" + "".join(
            f";[x{i - 1}][a{i}]acrossfade=d={xf:.2f}[x{i}]" for i in range(2, copies))
        run_ffmpeg(["-i", str(path), "-filter_complex", graph, "-map", f"[x{copies - 1}]", "-c:a", "aac", "-b:a", "192k", str(out)])
    return str(out)
