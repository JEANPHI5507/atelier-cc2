import asyncio
import time
import json
from pathlib import Path

import httpx
import pytest
import trimesh

import fakeprinter as sim
from elegoo_lab import comfy, config, mesh


@pytest.fixture
async def printer():
    s = sim.Sim(port=18840, print_seconds=3, http_port=18850)
    task = asyncio.create_task(s.serve())
    await asyncio.sleep(0.2)
    import pycentauri.cc2 as cc2
    import pycentauri.connect as connect
    old = (cc2.MQTT_PORT, cc2._fetch_serial, connect._port_open)
    sim.patch_pycentauri()
    cc2.MQTT_PORT = 18840
    p = await connect.connect_auto("127.0.0.1", enable_control=True, access_code=sim.SIM_CODE)
    yield p
    await p.close()
    task.cancel()
    cc2.MQTT_PORT, cc2._fetch_serial, connect._port_open = old


async def test_sim_print_cycle(printer):
    assert (await printer.attributes()).mainboard_id == sim.SIM_SERIAL
    assert len((await printer.canvas_status()).canvas_list[0].tray_list) == 4
    await printer.start_print("cube_20mm.gcode")
    await asyncio.sleep(1.5)
    assert (await printer.status()).print_info.filename == "cube_20mm.gcode"
    for _ in range(40):
        await asyncio.sleep(0.5)
        if (await printer.status()).print_info.filename == "":
            break
    hist = (await printer.print_history())["history_task_list"]
    assert hist and hist[0]["task_status"] == 1


async def test_wrong_access_code():
    from pycentauri.client import PrinterError
    import pycentauri.connect as connect
    s = sim.Sim(port=18841, http_port=18851)
    task = asyncio.create_task(s.serve())
    await asyncio.sleep(0.2)
    import pycentauri.cc2 as cc2
    old = (cc2.MQTT_PORT, cc2._fetch_serial, connect._port_open)
    sim.patch_pycentauri(); cc2.MQTT_PORT = 18841
    try:
        with pytest.raises(PrinterError):
            await connect.connect_auto("127.0.0.1", access_code="wrong", connect_timeout=3)
    finally:
        task.cancel()
        cc2.MQTT_PORT, cc2._fetch_serial, connect._port_open = old


def test_mesh_prepare_scales_and_grounds(tmp_path):
    src = tmp_path / "ball.glb"
    trimesh.creation.icosphere(radius=0.5).export(src)  # unit-less AI-style output
    out = tmp_path / "ball.stl"
    info = mesh.prepare(src, out, height_mm=60)
    assert info["watertight"] and info["fits_bed"]
    assert max(info["size_mm"]) == pytest.approx(60, abs=0.5)
    assert trimesh.load(out).bounds[0][2] == pytest.approx(0, abs=1e-6)


def test_comfy_generate_roundtrip(tmp_path, monkeypatch):
    wf_dir = tmp_path / "wf"; wf_dir.mkdir()
    (wf_dir / "t.json").write_text(json.dumps({"1": {"inputs": {"image": "x", "seed": 0}}}))
    (wf_dir / "t.map.json").write_text(json.dumps({"image": ["1", "image"], "seed": ["1", "seed"]}))
    monkeypatch.setattr(comfy, "WORKFLOWS", wf_dir)
    sent = {}

    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.path == "/upload/image":
            return httpx.Response(200, json={"name": "up.png"})
        if req.url.path == "/prompt":
            sent.update(json.loads(req.content)); return httpx.Response(200, json={"prompt_id": "p1"})
        if req.url.path == "/history/p1":
            return httpx.Response(200, json={"p1": {"status": {"completed": True, "status_str": "success"},
                "outputs": {"9": {"3d": [{"filename": "m.glb", "subfolder": "", "type": "output"}]}}}})
        if req.url.path == "/view":
            return httpx.Response(200, content=b"glbdata")
        return httpx.Response(404)

    c = comfy.Comfy("http://x")
    c.http = httpx.Client(base_url="http://x", transport=httpx.MockTransport(handler))
    img = tmp_path / "in.png"; img.write_bytes(b"png")
    files = comfy.generate(c, "t", tmp_path, image=img)
    assert files[0].read_bytes() == b"glbdata" and files[0].suffix == ".glb"
    assert sent["prompt"]["1"]["inputs"]["image"] == "up.png"
    with pytest.raises(comfy.ComfyError):
        comfy.load_workflow("nope")


def test_slice_cylinder_and_overrides(tmp_path):
    from elegoo_lab import slicer
    if not (slicer.TOOLS / "squashfs-root" / "AppRun").exists():
        pytest.skip("slicer non installé (make slicer)")
    src = tmp_path / "cyl.stl"
    trimesh.creation.cylinder(radius=10, height=20, sections=48).export(src)
    r = slicer.slice_model(src, tmp_path / "out", infill=5, supports=False)
    assert r.layers == 100 and r.gcode[0].exists() and "Centauri Carbon 2" in r.gcode[0].read_text(errors="ignore")
    dense = slicer.slice_model(src, tmp_path / "out2", infill=60)
    assert dense.filament_m > r.filament_m  # overrides really reach the slicer
    with pytest.raises(slicer.SliceError):
        slicer.slice_model(src, tmp_path / "o3", quality="nope")
    with pytest.raises(slicer.SliceError):
        slicer.slice_model(tmp_path / "x.txt", tmp_path / "o4")


def test_multicolor_parts_change_tool_at_junction(tmp_path):
    from elegoo_lab import colorize, slicer
    if not (slicer.TOOLS / "squashfs-root" / "AppRun").exists():
        pytest.skip("slicer non installé (make slicer)")
    base = trimesh.creation.box((30, 30, 10)); base.apply_translation((0, 0, 5)); base.export(tmp_path / "b.stl")
    top = trimesh.creation.cylinder(radius=8, height=10, sections=32); top.apply_translation((0, 0, 15)); top.export(tmp_path / "t.stl")
    info = colorize.build_3mf([(tmp_path / "b.stl", 1), (tmp_path / "t.stl", 2)], tmp_path / "duo.3mf")
    assert info["filaments"] == 2
    r = slicer.slice_model(tmp_path / "duo.3mf", tmp_path / "o", filament=["PLA", "PLA Matte"])
    g = r.gcode[0].read_text(errors="ignore")
    assert "\nT1\n" in g and g.count("\nT0\n") >= 1
    # wrong filament count for the 3MF, bad slot, and incompatible temperatures are all refused
    with pytest.raises(slicer.SliceError):
        slicer.slice_model(tmp_path / "duo.3mf", tmp_path / "o2", filament=["PLA"])
    with pytest.raises(ValueError):
        colorize.build_3mf([(tmp_path / "b.stl", 5)], tmp_path / "x.3mf")
    with pytest.raises(slicer.SliceError):
        slicer.slice_model(tmp_path / "duo.3mf", tmp_path / "o3", filament=["PLA", "PETG"])


def test_paint_codes_roundtrip_and_remap():
    from elegoo_lab import colors
    assert [colors.encode_state(s) for s in (1, 2, 3, 4)] == ["4", "8", "0C", "1C"]
    for s in range(0, 10):
        assert colors.paint_states(colors.encode_state(s)) == {s}
    assert colors.remap_paint("8", {2: 4}) == "1C"
    # triangle split in two (split=1, special side 0) with leaves 1 and 2: bits 1,0|0,0|0,0,1,0|0,0,0,1
    split = "841"
    assert colors.paint_states(split) == {1, 2}
    assert colors.remap_paint(split, {}) == split
    assert colors.paint_states(colors.remap_paint(split, {1: 4})) == {4, 2}


def test_coloured_mesh_to_canvas_and_slice(tmp_path):
    import numpy as np
    from elegoo_lab import colors, printprep, slicer
    if not (slicer.TOOLS / "squashfs-root" / "AppRun").exists():
        pytest.skip("slicer non installé (make slicer)")
    m = trimesh.creation.box((20, 20, 20)).subdivide().subdivide()
    top = m.triangles_center[:, 2] > 0
    m.visual.face_colors = np.where(top[:, None], [20, 60, 230, 255], [230, 30, 30, 255])
    src = tmp_path / "bicolore.ply"
    m.export(src)
    a = colors.analyze(src)
    assert len(a["colours"]) == 2 and a["multicolour"]
    res = printprep.prepare_and_slice(src, filaments=["PLA", "PLA Matte"], out_dir=tmp_path)
    g = (tmp_path / res["gcode"][0]).read_text(errors="ignore")
    assert "\nT1\n" in g and len(res["slots"]) == 2 and all(s["metres"] > 0 for s in res["slots"])
    # swapping slots swaps the filament usage
    swapped = printprep.prepare_and_slice(src, mapping={c["index"]: 3 - c["slot"] for c in a["colours"]},
                                          filaments=["PLA", "PLA Matte"], out_dir=tmp_path)
    assert [s["metres"] for s in swapped["slots"]] == pytest.approx([s["metres"] for s in res["slots"]][::-1], rel=0.05)


STD_3MF = """<?xml version="1.0" encoding="UTF-8"?>
<model unit="millimeter" xmlns="http://schemas.microsoft.com/3dmanufacturing/core/2015/02" xmlns:m="http://schemas.microsoft.com/3dmanufacturing/material/2015/02">
 <resources>
  <m:colorgroup id="2"><m:color color="#FF0000FF"/><m:color color="#0000FFFF"/></m:colorgroup>
  <object id="1" type="model" pid="2" pindex="0"><mesh><vertices>{v}</vertices><triangles>{t}</triangles></mesh></object>
 </resources>
 <build><item objectid="1"/></build>
</model>"""


def _std_3mf(path):
    """Standard-3MF (colorgroup) box: top half blue, rest red — the format Blender/3D Builder write."""
    import zipfile
    m = trimesh.creation.box((20, 20, 20)).subdivide().subdivide()
    m.apply_translation((50, 50, 10))
    v = "".join(f'<vertex x="{x}" y="{y}" z="{z}"/>' for x, y, z in m.vertices)
    t = "".join(f'<triangle v1="{a}" v2="{b}" v3="{c}"' + (' pid="2" p1="1"' if zc > 10 else "") + "/>"
                for (a, b, c), zc in zip(m.faces, m.triangles_center[:, 2]))
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("3D/3dmodel.model", STD_3MF.format(v=v, t=t))
        z.writestr("_rels/.rels", '<?xml version="1.0"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                   '<Relationship Target="/3D/3dmodel.model" Id="r" Type="http://schemas.microsoft.com/3dmanufacturing/2013/01/3dmodel"/></Relationships>')


def test_standard_3mf_colours_and_roundtrip(tmp_path):
    from elegoo_lab import colors, printprep, slicer, threemf
    src = tmp_path / "std.3mf"
    _std_3mf(src)
    a = colors.analyze(src)
    assert sorted(c["hex"] for c in a["colours"]) == ["#0000FF", "#FF0000"]
    # clean rewrite keeps geometry, objects and extruders
    out = tmp_path / "canvas.3mf"
    colors.to_canvas(src, out, {c["index"]: c["slot"] for c in a["colours"]})
    pr = threemf.read(out)
    assert len(pr.objects) == 1 and pr.objects[0].parts[0].paint and pr.colours[:2] == [c["hex"] for c in a["colours"]][:2]
    if not (slicer.TOOLS / "squashfs-root" / "AppRun").exists():
        pytest.skip("slicer non installé")
    r = printprep.prepare_and_slice(src, out_dir=tmp_path)
    assert len(r["slots"]) == 2 and all(s["metres"] > 0 for s in r["slots"]) and r["colour_changes"] >= 1


def test_3mf_reader_unusual_shapes_and_cache(tmp_path):
    import os
    import zipfile
    from elegoo_lab import threemf
    head = ('<?xml version="1.0"?>\n<model unit="centimeter" xmlns="http://schemas.microsoft.com/3dmanufacturing/core/2015/02"'
            ' xmlns:m="http://schemas.microsoft.com/3dmanufacturing/material/2015/02" xmlns:s="http://schemas.slic3r.org/3mf/2017/06">')
    verts = '<vertices><vertex y="2" x="1" z="3"/><vertex x="4" y="5" z="6" /><vertex x="7" y="8" z="9"/></vertices>'
    tris = ('<triangles><triangle v3="2" v1="0" v2="1" s:mmu_segmentation="8"/>\n<triangle\n v1="0"\tv2="2" v3="1"/>'
            '<triangle v1="1" v2="2" v3="0" paint_color="" s:mmu_segmentation="C" pid="5" p1="0"/></triangles>')
    doc = (head + '<resources><m:colorgroup id="5"><m:color color="#FF0000"/><m:color color="#00FF00"/></m:colorgroup>'
           f'<object id="1" type="model" pid="5" pindex="1"><mesh>{verts}{tris}</mesh></object>'
           '<object id="2" type="model"><mesh/></object></resources><build><item objectid="1"/></build></model>')
    src = tmp_path / "odd.3mf"
    with zipfile.ZipFile(src, "w") as z:
        z.writestr("3D/3dmodel.model", doc)
    p = threemf.read(src).objects[0].parts[0]
    assert p.vertices[0].tolist() == [10, 20, 30]                                    # attribute order, unit
    assert p.faces.tolist() == [[0, 1, 2], [0, 2, 1], [1, 2, 0]]
    assert p.paint == ["8", None, "C"]                                               # an empty paint_color falls back
    assert p.face_rgb.tolist() == [[0, 255, 0], [0, 255, 0], [255, 0, 0]]            # object colour, then the triangle's
    p.vertices += 100                                                                # a caller moving its copy...
    assert threemf.read(src).objects[0].parts[0].vertices[0].tolist() == [10, 20, 30]  # ...never moves the cached one
    with zipfile.ZipFile(src, "w") as z:
        z.writestr("3D/3dmodel.model", doc.replace('y="2" x="1"', 'y="2" x="2"'))
    os.utime(src, ns=(src.stat().st_mtime_ns + 10**6,) * 2)
    assert threemf.read(src).objects[0].parts[0].vertices[0].tolist() == [20, 20, 30]  # a new version is read again


def test_variable_layer_height_follows_the_slopes(tmp_path):
    import re
    import zipfile
    import numpy as np
    from elegoo_lab import couches, printprep, settings, slicer
    ball = trimesh.creation.icosphere(4, radius=15)
    ball.apply_translation([0, 0, 15])
    b = couches.bands(np.asarray(ball.vertices), np.asarray(ball.faces), 0.2, "pentes")
    h = lambda z: next(x for z0, z1, x in b if z0 <= z <= z1)                         # noqa: E731
    assert h(29.5) < h(15) == 0.2 and min(x for *_, x in b) >= couches.MIN_MM       # thin at the pole, as is at the equator
    tube = trimesh.creation.cylinder(radius=10, height=30, sections=64)
    tube.apply_translation([0, 0, 15])
    assert couches.bands(np.asarray(tube.vertices), np.asarray(tube.faces), 0.2, "rapide") == [(0.0, 30.0, 0.28)]   # walls only
    with pytest.raises(ValueError):
        settings.build({"couches": "partout"})
    if not (slicer.TOOLS / "squashfs-root" / "AppRun").exists():
        pytest.skip("slicer non installé")
    src = tmp_path / "boule.stl"
    ball.export(src)
    flat = printprep.prepare_and_slice(src, out_dir=tmp_path / "a", advanced={"couches": "non"})
    var = printprep.prepare_and_slice(src, out_dir=tmp_path / "b", advanced={"couches": "pentes"})
    assert zipfile.ZipFile(tmp_path / "b" / "boule_canvas.3mf").read("Metadata/layer_config_ranges.xml").count(b"<range") > 2
    assert var["layers"] > flat["layers"] and any("couches de plus" in w for w in var["warnings"])
    g = (tmp_path / "b" / var["gcode"][0]).read_text(errors="ignore")
    zs = [float(z) for z in re.findall(r"^;Z:([\d.]+)", g, re.M)]
    assert min(round(b - a, 2) for a, b in zip(zs, zs[1:])) < 0.2


def test_painted_supports_and_seam_reach_the_slicer():
    import zipfile
    from elegoo_lab import colors, printprep, slicer, threemf
    foot, cap = trimesh.creation.box((8, 8, 20)), trimesh.creation.box((30, 30, 4))
    foot.apply_translation([0, 0, 10])
    cap.apply_translation([0, 0, 22])
    src = config.MODELS_DIR / "champi.stl"                                           # a mushroom: the cap hangs out
    trimesh.util.concatenate([foot, cap]).export(src)
    pv = colors.preview_glb(src)
    under = [i for i, (c, n) in enumerate(zip(pv.triangles_center, pv.face_normals)) if n[2] < -0.9 and c[1] > 19]   # Y-up
    assert colors.save_marks(src, {"support": under, "couture": [0]}) == {"support": len(under), "couture": 1}
    with pytest.raises(ValueError):
        colors.save_marks(src, {"partout": [1]})
    out = config.MODELS_DIR / "c.3mf"
    colors.to_canvas(src, out, {1: 1}, copies=2)
    parts = [p for o in threemf.read(out).objects for p in o.parts]
    assert all(sum(1 for c in p.supports if c) == len(under) and p.seam[0] for p in parts)   # every copy carries them
    assert b'paint_supports="4"' in zipfile.ZipFile(out).read("3D/Objects/part_1.model")
    if not (slicer.TOOLS / "squashfs-root" / "AppRun").exists():
        pytest.skip("slicer non installé")
    support = lambda r, d: (d / r["gcode"][0]).read_text(errors="ignore").count(";TYPE:Support")   # noqa: E731
    d = config.MODELS_DIR / "a"
    r = printprep.prepare_and_slice(src, out_dir=d)
    assert support(r, d) > 0 and any("peints" in w for w in r["warnings"])         # painted, none asked: only there
    colors.save_marks(src, {"sans_support": list(range(len(pv.faces)))}, clear=False)
    d = config.MODELS_DIR / "b"
    assert support(printprep.prepare_and_slice(src, out_dir=d, supports=True), d) == 0   # never here, everywhere


def test_drill_add_or_keep_a_shape():
    from elegoo_lab import colors, forme, threemf
    lib = config.MODELS_DIR
    trimesh.creation.box((30, 30, 10)).export(lib / "plaque.stl")
    vol = lambda n: sum(trimesh.Trimesh(p.vertices, p.faces).volume for o in threemf.read(lib / n).objects for p in o.parts)  # noqa: E731
    hole = forme.apply(lib / "plaque.stl", shape="cylindre", op="percer", size=(8, 8, 20), at=(0, 0, 0))
    assert hole["name"] == "plaque_perce.3mf" and abs(vol(hole["name"]) - (9000 - 3.1416 * 16 * 10)) < 60
    peg = forme.apply(lib / "plaque.stl", shape="cylindre", op="ajouter", size=(8, 8, 20), at=(0, 0, 5), colour=2)
    parts = [p for o in threemf.read(lib / peg["name"]).objects for p in o.parts]
    assert [p.extruder for p in parts] == [1, 2] and abs(vol(peg["name"]) - (9000 + 3.1416 * 16 * 10)) < 60   # no overlap: the 10 mm above
    assert forme.apply(lib / "plaque.stl", shape="sphere", op="garder", size=(10, 10, 10), at=(0, 0, 0))["size_mm"] == [10.0, 10.0, 10.0]
    with pytest.raises(ValueError):
        forme.apply(lib / "plaque.stl", shape="cylindre", op="percer", size=(8, 8, 20), at=(100, 0, 0))   # misses: nothing changes
    two = trimesh.creation.box((20, 20, 20))
    two.unmerge_vertices()
    two.visual = trimesh.visual.ColorVisuals(two, face_colors=[[200, 0, 0, 255]] * 6 + [[0, 120, 0, 255]] * 6)
    two.export(lib / "deux.glb")
    cut = forme.apply(lib / "deux.glb", shape="sphere", op="percer", size=(14, 14, 14), at=(0, 0, 10))
    assert sorted(c["hex"] for c in colors.analyze(lib / cut["name"])["colours"]) == ["#007800", "#C80000"]   # no blend


def test_pieces_placed_by_hand_stay_on_the_plate():
    from elegoo_lab import colors
    src = config.MODELS_DIR / "cube.stl"
    trimesh.creation.box((20, 20, 20)).export(src)
    out = config.MODELS_DIR / "c.3mf"
    colors.to_canvas(src, out, {1: 1}, shift=(-60.0, 40.0))                         # moved, still on the plate
    with pytest.raises(ValueError, match="sort du plateau"):
        colors.to_canvas(src, out, {1: 1}, shift=(130.0, 0.0))
    with pytest.raises(ValueError, match="coin avant droit"):                       # the CC2 does not print there
        colors.to_canvas(src, out, {1: 1}, shift=(110.0, -110.0))


def test_two_models_on_one_plate_then_one_piece_resized(web):
    """« + Pièce »: two library models side by side in a new model, colours shared; one piece then resized on the plate."""
    import numpy as np
    from elegoo_lab import colors, compose, threemf
    client, lib = web
    trimesh.creation.box((20, 20, 20)).export(lib / "bloc.stl")
    trimesh.creation.cylinder(radius=8, height=30).export(lib / "tube.stl")
    r = client.post("/lab/api/composer", json={"names": ["bloc.stl", "tube.stl"]}).json()
    assert r["name"] == "bloc + tube.3mf" and r["pieces"] == 2 and len(r["colours"]) == 1    # same default colour: one spool
    pr = threemf.read(lib / r["name"])
    a, b = (np.vstack([p.vertices for p in o.parts]) for o in pr.objects)
    assert [o.name for o in pr.objects] == ["bloc", "tube"]
    assert b[:, 0].min() - a[:, 0].max() >= compose.GAP_MM - .01 and a[:, 2].min() == 0 == b[:, 2].min()
    assert client.post("/lab/api/composer", json={"names": ["bloc.stl"]}).status_code == 422
    out = lib / "bloc_plateau.3mf"
    colors.to_canvas(lib / r["name"], out, {1: 1}, scales={1: 2.0})
    a2, b2 = (np.vstack([p.vertices for p in o.parts]) for o in threemf.read(out).objects)
    assert np.ptp(b2[:, 2]) == pytest.approx(60, abs=.01) and np.ptp(a2[:, 2]) == pytest.approx(20, abs=.01)
    assert b2[:, 2].min() == pytest.approx(0, abs=.01)                        # resized about its foot: still on the plate
    assert (b2[:, 0].min() + b2[:, 0].max()) / 2 - (a2[:, 0].min() + a2[:, 0].max()) / 2 == pytest.approx(
        (b[:, 0].min() + b[:, 0].max()) / 2 - (a[:, 0].min() + a[:, 0].max()) / 2, abs=.01)   # and in the same place
    body = {"mapping": {"1": 1}, "scales": {"1": 9}}
    assert client.post(f"/lab/api/models/{r['name']}/prepare-print", json=body).status_code == 422


def test_composed_plate_loses_one_piece(web):
    """« Supprimer cette pièce »: one piece leaves the plate in a new model; the others keep place and size."""
    import numpy as np
    from elegoo_lab import threemf
    client, lib = web
    trimesh.creation.box((20, 20, 20)).export(lib / "bloc.stl")
    trimesh.creation.cylinder(radius=8, height=30).export(lib / "tube.stl")
    r = client.post("/lab/api/composer", json={"names": ["bloc.stl", "tube.stl"]}).json()
    out = client.post(f"/lab/api/models/{r['name']}/retirer", json={"index": 0, "moves": {}, "scales": {}}).json()
    assert out["pieces"] == 1 and out["piece"] == "bloc" and out["name"] == "bloc + tube sans bloc.3mf"
    pr = threemf.read(lib / out["name"])
    assert [o.name for o in pr.objects] == ["tube"]
    assert (lib / r["name"]).exists()                        # the original plate stays in the library
    before = np.vstack([p.vertices for p in threemf.read(lib / r["name"]).objects[1].parts])
    after = np.vstack([p.vertices for p in pr.objects[0].parts])
    assert np.allclose(before.max(0), after.max(0), atol=.01) and np.allclose(before.min(0), after.min(0), atol=.01)
    # the viewer's placements follow the surviving pieces (indexes shift past the removed one)
    out2 = client.post(f"/lab/api/models/{r['name']}/retirer",
                       json={"index": 1, "moves": {"0": [15.0, 2.0, 0.0]}, "scales": {"0": 2.0}}).json()
    assert out2["piece"] == "tube"
    base = np.vstack([p.vertices for p in threemf.read(lib / r["name"]).objects[0].parts])   # the bloc as composed
    kept = np.vstack([p.vertices for p in threemf.read(lib / out2["name"]).objects[0].parts])
    assert np.ptp(kept[:, 2]) == pytest.approx(40, abs=.01) and kept[:, 2].min() == pytest.approx(0, abs=.01)
    assert kept[:, 0].max() == pytest.approx(base[:, 0].max() + (base[:, 0].max() - base[:, 0].min()) / 2 + 15, abs=.05)
    assert kept[:, 0].min() == pytest.approx(base[:, 0].min() - (base[:, 0].max() - base[:, 0].min()) / 2 + 15, abs=.05)
    assert client.post(f"/lab/api/models/{out['name']}/retirer", json={"index": 0}).status_code == 422
    assert client.post(f"/lab/api/models/{r['name']}/retirer", json={"index": 7}).status_code == 422


def test_compact_preview_glb_is_face_for_face():
    import struct
    import numpy as np
    from elegoo_lab import colors
    src = config.MODELS_DIR / "boule.stl"
    trimesh.creation.icosphere(2, radius=10).export(src)
    glb = colors.preview_glb_bytes(src)
    n, kind = struct.unpack("<I4s", glb[12:20])
    gltf = json.loads(glb[20:20 + n])
    prim = gltf["meshes"][0]["primitives"][0]
    assert glb[:4] == b"glTF" and struct.unpack("<I", glb[8:12])[0] == len(glb) and "indices" not in prim
    acc = {k: gltf["accessors"][i] for k, i in prim["attributes"].items()}
    assert acc["POSITION"]["count"] == 3 * 320 and acc["NORMAL"]["componentType"] == 5120   # one corner per face corner
    assert gltf["extensionsRequired"] == ["KHR_mesh_quantization"]
    ref = colors.preview_glb(src)
    start = 20 + n + 8
    view = gltf["bufferViews"][acc["POSITION"]["bufferView"]]
    pos = np.frombuffer(glb[start + view["byteOffset"]:start + view["byteOffset"] + view["byteLength"]], np.float32)
    assert np.allclose(pos.reshape(-1, 3), ref.vertices, atol=1e-5)


def test_economy_mode_purge_and_tower(tmp_path):
    import numpy as np
    from elegoo_lab import colors, printprep, slicer
    fm = colors.flush_matrix(["#FFFF00", "#101010"])  # yellow, black
    assert fm[0] == 0 and fm[1] < fm[2]  # yellow->black needs less purge than black->yellow
    assert colors.flush_matrix(["#FFFF00", "#101010"], smart=False)[1] == colors.FLUSH_MAX
    if not (slicer.TOOLS / "squashfs-root" / "AppRun").exists():
        pytest.skip("slicer non installé")
    m = trimesh.creation.box((20, 20, 20)).subdivide().subdivide()
    m.visual.face_colors = np.where((m.triangles_center[:, 2] > 0)[:, None], [250, 220, 0, 255], [20, 20, 20, 255])
    src = tmp_path / "bi.ply"; m.export(src)
    eco = printprep.prepare_and_slice(src, out_dir=tmp_path / "e", mode="economie")
    qual = printprep.prepare_and_slice(src, out_dir=tmp_path / "q", mode="qualite")
    g_eco = (tmp_path / "e" / eco["gcode"][0]).read_text(errors="ignore")
    assert ";TYPE:Prime tower" not in g_eco and "\nT1\n" in g_eco
    assert eco["total_m"] < qual["total_m"] and sum(eco["purge_m"]) > 0


def test_a_bled_review_reinforces_the_purge(tmp_path):
    import numpy as np
    from elegoo_lab import colors, library, printprep, slicer
    if not (slicer.TOOLS / "squashfs-root" / "AppRun").exists():
        pytest.skip("slicer non installé")
    m = trimesh.creation.box((20, 20, 20)).subdivide().subdivide()
    m.visual.face_colors = np.where((m.triangles_center[:, 2] > 0)[:, None], [20, 20, 20, 255], [240, 240, 240, 255])
    src = tmp_path / "bi.ply"; m.export(src)
    # white -> slot 1 (printed first), black -> slot 2: the single change is light -> dark, the cheap
    # direction, so only the reinforced slice pays the worst-case purge
    a = colors.analyze(src)
    mapping = {c["index"]: 1 if c["hex"].upper().startswith("#F") else 2 for c in a["colours"]}
    eco = printprep.prepare_and_slice(src, out_dir=tmp_path / "e", mode="economie", mapping=mapping)
    library.annotate(src.name, retour={"issues": ["couleurs"]})   # what aftercare.review stores after a bad print
    fixed = printprep.prepare_and_slice(src, out_dir=tmp_path / "f", mode="economie", mapping=mapping)
    # the white->black change purges the worst case instead of the cheap smart guess (the start
    # load's own purge, purge_m[0], does not move)
    assert fixed["purge_m"][1] > 2 * eco["purge_m"][1]
    assert any("Purge renforcée" in w for w in fixed["warnings"])


def test_cut_oversized_into_pieces_with_dowels():
    import numpy as np
    from elegoo_lab import cut
    m = trimesh.creation.box((60, 60, 300))
    m.apply_translation((30, 30, 150))
    m = m.subdivide().subdivide()
    slots = np.where(m.triangles_center[:, 2] > 150, 2, 1)
    res = cut.cut(np.asarray(m.vertices), np.asarray(m.faces), slots, name="pave")
    assert [a for a, _ in res.planes] == [2] and len(res.pieces) == 2 and res.pin_count >= 1
    for p in res.pieces:
        piece = trimesh.Trimesh(p.vertices, p.faces, process=False)
        assert piece.is_watertight and np.ptp(p.vertices[:, 2]) <= 256 - cut.MARGIN_MM
        assert piece.volume < 60 * 60 * 150  # the dowel holes were drilled
    assert {int(s) for p in res.pieces for s in np.unique(p.slots)} == {1, 2}
    assert res.pins is not None and len(res.pins.split()) == res.pin_count


def test_config_save_keeps_other_settings(tmp_path, monkeypatch):
    from elegoo_lab import config
    monkeypatch.setattr(config, "CONFIG_FILE", tmp_path / "config.toml")
    (tmp_path / "config.toml").write_text('[comfyui]\nurl = "http://gpu:8188"\n')
    config.save("printer", host="192.168.1.42", access_code='Ab"3')
    config.save("assemblage", jeu_mm=0.2)
    c = config.load()
    assert (c.printer.host, c.printer.access_code, c.comfyui_url) == ("192.168.1.42", 'Ab"3', "http://gpu:8188")
    assert config.dowel_play() == 0.2


def test_calibration_pieces_are_printable(tmp_path):
    from elegoo_lab import calibration, colors, mesh
    for t in calibration.TESTS:
        p = tmp_path / t.file
        t.build(p)
        info = mesh.info(p)
        assert info["watertight"] and info["fits_bed"], t.key
        assert len(colors.analyze(p)["colours"]) == t.colours, t.key


async def test_connection_check_on_simulator():
    from elegoo_lab import connexion
    port, http_port = sim.SIM_PORT + 100, sim.SIM_HTTP_PORT + 100
    s = sim.Sim(port=port, http_port=http_port)
    task = asyncio.create_task(s.serve())
    await asyncio.sleep(0.3)
    try:
        ok = await connexion.check(sim.SIM_HOST, sim.SIM_CODE, mqtt_port=port, http_port=http_port)
        assert ok["ok"] and [st["ok"] for st in ok["steps"]] == [True, True, True]
        assert ok["serial"] == sim.SIM_SERIAL
        empty = await connexion.check("", "x")
        assert not empty["ok"] and empty["steps"][0]["fix"]
    finally:
        task.cancel()


def test_smart_cut_goes_through_the_neck():
    import numpy as np
    from elegoo_lab import cut
    # a 300 mm "figure": wide body, thin neck at z=190, wide head
    body = trimesh.creation.box((80, 80, 180)); body.apply_translation((0, 0, 90))
    neck = trimesh.creation.cylinder(radius=10, height=30, sections=48); neck.apply_translation((0, 0, 195))
    head = trimesh.creation.box((70, 70, 90)); head.apply_translation((0, 0, 255))
    import manifold3d as mf
    def m(t): return mf.Manifold(mf.Mesh(vert_properties=np.asarray(t.vertices, np.float32), tri_verts=np.asarray(t.faces, np.uint32)))
    fig = (m(body) + m(neck) + m(head)).to_mesh()
    v, f = np.asarray(fig.vert_properties)[:, :3].astype(float), np.asarray(fig.tri_verts).astype(np.int64)
    smart = cut.cut(v, f, np.ones(len(f), int), name="fig")
    even = cut.cut(v, f, np.ones(len(f), int), name="fig", smart=False)
    (axis, z), = smart.planes
    assert axis == 2 and 178 <= z <= 212, z         # at or through the neck (180 = body/neck junction)
    assert not 180 < even.planes[0][1] < 210        # even spacing would cut the body


def test_comfy_chained_workflow_frees_vram_between_stages(tmp_path, monkeypatch):
    from elegoo_lab import comfy
    wf_dir = tmp_path / "wf"; wf_dir.mkdir()
    (wf_dir / "a.json").write_text(json.dumps({"1": {"inputs": {"image": "x"}}}))
    (wf_dir / "a.map.json").write_text(json.dumps({"image": ["1", "image"], "next": "b"}))
    (wf_dir / "b.json").write_text(json.dumps({"7": {"inputs": {"image": "x"}}}))
    (wf_dir / "b.map.json").write_text(json.dumps({"image": ["7", "image"]}))
    monkeypatch.setattr(comfy, "WORKFLOWS", wf_dir)
    calls, uploads = [], []

    def handler(req):
        path = req.url.path
        calls.append(path)
        if path == "/upload/image":
            uploads.append(req.content.count(b"figurine"))
            return httpx.Response(200, json={"name": f"up{len(uploads)}.png"})
        if path == "/prompt":
            graph = json.loads(req.content)["prompt"]
            return httpx.Response(200, json={"prompt_id": "pa" if "1" in graph else "pb"})
        if path == "/history/pa":
            return httpx.Response(200, json={"pa": {"status": {"completed": True}, "outputs": {"9": {"images": [
                {"filename": "figurine.png", "subfolder": "", "type": "output"},
                {"filename": "tmp_preview.png", "subfolder": "", "type": "temp"}]}}}})
        if path == "/history/pb":
            return httpx.Response(200, json={"pb": {"status": {"completed": True}, "outputs": {"5": {"3d": [
                {"filename": "m.glb", "subfolder": "", "type": "output"}]}}}})
        if path == "/view":
            return httpx.Response(200, content=b"data")
        return httpx.Response(200, json={})

    c = comfy.Comfy("http://x")
    c.http = httpx.Client(base_url="http://x", transport=httpx.MockTransport(handler))
    img = tmp_path / "photo.png"; img.write_bytes(b"png")
    files = comfy.generate(c, "a", tmp_path, image=img)
    names = [f.name for f in files]
    assert any(n.endswith("figurine.png") for n in names) and any(n.endswith("m.glb") for n in names)
    assert not any("tmp_preview" in n for n in names)            # temp previews are not kept
    assert calls.index("/free") < calls.index("/history/pb")      # VRAM freed before stage 2 runs
    assert len(uploads) == 2                                      # stage 2 received stage 1's image


def test_spool_matching_follows_loaded_canvas():
    from elegoo_lab import spools
    trays = spools.loaded({"canvas_info": {"canvas_list": [{"tray_list": [
        {"tray_id": 0, "color": "#FFFFFF", "type": "PLA", "filament_name": "PLA Matte Blanc", "status": 1},
        {"tray_id": 1, "color": "#E53935", "type": "PLA", "filament_name": "PLA Rouge", "status": 1},
        {"tray_id": 2, "color": "", "type": "", "status": 0},
        {"tray_id": 3, "color": "#1E1E1E", "type": "PETG", "filament_name": "PETG Noir", "status": 1}]}]}})
    assert [t["tray_id"] for t in trays] == [0, 1, 3]            # the empty tray is ignored
    model = [{"index": 1, "hex": "#D02020", "share": 70.0}, {"index": 2, "hex": "#F4F4F4", "share": 30.0}]
    r = spools.match(model, trays)
    assert r["mapping"] == {1: 2, 2: 1}                           # red -> T1, white -> T0
    assert r["filaments"] == ["PLA Matte", "PLA"] and not r["warnings"]
    green = spools.match([{"index": 1, "hex": "#20C040", "share": 50.0}], trays)
    assert green["warnings"] and "pas de bobine proche" in green["warnings"][0]
    mixed = spools.match([{"index": 1, "hex": "#FFFFFF", "share": 50.0}, {"index": 2, "hex": "#101010", "share": 50.0}], trays)
    assert any("incompatibles" in w for w in mixed["warnings"])   # PLA + PETG


def test_a_colour_needs_grams_before_any_slicing(web):
    """The colour step says how many grams each colour will use (from the model's volume), so a nearly
    empty spool is caught before slicing, not when the print is already running."""
    from types import SimpleNamespace as NS
    import numpy as np
    from elegoo_lab import spools
    # solid 160 cm³, split in two equal colours: Décoratif ≈ 30 g each, Solide ≈ 95 g each
    model = [{"index": 1, "share": 50.0}, {"index": 2, "share": 50.0}]
    dec = spools.needs(160.0, model, usage="decoratif")
    fun = spools.needs(160.0, model, usage="fonctionnel")
    assert 20 <= dec[1] <= 40 and fun[1] > 3 * dec[1] and spools.needs(None, model) == {}

    client, lib = web
    m = trimesh.creation.box((100, 40, 40)).subdivide().subdivide()
    m.visual.face_colors = np.where((m.triangles_center[:, 2] > 0)[:, None], [250, 220, 0, 255], [20, 20, 20, 255])
    m.export(lib / "bi.ply")

    async def canvas():
        return NS(raw={"canvas_info": {"canvas_list": [{"canvas_id": 0, "tray_list": [
            {"tray_id": 0, "status": 1, "filament_color": "#FADC00", "filament_type": "PLA"},
            {"tray_id": 1, "status": 1, "filament_color": "#141414", "filament_type": "PLA"}]}]}})

    client.app.state.manager = NS(printer=NS(canvas_status=canvas))
    r = client.get("/lab/api/models/bi.ply/match-spools?usage=decoratif").json()
    assert set(r["needs"]) == {"1", "2"} and 20 <= int(r["needs"]["1"]) <= 40 and not r["warnings"]
    strong = client.get("/lab/api/models/bi.ply/match-spools?usage=fonctionnel").json()
    assert int(strong["needs"]["1"]) > 3 * int(r["needs"]["1"])

    from elegoo_lab import stock
    stock.calibrate_fill("decoratif", 100.0, 200.0)         # a real slice measured at twice the estimate
    after = spools.needs(160.0, model, usage="decoratif")
    assert dec[1] * 1.2 < after[1] <= dec[1] * 2            # the factor moved halfway, never straight to it
    assert stock.fill_factor("decoratif") == 1.5            # (100 g in, 200 g measured: ratio 2, half step)


def test_one_colour_model_takes_a_loaded_spool(tmp_path):
    from elegoo_lab import launch, spools
    trays = spools.loaded({"canvas_info": {"canvas_list": [{"tray_list": [
        {"tray_id": 1, "filament_color": "#E53935", "filament_type": "PLA", "filament_name": "PLA Rouge", "status": 2},
        {"tray_id": 2, "filament_color": "#FFFFFF", "filament_type": "PLA", "filament_name": "PLA Blanc", "status": 2},
        {"tray_id": 3, "filament_color": "#1E88E5", "filament_type": "PETG", "filament_name": "PETG Bleu", "status": 2}]}]}})
    blue = spools.single({"index": 1, "hex": "#2080E0", "share": 100.0}, trays, coloured=True)
    assert blue["mapping"] == {1: 1} and blue["single"]["pos"] == 2      # sliced as T0, fed by the third spool
    assert blue["filaments"] == ["PETG"] and blue["slot_colours"] == {1: "#1E88E5"} and not blue["warnings"]
    grey = {"index": 1, "hex": "#C0C0C0", "share": 100.0}
    assert spools.single(grey, trays, coloured=False, active=2)["single"]["pos"] == 1   # the spool in the head
    assert spools.single(grey, trays, coloured=False)["single"]["pos"] == 0
    # the start dialog then sends the file's only tool to that very spool, not to T0
    canvas = {"canvas_info": {"canvas_list": [{"canvas_id": 0, "tray_list": [
        {"tray_id": 1, "filament_color": "#FFFFFF", "filament_type": "PLA", "status": 2},
        {"tray_id": 2, "filament_color": "#F4F4F4", "filament_type": "PLA", "status": 2}]}]}}
    g = tmp_path / "gris.gcode"
    g.write_text("; filament_colour = #F4F4F4\n; filament_type = PLA\nG28\n")
    assert launch.plan(g, canvas)["slot_map"][0]["tray_id"] == 2      # near-white T0 would also have passed


def test_advanced_settings_reach_the_gcode(tmp_path):
    import re
    from elegoo_lab import printprep, settings, slicer
    with pytest.raises(ValueError):
        settings.build({"parois": 40})
    with pytest.raises(ValueError):
        settings.build({"motif": "spaghetti"})
    if not (slicer.TOOLS / "squashfs-root" / "AppRun").exists():
        pytest.skip("slicer non installé")
    src = tmp_path / "cyl.stl"
    trimesh.creation.cylinder(radius=10, height=30, sections=48).export(src)
    r = printprep.prepare_and_slice(src, out_dir=tmp_path / "a", rotate=(90, 0, 0), copies=2,
                                    advanced={"parois": 4, "motif": "gyroide", "temp_buse": 215, "motif_dessus": "concentrique",
                                              "paroi_dessus": "non", "paroi_precise": "oui"})
    g = (tmp_path / "a" / r["gcode"][0]).read_text(errors="ignore")
    val = lambda k: re.search(rf"^; {k} = (.*)$", g, re.M).group(1)
    assert val("curr_bed_type") == "Textured PEI Plate" and re.search(r"^M140 S60", g, re.M)   # PEI plate, 60 °C
    assert val("wall_loops") == "4" and val("sparse_infill_pattern") == "gyroid" and re.search(r"^M10[49] S215", g, re.M)
    assert val("top_surface_pattern") == "concentric" and val("only_one_wall_top") == "0" and val("precise_outer_wall") == "1"
    assert abs(float(re.search(r"^; max_z_height: ([\d.]+)", g, re.M).group(1)) - 20) < 0.5   # lying down: 20 mm tall
    with pytest.raises(ValueError):
        printprep.prepare_and_slice(src, out_dir=tmp_path / "b", copies=50, height_mm=60)       # does not fit


def test_off_dae_slice_and_the_temps_of_the_profile(tmp_path):
    """Formats beyond the usual four slice too (OFF, DAE), and the result shows the profile's temperatures."""
    from elegoo_lab import printprep, slicer
    if not (slicer.TOOLS / "squashfs-root" / "AppRun").exists():
        pytest.skip("slicer non installé")
    box = trimesh.creation.box((20, 20, 20))
    for ext in (".off", ".dae"):
        src = tmp_path / f"boite{ext}"
        box.export(src)
        res = printprep.prepare_and_slice(src, out_dir=tmp_path / ext[1:])
        assert res["gcode"]
    res = printprep.prepare_and_slice(tmp_path / "boite.off", out_dir=tmp_path)
    assert res["temps"]["nozzle"] and res["temps"]["bed"] > 0   # the profile's temperatures, shown in the result


def test_zip_upload_and_broken_step_rejected(web):
    import io
    import zipfile
    client, lib = web
    stl = trimesh.creation.box((10, 10, 10)).export(file_type="stl")
    zz = io.BytesIO()
    with zipfile.ZipFile(zz, "w") as z:
        z.writestr("un.stl", stl)
        z.writestr("deux.stl", stl)
        z.writestr(".cache.txt", b"junk")   # hidden files stay out
    r = client.post("/lab/api/models", files={"file": ("deux_pieces.zip", zz.getvalue())}).json()
    assert len(r["names"]) == 2 and (lib / r["names"][0]).exists()
    bad = client.post("/lab/api/models", files={"file": ("oxe.step", b"pas un STEP")})
    assert bad.status_code == 422 and not (lib / "oxe.step").exists()


@pytest.fixture
def web(tmp_path, monkeypatch, fake_printer_env):
    """The workshop API on a throw-away library (no printer connection: lifespan not started)."""
    from fastapi.testclient import TestClient
    from elegoo_lab import app as app_mod, config
    lib = tmp_path / "models"
    lib.mkdir()
    monkeypatch.setattr(config, "MODELS_DIR", lib)
    monkeypatch.setattr(app_mod, "JOBS_FILE", lib / ".jobs.json")
    monkeypatch.setattr(config, "CONFIG_FILE", tmp_path / "config.toml")
    (lib / ".jobs.json").write_text(json.dumps([{"id": "j1", "state": "running", "workflow": "x", "started": 1}]))
    return TestClient(app_mod.create_app(enable_control=True)), lib


def test_web_refuses_other_sites(web):
    client, lib = web
    stl = trimesh.creation.box((10, 10, 10)).export(file_type="stl")
    evil = client.post("/lab/api/models", files={"file": ("a.stl", stl)}, headers={"Origin": "http://evil.example"})
    assert evil.status_code == 403
    assert client.post("/print/pause", headers={"Sec-Fetch-Site": "cross-site"}).status_code == 403
    ok = client.post("/lab/api/models", files={"file": ("a.stl", stl)}, headers={"Origin": "http://testserver"})
    assert ok.status_code == 200 and ok.json()["name"] == "a.stl"
    again = client.post("/lab/api/models", files={"file": ("a.stl", stl)})          # CLI/scripts: no Origin
    assert again.json()["name"] == "a (2).stl"                                       # no silent overwrite
    assert client.get("/lab/api/models/..%2F..%2Fconfig.toml").status_code == 404     # stays in the library


def test_the_assistant_acts_through_the_workshop_tools(web, monkeypatch):
    """The chatbot, API engine: Mistral is faked, its tool calls run for real (resize → a new model in the library)."""
    from types import SimpleNamespace as NS
    from elegoo_lab import assistant
    client, lib = web
    trimesh.creation.box((20, 20, 20)).export(lib / "cube.stl")
    monkeypatch.setattr(assistant, "moteur", lambda: "api")
    monkeypatch.setattr(assistant, "api_key", lambda: "k-test")
    class Fake:
        status_code = 200
        text = ""
        seq = [
            # round 1: Mistral asks for the facts and resizes; round 2: Mistral answers
            {"choices": [{"message": {"tool_calls": [
                {"id": "c1", "function": {"name": "fiche", "arguments": "{}"}},
                {"id": "c2", "function": {"name": "redimensionner", "arguments": json.dumps({"hauteur": 40})}}]}}]},
            {"choices": [{"message": {"content": "Fait : « cube_h40mm.ply »."}}]}]
        def json(self):
            return Fake.seq.pop(0)
    monkeypatch.setattr(assistant.httpx, "post", lambda url, **kw: Fake())
    r = client.post("/lab/api/models/cube.stl/assistant", json={"message": "mets-le à 40 mm de haut"})
    d = r.json()
    assert r.status_code == 200 and d["outils"] == ["fiche", "redimensionner"]
    assert d["file"] == "cube_h40mm.ply" and (lib / "cube_h40mm.ply").exists()
    assert abs(mesh.info(lib / "cube_h40mm.ply")["size_mm"][2] - 40) < 0.5
    monkeypatch.setattr(assistant, "api_key", lambda: None)
    assert client.post("/lab/api/models/cube.stl/assistant", json={"message": "coucou"}).status_code == 422
    assert client.post("/lab/api/models/absent.stl/assistant", json={"message": "x"}).status_code == 404


def test_the_assistant_runs_on_the_local_cli(web, monkeypatch):
    """The chatbot, CLI engine: a fake headless vibe run thinks and asks the workshop's tools by JSON — no API key."""
    from elegoo_lab import assistant
    client, lib = web
    trimesh.creation.box((20, 20, 20)).export(lib / "cube.stl")
    monkeypatch.setattr(assistant, "moteur", lambda: "cli")
    monkeypatch.setattr(assistant, "cli_bin", lambda: "/tmp/bin/vibe")
    calls: list[list[str]] = []

    def cli_out(obj: dict) -> str:
        return json.dumps([{"sessionId": "S1", "role": "assistant", "type": "message",
                            "content": [{"type": "text", "text": json.dumps(obj, ensure_ascii=False)}]}])

    class Ok:
        returncode = 0
        stderr = ""
        def __init__(self, text): self.stdout = text
    seq = [Ok(cli_out({"outils": [{"outil": "fiche"},
                                  {"outil": "redimensionner", "arguments": {"hauteur": 40}}]})),
           Ok(cli_out({"reponse": "Fait : « cube_h40mm.ply » et exporté."}))]
    fake_system = ""
    def fake_run(cmd, **kw):
        calls.append(cmd)
        nonlocal fake_system
        if "--system-prompt-file" in cmd:
            with open(cmd[cmd.index("--system-prompt-file") + 1]) as fh:
                fake_system = fh.read()
        return seq.pop(0)
    monkeypatch.setattr(assistant.subprocess, "run", fake_run)
    r = client.post("/lab/api/models/cube.stl/assistant", json={"message": "mets-le à 40 mm de haut"})
    d = r.json()
    assert r.status_code == 200 and d["outils"] == ["fiche", "redimensionner"]
    assert d["file"] == "cube_h40mm.ply" and (lib / "cube_h40mm.ply").exists()
    prompt = calls[0][calls[0].index("-p") + 1]
    assert "cube.stl" in prompt and "PROTOCOLE" in fake_system
    assert "--resume" not in calls[0]
    # round 2 resumes the CLI session instead of resending the whole fiche and history
    assert calls[1][calls[1].index("--resume") + 1] == "S1" and "--system-prompt-file" not in calls[1]
    # headless mode: the native tools are off (the workshop does the files itself), MCP (Blender…) stays approved
    off = {t: i for i, t in enumerate(calls[0])}
    assert "bash" in calls[0] and calls[0][off["bash"] - 1] == "--disabled-tools"
    assert "--auto-approve" not in calls[0] and calls[0][off["--approval-policy"] + 1] == "auto-approve"
    # a CLI that goes away gives a clear error, not a crash
    monkeypatch.setattr(assistant, "cli_bin", lambda: None)
    assert client.post("/lab/api/models/cube.stl/assistant", json={"message": "x"}).status_code == 422


def test_the_api_engine_guards(web, monkeypatch):
    """API Mistral: a duplicate tool call is replayed without rerunning (then the answer is forced),
    a later tool of the same round works on the file the first one created, and a silent model gets one nudge."""
    from elegoo_lab import assistant
    client, lib = web
    trimesh.creation.box((20, 20, 20)).export(lib / "cube.stl")
    monkeypatch.setattr(assistant, "moteur", lambda: "api")
    monkeypatch.setattr(assistant, "api_key", lambda: "k-test")
    runs = {"n": 0}
    real_run = assistant.run_tool

    def counted(tool, args, name):
        runs["n"] += 1
        return real_run(tool, args, name)

    monkeypatch.setattr(assistant, "run_tool", counted)

    def msg(**kw):
        return {"choices": [{"message": kw}]}

    # guard 1: the same tool twice in a row on the same file — one run, the replay, then a forced answer
    seq = [msg(tool_calls=[{"id": "c1", "function": {"name": "fiche", "arguments": "{}"}}], content=None),
           msg(tool_calls=[{"id": "c2", "function": {"name": "fiche", "arguments": "{}"}}], content=None),
           msg(content="La fiche est là : cube de 20 mm de côté, étanche, 8 cm3.")]

    class Fake:
        status_code = 200
        text = ""

        def json(self):
            return seq.pop(0)

    choices = []

    def fake_post(url, **kw):
        choices.append(kw["json"]["tool_choice"])
        return Fake()

    monkeypatch.setattr(assistant.httpx, "post", fake_post)
    r = client.post("/lab/api/models/cube.stl/assistant", json={"message": "dis-moi tout du cube"})
    d = r.json()
    assert r.status_code == 200 and d["reply"].startswith("La fiche est là")
    assert d["outils"] == ["fiche"] and runs["n"] == 1     # the duplicate fiche was replayed, not rerun
    assert d["file"] == "cube.stl"
    assert choices == ["auto", "auto", "none"]       # the all-duplicate round forces a plain answer

    # guard 2: a later tool of the same round works on the file the first one created
    seq[:] = [msg(tool_calls=[
                   {"id": "c1", "function": {"name": "redimensionner", "arguments": json.dumps({"hauteur": 40})}},
                   {"id": "c2", "function": {"name": "redimensionner", "arguments": json.dumps({"hauteur": 50})}}],
               content=None),
              msg(content="Voilà le cube à 40 puis 50 mm de haut.")]
    r = client.post("/lab/api/models/cube.stl/assistant", json={"message": "mets-le à 40 puis 50 mm de haut"})
    d = r.json()
    assert d["outils"] == ["redimensionner", "redimensionner"] and runs["n"] == 3
    assert d["file"] == "cube_h40mm_h50mm.ply" and (lib / "cube_h40mm_h50mm.ply").exists()
    assert abs(mesh.info(lib / "cube_h40mm_h50mm.ply")["size_mm"][2] - 50) < 0.5

    # guard 3: a silent model after its tools gets one nudge, then it speaks
    seq[:] = [msg(tool_calls=[{"id": "c1", "function": {"name": "fiche", "arguments": "{}"}}], content=None),
              msg(content="   "),
              msg(content="La pièce fait 20 mm de côté : 40 puis 50 mm de haut.")]

    r = client.post("/lab/api/models/cube_h40mm_h50mm.ply/assistant", json={"message": "sa taille ?"})
    d = r.json()
    assert r.status_code == 200
    assert d["reply"].startswith("La pièce fait 20 mm") and choices[-1] == "none"


def test_the_aI_picks_the_slice_settings(web, monkeypatch):
    """slice-brain: the brain reads the part and decides the slicing settings; only valid choices survive."""
    from elegoo_lab import assistant
    client, lib = web
    trimesh.creation.box((20, 20, 20)).export(lib / "cube.stl")
    monkeypatch.setattr(assistant, "moteur", lambda: "cli")
    monkeypatch.setattr(assistant, "cli_bin", lambda: "/tmp/bin/vibe")

    text = json.dumps({"reponse": {"qualite": "0.16mm Optimal", "remplissage": 25, "supports": "aucun",
                                   "reglages": {"couture": "arriere", "cle_hors_profil": 3, "parois": 99},
                                   "usage": "fonctionnel", "rotate": None,
                                   "explication": "Pièce simple : 0,16 mm et parois épaisses suffisent."}},
                      ensure_ascii=False)

    class Ok:
        returncode = 0
        stderr = ""
        stdout = json.dumps([{"role": "assistant", "type": "message", "content": [{"type": "text", "text": text}]}])

    captured = {}
    def fake_run(cmd, **kw):
        captured["prompt"] = cmd[cmd.index("-p") + 1]
        captured["system"] = open(cmd[cmd.index("--system-prompt-file") + 1]).read()
        return Ok()
    monkeypatch.setattr(assistant.subprocess, "run", fake_run)
    r = client.post("/lab/api/models/cube.stl/slice-brain", json={"quality": "0.20mm Standard", "infill": 15})
    assert r.status_code == 200
    d = r.json()
    assert d["qualite"] == "0.16mm Optimal" and d["remplissage"] == 25 and d["supports"] == "aucun"
    assert d["reglages"] == {"couture": "arriere"}            # unknown key and out-of-range number dropped
    assert d["usage"] == "fonctionnel" and "explication" in d
    assert '"taille_mm"' in captured["prompt"]                # the brain sees the part's sheet
    assert "TRANCHEUR" in captured["system"] and "--resume" not in captured["prompt"]

    # no CLI configured: a clear error, not a crash
    monkeypatch.setattr(assistant, "cli_bin", lambda: None)
    assert client.post("/lab/api/models/cube.stl/slice-brain", json={"quality": "0.20mm Standard"}).status_code == 422


def test_the_assistant_journals_live_events(web, monkeypatch):
    """The streaming route: the brain's activity goes out as server-sent events, and the ordinary result lands in the last one."""
    from elegoo_lab import assistant
    client, lib = web
    trimesh.creation.box((20, 20, 20)).export(lib / "b.stl")
    monkeypatch.setattr(assistant, "moteur", lambda: "cli")
    monkeypatch.setattr(assistant, "cli_bin", lambda: "/tmp/bin/vibe")

    def fake_chat(name, message, history=None, conversation="", emit=None):
        assert emit is not None                              # live mode: events go out through emit
        emit({"type": "outil", "outil": "fiche"})
        emit({"type": "cli", "cible": "mcp_blender.get_scene_info"})
        return {"reply": "Voilà.", "file": name, "outils": ["fiche"]}

    monkeypatch.setattr(assistant, "chat", fake_chat)
    r = client.post("/lab/api/models/b.stl/assistant/stream", json={"message": "décris-la"})
    assert r.status_code == 200 and "text/event-stream" in r.headers["content-type"]
    events = [json.loads(L[6:]) for L in r.text.splitlines() if L.startswith("data: ")]
    assert [e["type"] for e in events] == ["outil", "cli", "final"]
    assert events[0]["outil"] == "fiche" and events[1]["cible"] == "mcp_blender.get_scene_info"
    assert events[-1]["reply"] == "Voilà." and events[-1]["outils"] == ["fiche"]


def test_web_preview_slice_and_jobs(web):
    from elegoo_lab import slicer
    client, lib = web
    trimesh.creation.box((20, 20, 20)).export(lib / "c.stl")
    assert client.get("/lab/api/models/c.stl/colors").json()["colours"]
    glb = client.get("/lab/api/models/c.stl/preview.glb")
    assert glb.status_code == 200 and glb.content[:4] == b"glTF"
    assert client.get("/lab/api/jobs").json()[0]["state"] == "error"                 # interrupted job reported
    assert client.get("/lab/api/setup").json()["tests"]
    if not (slicer.TOOLS / "squashfs-root" / "AppRun").exists():
        pytest.skip("slicer non installé")
    r = client.post("/lab/api/models/c.stl/prepare-print", json={"advanced": {"parois": 3}}).json()
    g = (lib / r["gcode"][0]).read_text(errors="ignore")
    assert "; thumbnail begin 144x144" in g and "; curr_bed_type = Textured PEI Plate" in g and "; wall_loops = 3" in g
    bad = client.post("/lab/api/models/c.stl/prepare-print", json={"advanced": {"parois": 99}})
    assert bad.status_code == 422 and "parois" in bad.json()["detail"].lower()


def test_parametric_parts_are_closed_and_validated(tmp_path, monkeypatch):
    from elegoo_lab import colors, config, mesh, parametric
    monkeypatch.setattr(config, "MODELS_DIR", tmp_path)
    for key in parametric.KINDS:
        p = parametric.create(key, {})
        info = mesh.info(p)
        assert info["watertight"] and info["fits_bed"], key
    label = parametric.create("etiquette", {"texte": "Léa"})
    assert len(colors.analyze(label)["colours"]) == 2                    # plate + text in two colours
    with pytest.raises(ValueError):
        parametric.create("boite", {"longueur": 500})                     # out of range
    with pytest.raises(ValueError):
        parametric.create("organiseur", {"longueur": 30, "cases_x": 12})  # cells too small


def test_phone_access_needs_the_code(web, monkeypatch):
    from fastapi.testclient import TestClient
    from elegoo_lab import access, app as app_mod
    client, lib = web
    code = access.ensure_code()
    assert code and access.ensure_code() is None and "code_hash" in config.CONFIG_FILE.read_text()
    assert code not in config.CONFIG_FILE.read_text()                                  # only the hash is stored
    phone = TestClient(app_mod.create_app(lan=True, port=8787), client=("192.168.1.42", 5000))
    page = phone.get("/lab/", follow_redirects=False)
    assert page.status_code == 303 and page.headers["location"] == "/lab/login.html"
    assert phone.get("/lab/login.html").status_code == 200
    assert phone.get("/lab/api/models").status_code == 401 and phone.post("/print/pause").status_code == 401
    for _ in range(access.MAX_FAILS):
        assert phone.post("/lab/api/login", json={"code": "nope"}).status_code == 403
    assert phone.post("/lab/api/login", json={"code": code}).status_code == 429        # guessing is throttled
    other = TestClient(app_mod.create_app(lan=True, port=8787), client=("192.168.1.43", 5000))
    ok = other.post("/lab/api/login", json={"code": code})
    assert ok.status_code == 200 and "HttpOnly" in ok.headers["set-cookie"] and "SameSite=Strict" in ok.headers["set-cookie"]
    assert other.get("/lab/api/models").status_code == 200                              # session cookie kept
    assert other.get("/lab/api/phone").json()["qr"].lstrip().startswith("<?xml")
    access.set_code("4321")                                                             # new code ends old sessions
    assert other.get("/lab/api/models").status_code == 401
    local = TestClient(app_mod.create_app(lan=True, port=8787), client=("127.0.0.1", 5000))
    assert local.get("/lab/api/models").status_code == 200                              # this PC: no code


async def test_alerts_follow_a_print(tmp_path, monkeypatch):
    from elegoo_lab import alerts
    monkeypatch.setattr(config, "MODELS_DIR", tmp_path)
    monkeypatch.setattr(config, "CONFIG_FILE", tmp_path / "config.toml")

    async def snap():
        return b"\xff\xd8jpeg\xff\xd9"

    w = alerts.Watcher(lambda: None, snap)
    for ps, prog, cc2 in [(0, 0, {}), (13, 0, {}), (13, 40, {}), (6, 40, {"filament_detect_enable": 1, "filament_detected": 0}),
                          (13, 41, {}), (13, 99, {}), (0, 0, {})]:
        w.observe(ps, prog, "chat.gcode", cc2)
    await asyncio.sleep(0.05)                                                           # photo task
    seen = [e["kind"] for e in w.events]
    assert seen == ["debut", "filament", "reprise", "fin"]
    assert w.events[-1].get("photo") and (alerts.photos_dir() / w.events[-1]["photo"]).read_bytes().startswith(b"\xff\xd8")
    w.observe(13, 0, "b.gcode", {}); w.observe(13, 30, "b.gcode", {}); w.observe(8, 30, "b.gcode", {})
    w.observe(13, 0, "c.gcode", {}); w.observe(14, 10, "c.gcode", {"exception_status": [501]})
    assert [e["kind"] for e in w.events[-4:]] == ["debut", "arret", "debut", "erreur"] and "501" in w.events[-1]["detail"]
    assert [e["kind"] for e in alerts.Watcher(lambda: None).events] == [e["kind"] for e in w.events]   # kept on disk



def test_alert_when_the_plate_is_cold(tmp_path, monkeypatch):
    from elegoo_lab import alerts
    monkeypatch.setattr(config, "MODELS_DIR", tmp_path)
    monkeypatch.setattr(config, "CONFIG_FILE", tmp_path / "config.toml")
    w = alerts.Watcher(lambda: None)
    for ps, prog in [(0, 0), (13, 0), (13, 99), (0, 0)]:
        w.observe(ps, prog, "chat.gcode", {})
    assert w.events[-1]["kind"] == "fin" and "35" in w.events[-1]["detail"]
    w.cool(None); w.cool(52.0)
    assert w.events[-1]["kind"] == "fin"                       # still hot, or no reading: wait
    w.cool(33.6)
    assert w.events[-1]["kind"] == "froid" and "34 °C" in w.events[-1]["detail"]
    w.cool(30.0)
    assert sum(e["kind"] == "froid" for e in w.events) == 1    # said once
    w2 = alerts.Watcher(lambda: None)
    w2.events = [e for e in w.events if e["kind"] == "fin"]  # restarted after "fin", before "froid"
    w2.observe(0, 0, "", {}); w2.cool(30.0)
    assert w2.events[-1]["kind"] == "froid"                    # restarted while it cooled: still told
    w.observe(13, 0, "b.gcode", {}); w.observe(8, 30, "b.gcode", {}); w.cool(20.0)
    assert w.events[-1]["kind"] == "arret"                     # a stopped print: no part to take



async def test_camera_feed_gives_whole_pictures():
    from elegoo_lab import camfeed

    class Relay:     # pycentauri's relay: raw byte chunks, cut anywhere
        async def subscribe(self):
            async def chunks():
                data = b"--b\r\n" + b"\xff\xd8one\xff\xd9" + b"\r\n--b\r\n" + b"\xff\xd8two\xff\xd9"
                for i in range(0, len(data), 5):
                    yield data[i:i + 5]
                    await asyncio.sleep(0.01)
                await asyncio.sleep(10)
            return "multipart/x-mixed-replace", chunks()

    f = camfeed.CameraFeed(Relay())
    seq, jpeg = await f.next(0)
    assert jpeg == b"\xff\xd8one\xff\xd9"
    seq2, jpeg2 = await f.next(seq)
    assert (seq2, jpeg2) == (seq + 1, b"\xff\xd8two\xff\xd9")     # the next one, whole
    f.task.cancel()



def test_section_for_the_tablet(tmp_path):
    from elegoo_lab import coupe
    g = ["M83", ";TYPE:Outer wall"]
    for i, z in enumerate((0.2, 0.4, 0.6)):          # three layers of a 10 mm square, the last one in colour 1
        g += [f";Z:{z}", f"G1 Z{z}", "T1" if i == 2 else "T0", "G1 X0 Y0 F3000",
              "G1 X10 Y0 E1", "G1 X10 Y10 E1", "G1 X0 Y10 E1", "G1 X0 Y0 E1"]
    f = tmp_path / "carre.gcode"
    f.write_text("\n".join(g) + "\n; filament_colour = #FF0000;#00FF00\n")
    d = coupe.coupe(f, 2)
    assert d["layer"] == 2 and d["layers"] == [0.2, 0.4, 0.6] and d["box"] == [0, 0, 10, 10]
    assert len(d["section"]) == 16 and d["tools"] == [0, 0, 0, 0]          # layer 2 from above: 4 sides
    assert [r[2] for r in d["front"][2]] == [1] and d["front"][0][0][:2] == [0, 9]   # front: whole width, colour per layer
    assert "front" not in coupe.coupe(f, 3, front=False)



def test_colours_now_and_next(web):
    from types import SimpleNamespace as NS
    from elegoo_lab import suivi_couleurs
    client, lib = web
    g = ["M6211 A1 L200 T0", "M73 P0 R30"]
    for z, tools in ((0.2, []), (0.4, [1, 2]), (0.6, [0])):   # layer 2 holds two changes
        g += [f";Z:{z}", f"M73 P0 R{int(30 - z * 20)}"] + [f"M6211 T{t} L60" for t in tools]
    f = lib / "noel_0.20mm_PLA.gcode"
    f.write_text("\n".join(g) + "\n; filament_colour = #008755;#E9E9E7;#D22630\n")
    p = suivi_couleurs.plan(f, 2, active=1)                      # white engaged: red comes next, in this layer
    assert p["tool"] == 1 and [n["tool"] for n in p["next"]] == [2, 0] and p["left"] == 2 and p["total"] == 3
    assert [n["tool"] for n in suivi_couleurs.plan(f, 2)["next"]] == [0]   # no CANVAS: the layer's changes are done
    # purge still to come per tool, as the firmware counts it (L under 23 mm rounded up, +6 mm): white is done
    assert [(x["tool"], x["left"], x["count"], x["left_m"], x["total_m"]) for x in p["purge"]] == [
        (0, 1, 2, 0.066, 0.272), (1, 0, 1, 0.0, 0.066), (2, 1, 1, 0.066, 0.066)]

    async def status():
        return NS(filename="/local/" + f.name, print_info=NS(current_layer=2))

    async def canvas():
        return NS(raw={"canvas_info": {"active_tray_id": 2, "canvas_list": [{"canvas_id": 0, "tray_list": [
            {"tray_id": i, "status": 1, "filament_color": c, "filament_type": "PLA"}
            for i, c in enumerate(["#077747", "#FFFFFF", "#F72221"])]}]}})
    client.app.state.manager = NS(printer=NS(status=status, canvas_status=canvas))
    from elegoo_lab import stock
    data = stock.load(); data["prints"][f.name] = {"per_m": [1, 1, 1], "route": {"0": 1, "1": 2, "2": 0}}; stock.save(data)
    d = client.get("/lab/api/couleurs").json()
    # tray 2 engaged = tool 1 by the launch route; tool 2 is in tray 0, tool 0 in tray 1
    assert d["maintenant"]["tool"] == 1 and d["maintenant"]["bobine"] == 3 and d["maintenant"]["hex"] == "#F72221"
    assert [(n["tool"], n["bobine"], n["couche"]) for n in d["suivants"]] == [(2, 1, 2), (0, 2, 3)]
    assert [(x["bobine"], x["reste"], x["total"]) for x in d["purge"]] == [(2, 1, 2), (3, 0, 1), (1, 1, 1)]



def test_english_dictionary_and_server_translation():
    import json, re
    from elegoo_lab import i18n
    d = json.loads(i18n.DICT.read_text())
    assert len(d["exact"]) > 1000 and len(d["patterns"]) > 100
    for fr, en in d["patterns"]:
        re.compile("^" + re.escape(fr).replace(r"\{\}", "(.*?)") + "$")                # every pattern is valid
        n = fr.count("{}")
        assert all(1 <= int(k) <= n for k in re.findall(r"\{(\d+)\}", en)), fr      # numbered slots exist
        assert en.count("{}") <= n, fr                                                   # never more values than captured
    assert i18n.tr("Impression terminée", "en") == "Print finished"
    assert i18n.tr("Impression terminée", "fr") == "Impression terminée"
    assert i18n.tr("Consigne Buse", "en") == "Target Nozzle"                            # pieces translated too
    assert i18n.tr("3 fichiers supprimés", "en") == "3 files deleted"
    assert i18n.tr("1 fichier supprimé", "en") == "1 file deleted"                      # empty plural mark
    t = "chat.gcode : terminée en 45 min. Pense à vider le bac de purge."
    assert i18n.tr(t, "en") == "chat.gcode: finished in 45 min. Remember to empty the purge bin."


def test_pwa_and_https_for_the_phone(web, monkeypatch, tmp_path):
    import ssl
    from cryptography import x509
    from fastapi.testclient import TestClient
    from elegoo_lab import access, app as app_mod, certs
    client, lib = web
    monkeypatch.setattr(config, "ROOT", tmp_path)
    code = access.ensure_code()
    crt, key = certs.ensure(["192.168.1.42"])
    assert oct((tmp_path / ".certs" / "ca.key").stat().st_mode)[-3:] == "600"
    san = x509.load_pem_x509_certificate(crt.read_bytes()).extensions.get_extension_for_class(x509.SubjectAlternativeName).value
    assert "192.168.1.42" in {str(a) for a in san.get_values_for_type(x509.IPAddress)}
    ssl.create_default_context(cadata=certs.ca_pem().decode()).load_cert_chain(crt, key)   # chain is coherent
    before = crt.read_bytes()
    assert certs.ensure(["192.168.1.42"]) == (crt, key) and crt.read_bytes() == before          # reused, not reissued
    web_app = app_mod.create_app(lan=True, port=8443, https=True, http_port=8787)
    plain = TestClient(web_app, base_url="http://192.168.1.42:8787", client=("192.168.1.50", 5000))
    r = plain.get("/lab/", follow_redirects=False)
    assert r.status_code == 307 and r.headers["location"] == "https://192.168.1.42:8443/lab/"   # HTTP: only a signpost
    ca = plain.get("/lab/ca.crt")
    assert ca.status_code == 200 and b"BEGIN CERTIFICATE" in ca.content and b"PRIVATE" not in ca.content
    phone = TestClient(web_app, base_url="https://192.168.1.42:8443", client=("192.168.1.50", 5000))
    for path in ("/lab/manifest.webmanifest", "/lab/sw.js", "/lab/offline.html", "/lab/icons/icon-192.png"):
        assert phone.get(path).status_code == 200, path                                 # installable before login
    assert phone.get("/lab/manifest.webmanifest").json()["display"] == "standalone"
    ok = phone.post("/lab/api/login", json={"code": code})
    assert "Secure" in ok.headers["set-cookie"]
    info = TestClient(web_app, client=("127.0.0.1", 5000)).get("/lab/api/phone").json()
    assert info["url"].startswith("https://") and info["ca_url"].endswith(":8787/lab/ca.crt")


def test_advisor_spots_what_ruins_prints(tmp_path):
    from elegoo_lab import advisor
    def save(m, name):
        m.export(tmp_path / name)
        return tmp_path / name
    keys = lambda p, **kw: {w["key"] for w in advisor.analyze(p, **kw)["warnings"]}
    assert keys(save(trimesh.creation.box((20, 20, 20)), "cube.stl")) == set()
    base = trimesh.creation.box((30, 30, 3)); base.apply_translation((0, 0, 1.5))
    fin = trimesh.creation.box((30, 0.5, 20)); fin.apply_translation((0, 0, 13))
    assert "fin" in keys(save(trimesh.util.concatenate([base, fin]), "ailette.stl"))
    stem = trimesh.creation.box((10, 10, 20)); stem.apply_translation((0, 0, 10))
    top = trimesh.creation.box((40, 40, 4)); top.apply_translation((0, 0, 22))
    tee = save(trimesh.util.concatenate([stem, top]), "champignon.stl")
    assert "surplombs" in keys(tee) and "surplombs" not in keys(tee, supports=True)
    w = next(w for w in advisor.analyze(tee)["warnings"] if w["key"] == "surplombs")
    assert w["fix"] == {"supports": "arbre"}
    ball = save(trimesh.creation.icosphere(subdivisions=3, radius=15), "boule.stl")
    assert "adherence" in keys(ball) and "adherence" not in keys(ball, brim=True)


def test_spool_stock_and_costs(tmp_path, monkeypatch):
    from elegoo_lab import alerts, stock
    monkeypatch.setattr(config, "MODELS_DIR", tmp_path)
    monkeypatch.setattr(config, "CONFIG_FILE", tmp_path / "config.toml")
    assert abs(stock.grams(1.0) - 2.98) < 0.02                                       # 1 m of 1.75 mm PLA ≈ 3 g
    trays = [{"tray_id": i, "color": c, "type": "PLA", "code": f"R{i}", "filament_name": f"PLA {i}"}
             for i, c in enumerate(["#E53935", "#FFFFFF"])]
    assert stock.sync(trays) == []                                                   # first sight: no alert
    stock.set_tray(1, restant_g=150, prix_kg=25)
    u = stock.record_slice("chat.gcode", [10.0, 30.0], [0.5, 0.5])
    assert u["trays"][1]["manque"] is False and abs(u["eur"] - (u["trays"][0]["eur"] + u["trays"][1]["eur"])) < 0.02
    stock.record_slice("gros.gcode", [0.0, 80.0])
    assert stock.check("gros.gcode")["manques"][0]["tray"] == 1                       # 238 g needed, 150 g left
    w = alerts.Watcher(lambda: None)
    for ps, prog in [(0, 0), (13, 0), (13, 99), (0, 0)]:
        w.observe(ps, prog, "/local/chat.gcode", {})
    s = stock.summary()
    assert s["trays"][1]["restant_g"] < 60 and s["history"][0]["fichier"] == "chat.gcode"
    assert any(e["kind"] == "stock" and "Bobine 2" in e["detail"] for e in w.events)       # nearly empty warning
    before = s["trays"][0]["restant_g"]
    assert stock.consume("chat.gcode", 1.0, s["history"][0]["ref"]) == []            # counted once only
    assert stock.summary()["trays"][0]["restant_g"] == before
    left = stock.summary()["trays"][1]["restant_g"]
    trays[1]["code"] = "R9"                                                          # another spool in tray 1
    assert [(t["tray"], t["remise"]) for t in stock.sync(trays)] == [(1, False)]
    assert stock.summary()["trays"][1]["restant_g"] == 1000
    assert stock.summary()["trays"][1]["question"]["remise"] is False                # "new, or already started?"
    trays[1]["code"] = "R1"                                                          # the first one comes back
    assert [(t["tray"], t["remise"], t["restant_g"]) for t in stock.sync(trays)] == [(1, True, round(left))]
    assert stock.summary()["trays"][1]["restant_g"] == left
    assert stock.summary()["trays"][1]["question"]["remise"] is True                 # "the same one, or a new one?"
    stock.set_tray(1, nouvelle=True)                                                 # the user says: a new one
    t1 = stock.summary()["trays"][1]
    assert t1["restant_g"] == t1["poids_g"] and "question" not in t1
    stock.set_tray(1, restant_g=left)
    stock.set_tray(0, restant_g=300)
    trays[0]["color"], trays[1]["color"] = trays[1]["color"], trays[0]["color"]   # two spools swap trays
    trays[0]["code"], trays[1]["code"] = "R1", "R0"
    assert {t["tray"]: t["restant_g"] for t in stock.sync(trays)} == {0: round(left), 1: 300}
    assert stock.sync(trays[:1]) == []                                               # tray 1 emptied...
    trays[1]["pos"] = 2
    assert [(t["tray"], t["remise"]) for t in stock.sync([trays[0], {**trays[1], "tray_id": 2}])] == [(2, True)]
    assert stock.summary()["trays"][2]["restant_g"] == 300                          # ...its spool found again in tray 3
    with pytest.raises(ValueError):
        stock.set_tray(0, restant_g=5000)


async def test_ai_watch_pauses_a_failed_print_and_gallery_keeps_it(tmp_path, monkeypatch):
    import io
    import shutil
    from PIL import Image
    from elegoo_lab import alerts, gallery, vision
    monkeypatch.setattr(config, "MODELS_DIR", tmp_path)
    monkeypatch.setattr(config, "CONFIG_FILE", tmp_path / "config.toml")
    config.save("surveillance", ia=True, pause_auto=True, sensibilite=1.0, timelapse=True)
    monkeypatch.setattr(alerts, "AI_EVERY_S", 0)
    monkeypatch.setattr(vision, "model_ready", lambda: True)
    failing = {"on": False}
    monkeypatch.setattr(vision, "detect", lambda jpeg: [(0.9, (0.2, 0.2, 0.6, 0.6))] * 3 if failing["on"] else [])

    def frame(i):
        buf = io.BytesIO()
        Image.new("RGB", (64, 48), (i * 3 % 255, 80, 90)).save(buf, format="JPEG")
        return buf.getvalue()
    n = {"i": 0}

    async def snap():
        n["i"] += 1
        return frame(n["i"])
    paused = []

    async def pause():
        paused.append(True)
    w = alerts.Watcher(lambda: None, snap, pause=pause)
    w.observe(0, 0, "", {})
    w.observe(13, 0, "dragon.gcode", {})
    assert w.rec is not None
    for layer in range(1, 41):                       # 40 healthy layers: nothing to say
        w.observe(13, layer * 2, "dragon.gcode", {})
        await w._camera(layer)
    assert not paused and not [e for e in w.events if e["kind"] in ("suspect", "rate")]
    failing["on"] = True                             # spaghetti appears
    for layer in range(41, 60):
        await w._camera(layer)
        if paused:
            break
    assert paused and w.events[-1]["kind"] == "rate" and (alerts.photos_dir() / w.events[-1]["photo"]).exists()
    assert w.rec.meta["alertes"] and w.rec.frames >= 40
    w.observe(6, 90, "dragon.gcode", {})
    w.observe(13, 90, "dragon.gcode", {})            # the user resumed: judged afresh
    assert not w.ai_paused and w.pred.frames == 0
    w.observe(0, 0, "", {})                          # stopped before the end
    await asyncio.sleep(0.5)
    for _ in range(50):
        if gallery.entries() and gallery.entries()[0]["issue"] != "en cours":
            break
        await asyncio.sleep(0.2)
    e = gallery.entries()[0]
    assert e["issue"] == "arretee" and e["photo"] and e["alertes"]
    if shutil.which("ffmpeg"):
        assert e["video"] == "timelapse.mp4" and gallery.file(e["id"], "timelapse.mp4").stat().st_size > 1000
    assert not (gallery.root() / e["id"] / "frames").exists()
    with pytest.raises(FileNotFoundError):
        gallery.file(e["id"], "../meta.json")


def test_failure_model_on_simulator_frame():
    from elegoo_lab import vision
    if not vision.model_ready():
        pytest.skip("modèle IA non installé")
    s = sim.Sim()
    s.s.update(status=sim.PRINTING, progress=50)
    assert sum(c for c, _ in vision.detect(s.camera_frame())) < 0.3     # a clean print looks clean


def test_web_forms_reach_the_server(web):
    client, lib = web
    r = client.post("/lab/api/bobines/1", json={"restant_g": 420, "prix_kg": 24.5})
    assert r.status_code == 200 and r.json()["restant_g"] == 420 and r.json()["prix_kg"] == 24.5
    assert client.post("/lab/api/bobines/1", json={"restant_g": 99999}).status_code == 422
    r = client.post("/lab/api/surveillance", json={"pause_auto": True, "sensibilite": 1.5})
    assert r.status_code == 200 and r.json()["pause_auto"] is True and r.json()["sensibilite"] == 1.5
    assert client.post("/lab/api/surveillance", json={"sensibilite": 9}).status_code == 422
    r = client.post("/lab/api/lancement", json={"bedlevel_force": True, "print_layout": "B"})
    assert r.status_code == 200 and r.json() == {**r.json(), "bedlevel_force": True, "print_layout": "B"}
    assert client.post("/lab/api/lancement", json={"print_layout": "Z"}).status_code == 422
    assert client.get("/lab/api/lancement").json()["print_layout"] == "B"


async def test_start_sends_the_spool_map(printer, tmp_path, monkeypatch):
    from elegoo_lab import launch
    monkeypatch.setattr(config, "CONFIG_FILE", tmp_path / "config.toml")
    g = tmp_path / "deux.gcode"
    g.write_text("; HEADER_BLOCK_START\n; filament used [mm] = 1200.00, 0.00, 340.50\n; HEADER_BLOCK_END\nG1 X1\n"
                 "; filament_colour = #008755;#E9E9E7;#F2A900\n; filament_type = PLA;PLA;PETG\n")
    tools = launch.gcode_colours(g)
    assert [t["t"] for t in tools] == [0, 2] and tools[1]["type"] == "PETG"          # unused colour left out
    canvas = (await printer.canvas_status()).raw
    plan = launch.plan(g, canvas)
    # green file colour is on the CANVAS's green spool, gold on the gold one, whatever their positions
    by_t = {m["t"]: m["tray_id"] for m in plan["slot_map"]}
    trays = {t["tray_id"]: t["colour"] for t in plan["trays"]}
    assert trays[by_t[0]] == "#008755" and trays[by_t[2]] == "#F2A900"
    payload = launch.params(g.name, {"bedlevel_force": True}, plan["slot_map"])
    assert payload["config"]["bedlevel_force"] is True and payload["config"]["slot_map"][0]["canvas_id"] == 0
    assert (await printer._cc2_request(1020, payload))["error_code"] == 0
    await printer.stop()
    await asyncio.sleep(0.3)
    bad = launch.params(g.name, {}, [{"t": 0, "tray_id": 7}])
    from pycentauri.client import PrinterError
    with pytest.raises(PrinterError, match="error_code"):                           # refused: no such spool
        await printer._cc2_request(1020, bad)


def test_printer_name_stays_ascii():
    """The printer's upload carries the file name in an HTTP header: ASCII only (a Chinese name
    crashed the send). ASCII names keep theirs so files on the printer stay reachable."""
    from elegoo_lab import launch
    assert launch.printer_name("cube_0.20mm_PLA.gcode") == "cube_0.20mm_PLA.gcode"
    cine = launch.printer_name("洋葱头宝宝_canvas_0.20mm_PLA.gcode")
    assert cine.isascii() and cine.endswith(".gcode") and len(cine) < 40
    assert launch.printer_name(cine) == cine                                # deterministic: upload and start agree
    assert launch.printer_name("洋葱头宝宝.3mf.json") != launch.printer_name("洋葱头宝宝.gcode")
    # the whole round trip: upload under the translated name, then start names the same file
    payload = launch.params(launch.printer_name("洋葱头宝宝.gcode"), {}, [])
    assert payload["filename"] == launch.printer_name("洋葱头宝宝.gcode")
    assert payload["filename"].isascii()


def test_usage_puts_plastic_where_it_matters(tmp_path):
    from elegoo_lab import printprep, slicer, stock
    assert printprep.usage_overrides("decoratif", None)["sparse_infill_pattern"] == "lightning"
    assert "sparse_infill_density" not in printprep.usage_overrides("decoratif", 30)   # the user's infill wins
    with pytest.raises(ValueError):
        printprep.usage_overrides("n'importe", None)
    assert printprep.suggest_usage(Path("boite_80x60.3mf")) == "fonctionnel"
    assert printprep.suggest_usage(Path("dragon.glb")) == "decoratif"
    if not (slicer.TOOLS / "squashfs-root" / "AppRun").exists():
        pytest.skip("slicer non installé")
    src = tmp_path / "bloc.stl"
    trimesh.creation.box((40, 40, 30)).export(src)
    grams = {}
    for u in ("decoratif", "fonctionnel"):
        r = printprep.prepare_and_slice(src, usage=u, out_dir=tmp_path / u, quality=printprep.USAGES[u]["quality"])
        grams[u] = sum(stock.grams(m) for m in r["per_filament_m"])
        g = (tmp_path / u / r["gcode"][0]).read_text(errors="ignore")
        assert f"; sparse_infill_pattern = {printprep.USAGES[u]['overrides']['sparse_infill_pattern']}" in g
        assert '; filament_settings_id = "Elegoo PLA @ECC2"' in g      # names the CC2 knows, or it refuses
        assert "; enable_filament_ramming = 0" in g                     # ramming on -> error 1243
    assert grams["decoratif"] < 0.75 * grams["fonctionnel"]
    rows = printprep.compare(src, {"usage": "decoratif"})
    assert rows[0]["current"] and {r["label"] for r in rows} >= {"Ton choix", "Rapide", "Solide", "Détaillé"}
    assert all("error" not in r and r["g"] > 0 for r in rows)


def test_cc2_knowledge_errors_materials_maintenance(tmp_path, monkeypatch):
    import time
    from elegoo_lab import alerts, errors, gallery, launch, maintenance
    monkeypatch.setattr(config, "MODELS_DIR", tmp_path)
    monkeypatch.setattr(config, "CONFIG_FILE", tmp_path / "config.toml")
    assert "capot" in errors.sentence([707]) and "code 707" in errors.sentence([707, 1231])   # cover fan detached, not "purge missed"
    assert "écran" in errors.sentence([4242])                                   # unknown code: look at the screen
    w = alerts.Watcher(lambda: None)
    w.observe(0, 0, "", {}); w.observe(13, 0, "a.gcode", {})
    w.observe(13, 10, "a.gcode", {"exception_status": [707]})
    w.observe(13, 11, "a.gcode", {"exception_status": [707]})                 # reported once
    assert [e["kind"] for e in w.events].count("anomalie") == 1
    w.observe(6, 12, "a.gcode", {"exception_status": [707, 1242]})
    assert w.events[-1]["kind"] == "filament" and "1242" in w.events[-1]["detail"]
    for _ in range(10):                                                         # the same picture over and over
        w._camera_health(b"same")
    w._camera_health(b"same")
    assert w.events[-1]["kind"] == "camera"
    warn = " ".join(launch.material_warnings([{"t": 0, "type": "TPU"}, {"t": 1, "type": "PLA-CF"}], []))
    assert "TPU" in warn and "abrasif" in warn
    assert launch.material_warnings([{"t": 0, "type": "PLA"}], [{"type": "PLA", "filament_name": "PLA Rouge"}]) == []
    st = {t["id"]: t for t in maintenance.status()}
    assert not any(t["a_faire"] for t in st.values())
    rec = gallery.Recorder("long.gcode")                                        # 40 h of printing since then
    rec.meta["debut"] = st["plateau"]["fait"]
    rec.finish("terminee")
    meta = gallery.entries()[0]
    gallery.update(meta["id"], duree_s=40 * 3600)
    due = {t["id"] for t in maintenance.newly_due()}
    assert due == {"plateau"} and maintenance.newly_due() == []                 # announced once
    time.sleep(1.1)
    assert not {t["id"]: t for t in maintenance.done("plateau")}["plateau"]["a_faire"]


def test_canvas_trays_in_both_formats():
    from elegoo_lab import spools
    sdk = {"canvas_info": {"canvas_list": [{"canvas_id": 0, "tray_list": [
        {"tray_id": 1, "filament_type": "PETG", "filament_color": "#ff0000", "filament_code": "0x01", "status": 2},
        {"tray_id": 0, "filament_type": "", "filament_color": "", "status": 0},                       # empty holder
        {"tray_id": 3, "filament_type": "PLA", "filament_color": "#00FF00", "status": 1},
        {"tray_id": 4, "filament_type": "PLA", "filament_color": "javascript:alert(1)", "status": 2}]}]}}  # refused
    got = spools.loaded(sdk)
    assert [(t["pos"], t["tray_id"], t["type"], t["color"]) for t in got] == [(0, 1, "PETG", "#FF0000"), (2, 3, "PLA", "#00FF00")]
    old = {"canvas_list": [{"tray_list": [{"tray_id": 0, "type": "PLA", "color": "#123456", "status": 1}]}]}
    assert spools.loaded(old)[0]["pos"] == 0 and spools.loaded(old)[0]["color"] == "#123456"


def test_orientations_advise_the_obvious(tmp_path):
    from elegoo_lab import orient
    # a sign: a wide plate with a thin mast on top, modelled lying on its back
    plate = trimesh.creation.box((60, 40, 3)); plate.apply_translation((0, 0, 1.5))
    mast = trimesh.creation.box((4, 4, 50)); mast.apply_translation((0, 0, 28))
    trimesh.util.concatenate([plate, mast]).export(tmp_path / "panneau.stl")
    out = {o["id"]: o for o in orient.orientations(tmp_path / "panneau.stl")}
    assert len(out) == 6 and all(o["image"].startswith("data:image/png;base64,") for o in out.values())
    assert out["debout"]["recommandee"]                       # plate down, mast up: no support, big footing
    assert out["envers"]["contact"] < 30                      # upside down it stands on the mast tip
    assert out["avant"]["surplomb"] > out["debout"]["surplomb"]
    assert out["gauche"]["size_mm"][2] == pytest.approx(60, abs=0.5)   # on its side: the plate's width is the height


def test_library_knows_each_file(tmp_path, monkeypatch):
    import base64
    import io
    from PIL import Image
    from elegoo_lab import library, stock, thumbnail
    monkeypatch.setattr(config, "MODELS_DIR", tmp_path)
    trimesh.creation.box((20, 20, 20)).export(tmp_path / "chat.stl")
    (tmp_path / "chat_canvas.3mf").write_bytes(b"x")                      # a technical by-product
    buf = io.BytesIO(); Image.new("RGB", (8, 8), (200, 30, 30)).save(buf, format="PNG")
    b64 = base64.b64encode(buf.getvalue()).decode()
    g = tmp_path / "chat_0.20mm_PLA.gcode"
    g.write_text("; HEADER_BLOCK_START\n; estimated printing time (normal mode) = 1h 2m 3s\n; HEADER_BLOCK_END\n"
                 f"; thumbnail begin 8x8 {len(b64)}\n; {b64}\n; thumbnail end\nG1 X1\n"
                 "; filament_colour = #E53935;#FFFFFF\n; filament used [mm] = 100.0, 0.0\n; total filament used [g] = 3.2\n"
                 "; print_settings_id = cc2lab 0.20mm Standard\n")
    (tmp_path / "orphelin_0.20mm_PLA.gcode").write_text("G1 X1\n")
    library.record("orphelin_0.20mm_PLA.gcode", source="parti.stl")
    by = {e["name"]: e for e in library.listing()}
    assert by["chat_canvas.3mf"]["kind"] == "technique" and by["chat.stl"]["prets"] == 1
    c = by["chat_0.20mm_PLA.gcode"]
    assert c["source"] == "chat.stl" and c["temps"] == "1h 2m 3s" and c["g"] == 3.2
    assert c["couleurs"] == ["#E53935"] and c["qualite"] == "0.20mm Standard"   # unused colour left out
    assert library.thumbnail("chat_0.20mm_PLA.gcode") == buf.getvalue()          # the embedded picture
    assert library.thumbnail("chat.stl")[:4] == b"\x89PNG"                        # a model gets a render
    stock.record_slice("chat_0.20mm_PLA.gcode", [1.0])
    new = library.rename("chat_0.20mm_PLA.gcode", "chat rouge")
    assert new == "chat rouge.gcode" and "chat rouge.gcode" in stock.load()["prints"]
    assert library.rename("chat.stl", "minou") == "minou.stl"
    assert {e["name"]: e for e in library.listing()}["chat rouge.gcode"]["source"] == "minou.stl"   # link kept
    with pytest.raises(ValueError):
        library.rename("minou.stl", "../evil")
    trimesh.creation.box((5, 5, 5)).export(tmp_path / "autre.stl")
    with pytest.raises(ValueError, match="existe déjà"):
        library.rename("minou.stl", "autre")                                      # no silent overwrite
    clean = {c["name"]: c["raison"] for c in library.cleanup()}
    assert "chat_canvas.3mf" in clean and "orphelin_0.20mm_PLA.gcode" in clean and "minou.stl" not in clean
    assert library.delete(list(clean)) == sorted(clean, key=list(clean).index)
    assert not (tmp_path / "chat_canvas.3mf").exists() and (tmp_path / "minou.stl").exists()
    assert library.rename("minou.stl", "chaton.obj") == "chaton.obj.stl"         # the extension stays


def test_error_codes_follow_elegoos_own_list():
    from elegoo_lab import errors
    official = {101, 102, 103, 104, 108, 304, 401, 701, 702, 703, 704, 705, 706, 707, 801, 802, 803, 902, 1101, 1103,
                1210, 1211, 1220, 1231, 1232, 1241, 1242, 1243, 1251, 1252, 1260, 1262, 1263, 1264}
    assert set(errors.CODES) == official                      # exception_handler.h, ErrorCode namespace
    assert "grille" in errors.sentence([1101]) and "grille" in errors.sentence([1103])   # exhaust grille, not a filter
    assert "Plus de filament" in errors.sentence([1211])
    for code in (605, 109, 1102, 1265):                       # codes an earlier guide listed, absent from the firmware
        assert "écran" in errors.sentence([code])


def test_purge_counted_like_the_firmware():
    from elegoo_lab import slicer
    g = (b"M6211 A1 L200 T0 Q210 R210 S210\nM6211 T0 L0 M523\nG1 X1\n"
         b"M6211 T1 L12.5 M523\nM6211 T0 L40 M523\nM6211 T7 L40\nM6211 T1 L23\n")
    out = slicer.firmware_purge_m(g, 2)
    # T0: 200+6 at the start, 40+6 later; the L0 line does nothing.  T1: 12.5 asked but 23 is the floor (+6), then 23+6.
    assert out == pytest.approx([(206 + 46) / 1000, (29 + 29) / 1000])


def test_several_copies_can_be_dropped_one_by_one(tmp_path):
    from elegoo_lab import printprep, slicer
    if not (slicer.TOOLS / "squashfs-root" / "AppRun").exists():
        pytest.skip("slicer non installé")
    import re
    src = tmp_path / "bloc.stl"
    trimesh.creation.box((20, 20, 10)).export(src)
    texts = {}
    for n in (1, 3):
        r = printprep.prepare_and_slice(src, copies=n, out_dir=tmp_path / str(n))
        texts[n] = (tmp_path / str(n) / r["gcode"][0]).read_text(errors="ignore")
    assert len(re.findall(r"^EXCLUDE_OBJECT_DEFINE NAME=", texts[3], re.M)) == 3
    assert "EXCLUDE_OBJECT" not in texts[1]                    # one part: the profile as Elegoo ships it


def test_repair_closes_an_open_coloured_mesh_and_keeps_the_original(tmp_path, monkeypatch):
    import numpy as np

    from elegoo_lab import advisor, repair
    monkeypatch.setattr(config, "MODELS_DIR", tmp_path)
    box = trimesh.creation.box(extents=(20, 20, 20))
    box.visual = trimesh.visual.ColorVisuals(box, vertex_colors=np.tile([200, 30, 30, 255], (len(box.vertices), 1)))
    bad = trimesh.Trimesh(box.vertices, np.vstack([box.faces[:-2], box.faces[:1]]), process=False)   # 2 faces gone + 1 duplicated
    bad.visual = box.visual
    src = tmp_path / "boite.glb"
    bad.export(src)
    assert {w["key"] for w in advisor.analyze(src, height_mm=20)["warnings"]} >= {"ouvert"}
    fix = next(w for w in advisor.analyze(src, height_mm=20)["warnings"] if w["key"] == "ouvert")["fix"]
    assert fix == {"repair": True}
    before = src.read_bytes()
    d = repair.diagnose(src)                                       # where it is open, before repairing
    assert d["holes"] == 1 and d["open_edges"] > 0 and len(d["open"]) == d["open_edges"] * 6
    r = repair.repair(src)
    assert r["closed"] and r["name"] == "boite_repare.glb" and r["coloured"] and r["holes_closed"] == 1
    note = advisor.analyze(tmp_path / r["name"], height_mm=20)["notes"][0]   # the copy says what was done
    assert note["from"] == "boite.glb" and "1 trou rebouché" in note["items"]
    assert advisor.analyze(src, height_mm=20)["notes"] == []
    assert src.read_bytes() == before                              # the original is untouched
    assert mesh.info(tmp_path / r["name"])["watertight"]
    assert repair.repair(src)["name"] == "boite_repare2.glb"       # never overwrites a copy


def test_repair_refuses_to_destroy_a_hopeless_mesh(tmp_path):
    import numpy as np

    from elegoo_lab import repair
    rng = np.random.default_rng(0)
    soup = trimesh.Trimesh(rng.random((3000, 3)) * 20, rng.integers(0, 3000, (1500, 3)), process=False)
    src = tmp_path / "soupe.glb"
    soup.export(src)
    with pytest.raises(ValueError):
        repair.repair(src, tmp_path / "out.glb")


def test_hand_retouch_repaints_faces_beside_the_model(tmp_path, monkeypatch):
    import numpy as np

    from elegoo_lab import colors, library
    monkeypatch.setattr(config, "MODELS_DIR", tmp_path)
    box = trimesh.creation.box(extents=(20, 20, 20))
    box.unmerge_vertices()                                                   # crisp colours: no vertex shared between faces
    box.visual = trimesh.visual.ColorVisuals(box, face_colors=np.array([[200, 0, 0, 255]] * 10 + [[0, 120, 0, 255]] * 2, np.uint8))
    src = tmp_path / "boite.glb"
    box.export(src)
    before = src.read_bytes()
    assert len(colors.analyze(src)["colours"]) == 2
    n_red = int(colors.analyze(src)["colours"][0]["share"] > 50)
    green = next(c["hex"] for c in colors.analyze(src)["colours"] if c["hex"].upper().startswith("#00"))
    assert colors.save_retouch(src, {green: list(range(10))}) == 10          # every red face turns green
    assert len(colors.analyze(src)["colours"]) == 1                          # caches saw the change
    assert src.read_bytes() == before                                        # the model itself is untouched
    assert colors.retouch_file(src).is_file() and n_red in (0, 1)
    pv = colors.preview_glb(src)                                             # triangle i of the preview is face i
    assert len(pv.faces) == 12 and len(pv.vertices) == 36
    with pytest.raises(ValueError):
        colors.save_retouch(src, {green: [999]})
    with pytest.raises(ValueError):
        colors.save_retouch(src, {"rouge": [1]})
    new = library.rename("boite.glb", "cadeau.glb")                          # the retouch follows its model
    assert colors.retouch_file(tmp_path / new).is_file() and not colors.retouch_file(src).exists()
    assert len(colors.analyze(tmp_path / new)["colours"]) == 1
    colors.save_retouch(tmp_path / new, {}, erase=list(range(10)))           # erasing brings the colours back
    assert len(colors.analyze(tmp_path / new)["colours"]) == 2
    colors.save_retouch(tmp_path / new, {green: [0]})
    library.delete([new])
    assert not colors.retouch_file(tmp_path / new).exists()


def test_hand_retouch_repaints_a_painted_3mf_and_a_plain_stl(tmp_path, monkeypatch):
    import numpy as np

    from elegoo_lab import colors, threemf
    monkeypatch.setattr(config, "MODELS_DIR", tmp_path)
    # a CANVAS-like 3MF: every other face red (state 1) or green (state 2), like the onion project
    box = trimesh.creation.box((20, 20, 20)).subdivide()
    box.apply_translation((50, 50, 10))
    faces = len(box.faces)
    p = threemf.Part("oignon", np.asarray(box.vertices, float), np.asarray(box.faces), 1,
                     [colors.encode_state(1 + i % 2) for i in range(faces)])
    src = tmp_path / "oignon.3mf"
    threemf.write(threemf.Project([threemf.Object("oignon", [p])], ["#FF0000", "#00AA00"]),
                  src, filaments=2, colours=["#FF0000", "#00AA00"])
    a = colors.analyze(src)
    assert sorted(c["hex"] for c in a["colours"]) == ["#00AA00", "#FF0000"]
    before = np.asarray(colors.preview(src).visual.face_colors[1][:3])
    assert (before == [0, 170, 0]).all()                       # face 1 starts green
    colors.save_retouch(src, {"#FF0000": [1]})                 # it turns red by hand
    pv = colors.preview(src)                                   # the preview follows the retouch
    assert (pv.visual.face_colors[1][:3] == [255, 0, 0]).all()
    out = tmp_path / "oignon_canvas.3mf"                       # the retouch goes along to the CANVAS
    colors.to_canvas(src, out, {c["index"]: c["slot"] for c in a["colours"]})
    pr2 = threemf.read(out)
    assert colors.paint_states(pr2.objects[0].parts[0].paint[1]) == {1}
    colors.save_retouch(src, {}, clear=True)
    pr3 = threemf.read(colors.to_canvas(src, out, {c["index"]: c["slot"] for c in a["colours"]}) and out)
    assert colors.paint_states(pr3.objects[0].parts[0].paint[1]) == {2}
    # a colourless STL gains colour families of its own (grey + the painted ones)
    stl = tmp_path / "plaine.stl"
    trimesh.creation.box((20, 20, 20)).subdivide().export(stl)
    colors.save_retouch(stl, {"#0000FF": list(range(5))})
    a = colors.analyze(stl)
    assert {c["hex"] for c in a["colours"]} == {"#C0C0C0", "#0000FF"}


def test_hand_retouch_keeps_a_colour_the_filaments_do_not_have(tmp_path, monkeypatch):
    """White painted by hand on an all-yellow 3MF stays white instead of riding the only (yellow)
    filament and vanishing (洋葱头宝宝): the project turns into face colours."""
    import numpy as np

    from elegoo_lab import colors, threemf
    monkeypatch.setattr(config, "MODELS_DIR", tmp_path)
    box = trimesh.creation.box((20, 20, 20)).subdivide()
    p = threemf.Part("jaune", np.asarray(box.vertices, float), np.asarray(box.faces), 1)
    src = tmp_path / "jaune.3mf"
    threemf.write(threemf.Project([threemf.Object("jaune", [p])], ["#FCE300"]), src,
                  filaments=1, colours=["#FCE300"])
    colors.save_retouch(src, {"#E9E9E7": list(range(10, 30))})
    a = colors.analyze(src)
    assert "#E9E9E7" in {c["hex"] for c in a["colours"]}
    pv = np.asarray(colors.preview(src).visual.face_colors)
    assert (pv[10][:3] == [233, 233, 231]).all()       # the painted faces stay white
    assert (pv[0][:3] == [252, 227, 0]).all()          # the rest keeps its yellow


def test_rebuild_drops_a_flat_sheet_and_closes_a_broken_mesh(tmp_path, monkeypatch):
    import numpy as np

    from elegoo_lab import advisor, repair
    monkeypatch.setattr(config, "MODELS_DIR", tmp_path)
    body = trimesh.creation.icosphere(subdivisions=4, radius=10)
    body.apply_translation([0, 0, 10])
    keep = np.random.default_rng(1).random(len(body.faces)) > 0.08          # 8 % of the faces missing
    sheet = trimesh.creation.box((60, 60, 0.01))                              # the flat plate an AI leaves below
    sheet = trimesh.Trimesh(sheet.vertices, sheet.faces[sheet.face_normals[:, 2] > 0.5], process=False)
    sheet = sheet.subdivide().subdivide().subdivide()
    broken = trimesh.util.concatenate([trimesh.Trimesh(body.vertices, body.faces[keep], process=False), sheet])
    src = tmp_path / "abime.stl"
    broken.export(src)
    r = repair.repair(src)
    assert r["rebuilt"] and r["closed"] and r["sheets_removed"]
    out = trimesh.load(tmp_path / r["name"], force="mesh")
    assert out.is_watertight and out.extents.max() < 25                      # the 60 mm plate is gone
    assert abs(out.volume - body.volume) / body.volume < 0.15                 # the ball is whole again
    note = advisor.analyze(tmp_path / r["name"])["notes"][0]
    assert note["title"] == "Maillage reconstruit" and any("Feuilles" in i for i in note["items"])


def test_own_spools_are_recognised_and_sliced(tmp_path, monkeypatch):

    from elegoo_lab import catalog, slicer, spools
    own = tmp_path / ".mes_bobines.json"
    own.write_text(json.dumps({
        "profils": {"PLA Silk Noël": {"base": "PLA Silk", "reglages": {"filament_max_volumetric_speed": "12"}}},
        "bobines": [{"nom": "Silk Rouge Noël", "couleur": "#D22630", "matiere": "PLA", "profil": "PLA Silk Noël"},
                    {"nom": "Silk Or", "couleur": "#F2A900", "matiere": "PLA", "profil": "PLA Silk Noël"}]}))
    monkeypatch.setattr(catalog, "_file", lambda: own)
    trays = spools.loaded({"canvas_list": [{"tray_list": [
        {"tray_id": 1, "filament_color": "#FF0000", "filament_type": "PLA", "status": 2},           # red picked on screen
        {"tray_id": 2, "filament_color": "#1E88E5", "filament_type": "PLA", "status": 2},           # a blue: not ours
        {"tray_id": 3, "filament_color": "#E53935", "filament_type": "PLA", "filament_name": "PLA Matte", "status": 2},
        {"tray_id": 4, "filament_color": "#FFD700", "filament_type": "PETG", "status": 2}]}]})     # other material
    assert trays[0]["color"] == "#D22630" and trays[0]["printer_color"] == "#FF0000"
    assert spools.filament_for(trays[0]) == "PLA Silk Noël" and trays[0]["filament_name"] == "Silk Rouge Noël"
    assert [t.get("profile") for t in trays[1:]] == [None, None, None]
    assert "PLA Silk Noël" in slicer.filaments()
    src = tmp_path / "cube.stl"
    trimesh.creation.box((20, 20, 20)).export(src)
    g = slicer.slice_model(src, tmp_path / "out", filament=["PLA Silk Noël"], colours=["#D22630"]).gcode[0]
    text = g.read_text(errors="ignore")
    assert g.name.isascii() and "; filament_max_volumetric_speed = 12" in text
    assert '; filament_settings_id = "Elegoo PLA Silk @ECC2"' in text     # a name the CC2 knows


def test_specks_melt_into_their_surroundings_but_hand_paint_stays():
    import numpy as np
    from elegoo_lab import colors, threemf
    s = trimesh.creation.icosphere(subdivisions=4)
    lab = (s.triangles_center[:, 2] > 0).astype(int)          # two halves
    speck = np.argsort(s.triangles_center[:, 2])[:3]          # around the bottom pole, far from the other half
    lab[speck] = 1                                             # a few faces of the other colour
    part = threemf.Part("s", np.asarray(s.vertices), np.asarray(s.faces))
    clean = colors._clean_labels(part, lab)
    assert (clean[speck] == 0).all()
    assert abs((clean == 1).mean() - (lab == 1).mean()) < 0.01   # the halves themselves stay
    part.locked = np.zeros(len(lab), bool)
    part.locked[speck] = True                                  # painted by hand: kept
    assert (colors._clean_labels(part, lab)[speck] == 1).all()


def test_model_repainted_with_the_loaded_spools(tmp_path):
    from elegoo_lab import colors, spools
    cube = trimesh.creation.box((20, 20, 20))
    cube.unmerge_vertices()
    cube.visual = trimesh.visual.ColorVisuals(cube, face_colors=[[150, 10, 10, 255]] * 6 + [[30, 110, 60, 255]] * 6)
    src = tmp_path / "rouge_vert.glb"
    cube.export(src)
    palette = ("#D22630", "#F2A900", None, "#008755")                # slot 3 empty
    a = colors.analyze(src, palette)
    assert a["palette"] and {c["index"] for c in a["colours"]} == {1, 4}     # dark red -> red spool, dull green -> green
    assert all(c["slot"] == c["index"] and c["hex"] == palette[c["index"] - 1] for c in a["colours"])
    out = colors.to_canvas(src, tmp_path / "c.3mf", {1: 1, 4: 4}, palette=palette)
    assert out["slot_colours"][0] == "#D22630" and out["slot_colours"][3] == "#008755"
    trays = [{"color": "#D22630", "pos": 0, "type": "PLA", "filament_name": "Rouge"}]
    assert "pas de bobine proche" in spools.far_colours([{"hex": "#0A3CC8", "share": 50.0}], trays)[0]
    assert not colors.analyze(src)["palette"]                         # without spools: the model's own colours



def test_assembly_takes_the_spools_colours(tmp_path):
    import zipfile
    from elegoo_lab import colorize, colors
    a, b = tmp_path / "a.stl", tmp_path / "b.stl"
    trimesh.creation.box((10, 10, 10)).export(a)
    trimesh.creation.box((10, 10, 10)).apply_translation((0, 0, 10)).export(b)
    cols = ["#E9E9E7", "#D22630"]
    colorize.build_3mf([(a, 1), (b, 2)], tmp_path / "x.3mf", colours=cols, flush=colors.flush_matrix(cols))
    cfg = json.loads(zipfile.ZipFile(tmp_path / "x.3mf").read("Metadata/project_settings.config"))
    assert cfg["filament_colour"] == cols
    assert cfg["flush_volumes_matrix"] == [str(v) for v in colors.flush_matrix(cols)]   # purge sized to each change


def test_name_added_inside_a_line_drawing(tmp_path):
    import numpy as np
    import manifold3d as mf
    from elegoo_lab import addtext, colors
    ring = (mf.CrossSection.circle(40, 96) - mf.CrossSection.circle(37, 96)).extrude(2.0)   # a drawn circle, 2 mm
    m = ring.to_mesh()
    src = tmp_path / "cercle.stl"
    trimesh.Trimesh(np.asarray(m.vert_properties)[:, :3], np.asarray(m.tri_verts)).export(src)
    for font, angle in (("manuscrite", 0), ("manuscrite", 30), ("trait", 0)):
        r = addtext.add(src, "Noël", font=font, angle=angle, out=tmp_path / f"c{font}{angle}.3mf")
        assert r["pieces"] == 1 and 3 < r["capitales_mm"] < 40               # one piece: accents and bar tied
        a = colors.analyze(tmp_path / r["name"])
        assert {c["index"] for c in a["colours"]} == {1, 2}                    # model and text, two colours
    with pytest.raises(ValueError):
        addtext.add(src, "   ")


def test_bed_mesh_can_be_commented_out_of_the_start_gcode():
    from elegoo_lab import slicer
    g = b"G90\nM190 S65 A\nBED_MESH_CALIBRATE mesh_min=10,74 mesh_max=203,233 FROM_SLICER=1\nG28\n"
    out = slicer.without_bed_mesh(g)
    assert b"\nBED_MESH_CALIBRATE" not in out and b"G28\n" in out and out.count(b"\n") == g.count(b"\n")


async def test_end_of_print_is_read_from_the_printer_history(tmp_path, monkeypatch):
    """The real CC2 goes from 97 % straight to idle: its history says whether the print completed (1) or was stopped (2)."""
    from elegoo_lab import alerts, gallery
    monkeypatch.setattr(config, "MODELS_DIR", tmp_path)
    monkeypatch.setattr(config, "CONFIG_FILE", tmp_path / "config.toml")
    tasks = []

    async def history():
        return {"history_task_list": tasks}

    w = alerts.Watcher(lambda: None, history=history)
    w.observe(0, 0, "", {})
    for name, status in (("spatule.gcode", 1), ("bac.gcode", 2)):
        w.observe(13, 0, name, {}); w.observe(13, 97, name, {})
        tasks.append({"task_name": name, "task_status": status, "end_time": int(time.time())})
        w.observe(0, 0, "", {})
        await asyncio.sleep(0.2)
    assert [(e["kind"], e["detail"].split(" :")[0]) for e in w.events] == [
        ("debut", "spatule.gcode"), ("fin", "spatule.gcode"), ("debut", "bac.gcode"), ("arret", "bac.gcode")]
    issues = {e["fichier"]: (e["issue"], e["progression"]) for e in gallery.entries()}
    assert issues == {"spatule.gcode": ("terminee", 100), "bac.gcode": ("arretee", 97)}


def test_restart_mid_print_carries_on_with_the_open_gallery_entry(tmp_path, monkeypatch):
    from elegoo_lab import gallery
    monkeypatch.setattr(config, "MODELS_DIR", tmp_path)
    old = gallery.Recorder("oublie.gcode")                  # left "en cours" by a workshop stopped mid-print
    rec = gallery.Recorder("piece.gcode")
    rec.meta["debut"] -= 600
    rec.save()
    rec.add_frame(b"\xff\xd8x\xff\xd9")
    again = gallery.Recorder.resume("piece.gcode")
    assert again.id == rec.id and again.frames == 1 and again.meta["debut"] == rec.meta["debut"]
    assert gallery.close_stale(gallery.stale(keep=again.id)) == 1
    issues = {e["fichier"]: e["issue"] for e in gallery.entries()}
    assert issues == {"oublie.gcode": "interrompue", "piece.gcode": "en cours"} and old.id != rec.id


def test_unknown_printer_state_is_not_a_print(tmp_path, monkeypatch):
    """Seen on the real CC2 while it starts up: machine_status 9, mapped to 99 by pycentauri."""
    from elegoo_lab import alerts, gallery
    monkeypatch.setattr(config, "MODELS_DIR", tmp_path)
    monkeypatch.setattr(config, "CONFIG_FILE", tmp_path / "config.toml")
    w = alerts.Watcher(lambda: None)
    w.observe(99, 0, "", {}); w.observe(0, 0, "", {}); w.observe(99, 0, "", {}); w.observe(0, 0, "", {})
    assert w.events == [] and w.rec is None and gallery.entries() == []


def test_filament_is_taken_off_the_spool_that_fed_it(tmp_path, monkeypatch):
    """Seen on 2026-11-09: gold was T1 in the file but fed from tray 3; the count took it off tray 1."""
    from elegoo_lab import stock
    monkeypatch.setattr(config, "MODELS_DIR", tmp_path)
    stock.record_slice("ange.gcode", [0.0, 0.44, 0.84], [0.0, 0.1, 0.2])
    assert [t["tray"] for t in stock.check("ange.gcode", {1: 3, 2: 2})["trays"]] == [2, 3]
    stock.record_route("ange.gcode", {1: 3, 2: 2})
    stock.consume("ange.gcode", 1.0, "r1")
    left = {int(i): t["restant_g"] for i, t in stock.load()["trays"].items()}
    assert left[1] == left[0] and left[3] < left[0] and left[2] < left[0]


def test_model_preview_is_revalidated_not_downloaded_again(web):
    client, lib = web
    trimesh.creation.box((20, 20, 20)).export(lib / "cube.stl")
    r = client.get("/lab/api/models/cube.stl/preview.glb")
    assert r.status_code == 200 and r.headers["etag"]
    again = client.get("/lab/api/models/cube.stl/preview.glb", headers={"If-None-Match": r.headers["etag"]})
    assert again.status_code == 304 and not again.content
    other = client.get("/lab/api/models/cube.stl/preview.glb?pal=%23FF0000", headers={"If-None-Match": r.headers["etag"]})
    assert other.status_code == 200


def test_model_renamed_while_read_is_not_found_not_an_error(web, monkeypatch):
    from elegoo_lab import orient
    client, lib = web
    trimesh.creation.box((20, 20, 20)).export(lib / "cube.stl")

    def renamed(path, *a):   # the page renames the model while its positions are computed
        path.rename(lib / "autre.stl")
        raise FileNotFoundError(path)
    monkeypatch.setattr(orient, "orientations", renamed)
    r = client.get("/lab/api/models/cube.stl/orientations")
    assert r.status_code == 404 and "introuvable" in r.json()["detail"]

    def broken(path, *a):
        raise ValueError("maillage vide")
    monkeypatch.setattr(orient, "orientations", broken)
    assert client.get("/lab/api/models/autre.stl/orientations").status_code == 422   # a real failure stays one


def test_tailscale_name_goes_into_the_certificate(tmp_path, monkeypatch):
    import subprocess
    from cryptography import x509
    from elegoo_lab import access, certs
    monkeypatch.setattr(config, "ROOT", tmp_path)
    status = {"Self": {"Online": True, "TailscaleIPs": ["100.101.102.103", "fd7a::1"], "DNSName": "pc.tail1.ts.net."}}
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: subprocess.CompletedProcess(a, 0, json.dumps(status), ""))
    monkeypatch.setattr("shutil.which", lambda n: "/usr/bin/tailscale")
    ts = access.tailscale()
    assert ts == {"ip": "100.101.102.103", "name": "pc.tail1.ts.net"}
    crt, _ = certs.ensure(["192.168.1.70", ts["ip"]], [ts["name"]])
    san = x509.load_pem_x509_certificate(crt.read_bytes()).extensions.get_extension_for_class(x509.SubjectAlternativeName).value
    assert "pc.tail1.ts.net" in san.get_values_for_type(x509.DNSName)
    assert {str(a) for a in san.get_values_for_type(x509.IPAddress)} >= {"192.168.1.70", "100.101.102.103"}
    before = crt.read_bytes()
    certs.ensure(["192.168.1.70"])                       # Tailscale not up yet at boot: the certificate is kept
    assert crt.read_bytes() == before
    status["Self"]["Online"] = False
    assert access.tailscale() is None


def test_without_purge_turns_colour_changes_into_a_bare_switch(tmp_path):
    from elegoo_lab import slicer
    g = (b"M6211 A1 L200 T1 Q230 R230 S230\nT1\nM6211 T2 L14.7 M299 N299 Q230 R240 S230\nT2\n"
         b"M6211 T2 L0 M299\nT2\n")
    out = slicer.without_purge(g)
    lines = out.split(b"\n")
    assert lines[0].startswith(b"M6211 A1")                      # the start load keeps its purge
    assert lines[2].startswith(b"CANVAS_SWITCH_FILAMENT T=2")
    assert lines[4].startswith(b"M6211 T2 L0")                   # same tool: untouched
    assert slicer.firmware_purge_m(out, 4)[2] == 0.0                # no purge left for the changed-to tool (T2)
    f = tmp_path / "a.gcode"
    f.write_bytes(out)
    assert slicer._header(f)["colour changes"] == "2"   # the L0 line counts as before


def test_a_failed_write_keeps_the_old_file(tmp_path, monkeypatch):
    import os
    f = tmp_path / "stock.json"
    config.write_atomic(f, '{"a": 1}')
    monkeypatch.setattr(os, "fsync", lambda fd: (_ for _ in ()).throw(OSError("disque plein")))
    with pytest.raises(OSError):
        config.write_atomic(f, '{"a": 2}')
    assert f.read_text() == '{"a": 1}' and [p.name for p in tmp_path.iterdir()] == ["stock.json"]   # no leftover temp file


def test_backup_copies_the_library_and_keeps_old_versions(tmp_path, monkeypatch):
    """Real rsync and git; ssh is a stand-in that runs the "remote" side in a local folder."""
    import os
    import shutil
    from elegoo_lab import sauvegarde
    if not shutil.which("rsync"):
        pytest.skip("rsync absent")
    far, bin_ = tmp_path / "serveur", tmp_path / "bin"
    far.mkdir(), bin_.mkdir()
    (bin_ / "ssh").write_text(f'#!/bin/sh\nwhile [ "$1" = "-o" ]; do shift 2; done\nshift\ncd {far} && exec sh -c "$*"\n')
    (bin_ / "ssh").chmod(0o755)
    monkeypatch.setenv("PATH", f"{bin_}:{os.environ['PATH']}")
    (config.MODELS_DIR / "coeur.stl").write_text("v1")
    config.CONFIG_FILE.write_text('[printer]\nhost = "x"\n')
    assert sauvegarde.overdue().startswith("Aucune sauvegarde")
    sauvegarde.run("serveur")
    dest = far / sauvegarde.DEST
    assert (dest / "models" / "coeur.stl").read_text() == "v1" and (dest / "config.toml").exists()
    assert (dest / "elegoo.bundle").stat().st_size > 0 and sauvegarde.overdue() is None
    assert sauvegarde.run("serveur", if_needed=True) == "sauvegarde du jour déjà faite"
    (config.MODELS_DIR / "coeur.stl").write_text("v2")
    os.utime(config.MODELS_DIR / "coeur.stl", (time.time() + 5,) * 2)   # rsync compares size and time: an edit an hour later
    sauvegarde.run("serveur")
    assert (dest / "models" / "coeur.stl").read_text() == "v2"
    assert [p.read_text() for p in (dest / "anciens").glob("*/models/coeur.stl")] == ["v1"]   # the old version is kept
    (bin_ / "ssh").write_text("#!/bin/sh\necho 'ssh: connect to host 192.168.1.48 port 22: No route to host' >&2\nexit 255\n")
    with pytest.raises(RuntimeError, match="No route to host"):
        sauvegarde.run("serveur")
    assert sauvegarde.status()["erreur"].endswith("No route to host") and sauvegarde.overdue() is None   # yesterday's copy still counts


def test_backup_to_a_usb_disk_never_fills_the_pc_disk(tmp_path, monkeypatch):
    import shutil
    from elegoo_lab import sauvegarde
    if not shutil.which("rsync"):
        pytest.skip("rsync absent")
    disk = tmp_path / "CLE"
    disk.mkdir()
    (config.MODELS_DIR / "coeur.stl").write_text("v1")
    with pytest.raises(RuntimeError, match="non branché"):   # same disk as the library: an unplugged key's mount folder
        sauvegarde.run(str(disk))
    assert not any(disk.iterdir())
    monkeypatch.setattr(sauvegarde, "_same_disk", lambda a, b: False)
    sauvegarde.run(str(disk))
    assert (disk / "atelier-cc2" / "models" / "coeur.stl").read_text() == "v1"
    assert sauvegarde.status()["vers"] == str(disk / "atelier-cc2")


def test_old_printed_gcodes_go_their_models_stay():
    import json
    import os
    from elegoo_lab import library
    lib, old = config.MODELS_DIR, time.time() - 40 * 86400
    for m in ("coeur", "sapin", "etoile", "renne", "boule"):
        (lib / f"{m}.stl").write_text("solid")
    printed = {"coeur": old, "sapin": old, "etoile": time.time() - 86400, "lutin": old, "boule": old}
    for g in [*printed, "renne"]:
        f = lib / f"{g}_0.20mm_PLA.gcode"
        f.write_text("; G-code\n")
        os.utime(f, (old, old))
    for i, (g, t) in enumerate(printed.items()):
        d = lib / ".galerie" / f"2026{i}_{g}"
        d.mkdir(parents=True)
        (d / "meta.json").write_text(json.dumps({"id": d.name, "fichier": f"{g}_0.20mm_PLA.gcode", "debut": t,
                                                 "issue": "en cours" if g == "boule" else "terminee"}))
    gone = library.old_gcodes(keep={"sapin_0.20mm_PLA.gcode"})
    # sapin: in the queue · etoile: printed yesterday · lutin: no model left · renne: never printed · boule: printing
    assert gone == ["coeur_0.20mm_PLA.gcode"]
    library.delete(gone)
    assert not (lib / "coeur_0.20mm_PLA.gcode").exists() and (lib / "coeur.stl").exists()


def test_terminal_tells_only_what_changed(tmp_path, monkeypatch):
    from elegoo_lab import alerts
    monkeypatch.setattr(config, "MODELS_DIR", tmp_path)
    monkeypatch.setattr(config, "CONFIG_FILE", tmp_path / "config.toml")
    w = alerts.Watcher(lambda: None)
    raw = {"TempOfNozzle": 25, "TempTargetNozzle": 0, "TempOfHotbed": 25, "TempTargetHotbed": 0,
           "CurrenCoord": "0,0,0.2", "PrintInfo": {"CurrentLayer": 0, "TotalLayer": 362, "PrintSpeedPct": 100},
           "_cc2": {"machine_status": 1, "sub_status": 0}}
    w.narrate(raw, 0)
    w.term.clear()
    w.narrate(raw, 0)
    assert not w.term                                   # nothing new, nothing said
    raw = {**raw, "TempTargetNozzle": 230, "PrintInfo": {**raw["PrintInfo"], "CurrentLayer": 1, "PrintSpeedPct": 160}}
    w.narrate(raw, 13)
    w.narrate({**raw, "TempOfNozzle": 229}, 13)
    w.narrate({**raw, "TempOfNozzle": 231}, 13)
    texts = [l["text"] for l in w.term]
    assert texts == ["État : impression", "Couche 1 / 362 · Z 0,20 mm", "Buse : consigne 230 °C", "Vitesse : 160 %",
                     "Buse à 229 °C : consigne atteinte"]
    w.emit("pause", "x.gcode")
    assert w.term[-1]["level"] == "warn" and w.term[-1]["text"].startswith("Impression en pause")


def test_toolchange_reprime_no_longer_drops_a_blob():
    from elegoo_lab import slicer
    g = (b"M6211 A1 L200 T1 Q220 R220 S220\nT1\nG1 E6 F600\n"          # start load: its push stays
         b"G1 E-10 F1800\nM6211 T2 L34.9 M299 N299 Q220 R240 S220\nT2\nG1 X10 Y10 F30000\nG1 E10 F1800\n"
         b"G1 X12 Y10 E.5\n")
    lines = slicer.without_toolchange_reprime(g).split(b"\n")
    assert lines[2] == b"G1 E6 F600"
    assert lines[3] == b"G1 E-10 F1800"                                # the retract before the change is kept
    assert lines[7].startswith(b"G1 E1.7 F1800 ;")                     # 10 mm pushed on the spot -> 1.7 mm
    assert lines[8] == b"G1 X12 Y10 E.5"
    same = b"G1 E-10 F1800\nM6211 T2 L0 M299\nT2\nG1 E10 F1800\n"   # same spool: nothing is reloaded
    assert slicer.without_toolchange_reprime(same) == same


def test_phone_alerts_topic(web):
    """Phone alerts: "on" makes a private ntfy topic, "off" clears it, a test needs it on."""
    client, _ = web
    assert client.get("/lab/api/alertes/telephone").json() == {"ntfy": None}
    assert client.post("/lab/api/alertes/telephone", json={"action": "test"}).status_code == 409
    url = client.post("/lab/api/alertes/telephone", json={"action": "on"}).json()["ntfy"]
    assert url.startswith("https://ntfy.sh/cc2-") and len(url.rsplit("/", 1)[1]) == 24
    assert client.post("/lab/api/alertes/telephone", json={"action": "on"}).json()["ntfy"] != url   # never reused
    assert client.post("/lab/api/alertes/telephone", json={"action": "off"}).json() == {"ntfy": None}
    assert client.post("/lab/api/alertes/telephone", json={"action": "x"}).status_code == 422


def test_add_pauses(tmp_path):
    """PAUSE goes before the first layer above the asked height, never before layer 1, once per layer."""
    from elegoo_lab.printprep import add_pauses
    g = tmp_path / "p.gcode"
    g.write_text("G28\n" + "".join(f";LAYER_CHANGE\n;Z:{z}\n;HEIGHT:0.2\nG1 X1 E1\n" for z in (0.2, 0.4, 0.6, 0.8)))
    placed = add_pauses(g, [0.5, 0.55, 0.1, 9])
    assert placed == [{"mm": 0.5, "z": 0.4, "layer": 3, "run": 1}]
    lines = g.read_text().splitlines()
    assert lines.count("PAUSE") == 1 and lines[lines.index("PAUSE") + 2] == ";Z:0.6"


def test_add_pauses_each_piece_of_a_piece_by_piece_print(tmp_path):
    """Pieces printed one at a time restart from the bed: every one pauses at its own height."""
    from elegoo_lab.printprep import add_pauses
    g = tmp_path / "p.gcode"
    g.write_text("G28\n" + "".join(f";LAYER_CHANGE\n;Z:{z}\n;HEIGHT:0.2\nG1 X1 E1\n"
                                   for z in (0.2, 0.4, 0.6) + (0.2, 0.4, 0.6, 0.8)))
    placed = add_pauses(g, [0.5])
    assert [p["run"] for p in placed] == [1, 2] and [p["layer"] for p in placed] == [3, 3]
    assert g.read_text().count("PAUSE") == 2


def _piece_plate(tmp_path, name, gap_mm=10.0, extruders=(1, 2), heights=(20, 20)):
    """A plate 3MF of two cubes with the given gap, colours and heights (piece by piece in tests)."""
    import numpy as np
    from elegoo_lab import colorize, colors, threemf
    objs, x = [], 0.0
    for k, (e, h) in enumerate(zip(extruders, heights)):
        m = trimesh.creation.box((20, 20, h))
        src = tmp_path / f"cube{k}_{name}.stl"
        m.export(src)
        one = tmp_path / f"cube{k}_{name}.3mf"
        colorize.build_3mf([(src, e)], one)
        o = threemf.read(one).objects[0]
        move = np.array([x - min(p.vertices[:, 0].min() for p in o.parts), 0, 0])
        for p in o.parts:
            p.vertices = p.vertices + move
        x = max(p.vertices[:, 0].max() for p in o.parts) + gap_mm
        objs.append(threemf.Object(f"cube{k}", o.parts))
    out = tmp_path / f"plateau_{name}.3mf"
    cols = ["#1E88E5", "#FDD835"][: len(extruders)]
    threemf.write(threemf.Project(objs, cols), out, filaments=len(cols), colours=cols, flush=colors.flush_matrix(cols))
    return out, cols


def test_piece_by_piece_groups_colours_and_checks_the_head_path(tmp_path):
    """«Ordre d'impression : pièce par pièce» sorts the pieces by colour, keeps the wipes' place, and
    asks for the CC2's own clearances: enough space between pieces, low enough pieces."""
    from elegoo_lab import colors, settings, slicer, threemf
    radius, height = slicer.clearances()
    out, _ = _piece_plate(tmp_path, "espaces", gap_mm=radius, extruders=(2, 1))  # first piece wears slot 2
    conv = colors.to_canvas(out, tmp_path / "suite.3mf", {1: 1, 2: 2}, ordre="suite")
    assert conv["ordre"] == "suite"
    assert [o.name for o in threemf.read(tmp_path / "suite.3mf").objects] == ["cube1", "cube0"]   # slot 1 first
    proche, _ = _piece_plate(tmp_path, "cote", gap_mm=10.0, extruders=(2, 1))
    with pytest.raises(ValueError, match="l'une de l'autre"):              # 10 mm apart: the head would hit one
        colors.to_canvas(proche, tmp_path / "trop_proche.3mf", {1: 1, 2: 2}, ordre="suite")
    out_meme, _ = _piece_plate(tmp_path, "jumeaux", gap_mm=radius, extruders=(1, 1))  # same colours: layer by layer shares
    assert colors.to_canvas(out_meme, tmp_path / "meme.3mf", {1: 1}, ordre="suite")["ordre"] == "meme"
    out_haut, _ = _piece_plate(tmp_path, "haut", gap_mm=radius, extruders=(1, 2), heights=(height + 10, 20))
    with pytest.raises(ValueError, match="de haut"):                       # taller than the head can fly over
        colors.to_canvas(out_haut, tmp_path / "trop_haut.3mf", {1: 1, 2: 2}, ordre="suite")
    names = [c["name"] for c in settings.spec()["choices"]]
    assert "ordre" in names                                                   # the choice reaches the web UI


def test_small_pieces_plate_leaves_room_for_the_prime_tower(tmp_path):
    """write_plate said nothing about the prime tower, so OrcaSlicer put one itself: on a plate filling
    the bed width it landed in the CC2's unprintable corner and the whole slice failed with -102 (seen
    on a real cut model). The plate now keeps the tower's place and writes it into the file."""
    import numpy as np
    import zipfile
    from elegoo_lab import colors, printprep, slicer, threemf
    cols = ["#008755", "#D22630"]
    items = [(f"petite{k}", np.asarray(trimesh.creation.box((60, 20, 8)).vertices) + [0, 0, 4],
              np.asarray(trimesh.creation.box((60, 20, 8)).faces).astype(int),
              np.full(len(trimesh.creation.box((60, 20, 8)).faces), e))
             for k, e in enumerate((1, 2, 1, 2, 1, 2))]
    out = tmp_path / "petites.3mf"
    colors.write_plate(items, cols, out)
    v = np.vstack([q.vertices for o in threemf.read(out).objects for q in o.parts])
    assert v[:, 0].max() <= 201.01          # the tower stands at the right, where the CC2 prints
    with zipfile.ZipFile(out) as z:
        assert b"wipe_tower_x" in b"".join(z.read(n) for n in z.namelist() if n.startswith("Metadata"))
    piece = tmp_path / "morceau.3mf"        # one cut piece says its tower's place too
    m = trimesh.creation.box((30, 30, 20))
    colors.write_piece(np.asarray(m.vertices) + [0, 0, 10], np.asarray(m.faces).astype(int),
                       np.ones(len(m.faces), int), cols, piece, name="morceau")
    with zipfile.ZipFile(piece) as z:
        assert b"wipe_tower_x" in b"".join(z.read(n) for n in z.namelist() if n.startswith("Metadata"))
    if not (slicer.TOOLS / "squashfs-root" / "AppRun").exists():
        pytest.skip("slicer non installé (make slicer)")
    r = slicer.slice_model(out, tmp_path / "g", quality="0.20mm Standard", filament=["PLA", "PLA"],
                           overrides=printprep.TOWER["overrides"], timeout=240)
    assert r.gcode[0].exists()             # this plate died with -102 before the tower had its place


def test_piece_by_piece_slices_the_plate_with_far_fewer_changes(tmp_path):
    """Two one-colour pieces of different colours on (well spaced) one plate: one change per colour
    instead of one at nearly every layer."""
    from elegoo_lab import printprep, slicer
    if not (slicer.TOOLS / "squashfs-root" / "AppRun").exists():
        pytest.skip("slicer non installé (make slicer)")
    out, _ = _piece_plate(tmp_path, "espaces", gap_mm=slicer.clearances()[0], extruders=(2, 1))
    couches = printprep.prepare_and_slice(out, filaments=["PLA", "PLA Matte"], out_dir=tmp_path / "c", screen_thumbnail=False)
    suite = printprep.prepare_and_slice(out, filaments=["PLA", "PLA Matte"], advanced={"ordre": "suite"},
                                        out_dir=tmp_path / "s", screen_thumbnail=False)
    assert couches["ordre"] == "couche" and suite["ordre"] == "suite"
    assert suite["colour_changes"] * 4 < couches["colour_changes"]
    g = (tmp_path / "s" / Path(suite["gcode"][0]).name).read_text(errors="ignore")
    z = [float(l[3:]) for l in g.splitlines() if l.startswith(";Z:")]
    assert any(z[i] < z[i - 1] - 1e-6 for i in range(1, len(z)))            # one piece finishes, the next starts over


def test_mirror_and_axis_scale(tmp_path):
    """rotate[3:6] scales along the plate axes after the turns; a mirror keeps the surface facing out."""
    from elegoo_lab import colors
    src = tmp_path / "b.stl"
    trimesh.creation.box((10, 20, 30)).export(src)
    assert colors.rotation((0, 0, 0)) is None and colors.rotation((0, 0, 0, 1, 1, 1)) is None
    v, f, _, _ = colors.solid(src, {}, rotate=(0, 0, 90, -2, 1, 1))
    m = trimesh.Trimesh(v, f, process=False)
    assert sorted(map(round, m.extents)) == [10, 30, 40] and round(m.extents[0]) == 40 and m.volume > 0
    with pytest.raises(ValueError):
        colors.rotation((0, 0, 0, 0, 1, 1))


def test_import_link_guards():
    """Links: https only, never the house network; zips give their models; names come from the server."""
    import io, zipfile
    from elegoo_lab import importlink
    for bad in ("http://example.com/a.stl", "https://localhost/a.stl", "https://192.168.1.10/a.stl", "https://127.0.0.1/a.stl"):
        with pytest.raises(importlink.LinkError):
            importlink._check_host(bad)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("files/robot.stl", b"solid x")
        z.writestr("README.txt", b"hi")
        z.writestr("__MACOSX/._robot.stl", b"junk")
    assert importlink._from_zip(buf.getvalue()) == [("robot.stl", b"solid x")]
    assert importlink._name("https://x.org/dl?id=3", 'attachment; filename="vase%20v2.3mf"') == "vase v2.3mf"
    assert importlink._name("https://x.org/a/b/../owl.stl", None) == "owl.stl"


def test_print_queue(web):
    """The queue holds sliced files only, keeps its order, and forgets files deleted from the library."""
    client, lib = web
    for n in ("a.gcode", "b.gcode", "c.gcode"):
        (lib / n).write_text(";x\n")
    (lib / "m.stl").write_bytes(b"solid m")
    assert client.post("/lab/api/queue", json={"name": "m.stl"}).status_code == 422
    for n in ("a.gcode", "b.gcode", "c.gcode"):
        client.post("/lab/api/queue", json={"name": n})
    assert client.post("/lab/api/queue/move", json={"index": 2, "to": 0}).json() == ["c.gcode", "a.gcode", "b.gcode"]
    assert client.delete("/lab/api/queue/1").json() == ["c.gcode", "b.gcode"]
    (lib / "c.gcode").unlink()
    assert client.get("/lab/api/queue").json() == ["b.gcode"]
    assert client.delete("/lab/api/queue/5").status_code == 404


def test_calibration_tower_bands(tmp_path):
    """Each band above the 2 mm base gets its value once; slicer PA lines are muted; flow is reset at the end."""
    from elegoo_lab import calibration, settings
    g = tmp_path / "t.gcode"
    zs = [0.2, 1.0, 2.0, 2.2, 4.4, 4.6, 7.2]
    g.write_text("SET_PRESSURE_ADVANCE ADVANCE=0.04\n" + "".join(f";LAYER_CHANGE\n;Z:{z}\nG1 X1 E1\n" for z in zs))
    bands = calibration.tune(g, calibration.BY_KEY["avance"])
    assert [b["value"] for b in bands] == [0.0, 0.005, 0.01]
    text = g.read_text()
    assert "\nSET_PRESSURE_ADVANCE ADVANCE=0.04" not in text and text.count("ADVANCE=0.005 ;") == 1
    g.write_text("".join(f";LAYER_CHANGE\n;Z:{z}\n" for z in (0.2, 2.2, 6.2)))
    calibration.tune(g, calibration.BY_KEY["debit"])
    assert g.read_text().splitlines()[-1].startswith("M221 S100") and "M221 S92 " in g.read_text()
    _, fil = settings.build({"avance_pression": 0.035, "debit": 0.97})
    assert fil == {"pressure_advance": ["0.035"], "enable_pressure_advance": ["1"], "filament_flow_ratio": ["0.97"]}
    with pytest.raises(ValueError):
        settings.build({"debit": 1.5})


def test_parametric_preview(web):
    """The live preview is a GLB with the part's size, saves nothing, and reports bad sizes."""
    client, lib = web
    before = set(lib.iterdir())
    r = client.post("/lab/api/parametric/boite/preview", json={"longueur": 100})
    assert r.status_code == 200 and r.content[:4] == b"glTF" and r.headers["x-size"].startswith("100.0,")
    assert set(lib.iterdir()) == before
    assert client.post("/lab/api/parametric/boite/preview", json={"longueur": 999}).status_code == 422
    assert client.post("/lab/api/parametric/inconnu/preview", json={}).status_code == 422


def test_optimize_plan(web):
    """« Optimiser pour la CC2 » : a T standing on its foot gets laid on its back (no overhang left),
    one line per change, and the original file is untouched."""
    client, lib = web
    stem = trimesh.creation.box((10, 10, 30))
    stem.apply_translation((0, 0, 15))
    bar = trimesh.creation.box((40, 10, 6))
    bar.apply_translation((0, 0, 33))
    src = lib / "t.stl"
    trimesh.util.concatenate([stem, bar]).export(src)
    before = src.read_bytes()
    p = client.post("/lab/api/models/t.stl/optimize").json()
    assert p["file"] == "t.stl" and p["rotate"] != [0, 0, 0] and p["steps"]
    assert p["steps"][0]["title"].startswith("Posée") and all(s["why"] for s in p["steps"])
    assert src.read_bytes() == before
    assert client.post("/lab/api/models/x.gcode/optimize").status_code in (400, 404)


def test_alert_names_are_short():
    """Phone alerts name the model and its layer height, not the whole G-code file name."""
    from elegoo_lab.alerts import _GCODE, nice
    t = "atelier_couleurs_00015_clean_canvas_0.24mm_PLA_Silk_Noel-PLA_Silk_Noel.gcode en 6 h 28."
    assert _GCODE.sub(lambda m: nice(m.group(0)), t) == "atelier couleurs 00015 clean · 0,24 mm en 6 h 28."
    assert nice("stand_0.20mm_PLA.gcode") == "stand · 0,20 mm" and nice("essai.gcode") == "essai"


def test_plate_check_sees_a_part(tmp_path, monkeypatch):
    """The camera check: same plate = empty, a small coloured part on it = occupied, dark or no reference = unknown."""
    import io
    from PIL import Image, ImageDraw
    from elegoo_lab import bedcheck, config
    monkeypatch.setattr(config, "MODELS_DIR", tmp_path)

    def photo(part: bool, light: int = 70) -> bytes:
        img = Image.new("RGB", (640, 360), (light, light, light + 4))
        if part:   # a 5 g stand: dark green, about the plate's own grey level
            ImageDraw.Draw(img).ellipse((260, 295, 345, 335), fill=(20, 120, 70))
        buf = io.BytesIO(); img.save(buf, "JPEG"); return buf.getvalue()

    assert bedcheck.check(photo(False))["etat"] == "inconnu"
    bedcheck.save_reference(photo(False))
    assert bedcheck.check(photo(False, light=76))["etat"] == "vide"      # a little more light is not a part
    assert bedcheck.check(photo(True))["etat"] == "occupe"
    assert bedcheck.check(photo(False, light=5))["etat"] == "inconnu"    # light off
    with pytest.raises(ValueError):
        bedcheck.save_reference(photo(False, light=5))


def test_print_review(web):
    """After a print: tips from how it was made, corrections from the values really used, kept on the source model."""
    from elegoo_lab import gallery
    client, lib = web
    (lib / "orque.stl").write_bytes(b"solid x")
    g = lib / "orque_0.20mm_PLA.gcode"
    g.write_text("M190 S65\nT0\nT1\n;LAYER_CHANGE\n" + "; nozzle_temperature = 230,230\n; enable_support = 1\n"
                 "; filament_settings_id = \"Elegoo PLA Silk @ECC2\"\n")
    client.app.state  # noqa: B018
    from elegoo_lab import library
    library.record(g.name, source="orque.stl")
    rec = gallery.Recorder(g.name)
    rec.finish("terminee")
    d = client.get(f"/lab/api/bilan/{rec.id}").json()
    tips = " ".join(d["tips"])
    assert "65 °C" in tips and "Supports" in tips and "Plusieurs couleurs" in tips and "Silk" in tips
    assert [q["key"] for q in d["questions"]] == ["global", "surface", "details", "supports", "couleurs", "solidite"]
    r = client.post(f"/lab/api/bilan/{rec.id}", json={"issues": ["fils", "decolle", "inconnu"], "note": "ok",
                                                      "notes": {"global": 9, "surface": 3, "supports": -2, "autre": 4}}).json()
    assert r["notes"] == {"global": 5, "surface": 3, "supports": 0}   # clamped to 0..5, unknown questions dropped
    assert r["issues"] == ["fils", "decolle"] and r["fix"]["advanced"]["temp_buse"] == 220 and r["fix"]["advanced"]["temp_plateau"] == 70
    assert client.get("/lab/api/models/orque.stl/info").status_code in (200, 422)
    assert library.load_index()["orque.stl"]["retour"]["issues"] == ["fils", "decolle"]


def test_supports_plan_says_where_the_supports_are(tmp_path):
    """From the printed G-code: columns of supports by height, their place around the part, and a top view."""
    from elegoo_lab import aftercare
    lines = ["; support_type = tree(auto)", "; enable_support = 1"]
    for k in range(1, 31):                                  # 30 layers of 0.2 mm
        z = k * 0.2
        lines += [";LAYER_CHANGE", f";Z:{z:.1f}", ";TYPE:Outer wall"]
        lines += [f"G1 X{100 + i} Y{100 + (i % 3)} E.05" for i in range(40)]            # the part, x 100..140
        lines += [";TYPE:Support"] + [f"G1 X{90 + i * 0.1} Y{101} E.05" for i in range(10)]   # supports left of it
        if k % 10 == 0:
            lines += [";TYPE:Support interface"] + [f"G1 X{90 + i * 0.1} Y{102} E.05" for i in range(5)]
    g = tmp_path / "x.gcode"
    g.write_text("\n".join(lines) + "\n")
    plan = aftercare.supports_plan(g)
    assert plan and "tronc" in plan["tips"][0]
    zone = plan["tips"][1]
    assert zone.startswith("Zone 1 · ") and "à gauche" in zone and "du plateau jusqu'à" in zone and "touche la pièce" in zone
    assert plan["map"]["part"] and plan["map"]["supports"]
    assert aftercare.supports_plan(tmp_path / "absent.gcode") is None


def test_paths_overview_is_lighter_and_cached(tmp_path):
    """The review's whole-print view keeps every few layers (and the top one); a second read comes from memory."""
    import base64

    import numpy as np

    from elegoo_lab import gcode_preview
    lines = ["M83"]
    for k in range(1, 11):
        lines += [";LAYER_CHANGE", f";Z:{k * 0.2:.1f}", ";TYPE:Outer wall", "G0 X10 Y10"] + [f"G1 X{10 + i} Y10 E.05" for i in range(1, 11)]
    g = tmp_path / "x.gcode"
    g.write_text("\n".join(lines) + "\n")
    full = gcode_preview.cached(g)
    assert full["count"] == 100 and "pas" not in full
    lite = gcode_preview.cached(g, 40)
    assert lite["pas"] == 3 and lite["layers"] == full["layers"]
    lay = np.frombuffer(base64.b64decode(lite["layer"]), "<u2")
    assert sorted(set(lay.tolist())) == [0, 3, 6, 9]          # every third layer, and the last one
    assert gcode_preview.cached(g, 40) is lite                  # from memory
    assert gcode_preview.cached(g, 1000)["count"] == 100       # small enough: whole


def test_ntfy_end_of_print_offers_the_review(monkeypatch):
    """The "finished" alert on the phone opens the workshop, with a « Faire le bilan » button on that print."""
    import asyncio
    import httpx
    from elegoo_lab import alerts
    sent = {}

    async def post(self, url, **kw):
        sent.update(url=url, **kw)
        return httpx.Response(200)
    monkeypatch.setattr(httpx.AsyncClient, "post", post)
    monkeypatch.setattr(alerts, "ntfy_url", lambda: "https://ntfy.sh/cc2-test")
    monkeypatch.setattr(alerts, "_app_url", ["https://pc.example.ts.net:8443/lab/"])
    monkeypatch.setattr(alerts, "APP", {"https": True, "port": 8443})
    ev = {"title": "Impression terminée", "detail": "orque_0.20mm_PLA.gcode en 1 h.", "level": "ok", "bilan": "20261111-orque"}
    assert asyncio.run(alerts.send_ntfy(ev))
    h = sent["headers"]
    assert h["Click"] == "https://pc.example.ts.net:8443/lab/"
    assert h["Actions"] == "view, Faire le bilan, https://pc.example.ts.net:8443/lab/#bilan=20261111-orque, clear=true"
    assert sent["content"].decode() == "orque · 0,20 mm en 1 h."


def test_more_parametric_parts():
    """The new generators: every variant builds, sizes follow the standards, bad choices are refused."""
    import base64, io
    from PIL import Image
    from elegoo_lab import parametric
    sz = lambda k, v=None: parametric.preview(k, v or {})[1]
    assert sz("gridfinity", {"cases_x": 2, "cases_y": 1, "hauteur_u": 6, "empilable": False})[:3] == [83.5, 41.5, 42.0]   # 42 mm grid, 7 mm units
    for piece in ("vis", "ecrou", "rondelle", "entretoise"):
        assert sz("visserie", {"piece": piece, "taille": "M5"})
    assert sz("visserie", {"piece": "ecrou", "taille": "M8"})[2] == 6.5                    # ISO nut height
    assert round(sz("engrenage", {"dents": 20, "module": 2})[0]) == 44                     # tip diameter (z + 2) m
    for forme in ("boule", "etoile", "sapin"):
        assert sz("decoration_noel", {"forme": forme})
    buf = io.BytesIO(); Image.new("L", (40, 20), 128).save(buf, "PNG")
    photo = "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()
    w, thick, h = sz("lithophanie", {"photo": photo, "largeur": 60, "cadre": 0})
    assert abs(w - 60) < 1 and abs(h - 30) < 1 and thick <= 3.0                            # stands up, keeps the photo's shape
    with pytest.raises(ValueError):
        parametric.preview("visserie", {"taille": "M7"})


def test_simplify_colour_specks():
    """In each layer, a colour under the threshold takes the layer's main colour; hand-painted faces never change."""
    import numpy as np
    from elegoo_lab import colors, threemf
    box = trimesh.creation.box((20, 20, 2)).subdivide().subdivide()
    part = threemf.Part("p", np.asarray(box.vertices), np.asarray(box.faces))
    st = np.ones(len(box.faces), int)
    st[:2] = 2                                       # a speck of colour 2
    states = [st.copy()]
    assert colors.simplify_layers([part], states, 2.5, 0.03) == 1 and (states[0] == 1).all()
    part.locked = np.zeros(len(box.faces), bool); part.locked[0] = True
    states = [st.copy()]
    assert colors.simplify_layers([part], states, 2.5, 0.03) == 0 and states[0][0] == 2
