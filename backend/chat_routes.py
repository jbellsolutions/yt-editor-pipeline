"""Chat API routes -- SSE streaming for editor agent conversation."""

import json
import uuid
from typing import Optional

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
import anthropic

from chat import ChatSession, create_session, load_session, save_session, add_message, get_editing_config
from agents.chat_editor import EDITOR_SYSTEM_PROMPT, build_messages_for_claude, extract_context_from_response

chat_router = APIRouter()


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------

class AttachmentItem(BaseModel):
    type: str  # "url" or "file"
    value: str


class SendMessageRequest(BaseModel):
    content: str
    attachments: Optional[list[AttachmentItem]] = None


class SessionResponse(BaseModel):
    session_id: str


class StartEditingResponse(BaseModel):
    job_id: str
    status: str


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_session_or_404(session_id: str) -> ChatSession:
    """Load a session or raise HTTP 404."""
    try:
        return load_session(session_id)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"Session {session_id} not found")


async def _generate_response(session: ChatSession, user_message: str):
    """Stream the editor agent response via SSE tokens.

    Yields Server-Sent Events in the format:
        data: {"type": "token", "content": "..."}
        data: {"type": "done"}
    """
    # Add user message to session
    add_message(session, role="user", content=user_message)

    # Build the messages array for Claude
    messages = build_messages_for_claude(session)

    # Call Claude with streaming
    client = anthropic.Anthropic()
    full_response = ""

    with client.messages.stream(
        model="claude-sonnet-4-20250514",
        max_tokens=1000,
        system=EDITOR_SYSTEM_PROMPT,
        messages=messages,
    ) as stream:
        for text in stream.text_stream:
            full_response += text
            yield f"data: {json.dumps({'type': 'token', 'content': text})}\n\n"

    # Extract context updates from the response
    session.context = extract_context_from_response(full_response, session.context)

    # Strip context markers from the stored response before saving
    import re
    clean_response = re.sub(r"\[CONTEXT:\s*[^\]]+\]", "", full_response).strip()

    # Save assistant message to session
    add_message(session, role="assistant", content=clean_response)

    yield f"data: {json.dumps({'type': 'done'})}\n\n"


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@chat_router.post("/sessions", response_model=SessionResponse)
async def create_new_session():
    """Create a new chat session and return its ID."""
    session = create_session()
    return SessionResponse(session_id=session.session_id)


@chat_router.post("/sessions/{session_id}/messages")
async def send_message(session_id: str, body: SendMessageRequest):
    """Send a user message and stream back the agent response via SSE."""
    session = _get_session_or_404(session_id)

    # Record any attachments in the session context
    if body.attachments:
        for att in body.attachments:
            entry = {"type": att.type, "value": att.value}
            if entry not in session.context.get("attachments", []):
                session.context.setdefault("attachments", []).append(entry)
        save_session(session)

    return StreamingResponse(
        _generate_response(session, body.content),
        media_type="text/event-stream",
    )


@chat_router.get("/sessions/{session_id}")
async def get_session(session_id: str):
    """Return the full session including messages and gathered context."""
    session = _get_session_or_404(session_id)
    return {
        "session_id": session.session_id,
        "messages": session.messages,
        "context": session.context,
        "created_at": session.created_at,
        "updated_at": session.updated_at,
    }


@chat_router.post("/sessions/{session_id}/start", response_model=StartEditingResponse)
async def start_editing(session_id: str):
    """Create a pipeline job from the session's gathered context.

    This is the equivalent of /api/ingest but uses the enriched config
    assembled through the chat conversation.
    """
    session = _get_session_or_404(session_id)
    config = get_editing_config(session)

    # Validate that we have at minimum a video URL
    if not config.get("video_url"):
        raise HTTPException(
            status_code=400,
            detail="Cannot start editing without a video URL. Ask the user to provide one first.",
        )

    # Create a job entry (mirrors the ingest endpoint pattern)
    job_id = str(uuid.uuid4())
    job = {
        "job_id": job_id,
        "status": "queued",
        "config": config,
        "session_id": session_id,
    }

    # Persist the job to the data directory
    import os
    from pathlib import Path

    data_dir = os.environ.get("DATA_DIR", "/opt/yt-editor/data")
    jobs_dir = Path(data_dir) / "jobs"
    jobs_dir.mkdir(parents=True, exist_ok=True)

    job_path = jobs_dir / f"{job_id}.json"
    with open(job_path, "w", encoding="utf-8") as f:
        json.dump(job, f, indent=2, ensure_ascii=False)

    return StartEditingResponse(job_id=job_id, status="queued")
