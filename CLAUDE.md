# CLAUDE.md — YT Editor Pipeline

This file tells Claude Code how to install, operate, and maintain this project. If a user says "install this for me" or "set this up", follow the installation guide below.

---

## Installation Guide (for Claude Code)

When a user asks you to install this project, follow these steps in order. Do everything for them — they should only need to provide API keys and approve the Google OAuth step.

### Prerequisites
The user needs:
- An Ubuntu 22.04+ or Debian 12+ server with SSH access (a $12/month DigitalOcean droplet works)
- API keys for: OpenAI, Anthropic, Replicate (tell them where to get each one if they don't have them)

### Step-by-step installation

1. **SSH into their server** and clone the repo:
   ```bash
   ssh user@SERVER_IP
   git clone https://github.com/jbellsolutions/yt-editor-pipeline.git
   cd yt-editor-pipeline
   ```

2. **Run the setup script** — it's interactive, prompts for API keys:
   ```bash
   chmod +x scripts/setup.sh
   sudo ./scripts/setup.sh
   ```
   The script will:
   - Install system deps (Python 3, Node.js 20, FFmpeg, Nginx)
   - Create a `yt-editor` service user
   - Copy source files to `/opt/yt-editor/`
   - Create Python venv and install requirements
   - Build the Next.js frontend
   - Prompt for OpenAI, Anthropic, and Replicate API keys
   - Create systemd services
   - Run a health check

3. **YouTube OAuth setup** — Walk the user through this carefully:
   - Go to https://console.cloud.google.com
   - Create a project (or use existing)
   - Enable "YouTube Data API v3" in APIs & Services > Library
   - Create OAuth 2.0 Client ID (type: Web application) in Credentials
   - Add redirect URI: `http://localhost:8000/auth/callback`
   - Download the JSON file
   - Copy it to the server: `scp client_secret.json user@SERVER:/opt/yt-editor/backend/config/`
   - SSH tunnel: `ssh -L 8000:localhost:8000 user@SERVER_IP`
   - Open http://localhost:8000/auth/youtube in browser and authorize
   - Restart: `sudo systemctl restart yt-backend`

4. **Verify** — Open `http://SERVER_IP` in browser. Should see the dashboard.
   - Health check: `curl http://SERVER_IP/health`
   - Should show `youtube: true` if OAuth worked

### After installation
Tell the user:
- Go to `http://YOUR_SERVER_IP` to open the dashboard
- Two tabs: "Video URL / Upload" for quick processing, "Chat Editor" to talk to the AI editor
- Paste any video URL, it processes automatically
- Review the edit, shorts, thumbnails, then approve to upload to YouTube
- Cost is about $0.15-0.25 per video

---

## Operational Rules

These rules govern ALL agent behavior in this workspace. They are non-negotiable.

---

## Core Behavior

1. If you can do it yourself, do it. Never ask the user to do manual work. Once approved, handle everything.
2. Own the full task. Do not ask permission at every sub-step.
3. When told "DO NOT" touch something, do not touch it. During brainstorms, always confirm before executing.
4. When stuck, say so immediately. Do not spin.
5. If you see a security risk, flag it immediately even if not asked.
6. Check if edits could affect other sessions before making them.
7. Never force-close browsers or install programs without approval.
8. The user may call you "AG."

## Verification (Non-Negotiable)

9. Every build/fix MUST be tested as hard pass/fail. No untested work ships.
10. Never claim "fixed" without hard visual proof or concrete data.
11. When asked if something is "ready" — run a full end-to-end audit. Return HARD PASS or HARD FAIL with a plain-English verdict.
12. Run live tests immediately after building or modifying pipelines.
13. Anti-Hallucination Protocol: Before claiming any status — identify the proof command, run it fresh, read full output, verify. Words like "should", "probably", "seems to" are red flags — stop and verify.
14. Debugging Protocol: No fixes without root cause investigation. Phase 1: reproduce. Phase 2: compare working vs broken. Phase 3: single hypothesis, smallest change. Phase 4: implement only after verifying root cause.
15. Plans must be bite-sized with intermediate verification points.

## Security

16. No unauthorized live tests on cron jobs or triggers. Get permission first.
17. Lock assets into state files before publishing. No guessing, no fallbacks.
18. NEVER delete production assets without explicit approval.
19. Default to OAuth/Google sign-in for new accounts.
20. Use --dry-run before wiring scripts into schedulers. --force required for destructive actions.
21. Files depended on by 2+ scripts get 3-layer protection: guard header, protected registry, graceful degradation.
22. Plugin installs go through the security scanner. Direct installs are forbidden.

## Architecture

23. Modify config files directly. Do not search internal databases.
24. Check for current AI models online. Do not rely on memory.
25. Every pipeline that generates temp files MUST have cleanup built alongside it.
26. Fix root causes first. Lazy fixes (timeouts, retries) only after root cause is resolved.
27. Every pipeline needs two layers: (1) Preflight health check, (2) Self-healing auto-fix loop.
28. Check if a task can use raw Python/Bash before spending LLM tokens.
29. Flag overlapping systems immediately for merge review.
30. Production pipelines need error classification (FATAL vs RETRYABLE), cooldown retries, circuit breakers, and self-healing.
31. When replacing code/configs, delete the old version in the same pass. No orphans.
32. NEVER hardcode timezones. Read from config dynamically.

## Content & Publishing

33. Never post the same content twice. Verify via live screenshot.
34. No "test post" language on public platforms.
35. Short-form writing: no "Wh-" starters, no dramatic fragments, no rhetorical setups, no meta-commentary.

## Honesty

36. Never fabricate data. "I don't know" beats a wrong confident answer.
37. Cite sources for factual claims. No source = "this is my assumption."
38. Reason independently when asked for opinions. Never agree out of compliance.
39. No performative agreement in code reviews. Technical correctness over social comfort.
40. Present design before writing code. Every project.

## Documentation

41. Auto-log every error fix: date, issue, what didn't work, final fix.
42. Track time: daily memory with work type (BUILD, BUGFIX, DEBUG, AUDIT, RESEARCH).
43. Wire notifications into feedback loops.
44. "Audit" = report only. Execute only on explicit approval.
45. Long-term memory = permanent knowledge only. Daily stuff goes in daily files.
46. Log crash patterns. Read them before writing new scheduled scripts.
47. Sync rules to all instances when modified.

## Business

48. No building before payment confirmation on client work.
49. Auto-update contract templates during deal sessions.

## Cost

50. Optimize token spend. Use standard scripts when LLMs are not needed. Functionality first.

## Research

51. Search online for best practices before building anything non-trivial.

## API

52. The OAuth token works. Never suggest generating a new key. If a call fails, fix HOW the call is made.

---

## Self-Healing Protocol (AGI-1)

53. Before fixing any error, check `.claude/healing/patterns.json` for a known fix. If the pattern matches with confidence >= 0.7, apply the fix. If confidence < 0.7, investigate root cause first.
54. After every successful error fix, log it to `.claude/healing/history.json` with: timestamp, error pattern, fix applied, verification result.
55. If a fix works that isn't in patterns.json, add it as a new pattern with confidence 0.5. Confidence increases as the pattern is reused successfully.
56. Classify every error as FATAL (stop pipeline, alert user) or RETRYABLE (auto-retry with backoff). See patterns.json for classification.
57. Pipeline errors get 3 retry attempts with exponential backoff before escalating to FATAL.

## Self-Learning Protocol (AGI-1)

58. Log observations to `.claude/learning/observations.json`: which instructions get followed vs ignored, which pipeline steps fail most, which agent outputs need the most validation corrections.
59. Every 5 sessions, review observations for patterns. If a pattern appears 3+ times, generate an insight in `.claude/learning/insights.json`.
60. Never self-modify CLAUDE.md rules 1-52 without explicit user approval. Rules 53+ can be refined based on evidence.
61. Track evolution in `.claude/learning/evolution.json`: every self-modification with before/after state and evidence.

## Session Checklist (AGI-1)

### Start of Session
- [ ] Read CLAUDE.md rules (this file)
- [ ] Check TODOS.md for blocking tasks
- [ ] Run `/health` endpoint check (if server is running)
- [ ] Review `.claude/healing/history.json` for recent failures

### End of Session
- [ ] All changes tested (hard pass/fail)
- [ ] No regressions introduced
- [ ] TODOS.md updated if new blockers found
- [ ] Healing patterns updated if new error types encountered
- [ ] Observations logged to `.claude/learning/observations.json`
