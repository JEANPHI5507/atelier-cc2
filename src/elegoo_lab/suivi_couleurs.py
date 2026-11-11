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

_TOOL = re.compile(r"\bT(\d+)")
_REMAIN = re.compile(r"^M73 P\d+ R(\d+)")


@lru_cache(maxsize=4)
def _scan(path: str, mtime: float) -> dict[str, Any]:
    layer, remain = 0, None
    first_tool, changes, remain_at = None, [], [None]   # remain_at[i]: minutes left when layer i starts
    colours: list[str] = []
    with open(path, errors="ignore") as f:
        for line in f:
            c = line[:1]
            if c == ";":
                if line.startswith(";Z:"):
                    layer += 1
                    remain_at.append(remain)
                elif line.startswith("; filament_colour = ") and not colours:
                    colours = [h.strip() for h in line.split("=", 1)[1].split(";")]
            elif c == "M":
                if line.startswith("M6211") and (m := _TOOL.search(line)):
                    t = int(m.group(1))
                    if layer == 0:
                        first_tool = t
                    elif not changes or changes[-1][1] != t:
                        changes.append((layer, t, remain))
                elif line.startswith("M73 P") and (m := _REMAIN.match(line)):
                    remain = int(m.group(1))
    return {"first": first_tool if first_tool is not None else 0, "changes": changes,
            "remain_at": remain_at, "colours": colours, "layers": layer}


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
    return {"tool": now, "colours": d["colours"], "layers": d["layers"], "left": len(ahead), "total": len(d["changes"]),
            "next": [{"layer": li, "tool": t,
                      "min": max(0, r_now - r) if r_now is not None and r is not None else None} for li, t, r in ahead[:upcoming]]}
