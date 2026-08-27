# Perfect Clips

Point it at a long recording — a stream VOD, a podcast, a coaching call —
and it hands back a ranked folder of finished clips in either of two modes.
**Shorts:** vertical 9:16 — moments found from the transcript, filler cut
from inside each clip, a hook headline and one-word captions burned on,
layouts verified against what's actually on screen, an optional music bed
underneath. **Long-form:** widescreen at the source's own resolution —
complete 2-6 minute stories with the dead weight cut out, captions along
the bottom, nothing reframed. Both ship a Premiere/Resolve timeline file
for every clip so you can re-edit any of them on the original footage.

## What you need

| Requirement | Size | When |
|---|---|---|
| ffmpeg + ffprobe | small | always (the skill offers the install) |
| Python 3.10–3.12 + WhisperX venv | ~3GB one-time | always (consent asked first) |
| Node.js 18+ (Remotion installs itself) | ~400MB one-time | captions + headlines |
| yt-dlp | a few MB | only for URL sources (Kick/Twitch/YouTube) |
| opencv-python-headless | ~60MB | only for stream layouts (split screens); skippable |

No API keys. No accounts. Everything runs on your machine. The first full
run downloads ~3.5GB total (WhisperX + the caption renderer) into
`~/.perfect-clips/` — allow 10-15 minutes and 5GB free disk, and it always
asks before installing anything.

| Platform | Support |
|---|---|
| Claude Code (Windows) | ✅ full |
| Claude Code (Mac) | ✅ full |
| claude.ai (web/desktop) | ❌ can't run here — the pipeline needs local ffmpeg, a WhisperX install, and Node renders |
| Codex (CLI) | ⚠️ works; on shorts the fresh-eyes layout review runs as a self-check instead of a second agent (long-form runs need no layout review at all) |

## Install

**Easiest way (any platform):** unzip, open your AI assistant, point it at
the unzipped folder and say "install this skill for my setup" — INSTALL.txt
tells it exactly what to do, including creating any missing folders.
(Claude Code runs inside the Terminal app: open Terminal, type `claude`,
press Return — if that says command not found, install Claude Code first
from claude.com/code. It is not the claude.ai desktop app.) After any
install or update, restart before trying the skill: type `/exit`, then
`claude` again.

**Claude Code, manual** — unzip, then drop the `perfect-clips` folder into:
- Windows: `%USERPROFILE%\.claude\skills\`
- Mac: `~/.claude/skills/` — in Finder press Cmd+Shift+G, paste
  `~/.claude/skills/` and press Return. If that folder doesn't exist, Go
  to `~/.claude` and create a folder named `skills` (Cmd+Shift+. shows
  hidden folders).

You should end up with `~/.claude/skills/perfect-clips/` containing
`SKILL.md` directly (not a second `perfect-clips` folder inside — macOS
unzip sometimes double-nests). Then restart Claude Code so it sees the
skill: type `/exit`, then `claude` again.

**Codex** — drop the same folder into `~/.agents/skills/` (some builds use
`~/.codex/skills/` — use whichever exists; repo projects: `.agents/skills/`
inside the repo).

**claude.ai** — not supported for this skill (see the table). Install it in
Claude Code instead; it's the same skill at full strength.

## First run — check it works

Type exactly: `/perfect-clips` (the guaranteed way to run it — or say
`clip this stream`; automatic triggering works too but depends on your
model).

You should see: it asks for your video (a file path or a VOD link) and runs
a quiet setup check, offering any missing installs with sizes before
touching anything.

## How to use

1. Say `clip this VOD` with a file path or a Kick/Twitch/YouTube link.
   (Mac: to get a video's path, right-click it in Finder, hold Option,
   choose "Copy as Pathname" — or just drag the file into the Claude Code
   window.)
2. Answer one round of questions: caption colour, shorts or long-form
   (and how many), font, save location. (First run ever also asks where your music folder should
   live — optional layer, skippable forever.)
3. Wait out the transcription (about 1 minute per 2 minutes of footage on
   Apple Silicon or a modern PC; older machines run slower — it quotes the
   real ETA up front on long VODs).
4. Approve the clip slate it presents (scores, durations, hooks) — nothing
   renders before your yes.
5. Collect the package folder: ranked MP4s, titles + descriptions, a
   REVIVE sheet of every candidate it considered, and per-clip timeline
   files for your editor.
6. Want a skipped candidate later? Say "revive clip N" — it renders from
   the saved work files without re-transcribing.

## Long-form mode

Say "make long clips from this" (or pick Long-form at the questions) and
the same engine cuts complete stories instead of moments: 2-6 minutes
each, widescreen at the source's own resolution, nothing cropped or
reframed — only the cuts change. Filler still gets cut from inside; the
captions sit low and still, placed to clear YouTube's player controls; no
headline, no music. Fewer clips per run is normal here — an hour of
material holds three or four real stories, and the REVIVE sheet keeps
everything else. Each long clip also ships an SRT you can upload to
YouTube as its caption track — the on-video captions are permanent, the
SRT is YouTube's optional CC layer, and uploading both is normal (viewers
only see the CC if they turn it on).

## The dashboard

Every run refreshes and opens a one-page local dashboard
(`~/.perfect-clips/dashboard.html`): pick your default caption colour,
font, and mode with pill buttons, and browse every package the skill has
made — each clip has a copy-path button, so you can paste a path into
chat and say "revive this" or "recut this". It is a plain file — no
server, nothing running in the background.

Saving settings works two ways: **Copy for Claude** puts a one-line
settings snippet on your clipboard — paste it into chat and the skill
saves it; **Save directly** uses the browser's own save dialog (Chrome
and Edge; the button hides itself elsewhere) — save over
`~/.perfect-clips/settings.json`. On a Mac the dialog hides dot-folders:
press Cmd+Shift+G, paste `~/.perfect-clips/`, keep the filename, click
Replace when asked — or skip the fiddle and use Copy for Claude. Your saved settings become the
pre-filled defaults at the next run's questions.

## Music beds (optional)

Drop tracks into the music folder it sets up on first run and clips get a
mood-matched bed at -20dB under the voice. Filenames lead with the mood
("Upbeat Hip Hop Beat 5 - Hype Workout.mp3"). A starter pack ZIP ships
alongside this skill in the download post. No tracks = no music, silently.
Rights and clearances for anything you publish are yours — the skill scans
nothing.

## Updating

Delete the old `perfect-clips` folder (it lives in `~/.claude/skills/` /
`%USERPROFILE%\.claude\skills\`) and install the new zip. Your 3GB WhisperX
install, music folder, dashboard and saved settings live elsewhere
(`~/.perfect-clips/`) and are kept.
New versions are posted in the community — skool.com/vic.

## Troubleshooting

- **`/perfect-clips` says unknown command** — confirm the path is exactly
  `~/.claude/skills/perfect-clips/SKILL.md` (Windows:
  `%USERPROFILE%\.claude\skills\perfect-clips\SKILL.md`), then restart
  Claude Code. A doubled folder (`perfect-clips/perfect-clips/`) is the
  usual cause.
- **Claude asks permission to run scripts** — normal. It's your machine;
  the skill runs ffmpeg/Python/Node locally. Approve the commands it shows.
- **No Python, or the wrong version** — the transcription engine needs
  Python 3.10, 3.11, or 3.12 (not 3.13+, not the 3.9 Apple ships) for
  its own private venv. Install 3.12 from python.org/downloads — pick
  3.12 specifically, not the newest. Your system Python can stay
  whatever it is; every other script in the skill runs on any modern
  Python.
- **WhisperX install fails** — same version rule as above. The skill
  installs into its own venv at `~/.perfect-clips/venv/` (or reuses
  Perfect Cuts' venv if you own that skill — no second 3GB).
- **First caption render is slow** — one-time: Remotion (~250MB) plus a
  headless Chrome (~150MB) install themselves, then it's fast. Node comes
  from nodejs.org (the LTS button).
- **A Kick link 404s but plays in your browser** — the skill's downloader
  auto-remaps Kick's new video IDs and falls back to the direct stream
  manifest, so most Kick links just work. If it still fails and mentions
  "impersonation", yt-dlp needs the curl_cffi add-on in its own
  environment — the error message tells you the exact install command.
- **Captions/headline missing on a clip** — Node wasn't found at render
  time. Install Node 18+, then ask to re-run captions for that clip; the
  cut itself is never lost.

## Credits & license

Built by Systems by Vic — systemsbyvic.com · skool.com/vic ·
youtube.com/@systemsbyvic. MIT license (see LICENSE, third-party notices
in THIRD-PARTY-NOTICES.md).
