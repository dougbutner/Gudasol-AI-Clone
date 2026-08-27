# URL ingest — the exact rigging for link sources

Follow in order. Zero extra questions beyond the normal intake.

1. Resolve the save location NOW, without asking: the location the user
   named in the request, else Downloads. "Next to the source file" is
   meaningless for a URL — drop Q4 from the intake on URL runs.
2. Create the package folder immediately:
   `<save location>/<slug> perfect clips/` — slug from the URL
   (streamer handle + video id when the URL carries them, else the video
   id). The VOD downloads INTO it, the finished clips land in it; URL runs
   never create a second package folder at packaging.
3. Launch the fetch IN THE BACKGROUND:
   ```
   python "<skill dir>/scripts/fetch_source.py" "<url>" "<package folder>" --max-height 1080
   ```
   Sub-only / login-walled VOD → append `--cookies-from-browser <browser>`
   (see references/sharp-edges.md). The 1080p H.264 MP4 cap is deliberate —
   it matches the delivery ceiling, and the NLE timeline files just work;
   never raise it. (The final `/best` fallback can exceed the cap on
   sources with no H.264 ≤1080p variant — rare, and the pipeline
   re-encodes regardless.)
4. Run the intake questions (Q1-Q3) while it downloads.
5. On exit, the LAST stdout line is the absolute path of the landed file —
   that is `<video>` for step 2 onward, no further prompts. Intake done but
   still downloading? Say so and wait — never start transcription on a
   `.part` file. Non-zero exit → surface the script's message verbatim (it
   self-describes the install and the login-wall fix) and stop.

The downloaded source STAYS in the package folder — the per-clip timeline
XMLs reference it there, so the package travels as a unit.

## Sharp edges for link sources (read with the steps above)

- VODs only. A stream still in progress has no finished VOD;
  fetch_source.py refuses live URLs (`--match-filter !is_live`) rather
  than record one forever. Re-run once the platform posts the VOD.
- Sub-only / login-walled VODs: `--cookies-from-browser
  chrome|edge|brave|firefox`. On Windows a Chromium browser must be FULLY
  closed first (the cookie DB is locked while it runs), and newer
  Chromium app-bound cookie encryption can still block the read — the
  honest fallback is the platform's own download/export, then run the
  skill on the local file.
- Very long VODs: the download is the cheap part — transcription is ~1
  min per 2 min of footage. State the full ETA the moment the duration is
  known, before committing a multi-hour VOD, not after.
- Playlist links are guarded: `--no-playlist` is hard-set in
  fetch_source.py — a watch-page URL carrying `list=` downloads the
  linked video only, never the binge.
- YouTube formats thin out without a JS runtime (deno) — yt-dlp's warning
  says so itself; Kick and Twitch don't care.
- Kick breaks yt-dlp in TWO independent ways, both handled by
  fetch_source.py's built-in resolver: (a) missing `curl_cffi` in
  yt-dlp's environment — Kick is Cloudflare-fronted; a "no impersonate
  target" warning means install it beside yt-dlp (see setup check);
  (b) Kick's VOD URLs moved to UUIDv7 while its video API still keys on
  the legacy v4 uuid, so every new-style URL 404s regardless of yt-dlp
  version. The resolver decodes the v7 timestamp (first 48 bits = unix
  ms), matches it against `api/v2/channels/<handle>/videos` created_at
  (±5s), and rewrites the URL to the v4 uuid; if the extractor STILL
  fails it pulls the direct IVS master.m3u8 from `api/v1/video/<v4>`'s
  `source` field and downloads that (the media CDN is unauthenticated
  even when the metadata API is not). The old "scrape the player page
  for a manifest" trick is DEAD — the page no longer exposes VOD media
  URLs. `pip install -U yt-dlp` is still worth trying first for
  extractor-level fixes.
