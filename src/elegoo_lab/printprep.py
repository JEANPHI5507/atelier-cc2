"""From any model in the library to G-code in one step: colours -> CANVAS slots, scale, slice.

Shared by the web workshop and the ``cc2 slice`` command so both behave the same.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

import numpy as np
import trimesh

from . import (
    colorize,
    colors,
    config,
    couches,
    cut,
    library,
    mesh,
    orient,
    settings,
    slicer,
    thumbnail,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

SLICEABLE_AS_IS = {".stl", ".obj"}

# multicolour print modes: OrcaSlicer's prime tower is ~90 % of the filament of a small multicolour model
# A tower of PLA Silk knocked over at layer 84 on the real CC2 (2026-11-11): the nozzle comes back from each purge
# (at 240 °C, Elegoo's change macro) oozing, the string curls into loops on top of the tower, and with OrcaSlicer's
# 0.4 mm hop the nozzle catches them on the next pass. A wider brim holds the tower, a 0.8 mm hop clears the loops.
# The CC2 purges in its waste chute, so OrcaSlicer's tower only gets the small prime and comes out a thin wall
# (34 x 5.5 mm at Elegoo's 35 mm width): it came unstuck from the first layers on 2026-11-13. A 20 mm wide tower
# with the same plastic is about twice as deep, so it stands on a much larger footprint.
TOWER = {
    "overrides": {"prime_tower_brim_width": "8", "prime_tower_width": "20"},
    "filament": {"filament_z_hop": ["0.8"]},
}
MODES: dict[str, dict[str, Any]] = {
    "qualite": {
        "smart_flush": False,
        "overrides": TOWER["overrides"],
        "filament": TOWER["filament"],
    },
    "equilibre": {
        "smart_flush": True,
        "overrides": TOWER["overrides"],
        "filament": TOWER["filament"],
    },
    "economie": {"smart_flush": True, "overrides": {"enable_prime_tower": "0"}},
    # no tower and no flush at all: the colour change is only the CANVAS switch (see slicer.without_purge)
    "sans_purge": {"smart_flush": True, "overrides": {"enable_prime_tower": "0"}, "no_purge": True},
}
DEFAULT_MODE = (
    "equilibre"  # quality first: the nozzle wipes on the tower before returning to the part;
)
# Économie stays one click away, and the result shows what both cost
BLED = {"couleurs", "gouttes"}  # review issues: the purge between colours was not enough


def bled_purge(src: Path) -> bool:
    """True when this model's last review reported bled or dripping colours: the next slice then
    purges every change as the worst case (the "qualite" volumes), whatever multicolour mode is shown.
    """
    r = (library.load_index().get(src.name) or {}).get("retour") or {}
    return bool(BLED & set(r.get("issues", [])))


def plane_json(c: cut.Plane) -> dict[str, Any]:
    out: dict[str, Any] = {"axis": "XYZ"[c.axis], "mm": round(float(c.pos), 1)}
    if c.angle:
        out.update(angle=c.angle, toward="XYZ"[c.lean])
    return out


VIVID = [
    (66.0, 133, 244),
    (52, 168, 83),
    (251, 188, 5),
    (171, 71, 188),
    (255, 112, 67),
    (0, 172, 193),
    (141, 110, 99),
    (120, 144, 156),
]
SMALL_PIECE_MM = 40.0  # cut pieces up to this size share the dowels' plate

# What the part is for decides where the plastic goes. Measured on the CC2 profile (95 mm figurine,
# 0.20 mm): "lightning" infill only holds the top skins up -> 26 g / 2 h 13 instead of 62 g / 3 h 35,
# same outside. A part that has to resist gets walls and a real infill instead.
USAGES: dict[str, dict[str, Any]] = {
    "decoratif": {
        "label": "Décoratif",
        "quality": "0.20mm Standard",
        "hint": "Figurine, déco, cadeau : même aspect, intérieur allégé (jusqu'à −55 % de filament).",
        "overrides": {
            "sparse_infill_pattern": "lightning",
            "sparse_infill_density": "8%",
            "wall_loops": "2",
            "top_shell_layers": "5",
        },
    },
    "fonctionnel": {
        "label": "Solide",
        "quality": "0.20mm Strength",
        "hint": "Support, crochet, boîte, pièce qui force : 4 parois et remplissage gyroïde, paroi extérieure précise.",
        "overrides": {
            "sparse_infill_pattern": "gyroid",
            "sparse_infill_density": "15%",
            "wall_loops": "4",
            "precise_outer_wall": "1",
        },
    },
    "detaille": {
        "label": "Détaillé",
        "quality": "0.12mm Fine",
        "hint": "Miniature, petit texte, visage : couches fines (plus long), intérieur allégé.",
        "overrides": {
            "sparse_infill_pattern": "lightning",
            "sparse_infill_density": "10%",
            "wall_loops": "2",
        },
    },
    "rapide": {
        "label": "Rapide",
        "quality": "0.24mm Draft",
        "hint": "Essai, prototype : couches épaisses, le moins de temps et de filament.",
        "overrides": {
            "sparse_infill_pattern": "lightning",
            "sparse_infill_density": "8%",
            "wall_loops": "2",
        },
    },
    # Single-colour fast-and-clean: the filament's volumetric flow (21 mm³/s for Elegoo PLA) is the real ceiling, so 0.20 mm
    # layers at 250 mm/s cost about what 0.28 mm ones do. Only the visible outer wall stays at the profile's pace.
    "turbo": {
        "label": "Turbo",
        "quality": "0.20mm Standard",
        "hint": "Monocouleur rapide et propre : couches de 0,20 mm, intérieur et accélérations poussés, "
        "paroi extérieure au rythme du profil Elegoo.",
        "overrides": {
            "sparse_infill_pattern": "lightning",
            "sparse_infill_density": "5%",
            "wall_loops": "2",
            "top_shell_layers": "5",
            "inner_wall_speed": "250",
            "sparse_infill_speed": "250",
            "internal_solid_infill_speed": "250",
            "inner_wall_acceleration": "15000",
            "sparse_infill_acceleration": "20000",
            "travel_acceleration": "20000",
            "travel_speed": "500",
        },
    },
    "profil": {
        "label": "Profil Elegoo",
        "quality": None,
        "hint": "Les réglages d'origine du profil CC2, sans changement.",
        "overrides": {},
    },
}
DEFAULT_USAGE = "decoratif"


def usage_overrides(usage: str | None, infill: int | None) -> dict[str, str]:
    if usage not in USAGES:
        raise ValueError(f"usage inconnu « {usage} »")
    ov = dict(USAGES[usage]["overrides"])
    if infill is not None:  # the user's own infill wins over the usage's
        ov.pop("sparse_infill_density", None)
    return ov


def suggest_usage(src: Path) -> str:
    """Parts made by the workshop's generators are functional; everything else is shown as decorative."""
    stem = src.stem.lower()
    return (
        "fonctionnel"
        if stem.startswith(("boite", "crochet", "organiseur", "calibration_chevilles"))
        else DEFAULT_USAGE
    )


# support styles offered to the user; the CC2 profile already defaults to organic tree supports
SUPPORTS = {
    "aucun": None,
    "arbre": {},
    "arbre_fin": {"support_style": "tree_slim"},
    "arbre_solide": {"support_style": "tree_strong"},
    "colonnes": {"support_type": "normal(auto)"},
}


def support_overrides(
    supports: bool | str, plate_only: bool = False
) -> tuple[bool, dict[str, str]]:
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
    scales: dict[int, float] | None = None,
    shift: tuple[float, float] | None = None,
    screen_thumbnail: bool = True,
    forbidden: Sequence[cut.Zone] = (),
    auto_pose: bool = False,
    oblique: bool = False,
    planes: Sequence[cut.Plane] | None = None,
) -> dict[str, Any]:
    """``mapping``: source colour index -> slot (1..4); colours not listed keep the suggested slot.
    ``palette``: the loaded spools' colours (slot 1 first): the model is repainted with them first.
    ``filaments``: one per slot, padded with PLA. ``advanced``: see settings.CHOICES/NUMBERS/TEMPS.
    ``pauses_mm``: heights of the finished model where the print stops (magnet, nut, colour swap).
    ``screen_thumbnail``: draw the printer-screen picture (an estimate never reaches the printer: 1 s saved).
    """
    warnings: list[str] = []
    out_dir = out_dir or config.MODELS_DIR  # read at call time (tests and tools point it elsewhere)
    out_dir.mkdir(parents=True, exist_ok=True)
    adv_proc, adv_fil = settings.build(advanced, plate)
    adv_proc = {
        **usage_overrides(usage, infill),
        **adv_proc,
    }  # the advanced fields stay the last word
    if not 1 <= copies <= 50:
        raise ValueError("nombre d'exemplaires entre 1 et 50")
    # 'suite' = one piece at a time (Orca 'by object'): the pieces of one colour print together and
    # a plate of pieces pays one change per colour instead of one at nearly every layer. Each copy
    # would go through every colour again, so copies keep the layer order and share the changes.
    ordre = ((advanced or {}).get("ordre") or "") if isinstance(advanced, dict) else ""
    if copies > 1 and ordre == "suite":
        adv_proc.pop("print_sequence", None)
        ordre = ""
        warnings.append(
            "Pièce par pièce ignoré : chaque exemplaire reprendrait toutes les couleurs ; "
            "couche par couche, ils se partagent chaque changement."
        )
    cli = ["--orient", "1"] if orient else []
    rot = colors.rotation(rotate)
    if not height_mm:
        base_info = mesh.info(src)
        if base_info.get("unitless"):
            height_mm = mesh.DEFAULT_AI_HEIGHT_MM
            warnings.append(
                f"Modèle sans unité réelle ({max(base_info['size_mm'])} « mm ») : mis à "
                f"{height_mm:.0f} mm de haut. Indique une hauteur pour changer."
            )
    if mode not in MODES:
        raise ValueError(f"mode inconnu « {mode} » (qualite, equilibre, economie, sans_purge)")
    info = colors.analyze(src, palette)
    slots = {c["index"]: (mapping or {}).get(c["index"], c["slot"]) for c in info["colours"]}
    n = max(slots.values())
    fil = ((filaments or []) + ["PLA"] * n)[:n]
    # colours bled at the last print of this model: every change purges the worst case, even in a lighter mode
    flush = MODES[mode]["smart_flush"] and n > 1 and not MODES[mode].get("no_purge")
    if flush and bled_purge(src):
        flush = False
        warnings.append(
            "Purge renforcée : ta dernière impression signalait des couleurs qui bavent."
        )

    size = np.array(mesh.info(src)["size_mm"], float)
    if rot is not None:
        size = np.abs(rot) @ size  # quarter turns swap the dimensions
    final: np.ndarray = size * (height_mm / size[2]) if height_mm else size
    if final.max() > mesh.BED_MM - cut.MARGIN_MM:
        if copies > 1:
            raise ValueError(
                "plusieurs exemplaires d'un modèle à découper : imprime d'abord un exemplaire"
            )
        if not split:
            raise ValueError(
                f"trop grand pour le plateau ({mesh.size_text(final)}, maximum "
                f"{mesh.BED_MM - cut.MARGIN_MM:.0f} mm de chaque côté) : réduis la hauteur ou active « Découper en pièces »"
            )
        if (
            pauses_mm
        ):  # each piece has its own heights: a pause on the whole model has no layer to go to
            warnings.append(
                "Pause ignorée : la pièce est découpée en morceaux, chacun avec sa propre hauteur."
            )
        if ordre == "suite":  # the pieces are already separate prints, one after the other
            adv_proc.pop("print_sequence", None)
            warnings.append(
                "Pièce par pièce ignoré : la pièce est découpée, chacun de ses morceaux est déjà imprimé l'un après l'autre."
            )
        return _split_and_slice(
            src,
            slots,
            fil,
            quality=quality,
            infill=infill,
            supports=supports,
            plate_only=plate_only,
            height_mm=height_mm,
            mode=mode,
            out_dir=out_dir,
            warnings=warnings,
            slot_colours=slot_colours,
            adv=(adv_proc, adv_fil),
            advanced=advanced,
            usage=usage,
            rotate=rotate,
            palette=palette,
            smart_flush=flush,
            forbidden=forbidden,
            auto_pose=auto_pose,
            oblique=oblique,
            planes=planes,
        )

    target, slot_hex = src, None
    layers = _layer_mode(advanced, usage)
    marks = colors.load_marks(src)
    ordre_conv: str | None = None
    if layers and (support_overrides(supports, plate_only)[0] or marks.get("support")):
        layers = ""  # OrcaSlicer refuses variable layer height with organic supports
        warnings.append(
            "Hauteur de couche variable ignorée : elle ne marche pas avec les supports en arbre."
        )
    if (
        n > 1
        or src.suffix.lower() not in SLICEABLE_AS_IS
        or height_mm
        or rot is not None
        or copies > 1
        or moves
        or scales
        or layers
        or marks
    ):
        base = src
        if height_mm and src.suffix.lower() == ".stl":
            base = out_dir / f".{src.stem}_scaled.stl"
            mesh.prepare(src, base, height_mm=height_mm)
        target = out_dir / f"{src.stem}_canvas.3mf"
        try:
            conv = colors.to_canvas(
                base,
                target,
                slots,
                height_mm=height_mm,
                rotate=rotate,
                copies=copies,
                moves=moves,
                shift=shift,
                marks_from=src,
                scales=scales,
                smart_flush=flush,
                palette=palette,
                ordre=ordre,
                simplify=(
                    colors.SIMPLIFY_LEVELS.get(simplify_colours, colors.SIMPLIFY_SHARE)
                    if isinstance(simplify_colours, str)
                    else (colors.SIMPLIFY_SHARE if simplify_colours else 0.0)
                ),
                layer_mm=_layer_mm(quality),
                real_colours=slot_colours,
            )
            slot_hex = conv["slot_colours"]
            ordre_conv = conv.get("ordre")
            if conv.get("simplified"):
                warnings.append(
                    f"{conv['simplified']} petite(s) tache(s) de couleur fondue(s) dans la couleur voisine : "
                    f"autant de changements et de purges en moins (« Simplifier les couleurs »)."
                )
        finally:
            if base != src:
                base.unlink(missing_ok=True)
        if layers:
            more = couches.apply(target, _layer_mm(quality), layers)
            warnings.append(
                "Hauteur de couche variable : "
                + (
                    f"environ {more} couches de plus, sur les pentes."
                    if more > 0
                    else (
                        f"environ {-more} couches de moins."
                        if more < 0
                        else "aucune pente douce, hauteur inchangée."
                    )
                )
            )

    slot_hex = _real_colours(slot_hex, slot_colours, n)
    if ordre == "suite":
        if ordre_conv == "suite":
            warnings.append(
                "Pièce par pièce : chaque couleur imprime toutes ses pièces à la suite, d'où bien moins de "
                "changements et de purge. Pas de tour d'essuyage dans cet ordre : le premier millimètre "
                "après chaque changement fond les deux couleurs."
            )
        else:  # not convertible (single piece, or every piece wears the same colours): stay layer by layer
            adv_proc.pop("print_sequence", None)
            ordre = ""
            warnings.append(
                "Pièce par pièce ignoré : "
                + {
                    "meme": "toutes les pièces de ce plateau portent les mêmes couleurs, et couche par couche "
                    "elles partagent déjà chaque changement.",
                    "seule": "ce plateau ne fait qu'une seule pièce.",
                }.get(ordre_conv or "", "ce modèle ne fait qu'une seule pièce.")
            )
    sup_on, sup_ov = support_overrides(supports, plate_only)
    if (
        marks.get("support") and not sup_on
    ):  # supports painted by hand, none asked for: only where painted
        sup_on, sup_ov = True, {
            "support_type": "tree(manual)",
            **({"support_on_build_plate_only": "1"} if plate_only else {}),
        }
        warnings.append("Supports ajoutés seulement là où tu les as peints.")
    try:
        res = slicer.slice_model(
            target,
            out_dir,
            quality=quality,
            filament=fil,
            infill=infill,
            supports=sup_on,
            colours=slot_hex,
            no_purge=bool(MODES[mode].get("no_purge")) and n > 1,
            overrides={
                **(MODES[mode]["overrides"] if n > 1 else {}),
                **sup_ov,
                # several parts: the CC2 can drop one that fails and finish the others
                # (its firmware reads EXCLUDE_OBJECT_DEFINE like Klipper); one part: profile as is
                **({"exclude_object": "1"} if copies > 1 else {}),
                **adv_proc,
            },
            filament_overrides={**(MODES[mode].get("filament", {}) if n > 1 else {}), **adv_fil},
            cli_args=cli,
        )
    except (
        slicer.SupportNeededError
    ):  # OrcaSlicer found parts that would hang in the air: tree supports, said in the result
        warnings.append(
            "Supports en arbre ajoutés : OrcaSlicer a trouvé des parties qui flotteraient sans support."
        )
        if layers:
            couches.remove(target)
            warnings.append(
                "Hauteur de couche variable retirée : elle ne marche pas avec les supports en arbre."
            )
        res = slicer.slice_model(
            target,
            out_dir,
            quality=quality,
            filament=fil,
            infill=infill,
            supports=True,
            colours=slot_hex,
            no_purge=bool(MODES[mode].get("no_purge")) and n > 1,
            overrides={
                **(MODES[mode]["overrides"] if n > 1 else {}),
                **sup_ov,
                # several parts: the CC2 can drop one that fails and finish the others
                # (its firmware reads EXCLUDE_OBJECT_DEFINE like Klipper); one part: profile as is
                **({"exclude_object": "1"} if copies > 1 else {}),
                **adv_proc,
            },
            filament_overrides={**(MODES[mode].get("filament", {}) if n > 1 else {}), **adv_fil},
            cli_args=cli,
        )
    if screen_thumbnail:
        _thumb_model(src, slots, rot, slot_hex, res.gcode, warnings, palette)
    palette = cast("colors.Palette", slot_hex or colorize.PALETTE)
    per = res.per_filament_m + [0.0] * n
    purge = res.purge_m + [0.0] * n
    from . import spools, stock  # needs() is what the colours step shows: keep it honest

    vol = mesh.info(src).get("volume_cm3")
    if vol and res.per_filament_m:
        est = sum(
            (spools.needs(vol, info["colours"], usage=usage, mapping=slots, filaments=fil)).values()
        )
        real = sum(stock.grams(mm + p, f) for mm, p, f in zip(per, purge, fil, strict=False))
        try:
            stock.calibrate_fill(usage, est, real)
        # a failed estimate correction must never fail a slice
        except Exception as e:  # noqa: BLE001
            import logging

            logging.getLogger(__name__).debug("calibrate_fill failed: %s", e)
    out = res.as_dict()
    out["warnings"] = warnings + out["warnings"]
    if pauses_mm:
        out["pauses"] = add_pauses(res.gcode[0], pauses_mm)
        if len(out["pauses"]) < len(set(pauses_mm)):
            out["warnings"].append(
                "Une pause tombe au-dessus de la pièce ou sur la même couche qu'une autre : elle est ignorée."
            )
    return {
        **out,
        "colours": info["colours"],
        "mode": mode,
        "usage": usage,
        "ordre": "suite" if ordre == "suite" else "couche",
        "slots": [
            {
                "slot": i + 1,
                "tool": f"T{i}",
                "filament": f,
                "colour": palette[i],
                "metres": round(per[i] + purge[i], 2),
                "purge_m": purge[i],
                **(
                    {"buse": res.temps["nozzle"][i]} if i < len(res.temps.get("nozzle", [])) else {}
                ),
            }
            for i, f in enumerate(fil)
        ],
    }


def _layer_mode(advanced: dict[str, str] | None, usage: str | None = None) -> str:
    """Variable layer height level for couches.apply: automatic (the default) thins slopes, which is a no-op on straight parts."""
    val = settings.CHOICES["couches"][2].get((advanced or {}).get("couches") or "auto", ("",))[0]
    return (
        ("" if usage == "profil" else "pentes") if val == "auto" else val
    )  # « Profil Elegoo » = no change at all


def _layer_mm(quality: str) -> float:
    m = re.match(r"[\d.]+", quality)
    return float(m.group()) if m else 0.2


def _real_colours(
    slot_hex: list[str] | None, slot_colours: dict[int, str] | None, n: int
) -> list[str] | None:
    """Colours of the spools really loaded (when known) replace the model's colours slot by slot."""
    if not slot_colours:
        return slot_hex
    base = list(slot_hex or colorize.PALETTE[:n]) + colorize.PALETTE[len(slot_hex or []) : n]
    return [slot_colours.get(i + 1, base[i]) for i in range(n)]


def _split_and_slice(
    src: Path,
    slots: dict[int, int],
    fil: list[str],
    *,
    quality: str,
    infill: int | None,
    supports: bool | str,
    plate_only: bool,
    height_mm: float | None,
    mode: str,
    out_dir: Path,
    warnings: list[str],
    slot_colours: dict[int, str] | None = None,
    adv: tuple[dict[str, str], dict[str, Any]] = ({}, {}),
    advanced: dict[str, str] | None = None,
    usage: str | None = None,
    rotate: tuple[float, ...] | None = None,
    palette: colors.Palette | None = None,
    smart_flush: bool | None = None,
    forbidden: Sequence[cut.Zone] = (),
    auto_pose: bool = False,
    oblique: bool = False,
    planes: Sequence[cut.Plane] | None = None,
) -> dict[str, Any]:
    """Cut a too-big model into pieces with dowel holes; one G-code per piece plus one for the dowels."""
    if smart_flush is None:
        smart_flush = MODES[mode]["smart_flush"]  # bled_purge already handled by the caller
    v, f, face_slots, slot_hex = colors.solid(
        src, slots, height_mm=height_mm, rotate=rotate, palette=palette
    )
    slot_hex = _real_colours(slot_hex, slot_colours, len(slot_hex))
    res = cut.cut(
        v, f, face_slots, name=src.stem, forbidden=forbidden, oblique=oblique, planes=planes
    )
    n = len(slot_hex)
    layer_level = _layer_mode(advanced, usage)
    sup_on, sup_ov = support_overrides(supports, plate_only)
    pieces, failed = [], []
    small: list[Any] = []
    big: list[Any] = []
    for (
        p
    ) in res.pieces:  # tiny pieces (spike tips…) go on the dowels' plate instead of a print each
        verts, laid = cut.rest_flat(p.vertices, p.faces)
        if (
            auto_pose
        ):  # the best of the six positions (fewest overhangs, firm footing) that fits the plate
            posed = orient.best_pose(p.vertices, p.faces, mesh.BED_MM - cut.MARGIN_MM)
            if posed is not None:
                verts, laid = posed["vertices"], posed["id"] != "debout"
        (small if np.ptp(verts, axis=0).max() <= SMALL_PIECE_MM else big).append((p, verts, laid))
    for p, verts, laid in big:
        target = out_dir / f"{p.name}.3mf"
        colors.write_piece(
            verts, p.faces, p.slots, slot_hex, target, name=p.name, smart_flush=smart_flush
        )
        if layer_level and not sup_on:
            couches.apply(target, _layer_mm(quality), layer_level)
        try:
            r = slicer.slice_model(
                target,
                out_dir,
                quality=quality,
                filament=fil,
                infill=infill,
                supports=sup_on,
                colours=slot_hex,
                no_purge=bool(MODES[mode].get("no_purge")) and n > 1,
                overrides={**(MODES[mode]["overrides"] if n > 1 else {}), **sup_ov, **adv[0]},
                filament_overrides={**(MODES[mode].get("filament", {}) if n > 1 else {}), **adv[1]},
            )
        except slicer.SliceError as err:  # one bad piece must not hide the others
            failed.append(f"{p.name} : {str(err)[:160]}")
            continue
        _thumb(
            verts,
            p.faces,
            np.array([colors._rgb(slot_hex[int(sl) - 1]) for sl in p.slots]),
            r.gcode,
            warnings,
        )
        pieces.append(
            {
                "name": p.name,
                "size_mm": np.ptp(verts, axis=0).round(1).tolist(),
                "laid_flat": laid,
                **r.as_dict(),
            }
        )
    if not pieces:
        raise slicer.SliceError("aucune pièce n'a pu être tranchée : " + " ; ".join(failed))
    warnings += [f"Pièce non tranchée — {msg}" for msg in failed]
    warnings += [
        f"{p['name']} est posée sur sa face plane pour tenir sur le plateau."
        for p in pieces
        if p["laid_flat"]
    ]
    pins = None
    if res.pins is not None or small:
        # one plate for the dowels (printed solid) and the small pieces
        items = [(p.name, v, p.faces, p.slots) for p, v, _ in small]
        if res.pins is not None:
            items += [
                (f"cheville{k + 1}", np.asarray(c.vertices), np.asarray(c.faces), None)
                for k, c in enumerate(res.pins.split(only_watertight=False))
            ]
        plate_file = out_dir / f"{src.stem}_petites_pieces.3mf"
        colors.write_plate(items, slot_hex, plate_file, smart_flush=smart_flush)
        r = slicer.slice_model(
            plate_file,
            out_dir,
            quality=quality,
            filament=fil,
            infill=100 if not small else infill,
            colours=slot_hex,
            no_purge=bool(MODES[mode].get("no_purge")) and n > 1,
            overrides={**(MODES[mode]["overrides"] if n > 1 else {}), **adv[0]},
            filament_overrides={**(MODES[mode].get("filament", {}) if n > 1 else {}), **adv[1]},
        )
        lengths = sorted({2 * d - 1 for d in res.pin_depths})
        allv = np.vstack([it[1] for it in items])
        allf = np.vstack([it[2] + sum(len(x[1]) for x in items[:i]) for i, it in enumerate(items)])
        rgb = np.vstack(
            [
                np.array(
                    [
                        colors._rgb(slot_hex[int(sl) - 1])
                        for sl in (it[3] if it[3] is not None else np.ones(len(it[2]), int))
                    ]
                )
                for it in items
            ]
        )
        _thumb(allv, allf, rgb, r.gcode, warnings)
        pins = {
            "name": plate_file.stem,
            "count": res.pin_count,
            "diameter_mm": cut.PIN_D,
            "length_mm": " ou ".join(f"{x:g}" for x in lengths) if lengths else "-",
            "small_pieces": len(small),
            **r.as_dict(),
        }
    total = sum(p["total_m"] for p in pieces) + (pins["total_m"] if pins else 0)
    return {
        "split": True,
        "mode": mode,
        "pieces": pieces,
        "pins": pins,
        "planes": [plane_json(c) for c in res.cuts],
        "total_m": round(total, 2),
        "alerts": res.alerts,
        "pin_count": res.pin_count,
        "warnings": warnings
        + [
            f"Découpé en {len(pieces) + len(small)} pièces"
            + (f" ({len(small)} petite(s) imprimée(s) avec les chevilles)" if small else "")
            + (
                f", {res.pin_count} chevilles de {cut.PIN_D:.0f} mm à coller"
                if res.pin_count
                else ""
            )
            + "."
        ],
        "gcode": [p["gcode"][0] for p in pieces] + ([pins["gcode"][0]] if pins else []),
        "colours": [],
        "slots": [],
    }


def cut_preview(
    src: Path,
    *,
    mapping: dict[int, int] | None = None,
    height_mm: float | None = None,
    palette: colors.Palette | None = None,
    forbidden: Sequence[cut.Zone] = (),
    explode: float = 0.3,
    show_planes: bool = False,
    distinct: bool = False,
    oblique: bool = False,
    planes: Sequence[cut.Plane] | None = None,
) -> tuple[dict[str, Any], trimesh.Trimesh]:
    """Where the model would be cut, plus a tinted view of the pieces, pushed apart by ``explode``
    (Y-up for the viewer). ``show_planes`` adds a translucent disc-like quad on every cut plane."""
    info = colors.analyze(src, palette)
    slots = {c["index"]: (mapping or {}).get(c["index"], c["slot"]) for c in info["colours"]}
    if not height_mm and mesh.info(src).get("unitless"):
        height_mm = mesh.DEFAULT_AI_HEIGHT_MM
    v, f, face_slots, slot_hex = colors.solid(src, slots, height_mm=height_mm, palette=palette)
    res = cut.cut(
        v, f, face_slots, name=src.stem, forbidden=forbidden, oblique=oblique, planes=planes
    )
    rgb = {i + 1: colors._rgb(h) for i, h in enumerate(slot_hex)}
    tints = [
        np.array(t)
        for t in (
            (1.0, 0.92, 0.82),
            (0.82, 0.9, 1.0),
            (0.85, 1.0, 0.85),
            (1.0, 0.85, 0.95),
            (0.95, 0.95, 0.8),
        )
    ]
    centre = v.mean(axis=0)
    vs, fs, cs, off = [], [], [], 0
    for i, p in enumerate(res.pieces):
        shift = (p.vertices.mean(axis=0) - centre) * explode  # explode outwards
        vs.append(p.vertices + shift)
        fs.append(p.faces + off)
        off += len(p.vertices)
        base = np.array([rgb.get(int(s), np.array([200.0, 200, 200])) for s in p.slots])
        if distinct:  # one clear colour per piece, to see how the model is divided
            base = np.tile(VIVID[i % len(VIVID)], (len(p.faces), 1))
        cs.append(np.clip(base * tints[i % len(tints)] if not distinct else base, 0, 255))
    rgba = np.c_[np.vstack(cs), np.full(off and sum(len(x) for x in fs), 255)].astype(np.uint8)
    allf = np.vstack(fs)
    allv = np.vstack(vs)
    if (
        show_planes and res.planes
    ):  # one translucent red quad per plane, a little larger than the model
        lo, hi = v.min(axis=0), v.max(axis=0)
        for cp in res.cuts:
            axis, pos = cp.axis, cp.pos
            a, b = [k for k in range(3) if k != axis]
            quad = np.zeros((4, 3))
            if (
                cp.angle
            ):  # a slanted plane: a square in its own plane, as large as the model's diagonal
                n = cp.normal()
                mid = (lo + hi) / 2
                mid = mid + (cp.d - n @ mid) * n
                u = np.cross(n, [1.0, 0, 0] if abs(n[0]) < 0.9 else [0, 1.0, 0])
                u /= np.linalg.norm(u)
                w = np.cross(n, u)
                r = np.linalg.norm(hi - lo) / 2 + 5
                quad = np.array(
                    [
                        mid - r * u - r * w,
                        mid + r * u - r * w,
                        mid + r * u + r * w,
                        mid - r * u + r * w,
                    ]
                )
            else:
                quad[:, axis] = pos
                corners = ((lo[a], lo[b]), (hi[a], lo[b]), (hi[a], hi[b]), (lo[a], hi[b]))
                for i, (ca, cb) in enumerate(corners):
                    quad[i, a] = ca - 5 if ca == lo[a] else ca + 5
                    quad[i, b] = cb - 5 if cb == lo[b] else cb + 5
            allf = np.vstack(
                [
                    allf,
                    [
                        [len(allv), len(allv) + 1, len(allv) + 2],
                        [len(allv), len(allv) + 2, len(allv) + 3],
                    ],
                ]
            )
            allv = np.vstack([allv, quad])
            rgba = np.vstack([rgba, np.tile([229, 57, 53, 90], (2, 1)).astype(np.uint8)])
    allv = np.c_[allv[:, 0], allv[:, 2], -allv[:, 1]]  # Z-up -> Y-up
    view = trimesh.Trimesh(allv, allf, face_colors=rgba, process=False)
    summary = {
        "planes": [plane_json(c) for c in res.cuts],
        "pieces": [
            {"name": p.name, "size_mm": np.ptp(p.vertices, axis=0).round(1).tolist()}
            for p in res.pieces
        ],
        "pins": res.pin_count,
        "alerts": res.alerts,
    }
    return summary, view


def _thumb(
    v: np.ndarray, f: np.ndarray, rgb: np.ndarray, gcodes: list[Path], warnings: list[str]
) -> None:
    """Printer-screen thumbnail; a failure only costs the picture, never the print."""
    try:
        png = thumbnail.render(v, f, rgb)
        for g in gcodes:
            thumbnail.inject(g, png)
    except Exception as err:  # noqa: BLE001 — — noqa: BLE001
        warnings.append(f"Vignette d'écran non générée ({type(err).__name__}).")


def _thumb_model(
    src: Path,
    slots: dict[int, int],
    rot: np.ndarray | None,
    slot_hex: list[str] | None,
    gcodes: list[Path],
    warnings: list[str],
    palette: colors.Palette | None = None,
) -> None:
    m = colors.preview(src, slots, palette)  # Y-up, one colour per face
    v = np.c_[m.vertices[:, 0], -m.vertices[:, 2], m.vertices[:, 1]]
    if rot is not None:
        v = v @ rot.T
    rgb = cast("trimesh.visual.ColorVisuals", m.visual).face_colors[:, :3].astype(float)
    if slot_hex:  # show the spools' real colours rather than the model's
        face_slot = {
            tuple(colors._rgb(c["hex"]).astype(int)): slots.get(c["index"], 1)
            for c in colors.analyze(src, palette)["colours"]
        }
        c = rgb.astype(np.int64)
        seen, back = np.unique(
            c[:, 0] << 16 | c[:, 1] << 8 | c[:, 2], return_inverse=True
        )  # a few colours, many faces
        rgb = np.array(
            [
                colors._rgb(slot_hex[face_slot.get((k >> 16, k >> 8 & 255, k & 255), 1) - 1])
                for k in seen.tolist()
            ]
        )[back.reshape(-1)]
    _thumb(v, np.asarray(m.faces), rgb, gcodes, warnings)


def compare(
    src: Path, base: dict[str, Any], on_row=None, only_current: bool = False
) -> list[dict[str, Any]]:
    """Slice the same model several ways (in a scratch folder) to show what each choice costs.

    ``base`` holds the prepare_and_slice arguments the user picked. Rows: the user's choice, the other
    usages, and for a multicolour model two copies on one plate (colour changes are shared: measured
    on a 4-colour figurine, 2 copies cost 57 g / 11 h instead of 2 × 39 g / 2 × 8 h 45)."""
    import tempfile

    from . import stock

    current = base.get("usage", DEFAULT_USAGE)
    variants: list[tuple[str, dict[str, Any]]] = [("Ton choix", {})]
    variants += [
        (
            USAGES[u]["label"],
            {"usage": u, "quality": USAGES[u]["quality"] or slicer.DEFAULT_QUALITY, "infill": None},
        )
        for u in ("decoratif", "rapide", "detaille", "fonctionnel")
        if u != current
    ]
    multicolour = len({c["slot"] for c in colors.analyze(src, base.get("palette"))["colours"]}) > 1
    if only_current:  # the estimate shown under the usage buttons: just the user's choice
        variants = variants[:1]
    elif multicolour and int(base.get("copies") or 1) == 1:
        # colour changes happen layer by layer for all copies at once, so the purge is shared:
        # measured on a 4-colour 60 mm figurine, 4 copies cost 24 g and 3 h 44 EACH instead of 51 g and 8 h 33
        variants += [
            ("2 exemplaires ensemble", {"copies": 2}),
            ("4 exemplaires ensemble", {"copies": 4, "_optional": True}),
        ]
    rows = []
    with tempfile.TemporaryDirectory() as tmp:
        for i, (label, change) in enumerate(variants):
            optional = change.pop("_optional", False)
            args = {**base, **change, "split": False}
            try:
                r = prepare_and_slice(
                    src, **args, out_dir=Path(tmp) / str(i), screen_thumbnail=False
                )
                u = stock.usage(r.get("per_filament_m") or [], r.get("purge_m"))
                copies = int(args.get("copies") or 1)
                row = {
                    "label": label,
                    "usage": args.get("usage"),
                    "quality": args.get("quality"),
                    "copies": copies,
                    "g": u["g"],
                    "eur": u["eur"],
                    "purge_g": round(sum(t["purge_g"] for t in u["trays"]), 1),
                    "time": r.get("time"),
                    "layers": r.get("layers"),
                    "changes": r.get("colour_changes", 0),
                    "current": not change,
                }
            except (ValueError, slicer.SliceError) as err:
                if optional:  # does not fit on the plate: simply not offered
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
    Pieces printing one at a time each go from the bed up: each one pauses at its own height ("run").
    Returns the pauses really placed: {"mm": asked, "z": layer top before the pause, "layer": 1-based layer of its piece, "run": which piece}.
    """
    lines = gcode.read_text(errors="ignore").splitlines(keepends=True)
    marks = [
        (i, float(lines[i + 1][3:]))
        for i in range(len(lines) - 1)
        if lines[i].startswith(";LAYER_CHANGE") and lines[i + 1].startswith(";Z:")
    ]
    placed: dict[int, dict[str, Any]] = {}
    for h in sorted(set(heights_mm)):
        run, crossed, prev, start = (
            1,
            set(),
            None,
            0,
        )  # a new run starts when Z goes back down: the next piece begins
        for n, (i, z) in enumerate(marks):
            if prev is not None and z < prev - 1e-6:
                run, start = run + 1, n
            if z > h + 1e-6 and (h, run) not in crossed:
                crossed.add(
                    (h, run)
                )  # one crossing per piece: heights stacked on the same layer, or before layer 1, stay dropped
                if (
                    n > start and i not in placed
                ):  # at least one layer of this piece is done: never before it
                    placed[i] = {"mm": h, "z": prev, "layer": n - start + 1, "run": run}
            prev = z
    for i in sorted(placed, reverse=True):
        lines.insert(i, f"; pause demandée à {placed[i]['mm']:g} mm\nPAUSE\n")
    if placed:
        tmp = gcode.with_suffix(".tmp")
        tmp.write_text("".join(lines))
        tmp.replace(gcode)
    return sorted(placed.values(), key=lambda p: p["z"])
