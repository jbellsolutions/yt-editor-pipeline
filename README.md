# YT Editor Pipeline

AI-powered YouTube video editor. Drop in a video, get back a polished edit with shorts, thumbnails, and SEO — ready to publish.

## What It Does

You give it a raw video. It gives you back:
- Filler words and dead air removed
- Color and audio enhanced (broadcast quality)
- 3-5 YouTube Shorts auto-created from the best moments
- AI-generated thumbnails (for long-form and each Short)
- SEO titles, descriptions, and tags
- Everything uploaded to your YouTube channel (you approve first)

Cost: ~$0.15-0.25 per video.

## How to Install

### Option A: Use Claude Code (easiest)

If you have [Claude Code](https://claude.ai/claude-code), just say:

> "Clone https://github.com/jbellsolutions/yt-editor-pipeline and install it on my server"

Claude will handle everything — cloning, running setup, configuring services. It reads the CLAUDE.md file in this repo which has full installation instructions.

**You'll need to provide:**
1. An Ubuntu/Debian server (a $12/month DigitalOcean droplet works great)
2. SSH access to that server
3. API keys (Claude will tell you where to get each one):
   - **OpenAI** — for transcription ([get key](https://platform.openai.com/api-keys))
   - **Anthropic** — for AI editing decisions ([get key](https://console.anthropic.com/))
   - **Replicate** — for thumbnail generation ([get key](https://replicate.com/account/api-tokens))
4. A Google Cloud OAuth credential for YouTube uploads (this is the only tricky part — Claude will walk you through it step by step)

### Option B: Manual install

```bash
git clone https://github.com/jbellsolutions/yt-editor-pipeline.git
cd yt-editor-pipeline
sudo ./scripts/setup.sh
```

The setup script walks you through everything interactively.

## How to Use

Open `http://YOUR_SERVER_IP` in your browser. Two modes:

- **Video URL / Upload** — Paste a YouTube/Loom/Vimeo link or upload a file. Add optional description template and instructions. Hit process.
- **Chat Editor** — Talk to the AI editor. Tell it what you want: "fast cuts, highlight the demo at 5:30, add my name as a lower-third." It asks smart questions, then you hit Start Editing.

Both modes produce the same output: an edited video with shorts, thumbnails, and SEO metadata. Review everything in the dashboard, then approve to upload to YouTube.

## Cost Per Video

| Service | Cost |
|---------|------|
| Whisper (transcription) | ~$0.006/min |
| Claude (editing AI) | ~$0.02/video |
| FLUX (thumbnails) | ~$0.03/image |
| **Total** | **~$0.15-0.25/video** |

## License

MIT — use it however you want.
