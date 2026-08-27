#!/usr/bin/env python3
"""Publish Shorts to social APIs through Nango.

Secrets stay in gitignored .env and nango/. Authorize each integration at
https://app.nango.dev, then put connection IDs in nango/connections.json.

  python3 tools/share_shorts.py platforms
  python3 tools/share_shorts.py status
  python3 tools/share_shorts.py share Shorts/clip.mp4 --to youtube,tiktok --title "Title"
"""

from __future__ import annotations

import argparse
import json
import os
import ssl
import subprocess
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

try:
    import certifi
except ImportError:  # pragma: no cover
    certifi = None  # type: ignore


def https_opener() -> urllib.request.OpenerDirector:
    context = ssl.create_default_context(cafile=certifi.where() if certifi else None)
    return urllib.request.build_opener(urllib.request.HTTPSHandler(context=context))

ROOT = Path(__file__).resolve().parents[1]
NANGO_DIR = ROOT / "nango"
CONNECTIONS_PATH = NANGO_DIR / "connections.json"
EXAMPLE_CONNECTIONS = Path(__file__).resolve().parent / "share_connections.example.json"
ENV_PATH = ROOT / ".env"
DEFAULT_DISCLAIMER = (
    "This work was not created by Gudasol and was not explicitly authorized "
    "by Gudasol as an official release. AI-generated. Gudasol AI."
)

PLATFORMS: dict[str, dict[str, Any]] = {
    "youtube": {
        "label": "YouTube / YouTube Shorts",
        "aspects": ("9:16", "16:9"),
        "needs": "YouTube Data API resumable upload. 9:16 + Shorts in the title lands as a Short.",
        "public_url": False,
    },
    "tiktok": {
        "label": "TikTok",
        "aspects": ("9:16",),
        "needs": "tiktok-personal (or tiktok-accounts) with publish scope. Uploads the local file.",
        "public_url": False,
    },
    "instagram": {
        "label": "Instagram Reels",
        "aspects": ("9:16",),
        "needs": "Facebook Graph connection plus ig_user_id. Meta fetches a public --url.",
        "public_url": True,
    },
    "linkedin": {
        "label": "LinkedIn",
        "aspects": ("16:9", "9:16"),
        "needs": "linkedin with w_member_social. Uploads the local file, then creates a post.",
        "public_url": False,
    },
    "facebook": {
        "label": "Facebook Page",
        "aspects": ("16:9", "9:16"),
        "needs": "facebook connection plus page_id. create-page-video with a public --url.",
        "public_url": True,
    },
    "x": {
        "label": "X (Twitter)",
        "aspects": ("16:9", "9:16"),
        "needs": "twitter-v2 connection. Tweets text plus --url until chunked upload is added.",
        "public_url": True,
    },
    "pinterest": {
        "label": "Pinterest",
        "aspects": ("16:9", "9:16"),
        "needs": "pinterest connection plus board_id. Pin from a public --url.",
        "public_url": True,
    },
}


def die(message: str, code: int = 1) -> None:
    print(message, file=sys.stderr)
    raise SystemExit(code)


def load_env(path: Path) -> None:
    if not path.is_file():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip("'").strip('"'))


def http_request(
    method: str,
    url: str,
    *,
    json_body: Any | None = None,
    data: bytes | None = None,
    headers: dict[str, str] | None = None,
    params: dict[str, Any] | None = None,
    timeout: int = 120,
) -> tuple[int, dict[str, str], Any]:
    if params:
        url += ("&" if "?" in url else "?") + urllib.parse.urlencode(params)
    hdrs: dict[str, str] = {}
    body = data
    if json_body is not None:
        hdrs["Content-Type"] = "application/json"
        body = json.dumps(json_body).encode("utf-8")
    if headers:
        hdrs.update(headers)
    req = urllib.request.Request(url, data=body, headers=hdrs, method=method)
    try:
        with https_opener().open(req, timeout=timeout) as resp:
            raw = resp.read()
            try:
                parsed: Any = json.loads(raw.decode("utf-8") or "null")
            except json.JSONDecodeError:
                parsed = raw
            return resp.status, {k.lower(): v for k, v in resp.headers.items()}, parsed
    except urllib.error.HTTPError as exc:
        err = exc.read().decode("utf-8", errors="replace")
        try:
            parsed = json.loads(err)
        except json.JSONDecodeError:
            parsed = err
        raise RuntimeError(f"{method} {url} -> {exc.code}: {parsed}") from exc


def youtube_access_token() -> str:
    load_env(ENV_PATH)
    token = os.environ.get("YOUTUBE_ACCESS_TOKEN", "").strip()
    refresh = os.environ.get("YOUTUBE_REFRESH_TOKEN", "").strip()
    client_id = os.environ.get("YOUTUBE_CLIENT_ID", "").strip()
    client_secret = os.environ.get("YOUTUBE_CLIENT_SECRET", "").strip()
    if refresh and client_id and client_secret:
        _, _, body = http_request(
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
        if isinstance(body, dict) and body.get("access_token"):
            return str(body["access_token"])
    return token


class Nango:
    def __init__(self, api_key: str, host: str) -> None:
        self.api_key = api_key
        self.host = host.rstrip("/")

    def request(
        self,
        method: str,
        path: str,
        *,
        json_body: Any | None = None,
        data: bytes | None = None,
        headers: dict[str, str] | None = None,
        params: dict[str, Any] | None = None,
        timeout: int = 120,
    ) -> tuple[int, dict[str, str], Any]:
        url = path if path.startswith("http") else f"{self.host}{path}"
        if params:
            url += ("&" if "?" in url else "?") + urllib.parse.urlencode(params)
        hdrs = {"Authorization": f"Bearer {self.api_key}"}
        body = data
        if json_body is not None:
            hdrs["Content-Type"] = "application/json"
            body = json.dumps(json_body).encode("utf-8")
        if headers:
            hdrs.update(headers)
        req = urllib.request.Request(url, data=body, headers=hdrs, method=method)
        try:
            with https_opener().open(req, timeout=timeout) as resp:
                raw = resp.read()
                try:
                    parsed: Any = json.loads(raw.decode("utf-8") or "null")
                except json.JSONDecodeError:
                    parsed = raw
                return resp.status, {k.lower(): v for k, v in resp.headers.items()}, parsed
        except urllib.error.HTTPError as exc:
            err = exc.read().decode("utf-8", errors="replace")
            try:
                parsed = json.loads(err)
            except json.JSONDecodeError:
                parsed = err
            raise RuntimeError(f"{method} {url} -> {exc.code}: {parsed}") from exc

    def get(self, path: str, **kwargs: Any) -> Any:
        return self.request("GET", path, **kwargs)[2]

    def list_connections(self) -> list[dict[str, Any]]:
        payload = self.get("/connections")
        if isinstance(payload, dict):
            return list(payload.get("connections") or payload.get("data") or [])
        return []

    def list_integrations(self) -> list[dict[str, Any]]:
        payload = self.get("/integrations")
        if isinstance(payload, dict):
            return list(payload.get("data") or payload.get("configs") or [])
        return []

    def trigger(
        self,
        integration_id: str,
        connection_id: str,
        action_name: str,
        input_data: dict[str, Any] | None = None,
    ) -> Any:
        return self.request(
            "POST",
            "/action/trigger",
            json_body={"action_name": action_name, "input": input_data or {}},
            headers={
                "Connection-Id": connection_id,
                "Provider-Config-Key": integration_id,
            },
        )[2]

    def proxy(
        self,
        method: str,
        integration_id: str,
        connection_id: str,
        endpoint: str,
        **kwargs: Any,
    ) -> tuple[int, dict[str, str], Any]:
        if not endpoint.startswith("/"):
            endpoint = "/" + endpoint
        extra = kwargs.pop("headers", {}) or {}
        headers = {
            "Connection-Id": connection_id,
            "Provider-Config-Key": integration_id,
            **extra,
        }
        return self.request(method, f"/proxy{endpoint}", headers=headers, **kwargs)


def ensure_local_dir() -> None:
    NANGO_DIR.mkdir(parents=True, exist_ok=True)
    if not CONNECTIONS_PATH.exists() and EXAMPLE_CONNECTIONS.exists():
        CONNECTIONS_PATH.write_text(EXAMPLE_CONNECTIONS.read_text(encoding="utf-8"), encoding="utf-8")


def load_connections() -> dict[str, Any]:
    ensure_local_dir()
    load_env(ENV_PATH)
    local: dict[str, Any] = {}
    if CONNECTIONS_PATH.is_file():
        loaded = json.loads(CONNECTIONS_PATH.read_text(encoding="utf-8"))
        if isinstance(loaded, dict):
            local = loaded
    env_map = {
        "youtube": {
            "integration_id": "NANGO_YOUTUBE_INTEGRATION_ID",
            "connection_id": "NANGO_YOUTUBE_CONNECTION_ID",
        },
        "tiktok": {
            "integration_id": "NANGO_TIKTOK_INTEGRATION_ID",
            "connection_id": "NANGO_TIKTOK_CONNECTION_ID",
        },
        "instagram": {
            "integration_id": "NANGO_INSTAGRAM_INTEGRATION_ID",
            "connection_id": "NANGO_INSTAGRAM_CONNECTION_ID",
            "ig_user_id": "NANGO_INSTAGRAM_IG_USER_ID",
        },
        "linkedin": {
            "integration_id": "NANGO_LINKEDIN_INTEGRATION_ID",
            "connection_id": "NANGO_LINKEDIN_CONNECTION_ID",
        },
        "facebook": {
            "integration_id": "NANGO_FACEBOOK_INTEGRATION_ID",
            "connection_id": "NANGO_FACEBOOK_CONNECTION_ID",
            "page_id": "NANGO_FACEBOOK_PAGE_ID",
        },
        "x": {
            "integration_id": "NANGO_X_INTEGRATION_ID",
            "connection_id": "NANGO_X_CONNECTION_ID",
        },
        "pinterest": {
            "integration_id": "NANGO_PINTEREST_INTEGRATION_ID",
            "connection_id": "NANGO_PINTEREST_CONNECTION_ID",
            "board_id": "NANGO_PINTEREST_BOARD_ID",
        },
    }
    for name, fields in env_map.items():
        cfg = dict(local.get(name) or {}) if isinstance(local.get(name), dict) else {}
        for key, env_name in fields.items():
            value = os.environ.get(env_name, "").strip()
            if value:
                cfg[key] = value
        local[name] = cfg
    return local


def nango_client() -> Nango:
    load_env(ENV_PATH)
    key = os.environ.get("NANGO_API_KEY", "").strip()
    if not key:
        die("Missing NANGO_API_KEY. Put it in .env (gitignored).")
    host = os.environ.get("NANGO_HOST", "https://api.nango.dev").strip()
    return Nango(key, host)


PROVIDER_HINTS = {
    "youtube": ("youtube",),
    "tiktok": ("tiktok-personal", "tiktok-accounts", "tiktok"),
    "instagram": ("facebook", "instagram"),
    "linkedin": ("linkedin",),
    "facebook": ("facebook",),
    "x": ("twitter-v2", "twitter"),
    "pinterest": ("pinterest",),
}


def save_connections(local: dict[str, Any]) -> None:
    ensure_local_dir()
    CONNECTIONS_PATH.write_text(json.dumps(local, indent=2) + "\n", encoding="utf-8")


def require_cfg(local: dict[str, Any], name: str, client: Nango | None = None) -> dict[str, Any]:
    cfg = local.get(name) or {}
    if not isinstance(cfg, dict):
        die(f"{name} in {CONNECTIONS_PATH} must be an object.")
    cfg = dict(cfg)
    if not (cfg.get("connection_id") or "").strip() and client is not None:
        hints = PROVIDER_HINTS.get(name, (name,))
        for row in client.list_connections():
            provider = str(row.get("provider") or "").lower()
            integration = str(
                row.get("provider_config_key") or row.get("providerConfigKey") or ""
            ).lower()
            if provider in hints or integration in hints or any(h in integration for h in hints):
                cfg["connection_id"] = str(row.get("connection_id") or row.get("connectionId") or "")
                cfg["integration_id"] = str(
                    row.get("provider_config_key")
                    or row.get("providerConfigKey")
                    or cfg.get("integration_id")
                    or ""
                )
                local[name] = {**cfg}
                save_connections(local)
                print(f"using Nango {name} connection {cfg['connection_id']} ({cfg['integration_id']})")
                break
    if not (cfg.get("connection_id") or "").strip():
        die(
            f"{name} is missing connection_id in {CONNECTIONS_PATH}. "
            "Authorize the app in Nango, then paste the connection ID."
        )
    if not (cfg.get("integration_id") or "").strip():
        die(f"{name} is missing integration_id in {CONNECTIONS_PATH}.")
    return cfg


def letterbox_16x9(src: Path) -> Path:
    out = Path(tempfile.mkdtemp(prefix="share-16x9-")) / (src.stem + "-16x9.mp4")
    cmd = [
        "ffmpeg",
        "-y",
        "-i",
        str(src),
        "-vf",
        "scale=1920:1080:force_original_aspect_ratio=decrease,pad=1920:1080:(ow-iw)/2:(oh-ih)/2:black",
        "-c:v",
        "libx264",
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "aac",
        str(out),
    ]
    subprocess.run(cmd, check=True)
    return out


def publish_youtube(
    client: Nango,
    cfg: dict[str, Any],
    video: Path,
    title: str,
    description: str,
    tags: list[str],
    privacy: str,
) -> Any:
    size = video.stat().st_size
    body = {
        "snippet": {
            "title": title,
            "description": description,
            "tags": tags,
            "categoryId": "22",
        },
        "status": {"privacyStatus": privacy, "selfDeclaredMadeForKids": False},
    }
    status, headers, _ = client.proxy(
        "POST",
        cfg["integration_id"],
        cfg["connection_id"],
        "/upload/youtube/v3/videos",
        params={"uploadType": "resumable", "part": "snippet,status"},
        json_body=body,
        headers={
            "X-Upload-Content-Length": str(size),
            "X-Upload-Content-Type": "video/mp4",
        },
    )
    location = headers.get("location")
    if not location:
        die(f"YouTube did not return an upload Location header (HTTP {status}).")
    parsed = urllib.parse.urlparse(location)
    endpoint = parsed.path + (f"?{parsed.query}" if parsed.query else "")
    _, _, result = client.proxy(
        "PUT",
        cfg["integration_id"],
        cfg["connection_id"],
        endpoint,
        data=video.read_bytes(),
        headers={"Content-Type": "video/mp4"},
        timeout=600,
    )
    return result


def publish_youtube_direct(
    video: Path,
    title: str,
    description: str,
    tags: list[str],
    privacy: str,
) -> Any:
    token = youtube_access_token()
    if not token:
        die("Missing YOUTUBE_ACCESS_TOKEN in .env")
    size = video.stat().st_size
    body = {
        "snippet": {
            "title": title[:100],
            "description": description,
            "tags": tags,
            "categoryId": "22",
        },
        "status": {"privacyStatus": privacy, "selfDeclaredMadeForKids": False},
    }
    status, headers, _ = http_request(
        "POST",
        "https://www.googleapis.com/upload/youtube/v3/videos",
        params={"uploadType": "resumable", "part": "snippet,status"},
        json_body=body,
        headers={
            "Authorization": f"Bearer {token}",
            "X-Upload-Content-Length": str(size),
            "X-Upload-Content-Type": "video/mp4",
        },
    )
    location = headers.get("location")
    if not location:
        die(f"YouTube did not return an upload Location header (HTTP {status}).")
    _, _, result = http_request(
        "PUT",
        location,
        data=video.read_bytes(),
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "video/mp4",
        },
        timeout=600,
    )
    return result


def publish_tiktok(client: Nango, cfg: dict[str, Any], video: Path, title: str) -> Any:
    size = video.stat().st_size
    init = client.trigger(
        cfg["integration_id"],
        cfg["connection_id"],
        "init-video-upload",
        {
            "post_info": {
                "title": title,
                "privacy_level": cfg.get("privacy_level") or "PUBLIC_TO_EVERYONE",
                "is_aigc": True,
            },
            "source_info": {
                "source": "FILE_UPLOAD",
                "video_size": size,
                "chunk_size": size,
                "total_chunk_count": 1,
            },
            "post_mode": "DIRECT_POST",
            "media_type": "VIDEO",
        },
    )
    upload_url = None
    if isinstance(init, dict):
        upload_url = init.get("upload_url") or (init.get("data") or {}).get("upload_url")
    if not upload_url:
        die(f"TikTok init-video-upload did not return upload_url: {init}")
    req = urllib.request.Request(
        upload_url,
        data=video.read_bytes(),
        method="PUT",
        headers={
            "Content-Type": "video/mp4",
            "Content-Length": str(size),
            "Content-Range": f"bytes 0-{size - 1}/{size}",
        },
    )
    with urllib.request.urlopen(req, timeout=600) as resp:
        raw = resp.read().decode("utf-8", errors="replace")
    return {"init": init, "upload_status": raw or "ok"}


def publish_linkedin(client: Nango, cfg: dict[str, Any], video: Path, title: str, text: str) -> Any:
    owner_id = (cfg.get("owner_id") or "").strip()
    if not owner_id:
        me = client.proxy("GET", cfg["integration_id"], cfg["connection_id"], "/v2/userinfo")[2]
        owner_id = (me or {}).get("sub") if isinstance(me, dict) else ""
        if not owner_id:
            die("LinkedIn owner_id missing and /v2/userinfo did not return sub.")
    size = video.stat().st_size
    init_body = {
        "initializeUploadRequest": {
            "owner": f"urn:li:person:{owner_id}",
            "fileSizeBytes": size,
            "uploadCaptions": False,
            "uploadThumbnail": False,
        }
    }
    _, _, init = client.proxy(
        "POST",
        cfg["integration_id"],
        cfg["connection_id"],
        "/rest/videos",
        params={"action": "initializeUpload"},
        json_body=init_body,
        headers={"LinkedIn-Version": "202405", "X-Restli-Protocol-Version": "2.0.0"},
    )
    value = (init or {}).get("value") if isinstance(init, dict) else {}
    upload_url = (value or {}).get("uploadUrl")
    video_urn = (value or {}).get("video")
    if not upload_url or not video_urn:
        die(f"LinkedIn initializeUpload missing uploadUrl/video: {init}")
    req = urllib.request.Request(
        upload_url,
        data=video.read_bytes(),
        method="PUT",
        headers={"Content-Type": "application/octet-stream"},
    )
    with urllib.request.urlopen(req, timeout=600):
        pass
    posted = client.trigger(
        cfg["integration_id"],
        cfg["connection_id"],
        "post",
        {"text": text, "videoURN": video_urn, "videoTitle": title, "ownerId": owner_id},
    )
    return {"video_urn": video_urn, "post": posted}


def publish_instagram(client: Nango, cfg: dict[str, Any], public_url: str, caption: str) -> Any:
    ig_user_id = (cfg.get("ig_user_id") or "").strip()
    if not ig_user_id:
        die("instagram.ig_user_id is required in nango/connections.json")
    _, _, container = client.proxy(
        "POST",
        cfg["integration_id"],
        cfg["connection_id"],
        f"/{ig_user_id}/media",
        params={
            "media_type": "REELS",
            "video_url": public_url,
            "caption": caption,
            "share_to_feed": "true",
        },
    )
    creation_id = (container or {}).get("id") if isinstance(container, dict) else None
    if not creation_id:
        die(f"Instagram media container missing id: {container}")
    _, _, published = client.proxy(
        "POST",
        cfg["integration_id"],
        cfg["connection_id"],
        f"/{ig_user_id}/media_publish",
        params={"creation_id": creation_id},
    )
    return {"container": container, "published": published}


def publish_facebook(client: Nango, cfg: dict[str, Any], public_url: str, title: str, description: str) -> Any:
    page_id = (cfg.get("page_id") or "").strip()
    if not page_id:
        die("facebook.page_id is required in nango/connections.json")
    return client.trigger(
        cfg["integration_id"],
        cfg["connection_id"],
        "create-page-video",
        {"page_id": page_id, "file_url": public_url, "title": title, "description": description},
    )


def publish_x(client: Nango, cfg: dict[str, Any], public_url: str, text: str) -> Any:
    _, _, result = client.proxy(
        "POST",
        cfg["integration_id"],
        cfg["connection_id"],
        "/2/tweets",
        json_body={"text": f"{text}\n{public_url}".strip()},
    )
    return result


def publish_pinterest(client: Nango, cfg: dict[str, Any], public_url: str, title: str, description: str) -> Any:
    board_id = (cfg.get("board_id") or "").strip()
    if not board_id:
        die("pinterest.board_id is required in nango/connections.json")
    registered = client.trigger(
        cfg["integration_id"],
        cfg["connection_id"],
        "register-media-upload",
        {"media_type": "video"},
    )
    return client.trigger(
        cfg["integration_id"],
        cfg["connection_id"],
        "create-pin",
        {
            "board_id": board_id,
            "title": title,
            "description": description,
            "media_source": {"source_type": "video_id", "url": public_url},
            "link": public_url,
            "registered": registered,
        },
    )


def cmd_platforms(_: argparse.Namespace) -> None:
    print("Platforms this repo can publish to through Nango:\n")
    for key, meta in PLATFORMS.items():
        aspects = ", ".join(meta["aspects"])
        print(f"  {key:12} {meta['label']}")
        print(f"               aspect {aspects}")
        print(f"               {meta['needs']}\n")
    print("Shorts in this project are 9:16. Use --aspect 16:9 to letterbox for landscape feeds.")
    print("Instagram, Facebook, X, and Pinterest need a public --url the platform can fetch.")


def cmd_status(_: argparse.Namespace) -> None:
    client = nango_client()
    local = load_connections()
    print("Nango integrations:")
    try:
        rows = client.list_integrations()
        if not rows:
            print("  none yet — add them at https://app.nango.dev/dev/integrations")
        for row in rows:
            key = row.get("unique_key") or row.get("uniqueKey")
            provider = row.get("provider")
            print(f"  {key}  (provider={provider})")
    except Exception as exc:
        print(f"  could not list integrations: {exc}")
    print("\nNango connections:")
    try:
        conns = client.list_connections()
        if not conns:
            print("  none yet — add them at https://app.nango.dev/dev/connections")
        for row in conns:
            print(
                f"  {row.get('provider_config_key') or row.get('providerConfigKey')}  "
                f"connection_id={row.get('connection_id') or row.get('connectionId')}  "
                f"provider={row.get('provider')}"
            )
    except Exception as exc:
        print(f"  could not list connections: {exc}")
    print(f"\nLocal map: {CONNECTIONS_PATH}")
    for name in PLATFORMS:
        cfg = local.get(name) or {}
        cid = (cfg.get("connection_id") or "").strip() if isinstance(cfg, dict) else ""
        print(f"  {name:12} {'ready' if cid else 'needs connection_id'}")


def cmd_share(args: argparse.Namespace) -> None:
    video = Path(args.video).expanduser()
    if not video.is_file():
        die(f"Video not found: {video}")
    names = [n.strip().lower() for n in args.to.split(",") if n.strip()]
    if names == ["all"]:
        names = list(PLATFORMS)
    unknown = [n for n in names if n not in PLATFORMS]
    if unknown:
        die(f"Unknown platform(s): {', '.join(unknown)}")
    title = args.title or video.stem.replace("-", " ")
    if "Gudasol AI" not in title:
        title = f"Gudasol AI | {title}"
    description = (args.description or args.caption or "").strip()
    if DEFAULT_DISCLAIMER.lower() not in description.lower():
        description = f"{description}\n\n{DEFAULT_DISCLAIMER}".strip()
    tags = [t.strip() for t in (args.tags or "Gudasol AI,EASY").split(",") if t.strip()]
    work = video
    if args.aspect == "16:9":
        print("Letterboxing to 16:9…")
        work = letterbox_16x9(video)
    if args.dry_run:
        print(f"dry-run {work} -> {', '.join(names)}")
        print(f"title: {title}")
        print(f"description:\n{description}")
        return
    load_env(ENV_PATH)
    needs_nango = any(n != "youtube" or not os.environ.get("YOUTUBE_ACCESS_TOKEN", "").strip() for n in names)
    client = nango_client() if needs_nango else None
    local = load_connections()
    results: dict[str, Any] = {}
    for name in names:
        meta = PLATFORMS[name]
        if meta["public_url"] and not args.url:
            print(f"skip {name}: needs --url (public HTTPS file the platform can fetch)")
            continue
        print(f"publishing {name}…")
        try:
            if name == "youtube" and os.environ.get("YOUTUBE_ACCESS_TOKEN", "").strip():
                print("using YOUTUBE_ACCESS_TOKEN from .env")
                results[name] = publish_youtube_direct(work, title, description, tags, args.privacy)
            elif name == "youtube":
                cfg = require_cfg(local, name, client)
                results[name] = publish_youtube(client, cfg, work, title, description, tags, args.privacy)
            elif name == "tiktok":
                results[name] = publish_tiktok(client, cfg, work, title)
            elif name == "linkedin":
                results[name] = publish_linkedin(client, cfg, work, title, description)
            elif name == "instagram":
                results[name] = publish_instagram(client, cfg, args.url, f"{title}\n\n{description}")
            elif name == "facebook":
                results[name] = publish_facebook(client, cfg, args.url, title, description)
            elif name == "x":
                results[name] = publish_x(client, cfg, args.url, title)
            elif name == "pinterest":
                results[name] = publish_pinterest(client, cfg, args.url, title, description)
            print(json.dumps({name: results[name]}, default=str, indent=2)[:2000])
        except Exception as exc:
            results[name] = {"error": str(exc)}
            print(f"  failed: {exc}")
    log_dir = NANGO_DIR / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    out = log_dir / f"share-{video.stem}.json"
    out.write_text(json.dumps(results, default=str, indent=2), encoding="utf-8")
    print(f"wrote {out}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("platforms", help="List supported social APIs and aspect ratios")
    sub.add_parser("status", help="Show Nango integrations, connections, and local IDs")
    share = sub.add_parser("share", help="Publish a local short")
    share.add_argument("video", help="Path to an mp4 (usually under Shorts/)")
    share.add_argument("--to", default="youtube", help="Comma list, or 'all'")
    share.add_argument("--title")
    share.add_argument("--caption")
    share.add_argument("--description")
    share.add_argument("--tags", help="Comma-separated YouTube tags")
    share.add_argument("--privacy", default="public", choices=("public", "unlisted", "private"))
    share.add_argument("--url", help="Public HTTPS URL required by Instagram/Facebook/X/Pinterest")
    share.add_argument("--aspect", choices=("9:16", "16:9"), default="9:16")
    share.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    if args.cmd == "platforms":
        cmd_platforms(args)
    elif args.cmd == "status":
        cmd_status(args)
    else:
        cmd_share(args)


if __name__ == "__main__":
    main()
