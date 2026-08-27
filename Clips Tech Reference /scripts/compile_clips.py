#!/usr/bin/env python3
"""Validate model-proposed clip candidates (word-index contract) and compile
each survivor into a waveform-snapped per-clip cuts JSON.

Usage:
    python3 compile_clips.py <candidates_json> <words_jsonl> <map_json>
                             [--outdir DIR] [--min-dur 15] [--max-dur 60]
                             [--stem "my video"] [--longform]

--longform enforces the long-form law (rule 11) mechanically: hook_mode
teaser is refused (the cold-open repeat is a swipe-feed device), and two
candidates may not draw on the same stretch of source — overlapping word
ranges are the same video twice, so the lower-scoring one is rejected.
Duration defaults shift to 120-360s; --min-dur/--max-dur still override.

Contract per candidate (all word indices 1-BASED and INCLUSIVE — they equal
line numbers in words.jsonl):
  {"title": str,
   "hook_mode": "natural" | "teaser",
   "teaser": {"start_word": i, "end_word": j},        # required iff teaser
   "segments": [{"start_word": i, "end_word": j}, ...],  # ordered keep-ranges
   "hook_quote": "verbatim first words of the OUTPUT",
   "scores": {"hook":1-25,"engagement":1-25,"value":1-25,"shareability":1-25},
   "why": str}
  Extra fields (titles, descriptions, rank_hint...) pass through to the manifest.

Boundary law — the LLM decides WHAT survives, the waveform decides THE FRAME:
  - boundary on a speech-block edge  -> block onset (-30dB, floor) in;
                                        block end (-38dB, ceil +1 frame) out
  - mid-block boundary (internal filler cut) -> force-aligned word time (the
    one place word timestamps rule), 60ms lead / 100ms tail, no +1 frame
A teaser becomes clips[0] and repeats naturally inside the body — intentional.

Rejects are reported with reasons; fix candidates.json and re-run. Never
hand-edit the emitted cuts files.
"""
import json
import math
import os
import re
import sys

BANNED_OPENERS = {"and", "but", "so", "because", "or", "that", "which", "if",
                  "when", "while", "though", "since", "as", "for", "also",
                  "plus", "then", "actually", "basically", "like", "really",
                  "just", "maybe", "cause", "uh", "um", "yeah", "okay", "ok",
                  "right", "well"}
BANNED_PAIRS = {("i", "mean"), ("you", "know")}


def norm_words(s):
    return re.sub(r"[^a-z0-9' ]", " ", s.lower()).split()


def flag(name, default):
    return sys.argv[sys.argv.index(name) + 1] if name in sys.argv else default


def main():
    if len(sys.argv) < 4:
        sys.exit(__doc__.strip())
    cand_path, words_path, map_path = sys.argv[1], sys.argv[2], sys.argv[3]
    outdir = flag("--outdir", os.path.dirname(os.path.abspath(cand_path)) or ".")
    longform = "--longform" in sys.argv
    min_dur = float(flag("--min-dur", "120" if longform else "15"))
    max_dur = float(flag("--max-dur", "360" if longform else "60"))
    os.makedirs(outdir, exist_ok=True)

    mp = json.load(open(map_path, encoding="utf-8"))
    fps = mp["fps"]
    blocks = {b["i"]: b for b in mp["blocks"]}
    words = {}
    with open(words_path, encoding="utf-8") as f:
        for line in f:
            if line.strip():
                w = json.loads(line)
                words[w["i"]] = w
    n_words = len(words)
    stem = flag("--stem", os.path.splitext(os.path.basename(
        mp.get("source", "clip")))[0])

    block_first, block_last = {}, {}
    for i in sorted(words):
        b = words[i]["b"]
        if b >= 0:
            block_first.setdefault(b, i)
            block_last[b] = i

    def resolve(sw_i, ew_i):
        """(start_word, end_word) -> (t_in, t_out, in_frame, out_frame)."""
        sw, ew = words[sw_i], words[ew_i]
        b_s, b_e = sw["b"], ew["b"]
        if b_s >= 0 and block_first.get(b_s) == sw_i:
            t_in = blocks[b_s]["onset"]
        else:
            prev_e = words[sw_i - 1]["e"] if sw_i - 1 in words else 0.0
            t_in = max(sw["s"] - 0.06, prev_e, 0.0)
        if b_e >= 0 and block_last.get(b_e) == ew_i:
            t_out = blocks[b_e]["end"]
            out_frame = math.ceil(t_out * fps) + 1
        else:
            nxt_s = words[ew_i + 1]["s"] if ew_i + 1 in words \
                else ew["e"] + 1.0
            t_out = min(ew["e"] + 0.10, max(nxt_s - 0.02, ew["e"]))
            out_frame = math.ceil(t_out * fps)
        in_frame = math.floor(t_in * fps)
        if out_frame <= in_frame:
            out_frame = in_frame + 1
        return t_in, t_out, in_frame, out_frame

    def seg_text(sw_i, ew_i):
        return " ".join(words[i]["w"] for i in range(sw_i, ew_i + 1)
                        if i in words)

    cands = json.load(open(cand_path, encoding="utf-8"))["clips"]
    manifest, rejects = [], []

    def score_of(c):
        sc = c.get("scores", {})
        return sum(int(sc.get(k2, 0)) for k2 in
                   ("hook", "engagement", "value", "shareability"))


    for n, c in enumerate(cands, 1):
        reasons, warnings = [], []
        segs = c.get("segments") or []
        teaser = c.get("teaser")
        hook_mode = c.get("hook_mode", "natural")

        if longform and hook_mode == "teaser":
            reasons.append("long-form takes no teaser -- at this length the "
                           "cold-open repeat reads as a mistake; open "
                           "naturally or skip the clip")

        # structural checks -- and reject NOW on any failure: everything
        # past this point indexes segment keys directly, and a malformed
        # segment used to crash the whole compile at the ordering check
        # instead of rejecting one candidate (review 2026-08-24)
        for s in segs + ([teaser] if teaser else []):
            if not isinstance(s, dict) or not (
                    1 <= s.get("start_word", 0)
                    <= s.get("end_word", 0) <= n_words):
                reasons.append(f"bad word range {s}")
        if not segs:
            reasons.append("no segments")
        if reasons:
            rejects.append({"title": c.get("title", f"candidate {n}"),
                            "reasons": reasons})
            continue
        for a, b in zip(segs, segs[1:]):
            if b["start_word"] <= a["end_word"]:
                reasons.append("segments overlap or are out of order")

        # NOTE: word-contiguous segments (end N, start N+1) are legitimate
        # and common -- when N ends a speech block and N+1 opens the next,
        # the material between them is SILENCE, and cutting dead air is the
        # whole point. Never merge on word adjacency. The only dishonest
        # join is one where the resolved FRAMES overlap, handled below.
        if hook_mode == "teaser":
            if not teaser:
                reasons.append("hook_mode=teaser but no teaser range")
            elif not any(s["start_word"] <= teaser["start_word"]
                         and teaser["end_word"] <= s["end_word"] for s in segs):
                reasons.append("teaser must sit INSIDE one kept segment "
                               "(it repeats there)")
        if reasons:
            rejects.append({"title": c.get("title", f"candidate {n}"),
                            "reasons": reasons})
            continue

        # opening words = teaser text when teaser, else first segment
        open_range = teaser if hook_mode == "teaser" else segs[0]
        opening = norm_words(seg_text(open_range["start_word"],
                                      open_range["end_word"]))
        quote = norm_words(c.get("hook_quote", ""))
        k = min(3, len(quote), len(opening))
        if k == 0 or opening[:k] != quote[:k]:
            reasons.append(
                f"hook_quote mismatch: clip opens '{' '.join(opening[:5])}' "
                f"but hook_quote says '{' '.join(quote[:5])}'")
        if opening and opening[0] in BANNED_OPENERS:
            reasons.append(f"opens on continuation token '{opening[0]}' -- "
                           "move the start")
        if len(opening) > 1 and (opening[0], opening[1]) in BANNED_PAIRS:
            reasons.append(f"opens on '{opening[0]} {opening[1]}' -- "
                           "move the start")

        # teaser duration
        clips_out = []
        teaser_dur = 0.0
        if hook_mode == "teaser":
            t_in, t_out, fi, fo = resolve(teaser["start_word"],
                                          teaser["end_word"])
            teaser_dur = (fo - fi) / fps
            if not 1.0 <= teaser_dur <= 4.0:
                reasons.append(f"teaser is {teaser_dur:.1f}s "
                               "(needs 1.5-3.5s, hard bounds 1-4)")
            clips_out.append({"in_frame": fi, "out_frame": fo,
                              "text": seg_text(teaser["start_word"],
                                               teaser["end_word"]),
                              "teaser": True})

        # The boundary law pads each edge (block end ceil +1 frame out, word
        # time -60ms in), so two segments cut close together can resolve into
        # each other by a frame or two. A frame served twice is a stutter at
        # the join -- clamp the later segment up to the earlier one's out
        # frame and say so. The teaser is exempt: its repeat is the point,
        # and it lives outside this loop.
        core = 0.0
        prev_out = None
        for s in segs:
            t_in, t_out, fi, fo = resolve(s["start_word"], s["end_word"])
            if prev_out is not None and fi < prev_out:
                clamp_n = prev_out - fi
                fi = prev_out
                if fo - fi < 3:
                    # the whole segment vanished into the clamp -- that is
                    # not padding overlap, it is glitched word timestamps
                    # (non-monotonic alignment); a 1-frame flash is a
                    # defect, not a join
                    reasons.append(
                        f"segment starting at word {s['start_word']} "
                        f"collapses to {max(fo - fi, 0)} frame(s) after a "
                        f"{clamp_n}-frame join clamp -- word timestamps "
                        "here look glitched; rework the boundary")
                    break
                warnings.append(f"join clamped {clamp_n} frame(s): "
                                f"segment starting at word {s['start_word']} "
                                "resolved back into the previous segment")
            prev_out = fo
            core += (fo - fi) / fps
            clips_out.append({"in_frame": fi, "out_frame": fo,
                              "text": seg_text(s["start_word"],
                                               s["end_word"])})
        if core < min_dur * 0.9:
            reasons.append(f"core {core:.1f}s under min {min_dur:.0f}s")
        if core > max_dur * 1.08:
            reasons.append(f"core {core:.1f}s over max {max_dur:.0f}s -- "
                           "cut filler with segments")
        if reasons:
            rejects.append({"title": c.get("title", f"candidate {n}"),
                            "reasons": reasons})
            continue

        total = score_of(c)
        fname = f"clip {n:02d} cuts.json"
        spec = {"source": mp["source"], "fps": fps,
                "width": mp["width"], "height": mp["height"],
                "samplerate": mp.get("samplerate", 48000),
                "source_duration": mp["duration"],
                "sequence_name": f"{stem} clip {n:02d}",
                "output": "", "clips": clips_out}
        json.dump(spec, open(os.path.join(outdir, fname), "w",
                             encoding="utf-8"), indent=1, ensure_ascii=False)
        entry = dict(c)
        entry.update({"n": n, "file": fname, "total_score": total,
                      "core_dur": round(core, 2),
                      "teaser_dur": round(teaser_dur, 2),
                      "total_dur": round(core + teaser_dur, 2),
                      "warnings": warnings})
        manifest.append(entry)

    # Long-form diversity is by STORY (rule 11): two clips drawing on the
    # same stretch of source are the same video twice. Filtered HERE, after
    # validation, over fully-compiled candidates only -- greedy by score,
    # losers' cuts files deleted. A pre-pass version let a candidate that
    # was itself doomed (teaser, bad ranges, duration...) kill a valid
    # neighbour before dying (review 2026-08-24); post-filtering makes that
    # impossible for every doom class at once. Ties keep the earlier
    # candidate. Deterministic.
    if longform and manifest:
        manifest.sort(key=lambda e: (-e["total_score"], e["n"]))
        kept = []
        for e in manifest:
            a0 = min(s2["start_word"] for s2 in e["segments"])
            a1 = max(s2["end_word"] for s2 in e["segments"])
            win = next((k for k in kept
                        if k["_span"][0] <= a1 and a0 <= k["_span"][1]), None)
            if win is None:
                e["_span"] = (a0, a1)
                kept.append(e)
            else:
                try:
                    os.remove(os.path.join(outdir, e["file"]))
                except OSError:
                    pass
                rejects.append({
                    "title": e.get("title", f"candidate {e['n']}"),
                    "reasons": [
                        f"long-form overlap: words {a0}-{a1} share source "
                        f"with candidate {win['n']} "
                        f"({win.get('title', '')[:32]}) -- same stretch "
                        "twice; move it or drop it"]})
        for e in kept:
            e.pop("_span", None)
        manifest = kept

    manifest.sort(key=lambda e: -e["total_score"])
    json.dump({"clips": manifest, "rejects": rejects},
              open(os.path.join(outdir, "manifest.json"), "w",
                   encoding="utf-8"), indent=1, ensure_ascii=False)

    print(f"{len(manifest)} compiled, {len(rejects)} rejected "
          f"-> manifest.json")
    for e in manifest:
        tag = "LONG" if longform else             ("TEASER" if e.get("hook_mode") == "teaser" else "natural")
        print(f"  [{e['n']:02d}] {e['total_score']:3d}/100  "
              f"{e['total_dur']:5.1f}s  {tag:7s}  {e.get('title', '')[:48]}")
    for r in rejects:
        print(f"  REJECT: {r['title'][:40]} — {'; '.join(r['reasons'])}")


if __name__ == "__main__":
    main()
