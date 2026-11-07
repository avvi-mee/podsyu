"""Paths, environment configuration and user-editable settings (persisted in SQLite)."""
import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[3]
load_dotenv(ROOT / ".env")

DATA_DIR = Path(os.getenv("PSF_DATA_DIR", ROOT / "data")).resolve()
PROJECTS_DIR = DATA_DIR / "projects"
SECRETS_DIR = DATA_DIR / "secrets"
LOG_DIR = DATA_DIR / "logs"
MODELS_DIR = ROOT / "models"
DB_PATH = DATA_DIR / "app.db"
CLIENT_SECRET_PATH = SECRETS_DIR / "client_secret.json"
MUSIC_DIR = DATA_DIR / "music"  # background music library (drop MP3s here or upload in the dashboard)
MEDIA_DIR = DATA_DIR / "media"  # background videos for story shorts
TTS_DIR = MODELS_DIR / "tts"  # Kokoro TTS model files

for d in (DATA_DIR, PROJECTS_DIR, SECRETS_DIR, LOG_DIR, MODELS_DIR, MUSIC_DIR, MEDIA_DIR, TTS_DIR):
    d.mkdir(parents=True, exist_ok=True)

API_PORT = int(os.getenv("PSF_API_PORT", "8000"))
FRONTEND_PORT = int(os.getenv("PSF_FRONTEND_PORT", "3000"))
FRONTEND_URL = os.getenv("PSF_FRONTEND_URL", f"http://localhost:{FRONTEND_PORT}")

# Defaults for settings editable in the dashboard. Env vars seed the defaults.
DEFAULT_SETTINGS: dict = {
    "whisper_model": os.getenv("WHISPER_MODEL", "small"),
    "whisper_device": os.getenv("WHISPER_DEVICE", "auto"),  # auto | cuda | cpu
    "transcription_language": "auto",
    "ollama_url": os.getenv("OLLAMA_URL", "http://localhost:11434"),
    "ollama_model": os.getenv("OLLAMA_MODEL", "qwen2.5:7b-instruct"),
    "ollama_num_ctx": 8192,
    "encoder": "auto",  # auto | gpu | cpu  (NVENC vs libx264)
    "min_duration": 30,
    "max_duration": 60,
    "num_shorts": 5,
    "default_caption_preset": "hormozi",
    "output_resolution": "1080x1920",
    "timezone": os.getenv("PSF_TIMEZONE", "Asia/Kolkata"),
    "output_dir": os.getenv("PSF_OUTPUT_DIR", str(DATA_DIR / "exports")),
    "auto_cleanup_source": False,
    "youtube_redirect_uri": os.getenv(
        "YOUTUBE_REDIRECT_URI", f"http://localhost:{API_PORT}/api/youtube/oauth/callback"
    ),
    "default_privacy": "private",
}

RESOLUTIONS = {"1080x1920": (1080, 1920), "720x1280": (720, 1280)}
