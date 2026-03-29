# CLAUDE.md — YT Editor Pipeline

This file tells Claude Code how to install, operate, and maintain this project.

---

## Installation Guide (for Claude Code)

When a user asks you to install this project (or says anything like "set this up", "install this for me", "help me get this running"), have a natural conversation with them. Don't dump technical instructions. Walk them through it like a friend helping them set up a new app.

### The Conversation Flow

**1. Start by asking about their setup:**

Say something like:
> "Hey! Let's get your YouTube editor set up. Quick question — are you on a Mac, Windows, or Linux? And do you want to run this on your own computer, or on a server that runs 24/7?"

**If they're not sure, explain the difference:**
> "Running it on your computer is free and works great — but it only runs when your computer is on. A cloud server runs 24/7 so you can submit videos anytime. A basic DigitalOcean server is $4-6/month. I'd recommend the server if you're going to use this regularly, but either way works."

**2. Based on their answer, pick the right path:**

#### PATH A: Local computer (Mac)
- Detect they're on Mac (check `uname` or ask)
- Install Homebrew if missing: `/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"`
- Install deps: `brew install python@3.12 node ffmpeg`
- Clone the repo to a local folder
- Create Python venv, install requirements
- Install frontend deps, build
- Create `.env` file with their API keys
- Start backend: `cd backend && source venv/bin/activate && uvicorn main:app --host 127.0.0.1 --port 8000`
- Start frontend: `cd frontend && npm start`
- Dashboard at http://localhost:3000
- Tell them: "You'll need to start these two commands each time you want to use it, or I can create a start script for you."

#### PATH B: Local computer (Windows)
- They'll need WSL2 (Windows Subsystem for Linux). Walk them through enabling it:
  - Open PowerShell as admin: `wsl --install`
  - Restart computer
  - Open Ubuntu from Start menu
- Once in WSL2, follow the Linux/server path below (but local, no SSH needed)
- Dashboard at http://localhost:3000

#### PATH C: Local computer (Linux)
- Same as server path below but install locally, no SSH needed
- Skip nginx and systemd — just run directly
- Dashboard at http://localhost:3000

#### PATH D: Cloud server (recommended for regular use)
- Ask: "Do you already have a server, or should we set one up?"
- If they need one: "Go to digitalocean.com, create an account, and spin up a Droplet — pick Ubuntu 24.04, the $6/month plan (1GB RAM is enough). Once it's ready, give me the IP address and your SSH key or password."
- Once they have a server IP:
  - SSH in and run `scripts/setup.sh` which handles everything
  - Dashboard at http://SERVER_IP

**3. API Keys — walk them through each one:**

Say: "We need three API keys. I'll walk you through getting each one — takes about 5 minutes total."

For each key, tell them exactly where to go and what to click:

- **OpenAI** (for transcription): "Go to platform.openai.com, sign in or create account, click API Keys in the left sidebar, click 'Create new secret key', copy it and paste it here."
- **Anthropic** (for the AI editor): "Go to console.anthropic.com, sign in or create account, go to API Keys, create one, paste it here."
- **Replicate** (for thumbnails): "Go to replicate.com, sign in, click your profile icon top-right, click API Tokens, create one, paste it here."

If they ask about cost: "OpenAI and Anthropic charge per use — maybe $5-10/month if you're doing a few videos a week. Replicate is a few cents per thumbnail. Total cost per video is about $0.15-0.25."

**4. YouTube connection — this is the hardest part, go slow:**

Say: "Last step — we need to connect your YouTube channel so the editor can upload videos for you. This part takes about 10 minutes and you'll need to do some clicking in Google Cloud. I'll walk you through every step."

Then walk them through:
1. Go to console.cloud.google.com and sign in with the Google account that owns the YouTube channel
2. Click "Select a project" at the top, then "New Project", name it "YT Editor", click Create
3. In the left sidebar, go to "APIs & Services" then "Library"
4. Search for "YouTube Data API v3" and click Enable
5. Go to "APIs & Services" then "Credentials"
6. Click "Create Credentials" then "OAuth 2.0 Client ID"
7. If asked to configure consent screen: pick External, fill in app name "YT Editor", add your email, save
8. For Application Type pick "Web application"
9. Under "Authorized redirect URIs" add: `http://localhost:8000/auth/callback`
10. Click Create, then click the download icon to download the JSON file
11. Tell them where to put the file (depends on local vs server install)

For server installs, set up SSH tunnel: `ssh -L 8000:localhost:8000 user@SERVER_IP`

Then have them visit http://localhost:8000/auth/youtube in their browser and authorize.

**5. Verify and celebrate:**

Run the health check. If it passes, say something like:
> "You're all set! Open [dashboard URL] in your browser. You've got two tabs — paste a video URL in the first one to process it automatically, or use the Chat Editor tab to talk to the AI about how you want your video edited. Your first video will take a few minutes to process. Have fun!"

### Technical Details (for the install scripts)

**Local Mac install commands:**
```bash
brew install python@3.12 node@20 ffmpeg
git clone https://github.com/jbellsolutions/yt-editor-pipeline.git
cd yt-editor-pipeline/backend
python3 -m venv venv && source venv/bin/activate && pip install -r requirements.txt
cd ../frontend && npm install && npm run build
```

**Local start script (create as `start.sh` in repo root):**
```bash
#!/bin/bash
cd "$(dirname "$0")"
echo "Starting YT Editor Pipeline..."
cd backend && source venv/bin/activate
uvicorn main:app --host 127.0.0.1 --port 8000 &
BACKEND_PID=$!
cd ../frontend && npm start &
FRONTEND_PID=$!
echo "Dashboard: http://localhost:3000"
echo "Press Ctrl+C to stop"
trap "kill $BACKEND_PID $FRONTEND_PID 2>/dev/null" EXIT
wait
```

**Server install:** Use `scripts/setup.sh` (interactive installer with all deps, systemd services, nginx).

**Windows WSL2 install:** After WSL2 is enabled, same as server install inside the Ubuntu terminal.

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
