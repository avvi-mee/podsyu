"""Download model files PODSYU needs (Kokoro voice ~350 MB, YuNet face detector) with parallel ranged
requests - much faster than a single stream on throttled connections. Safe to re-run: existing files are kept.

Usage (from the project folder):  backend\\.venv\\Scripts\\python scripts\\download_models.py
"""
import os
import sys
import threading
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FILES = [
    ("https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/voices-v1.0.bin", ROOT / "models/tts/voices-v1.0.bin"),
    ("https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/kokoro-v1.0.onnx", ROOT / "models/tts/kokoro-v1.0.onnx"),
    ("https://github.com/opencv/opencv_zoo/raw/main/models/face_detection_yunet/face_detection_yunet_2023mar.onnx",
     ROOT / "models/face_detection_yunet_2023mar.onnx"),
]
UA = {"User-Agent": "podsyu-setup"}
CHUNK = 4 * 2**20


def fetch(url: str, dest: Path):
    if dest.exists() and dest.stat().st_size > 0:
        print(f"ok (already present) {dest.name}")
        return
    dest.parent.mkdir(parents=True, exist_ok=True)
    with urllib.request.urlopen(urllib.request.Request(url, method="HEAD", headers=UA), timeout=60) as r:
        final, size = r.geturl(), int(r.headers["Content-Length"])
    tmp = Path(str(dest) + ".part")
    with open(tmp, "wb") as f:
        f.truncate(size)
    lock, done = threading.Lock(), [0]

    def get(a: int):
        b = min(size, a + CHUNK) - 1
        for _ in range(30):
            try:
                req = urllib.request.Request(final, headers={**UA, "Range": f"bytes={a}-{b}"})
                with urllib.request.urlopen(req, timeout=60) as r:
                    data = r.read()
                if len(data) == b - a + 1:
                    break
            except OSError:
                pass
        else:
            raise RuntimeError(f"Download failed: {dest.name}")
        with lock:
            with open(tmp, "r+b") as f:
                f.seek(a)
                f.write(data)
            done[0] += len(data)
            print(f"\r{dest.name}: {done[0] / 2**20:.0f}/{size / 2**20:.0f} MB", end="", flush=True)

    with ThreadPoolExecutor(12) as pool:
        list(pool.map(get, range(0, size, CHUNK)))
    os.replace(tmp, dest)
    print(f"\nok {dest.name}")


if __name__ == "__main__":
    failed = 0
    for url, dest in FILES:
        try:
            fetch(url, dest)
        except Exception as e:  # keep going; the app explains what's missing
            failed += 1
            print(f"\n[WARN] {dest.name}: {e}")
    sys.exit(1 if failed else 0)
