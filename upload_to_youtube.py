"""
upload_to_youtube.py
--------------------
Uploads a video file to YouTube using a pre-existing OAuth token stored in
token.pkl (base64-decoded from the YOUTUBE_TOKEN GitHub secret).

Usage:
    python3 upload_to_youtube.py \
        --file results/video_1.mp4 \
        --title "My Reddit Story" \
        --privacy private
"""

import argparse
import pickle
import os
import sys

from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from google.auth.transport.requests import Request

TOKEN_PATH = "token.pkl"
SCOPES     = ["https://www.googleapis.com/auth/youtube.upload"]


def get_authenticated_service():
    if not os.path.exists(TOKEN_PATH):
        raise FileNotFoundError(
            f"{TOKEN_PATH} not found. "
            "Make sure the 'Write OAuth token to disk' step ran first."
        )

    with open(TOKEN_PATH, "rb") as f:
        creds = pickle.load(f)

    # Refresh if expired
    if creds.expired and creds.refresh_token:
        print("Token expired — refreshing...")
        creds.refresh(Request())
        # Persist the refreshed token so future runs don't have to refresh again
        with open(TOKEN_PATH, "wb") as f:
            pickle.dump(creds, f)
        print("Token refreshed and saved.")

    return build("youtube", "v3", credentials=creds)


def upload_video(youtube, file_path, title, description="", privacy="private", category_id="22"):
    """
    category_id 22 = People & Blogs (a safe default for Reddit content).
    See https://developers.google.com/youtube/v3/docs/videoCategories/list
    """
    body = {
        "snippet": {
            "title":       title,
            "description": description,
            "categoryId":  category_id,
        },
        "status": {
            "privacyStatus":          privacy,
            "selfDeclaredMadeForKids": False,
        },
    }

    media = MediaFileUpload(
        file_path,
        mimetype="video/mp4",
        resumable=True,
        chunksize=8 * 1024 * 1024,   # 8 MB chunks
    )

    print(f"Uploading: {file_path}")
    print(f"  Title:   {title}")
    print(f"  Privacy: {privacy}")

    request  = youtube.videos().insert(part="snippet,status", body=body, media_body=media)
    response = None

    while response is None:
        status, response = request.next_chunk()
        if status:
            pct = int(status.progress() * 100)
            print(f"  Progress: {pct}%")

    video_id  = response.get("id", "unknown")
    video_url = f"https://www.youtube.com/watch?v={video_id}"
    print(f"\nUpload complete!")
    print(f"  Video ID:  {video_id}")
    print(f"  Video URL: {video_url}")
    return video_id


def main():
    parser = argparse.ArgumentParser(description="Upload a video to YouTube.")
    parser.add_argument("--file",    required=True,              help="Path to the .mp4 file")
    parser.add_argument("--title",   required=True,              help="Video title")
    parser.add_argument("--desc",    default="",                 help="Video description")
    parser.add_argument("--privacy", default="private",
                        choices=["public", "private", "unlisted"], help="Privacy setting")
    args = parser.parse_args()

    if not os.path.exists(args.file):
        print(f"ERROR: File not found: {args.file}", file=sys.stderr)
        sys.exit(1)

    youtube = get_authenticated_service()
    upload_video(youtube, args.file, args.title, args.desc, args.privacy)


if __name__ == "__main__":
    main()
