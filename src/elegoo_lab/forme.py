"""A simple shape drilled through a model, added to it, or kept where both meet (union / difference /
intersection), written as a new file next to the original.

Each part is cut on its own, so the parts keep their filament. Manifold remembers which original face every
triangle comes from: painted faces keep their paint code, coloured faces their colour.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import manifold3d as mf
import numpy as np
import trimesh

from . import colorize, colors, threemf

SHAPES = {"cylindre": "Cylindre", "cube": "Pavé", "sphere": "Boule"}
OPS = {"percer": "Percer", "ajouter": "Ajouter", "garder": "Garder seulement le commun"}
AXES = {"z": np.eye(3), "x": np.array([[0, 0, 1], [0, 1, 0], [-1, 0, 0]], float),   # the shape's length along X...
        "y": np.array([[1, 0, 0], [0, 0, 1], [0, -1, 0]], float)}                    # ...or along Y
SUFFIX = {"percer": "perce", "ajouter": "ajout", "garder": "commun"}


def _shape(kind: str, size: tuple[float, float, float], axis: str) -> mf.Manifold:
    """The shape centred on the origin, its length (``size[2]``) along ``axis``."""
    w, d, h = size
    if kind == "cylindre":
        s = mf.Manifold.cylinder(h, w / 2, w / 2, 96, True)
    elif kind == "cube":
        s = mf.Manifold.cube([w, d, h], True)
    elif kind == "sphere":
        s = mf.Manifold.sphere(w / 2, 96)
    else:
        raise ValueError(f"forme inconnue « {kind} » ({', '.join(SHAPES)})")
    r = AXES[axis]
    return s.transform(np.hstack([r, np.zeros((3, 1))]).tolist())


def _solid(p: threemf.Part) -> tuple[mf.Manifold, trimesh.Trimesh]:
    m = trimesh.Trimesh(p.vertices, p.faces, process=False)
    m.merge_vertices()                       # one vertex per corner breaks manifold; the face order stays
    solid = mf.Manifold(mf.Mesh(vert_properties=np.asarray(m.vertices, np.float32), tri_verts=np.asarray(m.faces, np.uint32)))
    if solid.status() != mf.Error.NoError or solid.is_empty():
        raise ValueError(f"« {p.name} » n'est pas un volume fermé : répare le modèle d'abord (bouton « Réparer »)")
    return solid.as_original(), m


def _part(result: mf.Manifold, source: threemf.Part, origin: int) -> threemf.Part | None:
    """The cut part, every triangle carrying the paint or colour of the face it comes from."""
    out = result.to_mesh()
    tri = np.asarray(out.tri_verts).astype(np.int64)
    if not len(tri):
        return None
    v = np.asarray(out.vert_properties)[:, :3].astype(float)
    runs, ids = np.asarray(out.run_index), np.asarray(out.run_original_id)
    run = np.searchsorted(runs, np.arange(len(tri)) * 3, side="right") - 1
    face = np.asarray(out.face_id).astype(np.int64)
    mine = ids[run] == origin                      # faces of this part; the others come from the shape
    paint = ([source.paint[f] if ok else None for f, ok in zip(face.tolist(), mine.tolist())] if source.paint else None)
    rgb = None
    if source.face_rgb is not None:
        known = np.asarray(source.face_rgb, float)
        shades, count = np.unique(known.astype(int), axis=0, return_counts=True) if len(known) else (np.full((1, 3), 192), [1])
        fill = shades[int(np.argmax(count))]       # the cut's new walls take the part's main colour
        rgb = np.where(mine[:, None], np.asarray(source.face_rgb, float)[np.clip(face, 0, len(source.face_rgb) - 1)], fill)
    return threemf.Part(source.name, v, tri, source.extruder, paint if paint and any(paint) else None, rgb)


def apply(src: Path, *, shape: str, op: str, size: tuple[float, float, float], at: tuple[float, float, float],
          axis: str = "z", colour: int = 1, out: Path | None = None) -> dict[str, Any]:
    """``at``: the shape's centre from the model's centre (mm, the model's own axes, z up). ``colour``: for
    « ajouter », the colour index the shape takes (one past the model's colours = a new one)."""
    if op not in OPS:
        raise ValueError(f"opération inconnue « {op} » ({', '.join(OPS)})")
    if axis not in AXES:
        raise ValueError("axe : z (debout), x ou y (couché)")
    if not all(0.5 <= s <= 300 for s in size):
        raise ValueError("chaque dimension de la forme entre 0,5 et 300 mm")
    pr = colors._load(src)
    parts = colors._parts(pr)
    allv = np.vstack([p.vertices for p in parts])
    centre = (allv.min(0) + allv.max(0)) / 2 + np.asarray(at, float)
    cutter = _shape(shape, size, axis).translate(centre.tolist()).as_original()
    rgb_mode = any(p.face_rgb is not None for p in parts)
    if op == "percer" and all((_solid(p)[0] ^ cutter).is_empty() for p in parts):
        raise ValueError("la forme ne touche pas le modèle : rapproche-la (décalages en mm depuis son centre)")
    objects: list[threemf.Object] = []
    for o in pr.objects:
        kept = []
        for p in o.parts:
            solid, _ = _solid(p)
            result = {"percer": lambda: solid - cutter, "garder": lambda: solid ^ cutter, "ajouter": lambda: solid}[op]()
            q = _part(result, p, solid.original_id())
            if q is not None:
                kept.append(q)
        if kept:
            objects.append(threemf.Object(o.name, kept))
    if not objects:
        raise ValueError("il ne reste rien du modèle : la forme ne le touche pas, ou l'enlève en entier")
    if op == "ajouter":
        # the shape minus the model: two parts never overlap (the slicer would have to pick a filament there)
        body = None
        for p in parts:
            solid, _ = _solid(p)
            body = solid if body is None else body + solid
        sm = (cutter - body).to_mesh()
        v, f = np.asarray(sm.vert_properties)[:, :3].astype(float), np.asarray(sm.tri_verts).astype(np.int64)
        if rgb_mode:
            known = [np.asarray(p.face_rgb, float).mean(axis=0) for p in parts if p.face_rgb is not None]
            hexes = [c["hex"] for c in colors.analyze(src)["colours"]]
            pick = hexes[colour - 1] if 1 <= colour <= len(hexes) else colorize.PALETTE[min(len(hexes), 3)]
            col = colors._rgb(pick) if pick else (known[0] if known else np.full(3, 192.0))
            objects.append(threemf.Object(SHAPES[shape], [threemf.Part(SHAPES[shape], v, f, 1, None, np.tile(col, (len(f), 1)))]))
        else:
            objects.append(threemf.Object(SHAPES[shape], [threemf.Part(SHAPES[shape], v, f, max(1, min(4, colour)))]))
    result = threemf.Project(objects, pr.colours)
    ext = ".glb" if rgb_mode else ".3mf"
    out = out or src.with_name(f"{src.stem}_{SUFFIX[op]}{ext}")
    k = 2
    while out.exists():
        out = src.with_name(f"{src.stem}_{SUFFIX[op]} ({k}){ext}")
        k += 1
    rparts = colors._parts(result)
    if rgb_mode:   # coloured meshes stay a coloured mesh: one GLB, a colour per face
        meshes = []
        for p in rparts:
            m = trimesh.Trimesh(p.vertices, p.faces, process=False)
            m.visual = trimesh.visual.ColorVisuals(m, face_colors=np.c_[np.asarray(p.face_rgb if p.face_rgb is not None
                                                                                     else np.full((len(p.faces), 3), 192.0)), np.full(len(p.faces), 255)].astype(np.uint8))
            m.unmerge_vertices()   # glTF keeps colours per vertex: shared corners would blend two faces
            meshes.append(m)
        whole = trimesh.util.concatenate(meshes)
        if src.suffix.lower() in {".glb", ".gltf"}:   # the loader turned glTF Y-up into Z-up: turn it back
            whole.apply_transform(trimesh.transformations.rotation_matrix(-np.pi / 2, [1, 0, 0]))
        whole.export(out)
    else:
        n = max(p.extruder for p in rparts)
        cols = (list(pr.colours) + colorize.PALETTE)[:max(n, 1)] if pr.colours else colorize.PALETTE[:max(n, 1)]
        threemf.write(result, out, filaments=max(n, 1), colours=cols)
    lo, hi = np.vstack([p.vertices for p in rparts]).min(0), np.vstack([p.vertices for p in rparts]).max(0)
    return {"name": out.name, "size_mm": (hi - lo).round(1).tolist()}
