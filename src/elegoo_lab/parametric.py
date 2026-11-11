"""Made-to-measure parts built from dimensions (no AI): box with lid, two-colour label, wall hook,
drawer organiser here, and the rest in parametric_more.py (Gridfinity, stand, cable comb, metric hardware,
gears, keychain, Christmas ornament, lithophane). Exact solids with manifold3d, written as 3MF in the library.

Each generator returns named parts with a filament slot, so the label's text prints in a second
colour from the CANVAS.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

import manifold3d as mf
import numpy as np
from fontTools.pens.basePen import BasePen
from fontTools.ttLib import TTFont

from . import colorize, config, threemf

FONT = Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf")
SCRIPT_FONT = Path("/usr/share/fonts/opentype/urw-base35/Z003-MediumItalic.otf")   # handwriting (URW, free)


@dataclass(frozen=True)
class Param:
    name: str
    label: str
    default: Any
    lo: float | None = None
    hi: float | None = None
    unit: str = "mm"
    kind: str = "number"      # number | int | text | bool | choice | image
    options: tuple[tuple[str, str], ...] = ()   # choice: (value, label)


Part = tuple[str, mf.Manifold, int]   # (name, solid, filament slot)


# --- helpers -----------------------------------------------------------------------------

def _rounded(w: float, d: float, r: float) -> mf.CrossSection:
    r = max(0.0, min(r, w / 2 - 0.01, d / 2 - 0.01))
    if r <= 0:
        return mf.CrossSection.square([w, d])
    return mf.CrossSection.square([w - 2 * r, d - 2 * r]).translate([r, r]).offset(r, mf.JoinType.Round, 2, 48)


class _FlatPen(BasePen):
    """Glyph outlines -> closed polylines (curves flattened)."""

    def __init__(self, glyphset: Any, steps: int = 8) -> None:
        super().__init__(glyphset)
        self.contours: list[list[tuple[float, float]]] = []
        self.cur: list[tuple[float, float]] = []
        self.steps = steps

    def _moveTo(self, p: tuple[float, float]) -> None:
        self.cur = [p]

    def _lineTo(self, p: tuple[float, float]) -> None:
        self.cur.append(p)

    def _curveToOne(self, p1: Any, p2: Any, p3: Any) -> None:
        p0 = np.array(self.cur[-1])
        for t in np.linspace(0, 1, self.steps + 1)[1:]:
            pt = (1 - t) ** 3 * p0 + 3 * (1 - t) ** 2 * t * np.array(p1) + 3 * (1 - t) * t ** 2 * np.array(p2) + t ** 3 * np.array(p3)
            self.cur.append(tuple(pt))

    def _qCurveToOne(self, p1: Any, p2: Any) -> None:
        p0 = np.array(self.cur[-1])
        for t in np.linspace(0, 1, self.steps + 1)[1:]:
            pt = (1 - t) ** 2 * p0 + 2 * (1 - t) * t * np.array(p1) + t ** 2 * np.array(p2)
            self.cur.append(tuple(pt))

    def _closePath(self) -> None:
        if len(self.cur) >= 3:
            self.contours.append(self.cur)
        self.cur = []

    _endPath = _closePath


def text_section(text: str, height: float, font_file: Path = FONT) -> mf.CrossSection:
    """Text outline (capital letters ``height`` mm tall), lines separated by \\n, left-aligned at x=0."""
    font = TTFont(font_file)
    gs, cmap = font.getGlyphSet(), font.getBestCmap()
    units = font["head"].unitsPerEm
    cap = getattr(font["OS/2"], "sCapHeight", 0) or units * 0.72
    k = height / cap
    contours: list[np.ndarray] = []
    lines = text.split("\n")
    for row, line in enumerate(lines):
        x = 0.0
        y = -row * cap * 1.45
        for ch in line:
            name = cmap.get(ord(ch)) or cmap.get(ord("?"))
            pen = _FlatPen(gs)
            gs[name].draw(pen)
            for c in pen.contours:
                contours.append((np.array(c) + [x, y]) * k)
            x += font["hmtx"][name][0]
    if not contours:
        raise ValueError("texte vide")
    return mf.CrossSection(contours, mf.FillRule.EvenOdd)


# --- generators ---------------------------------------------------------------------------

def box(longueur: float, largeur: float, hauteur: float, paroi: float, jeu: float, rayon: float) -> list[Part]:
    outer = _rounded(longueur, largeur, rayon)
    inner = _rounded(longueur - 2 * paroi, largeur - 2 * paroi, max(0, rayon - paroi)).translate([paroi, paroi])
    body = outer.extrude(hauteur) - inner.extrude(hauteur).translate([0, 0, paroi])
    lip_h = min(6.0, hauteur / 3)
    lip_out = _rounded(longueur - 2 * (paroi + jeu), largeur - 2 * (paroi + jeu), max(0, rayon - paroi - jeu)).translate([paroi + jeu, paroi + jeu])
    lip_in = _rounded(longueur - 2 * (2 * paroi + jeu), largeur - 2 * (2 * paroi + jeu), max(0, rayon - 2 * paroi - jeu)).translate([2 * paroi + jeu] * 2)
    lid = outer.extrude(paroi) + (lip_out.extrude(lip_h) - lip_in.extrude(lip_h)).translate([0, 0, paroi])
    return [("boite", body, 1), ("couvercle", lid.translate([0, largeur + 10, 0]), 1)]


def label(texte: str, taille_texte: float, epaisseur: float, relief: float, marge: float, trou: bool) -> list[Part]:
    if not texte.strip():
        raise ValueError("écris un texte pour l'étiquette")
    letters = text_section(texte.strip(), taille_texte)
    x0, y0, x1, y1 = letters.bounds()
    hole_d = 4.0 if trou else 0.0
    w = (x1 - x0) + 2 * marge + (hole_d + marge if trou else 0)
    d = (y1 - y0) + 2 * marge
    shift = [marge - x0 + (hole_d + marge if trou else 0), marge - y0]
    plate = _rounded(w, d, min(4.0, d / 4)).extrude(epaisseur)
    if trou:
        plate = plate - mf.Manifold.cylinder(epaisseur * 3, hole_d / 2, hole_d / 2, 40).translate([marge + hole_d / 2, d / 2, -epaisseur])
    text = letters.translate(shift).extrude(relief).translate([0, 0, epaisseur])
    return [("plaque", plate, 1), ("texte", text, 2)]


def hook(largeur: float, hauteur: float, profondeur: float, epaisseur: float, vis: float) -> list[Part]:
    back = mf.Manifold.cube([largeur, epaisseur, hauteur])
    arm = mf.Manifold.cube([largeur, profondeur, epaisseur])
    tip_h = min(15.0, hauteur / 3)
    tip = mf.Manifold.cube([largeur, epaisseur, tip_h]).translate([0, profondeur - epaisseur, 0])
    part = back + arm + tip
    for z in (hauteur * 0.45, hauteur * 0.8):  # two countersunk screw holes in the back plate
        hole = mf.Manifold.cylinder(epaisseur * 3, vis / 2, vis / 2, 40)
        sink = mf.Manifold.cylinder(vis * 0.6, vis / 2, vis, 40).translate([0, 0, epaisseur * 3 - vis * 0.6])
        both = (hole + sink).rotate([-90, 0, 0]).translate([largeur / 2, epaisseur * 2.0, z])
        part = part - both
    return [("crochet", part, 1)]


def organiser(longueur: float, largeur: float, hauteur: float, cases_x: int, cases_y: int,
              paroi: float, fond: float, rayon: float) -> list[Part]:
    nx, ny = int(cases_x), int(cases_y)
    cw = (longueur - (nx + 1) * paroi) / nx
    cd = (largeur - (ny + 1) * paroi) / ny
    if cw < 5 or cd < 5:
        raise ValueError("compartiments trop petits : moins de cases ou une boîte plus grande")
    solid = _rounded(longueur, largeur, rayon).extrude(hauteur)
    cells = [_rounded(cw, cd, max(0.5, rayon - paroi)).translate([paroi + i * (cw + paroi), paroi + j * (cd + paroi)])
             .extrude(hauteur).translate([0, 0, fond]) for i in range(nx) for j in range(ny)]
    return [("organiseur", solid - mf.Manifold.batch_boolean(cells, mf.OpType.Add), 1)]


@dataclass(frozen=True)
class Kind:
    key: str
    title: str
    description: str
    params: list[Param]
    build: Callable[..., list[Part]]


KINDS = {k.key: k for k in [
    Kind("boite", "Boîte avec couvercle", "Le couvercle s'emboîte grâce à une lèvre ; le jeu règle le serrage.", [
        Param("longueur", "Longueur", 80, 20, 240), Param("largeur", "Largeur", 60, 20, 240), Param("hauteur", "Hauteur", 40, 10, 200),
        Param("paroi", "Épaisseur des parois", 2.0, 1.2, 6), Param("jeu", "Jeu du couvercle", 0.2, 0.05, 0.6),
        Param("rayon", "Rayon des coins", 4, 0, 20)], box),
    Kind("etiquette", "Étiquette en relief (2 couleurs)", "Texte en relief d'une autre couleur : prénom, porte, bocal…", [
        Param("texte", "Texte (retour à la ligne possible)", "Atelier", kind="text"),
        Param("taille_texte", "Hauteur des lettres", 10, 4, 60), Param("epaisseur", "Épaisseur de la plaque", 2.0, 1.2, 6),
        Param("relief", "Relief du texte", 1.0, 0.4, 4), Param("marge", "Marge autour du texte", 4, 1, 20),
        Param("trou", "Trou pour l'accrocher", True, kind="bool")], label),
    Kind("crochet", "Crochet mural", "Deux trous fraisés pour vis ; à imprimer debout, dos à plat.", [
        Param("largeur", "Largeur", 20, 8, 80), Param("hauteur", "Hauteur du dos", 60, 25, 200),
        Param("profondeur", "Profondeur du crochet", 30, 10, 120), Param("epaisseur", "Épaisseur", 5, 3, 15),
        Param("vis", "Diamètre de vis", 4, 2.5, 8)], hook),
    Kind("organiseur", "Organiseur à compartiments", "Pour tiroir ou bureau : nombre de cases réglable.", [
        Param("longueur", "Longueur", 150, 30, 240), Param("largeur", "Largeur", 100, 30, 240), Param("hauteur", "Hauteur", 40, 10, 150),
        Param("cases_x", "Cases en longueur", 3, 1, 12, "", "int"), Param("cases_y", "Cases en largeur", 2, 1, 12, "", "int"),
        Param("paroi", "Épaisseur des cloisons", 1.6, 1.0, 5), Param("fond", "Épaisseur du fond", 1.2, 0.8, 5),
        Param("rayon", "Rayon des coins", 3, 0, 15)], organiser),
]}


def _more() -> list[Kind]:
    from . import parametric_more as pm
    sizes = tuple((k, k) for k in pm.METRIC)
    return [
        Kind("gridfinity", "Bac Gridfinity", "Rangement modulaire standard (grille de 42 mm) : bacs empilables, cases, aimants.", [
            Param("cases_x", "Largeur (cases de 42 mm)", 2, 1, 5, "", "int"), Param("cases_y", "Profondeur (cases)", 1, 1, 5, "", "int"),
            Param("hauteur_u", "Hauteur (unités de 7 mm)", 6, 2, 15, "", "int"),
            Param("compartiments_x", "Compartiments en largeur", 1, 1, 8, "", "int"), Param("compartiments_y", "Compartiments en profondeur", 1, 1, 8, "", "int"),
            Param("aimants", "Trous pour aimants 6 × 2 mm", False, kind="bool"), Param("empilable", "Lèvre pour empiler", True, kind="bool")], pm.gridfinity_bin),
        Kind("gridfinity_base", "Plaque Gridfinity", "La plaque qui reçoit les bacs, à poser au fond d'un tiroir.", [
            Param("cases_x", "Largeur (cases de 42 mm)", 4, 1, 5, "", "int"), Param("cases_y", "Profondeur (cases)", 3, 1, 5, "", "int"),
            Param("aimants", "Trous pour aimants 6 × 2 mm", False, kind="bool")], pm.gridfinity_base),
        Kind("support", "Support de téléphone", "Pour téléphone ou tablette, incliné, avec passage du câble de charge.", [
            Param("largeur", "Largeur", 70, 40, 200), Param("angle", "Inclinaison", 65, 45, 80, "°"),
            Param("epaisseur_appareil", "Épaisseur de l'appareil (coque comprise)", 12, 6, 30),
            Param("hauteur", "Hauteur du dossier", 90, 50, 180), Param("passage_cable", "Passage pour le câble", True, kind="bool")], pm.phone_stand),
        Kind("range_cables", "Range-câbles", "Peigne de bureau : les câbles se clipsent par le dessus.", [
            Param("nombre", "Nombre de câbles", 5, 1, 15, "", "int"), Param("diametre", "Diamètre des câbles", 5, 2, 15),
            Param("profondeur", "Profondeur", 15, 8, 40), Param("paroi", "Épaisseur", 2.0, 1.2, 5),
            Param("vis", "Pattes pour vis (sinon adhésif)", False, kind="bool")], pm.cable_comb),
        Kind("visserie", "Vis, écrou, rondelle, entretoise", "Filetage métrique ISO de M3 à M10 ; le jeu compense le plastique.", [
            Param("piece", "Pièce", "vis", kind="choice", options=(("vis", "Vis tête hexagonale"), ("ecrou", "Écrou"), ("rondelle", "Rondelle"), ("entretoise", "Entretoise"))),
            Param("taille", "Taille", "M8", kind="choice", options=sizes), Param("longueur", "Longueur (vis, entretoise)", 20, 4, 120),
            Param("jeu", "Jeu d'impression", 0.15, 0, 0.5)], pm.hardware),
        Kind("engrenage", "Engrenage droit", "Denture en développante, module et nombre de dents au choix.", [
            Param("dents", "Nombre de dents", 20, 8, 120, "", "int"), Param("module", "Module (taille des dents)", 2.0, 0.5, 5),
            Param("epaisseur", "Épaisseur", 8, 2, 40), Param("alesage", "Alésage (trou central)", 5, 0, 40),
            Param("angle_pression", "Angle de pression", 20, 14.5, 25, "°")], pm.gear),
        Kind("porte_cles", "Porte-clés prénom (2 couleurs)", "Le contour suit les lettres ; le prénom ressort d'une autre couleur.", [
            Param("texte", "Prénom", "Léa", kind="text"),
            Param("police", "Écriture", "simple", kind="choice", options=(("simple", "Simple"), ("manuscrite", "Manuscrite"))),
            Param("taille_texte", "Hauteur des lettres", 14, 6, 40), Param("epaisseur", "Épaisseur", 3, 1.6, 6),
            Param("relief", "Relief du prénom", 1.2, 0.4, 3)], pm.keychain),
        Kind("decoration_noel", "Décoration de Noël prénom", "Boule, étoile ou sapin à suspendre, prénom d'une autre couleur.", [
            Param("forme", "Forme", "boule", kind="choice", options=(("boule", "Boule"), ("etoile", "Étoile"), ("sapin", "Sapin"))),
            Param("texte", "Prénom", "Noël", kind="text"), Param("diametre", "Taille", 70, 40, 150),
            Param("epaisseur", "Épaisseur", 3, 1.6, 6), Param("relief", "Relief du prénom", 1.2, 0.4, 3)], pm.ornament),
        Kind("lithophanie", "Lithophanie photo", "Ta photo en relief : elle apparaît devant une lampe. Impression debout, remplissage 100 %.", [
            Param("photo", "Photo", "", kind="image"), Param("largeur", "Largeur", 100, 40, 200),
            Param("epaisseur_min", "Épaisseur claire", 0.8, 0.4, 2), Param("epaisseur_max", "Épaisseur foncée", 3.0, 1.5, 6),
            Param("cadre", "Cadre", 3, 0, 10)], pm.lithophane),
    ]


KINDS.update({k.key: k for k in _more()})


def catalogue() -> list[dict[str, Any]]:
    return [{"key": k.key, "title": k.title, "description": k.description,
             "params": [p.__dict__ for p in k.params]} for k in KINDS.values()]


def _clean(kind: Kind, values: dict[str, Any]) -> dict[str, Any]:
    out = {}
    for p in kind.params:
        v = values.get(p.name, p.default)
        if p.kind == "text":
            v = str(v)[:80]
        elif p.kind == "image":
            v = str(v or "")
        elif p.kind == "choice":
            if v not in {o for o, _ in p.options}:
                raise ValueError(f"{p.label} : choix « {v} » inconnu")
        elif p.kind == "bool":
            v = v in (True, "true", "1", 1, "on")
        else:
            v = float(v)
            if p.kind == "int":
                v = int(round(v))
            if not p.lo <= v <= p.hi:
                raise ValueError(f"{p.label} : {v:g} hors de {p.lo:g} à {p.hi:g} {p.unit}".strip())
        out[p.name] = v
    return out


def _build(key: str, values: dict[str, Any]) -> tuple[Kind, dict[str, Any], list, np.ndarray, np.ndarray]:
    """The part's meshes: (kind, cleaned values, [(name, vertices, faces, slot)], min corner, max corner)."""
    kind = KINDS.get(key)
    if kind is None:
        raise ValueError(f"pièce inconnue « {key} »")
    args = _clean(kind, values)
    objects = []
    for pname, solid, slot in kind.build(**args):
        m = solid.to_mesh()
        v = np.asarray(m.vert_properties)[:, :3].astype(float)
        f = np.asarray(m.tri_verts).astype(np.int64)
        if len(f):
            objects.append((pname, v, f, slot))
    if not objects:
        raise ValueError("ces cotes ne donnent aucune pièce")
    allv = np.vstack([o[1] for o in objects])
    return kind, args, objects, allv.min(0), allv.max(0)


def preview(key: str, values: dict[str, Any]) -> tuple[bytes, list[float]]:
    """The part as a coloured GLB for the live preview (nothing written), and its size in mm."""
    import trimesh
    from .parametric_more import PREVIEW
    tok = PREVIEW.set(True)
    try:
        _, _, objects, lo, hi = _build(key, values)
    finally:
        PREVIEW.reset(tok)
    # the spools loaded in the CANVAS when the page knows them ("_couleurs", slot 1 first), else the workshop's palette
    given = list(values.get("_couleurs") or [])[:len(colorize.PALETTE)]
    palette = [c if isinstance(c, str) and re.fullmatch(r"#[0-9A-Fa-f]{6}", c) else colorize.PALETTE[i]
               for i, c in enumerate(given)] + colorize.PALETTE[len(given):]   # an empty slot keeps its place
    scene = trimesh.Scene()
    for nm, v, f, slot in objects:
        rgb = tuple(int(palette[slot - 1].lstrip("#")[i:i + 2], 16) for i in (0, 2, 4))
        scene.add_geometry(trimesh.Trimesh(v - [(lo[0] + hi[0]) / 2, (lo[1] + hi[1]) / 2, lo[2]], f, process=False,
                                           face_colors=[*rgb, 255]), node_name=nm)
    return scene.export(file_type="glb"), [round(float(x), 1) for x in hi - lo]


def create(key: str, values: dict[str, Any], name: str | None = None) -> Path:
    """Build the part and write it to the library as a 3MF; returns its path."""
    kind, args, objects, lo, hi = _build(key, values)
    n = max(o[3] for o in objects)
    if (hi - lo)[:2].max() > 246 or (hi - lo)[2] > 246:
        raise ValueError(f"la pièce ({(hi - lo).round(0).astype(int).tolist()} mm) ne tient pas sur le plateau")
    offset = np.array([128 - (lo[0] + hi[0]) / 2, 128 - (lo[1] + hi[1]) / 2, -lo[2]])
    # parts that touch (the label's text on its plate) must be one object; separate pieces stay apart
    if key == "etiquette":
        project = threemf.Project([threemf.Object(kind.title, [threemf.Part(nm, v, f, sl) for nm, v, f, sl in objects])], [])
    else:
        project = threemf.Project([threemf.Object(nm, [threemf.Part(nm, v, f, sl)]) for nm, v, f, sl in objects], [])
    stem = name or (re.sub(r"[^\w-]+", "_", str(args.get("texte", "")).strip())[:24] if key == "etiquette" else "") or key
    out = config.MODELS_DIR / f"{key}_{stem}.3mf" if stem != key else config.MODELS_DIR / f"{key}.3mf"
    k = 1
    while out.exists():
        k += 1
        out = out.with_name(f"{out.stem.rsplit(' (', 1)[0]} ({k}).3mf")
    threemf.write(project, out, filaments=n, colours=colorize.PALETTE[:n], offset=offset)
    return out
