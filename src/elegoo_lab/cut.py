"""Cut a model that is too big for the 256 mm bed into pieces joined by dowel pins.

Pipeline: the model (printer axes, mm, one filament slot per face) becomes a manifold solid; dowel
holes are drilled across every cut plane, then the solid is split. Each piece gets its colours
back from the nearest original face, and the dowels are produced as a separate small part.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, cast

import manifold3d as mf
import numpy as np
import trimesh
from scipy.spatial import ConvexHull, QhullError, cKDTree

from . import config, mesh

if TYPE_CHECKING:
    from collections.abc import Sequence

MARGIN_MM = 10.0  # keep pieces comfortably inside the bed
PIN_D = 5.0  # dowel diameter
PIN_DEPTH = 8.0  # hole depth on each side of a cut
PIN_DEPTH_SHORT = 5.0  # fallback where 8 mm would break through a thin wall
PIERCE_TOLERANCE = 0.01  # share of a hole allowed outside the material (mesh noise)
# radial play of the holes: config.dowel_play(), tuned with the dowel test piece
WALL = 2.0  # material kept between a hole and the outer surface
MIN_WALL_MM = (
    1.2  # below this around a dowel hole, the wall is reported (and another depth tried first)
)

# A zone where no cut may pass: an axis-aligned box ((x0, y0, z0), (x1, y1, z1)); use +-inf for "any".
# Coordinates are the model's own: X and Y from the centre of its footprint, Z from its base (mm).
# A cut plane perpendicular to axis ``a`` at ``p`` crosses the box exactly when lo[a] <= p <= hi[a].
Zone = tuple[tuple[float, float, float], tuple[float, float, float]]
INF = float("inf")


def alert(kind: str, message: str, *, blocking: bool = False) -> dict[str, Any]:
    return {"type": kind, "message": message, "bloquante": blocking}


OBLIQUE_DEG = (15.0, -15.0, 30.0, -30.0)  # slanted cuts tried besides the aligned ones
OBLIQUE_GAIN = (
    0.9  # a slanted cut must beat the best aligned one by 10 %: aligned planes are steadier
)


@dataclass(frozen=True)
class Plane:
    """A cut plane ``normal . x = d``: perpendicular to ``axis``, or leaning ``angle`` degrees toward
    axis ``lean`` (-1 when aligned). ``pos`` is where it crosses the model's centre line along ``axis``.
    """

    axis: int
    pos: float
    d: float
    lean: int = -1
    angle: float = 0.0

    def normal(self) -> np.ndarray:
        n = np.zeros(3)
        n[self.axis] = math.cos(math.radians(self.angle))
        if self.lean >= 0:
            n[self.lean] = math.sin(math.radians(self.angle))
        return n

    def label(self, origin: np.ndarray) -> str:
        text = f"{'XYZ'[self.axis]} = {self.pos - origin[self.axis]:.0f} mm"
        if self.lean >= 0:
            text += f" (∠{self.angle:+g}° → {'XYZ'[self.lean]})"
        return text


def make_plane(axis: int, d: float, lean: int, angle: float, centre: np.ndarray) -> Plane:
    """The plane of offset ``d`` along its normal, with its crossing of the centre line worked out."""
    if lean < 0:
        return Plane(axis, float(d), float(d))
    c, s = math.cos(math.radians(angle)), math.sin(math.radians(angle))
    return Plane(axis, float((d - s * centre[lean]) / c), float(d), lean, float(angle))


@dataclass
class Piece:
    name: str
    vertices: np.ndarray
    faces: np.ndarray
    slots: np.ndarray  # filament slot (1..4) per face


@dataclass
class CutResult:
    pieces: list[Piece]
    pins: trimesh.Trimesh | None
    planes: list[tuple[int, float]]  # (axis, position mm)
    pin_count: int
    pin_depths: list[float] = field(default_factory=list)
    alerts: list[dict[str, Any]] = field(default_factory=list)
    cuts: list[Plane] = field(default_factory=list)  # the planes in full (slant included)


def _to_manifold(v: np.ndarray, f: np.ndarray) -> mf.Manifold:
    solid = mf.Manifold(
        mf.Mesh(vert_properties=np.asarray(v, np.float32), tri_verts=np.asarray(f, np.uint32))
    )
    if solid.status() != mf.Error.NoError or solid.is_empty():
        m = trimesh.Trimesh(v, f)
        m.merge_vertices()
        trimesh.repair.fill_holes(m)
        trimesh.repair.fix_normals(m)
        solid = mf.Manifold(
            mf.Mesh(
                vert_properties=np.asarray(m.vertices, np.float32),
                tri_verts=np.asarray(m.faces, np.uint32),
            )
        )
    if solid.status() != mf.Error.NoError or solid.is_empty():
        raise ValueError(
            "le maillage n'est pas un volume fermé : impossible de le découper proprement"
        )
    return solid


def _mesh(solid: mf.Manifold) -> tuple[np.ndarray, np.ndarray]:
    m = solid.to_mesh()
    return np.asarray(m.vert_properties)[:, :3].astype(float), np.asarray(m.tri_verts).astype(
        np.int64
    )


def _to_z(axis: int) -> np.ndarray:
    """3x4 transform bringing ``axis`` onto +Z (so slice() can cut along it)."""
    r = np.eye(3)
    if axis == 0:
        r = np.array([[0, 0, -1], [0, 1, 0], [1, 0, 0]], float)
    elif axis == 1:
        r = np.array([[1, 0, 0], [0, 0, -1], [0, 1, 0]], float)
    return cast("np.ndarray", np.c_[r, np.zeros(3)])


def _frame(axis: int, lean: int = -1, angle: float = 0.0) -> np.ndarray:
    """3x4 transform bringing the normal of that plane onto +Z."""
    if lean < 0:
        return _to_z(axis)
    n = Plane(axis, 0.0, 0.0, lean, angle).normal()
    return cast("np.ndarray", trimesh.geometry.align_vectors(n, [0, 0, 1])[:3, :4])


def _inside(points: np.ndarray, rings: list[np.ndarray]) -> np.ndarray:
    """Even-odd point-in-polygon over all rings (outer contours and holes alike)."""
    inside = np.zeros(len(points), bool)
    x, y = points[:, 0], points[:, 1]
    for ring in rings:
        xa, ya = ring[:, 0], ring[:, 1]
        xb, yb = np.roll(xa, -1), np.roll(ya, -1)
        for x1, y1, x2, y2 in zip(xa, ya, xb, yb, strict=False):
            crosses = ((y1 > y) != (y2 > y)) & (
                x < (x2 - x1) * (y - y1) / ((y2 - y1) or 1e-12) + x1
            )
            inside ^= crosses
    return inside


def _pin_points(
    solid: mf.Manifold, cut_plane: Plane
) -> tuple[np.ndarray, float, np.ndarray] | None:
    """Dowel positions (2D, in the plane's own frame) spread over the cut section."""
    xf = _frame(cut_plane.axis, cut_plane.lean, cut_plane.angle)
    rotated = solid.transform(xf)
    z = cut_plane.d
    section = rotated.slice(z)
    inset = section.offset(-(PIN_D / 2 + config.dowel_play() + WALL), mf.JoinType.Round)
    rings = [np.asarray(r) for r in inset.to_polygons() if len(r) >= 3]
    if not rings:
        return None
    lo = np.min([r.min(0) for r in rings], axis=0)
    hi = np.max([r.max(0) for r in rings], axis=0)
    gx, gy = np.meshgrid(np.arange(lo[0], hi[0] + 1, 2.0), np.arange(lo[1], hi[1] + 1, 2.0))
    cand = np.c_[gx.ravel(), gy.ravel()]
    cand = cand[_inside(cand, rings)]
    if not len(cand):
        return None
    want = int(min(6, max(1, round(inset.area() / 1500))))
    chosen = [cand[np.argmin(np.linalg.norm(cand - cand.mean(0), axis=1))]]  # start near the centre
    while len(chosen) < want:
        d = np.min([np.linalg.norm(cand - c, axis=1) for c in chosen], axis=0)
        if d.max() < PIN_D * 3:
            break
        chosen.append(cand[np.argmax(d)])
    return cast("np.ndarray", np.asarray(chosen)), z, xf


MIN_BASE_MM2 = 25.0  # a piece touching the bed with less than this is laid on its largest flat face


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


STEP_MM = 2.0  # section profile resolution
MIN_PIECE_MM = 20.0  # no sliver pieces at the ends
ISLAND_PENALTY = (
    400.0  # mm² of extra cost per additional separate island cut through (spikes, fingers)
)
BALANCE = 0.3  # cost x (1 + BALANCE * offset/extent): offsets are at most half the extent → ≤ +15 %


def _profile(
    solid: mf.Manifold, xf: np.ndarray
) -> tuple[np.ndarray, np.ndarray, np.ndarray, float, float]:
    """Slices along +Z of the transformed solid: offsets, area, islands, and the Z range."""
    rotated = solid.transform(xf)
    lo, hi = rotated.bounding_box()[2], rotated.bounding_box()[5]
    pos = np.arange(lo + STEP_MM, hi - STEP_MM / 2, STEP_MM)
    area, islands = np.zeros(len(pos)), np.zeros(len(pos), int)
    for i, t in enumerate(pos):
        cs = rotated.slice(float(t))
        area[i] = cs.area()
        islands[i] = len(cs.decompose()) if area[i] > 0 else 0
    return pos, area, islands, float(lo), float(hi)


def section_profile(solid: mf.Manifold, axis: int) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Positions along ``axis`` with the cut area (mm²) and number of separate islands there."""
    pos, area, islands, _, _ = _profile(solid, _to_z(axis))
    return pos, area, islands


def _hits(normal: np.ndarray, d: np.ndarray, zones: Sequence[Zone]) -> np.ndarray:
    """Which planes ``normal . x = d`` cross a forbidden box (min/max of n.x over the box)."""
    hit = np.zeros(len(d), bool)
    for lo, hi in zones:
        a = [
            normal[i] * (lo[i] if normal[i] > 0 else hi[i]) if normal[i] else 0.0 for i in range(3)
        ]
        b = [
            normal[i] * (hi[i] if normal[i] > 0 else lo[i]) if normal[i] else 0.0 for i in range(3)
        ]
        hit |= (d >= sum(a)) & (d <= sum(b))
    return hit


def _blocked(pos: np.ndarray, axis: int, zones: Sequence[Zone]) -> np.ndarray:
    return _hits(np.eye(3)[axis], pos, zones)


def _even(solid: mf.Manifold, axis: int, count: int) -> list[float]:
    lo, hi = solid.bounding_box()[axis], solid.bounding_box()[axis + 3]
    return [lo + (hi - lo) * i / count for i in range(1, count)]


def _dp(
    pos: np.ndarray,
    area: np.ndarray,
    islands: np.ndarray,
    lo: float,
    hi: float,
    count: int,
    max_mm: float,
    blocked: np.ndarray,
    weight: np.ndarray | None = None,
) -> tuple[list[float], float] | None:
    """The ``count - 1`` offsets keeping every piece <= max_mm at the most discreet places (smallest
    section, fewest islands), and the cost of that choice; None if no admissible sequence exists."""
    cost = area + ISLAND_PENALTY * np.maximum(islands - 1, 0)
    if weight is not None:
        cost = cost * weight  # a plane someone prefers is made cheap
    cost[area <= 0] = np.inf  # never cut through empty space between parts (no gain, no dowel)
    ok = (pos - lo >= MIN_PIECE_MM) & (hi - pos >= MIN_PIECE_MM)
    cost[~ok] = np.inf
    cost[blocked] = np.inf
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
    if not np.isfinite(last).any():
        return None
    j = int(np.argmin(last))
    total = float(last[j])
    out = [j]
    for c in range(k - 1, 0, -1):
        j = back[c, j]
        out.append(j)
    return sorted(float(pos[i]) for i in out), total


def search_planes(
    solid: mf.Manifold, axis: int, count: int, max_mm: float, forbidden: Sequence[Zone] = ()
) -> list[float] | None:
    """``count - 1`` aligned cut positions (see ``_dp``), outside the forbidden zones; None if none."""
    pos, area, islands, lo, hi = _profile(solid, _to_z(axis))
    found = _dp(pos, area, islands, lo, hi, count, max_mm, _blocked(pos, axis, forbidden))
    return found[0] if found else None


PREFER_MM = 4.0  # a preferred plane makes the offsets this close to it cheap
PREFER_WEIGHT = 0.05
AVOID_MM = 12.0  # an avoided plane rules out the offsets this close to it


def _wishes(
    pos: np.ndarray,
    axis: int,
    lean: int,
    angle: float,
    prefer: Sequence[Plane],
    avoid: Sequence[Plane],
) -> tuple[np.ndarray, np.ndarray, bool]:
    """Extra blocked offsets (near avoided planes of the same kind) and a cost weight (near preferred ones),
    and whether any preferred plane is of this kind."""
    same = lambda p: p.axis == axis and p.lean == lean and p.angle == angle  # noqa: E731
    blocked = np.zeros(len(pos), bool)
    weight = np.ones(len(pos))
    liked = [p for p in prefer if same(p)]
    for p in (q for q in avoid if same(q)):
        blocked |= np.abs(pos - p.d) < AVOID_MM
    for p in liked:
        weight[np.abs(pos - p.d) < PREFER_MM] = PREFER_WEIGHT
    return blocked, weight, bool(liked)


def _aligned_cost(
    solid: mf.Manifold,
    axis: int,
    count: int,
    max_mm: float,
    zones: Sequence[Zone],
    prefer: Sequence[Plane] = (),
    avoid: Sequence[Plane] = (),
) -> tuple[list[float], float] | None:
    pos, area, islands, lo, hi = _profile(solid, _to_z(axis))
    blocked, weight, _ = _wishes(pos, axis, -1, 0.0, prefer, avoid)
    return _dp(
        pos, area, islands, lo, hi, count, max_mm, _blocked(pos, axis, zones) | blocked, weight
    )


def _slanted(
    solid: mf.Manifold,
    axis: int,
    count: int,
    max_mm: float,
    zones: Sequence[Zone],
    lean: int,
    angle: float,
    centre: np.ndarray,
    prefer: Sequence[Plane] = (),
    avoid: Sequence[Plane] = (),
) -> tuple[list[Plane], float] | None:
    """Parallel planes leaning ``angle`` degrees toward axis ``lean``. A slab between two of them is taller
    than its thickness (``t / cos`` plus the climb across the model), so the thickness allowed is cut down.
    """
    ext = solid.bounding_box()[lean + 3] - solid.bounding_box()[lean]
    th = math.radians(abs(angle))
    eff = (max_mm - ext * math.tan(th)) * math.cos(th)
    if eff < MIN_PIECE_MM * 2:
        return None
    pos, area, islands, lo, hi = _profile(solid, _frame(axis, lean, angle))
    n = Plane(axis, 0.0, 0.0, lean, angle).normal()
    blocked, weight, _ = _wishes(pos, axis, lean, angle, prefer, avoid)
    found = _dp(pos, area, islands, lo, hi, count, eff, _hits(n, pos, zones) | blocked, weight)
    if found is None:
        return None
    return [make_plane(axis, d, lean, angle, centre) for d in found[0]], found[1]


@dataclass
class Candidate:
    """One possible cut plane with what it passes through: the section area there and its separate islands."""

    plane: Plane
    area: float
    islands: int
    cost: float


CAND_SPACING_MM = 25.0  # candidates on one axis stay at least this far apart


def _minima(
    pos: np.ndarray,
    area: np.ndarray,
    islands: np.ndarray,
    lo: float,
    hi: float,
    blocked: np.ndarray,
    how_many: int,
) -> list[tuple[float, float, int, float]]:
    """The cheapest cut offsets (cost = section + island penalty), spaced apart: (d, area, islands, cost)."""
    cost = area + ISLAND_PENALTY * np.maximum(islands - 1, 0)
    cost[area <= 0] = np.inf
    cost[~((pos - lo >= MIN_PIECE_MM) & (hi - pos >= MIN_PIECE_MM))] = np.inf
    cost[blocked] = np.inf
    out: list[tuple[float, float, int, float]] = []
    for i in np.argsort(cost):
        if not np.isfinite(cost[i]) or len(out) >= how_many:
            break
        if all(abs(pos[i] - o[0]) >= CAND_SPACING_MM for o in out):
            out.append((float(pos[i]), float(area[i]), int(islands[i]), float(cost[i])))
    return out


def candidate_planes(
    solid: mf.Manifold,
    axis: int,
    zones: Sequence[Zone],
    oblique: bool,
    centre: np.ndarray,
    per_axis: int = 5,
    slanted: int = 3,
) -> list[Candidate]:
    """Discreet places to cut along ``axis``: the cheapest aligned ones, and (if ``oblique``) the best slanted
    ones that beat the best aligned section by ``OBLIQUE_GAIN``."""
    pos, area, islands, lo, hi = _profile(solid, _to_z(axis))
    out = [
        Candidate(make_plane(axis, d, -1, 0.0, centre), a, n, c)
        for d, a, n, c in _minima(pos, area, islands, lo, hi, _blocked(pos, axis, zones), per_axis)
    ]
    if oblique and out:
        floor = OBLIQUE_GAIN * min(c.cost for c in out)
        found: list[Candidate] = []
        for lean in (a for a in range(3) if a != axis):
            for angle in OBLIQUE_DEG:
                pos, area, islands, lo, hi = _profile(solid, _frame(axis, lean, angle))
                n = Plane(axis, 0.0, 0.0, lean, angle).normal()
                for d, a, k, c in _minima(pos, area, islands, lo, hi, _hits(n, pos, zones), 2):
                    if c < floor:
                        found.append(Candidate(make_plane(axis, d, lean, angle, centre), a, k, c))
        for cand in sorted(found, key=lambda x: x.cost):
            if len([o for o in out if o.plane.angle]) >= slanted:
                break
            if all(abs(cand.plane.pos - o.plane.pos) >= CAND_SPACING_MM for o in out):
                out.append(cand)
    return sorted(out, key=lambda c: c.plane.pos)


def section_of(solid: mf.Manifold, cut_plane: Plane) -> tuple[float, int]:
    """Area and separate islands of the section at this plane."""
    cs = solid.transform(_frame(cut_plane.axis, cut_plane.lean, cut_plane.angle)).slice(cut_plane.d)
    return float(cs.area()), len(cs.decompose()) if cs.area() > 0 else 0


def candidates(
    v: np.ndarray,
    f: np.ndarray,
    *,
    max_mm: float = mesh.BED_MM - MARGIN_MM,
    forbidden: Sequence[Zone] = (),
    oblique: bool = False,
    include: Sequence[Plane] = (),
) -> tuple[list[Candidate], dict[int, int]]:
    """Every discreet cut plane worth showing for this model (``include``: planes already chosen, kept even if
    they are not among the cheapest), and how many pieces each axis needs."""
    solid = _to_manifold(v, f)
    lo, hi = np.asarray(solid.bounding_box()[:3]), np.asarray(solid.bounding_box()[3:])
    centre = (lo + hi) / 2
    origin = np.array([centre[0], centre[1], lo[2]])
    zones = [(tuple(np.add(a, origin)), tuple(np.add(b, origin))) for a, b in forbidden]
    needs = dict(plan(hi - lo, max_mm))
    out: list[Candidate] = []
    for axis in needs:
        out += candidate_planes(solid, axis, zones, oblique, centre)
    for p in include:
        if p.axis in needs and p not in [c.plane for c in out]:
            area, islands = section_of(solid, p)
            out.append(Candidate(p, area, islands, area + ISLAND_PENALTY * max(islands - 1, 0)))
    return sorted(out, key=lambda c: (c.plane.axis, c.plane.pos)), needs


def best_planes(solid: mf.Manifold, axis: int, count: int, max_mm: float) -> list[float]:
    """Like ``search_planes``; falls back to even spacing when no admissible sequence exists."""
    return search_planes(solid, axis, count, max_mm) or _even(solid, axis, count)


def fits(extents: Sequence[float] | np.ndarray, max_mm: float) -> bool:
    """A piece fits if some axis-aligned lay-down has both plate sides <= max_mm and the height <= the bed."""
    e = sorted(float(x) for x in extents)
    return e[2] <= mesh.BED_MM and e[1] <= max_mm


def check_pieces(pieces: Sequence[Piece], max_mm: float) -> list[dict[str, Any]]:
    """Alerts about the pieces themselves: too big for the plate (blocking), too small (to glue)."""
    out: list[dict[str, Any]] = []
    for p in pieces:
        ext = np.ptp(p.vertices, axis=0)
        if not fits(ext, max_mm):
            out.append(
                alert(
                    "trop_grande",
                    f"{p.name} ({mesh.size_text(ext)}) ne tient pas sur le plateau, même posée à plat.",
                    blocking=True,
                )
            )
        elif ext.max() < MIN_PIECE_MM:
            out.append(
                alert(
                    "trop_petite",
                    f"{p.name} est très petite ({mesh.size_text(ext)}) : imprimée avec les chevilles, à coller.",
                )
            )
    return out


def cut(
    v: np.ndarray,
    f: np.ndarray,
    slots: np.ndarray,
    *,
    max_mm: float = mesh.BED_MM - MARGIN_MM,
    name: str = "piece",
    smart: bool = True,
    forbidden: Sequence[Zone] = (),
    oblique: bool = False,
    planes: Sequence[Plane] | None = None,
    prefer: Sequence[Plane] = (),
    avoid: Sequence[Plane] = (),
) -> CutResult:
    """Cut a model into pieces that fit the plate. ``planes``: cut exactly there instead of searching (the
    checks still run). ``prefer`` / ``avoid``: wishes (e.g. from the vision) the search honours as far as every
    piece can still fit the plate: preferred planes are kept, avoided ones and their neighbourhood are not
    used. ``oblique``: slanted planes (15°, 30°) are tried too, and
    kept where they pass through a clearly narrower section; if they leave a piece too big, the aligned
    cuts are used instead."""
    res = _cut_once(v, f, slots, max_mm, name, smart, forbidden, oblique, planes, prefer, avoid)
    if (
        planes is None
        and oblique
        and any(c.angle for c in res.cuts)
        and any(a["type"] == "trop_grande" for a in res.alerts)
    ):
        res = _cut_once(v, f, slots, max_mm, name, smart, forbidden, False, None, prefer, avoid)
        res.alerts.append(
            alert(
                "biais_abandonne",
                "Les coupes en biais laissaient une pièce trop grande : coupes alignées gardées.",
            )
        )
    return res


def _axis_planes(
    solid: mf.Manifold,
    axis: int,
    count: int,
    max_mm: float,
    zones: Sequence[Zone],
    oblique: bool,
    centre: np.ndarray,
    prefer: Sequence[Plane] = (),
    avoid: Sequence[Plane] = (),
) -> list[Plane] | None:
    """The planes cutting ``axis`` into ``count`` pieces: aligned ones, or slanted ones where clearly cheaper.
    ``prefer``: planes to keep if the pieces can still all fit the plate (same kind as the first one);
    ``avoid``: planes (and their neighbourhood) to stay away from."""
    liked = [p for p in prefer if p.axis == axis]
    if liked:
        lean, angle = liked[0].lean, liked[0].angle
        if lean < 0:
            wanted = _aligned_cost(solid, axis, count, max_mm, zones, prefer, avoid)
            if wanted is not None:
                return [make_plane(axis, d, -1, 0.0, centre) for d in wanted[0]]
        else:
            slanted = _slanted(
                solid, axis, count, max_mm, zones, lean, angle, centre, prefer, avoid
            )
            if slanted is not None:
                return slanted[0]
    aligned = _aligned_cost(solid, axis, count, max_mm, zones, (), avoid)
    if aligned is None and zones:  # one more piece may let the cuts avoid the zones
        aligned = _aligned_cost(solid, axis, count + 1, max_mm, zones, (), avoid)
    best: tuple[list[Plane], float] | None = None
    if oblique:
        for lean in (a for a in range(3) if a != axis):
            for angle in OBLIQUE_DEG:
                got = _slanted(solid, axis, count, max_mm, zones, lean, angle, centre, (), avoid)
                if got is not None and (best is None or got[1] < best[1]):
                    best = got
    if best is not None and (aligned is None or best[1] < OBLIQUE_GAIN * aligned[1]):
        return best[0]
    if aligned is None:
        return None
    return [make_plane(axis, d, -1, 0.0, centre) for d in aligned[0]]


def _cut_once(
    v: np.ndarray,
    f: np.ndarray,
    slots: np.ndarray,
    max_mm: float,
    name: str,
    smart: bool,
    forbidden: Sequence[Zone],
    oblique: bool,
    planes: Sequence[Plane] | None,
    prefer: Sequence[Plane] = (),
    avoid: Sequence[Plane] = (),
) -> CutResult:
    solid = _to_manifold(v, f)
    lo, hi = np.asarray(solid.bounding_box()[:3]), np.asarray(solid.bounding_box()[3:])
    cuts: list[Plane] = []
    alerts: list[dict[str, Any]] = []
    origin = np.array([(lo[0] + hi[0]) / 2, (lo[1] + hi[1]) / 2, lo[2]])
    zones: list[Zone] = [
        (
            cast("tuple[float, float, float]", tuple(float(x) for x in np.add(z0, origin))),
            cast("tuple[float, float, float]", tuple(float(x) for x in np.add(z1, origin))),
        )
        for z0, z1 in forbidden
    ]
    centre = (lo + hi) / 2
    for a, k in [] if planes is not None else plan(hi - lo, max_mm):
        if smart:
            found = _axis_planes(solid, a, k, max_mm, zones, oblique, centre, prefer, avoid)
            if found is None:
                found = [make_plane(a, d, -1, 0.0, centre) for d in _even(solid, a, k)]
                alerts.append(
                    alert(
                        "coupe_reguliere",
                        f"Aucune coupe discrète possible sur l'axe {'XYZ'[a]} : coupe à intervalles réguliers.",
                    )
                )
        else:
            found = [
                make_plane(a, lo[a] + (hi[a] - lo[a]) * i / k, -1, 0.0, centre) for i in range(1, k)
            ]
        cuts += found
    if planes is not None:
        cuts = list(planes)
    if not cuts:
        return CutResult([Piece(name, v, f, slots)], None, [], 0)
    for c in cuts:
        if _hits(c.normal(), np.array([c.d]), zones)[0]:
            alerts.append(
                alert(
                    "zone_interdite",
                    f"La coupe {c.label(origin)} traverse une zone interdite : aucune autre position ne convient.",
                    blocking=True,
                )
            )

    # drill dowel holes across each plane (computed on the uncut solid)
    holes: list[mf.Manifold] = []
    pins: list[float] = []  # pins: depth of each dowel's holes (mm on each side)
    r_hole = PIN_D / 2 + config.dowel_play()
    thin = 0  # dowels whose wall stays under MIN_WALL_MM at both depths

    def _cyl(p: np.ndarray, z: float, depth: float, r: float, inv: np.ndarray) -> mf.Manifold:
        return (
            mf.Manifold.cylinder(2 * depth, r, r, 48)
            .translate([p[0], p[1], z - depth])
            .transform(inv)
        )

    def _inside(c: mf.Manifold) -> bool:  # a hole must stay inside the material
        return bool((c - solid).volume() <= PIERCE_TOLERANCE * c.volume())

    for cp in cuts:
        res = _pin_points(solid, cp)
        placed = 0
        if res is not None:
            pts, z, xf = res
            inv = np.linalg.inv(np.r_[xf, [[0, 0, 0, 1]]])[:3]
            for p in pts:
                for strict in (
                    True,
                    False,
                ):  # first demand a wall all round, then settle for the hole inside
                    for depth in (PIN_DEPTH, PIN_DEPTH_SHORT):
                        cyl = _cyl(p, z, depth, r_hole, inv)
                        if not _inside(cyl):
                            continue
                        if strict and not _inside(_cyl(p, z, depth, r_hole + MIN_WALL_MM, inv)):
                            continue
                        holes.append(cyl)
                        pins.append(depth)
                        placed += 1
                        thin += not strict
                        break
                    else:
                        continue
                    break
        if not placed:
            alerts.append(
                alert(
                    "sans_cheville",
                    f"Aucune cheville possible sur la coupe {cp.label(origin)} "
                    "(section trop fine) : les deux pièces seront à coller sans repère.",
                )
            )
    if thin:
        alerts.append(
            alert(
                "paroi_mince",
                f"{thin} cheville(s) ont une paroi de moins de {MIN_WALL_MM:g} mm autour du trou.",
            )
        )
    if holes:
        solid = solid - mf.Manifold.batch_boolean(holes, mf.OpType.Add)

    pieces = [solid]
    for cp in cuts:
        nxt = []
        for p in pieces:
            above, below = p.split_by_plane(cp.normal().tolist(), cp.d)
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
        pin_mesh = cast("trimesh.Trimesh", trimesh.util.concatenate(dowels))
    alerts += check_pieces(out, max_mm)
    return CutResult(out, pin_mesh, [(c.axis, c.pos) for c in cuts], len(pins), pins, alerts, cuts)
