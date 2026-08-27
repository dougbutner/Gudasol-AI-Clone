#!/usr/bin/env python3
"""Download a stream VOD (Kick / Twitch / YouTube / anything yt-dlp speaks)
into the run's package folder and print the FINAL absolute file path as the
LAST stdout line — that line is the contract the skill relies on.

Usage:
    python3 fetch_source.py <url> <outdir> [--max-height 1080]
                           [--cookies-from-browser chrome|edge|brave|firefox]

Wraps the yt-dlp CLI via subprocess (not the python lib — matches how users
install it: pip install -U yt-dlp). Quality policy: H.264 MP4 capped at
--max-height (NLE-compatible, matches the pipeline's 1080p delivery ceiling;
no AV1). VODs only — a live-in-progress stream would record forever, so it
is refused instead. Login-walled / sub-only VODs need --cookies-from-browser
(on Windows the browser must be fully closed for Chromium cookie reads).
"""
import json
import os
import re
import subprocess
import sys
import urllib.request

LOGIN_SMELLS = ("private", "sign in", "log in", "login", "subscriber",
                "members only", "members-only", "cookies")
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")


def _get_json(u, timeout=15):
    req = urllib.request.Request(u, headers={"User-Agent": UA,
                                             "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8", "replace"))


def _iso_ms(s):
    from datetime import datetime, timezone
    s = str(s).strip().replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        dt = datetime.strptime(s[:19], "%Y-%m-%d %H:%M:%S")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return int(dt.timestamp() * 1000)


def kick_resolve(url):
    """Kick moved to UUIDv7 VOD URLs while its video API still keys on the
    legacy v4 uuid — every new-style URL 404s in yt-dlp (observed 2026-08).
    Remap v7 -> v4 via the channel's videos API: a v7 uuid's first 48 bits
    ARE its unix-ms timestamp; match it against created_at. Returns
    (resolved_url, meta) — meta carries handle+v4 for the manifest
    fallback, None for non-Kick URLs. Any failure returns the URL
    unchanged (yt-dlp then gets its normal shot)."""
    m = re.match(r"https?://(?:www\.)?kick\.com/([^/?#]+)/videos?/"
                 r"([0-9a-fA-F-]{36})", url)
    if not m:
        return url, None
    handle, u = m.group(1), m.group(2)
    hexs = u.replace("-", "").lower()
    meta = {"handle": handle, "v4": u}
    if len(hexs) != 32 or hexs[12] != "7":
        return url, meta                      # already v4 (or unknown)
    try:
        ts_ms = int(hexs[:12], 16)
        vids = _get_json(f"https://kick.com/api/v2/channels/{handle}/videos")
        best = None
        for v in (vids if isinstance(vids, list) else vids.get("data", [])):
            created = v.get("created_at") or v.get("start_time")
            v4 = (v.get("video") or {}).get("uuid") or v.get("uuid")
            if not created or not v4:
                continue
            d = abs(_iso_ms(created) - ts_ms)
            if d <= 5000 and (best is None or d < best[0]):
                best = (d, v4)
        if best:
            new = url.replace(u, best[1])
            print(f"kick uuid remap (v7 -> v4): {u} -> {best[1]}",
                  file=sys.stderr)
            return new, {"handle": handle, "v4": best[1]}
    except Exception as e:
        print(f"kick remap skipped ({e}) — trying the URL as-is",
              file=sys.stderr)
    return url, meta


def kick_source_m3u8(meta):
    """/api/v1/video/<v4> exposes a direct `source` field holding the
    stream.kick.com IVS master.m3u8 — the media CDN is unauthenticated
    even when the metadata API is not."""
    try:
        d = _get_json(f"https://kick.com/api/v1/video/{meta['v4']}")
        src = d.get("source")
        return src if src and ".m3u8" in src else None
    except Exception:
        return None


def flag(name, default):
    return sys.argv[sys.argv.index(name) + 1] if name in sys.argv else default


def main():
    # UTF-8 both directions — streamer titles carry unicode, and Windows
    # pipes default to the locale codepage, which corrupts the path contract.
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    if len(sys.argv) < 3:
        sys.exit(__doc__.strip())
    url, outdir = sys.argv[1], os.path.abspath(sys.argv[2])
    h = int(flag("--max-height", "1080"))
    browser = flag("--cookies-from-browser", None)
    url, kick_meta = kick_resolve(url)

    try:
        v = subprocess.run(["yt-dlp", "--version"],
                           capture_output=True, text=True)
    except FileNotFoundError:
        v = None
    if v is None or v.returncode != 0:
        sys.exit("yt-dlp not found — install it: pip install -U yt-dlp")

    os.makedirs(outdir, exist_ok=True)
    # H.264 first, height-capped; progressive mp4 then anything as fallback.
    fmt = (f"bestvideo[vcodec^=avc1][height<={h}]+bestaudio/"
           f"best[ext=mp4][height<={h}]/best[height<={h}]/best")
    cmd = ["yt-dlp", url, "-f", fmt,
           "--merge-output-format", "mp4",
           "--no-playlist",               # a VOD link is one video, not a binge
           "--match-filter", "!is_live",  # VODs only — live would record forever
           "-N", "4",                     # HLS VODs (Twitch/Kick) crawl single-threaded
           "-o", os.path.join(outdir,
                              "source - %(uploader)s - %(title).60B.%(ext)s"),
           "--no-simulate", "--print", "after_move:filepath"]
    if browser:
        cmd += ["--cookies-from-browser", browser]

    # --print implies quiet: the only stdout is the final filepath.
    env = dict(os.environ, PYTHONUTF8="1")  # yt-dlp side of the pipe
    r = subprocess.run(cmd, capture_output=True, text=True,
                       encoding="utf-8", errors="replace", env=env)
    if r.returncode != 0 and kick_meta:
        # extractor still broken? go straight at the IVS manifest
        m3u8 = kick_source_m3u8(kick_meta)
        if m3u8:
            print("kick extractor failed — fetching the IVS manifest "
                  "directly from the video API", file=sys.stderr)
            cmd2 = ["yt-dlp", m3u8,
                    "-f", f"bestvideo[height<={h}]+bestaudio/best",
                    "--merge-output-format", "mp4", "-N", "4",
                    "-o", os.path.join(
                        outdir, f"source - {kick_meta['handle']} - "
                                f"{kick_meta['v4'][:8]}.%(ext)s"),
                    "--no-simulate", "--print", "after_move:filepath"]
            r = subprocess.run(cmd2, capture_output=True, text=True,
                               encoding="utf-8", errors="replace", env=env)
    if r.returncode != 0:
        tail = r.stderr.strip()[-1500:]
        msg = f"yt-dlp failed:\n{tail}"
        if any(s in r.stderr.lower() for s in LOGIN_SMELLS):
            msg += ("\nhint: looks login-walled — retry with "
                    "--cookies-from-browser chrome|edge|brave|firefox "
                    "(fully close the browser first on Windows)")
        if "impersonat" in r.stderr.lower():
            msg += ("\nhint: yt-dlp says no impersonation target — "
                    "Cloudflare-fronted hosts (Kick) need curl_cffi "
                    "installed INTO yt-dlp's own environment "
                    "(pip install curl_cffi beside yt-dlp; pipx: "
                    "pipx inject yt-dlp curl_cffi; brew: use the "
                    "yt-dlp venv's pip)")
        sys.exit(msg)

    lines = [ln.strip() for ln in r.stdout.splitlines() if ln.strip()]
    path = lines[-1] if lines else ""
    if not os.path.isfile(path):
        sys.exit("yt-dlp finished but no file landed — if the stream is "
                 "still live there is no VOD to fetch yet.\n"
                 + r.stderr.strip()[-800:])
    print(path)


if __name__ == "__main__":
    main()
