#!/usr/bin/env python3
"""Measure each scene region before the layout call: faces, facecam rect,
active-content rect, void detection. The MODEL still makes the categorical
mode call (rule 8) — this script replaces eyeballed rects with measured
ones and hands the model an annotated still per region.

    python3 layout_probe.py "clip NN cuts.json" \
        "clip NN cuts scenes.json" --outdir DIR [--samples 3]

Writes into --outdir:
    clip NN probe.json            measured data per region
    probe rNN annotated.png       mid frame, rects drawn (read these)

Detection lexicon (all rects [x,y,w,h] fractions of the source frame):
    faces        stable face clusters (hits = sampled frames seen in)
    full_face_x  face-center x when a face is FULL-FRAME scale (crop mode)
    cam          facecam candidate: motion blob containing a stable face,
                 else a corner motion blob at inset scale (conf reflects it)
    content      dominant active area outside cam/chat (motion first,
                 bright-structure fallback for static scenes)
    void         True when nothing but the cam moves and structure is flat
                 — a `split` content pane here renders a black pane
Suggestions are HINTS for the mode call, never bindings."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import layout_common as L  # noqa: E402

L.need_cv()
import cv2  # noqa: E402


def flag(name, default):
    return sys.argv[sys.argv.index(name) + 1] if name in sys.argv else default


def sample_frames(r, n):
    a, b = r["in_frame"], r["out_frame"]
    if b - a <= 8:
        return [(a + b) // 2]
    pts = [a + 2, (a + b) // 2, b - 3][:max(2, n)]
    return sorted(set(pts))


def corner_blob(blbs, W, H):
    """Inset-scale motion blob touching a frame corner — cam fallback when
    the face detector whiffs (caps, profiles, dark rooms)."""
    for b in blbs:
        x, y, w, h = b
        area = (w * h) / (W * H)
        touches = (x < W * 0.02 or x + w > W * 0.98) and \
                  (y < H * 0.02 or y + h > H * 0.98)
        if touches and 0.015 <= area <= 0.14 and 0.7 <= w / h <= 2.4:
            return b
    return None


def main():
    cuts = L.load_json(sys.argv[1])
    scenes = L.load_json(sys.argv[2])
    outdir = flag("--outdir", os.path.dirname(os.path.abspath(sys.argv[1])))
    n_samples = int(flag("--samples", "3"))
    os.makedirs(outdir, exist_ok=True)

    fps, W, H = cuts["fps"], cuts["width"], cuts["height"]
    stem = os.path.basename(sys.argv[1]).replace(" cuts.json", "")
    report = {"regions": []}

    for r in scenes["regions"]:
        frames = L.grab_frames(cuts["source"], fps,
                               sample_frames(r, n_samples))
        if not frames:
            report["regions"].append(dict(r, error="no frames extracted"))
            continue
        mid_img = frames[len(frames) // 2][1]

        per_frame = [L.detect_faces(img) for _, img in frames]
        clusters = [c for c in L.cluster_faces(per_frame)
                    if c["hits"] >= min(2, len(frames))]

        mmask = L.motion_mask(frames)
        if mmask is not None:      # OS taskbar clock/tray flicker is not
            mmask[int(H * 0.955):, :] = 0   # content — screen captures
        mblobs = L.blobs(mmask)

        # --- cam ---
        def motion_cover(box):
            if mmask is None:
                return 0.0
            x, y, w, h = box
            sub = mmask[max(0, y):y + h, max(0, x):x + w]
            return float((sub > 0).mean()) if sub.size else 0.0

        def corner_dist(box):
            bx, by = box[0] + box[2] / 2, box[1] + box[3] / 2
            return min(((bx - X) ** 2 + (by - Y) ** 2) ** 0.5
                       for X in (0, W) for Y in (0, H))

        cam, cam_conf, cam_face, cam_choice = None, 0.0, None, None
        inset_faces = [c for c in clusters if c["box"][3] < 0.24 * H]
        if inset_faces:
            # a face in a motionless area cannot be a live camera — a big
            # static portrait (thumbnail, AI image) once outranked the real
            # corner cam on size alone (field report 2026-08-22). Rank by
            # motion overlap first, corner proximity second, then
            # stability/size.
            ranked = sorted(inset_faces, key=lambda c: (
                -motion_cover(c["box"]), corner_dist(c["box"]),
                -c["hits"], -(c["box"][2] * c["box"][3])))
            f = ranked[0]["box"]
            cam_choice = {
                "picked": L.to_frac(f, W, H),
                "motion": round(motion_cover(f), 3),
                "reason": (f"motion {motion_cover(f):.2f}, corner-dist "
                           f"{corner_dist(f):.0f}px, over "
                           f"{len(ranked) - 1} other face(s)"
                           if len(ranked) > 1 else "only inset-scale face"),
            }
            fc = (f[0] + f[2] / 2, f[1] + f[3] / 2)
            host = next((b for b in mblobs if L.point_in(fc, b)), None)
            if host is None:                       # static cam frame; expand
                host = [max(0, int(f[0] - f[2] * 0.9)),
                        max(0, int(f[1] - f[3] * 0.8)),
                        int(f[2] * 2.8), int(f[3] * 3.2)]
            cx = max(0, host[0] - int(W * 0.004))
            cy = max(0, host[1] - int(H * 0.006))
            cam = [cx, cy,
                   min(host[2] + int(W * 0.008), W - cx),
                   min(host[3] + int(H * 0.012), H - cy)]
            cam_conf = ranked[0]["hits"] / len(frames)
            cam_face = f
        else:
            cb = corner_blob(mblobs, W, H)
            if cb is not None:
                cam, cam_conf = cb, 0.3

        # --- full-frame person ---
        big = [c for c in clusters if c["box"][3] >= 0.24 * H]
        full_face_x = round((big[0]["box"][0] + big[0]["box"][2] / 2) / W, 3) \
            if big else None

        # --- content: motion outside cam, bright-structure fallback ---
        def outside_cam(b):
            if cam is None:
                return True
            fc = (b[0] + b[2] / 2, b[1] + b[3] / 2)
            return not L.point_in(fc, cam)

        # motion bbox: the moving parts of the show, outside the cam
        mcands = [b for b in mblobs if outside_cam(b)]
        motion_rect = None
        if mcands:
            # weight area by distance from the vertical edges — chat columns
            # hug an edge, the show sits nearer the middle
            def score(b):
                cx = (b[0] + b[2] / 2) / W
                return b[2] * b[3] * (0.35 + min(cx, 1 - cx))
            best = max(mcands, key=score)
            grow = [b for b in mcands if b is not best and
                    abs((b[0] + b[2] / 2) - (best[0] + best[2] / 2))
                    < best[2] * 0.75]
            xs = [best[0]] + [b[0] for b in grow]
            ys = [best[1]] + [b[1] for b in grow]
            x2 = [best[0] + best[2]] + [b[0] + b[2] for b in grow]
            y2 = [best[1] + best[3]] + [b[1] + b[3] for b in grow]
            motion_rect = [min(xs), min(ys),
                           max(x2) - min(xs), max(y2) - min(ys)]

        # bright panel: the PANEL the motion lives in (modal, game board)
        panels = [b for b in L.panel_blobs(L.bright_mask(mid_img), W, H)
                  if outside_cam(b)]
        panel = None
        if panels:
            panel = (next((p for p in panels
                           if motion_rect and L.contains(p, motion_rect)),
                          None) or panels[0])

        # prefer the panel when the motion sits inside it — the moving
        # sliver (a scrolling list, a ticking chart) is not the show, the
        # panel around it is
        content, source, fill = None, None, 0.0
        if panel is not None and (motion_rect is None
                                  or L.contains(panel, motion_rect)):
            content, source = panel, "panel"
        elif motion_rect is not None:
            content, source = motion_rect, "motion"
        if content is not None and mmask is not None:
            sub = mmask[content[1]:content[1] + content[3],
                        content[0]:content[0] + content[2]]
            fill = round(float((sub > 0).mean()), 3) if sub.size else 0.0

        # void: nothing moves outside the cam and no discrete panel stands
        # out — a `split` content pane here renders near-black
        void = motion_rect is None and panel is None

        # --- suggestion (hint only) ---
        if full_face_x is not None:
            suggest = f"crop face_x={full_face_x}"
        elif void and cam is not None:
            suggest = "zoom on cam (screen is idle) or full"
        elif cam is not None and content is not None:
            suggest = "split (measured rects below)"
        else:
            suggest = "full (low confidence)"

        entry = {
            "seg": r.get("seg"), "in_frame": r["in_frame"],
            "out_frame": r["out_frame"],
            "faces": [{"box": L.to_frac(c["box"], W, H), "hits": c["hits"]}
                      for c in clusters],
            "full_face_x": full_face_x,
            "cam": ({"rect": L.to_frac(cam, W, H), "conf": round(cam_conf, 2),
                     "face": L.to_frac(cam_face, W, H) if cam_face else None}
                    if cam is not None else None),
            "cam_choice": cam_choice,
            "content": ({"rect": L.to_frac(content, W, H), "fill": fill,
                         "source": source} if content is not None else None),
            "motion": (L.to_frac(motion_rect, W, H)
                       if motion_rect is not None else None),
            "panel": L.to_frac(panel, W, H) if panel is not None else None,
            "void": bool(void),
            "suggest": suggest,
        }
        report["regions"].append(entry)

        # --- annotated still ---
        vis = mid_img.copy()
        for c in clusters:
            x, y, w, h = c["box"]
            cv2.rectangle(vis, (x, y), (x + w, y + h), (0, 220, 0), 3)
        if cam is not None:
            cv2.rectangle(vis, (cam[0], cam[1]),
                          (cam[0] + cam[2], cam[1] + cam[3]),
                          (255, 220, 0), 4)
            cv2.putText(vis, f"CAM {cam_conf:.1f}", (cam[0] + 6, cam[1] + 34),
                        cv2.FONT_HERSHEY_SIMPLEX, 1.1, (255, 220, 0), 3)
        if motion_rect is not None and motion_rect is not content:
            cv2.rectangle(vis, (motion_rect[0], motion_rect[1]),
                          (motion_rect[0] + motion_rect[2],
                           motion_rect[1] + motion_rect[3]),
                          (0, 90, 160), 2)
        if panel is not None and panel is not content:
            cv2.rectangle(vis, (panel[0], panel[1]),
                          (panel[0] + panel[2], panel[1] + panel[3]),
                          (255, 0, 200), 2)
        if content is not None:
            cv2.rectangle(vis, (content[0], content[1]),
                          (content[0] + content[2], content[1] + content[3]),
                          (0, 140, 255), 4)
            cv2.putText(vis, f"CONTENT {source} fill={fill}",
                        (content[0] + 6, max(30, content[1] - 12)),
                        cv2.FONT_HERSHEY_SIMPLEX, 1.1, (0, 140, 255), 3)
        cv2.putText(vis, f"r{scenes['regions'].index(r):02d} "
                    f"{r['in_frame']}-{r['out_frame']}  {suggest}"
                    + ("  VOID" if void else ""),
                    (14, H - 22), cv2.FONT_HERSHEY_SIMPLEX, 1.2,
                    (255, 255, 255), 3)
        scale = 960 / W
        vis = cv2.resize(vis, (960, int(H * scale)))
        cv2.imwrite(os.path.join(
            outdir, f"{stem} probe r{scenes['regions'].index(r):02d} "
                    f"annotated.png"), vis)

    out_json = os.path.join(outdir, f"{stem} probe.json")
    L.save_json(report, out_json)
    for i, e in enumerate(report["regions"]):
        print(f"r{i:02d} f{e['in_frame']}-{e['out_frame']}  "
              f"faces={len(e.get('faces', []))} "
              f"cam={'Y' if e.get('cam') else '-'} "
              f"content={'Y' if e.get('content') else '-'} "
              f"{'VOID ' if e.get('void') else ''}-> {e.get('suggest')}")
    print(out_json)


if __name__ == "__main__":
    main()
