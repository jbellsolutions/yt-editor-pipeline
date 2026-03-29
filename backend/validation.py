"""
Runtime validation schemas for agent outputs.
Validates that AI agents return well-formed data before it reaches FFmpeg or YouTube.
"""
import logging
from typing import Any

logger = logging.getLogger(__name__)


class ValidationError(Exception):
    """Raised when agent output doesn't match expected schema."""
    pass


def validate_intake_result(data: Any) -> dict:
    """Validate intake agent output."""
    if not isinstance(data, dict):
        raise ValidationError(f"Intake result must be dict, got {type(data).__name__}")

    # Must have at least these keys
    required = ["content_rating"]
    for key in required:
        if key not in data:
            raise ValidationError(f"Intake result missing required key: {key}")

    # content_rating should be numeric
    rating = data.get("content_rating")
    if not isinstance(rating, (int, float)):
        logger.warning(f"Intake content_rating not numeric: {rating}, defaulting to 5")
        data["content_rating"] = 5

    # filler_words should be a list
    if "filler_words" in data and not isinstance(data["filler_words"], list):
        data["filler_words"] = []

    return data


def validate_edit_plan(data: Any) -> dict:
    """Validate editor agent output."""
    if not isinstance(data, dict):
        raise ValidationError(f"Edit plan must be dict, got {type(data).__name__}")

    # cut_segments: each must have start < end
    for i, seg in enumerate(data.get("cut_segments", [])):
        if not isinstance(seg, dict):
            raise ValidationError(f"cut_segment[{i}] must be dict")
        start = seg.get("start", 0)
        end = seg.get("end", 0)
        if not isinstance(start, (int, float)) or not isinstance(end, (int, float)):
            raise ValidationError(f"cut_segment[{i}] start/end must be numeric")
        if start >= end:
            raise ValidationError(f"cut_segment[{i}] start ({start}) >= end ({end})")
        if start < 0:
            raise ValidationError(f"cut_segment[{i}] start ({start}) is negative")

    # Detect overlapping cut_segments (would corrupt FFmpeg output)
    segments = sorted(
        [(s.get("start", 0), s.get("end", 0)) for s in data.get("cut_segments", [])],
        key=lambda x: x[0],
    )
    for i in range(1, len(segments)):
        if segments[i][0] < segments[i - 1][1]:
            logger.warning(
                f"Overlapping cut_segments detected: segment ending at {segments[i-1][1]} "
                f"overlaps with segment starting at {segments[i][0]}. Merging."
            )
            # Merge overlapping segments in the original data
            merged = []
            for seg in sorted(data["cut_segments"], key=lambda s: s.get("start", 0)):
                if merged and seg.get("start", 0) < merged[-1]["end"]:
                    merged[-1]["end"] = max(merged[-1]["end"], seg.get("end", 0))
                else:
                    merged.append(dict(seg))
            data["cut_segments"] = merged
            break

    # text_overlays: each must have text, start, end
    for i, overlay in enumerate(data.get("text_overlays", [])):
        if not isinstance(overlay, dict):
            raise ValidationError(f"text_overlay[{i}] must be dict")
        if "text" not in overlay:
            raise ValidationError(f"text_overlay[{i}] missing 'text'")

    return data


def validate_short_designs(data: Any) -> list:
    """Validate short creator agent output."""
    if not isinstance(data, list):
        raise ValidationError(f"Short designs must be list, got {type(data).__name__}")

    for i, design in enumerate(data):
        if not isinstance(design, dict):
            raise ValidationError(f"short_design[{i}] must be dict")

        # Must have start, end, title
        for key in ["start", "end"]:
            if key not in design:
                raise ValidationError(f"short_design[{i}] missing '{key}'")
            if not isinstance(design[key], (int, float)):
                raise ValidationError(f"short_design[{i}].{key} must be numeric")

        start = design["start"]
        end = design["end"]
        if start >= end:
            raise ValidationError(f"short_design[{i}] start ({start}) >= end ({end})")

        duration = end - start
        if duration < 5:
            logger.warning(f"short_design[{i}] very short ({duration}s)")
        if duration > 90:
            logger.warning(f"short_design[{i}] exceeds 60s max ({duration}s)")

    return data


def validate_package_result(data: Any) -> dict:
    """Validate packager agent output."""
    if not isinstance(data, dict):
        raise ValidationError(f"Package result must be dict, got {type(data).__name__}")

    # Must have long_form with at least a title
    long_form = data.get("long_form", {})
    if not isinstance(long_form, dict):
        raise ValidationError("Package long_form must be dict")

    # Should have title or title_variants
    has_title = bool(long_form.get("title")) or bool(long_form.get("title_variants"))
    if not has_title:
        logger.warning("Package result has no title or title_variants")

    # shorts should be a list
    shorts = data.get("shorts", [])
    if not isinstance(shorts, list):
        data["shorts"] = []

    # community_posts should be a list
    posts = data.get("community_posts", [])
    if not isinstance(posts, list):
        data["community_posts"] = []

    return data


def validate_qa_result(data: Any) -> dict:
    """Validate QA agent output."""
    if not isinstance(data, dict):
        raise ValidationError(f"QA result must be dict, got {type(data).__name__}")

    # Should have verdict or passed
    has_verdict = "verdict" in data or "passed" in data
    if not has_verdict:
        logger.warning("QA result has no verdict or passed flag, defaulting to FAIL")
        data["verdict"] = "FAIL"
        data["passed"] = False

    return data
