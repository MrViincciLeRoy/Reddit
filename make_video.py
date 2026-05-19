import os
import re
import glob
import json
import random
import subprocess
import tempfile
import datetime
import requests
import soundfile as sf
from kokoro import KPipeline
import numpy as np
from PIL import Image, ImageDraw, ImageFont

PROXIES = {
    "http":  "socks5h://127.0.0.1:9050",
    "https": "socks5h://127.0.0.1:9050",
}
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
}

VOICE         = "af_heart"
OUT_DIR       = "results"
TRACKING_FILE = "data/seen_posts.json"
FONT_SIZE     = 52
MAX_WIDTH     = 900
VIDEO_W       = 1080
VIDEO_H       = 1920

SUBREDDIT_NAMES = {
    "amitheasshole":       "Am I the Asshole",
    "tifu":                "Today I Fucked Up",
    "relationship_advice": "Relationship Advice",
    "maliciouscompliance": "Malicious Compliance",
    "pettyrevenge":        "Petty Revenge",
    "prorevenge":          "Pro Revenge",
    "entitledparents":     "Entitled Parents",
    "confessions":         "Confessions",
    "AITA":                "Am I the A-hole",
    "offmychest":          "Off My Chest",
}

PROFANITY_MAP = {
    r"\bfuck\b":    "f*ck",
    r"\bfucked\b":  "f*cked",
    r"\bfucker\b":  "f*cker",
    r"\bfucking\b": "f*cking",
    r"\bfucks\b":   "f*cks",
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
}


# ?? Tracking helpers ??????????????????????????????????????????????????????????

def load_tracking():
    os.makedirs("data", exist_ok=True)
    if os.path.exists(TRACKING_FILE):
        with open(TRACKING_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"seen_posts": {}}


def save_tracking(tracking: dict):
    os.makedirs("data", exist_ok=True)
    with open(TRACKING_FILE, "w", encoding="utf-8") as f:
        json.dump(tracking, f, indent=2, ensure_ascii=False)
    print(f"Tracking saved ? {TRACKING_FILE} ({len(tracking['seen_posts'])} total posts)")


def mark_seen(tracking: dict, post: dict, subreddit: str, success: bool):
    tracking["seen_posts"][post["id"]] = {
        "title":        post["title"],
        "subreddit":    subreddit,
        "processed_at": datetime.datetime.utcnow().isoformat(timespec="seconds") + "Z",
        "success":      success,
    }


# ?? Reddit helpers ????????????????????????????????????????????????????????????

def censor(text):
    for pattern, replacement in PROFANITY_MAP.items():
        text = re.sub(pattern, replacement, text, flags=re.IGNORECASE)
    return text


def full_subreddit_name(sub):
    return SUBREDDIT_NAMES.get(sub.lower(), sub)


def expand_aita(title: str) -> str:
    """Replace AITA abbreviation with the full phrase for YouTube titles."""
    return re.sub(r'\bAITA\b', 'Am I The A-hole', title, flags=re.IGNORECASE)


def format_yt_title(raw_title: str) -> str:
    """Expand AITA and enforce YouTube's 100-char title limit."""
    title = expand_aita(raw_title)
    return title[:100]


def scrape_posts(subreddit, limit, seen_ids: set):
    fetch_n = min(limit * 3, 100)
    url = f"https://www.reddit.com/r/{subreddit}/top.json?limit={fetch_n}&t=day"
    r = requests.get(url, headers=HEADERS, proxies=PROXIES, timeout=30)
    r.raise_for_status()

    posts, skipped = [], 0
    for item in r.json()["data"]["children"]:
        d = item["data"]
        post_id = d["id"]
        if post_id in seen_ids:
            skipped += 1
            continue
        posts.append({
            "id":    post_id,
            "title": d["title"],
            "body":  d.get("selftext", "")[:800],
        })
        if len(posts) == limit:
            break

    print(f"Fetched {len(posts)} new posts from r/{subreddit} (skipped {skipped} already-seen)")
    return posts


# ?? Text / font helpers ???????????????????????????????????????????????????????

def split_sentences(text):
    return [s.strip() for s in re.split(r'(?<=[.!?])\s+', text.strip()) if s.strip()]


def get_font(size=FONT_SIZE, bold=False):
    candidates = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
        "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf" if bold else "/usr/share/fonts/truetype/freefont/FreeSans.ttf",
    ]
    for path in candidates:
        if os.path.exists(path):
            return ImageFont.truetype(path, size)
    return ImageFont.load_default()


def measure_text(draw, text, font):
    bbox = draw.textbbox((0, 0), text, font=font)
    return bbox[2] - bbox[0], bbox[3] - bbox[1]


def wrap_words(words, font, max_px):
    dummy = Image.new("RGBA", (1, 1))
    draw  = ImageDraw.Draw(dummy)
    lines, line = [], []
    for word in words:
        test = " ".join(line + [word])
        w, _ = measure_text(draw, test, font)
        if w > max_px and line:
            lines.append(line)
            line = [word]
        else:
            line.append(word)
    if line:
        lines.append(line)
    return lines


# ?? Frame rendering ???????????????????????????????????????????????????????????

def render_subtitle_frame(sentence, highlight_word_idx, font, font_bold):
    if not sentence:
        return Image.new("RGBA", (VIDEO_W, VIDEO_H), (0, 0, 0, 0))

    words  = sentence.split()
    lines  = wrap_words(words, font, MAX_WIDTH)

    pad_x, pad_y = 28, 18
    line_h  = FONT_SIZE + 12
    total_h = len(lines) * line_h

    dummy = Image.new("RGBA", (1, 1))
    draw  = ImageDraw.Draw(dummy)
    line_widths = [measure_text(draw, " ".join(ln), font)[0] for ln in lines]

    box_w = min(max(line_widths) + pad_x * 2, VIDEO_W - 40)
    box_h = total_h + pad_y * 2
    box_x = (VIDEO_W - box_w) // 2
    box_y = int(VIDEO_H * 0.62)

    img     = Image.new("RGBA", (VIDEO_W, VIDEO_H), (0, 0, 0, 0))
    overlay = Image.new("RGBA", (box_w, box_h), (0, 0, 0, 165))
    img.paste(overlay, (box_x, box_y), overlay)

    draw      = ImageDraw.Draw(img)
    global_wi = 0
    for li, line_words in enumerate(lines):
        lw, _    = measure_text(draw, " ".join(line_words), font)
        cursor_x = (VIDEO_W - lw) // 2
        text_y   = box_y + pad_y + li * line_h

        for word in line_words:
            is_hi = (global_wi == highlight_word_idx)
            color = (255, 220, 0, 255) if is_hi else (255, 255, 255, 255)
            ufont = font_bold if is_hi else font

            draw.text((cursor_x + 2, text_y + 2), word, font=ufont, fill=(0, 0, 0, 200))
            draw.text((cursor_x, text_y), word, font=ufont, fill=color)

            ww, _ = measure_text(draw, word, ufont)
            sw, _ = measure_text(draw, " ", font)
            cursor_x += ww + sw
            global_wi += 1

    return img


# ?? Video helpers ?????????????????????????????????????????????????????????????

def get_video_duration(path):
    r = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", path],
        capture_output=True, text=True
    )
    return float(r.stdout.strip())


def extract_random_bg_clip(bg_path, duration, output_path, fps=30):
    total = get_video_duration(bg_path)
    start = random.uniform(0, max(0, total - duration - 1))
    cmd = [
        "ffmpeg", "-ss", str(start), "-i", bg_path,
        "-t", str(duration),
        "-vf", "scale=-2:1920,crop=1080:1920",
        "-r", str(fps),
        "-c:v", "libx264", "-preset", "ultrafast", "-crf", "28",
        "-an", "-y", output_path
    ]
    print(f"  BG clip: {start:.1f}s for {duration:.1f}s")
    subprocess.run(cmd, capture_output=True, check=True)


def composite_subtitle_frames(bg_clip, frames_dir, audio_path, output_path, fps=30):
    cmd = [
        "ffmpeg",
        "-i", bg_clip,
        "-framerate", str(fps),
        "-i", os.path.join(frames_dir, "frame_%06d.png"),
        "-i", audio_path,
        "-filter_complex", "[0:v][1:v]overlay=0:0[v]",
        "-map", "[v]", "-map", "2:a",
        "-c:v", "libx264", "-preset", "fast", "-crf", "23",
        "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "128k",
        "-shortest", "-y", output_path
    ]
    result = subprocess.run(cmd, capture_output=False)
    if result.returncode != 0:
        raise RuntimeError(f"composite failed: {result.returncode}")


def build_timeline(text, audio_duration, fps=30):
    sentences    = split_sentences(text)
    total_chars  = max(sum(len(s) for s in sentences), 1)
    total_frames = int((audio_duration + 0.5) * fps)
    timeline     = []
    char_ptr     = 0

    for sentence in sentences:
        words = sentence.split()
        if not words:
            continue
        s_start = (char_ptr / total_chars) * audio_duration
        s_end   = ((char_ptr + len(sentence)) / total_chars) * audio_duration
        s_dur   = max(s_end - s_start, 0.01)
        wdur    = s_dur / len(words)
        for wi in range(len(words)):
            f_start = int((s_start + wi * wdur) * fps)
            f_end   = int((s_start + (wi + 1) * wdur) * fps)
            for f in range(f_start, f_end):
                timeline.append((sentence, wi))
        char_ptr += len(sentence) + 1

    while len(timeline) < total_frames:
        timeline.append(timeline[-1] if timeline else ("", 0))
    return timeline, total_frames


def make_video(text, audio_path, audio_duration, bg_path, output_path, fps=30):
    font      = get_font(FONT_SIZE, bold=False)
    font_bold = get_font(FONT_SIZE, bold=True)

    timeline, total_frames = build_timeline(text, audio_duration, fps)

    with tempfile.TemporaryDirectory() as frames_dir:
        bg_clip = os.path.join(frames_dir, "bg.mp4")
        extract_random_bg_clip(bg_path, audio_duration + 0.5, bg_clip, fps)

        print(f"  Rendering {total_frames} frames...")
        prev_state, prev_img = None, None
        for fi in range(total_frames):
            state = timeline[fi]
            if state != prev_state:
                prev_img   = render_subtitle_frame(state[0], state[1], font, font_bold)
                prev_state = state
            prev_img.save(os.path.join(frames_dir, f"frame_{fi:06d}.png"))

        print("  Compositing...")
        composite_subtitle_frames(bg_clip, frames_dir, audio_path, output_path, fps)

    size_mb = os.path.getsize(output_path) / (1024 * 1024)
    print(f"Done: {output_path} ({size_mb:.1f} MB)")


def generate_tts(pipeline, text, output_path):
    generator = pipeline(text, voice=VOICE, speed=1.0, split_pattern=r"\n+")
    chunks    = [audio for _, _, audio in generator]
    combined  = np.concatenate(chunks)
    sf.write(output_path, combined, 24000)
    duration = len(combined) / 24000
    print(f"TTS: {output_path} ({duration:.1f}s)")
    return duration


def pick_background(index):
    backgrounds = sorted(glob.glob("backgrounds/*.mp4"))
    if not backgrounds:
        raise FileNotFoundError("No background videos found in backgrounds/")
    return backgrounds[index % len(backgrounds)]


# ?? Entry point ???????????????????????????????????????????????????????????????

def main():
    subreddit = os.environ.get("SUBREDDIT", "AmItheAsshole")
    limit     = int(os.environ.get("LIMIT", "5"))
    print(f"Subreddit: r/{subreddit} ? \"{full_subreddit_name(subreddit)}\"")

    os.makedirs(OUT_DIR, exist_ok=True)
    os.makedirs("audio", exist_ok=True)

    tracking = load_tracking()
    seen_ids = set(tracking["seen_posts"].keys())
    print(f"Loaded {len(seen_ids)} previously-seen post IDs from {TRACKING_FILE}")

    posts    = scrape_posts(subreddit, limit, seen_ids)
    pipeline = KPipeline(lang_code="a")

    # Metadata file so the upload step knows each video's YouTube title
    metadata = []

    for i, post in enumerate(posts):
        print(f"\n--- Post {i+1}/{len(posts)}: {post['title']} (id={post['id']})")
        body = post["body"] or ""
        text = censor(post["title"])
        if body:
            text += ". " + censor(body)

        audio_path  = f"audio/post_{i+1}.wav"
        output_path = f"{OUT_DIR}/video_{i+1}.mp4"
        success     = False

        try:
            duration = generate_tts(pipeline, text, audio_path)
            make_video(text, audio_path, duration, pick_background(i), output_path)
            success = True
        except Exception as e:
            print(f"  Failed: {e}")
        finally:
            mark_seen(tracking, post, subreddit, success)
            save_tracking(tracking)

        metadata.append({
            "file":      output_path,
            "yt_title":  format_yt_title(post["title"]),
            "post_id":   post["id"],
            "success":   success,
        })

    # Write metadata for the upload step
    metadata_path = f"{OUT_DIR}/metadata.json"
    with open(metadata_path, "w", encoding="utf-8") as f:
        json.dump(metadata, f, indent=2, ensure_ascii=False)
    print(f"\nMetadata written ? {metadata_path}")
    print(f"All done ? {OUT_DIR}/")


if __name__ == "__main__":
    main()