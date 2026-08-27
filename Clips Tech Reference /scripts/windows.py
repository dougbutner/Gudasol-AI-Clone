#!/usr/bin/env python3
"""Build the analysis layer for perfect-clips: an indexed word file plus
segment-snapped candidate windows with density scores.

Usage:
    python3 windows.py <whisper_json> <map_json> [--outdir DIR]
                       [--win 90] [--overlap 30]

Outputs (in --outdir, default: alongside the map):
  words.jsonl   one word per line; LINE NUMBER == WORD INDEX (1-based).
                {"i":12,"w":"race,","s":16.38,"e":16.71,"b":0}
                b = speech-map block id (-1 when the word falls in no block).
  windows.json  {"meta":{...},"windows":[{"id":"w01","start":..,"end":..,
                "first_word":..,"last_word":..,"density":..,"text":"..."}]}

Windows are snapped to whisper segment boundaries (grown segment by segment
toward <win> seconds, hard cap 1.25x) so a sentence is never split mid-window;
the next window starts at the first segment after (end - <overlap>s).
Density is a no-LLM pre-rank (words/sec + speech continuity, 0-90ish) for long
VODs: read high-density windows first. It orders reading; it never judges.
"""
import json
import os
import sys


def flag(name, default):
    return sys.argv[sys.argv.index(name) + 1] if name in sys.argv else default


def main():
    whisper_path, map_path = sys.argv[1], sys.argv[2]
    outdir = flag("--outdir", os.path.dirname(os.path.abspath(map_path)) or ".")
    win_len = float(flag("--win", "90"))
    overlap = float(flag("--overlap", "30"))
    os.makedirs(outdir, exist_ok=True)

    tx = json.load(open(whisper_path, encoding="utf-8"))
    mp = json.load(open(map_path, encoding="utf-8"))
    blocks = mp["blocks"]

    # ---- flatten words; interpolate missing timestamps (whisperx skips
    # numerals etc.) so every word carries usable times ----
    raw = []
    for seg in tx.get("segments", []):
        for w in seg.get("words", []):
            raw.append({"w": (w.get("word") or "").strip(),
                        "s": w.get("start"), "e": w.get("end"),
                        "seg_start": seg["start"]})
    for i, w in enumerate(raw):
        if w["s"] is None:
            w["s"] = raw[i - 1]["e"] if i and raw[i - 1]["e"] is not None \
                else w["seg_start"]
        if w["e"] is None:
            nxt = next((raw[j]["s"] for j in range(i + 1, len(raw))
                        if raw[j]["s"] is not None), None)
            w["e"] = min(nxt, w["s"] + 0.5) if nxt is not None else w["s"] + 0.3

    # ---- block assignment (mirrors speech_map's text tolerance) ----
    def block_of(t):
        for b in blocks:
            if b["start"] - 0.15 <= t < b["end"] + 0.05:
                return b["i"]
        return -1

    words = []
    for i, w in enumerate(raw, 1):
        words.append({"i": i, "w": w["w"], "s": round(w["s"], 3),
                      "e": round(w["e"], 3), "b": block_of(w["s"])})
    with open(os.path.join(outdir, "words.jsonl"), "w", encoding="utf-8") as f:
        for w in words:
            f.write(json.dumps(w, ensure_ascii=False) + "\n")

    # ---- segment-snapped windows ----
    segs = [(s["start"], s["end"]) for s in tx.get("segments", [])]
    spans, si = [], 0
    while si < len(segs):
        w_start = segs[si][0]
        sj = si
        while sj + 1 < len(segs) and segs[sj][1] - w_start < win_len \
                and segs[sj + 1][1] - w_start <= win_len * 1.25:
            sj += 1
        w_end = segs[sj][1]
        spans.append((w_start, w_end))
        if sj + 1 >= len(segs):
            break
        target = w_end - overlap
        nxt = next((k for k in range(si + 1, len(segs))
                    if segs[k][0] >= target), sj + 1)
        si = max(nxt, si + 1)

    out_windows = []
    for n, (ws, we) in enumerate(spans, 1):
        in_win = [w for w in words if ws - 0.01 <= w["s"] < we]
        if not in_win:
            continue
        dur = max(we - ws, 0.001)
        speech = sum(max(0.0, min(w["e"], we) - w["s"]) for w in in_win)
        wps = len(in_win) / dur
        density = round(min(wps / 3.2, 1.3) * 45 + min(speech / dur, 1.0) * 45, 1)
        out_windows.append({
            "id": f"w{n:02d}", "start": round(ws, 2), "end": round(we, 2),
            "first_word": in_win[0]["i"], "last_word": in_win[-1]["i"],
            "density": density,
            "text": " ".join(w["w"] for w in in_win)})

    meta = {"source": mp.get("source"), "fps": mp.get("fps"),
            "width": mp.get("width"), "height": mp.get("height"),
            "samplerate": mp.get("samplerate"), "duration": mp.get("duration"),
            "word_count": len(words), "window_count": len(out_windows)}
    json.dump({"meta": meta, "windows": out_windows},
              open(os.path.join(outdir, "windows.json"), "w", encoding="utf-8"),
              indent=1, ensure_ascii=False)

    print(f"{len(words)} words -> words.jsonl (line N == word index N)")
    print(f"{len(out_windows)} windows -> windows.json")
    for w in sorted(out_windows, key=lambda x: -x["density"])[:10]:
        print(f"  {w['id']}  {w['start']:7.1f}-{w['end']:7.1f}  "
              f"density {w['density']:5.1f}  {w['text'][:70]}")


if __name__ == "__main__":
    main()
