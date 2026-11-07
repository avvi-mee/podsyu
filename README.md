# PODSYU - local AI content factory

Three engines, one dashboard, all running on your PC:

| Engine | What it makes |
|---|---|
| **Podcast Clipper** | The best self-contained moments of long conversations (30-60 s) |
| **Famous Creators Clipper** | The funniest / wildest 10-30 s moments of creator, gaming and stream videos |
| **ASMR Stories Factory** | Story shorts: script + local AI voice + satisfying background + captions + BGM |

All three share rendering (9:16, H.264/AAC, burned captions, fades, ducked BGM), the Media Library,
Generated Shorts, the Publishing Calendar and YouTube publishing. Details for the two newer engines are in
**"PODSYU engines"** below. The original podcast workflow:

A free, local, AI-powered podcast-to-YouTube-Shorts app. Paste a YouTube URL (for a video you own or are authorized to use) or upload a video file, and it will:

1. download / import the video
2. transcribe it with **faster-whisper** (word-level timestamps, GPU with CPU fallback)
3. find self-contained moments with a local LLM via **Ollama**, in two passes:
   - scan the whole transcript for candidates
   - for each candidate, pick the exact opening hook line and the payoff line, and score hook, standalone and payoff

   Code then enforces the rules:
   - start on a real sentence (never filler or a sentence fragment)
   - end on a completed statement (never on a new question)
   - include a directly following wrap-up line
   - skip the episode's intro/teaser, sponsor reads and outro
4. cut each moment, **reframe it to 9:16** (follows the speaking person using face + lip-motion detection)
5. **burn in word-synced captions** (5 presets, fully customizable, live preview)
6. write the **title, description and hashtags** from what's actually said
7. let you review, edit, approve/reject, download, and **publish or schedule to YouTube** through the official YouTube Data API v3

Every short also gets:
- **Fades:** a 0.5 s fade in and out (picture, captions and sound).
- **Loudness:** speech normalised to a consistent Shorts level.
- **Optional background music:** quiet by default (Low = 10%). It dips automatically while people talk, fills the pauses, loops for long clips and fades out at the end.
- **Length:** 30–60 s by default (change in Settings or per project).

Manage tracks on the **Background Music** page:
- **Adding tracks:** upload MP3/WAV/M4A or drop files into `data\music`.
- **Choosing music:** pick a track on Create Shorts, apply one track to all shorts from the project page, or set one per short in "Captions & framing".
- **Credits:** if a track has a credit line (e.g. Creative Commons BY), it is added to the YouTube description automatically.
- **Safest source for monetised channels:** YouTube Studio → Audio Library (filter "Attribution not required").
- **Starter tracks:** six Kevin MacLeod tracks from incompetech.com (CC BY 4.0, credit auto-filled).

Every exported short is written with **clean file metadata**: no tags, chapters or handler names copied from the source download, and no FFmpeg/x264 version strings. The creation time is the render time. Only file metadata is changed: the picture and sound are untouched, and this has no effect on YouTube's content matching.

Everything runs on your PC. No paid APIs, no subscriptions, no cloud requirement (a free Google Cloud project is needed only for YouTube uploading).

---

## Quick start (Windows 11)

Prerequisites (one time):

| Tool | Install |
|---|---|
| Python 3.13 (3.11–3.13 work) | https://www.python.org/downloads/ (tick "Add to PATH") |
| Node.js LTS (20+) | https://nodejs.org |
| FFmpeg | `winget install Gyan.FFmpeg` then open a **new** terminal |
| Ollama | https://ollama.com/download |
| NVIDIA driver (optional) | GeForce Experience / nvidia.com. Any driver supporting CUDA 12+ |

Then double-click **`start.bat`**. On first run it calls `scripts\setup.bat`, which:

- creates `backend\.venv` and installs the Python packages (~1.5 GB incl. CUDA 12 runtime libraries for the GPU)
- installs and builds the dashboard
- downloads the YuNet face-detection model (~230 KB)
- pulls the default LLM `qwen2.5:7b-instruct` (4.7 GB) if no qwen2.5 model is installed

The dashboard opens at **http://localhost:3000**. Stop everything with **`stop.bat`**.

> **Start-menu app:** run `powershell -ExecutionPolicy Bypass -File scripts\create_shortcut.ps1` once. Then search Windows for **Shorts Clipper** to start the app and open the dashboard, or **Stop Shorts Clipper** to stop it. Run the script again if you move the folder.

> If another app already uses port 3000, `start.bat` stops and names it. Either stop that app, or add `PSF_FRONTEND_PORT=3001` to `.env` (copy `.env.example`) and the dashboard runs at http://localhost:3001.

> Jobs are stored in SQLite. If you stop the app mid-processing, the job resumes from the last finished stage on the next start.

---

## Manual installation (what setup.bat does)

```bat
cd backend
py -3.13 -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
cd ..\frontend
npm install
npm run build
```

Run in two terminals:

```bat
cd backend  &&  .venv\Scripts\python run.py                  :: API on http://127.0.0.1:8000
cd frontend &&  npm run start -- -H 127.0.0.1 -p 3000         :: dashboard on http://localhost:3000
```

For development use `npm run dev` instead of `npm run start`.

### FFmpeg
`winget install Gyan.FFmpeg` (the "full" build includes libass for captions and NVENC for GPU encoding). Check with `ffmpeg -version`. Reopen your terminal afterwards so PATH is refreshed.

### NVIDIA GPU / CUDA
You do **not** need to install the CUDA Toolkit. `requirements.txt` installs `nvidia-cublas-cu12` and `nvidia-cudnn-cu12`, and the app loads those DLLs automatically. If the cuBLAS wheel is missing, it also uses the CUDA 12 cuBLAS that ships with Ollama for Windows. You only need a recent NVIDIA driver (`nvidia-smi` should work). Settings → System shows **faster-whisper CUDA: OK** when everything is found.

- Transcription runs on the GPU in float16. If the GPU fails (missing driver, out of memory) it **falls back to CPU automatically** (int8).
- Video encoding uses NVENC (`h264_nvenc`) and falls back to `libx264` on the CPU.
- On a 6 GB card (e.g. RTX 3050) the pipeline never holds Whisper and the LLM in VRAM at the same time: Whisper is unloaded after transcription and the Ollama model is unloaded before rendering.
- Settings → System shows GPU name, VRAM usage and whether faster-whisper sees CUDA.

### faster-whisper models
Models download automatically to `models/whisper` on first use. Choose in Settings:

| Model | VRAM | Notes |
|---|---|---|
| base | ~0.5 GB | fastest, lower accuracy |
| **small** (default) | ~1 GB | good balance |
| medium | ~2.5 GB | better names/jargon |
| large-v3-turbo | ~1.6 GB | best accuracy/speed on 6 GB GPUs |

### Ollama and the LLM
Install Ollama, then pull a model:

```bat
ollama pull qwen2.5:7b-instruct     :: default, best quality that fits 6 GB VRAM
ollama pull qwen2.5:3b              :: faster, lower quality
```

`qwen2.5:7b-instruct` needs ~5 GB VRAM while it runs. If your PC is short on RAM (many apps open), pick `qwen2.5:3b` in Settings: it's faster and lighter, but titles and moment picks are a bit weaker.

Pick the model in Settings. The app talks to `http://localhost:11434` (change in Settings/`.env`). `start.bat` starts `ollama serve` if it isn't running.

---

## PODSYU engines

### Famous Creators Clipper
1. Paste a YouTube link → **Inspect** shows title, creator, duration and whether captions exist.
2. Choose how to get the media:
   - **Authorized download**: tick "I own this video or have permission". The video is downloaded and gets the full analysis.
   - **Your own file**: upload it, for the same full analysis.
   - **Neither**: the app analyses the video's *published captions only* and says so. That can't see facial expressions or visual jokes. Candidates can't be rendered until you attach the authorized file ("Upload authorized video to render").
3. Analysis:
   - **Scenes:** the AI finds complete entertaining scenes, then the best individual moments inside each (not equal cuts).
   - **Default length:** 15 s (12-18 s). Also 10 / 20 / 30.
   - **Signals:** loud reactions (audio peaks), motion and camera cuts.
   - **Score (0-100):** combines humor, surprise, reaction, hook, completeness and context-independence, with a repetition penalty. It's a ranking aid, not a virality prediction.
4. Sort the candidates (funniest, highest score, newest timestamp, shortest, longest), then **Render selected**.
5. Layouts: *follow the speaker/webcam* (crop), or *full frame*, which keeps gameplay and on-screen info over a blurred fill.

### ASMR Stories Factory
- **Story sources:**
  - **Find Stories**: Reddit via its official API (free app key in Settings). Reddit stories are marked *needs permission* until you confirm you have the author's permission, or you click *Write original inspired by this*.
  - **Generate Random Story / Create Custom Story**: original fiction written by the local LLM.
  - **Upload My Own Story**: paste text or load a .txt file.
- **Generate Short** runs everything:
  1. adapts the story into a script (hook, incident, escalation, twist)
  2. voices it locally with **Kokoro TTS** (Apache-2.0, built-in voices, no voice cloning)
  3. word-syncs the captions with Whisper
  4. picks background footage and BGM that match the story's mood
  5. mixes the audio (voice normalised, music low and ducked, fades)
  6. renders the short and writes title and hashtags
- **Voice controls:** profile (expressive default, female, male, neutral, deep, youthful, storyteller, whisper), emotion, pitch, speed, volume, pause length and pronunciation fixes (`GIF = jif`). *Preview voice* plays a sample.
- **After generation:** edit captions/music and re-render, or *Regenerate voice & captions*.

### Media Library
- **Background videos:**
  - upload your own footage (gameplay you recorded, satisfying clips)
  - generate **original** loops locally (neon plasma, Game of Life, Mandelbrot zoom, dark mist, calm gradient)
  - import licensed stock from **Pexels** (free API key)

  Every item stores its source, creator and licence. Tag a category and star favourites; auto-selection prefers them.
- **BGM library:**
  - **Adding music:** upload audio, or extract the audio track from a video you own.
  - **Track details:** set category, licence, source and credit (added to YouTube descriptions automatically). Star favourites.
  - **Find catchy snippets:** detects the most hook-like part of a track (loud, punchy and repeated, like a chorus) and saves 15 / 20 / 30 s loopable snippets. Each has preview, trim and delete.
  - **Fitting the video:** when a full track is chosen, its 20 s snippet is used and looped with crossfades to the video's length.
- **Starter tracks:** 24 Kevin MacLeod tracks from incompetech.com (CC BY 4.0, credit filled in) across funny, suspense, dark, horror, relaxing, emotional, cinematic, mysterious and inspirational.

### Content source API keys (Settings → Content source API keys)
| Key | Where | Used for |
|---|---|---|
| Reddit client ID + secret | reddit.com/prefs/apps → create app → *script* | Story discovery (official API, app-only) |
| Pexels API key | pexels.com/api | Licensed stock background videos |

Keys are encrypted with Windows DPAPI in `data/secrets` and never sent to the browser.

### Models used by the new engines
`scripts\setup.bat` (or `backend\.venv\Scripts\python scripts\download_models.py`) downloads:
- the Kokoro voice model (~350 MB) into `models	ts`
- the YuNet face detector

Downloads use parallel connections and are safe to re-run.

## Google OAuth / YouTube API setup (free, one time)

1. Go to https://console.cloud.google.com/ and create a project.
2. **APIs & Services → Library** → search **YouTube Data API v3** → **Enable**.
3. **APIs & Services → OAuth consent screen** (Google Auth Platform):
   - User type **External**, app name e.g. "My Shorts Factory", your email as support/developer contact.
   - Under **Audience → Test users**, add the Google account that owns your YouTube channel.
4. **APIs & Services → Credentials → Create credentials → OAuth client ID**:
   - Application type: **Web application**
   - **Authorized redirect URIs**: `http://localhost:8000/api/youtube/oauth/callback`
5. Click **Download JSON**.
6. In the dashboard open **YouTube Accounts**, click **Load client JSON** and select the file. It is stored in `data/secrets/client_secret.json` and never sent to the browser.
7. Click **Connect YouTube account**, sign in, pick your channel, and approve. Tokens are encrypted with Windows DPAPI (tied to your Windows user) in `data/app.db`.

### Things Google enforces (shown as clear errors in the app)

- **Testing mode tokens expire after 7 days.** While the consent screen is in "Testing", reconnect the account weekly, or publish the app (Audience → Publish app). Personal use doesn't require verification for the token to stop expiring, but Google may show an "unverified app" warning you can click through.
- **Unverified projects upload as private.** Google locks videos uploaded through API projects that haven't passed a YouTube API audit to *private*. The app checks the real status after upload and only shows **Published** when the API confirms the video is public. Otherwise it shows "uploaded (private)" with an explanation. To publish publicly through the API, request an audit via the [YouTube API Services audit form](https://support.google.com/youtube/contact/yt_api_form), or switch the video to public yourself in YouTube Studio.
- **Quota:** 10,000 units/day by default and each upload costs ~1,600 units, so about **6 uploads per day**. Quota resets at midnight Pacific Time.

### Publishing options
| Option | How it works | PC must be on? |
|---|---|---|
| Publish now | Uploads immediately as public / unlisted / private | Only while uploading |
| Schedule on YouTube | Uploads now as private with `publishAt`; YouTube makes it public at that time | No |
| Schedule upload (this app) | The app's local scheduler uploads at the chosen time | **Yes, the PC and app must be running** |

The calendar shows scheduled, published and failed uploads. You can reschedule (YouTube-scheduled videos are updated through the API), cancel, or retry failed uploads. The default timezone is Asia/Kolkata (Settings).

If YouTube's daily API quota (about 6 uploads/day on the free tier) runs out, the upload stays pending and retries automatically after the quota resets at midnight Pacific Time. The app must be running then.

### Autopilot (sidebar → Autopilot)
Fill in the YouTube link, clip length, shorts to make and channel, then press **Next**. A dialog asks how each clip goes out: **Post now** (as soon as it is rendered), **Schedule** (a date and time) or **Don't post**. Use "Schedule all from … every …" to fill the times in one click. Clip 1 is the AI's best clip, Clip 2 the next, and so on. Press **Start autopilot**; nothing needs approving. Captions use the default style from Settings. A scheduled time that passes while the video is still processing becomes "post now". The project page shows the plan's status, and the Publishing Calendar can still reschedule or cancel each post.

---

## Using the app

1. **Create Shorts**: paste a YouTube URL → *Import video* (shows title, thumbnail, duration, channel) → confirm you're authorized. Or upload an MP4/MOV/MKV/WEBM.
2. Choose min/max duration (default 30–90 s), number of shorts, content category, strategy and caption preset → **Generate Shorts**.
3. The project page shows live progress per stage (WebSocket). Shorts appear when rendering finishes.
4. Each short card has the video on the left and the title, description, hashtags, transcript, timestamps, category and score on the right. You can:
   - edit and save metadata, or regenerate the title, description or hashtags with the LLM
   - **Captions & framing**: change caption style with a live preview (a real FFmpeg frame), switch auto/manual crop position, trim start/end, then save to re-render
   - regenerate captions (re-transcribes just that clip), re-render, delete, download the MP4, approve or reject
   - **Publish** to YouTube
5. Bulk-approve/reject/delete from the project page or **Generated Shorts**, and apply one caption preset to all shorts in a project.
6. **Find new clips** re-runs the AI selection on the saved transcript (no re-transcription). **Delete source video now** frees disk space while keeping finished shorts.
7. **Auto-delete the source video when finished**: tick it on Create Shorts, or flip the switch on the project page, even while it's processing. The video is deleted only after every short renders successfully. The default for new projects is in Settings. For YouTube projects, "Re-render all" downloads the video again if needed.

---

## Project structure

```
backend/
  run.py                  start the API (uvicorn, 127.0.0.1:8000)
  app/
    main.py               FastAPI app, CORS, cross-site write protection
    api/                  REST routes: projects, shorts, publishing, system (+ /ws WebSocket)
    core/                 config (.env + defaults), DPAPI token encryption
    database/             SQLite engine/session (WAL)
    models/               SQLAlchemy models: Project, Short, Job, Publication, YouTubeAccount, ...
    services/             job queue (persistent, resumable), pipeline, settings
    processors/           ffmpeg helpers, yt-dlp download, reframing, captions (ASS), rendering
    ai/                   faster-whisper transcription, Ollama moment detection + metadata
    publishing/           YouTube OAuth + resumable upload + schedule updates
    scheduler/            local publishing scheduler
  tests/test_core.py      self-checks for clip selection, captions, reframing, hashtags, DPAPI
frontend/                 Next.js (App Router) + TypeScript + Tailwind + shadcn/ui
data/                     created at runtime: app.db, projects/<id>/ (source, transcript, ASS), exports/, logs/, secrets/
models/                   whisper models + YuNet face detector
scripts/setup.bat         installer
start.bat / stop.bat
```

Run the self-checks: `cd backend && .venv\Scripts\python -m tests.test_core`

---

## Troubleshooting

| Problem | Fix |
|---|---|
| "Backend offline" in sidebar | Check the *Shorts Factory - Backend* window or `data\logs\app.log`. Port 8000 must be free. |
| `Cannot reach Ollama` | Start Ollama (tray app or `ollama serve`). Check `ollama list`. |
| `model ... is not installed` | `ollama pull <model>` or choose an installed model in Settings. |
| Transcription is slow / "on CPU" | Settings → System shows if CUDA is detected. Update the NVIDIA driver; re-run `pip install -r requirements.txt`. |
| CUDA out of memory | Use a smaller Whisper model, close games/other GPU apps. The app retries on CPU automatically. |
| YouTube download fails | Private, age-restricted, members-only and DRM videos can't be downloaded. If yt-dlp says YouTube changed: `backend\.venv\Scripts\python -m pip install -U yt-dlp`. Otherwise download your video from YouTube Studio and upload the file. |
| `redirect_uri_mismatch` | The redirect URI in Google Cloud must exactly equal Settings → YouTube OAuth redirect URI. |
| `access_denied` on Google sign-in | Add your account under OAuth consent screen → Test users. |
| "authorization expired" | Testing-mode tokens last 7 days. Reconnect on the YouTube Accounts page. |
| `quotaExceeded` | Daily API quota used up. Wait until midnight Pacific Time. |
| Video uploaded but private | Unverified API project (see above). |
| Captions show a fallback font | The font must be installed in Windows. Pick another in the caption editor. |
| Few or no clips found | Widen the duration range, change strategy, or use a larger Ollama model. Very short videos may have no 30 s+ self-contained moments. |
| "Port 3000 is used by another program" | Another app (e.g. a different Next.js project) owns the port. `start.bat` refuses to start rather than open the wrong app. Stop that program, then start again. `stop.bat` only ever stops processes started from this folder. |
| First transcription seems stuck at "Downloading Whisper model" | The model (~460 MB for *small*) downloads once, using parallel connections. Progress is shown in the job. Interrupted downloads resume. |

## Known limitations

- Active-speaker framing is a heuristic (face detection + lip motion + scene cuts). It works well for typical podcast layouts. When it can't find faces it uses a centre crop, and you can set a manual crop position per short.
- Speaker diarization is not included. Clip selection relies on the transcript only.
- App-managed scheduled uploads need the PC on. YouTube-managed scheduling does not.
- The API has no login and binds to 127.0.0.1 only. Don't expose ports 8000/3000 to a network.
