import os
import json
import io
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload

BACKGROUNDS = {
    "backgrounds/minecraft.mp4":      os.environ.get("GDRIVE_MINECRAFT_ID", ""),
    "backgrounds/subway_surfers.mp4": os.environ.get("GDRIVE_SUBWAY_ID", ""),
}


def get_service():
    raw = os.environ.get("GDRIVE_SERVICE_ACCOUNT", "").strip()
    if not raw:
        raise ValueError("GDRIVE_SERVICE_ACCOUNT is empty or not set")
    creds_json = json.loads(raw)
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
        print(f"  {int(status.progress() * 100)}%")
    fh.close()


if __name__ == "__main__":
    os.makedirs("backgrounds", exist_ok=True)
    service = get_service()
    print("Auth OK")

    for path, file_id in BACKGROUNDS.items():
        if not file_id:
            print(f"SKIP {path} — no file ID")
            continue

        print(f"Downloading {path}...")
        download_file(service, file_id, path)
        size_mb = os.path.getsize(path) / (1024 * 1024)
        print(f"OK — {size_mb:.1f} MB")

        os.remove(path)
        print(f"Deleted {path}")

    print("Test passed.")
