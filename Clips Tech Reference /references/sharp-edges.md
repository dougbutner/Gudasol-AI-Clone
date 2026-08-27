# Sharp edges — read in full before any render step

Failure modes that cost real productions. Every one of these is load-bearing.

## ffmpeg + timing

- `ffmpeg` always runs with `-nostdin`; never stream-copy concat separate
  segments (frozen frames). One filter_complex, one encode — the scripts
  already do this; don't "optimize" around them.
- fps comes from ffprobe via the map — never assume 30. NTSC rates are
  handled by the exporter; all frame math uses the real rate.

## Repairs (never start over)

- Captions are burned = final. Wrong word/colour/headline → re-run steps
  8.5-8.7 for that clip only (8.7 only when the music layer is live).
  Wrong LAYOUT → re-probe if the scene data is stale, fix the plan,
  verify, re-run 8.4-8.7. Wrong cut → fix candidates.json, recompile that
  clip, re-render. Never redo transcription.
- The cuts JSON `output` field is the XML TIMELINE destination and
  nothing else — pointing it at a render once destroyed two finished
  MP4s. The exporter refuses non-.xml targets; never "fix" that guard.
- The XML references the ORIGINAL source path; if the user moves it, the
  MP4s still stand alone (the package README says this).

## Layout layer

- Multi-speaker two-shots: no active-speaker switching yet — dominant-
  speaker crop, or `split` when one camera is an inset. Tell the user
  speaker-switching is on the roadmap.
- `zoom` zones taller than 9:16 overflow the frame edges when width-fit —
  prefer wider-than-tall zones; a zone you cannot name confidently in one
  sentence is a `full`, not a `zoom`. (verify_plan.py widens tall zones
  to 1:1+ automatically; zoom-on-cam zones are exempt.)
- Scene threshold: 0.30 default; animated dashboards and busy chat
  overlays can fire false cuts — the 12-frame merge guard eats
  micro-flicker; raise to 0.4 if a scan returns absurd region counts.
- The probe's cam rect is a MOTION footprint (the person's moving parts),
  not the cam panel — verify_plan.py sizes the streamer pane from the
  FACE (~3.3 face-heights, the overlay norm), so a twitchy or
  statue-still streamer still frames right. Prefer fixing the probe data
  over hand-tuning inset rects — but when the still proves the probe
  wrong (a static portrait picked over the live cam; check the probe's
  `cam_choice` field), hand-draw the rects AND mark the region
  `"rects_from": "still"`, or the verifier will overrule you
  (agreeing-but-offset rects get replaced; IoU≈0 disagreement hard-stops
  as structural).
- Hard-learned, the first way: one reused inset rect chopped the
  streamer's head off in a scene where the cam grew — cams move and
  resize BETWEEN scenes; never copy a rect across regions by hand.
- Hard-learned, the second way: a pane the editor can parse — because
  they know the scene — can still be a wall of tiny text to a stranger;
  that is why the fresh-eyes gate exists and why the editor never argues
  with it.
- Dark-UI site modals (dark panel on dark page) defeat the bright-panel
  detector — the probe reports the moving sliver inside the modal instead
  of the modal. The annotated still makes it obvious; draw the panel
  bounds yourself in the layout call and let the verifier aspect-expand.
- The YuNet face model downloads once to `~/.perfect-clips/models/`
  (~230KB, from the official opencv_zoo repo). Offline first run → face
  checks are skipped, aspect/void fixes still apply; mention it in the
  report.

## The fresh-eyes gate (run after verify, before framing)

Geometry checks can't judge whether a pane READS; that takes eyes with no
context. `verify_plan.py --panes` exported one preview PNG per split pane
(BOTH content and streamer — a wrong inset is exactly what strangers' eyes
catch: "that's a different person") and per zoom zone — each the exact
post-cover crop at pane resolution.

**With subagents (Claude Code):** spawn ONE subagent with ZERO context
about the batch. It reads every pane PNG and answers, per image:

- "WHAT: one sentence — what is on screen?"
- "VERDICT: CLEAR or UNCLEAR" — CLEAR means a stranger on a phone
  instantly knows what they're looking at AND the key info is readable;
  dense small-text UI in dark space = UNCLEAR.

**Without subagents (Codex and similar):** review the pane images
yourself in a fresh pass — look at each image BEFORE re-reading any plan
data, judge it purely as a stranger would, and note in the report that
the review was self-run (weaker than true fresh eyes).

**The law:** any UNCLEAR pane → demote that region to `full` in the
plan. Never argue with the verdict — the whole point is eyes without
your context bias; you know what the screen shows, the viewer doesn't.
A streamer pane whose person doesn't match the content pane's scene, or
that shows no person at all, is UNCLEAR by definition.

## Compiler contracts

- Teaser must sit INSIDE one kept segment (the repeat is the point). The
  compiler enforces 1.5-3.5s (hard 1-4).
- Two segments can be word-contiguous (one ends at word N, the next
  starts at N+1) and still be a real cut: when N closes a speech block
  and N+1 opens the next, what sits between them is SILENCE, and cutting
  dead air is exactly what filler removal is for. Never merge those by
  hand. What is never legitimate is a resolved FRAME overlap — the
  boundary law pads both edges, so two segments cut close together
  INSIDE one block can resolve into each other and serve a frame twice
  at the join. compile_clips.py clamps that to a flush join and warns; a
  clamp warning means the cut was tighter than the padding, not that
  anything is broken. A segment that collapses below 3 frames at the
  clamp is rejected outright — that is glitched word timestamps, not
  padding.
- WhisperX sometimes force-aligns one word across an alert/music span
  and reports it seconds long (19.7s seen in the field). clip_words.py
  clamps display at 2.5s past a 4s sanity bound — chip and SRT both. A
  clamp means dead air where nothing was said, which is honest; do not
  "fix" it by stretching the word back out. Long clips make hitting one
  of these likely; a 16.6s frozen chip shipped before the guard existed.

## Long-form mode (rule 11)

- `--mode wide` trusts every segment to share the source's dimensions —
  true for any normal file, but a VOD that changes resolution mid-stream
  (rare transcode hiccups) makes the concat inputs disagree and ffmpeg
  fails LOUDLY rather than corrupting. If that ever fires, the honest
  fallback for that source is the canvas path, which normalizes.
- On a screen-share source the caption chip at 86% can land on the
  SOURCE's own bottom UI (a site's bet bar, a taskbar, a video
  scrubber). That is the source's layout, not a placement bug — the
  chip stays legible on its own colour, and there is no universally
  empty band on a screen recording. Override per run with `--caption-y`
  when a specific source has a clean strip; never change the 0.86
  default, which is measured against YouTube's player, not against any
  one recording.
