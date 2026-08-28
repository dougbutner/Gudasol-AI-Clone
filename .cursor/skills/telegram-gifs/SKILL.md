---
name: telegram-gifs
description: >-
  Make silent square Telegram GIFs (muted H.264 MP4, 480x480, 3–6s) with
  animated meme text, face-tracked Gudasol crops, and a corner site link.
  Use when the user asks for Telegram GIFs, Cult of Code clips, square silent
  MP4 loops, crypto reaction clips, GM clips, or saves into Telegram Gifs.
---

# Telegram GIFs

Silent **square MP4s** (Telegram GIFs), not `.gif` and not audio.

## Spec

| Item | Value |
|------|--------|
| Size | **480 × 480** |
| Length | **3–6 seconds** |
| Video | H.264, `yuv420p`, `+faststart`, **no audio** |
| Face | Vision face only (`tools/detect_faces`), conf ≥ 0.55. Never body-only crops. |

**Never overwrite or delete existing GIFs.** New files always get a unique name.

Default source: **`Long Videos/Cracking the Galactic Code of Lifelight with Gudasol - 12min.mp4`**.

```bash
python ".cursor/skills/telegram-gifs/scripts/make_telegram_gif.py" --help
```

## Folders (under `Telegram Gifs/`)

| Folder | What goes here |
|--------|----------------|
| `Crypto/` | HODL, REKT, WAGMI, APE, DYOR, … |
| `Music/` | VIBE, BANGER, DROP, 432HZ, … |
| `Spiritual/` | NAMASTE, OM, AWAKEN, cult, BASED, … |
| `Gudasol/` | GM, GN, Guda …, Yves, code lines |

Uncategorized clips stay in `Telegram Gifs/` root. Sort existing:

```bash
python ".cursor/skills/telegram-gifs/scripts/make_telegram_gif.py" --sort
```

## Names

`{slug}-{url}-gudasol-{YYYYMMDD-HHMMSS}.mp4`  
Example: `gm-douglas.life-gudasol-20260828-112800.mp4`

## Presets

```bash
python ".cursor/skills/telegram-gifs/scripts/make_telegram_gif.py" --preset gm
python ".cursor/skills/telegram-gifs/scripts/make_telegram_gif.py" --preset more-20
python ".cursor/skills/telegram-gifs/scripts/make_telegram_gif.py" --preset cult-10
```

`--preset` also runs `--sort` first.

## URL rules

| Context | URL |
|---------|-----|
| **Crypto** | `flex.report` |
| **Music** | `cxc.world` |
| **Spiritual** | `aquarius.academy` |
| Gudasol / greetings / code | `douglas.life` |
| Earth / nature (only if none of the above) | `tetra.earth` |

## Text styles

Cycle 0–9: impact_bounce, typewriter, rainbow_stagger, drop_in, neon_pulse, karaoke_words, shake, glitch_chroma, wave, stamp.

**Rare extras (each ≤10% of clips, independent):** bulge, slice-glitch, end transition (fade / zoom-out / slide).
