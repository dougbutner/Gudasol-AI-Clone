---
name: niche-clips
description: >-
  Run the repo-wide niche clip CEO loop: scout sources from a niche
  search-terms file, cut one short, post to YouTube, and learn from
  stored stats. Use when the user mentions niche clips, the CEO loop,
  Aquarius Academy shorts posting, ceo.py, or scheduled clip posting.
---

# Niche clips

One command runs the loop locally and in GitHub Actions:

```bash
python3 tools/ceo.py run
python3 tools/ceo.py run --project "Aquarius Academy"
python3 tools/ceo.py run --project Gudasol
python3 tools/ceo.py status
python3 tools/ceo.py review
python3 tools/ceo.py review --project Gudasol
python3 tools/ceo.py approve <short_id>
```

Do not invent a second pipeline. Call `tools/ceo.py`.

## Niche folder

A niche is any repo folder with both `config.json` and `search-terms.md`.
Current projects: `Aquarius Academy/` and `Gudasol/`. Music videos stay on
the music-videos skill.

Each niche has its own YouTube channel credentials in `<niche>/.env`
(gitignored). Copy `<niche>/.env.example`. The niche file wins over the
repo-root `.env` for every `YOUTUBE_*` key. Do not reuse one channel’s
refresh token for another project.

Before any search, read that niche’s `search-terms.md`. That file is the only
term list. Expand or retire terms only by the rules written there, and write
changes back into that file with the date and evidence.

## Memory

`data/ceo.sqlite` is the record of every project, source, short, YouTube post
(with `channel_id` / `channel_title`), and stats read. `data/ceo-status.md` is
the human summary. Never invent view or like numbers; leave cells empty when a
read fails. YouTube does not return shares here; decisions use likes/views.

Pauses, layouts, and term misses are per niche. Posts from Aquarius Academy
and Gudasol stay separate in the same store.

## Captions and audio

Keep the niche caption look from `config.json` / `render-styles.json`
(gold chip, Bebas Neue, up to three words, 220px above the bottom). Title
prefix and tags come from that niche’s `.env`
(`YOUTUBE_TITLE_PREFIX`, `YOUTUBE_TAGS`). The main video is the only audio.
A support clip or fractal still is silent.

Layouts under test: `full`, `main-bottom`, `cutaway`.

## Effects (second arm)

After the spoken section is found and the picture is cut with a layout,
`tools/effects.py` picks one active moviepy preset (`none` is the control).
The effect runs on the picture only; logo and captions are composited after
so they stay sharp and the corner logo is not recolored.

Each short stores `layout`, `subject` (spoken text of the window), and
`effect` in `data/ceo.sqlite`. `run` calls a weekly effect review when the
niche’s last review is older than 7 days; `review` runs it on demand. Weak
effects (under 60% of `none` median likes/views after 4 qualified reads)
are retired and the oldest bench preset is promoted. Never retire `none`.

## Guardrails

- First three posts of a niche stay `awaiting_approval` until
  `python3 tools/ceo.py approve <id>`.
- Ask before paying, signing up, messaging anyone, or changing a profile.
- Do not delete `sources/`. Clean render temps only.
- Secrets stay in each niche’s `.env` / Actions secrets and are never printed.
