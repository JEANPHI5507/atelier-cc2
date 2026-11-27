"""Mesh helpers for print preparation (convert, inspect, scale)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

import numpy as np
import trimesh

if TYPE_CHECKING:
    from pathlib import Path

BED_MM = 256.0  # Centauri Carbon 2 build volume is 256 x 256 x 256 mm

# every 3D file the workshop takes. Mesh formats carry real colours (paint works on them); 3MF is a
# project; STEP is a CAD solid: trimesh cannot read it, cascadio turns it into a GLB at import.
MESH_EXT = {".stl", ".obj", ".off", ".dae", ".ply", ".glb", ".gltf"}
PROJECT_EXT = {".3mf"}
CAD_EXT = {".step", ".stp"}
MODEL_EXT = MESH_EXT | PROJECT_EXT | CAD_EXT


def step_to_glb(src: Path) -> Path:
    """A CAD STEP file as a plain GLB mesh: the whole pipeline (sizes, colours, bed) then treats it like any mesh.

    Raises ValueError when the CAD file is unreadable (cascadio's own message is terse)."""
    out = src.with_suffix(".glb")
    try:
        import cascadio

        cascadio.step_to_glb(str(src), str(out))
    except Exception as e:  # noqa: BLE001
        out.unlink(missing_ok=True)
        raise ValueError(f"{src.name} : fichier CAD illisible ({type(e).__name__})") from None
    if not out.is_file() or out.stat().st_size == 0:
        raise ValueError(f"{src.name} : fichier CAD illisible (aucune pièce convertie)")
    return out


def size_text(size, dec: int = 0) -> str:
    """A size for the user, each side named in the same order everywhere (across, front to back, up)."""
    x, y, z = (f"{float(v):.{dec}f}".replace(".", ",") for v in list(size)[:3])
    return f"largeur {x} × profondeur {y} × hauteur {z} mm"


UNITLESS_MM = (
    3.0  # AI generators (TRELLIS, Hunyuan) output ~1-unit meshes: below this, no real unit
)
UNITLESS_EXT = {".glb", ".gltf", ".obj", ".ply"}  # never STL/3MF: those come from CAD/slicers in mm
DEFAULT_AI_HEIGHT_MM = 60.0


_PLY_TYPES = {
    "char": "i1", "int8": "i1", "uchar": "u1", "uint8": "u1",
    "short": "i2", "int16": "i2", "ushort": "u2", "uint16": "u2",
    "int": "i4", "int32": "i4", "uint": "u4", "uint32": "u4",
    "float": "f4", "float32": "f4", "double": "f8", "float64": "f8",
}  # fmt: skip


def read_ply_polygons(path: Path) -> trimesh.Trimesh:
    """A PLY whose faces are not all triangles (Blender exports quads and n-gons unless told otherwise),
    which trimesh's binary reader refuses: faces split into triangle fans, face/vertex colours kept.
    """
    raw = path.read_bytes()
    end = raw.index(b"end_header") + len(b"end_header")
    end = raw.index(b"\n", end) + 1
    lines = raw[:end].decode("ascii", "replace").splitlines()
    fmt = next(ln.split()[1] for ln in lines if ln.startswith("format"))
    elements: list[tuple[str, int, list[tuple]]] = []
    for ln in lines:
        w = ln.split()
        if w and w[0] == "element":
            elements.append((w[1], int(w[2]), []))
        elif w and w[0] == "property" and elements:
            prop = ("list", w[2], w[3], w[4]) if w[1] == "list" else ("one", w[1], w[2])
            elements[-1][2].append(prop)
    order = "<" if fmt == "binary_little_endian" else ">"
    body, pos = raw[end:], 0
    tokens = body.split() if fmt == "ascii" else []
    tk = 0
    data: dict[str, dict[str, Any]] = {}
    for name, count, props in elements:
        cols: dict[str, Any] = {p[-1]: [] for p in props}
        if fmt != "ascii" and all(p[0] == "one" for p in props):
            dt = np.dtype([(p[2], order + _PLY_TYPES[p[1]]) for p in props])
            arr = np.frombuffer(body, dt, count, pos)
            pos += dt.itemsize * count
            data[name] = {p[2]: arr[p[2]] for p in props}
            continue
        for _ in range(count):
            for p in props:
                if fmt == "ascii":
                    if p[0] == "one":
                        cols[p[2]].append(float(tokens[tk]))
                        tk += 1
                    else:
                        n = int(tokens[tk])
                        cols[p[3]].append([int(t) for t in tokens[tk + 1 : tk + 1 + n]])
                        tk += 1 + n
                    continue
                if p[0] == "one":
                    t = np.dtype(order + _PLY_TYPES[p[1]])
                    cols[p[2]].append(np.frombuffer(body, t, 1, pos)[0])
                    pos += t.itemsize
                else:
                    ct, it = np.dtype(order + _PLY_TYPES[p[1]]), np.dtype(order + _PLY_TYPES[p[2]])
                    n = int(np.frombuffer(body, ct, 1, pos)[0])
                    pos += ct.itemsize
                    cols[p[3]].append(np.frombuffer(body, it, n, pos).tolist())
                    pos += it.itemsize * n
        data[name] = cols
    vx = data["vertex"]
    v = np.c_[np.asarray(vx["x"], float), np.asarray(vx["y"], float), np.asarray(vx["z"], float)]
    fx = data.get("face", {})
    polys = fx.get("vertex_indices") or fx.get("vertex_index") or []
    tris, owner = [], []
    for i, poly in enumerate(polys):
        for k in range(1, len(poly) - 1):  # fan: fine for the convex faces CAD exports
            tris.append((poly[0], poly[k], poly[k + 1]))
            owner.append(i)
    if not tris:
        raise ValueError(f"{path.name}: no triangle mesh found")
    kw: dict[str, Any] = {}
    if all(c in fx for c in ("red", "green", "blue")):
        rgb = np.c_[[np.asarray(fx[c], float)[owner] for c in ("red", "green", "blue")]].T
        kw["face_colors"] = np.c_[rgb, np.full(len(rgb), 255)].astype(np.uint8)
    elif all(c in vx for c in ("red", "green", "blue")):
        rgb = np.c_[[np.asarray(vx[c], float) for c in ("red", "green", "blue")]].T
        kw["vertex_colors"] = np.c_[rgb, np.full(len(rgb), 255)].astype(np.uint8)
    return trimesh.Trimesh(v, np.asarray(tris, np.int64), **kw)


def load(path: Path) -> trimesh.Trimesh:
    try:
        scene = trimesh.load(path, force="mesh")
    except (
        ValueError,
        IndexError,
        KeyError,
        UnboundLocalError,
    ) as err:  # trimesh's PLY reader on odd files
        if path.suffix.lower() != ".ply":
            raise
        try:
            scene = read_ply_polygons(path)  # quads / n-gons from Blender
        except (ValueError, IndexError, KeyError, StopIteration) as again:
            raise ValueError(f"{path.name}: PLY illisible ({again or err})") from again
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

        parts = [
            trimesh.Trimesh(p.vertices, p.faces, process=False)
            for o in threemf.read(path).objects
            for p in o.parts
        ]
        m = cast("trimesh.Trimesh", trimesh.util.concatenate(parts))
        x, y, z = (float(v) for v in m.extents)
        tight = all(p.is_watertight for p in parts)
        return {
            "file": path.name,
            "triangles": int(len(m.faces)),
            "size_mm": [round(x, 2), round(y, 2), round(z, 2)],
            "watertight": tight,
            "volume_cm3": round(sum(float(p.volume) for p in parts) / 1000, 2) if tight else None,
            "fits_bed": max(x, y, z) <= BED_MM,
            "objects": len(parts),
            "unitless": False,
        }
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


def prepare(
    src: Path, dst: Path, *, height_mm: float | None = None, fix: bool = True
) -> dict[str, Any]:
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
