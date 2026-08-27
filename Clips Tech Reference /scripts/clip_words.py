#!/usr/bin/env python3
"""Map source word timings onto ONE clip's OUTPUT timeline and emit the
Remotion caption word list plus a readable SRT caption track.

The SRT is chunked from the WORD timings, not from the keep-segments: a
segment-level cue on a four-minute long-form clip would be one two-minute
block of text, which no player and no YouTube upload can use. Cues break on
a real pause, on sentence punctuation, or at the length caps below — the
ordinary subtitle shape.

Handles rearrangement for free: it walks the cuts list in OUTPUT order, so a
teaser's words are emitted twice — once as the cold open, once where the line
lands naturally in the body.

Usage:
    python3 clip_words.py <clip_cuts_json> <words_jsonl>
                          [--out-words words.json] [--out-srt clip.srt]
"""
import json
import os
import sys


def flag(name, default):
    return sys.argv[sys.argv.index(name) + 1] if name in sys.argv else default


# WhisperX occasionally force-aligns a word across an alert/music span and
# reports it seconds long (19.7s seen in the field, 2026-08-24: a 16.6s
# frozen "EVERY" chip shipped before this guard). No spoken word lasts
# GLITCH_DUR; anything over it displays for CAP_DUR and the rest is dead
# air, which is honest -- nothing was being said. Clamping HERE fixes the
# burned chip and the SRT cue in one place (both consume this word list).
GLITCH_DUR = 4.0
CAP_DUR = 2.5

MAX_WORDS = 7        # a phone-legible line
HARD_WORDS = 10      # the cap even a dangling word cannot exceed
MAX_CUE_SEC = 5.0    # nobody reads one cue for longer
GAP_BREAK = 0.7      # a pause this long starts a new thought
MIN_CUE_SEC = 0.8    # a cue that flashes is worse than a slow one

# Breaking a line right after one of these strands it from the word it
# belongs to ("...right THE / fuck now"). The word cap defers past them.
DANGLERS = {"a", "an", "the", "my", "your", "his", "her", "its", "our",
            "their", "to", "of", "in", "on", "at", "for", "with", "from",
            "and", "or", "but", "is", "was", "that", "this"}


def build_cues(words):
    """Output-timeline word list -> SRT cues."""
    cues, cur = [], []
    for i, w in enumerate(words):
        cur.append(w)
        nxt = words[i + 1] if i + 1 < len(words) else None
        text = (w["text"] or "").strip()
        span = w["end"] - cur[0]["start"]
        bare = text.lower().strip(".,?!;:\"'")
        dangling = bare in DANGLERS and not text.endswith((".", "?", "!", ","))
        cap = len(cur) >= (HARD_WORDS if dangling else MAX_WORDS)
        brk = (nxt is None
               or cap
               or span >= MAX_CUE_SEC
               or (nxt["start"] - w["end"]) > GAP_BREAK
               or (text.endswith((".", "?", "!")) and len(cur) >= 3))
        if brk:
            start, end = cur[0]["start"], w["end"]
            if end - start < MIN_CUE_SEC:
                end = start + MIN_CUE_SEC
            if nxt is not None:
                end = min(end, nxt["start"])
            if end > start:
                cues.append((start, end,
                             " ".join((x["text"] or "").strip()
                                      for x in cur).strip()))
            cur = []
    return cues


def ts(seconds):
    ms = int(round(seconds * 1000))
    return (f"{ms // 3600000:02d}:{ms % 3600000 // 60000:02d}:"
            f"{ms % 60000 // 1000:02d},{ms % 1000:03d}")


def main():
    spec = json.load(open(sys.argv[1], encoding="utf-8"))
    base = os.path.splitext(sys.argv[1])[0]
    out_words = flag("--out-words", base + " words.json")
    out_srt = flag("--out-srt", base + ".srt")
    fps = spec["fps"]

    words = []
    with open(sys.argv[2], encoding="utf-8") as f:
        for line in f:
            if line.strip():
                words.append(json.loads(line))

    caption_words, offset = [], 0.0
    for n, c in enumerate(spec["clips"], 1):
        t_in, t_out = c["in_frame"] / fps, c["out_frame"] / fps
        dur = t_out - t_in
        for w in words:
            if t_in - 0.02 <= w["s"] < t_out - 0.005 and w["w"]:
                start = max(offset + (w["s"] - t_in), offset)
                end = min(offset + (w["e"] - t_in), offset + dur - 0.001)
                if end - start > GLITCH_DUR:
                    end = start + CAP_DUR
                if end > start:
                    caption_words.append({"text": w["w"],
                                          "start": round(start, 3),
                                          "end": round(end, 3)})
        offset += dur

    srt_blocks = [f"{n}\n{ts(a)} --> {ts(b)}\n{t}\n"
                  for n, (a, b, t) in enumerate(build_cues(caption_words), 1)]

    json.dump(caption_words, open(out_words, "w", encoding="utf-8"),
              indent=1, ensure_ascii=False)
    open(out_srt, "w", encoding="utf-8").write("\n".join(srt_blocks))
    print(f"{len(caption_words)} caption words -> {out_words}")
    print(f"{len(srt_blocks)} srt cues -> {out_srt}")


if __name__ == "__main__":
    main()
