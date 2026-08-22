#!/usr/bin/env python3
"""Build 9:16 talking shorts from long videos. Local ffmpeg + Hugging Face Whisper."""

from __future__ import annotations

import json
import math
import re
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
LONG_DIR = ROOT / "Long Videos"
VIDEO_DIR = ROOT / "Video Samples"
OUT_DIR = ROOT / "Shorts"
LOGO_CANDIDATES = [
    ROOT / "Token Images" / "EASY.png",
    ROOT / "Token Images" / "AA-Logo[PurpleInCircle][WhiteBG][1.4][512].png",
]
ART_DIRS = [
    ROOT / "Gudasol Fractal Art",
    ROOT / "Gudasol Sacred Geometry Art",
]
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
    for path, index in FONT_PATHS:
        if path.exists():
            return ImageFont.truetype(str(path), size=size, index=index)
    raise FileNotFoundError("no caption font found")


def render_caption_png(text: str, dest: Path, max_width: int = 980) -> Image.Image:
    text = re.sub(r"\s+", " ", text).strip().upper()
    dummy = ImageDraw.Draw(Image.new("RGBA", (4, 4)))
    if not text:
        img = Image.new("RGBA", (1, 1), (0, 0, 0, 0))
        dest.parent.mkdir(parents=True, exist_ok=True)
        img.save(dest)
        return img

    font_size = 92
    bbox = (0, 0, 0, 0)
    tw = th = 0
    font = load_font(font_size)
    while font_size >= 48:
        font = load_font(font_size)
        bbox = dummy.textbbox((0, 0), text, font=font)
        tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
        if tw + 80 <= max_width:
            break
        font_size -= 4

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
    dr.rectangle([x0, y0, x0 + box_w - 1, y0 + box_h - 1], fill=YELLOW)
    dr.rectangle([0, 0, tick_w - 1, canvas_h - 1], fill=WHITE)
    dr.rectangle([canvas_w - tick_w, 0, canvas_w - 1, canvas_h - 1], fill=WHITE)
    dr.text((x0 + pad_x - bbox[0], y0 + pad_y - bbox[1]), text, font=font, fill=BLACK)
    dest.parent.mkdir(parents=True, exist_ok=True)
    img.save(dest)
    return img


def render_caption_frame(text: str, dest: Path) -> None:
    frame = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    bar = render_caption_png(text, dest.with_suffix(".bar.png"))
    x = (W - bar.width) // 2
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


@dataclass
class FramingPlan:
    mode: str
    reason: str
    crop_keys: list[tuple[float, int]] = field(default_factory=list)
    art: Path | None = None
    stats: dict = field(default_factory=dict)

    def summary(self) -> str:
        extra = ""
        if self.art:
            extra = f" art={self.art.name}"
        hit = self.stats.get("hit_rate")
        if hit is not None:
            extra += f" hit={hit}"
        return f"{self.mode} ({self.reason}){extra}"


def list_art() -> list[Path]:
    files: list[Path] = []
    for folder in ART_DIRS:
        if not folder.is_dir():
            continue
        files.extend(p for p in folder.iterdir() if p.suffix.lower() in {".jpg", ".jpeg", ".png"})
    # Prefer the 2k masters; 11k prints are too heavy to stamp as a background.
    compact = [p for p in files if "[11k]" not in p.name]
    return sorted(compact or files)


def pick_art(seed: str) -> Path | None:
    files = list_art()
    if not files:
        return None
    acc = 0
    for ch in seed:
        acc = (acc * 33 + ord(ch)) & 0xFFFFFFFF
    return files[acc % len(files)]


def prepare_art_bg(src: Path, dest: Path) -> None:
    im = Image.open(src).convert("RGB")
    scale = max(W / im.width, H / im.height)
    nw, nh = max(W, int(im.width * scale)), max(H, int(im.height * scale))
    im = im.resize((nw, nh), Image.Resampling.LANCZOS)
    left = max(0, (nw - W) // 2)
    top = max(0, (nh - H) // 2)
    im = im.crop((left, top, left + W, top + H))
    dest.parent.mkdir(parents=True, exist_ok=True)
    im.save(dest, quality=92)


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
    art = pick_art(seed) if landscape else None

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


def build_caption_mov(cues: list[dict], start: float, duration: float, work: Path) -> Path | None:
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
        render_caption_frame(cue["text"], png)
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


def render_short(video: Path, start: float, end: float, cues: list[dict], plan: FramingPlan, work: Path, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    src_w, src_h = probe_wh(video)
    duration = end - start
    logo = work / "logo.png"
    prepare_logo(pick_logo(), logo)
    cap_mov = build_caption_mov(cues, start, duration, work)

    if plan.mode == "letterbox":
        art_src = plan.art or pick_art(video.stem) or pick_logo()
        art_png = work / "art.jpg"
        prepare_art_bg(art_src, art_png)
        vid_h = int(round(W * src_h / src_w))
        if vid_h % 2:
            vid_h -= 1
        inputs = [
            "-ss", f"{start:.3f}", "-t", f"{duration:.3f}", "-i", str(video),
            "-i", str(art_png), "-i", str(logo),
        ]
        filters = [
            f"[0:v]scale={W}:{vid_h}:flags=lanczos,setsar=1[vid]",
            f"[1:v]scale={W}:{H}:flags=lanczos,setsar=1[bg]",
            "[bg][vid]overlay=(W-w)/2:(H-h)/2[base]",
            "[base][2:v]overlay=W-w-36:36[logoed]",
        ]
        cap_idx = 3
    else:
        scaled_w = int(src_w * H / src_h)
        if scaled_w % 2:
            scaled_w -= 1
        if plan.crop_keys:
            x0 = int(round(plan.crop_keys[0][1] * H / src_h))
        else:
            x0 = int((scaled_w - W) / 2)
        x0 = max(0, min(max(0, scaled_w - W), x0))
        if x0 % 2:
            x0 -= 1
        cmd_file = work / "crop.txt"
        if plan.crop_keys:
            write_crop_sendcmd(plan.crop_keys, src_h, cmd_file)
            crop = f"sendcmd=f={cmd_file.name},crop={W}:{H}:{x0}:0"
        else:
            crop = f"crop={W}:{H}:{x0}:0"
        inputs = ["-ss", f"{start:.3f}", "-t", f"{duration:.3f}", "-i", str(video), "-i", str(logo)]
        filters = [
            f"[0:v]scale={scaled_w}:{H}:flags=lanczos,setsar=1,{crop}[base]",
            "[base][1:v]overlay=W-w-36:36[logoed]",
        ]
        cap_idx = 2

    if cap_mov:
        inputs += ["-i", str(cap_mov)]
        filters.append(f"[{cap_idx}:v]format=rgba[cc]")
        filters.append("[logoed][cc]overlay=0:0[vout]")
    else:
        filters.append("[logoed]copy[vout]")
    cmd = [
        "ffmpeg", "-y", *inputs,
        "-filter_complex", ";".join(filters),
        "-map", "[vout]", "-map", "0:a?",
        "-c:v", "h264_videotoolbox", "-b:v", "8M", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "128k",
        "-t", f"{duration:.3f}",
        "-movflags", "+faststart", str(dest),
    ]
    run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, cwd=str(work))


def slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:60]


def default_videos() -> list[Path]:
    found = sorted(LONG_DIR.glob("*.mp4"))
    return found


def main() -> int:
    OUT_DIR.mkdir(exist_ok=True)
    names = [a for a in sys.argv[1:] if a != "--plan"]
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

    made = []
    for video in videos:
        if not video.exists():
            print(f"skip missing {video}")
            continue
        duration = probe_duration(video)
        src_w, src_h = probe_wh(video)
        print(f"\n{video.name} ({duration:.1f}s {src_w}x{src_h})")
        payload = transcribe_hf(video)
        words = payload.get("words") or []
        windows = windows_from_transcript(payload, duration)
        print(f"  {len(words)} words, {len(windows)} talking shorts")
        cues = group_words(words)
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
                plan = plan_framing(video, a, b, src_w, src_h, section_work, seed=f"{video.stem}-{n}")
                print(f"    plan s{n:02d} {a:.1f}-{b:.1f}s ({b-a:.1f}s) {plan.summary()} {preview}")
                if "--plan" in sys.argv:
                    continue
                section_cues = [c for c in cues if c["end"] > a and c["start"] < b]
                out = OUT_DIR / f"{slug(video.stem)}-s{n:02d}.mp4"
                print(f"  s{n:02d} {a:.1f}-{b:.1f}s ({b-a:.1f}s) {plan.summary()}")
                try:
                    render_short(video, a, b, section_cues, plan, section_work, out)
                except subprocess.CalledProcessError as e:
                    err = e.stderr.decode() if e.stderr else str(e)
                    print(f"  ffmpeg failed: {err[-900:]}", file=sys.stderr)
                    return 1
                made.append(out)
                print(f"    wrote {out.name}")
    print("\nDone:")
    for p in made:
        print(" ", p)
    if "--plan" in sys.argv:
        return 0
    return 0 if made else 1


if __name__ == "__main__":
    sys.exit(main())
