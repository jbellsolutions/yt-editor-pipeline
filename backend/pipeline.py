import os
import re
import json
import subprocess
import time
import logging
from pathlib import Path
from urllib.parse import urlparse

import httpx
import anthropic
from openai import OpenAI

DATA_DIR = os.environ.get("DATA_DIR", "/opt/yt-editor/data")

logger = logging.getLogger("yt-pipeline")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

ALLOWED_DOMAINS = {
    "www.loom.com", "loom.com",
    "www.youtube.com", "youtube.com", "youtu.be",
    "vimeo.com", "www.vimeo.com",
    "drive.google.com",
}
MAX_RETRIES = 3
RETRY_BACKOFF = [2, 5, 10]


# ─── Retry Helper ───

def retry_on_transient(fn, retries=MAX_RETRIES, label="operation"):
    """Retry a function on transient errors with exponential backoff."""
    last_error = None
    for attempt in range(retries):
        try:
            return fn()
        except (httpx.TimeoutException, httpx.HTTPStatusError, ConnectionError,
                TimeoutError) as e:
            last_error = e
            if isinstance(e, httpx.HTTPStatusError) and e.response.status_code < 500:
                raise  # 4xx are not retryable
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
    """Validate video URL. Accepts Loom, YouTube, Vimeo, Google Drive, or any direct video URL."""
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise ValueError(f"Invalid URL scheme: {parsed.scheme}")
    # Allow known video platforms + any URL ending in video extension
    video_extensions = (".mp4", ".mov", ".avi", ".mkv", ".webm")
    is_known_domain = parsed.hostname in ALLOWED_DOMAINS
    is_direct_video = any(parsed.path.lower().endswith(ext) for ext in video_extensions)
    if not is_known_domain and not is_direct_video:
        # Still allow — yt-dlp supports thousands of sites
        logger.info(f"Non-standard video domain: {parsed.hostname}, will attempt yt-dlp")
    return url


def run_subprocess(cmd: list, timeout: int = 300, check: bool = True, label: str = "subprocess"):
    """Run subprocess with timeout and return code checking."""
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    if check and result.returncode != 0:
        raise subprocess.CalledProcessError(result.returncode, cmd, result.stdout, result.stderr)
    return result


# ─── STEP 1: Download Video ───

def download_video_from_url(video_url: str, job_id: str) -> str:
    """Download video from any URL to inbox directory. Returns filepath."""
    video_url = validate_video_url(video_url)
    outpath = os.path.join(DATA_DIR, "inbox", f"{job_id}.mp4")
    os.makedirs(os.path.dirname(outpath), exist_ok=True)

    parsed = urlparse(video_url)
    is_loom = parsed.hostname in ("www.loom.com", "loom.com")
    is_direct = any(parsed.path.lower().endswith(ext) for ext in (".mp4", ".mov", ".avi", ".mkv", ".webm"))

    if is_direct:
        # Direct video URL — download directly
        def download_direct():
            with httpx.stream("GET", video_url, timeout=300, follow_redirects=True) as stream:
                stream.raise_for_status()
                with open(outpath, "wb") as f:
                    for chunk in stream.iter_bytes(chunk_size=8192):
                        f.write(chunk)
        retry_on_transient(download_direct, label="Direct video download")

    elif is_loom:
        # Loom — try to extract video URL from page source
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
            # Fallback to yt-dlp
            run_subprocess(
                ["yt-dlp", "-o", outpath, "--", video_url],
                timeout=300, label="yt-dlp download"
            )
    else:
        # Any other URL — use yt-dlp (supports 1000+ sites)
        run_subprocess(
            ["yt-dlp", "-o", outpath, "--", video_url],
            timeout=600, label="yt-dlp download"
        )

    if not os.path.exists(outpath) or os.path.getsize(outpath) < 1000:
        raise Exception("Download failed: file too small or missing")

    logger.info(f"Job {job_id}: Downloaded {os.path.getsize(outpath)} bytes")
    return outpath


# ─── STEP 2: Transcribe with Whisper ───

def transcribe_video(video_path: str, job_id: str) -> dict:
    """Transcribe video using OpenAI Whisper API. Returns transcript with word timestamps."""
    audio_path = os.path.join(DATA_DIR, "inbox", f"{job_id}.mp3")
    os.makedirs(os.path.dirname(audio_path), exist_ok=True)

    run_subprocess([
        "ffmpeg", "-y", "-i", video_path, "-vn", "-acodec", "libmp3lame",
        "-ar", "16000", "-ac", "1", audio_path
    ], timeout=300, label="Audio extraction")

    client = OpenAI(timeout=120)

    def call_whisper():
        with open(audio_path, "rb") as f:
            return client.audio.transcriptions.create(
                model="whisper-1",
                file=f,
                response_format="verbose_json",
                timestamp_granularities=["word", "segment"]
            )

    result = retry_on_transient(call_whisper, label="Whisper transcription")

    transcript_path = os.path.join(DATA_DIR, "metadata", f"{job_id}_transcript.json")
    os.makedirs(os.path.dirname(transcript_path), exist_ok=True)
    transcript_data = result.model_dump()
    with open(transcript_path, "w") as f:
        json.dump(transcript_data, f, indent=2)

    Path(audio_path).unlink(missing_ok=True)

    logger.info(f"Job {job_id}: Transcribed {len(transcript_data.get('words', []))} words")
    return transcript_data


# ─── STEP 3: Remove Filler Words ───

FILLER_WORDS = {
    "um", "uh", "uhm", "umm", "uhh", "hmm", "hm",
}

def detect_filler_segments(transcript: dict) -> list:
    """Find filler word timestamps to cut from video."""
    filler_segments = []
    words = transcript.get("words", [])

    for word_info in words:
        word = word_info.get("word", "").strip().lower().rstrip(".,!?")
        if word in FILLER_WORDS:
            start = word_info.get("start", 0)
            end = word_info.get("end", 0)
            if end > start:
                filler_segments.append({"start": start, "end": end, "word": word})

    return filler_segments


def remove_fillers_from_video(video_path: str, filler_segments: list, job_id: str) -> str:
    """Remove filler word segments from video using FFmpeg. Returns cleaned video path."""
    cleaned_path = os.path.join(DATA_DIR, "cleaned", f"{job_id}.mp4")
    os.makedirs(os.path.dirname(cleaned_path), exist_ok=True)

    if not filler_segments:
        run_subprocess(["cp", video_path, cleaned_path], timeout=60, label="Copy (no fillers)")
        return cleaned_path

    probe = run_subprocess([
        "ffprobe", "-v", "quiet", "-print_format", "json",
        "-show_format", video_path
    ], timeout=30, label="FFprobe duration")
    duration = float(json.loads(probe.stdout)["format"]["duration"])

    keep_segments = []
    current = 0.0
    for filler in sorted(filler_segments, key=lambda x: x["start"]):
        if filler["start"] > current:
            keep_segments.append((current, filler["start"]))
        current = filler["end"]
    if current < duration:
        keep_segments.append((current, duration))

    if not keep_segments:
        raise Exception("No content remaining after filler removal")

    filter_parts = []
    inputs = []
    for i, (start, end) in enumerate(keep_segments):
        filter_parts.append(
            f"[0:v]trim=start={start}:end={end},setpts=PTS-STARTPTS[v{i}];"
            f"[0:a]atrim=start={start}:end={end},asetpts=PTS-STARTPTS[a{i}];"
        )
        inputs.append(f"[v{i}][a{i}]")

    filter_complex = "".join(filter_parts)
    filter_complex += "".join(inputs) + f"concat=n={len(keep_segments)}:v=1:a=1[outv][outa]"

    run_subprocess([
        "ffmpeg", "-y", "-i", video_path,
        "-filter_complex", filter_complex,
        "-map", "[outv]", "-map", "[outa]",
        "-c:v", "libx264", "-preset", "fast", "-crf", "23",
        "-c:a", "aac", "-b:a", "128k",
        cleaned_path
    ], timeout=600, label="FFmpeg filler removal")

    if not os.path.exists(cleaned_path) or os.path.getsize(cleaned_path) < 1000:
        raise Exception("Filler removal failed: output too small")

    logger.info(f"Job {job_id}: Removed {len(filler_segments)} fillers")
    return cleaned_path


# ─── STEP 4: Detect Short Segments via Claude ───

def detect_shorts(transcript: dict, job_id: str) -> list:
    """Use Claude to find the best 30-60s segments for YouTube Shorts."""
    segments = transcript.get("segments", [])

    timestamped = ""
    for seg in segments:
        start = seg.get("start", 0)
        end = seg.get("end", 0)
        text = seg.get("text", "").strip()
        timestamped += f"[{start:.1f}s - {end:.1f}s] {text}\n"

    client = anthropic.Anthropic(timeout=120.0)

    def call_claude():
        message = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=2000,
            messages=[{
                "role": "user",
                "content": f"""Analyze this video transcript and identify the 2-4 best segments for YouTube Shorts (30-60 seconds each).

Each segment must:
- Be self-contained (makes sense without context)
- Have a strong hook in the first 3 seconds
- Deliver value or entertainment
- End cleanly (not mid-sentence)

Return ONLY valid JSON array, no other text:
[
  {{"start": 12.5, "end": 55.0, "title": "Short title here", "hook": "Why this segment grabs attention"}},
  ...
]

TRANSCRIPT:
{timestamped}"""
            }]
        )
        return message.content[0].text.strip()

    response_text = retry_on_transient(call_claude, label="Claude shorts detection")

    json_match = re.search(r'\[.*\]', response_text, re.DOTALL)
    try:
        shorts = json.loads(json_match.group()) if json_match else json.loads(response_text)
    except json.JSONDecodeError:
        logger.warning(f"Job {job_id}: Claude returned invalid JSON for shorts, retrying...")
        response_text = retry_on_transient(call_claude, label="Claude shorts retry")
        json_match = re.search(r'\[.*\]', response_text, re.DOTALL)
        shorts = json.loads(json_match.group()) if json_match else json.loads(response_text)

    shorts_path = os.path.join(DATA_DIR, "metadata", f"{job_id}_shorts.json")
    os.makedirs(os.path.dirname(shorts_path), exist_ok=True)
    with open(shorts_path, "w") as f:
        json.dump(shorts, f, indent=2)

    logger.info(f"Job {job_id}: Detected {len(shorts)} short segments")
    return shorts


# ─── STEP 5: Create Short Videos ───

def create_shorts(cleaned_video: str, shorts_config: list, job_id: str) -> list:
    """Extract and crop short segments to 9:16 vertical format."""
    short_paths = []
    os.makedirs(os.path.join(DATA_DIR, "shorts"), exist_ok=True)

    probe = run_subprocess([
        "ffprobe", "-v", "quiet", "-print_format", "json",
        "-show_streams", cleaned_video
    ], timeout=30, label="FFprobe dimensions")
    streams = json.loads(probe.stdout).get("streams", [])
    video_stream = next((s for s in streams if s["codec_type"] == "video"), {})
    width = int(video_stream.get("width", 1920))
    height = int(video_stream.get("height", 1080))

    target_ratio = 9 / 16
    current_ratio = width / height

    if current_ratio > target_ratio:
        new_width = int(height * target_ratio)
        crop_x = (width - new_width) // 2
        crop_filter = f"crop={new_width}:{height}:{crop_x}:0,scale=1080:1920"
    else:
        new_height = int(width / target_ratio)
        crop_y = (height - new_height) // 2
        crop_filter = f"crop={width}:{new_height}:0:{crop_y},scale=1080:1920"

    for i, short in enumerate(shorts_config):
        out_path = os.path.join(DATA_DIR, "shorts", f"{job_id}_short_{i}.mp4")
        start = short["start"]
        duration = short["end"] - short["start"]

        try:
            run_subprocess([
                "ffmpeg", "-y", "-i", cleaned_video,
                "-ss", str(start), "-t", str(duration),
                "-vf", crop_filter,
                "-c:v", "libx264", "-preset", "fast", "-crf", "23",
                "-c:a", "aac", "-b:a", "128k",
                out_path
            ], timeout=300, label=f"Short {i} creation")

            if os.path.exists(out_path) and os.path.getsize(out_path) > 1000:
                short_paths.append(out_path)
        except subprocess.CalledProcessError as e:
            logger.error(f"Job {job_id}: Short {i} creation failed: {e}")

    logger.info(f"Job {job_id}: Created {len(short_paths)} shorts")
    return short_paths


# ─── STEP 6: Generate SEO Metadata ───

def generate_seo(transcript: dict, shorts_config: list, job_id: str) -> dict:
    """Generate SEO-optimized titles, descriptions, and tags."""
    full_text = transcript.get("text", "")

    client = anthropic.Anthropic(timeout=120.0)

    def call_claude():
        message = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=3000,
            messages=[{
                "role": "user",
                "content": f"""Based on this video transcript, generate SEO-optimized YouTube metadata.

Return ONLY valid JSON, no other text:
{{
  "long_form": {{
    "title": "SEO title under 60 chars, keyword-rich, click-worthy",
    "description": "Full description with keywords, value proposition, and call to action. Include relevant hashtags. 2-3 paragraphs.",
    "tags": ["tag1", "tag2", "up to 15 relevant tags"]
  }},
  "shorts": [
    {{
      "title": "Short title under 60 chars with hook",
      "description": "Short description with hashtags",
      "tags": ["tag1", "tag2"]
    }}
  ]
}}

Make titles click-worthy but NOT clickbait. Optimize for YouTube search and suggested videos.

TRANSCRIPT:
{full_text[:4000]}

SHORTS SEGMENTS:
{json.dumps(shorts_config, indent=2)}"""
            }]
        )
        return message.content[0].text.strip()

    response_text = retry_on_transient(call_claude, label="Claude SEO generation")

    json_match = re.search(r'\{.*\}', response_text, re.DOTALL)
    try:
        seo_data = json.loads(json_match.group()) if json_match else json.loads(response_text)
    except json.JSONDecodeError:
        logger.warning(f"Job {job_id}: Claude returned invalid JSON for SEO, retrying...")
        response_text = retry_on_transient(call_claude, label="Claude SEO retry")
        json_match = re.search(r'\{.*\}', response_text, re.DOTALL)
        seo_data = json.loads(json_match.group()) if json_match else json.loads(response_text)

    seo_path = os.path.join(DATA_DIR, "metadata", f"{job_id}_seo.json")
    os.makedirs(os.path.dirname(seo_path), exist_ok=True)
    with open(seo_path, "w") as f:
        json.dump(seo_data, f, indent=2)

    logger.info(f"Job {job_id}: SEO metadata generated")
    return seo_data


# ─── STEP 7: Generate Thumbnails ───

def generate_thumbnails(seo_data: dict, job_id: str) -> list:
    """Generate AI thumbnails using Replicate FLUX model."""
    import replicate

    title = seo_data.get("long_form", {}).get("title", "Video")
    thumbnail_paths = []
    os.makedirs(os.path.join(DATA_DIR, "thumbnails"), exist_ok=True)

    prompts = [
        f"YouTube thumbnail, bold text overlay '{title[:30]}', vibrant colors, high contrast, professional, eye-catching, 1280x720",
        f"YouTube thumbnail, cinematic style, dramatic lighting, person speaking, topic: {title[:40]}, bold typography, 1280x720",
        f"YouTube thumbnail, clean modern design, gradient background, bold white text, professional, {title[:30]}, 1280x720",
        f"YouTube thumbnail, energetic, bright colors, engaging visual, topic about {title[:40]}, YouTube style, 1280x720",
    ]

    for i, prompt in enumerate(prompts):
        try:
            output = replicate.run(
                "black-forest-labs/flux-schnell",
                input={
                    "prompt": prompt,
                    "num_outputs": 1,
                    "aspect_ratio": "16:9",
                    "output_format": "png",
                }
            )
            if output:
                img_url = output[0] if isinstance(output, list) else str(output)
                img_data = httpx.get(str(img_url), timeout=60).content
                thumb_path = os.path.join(DATA_DIR, "thumbnails", f"{job_id}_thumb_{i}.png")
                with open(thumb_path, "wb") as f:
                    f.write(img_data)
                thumbnail_paths.append(thumb_path)
                logger.info(f"Job {job_id}: Thumbnail {i} generated")
        except (httpx.TimeoutException, ConnectionError) as e:
            logger.warning(f"Job {job_id}: Thumbnail {i} transient error: {e}")
        except Exception as e:
            logger.error(f"Job {job_id}: Thumbnail {i} failed: {e}")

    return thumbnail_paths


# ─── MASTER PIPELINE ───

def run_pipeline(job_id: str, video_source: str, update_fn, is_file: bool = False):
    """Run the full pipeline. update_fn(step, status) updates job state."""
    # Step 1: Download (skip if file upload)
    if is_file:
        video_path = video_source  # Already on disk
        update_fn("download", "complete")
    else:
        update_fn("download", "running")
        video_path = download_video_from_url(video_source, job_id)
        update_fn("download", "complete")

    # Step 2: Transcribe
    update_fn("transcribe", "running")
    transcript = transcribe_video(video_path, job_id)
    update_fn("transcribe", "complete")

    # Step 3: Remove fillers
    update_fn("filler_removal", "running")
    fillers = detect_filler_segments(transcript)
    cleaned_path = remove_fillers_from_video(video_path, fillers, job_id)
    update_fn("filler_removal", "complete")

    # Step 4: Detect shorts
    update_fn("short_detection", "running")
    shorts_config = detect_shorts(transcript, job_id)
    update_fn("short_detection", "complete")

    # Step 5: Create shorts
    update_fn("short_creation", "running")
    short_paths = create_shorts(cleaned_path, shorts_config, job_id)
    update_fn("short_creation", "complete")

    # Step 6: SEO
    update_fn("seo_generation", "running")
    seo_data = generate_seo(transcript, shorts_config, job_id)
    update_fn("seo_generation", "complete")

    # Step 7: Thumbnails
    update_fn("thumbnail_generation", "running")
    thumbnail_paths = generate_thumbnails(seo_data, job_id)
    update_fn("thumbnail_generation", "complete")

    return {
        "video_path": cleaned_path,
        "short_paths": short_paths,
        "shorts_config": shorts_config,
        "seo_data": seo_data,
        "thumbnail_paths": thumbnail_paths,
        "filler_count": len(fillers),
        "transcript": transcript,
    }
