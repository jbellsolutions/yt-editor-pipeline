# YT Editor Pipeline

AI-powered YouTube video editing pipeline. Drop in a video (URL or file upload), and the system automatically:

1. **Downloads** the video from any URL (Loom, YouTube, Vimeo, direct links) or accepts file uploads
2. **Transcribes** with word-level timestamps using OpenAI Whisper
3. **Removes filler words** (um, uh, uhm, etc.) with precision cuts via FFmpeg
4. **Detects optimal Short segments** (30-60s self-contained clips) using Claude AI
5. **Crops Shorts to 9:16 vertical** format automatically
6. **Generates SEO metadata** — titles, descriptions, tags optimized for YouTube search
7. **Creates AI thumbnails** using FLUX image generation
8. **Uploads to YouTube** with scheduling support — long-form + Shorts

Everything goes through a review dashboard before publishing. You approve, it uploads.

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
   └── YouTube Data API (upload)
```

## Cost Per Video

| Service | Cost |
|---------|------|
| Whisper | ~$0.006/min of audio |
| Claude | ~$0.02/video |
| FLUX thumbnails | ~$0.03/image x4 |
| **Total** | **~$0.15-0.25/video** |

## Quick Start

### Prerequisites

- Ubuntu 22.04+ server (2GB+ RAM)
- API keys: OpenAI, Anthropic, Replicate
- Google Cloud project with YouTube Data API v3 enabled

### Setup

```bash
# Clone
git clone https://github.com/YOUR_USERNAME/yt-editor-pipeline.git
cd yt-editor-pipeline

# Run setup on your server
chmod +x scripts/setup.sh
sudo ./scripts/setup.sh

# Configure API keys
cp backend/.env.example /opt/yt-editor/backend/.env
nano /opt/yt-editor/backend/.env  # Fill in your keys

# Place Google OAuth credentials
cp your-client-secret.json /opt/yt-editor/backend/config/client_secret.json

# Restart
sudo systemctl restart yt-backend

# Connect YouTube (one-time)
ssh -L 8000:localhost:8000 root@YOUR_SERVER_IP
# Then visit http://localhost:8000/auth/youtube in your browser
```

### Google Cloud Setup (YouTube API)

1. Go to [console.cloud.google.com](https://console.cloud.google.com)
2. Create project → Enable **YouTube Data API v3**
3. Create OAuth 2.0 credentials (Web application)
4. Set redirect URI: `http://localhost:8000/auth/callback`
5. Download the JSON → place as `config/client_secret.json`

## API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/health` | GET | System health + YouTube auth status |
| `/auth/youtube` | GET | Start YouTube OAuth flow |
| `/auth/status` | GET | Check authentication status |
| `/api/ingest` | POST | Submit video URL for processing |
| `/api/upload` | POST | Upload video file directly |
| `/api/jobs` | GET | List all jobs |
| `/api/jobs/{id}` | GET | Get job details |
| `/api/jobs/{id}/approve` | POST | Approve and upload to YouTube |
| `/api/thumbnails/{file}` | GET | Serve generated thumbnails |
| `/api/logs` | GET | View pipeline logs |

## Tech Stack

- **Backend:** Python 3.12, FastAPI, FFmpeg, yt-dlp
- **Frontend:** Next.js 15, TypeScript, Tailwind CSS
- **AI:** OpenAI Whisper, Claude Sonnet, FLUX (Replicate)
- **Infra:** Nginx, systemd, Digital Ocean

## License

MIT
