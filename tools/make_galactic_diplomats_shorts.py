#!/usr/bin/env python3
"""20 captioned 9:16 shorts (2–3 min each) from The Amethyst Album."""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VIDEO = (
    ROOT
    / "Long Videos"
    / "Gudasol - The Amethyst Album - School for Galactic Diplomats.mp4"
)
OUT_DIR = ROOT / "Shorts" / "Galactic Diplomats"
FONT_DIR = ROOT / ".cursor" / "skills" / "telegram-gifs" / "fonts"
N = 20
MIN_S = 120.0
MAX_S = 178.0
W, H = 1080, 1920

THEMES = [
    "GRATITUDE",
    "GIVE IT UP TO LOVE",
    "OPEN HEART",
    "SURRENDER",
    "BLESS UP",
    "RECEIVE",
    "DEVOTION",
    "ONE LOVE",
    "THANK YOU",
    "OFFER IT UP",
    "PRESENCE",
    "BREATHE",
    "HOLY",
    "RISE",
    "AMETHYST",
    "LIGHT BODY",
    "PRAISE",
    "FREQUENCY",
    "LET GO",
    "GALACTIC LOVE",
]


def find_ffmpeg() -> str:
    candidates: list[str] = []
    cellar = Path("/usr/local/Cellar/ffmpeg")
    if cellar.is_dir():
        candidates.extend(sorted(str(p) for p in cellar.glob("*/bin/ffmpeg")))
    opt = Path("/usr/local/opt/ffmpeg/bin/ffmpeg")
    if opt.is_file():
        candidates.append(str(opt))
    which = shutil.which("ffmpeg")
    if which:
        candidates.append(which)
    for c in candidates:
        if not Path(c).is_file():
            continue
        filters = subprocess.run([c, "-hide_banner", "-filters"], capture_output=True, text=True).stdout
        enc = subprocess.run([c, "-hide_banner", "-encoders"], capture_output=True, text=True).stdout
        if "subtitles" in filters and ("h264_videotoolbox" in enc or "libx264" in enc):
            return c
    sys.exit("Need ffmpeg with subtitles (libass) and H.264")


FFMPEG = None
FFPROBE = None


def tools() -> tuple[str, str]:
    global FFMPEG, FFPROBE
    if not FFMPEG:
        FFMPEG = find_ffmpeg()
        FFPROBE = str(Path(FFMPEG).with_name("ffprobe"))
        if not Path(FFPROBE).is_file():
            FFPROBE = shutil.which("ffprobe") or FFPROBE
    return FFMPEG, FFPROBE


def probe_duration(path: Path) -> float:
    _, ffprobe = tools()
    out = subprocess.check_output(
        [
            ffprobe, "-v", "error", "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1", str(path),
        ],
        text=True,
    ).strip()
    return float(out)


def clip_windows(duration: float) -> list[tuple[float, float]]:
    if duration < MIN_S:
        sys.exit(f"Source is only {duration:.1f}s; need at least {MIN_S:.0f}s")
    usable = max(0.0, duration - MIN_S)
    windows: list[tuple[float, float]] = []
    for i in range(N):
        dur = MIN_S + (MAX_S - MIN_S) * ((i * 3) % 11) / 10.0
        dur = min(MAX_S, max(MIN_S, round(dur, 2)))
        start = 0.0 if N == 1 else i * usable / (N - 1)
        if start + dur > duration:
            start = max(0.0, duration - dur)
        dur = min(dur, duration - start)
        if dur < MIN_S - 0.05:
            start = max(0.0, duration - MIN_S)
            dur = min(MIN_S, duration - start)
        windows.append((round(start, 3), round(start + dur, 3)))
    return windows


def ass_time(t: float) -> str:
    t = max(0.0, t)
    h = int(t // 3600)
    m = int((t % 3600) // 60)
    s = t % 60
    return f"{h}:{m:02d}:{s:05.2f}"


def write_ass(text: str, duration: float, dest: Path) -> None:
    caption = " ".join(text.upper().split())
    caption = caption.replace("\\", "\\\\").replace("{", "(").replace("}", ")")
    dest.write_text(
        f"""[Script Info]
ScriptType: v4.00+
PlayResX: {W}
PlayResY: {H}
WrapStyle: 2
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Cap,Open Sans,72,&H00FFFFFF,&H000000FF,&H00000000,&HAA000000,0,0,0,0,100,100,0,0,1,4,2,2,80,80,240,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
Dialogue: 0,{ass_time(0.15)},{ass_time(duration - 0.08)},Cap,,0,0,0,,{caption}
""",
        encoding="utf-8",
    )


def slug(text: str) -> str:
    import re
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:40]


def render_clip(video: Path, start: float, end: float, theme: str, dest: Path, work: Path) -> None:
    duration = end - start
    dest.parent.mkdir(parents=True, exist_ok=True)
    work.mkdir(parents=True, exist_ok=True)
    ass = work / f"{dest.stem}.ass"
    write_ass(theme, duration, ass)
    fontsdir = str(FONT_DIR).replace("\\", "/").replace(":", "\\:")
    ass_esc = str(ass).replace("\\", "/").replace(":", "\\:")
    vf = (
        f"scale={W}:{H}:force_original_aspect_ratio=increase,"
        f"crop={W}:{H},setsar=1,"
        f"subtitles='{ass_esc}':fontsdir='{fontsdir}'"
    )
    ffmpeg, _ = tools()
    cmd = [
        ffmpeg, "-nostdin", "-y",
        "-ss", f"{start:.3f}", "-t", f"{duration:.3f}", "-i", str(video),
        "-vf", vf,
        "-map", "0:v:0", "-map", "0:a:0?",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "23", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "160k",
        "-movflags", "+faststart",
        str(dest),
    ]
    print(f"  {dest.name}  {start:.0f}–{end:.0f}s ({duration:.0f}s)  {theme!r}")
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        sys.exit(f"ffmpeg failed for {dest.name}:\n{proc.stderr[-2500:]}")


def main() -> int:
    if not VIDEO.is_file():
        print(f"missing {VIDEO}", file=sys.stderr)
        return 1
    if not (FONT_DIR / "OpenSans-Thin.ttf").is_file():
        print(f"missing Open Sans Thin in {FONT_DIR}", file=sys.stderr)
        return 1
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    duration = probe_duration(VIDEO)
    windows = clip_windows(duration)
    print(f"{VIDEO.name}  {duration/60:.1f} min → {len(windows)} shorts in {OUT_DIR.relative_to(ROOT)}")
    work = ROOT / "Shorts" / ".work" / "galactic-diplomats"
    for i, ((a, b), theme) in enumerate(zip(windows, THEMES), start=1):
        dest = OUT_DIR / f"galactic-diplomats-s{i:02d}-{slug(theme)}.mp4"
        if dest.is_file() and dest.stat().st_size > 1_000_000:
            print(f"  skip existing {dest.name}")
            continue
        render_clip(VIDEO, a, b, theme, dest, work)
        d = probe_duration(dest)
        if d < MIN_S - 0.5:
            dest.unlink(missing_ok=True)
            sys.exit(f"{dest.name} is only {d:.1f}s (need ≥ {MIN_S:.0f}s)")
        print(f"    wrote {dest.name} ({d:.1f}s)")
    print("\nDone.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
