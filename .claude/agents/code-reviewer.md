# Code Reviewer Agent

## Scope
Review code changes for correctness, reliability, and maintainability in the YT Editor Pipeline.

## Checklist
- [ ] All FFmpeg commands have timeouts
- [ ] API calls (Claude, Whisper, Replicate, YouTube) have retry logic
- [ ] Agent outputs validated before passing to FFmpeg engines
- [ ] Checkpoint/resume works for the modified step
- [ ] No new hardcoded paths (use DATA_DIR, CONFIG_DIR env vars)
- [ ] Error classification correct (FATAL vs RETRYABLE)
- [ ] No silent exception swallowing (empty catch blocks)
- [ ] Job status tracking updated for any new pipeline steps
- [ ] Frontend types match backend response shapes
- [ ] Cleanup logic exists for any new temp files

## Architecture Rules
- Pipeline steps must be idempotent (checkpoint/resume safe)
- MAX_CONCURRENT_JOBS=1 — do not add parallel job processing without queue system
- All agent outputs go through validation.py before use
- Frontend polls every 3s — keep API responses fast
