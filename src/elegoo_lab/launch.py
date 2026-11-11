"""Starting a print with the CC2's own options, and the colour -> CANVAS spool map.

The CC2's start command (method 1020) takes, besides the file name, a ``config`` block that
pycentauri leaves out (from Elegoo's LAN SDK, see the printer-protocol-orchard notes):
``bedlevel_force`` (level the bed before printing), ``printer_check`` (the printer's own checks),
``print_layout`` ("A"/"B", plate side), ``delay_video`` (the printer's own timelapse) and
``slot_map``: which CANVAS spool feeds each colour of the file (``[{t, canvas_id, tray_id}]``).
Without a slot map the firmware keeps its default, the identity (T0 -> channel 0 ... T3 -> channel 3:
``CANVAS_SET_COLOR_TABLE`` in the official firmware source): right when the file's tools are in spool
order, wrong when they are not, so the map is sent. Over LAN the CC2 accepts no homing, moves or Z
offset: those stay on its screen.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import numpy as np

from . import colors, config, spools

SAME_DE = 2.0   # under this two colours are the same spool colour


def _de(a: str, b: str) -> float:
    lab = colors._to_lab(np.array([colors._rgb(a), colors._rgb(b)]))
    return float(np.linalg.norm(lab[0] - lab[1]))


DEFAULTS = {"bedlevel_force": False, "printer_check": True, "print_layout": "A", "delay_video": False}
_HEAD, _TAIL = 60_000, 120_000


def options() -> dict[str, Any]:
    """Default start options, from config.toml [lancement]."""
    out = dict(DEFAULTS)
    if config.CONFIG_FILE.exists():
        import tomllib
        for k, v in tomllib.loads(config.CONFIG_FILE.read_text()).get("lancement", {}).items():
            if k in out and type(v) is type(out[k]):
                out[k] = v
    if out["print_layout"] not in ("A", "B"):
        out["print_layout"] = "A"
    return out


def save_options(**values: Any) -> dict[str, Any]:
    cur = options()
    for k, v in values.items():
        if k not in DEFAULTS or v is None:
            continue
        if type(v) is not type(DEFAULTS[k]) or (k == "print_layout" and v not in ("A", "B")):
            raise ValueError(f"valeur invalide pour {k}")
        cur[k] = v
    config.save("lancement", **cur)
    return cur


def gcode_colours(path: Path) -> list[dict[str, Any]]:
    """The file's tools: colour, material and metres used (from OrcaSlicer's header/footer)."""
    with path.open("rb") as f:
        head = f.read(_HEAD)
        f.seek(max(0, path.stat().st_size - _TAIL))
        tail = f.read()
    text = (head + b"\n" + tail).decode("utf-8", "ignore")

    def field(name: str) -> list[str]:
        m = re.search(rf"^; {re.escape(name)} = (.*)$", text, re.M)
        return [x.strip() for x in re.split(r"[;,]", m.group(1))] if m else []
    cols, types, used = field("filament_colour"), field("filament_type"), field("filament used [mm]")
    out = []
    for i, c in enumerate(cols):
        mm = float(used[i]) if i < len(used) and re.fullmatch(r"[\d.]+", used[i]) else None
        out.append({"t": i, "colour": c.upper() if re.fullmatch(r"#[0-9A-Fa-f]{6}", c) else "#888888",
                    "type": types[i] if i < len(types) else "PLA", "m": round(mm / 1000, 2) if mm is not None else None})
    return [t for t in out if t["m"] is None or t["m"] > 0] or out[:1]


ABRASIVE = ("CF", "GF", "GLOW", "PAILLET", "GLITTER", "SPARKLE", "MARBLE")


def material_warnings(tools: list[dict[str, Any]], trays: list[dict[str, Any]]) -> list[str]:
    """What owners learnt the hard way about materials on the CC2 + CANVAS."""
    out = []
    names = " ".join(f"{t.get('type', '')} {t.get('filament_name', '')}" for t in trays).upper()
    types = {str(t["type"]).upper() for t in tools}
    if any("TPU" in t for t in types):
        out.append("TPU : il ne passe pas par le CANVAS. Utilise le canal 1 avec l'adaptateur TPU, ou alimente la tête "
                   "directement. Décoche le nivellement : il chauffe le plateau à 60 °C, le TPU en veut 35.")
    if any(a in t for t in types for a in ABRASIVE) or any(a in names for a in ABRASIVE):
        out.append("Filament abrasif (carbone, verre, phosphorescent, paillettes) : il use le capteur du CANVAS "
                   "(≈ 3 à 5 kg). Pour un usage régulier, alimente la tête directement.")
    if any(t.startswith(("PC", "PA", "PET-")) or t in ("PC", "PA", "PET") for t in types):
        out.append("Matière haute température : le chargement automatique chauffe à 250 °C, trop peu. Purge à la main "
                   "à la bonne température avant de revenir au PLA (sinon la tête se bouche).")
    if {"ABS", "ASA"} & types:
        out.append("ABS / ASA : la CC2 n'a pas de chauffage de caisson (35 à 45 °C) ; les grandes pièces gauchissent. "
                   "Bordure conseillée, et garde le capot fermé.")
    return out


def plan(path: Path | None, canvas: dict[str, Any] | None) -> dict[str, Any]:
    """What the start dialog shows: the file's colours, the loaded spools, and the suggested map."""
    tools = gcode_colours(path) if path and path.exists() else []
    trays = sorted(spools.loaded(canvas or {}), key=lambda t: t["pos"])
    unit = (canvas or {}).get("canvas_info", canvas or {}).get("canvas_list", [{}])
    canvas_id = int(unit[0].get("canvas_id", 0)) if unit else 0
    suggestion = []
    for tool in tools:
        if not trays:
            break
        # same position first (T0 -> first spool…, the order the slicer used), the closest colour if that one is far
        pos = next((tr for tr in trays if tr["pos"] == tool["t"]), None)
        best = min(trays, key=lambda tr: _de(tool["colour"], tr["color"]))
        # a spool of exactly the file's colour wins (the workshop sliced with that spool's colour)
        pick = best if _de(tool["colour"], best["color"]) < SAME_DE else pos if pos and _de(tool["colour"], pos["color"]) <= spools.FAR_DE else best
        suggestion.append({"t": tool["t"], "tray_id": int(pick["tray_id"]),
                           "far": _de(tool["colour"], pick["color"]) > spools.FAR_DE})
    return {"tools": tools, "canvas_id": canvas_id, "options": options(), "warnings": material_warnings(tools, trays),
            "trays": [{"tray_id": int(t["tray_id"]), "pos": t["pos"], "colour": t["color"], "name": t.get("filament_name") or t.get("type"),
                       "type": t.get("type")} for t in trays],
            "slot_map": suggestion}


def params(filename: str, opts: dict[str, Any], slot_map: list[dict[str, int]] | None, canvas_id: int = 0,
           storage: str = "local") -> dict[str, Any]:
    """The method-1020 payload."""
    cfg = {**options(), **{k: v for k, v in opts.items() if k in DEFAULTS}}
    cfg["slot_map"] = [{"t": int(m["t"]), "canvas_id": int(m.get("canvas_id", canvas_id)), "tray_id": int(m["tray_id"])}
                       for m in (slot_map or [])]
    return {"filename": Path(filename).name, "storage_media": storage, "config": cfg}
