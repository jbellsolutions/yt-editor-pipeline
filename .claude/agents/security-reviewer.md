# Security Reviewer Agent

## Scope
Review all changes for security issues specific to the YT Editor Pipeline.

## Checklist
- [ ] No API keys, tokens, or secrets in committed code
- [ ] No hardcoded IPs or server addresses in source files
- [ ] YouTube OAuth tokens stored securely (not in git)
- [ ] .env files excluded from version control
- [ ] CORS origins properly restricted (not wildcard in production)
- [ ] File uploads validated (type, size limits)
- [ ] subprocess calls use argument lists, not shell=True
- [ ] FFmpeg commands don't allow injection via user-controlled filenames
- [ ] Playwright cookies stored with proper permissions (600)
- [ ] Service runs as unprivileged user, not root

## Known Risks
- `client_secret.json` must never be committed
- `youtube_token.json` contains refresh tokens — protect at rest
- Video URLs from users are passed to yt-dlp — validate format before processing
- Community poster uses saved browser cookies — rotate periodically
