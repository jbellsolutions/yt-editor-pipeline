"""
Editor Agent — Makes creative editing decisions based on intake analysis.
"""
import json
import logging
import os

from agents.base import call_claude_json

logger = logging.getLogger(__name__)

METADATA_DIR = "/opt/yt-editor/data/metadata"
MODEL = "claude-sonnet-4-20250514"
TRANSCRIPT_MAX_CHARS = 8000

SYSTEM_PROMPT = """You are a professional YouTube video editor with 10+ years of experience.
You receive an intake analysis and transcript. Your job is to make creative editing
decisions that maximize viewer retention and engagement.

Your editing philosophy:
- Cut ruthlessly: dead air, filler, repetition, and tangents must go
- Preserve flow: cuts should feel natural, not jarring
- Front-load value: the most compelling content should come early
- Maintain pacing: vary segment length to keep viewers engaged

Return a single JSON object with these exact keys:
- keep_segments (list): each has {start, end} — segments to keep, in chronological order.
  These are the INVERSE of cuts (the parts that survive editing).
- cut_segments (list): each has {start, end, reason} — what to remove and why.
  Reasons should be specific: "dead_air", "filler_heavy", "repetitive", "off_topic",
  "low_energy", "technical_issue"
- text_overlays (list): 3-5 items, each has {text, start, duration} — key point
  overlays that reinforce the most important ideas. Keep text under 8 words.
- pacing_notes (string): overall pacing assessment and recommendations (2-3 sentences)
- estimated_edited_duration (float): estimated duration after cuts in seconds

IMPORTANT: keep_segments and cut_segments should be complementary — together they
should cover the entire video duration with no gaps or overlaps.

Return ONLY valid JSON."""


def run(intake_result: dict, transcript_text: str, video_info: dict, job_id: str) -> dict:
    """Generate an edit plan based on intake analysis."""
    logger.info(f"[editor] Starting edit plan for job {job_id}")

    duration = intake_result.get("duration", 0)

    truncated = transcript_text[:TRANSCRIPT_MAX_CHARS]
    if len(transcript_text) > TRANSCRIPT_MAX_CHARS:
        truncated += "\n\n[TRANSCRIPT TRUNCATED]"

    prompt = f"""Create an edit plan for this video.

VIDEO DURATION: {duration:.1f} seconds

INTAKE ANALYSIS:
{json.dumps(intake_result, indent=2)[:4000]}

TRANSCRIPT:
{truncated}

Generate the complete edit plan JSON."""

    result = call_claude_json(
        prompt=prompt,
        system=SYSTEM_PROMPT,
        model=MODEL,
        max_tokens=4000,
        temperature=0.3,
    )

    # Save to disk
    os.makedirs(METADATA_DIR, exist_ok=True)
    out_path = os.path.join(METADATA_DIR, f"{job_id}_edit_plan.json")
    with open(out_path, "w") as f:
        json.dump(result, f, indent=2)
    logger.info(f"[editor] Saved edit plan to {out_path}")

    return result
run_editor_agent = run
