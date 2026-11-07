"""FFmpeg / ffprobe helpers."""
import json
import logging
import shutil
import subprocess
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

log = logging.getLogger(__name__)
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
_nvenc_ok: bool | None = None  # cached after first NVENC attempt


class MediaError(RuntimeError):
    pass


def require_ffmpeg():
    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        raise MediaError("FFmpeg/ffprobe not found on PATH. Install FFmpeg (see README) and restart the app.")


def probe(path: str | Path) -> dict:
    require_ffmpeg()
    r = subprocess.run(
        ["ffprobe", "-v", "error", "-print_format", "json", "-show_format", "-show_streams", str(path)],
        capture_output=True, text=True, encoding="utf-8", errors="replace", creationflags=NO_WINDOW,
    )
    if r.returncode != 0:
        raise MediaError(f"Could not read video (file may be corrupted or unsupported): {r.stderr.strip()[-300:]}")
    info = json.loads(r.stdout or "{}")
    streams = info.get("streams", [])
    v = next((s for s in streams if s.get("codec_type") == "video" and s.get("disposition", {}).get("attached_pic") != 1), None)
    a = next((s for s in streams if s.get("codec_type") == "audio"), None)
    duration = float(info.get("format", {}).get("duration") or (v or {}).get("duration") or 0)
    if not v:
        raise MediaError("No video stream found in the file.")
    if not a:
        raise MediaError("No audio stream found - a podcast video needs an audio track for transcription.")
    if duration <= 0:
        raise MediaError("Video duration could not be determined (file may be corrupted or incomplete).")
    num, _, den = (v.get("avg_frame_rate") or "30/1").partition("/")
    fps = float(num) / float(den or 1) if float(den or 1) else 30.0
    w, h = int(v["width"]), int(v["height"])
    rot = int((v.get("tags") or {}).get("rotate", 0) or 0)
    for sd in v.get("side_data_list", []):
        rot = int(sd.get("rotation", rot) or rot)
    if abs(rot) in (90, 270):
        w, h = h, w
    return {"duration": duration, "width": w, "height": h, "fps": round(fps or 30.0, 3)}


def audio_duration(path: str | Path) -> float:
    """Duration of an audio file; raises MediaError if it has no audio stream (corrupt/unsupported)."""
    require_ffmpeg()
    r = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "a:0", "-show_entries", "stream=codec_type:format=duration",
                        "-of", "json", str(path)], capture_output=True, text=True, creationflags=NO_WINDOW)
    info = json.loads(r.stdout or "{}") if r.returncode == 0 else {}
    if not info.get("streams"):
        raise MediaError("Not a playable audio file (MP3, WAV, M4A, AAC, OGG or FLAC).")
    return float(info.get("format", {}).get("duration") or 0)


def run_ffmpeg(args: list[str], duration: float | None = None, progress: Callable[[float], None] | None = None, cwd=None):
    """Run ffmpeg with machine-readable progress. Raises MediaError with the stderr tail on failure."""
    require_ffmpeg()
    cmd = ["ffmpeg", "-hide_banner", "-nostdin", "-y", "-progress", "pipe:1", "-loglevel", "error", *args]
    log.debug("ffmpeg %s", " ".join(cmd))
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, cwd=cwd, creationflags=NO_WINDOW,
                            text=True, encoding="utf-8", errors="replace")
    err_lines: list[str] = []
    t = threading.Thread(target=lambda: err_lines.extend(proc.stderr), daemon=True)  # drain stderr to avoid deadlock
    t.start()
    try:
        for line in proc.stdout:
            if progress and duration and line.startswith("out_time_us="):
                try:
                    progress(min(1.0, int(line.split("=")[1]) / 1e6 / duration))
                except ValueError:
                    pass
        proc.wait()
    except BaseException:
        proc.kill()
        raise
    t.join(timeout=5)
    if proc.returncode != 0:
        raise MediaError("FFmpeg failed: " + "".join(err_lines).strip()[-600:])


def extract_audio(src: Path, dst: Path, duration: float, progress=None):
    tmp = dst.with_suffix(".tmp.wav")
    run_ffmpeg(["-i", str(src), "-vn", "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", str(tmp)], duration, progress)
    tmp.replace(dst)


def video_encoder_args(pref: str) -> list[list[str]]:
    """Encoder argument sets to try in order (GPU first when allowed, CPU fallback)."""
    cpu = ["-c:v", "libx264", "-preset", "medium", "-crf", "20", "-profile:v", "high", "-pix_fmt", "yuv420p"]
    gpu = ["-c:v", "h264_nvenc", "-preset", "p5", "-rc", "vbr", "-cq", "21", "-b:v", "0", "-profile:v", "high", "-pix_fmt", "yuv420p"]
    if pref == "cpu" or _nvenc_ok is False:
        return [cpu]
    return [gpu, cpu]


def clean_metadata_args() -> list[str]:
    """Output carries no trace of the source file or tooling: no copied tags/chapters, no encoder string,
    no x264 settings SEI; creation time = now. (File metadata only - picture and sound are untouched.)"""
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000000Z")
    return ["-map_metadata", "-1", "-map_chapters", "-1", "-fflags", "+bitexact", "-flags:v", "+bitexact",
            "-flags:a", "+bitexact", "-bsf:v", "filter_units=remove_types=6", "-metadata", f"creation_time={now}",
            "-metadata:s:v", "handler_name=VideoHandler", "-metadata:s:v", "encoder=", "-metadata:s:a", "handler_name=SoundHandler"]


def clean_existing(path: Path):
    """Strip metadata from an already-rendered MP4 in place (stream copy: picture/sound unchanged)."""
    tmp = path.with_suffix(".clean.mp4")
    run_ffmpeg(["-i", str(path), "-map", "0:v", "-map", "0:a?", "-c", "copy", *clean_metadata_args(),
                "-movflags", "+faststart", "-f", "mp4", str(tmp)])
    tmp.replace(path)


FADE = 0.5  # seconds of fade in/out on every short (picture, captions, voice and music)


def audio_mix_args(duration: float, music: str | None = None, volume: float = 0.10, voice_input: int = 0,
                   music_input: int = 1) -> tuple[list[str], list[str]]:
    """(extra inputs, output args) for the short's audio: voice with fades, plus optional background music that
    is quiet, ducks further whenever someone speaks (sidechain compression), loops if short, and fades in/out.
    Video always comes from input 0; voice from `voice_input`; the music becomes input `music_input`."""
    fade_out = max(0.0, duration - FADE)
    # Normalise speech to a consistent Shorts loudness first, so quiet podcasts aren't drowned by the music.
    voice = (f"[{voice_input}:a]aformat=sample_rates=48000:channel_layouts=stereo,loudnorm=I=-16:TP=-1.5:LRA=11,"
             f"aformat=sample_rates=48000,afade=t=in:d=0.25,afade=t=out:st={fade_out:.3f}:d={FADE}")
    if not music:
        return [], ["-filter_complex", voice + "[aout]", "-map", "0:v", "-map", "[aout]"]
    graph = (f"{voice},asplit=2[voice][key];"
             f"[{music_input}:a]aformat=sample_rates=48000:channel_layouts=stereo,volume={volume:.3f},atrim=0:{duration:.3f},"
             f"asetpts=PTS-STARTPTS,afade=t=in:d=1,afade=t=out:st={max(0.0, duration - 1.5):.3f}:d=1.5[bgm];"
             f"[bgm][key]sidechaincompress=threshold=0.05:ratio=3:attack=30:release=600[ducked];"
             f"[voice][ducked]amix=inputs=2:duration=first:dropout_transition=0:normalize=0[aout]")
    return ["-stream_loop", "-1", "-i", music], ["-filter_complex", graph, "-map", "0:v", "-map", "[aout]"]


def encode(input_args: list[str], vf: str, out: Path, duration: float, pref: str, progress=None, cwd=None,
           music: str | None = None, music_volume: float = 0.10, voice_input: int = 0):
    global _nvenc_ok
    tmp = out.with_suffix(".part.mp4")
    last = None
    extra_inputs, audio = audio_mix_args(duration, music, music_volume, voice_input, input_args.count("-i"))
    for enc in video_encoder_args(pref):
        try:
            run_ffmpeg([*input_args, *extra_inputs, *audio, "-vf", vf, *enc, "-r", "30", "-c:a", "aac", "-b:a", "192k",
                        "-ar", "48000", *clean_metadata_args(), "-movflags", "+faststart", "-f", "mp4", str(tmp)],
                       duration, progress, cwd=cwd)
        except MediaError as e:
            last = e
            if enc[1] == "h264_nvenc":
                log.warning("NVENC encode failed, retrying on CPU (libx264): %s", e)
            continue
        if enc[1] == "h264_nvenc":
            _nvenc_ok = True
        elif last is not None:
            _nvenc_ok = False  # GPU failed but CPU worked: stop trying NVENC this session
        tmp.replace(out)
        return enc[1]
    tmp.unlink(missing_ok=True)
    raise last


def frame_jpeg(input_args: list[str], vf: str | None, out: Path, cwd=None):
    run_ffmpeg([*input_args, *(["-vf", vf] if vf else []), "-frames:v", "1", "-update", "1", "-q:v", "3", str(out)], cwd=cwd)
