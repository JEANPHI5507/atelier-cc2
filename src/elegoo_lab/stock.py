"""Spool stock and print costs.

Every CANVAS tray has a spool weight, what is left on it and a price per kilo. Slicing records how
many grams each tray will use (OrcaSlicer's extrusion plus the CC2's purge into the chute); when the
watcher sees the print end, the grams are taken off the trays (in proportion to the progress if the
print was stopped). Before a print starts, the workshop checks that every tray holds enough.

A spool taken out of the CANVAS is set aside with what is left on it; when a spool of the same identity
(RFID code, colour, material) comes back in any tray it takes that weight again. Any other spool is counted
as a new full one; the user can correct the weight in the Imprimante tab. Kept in models/.bobines.json.
"""

from __future__ import annotations

import json
import math
import threading
import time
from typing import Any

from . import config

TRAYS = 4
SPOOL_G = 1000.0
PRICE_KG = 20.0                # € per kg until the user says otherwise
LOW_G = 100.0                  # below this a spool is "presque vide"
DIAMETER = 1.75
DENSITY = {"PLA": 1.24, "PLA+": 1.24, "PLA-CF": 1.30, "PETG": 1.27, "PETG-CF": 1.30, "ABS": 1.04, "ASA": 1.07,
           "TPU": 1.21, "PC": 1.20, "PA": 1.14}
_lock = threading.Lock()


def _file():
    return config.MODELS_DIR / ".bobines.json"   # looked up each time: tests swap the library


def load() -> dict[str, Any]:
    try:
        data = json.loads(_file().read_text())
    except (OSError, ValueError):
        data = {}
    data.setdefault("trays", {})
    data.setdefault("prints", {})
    data.setdefault("history", [])
    data.setdefault("rangees", {})   # spools taken out, by identity: what was left on them
    for i in range(TRAYS):
        data["trays"].setdefault(str(i), {"poids_g": SPOOL_G, "restant_g": SPOOL_G, "prix_kg": PRICE_KG,
                                          "matiere": "PLA", "couleur": "", "nom": "", "code": "", "depuis": 0})
    return data


def save(data: dict[str, Any]) -> None:
    f = _file()
    f.parent.mkdir(exist_ok=True)
    data["prints"] = dict(list(data["prints"].items())[-300:])
    data["history"] = data["history"][-300:]
    config.write_atomic(f, json.dumps(data, ensure_ascii=False, indent=1))


def grams(metres: float, material: str = "PLA") -> float:
    area = math.pi * (DIAMETER / 2) ** 2                         # mm²
    return metres * 1000 * area / 1000 * DENSITY.get(material.upper(), 1.24)   # cm³ × g/cm³


def _ident(code: str, colour: str, material: str) -> str:
    return f"{code}|{colour.upper()}|{material.upper()}"


def sync(loaded: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Follow what the CANVAS reports; returns the trays that just got another spool: ``{"tray", "remise",
    "restant_g", "nom"}``, ``remise`` when it is a spool taken out earlier (its weight is back)."""
    changed = []
    with _lock:
        data = load()
        aside = data["rangees"]
        moves, seen = [], set()
        for t in loaded:
            i = str(int(t.get("pos", t["tray_id"])))   # place in the CANVAS (0-3), whatever the printer's numbering
            if i not in data["trays"]:
                continue
            seen.add(i)
            cur = data["trays"][i]
            ident = (str(t.get("code") or ""), t["color"].upper(), str(t.get("type") or "PLA").upper())
            known = (cur["code"], cur["couleur"].upper(), cur["matiere"].upper())
            if ident != known:
                moves.append((i, t, ident))
                if cur["couleur"]:  # the spool leaving keeps its weight: the same colour often comes back days later
                    aside[_ident(*known)] = {k: cur[k] for k in ("poids_g", "restant_g", "prix_kg", "nom", "depuis")} | {
                        "retiree": int(time.time())}
        for i, t, ident in moves:   # after every departure: two spools swapping trays both find their weight
            cur = data["trays"][i]
            back = aside.pop(_ident(*ident), None)
            for j, other in data["trays"].items():   # or moved from a tray that is empty now
                if not back and j not in seen and other["couleur"] and _ident(
                        other["code"], other["couleur"], other["matiere"]) == _ident(*ident):
                    back = dict(other)
                    other.update(code="", couleur="", nom="", restant_g=other["poids_g"])   # the next spool there is new
            if back:
                cur.update({k: back[k] for k in ("poids_g", "restant_g", "prix_kg", "depuis")})
            elif cur["couleur"]:    # not the very first time we see this tray: a new spool
                cur.update(restant_g=cur["poids_g"], depuis=int(time.time()))
            if back or cur["couleur"]:
                changed.append({"tray": int(i), "remise": bool(back), "restant_g": round(cur["restant_g"]),
                                "nom": t.get("filament_name") or ident[2]})
            cur.update(code=ident[0], couleur=ident[1], matiere=ident[2], nom=t.get("filament_name") or ident[2])
        while len(aside) > 40:
            aside.pop(next(iter(aside)))
        save(data)
    return changed


def set_tray(tray: int, *, restant_g: float | None = None, poids_g: float | None = None, prix_kg: float | None = None,
             nouvelle: bool = False) -> dict[str, Any]:
    if not 0 <= tray < TRAYS:
        raise ValueError("bobine inconnue")
    with _lock:
        data = load()
        cur = data["trays"][str(tray)]
        if poids_g is not None:
            if not 50 <= poids_g <= 10000:
                raise ValueError("poids de bobine entre 50 et 10 000 g")
            cur["poids_g"] = float(poids_g)
        if prix_kg is not None:
            if not 0 <= prix_kg <= 500:
                raise ValueError("prix entre 0 et 500 €/kg")
            cur["prix_kg"] = float(prix_kg)
        if nouvelle:
            cur.update(restant_g=cur["poids_g"], depuis=int(time.time()))
        if restant_g is not None:
            if not 0 <= restant_g <= cur["poids_g"]:
                raise ValueError(f"restant entre 0 et {cur['poids_g']:.0f} g")
            cur["restant_g"] = float(restant_g)
        save(data)
        return cur


def _per_tray(per_filament_m: list[float], purge_m: list[float] | None, route: dict | None) -> dict[int, tuple[float, float]]:
    """Metres (printed, purged) per CANVAS tray. ``route`` maps the file's filament to the tray that feeds it
    (the colour -> spool map sent at launch); without one the firmware feeds filament i from tray i."""
    out: dict[int, tuple[float, float]] = {}
    for i, m in enumerate(per_filament_m[:TRAYS]):
        p = (purge_m or [])[i] if purge_m and i < len(purge_m) else 0.0
        t = int((route or {}).get(str(i), i))
        if m + p > 0 and 0 <= t < TRAYS:
            a, b = out.get(t, (0.0, 0.0))
            out[t] = (a + m, b + p)
    return out


def usage(per_filament_m: list[float], purge_m: list[float] | None = None, route: dict | None = None) -> dict[str, Any]:
    """Grams and cost per tray for one slicing result."""
    data = load()
    out, total_g, total_eur = [], 0.0, 0.0
    for i, (m, p) in sorted(_per_tray(per_filament_m, purge_m, route).items()):
        tray = data["trays"][str(i)]
        g = grams(m + p, tray["matiere"])
        eur = g / 1000 * tray["prix_kg"]
        out.append({"tray": i, "g": round(g, 1), "purge_g": round(grams(p, tray["matiere"]), 1), "eur": round(eur, 2),
                    "restant_g": round(tray["restant_g"]), "manque": g > tray["restant_g"]})
        total_g, total_eur = total_g + g, total_eur + eur
    return {"trays": out, "g": round(total_g, 1), "eur": round(total_eur, 2)}


def record_route(gcode_name: str, route: dict[int, int]) -> None:
    """At launch: which tray feeds each filament of the file, so the count at the end hits the right spools."""
    with _lock:
        data = load()
        rec = data["prints"].get(gcode_name)
        if rec is not None:
            rec["route"] = {str(k): int(v) for k, v in route.items()}
            save(data)


def record_slice(gcode_name: str, per_filament_m: list[float], purge_m: list[float] | None = None) -> dict[str, Any]:
    """Remember what this G-code will use, for the check before printing and the count at the end."""
    u = usage(per_filament_m, purge_m)
    with _lock:
        data = load()
        data["prints"][gcode_name] = {"per_m": per_filament_m, "purge_m": purge_m or [], "g": u["g"], "eur": u["eur"],
                                      "t": int(time.time())}
        save(data)
    return u


def check(gcode_name: str, route: dict | None = None) -> dict[str, Any] | None:
    """Before printing: grams per tray against what is left (None if we never sliced this file)."""
    rec = load()["prints"].get(gcode_name)
    if not rec:
        return None
    u = usage(rec["per_m"], rec["purge_m"], {str(k): v for k, v in route.items()} if route else None)
    u["manques"] = [t for t in u["trays"] if t["manque"]]
    return u


def consume(gcode_name: str, fraction: float, ref: str) -> list[dict[str, Any]]:
    """Take a finished (or stopped) print off the spools; once per ``ref``. Returns trays now nearly empty."""
    with _lock:
        data = load()
        rec = data["prints"].get(gcode_name)
        if not rec or any(h.get("ref") == ref for h in data["history"]):
            return []
        fraction = max(0.0, min(1.0, fraction))
        low, used = [], []
        for i, (m, p) in sorted(_per_tray(rec["per_m"], rec["purge_m"], rec.get("route")).items()):
            tray = data["trays"][str(i)]
            g = grams(m + p, tray["matiere"]) * fraction
            if g <= 0:
                continue
            before = tray["restant_g"]
            tray["restant_g"] = round(max(0.0, before - g), 1)
            used.append({"tray": i, "g": round(g, 1), "eur": round(g / 1000 * tray["prix_kg"], 2)})
            if tray["restant_g"] < LOW_G <= before:
                low.append({"tray": i, "restant_g": tray["restant_g"], "nom": tray["nom"]})
        data["history"].append({"ref": ref, "t": int(time.time()), "fichier": gcode_name, "part": round(fraction, 2),
                                "g": round(sum(u["g"] for u in used), 1), "eur": round(sum(u["eur"] for u in used), 2),
                                "detail": used})
        save(data)
        return low


def summary() -> dict[str, Any]:
    data = load()
    month = time.strftime("%Y-%m")
    this_month = [h for h in data["history"] if time.strftime("%Y-%m", time.localtime(h["t"])) == month]
    return {"trays": [{"tray": int(i), **t} for i, t in sorted(data["trays"].items())],
            "history": list(reversed(data["history"][-30:])),
            "mois": {"g": round(sum(h["g"] for h in this_month)), "eur": round(sum(h["eur"] for h in this_month), 2),
                     "impressions": sum(1 for h in this_month if h["g"] > 0)},   # not the ones cancelled at 0 %
            "low_g": LOW_G}
