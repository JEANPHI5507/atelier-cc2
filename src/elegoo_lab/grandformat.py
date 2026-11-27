"""Large format: give a model and the final height wanted; the workshop sizes it, cuts it, picks the
best position of every piece and slices them. The code proposes and checks the geometry; nothing is
sliced before the plan (pieces, cut planes, alerts) has been seen.

Zones where no cut may pass are boxes in the model's own frame (X, Y from the centre of its
footprint, Z from its base, mm) — see ``cut.Zone``. Specs accepted from the assistant or the page:
``{"axe": "Z", "de": 150, "a": 190}`` (a band across the whole model) or
``{"boite": [[x0, y0, z0], [x1, y1, z1]]}`` or ``{"point": [x, y, z], "rayon": 15}`` (a click).
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any, cast

import numpy as np
import trimesh

from . import colors, config, cut, mesh, orient, printprep, stock

if TYPE_CHECKING:
    from pathlib import Path

MIN_HEIGHT_MM = 20.0
MAX_HEIGHT_MM = 1500.0
CLICK_RADIUS_MM = 15.0
_cache: dict[tuple, dict[str, Any]] = {}


def parse_zones(specs: list[dict[str, Any]] | None) -> list[cut.Zone]:
    """Forbidden zones from their JSON form; ValueError tells what is wrong."""
    out: list[cut.Zone] = []
    inf = cut.INF
    for spec in specs or []:
        if not isinstance(spec, dict):
            raise ValueError("une zone interdite est un objet {axe, de, a}, {boite} ou {point}")
        try:
            if "axe" in spec:
                axis = "XYZ".index(str(spec["axe"]).upper())
                lo, hi = [-inf] * 3, [inf] * 3
                lo[axis], hi[axis] = sorted((float(spec["de"]), float(spec["a"])))
            elif "boite" in spec:
                a, b = (np.asarray(p, float) for p in spec["boite"])
                if a.shape != (3,) or b.shape != (3,):
                    raise ValueError
                lo, hi = np.minimum(a, b).tolist(), np.maximum(a, b).tolist()
            elif "point" in spec:
                p = np.asarray(spec["point"], float)
                if p.shape != (3,):
                    raise ValueError
                r = float(spec.get("rayon", CLICK_RADIUS_MM))
                lo, hi = (p - r).tolist(), (p + r).tolist()
            else:
                raise ValueError
        except (ValueError, KeyError, TypeError) as err:
            raise ValueError(
                f"zone interdite illisible : {spec} (attendu : {{axe: X|Y|Z, de, a}}, "
                "{boite: [[x,y,z],[x,y,z]]} ou {point: [x,y,z], rayon})"
            ) from err
        out.append(((lo[0], lo[1], lo[2]), (hi[0], hi[1], hi[2])))
    return out


def _check_height(hauteur_mm: float) -> float:
    if not MIN_HEIGHT_MM <= hauteur_mm <= MAX_HEIGHT_MM:
        raise ValueError(
            f"hauteur finale entre {MIN_HEIGHT_MM:.0f} et {MAX_HEIGHT_MM:.0f} mm (reçu {hauteur_mm:g})"
        )
    return float(hauteur_mm)


def _solid(src: Path, hauteur_mm: float) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    info = colors.analyze(src)
    slots = {c["index"]: c["slot"] for c in info["colours"]}
    v, f, face_slots, _ = colors.solid(src, slots, height_mm=hauteur_mm)
    return v, f, face_slots


def plan(
    src: Path,
    hauteur_mm: float,
    interdites: list[dict[str, Any]] | None = None,
    biais: bool = True,
) -> dict[str, Any]:
    """Pieces, cut planes, positions and alerts for this height. Slices nothing. ``ok`` is False while
    an alert blocks (a piece that cannot fit the plate, a cut forced through a forbidden zone)."""
    hauteur_mm = _check_height(hauteur_mm)
    zones = parse_zones(interdites)
    st = src.stat()
    key = (str(src), st.st_mtime_ns, st.st_size, hauteur_mm, tuple(map(repr, zones)), biais)
    if key in _cache:
        return _cache[key]
    v, f, face_slots = _solid(src, hauteur_mm)
    res = cut.cut(v, f, face_slots, name=src.stem, forbidden=zones, oblique=biais)
    limit = mesh.BED_MM - cut.MARGIN_MM
    alerts = list(res.alerts)
    pieces = []
    for p in res.pieces:
        posed = orient.best_pose(p.vertices, p.faces, limit)
        m = trimesh.Trimesh(p.vertices, p.faces, process=False)
        pieces.append(
            {
                "nom": p.name,
                "taille_mm": np.ptp(p.vertices, axis=0).round(1).tolist(),
                "pose": posed["label"] if posed else None,
                "taille_posee_mm": [round(x, 1) for x in posed["size_mm"]] if posed else None,
                "volume_cm3": round(abs(float(m.volume)) / 1000, 1),
            }
        )
        if posed is None and not any(a["type"] == "trop_grande" for a in alerts):
            alerts.append(
                cut.alert(
                    "trop_grande",
                    f"{p.name} ne tient dans aucune des six poses.",
                    blocking=True,
                )
            )
    origin = np.array(
        [(v[:, 0].min() + v[:, 0].max()) / 2, (v[:, 1].min() + v[:, 1].max()) / 2, v[:, 2].min()]
    )
    out = {
        "hauteur_mm": hauteur_mm,
        "taille_mm": np.ptp(v, axis=0).round(1).tolist(),
        "plans": [_plane_json(c, origin) for c in res.cuts],
        "pieces": pieces,
        "chevilles": res.pin_count,
        "alertes": alerts,
        "ok": not any(a["bloquante"] for a in alerts),
    }
    _cache[key] = out
    while len(_cache) > 16:
        _cache.pop(next(iter(_cache)))
    return out


def _plane_json(c: cut.Plane, origin: np.ndarray) -> dict[str, Any]:
    out: dict[str, Any] = {"axe": "XYZ"[c.axis], "mm": round(float(c.pos - origin[c.axis]), 1)}
    if c.angle:
        out.update(angle=c.angle, vers="XYZ"[c.lean])
    return out


def preview(
    src: Path,
    hauteur_mm: float,
    interdites: list[dict[str, Any]] | None = None,
    biais: bool = True,
) -> tuple[dict[str, Any], bytes]:
    """The plan and a GLB: one colour per piece (slightly apart) and a translucent quad on each cut plane."""
    hauteur_mm = _check_height(hauteur_mm)
    _, view = printprep.cut_preview(
        src,
        height_mm=hauteur_mm,
        forbidden=parse_zones(interdites),
        explode=0.08,
        show_planes=True,
        distinct=True,
        oblique=biais,
    )
    return plan(src, hauteur_mm, interdites, biais), cast("bytes", view.export(file_type="glb"))


_TIME = re.compile(r"(?:(\d+)d)?\s*(?:(\d+)h)?\s*(?:(\d+)m)?\s*(?:(\d+)s)?")


def seconds(text: str | None) -> int:
    """OrcaSlicer's « 1d 2h 3m 4s » as seconds (0 when unreadable)."""
    m = _TIME.fullmatch((text or "").strip())
    if not m:
        return 0
    d, h, mi, s = (int(x or 0) for x in m.groups())
    return ((d * 24 + h) * 60 + mi) * 60 + s


def _duration(total: int) -> str:
    h, rest = divmod(total, 3600)
    return f"{h} h {rest // 60:02d} min"


def executer(
    src: Path,
    hauteur_mm: float,
    interdites: list[dict[str, Any]] | None = None,
    biais: bool = True,
    **options: Any,
) -> dict[str, Any]:
    """Slice every piece (and the plate of dowels). Refuses while the plan has a blocking alert.
    ``options`` go to ``printprep.prepare_and_slice`` (usage, supports, quality, infill, …)."""
    p = plan(src, hauteur_mm, interdites, biais)
    if not p["ok"]:
        raise ValueError(
            "plan à corriger avant de trancher : "
            + " ; ".join(a["message"] for a in p["alertes"] if a["bloquante"])
        )
    res = printprep.prepare_and_slice(
        src,
        out_dir=config.MODELS_DIR,
        height_mm=p["hauteur_mm"],
        split=True,
        forbidden=parse_zones(interdites),
        auto_pose=True,
        oblique=biais,
        screen_thumbnail=False,
        **options,
    )
    parts = res.get("pieces") or [res]
    plate = res.get("pins")
    runs = [*parts, *([plate] if plate else [])]
    total_s = sum(seconds(r.get("time")) for r in runs)
    metres = float(res.get("total_m", 0))
    grams = stock.grams(metres, "PLA")
    tray = stock.load()["trays"].get("1", {})
    price = float(tray.get("prix_kg", stock.PRICE_KG))
    return {
        "plan": p,
        "gcode": res["gcode"],
        "pieces": [
            {"nom": r.get("name", src.stem), "duree": r.get("time"), "gcode": r["gcode"]}
            for r in parts
        ],
        "bilan": {
            "pieces": len(parts),
            "duree": _duration(total_s),
            "duree_s": total_s,
            "filament_g": round(grams, 1),
            "cout_eur": round(grams / 1000 * price, 2),
            "chevilles": res.get("pin_count", 0),
        },
        "alertes": [*p["alertes"], *res.get("alerts", [])],
        "avertissements": res.get("warnings", []),
    }
