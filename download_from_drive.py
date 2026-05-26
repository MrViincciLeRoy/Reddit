import os
import json
import io
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload

# IDs were swapped in secrets — GDRIVE_SUBWAY_ID actually holds the Minecraft
# footage and GDRIVE_MINECRAFT_ID holds GTA. References corrected here.
BACKGROUNDS = {
    "backgrounds/minecraft.mp4":      os.environ.get("GDRIVE_SUBWAY_ID", ""),
    "backgrounds/subway_surfers.mp4": os.environ.get("GDRIVE_MINECRAFT_ID", ""),
}


def get_service():
    raw = os.environ.get("GDRIVE_SERVICE_ACCOUNT", "").strip()
    if not raw:
        raise ValueError("GDRIVE_SERVICE_ACCOUNT secret is empty or not set")
    try:
        creds_json = json.loads(raw)
    except json.JSONDecodeError as e:
        raise ValueError(f"GDRIVE_SERVICE_ACCOUNT is not valid JSON: {e}\nFirst 50 chars: {repr(raw[:50])}")
    creds = service_account.Credentials.from_service_account_info(
        creds_json,
        scopes=["https://www.googleapis.com/auth/drive.readonly"]
    )
    return build("drive", "v3", credentials=creds)


def download_file(service, file_id, output_path):
    request = service.files().get_media(fileId=file_id)
    fh = io.FileIO(output_path, "wb")
    downloader = MediaIoBaseDownload(fh, request)
    done = False
    while not done:
        status, done = downloader.next_chunk()
        print(f"  {output_path}: {int(status.progress() * 100)}%")


if __name__ == "__main__":
    os.makedirs("backgrounds", exist_ok=True)
    service = get_service()

    for path, file_id in BACKGROUNDS.items():
        if not file_id:
            print(f"Skipping {path} — no file ID set")
            continue
        if os.path.exists(path):
            print(f"Already cached: {path}")
            continue
        print(f"Downloading {path}...")
        download_file(service, file_id, path)

    print("All backgrounds ready.")
