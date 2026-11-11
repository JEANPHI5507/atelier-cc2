"""Test pieces for the day the printer arrives: first layer, calibration cube, CANVAS colours, dowel fit.

Each test is generated on demand (exact geometry, nothing downloaded) into ``models/`` and comes with
what to look at once printed. Colour tests are written as painted 3MF so they exercise the CANVAS.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import manifold3d as mf
import numpy as np
import trimesh

from . import colorize, colors, config, mesh

BED = mesh.BED_MM


@dataclass(frozen=True)
class Test:
    key: str
    title: str
    purpose: str
    look_for: list[str]
    colours: int                 # CANVAS slots used
    file: str
    build: Callable[[Path], None]
    slice_opts: dict
    bands: tuple[str, float, float, float] | None = None   # (G-code with {v}, first value, step, band height mm)


def _mf(m: mf.Manifold) -> trimesh.Trimesh:
    out = m.to_mesh()
    return trimesh.Trimesh(np.asarray(out.vert_properties)[:, :3], np.asarray(out.tri_verts), process=False)


def _first_layer(out: Path) -> None:
    """Five 30 mm squares one layer thick: four corners and the centre."""
    sq = 30.0
    m = 20.0  # distance from the bed edge
    centres = [(m + sq / 2, m + sq / 2), (BED - m - sq / 2, m + sq / 2), (m + sq / 2, BED - m - sq / 2),
               (BED - m - sq / 2, BED - m - sq / 2), (BED / 2, BED / 2)]
    boxes = []
    for x, y in centres:
        b = trimesh.creation.box((sq, sq, 0.2))
        b.apply_translation((x, y, 0.1))
        boxes.append(b)
    trimesh.util.concatenate(boxes).export(out)


def _tower(out: Path) -> None:
    """Hollow 30 mm square tower, 42 mm tall, on a 2 mm base: sharp corners show pressure advance and flow."""
    outer = mf.Manifold.cube([30, 30, 42])
    inner = mf.Manifold.cube([26.8, 26.8, 42]).translate([1.6, 1.6, 2])
    _mf((outer - inner).translate([BED / 2 - 15, BED / 2 - 15, 0])).export(out)


def tune(gcode: Path, test: "Test") -> list[dict[str, float]]:
    """Give each band of the tower its own value: the command goes in at the first layer of the band.
    The slicer's own pressure advance lines are commented out so they cannot undo the bands, and the
    flow factor is reset at the end so the next print is normal. Returns [{"from_mm", "to_mm", "value"}]."""
    cmd, start, step, band = test.bands
    out, bands, cur, last_k = [], [], None, -1
    lines = gcode.read_text(errors="ignore").splitlines(keepends=True)
    for i, line in enumerate(lines):
        if line.startswith("SET_PRESSURE_ADVANCE") and cmd.startswith("SET_PRESSURE_ADVANCE"):
            line = "; (tour de calibration) " + line
        elif line.startswith(";LAYER_CHANGE") and i + 1 < len(lines) and lines[i + 1].startswith(";Z:"):
            z = float(lines[i + 1][3:])
            k = max(0, int((z - 2 - 1e-6) // band)) if z > 2 else -1   # the 2 mm base keeps the first value
            v = round(start + step * max(k, 0), 4)
            if v != cur:
                out.append(cmd.format(v=v) + " ; tour de calibration\n")
                cur = v
            if k > last_k:
                bands.append({"from_mm": 2 + k * band, "to_mm": 2 + (k + 1) * band, "value": v})
                last_k = k
        out.append(line)
    if cmd.startswith("M221"):
        out.append("M221 S100 ; débit normal pour la suite\n")
    tmp = gcode.with_suffix(".tmp")
    tmp.write_text("".join(out))
    tmp.replace(gcode)
    return bands


def _cube(out: Path) -> None:
    """20 mm cube with an engraved X on top (orientation: the X sits over the X axis)."""
    cube = mf.Manifold.cube([20, 20, 20])
    bar = mf.Manifold.cube([14, 1.6, 1.0]).translate([-7, -0.8, 0])
    x_mark = (bar.rotate([0, 0, 45]) + bar.rotate([0, 0, -45])).translate([10, 10, 19.4])
    _mf(cube - x_mark).export(out)


def _canvas(out: Path) -> None:
    """Small tower painted in 4 bands (T0 bottom → T3 top) plus a 4-colour checker on the top face:
    checks every spool, the colour order and colour bleeding in the economy mode."""
    tower = trimesh.creation.box((24, 24, 32)).subdivide().subdivide().subdivide()
    tower.apply_translation((0, 0, 16))
    c = tower.triangles_center
    band = np.clip((c[:, 2] // 8).astype(int), 0, 3) + 1
    top = c[:, 2] > 31.9
    checker = ((np.floor((c[:, 0] + 12) / 6) + np.floor((c[:, 1] + 12) / 6)) % 4).astype(int) + 1
    slots = np.where(top, checker, band)
    pal = np.array([[229, 57, 53], [30, 136, 229], [67, 160, 71], [253, 216, 53]])
    tower.visual.face_colors = np.c_[pal[slots - 1], np.full(len(slots), 255)]
    tmp = out.with_suffix(".ply")
    tower.export(tmp)
    try:
        colors.to_canvas(tmp, out, {i: i for i in range(1, 5)})
    finally:
        tmp.unlink(missing_ok=True)


def _dowels(out: Path) -> None:
    """A plate with 5 holes of increasing play (0.05 → 0.25 mm) and the matching dowel to try in each."""
    from . import cut
    plate = mf.Manifold.cube([70, 16, 8]).translate([0, 0, 0])
    for i, play in enumerate(DOWEL_PLAYS):
        r = cut.PIN_D / 2 + play
        plate = plate - mf.Manifold.cylinder(10, r, r, 64).translate([8 + i * 13.5, 8, 2])
    # engraved marks: 1 to 5 notches next to each hole, read from the play table
    for i in range(len(DOWEL_PLAYS)):
        for k in range(i + 1):
            plate = plate - mf.Manifold.cube([1.0, 2.5, 1.0]).translate([3 + i * 13.5 + k * 1.8, 0.8, 7.4])
    pin = mf.Manifold.cylinder(2 * cut.PIN_DEPTH - 1, cut.PIN_D / 2, cut.PIN_D / 2, 64).translate([85, 8, 0])
    _mf(plate + pin).export(out)


DOWEL_PLAYS = [0.05, 0.10, 0.15, 0.20, 0.25]

TESTS = [
    Test("premiere_couche", "Première couche", "Vérifier le nivellement et l'écrasement de la première couche sur tout le plateau.",
         ["Les 5 carrés sont lisses, sans trous entre les lignes (trop haut) ni crêtes ou transparence (trop bas).",
          "Les carrés des coins ressemblent à celui du centre : sinon relancer le nivellement automatique.",
          "Ils se décollent d'une pièce, sans se déchirer."],
         1, "calibration_premiere_couche.stl", _first_layer, {}),
    Test("cube", "Cube de calibration 20 mm", "Contrôler dimensions, angles et qualité des parois.",
         ["Au pied à coulisse : 20,0 mm sur X, Y et Z (± 0,2 mm).",
          "Le X gravé sur le dessus est net et à 0,6 mm de profondeur.",
          "Angles nets, parois sans vagues ni décalage de couche."],
         1, "calibration_cube_20mm.stl", _cube, {}),
    Test("canvas", "Test CANVAS 4 couleurs (mode Économie)", "Vérifier les 4 bobines, leur ordre et la propreté des changements sans tour d'essuyage.",
         ["Bandes de bas en haut : bobines 1, 2, 3, 4, dans les couleurs chargées.",
          "Damier à 4 couleurs sur le dessus, sans traînées d'une couleur dans l'autre.",
          "Si des bavures ou mélanges apparaissent aux frontières : utiliser le mode Équilibré (avec tour)."],
         4, "calibration_canvas_4couleurs.3mf", _canvas, {"mode": "economie"}),
    Test("chevilles", "Ajustement des chevilles", "Choisir le jeu des trous utilisé pour assembler les pièces découpées.",
         ["Essaie la cheville dans chaque trou (1 à 5 encoches = jeu 0,05 à 0,25 mm).",
          "Retiens le premier trou où elle entre à la main, serrée mais sans forcer.",
          "Reporte ce jeu dans « Jeu des chevilles » ci-dessous : toutes les prochaines découpes l'utiliseront."],
         1, "calibration_chevilles.stl", _dowels, {"infill": 100}),
]
TESTS += [
    Test("avance", "Tour de pressure advance", "Régler la pressure advance : angles nets, sans renflement ni manque.",
         ["La tour change de valeur tous les 2,5 mm au-dessus du socle (0,000 en bas, +0,005 par bande).",
          "Repère la hauteur où les angles sont les plus nets (ni arrondis gonflés, ni trous juste après l'angle).",
          "Valeur = la bande lue sous la tour (résultat du tranchage) : reporte-la dans Réglages avancés → Pressure advance."],
         1, "calibration_tour_avance.stl", _tower, {"usage": "profil"}, ("SET_PRESSURE_ADVANCE ADVANCE={v}", 0.0, 0.005, 2.5)),
    Test("debit", "Tour de débit", "Régler le débit : parois pleines sans surépaisseur.",
         ["La tour change de débit tous les 4 mm au-dessus du socle (90 % en bas, +2 % par bande).",
          "Choisis la bande la plus lisse, sans trous entre les lignes ni bourrelets, paroi au pied à coulisse la plus proche de 1,6 mm.",
          "Débit = le pourcentage de cette bande × 0,98 (débit du profil) : reporte-le dans Réglages avancés → Débit."],
         1, "calibration_tour_debit.stl", _tower, {"usage": "profil"}, ("M221 S{v:g}", 90, 2, 4.0)),
]
BY_KEY = {t.key: t for t in TESTS}


def ensure(test: Test) -> Path:
    """Build the test file in the library if missing; returns its path."""
    path = config.MODELS_DIR / test.file
    if not path.exists():
        config.MODELS_DIR.mkdir(exist_ok=True)
        test.build(path)
    return path


def palette() -> list[str]:
    return colorize.PALETTE
