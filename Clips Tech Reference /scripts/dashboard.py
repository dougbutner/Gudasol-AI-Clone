#!/usr/bin/env python3
"""perfect-clips local dashboard.

Writes ONE self-contained static page to ~/.perfect-clips/dashboard.html:
settings pills (caption colour / font / default mode / clip target) plus a
browser of every package the skill has made, with copy-path buttons so any
clip can be named in a chat prompt by pasting its path.

No server, no ports, nothing runs when Claude isn't running. A file:// page
cannot silently write settings.json, so the page offers the two static write
paths: [Copy for Claude] puts a `perfect-clips settings {...}` line on the
clipboard (pasting it in chat = the write; SKILL.md handles it), and [Save
directly] uses the browser's file-save picker (Chromium) pointed at
~/.perfect-clips/settings.json. The dashboard changes DEFAULTS the intake
pre-fills — the one-round intake law stays; it never replaces consent.

Usage:
    python3 dashboard.py                      regenerate dashboard.html
    python3 dashboard.py --register <pkg_dir> add/update one package, regen
Last stdout line is always the absolute path of dashboard.html.

State (all beside the dashboard, all optional):
    ~/.perfect-clips/settings.json    {"caption_color": "#7C5CFF", ...}
    ~/.perfect-clips/packages.jsonl   one JSON line per registered package
"""
import html
import json
import os
import re
import sys
import time

HOME = os.path.join(os.path.expanduser("~"), ".perfect-clips")
SETTINGS = os.path.join(HOME, "settings.json")
REGISTRY = os.path.join(HOME, "packages.jsonl")
OUT = os.path.join(HOME, "dashboard.html")

DEFAULTS = {"caption_color": "#7C5CFF", "caption_font": "default",
            "default_mode": "shorts", "clip_count": "auto"}

CLIP_RE = re.compile(r"^(\d+) (CLIP|LONG) (\d+) - (.+?)\.mp4$")


def load_settings():
    try:
        d = json.load(open(SETTINGS, encoding="utf-8"))
        return {**DEFAULTS, **{k: d[k] for k in DEFAULTS if k in d}}
    except (OSError, ValueError):
        return dict(DEFAULTS)


def load_registry():
    pkgs = []
    try:
        for line in open(REGISTRY, encoding="utf-8"):
            if line.strip():
                pkgs.append(json.loads(line))
    except OSError:
        pass
    # last write per path wins (register updates by appending)
    by_path = {}
    for p in pkgs:
        by_path[p.get("path", "")] = p
    return sorted(by_path.values(), key=lambda p: p.get("date", ""),
                  reverse=True)


def scan_package(pkg_dir):
    """Build a registry entry from a package folder's own files."""
    pkg_dir = os.path.abspath(pkg_dir)
    clips = []
    mode = "shorts"
    for f in sorted(os.listdir(pkg_dir)):
        m = CLIP_RE.match(f)
        if not m:
            continue
        rank, kind, score, title = m.group(1), m.group(2), m.group(3), \
            m.group(4).replace("-", " ")
        if kind == "LONG":
            mode = "longform"
        clips.append({"file": os.path.join(pkg_dir, f), "rank": int(rank),
                      "score": int(score), "title": title})
    # manifest carries the real titles when present — prefer them
    for sub in ("clip data",):
        mp = os.path.join(pkg_dir, sub, "manifest.json")
        if os.path.exists(mp):
            try:
                man = json.load(open(mp, encoding="utf-8"))["clips"]
                ranked = sorted(man, key=lambda e: -e.get("total_score", 0))
                for c, e in zip(clips, ranked):
                    if e.get("title"):
                        c["title"] = e["title"]
            except (OSError, ValueError, KeyError):
                pass
            break
    if not clips:
        sys.exit(f"no ranked clip MP4s found in {pkg_dir}")
    return {"name": os.path.basename(pkg_dir), "path": pkg_dir,
            "date": time.strftime("%Y-%m-%d %H:%M",
                                  time.localtime(os.path.getmtime(pkg_dir))),
            "mode": mode, "clips": clips}


def register(pkg_dir):
    os.makedirs(HOME, exist_ok=True)
    entry = scan_package(pkg_dir)
    with open(REGISTRY, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    print(f"registered: {entry['name']} ({len(entry['clips'])} clips, "
          f"{entry['mode']})")


# ---------------------------------------------------------------- template
PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Perfect Clips — dashboard</title>
<style>
:root {{ --bg:#0b0b10; --panel:#14141c; --panel2:#1b1b26; --line:#262635;
  --text:#e8e8f0; --dim:#8a8a9e; --accent:#7c5cff; --accent2:#9d85ff;
  --yellow:#ffd400; --good:#3ddc84; }}
* {{ box-sizing:border-box; margin:0; padding:0; }}
body {{ background:var(--bg); color:var(--text); padding:32px 20px 60px;
  font-family:"Segoe UI",system-ui,-apple-system,sans-serif; }}
.wrap {{ max-width:880px; margin:0 auto; }}
h1 {{ font-size:26px; letter-spacing:.5px; }}
h1 .bolt {{ color:var(--accent); }}
.sub {{ color:var(--dim); font-size:13px; margin:4px 0 28px; }}
.card {{ background:var(--panel); border:1px solid var(--line);
  border-radius:14px; padding:22px; margin-bottom:22px; }}
.card h2 {{ font-size:15px; text-transform:uppercase; letter-spacing:1.5px;
  color:var(--accent2); margin-bottom:16px; }}
.row {{ display:flex; align-items:center; gap:10px; flex-wrap:wrap;
  margin-bottom:14px; }}
.row label {{ width:130px; color:var(--dim); font-size:13px; flex-shrink:0; }}
.pill {{ background:var(--panel2); border:1px solid var(--line);
  color:var(--text); border-radius:999px; padding:7px 16px; font-size:13px;
  cursor:pointer; transition:all .12s; }}
.pill:hover {{ border-color:var(--accent); }}
.pill.on {{ background:var(--accent); border-color:var(--accent);
  color:#fff; font-weight:600; }}
.pill.on[data-v="#FFD400"] {{ background:var(--yellow); color:#111; }}
.pill.on[data-v="#FFFFFF"] {{ background:#fff; color:#111; }}
input[type=text] {{ background:var(--panel2); border:1px solid var(--line);
  color:var(--text); border-radius:8px; padding:7px 10px; font-size:13px;
  width:150px; }}
input[type=text]:focus {{ outline:none; border-color:var(--accent); }}
.jsonbox {{ background:#0e0e14; border:1px solid var(--line); border-radius:8px;
  padding:12px 14px; font-family:Consolas,monospace; font-size:12px;
  color:var(--accent2); margin:14px 0 12px; word-break:break-all; }}
.btn {{ background:var(--accent); border:none; color:#fff; border-radius:8px;
  padding:9px 18px; font-size:13px; font-weight:600; cursor:pointer;
  margin-right:8px; }}
.btn.ghost {{ background:transparent; border:1px solid var(--line);
  color:var(--dim); }}
.btn.ghost:hover {{ border-color:var(--accent); color:var(--text); }}
.hint {{ color:var(--dim); font-size:12px; margin-top:10px; line-height:1.5; }}
.pkg {{ border:1px solid var(--line); border-radius:10px; margin-bottom:12px;
  overflow:hidden; }}
.pkg-head {{ display:flex; align-items:center; gap:12px; padding:12px 16px;
  background:var(--panel2); cursor:pointer; }}
.pkg-head .name {{ font-weight:600; font-size:14px; flex:1; min-width:0;
  overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }}
.badge {{ font-size:11px; padding:3px 10px; border-radius:999px;
  background:var(--accent); color:#fff; flex-shrink:0; }}
.badge.long {{ background:var(--yellow); color:#111; }}
.pkg-head .date {{ color:var(--dim); font-size:12px; flex-shrink:0; }}
.clips {{ display:none; }}
.pkg.open .clips {{ display:block; }}
.clip {{ display:flex; align-items:center; gap:10px; padding:9px 16px;
  border-top:1px solid var(--line); font-size:13px; }}
.clip .rank {{ color:var(--accent2); font-weight:700; width:22px; }}
.clip .score {{ color:var(--dim); width:34px; }}
.clip .title {{ flex:1; min-width:0; overflow:hidden; text-overflow:ellipsis;
  white-space:nowrap; }}
.copy {{ background:var(--panel2); border:1px solid var(--line);
  color:var(--dim); border-radius:6px; padding:5px 12px; font-size:12px;
  cursor:pointer; flex-shrink:0; }}
.copy:hover {{ border-color:var(--accent); color:var(--text); }}
.copy.done {{ background:var(--good); border-color:var(--good); color:#111; }}
.empty {{ color:var(--dim); font-size:13px; padding:8px 0; }}
</style></head><body><div class="wrap">
<h1><span class="bolt">&#9889;</span> PERFECT CLIPS</h1>
<div class="sub">local dashboard &middot; regenerated {generated} &middot;
this page runs nothing &mdash; it is a file</div>

<div class="card"><h2>Defaults</h2>
<div class="row"><label>Caption colour</label>
  <button class="pill" data-k="caption_color" data-v="#7C5CFF">Electric purple</button>
  <button class="pill" data-k="caption_color" data-v="#FFD400">Classic yellow</button>
  <button class="pill" data-k="caption_color" data-v="#FFFFFF">Clean white</button>
  <input type="text" id="hex" placeholder="#custom hex" maxlength="7">
</div>
<div class="row"><label>Caption font</label>
  <button class="pill" data-k="caption_font" data-v="default">Montserrat (ships with skill)</button>
  <input type="text" id="fontpath" placeholder="or path to a .ttf" style="width:220px">
</div>
<div class="row"><label>Default mode</label>
  <button class="pill" data-k="default_mode" data-v="shorts">Shorts 9:16</button>
  <button class="pill" data-k="default_mode" data-v="longform">Long-form (source aspect)</button>
</div>
<div class="row"><label>Shorts target</label>
  <button class="pill" data-k="clip_count" data-v="auto">Auto</button>
  <button class="pill" data-k="clip_count" data-v="3-5">3&ndash;5</button>
  <button class="pill" data-k="clip_count" data-v="6-10">6&ndash;10</button>
</div>
<div class="jsonbox" id="json"></div>
<button class="btn" id="copyClaude">Copy for Claude</button>
<button class="btn ghost" id="saveFile">Save directly&hellip;</button>
<div class="hint">These are the DEFAULTS the skill pre-fills at intake &mdash;
the question round still runs, this never replaces it.<br>
<b>Copy for Claude</b> puts a settings line on the clipboard: paste it into
any Claude Code chat and the skill writes it to settings.json.
<b>Save directly</b> uses the browser&rsquo;s file picker (Chromium) &mdash;
save over <span style="font-family:monospace">{settings_path}</span>.</div>
</div>

<div class="card"><h2>Packages</h2>
{packages_html}
<div class="hint">Click a package to expand. <b>copy path</b> puts the clip&rsquo;s
full path on the clipboard &mdash; paste it into chat to have that video
edited, revived or reworked by text.</div>
</div>

</div><script>
var S = {settings_json};
var SETTINGS_PATH = {settings_path_js};
function renderJson() {{
  document.getElementById('json').textContent =
    'perfect-clips settings ' + JSON.stringify(S);
  document.querySelectorAll('.pill').forEach(function(p) {{
    p.classList.toggle('on', S[p.dataset.k] === p.dataset.v);
  }});
}}
document.querySelectorAll('.pill').forEach(function(p) {{
  p.addEventListener('click', function() {{
    S[p.dataset.k] = p.dataset.v;
    if (p.dataset.k === 'caption_color') document.getElementById('hex').value = '';
    if (p.dataset.k === 'caption_font') document.getElementById('fontpath').value = '';
    renderJson();
  }});
}});
document.getElementById('hex').addEventListener('input', function(e) {{
  var v = e.target.value.trim();
  if (/^#[0-9a-fA-F]{{6}}$/.test(v)) {{ S.caption_color = v.toUpperCase(); renderJson(); }}
}});
document.getElementById('fontpath').addEventListener('input', function(e) {{
  var v = e.target.value.trim();
  S.caption_font = v || 'default'; renderJson();
}});
function toClipboard(text, btn, okLabel) {{
  var done = function() {{
    var old = btn.textContent; btn.textContent = okLabel || 'copied \\u2713';
    btn.classList.add('done');
    setTimeout(function() {{ btn.textContent = old; btn.classList.remove('done'); }}, 1400);
  }};
  if (navigator.clipboard && navigator.clipboard.writeText) {{
    navigator.clipboard.writeText(text).then(done, function() {{ fallback(); }});
  }} else fallback();
  function fallback() {{
    var t = document.createElement('textarea'); t.value = text;
    document.body.appendChild(t); t.select();
    try {{ document.execCommand('copy'); done(); }} catch (e) {{}}
    document.body.removeChild(t);
  }}
}}
document.getElementById('copyClaude').addEventListener('click', function() {{
  toClipboard('perfect-clips settings ' + JSON.stringify(S), this);
}});
var saveBtn = document.getElementById('saveFile');
if (!window.showSaveFilePicker) saveBtn.style.display = 'none';
else saveBtn.addEventListener('click', async function() {{
  try {{
    var h = await window.showSaveFilePicker({{
      suggestedName: 'settings.json',
      types: [{{description: 'JSON', accept: {{'application/json': ['.json']}}}}]
    }});
    var w = await h.createWritable();
    await w.write(JSON.stringify(S, null, 1)); await w.close();
    var old = this.textContent; this.textContent = 'saved \\u2713';
    var b = this; setTimeout(function() {{ b.textContent = old; }}, 1400);
  }} catch (e) {{}}
}});
document.querySelectorAll('.pkg-head').forEach(function(h) {{
  h.addEventListener('click', function(e) {{
    if (e.target.classList.contains('copy')) return;
    h.parentElement.classList.toggle('open');
  }});
}});
document.querySelectorAll('.copy').forEach(function(b) {{
  b.addEventListener('click', function() {{
    toClipboard(b.dataset.path, b, '\\u2713');
  }});
}});
renderJson();
</script></body></html>
"""


def pkg_html(pkgs):
    if not pkgs:
        return ('<div class="empty">No packages registered yet — the next '
                'run will appear here.</div>')
    out = []
    for i, p in enumerate(pkgs):
        badge = ('<span class="badge long">LONG-FORM</span>'
                 if p.get("mode") == "longform"
                 else '<span class="badge">SHORTS</span>')
        rows = [f'<div class="pkg{" open" if i == 0 else ""}">'
                f'<div class="pkg-head"><span class="name">'
                f'{html.escape(p.get("name", "?"))}</span>{badge}'
                f'<span class="date">{html.escape(p.get("date", ""))} '
                f'&middot; {len(p.get("clips", []))} clips</span>'
                f'<button class="copy" data-path="{html.escape(p.get("path", ""), quote=True)}">'
                f'copy folder</button></div><div class="clips">']
        for c in sorted(p.get("clips", []), key=lambda c: c.get("rank", 99)):
            rows.append(
                f'<div class="clip"><span class="rank">{c.get("rank", "?")}</span>'
                f'<span class="score">{c.get("score", "?")}</span>'
                f'<span class="title">{html.escape(str(c.get("title", "")))}</span>'
                f'<button class="copy" data-path="{html.escape(c.get("file", ""), quote=True)}">'
                f'copy path</button></div>')
        rows.append('</div></div>')
        out.append("".join(rows))
    return "\n".join(out)


def generate():
    os.makedirs(HOME, exist_ok=True)
    s = load_settings()
    pkgs = load_registry()
    page = PAGE.format(
        generated=time.strftime("%Y-%m-%d %H:%M"),
        settings_json=json.dumps(s),
        settings_path=html.escape(SETTINGS),
        settings_path_js=json.dumps(SETTINGS),
        packages_html=pkg_html(pkgs))
    open(OUT, "w", encoding="utf-8").write(page)
    print(f"{len(pkgs)} packages, settings "
          f"{'file' if os.path.exists(SETTINGS) else 'defaults'}")
    print(OUT)


if __name__ == "__main__":
    if "--register" in sys.argv:
        register(sys.argv[sys.argv.index("--register") + 1])
    generate()
