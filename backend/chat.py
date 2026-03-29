"""Chat session manager for the editor agent intake conversation."""

import json
import os
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

DATA_DIR = os.environ.get("DATA_DIR", "/opt/yt-editor/data")


@dataclass
class ChatSession:
    """Represents an active chat session with the editor agent."""

    session_id: str
    messages: list = field(default_factory=list)
    context: dict = field(default_factory=lambda: {
        "video_url": None,
        "goal": None,
        "audience": None,
        "style": None,
        "highlights": [],
        "graphics": [],
        "references": [],
        "attachments": [],
    })
    created_at: str = ""
    updated_at: str = ""


def _sessions_dir() -> Path:
    """Return the directory where chat sessions are stored, creating it if needed."""
    d = Path(DATA_DIR) / "chat_sessions"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _session_path(session_id: str) -> Path:
    """Return the file path for a given session ID."""
    return _sessions_dir() / f"{session_id}.json"


def _now_iso() -> str:
    """Return the current UTC time as an ISO 8601 string."""
    return datetime.now(timezone.utc).isoformat()


def create_session() -> ChatSession:
    """Create a new chat session and persist it."""
    session = ChatSession(
        session_id=str(uuid.uuid4()),
        created_at=_now_iso(),
        updated_at=_now_iso(),
    )
    save_session(session)
    return session


def load_session(session_id: str) -> ChatSession:
    """Load a chat session from disk by its ID.

    Raises FileNotFoundError if the session does not exist.
    """
    path = _session_path(session_id)
    if not path.exists():
        raise FileNotFoundError(f"Chat session not found: {session_id}")

    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    return ChatSession(
        session_id=data["session_id"],
        messages=data.get("messages", []),
        context=data.get("context", {}),
        created_at=data.get("created_at", ""),
        updated_at=data.get("updated_at", ""),
    )


def save_session(session: ChatSession) -> None:
    """Persist a chat session to disk as JSON."""
    session.updated_at = _now_iso()
    path = _session_path(session.session_id)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(asdict(session), f, indent=2, ensure_ascii=False)


def add_message(
    session: ChatSession,
    role: str,
    content: str,
    metadata: Optional[dict] = None,
) -> None:
    """Append a message to the session and save."""
    message = {
        "role": role,
        "content": content,
        "timestamp": _now_iso(),
    }
    if metadata:
        message["metadata"] = metadata
    session.messages.append(message)
    save_session(session)


def get_editing_config(session: ChatSession) -> dict:
    """Extract the structured editing config from session context for pipeline submission.

    Returns a dict compatible with the pipeline's expected job configuration.
    """
    ctx = session.context

    # Build the instruction string from gathered context
    instructions_parts = []
    if ctx.get("goal"):
        instructions_parts.append(f"Goal: {ctx['goal']}")
    if ctx.get("audience"):
        instructions_parts.append(f"Target audience: {ctx['audience']}")
    if ctx.get("style"):
        instructions_parts.append(f"Style: {ctx['style']}")
    if ctx.get("highlights"):
        highlights_str = ", ".join(ctx["highlights"]) if isinstance(ctx["highlights"], list) else ctx["highlights"]
        instructions_parts.append(f"Highlights: {highlights_str}")

    instructions = "\n".join(instructions_parts) if instructions_parts else ""

    # Build the description template from context
    description_parts = []
    if ctx.get("goal"):
        description_parts.append(ctx["goal"])
    if ctx.get("audience"):
        description_parts.append(f"For {ctx['audience']}")

    config = {
        "video_url": ctx.get("video_url"),
        "instructions": instructions,
        "graphics": ctx.get("graphics", []),
        "audience": ctx.get("audience"),
        "style": ctx.get("style"),
        "highlights": ctx.get("highlights", []),
        "references": ctx.get("references", []),
        "attachments": ctx.get("attachments", []),
        "description_template": "\n".join(description_parts) if description_parts else None,
        "custom_description": None,
        "session_id": session.session_id,
    }

    return config
