"""
HeyGen Avatar Video Generation Engine.

Creates talking-head videos from scripts using HeyGen's Avatar IV API.
Supports digital twin avatars (cloned from your likeness) and stock avatars.

Flow:
    1. Submit script + avatar_id to HeyGen API
    2. Poll for completion (async generation, ~10 min per 1 min of video)
    3. Download the finished MP4
    4. Return local path → feeds into existing edit/short/publish pipeline

Setup:
    1. Sign up at heygen.com, get API key
    2. Create your Digital Twin avatar in HeyGen's web UI
    3. Set HEYGEN_API_KEY env var
    4. Use list_avatars() to find your avatar_id

Usage:
    from engines.heygen import create_avatar_video, list_avatars

    avatars = list_avatars()
    video_path = create_avatar_video(
        script="Welcome to my channel. Today we're talking about...",
        avatar_id="your_avatar_id",
        job_id="abc123",
    )
"""
import json
import logging
import os
import time
from typing import Dict, List, Optional

import httpx

logger = logging.getLogger(__name__)

HEYGEN_API_KEY = os.environ.get("HEYGEN_API_KEY", "")
HEYGEN_BASE_URL = "https://api.heygen.com"
DATA_DIR = os.environ.get("DATA_DIR", "/opt/yt-editor/data")
POLL_INTERVAL = 15  # seconds between status checks
MAX_POLL_TIME = 1800  # 30 min max wait for video generation
DEFAULT_VOICE_ID = None  # Set after cloning your voice in HeyGen


def _headers() -> dict:
    """Build HeyGen API headers."""
    if not HEYGEN_API_KEY:
        raise RuntimeError("HEYGEN_API_KEY not set")
    return {
        "X-Api-Key": HEYGEN_API_KEY,
        "Content-Type": "application/json",
        "Accept": "application/json",
    }


def list_avatars() -> List[dict]:
    """List available avatars from HeyGen account.

    Returns list of {avatar_id, avatar_name, preview_image_url, type}.
    Types: "public" (stock), "private" (your clones/digital twins).
    """
    try:
        resp = httpx.get(
            f"{HEYGEN_BASE_URL}/v2/avatars",
            headers=_headers(),
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json().get("data", {})

        avatars = []
        for avatar in data.get("avatars", []):
            avatars.append({
                "avatar_id": avatar.get("avatar_id"),
                "avatar_name": avatar.get("avatar_name", "Unknown"),
                "preview_image_url": avatar.get("preview_image_url"),
                "type": "private" if avatar.get("is_private") else "public",
            })

        logger.info(f"HeyGen: Found {len(avatars)} avatars")
        return avatars

    except Exception as e:
        logger.error(f"HeyGen list_avatars failed: {e}")
        raise


def list_voices() -> List[dict]:
    """List available voices from HeyGen account.

    Returns list of {voice_id, name, language, gender, preview_audio}.
    """
    try:
        resp = httpx.get(
            f"{HEYGEN_BASE_URL}/v2/voices",
            headers=_headers(),
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json().get("data", {})

        voices = []
        for voice in data.get("voices", []):
            voices.append({
                "voice_id": voice.get("voice_id"),
                "name": voice.get("name", "Unknown"),
                "language": voice.get("language", "en"),
                "gender": voice.get("gender"),
                "preview_audio": voice.get("preview_audio"),
            })

        logger.info(f"HeyGen: Found {len(voices)} voices")
        return voices

    except Exception as e:
        logger.error(f"HeyGen list_voices failed: {e}")
        raise


def create_avatar_video(
    script: str,
    avatar_id: str,
    job_id: str,
    voice_id: Optional[str] = None,
    title: Optional[str] = None,
    dimension: str = "landscape",  # "landscape" (16:9) or "portrait" (9:16)
    test_mode: bool = False,
) -> str:
    """Generate an avatar video from a script using HeyGen API.

    Args:
        script: The text the avatar will speak.
        avatar_id: HeyGen avatar ID (from list_avatars).
        job_id: Internal job ID for file naming.
        voice_id: HeyGen voice ID. If None, uses avatar's default voice.
        title: Optional video title (for HeyGen's internal naming).
        dimension: "landscape" for 16:9, "portrait" for 9:16 Shorts.
        test_mode: If True, generates a shorter/cheaper test video.

    Returns:
        Local file path of the downloaded MP4.

    Raises:
        RuntimeError: If generation fails or times out.
    """
    if not HEYGEN_API_KEY:
        raise RuntimeError("HEYGEN_API_KEY not set — get one at heygen.com")

    # ── Build video generation request ────────────────────────────────────
    dimension_config = {
        "landscape": {"width": 1920, "height": 1080},
        "portrait": {"width": 1080, "height": 1920},
    }
    dims = dimension_config.get(dimension, dimension_config["landscape"])

    # Build the script input for HeyGen
    voice_config = {"type": "text", "input_text": script}
    if voice_id:
        voice_config["voice_id"] = voice_id

    payload = {
        "video_inputs": [
            {
                "character": {
                    "type": "avatar",
                    "avatar_id": avatar_id,
                    "avatar_style": "normal",
                },
                "voice": voice_config,
            }
        ],
        "dimension": dims,
        "test": test_mode,
    }

    if title:
        payload["title"] = title

    logger.info(f"HeyGen: Submitting video generation for job {job_id} "
                f"(avatar={avatar_id}, {dimension}, {len(script)} chars)")

    # ── Submit generation request ─────────────────────────────────────────
    try:
        resp = httpx.post(
            f"{HEYGEN_BASE_URL}/v2/video/generate",
            headers=_headers(),
            json=payload,
            timeout=60,
        )
        resp.raise_for_status()
        result = resp.json()

        video_id = result.get("data", {}).get("video_id")
        if not video_id:
            raise RuntimeError(f"HeyGen: No video_id in response: {result}")

        logger.info(f"HeyGen: Video submitted, id={video_id}")

    except httpx.HTTPStatusError as e:
        error_body = e.response.text[:500]
        raise RuntimeError(f"HeyGen API error ({e.response.status_code}): {error_body}")

    # ── Poll for completion ───────────────────────────────────────────────
    output_path = os.path.join(DATA_DIR, "inbox", f"{job_id}_heygen.mp4")
    os.makedirs(os.path.dirname(output_path), exist_ok=True)

    start_time = time.time()
    while time.time() - start_time < MAX_POLL_TIME:
        time.sleep(POLL_INTERVAL)

        try:
            status_resp = httpx.get(
                f"{HEYGEN_BASE_URL}/v1/video_status.get",
                params={"video_id": video_id},
                headers=_headers(),
                timeout=30,
            )
            status_resp.raise_for_status()
            status_data = status_resp.json().get("data", {})
            status = status_data.get("status")

            elapsed = int(time.time() - start_time)
            logger.info(f"HeyGen: video={video_id} status={status} ({elapsed}s elapsed)")

            if status == "completed":
                video_url = status_data.get("video_url")
                if not video_url:
                    raise RuntimeError("HeyGen: completed but no video_url")

                # Download the video
                _download_video(video_url, output_path)
                logger.info(f"HeyGen: Video downloaded to {output_path}")
                return output_path

            elif status == "failed":
                error = status_data.get("error", "Unknown error")
                raise RuntimeError(f"HeyGen generation failed: {error}")

            elif status in ("processing", "pending", "waiting"):
                continue  # Still working

            else:
                logger.warning(f"HeyGen: Unknown status '{status}', continuing to poll")

        except httpx.HTTPError as e:
            logger.warning(f"HeyGen: Poll request failed ({e}), retrying...")
            continue

    raise RuntimeError(f"HeyGen: Timed out after {MAX_POLL_TIME}s waiting for video {video_id}")


def _download_video(url: str, output_path: str) -> None:
    """Download video from URL to local file."""
    with httpx.stream("GET", url, timeout=300, follow_redirects=True) as stream:
        stream.raise_for_status()
        with open(output_path, "wb") as f:
            for chunk in stream.iter_bytes(chunk_size=8192):
                f.write(chunk)

    size = os.path.getsize(output_path)
    if size < 1000:
        raise RuntimeError(f"HeyGen: Downloaded file too small ({size} bytes)")
    logger.info(f"HeyGen: Downloaded {size / 1024 / 1024:.1f}MB to {output_path}")


def create_avatar_short(
    script: str,
    avatar_id: str,
    job_id: str,
    short_index: int,
    voice_id: Optional[str] = None,
) -> str:
    """Generate a portrait (9:16) avatar video for YouTube Shorts.

    Convenience wrapper around create_avatar_video with portrait dimensions.
    """
    return create_avatar_video(
        script=script,
        avatar_id=avatar_id,
        job_id=f"{job_id}_short_{short_index}",
        voice_id=voice_id,
        dimension="portrait",
    )
