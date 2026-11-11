"""After a print: what to do with the part now, and what to change next time.

Two parts. The tips depend on how the print was made (supports, several colours, Silk filament, its
plate temperature), read from the G-code that was printed. Then the user ticks what went wrong; each
defect comes with its cause and a correction in the workshop's own settings, computed from the values
really used (a Silk PLA printed at 230 °C gets 220 °C against stringing, not the profile's 210 - 10).
The corrections are kept on the source model and offered the next time it is prepared.
"""

from __future__ import annotations

import re
import time
from pathlib import Path
from typing import Any, Callable

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
    out = {"buse": 210, "plateau": 60, "supports": False, "couleurs": 1, "silk": False}
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
    if u["supports"]:
        out.append("Supports : retire-les pièce froide, à la pince coupante, en commençant par les plus fins.")
    if u["couleurs"] > 1:
        out.append("Plusieurs couleurs : vide le bac de purge à l'arrière avant la prochaine impression.")
    if u["silk"]:
        out.append("PLA Silk : ne ponce pas, il perd sa brillance. Les petits défauts partent au cutter, les fils au pistolet à chaleur.")
    out.append("Avant d'en lancer une autre : plateau vide et propre (l'atelier le vérifie à la caméra).")
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


def review(entry: dict[str, Any], issues: list[str], note: str = "") -> dict[str, Any]:
    """Keep the review on the print and the corrections on its source model; returns both."""
    issues = [k for k in issues if k in ISSUES]
    fix = corrections(entry, issues)
    source = library.load_index().get(entry["fichier"], {}).get("source")
    if source and (issues or note):
        library.annotate(source, retour={"date": int(time.time()), "issues": issues, "note": note[:300],
                                         "titres": [ISSUES[k][0] for k in issues], **fix})
    return {"issues": issues, "fix": fix, "source": source}
