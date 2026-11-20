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

Repo skill: `.cursor/skills/music-videos/`. Font: Open Sans Bold (default) from `.cursor/skills/telegram-gifs/fonts/OpenSans-Bold.ttf`.

## Spec

| Item | Value |
|------|--------|
| Vertical | **1080 × 1920** in `Music Videos/9by19/` |
| Landscape | **1920 × 1080** in `Music Videos/16by9/` |
| Frame rate | **24 fps** |
| Length | **Always the full song** |
| Audio | **Song only**, full volume. Ignore video audio unless the user says otherwise. |
| Caption font | **Open Sans Bold**, lowercase, large enough to read on a phone |
| Caption place | Whole caption **block** centered at **61.8% from the top** |
| Language | Original. **No translation** |
| Render | **One song at a time**, both aspect ratios together |

## Folders

| Path | What |
|------|------|
| `Music Videos/source audio/` | MP3 (or wav/m4a) masters |
| `Music Videos/source videos/` | Optional local clips (fallback) |
| `Music Videos/config.json` | `source_videos` + optional `pin_video` (reusable clip) |
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

6. `--render` refuses unless `verified` is true. Pinned clips stay reusable and are not written to `used.json`. Unpinned clips are marked used only after a successful dual render.

Pin a long clip (and reuse it for later songs):

```bash
python ".cursor/skills/music-videos/scripts/make_music_video.py" --video "/Volumes/Untitled/DCIM/DJI_002/DJI_20260911160102_0026_D.MP4" --render "SONG.mp3"
```

Captions lagging the vocal: set `"shift": -2.0` in the lyrics JSON (seconds; negative = earlier). Pass `--shift -2.0` to write it.

Art: `Gudasol Fractal Art/` is a strip behind captions at **62% opacity**, centered at 61.8% down. Scale it up and center-crop to the strip; do not stretch it. Its top and bottom edge changes every 30 seconds through 14 shapes (saw, squares, triangle, wave, scallop, wide diamond, stairs, narrow gaps, double peak, battlement, semicircle, ramp, spike, flat diamond). Shuffle that order per video so two songs do not share a sequence. Fractals + sacred geometry (skip `[11k]` PNGs) flash as 1–3s overlays every ~10–15s on commas and lyric pauses. Same center-crop for those full-frame flashes.

```bash
python ".cursor/skills/music-videos/scripts/make_music_video.py" --status
```

## Picture

If `pin_video` is set, play that clip from the start, cover-crop, trim to the song, and reuse it. Otherwise concatenate unused clips from the start. Mark unpinned clips used only after a successful dual render. Read sources in place (SD card OK).

## Captions

Hardcoded Open Sans Bold, lowercase, white, small black outline/shadow. The whole caption block is centered at **61.8% down** the frame, on one line or two. Horizontal center. Long lines wrap. Timed to the verified lyrics, on the audio. No auto-translate, no extra logos.

Optional `font`, `caption_case`, `caption_look`, and `caption_place` in `Music Videos/config.json` pick from `render-styles.json`. Leave them out and the line above stays the look.
