"""Resolve a project config against render-styles.json.

Chopping is not a style. tools/make_shorts.py owns where a short starts and ends.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OTHER = {"source_videos", "recursive", "pin_video"}


def resolve(chosen: dict | None) -> dict:
    options = json.loads((ROOT / "render-styles.json").read_text(encoding="utf-8"))["options"]
    out: dict = {}
    for key, value in (chosen or {}).items():
        if key not in options:
            if key not in OTHER:
                print(f"ignoring {key!r} (not in render-styles.json)", file=sys.stderr)
            continue
        allowed = options[key]
        if isinstance(allowed, dict):
            if value not in allowed:
                raise SystemExit(f"{key} {value!r} is not in render-styles.json")
            spec = allowed[value]
            if key == "font":
                found = ROOT / spec["repo"] if spec.get("repo") and (ROOT / spec["repo"]).is_file() else None
                if found is None and Path(spec["file"]).is_file():
                    found = Path(spec["file"])
                if found is None:
                    for folder in (
                        Path.home() / "Library/Fonts",
                        Path("/Library/Fonts"),
                        Path("/System/Library/Fonts"),
                        Path("/System/Library/Fonts/Supplemental"),
                    ):
                        if (folder / spec["file"]).is_file():
                            found = folder / spec["file"]
                            break
                if found is None:
                    raise SystemExit(f"missing font {value}: {spec['file']}")
                out["font"] = value
                out["font_name"] = spec["name"]
                out["font_index"] = int(spec.get("index") or 0)
                out["font_path"] = str(found)
            elif key == "logo":
                if not spec.get("file"):
                    out["logo"] = "none"
                elif not (ROOT / spec["file"]).is_file():
                    raise SystemExit(f"missing logo {spec['file']}")
                else:
                    out["logo"] = spec["file"]
            else:
                out[key] = spec
        elif value not in allowed:
            raise SystemExit(f"{key} {value!r} is not in render-styles.json")
        else:
            out[key] = value
    return out
