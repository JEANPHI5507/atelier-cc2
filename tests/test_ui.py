"""Interface tests: a real browser clicks through a throw-away workshop.

A fake printer and a dashboard run on their own ports, with their own library and config, so the
workshop in use is never touched. Uses the system Chrome through Playwright; skipped without it.
"""

import json
import os
import shutil
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

import pytest
import trimesh


def _find_chrome() -> str | None:
    found = shutil.which("google-chrome") or shutil.which("chromium")
    if found:
        return found
    try:  # fallback: the browser shipped by playwright itself
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            return p.chromium.executable_path
    except Exception:
        return None


CHROME = _find_chrome()
pytestmark = pytest.mark.skipif(not CHROME, reason="Chrome absent")
TESTS = Path(__file__).parent


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _wait(url: str, timeout: float = 40) -> None:
    end = time.time() + timeout
    while time.time() < end:
        try:
            urllib.request.urlopen(url, timeout=2)
            return
        except Exception:
            time.sleep(0.3)
    raise RuntimeError(f"{url} ne répond pas")


@pytest.fixture(scope="module")
def site(tmp_path_factory):
    root = tmp_path_factory.mktemp("atelier")
    lib = root / "models"
    lib.mkdir()
    trimesh.creation.box((20, 20, 20)).export(lib / "cube.stl")
    cube = trimesh.creation.box((20, 20, 20))  # same cube, one face removed: an open mesh to repair
    trimesh.Trimesh(cube.vertices, cube.faces[:-1], process=False).export(lib / "ouvert.stl")
    two = trimesh.creation.box((20, 20, 20))  # a two-colour cube for the brush
    two.unmerge_vertices()
    two.visual = trimesh.visual.ColorVisuals(
        two, face_colors=[[200, 0, 0, 255]] * 6 + [[0, 120, 0, 255]] * 6
    )
    two.export(lib / "deux.glb")
    sample = Path(__file__).parents[1] / "models" / "calibration_cube_20mm_0.20mm_PLA.gcode"
    if sample.exists():  # a ready G-code for the slicing view
        shutil.copy(sample, lib / "essai.gcode")
    env = {
        **os.environ,
        "CC2_MODELS": str(lib),
        "CC2_CONFIG": str(root / "config.toml"),
        "CC2_SIM_PORT": str(_free_port()),
        "CC2_SIM_HTTP_PORT": str(_free_port()),
    }
    port = _free_port()
    sim = subprocess.Popen(
        [sys.executable, str(TESTS / "fakeprinter.py"), "--seconds", "12"],
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    time.sleep(1.0)
    dash = subprocess.Popen(
        [sys.executable, str(TESTS / "run_dash.py"), "--control", "dash", "--port", str(port)],
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    base = f"http://127.0.0.1:{port}"
    try:
        _wait(base + "/lab/")
        _wait(base + "/status")
        yield {"base": base, "lib": lib}
    finally:
        for p in (dash, sim):
            p.terminate()
            try:
                p.wait(10)
            except subprocess.TimeoutExpired:
                p.kill()


@pytest.fixture(scope="module")
def browser():
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        b = p.chromium.launch(
            executable_path=CHROME,
            headless=True,
            args=["--use-angle=swiftshader", "--enable-unsafe-swiftshader"],
        )  # WebGL without a GPU
        yield b
        b.close()


@pytest.fixture
def page(browser, site):
    ctx = browser.new_context(locale="fr-FR", viewport={"width": 1366, "height": 860})
    pg = ctx.new_page()
    pg.errors = []
    pg.on("pageerror", lambda e: pg.errors.append(str(e)))
    pg.on(
        "console",
        lambda m: m.type == "error"
        and "WebGL" not in m.text
        and "404" not in m.text
        and pg.errors.append(m.text),
    )
    pg.goto(site["base"] + "/lab/")
    pg.wait_for_selector("#files .file")
    yield pg
    ctx.close()


def api(site, path, body=None):
    req = urllib.request.Request(
        site["base"] + path,
        method="POST" if body is not None else "GET",
        data=json.dumps(body).encode() if body is not None else None,
        headers={"Content-Type": "application/json"},
    )
    return json.loads(urllib.request.urlopen(req, timeout=30).read())


def test_every_tab_opens_without_script_errors(page):
    for tab, marker in (("start", "#start"), ("ui", "#pv"), ("gal", "#gal"), ("lab", "#lab")):
        page.click(f"#t-{tab}")
        page.wait_for_selector(f"{marker}:not([hidden])")
        page.wait_for_timeout(600)
    page.click("#ev-open")
    page.wait_for_selector("#ev[open]")
    assert page.errors == []


def test_from_model_to_print(page, site):
    page.click("#files .file[data-n='cube.stl']")
    # one colour, no colour of its own: the spool already in the CANVAS is picked without asking
    page.wait_for_selector("#c-match:has-text('Imprimé avec la bobine chargée 1')")
    assert "PLA Silk Blanc" in page.inner_text("#c-spools")
    page.wait_for_selector("#usage [data-usage='fonctionnel']")
    page.click("#usage [data-usage='fonctionnel']")
    assert page.input_value("#quality") == "0.20mm Strength"
    page.wait_for_selector("#advice .ah:has-text('Conseiller')", timeout=20000)
    page.click("#go")
    page.wait_for_selector("#result .result .stats", timeout=120000)
    assert " g" in page.inner_text("#result .stats")
    page.click("#result [data-send='start']")
    page.wait_for_selector("#launch[open] #ln-go")
    page.check("#ln-level")
    page.click("#ln-go")
    page.wait_for_selector("#toasts :text('Impression lancée')", timeout=60000)
    st = api(site, "/status")
    assert st["print_status"] not in (0, 8, 9)
    assert st["filename"].startswith("cube")
    assert page.errors == []


def test_printer_tab_forms_reach_the_server(page, site):
    page.click("#t-ui")
    page.wait_for_selector("#pv-trays [data-tray]")
    page.click("#pv-trays [data-tray='1']")
    page.wait_for_selector("#tray-dlg[open]")
    page.fill("#tray-left", "333")
    page.fill("#tray-price", "27")
    page.click("#tray-save")
    page.wait_for_function("!document.getElementById('tray-dlg').open")
    tray = next(t for t in api(site, "/lab/api/bobines")["trays"] if t["tray"] == 1)
    assert tray["restant_g"] == 333
    assert tray["prix_kg"] == 27
    page.click("#sv-tl")  # timelapse off
    page.wait_for_timeout(800)
    assert api(site, "/lab/api/surveillance")["timelapse"] is False
    page.click("#sv-tl")
    page.click("#mc-check")  # machine default option
    for _ in range(25):  # the server writes it behind, occasionally slower than 800 ms
        if api(site, "/lab/api/lancement")["printer_check"] is False:
            break
        page.wait_for_timeout(200)
    else:
        raise AssertionError("printer_check n'est pas passé à False")
    if page.is_visible("#mt-list .mt-more > summary"):  # tasks that are not due are folded away
        page.click("#mt-list .mt-more > summary")
    page.click("#mt-list [data-mt='plateau']")
    page.wait_for_selector("#toasts :text('Entretien noté')")
    assert page.errors == []


def test_firmware_limits_are_listed_on_the_printer_tab(page, site):
    page.click("#t-ui")
    page.wait_for_selector("#fw-blocked li", timeout=20000)
    assert "homing" in page.inner_text("#fw-blocked")
    assert page.errors == []


def test_nozzle_position_is_shown(page):
    page.click("#t-ui")
    page.wait_for_selector("#pv-pos:not([hidden])", timeout=20000)
    page.wait_for_function("document.getElementById('pv-pos-x').textContent !== '–'")
    x = float(page.text_content("#pv-pos-x").replace(",", "."))
    assert 0 <= x <= 256
    assert page.get_attribute("#pv-pos-dot", "cx") != "-50"
    assert page.errors == []


def test_phone_layout(browser, site):
    ctx = browser.new_context(
        viewport={"width": 375, "height": 812}, is_mobile=True, has_touch=True
    )
    pg = ctx.new_page()
    pg.goto(site["base"] + "/lab/")
    pg.wait_for_selector("#pv:not([hidden])")  # a phone opens on the printer
    assert not pg.is_visible("#t-start")  # the first-day guide is for the PC
    width = "document.documentElement.scrollWidth"
    for tab in ("lab", "ui", "gal"):
        pg.click(f"#t-{tab}")
        pg.wait_for_timeout(700)
        assert pg.evaluate(width) <= 376, f"débordement horizontal dans l'onglet {tab}"
    pg.click("#t-lab")
    pg.wait_for_selector("#files .file")
    assert pg.is_visible("#mnav")
    pg.click("#files .file[data-n='cube.stl']")
    pg.wait_for_function("document.getElementById('lab').dataset.m === 'view'")
    pg.click("#mnext")
    assert pg.evaluate("document.getElementById('lab').dataset.m") == "prep"
    ctx.close()


def test_finished_print_lands_in_gallery(page, site):
    for _ in range(60):  # the simulator prints in ~12 s
        if any(e["issue"] != "en cours" for e in api(site, "/lab/api/galerie")):
            break
        time.sleep(1)
    page.click("#t-gal")
    page.wait_for_selector("#gal-list .gcard")
    assert "cube" in page.inner_text("#gal-list")
    assert page.errors == []


def test_tablet_dashboard(browser, site):
    ctx = browser.new_context(viewport={"width": 1280, "height": 800}, has_touch=True)
    pg = ctx.new_page()
    errors = []
    pg.on("pageerror", lambda e: errors.append(str(e)))
    pg.goto(site["base"] + "/lab/tableau.html")
    pg.click("#go")
    pg.wait_for_function("document.getElementById('state').textContent !== '…'")
    pg.wait_for_selector("#spools .sp")
    assert pg.inner_text("#temps").count("°") >= 3
    assert pg.evaluate("document.documentElement.scrollWidth") <= 1280
    if (
        pg.evaluate("document.getElementById('idle').hidden") is False
    ):  # nothing printing: last print shown
        pg.wait_for_selector("#last b, #last .note")
    pg.click("#b-night")
    assert pg.evaluate("document.body.classList.contains('nuit')")
    pg.click("#b-night")
    pg.click("#back")  # back to the workshop…
    pg.wait_for_url("**/lab/")
    pg.wait_for_selector("#files .file")
    pg.click("#board-open")  # …and to the dashboard, same window
    pg.wait_for_url("**/lab/tableau.html")
    assert errors == []
    ctx.close()


@pytest.mark.parametrize("width", [700, 1024])
def test_no_sideways_scroll_on_tablet_widths(browser, site, width):
    ctx = browser.new_context(viewport={"width": width, "height": 800})
    pg = ctx.new_page()
    pg.goto(site["base"] + "/lab/")
    pg.wait_for_selector("#files .file")
    for tab in ("lab", "ui", "gal", "start"):
        pg.click(f"#t-{tab}")
        pg.wait_for_timeout(400)
        assert (
            pg.evaluate("document.documentElement.scrollWidth") <= width
        ), f"{tab} déborde à {width} px"
    ctx.close()


def test_interface_files_are_revalidated(site):
    for path in ("/lab/", "/lab/js/app.js", "/lab/css/app.css", "/lab/tableau.html"):
        r = urllib.request.urlopen(site["base"] + path)
        assert (
            r.headers["Cache-Control"] == "no-cache"
        ), path  # an update reaches the tablet at once


def test_a_turned_part_stays_on_the_plate(page, site):
    """A part away from its file's origin shows centred on the plate; laid down or turned, it stays there, resting on it."""
    tour = trimesh.creation.box((10, 10, 80))
    tour.apply_translation((60, 40, 40))  # away from the file's origin, like most exported 3MF
    tour.export(site["lib"] / "tour.stl")
    page.reload()
    page.click("#files .file[data-n='tour.stl']")
    page.wait_for_selector("#orients [data-orient]", timeout=30000)
    page.wait_for_timeout(1000)
    where = """() => Promise.all([import('/lab/js/lab.js'), import('three')]).then(([m, T]) => {
               const b = new T.Box3().setFromObject(m.current), c = b.getCenter(new T.Vector3()); return [c.x, c.y, b.min.z, b.max.z - b.min.z]; })"""
    x0, y0, z0, h0 = page.evaluate(where)
    assert abs(x0) < 0.5
    assert abs(y0) < 0.5
    assert abs(z0) < 0.1
    assert h0 > 70
    for k in range(
        page.locator("#orients [data-orient]").count()
    ):  # every way to lay it, then turned on the plate
        page.click(f"#orients [data-orient='{k}']")
        page.click("#rot [data-rot='2']")
        x, y, z, h = page.evaluate(where)
        assert abs(x - x0) < 0.5 and abs(y - y0) < 0.5 and abs(z) < 0.1, (k, x, y, z)
    assert page.errors == []


def test_add_a_piece_then_resize_it_on_the_plate(page, site):
    """« + Pièce » puts another library model beside this one; in « Déplacer » a touched piece gets its size slider."""
    trimesh.creation.cylinder(radius=6, height=30).export(site["lib"] / "pion.stl")
    page.reload()
    page.evaluate(
        """() => {
        const el = document.getElementById('chat-sec');
        const mo = new MutationObserver(() => {
            if (el.hidden) return;
            mo.disconnect();
            el.hidden = true;
            mo.observe(el, { attributes: true, attributeFilter: ['hidden'] }); });
        mo.observe(el, { attributes: true, attributeFilter: ['hidden'] }); }"""
    )  # the chat floats over the tools and reopens at each model pick
    page.click("#files .file[data-n='cube.stl']")
    page.wait_for_selector("#vtools [data-vt='add']:not([hidden])", timeout=30000)
    page.click("#vtools [data-vt='add']")
    page.click("#addp-list [data-addp='pion.stl']")
    page.wait_for_selector("#files .file.sel[data-n='cube + pion.3mf']", timeout=30000)
    page.wait_for_selector("#vtools [data-vt='move']:not([hidden])", timeout=30000)
    page.wait_for_timeout(800)
    page.click("#vtools [data-vt='move']")
    page.wait_for_timeout(800)
    # touch the cylinder: aim at its centre on screen
    xy = page.evaluate(
        """() => Promise.all([import('/lab/js/lab.js'), import('three')]).then(([m, T]) => {
        const g = m.current; g.updateMatrixWorld(true); let mesh; g.traverse(o => { if (o.isMesh && !mesh) mesh = o; });
        const r = m.mview ? null : null, box = new T.Box3(), v = new T.Vector3(), pos = mesh.geometry.attributes.position;
        return fetch('/lab/api/models/' + encodeURIComponent('cube + pion.3mf') + '/pieces').then(x => x.json()).then(rs => {
          const p = rs[1]; for (let i = p.first * 3; i < (p.first + p.count) * 3; i++) box.expandByPoint(v.fromBufferAttribute(pos, i).applyMatrix4(mesh.matrixWorld));
          const c = box.getCenter(new T.Vector3()); c.z = box.max.z; c.project(m.cam);
          const rect = document.querySelector('#stage canvas').getBoundingClientRect();
          return [rect.left + (c.x + 1) / 2 * rect.width, rect.top + (1 - c.y) / 2 * rect.height]; }); })"""
    )
    page.mouse.click(*xy)
    page.wait_for_selector("#pc-panel:not([hidden])")
    assert page.inner_text("#pc-name") == "pion"
    page.click("#pc-panel [data-pc='150']")
    assert page.input_value("#pc-pct") == "150"
    body = page.evaluate("() => import('/lab/js/lab.js').then(m => m.prepBody())")
    assert body["scales"] == {"1": 1.5}
    page.click("#vtools [data-vt='regroup']")
    assert page.input_value("#pc-pct") == "100"
    assert page.errors == []


def test_pick_how_the_part_lies(page):
    page.click("#files .file[data-n='cube.stl']")
    page.wait_for_selector("#orients [data-orient]", timeout=30000)
    assert page.locator("#orients .orient").count() == 6
    assert page.locator("#orients .best").count() == 1
    page.click("#orients [data-orient='4']")
    assert page.inner_text("#rot-v") == "sur le côté droit"
    page.click("#rot [data-rot='2']")
    assert "tournée de 90°" in page.inner_text("#rot-v")
    page.click("#rot [data-rot='reset']")
    assert page.inner_text("#rot-v") == "telle quelle"
    assert page.errors == []


@pytest.mark.parametrize("size", [(1280, 800), (1024, 768)])
def test_slicing_view_on_a_tablet(browser, site, size):
    if not (site["lib"] / "essai.gcode").exists():
        pytest.skip("pas de G-code d'exemple")
    ctx = browser.new_context(viewport={"width": size[0], "height": size[1]}, has_touch=True)
    pg = ctx.new_page()
    pg.goto(site["base"] + "/lab/")
    pg.wait_for_selector("#files .file")
    pg.click("#t-lab")
    pg.click("#files .file[data-n='essai.gcode']")
    pg.wait_for_selector("#layerbar:not([hidden])", timeout=30000)
    pg.wait_for_function("+document.getElementById('layer').max > 1", timeout=30000)  # paths loaded
    bar = pg.evaluate(
        """() => { const r = e => document.querySelector(e).getBoundingClientRect();
        return { range: r('#layer').width, stage: r('#stage').width, lv: r('#lv').right, steps: r('.lsteps').left,
                 sameRow: Math.abs(r('#lv').top - r('.lsteps').top) < 8, right: r('#layerbar').right, stageRight: r('#stage').right }; }"""
    )
    assert bar["range"] > 0.7 * (bar["stage"] - 60), bar  # the slider has its own full row
    assert (
        not bar["sameRow"] or bar["lv"] <= bar["steps"]
    ), bar  # the text never runs under the buttons
    assert bar["right"] <= bar["stageRight"] + 1, bar  # the bar stays inside the 3D view
    assert pg.evaluate("document.documentElement.scrollWidth") <= size[0]
    pg.fill("#layer", "10")
    pg.dispatch_event("#layer", "input")
    assert pg.inner_text("#lv").startswith("Couche 10")
    ctx.close()


def test_library_views_rename_and_bulk_delete(page, site):
    lib = site["lib"]
    for n in ("a_supprimer.stl", "b_supprimer.stl"):
        trimesh.creation.box((5, 5, 5)).export(lib / n)
    page.reload()
    page.wait_for_selector("#files .file[data-n='a_supprimer.stl']")
    page.click("#lib-view [data-view='modeles']")
    assert page.locator("#files .file[data-n$='.gcode']").count() == 0
    page.click("#lib-view [data-view='tout']")
    page.click("#files .file[data-n='a_supprimer.stl']")
    page.once("dialog", lambda d: d.accept("a_renomme"))
    page.click("#prep [data-ren]")
    page.wait_for_selector("#files .file[data-n='a_renomme.stl']")
    page.click("#lib-more")
    page.click("#lib-menu [data-act='select']")
    page.click("#files .file[data-n='a_renomme.stl']")
    page.click("#files .file[data-n='b_supprimer.stl']")
    assert page.inner_text("#bulk-n") == "2 sélectionnés"
    page.once("dialog", lambda d: d.accept())
    page.click("#bulk-del")
    page.wait_for_selector("#toasts :text('2 fichiers supprimés')")
    assert not (lib / "a_renomme.stl").exists()
    assert not (lib / "b_supprimer.stl").exists()
    assert page.errors == []


def test_viewer_tools(page, site):
    page.click("#files .file[data-n='cube.stl']")
    page.wait_for_selector("#vtools:not([hidden])", timeout=30000)
    page.click("#vtools [data-cam='face']")
    assert "on" in page.get_attribute("#vtools [data-cam='face']", "class")
    page.click("#vtools [data-vt='dims']")
    assert page.inner_text("#vdims") == "largeur 20 × profondeur 20 × hauteur 20 mm"
    page.click("#vtools [data-vt='over']")
    assert "on" in page.get_attribute("#vtools [data-vt='over']", "class")
    if (site["lib"] / "essai.gcode").exists():
        page.click("#files .file[data-n='essai.gcode']")
        page.wait_for_selector("#layerbar:not([hidden])", timeout=30000)
        page.wait_for_function("+document.getElementById('layer').max > 1", timeout=30000)
        assert page.is_hidden("#vtools [data-vt='over']")  # model-only tools leave the slicing view
        page.fill("#layer", "1")
        page.dispatch_event("#layer", "input")
        page.click("#lplay")
        page.wait_for_function("+document.getElementById('layer').value > 5")
        page.click("#lplay")  # pause
        page.check("#show-single")
        assert "on" in page.get_attribute("#vtools [data-cam='top']", "class")
    assert page.errors == []


def test_measure_between_two_picked_points(page, site):
    page.click("#files .file[data-n='cube.stl']")
    page.wait_for_selector("#vtools [data-vt='mesure']:not([hidden])", timeout=30000)
    page.click("#vtools [data-vt='mesure']")
    box = page.locator("#stage canvas").bounding_box()
    cx, cy = box["x"] + box["width"] / 2, box["y"] + box["height"] / 2
    page.mouse.move(cx - 35, cy)
    page.mouse.down()
    page.mouse.up()  # first point on the piece
    page.wait_for_selector("#vmeas:not([hidden])")
    assert "2e point" in page.inner_text("#vmeas")
    page.mouse.move(cx + 35, cy)
    page.mouse.down()
    page.mouse.up()  # second point: the distance shows up
    page.wait_for_function(
        "document.getElementById('vmeas').textContent.includes('mm')", timeout=10000
    )
    mm = float(page.inner_text("#vmeas").replace(" mm", "").replace(",", "."))
    assert 0.1 < mm < 35  # something sane across a 20 mm cube
    page.mouse.move(cx, cy + 20)
    page.mouse.down()
    page.mouse.up()  # another click starts a new measure
    page.wait_for_function("document.getElementById('vmeas').textContent.includes('2e')")
    page.click("#vtools [data-vt='mesure']")  # leaving the mode clears everything
    assert page.is_hidden("#vmeas")
    assert page.errors == []


def test_open_mesh_is_repaired_with_one_click(page, site):
    page.click("#files .file[data-n='ouvert.stl']")
    page.wait_for_selector("#chips [data-repair]", timeout=20000)  # the chip offers the repair too
    page.wait_for_selector("#advice .w:has-text('Maillage ouvert') [data-fix]", timeout=20000)
    page.click("#advice [data-also]")  # see where it is open
    page.wait_for_selector("#advice [data-also]:has-text('Masquer les défauts')", timeout=20000)
    page.wait_for_selector("#toasts :text('1 trou')")
    page.click("#advice .w:has-text('Maillage ouvert') [data-fix]")
    page.wait_for_selector("#toasts :text('Copie réparée créée')", timeout=60000)
    page.wait_for_selector("#files .file[data-n='ouvert_repare.stl']")
    page.wait_for_selector(
        "#advice .w:has-text('Maillage ouvert')", state="detached", timeout=20000
    )  # re-checked on the copy
    page.wait_for_selector("#advice .ah:has-text('Conseiller :')", timeout=20000)
    page.wait_for_selector("#advice .w.note:has-text('1 trou rebouché')")
    assert not page.query_selector("#chips [data-repair]")
    page.click("#advice [data-orig]")  # back to the original in one click
    page.wait_for_selector("#chips [data-repair]", timeout=20000)
    assert page.errors == []


def test_brush_repaints_a_coloured_model(page, site):
    page.click("#files .file[data-n='deux.glb']")
    page.wait_for_selector("#vtools [data-vt='paint']:not([hidden])", timeout=30000)
    page.click("#vtools [data-vt='paint']")
    page.wait_for_selector("#paintbar:not([hidden])")
    # the brush offers the model's colours plus every spool colour loaded in the CANVAS, deduplicated by hex
    page.wait_for_selector(
        "#pb-sw button[data-key='#E9E9E7']", timeout=15000
    )  # the CANVAS answer lands after the bar opens
    for hex in ("#E9E9E7", "#F2A900", "#D22630", "#008755"):  # the simulator's four trays
        assert page.locator(f"#pb-sw button[data-key='{hex}']").count() == 1
    page.fill("#pb-size", "20")
    box = page.locator("#stage canvas").bounding_box()
    cx, cy = box["x"] + box["width"] / 2, box["y"] + box["height"] / 2
    page.mouse.move(cx, cy)
    page.mouse.down()
    page.mouse.move(cx + 6, cy + 4)
    page.mouse.up()
    page.wait_for_function("!document.querySelector('#pb-save').disabled")
    page.click("#pb-undo")
    assert page.is_disabled("#pb-save")  # the stroke is undone
    page.mouse.move(cx, cy)
    page.mouse.down()
    page.mouse.up()
    page.click("#pb-save")
    page.wait_for_selector("#toasts :text('Retouche enregistrée')", timeout=60000)
    page.wait_for_selector("#paintbar", state="hidden")
    assert (Path(site["lib"]) / ".retouches" / "deux.glb.json").is_file()
    assert page.errors == []


def test_supports_and_seam_brush_on_any_model(page, site):
    page.click(
        "#files .file[data-n='cube.stl']"
    )  # a plain STL: one model colour, plus the CANVAS spools
    page.wait_for_selector("#vtools [data-vt='marks']:not([hidden])", timeout=30000)
    assert not page.is_hidden("#vtools [data-vt='paint']")
    page.click("#vtools [data-vt='paint']")  # the colour brush offers the CANVAS colours too
    page.wait_for_selector("#paintbar:not([hidden])")
    page.wait_for_selector("#pb-sw button[data-key='#E9E9E7']", timeout=15000)
    for hex in ("#E9E9E7", "#F2A900", "#D22630", "#008755"):
        assert page.locator(f"#pb-sw button[data-key='{hex}']").count() == 1
    assert page.locator("#pb-sw button[data-key='#C0C0C0']").count() == 1  # the STL's own grey
    page.click("#vtools [data-vt='paint']")  # close it
    page.wait_for_selector("#paintbar", state="hidden")
    page.click("#vtools [data-vt='marks']")
    page.wait_for_selector("#paintbar:not([hidden])")
    assert page.locator("#pb-sw button").count() == 4  # support, never, seam, eraser
    page.fill("#pb-size", "20")
    box = page.locator("#stage canvas").bounding_box()
    cx, cy = box["x"] + box["width"] / 2, box["y"] + box["height"] / 2
    page.mouse.move(cx, cy)
    page.mouse.down()
    page.mouse.up()
    page.click("#pb-sw button[data-key='couture']")
    page.mouse.move(cx + 40, cy + 30)
    page.mouse.down()
    page.mouse.up()
    page.click("#pb-save")
    page.wait_for_selector("#toasts :text('Faces enregistrées')", timeout=60000)
    marks = json.loads((Path(site["lib"]) / ".marques" / "cube.stl.json").read_text())
    assert marks.get("support")
    assert set(marks) <= {"support", "couture"}
    page.click("#vtools [data-vt='marks']")  # painted faces come back in their colour
    page.wait_for_selector("#paintbar:not([hidden])")
    page.on("dialog", lambda d: d.accept())
    page.click("#pb-reset")
    page.wait_for_selector("#toasts :text('Zones peintes effacées')", timeout=60000)
    assert not (Path(site["lib"]) / ".marques" / "cube.stl.json").exists()
    assert page.errors == []


def test_drill_a_hole_through_a_model(page, site):
    page.click("#files .file[data-n='cube.stl']")
    page.wait_for_selector(
        "#vtools [data-vt='marks']:not([hidden])", timeout=30000
    )  # the 3D view is up
    page.click("#add-shape")
    page.wait_for_selector("#shp[open]")
    assert page.is_hidden("#shp-col-f")
    assert page.is_hidden("#shp-d-f")
    page.fill("#shp-w", "6")
    page.select_option("#shp-kind", "cube")
    assert page.is_visible("#shp-d-f")
    page.select_option("#shp-kind", "cylindre")
    page.click("#shp-go")
    page.wait_for_selector("#toasts :text('Nouveau fichier')", timeout=60000)
    assert (Path(site["lib"]) / "cube_perce.3mf").is_file()
    page.wait_for_selector("#files .file.sel[data-n='cube_perce.3mf']", timeout=30000)
    assert page.errors == []


def test_make_preview_follows_the_sizes(page, site):
    """Créer: the 3D preview and its size follow the fields; the part lands in the library."""
    page.click("#make-open")
    page.wait_for_selector("#make-size:has-text('Sur le plateau')")
    first = page.text_content("#make-size")
    field = page.locator("#make-fields [data-mk]").first
    field.fill("150")
    page.wait_for_function("t => document.querySelector('#make-size').textContent !== t", arg=first)
    assert "150 ×" in page.text_content("#make-size")
    field.fill("999")  # out of range: said in red, creation blocked
    page.wait_for_selector("#make-size.bad")
    assert page.is_disabled("#make-go")
    page.errors.clear()  # that refusal is the server's expected 422
    page.click("[data-kind='etiquette']")
    page.wait_for_selector("#make-size:not(.bad):has-text('Sur le plateau')")
    page.click("#make-go")
    page.wait_for_selector("#files .file[data-n^='etiquette']")
    assert not page.errors


def test_make_dialog_fits_a_phone(browser, site):
    """The phone bug of 2026-11-11: the made-to-measure dialog was twice the screen's width."""
    ctx = browser.new_context(
        locale="fr-FR", viewport={"width": 412, "height": 915}, is_mobile=True, has_touch=True
    )
    pg = ctx.new_page()
    pg.goto(site["base"] + "/lab/")
    pg.wait_for_selector("#files .file", state="attached")
    pg.evaluate("document.getElementById('make-open').click()")
    pg.wait_for_selector("#make-size:has-text('Sur le plateau')")
    w = pg.evaluate(
        "[document.querySelector('#make .dlg-b').scrollWidth, document.querySelector('#make').clientWidth]"
    )
    assert w[0] <= w[1] <= 412
    ctx.close()


def test_assemble_search_and_preview(page):
    """Assembler: the search narrows the list, a spool picked shows the part in the preview and counts it."""
    page.click("#asm-open")
    page.wait_for_selector("#asm-list .asm-row")
    page.fill("#asm-q", "cube")
    page.wait_for_function("document.querySelectorAll('#asm-list .asm-row').length === 1")
    page.click("#asm-list .asm-row [data-s='1']")
    page.wait_for_selector("#asm-go:has-text('Assembler 1 pièce')")
    page.wait_for_selector("#asm-size:has-text('hauteur 20 mm')")
    assert page.input_value("#asm-name") == "cube"
    assert not page.errors


def test_review_from_the_phone_link(page, site):
    """The ntfy « Faire le bilan » link opens that print's review; saving it marks the gallery card."""
    entry = site["lib"] / ".galerie" / "20261111-000000_cube"
    entry.mkdir(parents=True, exist_ok=True)
    (entry / "meta.json").write_text(
        json.dumps(
            {
                "id": entry.name,
                "fichier": "essai.gcode",
                "debut": 1794350000,
                "fin": 1794351000,
                "duree_s": 1000,
                "issue": "terminee",
                "alertes": [],
            }
        )
    )
    page.goto(site["base"] + "/lab/#bilan=" + entry.name)
    page.wait_for_selector("#bilan[open] #bl-tips li")
    page.click("#bl-rate [data-q='details'][data-n='1']")  # a low mark ticks its defect
    page.wait_for_selector("#bl-issues [data-is='fils'].on")
    page.click("#bl-rate [data-q='global'][data-n='4']")
    page.wait_for_selector("#bl-why:has-text('Fils fins')")
    page.click("#bl-go")
    page.wait_for_selector("#gal-list :text('Bilan : fils fins')")
    bilan = json.loads((entry / "meta.json").read_text())["bilan"]
    assert bilan["issues"] == ["fils"]
    assert bilan["notes"] == {"details": 1, "global": 4}
    assert not page.errors


def test_mode_debutant_hides_advanced(page):
    # config neuve du fixture -> mode débutant : #adv masqué, puis le bouton Mode affiche tout
    page.wait_for_selector("#mode")
    page.wait_for_function("document.getElementById('mode-t').textContent !== ''")
    assert page.eval_on_selector("body", "b => b.classList.contains('mode-debutant')")
    assert page.eval_on_selector("#adv", "el => getComputedStyle(el).display") == "none"
    assert page.eval_on_selector("#ln-more", "el => getComputedStyle(el).display") == "none"
    page.click("#mode")
    page.wait_for_function("!document.body.classList.contains('mode-debutant')")
    assert page.eval_on_selector("#adv", "el => getComputedStyle(el).display") != "none"
    assert page.eval_on_selector("#mode-t", "el => el.textContent") == "Avancé"
    assert page.errors == []


def test_canvas_spools_schema(page, site):
    # stock de la bobine 1 renseigné d'abord, pour que le clic ouvre la fiche
    api(
        site,
        "/lab/api/bobines/0",
        {"restant_g": 800, "poids_g": 1000, "prix_kg": 20, "nouvelle": False},
    )
    page.click("#t-ui")
    page.wait_for_selector("#pv-trays .tray", timeout=15000)
    trays = page.query_selector_all("#pv-trays .tray")
    assert len(trays) == 4
    fills = [t.query_selector("svg.spool-c circle.fill").get_attribute("fill") for t in trays]
    assert fills == ["#E9E9E7", "#F2A900", "#D22630", "#008755"]  # couleurs actuelles du simulateur
    trays[0].click()
    page.wait_for_selector("#tray-dlg[open]")
    assert "Bobine 1" in page.inner_text("#tray-t")
    page.click("#tray-dlg [data-close]")
    assert page.errors == []


def test_alerts_filters_and_history(page):
    page.click("#ev-open")
    page.wait_for_selector("#ev[open]")
    page.wait_for_selector("#ev-filters [data-lvl]")
    btns = page.query_selector_all("#ev-filters [data-lvl]")
    assert len(btns) == 4  # Toutes / Critiques / Avertissements / Info
    page.click('[data-lvl="bad"]')
    assert page.eval_on_selector('[data-lvl="bad"]', "b => b.classList.contains('on')")
    page.click('[data-lvl="all"]')
    assert page.eval_on_selector('[data-lvl="all"]', "b => b.classList.contains('on')")
    page.click("#ev-hist")  # bascule vers l'historique persisté
    page.wait_for_timeout(600)
    assert page.eval_on_selector("#ev-hist", "b => b.classList.contains('on')")
    assert page.errors == []


def test_backup_card(page):
    page.click("#t-start")
    page.wait_for_selector("#bk-status")
    page.wait_for_function(
        "document.getElementById('bk-status').textContent.trim() !== '\u2026' && document.getElementById('bk-status').textContent.trim() !== ''"
    )
    assert "Dernière sauvegarde" in page.inner_text("#bk-status")
    assert (
        page.query_selector("#bk-now") is not None and page.query_selector("#bk-auto") is not None
    )
    # le comportement des POST /sauvegarde/* est couvert par les tests core (409 sans disque, etc.)
    assert page.errors == []


def test_workflow_guide_checklist(page):
    page.click("#files .file[data-n='cube.stl']")
    page.wait_for_selector("#chat-sec:not([hidden])")
    page.click("[data-wf]")
    page.wait_for_selector(".wf .wf-step")
    steps = page.query_selector_all(".wf .wf-step")
    assert len(steps) == 5  # fiche, pose, bobines, trancher, lancer
    steps[0].click()  # fiche : GET /models/cube.stl/info
    page.wait_for_function("document.querySelector('.wf .wf-step').classList.contains('done')")
    assert "✔" in page.inner_text(".wf .wf-step")
    assert "mm" in page.inner_text(".wf .wf-step")
    assert page.errors == []


def test_help_dialog(page):
    page.click("#help-open")
    page.wait_for_selector("#help[open]")
    assert len(page.query_selector_all("#help .tuto")) == 3  # 3 tutos
    assert len(page.query_selector_all("#help .tuto-v")) == 3  # 3 SVG animés
    assert page.query_selector("#help a[href*='/tree/main/guide']") is not None
    assert "CANVAS" in page.inner_text("#help")
    page.click("#help [data-close]")
    page.wait_for_function("!document.getElementById('help').open")
    assert page.errors == []
