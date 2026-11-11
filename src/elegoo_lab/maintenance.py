"""Maintenance log: reminders from the real printing hours (gallery) and the calendar.

Intervals follow what CC2 owners report (printer-hub.com, "30 Elegoo Centauri Carbon 2 issues"):
rods and belts every 250-300 h or three months (dry rods fool the sensorless homing), the exhaust
filter every three months, the wiper box and purge chute kept clean (waste piling up can knock off the toolhead's front cover: error 707). The PEI wash is the
usual practice when adhesion drops; the cutter check interval is the workshop's own choice. Kept in models/.entretien.json.
"""

from __future__ import annotations

import json
import time
from typing import Any

from . import config, gallery

DAY = 86400
TASKS: dict[str, dict[str, Any]] = {
    "plateau": {"titre": "Laver le plateau PEI", "heures": 30, "jours": None,
                "geste": "Eau chaude et liquide vaisselle, rinçage, séchage sans toucher la surface. Les traces de doigts "
                         "suffisent à faire décoller une première couche."},
    "essuyeur": {"titre": "Nettoyer l'essuyeur et la goulotte de purge", "heures": 50, "jours": None,
                 "geste": "Retire les déchets de la boîte de l'essuyeur, vérifie que la lame revient seule et vide le bac. "
                          "Sinon les déchets s'accumulent sous la tête et peuvent décrocher son capot avant (erreur 707)."},
    "tiges": {"titre": "Nettoyer et graisser les tiges X/Y, vérifier les courroies", "heures": 250, "jours": 90,
              "geste": "Chiffon sec puis une fine couche de graisse ; courroies tendues sans excès. Des tiges sèches ou "
                       "sales trompent la mise en origine sans capteur."},
    "filtre": {"titre": "Changer le filtre d'extraction", "heures": None, "jours": 90,
               "geste": "Remplace la cartouche puis valide « Remplacé » sur l'écran de l'imprimante."},
    "coupeur": {"titre": "Vérifier le coupe-filament et l'aimantation du capot", "heures": 150, "jours": None,
                "geste": "La butée près de la porte avant doit être serrée et le levier revenir seul (erreurs 1231/1232) ; "
                         "les 3 aimants du capot de la tête doivent tenir."},
}


def _file():
    return config.MODELS_DIR / ".entretien.json"


def _load() -> dict[str, Any]:
    try:
        data = json.loads(_file().read_text())
    except (OSError, ValueError):
        data = {}
    now = int(time.time())
    for k in TASKS:                       # a new log starts from today: the printer is new or just serviced
        data.setdefault(k, {"fait": now, "signale": False})
    return data


def _save(data: dict[str, Any]) -> None:
    _file().parent.mkdir(exist_ok=True)
    _file().write_text(json.dumps(data, indent=1))


def _hours_since(ts: int) -> float:
    return sum(e.get("duree_s", 0) for e in gallery.entries() if e.get("debut", 0) >= ts) / 3600


def status() -> list[dict[str, Any]]:
    data = _load()
    _save(data)
    out = []
    for k, t in TASKS.items():
        done = data[k]["fait"]
        h, d = _hours_since(done), (time.time() - done) / DAY
        parts = [x for x in ((h / t["heures"]) if t["heures"] else None, (d / t["jours"]) if t["jours"] else None) if x is not None]
        pct = max(parts) if parts else 0.0
        out.append({"id": k, "titre": t["titre"], "geste": t["geste"], "heures": round(h, 1), "jours": int(d),
                    "intervalle": " ou ".join(x for x in (f"{t['heures']} h d'impression" if t["heures"] else "",
                                                          f"{t['jours']} jours" if t["jours"] else "") if x),
                    "avancement": round(min(pct, 1.5), 2), "a_faire": pct >= 1.0, "fait": done})
    return sorted(out, key=lambda x: -x["avancement"])


def done(task: str) -> list[dict[str, Any]]:
    if task not in TASKS:
        raise ValueError("tâche inconnue")
    data = _load()
    data[task] = {"fait": int(time.time()), "signale": False}
    _save(data)
    return status()


def newly_due() -> list[dict[str, Any]]:
    """Tasks that just became due and were not announced yet (for the alerts)."""
    data = _load()
    out = [t for t in status() if t["a_faire"] and not data[t["id"]].get("signale")]
    for t in out:
        data[t["id"]]["signale"] = True
    _save(data)
    return out
