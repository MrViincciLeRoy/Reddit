import os
import pickle
import sys

from google.auth.transport.requests import Request
from googleapiclient.discovery import build

TOKEN_PATH = "token.pkl"


def get_service():
    if not os.path.exists(TOKEN_PATH):
        raise FileNotFoundError(f"{TOKEN_PATH} not found")
    with open(TOKEN_PATH, "rb") as f:
        creds = pickle.load(f)
    if creds.expired and creds.refresh_token:
        print("Token expired — refreshing...")
        creds.refresh(Request())
        with open(TOKEN_PATH, "wb") as f:
            pickle.dump(creds, f)
    return build("youtube", "v3", credentials=creds)


def get_non_public_videos(youtube):
    non_public = []
    page_token = None

    while True:
        params = {
            "part": "id,snippet,status",
            "mine": True,
            "type": "video",
            "maxResults": 50,
        }
        if page_token:
            params["pageToken"] = page_token

        response = youtube.search().list(**params).execute()

        for item in response.get("items", []):
            video_id = item["id"].get("videoId")
            if not video_id:
                continue

            # search() doesn't return status, fetch it separately
            vid_resp = youtube.videos().list(
                part="status,snippet",
                id=video_id
            ).execute()

            for v in vid_resp.get("items", []):
                status = v["status"]["privacyStatus"]
                if status in ("unlisted", "private"):
                    non_public.append({
                        "id":      video_id,
                        "title":   v["snippet"]["title"],
                        "privacy": status,
                    })

        page_token = response.get("nextPageToken")
        if not page_token:
            break

    return non_public


def publish_video(youtube, video_id, title):
    youtube.videos().update(
        part="status",
        body={
            "id": video_id,
            "status": {"privacyStatus": "public"},
        }
    ).execute()
    print(f"  ✓ Published: [{video_id}] {title}")


def main():
    youtube = get_service()

    print("Scanning channel for unlisted/private videos...")
    videos = get_non_public_videos(youtube)

    if not videos:
        print("Nothing to publish — all videos are already public.")
        sys.exit(0)

    print(f"Found {len(videos)} non-public video(s):")
    for v in videos:
        print(f"  [{v['privacy']}] {v['id']} — {v['title']}")

    published, failed = [], []
    for v in videos:
        try:
            publish_video(youtube, v["id"], v["title"])
            published.append(v["id"])
        except Exception as e:
            print(f"  ✗ Failed {v['id']}: {e}")
            failed.append(v["id"])

    print(f"\n── Summary ──────────────────────────────")
    print(f"  Published : {len(published)}")
    print(f"  Failed    : {len(failed)}")

    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
