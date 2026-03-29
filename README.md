# YT Editor Pipeline

An AI-powered YouTube video editing pipeline that takes a raw video (URL or file upload) and automatically transcribes it, removes filler words, detects optimal Short segments, crops to vertical format, generates SEO metadata and thumbnails, and uploads everything to YouTube with scheduling support -- all reviewed through a dashboard before publishing.

## Architecture

```
Next.js Dashboard (port 3000)
        |
   Nginx Reverse Proxy (port 80)
        |
FastAPI Backend (port 8000)
   ├── Whisper API (transcription)
   ├── Claude API (shorts detection + SEO)
   ├── Replicate FLUX (thumbnails)
   ├── FFmpeg (video processing)
   ├── yt-dlp (video download)
   └── YouTube Data API (upload + scheduling)
```

## Quick Start

### Prerequisites

- A fresh Ubuntu 22.04+ server (2GB+ RAM recommended)
- API keys for OpenAI, Anthropic, and Replicate (see step 3 below)
- A Google Cloud project with YouTube Data API v3 enabled (see step 4 below)

### 1. Clone the repo

```bash
git clone https://github.com/YOUR_USERNAME/yt-editor-pipeline.git
cd yt-editor-pipeline
```

### 2. Run the setup script

The interactive installer handles all system dependencies, creates a service user, builds the frontend, and configures systemd services.

```bash
chmod +x scripts/setup.sh
sudo ./scripts/setup.sh
```

The script will walk you through everything. It installs Python 3, Node.js 20, FFmpeg, and Nginx, then sets up the project under `/opt/yt-editor`.

### 3. Configure API keys

The setup script will interactively prompt you for each key. Here is what they do:

| Key | Service | What it does | Where to get it |
|-----|---------|-------------|-----------------|
| `OPENAI_API_KEY` | OpenAI | Whisper transcription (speech-to-text with word-level timestamps) | [platform.openai.com/api-keys](https://platform.openai.com/api-keys) |
| `ANTHROPIC_API_KEY` | Anthropic | Claude AI for Shorts detection and SEO metadata generation | [console.anthropic.com](https://console.anthropic.com/) |
| `REPLICATE_API_TOKEN` | Replicate | FLUX model for AI-generated thumbnails | [replicate.com/account/api-tokens](https://replicate.com/account/api-tokens) |

### 4. Connect YouTube OAuth

You need a Google Cloud OAuth credential so the pipeline can upload videos to your YouTube channel.

1. Go to [console.cloud.google.com](https://console.cloud.google.com)
2. Create a new project (or select an existing one)
3. Navigate to **APIs & Services > Library** and enable **YouTube Data API v3**
4. Go to **APIs & Services > Credentials** and create an **OAuth 2.0 Client ID** (type: Web application)
5. Add `http://localhost:8000/auth/callback` as an authorized redirect URI
6. Download the JSON credentials file
7. Place it at `/opt/yt-editor/backend/config/client_secret.json`
8. Set up an SSH tunnel to your server:
   ```bash
   ssh -L 8000:localhost:8000 user@YOUR_SERVER_IP
   ```
9. Visit `http://localhost:8000/auth/youtube` in your browser and authorize the app
10. Restart the backend:
    ```bash
    sudo systemctl restart yt-backend
    ```

### 5. Open the dashboard

Navigate to `http://YOUR_SERVER_IP` in your browser. The Nginx reverse proxy serves the dashboard on port 80.

From the dashboard you can:
- Submit video URLs or upload files
- Monitor pipeline progress in real time
- Review processed videos, Shorts, thumbnails, and SEO metadata
- Approve and schedule uploads to YouTube

## API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/health` | GET | System health check and YouTube auth status |
| `/auth/youtube` | GET | Start YouTube OAuth flow |
| `/auth/status` | GET | Check authentication status |
| `/api/ingest` | POST | Submit a video URL for processing |
| `/api/upload` | POST | Upload a video file directly |
| `/api/jobs` | GET | List all processing jobs |
| `/api/jobs/{id}` | GET | Get details for a specific job |
| `/api/jobs/{id}/approve` | POST | Approve a job and upload to YouTube |
| `/api/thumbnails/{file}` | GET | Serve a generated thumbnail image |
| `/api/logs` | GET | View pipeline logs |

## Cost Per Video

| Service | Cost |
|---------|------|
| Whisper | ~$0.006/min of audio |
| Claude | ~$0.02/video |
| FLUX thumbnails | ~$0.03/image x 4 |
| **Total** | **~$0.15 -- $0.25/video** |

## Tech Stack

- **Backend:** Python 3.12, FastAPI, FFmpeg, yt-dlp
- **Frontend:** Next.js 15, React 19, TypeScript, Tailwind CSS
- **AI:** OpenAI Whisper, Claude Sonnet, FLUX via Replicate
- **Infrastructure:** Nginx reverse proxy, systemd services, Ubuntu/Debian

## Project Structure

```
yt-editor-pipeline/
├── backend/
│   ├── main.py              # FastAPI application
│   ├── pipeline.py          # Core processing pipeline
│   ├── youtube_auth.py      # YouTube OAuth handling
│   ├── validation.py        # Input validation
│   ├── engines/             # Processing engines
│   │   ├── transcription.py # Whisper transcription
│   │   ├── ffmpeg_engine.py # FFmpeg video processing
│   │   ├── thumbnail.py     # FLUX thumbnail generation
│   │   └── video_composer.py# Video assembly
│   ├── agents/              # AI agent logic
│   ├── assets/              # Intro/outro clips
│   ├── config/              # OAuth credentials (gitignored)
│   └── requirements.txt
├── frontend/                # Next.js dashboard
├── infra/
│   └── nginx.conf           # Nginx reverse proxy config
├── scripts/
│   └── setup.sh             # Interactive installer
└── README.md
```

## License

MIT
