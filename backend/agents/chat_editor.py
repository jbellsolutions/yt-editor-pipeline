"""Chat-based YouTube editor agent -- conversational intake before pipeline."""

import re
from typing import Optional

# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------

EDITOR_SYSTEM_PROMPT = """\
You are a professional YouTube video editor working as part of an AI editing team. \
Your job is to have a friendly, focused conversation with the creator to gather everything \
needed before their video enters the editing pipeline.

PERSONALITY & TONE:
- Warm but efficient -- you respect the creator's time.
- Speak like a seasoned editor: you understand lower-thirds, J-cuts, B-roll, cold opens, \
jump cuts, text callouts, motion graphics, color grading, sound design, and pacing.
- Use casual professional language. No corporate jargon.

CONVERSATION FLOW:
1. Greet warmly: "Hey! I'm your editor. What are we working on?"
2. Get the video URL or file first -- you can't plan without seeing the content.
3. Ask about the GOAL next: what's this video trying to achieve?
4. Then AUDIENCE: who watches this channel?
5. Then STYLE preferences: fast cuts, cinematic, talking-head cleanup, etc.
6. Then SPECIFICS: any highlights to feature, graphics requests, reference videos.
7. Ask ONE focused question at a time -- don't overwhelm with a checklist.

SMART SUGGESTIONS:
- When you know the audience, suggest editing styles that work for them.
  Example: "Tech audience? I'd go with fast cuts, code overlays, and minimal B-roll."
- When you know the style, suggest specific techniques.
  Example: "For a cinematic vlog, I'll add smooth transitions, color grading, and ambient sound."
- Offer options when the creator seems unsure.

CONTEXT TRACKING:
When the creator provides information, embed context markers in your response. These markers \
are invisible to the creator but help the system track what's been gathered.

Format: [CONTEXT: key=value]

Valid keys: video_url, goal, audience, style, highlight, graphic, reference

Examples:
- [CONTEXT: video_url=https://youtube.com/watch?v=abc123]
- [CONTEXT: audience=tech professionals aged 25-40]
- [CONTEXT: style=fast-paced with text callouts]
- [CONTEXT: highlight=3:45-4:20 the product demo]
- [CONTEXT: graphic=lower-third intro card with channel name]
- [CONTEXT: reference=https://youtube.com/watch?v=xyz789]

IMPORTANT RULES:
- Place context markers at the END of your message, each on its own line.
- You can include multiple markers if the creator provided multiple pieces of info.
- Only add a marker when the creator has clearly stated something -- don't guess.

COMPLETION:
When you have enough context (at minimum: video URL, audience, and style), summarize the \
editing plan and say: "Ready when you are -- hit Start Editing!"

If the creator wants to start but you're missing critical info (especially the video URL), \
politely ask for it before proceeding.
"""

# ---------------------------------------------------------------------------
# Context marker pattern
# ---------------------------------------------------------------------------

_CONTEXT_PATTERN = re.compile(r"\[CONTEXT:\s*(\w+)=([^\]]+)\]")

# Keys that accumulate as lists rather than overwriting
_LIST_KEYS = {"highlight", "graphic", "reference"}

# Map from context marker keys to session context keys
_KEY_MAP = {
    "video_url": "video_url",
    "goal": "goal",
    "audience": "audience",
    "style": "style",
    "highlight": "highlights",
    "graphic": "graphics",
    "reference": "references",
}


# ---------------------------------------------------------------------------
# Public functions
# ---------------------------------------------------------------------------

def build_messages_for_claude(session) -> list:
    """Build Claude API messages from session history, injecting a context summary.

    The context summary is prepended as a system-style user message so Claude
    knows what has already been gathered.

    Args:
        session: A ChatSession instance.

    Returns:
        A list of message dicts suitable for the Claude messages API.
    """
    messages = []

    # If we have gathered context, inject a summary so the agent stays oriented
    ctx = session.context or {}
    gathered = []
    if ctx.get("video_url"):
        gathered.append(f"Video URL: {ctx['video_url']}")
    if ctx.get("goal"):
        gathered.append(f"Goal: {ctx['goal']}")
    if ctx.get("audience"):
        gathered.append(f"Audience: {ctx['audience']}")
    if ctx.get("style"):
        gathered.append(f"Style: {ctx['style']}")
    if ctx.get("highlights"):
        gathered.append(f"Highlights: {', '.join(ctx['highlights'])}")
    if ctx.get("graphics"):
        gathered.append(f"Graphics requests: {', '.join(ctx['graphics'])}")
    if ctx.get("references"):
        gathered.append(f"Reference videos: {', '.join(ctx['references'])}")

    if gathered:
        context_summary = (
            "[SYSTEM NOTE — gathered context so far]\n"
            + "\n".join(gathered)
            + "\n[END NOTE]"
        )
        messages.append({"role": "user", "content": context_summary})
        messages.append({
            "role": "assistant",
            "content": "Got it, I have that context noted. Let me continue our conversation.",
        })

    # Append the actual conversation history
    for msg in session.messages:
        role = msg.get("role", "user")
        content = msg.get("content", "")
        if role in ("user", "assistant"):
            messages.append({"role": role, "content": content})

    return messages


def extract_context_from_response(response_text: str, current_context: dict) -> dict:
    """Parse agent response to update editing context.

    Looks for [CONTEXT: key=value] markers in the response text and updates
    the context dict accordingly. List-type keys (highlights, graphics,
    references) accumulate; scalar keys overwrite.

    Args:
        response_text: The full text of the agent's response.
        current_context: The current session context dict.

    Returns:
        The updated context dict.
    """
    ctx = dict(current_context)  # shallow copy

    for match in _CONTEXT_PATTERN.finditer(response_text):
        raw_key = match.group(1).strip().lower()
        value = match.group(2).strip()

        mapped_key = _KEY_MAP.get(raw_key)
        if not mapped_key:
            continue

        if raw_key in _LIST_KEYS:
            # Accumulate into list, avoiding duplicates
            if not isinstance(ctx.get(mapped_key), list):
                ctx[mapped_key] = []
            if value not in ctx[mapped_key]:
                ctx[mapped_key].append(value)
        else:
            # Scalar overwrite
            ctx[mapped_key] = value

    return ctx


def get_editing_config(session) -> dict:
    """Convert session context into a pipeline-compatible config dict.

    This is a convenience wrapper -- the canonical implementation lives in
    chat.py. Import from there for the authoritative version.

    Args:
        session: A ChatSession instance.

    Returns:
        A dict with keys: video_url, instructions, graphics, audience, style,
        highlights, description_template, custom_description.
    """
    ctx = session.context or {}

    instructions_parts = []
    if ctx.get("goal"):
        instructions_parts.append(f"Goal: {ctx['goal']}")
    if ctx.get("audience"):
        instructions_parts.append(f"Target audience: {ctx['audience']}")
    if ctx.get("style"):
        instructions_parts.append(f"Style: {ctx['style']}")
    if ctx.get("highlights"):
        hl = ctx["highlights"]
        highlights_str = ", ".join(hl) if isinstance(hl, list) else hl
        instructions_parts.append(f"Highlights: {highlights_str}")

    return {
        "video_url": ctx.get("video_url"),
        "instructions": "\n".join(instructions_parts) if instructions_parts else "",
        "graphics": ctx.get("graphics", []),
        "audience": ctx.get("audience"),
        "style": ctx.get("style"),
        "highlights": ctx.get("highlights", []),
        "references": ctx.get("references", []),
        "attachments": ctx.get("attachments", []),
        "description_template": ctx.get("goal"),
        "custom_description": None,
        "session_id": session.session_id,
    }
