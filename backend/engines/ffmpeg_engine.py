"""
v6 FFmpeg engine — smart crop by video type, animated captions, thumbnail frames.
Optimized for 2GB RAM droplet: -threads 2, -preset fast -crf 23.
"""
import json
import logging
import math
import os
import re
import shutil
import subprocess
import tempfile
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

ENCODE_OPTS = ["-threads", "2", "-preset", "fast", "-crf", "23"]
TIMEOUT = 600  # 10 min default timeout


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _run(cmd: list, timeout: int = TIMEOUT) -> subprocess.CompletedProcess:
    """Run a subprocess with logging and error handling."""
    cmd_str = " ".join(str(c) for c in cmd)
    logger.info(f"FFmpeg cmd: {cmd_str}")
    result = subprocess.run(
        [str(c) for c in cmd],
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    if result.returncode != 0:
        logger.error(f"FFmpeg stderr: {result.stderr[:2000]}")
        raise RuntimeError(
            f"FFmpeg failed (exit {result.returncode}): {result.stderr[:500]}"
        )
    return result


def _normalize_and_prepare_for_concat(
    files: list, target_w: int, target_h: int, target_fps: int, workdir: str
) -> list:
    """Normalize resolution/fps for a list of files, return list of normalized paths."""
    normalized = []
    for i, fpath in enumerate(files):
        if not fpath or not os.path.exists(fpath):
            continue
        out = os.path.join(workdir, f"norm_{i}.mp4")
        _run([
            "ffmpeg", "-y", "-i", fpath,
            "-vf", (
                f"scale={target_w}:{target_h}:force_original_aspect_ratio=decrease,"
                f"pad={target_w}:{target_h}:(ow-iw)/2:(oh-ih)/2,fps={target_fps}"
            ),
            "-c:v", "libx264", *ENCODE_OPTS,
            "-c:a", "aac", "-b:a", "128k", "-ar", "48000", "-ac", "2",
            out,
        ], timeout=600)
        normalized.append(out)
    return normalized


# ---------------------------------------------------------------------------
# probe_video  (unchanged)
# ---------------------------------------------------------------------------

def probe_video(path: str) -> dict:
    """Probe video for metadata. Returns dict with duration, width, height, fps, codec."""
    cmd = [
        "ffprobe", "-v", "quiet",
        "-print_format", "json",
        "-show_format", "-show_streams",
        path,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    if result.returncode != 0:
        raise RuntimeError(f"ffprobe failed: {result.stderr[:500]}")

    data = json.loads(result.stdout)
    video_stream = next(
        (s for s in data.get("streams", []) if s.get("codec_type") == "video"),
        {},
    )

    fps_str = video_stream.get("r_frame_rate", "30/1")
    try:
        num, den = fps_str.split("/")
        fps = round(int(num) / int(den), 2)
    except (ValueError, ZeroDivisionError):
        fps = 30.0

    return {
        "duration": float(data.get("format", {}).get("duration", 0)),
        "width": int(video_stream.get("width", 0)),
        "height": int(video_stream.get("height", 0)),
        "fps": fps,
        "codec": video_stream.get("codec_name", "unknown"),
    }


# ---------------------------------------------------------------------------
# detect_video_type  (NEW)
# ---------------------------------------------------------------------------

def detect_video_type(video_path: str) -> dict:
    """Analyze video to determine its type.

    Returns dict with keys:
        type: "talking_head" | "screen_recording" | "loom_bubble" | "presentation" | "mixed"
        has_face: bool
        face_position: "center" | "left" | "right" | "corner" | None
        dominant_motion: "static" | "dynamic"
        resolution: {width, height}
    """
    try:
        info = probe_video(video_path)
        duration = info["duration"]
        width = info["width"]
        height = info["height"]

        if duration <= 0 or width <= 0 or height <= 0:
            logger.warning("detect_video_type: invalid probe data, defaulting to mixed")
            return {
                "type": "mixed",
                "has_face": False,
                "face_position": None,
                "dominant_motion": "static",
                "resolution": {"width": width, "height": height},
            }

        # Extract 5 evenly spaced frames
        timestamps = [duration * i / 6 for i in range(1, 6)]
        face_results = []

        with tempfile.TemporaryDirectory() as tmpdir:
            for idx, ts in enumerate(timestamps):
                frame_path = os.path.join(tmpdir, f"frame_{idx}.png")
                try:
                    _run([
                        "ffmpeg", "-y", "-ss", str(ts),
                        "-i", video_path,
                        "-frames:v", "1",
                        "-threads", "2",
                        frame_path,
                    ], timeout=30)
                except Exception:
                    continue

                if not os.path.exists(frame_path):
                    continue

                # Use signalstats for heuristic classification
                try:
                    sig_result = subprocess.run(
                        [
                            "ffmpeg", "-i", frame_path,
                            "-vf", "signalstats=stat=tout+vrep+brng,metadata=mode=print",
                            "-f", "null", "-",
                        ],
                        capture_output=True, text=True, timeout=15,
                    )
                    stderr = sig_result.stderr

                    brng_match = re.search(r"BRNG=(\d+\.?\d*)", stderr)
                    brng = float(brng_match.group(1)) if brng_match else 0

                    face_results.append({"brng": brng, "timestamp": ts})
                except Exception:
                    face_results.append({"brng": 0, "timestamp": ts})

        avg_brng = sum(r["brng"] for r in face_results) / max(len(face_results), 1)
        aspect = width / max(height, 1)

        has_face = False
        face_position = None
        video_type = "mixed"
        dominant_motion = "static"

        if aspect < 1.0:
            # Already vertical — likely a phone recording / talking head
            video_type = "talking_head"
            has_face = True
            face_position = "center"
        elif avg_brng > 15:
            # High out-of-range pixels suggest natural camera footage (face)
            video_type = "talking_head"
            has_face = True
            face_position = "center"
        elif avg_brng < 3 and aspect >= 1.5:
            # Very clean frames, wide aspect — screen recording
            video_type = "screen_recording"
            has_face = False
            face_position = None
            dominant_motion = "static"
        elif avg_brng < 8:
            video_type = "presentation"
            has_face = False
            face_position = None
            dominant_motion = "static"
        else:
            video_type = "mixed"
            dominant_motion = "dynamic"

        result = {
            "type": video_type,
            "has_face": has_face,
            "face_position": face_position,
            "dominant_motion": dominant_motion,
            "resolution": {"width": width, "height": height},
        }
        logger.info(f"detect_video_type result: {result}")
        return result

    except Exception as e:
        logger.error(f"detect_video_type failed: {e}")
        return {
            "type": "mixed",
            "has_face": False,
            "face_position": None,
            "dominant_motion": "static",
            "resolution": {"width": 0, "height": 0},
        }


# ---------------------------------------------------------------------------
# smart_crop  (NEW)
# ---------------------------------------------------------------------------

def smart_crop(
    video_path: str,
    video_type_info: dict,
    output_path: str,
    target_ratio: str = "9:16",
) -> str:
    """Apply the RIGHT crop strategy based on video type.

    - talking_head: crop around face, keep face centered
    - screen_recording / loom_bubble / presentation: scale full frame, pad
    - mixed: center crop fallback
    """
    try:
        vtype = video_type_info.get("type", "mixed")
        info = probe_video(video_path)
        w, h = info["width"], info["height"]
        logger.info(f"smart_crop: type={vtype}, source={w}x{h}, target={target_ratio}")

        if target_ratio == "9:16":
            target_w, target_h = 1080, 1920
        else:
            target_w, target_h = 1920, 1080

        if vtype == "talking_head":
            # Crop around face — center crop to 9:16
            face_pos = video_type_info.get("face_position", "center")
            crop_w = int(h * 9 / 16)
            if crop_w > w:
                crop_w = w

            if face_pos == "left":
                x_offset = 0
            elif face_pos == "right":
                x_offset = w - crop_w
            else:
                x_offset = (w - crop_w) // 2

            vf = f"crop={crop_w}:{h}:{x_offset}:0,scale={target_w}:{target_h}"
            _run([
                "ffmpeg", "-y", "-i", video_path,
                "-vf", vf,
                "-c:v", "libx264", *ENCODE_OPTS,
                "-c:a", "aac", "-b:a", "128k",
                output_path,
            ], timeout=TIMEOUT)

        elif vtype in ("screen_recording", "loom_bubble", "presentation"):
            # Scale full frame to fit width, pad top+bottom with black
            vf = f"scale={target_w}:-2,pad={target_w}:{target_h}:(ow-iw)/2:(oh-ih)/2:black"
            _run([
                "ffmpeg", "-y", "-i", video_path,
                "-vf", vf,
                "-c:v", "libx264", *ENCODE_OPTS,
                "-c:a", "aac", "-b:a", "128k",
                output_path,
            ], timeout=TIMEOUT)

        else:
            # mixed — center crop fallback
            crop_w = int(h * 9 / 16)
            if crop_w > w:
                crop_w = w
            x_offset = (w - crop_w) // 2
            vf = f"crop={crop_w}:{h}:{x_offset}:0,scale={target_w}:{target_h}"
            _run([
                "ffmpeg", "-y", "-i", video_path,
                "-vf", vf,
                "-c:v", "libx264", *ENCODE_OPTS,
                "-c:a", "aac", "-b:a", "128k",
                output_path,
            ], timeout=TIMEOUT)

        logger.info(f"smart_crop complete: {output_path}")
        return output_path

    except Exception as e:
        logger.error(f"smart_crop failed: {e}")
        return None


# ---------------------------------------------------------------------------
# extract_audio  (unchanged)
# ---------------------------------------------------------------------------

def extract_audio(
    video_path: str, audio_path: str, sample_rate: int = 16000
) -> str:
    """Extract audio as mono MP3."""
    _run([
        "ffmpeg", "-y", "-i", video_path,
        "-vn", "-ac", "1", "-ar", str(sample_rate),
        "-q:a", "4",
        audio_path,
    ])
    return audio_path


# ---------------------------------------------------------------------------
# detect_silence  (unchanged)
# ---------------------------------------------------------------------------

def detect_silence(
    video_path: str, threshold: int = -30, min_duration: float = 1.5
) -> list:
    """Detect silent segments using silencedetect filter.
    Returns list of {"start": float, "end": float}.
    """
    cmd = [
        "ffmpeg", "-i", video_path,
        "-af", f"silencedetect=n={threshold}dB:d={min_duration}",
        "-f", "null", "-",
    ]
    result = subprocess.run(
        cmd, capture_output=True, text=True, timeout=TIMEOUT
    )
    output = result.stderr
    silences = []
    current_start = None

    for line in output.split("\n"):
        if "silence_start:" in line:
            try:
                current_start = float(line.split("silence_start:")[1].strip().split()[0])
            except (ValueError, IndexError):
                pass
        elif "silence_end:" in line and current_start is not None:
            try:
                end = float(line.split("silence_end:")[1].strip().split()[0])
                silences.append({"start": current_start, "end": end})
                current_start = None
            except (ValueError, IndexError):
                pass

    return silences


# ---------------------------------------------------------------------------
# remove_segments  (unchanged)
# ---------------------------------------------------------------------------

def remove_segments(
    video_path: str, cut_segments: list, output_path: str
) -> str:
    """Remove segments from video using sequential cuts + concat demuxer.

    LOW MEMORY approach (~200MB peak vs ~1.7GB with filter_complex):
    1. Calculate which segments to KEEP (inverse of cut_segments)
    2. Extract each keep-segment to a temp file using -ss/-to (stream copy, fast)
    3. Re-encode each segment to normalize timestamps
    4. Concatenate all segments using concat demuxer (streams from disk)

    This is critical for 2GB RAM droplets — filter_complex loads all segments
    into memory simultaneously, causing OOM/swap thrashing on longer videos.

    cut_segments: list of {"start": float, "end": float} to REMOVE.
    """
    if not cut_segments:
        _run(["ffmpeg", "-y", "-i", video_path, "-c", "copy", output_path])
        return output_path

    info = probe_video(video_path)
    duration = info["duration"]

    # Calculate segments to KEEP (inverse of segments to cut)
    cuts = sorted(cut_segments, key=lambda x: x["start"])
    keeps = []
    pos = 0.0
    for cut in cuts:
        if cut["start"] > pos + 0.1:  # Skip tiny gaps < 100ms
            keeps.append({"start": pos, "end": cut["start"]})
        pos = cut["end"]
    if pos < duration - 0.1:
        keeps.append({"start": pos, "end": duration})

    if not keeps:
        raise ValueError("All content would be removed")

    logger.info(f"remove_segments: {len(cuts)} cuts → {len(keeps)} keep segments")

    # Sequential extraction: one segment at a time → low memory
    with tempfile.TemporaryDirectory() as tmpdir:
        segment_paths = []
        for i, seg in enumerate(keeps):
            seg_path = os.path.join(tmpdir, f"seg_{i:03d}.mp4")
            seg_duration = seg["end"] - seg["start"]

            # Extract + re-encode each segment individually (~200MB peak)
            # Timeout = max(300s, 3x segment duration) so long segments don't time out
            seg_timeout = max(300, int(seg_duration * 3))
            _run([
                "ffmpeg", "-y",
                "-ss", str(seg["start"]),
                "-i", video_path,
                "-t", str(seg_duration),
                "-c:v", "libx264", *ENCODE_OPTS,
                "-c:a", "aac", "-b:a", "128k",
                "-avoid_negative_ts", "make_zero",
                seg_path,
            ], timeout=seg_timeout)

            if os.path.exists(seg_path) and os.path.getsize(seg_path) > 100:
                segment_paths.append(seg_path)
            else:
                logger.warning(f"remove_segments: segment {i} failed, skipping")

        if not segment_paths:
            raise RuntimeError("No segments extracted successfully")

        # Concatenate using concat demuxer (streams from disk, near-zero RAM)
        list_file = os.path.join(tmpdir, "concat.txt")
        with open(list_file, "w") as f:
            for p in segment_paths:
                f.write(f"file '{p}'\n")

        _run([
            "ffmpeg", "-y",
            "-f", "concat", "-safe", "0",
            "-i", list_file,
            "-c", "copy",  # No re-encode needed — segments already encoded
            output_path,
        ], timeout=120)

    logger.info(f"remove_segments complete: {len(segment_paths)} segments → {output_path}")
    return output_path


# ---------------------------------------------------------------------------
# add_text_overlays  (unchanged)
# ---------------------------------------------------------------------------

def add_text_overlays(
    video_path: str, overlays: list, output_path: str
) -> str:
    """Add text overlays using drawtext filter.
    overlays: list of {"text": str, "start": float, "end": float,
                        "x": str, "y": str, "fontsize": int, "fontcolor": str}
    """
    if not overlays:
        _run(["ffmpeg", "-y", "-i", video_path, "-c", "copy", output_path])
        return output_path

    drawtext_parts = []
    for ov in overlays:
        text = ov["text"].replace("'", "\\'").replace(":", "\\:")
        x = ov.get("x", "(w-text_w)/2")
        y = ov.get("y", "(h-text_h)/2")
        fontsize = ov.get("fontsize", 48)
        fontcolor = ov.get("fontcolor", "white")
        start = ov.get("start", 0)
        # editor agent may return {duration} instead of {end}
        end = ov.get("end") or (start + ov.get("duration", 5))
        drawtext_parts.append(
            f"drawtext=text='{text}':x={x}:y={y}:fontsize={fontsize}:"
            f"fontcolor={fontcolor}:enable='between(t,{start},{end})'"
        )

    vf = ",".join(drawtext_parts)
    _run([
        "ffmpeg", "-y", "-i", video_path,
        "-vf", vf,
        "-c:v", "libx264", *ENCODE_OPTS,
        "-c:a", "copy",
        output_path,
    ], timeout=1200)
    return output_path


# ---------------------------------------------------------------------------
# normalize_audio  (unchanged)
# ---------------------------------------------------------------------------

def normalize_audio(video_path: str, output_path: str) -> str:
    """Two-pass loudnorm (I=-16, TP=-1.5, LRA=11)."""
    cmd1 = [
        "ffmpeg", "-y", "-i", video_path,
        "-af", "loudnorm=I=-16:TP=-1.5:LRA=11:print_format=json",
        "-f", "null", "-",
    ]
    result = subprocess.run(
        cmd1, capture_output=True, text=True, timeout=TIMEOUT
    )
    stderr = result.stderr
    json_start = stderr.rfind("{")
    json_end = stderr.rfind("}") + 1
    if json_start == -1 or json_end == 0:
        raise RuntimeError("Failed to get loudnorm measurements")
    stats = json.loads(stderr[json_start:json_end])

    af = (
        f"loudnorm=I=-16:TP=-1.5:LRA=11:"
        f"measured_I={stats['input_i']}:"
        f"measured_TP={stats['input_tp']}:"
        f"measured_LRA={stats['input_lra']}:"
        f"measured_thresh={stats['input_thresh']}:"
        f"offset={stats['target_offset']}:"
        f"linear=true:print_format=summary"
    )
    _run([
        "ffmpeg", "-y", "-i", video_path,
        "-af", af,
        "-c:v", "copy",
        "-c:a", "aac", "-b:a", "192k",
        output_path,
    ], timeout=TIMEOUT)
    return output_path


# ---------------------------------------------------------------------------
# concat_with_intro_outro  (unchanged)
# ---------------------------------------------------------------------------

def concat_with_intro_outro(
    video_path: str,
    intro_path: Optional[str],
    outro_path: Optional[str],
    output_path: str,
) -> str:
    """Normalize resolution/fps, then concat via demuxer."""
    info = probe_video(video_path)
    target_w, target_h = info["width"], info["height"]
    target_fps = int(info["fps"])

    if target_w <= 0 or target_h <= 0:
        target_w, target_h = 1920, 1080
    if target_fps <= 0:
        target_fps = 30

    files_to_concat = []
    if intro_path:
        files_to_concat.append(intro_path)
    files_to_concat.append(video_path)
    if outro_path:
        files_to_concat.append(outro_path)

    if len(files_to_concat) == 1:
        _run(["ffmpeg", "-y", "-i", video_path, "-c", "copy", output_path])
        return output_path

    with tempfile.TemporaryDirectory() as workdir:
        normalized = _normalize_and_prepare_for_concat(
            files_to_concat, target_w, target_h, target_fps, workdir
        )
        list_file = os.path.join(workdir, "concat.txt")
        with open(list_file, "w") as f:
            for p in normalized:
                f.write(f"file '{p}'\n")

        _run([
            "ffmpeg", "-y", "-f", "concat", "-safe", "0",
            "-i", list_file,
            "-c:v", "libx264", *ENCODE_OPTS,
            "-c:a", "aac", "-b:a", "128k",
            output_path,
        ], timeout=1200)

    return output_path


# ---------------------------------------------------------------------------
# create_short_with_restructure  (REWRITTEN)
# ---------------------------------------------------------------------------

def create_short_with_restructure(
    source_video: str,
    short_config: dict,
    output_path: str,
    video_type_info: dict,
) -> str:
    """Create a single Short from source video.

    1. Extract segment(s), restructure if hook provided
    2. Smart crop based on video_type_info
    3. Ensure 9:16 1080x1920
    4. Returns path to the cropped short (captions added separately)

    short_config keys:
        - start, end: float (required)
        - hook_start, hook_end: float (optional — play hook first)
    """
    try:
        start = float(short_config["start"])
        end = float(short_config["end"])
        hook_start = short_config.get("hook_start")
        hook_end = short_config.get("hook_end")

        with tempfile.TemporaryDirectory() as tmpdir:
            # Build segment list (hook first if present, then rest)
            segments = []
            if hook_start is not None and hook_end is not None:
                hook_start = float(hook_start)
                hook_end = float(hook_end)
                segments.append({"start": hook_start, "end": hook_end})
                if start < hook_start:
                    segments.append({"start": start, "end": hook_start})
                if hook_end < end:
                    segments.append({"start": hook_end, "end": end})
            else:
                segments.append({"start": start, "end": end})

            # Extract and concat segments
            raw_path = os.path.join(tmpdir, "raw_short.mp4")
            if len(segments) == 1:
                seg = segments[0]
                _run([
                    "ffmpeg", "-y",
                    "-ss", str(seg["start"]),
                    "-i", source_video,
                    "-t", str(seg["end"] - seg["start"]),
                    "-c:v", "libx264", *ENCODE_OPTS,
                    "-c:a", "aac", "-b:a", "128k",
                    raw_path,
                ], timeout=TIMEOUT)
            else:
                n = len(segments)
                filters = []
                concat_inputs = ""
                for i, seg in enumerate(segments):
                    filters.append(
                        f"[0:v]trim=start={seg['start']}:end={seg['end']},"
                        f"setpts=PTS-STARTPTS[v{i}];"
                    )
                    filters.append(
                        f"[0:a]atrim=start={seg['start']}:end={seg['end']},"
                        f"asetpts=PTS-STARTPTS[a{i}];"
                    )
                    concat_inputs += f"[v{i}][a{i}]"

                filter_str = (
                    "".join(filters)
                    + f"{concat_inputs}concat=n={n}:v=1:a=1[outv][outa]"
                )
                _run([
                    "ffmpeg", "-y", "-i", source_video,
                    "-filter_complex", filter_str,
                    "-map", "[outv]", "-map", "[outa]",
                    "-c:v", "libx264", *ENCODE_OPTS,
                    "-c:a", "aac", "-b:a", "128k",
                    raw_path,
                ], timeout=1200)

            # Smart crop to 9:16
            result = smart_crop(raw_path, video_type_info, output_path, target_ratio="9:16")
            if result is None:
                raise RuntimeError("smart_crop returned None")

        logger.info(f"create_short_with_restructure complete: {output_path}")
        return output_path

    except Exception as e:
        logger.error(f"create_short_with_restructure failed: {e}")
        return None


# ---------------------------------------------------------------------------
# burn_captions_animated  (NEW — Hormozi-style)
# ---------------------------------------------------------------------------

def burn_captions_animated(
    video_path: str, words: list, output_path: str
) -> str:
    """Professional Hormozi-style animated captions.

    - 2-3 words at a time
    - Bold white text (fontsize 72), black outline (borderw=4)
    - Centered at y = h*0.75
    - Each group fades in over 0.1s
    - First word of each group in YELLOW (#FFDD00)
    - Font: DejaVu Sans Bold or system fallback
    - words: list of {"word": str, "start": float, "end": float}
    """
    try:
        if not words:
            _run(["ffmpeg", "-y", "-i", video_path, "-c", "copy", output_path])
            return output_path

        info = probe_video(video_path)
        play_w = info.get("width", 1080)
        play_h = info.get("height", 1920)

        # Group words into chunks of 2-3
        groups = []
        i = 0
        while i < len(words):
            remaining = len(words) - i
            if remaining >= 3:
                chunk_size = 3
            elif remaining == 2:
                chunk_size = 2
            else:
                chunk_size = 1
            groups.append(words[i : i + chunk_size])
            i += chunk_size

        # Build ASS subtitle file
        ass_content = "[Script Info]\n"
        ass_content += "Title: Animated Captions\n"
        ass_content += "ScriptType: v4.00+\n"
        ass_content += f"PlayResX: {play_w}\n"
        ass_content += f"PlayResY: {play_h}\n\n"
        ass_content += "[V4+ Styles]\n"
        ass_content += (
            "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, "
            "OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, "
            "ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, "
            "Alignment, MarginL, MarginR, MarginV, Encoding\n"
        )
        # White style — bold, outline 4, no shadow
        ass_content += (
            "Style: White,DejaVu Sans,72,&H00FFFFFF,&H000000FF,&H00000000,"
            "&H00000000,-1,0,0,0,100,100,0,0,1,4,0,2,10,10,10,1\n"
        )
        ass_content += "\n[Events]\n"
        ass_content += (
            "Format: Layer, Start, End, Style, Name, MarginL, MarginR, "
            "MarginV, Effect, Text\n"
        )

        # MarginV positions text at y=h*0.75 (from bottom = h*0.25)
        margin_v = int(play_h * 0.25)

        def secs_to_ass(s: float) -> str:
            h = int(s // 3600)
            m = int((s % 3600) // 60)
            sec = s % 60
            return f"{h}:{m:02d}:{sec:05.2f}"

        for group in groups:
            if not group:
                continue
            group_start = group[0]["start"]
            group_end = group[-1]["end"]

            # First word yellow, rest white. Fade in 100ms.
            parts = []
            for wi, w in enumerate(group):
                word_text = w["word"].strip()
                if not word_text:
                    continue
                if wi == 0:
                    # Yellow (#FFDD00 -> ASS BGR &H0000DDFF&) + fade
                    parts.append(
                        r"{\fad(100,0)\c&H0000DDFF&}" + word_text
                    )
                else:
                    parts.append(r"{\c&H00FFFFFF&}" + word_text)

            text = " ".join(parts)
            start_ts = secs_to_ass(group_start)
            end_ts = secs_to_ass(group_end)

            ass_content += (
                f"Dialogue: 0,{start_ts},{end_ts},White,,0,0,{margin_v},,"
                f"{text}\n"
            )

        ass_path = output_path.rsplit(".", 1)[0] + ".ass"
        with open(ass_path, "w") as f:
            f.write(ass_content)

        _run([
            "ffmpeg", "-y", "-i", video_path,
            "-vf", f"ass={ass_path}",
            "-c:v", "libx264", *ENCODE_OPTS,
            "-c:a", "copy",
            output_path,
        ], timeout=1200)

        try:
            os.remove(ass_path)
        except OSError:
            pass

        logger.info(f"burn_captions_animated complete: {output_path}")
        return output_path

    except Exception as e:
        logger.error(f"burn_captions_animated failed: {e}")
        return None


# ---------------------------------------------------------------------------
# burn_captions_longform  (standard subtitle style for long-form videos)
# ---------------------------------------------------------------------------

def burn_captions_longform(
    video_path: str, words: list, output_path: str
) -> str:
    """Standard subtitle-style captions for long-form videos.

    - 2-3 words at a time (same grouping as shorts)
    - White text on semi-transparent dark pill/background
    - Bottom-center position (classic subtitle placement)
    - Clean, readable — NOT the Hormozi pop-in style
    - Font: DejaVu Sans Bold, fontsize 48 (smaller than shorts)
    - words: list of {"word": str, "start": float, "end": float}
    """
    try:
        if not words:
            logger.warning("burn_captions_longform: no words, skipping")
            _run(["ffmpeg", "-y", "-i", video_path, "-c", "copy", output_path])
            return output_path

        info = probe_video(video_path)
        play_w = info.get("width", 1920)
        play_h = info.get("height", 1080)

        # Group words into chunks of 2-3
        groups = []
        i = 0
        while i < len(words):
            remaining = len(words) - i
            if remaining >= 3:
                chunk_size = 3
            elif remaining == 2:
                chunk_size = 2
            else:
                chunk_size = 1
            groups.append(words[i : i + chunk_size])
            i += chunk_size

        # Build ASS subtitle file — clean subtitle style
        ass_content = "[Script Info]\n"
        ass_content += "Title: Long-form Captions\n"
        ass_content += "ScriptType: v4.00+\n"
        ass_content += f"PlayResX: {play_w}\n"
        ass_content += f"PlayResY: {play_h}\n\n"
        ass_content += "[V4+ Styles]\n"
        ass_content += (
            "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, "
            "OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, "
            "ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, "
            "Alignment, MarginL, MarginR, MarginV, Encoding\n"
        )
        # Subtitle style: white text, black outline (3px), dark semi-transparent
        # background box (BorderStyle=3 = opaque box)
        ass_content += (
            "Style: Subtitle,DejaVu Sans,48,&H00FFFFFF,&H000000FF,&H00000000,"
            "&H80000000,-1,0,0,0,100,100,0,0,3,2,0,2,20,20,30,1\n"
        )
        ass_content += "\n[Events]\n"
        ass_content += (
            "Format: Layer, Start, End, Style, Name, MarginL, MarginR, "
            "MarginV, Effect, Text\n"
        )

        def secs_to_ass(s: float) -> str:
            h = int(s // 3600)
            m = int((s % 3600) // 60)
            sec = s % 60
            return f"{h}:{m:02d}:{sec:05.2f}"

        for group in groups:
            if not group:
                continue
            group_start = group[0]["start"]
            group_end = group[-1]["end"]

            text = " ".join(w["word"].strip() for w in group if w.get("word", "").strip())
            if not text:
                continue

            start_ts = secs_to_ass(group_start)
            end_ts = secs_to_ass(group_end)

            ass_content += (
                f"Dialogue: 0,{start_ts},{end_ts},Subtitle,,0,0,0,,"
                f"{text}\n"
            )

        ass_path = output_path.rsplit(".", 1)[0] + "_lf.ass"
        with open(ass_path, "w") as f:
            f.write(ass_content)

        _run([
            "ffmpeg", "-y", "-i", video_path,
            "-vf", f"ass={ass_path}",
            "-c:v", "libx264", *ENCODE_OPTS,
            "-c:a", "copy",
            output_path,
        ], timeout=1800)  # 30 min for long videos

        try:
            os.remove(ass_path)
        except OSError:
            pass

        logger.info(f"burn_captions_longform complete: {output_path}")
        return output_path

    except Exception as e:
        logger.error(f"burn_captions_longform failed: {e}")
        return None


# ---------------------------------------------------------------------------
# extract_best_frame  (NEW)
# ---------------------------------------------------------------------------

def extract_best_frame(video_path: str, timestamps: list = None) -> str:
    """Extract the best frame from a video for thumbnail use.

    - If timestamps provided, extract frames at those timestamps
    - Otherwise extract at 10%, 25%, 50%, 75% of duration
    - Pick frame at 25% (usually after the intro)
    - Save as PNG at 1280x720
    - Return path
    """
    try:
        info = probe_video(video_path)
        duration = info["duration"]

        if not timestamps:
            timestamps = [
                duration * 0.10,
                duration * 0.25,
                duration * 0.50,
                duration * 0.75,
            ]

        output_dir = os.path.dirname(video_path)
        if not output_dir:
            output_dir = "/tmp"

        best_frame_path = os.path.join(output_dir, "best_frame.png")

        with tempfile.TemporaryDirectory() as tmpdir:
            frame_paths = []
            for i, ts in enumerate(timestamps):
                frame_path = os.path.join(tmpdir, f"frame_{i}.png")
                try:
                    _run([
                        "ffmpeg", "-y",
                        "-ss", str(ts),
                        "-i", video_path,
                        "-frames:v", "1",
                        "-vf", "scale=1280:720:force_original_aspect_ratio=decrease,"
                               "pad=1280:720:(ow-iw)/2:(oh-ih)/2",
                        "-threads", "2",
                        frame_path,
                    ], timeout=30)
                    if os.path.exists(frame_path):
                        frame_paths.append(frame_path)
                except Exception:
                    continue

            if not frame_paths:
                raise RuntimeError("No frames extracted")

            # Pick frame at ~25% (index 1 with 4 frames)
            best_idx = min(1, len(frame_paths) - 1)
            best_source = frame_paths[best_idx]

            shutil.copy2(best_source, best_frame_path)

        logger.info(f"extract_best_frame: {best_frame_path}")
        return best_frame_path

    except Exception as e:
        logger.error(f"extract_best_frame failed: {e}")
        return None


# ---------------------------------------------------------------------------
# concat_short_with_bumpers  (unchanged)
# ---------------------------------------------------------------------------

def concat_short_with_bumpers(
    short_path: str,
    intro_path: Optional[str],
    outro_path: Optional[str],
    output_path: str,
) -> str:
    """Same as concat_with_intro_outro but targeting 9:16 (1080x1920)."""
    target_w, target_h = 1080, 1920
    target_fps = 30

    files_to_concat = []
    if intro_path:
        files_to_concat.append(intro_path)
    files_to_concat.append(short_path)
    if outro_path:
        files_to_concat.append(outro_path)

    if len(files_to_concat) == 1:
        _run(["ffmpeg", "-y", "-i", short_path, "-c", "copy", output_path])
        return output_path

    with tempfile.TemporaryDirectory() as workdir:
        normalized = _normalize_and_prepare_for_concat(
            files_to_concat, target_w, target_h, target_fps, workdir
        )
        list_file = os.path.join(workdir, "concat.txt")
        with open(list_file, "w") as f:
            for p in normalized:
                f.write(f"file '{p}'\n")

        _run([
            "ffmpeg", "-y", "-f", "concat", "-safe", "0",
            "-i", list_file,
            "-c:v", "libx264", *ENCODE_OPTS,
            "-c:a", "aac", "-b:a", "128k",
            output_path,
        ], timeout=1200)

    return output_path
