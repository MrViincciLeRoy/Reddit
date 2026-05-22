import json
import os
import pickle
import sys

from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

TOKEN_PATH    = "token.pkl"
METADATA_PATH = "results/metadata.json"


def get_authenticated_service():
    if not os.path.exists(TOKEN_PATH):
        raise FileNotFoundError(f"{TOKEN_PATH} not found.")
    with open(TOKEN_PATH, "rb") as f:
        creds = pickle.load(f)
    if creds.expired and creds.refresh_token:
        print("Token expired — refreshing...")
        creds.refresh(Request())
        with open(TOKEN_PATH, "wb") as f:
            pickle.dump(creds, f)
    return build("youtube", "v3", credentials=creds)


def upload_video(youtube, file_path: str, title: str, privacy: str):
    shorts_title = f"{title} #Shorts"[:100]
    body = {
        "snippet": {
            "title":       shorts_title,
            "description": "#Shorts #Reddit #RedditStories #Story #Storytime #aita #satisfying #funny #comedy #askreddit #stories #redditstorytime #short #Redditreport #aitareddit #askredditstories #asmr #r/aita #viral",
            "tags":        ["AITA", "Reddit", "Shorts", "AmITheAsshole", "confession", "karma", "aita", "reddit stories"],
            "categoryId":  "24",
        },
        "status": {
            "privacyStatus":           privacy,
            "selfDeclaredMadeForKids": False,
        },
    }
    media   = MediaFileUpload(file_path, mimetype="video/mp4", resumable=True, chunksize=8 * 1024 * 1024)
    request = youtube.videos().insert(part="snippet,status", body=body, media_body=media)

    print(f"\nUploading: {file_path}  [{privacy}]")
    print(f"  Title: {title}")

    response = None
    while response is None:
        status, response = request.next_chunk()
        if status:
            print(f"  Progress: {int(status.progress() * 100)}%")

    video_id = response.get("id", "unknown")
    print(f"  ✓ https://www.youtube.com/watch?v={video_id}")
    return video_id


def main():
    if not os.path.exists(METADATA_PATH):
        print(f"No metadata found at {METADATA_PATH} — nothing to upload.")
        sys.exit(0)

    with open(METADATA_PATH, "r", encoding="utf-8") as f:
        metadata = json.load(f)

    to_upload = [m for m in metadata if m.get("success") and os.path.exists(m["file"])]
    if not to_upload:
        print("No successful videos to upload.")
        sys.exit(0)

    print(f"Found {len(to_upload)} video(s) to upload.")
    youtube = get_authenticated_service()

    uploaded, failed = [], []
    for item in to_upload:
        privacy = item.get("privacy", "public")
        try:
            vid_id = upload_video(youtube, item["file"], item["yt_title"], privacy)
            uploaded.append(vid_id)
        except Exception as e:
            print(f"  ✗ Failed to upload {item['file']}: {e}")
            failed.append(item["file"])

    print(f"\n── Summary ──────────────────────────────")
    print(f"  Uploaded : {len(uploaded)}")
    print(f"  Failed   : {len(failed)}")
    if failed:
        for f in failed:
            print(f"    {f}")
        sys.exit(1)


if __name__ == "__main__":
    main()
