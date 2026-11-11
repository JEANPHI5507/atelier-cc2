"""Automatic mesh repair: a closed, printable copy of a model that keeps its colours.

AI generators (TRELLIS, Hunyuan) and scans often return meshes the slicer has to guess about: duplicated
vertices along texture seams, stray fragments, edges shared by three faces, small holes. The repair welds
vertices, drops what cannot belong to a solid, fills the holes and checks the result; the original is never
touched (the copy is written next to it, and only when it really is closed).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
import trimesh

from . import advisor, config

DEBRIS_SHARE = 0.002      # fragments under 0.2 % of the faces (and of the volume) are stray specks
MAX_CHANGE = 0.2         # a repair that adds/removes over 20 % of the faces is rebuilding the model, not mending it
SEAL_STEPS = (2, 4, 6, 8)  # voxels: holes sealed before filling, widest last (8 ~ 1.9 mm on a 60 mm figurine)
REBUILD_VOXELS = 256       # reconstruction grid along the longest side (~0.23 mm for a 60 mm figurine)
REBUILD_MAX_WORK = 3e6     # surface / voxel² beyond which a rebuild would blow up memory (real figurines: 0.3-0.5e6)
MAX_SEGMENTS = 20000      # defect lines sent to the viewer
MAX_PASSES = 4           # remove non-manifold faces / fill holes, until stable


def _weld_points(v: np.ndarray, f: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Vertices merged by position: first original index of each kept vertex, original -> kept map, faces re-indexed."""
    digits = max(0, 6 - int(np.floor(np.log10(max(float(np.ptp(v, axis=0).max()), 1e-9)))))
    _, first, inverse = np.unique(np.round(v, digits), axis=0, return_index=True, return_inverse=True)
    inverse = np.asarray(inverse).reshape(-1)
    return first, inverse, inverse[np.asarray(f)]


def _colours(g: trimesh.Trimesh) -> np.ndarray | None:
    """RGBA (sRGB, 0-255) per vertex of one mesh, or None when it carries no real colour."""
    vis = g.visual
    va = getattr(vis, "vertex_attributes", None) or {}
    if "color" in va:   # glTF COLOR_0 beside a material (TRELLIS.2 "painted" meshes): linear floats -> sRGB bytes
        rgb = np.asarray(va["color"], dtype=float)[:, :3]
        if rgb.max() <= 1.0:
            rgb = np.where(rgb <= 0.0031308, 12.92 * rgb, 1.055 * np.power(np.clip(rgb, 0, 1), 1 / 2.4) - 0.055) * 255
        return np.c_[rgb, np.full(len(rgb), 255.0)]
    if vis.kind == "texture":
        mat = getattr(vis, "material", None)
        if getattr(vis, "uv", None) is None or (getattr(mat, "image", None) is None
                                                and getattr(mat, "baseColorTexture", None) is None):
            return None   # a material without a picture: no real colours
        vis = vis.to_color()
    return np.asarray(vis.vertex_colors, dtype=float) if vis.kind == "vertex" else None


def _load(path: Path) -> tuple[np.ndarray, np.ndarray, np.ndarray | None]:
    """Vertices, faces and per-vertex colours of every piece. The scene graph is walked by hand:
    flattening it (force="mesh") drops glTF COLOR_0, i.e. the colours of TRELLIS.2 painted meshes."""
    loaded = trimesh.load(path)
    if isinstance(loaded, trimesh.Scene):
        geoms = [(loaded.geometry[name], xf) for xf, name in (loaded.graph[n] for n in loaded.graph.nodes_geometry)]
    else:
        geoms = [(loaded, np.eye(4))]
    geoms = [(g, xf) for g, xf in geoms if isinstance(g, trimesh.Trimesh) and len(g.faces)]
    if not geoms:
        raise ValueError(f"{path.name}: aucun maillage à réparer")
    vs, fs, cs, off = [], [], [], 0
    for g, xf in geoms:
        vs.append(trimesh.transform_points(np.asarray(g.vertices, float), xf))
        fs.append(np.asarray(g.faces) + off)
        cs.append(_colours(g))
        off += len(g.vertices)
    rgba = None
    if any(c is not None for c in cs):
        rgba = np.vstack([c if c is not None else np.full((len(v), 4), [192.0, 192.0, 192.0, 255.0]) for c, v in zip(cs, vs)])
    return np.vstack(vs), np.vstack(fs), rgba


def _weld(v: np.ndarray, f: np.ndarray, colours: np.ndarray | None) -> tuple[np.ndarray, np.ndarray, np.ndarray | None]:
    """Vertices merged by position (colours averaged): returns vertices, faces, RGBA or None."""
    first, inverse, faces = _weld_points(v, f)
    out = None
    if colours is not None:
        out = np.zeros((len(first), 4))
        np.add.at(out, inverse, colours)
        out /= np.bincount(inverse, minlength=len(first))[:, None]
    return v[first], faces, out


def _edges(f: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Unique edges and how many faces use each (1 = open boundary, 2 = sound, 3+ = shared by too many faces)."""
    e = np.sort(np.concatenate([f[:, [0, 1]], f[:, [1, 2]], f[:, [2, 0]]]), axis=1)
    return np.unique(e, axis=0, return_counts=True)


def _holes(open_edges: np.ndarray) -> int:
    """Number of separate holes: connected chains of open edges."""
    return len(trimesh.graph.connected_components(open_edges, min_len=1)) if len(open_edges) else 0


def diagnose(path: Path) -> dict[str, Any]:
    """What is wrong with a model, and where: counts plus line segments (viewer axes) for open and over-shared edges."""
    from . import colors
    parts = colors._parts(colors._load(path))
    v = np.vstack([p.vertices for p in parts])
    off, faces = 0, []
    for p in parts:
        faces.append(np.asarray(p.faces) + off)
        off += len(p.vertices)
    first, _, f = _weld_points(v, np.vstack(faces))
    nv = v[first]
    f = _clean_faces(f, nv)
    uniq, cnt = _edges(f)
    open_e, nm_e = uniq[cnt == 1], uniq[cnt > 2]

    def seg(edges: np.ndarray) -> list[float]:
        if len(edges) > MAX_SEGMENTS:
            edges = edges[np.linspace(0, len(edges) - 1, MAX_SEGMENTS).astype(int)]
        pts = nv[edges].reshape(-1, 3)
        return np.round(np.c_[pts[:, 0], pts[:, 2], -pts[:, 1]], 4).ravel().tolist()   # Z-up -> Y-up, like the preview

    return {"open_edges": int(len(open_e)), "holes": _holes(open_e), "nonmanifold_edges": int(len(nm_e)),
            "open": seg(open_e), "nonmanifold": seg(nm_e)}


def report_file(model: Path) -> Path:
    return model.parent / ".repairs" / (model.name + ".json")


def report_for(model: Path) -> dict[str, Any] | None:
    """What the repair of this copy did (kept beside it), or None when it is not a repaired copy."""
    try:
        return json.loads(report_file(model).read_text())
    except (OSError, ValueError):
        return None


def _clean_faces(f: np.ndarray, v: np.ndarray) -> np.ndarray:
    keep = (f[:, 0] != f[:, 1]) & (f[:, 1] != f[:, 2]) & (f[:, 0] != f[:, 2])
    f = f[keep]
    a, b, c = (v[f[:, i]] for i in range(3))
    f = f[np.linalg.norm(np.cross(b - a, c - a), axis=1) > 1e-12]
    _, idx = np.unique(np.sort(f, axis=1), axis=0, return_index=True)  # duplicate faces (also flipped twins)
    return f[np.sort(idx)]


def _nonmanifold_faces(f: np.ndarray) -> np.ndarray:
    """Mask of faces touching an edge shared by more than two faces."""
    e = np.sort(np.concatenate([f[:, [0, 1]], f[:, [1, 2]], f[:, [2, 0]]]), axis=1)
    key = e[:, 0].astype(np.int64) * (int(f.max()) + 1) + e[:, 1]
    _, inv, cnt = np.unique(key, return_inverse=True, return_counts=True)
    bad_edge = (cnt > 2)[np.asarray(inv).reshape(-1)]   # edges are stacked: (0,1) of all faces, then (1,2), then (2,0)
    return bad_edge.reshape(3, len(f)).any(axis=0)


def _debris(m: trimesh.Trimesh) -> int:
    """Drop stray fragments (tiny share of faces and of volume); returns how many pieces went."""
    bodies = m.split(only_watertight=False)
    if len(bodies) < 2:
        return 0
    total = sum(len(b.faces) for b in bodies)
    ext = float(m.extents.max())
    drop = [b for b in bodies if len(b.faces) < max(30, DEBRIS_SHARE * total) and float(b.extents.max()) < 0.05 * ext]
    if not drop or len(drop) == len(bodies):
        return 0
    keep = [b for b in bodies if all(b is not d for d in drop)]
    merged = trimesh.util.concatenate(keep)
    m.vertices, m.faces = merged.vertices, merged.faces
    if merged.visual.kind == "vertex":
        m.visual = merged.visual
    return len(drop)


def _closed(m: trimesh.Trimesh) -> bool:
    """Watertight for trimesh AND a valid solid for manifold3d (what the advisor / slicer pipeline need)."""
    if not m.is_watertight:
        return False
    return advisor._sections(np.asarray(m.vertices, float), np.asarray(m.faces)) is not None or len(m.faces) == 0


def _rebuild(v: np.ndarray, f: np.ndarray, rgba: np.ndarray | None) -> tuple[trimesh.Trimesh, dict[str, Any]]:
    """Rebuild a closed surface from the model's volume, for meshes too broken to mend.

    Surface -> voxels (small holes sealed), inside filled, then everything without thickness removed (flat
    sheets the generator left around the model, loose specks): those cannot print anyway. The surface is
    extracted again, smooth and closed, and each new vertex takes the colour of the nearest original one."""
    from scipy import ndimage
    from scipy.spatial import cKDTree
    from skimage.measure import marching_cubes

    src = trimesh.Trimesh(v, f, process=False)
    pitch = float(np.ptp(v, axis=0).max()) / REBUILD_VOXELS
    if src.area / pitch ** 2 > REBUILD_MAX_WORK:     # huge triangles spread everywhere: not a model, a cloud of sheets
        raise ValueError("ce maillage n'a pas de forme reconnaissable (surfaces immenses ou éparpillées) : "
                         "régénère-le (autre graine) ou prends un autre modèle")
    pad = SEAL_STEPS[-1] + 3                                                 # room for the widest sealing
    grid = src.voxelized(pitch)                     # every face subdivided below the voxel size: no gaps in the shell
    shell = np.pad(grid.matrix, pad)
    origin = np.asarray(grid.translation, float)    # centre of voxel (0, 0, 0)

    ball = ndimage.generate_binary_structure(3, 1)
    for seal in SEAL_STEPS:                         # thicken the shell until it holds water, fill, shrink back
        grown = ndimage.binary_dilation(shell, ball, iterations=seal)
        filled = ndimage.binary_fill_holes(grown)
        if filled.sum() - grown.sum() >= 0.5 * shell.sum():
            solid = ndimage.binary_erosion(filled, ball, iterations=seal)
            break
    else:
        raise ValueError("l'enveloppe du modèle est trop trouée pour retrouver son volume : régénère-le "
                         "(autre graine) ou prends un autre modèle")
    thick = ndimage.binary_opening(solid, ball, iterations=2)             # sheets and threads without thickness go
    labels, n = ndimage.label(thick)
    if n == 0:
        raise ValueError("rien d'épais à reconstruire : le modèle n'est fait que de surfaces sans volume")
    sizes = ndimage.sum(thick, labels, index=np.arange(1, n + 1))
    keep = np.isin(labels, 1 + np.flatnonzero(sizes >= 0.01 * sizes.max()))
    vol = ndimage.gaussian_filter(keep.astype(np.float32), sigma=0.7)    # smooth, not blocky
    mv, mf_, _, _ = marching_cubes(vol, level=0.5)
    m = trimesh.Trimesh((mv - pad) * pitch + origin, mf_[:, ::-1], process=False)
    m.merge_vertices()
    trimesh.repair.fix_normals(m)
    if rgba is not None:
        _, near = cKDTree(v).query(m.vertices)
        m.visual = trimesh.visual.ColorVisuals(m, vertex_colors=np.clip(rgba[near], 0, 255).astype(np.uint8))
    removed = float(solid.sum() - keep.sum()) / max(1.0, float(solid.sum()))
    return m, {"rebuilt": True, "voxel_share": round(1 / REBUILD_VOXELS, 5), "sheets_removed": removed > 0.005, "sealed": seal,
               "pieces_dropped": int(n - int((sizes >= 0.01 * sizes.max()).sum()))}


def repair(path: Path, out: Path | None = None) -> dict[str, Any]:
    """Write a repaired copy of ``path`` and report what was done. Never overwrites an existing file."""
    v0, f0, c0 = _load(path)
    faces_before = int(len(f0))
    open_before = not trimesh.Trimesh(v0, f0, process=False).is_watertight

    v, f, rgba = _weld(v0, f0, c0)
    welded = len(v0) - len(v)
    faces_welded = len(f)
    f = _clean_faces(f, v)
    uniq, cnt = _edges(f)
    holes, open_edges, shared_edges = _holes(uniq[cnt == 1]), int((cnt == 1).sum()), int((cnt > 2).sum())
    m = trimesh.Trimesh(v, f, process=False)
    if rgba is not None:
        m.visual = trimesh.visual.ColorVisuals(m, vertex_colors=np.clip(rgba, 0, 255).astype(np.uint8))
    m.remove_unreferenced_vertices()

    removed = 0
    for _ in range(MAX_PASSES):
        bad = _nonmanifold_faces(np.asarray(m.faces)) if len(m.faces) else np.zeros(0, bool)
        if bad.any():
            removed += int(bad.sum())
            m.update_faces(~bad)
            m.remove_unreferenced_vertices()
        trimesh.repair.fix_winding(m)
        trimesh.repair.fix_normals(m)
        trimesh.repair.fill_holes(m)
        if m.is_watertight and not bad.any():
            break
    debris = _debris(m)
    if debris:
        trimesh.repair.fill_holes(m)
    closed = _closed(m)
    changed = abs(len(m.faces) - faces_before) / faces_before
    extra: dict[str, Any] = {"rebuilt": False}
    if not closed or changed > MAX_CHANGE or m.volume <= 0:   # mending is not enough: rebuild from the volume
        m, extra = _rebuild(v, f, rgba)                       # the welded, cleaned original
        closed = _closed(m)
        if not closed or m.volume <= 0:
            raise ValueError("ce maillage ne peut pas être fermé, même reconstruit : régénère-le (autre graine) "
                             "ou prends un autre modèle")

    if m.visual.kind != "vertex":     # no colour: the workshop's usual light grey, not trimesh's dark default
        m.visual = trimesh.visual.ColorVisuals(m, vertex_colors=np.tile([192, 192, 192, 255], (len(m.vertices), 1)).astype(np.uint8))
    if out is None:
        stem = path.stem.removesuffix("_repare")
        out = config.MODELS_DIR / f"{stem}_repare{path.suffix}"
        k = 1
        while out.exists():
            k += 1
            out = config.MODELS_DIR / f"{stem}_repare{k}{path.suffix}"
    m.export(out)
    report = {
        "name": out.name,
        "closed": closed,
        "was_open": open_before,
        "faces_before": faces_before,
        "faces_after": int(len(m.faces)),
        "faces_removed": removed,
        "debris_removed": debris,
        "coloured": rgba is not None,
        "holes_closed": holes,
        "open_edges": open_edges,
        "shared_edges": shared_edges,
        "welded": int(welded),
        "duplicates_removed": int(faces_welded - len(f)),
        **extra,
    }
    side = report_file(out)
    side.parent.mkdir(exist_ok=True)
    side.write_text(json.dumps({"from": path.name, **report}))
    return report
