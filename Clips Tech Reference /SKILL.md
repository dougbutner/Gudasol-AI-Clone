---
name: perfect-clips
description: Turn stream VODs and long recordings into ranked clips — 9:16 shorts or minutes-long widescreen cuts: transcript-found stories, filler cut from inside, hook headlines, pop captions, music beds.
license: MIT — see LICENSE
compatibility: Needs a real machine — ffmpeg, Python 3.10-3.12 venv for WhisperX (~3GB, consent first), Node for captions (~400MB one-time). Optional yt-dlp (URL ingest) and OpenCV (layout probe). claude.ai unsupported; Codex runs degraded — see README.
metadata:
  version: "1"
---

# Perfect Clips

The division of labor is the whole design: **the model decides WHAT
survives, the waveform decides THE FRAME.**

## Environment check (first, silently)

Detect where you are and adapt — don't narrate this:
- `CLAUDECODE=1` set → Claude Code on the user's machine. Full file + shell access. Save outputs per the intake's save-location answer.
- `CODEX_SANDBOX` or `CODEX_SANDBOX_NETWORK_DISABLED` set → Codex. Assume network is OFF: never download without asking; keep writes inside the workspace.
- Neither → assume the claude.ai sandbox. This skill cannot run there (local ffmpeg/WhisperX/Node renders) — say so plainly and stop; point at the README's Claude Code install instead of faking a run.
- In scripts, branch OS with `platform.system()`. In instructions, never assume bash — run scripts with Python ("run scripts/x.py with Python").
- If anything here needs rewiring for this environment (paths, commands), fix it quietly and append one line to `install-notes.md` beside this file (skip the log on claude.ai). Don't narrate errors you already fixed.

## The locked rules (the product — never soften)

1. **Hook law.** No clip ships unless its ACTUAL OPENING passes the 2-second
   test: would the first 2 seconds force a cold viewer (zero context) to keep
   watching? Every clip gets a `hook_mode`:
   - `natural` — the first line is the hook. Run it straight.
   - `teaser` — the natural open fails, but a hook-adjacent line lives inside
     the clip → extract it as a cold open (1.5-3.5s, complete phrase), play it
     first, then run the full clip INCLUDING that line where it naturally
     lands. The repetition is intentional — loop-close retention.
   - Neither → **skip the clip. No hook, no clip.**
2. **Word-index contract.** Never emit seconds when selecting — return word
   INDICES into words.jsonl (models are bad at millisecond arithmetic; the
   measured timestamps are ground truth). Every candidate carries a verbatim
   `hook_quote` of its opening words; the compiler verifies it and rejects
   mismatches. Clips may not open on a continuation token (and/but/so/
   because/then/like/i mean/you know/uh/um/yeah/okay/well...).
3. **Filler removal is core, not optional.** Streamer clips carry dead weight
   between the points. Use multi-segment keep-ranges to cut ramble from
   INSIDE a clip: great point (10s) + ramble (8s) + punchline (12s) = 2
   segments, 22s. Each segment starts and ends on a complete thought. A tight
   clip with zero dead weight beats a 60s clip with fluff.
4. **Boundary law.** Segment edges on speech-block boundaries get waveform
   frames (block onset -30dB in, block end -38dB +1 frame out). Mid-block
   edges (internal filler cuts) get force-aligned word times — the ONE place
   word timestamps rule. compile_clips.py enforces this; never override it.
5. **One-word captions, SUBTLE.** Exactly one word on screen at a time,
   uppercase, on a colour chip at 73% height, sized 7.6% of the frame's
   SHORT edge (identical to width on 9:16 output; rule 11 relies on this
   on widescreen).
   **Placement is safe-zone law:** on a 1080×1920 Reel, Instagram's UI eats
   the top ~250px, the bottom ~420px, ~70px each side, and a ~193px right
   rail over the lower half. Lower-third chips at 73% clear the bottom
   band; the split-region seam position (50%) is safe by construction;
   never park a chip below ~76% or above ~15% — on 9:16 Reels output.
   Long-form widescreen (rule 11) is measured against YouTube's player
   instead and sits at 86%; that is rule 11's number, not a violation of
   this one.
   Gentle ease-in (0.96→1.0 over 3 frames, NO overshoot); a word HOLDS on
   screen until the next word starts whenever the gap is under 1.0s — no
   dead air between words (inter-word fading reads as flashing — a
   production-run lesson); fade-out (~6 frames) only into a real pause;
   never shrink on exit.
6. **Count floor.** Production data from a large open-source clipping
   service (429 jobs): users who got 1-3 clips returned 0.4% of the time;
   4-9 clips → 16.1%. The skip rules above are not a licence to return two
   clips and stop. Work every shortlisted window; fall short of the target
   only when the material truly lacks it — and say so.
7. **Diversity.** Never two clips making the same point or landing the same
   joke — keep the stronger, drop the other. Same broad topic is fine when
   each lands its own moment.
8. **Frame-exact layout law.** Layout may change ONLY on scene-scan
   boundaries; regions tile the keep-segments exactly, and the renderer
   hard-fails on any gap or overlap rather than render it. One frame of
   layout bleed across a cut is a defect, not a rounding error. Layout
   doctrine: `split` is 50/50 — content on TOP, streamer on the BOTTOM;
   `zoom` only when the area of focus is unmistakable (any doubt → `full`);
   the blurred backdrop stays subtle (half luminance) — it is never the
   show. Captions follow the layout on the same exact frames: the pane seam
   over split regions, the lower third everywhere else — always pass the
   layout plan to the caption renderer.
   **Rects are measured and verified, never trusted from an eyeball.** The
   mode call stays categorical and stays the model's, but every rect
   behind it comes from the layout probe (faces, facecam, active-content
   panel), and no split/zoom/crop region renders unverified:
   verify_plan.py expands every pane rect to EXACT pane aspect (expansion
   reveals more, never trims), rebuilds the streamer pane face-anchored,
   and asserts the face actually sits in the rendered pane and the
   content pane actually holds the show. A region that can't be made
   honest DEMOTES to `full` — the verifier never promotes, never
   guesses. Facecams move and resize BETWEEN scenes — the probe measures
   per region, so never copy a rect across regions by hand. A screen
   where nothing but the cam moves is a VOID — a split content pane
   there renders near-black; the honest
   calls are zoom-on-cam (the streamer IS the show) or `full`. Geometry
   verification alone is not enough: every split/zoom pane also passes a
   FRESH-EYES gate — a second reviewer with zero context says what it
   sees, and an unclear pane ships as `full` (the editor never argues
   with the fresh eyes).
9. **Headline law.** Every clip opens with an on-screen HEADLINE that
   names the moment in THIRD PERSON, present tense — a scene caption,
   not a quote: subject + strong verb + object, 3-5 words, ALL-CAPS
   ("STREAMER HITS A BIG WIN", "STREAMER CALLS OUT A VIEWER", "CHAT
   BREAKS THE STREAMER", "HOW STREAMERS GET PAID"). The subject is who
   the cold viewer is watching (STREAMER / HE / SHE / CHAT / a name they
   might know); never first person — the headline is the narrator's
   voice, the captions are the speaker's. Writing rules: name the
   moment, sell the watch — the event class may be named (a win lands, a
   meltdown happens), its magnitude and punchline may not; concrete
   verbs beat adjectives; mass-appeal wording a zero-context scroller
   gets instantly; no trailing punctuation. Render: same chip system as
   the captions (same font, same colour, auto text-contrast), 1.35×
   caption size, pinned top-center (18% height — the whole chip sits
   below Instagram's top ~250px UI band, safe-zone law), on screen for
   the hook window only (~3s) then a quiet fade — it never moves with
   the layout, and the subtle-motion law applies to it like any caption.
   The headline and the one-word captions share the screen during the
   hook — two different elements; never merge them.
10. **Music law.** A music bed exists only when the configured music
    folder holds tracks — resolution: `~/.perfect-clips/music-folder.txt`
    names the folder if it exists, else `~/.perfect-clips/music/` when it
    holds audio (write the config to match), else the layer is
    unconfigured (first-run setup, step 1) — and a `disabled` config, or
    a folder absent or empty, means skip silently, never a warning. The
    filename's leading words name the mood family in plain language
    ("Intense Suspense 2 - Villain Moves.mp3"); mood-match the whole
    filename against each clip's emotional register, then pick at random
    among the fits — and never repeat a track within one package unless
    the shortlist makes it unavoidable. Music sits at -20dB under the
    speech and NEVER louder by default — the bed supports, it never
    competes. Tracks are pre-trimmed by the folder owner: t=0 of the
    file IS the entry point, so the engine lays them at clip start with
    zero offset logic. NO copyright scanning of any kind — every music
    right and clearance is the user's own responsibility (see
    Liability). Full folder/config details: references/music-layer.md.
11. **Mode law.** Every run is `short` (the default — everything above) or
    `longform`, decided at intake and stated in the report. Long-form
    ships **the frame as shot**: source resolution, source aspect, no
    scene scan, no layout probe, no verify, no split/zoom/crop, no
    headline, no music bed. Only the CUTS change — that is the whole
    product: a full story with the dead weight removed, not a moment
    reframed for a feed.
    - **Substance, not moments.** One complete story, argument or segment
      per clip, 2-6 minutes, that a stranger could land on cold and watch
      to the end. A short is a moment; a long-form clip has a beginning,
      a middle and a payoff.
    - **Fewer clips.** Target one per 15 minutes of source, never under
      2, never over 6. The count floor (rule 6) is a short-form number
      and does not apply here — an hour of material holds three or four
      real stories, not eight.
    - **Diversity is by STORY.** No two long-form clips may draw on the
      same stretch of source; overlapping ranges are the same video
      twice. Same topic from a genuinely different segment is fine.
    - **No teaser.** `hook_mode` is `natural` or the clip is skipped. The
      cold-open repeat is a swipe-feed device that closes its loop
      seconds later; at three minutes the repeat lands as a mistake, not
      a hook. The 2-second test still gates every opening — a weak open
      gets a better START, or it does not ship.
    - **Filler removal is the point.** Multi-segment keep-ranges (rule 3)
      matter MORE at this length, not less — raw cuts are what everyone
      else ships. Same boundary law (rule 4), same waveform frames.
    - **Captions stay, static.** One-word chips (rule 5), same font and
      colour, centred at 86% height and never moving — no layout to
      track, no seam to follow. 86% is measured: YouTube's bottom chrome
      is a fixed ~59px, so at theater and fullscreen sizes it starts at
      ~93% of the frame, and a chip centred at 86% puts its bottom edge
      at ~91%. YouTube's chrome auto-hides during playback (Instagram's
      never does), so a small embedded player with controls up is a
      transient overlap, not the design constraint.
    - **Chip size follows the SHORT edge** of the frame (7.6% of
      min(width, height)), so a caption on a 1920x1080 clip reads at the
      same physical size as one on a 1080x1920 short.
      render_captions.mjs does this itself — vertical output is
      unchanged.

## Workflow

`<skill dir>` = the folder with this SKILL.md. Always quote paths.

**Package folder + workdir.** The package folder is created at intake for
EVERY run: `<save location>/<stem> perfect clips/`. ALL intermediates live
in `<package folder>/work/` — never a system temp dir — and stay after the
run: "revive clip N" days later reuses them without re-transcribing.

**Before the first render step of any run, read references/sharp-edges.md
in full — do not proceed to step 8 without it.** It carries the failure
modes that cost real productions.

### 0. Setup check (silent)

Run `python "<skill dir>/scripts/doctor.py"` with any Python that
resolves (`python3` → `python` → `py -3`; a Windows-Store stub that
opens the Store counts as absent) and read its output: set `$WHISPERX`
and `$PYCV` from its `WHISPERX=` / `PYCV=` lines. **Anything it reports
MISSING → read references/setup-installs.md and follow its consent-gated
recipe for that item — do not improvise an install.** Standing rules:

- WhisperX: a Perfect Cuts venv (`~/.perfect-cuts/venv/`, or the older
  `~/.buttercut/venv/`) is reused when it exists — never install a
  second copy.
- Node missing → captions can't burn — offer the captionless route (MP4s
  + SRT for a caption app) rather than blocking.
- yt-dlp matters only when the source is a URL; never block a local-file
  run on it.
- `$PYCV` (layout probe layer — multi-layout sources only: streams/screen
  shares) runs layout_probe.py / verify_plan.py. Missing and the install
  declined → legacy eyeball layout flow, said in the report. Plain
  talking-head runs never need it, and neither do long-form runs
  (rule 11) — that mode has no layout to probe; never offer the install
  on one.

### 0.5 Dashboard (silent, never blocks)

Right after the setup check, refresh and open the local dashboard — any
failure here is ignorable (one line, move on):

```
python "<skill dir>/scripts/dashboard.py"
```

Last stdout line is the page's absolute path — open it with the OS opener
(Windows `start "" "<path>"`, macOS `open "<path>"`, Linux
`xdg-open "<path>"`). It is ONE static file at
`~/.perfect-clips/dashboard.html`: settings pills plus a browser of every
registered package with copy-path buttons. No server, no ports, nothing
runs between sessions.

**Settings paste contract:** a message containing a line that starts with
`perfect-clips settings ` followed by JSON is the dashboard's [Copy for
Claude] button — write that JSON object to `~/.perfect-clips/settings.json`
(keys: caption_color, caption_font, default_mode, clip_count; drop unknown
keys), rerun dashboard.py, and confirm in one line. That paste IS the
consent for the write.

**The dashboard changes DEFAULTS, never consent:** settings.json values
pre-fill the intake round below — they pick which option is recommended
and pre-filled, and the questions still run. Skipping intake because a
settings file exists is a violation of the one-round law, not a shortcut.

### 1. Intake — ONE question round, then no more (first run ever: one extra music-setup round — below)

**Local path** → run the intake, then straight to step 2.

**URL** (kick.com, twitch.tv, youtube.com / youtu.be — anything yt-dlp
speaks) → **read references/url-ingest.md NOW and follow it exactly — do
not improvise the download.**

**First-run music setup — once ever.** Resolve the music config per
rule 10 BEFORE the main intake; unconfigured → **read
references/music-layer.md §First-run setup and run its one question
round now** (URL downloads keep going), then run the normal intake as
ONE multiple-choice round:

With a `~/.perfect-clips/settings.json` present, its values move the
recommended tag: saved caption_color / caption_font / default_mode /
clip_count become each question's first, recommended option. The
questions still fire — defaults, not consent.

- **Q1 — Caption colour:** "What colour for the caption chip?" → **Electric
  purple #7C5CFF (recommended)** / **Classic yellow #FFD400** / **Clean white
  #FFFFFF** / any other hex.
- **Q2 — What am I making:** "Shorts, or long-form clips?" → **Shorts —
  auto count (recommended)** (9:16, target 6, floor 4 — the count-floor
  rule) / **Shorts — 3-5** / **Shorts — 6-10** / **Long-form — 2-6 min,
  source aspect** (mode law, rule 11: widescreen stays widescreen, no
  headline, no music, count comes from the material). Exactly these four
  options — the question tool adds its own free-text choice; never list
  a fifth. The request usually answers this before the round ever fires
  ("give me some long clips from this VOD"): request says LONG-FORM →
  drop Q2 entirely, the count comes from the material (rule 11), never
  ask it; request says SHORTS → Q2 keeps only the three count options.
- **Q3 — Caption font:** "Font for captions?" → **Montserrat ExtraBold
  (recommended, ships with the skill)** / a .ttf path.
- **Q4 — Save location:** → **Downloads (recommended)** / **Next to the
  source file** / another folder.

### 2. Transcribe

```
TORCH_FORCE_NO_WEIGHTS_ONLY_LOAD=1 "$WHISPERX" "<video>" \
  --model small --language en --compute_type float32 --device cpu \
  --output_format json --output_dir "<package folder>/work"
```

Locked flags: `--language en` unless the user says otherwise (mis-detection
silently poisons every decision downstream); float32 on CPU; the env var is
required. ~1 min per 2 min of footage — anything over 10 minutes runs in
background and you say so.

### 3. Speech map + analysis layer

```
python "<skill dir>/scripts/speech_map.py" "<video>" "<package folder>/work/<stem>.json" --out "<package folder>/work/map.json"
python "<skill dir>/scripts/windows.py" "<package folder>/work/<stem>.json" "<package folder>/work/map.json" --outdir "<package folder>/work"
```

Sanity-check the speech map (blocks should read like sentences; a
rescue-calibration line printed = warn the user and scrutinize every
boundary in that run). windows.py emits:
- `words.jsonl` — **line N is word index N** (1-based). To read words A..B,
  read that line range of the file (offset/limit).
- `windows.json` — segment-snapped ~90s windows (30s overlap) with text and a
  density score.

### 4. Score pass (you) — cheap triage

Read `windows.json` (in chunks on long VODs). Under ~20 minutes of footage:
read every window. Longer: read in density order, but state coverage in the
report — density orders reading, it never judges.

Score each window 0-100 with a short reason. **The 2-second test is the main
criterion.** Prefer conflict, surprise, outrage, emotion, novelty, big
numbers, bold claims, complete payoffs. Ignore housekeeping, outros, rambling
transitions. Shortlist ≈ 2× the clip target, minimum score 55.

**Long-form runs read for ARCS, not moments** (rule 11). A 2-6 minute
story spans two to four of these windows, so score NEIGHBOURHOODS: where
does a thing start, build and land? A window that scores 90 on its own but
has no before and no after is a short, not a long-form clip — note it in
the REVIVE sheet and move on. Shortlist ≈ 2× the long-form target (source
minutes / 15).

### 5. Detail pass (you) — the judgment step. This IS the product.

For each shortlisted window, read its words.jsonl slice and build
candidates. Work the words, not your memory of them.

**In long-form mode, four things change here** (rule 11) — read the whole
arc's words, not one window's: the unit is a complete STORY of 2-6
minutes, not a moment; `hook_mode` is `natural` or the clip is skipped
(no teaser at this length); no `headline` field (nothing burns one in
this mode); and no two candidates may draw on the same stretch of source
— the compiler keeps the higher-scoring one. Filler removal carries more
weight, not less: an opening you would keep in a 40-second clip is often
two segments in a four-minute one. Everything else below applies
unchanged.

Per clip decide, in order:
1. **The moment** — one focused idea, fully delivered. Standalone: no "as I
   mentioned", no answers to unheard questions. Fix context problems by
   moving the START earlier, never by cutting the payoff.
2. **Keep-ranges** — cut filler/tangents inside the clip (rule 3). Each
   segment opens and closes on a complete thought. Watch the merge trap: a
   transcript sentence spanning two speech blocks usually hides an aborted
   restart — keep the later attempt.
3. **Hook decision** — apply the hook law. For `teaser`: pick the single most
   scroll-stopping phrase INSIDE one kept segment, 1.5-3.5s, complete phrase.
4. **Self-tests** before finalizing boundaries:
   - *Stop early:* cut 5s before your end — viewer already got the point?
     Your end is too late.
   - *Continue:* does the next sentence continue the thought? You ended
     mid-explanation.
   - *Title delivers:* the title's concrete noun/number/reveal must be SPOKEN
     inside the clip — else extend, retitle, or skip.
5. **Score** hook/engagement/value/shareability, 1-25 each. Be harsh and use
   the whole range — flat 80s are useless for ranking. Don't downgrade
   controversial topics; downgrade weak transcripts. Selection is EDITORIAL,
   never a content-policy or legal review — this skill ships no topic gates.
   Users who have their own content rules (brand, legal, platform) carry
   them in their own instructions or memory, and those apply at runtime
   like any other user instruction.
   Also tag each clip's **emotional register** — one word: hype-win /
   tilt-loss / wholesome / tense / comedic / other. The music bed (step
   8.7) matches tracks against it.
6. **Copy** — **before writing ANY copy, read references/style-rules/core.md
   and apply it — do not draft titles, headlines, or descriptions without
   it.** `title` ≤38 chars, phrased as what a viewer would TYPE INTO
   SEARCH (concrete nouns and numbers beat emotion words); `headline`
   per rule 9 — third person, present tense, subject + verb + object,
   3-5 words, ALL-CAPS, punchline unspoken (a "HOW HE..." clause is not
   a headline); per-platform descriptions (1-2 punchy sentences teasing
   the payoff + 3-5 topical hashtags, every claim and tag grounded in
   what the clip actually says).

Write `<package folder>/work/candidates.json` — word indices 1-BASED and
INCLUSIVE (= line numbers in words.jsonl); every field below is required,
extra fields pass through to the manifest untouched:

```json
{"clips": [{
  "title": "The $40k mistake new streamers make",
  "headline": "HE MAKES A $40K MISTAKE",
  "hook_mode": "teaser",
  "teaser": {"start_word": 1481, "end_word": 1490},
  "segments": [{"start_word": 1440, "end_word": 1497},
               {"start_word": 1512, "end_word": 1568}],
  "hook_quote": "this mistake cost me forty",
  "register": "tense",
  "scores": {"hook": 21, "engagement": 17, "value": 22, "shareability": 16},
  "why": "founder war story with a number, payoff lands at the end",
  "descriptions": {"tiktok": "...", "instagram": "...", "youtube": "..."}
}]}
```

`hook_quote` = verbatim first words of the OUTPUT (the teaser text when
hook_mode=teaser, else the first segment's opening) — the compiler
matches the first ~3 words, mismatch = reject. `teaser` must sit INSIDE
one kept segment. `segments` ordered, no overlaps, each one opening AND
closing on a complete thought — in-points land on a phrase-initial word
after a real pause, never mid-sentence; cut filler from INSIDE with a
second segment rather than shrinking the range. `why` — one clause,
≤80 chars (editing notes belong in the report). `register` drives the
music bed.

### 6. Compile + fix rejects

```
python "<skill dir>/scripts/compile_clips.py" "<package folder>/work/candidates.json" "<package folder>/work/words.jsonl" "<package folder>/work/map.json" --outdir "<package folder>/work" --min-dur 15 --max-dur 60
```

**Long-form** (rule 11): add `--longform` — it enforces the law
mechanically: teaser candidates are refused, and of two candidates
drawing on the same stretch of source only the higher-scoring one
survives (greedy by score, after validation — the loser's cuts file is
removed). `--longform` alone already defaults the window to 120/360s;
`--min-dur`/`--max-dur` still override.

Rejects come back with reasons (hook_quote mismatch, banned opener, teaser
outside its segment, duration, long-form overlap). Fix candidates.json and
re-run — never hand-edit the emitted cuts files. Output: per-clip
`clip NN cuts.json` + `manifest.json` (ranked).

### 7. Plan gate — show the slate, wait for approval

Present the manifest as a table before any rendering:

| # | Score | Dur | Hook | Opens on | Why |
|---|---|---|---|---|---|
| 03 | 76/100 | 41.2s | TEASER | "this mistake cost me forty..." | founder war story, number |

Approve all / drop some / adjust = edit candidates.json and recompile. Only
render approved clips.

### 8. Per-clip render

**LONG-FORM RUNS TAKE THE SHORT PATH** (rule 11). Steps 8.1-8.4 — scene
scan, layout probe, layout call, verify, fresh-eyes gate — do not run at
all: there is no reframing to measure, so there is nothing to verify. One
command replaces all four:

```
python "<skill dir>/scripts/render_clip.py" "<package folder>/work/clip NN cuts.json" "<package folder>/work/clip NN wide.mp4" --mode wide
```

Source resolution, source aspect, one filter_complex, one encode —
frame-exact trim and concat, never a stream-copy concat. It refuses
`--plan`: a layout plan in wide mode is a category error. Then go straight
to 8.5 (caption words) and 8.6 (burn), and skip 8.7 (music) entirely.

For each approved clip (short mode):

1. **Frame-exact scene scan** — find every hard cut inside the keep-segments:
   ```
   python "<skill dir>/scripts/scene_scan.py" "<package folder>/work/clip NN cuts.json" --outdir "<package folder>/work"
   ```
   The emitted regions are the ONLY places layout may change. Streams with
   busy animated screens throwing false cuts: raise `--threshold` to 0.4.
2. **Layout probe (measure before judging):**
   ```
   "$PYCV" "<skill dir>/scripts/layout_probe.py" "<package folder>/work/clip NN cuts.json" "<package folder>/work/clip NN cuts scenes.json" --outdir "<package folder>/work"
   ```
   Per region it measures faces, the facecam rect, the active-content
   rect, full-frame face-x (person-only scenes) and a VOID flag (nothing
   but the cam moves). Output: `clip NN probe.json` + one annotated still
   per region. No cv2 → legacy eyeball flow (estimate
   rects from each probe still; drawbox-verify when unsure, max 2
   iterations) and say so in the report.
3. **Layout call PER REGION (categorical — the mode is yours, the rects
   are measured).** Read each region's ANNOTATED probe still plus the
   probe JSON and pick ONE mode:
   - `crop` — a full-frame person. Use the probe's `full_face_x`.
   - `split` — screen content WITH a facecam inset. Inset = the probe's
     cam rect; content = the probe's content rect — override it only
     when the still shows the measurement missed the show (dark modals
     defeat the panel detector; static portraits can outrank the real
     cam — `cam_choice` in the probe JSON says which face it picked and
     why). Hand-drawn rects need `"rects_from": "still"` on the region —
     without it the verifier overrules them (sharp-edges has the rules).
   - `zoom` — ONE unmistakable area of focus. A VOID region with a live
     cam is the classic case: zone = the cam rect (zoom-on-cam — the
     streamer is the show). Prefer zones wider than tall. Doubt → `full`.
   - `full` — dynamic shots, mixed screens, low confidence. The honest
     fallback, and a good look on motion.
   Write `clip NN layout plan.json`: `{"regions": [...]}` carrying
   each region's `in_frame`/`out_frame` from the scan plus its mode
   fields.
4. **Verify (mandatory when the probe ran), fresh-eyes gate, then frame:**
   ```
   "$PYCV" "<skill dir>/scripts/verify_plan.py" "<package folder>/work/clip NN cuts.json" "<package folder>/work/clip NN layout plan.json" --probe "<package folder>/work/clip NN probe.json" --fix --panes "<package folder>/work/panes"
   ```
   The verifier enforces rule 8 (aspect-expand, face-anchor — bottom-
   pinned for corner cams — snap zoom-on-cam zones, demote-never-promote).
   A DEMOTED region is the verifier doing its job, not an error. Plan
   backed up to `*.pre-verify`; frame boundaries never touched. Exit 2 =
   probe and plan disagree structurally — re-probe, re-decide.
   **Fresh-eyes gate (MANDATORY after verify, before framing): read
   references/sharp-edges.md §The fresh-eyes gate NOW and run it
   exactly.** Then frame:
   ```
   python "<skill dir>/scripts/render_clip.py" "<package folder>/work/clip NN cuts.json" "<package folder>/work/clip NN framed.mp4" --plan "<package folder>/work/clip NN layout plan.json"
   ```
   Sources with one constant layout (plain talking-head recordings) can
   skip probe+scan and use legacy `--mode crop --face-x 0.5` /
   `--mode canvas`.
5. **Caption words:**
   ```
   python "<skill dir>/scripts/clip_words.py" "<package folder>/work/clip NN cuts.json" "<package folder>/work/words.jsonl"
   ```
6. **Burn captions + headline (layout-aware):**
   ```
   node "<skill dir>/scripts/render_captions.mjs" "<package folder>/work/clip NN framed.mp4" "<package folder>/work/clip NN cuts words.json" "<final>.mp4" --color "#7C5CFF" --font "<ttf or skill default>" --plan "<package folder>/work/clip NN layout plan.json" --title "<headline from candidates.json>" --title-sec 3
   ```
   Pass the SAME layout plan used for framing: the chip follows the layout,
   switching position on the exact region frames — the pane seam over
   `split` regions, the lower third over `crop`/`full`/`zoom`. No plan
   (legacy single-mode clips) → flat `--caption-y` (0.73 default,
   Reels-safe). `--title` burns the headline chip (rule 9); omit it
   ONLY if the user explicitly asked for headline-free clips.
   **Long-form** (rule 11) burns the same chips onto the wide render with
   no plan, no title and a static lower position:
   ```
   node "<skill dir>/scripts/render_captions.mjs" "<package folder>/work/clip NN wide.mp4" "<package folder>/work/clip NN cuts words.json" "<final>.mp4" --color "#7C5CFF" --font "<ttf or skill default>" --caption-y 0.86
   ```
   0.86 clears YouTube's control bar at theater and fullscreen sizes and
   is not a preference — do not raise it toward the frame edge. The chip
   sizes itself off the frame's short edge, so nothing else changes.
7. **Music bed (short mode only, and only when the music layer is
   live).** Long-form runs skip this step entirely (rule 11) — a bed
   under a three-minute story fights the talking, and the mode ships the
   source audio. Otherwise resolve per rule 10; not live → skip this
   step silently. Otherwise, FIRST run the
   source-music gate per clip:
   ```
   python "<skill dir>/scripts/music_gate.py" "<package folder>/work/clip NN cuts.json" "<package folder>/work/map.json"
   ```
   Last stdout line: `bed=skip` → the clip ships on its own audio (say
   so in the report, never argue with the number); `bed=ok` → proceed.
   Then list the tracks once per run. Per clip: match by filename mood
   family against its `register` (rule 10 — decide the register now from
   the clip's content if a candidate lacks one), ONE random pick from the
   fits, no repeats within the package unless the shortlist leaves no
   choice; no fit → no bed (a mismatched bed is worse than none).
   ```
   python "<skill dir>/scripts/add_music.py" "<final>.mp4" "<music folder>/<track>" "<package folder>/work/clip NN music tmp.mp4" --gain-db -20
   ```
   then replace `<final>.mp4` with the temp file only on success
   (behavior notes: references/music-layer.md §Runtime).
8. **Premiere/Resolve XML:** set the cuts JSON `output` field to the
   **.xml timeline path — NOT the clip MP4** (the exporter writes XML to
   exactly this path; non-.xml targets are refused), then export:
   ```
   python "<skill dir>/scripts/export_fcp7.py" "<package folder>/work/clip NN cuts.json"
   ```

### 9. Package

Finalize into `<package folder>` (created at intake — never a second one):

| File | Source |
|---|---|
| `README.txt` | `scripts/readme_template.txt` verbatim — long-form runs use `scripts/readme_template_longform.txt` instead (the short-form one promises vertical reframing, headlines and music beds a long-form package does not have) |
| `1 CLIP 87 - <kebab-title>.mp4` ... ranked, score in the name | captioned renders |
| `1 LONG 80 - <kebab-title>.mp4` ... same, long-form runs (rule 11) | captioned wide renders |
| `TITLES + DESCRIPTIONS.txt` | manifest copy fields, style-rules applied |
| `REVIVE - candidates.csv` | every candidate, kept AND rejected/skipped: `clip,mode,status,score,dur,hook_mode,title,reason` — `mode` is `short` or `long`, so a revived row rebuilds in the mode it was cut for |
| `clip data/` | per-clip cuts JSON, words JSON, SRT, XML + `manifest.json` + `candidates.json` |

The `work/` folder stays in the package — it is what makes "revive" work
later without re-transcribing. Register the package so the dashboard's
browser shows it (silent, failure ignorable):

```
python "<skill dir>/scripts/dashboard.py" --register "<package folder>"
```

Open the folder for the user (macOS `open`,
Windows `start`, Linux `xdg-open`). "Revive clip N" = compile/render that
one candidate into the same folder — never redo transcription or analysis.

### 10. Report

- Name the mode in the first line — `short` or `longform` (rule 11) —
  with the output geometry for long-form runs ("four 16:9 clips at
  1920x1080, source untouched"). A user who expected 9:16 needs to know
  immediately.
- Ranked list: score, duration, hook mode, title + headline. Lead with
  "watch CLIP 1."
- Per clip: segments kept (filler cuts count) and what got cut from inside.
- Teaser clips flagged: the line plays twice on purpose — say it before
  they ask.
- Long-form runs: say how many stories the material actually held. Fewer
  than the target is an honest result, not a failure — the count floor
  is a short-form rule. Name the arcs you rejected for being moments
  rather than stories; they are short-form candidates and the REVIVE
  sheet keeps them.
- Long-form clips ship an SRT beside the MP4 in `clip data/` — worth a
  line, since YouTube takes it as a caption upload.
- Coverage: on VODs, which windows were never read (density order) — honest
  gaps, never silent ones.
- Point at the REVIVE sheet for skipped candidates.

## Liability

This is a production tool. It runs no copyright scanning, no licensing
checks, and no rights verification of any kind — not on music, not on
footage. Every right and clearance behind what you publish — music
licenses, footage permissions, platform rules — is your responsibility
alone. If you don't have the rights to a track, don't put it in the
music folder. Downloading and reusing stream content is subject to the
platforms' terms and the rights of the people in the footage — clearing
that is the user's responsibility, not the tool's.

## When to use

Explicit invocation always works: `/perfect-clips` (Claude Code) or
naming the skill. Typical asks: "perfect clip this", "clip this stream",
"clip this VOD", "make clips from this", "make shorts from this", "opus
clip this", "find the viral moments", "turn this podcast into shorts",
"cut this stream into TikToks". Long-form asks route here too: "make
long clips from this", "cut this VOD into YouTube videos", "pull the
full stories out of this stream" (rule 11 — widescreen, minutes-long).
