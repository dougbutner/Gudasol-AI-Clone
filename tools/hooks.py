"""Opening hook for a talking short.

Bebas Neue, big and stacked tight, with a short Reels-style pop then a hold.
A viral clip fills the frame, muted. Its text fades out from 1.5s over 0.5s.
The clip file is deleted after the short that uses it is finished.
"""

from __future__ import annotations

import math
import re
import subprocess
import urllib.request
from pathlib import Path
from random import Random

from PIL import Image, ImageDraw, ImageFont

W, H = 1080, 1920
HOLD = 2.0
FADE_AT = 1.5
FADE_FOR = 0.5
KINDS = ("cloud", "ask", "viral")
STYLES = ("stroke", "pill", "invert", "marker", "neon", "shadow")
SHAPES = ("pyramid", "diamond", "stack", "stagger", "bow", "cross")
SKIP = re.compile(
    r"\b(baby|babies|child|children|kid|kids|infant|vomit|injury|blood)\b",
    re.I,
)
_STOP = {
    "a", "an", "the", "and", "or", "but", "so", "to", "of", "in", "on", "for",
    "with", "as", "at", "from", "by", "into", "that", "this", "these", "those",
    "is", "are", "was", "were", "be", "it", "its", "it's", "we", "you", "i",
    "they", "have", "has", "had", "just", "also", "then", "than", "about",
    "not", "your", "our", "their", "my", "if", "when", "what", "why", "how",
    "where", "who", "which", "can", "do", "would", "let's", "lets", "let",
    "talk", "some", "there", "here", "really", "common", "everyday", "first", "off", "like",
}
_OPEN = {"what", "why", "how", "where", "who", "when", "can", "do", "which", "would"}
_ASK = (
    ("WHAT", "IS", "{term}?"),
    ("IMAGINE", "{term}"),
    ("FEEL", "{term}?"),
    ("CHOOSE", "{term}", "OR", "{other}"),
    ("TEACH", "{term}", "BACK"),
    ("WHERE", "DOES", "{term}", "LIVE?"),
)


def pools() -> list[tuple[str, str]]:
    return [("kind:" + name, "active") for name in KINDS] + [
        ("style:" + name, "active") for name in STYLES
    ]


def bebas(size: int) -> ImageFont.FreeTypeFont:
    for folder in (
        Path(__file__).resolve().parent / "fonts",
        Path.home() / "Library/Fonts",
        Path("/Library/Fonts"),
    ):
        for name in ("BebasNeue Bold.otf", "BebasNeue-Bold.otf", "BebasNeue Regular.otf"):
            path = folder / name
            if path.is_file():
                return ImageFont.truetype(str(path), size=size)
    raise FileNotFoundError("Bebas Neue")


def _sticker(word: str, size: int, style: str) -> Image.Image:
    face = bebas(size)
    stroke = 12 if style in ("stroke", "neon") else (3 if style == "shadow" else 0)
    box = ImageDraw.Draw(Image.new("RGBA", (4, 4))).textbbox((0, 0), word, font=face, stroke_width=stroke)
    pad = 14 if style in ("pill", "invert", "marker") else 6
    img = Image.new(
        "RGBA",
        (box[2] - box[0] + pad * 2 + stroke * 2, box[3] - box[1] + pad * 2 + stroke * 2),
        (0, 0, 0, 0),
    )
    draw = ImageDraw.Draw(img)
    x, y = pad + stroke - box[0], pad + stroke - box[1]
    if style == "pill":
        draw.rounded_rectangle(
            [1, 1, img.width - 2, img.height - 2], radius=14,
            fill=(255, 255, 255, 255), outline=(0, 0, 0, 255), width=5,
        )
        draw.text((x, y), word, font=face, fill=(0, 0, 0, 255))
    elif style == "invert":
        draw.rounded_rectangle([0, 0, img.width - 1, img.height - 1], radius=14, fill=(12, 12, 12, 242))
        draw.text((x, y), word, font=face, fill=(255, 255, 255, 255))
    elif style == "marker":
        draw.rounded_rectangle([0, 0, img.width - 1, img.height - 1], radius=8, fill=(255, 226, 0, 255))
        draw.text((x, y), word, font=face, fill=(0, 0, 0, 255))
    elif style == "neon":
        draw.text((x, y), word, font=face, fill=(255, 255, 255, 255), stroke_width=16, stroke_fill=(0, 0, 0, 255))
        draw.text((x, y), word, font=face, fill=(255, 255, 255, 255), stroke_width=6, stroke_fill=(90, 220, 255, 255))
    elif style == "shadow":
        draw.text((x + 6, y + 6), word, font=face, fill=(0, 0, 0, 230))
        draw.text((x, y), word, font=face, fill=(255, 255, 255, 255), stroke_width=stroke, stroke_fill=(0, 0, 0, 255))
    else:
        draw.text((x, y), word, font=face, fill=(255, 255, 255, 255), stroke_width=stroke, stroke_fill=(0, 0, 0, 255))
    ink = img.getbbox()
    if ink:
        img = img.crop(ink)
    return img


def _stack(words: list[str], style: str, shape: str, emphasis: int) -> list[tuple[Image.Image, int, int]]:
    """Big lines, nearly touching, centered. Shape only nudges a line sideways."""
    words = [w for w in words if w][:4] or ["THIS"]
    emphasis = min(max(0, emphasis), len(words) - 1)
    if style not in STYLES:
        style = "stroke"
    body, lead = 164, 214
    made = [_sticker(word, lead if i == emphasis else body, style) for i, word in enumerate(words)]
    widest = max(im.width for im in made)
    tall = sum(im.height for im in made) + 8 * (len(made) - 1)
    fit = min(1.0, (W * 0.90) / widest, (H * 0.58) / max(tall, 1))
    if fit < 0.999:
        made = [
            im.resize((max(1, int(im.width * fit)), max(1, int(im.height * fit))), Image.Resampling.LANCZOS)
            for im in made
        ]
    gap = 2
    block = sum(im.height for im in made) + gap * (len(made) - 1)
    y = max(200, min(int(H * 0.46 - block / 2), H - 360 - block))
    placed = []
    for i, im in enumerate(made):
        nudge = 0
        if shape == "stagger":
            nudge = -22 if i % 2 == 0 else 22
        elif shape == "bow":
            nudge = int(18 * math.sin(math.pi * (0.5 if len(made) == 1 else i / (len(made) - 1))))
        elif shape == "pyramid" and i == 0:
            nudge = 0
        cx = W // 2 + nudge
        cx = max(im.width // 2 + 36, min(W - im.width // 2 - 36, cx))
        placed.append((im, cx, y + im.height // 2))
        y += im.height + gap
    return placed


def paint(words: list[str], style: str, shape: str, emphasis: int, work: Path, viral: bool = False) -> Path:
    """Animated overlay. Words pop in and stay. A viral hook fades them from 1.5s over 0.5s."""
    placed = _stack(words, style, shape, emphasis)
    fps = 24
    span = HOLD if viral else HOLD + FADE_FOR
    frames = max(1, int(round(span * fps)))
    folder = work / "hook-frames"
    folder.mkdir(parents=True, exist_ok=True)
    for index in range(frames):
        t = index / fps
        frame = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        for i, (im, cx, cy) in enumerate(placed):
            u = (t - i * 0.08) / 0.36
            if u <= 0:
                continue
            u = 1 - (1 - min(1.0, u)) ** 3
            alpha = u
            if t >= (FADE_AT if viral else HOLD):
                alpha *= max(0.0, 1 - (t - (FADE_AT if viral else HOLD)) / FADE_FOR)
            if alpha <= 0.01:
                continue
            scale = 0.94 + 0.06 * u
            sw, sh = max(1, int(im.width * scale)), max(1, int(im.height * scale))
            sprite = im.resize((sw, sh), Image.Resampling.LANCZOS)
            if alpha < 0.999:
                band = sprite.getchannel("A").point([min(255, int(i * alpha)) for i in range(256)])
                sprite.putalpha(band)
            frame.alpha_composite(sprite, (cx - sw // 2, cy - sh // 2 + int((1 - u) * 12)))
        frame.save(folder / f"{index:04d}.png")
    mov = work / "hook.mov"
    subprocess.run(
        [
            "ffmpeg", "-y", "-framerate", str(fps), "-i", str(folder / "%04d.png"),
            "-c:v", "qtrle", "-pix_fmt", "argb", str(mov),
        ],
        check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
    )
    return mov


def phrase(subject: str, kind: str, rng: Random) -> tuple[list[str], int]:
    """Short hook copy. Ask-lines are a question or a choice. Cloud uses his words."""
    text = subject or ""
    raw = re.findall(r"[A-Za-z0-9']+", text)
    kept: list[str] = []
    freq: dict[str, int] = {}
    for word in raw:
        if word.lower() in _STOP:
            continue
        up = word.upper()
        freq[up] = freq.get(up, 0) + 1
        if up not in kept:
            kept.append(up)
    term = max(kept, key=lambda w: (freq[w], -kept.index(w))) if kept else "THIS"
    other = next((w for w in kept if w != term), "IT")
    if kind == "viral":
        return ["THIS", "IS", term], 2
    if kind == "cloud":
        words = [term] + [w for w in kept if w != term]
        return words[:4] or [term], 0
    first = re.split(r"[.?!]", text, maxsplit=1)[0]
    sent = re.findall(r"[A-Za-z0-9']+", first)
    if sent and sent[0].lower() in _OPEN and "?" in text[: len(first) + 1]:
        spoken: list[str] = []
        for word in sent:
            if word.upper() not in spoken:
                spoken.append(word.upper())
            if len(spoken) == 4:
                break
        if spoken and not spoken[-1].endswith("?"):
            spoken[-1] += "?"
        spot = next((i for i, word in enumerate(spoken) if term in word), len(spoken) - 1)
        return spoken or ["WHAT", "IS", term + "?"], spot
    pattern = _ASK[rng.randrange(len(_ASK))]
    words = [part.format(term=term, other=other) for part in pattern]
    return words, next(i for i, word in enumerate(words) if term in word)


def blocked(title: str, slug: str) -> bool:
    return bool(SKIP.search(f"{title} {slug}"))


def _get(url: str, timeout: int = 25) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=timeout) as response:
        return response.read().decode("utf-8", "replace")


def catalog() -> tuple[list[dict[str, str]], list[str]]:
    """Live clip list. Notes explain sources that did not yield a file."""
    groups: list[list[dict[str, str]]] = []
    notes: list[str] = []
    try:
        page = _get("https://viralhookmaster.com/")
        titled = {
            slug: title.strip()
            for slug, title in re.findall(r'data-slug="([^"]+)"[\s\S]{0,900}?<h3[^>]*>([^<]+)</h3>', page)
        }
        found = []
        seen: set[str] = set()
        for slug in re.findall(r'data-slug="([^"]+)"', page):
            if slug in seen:
                continue
            seen.add(slug)
            title = titled.get(slug) or slug.replace("-", " ")
            if blocked(title, slug):
                continue
            found.append({
                "source": "viralhookmaster",
                "slug": "vhm-" + slug,
                "title": title,
                "url": f"https://viralhookmaster.com/hooks/{slug}.mp4",
            })
        groups.append(found)
        notes.append(f"viralhookmaster: {len(found)} clips")
    except Exception as exc:
        notes.append(f"viralhookmaster: {exc}")
        groups.append([])
    try:
        page = _get("https://www.gethighconvert.com/pages/viral-hooks")
        found = []
        for url in sorted(set(re.findall(r"https://cdn\.shopify\.com/[^\"']+\.mp4[^\"']*", page))):
            name = url.split("/")[-1].split("?")[0].replace(".mp4", "")
            if blocked(name, name):
                continue
            found.append({
                "source": "gethighconvert",
                "slug": "ghc-" + name.removeprefix("hc-hook-"),
                "title": name,
                "url": url,
            })
        groups.append(found)
        notes.append(f"gethighconvert: {len(found)} clips")
    except Exception as exc:
        notes.append(f"gethighconvert: {exc}")
        groups.append([])
    try:
        page = _get("https://aiseo.ai/tools/transitional-hooks")
        titles = []
        for title in re.findall(r"<h2[^>]*>([^<]+)</h2>", page):
            if title.startswith("How ") or title.startswith("What"):
                break
            titles.append(re.sub(r"&#x27;", "'", title).strip())
        found = []
        for i in range(231):
            title = titles[i] if i < len(titles) else f"aiseo {i}"
            if blocked(title, f"aiseo-{i}"):
                continue
            found.append({
                "source": "aiseo",
                "slug": f"aiseo-{i}",
                "title": title,
                "url": f"https://aiseo.ai/api/transitional-hooks/download?clip={i}",
            })
        groups.append(found)
        notes.append(f"aiseo: {len(found)} clips")
    except Exception as exc:
        notes.append(f"aiseo: {exc}")
        groups.append([])
    try:
        _get("https://www.goviralhooks.com/library", timeout=20)
        notes.append("goviralhooks: page answered but no mp4 urls")
    except Exception as exc:
        notes.append(f"goviralhooks: {exc}")
    try:
        page = _get("https://viralhooks.org/tools/video-editor/")
        if ".mp4" not in page:
            notes.append("viralhooks.org editor: no clip files on the page")
        else:
            notes.append("viralhooks.org editor: page mentions mp4 but none were direct files")
    except Exception as exc:
        notes.append(f"viralhooks.org: {exc}")
    rows: list[dict[str, str]] = []
    depth = max((len(group) for group in groups), default=0)
    for i in range(depth):
        for group in groups:
            if i < len(group):
                rows.append(group[i])
    return rows, notes


def save(url: str, dest: Path) -> bool:
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_suffix(".part")
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=90) as response, part.open("wb") as out:
            while True:
                chunk = response.read(1 << 20)
                if not chunk:
                    break
                out.write(chunk)
                if out.tell() > 40_000_000:
                    raise OSError("clip over 40MB")
        if b"ftyp" not in part.read_bytes()[:32]:
            part.unlink(missing_ok=True)
            return False
        part.replace(dest)
        return True
    except Exception:
        part.unlink(missing_ok=True)
        return False


def drop(path: Path | None) -> None:
    if path is not None and path.is_file():
        path.unlink()


def burn(picture: Path, dest: Path, mov: Path, clip: Path | None, work: Path) -> float:
    """Burn the hook onto the picture. A viral clip fills the frame and stays muted."""
    from make_shorts import probe_duration, video_encoder

    dest.parent.mkdir(parents=True, exist_ok=True)
    duration = probe_duration(picture)
    inputs = ["-i", str(picture)]
    use_clip = clip is not None and clip.is_file()
    if use_clip:
        inputs += ["-i", str(clip)]
    inputs += ["-i", str(mov)]
    if use_clip:
        filt = (
            f"[1:v]scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},setsar=1,"
            f"tpad=stop_mode=clone:stop_duration={HOLD:.3f},trim=duration={HOLD:.3f},setpts=PTS-STARTPTS[clip];"
            f"[2:v]format=rgba[hk];"
            f"[0:v][clip]overlay=0:0:enable='lt(t,{HOLD:.3f})'[mid];"
            f"[mid][hk]overlay=0:0:eof_action=pass[vout]"
        )
    else:
        filt = (
            "[1:v]format=rgba[hk];"
            "[0:v][hk]overlay=0:0:eof_action=pass[vout]"
        )
    try:
        subprocess.run(
            [
                "ffmpeg", "-y", *inputs,
                "-filter_complex", filt,
                "-map", "[vout]", "-map", "0:a?",
                *video_encoder(), "-pix_fmt", "yuv420p",
                "-c:a", "aac", "-b:a", "128k",
                "-t", f"{duration:.3f}",
                "-movflags", "+faststart", str(dest),
            ],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            cwd=str(work),
        )
    except subprocess.CalledProcessError as exc:
        err = exc.stderr.decode("utf-8", "replace")[-900:] if exc.stderr else str(exc)
        raise RuntimeError(err) from exc
    return HOLD
