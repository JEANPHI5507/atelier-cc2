"""Build a multi-colour 3MF (OrcaSlicer format): ONE object made of several parts, one filament slot each.

The CANVAS prints with up to 4 filaments (slots 1-4 = T0-T3). Parts that touch
must live in one object: separate objects that touch are rejected by the slicer
as a G-code conflict. The 3MF carries the per-part ``extruder`` and the number
of filaments (OrcaSlicer rejects a project whose flush matrix size differs from
the number of filaments it is given), so slice it with the same filament count.
"""

from __future__ import annotations

import json
import zipfile
from pathlib import Path
from xml.sax.saxutils import quoteattr

import numpy as np

from . import mesh

BED_CENTER = mesh.BED_MM / 2
MAX_SLOTS = 4
PALETTE = ["#E53935", "#1E88E5", "#43A047", "#FDD835"]

_NS = ('xmlns="http://schemas.microsoft.com/3dmanufacturing/core/2015/02" '
       'xmlns:BambuStudio="http://schemas.bambulab.com/package/2021" '
       'xmlns:p="http://schemas.microsoft.com/3dmanufacturing/production/2015/06" requiredextensions="p"')


def build_3mf(parts: list[tuple[Path, int]], out: Path, *, filaments: int | None = None, name: str = "model",
              colours: list[str] | None = None, flush: list[int] | None = None) -> dict:
    """``parts`` = [(mesh file, filament slot 1..4), ...]. Relative positions between parts are kept;
    the assembly is rested on Z=0 and centred on the bed. ``filaments`` = number of filaments the
    slicer will be given (defaults to the highest slot used). ``colours``: the spools' colours, slot 1
    first; ``flush``: purge matrix (colors.flush_matrix), both default to a fixed palette and full purge."""
    if not parts:
        raise ValueError("au moins une pièce est nécessaire")
    meshes = []
    for path, slot in parts:
        if not 1 <= slot <= MAX_SLOTS:
            raise ValueError(f"{path.name}: emplacement filament {slot} hors 1..{MAX_SLOTS}")
        meshes.append((path, slot, mesh.load(path)))
    n_fil = max(filaments or 0, max(s for _, s, _ in meshes))

    lo = np.min([m.bounds[0] for _, _, m in meshes], axis=0)
    hi = np.max([m.bounds[1] for _, _, m in meshes], axis=0)
    if (hi - lo).max() > mesh.BED_MM:
        raise ValueError(f"l'assemblage ({(hi - lo).round(1).tolist()} mm) dépasse le plateau de {mesh.BED_MM:.0f} mm")
    shift = np.array([BED_CENTER - (lo[0] + hi[0]) / 2, BED_CENTER - (lo[1] + hi[1]) / 2, -lo[2]])

    obj_id = len(meshes) + 1
    files: dict[str, str] = {}
    components, parts_cfg, rels = [], [], []
    for i, (path, slot, m) in enumerate(meshes, 1):
        v = np.asarray(m.vertices) + shift
        fname = f"3D/Objects/part_{i}.model"
        files[fname] = (
            f'<?xml version="1.0" encoding="UTF-8"?>\n<model unit="millimeter" xml:lang="en-US" {_NS}>\n'
            f' <resources>\n  <object id="{i}" type="model">\n   <mesh>\n    <vertices>\n'
            + "\n".join(f'     <vertex x="{x:.5f}" y="{y:.5f}" z="{z:.5f}"/>' for x, y, z in v)
            + "\n    </vertices>\n    <triangles>\n"
            + "\n".join(f'     <triangle v1="{a}" v2="{b}" v3="{c}"/>' for a, b, c in m.faces)
            + "\n    </triangles>\n   </mesh>\n  </object>\n </resources>\n <build/>\n</model>\n"
        )
        components.append(f'    <component p:path="/{fname}" objectid="{i}" transform="1 0 0 0 1 0 0 0 1 0 0 0"/>')
        rels.append(f' <Relationship Target="/{fname}" Id="rel-{i}" Type="http://schemas.microsoft.com/3dmanufacturing/2013/01/3dmodel"/>')
        parts_cfg.append(
            f'    <part id="{i}" subtype="normal_part">\n'
            f'      <metadata key="name" value={quoteattr(path.stem)}/>\n'
            f'      <metadata key="matrix" value="1 0 0 0 0 1 0 0 0 0 1 0 0 0 0 1"/>\n'
            f'      <metadata key="extruder" value="{slot}"/>\n    </part>'
        )

    files["3D/3dmodel.model"] = (
        f'<?xml version="1.0" encoding="UTF-8"?>\n<model unit="millimeter" xml:lang="en-US" {_NS}>\n'
        ' <metadata name="BambuStudio:3mfVersion">1</metadata>\n'
        f' <resources>\n  <object id="{obj_id}" type="model">\n   <components>\n'
        + "\n".join(components)
        + f'\n   </components>\n  </object>\n </resources>\n <build>\n'
        f'  <item objectid="{obj_id}" transform="1 0 0 0 1 0 0 0 1 0 0 0" printable="1"/>\n </build>\n</model>\n'
    )
    files["3D/_rels/3dmodel.model.rels"] = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">\n'
        + "\n".join(rels) + "\n</Relationships>\n"
    )
    files["Metadata/model_settings.config"] = (
        '<?xml version="1.0" encoding="UTF-8"?>\n<config>\n'
        f'  <object id="{obj_id}">\n    <metadata key="name" value={quoteattr(name)}/>\n'
        '    <metadata key="extruder" value="1"/>\n' + "\n".join(parts_cfg) + "\n  </object>\n"
        '  <plate>\n    <metadata key="plater_id" value="1"/>\n    <metadata key="plater_name" value=""/>\n'
        '    <metadata key="locked" value="false"/>\n    <metadata key="gcode_file" value=""/>\n  </plate>\n'
        "  <assemble>\n  </assemble>\n</config>\n"
    )
    files["Metadata/project_settings.config"] = json.dumps({
        "filament_colour": ((colours or [])[:n_fil] + PALETTE[len(colours or []):n_fil] + ["#808080"] * n_fil)[:n_fil],
        "flush_volumes_matrix": [str(v) for v in flush] if flush else
                                ["0" if i == j else "280" for i in range(n_fil) for j in range(n_fil)],
        "flush_volumes_vector": ["140"] * (2 * n_fil),
    }, indent=2)
    files["_rels/.rels"] = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">\n'
        ' <Relationship Target="/3D/3dmodel.model" Id="rel-1" '
        'Type="http://schemas.microsoft.com/3dmanufacturing/2013/01/3dmodel"/>\n</Relationships>\n'
    )
    files["[Content_Types].xml"] = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">\n'
        ' <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>\n'
        ' <Default Extension="model" ContentType="application/vnd.ms-package.3dmanufacturing-3dmodel+xml"/>\n'
        '</Types>\n'
    )
    out.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for fname, data in files.items():
            z.writestr(fname, data)
    return {"file": out.name, "parts": [(p.name, s) for p, s, _ in meshes], "filaments": n_fil,
            "size_mm": (hi - lo).round(2).tolist()}


def filament_count(path: Path) -> int | None:
    """Number of filaments declared by a 3MF's project settings (None if not a project)."""
    try:
        with zipfile.ZipFile(path) as z:
            return len(json.loads(z.read("Metadata/project_settings.config")).get("filament_colour", [])) or None
    except (OSError, KeyError, ValueError, zipfile.BadZipFile):
        return None
