import os
import re
import glob
import json
import random
import hashlib
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

OUT_DIR       = "results"
TRACKING_FILE = "data/seen_posts.json"
FONT_SIZE     = 52
MAX_WIDTH     = 900
VIDEO_W       = 1080
VIDEO_H       = 1920
MAX_BODY_CHARS = 4000

# All valid Kokoro voices (af=American female, am=American male, bf=British female, bm=British male)
KOKORO_VOICES = [
    "af_heart", "af_alloy", "af_aoede", "af_bella", "af_jessica",
    "af_kore", "af_nicole", "af_nova", "af_river", "af_sarah", "af_sky",
    "am_adam", "am_echo", "am_eric", "am_fenrir", "am_liam",
    "am_michael", "am_onyx", "am_puck", "am_santa",
    "bf_alice", "bf_emma", "bf_isabella", "bf_lily",
    "bm_daniel", "bm_fable", "bm_george", "bm_lewis",
]

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


# ── Entropy-based seeding ──────────────────────────────────────────────────────
# Combines wall-clock readings expressed in three timezones + post_id hash.
# Haiti = UTC-5, Johannesburg = UTC+2. Same underlying moment but different
# numeric representations when formatted → hashing them together with the
# post_id gives unique, hard-to-predict seeds per video.

def make_seed(post_id: str, index: int) -> int:
    now_utc  = datetime.datetime.utcnow()
    haiti_dt = now_utc - datetime.timedelta(hours=5)
    joburg_dt = now_utc + datetime.timedelta(hours=2)

    entropy = (
        f"{now_utc.strftime('%Y%m%d%H%M%S%f')}"
        f"{haiti_dt.strftime('%Y%m%d%H%M%S%f')}"
        f"{joburg_dt.strftime('%Y%m%d%H%M%S%f')}"
        f"{post_id}{index}"
    )
    return int(hashlib.sha256(entropy.encode()).hexdigest(), 16) % (2**32)


def seeded_rng(post_id: str, index: int) -> random.Random:
    rng = random.Random()
    rng.seed(make_seed(post_id, index))
    return rng


def pick_voice(rng: random.Random) -> str:
    voices = KOKORO_VOICES[:]
    rng.shuffle(voices)
    return voices[0]


# ── Privacy distribution ───────────────────────────────────────────────────────
# Index 0 → unlisted, index 1 → private ("scheduled"), rest → public
def get_privacy(index: int) -> str:
    if index == 0:
        return "unlisted"
    if index == 1:
        return "private"
    return "public"


# ── Tracking helpers ───────────────────────────────────────────────────────────

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
    print(f"Tracking saved → {TRACKING_FILE} ({len(tracking['seen_posts'])} total posts)")


def mark_seen(tracking: dict, post: dict, subreddit: str, success: bool):
    tracking["seen_posts"][post["id"]] = {
        "title":        post["title"],
        "subreddit":    subreddit,
        "processed_at": datetime.datetime.utcnow().isoformat(timespec="seconds") + "Z",
        "success":      success,
    }


# ── Reddit helpers ─────────────────────────────────────────────────────────────

def censor(text):
    for pattern, replacement in PROFANITY_MAP.items():
        text = re.sub(pattern, replacement, text, flags=re.IGNORECASE)
    return text


def full_subreddit_name(sub):
    return SUBREDDIT_NAMES.get(sub.lower(), sub)


def expand_aita(title: str) -> str:
    return re.sub(r'\bAITA\b', 'Am I The A-hole', title, flags=re.IGNORECASE)


def format_yt_title(raw_title: str) -> str:
    return expand_aita(raw_title)[:100]


def reddit_get(url, retries=5):
    import time
    delay = 10
    for attempt in range(retries):
        r = requests.get(url, headers=HEADERS, proxies=PROXIES, timeout=30)
        if r.status_code == 429:
            wait = delay * (2 ** attempt)
            print(f"  429 rate limit — waiting {wait}s (attempt {attempt+1}/{retries})")
            time.sleep(wait)
            continue
        r.raise_for_status()
        return r
    raise RuntimeError(f"Failed after {retries} retries: {url}")


FALLBACK_SUBREDDITS = [
    "AmItheAsshole", "tifu", "relationship_advice",
    "maliciouscompliance", "pettyrevenge", "prorevenge",
    "entitledparents", "offmychest", "confessions",
]


def scrape_from_subreddit(subreddit, limit, seen_ids: set):
    fetch_n = min(limit * 3, 100)
    url = f"https://www.reddit.com/r/{subreddit}/top.json?limit={fetch_n}&t=day"
    try:
        r = reddit_get(url)
    except Exception as e:
        print(f"  Could not fetch r/{subreddit}: {e}")
        return []

    posts, skipped = [], 0
    for item in r.json()["data"]["children"]:
        d = item["data"]
        post_id = d["id"]
        if post_id in seen_ids:
            skipped += 1
            continue
        raw_body = d.get("selftext", "")
        if len(raw_body) > MAX_BODY_CHARS:
            trimmed  = raw_body[:MAX_BODY_CHARS]
            last_end = max(trimmed.rfind(". "), trimmed.rfind("? "), trimmed.rfind("! "))
            raw_body = trimmed[:last_end + 1] if last_end != -1 else trimmed
        posts.append({"id": post_id, "title": d["title"], "body": raw_body, "subreddit": subreddit})
        if len(posts) == limit:
            break

    print(f"  r/{subreddit}: {len(posts)} new, {skipped} skipped")
    return posts


def scrape_posts(primary_subreddit, limit, seen_ids: set):
    queue     = [primary_subreddit] + [s for s in FALLBACK_SUBREDDITS if s.lower() != primary_subreddit.lower()]
    collected = []
    for sub in queue:
        if len(collected) >= limit:
            break
        needed = limit - len(collected)
        print(f"Fetching from r/{sub} (need {needed} more)...")
        collected.extend(scrape_from_subreddit(sub, needed, seen_ids))
    print(f"Total collected: {len(collected)} posts")
    return collected


# ── Text / font helpers ────────────────────────────────────────────────────────

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


# ── Frame rendering ────────────────────────────────────────────────────────────

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


# ── Video helpers ──────────────────────────────────────────────────────────────

def get_video_duration(path):
    r = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", path],
        capture_output=True, text=True
    )
    return float(r.stdout.strip())


def extract_random_bg_clip(bg_path, duration, output_path, rng: random.Random, fps=30):
    total = get_video_duration(bg_path)
    start = rng.uniform(0, max(0, total - duration - 1))
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


def make_video(text, audio_path, audio_duration, bg_path, output_path, rng: random.Random, fps=30):
    font      = get_font(FONT_SIZE, bold=False)
    font_bold = get_font(FONT_SIZE, bold=True)

    timeline, total_frames = build_timeline(text, audio_duration, fps)

    with tempfile.TemporaryDirectory() as frames_dir:
        bg_clip = os.path.join(frames_dir, "bg.mp4")
        extract_random_bg_clip(bg_path, audio_duration + 0.5, bg_clip, rng, fps)

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


def generate_tts(pipeline, text, voice, output_path):
    generator = pipeline(text, voice=voice, speed=1.0, split_pattern=r"\n+")
    chunks    = [audio for _, _, audio in generator]
    combined  = np.concatenate(chunks)
    sf.write(output_path, combined, 24000)
    duration = len(combined) / 24000
    print(f"TTS [{voice}]: {output_path} ({duration:.1f}s)")
    return duration


def pick_background(backgrounds, rng: random.Random):
    return rng.choice(backgrounds)


# ── Entry point ────────────────────────────────────────────────────────────────

def main():
    subreddit = os.environ.get("SUBREDDIT", "AmItheAsshole")
    limit     = int(os.environ.get("LIMIT", "5"))
    print(f"Subreddit: r/{subreddit} → \"{full_subreddit_name(subreddit)}\"")

    os.makedirs(OUT_DIR, exist_ok=True)
    os.makedirs("audio", exist_ok=True)

    tracking    = load_tracking()
    seen_ids    = set(tracking["seen_posts"].keys())
    backgrounds = sorted(glob.glob("backgrounds/*.mp4"))
    if not backgrounds:
        raise FileNotFoundError("No background videos found in backgrounds/")

    print(f"Loaded {len(seen_ids)} previously-seen post IDs")
    posts    = scrape_posts(subreddit, limit, seen_ids)
    pipeline = KPipeline(lang_code="a")
    metadata = []

    for i, post in enumerate(posts):
        rng     = seeded_rng(post["id"], i)
        voice   = pick_voice(rng)
        privacy = get_privacy(i)

        print(f"\n--- Post {i+1}/{len(posts)}: {post['title']} (id={post['id']})")
        print(f"  Voice: {voice}  |  Privacy: {privacy}")

        body = post["body"] or ""
        text = expand_aita(censor(post["title"]))
        if body:
            text += ". " + expand_aita(censor(body))
        print(f"  Script length: {len(text)} chars")

        audio_path  = f"audio/post_{i+1}.wav"
        output_path = f"{OUT_DIR}/video_{i+1}.mp4"
        success     = False

        try:
            duration = generate_tts(pipeline, text, voice, audio_path)
            make_video(text, audio_path, duration, pick_background(backgrounds, rng), output_path, rng)
            success = True
        except Exception as e:
            print(f"  Failed: {e}")
        finally:
            mark_seen(tracking, post, post.get("subreddit", subreddit), success)
            save_tracking(tracking)

        metadata.append({
            "file":      output_path,
            "yt_title":  format_yt_title(post["title"]),
            "post_id":   post["id"],
            "voice":     voice,
            "privacy":   privacy,
            "success":   success,
        })

    metadata_path = f"{OUT_DIR}/metadata.json"
    with open(metadata_path, "w", encoding="utf-8") as f:
        json.dump(metadata, f, indent=2, ensure_ascii=False)
    print(f"\nMetadata written → {metadata_path}")
    print(f"All done → {OUT_DIR}/")


if __name__ == "__main__":
    main()
