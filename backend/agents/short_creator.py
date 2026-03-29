"""
Short Creator Agent — Designs YouTube Shorts that are standalone, coherent pieces of content.

This is the most critical agent in the pipeline. Every Short must MEAN SOMETHING
on its own — a viewer who has never seen the full video must understand and
enjoy the Short without any additional context.
"""
import json
import logging
import math
import os

from agents.base import call_claude_json

logger = logging.getLogger(__name__)

METADATA_DIR = "/opt/yt-editor/data/metadata"
MODEL = "claude-sonnet-4-20250514"
TRANSCRIPT_MAX_CHARS = 8000

SYSTEM_PROMPT = """You are a YouTube Shorts specialist who designs viral short-form content.
Your Shorts are famous for being COMPLETE STORIES — not random clips.

CORE RULES (non-negotiable):
1. STANDALONE: Each Short must make COMPLETE sense to a viewer who has NEVER seen
   the full video. No references to "earlier in the video" or unexplained context.
2. HOOK FIRST: The most compelling moment (the hook) goes in the FIRST 3 SECONDS.
   If the best moment is at timestamp 35s in the original, the Short OPENS with
   that moment (seconds 35-38), then provides context (seconds 20-35).
3. ONE IDEA: Each Short develops exactly ONE coherent idea from start to finish.
   Not two ideas crammed together. Not half an idea.
4. COMPLETE ENDING: The Short must END on a complete thought. Never mid-sentence,
   never mid-point. The viewer should feel satisfied, not confused.
5. SWEET SPOT: Target 20-45 seconds. Under 20 feels rushed. Over 45 loses attention.
6. FRONT-LOAD THE HOOK: If the best moment is at second 35 of the original video,
   the Short should OPEN with seconds 35-40 as the hook, THEN show seconds 20-35
   as the context/buildup. This creates a "wait, what?" -> "oh, here's why" arc.
7. LOOP-ABILITY: The ending should feel like it flows back into the beginning.
   A viewer who watches it twice should feel the loop is natural.

NARRATIVE ARC for each Short:
- Hook (0-3s): The most compelling/surprising/intriguing moment
- Context (3-15s): Quick setup so the viewer understands
- Development (15-35s): The idea unfolds
- Payoff (last 5-10s): Complete the thought, land the point

QUALITY GATES:
- coherence_score: Rate yourself 1-10 on how well the Short holds together
- standalone_check: Would someone who ONLY sees this Short understand it? true/false
- Only include Shorts where coherence_score >= 7 AND standalone_check is true

Return a JSON object with key "shorts" containing a list.
Each Short has:
- start (float): start timestamp in original video
- end (float): end timestamp in original video
- hook_start (float): timestamp of the hook moment in original video
- hook_end (float): timestamp where the hook moment ends
- title (string): Bencivenga-style headline — specific, benefit-driven, curiosity-inducing
- hook_description (string): what makes this moment hook-worthy (1 sentence)
- narrative_arc (string): the story this Short tells (2-3 sentences)
- coherence_score (int 1-10): honest self-assessment
- standalone_check (bool): does this truly make sense alone?

IMPORTANT: Do NOT pad the list with weak Shorts. Quality over quantity.
If you can only find 3 strong Shorts in a 20-minute video, return 3."""


def run(transcript_text: str, intake_result: dict, edited_video_duration: float, job_id: str) -> list:
    """Design YouTube Shorts from the analyzed video content."""
    logger.info(f"[short_creator] Designing Shorts for job {job_id}")

    duration = intake_result.get("duration", edited_video_duration)

    # Calculate target count: ~1 per 2 minutes, min 3, max 5
    target_count = max(3, min(5, math.ceil(duration / 120)))

    truncated = transcript_text[:TRANSCRIPT_MAX_CHARS]
    if len(transcript_text) > TRANSCRIPT_MAX_CHARS:
        truncated += "\n\n[TRANSCRIPT TRUNCATED]"

    # Extract best_moments and topic_segments for the prompt
    best_moments = intake_result.get("best_moments", [])
    topic_segments = intake_result.get("topic_segments", [])

    prompt = f"""Design YouTube Shorts from this video.

VIDEO DURATION: {duration:.1f} seconds
TARGET SHORT COUNT: {target_count} (but quality over quantity — fewer is fine)

BEST MOMENTS (from intake analysis — use these as starting points for hooks):
{json.dumps(best_moments, indent=2)}

TOPIC SEGMENTS:
{json.dumps(topic_segments, indent=2)}

TRANSCRIPT:
{truncated}

Design the Shorts. Remember:
- Each Short must be a COMPLETE, STANDALONE piece
- Front-load the hook moment to the first 3 seconds
- Every Short needs a clear narrative arc
- Only include Shorts with coherence_score >= 7 AND standalone_check = true
- Target 20-45 seconds per Short

Return JSON with key "shorts" containing the list."""

    result = call_claude_json(
        prompt=prompt,
        system=SYSTEM_PROMPT,
        model=MODEL,
        max_tokens=4000,
        temperature=0.4,
    )

    # Extract the shorts list
    shorts = result.get("shorts", result if isinstance(result, list) else [])

    # Filter: only keep coherence >= 7 AND standalone_check true
    filtered = [
        s for s in shorts
        if s.get("coherence_score", 0) >= 7 and s.get("standalone_check", False)
    ]

    # If filtering removed everything, keep the best ones anyway (at least log it)
    if not filtered and shorts:
        logger.warning(
            f"[short_creator] All {len(shorts)} Shorts failed quality gates. "
            "Keeping top 3 by coherence_score."
        )
        filtered = sorted(shorts, key=lambda s: s.get("coherence_score", 0), reverse=True)[:3]

    # Save to disk
    os.makedirs(METADATA_DIR, exist_ok=True)
    out_path = os.path.join(METADATA_DIR, f"{job_id}_short_designs.json")
    with open(out_path, "w") as f:
        json.dump(filtered, f, indent=2)
    logger.info(f"[short_creator] Saved {len(filtered)} Short designs to {out_path}")

    return filtered
run_short_creator_agent = run
