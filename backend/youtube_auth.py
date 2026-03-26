import os
import json
import logging
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

logger = logging.getLogger("yt-pipeline")

CONFIG_DIR = os.environ.get("CONFIG_DIR", "/opt/yt-editor/backend/config")
CLIENT_SECRET = os.path.join(CONFIG_DIR, "client_secret.json")
TOKEN_FILE = os.path.join(CONFIG_DIR, "youtube_token.json")
REDIRECT_URI = os.environ.get("OAUTH_REDIRECT_URI", "http://localhost:8000/auth/callback")

SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube.force-ssl",
]


def get_auth_url():
    flow = Flow.from_client_secrets_file(
        CLIENT_SECRET, scopes=SCOPES,
        redirect_uri=REDIRECT_URI
    )
    auth_url, _ = flow.authorization_url(
        access_type="offline", include_granted_scopes="true", prompt="consent"
    )
    return auth_url


def handle_callback(code: str):
    flow = Flow.from_client_secrets_file(
        CLIENT_SECRET, scopes=SCOPES,
        redirect_uri=REDIRECT_URI
    )
    flow.fetch_token(code=code)
    creds = flow.credentials
    token_data = {
        "token": creds.token,
        "refresh_token": creds.refresh_token,
        "token_uri": creds.token_uri,
        "client_id": creds.client_id,
        "client_secret": creds.client_secret,
        "scopes": list(creds.scopes) if creds.scopes else [],
    }
    with open(TOKEN_FILE, "w") as f:
        json.dump(token_data, f, indent=2)
    os.chmod(TOKEN_FILE, 0o600)
    logger.info("YouTube token saved")
    return True


def get_youtube_service():
    if not os.path.exists(TOKEN_FILE):
        return None
    with open(TOKEN_FILE, "r") as f:
        token_data = json.load(f)
    creds = Credentials(
        token=token_data["token"],
        refresh_token=token_data["refresh_token"],
        token_uri=token_data["token_uri"],
        client_id=token_data["client_id"],
        client_secret=token_data["client_secret"],
        scopes=token_data.get("scopes"),
    )
    return build("youtube", "v3", credentials=creds)


def upload_video(filepath: str, title: str, description: str, tags: list,
                 category_id: str = "22", privacy: str = "private",
                 publish_at: str = None):
    youtube = get_youtube_service()
    if not youtube:
        raise Exception("YouTube not authenticated. Visit /auth/youtube first.")

    body = {
        "snippet": {
            "title": title,
            "description": description,
            "tags": tags,
            "categoryId": category_id,
        },
        "status": {
            "privacyStatus": privacy,
        },
    }
    if publish_at and privacy == "private":
        body["status"]["privacyStatus"] = "private"
        body["status"]["publishAt"] = publish_at

    media = MediaFileUpload(filepath, chunksize=256 * 1024, resumable=True)
    request = youtube.videos().insert(
        part="snippet,status", body=body, media_body=media
    )
    response = None
    while response is None:
        _, response = request.next_chunk()

    logger.info(f"Uploaded video: {response.get('id')} - {title}")
    return response


def upload_thumbnail(video_id: str, thumbnail_path: str):
    youtube = get_youtube_service()
    if not youtube:
        raise Exception("YouTube not authenticated.")
    media = MediaFileUpload(thumbnail_path)
    youtube.thumbnails().set(videoId=video_id, media_body=media).execute()
    logger.info(f"Uploaded thumbnail for video: {video_id}")
