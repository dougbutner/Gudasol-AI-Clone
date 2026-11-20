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
python3 tools/ceo.py status
python3 tools/ceo.py approve <short_id>
```

Do not invent a second pipeline. Call `tools/ceo.py`.

## Niche folder

A niche is any repo folder with both `config.json` and `search-terms.md`.
Aquarius Academy is the example. Music videos stay on the music-videos skill.

Before any search, read that niche’s `search-terms.md`. That file is the only
term list. Expand or retire terms only by the rules written there, and write
changes back into that file with the date and evidence.

## Memory

`data/ceo.sqlite` is the record of every source, short, YouTube post, and
stats read. `data/ceo-status.md` is the human summary. Never invent view or
like numbers; leave cells empty when a read fails. YouTube does not return
shares here; decisions use likes/views.

## Captions and audio

Keep the niche caption look from `config.json` / `render-styles.json`
(gold chip, Bebas Neue, up to three words, 220px above the bottom). The main
video is the only audio. A support clip or fractal still is silent.

Layouts under test: `full`, `main-bottom`, `cutaway`.

## Guardrails

- First three posts of a niche stay `awaiting_approval` until
  `python3 tools/ceo.py approve <id>`.
- Ask before paying, signing up, messaging anyone, or changing a profile.
- Do not delete `sources/`. Clean render temps only.
- Secrets stay in `.env` / Actions secrets and are never printed.
