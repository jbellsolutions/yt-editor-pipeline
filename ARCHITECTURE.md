# Architecture

## System Overview

```
┌─────────────────────────────────────────────────┐
│                  FRONTEND                        │
│  Next.js Dashboard (port 3000)                  │
│  ├── Quick Mode: URL / Upload / Avatar / UGC    │
│  ├── Chat Editor: Conversational intake agent   │
│  └── Review: Approve, select titles/thumbnails  │
└───────────────────┬─────────────────────────────┘
                    │
          Nginx Reverse Proxy (port 80)
                    │
┌───────────────────┴─────────────────────────────┐
│                  BACKEND                         │
│  FastAPI Application (port 8000)                │
│  ├── Chat Routes: /api/chat/* (SSE streaming)   │
│  ├── Pipeline Routes: /api/ingest, /api/upload  │
│  ├── Job Management: /api/jobs/*                │
│  └── YouTube: /auth/*, /api/jobs/*/approve      │
└───────────────────┬─────────────────────────────┘
                    │
┌───────────────────┴─────────────────────────────┐
│              AI AGENT TEAM                       │
│  ├── Chat Editor Agent (conversational intake)  │
│  ├── Intake Agent (content analysis)            │
│  ├── Editor Agent (cut decisions)               │
│  ├── Short Creator (hook detection)             │
│  ├── Packager (SEO + copywriting)               │
│  └── QA Agent (quality scoring)                 │
└───────────────────┬─────────────────────────────┘
                    │
┌───────────────────┴─────────────────────────────┐
│            PROCESSING ENGINES                    │
│  ├── FFmpeg Engine (cuts, overlays, audio)       │
│  ├── Graphics Engine (lower-thirds, titles)      │
│  ├── Thumbnail Engine (FLUX + Claude Vision)     │
│  ├── Transcription Engine (Whisper)              │
│  └── YouTube Upload (OAuth + Data API v3)        │
└─────────────────────────────────────────────────┘
```

## Pipeline Flow

```
Video In → Download → Transcribe → Analyze → Intake Agent
    → Editor Agent → Execute Edits (FFmpeg)
        → Color Enhancement
        → Audio Enhancement (EQ + compression + loudnorm)
        → Graphics Overlays (lower-thirds, title cards)
        → Intro/Outro Concatenation
    → Caption Burning → Short Design → Short Creation
    → Packaging (SEO) → Thumbnail Generation → QA Review
    → [Auto-Publish OR Ready for Review]
```

## Data Storage

```
/opt/yt-editor/
├── backend/          # Application code
│   ├── config/       # OAuth credentials, cookies (not in git)
│   └── assets/       # Intro/outro clips
├── data/             # All job data
│   ├── inbox/        # Downloaded raw videos
│   ├── edited/       # Processed videos
│   ├── shorts/       # Generated shorts
│   ├── thumbnails/   # Generated thumbnails
│   ├── metadata/     # Agent checkpoints
│   ├── chat_sessions/# Chat editor conversations
│   ├── logs/         # Pipeline logs
│   └── jobs.json     # Job state database
└── frontend/         # Next.js dashboard
```

## Key Design Patterns

- **Checkpoint/Resume**: Each pipeline step saves JSON output. On restart, completed steps are skipped.
- **Background Threads**: Jobs run in daemon threads with MAX_CONCURRENT_JOBS=1. A watchdog thread detects and marks stale jobs.
- **Validation Gates**: Every AI agent output goes through validation.py before use.
- **Self-Healing**: Error patterns in .claude/healing/patterns.json enable automatic fix attempts.
