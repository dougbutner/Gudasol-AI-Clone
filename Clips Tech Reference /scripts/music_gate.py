#!/usr/bin/env python3
"""Decide whether ONE clip may take a music bed: measure whether the
SOURCE already carries music under the speech.

    python3 music_gate.py <clip_cuts_json> <map_json>

The instrument is the waveform, not the transcript: in a clean recording
the gaps BETWEEN speech blocks sit near silence; when the stream is
running music the gaps never drop — the bed under the voice keeps
playing. So: take the clip's keep-ranges, find the inter-speech gaps
inside them (speech map blocks), measure the audio level in just those
gaps, and let the number decide.

Rules:
  gap floor louder than -38dB (the boundary law's out-threshold — audio
  that silencedetect would not call silence) -> the source is already
  scored -> bed=skip.
  Too little gap time to measure (< 0.8s, wall-to-wall speech) -> fall
  back to the speech map's rescue-calibration flag (rescue fires exactly
  when muxed music defeats the locked thresholds): rescued -> bed=skip,
  else bed=ok with a thin-evidence note.

LAST stdout line is the contract: `bed=ok` or `bed=skip`.
"""
import json
import re
import subprocess
import sys

GAP_MARGIN = 0.06      # keep block-edge bleed out of the measurement
MIN_GAP = 0.35         # gaps shorter than this measure the speaker, not the room
MIN_EVIDENCE = 0.8     # total gap seconds needed to trust the measurement
MUSIC_FLOOR_DB = -38.0


def mean_volume(src, start, dur):
    r = subprocess.run(
        ["ffmpeg", "-nostdin", "-ss", f"{start:.3f}", "-t", f"{dur:.3f}",
         "-i", src, "-af", "volumedetect", "-f", "null", "-"],
        capture_output=True, text=True)
    m = re.search(r"mean_volume:\s*(-?[\d.]+) dB", r.stderr)
    return float(m.group(1)) if m else None


def main():
    if len(sys.argv) < 3:
        sys.exit(__doc__.strip())
    cuts = json.load(open(sys.argv[1], encoding="utf-8"))
    mp = json.load(open(sys.argv[2], encoding="utf-8"))
    fps, src = cuts["fps"], cuts["source"]
    blocks = [(b["start"], b["end"]) for b in mp["blocks"]]
    rescued = bool(mp.get("thresholds", {}).get("rescued"))

    gaps = []
    for c in cuts["clips"]:
        t0, t1 = c["in_frame"] / fps, c["out_frame"] / fps
        cursor = t0
        for bs, be in sorted((max(bs, t0), min(be, t1))
                             for bs, be in blocks if be > t0 and bs < t1):
            if bs - cursor >= MIN_GAP + 2 * GAP_MARGIN:
                gaps.append((cursor + GAP_MARGIN, bs - GAP_MARGIN))
            cursor = max(cursor, be)
        if t1 - cursor >= MIN_GAP + 2 * GAP_MARGIN:
            gaps.append((cursor + GAP_MARGIN, t1 - GAP_MARGIN))

    total = sum(b - a for a, b in gaps)
    if total < MIN_EVIDENCE:
        why = ("rescue-calibrated map (muxed music defeated the locked "
               "thresholds)" if rescued else "thin evidence — wall-to-wall "
               "speech, no rescue flag")
        print(f"gap time {total:.2f}s < {MIN_EVIDENCE}s — {why}")
        print("bed=skip" if rescued else "bed=ok")
        return

    levels = []
    for a, b in gaps:
        v = mean_volume(src, a, b - a)
        if v is not None:
            levels.append((b - a, v))
            print(f"  gap {a:8.2f}-{b:8.2f}  {b - a:5.2f}s  {v:7.1f} dB")
    if not levels:
        print("no measurable gaps — falling back to rescue flag")
        print("bed=skip" if rescued else "bed=ok")
        return
    wmean = sum(d * v for d, v in levels) / sum(d for d, v in levels)
    verdict = wmean > MUSIC_FLOOR_DB or rescued
    print(f"gap floor {wmean:.1f} dB over {total:.1f}s "
          f"(threshold {MUSIC_FLOOR_DB:.0f} dB"
          + (", rescue-calibrated map" if rescued else "") + ")")
    print(f"the source is {'already scored — bed yields' if verdict else 'clean — bed ok'}")
    print("bed=skip" if verdict else "bed=ok")


if __name__ == "__main__":
    main()
