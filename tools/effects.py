"""Moviepy effect presets for talking shorts.

Picture-only. Logo and captions are composited after apply().
Audio is copied through; no time remapping.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

W, H = 1080, 1920

# Seeded into data/ceo.sqlite. pool is the default niche pool on first migrate.
PRESETS: list[dict[str, Any]] = [
    {
        "slug": "none",
        "fx": "none",
        "params": {},
        "note": "Control. No moviepy pass.",
        "pool": "active",
    },
    {
        "slug": "fade-in",
        "fx": "FadeIn",
        "params": {"duration": 0.4},
        "note": "Fade from black at the start.",
        "pool": "active",
    },
    {
        "slug": "lift-contrast",
        "fx": "LumContrast",
        "params": {"lum": 8, "contrast": 12},
        "note": "Slight lift and contrast.",
        "pool": "active",
    },
    {
        "slug": "warm",
        "fx": "MultiplyColor",
        "params": {"factor": 1.08},
        "note": "Warm brightness multiply.",
        "pool": "active",
    },
    {
        "slug": "cool",
        "fx": "MultiplyColor",
        "params": {"factor": 0.92},
        "note": "Cool darker multiply.",
        "pool": "active",
    },
    {
        "slug": "fade-out",
        "fx": "FadeOut",
        "params": {"duration": 0.4},
        "note": "Fade to black at the end.",
        "pool": "bench",
    },
    {
        "slug": "gamma-lift",
        "fx": "GammaCorrection",
        "params": {"gamma": 1.15},
        "note": "Mild gamma lift.",
        "pool": "bench",
    },
    {
        "slug": "black-white",
        "fx": "BlackAndWhite",
        "params": {"preserve_luminosity": True},
        "note": "Desaturate picture only.",
        "pool": "bench",
    },
    {
        "slug": "slow-push",
        "fx": "slow_push",
        "params": {"end_scale": 1.08},
        "note": "Slow zoom in, then crop back to 1080x1920.",
        "pool": "bench",
    },
]

ACTIVE_SLUGS = [p["slug"] for p in PRESETS if p["pool"] == "active"]
BENCH_SLUGS = [p["slug"] for p in PRESETS if p["pool"] == "bench"]
CONTROL_SLUG = "none"
JUMP_SKIP_SLUGS = frozenset({"slow-push"})


def preset_by_slug(slug: str) -> dict[str, Any] | None:
    for row in PRESETS:
        if row["slug"] == slug:
            return row
    return None


def _slow_push(clip: Any, end_scale: float = 1.08) -> Any:
    """Resize over time, then center-crop back to 1080x1920."""
    import numpy as np
    from PIL import Image

    duration = max(float(clip.duration or 0.0), 0.001)
    scale_end = max(1.0, float(end_scale))

    def fl(get_frame: Any, t: float) -> Any:
        frame = get_frame(t)
        scale = 1.0 + (scale_end - 1.0) * min(1.0, max(0.0, t / duration))
        if scale <= 1.001:
            return frame
        img = Image.fromarray(frame)
        nw = max(W, int(round(img.width * scale)))
        nh = max(H, int(round(img.height * scale)))
        if nw % 2:
            nw += 1
        if nh % 2:
            nh += 1
        img = img.resize((nw, nh), Image.Resampling.LANCZOS)
        left = max(0, (nw - W) // 2)
        top = max(0, (nh - H) // 2)
        img = img.crop((left, top, left + W, top + H))
        return np.asarray(img)

    return clip.transform(fl)


def _build_effects(slug: str, params: dict[str, Any]) -> list[Any]:
    from moviepy.video import fx as vfx

    row = preset_by_slug(slug)
    name = (row or {}).get("fx") or slug
    if name in {"none", "slow_push"}:
        return []
    cls = getattr(vfx, name, None)
    if cls is None:
        raise ValueError(f"unknown moviepy fx {name!r} for slug {slug!r}")
    return [cls(**params)]


def _video_codec() -> tuple[str, list[str]]:
    """Match the shorts renderer: prefer VideoToolbox when libx264 is missing."""
    import subprocess

    try:
        out = subprocess.check_output(
            ["ffmpeg", "-hide_banner", "-encoders"],
            text=True,
            stderr=subprocess.STDOUT,
        )
    except (subprocess.CalledProcessError, FileNotFoundError):
        return "libx264", ["-preset", "veryfast", "-crf", "20"]
    if "libx264" in out:
        return "libx264", ["-preset", "veryfast", "-crf", "20"]
    if "h264_videotoolbox" in out:
        return "h264_videotoolbox", ["-b:v", "8M"]
    return "libx264", ["-preset", "veryfast", "-crf", "20"]


def apply(picture: Path, dest: Path, slug: str, params: dict[str, Any] | None = None) -> Path:
    """Apply a preset to a picture cut. Audio is kept in sync (no time remap)."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    preset = preset_by_slug(slug)
    if preset is None and slug != "none":
        raise ValueError(f"unknown effect slug {slug!r}")
    use_params = dict(params if params is not None else (preset or {}).get("params") or {})
    fx_name = (preset or {}).get("fx") or "none"

    if slug == "none" or fx_name == "none":
        if picture.resolve() != dest.resolve():
            shutil.copy2(picture, dest)
        return dest

    from moviepy import VideoFileClip

    codec, ffmpeg_params = _video_codec()
    clip = VideoFileClip(str(picture))
    out = clip
    try:
        if fx_name == "slow_push":
            out = _slow_push(clip, end_scale=float(use_params.get("end_scale", 1.08)))
        else:
            built = _build_effects(slug, use_params)
            out = clip.with_effects(built) if built else clip
        # Keep original audio track; effects above are video-only.
        if clip.audio is not None and out.audio is None:
            out = out.with_audio(clip.audio)
        kwargs: dict[str, Any] = {
            "codec": codec,
            "audio_codec": "aac",
            "fps": clip.fps or 24,
            "ffmpeg_params": ffmpeg_params,
            "logger": None,
        }
        if codec == "libx264":
            kwargs["preset"] = "veryfast"
        out.write_videofile(str(dest), **kwargs)
    finally:
        clip.close()
        try:
            out.close()
        except Exception:
            pass
    return dest


def seed_rows() -> list[tuple[str, str, str, str]]:
    """Rows for the effects catalog table: slug, fx, params_json, note."""
    return [
        (p["slug"], p["fx"], json.dumps(p["params"], sort_keys=True), p["note"])
        for p in PRESETS
    ]


def default_niche_pools() -> list[tuple[str, str]]:
    """(slug, pool) defaults for a new niche."""
    return [(p["slug"], p["pool"]) for p in PRESETS]
