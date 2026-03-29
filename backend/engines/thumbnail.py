"""
v6 Thumbnail generation — frame-based with FFmpeg text overlays.
No external AI APIs. Extracts frames from video + adds styled text.
"""
import logging
import os
import subprocess
from typing import List, Optional

logger = logging.getLogger(__name__)

ENCODE_OPTS = ["-threads", "2"]
TIMEOUT = 120
THUMBNAIL_DIR = "/data/thumbnails"


def _run(cmd: list, timeout: int = TIMEOUT) -> subprocess.CompletedProcess:
    """Run a subprocess with logging and error handling."""
    cmd_str = " ".join(str(c) for c in cmd)
    logger.info(f"Thumbnail cmd: {cmd_str}")
    result = subprocess.run(
        [str(c) for c in cmd],
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    if result.returncode != 0:
        logger.error(f"Thumbnail stderr: {result.stderr[:2000]}")
        raise RuntimeError(
            f"Thumbnail cmd failed (exit {result.returncode}): {result.stderr[:500]}"
        )
    return result


def _ensure_dir(path: str) -> None:
    """Ensure directory for a file path exists."""
    d = os.path.dirname(path)
    if d:
        os.makedirs(d, exist_ok=True)


# ---------------------------------------------------------------------------
# generate_thumbnail_from_frame  (NEW)
# ---------------------------------------------------------------------------

def generate_thumbnail_from_frame(
    frame_path: str,
    title_text: str,
    output_path: str,
    style: str = "bold",
) -> str:
    """Take a frame from the video and add text overlay.

    1. Bold text overlay (3-5 words from title), positioned top-left
    2. Font: 80px bold white with black outline (4px)
    3. Semi-transparent gradient overlay at bottom
    4. Slight color boost (saturation +20%, contrast +10%)
    5. Output at 1280x720 (long-form) — caller can override via output dimensions
    6. Return path
    """
    try:
        _ensure_dir(output_path)

        # Truncate title to 3-5 words
        words = title_text.split()
        short_title = " ".join(words[:5])
        # Escape special chars for drawtext
        safe_title = short_title.replace("'", "\\'").replace(":", "\\:").replace('"', '\\"')

        # Detect font
        font_path = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
        if not os.path.exists(font_path):
            font_path = "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf"
        font_arg = f":fontfile={font_path}" if os.path.exists(font_path) else ""

        # Build filter:
        # 1. Scale to 1280x720
        # 2. Color boost (eq filter: contrast=1.1, saturation=1.2)
        # 3. Semi-transparent gradient at bottom (drawbox)
        # 4. Text overlay top-left
        vf_parts = [
            "scale=1280:720:force_original_aspect_ratio=decrease",
            "pad=1280:720:(ow-iw)/2:(oh-ih)/2",
            "eq=contrast=1.1:saturation=1.2",
            "drawbox=x=0:y=ih*0.75:w=iw:h=ih*0.25:color=black@0.4:t=fill",
            (
                f"drawtext=text='{safe_title}'"
                f"{font_arg}"
                f":fontsize=80:fontcolor=white"
                f":borderw=4:bordercolor=black"
                f":x=40:y=40"
            ),
        ]
        vf = ",".join(vf_parts)

        _run([
            "ffmpeg", "-y", "-i", frame_path,
            "-vf", vf,
            *ENCODE_OPTS,
            output_path,
        ], timeout=TIMEOUT)

        logger.info(f"generate_thumbnail_from_frame: {output_path}")
        return output_path

    except Exception as e:
        logger.error(f"generate_thumbnail_from_frame failed: {e}")
        return None


# ---------------------------------------------------------------------------
# generate_long_form_thumbnails  (NEW)
# ---------------------------------------------------------------------------

def generate_long_form_thumbnails(
    video_path: str,
    title_variants: List[str],
    job_id: str,
) -> list:
    """Generate 3 thumbnail variants for YouTube Test & Compare.

    1. Extract best frame from video
    2. For each title variant, create a thumbnail with different text positioning
    3. Save to /data/thumbnails/{job_id}_longform_thumb_{i}.png
    4. Return list of paths
    """
    try:
        from engines.ffmpeg_engine import extract_best_frame, probe_video

        os.makedirs(THUMBNAIL_DIR, exist_ok=True)

        # Extract best frame
        frame_path = extract_best_frame(video_path)
        if not frame_path or not os.path.exists(frame_path):
            logger.error("generate_long_form_thumbnails: no frame extracted")
            return []

        # Ensure we have exactly 3 variants (pad or trim)
        variants = list(title_variants)
        while len(variants) < 3:
            variants.append(variants[-1] if variants else "Watch Now")
        variants = variants[:3]

        # Detect font
        font_path = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
        if not os.path.exists(font_path):
            font_path = "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf"
        font_arg = f":fontfile={font_path}" if os.path.exists(font_path) else ""

        # Text positions for variety
        positions = [
            ("40", "40"),          # top-left
            ("(w-text_w)/2", "40"),  # top-center
            ("40", "(h-text_h)/2"),  # middle-left
        ]

        paths = []
        for i, title in enumerate(variants):
            output_path = os.path.join(
                THUMBNAIL_DIR, f"{job_id}_longform_thumb_{i}.png"
            )
            safe_title = " ".join(title.split()[:5])
            safe_title = safe_title.replace("'", "\\'").replace(":", "\\:").replace('"', '\\"')
            x_pos, y_pos = positions[i]

            vf_parts = [
                "scale=1280:720:force_original_aspect_ratio=decrease",
                "pad=1280:720:(ow-iw)/2:(oh-ih)/2",
                "eq=contrast=1.1:saturation=1.2",
                "drawbox=x=0:y=ih*0.75:w=iw:h=ih*0.25:color=black@0.4:t=fill",
                (
                    f"drawtext=text='{safe_title}'"
                    f"{font_arg}"
                    f":fontsize=80:fontcolor=white"
                    f":borderw=4:bordercolor=black"
                    f":x={x_pos}:y={y_pos}"
                ),
            ]
            vf = ",".join(vf_parts)

            try:
                _run([
                    "ffmpeg", "-y", "-i", frame_path,
                    "-vf", vf,
                    *ENCODE_OPTS,
                    output_path,
                ], timeout=TIMEOUT)
                paths.append(output_path)
                logger.info(f"Long-form thumbnail {i}: {output_path}")
            except Exception as e:
                logger.error(f"Long-form thumbnail {i} failed: {e}")

        # Clean up extracted frame
        try:
            os.remove(frame_path)
        except OSError:
            pass

        return paths

    except Exception as e:
        logger.error(f"generate_long_form_thumbnails failed: {e}")
        return []


# ---------------------------------------------------------------------------
# generate_ai_thumbnails  (NEW — FLUX-powered with headlines)
# ---------------------------------------------------------------------------

def generate_ai_thumbnails(
    video_path: str,
    headlines: List[str],
    topic_summary: str,
    job_id: str,
) -> list:
    """Generate AI-powered thumbnails using Replicate FLUX + headline overlay.

    1. Generate a compelling background image via FLUX based on the video topic
    2. Overlay bold headline text via FFmpeg
    3. Return list of paths (one per headline variant)

    Falls back to frame-based thumbnails if FLUX is unavailable.
    """
    try:
        os.makedirs(THUMBNAIL_DIR, exist_ok=True)

        # Ensure 3 headlines
        h_list = list(headlines) if headlines else ["WATCH THIS", "MUST SEE", "NEW VIDEO"]
        while len(h_list) < 3:
            h_list.append(h_list[-1])
        h_list = h_list[:3]

        # Detect font
        font_path = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
        if not os.path.exists(font_path):
            font_path = "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf"
        font_arg = f":fontfile={font_path}" if os.path.exists(font_path) else ""

        paths = []

        for i, headline in enumerate(h_list):
            output_path = os.path.join(
                THUMBNAIL_DIR, f"{job_id}_ai_thumb_{i}.png"
            )

            # Try AI generation first
            ai_bg = _generate_flux_thumbnail_bg(topic_summary, i)

            if ai_bg and os.path.exists(ai_bg):
                # AI background + headline overlay
                safe_headline = headline.replace("'", "\\'").replace(":", "\\:").replace('"', '\\"')
                vf_parts = [
                    "scale=1280:720:force_original_aspect_ratio=decrease",
                    "pad=1280:720:(ow-iw)/2:(oh-ih)/2",
                    "eq=contrast=1.1:saturation=1.3:brightness=0.03",
                    # Dark gradient on left side for text readability
                    "drawbox=x=0:y=0:w=iw*0.55:h=ih:color=black@0.45:t=fill",
                    # Big bold headline text, left-aligned
                    (
                        f"drawtext=text='{safe_headline}'"
                        f"{font_arg}"
                        f":fontsize=90:fontcolor=white"
                        f":borderw=5:bordercolor=black"
                        f":x=50:y=(h-text_h)/2"
                    ),
                ]
                vf = ",".join(vf_parts)

                try:
                    _run([
                        "ffmpeg", "-y", "-i", ai_bg,
                        "-vf", vf,
                        *ENCODE_OPTS,
                        output_path,
                    ], timeout=TIMEOUT)
                    paths.append(output_path)
                    logger.info(f"AI thumbnail {i}: {output_path}")

                    # Clean up temp AI image
                    try:
                        os.remove(ai_bg)
                    except OSError:
                        pass
                    continue
                except Exception as e:
                    logger.warning(f"AI thumbnail overlay failed, falling back to frame: {e}")

            # Fallback: extract frame + headline
            from engines.ffmpeg_engine import extract_best_frame
            frame = extract_best_frame(video_path, timestamps=[
                float(i + 1) * 0.2  # different frame per variant
            ])
            if frame:
                safe_headline = headline.replace("'", "\\'").replace(":", "\\:").replace('"', '\\"')
                vf_parts = [
                    "scale=1280:720:force_original_aspect_ratio=decrease",
                    "pad=1280:720:(ow-iw)/2:(oh-ih)/2",
                    "eq=contrast=1.15:saturation=1.25",
                    "drawbox=x=0:y=0:w=iw*0.55:h=ih:color=black@0.5:t=fill",
                    (
                        f"drawtext=text='{safe_headline}'"
                        f"{font_arg}"
                        f":fontsize=90:fontcolor=white"
                        f":borderw=5:bordercolor=black"
                        f":x=50:y=(h-text_h)/2"
                    ),
                ]
                vf = ",".join(vf_parts)
                try:
                    _run([
                        "ffmpeg", "-y", "-i", frame,
                        "-vf", vf,
                        *ENCODE_OPTS,
                        output_path,
                    ], timeout=TIMEOUT)
                    paths.append(output_path)
                except Exception as e:
                    logger.error(f"Fallback thumbnail {i} failed: {e}")

        return paths

    except Exception as e:
        logger.error(f"generate_ai_thumbnails failed: {e}")
        return []


def _generate_flux_thumbnail_bg(topic: str, variant_index: int) -> Optional[str]:
    """Generate a thumbnail background image via Replicate FLUX."""
    try:
        import replicate
        import httpx as _httpx

        if not os.environ.get("REPLICATE_API_TOKEN"):
            return None

        # Different visual styles per variant for A/B testing
        styles = [
            "dramatic cinematic lighting, dark moody atmosphere, professional",
            "bright vibrant colors, energetic, modern clean aesthetic",
            "warm golden hour lighting, inspiring, professional studio",
        ]
        style = styles[variant_index % len(styles)]

        prompt = (
            f"YouTube thumbnail background image. Topic: {topic[:200]}. "
            f"Style: {style}. "
            f"No text in the image. No faces. Abstract/conceptual background. "
            f"16:9 aspect ratio. Ultra high quality, 4K."
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

        if output and len(output) > 0:
            img_url = str(output[0])
            tmp_path = os.path.join(THUMBNAIL_DIR, f"_flux_bg_{variant_index}.png")
            resp = _httpx.get(img_url, timeout=60)
            resp.raise_for_status()
            with open(tmp_path, "wb") as f:
                f.write(resp.content)
            logger.info(f"FLUX thumbnail bg generated: {tmp_path}")
            return tmp_path

    except ImportError:
        logger.info("replicate not installed, skipping AI thumbnail")
    except Exception as e:
        logger.warning(f"FLUX thumbnail generation failed: {e}")
    return None


# ---------------------------------------------------------------------------
# generate_single_thumbnail  — 1 high-converting thumbnail, no variants
# ---------------------------------------------------------------------------

def generate_single_thumbnail(
    video_path: str,
    headline: str,
    topic_summary: str,
    job_id: str,
) -> Optional[str]:
    """Generate exactly ONE optimised thumbnail for the long-form video.

    Strategy (in priority order):
    1. FLUX AI background (dramatic cinematic) + bold headline overlay
    2. Best extracted frame + bold headline overlay
    3. Return None (caller should handle gracefully)

    The headline is shown in large bold text, left-aligned, with a dark
    semi-transparent panel behind it for readability.

    Output: /data/thumbnails/{job_id}_thumb.png  (1280x720)
    """
    try:
        os.makedirs(THUMBNAIL_DIR, exist_ok=True)
        output_path = os.path.join(THUMBNAIL_DIR, f"{job_id}_thumb.png")

        # Detect font
        font_path = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
        if not os.path.exists(font_path):
            font_path = "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf"
        font_arg = f":fontfile={font_path}" if os.path.exists(font_path) else ""

        safe_headline = headline.replace("'", "\\'").replace(":", "\\:").replace('"', '\\"')

        def _apply_overlay(source_path: str) -> bool:
            """Apply headline overlay onto source_path → output_path."""
            vf_parts = [
                "scale=1280:720:force_original_aspect_ratio=decrease",
                "pad=1280:720:(ow-iw)/2:(oh-ih)/2",
                "eq=contrast=1.12:saturation=1.25:brightness=0.02",
                # Left-side dark panel for text readability
                "drawbox=x=0:y=0:w=iw*0.6:h=ih:color=black@0.5:t=fill",
                # Large bold headline, vertically centered, left-aligned
                (
                    f"drawtext=text='{safe_headline}'"
                    f"{font_arg}"
                    f":fontsize=92:fontcolor=white"
                    f":borderw=5:bordercolor=black"
                    f":x=50:y=(h-text_h)/2"
                ),
            ]
            try:
                _run([
                    "ffmpeg", "-y", "-i", source_path,
                    "-vf", ",".join(vf_parts),
                    *ENCODE_OPTS,
                    output_path,
                ], timeout=TIMEOUT)
                return os.path.exists(output_path) and os.path.getsize(output_path) > 1000
            except Exception as e:
                logger.warning(f"_apply_overlay failed: {e}")
                return False

        # ── Attempt 1: FLUX AI background ────────────────────────────────
        ai_bg = _generate_flux_thumbnail_bg(topic_summary, 0)
        if ai_bg and os.path.exists(ai_bg):
            success = _apply_overlay(ai_bg)
            try:
                os.remove(ai_bg)
            except OSError:
                pass
            if success:
                logger.info(f"Single thumbnail (AI): {output_path}")
                return output_path

        # ── Attempt 2: Best frame from video ─────────────────────────────
        from engines.ffmpeg_engine import extract_best_frame
        frame = extract_best_frame(video_path)
        if frame and os.path.exists(frame):
            success = _apply_overlay(frame)
            try:
                os.remove(frame)
            except OSError:
                pass
            if success:
                logger.info(f"Single thumbnail (frame): {output_path}")
                return output_path

        logger.error("generate_single_thumbnail: all attempts failed")
        return None

    except Exception as e:
        logger.error(f"generate_single_thumbnail failed: {e}")
        return None


# ---------------------------------------------------------------------------
# generate_short_thumbnail  (NEW)
# ---------------------------------------------------------------------------

def generate_short_thumbnail(
    video_path: str,
    short_config: dict,
    title: str,
    job_id: str,
    short_index: int,
) -> str:
    """Generate a single thumbnail for a Short.

    1. Extract frame at hook moment (short_config.hook_start or 25% mark)
    2. Smart-crop to 9:16
    3. Add title text overlay (large, centered)
    4. Add color boost
    5. Save to /data/thumbnails/{job_id}_short_{i}_thumb.png
    6. Return path
    """
    try:
        import tempfile
        from engines.ffmpeg_engine import extract_best_frame, probe_video, smart_crop

        os.makedirs(THUMBNAIL_DIR, exist_ok=True)

        output_path = os.path.join(
            THUMBNAIL_DIR, f"{job_id}_short_{short_index}_thumb.png"
        )

        info = probe_video(video_path)
        duration = info["duration"]

        # Determine extraction timestamp
        hook_start = short_config.get("hook_start")
        if hook_start is not None:
            ts = float(hook_start)
        else:
            ts = duration * 0.25

        with tempfile.TemporaryDirectory() as tmpdir:
            # Extract frame at the hook moment
            raw_frame = os.path.join(tmpdir, "short_frame.png")
            try:
                subprocess.run(
                    [
                        "ffmpeg", "-y", "-ss", str(ts),
                        "-i", video_path,
                        "-frames:v", "1",
                        "-threads", "2",
                        raw_frame,
                    ],
                    capture_output=True, text=True, timeout=30,
                )
            except Exception:
                pass

            if not os.path.exists(raw_frame):
                logger.error("generate_short_thumbnail: frame extraction failed")
                return None

            # Smart-crop frame to 9:16 using a still image approach
            cropped_frame = os.path.join(tmpdir, "cropped_frame.png")
            w, h = info["width"], info["height"]

            # For a still image, apply the crop logic directly
            crop_w = int(h * 9 / 16)
            if crop_w > w:
                crop_w = w
            x_offset = (w - crop_w) // 2

            # Detect font
            font_path = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
            if not os.path.exists(font_path):
                font_path = "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf"
            font_arg = f":fontfile={font_path}" if os.path.exists(font_path) else ""

            safe_title = " ".join(title.split()[:5])
            safe_title = safe_title.replace("'", "\\'").replace(":", "\\:").replace('"', '\\"')

            vf_parts = [
                f"crop={crop_w}:{h}:{x_offset}:0",
                "scale=1080:1920",
                "eq=contrast=1.1:saturation=1.2",
                (
                    f"drawtext=text='{safe_title}'"
                    f"{font_arg}"
                    f":fontsize=90:fontcolor=white"
                    f":borderw=4:bordercolor=black"
                    f":x=(w-text_w)/2:y=(h-text_h)/2"
                ),
            ]
            vf = ",".join(vf_parts)

            _run([
                "ffmpeg", "-y", "-i", raw_frame,
                "-vf", vf,
                *ENCODE_OPTS,
                output_path,
            ], timeout=TIMEOUT)

        logger.info(f"generate_short_thumbnail: {output_path}")
        return output_path

    except Exception as e:
        logger.error(f"generate_short_thumbnail failed: {e}")
        return None


# ---------------------------------------------------------------------------
# generate_community_post_image  (NEW)
# ---------------------------------------------------------------------------

def generate_community_post_image(
    video_path: str,
    post_text: str,
    job_id: str,
    post_index: int,
    method: str = "frame",
) -> Optional[str]:
    """Generate an image for a community post.

    method="frame": Extract frame + text overlay (free, uses FFmpeg)
    method="ai": Generate via Replicate FLUX API (costs ~$0.03)
    Returns path to the generated image, or None on failure.
    """
    os.makedirs(THUMBNAIL_DIR, exist_ok=True)
    output_path = os.path.join(
        THUMBNAIL_DIR, f"{job_id}_community_{post_index}_{method}.png"
    )

    if method == "frame":
        return _community_image_from_frame(video_path, post_text, output_path)
    elif method == "ai":
        return _community_image_from_ai(post_text, output_path)
    else:
        logger.error(f"Unknown community image method: {method}")
        return None


def _community_image_from_frame(
    video_path: str, post_text: str, output_path: str
) -> Optional[str]:
    """Extract a visually interesting frame and overlay community post text."""
    try:
        import tempfile
        from engines.ffmpeg_engine import probe_video

        info = probe_video(video_path)
        duration = info["duration"]
        # Use frame at 40% for variety (different from thumbnail frames)
        ts = duration * 0.40

        with tempfile.TemporaryDirectory() as tmpdir:
            raw_frame = os.path.join(tmpdir, "community_frame.png")
            _run([
                "ffmpeg", "-y", "-ss", str(ts),
                "-i", video_path,
                "-frames:v", "1",
                "-threads", "2",
                raw_frame,
            ], timeout=30)

            if not os.path.exists(raw_frame):
                return None

            # Truncate text for overlay
            words = post_text.split()
            overlay_text = " ".join(words[:8])
            safe_text = overlay_text.replace("'", "\\'").replace(":", "\\:").replace('"', '\\"')

            font_path = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
            if not os.path.exists(font_path):
                font_path = "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf"
            font_arg = f":fontfile={font_path}" if os.path.exists(font_path) else ""

            vf_parts = [
                "scale=1200:675:force_original_aspect_ratio=decrease",
                "pad=1200:675:(ow-iw)/2:(oh-ih)/2",
                "eq=contrast=1.15:saturation=1.25:brightness=0.02",
                "drawbox=x=0:y=ih*0.65:w=iw:h=ih*0.35:color=black@0.6:t=fill",
                (
                    f"drawtext=text='{safe_text}'"
                    f"{font_arg}"
                    f":fontsize=48:fontcolor=white"
                    f":borderw=3:bordercolor=black"
                    f":x=(w-text_w)/2:y=ih*0.78"
                ),
            ]
            vf = ",".join(vf_parts)

            _run([
                "ffmpeg", "-y", "-i", raw_frame,
                "-vf", vf,
                *ENCODE_OPTS,
                output_path,
            ], timeout=TIMEOUT)

        logger.info(f"Community post image (frame): {output_path}")
        return output_path

    except Exception as e:
        logger.error(f"Community image from frame failed: {e}")
        return None


def _community_image_from_ai(post_text: str, output_path: str) -> Optional[str]:
    """Generate community post image using Replicate FLUX."""
    try:
        import replicate
        import httpx as _httpx

        # Build a prompt from the post text
        prompt = (
            f"Professional YouTube community post image. "
            f"Topic: {post_text[:200]}. "
            f"Style: clean, modern, eye-catching social media graphic. "
            f"No text in the image. Vibrant colors, high contrast."
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

        # Download the generated image
        if output and len(output) > 0:
            img_url = str(output[0])
            resp = _httpx.get(img_url, timeout=60)
            resp.raise_for_status()
            with open(output_path, "wb") as f:
                f.write(resp.content)
            logger.info(f"Community post image (AI): {output_path}")
            return output_path

        return None

    except ImportError:
        logger.warning("replicate package not installed, skipping AI image generation")
        return None
    except Exception as e:
        logger.error(f"Community image from AI failed: {e}")
        return None
