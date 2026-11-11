"""Headless slicing with OrcaSlicer's CLI and its built-in Centauri Carbon 2 profiles.

OrcaSlicer's CLI takes exactly one machine and one process file and cannot
resolve ``inherits`` for files it is handed, so the process profile is
flattened here (parent chain merged) before user overrides are applied.
"""

from __future__ import annotations

import json
import re
import subprocess
import tempfile
import unicodedata
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

from . import catalog, config

TOOLS = config.ROOT / "tools" / "orcaslicer"
DEFAULT_NOZZLE = "0.4"
DEFAULT_QUALITY = "0.20mm Standard"
DEFAULT_FILAMENT = "PLA"
MESH_INPUT = {".stl", ".3mf", ".obj", ".step", ".stp"}


class SliceError(RuntimeError):
    pass


class SupportNeeded(SliceError):
    """OrcaSlicer's command line refused a part sliced without supports (return -100): worth one retry with them."""


def binary() -> Path:
    cfg = config.slicer_path()
    for cand in (cfg, TOOLS / "squashfs-root" / "AppRun"):
        if cand and Path(cand).is_file():
            return Path(cand)
    raise SliceError("Slicer introuvable. Lance: make slicer   (ou renseigne [slicer] path dans config.toml)")


def profiles_dir() -> Path:
    d = binary().parent / "resources" / "profiles" / "Elegoo"
    if not d.is_dir():
        raise SliceError(f"profils Elegoo introuvables dans {d}")
    return d


@lru_cache(maxsize=1)
def _index() -> dict[str, dict[str, Any]]:
    idx: dict[str, dict[str, Any]] = {}
    for p in profiles_dir().rglob("*.json"):
        try:
            d = json.loads(p.read_text())
        except (OSError, ValueError):
            continue
        if isinstance(d, dict) and "name" in d:
            d["_path"] = str(p)
            idx[d["name"]] = d
    return idx


def _flat(name: str) -> dict[str, Any]:
    d = _index()[name]
    base = _flat(d["inherits"]) if d.get("inherits") else {}
    return {**base, **{k: v for k, v in d.items() if k not in ("inherits", "_path")}}


def machine_profile(nozzle: str) -> Path:
    name = f"Elegoo Centauri Carbon 2 {nozzle} nozzle"
    if name not in _index():
        raise SliceError(f"pas de profil machine pour une buse de {nozzle} mm (disponibles: {nozzles()})")
    return Path(_index()[name]["_path"])


def nozzles() -> list[str]:
    return sorted(n.split()[-2] for n in _index() if re.fullmatch(r"Elegoo Centauri Carbon 2 [\d.]+ nozzle", n))


def qualities(nozzle: str = DEFAULT_NOZZLE) -> list[str]:
    suffix = f" @Elegoo CC2 {nozzle} nozzle"
    return sorted(n[: -len(suffix)] for n in _index() if n.endswith(suffix) and n[0].isdigit())


def filaments() -> list[str]:
    """Elegoo's CC2 filaments, then the user's own profiles (catalog) built on one of them."""
    elegoo = sorted(n[len("Elegoo "): -len(" @ECC2")] for n in _index() if n.startswith("Elegoo ") and n.endswith(" @ECC2"))
    return elegoo + sorted(k for k, v in catalog.profiles().items() if v["base"] in elegoo and k not in elegoo)


def _filament_path(short: str) -> Path:
    name = f"Elegoo {short} @ECC2"
    if name not in _index():
        raise SliceError(f"filament '{short}' inconnu. Disponibles: {', '.join(filaments())}")
    return Path(_index()[name]["_path"])


PALETTE = ["#E53935", "#1E88E5", "#43A047", "#FDD835"]


def _user_filament(short: str, colour: str, dest: Path, overrides: dict[str, Any] | None = None) -> Path:
    """Flattened copy of an Elegoo filament with its own colour: the slicer only registers
    several filaments when each one is a self-contained file with a distinct colour."""
    own = catalog.profiles().get(short)
    base = own["base"] if own else short
    _filament_path(base)  # validates the name
    f = _flat(f"Elegoo {base} @ECC2")
    f.update({k: v if isinstance(v, list) else [str(v)] for k, v in (own or {}).get("reglages", {}).items()})
    f.update({"type": "filament", "from": "User", "name": f"cc2lab {short} {colour}", "filament_colour": [colour]})
    f.update(overrides or {})
    f.pop("setting_id", None)
    p = dest / f"fil_{len(list(dest.glob('fil_*.json')))}.json"
    p.write_text(json.dumps(f))
    return p


def _official_names(gcode: bytes, names: list[str], process_name: str) -> bytes:
    """Put Elegoo's own profile names back in the G-code: our per-colour copies are named
    "cc2lab PLA #RRGGBB" (the slicer needs distinct files), but the CC2 refuses a print whose
    filament profile names it does not know."""
    own = catalog.profiles()   # the user's own profiles go out under the Elegoo filament they build on
    fil = ";".join(f'"Elegoo {own[n]["base"] if n in own else n} @ECC2"' for n in names).encode()
    gcode = re.sub(rb"^; filament_settings_id = .*$", b"; filament_settings_id = " + fil, gcode, flags=re.M)
    return re.sub(rb"^; print_settings_id = .*$", b"; print_settings_id = " + process_name.encode(), gcode, flags=re.M)


_MESH = re.compile(rb"^BED_MESH_CALIBRATE\b[^\n]*$", re.M)


def without_bed_mesh(gcode: bytes) -> bytes:
    """Comment out Elegoo's start-up bed levelling (the profile runs it before every single print)."""
    return _MESH.sub(lambda m: b"; (niveau du plateau retire) " + m.group(0), gcode)


# What the CC2 really pushes at each colour change (Elegoo's firmware, ``Canvas::CMD_M6211``): a fixed
# e_flush_dist = 23 mm, then up to the requested length L, then e_flush_ex_dist = 6 mm. So a change
# asked for L < 23 mm still costs 23 mm; OrcaSlicer's own purge figure ignores that floor.
FLUSH_FLOOR_MM, FLUSH_EXTRA_MM = 23.0, 6.0
_M6211 = re.compile(rb"^M6211 [^\n]*", re.M)


def without_purge(gcode: bytes) -> bytes:
    """Colour changes with no flush at all: ``M6211`` (whose 23 + 6 mm push cannot be asked away) becomes the bare
    CANVAS switch. The first load (``A1``) and same-tool changes keep their original line.

    The nozzle still holds the old colour, so the first millimetres after each change are a blend."""
    def swap(m: re.Match[bytes]) -> bytes:
        line = m.group(0)
        t, length = re.search(rb"\bT(\d+)", line), re.search(rb"\bL([\d.]+)", line)
        if not t or b" A1" in line or not length or float(length.group(1)) <= 0:
            return line
        return b"CANVAS_SWITCH_FILAMENT T=" + t.group(1) + b" ; (purge retiree) " + line
    return _M6211.sub(swap, gcode)


def firmware_purge_m(gcode: bytes, n_fil: int) -> list[float]:
    """Metres of filament purged per filament, counted the way the CC2 firmware does it.

    A change to the tool that is already loaded (``L0``) does nothing and costs nothing."""
    out = [0.0] * n_fil
    for m in _M6211.finditer(gcode):
        line = m.group(0).decode("ascii", "ignore")
        t, length = re.search(r"\bT(\d+)", line), re.search(r"\bL([\d.]+)", line)
        if not t or not length or float(length.group(1)) <= 0 or int(t.group(1)) >= n_fil:
            continue
        out[int(t.group(1))] += (max(float(length.group(1)), FLUSH_FLOOR_MM) + FLUSH_EXTRA_MM) / 1000
    return out


_FR = [
    ("floating regions", "Des zones de la pièce sont dans le vide (surplombs) : active les supports ou change l'orientation."),
    ("empty layer", "Une couche vide a été détectée : la pièce a peut-être une partie détachée ou trop fine."),
    ("too small", "Certains détails sont trop fins pour la buse et ne seront pas imprimés."),
]


def _fr(message: str) -> str:
    """OrcaSlicer warnings come in English: French for the common ones, original otherwise."""
    low = message.lower()
    return next((fr for key, fr in _FR if key in low), message)


@dataclass
class Result:
    gcode: list[Path] = field(default_factory=list)
    layers: int | None = None
    time: str | None = None
    filament_m: float | None = None
    per_filament_m: list[float] = field(default_factory=list)
    colour_changes: int = 0
    purge_m: list[float] = field(default_factory=list)   # firmware purge per filament (not in Orca's totals)
    warnings: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {"gcode": [p.name for p in self.gcode], "layers": self.layers, "time": self.time,
                "filament_m": self.filament_m, "per_filament_m": self.per_filament_m,
                "colour_changes": self.colour_changes, "purge_m": self.purge_m,
                "total_m": round((self.filament_m or 0) + sum(self.purge_m), 2), "warnings": self.warnings}


def _header(gcode: Path) -> dict[str, str]:
    """Pull the summary lines OrcaSlicer writes into the G-code comments."""
    changes = 0
    purge: dict[int, float] = {}
    first_load = True
    want = re.compile(r"; (total layer number|estimated printing time \(normal mode\)|total filament used \[mm\]|filament used \[mm\])\s*[:=]\s*(.+)")
    out: dict[str, str] = {}
    with gcode.open("rb") as f:
        for raw in f:
            if raw.startswith(b"CANVAS_SWITCH_FILAMENT T="):   # a change made by without_purge
                changes += 1
            elif raw.startswith(b"M6211 ") and b" T" in raw:  # CC2 filament change macro
                changes += 1
                m = re.search(rb" T(\d+).* L([\d.]+)", raw)
                if m and not first_load:  # the start load is not a colour change purge
                    purge[int(m.group(1))] = purge.get(int(m.group(1)), 0.0) + float(m.group(2))
                first_load = False
            elif raw.startswith(b"; "):
                m = want.match(raw.decode("utf-8", "ignore"))
                if m:
                    out.setdefault(m.group(1), m.group(2).strip())
    out["colour changes"] = str(max(0, changes - 1))  # the first one loads the starting filament
    out["purge"] = json.dumps(purge)
    return out


def slice_model(
    model: Path,
    out_dir: Path,
    *,
    nozzle: str = DEFAULT_NOZZLE,
    quality: str = DEFAULT_QUALITY,
    filament: list[str] | None = None,
    infill: int | None = None,
    walls: int | None = None,
    supports: bool = False,
    colours: list[str] | None = None,
    overrides: dict[str, str] | None = None,
    filament_overrides: dict[str, Any] | None = None,
    cli_args: list[str] | None = None,
    no_purge: bool = False,
    timeout: float = 600.0,
) -> Result:
    if model.suffix.lower() not in MESH_INPUT:
        raise SliceError(f"{model.name}: format non tranchable (accepté: {sorted(MESH_INPUT)})")
    process_name = f"{quality} @Elegoo CC2 {nozzle} nozzle"
    if process_name not in _index():
        raise SliceError(f"qualité '{quality}' inconnue pour une buse de {nozzle} mm. Disponibles: {qualities(nozzle)}")
    names = filament or [DEFAULT_FILAMENT]
    if len(names) > 4:
        raise SliceError("le CANVAS gère 4 filaments au maximum")
    if model.suffix.lower() == ".3mf":
        from .colorize import filament_count
        declared = filament_count(model)
        if declared and declared != len(names):
            raise SliceError(f"{model.name} prévoit {declared} filament(s) mais {len(names)} fourni(s): "
                             f"répète --filament {declared} fois")

    proc = _flat(process_name)
    proc.update({"type": "process", "name": f"cc2lab {quality}", "from": "User"})
    proc.pop("setting_id", None)
    if infill is not None:
        proc["sparse_infill_density"] = f"{infill}%"
    if walls is not None:
        proc["wall_loops"] = str(walls)
    if supports:
        proc["enable_support"] = "1"
    proc.setdefault("curr_bed_type", "Textured PEI Plate")  # the CC2 ships with a textured PEI plate (60 °C for PLA)
    proc.update(overrides or {})
    # ElegooSlicer ships the CC2 with ramming off: on, the CC2 stops with error 1243 "extrusion failed"
    proc["enable_filament_ramming"] = "0"

    out_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        cols = (colours or []) + PALETTE[len(colours or []):]
        fil = [_user_filament(n, cols[i], Path(tmp), filament_overrides) for i, n in enumerate(names)]
        pf = Path(tmp) / "process.json"
        pf.write_text(json.dumps(proc))
        work = Path(tmp) / "out"
        # --allow-newer-file: projects saved by newer Bambu Studio / OrcaSlicer (most MakerWorld files)
        # are otherwise refused with "Unsupported 3MF version" (-24)
        cmd = [str(binary()), "--slice", "0", "--allow-newer-file", *(cli_args or []), "--outputdir", str(work),
               "--load-settings", f"{machine_profile(nozzle)};{pf}",
               "--load-filaments", ";".join(str(p) for p in fil), str(model.resolve())]  # cwd is tmp
        try:
            run = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, cwd=tmp)  # its log lands in tmp
        except subprocess.TimeoutExpired as err:
            raise SliceError(f"tranchage trop long (> {timeout:.0f}s)") from err
        report: dict[str, Any] = {}
        if (work / "result.json").exists():
            report = json.loads((work / "result.json").read_text())
        gcodes = sorted(work.glob("plate_*.gcode")) if work.exists() else []
        if run.returncode != 0 or report.get("return_code", 0) != 0 or not gcodes:
            # without supports, OrcaSlicer's command line fails (return -100, code 156) on parts that would hang
            # in the air instead of warning; its log only says so at --debug 3, so the caller retries with supports
            if not supports and report.get("return_code", run.returncode) in (156, -100) and "return -100" in run.stdout + run.stderr:
                raise SupportNeeded("une partie flotterait sans support")
            detail = (report.get("error_string") or "") + " " + (run.stdout + run.stderr).strip()[-400:]
            raise SliceError(f"OrcaSlicer a échoué (code {report.get('return_code', run.returncode)}): {detail.strip()}")

        tag = quality.split()[0] + (f"_{'-'.join(names)}" if filament else "")
        # plain ASCII file names for the printer: "Noël" -> "Noel"
        tag = re.sub(r"[^\w.-]+", "_", unicodedata.normalize("NFKD", tag).encode("ascii", "ignore").decode(), flags=re.A)
        res = Result(warnings=[_fr(w["warning_message"]) for p in report.get("sliced_plates", [])
                               if (w := p).get("warning_message")])
        for i, g in enumerate(gcodes):
            dest = out_dir / f"{model.stem}_{tag}{'' if len(gcodes) == 1 else f'_p{i + 1}'}.gcode"
            data = _official_names(g.read_bytes(), names, process_name)
            if not config.level_each_print():
                data = without_bed_mesh(data)
            if no_purge:
                data = without_purge(data)
            dest.write_bytes(data)
            res.gcode.append(dest)
            if i == 0:
                fw_purge = firmware_purge_m(data, len(names))
        h = _header(res.gcode[0])
        res.layers = int(h["total layer number"]) if "total layer number" in h else None
        res.time = h.get("estimated printing time (normal mode)")
        res.colour_changes = int(h.get("colour changes", 0))
        purge = {int(k): v for k, v in json.loads(h.get("purge", "{}")).items()}
        n_fil = len(names)
        res.purge_m = [round(purge.get(i, 0.0) / 1000, 2) for i in range(n_fil)] if purge else []
        if any(fw_purge):      # the firmware's own count: higher than OrcaSlicer's whenever changes ask for under 23 mm
            res.purge_m = [round(x, 2) for x in fw_purge]
        if res.colour_changes > 150:
            res.warnings.append(f"{res.colour_changes} changements de couleur (≈ 1 min chacun) : pour gagner du temps, "
                                "passe en couches de 0,28 mm ou regroupe une couleur peu utilisée avec une autre.")
        fm = h.get("total filament used [mm]") or h.get("filament used [mm]")
        if fm:
            try:
                per = [float(x) / 1000 for x in re.findall(r"[\d.]+", fm)]
                res.per_filament_m = [round(x, 2) for x in per]
                res.filament_m = round(sum(per), 2)
            except ValueError:
                pass
        return res
