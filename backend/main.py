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

from pipeline import run_pipeline, DATA_DIR
from youtube_auth import (
    get_auth_url, handle_callback, get_youtube_service,
    upload_video, upload_thumbnail,
)

logger = logging.getLogger("yt-pipeline")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

app = FastAPI(title="YT Editor Pipeline", version="3.0.0")

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
MAX_CONCURRENT_JOBS = 3

_jobs_lock = threading.Lock()
_active_jobs = 0
_active_jobs_lock = threading.Lock()


# ─── Startup Validation ───

@app.on_event("startup")
def validate_config():
    required_keys = ["OPENAI_API_KEY", "ANTHROPIC_API_KEY", "REPLICATE_API_TOKEN"]
    missing = [k for k in required_keys if not os.environ.get(k)]
    if missing:
        logger.error(f"Missing required environment variables: {missing}")
    os.makedirs(os.path.join(DATA_DIR, "logs"), exist_ok=True)
    os.makedirs(os.path.join(DATA_DIR, "inbox"), exist_ok=True)
    os.makedirs(os.path.join(DATA_DIR, "cleaned"), exist_ok=True)
    os.makedirs(os.path.join(DATA_DIR, "shorts"), exist_ok=True)
    os.makedirs(os.path.join(DATA_DIR, "thumbnails"), exist_ok=True)
    os.makedirs(os.path.join(DATA_DIR, "metadata"), exist_ok=True)
    os.makedirs(os.path.join(DATA_DIR, "published"), exist_ok=True)
    logger.info("YT Editor Pipeline v3.0.0 started")


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


# ─── Health ───

@app.get("/health")
def health():
    yt_authed = os.path.exists("/opt/yt-editor/backend/config/youtube_token.json")
    return {
        "status": "healthy",
        "version": "3.0.0",
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
        return {"error": "Authentication failed. Please try again."}


@app.get("/auth/status")
def auth_status():
    yt = os.path.exists("/opt/yt-editor/backend/config/youtube_token.json")
    return {"youtube": yt}


# ─── Pipeline ───

def run_pipeline_background(job_id: str, video_source: str, is_file: bool = False):
    """Run pipeline in background thread."""
    global _active_jobs

    def update_step(step: str, status: str):
        jobs = load_jobs()
        if job_id in jobs:
            jobs[job_id]["steps"][step] = status
            if status == "running":
                jobs[job_id]["status"] = f"processing: {step}"
            save_jobs(jobs)
            log_event(f"Job {job_id} - {step}: {status}")

    try:
        with _active_jobs_lock:
            _active_jobs += 1

        result = run_pipeline(job_id, video_source, update_step, is_file=is_file)
        jobs = load_jobs()
        if job_id in jobs:
            jobs[job_id]["status"] = "ready_for_review"
            jobs[job_id]["result"] = {
                "video_path": result["video_path"],
                "short_paths": result["short_paths"],
                "shorts_config": result["shorts_config"],
                "seo_data": result["seo_data"],
                "thumbnail_paths": result["thumbnail_paths"],
                "filler_count": result["filler_count"],
                "word_count": len(result["transcript"].get("words", [])),
            }
            save_jobs(jobs)
        log_event(f"Job {job_id} - Pipeline complete. Ready for review.")
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
        "id": job_id,
        "source": req.video_url,
        "source_type": "url",
        "status": "queued",
        "created_at": datetime.utcnow().isoformat(),
        "steps": {
            "download": "pending",
            "transcribe": "pending",
            "filler_removal": "pending",
            "short_detection": "pending",
            "short_creation": "pending",
            "seo_generation": "pending",
            "thumbnail_generation": "pending",
        },
        "result": {},
    }
    jobs = load_jobs()
    jobs[job_id] = job
    save_jobs(jobs)
    log_event(f"Job {job_id} - Created from URL")

    thread = threading.Thread(
        target=run_pipeline_background,
        args=(job_id, req.video_url, False),
        daemon=True
    )
    thread.start()

    return {"job_id": job_id, "status": "queued"}


@app.post("/api/upload")
async def upload_video_file(file: UploadFile = File(...)):
    """Upload a video file directly instead of providing a URL."""
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

    # Convert to mp4 if needed
    mp4_path = os.path.join(DATA_DIR, "inbox", f"{job_id}.mp4")
    if ext != ".mp4":
        import subprocess
        subprocess.run([
            "ffmpeg", "-y", "-i", filepath, "-c:v", "libx264",
            "-preset", "fast", "-c:a", "aac", mp4_path
        ], capture_output=True, timeout=600)
        os.remove(filepath)
    else:
        mp4_path = filepath

    job = {
        "id": job_id,
        "source": file.filename,
        "source_type": "upload",
        "status": "queued",
        "created_at": datetime.utcnow().isoformat(),
        "steps": {
            "download": "complete",  # already have the file
            "transcribe": "pending",
            "filler_removal": "pending",
            "short_detection": "pending",
            "short_creation": "pending",
            "seo_generation": "pending",
            "thumbnail_generation": "pending",
        },
        "result": {},
    }
    jobs = load_jobs()
    jobs[job_id] = job
    save_jobs(jobs)
    log_event(f"Job {job_id} - Created from upload: {file.filename}")

    thread = threading.Thread(
        target=run_pipeline_background,
        args=(job_id, mp4_path, True),
        daemon=True
    )
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


@app.post("/api/jobs/{job_id}/approve")
def approve_job(job_id: str, req: ApproveRequest):
    if not re.match(r'^[a-f0-9]{8}$', job_id):
        raise HTTPException(status_code=400, detail="Invalid job ID")
    jobs = load_jobs()
    if job_id not in jobs:
        raise HTTPException(status_code=404, detail="Job not found")
    job = jobs[job_id]
    if job["status"] != "ready_for_review":
        raise HTTPException(status_code=400, detail="Job not ready for approval")

    result = job.get("result", {})
    seo = result.get("seo_data", {})
    long_form = seo.get("long_form", {})

    try:
        video_response = upload_video(
            filepath=result["video_path"],
            title=long_form.get("title", f"Video {job_id}"),
            description=long_form.get("description", ""),
            tags=long_form.get("tags", []),
            privacy="private",
            publish_at=req.publish_at if req.publish_at else None,
        )
        video_id = video_response.get("id")

        thumbs = result.get("thumbnail_paths", [])
        if thumbs and 0 <= req.selected_thumbnail < len(thumbs):
            upload_thumbnail(video_id, thumbs[req.selected_thumbnail])

        shorts_seo = seo.get("shorts", [])
        short_ids = []
        for i, short_path in enumerate(result.get("short_paths", [])):
            short_seo = shorts_seo[i] if i < len(shorts_seo) else {}
            short_resp = upload_video(
                filepath=short_path,
                title=short_seo.get("title", f"Short {i+1}"),
                description=short_seo.get("description", ""),
                tags=short_seo.get("tags", []),
                privacy="private",
                publish_at=req.publish_at if req.publish_at else None,
            )
            short_ids.append(short_resp.get("id"))

        job["status"] = "published"
        job["youtube_video_id"] = video_id
        job["youtube_short_ids"] = short_ids
        job["published_at"] = datetime.utcnow().isoformat()
        save_jobs(jobs)

        log_event(f"Job {job_id} - Published. Video: {video_id}, Shorts: {short_ids}")
        return {"status": "published", "video_id": video_id, "short_ids": short_ids}

    except Exception as e:
        log_event(f"Job {job_id} - Upload failed: {type(e).__name__}")
        raise HTTPException(status_code=500, detail="YouTube upload failed. Check logs.")


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


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000)
