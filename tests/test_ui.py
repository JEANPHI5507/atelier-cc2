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

CHROME = shutil.which("google-chrome") or shutil.which("chromium")
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
    cube = trimesh.creation.box((20, 20, 20))                # same cube, one face removed: an open mesh to repair
    trimesh.Trimesh(cube.vertices, cube.faces[:-1], process=False).export(lib / "ouvert.stl")
    two = trimesh.creation.box((20, 20, 20))                 # a two-colour cube for the brush
    two.unmerge_vertices()
    two.visual = trimesh.visual.ColorVisuals(two, face_colors=[[200, 0, 0, 255]] * 6 + [[0, 120, 0, 255]] * 6)
    two.export(lib / "deux.glb")
    sample = Path(__file__).parents[1] / "models" / "calibration_cube_20mm_0.20mm_PLA.gcode"
    if sample.exists():                                    # a ready G-code for the slicing view
        shutil.copy(sample, lib / "essai.gcode")
    env = {**os.environ, "CC2_MODELS": str(lib), "CC2_CONFIG": str(root / "config.toml"),
           "CC2_SIM_PORT": str(_free_port()), "CC2_SIM_HTTP_PORT": str(_free_port())}
    port = _free_port()
    sim = subprocess.Popen([sys.executable, str(TESTS / "fakeprinter.py"), "--seconds", "12"], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(1.0)
    dash = subprocess.Popen([sys.executable, str(TESTS / "run_dash.py"), "--control", "dash", "--port", str(port)], env=env,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
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
        b = p.chromium.launch(executable_path=CHROME, headless=True,
                              args=["--use-angle=swiftshader", "--enable-unsafe-swiftshader"])   # WebGL without a GPU
        yield b
        b.close()


@pytest.fixture
def page(browser, site):
    ctx = browser.new_context(viewport={"width": 1366, "height": 860})
    pg = ctx.new_page()
    pg.errors = []
    pg.on("pageerror", lambda e: pg.errors.append(str(e)))
    pg.on("console", lambda m: m.type == "error" and "WebGL" not in m.text and "404" not in m.text
          and pg.errors.append(m.text))
    pg.goto(site["base"] + "/lab/")
    pg.wait_for_selector("#files .file")
    yield pg
    ctx.close()


def api(site, path, body=None):
    req = urllib.request.Request(site["base"] + path, method="POST" if body is not None else "GET",
                                 data=json.dumps(body).encode() if body is not None else None,
                                 headers={"Content-Type": "application/json"})
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
    assert st["print_status"] not in (0, 8, 9) and st["filename"].startswith("cube")
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
    assert tray["restant_g"] == 333 and tray["prix_kg"] == 27
    page.click("#sv-tl")                                   # timelapse off
    page.wait_for_timeout(800)
    assert api(site, "/lab/api/surveillance")["timelapse"] is False
    page.click("#sv-tl")
    page.click("#mc-check")                                # machine default option
    page.wait_for_timeout(800)
    assert api(site, "/lab/api/lancement")["printer_check"] is False
    if page.is_visible("#mt-list .mt-more > summary"):   # tasks that are not due are folded away
        page.click("#mt-list .mt-more > summary")
    page.click("#mt-list [data-mt='plateau']")
    page.wait_for_selector("#toasts :text('Entretien noté')")
    assert page.errors == []


def test_nozzle_position_is_shown(page):
    page.click("#t-ui")
    page.wait_for_selector("#pv-pos:not([hidden])", timeout=20000)
    page.wait_for_function("document.getElementById('pv-pos-x').textContent !== '–'")
    x = float(page.text_content("#pv-pos-x").replace(",", "."))
    assert 0 <= x <= 256 and page.get_attribute("#pv-pos-dot", "cx") != "-50"       # the dot is on the plate
    assert page.errors == []


def test_phone_layout(browser, site):
    ctx = browser.new_context(viewport={"width": 375, "height": 812}, is_mobile=True, has_touch=True)
    pg = ctx.new_page()
    pg.goto(site["base"] + "/lab/")
    pg.wait_for_selector("#pv:not([hidden])")               # a phone opens on the printer
    assert not pg.is_visible("#t-start")                    # the first-day guide is for the PC
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
    for _ in range(60):                                    # the simulator prints in ~12 s
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
    if pg.evaluate("document.getElementById('idle').hidden") is False:          # nothing printing: last print shown
        pg.wait_for_selector("#last b, #last .note")
    pg.click("#b-night")
    assert pg.evaluate("document.body.classList.contains('nuit')")
    pg.click("#b-night")
    pg.click("#back")                                                     # back to the workshop…
    pg.wait_for_url("**/lab/")
    pg.wait_for_selector("#files .file")
    pg.click("#board-open")                                               # …and to the dashboard, same window
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
        assert pg.evaluate("document.documentElement.scrollWidth") <= width, f"{tab} déborde à {width} px"
    ctx.close()


def test_interface_files_are_revalidated(site):
    for path in ("/lab/", "/lab/js/app.js", "/lab/css/app.css", "/lab/tableau.html"):
        r = urllib.request.urlopen(site["base"] + path)
        assert r.headers["Cache-Control"] == "no-cache", path      # an update reaches the tablet at once


def test_pick_how_the_part_lies(page):
    page.click("#files .file[data-n='cube.stl']")
    page.wait_for_selector("#orients [data-orient]", timeout=30000)
    assert page.locator("#orients .orient").count() == 6 and page.locator("#orients .best").count() == 1
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
    pg.wait_for_function("+document.getElementById('layer').max > 1", timeout=30000)   # paths loaded
    bar = pg.evaluate("""() => { const r = e => document.querySelector(e).getBoundingClientRect();
        return { range: r('#layer').width, stage: r('#stage').width, lv: r('#lv').right, steps: r('.lsteps').left,
                 sameRow: Math.abs(r('#lv').top - r('.lsteps').top) < 8, right: r('#layerbar').right, stageRight: r('#stage').right }; }""")
    assert bar["range"] > 0.7 * (bar["stage"] - 60), bar            # the slider has its own full row
    assert not bar["sameRow"] or bar["lv"] <= bar["steps"], bar      # the text never runs under the buttons
    assert bar["right"] <= bar["stageRight"] + 1, bar                # the bar stays inside the 3D view
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
    assert not (lib / "a_renomme.stl").exists() and not (lib / "b_supprimer.stl").exists()
    assert page.errors == []


def test_viewer_tools(page, site):
    page.click("#files .file[data-n='cube.stl']")
    page.wait_for_selector("#vtools:not([hidden])", timeout=30000)
    page.click("#vtools [data-cam='face']")
    assert "on" in page.get_attribute("#vtools [data-cam='face']", "class")
    page.click("#vtools [data-vt='dims']")
    assert page.inner_text("#vdims") == "L 20 × P 20 × H 20 mm"
    page.click("#vtools [data-vt='over']")
    assert "on" in page.get_attribute("#vtools [data-vt='over']", "class")
    if (site["lib"] / "essai.gcode").exists():
        page.click("#files .file[data-n='essai.gcode']")
        page.wait_for_selector("#layerbar:not([hidden])", timeout=30000)
        page.wait_for_function("+document.getElementById('layer').max > 1", timeout=30000)
        assert page.is_hidden("#vtools [data-vt='over']")                 # model-only tools leave the slicing view
        page.fill("#layer", "1"); page.dispatch_event("#layer", "input")
        page.click("#lplay")
        page.wait_for_function("+document.getElementById('layer').value > 5")
        page.click("#lplay")                                              # pause
        page.check("#show-single")
        assert "on" in page.get_attribute("#vtools [data-cam='top']", "class")
    assert page.errors == []


def test_open_mesh_is_repaired_with_one_click(page, site):
    page.click("#files .file[data-n='ouvert.stl']")
    page.wait_for_selector("#chips [data-repair]", timeout=20000)          # the chip offers the repair too
    page.wait_for_selector("#advice .w:has-text('Maillage ouvert') [data-fix]", timeout=20000)
    page.click("#advice [data-also]")                                     # see where it is open
    page.wait_for_selector("#advice [data-also]:has-text('Masquer les défauts')", timeout=20000)
    page.wait_for_selector("#toasts :text('1 trou')")
    page.click("#advice .w:has-text('Maillage ouvert') [data-fix]")
    page.wait_for_selector("#toasts :text('Copie réparée créée')", timeout=60000)
    page.wait_for_selector("#files .file[data-n='ouvert_repare.stl']")
    page.wait_for_selector("#advice .w:has-text('Maillage ouvert')", state="detached", timeout=20000)   # re-checked on the copy
    page.wait_for_selector("#advice .ah:has-text('Conseiller :')", timeout=20000)
    page.wait_for_selector("#advice .w.note:has-text('1 trou rebouché')")
    assert not page.query_selector("#chips [data-repair]")
    page.click("#advice [data-orig]")                                     # back to the original in one click
    page.wait_for_selector("#chips [data-repair]", timeout=20000)
    assert page.errors == []


def test_brush_repaints_a_coloured_model(page, site):
    page.click("#files .file[data-n='deux.glb']")
    page.wait_for_selector("#vtools [data-vt='paint']:not([hidden])", timeout=30000)
    page.click("#vtools [data-vt='paint']")
    page.wait_for_selector("#paintbar:not([hidden])")
    assert page.locator("#pb-sw button").count() == 2
    page.fill("#pb-size", "20")
    box = page.locator("#stage canvas").bounding_box()
    cx, cy = box["x"] + box["width"] / 2, box["y"] + box["height"] / 2
    page.mouse.move(cx, cy)
    page.mouse.down()
    page.mouse.move(cx + 6, cy + 4)
    page.mouse.up()
    page.wait_for_function("!document.querySelector('#pb-save').disabled")
    page.click("#pb-undo")
    assert page.is_disabled("#pb-save")                                  # the stroke is undone
    page.mouse.move(cx, cy)
    page.mouse.down()
    page.mouse.up()
    page.click("#pb-save")
    page.wait_for_selector("#toasts :text('Retouche enregistrée')", timeout=60000)
    page.wait_for_selector("#paintbar", state="hidden")
    assert (Path(site["lib"]) / ".retouches" / "deux.glb.json").is_file()
    assert page.errors == []


def test_supports_and_seam_brush_on_any_model(page, site):
    page.click("#files .file[data-n='cube.stl']")                        # a plain STL: no colour brush, but this one
    page.wait_for_selector("#vtools [data-vt='marks']:not([hidden])", timeout=30000)
    assert page.is_hidden("#vtools [data-vt='paint']")
    page.click("#vtools [data-vt='marks']")
    page.wait_for_selector("#paintbar:not([hidden])")
    assert page.locator("#pb-sw button").count() == 4                   # support, never, seam, eraser
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
    assert marks.get("support") and set(marks) <= {"support", "couture"}
    page.click("#vtools [data-vt='marks']")                              # painted faces come back in their colour
    page.wait_for_selector("#paintbar:not([hidden])")
    page.on("dialog", lambda d: d.accept())
    page.click("#pb-reset")
    page.wait_for_selector("#toasts :text('Zones peintes effacées')", timeout=60000)
    assert not (Path(site["lib"]) / ".marques" / "cube.stl.json").exists()
    assert page.errors == []


def test_drill_a_hole_through_a_model(page, site):
    page.click("#files .file[data-n='cube.stl']")
    page.wait_for_selector("#vtools [data-vt='marks']:not([hidden])", timeout=30000)   # the 3D view is up
    page.click("#add-shape")
    page.wait_for_selector("#shp[open]")
    assert page.is_hidden("#shp-col-f") and page.is_hidden("#shp-d-f")               # a round hole: no colour, no depth
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
    field.fill("999")                                       # out of range: said in red, creation blocked
    page.wait_for_selector("#make-size.bad")
    assert page.is_disabled("#make-go")
    page.errors.clear()                                     # that refusal is the server's expected 422
    page.click("[data-kind='etiquette']")
    page.wait_for_selector("#make-size:not(.bad):has-text('Sur le plateau')")
    page.click("#make-go")
    page.wait_for_selector("#files .file[data-n^='etiquette']")
    assert not page.errors


def test_make_dialog_fits_a_phone(browser, site):
    """The phone bug of 2026-11-11: the made-to-measure dialog was twice the screen's width."""
    ctx = browser.new_context(viewport={"width": 412, "height": 915}, is_mobile=True, has_touch=True)
    pg = ctx.new_page()
    pg.goto(site["base"] + "/lab/")
    pg.wait_for_selector("#files .file", state="attached")
    pg.evaluate("document.getElementById('make-open').click()")
    pg.wait_for_selector("#make-size:has-text('Sur le plateau')")
    w = pg.evaluate("[document.querySelector('#make .dlg-b').scrollWidth, document.querySelector('#make').clientWidth]")
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
    page.wait_for_selector("#asm-size:has-text('× 20 mm')")
    assert page.input_value("#asm-name") == "cube"
    assert not page.errors


def test_review_from_the_phone_link(page, site):
    """The ntfy « Faire le bilan » link opens that print's review; saving it marks the gallery card."""
    entry = site["lib"] / ".galerie" / "20261111-000000_cube"
    entry.mkdir(parents=True, exist_ok=True)
    (entry / "meta.json").write_text(json.dumps({"id": entry.name, "fichier": "essai.gcode", "debut": 1794350000,
                                                 "fin": 1794351000, "duree_s": 1000, "issue": "terminee", "alertes": []}))
    page.goto(site["base"] + "/lab/#bilan=" + entry.name)
    page.wait_for_selector("#bilan[open] #bl-tips li")
    page.click("#bl-issues [data-is='fils']")
    page.wait_for_selector("#bl-why:has-text('Fils fins')")
    page.click("#bl-go")
    page.wait_for_selector("#gal-list :text('Bilan : fils fins')")
    assert json.loads((entry / "meta.json").read_text())["bilan"]["issues"] == ["fils"]
    assert not page.errors
