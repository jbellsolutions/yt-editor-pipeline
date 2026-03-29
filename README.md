# YT Editor Pipeline

Your own AI-powered YouTube video editor. Drop in a video, get back a polished edit with shorts, thumbnails, SEO titles, and descriptions — ready to publish to your channel.

## What It Does

You give it a raw video (paste a link or upload a file). It gives you back:

- Filler words ("um", "uh") and awkward pauses removed
- Color enhanced and audio cleaned up
- 3-5 YouTube Shorts auto-created from the best moments
- AI-generated thumbnails for everything
- SEO-optimized titles, descriptions, and tags
- One-click upload to your YouTube channel

Cost: about $0.15-0.25 per video in API fees.

## How to Install

### If you have Claude Code (easiest way)

Open Claude Code and say:

> "Install this YouTube editor for me: https://github.com/jbellsolutions/yt-editor-pipeline"

Claude will ask you a few questions (Mac/Windows/Linux? Local or server?) and handle the entire setup for you. The only part you'll need to do yourself is set up the Google Cloud YouTube connection — Claude walks you through that step by step.

### If you want to install manually

You need: Mac, Windows (with WSL2), or a Linux server.

**On Mac:**
```
brew install python@3.12 node@20 ffmpeg
git clone https://github.com/jbellsolutions/yt-editor-pipeline.git
cd yt-editor-pipeline/backend
python3 -m venv venv && source venv/bin/activate && pip install -r requirements.txt
cd ../frontend && npm install && npm run build
```

**On a server (Ubuntu/Debian):**
```
git clone https://github.com/jbellsolutions/yt-editor-pipeline.git
cd yt-editor-pipeline
sudo ./scripts/setup.sh
```

The setup script walks you through everything.

## What You'll Need

- **3 API keys** (takes ~5 min to set up):
  - [OpenAI](https://platform.openai.com/api-keys) — for transcription
  - [Anthropic](https://console.anthropic.com/) — for the AI editing brain
  - [Replicate](https://replicate.com/account/api-tokens) — for thumbnail generation
- **Google Cloud YouTube OAuth** — so it can upload to your channel (Claude walks you through this)

## How to Use

Open the dashboard in your browser. Two modes:

1. **Video URL / Upload** — Paste any video link (YouTube, Loom, Vimeo, or direct MP4). Optionally add a description template and special instructions. Hit Process.

2. **Chat Editor** — Talk to the AI editor like a person. "Make it fast-paced, highlight the demo at 5:30, add my name as a lower-third." It asks smart questions, then you hit Start Editing.

Review everything before it publishes. You approve, it uploads.

## License

MIT — use it however you want.
