#!/usr/bin/env python3
"""Build 9:16 talking shorts from long videos. Local ffmpeg + Hugging Face Whisper.

Gudasol, current look: python3 tools/make_shorts.py
Aquarius Academy, first link in pending_videos.txt:
  python3 tools/make_shorts.py --project "Aquarius Academy"

Style keys are render-styles.json. Where a short starts and ends stays here.
"""

from __future__ import annotations

import json
import math
import random
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

import edges
import hooks
from render_style import resolve

ROOT = Path(__file__).resolve().parents[1]
LONG_DIR = ROOT / "Long Videos"
VIDEO_DIR = ROOT / "Video Samples"
OUT_DIR = ROOT / "Shorts"
LOGO_CANDIDATES = [
    ROOT / "Token Images" / "EASY.png",
    ROOT / "Token Images" / "AA-Logo[PurpleInCircle][WhiteBG][1.4][512].png",
]
FRACTAL_DIR = ROOT / "Gudasol Fractal Art"
SACRED_DIR = ROOT / "Gudasol Sacred Geometry Art"
ART_DIRS = [FRACTAL_DIR, SACRED_DIR]
# 11k sacred masters are fine after a downscale; raise PIL's bomb guard for them.
Image.MAX_IMAGE_PIXELS = max(getattr(Image, "MAX_IMAGE_PIXELS", 0) or 0, 200_000_000)
FACE_SWIFT = Path(__file__).resolve().parent / "detect_faces.swift"
FACE_BIN = Path(__file__).resolve().parent / "detect_faces"
FONT_PATHS = [
    (Path("/Users/fresh/Library/Fonts/BebasNeue Bold.otf"), 0),
    (Path("/System/Library/Fonts/Avenir Next Condensed.ttc"), 8),
    (Path("/System/Library/Fonts/Supplemental/Impact.ttf"), 0),
]

WHISPER_MODEL = "base.en"
BREATH_PAUSE = 0.70
IDEA_PAUSE = 2.15
SCENE_PAUSE = 8.50
MIN_SHORT = 15.0
MIN_WORDS = 5
MAX_SHORT = 180.0
PREFER_LONG = 85.0

INCOMPLETE_TAILS = {
    "a", "an", "the", "and", "or", "but", "so", "because", "if", "when", "while",
    "to", "of", "in", "on", "for", "with", "as", "at", "from", "by", "into",
    "that", "which", "who", "whom", "whose", "my", "our", "your", "their",
    "it's", "its", "we're", "i've", "i'm", "that's", "there's", "just", "very",
    "this", "these", "those", "also", "then", "than", "like", "about",
}
STOPWORDS = INCOMPLETE_TAILS | {
    "i", "we", "you", "he", "she", "it", "they", "me", "us", "them", "be", "is",
    "are", "was", "were", "been", "being", "have", "has", "had", "do", "did",
    "does", "not", "no", "yes", "can", "could", "would", "should", "will",
    "what", "how", "where", "why", "who", "all", "each", "more", "some", "any",
    "out", "up", "down", "over", "really", "kind", "get", "got", "go", "going",
}
TOPIC_START = re.compile(
    r"^\s*("
    r"anyway |another |meanwhile |"
    r"so aquarius |i'?ve been |right now |"
    r"you can belittle |the co-roper"
    r")",
    re.I,
)
CONTINUE_START = re.compile(
    r"^\s*(that's |that is |and |our ability |because |which |"
    r"so that |to be |to choose |i choose |connecting |we need )",
    re.I,
)

W, H = 1080, 1920
YELLOW = (255, 215, 0, 255)
BLACK = (0, 0, 0, 255)
WHITE = (255, 255, 255, 255)
STYLE: dict = {}

SAMPLE_FPS = 3.0
CAMERA_FPS = 24.0
DEADZONE_FRAC = 0.055
STICKY_FRAC = 0.11
SETTLE_FRAC = 0.012
FOLLOW_OMEGA = 2.6
FOLLOW_DAMPING = 1.15
MAX_PAN_FRAC_PER_S = 0.085
MAX_ACCEL_FRAC_PER_S2 = 0.16
FAST_P90_FRAC_PER_S = 0.55
FAST_MEDIAN_FRAC_PER_S = 0.22
JUMP_MIN_HOLD = 0.85
JUMP_SIZE_RATIO = 1.28
MAX_JUMPS_PER_S = 0.38
MULTI_FACE_SPAN = 0.52
CLUSTER_GAP = 0.18


def run(cmd, **kw):
    return subprocess.run(cmd, check=True, **kw)


def probe_duration(path: Path) -> float:
    out = subprocess.check_output(
        [
            "ffprobe", "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            str(path),
        ],
        text=True,
    ).strip()
    return float(out)


def probe_wh(path: Path) -> tuple[int, int]:
    out = subprocess.check_output(
        [
            "ffprobe", "-v", "error", "-select_streams", "v:0",
            "-show_entries", "stream=width,height",
            "-of", "csv=p=0", str(path),
        ],
        text=True,
    ).strip()
    w, h = out.split(",")
    return int(w), int(h)


def load_font(size: int) -> ImageFont.FreeTypeFont:
    if STYLE.get("font_path"):
        return ImageFont.truetype(STYLE["font_path"], size=size, index=int(STYLE.get("font_index") or 0))
    for path, index in FONT_PATHS:
        if path.exists():
            return ImageFont.truetype(str(path), size=size, index=index)
    raise FileNotFoundError("no caption font found")


def render_caption_png(text: str, dest: Path, max_width: int = 980) -> Image.Image:
    text = re.sub(r"\s+", " ", text).strip()
    case = STYLE.get("caption_case") or "upper"
    if case == "upper":
        text = text.upper()
    elif case == "lower":
        text = text.lower()
    dummy = ImageDraw.Draw(Image.new("RGBA", (4, 4)))
    if not text:
        img = Image.new("RGBA", (1, 1), (0, 0, 0, 0))
        dest.parent.mkdir(parents=True, exist_ok=True)
        img.save(dest)
        return img

    look = STYLE.get("caption_look") or {}
    stroke_px = int(look.get("stroke_px") or 3) if look.get("draw") == "outline" else 0
    font_size = 92
    bbox = (0, 0, 0, 0)
    tw = th = 0
    font = load_font(font_size)
    while font_size >= 48:
        font = load_font(font_size)
        bbox = dummy.textbbox((0, 0), text, font=font)
        tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
        if tw + 80 + stroke_px * 2 <= max_width:
            break
        font_size -= 4

    if look.get("draw") == "outline":
        pad_x, pad_y = 28, 16
        img = Image.new(
            "RGBA",
            (tw + pad_x * 2 + stroke_px * 2, th + pad_y * 2 + stroke_px * 2),
            (0, 0, 0, 0),
        )
        ImageDraw.Draw(img).text(
            (pad_x + stroke_px - bbox[0], pad_y + stroke_px - bbox[1]),
            text,
            font=font,
            fill=tuple(look.get("ink") or WHITE),
            stroke_width=stroke_px,
            stroke_fill=tuple(look.get("stroke") or BLACK),
        )
        dest.parent.mkdir(parents=True, exist_ok=True)
        img.save(dest)
        return img

    fill = tuple(look["fill"]) if look.get("fill") else YELLOW
    ink = tuple(look["ink"]) if look.get("ink") else BLACK
    tick = tuple(look["tick"]) if look.get("tick") else WHITE
    pad_x, pad_y = 28, 10
    box_w = tw + pad_x * 2
    box_h = th + pad_y * 2
    tick_w, tick_over, gap = 7, 10, 8
    canvas_w = box_w + (tick_w + gap) * 2
    canvas_h = box_h + tick_over * 2
    img = Image.new("RGBA", (canvas_w, canvas_h), (0, 0, 0, 0))
    dr = ImageDraw.Draw(img)
    x0 = tick_w + gap
    y0 = tick_over
    dr.rectangle([x0, y0, x0 + box_w - 1, y0 + box_h - 1], fill=fill)
    dr.rectangle([0, 0, tick_w - 1, canvas_h - 1], fill=tick)
    dr.rectangle([canvas_w - tick_w, 0, canvas_w - 1, canvas_h - 1], fill=tick)
    dr.text((x0 + pad_x - bbox[0], y0 + pad_y - bbox[1]), text, font=font, fill=ink)
    dest.parent.mkdir(parents=True, exist_ok=True)
    img.save(dest)
    return img


def render_caption_frame(
    text: str,
    dest: Path,
    band: tuple[int, int] | None = None,
) -> None:
    """Place caption bar. band=(y0,y1) centers it in that vertical strip (main-bottom art)."""
    frame = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    bar = render_caption_png(text, dest.with_suffix(".bar.png"))
    x = (W - bar.width) // 2
    if band is not None:
        y0, y1 = band
        y = y0 + max(0, (y1 - y0 - bar.height) // 2)
        y = max(y0, min(y1 - bar.height, y))
    else:
        place = STYLE.get("caption_place") or {}
        if place.get("at") == "center":
            y = int(round(H * float(place["center"]) - bar.height / 2))
            y = max(0, min(H - bar.height, y))
        else:
            y = H - bar.height - 220
    frame.paste(bar, (x, y), bar)
    dest.parent.mkdir(parents=True, exist_ok=True)
    frame.save(dest)


def group_words(segments: list[dict], max_words: int = 3, max_secs: float = 1.35) -> list[dict]:
    cues, buf = [], []
    for seg in segments:
        word = str(seg.get("text", "")).strip()
        if not word:
            continue
        buf.append(seg)
        dur = float(buf[-1]["end"]) - float(buf[0]["start"])
        if len(buf) >= max_words or dur >= max_secs or word[-1:] in ".!?":
            cues.append(
                {
                    "start": float(buf[0]["start"]),
                    "end": float(buf[-1]["end"]),
                    "text": " ".join(s["text"].strip() for s in buf),
                }
            )
            buf = []
    if buf:
        cues.append(
            {
                "start": float(buf[0]["start"]),
                "end": float(buf[-1]["end"]),
                "text": " ".join(s["text"].strip() for s in buf),
            }
        )
    for i, c in enumerate(cues):
        if c["end"] <= c["start"]:
            c["end"] = c["start"] + 0.45
        if i + 1 < len(cues):
            c["end"] = min(cues[i + 1]["start"], max(c["end"], c["start"] + 0.35))
    return cues


def _norm_token(text: str) -> str:
    return re.sub(r"[^a-z0-9']+", "", text.lower())


def _content_tokens(text: str) -> set[str]:
    return {t for t in (_norm_token(w) for w in text.split()) if t and t not in STOPWORDS and len(t) > 2}


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def thought_complete(text: str) -> bool:
    stripped = text.strip()
    if not stripped:
        return False
    if stripped[-1] in ".?!":
        return True
    last = _norm_token(stripped.split()[-1])
    return last not in INCOMPLETE_TAILS and len(stripped.split()) >= 6


def topic_shift_score(prev_text: str, next_text: str, gap: float) -> float:
    score = 0.0
    if gap >= IDEA_PAUSE:
        score += 2.2
    if gap >= SCENE_PAUSE:
        score += 2.5
    if TOPIC_START.search(next_text or ""):
        score += 2.4
    if CONTINUE_START.search(next_text or ""):
        score -= 2.2
    prev_c = _content_tokens(prev_text)
    next_c = _content_tokens(next_text)
    sim = _jaccard(prev_c, next_c)
    if sim < 0.08 and (prev_c and next_c):
        score += 2.0
    elif sim < 0.16:
        score += 1.0
    if thought_complete(prev_text):
        score += 0.6
    else:
        score -= 2.8
    return score


def _split_internal_topic_starts(units: list[dict]) -> list[dict]:
    """Break a run-on unit when a new subject starts mid-thought."""
    out: list[dict] = []
    for unit in units:
        ws = unit.get("words") or []
        if len(ws) < 12:
            out.append(unit)
            continue
        cuts = [0]
        for i in range(5, len(ws) - 3):
            snippet = " ".join(w["text"] for w in ws[i : i + 8])
            prev = " ".join(w["text"] for w in ws[:i])
            if TOPIC_START.search(snippet) and thought_complete(prev) and i - cuts[-1] >= 8:
                cuts.append(i)
        cuts.append(len(ws))
        if len(cuts) == 2:
            out.append(unit)
            continue
        for a, b in zip(cuts, cuts[1:]):
            part = ws[a:b]
            if len(part) < MIN_WORDS:
                continue
            out.append(
                {
                    "start": float(part[0]["start"]),
                    "end": float(part[-1]["end"]),
                    "text": " ".join(w["text"].strip() for w in part),
                    "gap_after": unit.get("gap_after", 0.0) if b == len(ws) else 0.45,
                    "words": part,
                }
            )
    return out


def thought_units(words: list[dict]) -> list[dict]:
    """Group words into finished thoughts using pauses and trailing grammar."""
    if not words:
        return []
    units: list[dict] = []
    buf = [words[0]]
    for prev, cur in zip(words, words[1:]):
        gap = float(cur["start"]) - float(prev["end"])
        text = " ".join(w["text"].strip() for w in buf)
        complete = thought_complete(text)
        idea_break = gap >= IDEA_PAUSE or (complete and gap >= BREATH_PAUSE)
        if idea_break and not (not complete and gap < SCENE_PAUSE):
            units.append(
                {
                    "start": float(buf[0]["start"]),
                    "end": float(buf[-1]["end"]),
                    "text": text,
                    "gap_after": gap,
                    "words": list(buf),
                }
            )
            buf = [cur]
        else:
            buf.append(cur)
    if buf:
        units.append(
            {
                "start": float(buf[0]["start"]),
                "end": float(buf[-1]["end"]),
                "text": " ".join(w["text"].strip() for w in buf),
                "gap_after": 0.0,
                "words": list(buf),
            }
        )
    units = [u for u in units if len(u["text"].split()) >= MIN_WORDS]
    return _split_internal_topic_starts(units)


def windows_from_words(words: list[dict], duration: float) -> list[tuple[float, float]]:
    return windows_from_transcript({"words": words}, duration)


def windows_from_transcript(payload: dict, duration: float) -> list[tuple[float, float]]:
    """Cut on finished ideas. Long pauses and topic shifts split; otherwise keep going (longer is better)."""
    words = payload.get("words") or []
    units = thought_units(words)
    if not units:
        return []

    windows: list[tuple[float, float]] = []
    start_i = 0
    while start_i < len(units):
        end_i = start_i
        while end_i + 1 < len(units):
            nxt = units[end_i + 1]
            a = max(0.0, float(units[start_i]["start"]) - 0.08)
            b_now = min(duration, float(units[end_i]["end"]) + 0.12)
            b_next = min(duration, float(nxt["end"]) + 0.12)
            cur_len = b_now - a
            next_len = b_next - a
            gap = float(units[end_i].get("gap_after") or (nxt["start"] - units[end_i]["end"]))
            shift = topic_shift_score(units[end_i]["text"], nxt["text"], gap)
            complete = thought_complete(units[end_i]["text"])

            if next_len > MAX_SHORT:
                break
            if cur_len < MIN_SHORT:
                end_i += 1
                continue
            strong = (
                gap >= SCENE_PAUSE
                or (complete and gap >= 3.2 and shift >= 2.8)
                or (complete and bool(TOPIC_START.search(nxt["text"] or "")) and cur_len >= PREFER_LONG)
            )
            very_strong = gap >= SCENE_PAUSE or (
                bool(TOPIC_START.search(nxt["text"] or "")) and complete
            )
            if cur_len < PREFER_LONG:
                if very_strong:
                    break
                end_i += 1
                continue
            if strong:
                break
            if cur_len >= 120 and complete and gap >= IDEA_PAUSE:
                break
            if cur_len >= 155 and complete:
                break
            end_i += 1

        a = max(0.0, float(units[start_i]["start"]) - 0.08)
        b = min(duration, float(units[end_i]["end"]) + 0.12)
        if b - a > MAX_SHORT:
            # Walk back to the last complete thought that still fits.
            fit = end_i
            while fit > start_i:
                bb = min(duration, float(units[fit]["end"]) + 0.12)
                if bb - a <= MAX_SHORT and thought_complete(units[fit]["text"]):
                    b = bb
                    end_i = fit
                    break
                fit -= 1
            else:
                b = min(a + MAX_SHORT, duration)
        if b - a >= MIN_SHORT:
            windows.append((a, b))
        start_i = end_i + 1

    # Fold a leftover tail under 15s into the previous short when it fits.
    if len(windows) >= 2:
        a, b = windows[-1]
        if b - a < MIN_SHORT:
            pa, _ = windows[-2]
            if b - pa <= MAX_SHORT:
                windows[-2] = (pa, b)
                windows.pop()
    return [(a, b) for a, b in windows if MIN_SHORT <= (b - a) <= MAX_SHORT]


def extract_frame(path: Path, t: float, dest: Path) -> None:
    run(
        ["ffmpeg", "-y", "-ss", f"{max(t, 0):.3f}", "-i", str(path), "-frames:v", "1", str(dest)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def subject_crop_x(frame_path: Path, src_w: int, src_h: int) -> int:
    im = Image.open(frame_path).convert("RGB")
    im = im.resize((im.width // 4, im.height // 4))
    px = im.load()
    acc_x = acc = 0.0
    thirds = [0.0, 0.0, 0.0]
    y0, y1 = int(im.height * 0.06), int(im.height * 0.32)
    for y in range(y0, y1):
        for x in range(im.width):
            r, g, b = px[x, y]
            if r > 95 and g > 45 and b > 30 and r > b + 8 and abs(r - g) < 70:
                band = 0 if x < im.width / 3 else (1 if x < 2 * im.width / 3 else 2)
                thirds[band] += 1.0
    band = max(range(3), key=lambda i: thirds[i])
    x0 = int(im.width * band / 3)
    x1 = int(im.width * (band + 1) / 3)
    for y in range(y0, y1):
        for x in range(x0, x1):
            r, g, b = px[x, y]
            if r > 95 and g > 45 and b > 30 and r > b + 8 and abs(r - g) < 70:
                acc_x += x
                acc += 1.0
    cx = (acc_x / acc) * 4 if acc > 80 else src_w / 2
    crop_w = src_h * 9 / 16
    x = int(round(cx - crop_w / 2))
    return max(0, min(int(src_w - crop_w), x))


# Face + art mashup: video takes 62% of the short height.
MAIN_BOTTOM_SPEAKER = int(round(H * 0.62)) // 2 * 2  # 1190
MAIN_BOTTOM_TOP = H - MAIN_BOTTOM_SPEAKER  # 730
CUTAWAY_BAND = 640
# Sacred cover starts larger than the display on both axes, then keeps growing.
SACRED_MIN_OVER = 1.08
SACRED_EXPAND = 1.20
ART_FPS = 12
ART_SLOT = 15.0
ART_CHANCE = 0.30
GLITCH_SECS = 0.5
SYMBOL_SECS = 0.8
# Per short: chance the sacred-geometry symbols from the music videos pop in at random times.
SYMBOL_VIDEO_CHANCE = 0.45
COLOR_FX = ("kaleido", "prism", "wedges", "hue")


@dataclass
class FramingPlan:
    mode: str
    reason: str
    crop_keys: list[tuple[float, int]] = field(default_factory=list)
    art: Path | None = None
    support: Path | None = None
    cutaways: list[tuple[float, float]] = field(default_factory=list)
    stats: dict = field(default_factory=dict)

    def summary(self) -> str:
        extra = ""
        if self.art:
            extra = f" art={self.art.name}"
        if self.support:
            extra += f" support={self.support.name}"
        if self.cutaways:
            extra += f" cutaways={len(self.cutaways)}"
        hit = self.stats.get("hit_rate")
        if hit is not None:
            extra += f" hit={hit}"
        return f"{self.mode} ({self.reason}){extra}"


def video_encoder() -> list[str]:
    try:
        out = subprocess.check_output(
            ["ffmpeg", "-hide_banner", "-encoders"],
            text=True,
            stderr=subprocess.STDOUT,
        )
    except (subprocess.CalledProcessError, FileNotFoundError):
        return ["-c:v", "libx264", "-preset", "veryfast", "-crf", "20"]
    if "h264_videotoolbox" in out:
        return ["-c:v", "h264_videotoolbox", "-b:v", "8M"]
    return ["-c:v", "libx264", "-preset", "veryfast", "-crf", "20"]


def prepare_support_still(src: Path, dest: Path, band_h: int) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    _cover_rgb(src, W, band_h).save(dest, quality=92)


def cutaway_spans(words: list[dict], start: float, end: float, max_spans: int = 2) -> list[tuple[float, float]]:
    """Return up to two pause windows relative to clip start. Never in the first 2 seconds."""
    timed = sorted(
        (float(w["start"]), float(w["end"]))
        for w in words
        if float(w["end"]) > start and float(w["start"]) < end
    )
    if not timed:
        return []
    gaps: list[tuple[float, float]] = []
    prev_end = start
    for a, b in timed:
        if a - prev_end >= BREATH_PAUSE and a - start >= 2.0:
            gaps.append((prev_end, a))
        prev_end = max(prev_end, b)
    spans: list[tuple[float, float]] = []
    for a, b in gaps:
        mid = (a + b) / 2
        left = max(2.0, mid - 2.0)
        right = min(end - start, left + 4.0)
        left = max(2.0, right - 4.0)
        if right - left < 3.0:
            continue
        spans.append((left, right))
        if len(spans) >= max_spans:
            break
    return spans


def audio_stream_count(path: Path) -> int:
    out = subprocess.check_output(
        [
            "ffprobe", "-v", "error", "-select_streams", "a",
            "-show_entries", "stream=index", "-of", "csv=p=0", str(path),
        ],
        text=True,
    ).strip()
    return len([line for line in out.splitlines() if line.strip()])


def extract_qa_frames(video: Path, dest_dir: Path) -> list[Path]:
    dest_dir.mkdir(parents=True, exist_ok=True)
    dur = probe_duration(video)
    stamps = [1.0, max(1.0, dur / 2), max(1.0, dur - 1.0)]
    frames: list[Path] = []
    for i, t in enumerate(stamps):
        frame = dest_dir / f"qa-{i + 1}.jpg"
        run(
            [
                "ffmpeg", "-y", "-ss", f"{min(t, max(0.0, dur - 0.05)):.3f}",
                "-i", str(video), "-frames:v", "1", str(frame),
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        frames.append(frame)
    return frames


def _list_images(folder: Path, allow_11k: bool = False) -> list[Path]:
    if not folder.is_dir():
        return []
    files = [p for p in folder.iterdir() if p.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp"}]
    if allow_11k:
        return sorted(files)
    compact = [p for p in files if "[11k]" not in p.name]
    return sorted(compact or files)


def list_fractal_art() -> list[Path]:
    return _list_images(FRACTAL_DIR, allow_11k=False)


def list_sacred_art() -> list[Path]:
    # Sacred masters are PNG 11k prints now; include them and downscale on use.
    return _list_images(SACRED_DIR, allow_11k=True)


def list_art() -> list[Path]:
    return list_fractal_art() + list_sacred_art()


def is_sacred(path: Path | None) -> bool:
    if path is None:
        return False
    try:
        return path.resolve().is_relative_to(SACRED_DIR.resolve())
    except (ValueError, AttributeError):
        return SACRED_DIR.name in path.parts


def _pick_from(files: list[Path], seed: str) -> Path | None:
    if not files:
        return None
    acc = 0
    for ch in seed:
        acc = (acc * 33 + ord(ch)) & 0xFFFFFFFF
    return files[acc % len(files)]


def pick_art(seed: str) -> Path | None:
    return _pick_from(list_art(), seed)


def pick_art_stack(seed: str) -> tuple[Path | None, Path | None]:
    """Fractal underlay + optional sacred overlay. Sacred always gets a fractal under it."""
    sacred = _pick_from(list_sacred_art(), seed + "-sacred")
    fractal = _pick_from(list_fractal_art(), seed + "-fractal")
    if sacred and fractal:
        return fractal, sacred
    if sacred and not fractal:
        return sacred, None
    return fractal, None


def _cover_rgb(src: Path, tw: int, th: int) -> Image.Image:
    im = Image.open(src)
    if im.mode in {"RGBA", "LA", "P"}:
        rgba = im.convert("RGBA")
        base = Image.new("RGB", rgba.size, (0, 0, 0))
        base.paste(rgba, mask=rgba.split()[-1])
        im = base
    else:
        im = im.convert("RGB")
    # Cap decode work on 11k masters before the cover scale.
    longest = max(im.size)
    if longest > 4096:
        shrink = 4096 / longest
        im = im.resize(
            (max(2, int(im.width * shrink) // 2 * 2), max(2, int(im.height * shrink) // 2 * 2)),
            Image.Resampling.LANCZOS,
        )
    scale = max(tw / im.width, th / im.height)
    nw, nh = max(tw, int(im.width * scale)), max(th, int(im.height * scale))
    im = im.resize((nw, nh), Image.Resampling.LANCZOS)
    left = max(0, (nw - tw) // 2)
    top = max(0, (nh - th) // 2)
    return im.crop((left, top, left + tw, top + th))


def _fit_rgba(src: Path, tw: int, th: int) -> Image.Image:
    """Sacred pattern covering the frame: both edges >= display after center crop.

    PNG masters store geometry mostly in alpha on near-black RGB. Rebuild as
    soft-white ink so fractal color shows through. Zoompan then starts above 1.0
    so the visible pattern is already larger than the display and keeps growing.
    """
    import numpy as np

    im = Image.open(src).convert("RGBA")
    longest = max(im.size)
    if longest > 4096:
        shrink = 4096 / longest
        im = im.resize(
            (max(2, int(im.width * shrink) // 2 * 2), max(2, int(im.height * shrink) // 2 * 2)),
            Image.Resampling.LANCZOS,
        )
    # Cover: both scaled edges are at least the display size.
    scale = max(tw / im.width, th / im.height)
    nw = max(tw, int(im.width * scale) // 2 * 2)
    nh = max(th, int(im.height * scale) // 2 * 2)
    im = im.resize((nw, nh), Image.Resampling.LANCZOS)
    left = max(0, (nw - tw) // 2)
    top = max(0, (nh - th) // 2)
    im = im.crop((left, top, left + tw, top + th))
    arr = np.asarray(im)
    alpha = arr[:, :, 3].astype(np.float32)
    lum = arr[:, :, :3].mean(axis=2)
    ink = alpha * (0.55 + 0.45 * ((255.0 - lum) / 255.0))
    lo = float(np.percentile(ink, 8))
    hi = float(np.percentile(ink, 96))
    if hi <= lo + 1:
        stretched = ink
    else:
        stretched = (ink - lo) * (255.0 / (hi - lo))
    stretched = np.clip(stretched * 0.72, 0, 210)
    stretched[stretched < 10] = 0
    out = np.zeros((th, tw, 4), dtype=np.uint8)
    out[:, :, 0] = 250
    out[:, :, 1] = 250
    out[:, :, 2] = 250
    out[:, :, 3] = stretched.astype(np.uint8)
    return Image.fromarray(out, "RGBA")


def prepare_art_bg(src: Path, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    _cover_rgb(src, W, H).save(dest, quality=92)


def _hue_rotate(rgb, deg: float):
    import numpy as np

    a = np.deg2rad(deg)
    c, s = float(np.cos(a)), float(np.sin(a))
    m = np.array(
        [
            [0.213 + c * 0.787 - s * 0.213, 0.715 - c * 0.715 - s * 0.715, 0.072 - c * 0.072 + s * 0.928],
            [0.213 - c * 0.213 + s * 0.143, 0.715 + c * 0.285 + s * 0.140, 0.072 - c * 0.072 - s * 0.283],
            [0.213 - c * 0.213 - s * 0.787, 0.715 - c * 0.715 + s * 0.715, 0.072 + c * 0.928 + s * 0.072],
        ],
        dtype=np.float32,
    )
    out = rgb.astype(np.float32) @ m.T
    return np.clip(out, 0, 255).astype(np.uint8)


def _color_sacred(rgba, t: float):
    """Six saturated color wedges on the sacred ink. Geometry stays; hues spin."""
    import colorsys
    import numpy as np

    h, w = rgba.shape[:2]
    yy, xx = np.mgrid[0:h, 0:w]
    ang = np.arctan2(yy - h / 2, xx - w / 2)
    spin = t * 0.08
    sector = np.floor(((ang + np.pi) / (2 * np.pi) * 6 + spin) % 6).astype(np.int32)
    colored = np.zeros((h, w, 3), dtype=np.uint8)
    veil = np.zeros((h, w, 4), dtype=np.uint8)
    for k in range(6):
        mask = sector == k
        if not mask.any():
            continue
        r, g, b = colorsys.hsv_to_rgb(((k / 6.0) + spin) % 1.0, 0.92, 1.0)
        swatch = (int(r * 255), int(g * 255), int(b * 255))
        colored[mask] = swatch
        veil[mask, 0] = swatch[0]
        veil[mask, 1] = swatch[1]
        veil[mask, 2] = swatch[2]
        veil[mask, 3] = 70
    out = np.zeros_like(rgba)
    out[:, :, :3] = colored
    ink = rgba[:, :, 3].astype(np.float32)
    out[:, :, 3] = np.clip(ink * 1.35, 0, 230).astype(np.uint8)
    # Veil sits in the clear gaps so the kaleidoscope reads even on thin linework.
    clear = out[:, :, 3] < 24
    out[clear] = veil[clear]
    return out


def _kaleido(rgb, n: int = 6):
    import numpy as np

    h, w = rgb.shape[:2]
    yy, xx = np.mgrid[0:h, 0:w]
    cy, cx = (h - 1) / 2, (w - 1) / 2
    ang = np.arctan2(yy - cy, xx - cx)
    rad = np.hypot(yy - cy, xx - cx)
    sector = np.pi / n
    ang = np.abs(np.mod(ang, 2 * sector) - sector)
    sx = np.clip((cx + rad * np.cos(ang)).astype(np.int32), 0, w - 1)
    sy = np.clip((cy + rad * np.sin(ang)).astype(np.int32), 0, h - 1)
    return rgb[sy, sx]


def _prism(rgb, shift: int):
    import numpy as np

    out = rgb.copy()
    out[:, :, 0] = np.roll(rgb[:, :, 0], shift, axis=1)
    out[:, :, 2] = np.roll(rgb[:, :, 2], -shift, axis=1)
    return out


def _wedges(rgb, t: float):
    import numpy as np

    h, w = rgb.shape[:2]
    yy, xx = np.mgrid[0:h, 0:w]
    ang = np.arctan2(yy - h / 2, xx - w / 2)
    sector = np.floor(((ang + np.pi) / (2 * np.pi) * 6 + t * 0.2) % 6).astype(np.int32)
    out = rgb.astype(np.float32)
    for k in range(6):
        mask = sector == k
        tint = _hue_rotate(np.full((1, 1, 3), 255, dtype=np.uint8), k * 60 + t * 30)
        out[mask] = out[mask] * 0.55 + tint.astype(np.float32)[0, 0] * 0.45
    return np.clip(out, 0, 255).astype(np.uint8)


def _apply_edge(rgb, name: str, t: float):
    """Cut a thin top and bottom fringe with one shared edge shape."""
    import numpy as np

    h, w = rgb.shape[:2]
    depth = edges.fringe_px(h)
    cut = (edges.unit(name, np.arange(w), t) * depth).astype(np.int32)
    yy = np.arange(h)[:, None]
    outside = (yy < cut[None, :]) | (yy > h - 1 - cut[None, :])
    out = rgb.astype(np.float32)
    out[outside] *= 0.12
    return np.clip(out, 0, 255).astype(np.uint8)


def _tint_sacred(rgba, hue: float):
    import colorsys
    import numpy as np

    r, g, b = colorsys.hsv_to_rgb((hue % 360) / 360.0, 0.85, 1.0)
    out = np.zeros_like(rgba)
    out[:, :, 0] = int(r * 255)
    out[:, :, 1] = int(g * 255)
    out[:, :, 2] = int(b * 255)
    out[:, :, 3] = np.clip(rgba[:, :, 3].astype(np.float32) * 1.25, 0, 220).astype(np.uint8)
    return out


def _hold_fx(rgb, name: str, t: float, t0: float):
    if name == "kaleido":
        spun = _hue_rotate(rgb, (t - t0) * 28)
        return _kaleido(spun, 6)
    if name == "prism":
        return _prism(rgb, 8 + int((t - t0) * 6) % 24)
    if name == "wedges":
        return _wedges(rgb, t)
    return _hue_rotate(rgb, (t - t0) * 36)


def _glitch_rgba(rgba, t: float):
    import numpy as np

    out = rgba.copy()
    rng = random.Random(int(t * 48) + 7)
    h, w = out.shape[:2]
    for _ in range(6):
        y = rng.randint(0, max(1, h - 10))
        hh = rng.randint(3, 14)
        y1 = min(h, y + hh)
        xoff = rng.randint(-36, 36)
        band = out[y:y1].copy()
        out[y:y1] = 0
        if xoff >= 0:
            out[y:y1, xoff:] = band[:, : w - xoff]
        elif xoff < 0:
            out[y:y1, : w + xoff] = band[:, -xoff:]
    # Channel tear so the glitch reads as color, not just a shift.
    tear = rng.randint(6, 22)
    out[:, :, 0] = np.roll(out[:, :, 0], tear, axis=1)
    return out


def _zoom_center(rgba, z: float):
    """Scale up and center-crop so the overlay stays larger than the frame."""
    h, w = rgba.shape[:2]
    im = Image.fromarray(rgba, "RGBA")
    nw = max(w + 2, int(w * z) // 2 * 2)
    nh = max(h + 2, int(h * z) // 2 * 2)
    im = im.resize((nw, nh), Image.Resampling.BILINEAR)
    left = (nw - w) // 2
    top = (nh - h) // 2
    return np_rgba(im.crop((left, top, left + w, top + h)))


def np_rgba(im: Image.Image):
    import numpy as np

    return np.asarray(im.convert("RGBA"))


def _over(base, rgba, opacity: float = 1.0):
    import numpy as np

    a = (rgba[:, :, 3:4].astype(np.float32) / 255.0) * opacity
    return np.clip(
        rgba[:, :, :3].astype(np.float32) * a + base.astype(np.float32) * (1.0 - a),
        0,
        255,
    ).astype(np.uint8)


def _art_plan(seed: str, duration: float) -> tuple[list[dict], list[float], bool]:
    """Per short, shuffle the music-video edge shapes. Each 15s uses the next one.

    Separately, 30% of slots also take a color effect for the full 15s, and 30%
    flash a 0.5s glitch symbol.
    """
    rng = random.Random(seed)
    order = edges.shuffle(seed)
    slots: list[dict] = []
    t = 0.0
    while t < duration - 0.05:
        span = min(ART_SLOT, duration - t)
        glitch = rng.random() < ART_CHANCE
        hold = rng.choice(COLOR_FX) if rng.random() < ART_CHANCE else None
        at = None
        if glitch and span > GLITCH_SECS + 0.4:
            at = rng.uniform(t + 0.25, t + span - GLITCH_SECS - 0.05)
        slots.append({
            "t0": t,
            "t1": t + span,
            "edge": order[len(slots) % len(order)],
            "hold": hold,
            "glitch": at,
        })
        t += ART_SLOT
    symbols = rng.random() < SYMBOL_VIDEO_CHANCE
    pops: list[float] = []
    if symbols:
        cursor = rng.uniform(1.2, 4.0)
        while cursor < duration - SYMBOL_SECS:
            pops.append(cursor)
            cursor += rng.uniform(7.0, 16.0)
    return slots, pops, symbols


def _encode_rgb(frames, dest: Path, width: int, height: int, fps: int, duration: float) -> None:
    enc = video_encoder()
    proc = subprocess.Popen(
        [
            "ffmpeg", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24",
            "-s", f"{width}x{height}", "-r", str(fps), "-i", "-",
            *enc, "-pix_fmt", "yuv420p", "-an",
            "-t", f"{duration:.3f}", "-movflags", "+faststart", str(dest),
        ],
        stdin=subprocess.PIPE,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
    )
    assert proc.stdin is not None
    try:
        for frame in frames:
            proc.stdin.write(frame.tobytes())
    finally:
        proc.stdin.close()
    err = proc.stderr.read() if proc.stderr else b""
    code = proc.wait()
    if code != 0:
        raise subprocess.CalledProcessError(code, "ffmpeg", stderr=err)


def build_art_backdrop(
    duration: float,
    work: Path,
    seed: str,
    width: int = W,
    height: int = H,
    fractal: Path | None = None,
    sacred: Path | None = None,
) -> Path:
    """Centered fractal underlay; when sacred is set, slow-expand it on top."""
    work.mkdir(parents=True, exist_ok=True)
    if fractal is None and sacred is None:
        fractal, sacred = pick_art_stack(seed)
    elif sacred is not None and fractal is None and is_sacred(sacred):
        fractal = _pick_from(list_fractal_art(), seed + "-under")
    elif fractal is None and sacred is None:
        fractal = pick_art(seed)

    under = fractal or sacred
    if under is None:
        raise FileNotFoundError("no fractal or sacred art for backdrop")

    dest = work / f"art-backdrop-{width}x{height}.mp4"
    import numpy as np

    base = np.asarray(_cover_rgb(under if fractal else under, width, height).convert("RGB"))
    sacred_rgba = None
    if sacred is not None and is_sacred(sacred):
        sacred_rgba = np_rgba(_fit_rgba(sacred, width, height))
    geos = list_sacred_art()
    if sacred is not None:
        geos = [p for p in geos if p.resolve() != sacred.resolve()]
    slots, pops, symbols_on = _art_plan(f"{seed}-{width}x{height}", duration)
    notes = [
        f"{s['t0']:.0f}s {s['edge']}"
        + (f"+{s['hold']}" if s["hold"] else "")
        + (" glitch" if s["glitch"] is not None else "")
        for s in slots
    ]
    print(
        f"  art {width}x{height}: symbols={symbols_on} pops={len(pops)} | " + "; ".join(notes),
        flush=True,
    )
    cache: dict[str, object] = {}

    def symbol_layer(path: Path, t: float, glitch: bool):
        key = str(path)
        if key not in cache:
            cache[key] = np_rgba(_fit_rgba(path, width, height))
        layer = cache[key]
        if glitch:
            layer = _glitch_rgba(layer, t)
        return _tint_sacred(layer, (t * 40) % 360)

    def frames():
        count = max(1, int(round(duration * ART_FPS)))
        for i in range(count):
            t = i / ART_FPS
            frame = base
            slot = next((s for s in slots if s["t0"] <= t < s["t1"]), slots[-1] if slots else None)
            if sacred_rgba is not None:
                z = SACRED_MIN_OVER + (SACRED_EXPAND - SACRED_MIN_OVER) * min(
                    1.0, t / max(duration, 0.01)
                )
                hue = edges.NAMES.index(slot["edge"]) * (360 / len(edges.NAMES)) if slot else 40
                frame = _over(frame, _tint_sacred(_zoom_center(sacred_rgba, z), hue + t * 12), 0.9)
            if slot and slot["hold"]:
                frame = _hold_fx(frame, slot["hold"], t, slot["t0"])
            elif slot:
                frame = _apply_edge(frame, slot["edge"], t)
            if (
                slot
                and slot["glitch"] is not None
                and geos
                and slot["glitch"] <= t < slot["glitch"] + GLITCH_SECS
            ):
                frame = _over(frame, symbol_layer(geos[int(slot["glitch"]) % len(geos)], t, True), 0.9)
            if geos and symbols_on:
                for pop in pops:
                    if pop <= t < pop + SYMBOL_SECS:
                        frame = _over(
                            frame,
                            symbol_layer(geos[int(pop * 3) % len(geos)], t, False),
                            0.62,
                        )
                        break
            yield frame

    _encode_rgb(frames(), dest, width, height, ART_FPS, duration)
    return dest


def ensure_face_bin() -> Path:
    if FACE_BIN.exists() and FACE_BIN.stat().st_mtime >= FACE_SWIFT.stat().st_mtime:
        return FACE_BIN
    if not FACE_SWIFT.exists():
        raise FileNotFoundError(FACE_SWIFT)
    run(
        [
            "swiftc", "-O", "-o", str(FACE_BIN), str(FACE_SWIFT),
            "-framework", "AppKit", "-framework", "Vision",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
    )
    return FACE_BIN


def detect_faces_dir(folder: Path) -> list[dict]:
    if not any(folder.glob("*.jpg")):
        return []
    try:
        bin_path = ensure_face_bin()
    except (FileNotFoundError, subprocess.CalledProcessError):
        return []
    proc = subprocess.run(
        [str(bin_path), str(folder)],
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0 or not proc.stdout.strip():
        return []
    try:
        return json.loads(proc.stdout)
    except json.JSONDecodeError:
        return []


def extract_sample_frames(video: Path, start: float, duration: float, dest: Path, fps: float = SAMPLE_FPS) -> None:
    dest.mkdir(parents=True, exist_ok=True)
    run(
        [
            "ffmpeg", "-y", "-ss", f"{start:.3f}", "-t", f"{duration:.3f}", "-i", str(video),
            "-vf", f"fps={fps}", str(dest / "f%04d.jpg"),
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def _face_cx(face: dict) -> float:
    return float(face["x"]) + float(face["w"]) / 2.0


def _face_area(face: dict) -> float:
    return max(1.0, float(face["w"]) * float(face["h"]))


def _cluster_id(face: dict, src_w: int) -> int:
    return int(_face_cx(face) / max(1.0, src_w * CLUSTER_GAP))


def _pick_face(faces: list[dict], prev_id: int | None, src_w: int, mode: str, last_switch: float, t: float) -> tuple[dict | None, int | None, float]:
    if not faces:
        return None, prev_id, last_switch
    ranked = sorted(faces, key=_face_area, reverse=True)
    if prev_id is not None:
        same = [f for f in ranked if _cluster_id(f, src_w) == prev_id]
        if mode == "track" and same:
            return same[0], prev_id, last_switch
        if mode == "jump" and same:
            best = ranked[0]
            if _cluster_id(best, src_w) == prev_id:
                return same[0], prev_id, last_switch
            if _face_area(best) < _face_area(same[0]) * JUMP_SIZE_RATIO:
                return same[0], prev_id, last_switch
            if t - last_switch < JUMP_MIN_HOLD:
                return same[0], prev_id, last_switch
            cid = _cluster_id(best, src_w)
            return best, cid, t
    chosen = ranked[0]
    return chosen, _cluster_id(chosen, src_w), t if prev_id is None else last_switch


def _clamp_crop_x(cx: float, src_w: int, crop_w: float) -> int:
    x = int(round(cx - crop_w / 2.0))
    return max(0, min(int(src_w - crop_w), x))


def _median_cx(values: list[float]) -> float:
    s = sorted(values)
    n = len(s)
    if n == 0:
        return 0.0
    mid = n // 2
    if n % 2:
        return s[mid]
    return 0.5 * (s[mid - 1] + s[mid])


def _sticky_targets(
    samples: list[tuple[float, list[dict]]],
    src_w: int,
    crop_w: float,
    mode: str,
) -> tuple[list[tuple[float, int]], int]:
    """Hold the frame still through small face motion; retarget only on real shifts."""
    prev_id = None
    last_switch = -10.0
    switches = 0
    recent: list[float] = []
    targets: list[tuple[float, int]] = []
    held_cx: float | None = None
    crop_x: int | None = None

    for t, faces in samples:
        chosen, new_id, last_switch2 = _pick_face(faces, prev_id, src_w, mode, last_switch, t)
        switched = False
        if prev_id is not None and new_id is not None and new_id != prev_id:
            switches += 1
            switched = True
            recent = []
            held_cx = None
        prev_id, last_switch = new_id, last_switch2
        if not chosen:
            continue
        cx = _face_cx(chosen)
        recent.append(cx)
        if len(recent) > 5:
            recent.pop(0)
        stable = _median_cx(recent)
        if crop_x is None:
            crop_x = _clamp_crop_x(stable, src_w, crop_w)
            held_cx = stable
            targets.append((t, crop_x))
            continue
        center = crop_x + crop_w / 2.0
        moved = abs(stable - (held_cx if held_cx is not None else center))
        off_center = abs(stable - center)
        if switched or (moved >= DEADZONE_FRAC * crop_w and off_center >= STICKY_FRAC * crop_w):
            crop_x = _clamp_crop_x(stable, src_w, crop_w)
            held_cx = stable
            if not targets or abs(crop_x - targets[-1][1]) >= 2:
                targets.append((t, crop_x))
    return targets, switches


def _damped_keys(
    targets: list[tuple[float, int]],
    duration: float,
    src_w: int,
    crop_w: float,
    snap_delta: float | None = None,
) -> list[tuple[float, int]]:
    if not targets:
        return []
    pts = [(0.0, targets[0][1])] + [(max(0.0, t), x) for t, x in targets]
    if pts[-1][0] < duration:
        pts.append((duration, pts[-1][1]))
    dt = 1.0 / CAMERA_FPS
    max_v = crop_w * MAX_PAN_FRAC_PER_S
    max_a = crop_w * MAX_ACCEL_FRAC_PER_S2
    pos = float(pts[0][1])
    vel = 0.0
    i = 0
    out: list[tuple[float, int]] = []
    t = 0.0
    while t <= duration + 1e-6:
        while i + 1 < len(pts) and pts[i + 1][0] <= t:
            i += 1
        tgt = float(pts[i][1])
        if i + 1 < len(pts) and snap_delta is not None and abs(pts[i + 1][1] - pts[i][1]) >= snap_delta:
            if t >= pts[i + 1][0]:
                tgt = float(pts[i + 1][1])
        err = tgt - pos
        if abs(err) <= crop_w * SETTLE_FRAC and abs(vel) <= crop_w * 0.015:
            vel = 0.0
            pos = tgt
        else:
            acc = FOLLOW_OMEGA * FOLLOW_OMEGA * err - 2.0 * FOLLOW_DAMPING * FOLLOW_OMEGA * vel
            acc = max(-max_a, min(max_a, acc))
            vel = max(-max_v, min(max_v, vel + acc * dt))
            pos = pos + vel * dt
        pos = max(0.0, min(float(src_w - crop_w), pos))
        x = int(round(pos))
        if not out or x != out[-1][1]:
            out.append((round(t, 3), x))
        t += dt
    if out and out[-1][0] < duration:
        out.append((round(duration, 3), out[-1][1]))
    return out


def _resample_keys(
    keys: list[tuple[float, int]],
    duration: float,
    step: float = 0.12,
    snap_delta: float | None = None,
) -> list[tuple[float, int]]:
    if not keys:
        return []
    pts = [(0.0, keys[0][1])] + list(keys)
    if pts[-1][0] < duration:
        pts.append((duration, pts[-1][1]))
    out: list[tuple[float, int]] = []
    i = 0
    t = 0.0
    while t <= duration + 1e-6:
        while i + 1 < len(pts) and pts[i + 1][0] < t:
            i += 1
        if i + 1 >= len(pts) or pts[i + 1][0] <= pts[i][0]:
            x = pts[i][1]
        else:
            t0, x0 = pts[i]
            t1, x1 = pts[i + 1]
            if snap_delta is not None and abs(x1 - x0) >= snap_delta:
                x = x0 if t < t1 else x1
            else:
                u = (t - t0) / (t1 - t0)
                x = int(round(x0 + (x1 - x0) * u))
        out.append((round(t, 3), x))
        t += step
    return out


def _percentile(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    s = sorted(values)
    if len(s) == 1:
        return s[0]
    idx = min(len(s) - 1, max(0, int(round((len(s) - 1) * p))))
    return s[idx]


def _scale_boxes(items: list[dict], sx: float, sy: float) -> list[dict]:
    out = []
    for f in items:
        out.append(
            {
                "x": max(0.0, float(f["x"]) * sx),
                "y": max(0.0, float(f["y"]) * sy),
                "w": max(1.0, float(f["w"]) * sx),
                "h": max(1.0, float(f["h"]) * sy),
                "conf": float(f.get("conf") or 0),
            }
        )
    return out


def samples_from_detections(
    rows: list[dict],
    fps: float,
    src_w: int,
    src_h: int,
    use_body: bool = True,
) -> list[tuple[float, list[dict]]]:
    out = []
    for i, row in enumerate(rows):
        t = i / max(fps, 0.001)
        rw = float(row.get("width") or src_w) or src_w
        rh = float(row.get("height") or src_h) or src_h
        sx, sy = src_w / rw, src_h / rh
        faces = _scale_boxes(row.get("faces") or [], sx, sy)
        if use_body and not faces:
            for body in _scale_boxes(row.get("humans") or [], sx, sy):
                head_h = max(12.0, float(body["h"]) * 0.28)
                faces.append(
                    {
                        "x": float(body["x"]) + float(body["w"]) * 0.25,
                        "y": float(body["y"]),
                        "w": float(body["w"]) * 0.50,
                        "h": head_h,
                        "conf": float(body["conf"]) * 0.6,
                    }
                )
        out.append((t, faces))
    return out


def _face_span(faces: list[dict], src_w: int) -> float:
    if len(faces) < 2:
        return 0.0
    xs = [_face_cx(f) for f in faces]
    return (max(xs) - min(xs)) / max(1, src_w)


def _cluster_count(faces: list[dict], src_w: int) -> int:
    return len({_cluster_id(f, src_w) for f in faces})


def plan_framing(
    video: Path,
    start: float,
    end: float,
    src_w: int,
    src_h: int,
    work: Path,
    seed: str,
    sample_fps: float = SAMPLE_FPS,
) -> FramingPlan:
    duration = max(0.2, end - start)
    crop_w = src_h * 9 / 16
    landscape = src_w / max(1, src_h) >= 1.25
    frames_dir = work / "faces"
    extract_sample_frames(video, start, duration, frames_dir, fps=sample_fps)
    rows = detect_faces_dir(frames_dir)
    samples = samples_from_detections(rows, sample_fps, src_w, src_h, use_body=True)
    face_samples = samples_from_detections(rows, sample_fps, src_w, src_h, use_body=False)
    art = (
        _pick_from(list_sacred_art(), seed)
        or _pick_from(list_fractal_art(), seed)
        if landscape
        else None
    )

    if not samples:
        x = int((src_w - crop_w) / 2)
        if landscape:
            return FramingPlan("letterbox", "no-samples", art=art, stats={"faces": 0})
        return FramingPlan("track", "no-samples-center", crop_keys=[(0.0, x)], stats={"faces": 0})

    counts = [len(faces) for _, faces in samples]
    cluster_counts = [_cluster_count(faces, src_w) for _, faces in samples]
    hit_rate = sum(1 for n in counts if n > 0) / max(1, len(counts))
    mean_faces = sum(counts) / max(1, len(counts))
    mean_clusters = sum(cluster_counts) / max(1, len(cluster_counts))
    multi_share = sum(1 for n in cluster_counts if n >= 2) / max(1, len(cluster_counts))
    wide_share = sum(1 for _, faces in samples if _face_span(faces, src_w) >= MULTI_FACE_SPAN) / max(1, len(samples))
    three_share = sum(1 for n in cluster_counts if n >= 3) / max(1, len(cluster_counts))

    stats = {
        "hit_rate": round(hit_rate, 3),
        "mean_faces": round(mean_faces, 2),
        "mean_clusters": round(mean_clusters, 2),
        "multi_share": round(multi_share, 3),
        "wide_share": round(wide_share, 3),
        "samples": len(samples),
    }

    def letterbox(reason: str) -> FramingPlan:
        return FramingPlan("letterbox", reason, art=art, stats=stats)

    if landscape and hit_rate < 0.28:
        return letterbox("few-faces")
    if landscape and three_share >= 0.22:
        return letterbox("crowd")
    if landscape and wide_share >= 0.45 and multi_share >= 0.5:
        return letterbox("wide-action")

    jump_mode = landscape and multi_share >= 0.32 and mean_clusters >= 1.25
    mode = "jump" if jump_mode else "track"

    targets, switches = _sticky_targets(face_samples, src_w, crop_w, mode)
    if not targets:
        targets, switches = _sticky_targets(samples, src_w, crop_w, mode)

    face_speeds = []
    prev_cx = None
    prev_t = None
    prev_id = None
    last_switch = -10.0
    for t, faces in face_samples:
        chosen, new_id, last_switch = _pick_face(faces, prev_id, src_w, mode, last_switch, t)
        prev_id = new_id
        if not chosen:
            continue
        cx = _face_cx(chosen)
        if prev_cx is not None and (t - (prev_t or t)) >= 0.25:
            delta = abs(cx - prev_cx)
            if delta >= DEADZONE_FRAC * crop_w:
                face_speeds.append(delta / max(t - (prev_t or t), 1e-3))
        prev_cx, prev_t = cx, t
    med_speed = _percentile(face_speeds, 0.5)
    p90_speed = _percentile(face_speeds, 0.9)
    stats.update(
        {
            "median_px_s": round(med_speed, 1),
            "p90_px_s": round(p90_speed, 1),
            "switches": switches,
            "retargets": len(targets),
        }
    )
    jump_rate = switches / duration

    if landscape and (med_speed > FAST_MEDIAN_FRAC_PER_S * crop_w or p90_speed > FAST_P90_FRAC_PER_S * crop_w):
        return letterbox("too-fast")
    if mode == "jump" and jump_rate > MAX_JUMPS_PER_S:
        return letterbox("jump-too-often")

    snap = 0.10 * crop_w if mode == "jump" else None
    if not targets:
        x = int((src_w - crop_w) / 2)
        keys = [(0.0, x)]
    else:
        keys = _damped_keys(targets, duration, src_w, crop_w, snap_delta=snap)
    reason = f"two-faces-{switches}jumps" if mode == "jump" else (
        "one-face" if mean_clusters < 1.2 else "primary-face"
    )

    if not landscape:
        reason = "portrait-" + reason
    return FramingPlan(mode, reason, crop_keys=keys, stats=stats)


def write_crop_sendcmd(keys: list[tuple[float, int]], src_h: int, dest: Path) -> None:
    scale = H / max(1, src_h)
    lines = []
    last = None
    for t, x in keys:
        sx = int(round(x * scale))
        if sx % 2:
            sx -= 1
        if last == sx and lines:
            continue
        last = sx
        lines.append(f"{t:.3f} crop x {max(0, sx)};")
    dest.write_text("\n".join(lines) + "\n", encoding="utf-8")


def transcript_paths(video: Path) -> dict[str, Path]:
    stem = video.with_suffix("")
    return {
        "json": Path(str(stem) + ".transcript.json"),
        "srt": Path(str(stem) + ".srt"),
        "txt": Path(str(stem) + ".txt"),
        "wav": Path(str(stem) + ".wav"),
    }


def format_srt_time(t: float) -> str:
    h = int(t // 3600)
    m = int((t % 3600) // 60)
    s = int(t % 60)
    ms = int(round((t - math.floor(t)) * 1000))
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def write_transcript_files(video: Path, payload: dict) -> None:
    paths = transcript_paths(video)
    paths["json"].write_text(json.dumps(payload, indent=2), encoding="utf-8")
    lines = []
    for i, seg in enumerate(payload.get("segments") or [], start=1):
        lines.append(str(i))
        lines.append(f"{format_srt_time(seg['start'])} --> {format_srt_time(seg['end'])}")
        lines.append(seg["text"].strip())
        lines.append("")
    paths["srt"].write_text("\n".join(lines), encoding="utf-8")
    txt = "\n\n".join(seg["text"].strip() for seg in payload.get("segments") or [] if seg.get("text", "").strip())
    paths["txt"].write_text(txt + "\n", encoding="utf-8")
    print(f"  wrote {paths['json'].name}")
    print(f"  wrote {paths['srt'].name}")
    print(f"  wrote {paths['txt'].name}")


def transcribe_hf(video: Path) -> dict:
    from faster_whisper import WhisperModel

    paths = transcript_paths(video)
    if paths["json"].exists():
        print(f"  using cached transcript {paths['json'].name}")
        return json.loads(paths["json"].read_text(encoding="utf-8"))

    wav = paths["wav"]
    print("  extracting audio...")
    run(
        ["ffmpeg", "-y", "-i", str(video), "-vn", "-ac", "1", "-ar", "16000", str(wav)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    print(f"  loading Hugging Face Whisper ({WHISPER_MODEL}, local, free)...")
    model = WhisperModel(WHISPER_MODEL, device="cpu", compute_type="int8")
    print("  transcribing...")
    segments_iter, info = model.transcribe(
        str(wav),
        language="en",
        word_timestamps=True,
        vad_filter=True,
        beam_size=1,
    )
    words = []
    segments = []
    for seg in segments_iter:
        text = (seg.text or "").strip()
        segments.append({"start": float(seg.start), "end": float(seg.end), "text": text})
        print(f"    [{seg.start:7.1f}-{seg.end:7.1f}] {text[:80]}")
        for w in seg.words or []:
            token = (w.word or "").strip()
            if token:
                words.append({"start": float(w.start), "end": float(w.end), "text": token})
    payload = {
        "source": video.name,
        "model": f"faster-whisper/{WHISPER_MODEL}",
        "language": getattr(info, "language", "en"),
        "duration": probe_duration(video),
        "words": words,
        "segments": segments,
    }
    write_transcript_files(video, payload)
    try:
        wav.unlink()
    except OSError:
        pass
    return payload


def pick_logo() -> Path:
    for p in LOGO_CANDIDATES:
        if p.exists():
            return p
    raise FileNotFoundError("no logo")


def prepare_logo(src: Path, dest: Path, target_w: int = 168) -> None:
    im = Image.open(src).convert("RGBA")
    ratio = target_w / im.width
    im = im.resize((target_w, int(im.height * ratio)), Image.Resampling.LANCZOS)
    im.save(dest)


def build_caption_mov(
    cues: list[dict],
    start: float,
    duration: float,
    work: Path,
    band: tuple[int, int] | None = None,
) -> Path | None:
    local = []
    for cue in cues:
        a = max(0.0, cue["start"] - start)
        b = min(duration, max(a + 0.18, cue["end"] - start))
        if b <= 0 or a >= duration:
            continue
        local.append({"start": a, "end": b, "text": cue["text"]})
    if not local:
        return None
    blank = work / "blank.png"
    Image.new("RGBA", (W, H), (0, 0, 0, 0)).save(blank)
    concat = work / "caps.txt"
    rows = ["ffconcat version 1.0"]
    t = 0.0
    n = 0

    def add(png: Path, dur: float) -> None:
        nonlocal n
        if dur <= 0.02:
            return
        rows.append(f"file {png.as_posix()}")
        rows.append(f"duration {dur:.3f}")
        n += 1

    for cue in local:
        if cue["start"] > t:
            add(blank, cue["start"] - t)
        png = work / f"cap_{n:04d}.png"
        render_caption_frame(cue["text"], png, band=band)
        add(png, cue["end"] - cue["start"])
        t = cue["end"]
    if t < duration:
        add(blank, duration - t)
    if n:
        rows.append(rows[-2])
    concat.write_text("\n".join(rows) + "\n", encoding="utf-8")
    mov = work / "captions.mov"
    run(
        [
            "ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(concat),
            "-vsync", "vfr", "-pix_fmt", "argb", "-c:v", "qtrle", str(mov),
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
    )
    return mov


def _support_is_still(path: Path) -> bool:
    return path.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp"}


def _support_inputs(
    support: Path,
    duration: float,
    band_h: int,
    work: Path,
    seed: str = "support",
) -> tuple[list[str], str]:
    """Return ffmpeg input args and a filter that produces a [support] band of W x band_h.

    Still art: fractal under sacred (slow expand) when the pick is sacred geometry.
    """
    if _support_is_still(support):
        if is_sacred(support):
            fractal = _pick_from(list_fractal_art(), seed + "-under")
            sacred = support
        else:
            fractal, sacred = support, None
        backdrop = build_art_backdrop(
            duration, work / "support-art", seed,
            width=W, height=band_h, fractal=fractal, sacred=sacred,
        )
        return (
            ["-i", str(backdrop)],
            f"[1:v]scale={W}:{band_h}:flags=lanczos,setsar=1[support]",
        )
    return (
        ["-ss", "0", "-t", f"{duration:.3f}", "-i", str(support)],
        (
            f"[1:v]scale={W}:{band_h}:force_original_aspect_ratio=increase:flags=lanczos,"
            f"crop={W}:{band_h},setsar=1[support]"
        ),
    )


def _face_crop_filter(video: Path, start: float, duration: float, src_w: int, src_h: int, plan: FramingPlan, work: Path, out_h: int) -> str:
    scaled_w = int(src_w * out_h / src_h)
    if scaled_w % 2:
        scaled_w -= 1
    if plan.crop_keys:
        x0 = int(round(plan.crop_keys[0][1] * out_h / src_h))
    else:
        x0 = int((scaled_w - W) / 2)
    x0 = max(0, min(max(0, scaled_w - W), x0))
    if x0 % 2:
        x0 -= 1
    if plan.crop_keys and out_h == H:
        cmd_file = work / "crop.txt"
        write_crop_sendcmd(plan.crop_keys, src_h, cmd_file)
        return f"[0:v]scale={scaled_w}:{out_h}:flags=lanczos,setsar=1,sendcmd=f={cmd_file.name},crop={W}:{out_h}:{x0}:0[speaker]"
    return f"[0:v]scale={scaled_w}:{out_h}:flags=lanczos,setsar=1,crop={W}:{out_h}:{x0}:0[speaker]"


def render_picture(
    video: Path,
    start: float,
    end: float,
    plan: FramingPlan,
    work: Path,
    dest: Path,
) -> None:
    """Cut the 9:16 picture (layout + framing + cutaways). No logo or captions."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    src_w, src_h = probe_wh(video)
    duration = end - start
    enc = video_encoder()
    inputs = ["-ss", f"{start:.3f}", "-t", f"{duration:.3f}", "-i", str(video)]
    filters: list[str] = []

    if plan.mode == "main-bottom":
        # Prefer sacred-on-fractal for the art pane; fall back to a support clip or fractal.
        fractal, sacred = pick_art_stack(f"{video.stem}-mb-{start:.1f}")
        support = plan.support
        if support is None:
            support = sacred or fractal or plan.art or pick_logo()
        if support is None:
            raise FileNotFoundError("main-bottom needs a support still or video")
        if _support_is_still(support) and sacred and fractal:
            backdrop = build_art_backdrop(
                duration, work / "mb-art", f"{video.stem}-mb-{start:.1f}",
                width=W, height=MAIN_BOTTOM_TOP, fractal=fractal, sacred=sacred,
            )
            support_args, support_filter = (
                ["-i", str(backdrop)],
                f"[1:v]scale={W}:{MAIN_BOTTOM_TOP}:flags=lanczos,setsar=1[support]",
            )
        else:
            support_args, support_filter = _support_inputs(
                support, duration, MAIN_BOTTOM_TOP, work, seed=f"{video.stem}-mb",
            )
        inputs += support_args
        filters.append(support_filter)
        full_plan = FramingPlan(
            "track",
            plan.reason,
            crop_keys=plan.crop_keys,
            stats=plan.stats,
        )
        if not full_plan.crop_keys:
            tracked = plan_framing(video, start, end, src_w, src_h, work / "mb-faces", seed=f"{video.stem}-mb")
            if tracked.crop_keys:
                full_plan.crop_keys = tracked.crop_keys
        # Speaker pane is 62% of the short so the face reads as the main half.
        filters.append(
            _face_crop_filter(
                video, start, duration, src_w, src_h, full_plan, work, MAIN_BOTTOM_SPEAKER
            )
        )
        filters.append("[support][speaker]vstack=inputs=2[vout]")
    elif plan.mode == "letterbox":
        fractal, sacred = pick_art_stack(f"{video.stem}-letterbox-{start:.1f}")
        if plan.art:
            if is_sacred(plan.art):
                sacred = plan.art
                fractal = fractal or _pick_from(list_fractal_art(), f"{video.stem}-under")
            else:
                fractal = plan.art
        if fractal is None and sacred is None:
            raise FileNotFoundError("letterbox needs fractal or sacred art")
        backdrop = build_art_backdrop(
            duration, work / "lb-art", f"{video.stem}-lb-{start:.1f}",
            width=W, height=H, fractal=fractal, sacred=sacred,
        )
        vid_h = int(round(W * src_h / src_w))
        if vid_h % 2:
            vid_h -= 1
        inputs += ["-i", str(backdrop)]
        filters = [
            f"[0:v]scale={W}:{vid_h}:flags=lanczos,setsar=1[vid]",
            f"[1:v]scale={W}:{H}:flags=lanczos,setsar=1[bg]",
            "[bg][vid]overlay=(W-w)/2:(H-h)/2[vout]",
        ]
    else:
        # full / track / jump / cutaway base
        use_plan = plan
        if plan.mode == "cutaway" and not plan.crop_keys:
            tracked = plan_framing(video, start, end, src_w, src_h, work / "cut-faces", seed=f"{video.stem}-cut")
            use_plan = FramingPlan(
                tracked.mode if tracked.mode in {"track", "jump"} else "track",
                tracked.reason,
                crop_keys=tracked.crop_keys,
                support=plan.support,
                cutaways=plan.cutaways,
                art=plan.art,
                stats=tracked.stats,
            )
        filters.append(
            _face_crop_filter(video, start, duration, src_w, src_h, use_plan, work, H).replace(
                "[speaker]", "[base]"
            )
        )
        last = "base"
        if plan.mode == "cutaway":
            fractal, sacred = pick_art_stack(f"{video.stem}-cutaway-{start:.1f}")
            support = plan.support
            if support is None:
                support = sacred or fractal or plan.art or pick_logo()
            if support is None:
                raise FileNotFoundError("cutaway needs a support still or video")
            if _support_is_still(support) and sacred and fractal:
                backdrop = build_art_backdrop(
                    duration, work / "cut-art", f"{video.stem}-cut-{start:.1f}",
                    width=W, height=CUTAWAY_BAND, fractal=fractal, sacred=sacred,
                )
                support_args, support_filter = (
                    ["-i", str(backdrop)],
                    f"[1:v]scale={W}:{CUTAWAY_BAND}:flags=lanczos,setsar=1[band]",
                )
            else:
                support_args, support_filter = _support_inputs(
                    support, duration, CUTAWAY_BAND, work, seed=f"{video.stem}-cut",
                )
                support_filter = support_filter.replace("[support]", "[band]")
            inputs += support_args
            filters.append(support_filter)
            spans = plan.cutaways or []
            if spans:
                enable = "+".join(f"between(t\\,{a:.3f}\\,{b:.3f})" for a, b in spans)
                filters.append(f"[{last}][band]overlay=0:0:enable='{enable}'[cut]")
                last = "cut"
        filters.append(f"[{last}]copy[vout]")

    cmd = [
        "ffmpeg", "-y", *inputs,
        "-filter_complex", ";".join(filters),
        "-map", "[vout]", "-map", "0:a?",
        *enc, "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "128k",
        "-t", f"{duration:.3f}",
        "-movflags", "+faststart", str(dest),
    ]
    run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, cwd=str(work))


def composite_top(
    picture: Path,
    cues: list[dict],
    start: float,
    end: float,
    work: Path,
    dest: Path,
    layout: str | None = None,
    hook: dict | None = None,
) -> None:
    """Burn the opening hook, then the logo and captions.

    On main-bottom (62% video), captions sit centered in the secondary art band.
    The hook is already inside the middle 38% and stays under the logo.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    if hook is None:
        text = " ".join(str(c.get("text") or "") for c in cues[:12])
        rng = random.Random(text or f"{start:.2f}")
        kind = rng.choice(("cloud", "ask"))
        words, emphasis = hooks.phrase(text, kind, rng)
        hook = {
            "kind": kind,
            "style": rng.choice(hooks.STYLES),
            "shape": rng.choice(hooks.SHAPES),
            "words": words,
            "emphasis": emphasis,
            "clip": None,
        }
    hooked = work / "hooked.mp4"
    hooks.burn(
        picture, hooked,
        hooks.paint(
            hook["words"], hook["style"], hook["shape"], int(hook["emphasis"]),
            work, viral=hook["kind"] == "viral",
        ),
        hook.get("clip"), work,
    )
    picture = hooked
    duration = end - start
    logo = work / "logo.png"
    if STYLE.get("logo") == "none":
        logo_file = None
    elif STYLE.get("logo"):
        logo_file = ROOT / STYLE["logo"]
    else:
        logo_file = pick_logo()
    if logo_file:
        prepare_logo(logo_file, logo)
    band = (0, MAIN_BOTTOM_TOP) if layout == "main-bottom" else None
    if hook and hook.get("kind") == "viral":
        cues = [
            {**c, "start": max(float(c["start"]), start + hooks.HOLD)}
            for c in cues
            if float(c["end"]) > start + hooks.HOLD
        ]
    cap_mov = build_caption_mov(cues, start, duration, work, band=band)
    enc = video_encoder()
    inputs = ["-i", str(picture)]
    filters: list[str] = []
    last = "0:v"
    next_idx = 1

    if logo_file:
        logo_idx = next_idx
        next_idx += 1
        if hook and hook.get("kind") == "viral":
            inputs += ["-loop", "1", "-t", f"{duration:.3f}", "-i", str(logo)]
            filters.append(f"[{logo_idx}:v]format=rgba,fade=t=in:st=1:d=0.45:alpha=1[lg]")
            filters.append(f"[{last}][lg]overlay=W-w-36:36:enable='gte(t,1)'[logoed]")
        else:
            inputs += ["-i", str(logo)]
            filters.append(f"[{last}][{logo_idx}:v]overlay=W-w-36:36[logoed]")
        last = "logoed"

    if cap_mov:
        inputs += ["-i", str(cap_mov)]
        if last == "0:v":
            filters.append(f"[{next_idx}:v]format=rgba[cc]")
            filters.append(f"[0:v][cc]overlay=0:0[vout]")
        else:
            filters.append(f"[{next_idx}:v]format=rgba[cc]")
            filters.append(f"[{last}][cc]overlay=0:0[vout]")
    elif last == "0:v":
        filters.append("[0:v]copy[vout]")
    else:
        filters.append(f"[{last}]copy[vout]")

    cmd = [
        "ffmpeg", "-y", *inputs,
        "-filter_complex", ";".join(filters),
        "-map", "[vout]", "-map", "0:a?",
        *enc, "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "128k",
        "-t", f"{duration:.3f}",
        "-movflags", "+faststart", str(dest),
    ]
    run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, cwd=str(work))


def render_short(video: Path, start: float, end: float, cues: list[dict], plan: FramingPlan, work: Path, dest: Path) -> None:
    picture = work / "picture.mp4"
    render_picture(video, start, end, plan, work, picture)
    layout = "main-bottom" if plan.mode == "main-bottom" else None
    composite_top(picture, cues, start, end, work, dest, layout=layout)


def plan_layout(
    video: Path,
    start: float,
    end: float,
    layout: str,
    work: Path,
    support: Path | None = None,
    words: list[dict] | None = None,
) -> FramingPlan:
    """Build the framing plan for a layout without rendering."""
    src_w, src_h = probe_wh(video)
    if layout == "main-bottom":
        tracked = plan_framing(video, start, end, src_w, src_h, work / "faces", seed=f"{video.stem}-mb")
        return FramingPlan(
            "main-bottom",
            tracked.reason,
            crop_keys=tracked.crop_keys if tracked.mode in {"track", "jump"} else [],
            support=support or pick_art(f"{video.stem}-mb"),
            stats=tracked.stats,
        )
    if layout == "cutaway":
        tracked = plan_framing(video, start, end, src_w, src_h, work / "faces", seed=f"{video.stem}-cut")
        spans = cutaway_spans(words or [], start, end) if words else []
        return FramingPlan(
            "cutaway",
            tracked.reason,
            crop_keys=tracked.crop_keys if tracked.mode in {"track", "jump"} else [],
            support=support or pick_art(f"{video.stem}-cut"),
            cutaways=spans,
            stats=tracked.stats,
        )
    if STYLE.get("frame") == "letterbox":
        return FramingPlan("letterbox", "style", art=pick_art(f"{video.stem}-full"))
    if STYLE.get("frame") == "center-crop":
        crop_w = src_h * 9 / 16
        return FramingPlan("track", "style-center", crop_keys=[(0.0, max(0, int((src_w - crop_w) / 2)))])
    return plan_framing(video, start, end, src_w, src_h, work / "faces", seed=f"{video.stem}-full")


def render_layout_short(
    video: Path,
    start: float,
    end: float,
    cues: list[dict],
    layout: str,
    work: Path,
    dest: Path,
    support: Path | None = None,
    words: list[dict] | None = None,
) -> FramingPlan:
    """Render one short with layout full | main-bottom | cutaway. Main audio only."""
    plan = plan_layout(video, start, end, layout, work, support=support, words=words)
    render_short(video, start, end, cues, plan, work, dest)
    return plan


def slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:60]


def default_videos() -> list[Path]:
    found = sorted(LONG_DIR.glob("*.mp4"))
    return found


def next_youtube(text: str) -> tuple[str, int] | None:
    found = re.search(
        r"https?://(?:www\.|m\.)?(?:youtube\.com/(?:watch\?[^\s<>\"']+|shorts/[^\s<>\"']+|live/[^\s<>\"']+|embed/[^\s<>\"']+)|youtu\.be/[^\s<>\"']+)",
        text,
        re.I,
    )
    if not found:
        return None
    url = found.group(0).rstrip(").,;]}")
    return url, found.start() + len(url)


def chop_video(video: Path, out_dir: Path, name: str, plan_only: bool) -> list[Path] | None:
    duration = probe_duration(video)
    src_w, src_h = probe_wh(video)
    print(f"\n{video.name} ({duration:.1f}s {src_w}x{src_h})")
    payload = transcribe_hf(video)
    words = payload.get("words") or []
    windows = windows_from_transcript(payload, duration)
    print(f"  {len(words)} words, {len(windows)} talking shorts")
    cues = group_words(words, max_words=int(STYLE.get("words") or 3))
    made: list[Path] = []
    with tempfile.TemporaryDirectory() as td:
        work = Path(td)
        n = 0
        for a, b in windows:
            if not (MIN_SHORT <= (b - a) <= MAX_SHORT):
                print(f"  skip {a:.1f}-{b:.1f}s ({b-a:.1f}s) outside 15s-3min")
                continue
            n += 1
            clip_words = [w["text"] for w in words if float(w["start"]) >= a - 0.05 and float(w["end"]) <= b + 0.05]
            preview = " ".join(clip_words)
            if len(preview) > 110:
                preview = preview[:110] + "..."
            section_work = work / f"s{n:02d}"
            section_work.mkdir()
            if STYLE.get("frame") == "letterbox":
                plan = FramingPlan("letterbox", "style", art=pick_art(f"{video.stem}-{n}"))
            elif STYLE.get("frame") == "center-crop":
                crop_w = src_h * 9 / 16
                plan = FramingPlan("track", "style-center", crop_keys=[(0.0, max(0, int((src_w - crop_w) / 2)))])
            else:
                plan = plan_framing(video, a, b, src_w, src_h, section_work, seed=f"{video.stem}-{n}")
            print(f"    plan s{n:02d} {a:.1f}-{b:.1f}s ({b-a:.1f}s) {plan.summary()} {preview}")
            if plan_only:
                continue
            section_cues = [c for c in cues if c["end"] > a and c["start"] < b]
            out = out_dir / f"{slug(name)}-s{n:02d}.mp4"
            print(f"  s{n:02d} {a:.1f}-{b:.1f}s ({b-a:.1f}s) {plan.summary()}")
            try:
                render_short(video, a, b, section_cues, plan, section_work, out)
            except subprocess.CalledProcessError as e:
                err = e.stderr.decode() if e.stderr else str(e)
                print(f"  ffmpeg failed: {err[-900:]}", file=sys.stderr)
                return None
            made.append(out)
            print(f"    wrote {out}")
    return made


def run_project(project: Path, plan_only: bool) -> int:
    cfg_path = project / "config.json"
    pending = project / "pending_videos.txt"
    if not cfg_path.is_file():
        print(f"missing {cfg_path}", file=sys.stderr)
        return 1
    if not pending.is_file():
        print(f"missing {pending}", file=sys.stderr)
        return 1
    STYLE.clear()
    STYLE.update(resolve(json.loads(cfg_path.read_text(encoding="utf-8"))))
    found = next_youtube(pending.read_text(encoding="utf-8"))
    if not found:
        print(f"no youtube link in {pending}")
        return 0
    url = found[0]
    vid = re.search(r"(?:v=|/shorts/|/live/|/embed/|youtu\.be/)([\w-]{11})", url)
    if not vid:
        print(f"no video id in {url}", file=sys.stderr)
        return 1
    sources = project / "sources"
    sources.mkdir(parents=True, exist_ok=True)
    dest = sources / f"{vid.group(1)}.mp4"
    info = dest.with_suffix(".info.json")
    if not dest.is_file():
        ytdlp = shutil.which("yt-dlp")
        if not ytdlp:
            for candidate in ("/usr/local/bin/yt-dlp", "/opt/homebrew/bin/yt-dlp"):
                if Path(candidate).is_file():
                    ytdlp = candidate
                    break
        if not ytdlp:
            print("yt-dlp not found. Install it with: pip install -U yt-dlp", file=sys.stderr)
            return 1
        print(f"pull {url}")
        try:
            run(
                [
                    ytdlp, "--no-playlist",
                    "-f", "bv*[vcodec^=avc1][ext=mp4]+ba[ext=m4a]/b[ext=mp4]/bv*+ba/b",
                    "--merge-output-format", "mp4",
                    "--write-info-json",
                    "-o", str(dest),
                    url,
                ]
            )
        except subprocess.CalledProcessError:
            print(f"could not download {url}", file=sys.stderr)
            return 1
    if not dest.is_file():
        print(f"download finished without {dest.name}", file=sys.stderr)
        return 1
    if not info.is_file():
        info = Path(str(dest) + ".info.json")
    title = vid.group(1)
    if info.is_file():
        try:
            title = json.loads(info.read_text(encoding="utf-8")).get("title") or title
        except json.JSONDecodeError:
            pass
    name = slug(title) or vid.group(1)
    out_dir = project / name
    print(f"{project.name}  {STYLE.get('font_name', 'default font')}  → {out_dir.relative_to(ROOT)}")
    made = chop_video(dest, out_dir, name, plan_only)
    if made is None:
        return 1
    if plan_only:
        return 0
    if not made:
        print("no shorts from this video", file=sys.stderr)
        return 1
    text = pending.read_text(encoding="utf-8")
    again = next_youtube(text)
    if not again or again[0] != url:
        print(f"left {pending.name} in place (the first link changed during the run)")
        return 0
    pending.write_text(text[again[1]:], encoding="utf-8")
    print(f"removed the first link from {pending.name}")
    print("\nDone:")
    for path in made:
        print(" ", path)
    return 0


def main() -> int:
    args = sys.argv[1:]
    plan_only = "--plan" in args
    if "--project" in args:
        slot = args.index("--project")
        if slot + 1 >= len(args):
            print('need a project folder, for example --project "Aquarius Academy"', file=sys.stderr)
            return 1
        project = Path(args[slot + 1])
        if not project.is_absolute():
            project = ROOT / project
        return run_project(project, plan_only)
    OUT_DIR.mkdir(exist_ok=True)
    names = [a for a in args if a != "--plan"]
    videos = []
    if names:
        for name in names:
            p = Path(name)
            videos.append(p if p.exists() else (LONG_DIR / name if (LONG_DIR / name).exists() else VIDEO_DIR / name))
    else:
        videos = default_videos()
    if not videos:
        print("no long videos found", file=sys.stderr)
        return 1

    made: list[Path] = []
    for video in videos:
        if not video.exists():
            print(f"skip missing {video}")
            continue
        got = chop_video(video, OUT_DIR, video.stem, plan_only)
        if got is None:
            return 1
        made.extend(got)
    print("\nDone:")
    for path in made:
        print(" ", path)
    if plan_only:
        return 0
    return 0 if made else 1


if __name__ == "__main__":
    sys.exit(main())
