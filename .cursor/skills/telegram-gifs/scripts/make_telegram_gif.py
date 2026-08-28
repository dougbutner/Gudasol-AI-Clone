#!/usr/bin/env python3
"""Render silent 480x480 Telegram GIFs (muted H.264 MP4, 3–6s, face-locked)."""

from __future__ import annotations

import argparse
import colorsys
import json
import math
import random
import re
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

ROOT = Path(__file__).resolve().parents[4]
OUT_DIR = ROOT / "Telegram Gifs"
CULT_DIR = OUT_DIR / "Cult of Code"
WORK = OUT_DIR / ".work"
CATEGORIES = ("Spiritual", "Crypto", "Music", "Gudasol")
GALACTIC = (
    ROOT
    / "Long Videos"
    / "Cracking the Galactic Code of Lifelight with Gudasol - 12min.mp4"
)
FACE_SWIFT = ROOT / "tools" / "detect_faces.swift"
FACE_BIN = ROOT / "tools" / "detect_faces"
SIZE = 480
FPS = 30
SCAN_FPS = 1.0
MIN_FACE_FRAC = 0.003

FONTS = [
    Path("/System/Library/Fonts/Supplemental/Impact.ttf"),
    Path("/System/Library/Fonts/Supplemental/Arial Bold.ttf"),
]
URL_FONT = Path("/System/Library/Fonts/Supplemental/Arial Bold.ttf")

URLS = (
    "douglas.life",
    "flex.report",
    "aquarius.academy",
    "tetra.earth",
    "cxc.world",
)

LOGOS = {
    "douglas.life": ROOT / "Token Images" / "EASY.png",
    "flex.report": ROOT / "Token Images" / "meme.png",
    "aquarius.academy": ROOT
    / "Token Images"
    / "AA-Logo[PurpleInCircle][WhiteBG][1.4][512].png",
    "tetra.earth": ROOT / "Token Images" / "grams-512.png",
    "cxc.world": ROOT / "Token Images" / "Purple-Token-[1.2][ThinCircleOL][640px].png",
}

CRYPTO_KEYS = {
    "rekt", "hodl", "wagmi", "ngmi", "lfg", "fomo", "dyor", "nfa", "buidl",
    "ape", "degen", "moon", "pump", "dump", "wen", "gmi", "alpha", "anon",
    "bullish", "bearish", "paper", "diamond", "hands", "send", "ct", "ser",
    "poor",
}
MUSIC_KEYS = {
    "vibe", "banger", "drop", "432", "hz", "beat", "mix", "track", "song",
    "flow", "cxc",
}
SPIRIT_KEYS = {
    "namaste", "om", "awaken", "bless", "based", "cult", "spirit", "light",
}
GREET_KEYS = {"gm", "gn", "guda", "yves", "approves", "dissapproves", "disapproves"}
CODE_KEYS = {"code", "push", "telegram", "yves"}

MORE_20 = [
    "APE", "DEGEN", "MOON", "PUMP", "DUMP", "WEN", "SEND IT",
    "DIAMOND HANDS", "PAPER HANDS", "BULLISH", "ALPHA", "ANON",
    "VIBE", "BANGER", "DROP", "432HZ",
    "NAMASTE", "AWAKEN", "BLESS UP", "OM",
]

CULT_10 = [
    "Join the Cult",
    "Cult of Code",
    "Have fun being poor",
    "ok Yves",
    "Guda Approves",
    "Guda Dissapproves",
    "Push the code",
    "shut up and push code",
    "less telegram more code",
    "Welcome to the Cult",
]

GM_MORE = ["GM"] * 8

STYLE_NAMES = [
    "impact_bounce",
    "typewriter",
    "rainbow_stagger",
    "drop_in",
    "neon_pulse",
    "karaoke_words",
    "shake",
    "glitch_chroma",
    "wave",
    "stamp",
]


_FFMPEG: str | None = None
_ENC_ARGS: list[str] | None = None
_FFPROBE: str | None = None


def find_ffmpeg() -> str:
    global _FFMPEG
    if _FFMPEG:
        return _FFMPEG
    candidates: list[str] = []
    opt = Path("/usr/local/opt/ffmpeg/bin/ffmpeg")
    if opt.is_file():
        candidates.append(str(opt))
    cellar = Path("/usr/local/Cellar/ffmpeg")
    if cellar.is_dir():
        candidates.extend(sorted(str(p) for p in cellar.glob("*/bin/ffmpeg")))
    which = shutil.which("ffmpeg")
    if which:
        candidates.append(which)
    seen: set[str] = set()
    libx: str | None = None
    any_bin: str | None = None
    for c in candidates:
        if c in seen or not Path(c).is_file():
            continue
        seen.add(c)
        probe = subprocess.run([c, "-hide_banner", "-encoders"], capture_output=True, text=True)
        if "libx264" in probe.stdout:
            libx = c
            break
        any_bin = any_bin or c
    _FFMPEG = libx or any_bin
    if not _FFMPEG:
        sys.exit("ffmpeg not found")
    return _FFMPEG


def find_ffprobe() -> str:
    global _FFPROBE
    if _FFPROBE:
        return _FFPROBE
    ff = Path(find_ffmpeg())
    cand = ff.with_name("ffprobe")
    _FFPROBE = str(cand) if cand.is_file() else (shutil.which("ffprobe") or "")
    if not _FFPROBE:
        sys.exit("ffprobe not found")
    return _FFPROBE


def encoder_args(ffmpeg: str) -> list[str]:
    global _ENC_ARGS
    if _ENC_ARGS is not None:
        return _ENC_ARGS
    probe = subprocess.run(
        [ffmpeg, "-hide_banner", "-encoders"], capture_output=True, text=True
    )
    if "libx264" in probe.stdout:
        _ENC_ARGS = ["-c:v", "libx264", "-profile:v", "baseline", "-level", "3.0"]
        return _ENC_ARGS
    if "h264_videotoolbox" in probe.stdout:
        _ENC_ARGS = ["-c:v", "h264_videotoolbox", "-profile:v", "baseline"]
        return _ENC_ARGS
    sys.exit("Need libx264 or h264_videotoolbox")


def load_font(path: Path, size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(path), size)


def pick_font() -> Path:
    for p in FONTS:
        if p.is_file():
            return p
    sys.exit("No usable TTF found (Impact / Arial Bold).")


def slug(text: str) -> str:
    s = re.sub(r"[^a-zA-Z0-9]+", "-", text.strip().lower()).strip("-")
    return s or "clip"


def pick_url(text: str) -> str:
    blob = text.lower()
    tokens = set(re.findall(r"[a-z0-9]+", blob))
    if tokens & CRYPTO_KEYS or "diamond hands" in blob or "paper hands" in blob or "send it" in blob:
        return "flex.report"
    if tokens & MUSIC_KEYS or "432" in blob:
        return "cxc.world"
    if tokens & SPIRIT_KEYS or "cult" in blob:
        return "aquarius.academy"
    if tokens & GREET_KEYS:
        return "douglas.life"
    if "code" in blob or "push" in blob or "telegram" in blob:
        return "douglas.life"
    return "douglas.life"


def pick_category(text: str) -> str | None:
    blob = text.lower()
    tokens = set(re.findall(r"[a-z0-9]+", blob))
    if tokens & CRYPTO_KEYS or "diamond hands" in blob or "paper hands" in blob or "send it" in blob:
        return "Crypto"
    if tokens & MUSIC_KEYS or "432" in blob:
        return "Music"
    if tokens & SPIRIT_KEYS or "cult" in blob:
        return "Spiritual"
    if tokens & GREET_KEYS or tokens & CODE_KEYS:
        return "Gudasol"
    return None


def phrase_from_filename(name: str) -> str:
    stem = Path(name).stem
    stem = re.sub(r"-gudasol-\d{8}-\d{6}.*$", "", stem, flags=re.I)
    for url in sorted(URLS, key=len, reverse=True):
        suffix = "-" + url
        if stem.endswith(suffix):
            return stem[: -len(suffix)].replace("-", " ")
    return stem.replace("-", " ")


def duration_for(text: str, i: int) -> float:
    base = 3.2 + (len(text) / 28.0) + (i % 5) * 0.25
    return round(min(6.0, max(3.0, base)), 2)


def ensure_face_bin() -> Path:
    if FACE_BIN.exists() and (
        not FACE_SWIFT.exists() or FACE_BIN.stat().st_mtime >= FACE_SWIFT.stat().st_mtime
    ):
        return FACE_BIN
    if not FACE_SWIFT.exists():
        sys.exit(f"Missing {FACE_SWIFT}")
    subprocess.run(
        [
            "swiftc", "-O", "-o", str(FACE_BIN), str(FACE_SWIFT),
            "-framework", "AppKit", "-framework", "Vision",
        ],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
    )
    return FACE_BIN


def detect_faces_dir(folder: Path) -> list[dict]:
    proc = subprocess.run(
        [str(ensure_face_bin()), str(folder)],
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0 or not proc.stdout.strip():
        return []
    return json.loads(proc.stdout)


def largest_face(row: dict) -> dict | None:
    """True face boxes only — never body/head estimates (those crop on backs/leaves)."""
    w = float(row.get("width") or 1)
    h = float(row.get("height") or 1)
    area = max(1.0, w * h)
    faces = [
        f
        for f in (row.get("faces") or [])
        if float(f.get("conf") or 0) >= 0.55
    ]
    if not faces:
        return None
    faces = sorted(faces, key=lambda f: float(f["w"]) * float(f["h"]), reverse=True)
    f = faces[0]
    if (float(f["w"]) * float(f["h"])) / area < MIN_FACE_FRAC:
        return None
    return f


def face_windows(
    rows: list[dict], src_w: int, src_h: int, n: int, seconds: list[float], phase: float = 0.0
) -> list[tuple[float, tuple[int, int, int]]]:
    hits: list[tuple[int, dict]] = []
    for i, row in enumerate(rows):
        face = largest_face(row)
        if face:
            hits.append((i, face))
    if len(hits) < n:
        sys.exit(f"Only {len(hits)} face frames; need {n}")
    picked: list[tuple[float, tuple[int, int, int]]] = []
    used: set[int] = set()
    for k in range(n):
        target = int(round((k + phase) * (len(hits) - 1) / max(1, n))) % len(hits)
        chosen = None
        for delta in range(len(hits)):
            for j in (target + delta, target - delta):
                if j < 0 or j >= len(hits):
                    continue
                t0, face = hits[j]
                if t0 in used:
                    continue
                chosen = (float(t0), square_from_face(face, src_w, src_h))
                used.add(t0)
                break
            if chosen:
                break
        if chosen is None:
            t0, face = hits[target]
            chosen = (float(t0), square_from_face(face, src_w, src_h))
        picked.append(chosen)
    return picked


def probe_wh(path: Path) -> tuple[int, int]:
    out = subprocess.check_output(
        [
            find_ffprobe(), "-v", "error", "-select_streams", "v:0",
            "-show_entries", "stream=width,height", "-of", "csv=p=0", str(path),
        ],
        text=True,
    ).strip()
    w, h = out.split(",")
    return int(w), int(h)


def probe_duration(path: Path) -> float:
    out = subprocess.check_output(
        [
            find_ffprobe(), "-v", "error", "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1", str(path),
        ],
        text=True,
    ).strip()
    return float(out)


def scan_galactic(video: Path) -> list[dict]:
    cache = WORK / "galactic-faces.json"
    if cache.is_file():
        data = json.loads(cache.read_text())
        if data.get("video") == str(video) and data.get("rows"):
            return data["rows"]
    thumbs = WORK / "galactic_thumbs"
    thumbs.mkdir(parents=True, exist_ok=True)
    if not any(thumbs.glob("*.jpg")):
        print("Scanning Galactic Code for faces…")
        subprocess.run(
            [
                find_ffmpeg(), "-nostdin", "-y", "-i", str(video),
                "-vf", f"fps={SCAN_FPS}", str(thumbs / "f%04d.jpg"),
            ],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    rows = detect_faces_dir(thumbs)
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps({"video": str(video), "rows": rows}))
    return rows


def square_from_face(face: dict, src_w: int, src_h: int) -> tuple[int, int, int]:
    cx = float(face["x"]) + float(face["w"]) / 2.0
    cy = float(face["y"]) + float(face["h"]) * 0.55
    side = max(float(face["w"]), float(face["h"])) * 2.7
    side = max(side, min(src_w, src_h) * 0.42)
    side = min(side, min(src_w, src_h))
    x = int(round(cx - side / 2.0))
    y = int(round(cy - side / 2.0))
    side = int(side) // 2 * 2
    side = max(64, min(side, min(src_w, src_h) // 2 * 2))
    x = max(0, min(src_w - side, int(x) // 2 * 2))
    y = max(0, min(src_h - side, int(y) // 2 * 2))
    return x, y, side


def wrap_lines(text: str) -> list[str]:
    text = text.strip()
    if len(text) <= 12:
        return [text]
    words = text.split()
    lines: list[str] = []
    cur = ""
    for w in words:
        trial = (cur + " " + w).strip()
        if len(trial) > 14 and cur:
            lines.append(cur)
            cur = w
        else:
            cur = trial
    if cur:
        lines.append(cur)
    return lines[:3]


def font_size_for(lines: list[str]) -> int:
    longest = max(len(s) for s in lines)
    if longest <= 5:
        return 78
    if longest <= 9:
        return 58
    if longest <= 14:
        return 42
    return 32


def outline_draw(draw: ImageDraw.ImageDraw, xy, text, font, fill, width: int = 3):
    x, y = xy
    a = fill[3] if len(fill) == 4 else 255
    ol = (0, 0, 0, a)
    for dx in range(-width, width + 1):
        for dy in range(-width, width + 1):
            if dx == 0 and dy == 0:
                continue
            if dx * dx + dy * dy > width * width:
                continue
            draw.text((x + dx, y + dy), text, font=font, fill=ol)
    draw.text((x, y), text, font=font, fill=fill)


def hsv(h: float, s: float = 0.85, v: float = 1.0, a: int = 255) -> tuple[int, int, int, int]:
    r, g, b = colorsys.hsv_to_rgb(h % 1.0, s, v)
    return int(r * 255), int(g * 255), int(b * 255), a


def fade(t: float, seconds: float) -> float:
    if t < 0.2:
        return t / 0.2
    if t > seconds - 0.35:
        return max(0.0, (seconds - t) / 0.35)
    return 1.0


def layout_glyphs(lines: list[str], font: ImageFont.FreeTypeFont) -> list[dict]:
    """Each glyph: {ch, line, i, x, y, line_w} in a SIZE canvas, centered block."""
    dummy = ImageDraw.Draw(Image.new("RGBA", (SIZE, SIZE)))
    line_sizes = []
    for line in lines:
        bbox = dummy.textbbox((0, 0), line, font=font)
        line_sizes.append((bbox[2] - bbox[0], bbox[3] - bbox[1], -bbox[0], -bbox[1]))
    gap = 6
    total_h = sum(h for _, h, _, _ in line_sizes) + gap * (len(lines) - 1)
    y0 = (SIZE - total_h) // 2 - 8
    glyphs: list[dict] = []
    gi = 0
    y = y0
    for li, line in enumerate(lines):
        lw, lh, ox, oy = line_sizes[li]
        x0 = (SIZE - lw) // 2
        x = x0
        for ch in line:
            cb = dummy.textbbox((0, 0), ch, font=font)
            cw = cb[2] - cb[0]
            glyphs.append(
                {
                    "ch": ch,
                    "line": li,
                    "i": gi,
                    "x": x - cb[0],
                    "y": y - cb[1],
                    "cw": cw,
                }
            )
            x += cw
            gi += 1
        y += lh + gap
    return glyphs


def text_layer(text: str, font_path: Path, t: float, seconds: float, style: int) -> Image.Image:
    layer = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    lines = wrap_lines(text)
    display = [ln.upper() if style in {0, 6, 7, 9} else ln for ln in lines]
    if style in {0, 3, 6, 7, 9}:
        display = [ln.upper() for ln in lines]
    font = load_font(font_path, font_size_for(display))
    glyphs = layout_glyphs(display, font)
    n = max(1, len(glyphs))
    a_fade = fade(t, seconds)
    kind = style % 10
    draw_img = layer
    d = ImageDraw.Draw(draw_img)

    def alpha(v: float) -> int:
        return max(0, min(255, int(255 * v * a_fade)))

    if kind == 0:  # impact bounce
        scale = 1.0 + 0.1 * math.sin(t * 2.1 * math.pi * 2)
        tmp = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
        td = ImageDraw.Draw(tmp)
        for g in glyphs:
            outline_draw(td, (g["x"], g["y"]), g["ch"], font, (255, 255, 255, alpha(1)))
        if abs(scale - 1) > 0.01:
            nw = max(1, int(SIZE * scale))
            tmp = tmp.resize((nw, nw), Image.Resampling.LANCZOS)
            out = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
            out.paste(tmp, ((SIZE - nw) // 2, (SIZE - nw) // 2))
            return out
        return tmp

    if kind == 1:  # typewriter
        shown = int(min(n, math.floor((t / max(0.15, seconds * 0.55)) * n) + 1))
        for g in glyphs[:shown]:
            if g["ch"] == " ":
                continue
            outline_draw(d, (g["x"], g["y"]), g["ch"], font, (255, 255, 255, alpha(1)))
        return layer

    if kind == 2:  # rainbow stagger
        for g in glyphs:
            delay = g["i"] * 0.09
            local = min(1.0, max(0.0, (t - delay) / 0.25))
            if local <= 0 or g["ch"] == " ":
                continue
            col = hsv((g["i"] * 0.12 + t * 0.15) % 1.0, 0.9, 1.0, alpha(local))
            outline_draw(d, (g["x"], g["y"]), g["ch"], font, col)
        return layer

    if kind == 3:  # drop in
        for g in glyphs:
            delay = g["i"] * 0.07
            u = min(1.0, max(0.0, (t - delay) / 0.28))
            if u <= 0 or g["ch"] == " ":
                continue
            dy = int((1 - u) ** 2 * -70)
            outline_draw(d, (g["x"], g["y"] + dy), g["ch"], font, (255, 255, 255, alpha(u)))
        return layer

    if kind == 4:  # neon pulse
        hue = (t * 0.35) % 1.0
        col = hsv(hue, 0.7, 1.0, alpha(1))
        glow = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
        gd = ImageDraw.Draw(glow)
        for g in glyphs:
            if g["ch"] == " ":
                continue
            outline_draw(gd, (g["x"], g["y"]), g["ch"], font, col, width=1)
        glow = glow.filter(ImageFilter.GaussianBlur(4))
        layer = Image.alpha_composite(layer, glow)
        d = ImageDraw.Draw(layer)
        pulse = 0.75 + 0.25 * math.sin(t * 6)
        col2 = hsv(hue, 0.4, 1.0, alpha(pulse))
        for g in glyphs:
            if g["ch"] == " ":
                continue
            outline_draw(d, (g["x"], g["y"]), g["ch"], font, col2)
        return layer

    if kind == 5:  # karaoke words
        words: list[list[dict]] = []
        cur: list[dict] = []
        for g in glyphs:
            if g["ch"] == " " and cur:
                words.append(cur)
                cur = []
            elif g["ch"] != " ":
                cur.append(g)
        if cur:
            words.append(cur)
        wn = max(1, len(words))
        active = min(wn - 1, int(t / max(0.2, seconds * 0.7) * wn))
        for wi, word in enumerate(words):
            on = wi <= active
            u = 1.0 if on else 0.0
            if wi == active:
                u = 1.0
            col = (255, 230, 80, alpha(1)) if wi == active else (255, 255, 255, alpha(0.55 if on else 0.0))
            if not on and wi != active:
                continue
            for g in word:
                outline_draw(d, (g["x"], g["y"]), g["ch"], font, col)
        return layer

    if kind == 6:  # shake
        jx = int(4 * math.sin(t * 55))
        jy = int(3 * math.cos(t * 47))
        for g in glyphs:
            if g["ch"] == " ":
                continue
            outline_draw(d, (g["x"] + jx, g["y"] + jy), g["ch"], font, (255, 255, 255, alpha(1)))
        return layer

    if kind == 7:  # glitch chroma
        scale = 1.08 if t < 0.35 else 1.0 + 0.04 * math.sin(t * 8)
        off = 3 if t < 0.5 or (int(t * 12) % 7 == 0) else 2
        tmp = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
        for channel, dx in (( (255, 40, 40, alpha(0.85)), -off), ( (40, 220, 255, alpha(0.85)), off)):
            td = ImageDraw.Draw(tmp)
            for g in glyphs:
                if g["ch"] == " ":
                    continue
                td.text((g["x"] + dx, g["y"]), g["ch"], font=font, fill=channel)
        td = ImageDraw.Draw(tmp)
        for g in glyphs:
            if g["ch"] == " ":
                continue
            outline_draw(td, (g["x"], g["y"]), g["ch"], font, (255, 255, 255, alpha(1)))
        if abs(scale - 1) > 0.01:
            nw = max(1, int(SIZE * scale))
            tmp = tmp.resize((nw, nw), Image.Resampling.LANCZOS)
            out = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
            out.paste(tmp, ((SIZE - nw) // 2, (SIZE - nw) // 2))
            return out
        return tmp

    if kind == 8:  # wave
        for g in glyphs:
            if g["ch"] == " ":
                continue
            dy = int(10 * math.sin(t * 8 + g["i"] * 0.55))
            col = hsv((0.75 + g["i"] * 0.08 + t * 0.2) % 1.0, 0.55, 1.0, alpha(1))
            outline_draw(d, (g["x"], g["y"] + dy), g["ch"], font, col)
        return layer

    # stamp
    if t < 0.08:
        flash = Image.new("RGBA", (SIZE, SIZE), (255, 255, 255, alpha(1)))
        return flash
    rot = 0 if t > 0.25 else (1 - t / 0.25) * -12
    tmp = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    td = ImageDraw.Draw(tmp)
    col = (255, 50, 50, alpha(1)) if "diss" in text.lower() or "poor" in text.lower() else (40, 220, 90, alpha(1))
    if kind == 9 and "approves" in text.lower() and "diss" not in text.lower():
        col = (40, 220, 90, alpha(1))
    for g in glyphs:
        if g["ch"] == " ":
            continue
        outline_draw(td, (g["x"], g["y"]), g["ch"], font, col, width=4)
    if rot:
        tmp = tmp.rotate(rot, resample=Image.Resampling.BICUBIC, expand=False)
    return tmp


def bulge_rgba(im: Image.Image, amount: float) -> Image.Image:
    try:
        import numpy as np
    except ImportError:
        extra = 1.0 + amount
        nw = max(1, int(SIZE * extra))
        scaled = im.resize((nw, nw), Image.Resampling.LANCZOS)
        out = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
        out.paste(scaled, ((SIZE - nw) // 2, (SIZE - nw) // 2), scaled)
        return out
    a = np.array(im)
    h, w = a.shape[:2]
    ys, xs = np.indices((h, w))
    cx, cy = (w - 1) / 2.0, (h - 1) / 2.0
    dx, dy = xs - cx, ys - cy
    r = np.sqrt(dx * dx + dy * dy)
    maxr = math.hypot(cx, cy) or 1.0
    rn = np.clip(r / maxr, 0, 1)
    factor = 1.0 + amount * (1.0 - rn * rn)
    sx = np.clip((cx + dx / factor).astype(np.int32), 0, w - 1)
    sy = np.clip((cy + dy / factor).astype(np.int32), 0, h - 1)
    return Image.fromarray(a[sy, sx])


def slice_glitch_rgba(im: Image.Image, t: float) -> Image.Image:
    out = im.copy()
    rng = random.Random(int(t * 24) + 7)
    for _ in range(5):
        y = rng.randint(30, SIZE - 40)
        hh = rng.randint(3, 16)
        xoff = rng.randint(-28, 28)
        band = out.crop((0, y, SIZE, y + hh))
        clear = Image.new("RGBA", (SIZE, hh), (0, 0, 0, 0))
        out.paste(clear, (0, y))
        out.paste(band, (xoff, y), band)
    return out


def end_transition_rgb(frame: Image.Image, t: float, seconds: float, kind: str | None) -> Image.Image:
    if not kind:
        return frame
    window = 0.45
    if t < seconds - window:
        return frame
    u = min(1.0, max(0.0, (t - (seconds - window)) / window))
    rgb = frame.convert("RGB")
    if kind == "fade":
        black = Image.new("RGB", (SIZE, SIZE), (0, 0, 0))
        return Image.blend(rgb, black, u)
    if kind == "zoomout":
        s = max(0.08, 1.0 - 0.92 * u)
        nw = max(1, int(SIZE * s))
        small = rgb.resize((nw, nw), Image.Resampling.LANCZOS)
        canvas = Image.new("RGB", (SIZE, SIZE), (0, 0, 0))
        canvas.paste(small, ((SIZE - nw) // 2, (SIZE - nw) // 2))
        return canvas
    canvas = Image.new("RGB", (SIZE, SIZE), (0, 0, 0))
    canvas.paste(rgb, (0, int(-SIZE * u)))
    return canvas


def roll_rare(seed: str) -> dict:
    rng = random.Random(seed)
    return {
        "bulge": rng.random() < 0.10,
        "glitch": rng.random() < 0.10,
        "end": rng.choice(["fade", "zoomout", "slide"]) if rng.random() < 0.10 else None,
        "bulge_amt": 0.20 + rng.random() * 0.20,
    }


def chrome(frame: Image.Image, url: str, logo: Path | None, url_font_path: Path) -> Image.Image:
    rgba = frame.convert("RGBA")
    draw = ImageDraw.Draw(rgba)
    font = load_font(url_font_path if url_font_path.is_file() else pick_font(), 16)
    bbox = draw.textbbox((0, 0), url, font=font)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    x = SIZE - tw - 12
    y = SIZE - th - 12
    pad = 6
    draw.rounded_rectangle(
        (x - pad, y - pad, x + tw + pad, y + th + pad),
        radius=6,
        fill=(0, 0, 0, 140),
    )
    draw.text((x, y), url, font=font, fill=(255, 255, 255, 245))
    if logo and logo.is_file():
        mark = Image.open(logo).convert("RGBA")
        mark.thumbnail((52, 52), Image.Resampling.LANCZOS)
        rgba.paste(mark, (10, 10), mark)
    return rgba.convert("RGB")


def extract_face_clip(
    video: Path,
    start: float,
    seconds: float,
    crop: tuple[int, int, int],
) -> list[Image.Image]:
    x, y, side = crop
    ffmpeg = find_ffmpeg()
    cmd = [
        ffmpeg, "-nostdin", "-ss", f"{start:.3f}", "-t", f"{seconds:.3f}",
        "-i", str(video),
        "-an",
        "-vf", f"crop={side}:{side}:{x}:{y},scale={SIZE}:{SIZE},fps={FPS}",
        "-f", "rawvideo", "-pix_fmt", "rgb24", "pipe:1",
    ]
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    assert proc.stdout is not None
    frame_n = SIZE * SIZE * 3
    frames: list[Image.Image] = []
    while True:
        buf = proc.stdout.read(frame_n)
        if not buf or len(buf) < frame_n:
            break
        frames.append(Image.frombytes("RGB", (SIZE, SIZE), buf))
    proc.wait()
    if not frames:
        err = proc.stderr.read().decode("utf-8", "replace") if proc.stderr else ""
        sys.exit(f"No frames from {video.name} @{start:.1f}s:\n{err[-1500:]}")
    return frames


def still_face_crop(image: Path) -> Image.Image | None:
    tmp = WORK / "still_face"
    tmp.mkdir(parents=True, exist_ok=True)
    dest = tmp / "one.jpg"
    Image.open(image).convert("RGB").save(dest, quality=92)
    rows = detect_faces_dir(tmp)
    if not rows:
        return None
    face = largest_face(rows[0])
    if not face:
        return None
    im = Image.open(image).convert("RGB")
    x, y, side = square_from_face(face, im.size[0], im.size[1])
    return im.crop((x, y, x + side, y + side)).resize((SIZE, SIZE), Image.Resampling.LANCZOS)


def encode_overlay(
    frames: list[Image.Image],
    text: str,
    url: str,
    seconds: float,
    dest: Path,
    style: int,
    logo: Path | None,
    rare: dict | None = None,
) -> None:
    font_path = pick_font()
    url_font = URL_FONT if URL_FONT.is_file() else font_path
    ffmpeg = find_ffmpeg()
    dest.parent.mkdir(parents=True, exist_ok=True)
    rare = rare or {}
    cmd = [
        ffmpeg, "-nostdin", "-y",
        "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{SIZE}x{SIZE}",
        "-r", str(FPS), "-i", "-",
        "-an", *encoder_args(ffmpeg), "-pix_fmt", "yuv420p",
        "-movflags", "+faststart", "-t", f"{seconds:.2f}", str(dest),
    ]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=subprocess.PIPE)
    assert proc.stdin is not None
    n = min(len(frames), int(round(seconds * FPS)))
    try:
        for i in range(n):
            t = i / FPS
            overlay = text_layer(text, font_path, t, seconds, style)
            if rare.get("bulge"):
                pulse = 0.65 + 0.35 * math.sin(t * 5.5)
                overlay = bulge_rgba(overlay, float(rare.get("bulge_amt") or 0.28) * pulse)
            if rare.get("glitch"):
                overlay = slice_glitch_rgba(overlay, t)
            composed = Image.alpha_composite(frames[i].convert("RGBA"), overlay)
            out = chrome(composed, url, logo, url_font)
            out = end_transition_rgb(out, t, seconds, rare.get("end"))
            proc.stdin.write(out.tobytes())
        proc.stdin.close()
        err = proc.stderr.read().decode("utf-8", "replace") if proc.stderr else ""
        code = proc.wait()
    except BrokenPipeError:
        err = proc.stderr.read().decode("utf-8", "replace") if proc.stderr else ""
        code = proc.wait()
    if code != 0:
        sys.exit(f"ffmpeg failed for {dest.name}:\n{err[-2000:]}")


def unique_dest(folder: Path, text: str, url: str) -> Path:
    """Never overwrite. slug-url-gudasol-timestamp.mp4"""
    folder.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    dest = folder / f"{slug(text)}-{url}-gudasol-{ts}.mp4"
    n = 0
    while dest.exists():
        n += 1
        dest = folder / f"{slug(text)}-{url}-gudasol-{ts}-{n}.mp4"
    return dest


def sort_existing() -> None:
    """Move already-made mp4s into category folders. Never delete. Skip unknowns."""
    for name in CATEGORIES:
        (OUT_DIR / name).mkdir(parents=True, exist_ok=True)
    moved = 0
    left = 0
    for path in list(OUT_DIR.rglob("*.mp4")):
        if ".work" in path.parts:
            continue
        phrase = phrase_from_filename(path.name)
        cat = pick_category(phrase)
        if cat is None:
            left += 1
            continue
        dest_dir = OUT_DIR / cat
        dest = dest_dir / path.name
        if path.resolve() == dest.resolve():
            continue
        if dest.exists():
            dest = dest_dir / f"{path.stem}-gudasol-{datetime.now().strftime('%Y%m%d-%H%M%S')}{path.suffix}"
        dest_dir.mkdir(parents=True, exist_ok=True)
        shutil.move(str(path), str(dest))
        print(f"move {path.relative_to(OUT_DIR)} → {dest.relative_to(OUT_DIR)}")
        moved += 1
    print(f"Sorted {moved} files; {left} left uncategorized")


def render_batch(phrases: list[str], dest_dir: Path | None, video: Path, phase: float = 0.0) -> None:
    if not video.is_file():
        sys.exit(f"Missing source video: {video}")
    seconds = [duration_for(p, i) for i, p in enumerate(phrases)]
    src_w, src_h = probe_wh(video)
    rows = scan_galactic(video)
    windows = face_windows(rows, src_w, src_h, len(phrases), seconds, phase=phase)
    for i, phrase in enumerate(phrases):
        url = pick_url(phrase)
        cat = pick_category(phrase)
        folder = dest_dir if dest_dir is not None else (OUT_DIR / cat if cat else OUT_DIR)
        folder.mkdir(parents=True, exist_ok=True)
        start, crop = windows[i]
        dest = unique_dest(folder, phrase, url)
        style = i % 10
        rare = roll_rare(f"{phrase}|{start:.3f}|{i}")
        extra = []
        if rare["bulge"]:
            extra.append("bulge")
        if rare["glitch"]:
            extra.append("glitch")
        if rare["end"]:
            extra.append(f"end:{rare['end']}")
        extras = (" +" + ",".join(extra)) if extra else ""
        print(
            f"[{i + 1}/{len(phrases)}] {phrase!r}  {url}  {folder.name}  "
            f"t={start:.0f}s  style={STYLE_NAMES[style]}{extras}  → {dest.name}"
        )
        frames = extract_face_clip(video, start, seconds[i], crop)
        encode_overlay(frames, phrase, url, seconds[i], dest, style, LOGOS.get(url), rare)
    print(f"Wrote {len(phrases)} files")


def main() -> None:
    find_ffmpeg()
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--preset", choices=["more-20", "cult-10", "gm"])
    p.add_argument("--video", type=Path, default=GALACTIC)
    p.add_argument("--sort", action="store_true", help="Move existing GIFs into category folders")
    args = p.parse_args()

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    video = args.video if args.video.is_file() else GALACTIC

    if args.sort or args.preset:
        sort_existing()
    if args.preset == "more-20":
        render_batch(MORE_20, None, video)
        return
    if args.preset == "cult-10":
        render_batch(CULT_10, None, video, phase=0.5)
        return
    if args.preset == "gm":
        render_batch(GM_MORE, None, video, phase=0.33)
        return
    if args.sort:
        return
    p.error("Need --sort and/or --preset gm|more-20|cult-10")


if __name__ == "__main__":
    main()
