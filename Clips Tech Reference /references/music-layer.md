# Music folder (optional layer)

## First-run setup (one question round, once ever)

The layer is unconfigured (no config file, default folder empty) → ask the
user ONE setup round, two multiple-choice questions:

- **MQ1 — Music folder:** "Where should your music folder live?" →
  **`~/.perfect-clips/music/` (recommended)** / **I'll give a path** /
  **No music — skip this layer**. Skipping still writes the config —
  the literal line `disabled` — so the question never fires again; a
  `disabled` config = music layer off, silently.
- **MQ2 — Starter pack:** "Install the starter music pack?" → **Yes —
  show me how** / **No, I'll use my own tracks**. YES → tell the user:
  the pack ships as a separate ZIP alongside this skill in the download
  post where you got it; download it, unzip it, drop the tracks into
  the folder from MQ1. The skill never downloads the pack and never
  blocks a run waiting for it — folder still empty → this run ships
  music-free, and the layer picks the tracks up automatically on the
  next run (folder contents stay the runtime switch).

Then write the config — one line, the chosen path or `disabled` — to
`~/.perfect-clips/music-folder.txt` (create the folder if needed).

## Runtime resolution + conventions

`~/.perfect-clips/music-folder.txt` is the source of truth: one line,
the absolute path of the music folder — or the literal line `disabled`,
which turns the layer off silently. Resolution at runtime: config file
exists → that path; no config but `~/.perfect-clips/music/` holds
audio → use it and write the config to match (self-heals existing
setups); neither → unconfigured, and the first-run setup round (workflow
step 1) asks once, then never again. With a folder configured, its
CONTENTS are the switch: tracks present → beds on; empty → clips ship
music-free, silently.

- **Filenames name the mood family in plain words, first.** The leading
  words are the mood family; whatever follows (a number, a track name)
  is flavor. Mood-matching reads the whole filename. The starter pack
  is the convention:
  - `Upbeat Hip Hop Beat 5 - Hype Workout.mp3`
  - `LoFi Chill Wave Beat 2 - Late Night Cozy.mp3`
  - `Intense Suspense 2 - Villain Moves.mp3`
  - `Sad Emotional Piano 1 - Sincere Moments.mp3`
- **Formats:** mp3, wav, m4a, ogg.
- **Pre-trim your tracks.** t=0 of the file is where the bed enters — the
  engine lays every track at clip start, no offset logic. Cut intro dead
  air before dropping a track in.
- Mood-matching examples: "Upbeat Hip Hop Beat 5 - Hype Workout.mp3" →
  hype-win; "Sad Emotional Piano 1 - Sincere Moments.mp3" → wholesome or
  tilt-loss; "Intense Suspense 2 - Villain Moves.mp3" → tense.

## Runtime behavior notes (add_music.py)

- Video is stream-copied — frames and burned captions come out
  bit-identical; only the audio re-encodes.
- A track longer than the clip is cut at clip end; shorter leaves
  silence after — both by design (amix duration=first).

## The source-music gate (why a clip can refuse a bed)

A clip whose source already carries music ships on its own audio — the
stream's music IS that moment's energy, and a bed on top just clashes.
music_gate.py decides per clip, from measurement: in a clean recording
the gaps BETWEEN speech blocks sit near silence, while a scored stream
never drops there. The gate takes the clip's keep-ranges, finds the
inter-speech gaps (speech map blocks), measures the audio floor in just
those gaps, and verdicts on the number: gap floor louder than -38dB (the
boundary law's own out-threshold) → `bed=skip`. Too little gap time to
measure (wall-to-wall speech) → it falls back to the speech map's
rescue-calibration flag, which fires exactly when muxed music defeated
the locked thresholds → `bed=skip`. The verdict is final either way —
never argue with the number, and say in the report when a clip shipped
on its own audio.
