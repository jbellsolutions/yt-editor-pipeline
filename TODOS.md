# TODOS

## Create Production Intro/Outro Clips
**Priority:** Medium
**Status:** Blocked (needs creative direction)
**Estimated effort:** human: ~2 hours creative work / CC: N/A (creative task)

**What:** Design and produce real intro and outro video clips for the YouTube channel. Current placeholder files are 17-18KB dummy files that are too small to be real video.

**Why:** The pipeline code already handles intro/outro concatenation for both long-form videos and shorts. But the actual asset files (`intro_default.mp4`, `outro_default.mp4`) are placeholder dummies. Without real intro/outros, every video ships without channel branding.

**Specs needed:**
- Long-form intro: 3-5 seconds, channel branding animation
- Long-form outro: 5-15 seconds, subscribe CTA + end screen compatible
- Short intro: 1-2 seconds, quick logo sting
- Short outro: 2-3 seconds, channel name + follow CTA
- All at 1920x1080 (long-form) and 1080x1920 (shorts)
- H.264 codec, AAC audio, 30fps

**How to deploy:** Once created, upload via:
```bash
scp intro.mp4 root@142.93.54.26:/opt/yt-editor/backend/assets/intro.mp4
scp outro.mp4 root@142.93.54.26:/opt/yt-editor/backend/assets/outro.mp4
scp short_intro.mp4 root@142.93.54.26:/opt/yt-editor/backend/assets/short_intro.mp4
scp short_outro.mp4 root@142.93.54.26:/opt/yt-editor/backend/assets/short_outro.mp4
```
Or use the API endpoints: `POST /api/assets/intro`, `POST /api/assets/outro`

**Depends on:** Brand guidelines / creative direction from channel owner
**Blocked by:** Nothing technical — purely a creative deliverable

## Set Up Playwright Cookies for Community Posting
**Priority:** High (blocks community post automation)
**Status:** Needs manual step
**Estimated effort:** human: ~5 minutes / CC: N/A (manual login required)

**What:** Run the cookie export helper to capture YouTube Studio login cookies for community post automation.

**How:**
```bash
ssh root@142.93.54.26
cd /opt/yt-editor/backend
source venv/bin/activate
pip install playwright && playwright install chromium
python -c "from engines.community_poster import export_browser_cookies; export_browser_cookies()"
```
This opens a browser, you log into YouTube, then press Enter to save cookies.

**Depends on:** Playwright installed on server
**Blocked by:** Nothing — just needs to be done once
