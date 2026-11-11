"""« Optimiser pour la CC2 » : one pass that takes any model to the best settings this printer can give it.

It chains what the workshop already knows how to do, in the order that matters: mend an open mesh (on a
copy), give a unitless model its real size, lay it on its best face at that size, then let the advisor
check that position and apply its fixes (supports, brim, larger part for thin walls, cut when too big)
until nothing it can fix is left. The result is a plan the page applies to the preparation form, with
one plain sentence per change; nothing is sliced here and the original file is never modified.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from . import advisor, config, mesh, orient, printprep

REPAIRABLE = {".glb", ".gltf", ".obj", ".ply", ".stl"}
MAX_ROUNDS = 3          # advisor passes: a fix can reveal the next point (larger part -> new overhangs)


def plan(path: Path, *, height_mm: float | None = None, rz: int = 0) -> dict[str, Any]:
    steps: list[dict[str, str]] = []

    def step(title: str, why: str) -> None:
        steps.append({"title": title, "why": why})

    # 1. a closed mesh first: every later measure (overhangs, walls, contact) needs a real volume
    first = advisor.analyze(path, height_mm=height_mm)
    if any(w["key"] == "ouvert" for w in first["warnings"]) and path.suffix.lower() in REPAIRABLE:
        from . import repair
        try:
            rep = repair.repair(path)
            path = config.MODELS_DIR / rep["name"]
            step("Maillage réparé", f"Le modèle n'était pas un volume fermé : copie réparée « {path.name} », original gardé.")
        except ValueError as err:
            step("Réparation impossible", str(err))

    # 2. a real size for models without units (AI generators)
    if not height_mm and mesh.info(path).get("unitless"):
        height_mm = mesh.DEFAULT_AI_HEIGHT_MM
        step(f"Taille réelle : {height_mm:.0f} mm de haut tel que modélisé", "Le fichier n'a pas d'unité réelle : taille de figurine proposée, à ajuster.")

    # 3. the best face on the plate at that size
    positions = orient.orientations(path, height_mm, rz)
    best = next(o for o in positions if o["recommandee"])
    asis = positions[0]
    rotate = (best["rotate"][0], best["rotate"][1], rz)
    if height_mm:   # same object, laid another way: the height as it now stands
        height_mm = float(best["size_mm"][2])
    if best is not asis:
        why = (f"{best['surplomb']:.0f} mm² en surplomb au lieu de {asis['surplomb']:.0f}" if best["surplomb"] < asis["surplomb"]
               else f"plus stable : {best['contact']:.0f} mm² posés au lieu de {asis['contact']:.0f}, {best['size_mm'][2]:.0f} mm de haut au lieu de "
                    f"{asis['size_mm'][2]:.0f} (les surplombs auront des supports)")
        step(f"Posée {best['label'].lower()}", why[:1].upper() + why[1:] + ".")

    # 4. the advisor at that position, its fixes applied until it has nothing left it can fix
    supports, advanced, split = "aucun", {}, False
    for _ in range(MAX_ROUNDS):
        a = advisor.analyze(path, height_mm=height_mm, rotate=rotate, supports=supports != "aucun",
                            brim=advanced.get("bordure") in ("exterieure", "oreilles"), split=split)
        todo = [w for w in a["warnings"] if w["fix"] and not w["fix"].get("repair")]
        if not todo:
            break
        for w in todo:   # one line per setting really changed, in the page's words
            fix = w["fix"]
            if fix.get("supports") and supports == "aucun":
                supports = fix["supports"]
                step("Supports en arbre", w["detail"])
            if (fix.get("advanced") or {}).get("bordure") and not advanced.get("bordure"):
                advanced.update(fix["advanced"])
                step(f"Bordure de {advanced.get('largeur_bordure', 5)} mm", w["detail"])
            if fix.get("split") and not split:
                split = True
                step("Découpée en pièces", w["detail"])
            if fix.get("height_mm"):
                height_mm = float(fix["height_mm"])
                prev = next((x for x in steps if x.get("grow")), None)   # several rounds: one line, the final size,
                steps[:] = [x for x in steps if x is not prev]           # the first reason (the thinnest walls)
                steps.append({"title": f"Agrandie à {height_mm:.0f} mm de haut", "why": prev["why"] if prev else w["detail"], "grow": "1"})
    else:   # out of rounds: what is left after the last fixes
        a = advisor.analyze(path, height_mm=height_mm, rotate=rotate, supports=supports != "aucun",
                            brim=advanced.get("bordure") in ("exterieure", "oreilles"), split=split)

    usage = printprep.suggest_usage(path)
    left = [{"title": w["title"], "detail": w["detail"], "level": w["level"]} for w in a["warnings"]]
    return {"file": path.name, "height_mm": height_mm, "rotate": list(rotate), "supports": supports,
            "advanced": advanced, "split": split, "usage": usage, "steps": steps, "left": left,
            "verdict": a["verdict"]}
