"""Match a model's colours with the spools actually loaded in the CANVAS.

Each model colour goes to the loaded spool that looks closest (ΔE in CIELAB). The assignment is
global (Hungarian method) so two colours do not fight over one spool while another sits unused,
and each spool's material picks the matching OrcaSlicer filament profile.
"""

from __future__ import annotations

import re
from typing import Any

import numpy as np
from scipy.optimize import linear_sum_assignment

from . import catalog, colors, slicer

HEX = re.compile(r"#[0-9A-Fa-f]{6}")
FAR_DE = 25.0   # beyond this ΔE the closest spool is visibly another colour
LOW_TEMP = {"PLA", "PLA+", "PLA-CF", "TPU"}   # materials printed around 190-230 °C
# the printer's colour palette is coarse (pure red is ΔE 33 from a Christmas red): a typed-in spool is
# one of the user's own when that one is near enough and clearly nearer than the next one
OWN_DE, OWN_RATIO = 50.0, 1.5
# a spool the printer names with one of these is an Elegoo variant, not one of the user's own
VARIANTS = {"BASIC", "MATTE", "GALAXY", "GLOW", "MARBLE", "PRO", "SPARKLE", "TRANSLUCENT", "TRANSLUCENT2", "WOOD", "CF", "RAPID", "HF"}


def loaded(canvas: dict[str, Any]) -> list[dict[str, Any]]:
    """Loaded trays from a CANVAS status (pycentauri /canvas payload or CanvasStatus.raw).

    Elegoo's SDK names the fields ``filament_color`` / ``filament_type`` / ``filament_code``, numbers
    the trays 1-4 (0 = empty) and marks a spool 1 (pre-loaded) or 2 (loaded); older captures and the
    simulator used ``color`` / ``type`` and 0-3. Both are read. ``pos`` is the tray's place in the unit
    (0-3, the slicer's T0-T3); ``tray_id`` stays the printer's own number, for the start command."""
    info = canvas.get("canvas_info", canvas)
    out = []
    for unit in info.get("canvas_list", []) or []:
        for pos, t in enumerate(unit.get("tray_list", []) or []):
            colour = str(t.get("filament_color") or t.get("color") or "").strip()
            if t.get("status") not in (1, 2) or not HEX.fullmatch(colour):  # printer data: never trust it into the page
                continue
            out.append(own({**t, "pos": pos, "tray_id": int(t.get("tray_id", pos)), "canvas_id": int(unit.get("canvas_id", 0)),
                            "color": colour.upper(), "filament_name": str(t.get("filament_name") or "")[:40],
                            "type": str(t.get("filament_type") or t.get("type") or "PLA")[:16],
                            "code": str(t.get("filament_code") or t.get("code") or "")[:32]}))
    return out


def own(tray: dict[str, Any], mine: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """A tray that is one of the user's own spools (catalog) takes its true colour, name and profile.

    Same material family and the closest colour (OWN_DE, OWN_RATIO); ``printer_color`` keeps what the
    printer said. Trays named as another Elegoo variant (Matte, Galaxy...) are left alone."""
    mine = catalog.spools() if mine is None else mine
    words = set(re.split(r"[\s\-_]+", f"{tray.get('type', '')} {tray.get('filament_name', '')}".upper()))
    family = re.split(r"[\s\-_]+", str(tray.get("type") or "PLA").upper())[0]
    cands = [b for b in mine if str(b.get("matiere") or "PLA").upper() == family and HEX.fullmatch(str(b["couleur"]))]
    if not cands or words & VARIANTS:
        return tray
    lab = colors._to_lab(np.array([colors._rgb(tray["color"])] + [colors._rgb(b["couleur"]) for b in cands]))
    de = np.linalg.norm(lab[1:] - lab[0], axis=1)
    i, *rest = np.argsort(de)
    if de[i] > OWN_DE or (rest and de[rest[0]] < OWN_RATIO * de[i]):
        return tray
    b = cands[i]
    return {**tray, "printer_color": tray["color"], "color": b["couleur"].upper(), "profile": b["profil"],
            "filament_name": str(b.get("nom") or b["profil"])[:40]}


def filament_for(tray: dict[str, Any]) -> str:
    """OrcaSlicer profile name for a tray: same material, and the variant named on the spool if known."""
    known = slicer.filaments()
    if tray.get("profile") in known:
        return tray["profile"]
    material = str(tray.get("type") or "PLA").strip().upper()
    name = f"{tray.get('filament_name') or ''} {tray.get('brand') or ''}".upper()
    same = [k for k in known if k.split()[0].upper() == material]
    variants = sorted((k for k in same if " " in k and all(w.upper() in name for w in k.split()[1:])), key=len, reverse=True)
    if variants:
        return variants[0]
    if any(k.upper() == material for k in known):
        return next(k for k in known if k.upper() == material)
    return "PLA" if material.startswith("PLA") else (same[0] if same else "PLA")


def single(colour: dict[str, Any], trays: list[dict[str, Any]], *, coloured: bool,
           active: int | None = None) -> dict[str, Any]:
    """Spool for a one-colour model, in the same shape as match(). The model slices as T0 whatever the
    spool, so ``slot`` stays 1 and ``tray_pos`` says which spool feeds it: the closest colour when the
    model has one, else the spool already in the head (``active`` = its tray_id), else the first one."""
    if not trays:
        raise ValueError("aucune bobine chargée dans le CANVAS")
    lab = colors._to_lab(np.array([colors._rgb(colour["hex"])] + [colors._rgb(t["color"]) for t in trays]))
    de = np.linalg.norm(lab[1:] - lab[0], axis=1)
    if coloured:
        i = int(np.argmin(de))
    else:
        i = next((k for k, t in enumerate(trays) if t["tray_id"] == active), 0)
    t, d = trays[i], float(de[i])
    warnings = []
    if coloured and d > FAR_DE:
        warnings.append(f"La couleur {colour['hex']} du modèle n'a pas de bobine proche : il sortira en "
                        f"{t.get('filament_name') or t['color']} (bobine {t['pos'] + 1}).")
    return {"mapping": {colour["index"]: 1}, "filaments": [filament_for(t)], "warnings": warnings,
            "details": [{"index": colour["index"], "hex": colour["hex"], "share": colour["share"], "slot": 1, "tray_pos": t["pos"],
                         "tray_hex": t["color"], "tray_name": t.get("filament_name") or t.get("type"), "de": round(d, 1)}],
            "slot_colours": {1: t["color"]}, "unused": [], "single": {"pos": t["pos"], "tray_id": t["tray_id"]}}


def far_colours(model_colours: list[dict[str, Any]], trays: list[dict[str, Any]]) -> list[str]:
    """Warnings for the model's own colours that no loaded spool comes near (repainting changes them)."""
    if not trays or not model_colours:
        return []
    lab = colors._to_lab(np.array([colors._rgb(c["hex"]) for c in model_colours]))
    tl = colors._to_lab(np.array([colors._rgb(t["color"]) for t in trays]))
    de = np.linalg.norm(lab[:, None] - tl[None], axis=2)
    out = []
    for c, row in zip(model_colours, de):
        t = trays[int(row.argmin())]
        if row.min() > FAR_DE and c["share"] >= 2:
            out.append(f"La couleur {c['hex']} ({c['share']:.0f} % du modèle) n'a pas de bobine proche : elle sera "
                       f"imprimée en {t.get('filament_name') or t['color']} (bobine {t['pos'] + 1}), la plus proche chargée.")
    return out


def match(model_colours: list[dict[str, Any]], trays: list[dict[str, Any]]) -> dict[str, Any]:
    """``model_colours``: colors.analyze()["colours"]; ``trays``: loaded() output.

    Returns the colour→slot mapping (slot = pos + 1), one filament profile per slot up to the
    highest one used, the detail of each pairing and plain-French warnings."""
    if not trays:
        raise ValueError("aucune bobine chargée dans le CANVAS")
    if not model_colours:
        raise ValueError("le modèle n'a pas de couleur détectée")
    mc = np.array([colors._rgb(c["hex"]) for c in model_colours])
    tc = np.array([colors._rgb(t["color"]) for t in trays])
    de = np.linalg.norm(colors._to_lab(mc)[:, None] - colors._to_lab(tc)[None], axis=2)

    order = np.argsort([-c["share"] for c in model_colours])   # biggest areas choose first
    pick = {}
    head = order[: len(trays)]
    rows, cols = linear_sum_assignment(de[head])
    for r, c in zip(rows, cols):
        pick[int(head[r])] = int(c)
    for i in order[len(trays):]:                               # more colours than spools: share the nearest
        pick[int(i)] = int(np.argmin(de[i]))

    mapping, details, warnings = {}, [], []
    for i, c in enumerate(model_colours):
        t = trays[pick[i]]
        slot = t["pos"] + 1
        mapping[c["index"]] = slot
        d = float(de[i, pick[i]])
        details.append({"index": c["index"], "hex": c["hex"], "share": c["share"], "slot": slot, "tray_pos": t["pos"],
                        "tray_hex": t["color"], "tray_name": t.get("filament_name") or t.get("type"), "de": round(d, 1)})
        if d > FAR_DE and c["share"] >= 2:
            warnings.append(f"La couleur {c['hex']} ({c['share']:.0f} % du modèle) n'a pas de bobine proche : elle sortira en "
                            f"{t.get('filament_name') or t['color']} (bobine {slot}). Charge une bobine de cette couleur pour être fidèle.")

    by_slot = {t["pos"] + 1: t for t in trays}
    top = max(mapping.values())
    filaments = [filament_for(by_slot[s]) if s in by_slot else "PLA" for s in range(1, top + 1)]
    missing = [s for s in range(1, top + 1) if s not in by_slot]
    if missing:
        warnings.append("Bobine(s) vide(s) à des emplacements intermédiaires : " + ", ".join(str(s) for s in missing)
                        + ". Le tranchage les compte, l'impression ne les utilisera pas.")
    used = {by_slot[s]["type"].upper() for s in set(mapping.values()) if s in by_slot}
    if used & LOW_TEMP and used - LOW_TEMP:
        warnings.append(f"Matières aux températures incompatibles dans le même modèle ({', '.join(sorted(used))}) : "
                        "le slicer refusera. Garde une seule famille (ex. tout en PLA).")
    unused = [t for t in trays if t["pos"] + 1 not in set(mapping.values())]
    return {"mapping": mapping, "filaments": filaments, "details": details, "warnings": warnings,
            "slot_colours": {s: by_slot[s]["color"] for s in by_slot},
            "unused": [{"slot": t["pos"] + 1, "hex": t["color"], "name": t.get("filament_name")} for t in unused]}
