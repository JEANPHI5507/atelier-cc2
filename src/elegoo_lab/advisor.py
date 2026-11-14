"""Print advisor: looks at the model as it will be printed and warns before slicing.

Checks what most often ruins a print on a 0.4 mm nozzle: walls too thin to be printed, too little
contact with the plate (the part comes loose), overhangs without supports, parts floating above the
plate, tall and slender shapes that wobble, open meshes. Each warning says why, and most carry a fix
the workshop can apply in one click (the same fields as the "Taille et réglages" step).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import manifold3d as mf
import numpy as np
import trimesh

from . import colors, mesh

NOZZLE = 0.4
MIN_WALL = 2 * NOZZLE          # thinner than two lines: the slicer drops or weakens it
OVERHANG_DEG = 50              # steeper than this from vertical needs support (PLA, CC2 cooling)
BED_TOL = 0.25                 # mm above the lowest point still counted as touching the plate
SLICE_STEP = 1.0               # mm between analysed sections (upper bound 300 sections)


def manifold(v: np.ndarray, f: np.ndarray) -> mf.Manifold | None:
    """The mesh as a closed volume (vertices merged when it needs it), or None for an open mesh."""
    try:
        solid = mf.Manifold(mf.Mesh(vert_properties=np.asarray(v, np.float32), tri_verts=np.asarray(f, np.uint32)))
        if solid.status() != mf.Error.NoError or solid.is_empty():
            m = trimesh.Trimesh(v, f)
            m.merge_vertices()
            solid = mf.Manifold(mf.Mesh(vert_properties=np.asarray(m.vertices, np.float32), tri_verts=np.asarray(m.faces, np.uint32)))
        if solid.status() != mf.Error.NoError or solid.is_empty():
            return None
    except Exception:
        return None
    return solid


def _sections(v: np.ndarray, f: np.ndarray) -> list[tuple[float, mf.CrossSection]] | None:
    solid = manifold(v, f)
    if solid is None:
        return None
    h = float(v[:, 2].max())
    step = max(SLICE_STEP, h / 300)
    return [(float(z), solid.slice(float(z))) for z in np.arange(min(0.3, h / 2), h, step)]


def analyze(path: Path, *, height_mm: float | None = None, rotate: tuple[float, ...] | None = None,
            supports: bool = False, brim: bool = False, split: bool = False) -> dict[str, Any]:
    """Warnings for this model at this size and orientation, worst first."""
    if not height_mm and mesh.info(path).get("unitless"):
        height_mm = mesh.DEFAULT_AI_HEIGHT_MM
    v, f, _, _ = colors.solid(path, {}, height_mm=height_mm, rotate=rotate)
    tm = trimesh.Trimesh(v, f, process=False)
    size = np.ptp(v, axis=0)
    out: list[dict[str, Any]] = []

    def add(level: str, key: str, title: str, detail: str, fix: dict[str, Any] | None = None, label: str = "",
            also: list[dict[str, str]] | None = None) -> None:
        out.append({"level": level, "key": key, "title": title, "detail": detail, "fix": fix, "fix_label": label,
                    "also": also or []})

    normals, areas = tm.face_normals, tm.area_faces
    centres_z = tm.triangles_center[:, 2]
    down = normals[:, 2]

    # --- contact with the plate -------------------------------------------------
    on_bed = (centres_z < BED_TOL) & (down < -0.95)
    contact = float(areas[on_bed].sum())
    footprint = float(size[0] * size[1]) or 1.0
    tall = size[2] / max(min(size[0], size[1]), 1.0)
    if brim:
        pass  # a brim is the answer to both plate warnings below
    elif contact < 30 or (contact < 0.08 * footprint and size[2] > 15):
        add("bad" if contact < 30 else "warn", "adherence", "Peu de contact avec le plateau",
            f"Seulement {contact:.0f} mm² posés à plat : la pièce risque de se décoller en cours d'impression.",
            {"advanced": {"bordure": "exterieure", "largeur_bordure": 6}, "orient": True},
            "Ajouter une bordure et chercher la meilleure face")
    elif tall > 4 and size[2] > 40:
        add("warn", "elance", "Pièce haute et fine",
            f"{size[2]:.0f} mm de haut pour {min(size[0], size[1]):.0f} mm au sol : elle peut osciller en haut.",
            {"advanced": {"bordure": "exterieure", "largeur_bordure": 8}}, "Ajouter une bordure large")

    # --- overhangs: what sticks out beyond the layer below (as the slicer sees it) ----------------
    secs = _sections(v, f)
    if secs is not None:
        reach = (secs[1][0] - secs[0][0] if len(secs) > 1 else SLICE_STEP) * np.tan(np.radians(OVERHANG_DEG))
        layers = [max(0.0, (cs - below.offset(reach, mf.JoinType.Round)).area())
                  for (_, below), (_, cs) in zip(secs, secs[1:])]
        over = float(sum(layers))
        big = over > 60 or max(layers, default=0) > 20      # a lot in all, or one flat ceiling
    else:  # open mesh: fall back to the faces' orientation
        steep = (down < -np.cos(np.radians(90 - OVERHANG_DEG))) & (centres_z > BED_TOL + 0.2)
        over = float(areas[steep].sum())
        big = over > max(25.0, 0.01 * float(areas.sum()))
    if not supports and big:
        add("bad" if over > 400 else "warn", "surplombs", "Surplombs sans support",
            f"Environ {over:.0f} mm² pendent dans le vide (plus de {OVERHANG_DEG}°) : ils s'affaisseront sans support.",
            {"supports": "arbre"}, "Activer les supports en arbre")

    # --- floating parts: a separate body with nothing under it ---------------------------------
    bodies = tm.split(only_watertight=False) if len(f) < 400_000 else []
    boxes = [b.bounds for b in bodies]
    floating = 0
    for i, (lo, hi) in enumerate(boxes):
        if lo[2] <= 1.0 or bodies[i].area < 5:
            continue
        rests = any(j != i and l2[0] <= hi[0] and h2[0] >= lo[0] and l2[1] <= hi[1] and h2[1] >= lo[1]
                    and l2[2] < lo[2] + 0.3 and h2[2] >= lo[2] - 0.5 for j, (l2, h2) in enumerate(boxes))
        floating += not rests
    if floating and not supports:
        add("bad", "flottant", "Morceau en l'air",
            f"{floating} partie(s) séparée(s) ne reposent sur rien : elles tomberaient.",
            {"supports": "arbre"}, "Activer les supports")

    # --- thin walls -------------------------------------------------------------
    if secs is None:
        add("warn", "ouvert", "Maillage ouvert",
            "Le modèle n'est pas un volume fermé (trous, faces inversées). Le slicer le répare souvent, "
            "mais mieux vaut le réparer avant : une copie fermée est créée (reconstruite si le maillage est trop "
            "abîmé), l'original est gardé.",
            {"repair": True}, "Réparer automatiquement", [{"label": "Voir les défauts", "action": "defects"}])
    else:
        r = MIN_WALL / 2
        lost = whole = 0.0
        worst_z = None
        worst = 0.0
        for z, cs in secs:
            a = cs.area()
            if a <= 0:
                continue
            kept = cs.offset(-r, mf.JoinType.Round).offset(r, mf.JoinType.Round).area()
            gone = max(0.0, a - kept)
            lost, whole = lost + gone, whole + a
            if gone / a > worst and a > 2:
                worst, worst_z = gone / a, z
        share = lost / whole if whole else 0.0
        if share > 0.02:
            scale = min(3.0, 1 + share * 4)
            target = round(float(size[2]) * scale)
            add("bad" if share > 0.08 else "warn", "fin", "Parois trop fines",
                f"{share * 100:.0f} % du modèle fait moins de {MIN_WALL:.1f} mm d'épaisseur"
                + (f" (surtout vers {worst_z:.0f} mm de haut)" if worst_z is not None else "")
                + " : ces détails seront fragiles ou absents.",
                {"height_mm": target} if target <= mesh.BED_MM else None,
                f"Agrandir à {target} mm de haut" if target <= mesh.BED_MM else "")

    # --- bed size ---------------------------------------------------------------
    if size.max() > mesh.BED_MM and not split:
        add("warn", "taille", "Plus grand que le plateau",
            f"{size.max():.0f} mm pour {mesh.BED_MM} mm de plateau.", {"split": True}, "Découper en pièces")

    order = {"bad": 0, "warn": 1, "ok": 2}
    out.sort(key=lambda w: order[w["level"]])
    return {"size": [round(float(x), 1) for x in size], "contact_mm2": round(contact), "warnings": out,
            "notes": _notes(path), "verdict": "ok" if not out else out[0]["level"]}


def _notes(path: Path) -> list[dict[str, Any]]:
    """Good news worth showing: this file is a repaired copy, and what the repair did."""
    from . import repair
    rep = repair.report_for(path)
    if not rep:
        return []
    plural = lambda n, one, many: f"{n} {one if n == 1 else many}"   # noqa: E731
    if rep.get("rebuilt"):
        found = [plural(rep[k], one, many) for k, one, many in (("holes_closed", "trou", "trous"),
                 ("shared_edges", "arête partagée à tort", "arêtes partagées à tort")) if rep.get(k)]
        items = ["Surface reconstruite à partir du volume : l'original était trop abîmé pour une simple réparation"
                 + (f" ({', '.join(found)})" if found else "")]
        if rep.get("sheets_removed"):
            items.append("Feuilles sans épaisseur retirées (plaque ou voile laissés par l'IA autour du modèle)")
        if rep.get("pieces_dropped"):
            items.append(plural(rep["pieces_dropped"], "éclat isolé retiré", "éclats isolés retirés"))
        items.append("Détails plus fins qu'environ 1 % de la taille lissés ou retirés : vérifie l'aperçu")
        items.append("Volume fermé et vérifié, prêt à trancher")
        if rep.get("coloured"):
            items.append("Couleurs reportées depuis l'original")
        return [{"title": "Maillage reconstruit", "items": items, "from": rep.get("from")}]
    items = []
    if rep.get("holes_closed"):
        items.append(plural(rep["holes_closed"], "trou rebouché", "trous rebouchés"))
    if rep.get("welded"):
        items.append(plural(rep["welded"], "sommet en double soudé", "sommets en double soudés"))
    if rep.get("shared_edges"):
        items.append(plural(rep["shared_edges"], "arête partagée à tort corrigée", "arêtes partagées à tort corrigées")
                     + f" ({plural(rep.get('faces_removed', 0), 'face retirée', 'faces retirées')})")
    if rep.get("duplicates_removed"):
        items.append(plural(rep["duplicates_removed"], "face en double retirée", "faces en double retirées"))
    if rep.get("debris_removed"):
        items.append(plural(rep["debris_removed"], "éclat isolé retiré", "éclats isolés retirés"))
    items.append("Volume fermé et vérifié, prêt à trancher")
    if rep.get("coloured"):
        items.append("Couleurs conservées")
    return [{"title": "Maillage réparé", "items": items, "from": rep.get("from")}]
