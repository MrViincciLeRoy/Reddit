# Reddit Video Generator and Publisher

This project generates videos from Reddit posts and publishes them to YouTube.

## Key Features
- Generates videos from Reddit posts
- Publishes videos to YouTube
- Supports multiple subreddits and video templates
- Uses Kokoro for text-to-speech functionality
- Uses Google Drive for storing video backgrounds

## Tech Stack
- Python 3.x
- Google API Client Library
- Kokoro
- Pillow
- NumPy
- soundfile
- requests

## Installation
- Install Python 3.x
- Install required libraries: `pip install google-api-python-client pillow numpy soundfile requests`
- Set up Google API credentials and download the JSON key file
- Set up Kokoro and download the voice models

## Usage
- Set environment variables: `GDRIVE_SERVICE_ACCOUNT`, `GDRIVE_MINECRAFT_ID`, `GDRIVE_SUBWAY_ID`, etc.
- Run `download_from_drive.py` to download video backgrounds from Google Drive
- Run `make_video.py` to generate videos from Reddit posts
- Run `upload_to_youtube.py` to upload videos to YouTube
- Run `publish_unlisted.py` to publish unlisted videos

## Environment Variables
- `GDRIVE_SERVICE_ACCOUNT`: Google Drive service account JSON key file
- `GDRIVE_MINECRAFT_ID`: Google Drive file ID for Minecraft background video
- `GDRIVE_SUBWAY_ID`: Google Drive file ID for Subway background video
- `KOKORO_VOICES`: Kokoro voice models to use for text-to-speech functionality
- `SUBREDDIT_NAMES`: Subreddits to generate videos from
- `PROFANITY_MAP`: Profanity filter to use for video titles and descriptions