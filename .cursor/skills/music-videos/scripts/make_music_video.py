#!/usr/bin/env python3
"""Full-length local music videos: song audio + unused source clips + verified captions.

Optional font, caption_case, caption_look, and caption_place in Music Videos/config.json
come from render-styles.json. Leave them out and the captions stay as they are.
"""

from __future__ import annotations

import argparse
import json
import math
import random
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
if str(ROOT / "tools") not in sys.path:
    sys.path.insert(0, str(ROOT / "tools"))
import edges
from render_style import resolve

MV = ROOT / "Music Videos"
SRC_VIDEO = MV / "source videos"
SRC_AUDIO = MV / "source audio"
OUT_916 = MV / "9by19"  # 1080x1920
OUT_169 = MV / "16by9"  # 1920x1080
LYRICS = MV / "lyrics"
WORK = MV / ".work"
USED_PATH = MV / "used.json"
CONFIG_PATH = MV / "config.json"
FONT = ROOT / ".cursor" / "skills" / "telegram-gifs" / "fonts" / "OpenSans-Bold.ttf"
FRACTAL_DIR = ROOT / "Gudasol Fractal Art"
GEO_DIR = ROOT / "Gudasol Sacred Geometry Art"
FPS = 24
FIRST_LINE_CENTER = 0.618
FONT_PX = 92
STRIP_H_FRAC = 0.11
DEFAULT_SHIFT = 0.0
PIN_CLIP = "/Volumes/Untitled/DCIM/DJI_002/DJI_20260911160102_0026_D.MP4"
AUDIO_EXTS = {".mp3", ".wav", ".m4a", ".aac", ".flac", ".aiff"}
VIDEO_EXTS = {".mp4", ".mov", ".m4v", ".mkv", ".webm"}

SIZES = {
    "9by19": (1080, 1920),
    "16by9": (1920, 1080),
}

_FFMPEG: str | None = None
_FFPROBE: str | None = None


def find_ffmpeg() -> str:
    global _FFMPEG
    if _FFMPEG:
        return _FFMPEG
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
        if "subtitles" in filters and ("libx264" in enc or "h264_videotoolbox" in enc):
            _FFMPEG = c
            return c
    sys.exit("Need ffmpeg with libass subtitles and H.264")


def find_ffprobe() -> str:
    global _FFPROBE
    if _FFPROBE:
        return _FFPROBE
    cand = Path(find_ffmpeg()).with_name("ffprobe")
    _FFPROBE = str(cand) if cand.is_file() else (shutil.which("ffprobe") or "")
    if not _FFPROBE:
        sys.exit("ffprobe not found")
    return _FFPROBE


def init_folders() -> None:
    for p in (SRC_VIDEO, SRC_AUDIO, OUT_916, OUT_169, LYRICS, WORK):
        p.mkdir(parents=True, exist_ok=True)
        keep = p / ".gitkeep"
        if p in (SRC_VIDEO, SRC_AUDIO, OUT_916, OUT_169, WORK) and not keep.exists():
            keep.write_text("")
    if not USED_PATH.exists():
        USED_PATH.write_text(json.dumps({"used_videos": []}, indent=2) + "\n")
    if not CONFIG_PATH.exists():
        sd = Path("/Volumes/Untitled/DCIM")
        CONFIG_PATH.write_text(
            json.dumps(
                {
                    "source_videos": str(sd if sd.is_dir() else SRC_VIDEO),
                    "recursive": True,
                    "pin_video": PIN_CLIP if Path(PIN_CLIP).is_file() else "",
                },
                indent=2,
            )
            + "\n"
        )
    if not FONT.is_file():
        sys.exit(f"Missing Open Sans Bold: {FONT}")


def load_config() -> dict:
    if not CONFIG_PATH.exists():
        return {"source_videos": str(SRC_VIDEO), "recursive": True}
    return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))


def set_source_videos(folder: str | Path) -> Path:
    p = Path(folder).expanduser().resolve()
    if not p.is_dir():
        sys.exit(f"Source videos folder missing (is the SD card mounted?): {p}")
    cfg = load_config()
    cfg["source_videos"] = str(p)
    cfg["recursive"] = True
    CONFIG_PATH.write_text(json.dumps(cfg, indent=2) + "\n")
    return p


def source_video_root() -> Path:
    raw = (load_config().get("source_videos") or str(SRC_VIDEO)).strip()
    p = Path(raw).expanduser()
    if not p.is_dir():
        sys.exit(
            f"Source videos folder missing: {p}\n"
            "Mount the SD card, or set it with --source-videos /Volumes/YourCard/DCIM"
        )
    return p


def set_pin_video(path: str | Path) -> Path:
    p = Path(path).expanduser().resolve()
    if not p.is_file():
        sys.exit(f"Pinned video missing (is the SD card mounted?): {p}")
    cfg = load_config()
    cfg["pin_video"] = str(p)
    CONFIG_PATH.write_text(json.dumps(cfg, indent=2) + "\n")
    return p


def pinned_video() -> Path | None:
    raw = (load_config().get("pin_video") or "").strip()
    if not raw:
        return None
    p = Path(raw).expanduser()
    if not p.is_file():
        sys.exit(f"Pinned video missing (is the SD card mounted?): {p}")
    return p


def list_art(folder: Path) -> list[Path]:
    if not folder.is_dir():
        return []
    pics: list[Path] = []
    for p in sorted(folder.iterdir()):
        if p.suffix.lower() not in {".jpg", ".jpeg", ".png", ".webp"}:
            continue
        if "11k" in p.name.lower():
            continue
        pics.append(p)
    return pics


def shifted_lines(lyrics: dict) -> list[dict]:
    shift = float(lyrics.get("shift") or 0)
    duration = float(lyrics.get("duration") or 0)
    out: list[dict] = []
    for line in lyrics.get("lines") or []:
        a = float(line["start"]) + shift
        b = float(line["end"]) + shift
        if b <= 0.04 or a >= duration - 0.04:
            continue
        out.append(
            {
                "start": max(0.0, a),
                "end": min(duration, max(a + 0.12, b)),
                "text": str(line.get("text") or ""),
            }
        )
    return out


def glimpse_windows(lines: list[dict], duration: float) -> list[tuple[float, float]]:
    """1–3s flashes on commas / pauses, spaced about 10–15s."""
    raw: list[tuple[float, float]] = []
    last_end = 0.0
    for line in lines:
        start, end = float(line["start"]), float(line["end"])
        text = str(line.get("text") or "").rstrip()
        gap = start - last_end
        if gap >= 0.45 and last_end > 0.4:
            dur = min(3.0, max(1.0, gap * 0.75))
            t0 = last_end + max(0.0, (gap - dur) * 0.35)
            raw.append((t0, min(duration, t0 + dur)))
        if text.endswith(","):
            raw.append((end, min(duration, end + 1.35)))
        last_end = end
    picked: list[tuple[float, float]] = []
    for t0, t1 in sorted(raw):
        if t1 - t0 < 0.7:
            continue
        if picked and t0 - picked[-1][0] < 10.0:
            continue
        picked.append((t0, min(t0 + 2.6, t1)))
        if len(picked) >= 14:
            break
    t = 11.0
    while t < duration - 3.0 and len(picked) < 14:
        if all(abs(t - a) >= 12.0 for a, _ in picked):
            picked.append((t, t + 1.8))
        t += 13.0
    return sorted(picked)


def clip_id(path: Path) -> str:
    root = source_video_root().resolve()
    try:
        return path.resolve().relative_to(root).as_posix()
    except ValueError:
        return path.name


def slug(name: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", Path(name).stem.lower()).strip("-")
    return s or "song"


def probe_duration(path: Path) -> float:
    out = subprocess.check_output(
        [
            find_ffprobe(), "-v", "error", "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1", str(path),
        ],
        text=True,
    ).strip()
    return float(out)


def load_used() -> dict:
    if not USED_PATH.exists():
        return {"used_videos": []}
    return json.loads(USED_PATH.read_text(encoding="utf-8"))


def save_used(data: dict) -> None:
    USED_PATH.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def used_names() -> set[str]:
    return {row["file"] for row in load_used().get("used_videos") or [] if row.get("file")}


def list_media(folder: Path, exts: set[str]) -> list[Path]:
    return sorted(p for p in folder.iterdir() if p.is_file() and p.suffix.lower() in exts)


def list_videos() -> list[Path]:
    root = source_video_root()
    found: list[Path] = []
    for p in root.rglob("*"):
        if not p.is_file() or p.suffix.lower() not in VIDEO_EXTS:
            continue
        rel = p.relative_to(root)
        if any(part.startswith(".") for part in rel.parts):
            continue
        found.append(p)
    return sorted(found)


def resolve_song(name: str) -> Path:
    p = Path(name)
    if p.is_file():
        return p
    cand = SRC_AUDIO / name
    if cand.is_file():
        return cand
    matches = [x for x in list_media(SRC_AUDIO, AUDIO_EXTS) if x.stem == Path(name).stem or x.name == name]
    if len(matches) == 1:
        return matches[0]
    sys.exit(f"Song not found in {SRC_AUDIO}: {name}")


def lyrics_paths(song: Path) -> dict[str, Path]:
    stem = slug(song.name)
    return {
        "json": LYRICS / f"{stem}.json",
        "srt": LYRICS / f"{stem}.srt",
        "txt": LYRICS / f"{stem}.txt",
    }


def srt_time(t: float) -> str:
    t = max(0.0, t)
    h = int(t // 3600)
    m = int((t % 3600) // 60)
    s = int(t % 60)
    ms = int(round((t - math.floor(t)) * 1000))
    if ms == 1000:
        s += 1
        ms = 0
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def ass_time(t: float) -> str:
    t = max(0.0, t)
    h = int(t // 3600)
    m = int((t % 3600) // 60)
    s = t % 60
    return f"{h}:{m:02d}:{s:05.2f}"


def group_lines(words: list[dict], max_words: int = 6, max_secs: float = 2.4) -> list[dict]:
    cues, buf = [], []
    for w in words:
        token = str(w.get("text") or "").strip()
        if not token:
            continue
        buf.append(w)
        dur = float(buf[-1]["end"]) - float(buf[0]["start"])
        punct = token[-1:] in ".?!,"
        if len(buf) >= max_words or dur >= max_secs or punct:
            cues.append(
                {
                    "start": float(buf[0]["start"]),
                    "end": float(buf[-1]["end"]),
                    "text": " ".join(str(x["text"]).strip() for x in buf),
                }
            )
            buf = []
    if buf:
        cues.append(
            {
                "start": float(buf[0]["start"]),
                "end": float(buf[-1]["end"]),
                "text": " ".join(str(x["text"]).strip() for x in buf),
            }
        )
    for i, c in enumerate(cues):
        if c["end"] <= c["start"]:
            c["end"] = c["start"] + 0.35
        if i + 1 < len(cues):
            c["end"] = min(cues[i + 1]["start"], max(c["end"], c["start"] + 0.25))
    return cues


def write_lyrics_files(payload: dict, paths: dict[str, Path]) -> None:
    paths["json"].write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    lines = payload.get("lines") or []
    srt = []
    for i, line in enumerate(lines, start=1):
        srt.append(str(i))
        srt.append(f"{srt_time(line['start'])} --> {srt_time(line['end'])}")
        srt.append(str(line["text"]).strip())
        srt.append("")
    paths["srt"].write_text("\n".join(srt), encoding="utf-8")
    txt = "\n".join(str(x["text"]).strip() for x in lines if str(x.get("text") or "").strip())
    header = (
        f"# {payload.get('song')}\n"
        f"# duration {payload.get('duration'):.2f}s  language={payload.get('language')}\n"
        f"# verified={payload.get('verified')}\n"
        "# Edit this file or the .json / .srt, then set verified=true in the JSON.\n\n"
    )
    paths["txt"].write_text(header + txt + ("\n" if txt else ""), encoding="utf-8")


def transcribe_song(song: Path) -> dict:
    """Local ASR only. Never translate. Word timestamps when the backend allows it."""
    ffmpeg = find_ffmpeg()
    wav = WORK / f"{slug(song.name)}.16k.wav"
    WORK.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            ffmpeg, "-nostdin", "-y", "-i", str(song),
            "-vn", "-ac", "1", "-ar", "16000",
            "-af", "highpass=f=80,loudnorm",
            str(wav),
        ],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    words: list[dict] = []
    segments: list[dict] = []
    language = "und"
    model_name = ""

    try:
        from faster_whisper import WhisperModel

        print("  transcribing locally (faster-whisper small, no VAD, no translation)…")
        model = WhisperModel("small", device="cpu", compute_type="int8")
        segs, info = model.transcribe(
            str(wav),
            task="transcribe",
            language="en",
            word_timestamps=True,
            vad_filter=False,
            condition_on_previous_text=False,
            beam_size=5,
        )
        language = getattr(info, "language", None) or "en"
        model_name = "faster-whisper/small"
        for seg in segs:
            text = (seg.text or "").strip()
            segments.append({"start": float(seg.start), "end": float(seg.end), "text": text})
            print(f"    [{seg.start:7.1f}-{seg.end:7.1f}] {text[:90]}")
            for w in seg.words or []:
                token = (w.word or "").strip()
                if token:
                    words.append({"start": float(w.start), "end": float(w.end), "text": token})
    except Exception as err:
        try:
            import whisper  # type: ignore

            print("  transcribing locally (whisper, no translation)…")
            model = whisper.load_model("base")
            result = model.transcribe(str(wav), task="transcribe", word_timestamps=True, verbose=False)
            language = result.get("language") or "und"
            model_name = "whisper/base"
            for seg in result.get("segments") or []:
                text = (seg.get("text") or "").strip()
                segments.append({"start": float(seg["start"]), "end": float(seg["end"]), "text": text})
                print(f"    [{seg['start']:7.1f}-{seg['end']:7.1f}] {text[:90]}")
                for w in seg.get("words") or []:
                    token = str(w.get("word") or "").strip()
                    if token:
                        words.append(
                            {
                                "start": float(w.get("start") or seg["start"]),
                                "end": float(w.get("end") or seg["end"]),
                                "text": token,
                            }
                        )
        except Exception as err2:
            print(f"  no local whisper ({err}; {err2})")
            print("  wrote empty lyrics for you to type/timing-edit.")

    try:
        wav.unlink()
    except OSError:
        pass

    lines = group_lines(words) if words else [
        {"start": float(s["start"]), "end": float(s["end"]), "text": s["text"]} for s in segments
    ]
    return {
        "song": song.name,
        "verified": False,
        "language": language,
        "translate": False,
        "model": model_name,
        "duration": probe_duration(song),
        "words": words,
        "lines": lines,
    }


def load_lyrics(song: Path) -> dict:
    path = lyrics_paths(song)["json"]
    if not path.is_file():
        sys.exit(f"No lyrics yet. Run: python …/make_music_video.py --lyrics {song.name}")
    return json.loads(path.read_text(encoding="utf-8"))


def pick_videos(song_dur: float, explicit: Path | None = None) -> list[Path]:
    pin = explicit or pinned_video()
    if pin:
        d = probe_duration(pin)
        print(f"  pin {pin}  {d:.1f}s  (song {song_dur:.1f}s)")
        if d + 0.05 < song_dur:
            sys.exit(f"Pinned clip is only {d:.1f}s, song is {song_dur:.1f}s")
        return [pin]
    used = used_names()
    unused = [p for p in list_videos() if clip_id(p) not in used]
    root = source_video_root()
    if not unused:
        sys.exit(f"No unused source videos in {root}. Add clips or plug in the card, then retry.")
    picked: list[Path] = []
    covered = 0.0
    for p in unused:
        d = probe_duration(p)
        picked.append(p)
        covered += d
        print(f"  + {clip_id(p)}  {d:.1f}s  (cover {covered:.1f}/{song_dur:.1f}s)")
        if covered + 0.05 >= song_dur:
            break
    if covered + 0.05 < song_dur:
        sys.exit(
            f"Unused videos only cover {covered:.1f}s of a {song_dur:.1f}s song. "
            f"Add more files on the card / {root}."
        )
    return picked


def write_ass(lines: list[dict], duration: float, w: int, h: int, dest: Path) -> None:
    style = resolve(load_config())
    center = float(style["caption_place"]["center"]) if style.get("caption_place") else FIRST_LINE_CENTER
    font_name = style.get("font_name") or "Open Sans Bold"
    case = style.get("caption_case") or "lower"
    look = style.get("caption_look") or {}
    margin_v = max(8, int(round(h * center - FONT_PX * 0.5)))
    if look.get("draw") == "chip":
        face = (
            f"Style: Cap,{font_name},{FONT_PX},"
            f"&H00{look['ink'][2]:02X}{look['ink'][1]:02X}{look['ink'][0]:02X},"
            f"&H000000FF,&H00000000,"
            f"&H00{look['fill'][2]:02X}{look['fill'][1]:02X}{look['fill'][0]:02X},"
            f"0,0,0,0,100,100,0,0,3,16,0,8,80,80,{margin_v},1\n\n"
        )
    else:
        ink = look.get("ink") or (255, 255, 255, 255)
        stroke = look.get("stroke") or (0, 0, 0, 255)
        face = (
            f"Style: Cap,{font_name},{FONT_PX},"
            f"&H00{ink[2]:02X}{ink[1]:02X}{ink[0]:02X},&H000000FF,"
            f"&H00{stroke[2]:02X}{stroke[1]:02X}{stroke[0]:02X},&HAA000000,"
            f"0,0,0,0,100,100,0,0,1,{int(look.get('stroke_px') or 3)},2,8,80,80,{margin_v},1\n\n"
        )
    events = [
        "[Script Info]\n",
        "ScriptType: v4.00+\n",
        f"PlayResX: {w}\n",
        f"PlayResY: {h}\n",
        "WrapStyle: 0\n",
        "ScaledBorderAndShadow: yes\n\n",
        "[V4+ Styles]\n",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\n",
        face,
        "[Events]\n",
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n",
    ]
    for line in lines:
        a = max(0.0, float(line["start"]))
        b = min(duration, max(a + 0.12, float(line["end"])))
        if b <= 0.05 or a >= duration - 0.04:
            continue
        text = " ".join(str(line.get("text") or "").split())
        if case == "upper":
            text = text.upper()
        elif case != "as-spoken":
            text = text.lower()
        text = text.replace("\\", "\\\\").replace("{", "(").replace("}", ")")
        if not text:
            continue
        events.append(
            f"Dialogue: 0,{ass_time(a)},{ass_time(b)},Cap,,0,0,0,,"
            f"{{\\an5\\pos({w // 2},{int(round(h * center))})}}{text}\n"
        )
    dest.write_text("".join(events), encoding="utf-8")


def edge_cut(seed: str, depth: int) -> str:
    """Inset from the strip edge. Shape order is shuffled per video."""
    return edges.ffmpeg_cycle(seed, depth, every=30.0)


def ffmpeg_escape(path: Path) -> str:
    return str(path).replace("\\", "/").replace(":", "\\:").replace("'", r"\'")


def render_aspect(
    song: Path,
    videos: list[Path],
    lyrics: dict,
    kind: str,
    dest: Path,
) -> None:
    w, h = SIZES[kind]
    ffmpeg = find_ffmpeg()
    duration = float(lyrics["duration"])
    dest.parent.mkdir(parents=True, exist_ok=True)
    lines = shifted_lines(lyrics)
    ass = WORK / f"{slug(song.name)}-{kind}.ass"
    write_ass(lines, duration, w, h, ass)
    style = resolve(load_config())
    if style.get("font_path"):
        font_dir = WORK / "font"
        font_dir.mkdir(parents=True, exist_ok=True)
        chosen = font_dir / Path(style["font_path"]).name
        if not chosen.is_file() or chosen.stat().st_size != Path(style["font_path"]).stat().st_size:
            shutil.copyfile(style["font_path"], chosen)
        fontsdir = ffmpeg_escape(font_dir)
    else:
        fontsdir = ffmpeg_escape(FONT.parent)
    ass_esc = ffmpeg_escape(ass)
    fractals = list_art(FRACTAL_DIR)
    geos = list_art(GEO_DIR)
    mix = geos + fractals
    windows = glimpse_windows(lines, duration)
    glimpses = [mix[i % len(mix)] for i in range(len(windows))] if mix and windows else []
    strip = fractals[0] if fractals else None
    center = float(style["caption_place"]["center"]) if style.get("caption_place") else FIRST_LINE_CENTER
    strip_h = max(int(round(h * STRIP_H_FRAC)), int(round(FONT_PX * 3.2)))
    strip_y = max(0, int(round(h * center - strip_h / 2)))
    cmd: list[str] = [ffmpeg, "-nostdin", "-y"]
    for v in videos:
        cmd += ["-t", f"{duration:.3f}", "-i", str(v)]
    for img, (t0, t1) in zip(glimpses, windows):
        cmd += [
            "-loop", "1",
            "-framerate", str(FPS),
            "-t", f"{max(1.0, t1 - t0) + 0.2:.3f}",
            "-i",
            str(img),
        ]
    if strip:
        cmd += ["-loop", "1", "-framerate", "1", "-t", f"{duration:.3f}", "-i", str(strip)]
    cmd += ["-i", str(song)]
    n = len(videos)
    g0 = n
    strip_i = n + len(glimpses)
    audio_i = strip_i + (1 if strip else 0)
    parts = []
    for i in range(n):
        parts.append(
            f"[{i}:v]scale={w}:{h}:force_original_aspect_ratio=increase,"
            f"crop={w}:{h}:(iw-{w})/2:(ih-{h})/2,fps={FPS},setsar=1,format=yuv420p[v{i}]"
        )
    parts.append("".join(f"[v{i}]" for i in range(n)) + f"concat=n={n}:v=1:a=0[vcat]")
    prev = "vcat"
    for i, (t0, t1) in enumerate(windows):
        if i >= len(glimpses):
            break
        idx = g0 + i
        alpha = 0.38 if i % 2 == 0 else 0.48
        parts.append(
            f"[{idx}:v]scale={w}:{h}:force_original_aspect_ratio=increase,"
            f"crop={w}:{h}:(iw-{w})/2:(ih-{h})/2,format=rgba,colorchannelmixer=aa={alpha:.2f},"
            f"setpts=PTS-STARTPTS+{t0:.3f}/TB[g{i}]"
        )
        nxt = f"o{i}"
        parts.append(
            f"[{prev}][g{i}]overlay=0:0:eof_action=pass:enable='between(t,{t0:.3f},{t1:.3f})'[{nxt}]"
        )
        prev = nxt
    if strip:
        cut = edge_cut(f"{slug(song.name)}-{kind}", 16)
        parts.append(
            f"[{strip_i}:v]fps={FPS},scale={w}:{strip_h}:force_original_aspect_ratio=increase,"
            f"crop={w}:{strip_h}:(iw-{w})/2:(ih-{strip_h})/2,format=rgba,"
            f"geq=r='r(X,Y)':g='g(X,Y)':b='b(X,Y)':a='if(lt(Y\\,{cut})+gt(Y\\,H-1-{cut})\\,0\\,158)'[strip]"
        )
        parts.append(f"[{prev}][strip]overlay=0:{strip_y}[banded]")
        prev = "banded"
    parts.append(f"[{prev}]subtitles='{ass_esc}':fontsdir='{fontsdir}'[vout]")
    cmd += [
        "-filter_complex", ";".join(parts),
        "-map", "[vout]",
        "-map", f"{audio_i}:a:0",
        "-t", f"{duration:.3f}",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p",
        "-r", str(FPS),
        "-c:a", "aac", "-b:a", "192k",
        "-af", "volume=1.0",
        "-movflags", "+faststart",
        str(dest),
    ]
    print(f"  render {kind} {w}x{h} → {dest.relative_to(MV)}  glimpses={len(windows)}", flush=True)
    proc = subprocess.run(cmd)
    if proc.returncode != 0:
        sys.exit(f"ffmpeg failed ({kind})")


def cmd_lyrics(song_name: str) -> None:
    init_folders()
    song = resolve_song(song_name)
    paths = lyrics_paths(song)
    print(f"song {song.name}  {probe_duration(song):.1f}s")
    payload = transcribe_song(song)
    write_lyrics_files(payload, paths)
    print(f"\nEdit and verify BEFORE render:")
    print(f"  {paths['json']}")
    print(f"  {paths['srt']}")
    print(f"  {paths['txt']}")
    print("Set \"verified\": true in the JSON after you check timing and wording.")
    print("Do not translate. Keep original language, on-beat with the song.")


def cmd_render(song_name: str, video: str | None = None, shift: float | None = None) -> None:
    init_folders()
    song = resolve_song(song_name)
    lyrics = load_lyrics(song)
    if lyrics.get("verified") is not True:
        sys.exit(
            f"{lyrics_paths(song)['json'].name} is not verified. "
            "Fix lyrics, set \"verified\": true, then rerun --render."
        )
    if lyrics.get("translate"):
        sys.exit("translate must stay false — original language only.")
    song_dur = probe_duration(song)
    lyrics["duration"] = song_dur
    if shift is not None:
        lyrics["shift"] = float(shift)
        paths = lyrics_paths(song)
        paths["json"].write_text(json.dumps(lyrics, indent=2) + "\n", encoding="utf-8")
    elif "shift" not in lyrics:
        lyrics["shift"] = DEFAULT_SHIFT
        paths = lyrics_paths(song)
        paths["json"].write_text(json.dumps(lyrics, indent=2) + "\n", encoding="utf-8")
    explicit = set_pin_video(video) if video else None
    videos = pick_videos(song_dur, explicit)
    pin = pinned_video()
    stem = slug(song.name)
    dest_a = OUT_916 / f"{stem}.mp4"
    dest_b = OUT_169 / f"{stem}.mp4"
    render_aspect(song, videos, lyrics, "9by19", dest_a)
    da = probe_duration(dest_a)
    render_aspect(song, videos, lyrics, "16by9", dest_b)
    db = probe_duration(dest_b)
    if da < song_dur - 0.35 or db < song_dur - 0.35:
        dest_a.unlink(missing_ok=True)
        dest_b.unlink(missing_ok=True)
        sys.exit(f"Output shorter than song ({da:.1f}s / {db:.1f}s vs {song_dur:.1f}s). Nothing marked used.")
    if not pin:
        data = load_used()
        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        for v in videos:
            data.setdefault("used_videos", []).append(
                {"file": clip_id(v), "song": song.name, "at": now}
            )
        save_used(data)
    print(f"\naccepted {song.name}")
    print(f"  9by19 {dest_a}  {da:.1f}s")
    print(f"  16by9 {dest_b}  {db:.1f}s")
    print(f"  picture {', '.join(clip_id(v) for v in videos)}" + ("  (pinned, reusable)" if pin else ""))
    print(f"  caption shift {float(lyrics.get('shift') or 0):+.2f}s")


def cmd_status() -> None:
    init_folders()
    songs = list_media(SRC_AUDIO, AUDIO_EXTS)
    root = source_video_root()
    vids = list_videos()
    used = used_names()
    unused = [p for p in vids if clip_id(p) not in used]
    print(f"source videos root: {root}")
    print(f"songs: {len(songs)}")
    for s in songs:
        flag = "verified" if (lyrics_paths(s)["json"].exists() and load_lyrics(s).get("verified")) else (
            "lyrics" if lyrics_paths(s)["json"].exists() else "no-lyrics"
        )
        print(f"  {s.name}  {probe_duration(s):.1f}s  {flag}")
    print(f"source videos: {len(vids)}  unused: {len(unused)}")
    for p in unused:
        print(f"  unused {clip_id(p)}  {probe_duration(p):.1f}s")
    for p in vids:
        if clip_id(p) in used:
            print(f"  used   {clip_id(p)}")


def main() -> None:
    init_folders()
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--lyrics", metavar="SONG", help="Transcribe locally into Music Videos/lyrics/ (not verified)")
    p.add_argument("--render", metavar="SONG", help="Render 9by19 + 16by9 after lyrics verified=true")
    p.add_argument(
        "--source-videos",
        metavar="DIR",
        help="Read clips in place (SD card OK). Saved in Music Videos/config.json",
    )
    p.add_argument("--status", action="store_true")
    p.add_argument("--video", metavar="PATH", help="Pin a source clip for this and later songs (reusable)")
    p.add_argument("--shift", type=float, help="Seconds to move captions (negative = earlier)")
    args = p.parse_args()
    if args.source_videos:
        set_source_videos(args.source_videos)
    if args.video:
        set_pin_video(args.video)
    if args.lyrics:
        cmd_lyrics(args.lyrics)
        return
    if args.render:
        cmd_render(args.render, video=args.video, shift=args.shift)
        return
    if args.status:
        cmd_status()
        return
    cmd_status()


if __name__ == "__main__":
    main()
