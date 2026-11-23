import asyncio
import json
import time
from pathlib import Path

import fakeprinter as sim
import httpx
import pytest
import trimesh

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
    assert hist
    assert hist[0]["task_status"] == 1


async def test_wrong_access_code():
    import pycentauri.connect as connect
    from pycentauri.client import PrinterError

    s = sim.Sim(port=18841, http_port=18851)
    task = asyncio.create_task(s.serve())
    await asyncio.sleep(0.2)
    import pycentauri.cc2 as cc2

    old = (cc2.MQTT_PORT, cc2._fetch_serial, connect._port_open)
    sim.patch_pycentauri()
    cc2.MQTT_PORT = 18841
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
    assert info["watertight"]
    assert info["fits_bed"]
    assert max(info["size_mm"]) == pytest.approx(60, abs=0.5)
    assert trimesh.load(out).bounds[0][2] == pytest.approx(0, abs=1e-6)


def test_comfy_generate_roundtrip(tmp_path, monkeypatch):
    wf_dir = tmp_path / "wf"
    wf_dir.mkdir()
    (wf_dir / "t.json").write_text(json.dumps({"1": {"inputs": {"image": "x", "seed": 0}}}))
    (wf_dir / "t.map.json").write_text(json.dumps({"image": ["1", "image"], "seed": ["1", "seed"]}))
    monkeypatch.setattr(comfy, "WORKFLOWS", wf_dir)
    sent = {}

    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.path == "/upload/image":
            return httpx.Response(200, json={"name": "up.png"})
        if req.url.path == "/prompt":
            sent.update(json.loads(req.content))
            return httpx.Response(200, json={"prompt_id": "p1"})
        if req.url.path == "/history/p1":
            return httpx.Response(
                200,
                json={
                    "p1": {
                        "status": {"completed": True, "status_str": "success"},
                        "outputs": {
                            "9": {"3d": [{"filename": "m.glb", "subfolder": "", "type": "output"}]}
                        },
                    }
                },
            )
        if req.url.path == "/view":
            return httpx.Response(200, content=b"glbdata")
        return httpx.Response(404)

    c = comfy.Comfy("http://x")
    c.http = httpx.Client(base_url="http://x", transport=httpx.MockTransport(handler))
    img = tmp_path / "in.png"
    img.write_bytes(b"png")
    files = comfy.generate(c, "t", tmp_path, image=img)
    assert files[0].read_bytes() == b"glbdata"
    assert files[0].suffix == ".glb"
    assert sent["prompt"]["1"]["inputs"]["image"] == "up.png"
    with pytest.raises(comfy.ComfyError):
        comfy.load_workflow("nope")


@pytest.mark.slicing
def test_slice_cylinder_and_overrides(tmp_path):
    from elegoo_lab import slicer

    if not (slicer.TOOLS / "squashfs-root" / "AppRun").exists():
        pytest.skip("slicer non installé (make slicer)")
    src = tmp_path / "cyl.stl"
    trimesh.creation.cylinder(radius=10, height=20, sections=48).export(src)
    r = slicer.slice_model(src, tmp_path / "out", infill=5, supports=False)
    assert r.layers == 100
    assert r.gcode[0].exists()
    assert "Centauri Carbon 2" in r.gcode[0].read_text(errors="ignore")
    dense = slicer.slice_model(src, tmp_path / "out2", infill=60)
    assert dense.filament_m > r.filament_m  # overrides really reach the slicer
    with pytest.raises(slicer.SliceError):
        slicer.slice_model(src, tmp_path / "o3", quality="nope")
    with pytest.raises(slicer.SliceError):
        slicer.slice_model(tmp_path / "x.txt", tmp_path / "o4")


@pytest.mark.slicing
def test_multicolor_parts_change_tool_at_junction(tmp_path):
    from elegoo_lab import colorize, slicer

    if not (slicer.TOOLS / "squashfs-root" / "AppRun").exists():
        pytest.skip("slicer non installé (make slicer)")
    base = trimesh.creation.box((30, 30, 10))
    base.apply_translation((0, 0, 5))
    base.export(tmp_path / "b.stl")
    top = trimesh.creation.cylinder(radius=8, height=10, sections=32)
    top.apply_translation((0, 0, 15))
    top.export(tmp_path / "t.stl")
    info = colorize.build_3mf(
        [(tmp_path / "b.stl", 1), (tmp_path / "t.stl", 2)], tmp_path / "duo.3mf"
    )
    assert info["filaments"] == 2
    r = slicer.slice_model(tmp_path / "duo.3mf", tmp_path / "o", filament=["PLA", "PLA Matte"])
    g = r.gcode[0].read_text(errors="ignore")
    assert "\nT1\n" in g
    assert g.count("\nT0\n") >= 1
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
    for s in range(10):
        assert colors.paint_states(colors.encode_state(s)) == {s}
    assert colors.remap_paint("8", {2: 4}) == "1C"
    # triangle split in two (split=1, special side 0) with leaves 1 and 2: bits 1,0|0,0|0,0,1,0|0,0,0,1
    split = "841"
    assert colors.paint_states(split) == {1, 2}
    assert colors.remap_paint(split, {}) == split
    assert colors.paint_states(colors.remap_paint(split, {1: 4})) == {4, 2}


@pytest.mark.slicing
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
    assert len(a["colours"]) == 2
    assert a["multicolour"]
    res = printprep.prepare_and_slice(src, filaments=["PLA", "PLA Matte"], out_dir=tmp_path)
    g = (tmp_path / res["gcode"][0]).read_text(errors="ignore")
    assert "\nT1\n" in g
    assert len(res["slots"]) == 2
    assert all(s["metres"] > 0 for s in res["slots"])
    # swapping slots swaps the filament usage
    swapped = printprep.prepare_and_slice(
        src,
        mapping={c["index"]: 3 - c["slot"] for c in a["colours"]},
        filaments=["PLA", "PLA Matte"],
        out_dir=tmp_path,
    )
    assert [s["metres"] for s in swapped["slots"]] == pytest.approx(
        [s["metres"] for s in res["slots"]][::-1], rel=0.05
    )


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
    t = "".join(
        f'<triangle v1="{a}" v2="{b}" v3="{c}"' + (' pid="2" p1="1"' if zc > 10 else "") + "/>"
        for (a, b, c), zc in zip(m.faces, m.triangles_center[:, 2], strict=True)
    )
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("3D/3dmodel.model", STD_3MF.format(v=v, t=t))
        z.writestr(
            "_rels/.rels",
            '<?xml version="1.0"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Target="/3D/3dmodel.model" Id="r" Type="http://schemas.microsoft.com/3dmanufacturing/2013/01/3dmodel"/></Relationships>',
        )


@pytest.mark.slicing
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
    assert len(pr.objects) == 1
    assert pr.objects[0].parts[0].paint
    assert pr.colours[:2] == [c["hex"] for c in a["colours"]][:2]
    if not (slicer.TOOLS / "squashfs-root" / "AppRun").exists():
        pytest.skip("slicer non installé")
    r = printprep.prepare_and_slice(src, out_dir=tmp_path)
    assert len(r["slots"]) == 2
    assert all(s["metres"] > 0 for s in r["slots"])
    assert r["colour_changes"] >= 1


def test_3mf_reader_unusual_shapes_and_cache(tmp_path):
    import os
    import zipfile

    from elegoo_lab import threemf

    head = (
        '<?xml version="1.0"?>\n<model unit="centimeter" xmlns="http://schemas.microsoft.com/3dmanufacturing/core/2015/02"'
        ' xmlns:m="http://schemas.microsoft.com/3dmanufacturing/material/2015/02" xmlns:s="http://schemas.slic3r.org/3mf/2017/06">'
    )
    verts = '<vertices><vertex y="2" x="1" z="3"/><vertex x="4" y="5" z="6" /><vertex x="7" y="8" z="9"/></vertices>'
    tris = (
        '<triangles><triangle v3="2" v1="0" v2="1" s:mmu_segmentation="8"/>\n<triangle\n v1="0"\tv2="2" v3="1"/>'
        '<triangle v1="1" v2="2" v3="0" paint_color="" s:mmu_segmentation="C" pid="5" p1="0"/></triangles>'
    )
    doc = (
        head
        + '<resources><m:colorgroup id="5"><m:color color="#FF0000"/><m:color color="#00FF00"/></m:colorgroup>'
        f'<object id="1" type="model" pid="5" pindex="1"><mesh>{verts}{tris}</mesh></object>'
        '<object id="2" type="model"><mesh/></object></resources><build><item objectid="1"/></build></model>'
    )
    src = tmp_path / "odd.3mf"
    with zipfile.ZipFile(src, "w") as z:
        z.writestr("3D/3dmodel.model", doc)
    p = threemf.read(src).objects[0].parts[0]
    assert p.vertices[0].tolist() == [10, 20, 30]  # attribute order, unit
    assert p.faces.tolist() == [[0, 1, 2], [0, 2, 1], [1, 2, 0]]
    assert p.paint == ["8", None, "C"]  # an empty paint_color falls back
    assert p.face_rgb.tolist() == [
        [0, 255, 0],
        [0, 255, 0],
        [255, 0, 0],
    ]  # object colour, then the triangle's
    p.vertices += 100  # a caller moving its copy...
    assert threemf.read(src).objects[0].parts[0].vertices[0].tolist() == [
        10,
        20,
        30,
    ]  # ...never moves the cached one
    with zipfile.ZipFile(src, "w") as z:
        z.writestr("3D/3dmodel.model", doc.replace('y="2" x="1"', 'y="2" x="2"'))
    os.utime(src, ns=(src.stat().st_mtime_ns + 10**6,) * 2)
    assert threemf.read(src).objects[0].parts[0].vertices[0].tolist() == [
        20,
        20,
        30,
    ]  # a new version is read again


@pytest.mark.slicing
def test_variable_layer_height_follows_the_slopes(tmp_path):
    import re
    import zipfile

    import numpy as np

    from elegoo_lab import couches, printprep, settings, slicer

    ball = trimesh.creation.icosphere(4, radius=15)
    ball.apply_translation([0, 0, 15])
    b = couches.bands(np.asarray(ball.vertices), np.asarray(ball.faces), 0.2, "pentes")
    h = lambda z: next(x for z0, z1, x in b if z0 <= z <= z1)  # noqa: E731
    assert h(29.5) < h(15) == 0.2
    assert min(x for *_, x in b) >= couches.MIN_MM
    tube = trimesh.creation.cylinder(radius=10, height=30, sections=64)
    tube.apply_translation([0, 0, 15])
    assert couches.bands(np.asarray(tube.vertices), np.asarray(tube.faces), 0.2, "rapide") == [
        (0.0, 30.0, 0.28)
    ]  # walls only
    with pytest.raises(ValueError):
        settings.build({"couches": "partout"})
    if not (slicer.TOOLS / "squashfs-root" / "AppRun").exists():
        pytest.skip("slicer non installé")
    src = tmp_path / "boule.stl"
    ball.export(src)
    flat = printprep.prepare_and_slice(src, out_dir=tmp_path / "a", advanced={"couches": "non"})
    var = printprep.prepare_and_slice(src, out_dir=tmp_path / "b", advanced={"couches": "pentes"})
    assert (
        zipfile.ZipFile(tmp_path / "b" / "boule_canvas.3mf")
        .read("Metadata/layer_config_ranges.xml")
        .count(b"<range")
        > 2
    )
    assert var["layers"] > flat["layers"]
    assert any("couches de plus" in w for w in var["warnings"])
    g = (tmp_path / "b" / var["gcode"][0]).read_text(errors="ignore")
    zs = [float(z) for z in re.findall(r"^;Z:([\d.]+)", g, re.M)]
    assert min(round(b - a, 2) for a, b in zip(zs, zs[1:], strict=False)) < 0.2


@pytest.mark.slicing
def test_painted_supports_and_seam_reach_the_slicer():
    import zipfile

    from elegoo_lab import colors, printprep, slicer, threemf

    foot, cap = trimesh.creation.box((8, 8, 20)), trimesh.creation.box((30, 30, 4))
    foot.apply_translation([0, 0, 10])
    cap.apply_translation([0, 0, 22])
    src = config.MODELS_DIR / "champi.stl"  # a mushroom: the cap hangs out
    trimesh.util.concatenate([foot, cap]).export(src)
    pv = colors.preview_glb(src)
    under = [
        i
        for i, (c, n) in enumerate(zip(pv.triangles_center, pv.face_normals, strict=True))
        if n[2] < -0.9 and c[1] > 19
    ]  # Y-up
    assert colors.save_marks(src, {"support": under, "couture": [0]}) == {
        "support": len(under),
        "couture": 1,
    }
    with pytest.raises(ValueError):
        colors.save_marks(src, {"partout": [1]})
    out = config.MODELS_DIR / "c.3mf"
    colors.to_canvas(src, out, {1: 1}, copies=2)
    parts = [p for o in threemf.read(out).objects for p in o.parts]
    assert all(
        sum(1 for c in p.supports if c) == len(under) and p.seam[0] for p in parts
    )  # every copy carries them
    assert b'paint_supports="4"' in zipfile.ZipFile(out).read("3D/Objects/part_1.model")
    if not (slicer.TOOLS / "squashfs-root" / "AppRun").exists():
        pytest.skip("slicer non installé")
    support = (
        lambda r, d: (d / r["gcode"][0]).read_text(errors="ignore").count(";TYPE:Support")
    )  # noqa: E731
    d = config.MODELS_DIR / "a"
    r = printprep.prepare_and_slice(src, out_dir=d)
    assert support(r, d) > 0
    assert any("peints" in w for w in r["warnings"])
    colors.save_marks(src, {"sans_support": list(range(len(pv.faces)))}, clear=False)
    d = config.MODELS_DIR / "b"
    assert (
        support(printprep.prepare_and_slice(src, out_dir=d, supports=True), d) == 0
    )  # never here, everywhere


def test_drill_add_or_keep_a_shape():
    from elegoo_lab import colors, forme, threemf

    lib = config.MODELS_DIR
    trimesh.creation.box((30, 30, 10)).export(lib / "plaque.stl")
    vol = lambda n: sum(
        trimesh.Trimesh(p.vertices, p.faces).volume
        for o in threemf.read(lib / n).objects
        for p in o.parts
    )  # noqa: E731
    hole = forme.apply(
        lib / "plaque.stl", shape="cylindre", op="percer", size=(8, 8, 20), at=(0, 0, 0)
    )
    assert hole["name"] == "plaque_perce.3mf"
    assert abs(vol(hole["name"]) - (9000 - 3.1416 * 16 * 10)) < 60
    peg = forme.apply(
        lib / "plaque.stl", shape="cylindre", op="ajouter", size=(8, 8, 20), at=(0, 0, 5), colour=2
    )
    parts = [p for o in threemf.read(lib / peg["name"]).objects for p in o.parts]
    assert [p.extruder for p in parts] == [1, 2]
    assert abs(vol(peg["name"]) - (9000 + 3.1416 * 16 * 10)) < 60
    assert forme.apply(
        lib / "plaque.stl", shape="sphere", op="garder", size=(10, 10, 10), at=(0, 0, 0)
    )["size_mm"] == [10.0, 10.0, 10.0]
    with pytest.raises(ValueError):
        forme.apply(
            lib / "plaque.stl", shape="cylindre", op="percer", size=(8, 8, 20), at=(100, 0, 0)
        )  # misses: nothing changes
    two = trimesh.creation.box((20, 20, 20))
    two.unmerge_vertices()
    two.visual = trimesh.visual.ColorVisuals(
        two, face_colors=[[200, 0, 0, 255]] * 6 + [[0, 120, 0, 255]] * 6
    )
    two.export(lib / "deux.glb")
    cut = forme.apply(
        lib / "deux.glb", shape="sphere", op="percer", size=(14, 14, 14), at=(0, 0, 10)
    )
    assert sorted(c["hex"] for c in colors.analyze(lib / cut["name"])["colours"]) == [
        "#007800",
        "#C80000",
    ]  # no blend


def test_pieces_placed_by_hand_stay_on_the_plate():
    from elegoo_lab import colors

    src = config.MODELS_DIR / "cube.stl"
    trimesh.creation.box((20, 20, 20)).export(src)
    out = config.MODELS_DIR / "c.3mf"
    colors.to_canvas(src, out, {1: 1}, shift=(-60.0, 40.0))  # moved, still on the plate
    with pytest.raises(ValueError, match="sort du plateau"):
        colors.to_canvas(src, out, {1: 1}, shift=(130.0, 0.0))
    with pytest.raises(ValueError, match="coin avant droit"):  # the CC2 does not print there
        colors.to_canvas(src, out, {1: 1}, shift=(110.0, -110.0))


def test_two_models_on_one_plate_then_one_piece_resized(web):
    """« + Pièce »: two library models side by side in a new model, colours shared; one piece then resized on the plate."""
    import numpy as np

    from elegoo_lab import colors, compose, threemf

    client, lib = web
    trimesh.creation.box((20, 20, 20)).export(lib / "bloc.stl")
    trimesh.creation.cylinder(radius=8, height=30).export(lib / "tube.stl")
    r = client.post("/lab/api/composer", json={"names": ["bloc.stl", "tube.stl"]}).json()
    assert r["name"] == "bloc + tube.3mf"
    assert r["pieces"] == 2
    assert len(r["colours"]) == 1
    pr = threemf.read(lib / r["name"])
    a, b = (np.vstack([p.vertices for p in o.parts]) for o in pr.objects)
    assert [o.name for o in pr.objects] == ["bloc", "tube"]
    assert b[:, 0].min() - a[:, 0].max() >= compose.GAP_MM - 0.01
    assert a[:, 2].min() == 0 == b[:, 2].min()
    assert client.post("/lab/api/composer", json={"names": ["bloc.stl"]}).status_code == 422
    out = lib / "bloc_plateau.3mf"
    colors.to_canvas(lib / r["name"], out, {1: 1}, scales={1: 2.0})
    a2, b2 = (np.vstack([p.vertices for p in o.parts]) for o in threemf.read(out).objects)
    assert np.ptp(b2[:, 2]) == pytest.approx(60, abs=0.01)
    assert np.ptp(a2[:, 2]) == pytest.approx(20, abs=0.01)
    assert b2[:, 2].min() == pytest.approx(
        0, abs=0.01
    )  # resized about its foot: still on the plate
    assert (b2[:, 0].min() + b2[:, 0].max()) / 2 - (
        a2[:, 0].min() + a2[:, 0].max()
    ) / 2 == pytest.approx(
        (b[:, 0].min() + b[:, 0].max()) / 2 - (a[:, 0].min() + a[:, 0].max()) / 2, abs=0.01
    )  # and in the same place
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
    out = client.post(
        f"/lab/api/models/{r['name']}/retirer", json={"index": 0, "moves": {}, "scales": {}}
    ).json()
    assert out["pieces"] == 1
    assert out["piece"] == "bloc"
    assert out["name"] == "bloc + tube sans bloc.3mf"
    pr = threemf.read(lib / out["name"])
    assert [o.name for o in pr.objects] == ["tube"]
    assert (lib / r["name"]).exists()  # the original plate stays in the library
    before = np.vstack([p.vertices for p in threemf.read(lib / r["name"]).objects[1].parts])
    after = np.vstack([p.vertices for p in pr.objects[0].parts])
    assert np.allclose(before.max(0), after.max(0), atol=0.01)
    assert np.allclose(before.min(0), after.min(0), atol=0.01)
    # the viewer's placements follow the surviving pieces (indexes shift past the removed one)
    out2 = client.post(
        f"/lab/api/models/{r['name']}/retirer",
        json={"index": 1, "moves": {"0": [15.0, 2.0, 0.0]}, "scales": {"0": 2.0}},
    ).json()
    assert out2["piece"] == "tube"
    base = np.vstack(
        [p.vertices for p in threemf.read(lib / r["name"]).objects[0].parts]
    )  # the bloc as composed
    kept = np.vstack([p.vertices for p in threemf.read(lib / out2["name"]).objects[0].parts])
    assert np.ptp(kept[:, 2]) == pytest.approx(40, abs=0.01)
    assert kept[:, 2].min() == pytest.approx(0, abs=0.01)
    assert kept[:, 0].max() == pytest.approx(
        base[:, 0].max() + (base[:, 0].max() - base[:, 0].min()) / 2 + 15, abs=0.05
    )
    assert kept[:, 0].min() == pytest.approx(
        base[:, 0].min() - (base[:, 0].max() - base[:, 0].min()) / 2 + 15, abs=0.05
    )
    assert (
        client.post(f"/lab/api/models/{out['name']}/retirer", json={"index": 0}).status_code == 422
    )
    assert client.post(f"/lab/api/models/{r['name']}/retirer", json={"index": 7}).status_code == 422


def test_compact_preview_glb_is_face_for_face():
    import struct

    import numpy as np

    from elegoo_lab import colors

    src = config.MODELS_DIR / "boule.stl"
    trimesh.creation.icosphere(2, radius=10).export(src)
    glb = colors.preview_glb_bytes(src)
    n, kind = struct.unpack("<I4s", glb[12:20])
    gltf = json.loads(glb[20 : 20 + n])
    prim = gltf["meshes"][0]["primitives"][0]
    assert glb[:4] == b"glTF"
    assert struct.unpack("<I", glb[8:12])[0] == len(glb)
    assert "indices" not in prim
    acc = {k: gltf["accessors"][i] for k, i in prim["attributes"].items()}
    assert acc["POSITION"]["count"] == 3 * 320
    assert acc["NORMAL"]["componentType"] == 5120
    assert gltf["extensionsRequired"] == ["KHR_mesh_quantization"]
    ref = colors.preview_glb(src)
    start = 20 + n + 8
    view = gltf["bufferViews"][acc["POSITION"]["bufferView"]]
    pos = np.frombuffer(
        glb[start + view["byteOffset"] : start + view["byteOffset"] + view["byteLength"]],
        np.float32,
    )
    assert np.allclose(pos.reshape(-1, 3), ref.vertices, atol=1e-5)


@pytest.mark.slicing
def test_economy_mode_purge_and_tower(tmp_path):
    import numpy as np

    from elegoo_lab import colors, printprep, slicer

    fm = colors.flush_matrix(["#FFFF00", "#101010"])  # yellow, black
    assert fm[0] == 0
    assert fm[1] < fm[2]
    assert colors.flush_matrix(["#FFFF00", "#101010"], smart=False)[1] == colors.FLUSH_MAX
    if not (slicer.TOOLS / "squashfs-root" / "AppRun").exists():
        pytest.skip("slicer non installé")
    m = trimesh.creation.box((20, 20, 20)).subdivide().subdivide()
    m.visual.face_colors = np.where(
        (m.triangles_center[:, 2] > 0)[:, None], [250, 220, 0, 255], [20, 20, 20, 255]
    )
    src = tmp_path / "bi.ply"
    m.export(src)
    eco = printprep.prepare_and_slice(src, out_dir=tmp_path / "e", mode="economie")
    qual = printprep.prepare_and_slice(src, out_dir=tmp_path / "q", mode="qualite")
    g_eco = (tmp_path / "e" / eco["gcode"][0]).read_text(errors="ignore")
    assert ";TYPE:Prime tower" not in g_eco
    assert "\nT1\n" in g_eco
    assert eco["total_m"] < qual["total_m"]
    assert sum(eco["purge_m"]) > 0


@pytest.mark.slicing
def test_a_bled_review_reinforces_the_purge(tmp_path):
    import numpy as np

    from elegoo_lab import colors, library, printprep, slicer

    if not (slicer.TOOLS / "squashfs-root" / "AppRun").exists():
        pytest.skip("slicer non installé")
    m = trimesh.creation.box((20, 20, 20)).subdivide().subdivide()
    m.visual.face_colors = np.where(
        (m.triangles_center[:, 2] > 0)[:, None], [20, 20, 20, 255], [240, 240, 240, 255]
    )
    src = tmp_path / "bi.ply"
    m.export(src)
    # white -> slot 1 (printed first), black -> slot 2: the single change is light -> dark, the cheap
    # direction, so only the reinforced slice pays the worst-case purge
    a = colors.analyze(src)
    mapping = {c["index"]: 1 if c["hex"].upper().startswith("#F") else 2 for c in a["colours"]}
    eco = printprep.prepare_and_slice(src, out_dir=tmp_path / "e", mode="economie", mapping=mapping)
    library.annotate(
        src.name, retour={"issues": ["couleurs"]}
    )  # what aftercare.review stores after a bad print
    fixed = printprep.prepare_and_slice(
        src, out_dir=tmp_path / "f", mode="economie", mapping=mapping
    )
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
    assert [a for a, _ in res.planes] == [2]
    assert len(res.pieces) == 2
    assert res.pin_count >= 1
    for p in res.pieces:
        piece = trimesh.Trimesh(p.vertices, p.faces, process=False)
        assert piece.is_watertight
        assert np.ptp(p.vertices[:, 2]) <= 256 - cut.MARGIN_MM
        assert piece.volume < 60 * 60 * 150  # the dowel holes were drilled
    assert {int(s) for p in res.pieces for s in np.unique(p.slots)} == {1, 2}
    assert res.pins is not None
    assert len(res.pins.split()) == res.pin_count


def test_config_save_keeps_other_settings(tmp_path, monkeypatch):
    from elegoo_lab import config

    monkeypatch.setattr(config, "CONFIG_FILE", tmp_path / "config.toml")
    (tmp_path / "config.toml").write_text('[comfyui]\nurl = "http://gpu:8188"\n')
    config.save("printer", host="192.168.1.42", access_code='Ab"3')
    config.save("assemblage", jeu_mm=0.2)
    c = config.load()
    assert (c.printer.host, c.printer.access_code, c.comfyui_url) == (
        "192.168.1.42",
        'Ab"3',
        "http://gpu:8188",
    )
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
        assert ok["ok"]
        assert [st["ok"] for st in ok["steps"]] == [True, True, True]
        assert ok["serial"] == sim.SIM_SERIAL
        empty = await connexion.check("", "x")
        assert not empty["ok"]
        assert empty["steps"][0]["fix"]
    finally:
        task.cancel()


def test_smart_cut_goes_through_the_neck():
    import numpy as np

    from elegoo_lab import cut

    # a 300 mm "figure": wide body, thin neck at z=190, wide head
    body = trimesh.creation.box((80, 80, 180))
    body.apply_translation((0, 0, 90))
    neck = trimesh.creation.cylinder(radius=10, height=30, sections=48)
    neck.apply_translation((0, 0, 195))
    head = trimesh.creation.box((70, 70, 90))
    head.apply_translation((0, 0, 255))
    import manifold3d as mf

    def m(t):
        return mf.Manifold(
            mf.Mesh(
                vert_properties=np.asarray(t.vertices, np.float32),
                tri_verts=np.asarray(t.faces, np.uint32),
            )
        )

    fig = (m(body) + m(neck) + m(head)).to_mesh()
    v, f = np.asarray(fig.vert_properties)[:, :3].astype(float), np.asarray(fig.tri_verts).astype(
        np.int64
    )
    smart = cut.cut(v, f, np.ones(len(f), int), name="fig")
    even = cut.cut(v, f, np.ones(len(f), int), name="fig", smart=False)
    ((axis, z),) = smart.planes
    assert axis == 2 and 178 <= z <= 212, z  # at or through the neck (180 = body/neck junction)
    assert not 180 < even.planes[0][1] < 210  # even spacing would cut the body


def test_comfy_chained_workflow_frees_vram_between_stages(tmp_path, monkeypatch):
    from elegoo_lab import comfy

    wf_dir = tmp_path / "wf"
    wf_dir.mkdir()
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
            return httpx.Response(
                200,
                json={
                    "pa": {
                        "status": {"completed": True},
                        "outputs": {
                            "9": {
                                "images": [
                                    {"filename": "figurine.png", "subfolder": "", "type": "output"},
                                    {
                                        "filename": "tmp_preview.png",
                                        "subfolder": "",
                                        "type": "temp",
                                    },
                                ]
                            }
                        },
                    }
                },
            )
        if path == "/history/pb":
            return httpx.Response(
                200,
                json={
                    "pb": {
                        "status": {"completed": True},
                        "outputs": {
                            "5": {"3d": [{"filename": "m.glb", "subfolder": "", "type": "output"}]}
                        },
                    }
                },
            )
        if path == "/view":
            return httpx.Response(200, content=b"data")
        return httpx.Response(200, json={})

    c = comfy.Comfy("http://x")
    c.http = httpx.Client(base_url="http://x", transport=httpx.MockTransport(handler))
    img = tmp_path / "photo.png"
    img.write_bytes(b"png")
    files = comfy.generate(c, "a", tmp_path, image=img)
    names = [f.name for f in files]
    assert any(n.endswith("figurine.png") for n in names)
    assert any(n.endswith("m.glb") for n in names)
    assert not any("tmp_preview" in n for n in names)  # temp previews are not kept
    assert calls.index("/free") < calls.index("/history/pb")  # VRAM freed before stage 2 runs
    assert len(uploads) == 2  # stage 2 received stage 1's image


@pytest.mark.slicing
def test_spool_matching_follows_loaded_canvas():
    from elegoo_lab import spools

    trays = spools.loaded(
        {
            "canvas_info": {
                "canvas_list": [
                    {
                        "tray_list": [
                            {
                                "tray_id": 0,
                                "color": "#FFFFFF",
                                "type": "PLA",
                                "filament_name": "PLA Matte Blanc",
                                "status": 1,
                            },
                            {
                                "tray_id": 1,
                                "color": "#E53935",
                                "type": "PLA",
                                "filament_name": "PLA Rouge",
                                "status": 1,
                            },
                            {"tray_id": 2, "color": "", "type": "", "status": 0},
                            {
                                "tray_id": 3,
                                "color": "#1E1E1E",
                                "type": "PETG",
                                "filament_name": "PETG Noir",
                                "status": 1,
                            },
                        ]
                    }
                ]
            }
        }
    )
    assert [t["tray_id"] for t in trays] == [0, 1, 3]  # the empty tray is ignored
    model = [
        {"index": 1, "hex": "#D02020", "share": 70.0},
        {"index": 2, "hex": "#F4F4F4", "share": 30.0},
    ]
    r = spools.match(model, trays)
    assert r["mapping"] == {1: 2, 2: 1}  # red -> T1, white -> T0
    assert r["filaments"] == ["PLA Matte", "PLA"]
    assert not r["warnings"]
    green = spools.match([{"index": 1, "hex": "#20C040", "share": 50.0}], trays)
    assert green["warnings"]
    assert "pas de bobine proche" in green["warnings"][0]
    mixed = spools.match(
        [
            {"index": 1, "hex": "#FFFFFF", "share": 50.0},
            {"index": 2, "hex": "#101010", "share": 50.0},
        ],
        trays,
    )
    assert any("incompatibles" in w for w in mixed["warnings"])  # PLA + PETG


@pytest.mark.slicing
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
    assert 20 <= dec[1] <= 40
    assert fun[1] > 3 * dec[1]
    assert spools.needs(None, model) == {}

    client, lib = web
    m = trimesh.creation.box((100, 40, 40)).subdivide().subdivide()
    m.visual.face_colors = np.where(
        (m.triangles_center[:, 2] > 0)[:, None], [250, 220, 0, 255], [20, 20, 20, 255]
    )
    m.export(lib / "bi.ply")

    async def canvas():
        return NS(
            raw={
                "canvas_info": {
                    "canvas_list": [
                        {
                            "canvas_id": 0,
                            "tray_list": [
                                {
                                    "tray_id": 0,
                                    "status": 1,
                                    "filament_color": "#FADC00",
                                    "filament_type": "PLA",
                                },
                                {
                                    "tray_id": 1,
                                    "status": 1,
                                    "filament_color": "#141414",
                                    "filament_type": "PLA",
                                },
                            ],
                        }
                    ]
                }
            }
        )

    client.app.state.manager = NS(printer=NS(canvas_status=canvas))
    r = client.get("/lab/api/models/bi.ply/match-spools?usage=decoratif").json()
    assert set(r["needs"]) == {"1", "2"}
    assert 20 <= int(r["needs"]["1"]) <= 40
    assert not r["warnings"]
    strong = client.get("/lab/api/models/bi.ply/match-spools?usage=fonctionnel").json()
    assert int(strong["needs"]["1"]) > 3 * int(r["needs"]["1"])

    from elegoo_lab import stock

    stock.calibrate_fill("decoratif", 100.0, 200.0)  # a real slice measured at twice the estimate
    after = spools.needs(160.0, model, usage="decoratif")
    assert dec[1] * 1.2 < after[1] <= dec[1] * 2  # the factor moved halfway, never straight to it
    assert stock.fill_factor("decoratif") == 1.5  # (100 g in, 200 g measured: ratio 2, half step)


@pytest.mark.slicing
def test_one_colour_model_takes_a_loaded_spool(tmp_path):
    from elegoo_lab import launch, spools

    trays = spools.loaded(
        {
            "canvas_info": {
                "canvas_list": [
                    {
                        "tray_list": [
                            {
                                "tray_id": 1,
                                "filament_color": "#E53935",
                                "filament_type": "PLA",
                                "filament_name": "PLA Rouge",
                                "status": 2,
                            },
                            {
                                "tray_id": 2,
                                "filament_color": "#FFFFFF",
                                "filament_type": "PLA",
                                "filament_name": "PLA Blanc",
                                "status": 2,
                            },
                            {
                                "tray_id": 3,
                                "filament_color": "#1E88E5",
                                "filament_type": "PETG",
                                "filament_name": "PETG Bleu",
                                "status": 2,
                            },
                        ]
                    }
                ]
            }
        }
    )
    blue = spools.single({"index": 1, "hex": "#2080E0", "share": 100.0}, trays, coloured=True)
    assert blue["mapping"] == {1: 1}
    assert blue["single"]["pos"] == 2
    assert blue["filaments"] == ["PETG"]
    assert blue["slot_colours"] == {1: "#1E88E5"}
    assert not blue["warnings"]
    grey = {"index": 1, "hex": "#C0C0C0", "share": 100.0}
    assert (
        spools.single(grey, trays, coloured=False, active=2)["single"]["pos"] == 1
    )  # the spool in the head
    assert spools.single(grey, trays, coloured=False)["single"]["pos"] == 0
    # the start dialog then sends the file's only tool to that very spool, not to T0
    canvas = {
        "canvas_info": {
            "canvas_list": [
                {
                    "canvas_id": 0,
                    "tray_list": [
                        {
                            "tray_id": 1,
                            "filament_color": "#FFFFFF",
                            "filament_type": "PLA",
                            "status": 2,
                        },
                        {
                            "tray_id": 2,
                            "filament_color": "#F4F4F4",
                            "filament_type": "PLA",
                            "status": 2,
                        },
                    ],
                }
            ]
        }
    }
    g = tmp_path / "gris.gcode"
    g.write_text("; filament_colour = #F4F4F4\n; filament_type = PLA\nG28\n")
    assert (
        launch.plan(g, canvas)["slot_map"][0]["tray_id"] == 2
    )  # near-white T0 would also have passed


@pytest.mark.slicing
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
    r = printprep.prepare_and_slice(
        src,
        out_dir=tmp_path / "a",
        rotate=(90, 0, 0),
        copies=2,
        advanced={
            "parois": 4,
            "motif": "gyroide",
            "temp_buse": 215,
            "motif_dessus": "concentrique",
            "paroi_dessus": "non",
            "paroi_precise": "oui",
        },
    )
    g = (tmp_path / "a" / r["gcode"][0]).read_text(errors="ignore")

    def val(k):
        return re.search(rf"^; {k} = (.*)$", g, re.M).group(1)

    assert val("curr_bed_type") == "Textured PEI Plate"
    assert re.search(r"^M140 S60", g, re.M)
    assert val("wall_loops") == "4"
    assert val("sparse_infill_pattern") == "gyroid"
    assert re.search(r"^M10[49] S215", g, re.M)
    assert val("top_surface_pattern") == "concentric"
    assert val("only_one_wall_top") == "0"
    assert val("precise_outer_wall") == "1"
    assert (
        abs(float(re.search(r"^; max_z_height: ([\d.]+)", g, re.M).group(1)) - 20) < 0.5
    )  # lying down: 20 mm tall
    with pytest.raises(ValueError):
        printprep.prepare_and_slice(
            src, out_dir=tmp_path / "b", copies=50, height_mm=60
        )  # does not fit


@pytest.mark.slicing
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
    assert res["temps"]["nozzle"]
    assert res["temps"]["bed"] > 0


def test_zip_upload_and_broken_step_rejected(web):
    import io
    import zipfile

    client, lib = web
    stl = trimesh.creation.box((10, 10, 10)).export(file_type="stl")
    zz = io.BytesIO()
    with zipfile.ZipFile(zz, "w") as z:
        z.writestr("un.stl", stl)
        z.writestr("deux.stl", stl)
        z.writestr(".cache.txt", b"junk")  # hidden files stay out
    r = client.post("/lab/api/models", files={"file": ("deux_pieces.zip", zz.getvalue())}).json()
    assert len(r["names"]) == 2
    assert (lib / r["names"][0]).exists()
    bad = client.post("/lab/api/models", files={"file": ("oxe.step", b"pas un STEP")})
    assert bad.status_code == 422
    assert not (lib / "oxe.step").exists()


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
    (lib / ".jobs.json").write_text(
        json.dumps([{"id": "j1", "state": "running", "workflow": "x", "started": 1}])
    )
    return TestClient(app_mod.create_app(enable_control=True)), lib


def test_firmware_limits_and_status_endpoints(web):
    """R1.5: the UI reads the CC2 limitations (blocked commands, versions) from these endpoints."""
    client, _lib = web
    lim = client.get("/lab/api/firmware/limits")
    assert lim.status_code == 200
    body = lim.json()
    assert "homing" in body["blocked_commands"]
    assert body["blocked_commands"]["homing"]
    assert body["safe_commands"]
    assert body["supported_versions"]
    assert body["problematic_versions"]
    st = client.get("/lab/api/firmware/status")
    assert st.status_code == 200
    assert "safe_mode" in st.json()
    assert "is_supported" in st.json()


def test_web_refuses_other_sites(web):
    client, lib = web
    stl = trimesh.creation.box((10, 10, 10)).export(file_type="stl")
    evil = client.post(
        "/lab/api/models", files={"file": ("a.stl", stl)}, headers={"Origin": "http://evil.example"}
    )
    assert evil.status_code == 403
    assert client.post("/print/pause", headers={"Sec-Fetch-Site": "cross-site"}).status_code == 403
    ok = client.post(
        "/lab/api/models", files={"file": ("a.stl", stl)}, headers={"Origin": "http://testserver"}
    )
    assert ok.status_code == 200
    assert ok.json()["name"] == "a.stl"
    again = client.post("/lab/api/models", files={"file": ("a.stl", stl)})  # CLI/scripts: no Origin
    assert again.json()["name"] == "a (2).stl"  # no silent overwrite
    assert (
        client.get("/lab/api/models/..%2F..%2Fconfig.toml").status_code == 404
    )  # stays in the library


def test_the_assistant_acts_through_the_workshop_tools(web, monkeypatch):
    """The chatbot, API engine: Mistral is faked, its tool calls run for real (resize → a new model in the library)."""
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
            {
                "choices": [
                    {
                        "message": {
                            "tool_calls": [
                                {"id": "c1", "function": {"name": "fiche", "arguments": "{}"}},
                                {
                                    "id": "c2",
                                    "function": {
                                        "name": "redimensionner",
                                        "arguments": json.dumps({"hauteur": 40}),
                                    },
                                },
                            ]
                        }
                    }
                ]
            },
            {"choices": [{"message": {"content": "Fait : « cube_h40mm.ply »."}}]},
        ]

        def json(self):
            return Fake.seq.pop(0)

    monkeypatch.setattr(assistant.httpx, "post", lambda url, **kw: Fake())
    r = client.post(
        "/lab/api/models/cube.stl/assistant", json={"message": "mets-le à 40 mm de haut"}
    )
    d = r.json()
    assert r.status_code == 200
    assert d["outils"] == ["fiche", "redimensionner"]
    assert d["file"] == "cube_h40mm.ply"
    assert (lib / "cube_h40mm.ply").exists()
    assert abs(mesh.info(lib / "cube_h40mm.ply")["size_mm"][2] - 40) < 0.5
    monkeypatch.setattr(assistant, "api_key", lambda: None)
    assert (
        client.post("/lab/api/models/cube.stl/assistant", json={"message": "coucou"}).status_code
        == 422
    )
    assert (
        client.post("/lab/api/models/absent.stl/assistant", json={"message": "x"}).status_code
        == 404
    )


def test_the_assistant_runs_on_the_local_cli(web, monkeypatch):
    """The chatbot, CLI engine: a fake headless vibe run thinks and asks the workshop's tools by JSON — no API key."""
    from elegoo_lab import assistant

    client, lib = web
    trimesh.creation.box((20, 20, 20)).export(lib / "cube.stl")
    monkeypatch.setattr(assistant, "moteur", lambda: "cli")
    monkeypatch.setattr(assistant, "cli_bin", lambda: "/tmp/bin/vibe")
    calls: list[list[str]] = []

    def cli_out(obj: dict) -> str:
        return json.dumps(
            [
                {
                    "sessionId": "S1",
                    "role": "assistant",
                    "type": "message",
                    "content": [{"type": "text", "text": json.dumps(obj, ensure_ascii=False)}],
                }
            ]
        )

    class Ok:
        returncode = 0
        stderr = ""

        def __init__(self, text):
            self.stdout = text

    seq = [
        Ok(
            cli_out(
                {
                    "outils": [
                        {"outil": "fiche"},
                        {"outil": "redimensionner", "arguments": {"hauteur": 40}},
                    ]
                }
            )
        ),
        Ok(cli_out({"reponse": "Fait : « cube_h40mm.ply » et exporté."})),
    ]
    fake_system = ""

    def fake_run(cmd, **kw):
        calls.append(cmd)
        nonlocal fake_system
        if "--system-prompt-file" in cmd:
            with open(cmd[cmd.index("--system-prompt-file") + 1]) as fh:
                fake_system = fh.read()
        return seq.pop(0)

    monkeypatch.setattr(assistant.subprocess, "run", fake_run)
    r = client.post(
        "/lab/api/models/cube.stl/assistant", json={"message": "mets-le à 40 mm de haut"}
    )
    d = r.json()
    assert r.status_code == 200
    assert d["outils"] == ["fiche", "redimensionner"]
    assert d["file"] == "cube_h40mm.ply"
    assert (lib / "cube_h40mm.ply").exists()
    prompt = calls[0][calls[0].index("-p") + 1]
    assert "cube.stl" in prompt
    assert "PROTOCOLE" in fake_system
    assert "--resume" not in calls[0]
    # round 2 resumes the CLI session instead of resending the whole fiche and history
    assert calls[1][calls[1].index("--resume") + 1] == "S1"
    assert "--system-prompt-file" not in calls[1]
    # headless mode: the native tools are off (the workshop does the files itself), MCP (Blender…) stays approved
    off = {t: i for i, t in enumerate(calls[0])}
    assert "bash" in calls[0]
    assert calls[0][off["bash"] - 1] == "--disabled-tools"
    assert "--auto-approve" not in calls[0]
    assert calls[0][off["--approval-policy"] + 1] == "auto-approve"
    # a CLI that goes away gives a clear error, not a crash
    monkeypatch.setattr(assistant, "cli_bin", lambda: None)
    assert (
        client.post("/lab/api/models/cube.stl/assistant", json={"message": "x"}).status_code == 422
    )


def test_the_api_engine_guards(web, monkeypatch):
    """API Mistral: a duplicate tool call is replayed without rerunning (then the answer is forced),
    a later tool of the same round works on the file the first one created, and a silent model gets one nudge.
    """
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
    seq = [
        msg(
            tool_calls=[{"id": "c1", "function": {"name": "fiche", "arguments": "{}"}}],
            content=None,
        ),
        msg(
            tool_calls=[{"id": "c2", "function": {"name": "fiche", "arguments": "{}"}}],
            content=None,
        ),
        msg(content="La fiche est là : cube de 20 mm de côté, étanche, 8 cm3."),
    ]

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
    assert r.status_code == 200
    assert d["reply"].startswith("La fiche est là")
    assert d["outils"] == ["fiche"]
    assert runs["n"] == 1
    assert d["file"] == "cube.stl"
    assert choices == ["auto", "auto", "none"]  # the all-duplicate round forces a plain answer

    # guard 2: a later tool of the same round works on the file the first one created
    seq[:] = [
        msg(
            tool_calls=[
                {
                    "id": "c1",
                    "function": {
                        "name": "redimensionner",
                        "arguments": json.dumps({"hauteur": 40}),
                    },
                },
                {
                    "id": "c2",
                    "function": {
                        "name": "redimensionner",
                        "arguments": json.dumps({"hauteur": 50}),
                    },
                },
            ],
            content=None,
        ),
        msg(content="Voilà le cube à 40 puis 50 mm de haut."),
    ]
    r = client.post(
        "/lab/api/models/cube.stl/assistant", json={"message": "mets-le à 40 puis 50 mm de haut"}
    )
    d = r.json()
    assert d["outils"] == ["redimensionner", "redimensionner"]
    assert runs["n"] == 3
    assert d["file"] == "cube_h40mm_h50mm.ply"
    assert (lib / "cube_h40mm_h50mm.ply").exists()
    assert abs(mesh.info(lib / "cube_h40mm_h50mm.ply")["size_mm"][2] - 50) < 0.5

    # guard 3: a silent model after its tools gets one nudge, then it speaks
    seq[:] = [
        msg(
            tool_calls=[{"id": "c1", "function": {"name": "fiche", "arguments": "{}"}}],
            content=None,
        ),
        msg(content="   "),
        msg(content="La pièce fait 20 mm de côté : 40 puis 50 mm de haut."),
    ]

    r = client.post(
        "/lab/api/models/cube_h40mm_h50mm.ply/assistant", json={"message": "sa taille ?"}
    )
    d = r.json()
    assert r.status_code == 200
    assert d["reply"].startswith("La pièce fait 20 mm")
    assert choices[-1] == "none"


@pytest.mark.slicing
def test_the_aI_picks_the_slice_settings(web, monkeypatch):
    """slice-brain: the brain reads the part and decides the slicing settings; only valid choices survive."""
    from elegoo_lab import assistant

    client, lib = web
    trimesh.creation.box((20, 20, 20)).export(lib / "cube.stl")
    monkeypatch.setattr(assistant, "moteur", lambda: "cli")
    monkeypatch.setattr(assistant, "cli_bin", lambda: "/tmp/bin/vibe")

    text = json.dumps(
        {
            "reponse": {
                "qualite": "0.16mm Optimal",
                "remplissage": 25,
                "supports": "aucun",
                "reglages": {"couture": "arriere", "cle_hors_profil": 3, "parois": 99},
                "usage": "fonctionnel",
                "rotate": None,
                "explication": "Pièce simple : 0,16 mm et parois épaisses suffisent.",
            }
        },
        ensure_ascii=False,
    )

    class Ok:
        returncode = 0
        stderr = ""
        stdout = json.dumps(
            [{"role": "assistant", "type": "message", "content": [{"type": "text", "text": text}]}]
        )

    captured = {}

    def fake_run(cmd, **kw):
        captured["prompt"] = cmd[cmd.index("-p") + 1]
        captured["system"] = open(cmd[cmd.index("--system-prompt-file") + 1]).read()
        return Ok()

    monkeypatch.setattr(assistant.subprocess, "run", fake_run)
    r = client.post(
        "/lab/api/models/cube.stl/slice-brain", json={"quality": "0.20mm Standard", "infill": 15}
    )
    assert r.status_code == 200
    d = r.json()
    assert d["qualite"] == "0.16mm Optimal"
    assert d["remplissage"] == 25
    assert d["supports"] == "aucun"
    assert d["reglages"] == {"couture": "arriere"}  # unknown key and out-of-range number dropped
    assert d["usage"] == "fonctionnel"
    assert "explication" in d
    assert '"taille_mm"' in captured["prompt"]  # the brain sees the part's sheet
    assert "TRANCHEUR" in captured["system"]
    assert "--resume" not in captured["prompt"]

    # no CLI configured: a clear error, not a crash
    monkeypatch.setattr(assistant, "cli_bin", lambda: None)
    assert (
        client.post(
            "/lab/api/models/cube.stl/slice-brain", json={"quality": "0.20mm Standard"}
        ).status_code
        == 422
    )


def test_the_assistant_journals_live_events(web, monkeypatch):
    """The streaming route: the brain's activity goes out as server-sent events, and the ordinary result lands in the last one."""
    from elegoo_lab import assistant

    client, lib = web
    trimesh.creation.box((20, 20, 20)).export(lib / "b.stl")
    monkeypatch.setattr(assistant, "moteur", lambda: "cli")
    monkeypatch.setattr(assistant, "cli_bin", lambda: "/tmp/bin/vibe")

    def fake_chat(name, message, history=None, conversation="", emit=None):
        assert emit is not None  # live mode: events go out through emit
        emit({"type": "outil", "outil": "fiche"})
        emit({"type": "cli", "cible": "mcp_blender.get_scene_info"})
        return {"reply": "Voilà.", "file": name, "outils": ["fiche"]}

    monkeypatch.setattr(assistant, "chat", fake_chat)
    r = client.post("/lab/api/models/b.stl/assistant/stream", json={"message": "décris-la"})
    assert r.status_code == 200
    assert "text/event-stream" in r.headers["content-type"]
    events = [json.loads(L[6:]) for L in r.text.splitlines() if L.startswith("data: ")]
    assert [e["type"] for e in events] == ["outil", "cli", "final"]
    assert events[0]["outil"] == "fiche"
    assert events[1]["cible"] == "mcp_blender.get_scene_info"
    assert events[-1]["reply"] == "Voilà."
    assert events[-1]["outils"] == ["fiche"]


@pytest.mark.slicing
def test_web_preview_slice_and_jobs(web):
    from elegoo_lab import slicer

    client, lib = web
    trimesh.creation.box((20, 20, 20)).export(lib / "c.stl")
    assert client.get("/lab/api/models/c.stl/colors").json()["colours"]
    glb = client.get("/lab/api/models/c.stl/preview.glb")
    assert glb.status_code == 200
    assert glb.content[:4] == b"glTF"
    assert client.get("/lab/api/jobs").json()[0]["state"] == "error"  # interrupted job reported
    assert client.get("/lab/api/setup").json()["tests"]
    if not (slicer.TOOLS / "squashfs-root" / "AppRun").exists():
        pytest.skip("slicer non installé")
    r = client.post("/lab/api/models/c.stl/prepare-print", json={"advanced": {"parois": 3}}).json()
    g = (lib / r["gcode"][0]).read_text(errors="ignore")
    assert "; thumbnail begin 144x144" in g
    assert "; curr_bed_type = Textured PEI Plate" in g
    assert "; wall_loops = 3" in g
    bad = client.post("/lab/api/models/c.stl/prepare-print", json={"advanced": {"parois": 99}})
    assert bad.status_code == 422
    assert "parois" in bad.json()["detail"].lower()


def test_parametric_parts_are_closed_and_validated(tmp_path, monkeypatch):
    from pathlib import Path

    from elegoo_lab import colors, config, mesh, parametric

    if not Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf").exists():
        pytest.skip("DejaVuSans-Bold font not available")
    monkeypatch.setattr(config, "MODELS_DIR", tmp_path)
    for key in parametric.KINDS:
        p = parametric.create(key, {})
        info = mesh.info(p)
        assert info["watertight"] and info["fits_bed"], key
    label = parametric.create("etiquette", {"texte": "Léa"})
    assert len(colors.analyze(label)["colours"]) == 2  # plate + text in two colours
    with pytest.raises(ValueError):
        parametric.create("boite", {"longueur": 500})  # out of range
    with pytest.raises(ValueError):
        parametric.create("organiseur", {"longueur": 30, "cases_x": 12})  # cells too small


def test_phone_access_needs_the_code(web, monkeypatch):
    from fastapi.testclient import TestClient

    from elegoo_lab import access, app as app_mod

    client, lib = web
    code = access.ensure_code()
    assert code
    assert access.ensure_code() is None
    assert "code_hash" in config.CONFIG_FILE.read_text()
    assert code not in config.CONFIG_FILE.read_text()  # only the hash is stored
    phone = TestClient(app_mod.create_app(lan=True, port=8787), client=("192.168.1.42", 5000))
    page = phone.get("/lab/", follow_redirects=False)
    assert page.status_code == 303
    assert page.headers["location"] == "/lab/login.html"
    assert phone.get("/lab/login.html").status_code == 200
    assert phone.get("/lab/api/models").status_code == 401
    assert phone.post("/print/pause").status_code == 401
    for _ in range(access.MAX_FAILS):
        assert phone.post("/lab/api/login", json={"code": "nope"}).status_code == 403
    assert (
        phone.post("/lab/api/login", json={"code": code}).status_code == 429
    )  # guessing is throttled
    other = TestClient(app_mod.create_app(lan=True, port=8787), client=("192.168.1.43", 5000))
    ok = other.post("/lab/api/login", json={"code": code})
    assert ok.status_code == 200
    assert "HttpOnly" in ok.headers["set-cookie"]
    assert "SameSite=Strict" in ok.headers["set-cookie"]
    assert other.get("/lab/api/models").status_code == 200  # session cookie kept
    assert other.get("/lab/api/phone").json()["qr"].lstrip().startswith("<?xml")
    access.set_code("4321")  # new code ends old sessions
    assert other.get("/lab/api/models").status_code == 401
    local = TestClient(app_mod.create_app(lan=True, port=8787), client=("127.0.0.1", 5000))
    assert local.get("/lab/api/models").status_code == 200  # this PC: no code


async def test_alerts_follow_a_print(tmp_path, monkeypatch):
    from elegoo_lab import alerts

    monkeypatch.setattr(config, "MODELS_DIR", tmp_path)
    monkeypatch.setattr(config, "CONFIG_FILE", tmp_path / "config.toml")

    async def snap():
        return b"\xff\xd8jpeg\xff\xd9"

    w = alerts.Watcher(lambda: None, snap)
    for ps, prog, cc2 in [
        (0, 0, {}),
        (13, 0, {}),
        (13, 40, {}),
        (6, 40, {"filament_detect_enable": 1, "filament_detected": 0}),
        (13, 41, {}),
        (13, 99, {}),
        (0, 0, {}),
    ]:
        w.observe(ps, prog, "chat.gcode", cc2)
    await asyncio.sleep(0.05)  # photo task
    seen = [e["kind"] for e in w.events]
    assert seen == ["debut", "filament", "reprise", "fin"]
    assert w.events[-1].get("photo")
    assert (alerts.photos_dir() / w.events[-1]["photo"]).read_bytes().startswith(b"\xff\xd8")
    w.observe(13, 0, "b.gcode", {})
    w.observe(13, 30, "b.gcode", {})
    w.observe(8, 30, "b.gcode", {})
    w.observe(13, 0, "c.gcode", {})
    w.observe(14, 10, "c.gcode", {"exception_status": [501]})
    assert [e["kind"] for e in w.events[-4:]] == ["debut", "arret", "debut", "erreur"]
    assert "501" in w.events[-1]["detail"]
    assert [e["kind"] for e in alerts.Watcher(lambda: None).events] == [
        e["kind"] for e in w.events
    ]  # kept on disk


def test_alert_when_the_plate_is_cold(tmp_path, monkeypatch):
    from elegoo_lab import alerts

    monkeypatch.setattr(config, "MODELS_DIR", tmp_path)
    monkeypatch.setattr(config, "CONFIG_FILE", tmp_path / "config.toml")
    w = alerts.Watcher(lambda: None)
    for ps, prog in [(0, 0), (13, 0), (13, 99), (0, 0)]:
        w.observe(ps, prog, "chat.gcode", {})
    assert w.events[-1]["kind"] == "fin"
    assert "35" in w.events[-1]["detail"]
    w.cool(None)
    w.cool(52.0)
    assert w.events[-1]["kind"] == "fin"  # still hot, or no reading: wait
    w.cool(33.6)
    assert w.events[-1]["kind"] == "froid"
    assert "34 °C" in w.events[-1]["detail"]
    w.cool(30.0)
    assert sum(e["kind"] == "froid" for e in w.events) == 1  # said once
    w2 = alerts.Watcher(lambda: None)
    w2.events = [e for e in w.events if e["kind"] == "fin"]  # restarted after "fin", before "froid"
    w2.observe(0, 0, "", {})
    w2.cool(30.0)
    assert w2.events[-1]["kind"] == "froid"  # restarted while it cooled: still told
    w.observe(13, 0, "b.gcode", {})
    w.observe(8, 30, "b.gcode", {})
    w.cool(20.0)
    assert w.events[-1]["kind"] == "arret"  # a stopped print: no part to take


async def test_camera_feed_gives_whole_pictures():
    from elegoo_lab import camfeed

    class Relay:  # pycentauri's relay: raw byte chunks, cut anywhere
        async def subscribe(self):
            async def chunks():
                data = b"--b\r\n" + b"\xff\xd8one\xff\xd9" + b"\r\n--b\r\n" + b"\xff\xd8two\xff\xd9"
                for i in range(0, len(data), 5):
                    yield data[i : i + 5]
                    await asyncio.sleep(0.01)
                await asyncio.sleep(10)

            return "multipart/x-mixed-replace", chunks()

    f = camfeed.CameraFeed(Relay())
    seq, jpeg = await f.next(0)
    assert jpeg == b"\xff\xd8one\xff\xd9"
    seq2, jpeg2 = await f.next(seq)
    assert (seq2, jpeg2) == (seq + 1, b"\xff\xd8two\xff\xd9")  # the next one, whole
    f.task.cancel()


async def test_camera_feed_detects_a_frozen_stream_and_restarts():
    from elegoo_lab import camfeed

    class Relay:  # the same picture over and over, like a firmware-frozen stream
        async def subscribe(self):
            async def chunks():
                for _ in range(12):
                    yield b"\xff\xd8same\xff\xd9"
                    await asyncio.sleep(0.01)
                await asyncio.sleep(60)

            return "multipart/x-mixed-replace", chunks()

    f = camfeed.CameraFeed(Relay())
    seq = 0
    for _ in range(11):  # the first picture only starts the count
        got = await f.next(seq)
        assert got is not None
        seq = got[0]
    assert f.same >= 10
    assert f.frozen  # R1.6: a frozen stream is detected
    await f.restart()
    assert f.restarts == 1
    assert f.same == 0
    if f.task is not None:
        f.task.cancel()


def test_camera_frozen_is_reported_once_until_it_recovers(tmp_path, monkeypatch):
    from elegoo_lab import alerts, config

    monkeypatch.setattr(config, "CONFIG_FILE", tmp_path / "config.toml")
    w = alerts.Watcher(lambda: None)
    w.observe(0, 0, "", {})  # idle: no print running
    w.camera_frozen()
    assert w.events[-1]["kind"] == "camera"
    w.camera_frozen()
    assert sum(e["kind"] == "camera" for e in w.events) == 1  # said once
    w.camera_ok()
    w.camera_frozen()
    assert sum(e["kind"] == "camera" for e in w.events) == 2  # a later freeze is reported again


def test_camera_endpoint_restarts_the_stream_when_no_picture(
    tmp_path, monkeypatch, fake_printer_env
):
    """R1.6: no new picture -> the stream is restarted once, the watcher warned, then 503."""
    from fastapi.testclient import TestClient

    from elegoo_lab import app as app_mod, camfeed, config

    class DeadRelay:  # camera away: the subscription fails at once
        async def subscribe(self):
            raise RuntimeError("caméra éteinte")

    monkeypatch.setattr(config, "CONFIG_FILE", tmp_path / "config.toml")
    monkeypatch.setattr(camfeed, "WAIT_S", 0.05)  # do not wait the full 3 s twice
    app = app_mod.create_app(enable_control=True)
    with TestClient(app) as client:
        feed = camfeed.CameraFeed(DeadRelay())
        client.app.state.camfeed = feed  # replace the live one: this camera gives nothing
        r = client.get("/lab/api/camera?after=0")
        assert r.status_code == 503
        assert feed.restarts == 1  # the stream was restarted once before answering
        w = client.app.state.watcher
        assert any(e["kind"] == "camera" for e in w.events)  # the watcher warned
        if feed.task is not None:
            feed.task.cancel()


def test_section_for_the_tablet(tmp_path):
    from elegoo_lab import coupe

    g = ["M83", ";TYPE:Outer wall"]
    for i, z in enumerate(
        (0.2, 0.4, 0.6)
    ):  # three layers of a 10 mm square, the last one in colour 1
        g += [
            f";Z:{z}",
            f"G1 Z{z}",
            "T1" if i == 2 else "T0",
            "G1 X0 Y0 F3000",
            "G1 X10 Y0 E1",
            "G1 X10 Y10 E1",
            "G1 X0 Y10 E1",
            "G1 X0 Y0 E1",
        ]
    f = tmp_path / "carre.gcode"
    f.write_text("\n".join(g) + "\n; filament_colour = #FF0000;#00FF00\n")
    d = coupe.coupe(f, 2)
    assert d["layer"] == 2
    assert d["layers"] == [0.2, 0.4, 0.6]
    assert d["box"] == [0, 0, 10, 10]
    assert len(d["section"]) == 16
    assert d["tools"] == [0, 0, 0, 0]
    assert [r[2] for r in d["front"][2]] == [1]
    assert d["front"][0][0][:2] == [0, 9]
    assert "front" not in coupe.coupe(f, 3, front=False)


def test_colours_now_and_next(web):
    from types import SimpleNamespace as NS

    from elegoo_lab import suivi_couleurs

    client, lib = web
    g = ["M6211 A1 L200 T0", "M73 P0 R30"]
    for z, tools in ((0.2, []), (0.4, [1, 2]), (0.6, [0])):  # layer 2 holds two changes
        g += [f";Z:{z}", f"M73 P0 R{int(30 - z * 20)}"] + [f"M6211 T{t} L60" for t in tools]
    f = lib / "noel_0.20mm_PLA.gcode"
    f.write_text("\n".join(g) + "\n; filament_colour = #008755;#E9E9E7;#D22630\n")
    p = suivi_couleurs.plan(f, 2, active=1)  # white engaged: red comes next, in this layer
    assert p["tool"] == 1
    assert [n["tool"] for n in p["next"]] == [2, 0]
    assert p["left"] == 2
    assert p["total"] == 3
    assert [n["tool"] for n in suivi_couleurs.plan(f, 2)["next"]] == [
        0
    ]  # no CANVAS: the layer's changes are done
    # purge still to come per tool, as the firmware counts it (L under 23 mm rounded up, +6 mm): white is done
    assert [(x["tool"], x["left"], x["count"], x["left_m"], x["total_m"]) for x in p["purge"]] == [
        (0, 1, 2, 0.066, 0.272),
        (1, 0, 1, 0.0, 0.066),
        (2, 1, 1, 0.066, 0.066),
    ]

    async def status():
        return NS(filename="/local/" + f.name, print_info=NS(current_layer=2))

    async def canvas():
        return NS(
            raw={
                "canvas_info": {
                    "active_tray_id": 2,
                    "canvas_list": [
                        {
                            "canvas_id": 0,
                            "tray_list": [
                                {
                                    "tray_id": i,
                                    "status": 1,
                                    "filament_color": c,
                                    "filament_type": "PLA",
                                }
                                for i, c in enumerate(["#077747", "#FFFFFF", "#F72221"])
                            ],
                        }
                    ],
                }
            }
        )

    client.app.state.manager = NS(printer=NS(status=status, canvas_status=canvas))
    from elegoo_lab import stock

    data = stock.load()
    data["prints"][f.name] = {"per_m": [1, 1, 1], "route": {"0": 1, "1": 2, "2": 0}}
    stock.save(data)
    d = client.get("/lab/api/couleurs").json()
    # tray 2 engaged = tool 1 by the launch route; tool 2 is in tray 0, tool 0 in tray 1
    assert d["maintenant"]["tool"] == 1
    assert d["maintenant"]["bobine"] == 3
    assert d["maintenant"]["hex"] == "#F72221"
    assert [(n["tool"], n["bobine"], n["couche"]) for n in d["suivants"]] == [(2, 1, 2), (0, 2, 3)]
    assert [(x["bobine"], x["reste"], x["total"]) for x in d["purge"]] == [
        (2, 1, 2),
        (3, 0, 1),
        (1, 1, 1),
    ]


def test_english_dictionary_and_server_translation():
    import json
    import re

    from elegoo_lab import i18n

    d = json.loads(i18n.DICT.read_text())
    assert len(d["exact"]) > 1000
    assert len(d["patterns"]) > 100
    for fr, en in d["patterns"]:
        re.compile("^" + re.escape(fr).replace(r"\{\}", "(.*?)") + "$")  # every pattern is valid
        n = fr.count("{}")
        assert all(
            1 <= int(k) <= n for k in re.findall(r"\{(\d+)\}", en)
        ), fr  # numbered slots exist
        assert en.count("{}") <= n, fr  # never more values than captured
    assert i18n.tr("Impression terminée", "en") == "Print finished"
    assert i18n.tr("Impression terminée", "fr") == "Impression terminée"
    assert i18n.tr("Consigne Buse", "en") == "Target Nozzle"  # pieces translated too
    assert i18n.tr("3 fichiers supprimés", "en") == "3 files deleted"
    assert i18n.tr("1 fichier supprimé", "en") == "1 file deleted"  # empty plural mark
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
    san = (
        x509.load_pem_x509_certificate(crt.read_bytes())
        .extensions.get_extension_for_class(x509.SubjectAlternativeName)
        .value
    )
    assert "192.168.1.42" in {str(a) for a in san.get_values_for_type(x509.IPAddress)}
    ssl.create_default_context(cadata=certs.ca_pem().decode()).load_cert_chain(
        crt, key
    )  # chain is coherent
    before = crt.read_bytes()
    assert certs.ensure(["192.168.1.42"]) == (crt, key)
    assert crt.read_bytes() == before
    web_app = app_mod.create_app(lan=True, port=8443, https=True, http_port=8787)
    plain = TestClient(web_app, base_url="http://192.168.1.42:8787", client=("192.168.1.50", 5000))
    r = plain.get("/lab/", follow_redirects=False)
    assert r.status_code == 307
    assert r.headers["location"] == "https://192.168.1.42:8443/lab/"
    ca = plain.get("/lab/ca.crt")
    assert ca.status_code == 200
    assert b"BEGIN CERTIFICATE" in ca.content
    assert b"PRIVATE" not in ca.content
    phone = TestClient(web_app, base_url="https://192.168.1.42:8443", client=("192.168.1.50", 5000))
    for path in (
        "/lab/manifest.webmanifest",
        "/lab/sw.js",
        "/lab/offline.html",
        "/lab/icons/icon-192.png",
    ):
        assert phone.get(path).status_code == 200, path  # installable before login
    assert phone.get("/lab/manifest.webmanifest").json()["display"] == "standalone"
    ok = phone.post("/lab/api/login", json={"code": code})
    assert "Secure" in ok.headers["set-cookie"]
    info = TestClient(web_app, client=("127.0.0.1", 5000)).get("/lab/api/phone").json()
    assert info["url"].startswith("https://")
    assert info["ca_url"].endswith(":8787/lab/ca.crt")


def test_advisor_spots_what_ruins_prints(tmp_path):
    from elegoo_lab import advisor

    def save(m, name):
        m.export(tmp_path / name)
        return tmp_path / name

    def keys(p, **kw):
        return {w["key"] for w in advisor.analyze(p, **kw)["warnings"]}

    assert keys(save(trimesh.creation.box((20, 20, 20)), "cube.stl")) == set()
    base = trimesh.creation.box((30, 30, 3))
    base.apply_translation((0, 0, 1.5))
    fin = trimesh.creation.box((30, 0.5, 20))
    fin.apply_translation((0, 0, 13))
    assert "fin" in keys(save(trimesh.util.concatenate([base, fin]), "ailette.stl"))
    stem = trimesh.creation.box((10, 10, 20))
    stem.apply_translation((0, 0, 10))
    top = trimesh.creation.box((40, 40, 4))
    top.apply_translation((0, 0, 22))
    tee = save(trimesh.util.concatenate([stem, top]), "champignon.stl")
    assert "surplombs" in keys(tee)
    assert "surplombs" not in keys(tee, supports=True)
    w = next(w for w in advisor.analyze(tee)["warnings"] if w["key"] == "surplombs")
    assert w["fix"] == {"supports": "arbre"}
    ball = save(trimesh.creation.icosphere(subdivisions=3, radius=15), "boule.stl")
    assert "adherence" in keys(ball)
    assert "adherence" not in keys(ball, brim=True)


def test_spool_stock_and_costs(tmp_path, monkeypatch):
    from elegoo_lab import alerts, stock

    monkeypatch.setattr(config, "MODELS_DIR", tmp_path)
    monkeypatch.setattr(config, "CONFIG_FILE", tmp_path / "config.toml")
    assert abs(stock.grams(1.0) - 2.98) < 0.02  # 1 m of 1.75 mm PLA ≈ 3 g
    trays = [
        {"tray_id": i, "color": c, "type": "PLA", "code": f"R{i}", "filament_name": f"PLA {i}"}
        for i, c in enumerate(["#E53935", "#FFFFFF"])
    ]
    assert stock.sync(trays) == []  # first sight: no alert
    stock.set_tray(1, restant_g=150, prix_kg=25)
    u = stock.record_slice("chat.gcode", [10.0, 30.0], [0.5, 0.5])
    assert u["trays"][1]["manque"] is False
    assert abs(u["eur"] - (u["trays"][0]["eur"] + u["trays"][1]["eur"])) < 0.02
    stock.record_slice("gros.gcode", [0.0, 80.0])
    assert stock.check("gros.gcode")["manques"][0]["tray"] == 1  # 238 g needed, 150 g left
    w = alerts.Watcher(lambda: None)
    for ps, prog in [(0, 0), (13, 0), (13, 99), (0, 0)]:
        w.observe(ps, prog, "/local/chat.gcode", {})
    s = stock.summary()
    assert s["trays"][1]["restant_g"] < 60
    assert s["history"][0]["fichier"] == "chat.gcode"
    assert any(
        e["kind"] == "stock" and "Bobine 2" in e["detail"] for e in w.events
    )  # nearly empty warning
    before = s["trays"][0]["restant_g"]
    assert stock.consume("chat.gcode", 1.0, s["history"][0]["ref"]) == []  # counted once only
    assert stock.summary()["trays"][0]["restant_g"] == before
    left = stock.summary()["trays"][1]["restant_g"]
    trays[1]["code"] = "R9"  # another spool in tray 1
    assert [(t["tray"], t["remise"]) for t in stock.sync(trays)] == [(1, False)]
    assert stock.summary()["trays"][1]["restant_g"] == 1000
    assert stock.summary()["trays"][1]["question"]["remise"] is False  # "new, or already started?"
    trays[1]["code"] = "R1"  # the first one comes back
    assert [(t["tray"], t["remise"], t["restant_g"]) for t in stock.sync(trays)] == [
        (1, True, round(left))
    ]
    assert stock.summary()["trays"][1]["restant_g"] == left
    assert (
        stock.summary()["trays"][1]["question"]["remise"] is True
    )  # "the same one, or a new one?"
    stock.set_tray(1, nouvelle=True)  # the user says: a new one
    t1 = stock.summary()["trays"][1]
    assert t1["restant_g"] == t1["poids_g"]
    assert "question" not in t1
    stock.set_tray(1, restant_g=left)
    stock.set_tray(0, restant_g=300)
    trays[0]["color"], trays[1]["color"] = (
        trays[1]["color"],
        trays[0]["color"],
    )  # two spools swap trays
    trays[0]["code"], trays[1]["code"] = "R1", "R0"
    assert {t["tray"]: t["restant_g"] for t in stock.sync(trays)} == {0: round(left), 1: 300}
    assert stock.sync(trays[:1]) == []  # tray 1 emptied...
    trays[1]["pos"] = 2
    assert [
        (t["tray"], t["remise"]) for t in stock.sync([trays[0], {**trays[1], "tray_id": 2}])
    ] == [(2, True)]
    assert stock.summary()["trays"][2]["restant_g"] == 300  # ...its spool found again in tray 3
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
    monkeypatch.setattr(
        vision, "detect", lambda jpeg: [(0.9, (0.2, 0.2, 0.6, 0.6))] * 3 if failing["on"] else []
    )

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
    for layer in range(1, 41):  # 40 healthy layers: nothing to say
        w.observe(13, layer * 2, "dragon.gcode", {})
        await w._camera(layer)
    assert not paused
    assert not [e for e in w.events if e["kind"] in ("suspect", "rate")]
    failing["on"] = True  # spaghetti appears
    for layer in range(41, 60):
        await w._camera(layer)
        if paused:
            break
    assert paused
    assert w.events[-1]["kind"] == "rate"
    assert (alerts.photos_dir() / w.events[-1]["photo"]).exists()
    assert w.rec.meta["alertes"]
    assert w.rec.frames >= 40
    w.observe(6, 90, "dragon.gcode", {})
    w.observe(13, 90, "dragon.gcode", {})  # the user resumed: judged afresh
    assert not w.ai_paused
    assert w.pred.frames == 0
    w.observe(0, 0, "", {})  # stopped before the end
    await asyncio.sleep(0.5)
    for _ in range(50):
        if gallery.entries() and gallery.entries()[0]["issue"] != "en cours":
            break
        await asyncio.sleep(0.2)
    e = gallery.entries()[0]
    assert e["issue"] == "arretee"
    assert e["photo"]
    assert e["alertes"]
    if shutil.which("ffmpeg"):
        assert e["video"] == "timelapse.mp4"
        assert gallery.file(e["id"], "timelapse.mp4").stat().st_size > 1000
    assert not (gallery.root() / e["id"] / "frames").exists()
    with pytest.raises(FileNotFoundError):
        gallery.file(e["id"], "../meta.json")


def test_failure_model_on_simulator_frame():
    from elegoo_lab import vision

    if not vision.model_ready():
        pytest.skip("modèle IA non installé")
    s = sim.Sim()
    s.s.update(status=sim.PRINTING, progress=50)
    assert sum(c for c, _ in vision.detect(s.camera_frame())) < 0.3  # a clean print looks clean


def test_web_forms_reach_the_server(web):
    client, lib = web
    r = client.post("/lab/api/bobines/1", json={"restant_g": 420, "prix_kg": 24.5})
    assert r.status_code == 200
    assert r.json()["restant_g"] == 420
    assert r.json()["prix_kg"] == 24.5
    assert client.post("/lab/api/bobines/1", json={"restant_g": 99999}).status_code == 422
    r = client.post("/lab/api/surveillance", json={"pause_auto": True, "sensibilite": 1.5})
    assert r.status_code == 200
    assert r.json()["pause_auto"] is True
    assert r.json()["sensibilite"] == 1.5
    assert client.post("/lab/api/surveillance", json={"sensibilite": 9}).status_code == 422
    r = client.post("/lab/api/lancement", json={"bedlevel_force": True, "print_layout": "B"})
    assert r.status_code == 200
    assert r.json() == {**r.json(), "bedlevel_force": True, "print_layout": "B"}
    assert client.post("/lab/api/lancement", json={"print_layout": "Z"}).status_code == 422
    assert client.get("/lab/api/lancement").json()["print_layout"] == "B"


async def test_start_sends_the_spool_map(printer, tmp_path, monkeypatch):
    from elegoo_lab import launch

    monkeypatch.setattr(config, "CONFIG_FILE", tmp_path / "config.toml")
    g = tmp_path / "deux.gcode"
    g.write_text(
        "; HEADER_BLOCK_START\n; filament used [mm] = 1200.00, 0.00, 340.50\n; HEADER_BLOCK_END\nG1 X1\n"
        "; filament_colour = #008755;#E9E9E7;#F2A900\n; filament_type = PLA;PLA;PETG\n"
    )
    tools = launch.gcode_colours(g)
    assert [t["t"] for t in tools] == [0, 2]
    assert tools[1]["type"] == "PETG"
    canvas = (await printer.canvas_status()).raw
    plan = launch.plan(g, canvas)
    # green file colour is on the CANVAS's green spool, gold on the gold one, whatever their positions
    by_t = {m["t"]: m["tray_id"] for m in plan["slot_map"]}
    trays = {t["tray_id"]: t["colour"] for t in plan["trays"]}
    assert trays[by_t[0]] == "#008755"
    assert trays[by_t[2]] == "#F2A900"
    payload = launch.params(g.name, {"bedlevel_force": True}, plan["slot_map"])
    assert payload["config"]["bedlevel_force"] is True
    assert payload["config"]["slot_map"][0]["canvas_id"] == 0
    assert (await printer._cc2_request(1020, payload))["error_code"] == 0
    await printer.stop()
    await asyncio.sleep(0.3)
    bad = launch.params(g.name, {}, [{"t": 0, "tray_id": 7}])
    from pycentauri.client import PrinterError

    with pytest.raises(PrinterError, match="error_code"):  # refused: no such spool
        await printer._cc2_request(1020, bad)


def test_printer_name_stays_ascii():
    """The printer's upload carries the file name in an HTTP header: ASCII only (a Chinese name
    crashed the send). ASCII names keep theirs so files on the printer stay reachable."""
    from elegoo_lab import launch

    assert launch.printer_name("cube_0.20mm_PLA.gcode") == "cube_0.20mm_PLA.gcode"
    cine = launch.printer_name("洋葱头宝宝_canvas_0.20mm_PLA.gcode")
    assert cine.isascii()
    assert cine.endswith(".gcode")
    assert len(cine) < 40
    assert launch.printer_name(cine) == cine  # deterministic: upload and start agree
    assert launch.printer_name("洋葱头宝宝.3mf.json") != launch.printer_name("洋葱头宝宝.gcode")
    # the whole round trip: upload under the translated name, then start names the same file
    payload = launch.params(launch.printer_name("洋葱头宝宝.gcode"), {}, [])
    assert payload["filename"] == launch.printer_name("洋葱头宝宝.gcode")
    assert payload["filename"].isascii()


@pytest.mark.slicing
def test_usage_puts_plastic_where_it_matters(tmp_path):
    from elegoo_lab import printprep, slicer, stock

    assert printprep.usage_overrides("decoratif", None)["sparse_infill_pattern"] == "lightning"
    assert "sparse_infill_density" not in printprep.usage_overrides(
        "decoratif", 30
    )  # the user's infill wins
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
        r = printprep.prepare_and_slice(
            src, usage=u, out_dir=tmp_path / u, quality=printprep.USAGES[u]["quality"]
        )
        grams[u] = sum(stock.grams(m) for m in r["per_filament_m"])
        g = (tmp_path / u / r["gcode"][0]).read_text(errors="ignore")
        assert (
            f"; sparse_infill_pattern = {printprep.USAGES[u]['overrides']['sparse_infill_pattern']}"
            in g
        )
        assert (
            '; filament_settings_id = "Elegoo PLA @ECC2"' in g
        )  # names the CC2 knows, or it refuses
        assert "; enable_filament_ramming = 0" in g  # ramming on -> error 1243
    assert grams["decoratif"] < 0.75 * grams["fonctionnel"]
    rows = printprep.compare(src, {"usage": "decoratif"})
    assert rows[0]["current"]
    assert {r["label"] for r in rows} >= {"Ton choix", "Rapide", "Solide", "Détaillé"}
    assert all("error" not in r and r["g"] > 0 for r in rows)


def test_cc2_knowledge_errors_materials_maintenance(tmp_path, monkeypatch):
    import time

    from elegoo_lab import alerts, errors, gallery, launch, maintenance

    monkeypatch.setattr(config, "MODELS_DIR", tmp_path)
    monkeypatch.setattr(config, "CONFIG_FILE", tmp_path / "config.toml")
    assert "capot" in errors.sentence([707])
    assert "code 707" in errors.sentence([707, 1231])
    assert "écran" in errors.sentence([4242])  # unknown code: look at the screen
    w = alerts.Watcher(lambda: None)
    w.observe(0, 0, "", {})
    w.observe(13, 0, "a.gcode", {})
    w.observe(13, 10, "a.gcode", {"exception_status": [707]})
    w.observe(13, 11, "a.gcode", {"exception_status": [707]})  # reported once
    assert [e["kind"] for e in w.events].count("anomalie") == 1
    w.observe(6, 12, "a.gcode", {"exception_status": [707, 1242]})
    assert w.events[-1]["kind"] == "filament"
    assert "1242" in w.events[-1]["detail"]
    for _ in range(10):  # the same picture over and over
        w._camera_health(b"same")
    w._camera_health(b"same")
    assert w.events[-1]["kind"] == "camera"
    warn = " ".join(
        launch.material_warnings([{"t": 0, "type": "TPU"}, {"t": 1, "type": "PLA-CF"}], [])
    )
    assert "TPU" in warn
    assert "abrasif" in warn
    assert (
        launch.material_warnings(
            [{"t": 0, "type": "PLA"}], [{"type": "PLA", "filament_name": "PLA Rouge"}]
        )
        == []
    )
    st = {t["id"]: t for t in maintenance.status()}
    assert not any(t["a_faire"] for t in st.values())
    rec = gallery.Recorder("long.gcode")  # 40 h of printing since then
    rec.meta["debut"] = st["plateau"]["fait"]
    rec.finish("terminee")
    meta = gallery.entries()[0]
    gallery.update(meta["id"], duree_s=40 * 3600)
    due = {t["id"] for t in maintenance.newly_due()}
    assert due == {"plateau"}
    assert maintenance.newly_due() == []
    time.sleep(1.1)
    assert not {t["id"]: t for t in maintenance.done("plateau")}["plateau"]["a_faire"]


def test_canvas_trays_in_both_formats():
    from elegoo_lab import spools

    sdk = {
        "canvas_info": {
            "canvas_list": [
                {
                    "canvas_id": 0,
                    "tray_list": [
                        {
                            "tray_id": 1,
                            "filament_type": "PETG",
                            "filament_color": "#ff0000",
                            "filament_code": "0x01",
                            "status": 2,
                        },
                        {
                            "tray_id": 0,
                            "filament_type": "",
                            "filament_color": "",
                            "status": 0,
                        },  # empty holder
                        {
                            "tray_id": 3,
                            "filament_type": "PLA",
                            "filament_color": "#00FF00",
                            "status": 1,
                        },
                        {
                            "tray_id": 4,
                            "filament_type": "PLA",
                            "filament_color": "javascript:alert(1)",
                            "status": 2,
                        },
                    ],
                }
            ]
        }
    }  # refused
    got = spools.loaded(sdk)
    assert [(t["pos"], t["tray_id"], t["type"], t["color"]) for t in got] == [
        (0, 1, "PETG", "#FF0000"),
        (2, 3, "PLA", "#00FF00"),
    ]
    old = {
        "canvas_list": [
            {"tray_list": [{"tray_id": 0, "type": "PLA", "color": "#123456", "status": 1}]}
        ]
    }
    assert spools.loaded(old)[0]["pos"] == 0
    assert spools.loaded(old)[0]["color"] == "#123456"


def test_orientations_advise_the_obvious(tmp_path):
    from elegoo_lab import orient

    # a sign: a wide plate with a thin mast on top, modelled lying on its back
    plate = trimesh.creation.box((60, 40, 3))
    plate.apply_translation((0, 0, 1.5))
    mast = trimesh.creation.box((4, 4, 50))
    mast.apply_translation((0, 0, 28))
    trimesh.util.concatenate([plate, mast]).export(tmp_path / "panneau.stl")
    out = {o["id"]: o for o in orient.orientations(tmp_path / "panneau.stl")}
    assert len(out) == 6
    assert all(o["image"].startswith("data:image/png;base64,") for o in out.values())
    assert out["debout"]["recommandee"]  # plate down, mast up: no support, big footing
    assert out["envers"]["contact"] < 30  # upside down it stands on the mast tip
    assert out["avant"]["surplomb"] > out["debout"]["surplomb"]
    assert out["gauche"]["size_mm"][2] == pytest.approx(
        60, abs=0.5
    )  # on its side: the plate's width is the height


def test_library_knows_each_file(tmp_path, monkeypatch):
    import base64
    import io

    from PIL import Image

    from elegoo_lab import library, stock

    monkeypatch.setattr(config, "MODELS_DIR", tmp_path)
    trimesh.creation.box((20, 20, 20)).export(tmp_path / "chat.stl")
    (tmp_path / "chat_canvas.3mf").write_bytes(b"x")  # a technical by-product
    buf = io.BytesIO()
    Image.new("RGB", (8, 8), (200, 30, 30)).save(buf, format="PNG")
    b64 = base64.b64encode(buf.getvalue()).decode()
    g = tmp_path / "chat_0.20mm_PLA.gcode"
    g.write_text(
        "; HEADER_BLOCK_START\n; estimated printing time (normal mode) = 1h 2m 3s\n; HEADER_BLOCK_END\n"
        f"; thumbnail begin 8x8 {len(b64)}\n; {b64}\n; thumbnail end\nG1 X1\n"
        "; filament_colour = #E53935;#FFFFFF\n; filament used [mm] = 100.0, 0.0\n; total filament used [g] = 3.2\n"
        "; print_settings_id = cc2lab 0.20mm Standard\n"
    )
    (tmp_path / "orphelin_0.20mm_PLA.gcode").write_text("G1 X1\n")
    library.record("orphelin_0.20mm_PLA.gcode", source="parti.stl")
    by = {e["name"]: e for e in library.listing()}
    assert by["chat_canvas.3mf"]["kind"] == "technique"
    assert by["chat.stl"]["prets"] == 1
    c = by["chat_0.20mm_PLA.gcode"]
    assert c["source"] == "chat.stl"
    assert c["temps"] == "1h 2m 3s"
    assert c["g"] == 3.2
    assert c["couleurs"] == ["#E53935"]
    assert c["qualite"] == "0.20mm Standard"
    assert library.thumbnail("chat_0.20mm_PLA.gcode") == buf.getvalue()  # the embedded picture
    assert library.thumbnail("chat.stl")[:4] == b"\x89PNG"  # a model gets a render
    stock.record_slice("chat_0.20mm_PLA.gcode", [1.0])
    new = library.rename("chat_0.20mm_PLA.gcode", "chat rouge")
    assert new == "chat rouge.gcode"
    assert "chat rouge.gcode" in stock.load()["prints"]
    assert library.rename("chat.stl", "minou") == "minou.stl"
    assert {e["name"]: e for e in library.listing()}["chat rouge.gcode"][
        "source"
    ] == "minou.stl"  # link kept
    with pytest.raises(ValueError):
        library.rename("minou.stl", "../evil")
    trimesh.creation.box((5, 5, 5)).export(tmp_path / "autre.stl")
    with pytest.raises(ValueError, match="existe déjà"):
        library.rename("minou.stl", "autre")  # no silent overwrite
    clean = {c["name"]: c["raison"] for c in library.cleanup()}
    assert "chat_canvas.3mf" in clean
    assert "orphelin_0.20mm_PLA.gcode" in clean
    assert "minou.stl" not in clean
    assert library.delete(list(clean)) == sorted(clean, key=list(clean).index)
    assert not (tmp_path / "chat_canvas.3mf").exists()
    assert (tmp_path / "minou.stl").exists()
    assert library.rename("minou.stl", "chaton.obj") == "chaton.obj.stl"  # the extension stays


def test_error_codes_follow_elegoos_own_list():
    from elegoo_lab import errors

    official = {
        101,
        102,
        103,
        104,
        108,
        304,
        401,
        701,
        702,
        703,
        704,
        705,
        706,
        707,
        801,
        802,
        803,
        902,
        1101,
        1103,
        1210,
        1211,
        1220,
        1231,
        1232,
        1241,
        1242,
        1243,
        1251,
        1252,
        1260,
        1262,
        1263,
        1264,
    }
    assert set(errors.CODES) == official  # exception_handler.h, ErrorCode namespace
    assert "grille" in errors.sentence([1101])
    assert "grille" in errors.sentence([1103])
    assert "Plus de filament" in errors.sentence([1211])
    for code in (605, 109, 1102, 1265):  # codes an earlier guide listed, absent from the firmware
        assert "écran" in errors.sentence([code])


def test_purge_counted_like_the_firmware():
    from elegoo_lab import slicer

    g = (
        b"M6211 A1 L200 T0 Q210 R210 S210\nM6211 T0 L0 M523\nG1 X1\n"
        b"M6211 T1 L12.5 M523\nM6211 T0 L40 M523\nM6211 T7 L40\nM6211 T1 L23\n"
    )
    out = slicer.firmware_purge_m(g, 2)
    # T0: 200+6 at the start, 40+6 later; the L0 line does nothing.  T1: 12.5 asked but 23 is the floor (+6), then 23+6.
    assert out == pytest.approx([(206 + 46) / 1000, (29 + 29) / 1000])


@pytest.mark.slicing
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
    assert "EXCLUDE_OBJECT" not in texts[1]  # one part: the profile as Elegoo ships it


def test_repair_closes_an_open_coloured_mesh_and_keeps_the_original(tmp_path, monkeypatch):
    import numpy as np

    from elegoo_lab import advisor, repair

    monkeypatch.setattr(config, "MODELS_DIR", tmp_path)
    box = trimesh.creation.box(extents=(20, 20, 20))
    box.visual = trimesh.visual.ColorVisuals(
        box, vertex_colors=np.tile([200, 30, 30, 255], (len(box.vertices), 1))
    )
    bad = trimesh.Trimesh(
        box.vertices, np.vstack([box.faces[:-2], box.faces[:1]]), process=False
    )  # 2 faces gone + 1 duplicated
    bad.visual = box.visual
    src = tmp_path / "boite.glb"
    bad.export(src)
    assert {w["key"] for w in advisor.analyze(src, height_mm=20)["warnings"]} >= {"ouvert"}
    fix = next(w for w in advisor.analyze(src, height_mm=20)["warnings"] if w["key"] == "ouvert")[
        "fix"
    ]
    assert fix == {"repair": True}
    before = src.read_bytes()
    d = repair.diagnose(src)  # where it is open, before repairing
    assert d["holes"] == 1
    assert d["open_edges"] > 0
    assert len(d["open"]) == d["open_edges"] * 6
    r = repair.repair(src)
    assert r["closed"]
    assert r["name"] == "boite_repare.glb"
    assert r["coloured"]
    assert r["holes_closed"] == 1
    note = advisor.analyze(tmp_path / r["name"], height_mm=20)["notes"][
        0
    ]  # the copy says what was done
    assert note["from"] == "boite.glb"
    assert "1 trou rebouché" in note["items"]
    assert advisor.analyze(src, height_mm=20)["notes"] == []
    assert src.read_bytes() == before  # the original is untouched
    assert mesh.info(tmp_path / r["name"])["watertight"]
    assert repair.repair(src)["name"] == "boite_repare2.glb"  # never overwrites a copy


def test_repair_refuses_to_destroy_a_hopeless_mesh(tmp_path):
    import numpy as np

    from elegoo_lab import repair

    rng = np.random.default_rng(0)
    soup = trimesh.Trimesh(
        rng.random((3000, 3)) * 20, rng.integers(0, 3000, (1500, 3)), process=False
    )
    src = tmp_path / "soupe.glb"
    soup.export(src)
    with pytest.raises(ValueError):
        repair.repair(src, tmp_path / "out.glb")


def test_hand_retouch_repaints_faces_beside_the_model(tmp_path, monkeypatch):
    import numpy as np

    from elegoo_lab import colors, library

    monkeypatch.setattr(config, "MODELS_DIR", tmp_path)
    box = trimesh.creation.box(extents=(20, 20, 20))
    box.unmerge_vertices()  # crisp colours: no vertex shared between faces
    box.visual = trimesh.visual.ColorVisuals(
        box, face_colors=np.array([[200, 0, 0, 255]] * 10 + [[0, 120, 0, 255]] * 2, np.uint8)
    )
    src = tmp_path / "boite.glb"
    box.export(src)
    before = src.read_bytes()
    assert len(colors.analyze(src)["colours"]) == 2
    n_red = int(colors.analyze(src)["colours"][0]["share"] > 50)
    green = next(
        c["hex"] for c in colors.analyze(src)["colours"] if c["hex"].upper().startswith("#00")
    )
    assert colors.save_retouch(src, {green: list(range(10))}) == 10  # every red face turns green
    assert len(colors.analyze(src)["colours"]) == 1  # caches saw the change
    assert src.read_bytes() == before  # the model itself is untouched
    assert colors.retouch_file(src).is_file()
    assert n_red in (0, 1)
    pv = colors.preview_glb(src)  # triangle i of the preview is face i
    assert len(pv.faces) == 12
    assert len(pv.vertices) == 36
    with pytest.raises(ValueError):
        colors.save_retouch(src, {green: [999]})
    with pytest.raises(ValueError):
        colors.save_retouch(src, {"rouge": [1]})
    new = library.rename("boite.glb", "cadeau.glb")  # the retouch follows its model
    assert colors.retouch_file(tmp_path / new).is_file()
    assert not colors.retouch_file(src).exists()
    assert len(colors.analyze(tmp_path / new)["colours"]) == 1
    colors.save_retouch(
        tmp_path / new, {}, erase=list(range(10))
    )  # erasing brings the colours back
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
    p = threemf.Part(
        "oignon",
        np.asarray(box.vertices, float),
        np.asarray(box.faces),
        1,
        [colors.encode_state(1 + i % 2) for i in range(faces)],
    )
    src = tmp_path / "oignon.3mf"
    threemf.write(
        threemf.Project([threemf.Object("oignon", [p])], ["#FF0000", "#00AA00"]),
        src,
        filaments=2,
        colours=["#FF0000", "#00AA00"],
    )
    a = colors.analyze(src)
    assert sorted(c["hex"] for c in a["colours"]) == ["#00AA00", "#FF0000"]
    before = np.asarray(colors.preview(src).visual.face_colors[1][:3])
    assert (before == [0, 170, 0]).all()  # face 1 starts green
    colors.save_retouch(src, {"#FF0000": [1]})  # it turns red by hand
    pv = colors.preview(src)  # the preview follows the retouch
    assert (pv.visual.face_colors[1][:3] == [255, 0, 0]).all()
    out = tmp_path / "oignon_canvas.3mf"  # the retouch goes along to the CANVAS
    colors.to_canvas(src, out, {c["index"]: c["slot"] for c in a["colours"]})
    pr2 = threemf.read(out)
    assert colors.paint_states(pr2.objects[0].parts[0].paint[1]) == {1}
    colors.save_retouch(src, {}, clear=True)
    pr3 = threemf.read(
        colors.to_canvas(src, out, {c["index"]: c["slot"] for c in a["colours"]}) and out
    )
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
    threemf.write(
        threemf.Project([threemf.Object("jaune", [p])], ["#FCE300"]),
        src,
        filaments=1,
        colours=["#FCE300"],
    )
    colors.save_retouch(src, {"#E9E9E7": list(range(10, 30))})
    a = colors.analyze(src)
    assert "#E9E9E7" in {c["hex"] for c in a["colours"]}
    pv = np.asarray(colors.preview(src).visual.face_colors)
    assert (pv[10][:3] == [233, 233, 231]).all()  # the painted faces stay white
    assert (pv[0][:3] == [252, 227, 0]).all()  # the rest keeps its yellow


def test_rebuild_drops_a_flat_sheet_and_closes_a_broken_mesh(tmp_path, monkeypatch):
    import numpy as np

    from elegoo_lab import advisor, repair

    monkeypatch.setattr(config, "MODELS_DIR", tmp_path)
    body = trimesh.creation.icosphere(subdivisions=4, radius=10)
    body.apply_translation([0, 0, 10])
    keep = np.random.default_rng(1).random(len(body.faces)) > 0.08  # 8 % of the faces missing
    sheet = trimesh.creation.box((60, 60, 0.01))  # the flat plate an AI leaves below
    sheet = trimesh.Trimesh(
        sheet.vertices, sheet.faces[sheet.face_normals[:, 2] > 0.5], process=False
    )
    sheet = sheet.subdivide().subdivide().subdivide()
    broken = trimesh.util.concatenate(
        [trimesh.Trimesh(body.vertices, body.faces[keep], process=False), sheet]
    )
    src = tmp_path / "abime.stl"
    broken.export(src)
    r = repair.repair(src)
    assert r["rebuilt"]
    assert r["closed"]
    assert r["sheets_removed"]
    out = trimesh.load(tmp_path / r["name"], force="mesh")
    assert out.is_watertight
    assert out.extents.max() < 25
    assert abs(out.volume - body.volume) / body.volume < 0.15  # the ball is whole again
    note = advisor.analyze(tmp_path / r["name"])["notes"][0]
    assert note["title"] == "Maillage reconstruit"
    assert any("Feuilles" in i for i in note["items"])


@pytest.mark.slicing
def test_own_spools_are_recognised_and_sliced(tmp_path, monkeypatch):

    from elegoo_lab import catalog, slicer, spools

    own = tmp_path / ".mes_bobines.json"
    own.write_text(
        json.dumps(
            {
                "profils": {
                    "PLA Silk Noël": {
                        "base": "PLA Silk",
                        "reglages": {"filament_max_volumetric_speed": "12"},
                    }
                },
                "bobines": [
                    {
                        "nom": "Silk Rouge Noël",
                        "couleur": "#D22630",
                        "matiere": "PLA",
                        "profil": "PLA Silk Noël",
                    },
                    {
                        "nom": "Silk Or",
                        "couleur": "#F2A900",
                        "matiere": "PLA",
                        "profil": "PLA Silk Noël",
                    },
                ],
            }
        )
    )
    monkeypatch.setattr(catalog, "_file", lambda: own)
    trays = spools.loaded(
        {
            "canvas_list": [
                {
                    "tray_list": [
                        {
                            "tray_id": 1,
                            "filament_color": "#FF0000",
                            "filament_type": "PLA",
                            "status": 2,
                        },  # red picked on screen
                        {
                            "tray_id": 2,
                            "filament_color": "#1E88E5",
                            "filament_type": "PLA",
                            "status": 2,
                        },  # a blue: not ours
                        {
                            "tray_id": 3,
                            "filament_color": "#E53935",
                            "filament_type": "PLA",
                            "filament_name": "PLA Matte",
                            "status": 2,
                        },
                        {
                            "tray_id": 4,
                            "filament_color": "#FFD700",
                            "filament_type": "PETG",
                            "status": 2,
                        },
                    ]
                }
            ]
        }
    )  # other material
    assert trays[0]["color"] == "#D22630"
    assert trays[0]["printer_color"] == "#FF0000"
    assert spools.filament_for(trays[0]) == "PLA Silk Noël"
    assert trays[0]["filament_name"] == "Silk Rouge Noël"
    assert [t.get("profile") for t in trays[1:]] == [None, None, None]
    assert "PLA Silk Noël" in slicer.filaments()
    src = tmp_path / "cube.stl"
    trimesh.creation.box((20, 20, 20)).export(src)
    g = slicer.slice_model(
        src, tmp_path / "out", filament=["PLA Silk Noël"], colours=["#D22630"]
    ).gcode[0]
    text = g.read_text(errors="ignore")
    assert g.name.isascii()
    assert "; filament_max_volumetric_speed = 12" in text
    assert '; filament_settings_id = "Elegoo PLA Silk @ECC2"' in text  # a name the CC2 knows


def test_specks_melt_into_their_surroundings_but_hand_paint_stays():
    import numpy as np

    from elegoo_lab import colors, threemf

    s = trimesh.creation.icosphere(subdivisions=4)
    lab = (s.triangles_center[:, 2] > 0).astype(int)  # two halves
    speck = np.argsort(s.triangles_center[:, 2])[
        :3
    ]  # around the bottom pole, far from the other half
    lab[speck] = 1  # a few faces of the other colour
    part = threemf.Part("s", np.asarray(s.vertices), np.asarray(s.faces))
    clean = colors._clean_labels(part, lab)
    assert (clean[speck] == 0).all()
    assert abs((clean == 1).mean() - (lab == 1).mean()) < 0.01  # the halves themselves stay
    part.locked = np.zeros(len(lab), bool)
    part.locked[speck] = True  # painted by hand: kept
    assert (colors._clean_labels(part, lab)[speck] == 1).all()


def test_model_repainted_with_the_loaded_spools(tmp_path):
    from elegoo_lab import colors, spools

    cube = trimesh.creation.box((20, 20, 20))
    cube.unmerge_vertices()
    cube.visual = trimesh.visual.ColorVisuals(
        cube, face_colors=[[150, 10, 10, 255]] * 6 + [[30, 110, 60, 255]] * 6
    )
    src = tmp_path / "rouge_vert.glb"
    cube.export(src)
    palette = ("#D22630", "#F2A900", None, "#008755")  # slot 3 empty
    a = colors.analyze(src, palette)
    assert a["palette"]
    assert {c["index"] for c in a["colours"]} == {1, 4}
    assert all(
        c["slot"] == c["index"] and c["hex"] == palette[c["index"] - 1] for c in a["colours"]
    )
    out = colors.to_canvas(src, tmp_path / "c.3mf", {1: 1, 4: 4}, palette=palette)
    assert out["slot_colours"][0] == "#D22630"
    assert out["slot_colours"][3] == "#008755"
    trays = [{"color": "#D22630", "pos": 0, "type": "PLA", "filament_name": "Rouge"}]
    assert (
        "pas de bobine proche" in spools.far_colours([{"hex": "#0A3CC8", "share": 50.0}], trays)[0]
    )
    assert not colors.analyze(src)["palette"]  # without spools: the model's own colours


def test_assembly_takes_the_spools_colours(tmp_path):
    import zipfile

    from elegoo_lab import colorize, colors

    a, b = tmp_path / "a.stl", tmp_path / "b.stl"
    trimesh.creation.box((10, 10, 10)).export(a)
    trimesh.creation.box((10, 10, 10)).apply_translation((0, 0, 10)).export(b)
    cols = ["#E9E9E7", "#D22630"]
    colorize.build_3mf(
        [(a, 1), (b, 2)], tmp_path / "x.3mf", colours=cols, flush=colors.flush_matrix(cols)
    )
    cfg = json.loads(zipfile.ZipFile(tmp_path / "x.3mf").read("Metadata/project_settings.config"))
    assert cfg["filament_colour"] == cols
    assert cfg["flush_volumes_matrix"] == [
        str(v) for v in colors.flush_matrix(cols)
    ]  # purge sized to each change


def test_name_added_inside_a_line_drawing(tmp_path):
    from pathlib import Path

    import manifold3d as mf
    import numpy as np

    from elegoo_lab import addtext, colors

    if not Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf").exists():
        pytest.skip("DejaVuSans-Bold font not available")
    ring = (mf.CrossSection.circle(40, 96) - mf.CrossSection.circle(37, 96)).extrude(
        2.0
    )  # a drawn circle, 2 mm
    m = ring.to_mesh()
    src = tmp_path / "cercle.stl"
    trimesh.Trimesh(np.asarray(m.vert_properties)[:, :3], np.asarray(m.tri_verts)).export(src)
    for font, angle in (("manuscrite", 0), ("manuscrite", 30), ("trait", 0)):
        r = addtext.add(src, "Noël", font=font, angle=angle, out=tmp_path / f"c{font}{angle}.3mf")
        assert r["pieces"] == 1
        assert 3 < r["capitales_mm"] < 40
        a = colors.analyze(tmp_path / r["name"])
        assert {c["index"] for c in a["colours"]} == {1, 2}  # model and text, two colours
    with pytest.raises(ValueError):
        addtext.add(src, "   ")


def test_bed_mesh_can_be_commented_out_of_the_start_gcode():
    from elegoo_lab import slicer

    g = b"G90\nM190 S65 A\nBED_MESH_CALIBRATE mesh_min=10,74 mesh_max=203,233 FROM_SLICER=1\nG28\n"
    out = slicer.without_bed_mesh(g)
    assert b"\nBED_MESH_CALIBRATE" not in out
    assert b"G28\n" in out
    assert out.count(b"\n") == g.count(b"\n")


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
        w.observe(13, 0, name, {})
        w.observe(13, 97, name, {})
        tasks.append({"task_name": name, "task_status": status, "end_time": int(time.time())})
        w.observe(0, 0, "", {})
        await asyncio.sleep(0.2)
    assert [(e["kind"], e["detail"].split(" :")[0]) for e in w.events] == [
        ("debut", "spatule.gcode"),
        ("fin", "spatule.gcode"),
        ("debut", "bac.gcode"),
        ("arret", "bac.gcode"),
    ]
    issues = {e["fichier"]: (e["issue"], e["progression"]) for e in gallery.entries()}
    assert issues == {"spatule.gcode": ("terminee", 100), "bac.gcode": ("arretee", 97)}


def test_restart_mid_print_carries_on_with_the_open_gallery_entry(tmp_path, monkeypatch):
    from elegoo_lab import gallery

    monkeypatch.setattr(config, "MODELS_DIR", tmp_path)
    old = gallery.Recorder("oublie.gcode")  # left "en cours" by a workshop stopped mid-print
    rec = gallery.Recorder("piece.gcode")
    rec.meta["debut"] -= 600
    rec.save()
    rec.add_frame(b"\xff\xd8x\xff\xd9")
    again = gallery.Recorder.resume("piece.gcode")
    assert again.id == rec.id
    assert again.frames == 1
    assert again.meta["debut"] == rec.meta["debut"]
    assert gallery.close_stale(gallery.stale(keep=again.id)) == 1
    issues = {e["fichier"]: e["issue"] for e in gallery.entries()}
    assert issues == {"oublie.gcode": "interrompue", "piece.gcode": "en cours"}
    assert old.id != rec.id


def test_unknown_printer_state_is_not_a_print(tmp_path, monkeypatch):
    """Seen on the real CC2 while it starts up: machine_status 9, mapped to 99 by pycentauri."""
    from elegoo_lab import alerts, gallery

    monkeypatch.setattr(config, "MODELS_DIR", tmp_path)
    monkeypatch.setattr(config, "CONFIG_FILE", tmp_path / "config.toml")
    w = alerts.Watcher(lambda: None)
    w.observe(99, 0, "", {})
    w.observe(0, 0, "", {})
    w.observe(99, 0, "", {})
    w.observe(0, 0, "", {})
    assert w.events == []
    assert w.rec is None
    assert gallery.entries() == []


def test_filament_is_taken_off_the_spool_that_fed_it(tmp_path, monkeypatch):
    """Seen on 2026-11-09: gold was T1 in the file but fed from tray 3; the count took it off tray 1."""
    from elegoo_lab import stock

    monkeypatch.setattr(config, "MODELS_DIR", tmp_path)
    stock.record_slice("ange.gcode", [0.0, 0.44, 0.84], [0.0, 0.1, 0.2])
    assert [t["tray"] for t in stock.check("ange.gcode", {1: 3, 2: 2})["trays"]] == [2, 3]
    stock.record_route("ange.gcode", {1: 3, 2: 2})
    stock.consume("ange.gcode", 1.0, "r1")
    left = {int(i): t["restant_g"] for i, t in stock.load()["trays"].items()}
    assert left[1] == left[0]
    assert left[3] < left[0]
    assert left[2] < left[0]


def test_model_preview_is_revalidated_not_downloaded_again(web):
    client, lib = web
    trimesh.creation.box((20, 20, 20)).export(lib / "cube.stl")
    r = client.get("/lab/api/models/cube.stl/preview.glb")
    assert r.status_code == 200
    assert r.headers["etag"]
    again = client.get(
        "/lab/api/models/cube.stl/preview.glb", headers={"If-None-Match": r.headers["etag"]}
    )
    assert again.status_code == 304
    assert not again.content
    other = client.get(
        "/lab/api/models/cube.stl/preview.glb?pal=%23FF0000",
        headers={"If-None-Match": r.headers["etag"]},
    )
    assert other.status_code == 200


def test_model_renamed_while_read_is_not_found_not_an_error(web, monkeypatch):
    from elegoo_lab import orient

    client, lib = web
    trimesh.creation.box((20, 20, 20)).export(lib / "cube.stl")

    def renamed(path, *a):  # the page renames the model while its positions are computed
        path.rename(lib / "autre.stl")
        raise FileNotFoundError(path)

    monkeypatch.setattr(orient, "orientations", renamed)
    r = client.get("/lab/api/models/cube.stl/orientations")
    assert r.status_code == 404
    assert "introuvable" in r.json()["detail"]

    def broken(path, *a):
        raise ValueError("maillage vide")

    monkeypatch.setattr(orient, "orientations", broken)
    assert (
        client.get("/lab/api/models/autre.stl/orientations").status_code == 422
    )  # a real failure stays one


def test_tailscale_name_goes_into_the_certificate(tmp_path, monkeypatch):
    import subprocess

    from cryptography import x509

    from elegoo_lab import access, certs

    monkeypatch.setattr(config, "ROOT", tmp_path)
    status = {
        "Self": {
            "Online": True,
            "TailscaleIPs": ["100.101.102.103", "fd7a::1"],
            "DNSName": "pc.tail1.ts.net.",
        }
    }
    monkeypatch.setattr(
        subprocess, "run", lambda *a, **k: subprocess.CompletedProcess(a, 0, json.dumps(status), "")
    )
    monkeypatch.setattr("shutil.which", lambda n: "/usr/bin/tailscale")
    ts = access.tailscale()
    assert ts == {"ip": "100.101.102.103", "name": "pc.tail1.ts.net"}
    crt, _ = certs.ensure(["192.168.1.70", ts["ip"]], [ts["name"]])
    san = (
        x509.load_pem_x509_certificate(crt.read_bytes())
        .extensions.get_extension_for_class(x509.SubjectAlternativeName)
        .value
    )
    assert "pc.tail1.ts.net" in san.get_values_for_type(x509.DNSName)
    assert {str(a) for a in san.get_values_for_type(x509.IPAddress)} >= {
        "192.168.1.70",
        "100.101.102.103",
    }
    before = crt.read_bytes()
    certs.ensure(["192.168.1.70"])  # Tailscale not up yet at boot: the certificate is kept
    assert crt.read_bytes() == before
    status["Self"]["Online"] = False
    assert access.tailscale() is None


def test_without_purge_turns_colour_changes_into_a_bare_switch(tmp_path):
    from elegoo_lab import slicer

    g = (
        b"M6211 A1 L200 T1 Q230 R230 S230\nT1\nM6211 T2 L14.7 M299 N299 Q230 R240 S230\nT2\n"
        b"M6211 T2 L0 M299\nT2\n"
    )
    out = slicer.without_purge(g)
    lines = out.split(b"\n")
    assert lines[0].startswith(b"M6211 A1")  # the start load keeps its purge
    assert lines[2].startswith(b"CANVAS_SWITCH_FILAMENT T=2")
    assert lines[4].startswith(b"M6211 T2 L0")  # same tool: untouched
    assert slicer.firmware_purge_m(out, 4)[2] == 0.0  # no purge left for the changed-to tool (T2)
    f = tmp_path / "a.gcode"
    f.write_bytes(out)
    assert slicer._header(f)["colour changes"] == "2"  # the L0 line counts as before


def test_a_failed_write_keeps_the_old_file(tmp_path, monkeypatch):
    import os

    f = tmp_path / "stock.json"
    config.write_atomic(f, '{"a": 1}')
    monkeypatch.setattr(os, "fsync", lambda fd: (_ for _ in ()).throw(OSError("disque plein")))
    with pytest.raises(OSError):
        config.write_atomic(f, '{"a": 2}')
    assert f.read_text() == '{"a": 1}'
    assert [p.name for p in tmp_path.iterdir()] == ["stock.json"]


def test_backup_copies_the_library_and_keeps_old_versions(tmp_path, monkeypatch):
    """Real rsync and git; ssh is a stand-in that runs the "remote" side in a local folder."""
    import os
    import shutil

    from elegoo_lab import sauvegarde

    if not shutil.which("rsync"):
        pytest.skip("rsync absent")
    far, bin_ = tmp_path / "serveur", tmp_path / "bin"
    far.mkdir(), bin_.mkdir()
    (bin_ / "ssh").write_text(
        f'#!/bin/sh\nwhile [ "$1" = "-o" ]; do shift 2; done\nshift\ncd {far} && exec sh -c "$*"\n'
    )
    (bin_ / "ssh").chmod(0o755)
    monkeypatch.setenv("PATH", f"{bin_}:{os.environ['PATH']}")
    (config.MODELS_DIR / "coeur.stl").write_text("v1")
    config.CONFIG_FILE.write_text('[printer]\nhost = "x"\n')
    assert sauvegarde.overdue().startswith("Aucune sauvegarde")
    sauvegarde.run("serveur")
    dest = far / sauvegarde.DEST
    assert (dest / "models" / "coeur.stl").read_text() == "v1"
    assert (dest / "config.toml").exists()
    assert (dest / "elegoo.bundle").stat().st_size > 0
    assert sauvegarde.overdue() is None
    assert sauvegarde.run("serveur", if_needed=True) == "sauvegarde du jour déjà faite"
    (config.MODELS_DIR / "coeur.stl").write_text("v2")
    os.utime(
        config.MODELS_DIR / "coeur.stl", (time.time() + 5,) * 2
    )  # rsync compares size and time: an edit an hour later
    sauvegarde.run("serveur")
    assert (dest / "models" / "coeur.stl").read_text() == "v2"
    assert [p.read_text() for p in (dest / "anciens").glob("*/models/coeur.stl")] == [
        "v1"
    ]  # the old version is kept
    (bin_ / "ssh").write_text(
        "#!/bin/sh\necho 'ssh: connect to host 192.168.1.48 port 22: No route to host' >&2\nexit 255\n"
    )
    with pytest.raises(RuntimeError, match="No route to host"):
        sauvegarde.run("serveur")
    assert sauvegarde.status()["erreur"].endswith("No route to host")
    assert sauvegarde.overdue() is None


def test_backup_to_a_usb_disk_never_fills_the_pc_disk(tmp_path, monkeypatch):
    import shutil

    from elegoo_lab import sauvegarde

    if not shutil.which("rsync"):
        pytest.skip("rsync absent")
    disk = tmp_path / "CLE"
    disk.mkdir()
    (config.MODELS_DIR / "coeur.stl").write_text("v1")
    with pytest.raises(
        RuntimeError, match="non branché"
    ):  # same disk as the library: an unplugged key's mount folder
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
    printed = {
        "coeur": old,
        "sapin": old,
        "etoile": time.time() - 86400,
        "lutin": old,
        "boule": old,
    }
    for g in [*printed, "renne"]:
        f = lib / f"{g}_0.20mm_PLA.gcode"
        f.write_text("; G-code\n")
        os.utime(f, (old, old))
    for i, (g, t) in enumerate(printed.items()):
        d = lib / ".galerie" / f"2026{i}_{g}"
        d.mkdir(parents=True)
        (d / "meta.json").write_text(
            json.dumps(
                {
                    "id": d.name,
                    "fichier": f"{g}_0.20mm_PLA.gcode",
                    "debut": t,
                    "issue": "en cours" if g == "boule" else "terminee",
                }
            )
        )
    gone = library.old_gcodes(keep={"sapin_0.20mm_PLA.gcode"})
    # sapin: in the queue · etoile: printed yesterday · lutin: no model left · renne: never printed · boule: printing
    assert gone == ["coeur_0.20mm_PLA.gcode"]
    library.delete(gone)
    assert not (lib / "coeur_0.20mm_PLA.gcode").exists()
    assert (lib / "coeur.stl").exists()


def test_terminal_tells_only_what_changed(tmp_path, monkeypatch):
    from elegoo_lab import alerts

    monkeypatch.setattr(config, "MODELS_DIR", tmp_path)
    monkeypatch.setattr(config, "CONFIG_FILE", tmp_path / "config.toml")
    w = alerts.Watcher(lambda: None)
    raw = {
        "TempOfNozzle": 25,
        "TempTargetNozzle": 0,
        "TempOfHotbed": 25,
        "TempTargetHotbed": 0,
        "CurrenCoord": "0,0,0.2",
        "PrintInfo": {"CurrentLayer": 0, "TotalLayer": 362, "PrintSpeedPct": 100},
        "_cc2": {"machine_status": 1, "sub_status": 0},
    }
    w.narrate(raw, 0)
    w.term.clear()
    w.narrate(raw, 0)
    assert not w.term  # nothing new, nothing said
    raw = {
        **raw,
        "TempTargetNozzle": 230,
        "PrintInfo": {**raw["PrintInfo"], "CurrentLayer": 1, "PrintSpeedPct": 160},
    }
    w.narrate(raw, 13)
    w.narrate({**raw, "TempOfNozzle": 229}, 13)
    w.narrate({**raw, "TempOfNozzle": 231}, 13)
    texts = [l["text"] for l in w.term]
    assert texts == [
        "État : impression",
        "Couche 1 / 362 · Z 0,20 mm",
        "Buse : consigne 230 °C",
        "Vitesse : 160 %",
        "Buse à 229 °C : consigne atteinte",
    ]
    w.emit("pause", "x.gcode")
    assert w.term[-1]["level"] == "warn"
    assert w.term[-1]["text"].startswith("Impression en pause")


def test_toolchange_reprime_no_longer_drops_a_blob():
    from elegoo_lab import slicer

    g = (
        b"M6211 A1 L200 T1 Q220 R220 S220\nT1\nG1 E6 F600\n"  # start load: its push stays
        b"G1 E-10 F1800\nM6211 T2 L34.9 M299 N299 Q220 R240 S220\nT2\nG1 X10 Y10 F30000\nG1 E10 F1800\n"
        b"G1 X12 Y10 E.5\n"
    )
    lines = slicer.without_toolchange_reprime(g).split(b"\n")
    assert lines[2] == b"G1 E6 F600"
    assert lines[3] == b"G1 E-10 F1800"  # the retract before the change is kept
    assert lines[7].startswith(b"G1 E1.7 F1800 ;")  # 10 mm pushed on the spot -> 1.7 mm
    assert lines[8] == b"G1 X12 Y10 E.5"
    same = b"G1 E-10 F1800\nM6211 T2 L0 M299\nT2\nG1 E10 F1800\n"  # same spool: nothing is reloaded
    assert slicer.without_toolchange_reprime(same) == same


def test_phone_alerts_topic(web):
    """Phone alerts: "on" makes a private ntfy topic, "off" clears it, a test needs it on."""
    client, _ = web
    assert client.get("/lab/api/alertes/telephone").json() == {"ntfy": None}
    assert client.post("/lab/api/alertes/telephone", json={"action": "test"}).status_code == 409
    url = client.post("/lab/api/alertes/telephone", json={"action": "on"}).json()["ntfy"]
    assert url.startswith("https://ntfy.sh/cc2-")
    assert len(url.rsplit("/", 1)[1]) == 24
    assert (
        client.post("/lab/api/alertes/telephone", json={"action": "on"}).json()["ntfy"] != url
    )  # never reused
    assert client.post("/lab/api/alertes/telephone", json={"action": "off"}).json() == {
        "ntfy": None
    }
    assert client.post("/lab/api/alertes/telephone", json={"action": "x"}).status_code == 422


def test_add_pauses(tmp_path):
    """PAUSE goes before the first layer above the asked height, never before layer 1, once per layer."""
    from elegoo_lab.printprep import add_pauses

    g = tmp_path / "p.gcode"
    g.write_text(
        "G28\n"
        + "".join(f";LAYER_CHANGE\n;Z:{z}\n;HEIGHT:0.2\nG1 X1 E1\n" for z in (0.2, 0.4, 0.6, 0.8))
    )
    placed = add_pauses(g, [0.5, 0.55, 0.1, 9])
    assert placed == [{"mm": 0.5, "z": 0.4, "layer": 3, "run": 1}]
    lines = g.read_text().splitlines()
    assert lines.count("PAUSE") == 1
    assert lines[lines.index("PAUSE") + 2] == ";Z:0.6"


def test_add_pauses_each_piece_of_a_piece_by_piece_print(tmp_path):
    """Pieces printed one at a time restart from the bed: every one pauses at its own height."""
    from elegoo_lab.printprep import add_pauses

    g = tmp_path / "p.gcode"
    g.write_text(
        "G28\n"
        + "".join(
            f";LAYER_CHANGE\n;Z:{z}\n;HEIGHT:0.2\nG1 X1 E1\n"
            for z in (0.2, 0.4, 0.6) + (0.2, 0.4, 0.6, 0.8)
        )
    )
    placed = add_pauses(g, [0.5])
    assert [p["run"] for p in placed] == [1, 2]
    assert [p["layer"] for p in placed] == [3, 3]
    assert g.read_text().count("PAUSE") == 2


def _piece_plate(tmp_path, name, gap_mm=10.0, extruders=(1, 2), heights=(20, 20)):
    """A plate 3MF of two cubes with the given gap, colours and heights (piece by piece in tests)."""
    import numpy as np

    from elegoo_lab import colorize, colors, threemf

    objs, x = [], 0.0
    for k, (e, h) in enumerate(zip(extruders, heights, strict=True)):
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
    threemf.write(
        threemf.Project(objs, cols),
        out,
        filaments=len(cols),
        colours=cols,
        flush=colors.flush_matrix(cols),
    )
    return out, cols


@pytest.mark.slicing
def test_piece_by_piece_groups_colours_and_checks_the_head_path(tmp_path):
    """«Ordre d'impression : pièce par pièce» sorts the pieces by colour, keeps the wipes' place, and
    asks for the CC2's own clearances: enough space between pieces, low enough pieces."""
    from elegoo_lab import colors, settings, slicer, threemf

    radius, height = slicer.clearances()
    out, _ = _piece_plate(
        tmp_path, "espaces", gap_mm=radius, extruders=(2, 1)
    )  # first piece wears slot 2
    conv = colors.to_canvas(out, tmp_path / "suite.3mf", {1: 1, 2: 2}, ordre="suite")
    assert conv["ordre"] == "suite"
    assert [o.name for o in threemf.read(tmp_path / "suite.3mf").objects] == [
        "cube1",
        "cube0",
    ]  # slot 1 first
    proche, _ = _piece_plate(tmp_path, "cote", gap_mm=10.0, extruders=(2, 1))
    with pytest.raises(ValueError, match="l'une de l'autre"):  # 10 mm apart: the head would hit one
        colors.to_canvas(proche, tmp_path / "trop_proche.3mf", {1: 1, 2: 2}, ordre="suite")
    out_meme, _ = _piece_plate(
        tmp_path, "jumeaux", gap_mm=radius, extruders=(1, 1)
    )  # same colours: layer by layer shares
    assert (
        colors.to_canvas(out_meme, tmp_path / "meme.3mf", {1: 1}, ordre="suite")["ordre"] == "meme"
    )
    out_haut, _ = _piece_plate(
        tmp_path, "haut", gap_mm=radius, extruders=(1, 2), heights=(height + 10, 20)
    )
    with pytest.raises(ValueError, match="de haut"):  # taller than the head can fly over
        colors.to_canvas(out_haut, tmp_path / "trop_haut.3mf", {1: 1, 2: 2}, ordre="suite")
    names = [c["name"] for c in settings.spec()["choices"]]
    assert "ordre" in names  # the choice reaches the web UI


@pytest.mark.slicing
def test_small_pieces_plate_leaves_room_for_the_prime_tower(tmp_path):
    """write_plate said nothing about the prime tower, so OrcaSlicer put one itself: on a plate filling
    the bed width it landed in the CC2's unprintable corner and the whole slice failed with -102 (seen
    on a real cut model). The plate now keeps the tower's place and writes it into the file."""
    import zipfile

    import numpy as np

    from elegoo_lab import colors, printprep, slicer, threemf

    cols = ["#008755", "#D22630"]
    items = [
        (
            f"petite{k}",
            np.asarray(trimesh.creation.box((60, 20, 8)).vertices) + [0, 0, 4],
            np.asarray(trimesh.creation.box((60, 20, 8)).faces).astype(int),
            np.full(len(trimesh.creation.box((60, 20, 8)).faces), e),
        )
        for k, e in enumerate((1, 2, 1, 2, 1, 2))
    ]
    out = tmp_path / "petites.3mf"
    colors.write_plate(items, cols, out)
    v = np.vstack([q.vertices for o in threemf.read(out).objects for q in o.parts])
    assert v[:, 0].max() <= 201.01  # the tower stands at the right, where the CC2 prints
    with zipfile.ZipFile(out) as z:
        assert b"wipe_tower_x" in b"".join(
            z.read(n) for n in z.namelist() if n.startswith("Metadata")
        )
    piece = tmp_path / "morceau.3mf"  # one cut piece says its tower's place too
    m = trimesh.creation.box((30, 30, 20))
    colors.write_piece(
        np.asarray(m.vertices) + [0, 0, 10],
        np.asarray(m.faces).astype(int),
        np.ones(len(m.faces), int),
        cols,
        piece,
        name="morceau",
    )
    with zipfile.ZipFile(piece) as z:
        assert b"wipe_tower_x" in b"".join(
            z.read(n) for n in z.namelist() if n.startswith("Metadata")
        )
    if not (slicer.TOOLS / "squashfs-root" / "AppRun").exists():
        pytest.skip("slicer non installé (make slicer)")
    r = slicer.slice_model(
        out,
        tmp_path / "g",
        quality="0.20mm Standard",
        filament=["PLA", "PLA"],
        overrides=printprep.TOWER["overrides"],
        timeout=240,
    )
    assert r.gcode[0].exists()  # this plate died with -102 before the tower had its place


@pytest.mark.slicing
def test_piece_by_piece_slices_the_plate_with_far_fewer_changes(tmp_path):
    """Two one-colour pieces of different colours on (well spaced) one plate: one change per colour
    instead of one at nearly every layer."""
    from elegoo_lab import printprep, slicer

    if not (slicer.TOOLS / "squashfs-root" / "AppRun").exists():
        pytest.skip("slicer non installé (make slicer)")
    out, _ = _piece_plate(tmp_path, "espaces", gap_mm=slicer.clearances()[0], extruders=(2, 1))
    couches = printprep.prepare_and_slice(
        out, filaments=["PLA", "PLA Matte"], out_dir=tmp_path / "c", screen_thumbnail=False
    )
    suite = printprep.prepare_and_slice(
        out,
        filaments=["PLA", "PLA Matte"],
        advanced={"ordre": "suite"},
        out_dir=tmp_path / "s",
        screen_thumbnail=False,
    )
    assert couches["ordre"] == "couche"
    assert suite["ordre"] == "suite"
    assert suite["colour_changes"] * 4 < couches["colour_changes"]
    g = (tmp_path / "s" / Path(suite["gcode"][0]).name).read_text(errors="ignore")
    z = [float(l[3:]) for l in g.splitlines() if l.startswith(";Z:")]
    assert any(
        z[i] < z[i - 1] - 1e-6 for i in range(1, len(z))
    )  # one piece finishes, the next starts over


def test_mirror_and_axis_scale(tmp_path):
    """rotate[3:6] scales along the plate axes after the turns; a mirror keeps the surface facing out."""
    from elegoo_lab import colors

    src = tmp_path / "b.stl"
    trimesh.creation.box((10, 20, 30)).export(src)
    assert colors.rotation((0, 0, 0)) is None
    assert colors.rotation((0, 0, 0, 1, 1, 1)) is None
    v, f, _, _ = colors.solid(src, {}, rotate=(0, 0, 90, -2, 1, 1))
    m = trimesh.Trimesh(v, f, process=False)
    assert sorted(map(round, m.extents)) == [10, 30, 40]
    assert round(m.extents[0]) == 40
    assert m.volume > 0
    with pytest.raises(ValueError):
        colors.rotation((0, 0, 0, 0, 1, 1))


def test_import_link_guards():
    """Links: https only, never the house network; zips give their models; names come from the server."""
    import io
    import zipfile

    from elegoo_lab import importlink

    for bad in (
        "http://example.com/a.stl",
        "https://localhost/a.stl",
        "https://192.168.1.10/a.stl",
        "https://127.0.0.1/a.stl",
    ):
        with pytest.raises(importlink.LinkError):
            importlink._check_host(bad)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("files/robot.stl", b"solid x")
        z.writestr("README.txt", b"hi")
        z.writestr("__MACOSX/._robot.stl", b"junk")
    assert importlink._from_zip(buf.getvalue()) == [("robot.stl", b"solid x")]
    assert (
        importlink._name("https://x.org/dl?id=3", 'attachment; filename="vase%20v2.3mf"')
        == "vase v2.3mf"
    )
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
    assert client.post("/lab/api/queue/move", json={"index": 2, "to": 0}).json() == [
        "c.gcode",
        "a.gcode",
        "b.gcode",
    ]
    assert client.delete("/lab/api/queue/1").json() == ["c.gcode", "b.gcode"]
    (lib / "c.gcode").unlink()
    assert client.get("/lab/api/queue").json() == ["b.gcode"]
    assert client.delete("/lab/api/queue/5").status_code == 404


def test_calibration_tower_bands(tmp_path):
    """Each band above the 2 mm base gets its value once; slicer PA lines are muted; flow is reset at the end."""
    from elegoo_lab import calibration, settings

    g = tmp_path / "t.gcode"
    zs = [0.2, 1.0, 2.0, 2.2, 4.4, 4.6, 7.2]
    g.write_text(
        "SET_PRESSURE_ADVANCE ADVANCE=0.04\n"
        + "".join(f";LAYER_CHANGE\n;Z:{z}\nG1 X1 E1\n" for z in zs)
    )
    bands = calibration.tune(g, calibration.BY_KEY["avance"])
    assert [b["value"] for b in bands] == [0.0, 0.005, 0.01]
    text = g.read_text()
    assert "\nSET_PRESSURE_ADVANCE ADVANCE=0.04" not in text
    assert text.count("ADVANCE=0.005 ;") == 1
    g.write_text("".join(f";LAYER_CHANGE\n;Z:{z}\n" for z in (0.2, 2.2, 6.2)))
    calibration.tune(g, calibration.BY_KEY["debit"])
    assert g.read_text().splitlines()[-1].startswith("M221 S100")
    assert "M221 S92 " in g.read_text()
    _, fil = settings.build({"avance_pression": 0.035, "debit": 0.97})
    assert fil == {
        "pressure_advance": ["0.035"],
        "enable_pressure_advance": ["1"],
        "filament_flow_ratio": ["0.97"],
    }
    with pytest.raises(ValueError):
        settings.build({"debit": 1.5})


def test_parametric_preview(web):
    """The live preview is a GLB with the part's size, saves nothing, and reports bad sizes."""
    client, lib = web
    before = set(lib.iterdir())
    r = client.post("/lab/api/parametric/boite/preview", json={"longueur": 100})
    assert r.status_code == 200
    assert r.content[:4] == b"glTF"
    assert r.headers["x-size"].startswith("100.0,")
    assert set(lib.iterdir()) == before
    assert (
        client.post("/lab/api/parametric/boite/preview", json={"longueur": 999}).status_code == 422
    )
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
    assert p["file"] == "t.stl"
    assert p["rotate"] != [0, 0, 0]
    assert p["steps"]
    assert p["steps"][0]["title"].startswith("Posée")
    assert all(s["why"] for s in p["steps"])
    assert src.read_bytes() == before
    assert client.post("/lab/api/models/x.gcode/optimize").status_code in (400, 404)


def test_alert_names_are_short():
    """Phone alerts name the model and its layer height, not the whole G-code file name."""
    from elegoo_lab.alerts import _GCODE, nice

    t = "atelier_couleurs_00015_clean_canvas_0.24mm_PLA_Silk_Noel-PLA_Silk_Noel.gcode en 6 h 28."
    assert (
        _GCODE.sub(lambda m: nice(m.group(0)), t)
        == "atelier couleurs 00015 clean · 0,24 mm en 6 h 28."
    )
    assert nice("stand_0.20mm_PLA.gcode") == "stand · 0,20 mm"
    assert nice("essai.gcode") == "essai"


def test_plate_check_sees_a_part(tmp_path, monkeypatch):
    """The camera check: same plate = empty, a small coloured part on it = occupied, dark or no reference = unknown."""
    import io

    from PIL import Image, ImageDraw

    from elegoo_lab import bedcheck, config

    monkeypatch.setattr(config, "MODELS_DIR", tmp_path)

    def photo(part: bool, light: int = 70) -> bytes:
        img = Image.new("RGB", (640, 360), (light, light, light + 4))
        if part:  # a 5 g stand: dark green, about the plate's own grey level
            ImageDraw.Draw(img).ellipse((260, 295, 345, 335), fill=(20, 120, 70))
        buf = io.BytesIO()
        img.save(buf, "JPEG")
        return buf.getvalue()

    assert bedcheck.check(photo(False))["etat"] == "inconnu"
    bedcheck.save_reference(photo(False))
    assert (
        bedcheck.check(photo(False, light=76))["etat"] == "vide"
    )  # a little more light is not a part
    assert bedcheck.check(photo(True))["etat"] == "occupe"
    assert bedcheck.check(photo(False, light=5))["etat"] == "inconnu"  # light off
    with pytest.raises(ValueError):
        bedcheck.save_reference(photo(False, light=5))


def test_print_review(web):
    """After a print: tips from how it was made, corrections from the values really used, kept on the source model."""
    from elegoo_lab import gallery

    client, lib = web
    (lib / "orque.stl").write_bytes(b"solid x")
    g = lib / "orque_0.20mm_PLA.gcode"
    g.write_text(
        "M190 S65\nT0\nT1\n;LAYER_CHANGE\n"
        "; nozzle_temperature = 230,230\n; enable_support = 1\n"
        '; filament_settings_id = "Elegoo PLA Silk @ECC2"\n'
    )
    client.app.state  # noqa: B018
    from elegoo_lab import library

    library.record(g.name, source="orque.stl")
    rec = gallery.Recorder(g.name)
    rec.finish("terminee")
    d = client.get(f"/lab/api/bilan/{rec.id}").json()
    tips = " ".join(d["tips"])
    assert "65 °C" in tips
    assert "Supports" in tips
    assert "Plusieurs couleurs" in tips
    assert "Silk" in tips
    assert [q["key"] for q in d["questions"]] == [
        "global",
        "surface",
        "details",
        "supports",
        "couleurs",
        "solidite",
    ]
    r = client.post(
        f"/lab/api/bilan/{rec.id}",
        json={
            "issues": ["fils", "decolle", "inconnu"],
            "note": "ok",
            "notes": {"global": 9, "surface": 3, "supports": -2, "autre": 4},
        },
    ).json()
    assert r["notes"] == {
        "global": 5,
        "surface": 3,
        "supports": 0,
    }  # clamped to 0..5, unknown questions dropped
    assert r["issues"] == ["fils", "decolle"]
    assert r["fix"]["advanced"]["temp_buse"] == 220
    assert r["fix"]["advanced"]["temp_plateau"] == 70
    assert client.get("/lab/api/models/orque.stl/info").status_code in (200, 422)
    assert library.load_index()["orque.stl"]["retour"]["issues"] == ["fils", "decolle"]


def test_supports_plan_says_where_the_supports_are(tmp_path):
    """From the printed G-code: columns of supports by height, their place around the part, and a top view."""
    from elegoo_lab import aftercare

    lines = ["; support_type = tree(auto)", "; enable_support = 1"]
    for k in range(1, 31):  # 30 layers of 0.2 mm
        z = k * 0.2
        lines += [";LAYER_CHANGE", f";Z:{z:.1f}", ";TYPE:Outer wall"]
        lines += [f"G1 X{100 + i} Y{100 + (i % 3)} E.05" for i in range(40)]  # the part, x 100..140
        lines += [";TYPE:Support"] + [
            f"G1 X{90 + i * 0.1} Y{101} E.05" for i in range(10)
        ]  # supports left of it
        if k % 10 == 0:
            lines += [";TYPE:Support interface"] + [
                f"G1 X{90 + i * 0.1} Y{102} E.05" for i in range(5)
            ]
    g = tmp_path / "x.gcode"
    g.write_text("\n".join(lines) + "\n")
    plan = aftercare.supports_plan(g)
    assert plan
    assert "tronc" in plan["tips"][0]
    zone = plan["tips"][1]
    assert zone.startswith("Zone 1 · ")
    assert "à gauche" in zone
    assert "du plateau jusqu'à" in zone
    assert "touche la pièce" in zone
    assert plan["map"]["part"]
    assert plan["map"]["supports"]
    assert aftercare.supports_plan(tmp_path / "absent.gcode") is None


def test_paths_overview_is_lighter_and_cached(tmp_path):
    """The review's whole-print view keeps every few layers (and the top one); a second read comes from memory."""
    import base64

    import numpy as np

    from elegoo_lab import gcode_preview

    lines = ["M83"]
    for k in range(1, 11):
        lines += [";LAYER_CHANGE", f";Z:{k * 0.2:.1f}", ";TYPE:Outer wall", "G0 X10 Y10"] + [
            f"G1 X{10 + i} Y10 E.05" for i in range(1, 11)
        ]
    g = tmp_path / "x.gcode"
    g.write_text("\n".join(lines) + "\n")
    full = gcode_preview.cached(g)
    assert full["count"] == 100
    assert "pas" not in full
    lite = gcode_preview.cached(g, 40)
    assert lite["pas"] == 3
    assert lite["layers"] == full["layers"]
    lay = np.frombuffer(base64.b64decode(lite["layer"]), "<u2")
    assert sorted(set(lay.tolist())) == [0, 3, 6, 9]  # every third layer, and the last one
    assert gcode_preview.cached(g, 40) is lite  # from memory
    assert gcode_preview.cached(g, 1000)["count"] == 100  # small enough: whole


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
    ev = {
        "title": "Impression terminée",
        "detail": "orque_0.20mm_PLA.gcode en 1 h.",
        "level": "ok",
        "bilan": "20261111-orque",
    }
    assert asyncio.run(alerts.send_ntfy(ev))
    h = sent["headers"]
    assert h["Click"] == "https://pc.example.ts.net:8443/lab/"
    assert (
        h["Actions"]
        == "view, Faire le bilan, https://pc.example.ts.net:8443/lab/#bilan=20261111-orque, clear=true"
    )
    assert sent["content"].decode() == "orque · 0,20 mm en 1 h."


def test_more_parametric_parts():
    """The new generators: every variant builds, sizes follow the standards, bad choices are refused."""
    import base64
    import io
    from pathlib import Path

    from PIL import Image

    from elegoo_lab import parametric

    if not Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf").exists():
        pytest.skip("DejaVuSans-Bold font not available")

    def sz(k, v=None):
        return parametric.preview(k, v or {})[1]

    assert sz("gridfinity", {"cases_x": 2, "cases_y": 1, "hauteur_u": 6, "empilable": False})[
        :3
    ] == [
        83.5,
        41.5,
        42.0,
    ]  # 42 mm grid, 7 mm units
    for piece in ("vis", "ecrou", "rondelle", "entretoise"):
        assert sz("visserie", {"piece": piece, "taille": "M5"})
    assert sz("visserie", {"piece": "ecrou", "taille": "M8"})[2] == 6.5  # ISO nut height
    assert round(sz("engrenage", {"dents": 20, "module": 2})[0]) == 44  # tip diameter (z + 2) m
    for forme in ("boule", "etoile", "sapin"):
        assert sz("decoration_noel", {"forme": forme})
    buf = io.BytesIO()
    Image.new("L", (40, 20), 128).save(buf, "PNG")
    photo = "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()
    w, thick, h = sz("lithophanie", {"photo": photo, "largeur": 60, "cadre": 0})
    assert abs(w - 60) < 1
    assert abs(h - 30) < 1
    assert thick <= 3.0
    with pytest.raises(ValueError):
        parametric.preview("visserie", {"taille": "M7"})


def test_simplify_colour_specks():
    """In each layer, a colour under the threshold takes the layer's main colour; hand-painted faces never change."""
    import numpy as np

    from elegoo_lab import colors, threemf

    box = trimesh.creation.box((20, 20, 2)).subdivide().subdivide()
    part = threemf.Part("p", np.asarray(box.vertices), np.asarray(box.faces))
    st = np.ones(len(box.faces), int)
    st[:2] = 2  # a speck of colour 2
    states = [st.copy()]
    assert colors.simplify_layers([part], states, 2.5, 0.03) == 1
    assert (states[0] == 1).all()
    part.locked = np.zeros(len(box.faces), bool)
    part.locked[0] = True
    states = [st.copy()]
    assert colors.simplify_layers([part], states, 2.5, 0.03) == 0
    assert states[0][0] == 2


# --- INF.3: couverture — modules faiblement couverts (firmware, settings, spools, printprep, sauvegarde, cli) ---


def test_firmware_version_and_manager():
    from elegoo_lab import firmware

    v = firmware.FirmwareVersion("02.01.00.00")
    assert (v.major, v.minor, v.patch, v.build) == (2, 1, 0, 0)
    assert str(v) == "02.01.00.00"
    assert firmware.FirmwareVersion("x").major == 0  # illisible -> 0.0.0.0
    assert firmware.FirmwareVersion("02.00.02.01").is_supported()
    assert not firmware.FirmwareVersion("01.00.00.00").is_supported()
    assert "Complètement" in firmware.FirmwareVersion("02.00.02.01").get_support_level()
    assert "inconnu" in firmware.FirmwareVersion("00.00.00.01").get_support_level()
    ok, msg = firmware.check_firmware_version("02.00.02.05")
    assert ok and "supporté" in msg
    ok, msg = firmware.check_firmware_version("09.09.09.09")
    assert not ok and "non supporté" in msg

    m = firmware.FirmwareManager()
    assert m.detected_version is None and not m.is_supported and not m.safe_mode
    assert m.get_warning_message() == ""
    info = m.get_safe_mode_info()
    assert info["firmware_detected"] is False and info["blocked_commands"] == {}
    m.set_detected_version("02.00.02.01")
    assert m.is_supported and not m.safe_mode
    assert m.is_command_safe("homing")  # hors mode safe, tout passe
    m.set_detected_version("99.00.00.00")
    assert m.safe_mode and not m.is_supported
    assert not m.is_command_safe("homing")
    assert m.is_command_safe("status")
    assert "homing" in m.get_blocked_commands()
    assert "99.00.00.00" in m.get_warning_message()
    assert m.get_safe_mode_info()["safe_mode"] is True


def test_settings_build_validates_every_choice_kind():
    from elegoo_lab import settings

    proc, fil = settings.build(None)
    assert proc["curr_bed_type"] == "Textured PEI Plate"
    proc, _ = settings.build({"motif": "gyroide"}, plate="pei_lisse")
    assert proc["sparse_infill_pattern"] == "gyroid" and proc["curr_bed_type"] == "High Temp Plate"
    proc, fil = settings.build({"parois": 3, "temp_buse": 210, "avance_pression": 0.04})
    assert proc["wall_loops"] == "3"
    assert fil["nozzle_temperature"] == ["210"]
    assert fil["enable_pressure_advance"] == ["1"]
    for bad in ({"motif": "inconnu"}, {"parois": 99}, {"temp_buse": 999}, {"bidule": 1}):
        with pytest.raises(ValueError):
            settings.build(bad)
    with pytest.raises(ValueError):
        settings.build(None, plate="inconnu")


def test_spools_loaded_and_own(monkeypatch):
    from elegoo_lab import slicer, spools

    monkeypatch.setattr(slicer, "filaments", lambda: ["PLA", "PLA Silk"])

    canvas = {
        "canvas_info": {
            "canvas_list": [
                {
                    "canvas_id": 1,
                    "tray_list": [
                        {
                            "tray_id": 1,
                            "status": 2,
                            "filament_color": "#ff0000",
                            "filament_type": "PLA",
                            "filament_name": "Rouge",
                        },
                        {"tray_id": 2, "status": 0, "filament_color": "#00FF00"},  # vide
                        {
                            "tray_id": 3,
                            "status": 1,
                            "filament_color": "pas-une-couleur",
                        },  # invalide
                    ],
                }
            ]
        }
    }
    trays = spools.loaded(canvas)
    assert len(trays) == 1
    assert trays[0]["color"] == "#FF0000" and trays[0]["tray_id"] == 1 and trays[0]["pos"] == 0
    assert spools.loaded({}) == []
    assert spools.loaded({"canvas_list": []}) == []
    t = spools.own({"color": "#FF0000", "type": "PLA"}, mine=[])
    assert t["color"] == "#FF0000"  # sans catalogue perso: inchangé
    assert spools.filament_for({"type": "PLA"}) == "PLA"
    assert spools.filament_for({"type": "PLA", "filament_name": "Silk rouge"}) == "PLA Silk"
    assert spools.filament_for({"type": "TPU"}) == "PLA"  # matière inconnue -> défaut


def test_printprep_usage_support_pauses(tmp_path):
    from elegoo_lab import printprep

    with pytest.raises(ValueError):
        printprep.usage_overrides("inconnu", None)
    ov = printprep.usage_overrides("decoratif", 30)
    assert "sparse_infill_density" not in ov  # le remplissage perso gagne
    assert "sparse_infill_density" in printprep.usage_overrides("decoratif", None)
    assert printprep.suggest_usage(Path("boite_x.stl")) == "fonctionnel"
    assert printprep.suggest_usage(Path("figurine.stl")) == printprep.DEFAULT_USAGE
    on, ov = printprep.support_overrides(True)
    assert on and ov == {}
    on, ov = printprep.support_overrides("colonnes", plate_only=True)
    assert on and ov["support_type"] == "normal(auto)" and ov["support_on_build_plate_only"] == "1"
    assert printprep.support_overrides(False) == (False, {})
    with pytest.raises(ValueError):
        printprep.support_overrides("inconnu")
    g = tmp_path / "p.gcode"
    g.write_text(";LAYER_CHANGE\n;Z:0.2\nG1\n;LAYER_CHANGE\n;Z:0.4\nG1\n;LAYER_CHANGE\n;Z:0.6\n")
    placed = printprep.add_pauses(g, [0.5])
    assert placed and placed[0]["mm"] == 0.5


def test_sauvegarde_status_overdue_and_disk(tmp_path, monkeypatch):
    from elegoo_lab import sauvegarde

    monkeypatch.setattr(sauvegarde, "_file", lambda: tmp_path / "sauvegarde.json")
    assert sauvegarde.status().get("ok") is None
    assert "Aucune sauvegarde" in (sauvegarde.overdue() or "")
    sauvegarde._record(ok=int(time.time()))
    assert sauvegarde.overdue() is None
    assert sauvegarde.status()["ok"] > 0
    assert sauvegarde._same_disk(tmp_path, tmp_path)
    disk = sauvegarde.usb_disk()
    assert disk is None or disk.is_dir()


def test_cli_models_list_and_info(tmp_path, monkeypatch):
    from typer.testing import CliRunner

    from elegoo_lab import cli, config

    lib = tmp_path / "models"
    lib.mkdir()
    monkeypatch.setattr(config, "MODELS_DIR", lib)
    monkeypatch.setattr(config, "CONFIG_FILE", tmp_path / "config.toml")
    trimesh.creation.box((10, 20, 30)).export(lib / "cube.stl")
    r = CliRunner().invoke(cli.app, ["models", "list"])
    assert r.exit_code == 0 and "cube.stl" in r.output
    r = CliRunner().invoke(cli.app, ["models", "info", "cube.stl"])
    assert r.exit_code == 0 and "10" in r.output


def test_couches_bands_on_a_box():
    import numpy as np

    from elegoo_lab import couches

    m = trimesh.creation.box((10, 10, 5))
    m.apply_translation([0, 0, 2.5])  # resting on z = 0
    bands = couches.bands(np.asarray(m.vertices), np.asarray(m.faces), 0.2, "pentes")
    assert bands and bands[0][0] == 0.0
    assert abs(bands[-1][1] - 5.0) < 1e-6
    assert all(0.08 <= h <= 0.28 for _, _, h in bands)


def test_parametric_shapes(monkeypatch):
    from elegoo_lab import parametric

    repo_font = Path(parametric.__file__).parent / "fonts" / "Sacramento-Regular.ttf"
    # polices système (DejaVu/URW) absentes hors CI : on branche la police du repo
    monkeypatch.setattr(parametric, "FONT", repo_font)
    monkeypatch.setattr(parametric, "SCRIPT_FONT", repo_font)
    monkeypatch.setattr(parametric.text_section, "__defaults__", (repo_font,))
    parts = parametric.box(50, 40, 20, 2, 0.2, 3)
    assert [p[0] for p in parts] == ["boite", "couvercle"]
    h = parametric.hook(30, 40, 20, 3, 4)
    assert len(h) == 1 and h[0][0] == "crochet"
    o = parametric.organiser(60, 40, 15, 2, 2, 2, 2, 3)
    assert o[0][0] == "organiseur"
    with pytest.raises(ValueError):
        parametric.organiser(10, 10, 5, 4, 4, 2, 1, 2)  # compartiments trop petits
    lab = parametric.label("ABC", 10, 2, 1, 3, True)
    assert [p[0] for p in lab] == ["plaque", "texte"]
    with pytest.raises(ValueError):
        parametric.label("   ", 10, 2, 1, 3, False)


def test_parametric_more_shapes():
    from elegoo_lab import parametric_more as pm

    b = pm.gridfinity_bin(1, 1, 2, 1, 1, False, True)
    assert b and b[0][0]
    g = pm.gear(12, 2.0, 5, 4, 20)
    assert g and g[0][0]
    v = pm.hardware("vis", "M5", 20, 0.2)
    assert v and v[0][0] == "vis"
    with pytest.raises(ValueError):
        pm.hardware("vis", "M99", 20, 0.2)


def test_addtext_writes_a_3mf(tmp_path, monkeypatch):
    from elegoo_lab import addtext, parametric

    repo_font = Path(parametric.__file__).parent / "fonts" / "Sacramento-Regular.ttf"
    monkeypatch.setattr(parametric, "FONT", repo_font)
    monkeypatch.setattr(parametric, "SCRIPT_FONT", repo_font)
    monkeypatch.setattr(parametric.text_section, "__defaults__", (repo_font,))
    monkeypatch.setitem(addtext.FONTS, "manuscrite", repo_font)
    monkeypatch.setitem(addtext.FONTS, "droite", repo_font)
    src = tmp_path / "m.stl"
    trimesh.creation.box((30, 30, 5)).export(src)
    out = tmp_path / "out.3mf"
    addtext.add(src, "ABC", size_mm=8, out=out)
    assert out.exists() and out.stat().st_size > 0
    with pytest.raises(ValueError):
        addtext.add(src, "x" * 50, out=tmp_path / "o2.3mf")  # texte trop long
    with pytest.raises(ValueError):
        addtext.add(src, "ABC", angle=120, out=tmp_path / "o3.3mf")  # angle hors bornes


def test_web_simple_get_endpoints(web):
    client, _lib = web
    for path in (
        "/lab/api/setup",
        "/lab/api/parametric",
        "/lab/api/queue",
        "/lab/api/entretien",
        "/lab/api/lancement",
        "/lab/api/models",
    ):
        r = client.get(path)
        assert r.status_code == 200, path


def test_slicer_gcode_helpers():
    from elegoo_lab import slicer

    g = b"G28\nBED_MESH_CALIBRATE\nG1 X0\n"
    out = slicer.without_bed_mesh(g)
    assert b"BED_MESH_CALIBRATE" in out and out != g  # commenté, pas supprimé
    p = slicer.without_purge(b"M6211 T2 L10\nG1 E5\n")
    assert (
        b"CANVAS_SWITCH_FILAMENT T=2" in p and b"M6211 T2 L10" in p
    )  # remplacée, ligne gardée en commentaire
    with pytest.raises(slicer.SliceError):
        slicer.binary()  # pas d'OrcaSlicer dans l'environnement de test


async def test_importlink_validation():
    import io
    import zipfile

    from elegoo_lab import importlink

    with pytest.raises(importlink.LinkError):
        importlink._check_host("http://example.com/x.stl")  # http refusé
    with pytest.raises(importlink.LinkError):
        importlink._check_host("https://127.0.0.1/x.stl")  # réseau local refusé
    with pytest.raises(importlink.LinkError):
        await importlink.fetch("https://127.0.0.1:9/x.stl")  # jamais de réseau local
    assert importlink._name("https://x.com/a/b.stl", None) == "b.stl"
    assert importlink._name("https://x.com/a", 'filename="truc 3mf.stl"') == "truc 3mf.stl"
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("a.stl", b"solid\nendsolid")
    assert importlink._from_zip(buf.getvalue()) == [("a.stl", b"solid\nendsolid")]


def test_vision_nms_and_no_model():
    import numpy as np

    from elegoo_lab import vision

    boxes = np.array([[0, 0, 10, 10], [1, 1, 11, 11], [50, 50, 60, 60]], dtype=float)
    confs = np.array([0.9, 0.8, 0.7])
    assert vision._nms(boxes, confs) == [0, 2]  # la 2e est noyée dans la 1re
    assert not vision.model_ready()  # pas de modèle IA téléchargé en test


def test_spools_match_pairs_colours_to_trays(monkeypatch):
    from elegoo_lab import slicer, spools

    monkeypatch.setattr(slicer, "filaments", lambda: ["PLA"])
    trays = [
        {"color": c, "type": "PLA", "tray_id": i + 1, "pos": i, "status": 2}
        for i, c in enumerate(["#FF0000", "#0000FF"])
    ]
    model = [
        {"index": 0, "hex": "#FF0000", "share": 0.7},
        {"index": 1, "hex": "#0000FF", "share": 0.3},
    ]
    m = spools.match(model, trays)
    assert m["mapping"][0] == 1 and m["mapping"][1] == 2
    with pytest.raises(ValueError):
        spools.match(model, [])
    with pytest.raises(ValueError):
        spools.match([], trays)


def test_cli_models_prepare_and_backup_status(tmp_path, monkeypatch):
    from typer.testing import CliRunner

    from elegoo_lab import cli, config

    lib = tmp_path / "models"
    lib.mkdir()
    monkeypatch.setattr(config, "MODELS_DIR", lib)
    monkeypatch.setattr(config, "CONFIG_FILE", tmp_path / "config.toml")
    trimesh.creation.box((10, 20, 30)).export(lib / "cube.stl")
    out = lib / "out.stl"
    r = CliRunner().invoke(cli.app, ["models", "prepare", "cube.stl", "--out", str(out)])
    assert r.exit_code == 0, r.output
    assert out.exists() and out.stat().st_size > 0
    r = CliRunner().invoke(cli.app, ["sauvegarde", "etat"])
    assert r.exit_code == 0


def test_web_model_detail_endpoints(web):
    client, _lib = web
    stl = trimesh.creation.box((20, 20, 10)).export(file_type="stl")
    r = client.post(
        "/lab/api/models",
        files={"file": ("cube.stl", stl)},
        headers={"Origin": "http://testserver"},
    )
    assert r.status_code == 200
    for path in ("info", "colors", "marks", "pieces", "orientations", "advice", "defects"):
        rr = client.get(f"/lab/api/models/cube.stl/{path}")
        assert rr.status_code == 200, path


def test_assistant_pure_helpers(tmp_path, monkeypatch):
    from elegoo_lab import assistant, config

    monkeypatch.setattr(config, "CONFIG_FILE", tmp_path / "config.toml")
    assert assistant._json_only('{"a": 1}') == {"a": 1}
    assert assistant._json_only('```json\n{"b": 2}\n```') == {"b": 2}
    assert assistant._json_only('du texte {"c": 3} et la fin') == {"c": 3}
    assert assistant._json_only("rien") == {}
    assert "inconnu" in assistant.run_tool("bidule", {}, "x.stl")["erreur"]
    assert "n'est plus" in assistant.run_tool("fiche", {}, "absent.stl")["erreur"]
    lib = tmp_path / "models"
    lib.mkdir()
    monkeypatch.setattr(config, "MODELS_DIR", lib)
    trimesh.creation.box((10, 10, 10)).export(lib / "cube.stl")
    assert assistant.run_tool("fiche", {}, "cube.stl")
    assert "cube.stl" in assistant._scan_meshes()


def test_printprep_layer_helpers(monkeypatch):
    from pathlib import Path as _P

    from elegoo_lab import library, printprep

    assert printprep._layer_mm("0.20mm Standard") == 0.2
    assert printprep._layer_mode(None) == "pentes"
    assert printprep._layer_mode(None, usage="profil") == ""
    assert printprep._real_colours(["#FF0000"], None, 2)[0] == "#FF0000"
    monkeypatch.setattr(
        library, "load_index", lambda: {"m.stl": {"retour": {"issues": ["couleurs"]}}}
    )
    assert printprep.bled_purge(_P("m.stl")) is True
    monkeypatch.setattr(library, "load_index", dict)
    assert printprep.bled_purge(_P("m.stl")) is False


def test_parametric_more_text_and_stand_shapes(monkeypatch):
    from elegoo_lab import parametric, parametric_more as pm

    repo_font = Path(parametric.__file__).parent / "fonts" / "Sacramento-Regular.ttf"
    monkeypatch.setattr(parametric, "FONT", repo_font)
    monkeypatch.setattr(parametric, "SCRIPT_FONT", repo_font)
    monkeypatch.setattr(parametric.text_section, "__defaults__", (repo_font,))
    monkeypatch.setattr(pm, "FONT", repo_font)
    monkeypatch.setattr(pm, "SCRIPT_FONT", repo_font)
    k = pm.keychain("LUC", "manuscrite", 8, 3, 1)
    assert k and k[0][0]
    o = pm.ornament("etoile", "", 30, 3, 1)
    assert o and o[0][0]
    s = pm.phone_stand(60, 60, 8, 120, True)
    assert s and s[0][0]
    c = pm.cable_comb(4, 6, 10, 2, False)
    assert c and c[0][0]


def test_web_more_get_endpoints(web):
    client, _lib = web
    for path in (
        "/lab/api/bobines",
        "/lab/api/slicer",
    ):  # les autres ont besoin du manager (lifespan)
        r = client.get(path)
        assert r.status_code == 200, path


def test_firmware_integration_helpers():
    from types import SimpleNamespace

    from elegoo_lab import firmware, firmware_integration as fi

    info = fi.check_firmware_on_connection(SimpleNamespace(firmware_version="02.00.02.01"))
    assert info["firmware_detected"] and info["is_supported"]
    firmware.firmware_manager._detected_version = None
    firmware.firmware_manager._safe_mode = False
    info = fi.check_firmware_on_connection(SimpleNamespace(firmware_version=None))
    assert info["firmware_detected"] is False
    ok, msg = fi.can_execute_printer_command("status")
    assert ok and msg == ""
    assert fi.get_blocked_commands_list()
    firmware.firmware_manager._detected_version = None
    firmware.firmware_manager._safe_mode = False


def test_cli_colors_and_slice_profiles(tmp_path, monkeypatch):
    from typer.testing import CliRunner

    from elegoo_lab import cli, config

    lib = tmp_path / "models"
    lib.mkdir()
    monkeypatch.setattr(config, "MODELS_DIR", lib)
    monkeypatch.setattr(config, "CONFIG_FILE", tmp_path / "config.toml")
    trimesh.creation.box((10, 10, 10)).export(lib / "cube.stl")
    r = CliRunner().invoke(cli.app, ["colors", "cube.stl"])
    assert r.exit_code == 0 and "bobine" in r.output
    r = CliRunner().invoke(cli.app, ["slice-profiles"])
    assert r.exit_code == 1 and "Slicer" in r.output  # pas d'OrcaSlicer en local


def test_assistant_resize_tool(tmp_path, monkeypatch):
    from elegoo_lab import assistant, config

    lib = tmp_path / "models"
    lib.mkdir()
    monkeypatch.setattr(config, "MODELS_DIR", lib)
    monkeypatch.setattr(config, "CONFIG_FILE", tmp_path / "config.toml")
    trimesh.creation.box((10, 10, 10)).export(lib / "cube.stl")
    r = assistant.run_tool("redimensionner", {"hauteur": 5}, "cube.stl")
    assert "erreur" not in r, r
    assert any("h5mm" in p.name for p in lib.glob("*.ply"))  # _baked écrit un PLY


def test_sauvegarde_run_without_disk(tmp_path, monkeypatch):
    from elegoo_lab import sauvegarde

    monkeypatch.setattr(sauvegarde, "_file", lambda: tmp_path / "s.json")
    monkeypatch.setattr(sauvegarde, "usb_disk", lambda: None)
    with pytest.raises(RuntimeError, match="disque"):
        sauvegarde.run(if_needed=True)


def test_web_library_endpoints(web):
    client, _lib = web
    stl = trimesh.creation.box((20, 20, 10)).export(file_type="stl")
    client.post(
        "/lab/api/models",
        files={"file": ("cube.stl", stl)},
        headers={"Origin": "http://testserver"},
    )
    r = client.get("/lab/api/models")
    assert r.status_code == 200 and any(m.get("name") == "cube.stl" for m in r.json())
    assert client.get("/lab/api/models/cube.stl").status_code == 200
    r = client.get("/lab/api/models/cube.stl/thumb.png")
    assert r.status_code == 200 and r.headers["content-type"] == "image/png"
    assert client.get("/lab/api/library/cleanup").status_code == 200
    r = client.post(
        "/lab/api/models/cube.stl/rename",
        json={"name": "cube2.stl"},
        headers={"Origin": "http://testserver"},
    )
    assert r.status_code == 200 and r.json()["name"] == "cube2.stl"
    r = client.post(
        "/lab/api/library/delete",
        json={"names": ["cube2.stl"]},
        headers={"Origin": "http://testserver"},
    )
    assert r.status_code == 200 and "cube2.stl" in r.json()["deleted"]


def test_cli_service_etat_no_unit(tmp_path, monkeypatch):
    import subprocess

    from typer.testing import CliRunner

    from elegoo_lab import cli, config

    monkeypatch.setattr(config, "CONFIG_FILE", tmp_path / "config.toml")
    monkeypatch.setattr(cli, "UNIT_DIR", tmp_path / "units")
    r = CliRunner().invoke(cli.app, ["service", "etat"])
    assert r.exit_code == 0 and "Pas de service" in r.output
    (tmp_path / "units").mkdir()
    (tmp_path / "units" / "cc2-atelier.service").write_text("[Unit]\n")
    monkeypatch.setattr(
        cli,
        "_systemctl",
        lambda *a, **k: subprocess.CompletedProcess(
            a, 0, "active" if a[0] == "is-active" else "enabled", ""
        ),
    )
    r = CliRunner().invoke(cli.app, ["service", "etat"])
    assert r.exit_code == 0 and "en marche" in r.output


def test_assistant_cli_detail():
    from elegoo_lab import assistant

    assert "connecté" in assistant._cli_detail("Reading API keys from file\n401 Unauthorized")
    assert "offre" in assistant._cli_detail("subscription not available for this model")
    assert assistant._cli_detail("") == "sortie vide"


def test_parametric_more_lithophane():
    from elegoo_lab import parametric_more as pm

    l = pm.lithophane(None, 60, 2, 4, 3)
    assert l and l[0][0]
    with pytest.raises(ValueError):
        pm.lithophane(None, 60, 4, 2, 3)  # max <= min


def test_slicer_fr_and_header(tmp_path):
    from elegoo_lab import slicer

    g = tmp_path / "p.gcode"
    g.write_text(
        "; total layer number: 10\n; estimated printing time (normal mode): 1h 2m\n"
        "; total filament used [mm]: 1234\n; nozzle_temperature: 220\n"
    )
    h = slicer._header(g)
    assert h and any("1234" in v for v in h.values())
    assert isinstance(slicer._fr("some english warning"), str)


def test_assistant_cli_message():
    from elegoo_lab import assistant

    out = '[{"role": "assistant", "type": "message", "content": [{"text": "Bonjour"}]}]'
    assert assistant._cli_message(out) == "Bonjour"
    assert assistant._cli_message("pas du json") == ""
    assert assistant._cli_message([]) == ""


def test_web_texte_and_parametric_preview(web, monkeypatch):
    from elegoo_lab import addtext, parametric

    repo_font = Path(parametric.__file__).parent / "fonts" / "Sacramento-Regular.ttf"
    monkeypatch.setattr(parametric, "FONT", repo_font)
    monkeypatch.setattr(parametric, "SCRIPT_FONT", repo_font)
    monkeypatch.setattr(parametric.text_section, "__defaults__", (repo_font,))
    monkeypatch.setitem(addtext.FONTS, "manuscrite", repo_font)
    monkeypatch.setitem(addtext.FONTS, "droite", repo_font)
    client, _lib = web
    stl = trimesh.creation.box((40, 20, 5)).export(file_type="stl")
    client.post(
        "/lab/api/models",
        files={"file": ("plaque.stl", stl)},
        headers={"Origin": "http://testserver"},
    )
    r = client.post(
        "/lab/api/models/plaque.stl/texte",
        json={"texte": "ABC", "police": "droite", "angle": 0, "taille": 8},
        headers={"Origin": "http://testserver"},
    )
    assert r.status_code == 200, r.text
    r = client.post(
        "/lab/api/parametric/boite/preview",
        json={"longueur": 50, "largeur": 40, "hauteur": 20, "paroi": 2, "jeu": 0.2, "rayon": 3},
        headers={"Origin": "http://testserver"},
    )
    assert r.status_code == 200 and r.headers["content-type"] == "model/gltf-binary", r.text


def test_cli_code_acces(tmp_path, monkeypatch):
    from typer.testing import CliRunner

    from elegoo_lab import cli, config

    monkeypatch.setattr(config, "CONFIG_FILE", tmp_path / "config.toml")
    r = CliRunner().invoke(cli.app, ["code-acces", "123456"])
    assert r.exit_code == 0 and "123456" in r.output
    r = CliRunner().invoke(cli.app, ["code-acces", "ab"])
    assert r.exit_code != 0  # code non numérique refusé


def test_assistant_more_tools(tmp_path, monkeypatch):
    from elegoo_lab import assistant, config

    lib = tmp_path / "models"
    lib.mkdir()
    monkeypatch.setattr(config, "MODELS_DIR", lib)
    monkeypatch.setattr(config, "CONFIG_FILE", tmp_path / "config.toml")
    trimesh.creation.box((10, 10, 10)).export(lib / "cube.stl")
    assert "erreur" not in assistant.run_tool("reparer", {}, "cube.stl")
    assert "erreur" not in assistant.run_tool(
        "faire_pivoter", {"rx": 0, "ry": 0, "rz": 90}, "cube.stl"
    )
    r = assistant.run_tool("orienter", {}, "cube.stl")
    assert r.get("poses"), r


def test_web_forme_endpoint(web):
    client, _lib = web
    stl = trimesh.creation.box((30, 30, 10)).export(file_type="stl")
    client.post(
        "/lab/api/models",
        files={"file": ("plaque.stl", stl)},
        headers={"Origin": "http://testserver"},
    )
    r = client.post(
        "/lab/api/models/plaque.stl/forme",
        json={
            "forme": "cylindre",
            "operation": "percer",
            "taille": [6, 6, 30],
            "position": [15, 15, 5],
            "axe": "z",
            "couleur": 1,
        },
        headers={"Origin": "http://testserver"},
    )
    assert r.status_code == 200, r.text


# --- INF.3 bloc 2 : endpoints web restants (sans manager), config assistant, cli ---


def test_web_endpoints_round2(web):
    client, _lib = web
    hdrs = {"Origin": "http://testserver"}
    stl = trimesh.creation.box((20, 20, 10)).export(file_type="stl")
    client.post("/lab/api/models", files={"file": ("cube.stl", stl)}, headers=hdrs)
    client.post(
        "/lab/api/models",
        files={"file": ("p.gcode", b"G28\n;LAYER_CHANGE\n;Z:0.2\nG1 X1\n")},
        headers=hdrs,
    )
    assert client.get("/lab/api/models/p.gcode/coupe").status_code == 200
    assert client.get("/lab/api/models/cube.stl/cut-preview.glb").status_code == 200
    assert client.post("/lab/api/langue", json={"lang": "en"}, headers=hdrs).status_code == 200
    assert client.post("/lab/api/entretien/plateau", headers=hdrs).status_code == 200
    assert (
        client.post("/lab/api/lancement", json={"printer_check": False}, headers=hdrs).status_code
        == 200
    )
    assert (
        client.post("/lab/api/models/cube.stl/optimize", json={}, headers=hdrs).status_code == 200
    )
    assert client.post("/lab/api/models/cube.stl/repair", json={}, headers=hdrs).status_code == 200
    assert (
        client.post(
            "/lab/api/models/cube.stl/retouch", json={"couleur": 1, "zones": []}, headers=hdrs
        ).status_code
        == 200
    )
    r = client.post(
        "/lab/api/setup/check", json={"host": "127.0.0.1", "access_code": "123456"}, headers=hdrs
    )
    assert r.status_code == 200, r.text  # answer from connexion.check, ok or not
    r = client.post("/lab/api/setup/dowel", data={"play": "0.2"}, headers=hdrs)
    assert r.status_code == 200 and r.json()["dowel_play"] == 0.2
    assert client.post("/lab/api/queue", json={"name": "p.gcode"}, headers=hdrs).status_code in (
        200,
        409,
    )
    assert client.get("/lab/api/bilan/x").status_code == 404


def test_assistant_config_helpers(tmp_path, monkeypatch):
    from elegoo_lab import assistant, config

    monkeypatch.setattr(config, "CONFIG_FILE", tmp_path / "config.toml")
    assert assistant.api_key() is None  # pas de clé dans un config vierge
    assert assistant.model_name()
    assert assistant.moteur()
    (tmp_path / "config.toml").write_text(
        '[assistant]\napi_key = "sk-test"\nmodel = "gros"\nmoteur = "cli"\ncommande = "vibe"\n'
    )
    assert assistant.api_key() == "sk-test"
    assert assistant.model_name() == "gros"
    assert assistant.moteur() == "cli"
    monkeypatch.setattr(assistant.shutil, "which", lambda c: "/usr/bin/" + c)
    assert assistant.cli_bin() == "/usr/bin/vibe"
    monkeypatch.setattr(assistant.shutil, "which", lambda c: None)
    monkeypatch.setattr(assistant.Path, "home", lambda: tmp_path)  # aucun binaire en local/bin
    assert assistant.cli_bin() is None


def test_cli_help_and_slice_without_slicer(tmp_path, monkeypatch):
    from typer.testing import CliRunner

    from elegoo_lab import cli, config

    lib = tmp_path / "models"
    lib.mkdir()
    monkeypatch.setattr(config, "MODELS_DIR", lib)
    monkeypatch.setattr(config, "CONFIG_FILE", tmp_path / "config.toml")
    trimesh.creation.box((10, 10, 10)).export(lib / "cube.stl")
    for args in (["--help"], ["models", "--help"], ["slice", "--help"], ["simulateur", "--help"]):
        r = CliRunner().invoke(cli.app, args)
        assert r.exit_code == 0, (args, r.output)
    r = CliRunner().invoke(cli.app, ["slice", "cube.stl"])
    assert r.exit_code == 1 and "Slicer" in r.output  # pas d'OrcaSlicer en local


def test_stock_and_maintenance_helpers(tmp_path, monkeypatch):
    from elegoo_lab import maintenance, stock

    monkeypatch.setattr(stock, "_file", lambda: tmp_path / "stock.json")
    monkeypatch.setattr(maintenance, "_file", lambda: tmp_path / "maint.json")
    assert stock.grams(10, "PLA") > stock.grams(10, "ABS")  # densité PLA > ABS
    assert stock.sync([]) == []
    assert isinstance(stock.load(), dict)
    assert stock.check("inconnu.gcode") is None
    st = maintenance.status()
    assert isinstance(st, list) and st
    assert isinstance(maintenance.done("plateau"), list)
    assert isinstance(maintenance.newly_due(), list)


def test_colors_pure_helpers(tmp_path):
    import numpy as np

    from elegoo_lab import colors

    assert colors._hex(np.array([255, 0, 0])) == "#FF0000"
    assert (colors._rgb("#FF0000") == [255, 0, 0]).all()
    c = colors.encode_state(5)
    assert colors.paint_states(c) == {5}
    assert colors.paint_states(colors.remap_paint(c, {5: 2})) == {2}
    p = tmp_path / "m.stl"
    trimesh.creation.box((5, 5, 5)).export(p)
    colors.save_retouch(p, {"#FF0000": [0, 1, 2]})
    assert colors.load_retouch(p) == {"#FF0000": [0, 1, 2]}
    colors.save_marks(p, {"support": [3]})
    assert colors.load_marks(p) == {"support": [3]}


def test_library_helpers(tmp_path, monkeypatch):
    from elegoo_lab import config, library

    lib = tmp_path / "models"
    lib.mkdir()
    monkeypatch.setattr(config, "MODELS_DIR", lib)
    trimesh.creation.box((5, 5, 5)).export(lib / "a.stl")
    library.record("a.gcode", source="a.stl", temps_s=10)
    assert "a.gcode" in library.load_index()
    assert library.kind("a.stl") == "modele" and library.kind("x.gcode") == "gcode"
    assert any(m["name"] == "a.stl" for m in library.listing())
    assert library.rename("a.stl", "b.stl") == "b.stl"
    assert library.delete(["b.stl"]) == ["b.stl"]
    assert isinstance(library.cleanup(), list)
    assert isinstance(library.old_gcodes(), list)


def test_threemf_plate_count_and_split(tmp_path):
    from elegoo_lab import colorize, threemf

    src = tmp_path / "c.stl"
    trimesh.creation.box((10, 10, 10)).export(src)
    out = tmp_path / "c.3mf"
    colorize.build_3mf([(src, 1)], out)  # filament 1..4
    assert threemf.plate_count(out) >= 1
    plates = threemf.split_plates(out, tmp_path / "plates")
    assert isinstance(plates, list)  # une seule plaque ici : rien à découper


def test_optimize_plan_on_a_box(tmp_path):
    from elegoo_lab import optimize

    src = tmp_path / "b.stl"
    trimesh.creation.box((30, 30, 10)).export(src)
    assert optimize.plan(src)


# --- INF.3 bloc 3 : endpoints avec lifespan (watcher actif), access, connexion ---


def test_web_endpoints_with_lifespan(tmp_path, monkeypatch, fake_printer_env):
    from fastapi.testclient import TestClient

    from elegoo_lab import app as app_mod, config

    lib = tmp_path / "models"
    lib.mkdir()
    monkeypatch.setattr(config, "MODELS_DIR", lib)
    monkeypatch.setattr(config, "CONFIG_FILE", tmp_path / "config.toml")
    monkeypatch.setattr(app_mod, "JOBS_FILE", lib / ".jobs.json")
    app = app_mod.create_app(enable_control=True)
    with TestClient(app) as client:
        for p in (
            "/lab/api/events",
            "/lab/api/surveillance",
            "/lab/api/plateau",
            "/lab/api/bobines",
            "/lab/api/models",
        ):
            assert client.get(p).status_code == 200, p
        assert client.post("/lab/api/surveillance", json={"ia": True}).status_code == 200
        # pas de connexion réelle au simulateur : 503 propre, pas de crash
        for p in ("/status", "/lab/api/canvas/bobines", "/lab/api/couleurs"):
            assert client.get(p).status_code == 503, p


def test_access_code_helpers(tmp_path, monkeypatch):
    from elegoo_lab import access, config

    monkeypatch.setattr(config, "CONFIG_FILE", tmp_path / "config.toml")
    code = access.ensure_code()
    assert code and code.isdigit()
    assert access.check_code(code)
    assert not access.check_code("0" * len(code)) or code == "0" * len(code)
    access.set_code("4321")
    assert access.check_code("4321")
    assert not access.check_code(code)
    with pytest.raises(ValueError):
        access.set_code("ab")  # non numérique


async def test_connexion_check_without_printer():
    from elegoo_lab import connexion

    out = await connexion.check("127.0.0.1", "x")  # rien n'écoute : étapes en échec, pas de crash
    assert isinstance(out, dict) and out.get("steps")
    assert isinstance(connexion.resolve_hint(), str)


def test_cli_slice_with_mocked_prepare(tmp_path, monkeypatch):
    from typer.testing import CliRunner

    from elegoo_lab import cli, config, printprep

    lib = tmp_path / "models"
    lib.mkdir()
    monkeypatch.setattr(config, "MODELS_DIR", lib)
    monkeypatch.setattr(config, "CONFIG_FILE", tmp_path / "config.toml")
    trimesh.creation.box((10, 10, 10)).export(lib / "cube.stl")

    def fake_prepare(src, **kw):
        (lib / "cube.gcode").write_text("G28\n")
        return {
            "gcode": ["cube.gcode"],
            "layers": 10,
            "time": "1 h 00",
            "filament_m": 12.0,
            "total_m": 12.0,
            "purge_m": [],
            "slots": [],
            "warnings": [],
            "colour_changes": 0,
            "split": False,
        }

    monkeypatch.setattr(printprep, "prepare_and_slice", fake_prepare)
    r = CliRunner().invoke(cli.app, ["slice", "cube.stl"])
    assert r.exit_code == 0 and "couches" in r.output, r.output

    def boom(src, **kw):
        raise ValueError("modèle illisible")

    monkeypatch.setattr(printprep, "prepare_and_slice", boom)
    r = CliRunner().invoke(cli.app, ["slice", "cube.stl"])
    assert r.exit_code == 1 and "illisible" in r.output


# --- INF.3 bloc 4 : cli (doctor, service, sauvegarde, models/multicolor/gen, erreurs slice),
#     assistant (chat_cli avec faux binaire, slice_brain, chat_api mocke, chat_events),
#     vision (Prediction/annotate/grab), spools, importlink, sauvegarde.run,
#     couches (apply/remove/bandes pentues), optimize (corrections), addtext (erreurs),
#     simulateur vivant (commandes de controle + app web contre le Sim) ---


def test_cli_doctor():
    from typer.testing import CliRunner

    from elegoo_lab import cli

    r = CliRunner().invoke(cli.app, ["doctor"])
    assert r.exit_code == 0, r.output
    for section in (
        "Configuration",
        "OrcaSlicer",
        "Modèle IA",
        "Imprimante",
        "Caméra",
        "Espace disque",
        "ComfyUI",
    ):
        assert section in r.output, section


def test_cli_service_lifecycle(tmp_path, monkeypatch):
    from types import SimpleNamespace

    from typer.testing import CliRunner

    from elegoo_lab import cli, config

    units = tmp_path / "units"
    monkeypatch.setattr(cli, "UNIT_DIR", units)
    monkeypatch.setattr(
        cli,
        "_systemctl",
        lambda *a, check=True: SimpleNamespace(
            stdout=("active\n" if a[0] == "is-active" else "enabled\n"), returncode=0
        ),
    )
    monkeypatch.setattr(
        cli.subprocess, "run", lambda *a, **k: SimpleNamespace(returncode=0, stderr="", stdout="")
    )
    runner = CliRunner()
    r = runner.invoke(cli.app, ["service", "installer"])
    assert r.exit_code != 0 and "non configur" in r.output  # pas d'imprimante en config de test
    config.CONFIG_FILE.write_text('[printer]\nhost = "1.2.3.4"\naccess_code = "123456"\n')
    r = runner.invoke(cli.app, ["service", "installer", "--local"])
    assert r.exit_code == 0, r.output
    unit = units / "cc2-atelier.service"
    assert unit.exists() and "ExecStart=" in unit.read_text()
    r = runner.invoke(cli.app, ["service", "etat"])
    assert r.exit_code == 0 and "en marche" in r.output
    r = runner.invoke(cli.app, ["service", "journal", "--lignes", "5"])
    assert r.exit_code == 0, r.output
    r = runner.invoke(cli.app, ["service", "retirer"])
    assert r.exit_code == 0 and not unit.exists()


def test_cli_sauvegarde_commands(tmp_path, monkeypatch):
    from types import SimpleNamespace

    from typer.testing import CliRunner

    from elegoo_lab import cli, sauvegarde

    monkeypatch.setattr(sauvegarde, "UNIT_DIR", tmp_path / "units")
    monkeypatch.setattr(
        sauvegarde, "_systemctl", lambda *a, check=True: SimpleNamespace(stdout="", returncode=0)
    )
    runner = CliRunner()
    monkeypatch.setattr(sauvegarde, "run", lambda *a, **k: "sauvegarde faite vers /usb")
    r = runner.invoke(cli.app, ["sauvegarde", "faire"])
    assert r.exit_code == 0 and "sauvegarde faite" in r.output

    def boom(*a, **k):
        raise RuntimeError("disque non branche")

    monkeypatch.setattr(sauvegarde, "run", boom)
    r = runner.invoke(cli.app, ["sauvegarde", "faire", "--si-besoin"])
    assert r.exit_code == 1 and "impossible" in r.output
    monkeypatch.setattr(
        sauvegarde,
        "status",
        lambda: {"ok": 1700000000, "vers": "/usb", "essai": 1700000100, "erreur": "boom"},
    )
    r = runner.invoke(cli.app, ["sauvegarde", "etat"])
    assert r.exit_code == 0 and "/usb" in r.output and "boom" in r.output
    r = runner.invoke(cli.app, ["sauvegarde", "installer", "--vers", "/mnt/usb"])
    assert r.exit_code == 0 and (tmp_path / "units" / "cc2-sauvegarde.timer").exists()


def test_cli_models_prepare_and_multicolor(tmp_path, monkeypatch):
    from types import SimpleNamespace

    from typer.testing import CliRunner

    from elegoo_lab import cli, config, slicer

    lib = config.MODELS_DIR
    trimesh.creation.box((10, 10, 10)).export(lib / "a.stl")
    trimesh.creation.box((5, 5, 5)).export(lib / "b.stl")
    runner = CliRunner()
    r = runner.invoke(cli.app, ["models", "prepare", "a.stl"])
    assert r.exit_code == 0, r.output
    assert (lib / "a_print.stl").exists()
    r = runner.invoke(cli.app, ["multicolor", "a.stl"])  # pas de :emplacement
    assert r.exit_code == 1
    monkeypatch.setattr(
        slicer,
        "slice_model",
        lambda *a, **k: SimpleNamespace(
            gcode=["multi.gcode"], layers=10, time="1 h", filament_m=3.0
        ),
    )
    r = runner.invoke(cli.app, ["multicolor", "a.stl:1", "b.stl:2", "--name", "multi"])
    assert r.exit_code == 0, r.output
    assert (lib / "multi.3mf").exists()
    assert "bobine 1 = PLA" in r.output


def test_cli_gen_and_slice_option_errors(tmp_path, monkeypatch):
    from typer.testing import CliRunner

    from elegoo_lab import cli, comfy as comfy_mod, config

    runner = CliRunner()
    lib = config.MODELS_DIR
    trimesh.creation.box((10, 10, 10)).export(lib / "a.stl")

    def boom(*a, **k):
        raise comfy_mod.ComfyError("ko comfy")

    monkeypatch.setattr(comfy_mod, "generate", boom)
    r = runner.invoke(cli.app, ["gen", "texte3d"])
    assert r.exit_code == 1 and "ko comfy" in r.output
    monkeypatch.setattr(comfy_mod, "generate", lambda *a, **k: [lib / "x.glb"])
    r = runner.invoke(cli.app, ["gen", "texte3d", "--prompt", "un cube"])
    assert r.exit_code == 0 and "x.glb" in r.output
    r = runner.invoke(cli.app, ["slice", "a.stl", "--slot", "x:y"])  # couleur non numérique
    assert r.exit_code == 1
    r = runner.invoke(cli.app, ["slice", "a.stl", "--nozzle", "0.8"])  # buse perso -> SliceError
    assert r.exit_code == 1


def _fake_cli_script(tmp_path, body: str) -> Path:
    script = tmp_path / "fakevibe"
    script.write_text("#!/bin/sh\n" + body)
    script.chmod(0o755)
    return script


def test_assistant_chat_cli_with_fake_bin(tmp_path, monkeypatch):
    from elegoo_lab import assistant, config

    lib = tmp_path / "models"
    lib.mkdir()
    monkeypatch.setattr(config, "MODELS_DIR", lib)
    monkeypatch.setattr(config, "CONFIG_FILE", tmp_path / "config.toml")
    trimesh.creation.box((10, 10, 10)).export(lib / "cube.stl")
    state = tmp_path / "n"
    first = json.dumps(
        [
            {
                "role": "assistant",
                "type": "message",
                "sessionId": "s1",
                "content": [
                    {"text": json.dumps({"outils": [{"outil": "fiche", "arguments": {}}]})}
                ],
            }
        ]
    )
    second = json.dumps(
        [
            {
                "role": "assistant",
                "type": "message",
                "sessionId": "s1",
                "content": [{"text": json.dumps({"reponse": "voila la fiche"})}],
            }
        ]
    )
    assert "'" not in first + second
    _fake_cli_script(
        tmp_path,
        f'n=0\n[ -f "{state}" ] && read n < "{state}"\nn=$((n+1))\necho "$n" > "{state}"\n'
        f"if [ \"$n\" -eq 1 ]; then printf '%s' '{first}'\n"
        f"else printf '%s' '{second}'\nfi\n",
    )
    monkeypatch.setattr(assistant, "cli_bin", lambda: str(tmp_path / "fakevibe"))
    res = assistant.chat("cube.stl", "donne la fiche")
    assert res["reply"] == "voila la fiche"
    assert res["outils"] == ["fiche"] and res["file"] == "cube.stl"
    # mode streaming (emit) : lignes JSON + événement d'outil CLI
    line1 = json.dumps({"type": "effect", "detail": {"toolName": "blender_cao"}})
    line2 = json.dumps(
        {
            "role": "assistant",
            "type": "message",
            "sessionId": "s2",
            "content": [{"text": json.dumps({"reponse": "ok stream"})}],
        }
    )
    assert "'" not in line1 + line2
    _fake_cli_script(tmp_path, f"printf '%s\\n' '{line1}' '{line2}'\n")
    events = []
    res2 = assistant.chat("cube.stl", "salut", emit=events.append)
    assert res2["reply"] == "ok stream"
    assert {"type": "cli", "cible": "blender_cao"} in events
    # moteur cli sans binaire -> ValueError
    monkeypatch.setattr(assistant, "cli_bin", lambda: None)
    (tmp_path / "config.toml").write_text('[assistant]\nmoteur = "cli"\n')
    with pytest.raises(ValueError, match="introuvable"):
        assistant.chat("cube.stl", "x")


def test_assistant_slice_brain_with_fake_bin(tmp_path, monkeypatch):
    from elegoo_lab import assistant, config

    lib = tmp_path / "models"
    lib.mkdir()
    monkeypatch.setattr(config, "MODELS_DIR", lib)
    monkeypatch.setattr(config, "CONFIG_FILE", tmp_path / "config.toml")
    trimesh.creation.box((20, 20, 20)).export(lib / "cube.stl")
    payload = json.dumps(
        [
            {
                "role": "assistant",
                "type": "message",
                "content": [
                    {
                        "text": json.dumps(
                            {
                                "reponse": {
                                    "qualite": "0.20 mm",
                                    "remplissage": 25,
                                    "supports": "arbre",
                                    "usage": "fonctionnel",
                                    "reglages": {"wall_loops": "4"},
                                    "rotate": [0, 0, 90],
                                    "explication": "test",
                                }
                            }
                        )
                    }
                ],
            }
        ]
    )
    assert "'" not in payload
    _fake_cli_script(tmp_path, f"printf '%s' '{payload}'\n")
    monkeypatch.setattr(assistant, "cli_bin", lambda: str(tmp_path / "fakevibe"))
    out = assistant.slice_brain(
        "cube.stl",
        {"usage": "fonctionnel"},
        qualities=["0.12 mm", "0.20 mm"],
        spec={
            "choices": [{"name": "wall_loops", "options": [{"value": "4"}, {"value": "3"}]}],
            "numbers": [{"name": "x", "min": 0, "max": 10}],
            "numbers_fil": [],
            "temps": [],
        },
    )
    assert out["qualite"] == "0.20 mm"
    assert out["remplissage"] == 25 and out["supports"] == "arbre"
    assert out["usage"] == "fonctionnel"
    assert out["reglages"] == {"wall_loops": "4"}
    assert out["rotate"] == [0.0, 0.0, 90.0]
    monkeypatch.setattr(assistant, "cli_bin", lambda: None)
    with pytest.raises(ValueError, match="introuvable"):
        assistant.slice_brain("cube.stl", {})


def test_assistant_chat_api_mocked(tmp_path, monkeypatch):
    from types import SimpleNamespace

    from elegoo_lab import assistant, config

    lib = tmp_path / "models"
    lib.mkdir()
    monkeypatch.setattr(config, "MODELS_DIR", lib)
    monkeypatch.setattr(config, "CONFIG_FILE", tmp_path / "config.toml")
    trimesh.creation.box((10, 10, 10)).export(lib / "cube.stl")
    (tmp_path / "config.toml").write_text('[assistant]\napi_key = "sk-test"\nmoteur = "api"\n')
    real_chat = assistant.chat

    def resp_tool():
        return SimpleNamespace(
            status_code=200,
            text="",
            json=lambda: {
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": None,
                            "tool_calls": [
                                {"id": "t1", "function": {"name": "fiche", "arguments": "{}"}}
                            ],
                        }
                    }
                ]
            },
        )

    def resp_text():
        return SimpleNamespace(
            status_code=200,
            text="",
            json=lambda: {
                "choices": [{"message": {"role": "assistant", "content": "reponse finale"}}]
            },
        )

    seq = [resp_tool(), resp_text()]
    monkeypatch.setattr(assistant.httpx, "post", lambda *a, **k: seq.pop(0))
    res = assistant.chat("cube.stl", "fiche stp")
    assert res["reply"] == "reponse finale" and res["outils"] == ["fiche"]
    monkeypatch.setattr(
        assistant.httpx,
        "post",
        lambda *a, **k: SimpleNamespace(status_code=500, text="boom", json=dict),
    )
    with pytest.raises(ValueError, match="500"):
        assistant.chat("cube.stl", "x")
    # chat_events : un événement final, ou erreur propre
    monkeypatch.setattr(
        assistant, "chat", lambda *a, **k: {"reply": "ok", "file": "f", "outils": []}
    )
    evs = list(assistant.chat_events("f", "m"))
    assert evs[-1]["type"] == "final" and evs[-1]["reply"] == "ok"

    def boom(*a, **k):
        raise ValueError("ko")

    monkeypatch.setattr(assistant, "chat", boom)
    evs = list(assistant.chat_events("f", "m"))
    assert evs[-1]["type"] == "erreur" and "ko" in evs[-1]["texte"]
    # moteur api sans clé -> ValueError explicite
    monkeypatch.setattr(assistant, "chat", real_chat)
    (tmp_path / "config.toml").write_text('[assistant]\nmoteur = "api"\n')
    monkeypatch.delenv("MISTRAL_API_KEY", raising=False)
    with pytest.raises(ValueError, match="pas de cl"):
        assistant.chat("cube.stl", "x")


async def test_vision_prediction_annotate_grab():
    import io

    from PIL import Image

    from elegoo_lab import vision

    p = vision.Prediction()
    assert not p.failing()  # moins de 30 images : jamais d'alerte
    for _ in range(40):
        p.update(0.01)
    for _ in range(40):
        p.update(0.99)
    assert p.failing()
    assert len(p.history) <= 120 and p.last_p == 0.99
    p.new_print()
    assert p.frames == 0 and not p.failing()
    img = Image.new("RGB", (64, 64), (10, 10, 10))
    buf = io.BytesIO()
    img.save(buf, format="JPEG")
    jpeg = buf.getvalue()
    out = vision.annotate(jpeg, [(0.9, (0.1, 0.1, 0.5, 0.5)), (0.1, (0.2, 0.2, 0.3, 0.3))])
    assert out[:2] == b"\xff\xd8"
    assert not vision.model_ready()  # pas de modèle ONNX dans le repo

    class Chunks:
        async def __aiter__(self):
            yield jpeg[:10]
            yield jpeg[10:]

        async def aclose(self):
            pass

    class Cam:
        async def subscribe(self):
            return None, Chunks()

    class Mgr:
        camera = Cam()

    data = await vision.grab(Mgr())
    assert data[:2] == b"\xff\xd8" and data[-2:] == b"\xff\xd9"


def test_spools_single_own_and_needs(monkeypatch):
    from elegoo_lab import slicer, spools

    monkeypatch.setattr(slicer, "filaments", lambda: ["PLA", "PLA Silk", "PETG"])
    trays = [
        {
            "tray_id": i,
            "pos": i - 1,
            "color": c,
            "type": "PLA",
            "filament_name": n,
            "profile": "Elegoo PLA",
            "brand": "Elegoo",
        }
        for i, (c, n) in enumerate(
            [("#FF0000", "Rouge"), ("#00FF00", "Vert"), ("#0000FF", "Bleu"), ("#FFFFFF", "Blanc")],
            1,
        )
    ]
    r = spools.single({"index": 1, "hex": "#FF1100", "share": 100.0}, trays, coloured=True)
    assert r["mapping"] == {1: 1} and r["filaments"] and not r["warnings"]
    r2 = spools.single(
        {"index": 1, "hex": "#123456", "share": 100.0}, trays, coloured=False, active=3
    )
    assert r2["filaments"] == [spools.filament_for(trays[2])]  # bobine active = tray 3
    with pytest.raises(ValueError, match="aucune bobine"):
        spools.single({"index": 1, "hex": "#FF0000", "share": 100.0}, [], coloured=True)
    mine = [{"matiere": "PLA", "couleur": "#FF0002", "profil": "Mon PLA", "nom": "Mon rouge"}]
    tray = {
        "color": "#FF0000",
        "type": "PLA",
        "filament_name": "Rouge",
        "profile": "Elegoo PLA",
        "tray_id": 1,
        "pos": 0,
    }
    out = spools.own(tray, mine)  # bobine perso proche -> profil repris
    assert out["color"] == "#FF0002" and out["profile"] == "Mon PLA"
    out2 = spools.own({**tray, "filament_name": "PLA Matte rouge"}, mine)  # variante -> inchangé
    assert out2["color"] == "#FF0000"
    assert spools.needs(100.0, [{"index": 1, "share": 100.0}], usage="decoratif")[1] >= 5
    assert spools.needs(None, [{"index": 1, "share": 100.0}]) == {}  # volume inconnu -> {}
    assert (
        spools.filament_for({"type": "PLA", "filament_name": "Silk", "profile": "zzz"})
        == "PLA Silk"
    )
    assert spools.filament_for({"type": "PETG", "filament_name": "", "profile": "zzz"}) == "PETG"


async def test_importlink_get_and_fetch(monkeypatch):
    from elegoo_lab import importlink

    monkeypatch.setattr(importlink, "_check_host", lambda url: None)  # pas de DNS en test

    class Resp:
        def __init__(self, status=200, headers=None, body=b"", redirect=False):
            self.status_code = status
            self.headers = headers or {}
            self._body = body
            self.is_redirect = redirect

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def aiter_bytes(self):
            yield self._body

    class Client:
        def __init__(self, routes):
            self.routes = routes

        def stream(self, _method, url):
            return self.routes[url]

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

    a, b = "https://a.example/x", "https://b.example/y"
    loop_client = Client(
        {
            a: Resp(redirect=True, headers={"location": b}),
            b: Resp(redirect=True, headers={"location": a}),
        }
    )
    with pytest.raises(importlink.LinkError, match="Trop de redirections"):
        await importlink._get(loop_client, a)
    c404 = Client({a: Resp(status=404)})
    with pytest.raises(importlink.LinkError, match="répond 404"):
        await importlink._get(c404, a)
    c401 = Client({a: Resp(status=401)})
    with pytest.raises(importlink.LinkError, match="connecté"):
        await importlink._get(c401, a)
    cbig = Client({a: Resp(headers={"content-length": str(importlink.MAX_BYTES + 1)})})
    with pytest.raises(importlink.LinkError, match="trop gros"):
        await importlink._get(cbig, a)
    cok = Client(
        {
            a: Resp(
                headers={
                    "content-type": "application/octet-stream",
                    "content-disposition": 'attachment; filename="cube.stl"',
                },
                body=b"solid",
            )
        }
    )
    final, data, ctype, disp = await importlink._get(cok, a)
    assert (final, data) == (a, b"solid") and "cube.stl" in disp
    # fetch : page HTML -> premier lien suivi, puis fichier direct
    page = "https://site.example/page"
    cdn = "https://cdn.example.com/m.stl"
    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **kw: Client(
            {
                page: Resp(
                    headers={"content-type": "text/html"},
                    body=b'<a href="' + cdn.encode() + b'">dl</a>',
                ),
                cdn: Resp(headers={"content-type": "model/stl"}, body=b"solid m"),
                "https://x.example/f.stl": Resp(
                    headers={"content-type": "model/stl"}, body=b"solid direct"
                ),
                "https://x.example/f.txt": Resp(headers={"content-type": "text/plain"}, body=b"hi"),
            }
        ),
    )
    assert await importlink.fetch(page) == [("m.stl", b"solid m")]
    assert await importlink.fetch("https://x.example/f.stl") == [("f.stl", b"solid direct")]
    with pytest.raises(importlink.LinkError, match="ne mène pas"):
        await importlink.fetch("https://x.example/f.txt")


def test_sauvegarde_run_paths(tmp_path, monkeypatch):
    from types import SimpleNamespace

    from elegoo_lab import config, sauvegarde

    (tmp_path / "models").mkdir()
    monkeypatch.setattr(config, "MODELS_DIR", tmp_path / "models")
    monkeypatch.setattr(config, "CONFIG_FILE", tmp_path / "config.toml")
    monkeypatch.setattr(sauvegarde, "_file", lambda: tmp_path / ".sauvegarde.json")
    monkeypatch.setattr(sauvegarde, "status", lambda: {"ok": time.time()})
    assert sauvegarde.run(if_needed=True) == "sauvegarde du jour déjà faite"
    monkeypatch.setattr(sauvegarde, "status", lambda: {"ok": 0})
    with pytest.raises(RuntimeError, match="non branché"):
        sauvegarde.run(str(tmp_path))  # même disque que la bibliothèque -> refus
    disk = tmp_path / "usb"
    disk.mkdir()
    monkeypatch.setattr(sauvegarde, "_same_disk", lambda a, b: False)
    monkeypatch.setattr(
        sauvegarde.subprocess,
        "run",
        lambda *a, **k: SimpleNamespace(returncode=0, stderr="", stdout=""),
    )
    msg = sauvegarde.run(str(disk))
    assert "sauvegarde faite vers" in msg
    assert (disk / sauvegarde.LOCAL_DIR / "models").exists()
    msg2 = sauvegarde.run("maison")  # destination distante
    assert "maison" in msg2
    monkeypatch.setattr(sauvegarde, "usb_disk", lambda: None)
    with pytest.raises(RuntimeError, match="non branché"):
        sauvegarde.run()
    monkeypatch.setattr("getpass.getuser", lambda: "zz_no_such_user_zz")
    assert sauvegarde.usb_disk() is None  # aucun disque monté sous /media/<user>


def test_couches_apply_remove_and_sloped_bands(tmp_path):
    import zipfile

    import numpy as np

    from elegoo_lab import couches, threemf

    box = trimesh.creation.box((20, 20, 10))
    p = threemf.Part(
        "p", np.asarray(box.vertices, float), np.asarray(box.faces), 1, [None] * len(box.faces)
    )
    src = tmp_path / "m.3mf"
    threemf.write(
        threemf.Project([threemf.Object("m", [p])], ["#FF0000"]),
        src,
        filaments=1,
        colours=["#FF0000"],
    )
    assert isinstance(couches.apply(src, 0.2, "pentes"), int)
    with zipfile.ZipFile(src) as z:
        assert "Metadata/layer_config_ranges.xml" in z.namelist()
    couches.remove(src)
    with zipfile.ZipFile(src) as z:
        assert "Metadata/layer_config_ranges.xml" not in z.namelist()
    with pytest.raises(ValueError, match="inconnu"):
        couches.apply(src, 0.2, "inconnu")
    m = trimesh.creation.box((20, 20, 0.5))
    m.apply_transform(trimesh.transformations.rotation_matrix(np.pi / 6, [1, 0, 0]))
    bands = couches.bands(np.asarray(m.vertices), np.asarray(m.faces), 0.2, "pentes")
    assert bands and all(0.08 <= h <= 0.28 for _, _, h in bands)


def test_optimize_plan_applies_fixes(tmp_path):
    from elegoo_lab import optimize

    stem = trimesh.creation.cylinder(radius=3, height=20)
    cap = trimesh.creation.icosphere(subdivisions=2, radius=12)
    cap.apply_translation([0, 0, 20])
    src = tmp_path / "champi.stl"
    trimesh.util.concatenate([stem, cap]).export(src)
    r = optimize.plan(src)
    titles = [s["title"] for s in r["steps"]]
    assert "Supports en arbre" in titles and any("Bordure" in t for t in titles)
    assert r["supports"] == "arbre"


def test_addtext_error_paths(tmp_path, monkeypatch):
    from elegoo_lab import addtext, parametric

    repo_font = Path(parametric.__file__).parent / "fonts" / "Sacramento-Regular.ttf"
    monkeypatch.setattr(parametric, "FONT", repo_font)
    monkeypatch.setattr(parametric, "SCRIPT_FONT", repo_font)
    monkeypatch.setattr(parametric.text_section, "__defaults__", (repo_font,))
    monkeypatch.setitem(addtext.FONTS, "manuscrite", repo_font)
    monkeypatch.setitem(addtext.FONTS, "droite", repo_font)
    src = tmp_path / "m.stl"
    trimesh.creation.box((30, 30, 5)).export(src)
    open_m = trimesh.creation.box((30, 30, 5))
    open_m.faces = open_m.faces[:-2]  # plaque mais maillage ouvert
    bad = tmp_path / "bad.stl"
    open_m.export(bad)
    with pytest.raises(ValueError, match="non fermé"):
        addtext.add(bad, "ABC", size_mm=8, out=tmp_path / "o.3mf")
    out = tmp_path / "out.3mf"
    addtext.add(src, "ABC", size_mm=8, out=out)
    addtext.add(src, "ABC", size_mm=8, out=out)  # nom déjà pris -> suffixe (2)
    assert (tmp_path / "m_ABC (2).3mf").exists()
    with pytest.raises(ValueError, match="plateau"):
        addtext.add(src, "ABC", size_mm=300, out=tmp_path / "big.3mf")  # trop grand pour le plateau


async def test_sim_control_commands(printer, tmp_path, monkeypatch):
    import pycentauri.upload as upload_mod

    monkeypatch.setattr(upload_mod, "UPLOAD_PORT", 18850)  # le HTTP du Sim du fixture printer
    await printer.set_light(True)
    light = (await printer.status()).light
    assert (light.get("SecondLight") if isinstance(light, dict) else light) == 1
    await printer.set_fan_speed(model=60, auxiliary=30, chamber=10)
    await printer.set_temperatures(nozzle=205.0, bed=55.0)
    st = await printer.status()
    assert st.temp_nozzle_target == 205.0 and st.temp_bed_target == 55.0
    assert (await printer.print_history()) is not None

    def _names(resp):
        files = resp.get("file_list", []) if isinstance(resp, dict) else resp
        return [
            f if isinstance(f, str) else f.get("filename", getattr(f, "filename", None))
            for f in files
        ]

    assert "cube_20mm.gcode" in _names(await printer.list_files())
    info = await printer.disk_info()
    total = (
        info.get("total_bytes", 0) if isinstance(info, dict) else getattr(info, "total_bytes", 0)
    )
    assert total > 0
    await printer.set_auto_refill(True)
    g = tmp_path / "up.gcode"
    g.write_text("G28\n;LAYER_CHANGE\n")
    name = await printer.upload_file(g)
    assert name in _names(await printer.list_files())
    await printer.delete_files([name])
    assert name not in _names(await printer.list_files())
    await printer.start_print("cube_20mm.gcode")
    await asyncio.sleep(1.0)
    await printer.pause()
    await printer.resume()
    await printer.set_print_speed(2)
    await printer.stop()


def test_web_app_against_live_simulator(tmp_path, monkeypatch):
    import threading

    import pycentauri.camera as camera_mod
    import pycentauri.cc2 as cc2
    import pycentauri.upload as upload_mod
    from fastapi.testclient import TestClient

    # le simulateur tourne dans son propre thread : le TestClient bloque la boucle du test
    from elegoo_lab import app as app_mod, config, slicer

    monkeypatch.setattr(slicer, "filaments", lambda: ["PLA"])  # pas d'OrcaSlicer en test
    monkeypatch.setattr(slicer, "nozzles", lambda: ["0.4"])
    monkeypatch.setattr(slicer, "qualities", lambda nozzle="0.4": ["0.20 mm"])
    s = sim.Sim(port=18841, http_port=18851, print_seconds=5)
    loop = asyncio.new_event_loop()
    sim_task = None

    def run_sim():
        nonlocal sim_task
        asyncio.set_event_loop(loop)
        sim_task = loop.create_task(s.serve())
        loop.run_forever()

    th = threading.Thread(target=run_sim, daemon=True)
    th.start()
    time.sleep(0.5)
    monkeypatch.setenv("CC2_HOST", sim.SIM_HOST)
    monkeypatch.setenv("CC2_ACCESS_CODE", sim.SIM_CODE)
    monkeypatch.setenv("CC2_SERIAL", sim.SIM_SERIAL)
    sim.patch_pycentauri()
    monkeypatch.setattr(cc2, "MQTT_PORT", 18841)
    monkeypatch.setattr(upload_mod, "UPLOAD_PORT", 18851)
    monkeypatch.setattr(camera_mod, "CAMERA_PORT_CC2", 18851)
    lib = tmp_path / "models"
    lib.mkdir()
    monkeypatch.setattr(config, "MODELS_DIR", lib)
    monkeypatch.setattr(config, "CONFIG_FILE", tmp_path / "config.toml")
    monkeypatch.setattr(app_mod, "JOBS_FILE", lib / ".jobs.json")
    try:
        app = app_mod.create_app(enable_control=True)
        with TestClient(app) as client:
            for p in (
                "/status",
                "/lab/api/plateau",
                "/lab/api/bobines",
                "/lab/api/canvas/bobines",
                "/lab/api/events",
                "/lab/api/models",
            ):
                r = client.get(p)
                assert r.status_code == 200, (p, r.status_code, r.text[:200])
    finally:
        if sim_task is not None:
            loop.call_soon_threadsafe(sim_task.cancel)
        loop.call_soon_threadsafe(loop.stop)
        th.join(timeout=5)
        loop.close()


# --- INF.3 bloc 5 : vision.detect (réseau factice), colors (sidecars/preview/plate),
#     alerts (Watcher.observe + ntfy), threemf.split_plates, comfy (client HTTP factice),
#     firmware_integration, assistant (trancher/percer_ou_ajouter), cli (garde --upload),
#     app web contre Sim vivant (print/start, bobines, models) ---


def test_vision_detect_with_fake_net(monkeypatch):
    import io

    import numpy as np
    from PIL import Image

    from elegoo_lab import vision

    class FakeInput:
        name = "input"
        shape = [1, 3, 8, 8]

    class FakeNet:
        def get_inputs(self):
            return [FakeInput()]

        def run(self, _o, feed):
            assert feed["input"].shape == (1, 3, 8, 8)
            boxes = np.zeros((1, 3, 1, 4), np.float32)
            boxes[0, 0, 0] = [0.1, 0.1, 0.5, 0.5]
            boxes[0, 1, 0] = [0.6, 0.6, 0.9, 0.9]  # loin de la 1re : les deux passent le NMS
            boxes[0, 2, 0] = [0.12, 0.12, 0.52, 0.52]  # chevauche la 1re et faible confiance
            confs = np.array([[[0.9], [0.8], [0.05]]], np.float32)
            return boxes, confs

    monkeypatch.setattr(vision, "_session", lambda: FakeNet())
    img = Image.new("RGB", (16, 16), (30, 30, 30))
    buf = io.BytesIO()
    img.save(buf, format="JPEG")
    dets = vision.detect(buf.getvalue())
    assert len(dets) == 2  # la 3e est sous BOX_THRESH
    assert all(0.0 <= c <= 1.0 for c, _ in dets)
    assert dets[0][0] == pytest.approx(0.9)  # triées par confiance décroissante


def test_colors_sidecar_and_helpers(tmp_path):
    import numpy as np

    from elegoo_lab import colors, threemf

    box = trimesh.creation.box((20, 20, 10))
    p = threemf.Part(
        "p",
        np.asarray(box.vertices, float),
        np.asarray(box.faces),
        1,
        [colors.encode_state(1)] * len(box.faces),
    )
    src = tmp_path / "m.3mf"
    threemf.write(
        threemf.Project([threemf.Object("m", [p])], ["#FF0000", "#00FF00"]),
        src,
        filaments=2,
        colours=["#FF0000", "#00FF00"],
    )
    # sidecars : retouches puis marques
    assert colors.save_retouch(src, {"#00FF00": [0, 1]}) == 2
    assert colors.load_retouch(src) == {"#00FF00": [0, 1]}
    assert colors.save_retouch(src, {}, clear=True) == 0 and colors.load_retouch(src) == {}
    assert colors.save_marks(src, {"support": [0]}) == {"support": 1}
    assert colors.load_marks(src)["support"] == [0]
    with pytest.raises(ValueError, match="marque inconnue"):
        colors.save_marks(src, {"inconnue": [0]})
    with pytest.raises(ValueError, match="hors du modèle"):
        colors.save_marks(src, {"support": [99999]})
    assert colors.save_marks(src, {}, clear=True) == {} and colors.load_marks(src) == {}
    # codage des états de peinture
    code = colors.encode_state(2)
    assert 2 in colors.paint_states(code)
    assert colors.remap_paint(code, {2: 1}) == colors.encode_state(1)
    assert colors._hex((255, 0, 0)) == "#FF0000" and tuple(colors._rgb("#FF0000")) == (255, 0, 0)
    # analyse + prévisualisation + découpe en plaques
    a = colors.analyze(src)
    assert a["detected"] >= 1
    assert colors.piece_ranges(src)[0]["count"] == len(box.faces)
    assert colors.preview_glb_bytes(src)[:4] == b"glTF"
    spot = colors.tower_spot(np.array([100.0, 100.0, 0.0]), np.array([140.0, 140.0, 10.0]))
    assert spot is not None and spot[0] < 100.0  # tour d'essuyage à gauche de la pièce
    centres = np.array([[255, 0, 0], [255, 1, 1], [0, 0, 255]], float)
    c2, _l2 = colors._merge_close(centres, np.array([0, 1, 2]), np.array([10.0, 10.0, 1.0]))
    assert len(c2) <= 2  # les deux rouges fusionnent (ou la paillette saute)
    # write_plate : deux petites pièces sur un plateau
    items = [
        ("a", np.asarray(box.vertices, float), np.asarray(box.faces), None),
        ("b", np.asarray(box.vertices, float), np.asarray(box.faces), None),
    ]
    out = tmp_path / "plate.3mf"
    colors.write_plate(items, ["#FF0000"], out)
    assert out.exists() and threemf.plate_count(out) == 1


def test_alerts_watcher_observe_flow(tmp_path, monkeypatch):
    from elegoo_lab import alerts

    monkeypatch.setattr(alerts, "events_file", lambda: tmp_path / "events.json")
    monkeypatch.setattr(alerts, "photos_dir", lambda: tmp_path / "photos")
    (tmp_path / "photos").mkdir()
    w = alerts.Watcher(status=lambda: None)
    w.observe(0, 0, "", {})  # première lecture : on apprend, on n'alerte pas
    w.observe(1, 5, "cube.gcode", {})  # début d'impression
    assert "debut" in [e["kind"] for e in w.events]
    w.observe(1, 50, "cube.gcode", {"exception_status": [1201]})  # code anomalie
    w.observe(5, 50, "cube.gcode", {"filament_detect_enable": 1, "filament_detected": 0})  # pause
    w.observe(1, 50, "cube.gcode", {})  # reprise
    w.observe(9, 100, "cube.gcode", {})  # fin
    kinds = [e["kind"] for e in w.events]
    for k in ("anomalie", "filament", "reprise", "fin"):
        assert k in kinds, kinds
    w.say("bonjour le terminal")
    assert "bonjour" in str(w.term[-1])
    w.narrate({"PrintInfo": {"Filename": "cube.gcode", "CurrentLayer": 3, "TotalLayer": 100}}, 1)
    assert w.term
    # caméra : figée -> alerte unique, puis OK -> réarmement
    w.camera_frozen()
    w.camera_frozen()
    assert [e["kind"] for e in w.events].count("camera") == 1
    w.camera_ok()
    w.camera_frozen()
    assert [e["kind"] for e in w.events].count("camera") == 2


async def test_alerts_send_ntfy_mocked(monkeypatch):
    from types import SimpleNamespace

    from elegoo_lab import alerts

    assert await alerts.send_ntfy({"title": "t", "detail": "d", "level": "info"}) is False
    monkeypatch.setattr(alerts, "ntfy_url", lambda: "https://ntfy.sh/atelier")
    calls = []

    class FakeClient:
        def __init__(self, **kw):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, url, **kw):
            calls.append((url, kw))
            return SimpleNamespace(is_success=True)

    monkeypatch.setattr(httpx, "AsyncClient", FakeClient)
    ok = await alerts.send_ntfy({"title": "Fin", "detail": "terminée", "level": "ok"})
    assert ok is True and calls[0][0] == "https://ntfy.sh/atelier"


def test_threemf_split_plates(tmp_path):
    import zipfile

    from elegoo_lab import threemf

    def make_3mf(path, n_plates):
        cfg_objs = "\n".join(f'  <object id="{i}">\n  </object>' for i in range(1, n_plates + 1))
        plates = "\n".join(
            f'  <plate>\n    <metadata key="object_id" value="{i}"/>\n  </plate>'
            for i in range(1, n_plates + 1)
        )
        cfg = f'<?xml version="1.0" encoding="UTF-8"?>\n<config>\n{cfg_objs}\n{plates}\n</config>'
        objs = "\n".join(
            f'<object id="{i}"><mesh><vertices><vertex x="0" y="0" z="0"/></vertices>'
            f'<triangles><triangle v1="0" v2="0" v3="0"/></triangles></mesh></object>'
            for i in range(1, n_plates + 1)
        )
        items = "\n".join(
            f'  <item objectid="{i}" transform="1 0 0 0 1 0 0 0 1 {100 * i} 200 0"/>'
            for i in range(1, n_plates + 1)
        )
        model = (
            '<?xml version="1.0" encoding="UTF-8"?>\n<model unit="millimeter">\n'
            f"<resources>\n{objs}\n </resources>\n <build>\n{items}\n </build>\n</model>\n"
        )
        with zipfile.ZipFile(path, "w") as z:
            z.writestr("Metadata/model_settings.config", cfg)
            z.writestr("Metadata/project_settings.config", '{"printable_area": ["0x0", "256x256"]}')
            z.writestr("3D/3dmodel.model", model)

    two = tmp_path / "deux.3mf"
    make_3mf(two, 2)
    assert threemf.plate_count(two) == 2
    (tmp_path / "out").mkdir()
    out = threemf.split_plates(two, tmp_path / "out")
    assert len(out) == 2
    for f in out:
        with zipfile.ZipFile(f) as z:
            assert "3D/3dmodel.model" in z.namelist()
    one = tmp_path / "un.3mf"
    make_3mf(one, 1)
    assert threemf.split_plates(one) == []  # un seul plateau : rien à découper


def test_comfy_client_mocked(tmp_path, monkeypatch):
    from elegoo_lab import comfy as comfy_mod

    class FakeResp:
        status_code = 200

        def __init__(self, payload, content=b"GLB"):
            self._p = payload
            self.content = content

        def json(self):
            return self._p

        @property
        def text(self):
            return json.dumps(self._p)

        def raise_for_status(self):
            return None

    class FakeClient:
        def __init__(self, base_url=None, timeout=None):
            pass

        def get(self, url, **_kw):
            if "system_stats" in url:
                return FakeResp({"devices": [{"name": "GPU"}]})
            if "history" in url:
                return FakeResp({"p1": {"outputs": {"9": {"gables": [{"filename": "m.glb"}]}}}})
            return FakeResp({})

        def post(self, url, **_kw):
            if url.endswith("/prompt"):
                return FakeResp({"prompt_id": "p1"})
            if "/upload" in url:
                return FakeResp({"name": "img.png", "subfolder": "", "type": "input"})
            return FakeResp({})

        def delete(self, _url, **_kw):
            return FakeResp({})

    monkeypatch.setattr(comfy_mod.httpx, "Client", FakeClient)
    c = comfy_mod.Comfy("http://comfy:8188")
    assert c.stats()["devices"][0]["name"] == "GPU"
    assert c.known("p1") and not c.known("inconnu")
    c.free()
    img = tmp_path / "i.png"
    img.write_bytes(b"x")
    assert c.upload_image(img) == "img.png"
    assert c.queue({"wf": 1}) == "p1"
    out = c.wait("p1", poll=0.01, timeout=5)  # wait renvoie déjà le bloc "outputs"
    files = c.download_outputs(out, tmp_path, "t")
    assert files and files[0].exists() and files[0].suffix == ".glb"
    # workflows : chargement + generate de bout en bout
    wf_dir = tmp_path / "workflows"
    wf_dir.mkdir()
    (wf_dir / "w.json").write_text('{"3": {"class_type": "CLIP", "inputs": {"text": ""}}}')
    (wf_dir / "w.map.json").write_text('{"prompt": ["3", "text"]}')
    monkeypatch.setattr(comfy_mod, "WORKFLOWS", wf_dir)
    wf, mp = comfy_mod.load_workflow("w")
    assert wf["3"]["class_type"] == "CLIP" and mp["prompt"] == ["3", "text"]
    with pytest.raises(comfy_mod.ComfyError, match="introuvable"):
        comfy_mod.load_workflow("inconnu")
    dest = tmp_path / "gen"
    dest.mkdir()
    files = comfy_mod.generate(c, "w", dest, prompt="un cube", seed=42)
    assert files and files[0].exists()


def test_firmware_integration_helpers():
    from types import SimpleNamespace

    from elegoo_lab import firmware_integration as fi

    mgr = fi.firmware_manager
    try:
        info = fi.check_firmware_on_connection(SimpleNamespace(firmware_version="02.01.00.00"))
        assert info["safe_mode"] is False
        ok, msg = fi.can_execute_printer_command("M104")
        assert ok is True and msg == ""
        info = fi.check_firmware_on_connection(SimpleNamespace(firmware_version="00.00.00.00"))
        assert info["safe_mode"] is True
        from elegoo_lab import firmware

        blocked_cmd = next(iter(firmware.BLOCKED_COMMANDS_IN_SAFE_MODE))
        ok, msg = fi.can_execute_printer_command(blocked_cmd)
        assert ok is False and msg
        lst = fi.get_blocked_commands_list()
        assert lst and all(set(d) >= {"command", "reason", "action"} for d in lst)
        status = fi.get_firmware_status_for_ui()
        assert "mode s" in status["user_message"]
        info = fi.check_firmware_on_connection(SimpleNamespace(firmware_version=None))
        assert "safe_mode" in info
    finally:
        mgr.set_detected_version("02.01.00.00")  # état global : on remet un firmware supporté


def test_assistant_trancher_and_forme_tools(tmp_path, monkeypatch):
    from elegoo_lab import assistant, config, printprep

    lib = tmp_path / "models"
    lib.mkdir()
    monkeypatch.setattr(config, "MODELS_DIR", lib)
    monkeypatch.setattr(config, "CONFIG_FILE", tmp_path / "config.toml")
    trimesh.creation.box((20, 20, 20)).export(lib / "cube.stl")
    usage = next(iter(printprep.USAGES))

    def fake_prep(src, **kw):
        return {
            "gcode": ["cube.gcode"],
            "time": "1 h",
            "total_m": 12.5,
            "warnings": ["w1"],
            "slots": [{"slot": 1, "filament": "PLA", "metres": 12.5}],
            "temps": {"nozzle": [220], "bed": 60},
        }

    monkeypatch.setattr(printprep, "prepare_and_slice", fake_prep)
    r = assistant.run_tool(
        "trancher", {"usage": usage, "supports": "arbre", "remplissage": 30}, "cube.stl"
    )
    assert "erreur" not in r and r["usage"] == usage
    assert r["slots"][0]["bobine"] == 1 and "buse 220" in r["temperatures"]

    def boom(src, **kw):
        raise ValueError("nope")

    monkeypatch.setattr(printprep, "prepare_and_slice", boom)
    r2 = assistant.run_tool("trancher", {}, "cube.stl")
    assert "nope" in r2["erreur"]
    r3 = assistant.run_tool(
        "percer_ou_ajouter",
        {
            "forme": "cylindre",
            "operation": "percer",
            "taille": [6, 6, 30],
            "position": [10, 10, 5],
            "couleur": 1,
        },
        "cube.stl",
    )
    assert "erreur" not in r3, r3
    r4 = assistant.run_tool(
        "percer_ou_ajouter",
        {"forme": "zzz", "operation": "percer", "taille": [1, 1, 1]},
        "cube.stl",
    )
    assert "erreur" in r4


def test_cli_slice_upload_guard(tmp_path, monkeypatch):
    from typer.testing import CliRunner

    from elegoo_lab import cli, config, printprep

    lib = config.MODELS_DIR
    trimesh.creation.box((10, 10, 10)).export(lib / "cube.stl")

    def fake_prepare(src, **kw):
        (lib / "cube.gcode").write_text("G28\n")
        return {
            "gcode": ["cube.gcode"],
            "layers": 5,
            "time": "10 min",
            "filament_m": 3.0,
            "total_m": 3.0,
            "purge_m": [],
            "slots": [],
            "warnings": [],
            "colour_changes": 0,
            "split": False,
            "temps": {},
        }

    monkeypatch.setattr(printprep, "prepare_and_slice", fake_prepare)
    monkeypatch.delenv("PYCENTAURI_ENABLE_CONTROL", raising=False)
    r = CliRunner().invoke(cli.app, ["slice", "cube.stl", "--upload"])
    assert r.exit_code == 2 and "control" in r.output  # --upload sans --control : refusé
    sent = []
    monkeypatch.setattr(cli, "_send", lambda path, start: sent.append((path, start)))
    monkeypatch.setenv("PYCENTAURI_ENABLE_CONTROL", "1")
    r = CliRunner().invoke(cli.app, ["slice", "cube.stl", "--upload", "--start"])
    assert r.exit_code == 0 and sent and sent[0][1] is True


def test_web_live_sim_more_endpoints(tmp_path, monkeypatch):
    import threading

    import pycentauri.camera as camera_mod
    import pycentauri.cc2 as cc2
    import pycentauri.upload as upload_mod
    from fastapi.testclient import TestClient

    from elegoo_lab import app as app_mod, config, slicer

    monkeypatch.setattr(slicer, "filaments", lambda: ["PLA"])  # pas d'OrcaSlicer en test
    monkeypatch.setattr(slicer, "nozzles", lambda: ["0.4"])
    monkeypatch.setattr(slicer, "qualities", lambda nozzle="0.4": ["0.20 mm"])
    s = sim.Sim(port=18842, http_port=18852, print_seconds=30)
    loop = asyncio.new_event_loop()
    sim_task = None

    def run_sim():
        nonlocal sim_task
        asyncio.set_event_loop(loop)
        sim_task = loop.create_task(s.serve())
        loop.run_forever()

    th = threading.Thread(target=run_sim, daemon=True)
    th.start()
    time.sleep(0.5)
    monkeypatch.setenv("CC2_HOST", sim.SIM_HOST)
    monkeypatch.setenv("CC2_ACCESS_CODE", sim.SIM_CODE)
    monkeypatch.setenv("CC2_SERIAL", sim.SIM_SERIAL)
    sim.patch_pycentauri()
    monkeypatch.setattr(cc2, "MQTT_PORT", 18842)
    monkeypatch.setattr(upload_mod, "UPLOAD_PORT", 18852)
    monkeypatch.setattr(camera_mod, "CAMERA_PORT_CC2", 18852)
    lib = tmp_path / "models"
    lib.mkdir()
    monkeypatch.setattr(config, "MODELS_DIR", lib)
    monkeypatch.setattr(config, "CONFIG_FILE", tmp_path / "config.toml")
    monkeypatch.setattr(app_mod, "JOBS_FILE", lib / ".jobs.json")
    hdrs = {"Origin": "http://testserver"}
    try:
        app = app_mod.create_app(enable_control=True)
        with TestClient(app) as client:
            stl = trimesh.creation.box((20, 20, 20)).export(file_type="stl")
            r = client.post("/lab/api/models", files={"file": ("cube.stl", stl)}, headers=hdrs)
            assert r.status_code == 200, r.text
            r = client.get("/lab/api/models/cube.stl/info")
            assert r.status_code == 200 and "size_mm" in r.json(), r.text
            r = client.post(
                "/lab/api/bobines/0",
                json={"restant_g": 500, "poids_g": 1000, "prix_kg": 20, "nouvelle": False},
                headers=hdrs,
            )
            assert r.status_code == 200, r.text
            assert client.get("/lab/api/bobines/check/cube.stl").status_code == 200
            r = client.post(
                "/lab/api/print/start", json={"filename": "cube_20mm.gcode"}, headers=hdrs
            )
            assert r.status_code == 200 and r.json().get("ok"), r.text
            r = client.get("/status")
            assert r.status_code == 200 and "cube_20mm.gcode" in r.text, r.text[:300]
    finally:
        if sim_task is not None:
            loop.call_soon_threadsafe(sim_task.cancel)
        loop.call_soon_threadsafe(loop.stop)
        th.join(timeout=5)
        loop.close()


# --- R2.1 : mode Débutant (bascule persistée dans config.toml, endpoints, assets UI) ---


def test_config_ui_mode_defaults(tmp_path, monkeypatch):
    from elegoo_lab import config

    monkeypatch.setattr(config, "CONFIG_FILE", tmp_path / "config.toml")
    assert config.ui_mode() == "debutant"  # installation neuve
    (tmp_path / "config.toml").write_text('[interface]\nlangue = "fr"\n')
    assert config.ui_mode() == "avance"  # config existante sans la clé : utilisateur déjà connu
    config.save("interface", mode="debutant")
    assert config.ui_mode() == "debutant"
    assert 'mode = "debutant"' in (tmp_path / "config.toml").read_text()
    config.save("interface", mode="avance")
    assert config.ui_mode() == "avance"


def test_web_mode_endpoint(web):
    from elegoo_lab import config

    client, _lib = web
    hdrs = {"Origin": "http://testserver"}
    r = client.get("/lab/api/mode")
    assert r.status_code == 200 and r.json()["mode"] in ("debutant", "avance"), r.text
    r = client.post("/lab/api/mode", json={"mode": "avance"}, headers=hdrs)
    assert r.status_code == 200 and r.json()["mode"] == "avance"
    assert config.ui_mode() == "avance"  # persisté dans config.toml
    r = client.post("/lab/api/mode", json={"mode": "bidule"}, headers=hdrs)
    assert r.status_code == 422


def test_mode_debutant_assets():
    import json as _json

    web = Path(config.ROOT) / "src" / "elegoo_lab" / "web"
    html = (web / "index.html").read_text(encoding="utf-8")
    assert 'id="mode"' in html and "js/mode.js" in html and 'id="mode-t"' in html
    assert 'id="adv" class="advanced"' in html  # réglages avancés masqués en mode débutant
    assert 'class="ln-more advanced"' in html
    assert "btn ghost advanced" in html  # lien « Interface avancée » masqué aussi
    css = (web / "css" / "app.css").read_text(encoding="utf-8")
    assert "body.mode-debutant .advanced" in css
    js = (web / "js" / "mode.js").read_text(encoding="utf-8")
    assert "/lab/api/mode" in js and "mode-debutant" in js
    en = _json.loads((web / "i18n" / "en.json").read_text(encoding="utf-8"))
    for k in ("Débutant", "Avancé", "Mode", "Mode Débutant / Avancé"):
        assert k in en["exact"] and en["exact"][k], k


# --- R2.2 : schéma interactif du CANVAS (bobines SVG, bobine active, i18n) ---


def test_canvas_spools_schema_assets():
    import json as _json

    web = Path(config.ROOT) / "src" / "elegoo_lab" / "web"
    js = (web / "js" / "printer.js").read_text(encoding="utf-8")
    assert (
        'class="spool-c"' in js and 'circle class="fill"' in js
    )  # bobine SVG avec couleur actuelle
    assert "tag-now" in js and "en cours" in js  # bobine active pendant l'impression
    css = (web / "css" / "app.css").read_text(encoding="utf-8")
    assert ".tray .spool-c .rim" in css and ".tray.active .spool-c" in css and ".tag-now" in css
    en = _json.loads((web / "i18n" / "en.json").read_text(encoding="utf-8"))
    assert en["exact"].get("Vide") == "Empty"
    assert any(p[0] == "Modifier le stock de la bobine {}" for p in en["patterns"])


# --- R2.3 : notifications intelligentes (filtres par niveau, historique des alertes) ---


def test_events_historique_endpoint(tmp_path, monkeypatch, fake_printer_env):
    from fastapi.testclient import TestClient

    from elegoo_lab import app as app_mod, config

    lib = tmp_path / "models"
    lib.mkdir()
    monkeypatch.setattr(config, "MODELS_DIR", lib)
    monkeypatch.setattr(config, "CONFIG_FILE", tmp_path / "config.toml")
    monkeypatch.setattr(app_mod, "JOBS_FILE", lib / ".jobs.json")
    events = [
        {
            "id": "1",
            "t": 1000,
            "kind": "debut",
            "level": "info",
            "title": "Impression lancée",
            "detail": "a.gcode",
        },
        {
            "id": "2",
            "t": 2000,
            "kind": "filament",
            "level": "bad",
            "title": "Plus de filament",
            "detail": "",
        },
        {
            "id": "3",
            "t": 3000,
            "kind": "fin",
            "level": "ok",
            "title": "Impression terminée",
            "detail": "b.gcode",
            "bilan": "x",
        },
    ]
    (lib / ".events.json").write_text(json.dumps(events))
    app = app_mod.create_app(enable_control=True)
    with TestClient(app) as client:
        r = client.get("/lab/api/events/historique")  # fichier persisté, récent d'abord
        assert r.status_code == 200, r.text
        hist = r.json()
        assert [e["kind"] for e in hist] == ["fin", "filament", "debut"]
        assert hist[0]["level"] == "ok" and hist[1]["level"] == "bad"
        r2 = client.get("/lab/api/events")  # 50 dernières en mémoire
        assert r2.status_code == 200 and len(r2.json()) == 3


def test_notifications_filters_assets():
    import json as _json

    web = Path(config.ROOT) / "src" / "elegoo_lab" / "web"
    html = (web / "index.html").read_text(encoding="utf-8")
    assert 'id="ev-filters"' in html and 'data-lvl="bad"' in html and 'data-lvl="warn"' in html
    assert 'id="ev-hist"' in html
    js = (web / "js" / "alerts.js").read_text(encoding="utf-8")
    assert "/events/historique" in js and "evFilter" in js and "cc2-ev-filter" in js
    css = (web / "css" / "app.css").read_text(encoding="utf-8")
    assert ".ev-filters" in css
    en = _json.loads((web / "i18n" / "en.json").read_text(encoding="utf-8"))
    for k in ("Toutes", "Critiques", "Avertissements", "Historique", "Aucune alerte de ce niveau."):
        assert k in en["exact"] and en["exact"][k], k


# --- R2.4 : backup automatique guidé depuis l'UI (helpers auto, endpoints, assets) ---


def test_sauvegarde_auto_helpers(tmp_path, monkeypatch):
    from types import SimpleNamespace

    from elegoo_lab import sauvegarde

    units = tmp_path / "units"
    monkeypatch.setattr(sauvegarde, "UNIT_DIR", units)
    calls = []
    monkeypatch.setattr(
        sauvegarde,
        "_systemctl",
        lambda *a, check=True: calls.append(a) or SimpleNamespace(stdout="", returncode=0),
    )
    msg = sauvegarde.install_auto("/mnt/usb")
    assert "installée" in msg and (units / "cc2-sauvegarde.timer").exists()
    assert (units / "cc2-sauvegarde.service").exists()
    assert "--vers /mnt/usb" in (units / "cc2-sauvegarde.service").read_text()
    assert ("enable", "--now", "cc2-sauvegarde.timer") in calls
    msg2 = sauvegarde.remove_auto()
    assert "retirée" in msg2
    assert not (units / "cc2-sauvegarde.timer").exists()
    assert ("disable", "--now", "cc2-sauvegarde.timer") in calls


def test_web_backup_endpoints(web, monkeypatch):
    from types import SimpleNamespace

    from elegoo_lab import sauvegarde

    client, _lib = web
    hdrs = {"Origin": "http://testserver"}
    monkeypatch.setattr(
        sauvegarde,
        "status",
        lambda: {"ok": 1700000000, "vers": "/usb", "essai": 1700000100, "erreur": ""},
    )
    monkeypatch.setattr(sauvegarde, "usb_disk", lambda: None)
    monkeypatch.setattr(
        sauvegarde, "overdue", lambda: "Aucune sauvegarde de la bibliothèque n'a encore réussi."
    )
    monkeypatch.setattr(sauvegarde, "UNIT_DIR", _lib / "units")
    r = client.get("/lab/api/sauvegarde")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["disque"] is False and body["auto"] is False
    assert "jamais" not in body["en_retard"] and "Aucune" in body["en_retard"]
    # POST sans contrôle -> 403 (pas de manager démarré dans ce fixture)
    assert client.post("/lab/api/sauvegarde/faire", headers=hdrs).status_code == 403
    assert (
        client.post("/lab/api/sauvegarde/auto", json={"activer": True}, headers=hdrs).status_code
        == 403
    )
    # avec contrôle : copie immédiate + timer auto (fonctions mockées)
    client.app.state.manager = SimpleNamespace(enable_control=True)
    monkeypatch.setattr(sauvegarde, "run", lambda *a, **k: "sauvegarde faite vers /usb")
    r = client.post("/lab/api/sauvegarde/faire", headers=hdrs)
    assert r.status_code == 200 and r.json()["ok"] and "faite" in r.json()["message"]

    def boom(*a, **k):
        raise RuntimeError("disque de sauvegarde non branché")

    monkeypatch.setattr(sauvegarde, "run", boom)
    r = client.post("/lab/api/sauvegarde/faire", headers=hdrs)
    assert r.status_code == 409 and "non branché" in r.json()["detail"]
    monkeypatch.setattr(sauvegarde, "install_auto", lambda vers=None: "auto installée")
    monkeypatch.setattr(sauvegarde, "remove_auto", lambda: "auto retirée")
    r = client.post(
        "/lab/api/sauvegarde/auto", json={"activer": True, "vers": "/mnt/usb"}, headers=hdrs
    )
    assert r.status_code == 200 and "installée" in r.json()["message"]
    r = client.post("/lab/api/sauvegarde/auto", json={"activer": False}, headers=hdrs)
    assert r.status_code == 200 and "retirée" in r.json()["message"]


def test_backup_ui_assets():
    import json as _json

    web = Path(config.ROOT) / "src" / "elegoo_lab" / "web"
    html = (web / "index.html").read_text(encoding="utf-8")
    assert 'id="bk-now"' in html and 'id="bk-auto"' in html and 'id="bk-status"' in html
    assert 'id="bk-vers"' in html and "Sauvegarder la bibliothèque" in html
    js = (web / "js" / "setup.js").read_text(encoding="utf-8")
    assert "/sauvegarde/faire" in js and "/sauvegarde/auto" in js and "loadBackup" in js
    en = _json.loads((web / "i18n" / "en.json").read_text(encoding="utf-8"))
    for k in (
        "Sauvegarder maintenant",
        "Activer la sauvegarde auto",
        "Sauvegarder la bibliothèque",
    ):
        assert k in en["exact"] and en["exact"][k], k


# --- R2.5 : assistant guidé (endpoint workflow + checklist pas à pas dans le chat) ---


def test_workflow_endpoint(web):
    client, lib = web
    hdrs = {"Origin": "http://testserver"}
    stl = trimesh.creation.box((20, 20, 20)).export(file_type="stl")
    r = client.post("/lab/api/models", files={"file": ("cube.stl", stl)}, headers=hdrs)
    assert r.status_code == 200, r.text
    r = client.get("/lab/api/models/cube.stl/workflow")
    assert r.status_code == 200 and r.json() == {"model": "cube.stl", "gcode": None}, r.text
    (lib / "cube_0.20mm_PLA.gcode").write_text("G28\n")
    r = client.get("/lab/api/models/cube.stl/workflow")
    assert r.json()["gcode"] == "cube_0.20mm_PLA.gcode"  # étape « trancher » déjà faite
    assert client.get("/lab/api/models/zzz.stl/workflow").status_code == 404
    assert client.get("/lab/api/models/cube_0.20mm_PLA.gcode/workflow").status_code == 400


def test_workflow_ui_assets():
    import json as _json

    web = Path(config.ROOT) / "src" / "elegoo_lab" / "web"
    html = (web / "index.html").read_text(encoding="utf-8")
    assert "data-wf" in html and "Workflow guidé" in html
    js = (web / "js" / "lab.js").read_text(encoding="utf-8")
    assert "workflowShow" in js and "/workflow" in js and "wf-step" in js
    css = (web / "css" / "app.css").read_text(encoding="utf-8")
    assert ".wf .wf-step" in css
    en = _json.loads((web / "i18n" / "en.json").read_text(encoding="utf-8"))
    for k in ("Workflow guidé :", "Voir la fiche de la pièce", "Trancher pour la CC2"):
        assert k in en["exact"] and en["exact"][k], k


# --- R2.6 : aide intégrée — dialog #help, 3 tutos animés SVG/CSS, i18n ---


def test_help_tutos_assets():
    import json as _json

    web = Path(config.ROOT) / "src" / "elegoo_lab" / "web"
    html = (web / "index.html").read_text(encoding="utf-8")
    assert 'id="help-open"' in html and '<dialog id="help"' in html and 'id="i-help"' in html
    assert html.count('<article class="tuto">') == 3  # 3 tutos
    assert html.count('class="tuto-v"') == 3  # 3 SVG animés, markup pur (pas de vidéo)
    assert "github.com/JEANPHI5507/atelier-cc2/tree/main/guide" in html  # lien vers les guides
    js = (web / "js" / "app.js").read_text(encoding="utf-8")
    assert "$('help-open')" in js and "$('help').showModal()" in js
    css = (web / "css" / "app.css").read_text(encoding="utf-8")
    assert ".tutos" in css and ".tuto-v" in css
    assert "@media (prefers-reduced-motion: no-preference)" in css  # animations coupables
    for kf in (
        "@keyframes tuto-spool",
        "@keyframes tuto-prog",
        "@keyframes tuto-eye",
        "@keyframes tuto-scan",
    ):
        assert kf in css, kf
    en = _json.loads((web / "i18n" / "en.json").read_text(encoding="utf-8"))
    for k in (
        "Aide et tutoriels",
        "Charger le CANVAS",
        "Préparer et lancer une impression",
        "Surveiller l'impression",
        "Tous les guides détaillés sur GitHub",
    ):
        assert k in en["exact"] and en["exact"][k], k
