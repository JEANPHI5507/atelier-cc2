"""Is something still on the plate? A camera check before a print starts.

The workshop keeps one photo of the empty plate (taken when the user says it is empty, light on).
Before a print it takes a new photo the same way and compares the plate area only: the lower part
of the picture, where the plate is, blurred and brightness-matched so the light's small changes and
the camera's noise do not count. A part, a purge blob or a forgotten tool changes enough of it.
"""

from __future__ import annotations

import io
import json
import time
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image, ImageFilter

from . import config

SIZE = (160, 90)                  # compared at this size: fine enough for a part, blind to sensor noise
PLATE = (0.08, 0.70, 0.92, 0.98)  # front of the plate in the CC2 camera picture (x0, y0, x1, y1 fractions): the plate
                                  # moves up and down, its far edge and the back wall must stay out
PIXEL_DIFF = 22                   # levels (0-255), on the channel that moved most: this far from the reference = changed
OCCUPIED_SHARE = 0.012            # share of changed plate pixels that means "something is there" (a 5 g stand: ~3 %)


def ref_file() -> Path:
    return config.MODELS_DIR / ".plateau_vide.jpg"


def _plate(jpeg: bytes) -> np.ndarray:
    """The plate area in colour: a green or red part can have the plate's own grey level."""
    img = Image.open(io.BytesIO(jpeg)).convert("RGB").resize(SIZE).filter(ImageFilter.GaussianBlur(1.2))
    a = np.asarray(img, dtype=float)
    h, w = a.shape[:2]
    x0, y0, x1, y1 = PLATE
    return a[int(y0 * h):int(y1 * h), int(x0 * w):int(x1 * w)]


def dark(jpeg: bytes) -> bool:
    return float(np.asarray(Image.open(io.BytesIO(jpeg)).convert("L")).mean()) < 25


def compare(ref: bytes, now: bytes) -> dict[str, Any]:
    """{"occupe": bool, "part": share of the plate that changed, "zones": [(x, y) fractions of the main changes]}."""
    a, b = _plate(ref), _plate(now)
    b = b * (a.mean() / max(b.mean(), 1.0))           # same overall brightness before comparing
    changed = np.abs(a - b).max(axis=2) > PIXEL_DIFF  # the channel that changed most
    share = float(changed.mean())
    ys, xs = np.nonzero(changed)
    h, w = changed.shape
    zones = [] if not len(xs) else [(round(float(xs.mean()) / w, 2), round(float(ys.mean()) / h, 2))]
    return {"occupe": share > OCCUPIED_SHARE, "part": round(share, 4), "zones": zones}


def save_reference(jpeg: bytes) -> dict[str, Any]:
    if dark(jpeg):
        raise ValueError("image trop sombre : allume la lumière de la chambre")
    f = ref_file()
    f.parent.mkdir(exist_ok=True)
    f.write_bytes(jpeg)
    f.with_suffix(".json").write_text(json.dumps({"date": int(time.time())}))
    return {"date": int(time.time())}


def check(jpeg: bytes) -> dict[str, Any]:
    """The verdict for a new photo: "vide", "occupe", or "inconnu" (no reference yet, or too dark)."""
    if not ref_file().exists():
        return {"etat": "inconnu", "raison": "pas encore de photo du plateau vide"}
    if dark(jpeg):
        return {"etat": "inconnu", "raison": "image trop sombre"}
    r = compare(ref_file().read_bytes(), jpeg)
    return {"etat": "occupe" if r["occupe"] else "vide", **r}
