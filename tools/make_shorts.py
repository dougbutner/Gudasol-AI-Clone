#!/usr/bin/env python3
"""Build 9:16 talking shorts from long videos. Local ffmpeg + Hugging Face Whisper."""

from __future__ import annotations

import json
import math
import re
import subprocess
import sys
import tempfile
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
FONT_PATHS = [
    (Path("/Users/fresh/Library/Fonts/BebasNeue Bold.otf"), 0),
    (Path("/System/Library/Fonts/Avenir Next Condensed.ttc"), 8),
    (Path("/System/Library/Fonts/Supplemental/Impact.ttf"), 0),
]

WHISPER_MODEL = "base.en"
PAUSE_GAP = 0.90
MIN_SHORT = 15.0
MIN_WORDS = 5
MAX_SHORT = 180.0

W, H = 1080, 1920
YELLOW = (255, 215, 0, 255)
BLACK = (0, 0, 0, 255)
WHITE = (255, 255, 255, 255)

CROP_CENTER = {
    "Gudasol in studio talking.mp4": 0.80,
}


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


def windows_from_words(words: list[dict], duration: float) -> list[tuple[float, float]]:
    """Pause-based cuts, merged up to 15s minimum and split at 3 minutes."""
    if not words:
        return []
    chunks: list[list[dict]] = [[words[0]]]
    for prev, cur in zip(words, words[1:]):
        gap = float(cur["start"]) - float(prev["end"])
        punct = str(prev["text"]).rstrip().endswith((".", "?", "!"))
        if gap >= PAUSE_GAP or (punct and gap >= 0.50):
            chunks.append([cur])
        else:
            chunks[-1].append(cur)

    raw: list[tuple[float, float]] = []
    for chunk in chunks:
        if len(chunk) < MIN_WORDS:
            continue
        a = max(0.0, float(chunk[0]["start"]) - 0.08)
        b = min(duration, float(chunk[-1]["end"]) + 0.12)
        if b > a:
            raw.append((a, b))
    if not raw:
        return []

    packed: list[tuple[float, float]] = []
    cur_a, cur_b = raw[0]
    for a, b in raw[1:]:
        if cur_b - cur_a < MIN_SHORT:
            cur_b = b
            continue
        packed.append((cur_a, cur_b))
        cur_a, cur_b = a, b
    if cur_b - cur_a >= MIN_SHORT:
        packed.append((cur_a, cur_b))
    elif packed and cur_b - packed[-1][0] <= MAX_SHORT:
        pa, _ = packed[-1]
        packed[-1] = (pa, cur_b)

    windows: list[tuple[float, float]] = []
    for a, b in packed:
        if MIN_SHORT <= (b - a) <= MAX_SHORT:
            windows.append((a, b))
            continue
        t = a
        while b - t > MAX_SHORT:
            windows.append((t, t + MAX_SHORT))
            t += MAX_SHORT
        if b - t >= MIN_SHORT:
            windows.append((t, b))
        elif windows and b - windows[-1][0] <= MAX_SHORT:
            pa, _ = windows[-1]
            windows[-1] = (pa, b)
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


def render_short(video: Path, start: float, end: float, cues: list[dict], crop_x: int, work: Path, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    src_w, src_h = probe_wh(video)
    scaled_w = int(src_w * H / src_h)
    if scaled_w % 2:
        scaled_w -= 1
    cx = int(crop_x * H / src_h)
    cx = max(0, min(max(0, scaled_w - W), cx))
    duration = end - start
    logo = work / "logo.png"
    prepare_logo(pick_logo(), logo)
    cap_mov = build_caption_mov(cues, start, duration, work)
    inputs = ["-ss", f"{start:.3f}", "-t", f"{duration:.3f}", "-i", str(video), "-i", str(logo)]
    filters = [
        f"[0:v]scale={scaled_w}:{H},crop={W}:{H}:{cx}:0[base]",
        "[base][1:v]overlay=W-w-36:36[logoed]",
    ]
    if cap_mov:
        inputs += ["-i", str(cap_mov)]
        filters.append("[2:v]format=rgba[cc]")
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
    run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)


def slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:60]


def default_videos() -> list[Path]:
    found = sorted(LONG_DIR.glob("*.mp4"))
    return found


def main() -> int:
    OUT_DIR.mkdir(exist_ok=True)
    names = sys.argv[1:]
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
        windows = windows_from_words(words, duration)
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
                section_cues = [c for c in cues if c["end"] > a and c["start"] < b]
                frame = work / f"face_{n:02d}.jpg"
                extract_frame(video, a + (b - a) * 0.35, frame)
                crop_w = src_h * 9 / 16
                if video.name in CROP_CENTER:
                    crop_x = int(src_w * CROP_CENTER[video.name] - crop_w / 2)
                    crop_x = max(0, min(int(src_w - crop_w), crop_x))
                else:
                    crop_x = subject_crop_x(frame, src_w, src_h) if frame.exists() else int((src_w - crop_w) / 2)
                out = OUT_DIR / f"{slug(video.stem)}-s{n:02d}.mp4"
                section_work = work / f"s{n:02d}"
                section_work.mkdir()
                print(f"  s{n:02d} {a:.1f}-{b:.1f}s ({b-a:.1f}s) crop_x={crop_x}")
                try:
                    render_short(video, a, b, section_cues, crop_x, section_work, out)
                except subprocess.CalledProcessError as e:
                    err = e.stderr.decode() if e.stderr else str(e)
                    print(f"  ffmpeg failed: {err[-900:]}", file=sys.stderr)
                    return 1
                made.append(out)
                print(f"    wrote {out.name}")
    print("\nDone:")
    for p in made:
        print(" ", p)
    return 0 if made else 1


if __name__ == "__main__":
    sys.exit(main())
