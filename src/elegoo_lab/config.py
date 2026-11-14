"""Configuration: config.toml at the project root, overridable by environment.

Printer settings (the actual Centauri Carbon 2), comfyui and dashboard sections.
"""

from __future__ import annotations

import contextlib
import os
import tomllib
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
# CC2_CONFIG / CC2_MODELS: a second, throw-away workshop next to the real one (interface tests)
CONFIG_FILE = Path(os.environ.get("CC2_CONFIG", ROOT / "config.toml"))
MODELS_DIR = Path(os.environ.get("CC2_MODELS", ROOT / "models"))


@dataclass(frozen=True)
class PrinterConfig:
    host: str
    access_code: str
    serial: str | None = None  # known serial skips the HTTP :80 bootstrap


@dataclass(frozen=True)
class Config:
    printer: PrinterConfig
    comfyui_url: str
    dashboard_port: int


def slicer_path() -> str | None:
    """Optional override: path to an OrcaSlicer/ElegooSlicer executable (AppRun or AppImage)."""
    if CONFIG_FILE.exists():
        return tomllib.loads(CONFIG_FILE.read_text()).get("slicer", {}).get("path") or None
    return None


def load() -> Config:
    raw: dict = {}
    if CONFIG_FILE.exists():
        raw = tomllib.loads(CONFIG_FILE.read_text())
    p = raw.get("printer", {})
    c = raw.get("comfyui", {})
    d = raw.get("dashboard", {})
    return Config(
        printer=PrinterConfig(
            host=os.environ.get("CC2_HOST", p.get("host", "")),
            access_code=os.environ.get("CC2_ACCESS_CODE", p.get("access_code", "")),
            serial=os.environ.get("CC2_SERIAL", p.get("serial")) or None,
        ),
        comfyui_url=os.environ.get("COMFYUI_URL", c.get("url", "http://127.0.0.1:8188")),
        dashboard_port=int(os.environ.get("CC2_DASH_PORT", d.get("port", 8787))),
    )


DEFAULT_DOWEL_PLAY_MM = 0.15


def dowel_play() -> float:
    """Radial play of dowel holes in cut pieces ([assemblage] jeu_mm), tuned with the dowel test piece."""
    if CONFIG_FILE.exists():
        return float(tomllib.loads(CONFIG_FILE.read_text()).get("assemblage", {}).get("jeu_mm", DEFAULT_DOWEL_PLAY_MM))
    return DEFAULT_DOWEL_PLAY_MM


def level_each_print() -> bool:
    """Whether sliced G-code keeps Elegoo's BED_MESH_CALIBRATE, probing only the area of the part. On by default:
    without it the CC2 firmware levels the whole bed itself before the print (seen on the printer, 2026-11-09).
    ``[tranchage] niveler = false`` comments the line out."""
    if CONFIG_FILE.exists():
        return bool(tomllib.loads(CONFIG_FILE.read_text()).get("tranchage", {}).get("niveler", True))
    return True


def write_atomic(path: Path, text: str, mode: int | None = None) -> None:
    """Replace a file in one step: a power cut or a crash leaves the old content or the new one, never a
    half-written or empty file (the library, spools, gallery and logs are the user's only copy)."""
    import tempfile
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        if mode is not None:
            os.chmod(tmp, mode)
        os.replace(tmp, path)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(tmp)
        raise


def _toml_value(v: object) -> str:
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return repr(v)
    return '"' + str(v).replace("\\", "\\\\").replace('"', '\\"') + '"'


def save(section: str, **values: object) -> None:
    """Update keys of one section of config.toml, keeping every other setting."""
    raw = tomllib.loads(CONFIG_FILE.read_text()) if CONFIG_FILE.exists() else {}
    raw.setdefault(section, {}).update(values)
    lines = ["# Atelier Centauri Carbon 2 — réglages (modifiables aussi depuis l'onglet Démarrage)", ""]
    for name, table in raw.items():
        if not isinstance(table, dict):
            continue
        lines.append(f"[{name}]")
        lines += [f"{k} = {_toml_value(v)}" for k, v in table.items() if not isinstance(v, dict)]
        lines.append("")
    write_atomic(CONFIG_FILE, "\n".join(lines), mode=0o600)  # holds the printer access code


def hunyuan_allowed() -> bool:
    """Hunyuan3D's licence does not apply in the EU, UK and South Korea: its workflows stay hidden unless
    ``[comfyui] hunyuan = true`` says the user is allowed to use them."""
    if CONFIG_FILE.exists():
        return bool(tomllib.loads(CONFIG_FILE.read_text()).get("comfyui", {}).get("hunyuan", False))
    return False
