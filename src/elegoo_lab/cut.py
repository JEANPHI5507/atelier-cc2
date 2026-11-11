"""Cut a model that is too big for the 256 mm bed into pieces joined by dowel pins.

Pipeline: the model (printer axes, mm, one filament slot per face) becomes a manifold solid; dowel
holes are drilled across every cut plane, then the solid is split. Each piece gets its colours
back from the nearest original face, and the dowels are produced as a separate small part.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import manifold3d as mf
import numpy as np
import trimesh
from scipy.spatial import ConvexHull, QhullError, cKDTree

from . import config, mesh

MARGIN_MM = 10.0        # keep pieces comfortably inside the bed
PIN_D = 5.0             # dowel diameter
PIN_DEPTH = 8.0         # hole depth on each side of a cut
PIN_DEPTH_SHORT = 5.0   # fallback where 8 mm would break through a thin wall
PIERCE_TOLERANCE = 0.01 # share of a hole allowed outside the material (mesh noise)
# radial play of the holes: config.dowel_play(), tuned with the dowel test piece
WALL = 2.0              # material kept between a hole and the outer surface


@dataclass
class Piece:
    name: str
    vertices: np.ndarray
    faces: np.ndarray
    slots: np.ndarray      # filament slot (1..4) per face


@dataclass
class CutResult:
    pieces: list[Piece]
    pins: trimesh.Trimesh | None
    planes: list[tuple[int, float]]   # (axis, position mm)
    pin_count: int
    pin_depths: list[float] = field(default_factory=list)


def _to_manifold(v: np.ndarray, f: np.ndarray) -> mf.Manifold:
    solid = mf.Manifold(mf.Mesh(vert_properties=np.asarray(v, np.float32), tri_verts=np.asarray(f, np.uint32)))
    if solid.status() != mf.Error.NoError or solid.is_empty():
        m = trimesh.Trimesh(v, f)
        m.merge_vertices()
        trimesh.repair.fill_holes(m)
        trimesh.repair.fix_normals(m)
        solid = mf.Manifold(mf.Mesh(vert_properties=np.asarray(m.vertices, np.float32),
                                    tri_verts=np.asarray(m.faces, np.uint32)))
    if solid.status() != mf.Error.NoError or solid.is_empty():
        raise ValueError("le maillage n'est pas un volume fermé : impossible de le découper proprement")
    return solid


def _mesh(solid: mf.Manifold) -> tuple[np.ndarray, np.ndarray]:
    m = solid.to_mesh()
    return np.asarray(m.vert_properties)[:, :3].astype(float), np.asarray(m.tri_verts).astype(np.int64)


def _to_z(axis: int) -> np.ndarray:
    """3x4 transform bringing ``axis`` onto +Z (so slice() can cut along it)."""
    r = np.eye(3)
    if axis == 0:
        r = np.array([[0, 0, -1], [0, 1, 0], [1, 0, 0]], float)
    elif axis == 1:
        r = np.array([[1, 0, 0], [0, 0, -1], [0, 1, 0]], float)
    return np.c_[r, np.zeros(3)]


def _inside(points: np.ndarray, rings: list[np.ndarray]) -> np.ndarray:
    """Even-odd point-in-polygon over all rings (outer contours and holes alike)."""
    inside = np.zeros(len(points), bool)
    x, y = points[:, 0], points[:, 1]
    for ring in rings:
        xa, ya = ring[:, 0], ring[:, 1]
        xb, yb = np.roll(xa, -1), np.roll(ya, -1)
        for x1, y1, x2, y2 in zip(xa, ya, xb, yb):
            crosses = ((y1 > y) != (y2 > y)) & (x < (x2 - x1) * (y - y1) / ((y2 - y1) or 1e-12) + x1)
            inside ^= crosses
    return inside


def _pin_points(solid: mf.Manifold, axis: int, pos: float) -> np.ndarray:
    """Dowel positions (2D, in the rotated frame) spread over the cut section."""
    xf = _to_z(axis)
    rotated = solid.transform(xf)
    z = (xf[:, :3] @ np.eye(3)[axis])[2] * pos
    section = rotated.slice(z)
    inset = section.offset(-(PIN_D / 2 + config.dowel_play() + WALL), mf.JoinType.Round)
    rings = [np.asarray(r) for r in inset.to_polygons() if len(r) >= 3]
    if not rings:
        return np.zeros((0, 2))
    lo = np.min([r.min(0) for r in rings], axis=0)
    hi = np.max([r.max(0) for r in rings], axis=0)
    gx, gy = np.meshgrid(np.arange(lo[0], hi[0] + 1, 2.0), np.arange(lo[1], hi[1] + 1, 2.0))
    cand = np.c_[gx.ravel(), gy.ravel()]
    cand = cand[_inside(cand, rings)]
    if not len(cand):
        return np.zeros((0, 2))
    want = int(min(6, max(1, round(inset.area() / 1500))))
    chosen = [cand[np.argmin(np.linalg.norm(cand - cand.mean(0), axis=1))]]  # start near the centre
    while len(chosen) < want:
        d = np.min([np.linalg.norm(cand - c, axis=1) for c in chosen], axis=0)
        if d.max() < PIN_D * 3:
            break
        chosen.append(cand[np.argmax(d)])
    return np.asarray(chosen), z, xf


MIN_BASE_MM2 = 25.0     # a piece touching the bed with less than this is laid on its largest flat face


def rest_flat(v: np.ndarray, f: np.ndarray) -> tuple[np.ndarray, bool]:
    """Lay a piece that would stand on a point onto its largest flat face (usually the cut face)."""
    m = trimesh.Trimesh(v, f, process=False)
    foot = v[v[:, 2] < v[:, 2].min() + 1.0][:, :2]  # footprint: what touches (or almost) the bed
    try:
        area = ConvexHull(foot).volume if len(foot) >= 3 else 0.0  # 2-D hull "volume" is its area
    except QhullError:
        area = 0.0
    if area >= MIN_BASE_MM2 or not len(m.facets):
        return v, False
    normal = m.facets_normal[int(np.argmax(m.facets_area))]
    rot = trimesh.geometry.align_vectors(normal, [0, 0, -1])
    out = trimesh.transform_points(v, rot)
    return out - [0, 0, out[:, 2].min()], True


def plan(extent: np.ndarray, max_mm: float) -> list[tuple[int, int]]:
    """How many pieces along each axis: [(axis, count), ...] for axes that need cutting."""
    return [(a, math.ceil(e / max_mm)) for a, e in enumerate(extent) if e > max_mm]


STEP_MM = 2.0            # section profile resolution
MIN_PIECE_MM = 20.0      # no sliver pieces at the ends
ISLAND_PENALTY = 400.0   # mm² of extra cost per additional separate island cut through (spikes, fingers)
BALANCE = 0.3            # cost x (1 + BALANCE * offset/extent): offsets are at most half the extent → ≤ +15 %


def section_profile(solid: mf.Manifold, axis: int) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Positions along ``axis`` with the cut area (mm²) and number of separate islands there."""
    lo, hi = solid.bounding_box()[axis], solid.bounding_box()[axis + 3]
    rotated = solid.transform(_to_z(axis))
    pos = np.arange(lo + STEP_MM, hi - STEP_MM / 2, STEP_MM)
    area, islands = np.zeros(len(pos)), np.zeros(len(pos), int)
    for i, t in enumerate(pos):
        cs = rotated.slice(float(t))
        area[i] = cs.area()
        islands[i] = len(cs.decompose()) if area[i] > 0 else 0
    return pos, area, islands


def best_planes(solid: mf.Manifold, axis: int, count: int, max_mm: float) -> list[float]:
    """``count - 1`` cut positions keeping every piece <= max_mm, at the most discreet places:
    smallest section (neck, waist) and fewest islands cut through."""
    lo, hi = solid.bounding_box()[axis], solid.bounding_box()[axis + 3]
    pos, area, islands = section_profile(solid, axis)
    cost = area + ISLAND_PENALTY * np.maximum(islands - 1, 0)
    cost[area <= 0] = np.inf  # never cut through empty space between parts (no gain, no dowel)
    ok = (pos - lo >= MIN_PIECE_MM) & (hi - pos >= MIN_PIECE_MM)
    cost[~ok] = np.inf
    n, k = len(pos), count - 1
    # mild preference for balanced pieces (≤ +15 % far from even spacing): a real narrowing still wins
    ideal = [lo + (hi - lo) * (c + 1) / count for c in range(k)]
    cost_at = [cost * (1 + BALANCE * np.abs(pos - ideal[c]) / (hi - lo)) for c in range(k)]
    best = np.full((k, n), np.inf)
    back = np.full((k, n), -1, int)
    best[0] = np.where(pos - lo <= max_mm, cost_at[0], np.inf)
    for c in range(1, k):
        for j in range(n):
            if not np.isfinite(cost[j]):
                continue
            prev = np.where((pos[j] - pos <= max_mm) & (pos < pos[j] - MIN_PIECE_MM))[0]
            if len(prev):
                i = prev[np.argmin(best[c - 1, prev])]
                best[c, j], back[c, j] = best[c - 1, i] + cost_at[c][j], i
    last = np.where(hi - pos <= max_mm, best[k - 1], np.inf)
    if not np.isfinite(last).any():  # no admissible sequence: fall back to even spacing
        return [lo + (hi - lo) * i / count for i in range(1, count)]
    j = int(np.argmin(last))
    out = [j]
    for c in range(k - 1, 0, -1):
        j = back[c, j]
        out.append(j)
    return sorted(float(pos[i]) for i in out)


def cut(v: np.ndarray, f: np.ndarray, slots: np.ndarray, *, max_mm: float = mesh.BED_MM - MARGIN_MM,
        name: str = "piece", smart: bool = True) -> CutResult:
    solid = _to_manifold(v, f)
    lo, hi = np.asarray(solid.bounding_box()[:3]), np.asarray(solid.bounding_box()[3:])
    planes = []
    for a, k in plan(hi - lo, max_mm):
        spots = best_planes(solid, a, k, max_mm) if smart else [lo[a] + (hi[a] - lo[a]) * i / k for i in range(1, k)]
        planes += [(a, p) for p in spots]
    if not planes:
        return CutResult([Piece(name, v, f, slots)], None, [], 0)

    # drill dowel holes across each plane (computed on the uncut solid)
    holes, pins = [], []  # pins: depth of each dowel's holes (mm on each side)
    r_hole = PIN_D / 2 + config.dowel_play()
    for axis, pos in planes:
        res = _pin_points(solid, axis, pos)
        if not isinstance(res, tuple):
            continue
        pts, z, xf = res
        inv = np.linalg.inv(np.r_[xf, [[0, 0, 0, 1]]])[:3]
        for p in pts:
            for depth in (PIN_DEPTH, PIN_DEPTH_SHORT):  # a hole must stay inside the material
                cyl = mf.Manifold.cylinder(2 * depth, r_hole, r_hole, 48).translate([p[0], p[1], z - depth]).transform(inv)
                if (cyl - solid).volume() <= PIERCE_TOLERANCE * cyl.volume():
                    holes.append(cyl)
                    pins.append(depth)
                    break
    if holes:
        solid = solid - mf.Manifold.batch_boolean(holes, mf.OpType.Add)

    pieces = [solid]
    for axis, pos in planes:
        normal = [0.0, 0.0, 0.0]
        normal[axis] = 1.0
        nxt = []
        for p in pieces:
            above, below = p.split_by_plane(normal, pos)
            nxt += [q for q in (below, above) if not q.is_empty()]
        pieces = nxt

    # a cut can leave detached bits (a spike tip): each connected part becomes its own piece
    pieces = [c for p in pieces for c in p.decompose() if c.volume() > 1.0]
    pieces.sort(key=lambda m: -m.volume())

    # colours back from the nearest original face
    tree = cKDTree(v[f].mean(axis=1))
    out = []
    for i, p in enumerate(pieces, 1):
        pv, pf = _mesh(p)
        _, near = tree.query(pv[pf].mean(axis=1))
        out.append(Piece(f"{name}_partie{i}", pv, pf, slots[near]))

    pin_mesh = None
    if pins:
        cols = math.ceil(math.sqrt(len(pins)))
        dowels = []
        for k, depth in enumerate(pins):  # each dowel matches its holes, 0.5 mm shorter at each end
            length = 2 * depth - 1.0
            one = trimesh.creation.cylinder(radius=PIN_D / 2, height=length, sections=48)
            dowels.append(one.apply_translation([(k % cols) * 9, (k // cols) * 9, length / 2]))
        pin_mesh = trimesh.util.concatenate(dowels)
    return CutResult(out, pin_mesh, planes, len(pins), pins)
