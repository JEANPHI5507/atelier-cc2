"""Mesh helpers for print preparation (convert, inspect, scale)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import trimesh

BED_MM = 256.0  # Centauri Carbon 2 build volume is 256 x 256 x 256 mm
UNITLESS_MM = 3.0  # AI generators (TRELLIS, Hunyuan) output ~1-unit meshes: below this, no real unit
UNITLESS_EXT = {".glb", ".gltf", ".obj", ".ply"}  # never STL/3MF: those come from CAD/slicers in mm
DEFAULT_AI_HEIGHT_MM = 60.0


def load(path: Path) -> trimesh.Trimesh:
    scene = trimesh.load(path, force="mesh")
    if not isinstance(scene, trimesh.Trimesh) or len(scene.faces) == 0:
        raise ValueError(f"{path.name}: no triangle mesh found")
    return scene


_INFO_CACHE: dict[tuple, dict[str, Any]] = {}


def info(path: Path) -> dict[str, Any]:
    """Size, watertightness, bed fit (cached per file version)."""
    st = path.stat()
    key = (str(path.resolve()), st.st_mtime_ns, st.st_size)
    if key not in _INFO_CACHE:
        if len(_INFO_CACHE) > 128:
            _INFO_CACHE.clear()
        _INFO_CACHE[key] = _info(path)
    return dict(_INFO_CACHE[key])


def _info(path: Path) -> dict[str, Any]:
    if path.suffix.lower() == ".3mf":
        # trimesh misplaces parts of OrcaSlicer/Bambu projects (component transforms); use our reader
        from . import threemf
        parts = [trimesh.Trimesh(p.vertices, p.faces, process=False) for o in threemf.read(path).objects for p in o.parts]
        m = trimesh.util.concatenate(parts)
        x, y, z = (float(v) for v in m.extents)
        tight = all(p.is_watertight for p in parts)
        return {"file": path.name, "triangles": int(len(m.faces)), "size_mm": [round(x, 2), round(y, 2), round(z, 2)],
                "watertight": tight, "volume_cm3": round(sum(float(p.volume) for p in parts) / 1000, 2) if tight else None,
                "fits_bed": max(x, y, z) <= BED_MM, "objects": len(parts),
                "unitless": False}
    m = load(path)
    if path.suffix.lower() in {".glb", ".gltf"}:  # glTF is Y-up; report printer axes (Z-up)
        m.apply_transform(trimesh.transformations.rotation_matrix(3.141592653589793 / 2, [1, 0, 0]))
    x, y, z = (float(v) for v in m.extents)
    return {
        "file": path.name,
        "triangles": int(len(m.faces)),
        "size_mm": [round(x, 2), round(y, 2), round(z, 2)],
        "watertight": bool(m.is_watertight),
        "volume_cm3": round(float(m.volume) / 1000, 2) if m.is_watertight else None,
        "fits_bed": max(x, y, z) <= BED_MM,
        "unitless": path.suffix.lower() in UNITLESS_EXT and max(x, y, z) < UNITLESS_MM,
    }


def prepare(src: Path, dst: Path, *, height_mm: float | None = None, fix: bool = True) -> dict[str, Any]:
    """Convert to ``dst`` (format by extension), rest it on Z=0, centre on the bed.

    ``height_mm`` rescales uniformly so the model is that tall (AI-generated
    meshes come out at arbitrary units). Z is assumed up; Y-up GLB output is
    rotated to Z-up automatically when the model is taller along Y.
    """
    m = load(src)
    if src.suffix.lower() in {".glb", ".gltf"}:
        m.apply_transform(trimesh.transformations.rotation_matrix(3.141592653589793 / 2, [1, 0, 0]))
    if fix:
        m.merge_vertices()
        m.update_faces(m.nondegenerate_faces())
        trimesh.repair.fix_normals(m)
        trimesh.repair.fill_holes(m)
    if height_mm:
        m.apply_scale(height_mm / float(m.extents[2]))
    lo, hi = m.bounds
    m.apply_translation([-(lo[0] + hi[0]) / 2, -(lo[1] + hi[1]) / 2, -lo[2]])
    m.export(dst)
    return info(dst)
