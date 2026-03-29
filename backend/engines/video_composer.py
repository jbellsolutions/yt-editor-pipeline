"""
UGC / Testimonial / Case Study Video Composer.

Creates professional composed videos from:
- Avatar talking-head clip (main footage from HeyGen)
- B-roll footage (overlaid at specified timestamps)
- Lower-third text overlays (name, title, key points)
- Background music (mixed under voice)
- Transitions (cross-fade between sections)

All composition done with FFmpeg — no new dependencies.

Templates:
    - testimonial: Avatar speaks, B-roll cutaways, lower-thirds with name/title
    - case_study: Problem → Solution → Results structure with B-roll + metrics
    - product_demo: Avatar intro → screen recording → Avatar outro

Usage:
    from engines.video_composer import compose_video

    config = {
        "template": "testimonial",
        "avatar_clip": "/path/to/heygen_output.mp4",
        "sections": [
            {
                "type": "avatar",
                "start": 0, "end": 15,
                "lower_third": {"name": "Josh", "title": "CEO, Company"}
            },
            {
                "type": "broll",
                "start": 15, "end": 22,
                "clip": "/path/to/broll_1.mp4",
                "text_overlay": "50% Revenue Growth"
            },
            {
                "type": "avatar",
                "start": 22, "end": 45,
            }
        ],
        "music": "/path/to/background.mp3",
        "music_volume": 0.15,
    }
    output = compose_video(config, job_id="abc123")
"""
import json
import logging
import os
import subprocess
import tempfile
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

DATA_DIR = os.environ.get("DATA_DIR", "/opt/yt-editor/data")
ASSETS_DIR = "/opt/yt-editor/backend/assets"
ENCODE_OPTS = ["-threads", "2", "-preset", "fast", "-crf", "23"]
TIMEOUT = 600


def _run(cmd: list, timeout: int = TIMEOUT) -> subprocess.CompletedProcess:
    """Run subprocess with logging."""
    cmd_str = " ".join(str(c) for c in cmd)
    logger.info(f"Composer cmd: {cmd_str[:200]}...")
    result = subprocess.run(
        [str(c) for c in cmd], capture_output=True, text=True, timeout=timeout,
    )
    if result.returncode != 0:
        logger.error(f"Composer stderr: {result.stderr[:2000]}")
        raise RuntimeError(f"Composer failed (exit {result.returncode}): {result.stderr[:500]}")
    return result


def _detect_font() -> str:
    """Find a usable bold font on the system."""
    candidates = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    ]
    for f in candidates:
        if os.path.exists(f):
            return f
    return ""


def compose_video(config: dict, job_id: str) -> str:
    """Compose a UGC/testimonial/case study video from config.

    ┌─────────────────────────────────────────────────────┐
    │  COMPOSITION PIPELINE                                │
    │                                                      │
    │  1. Parse sections from config                       │
    │  2. For each section:                                │
    │     - "avatar": trim avatar clip to timestamp range  │
    │     - "broll": trim B-roll clip, add text overlay    │
    │  3. Add lower-thirds to avatar sections              │
    │  4. Concatenate all sections with cross-fades        │
    │  5. Mix background music under voice audio           │
    │  6. Output final MP4                                 │
    └─────────────────────────────────────────────────────┘

    Returns path to composed MP4.
    """
    output_dir = os.path.join(DATA_DIR, "edited")
    os.makedirs(output_dir, exist_ok=True)
    output_path = os.path.join(output_dir, f"{job_id}_composed.mp4")

    avatar_clip = config.get("avatar_clip")
    if not avatar_clip or not os.path.exists(avatar_clip):
        raise ValueError(f"Avatar clip not found: {avatar_clip}")

    sections = config.get("sections", [])
    if not sections:
        raise ValueError("No sections defined in composition config")

    music_path = config.get("music")
    music_volume = config.get("music_volume", 0.15)
    font_path = _detect_font()

    with tempfile.TemporaryDirectory() as tmpdir:
        # ── Step 1: Render each section to a temp file ────────────────────
        section_files = []

        for i, section in enumerate(sections):
            section_type = section.get("type", "avatar")
            section_path = os.path.join(tmpdir, f"section_{i:03d}.mp4")

            if section_type == "avatar":
                _render_avatar_section(
                    avatar_clip, section, section_path, font_path, i
                )
            elif section_type == "broll":
                _render_broll_section(
                    section, section_path, font_path, i
                )
            else:
                logger.warning(f"Unknown section type '{section_type}', skipping")
                continue

            if os.path.exists(section_path) and os.path.getsize(section_path) > 100:
                section_files.append(section_path)
            else:
                logger.warning(f"Section {i} ({section_type}) failed to render")

        if not section_files:
            raise RuntimeError("No sections rendered successfully")

        # ── Step 2: Concatenate sections ──────────────────────────────────
        concat_path = os.path.join(tmpdir, "concat.mp4")
        _concatenate_sections(section_files, concat_path)

        # ── Step 3: Mix background music ──────────────────────────────────
        if music_path and os.path.exists(music_path):
            _mix_background_music(concat_path, music_path, music_volume, output_path)
        else:
            # No music — just copy
            _run(["ffmpeg", "-y", "-i", concat_path, "-c", "copy", output_path])

    logger.info(f"Composed video: {output_path}")
    return output_path


def _render_avatar_section(
    avatar_clip: str, section: dict, output_path: str, font_path: str, index: int
) -> None:
    """Render an avatar section: trim clip + optional lower-third."""
    start = section.get("start", 0)
    end = section.get("end")
    duration = (end - start) if end else None
    lower_third = section.get("lower_third")

    # Build FFmpeg command
    cmd = ["ffmpeg", "-y", "-ss", str(start), "-i", avatar_clip]
    if duration:
        cmd.extend(["-t", str(duration)])

    # Add lower-third overlay if specified
    if lower_third and font_path:
        name = lower_third.get("name", "")
        title = lower_third.get("title", "")
        safe_name = name.replace("'", "\\'").replace(":", "\\:")
        safe_title = title.replace("'", "\\'").replace(":", "\\:")

        # Lower-third: dark semi-transparent bar with name + title
        #   ┌────────────────────────────────────┐
        #   │                                    │
        #   │                                    │
        #   │  ┌──────────────────────────────┐  │
        #   │  │ Josh                         │  │
        #   │  │ CEO, Company                 │  │
        #   │  └──────────────────────────────┘  │
        #   └────────────────────────────────────┘
        vf_parts = [
            # Dark bar at bottom
            "drawbox=x=0:y=ih*0.82:w=iw*0.45:h=ih*0.16:color=black@0.7:t=fill",
        ]
        if safe_name:
            vf_parts.append(
                f"drawtext=text='{safe_name}'"
                f":fontfile={font_path}"
                f":fontsize=36:fontcolor=white:borderw=0"
                f":x=30:y=ih*0.84"
                f":enable='between(t,1,{duration - 1 if duration else 9999})'"
            )
        if safe_title:
            vf_parts.append(
                f"drawtext=text='{safe_title}'"
                f":fontfile={font_path}"
                f":fontsize=24:fontcolor=#CCCCCC:borderw=0"
                f":x=30:y=ih*0.84+42"
                f":enable='between(t,1,{duration - 1 if duration else 9999})'"
            )

        cmd.extend(["-vf", ",".join(vf_parts)])

    cmd.extend([
        "-c:v", "libx264", *ENCODE_OPTS,
        "-c:a", "aac", "-b:a", "128k",
        output_path,
    ])
    _run(cmd, timeout=300)


def _render_broll_section(
    section: dict, output_path: str, font_path: str, index: int
) -> None:
    """Render a B-roll section: trim clip + optional text overlay."""
    clip_path = section.get("clip")
    if not clip_path or not os.path.exists(clip_path):
        raise ValueError(f"B-roll clip not found: {clip_path}")

    start = section.get("start", 0)
    end = section.get("end")
    duration = (end - start) if end else None
    text_overlay = section.get("text_overlay")

    cmd = ["ffmpeg", "-y", "-ss", str(start), "-i", clip_path]
    if duration:
        cmd.extend(["-t", str(duration)])

    # Add text overlay if specified
    if text_overlay and font_path:
        safe_text = text_overlay.replace("'", "\\'").replace(":", "\\:")
        vf = (
            f"drawtext=text='{safe_text}'"
            f":fontfile={font_path}"
            f":fontsize=56:fontcolor=white:borderw=3:bordercolor=black"
            f":x=(w-text_w)/2:y=(h-text_h)/2"
        )
        cmd.extend(["-vf", vf])

    cmd.extend([
        "-c:v", "libx264", *ENCODE_OPTS,
        "-c:a", "aac", "-b:a", "128k",
        output_path,
    ])
    _run(cmd, timeout=300)


def _concatenate_sections(section_files: list, output_path: str) -> None:
    """Concatenate rendered sections using concat demuxer."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
        for path in section_files:
            f.write(f"file '{path}'\n")
        list_path = f.name

    try:
        _run([
            "ffmpeg", "-y", "-f", "concat", "-safe", "0",
            "-i", list_path,
            "-c:v", "libx264", *ENCODE_OPTS,
            "-c:a", "aac", "-b:a", "128k",
            output_path,
        ], timeout=600)
    finally:
        os.unlink(list_path)


def _mix_background_music(
    video_path: str, music_path: str, volume: float, output_path: str
) -> None:
    """Mix background music under the video's voice audio.

    Music is looped to match video length, volume-reduced, then mixed
    with the original audio.
    """
    _run([
        "ffmpeg", "-y",
        "-i", video_path,
        "-stream_loop", "-1", "-i", music_path,
        "-filter_complex", (
            f"[1:a]volume={volume}[music];"
            f"[0:a][music]amix=inputs=2:duration=first:dropout_transition=3[aout]"
        ),
        "-map", "0:v", "-map", "[aout]",
        "-c:v", "copy",
        "-c:a", "aac", "-b:a", "128k",
        "-shortest",
        output_path,
    ], timeout=600)


# ─── Template Presets ────────────────────────────────────────────────────────

def build_testimonial_config(
    avatar_clip: str,
    script_sections: List[dict],
    broll_clips: List[str] = None,
    music_path: str = None,
    speaker_name: str = "",
    speaker_title: str = "",
) -> dict:
    """Build a testimonial video composition config.

    script_sections: list of {"text": str, "duration": float}
    broll_clips: optional B-roll clips to insert between avatar sections
    """
    sections = []
    time_cursor = 0.0
    broll_idx = 0

    for i, script_sec in enumerate(script_sections):
        dur = script_sec.get("duration", 10)

        # Avatar section (speaker talking)
        avatar_section = {
            "type": "avatar",
            "start": time_cursor,
            "end": time_cursor + dur,
        }
        # Add lower-third on first appearance
        if i == 0 and (speaker_name or speaker_title):
            avatar_section["lower_third"] = {
                "name": speaker_name,
                "title": speaker_title,
            }
        sections.append(avatar_section)
        time_cursor += dur

        # Insert B-roll between sections (if available)
        if broll_clips and broll_idx < len(broll_clips) and i < len(script_sections) - 1:
            broll_dur = 5.0  # Default 5-second B-roll cutaway
            sections.append({
                "type": "broll",
                "start": 0,
                "end": broll_dur,
                "clip": broll_clips[broll_idx],
                "text_overlay": script_sec.get("key_point", ""),
            })
            time_cursor += broll_dur
            broll_idx += 1

    return {
        "template": "testimonial",
        "avatar_clip": avatar_clip,
        "sections": sections,
        "music": music_path,
        "music_volume": 0.12,
    }


def build_case_study_config(
    avatar_clip: str,
    problem: dict,
    solution: dict,
    results: dict,
    broll_clips: List[str] = None,
    music_path: str = None,
    speaker_name: str = "",
    speaker_title: str = "",
) -> dict:
    """Build a case study video (Problem → Solution → Results).

    Each section dict: {"text": str, "duration": float, "key_metric": str}
    """
    sections = []
    time_cursor = 0.0

    for i, (label, section_data) in enumerate([
        ("THE PROBLEM", problem),
        ("THE SOLUTION", solution),
        ("THE RESULTS", results),
    ]):
        dur = section_data.get("duration", 15)

        # Avatar speaking section
        avatar_sec = {
            "type": "avatar",
            "start": time_cursor,
            "end": time_cursor + dur,
        }
        if i == 0:
            avatar_sec["lower_third"] = {
                "name": speaker_name,
                "title": speaker_title,
            }
        sections.append(avatar_sec)
        time_cursor += dur

        # B-roll with metric/label overlay
        if broll_clips and i < len(broll_clips):
            metric = section_data.get("key_metric", label)
            sections.append({
                "type": "broll",
                "start": 0,
                "end": 5,
                "clip": broll_clips[i] if i < len(broll_clips) else broll_clips[0],
                "text_overlay": metric,
            })
            time_cursor += 5

    return {
        "template": "case_study",
        "avatar_clip": avatar_clip,
        "sections": sections,
        "music": music_path,
        "music_volume": 0.12,
    }
