#!/usr/bin/env python3
"""Verify + fix a layout plan against measured reality BEFORE rendering.
Frame boundaries are never touched (frame-exact law). Modes are only ever
DEMOTED toward honesty (split/crop/zoom -> full) — promotion is the model's
judgment, demotion is safety. Rects are corrected and aspect-expanded so
the renderer's cover-fill crops NOTHING.

    python3 verify_plan.py "clip NN cuts.json" \
        "clip NN layout plan.json" --probe "clip NN probe.json" --fix \
        [--panes DIR]

--panes DIR additionally exports one preview PNG per split content pane /
zoom zone — the EXACT post-cover crop the renderer will produce, at pane
resolution. These previews feed the FRESH-EYES GATE (SKILL.md step 8.5):
a second agent with zero context looks at each pane and says what it
sees; an unclear pane demotes its region to `full`. The verifier checks
geometry and faces — it cannot judge whether a pane READS; that takes
eyes.

Checks per mode:
    split  inset vs measured cam (IoU < 0.35 -> replace with measured);
           inset expanded to pane aspect CENTERED on the detected face and
           still containing the cam; content expanded to pane aspect
           (growth only — reveals context, never trims); face must sit in
           the pane's visible area or the region demotes (crop if the
           scene is really a full-frame person, else full); a VOID content
           pane demotes the region.
    crop   measured face must sit inside the 9:16 column (12% margin) —
           else face_x is corrected to the measured center; no full-frame
           face at all -> full.
    zoom   a zone that IS the cam (IoU >= 0.5) is legal — face rules
           apply; other zones must not be void and get widened to aspect
           >= 1.0 (tall zones overflow the canvas when width-fit).
    full   always passes.

--fix rewrites the plan in place (original saved next to it as
"<plan>.pre-verify"); without it the script only reports. A "verify
report.json" lands next to the plan either way. Exit code 0 = plan is
render-ready (after fixes); 2 = structural problems the model must
re-decide (missing probe regions, unfixable geometry)."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import layout_common as L  # noqa: E402


def flag(name, default):
    return sys.argv[sys.argv.index(name) + 1] if name in sys.argv else default


def iou(a, b):
    ax2, ay2 = a[0] + a[2], a[1] + a[3]
    bx2, by2 = b[0] + b[2], b[1] + b[3]
    ix = max(0.0, min(ax2, bx2) - max(a[0], b[0]))
    iy = max(0.0, min(ay2, by2) - max(a[1], b[1]))
    inter = ix * iy
    union = a[2] * a[3] + b[2] * b[3] - inter
    return inter / union if union else 0.0


def clamp(v, lo, hi):
    return max(lo, min(v, hi))


def inset_window(cam, face, W, H):
    """Pane-aspect window for the streamer pane, anchored on the FACE.
    The measured cam rect is a motion footprint (the person's moving
    parts), not the cam panel — so the window is sized from the face
    (panel height ~= 3.3 face heights, the streamer-overlay norm),
    clamped sane, and bottom-anchored when the cam hugs the frame bottom
    (corner cams end at the screen edge). All px."""
    cx, cy, cw, ch = cam
    fh = face[3] if face else ch * 0.35
    fx = face[0] + face[2] / 2 if face else cx + cw / 2
    fy = face[1] + face[3] / 2 if face else cy + ch / 2
    h2 = clamp(fh * 3.3, 0.22 * H, 0.36 * H)
    h2 = max(h2, ch)                   # never smaller than what moves
    w2 = h2 * L.PANE_AR
    x2 = clamp(fx - w2 / 2, 0, max(0, W - w2))
    if cy + ch >= 0.96 * H:            # corner cam -> pin to screen bottom
        y2 = H - h2
    else:
        y2 = clamp(fy - 0.42 * h2, 0, max(0, H - h2))
    return [x2, y2, min(w2, W), min(h2, H)]


def face_visible(face, window, ar):
    if not face:
        return False
    vis = L.visible_after_cover(window, ar)
    fc = (face[0] + face[2] / 2, face[1] + face[3] / 2)
    return L.point_in(fc, vis, margin=0.06)


def main():
    cuts = L.load_json(sys.argv[1])
    plan_path = sys.argv[2]
    plan = L.load_json(plan_path)
    probe_path = flag("--probe", None)
    probe = L.load_json(probe_path) if probe_path else {"regions": []}
    fix = "--fix" in sys.argv
    W, H = cuts["width"], cuts["height"]

    pmap = {(p["in_frame"], p["out_frame"]): p for p in probe["regions"]}
    report, structural = [], False

    for i, r in enumerate(plan["regions"]):
        key = (r["in_frame"], r["out_frame"])
        p = pmap.get(key)
        mode = r.get("mode", "full")
        notes = []
        if p is None:
            report.append({"region": i, "mode": mode, "verdict": "NO-PROBE",
                           "notes": ["no probe data for this region — "
                                     "re-run layout_probe.py"]})
            structural = True
            continue

        cam = L.to_px(p["cam"]["rect"], W, H) if p.get("cam") else None
        cam_face = (L.to_px(p["cam"]["face"], W, H)
                    if p.get("cam") and p["cam"].get("face") else None)
        full_x = p.get("full_face_x")

        def demote(why):
            notes.append(why)
            if full_x is not None:
                r.clear()
                r.update({"mode": "crop", "face_x": full_x,
                          "in_frame": key[0], "out_frame": key[1]})
                notes.append(f"demoted -> crop face_x={full_x} "
                             "(scene is a full-frame person)")
            else:
                r.clear()
                r.update({"mode": "full",
                          "in_frame": key[0], "out_frame": key[1]})
                notes.append("demoted -> full")

        hand = r.get("rects_from") == "still"
        if mode == "split":
            if p.get("void") and not hand:
                demote("content pane is VOID (screen idle)")
            elif cam is None and not p.get("faces") and not hand:
                demote("no cam / no face measured — split unverifiable")
            else:
                inset = L.to_px(r["inset"], W, H)
                seed, seed_face = inset, cam_face
                if cam is not None and not hand:
                    ov = iou(r["inset"], p["cam"]["rect"])
                    if ov < 0.05:
                        # the plan and the probe are looking at DIFFERENT
                        # objects — replacing either would be a guess
                        # (field report 2026-08-22: probe mistook a static
                        # AI portrait for the cam and clobbered a correct
                        # hand-drawn plan). Structural: human re-decides.
                        report.append({
                            "region": i, "mode": "split",
                            "verdict": "STRUCTURAL",
                            "notes": [
                                f"plan inset {r['inset']} and measured cam "
                                f"{p['cam']['rect']} are different objects "
                                f"(IoU {ov:.2f}) — re-probe, or keep the "
                                "hand-drawn rects by adding "
                                "\"rects_from\": \"still\" to this region"]})
                        structural = True
                        continue
                    if ov < 0.35:
                        notes.append(
                            f"inset corrected: plan {r['inset']} -> "
                            f"measured cam {p['cam']['rect']} "
                            f"(IoU {ov:.2f})")
                    seed = cam
                elif hand:
                    notes.append("rects_from=still: plan inset honoured "
                                 "(aspect-expand only)")
                    if cam_face and not L.point_in(
                            (cam_face[0] + cam_face[2] / 2,
                             cam_face[1] + cam_face[3] / 2), inset):
                        seed_face = None
                win = inset_window(seed, seed_face, W, H)
                r["inset"] = L.to_frac([int(v) for v in win], W, H)
                if hand and seed_face is None:
                    notes.append("face check skipped (hand-drawn rects; "
                                 "the probe's face is elsewhere)")
                elif cam_face and not face_visible(cam_face, win,
                                                   L.PANE_AR):
                    demote("face outside the streamer pane after centering")
                if r.get("mode") == "split":
                    content = L.to_px(r.get("content",
                                            [0.0, 0.0, 1.0, 1.0]), W, H)
                    grown = L.expand_to_aspect(content, L.PANE_AR, W, H)
                    if [round(v) for v in grown] != [round(v)
                                                     for v in content]:
                        notes.append(
                            f"content expanded to pane aspect: "
                            f"{r.get('content')} -> "
                            f"{L.to_frac(grown, W, H)}")
                    r["content"] = L.to_frac(grown, W, H)

        elif mode == "crop":
            if full_x is None:
                demote("no full-frame face measured — crop shows a person "
                       "that isn't there")
            else:
                col_w = H * L.COL_AR
                cx = clamp(r.get("face_x", 0.5) * W, col_w / 2, W - col_w / 2)
                col = [cx - col_w / 2, 0, col_w, H]
                fpx = full_x * W
                if not (col[0] + col_w * 0.12 <= fpx
                        <= col[0] + col_w * 0.88):
                    notes.append(f"face_x corrected {r.get('face_x')} -> "
                                 f"{full_x} (face was leaving the column)")
                    r["face_x"] = full_x

        elif mode == "zoom":
            zone = L.to_px(r["zone"], W, H)
            # zoom-on-cam when the zone IS or CONTAINS the cam (containment,
            # not IoU — a snapped window is bigger than the raw cam rect and
            # must still be recognized on re-verify)
            on_cam = not hand and cam is not None and (
                iou(r["zone"], p["cam"]["rect"]) >= 0.5
                or L.contains(zone, cam, 0.7))
            if hand:
                notes.append("rects_from=still: zone honoured "
                             "(tall-widen only)")
                if zone[2] / zone[3] < 1.0:
                    grown = L.expand_to_aspect(zone, 1.0, W, H)
                    r["zone"] = L.to_frac(grown, W, H)
                    notes.append("tall zone widened to 1:1+")
            elif on_cam:
                win = inset_window(cam, cam_face, W, H)
                r["zone"] = L.to_frac([int(v) for v in win], W, H)
                notes.append("zoom-on-cam: zone snapped to measured cam")
            elif p.get("void"):
                demote("zoom zone is VOID")
            else:
                if zone[2] / zone[3] < 1.0:
                    grown = L.expand_to_aspect(zone, 1.0, W, H)
                    notes.append(f"tall zone widened to 1:1+ "
                                 f"({L.to_frac(grown, W, H)})")
                    r["zone"] = L.to_frac(grown, W, H)

        verdict = ("DEMOTED" if any("demoted" in n for n in notes)
                   else "FIXED" if notes else "OK")
        report.append({"region": i, "mode": r.get("mode", "full"),
                       "verdict": verdict, "notes": notes})

    panes_dir = flag("--panes", None)
    if panes_dir and not structural:
        import cv2
        os.makedirs(panes_dir, exist_ok=True)
        stem = os.path.basename(plan_path).replace(
            " layout plan.json", "")
        fps = cuts["fps"]
        n_out = 0
        for i, r in enumerate(plan["regions"]):
            mode = r.get("mode", "full")
            if mode == "split":
                # BOTH panes — a wrong streamer inset is exactly what
                # fresh eyes catch ("that's a different person"); exporting
                # only the content pane hid one in the field (2026-08-22)
                todo = [(r["content"], "split-content"),
                        (r["inset"], "split-streamer")]
            elif mode == "zoom":
                todo = [(r["zone"], "zoom")]
            else:
                continue
            mid = (r["in_frame"] + r["out_frame"]) // 2
            frames = L.grab_frames(cuts["source"], fps, [mid])
            if not frames:
                continue
            img = frames[0][1]
            for rect, label in todo:
                pane_w, pane_h = 1080, 960
                x, y, w, h = [int(v) for v in L.to_px(rect, W, H)]
                crop = img[max(0, y):y + h, max(0, x):x + w]
                if crop.size == 0:
                    continue
                s = max(pane_w / crop.shape[1], pane_h / crop.shape[0])
                crop = cv2.resize(crop, (int(crop.shape[1] * s),
                                         int(crop.shape[0] * s)))
                cy = (crop.shape[0] - pane_h) // 2
                cx = (crop.shape[1] - pane_w) // 2
                crop = crop[cy:cy + pane_h, cx:cx + pane_w]
                crop = cv2.resize(crop, (540, 480))
                cv2.imwrite(os.path.join(
                    panes_dir, f"{stem} pane r{i:02d} {label}.png"),
                    crop)
                n_out += 1
        print(f"{n_out} pane previews -> {panes_dir}")

    rep_path = plan_path.replace(".json", "") + " verify report.json"
    # never let the report path collide with the plan
    if rep_path == plan_path:
        rep_path = plan_path + ".verify.json"
    L.save_json({"regions": report}, rep_path)

    if fix and not structural:
        backup = plan_path + ".pre-verify"
        if not os.path.exists(backup):
            os.replace(plan_path, backup)
        L.save_json(plan, plan_path)

    for e in report:
        tail = ("  |  " + "; ".join(e["notes"])) if e["notes"] else ""
        print(f"r{e['region']:02d} {e['mode']:<5} {e['verdict']}{tail}")
    print(("plan rewritten (backup at *.pre-verify)" if fix and not structural
           else "report only — re-run with --fix to apply") +
          f"  -> {os.path.basename(rep_path)}")
    sys.exit(2 if structural else 0)


if __name__ == "__main__":
    main()
