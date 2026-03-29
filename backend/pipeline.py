import os
import re
import json
import subprocess
import time
import logging
from pathlib import Path
from urllib.parse import urlparse

import httpx

# ─── Configuration ───

DATA_DIR = os.environ.get("DATA_DIR", "/opt/yt-editor/data")
METADATA_DIR = os.path.join(DATA_DIR, "metadata")
ASSETS_DIR = "/opt/yt-editor/backend/assets"

logger = logging.getLogger("yt-pipeline")

ALLOWED_DOMAINS = {
    "www.loom.com", "loom.com",
    "www.youtube.com", "youtube.com", "youtu.be",
    "vimeo.com", "www.vimeo.com",
    "drive.google.com",
}
MAX_RETRIES = 3
RETRY_BACKOFF = [2, 5, 10]


# ─── Retry Helper (preserved from v5) ───

def retry_on_transient(fn, retries=MAX_RETRIES, label="operation"):
    import anthropic
    last_error = None
    for attempt in range(retries):
        try:
            return fn()
        except (httpx.TimeoutException, httpx.HTTPStatusError, ConnectionError,
                TimeoutError) as e:
            last_error = e
            if isinstance(e, httpx.HTTPStatusError) and e.response.status_code < 500:
                raise
            wait = RETRY_BACKOFF[min(attempt, len(RETRY_BACKOFF) - 1)]
            logger.warning(f"{label} failed (attempt {attempt+1}/{retries}): {e}. Retrying in {wait}s...")
            time.sleep(wait)
        except (anthropic.RateLimitError,) as e:
            last_error = e
            wait = RETRY_BACKOFF[min(attempt, len(RETRY_BACKOFF) - 1)]
            logger.warning(f"{label} rate limited (attempt {attempt+1}/{retries}). Retrying in {wait}s...")
            time.sleep(wait)
    raise Exception(f"{label} failed after {retries} retries: {last_error}")


def validate_video_url(url: str) -> str:
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise ValueError(f"Invalid URL scheme: {parsed.scheme}")
    video_extensions = (".mp4", ".mov", ".avi", ".mkv", ".webm")
    is_known_domain = parsed.hostname in ALLOWED_DOMAINS
    is_direct_video = any(parsed.path.lower().endswith(ext) for ext in video_extensions)
    if not is_known_domain and not is_direct_video:
        logger.info(f"Non-standard video domain: {parsed.hostname}, will attempt yt-dlp")
    return url


def run_subprocess(cmd: list, timeout: int = 300, check: bool = True, label: str = "subprocess"):
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    if check and result.returncode != 0:
        raise subprocess.CalledProcessError(result.returncode, cmd, result.stdout, result.stderr)
    return result


# ─── Download Video (preserved from v5) ───

def download_video_from_url(video_url: str, job_id: str) -> str:
    video_url = validate_video_url(video_url)
    outpath = os.path.join(DATA_DIR, "inbox", f"{job_id}.mp4")
    os.makedirs(os.path.dirname(outpath), exist_ok=True)

    parsed = urlparse(video_url)
    is_loom = parsed.hostname in ("www.loom.com", "loom.com")
    is_direct = any(parsed.path.lower().endswith(ext) for ext in (".mp4", ".mov", ".avi", ".mkv", ".webm"))

    if is_direct:
        def download_direct():
            with httpx.stream("GET", video_url, timeout=300, follow_redirects=True) as stream:
                stream.raise_for_status()
                with open(outpath, "wb") as f:
                    for chunk in stream.iter_bytes(chunk_size=8192):
                        f.write(chunk)
        retry_on_transient(download_direct, label="Direct video download")
    elif is_loom:
        def fetch_page():
            resp = httpx.get(video_url, follow_redirects=True, timeout=30)
            resp.raise_for_status()
            return resp.text
        html = retry_on_transient(fetch_page, label="Loom page fetch")
        extracted_url = None
        patterns = [
            r'"url":"(https://[^"]*\.mp4[^"]*)"',
            r'"transcoded_url":"(https://[^"]*\.mp4[^"]*)"',
            r'source src="(https://[^"]*\.mp4[^"]*)"',
        ]
        for pattern in patterns:
            match = re.search(pattern, html)
            if match:
                extracted_url = match.group(1).replace("\\", "")
                break
        if extracted_url:
            def download_extracted():
                with httpx.stream("GET", extracted_url, timeout=300) as stream:
                    stream.raise_for_status()
                    with open(outpath, "wb") as f:
                        for chunk in stream.iter_bytes(chunk_size=8192):
                            f.write(chunk)
            retry_on_transient(download_extracted, label="Loom video download")
        else:
            run_subprocess(["yt-dlp", "-o", outpath, "--", video_url], timeout=300, label="yt-dlp download")
    else:
        run_subprocess(["yt-dlp", "-o", outpath, "--", video_url], timeout=600, label="yt-dlp download")

    if not os.path.exists(outpath) or os.path.getsize(outpath) < 1000:
        raise Exception("Download failed: file too small or missing")
    logger.info(f"Job {job_id}: Downloaded {os.path.getsize(outpath)} bytes")
    return outpath


# ═══════════════════════════════════════════════════════════════════════════════
#  V7 PIPELINE ORCHESTRATOR
#  - Checkpoint/resume: each step checks for existing output before running
#  - Long-form caption burning (new step after execute_edits)
#  - Community post image generation (new step after thumbnails)
#  - Auto-publish mode: uploads to YouTube after QA passes
#  Agents communicate via JSON files in METADATA_DIR.
# ═══════════════════════════════════════════════════════════════════════════════

AUTO_PUBLISH = os.environ.get("AUTO_PUBLISH", "true").lower() in ("true", "1", "yes")

from validation import (
    validate_intake_result, validate_edit_plan,
    validate_short_designs, validate_package_result, validate_qa_result,
)


def _load_checkpoint(job_id: str, step_name: str):
    """Load checkpoint JSON if it exists and is valid."""
    path = os.path.join(METADATA_DIR, f"{job_id}_{step_name}.json")
    if os.path.exists(path):
        try:
            with open(path) as f:
                data = json.load(f)
            if data:
                logger.info(f"Job {job_id}: Resuming from checkpoint: {step_name}")
                return data
        except (json.JSONDecodeError, OSError) as e:
            logger.warning(f"Job {job_id}: Corrupt checkpoint {step_name}, re-running: {e}")
    return None


def _save_checkpoint(job_id: str, step_name: str, data):
    """Save step output as checkpoint JSON."""
    os.makedirs(METADATA_DIR, exist_ok=True)
    path = os.path.join(METADATA_DIR, f"{job_id}_{step_name}.json")
    with open(path, "w") as f:
        json.dump(data, f, indent=2, default=str)


def _validate_asset(path: str) -> bool:
    """Check if a video asset file is valid (exists, reasonable size, probes OK)."""
    if not path or not os.path.exists(path):
        return False
    if os.path.getsize(path) < 5000:  # Less than 5KB is suspicious
        logger.warning(f"Asset too small ({os.path.getsize(path)} bytes): {path}")
        return False
    try:
        from engines.ffmpeg_engine import probe_video
        info = probe_video(path)
        dur = float(info.get("format", {}).get("duration", 0))
        if dur < 0.5:
            logger.warning(f"Asset too short ({dur}s): {path}")
            return False
        return True
    except Exception:
        logger.warning(f"Asset failed probe: {path}")
        return False


def _build_transcript_text(transcript_data: dict) -> str:
    """Build formatted transcript string for agents."""
    text = ""
    for seg in transcript_data.get("segments", []):
        text += f"[{seg.get('start', 0):.1f}s - {seg.get('end', 0):.1f}s] {seg.get('text', '').strip()}\n"
    if not text:
        text = transcript_data.get("text", "")
    return text


def run_pipeline_v7(job_id: str, video_source: str, update_fn, is_file: bool = False, extras: dict = None):
    """v7 pipeline orchestrator with checkpoint/resume, captions, and auto-publish."""
    extras = extras or {}

    os.makedirs(METADATA_DIR, exist_ok=True)
    import traceback as _tb

    # ── Step 1: Download ──────────────────────────────────────────────────────
    video_path = os.path.join(DATA_DIR, "inbox", f"{job_id}.mp4")
    if is_file:
        video_path = video_source
        update_fn("download", "complete")
    elif os.path.exists(video_path) and os.path.getsize(video_path) > 1000:
        logger.info(f"Job {job_id}: Download checkpoint found, skipping")
        update_fn("download", "complete")
    else:
        update_fn("download", "running")
        video_path = download_video_from_url(video_source, job_id)
        update_fn("download", "complete")

    # ── Step 2: Transcribe ────────────────────────────────────────────────────
    checkpoint = _load_checkpoint(job_id, "transcript")
    if checkpoint:
        transcript_data = checkpoint
        update_fn("transcribe", "complete")
    else:
        update_fn("transcribe", "running")
        from engines.transcription import transcribe_video
        transcript_data = transcribe_video(video_path, job_id)
        _save_checkpoint(job_id, "transcript", transcript_data)
        update_fn("transcribe", "complete")
    transcript_text = _build_transcript_text(transcript_data)

    # ── Step 3: Video Analysis (type detection + silence) ─────────────────────
    checkpoint = _load_checkpoint(job_id, "analysis")
    if checkpoint:
        analysis = checkpoint
        video_info = analysis["video_info"]
        original_duration = analysis["original_duration"]
        video_type_info = analysis["video_type"]
        silence_segments = analysis["silence_segments"]
        update_fn("analyze", "complete")
    else:
        update_fn("analyze", "running")
        from engines.ffmpeg_engine import probe_video, detect_video_type, detect_silence
        video_info = probe_video(video_path)
        original_duration = float(video_info.get("format", {}).get("duration", 0))
        video_type_info = detect_video_type(video_path)
        silence_segments = detect_silence(video_path)
        analysis = {
            "video_info": video_info,
            "video_type": video_type_info,
            "silence_segments": silence_segments,
            "original_duration": original_duration,
        }
        _save_checkpoint(job_id, "analysis", analysis)
        logger.info(f"Job {job_id}: Video type: {video_type_info.get('type', 'unknown')}, "
                    f"Duration: {original_duration:.1f}s, Silences: {len(silence_segments)}")
        update_fn("analyze", "complete")

    # ── Step 4: Intake Agent ──────────────────────────────────────────────────
    checkpoint = _load_checkpoint(job_id, "intake")
    if checkpoint:
        intake_result = checkpoint
        update_fn("intake", "complete")
    else:
        update_fn("intake", "running")
        from agents.intake import run_intake_agent
        intake_result = run_intake_agent(transcript_text, silence_segments, video_info, job_id)
        intake_result = validate_intake_result(intake_result)
        _save_checkpoint(job_id, "intake", intake_result)
        logger.info(f"Job {job_id}: Intake complete — {len(intake_result.get('filler_words', []))} fillers, "
                    f"rating: {intake_result.get('content_rating', '?')}/10")
        update_fn("intake", "complete")

    # ── Step 5: Editor Agent ──────────────────────────────────────────────────
    checkpoint = _load_checkpoint(job_id, "edit_plan")
    if checkpoint:
        edit_plan = checkpoint
        update_fn("edit_plan", "complete")
    else:
        update_fn("edit_plan", "running")
        from agents.editor import run_editor_agent
        edit_plan = run_editor_agent(intake_result, transcript_text, video_info, job_id)
        edit_plan = validate_edit_plan(edit_plan)
        _save_checkpoint(job_id, "edit_plan", edit_plan)
        update_fn("edit_plan", "complete")

    # ── Step 6: Execute Edits (FFmpeg) ────────────────────────────────────────
    # Check for existing edited video
    final_edited_path = os.path.join(DATA_DIR, "edited", f"{job_id}_final.mp4")
    captioned_lf_path = os.path.join(DATA_DIR, "edited", f"{job_id}_captioned.mp4")
    if os.path.exists(captioned_lf_path) and os.path.getsize(captioned_lf_path) > 1000:
        edited_path = captioned_lf_path
        from engines.ffmpeg_engine import probe_video
        edited_duration_info = probe_video(edited_path)
        edited_duration = float(edited_duration_info.get("format", {}).get("duration", original_duration))
        update_fn("execute_edits", "complete")
        update_fn("caption_longform", "complete")
    elif os.path.exists(final_edited_path) and os.path.getsize(final_edited_path) > 1000:
        edited_path = final_edited_path
        from engines.ffmpeg_engine import probe_video
        edited_duration_info = probe_video(edited_path)
        edited_duration = float(edited_duration_info.get("format", {}).get("duration", original_duration))
        update_fn("execute_edits", "complete")
        # Still need to burn captions on long-form
        update_fn("caption_longform", "running")
        from engines.ffmpeg_engine import burn_captions_longform
        words = transcript_data.get("words", [])
        result = burn_captions_longform(edited_path, words, captioned_lf_path)
        if result:
            edited_path = result
            logger.info(f"Job {job_id}: Long-form captions burned")
        else:
            logger.warning(f"Job {job_id}: Long-form caption burn failed, using uncaptioned")
        update_fn("caption_longform", "complete")
    else:
        update_fn("execute_edits", "running")
        from engines.ffmpeg_engine import (
            remove_segments, add_text_overlays, normalize_audio,
            concat_with_intro_outro, probe_video
        )

        edited_path = video_path
        os.makedirs(os.path.join(DATA_DIR, "edited"), exist_ok=True)

        # 6a: Remove filler words and dead air
        cut_segments = edit_plan.get("cut_segments", [])
        if cut_segments:
            try:
                segments_to_remove = [{"start": s["start"], "end": s["end"]} for s in cut_segments]
                cleaned_path = os.path.join(DATA_DIR, "edited", f"{job_id}_cleaned.mp4")
                result = remove_segments(video_path, segments_to_remove, cleaned_path)
                if result:
                    edited_path = result
                logger.info(f"Job {job_id}: Removed {len(segments_to_remove)} segments")
            except Exception as e:
                logger.error(f"Job {job_id}: remove_segments failed: {e}\n{_tb.format_exc()}")
                edited_path = video_path

        # 6b: Add text overlays
        overlays = edit_plan.get("text_overlays", [])
        if overlays and edited_path:
            try:
                overlay_path = os.path.join(DATA_DIR, "edited", f"{job_id}_overlay.mp4")
                result = add_text_overlays(edited_path, overlays, overlay_path)
                if result:
                    edited_path = result
                logger.info(f"Job {job_id}: Added {len(overlays)} text overlays")
            except Exception as e:
                logger.error(f"Job {job_id}: add_text_overlays failed: {e}\n{_tb.format_exc()}")

        # 6c: Normalize audio
        try:
            norm_path = os.path.join(DATA_DIR, "edited", f"{job_id}_normalized.mp4")
            result = normalize_audio(edited_path, norm_path)
            if result:
                edited_path = result
            logger.info(f"Job {job_id}: Audio normalized")
        except Exception as e:
            logger.error(f"Job {job_id}: normalize_audio failed: {e}\n{_tb.format_exc()}")

        # 6d: Add intro/outro (with validation)
        intro_path = os.path.join(ASSETS_DIR, "intro.mp4") if os.path.exists(os.path.join(ASSETS_DIR, "intro.mp4")) else os.path.join(ASSETS_DIR, "intro_default.mp4")
        outro_path = os.path.join(ASSETS_DIR, "outro.mp4") if os.path.exists(os.path.join(ASSETS_DIR, "outro.mp4")) else os.path.join(ASSETS_DIR, "outro_default.mp4")
        if _validate_asset(intro_path) and _validate_asset(outro_path):
            try:
                result = concat_with_intro_outro(edited_path, intro_path, outro_path, final_edited_path)
                if result:
                    edited_path = result
                logger.info(f"Job {job_id}: Intro/outro added")
            except Exception as e:
                logger.error(f"Job {job_id}: concat_with_intro_outro failed: {e}\n{_tb.format_exc()}")
        else:
            logger.info(f"Job {job_id}: Skipping intro/outro (assets not valid)")

        edited_duration_info = probe_video(edited_path)
        edited_duration = float(edited_duration_info.get("format", {}).get("duration", original_duration))
        logger.info(f"Job {job_id}: Edits complete — {original_duration:.1f}s -> {edited_duration:.1f}s "
                    f"({original_duration - edited_duration:.1f}s removed)")
        update_fn("execute_edits", "complete")

        # ── Step 6.5: Burn captions on long-form video ───────────────────────
        update_fn("caption_longform", "running")
        from engines.ffmpeg_engine import burn_captions_longform
        words = transcript_data.get("words", [])
        result = burn_captions_longform(edited_path, words, captioned_lf_path)
        if result:
            edited_path = result
            logger.info(f"Job {job_id}: Long-form captions burned ({len(words)} words)")
        else:
            logger.warning(f"Job {job_id}: Long-form caption burn failed, using uncaptioned")
        update_fn("caption_longform", "complete")

    # ── Step 7: Short Creator Agent ───────────────────────────────────────────
    checkpoint = _load_checkpoint(job_id, "short_designs")
    if checkpoint:
        short_designs = checkpoint
        update_fn("short_design", "complete")
    else:
        update_fn("short_design", "running")
        from agents.short_creator import run_short_creator_agent
        short_designs = run_short_creator_agent(transcript_text, intake_result, edited_duration, job_id)
        short_designs = validate_short_designs(short_designs)
        _save_checkpoint(job_id, "short_designs", short_designs)
        logger.info(f"Job {job_id}: Designed {len(short_designs)} shorts")
        update_fn("short_design", "complete")

    # ── Step 8: Create Shorts (FFmpeg) ────────────────────────────────────────
    update_fn("short_creation", "running")
    from engines.ffmpeg_engine import create_short_with_restructure, burn_captions_animated, concat_short_with_bumpers

    short_paths = []
    os.makedirs(os.path.join(DATA_DIR, "shorts"), exist_ok=True)

    for i, design in enumerate(short_designs):
        # Check for existing final short
        existing_final = os.path.join(DATA_DIR, "shorts", f"{job_id}_short_{i}_final.mp4")
        existing_captioned = os.path.join(DATA_DIR, "shorts", f"{job_id}_short_{i}_captioned.mp4")
        if os.path.exists(existing_final) and os.path.getsize(existing_final) > 1000:
            short_paths.append(existing_final)
            continue
        if os.path.exists(existing_captioned) and os.path.getsize(existing_captioned) > 1000:
            short_paths.append(existing_captioned)
            continue

        try:
            raw_short_path = os.path.join(DATA_DIR, "shorts", f"{job_id}_short_{i}_raw.mp4")
            result = create_short_with_restructure(video_path, design, raw_short_path, video_type_info)
            if not result:
                logger.error(f"Job {job_id}: Short {i} creation failed")
                continue

            short_words = [w for w in transcript_data.get("words", [])
                          if w.get("start", 0) >= design["start"] and w.get("end", 0) <= design["end"]]

            captioned_path = os.path.join(DATA_DIR, "shorts", f"{job_id}_short_{i}_captioned.mp4")
            result = burn_captions_animated(raw_short_path, short_words, captioned_path)
            final_short = result if result else raw_short_path

            short_intro = os.path.join(ASSETS_DIR, "short_intro.mp4")
            short_outro = os.path.join(ASSETS_DIR, "short_outro.mp4")
            has_intro = _validate_asset(short_intro)
            has_outro = _validate_asset(short_outro)
            if has_intro or has_outro:
                bumper_path = os.path.join(DATA_DIR, "shorts", f"{job_id}_short_{i}_final.mp4")
                si = short_intro if has_intro else None
                so = short_outro if has_outro else None
                result = concat_short_with_bumpers(final_short, si, so, bumper_path)
                if result:
                    final_short = result

            short_paths.append(final_short)
        except Exception as e:
            logger.error(f"Job {job_id}: Short {i} creation failed: {e}", exc_info=True)
            continue

    logger.info(f"Job {job_id}: Created {len(short_paths)}/{len(short_designs)} shorts")
    update_fn("short_creation", "complete")

    # ── Step 9: Packager Agent (SEO + Community Posts) ────────────────────────
    checkpoint = _load_checkpoint(job_id, "package")
    if checkpoint:
        package_result = checkpoint
        update_fn("packaging", "complete")
    else:
        update_fn("packaging", "running")
        from agents.packager import run_packager_agent
        package_result = run_packager_agent(transcript_text, intake_result, short_designs, job_id, extras=extras)
        package_result = validate_package_result(package_result)
        _save_checkpoint(job_id, "package", package_result)
        update_fn("packaging", "complete")

    # ── Step 10: Thumbnail (single high-converting) ──────────────────────────
    update_fn("thumbnail_gen", "running")
    from engines.thumbnail import (
        generate_single_thumbnail, generate_short_thumbnail,
    )

    long_form_seo = package_result.get("long_form", {})
    thumbnail_headlines = long_form_seo.get("thumbnail_headlines", [])
    topic_summary = long_form_seo.get("title", "Video content")
    title_variants = long_form_seo.get("title_variants", [topic_summary])

    # Pick the single strongest headline (packager lists them in priority order)
    best_headline = thumbnail_headlines[0] if thumbnail_headlines else topic_summary

    single_thumb = generate_single_thumbnail(video_path, best_headline, topic_summary, job_id)
    long_form_thumbs = [single_thumb] if single_thumb else []

    short_thumbs = []
    shorts_seo = package_result.get("shorts", [])
    for i, design in enumerate(short_designs):
        if i < len(short_paths):
            thumb_text = (shorts_seo[i].get("thumbnail_text", design.get("title", ""))
                         if i < len(shorts_seo) else design.get("title", ""))
            thumb = generate_short_thumbnail(short_paths[i], design, thumb_text, job_id, i)
            short_thumbs.append(thumb)

    update_fn("thumbnail_gen", "complete")

    # ── Step 10.5: Community Post Images ──────────────────────────────────────
    update_fn("community_images", "running")
    from engines.thumbnail import generate_community_post_image
    community_posts = package_result.get("community_posts", [])
    for i, post in enumerate(community_posts):
        try:
            # Frame-based image
            frame_img = generate_community_post_image(
                video_path, post.get("text", ""), job_id, i, method="frame"
            )
            if frame_img:
                post["frame_image"] = frame_img

            # AI-generated image (if Replicate key available)
            if os.environ.get("REPLICATE_API_TOKEN"):
                ai_img = generate_community_post_image(
                    video_path, post.get("text", ""), job_id, i, method="ai"
                )
                if ai_img:
                    post["ai_image"] = ai_img
        except Exception as e:
            logger.warning(f"Job {job_id}: Community post {i} image failed: {e}")
    update_fn("community_images", "complete")

    # ── Step 11: QA Review ────────────────────────────────────────────────────
    update_fn("qa_review", "running")
    from agents.qa import run_qa_agent
    qa_result = run_qa_agent(short_designs, package_result, transcript_text, job_id)
    qa_result = validate_qa_result(qa_result)

    flagged = qa_result.get("flagged_shorts", [])
    if flagged:
        logger.info(f"Job {job_id}: QA flagged shorts at indices: {flagged}")

    update_fn("qa_review", "complete")

    # ── Build result ──────────────────────────────────────────────────────────
    result = {
        "video_path": edited_path,
        "short_paths": short_paths,
        "short_designs": short_designs,
        "seo_data": package_result,
        "thumbnail_paths": long_form_thumbs,
        "thumbnail_data": {
            "long_form": long_form_thumbs,
            "shorts": [[t] if t else [] for t in short_thumbs],
        },
        "short_thumbnail_paths": short_thumbs,
        "qa_scores": qa_result,
        "community_posts": community_posts,
        "filler_count": len(intake_result.get("filler_words", [])),
        "transcript": transcript_data,
        "video_type": video_type_info,
        "original_duration": original_duration,
        "edited_duration": edited_duration,
        "title_variants": title_variants,
        "intake_result": intake_result,
        "edit_plan": edit_plan,
        "captioned_longform": edited_path,
        "extras": extras,
    }

    # ── Step 12: Auto-Publish ─────────────────────────────────────────────────
    # ── Step 12a: Community Post Automation ────────────────────────────────────
    if AUTO_PUBLISH and community_posts:
        update_fn("community_posts", "running")
        try:
            from engines.community_poster import post_community_updates
            post_results = post_community_updates(community_posts)
            posted_count = sum(1 for r in post_results if r.get("status") == "posted")
            logger.info(f"Job {job_id}: Community posts: {posted_count}/{len(community_posts)} posted")
            result["community_post_results"] = post_results
        except ImportError:
            logger.info(f"Job {job_id}: Community poster not available (playwright not installed)")
            result["community_post_results"] = []
        except Exception as e:
            logger.warning(f"Job {job_id}: Community post automation failed: {e}")
            result["community_post_results"] = []
        update_fn("community_posts", "complete")

    if AUTO_PUBLISH:
        qa_passed = qa_result.get("verdict", "").upper() == "PASS" or qa_result.get("passed", False)
        if qa_passed:
            update_fn("auto_publish", "running")
            try:
                publish_result = _auto_publish(job_id, result, update_fn)
                result["auto_published"] = True
                result["youtube_video_id"] = publish_result.get("video_id")
                result["youtube_short_ids"] = publish_result.get("short_ids", [])
                logger.info(f"Job {job_id}: Auto-published! Video: {publish_result.get('video_id')}")
                update_fn("auto_publish", "complete")
            except Exception as e:
                logger.error(f"Job {job_id}: Auto-publish failed: {e}\n{_tb.format_exc()}")
                result["auto_published"] = False
                result["auto_publish_error"] = str(e)
                update_fn("auto_publish", "failed")
        else:
            logger.info(f"Job {job_id}: QA did not pass, skipping auto-publish")
            result["auto_published"] = False
            result["auto_publish_skip_reason"] = "QA did not pass"

    return result


def _auto_publish(job_id: str, result: dict, update_fn) -> dict:
    """Upload long-form video + shorts + thumbnails to YouTube."""
    from youtube_auth import get_youtube_service, upload_video, upload_thumbnail

    yt = get_youtube_service()
    if not yt:
        raise Exception("YouTube not authenticated — cannot auto-publish")

    seo = result.get("seo_data", {})
    long_form_seo = seo.get("long_form", {})
    shorts_seo = seo.get("shorts", [])
    thumbnail_data = result.get("thumbnail_data", {"long_form": [], "shorts": []})

    # Resolve title
    title_variants = result.get("title_variants", [])
    if not title_variants:
        title_variants = long_form_seo.get("title_variants",
                         [long_form_seo.get("title", f"Video {job_id}")])
    chosen_title = (title_variants[0] if title_variants else f"Video {job_id}")[:100]  # YouTube max 100 chars

    # Build long-form description with custom desc + template
    extras = result.get("extras", {})
    lf_description = long_form_seo.get("description", "")
    custom_desc = extras.get("custom_description", "")
    desc_template = extras.get("description_template", "")
    if custom_desc:
        lf_description = f"{custom_desc}\n\n{lf_description}"
    if desc_template and desc_template not in lf_description:
        lf_description = f"{lf_description}\n\n{desc_template}"

    # Upload long-form
    video_response = retry_on_transient(
        lambda: upload_video(
            filepath=result["video_path"],
            title=chosen_title,
            description=lf_description,
            tags=long_form_seo.get("tags", []),
            privacy="private",
        ),
        label="YouTube long-form upload",
    )
    video_id = video_response.get("id")
    logger.info(f"Job {job_id}: Long-form uploaded: {video_id}")

    # Upload long-form thumbnail
    long_thumbs = thumbnail_data.get("long_form", [])
    if long_thumbs:
        try:
            retry_on_transient(
                lambda: upload_thumbnail(video_id, long_thumbs[0]),
                label="YouTube long-form thumbnail",
            )
        except Exception as e:
            logger.warning(f"Job {job_id}: Long-form thumbnail upload failed: {e}")

    # Upload shorts — inject main video link into each Short's description
    short_ids = []
    short_thumbs_data = thumbnail_data.get("shorts", [])
    main_video_url = f"https://www.youtube.com/watch?v={video_id}" if video_id else ""
    extras = result.get("extras", {})
    desc_template = extras.get("description_template", "")

    for i, short_path in enumerate(result.get("short_paths", [])):
        short_seo = shorts_seo[i] if i < len(shorts_seo) else {}
        short_title = short_seo.get("title", f"Short {i+1} from {chosen_title}")[:100]
        short_desc = short_seo.get("description", "")

        # Inject main video link at the top of each Short description
        if main_video_url and main_video_url not in short_desc:
            short_desc = f"Watch the full video: {main_video_url}\n\n{short_desc}"

        # Append description template if provided
        if desc_template and desc_template not in short_desc:
            short_desc = f"{short_desc}\n\n{desc_template}"

        short_tags = short_seo.get("tags", long_form_seo.get("tags", [])[:5])

        short_resp = retry_on_transient(
            lambda sp=short_path, st=short_title, sd=short_desc, stg=short_tags: upload_video(
                filepath=sp, title=st, description=sd, tags=stg, privacy="private",
            ),
            label=f"YouTube short {i} upload",
        )
        short_id = short_resp.get("id")
        short_ids.append(short_id)
        logger.info(f"Job {job_id}: Short {i} uploaded: {short_id}")

        if i < len(short_thumbs_data) and short_thumbs_data[i]:
            try:
                retry_on_transient(
                    lambda sid=short_id, st=short_thumbs_data[i][0]: upload_thumbnail(sid, st),
                    label=f"YouTube short {i} thumbnail",
                )
            except Exception as e:
                logger.warning(f"Job {job_id}: Short {i} thumbnail upload failed: {e}")

    return {"video_id": video_id, "short_ids": short_ids, "title": chosen_title}


# ─── Backward-compatible aliases ───
run_pipeline_v6 = run_pipeline_v7
run_pipeline = run_pipeline_v7
