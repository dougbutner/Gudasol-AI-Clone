#!/usr/bin/env node
/* perfect-clips — one-word caption renderer.
   Burns the word-at-a-time caption layer onto a pre-cut vertical clip using a
   minimal embedded Remotion project (cached at ~/.perfect-clips/renderer).

   Usage:
     node render_captions.mjs <clip.mp4> <words.json> <out.mp4>
                              [--color "#7C5CFF"] [--font /path/to/font.ttf]
                              [--font-weight 800] [--caption-y 0.73]
                              [--plan "layout plan.json"]
                              [--title "ONE MASSIVE BET"] [--title-sec 3]
     node render_captions.mjs --setup     (write project + npm install, exit)

   LONG-FORM (rule 11): no --plan, no --title, --caption-y 0.86. 0.86 is
   measured, not guessed — YouTube's bottom chrome is a fixed ~59px, so at
   theater/fullscreen sizes it starts at ~93% of the frame; a chip centred at
   86% has its bottom edge at ~91% and clears it. YouTube's chrome auto-hides
   during playback (Instagram's never does), so a small embedded player with
   controls up is a transient overlap, not the design constraint.

   --plan makes captions LAYOUT-AWARE: the layout plan's regions are mapped
   onto the output timeline and the chip moves with the layout, switching on
   the same exact frames — the pane seam (0.5) over split regions, the lower
   third (--caption-y, default 0.73 — Reels-safe) over crop/full/zoom
   regions.

   --title burns the HEADLINE: a 2-3 word all-caps hook chip (lifted from
   the clip's spoken hook — see SKILL.md headline law), same chip system as
   the captions but larger, pinned top-center (18% height, Reels-safe), on screen for
   the hook window only (--title-sec, default 3s), then a quiet fade. It
   never moves with the layout and never restates the payoff. Ported from
   the retired reels-auto-editor hook banner (2026-06), restyled to the
   perfect-clips chip.

   Requires Node.js + ffprobe. First run: npm install (~250MB) and Remotion
   downloads Chrome Headless Shell (~150MB). Both are one-time, cached. */

import fs from "fs";
import os from "os";
import path from "path";
import { fileURLToPath } from "url";
import { spawnSync } from "child_process";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const APP = path.join(os.homedir(), ".perfect-clips", "renderer");
const DEFAULT_FONT = path.join(HERE, "..", "assets", "Montserrat-Variable.ttf");

// ---------- embedded Remotion project ----------
const FILES = {
  "package.json": `{
  "name": "perfect-clips-renderer",
  "version": "1.0.0",
  "private": true,
  "dependencies": {
    "@remotion/cli": "^4.0.0",
    "react": "^18.3.1",
    "react-dom": "^18.3.1",
    "remotion": "^4.0.0"
  },
  "devDependencies": { "@types/react": "^18.3.1", "typescript": "^5.5.0" }
}
`,
  "tsconfig.json": `{
  "compilerOptions": {
    "target": "ES2022",
    "module": "ESNext",
    "moduleResolution": "Bundler",
    "jsx": "react-jsx",
    "strict": false,
    "skipLibCheck": true,
    "esModuleInterop": true,
    "resolveJsonModule": true,
    "noEmit": true
  },
  "include": ["src"]
}
`,
  "src/index.ts": `import { registerRoot } from "remotion";
import { Root } from "./Root";

registerRoot(Root);
`,
  "src/Root.tsx": `import React from "react";
import { Composition } from "remotion";
import { PerfectClip } from "./PerfectClip";
import props from "./props.json";

export const Root = () => (
  <Composition
    id="PerfectClip"
    component={PerfectClip}
    durationInFrames={Math.max(1, Math.round(props.video.durationSec * props.video.fps))}
    fps={props.video.fps}
    width={props.video.width}
    height={props.video.height}
    defaultProps={props}
  />
);
`,
  "src/PerfectClip.tsx": `import React, { useMemo } from "react";
import { AbsoluteFill, OffthreadVideo, interpolate, staticFile, useCurrentFrame, useVideoConfig } from "remotion";

/* One word on screen at a time, SUBTLE. A word HOLDS on screen until the
   next word starts whenever the gap is under HOLD_GAP — no dead air between
   words (inter-word fading reads as flashing; flagged on the first
   production run 2026-08-22). Gentle ease-in, no overshoot, no shrink on
   exit; fade only into a real pause.
   SIZE FOLLOWS THE SHORT EDGE of the frame — 7.6% of min(width, height), the
   headline 1.35x that. On a 1080x1920 short min IS the width, so vertical
   output is unchanged; on a 1920x1080 long-form clip (rule 11) keying to
   width would render the chip 1.8x too large. Horizontal fit limits stay
   width-based — they are horizontal. */
const POP = 3;
const FADE = 6;
const HOLD_GAP = 1.0;

const lum = (hex) => {
  const h = String(hex || "#7C5CFF").replace("#", "");
  const n = h.length === 3 ? h.split("").map((c) => c + c).join("") : h;
  const v = [0, 2, 4].map((o) => parseInt(n.slice(o, o + 2), 16) / 255);
  return 0.2126 * v[0] + 0.7152 * v[1] + 0.0722 * v[2];
};

/* Headline chip: the hook title, top-center, hook window only. Same chip
   DNA as the caption (colour, font, radius, shadow), 1.35x the size,
   deterministic shrink-to-fit so it never leaves the frame. Subtle motion
   law applies: gentle ease-in, fade-out, nothing bounces.
   PLACEMENT IS REELS-SAFE-ZONE LAW (2026-08-22): center 18% keeps the
   whole chip below IG's top 250px UI band; max width 87% respects the
   ~70px side margins. Do not raise it. */
const Headline = ({ title, chip, fontWeight, durFrames }) => {
  const frame = useCurrentFrame();
  const { fps, width, height } = useVideoConfig();
  const endF = Math.min(Math.round(title.sec * fps), durFrames);
  if (!title.text || frame >= endF) return null;
  const textColor = lum(chip.color) > 0.55 ? "#111111" : "#FFFFFF";
  const text = String(title.text).toUpperCase();
  let size = Math.min(width, height) * 0.1026;
  const est = text.length * size * 0.62 + size * 0.8;
  const maxW = width * 0.87;
  if (est > maxW) size = size * (maxW / est);
  const scale = interpolate(frame, [0, POP], [0.96, 1], { extrapolateRight: "clamp" });
  let opacity = interpolate(frame, [0, 2], [0, 1], { extrapolateRight: "clamp" });
  opacity *= interpolate(frame, [endF - FADE, endF], [1, 0], { extrapolateLeft: "clamp", extrapolateRight: "clamp" });
  return (
    <div
      style={{
        position: "absolute",
        top: "18%",
        left: "50%",
        transform: "translate(-50%, -50%) scale(" + scale + ")",
        opacity,
        background: chip.color,
        color: textColor,
        fontFamily: "PCFont, Arial, sans-serif",
        fontWeight,
        fontSize: size,
        lineHeight: 1.1,
        padding: "0.14em 0.4em",
        borderRadius: "0.16em",
        whiteSpace: "nowrap",
        boxShadow: "0 0.06em 0.25em rgba(0,0,0,0.35)",
      }}
    >
      {text}
    </div>
  );
};

export const PerfectClip = (props) => {
  const { words, chip, fontWeight, captionY, track, title } = props;
  const frame = useCurrentFrame();
  const { fps, width, height } = useVideoConfig();
  const tSec = frame / fps;
  const trackSeg = track && track.length
    ? (track.find((r) => tSec >= r.start && tSec < r.end) || track[track.length - 1])
    : null;
  const chipY = trackSeg ? trackSeg.y : (captionY || 0.73);

  const timed = useMemo(() => words.map((w, i) => {
    const startF = Math.max(0, Math.floor(w.start * fps));
    const endF = Math.max(startF + 1, Math.round(w.end * fps));
    const next = words[i + 1];
    const nextStartF = next ? Math.max(0, Math.floor(next.start * fps)) : Infinity;
    const holds = next ? next.start - w.end < HOLD_GAP : false;
    const visEndF = holds
      ? Math.max(startF + 1, nextStartF)
      : Math.min(endF + FADE, nextStartF);
    return { ...w, startF, endF, visEndF, holds };
  }), [words, fps]);

  const active = timed.find((w) => frame >= w.startF && frame < w.visEndF);
  const textColor = lum(chip.color) > 0.55 ? "#111111" : "#FFFFFF";

  let el = null;
  if (active) {
    const local = frame - active.startF;
    const scale = interpolate(local, [0, POP], [0.96, 1], { extrapolateRight: "clamp" });
    let opacity = interpolate(local, [0, 2], [0, 1], { extrapolateRight: "clamp" });
    if (!active.holds && frame >= active.endF) {
      const fadeLen = Math.max(1, active.visEndF - active.endF);
      opacity = interpolate(frame, [active.endF, active.endF + fadeLen], [1, 0], { extrapolateRight: "clamp" });
    }
    const word = String(active.text || "").toUpperCase();
    const base = Math.min(width, height) * 0.076;
    const size = word.length > 10 ? base * (10 / word.length) : base;
    el = (
      <div
        style={{
          position: "absolute",
          top: (chipY * 100) + "%",
          left: "50%",
          transform: "translate(-50%, -50%) scale(" + scale + ")",
          opacity,
          background: chip.color,
          color: textColor,
          fontFamily: "PCFont, Arial, sans-serif",
          fontWeight,
          fontSize: size,
          lineHeight: 1.1,
          padding: "0.14em 0.4em",
          borderRadius: "0.16em",
          whiteSpace: "nowrap",
          boxShadow: "0 0.06em 0.25em rgba(0,0,0,0.35)",
        }}
      >
        {word}
      </div>
    );
  }

  const face =
    "@font-face{font-family:'PCFont';src:url('" + staticFile("font.ttf") +
    "');font-weight:100 900;}";
  const durFrames = Math.max(1, Math.round(props.video.durationSec * fps));
  return (
    <AbsoluteFill style={{ background: "#000" }}>
      <style>{face}</style>
      <OffthreadVideo src={staticFile("clip.mp4")} />
      {title && title.text ? (
        <Headline title={title} chip={chip} fontWeight={fontWeight} durFrames={durFrames} />
      ) : null}
      {el}
    </AbsoluteFill>
  );
};
`,
};
// -----------------------------------------------

function fail(msg) {
  console.error("\n  PROBLEM: " + msg + "\n");
  process.exit(1);
}

function flagVal(name, dflt) {
  const i = process.argv.indexOf(name);
  return i > -1 ? process.argv[i + 1] : dflt;
}

function writeProject() {
  for (const [rel, content] of Object.entries(FILES)) {
    const dest = path.join(APP, rel);
    fs.mkdirSync(path.dirname(dest), { recursive: true });
    fs.writeFileSync(dest, content);
  }
}

function ensureDeps() {
  if (!fs.existsSync(path.join(APP, "node_modules"))) {
    console.log("\nFirst run — installing Remotion (one-time, a few minutes)...\n");
    const r = spawnSync("npm install", { cwd: APP, stdio: "inherit", shell: true });
    if (r.status !== 0) fail("npm install failed — check the internet connection and retry.");
  }
}

function probe(file) {
  const r = spawnSync(
    "ffprobe",
    ["-v", "error", "-show_entries",
     "stream=codec_type,r_frame_rate,width,height:format=duration",
     "-of", "json", file],
    { encoding: "utf8" },
  );
  if (r.status !== 0) fail("ffprobe failed on " + file);
  const info = JSON.parse(r.stdout);
  const v = (info.streams || []).find((s) => s.codec_type === "video");
  if (!v) fail("no video stream in " + file);
  const [num, den] = v.r_frame_rate.split("/").map(Number);
  return {
    width: v.width, height: v.height, fps: num / (den || 1),
    durationSec: parseFloat(info.format.duration),
  };
}

function place(src, destName) {
  // Always copy real bytes: Remotion's bundler copies public/ into a temp
  // bundle and symlinks don't survive the trip (Windows dev-mode symlinks
  // silently 404 at render time — learned 2026-08-21).
  const pub = path.join(APP, "public");
  fs.mkdirSync(pub, { recursive: true });
  const dest = path.join(pub, destName);
  try { fs.rmSync(dest, { force: true }); } catch {}
  fs.copyFileSync(src, dest);
}

// ---- main ----
if (process.argv.includes("--setup")) {
  writeProject();
  ensureDeps();
  console.log("renderer ready at " + APP);
  process.exit(0);
}

const positionals = [];
{
  const argv = process.argv.slice(2);
  for (let i = 0; i < argv.length; i++) {
    if (argv[i].startsWith("--")) { i++; continue; }  // skip flag + value
    positionals.push(argv[i]);
  }
}
const [clip, wordsFile, out] = positionals;
if (!clip || !wordsFile || !out) fail("usage: render_captions.mjs <clip.mp4> <words.json> <out.mp4> [--color HEX] [--font TTF]");
if (!fs.existsSync(clip)) fail("clip not found: " + clip);
if (!fs.existsSync(wordsFile)) fail("words file not found: " + wordsFile);

const color = flagVal("--color", "#7C5CFF");
const font = flagVal("--font", DEFAULT_FONT);
const fontWeight = parseInt(flagVal("--font-weight", "800"), 10);
const titleText = flagVal("--title", "");
const titleSec = parseFloat(flagVal("--title-sec", "3"));
// 0.73 = lower third, Reels-safe (chip bottom clears IG's 420px caption
// band); 0.5 = the pane seam (split regions). Raised from 0.8 on
// 2026-08-22 — 0.8 put the chip inside Instagram's bottom UI.
const captionY = parseFloat(flagVal("--caption-y", "0.73"));
const planPath = flagVal("--plan", null);
if (!fs.existsSync(font)) fail("font not found: " + font);

const video = probe(clip);
writeProject();
const words = JSON.parse(fs.readFileSync(wordsFile, "utf8"));

// Layout-aware caption track: map plan regions (source frames, render order)
// onto the output timeline. Seam over split; --caption-y over everything else.
let track = null;
if (planPath) {
  if (!fs.existsSync(planPath)) fail("plan not found: " + planPath);
  const regions = JSON.parse(fs.readFileSync(planPath, "utf8")).regions;
  let t = 0;
  track = [];
  for (const r of regions) {
    const dur = (r.out_frame - r.in_frame) / video.fps;
    const y = r.mode === "split" ? 0.5 : captionY;
    const last = track[track.length - 1];
    if (last && last.y === y) last.end = t + dur;
    else track.push({ start: t, end: t + dur, y });
    t += dur;
  }
}

fs.writeFileSync(
  path.join(APP, "src", "props.json"),
  JSON.stringify({ video, words, chip: { color }, fontWeight, captionY, track,
                   title: { text: titleText, sec: titleSec } }, null, 1),
);
place(path.resolve(clip), "clip.mp4");
try { fs.rmSync(path.join(APP, "public", "font.ttf"), { force: true }); } catch {}
fs.copyFileSync(font, path.join(APP, "public", "font.ttf"));
ensureDeps();

const outAbs = path.resolve(out);
console.log("Rendering captions -> " + outAbs);
const r = spawnSync(
  'npx remotion render src/index.ts PerfectClip "' + outAbs + '" --overwrite --crf 18 --log=error',
  { cwd: APP, stdio: "inherit", shell: true },
);
if (r.status !== 0 || !fs.existsSync(outAbs)) fail("remotion render failed");
console.log("done: " + outAbs);
