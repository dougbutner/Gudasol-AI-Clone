#!/usr/bin/env python3
"""Perfect Clips setup check: prints what the pipeline can find on this machine.

Usage: python doctor.py [--help]

Stdlib only. Installs nothing, touches no network, always exits 0.
One line per item, in this order, then a SUMMARY line:

  PYTHON:   the interpreter running this script + whether python3 /
            python / py -3 resolve on PATH (a Windows Store stub that
            only opens the Store counts as MISSING)
  FFMPEG:   ffmpeg + ffprobe on PATH
  WHISPERX= first WhisperX found: ~/.perfect-cuts/venv, ~/.buttercut/venv,
            ~/.perfect-clips/venv (bin/whisperx or Scripts/whisperx.exe),
            then whisperx on PATH; else MISSING
  NODE:     node version, or MISSING (captions need it)
  YT-DLP:   present or MISSING (only needed for URL sources)
  PYCV=     first python that can `import cv2`: the WhisperX venv's python
            first, then this interpreter; else MISSING (only needed for
            multi-layout sources)

Read WHISPERX= and PYCV= straight into the skill's $WHISPERX / $PYCV.
"""
import argparse
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path

IS_WIN = platform.system() == "Windows"
TIMEOUT = 20


def run(cmd):
    """Run a command list; return (ok, stdout) where ok = exit 0 and non-empty stdout."""
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=TIMEOUT)
    except (OSError, subprocess.SubprocessError):
        return False, ""
    out = (r.stdout or "").strip()
    return (r.returncode == 0 and bool(out)), out


def python_resolves(name_args):
    """True when `<name> <args> -c print(...)` runs and prints (Store stub exits non-zero / prints nothing)."""
    exe = shutil.which(name_args[0])
    if not exe:
        return False
    ok, _ = run([exe] + name_args[1:] + ["-c", "import sys; print(sys.executable)"])
    return ok


def find_whisperx():
    home = Path.home()
    for venv in (home / ".perfect-cuts" / "venv",
                 home / ".buttercut" / "venv",
                 home / ".perfect-clips" / "venv"):
        for rel in ("bin/whisperx", "Scripts/whisperx.exe"):
            cand = venv / rel
            if cand.is_file():
                return cand
    on_path = shutil.which("whisperx")
    return Path(on_path) if on_path else None


def python_beside(whisperx):
    """The venv python that sits next to a found whisperx binary."""
    if not whisperx:
        return None
    d = whisperx.parent
    for name in ("python.exe", "python", "python3"):
        cand = d / name
        if cand.is_file():
            return cand
    return None


def can_import_cv2(py):
    ok, _ = run([str(py), "-c", "import cv2; print(cv2.__version__)"])
    return ok


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.parse_args()

    ok_items, missing_items = [], []

    # 1. Python
    ver = " ".join(sys.version.split())
    probes = []
    for label, args in (("python3", ["python3"]), ("python", ["python"]), ("py -3", ["py", "-3"])):
        probes.append(f"{label}={'OK' if python_resolves(args) else 'MISSING'}")
    print(f"PYTHON: {ver} at {sys.executable} | {' '.join(probes)}")
    ok_items.append("python")

    # 2. ffmpeg + ffprobe
    ffmpeg = shutil.which("ffmpeg")
    ffprobe = shutil.which("ffprobe")
    print(f"FFMPEG: {ffmpeg or 'MISSING'} | FFPROBE: {ffprobe or 'MISSING'}")
    (ok_items if ffmpeg else missing_items).append("ffmpeg")
    (ok_items if ffprobe else missing_items).append("ffprobe")

    # 3. WhisperX
    wx = find_whisperx()
    print(f"WHISPERX={wx if wx else 'MISSING'}")
    (ok_items if wx else missing_items).append("whisperx")

    # 4. Node
    node = shutil.which("node")
    node_ver = ""
    if node:
        _, node_ver = run([node, "--version"])
    print(f"NODE: {node_ver + ' at ' + node if node else 'MISSING'}")
    (ok_items if node else missing_items).append("node")

    # 5. yt-dlp
    ytdlp = shutil.which("yt-dlp")
    print(f"YT-DLP: {ytdlp if ytdlp else 'MISSING'} (only needed for URL sources)")
    (ok_items if ytdlp else missing_items).append("yt-dlp (URL sources only)")

    # 6. PYCV
    pycv = None
    for cand in (python_beside(wx), Path(sys.executable)):
        if cand and can_import_cv2(cand):
            pycv = cand
            break
    print(f"PYCV={pycv if pycv else 'MISSING'} (only needed for multi-layout sources)")
    (ok_items if pycv else missing_items).append("pycv (multi-layout sources only)")

    print(f"SUMMARY: OK: {', '.join(ok_items)} | MISSING: {', '.join(missing_items) if missing_items else 'none'}")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:  # never block a run on the doctor itself
        print(f"DOCTOR-ERROR: {exc}")
    sys.exit(0)
