"""Models that already carry colours -> a CANVAS-ready 3MF (at most 4 filaments).

Sources handled:

* 3MF projects (OrcaSlicer / Bambu Studio / MakerWorld): colours come from the
  project's ``filament_colour``; geometry is coloured by per-triangle painting
  (``paint_color``) and/or per-part ``extruder``. Filament indices are remapped
  in place, so painting detail is preserved exactly.
* Coloured meshes (GLB/GLTF, OBJ+MTL, PLY): per-face colours (materials,
  textures or vertex colours) are clustered to <= 4 colours and written as
  per-triangle paint on a single object.

Painting uses the PrusaSlicer/Orca TriangleSelector encoding: a bitstream
written LSB-first per hex nibble, nibbles in reverse order. A leaf stores its
state in 2 bits, or ``0b11`` + 4 bits (state - 3) for states >= 3. State 0 =
"use the part's filament", state N = filament N.
"""

from __future__ import annotations

import copy
import itertools
import json
import os
import re
import struct
from collections import Counter
from collections.abc import Callable
from pathlib import Path
from typing import Any

import numpy as np
import trimesh
from scipy.sparse import coo_matrix
from scipy.sparse.csgraph import connected_components

from . import colorize, config, mesh, slicer, threemf

MAX_SLOTS = 4
MIN_SHARE = 0.01   # colours covering less than 1 % of the surface join their nearest colour
MERGE_DIST = 30.0  # RGB distance under which two colours count as one filament
MESH_COLOUR_EXT = {".glb", ".gltf", ".obj", ".ply"}


# --- TriangleSelector paint strings -----------------------------------------------------

def _bits(code: str) -> list[int]:
    out: list[int] = []
    for ch in reversed(code):
        v = int(ch, 16)
        out += [(v >> k) & 1 for k in range(4)]
    return out


def _walk(code: str, leaf: Callable[[int], int]) -> str:
    """Re-encode ``code`` with every leaf state passed through ``leaf``."""
    bits, pos, out = _bits(code), 0, []

    def take(n: int) -> int:
        nonlocal pos
        v = sum(bits[pos + k] << k for k in range(n))
        pos += n
        return v

    def put(v: int, n: int) -> None:
        out.extend((v >> k) & 1 for k in range(n))

    def node() -> None:
        split = take(2)
        put(split, 2)
        if split:
            put(take(2), 2)  # special side
            for _ in range(split + 1):
                node()
            return
        st = take(2)
        if st == 3:
            st = 3 + take(4)
        st = leaf(st)
        if st < 3:
            put(st, 2)
        else:
            put(3, 2)
            put(st - 3, 4)

    node()
    while len(out) % 4:
        out.append(0)
    return "".join(f"{sum(out[j + k] << k for k in range(4)):X}" for j in range(0, len(out), 4))[::-1]


def paint_states(code: str) -> set[int]:
    seen: set[int] = set()
    _walk(code, lambda s: seen.add(s) or s)
    return seen


def remap_paint(code: str, mapping: dict[int, int]) -> str:
    return _walk(code, lambda s: mapping.get(s, s))


def encode_state(state: int) -> str:
    return _walk("4", lambda _s: state)


# --- loading: every format -> parts with a colour label per face ------------------------------

def _hex(rgb: np.ndarray) -> str:
    return "#{:02X}{:02X}{:02X}".format(*tuple(int(round(c)) for c in rgb[:3]))


def _rgb(h: str) -> np.ndarray:
    h = h.lstrip("#")[:6]
    return np.array([int(h[i:i + 2], 16) for i in (0, 2, 4)], dtype=float)


def _vertex_majority(g: trimesh.Trimesh, vc: np.ndarray) -> np.ndarray:
    """Face colour = colour shared by most of its vertices (averaging invents hues at borders)."""
    vc = vc[:, :3][g.faces]
    same01 = (vc[:, 0] == vc[:, 1]).all(1)
    same12 = (vc[:, 1] == vc[:, 2]).all(1)
    return np.where(same12[:, None] & ~same01[:, None], vc[:, 1], vc[:, 0]).astype(float)


def _face_from_vertex(g: trimesh.Trimesh, vc: np.ndarray) -> np.ndarray:
    """Flat palettes keep their exact colours (majority); continuous colours are averaged."""
    if len(np.unique(vc.round(), axis=0)) <= 64:
        return _vertex_majority(g, vc)
    return vc[g.faces].mean(axis=1)


def _merge_close(centres: np.ndarray, labels: np.ndarray, weights: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Fuse colours no filament could tell apart (RGB distance < MERGE_DIST) and specks (< MIN_SHARE)."""
    share = np.bincount(labels, weights=weights, minlength=len(centres))
    keep: list[int] = []
    remap = np.arange(len(centres))
    total = share.sum() or 1
    for i in np.argsort(-share):
        near = [k for k in keep if np.linalg.norm(centres[i] - centres[k]) < MERGE_DIST]
        if not near and keep and share[i] / total < MIN_SHARE:  # specks: not worth a filament change
            near = [min(keep, key=lambda k: np.linalg.norm(centres[i] - centres[k]))]
        if near:
            remap[i] = near[0]
        else:
            keep.append(int(i))
    new_index = {k: j for j, k in enumerate(keep)}
    return centres[keep], np.array([new_index[remap[label_idx]] for label_idx in range(len(centres))])[labels]


# --- hand retouching: faces repainted in the viewer, kept beside the model (never inside it) ---------

HEX = re.compile(r"^#[0-9A-Fa-f]{6}$")


def retouch_file(path: Path) -> Path:
    return path.parent / ".retouches" / (path.name + ".json")


def load_retouch(path: Path) -> dict[str, list[int]]:
    """{"#RRGGBB": [face index, ...]}: face numbers follow the model's own triangle order."""
    try:
        data = json.loads(retouch_file(path).read_text())
    except (OSError, ValueError):
        return {}
    return {h: [int(i) for i in idx] for h, idx in data.items() if HEX.match(h)} if isinstance(data, dict) else {}


def save_retouch(path: Path, paint: dict[str, list[int]], erase: list[int] | None = None, clear: bool = False) -> int:
    """Merge a retouch into the model's sidecar; returns how many faces are retouched. Touches the model's
    date so every cache keyed on it (colours, previews, advice) forgets the old look."""
    f = retouch_file(path)
    if clear:
        f.unlink(missing_ok=True)
        os.utime(path)
        return 0
    total = int(mesh.info(path)["triangles"])
    faces: dict[int, str] = {i: h for h, idx in load_retouch(path).items() for i in idx}
    for i in erase or []:
        faces.pop(int(i), None)
    for h, idx in paint.items():
        if not HEX.match(h):
            raise ValueError(f"couleur invalide : {h}")
        for i in idx:
            if not 0 <= int(i) < total:
                raise ValueError(f"face {i} hors du modèle ({total} faces)")
            faces[int(i)] = h.upper()
    out: dict[str, list[int]] = {}
    for i, h in faces.items():
        out.setdefault(h, []).append(i)
    if out:
        f.parent.mkdir(exist_ok=True)
        f.write_text(json.dumps({h: sorted(v) for h, v in out.items()}))
    else:
        f.unlink(missing_ok=True)
    os.utime(path)
    return len(faces)


# painted by hand in the viewer, for the slicer: kind -> (Part field, TriangleSelector state)
MARKS = {"support": ("supports", 1), "sans_support": ("supports", 2), "couture": ("seam", 1)}


def marks_file(path: Path) -> Path:
    return path.parent / ".marques" / (path.name + ".json")


def load_marks(path: Path) -> dict[str, list[int]]:
    """{"support" | "sans_support" | "couture": [face index, ...]}, faces in the model's own order."""
    try:
        data = json.loads(marks_file(path).read_text())
    except (OSError, ValueError):
        return {}
    return {k: [int(i) for i in v] for k, v in data.items() if k in MARKS} if isinstance(data, dict) else {}


def save_marks(path: Path, add: dict[str, list[int]], erase: list[int] | None = None, clear: bool = False) -> dict[str, int]:
    """Merge painted marks into the model's sidecar (a face has one mark at most); returns the count per kind.
    The model's date is left alone: the marks change nothing the colour and preview caches keep."""
    f = marks_file(path)
    if clear:
        f.unlink(missing_ok=True)
        return {}
    total = int(mesh.info(path)["triangles"])
    faces: dict[int, str] = {i: k for k, idx in load_marks(path).items() for i in idx}
    for i in erase or []:
        faces.pop(int(i), None)
    for k, idx in add.items():
        if k not in MARKS:
            raise ValueError(f"marque inconnue : {k} ({', '.join(MARKS)})")
        for i in idx:
            if not 0 <= int(i) < total:
                raise ValueError(f"face {i} hors du modèle ({total} faces)")
            faces[int(i)] = k
    out: dict[str, list[int]] = {}
    for i, k in faces.items():
        out.setdefault(k, []).append(i)
    if out:
        f.parent.mkdir(exist_ok=True)
        config.write_atomic(f, json.dumps({k: sorted(v) for k, v in out.items()}))
    else:
        f.unlink(missing_ok=True)
    return {k: len(v) for k, v in out.items()}


def _apply_marks(path: Path, parts: list[threemf.Part]) -> None:
    marks = load_marks(path)
    if not marks or not parts:
        return
    starts = np.cumsum([0] + [len(p.faces) for p in parts])
    for kind, idx in marks.items():
        field, state = MARKS[kind]
        code = encode_state(state)
        ids = np.asarray(idx, dtype=int)
        ids = ids[(ids >= 0) & (ids < starts[-1])]
        which = np.searchsorted(starts, ids, side="right") - 1
        for k, p in enumerate(parts):
            local = ids[which == k] - starts[k]
            if len(local):
                codes = getattr(p, field) or [None] * len(p.faces)
                for i in local.tolist():
                    codes[i] = code
                setattr(p, field, codes)


FILAMENT_DE = 25.0  # beyond this ΔE a project filament is visibly another colour (spools.FAR_DE)


def _beyond_filaments(paint: dict[str, list[int]], pr: threemf.Project) -> bool:
    """True when a hand-painted colour would have to ride a project filament of another colour
    (white on an all-yellow 3MF): it must stay itself instead of turning that wrong colour."""
    cols = np.array([_rgb(h) for h in (pr.colours or []) if HEX.match(str(h))]) if pr.colours else None
    if cols is None or not len(cols):
        return True
    lab = _to_lab(cols)
    return any(float(np.linalg.norm(lab - _to_lab(_rgb(h).reshape(1, -1)))) > FILAMENT_DE for h in paint)


def _seed_face_colours(pr: threemf.Project) -> None:
    """Give every part face colours of its look today (one filament colour per paint state), so a hand
    paint can use exact colours the project's own filaments cannot render."""
    pal = [None] + [_rgb(h) if HEX.match(str(h)) else None for h in (pr.colours or [])]
    for p in _parts(pr):
        if p.face_rgb is not None:
            continue
        base = pal[p.extruder] if p.extruder < len(pal) else None
        rgb = np.tile(base if base is not None else np.full(3, 192.0), (len(p.faces), 1))
        for i, code in enumerate(p.paint or []):
            st = min(paint_states(code) - {0}, default=0) if code else 0   # first override, else the base
            c = pal[st] if st and st < len(pal) else base
            if c is not None:
                rgb[i] = c
        p.face_rgb = rgb


def _apply_retouch(path: Path, pr: threemf.Project) -> None:
    """Hand painting into the loaded parts, face numbers as in the viewer: face colours where the file
    carries them, else paint states pointing at the project's own filament of that colour (3MF), else
    colour families beside the model's plain grey (a plain STL gains colours it never had)."""
    paint = load_retouch(path)
    parts = _parts(pr)
    if not paint or not parts:
        return
    starts = np.cumsum([0] + [len(p.faces) for p in parts])
    # a painted colour no project filament comes close to (white on an all-yellow 3MF) must not ride a
    # filament of another colour: the project becomes a face-coloured mesh, the exact colour kept
    if not _rgb_mode(pr) and _beyond_filaments(paint, pr):
        _seed_face_colours(pr)
    if _rgb_mode(pr) or not (pr.colours or any(p.paint for p in parts)):
        grey = np.full(3, 192.0)
        for h, idx in paint.items():
            rgb = _rgb(h)
            ids = np.asarray(idx, dtype=int)
            ids = ids[(ids >= 0) & (ids < starts[-1])]
            which = np.searchsorted(starts, ids, side="right") - 1
            for k, p in enumerate(parts):
                local = ids[which == k] - starts[k]
                if not len(local):
                    continue
                if p.face_rgb is None:
                    p.face_rgb = np.repeat(grey, len(p.faces), axis=0).reshape(len(p.faces), 3)
                p.face_rgb[local] = rgb
                if p.locked is None:
                    p.locked = np.zeros(len(p.faces), bool)
                p.locked[local] = True
        return
    # a 3MF colours by filament: the face takes the project's filament matching that colour
    codes: dict[str, str] = {}
    pal = [(i + 1, _rgb(h)) for i, h in enumerate(pr.colours or [])]
    for h, idx in paint.items():
        if not pal:
            continue
        rgb, state = _rgb(h), min(pal, key=lambda c: float(np.linalg.norm(c[1] - _rgb(h))))[0]
        code = codes.setdefault(h, encode_state(state))
        ids = np.asarray(idx, dtype=int)
        ids = ids[(ids >= 0) & (ids < starts[-1])]
        which = np.searchsorted(starts, ids, side="right") - 1
        for k, p in enumerate(parts):
            local = ids[which == k] - starts[k]
            if not len(local):
                continue
            if p.paint is None:
                p.paint = [None] * len(p.faces)
            for i in local.tolist():
                p.paint[i] = code


def _mesh_project(path: Path) -> threemf.Project:
    loaded = trimesh.load(path)
    if isinstance(loaded, trimesh.Scene):
        # walk the scene graph ourselves: Scene.dump() drops glTF vertex attributes (COLOR_0)
        geoms = []
        for node in loaded.graph.nodes_geometry:
            xf, name = loaded.graph[node]
            geoms.append((loaded.geometry[name], xf))
    else:
        geoms = [(loaded, np.eye(4))]
    parts = []
    for g, xf in geoms:
        if not isinstance(g, trimesh.Trimesh) or not len(g.faces):
            continue
        try:
            va = getattr(g.visual, "vertex_attributes", None) or {}
            if "color" in va:  # glTF COLOR_0 next to a material (TRELLIS.2 "painted" meshes)
                vc = np.asarray(va["color"], dtype=float)[:, :3]
                if vc.max() <= 1.0:  # glTF COLOR_0 floats are linear: convert to sRGB like textures
                    vc = np.where(vc <= 0.0031308, 12.92 * vc, 1.055 * np.power(np.clip(vc, 0, 1), 1 / 2.4) - 0.055) * 255
                fc = _face_from_vertex(g, vc)
            else:
                vis = g.visual.to_color() if g.visual.kind == "texture" else g.visual
                fc = (_face_from_vertex(g, np.asarray(vis.vertex_colors, dtype=float)[:, :3]) if vis.kind == "vertex"
                      else np.asarray(vis.face_colors, dtype=float)[:, :3])
        except Exception:
            fc = np.full((len(g.faces), 3), 192.0)
        verts = trimesh.transform_points(np.asarray(g.vertices, float), xf)
        parts.append(threemf.Part(path.stem, verts, np.asarray(g.faces), 1, None, fc))
    if not parts:
        raise ValueError(f"{path.name}: aucun maillage")
    if path.suffix.lower() in {".glb", ".gltf"}:  # Y-up -> Z-up
        rot = trimesh.transformations.rotation_matrix(np.pi / 2, [1, 0, 0])[:3, :3]
        for p in parts:
            p.vertices = p.vertices @ rot.T
    return threemf.Project([threemf.Object(path.stem, parts)], [])


def _load(path: Path) -> threemf.Project:
    pr = threemf.read(path) if path.suffix.lower() == ".3mf" else threemf.cached(path, _load_mesh)
    _apply_retouch(path, pr)
    return pr


def _load_mesh(path: Path) -> threemf.Project:
    if path.suffix.lower() in MESH_COLOUR_EXT:
        return _mesh_project(path)
    m = mesh.load(path)  # plain STL & co: one colour
    return threemf.Project([threemf.Object(path.stem, [threemf.Part(path.stem, np.asarray(m.vertices, float),
                                                                     np.asarray(m.faces))])], [])


def _parts(pr: threemf.Project) -> list[threemf.Part]:
    return [p for o in pr.objects for p in o.parts]


def _areas(p: threemf.Part) -> np.ndarray:
    t = p.vertices[p.faces]
    return np.linalg.norm(np.cross(t[:, 1] - t[:, 0], t[:, 2] - t[:, 0]), axis=1) / 2


def _cluster(cols: np.ndarray, weights: np.ndarray, k: int) -> tuple[np.ndarray, np.ndarray]:
    """Weighted k-means on RGB. Returns (centres, label per row)."""
    uniq, inv = np.unique(cols.round(), axis=0, return_inverse=True)
    w = np.bincount(inv.ravel(), weights=weights)
    k = min(k, len(uniq))
    centres = uniq[np.argsort(-w)[:1]]
    while len(centres) < k:  # farthest-point init, weighted
        d = ((uniq[:, None] - centres[None]) ** 2).sum(-1).min(1) * w
        centres = np.vstack([centres, uniq[np.argmax(d)]])
    for _ in range(25):
        lab = ((uniq[:, None] - centres[None]) ** 2).sum(-1).argmin(1)
        new = np.array([np.average(uniq[lab == i], axis=0, weights=w[lab == i]) if (lab == i).any() else centres[i]
                        for i in range(k)])
        if np.allclose(new, centres):
            break
        centres = new
    return centres, lab[inv.ravel()]


def _to_lab(rgb: np.ndarray) -> np.ndarray:
    """sRGB (0-255) -> CIELAB, where distances follow perceived colour differences."""
    c = np.asarray(rgb, float) / 255
    lin = np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)
    xyz = lin @ np.array([[0.4124, 0.3576, 0.1805], [0.2126, 0.7152, 0.0722], [0.0193, 0.1192, 0.9505]]).T
    xyz /= np.array([0.95047, 1.0, 1.08883])
    f = np.where(xyz > 0.008856, np.cbrt(xyz), 7.787 * xyz + 16 / 116)
    return np.c_[116 * f[:, 1] - 16, 500 * (f[:, 0] - f[:, 1]), 200 * (f[:, 1] - f[:, 2])]


FINE_CLUSTERS = 12      # colour families found first, before choosing the 4 spools
DISTINCT_CAP = 60.0     # ΔE above which two colours count as fully different


def _palette(cols: np.ndarray, weights: np.ndarray, k: int) -> tuple[np.ndarray, np.ndarray]:
    """Pick k spool colours for a many-coloured mesh: colour families in Lab, then the families that
    cover the model best while staying distinct, so a small vivid area (a red shirt) beats a second
    shade of the dominant colour. Returns (k RGB centres, label per row)."""
    uniq, inv = np.unique(cols.round(), axis=0, return_inverse=True)
    w = np.bincount(inv.ravel(), weights=weights)
    lab = _to_lab(uniq)
    fine = _cluster_points(lab, w, min(FINE_CLUSTERS, len(uniq)))
    fam_w = np.bincount(fine, weights=w, minlength=fine.max() + 1)
    fam_lab = np.array([np.average(lab[fine == i], axis=0, weights=w[fine == i]) if fam_w[i] > 0 else lab[0]
                        for i in range(len(fam_w))])
    # family colour = its most used real colour (not an average: averages look muddy)
    fam_rgb = np.array([uniq[fine == i][np.argmax(w[fine == i])] if fam_w[i] > 0 else uniq[0] for i in range(len(fam_w))])
    share = fam_w / fam_w.sum()
    chosen = [int(np.argmax(share))]
    while len(chosen) < min(k, int((fam_w > 0).sum())):
        de = np.min([np.linalg.norm(fam_lab - fam_lab[c], axis=1) for c in chosen], axis=0)
        score = share ** 0.35 * np.minimum(de, DISTINCT_CAP)
        score[chosen] = -1
        chosen.append(int(np.argmax(score)))
    to_chosen = np.argmin([np.linalg.norm(fam_lab - fam_lab[c], axis=1) for c in chosen], axis=0)
    return fam_rgb[chosen].astype(float), to_chosen[fine][inv.ravel()]


def _cluster_points(pts: np.ndarray, w: np.ndarray, k: int) -> np.ndarray:
    """Weighted k-means (farthest-point start) on arbitrary points; returns a label per point."""
    centres = pts[np.argsort(-w)[:1]]
    while len(centres) < k:
        d = ((pts[:, None] - centres[None]) ** 2).sum(-1).min(1) * w
        centres = np.vstack([centres, pts[np.argmax(d)]])
    for _ in range(30):
        lab = ((pts[:, None] - centres[None]) ** 2).sum(-1).argmin(1)
        new = np.array([np.average(pts[lab == i], axis=0, weights=w[lab == i]) if (lab == i).any() else centres[i]
                        for i in range(k)])
        if np.allclose(new, centres):
            break
        centres = new
    return lab


def _rgb_mode(pr: threemf.Project) -> bool:
    return any(p.face_rgb is not None for p in _parts(pr))


Palette = tuple[str | None, ...]   # spool colour per CANVAS slot (slot 1 first), None for an empty slot


def _rgb_labels(pr: threemf.Project, palette: Palette | None = None) -> tuple[np.ndarray, list[np.ndarray], int]:
    """Colour centres (<= 4) and a centre index per face for every part.

    With ``palette`` (the spools loaded in the CANVAS) every face takes the closest spool colour
    (CIELAB) instead of the model's own colour families: centre ``i`` is then slot ``i + 1``."""
    parts = _parts(pr)
    cols = np.vstack([p.face_rgb if p.face_rgb is not None else np.full((len(p.faces), 3), 192.0) for p in parts])
    w = np.concatenate([_areas(p) for p in parts])
    uniq, inv = np.unique(cols.round(), axis=0, return_inverse=True)
    if palette and any(palette):
        centres = np.array([_rgb(h) if h else np.full(3, 192.0) for h in palette])
        de = np.linalg.norm(_to_lab(uniq)[:, None] - _to_lab(centres)[None], axis=2)
        de[:, [i for i, h in enumerate(palette) if not h]] = np.inf
        lab = de.argmin(1)[inv.ravel()]
    else:
        centres, lab = (uniq, inv.ravel()) if len(uniq) <= MAX_SLOTS else _palette(cols, w, MAX_SLOTS)
        centres, lab = _merge_close(centres, lab, w)
    out, i = [], 0
    for p in parts:
        out.append(_clean_labels(p, lab[i:i + len(p.faces)]))
        i += len(p.faces)
    return centres, out, len(uniq)


SMOOTH_PASSES = 2       # majority passes that straighten ragged borders between two colours
MIN_ISLAND = 0.002      # a patch under 0.2 % of the part's surface takes the colour around it


def _neighbours(p: threemf.Part) -> np.ndarray:
    """(M, 3) faces sharing an edge with each face, -1 where none (open edge)."""
    m = trimesh.Trimesh(p.vertices, p.faces, process=False)
    m.merge_vertices()            # texture seams split vertices; the face order is kept
    pairs = np.vstack([m.face_adjacency, m.face_adjacency[:, ::-1]])
    pairs = pairs[np.argsort(pairs[:, 0], kind="stable")]
    first = np.searchsorted(pairs[:, 0], pairs[:, 0])        # rank of each pair among its face's pairs
    rank = np.arange(len(pairs)) - first
    keep = rank < 3                                           # non-manifold edges: three neighbours are enough
    nb = np.full((len(p.faces), 3), -1)
    nb[pairs[keep, 0], rank[keep]] = pairs[keep, 1]
    return nb


def _clean_labels(p: threemf.Part, lab: np.ndarray) -> np.ndarray:
    """Fewer, cleaner colour areas, as a printer can render them.

    Textures from AI models leave ragged borders and hundreds of specks. Each speck is a filament
    change on every layer it crosses (about a minute each on the CANVAS) for a dot nobody sees.
    Borders are smoothed (a face whose neighbours agree on another colour takes it), then patches
    under MIN_ISLAND of the surface melt into the colour they share the longest border with.
    Faces painted by hand (``p.locked``) never change."""
    lab = lab.copy()
    if len(lab) < 50 or len(np.unique(lab)) < 2:
        return lab
    locked = p.locked if p.locked is not None else np.zeros(len(lab), bool)
    nb = _neighbours(p)
    has = nb >= 0
    for _ in range(SMOOTH_PASSES):
        nl = np.where(has, lab[np.maximum(nb, 0)], -1)
        # two or three neighbours with the same other colour win
        pair = np.where((nl[:, 0] == nl[:, 1]) | (nl[:, 0] == nl[:, 2]), nl[:, 0], np.where(nl[:, 1] == nl[:, 2], nl[:, 1], -1))
        flip = (pair >= 0) & (pair != lab) & ~locked
        lab[flip] = pair[flip]
    area = _areas(p)
    edges = np.column_stack([np.repeat(np.arange(len(lab)), 3), nb.ravel()])
    edges = edges[edges[:, 1] >= 0]
    for _ in range(4):
        same = edges[lab[edges[:, 0]] == lab[edges[:, 1]]]
        g = coo_matrix((np.ones(len(same)), (same[:, 0], same[:, 1])), shape=(len(lab), len(lab)))
        _, comp = connected_components(g, directed=False)
        small = np.bincount(comp, weights=area) < MIN_ISLAND * area.sum()
        small &= ~np.bincount(comp, weights=locked, minlength=len(small)).astype(bool)
        if not small.any():
            break
        # border edges leaving a small patch vote for the colour on the other side
        out = edges[small[comp[edges[:, 0]]] & (comp[edges[:, 0]] != comp[edges[:, 1]])]
        if not len(out):
            break
        votes = coo_matrix((np.ones(len(out)), (comp[out[:, 0]], lab[out[:, 1]])),
                           shape=(comp.max() + 1, lab.max() + 1)).toarray()
        target = votes.argmax(1)
        move = small[comp] & (votes.sum(1) > 0)[comp] & ~locked
        lab[move] = target[comp[move]]
    return lab


# --- analysis --------------------------------------------------------------------------

_ANALYZE_CACHE: dict[tuple, dict[str, Any]] = {}


def analyze(path: Path, palette: Palette | None = None) -> dict[str, Any]:
    """Colours present in a model, most used first, with a suggested slot (1..4) for each.
    With ``palette`` the model is repainted with the loaded spools' colours (see _rgb_labels) and
    each colour's index is its slot. Cached per file version: one slicing asks for it several times."""
    st = path.stat()
    palette = tuple(palette) if palette and any(palette) else None
    key = (str(path.resolve()), st.st_mtime_ns, st.st_size, palette)
    if key not in _ANALYZE_CACHE:
        if len(_ANALYZE_CACHE) > 64:
            _ANALYZE_CACHE.clear()
        _ANALYZE_CACHE[key] = _analyze(path, palette)
    return copy.deepcopy(_ANALYZE_CACHE[key])


def _analyze(path: Path, palette: Palette | None = None) -> dict[str, Any]:
    pr = _load(path)
    parts = _parts(pr)
    painted = False
    if _rgb_mode(pr):
        centres, labels, detected = _rgb_labels(pr, palette)
        painted = bool(palette)
        share = np.zeros(len(centres))
        for p, lab in zip(parts, labels):
            share += np.bincount(lab, weights=_areas(p), minlength=len(centres))
        share /= share.sum() or 1
        found = [{"index": i + 1, "hex": _hex(centres[i]), "share": round(100 * share[i], 1)}
                 for i in range(len(centres)) if share[i] > 0.001]
        source = "couleurs du maillage"
    else:
        usage: Counter = Counter()
        for p in parts:
            areas = _areas(p)
            for k, a in enumerate(areas):
                code = p.paint[k] if p.paint else None
                states = paint_states(code) if code else {0}
                for st in states:
                    usage[p.extruder if st == 0 else st] += a / len(states)
        total = sum(usage.values()) or 1
        pal = pr.colours or []
        found = [{"index": i, "hex": pal[i - 1] if i <= len(pal) else colorize.PALETTE[(i - 1) % 4] if len(usage) > 1 else "#C0C0C0",
                  "share": round(100 * usage[i] / total, 1)} for i in sorted(usage) if usage[i] > 0]
        detected = len(found)
        source = "projet 3MF" if path.suffix.lower() == ".3mf" else "sans couleur"
    found.sort(key=lambda c: -c["share"])
    # suggestion: the 4 most used colours get their own slot, the rest join the nearest one
    for i, c in enumerate(found):
        if painted:                       # repainted with the spools: colour i is spool i
            c["slot"] = c["index"]
        elif i < MAX_SLOTS:
            c["slot"] = i + 1
        else:
            d = [((_rgb(c["hex"]) - _rgb(found[j]["hex"])) ** 2).sum() for j in range(MAX_SLOTS)]
            c["slot"] = int(np.argmin(d)) + 1
    return {"source": source, "colours": found, "detected": detected, "multicolour": len(found) > 1, "palette": painted}


# --- conversion -------------------------------------------------------------------------

FLUSH_MULTIPLIER = 0.3  # OrcaSlicer multiplies every volume below by this (CC2 profile)
FLUSH_MIN_MM3 = 60      # real purge for a change that hides itself (light -> dark, close colours)
FLUSH_UP_MM3 = 300      # extra real purge for a jump to a much lighter colour (dark/red -> white)
FLUSH_DIST_MM3 = 80     # extra real purge for very different hues
FLUSH_MAX = int(round((FLUSH_MIN_MM3 + FLUSH_UP_MM3 + FLUSH_DIST_MM3) / FLUSH_MULTIPLIER))   # "qualite": the worst case, every time


def _luminance(h: str) -> float:
    r, g, b = _rgb(h) / 255
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def flush_matrix(colours: list[str], smart: bool = True) -> list[int]:
    """Purge volume for every filament change, row = from, column = to (OrcaSlicer units, before ×0.3).

    Going from a light to a dark colour hides contamination, so it needs little purge; dark to light
    needs the most. Sized in real mm³ after OrcaSlicer's 0.3 multiplier: red -> white gets ~330 mm³.
    The former curve gave ~70 mm³ there, and a red/white print came out marbled pink with white blobs
    at each change (2026-11-11). ``smart=False`` purges the worst case at every change."""
    n = len(colours)
    out = []
    for i in range(n):
        for j in range(n):
            if i == j:
                out.append(0)
            elif not smart:
                out.append(FLUSH_MAX)
            else:
                up = max(0.0, _luminance(colours[j]) - _luminance(colours[i]))
                dist = float(np.linalg.norm(_rgb(colours[i]) - _rgb(colours[j]))) / 441.7
                real = FLUSH_MIN_MM3 + FLUSH_UP_MM3 * up + FLUSH_DIST_MM3 * dist
                out.append(int(round(real / FLUSH_MULTIPLIER)))
    return out


COPY_GAP_MM = 8.0
EXCLUDE = (246.0, 0.0, 256.0, 20.0)  # CC2 bed_exclude_area (x0, y0, x1, y1): front-right corner


def avoid_exclude(lo: np.ndarray, hi: np.ndarray, offset: np.ndarray) -> np.ndarray:
    """Shift a centred layout off the bed's no-print corner, or refuse when it cannot be avoided."""
    x0, y0, x1, y1 = EXCLUDE
    a, b = lo[:2] + offset[:2], hi[:2] + offset[:2]
    if b[0] <= x0 or a[1] >= y1:
        return offset
    out = offset.copy()
    if a[0] - (b[0] - x0) >= 0:          # slide left
        out[0] -= b[0] - x0
    elif b[1] + (y1 - a[1]) <= mesh.BED_MM:  # or slide back
        out[1] += y1 - a[1]
    else:
        raise ValueError("le modèle déborderait sur le coin avant droit du plateau, où la CC2 n'imprime pas : "
                         "réduis la taille ou le nombre d'exemplaires")
    return out


def rotation(rotate: tuple[float, ...] | None) -> np.ndarray | None:
    """3x3 matrix for rotations about X, then Y, then Z (degrees), then an optional scale along the plate's
    axes ``rotate[3:6]`` (1 = unchanged, negative = mirrored); None when there is nothing to do.
    A mirrored matrix has a negative determinant: callers flip the faces with ``flip_if_mirrored``."""
    if not rotate:
        return None
    angles, scale = tuple(rotate[:3]) + (0,) * (3 - len(rotate[:3])), tuple(rotate[3:6]) + (1,) * (3 - len(rotate[3:6]))
    if not any(angles) and all(k == 1 for k in scale):
        return None
    if any(k == 0 for k in scale):
        raise ValueError("une échelle ne peut pas être nulle")
    rx, ry, rz = (np.radians(a) for a in angles)
    cx, sx, cy, sy, cz, sz = np.cos(rx), np.sin(rx), np.cos(ry), np.sin(ry), np.cos(rz), np.sin(rz)
    mx = np.array([[1, 0, 0], [0, cx, -sx], [0, sx, cx]])
    my = np.array([[cy, 0, sy], [0, 1, 0], [-sy, 0, cy]])
    mz = np.array([[cz, -sz, 0], [sz, cz, 0], [0, 0, 1]])
    return np.round(np.diag(scale) @ mz @ my @ mx, 12)   # scale last: X/Y/Z are the plate's axes


def flip_if_mirrored(rot: np.ndarray | None, faces: np.ndarray) -> np.ndarray:
    """A mirror turns the surface inside out: swap two corners of each triangle so normals point out again
    (corner 0 stays first, which painted 3MF triangles key their subdivision on)."""
    return faces[:, [0, 2, 1]] if rot is not None and np.linalg.det(rot) < 0 else faces


def grid(footprint: tuple[float, float], copies: int, bed: float = mesh.BED_MM) -> list[tuple[float, float]]:
    """Offsets (x, y) of ``copies`` copies laid out in rows on the bed, or ValueError if they do not fit."""
    w, d = footprint
    per_row = max(0, int((bed + COPY_GAP_MM) // (w + COPY_GAP_MM)))
    per_col = max(0, int((bed + COPY_GAP_MM) // (d + COPY_GAP_MM)))
    if per_row * per_col < copies:
        raise ValueError(f"{copies} exemplaires de largeur {w:.0f} × profondeur {d:.0f} mm ne tiennent pas sur le plateau "
                         f"(maximum {per_row * per_col}) : réduis la taille ou le nombre")
    return [((i % per_row) * (w + COPY_GAP_MM), (i // per_row) * (d + COPY_GAP_MM)) for i in range(copies)]


def to_canvas(path: Path, out: Path, mapping: dict[int, int], *, height_mm: float | None = None,
              smart_flush: bool = True, rotate: tuple[float, ...] | None = None,
              copies: int = 1, palette: Palette | None = None, simplify: float = 0.0, layer_mm: float = 0.2,
              moves: dict[int, tuple[float, float, float]] | None = None,
              shift: tuple[float, float] | None = None, marks_from: Path | None = None,
              scales: dict[int, float] | None = None, real_colours: dict[int, str] | None = None,
              ordre: str | None = None) -> dict[str, Any]:
    """Write a clean CANVAS 3MF where source colour ``i`` prints from slot ``mapping[i]`` (1..4),
    centred on the bed, optionally rotated, rescaled to ``height_mm`` and repeated ``copies`` times.
    ``moves``: object index -> translation in the model's own axes (pieces dragged apart in the viewer);
    ``shift``: where the middle of the result sits, from the bed centre (None = centred);
    ``scales``: object index -> size factor, about the bottom centre of that object as it lies on the plate;
    ``marks_from``: the model whose painted supports and seam apply (``path`` itself when None);
    ``real_colours``: slot -> colour of the spool really loaded: the purge follows what goes through the nozzle;
    ``ordre``: 'suite' asks for one piece at a time (see _piece_par_piece)."""
    if any(not 1 <= s <= MAX_SLOTS for s in mapping.values()):
        raise ValueError("chaque couleur doit aller dans une bobine de 1 à 4")
    info = analyze(path, palette)
    n = max(mapping.values()) if mapping else 1
    slot_hex = []
    for slot in range(1, n + 1):
        members = [c for c in info["colours"] if mapping.get(c["index"]) == slot]
        slot_hex.append(max(members, key=lambda c: c["share"])["hex"] if members else colorize.PALETTE[slot - 1])

    pr = _load(path)
    for k, d in (moves or {}).items():
        if 0 <= k < len(pr.objects):
            for p in pr.objects[k].parts:
                p.vertices = p.vertices + np.asarray(d, float)
    parts = _parts(pr)
    _apply_marks(marks_from or path, parts)   # faces follow the model's order here, as in the viewer
    rgb = _rgb_mode(pr)      # asked once: the colours per face are replaced by paint codes below
    if rgb:
        _, labels, _ = _rgb_labels(pr, palette)
        codes = {s: encode_state(s) for s in range(1, MAX_SLOTS + 1)}
        face_states = []
        for p, lab in zip(parts, labels):
            states = np.array([mapping.get(int(label) + 1, 1) for label in lab])
            p.extruder = int(np.bincount(states).argmax())
            p.paint = [codes[int(s)] for s in states]
            p.face_rgb = None
            face_states.append(states)
    else:
        for p in parts:
            p.extruder = mapping.get(p.extruder, 1)
            if p.paint:
                p.paint = [remap_paint(c, mapping) if c else None for c in p.paint]

    rot = rotation(rotate)
    if rot is not None:
        for p in parts:
            p.vertices, p.faces = p.vertices @ rot.T, flip_if_mirrored(rot, p.faces)
    allv = np.vstack([p.vertices for p in parts])
    if height_mm:
        k = height_mm / float(np.ptp(allv[:, 2]) or 1)
        for p in parts:
            p.vertices = p.vertices * k
        allv = allv * k
    for k, f in (scales or {}).items():   # one piece bigger or smaller: it stays where it stood, on the plate
        if 0 <= k < len(pr.objects) and f != 1:
            v = np.vstack([p.vertices for p in pr.objects[k].parts])
            a, b = v.min(0), v.max(0)
            c = np.array([(a[0] + b[0]) / 2, (a[1] + b[1]) / 2, a[2]])
            for p in pr.objects[k].parts:
                p.vertices = c + (p.vertices - c) * f
    if scales:
        allv = np.vstack([p.vertices for p in parts])
    lo, hi = allv.min(0), allv.max(0)
    if (hi - lo)[:2].max() > mesh.BED_MM or (hi - lo)[2] > mesh.BED_MM:
        raise ValueError(f"le modèle ({mesh.size_text(hi - lo)}) dépasse le volume de {mesh.BED_MM:.0f} mm")
    simplified = 0
    if simplify > 0 and rgb:   # placed and scaled now: layers are known
        simplified = simplify_layers(parts, face_states, layer_mm, simplify)
        for p, states in zip(parts, face_states):
            p.paint = [codes[int(x)] for x in states]
            p.extruder = int(np.bincount(states).argmax())
    if copies > 1:  # repeat every object on a grid, then centre the whole grid
        spots = grid((float(hi[0] - lo[0]), float(hi[1] - lo[1])), copies)
        objects = []
        for k, (dx, dy) in enumerate(spots):
            for o in pr.objects:
                objects.append(threemf.Object(f"{o.name} #{k + 1}", [
                    threemf.Part(p.name, p.vertices + [dx, dy, 0], p.faces, p.extruder, p.paint, p.face_rgb,
                                 supports=p.supports, seam=p.seam) for p in o.parts]))
        pr = threemf.Project(objects, pr.colours)
        hi = hi + [max(x for x, _ in spots), max(y for _, y in spots), 0]
    sx, sy = shift or (0.0, 0.0)
    offset = np.array([mesh.BED_MM / 2 + sx - (lo[0] + hi[0]) / 2, mesh.BED_MM / 2 + sy - (lo[1] + hi[1]) / 2, -lo[2]])
    if shift is None:
        offset = avoid_exclude(lo, hi, offset)
    elif any(lo[:2] + offset[:2] < 0) or any(hi[:2] + offset[:2] > mesh.BED_MM):
        raise ValueError("une pièce déplacée sort du plateau : rapproche-la")
    else:   # pieces placed by hand: none may sit on the corner where the CC2 does not print
        x0, y0, x1, y1 = EXCLUDE
        for o in pr.objects:
            v = np.vstack([p.vertices for p in o.parts])[:, :2] + offset[:2]
            if ((v[:, 0] > x0) & (v[:, 1] < y1)).any():
                raise ValueError("une pièce déplacée touche le coin avant droit du plateau, où la CC2 n'imprime pas : "
                                 "éloigne-la de ce coin (en rouge dans la vue 3D)")
    endroit = _piece_par_piece(pr, offset) if ordre == "suite" else None
    tower = None if endroit else (tower_spot(lo[:2] + offset[:2], hi[:2] + offset[:2]) if n > 1 else None)
    threemf.write(pr, out, filaments=n, colours=slot_hex, offset=offset, flush=flush_matrix([(real_colours or {}).get(i + 1, h) for i, h in enumerate(slot_hex)], smart_flush), tower=tower)
    return {"file": out.name, "filaments": n, "slot_colours": slot_hex, "simplified": simplified, "ordre": endroit}


def _colour_key(o: threemf.Object) -> tuple[int, ...]:
    """The spools a piece prints with: its own extruder and every colour its paint uses."""
    s = {p.extruder for p in o.parts} | {st for p in o.parts for c in p.paint or [] if c for st in paint_states(c)}
    return tuple(sorted(s - {0}))


def _piece_par_piece(pr: threemf.Project, offset: np.ndarray) -> str | None:
    """Print one piece entirely before the next ('by object'), pieces grouped by their colours: one
    change per colour around the plate instead of one change at nearly every layer. OrcaSlicer's
    command line accepts any layout — even one the print head would hit — so the CC2's own
    clearances are checked here. Returns None when the pieces all wear the same colours (layer
    by layer, they share each change) or when there is nothing to reorder.

    The piece order is the 3MF's object order, and pieces sharing a colour end up side by side:
    a spool prints every piece that wants it, then the next spool takes over."""
    if len(pr.objects) < 2:
        return "seule"
    keys = [_colour_key(o) for o in pr.objects]
    if len(set(keys)) == 1:
        return "meme"
    radius, height = slicer.clearances()
    boxes = []
    for o, k in zip(pr.objects, keys):
        label = o.name.split(" · ")[-1]
        v = np.vstack([p.vertices for p in o.parts]) + offset if o.parts else np.zeros((1, 3)) + offset
        lo, hi = v.min(0), v.max(0)
        if hi[2] - lo[2] > height + 1e-3:
            raise ValueError(f"Pièce par pièce : « {label} » fait {hi[2] - lo[2]:.0f} mm de haut, plus que les {height:.0f} mm "
                             f"que la tête peut survoler en allant à la pièce suivante : imprime-la à part, ou en couche par couche.")
        boxes.append((o, k, label, lo, hi))
    for (_oa, _, na, la, ha), (_ob, _, nb, lb, hb) in itertools.combinations(boxes, 2):
        dx = max(lb[0] - ha[0], la[0] - hb[0], 0.0)
        dy = max(lb[1] - ha[1], la[1] - hb[1], 0.0)
        gap = (dx * dx + dy * dy) ** 0.5
        if gap + 1e-3 < radius:
            raise ValueError(f"Pièce par pièce : « {na} » et « {nb} » ne sont qu'à {gap:.0f} mm l'une de l'autre, et il en faut "
                             f"{radius:.0f} : en imprimant l'une la tête passe sur l'autre, déjà finie. Écarte les pièces "
                             f"en mode Déplacer, ou reviens en couche par couche.")
    order = sorted(range(len(pr.objects)), key=lambda i: (keys[i], i))
    pr.objects = [pr.objects[i] for i in order]
    return "suite"


TOWER_W, TOWER_D = 20.0, 12.0   # printprep.TOWER's 20 mm width; about 11 mm deep on a small model
TOWER_GAP = 20.0                # tower body to part: the part's brim (6 mm) + the tower's (8 mm) + a margin


def tower_spot(lo: np.ndarray, hi: np.ndarray) -> tuple[float, float] | None:
    """Front-left corner of the prime tower, beside the part instead of Elegoo's back-left corner (X 15, Y 220):
    every colour change travels to it, so a long trip across the bed means strings and lost time. Left of the
    part, else right of it; None (the profile's place) when neither side has room."""
    y = float(np.clip((lo[1] + hi[1]) / 2 - TOWER_D / 2, 15, mesh.BED_MM - 15 - TOWER_D))
    left = float(lo[0]) - TOWER_GAP - TOWER_W
    if left >= 15:
        return round(left, 1), round(y, 1)
    right = float(hi[0]) + TOWER_GAP
    if right + TOWER_W <= mesh.BED_MM - 15 and not (right + TOWER_W > EXCLUDE[0] and y < EXCLUDE[3] + 8):
        return round(right, 1), round(y, 1)
    return None


SIMPLIFY_SHARE = 0.03   # a colour under 3 % of a layer's surface is a speck nobody sees, yet a whole change and purge
# measured 2026-11-11 on a 3-colour AI model lying flat (~200 changes): 3 % -> 2 fewer, 10 % -> 30, 15 % -> 65 (visible)
SIMPLIFY_LEVELS = {"non": 0.0, "leger": SIMPLIFY_SHARE, "fort": 0.10}


def simplify_layers(parts: list[threemf.Part], states: list[np.ndarray], layer_mm: float, share: float) -> int:
    """Fewer colour changes: in each layer, a colour covering under ``share`` of that layer's surface takes the
    layer's main colour. Every colour present in a layer costs one filament change (and its purge) there;
    on an AI model a third of them are specks (measured 2026-11-11: 28 of 88 changes). Faces painted by hand
    stay as they are. Changes ``states`` in place; returns how many (layer, colour) changes were saved."""
    zc = np.concatenate([p.vertices[p.faces][:, :, 2].mean(1) for p in parts])
    area = np.concatenate([_areas(p) for p in parts])
    st = np.concatenate(states)
    locked = np.concatenate([p.locked if p.locked is not None else np.zeros(len(p.faces), bool) for p in parts])
    band = np.floor((zc - zc.min()) / max(layer_mm, 0.05)).astype(int)
    saved = 0
    order = np.argsort(band, kind="stable")
    bounds = np.flatnonzero(np.diff(band[order])) + 1
    for idx in np.split(order, bounds):
        a = np.bincount(st[idx], weights=area[idx], minlength=MAX_SLOTS + 1)
        if (a > 0).sum() < 2:
            continue
        main = int(a.argmax())
        for c in np.flatnonzero((a > 0) & (a < share * a.sum())):
            own = idx[st[idx] == c]
            if locked[own].any():
                continue
            st[own] = main
            saved += 1
    i = 0
    for k, s_ in enumerate(states):
        states[k][:] = st[i:i + len(s_)]
        i += len(s_)
    return saved


# --- preview ----------------------------------------------------------------------------

def preview(path: Path, mapping: dict[int, int] | None = None, palette: Palette | None = None) -> trimesh.Trimesh:
    """One mesh coloured as it will print: each face takes the colour of its CANVAS slot.

    Returned Y-up (glTF convention) so the web viewer treats every format the same way."""
    info = analyze(path, palette)
    slots = {c["index"]: (mapping or {}).get(c["index"], c["slot"]) for c in info["colours"]}
    slot_rgb: dict[int, np.ndarray] = {}
    for s in set(slots.values()):
        best = max((c for c in info["colours"] if slots[c["index"]] == s), key=lambda c: c["share"])
        slot_rgb[s] = _rgb(best["hex"])
    pr = _load(path)
    parts = _parts(pr)
    if _rgb_mode(pr):
        _, labels, _ = _rgb_labels(pr, palette)
        idx = [lab + 1 for lab in labels]
    else:
        idx = []
        for p in parts:
            first = [(min(paint_states(c) - {0}, default=0) if c else 0) for c in p.paint] if p.paint else [0] * len(p.faces)
            idx.append(np.array([p.extruder if st == 0 else st for st in first]))
    grey = np.array([200.0, 200.0, 200.0])
    verts, faces, cols, off = [], [], [], 0
    for p, ix in zip(parts, idx):
        verts.append(p.vertices)
        faces.append(p.faces + off)
        off += len(p.vertices)
        cols.append(np.array([slot_rgb.get(slots.get(int(i), 0), grey) for i in ix]))
    v = np.vstack(verts)
    v = np.c_[v[:, 0], v[:, 2], -v[:, 1]]  # Z-up -> Y-up
    rgba = np.c_[np.vstack(cols), np.full(sum(len(f) for f in faces), 255)].astype(np.uint8)
    return trimesh.Trimesh(v, np.vstack(faces), face_colors=rgba, process=False)


def piece_ranges(path: Path) -> list[dict[str, Any]]:
    """Per object: its name and the face range it takes in ``preview_glb`` (faces follow object order)."""
    out, first = [], 0
    for o in _load(path).objects:
        n = sum(len(p.faces) for p in o.parts)
        out.append({"name": o.name, "first": first, "count": n})
        first += n
    return out


def _preview_corners(path: Path, mapping: dict[int, int] | None, palette: Palette | None
                     ) -> tuple[np.ndarray, np.ndarray, np.ndarray | None]:
    """Corner positions (3 per face, in face order), their RGBA, and normals smoothed over the real surface
    (None when welding changes the face count)."""
    m = preview(path, mapping, palette)
    v, f = np.asarray(m.vertices, float), np.asarray(m.faces)
    rgba = np.asarray(m.visual.face_colors)
    welded = trimesh.Trimesh(v, f, process=False)
    welded.merge_vertices()
    normals = welded.vertex_normals[welded.faces].reshape(-1, 3) if len(welded.faces) == len(f) else None
    return v[f.reshape(-1)], np.repeat(rgba, 3, axis=0), normals


def preview_glb(path: Path, mapping: dict[int, int] | None = None, palette: Palette | None = None) -> trimesh.Trimesh:
    """``preview`` for the viewer: triangle ``i`` is face ``i`` of the model (so a brush can name faces), each
    corner is its own vertex (crisp colour edges), normals are smoothed over the real surface."""
    pos, rgba, normals = _preview_corners(path, mapping, palette)
    out = trimesh.Trimesh(pos, np.arange(len(pos)).reshape(-1, 3), process=False)
    out.visual = trimesh.visual.ColorVisuals(out, vertex_colors=rgba)
    if normals is not None:
        out.vertex_normals = normals
    return out


def preview_glb_bytes(path: Path, mapping: dict[int, int] | None = None, palette: Palette | None = None) -> bytes:
    """``preview_glb`` written compactly: no index (it was the identity), normals on one byte per axis
    (KHR_mesh_quantization). 20 bytes a corner instead of 32: a 600k-face model drops from 59 to 37 MB."""
    pos, rgba, normals = _preview_corners(path, mapping, palette)
    n = len(pos)
    views, accessors, attrs, blobs, offset = [], [], {}, [], 0

    def add(name: str, data: np.ndarray, kind: str, ctype: int, stride: int | None = None, **extra: Any) -> None:
        nonlocal offset
        raw = np.ascontiguousarray(data).tobytes()
        views.append({"buffer": 0, "byteOffset": offset, "byteLength": len(raw), "target": 34962,
                      **({"byteStride": stride} if stride else {})})
        accessors.append({"bufferView": len(views) - 1, "componentType": ctype, "count": n, "type": kind, **extra})
        attrs[name] = len(accessors) - 1
        blobs.append(raw)
        offset += len(raw)

    p32 = pos.astype(np.float32)
    add("POSITION", p32, "VEC3", 5126, min=p32.min(0).tolist() if n else [0, 0, 0],
        max=p32.max(0).tolist() if n else [0, 0, 0])
    add("COLOR_0", rgba.astype(np.uint8), "VEC4", 5121, normalized=True)
    used = []
    if normals is not None:   # signed bytes, each padded to 4 (vertex attributes are 4-byte aligned)
        q = np.zeros((n, 4), np.int8)
        q[:, :3] = np.clip(np.round(normals * 127), -127, 127)
        add("NORMAL", q, "VEC3", 5120, stride=4, normalized=True)
        used = ["KHR_mesh_quantization"]
    gltf = {"asset": {"version": "2.0", "generator": "atelier-cc2"}, "scene": 0, "scenes": [{"nodes": [0]}],
            "nodes": [{"mesh": 0}], "meshes": [{"primitives": [{"attributes": attrs, "mode": 4}]}],
            "accessors": accessors, "bufferViews": views, "buffers": [{"byteLength": offset}],
            **({"extensionsUsed": used, "extensionsRequired": used} if used else {})}
    js = json.dumps(gltf, separators=(",", ":")).encode()
    js += b" " * (-len(js) % 4)
    body = b"".join(blobs)
    body += b"\0" * (-len(body) % 4)
    head = struct.pack("<4sII", b"glTF", 2, 12 + 8 + len(js) + 8 + len(body))
    return head + struct.pack("<I4s", len(js), b"JSON") + js + struct.pack("<I4s", len(body), b"BIN\0") + body


def solid(path: Path, mapping: dict[int, int], *, height_mm: float | None = None,
          rotate: tuple[float, ...] | None = None, palette: Palette | None = None
          ) -> tuple[np.ndarray, np.ndarray, np.ndarray, list[str]]:
    """The whole model as one mesh in printer axes (mm, resting on Z=0) with a CANVAS slot per face,
    plus the colour of each slot. Used to cut models bigger than the bed."""
    info = analyze(path, palette)
    n = max(mapping.values()) if mapping else 1
    slot_hex = []
    for slot in range(1, n + 1):
        members = [c for c in info["colours"] if mapping.get(c["index"]) == slot]
        slot_hex.append(max(members, key=lambda c: c["share"])["hex"] if members else colorize.PALETTE[slot - 1])
    pr = _load(path)
    parts = _parts(pr)
    if _rgb_mode(pr):
        _, labels, _ = _rgb_labels(pr, palette)
        per = [np.array([mapping.get(int(label) + 1, 1) for label in lab]) for lab in labels]
    else:
        per = []
        for p in parts:
            first = [(min(paint_states(c) - {0}, default=0) if c else 0) for c in p.paint] if p.paint else [0] * len(p.faces)
            per.append(np.array([mapping.get(p.extruder if st == 0 else st, 1) for st in first]))
    v, f, off = [], [], 0
    for p in parts:
        v.append(p.vertices)
        f.append(p.faces + off)
        off += len(p.vertices)
    v = np.vstack(v)
    rot = rotation(rotate)
    if rot is not None:
        v = v @ rot.T
    if height_mm:
        v = v * (height_mm / float(np.ptp(v[:, 2]) or 1))
    v = v - v.min(0)
    return v, flip_if_mirrored(rot, np.vstack(f)), np.concatenate(per), slot_hex


def write_piece(v: np.ndarray, f: np.ndarray, slots: np.ndarray, slot_hex: list[str], out: Path, *,
                name: str, smart_flush: bool = True) -> None:
    """One cut piece as a centred CANVAS 3MF (per-triangle paint, same slots as the whole model)."""
    n = len(slot_hex)
    codes = {s: encode_state(s) for s in range(1, MAX_SLOTS + 1)}
    part = threemf.Part(name, v, f, int(np.bincount(slots).argmax()), [codes[int(s)] for s in slots])
    lo, hi = v.min(0), v.max(0)
    offset = np.array([mesh.BED_MM / 2 - (lo[0] + hi[0]) / 2, mesh.BED_MM / 2 - (lo[1] + hi[1]) / 2, -lo[2]])
    offset = avoid_exclude(lo, hi, offset)
    # same as write_plate: the prime tower's place must be told to OrcaSlicer, or it picks its own
    tower = tower_spot((lo[:2] + offset[:2]), (hi[:2] + offset[:2])) if n > 1 else None
    threemf.write(threemf.Project([threemf.Object(name, [part])], slot_hex), out, filaments=n,
                  colours=slot_hex, offset=offset, flush=flush_matrix(slot_hex, smart_flush), tower=tower)


def write_plate(items: list[tuple[str, np.ndarray, np.ndarray, np.ndarray | None]], slot_hex: list[str], out: Path, *,
                smart_flush: bool = True, gap: float = COPY_GAP_MM) -> None:
    """Several small parts on one plate: ``items`` = (name, vertices, faces, slot per face or None for slot 1).
    Shelf packing from the back-left corner; ValueError if they do not fit.

    A multicolour plate prints a prime tower, and the tower's place must be in the file: with none
    OrcaSlicer puts it where it likes, and on a plate that fills the bed width it chose the corner the
    CC2 cannot print (246-256 x 0-20 mm), so the slice ended in error -102 after slicing it."""
    n = len(slot_hex)
    codes = {s: encode_state(s) for s in range(1, MAX_SLOTS + 1)}
    usable_x = (mesh.BED_MM - 15 - TOWER_W - TOWER_GAP) if n > 1 else (mesh.BED_MM - 10)   # room for the tower
    usable_y = mesh.BED_MM - EXCLUDE[3] - 10
    order = sorted(items, key=lambda it: -float(np.ptp(it[1][:, 1])))
    objects, x, y, shelf = [], 5.0, EXCLUDE[3] + 5.0, 0.0
    for name, v, f, slots in order:
        lo, hi = v.min(0), v.max(0)
        w, d = hi[0] - lo[0], hi[1] - lo[1]
        if x + w > usable_x:
            x, y, shelf = 5.0, y + shelf + gap, 0.0
        if y + d > usable_y + EXCLUDE[3] + 5 or w > usable_x:
            raise ValueError("les petites pièces ne tiennent pas sur un seul plateau")
        placed = v - lo + [x, y, 0]
        paint = [codes[int(sl)] for sl in slots] if slots is not None else None
        extruder = int(np.bincount(slots.astype(int)).argmax()) if slots is not None else 1
        objects.append(threemf.Object(name, [threemf.Part(name, placed, f, extruder, paint)]))
        x += w + gap
        shelf = max(shelf, d)
    allv = np.vstack([p.vertices for o in objects for p in o.parts])
    tower = tower_spot(allv.min(0)[:2], allv.max(0)[:2]) if n > 1 else None
    threemf.write(threemf.Project(objects, slot_hex), out, filaments=n, colours=slot_hex,
                  offset=np.zeros(3), flush=flush_matrix(slot_hex, smart_flush), tower=tower)
