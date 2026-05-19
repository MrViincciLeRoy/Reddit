import os
import re
import glob
import subprocess
import requests
import soundfile as sf
from kokoro import KPipeline
import numpy as np

PROXIES = {
    "http":  "socks5h://127.0.0.1:9050",
    "https": "socks5h://127.0.0.1:9050",
}
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
}

VOICE   = "af_heart"
OUT_DIR = "results"


def scrape_posts(subreddit, limit):
    url = f"https://www.reddit.com/r/{subreddit}/top.json?limit={limit}&t=day"
    r = requests.get(url, headers=HEADERS, proxies=PROXIES, timeout=30)
    r.raise_for_status()
    posts = []
    for item in r.json()["data"]["children"]:
        d = item["data"]
        posts.append({
            "title":    d["title"],
            "score":    d["score"],
            "comments": d["num_comments"],
            "url":      f"https://reddit.com{d['permalink']}",
            "body":     d.get("selftext", "")[:800],
        })
    print(f"Fetched {len(posts)} posts from r/{subreddit}")
    return posts


def generate_tts(pipeline, text, output_path):
    generator = pipeline(text, voice=VOICE, speed=1.0, split_pattern=r"\n+")
    chunks = []
    for _, _, audio in generator:
        chunks.append(audio)
    combined = np.concatenate(chunks)
    sf.write(output_path, combined, 24000)
    duration = len(combined) / 24000
    print(f"TTS saved: {output_path} ({duration:.1f}s)")


def get_duration(audio_path):
    data, rate = sf.read(audio_path)
    return len(data) / rate


def wrap_text(text, max_chars=35):
    words = text.split()
    lines, line = [], ""
    for word in words:
        if len(line) + len(word) + 1 > max_chars:
            lines.append(line.strip())
            line = ""
        line += word + " "
    if line.strip():
        lines.append(line.strip())
    return lines


def sanitize(text):
    return re.sub(r"[':\"\\]", "", text)


def make_video(title, audio_path, background_path, output_path):
    duration = get_duration(audio_path) + 0.5
    lines = wrap_text(sanitize(title))
    total_height = len(lines) * 70

    drawtext_parts = []
    for i, line in enumerate(lines):
        y = f"(h-{total_height})/2+{i * 70}"
        drawtext_parts.append(
            f"drawtext=text='{line}':"
            f"fontsize=52:"
            f"fontcolor=white:"
            f"borderw=4:"
            f"bordercolor=black:"
            f"x=(w-text_w)/2:"
            f"y={y}:"
            f"font=Arial"
        )

    # Scale landscape (1920x1080) up so height=1920, then crop center 1080px wide for 9:16
    vf = "scale=-2:1920,crop=1080:1920," + ",".join(drawtext_parts)

    cmd = [
        "ffmpeg",
        "-stream_loop", "-1",
        "-i", background_path,
        "-i", audio_path,
        "-vf", vf,
        "-map", "0:v",
        "-map", "1:a",
        "-t", str(duration),
        "-shortest",
        "-c:v", "libx264",
        "-preset", "fast",
        "-crf", "23",
        "-c:a", "aac",
        "-b:a", "128k",
        "-y", output_path
    ]

    print(f"Rendering: {output_path}")
    result = subprocess.run(cmd, capture_output=False)
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg failed with exit code {result.returncode}")

    size_mb = os.path.getsize(output_path) / (1024 * 1024)
    if size_mb == 0:
        raise RuntimeError(f"Output file is 0 bytes: {output_path}")
    print(f"Done: {output_path} ({size_mb:.1f} MB)")


def pick_background(index):
    backgrounds = sorted(glob.glob("backgrounds/*.mp4"))
    if not backgrounds:
        raise FileNotFoundError("No background videos found in backgrounds/")
    return backgrounds[index % len(backgrounds)]


def main():
    subreddit = os.environ.get("SUBREDDIT", "AmItheAsshole")
    limit = int(os.environ.get("LIMIT", "5"))

    os.makedirs(OUT_DIR, exist_ok=True)
    os.makedirs("audio", exist_ok=True)

    posts = scrape_posts(subreddit, limit)

    pipeline = KPipeline(lang_code="a")

    for i, post in enumerate(posts):
        print(f"\n--- Post {i+1}/{len(posts)} ---")
        print(f"Title: {post['title']}")

        text = post["title"]
        if post["body"]:
            text += ". " + post["body"]

        audio_path = f"audio/post_{i+1}.wav"
        output_path = f"{OUT_DIR}/video_{i+1}.mp4"
        bg_path = pick_background(i)

        try:
            generate_tts(pipeline, text, audio_path)
            make_video(post["title"], audio_path, bg_path, output_path)
        except Exception as e:
            print(f"Failed on post {i+1}: {e}")
            continue

    print(f"\nAll done. Videos in: {OUT_DIR}/")


if __name__ == "__main__":
    main()