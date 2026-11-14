"""Which colour prints now and which ones come next, from the print's G-code.

On the CC2 a colour change is ``M6211 T<n> L<flush mm>`` (the first ones, before layer 1, load the first colour).
Each one is placed at its layer, with the slicer's remaining time there (``M73 R<minutes>``), so the page can say
"next: red at layer 64, in 3 min". The colour engaged right now is what the CANVAS reports (active tray); the
G-code tool of each change goes to a tray through the slot route chosen at launch.
"""

from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path
from typing import Any

from . import slicer

_TOOL = re.compile(r"\bT(\d+)")
_LEN = re.compile(r"\bL([\d.]+)")
_REMAIN = re.compile(r"^M73 P\d+ R(\d+)")


@lru_cache(maxsize=4)
def _scan(path: str, mtime: float) -> dict[str, Any]:
    layer, remain = 0, None
    first_tool, changes, remain_at = None, [], [None]   # remain_at[i]: minutes left when layer i starts
    colours: list[str] = []
    types: list[str] = []
    purges = []   # (layer, tool, mm): every change that pushes filament into the chute
    with open(path, errors="ignore") as f:
        for line in f:
            c = line[:1]
            if c == ";":
                if line.startswith(";Z:"):
                    layer += 1
                    remain_at.append(remain)
                elif line.startswith("; filament_colour = ") and not colours:
                    colours = [h.strip() for h in line.split("=", 1)[1].split(";")]
                elif line.startswith("; filament_type = ") and not types:
                    types = [h.strip() for h in line.split("=", 1)[1].split(";")]
            elif c == "M":
                if line.startswith("M6211") and (m := _TOOL.search(line)):
                    t = int(m.group(1))
                    if (n := _LEN.search(line)) and float(n.group(1)) > 0:   # L0: the tool already loaded, no purge
                        purges.append((layer, t, max(float(n.group(1)), slicer.FLUSH_FLOOR_MM) + slicer.FLUSH_EXTRA_MM))
                    if layer == 0:
                        first_tool = t
                    elif not changes or changes[-1][1] != t:
                        changes.append((layer, t, remain))
                elif line.startswith("M73 P") and (m := _REMAIN.match(line)):
                    remain = int(m.group(1))
    return {"first": first_tool if first_tool is not None else 0, "changes": changes, "purges": purges,
            "remain_at": remain_at, "colours": colours, "types": types, "layers": layer}


def plan(path: Path, layer: int, active: int | None = None, upcoming: int = 4) -> dict[str, Any]:
    """The tool printing now, the next ``upcoming`` changes and how many are left.

    ``layer`` is the printer's current layer; ``active`` the G-code tool of the spool the CANVAS has engaged, if known.
    A layer can hold several changes: the active tool says how far into the layer the print is."""
    d = _scan(str(path), path.stat().st_mtime)
    layer = max(1, layer)
    by_gcode = d["first"]
    for li, t, _ in d["changes"]:
        if li > layer:
            break
        by_gcode = t
    here = [c for c in d["changes"] if c[0] == layer]
    later = [c for c in d["changes"] if c[0] > layer]
    done_here = next((i + 1 for i, c in enumerate(here) if c[1] == active), 0) if active is not None else len(here)
    ahead = here[done_here:] + later
    now = active if active is not None else by_gcode
    r_now = d["remain_at"][min(layer, len(d["remain_at"]) - 1)]
    # purge still to come per tool, counted the way slicer.firmware_purge_m counts it for the whole print
    here_p = [p for p in d["purges"] if p[0] == layer]
    todo = here_p[min(done_here, len(here_p)):] + [p for p in d["purges"] if p[0] > layer]
    purge: dict[int, list[float]] = {}   # tool -> [metres left, metres in all, purges left, purges in all]
    for _, t, mm in d["purges"]:
        q = purge.setdefault(t, [0.0, 0.0, 0, 0])
        q[1] += mm / 1000
        q[3] += 1
    for _, t, mm in todo:
        purge[t][0] += mm / 1000
        purge[t][2] += 1
    return {"tool": now, "colours": d["colours"], "types": d["types"], "layers": d["layers"], "left": len(ahead),
            "total": len(d["changes"]),
            "purge": [{"tool": t, "left": n, "count": c, "left_m": round(a, 3), "total_m": round(b, 3)}
                      for t, (a, b, n, c) in sorted(purge.items())],
            "next": [{"layer": li, "tool": t,
                      "min": max(0, r_now - r) if r_now is not None and r is not None else None} for li, t, r in ahead[:upcoming]]}
