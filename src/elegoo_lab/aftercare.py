"""After a print: what to do with the part now, and what to change next time.

Two parts. The tips depend on how the print was made (supports, several colours, Silk filament, its
plate temperature), read from the G-code that was printed. Then the user ticks what went wrong; each
defect comes with its cause and a correction in the workshop's own settings, computed from the values
really used (a Silk PLA printed at 230 °C gets 220 °C against stringing, not the profile's 210 - 10).
The corrections are kept on the source model and applied by itself the next time it is prepared (prepared in
printprep: the form gets them as defaults, and bled colours purge the worst case at every change).
"""

from __future__ import annotations

import re
import time
from pathlib import Path
from typing import Any, Callable

import numpy as np
from scipy import ndimage

from . import config, library

# key: (title, cause, what to do, settings for next time from the print's facts)
Fix = Callable[[dict[str, Any]], dict[str, Any]]
ISSUES: dict[str, tuple[str, str, str, Fix]] = {
    "decolle": ("Décollée ou coins relevés",
                "Pas assez de surface ou de chaleur au contact du plateau.",
                "Nettoie le plateau au liquide vaisselle et rince (pas de doigts dessus) ; la prochaine fois : bordure et plateau plus chaud.",
                lambda u: {"advanced": {"bordure": "exterieure", "largeur_bordure": 8, "temp_plateau": min(u["plateau"] + 5, 70)}}),
    "fils": ("Fils fins entre les parties",
             "Buse trop chaude ou filament humide : il coule pendant les déplacements.",
             "Les fils partent au pistolet à chaleur (passage rapide) ou à la pince. Le Silk prend l'humidité : sèche la bobine (50 °C, 6 h).",
             lambda u: {"advanced": {"temp_buse": u["buse"] - 10}}),
    "dessus": ("Dessus rugueux ou troué",
               "Pas assez de couches pleines sur le remplissage.",
               "La prochaine fois : plus de couches dessus et lissage de la face la plus haute.",
               lambda u: {"advanced": {"dessus": 6, "lissage": "dernier"}}),
    "couture": ("Ligne ou petits boutons sur le côté",
                "La couture : chaque couche commence au même endroit.",
                "Ébavure au cutter. La prochaine fois : couture cachée à l'arrière.",
                lambda u: {"advanced": {"couture": "arriere"}}),
    "fragile": ("Fragile, couches qui se séparent",
                "Couches mal soudées (buse un peu froide) ou parois trop fines.",
                "La prochaine fois : une paroi de plus, buse +5 °C, remplissage gyroïde.",
                lambda u: {"advanced": {"parois": 4, "temp_buse": u["buse"] + 5, "motif": "gyroide"}, "usage": "solide"}),
    "supports": ("Supports durs à enlever ou marques",
                 "Supports trop solides ou trop collés à la pièce.",
                 "Retire-les pièce froide, à la pince coupante, par petits morceaux. La prochaine fois : supports en arbre fins.",
                 lambda u: {"supports": "arbre_fin"}),
    "affaisse": ("Dessous ou surplombs affaissés",
                 "Des zones penchées n'avaient rien dessous.",
                 "La prochaine fois : supports en arbre, déclenchés plus tôt (40°).",
                 lambda u: {"supports": "arbre", "advanced": {"angle_support": 40}}),
    "maigre": ("Trous ou lignes maigres",
               "Pas assez de plastique (débit, filament humide ou buse en partie bouchée).",
               "Imprime la tour de débit (onglet Démarrage) et reporte la valeur ; vérifie que la bobine tourne librement.",
               lambda u: {}),
    "couleurs": ("Couleurs qui bavent les unes sur les autres",
                 "La purge entre deux couleurs ne suffisait pas.",
                 "La prochaine fois : mode multicolore Équilibré (tour d'essuyage).",
                 lambda u: {"mode": "equilibre"}),
    "gouttes": ("Gouttes ou pâtés aux changements de couleur",
                "La buse coule en attendant la couleur suivante et dépose le surplus sur la pièce.",
                "Les gouttes partent au cutter, pièce froide. La prochaine fois : mode Équilibré, la buse s'essuie sur une tour avant de revenir sur la pièce.",
                lambda u: {"mode": "equilibre"}),
    "tour": ("Tour de purge tombée ou décollée",
             "La buse revient de chaque purge en suintant : le fil fait des boucles sur la tour et la buse finit par les accrocher.",
             "Ne remets pas la tour : reprends, quelques fils tomberont à sa place. L'atelier imprime déjà la tour avec une bordure "
             "de 8 mm et lève la buse de 0,8 mm ; nettoie le plateau à cet endroit. Pour une petite pièce, le mode Économie n'a pas de tour.",
             lambda u: {}),
    "pied": ("Base évasée (pied d'éléphant)",
             "Première couche écrasée par un plateau trop chaud.",
             "Lime légèrement l'arête du bas. La prochaine fois : plateau 5 °C plus froid.",
             lambda u: {"advanced": {"temp_plateau": max(u["plateau"] - 5, 45)}}),
    "decalage": ("Couches décalées d'un coup",
                 "La tête a sauté des pas : choc, courroie ou vitesse trop haute.",
                 "Vérifie que rien ne gêne la tête, puis imprime en vitesse Équilibré ou Silencieux (onglet Imprimante).",
                 lambda u: {}),
}


def used(gcode: Path) -> dict[str, Any]:
    """How the print was made, from the G-code's own settings block (end of file) and start code."""
    out = {"buse": 210, "plateau": 60, "supports": False, "arbre": False, "couleurs": 1, "silk": False}
    if not gcode.exists():
        return out
    with gcode.open("rb") as f:
        head = f.read(200_000).decode("utf-8", "ignore")
        f.seek(max(0, gcode.stat().st_size - 400_000))
        tail = f.read().decode("utf-8", "ignore")
    if m := re.search(r"^M190 S(\d+)", head, re.M):
        out["plateau"] = int(m.group(1))
    if m := re.search(r"^; nozzle_temperature = (\d+)", tail, re.M):
        out["buse"] = int(m.group(1))
    out["supports"] = bool(re.search(r"^; enable_support = 1", tail, re.M))
    out["arbre"] = bool(re.search(r"^; support_type = tree", tail, re.M))
    if m := re.search(r"^; filament_settings_id = (.*)$", tail, re.M):
        out["silk"] = "silk" in m.group(1).lower()
    out["couleurs"] = max(1, len(set(re.findall(r"^T(\d+)\s*$", head + tail, re.M))))
    return out


def tips(entry: dict[str, Any]) -> list[str]:
    """What to do with the part now, for this print."""
    u = used(config.MODELS_DIR / entry["fichier"])
    u["couleurs"] = max(u["couleurs"], len(library.load_index().get(entry["fichier"], {}).get("couleurs") or []))
    out = [f"Attends que le plateau redescende sous 35 °C (il était à {u['plateau']} °C) : la pièce se décolle alors "
           "presque seule. Sinon, retire la plaque et plie-la doucement."]
    plan = supports_plan(config.MODELS_DIR / entry["fichier"]) if u["supports"] else None
    if plan:
        out += plan["tips"]
    elif u["supports"]:
        out.append("Supports : retire-les pièce froide, à la pince coupante, en commençant par les plus fins.")
    if u["couleurs"] > 1:
        out.append("Plusieurs couleurs : vide le bac de purge à l'arrière avant la prochaine impression.")
    if u["silk"]:
        out.append("PLA Silk : ne ponce pas, il perd sa brillance. Les petits défauts partent au cutter, les fils au pistolet à chaleur.")
    out.append("Avant d'en lancer une autre : plateau vide et propre (l'atelier le vérifie à la caméra).")
    return out


# --- where the supports are, from the G-code ----------------------------------------------------------
_MOVE = re.compile(rb"^G[123] [^\n]*?X(-?[\d.]+) Y(-?[\d.]+)[^\n]*? E(\d*\.?\d+)", re.M)   # an extruding move
CELL = 4.0           # mm: supports are mapped on a grid this coarse, which is plenty to say "left, front, low"
MIN_SHARE = 0.04     # a zone under this share of the supports is not worth a line
_plans: dict[tuple[str, int, int], dict[str, Any] | None] = {}


def _extruded(raw: bytes, kinds: dict[bytes, str]) -> dict[str, np.ndarray]:
    """Every extruding move of the given ``;TYPE:`` sections as rows (x, y, z, filament mm)."""
    rows: dict[str, list[np.ndarray]] = {k: [] for k in kinds.values()}
    for chunk in raw.split(b";LAYER_CHANGE")[1:]:
        m = re.search(rb";Z:([\d.]+)", chunk)
        if not m:
            continue
        z = float(m.group(1))
        for sec in chunk.split(b";TYPE:")[1:]:
            name, _, body = sec.partition(b"\n")
            kind = kinds.get(name.strip())
            if kind and (found := _MOVE.findall(body)):
                a = np.array(found, dtype="S").astype(float)
                rows[kind].append(np.column_stack([a[:, 0], a[:, 1], np.full(len(a), z), a[:, 2]]))
    return {k: np.vstack(v) if v else np.empty((0, 4)) for k, v in rows.items()}


def _word(f: float, words: tuple[str, str, str]) -> str:
    return words[0] if f < 1 / 3 else words[2] if f > 2 / 3 else words[1]


def supports_plan(gcode: Path) -> dict[str, Any] | None:
    """Where the supports of a printed G-code sit, as zones with a plain description each and a top view for the page.
    Seen from the front of the printer: x grows to the right, y towards the back."""
    if not gcode.exists():
        return None
    st = gcode.stat()
    key = (str(gcode), st.st_mtime_ns, st.st_size)
    if key not in _plans:
        _plans[key] = _supports_plan(gcode)
        while len(_plans) > 8:
            _plans.pop(next(iter(_plans)))
    return _plans[key]


def _supports_plan(gcode: Path) -> dict[str, Any] | None:
    pts = _extruded(gcode.read_bytes(), {b"Support": "s", b"Support interface": "i", b"Outer wall": "p"})
    sup = np.vstack([pts["s"], pts["i"]])
    if len(sup) < 20 or not len(pts["p"]):
        return None
    contact = pts["i"]
    part = pts["p"]
    x0, y0 = np.floor(np.minimum(sup[:, :2].min(0), part[:, :2].min(0)) / CELL).astype(int)
    x1, y1 = np.floor(np.maximum(sup[:, :2].max(0), part[:, :2].max(0)) / CELL).astype(int)
    grid = np.zeros((y1 - y0 + 1, x1 - x0 + 1))
    cx, cy = (np.floor(sup[:, 0] / CELL) - x0).astype(int), (np.floor(sup[:, 1] / CELL) - y0).astype(int)
    np.add.at(grid, (cy, cx), sup[:, 3])
    total = float(grid.sum())
    px0, py0 = part[:, :2].min(0)
    px1, py1 = part[:, :2].max(0)
    # the supports of a figure fill the whole footprint: seen from above they are one block. Each third of their
    # height is cut into separate columns instead, which is what one removes in one go
    edges = np.linspace(sup[:, 2].min(), sup[:, 2].max() + 1e-6, 4)
    ci_x = (np.floor(contact[:, 0] / CELL) - x0).astype(int).clip(0, grid.shape[1] - 1)
    ci_y = (np.floor(contact[:, 1] / CELL) - y0).astype(int).clip(0, grid.shape[0] - 1)
    zones = []
    for lo, hi in zip(edges[:-1], edges[1:]):
        inb = (sup[:, 2] >= lo) & (sup[:, 2] < hi)
        g = np.zeros_like(grid)
        np.add.at(g, (cy[inb], cx[inb]), sup[inb, 3])
        label, count = ndimage.label(ndimage.binary_dilation(g > 0, iterations=1), structure=np.ones((3, 3)))
        label = np.where(g > 0, label, 0)
        for n in range(1, count + 1):
            mask = label == n
            share = float(g[mask].sum()) / total
            if share < MIN_SHARE:
                continue
            sz = sup[inb & mask[cy, cx]]
            w = sz[:, 3]
            ci = contact[(contact[:, 2] >= lo) & (contact[:, 2] < hi) & mask[ci_y, ci_x]] if len(contact) else contact
            zones.append({"share": share, "x": float((sz[:, 0] * w).sum() / w.sum()), "y": float((sz[:, 1] * w).sum() / w.sum()),
                          "zlo": float(sz[:, 2].min()), "zhi": float(sz[:, 2].max()),
                          "contact": (float(ci[:, 2].min()), float(ci[:, 2].max())) if len(ci) else None})
    if not zones:
        return None
    zones.sort(key=lambda z: -z["share"])
    zones = zones[:5]
    shown = sum(z["share"] for z in zones)
    lines = []
    for i, z in enumerate(zones, 1):
        z["n"] = i
        bits = [f"Zone {i}", f"{z['share'] / shown * 100:.0f} % des supports",
                _word((z["x"] - px0) / max(px1 - px0, 1), ("à gauche", "au centre", "à droite")),
                _word((z["y"] - py0) / max(py1 - py0, 1), ("à l'avant", "au milieu", "à l'arrière"))]
        if z["zlo"] < 0.8:
            bits.append(f"du plateau jusqu'à {z['zhi']:.0f} mm de haut")
        else:
            bits.append(f"de {z['zlo']:.0f} à {z['zhi']:.0f} mm de haut")
        if z["contact"]:
            a, b = z["contact"]
            bits.append(f"touche la pièce entre {a:.0f} et {b:.0f} mm" if b - a >= 1 else f"touche la pièce vers {b:.0f} mm")
        lines.append(" · ".join(bits))
    u = used(gcode)
    how = ("Ils se retirent du haut vers le bas : coupe d'abord les branches fines près de la pièce, au ras, puis le tronc. "
           "Ne tire jamais sur une branche : tiens la pièce dans la main et coupe de l'autre."
           if u["arbre"] else
           "Glisse un cutter ou la pince sous un coin du bloc et soulève-le d'un seul morceau, sans tirer sur la pièce.")
    # the page draws them: part outline and support zones, cells of CELL mm, y up
    top = [[int((x + x0) * CELL), int((y + y0) * CELL)] for y, x in zip(*np.nonzero(_occupied(part, x0, y0, grid.shape)))]
    return {
        "tips": [f"Supports : {len(zones)} zone{'s' if len(zones) > 1 else ''} à retirer, en orange sur la vue 3D. {how}", *lines,
                 "Il reste de petits points là où les supports touchaient : passe le cutter à plat, sans appuyer."],
        "map": {"cell": CELL, "part": top, "supports": [[int((x + x0) * CELL), int((y + y0) * CELL)] for y, x in zip(*np.nonzero(grid))]},
    }


def _occupied(part: np.ndarray, x0: int, y0: int, shape: tuple[int, int]) -> np.ndarray:
    m = np.zeros(shape, bool)
    m[(np.floor(part[:, 1] / CELL) - y0).astype(int), (np.floor(part[:, 0] / CELL) - x0).astype(int)] = True
    return m


# question key: (what the user rates 0 to 5, the defect a low mark ticks)
QUESTIONS: dict[str, tuple[str, str | None]] = {
    "global": ("Dans l'ensemble", None),
    "surface": ("Surfaces lisses (dessus, côtés)", "dessus"),
    "details": ("Détails fins nets", "fils"),
    "supports": ("Supports faciles à enlever", "supports"),
    "couleurs": ("Couleurs propres", "couleurs"),
    "solidite": ("Solidité", "fragile"),
}


def questions(entry: dict[str, Any]) -> list[dict[str, str | None]]:
    """The questions to rate for this print: the ones about supports and colours only when it had some."""
    u = used(config.MODELS_DIR / entry["fichier"])
    u["couleurs"] = max(u["couleurs"], len(library.load_index().get(entry["fichier"], {}).get("couleurs") or []))
    skip = {"supports"} if not u["supports"] else set()
    skip |= {"couleurs"} if u["couleurs"] < 2 else set()
    return [{"key": k, "title": t, "issue": i} for k, (t, i) in QUESTIONS.items() if k not in skip]


def clean_notes(notes: dict[str, Any]) -> dict[str, int]:
    out: dict[str, int] = {}
    for k, v in (notes or {}).items():
        if k in QUESTIONS and isinstance(v, (int, float)) and not isinstance(v, bool):
            out[k] = max(0, min(5, int(v)))
    return out


def catalogue() -> list[dict[str, str]]:
    return [{"key": k, "title": t, "cause": c, "todo": d} for k, (t, c, d, _) in ISSUES.items()]


def corrections(entry: dict[str, Any], issues: list[str]) -> dict[str, Any]:
    """The settings to use next time for these defects, merged (later ones win on the same setting)."""
    u = used(config.MODELS_DIR / entry["fichier"])
    out: dict[str, Any] = {"advanced": {}}
    for k in issues:
        if k in ISSUES:
            fix = ISSUES[k][3](u)
            out["advanced"].update(fix.get("advanced", {}))
            out.update({x: v for x, v in fix.items() if x != "advanced"})
    return out


def review(entry: dict[str, Any], issues: list[str], note: str = "", notes: dict[str, Any] | None = None) -> dict[str, Any]:
    """Keep the review on the print and the corrections on its source model; returns both."""
    issues = [k for k in issues if k in ISSUES]
    marks = clean_notes(notes or {})
    fix = corrections(entry, issues)
    source = library.load_index().get(entry["fichier"], {}).get("source")
    if source and (issues or note or marks):
        library.annotate(source, retour={"date": int(time.time()), "issues": issues, "note": note[:300], "notes": marks,
                                         "titres": [ISSUES[k][0] for k in issues], **fix})
    return {"issues": issues, "fix": fix, "source": source, "notes": marks}
