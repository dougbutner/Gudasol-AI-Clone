"""Shared art-edge catalog for shorts and music videos.

Each shape returns 0..1 along x. Periods stay short so the fringe is a
row of small cuts, not a few giant teeth. Callers multiply by a small
pixel depth.
"""

from __future__ import annotations

import random

import numpy as np

# (name, ffmpeg expression in X that is 0..1). Commas are escaped later.
_EXPR = (
    ("saw", "abs(mod(X,28)-14)/14"),
    ("fine-saw", "abs(mod(X,14)-7)/7"),
    ("squares", "if(lt(mod(X,22),11),1,0)"),
    ("narrow-squares", "if(lt(mod(X,16),4),1,0)"),
    ("triangle", "abs(mod(X,36)-18)/18"),
    ("wave", "sin(X*PI/18)*0.5+0.5"),
    ("fine-wave", "sin(X*PI/9)*0.5+0.5"),
    ("scallop", "pow(sin(X*PI/14)*0.5+0.5,2)"),
    ("double-wave", "(sin(X*PI/22)*0.5+0.5)*0.65+(sin(X*PI/7)*0.5+0.5)*0.35"),
    ("diamond", "abs(mod(X,32)-16)/16"),
    ("stairs", "floor(mod(X,32)/8)/4"),
    ("fine-stairs", "floor(mod(X,20)/4)/5"),
    ("gaps", "if(lt(mod(X,18),5),1,0)"),
    ("peaks", "abs(sin(X*PI/12))"),
    ("battlement", "if(lt(mod(X,24),16),0,1)"),
    ("semicircle", "1-sqrt(max(1-pow((mod(X,26)-13)/13,2),0))"),
    ("ramp", "mod(X,24)/24"),
    ("spike", "pow(abs(mod(X,20)-10)/10,3)"),
    ("flat-diamond", "min(abs(mod(X,40)-20)/20,0.55)"),
    ("chevron", "abs(abs(mod(X,24)-12)/12-0.5)*2"),
    ("beads", "pow(1-sqrt(max(1-pow((mod(X,18)-9)/9,2),0)),2)"),
    ("notches", "if(lt(mod(X,12),2),1,0)"),
    ("braid", "min(1,abs(sin(X*PI/16))*0.7+abs(sin(X*PI/6))*0.45)"),
    ("hills", "pow(sin(X*PI/20)*0.5+0.5,4)"),
    ("barcode", "if(lt(mod(X*3,17),3)+lt(mod(X,11),2),1,0)"),
    ("arches", "1-sqrt(max(1-pow((mod(X,20)-10)/10,2),0))"),
    ("terraces", "floor((sin(X*PI/15)*0.5+0.5)*5)/5"),
    ("cusps", "pow(abs(sin(X*PI/11)),0.35)"),
    ("lace", "min(abs(mod(X,22)-11)/11,abs(mod(X,14)-7)/7)"),
    ("drip", "pow(mod(X,22)/22,3)"),
    ("heartbeat", "pow(abs(sin(X*PI/26)),8)*0.85+pow(abs(sin(X*PI/26+1.4)),14)*0.4"),
    ("cross", "max(if(lt(mod(X,20),2),1,0),if(lt(abs(mod(X,20)-10),2),0.65,0))"),
)

NAMES = tuple(name for name, _ in _EXPR)
_BY_NAME = {name: expr for name, expr in _EXPR}


def unit(name: str, xs, t: float = 0.0):
    """0..1 curve along x. `xs` is a 1-d array of pixel positions."""
    x = np.asarray(xs, dtype=np.float32) + float(int(t * 10) % 36)
    if name == "saw":
        u = np.abs((x % 28) - 14) / 14
    elif name == "fine-saw":
        u = np.abs((x % 14) - 7) / 7
    elif name == "squares":
        u = np.where((x % 22) < 11, 1.0, 0.0)
    elif name == "narrow-squares":
        u = np.where((x % 16) < 4, 1.0, 0.0)
    elif name == "triangle":
        u = np.abs((x % 36) - 18) / 18
    elif name == "wave":
        u = np.sin(x * np.pi / 18) * 0.5 + 0.5
    elif name == "fine-wave":
        u = np.sin(x * np.pi / 9) * 0.5 + 0.5
    elif name == "scallop":
        u = (np.sin(x * np.pi / 14) * 0.5 + 0.5) ** 2
    elif name == "double-wave":
        u = (np.sin(x * np.pi / 22) * 0.5 + 0.5) * 0.65 + (np.sin(x * np.pi / 7) * 0.5 + 0.5) * 0.35
    elif name == "diamond":
        u = np.abs((x % 32) - 16) / 16
    elif name == "stairs":
        u = np.floor((x % 32) / 8) / 4
    elif name == "fine-stairs":
        u = np.floor((x % 20) / 4) / 5
    elif name == "gaps":
        u = np.where((x % 18) < 5, 1.0, 0.0)
    elif name == "peaks":
        u = np.abs(np.sin(x * np.pi / 12))
    elif name == "battlement":
        u = np.where((x % 24) < 16, 0.0, 1.0)
    elif name == "semicircle":
        p = (x % 26) - 13
        u = 1 - np.sqrt(np.maximum(1 - (p / 13) ** 2, 0))
    elif name == "ramp":
        u = (x % 24) / 24
    elif name == "spike":
        u = (np.abs((x % 20) - 10) / 10) ** 3
    elif name == "flat-diamond":
        u = np.minimum(np.abs((x % 40) - 20) / 20, 0.55)
    elif name == "chevron":
        u = np.abs(np.abs((x % 24) - 12) / 12 - 0.5) * 2
    elif name == "beads":
        p = (x % 18) - 9
        u = (1 - np.sqrt(np.maximum(1 - (p / 9) ** 2, 0))) ** 2
    elif name == "notches":
        u = np.where((x % 12) < 2, 1.0, 0.0)
    elif name == "braid":
        u = np.minimum(1, np.abs(np.sin(x * np.pi / 16)) * 0.7 + np.abs(np.sin(x * np.pi / 6)) * 0.45)
    elif name == "hills":
        u = (np.sin(x * np.pi / 20) * 0.5 + 0.5) ** 4
    elif name == "barcode":
        u = np.where(((x * 3) % 17 < 3) | (x % 11 < 2), 1.0, 0.0)
    elif name == "arches":
        p = (x % 20) - 10
        u = 1 - np.sqrt(np.maximum(1 - (p / 10) ** 2, 0))
    elif name == "terraces":
        u = np.floor((np.sin(x * np.pi / 15) * 0.5 + 0.5) * 5) / 5
    elif name == "cusps":
        u = np.abs(np.sin(x * np.pi / 11)) ** 0.35
    elif name == "lace":
        u = np.minimum(np.abs((x % 22) - 11) / 11, np.abs((x % 14) - 7) / 7)
    elif name == "drip":
        u = ((x % 22) / 22) ** 3
    elif name == "heartbeat":
        s = np.abs(np.sin(x * np.pi / 26))
        u = s ** 8 * 0.85 + np.abs(np.sin(x * np.pi / 26 + 1.4)) ** 14 * 0.4
    elif name == "cross":
        u = np.maximum(np.where((x % 20) < 2, 1.0, 0.0), np.where(np.abs((x % 20) - 10) < 2, 0.65, 0.0))
    else:
        u = np.abs((x % 28) - 14) / 14
    return np.clip(u, 0, 1)


def fringe_px(height: int) -> int:
    """Thin edge. A 730px art band gets about 16px, not a third of the frame."""
    return int(min(18, max(6, round(height * 0.022))))


def shuffle(seed: str) -> list[str]:
    order = list(NAMES)
    random.Random(seed).shuffle(order)
    return order


def ffmpeg_cycle(seed: str, depth: int, every: float = 30.0) -> str:
    """geq expression: shuffled shapes, one every `every` seconds, in pixels."""
    rng = random.Random(seed)
    order = list(range(len(_EXPR)))
    rng.shuffle(order)
    xoff = rng.randrange(8, 80)

    def one(idx: int) -> str:
        expr = _EXPR[idx][1].replace("X", f"(X+{xoff})")
        return expr.replace(",", "\\,")

    n = len(_EXPR)
    cut = f"({one(order[-1])})*{depth}"
    for slot in range(n - 1, -1, -1):
        cut = (
            f"if(eq(floor(mod(T/{every}\\,{n}))\\,{slot})\\,"
            f"({one(order[slot])})*{depth}\\,{cut})"
        )
    return cut
