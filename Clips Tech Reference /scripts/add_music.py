#!/usr/bin/env python3
"""Lay a music bed under ONE finished clip — video stream copied, untouched.

    python3 add_music.py <clip_mp4> <music_file> <out_mp4> [--gain-db -20]

The bed enters at clip start: tracks are pre-trimmed by the music-folder
owner so t=0 of the file IS the entry point — no offset logic here. Music
sits QUIET under speech (-20dB default for normally mastered tracks, never
louder by default). amix duration=first pins output length to the clip
exactly — a longer track gets cut, a shorter one leaves silence after
(fine); normalize=0 so amix never ducks the speech to make room.

One ffmpeg pass, -c:v copy: frames and captions come out bit-identical.
"""
import os
import subprocess
import sys


def flag(name, default):
    return sys.argv[sys.argv.index(name) + 1] if name in sys.argv else default


def probe_duration(path):
    r = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", path],
        capture_output=True, text=True)
    return float(r.stdout.strip()) if r.returncode == 0 else 0.0


def main():
    if len(sys.argv) < 4:
        sys.exit("usage: add_music.py <clip_mp4> <music_file> <out_mp4> "
                 "[--gain-db -20]")
    clip, music, out = sys.argv[1], sys.argv[2], sys.argv[3]
    gain = float(flag("--gain-db", "-20"))
    for p in (clip, music):
        if not os.path.isfile(p):
            sys.exit(f"input not found: {p}")

    fc = (f"[1:a]volume={gain:g}dB[m];"
          f"[0:a][m]amix=inputs=2:duration=first:normalize=0[aout]")
    cmd = ["ffmpeg", "-nostdin", "-i", clip, "-i", music,
           "-filter_complex", fc, "-map", "0:v", "-map", "[aout]",
           "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
           "-movflags", "+faststart", "-y", out]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        sys.exit(f"ffmpeg failed:\n{r.stderr[-1500:]}")
    print(f"{probe_duration(out):.2f}s, music at {gain:g}dB -> {out}")


if __name__ == "__main__":
    main()
