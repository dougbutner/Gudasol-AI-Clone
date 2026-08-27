# Setup installs — consent-gated recipes (read when the setup check finds something missing)

Every install here is offered, never forced: name the size, get a yes,
then install. Log any machine-specific adjustment to install-notes.md.

- **ffmpeg + ffprobe** missing → bootstrap install: Windows `winget`;
  macOS `brew`, or the static build if brew is absent; Linux apt or a
  static build. Verify both binaries answer on PATH afterwards.
- **WhisperX** missing everywhere → offer the pinned install (consent
  first, ~3GB): `whisperx==3.4.2 pyannote-audio==3.4.0 torch==2.8.0
  torchaudio==2.8.0`, Python 3.10-3.12 ONLY, into `~/.perfect-clips/venv/`
  (never a second copy when a Perfect Cuts venv already exists — probe
  `~/.perfect-cuts/venv/` and `~/.buttercut/venv/` first). The 3.10-3.12
  pin applies ONLY to this venv — every pipeline script is stdlib-only
  and runs on any modern Python.
- **Node** present but first caption render ever: `node "<skill
  dir>/scripts/render_captions.mjs" --setup` installs Remotion (~250MB)
  and Chrome Headless Shell (~150MB) — one-time, mention it before it
  happens. Node missing → the captionless route (MP4s + SRT for a
  caption app); Node 18+ comes from nodejs.org (the LTS button).
- **yt-dlp** missing and the run needs it (URL source) → offer the tiny
  install (consent first, a few MB): `pip install -U yt-dlp`. Kick URLs
  may also need `curl_cffi` inside yt-dlp's OWN environment —
  fetch_source.py's error message names the exact install when missing
  (pipx: `pipx inject yt-dlp curl_cffi`; brew's yt-dlp: its private
  venv's pip — a user-level pip install does nothing there).
- **OpenCV** (layout probe layer) missing everywhere → offer the install
  INTO THE WHISPERX VENV, not the system python: `"<venv>/bin/pip"
  install opencv-python-headless` (Windows `Scripts\pip`), consent
  first, ~60MB — system pythons are often 3.13/3.14 with no cv2 wheels.
  Declined → legacy eyeball layout flow, said in the report.
