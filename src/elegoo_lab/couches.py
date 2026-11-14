"""Variable layer height: thin layers where the surface slopes gently (that is where the stair steps show),
the usual height on walls and flat faces.

Written as OrcaSlicer height ranges (``Metadata/layer_config_ranges.xml``, one range per band of equal
height): its command line ignores the ``layer_heights_profile`` a 3MF can carry, but honours ranges
(checked on 2.4.2: a sphere went from 100 to 161 layers).
"""

from __future__ import annotations

import zipfile
from pathlib import Path

import numpy as np

from . import threemf

MIN_MM, MAX_MM = 0.08, 0.28    # the CC2 0.4 nozzle profile's min_layer_height / max_layer_height
BAND_MM = 0.4                  # heights are decided per band of this thickness
MIN_SHARE = 0.05               # share of a band's surface that must want thinner layers for the band to get them
# level: (step height left on a slope, as a share of the chosen layer height; thickest layer, None = the chosen one)
LEVELS = {"pentes": (0.5, None), "rapide": (0.5, MAX_MM)}


def bands(v: np.ndarray, f: np.ndarray, layer_mm: float, level: str) -> list[tuple[float, float, float]]:
    """(from z, to z, layer height) for a part resting on z = 0, merged where the height does not change."""
    share, top = LEVELS[level]
    hi, cusp = top or layer_mm, share * layer_mm
    tri = v[f]
    n = np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0])
    norm = np.linalg.norm(n, axis=1)
    area, nz = norm / 2, np.abs(n[:, 2]) / (norm + 1e-12)
    zlo, zhi = tri[:, :, 2].min(axis=1), tri[:, :, 2].max(axis=1)
    height = float(zhi.max()) if len(f) else 0.0
    count = int(np.ceil(height / BAND_MM)) or 1
    want = np.full(count, hi)
    i0 = np.clip((zlo / BAND_MM).astype(int), 0, count - 1)
    span = np.clip((zhi / BAND_MM).astype(int), 0, count - 1) - i0 + 1
    band = np.repeat(i0, span) + (np.arange(span.sum()) - np.repeat(np.cumsum(span) - span, span))
    face = np.repeat(np.arange(len(f)), span)
    share_area = (area / span)[face]
    total = np.bincount(band, share_area, minlength=count)
    # walls (no steps) and flat faces (printed solid anyway) leave the height alone; a band thins only when
    # a real share of its surface slopes gently (a knitted or bumpy texture would thin everything otherwise)
    sloped = (nz[face] > 0.05) & (nz[face] < 0.995)
    if sloped.any():
        steps = np.arange(MIN_MM, hi + 1e-9, 0.02)
        h = np.clip(cusp / nz[face][sloped], MIN_MM, hi)
        level = np.searchsorted(steps, h - 1e-9)
        hist = np.zeros((count, len(steps)))
        np.add.at(hist, (band[sloped], level), share_area[sloped])
        enough = np.cumsum(hist, axis=1) >= MIN_SHARE * total[:, None]
        first = np.where(enough.any(axis=1), enough.argmax(axis=1), len(steps) - 1)
        want = np.minimum(want, steps[first])
    for i in range(1, count):            # grow back gently after a thin stretch, both ways
        want[i] = min(want[i], want[i - 1] * 1.5)
    for i in range(count - 2, -1, -1):
        want[i] = min(want[i], want[i + 1] * 1.5)
    want = np.round(want / 0.02) * 0.02  # fewer ranges, same look
    out: list[tuple[float, float, float]] = []
    for i, h in enumerate(want):
        z0, z1 = i * BAND_MM, min((i + 1) * BAND_MM, height)
        if out and abs(out[-1][2] - h) < 1e-9:
            out[-1] = (out[-1][0], z1, h)
        else:
            out.append((z0, z1, float(h)))
    return out


def apply(model: Path, layer_mm: float, level: str) -> int:
    """Add the height ranges of every object of ``model`` (a 3MF we wrote); returns roughly how many layers it
    adds (negative when thick layers on the walls save more than the slopes cost), for the message."""
    if level not in LEVELS:
        raise ValueError(f"hauteur de couche variable : « {level} » inconnu ({', '.join(LEVELS)})")
    objects, extra = [], 0.0
    for k, o in enumerate(threemf.read(model).objects, 1):     # object ids in this file follow the build order
        if not o.parts:
            continue
        v = np.vstack([p.vertices for p in o.parts])
        f = np.vstack([p.faces + off for p, off in zip(o.parts, np.cumsum([0] + [len(p.vertices) for p in o.parts]))])
        v = v - [0, 0, v[:, 2].min()]
        rng = bands(v, f, layer_mm, level)
        extra += sum((z1 - z0) / h - (z1 - z0) / layer_mm for z0, z1, h in rng)
        objects.append(f' <object id="{k}">\n' + "".join(
            f'  <range min_z="{z0:.3f}" max_z="{z1:.3f}">\n   <option opt_key="layer_height">{h:.2f}</option>\n  </range>\n'
            for z0, z1, h in rng) + " </object>\n")
    with zipfile.ZipFile(model, "a", zipfile.ZIP_DEFLATED, compresslevel=1) as z:
        z.writestr("Metadata/layer_config_ranges.xml", '<?xml version="1.0" encoding="utf-8"?>\n<objects>\n'
                   + "".join(objects) + "</objects>\n")
    return round(extra)
