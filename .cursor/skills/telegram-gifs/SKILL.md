---
name: telegram-gifs
description: >-
  Make silent square Telegram GIFs (muted H.264 MP4, 480x480, 3–6s) with
  Open Sans Thin meme text, a small pure-black drop shadow, face-tracked
  Gudasol crops, and a corner site link. Use when the user asks for Telegram
  GIFs, Cult of Code clips, square silent MP4 loops, crypto reaction clips,
  GM clips, or saves into Telegram Gifs.
---

# Telegram GIFs

Silent **square MP4s** (Telegram GIFs), not `.gif` and not audio.

This is a **repo skill** (`.cursor/skills/telegram-gifs/`). Font file: `fonts/OpenSans-Thin.ttf`.

## Spec

| Item | Value |
|------|--------|
| Size | **480 × 480** |
| Length | **3–6 seconds** |
| Video | H.264, `yuv420p`, `+faststart`, **no audio** |
| Face | Vision face only (`tools/detect_faces`), conf ≥ 0.55. Never body-only crops. |
| Caption | **Open Sans Thin**, white, **2px pure-black drop shadow** |
| Chrome | Logo + Open Sans Thin URL only in the **last 1 second** |

Default source: **`Long Videos/Cracking the Galactic Code of Lifelight with Gudasol - 12min.mp4`**.

Still portraits: **`Gudasol Persona/`** (face-cropped when Vision finds a face).

When replacing a generation, **move live GIFs into `archives/Telegram-gifs/`** (keep category subfolders). Never delete that archive. New files always get a unique timestamp name.

```bash
python ".cursor/skills/telegram-gifs/scripts/make_telegram_gif.py" --help
```

## Folders

| Folder | What goes here |
|--------|----------------|
| `Telegram Gifs/Crypto/` | HODL, REKT, WAGMI, APE, DYOR, … |
| `Telegram Gifs/Music/` | VIBE, BANGER, DROP, 432HZ, … |
| `Telegram Gifs/Spiritual/` | NAMASTE, OM, AWAKEN, cult, BASED, … |
| `Telegram Gifs/Gudasol/` | GM, GN, Guda …, Yves, code lines |
| `archives/Telegram-gifs/` | Previous generations, archived as-is |

Uncategorized live clips stay in `Telegram Gifs/` root.

```bash
python ".cursor/skills/telegram-gifs/scripts/make_telegram_gif.py" --sort
python ".cursor/skills/telegram-gifs/scripts/make_telegram_gif.py" --archive-old
python ".cursor/skills/telegram-gifs/scripts/make_telegram_gif.py" --preset all
```

`--preset all` archives live GIFs into `archives/Telegram-gifs/`, then regenerates **one clip per unique caption** found there.

## Names

`{slug}-{url}-gudasol-{YYYYMMDD-HHMMSS}.mp4`  
Example: `gm-douglas.life-gudasol-20260828-112800.mp4`

## Gudasol motion (folder `Gudasol/`)

Do **not** play a live talking clip. Pick a **facial expression**, then loop it:

1. **Still + slow zoom** — one Vision face frame from the source video, or a face crop from `Gudasol Persona/`. Ken Burns zoom in and back out so the Telegram loop is seamless.
2. **Expression ping-pong** (video only) — two **next-in-order** face hits (adjacent 1fps scan frames). Hold each expression ~0.4s and alternate, with a light zoom on top.

Prefer ping-pong when two nearby face boxes differ (mouth/head change). Otherwise use a still zoom.

Crypto / Music / Spiritual clips still use short face-locked video extracts.

## Presets

```bash
python ".cursor/skills/telegram-gifs/scripts/make_telegram_gif.py" --preset look-test
python ".cursor/skills/telegram-gifs/scripts/make_telegram_gif.py" --preset gm
python ".cursor/skills/telegram-gifs/scripts/make_telegram_gif.py" --preset more-20
python ".cursor/skills/telegram-gifs/scripts/make_telegram_gif.py" --preset cult-10
python ".cursor/skills/telegram-gifs/scripts/make_telegram_gif.py" --preset all
```

`--preset` (except `look-test` and `all`) also runs `--sort` first. `look-test` is still caption, no extra motion (GM uses Gudasol still/ping-pong).

## URL rules

| Context | URL |
|---------|-----|
| **Crypto** | `flex.report` |
| **Music** | `cxc.world` |
| **Spiritual** | `aquarius.academy` |
| Gudasol / greetings / code | `douglas.life` |
| Earth / nature (only if none of the above) | `tetra.earth` |

## Text attention (random)

About one third of clips stay **still**. The rest pick one motion. Cycle extras (bulge, slice-glitch, end fade/zoom/slide) stay rare (≤10%).

| Kind | What it does |
|------|----------------|
| **still** | Frozen Thin + black shadow |
| **pulse** | Whole caption breathes in scale |
| **shake** | 1–2px jitter |
| **typewriter** | Letters appear left → right |
| **drop_in** | Letters fall into place |
| **wave** | Letters bob on a sine |
| **stagger** | Letters fade in left → right |
| **flash** | Brief opacity blink |

Other ideas (not wired yet): tracking pulse, karaoke word highlight, 3° wobble, underline grow, chromatic split, stamp bounce. Ask to add any of these.
