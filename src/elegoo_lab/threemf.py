"""Read any 3MF (OrcaSlicer, Bambu Studio, PrusaSlicer, standard 3MF materials) into plain geometry,
and write a clean OrcaSlicer-format project back.

Re-writing instead of patching makes slicing independent of the dialect and version that saved the
file: OrcaSlicer 2.4's CLI crashes or refuses on some projects saved by newer Bambu Studio/Orca.

Per part we keep: world-space mesh, filament (``extruder``), per-triangle painting (``paint_color``
/ ``slic3rpe:mmu_segmentation``) and per-triangle colours from standard ``colorgroup`` /
``basematerials`` resources.
"""

from __future__ import annotations

import json
import re
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from xml.etree import ElementTree as ET
from xml.sax.saxutils import quoteattr

import numpy as np

CORE = "http://schemas.microsoft.com/3dmanufacturing/core/2015/02"
MAT = "http://schemas.microsoft.com/3dmanufacturing/material/2015/02"
PROD = "http://schemas.microsoft.com/3dmanufacturing/production/2015/06"
SLIC3R = "http://schemas.slic3r.org/3mf/2017/06"
UNITS = {"micron": 0.001, "millimeter": 1.0, "centimeter": 10.0, "inch": 25.4, "foot": 304.8, "meter": 1000.0}


@dataclass
class Part:
    name: str
    vertices: np.ndarray            # (N, 3) world mm
    faces: np.ndarray               # (M, 3)
    extruder: int = 1
    paint: list[str | None] | None = None          # TriangleSelector code per face
    face_rgb: np.ndarray | None = None             # (M, 3) from standard 3MF colours
    locked: np.ndarray | None = None               # (M,) faces repainted by hand: kept as painted


@dataclass
class Object:
    name: str
    parts: list[Part] = field(default_factory=list)


@dataclass
class Project:
    objects: list[Object]
    colours: list[str]              # declared filament colours (may be empty)


def _matrix(attr: str | None) -> np.ndarray:
    m = np.eye(4)
    if attr:
        v = [float(x) for x in attr.split()]
        m[:3, :3] = np.array(v[:9]).reshape(3, 3)
        m[3, :3] = v[9:12]
    return m  # row-vector convention: p' = [p 1] @ m


def _colour(c: str) -> tuple[int, int, int]:
    c = c.lstrip("#")
    return int(c[0:2], 16), int(c[2:4], 16), int(c[4:6], 16)


def read(path: Path) -> Project:
    with zipfile.ZipFile(path) as z:
        names = z.namelist()
        docs = {"/" + n: ET.fromstring(z.read(n)) for n in names if n.endswith(".model")}
        settings = z.read("Metadata/model_settings.config").decode("utf-8", "ignore") \
            if "Metadata/model_settings.config" in names else ""
        try:
            colours = [c[:7].upper() for c in json.loads(z.read("Metadata/project_settings.config")).get("filament_colour", [])]
        except (KeyError, ValueError):
            colours = []
        if not colours and "Metadata/Slic3r_PE.config" in names:  # PrusaSlicer project
            m = re.search(r"; extruder_colour = (.+)", z.read("Metadata/Slic3r_PE.config").decode("utf-8", "ignore"))
            colours = [c.strip('" ')[:7].upper() for c in m.group(1).split(";")] if m else []
        root_name = next((n for n in docs if n.lower() == "/3d/3dmodel.model"), next(iter(docs)))

    # extruders from Orca/Bambu model_settings: <object id> default and <part id> override
    obj_ext: dict[str, int] = {}
    part_ext: dict[str, int] = {}
    for om in re.finditer(r'<object id="(\d+)">(.*?)</object>', settings, re.S):
        body = om.group(2)
        head = body.split("<part", 1)[0]
        e = re.search(r'key="extruder" value="(\d+)"', head)
        if e:
            obj_ext[om.group(1)] = int(e.group(1))
        for pm in re.finditer(r'<part id="(\d+)"[^>]*>(.*?)</part>', body, re.S):
            e = re.search(r'key="extruder" value="(\d+)"', pm.group(2))
            if e:
                part_ext[pm.group(1)] = int(e.group(1))

    def resources(doc_path: str) -> tuple[dict[str, ET.Element], dict[str, list]]:
        doc = docs[doc_path]
        objs, mats = {}, {}
        for res in doc.iter(f"{{{CORE}}}resources"):
            for el in res:
                tag = el.tag.split("}")[1]
                if tag == "object":
                    objs[el.get("id")] = el
                elif tag == "colorgroup":
                    mats[el.get("id")] = [_colour(c.get("color")) for c in el if c.tag.endswith("color")]
                elif tag == "basematerials":
                    mats[el.get("id")] = [_colour(b.get("displaycolor", "#C0C0C0")) for b in el if b.tag.endswith("base")]
        return objs, mats

    cache = {p: resources(p) for p in docs}
    unit = UNITS.get(docs[root_name].get("unit", "millimeter"), 1.0)

    def mesh_part(el: ET.Element, mats: dict, xf: np.ndarray, name: str, ext: int) -> Part:
        mesh = el.find(f"{{{CORE}}}mesh")
        vs = np.array([[float(v.get("x")), float(v.get("y")), float(v.get("z"))]
                       for v in mesh.find(f"{{{CORE}}}vertices")], dtype=float) * unit
        vs = (np.c_[vs, np.ones(len(vs))] @ xf)[:, :3]
        tris = list(mesh.find(f"{{{CORE}}}triangles"))
        faces = np.array([[int(t.get("v1")), int(t.get("v2")), int(t.get("v3"))] for t in tris], dtype=np.int64)
        paint = [t.get("paint_color") or t.get(f"{{{SLIC3R}}}mmu_segmentation") for t in tris]
        rgb = None
        opid, oidx = el.get("pid"), el.get("pindex")
        if mats and (opid or any(t.get("pid") for t in tris)):
            rgb = np.zeros((len(tris), 3))
            for i, t in enumerate(tris):
                pid, p1 = t.get("pid", opid), t.get("p1", oidx if t.get("pid") is None else "0")
                group = mats.get(pid)
                rgb[i] = group[int(p1 or 0)] if group else (192, 192, 192)
        return Part(name, vs, faces, ext, paint if any(paint) else None, rgb)

    def flatten(doc_path: str, oid: str, xf: np.ndarray, top_id: str, name: str) -> list[Part]:
        objs, mats = cache[doc_path]
        el = objs[oid]
        comps = el.find(f"{{{CORE}}}components")
        if comps is None:
            ext = part_ext.get(oid) or obj_ext.get(top_id) or 1
            return [mesh_part(el, mats, xf, el.get("name") or name, ext)]
        parts = []
        for c in comps:
            target = c.get(f"{{{PROD}}}path") or doc_path
            parts += flatten(target, c.get("objectid"), _matrix(c.get("transform")) @ xf, top_id, name)
        return parts

    objects = []
    root = docs[root_name]
    for item in root.iter(f"{{{CORE}}}item"):
        if item.get("printable") == "0":
            continue
        oid = item.get("objectid")
        el = cache[root_name][0][oid]
        name = el.get("name") or f"objet {oid}"
        objects.append(Object(name, flatten(root_name, oid, _matrix(item.get("transform")), oid, name)))
    return Project(objects, colours)


_NS = ('xmlns="http://schemas.microsoft.com/3dmanufacturing/core/2015/02" '
       'xmlns:BambuStudio="http://schemas.bambulab.com/package/2021" '
       'xmlns:p="http://schemas.microsoft.com/3dmanufacturing/production/2015/06" requiredextensions="p"')


def write(project: Project, out: Path, *, filaments: int, colours: list[str], offset: np.ndarray | None = None,
          flush: list[int] | None = None) -> None:
    """Write ``project`` as a clean OrcaSlicer 3MF. ``offset`` is added to every vertex; ``flush`` is the
    n x n purge matrix (mm³ before OrcaSlicer's 0.3 multiplier), 280 everywhere when omitted."""
    off = np.zeros(3) if offset is None else offset
    files: dict[str, str] = {}
    res_objects, items, cfg_objects, rels = [], [], [], []
    pid = 0
    for o in project.objects:
        comps, cfg_parts = [], []
        for p in o.parts:
            pid += 1
            fname = f"3D/Objects/part_{pid}.model"
            v = p.vertices + off
            tri = []
            for k, (a, b, c) in enumerate(p.faces):
                code = p.paint[k] if p.paint else None
                tri.append(f'     <triangle v1="{a}" v2="{b}" v3="{c}"' + (f' paint_color="{code}"' if code else "") + "/>")
            files[fname] = (
                f'<?xml version="1.0" encoding="UTF-8"?>\n<model unit="millimeter" xml:lang="en-US" {_NS}>\n'
                f' <resources>\n  <object id="{pid}" type="model">\n   <mesh>\n    <vertices>\n'
                + "\n".join(f'     <vertex x="{x:.5f}" y="{y:.5f}" z="{z:.5f}"/>' for x, y, z in v)
                + "\n    </vertices>\n    <triangles>\n" + "\n".join(tri)
                + "\n    </triangles>\n   </mesh>\n  </object>\n </resources>\n <build/>\n</model>\n"
            )
            comps.append(f'    <component p:path="/{fname}" objectid="{pid}" transform="1 0 0 0 1 0 0 0 1 0 0 0"/>')
            rels.append(f' <Relationship Target="/{fname}" Id="rel-{pid}" Type="http://schemas.microsoft.com/3dmanufacturing/2013/01/3dmodel"/>')
            cfg_parts.append(
                f'    <part id="{pid}" subtype="normal_part">\n      <metadata key="name" value={quoteattr(p.name)}/>\n'
                f'      <metadata key="matrix" value="1 0 0 0 0 1 0 0 0 0 1 0 0 0 0 1"/>\n'
                f'      <metadata key="extruder" value="{p.extruder}"/>\n    </part>')
        res_objects.append((o, comps, cfg_parts))
    oid = pid
    model_objs = []
    for o, comps, cfg_parts in res_objects:
        oid += 1
        model_objs.append(f'  <object id="{oid}" type="model">\n   <components>\n' + "\n".join(comps) + "\n   </components>\n  </object>")
        items.append(f'  <item objectid="{oid}" transform="1 0 0 0 1 0 0 0 1 0 0 0" printable="1"/>')
        first = o.parts[0].extruder if o.parts else 1
        cfg_objects.append(f'  <object id="{oid}">\n    <metadata key="name" value={quoteattr(o.name)}/>\n'
                           f'    <metadata key="extruder" value="{first}"/>\n' + "\n".join(cfg_parts) + "\n  </object>")
    files["3D/3dmodel.model"] = (
        f'<?xml version="1.0" encoding="UTF-8"?>\n<model unit="millimeter" xml:lang="en-US" {_NS}>\n'
        ' <metadata name="BambuStudio:3mfVersion">1</metadata>\n <resources>\n' + "\n".join(model_objs)
        + "\n </resources>\n <build>\n" + "\n".join(items) + "\n </build>\n</model>\n")
    files["3D/_rels/3dmodel.model.rels"] = (
        '<?xml version="1.0" encoding="UTF-8"?>\n<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">\n'
        + "\n".join(rels) + "\n</Relationships>\n")
    files["Metadata/model_settings.config"] = (
        '<?xml version="1.0" encoding="UTF-8"?>\n<config>\n' + "\n".join(cfg_objects)
        + '\n  <plate>\n    <metadata key="plater_id" value="1"/>\n    <metadata key="locked" value="false"/>\n  </plate>\n</config>\n')
    files["Metadata/project_settings.config"] = json.dumps({
        "filament_colour": colours[:filaments],
        "flush_volumes_matrix": [str(v) for v in flush] if flush else
                                ["0" if i == j else "280" for i in range(filaments) for j in range(filaments)],
        "flush_volumes_vector": ["140"] * (2 * filaments),
    }, indent=2)
    files["_rels/.rels"] = (
        '<?xml version="1.0" encoding="UTF-8"?>\n<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">\n'
        ' <Relationship Target="/3D/3dmodel.model" Id="rel-1" Type="http://schemas.microsoft.com/3dmanufacturing/2013/01/3dmodel"/>\n'
        "</Relationships>\n")
    files["[Content_Types].xml"] = (
        '<?xml version="1.0" encoding="UTF-8"?>\n<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">\n'
        ' <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>\n'
        ' <Default Extension="model" ContentType="application/vnd.ms-package.3dmanufacturing-3dmodel+xml"/>\n</Types>\n')
    out.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for name, data in files.items():
            z.writestr(name, data)


def plate_count(path: Path) -> int:
    """Number of plates of a Bambu/Orca project (1 for anything else)."""
    try:
        with zipfile.ZipFile(path) as z:
            cfg = z.read("Metadata/model_settings.config").decode("utf-8", "ignore")
    except (KeyError, OSError, zipfile.BadZipFile):
        return 1
    return max(1, len(re.findall(r"<plate>", cfg)))


def split_plates(path: Path, out_dir: Path | None = None) -> list[Path]:
    """A project with several plates laid side by side (Bambu Studio puts them 1.2 bed-widths apart)
    loads as one huge scattered scene. Write one 3MF per plate, objects moved back onto a single bed,
    everything else (painting, settings, meshes) kept byte for byte. Returns [] when there is one plate."""
    out_dir = out_dir or path.parent
    with zipfile.ZipFile(path) as z:
        names = z.namelist()
        if "Metadata/model_settings.config" not in names or "3D/3dmodel.model" not in names:
            return []
        cfg = z.read("Metadata/model_settings.config").decode("utf-8")
        plates = re.findall(r"<plate>.*?</plate>", cfg, re.S)
        if len(plates) < 2:
            return []
        model = z.read("3D/3dmodel.model").decode("utf-8")
        try:
            area = json.loads(z.read("Metadata/project_settings.config")).get("printable_area", [])
            bed = max(float(p.split("x")[0]) for p in area) or 256.0
        except (KeyError, ValueError):
            bed = 256.0
        step = bed * 1.2
        cols = int(np.ceil(np.sqrt(len(plates))))
        items = {m.group(1): m.group(0) for m in re.finditer(r'<item objectid="(\d+)"[^>]*/>', model)}
        objs = {m.group(1): m.group(0) for m in re.finditer(r'<object id="(\d+)".*?</object>', model, re.S)}
        cfg_objs = {m.group(1): m.group(0) for m in re.finditer(r'  <object id="(\d+)">.*?</object>', cfg, re.S)}
        head = model[:model.index("<resources>")]
        tail_cfg = cfg[cfg.rindex("</plate>") + len("</plate>"):]
        written = []
        for i, plate in enumerate(plates):
            ids = [x for x in re.findall(r'key="object_id" value="(\d+)"', plate) if x in items]
            if not ids:
                continue
            dx, dy = (i % cols) * step, -(i // cols) * step
            keep, build = set(ids), []
            for oid in ids:
                keep |= set(re.findall(r'<component [^>]*objectid="(\d+)"', objs[oid]))
                v = items[oid]
                t = re.search(r'transform="([^"]+)"', v)
                if t:
                    n = t.group(1).split()
                    n[9], n[10] = f"{float(n[9]) - dx:.6f}", f"{float(n[10]) - dy:.6f}"
                    v = v.replace(t.group(0), f'transform="{" ".join(n)}"')
                build.append("  " + v)
            n = i + 1
            sub = re.sub(rf"(?<=_){n}\.png", "1.png", plate)
            sub = re.sub(r'(key="plater_id" value=)"\d+"', r'\1"1"', sub)
            new_cfg = ('<?xml version="1.0" encoding="UTF-8"?>\n<config>\n'
                       + "\n".join(cfg_objs[o] for o in cfg_objs if o in keep) + "\n  " + sub + tail_cfg)
            new_model = (head + "<resources>\n" + "\n".join(objs[o] for o in objs if o in keep)
                         + "\n </resources>\n <build>\n" + "\n".join(build) + "\n </build>\n</model>\n")
            dst = out_dir / f"{path.stem}_plateau{n}.3mf"
            with zipfile.ZipFile(dst, "w", zipfile.ZIP_DEFLATED) as zo:
                for name in names:
                    if name == "3D/3dmodel.model":
                        zo.writestr(name, new_model)
                    elif name == "Metadata/model_settings.config":
                        zo.writestr(name, new_cfg)
                    else:
                        m = re.fullmatch(r"(Metadata/(?:plate|plate_no_light|top|pick)_)(\d+)(_small)?\.png", name)
                        if m and int(m.group(2)) != n:
                            continue
                        zo.writestr(m.group(1) + "1" + (m.group(3) or "") + ".png" if m else name, z.read(name))
            written.append(dst)
    return written
