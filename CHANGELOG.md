# Changelog

## v8.0.0 — 2026-03-29

### Added
- Chat Editor tab — conversational AI editor agent for intake before processing
- Graphics engine — lower-thirds, title cards, animated popups, corner badges
- Multi-step thumbnail pipeline — Claude concept generation + FLUX backgrounds + Claude Vision review
- Color enhancement — auto color balance, contrast S-curve, saturation boost, sharpening
- Audio enhancement — 80Hz high-pass, voice EQ, compression, loudnorm to -14 LUFS
- Description template system with saved templates dropdown
- Custom description and special instructions per video
- Shorts auto-link back to main video in description
- Interactive setup.sh installer with API key prompts and health checks
- Intro/outro asset upload from dashboard header
- AGI-1 self-healing patterns (14 pipeline-specific error patterns)
- Security headers in nginx (X-Frame-Options, X-Content-Type-Options, XSS-Protection)
- Service runs as unprivileged yt-editor user (not root)

### Fixed
- YouTube title truncation to 100 chars (was causing upload failures)
- NameError in base.py (undefined variable `empty` in JSON parse error path)
- Missing `community_posts` step in V6_STEPS dict
- Hardcoded thumbnail directory path (now uses DATA_DIR env var)
- Overlapping cut_segment detection and auto-merge in validation
- Deploy script pm2 vs systemd inconsistency
- HeyGen voice_id now auto-fetched when not provided

## v7.0.0 — 2026-03-28

### Added
- V7 pipeline with checkpoint/resume
- Long-form caption burning (word-level animated captions)
- Community post image generation (frame-based + AI)
- Auto-publish mode (uploads to YouTube after QA passes)
- QA review agent with 2-layer scoring
- Short creation with hook restructuring
- AI thumbnails via FLUX (Replicate)

## v6.0.0 — 2026-03-26

### Added
- Initial release: full pipeline from ingest to YouTube upload
- Whisper transcription with word-level timestamps
- Filler word removal via FFmpeg
- Silence detection and dead air removal
- Claude-powered editing agents (intake, editor, short creator, packager)
- Next.js dashboard with real-time progress tracking
- YouTube OAuth integration
