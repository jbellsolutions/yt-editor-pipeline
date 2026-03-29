"""
Transcription engine using OpenAI Whisper API.
"""
import logging
import os
import tempfile
from openai import OpenAI

from engines.ffmpeg_engine import extract_audio

logger = logging.getLogger(__name__)


def transcribe_video(video_path: str, job_id: str) -> dict:
    """Transcribe a video using OpenAI Whisper API.

    Returns dict with:
        - text: full transcript string
        - words: list of {"word": str, "start": float, "end": float}
        - segments: list of {"id": int, "start": float, "end": float, "text": str}
    """
    client = OpenAI()

    # Extract audio to temp file
    with tempfile.TemporaryDirectory() as tmpdir:
        audio_path = os.path.join(tmpdir, f"{job_id}_audio.mp3")
        extract_audio(video_path, audio_path, sample_rate=16000)

        logger.info(f"[{job_id}] Transcribing audio: {audio_path}")

        with open(audio_path, "rb") as audio_file:
            response = client.audio.transcriptions.create(
                model="whisper-1",
                file=audio_file,
                response_format="verbose_json",
                timestamp_granularities=["word", "segment"],
            )

    # Parse response
    result = {
        "text": response.text,
        "words": [],
        "segments": [],
    }

    # Extract word-level timestamps
    if hasattr(response, "words") and response.words:
        for w in response.words:
            result["words"].append({
                "word": w.word if hasattr(w, "word") else str(w.get("word", "")),
                "start": float(w.start if hasattr(w, "start") else w.get("start", 0)),
                "end": float(w.end if hasattr(w, "end") else w.get("end", 0)),
            })

    # Extract segment-level timestamps
    if hasattr(response, "segments") and response.segments:
        for s in response.segments:
            result["segments"].append({
                "id": int(s.id if hasattr(s, "id") else s.get("id", 0)),
                "start": float(s.start if hasattr(s, "start") else s.get("start", 0)),
                "end": float(s.end if hasattr(s, "end") else s.get("end", 0)),
                "text": str(s.text if hasattr(s, "text") else s.get("text", "")),
            })

    logger.info(
        f"[{job_id}] Transcription complete: {len(result['words'])} words, "
        f"{len(result['segments'])} segments"
    )
    return result
