"""From any model in the library to G-code in one step: colours -> CANVAS slots, scale, slice.

Shared by the web workshop and the ``cc2 slice`` command so both behave the same.
"""

from __future__ import annotations

import re

from pathlib import Path
from typing import Any

import numpy as np
import trimesh

from . import colorize, colors, config, cut, mesh, settings, slicer, thumbnail

SLICEABLE_AS_IS = {".stl", ".obj"}

# multicolour print modes: OrcaSlicer's prime tower is ~90 % of the filament of a small multicolour model
# A tower of PLA Silk knocked over at layer 84 on the real CC2 (2026-11-11): the nozzle comes back from each purge
# (at 240 °C, Elegoo's change macro) oozing, the string curls into loops on top of the tower, and with OrcaSlicer's
# 0.4 mm hop the nozzle catches them on the next pass. A wider brim holds the tower, a 0.8 mm hop clears the loops.
# The CC2 purges in its waste chute, so OrcaSlicer's tower only gets the small prime and comes out a thin wall
# (34 x 5.5 mm at Elegoo's 35 mm width): it came unstuck from the first layers on 2026-11-13. A 20 mm wide tower
# with the same plastic is about twice as deep, so it stands on a much larger footprint.
TOWER = {"overrides": {"prime_tower_brim_width": "8", "prime_tower_width": "20"},
         "filament": {"filament_z_hop": ["0.8"]}}
MODES = {
    "qualite":   {"smart_flush": False, "overrides": TOWER["overrides"], "filament": TOWER["filament"]},
    "equilibre": {"smart_flush": True,  "overrides": TOWER["overrides"], "filament": TOWER["filament"]},
    "economie":  {"smart_flush": True,  "overrides": {"enable_prime_tower": "0"}},
    # no tower and no flush at all: the colour change is only the CANVAS switch (see slicer.without_purge)
    "sans_purge": {"smart_flush": True, "overrides": {"enable_prime_tower": "0"}, "no_purge": True},
}
DEFAULT_MODE = "economie"
SMALL_PIECE_MM = 40.0  # cut pieces up to this size share the dowels' plate

# What the part is for decides where the plastic goes. Measured on the CC2 profile (95 mm figurine,
# 0.20 mm): "lightning" infill only holds the top skins up -> 26 g / 2 h 13 instead of 62 g / 3 h 35,
# same outside. A part that has to resist gets walls and a real infill instead.
USAGES: dict[str, dict[str, Any]] = {
    "decoratif": {"label": "Décoratif", "quality": "0.20mm Standard",
                  "hint": "Figurine, déco, cadeau : même aspect, intérieur allégé (jusqu'à −55 % de filament).",
                  "overrides": {"sparse_infill_pattern": "lightning", "sparse_infill_density": "8%", "wall_loops": "2",
                                "top_shell_layers": "5"}},
    "fonctionnel": {"label": "Solide", "quality": "0.20mm Strength",
                    "hint": "Support, crochet, boîte, pièce qui force : 4 parois et remplissage gyroïde.",
                    "overrides": {"sparse_infill_pattern": "gyroid", "sparse_infill_density": "15%", "wall_loops": "4"}},
    "detaille": {"label": "Détaillé", "quality": "0.12mm Fine",
                 "hint": "Miniature, petit texte, visage : couches fines (plus long), intérieur allégé.",
                 "overrides": {"sparse_infill_pattern": "lightning", "sparse_infill_density": "10%", "wall_loops": "2"}},
    "rapide": {"label": "Rapide", "quality": "0.24mm Draft",
               "hint": "Essai, prototype : couches épaisses, le moins de temps et de filament.",
               "overrides": {"sparse_infill_pattern": "lightning", "sparse_infill_density": "8%", "wall_loops": "2"}},
    # Single-colour fast-and-clean: the filament's volumetric flow (21 mm³/s for Elegoo PLA) is the real ceiling, so 0.20 mm
    # layers at 250 mm/s cost about what 0.28 mm ones do. Only the visible outer wall stays at the profile's pace.
    "turbo": {"label": "Turbo", "quality": "0.20mm Standard",
              "hint": "Monocouleur rapide et propre : couches de 0,20 mm, intérieur et accélérations poussés, "
                      "paroi extérieure au rythme du profil Elegoo.",
              "overrides": {"sparse_infill_pattern": "lightning", "sparse_infill_density": "5%", "wall_loops": "2",
                            "top_shell_layers": "5", "inner_wall_speed": "250", "sparse_infill_speed": "250",
                            "internal_solid_infill_speed": "250", "inner_wall_acceleration": "15000",
                            "sparse_infill_acceleration": "20000", "travel_acceleration": "20000",
                            "travel_speed": "500"}},
    "profil": {"label": "Profil Elegoo", "quality": None, "hint": "Les réglages d'origine du profil CC2, sans changement.",
               "overrides": {}},
}
DEFAULT_USAGE = "decoratif"


def usage_overrides(usage: str | None, infill: int | None) -> dict[str, str]:
    if usage not in USAGES:
        raise ValueError(f"usage inconnu « {usage} »")
    ov = dict(USAGES[usage]["overrides"])
    if infill is not None:          # the user's own infill wins over the usage's
        ov.pop("sparse_infill_density", None)
    return ov


def suggest_usage(src: Path) -> str:
    """Parts made by the workshop's generators are functional; everything else is shown as decorative."""
    stem = src.stem.lower()
    return "fonctionnel" if stem.startswith(("boite", "crochet", "organiseur", "calibration_chevilles")) else DEFAULT_USAGE


# support styles offered to the user; the CC2 profile already defaults to organic tree supports
SUPPORTS = {
    "aucun": None,
    "arbre": {},
    "arbre_fin": {"support_style": "tree_slim"},
    "arbre_solide": {"support_style": "tree_strong"},
    "colonnes": {"support_type": "normal(auto)"},
}


def support_overrides(supports: bool | str, plate_only: bool = False) -> tuple[bool, dict[str, str]]:
    """``supports``: True/False or a key of SUPPORTS. Returns (enable, process overrides)."""
    key = ("arbre" if supports else "aucun") if isinstance(supports, bool) else supports
    if key not in SUPPORTS:
        raise ValueError(f"supports inconnus « {key} » ({', '.join(SUPPORTS)})")
    ov = SUPPORTS[key]
    if ov is None:
        return False, {}
    return True, {**ov, **({"support_on_build_plate_only": "1"} if plate_only else {})}


def prepare_and_slice(
    src: Path,
    *,
    mapping: dict[int, int] | None = None,
    filaments: list[str] | None = None,
    quality: str = slicer.DEFAULT_QUALITY,
    infill: int | None = None,
    supports: bool | str = False,
    plate_only: bool = False,
    height_mm: float | None = None,
    mode: str = DEFAULT_MODE,
    split: bool = False,
    slot_colours: dict[int, str] | None = None,
    plate: str = settings.DEFAULT_PLATE,
    advanced: dict[str, Any] | None = None,
    rotate: tuple[float, ...] | None = None,
    copies: int = 1,
    orient: bool = False,
    usage: str = "profil",
    out_dir: Path | None = None,
    palette: colors.Palette | None = None,
    pauses_mm: list[float] | None = None,
    simplify_colours: bool | str = "leger",
    moves: dict[int, tuple[float, float, float]] | None = None,
    shift: tuple[float, float] | None = None,
) -> dict[str, Any]:
    """``mapping``: source colour index -> slot (1..4); colours not listed keep the suggested slot.
    ``palette``: the loaded spools' colours (slot 1 first): the model is repainted with them first.
    ``filaments``: one per slot, padded with PLA. ``advanced``: see settings.CHOICES/NUMBERS/TEMPS.
    ``pauses_mm``: heights of the finished model where the print stops (magnet, nut, colour swap)."""
    warnings: list[str] = []
    out_dir = out_dir or config.MODELS_DIR  # read at call time (tests and tools point it elsewhere)
    out_dir.mkdir(parents=True, exist_ok=True)
    adv_proc, adv_fil = settings.build(advanced, plate)
    adv_proc = {**usage_overrides(usage, infill), **adv_proc}   # the advanced fields stay the last word
    if not 1 <= copies <= 50:
        raise ValueError("nombre d'exemplaires entre 1 et 50")
    cli = ["--orient", "1"] if orient else []
    rot = colors.rotation(rotate)
    if not height_mm:
        size = mesh.info(src)
        if size.get("unitless"):
            height_mm = mesh.DEFAULT_AI_HEIGHT_MM
            warnings.append(f"Modèle sans unité réelle ({max(size['size_mm'])} « mm ») : mis à "
                            f"{height_mm:.0f} mm de haut. Indique une hauteur pour changer.")
    if mode not in MODES:
        raise ValueError(f"mode inconnu « {mode} » (qualite, equilibre, economie, sans_purge)")
    info = colors.analyze(src, palette)
    slots = {c["index"]: (mapping or {}).get(c["index"], c["slot"]) for c in info["colours"]}
    n = max(slots.values())
    fil = ((filaments or []) + ["PLA"] * n)[:n]

    size = np.array(mesh.info(src)["size_mm"], float)
    if rot is not None:
        size = np.abs(rot) @ size  # quarter turns swap the dimensions
    final = size * (height_mm / size[2]) if height_mm else size
    if final.max() > mesh.BED_MM - cut.MARGIN_MM:
        if copies > 1:
            raise ValueError("plusieurs exemplaires d'un modèle à découper : imprime d'abord un exemplaire")
        if not split:
            raise ValueError(f"trop grand pour le plateau ({final.round(0).astype(int).tolist()} mm, maximum "
                             f"{mesh.BED_MM - cut.MARGIN_MM:.0f}) : réduis la hauteur ou active « Découper en pièces »")
        if pauses_mm:   # each piece has its own heights: a pause on the whole model has no layer to go to
            warnings.append("Pause ignorée : la pièce est découpée en morceaux, chacun avec sa propre hauteur.")
        return _split_and_slice(src, slots, fil, quality=quality, infill=infill, supports=supports,
                                plate_only=plate_only, height_mm=height_mm, mode=mode, out_dir=out_dir, warnings=warnings,
                                slot_colours=slot_colours, adv=(adv_proc, adv_fil), rotate=rotate, palette=palette)

    target, slot_hex = src, None
    if n > 1 or src.suffix.lower() not in SLICEABLE_AS_IS or height_mm or rot is not None or copies > 1 or moves:
        base = src
        if height_mm and src.suffix.lower() == ".stl":
            base = out_dir / f".{src.stem}_scaled.stl"
            mesh.prepare(src, base, height_mm=height_mm)
        target = out_dir / f"{src.stem}_canvas.3mf"
        try:
            conv = colors.to_canvas(base, target, slots, height_mm=height_mm, rotate=rotate, copies=copies, moves=moves, shift=shift,
                                    smart_flush=MODES[mode]["smart_flush"], palette=palette,
                                    simplify=colors.SIMPLIFY_LEVELS.get(simplify_colours, colors.SIMPLIFY_SHARE) if isinstance(simplify_colours, str)
                                    else (colors.SIMPLIFY_SHARE if simplify_colours else 0.0),
                                    layer_mm=float(re.match(r"[\d.]+", quality).group()) if re.match(r"[\d.]+", quality) else 0.2)
            slot_hex = conv["slot_colours"]
            if conv.get("simplified"):
                warnings.append(f"{conv['simplified']} petite(s) tache(s) de couleur fondue(s) dans la couleur voisine : "
                                f"autant de changements et de purges en moins (« Simplifier les couleurs »).")
        finally:
            if base != src:
                base.unlink(missing_ok=True)

    slot_hex = _real_colours(slot_hex, slot_colours, n)
    sup_on, sup_ov = support_overrides(supports, plate_only)
    try:
        res = slicer.slice_model(target, out_dir, quality=quality, filament=fil, infill=infill, supports=sup_on,
                                 colours=slot_hex, no_purge=bool(MODES[mode].get("no_purge")) and n > 1, overrides={**(MODES[mode]["overrides"] if n > 1 else {}), **sup_ov,
                                                      # several parts: the CC2 can drop one that fails and finish the others
                                                      # (its firmware reads EXCLUDE_OBJECT_DEFINE like Klipper); one part: profile as is
                                                      **({"exclude_object": "1"} if copies > 1 else {}), **adv_proc},
                                 filament_overrides={**(MODES[mode].get("filament", {}) if n > 1 else {}), **adv_fil}, cli_args=cli)
    except slicer.SupportNeeded:   # OrcaSlicer found parts that would hang in the air: tree supports, said in the result
        warnings.append("Supports en arbre ajoutés : OrcaSlicer a trouvé des parties qui flotteraient sans support.")
        res = slicer.slice_model(target, out_dir, quality=quality, filament=fil, infill=infill, supports=True,
                             colours=slot_hex, no_purge=bool(MODES[mode].get("no_purge")) and n > 1, overrides={**(MODES[mode]["overrides"] if n > 1 else {}), **sup_ov,
                                                  # several parts: the CC2 can drop one that fails and finish the others
                                                  # (its firmware reads EXCLUDE_OBJECT_DEFINE like Klipper); one part: profile as is
                                                  **({"exclude_object": "1"} if copies > 1 else {}), **adv_proc},
                             filament_overrides={**(MODES[mode].get("filament", {}) if n > 1 else {}), **adv_fil}, cli_args=cli)
    _thumb_model(src, slots, rot, slot_hex, res.gcode, warnings, palette)
    palette = slot_hex or colorize.PALETTE
    per = res.per_filament_m + [0.0] * n
    purge = res.purge_m + [0.0] * n
    out = res.as_dict()
    out["warnings"] = warnings + out["warnings"]
    if pauses_mm:
        out["pauses"] = add_pauses(res.gcode[0], pauses_mm)
        if len(out["pauses"]) < len(set(pauses_mm)):
            out["warnings"].append("Une pause tombe au-dessus de la pièce ou sur la même couche qu'une autre : elle est ignorée.")
    return {
        **out,
        "colours": info["colours"],
        "mode": mode, "usage": usage,
        "slots": [{"slot": i + 1, "tool": f"T{i}", "filament": f, "colour": palette[i],
                   "metres": round(per[i] + purge[i], 2), "purge_m": purge[i]}
                  for i, f in enumerate(fil)],
    }


def _real_colours(slot_hex: list[str] | None, slot_colours: dict[int, str] | None, n: int) -> list[str] | None:
    """Colours of the spools really loaded (when known) replace the model's colours slot by slot."""
    if not slot_colours:
        return slot_hex
    base = list(slot_hex or colorize.PALETTE[:n]) + colorize.PALETTE[len(slot_hex or []):n]
    return [slot_colours.get(i + 1, base[i]) for i in range(n)]


def _split_and_slice(src: Path, slots: dict[int, int], fil: list[str], *, quality: str, infill: int | None,
                     supports: bool | str, plate_only: bool, height_mm: float | None, mode: str, out_dir: Path,
                     warnings: list[str], slot_colours: dict[int, str] | None = None,
                     adv: tuple[dict[str, str], dict[str, Any]] = ({}, {}),
                     rotate: tuple[float, ...] | None = None, palette: colors.Palette | None = None) -> dict[str, Any]:
    """Cut a too-big model into pieces with dowel holes; one G-code per piece plus one for the dowels."""
    v, f, face_slots, slot_hex = colors.solid(src, slots, height_mm=height_mm, rotate=rotate, palette=palette)
    slot_hex = _real_colours(slot_hex, slot_colours, len(slot_hex))
    res = cut.cut(v, f, face_slots, name=src.stem)
    n = len(slot_hex)
    sup_on, sup_ov = support_overrides(supports, plate_only)
    pieces, failed = [], []
    small, big = [], []
    for p in res.pieces:  # tiny pieces (spike tips…) go on the dowels' plate instead of a print each
        verts, laid = cut.rest_flat(p.vertices, p.faces)
        (small if np.ptp(verts, axis=0).max() <= SMALL_PIECE_MM else big).append((p, verts, laid))
    for p, verts, laid in big:
        target = out_dir / f"{p.name}.3mf"
        colors.write_piece(verts, p.faces, p.slots, slot_hex, target, name=p.name,
                           smart_flush=MODES[mode]["smart_flush"])
        try:
            r = slicer.slice_model(target, out_dir, quality=quality, filament=fil, infill=infill, supports=sup_on,
                                   colours=slot_hex, no_purge=bool(MODES[mode].get("no_purge")) and n > 1, overrides={**(MODES[mode]["overrides"] if n > 1 else {}), **sup_ov, **adv[0]},
                                   filament_overrides={**(MODES[mode].get("filament", {}) if n > 1 else {}), **adv[1]})
        except slicer.SliceError as err:  # one bad piece must not hide the others
            failed.append(f"{p.name} : {str(err)[:160]}")
            continue
        _thumb(verts, p.faces, np.array([colors._rgb(slot_hex[int(sl) - 1]) for sl in p.slots]), r.gcode, warnings)
        pieces.append({"name": p.name, "size_mm": np.ptp(verts, axis=0).round(1).tolist(), "laid_flat": laid, **r.as_dict()})
    if not pieces:
        raise slicer.SliceError("aucune pièce n'a pu être tranchée : " + " ; ".join(failed))
    warnings += [f"Pièce non tranchée — {msg}" for msg in failed]
    warnings += [f"{p['name']} est posée sur sa face plane pour tenir sur le plateau." for p in pieces if p["laid_flat"]]
    pins = None
    if res.pins is not None or small:
        # one plate for the dowels (printed solid) and the small pieces
        items = [(p.name, v, p.faces, p.slots) for p, v, _ in small]
        if res.pins is not None:
            items += [(f"cheville{k + 1}", np.asarray(c.vertices), np.asarray(c.faces), None)
                      for k, c in enumerate(res.pins.split(only_watertight=False))]
        plate_file = out_dir / f"{src.stem}_petites_pieces.3mf"
        colors.write_plate(items, slot_hex, plate_file, smart_flush=MODES[mode]["smart_flush"])
        r = slicer.slice_model(plate_file, out_dir, quality=quality, filament=fil, infill=100 if not small else infill,
                               colours=slot_hex, no_purge=bool(MODES[mode].get("no_purge")) and n > 1, overrides={**(MODES[mode]["overrides"] if n > 1 else {}), **adv[0]},
                               filament_overrides={**(MODES[mode].get("filament", {}) if n > 1 else {}), **adv[1]})
        lengths = sorted({2 * d - 1 for d in res.pin_depths})
        allv = np.vstack([it[1] for it in items])
        allf = np.vstack([it[2] + sum(len(x[1]) for x in items[:i]) for i, it in enumerate(items)])
        rgb = np.vstack([np.array([colors._rgb(slot_hex[int(sl) - 1]) for sl in (it[3] if it[3] is not None else np.ones(len(it[2]), int))])
                         for it in items])
        _thumb(allv, allf, rgb, r.gcode, warnings)
        pins = {"name": plate_file.stem, "count": res.pin_count, "diameter_mm": cut.PIN_D,
                "length_mm": " ou ".join(f"{x:g}" for x in lengths) if lengths else "-",
                "small_pieces": len(small), **r.as_dict()}
    total = sum(p["total_m"] for p in pieces) + (pins["total_m"] if pins else 0)
    return {
        "split": True, "mode": mode, "pieces": pieces, "pins": pins,
        "planes": [{"axis": "XYZ"[a], "mm": round(float(pos), 1)} for a, pos in res.planes],
        "total_m": round(total, 2),
        "warnings": warnings + [f"Découpé en {len(pieces) + len(small)} pièces"
                                + (f" ({len(small)} petite(s) imprimée(s) avec les chevilles)" if small else "")
                                + (f", {res.pin_count} chevilles de {cut.PIN_D:.0f} mm à coller" if res.pin_count else "") + "."],
        "gcode": [p["gcode"][0] for p in pieces] + ([pins["gcode"][0]] if pins else []),
        "colours": [], "slots": [],
    }


def cut_preview(src: Path, *, mapping: dict[int, int] | None = None, height_mm: float | None = None,
                palette: colors.Palette | None = None) -> tuple[dict[str, Any], trimesh.Trimesh]:
    """Where the model would be cut, plus an exploded, tinted view of the pieces (Y-up for the viewer)."""
    info = colors.analyze(src, palette)
    slots = {c["index"]: (mapping or {}).get(c["index"], c["slot"]) for c in info["colours"]}
    if not height_mm and mesh.info(src).get("unitless"):
        height_mm = mesh.DEFAULT_AI_HEIGHT_MM
    v, f, face_slots, slot_hex = colors.solid(src, slots, height_mm=height_mm, palette=palette)
    res = cut.cut(v, f, face_slots, name=src.stem)
    rgb = {i + 1: colors._rgb(h) for i, h in enumerate(slot_hex)}
    tints = [np.array(t) for t in ((1.0, .92, .82), (.82, .9, 1.0), (.85, 1.0, .85), (1.0, .85, .95), (.95, .95, .8))]
    centre = v.mean(axis=0)
    vs, fs, cs, off = [], [], [], 0
    for i, p in enumerate(res.pieces):
        shift = (p.vertices.mean(axis=0) - centre) * 0.3  # explode outwards
        vs.append(p.vertices + shift)
        fs.append(p.faces + off)
        off += len(p.vertices)
        base = np.array([rgb.get(int(s), np.array([200.0, 200, 200])) for s in p.slots])
        cs.append(np.clip(base * tints[i % len(tints)], 0, 255))
    allv = np.vstack(vs)
    allv = np.c_[allv[:, 0], allv[:, 2], -allv[:, 1]]  # Z-up -> Y-up
    rgba = np.c_[np.vstack(cs), np.full(off and sum(len(x) for x in fs), 255)].astype(np.uint8)
    view = trimesh.Trimesh(allv, np.vstack(fs), face_colors=rgba, process=False)
    summary = {
        "planes": [{"axis": "XYZ"[a], "mm": round(float(pos), 1)} for a, pos in res.planes],
        "pieces": [{"name": p.name, "size_mm": np.ptp(p.vertices, axis=0).round(1).tolist()} for p in res.pieces],
        "pins": res.pin_count,
    }
    return summary, view


def _thumb(v: np.ndarray, f: np.ndarray, rgb: np.ndarray, gcodes: list[Path], warnings: list[str]) -> None:
    """Printer-screen thumbnail; a failure only costs the picture, never the print."""
    try:
        png = thumbnail.render(v, f, rgb)
        for g in gcodes:
            thumbnail.inject(g, png)
    except Exception as err:  # noqa: BLE001
        warnings.append(f"Vignette d'écran non générée ({type(err).__name__}).")


def _thumb_model(src: Path, slots: dict[int, int], rot: np.ndarray | None, slot_hex: list[str] | None,
                 gcodes: list[Path], warnings: list[str], palette: colors.Palette | None = None) -> None:
    m = colors.preview(src, slots, palette)                       # Y-up, one colour per face
    v = np.c_[m.vertices[:, 0], -m.vertices[:, 2], m.vertices[:, 1]]
    if rot is not None:
        v = v @ rot.T
    rgb = m.visual.face_colors[:, :3].astype(float)
    if slot_hex:  # show the spools' real colours rather than the model's
        face_slot = {tuple(colors._rgb(c["hex"]).astype(int)): slots.get(c["index"], 1) for c in colors.analyze(src, palette)["colours"]}
        rgb = np.array([colors._rgb(slot_hex[face_slot.get(tuple(c.astype(int)), 1) - 1]) for c in rgb])
    _thumb(v, np.asarray(m.faces), rgb, gcodes, warnings)


def compare(src: Path, base: dict[str, Any], on_row=None, only_current: bool = False) -> list[dict[str, Any]]:
    """Slice the same model several ways (in a scratch folder) to show what each choice costs.

    ``base`` holds the prepare_and_slice arguments the user picked. Rows: the user's choice, the other
    usages, and for a multicolour model two copies on one plate (colour changes are shared: measured
    on a 4-colour figurine, 2 copies cost 57 g / 11 h instead of 2 × 39 g / 2 × 8 h 45)."""
    import tempfile
    from . import stock
    current = base.get("usage", DEFAULT_USAGE)
    variants = [("Ton choix", {})]
    variants += [(USAGES[u]["label"], {"usage": u, "quality": USAGES[u]["quality"] or slicer.DEFAULT_QUALITY, "infill": None})
                 for u in ("decoratif", "rapide", "detaille", "fonctionnel") if u != current]
    multicolour = len({c["slot"] for c in colors.analyze(src, base.get("palette"))["colours"]}) > 1
    if only_current:     # the estimate shown under the usage buttons: just the user's choice
        variants = variants[:1]
    elif multicolour and int(base.get("copies") or 1) == 1:
        # colour changes happen layer by layer for all copies at once, so the purge is shared:
        # measured on a 4-colour 60 mm figurine, 4 copies cost 24 g and 3 h 44 EACH instead of 51 g and 8 h 33
        variants += [("2 exemplaires ensemble", {"copies": 2}), ("4 exemplaires ensemble", {"copies": 4, "_optional": True})]
    rows = []
    with tempfile.TemporaryDirectory() as tmp:
        for i, (label, change) in enumerate(variants):
            optional = change.pop("_optional", False)
            args = {**base, **change, "split": False}
            try:
                r = prepare_and_slice(src, **args, out_dir=Path(tmp) / str(i))
                u = stock.usage(r.get("per_filament_m") or [], r.get("purge_m"))
                copies = int(args.get("copies") or 1)
                row = {"label": label, "usage": args.get("usage"), "quality": args.get("quality"), "copies": copies,
                       "g": u["g"], "eur": u["eur"], "purge_g": round(sum(t["purge_g"] for t in u["trays"]), 1),
                       "time": r.get("time"), "layers": r.get("layers"), "changes": r.get("colour_changes", 0),
                       "current": not change}
            except (ValueError, slicer.SliceError) as err:
                if optional:      # does not fit on the plate: simply not offered
                    continue
                row = {"label": label, "error": str(err)[:160], "current": not change}
            rows.append(row)
            if on_row:
                on_row(rows)
    return rows


def add_pauses(gcode: Path, heights_mm: list[float]) -> list[dict[str, Any]]:
    """Stop the print once the model is ``h`` mm tall: a ``PAUSE`` before the first layer above h.
    The CC2 firmware's PAUSE parks over the waste box and drops the nozzle to 100 °C; resuming from the
    screen or the app restores the temperature and purges (CentauriCarbon2 elegoo/extras/pause_resume.cpp).
    Returns the pauses really placed: {"mm": asked, "z": layer top before the pause, "layer": 1-based layer}."""
    lines = gcode.read_text(errors="ignore").splitlines(keepends=True)
    marks = [(i, float(lines[i + 1][3:])) for i in range(len(lines) - 1)
             if lines[i].startswith(";LAYER_CHANGE") and lines[i + 1].startswith(";Z:")]
    placed: dict[int, dict[str, Any]] = {}
    for h in sorted(set(heights_mm)):
        for n, (i, z) in enumerate(marks):
            if z > h + 1e-6:
                if n and i not in placed:   # never before the first layer: nothing to pause on yet
                    placed[i] = {"mm": h, "z": marks[n - 1][1], "layer": n + 1}
                break
    for i in sorted(placed, reverse=True):
        lines.insert(i, f"; pause demandée à {placed[i]['mm']:g} mm\nPAUSE\n")
    if placed:
        tmp = gcode.with_suffix(".tmp")
        tmp.write_text("".join(lines))
        tmp.replace(gcode)
    return sorted(placed.values(), key=lambda p: p["z"])
