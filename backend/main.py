import os
import re
import json
import uuid
import logging
import threading
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

from fastapi import FastAPI, HTTPException, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse, FileResponse
from pydantic import BaseModel, field_validator

from pipeline import run_pipeline_v7 as run_pipeline, DATA_DIR
from youtube_auth import (
    get_auth_url, handle_callback, get_youtube_service,
    upload_video, upload_thumbnail,
)

logger = logging.getLogger("yt-pipeline")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

app = FastAPI(title="YT Editor Pipeline", version="7.0.0")

ALLOWED_ORIGINS = os.environ.get("ALLOWED_ORIGINS", "http://localhost:3000").split(",")

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

JOBS_FILE = os.path.join(DATA_DIR, "jobs.json")
LOG_FILE = os.path.join(DATA_DIR, "logs", "pipeline.log")
MAX_CONCURRENT_JOBS = 1

_jobs_lock = threading.Lock()
_active_jobs = 0
_active_jobs_lock = threading.Lock()
_approve_locks = {}  # Per-job approve lock to prevent double-click


# ─── Startup Validation ───

@app.on_event("startup")
def validate_config():
    required_keys = ["OPENAI_API_KEY", "ANTHROPIC_API_KEY", "REPLICATE_API_TOKEN"]
    missing = [k for k in required_keys if not os.environ.get(k)]
    if missing:
        logger.error(f"Missing required environment variables: {missing}")
    for d in ["logs", "inbox", "cleaned", "edited", "shorts", "thumbnails", "metadata", "published"]:
        os.makedirs(os.path.join(DATA_DIR, d), exist_ok=True)
    os.makedirs("/opt/yt-editor/backend/assets", exist_ok=True)
    logger.info("YT Editor Pipeline v7.0.0 started (auto-publish + captions + community images)")

    # ─── Startup Watchdog: auto-retry stuck jobs ───
    _recover_stuck_jobs()

    # ─── Background watchdog thread: detect stale steps ───
    watchdog = threading.Thread(target=_stale_job_watchdog, daemon=True)
    watchdog.start()


# Step timeout limits (seconds)
STEP_TIMEOUTS = {
    "download": 600,        # 10 min
    "transcribe": 300,      # 5 min
    "analyze": 300,         # 5 min
    "intake": 120,          # 2 min
    "edit_plan": 120,       # 2 min
    "execute_edits": 900,   # 15 min (FFmpeg, now low-memory)
    "caption_longform": 900,# 15 min (FFmpeg)
    "short_design": 120,    # 2 min
    "short_creation": 600,  # 10 min (multiple shorts)
    "packaging": 120,       # 2 min
    "thumbnail_gen": 300,   # 5 min
    "community_images": 300,# 5 min
    "qa_review": 120,       # 2 min
    "auto_publish": 600,    # 10 min (YouTube uploads)
    "community_posts": 300, # 5 min
}


def _recover_stuck_jobs():
    """On startup, find the most recent stuck job and auto-retry it.

    Only retries ONE job (most recent) to respect MAX_CONCURRENT_JOBS.
    Older stuck jobs are marked as failed so they don't pile up.
    """
    try:
        jobs = load_jobs()
        stuck_jobs = []
        for job_id, job in jobs.items():
            status = job.get("status", "")
            if status.startswith("processing:") or status == "queued":
                stuck_jobs.append((job_id, job))

        if not stuck_jobs:
            return

        # Sort by created_at descending — retry only the newest
        stuck_jobs.sort(key=lambda x: x[1].get("created_at", ""), reverse=True)

        # Mark older stuck jobs as failed
        for job_id, job in stuck_jobs[1:]:
            job["status"] = "failed"
            job["error"] = "Stuck job abandoned (newer job takes priority)"
            for step, step_status in job.get("steps", {}).items():
                if step_status == "running":
                    job["steps"][step] = "failed"
            log_event(f"Job {job_id} - Marked failed (older stuck job)")

        # Retry the newest stuck job
        job_id, job = stuck_jobs[0]
        for step, step_status in job.get("steps", {}).items():
            if step_status == "running":
                job["steps"][step] = "pending"
        job["status"] = "queued"
        job["error"] = None
        save_jobs(jobs)

        source = job.get("source", "")
        is_file = job.get("source_type") == "upload"
        if is_file:
            video_path = os.path.join(DATA_DIR, "inbox", f"{job_id}.mp4")
            if os.path.exists(video_path):
                source = video_path
            else:
                job["status"] = "failed"
                job["error"] = "Original video file missing after restart"
                save_jobs(jobs)
                log_event(f"Job {job_id} - Cannot recover: video file missing")
                return

        log_event(f"Job {job_id} - Auto-recovering stuck job on startup")
        thread = threading.Thread(
            target=run_pipeline_background, args=(job_id, source, is_file), daemon=True
        )
        thread.start()
    except Exception as e:
        logger.error(f"Startup recovery failed: {e}")


def _stale_job_watchdog():
    """Background thread that checks every 60s for jobs stuck past their timeout."""
    import time as _time
    while True:
        _time.sleep(60)
        try:
            jobs = load_jobs()
            for job_id, job in jobs.items():
                status = job.get("status", "")
                if not status.startswith("processing:"):
                    continue

                # Find which step is running
                running_step = None
                for step, step_status in job.get("steps", {}).items():
                    if step_status == "running":
                        running_step = step
                        break

                if not running_step:
                    continue

                # Check how long this step has been running
                # Use the last log entry timestamp as proxy
                timeout = STEP_TIMEOUTS.get(running_step, 600)
                step_start = job.get("step_started_at")
                if step_start:
                    elapsed = (datetime.utcnow() - datetime.fromisoformat(step_start)).total_seconds()
                    if elapsed > timeout:
                        logger.warning(
                            f"Job {job_id}: Step '{running_step}' timed out "
                            f"({elapsed:.0f}s > {timeout}s limit). Marking failed."
                        )
                        job["status"] = "failed"
                        job["error"] = f"Step '{running_step}' timed out after {elapsed:.0f}s"
                        job["steps"][running_step] = "failed"
                        save_jobs(jobs)
                        log_event(f"Job {job_id} - TIMEOUT: {running_step} after {elapsed:.0f}s")
        except Exception as e:
            logger.error(f"Watchdog error: {e}")


def log_event(msg: str):
    ts = datetime.utcnow().isoformat()
    try:
        safe_msg = msg.replace("\n", " ").replace("\r", "")
        with open(LOG_FILE, "a") as f:
            f.write(f"[{ts}] {safe_msg}\n")
    except OSError:
        logger.error(f"Failed to write log: {msg}")


def load_jobs() -> dict:
    with _jobs_lock:
        if os.path.exists(JOBS_FILE):
            try:
                with open(JOBS_FILE, "r") as f:
                    return json.load(f)
            except json.JSONDecodeError:
                logger.error("jobs.json corrupted, starting fresh")
                return {}
        return {}


def save_jobs(jobs: dict):
    with _jobs_lock:
        with open(JOBS_FILE, "w") as f:
            json.dump(jobs, f, indent=2, default=str)


# ─── Request Models ───

class VideoRequest(BaseModel):
    video_url: str
    @field_validator("video_url")
    @classmethod
    def validate_url(cls, v):
        parsed = urlparse(v)
        if parsed.scheme not in ("http", "https"):
            raise ValueError("URL must start with http:// or https://")
        return v


class ApproveRequest(BaseModel):
    publish_at: str = ""
    selected_thumbnail: int = 0
    selected_title_index: int = 0


# ─── Health ───

@app.get("/health")
def health():
    yt_authed = os.path.exists("/opt/yt-editor/backend/config/youtube_token.json")
    return {
        "status": "healthy",
        "version": "7.0.0",
        "youtube_authenticated": yt_authed,
        "active_jobs": _active_jobs,
        "timestamp": datetime.utcnow().isoformat(),
    }


# ─── YouTube OAuth ───

@app.get("/auth/youtube")
def auth_youtube():
    try:
        url = get_auth_url()
        return RedirectResponse(url)
    except Exception as e:
        logger.error(f"OAuth init failed: {e}")
        raise HTTPException(status_code=500, detail="OAuth configuration error")


@app.get("/auth/callback")
def auth_callback(code: str = None, error: str = None):
    if error:
        return {"error": error}
    if not code:
        return {"error": "No authorization code received"}
    try:
        handle_callback(code)
        log_event("YouTube OAuth completed successfully")
        return {"status": "success", "message": "YouTube authenticated! You can close this tab."}
    except Exception as e:
        log_event(f"YouTube OAuth failed: {type(e).__name__}")
        import traceback
        tb = traceback.format_exc()
        log_event(f"OAuth traceback: {tb}")
        return {"error": str(e), "detail": tb}


@app.get("/auth/status")
def auth_status():
    yt = os.path.exists("/opt/yt-editor/backend/config/youtube_token.json")
    return {"youtube": yt}


# ─── V6 Job Steps (11 steps) ───

V6_STEPS = {
    "download": "pending",
    "transcribe": "pending",
    "analyze": "pending",
    "intake": "pending",
    "edit_plan": "pending",
    "execute_edits": "pending",
    "caption_longform": "pending",
    "short_design": "pending",
    "short_creation": "pending",
    "packaging": "pending",
    "thumbnail_gen": "pending",
    "community_images": "pending",
    "qa_review": "pending",
    "auto_publish": "pending",
}


# ─── Pipeline ───

def run_pipeline_background(job_id: str, video_source: str, is_file: bool = False):
    global _active_jobs
    def update_step(step: str, status: str):
        jobs = load_jobs()
        if job_id in jobs:
            jobs[job_id]["steps"][step] = status
            if status == "running":
                jobs[job_id]["status"] = f"processing: {step}"
                jobs[job_id]["step_started_at"] = datetime.utcnow().isoformat()
            elif status in ("complete", "failed"):
                jobs[job_id].pop("step_started_at", None)
            save_jobs(jobs)
            log_event(f"Job {job_id} - {step}: {status}")

    try:
        with _active_jobs_lock:
            _active_jobs += 1
        result = run_pipeline(job_id, video_source, update_step, is_file=is_file)

        jobs = load_jobs()
        if job_id in jobs:
            # Determine final status based on auto-publish result
            if result.get("auto_published"):
                jobs[job_id]["status"] = "published"
                jobs[job_id]["youtube_video_id"] = result.get("youtube_video_id")
                jobs[job_id]["youtube_short_ids"] = result.get("youtube_short_ids", [])
                jobs[job_id]["published_at"] = datetime.utcnow().isoformat()
            else:
                jobs[job_id]["status"] = "ready_for_review"

            jobs[job_id]["result"] = {
                "video_path": result["video_path"],
                "short_paths": result["short_paths"],
                "short_designs": result.get("short_designs", []),
                "seo_data": result.get("seo_data", {}),
                "thumbnail_paths": result.get("thumbnail_paths", []),
                "thumbnail_data": result.get("thumbnail_data", {"long_form": [], "shorts": []}),
                "short_thumbnail_paths": result.get("short_thumbnail_paths", []),
                "community_posts": result.get("community_posts", []),
                "qa_scores": result.get("qa_scores", {}),
                "filler_count": result.get("filler_count", 0),
                "word_count": len(result.get("transcript", {}).get("words", [])),
                "video_type": result.get("video_type", {}),
                "original_duration": result.get("original_duration", 0),
                "edited_duration": result.get("edited_duration", 0),
                "title_variants": result.get("title_variants", []),
                "intake_result": result.get("intake_result", {}),
                "edit_plan": result.get("edit_plan", {}),
                "auto_published": result.get("auto_published", False),
                "auto_publish_error": result.get("auto_publish_error"),
            }
            save_jobs(jobs)

        status_msg = "Auto-published!" if result.get("auto_published") else "Ready for review."
        log_event(f"Job {job_id} - Pipeline complete. {status_msg}")
    except Exception as e:
        jobs = load_jobs()
        if job_id in jobs:
            jobs[job_id]["status"] = "failed"
            jobs[job_id]["error"] = str(e)[:500]
            save_jobs(jobs)
        log_event(f"Job {job_id} - FAILED: {type(e).__name__}")
        logger.error(f"Job {job_id} failed: {e}")
    finally:
        with _active_jobs_lock:
            _active_jobs -= 1


@app.post("/api/ingest")
async def ingest_video(req: VideoRequest):
    if _active_jobs >= MAX_CONCURRENT_JOBS:
        raise HTTPException(status_code=429, detail="Too many active jobs. Try again shortly.")
    job_id = str(uuid.uuid4())[:8]
    job = {
        "id": job_id, "source": req.video_url, "source_type": "url",
        "status": "queued", "created_at": datetime.utcnow().isoformat(),
        "steps": dict(V6_STEPS),
        "result": {},
    }
    jobs = load_jobs()
    jobs[job_id] = job
    save_jobs(jobs)
    log_event(f"Job {job_id} - Created from URL")
    thread = threading.Thread(target=run_pipeline_background, args=(job_id, req.video_url, False), daemon=True)
    thread.start()
    return {"job_id": job_id, "status": "queued"}


@app.post("/api/upload")
async def upload_video_file(file: UploadFile = File(...)):
    if _active_jobs >= MAX_CONCURRENT_JOBS:
        raise HTTPException(status_code=429, detail="Too many active jobs. Try again shortly.")
    allowed_extensions = {".mp4", ".mov", ".avi", ".mkv", ".webm"}
    ext = Path(file.filename).suffix.lower() if file.filename else ".mp4"
    if ext not in allowed_extensions:
        raise HTTPException(status_code=400, detail=f"Unsupported format. Allowed: {allowed_extensions}")

    job_id = str(uuid.uuid4())[:8]
    filepath = os.path.join(DATA_DIR, "inbox", f"{job_id}{ext}")
    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    with open(filepath, "wb") as f:
        while chunk := await file.read(8192):
            f.write(chunk)
    if os.path.getsize(filepath) < 1000:
        os.remove(filepath)
        raise HTTPException(status_code=400, detail="File too small")

    mp4_path = os.path.join(DATA_DIR, "inbox", f"{job_id}.mp4")
    if ext != ".mp4":
        import subprocess
        subprocess.run(["ffmpeg", "-y", "-i", filepath, "-c:v", "libx264", "-preset", "fast", "-c:a", "aac", mp4_path], capture_output=True, timeout=600)
        os.remove(filepath)
    else:
        mp4_path = filepath

    upload_steps = dict(V6_STEPS)
    upload_steps["download"] = "complete"
    job = {
        "id": job_id, "source": file.filename, "source_type": "upload",
        "status": "queued", "created_at": datetime.utcnow().isoformat(),
        "steps": upload_steps,
        "result": {},
    }
    jobs = load_jobs()
    jobs[job_id] = job
    save_jobs(jobs)
    log_event(f"Job {job_id} - Created from upload: {file.filename}")
    thread = threading.Thread(target=run_pipeline_background, args=(job_id, mp4_path, True), daemon=True)
    thread.start()
    return {"job_id": job_id, "status": "queued"}


@app.get("/api/jobs")
def list_jobs():
    jobs = load_jobs()
    return {"jobs": list(jobs.values())}


@app.get("/api/jobs/{job_id}")
def get_job(job_id: str):
    if not re.match(r'^[a-f0-9]{8}$', job_id):
        raise HTTPException(status_code=400, detail="Invalid job ID")
    jobs = load_jobs()
    if job_id not in jobs:
        raise HTTPException(status_code=404, detail="Job not found")
    return jobs[job_id]


@app.get("/api/jobs/{job_id}/approve-status")
def get_approve_status(job_id: str):
    """Returns current upload progress during approve. Frontend polls this."""
    if not re.match(r'^[a-f0-9]{8}$', job_id):
        raise HTTPException(status_code=400, detail="Invalid job ID")
    jobs = load_jobs()
    if job_id not in jobs:
        raise HTTPException(status_code=404, detail="Job not found")
    job = jobs[job_id]
    return {
        "job_id": job_id,
        "status": job["status"],
        "approve_progress": job.get("approve_progress", None),
        "youtube_video_id": job.get("youtube_video_id", None),
        "youtube_short_ids": job.get("youtube_short_ids", []),
        "published_at": job.get("published_at", None),
    }


@app.get("/api/jobs/{job_id}/qa")
def get_qa_report(job_id: str):
    """Get QA report for a job."""
    if not re.match(r'^[a-f0-9]{8}$', job_id):
        raise HTTPException(status_code=400, detail="Invalid job ID")
    jobs = load_jobs()
    if job_id not in jobs:
        raise HTTPException(status_code=404, detail="Job not found")
    job = jobs[job_id]
    result = job.get("result", {})
    return {"job_id": job_id, "qa_scores": result.get("qa_scores", {})}


@app.get("/api/jobs/{job_id}/community-posts")
def get_community_posts(job_id: str):
    """Get community posts for a job."""
    if not re.match(r'^[a-f0-9]{8}$', job_id):
        raise HTTPException(status_code=400, detail="Invalid job ID")
    jobs = load_jobs()
    if job_id not in jobs:
        raise HTTPException(status_code=404, detail="Job not found")
    job = jobs[job_id]
    result = job.get("result", {})
    return {"job_id": job_id, "community_posts": result.get("community_posts", [])}


def _update_approve_progress(jobs: dict, job_id: str, stage: str):
    """Helper to update approve progress in job data."""
    if job_id in jobs:
        jobs[job_id]["approve_progress"] = stage
        jobs[job_id]["status"] = f"uploading: {stage}"
        save_jobs(jobs)
        log_event(f"Job {job_id} - Approve progress: {stage}")


@app.post("/api/jobs/{job_id}/retry")
def retry_job(job_id: str):
    """Retry a failed or stuck job. Uses checkpoint/resume to skip completed steps."""
    if not re.match(r'^[a-f0-9]{8}$', job_id):
        raise HTTPException(status_code=400, detail="Invalid job ID")
    jobs = load_jobs()
    if job_id not in jobs:
        raise HTTPException(status_code=404, detail="Job not found")
    job = jobs[job_id]
    if job["status"] == "published":
        raise HTTPException(status_code=400, detail="Job already published")
    if _active_jobs >= MAX_CONCURRENT_JOBS:
        raise HTTPException(status_code=429, detail="Too many active jobs")

    # Determine source
    source = job.get("source", "")
    is_file = job.get("source_type") == "upload"
    if is_file:
        video_path = os.path.join(DATA_DIR, "inbox", f"{job_id}.mp4")
        if not os.path.exists(video_path):
            raise HTTPException(status_code=400, detail="Original video file not found")
        source = video_path

    # Reset pending steps (keep completed ones for checkpoint/resume)
    for step, status in job["steps"].items():
        if status == "running":
            job["steps"][step] = "pending"
    job["status"] = "queued"
    job["error"] = None
    save_jobs(jobs)
    log_event(f"Job {job_id} - Retrying (checkpoint/resume)")

    thread = threading.Thread(
        target=run_pipeline_background, args=(job_id, source, is_file), daemon=True
    )
    thread.start()
    return {"job_id": job_id, "status": "retrying"}


@app.post("/api/jobs/{job_id}/approve")
def approve_job(job_id: str, req: ApproveRequest):
    """Upload long-form ONCE + each short with unique thumbnail. Double-click protected."""
    if not re.match(r'^[a-f0-9]{8}$', job_id):
        raise HTTPException(status_code=400, detail="Invalid job ID")

    # Double-click protection: per-job mutex lock
    if job_id not in _approve_locks:
        _approve_locks[job_id] = threading.Lock()
    if not _approve_locks[job_id].acquire(blocking=False):
        raise HTTPException(status_code=409, detail="Upload already in progress for this job")

    try:
        jobs = load_jobs()
        if job_id not in jobs:
            raise HTTPException(status_code=404, detail="Job not found")
        job = jobs[job_id]

        # Prevent re-publishing
        if job["status"] == "published":
            raise HTTPException(status_code=400, detail="Job already published")
        if job["status"] != "ready_for_review":
            raise HTTPException(status_code=400, detail="Job not ready for approval")

        result = job.get("result", {})
        seo = result.get("seo_data", {})
        long_form_seo = seo.get("long_form", {})
        shorts_seo = seo.get("shorts", [])
        thumbnail_data = result.get("thumbnail_data", {"long_form": [], "shorts": []})

        # ─── Resolve long-form title from variants ───
        title_variants = result.get("title_variants", [])
        if not title_variants:
            titles_from_seo = long_form_seo.get("titles", None)
            if titles_from_seo and isinstance(titles_from_seo, list):
                title_variants = titles_from_seo
            else:
                single = long_form_seo.get("title", None)
                if single:
                    title_variants = [single]
                else:
                    tv = long_form_seo.get("title_variants", [])
                    title_variants = tv if tv else [f"Video {job_id}"]

        selected_idx = req.selected_title_index
        if selected_idx < 0 or selected_idx >= len(title_variants):
            selected_idx = 0
        chosen_title = title_variants[selected_idx]

        # ─── Upload long-form video ONCE ───
        _update_approve_progress(jobs, job_id, "uploading_longform")

        video_response = upload_video(
            filepath=result["video_path"],
            title=chosen_title,
            description=long_form_seo.get("description", ""),
            tags=long_form_seo.get("tags", []),
            privacy="private",
            publish_at=req.publish_at if req.publish_at else None,
        )
        video_id = video_response.get("id")
        log_event(f"Job {job_id} - Long-form uploaded: {video_id} — title variant {selected_idx}: '{chosen_title}'")

        # Upload selected thumbnail to long-form video
        long_thumbs = thumbnail_data.get("long_form", result.get("thumbnail_paths", []))
        if long_thumbs and 0 <= req.selected_thumbnail < len(long_thumbs):
            try:
                upload_thumbnail(video_id, long_thumbs[req.selected_thumbnail])
                log_event(f"Job {job_id} - Long-form thumbnail uploaded (index {req.selected_thumbnail})")
            except Exception as e:
                logger.warning(f"Job {job_id}: Long-form thumbnail upload failed: {e}")

        # ─── Upload each short with UNIQUE title, description, and thumbnail ───
        short_ids = []
        short_thumbs_data = thumbnail_data.get("shorts", [])

        for i, short_path in enumerate(result.get("short_paths", [])):
            _update_approve_progress(jobs, job_id, f"uploading_short_{i}")

            short_seo = shorts_seo[i] if i < len(shorts_seo) else {}
            short_title = short_seo.get("title", f"Short {i+1} from {chosen_title}")
            short_desc = short_seo.get("description", "")
            short_tags = short_seo.get("tags", long_form_seo.get("tags", [])[:5])

            short_resp = upload_video(
                filepath=short_path,
                title=short_title,
                description=short_desc,
                tags=short_tags,
                privacy="private",
                publish_at=req.publish_at if req.publish_at else None,
            )
            short_id = short_resp.get("id")
            short_ids.append(short_id)
            log_event(f"Job {job_id} - Short {i} uploaded: {short_id} — '{short_title}'")

            # Upload unique thumbnail for this short
            if i < len(short_thumbs_data) and short_thumbs_data[i]:
                try:
                    upload_thumbnail(short_id, short_thumbs_data[i][0])
                    log_event(f"Job {job_id} - Short {i} thumbnail uploaded")
                except Exception as e:
                    logger.warning(f"Job {job_id}: Short {i} thumbnail upload failed: {e}")

        # ─── Mark published ───
        _update_approve_progress(jobs, job_id, "complete")

        job["status"] = "published"
        job["approve_progress"] = "complete"
        job["youtube_video_id"] = video_id
        job["youtube_short_ids"] = short_ids
        job["published_at"] = datetime.utcnow().isoformat()
        job["selected_title"] = chosen_title
        job["selected_title_index"] = selected_idx
        save_jobs(jobs)

        log_event(f"Job {job_id} - Published. Video: {video_id}, Shorts: {short_ids}")
        return {"status": "published", "video_id": video_id, "short_ids": short_ids, "selected_title": chosen_title}

    except HTTPException:
        raise
    except Exception as e:
        try:
            jobs = load_jobs()
            if job_id in jobs and jobs[job_id]["status"].startswith("uploading"):
                jobs[job_id]["status"] = "ready_for_review"
                jobs[job_id]["approve_progress"] = f"failed: {str(e)[:200]}"
                save_jobs(jobs)
        except Exception:
            pass
        log_event(f"Job {job_id} - Upload failed: {type(e).__name__}: {e}")
        raise HTTPException(status_code=500, detail="YouTube upload failed. Check logs.")
    finally:
        _approve_locks[job_id].release()


# ─── Assets Management ───

@app.get("/api/assets/status")
def get_assets_status():
    """Check if intro/outro assets exist."""
    assets_dir = "/opt/yt-editor/backend/assets"
    return {
        "intro": os.path.exists(os.path.join(assets_dir, "intro.mp4")) or os.path.exists(os.path.join(assets_dir, "intro_default.mp4")),
        "outro": os.path.exists(os.path.join(assets_dir, "outro.mp4")) or os.path.exists(os.path.join(assets_dir, "outro_default.mp4")),
        "intro_custom": os.path.exists(os.path.join(assets_dir, "intro.mp4")),
        "outro_custom": os.path.exists(os.path.join(assets_dir, "outro.mp4")),
    }


@app.post("/api/assets/intro")
async def upload_intro(file: UploadFile = File(...)):
    """Upload custom intro clip."""
    assets_dir = "/opt/yt-editor/backend/assets"
    os.makedirs(assets_dir, exist_ok=True)
    dest = os.path.join(assets_dir, "intro.mp4")
    with open(dest, "wb") as f:
        while chunk := await file.read(8192):
            f.write(chunk)
    log_event("Custom intro uploaded")
    return {"status": "ok", "path": dest}


@app.post("/api/assets/outro")
async def upload_outro(file: UploadFile = File(...)):
    """Upload custom outro clip."""
    assets_dir = "/opt/yt-editor/backend/assets"
    os.makedirs(assets_dir, exist_ok=True)
    dest = os.path.join(assets_dir, "outro.mp4")
    with open(dest, "wb") as f:
        while chunk := await file.read(8192):
            f.write(chunk)
    log_event("Custom outro uploaded")
    return {"status": "ok", "path": dest}


# ─── File serving ───

@app.get("/api/thumbnails/{filename}")
def serve_thumbnail(filename: str):
    if ".." in filename or "/" in filename or "\\" in filename:
        raise HTTPException(status_code=400, detail="Invalid filename")
    path = os.path.join(DATA_DIR, "thumbnails", filename)
    real_path = os.path.realpath(path)
    if not real_path.startswith(os.path.realpath(os.path.join(DATA_DIR, "thumbnails"))):
        raise HTTPException(status_code=403, detail="Access denied")
    if not os.path.exists(real_path):
        raise HTTPException(status_code=404)
    return FileResponse(real_path)


@app.get("/api/logs")
def get_logs(lines: int = 50):
    lines = min(lines, 200)
    if not os.path.exists(LOG_FILE):
        return {"logs": []}
    with open(LOG_FILE, "r") as f:
        all_lines = f.readlines()
    return {"logs": all_lines[-lines:]}


# ═══════════════════════════════════════════════════════════════════════════════
#  V8: Avatar + UGC Video Generation Endpoints
# ═══════════════════════════════════════════════════════════════════════════════

class AvatarRequest(BaseModel):
    """Generate a talking-head video from a script using HeyGen avatar."""
    script: str
    avatar_id: str = ""  # Empty = use default/first available
    voice_id: str = ""
    title: str = ""
    dimension: str = "landscape"  # "landscape" or "portrait"
    run_pipeline: bool = True  # After generating, run full edit/short/publish pipeline

class UGCRequest(BaseModel):
    """Generate a UGC testimonial/case study video."""
    script: str
    template: str = "testimonial"  # "testimonial" or "case_study"
    speaker_name: str = ""
    speaker_title: str = ""
    avatar_id: str = ""
    voice_id: str = ""
    broll_ids: list = []  # IDs of uploaded B-roll clips
    music_id: str = ""  # ID of uploaded music track
    run_pipeline: bool = True


@app.get("/api/avatars")
def list_avatars():
    """List available HeyGen avatars."""
    try:
        from engines.heygen import list_avatars as _list_avatars
        avatars = _list_avatars()
        return {"avatars": avatars}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to list avatars: {e}")


@app.get("/api/voices")
def list_voices():
    """List available HeyGen voices."""
    try:
        from engines.heygen import list_voices as _list_voices
        voices = _list_voices()
        return {"voices": voices}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to list voices: {e}")


@app.post("/api/generate/avatar")
def generate_avatar_video(req: AvatarRequest):
    """Generate a talking-head video from script using HeyGen, then optionally
    run it through the full edit/short/publish pipeline."""
    if _active_jobs >= MAX_CONCURRENT_JOBS:
        raise HTTPException(status_code=429, detail="Too many active jobs. Try again shortly.")

    if not req.script.strip():
        raise HTTPException(status_code=400, detail="Script cannot be empty")

    job_id = uuid.uuid4().hex[:8]
    steps = dict(V6_STEPS)
    steps["heygen_generate"] = "pending"  # Add HeyGen step before download

    job = {
        "id": job_id,
        "source": f"avatar:{req.avatar_id or 'default'}",
        "source_type": "avatar",
        "status": "queued",
        "created_at": datetime.utcnow().isoformat(),
        "steps": steps,
        "result": {},
        "avatar_config": {
            "script": req.script,
            "avatar_id": req.avatar_id,
            "voice_id": req.voice_id,
            "dimension": req.dimension,
            "title": req.title,
        },
    }
    jobs = load_jobs()
    jobs[job_id] = job
    save_jobs(jobs)
    log_event(f"Job {job_id} - Avatar generation queued ({len(req.script)} chars)")

    thread = threading.Thread(
        target=_run_avatar_pipeline, args=(job_id, req), daemon=True
    )
    thread.start()
    return {"job_id": job_id, "status": "queued", "type": "avatar"}


def _run_avatar_pipeline(job_id: str, req: AvatarRequest):
    """Generate avatar video via HeyGen, then run through edit/short/publish pipeline."""
    global _active_jobs

    def update_step(step: str, status: str):
        jobs = load_jobs()
        if job_id in jobs:
            jobs[job_id]["steps"][step] = status
            if status == "running":
                jobs[job_id]["status"] = f"processing: {step}"
                jobs[job_id]["step_started_at"] = datetime.utcnow().isoformat()
            elif status in ("complete", "failed"):
                jobs[job_id].pop("step_started_at", None)
            save_jobs(jobs)
            log_event(f"Job {job_id} - {step}: {status}")

    try:
        with _active_jobs_lock:
            _active_jobs += 1

        # Step 0: Generate avatar video via HeyGen
        update_step("heygen_generate", "running")
        from engines.heygen import create_avatar_video

        avatar_id = req.avatar_id
        if not avatar_id:
            # Use first available avatar
            from engines.heygen import list_avatars as _list
            avatars = _list()
            private = [a for a in avatars if a["type"] == "private"]
            avatar_id = private[0]["avatar_id"] if private else avatars[0]["avatar_id"]

        video_path = create_avatar_video(
            script=req.script,
            avatar_id=avatar_id,
            job_id=job_id,
            voice_id=req.voice_id or None,
            title=req.title or None,
            dimension=req.dimension,
        )
        update_step("heygen_generate", "complete")
        log_event(f"Job {job_id} - HeyGen video generated: {video_path}")

        if req.run_pipeline:
            # Feed into existing pipeline (as if it was an uploaded file)
            result = run_pipeline(job_id, video_path, update_step, is_file=True)

            jobs = load_jobs()
            if job_id in jobs:
                if result.get("auto_published"):
                    jobs[job_id]["status"] = "published"
                    jobs[job_id]["youtube_video_id"] = result.get("youtube_video_id")
                    jobs[job_id]["youtube_short_ids"] = result.get("youtube_short_ids", [])
                    jobs[job_id]["published_at"] = datetime.utcnow().isoformat()
                else:
                    jobs[job_id]["status"] = "ready_for_review"
                jobs[job_id]["result"] = _build_result_dict(result)
                save_jobs(jobs)

            status_msg = "Auto-published!" if result.get("auto_published") else "Ready for review."
            log_event(f"Job {job_id} - Avatar pipeline complete. {status_msg}")
        else:
            # Just store the raw video, no pipeline
            jobs = load_jobs()
            if job_id in jobs:
                jobs[job_id]["status"] = "ready_for_review"
                jobs[job_id]["result"] = {"video_path": video_path}
                save_jobs(jobs)
            log_event(f"Job {job_id} - Avatar video ready (no pipeline)")

    except Exception as e:
        logger.error(f"Job {job_id}: Avatar pipeline failed: {e}", exc_info=True)
        try:
            jobs = load_jobs()
            if job_id in jobs:
                jobs[job_id]["status"] = "failed"
                jobs[job_id]["error"] = str(e)[:500]
                save_jobs(jobs)
        except Exception:
            pass
        log_event(f"Job {job_id} - Avatar pipeline FAILED: {e}")
    finally:
        with _active_jobs_lock:
            _active_jobs -= 1


@app.post("/api/generate/ugc")
def generate_ugc_video(req: UGCRequest):
    """Generate a UGC testimonial/case study video, then optionally run pipeline."""
    if _active_jobs >= MAX_CONCURRENT_JOBS:
        raise HTTPException(status_code=429, detail="Too many active jobs. Try again shortly.")

    if not req.script.strip():
        raise HTTPException(status_code=400, detail="Script cannot be empty")

    job_id = uuid.uuid4().hex[:8]
    steps = dict(V6_STEPS)
    steps["heygen_generate"] = "pending"
    steps["compose_ugc"] = "pending"

    job = {
        "id": job_id,
        "source": f"ugc:{req.template}",
        "source_type": "ugc",
        "status": "queued",
        "created_at": datetime.utcnow().isoformat(),
        "steps": steps,
        "result": {},
        "ugc_config": {
            "script": req.script,
            "template": req.template,
            "speaker_name": req.speaker_name,
            "speaker_title": req.speaker_title,
            "avatar_id": req.avatar_id,
            "voice_id": req.voice_id,
            "broll_ids": req.broll_ids,
            "music_id": req.music_id,
        },
    }
    jobs = load_jobs()
    jobs[job_id] = job
    save_jobs(jobs)
    log_event(f"Job {job_id} - UGC generation queued ({req.template}, {len(req.script)} chars)")

    thread = threading.Thread(
        target=_run_ugc_pipeline, args=(job_id, req), daemon=True
    )
    thread.start()
    return {"job_id": job_id, "status": "queued", "type": "ugc"}


def _run_ugc_pipeline(job_id: str, req: UGCRequest):
    """Generate avatar clip → compose UGC video → run pipeline."""
    global _active_jobs

    def update_step(step: str, status: str):
        jobs = load_jobs()
        if job_id in jobs:
            jobs[job_id]["steps"][step] = status
            if status == "running":
                jobs[job_id]["status"] = f"processing: {step}"
                jobs[job_id]["step_started_at"] = datetime.utcnow().isoformat()
            elif status in ("complete", "failed"):
                jobs[job_id].pop("step_started_at", None)
            save_jobs(jobs)
            log_event(f"Job {job_id} - {step}: {status}")

    try:
        with _active_jobs_lock:
            _active_jobs += 1

        # Step 0: Generate avatar clip via HeyGen
        update_step("heygen_generate", "running")
        from engines.heygen import create_avatar_video, list_avatars as _list

        avatar_id = req.avatar_id
        if not avatar_id:
            avatars = _list()
            private = [a for a in avatars if a["type"] == "private"]
            avatar_id = private[0]["avatar_id"] if private else avatars[0]["avatar_id"]

        avatar_clip = create_avatar_video(
            script=req.script,
            avatar_id=avatar_id,
            job_id=job_id,
            voice_id=req.voice_id or None,
        )
        update_step("heygen_generate", "complete")

        # Step 1: Compose UGC video
        update_step("compose_ugc", "running")
        from engines.video_composer import compose_video, build_testimonial_config, build_case_study_config

        # Resolve B-roll and music paths from asset IDs
        broll_dir = os.path.join(ASSETS_DIR, "broll")
        music_dir = os.path.join(ASSETS_DIR, "music")
        broll_clips = [os.path.join(broll_dir, f"{bid}.mp4") for bid in req.broll_ids
                       if os.path.exists(os.path.join(broll_dir, f"{bid}.mp4"))]
        music_path = None
        if req.music_id:
            mp = os.path.join(music_dir, f"{req.music_id}.mp3")
            if os.path.exists(mp):
                music_path = mp

        # Build composition config based on template
        # For now, use simple section splitting (script → sections by paragraph)
        paragraphs = [p.strip() for p in req.script.split("\n\n") if p.strip()]
        if not paragraphs:
            paragraphs = [req.script]

        if req.template == "case_study" and len(paragraphs) >= 3:
            # Map paragraphs to problem/solution/results
            config = build_case_study_config(
                avatar_clip=avatar_clip,
                problem={"text": paragraphs[0], "duration": 15, "key_metric": "THE PROBLEM"},
                solution={"text": paragraphs[1], "duration": 15, "key_metric": "THE SOLUTION"},
                results={"text": paragraphs[2], "duration": 15, "key_metric": "THE RESULTS"},
                broll_clips=broll_clips,
                music_path=music_path,
                speaker_name=req.speaker_name,
                speaker_title=req.speaker_title,
            )
        else:
            # Default: testimonial
            script_sections = [{"text": p, "duration": max(5, len(p) / 15)}
                              for p in paragraphs]
            config = build_testimonial_config(
                avatar_clip=avatar_clip,
                script_sections=script_sections,
                broll_clips=broll_clips,
                music_path=music_path,
                speaker_name=req.speaker_name,
                speaker_title=req.speaker_title,
            )

        composed_path = compose_video(config, job_id)
        update_step("compose_ugc", "complete")
        log_event(f"Job {job_id} - UGC video composed: {composed_path}")

        if req.run_pipeline:
            result = run_pipeline(job_id, composed_path, update_step, is_file=True)

            jobs = load_jobs()
            if job_id in jobs:
                if result.get("auto_published"):
                    jobs[job_id]["status"] = "published"
                    jobs[job_id]["youtube_video_id"] = result.get("youtube_video_id")
                    jobs[job_id]["youtube_short_ids"] = result.get("youtube_short_ids", [])
                    jobs[job_id]["published_at"] = datetime.utcnow().isoformat()
                else:
                    jobs[job_id]["status"] = "ready_for_review"
                jobs[job_id]["result"] = _build_result_dict(result)
                save_jobs(jobs)

            status_msg = "Auto-published!" if result.get("auto_published") else "Ready for review."
            log_event(f"Job {job_id} - UGC pipeline complete. {status_msg}")
        else:
            jobs = load_jobs()
            if job_id in jobs:
                jobs[job_id]["status"] = "ready_for_review"
                jobs[job_id]["result"] = {"video_path": composed_path}
                save_jobs(jobs)

    except Exception as e:
        logger.error(f"Job {job_id}: UGC pipeline failed: {e}", exc_info=True)
        try:
            jobs = load_jobs()
            if job_id in jobs:
                jobs[job_id]["status"] = "failed"
                jobs[job_id]["error"] = str(e)[:500]
                save_jobs(jobs)
        except Exception:
            pass
        log_event(f"Job {job_id} - UGC pipeline FAILED: {e}")
    finally:
        with _active_jobs_lock:
            _active_jobs -= 1


def _build_result_dict(result: dict) -> dict:
    """Build the result dict stored in jobs.json from pipeline output."""
    return {
        "video_path": result.get("video_path"),
        "short_paths": result.get("short_paths", []),
        "short_designs": result.get("short_designs", []),
        "seo_data": result.get("seo_data", {}),
        "thumbnail_paths": result.get("thumbnail_paths", []),
        "thumbnail_data": result.get("thumbnail_data", {"long_form": [], "shorts": []}),
        "short_thumbnail_paths": result.get("short_thumbnail_paths", []),
        "community_posts": result.get("community_posts", []),
        "qa_scores": result.get("qa_scores", {}),
        "filler_count": result.get("filler_count", 0),
        "word_count": len(result.get("transcript", {}).get("words", [])),
        "video_type": result.get("video_type", {}),
        "original_duration": result.get("original_duration", 0),
        "edited_duration": result.get("edited_duration", 0),
        "title_variants": result.get("title_variants", []),
        "intake_result": result.get("intake_result", {}),
        "edit_plan": result.get("edit_plan", {}),
        "auto_published": result.get("auto_published", False),
        "auto_publish_error": result.get("auto_publish_error"),
    }


# ─── B-Roll and Music Asset Management ───

@app.post("/api/assets/broll")
async def upload_broll(file: UploadFile = File(...)):
    """Upload a B-roll clip for UGC compositions."""
    broll_dir = os.path.join(ASSETS_DIR, "broll")
    os.makedirs(broll_dir, exist_ok=True)
    broll_id = uuid.uuid4().hex[:8]
    dest = os.path.join(broll_dir, f"{broll_id}.mp4")
    with open(dest, "wb") as f:
        while chunk := await file.read(8192):
            f.write(chunk)
    log_event(f"B-roll uploaded: {broll_id} ({file.filename})")
    return {"broll_id": broll_id, "filename": file.filename, "path": dest}


@app.post("/api/assets/music")
async def upload_music(file: UploadFile = File(...)):
    """Upload a background music track for UGC compositions."""
    music_dir = os.path.join(ASSETS_DIR, "music")
    os.makedirs(music_dir, exist_ok=True)
    music_id = uuid.uuid4().hex[:8]
    dest = os.path.join(music_dir, f"{music_id}.mp3")
    with open(dest, "wb") as f:
        while chunk := await file.read(8192):
            f.write(chunk)
    log_event(f"Music uploaded: {music_id} ({file.filename})")
    return {"music_id": music_id, "filename": file.filename, "path": dest}


@app.get("/api/assets/broll")
def list_broll():
    """List available B-roll clips."""
    broll_dir = os.path.join(ASSETS_DIR, "broll")
    if not os.path.exists(broll_dir):
        return {"broll": []}
    clips = []
    for f in os.listdir(broll_dir):
        if f.endswith(".mp4"):
            clips.append({"broll_id": f.replace(".mp4", ""), "filename": f})
    return {"broll": clips}


@app.get("/api/assets/music")
def list_music():
    """List available music tracks."""
    music_dir = os.path.join(ASSETS_DIR, "music")
    if not os.path.exists(music_dir):
        return {"music": []}
    tracks = []
    for f in os.listdir(music_dir):
        if f.endswith(".mp3"):
            tracks.append({"music_id": f.replace(".mp3", ""), "filename": f})
    return {"music": tracks}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000)
