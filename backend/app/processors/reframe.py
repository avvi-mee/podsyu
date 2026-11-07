"""Vertical reframing: find faces, pick the active speaker by lip motion, emit a stepwise crop plan."""
import logging
import subprocess
import urllib.request

import cv2
import numpy as np

from app.core.config import MODELS_DIR
from app.processors.media import NO_WINDOW

log = logging.getLogger(__name__)
cv2.utils.logging.setLogLevel(cv2.utils.logging.LOG_LEVEL_ERROR)  # OpenCV 5 warns about DNN targets on every create
YUNET_URL = "https://github.com/opencv/opencv_zoo/raw/main/models/face_detection_yunet/face_detection_yunet_2023mar.onnx"
YUNET_PATH = MODELS_DIR / "face_detection_yunet_2023mar.onnx"
SAMPLE_FPS = 8
AW = 640  # analysis width


def ensure_face_model() -> bool:
    if YUNET_PATH.exists() and YUNET_PATH.stat().st_size > 100_000:
        return True
    for attempt in range(4):
        try:
            log.info("Downloading YuNet face detector to %s", YUNET_PATH)
            tmp = YUNET_PATH.with_suffix(".part")
            urllib.request.urlretrieve(YUNET_URL, tmp)
            tmp.replace(YUNET_PATH)
            return True
        except Exception as e:
            log.warning("Face model download attempt %d failed: %s", attempt + 1, e)
    log.warning("Face model unavailable; auto-reframe will use centre crop")
    return False


def crop_width(src_w: int, src_h: int) -> int:
    return min(src_w, int(round(src_h * 9 / 16 / 2)) * 2)


def _frames(src: str, start: float, end: float, ah: int):
    cmd = ["ffmpeg", "-nostdin", "-loglevel", "error", "-ss", f"{start:.3f}", "-to", f"{end:.3f}", "-i", src,
           "-vf", f"fps={SAMPLE_FPS},scale={AW}:{ah}", "-f", "rawvideo", "-pix_fmt", "bgr24", "-"]
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, creationflags=NO_WINDOW)
    size = AW * ah * 3
    try:
        while True:
            buf = proc.stdout.read(size)
            if len(buf) < size:
                break
            yield np.frombuffer(buf, np.uint8).reshape(ah, AW, 3)
    finally:
        proc.kill()


def plan(src: str, start: float, end: float, src_w: int, src_h: int) -> tuple[list[tuple[float, float]], str]:
    """Return ([(t, crop_x_pixels)...] step function relative to clip start, description)."""
    cw = crop_width(src_w, src_h)
    center = (src_w - cw) / 2
    if cw >= src_w - 2:
        return [(0.0, 0.0)], "source already vertical"
    if not ensure_face_model():
        return [(0.0, center)], "centre crop (face model unavailable)"
    ah = int(round(AW * src_h / src_w / 2)) * 2
    det = cv2.FaceDetectorYN.create(str(YUNET_PATH), "", (AW, ah), 0.75, 0.3, 50)

    tracks: list[dict] = []  # {"x": centre_x (analysis px), "act": smoothed lip activity, "mouth": prev crop, "seen": i}
    samples = []  # per sample: (cut: bool, {track_index: (cx, activity)})
    prev_small = None
    for i, frame in enumerate(_frames(src, start, end, ah)):
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        small = cv2.resize(gray, (64, 36)).astype(np.int16)
        cut = prev_small is not None and float(np.mean(np.abs(small - prev_small))) > 28
        prev_small = small
        if cut:
            tracks = []
        _, faces = det.detect(frame)
        present = {}
        for f in faces if faces is not None else []:
            x, y, w, h = f[:4]
            if w < AW * 0.035:
                continue  # ignore tiny background faces
            cx = x + w / 2
            # Mouth region from YuNet landmarks (right/left mouth corners at idx 10..13)
            mx1, my1, mx2, my2 = f[10], f[11], f[12], f[13]
            x0, x1 = int(max(0, min(mx1, mx2) - w * 0.08)), int(min(AW, max(mx1, mx2) + w * 0.08))
            y0, y1 = int(max(0, min(my1, my2) - h * 0.10)), int(min(ah, max(my1, my2) + h * 0.15))
            mouth = cv2.resize(gray[y0:y1, x0:x1], (24, 12)).astype(np.int16) if x1 > x0 + 2 and y1 > y0 + 2 else None
            ti = next((k for k, t in enumerate(tracks) if abs(t["x"] - cx) < AW * 0.09 and k not in present), None)
            if ti is None:
                tracks.append({"x": cx, "act": 0.0, "mouth": None, "seen": i})
                ti = len(tracks) - 1
            t = tracks[ti]
            motion = float(np.mean(np.abs(mouth - t["mouth"]))) if mouth is not None and t["mouth"] is not None else 0.0
            t.update(x=0.7 * t["x"] + 0.3 * cx, act=0.75 * t["act"] + 0.25 * motion, mouth=mouth, seen=i)
            present[ti] = (cx, t["act"])
        samples.append((cut, present))

    if not samples or sum(1 for _, p in samples if p) < len(samples) * 0.3:
        return [(0.0, center)], "centre crop (no reliable faces detected)"

    hold = int(SAMPLE_FPS * 1.5)  # min time on one framing unless the camera cuts
    confirm = int(SAMPLE_FPS * 0.5)  # a new framing must persist this long before we move
    steps: list[tuple[float, float]] = []
    cur_x, since, pending = None, 0, None
    multi = False
    for i, (cut, present) in enumerate(samples):
        since += 1
        if not present:
            continue
        multi |= len(present) > 1
        best = max(present.values(), key=lambda v: v[1])
        xs = [v[0] for v in present.values()]
        if len(xs) > 1 and (max(xs) - min(xs)) * (src_w / AW) <= cw * 0.6:
            target = (max(xs) + min(xs)) / 2  # everyone fits in one vertical frame: keep them together, no cuts
        elif cur_x is None or cut or len(present) == 1:
            target = best[0]
        else:
            cur = min(present.values(), key=lambda v: abs(v[0] - cur_x))
            target = best[0] if best is not cur and best[1] > cur[1] * 1.35 + 0.4 else cur[0]
        if cur_x is None or cut:  # camera cut: reframe immediately
            steps.append((i / SAMPLE_FPS, target))
            cur_x, since, pending = target, 0, None
            continue
        if abs(target - cur_x) <= AW * 0.06:
            pending = None
            continue
        # Commit a move only once it has persisted (detector flicker) and the current shot has been held long enough.
        if pending and abs(pending[1] - target) <= AW * 0.06:
            pending = (pending[0], pending[1], pending[2] + 1)
        else:
            pending = (i, target, 1)
        if pending[2] >= confirm and since >= hold:
            start_i = max(pending[0], i - since + hold)  # back-date to when the change began, but keep the min hold
            steps.append((start_i / SAMPLE_FPS, pending[1]))
            cur_x, since, pending = pending[1], 0, None
    scale = src_w / AW
    out, last = [], None
    for t, cx in steps:
        x = float(np.clip(cx * scale - cw / 2, 0, src_w - cw))
        if last is None or abs(x - last) > src_w * 0.02:
            out.append((round(t, 2), round(x)))
            last = x
    desc = "auto: following active speaker" if multi else "auto: tracking speaker"
    return out or [(0.0, center)], f"{desc} ({len(out)} shot{'s' if len(out) != 1 else ''})"


def crop_x_expr(steps: list[tuple[float, float]]) -> str:
    """Flat step-function expression for ffmpeg's crop x (evaluated per frame)."""
    expr = f"{steps[0][1]:.0f}"
    for (_, prev), (t, x) in zip(steps, steps[1:]):
        expr += f"+({x - prev:.0f})*gte(t\\,{t:.2f})"
    return expr
