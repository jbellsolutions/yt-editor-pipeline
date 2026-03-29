"""
Packager Agent — Generates SEO metadata using direct response copywriting frameworks.

Frameworks:
- Bencivenga: Headlines that are specific, benefit-driven, and curiosity-inducing
- Schwartz: Awareness levels (unaware -> most aware) to calibrate messaging
- Hormozi: Value equation (Dream Outcome x Perceived Likelihood) / (Time x Effort)
"""
import json
import logging
import os

from agents.base import call_claude_json

logger = logging.getLogger(__name__)

METADATA_DIR = "/opt/yt-editor/data/metadata"
MODEL = "claude-sonnet-4-20250514"
TRANSCRIPT_MAX_CHARS = 8000

SYSTEM_PROMPT = """You are a world-class YouTube SEO and copywriting specialist who combines
three legendary direct response frameworks:

1. BENCIVENGA (Headlines):
   - Every headline must be specific, not vague
   - Lead with the benefit, not the feature
   - Create a curiosity gap — the reader MUST click to resolve it
   - Use concrete numbers and timeframes when possible

2. SCHWARTZ (Awareness Levels):
   - Unaware: Doesn't know they have a problem
   - Problem-aware: Knows the problem, not the solution
   - Solution-aware: Knows solutions exist, not yours
   - Product-aware: Knows your channel, needs convincing
   - Most aware: Fan, just needs a reason to click
   Calibrate ALL copy to the likely awareness level of the target audience.

3. HORMOZI (Value Equation):
   Dream Outcome x Perceived Likelihood of Achievement
   ÷ Time Delay x Effort & Sacrifice
   Maximize the numerator, minimize the denominator in all copy.

Return a single JSON object with these exact keys:

- long_form (object):
  - title_variants (list of 3 strings): A/B test options, each using a different
    Bencivenga angle
  - title (string): the primary title (your #1 pick from variants)
  - description (string): YouTube description with timestamps, value props, and CTA.
    First 2 lines are critical (shown before "Show More").
  - tags (list of strings): 15-20 relevant tags mixing broad and specific
  - awareness_level (string): the target audience awareness level
  - thumbnail_text_options (list of 3 strings): 3-5 word phrases for thumbnail overlay.
    Must be readable at small size. High contrast. Emotional trigger.
  - thumbnail_headlines (list of 3 strings): Bold 2-4 word HEADLINES for AI-generated
    thumbnails. These go on eye-catching images, not frame shots. Think YouTube
    clickbait that delivers: "GAME CHANGER", "I Was Wrong", "The $0 Strategy".
    Must be ALL CAPS, punchy, create urgency or curiosity.

- shorts (list): one per short_design provided, each has:
  - title (string): UNIQUE title specific to THIS Short's content. Do NOT reuse
    the long-form title. Use the Short's hook_description and narrative_arc to
    craft a title that stands alone.
  - description (string): Short-specific description with relevant hashtags
  - tags (list of strings): 5-8 tags specific to this Short's content
  - thumbnail_text (string): 3-5 words for thumbnail overlay

- community_posts (list of 3 objects): each has:
  - text (string): the post content (keep under 300 chars)
  - type (string): one of "teaser", "question", "bold_claim"

IMPORTANT: Each Short's title and description must be UNIQUE and specific to that
Short's content. Generic titles that could apply to any Short are unacceptable.

Return ONLY valid JSON."""


def run(transcript_text: str, intake_result: dict, short_designs: list, job_id: str, extras: dict = None) -> dict:
    """Generate SEO metadata and copy for all content pieces."""
    logger.info(f"[packager] Generating package for job {job_id}")
    extras = extras or {}

    truncated = transcript_text[:TRANSCRIPT_MAX_CHARS]
    if len(transcript_text) > TRANSCRIPT_MAX_CHARS:
        truncated += "\n\n[TRANSCRIPT TRUNCATED]"

    # Build extras context for Claude
    extras_context = ""
    description_template = extras.get("description_template", "")
    custom_description = extras.get("custom_description", "")
    instructions = extras.get("instructions", "")

    if custom_description:
        extras_context += f"\n\nCUSTOM DESCRIPTION FROM CREATOR — Use this as the primary description body for the long-form video (you can enhance it but keep the core message):\n{custom_description}"
    if description_template:
        extras_context += f"\n\nDESCRIPTION TEMPLATE — Append this to the END of every description (long-form and shorts):\n{description_template}"
    if instructions:
        extras_context += f"\n\nSPECIAL INSTRUCTIONS FROM CREATOR:\n{instructions}"

    # Note: Shorts will automatically get a "Watch the full video" link injected
    # at upload time using the actual YouTube video ID — no need to generate placeholder links

    prompt = f"""Generate complete SEO metadata for this video and its Shorts.

INTAKE ANALYSIS (key points and content rating):
{json.dumps({k: intake_result.get(k) for k in ["key_points", "content_rating", "topic_segments", "duration"]}, indent=2)[:3000]}

SHORT DESIGNS ({len(short_designs)} Shorts):
{json.dumps(short_designs, indent=2)[:3000]}

TRANSCRIPT:
{truncated}
{extras_context}

Generate the complete package JSON. Remember:
- Each Short gets a UNIQUE title based on its specific content
- Titles use Bencivenga principles (specific, benefit-driven, curiosity gap)
- Description calibrated to the audience awareness level
- Thumbnail text must be 3-5 words, high impact, readable at small size
- Community posts should drive engagement (teaser, question, bold_claim)
- If a description template was provided, append it to ALL descriptions
- If a channel handle was provided, every Short description must link back to the full video"""

    result = call_claude_json(
        prompt=prompt,
        system=SYSTEM_PROMPT,
        model=MODEL,
        max_tokens=4000,
        temperature=0.4,
    )

    # Save to disk
    os.makedirs(METADATA_DIR, exist_ok=True)
    out_path = os.path.join(METADATA_DIR, f"{job_id}_package.json")
    with open(out_path, "w") as f:
        json.dump(result, f, indent=2)
    logger.info(f"[packager] Saved package to {out_path}")

    return result
run_packager_agent = run
