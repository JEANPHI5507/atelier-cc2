"""A name or a word added to a flat model, in a second colour: "Noël" inside a line-art heart.

The letters stand on a thin bar that runs to the model's own outline, so the whole thing is one
piece that can hang on a wall without letters falling off. Text and bar are cut where they cross
the model (the model keeps its colour there) and written with the model as one two-colour 3MF.
"""

from __future__ import annotations

import re
import unicodedata
from pathlib import Path
from typing import Any

import manifold3d as mf
import numpy as np
import trimesh

from . import colorize, config, mesh, parametric, threemf

LINE_FONT = Path(__file__).parent / "fonts" / "Sacramento-Regular.ttf"   # joined, one even line (SIL OFL)
FONTS = {"manuscrite": parametric.SCRIPT_FONT, "droite": parametric.FONT, "trait": LINE_FONT}
WIDTH_SHARE = 0.5      # automatic size: the text takes half the model's width...
HEIGHT_SHARE = 0.22    # ...but its capitals stay under this share of the model's height


def _manifold(m: trimesh.Trimesh) -> mf.Manifold:
    solid = mf.Manifold(mf.Mesh(vert_properties=np.asarray(m.vertices, np.float32),
                                tri_verts=np.asarray(m.faces, np.uint32)))
    if solid.status() != mf.Error.NoError or solid.volume() <= 0:
        raise ValueError("maillage non fermé : répare le modèle d'abord (bouton « Réparer »)")
    return solid


def _arrays(solid: mf.Manifold) -> tuple[np.ndarray, np.ndarray]:
    m = solid.to_mesh()
    return np.asarray(m.vert_properties)[:, :3].astype(float), np.asarray(m.tri_verts).astype(np.int64)


def _room(outline: mf.CrossSection) -> tuple[mf.CrossSection, tuple[float, float]] | None:
    """The widest free space between the model's strokes (inside a line-art heart, open or not) and
    its deepest point, where the text goes. None for a model without such space (a full plate)."""
    hull = outline.hull()
    free = hull - outline
    if free.area() < 0.05 * hull.area():
        return None
    x0, y0, x1, y1 = free.bounds()
    step, last = max(x1 - x0, y1 - y0) / 80, free
    while True:                                   # erode until almost nothing is left
        nxt = last.offset(-step, mf.JoinType.Round)
        if nxt.area() <= 0:
            break
        last = nxt
    core = max(last.decompose(), key=lambda c: c.area())
    cx0, cy0, cx1, cy1 = core.bounds()
    centre = ((cx0 + cx1) / 2, (cy0 + cy1) / 2)
    region = next(g for g in free.decompose() if (g ^ core).area() > 0)
    return region, centre


def _stroke(section: mf.CrossSection) -> float:
    """Width of a drawn line: twice how far it can be eroded before it disappears."""
    x0, y0, x1, y1 = section.bounds()
    lo, hi = 0.0, max(x1 - x0, y1 - y0)
    for _ in range(20):
        mid = (lo + hi) / 2
        lo, hi = (mid, hi) if section.offset(-mid, mf.JoinType.Round).area() > 0.002 * section.area() else (lo, mid)
    return 2 * lo


def _one_line(region: mf.CrossSection, base: mf.CrossSection, width: float, dx: float, dy: float
              ) -> tuple[mf.CrossSection, float]:
    """The word written like the drawing: its line as thick as the model's, its first and last letters
    running into the strokes on each side, so drawing and name read as one line. Tries heights across
    the free space and keeps the longest line from stroke to stroke the word fits on."""
    bx0, by0, bx1, by1 = base.bounds()
    glyph = _stroke(base)                          # the font's own line width at 10 mm capitals
    room = region.offset(0.5 * width, mf.JoinType.Round)
    rx0, ry0, rx1, ry1 = region.bounds()
    best: tuple[float, mf.CrossSection | None, float] = (0.0, None, 0.0)
    for y in np.linspace(ry0, ry1, 40)[1:-1]:
        line = mf.CrossSection.square([rx1 - rx0 + 2, 0.2]).translate([rx0 - 1, y - 0.1]) ^ region
        spans = line.decompose()
        if not spans:
            continue
        sx0, _, sx1, _ = max(spans, key=lambda sp: sp.area()).bounds()
        if sx1 - sx0 <= best[0]:
            continue
        k = (sx1 - sx0 + 1.2 * width) / (bx1 - bx0)          # ends 0.6 line widths into each stroke
        t = base.scale([k, k])
        t = t.offset(max(0.0, (width - glyph * k) / 2), mf.JoinType.Round)
        tx0, ty0, tx1, ty1 = t.bounds()
        # the baseline sits on the chord: the word's ends meet the strokes where the chord does
        t = t.translate([(sx0 + sx1) / 2 - (tx0 + tx1) / 2 + dx, y + dy])   # font baseline (y = 0) on the chord
        if (t - room).area() <= 0.01 * t.area():
            best = (sx1 - sx0, t, 10.0 * k)
    if best[1] is None:
        raise ValueError("pas de place pour écrire ce texte d'un seul trait dans ce dessin : essaie l'écriture manuscrite")
    return best[1], best[2]


def _tie(shape: mf.CrossSection, cap: float) -> mf.CrossSection:
    """Hook loose bits (the dot of an i, an accent) onto what lies under them with a thin stem."""
    pieces = sorted(shape.decompose(), key=lambda p: -p.area())
    main = pieces[0]
    for p in pieces[1:]:
        x0, y0, x1, y1 = p.bounds()
        for reach in (0.2, 0.4, 0.7, 1.2):
            # up to the bit's middle: accents are slanted, their lowest point is off to one side
            w = max(0.8, 0.07 * cap)
            stem = mf.CrossSection.square([w, reach * cap + (y1 - y0) / 2]).translate([(x0 + x1) / 2 - w / 2, y0 - reach * cap])
            joined = main + p + stem
            if len(joined.decompose()) < len((main + p).decompose()):   # the stem reached something
                main = joined
                break
        else:
            main = main + p                       # left loose: counted in "pieces"
    return main


def add(src: Path, text: str, *, font: str = "manuscrite", size_mm: float | None = None,
        dx: float = 0.0, dy: float = 0.0, angle: float = 0.0, bar: bool = True, out: Path | None = None) -> dict[str, Any]:
    """Write ``<model>_<text>.3mf`` next to ``src``: the model in colour 1, the text in colour 2.

    ``size_mm``: capital height (automatic when None); ``dx``/``dy``: shift from the model's centre (mm);
    ``angle``: the word's slope in degrees (30 = rising to the right, across a heart);
    ``bar``: tie the letters to the outline. A model lying on its side is laid flat first."""
    if not -90 <= angle <= 90:
        raise ValueError("angle entre -90 et 90°")
    text = text.strip()
    if not text or len(text) > 40:
        raise ValueError("écris un texte de 1 à 40 caractères")
    if font not in FONTS:
        raise ValueError(f"police inconnue « {font} »")
    m = mesh.load(src)
    ext = m.extents
    thin = int(np.argmin(ext))
    if thin != 2:                                   # lay it flat: its thinnest side down
        axis = [[0, 1, 0], [1, 0, 0]][thin]
        m.apply_transform(trimesh.transformations.rotation_matrix(np.pi / 2, axis))
    if m.extents[2] > 0.4 * min(m.extents[:2]):
        raise ValueError("le texte s'ajoute aux modèles plats (plaque, dessin au trait, découpe)")
    model = _manifold(m)
    z0, z1 = m.bounds[:, 2]
    # everything below is worked out with the word level: the model's outline turned by -angle
    outline = model.slice(float((z0 + z1) / 2)).rotate(-angle)
    x0, y0, x1, y1 = outline.bounds()
    room = _room(outline)
    if room is not None:
        region, (cx, cy) = room
    else:
        region = mf.CrossSection.square([x1 - x0, y1 - y0]).translate([x0, y0])
        cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    cx, cy = cx + dx, cy + dy

    base = parametric.text_section(text, 10.0, FONTS[font]).offset(0.15, mf.JoinType.Round)  # a hair bolder: strokes hold
    bx0, by0, bx1, by1 = base.bounds()
    k = size_mm / 10.0 if size_mm else min(WIDTH_SHARE * (x1 - x0) / (bx1 - bx0), HEIGHT_SHARE * (y1 - y0) / 10.0)
    inner = region.offset(-1.0, mf.JoinType.Round)

    def placed(k: float) -> mf.CrossSection:
        t = base.scale([k, k])
        tx0, ty0, tx1, ty1 = t.bounds()
        return t.translate([cx - (tx0 + tx1) / 2, cy - (ty0 + ty1) / 2])

    letters = placed(k)
    if font == "trait" and room is not None:
        letters, cap = _one_line(region, base, _stroke(outline), dx, dy)
        k = cap / 10.0
        bar = False
    elif not size_mm and room is not None:
        # try heights across the free space: at each, centre the word between the strokes and grow it
        # as much as it fits; then, among the nearly-biggest, the longest line from stroke to stroke
        # (straight across the heart rather than tucked in a corner)
        fits = lambda t: (t - inner).area() <= 0.005 * t.area()
        rx0, ry0, rx1, ry1 = inner.bounds()
        tries = []
        for y in np.linspace(ry0, ry1, 32)[1:-1]:
            line = mf.CrossSection.square([rx1 - rx0 + 2, 0.2]).translate([rx0 - 1, y - 0.1]) ^ inner
            spans = line.decompose()
            if not spans:
                continue
            sx0, _, sx1, _ = max(spans, key=lambda sp: sp.area()).bounds()
            cx, cy = (sx0 + sx1) / 2 + dx, y + dy
            lo_k, hi_k = 0.0, min(k, (sx1 - sx0) / (bx1 - bx0))
            for _ in range(7):
                mid = (lo_k + hi_k) / 2
                lo_k, hi_k = (mid, hi_k) if fits(placed(mid)) else (lo_k, mid)
            tries.append((lo_k, cx, cy, sx1 - sx0))
        top = max((t[0] for t in tries), default=0.0)
        k, cx, cy, _ = max((t for t in tries if t[0] >= 0.8 * top), key=lambda t: t[3], default=(0.0, cx, cy, 0))
        if k < 0.25:
            raise ValueError("pas assez de place entre les traits pour ce texte : raccourcis-le ou donne une taille")
        letters = placed(k)
    base_y = letters.bounds()[1] - by0 * k        # the font baseline once placed
    shape = letters
    if font == "trait":
        shape = _tie(shape, 10.0 * k)
    elif bar:
        t = max(1.2, 0.1 * 10.0 * k)
        strip = mf.CrossSection.square([4 * (x1 - x0), t]).translate([x0 - 2 * (x1 - x0), base_y - 0.7 * t])
        # from the stroke on the left of the word to the one on its right (0.8 mm into each)
        spans = (strip ^ region.offset(0.8, mf.JoinType.Round)).decompose()
        lx0, _, lx1, _ = letters.bounds()
        shape = shape + mf.CrossSection.batch_boolean([sp for sp in spans if sp.bounds()[0] < lx1 and sp.bounds()[2] > lx0]
                                                       or [mf.CrossSection()], mf.OpType.Add)
        shape = _tie(shape, 10.0 * k)
    loose = len((shape + outline).decompose())     # 1: model and text hold as one piece
    solid = shape.rotate(angle).extrude(z1 - z0).translate([0, 0, z0]) - model
    if solid.volume() <= 0:
        raise ValueError("le texte tombe entièrement sur le trait du modèle : décale-le")

    tv, tf = _arrays(solid)
    mv, mf_ = _arrays(model)
    plain = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()   # "Noël" -> "Noel"
    stem = re.sub(r"[^\w-]+", "_", plain, flags=re.A).strip("_")[:24] or "texte"
    out = out or src.with_name(f"{src.stem}_{stem}.3mf")
    k2 = 1
    while out.exists():
        k2 += 1
        out = out.with_name(f"{src.stem}_{stem} ({k2}).3mf")
    lo = np.minimum(mv.min(0), tv.min(0))
    hi = np.maximum(mv.max(0), tv.max(0))
    if (hi - lo)[:2].max() > mesh.BED_MM:
        raise ValueError("trop grand pour le plateau avec le texte")
    offset = np.array([mesh.BED_MM / 2 - (lo[0] + hi[0]) / 2, mesh.BED_MM / 2 - (lo[1] + hi[1]) / 2, -lo[2]])
    project = threemf.Project([threemf.Object(src.stem, [threemf.Part(src.stem, mv, mf_, 1),
                                                         threemf.Part(f"texte {text}", tv, tf, 2)])], [])
    # red model, yellow text: the spool matching then puts the text on the lightest warm spool
    threemf.write(project, out, filaments=2, colours=[colorize.PALETTE[0], colorize.PALETTE[3]], offset=offset)
    return {"name": out.name, "size_mm": (hi - lo).round(1).tolist(), "capitales_mm": round(10.0 * k, 1),
            "pieces": loose}
