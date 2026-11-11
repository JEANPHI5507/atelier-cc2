"""More made-to-measure parts: Gridfinity bins and baseplate, phone stand, cable comb, metric screws, nuts,
washers and spacers, spur gears, name keychain, Christmas ornament, photo lithophane.

The most printed parametric things on MakerWorld and GitHub (2026-11): Gridfinity storage, threaded parts and
gears, stands and cable organisers, personalised names. Each generator returns named parts with a filament
slot like parametric.py's; dimensions follow the published standards where there is one (Gridfinity 42 mm
grid and its foot profile, ISO metric coarse threads and hex sizes, involute gear teeth).
"""

from __future__ import annotations

import base64
import contextvars
import io
import math
from typing import Any

import manifold3d as mf
import numpy as np

from .parametric import FONT, SCRIPT_FONT, Part, _rounded, text_section


PREVIEW = contextvars.ContextVar("preview", default=False)   # the live preview: coarser where it costs (lithophane)


def _from_grid(v: np.ndarray, f: np.ndarray) -> mf.Manifold:
    s = mf.Manifold(mf.Mesh(vert_properties=np.asarray(v, np.float32), tri_verts=np.asarray(f, np.uint32)))
    if s.status() != mf.Error.NoError or s.is_empty():
        raise ValueError("pièce impossible à construire avec ces cotes")
    return s


def _slab(w: float, d: float, r: float, z: float, h: float = 0.01) -> mf.Manifold:
    """A thin rounded rectangle centred on the origin at height z: hull them to make chamfered profiles."""
    return _rounded(w, d, r).translate([-w / 2, -d / 2]).extrude(h).translate([0, 0, z])


# --- Gridfinity (Zack Freedman's open standard: 42 mm grid, 7 mm height units) -----------------------

GF = 42.0
GF_FOOT = [(35.6, 0.8, 0.0), (37.2, 1.6, 0.8), (37.2, 1.6, 2.6), (41.5, 3.75, 4.75)]   # (size, radius, z) of the foot


def _gf_foot() -> mf.Manifold:
    return mf.Manifold.batch_hull([_slab(s, s, r, z) for s, r, z in GF_FOOT])


def gridfinity_bin(cases_x: int, cases_y: int, hauteur_u: int, compartiments_x: int, compartiments_y: int,
                   aimants: bool, empilable: bool) -> list[Part]:
    nx, ny, u = int(cases_x), int(cases_y), int(hauteur_u)
    w, d, top = nx * GF - 0.5, ny * GF - 0.5, 7.0 * u
    feet = [_gf_foot().translate([(i - (nx - 1) / 2) * GF, (j - (ny - 1) / 2) * GF, 0]) for i in range(nx) for j in range(ny)]
    body = mf.Manifold.batch_boolean(feet + [_slab(w, d, 3.75, 4.75, top - 4.75)], mf.OpType.Add)
    wall, floor = 1.2, 4.75 + 1.2
    cx, cy = int(compartiments_x), int(compartiments_y)
    iw, idp = w - 2 * wall, d - 2 * wall
    cw, cd = (iw - (cx - 1) * wall) / cx, (idp - (cy - 1) * wall) / cy
    if cw < 8 or cd < 8:
        raise ValueError("compartiments trop petits : moins de cases ou un bac plus grand")
    cells = [_slab(cw, cd, 1.6, floor, top).translate([-iw / 2 + cw / 2 + i * (cw + wall), -idp / 2 + cd / 2 + j * (cd + wall), 0])
             for i in range(cx) for j in range(cy)]
    body = body - mf.Manifold.batch_boolean(cells, mf.OpType.Add)
    if empilable:   # stacking lip: the next bin's foot sits in it
        lip_h = 4.4
        rim = _slab(w, d, 3.75, top, lip_h) - mf.Manifold.hull(_slab(w - 2 * 2.6, d - 2 * 2.6, 1.15, top - 0.01)
                                                               + _slab(w - 1.0, d - 1.0, 3.25, top + lip_h))
        body = body + rim
    if aimants:     # 6 × 2 mm magnets, 13 mm from each cell's centre, from below
        holes = [mf.Manifold.cylinder(2.4, 3.25, 3.25, 32).translate([(i - (nx - 1) / 2) * GF + sx * 13, (j - (ny - 1) / 2) * GF + sy * 13, -0.01])
                 for i in range(nx) for j in range(ny) for sx in (-1, 1) for sy in (-1, 1)]
        body = body - mf.Manifold.batch_boolean(holes, mf.OpType.Add)
    return [("bac", body, 1)]


def gridfinity_base(cases_x: int, cases_y: int, aimants: bool) -> list[Part]:
    nx, ny = int(cases_x), int(cases_y)
    h = 4.65 + (2.4 if aimants else 0.0)
    plate = _slab(nx * GF, ny * GF, 4.0, 0, h)
    pocket = mf.Manifold.batch_hull([_slab(s, s, r, z + h - 4.65) for s, r, z in
                                     [(36.3, 1.15, 0.0), (37.7, 1.85, 0.7), (37.7, 1.85, 2.5), (42.0, 4.0, 4.66)]])
    cut = [pocket.translate([(i - (nx - 1) / 2) * GF, (j - (ny - 1) / 2) * GF, 0]) for i in range(nx) for j in range(ny)]
    if aimants:
        cut += [mf.Manifold.cylinder(2.41, 3.25, 3.25, 32).translate([(i - (nx - 1) / 2) * GF + sx * 13, (j - (ny - 1) / 2) * GF + sy * 13, 0.01])
                for i in range(nx) for j in range(ny) for sx in (-1, 1) for sy in (-1, 1)]
    return [("plaque", plate - mf.Manifold.batch_boolean(cut, mf.OpType.Add), 1)]


# --- phone / tablet stand ------------------------------------------------------------------------

def phone_stand(largeur: float, angle: float, epaisseur_appareil: float, hauteur: float, passage_cable: bool) -> list[Part]:
    """Side profile extruded across the width: a base, a back leaning at ``angle``, a front lip holding the device."""
    a = math.radians(angle)
    t, base_d = 5.0, max(70.0, hauteur * math.cos(a) + 45)
    y0 = 18 + epaisseur_appareil / math.sin(a) + 4        # where the back meets the base
    back = [(y0, t), (y0 + hauteur * math.cos(a), t + hauteur * math.sin(a)),
            (y0 + hauteur * math.cos(a) + t / math.sin(a), t + hauteur * math.sin(a)), (y0 + t / math.sin(a), t)]
    strut = [(y0 + hauteur * 0.5 * math.cos(a) + t, t + hauteur * 0.5 * math.sin(a)), (base_d, t), (base_d - 2 * t, t)]
    poly = lambda pts: mf.CrossSection([pts], mf.FillRule.NonZero)   # either winding: the outlines are drawn clockwise
    profile = (mf.CrossSection.square([base_d, t]) + poly(back) + poly(strut)
               + mf.CrossSection.square([4.0, 12.0]).translate([10.0, t - 0.01]))
    solid = profile.extrude(largeur).rotate([90, 0, 0])
    if passage_cable:   # a 14 mm slot through the lip and the front of the base, for the charging cable
        solid = solid - mf.Manifold.cube([y0 + 6, 14, 40]).translate([-1, -largeur / 2 - 7, -1])
    return [("support", solid, 1)]


# --- cable comb -----------------------------------------------------------------------------------

def cable_comb(nombre: int, diametre: float, profondeur: float, paroi: float, vis: bool) -> list[Part]:
    n, d = int(nombre), diametre
    pitch = d + 2 * paroi
    length, height = n * pitch + paroi, d + 2 * paroi
    block = mf.Manifold.cube([length, profondeur, height])
    slots = []
    for i in range(n):
        cx = paroi / 2 + pitch * i + pitch / 2
        hole = mf.Manifold.cylinder(profondeur + 2, d / 2, d / 2, 40).rotate([-90, 0, 0]).translate([cx, -1, paroi + d / 2])
        mouth = mf.Manifold.cube([d * 0.75, profondeur + 2, height]).translate([cx - d * 0.375, -1, paroi + d / 2])
        slots += [hole, mouth]
    part = block - mf.Manifold.batch_boolean(slots, mf.OpType.Add)
    if vis:   # two screw tabs at the ends
        for x in (-12.0, length):
            tab = mf.Manifold.cube([12, profondeur, paroi * 1.5]).translate([x, 0, 0])
            part = part + tab - mf.Manifold.cylinder(10, 2.0, 2.0, 32).translate([x + 6, profondeur / 2, -1])
    return [("range-cables", part, 1)]


# --- ISO metric screws, nuts, washers, spacers ---------------------------------------------------

# M: (pitch, hex across flats, head height, nut height)
METRIC = {"M3": (0.5, 5.5, 2.0, 2.4), "M4": (0.7, 7.0, 2.8, 3.2), "M5": (0.8, 8.0, 3.5, 4.0),
          "M6": (1.0, 10.0, 4.0, 5.0), "M8": (1.25, 13.0, 5.3, 6.5), "M10": (1.5, 16.0, 6.4, 8.0)}


def _thread(d: float, pitch: float, length: float, inner: bool, play: float, steps: int = 96) -> mf.Manifold:
    """An ISO 60° thread as a closed radial surface: r(θ, z) from the tooth profile at phase (z - pitch·θ/2π)."""
    h = 0.866 * pitch
    r_major = d / 2 + (play if inner else -play)
    r_minor = r_major - 0.625 * h
    nz = max(8, int(length / pitch * 16))
    th = np.linspace(0, 2 * np.pi, steps, endpoint=False)
    zs = np.linspace(0, length, nz + 1)
    T, Z = np.meshgrid(th, zs)
    phase = ((Z - pitch * T / (2 * np.pi)) / pitch) % 1.0
    tooth = np.clip(1 - np.abs(phase - 0.5) * 2 * 1.6 + 0.3, 0, 1)   # trapezoid: flat crests and roots
    R = r_minor + (r_major - r_minor) * tooth
    v = np.c_[(R * np.cos(T)).ravel(), (R * np.sin(T)).ravel(), Z.ravel()]
    idx = np.arange(len(v)).reshape(nz + 1, steps)
    a, b = idx[:-1], np.roll(idx[:-1], -1, axis=1)
    c, e = idx[1:], np.roll(idx[1:], -1, axis=1)
    f = np.r_[np.c_[a.ravel(), b.ravel(), e.ravel()], np.c_[a.ravel(), e.ravel(), c.ravel()]]
    bottom, top = len(v), len(v) + 1
    v = np.r_[v, [[0, 0, 0], [0, 0, length]]]
    ring0, ring1 = idx[0], idx[-1]
    f = np.r_[f, np.c_[np.full(steps, bottom), np.roll(ring0, -1), ring0], np.c_[np.full(steps, top), ring1, np.roll(ring1, -1)]]
    return _from_grid(v, f)


def _hexagon(across_flats: float, h: float) -> mf.Manifold:
    return mf.Manifold.cylinder(h, across_flats / math.sqrt(3), across_flats / math.sqrt(3), 6)


def hardware(piece: str, taille: str, longueur: float, jeu: float) -> list[Part]:
    if taille not in METRIC:
        raise ValueError(f"taille inconnue « {taille} »")
    pitch, af, head, nut_h = METRIC[taille]
    d = float(taille[1:])
    if piece == "vis":
        shank = _thread(d, pitch, longueur, inner=False, play=jeu).translate([0, 0, head])
        return [("vis", _hexagon(af, head) + shank, 1)]
    if piece == "ecrou":
        return [("ecrou", _hexagon(af, nut_h) - _thread(d, pitch, nut_h + 2, inner=True, play=jeu).translate([0, 0, -1]), 1)]
    if piece == "rondelle":
        ring = mf.Manifold.cylinder(max(0.8, d * 0.18), d * 1.05, d * 1.05, 64) - mf.Manifold.cylinder(10, d / 2 + jeu + 0.1, d / 2 + jeu + 0.1, 48).translate([0, 0, -1])
        return [("rondelle", ring, 1)]
    if piece == "entretoise":
        return [("entretoise", mf.Manifold.cylinder(longueur, d, d, 64) - mf.Manifold.cylinder(longueur + 2, d / 2 + jeu + 0.1, d / 2 + jeu + 0.1, 48).translate([0, 0, -1]), 1)]
    raise ValueError(f"pièce inconnue « {piece} »")


# --- spur gear (involute teeth) ------------------------------------------------------------------

def _involute(rb: float, r: float) -> float:
    """Angle along the involute of the base circle rb where it reaches radius r."""
    return math.sqrt(max(0.0, (r / rb) ** 2 - 1)) - math.acos(min(1.0, rb / r))


def gear(dents: int, module: float, epaisseur: float, alesage: float, angle_pression: float) -> list[Part]:
    z, m = int(dents), module
    a = math.radians(angle_pression)
    rp, ra, rf = z * m / 2, z * m / 2 + m, z * m / 2 - 1.25 * m
    rb = rp * math.cos(a)
    half = math.pi / (2 * z) + _involute(rb, rp)          # half tooth angle at the base circle side
    pts: list[tuple[float, float]] = []
    radii = np.linspace(max(rb, rf), ra, 10)
    for k in range(z):
        c = 2 * math.pi * k / z
        left = [c - half + _involute(rb, r) for r in radii]
        right = [c + half - _involute(rb, r) for r in radii]
        pts.append((rf * math.cos(c - math.pi / z + 0.0001), rf * math.sin(c - math.pi / z + 0.0001)))
        pts += [(r * math.cos(t), r * math.sin(t)) for r, t in zip(radii, left)]
        pts += [(r * math.cos(t), r * math.sin(t)) for r, t in reversed(list(zip(radii, right)))]
    body = mf.CrossSection([pts]).extrude(epaisseur)
    if alesage > 0:
        if alesage >= 2 * rf - 2 * m:
            raise ValueError("alésage plus grand que la roue")
        body = body - mf.Manifold.cylinder(epaisseur + 2, alesage / 2, alesage / 2, 48).translate([0, 0, -1])
    return [("engrenage", body, 1)]


# --- name keychain and Christmas ornament (two colours) ------------------------------------------

def _font(police: str):
    return SCRIPT_FONT if police == "manuscrite" and SCRIPT_FONT.exists() else FONT


def keychain(texte: str, police: str, taille_texte: float, epaisseur: float, relief: float) -> list[Part]:
    if not texte.strip():
        raise ValueError("écris un prénom")
    letters = text_section(texte.strip(), taille_texte, _font(police))
    x0, y0, x1, y1 = letters.bounds()
    letters = letters.translate([-x0, -y0])
    outline = letters.offset(max(2.5, taille_texte * 0.28), mf.JoinType.Round, 2, 24)   # the plate follows the letters
    ring_c = (-3.5, (y1 - y0) / 2)
    ring = mf.CrossSection.circle(5.5, 48).translate(ring_c) - mf.CrossSection.circle(2.6, 40).translate(ring_c)
    plate = (outline + ring).extrude(epaisseur) - mf.Manifold.cylinder(epaisseur * 3, 2.6, 2.6, 40).translate([*ring_c, -epaisseur])
    return [("porte-cles", plate, 1), ("prenom", letters.extrude(relief).translate([0, 0, epaisseur]), 2)]


def _star(r: float, n: int = 5) -> mf.CrossSection:
    return mf.CrossSection([[((r if i % 2 == 0 else r * 0.45) * math.sin(i * math.pi / n), (r if i % 2 == 0 else r * 0.45) * math.cos(i * math.pi / n))
                             for i in range(2 * n)]], mf.FillRule.NonZero)   # drawn clockwise


def _tree(h: float) -> mf.CrossSection:
    w = h * 0.8
    tiers = [mf.CrossSection([[(-w / 2 * k, h * (0.15 + 0.3 * (1 - k))), (w / 2 * k, h * (0.15 + 0.3 * (1 - k))), (0, h * (0.62 + 0.38 * (1 - k)))]])
             for k in (1.0, 0.78, 0.55)]
    trunk = mf.CrossSection.square([h * 0.14, h * 0.18]).translate([-h * 0.07, 0])
    return trunk + sum(tiers[1:], tiers[0])


def ornament(forme: str, texte: str, diametre: float, epaisseur: float, relief: float) -> list[Part]:
    r = diametre / 2
    shape = {"boule": lambda: mf.CrossSection.circle(r, 96) + mf.CrossSection.square([r * 0.36, r * 0.2]).translate([-r * 0.18, r * 0.95]),
             "etoile": lambda: _star(r), "sapin": lambda: _tree(diametre).translate([0, -r])}.get(forme)
    if shape is None:
        raise ValueError(f"forme inconnue « {forme} »")
    body = shape()
    top = body.bounds()[3]
    loop_c = (0.0, top + 3.0)
    loop = mf.CrossSection.circle(4.5, 40).translate(loop_c) - mf.CrossSection.circle(2.2, 32).translate(loop_c)
    parts: list[Part] = [("decoration", (body + loop).extrude(epaisseur), 1)]
    if texte.strip():
        letters = text_section(texte.strip(), max(4.0, diametre * 0.16), SCRIPT_FONT if SCRIPT_FONT.exists() else FONT)
        x0, y0, x1, y1 = letters.bounds()
        k = min(1.0, diametre * 0.72 / max(x1 - x0, 1))     # the name fits inside the shape
        letters = letters.translate([-(x0 + x1) / 2, -(y0 + y1) / 2]).scale([k, k])
        parts.append(("prenom", letters.extrude(relief).translate([0, 0, epaisseur]), 2))
    return parts


# --- photo lithophane ----------------------------------------------------------------------------

def _default_picture() -> np.ndarray:
    """A heart on a soft gradient: the preview before a photo is chosen."""
    y, x = np.mgrid[1.4:-1.3:240j, -1.8:1.8:320j]
    heart = (x ** 2 + y ** 2 - 1) ** 3 - x ** 2 * y ** 3 < 0          # the classic heart curve, point down
    return np.where(heart, 0.2, 0.9) - 0.1 * (y + 1.3) / 2.7


def _picture(data: str | None) -> np.ndarray:
    """Grey levels 0 (black) .. 1 (white) from a data: URL or base64 image, at most 700 px wide."""
    if not data:
        return _default_picture()
    from PIL import Image, ImageOps
    raw = base64.b64decode(data.split(",", 1)[-1])
    if len(raw) > 12_000_000:
        raise ValueError("photo trop lourde (12 Mo au plus)")
    img = ImageOps.exif_transpose(Image.open(io.BytesIO(raw))).convert("L")
    img.thumbnail((700, 700))
    return np.asarray(img, dtype=float) / 255.0


def lithophane(photo: str, largeur: float, epaisseur_min: float, epaisseur_max: float, cadre: float) -> list[Part]:
    """Dark = thick, light = thin: lit from behind, the plate shows the photo. Printed upright, 100 % infill."""
    if epaisseur_max <= epaisseur_min:
        raise ValueError("l'épaisseur max doit dépasser l'épaisseur min")
    g = _picture(photo)
    step = 0.6 if PREVIEW.get() else 0.25            # one height per 0.25 mm: finer than the nozzle can show
    nx = max(20, int(largeur / step))
    ny = max(20, int(nx * g.shape[0] / g.shape[1]))
    from PIL import Image
    g = np.asarray(Image.fromarray((g * 255).astype(np.uint8)).resize((nx, ny), Image.LANCZOS), float) / 255
    hgt = epaisseur_min + (1 - g[::-1]) * (epaisseur_max - epaisseur_min)
    xs, ys = np.arange(nx) * step, np.arange(ny) * step
    X, Y = np.meshgrid(xs, ys)
    top = np.c_[X.ravel(), Y.ravel(), hgt.ravel()]
    bot = np.c_[X.ravel(), Y.ravel(), np.zeros(X.size)]
    v = np.r_[top, bot]
    idx = np.arange(nx * ny).reshape(ny, nx)
    a, b, c, d = idx[:-1, :-1].ravel(), idx[:-1, 1:].ravel(), idx[1:, :-1].ravel(), idx[1:, 1:].ravel()
    off = nx * ny
    f = [np.c_[a, b, d], np.c_[a, d, c], np.c_[a + off, d + off, b + off], np.c_[a + off, c + off, d + off]]
    for edge in (idx[0, :], idx[:, -1], idx[-1, ::-1], idx[::-1, 0]):   # walls around, outward
        e0, e1 = edge[:-1], edge[1:]
        f += [np.c_[e0, e0 + off, e1], np.c_[e1, e0 + off, e1 + off]]
    plate = _from_grid(v, np.vstack(f))
    if cadre > 0:
        w, h = xs[-1], ys[-1]
        frame = mf.Manifold.cube([w + 2 * cadre, h + 2 * cadre, epaisseur_max + 1]).translate([-cadre, -cadre, 0]) \
            - mf.Manifold.cube([w - 0.02, h - 0.02, epaisseur_max + 3]).translate([0.01, 0.01, -1])
        plate = plate + frame
    # stood up on its bottom edge: layers run across the picture, the cleanest way to print one
    return [("lithophanie", plate.rotate([90, 0, 0]), 1)]
