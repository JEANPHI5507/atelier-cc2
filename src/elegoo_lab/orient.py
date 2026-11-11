"""How to lay the part on the plate: six positions, each with a thumbnail and a recommendation.

Same rotations as the slicing (``colors.rotation``: X, then Y, then Z, in degrees). The scores are
the advisor's layer view, computed once and turned: first layer's area (footing), what each layer
adds beyond the one below past 50° (support needed), and the height (more layers = longer, and more
colour changes in multicolour). Open meshes fall back to face statistics.
"""

from __future__ import annotations

import base64
from pathlib import Path
from typing import Any

import manifold3d as mf
import numpy as np

from . import advisor, colors, mesh, thumbnail

POSITIONS: list[tuple[str, str, tuple[int, int, int]]] = [
    ("debout", "Telle quelle", (0, 0, 0)),
    ("avant", "Couchée vers l'avant", (90, 0, 0)),
    ("arriere", "Couchée vers l'arrière", (-90, 0, 0)),
    ("gauche", "Sur le côté gauche", (0, -90, 0)),
    ("droite", "Sur le côté droit", (0, 90, 0)),
    ("envers", "À l'envers", (180, 0, 0)),
]
OVERHANG_COS = np.cos(np.radians(90 - 50))
_cache: dict[tuple, list[dict[str, Any]]] = {}


def _stats(v: np.ndarray, f: np.ndarray) -> dict[str, float]:
    tri = v[f]
    n = np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0])
    area = np.linalg.norm(n, axis=1) / 2
    nz = n[:, 2] / (2 * area + 1e-12)
    cz = tri[:, :, 2].mean(axis=1)
    lo = v[:, 2].min()
    on_plate = (cz - lo < 0.3) & (nz < -0.95)
    hanging = (nz < -OVERHANG_COS) & (cz - lo > 0.5)
    return {"contact": float(area[on_plate].sum()), "surplomb": float(area[hanging].sum()),
            "hauteur": float(np.ptp(v[:, 2]))}


def _solid(v: np.ndarray, f: np.ndarray) -> mf.Manifold | None:
    """The part as a closed volume (like the advisor), or None for an open mesh."""
    secs = advisor._sections(v, f)          # validates and repairs once
    if secs is None:
        return None
    import trimesh
    m = trimesh.Trimesh(v, f)
    m.merge_vertices()
    solid = mf.Manifold(mf.Mesh(vert_properties=np.asarray(m.vertices, np.float32), tri_verts=np.asarray(m.faces, np.uint32)))
    return solid if solid.status() == mf.Error.NoError and not solid.is_empty() else None


def _layer_stats(solid: mf.Manifold, rot: np.ndarray | None, scale: float) -> dict[str, float]:
    """Contact = first layer's area; overhang = what each layer adds beyond the one below (slicer's view)."""
    m3 = (rot if rot is not None else np.eye(3)) * scale
    turned = solid.transform(np.hstack([m3, np.zeros((3, 1))]).tolist())
    lo, hi = turned.bounding_box()[2], turned.bounding_box()[5]
    turned = turned.translate([0, 0, -lo])
    h = hi - lo
    step = max(1.0, h / 150)
    zs = np.arange(min(0.2, h / 2), h, step)
    secs = [turned.slice(float(z)) for z in zs]
    reach = step * np.tan(np.radians(50))
    over = sum(max(0.0, (cs - below.offset(reach, mf.JoinType.Round)).area()) for below, cs in zip(secs, secs[1:]))
    return {"contact": float(secs[0].area()) if secs else 0.0, "surplomb": float(over), "hauteur": float(h)}


def orientations(path: Path, height_mm: float | None = None, rz: int = 0) -> list[dict[str, Any]]:
    """The six positions, best first marked ``recommandee`` (keeping the user's turn on the plate, ``rz``)."""
    st = path.stat()
    key = (str(path), st.st_mtime_ns, st.st_size, height_mm, rz)
    if key in _cache:
        return _cache[key]
    if not height_mm and mesh.info(path).get("unitless"):
        height_mm = mesh.DEFAULT_AI_HEIGHT_MM
    v0, f, slots, slot_hex = colors.solid(path, {})          # loaded once, turned six times
    rgb = np.array([colors._rgb(slot_hex[int(s) - 1]) for s in slots]) if slot_hex else np.full((len(f), 3), 190.0)
    solid = _solid(v0, f)
    out = []
    # one object, laid six ways: the same scale for every position (height_mm is its height as it comes), so a
    # long part lying flat stays its real size instead of being blown up to the same height (2026-11-11: a gun
    # 60 mm tall as modelled was 620 mm long lying down, so only "standing on its tip" seemed to fit)
    scale = (height_mm / (float(np.ptp(v0[:, 2])) or 1)) if height_mm else 1.0
    for key_, label, (rx, ry, _) in POSITIONS:
        rot = colors.rotation((rx, ry, rz))
        v = (v0 @ rot.T if rot is not None else v0.copy()) * scale
        v = v - v.min(axis=0)
        s = _layer_stats(solid, rot, scale) if solid is not None else _stats(v, f)
        png = thumbnail.render(v, f, rgb, size=112)
        out.append({"id": key_, "label": label, "rotate": [rx, ry, rz], **{k: round(x, 1) for k, x in s.items()},
                    "size_mm": [round(float(x), 1) for x in np.ptp(v, axis=0)],
                    "image": "data:image/png;base64," + base64.b64encode(png).decode()})
    # fewest overhangs first; a part standing on a few mm² falls over or comes loose; lower = shorter print
    for o in out:
        # a part standing on a few mm² for hours comes loose and the print is lost, while overhangs get tree supports:
        # standing on its tip (1 mm², 2026-11-11) must lose to lying flat even with 1300 mm² of overhang
        # and a tall thin part sways at the top (the advisor's "pièce haute et fine": over 4 times its base)
        sx, sy, sz = o["size_mm"]
        o["score"] = (o["surplomb"] + (2000 * (1 - o["contact"] / 30) if o["contact"] < 30 else 0) + 200 / (1 + o["contact"] / 50)
                      + 0.5 * o["hauteur"] + 300 * max(0.0, sz / max(min(sx, sy), 1.0) - 4))
        o["tient"] = max(o["size_mm"]) <= mesh.BED_MM
    best = min((o for o in out if o["tient"]), key=lambda o: o["score"], default=out[0])
    for o in out:
        o["recommandee"] = o is best
    _cache[key] = out
    while len(_cache) > 32:
        _cache.pop(next(iter(_cache)))
    return out
