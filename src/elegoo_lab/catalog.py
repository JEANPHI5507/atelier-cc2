"""The user's own spools: true colour and slicing settings of filaments the printer cannot read.

Spools without an Elegoo RFID tag are typed in on the printer's screen, with a colour from its
palette and a generic material. This list, kept in models/.mes_bobines.json, says what they really
are: each spool has its maker's colour and a profile, an Elegoo filament (``base``) with the maker's
limits on top (``reglages``, OrcaSlicer keys). The workshop recognises them in the CANVAS
(spools.loaded) and slices them with that profile.
"""

from __future__ import annotations

import json
from typing import Any

from . import config


def _file():
    return config.MODELS_DIR / ".mes_bobines.json"   # looked up each time: tests swap the library


def load() -> dict[str, Any]:
    try:
        data = json.loads(_file().read_text())
    except (OSError, ValueError):
        data = {}
    return {"profils": data.get("profils") or {}, "bobines": data.get("bobines") or []}


def profiles() -> dict[str, dict[str, Any]]:
    """Profile name -> {"base": Elegoo filament, "reglages": {orca key: value}, "note": ...}."""
    return {k: v for k, v in load()["profils"].items() if isinstance(v, dict) and v.get("base")}


def spools() -> list[dict[str, Any]]:
    """Spools whose profile exists: {"nom", "couleur", "matiere", "profil"}."""
    known = profiles()
    return [b for b in load()["bobines"] if isinstance(b, dict) and b.get("profil") in known and b.get("couleur")]
