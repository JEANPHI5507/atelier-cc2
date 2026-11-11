"""Advanced slicer settings offered in the workshop: French names, checked values, CC2 profile defaults.

Each entry maps to OrcaSlicer keys; values are validated here so a typo never reaches the slicer.
"""

from __future__ import annotations

from typing import Any

from . import slicer

# plate type -> (OrcaSlicer curr_bed_type, filament key holding its bed temperature)
PLATES = {
    "pei_texture": ("Textured PEI Plate", "textured_plate_temp", "PEI texturé (livré avec la CC2)"),
    "pei_lisse": ("High Temp Plate", "hot_plate_temp", "PEI lisse / haute température"),
    "froid": ("Cool Plate", "cool_plate_temp", "Plateau froid (SuperTack)"),
    "ingenierie": ("Engineering Plate", "eng_plate_temp", "Plateau ingénierie"),
}
DEFAULT_PLATE = "pei_texture"

CHOICES: dict[str, tuple[str, str, dict[str, tuple[str, str]]]] = {
    # name: (orca key, label, {value: (orca value, label)})
    "motif": ("sparse_infill_pattern", "Motif de remplissage", {
        "lignes": ("rectilinear", "Lignes (rapide)"), "grille": ("grid", "Grille"), "gyroide": ("gyroid", "Gyroïde (solide dans tous les sens)"),
        "nid_abeille": ("honeycomb", "Nid d'abeille"), "cubique": ("cubic", "Cubique"), "eclair": ("lightning", "Éclair (le plus léger, décoratif)"),
        "triangles": ("triangles", "Triangles")}),
    "couture": ("seam_position", "Couture (point de départ de chaque couche)", {
        "alignee": ("aligned", "Alignée"), "proche": ("nearest", "La plus discrète"), "arriere": ("back", "À l'arrière"),
        "aleatoire": ("random", "Aléatoire (pas de ligne visible)")}),
    "lissage": ("ironing_type", "Lissage du dessus", {
        "non": ("no ironing", "Non"), "dessus": ("top", "Toutes les faces du dessus"), "dernier": ("topmost", "Seulement la face la plus haute")}),
    "peau": ("fuzzy_skin", "Texture « peau » (aspect granuleux)", {
        "non": ("none", "Non"), "exterieur": ("external", "Parois extérieures"), "partout": ("all", "Toutes les parois")}),
    "bordure": ("brim_type", "Bordure d'adhérence", {
        "auto": ("auto_brim", "Automatique"), "non": ("no_brim", "Aucune"), "exterieure": ("outer_only", "Autour de la pièce"),
        "oreilles": ("brim_ears", "Oreilles aux angles")}),
}
NUMBERS: dict[str, tuple[str, str, float, float, str]] = {
    # name: (orca key, label, min, max, unit)
    "parois": ("wall_loops", "Nombre de parois", 1, 10, ""),
    "dessus": ("top_shell_layers", "Couches pleines dessus", 0, 20, ""),
    "dessous": ("bottom_shell_layers", "Couches pleines dessous", 0, 20, ""),
    "largeur_bordure": ("brim_width", "Largeur de bordure", 1, 20, "mm"),
    "radeau": ("raft_layers", "Radeau (couches sous la pièce)", 0, 6, ""),
    "angle_support": ("support_threshold_angle", "Angle de déclenchement des supports", 0, 90, "°"),
}
FIL_NUMBERS: dict[str, tuple[str, str, float, float, str]] = {
    # filament settings, set from the calibration towers (onglet Démarrage)
    "avance_pression": ("pressure_advance", "Pressure advance (tour de calibration)", 0, 0.2, ""),
    "debit": ("filament_flow_ratio", "Débit (tour de calibration, 1 = 100 %)", 0.8, 1.2, ""),
}
TEMPS: dict[str, tuple[str, float, float]] = {"temp_buse": ("Température buse", 170, 300), "temp_plateau": ("Température plateau", 0, 110)}


def spec(quality: str = slicer.DEFAULT_QUALITY) -> dict[str, Any]:
    """What the UI shows: every option with its allowed values and the CC2 profile default."""
    proc = slicer._flat(f"{quality} @Elegoo CC2 {slicer.DEFAULT_NOZZLE} nozzle")
    fil = slicer._flat("Elegoo PLA @ECC2")
    rev = {name: {orca: v for v, (orca, _) in opts.items()} for name, (_, _, opts) in CHOICES.items()}
    return {
        "plates": [{"value": k, "label": lab} for k, (_, _, lab) in PLATES.items()], "default_plate": DEFAULT_PLATE,
        "choices": [{"name": n, "label": lab, "default": rev[n].get(str(proc.get(key)), next(iter(opts))),
                     "options": [{"value": v, "label": l} for v, (_, l) in opts.items()]} for n, (key, lab, opts) in CHOICES.items()],
        "numbers": [{"name": n, "label": lab, "min": lo, "max": hi, "unit": u, "default": float(str(proc.get(key, lo)).rstrip("%"))}
                    for n, (key, lab, lo, hi, u) in NUMBERS.items()],
        "numbers_fil": [{"name": n, "label": lab, "min": lo, "max": hi, "unit": u, "step": 0.001 if key == "pressure_advance" else 0.01,
                         "default": float(fil.get(key, [lo])[0])} for n, (key, lab, lo, hi, u) in FIL_NUMBERS.items()],
        "temps": [{"name": n, "label": lab, "min": lo, "max": hi,
                   "default_pla": float((fil["nozzle_temperature"] if n == "temp_buse" else fil[PLATES[DEFAULT_PLATE][1]])[0])}
                  for n, (lab, lo, hi) in TEMPS.items()],
    }


def build(advanced: dict[str, Any] | None, plate: str = DEFAULT_PLATE) -> tuple[dict[str, str], dict[str, Any]]:
    """User choices -> (process overrides, filament overrides). Unknown names or bad values raise ValueError."""
    advanced = {k: v for k, v in (advanced or {}).items() if v not in (None, "")}
    if plate not in PLATES:
        raise ValueError(f"plateau inconnu « {plate} » ({', '.join(PLATES)})")
    bed_type, bed_key, _ = PLATES[plate]
    proc: dict[str, str] = {"curr_bed_type": bed_type}
    fil: dict[str, Any] = {}
    for name, value in advanced.items():
        if name in CHOICES:
            key, label, opts = CHOICES[name]
            if value not in opts:
                raise ValueError(f"{label} : valeur « {value} » inconnue ({', '.join(opts)})")
            proc[key] = opts[value][0]
        elif name in NUMBERS:
            key, label, lo, hi, unit = NUMBERS[name]
            v = float(value)
            if not lo <= v <= hi:
                raise ValueError(f"{label} : {v:g} hors de {lo:g} à {hi:g} {unit}".strip())
            proc[key] = str(int(v)) if v == int(v) else str(v)
        elif name in FIL_NUMBERS:
            key, label, lo, hi, _ = FIL_NUMBERS[name]
            v = float(value)
            if not lo <= v <= hi:
                raise ValueError(f"{label} : {v:g} hors de {lo:g} à {hi:g}")
            fil[key] = [f"{v:g}"]
            if key == "pressure_advance":
                fil["enable_pressure_advance"] = ["1"]
        elif name in TEMPS:
            label, lo, hi = TEMPS[name]
            v = int(float(value))
            if not lo <= v <= hi:
                raise ValueError(f"{label} : {v} °C hors de {lo:g} à {hi:g} °C")
            keys = ("nozzle_temperature", "nozzle_temperature_initial_layer") if name == "temp_buse" \
                else (bed_key, f"{bed_key}_initial_layer")
            fil.update({k: [str(v)] for k in keys})
        else:
            raise ValueError(f"réglage inconnu « {name} »")
    return proc, fil
