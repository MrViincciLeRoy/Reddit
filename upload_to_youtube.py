import json
import os
import pickle
import sys

from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

TOKEN_PATH    = "token.pkl"
METADATA_PATH = "results/metadata.json"

TAGS = [
    "AITA", "AmITheAsshole", "Reddit", "RedditStories", "Shorts",
    "RedditStorytime", "Story", "Storytime", "AskReddit", "Confession",
    "Funny", "Comedy", "Satisfying", "Viral", "RedditReport",
    "AITAReddit", "AskRedditStories", "ASMR", "rAITA", "Short",
    "RedditTop", "TIFU", "TodayIFuckedUp", "RelationshipAdvice",
    "EntitledParents", "PettyRevenge", "MaliciousCompliance",
]

DESCRIPTION_TEMPLATE = """{title}

Watch till the end and drop your verdict below! 👇

#Shorts #AITA #AmITheAsshole #Reddit #RedditStories #RedditStorytime
#Story #Storytime #AskReddit #Confession #Funny #Comedy #viral #relationship #relationshipdrama #family #neighbor 
#AITAReddit #RedditReport #rAITA #EntitledPeople #PettyRevenge #Drama #aita #NTA #YATA #judge #female #femaledrama #USA #texas #newyork"""


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
    # #Shorts must be in both title AND description for YouTube to classify it
    shorts_title = title if title.endswith("#Shorts") else f"{title} #Shorts"
    shorts_title = shorts_title[:100]

    description = DESCRIPTION_TEMPLATE.format(title=title)

    body = {
        "snippet": {
            "title":          shorts_title,
            "description":    description,
            "tags":           TAGS,
            "categoryId":     "24",  # Entertainment
            "defaultLanguage": "en",
            "defaultAudioLanguage": "en",
        },
        "status": {
            "privacyStatus":           privacy,
            "selfDeclaredMadeForKids": False,
            "madeForKids":             False,
        },
    }

    media = MediaFileUpload(
        file_path, mimetype="video/mp4",
        resumable=True, chunksize=8 * 1024 * 1024
    )
    request = youtube.videos().insert(
        part="snippet,status", body=body, media_body=media
    )

    print(f"\nUploading: {file_path}  [{privacy}]")
    print(f"  Title: {shorts_title}")

    response = None
    while response is None:
        status, response = request.next_chunk()
        if status:
            print(f"  Progress: {int(status.progress() * 100)}%")

    video_id = response.get("id", "unknown")
    print(f"  ✓ https://www.youtube.com/shorts/{video_id}")
    return video_id


def main():
    if not os.path.exists(METADATA_PATH):
        print(f"No metadata at {METADATA_PATH} — nothing to upload.")
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
        try:
            vid_id = upload_video(youtube, item["file"], item["yt_title"], item.get("privacy", "public"))
            uploaded.append(vid_id)
        except Exception as e:
            print(f"  ✗ Failed {item['file']}: {e}")
            failed.append(item["file"])

    print(f"\n── Summary ──")
    print(f"  Uploaded : {len(uploaded)}")
    print(f"  Failed   : {len(failed)}")
    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
