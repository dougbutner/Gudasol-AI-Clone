#!/usr/bin/env python3
"""Frame-exact scene scan for ONE clip: find every hard scene change inside
the clip's keep-segments so layout regions can switch on the EXACT frame.

Usage:
    python3 scene_scan.py <clip_cuts_json> [--outdir DIR]
                          [--threshold 0.30] [--min-frames 12]

For each keep-segment: ffmpeg scene detection over exactly that frame range.
Cuts closer than --min-frames to a segment boundary or to each other are
merged — a layout that flips for under half a second reads as flicker, not
precision. Every resulting region gets a probe still (midpoint frame, 640px
wide) for the layout decision.

Output (in --outdir, default alongside the cuts json):
  <base> scenes.json    {"fps":30,"regions":[{"seg":0,"in_frame":13392,
                             "out_frame":13470,"probe":"probe r00 ....png"}]}
  probe rNN f<in>-<out>.png  one per region

Regions tile the keep-segments exactly — they are the input to
render_clip.py --plan, which enforces the same tiling (frame-exact law).
"""
import json
import os
import re
import subprocess
import sys


def flag(name, default):
    return sys.argv[sys.argv.index(name) + 1] if name in sys.argv else default


def main():
    spec = json.load(open(sys.argv[1], encoding="utf-8"))
    base = os.path.splitext(os.path.basename(sys.argv[1]))[0]
    outdir = flag("--outdir",
                  os.path.dirname(os.path.abspath(sys.argv[1])) or ".")
    thr = float(flag("--threshold", "0.30"))
    min_f = int(flag("--min-frames", "12"))
    os.makedirs(outdir, exist_ok=True)
    src, fps = spec["source"], spec["fps"]

    regions = []
    for k, c in enumerate(spec["clips"]):
        a, b = c["in_frame"], c["out_frame"]
        s, e = a / fps, b / fps
        r = subprocess.run(
            ["ffmpeg", "-nostdin", "-i", src, "-vf",
             f"trim=start={s:.4f}:end={e:.4f},setpts=PTS-STARTPTS,"
             f"select='gt(scene,{thr})',showinfo",
             "-f", "null", "-"], capture_output=True, text=True)
        cuts = []
        for m in re.finditer(r"pts_time:([\d.]+)", r.stderr):
            f_abs = a + round(float(m.group(1)) * fps)
            if a + min_f <= f_abs <= b - min_f and \
                    (not cuts or f_abs - cuts[-1] >= min_f):
                cuts.append(f_abs)
        bounds = [a] + cuts + [b]
        for i in range(len(bounds) - 1):
            regions.append({"seg": k, "in_frame": bounds[i],
                            "out_frame": bounds[i + 1]})

    for n, rg in enumerate(regions):
        mid_t = (rg["in_frame"] + rg["out_frame"]) / 2 / fps
        probe = f"probe r{n:02d} f{rg['in_frame']}-{rg['out_frame']}.png"
        subprocess.run(
            ["ffmpeg", "-nostdin", "-ss", f"{mid_t:.3f}", "-i", src,
             "-frames:v", "1", "-vf", "scale=640:-2", "-y",
             os.path.join(outdir, probe)], capture_output=True)
        rg["probe"] = probe

    out_path = os.path.join(outdir, f"{base} scenes.json")
    json.dump({"fps": fps, "regions": regions},
              open(out_path, "w", encoding="utf-8"), indent=1)
    print(f"{len(regions)} regions -> {out_path}")
    for n, rg in enumerate(regions):
        d = (rg["out_frame"] - rg["in_frame"]) / fps
        print(f"  r{n:02d}  seg{rg['seg']}  "
              f"f{rg['in_frame']}-{rg['out_frame']}  {d:5.1f}s")


if __name__ == "__main__":
    main()
