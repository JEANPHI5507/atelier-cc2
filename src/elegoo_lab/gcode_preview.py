"""Extract printed paths from a G-code for the web preview (layer slider, supports, colours).

Output is compact: one int16 array of segments ``x0 y0 x1 y1`` in 1/50 mm, plus per-segment
layer index, kind and tool, so a 60 mm multicolour figurine stays a few MB before gzip.
"""

from __future__ import annotations

import base64
import math
import re
from pathlib import Path
from typing import Any

import numpy as np

KINDS = {"model": 0, "support": 1, "tower": 2}
SCALE = 50  # int16 units per mm (±655 mm range)
REVIEW = 1_200_000  # segments in the review's whole-print view (gallery.js asks for the same)
_NUM = re.compile(r"([XYZEF])(-?\d*\.?\d+)")


def _kind(t: str) -> int:
    t = t.lower()
    if "support" in t:
        return KINDS["support"]
    if "prime tower" in t or "wipe tower" in t:
        return KINDS["tower"]
    return KINDS["model"]


def extract(path: Path) -> dict[str, Any]:
    x = y = z = 0.0
    absolute_e, kind, tool, last_e = False, 0, 0, 0.0
    layer_z: list[float] = []
    seg, lay, knd, tl = [], [], [], []
    colours: list[str] = []
    with path.open("r", errors="ignore") as f:
        for line in f:
            c = line[:1]
            if c == ";":
                if line.startswith(
                    ";Z:"
                ):  # OrcaSlicer layer marker: the start purge line comes before
                    layer_z.append(float(line[3:]))
                elif line.startswith(";TYPE:"):
                    kind = _kind(line[6:].strip())
                elif line.startswith("; filament_colour = ") and not colours:
                    colours = [h.strip() for h in line.split("=", 1)[1].split(";")]
                continue
            if c == "T" and line[1:2].isdigit():
                tool = int(line[1:].split()[0])
                continue
            if c == "M":
                if line.startswith("M82"):
                    absolute_e = True
                elif line.startswith("M83"):
                    absolute_e = False
                continue
            if c != "G" or line[1:3] not in ("0 ", "1 ", "2 ", "3 ", "0\n", "1\n"):
                if line.startswith("G92") and "E" in line:
                    last_e = 0.0
                continue
            vals = dict(_NUM.findall(line.split(";", 1)[0]))
            nx = float(vals["X"]) if "X" in vals else x
            ny = float(vals["Y"]) if "Y" in vals else y
            nz = float(vals["Z"]) if "Z" in vals else z
            extruding = False
            if "E" in vals:
                e = float(vals["E"])
                extruding = (e - last_e) > 0 if absolute_e else e > 0
                if absolute_e:
                    last_e = e
            if extruding and layer_z and line[1] in "123" and (nx != x or ny != y):
                li = len(layer_z) - 1
                seg.append((x, y, nx, ny))
                lay.append(li)
                knd.append(kind)
                tl.append(tool)
            x, y, z = nx, ny, nz
    s = (
        np.round(np.asarray(seg, dtype=float) * SCALE).astype("<i2")
        if seg
        else np.zeros((0, 4), "<i2")
    )
    return {
        "scale": SCALE,
        "layers": [round(v, 3) for v in layer_z],
        "colours": colours,
        "count": len(seg),
        "segments": base64.b64encode(s.tobytes()).decode(),
        "layer": base64.b64encode(np.asarray(lay, "<u2").tobytes()).decode(),
        "kind": base64.b64encode(np.asarray(knd, "u1").tobytes()).decode(),
        "tool": base64.b64encode(np.asarray(tl, "u1").tobytes()).decode(),
        "stats": {k: int((np.asarray(knd) == v).sum()) for k, v in KINDS.items()},
    }


_cache: dict[tuple[str, int, int, int], dict[str, Any]] = {}


def cached(path: Path, most: int = 0) -> dict[str, Any]:
    """``extract`` kept for the file's current version (a big figure takes seconds to read); ``most`` > 0: ``lite``."""
    st = path.stat()
    key = (str(path), st.st_mtime_ns, st.st_size, most)
    if key not in _cache:
        full = (str(path), st.st_mtime_ns, st.st_size, 0)
        d = _cache.get(full) or extract(path)
        _cache[full] = d
        if most:
            _cache[key] = lite(d, most)
        while len(_cache) > 4:  # a few big prints at most: each is tens of MB
            _cache.pop(next(iter(_cache)))
    return _cache[key]


def lite(d: dict[str, Any], most: int) -> dict[str, Any]:
    """The same print with one layer out of every few kept, so a whole big print shows quickly (the review's 3D view).
    The layer list stays whole: indices still match the printed layers."""
    if d["count"] <= most:
        return d
    step = math.ceil(d["count"] / most)
    seg = np.frombuffer(base64.b64decode(d["segments"]), "<i2").reshape(-1, 4)
    lay = np.frombuffer(base64.b64decode(d["layer"]), "<u2")
    knd = np.frombuffer(base64.b64decode(d["kind"]), "u1")
    tl = np.frombuffer(base64.b64decode(d["tool"]), "u1")
    keep = (lay % step == 0) | (lay == lay.max())  # the top layer always: it is what one sees
    return {
        **d,
        "count": int(keep.sum()),
        "pas": step,
        "segments": base64.b64encode(seg[keep].tobytes()).decode(),
        "layer": base64.b64encode(lay[keep].tobytes()).decode(),
        "kind": base64.b64encode(knd[keep].tobytes()).decode(),
        "tool": base64.b64encode(tl[keep].tobytes()).decode(),
    }
