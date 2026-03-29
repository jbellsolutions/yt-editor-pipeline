"""
Intake Agent — Analyzes raw video content to produce structured metadata.
"""
import json
import logging
import os

from agents.base import call_claude_json

logger = logging.getLogger(__name__)

METADATA_DIR = "/opt/yt-editor/data/metadata"
MODEL = "claude-sonnet-4-20250514"
TRANSCRIPT_MAX_CHARS = 8000

SYSTEM_PROMPT = """You are a senior video content analyst. You receive a transcript, silence/dead-air
segments, and technical video metadata. Your job is to produce a detailed structural
analysis of the video content.

Return a single JSON object with these exact keys:
- duration (float): total video duration in seconds
- topic_segments (list): each has {start, end, topic, quality (1-10), is_standalone (bool)}
  Quality measures how engaging/valuable the segment is. is_standalone means it could
  make sense as an isolated clip.
- dead_air_segments (list): each has {start, end, type} where type is one of
  "silence", "filler_heavy", "off_topic", "technical_difficulty"
- filler_words (list): each has {start, end, word} — detected filler words like
  "um", "uh", "like", "you know", "basically", "right", "so"
- content_rating (int 1-10): overall content quality rating
- key_points (list of strings): the main takeaways from the video
- suggested_text_overlays (list): each has {text, start, duration} — key points
  that should appear as on-screen text
- best_moments (list): each has {start, end, reason, hook_potential (1-10)} —
  moments that could be great Short hooks. hook_potential measures how compelling
  the moment is as an opening hook for a Short.

Be precise with timestamps. Base your analysis on the transcript timestamps provided.
Return ONLY valid JSON."""


def run(transcript_text: str, silence_segments: list, video_info: dict, job_id: str) -> dict:
    """Analyze raw video content and produce intake metadata."""
    logger.info(f"[intake] Starting analysis for job {job_id}")

    # Extract duration from video_info
    duration = 0.0
    try:
        duration = float(video_info.get("format", {}).get("duration", 0))
    except (ValueError, TypeError):
        logger.warning("[intake] Could not parse duration from video_info")

    # Truncate transcript
    truncated = transcript_text[:TRANSCRIPT_MAX_CHARS]
    if len(transcript_text) > TRANSCRIPT_MAX_CHARS:
        truncated += "\n\n[TRANSCRIPT TRUNCATED]"

    prompt = f"""Analyze this video content.

VIDEO DURATION: {duration:.1f} seconds

TRANSCRIPT:
{truncated}

SILENCE SEGMENTS:
{json.dumps(silence_segments[:50], indent=2)}

VIDEO STREAMS:
{json.dumps(video_info.get("streams", [])[:3], indent=2)}

Produce the full analysis JSON."""

    result = call_claude_json(
        prompt=prompt,
        system=SYSTEM_PROMPT,
        model=MODEL,
        max_tokens=4000,
        temperature=0.3,
    )

    # Ensure duration is set from ffprobe even if Claude guessed differently
    if duration > 0:
        result["duration"] = duration

    # Save to disk
    os.makedirs(METADATA_DIR, exist_ok=True)
    out_path = os.path.join(METADATA_DIR, f"{job_id}_intake.json")
    with open(out_path, "w") as f:
        json.dump(result, f, indent=2)
    logger.info(f"[intake] Saved intake metadata to {out_path}")

    return result
run_intake_agent = run
