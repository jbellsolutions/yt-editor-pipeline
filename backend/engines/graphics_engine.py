"""
Rich FFmpeg overlay graphics engine — lower-thirds, title cards, popups, badges.

All graphics are applied in a SINGLE FFmpeg pass for performance.
Uses drawbox + drawtext filter chains with timed enable expressions.
"""
import logging
import os
import subprocess
from typing import List

logger = logging.getLogger(__name__)

ENCODE_OPTS = ["-threads", "2", "-preset", "fast", "-crf", "18"]
TIMEOUT = 300  # 5 min for graphics pass


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _run(cmd: list, timeout: int = TIMEOUT) -> subprocess.CompletedProcess:
    """Run a subprocess with logging and error handling."""
    cmd_str = " ".join(str(c) for c in cmd)
    logger.info(f"Graphics cmd: {cmd_str}")
    result = subprocess.run(
        [str(c) for c in cmd],
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    if result.returncode != 0:
        logger.error(f"Graphics stderr: {result.stderr[:2000]}")
        raise RuntimeError(
            f"Graphics cmd failed (exit {result.returncode}): {result.stderr[:500]}"
        )
    return result


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
# Individual graphic filter builders
# ---------------------------------------------------------------------------

def _build_lower_third_filter(config: dict, font_path: str) -> str:
    """Build FFmpeg filter string for an animated lower-third name/title bar.

    config keys:
        name (str): Primary name text
        subtitle (str): Secondary subtitle text (optional)
        start (float): Start time in seconds
        duration (float): Duration in seconds
    """
    name = _escape_text(config.get("name", ""))
    subtitle = _escape_text(config.get("subtitle", ""))
    start = config["start"]
    end = start + config["duration"]
    fa = _font_arg(font_path)

    enable = f"enable='between(t,{start},{end})'"

    # Semi-transparent dark bar at bottom 18% of frame
    bar_filter = (
        f"drawbox=x=0:y=ih*0.82:w=iw:h=ih*0.18"
        f":color=black@0.7:t=fill:{enable}"
    )

    # Name text — slide-in animation from left over 0.5s
    # x expression: starts off-screen left, slides to x=50 over 0.5s
    name_x = f"if(lt(t-{start},0.5),-text_w+(text_w+50)*((t-{start})/0.5),50)"
    name_filter = (
        f"drawtext=text='{name}'"
        f"{fa}"
        f":fontsize=42:fontcolor=white"
        f":borderw=2:bordercolor=black@0.5"
        f":x='{name_x}':y=ih*0.84"
        f":{enable}"
    )

    filters = [bar_filter, name_filter]

    # Subtitle text — same slide-in, slightly delayed feel via position
    if subtitle:
        sub_x = f"if(lt(t-{start},0.5),-text_w+(text_w+50)*((t-{start})/0.5),50)"
        sub_filter = (
            f"drawtext=text='{subtitle}'"
            f"{fa}"
            f":fontsize=28:fontcolor=gray"
            f":x='{sub_x}':y=ih*0.91"
            f":{enable}"
        )
        filters.append(sub_filter)

    return ",".join(filters)


def _build_title_card_filter(config: dict, font_path: str) -> str:
    """Build FFmpeg filter string for a full-screen title card transition.

    config keys:
        text (str): Title card text
        start (float): Start time in seconds
        duration (float): Duration in seconds
        fontsize (int): Optional, default 72
    """
    text = _escape_text(config.get("text", ""))
    start = config["start"]
    end = start + config["duration"]
    fontsize = config.get("fontsize", 72)
    fa = _font_arg(font_path)

    enable = f"enable='between(t,{start},{end})'"

    # Dark overlay covering full frame
    overlay_filter = (
        f"drawbox=x=0:y=0:w=iw:h=ih"
        f":color=black@0.8:t=fill:{enable}"
    )

    # Fade-in via alpha expression over first 0.4s of the card
    alpha_expr = f"if(lt(t-{start},0.4),(t-{start})/0.4,1)"

    # Large centered text with fade-in
    text_filter = (
        f"drawtext=text='{text}'"
        f"{fa}"
        f":fontsize={fontsize}:fontcolor=white@'{alpha_expr}'"
        f":borderw=3:bordercolor=black@0.4"
        f":x=(w-text_w)/2:y=(h-text_h)/2"
        f":{enable}"
    )

    return f"{overlay_filter},{text_filter}"


def _build_popup_filter(config: dict, font_path: str) -> str:
    """Build FFmpeg filter string for an animated text popup callout.

    config keys:
        text (str): Popup text
        start (float): Start time in seconds
        duration (float): Duration in seconds
        fontsize (int): Optional, default 36
    """
    text = _escape_text(config.get("text", ""))
    start = config["start"]
    end = start + config["duration"]
    fontsize = config.get("fontsize", 36)
    fa = _font_arg(font_path)

    enable = f"enable='between(t,{start},{end})'"

    # Background pill shape — drawbox centered at bottom, above lower-third zone
    # Pill positioned at bottom-center, y at 72% (above the 82% lower-third zone)
    pill_w = max(len(config.get("text", "")) * fontsize * 0.55, 200)
    pill_h = fontsize + 30
    pill_x = f"(iw-{int(pill_w)})/2"
    pill_y = f"ih*0.72-{int(pill_h/2)}"

    pill_filter = (
        f"drawbox=x={pill_x}:y={pill_y}"
        f":w={int(pill_w)}:h={int(pill_h)}"
        f":color=black@0.75:t=fill:{enable}"
    )

    # Bold text centered in pill
    text_filter = (
        f"drawtext=text='{text}'"
        f"{fa}"
        f":fontsize={fontsize}:fontcolor=white"
        f":borderw=2:bordercolor=black@0.4"
        f":x=(w-text_w)/2:y=ih*0.72-text_h/2"
        f":{enable}"
    )

    return f"{pill_filter},{text_filter}"


def _build_badge_filter(config: dict, font_path: str) -> str:
    """Build FFmpeg filter string for a small corner badge label.

    config keys:
        text (str): Badge text (e.g. "SUBSCRIBE", "NEW", "Part 1")
        start (float): Start time in seconds
        duration (float): Duration in seconds
        corner (str): "top_left" | "top_right" | "bottom_left" | "bottom_right"
                      Default: "top_right"
        fontsize (int): Optional, default 24
        color (str): Background color, default "red@0.85"
    """
    text = _escape_text(config.get("text", ""))
    start = config["start"]
    end = start + config["duration"]
    corner = config.get("corner", "top_right")
    fontsize = config.get("fontsize", 24)
    bg_color = config.get("color", "red@0.85")
    fa = _font_arg(font_path)

    enable = f"enable='between(t,{start},{end})'"

    # Badge dimensions
    badge_w = max(len(config.get("text", "")) * fontsize * 0.65, 80) + 20
    badge_h = fontsize + 16

    # Position based on corner
    positions = {
        "top_left": (10, 10),
        "top_right": (f"iw-{int(badge_w)}-10", 10),
        "bottom_left": (10, f"ih-{int(badge_h)}-10"),
        "bottom_right": (f"iw-{int(badge_w)}-10", f"ih-{int(badge_h)}-10"),
    }
    box_x, box_y = positions.get(corner, positions["top_right"])

    # Text position — centered within badge
    text_positions = {
        "top_left": ("20", f"{int(8 + fontsize * 0.05)}"),
        "top_right": (f"iw-{int(badge_w)}+10", f"{int(8 + fontsize * 0.05)}"),
        "bottom_left": ("20", f"ih-{int(badge_h)}"),
        "bottom_right": (f"iw-{int(badge_w)}+10", f"ih-{int(badge_h)}"),
    }
    text_x, text_y = text_positions.get(corner, text_positions["top_right"])

    box_filter = (
        f"drawbox=x={box_x}:y={box_y}"
        f":w={int(badge_w)}:h={int(badge_h)}"
        f":color={bg_color}:t=fill:{enable}"
    )

    text_filter = (
        f"drawtext=text='{text}'"
        f"{fa}"
        f":fontsize={fontsize}:fontcolor=white"
        f":borderw=1:bordercolor=black@0.3"
        f":x={text_x}:y={text_y}"
        f":{enable}"
    )

    return f"{box_filter},{text_filter}"


# ---------------------------------------------------------------------------
# Graphic type dispatcher
# ---------------------------------------------------------------------------

_BUILDERS = {
    "lower_third": _build_lower_third_filter,
    "title_card": _build_title_card_filter,
    "popup": _build_popup_filter,
    "badge": _build_badge_filter,
}


# ---------------------------------------------------------------------------
# Main public API
# ---------------------------------------------------------------------------

def apply_graphics(video_path: str, graphics: list, output_path: str) -> str:
    """Apply all graphics in a single FFmpeg pass.

    Args:
        video_path: Path to the input video file.
        graphics: List of dicts, each with:
            - type: "lower_third" | "title_card" | "popup" | "badge"
            - start: float (seconds)
            - duration: float (seconds)
            - config: dict (type-specific params — see individual builders)
        output_path: Path for the output video.

    Returns:
        output_path on success.

    Raises:
        RuntimeError: If FFmpeg fails.
        ValueError: If an unknown graphic type is encountered.
    """
    if not graphics:
        logger.warning("apply_graphics called with empty graphics list, copying input")
        _run(["ffmpeg", "-y", "-i", video_path, "-c", "copy", output_path])
        return output_path

    font_path = _detect_font()
    if not font_path:
        logger.warning("No system font detected; text rendering may use default font")

    # Build filter chain from all graphics
    filter_parts = []
    for g in graphics:
        gtype = g.get("type")
        builder = _BUILDERS.get(gtype)
        if builder is None:
            raise ValueError(
                f"Unknown graphic type '{gtype}'. "
                f"Valid types: {list(_BUILDERS.keys())}"
            )

        # Merge top-level start/duration into config for builder convenience
        config = dict(g.get("config", {}))
        config["start"] = g["start"]
        config["duration"] = g["duration"]

        fragment = builder(config, font_path)
        if fragment:
            filter_parts.append(fragment)

    if not filter_parts:
        logger.warning("No valid filter fragments built, copying input")
        _run(["ffmpeg", "-y", "-i", video_path, "-c", "copy", output_path])
        return output_path

    # Join all filter fragments into one video filter chain
    vf = ",".join(filter_parts)

    # Ensure output directory exists
    out_dir = os.path.dirname(output_path)
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)

    _run([
        "ffmpeg", "-y",
        "-i", video_path,
        "-vf", vf,
        "-c:v", "libx264", *ENCODE_OPTS,
        "-c:a", "copy",
        output_path,
    ])

    if not os.path.exists(output_path):
        raise RuntimeError(f"Graphics output not created: {output_path}")

    size_mb = os.path.getsize(output_path) / (1024 * 1024)
    logger.info(
        f"apply_graphics: {len(graphics)} graphics applied → "
        f"{output_path} ({size_mb:.1f} MB)"
    )
    return output_path
