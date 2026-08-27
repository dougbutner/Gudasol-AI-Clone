#!/usr/bin/env python3
"""Render ONE clip's cuts JSON to a 1080x1920 vertical MP4 — captionless
(render_captions.mjs burns the words afterwards).

Two ways to drive it:

LEGACY (whole-clip, single mode — fine for simple talking-head sources):
    python3 render_clip.py <cuts_json> <out_mp4> --mode crop [--face-x 0.5]
    python3 render_clip.py <cuts_json> <out_mp4> --mode canvas
                           [--canvas-fit width|height]

WIDE (long-form mode — the frame ships as shot):
    python3 render_clip.py <cuts_json> <out_mp4> --mode wide
Source resolution, source aspect, no reframing of any kind: only the CUTS
change. Rejects --plan — a layout plan in wide mode is a category error.

PLAN (layout v2 — per-region layouts, frame-exact):
    python3 render_clip.py <cuts_json> <out_mp4> --plan <plan_json>

A plan tiles the clip's keep-segments into contiguous frame-exact REGIONS
(from scene_scan.py) and gives each region its own layout:

{"regions": [
  {"in_frame": 13392, "out_frame": 13470, "mode": "split",
   "inset":   [0.014, 0.507, 0.286, 0.397],
   "content": [0.300, 0.060, 0.680, 0.870]},
  {"in_frame": 13470, "out_frame": 13600, "mode": "crop", "face_x": 0.55},
  {"in_frame": 13600, "out_frame": 13720, "mode": "zoom",
   "zone": [0.28, 0.05, 0.55, 0.75]},
  {"in_frame": 13720, "out_frame": 13800, "mode": "full"}
]}
All rects are [x, y, w, h] as fractions of the SOURCE frame.

Modes:
  crop   9:16 column crop centered on face_x. Full-frame talking heads.
  split  50/50 vertical stack: CONTENT on top, STREAMER (facecam inset crop)
         on the bottom, each cover-filling 1080x960.
  zoom   punch into `zone` (the area of focus), presented over the dimmed
         blurred canvas. High-confidence focus areas only.
  full   whole frame over the dimmed blurred canvas (the fallback and the
         dynamic-shot look).
  wide   passthrough at SOURCE dimensions — no scale, no crop, no canvas.
         Long-form mode (rule 11): the frame ships as shot.

FRAME-EXACT LAW: regions must tile the cuts segments exactly — no gaps, no
overlaps, boundaries inside a segment only where the scene scan cut. One
frame of layout bleed across a scene cut reads as sloppy; the script
hard-fails on any tiling error rather than render it.

Everything renders in ONE ffmpeg filter_complex with a single concat and one
encode. Never stream-copy concat (frozen frames — perfect-cuts lesson).
"""
import json
import subprocess
import sys

OUT_W, OUT_H = 1080, 1920
HALF_H = OUT_H // 2
CANVAS_FG_H = 806
BG_DIM = 0.5   # blurred-backdrop luminance multiplier: subtle, not a focus


def flag(name, default):
    return sys.argv[sys.argv.index(name) + 1] if name in sys.argv else default


def even(v):
    return int(v) // 2 * 2


def rect_px(frac, w, h):
    x = max(0, min(even(frac[0] * w), w - 16))
    y = max(0, min(even(frac[1] * h), h - 16))
    rw = max(even(min(frac[2] * w, w - x)), 16)
    rh = max(even(min(frac[3] * h, h - y)), 16)
    return x, y, rw, rh


def bg_chain(label_in, label_out):
    return (f"[{label_in}]scale={OUT_W}:{OUT_H}:"
            f"force_original_aspect_ratio=increase,"
            f"crop={OUT_W}:{OUT_H},boxblur=24:2,"
            f"lutyuv=y=val*{BG_DIM}[{label_out}];")


def chain_for(region, n, w, h):
    mode = region.get("mode", "full")
    if mode == "crop":
        cw = even(h * 9 / 16)
        fx = float(region.get("face_x", 0.5))
        cx = even(max(0, min(int(fx * w - cw / 2), w - cw)))
        return (f"[v{n}]crop={cw}:{h}:{cx}:0,"
                f"scale={OUT_W}:{OUT_H}:flags=lanczos,setsar=1[o{n}];")
    if mode == "split":
        ix, iy, iw, ih = rect_px(region["inset"], w, h)
        cx, cy, cw, ch = rect_px(region.get("content",
                                            [0.0, 0.0, 1.0, 1.0]), w, h)
        return (
            f"[v{n}]split[c{n}][f{n}];"
            f"[c{n}]crop={cw}:{ch}:{cx}:{cy},"
            f"scale={OUT_W}:{HALF_H}:force_original_aspect_ratio=increase,"
            f"crop={OUT_W}:{HALF_H}[ct{n}];"
            f"[f{n}]crop={iw}:{ih}:{ix}:{iy},"
            f"scale={OUT_W}:{HALF_H}:force_original_aspect_ratio=increase,"
            f"crop={OUT_W}:{HALF_H}[fb{n}];"
            f"[ct{n}][fb{n}]vstack,setsar=1[o{n}];")
    if mode == "zoom":
        zx, zy, zw, zh = rect_px(region["zone"], w, h)
        # backdrop from the FULL frame, not the zone — a zone whose lower
        # half is dark UI (chat under a corner cam) otherwise blurs to a
        # near-black dead band (field report 2026-08-22); full-frame keeps
        # the scene's colour, same as `full` mode's canvas
        return (
            f"[v{n}]split[zb{n}][zf{n}];"
            + bg_chain(f"zb{n}", f"zbg{n}") +
            f"[zf{n}]crop={zw}:{zh}:{zx}:{zy},scale={OUT_W}:-2[zfg{n}];"
            f"[zbg{n}][zfg{n}]overlay=(W-w)/2:(H-h)/2,setsar=1[o{n}];")
    if mode == "wide":
        # LONG-FORM PASSTHROUGH (rule 11): the frame ships as shot, at SOURCE
        # dimensions. No scale, no crop, no setsar — a source with non-square
        # pixels keeps them, and every segment comes from the same source so
        # concat's size/SAR inputs already agree. Only the CUTS change.
        return f"[v{n}]null[o{n}];"
    if mode == "_canvas_height":
        return (
            f"[v{n}]split[b{n}][f{n}];"
            + bg_chain(f"b{n}", f"bg{n}") +
            f"[f{n}]scale=-2:{CANVAS_FG_H}[fg{n}];"
            f"[bg{n}][fg{n}]overlay=(W-w)/2:(H-h)/2,setsar=1[o{n}];")
    # full
    return (
        f"[v{n}]split[b{n}][f{n}];"
        + bg_chain(f"b{n}", f"bg{n}") +
        f"[f{n}]scale={OUT_W}:-2[fg{n}];"
        f"[bg{n}][fg{n}]overlay=(W-w)/2:(H-h)/2,setsar=1[o{n}];")


def validate_plan(regions, clips):
    """Regions must tile the cuts segments exactly, in order."""
    ri = 0
    for c in clips:
        pos = c["in_frame"]
        while pos < c["out_frame"]:
            if ri >= len(regions):
                sys.exit(f"plan error: no region covers frame {pos} "
                         "(frame-exact law)")
            r = regions[ri]
            if r["in_frame"] != pos:
                sys.exit(f"plan error: region {ri} starts at "
                         f"{r['in_frame']}, expected {pos} (frame-exact law)")
            if r["out_frame"] > c["out_frame"]:
                sys.exit(f"plan error: region {ri} crosses a segment "
                         f"boundary ({r['out_frame']} > {c['out_frame']})")
            pos = r["out_frame"]
            ri += 1
    if ri != len(regions):
        sys.exit("plan error: extra regions past the last segment")


def main():
    spec = json.load(open(sys.argv[1], encoding="utf-8"))
    out = sys.argv[2]
    fps, w, h = spec["fps"], spec["width"], spec["height"]
    clips = spec["clips"]
    plan_path = flag("--plan", None)

    mode = flag("--mode", "crop")
    if plan_path and mode == "wide":
        sys.exit("--mode wide takes no --plan: long-form ships the frame as "
                 "shot (rule 11). Drop one of the two.")

    if plan_path:
        regions = json.load(open(plan_path, encoding="utf-8"))["regions"]
        validate_plan(regions, clips)
    else:
        if mode == "crop":
            m = {"mode": "crop", "face_x": float(flag("--face-x", "0.5"))}
        elif mode == "wide":
            m = {"mode": "wide"}
        elif flag("--canvas-fit", "height") == "width":
            m = {"mode": "full"}
        else:
            m = {"mode": "_canvas_height"}
        regions = [dict(m, in_frame=c["in_frame"], out_frame=c["out_frame"])
                   for c in clips]

    parts, labels = [], []
    for n, r in enumerate(regions):
        s, e = r["in_frame"] / fps, r["out_frame"] / fps
        parts.append(
            f"[0:v]trim=start={s:.4f}:end={e:.4f},setpts=PTS-STARTPTS[v{n}];"
            f"[0:a]atrim=start={s:.4f}:end={e:.4f},asetpts=PTS-STARTPTS"
            f"[a{n}];")
        parts.append(chain_for(r, n, w, h))
        labels.append(f"[o{n}][a{n}]")
    fc = "".join(parts) + "".join(labels) + \
        f"concat=n={len(regions)}:v=1:a=1[outv][outa]"

    cmd = ["ffmpeg", "-nostdin", "-i", spec["source"],
           "-filter_complex", fc, "-map", "[outv]", "-map", "[outa]",
           "-c:v", "libx264", "-preset", "medium", "-crf", "18",
           "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart",
           "-y", out]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        sys.exit(f"ffmpeg failed:\n{r.stderr[-1500:]}")
    total = sum(c["out_frame"] - c["in_frame"] for c in clips) / fps
    modes = ",".join(sorted({str(rr.get("mode", "full")).strip("_")
                             for rr in regions}))
    geom = f"{w}x{h}" if modes == "wide" else f"{OUT_W}x{OUT_H}"
    print(f"{len(regions)} regions ({modes}), {geom}, {total:.2f}s -> {out}")


if __name__ == "__main__":
    main()
