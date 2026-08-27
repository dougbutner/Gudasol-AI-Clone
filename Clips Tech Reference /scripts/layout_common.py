#!/usr/bin/env python3
"""Shared vision helpers for layout_probe.py / verify_plan.py.

Needs opencv-python-headless + numpy (the ONLY scripts in the skill that
do). Import failure is handled by the callers with a plain message — the
layout probe/verify layer is optional; the legacy eyeball path still works
without it.
"""
import json
import subprocess
import sys

try:
    import cv2
    import numpy as np
except ImportError:  # callers print the install hint
    cv2 = None
    np = None

PANE_AR = 1080 / 960  # split pane aspect (w/h)
COL_AR = 9 / 16       # crop-mode column aspect


def need_cv():
    if cv2 is None:
        sys.exit("layout probe/verify needs opencv-python-headless + numpy:\n"
                 "    pip install opencv-python-headless\n"
                 "(one-time, ~60MB — or skip the probe layer and use the "
                 "legacy eyeball path)")


def grab_frames(source, fps, frame_nos):
    """Extract exact source frames as BGR arrays via one ffmpeg call each."""
    need_cv()
    out = []
    for fn in frame_nos:
        t = fn / fps
        r = subprocess.run(
            ["ffmpeg", "-nostdin", "-ss", f"{t:.4f}", "-i", source,
             "-frames:v", "1", "-f", "image2pipe", "-vcodec", "png", "-"],
            capture_output=True)
        if r.returncode != 0 or not r.stdout:
            continue
        img = cv2.imdecode(np.frombuffer(r.stdout, np.uint8),
                           cv2.IMREAD_COLOR)
        if img is not None:
            out.append((fn, img))
    return out


YUNET_URL = ("https://github.com/opencv/opencv_zoo/raw/main/models/"
             "face_detection_yunet/face_detection_yunet_2023mar.onnx")
_DETECTOR = None


def _yunet_path():
    import os
    d = os.path.join(os.path.expanduser("~"), ".perfect-clips", "models")
    os.makedirs(d, exist_ok=True)
    p = os.path.join(d, "face_detection_yunet_2023mar.onnx")
    if not os.path.exists(p):
        print("first run — fetching the YuNet face model (~230KB, one-time)",
              file=sys.stderr)
        import urllib.request
        try:
            urllib.request.urlretrieve(YUNET_URL, p + ".part")
            os.replace(p + ".part", p)
        except Exception as e:  # offline: degrade, don't die
            print(f"face model unavailable ({e}) — face checks skipped "
                  "this run; aspect/void fixes still apply", file=sys.stderr)
            return None
    return p


def _detector():
    global _DETECTOR
    if _DETECTOR is None:
        mp = _yunet_path()
        _DETECTOR = (cv2.FaceDetectorYN_create(mp, "", (320, 320),
                                               0.6, 0.3, 5000)
                     if mp else False)
    return _DETECTOR


def detect_faces(img, det_w=960):
    """Face boxes [x,y,w,h] in px (source scale). YuNet handles caps,
    profiles and streamer lighting far better than the old cascades.
    Returns [] when the model is unavailable (offline first run)."""
    det = _detector()
    if det is False:
        return []
    H, W = img.shape[:2]
    s = det_w / W if W > det_w else 1.0
    small = cv2.resize(img, (int(W * s), int(H * s))) if s < 1.0 else img
    det.setInputSize((small.shape[1], small.shape[0]))
    _, faces = det.detect(small)
    boxes = []
    if faces is not None:
        for f in faces:
            x, y, w, h = f[:4]
            boxes.append([int(x / s), int(y / s),
                          int(w / s), int(h / s)])
    return _merge_boxes(boxes)


def _iou(a, b):
    ax2, ay2 = a[0] + a[2], a[1] + a[3]
    bx2, by2 = b[0] + b[2], b[1] + b[3]
    ix = max(0, min(ax2, bx2) - max(a[0], b[0]))
    iy = max(0, min(ay2, by2) - max(a[1], b[1]))
    inter = ix * iy
    union = a[2] * a[3] + b[2] * b[3] - inter
    return inter / union if union else 0.0


def _merge_boxes(boxes, thr=0.35):
    merged = []
    for b in sorted(boxes, key=lambda b: -b[2] * b[3]):
        for m in merged:
            if _iou(b, m) > thr:
                break
        else:
            merged.append(b)
    return merged


def cluster_faces(per_frame):
    """per_frame: list of face-box lists (one per sampled frame). Returns
    clusters [{box, hits}] — box averaged, hits = frames seen."""
    clusters = []
    for boxes in per_frame:
        for b in boxes:
            for c in clusters:
                if _iou(b, c["box"]) > 0.3:
                    n = c["hits"]
                    c["box"] = [(c["box"][i] * n + b[i]) // (n + 1)
                                for i in range(4)]
                    c["hits"] += 1
                    break
            else:
                clusters.append({"box": list(b), "hits": 1})
    clusters.sort(key=lambda c: (-c["hits"], -c["box"][2] * c["box"][3]))
    return clusters


def motion_mask(frames):
    """Combined |diff| mask across sampled frames (uint8 0/255)."""
    if len(frames) < 2:
        return None
    grays = [cv2.GaussianBlur(cv2.cvtColor(f, cv2.COLOR_BGR2GRAY), (5, 5), 0)
             for _, f in frames]
    acc = None
    for a, b in zip(grays, grays[1:]):
        d = cv2.absdiff(a, b)
        acc = d if acc is None else cv2.max(acc, d)
    thr = max(14, float(acc.mean()) + 2 * float(acc.std()))
    _, mask = cv2.threshold(acc, thr, 255, cv2.THRESH_BINARY)
    k = cv2.getStructuringElement(
        cv2.MORPH_RECT, (max(9, mask.shape[1] // 96),) * 2)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, k)
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, k)
    return mask


def bright_mask(img):
    """Structure detector for static scenes (site modals, browser pages):
    regions clearly brighter than the page background. Close-then-open so
    thin text (chat columns) doesn't bridge separate panels together."""
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    med = float(np.median(gray))
    _, mask = cv2.threshold(gray, med + 34, 255, cv2.THRESH_BINARY)
    k = cv2.getStructuringElement(
        cv2.MORPH_RECT, (max(9, gray.shape[1] // 96),) * 2)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, k)
    k2 = cv2.getStructuringElement(
        cv2.MORPH_RECT, (max(5, gray.shape[1] // 160),) * 2)
    return cv2.morphologyEx(mask, cv2.MORPH_OPEN, k2)


def panel_blobs(mask, W, H):
    """Discrete bright PANELS: blobs that don't hug the vertical frame
    edges (chat columns do) and aren't the whole screen."""
    out = []
    for b in blobs(mask, 0.01):
        if b[0] < 0.02 * W or b[0] + b[2] > 0.98 * W:
            continue
        if b[2] * b[3] > 0.85 * W * H:
            continue
        out.append(b)
    return out


def contains(outer, inner, frac=0.8):
    """True when >= frac of inner's area lies inside outer."""
    ix = max(0, min(outer[0] + outer[2], inner[0] + inner[2])
             - max(outer[0], inner[0]))
    iy = max(0, min(outer[1] + outer[3], inner[1] + inner[3])
             - max(outer[1], inner[1]))
    a = inner[2] * inner[3]
    return a > 0 and (ix * iy) / a >= frac


def blobs(mask, min_area_frac=0.004):
    """Connected components as [x,y,w,h] boxes, big→small."""
    if mask is None:
        return []
    n, _, stats, _ = cv2.connectedComponentsWithStats(mask)
    H, W = mask.shape
    out = []
    for i in range(1, n):
        x, y, w, h, area = stats[i]
        if area >= min_area_frac * W * H:
            out.append([int(x), int(y), int(w), int(h)])
    out.sort(key=lambda b: -b[2] * b[3])
    return out


def to_frac(box, W, H):
    return [round(box[0] / W, 4), round(box[1] / H, 4),
            round(box[2] / W, 4), round(box[3] / H, 4)]


def to_px(frac, W, H):
    return [frac[0] * W, frac[1] * H, frac[2] * W, frac[3] * H]


def expand_to_aspect(rect, target_ar, W, H, focus=None):
    """Grow rect [x,y,w,h] (px) to exactly target_ar (w/h) inside WxH.
    Growth only — never trims the original rect, so cover-fill in the
    renderer crops NOTHING. focus=(fx,fy) px biases where the extra room
    goes (face center); default symmetric. Returns new [x,y,w,h]."""
    x, y, w, h = rect
    if w / h < target_ar:            # too tall -> widen
        need = target_ar * h - w
        fx = focus[0] if focus else x + w / 2
        left_share = min(max((fx - x) / w, 0.30), 0.70)
        x2 = x - need * (1 - left_share)
        w2 = w + need
        x2 = min(max(x2, 0), W - w2) if w2 <= W else 0
        if w2 > W:                   # can't reach aspect by widening alone
            w2 = W
            h2 = w2 / target_ar
            y2 = min(max(y + h / 2 - h2 / 2, 0), H - h2)
            return [0, y2, w2, h2]
        return [x2, y, w2, h]
    if w / h > target_ar:            # too wide -> heighten
        need = w / target_ar - h
        fy = focus[1] if focus else y + h / 2
        top_share = min(max((fy - y) / h, 0.30), 0.70)
        y2 = y - need * (1 - top_share)
        h2 = h + need
        y2 = min(max(y2, 0), H - h2) if h2 <= H else 0
        if h2 > H:
            h2 = H
            w2 = h2 * target_ar
            x2 = min(max(x + w / 2 - w2 / 2, 0), W - w2)
            return [x2, 0, w2, h2]
        return [x, y2, w, h2]
    return [x, y, w, h]


def visible_after_cover(rect, target_ar):
    """The sub-rect of rect that survives the renderer's cover-fill center
    crop into a pane of target_ar. rect px -> visible rect px."""
    x, y, w, h = rect
    if w / h > target_ar:      # wider than pane -> sides crop
        vw = h * target_ar
        return [x + (w - vw) / 2, y, vw, h]
    vh = w / target_ar         # taller than pane -> top/bottom crop
    return [x, y + (h - vh) / 2, w, vh]


def point_in(px_pt, rect, margin=0.0):
    x, y, w, h = rect
    mx, my = w * margin, h * margin
    return (x + mx <= px_pt[0] <= x + w - mx and
            y + my <= px_pt[1] <= y + h - my)


def load_json(p):
    return json.load(open(p, encoding="utf-8"))


def save_json(obj, p):
    json.dump(obj, open(p, "w", encoding="utf-8"), indent=1)
