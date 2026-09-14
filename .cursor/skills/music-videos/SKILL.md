---
name: music-videos
description: >-
  Make full-length local music videos (1080x1920 and 1920x1080, 24fps) from
  MP3s plus unused source clips, with Open Sans Thin captions timed to the
  song. Use when the user mentions Music Videos, source audio, source videos,
  9by19, 16by9, lyrics verify, or full-song captioned MP4s. Not shorts.
---

# Music Videos

Full-length **song videos**, not Shorts and not Telegram GIFs.

Repo skill: `.cursor/skills/music-videos/`. Font: Open Sans Thin from `.cursor/skills/telegram-gifs/fonts/OpenSans-Thin.ttf`.

## Spec

| Item | Value |
|------|--------|
| Vertical | **1080 × 1920** in `Music Videos/9by19/` |
| Landscape | **1920 × 1080** in `Music Videos/16by9/` |
| Frame rate | **24 fps** |
| Length | **Always the full song** |
| Audio | **Song only**, full volume. Ignore video audio unless the user says otherwise. |
| Caption font | **Open Sans Thin only** |
| Caption place | First-line **center** at **61.8% from the top**, block centered |
| Language | Original. **No translation** |
| Render | **One song at a time**, both aspect ratios together |

## Folders

| Path | What |
|------|------|
| `Music Videos/source audio/` | MP3 (or wav/m4a) masters |
| `Music Videos/source videos/` | Optional local clips (fallback) |
| `Music Videos/config.json` | `source_videos` path — SD card / DCIM is fine, no copy |
| `Music Videos/lyrics/` | Editable `.json` + `.srt` + `.txt` |
| `Music Videos/9by19/` | Vertical outputs |
| `Music Videos/16by9/` | Landscape outputs |
| `Music Videos/used.json` | Source clips already accepted into a render |

## Workflow (never skip verify)

1. User drops song(s) in `source audio/`. Picture can stay on an **SD card** — do not copy the big files. Point at the card (saved in `config.json`):

```bash
python ".cursor/skills/music-videos/scripts/make_music_video.py" --source-videos "/Volumes/Untitled/DCIM" --status
```

Keep the card mounted for the whole render. Used clips are tracked by relative path in `used.json`.
2. Transcribe **locally** (no translate):

```bash
python ".cursor/skills/music-videos/scripts/make_music_video.py" --lyrics "SONG.mp3"
```

3. **Stop.** Show the user `Music Videos/lyrics/{slug}.txt` (and `.srt` / `.json`). Ask them to fix wording and timing. Do not render yet.
4. After they confirm, set `"verified": true` in the JSON (keep `"translate": false`).
5. Render both sizes, full song length:

```bash
python ".cursor/skills/music-videos/scripts/make_music_video.py" --render "SONG.mp3"
```

6. `--render` refuses unless `verified` is true. After both files succeed, those source videos are written to `used.json` and will not be reused. If unused clips cannot cover the song, fail and ask for more source videos.

```bash
python ".cursor/skills/music-videos/scripts/make_music_video.py" --status
```

## Picture

Play one or more **unused** source videos **from the start, in full**, concatenated, then trim to the song. Cover-crop to fill. Never loop a used clip. Mark used **only after** a successful dual render (accepted). Source files are read in place (local folder or mounted SD card).

## Captions

Hardcoded Open Sans Thin, white, small black outline/shadow. First line’s vertical center is **61.8% down** the frame. Horizontal center. Timed to the verified lyrics, on the audio. No auto-translate, no extra logos.
