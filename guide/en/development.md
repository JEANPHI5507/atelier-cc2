# Development

[← Back to the README](../../README.md) · 🇫🇷 [Français](../developpement.md)

## Layout

```
src/elegoo_lab/
  cli.py            the cc2 command (includes pycentauri's, pre-filled)
  app.py            the web server (FastAPI): /lab/api/… routes, mounted on pycentauri's server
  web/              the interface, no build step
    index.html        workshop structure; css/app.css (themes, mobile)
    js/core.js        shared helpers; lab.js (workshop, 3D, slicing); printer.js (Printer tab)
    js/gallery.js, alerts.js, setup.js (Démarrage), app.js (tabs, start-up)
    tableau.html + js/tableau.js   the tablet (old-style JavaScript, no modules: old browsers)
    vendor/           three.js; cc2/ (build plate copied from OrcaSlicer by make plateau)
  slicer.py         OrcaSlicer on the command line, CC2 profiles, M6211 purge
  printprep.py      from model to G-code: colours, size, position, multicolour modes, cutting, copies
  colors.py         a model's colours, conversion for the CANVAS, sized purge, simplification
  colorize.py       assembling parts into a multicolour 3MF
  mesh.py, orient.py, cut.py, advisor.py, optimize.py   mesh, positions, cutting, advisor, "Optimiser"
  parametric.py, parametric_more.py, addtext.py          the "Créer" parts
  launch.py         starting a print (spool table, machine options); spools.py, stock.py (spools, costs)
  alerts.py         continuous printer monitoring and alerts; vision.py (camera AI); gallery.py
  camfeed.py        the camera frame by frame; coupe.py, suivi_couleurs.py (tablet, upcoming colours)
  aftercare.py      the review; maintenance.py (maintenance); bedcheck.py (empty plate)
  access.py, certs.py   access code, HTTPS, Tailscale
  comfy.py          ComfyUI client; simulateur.py (the simulated CC2)
  library.py, importlink.py, thumbnail.py, threemf.py, repair.py   library, link import, thumbnails, 3MF, repair
  catalog.py, settings.py, calibration.py, gcode_preview.py         profiles, advanced settings, test towers, toolpath preview
  connexion.py, errors.py   Démarrage tab (connection test); CC2 error codes
  config.py         config.toml
workflows/          ComfyUI workflows (API format) and their .map.json
tests/              test_core.py (server), test_ui.py (a real Chrome clicks through the workshop), conftest.py
docs/               the home page (GitHub Pages) and its images
guide/              these guides (French), guide/en/ (English)
```

## Running in development

```bash
uv sync                                  # with the test tools
uv run cc2 simulateur --duree 60         # the workshop on a simulated CC2: http://localhost:8788/lab/
```

The interface is static files re-checked on every load: changing a `.js` or `.css` only needs a page reload. A Python
change needs the command restarted.

To check a JavaScript module without a browser: `node --input-type=module --check < src/elegoo_lab/web/js/lab.js`
(the tablet: `node --check src/elegoo_lab/web/js/tableau.js`).

## Tests

```bash
make test                # or: uv run pytest -q
```

- `tests/test_core.py`: the server, slicing, colours, alerts, camera… against the simulated CC2. Some tests really slice
  with OrcaSlicer (needs `make slicer`).
- `tests/test_ui.py`: a real Chrome (Playwright) clicks through a test workshop, with its own library and ports; skipped
  if Chrome isn't installed (`uv run playwright install chromium`).

## The simulator

`src/elegoo_lab/simulateur.py` is a small MQTT 3.1.1 broker and a fake CC2 speaking the protocol documented by
pycentauri: state, a CANVAS with four spools, files, prints in fast motion, a drawn camera, file upload. It is not a
faithful model of the firmware: what is true on the real printer is listed in [What to know about the CC2](cc2.md).

## Conventions

- Interface texts are written in French, informal "tu", concrete (what happens and what to do), no jargon. The English
  interface comes from `web/i18n/en.json`: `web/js/i18n.js` swaps every text shown (exact texts, then patterns where `{}`
  is a value), and `i18n.py` does the same for the phone notifications. A new French text needs its English line there.
- Comments say why, not what.
- pycentauri is pinned to 0.9.1: a reverse-engineered protocol, to upgrade on purpose only.
- Any action that changes the printer goes through `--control`; any request that changes something is refused if it
  comes from another site than the workshop.
