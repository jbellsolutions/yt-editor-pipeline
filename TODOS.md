# TODOS

## Current Status

The core pipeline is feature-complete: ingest, transcription, filler removal, Shorts detection, vertical crop, SEO metadata, thumbnail generation, and YouTube upload all work end-to-end. The setup script is an interactive installer that works on fresh Ubuntu/Debian servers.

---

## Create Production Intro/Outro Clips
**Priority:** Medium
**Status:** Blocked (needs creative direction)

Design and produce real intro and outro video clips for the YouTube channel. The pipeline already handles intro/outro concatenation, but the asset files are placeholders.

**Specs needed:**
- Long-form intro: 3-5 seconds, channel branding animation (1920x1080)
- Long-form outro: 5-15 seconds, subscribe CTA + end screen compatible (1920x1080)
- Short intro: 1-2 seconds, quick logo sting (1080x1920)
- Short outro: 2-3 seconds, channel name + follow CTA (1080x1920)
- H.264 codec, AAC audio, 30fps

**Blocked by:** Brand guidelines / creative direction from channel owner

## Set Up Playwright Cookies for Community Posting
**Priority:** High
**Status:** Needs manual step (one-time)

Run the cookie export helper to capture YouTube Studio login cookies for community post automation.

```bash
cd /opt/yt-editor/backend
source venv/bin/activate
pip install playwright && playwright install chromium
python -c "from engines.community_poster import export_browser_cookies; export_browser_cookies()"
```

Log into YouTube when the browser opens, then press Enter to save cookies.

## Add HTTPS / TLS Support
**Priority:** Medium
**Status:** Not started

Add Let's Encrypt / certbot integration to the setup script for production HTTPS. Currently Nginx serves on port 80 only.

## Add Batch Processing
**Priority:** Low
**Status:** Not started

Support submitting multiple video URLs at once and processing them as a queue.
