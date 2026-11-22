"""Several library models on one plate: a new 3MF holding each model as its own pieces, side by side.

Each model keeps its colours. Models that share a colour share a spool, and four colours at most are allowed
(the CANVAS has four spools). Once the plate is made, it behaves like any model made of several pieces: the
viewer moves each piece and changes its size, and the slicer does the same.
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any

import numpy as np

from . import colorize, colors, config, threemf

GAP_MM = 10.0  # between two models on the plate
MAX_MODELS = 6


def _as_extruders(path: Path, tmp: Path) -> threemf.Project:
    """The model with its colours as extruders and paint (a coloured mesh, such as a GLB, is read the slicer's way)."""
    pr = colors._load(path)
    if not colors._rgb_mode(pr):
        return pr
    found = colors.analyze(path)["colours"]
    out = tmp / f"{path.stem}.3mf"
    colors.to_canvas(path, out, {c["index"]: min(c["index"], colors.MAX_SLOTS) for c in found})
    return threemf.read(out)


def combine(paths: list[Path], out: Path | None = None) -> dict[str, Any]:
    """Write the models of ``paths`` side by side in one 3MF of the library; returns its name, size and colours."""
    if not 2 <= len(paths) <= MAX_MODELS:
        raise ValueError(f"choisis de 2 à {MAX_MODELS} modèles")
    colours: list[str] = []
    objects: list[threemf.Object] = []
    x = 0.0
    with tempfile.TemporaryDirectory() as tmp:
        for path in paths:
            pr = _as_extruders(path, Path(tmp))
            used = sorted({p.extruder for o in pr.objects for p in o.parts})
            remap = {}
            for e in used:
                hexc = (
                    pr.colours[e - 1] if e - 1 < len(pr.colours) else colorize.PALETTE[(e - 1) % 4]
                ).upper()
                if hexc not in colours:
                    colours.append(hexc)
                remap[e] = colours.index(hexc) + 1
            # painted faces name their colour by extruder too: every state the paint uses must follow
            for o in pr.objects:
                for p in o.parts:
                    for code in p.paint or []:
                        if code:
                            for s in colors.paint_states(code):
                                if s and s not in remap:
                                    hexc = (
                                        pr.colours[s - 1]
                                        if s - 1 < len(pr.colours)
                                        else colorize.PALETTE[(s - 1) % 4]
                                    ).upper()
                                    if hexc not in colours:
                                        colours.append(hexc)
                                    remap[s] = colours.index(hexc) + 1
            if len(colours) > colors.MAX_SLOTS:
                raise ValueError(
                    f"ces modèles ont {len(colours)} couleurs en tout : la CC2 n'a que 4 bobines"
                )
            parts = [p for o in pr.objects for p in o.parts]
            allv = np.vstack([p.vertices for p in parts])
            lo, hi = allv.min(0), allv.max(0)
            move = np.array([x - lo[0], -(lo[1] + hi[1]) / 2, -lo[2]])
            x += float(hi[0] - lo[0]) + GAP_MM
            single = len(pr.objects) == 1
            for o in pr.objects:
                for p in o.parts:
                    p.vertices = p.vertices + move
                    p.extruder = remap.get(p.extruder, 1)
                    if p.paint:
                        p.paint = [colors.remap_paint(c, remap) if c else None for c in p.paint]
                objects.append(
                    threemf.Object(path.stem if single else f"{path.stem} · {o.name}", o.parts)
                )
    width = x - GAP_MM
    if width > 246:  # the plate less the CC2's forbidden front-right corner
        raise ValueError(
            f"côte à côte, ces modèles font {width:.0f} mm de large : trop pour le plateau, réduis-en un d'abord"
        )
    if out is None:
        stem = " + ".join(p.stem for p in paths)[:80]
        out = config.MODELS_DIR / f"{stem}.3mf"
        k = 2
        while out.exists():
            out = config.MODELS_DIR / f"{stem} ({k}).3mf"
            k += 1
    threemf.write(
        threemf.Project(objects, colours),
        out,
        filaments=len(colours),
        colours=colours,
        flush=colors.flush_matrix(colours),
    )
    return {
        "name": out.name,
        "pieces": len(objects),
        "colours": colours,
        "width_mm": round(width, 1),
    }


def remove(
    path: Path,
    index: int,
    *,
    moves: dict[int, tuple[float, float, float]] | None = None,
    scales: dict[int, float] | None = None,
) -> dict[str, Any]:
    """Write a new plate model without object ``index``; the original is never touched.

    ``moves``/``scales`` are the viewer's placements (object index -> translation in mm / size
    factor): indexes past the removed piece shift down by one, so a layout in progress survives.
    """
    with tempfile.TemporaryDirectory() as tmp:
        pr = _as_extruders(path, Path(tmp))
        if not 0 <= index < len(pr.objects):
            raise ValueError("cette pièce n'est pas sur ce plateau")
        if len(pr.objects) < 2:
            raise ValueError(
                "cette pièce est seule : supprime le modèle entier depuis la bibliothèque"
            )
        gone = pr.objects.pop(index)

        for k, d in (
            moves or {}
        ).items():  # the pieces the user already moved, minus the deleted one
            j = k if k < index else k - 1
            if k != index and 0 <= j < len(pr.objects):
                for p in pr.objects[j].parts:
                    p.vertices = p.vertices + np.asarray(d, float)
        for k, f in (
            scales or {}
        ).items():  # resized about its foot (same rule as the slicer): stays put
            j = k if k < index else k - 1
            if k != index and 0 <= j < len(pr.objects) and f != 1:
                v = np.vstack([p.vertices for p in pr.objects[j].parts])
                a, b = v.min(0), v.max(0)
                c = np.array([(a[0] + b[0]) / 2, (a[1] + b[1]) / 2, a[2]])
                for p in pr.objects[j].parts:
                    p.vertices = c + (p.vertices - c) * f

        # the colours still in use (same walk as combine): no empty spool left in the new plate
        colours: list[str] = []
        remap: dict[int, int] = {}

        def colour_of(e: int) -> None:
            hexc = (
                pr.colours[e - 1] if e - 1 < len(pr.colours) else colorize.PALETTE[(e - 1) % 4]
            ).upper()
            if hexc not in colours:
                colours.append(hexc)
            remap[e] = colours.index(hexc) + 1

        for o in pr.objects:
            for p in o.parts:
                for e in sorted(
                    {p.extruder}
                    | {s for c in p.paint or [] if c for s in colors.paint_states(c)} - {0}
                ):
                    if e not in remap:
                        colour_of(e)
        for o in pr.objects:
            for p in o.parts:
                p.extruder = remap.get(p.extruder, 1)
                if p.paint:
                    p.paint = [colors.remap_paint(c, remap) if c else None for c in p.paint]

        label = gone.name.split(" · ")[-1]
        stem = " ".join((path.stem, "sans", label))[:120]
        out = config.MODELS_DIR / f"{stem}.3mf"
        k = 2
        while out.exists():
            out = config.MODELS_DIR / f"{stem} ({k}).3mf"
            k += 1
        threemf.write(
            threemf.Project(pr.objects, colours),
            out,
            filaments=len(colours),
            colours=colours,
            flush=colors.flush_matrix(colours),
        )
    return {"name": out.name, "piece": label, "pieces": len(pr.objects), "colours": colours}
