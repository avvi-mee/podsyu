"""faster-whisper transcription with word timestamps.

Whisper runs in a child process: a CUDA/cuDNN failure (which can hard-crash CTranslate2 on Windows) can't take
the backend down, VRAM is fully released when it exits, and cancelling a job kills it immediately.
GPU failures automatically fall back to CPU.
"""
import ctypes
import json
import logging
import os
import queue
import subprocess
import sys
import tempfile
import threading
from functools import lru_cache
from pathlib import Path

log = logging.getLogger(__name__)
BACKEND_DIR = Path(__file__).resolve().parents[2]
_children: set[subprocess.Popen] = set()


def kill_children():
    """Called on backend shutdown so a running Whisper process doesn't outlive the app."""
    for p in list(_children):
        p.kill()


def _cuda_dirs() -> list[Path]:
    dirs = []
    try:
        import nvidia  # namespace package from the nvidia-*-cu12 wheels

        for base in nvidia.__path__:
            dirs += [Path(base) / sub / "bin" for sub in ("cublas", "cudnn", "cuda_nvrtc", "cuda_runtime")]
    except ImportError:
        pass
    # Fallback: Ollama for Windows ships the CUDA 12 cuBLAS runtime.
    dirs.append(Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Ollama" / "lib" / "ollama" / "cuda_v12")
    return [d for d in dirs if d.is_dir()]


def add_cuda_dlls():
    if sys.platform != "win32":
        return
    for d in _cuda_dirs():
        os.add_dll_directory(str(d))
        os.environ["PATH"] = str(d) + os.pathsep + os.environ.get("PATH", "")


@lru_cache(maxsize=1)
def cuda_available() -> bool:
    """True when an NVIDIA GPU is visible AND the cuBLAS/cuDNN DLLs CTranslate2 needs can be loaded."""
    add_cuda_dlls()
    try:
        import ctranslate2

        if ctranslate2.get_cuda_device_count() < 1:
            return False
        if sys.platform == "win32":
            for dll in ("cublas64_12.dll", "cublasLt64_12.dll", "cudnn64_9.dll", "cudnn_ops64_9.dll", "cudnn_cnn64_9.dll"):
                ctypes.WinDLL(dll)
        return True
    except Exception as e:
        log.info("CUDA transcription unavailable: %s", e)
        return False


def transcribe(audio_path: Path, settings: dict, progress=None, initial_prompt: str | None = None,
               total_duration: float | None = None, offset: float = 0.0, vad: bool = True) -> dict:
    """Return {"language", "device", "segments": [{start, end, text, words: [{w, s, e, p}]}]}.

    progress(fraction, message) is called as segments are decoded; it may raise to cancel.
    `offset` is added to every timestamp (used when transcribing an excerpt of the source).
    """
    pref = settings.get("whisper_device", "auto")
    devices = ["cpu"] if pref == "cpu" else (["cuda", "cpu"] if cuda_available() or pref == "cuda" else ["cpu"])
    with tempfile.TemporaryDirectory() as conv_dir:
        return _run_devices(_as_16k(Path(audio_path), Path(conv_dir)), devices, settings, progress, initial_prompt,
                            total_duration, offset, vad)


def _as_16k(path: Path, tmp: Path) -> Path:
    """The worker reads 16 kHz mono 16-bit WAV directly; convert anything else (e.g. 48 kHz TTS narration)."""
    import wave

    try:
        with wave.open(str(path), "rb") as w:
            if (w.getframerate(), w.getnchannels(), w.getsampwidth()) == (16000, 1, 2):
                return path
    except (wave.Error, EOFError):
        pass
    from app.processors.media import run_ffmpeg

    out = tmp / "audio16k.wav"
    run_ffmpeg(["-i", str(path), "-vn", "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", str(out)])
    return out


def _run_devices(audio_path: Path, devices: list[str], settings: dict, progress, initial_prompt, total_duration,
                 offset: float, vad: bool) -> dict:
    errors = []
    for device in devices:
        with tempfile.TemporaryDirectory() as tmp:
            out, err_log = Path(tmp) / "out.json", Path(tmp) / "stderr.txt"
            args = {"audio": str(audio_path), "out": str(out), "device": device, "offset": offset,
                    "model": settings.get("whisper_model", "small"), "prompt": initial_prompt,
                    "language": settings.get("transcription_language", "auto"), "total": total_duration, "vad": vad}
            with open(err_log, "w", encoding="utf-8") as ef:
                proc = subprocess.Popen([sys.executable, "-m", "app.ai.transcribe", json.dumps(args)], cwd=BACKEND_DIR,
                                        stdout=subprocess.PIPE, stderr=ef, text=True, encoding="utf-8",
                                        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
                _children.add(proc)
                lines: queue.Queue = queue.Queue()
                threading.Thread(target=lambda: ([lines.put(x) for x in proc.stdout], lines.put(None)), daemon=True).start()
                last = (0.0, f"Starting Whisper on {device.upper()}")
                try:
                    while True:
                        try:
                            line = lines.get(timeout=2)
                        except queue.Empty:
                            line = ""  # heartbeat: lets a cancel request through even if the child is silent
                        if line is None:
                            break
                        if line.startswith("P "):
                            frac, msg = line[2:].rstrip("\n").split(" ", 1)
                            last = (float(frac), msg)
                        if progress:
                            progress(*last)
                    proc.wait()
                except BaseException:
                    proc.kill()
                    raise
                finally:
                    _children.discard(proc)
            if proc.returncode == 0 and out.exists():
                return json.loads(out.read_text("utf-8"))
            tail = err_log.read_text("utf-8", errors="replace").strip().splitlines()[-3:]
            errors.append(f"{device}: exit {proc.returncode}: {' | '.join(tail)[-300:]}")
            log.warning("Whisper on %s failed: %s", device, errors[-1])
            if device == "cuda" and progress:
                progress(0.0, "GPU transcription failed - retrying on CPU")
    raise RuntimeError("Transcription failed. " + " ; ".join(errors))


def ensure_model(name: str) -> str:
    """Fetch a faster-whisper model with parallel ranged requests (single-stream CDN downloads can crawl).

    Returns a local directory, or `name` unchanged for custom paths/repos (faster-whisper handles those).
    """
    import fnmatch
    import hashlib
    import threading
    import urllib.request
    from concurrent.futures import ThreadPoolExecutor

    from faster_whisper.utils import _MODELS
    from huggingface_hub import HfApi

    from app.core.config import MODELS_DIR

    repo = _MODELS.get(name)
    dest = MODELS_DIR / "whisper" / name
    if repo is None or (dest / "model.bin").exists():
        return str(dest) if repo else name
    info = HfApi().model_info(repo, files_metadata=True)
    patterns = ["config.json", "preprocessor_config.json", "model.bin", "tokenizer.json", "vocabulary.*"]
    files = [s for s in info.siblings if any(fnmatch.fnmatch(s.rfilename, p) for p in patterns)]
    total, done, lock = sum(s.size or 0 for s in files), [0], threading.Lock()
    tmp = dest.with_name(name + ".partial")
    tmp.mkdir(parents=True, exist_ok=True)
    chunk = 4 * 2**20

    def get(url, path, a, b):
        for attempt in range(20):
            try:
                req = urllib.request.Request(url, headers={"Range": f"bytes={a}-{b}", "User-Agent": "shorts-factory"})
                with urllib.request.urlopen(req, timeout=60) as r:
                    data = r.read()
                if len(data) == b - a + 1:
                    break
            except OSError:
                pass
        else:
            raise RuntimeError(f"Model download failed for {url}")
        with open(path, "r+b") as f:
            f.seek(a)
            f.write(data)
        with lock:
            with open(f"{path}.chunks", "a") as log_f:  # lets an interrupted download resume
                log_f.write(f"{a}\n")
            done[0] += len(data)
            print(f"P 0 Downloading Whisper '{name}' model {done[0] / 2**20:.0f}/{total / 2**20:.0f} MB (first use only)", flush=True)

    with ThreadPoolExecutor(12) as pool:
        for s in files:
            path, url = tmp / s.rfilename, f"https://huggingface.co/{repo}/resolve/{info.sha}/{s.rfilename}"
            sidecar = Path(f"{path}.chunks")
            have = set()
            if path.exists() and path.stat().st_size == (s.size or 0) and sidecar.exists():
                have = {int(x) for x in sidecar.read_text().split()}
            else:
                sidecar.unlink(missing_ok=True)
                with open(path, "wb") as f:
                    f.truncate(s.size or 0)
            done[0] += sum(min(chunk, s.size - a) for a in have)
            todo = [(a, min(s.size, a + chunk) - 1) for a in range(0, s.size or 0, chunk) if a not in have]
            list(pool.map(lambda r: get(url, path, *r), todo))
            if s.lfs and hashlib.sha256(path.read_bytes()).hexdigest() != s.lfs.sha256:
                path.unlink()
                sidecar.unlink(missing_ok=True)
                raise RuntimeError(f"Checksum mismatch for {s.rfilename} - retry to download it again")
            sidecar.unlink(missing_ok=True)
    tmp.rename(dest)
    return str(dest)


def _worker(a: dict):
    add_cuda_dlls()
    from faster_whisper import WhisperModel

    compute = "float16" if a["device"] == "cuda" else "int8"
    model = WhisperModel(ensure_model(a["model"]), device=a["device"], compute_type=compute)
    print(f"P 0 Loaded Whisper {a['model']} on {a['device'].upper()}", flush=True)
    # Our audio is always a 16 kHz mono PCM WAV made by FFmpeg; reading it directly avoids PyAV
    # (newer PyAV releases broke faster-whisper's decode_audio).
    import wave

    import numpy as np

    with wave.open(a["audio"], "rb") as w:
        if (w.getframerate(), w.getnchannels(), w.getsampwidth()) != (16000, 1, 2):
            raise ValueError("Expected 16 kHz mono 16-bit WAV")
        audio = np.frombuffer(w.readframes(w.getnframes()), np.int16).astype(np.float32) / 32768.0
    segments, info = model.transcribe(
        audio, language=None if a["language"] == "auto" else a["language"], word_timestamps=True,
        vad_filter=a.get("vad", True), beam_size=5, initial_prompt=a["prompt"], condition_on_previous_text=False)
    total, off, out = a["total"] or info.duration or 1, a["offset"], []
    for seg in segments:
        words = [{"w": w.word.strip(), "s": round(w.start + off, 3), "e": round(w.end + off, 3), "p": round(w.probability, 3)}
                 for w in (seg.words or []) if w.word.strip()]
        words = [w for w in words if w["p"] > 0.01]  # drop zero-confidence (hallucinated) words
        if words:
            out.append({"start": round(seg.start + off, 3), "end": round(seg.end + off, 3), "text": seg.text.strip(), "words": words})
        print(f"P {min(1.0, seg.end / total):.4f} Transcribed {int(seg.end // 60)}:{int(seg.end % 60):02d} on {a['device'].upper()}", flush=True)
    Path(a["out"]).write_text(json.dumps({"language": info.language, "device": a["device"], "segments": out}), "utf-8")


def sentences_from_segments(segments: list[dict]) -> list[dict]:
    """Split word stream into sentences on terminal punctuation or long pauses."""
    words = [w for seg in segments for w in seg["words"]]
    out, cur = [], []
    for i, w in enumerate(words):
        cur.append(w)
        nxt = words[i + 1] if i + 1 < len(words) else None
        gap = (nxt["s"] - w["e"]) if nxt else 99
        ends = w["w"].endswith((".", "?", "!", '."', '?"', '!"'))
        # Split on real sentence ends only - a thinking pause mid-sentence must not create a cut point.
        too_long = cur[-1]["e"] - cur[0]["s"] > 25 and (w["w"].endswith((",", ";", ":")) or gap > 0.8)
        if ends or gap > 3.0 or too_long or nxt is None:
            out.append({"i": len(out), "start": cur[0]["s"], "end": cur[-1]["e"], "text": " ".join(x["w"] for x in cur)})
            cur = []
    return out


if __name__ == "__main__":
    _worker(json.loads(sys.argv[1]))
