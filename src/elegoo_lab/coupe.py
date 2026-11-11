"""The print in section, for the wall tablet: drawn in 2D from the G-code, light enough for an old tablet.

Two pictures share one scale: the part seen from the front (for each layer, which stretches of X hold plastic and
in which colour), and the layer being printed seen from above (its paths, thinned out to a few thousand lines).
The tablet colours the layers already printed and greys the rest.
"""

from __future__ import annotations

import base64
from functools import lru_cache
from pathlib import Path
from typing import Any

import numpy as np

from . import gcode_preview

BIN_MM = 1.0           # width of one column of the front view
MAX_SECTION = 5000     # lines kept for the layer seen from above


@lru_cache(maxsize=4)
def _load(path: str, mtime: float) -> dict[str, Any]:
    d = gcode_preview.extract(Path(path))
    k = 1 / d["scale"]
    seg = np.frombuffer(base64.b64decode(d["segments"]), "<i2").reshape(-1, 4).astype(np.float32) * k
    lay = np.frombuffer(base64.b64decode(d["layer"]), "<u2")
    kind = np.frombuffer(base64.b64decode(d["kind"]), "u1")
    tool = np.frombuffer(base64.b64decode(d["tool"]), "u1")
    model = kind == gcode_preview.KINDS["model"]              # the part itself: supports and tower left out
    seg, lay, tool = seg[model], lay[model], tool[model]
    xs, ys = seg[:, [0, 2]], seg[:, [1, 3]]
    box = [float(xs.min()), float(ys.min()), float(xs.max()), float(ys.max())] if len(seg) else [0, 0, 1, 1]
    # front view: for each layer and column of X, the colour that covers it most
    nb = max(1, int(np.ceil((box[2] - box[0]) / BIN_MM)))
    front: list[list[list[int]]] = []
    order = np.argsort(lay, kind="stable")
    seg, lay, tool = seg[order], lay[order], tool[order]
    starts = np.searchsorted(lay, np.arange(len(d["layers"]) + 1))
    for li in range(len(d["layers"])):
        a, b = starts[li], starts[li + 1]
        runs: list[list[int]] = []
        if b > a:
            lo = ((np.minimum(seg[a:b, 0], seg[a:b, 2]) - box[0]) / BIN_MM).astype(int).clip(0, nb - 1)
            hi = ((np.maximum(seg[a:b, 0], seg[a:b, 2]) - box[0]) / BIN_MM).astype(int).clip(0, nb - 1)
            cover = np.zeros((int(tool[a:b].max()) + 1, nb + 1), np.int32)
            for t in np.unique(tool[a:b]):
                m = tool[a:b] == t
                np.add.at(cover[t], lo[m], 1)
                np.add.at(cover[t], hi[m] + 1, -1)
            cover = np.cumsum(cover, axis=1)[:, :nb]
            col = np.where(cover.max(axis=0) > 0, cover.argmax(axis=0), -1)
            i = 0
            while i < nb:                                     # runs of one colour: [first column, last column, tool]
                j = i
                while j + 1 < nb and col[j + 1] == col[i]:
                    j += 1
                if col[i] >= 0:
                    runs.append([i, j, int(col[i])])
                i = j + 1
        front.append(runs)
    return {"layers": d["layers"], "colours": d["colours"], "box": box, "bin": BIN_MM, "front": front,
            "seg": seg, "lay": lay, "tool": tool, "starts": starts}


def coupe(path: Path, layer: int, front: bool = True) -> dict[str, Any]:
    """The paths of ``layer`` (1 = first) seen from above, in mm, and with ``front`` the whole part seen from the front."""
    d = _load(str(path), path.stat().st_mtime)
    n = len(d["layers"])
    li = min(max(layer, 1), n) - 1 if n else 0
    a, b = (d["starts"][li], d["starts"][li + 1]) if n else (0, 0)
    seg, tool = d["seg"][a:b], d["tool"][a:b]
    if len(seg) > MAX_SECTION:                                # keep the longest lines: the outline stays whole
        keep = np.argsort(-np.hypot(seg[:, 2] - seg[:, 0], seg[:, 3] - seg[:, 1]))[:MAX_SECTION]
        keep.sort()
        seg, tool = seg[keep], tool[keep]
    return {"layers": d["layers"], "colours": d["colours"], "box": [round(v, 1) for v in d["box"]], "bin": d["bin"],
            **({"front": d["front"]} if front else {}), "layer": li + 1,
            "section": np.round(seg, 1).ravel().tolist(), "tools": tool.tolist()}
