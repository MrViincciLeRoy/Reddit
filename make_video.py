import os
import re
import glob
import random
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

SUBREDDIT_NAMES = {
    "amitheasshole":    "Am I the Asshole",
    "tifu":             "Today I Fucked Up",
    "relationship_advice": "Relationship Advice",
    "maliciouscompliance": "Malicious Compliance",
    "pettyrevenge":     "Petty Revenge",
    "prorevenge":       "Pro Revenge",
    "entitledparents":  "Entitled Parents",
    "notifu":           "Not Today I Fucked Up",
    "confessions":      "Confessions",
    "AITA":      "Am I The A-hole",
    "offmychest":       "Off My Chest",
}

PROFANITY_MAP = {
    r"\bfuck\b":    "f*ck",
    r"\bfucked\b":  "f*cked",
    r"\bfucker\b":  "f*cker",
    r"\bfucking\b": "f*cking",
    r"\bfucks\b":   "f*cks",
    r"\bfuck'?s\b": "f*ck's",
    r"\bbitch\b":   "b*tch",
    r"\bbitches\b": "b*tches",
    r"\basshole\b": "a**hole",
    r"\bass\b":     "a**",
    r"\bcunt\b":    "c*nt",
    r"\bdick\b":    "d*ck",
    r"\bpussy\b":   "p*ssy",
    r"\bwhore\b":   "wh*re",
    r"\bslut\b":    "sl*t",
    r"\bcock\b":    "c*ck",
    r"\bnigga\b":   "n***a",
    r"\bnigger\b":  "n*****",
    r"\bfaggot\b":  "f*ggot",
    r"\bretard\b":  "r*tard",
    # "shit" intentionally excluded
}


def censor(text):
    for pattern, replacement in PROFANITY_MAP.items():
        text = re.sub(pattern, replacement, text, flags=re.IGNORECASE)
    return text


def full_subreddit_name(sub):
    return SUBREDDIT_NAMES.get(sub.lower(), sub)


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


def split_into_sentences(text):
    sentences = re.split(r'(?<=[.!?])\s+', text.strip())
    return [s.strip() for s in sentences if s.strip()]


def generate_tts_with_timing(pipeline, text, output_path):
    generator = pipeline(text, voice=VOICE, speed=1.0, split_pattern=r"\n+")
    chunks = []
    for _, _, audio in generator:
        chunks.append(audio)
    combined = np.concatenate(chunks)
    sf.write(output_path, combined, 24000)
    duration = len(combined) / 24000
    print(f"TTS saved: {output_path} ({duration:.1f}s)")
    return duration


def get_video_duration(path):
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", path],
        capture_output=True, text=True
    )
    return float(result.stdout.strip())


def get_random_start(bg_path, needed_duration):
    total = get_video_duration(bg_path)
    max_start = max(0, total - needed_duration - 1)
    return random.uniform(0, max_start)


def sanitize_drawtext(text):
    return re.sub(r"[':\"\\@%]", "", text)


def build_subtitle_drawtext(text, audio_duration, total_chars):
    sentences = split_into_sentences(text)
    if not sentences:
        return []

    drawtext_parts = []
    char_count = 0

    for sentence in sentences:
        sentence_chars = len(sentence)
        start_time = (char_count / total_chars) * audio_duration
        end_time = ((char_count + sentence_chars) / total_chars) * audio_duration
        char_count += sentence_chars + 1  # +1 for space

        words = sentence.split()
        if not words:
            continue

        sentence_duration = end_time - start_time
        word_duration = sentence_duration / len(words)

        safe_sentence = sanitize_drawtext(sentence)

        # Background box for the subtitle
        drawtext_parts.append(
            f"drawbox="
            f"x=(w-800)/2:y=(h/2)-60:"
            f"w=800:h=80:"
            f"color=black@0.55:t=fill:"
            f"enable='between(t,{start_time:.3f},{end_time:.3f})'"
        )

        # Full sentence (white)
        drawtext_parts.append(
            f"drawtext=text='{safe_sentence}':"
            f"fontsize=42:"
            f"fontcolor=white:"
            f"borderw=2:"
            f"bordercolor=black:"
            f"x=(w-text_w)/2:"
            f"y=(h/2)-40:"
            f"font=Arial:"
            f"enable='between(t,{start_time:.3f},{end_time:.3f})'"
        )

        # Highlight each word in yellow
        for wi, word in enumerate(words):
            word_start = start_time + wi * word_duration
            word_end   = word_start + word_duration
            safe_word  = sanitize_drawtext(word)

            # Calculate x offset for the word within the sentence
            prefix = " ".join(words[:wi])
            prefix_len = len(prefix) + (1 if prefix else 0)
            char_offset = prefix_len / max(len(sentence), 1)
            # approx pixel offset (rough ? ffmpeg doesn't expose text_w per word)
            x_expr = f"(w-text_w)/2+{int(char_offset * len(safe_sentence) * 22)}"

            drawtext_parts.append(
                f"drawtext=text='{safe_word}':"
                f"fontsize=42:"
                f"fontcolor=yellow:"
                f"borderw=2:"
                f"bordercolor=black:"
                f"x={x_expr}:"
                f"y=(h/2)-40:"
                f"font=Arial:"
                f"enable='between(t,{word_start:.3f},{word_end:.3f})'"
            )

    return drawtext_parts


def make_video(title, text, audio_path, audio_duration, background_path, output_path):
    duration = audio_duration + 0.5
    bg_start = get_random_start(background_path, duration)

    censored_text = censor(text)
    total_chars = max(len(censored_text), 1)

    subtitle_filters = build_subtitle_drawtext(censored_text, audio_duration, total_chars)

    scale_crop = "scale=-2:1920,crop=1080:1920"
    vf = scale_crop
    if subtitle_filters:
        vf += "," + ",".join(subtitle_filters)

    cmd = [
        "ffmpeg",
        "-ss", str(bg_start),
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

    print(f"Rendering: {output_path} (bg starts at {bg_start:.1f}s)")
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

    full_name = full_subreddit_name(subreddit)
    print(f"Subreddit: r/{subreddit} ? \"{full_name}\"")

    os.makedirs(OUT_DIR, exist_ok=True)
    os.makedirs("audio", exist_ok=True)

    posts = scrape_posts(subreddit, limit)
    pipeline = KPipeline(lang_code="a")

    for i, post in enumerate(posts):
        print(f"\n--- Post {i+1}/{len(posts)} ---")
        print(f"Title: {post['title']}")

        title_censored = censor(post["title"])
        body_censored  = censor(post["body"]) if post["body"] else ""

        text = title_censored
        if body_censored:
            text += ". " + body_censored

        audio_path  = f"audio/post_{i+1}.wav"
        output_path = f"{OUT_DIR}/video_{i+1}.mp4"
        bg_path     = pick_background(i)

        try:
            duration = generate_tts_with_timing(pipeline, text, audio_path)
            make_video(post["title"], text, audio_path, duration, bg_path, output_path)
        except Exception as e:
            print(f"Failed on post {i+1}: {e}")
            continue

    print(f"\nAll done. Videos in: {OUT_DIR}/")


if __name__ == "__main__":
    main()