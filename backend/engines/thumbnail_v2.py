"""
Multi-step compelling thumbnail pipeline (v2).

Generates genuinely compelling thumbnails through a multi-step process:
1. Concept generation via Claude (think like a YouTube thumbnail designer)
2. AI background generation via Replicate FLUX
3. FFmpeg composition with text layers for depth
4. Claude vision review for quality scoring

Each concept can be regenerated once if the review score is below threshold.
"""
import base64
import logging
import os
import subprocess
from typing import List, Optional

logger = logging.getLogger(__name__)

DATA_DIR = os.environ.get("DATA_DIR", "/opt/yt-editor/data")
THUMBNAIL_DIR = os.path.join(DATA_DIR, "thumbnails")
ENCODE_OPTS = ["-threads", "2"]
TIMEOUT = 120
MAX_ATTEMPTS_PER_CONCEPT = 2
REVIEW_PASS_THRESHOLD = 7.0


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _run(cmd: list, timeout: int = TIMEOUT) -> subprocess.CompletedProcess:
    """Run a subprocess with logging and error handling."""
    cmd_str = " ".join(str(c) for c in cmd)
    logger.info(f"Thumbnail v2 cmd: {cmd_str}")
    result = subprocess.run(
        [str(c) for c in cmd],
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    if result.returncode != 0:
        logger.error(f"Thumbnail v2 stderr: {result.stderr[:2000]}")
        raise RuntimeError(
            f"Thumbnail v2 cmd failed (exit {result.returncode}): {result.stderr[:500]}"
        )
    return result


def _ensure_dir(path: str) -> None:
    """Ensure directory for a file path exists."""
    d = os.path.dirname(path) if not os.path.isdir(path) else path
    if d:
        os.makedirs(d, exist_ok=True)


def _detect_font() -> str:
    """Find a bold system font, checking common paths."""
    candidates = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
        "/usr/share/fonts/TTF/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf",
        "/System/Library/Fonts/Helvetica.ttc",
        "/System/Library/Fonts/SFNSDisplay.ttf",
    ]
    for path in candidates:
        if os.path.exists(path):
            return path
    return ""


def _escape_text(text: str) -> str:
    """Escape special characters for FFmpeg drawtext."""
    return (
        text.replace("\\", "\\\\")
        .replace("'", "\\'")
        .replace(":", "\\:")
        .replace('"', '\\"')
        .replace("%", "%%")
    )


def _font_arg(font_path: str) -> str:
    """Return fontfile argument fragment or empty string."""
    if font_path and os.path.exists(font_path):
        return f":fontfile={font_path}"
    return ""


# ---------------------------------------------------------------------------
# Step 1: Generate concepts via Claude
# ---------------------------------------------------------------------------

def generate_concepts(
    transcript_summary: str,
    audience: str,
    goal: str,
    job_id: str,
) -> List[dict]:
    """Generate 3 compelling thumbnail concepts using Claude.

    Each concept contains:
        visual_description (str): Scene description for image generation
        headline (str): 3-5 words, ALL CAPS
        text_position (str): "left" | "right" | "center"
        emotion (str): Target emotional response
        color_mood (str): Color palette description

    Returns list of 3 concept dicts.
    """
    from agents.base import call_claude_json

    prompt = f"""You are an elite YouTube thumbnail designer who has created thumbnails
for channels with 10M+ subscribers. Your thumbnails consistently achieve 12%+ CTR.

Analyze this video and create 3 DIFFERENT compelling thumbnail concepts.

VIDEO SUMMARY:
{transcript_summary[:2000]}

TARGET AUDIENCE: {audience}
VIDEO GOAL: {goal}

For each concept, think about:
- What would make someone STOP scrolling and click?
- High contrast, bold visuals that read at small sizes
- Curiosity gaps that demand a click
- Emotional triggers (shock, curiosity, aspiration, fear of missing out)

Return a JSON object with this exact structure:
{{
    "concepts": [
        {{
            "visual_description": "Detailed scene description for AI image generation. Be specific about composition, lighting, colors, and subjects. NO TEXT in the image.",
            "headline": "3-5 WORDS ALL CAPS",
            "text_position": "left",
            "emotion": "curiosity",
            "color_mood": "dark background with vibrant orange and teal accents, dramatic lighting"
        }},
        {{
            "visual_description": "...",
            "headline": "...",
            "text_position": "right",
            "emotion": "...",
            "color_mood": "..."
        }},
        {{
            "visual_description": "...",
            "headline": "...",
            "text_position": "center",
            "emotion": "...",
            "color_mood": "..."
        }}
    ]
}}

Rules:
- Each concept must be visually DISTINCT from the others
- Headlines must be 3-5 words, ALL CAPS, curiosity-inducing
- Visual descriptions must explicitly say NO TEXT in the image
- Vary text_position across concepts
- Think bold, high-contrast, thumbnail-sized readability"""

    system = (
        "You are a world-class YouTube thumbnail designer. "
        "Return only valid JSON. No markdown, no explanation."
    )

    result = call_claude_json(prompt, system, max_tokens=2000, temperature=0.7)
    concepts = result.get("concepts", [])

    if len(concepts) < 3:
        logger.warning(
            f"generate_concepts returned {len(concepts)} concepts, expected 3"
        )

    logger.info(
        f"[{job_id}] Generated {len(concepts)} thumbnail concepts"
    )
    return concepts[:3]


# ---------------------------------------------------------------------------
# Step 2: Generate AI background via Replicate FLUX
# ---------------------------------------------------------------------------

def generate_background(concept: dict, job_id: str, index: int) -> Optional[str]:
    """Generate a background image using Replicate FLUX-schnell.

    Builds a specific prompt from concept visual_description + color_mood.
    Downloads result to DATA_DIR/thumbnails/{job_id}_concept_{i}_bg.png.

    Returns path to the downloaded image, or None on failure.
    """
    try:
        import replicate
        import httpx

        token = os.environ.get("REPLICATE_API_TOKEN")
        if not token:
            logger.warning("REPLICATE_API_TOKEN not set, cannot generate background")
            return None

        visual = concept.get("visual_description", "")
        color_mood = concept.get("color_mood", "")

        prompt = (
            f"Stunning YouTube thumbnail background image, ultra high quality, 4K. "
            f"{visual[:500]} "
            f"Color mood: {color_mood[:200]}. "
            f"ABSOLUTELY NO TEXT. NO words. NO letters. NO numbers. NO writing. "
            f"Strong visual hierarchy. Bold composition. "
            f"16:9 aspect ratio. Photorealistic. Professional studio quality."
        )

        output = replicate.run(
            "black-forest-labs/flux-schnell",
            input={
                "prompt": prompt,
                "num_outputs": 1,
                "aspect_ratio": "16:9",
                "output_format": "png",
            },
        )

        if not output or len(output) == 0:
            logger.error(f"[{job_id}] FLUX returned empty output for concept {index}")
            return None

        img_url = str(output[0])
        _ensure_dir(THUMBNAIL_DIR)
        out_path = os.path.join(
            THUMBNAIL_DIR, f"{job_id}_concept_{index}_bg.png"
        )

        resp = httpx.get(img_url, timeout=60)
        resp.raise_for_status()
        with open(out_path, "wb") as f:
            f.write(resp.content)

        logger.info(f"[{job_id}] Background generated: {out_path}")
        return out_path

    except ImportError:
        logger.warning("replicate or httpx not installed, skipping background generation")
        return None
    except Exception as e:
        logger.error(f"[{job_id}] Background generation failed for concept {index}: {e}")
        return None


# ---------------------------------------------------------------------------
# Step 3: Compose thumbnail with FFmpeg overlays
# ---------------------------------------------------------------------------

def compose_thumbnail(
    bg_path: str,
    concept: dict,
    job_id: str,
    index: int,
) -> Optional[str]:
    """Compose final thumbnail: background + multi-layer text + color grading.

    Layers:
        1. Shadow text (offset 4px, black@0.6) for depth
        2. Main text (white, fontsize 96, borderw 6)
    Position based on concept.text_position.
    Color grading: contrast 1.15, saturation 1.3.

    Output: 1280x720 PNG at DATA_DIR/thumbnails/{job_id}_concept_{i}_final.png
    Returns path to final thumbnail or None on failure.
    """
    try:
        font_path = _detect_font()
        fa = _font_arg(font_path)

        headline = _escape_text(concept.get("headline", "WATCH NOW"))
        text_position = concept.get("text_position", "left")

        # Determine x position based on text_position
        position_map = {
            "left": ("50", "54"),
            "right": ("w-text_w-50", "w-text_w-46"),
            "center": ("(w-text_w)/2", "(w-text_w)/2+4"),
        }
        main_x, shadow_x = position_map.get(text_position, position_map["left"])
        main_y = "(h-text_h)/2"
        shadow_y = "(h-text_h)/2+4"

        _ensure_dir(THUMBNAIL_DIR)
        output_path = os.path.join(
            THUMBNAIL_DIR, f"{job_id}_concept_{index}_final.png"
        )

        vf_parts = [
            # Scale and pad to exact 1280x720
            "scale=1280:720:force_original_aspect_ratio=decrease",
            "pad=1280:720:(ow-iw)/2:(oh-ih)/2",
            # Color grading
            "eq=contrast=1.15:saturation=1.3",
            # Layer 1: Shadow text for depth
            (
                f"drawtext=text='{headline}'"
                f"{fa}"
                f":fontsize=96:fontcolor=black@0.6"
                f":x={shadow_x}:y={shadow_y}"
            ),
            # Layer 2: Main headline text
            (
                f"drawtext=text='{headline}'"
                f"{fa}"
                f":fontsize=96:fontcolor=white"
                f":borderw=6:bordercolor=black"
                f":x={main_x}:y={main_y}"
            ),
        ]
        vf = ",".join(vf_parts)

        _run([
            "ffmpeg", "-y",
            "-i", bg_path,
            "-vf", vf,
            *ENCODE_OPTS,
            output_path,
        ])

        if not os.path.exists(output_path) or os.path.getsize(output_path) < 1000:
            logger.error(f"[{job_id}] Compose produced invalid output for concept {index}")
            return None

        logger.info(f"[{job_id}] Thumbnail composed: {output_path}")
        return output_path

    except Exception as e:
        logger.error(f"[{job_id}] Thumbnail composition failed for concept {index}: {e}")
        return None


# ---------------------------------------------------------------------------
# Step 4: Review thumbnail with Claude vision
# ---------------------------------------------------------------------------

def review_thumbnail(thumbnail_path: str) -> dict:
    """Review a thumbnail using Claude with vision (base64 image).

    Rates on 4 criteria (1-10 each):
        - contrast: Visual contrast and readability at small sizes
        - text_readability: Can headline be read instantly?
        - click_worthiness: Would this make someone click?
        - emotional_impact: Does it trigger curiosity/emotion?

    Returns:
        {
            "score": float (average of 4 criteria),
            "feedback": str (brief improvement suggestions),
            "pass": bool (score >= 7.0),
            "scores": {"contrast": ..., "text_readability": ..., ...}
        }
    """
    try:
        import anthropic

        if not os.path.exists(thumbnail_path):
            logger.error(f"review_thumbnail: file not found: {thumbnail_path}")
            return {"score": 0.0, "feedback": "File not found", "pass": False}

        # Read and encode image as base64
        with open(thumbnail_path, "rb") as f:
            image_data = base64.b64encode(f.read()).decode("utf-8")

        # Determine media type
        ext = os.path.splitext(thumbnail_path)[1].lower()
        media_type = "image/png" if ext == ".png" else "image/jpeg"

        client = anthropic.Anthropic()
        response = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=800,
            temperature=0.2,
            system=(
                "You are a YouTube thumbnail expert who reviews thumbnails for "
                "maximum click-through rate. Return only valid JSON."
            ),
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": media_type,
                                "data": image_data,
                            },
                        },
                        {
                            "type": "text",
                            "text": """Rate this YouTube thumbnail on 4 criteria (1-10 each):

1. contrast: Visual contrast, color pop, readability at 160x90px thumbnail size
2. text_readability: Can the headline be read instantly without squinting?
3. click_worthiness: Would this make someone stop scrolling and click?
4. emotional_impact: Does it trigger curiosity, shock, FOMO, or aspiration?

Return JSON:
{
    "contrast": <int 1-10>,
    "text_readability": <int 1-10>,
    "click_worthiness": <int 1-10>,
    "emotional_impact": <int 1-10>,
    "feedback": "<2-3 sentences of specific improvement suggestions>"
}""",
                        },
                    ],
                }
            ],
        )

        import json
        import re

        raw = response.content[0].text.strip()
        # Strip markdown code blocks if present
        pattern = r"```(?:json)?\s*\n?(.*?)\n?\s*```"
        match = re.search(pattern, raw, re.DOTALL)
        if match:
            raw = match.group(1).strip()

        data = json.loads(raw)

        scores = {
            "contrast": int(data.get("contrast", 5)),
            "text_readability": int(data.get("text_readability", 5)),
            "click_worthiness": int(data.get("click_worthiness", 5)),
            "emotional_impact": int(data.get("emotional_impact", 5)),
        }
        avg_score = sum(scores.values()) / len(scores)
        feedback = data.get("feedback", "No specific feedback provided.")

        result = {
            "score": round(avg_score, 1),
            "feedback": feedback,
            "pass": avg_score >= REVIEW_PASS_THRESHOLD,
            "scores": scores,
        }

        logger.info(
            f"Thumbnail review: score={result['score']}, "
            f"pass={result['pass']}, feedback={feedback[:100]}"
        )
        return result

    except Exception as e:
        logger.error(f"review_thumbnail failed: {e}")
        # Default to pass on review failure so pipeline continues
        return {
            "score": 7.0,
            "feedback": f"Review failed ({e}), defaulting to pass",
            "pass": True,
            "scores": {},
        }


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------

def generate_compelling_thumbnails(
    video_path: str,
    transcript_summary: str,
    audience: str,
    goal: str,
    job_id: str,
    count: int = 3,
) -> list:
    """Generate count compelling thumbnails through multi-step pipeline.

    Pipeline per concept:
        1. Generate concepts via Claude
        2. Generate AI background via FLUX
        3. Compose thumbnail (text + color grading)
        4. Review via Claude vision — if score < 7, regenerate once

    Returns list of paths to final thumbnails, sorted by review score
    (highest first).
    """
    _ensure_dir(THUMBNAIL_DIR)

    # Step 1: Generate concepts
    try:
        concepts = generate_concepts(transcript_summary, audience, goal, job_id)
    except Exception as e:
        logger.error(f"[{job_id}] Concept generation failed: {e}")
        return []

    if not concepts:
        logger.error(f"[{job_id}] No concepts generated")
        return []

    # Ensure we have the requested count
    while len(concepts) < count:
        concepts.append(concepts[-1])
    concepts = concepts[:count]

    results = []  # list of (path, score)

    for i, concept in enumerate(concepts):
        best_path = None
        best_score = 0.0

        for attempt in range(MAX_ATTEMPTS_PER_CONCEPT):
            attempt_label = f"concept {i}, attempt {attempt + 1}"
            logger.info(f"[{job_id}] Processing {attempt_label}")

            # Step 2: Generate background
            bg_path = generate_background(concept, job_id, i)
            if not bg_path:
                logger.warning(f"[{job_id}] No background for {attempt_label}")
                break

            # Step 3: Compose thumbnail
            thumb_path = compose_thumbnail(bg_path, concept, job_id, i)

            # Clean up background
            try:
                if bg_path and os.path.exists(bg_path):
                    os.remove(bg_path)
            except OSError:
                pass

            if not thumb_path:
                logger.warning(f"[{job_id}] Composition failed for {attempt_label}")
                break

            # Step 4: Review
            review = review_thumbnail(thumb_path)
            score = review.get("score", 0.0)

            if score > best_score:
                # Remove previous best if it exists and is different
                if best_path and best_path != thumb_path and os.path.exists(best_path):
                    try:
                        os.remove(best_path)
                    except OSError:
                        pass
                best_path = thumb_path
                best_score = score

            if review.get("pass", False):
                logger.info(
                    f"[{job_id}] {attempt_label} PASSED review "
                    f"(score={score})"
                )
                break

            # Failed review — adjust concept prompt for retry
            logger.info(
                f"[{job_id}] {attempt_label} FAILED review "
                f"(score={score}): {review.get('feedback', '')}"
            )
            if attempt < MAX_ATTEMPTS_PER_CONCEPT - 1:
                # Boost the concept description for retry
                feedback = review.get("feedback", "")
                concept = dict(concept)
                concept["visual_description"] = (
                    f"{concept.get('visual_description', '')} "
                    f"IMPORTANT IMPROVEMENTS NEEDED: {feedback} "
                    f"Make it bolder, higher contrast, more eye-catching."
                )
                concept["color_mood"] = (
                    f"{concept.get('color_mood', '')}; "
                    f"increase contrast and visual impact dramatically"
                )

        if best_path:
            results.append((best_path, best_score))

    # Sort by score descending
    results.sort(key=lambda x: x[1], reverse=True)

    final_paths = [path for path, _ in results]
    logger.info(
        f"[{job_id}] Thumbnail pipeline complete: "
        f"{len(final_paths)}/{count} thumbnails generated"
    )
    return final_paths
