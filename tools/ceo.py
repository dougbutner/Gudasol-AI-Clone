#!/usr/bin/env python3
"""CEO loop: scout, cut one short, post at most one YouTube video, learn from reads.

  python3 tools/ceo.py run
  python3 tools/ceo.py run --project "Aquarius Academy"
  python3 tools/ceo.py status
  python3 tools/ceo.py review
  python3 tools/ceo.py review --project Gudasol
  python3 tools/ceo.py approve <short_id>

Each niche folder has its own .env (YouTube channel). Shared keys may live in
the repo-root .env. Memory lives in data/ceo.sqlite and tracks many projects
and channels. Layout and effect are separate arms; weekly review prunes weak
effects. Video files stay gitignored.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import sqlite3
import ssl
import subprocess
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

try:
    import certifi
except ImportError:  # pragma: no cover
    certifi = None  # type: ignore

ROOT = Path(__file__).resolve().parents[1]
TOOLS = Path(__file__).resolve().parent
sys.path.insert(0, str(TOOLS))

import effects as fxcat  # noqa: E402
import make_shorts as shorts  # noqa: E402
import share_shorts as share  # noqa: E402

DATA = ROOT / "data"
DB_PATH = DATA / "ceo.sqlite"
STATUS_PATH = DATA / "ceo-status.md"
LAYOUTS = ("full", "main-bottom", "cutaway")
EFFECT_MIN_SAMPLES = 4
EFFECT_RETIRE_RATIO = 0.60
EFFECT_REVIEW_DAYS = 7
HOST = "gha" if os.environ.get("GITHUB_ACTIONS") == "true" else "local"
YOUTUBE_ENV_KEYS = (
    "YOUTUBE_ACCESS_TOKEN",
    "YOUTUBE_REFRESH_TOKEN",
    "YOUTUBE_CLIENT_ID",
    "YOUTUBE_CLIENT_SECRET",
    "YOUTUBE_TITLE_PREFIX",
    "YOUTUBE_TAGS",
    "YOUTUBE_DISCLAIMER",
)


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def parse_time(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def https_ctx() -> ssl.SSLContext:
    return ssl.create_default_context(cafile=certifi.where() if certifi else None)


def read_env_file(path: Path) -> dict[str, str]:
    if not path.is_file():
        return {}
    out: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        out[key.strip()] = value.strip().strip("'").strip('"')
    return out


def load_project_env(niche: Path) -> None:
    """Root .env for shared keys; niche/.env wins for YouTube and project overrides."""
    for key in YOUTUBE_ENV_KEYS:
        os.environ.pop(key, None)
    root_vars = read_env_file(ROOT / ".env")
    niche_vars = read_env_file(niche / ".env")
    for key, value in root_vars.items():
        if key in YOUTUBE_ENV_KEYS:
            os.environ[key] = value
        else:
            os.environ.setdefault(key, value)
    for key, value in niche_vars.items():
        os.environ[key] = value


def _table_cols(conn: sqlite3.Connection, table: str) -> set[str]:
    return {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}


def migrate(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS projects (
            slug TEXT PRIMARY KEY,
            path TEXT NOT NULL,
            channel_id TEXT,
            channel_title TEXT,
            updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS effects (
            slug TEXT PRIMARY KEY,
            fx TEXT NOT NULL,
            params TEXT NOT NULL,
            note TEXT
        );
        CREATE TABLE IF NOT EXISTS niche_effects (
            niche TEXT NOT NULL,
            slug TEXT NOT NULL,
            pool TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            PRIMARY KEY (niche, slug)
        );
        CREATE TABLE IF NOT EXISTS effect_reviews (
            id INTEGER PRIMARY KEY,
            reviewed_at TEXT NOT NULL,
            niche TEXT NOT NULL,
            slug TEXT NOT NULL,
            action TEXT NOT NULL,
            samples INTEGER,
            median_likes_views REAL,
            reason TEXT
        );
        """
    )
    post_cols = _table_cols(conn, "posts")
    if "channel_id" not in post_cols:
        conn.execute("ALTER TABLE posts ADD COLUMN channel_id TEXT")
    if "channel_title" not in post_cols:
        conn.execute("ALTER TABLE posts ADD COLUMN channel_title TEXT")
    run_cols = _table_cols(conn, "runs")
    if "channel_id" not in run_cols:
        conn.execute("ALTER TABLE runs ADD COLUMN channel_id TEXT")
    if "channel_title" not in run_cols:
        conn.execute("ALTER TABLE runs ADD COLUMN channel_title TEXT")
    short_cols = _table_cols(conn, "shorts")
    if "subject" not in short_cols:
        conn.execute("ALTER TABLE shorts ADD COLUMN subject TEXT")
    if "effect" not in short_cols:
        conn.execute("ALTER TABLE shorts ADD COLUMN effect TEXT")
    decision_cols = _table_cols(conn, "decisions")
    if "effect" not in decision_cols:
        conn.execute("ALTER TABLE decisions ADD COLUMN effect TEXT")
    for slug, fx_name, params, note in fxcat.seed_rows():
        conn.execute(
            """
            INSERT INTO effects (slug, fx, params, note) VALUES (?, ?, ?, ?)
            ON CONFLICT(slug) DO UPDATE SET fx = excluded.fx, params = excluded.params, note = excluded.note
            """,
            (slug, fx_name, params, note),
        )
    conn.commit()


def ensure_niche_effects(conn: sqlite3.Connection, niche: str) -> None:
    now = utc_now()
    for slug, pool in fxcat.default_niche_pools():
        row = conn.execute(
            "SELECT slug FROM niche_effects WHERE niche = ? AND slug = ?",
            (niche, slug),
        ).fetchone()
        if row:
            continue
        conn.execute(
            "INSERT INTO niche_effects (niche, slug, pool, updated_at) VALUES (?, ?, ?, ?)",
            (niche, slug, pool, now),
        )
    conn.commit()


def connect() -> sqlite3.Connection:
    DATA.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS projects (
            slug TEXT PRIMARY KEY,
            path TEXT NOT NULL,
            channel_id TEXT,
            channel_title TEXT,
            updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS sources (
            id INTEGER PRIMARY KEY,
            niche TEXT NOT NULL,
            youtube_id TEXT NOT NULL,
            url TEXT NOT NULL,
            title TEXT,
            duration_sec REAL,
            term TEXT,
            status TEXT NOT NULL,
            found_at TEXT NOT NULL,
            UNIQUE(niche, youtube_id)
        );
        CREATE TABLE IF NOT EXISTS shorts (
            id INTEGER PRIMARY KEY,
            source_id INTEGER NOT NULL REFERENCES sources(id),
            layout TEXT NOT NULL,
            start_sec REAL NOT NULL,
            end_sec REAL NOT NULL,
            path TEXT,
            sha256 TEXT,
            audio_streams INTEGER,
            status TEXT NOT NULL,
            created_at TEXT NOT NULL,
            UNIQUE(source_id, layout, start_sec, end_sec)
        );
        CREATE TABLE IF NOT EXISTS posts (
            id INTEGER PRIMARY KEY,
            short_id INTEGER NOT NULL REFERENCES shorts(id),
            platform TEXT NOT NULL,
            platform_id TEXT,
            url TEXT,
            caption TEXT,
            posted_at TEXT NOT NULL,
            channel_id TEXT,
            channel_title TEXT,
            UNIQUE(short_id, platform)
        );
        CREATE TABLE IF NOT EXISTS reads (
            id INTEGER PRIMARY KEY,
            post_id INTEGER NOT NULL REFERENCES posts(id),
            read_at TEXT NOT NULL,
            views INTEGER,
            likes INTEGER,
            comments INTEGER,
            shares INTEGER,
            stuck INTEGER NOT NULL DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS runs (
            id INTEGER PRIMARY KEY,
            started_at TEXT NOT NULL,
            finished_at TEXT,
            host TEXT NOT NULL,
            niche TEXT,
            auth TEXT,
            summary TEXT,
            channel_id TEXT,
            channel_title TEXT
        );
        CREATE TABLE IF NOT EXISTS decisions (
            id INTEGER PRIMARY KEY,
            decided_at TEXT NOT NULL,
            niche TEXT NOT NULL,
            layout TEXT,
            term TEXT,
            reason TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS pauses (
            id INTEGER PRIMARY KEY,
            niche TEXT NOT NULL,
            platform TEXT NOT NULL,
            until_at TEXT NOT NULL,
            reason TEXT
        );
        CREATE TABLE IF NOT EXISTS term_misses (
            niche TEXT NOT NULL,
            term TEXT NOT NULL,
            misses INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (niche, term)
        );
        """
    )
    migrate(conn)
    conn.commit()
    return conn


def niche_dirs() -> list[Path]:
    found: list[Path] = []
    for path in sorted(ROOT.iterdir()):
        if path.is_dir() and (path / "config.json").is_file() and (path / "search-terms.md").is_file():
            found.append(path)
    return found


def resolve_niche(name: str | None) -> Path | None:
    if not name:
        return None
    path = Path(name)
    if not path.is_absolute():
        path = ROOT / name
    if path.is_dir() and (path / "config.json").is_file() and (path / "search-terms.md").is_file():
        return path
    return None


def pick_niche(conn: sqlite3.Connection, forced: str | None = None) -> Path | None:
    if forced:
        return resolve_niche(forced)
    niches = niche_dirs()
    if not niches:
        return None
    latest: dict[str, str] = {}
    for row in conn.execute("SELECT niche, MAX(started_at) AS t FROM runs WHERE niche IS NOT NULL GROUP BY niche"):
        latest[row["niche"]] = row["t"]
    niches.sort(key=lambda p: (latest.get(p.name) or "", p.name))
    return niches[0]


def upsert_project(
    conn: sqlite3.Connection,
    niche: Path,
    channel_id: str | None = None,
    channel_title: str | None = None,
) -> None:
    abs_niche = niche if niche.is_absolute() else (ROOT / niche)
    try:
        rel = str(abs_niche.resolve().relative_to(ROOT.resolve()))
    except ValueError:
        rel = niche.name
    row = conn.execute("SELECT channel_id, channel_title FROM projects WHERE slug = ?", (abs_niche.name,)).fetchone()
    keep_id = channel_id or (row["channel_id"] if row else None)
    keep_title = channel_title or (row["channel_title"] if row else None)
    conn.execute(
        """
        INSERT INTO projects (slug, path, channel_id, channel_title, updated_at)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(slug) DO UPDATE SET
            path = excluded.path,
            channel_id = COALESCE(excluded.channel_id, projects.channel_id),
            channel_title = COALESCE(excluded.channel_title, projects.channel_title),
            updated_at = excluded.updated_at
        """,
        (abs_niche.name, rel, keep_id, keep_title, utc_now()),
    )
    conn.commit()


def fetch_channel(token: str) -> tuple[str | None, str | None]:
    data = youtube_get(token, "channels", {"part": "snippet,id", "mine": "true"})
    if not data or not data.get("items"):
        return None, None
    item = data["items"][0]
    return str(item.get("id") or "") or None, str((item.get("snippet") or {}).get("title") or "") or None


def parse_terms(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    lane = ""
    on_lane: list[str] = []
    terms: list[str] = []
    retired: list[str] = []
    section = ""
    for raw in text.splitlines():
        line = raw.strip()
        if line.startswith("## "):
            section = line[3:].strip().lower()
            continue
        if line.startswith("- Lane:"):
            lane = line.split(":", 1)[1].strip()
        elif line.startswith("- On lane:"):
            body = line.split(":", 1)[1].strip()
            on_lane = [w.strip().lower() for w in re.split(r"[,/]| or ", body) if w.strip()]
        elif section in {"terms", "seed terms", "active terms"} or section.startswith("seed") or section.startswith("active"):
            if line.startswith("- `") and "`" in line[3:]:
                terms.append(line.split("`")[1].strip())
        elif section.startswith("retired"):
            if line.startswith("- `") and "`" in line[3:]:
                retired.append(line.split("`")[1].strip())
    # de-dupe, keep order
    seen: set[str] = set()
    ordered: list[str] = []
    for term in terms:
        if term and term not in seen and term not in retired:
            seen.add(term)
            ordered.append(term)
    return {"lane": lane, "on_lane": on_lane, "terms": ordered, "retired": retired, "raw": text}


def on_lane_match(title: str, description: str, words: list[str]) -> bool:
    blob = f"{title} {description}".lower()
    return any(w and w.lower() in blob for w in words)


def youtube_refresh(niche: Path) -> tuple[str, str]:
    """Return (access_token, auth_status) using that niche's .env. auth is ok or blocked."""
    load_project_env(niche)
    client_id = os.environ.get("YOUTUBE_CLIENT_ID", "").strip()
    client_secret = os.environ.get("YOUTUBE_CLIENT_SECRET", "").strip()
    refresh = os.environ.get("YOUTUBE_REFRESH_TOKEN", "").strip()
    if not (client_id and client_secret and refresh):
        return "", "blocked"
    try:
        _, _, body = share.http_request(
            "POST",
            "https://oauth2.googleapis.com/token",
            data=urllib.parse.urlencode(
                {
                    "client_id": client_id,
                    "client_secret": client_secret,
                    "refresh_token": refresh,
                    "grant_type": "refresh_token",
                }
            ).encode("utf-8"),
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
    except Exception:
        return "", "blocked"
    if not isinstance(body, dict) or not body.get("access_token"):
        return "", "blocked"
    token = str(body["access_token"])
    os.environ["YOUTUBE_ACCESS_TOKEN"] = token
    return token, "ok"


def youtube_get(token: str, path: str, params: dict[str, str]) -> dict[str, Any] | None:
    url = "https://www.googleapis.com/youtube/v3/" + path + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"Authorization": "Bearer " + token})
    try:
        with urllib.request.urlopen(req, timeout=45, context=https_ctx()) as resp:
            return json.loads(resp.read().decode())
    except Exception:
        return None


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def source_path(niche: Path, youtube_id: str) -> Path:
    return niche / "sources" / f"{youtube_id}.mp4"


def ytdlp_bin() -> str | None:
    found = shutil.which("yt-dlp")
    if found:
        return found
    for candidate in ("/usr/local/bin/yt-dlp", "/opt/homebrew/bin/yt-dlp"):
        if Path(candidate).is_file():
            return candidate
    return None


def download_source(url: str, dest: Path) -> bool:
    ytdlp = ytdlp_bin()
    if not ytdlp:
        return False
    dest.parent.mkdir(parents=True, exist_ok=True)
    try:
        subprocess.run(
            [
                ytdlp, "--no-playlist",
                "-f", "bv*[vcodec^=avc1][ext=mp4]+ba[ext=m4a]/b[ext=mp4]/bv*+ba/b",
                "--merge-output-format", "mp4",
                "--write-info-json",
                "-o", str(dest),
                url,
            ],
            check=True,
        )
    except subprocess.CalledProcessError:
        return False
    return dest.is_file()


def search_youtube(term: str, limit: int = 8) -> list[dict[str, Any]]:
    ytdlp = ytdlp_bin()
    if not ytdlp:
        return []
    try:
        raw = subprocess.check_output(
            [
                ytdlp, f"ytsearch{limit}:{term}",
                "--dump-json", "--flat-playlist", "--no-download",
            ],
            text=True,
            stderr=subprocess.DEVNULL,
        )
    except subprocess.CalledProcessError:
        return []
    rows: list[dict[str, Any]] = []
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return rows


def choose_layout(conn: sqlite3.Connection, niche: str) -> tuple[str, str]:
    ready: dict[str, list[float]] = {name: [] for name in LAYOUTS}
    for row in conn.execute(
        """
        SELECT s.layout, r.views, r.likes, p.posted_at, r.read_at
        FROM posts p
        JOIN shorts s ON s.id = p.short_id
        JOIN sources src ON src.id = s.source_id
        JOIN reads r ON r.post_id = p.id
        WHERE src.niche = ? AND p.platform = 'youtube'
          AND r.views IS NOT NULL AND r.likes IS NOT NULL
        """,
        (niche,),
    ):
        posted = parse_time(row["posted_at"])
        read_at = parse_time(row["read_at"])
        if not posted or not read_at:
            continue
        if read_at - posted < timedelta(hours=24):
            continue
        views = int(row["views"] or 0)
        likes = int(row["likes"] or 0)
        if views <= 0:
            continue
        ready[row["layout"]].append(likes / views)
    if any(len(ready[name]) < 4 for name in LAYOUTS):
        counts = {
            name: conn.execute(
                """
                SELECT COUNT(*) FROM posts p
                JOIN shorts s ON s.id = p.short_id
                JOIN sources src ON src.id = s.source_id
                WHERE src.niche = ? AND s.layout = ?
                """,
                (niche, name),
            ).fetchone()[0]
            for name in LAYOUTS
        }
        layout = min(LAYOUTS, key=lambda name: (counts[name], LAYOUTS.index(name)))
        return layout, f"rotate to {layout} until each arm has 4 posts with a 24h read"
    medians = {
        name: sorted(vals)[len(vals) // 2]
        for name, vals in ready.items()
        if vals
    }
    layout = max(medians, key=lambda name: medians[name])
    return layout, f"pick {layout} with median likes/views {medians[layout]:.4f}"


def active_effect_slugs(conn: sqlite3.Connection, niche: str) -> list[str]:
    ensure_niche_effects(conn, niche)
    rows = conn.execute(
        """
        SELECT slug FROM niche_effects
        WHERE niche = ? AND pool = 'active'
        ORDER BY CASE WHEN slug = 'none' THEN 0 ELSE 1 END, slug
        """,
        (niche,),
    ).fetchall()
    return [row["slug"] for row in rows]


def effect_ratio_samples(conn: sqlite3.Connection, niche: str) -> dict[str, list[float]]:
    ready: dict[str, list[float]] = {}
    for row in conn.execute(
        """
        SELECT COALESCE(s.effect, 'none') AS effect, r.views, r.likes, p.posted_at, r.read_at
        FROM posts p
        JOIN shorts s ON s.id = p.short_id
        JOIN sources src ON src.id = s.source_id
        JOIN reads r ON r.post_id = p.id
        WHERE src.niche = ? AND p.platform = 'youtube'
          AND r.views IS NOT NULL AND r.likes IS NOT NULL
        """,
        (niche,),
    ):
        posted = parse_time(row["posted_at"])
        read_at = parse_time(row["read_at"])
        if not posted or not read_at:
            continue
        if read_at - posted < timedelta(hours=24):
            continue
        views = int(row["views"] or 0)
        likes = int(row["likes"] or 0)
        if views <= 0:
            continue
        ready.setdefault(row["effect"], []).append(likes / views)
    return ready


def choose_effect(
    conn: sqlite3.Connection,
    niche: str,
    plan: Any | None = None,
) -> tuple[str, str]:
    active = active_effect_slugs(conn, niche)
    if not active:
        return fxcat.CONTROL_SLUG, "no active effects; use none"
    skip_note = ""
    candidates = list(active)
    is_jump = False
    if plan is not None:
        mode = getattr(plan, "mode", None)
        reason_txt = str(getattr(plan, "reason", "") or "")
        is_jump = mode == "jump" or "jumps" in reason_txt
    if is_jump:
        blocked = [s for s in candidates if s in fxcat.JUMP_SKIP_SLUGS]
        if blocked:
            candidates = [s for s in candidates if s not in fxcat.JUMP_SKIP_SLUGS]
            skip_note = f"; skip {','.join(blocked)} on jump framing"
            if not candidates:
                return fxcat.CONTROL_SLUG, f"only jump-incompatible effects active; use none{skip_note}"
    ready = effect_ratio_samples(conn, niche)
    if any(len(ready.get(name, [])) < EFFECT_MIN_SAMPLES for name in candidates):
        counts = {
            name: conn.execute(
                """
                SELECT COUNT(*) FROM posts p
                JOIN shorts s ON s.id = p.short_id
                JOIN sources src ON src.id = s.source_id
                WHERE src.niche = ? AND COALESCE(s.effect, 'none') = ?
                """,
                (niche, name),
            ).fetchone()[0]
            for name in candidates
        }
        effect = min(candidates, key=lambda name: (counts[name], candidates.index(name)))
        return effect, f"rotate to {effect} until each active effect has {EFFECT_MIN_SAMPLES} posts with a 24h read{skip_note}"
    medians = {
        name: sorted(ready[name])[len(ready[name]) // 2]
        for name in candidates
        if ready.get(name)
    }
    if not medians:
        return candidates[0], f"pick {candidates[0]} (no scored samples yet){skip_note}"
    effect = max(medians, key=lambda name: medians[name])
    return effect, f"pick {effect} with median likes/views {medians[effect]:.4f}{skip_note}"


def subject_for_window(words: list[dict], start: float, end: float, max_chars: int = 280) -> str:
    parts = [
        str(w.get("text") or "").strip()
        for w in words
        if float(w.get("end") or 0) > start and float(w.get("start") or 0) < end
    ]
    text = " ".join(p for p in parts if p).strip()
    text = re.sub(r"\s+", " ", text)
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 1].rstrip() + "…"


def next_term(conn: sqlite3.Connection, niche: str, terms: list[str]) -> str:
    if not terms:
        return ""
    used = {
        row["term"]: row["c"]
        for row in conn.execute(
            "SELECT term, COUNT(*) AS c FROM sources WHERE niche = ? AND term IS NOT NULL GROUP BY term",
            (niche,),
        )
    }
    return min(terms, key=lambda t: (used.get(t, 0), terms.index(t)))


def pause_active(conn: sqlite3.Connection, niche: str) -> bool:
    now = utc_now()
    row = conn.execute(
        """
        SELECT until_at FROM pauses
        WHERE niche = ? AND platform = 'youtube' AND until_at > ?
        ORDER BY until_at DESC LIMIT 1
        """,
        (niche, now),
    ).fetchone()
    return bool(row)


def update_stuck_and_pause(conn: sqlite3.Connection, niche: str) -> None:
    now = datetime.now(timezone.utc)
    for row in conn.execute(
        """
        SELECT p.id AS post_id, p.posted_at, r.id AS read_id, r.views, r.read_at
        FROM posts p
        JOIN shorts s ON s.id = p.short_id
        JOIN sources src ON src.id = s.source_id
        JOIN reads r ON r.id = (
            SELECT id FROM reads WHERE post_id = p.id ORDER BY read_at DESC LIMIT 1
        )
        WHERE src.niche = ? AND p.platform = 'youtube'
        """,
        (niche,),
    ):
        posted = parse_time(row["posted_at"])
        if not posted or now - posted < timedelta(hours=1):
            continue
        if row["views"] is None:
            continue
        stuck = 1 if int(row["views"]) < 20 else 0
        conn.execute("UPDATE reads SET stuck = ? WHERE id = ?", (stuck, row["read_id"]))
    recent = conn.execute(
        """
        SELECT r.stuck FROM posts p
        JOIN shorts s ON s.id = p.short_id
        JOIN sources src ON src.id = s.source_id
        JOIN reads r ON r.id = (
            SELECT id FROM reads WHERE post_id = p.id ORDER BY read_at DESC LIMIT 1
        )
        WHERE src.niche = ? AND p.platform = 'youtube'
        ORDER BY p.posted_at DESC LIMIT 2
        """,
        (niche,),
    ).fetchall()
    if len(recent) == 2 and all(int(r["stuck"] or 0) == 1 for r in recent):
        until = (now + timedelta(hours=24)).replace(microsecond=0).isoformat()
        conn.execute(
            "INSERT INTO pauses (niche, platform, until_at, reason) VALUES (?, 'youtube', ?, ?)",
            (niche, until, "two stuck youtube posts in a row"),
        )
    conn.commit()


def read_stats(conn: sqlite3.Connection, token: str, niche: str) -> int:
    count = 0
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=6)).replace(microsecond=0).isoformat()
    rows = conn.execute(
        """
        SELECT p.id, p.platform_id FROM posts p
        JOIN shorts s ON s.id = p.short_id
        JOIN sources src ON src.id = s.source_id
        WHERE src.niche = ? AND p.platform = 'youtube' AND p.platform_id IS NOT NULL
          AND (
            NOT EXISTS (SELECT 1 FROM reads r WHERE r.post_id = p.id)
            OR (SELECT MAX(read_at) FROM reads r WHERE r.post_id = p.id) < ?
          )
        """,
        (niche, cutoff),
    ).fetchall()
    for row in rows:
        data = youtube_get(token, "videos", {"part": "statistics", "id": row["platform_id"]})
        if not data or not data.get("items"):
            continue
        stats = (data["items"][0].get("statistics") or {})
        views = int(stats["viewCount"]) if "viewCount" in stats else None
        likes = int(stats["likeCount"]) if "likeCount" in stats else None
        comments = int(stats["commentCount"]) if "commentCount" in stats else None
        conn.execute(
            """
            INSERT INTO reads (post_id, read_at, views, likes, comments, shares, stuck)
            VALUES (?, ?, ?, ?, ?, NULL, 0)
            """,
            (row["id"], utc_now(), views, likes, comments),
        )
        count += 1
    conn.commit()
    return count


def find_support(niche: Path, main_id: str, on_lane: list[str]) -> Path | None:
    sources = niche / "sources"
    if sources.is_dir():
        for path in sorted(sources.glob("*.mp4")):
            if path.stem == main_id:
                continue
            info = path.with_suffix(".info.json")
            title = path.stem
            desc = ""
            if info.is_file():
                try:
                    payload = json.loads(info.read_text(encoding="utf-8"))
                    title = str(payload.get("title") or title)
                    desc = str(payload.get("description") or "")
                except json.JSONDecodeError:
                    pass
            if on_lane_match(title, desc, on_lane):
                return path
    return shorts.pick_art(f"{niche.name}-{main_id}")


def seed_existing_source(conn: sqlite3.Connection, niche: Path) -> int | None:
    sources = niche / "sources"
    if not sources.is_dir():
        return None
    for path in sorted(sources.glob("*.mp4")):
        youtube_id = path.stem
        row = conn.execute(
            "SELECT id, status FROM sources WHERE niche = ? AND youtube_id = ?",
            (niche.name, youtube_id),
        ).fetchone()
        if row:
            if row["status"] == "new":
                return int(row["id"])
            continue
        title = youtube_id
        info = path.with_suffix(".info.json")
        if not info.is_file():
            alt = Path(str(path) + ".info.json")
            info = alt if alt.is_file() else info
        if info.is_file():
            try:
                title = str(json.loads(info.read_text(encoding="utf-8")).get("title") or title)
            except json.JSONDecodeError:
                pass
        dur = shorts.probe_duration(path)
        cur = conn.execute(
            """
            INSERT INTO sources (niche, youtube_id, url, title, duration_sec, term, status, found_at)
            VALUES (?, ?, ?, ?, ?, ?, 'new', ?)
            """,
            (
                niche.name,
                youtube_id,
                f"https://www.youtube.com/watch?v={youtube_id}",
                title,
                dur,
                "local-seed",
                utc_now(),
            ),
        )
        conn.commit()
        return int(cur.lastrowid)
    return None


def scout_source(conn: sqlite3.Connection, niche: Path, terms_doc: dict[str, Any]) -> int | None:
    existing = seed_existing_source(conn, niche)
    if existing:
        return existing
    waiting = conn.execute(
        """
        SELECT id, youtube_id FROM sources
        WHERE niche = ? AND status = 'new'
        ORDER BY found_at ASC LIMIT 1
        """,
        (niche.name,),
    ).fetchone()
    if waiting:
        path = source_path(niche, waiting["youtube_id"])
        if path.is_file():
            return int(waiting["id"])
    term = next_term(conn, niche.name, terms_doc["terms"])
    if not term:
        return None
    known = {
        row["youtube_id"]
        for row in conn.execute("SELECT youtube_id FROM sources WHERE niche = ?", (niche.name,))
    }
    picked = None
    for item in search_youtube(term):
        vid = str(item.get("id") or item.get("url") or "")
        m = re.search(r"([\w-]{11})$", vid) or re.search(r"(?:v=|youtu\.be/)([\w-]{11})", str(item.get("url") or ""))
        youtube_id = m.group(1) if m else (vid if re.fullmatch(r"[\w-]{11}", vid) else "")
        if not youtube_id or youtube_id in known:
            continue
        title = str(item.get("title") or "")
        desc = str(item.get("description") or "")
        duration = float(item.get("duration") or 0)
        if duration and (duration < 60 or duration > 4 * 3600):
            continue
        if not on_lane_match(title, desc, terms_doc["on_lane"]):
            continue
        picked = {
            "youtube_id": youtube_id,
            "url": f"https://www.youtube.com/watch?v={youtube_id}",
            "title": title,
            "duration": duration or None,
            "term": term,
        }
        break
    if not picked:
        row = conn.execute(
            "SELECT misses FROM term_misses WHERE niche = ? AND term = ?",
            (niche.name, term),
        ).fetchone()
        misses = int(row["misses"]) + 1 if row else 1
        conn.execute(
            """
            INSERT INTO term_misses (niche, term, misses) VALUES (?, ?, ?)
            ON CONFLICT(niche, term) DO UPDATE SET misses = excluded.misses
            """,
            (niche.name, term, misses),
        )
        conn.commit()
        if misses >= 3:
            retire_term(niche / "search-terms.md", term, misses)
        return None
    conn.execute(
        """
        INSERT INTO term_misses (niche, term, misses) VALUES (?, ?, 0)
        ON CONFLICT(niche, term) DO UPDATE SET misses = 0
        """,
        (niche.name, term),
    )
    dest = source_path(niche, picked["youtube_id"])
    ok = dest.is_file() or download_source(picked["url"], dest)
    status = "new" if ok else "download_failed"
    if ok and not picked["duration"]:
        picked["duration"] = shorts.probe_duration(dest)
    cur = conn.execute(
        """
        INSERT INTO sources (niche, youtube_id, url, title, duration_sec, term, status, found_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            niche.name,
            picked["youtube_id"],
            picked["url"],
            picked["title"],
            picked["duration"],
            picked["term"],
            status,
            utc_now(),
        ),
    )
    conn.commit()
    if status != "new":
        return None
    return int(cur.lastrowid)


def retire_term(path: Path, term: str, misses: int) -> None:
    text = path.read_text(encoding="utf-8")
    line = f"- `{term}`"
    if line not in text and f"- `{term}`" not in text:
        return
    text = text.replace(f"- `{term}`\n", "").replace(f"- `{term}`", "")
    stamp = datetime.now(timezone.utc).date().isoformat()
    note = f"\n- `{term}` — retired {stamp} after {misses} empty on-lane searches\n"
    if "## Retired" in text:
        text = text.replace("## Retired", "## Retired" + note, 1)
    else:
        text += "\n## Retired\n" + note
    path.write_text(text, encoding="utf-8")


def apply_niche_style(niche: Path) -> None:
    from render_style import resolve

    cfg = json.loads((niche / "config.json").read_text(encoding="utf-8"))
    shorts.STYLE.clear()
    shorts.STYLE.update(resolve(cfg))


def cut_one(
    conn: sqlite3.Connection,
    niche: Path,
    source_id: int,
    layout: str,
    on_lane: list[str],
) -> tuple[int | None, str, str]:
    """Cut one short. Returns (short_id, effect, effect_reason)."""
    src = conn.execute("SELECT * FROM sources WHERE id = ?", (source_id,)).fetchone()
    if not src:
        return None, fxcat.CONTROL_SLUG, "no source"
    video = source_path(niche, src["youtube_id"])
    if not video.is_file():
        conn.execute("UPDATE sources SET status = 'download_failed' WHERE id = ?", (source_id,))
        conn.commit()
        return None, fxcat.CONTROL_SLUG, "download missing"
    apply_niche_style(niche)
    ensure_niche_effects(conn, niche.name)
    payload = shorts.transcribe_hf(video)
    words = payload.get("words") or []
    windows = shorts.windows_from_transcript(payload, float(src["duration_sec"] or shorts.probe_duration(video)))
    used = {
        (round(float(r["start_sec"]), 2), round(float(r["end_sec"]), 2))
        for r in conn.execute(
            "SELECT start_sec, end_sec FROM shorts WHERE source_id = ? AND layout = ?",
            (source_id, layout),
        )
    }
    chosen = None
    for a, b in windows:
        if not (shorts.MIN_SHORT <= (b - a) <= shorts.MAX_SHORT):
            continue
        key = (round(a, 2), round(b, 2))
        if key in used:
            continue
        chosen = (a, b)
        break
    if not chosen:
        conn.execute("UPDATE sources SET status = 'cut' WHERE id = ?", (source_id,))
        conn.commit()
        return None, fxcat.CONTROL_SLUG, "no unused window"
    start, end = chosen
    cues = shorts.group_words(words, max_words=int(shorts.STYLE.get("words") or 3))
    section_cues = [c for c in cues if c["end"] > start and c["start"] < end]
    subject = subject_for_window(words, start, end)
    support = find_support(niche, src["youtube_id"], on_lane)
    title_slug = shorts.slug(src["title"] or src["youtube_id"]) or src["youtube_id"]
    out_dir = niche / title_slug
    out_dir.mkdir(parents=True, exist_ok=True)
    n = conn.execute("SELECT COUNT(*) FROM shorts WHERE source_id = ?", (source_id,)).fetchone()[0] + 1
    dest = out_dir / f"{title_slug}-s{n:02d}-{layout}.mp4"
    effect = fxcat.CONTROL_SLUG
    effect_reason = "none"
    with tempfile.TemporaryDirectory(prefix="ceo-") as td:
        work = Path(td)
        try:
            plan = shorts.plan_layout(
                video, start, end, layout, work, support=support, words=words,
            )
            picture = work / "picture.mp4"
            shorts.render_picture(video, start, end, plan, work, picture)
            effect, effect_reason = choose_effect(conn, niche.name, plan)
            effected = work / "effected.mp4"
            preset = fxcat.preset_by_slug(effect) or {"params": {}}
            fxcat.apply(picture, effected, effect, dict(preset.get("params") or {}))
            shorts.composite_top(
                effected, section_cues, start, end, work, dest, layout=layout,
            )
        except Exception as exc:
            print(f"render failed: {exc}", file=sys.stderr)
            return None, effect, f"render failed: {exc}"
        print(
            f"rendered {dest.name} {plan.summary()} effect={effect} "
            f"cues={len(section_cues)} subject_chars={len(subject)}"
        )
    frames = shorts.extract_qa_frames(dest, out_dir / f".qa-{dest.stem}")
    audio_n = shorts.audio_stream_count(dest)
    digest = sha256_file(dest)
    posts_n = conn.execute(
        """
        SELECT COUNT(*) FROM posts p
        JOIN shorts s ON s.id = p.short_id
        JOIN sources src ON src.id = s.source_id
        WHERE src.niche = ?
        """,
        (niche.name,),
    ).fetchone()[0]
    status = "awaiting_approval" if posts_n < 3 else "rendered"
    cur = conn.execute(
        """
        INSERT INTO shorts (
            source_id, layout, start_sec, end_sec, path, sha256, audio_streams,
            status, created_at, subject, effect
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            source_id,
            layout,
            start,
            end,
            str(dest.relative_to(ROOT)),
            digest,
            audio_n,
            status,
            utc_now(),
            subject,
            effect,
        ),
    )
    used.add((round(start, 2), round(end, 2)))
    more = False
    for a, b in windows:
        if not (shorts.MIN_SHORT <= (b - a) <= shorts.MAX_SHORT):
            continue
        if (round(a, 2), round(b, 2)) not in used:
            more = True
            break
    conn.execute(
        "UPDATE sources SET status = ? WHERE id = ?",
        ("new" if more else "cut", source_id),
    )
    conn.commit()
    print("qa frames:", ", ".join(str(p.relative_to(ROOT)) for p in frames))
    print(f"audio streams: {audio_n}")
    return int(cur.lastrowid), effect, effect_reason


def niche_for_short(conn: sqlite3.Connection, short_id: int) -> Path | None:
    row = conn.execute(
        """
        SELECT src.niche FROM shorts s
        JOIN sources src ON src.id = s.source_id
        WHERE s.id = ?
        """,
        (short_id,),
    ).fetchone()
    if not row:
        return None
    return resolve_niche(row["niche"])


def caption_for(conn: sqlite3.Connection, short_id: int) -> tuple[str, str, list[str]]:
    row = conn.execute(
        """
        SELECT s.*, src.title, src.youtube_id, src.niche
        FROM shorts s JOIN sources src ON src.id = s.source_id
        WHERE s.id = ?
        """,
        (short_id,),
    ).fetchone()
    base = (row["title"] or row["youtube_id"] or "clip")[:80]
    prefix = os.environ.get("YOUTUBE_TITLE_PREFIX", "").strip()
    if prefix and prefix not in base:
        title = f"{prefix} {base}".strip()
    else:
        title = base
    disclaimer = os.environ.get("YOUTUBE_DISCLAIMER", "").strip() or share.DEFAULT_DISCLAIMER
    effect = row["effect"] if "effect" in row.keys() else None
    effect_bit = f" · effect {effect}" if effect else ""
    description = (
        f"{row['niche']} short · layout {row['layout']}{effect_bit}\n\n"
        f"Source: https://www.youtube.com/watch?v={row['youtube_id']}\n\n"
        f"{disclaimer}"
    )
    tags_raw = os.environ.get("YOUTUBE_TAGS", "").strip()
    tags = [t.strip() for t in tags_raw.split(",") if t.strip()] if tags_raw else [row["niche"]]
    return title, description, tags


def last_effect_review_at(conn: sqlite3.Connection, niche: str) -> datetime | None:
    row = conn.execute(
        "SELECT MAX(reviewed_at) AS t FROM effect_reviews WHERE niche = ?",
        (niche,),
    ).fetchone()
    return parse_time(row["t"] if row else None)


def needs_effect_review(conn: sqlite3.Connection, niche: str) -> bool:
    last = last_effect_review_at(conn, niche)
    if not last:
        return True
    return datetime.now(timezone.utc) - last >= timedelta(days=EFFECT_REVIEW_DAYS)


def _median(vals: list[float]) -> float:
    ordered = sorted(vals)
    return ordered[len(ordered) // 2]


def review_effects(conn: sqlite3.Connection, niche: str) -> str:
    """Weekly prune: retire weak active effects, promote one bench preset."""
    ensure_niche_effects(conn, niche)
    now = utc_now()
    ready = effect_ratio_samples(conn, niche)
    active = active_effect_slugs(conn, niche)
    none_vals = ready.get(fxcat.CONTROL_SLUG, [])
    none_median = _median(none_vals) if len(none_vals) >= EFFECT_MIN_SAMPLES else None
    actions: list[str] = []

    if none_median is not None:
        for slug in list(active):
            if slug == fxcat.CONTROL_SLUG:
                continue
            vals = ready.get(slug, [])
            if len(vals) < EFFECT_MIN_SAMPLES:
                continue
            med = _median(vals)
            if none_median <= 0:
                continue
            if med >= EFFECT_RETIRE_RATIO * none_median:
                conn.execute(
                    """
                    INSERT INTO effect_reviews
                        (reviewed_at, niche, slug, action, samples, median_likes_views, reason)
                    VALUES (?, ?, ?, 'keep', ?, ?, ?)
                    """,
                    (
                        now,
                        niche,
                        slug,
                        len(vals),
                        med,
                        f"keep {slug}: median {med:.4f} vs none {none_median:.4f}",
                    ),
                )
                continue
            remaining = [s for s in active if s != slug]
            if len(remaining) < 2:  # none + at least one other
                conn.execute(
                    """
                    INSERT INTO effect_reviews
                        (reviewed_at, niche, slug, action, samples, median_likes_views, reason)
                    VALUES (?, ?, ?, 'keep', ?, ?, ?)
                    """,
                    (
                        now,
                        niche,
                        slug,
                        len(vals),
                        med,
                        f"keep {slug}: would drop below none+one",
                    ),
                )
                continue
            conn.execute(
                "UPDATE niche_effects SET pool = 'retired', updated_at = ? WHERE niche = ? AND slug = ?",
                (now, niche, slug),
            )
            reason = (
                f"retire {slug}: median {med:.4f} under "
                f"{EFFECT_RETIRE_RATIO:.0%} of none {none_median:.4f}"
            )
            conn.execute(
                """
                INSERT INTO effect_reviews
                    (reviewed_at, niche, slug, action, samples, median_likes_views, reason)
                VALUES (?, ?, ?, 'retire', ?, ?, ?)
                """,
                (now, niche, slug, len(vals), med, reason),
            )
            actions.append(reason)
            active = remaining
            # Promote oldest bench so active returns toward five including none.
            bench = conn.execute(
                """
                SELECT slug FROM niche_effects
                WHERE niche = ? AND pool = 'bench'
                ORDER BY updated_at ASC, slug ASC LIMIT 1
                """,
                (niche,),
            ).fetchone()
            if bench:
                conn.execute(
                    "UPDATE niche_effects SET pool = 'active', updated_at = ? WHERE niche = ? AND slug = ?",
                    (now, niche, bench["slug"]),
                )
                promote_reason = f"promote {bench['slug']} after retiring {slug}"
                conn.execute(
                    """
                    INSERT INTO effect_reviews
                        (reviewed_at, niche, slug, action, samples, median_likes_views, reason)
                    VALUES (?, ?, ?, 'promote', NULL, NULL, ?)
                    """,
                    (now, niche, bench["slug"], promote_reason),
                )
                actions.append(promote_reason)
                active.append(bench["slug"])
            break  # one retire per weekly pass

    if not actions:
        note = (
            f"no retire this week; none_samples={len(none_vals)}; "
            f"active={','.join(active)}"
        )
        conn.execute(
            """
            INSERT INTO effect_reviews
                (reviewed_at, niche, slug, action, samples, median_likes_views, reason)
            VALUES (?, ?, 'none', 'keep', ?, ?, ?)
            """,
            (
                now,
                niche,
                len(none_vals),
                none_median,
                note,
            ),
        )
        actions.append(note)

    summary = "; ".join(actions)
    conn.execute(
        "INSERT INTO decisions (decided_at, niche, layout, term, reason, effect) VALUES (?, ?, ?, ?, ?, ?)",
        (now, niche, None, None, f"effect review: {summary}", fxcat.CONTROL_SLUG),
    )
    conn.commit()
    return summary


def post_short(
    conn: sqlite3.Connection,
    short_id: int,
    auth: str,
    channel_id: str | None = None,
    channel_title: str | None = None,
) -> bool:
    if auth != "ok":
        print("auth blocked; not posting")
        return False
    row = conn.execute("SELECT * FROM shorts WHERE id = ?", (short_id,)).fetchone()
    if not row or not row["path"]:
        return False
    existing = conn.execute(
        "SELECT id FROM posts WHERE short_id = ? AND platform = 'youtube'",
        (short_id,),
    ).fetchone()
    if existing:
        print(f"already posted short {short_id}")
        return True
    path = ROOT / row["path"]
    if not path.is_file():
        print(f"missing file for short {short_id}: {path}")
        return False
    title, description, tags = caption_for(conn, short_id)
    try:
        result = share.publish_youtube_direct(path, title, description, tags, "public")
    except Exception as exc:
        print(f"youtube upload failed: {exc}", file=sys.stderr)
        conn.execute("UPDATE shorts SET status = 'failed' WHERE id = ?", (short_id,))
        conn.commit()
        return False
    platform_id = None
    if isinstance(result, dict):
        platform_id = result.get("id")
    url = f"https://www.youtube.com/watch?v={platform_id}" if platform_id else None
    conn.execute(
        """
        INSERT INTO posts (short_id, platform, platform_id, url, caption, posted_at, channel_id, channel_title)
        VALUES (?, 'youtube', ?, ?, ?, ?, ?, ?)
        """,
        (short_id, platform_id, url, title, utc_now(), channel_id, channel_title),
    )
    conn.execute("UPDATE shorts SET status = 'posted' WHERE id = ?", (short_id,))
    conn.commit()
    print(f"posted short {short_id} -> {url} (channel={channel_title or channel_id or '?'})")
    return True


def _effect_status_lines(conn: sqlite3.Connection) -> list[str]:
    lines: list[str] = []
    niches = [r["niche"] for r in conn.execute("SELECT DISTINCT niche FROM niche_effects ORDER BY niche")]
    if not niches:
        niches = [r["slug"] for r in conn.execute("SELECT slug FROM projects ORDER BY slug")]
    if not niches:
        return ["No effect pools yet."]
    for niche in niches:
        ensure_niche_effects(conn, niche)
        ready = effect_ratio_samples(conn, niche)
        active = active_effect_slugs(conn, niche)
        med_bits = []
        for slug in active:
            vals = ready.get(slug, [])
            if len(vals) >= EFFECT_MIN_SAMPLES:
                med_bits.append(f"{slug}={_median(vals):.4f}(n={len(vals)})")
            else:
                med_bits.append(f"{slug}=n={len(vals)}")
        bench = conn.execute(
            """
            SELECT slug FROM niche_effects
            WHERE niche = ? AND pool = 'bench'
            ORDER BY updated_at ASC, slug ASC LIMIT 1
            """,
            (niche,),
        ).fetchone()
        last = conn.execute(
            """
            SELECT reviewed_at, slug, action, reason FROM effect_reviews
            WHERE niche = ? ORDER BY id DESC LIMIT 1
            """,
            (niche,),
        ).fetchone()
        lines.append(f"- {niche} active: {', '.join(active)}")
        lines.append(f"  medians: {', '.join(med_bits) if med_bits else 'none yet'}")
        lines.append(f"  next bench: {bench['slug'] if bench else 'empty'}")
        if last:
            lines.append(
                f"  last review: {last['reviewed_at']} · {last['action']} {last['slug']} · {last['reason']}"
            )
        else:
            lines.append("  last review: never")
    return lines


def write_status(conn: sqlite3.Connection, summary: str) -> None:
    lines = ["# CEO status", "", f"Updated: {utc_now()}", "", summary, "", "## Projects", ""]
    projects = conn.execute(
        "SELECT slug, channel_id, channel_title, path FROM projects ORDER BY slug"
    ).fetchall()
    if not projects:
        lines.append("None registered yet.")
    for row in projects:
        lines.append(
            f"- {row['slug']} · channel={row['channel_title'] or 'unknown'} "
            f"({row['channel_id'] or 'no id'}) · {row['path']}"
        )
    lines.extend(["", "## Effects", ""])
    lines.extend(_effect_status_lines(conn))
    lines.extend(["", "## Recent posts", ""])
    rows = conn.execute(
        """
        SELECT p.posted_at, p.url, p.platform_id, p.channel_title, s.layout, s.effect, src.niche, src.title,
               (SELECT views FROM reads r WHERE r.post_id = p.id ORDER BY read_at DESC LIMIT 1) AS views,
               (SELECT likes FROM reads r WHERE r.post_id = p.id ORDER BY read_at DESC LIMIT 1) AS likes
        FROM posts p
        JOIN shorts s ON s.id = p.short_id
        JOIN sources src ON src.id = s.source_id
        ORDER BY p.posted_at DESC LIMIT 12
        """
    ).fetchall()
    if not rows:
        lines.append("None yet.")
    for row in rows:
        effect = row["effect"] or "none"
        lines.append(
            f"- {row['posted_at']} · {row['niche']} · {row['channel_title'] or 'channel?'} · "
            f"{row['layout']} · {effect} · views={row['views']} likes={row['likes']} · "
            f"{row['url'] or row['platform_id']}"
        )
    lines.extend(["", "## Awaiting approval", ""])
    waiting = conn.execute(
        """
        SELECT s.id, s.layout, s.effect, s.path, src.title, src.niche FROM shorts s
        JOIN sources src ON src.id = s.source_id
        WHERE s.status = 'awaiting_approval'
        ORDER BY s.id
        """
    ).fetchall()
    if not waiting:
        lines.append("None.")
    for row in waiting:
        lines.append(
            f"- short {row['id']} · {row['niche']} · {row['layout']} · "
            f"{row['effect'] or 'none'} · {row['path']} · {row['title']}"
        )
    lines.extend(["", "## Last decisions", ""])
    for row in conn.execute("SELECT * FROM decisions ORDER BY id DESC LIMIT 8"):
        effect = row["effect"] if "effect" in row.keys() else None
        layout = row["layout"] or "—"
        effect_bit = f" · {effect}" if effect else ""
        lines.append(
            f"- {row['decided_at']} · {row['niche']} · {layout}{effect_bit} · {row['reason']}"
        )
    STATUS_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")


def cmd_status(_: argparse.Namespace) -> int:
    connect()
    if STATUS_PATH.is_file():
        print(STATUS_PATH.read_text(encoding="utf-8"))
    else:
        print("no status yet; run python3 tools/ceo.py run")
    return 0


def cmd_review(args: argparse.Namespace) -> int:
    conn = connect()
    niche = resolve_niche(getattr(args, "project", None)) if getattr(args, "project", None) else None
    niches = [niche] if niche else niche_dirs()
    if not niches:
        print("No niche folder with both config.json and search-terms.md.", file=sys.stderr)
        return 1
    notes = []
    for path in niches:
        upsert_project(conn, path)
        note = review_effects(conn, path.name)
        notes.append(f"{path.name}: {note}")
        print(notes[-1])
    write_status(conn, "Effect review: " + " | ".join(notes))
    return 0


def cmd_approve(args: argparse.Namespace) -> int:
    conn = connect()
    short_id = int(args.short_id)
    row = conn.execute("SELECT * FROM shorts WHERE id = ?", (short_id,)).fetchone()
    if not row:
        print(f"unknown short {short_id}", file=sys.stderr)
        return 1
    niche = niche_for_short(conn, short_id)
    if not niche:
        print(f"no niche folder for short {short_id}", file=sys.stderr)
        return 1
    conn.execute(
        "UPDATE shorts SET status = 'rendered' WHERE id = ? AND status = 'awaiting_approval'",
        (short_id,),
    )
    conn.commit()
    token, auth = youtube_refresh(niche)
    channel_id = channel_title = None
    if auth == "ok" and token:
        channel_id, channel_title = fetch_channel(token)
        upsert_project(conn, niche, channel_id, channel_title)
    ok = post_short(conn, short_id, auth, channel_id, channel_title)
    write_status(conn, f"Approved short {short_id} for {niche.name}; posted={ok}.")
    return 0 if ok or auth == "blocked" else 1


def cmd_run(args: argparse.Namespace) -> int:
    conn = connect()
    started = utc_now()
    cur = conn.execute(
        "INSERT INTO runs (started_at, host, auth) VALUES (?, ?, ?)",
        (started, HOST, None),
    )
    run_id = int(cur.lastrowid)
    conn.commit()
    niche = pick_niche(conn, getattr(args, "project", None))
    if not niche:
        summary = "No niche folder with both config.json and search-terms.md."
        conn.execute(
            "UPDATE runs SET finished_at = ?, summary = ?, auth = ? WHERE id = ?",
            (utc_now(), summary, "blocked", run_id),
        )
        conn.commit()
        write_status(conn, summary)
        print(summary)
        return 1
    upsert_project(conn, niche)
    terms_doc = parse_terms(niche / "search-terms.md")
    token, auth = youtube_refresh(niche)
    channel_id = channel_title = None
    if auth == "ok" and token:
        channel_id, channel_title = fetch_channel(token)
        upsert_project(conn, niche, channel_id, channel_title)
    conn.execute(
        "UPDATE runs SET niche = ?, auth = ?, channel_id = ?, channel_title = ? WHERE id = ?",
        (niche.name, auth, channel_id, channel_title, run_id),
    )
    conn.commit()
    reads_n = 0
    if auth == "ok" and token:
        reads_n = read_stats(conn, token, niche.name)
        update_stuck_and_pause(conn, niche.name)
    ensure_niche_effects(conn, niche.name)
    review_note = ""
    if needs_effect_review(conn, niche.name):
        review_note = review_effects(conn, niche.name)
        print(f"effect review: {review_note}")
    layout, reason = choose_layout(conn, niche.name)
    term = next_term(conn, niche.name, terms_doc["terms"])
    cur_decision = conn.execute(
        "INSERT INTO decisions (decided_at, niche, layout, term, reason, effect) VALUES (?, ?, ?, ?, ?, ?)",
        (utc_now(), niche.name, layout, term, reason, None),
    )
    decision_id = int(cur_decision.lastrowid)
    conn.commit()
    source_id = scout_source(conn, niche, terms_doc)
    if not source_id:
        summary = (
            f"{niche.name}: no source available this run "
            f"(auth={auth}; channel={channel_title or 'unknown'})."
        )
        conn.execute(
            "UPDATE runs SET finished_at = ?, summary = ? WHERE id = ?",
            (utc_now(), summary, run_id),
        )
        conn.commit()
        write_status(conn, summary)
        print(summary)
        return 0
    short_id, effect, effect_reason = cut_one(
        conn, niche, source_id, layout, terms_doc["on_lane"]
    )
    combined = f"{reason} | effect {effect}: {effect_reason}"
    if review_note:
        combined = f"{combined} | review: {review_note}"
    conn.execute(
        "UPDATE decisions SET effect = ?, reason = ? WHERE id = ?",
        (effect, combined, decision_id),
    )
    conn.commit()
    posted = False
    if short_id:
        row = conn.execute("SELECT status FROM shorts WHERE id = ?", (short_id,)).fetchone()
        if row and row["status"] == "rendered" and not pause_active(conn, niche.name):
            posted = post_short(conn, short_id, auth, channel_id, channel_title)
        elif row and row["status"] == "awaiting_approval":
            print(f"short {short_id} awaiting approval")
    best = conn.execute(
        """
        SELECT r.views, r.likes, s.layout, s.effect FROM posts p
        JOIN shorts s ON s.id = p.short_id
        JOIN sources src ON src.id = s.source_id
        JOIN reads r ON r.post_id = p.id
        WHERE src.niche = ? AND r.views IS NOT NULL
        ORDER BY r.views DESC LIMIT 1
        """,
        (niche.name,),
    ).fetchone()
    best_bits = (
        f"best views={best['views']} likes={best['likes']} "
        f"layout={best['layout']} effect={best['effect'] or 'none'}"
        if best
        else "no stats yet"
    )
    summary = (
        f"{niche.name}: channel={channel_title or 'unknown'}; layout={layout}; "
        f"effect={effect}; short={short_id}; posted={posted}; reads={reads_n}; "
        f"auth={auth}; {best_bits}"
    )
    conn.execute(
        "UPDATE runs SET finished_at = ?, summary = ? WHERE id = ?",
        (utc_now(), summary, run_id),
    )
    conn.commit()
    write_status(conn, summary)
    print(summary)
    if short_id:
        row = conn.execute("SELECT path, status FROM shorts WHERE id = ?", (short_id,)).fetchone()
        if row and row["status"] == "awaiting_approval" and row["path"]:
            (DATA / "awaiting-short.txt").write_text(f"{short_id}\n{row['path']}\n", encoding="utf-8")
        elif (DATA / "awaiting-short.txt").is_file():
            (DATA / "awaiting-short.txt").unlink()
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)
    run = sub.add_parser("run", help="One scout/cut/post cycle")
    run.add_argument(
        "--project",
        help='Niche folder name, e.g. "Aquarius Academy" or Gudasol',
    )
    sub.add_parser("status", help="Print data/ceo-status.md")
    review = sub.add_parser("review", help="Weekly effect prune/promote for a niche")
    review.add_argument(
        "--project",
        help='Niche folder name, e.g. "Aquarius Academy" or Gudasol (default: all)',
    )
    approve = sub.add_parser("approve", help="Approve and post a short id")
    approve.add_argument("short_id")
    args = parser.parse_args()
    if args.cmd == "run":
        return cmd_run(args)
    if args.cmd == "status":
        return cmd_status(args)
    if args.cmd == "review":
        return cmd_review(args)
    return cmd_approve(args)


if __name__ == "__main__":
    raise SystemExit(main())
