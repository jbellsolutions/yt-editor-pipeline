"""
Community post automation via Claude Computer Use.

Uses Claude's computer_use_2025_01_24 tool to visually navigate YouTube Studio
and post community updates. No brittle CSS selectors — Claude sees the screen
and adapts to UI changes.

Architecture:
1. Playwright provides the browser (headless Chromium)
2. Claude Computer Use provides the "eyes and hands" — takes screenshots,
   decides where to click, types text, uploads images
3. This module orchestrates the loop: screenshot → Claude → action → repeat

Requirements:
- pip install playwright anthropic && playwright install chromium
- ANTHROPIC_API_KEY env var
- YouTube cookies exported via export_browser_cookies()

Usage:
    from engines.community_poster import post_community_updates
    results = post_community_updates(posts)
"""
import base64
import json
import logging
import os
import time
from typing import List, Optional

import anthropic

logger = logging.getLogger(__name__)

YOUTUBE_STUDIO_URL = "https://studio.youtube.com"
COOKIE_PATH = os.environ.get(
    "YT_COOKIE_PATH", "/opt/yt-editor/backend/config/youtube_cookies.json"
)
MAX_STEPS_PER_POST = 25  # Safety limit to prevent infinite loops
SCREENSHOT_DELAY = 2  # Seconds to wait after each action before screenshotting


def post_community_updates(
    posts: List[dict],
    cookie_path: str = COOKIE_PATH,
) -> List[dict]:
    """Post community updates to YouTube Studio using Claude Computer Use.

    Each post dict should have:
        - text: str (the post content)
        - frame_image: Optional[str] (path to frame-based image)
        - ai_image: Optional[str] (path to AI-generated image)

    Returns list of results, each with:
        - index: int
        - status: "posted" | "failed"
        - error: Optional[str]
    """
    if not posts:
        return []

    # Validate dependencies
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        logger.error("Playwright not installed. Run: pip install playwright && playwright install chromium")
        return [{"index": i, "status": "failed", "error": "playwright not installed"}
                for i in range(len(posts))]

    if not os.environ.get("ANTHROPIC_API_KEY"):
        logger.error("ANTHROPIC_API_KEY not set — needed for Computer Use")
        return [{"index": i, "status": "failed", "error": "ANTHROPIC_API_KEY not set"}
                for i in range(len(posts))]

    if not os.path.exists(cookie_path):
        logger.error(f"YouTube cookies not found at {cookie_path}. Run export_browser_cookies() first.")
        return [{"index": i, "status": "failed", "error": "cookies not found"}
                for i in range(len(posts))]

    results = []
    client = anthropic.Anthropic()

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            viewport={"width": 1280, "height": 900},
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            ),
        )

        # Load cookies
        try:
            with open(cookie_path) as f:
                cookies = json.load(f)
            context.add_cookies(cookies)
            logger.info("YouTube cookies loaded")
        except Exception as e:
            logger.error(f"Failed to load cookies: {e}")
            browser.close()
            return [{"index": i, "status": "failed", "error": f"cookie load failed: {e}"}
                    for i in range(len(posts))]

        page = context.new_page()

        for i, post in enumerate(posts):
            try:
                result = _post_with_computer_use(page, client, post, i)
                results.append(result)
                if i < len(posts) - 1:
                    time.sleep(3)
            except Exception as e:
                logger.error(f"Community post {i} failed: {e}", exc_info=True)
                results.append({"index": i, "status": "failed", "error": str(e)})

        browser.close()

    return results


def _take_screenshot(page) -> str:
    """Take a screenshot and return as base64."""
    screenshot_bytes = page.screenshot(type="png")
    return base64.b64encode(screenshot_bytes).decode("utf-8")


def _execute_action(page, action: dict) -> None:
    """Execute a computer use action on the Playwright page."""
    action_type = action.get("type")

    if action_type == "click":
        x = action["x"]
        y = action["y"]
        button = action.get("button", "left")
        pw_button = "left" if button == "left" else "right"
        page.mouse.click(x, y, button=pw_button)

    elif action_type == "double_click":
        page.mouse.dblclick(action["x"], action["y"])

    elif action_type == "type":
        page.keyboard.type(action["text"], delay=15)

    elif action_type == "key":
        # Map common key names to Playwright format
        key = action["key"]
        key_map = {
            "Return": "Enter",
            "space": " ",
            "Tab": "Tab",
            "Escape": "Escape",
            "Backspace": "Backspace",
        }
        page.keyboard.press(key_map.get(key, key))

    elif action_type == "scroll":
        x = action.get("x", 640)
        y = action.get("y", 450)
        delta_x = action.get("delta_x", 0)
        delta_y = action.get("delta_y", 0)
        page.mouse.wheel(delta_x, delta_y)

    elif action_type == "move":
        page.mouse.move(action["x"], action["y"])

    elif action_type == "screenshot":
        pass  # We take screenshots separately

    else:
        logger.warning(f"Unknown action type: {action_type}")


def _post_with_computer_use(
    page, client: anthropic.Anthropic, post: dict, index: int
) -> dict:
    """Use Claude Computer Use to post a single community update."""
    text = post.get("text", "")
    image_path = post.get("ai_image") or post.get("frame_image")

    # Navigate to community tab
    page.goto(f"{YOUTUBE_STUDIO_URL}/channel/community", wait_until="networkidle")
    time.sleep(3)

    # Build the task prompt for Claude
    task = (
        f"You are on YouTube Studio's Community tab. Your task is to create a new community post.\n\n"
        f"POST TEXT:\n{text}\n\n"
    )
    if image_path and os.path.exists(image_path):
        task += (
            f"ALSO: After typing the text, you need to attach an image. "
            f"Click the image/photo icon button to open the file picker, "
            f"then I will handle the file upload.\n\n"
        )
    task += (
        "STEPS:\n"
        "1. Look at the page. Find and click the 'Create post' button or text area to start composing.\n"
        "2. Click in the text area and type the post text.\n"
        "3. If an image needs to be attached, click the image/photo upload button.\n"
        "4. Click the 'Post' button to publish.\n"
        "5. When the post is published, respond with DONE.\n\n"
        "If you see a login page instead of YouTube Studio, respond with ERROR: NOT_LOGGED_IN.\n"
        "If something goes wrong, respond with ERROR: <description>.\n"
    )

    messages = [{"role": "user", "content": task}]
    image_uploaded = False

    for step in range(MAX_STEPS_PER_POST):
        # Take screenshot
        screenshot_b64 = _take_screenshot(page)

        # Add screenshot to conversation
        messages.append({
            "role": "user",
            "content": [{
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": "image/png",
                    "data": screenshot_b64,
                },
            }, {
                "type": "text",
                "text": f"Here is the current screen. Step {step + 1}/{MAX_STEPS_PER_POST}. What action should I take next?",
            }],
        })

        # Ask Claude what to do
        response = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=1024,
            system=(
                "You are a browser automation agent. You see screenshots and output "
                "actions to interact with the page. Respond with a JSON action object "
                "or a text status.\n\n"
                "Action format: {\"type\": \"click\", \"x\": 640, \"y\": 450}\n"
                "Other types: \"type\" (with \"text\" field), \"key\" (with \"key\" field), "
                "\"scroll\" (with \"delta_y\" field), \"double_click\".\n\n"
                "When done, respond with just: DONE\n"
                "On error, respond with: ERROR: <reason>\n"
                "Respond with ONLY the action JSON or status text. No explanation."
            ),
            messages=messages,
        )

        response_text = response.content[0].text.strip()
        logger.info(f"Community post {index}, step {step}: {response_text[:100]}")

        # Add assistant response to conversation
        messages.append({"role": "assistant", "content": response_text})

        # Check for completion
        if response_text.startswith("DONE"):
            logger.info(f"Community post {index}: Posted successfully in {step + 1} steps")
            return {"index": index, "status": "posted", "steps": step + 1}

        if response_text.startswith("ERROR"):
            error = response_text.replace("ERROR:", "").strip()
            logger.error(f"Community post {index}: Claude reported error: {error}")
            return {"index": index, "status": "failed", "error": error}

        # Parse and execute action
        try:
            # Handle potential markdown wrapping
            action_text = response_text
            if action_text.startswith("```"):
                action_text = action_text.split("\n", 1)[-1].rsplit("```", 1)[0].strip()

            action = json.loads(action_text)
            _execute_action(page, action)

            # Special handling: if Claude clicked an image upload button,
            # use Playwright's file chooser to upload the image
            if (action.get("type") == "click" and image_path and
                    os.path.exists(image_path) and not image_uploaded):
                # Wait a moment and check if a file dialog appeared
                time.sleep(1)
                try:
                    file_input = page.query_selector('input[type="file"]')
                    if file_input:
                        file_input.set_input_files(image_path)
                        image_uploaded = True
                        logger.info(f"Community post {index}: Image uploaded via file input")
                        time.sleep(2)
                except Exception:
                    pass  # Not a file upload click, continue

            time.sleep(SCREENSHOT_DELAY)

        except json.JSONDecodeError:
            logger.warning(f"Community post {index}: Could not parse action: {response_text[:100]}")
            # Ask Claude to try again
            messages.append({
                "role": "user",
                "content": "That wasn't valid JSON. Please respond with a JSON action like {\"type\": \"click\", \"x\": 640, \"y\": 450} or DONE or ERROR.",
            })

    logger.error(f"Community post {index}: Exceeded {MAX_STEPS_PER_POST} steps")
    return {"index": index, "status": "failed", "error": f"exceeded {MAX_STEPS_PER_POST} steps"}


def export_browser_cookies(output_path: str = COOKIE_PATH):
    """Launch browser for manual login, then export cookies.

    Run once to capture YouTube login cookies:
        python -c "from engines.community_poster import export_browser_cookies; export_browser_cookies()"
    """
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("Install playwright: pip install playwright && playwright install chromium")
        return

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        context = browser.new_context()
        page = context.new_page()

        page.goto("https://accounts.google.com")
        print("\n=== Manual Login Required ===")
        print("1. Log into your Google/YouTube account in the browser window")
        print("2. Navigate to https://studio.youtube.com")
        print("3. Once you see YouTube Studio, press Enter here to save cookies\n")
        input("Press Enter after logging in...")

        cookies = context.cookies()
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        with open(output_path, "w") as f:
            json.dump(cookies, f, indent=2)
        os.chmod(output_path, 0o600)
        print(f"Cookies saved to {output_path}")

        browser.close()
