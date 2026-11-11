"""Web app: pycentauri's printer dashboard (/ui/) + our workshop (/lab/)."""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import json
import re
from urllib.parse import urlsplit
import shutil
import threading
import time
import uuid
from pathlib import Path
from typing import Any

from pydantic import BaseModel
from fastapi import APIRouter, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from pycentauri.server import create_app as create_printer_app

from . import (launch, library, stock, calibration, colorize, colors, comfy, config, connexion, gcode_preview, mesh, parametric, printprep,
               settings, slicer, spools)

WEB = Path(__file__).parent / "web"
JOBS_FILE = config.MODELS_DIR / ".jobs.json"
ALLOWED = {".stl", ".3mf", ".glb", ".gltf", ".obj", ".gcode", ".ply"}



def _pal(values: list[str | None] | None) -> tuple[str | None, ...] | None:
    """Spool colours to repaint a model with (slot 1 first); anything that is not #RRGGBB is an empty slot."""
    if not values:
        return None
    pal = tuple(v.upper() if isinstance(v, str) and spools.HEX.fullmatch(v) else None for v in values[:4])
    return pal if any(pal) else None

def _new_model_path(name: str) -> Path:
    """Where a new model goes: never overwrite one silently ("dragon (2).stl")."""
    config.MODELS_DIR.mkdir(exist_ok=True)
    dest, k = config.MODELS_DIR / name, 1
    while dest.exists():
        k += 1
        dest = config.MODELS_DIR / f"{Path(name).stem} ({k}){Path(name).suffix}"
    return dest


def _model_path(name: str) -> Path:
    p = (config.MODELS_DIR / Path(name).name)
    if not p.is_file():
        raise HTTPException(404, f"modèle introuvable: {name}")
    return p


class RetouchIn(BaseModel):
    paint: dict[str, list[int]] = {}
    erase: list[int] = []
    clear: bool = False


class TextIn(BaseModel):
    texte: str
    police: str = "manuscrite"
    angle: float = 0.0
    taille: float | None = None        # capital height in mm, automatic when None


class PartIn(BaseModel):
    name: str
    slot: int


class MulticolorIn(BaseModel):
    name: str = "multicolore"
    parts: list[PartIn]
    filaments: list[str]
    colours: list[str] | None = None   # the loaded spools' colours, slot 1 first
    quality: str = slicer.DEFAULT_QUALITY
    infill: int | None = None


class PrepareIn(BaseModel):
    mapping: dict[int, int] = {}       # source colour index -> CANVAS slot (1..4)
    filaments: list[str] = ["PLA"]     # filament per slot
    quality: str = slicer.DEFAULT_QUALITY
    infill: int | None = None
    supports: bool | str = False
    plate_only: bool = False
    height_mm: float | None = None
    mode: str = printprep.DEFAULT_MODE
    split: bool = True
    slot_colours: dict[int, str] | None = None  # colours of the spools really loaded
    palette: list[str | None] | None = None     # repaint the model with these spool colours (slot 1 first)
    plate: str = settings.DEFAULT_PLATE
    advanced: dict[str, Any] = {}
    rotate: list[float] = [0, 0, 0]
    copies: int = 1
    orient: bool = False
    usage: str = "profil"
    pauses_mm: list[float] = []         # stop at these model heights (magnet, nut, colour swap)
    simplify_colours: bool | str = "leger"   # non / leger (3 %) / fort (10 %): specks of a layer take its main colour


class PrinterIn(BaseModel):
    host: str
    access_code: str
    serial: str | None = None


class FreshStatic(StaticFiles):
    """The workshop's pages, styles and scripts: browsers must check for a newer version every time
    (a cheap 304 when nothing changed). Without it a phone or tablet keeps showing the old interface
    after an update, since nothing tells it the files changed."""

    def file_response(self, *args: Any, **kwargs: Any) -> Response:
        resp = super().file_response(*args, **kwargs)
        resp.headers["Cache-Control"] = "no-cache"
        return resp


class LaunchIn(BaseModel):
    filename: str
    bedlevel_force: bool | None = None
    printer_check: bool | None = None
    print_layout: str | None = None
    delay_video: bool | None = None
    slot_map: list[dict[str, int]] | None = None
    remember: bool = False


class RenameIn(BaseModel):
    name: str


class NamesIn(BaseModel):
    names: list[str]


class LaunchOptionsIn(BaseModel):
    bedlevel_force: bool | None = None
    printer_check: bool | None = None
    print_layout: str | None = None
    delay_video: bool | None = None


class TrayIn(BaseModel):
    restant_g: float | None = None
    poids_g: float | None = None
    prix_kg: float | None = None
    nouvelle: bool = False


class ReviewIn(BaseModel):
    issues: list[str] = []
    note: str = ""


class QueueIn(BaseModel):
    name: str


class QueueMoveIn(BaseModel):
    index: int
    to: int


class LinkIn(BaseModel):
    url: str


class PhoneAlertIn(BaseModel):
    action: str   # "on" (new private topic), "off", "test"


class SurvIn(BaseModel):
    ia: bool | None = None
    pause_auto: bool | None = None
    sensibilite: float | None = None
    timelapse: bool | None = None


class TestIn(BaseModel):
    filaments: list[str] = []


def lab_router(cfg: config.Config) -> APIRouter:
    r = APIRouter(prefix="/lab/api", tags=["lab"])
    jobs: dict[str, dict[str, Any]] = {}

    @r.get("/models")
    async def models() -> list[dict[str, Any]]:
        """The library: models, G-codes with their facts (source, time, grams, colours), technical files."""
        return await asyncio.to_thread(library.listing)

    @r.get("/models/{name}/thumb.png")
    async def model_thumb(name: str) -> Response:
        _model_path(name)
        try:
            png = await asyncio.to_thread(library.thumbnail, name)
        except Exception:      # a mesh that cannot be read still lists, just without a picture
            png = None
        if not png:
            raise HTTPException(404, "pas de vignette")
        return Response(png, media_type="image/png", headers={"Cache-Control": "max-age=86400"})

    @r.post("/models/{name}/rename")
    def model_rename(name: str, body: RenameIn) -> dict[str, str]:
        _model_path(name)
        try:
            return {"name": library.rename(name, body.name)}
        except ValueError as err:
            raise HTTPException(422, str(err)) from err

    @r.post("/library/delete")
    def library_delete(body: NamesIn) -> dict[str, Any]:
        return {"deleted": library.delete(body.names)}

    @r.get("/library/cleanup")
    def library_cleanup() -> list[dict[str, Any]]:
        return library.cleanup()

    @r.get("/models/{name}")
    def model_file(name: str) -> FileResponse:
        return FileResponse(_model_path(name))

    @r.post("/models")
    async def upload_model(file: UploadFile = File(...)) -> dict[str, str]:
        name = Path(file.filename or "model.stl").name
        if Path(name).suffix.lower() not in ALLOWED:
            raise HTTPException(400, f"format non supporté (accepté: {sorted(ALLOWED)})")
        dest = _new_model_path(name)
        with dest.open("wb") as out:
            shutil.copyfileobj(file.file, out)
        return {"name": dest.name}

    # --- print queue: G-codes to print one after the other; the next one starts by hand (the bed must be cleared)
    def _queue() -> list[str]:
        try:
            q = json.loads((config.MODELS_DIR / ".queue.json").read_text())
        except (OSError, ValueError):
            return []
        return [n for n in q if isinstance(n, str) and (config.MODELS_DIR / n).exists()]   # deleted files drop out

    def _queue_save(q: list[str]) -> list[str]:
        f = config.MODELS_DIR / ".queue.json"
        f.parent.mkdir(exist_ok=True)
        f.write_text(json.dumps(q, ensure_ascii=False))
        return q

    @r.get("/queue")
    def queue_get() -> list[str]:
        return _queue()

    @r.post("/queue")
    def queue_add(body: QueueIn) -> list[str]:
        p = _model_path(body.name)
        if p.suffix.lower() != ".gcode":
            raise HTTPException(422, "seul un fichier tranché (G-code) peut aller dans la file")
        return _queue_save(_queue() + [p.name])

    @r.post("/queue/move")
    def queue_move(body: QueueMoveIn) -> list[str]:
        q = _queue()
        if not (0 <= body.index < len(q) and 0 <= body.to < len(q)):
            raise HTTPException(422, "position hors de la file")
        q.insert(body.to, q.pop(body.index))
        return _queue_save(q)

    @r.delete("/queue/{index}")
    def queue_remove(index: int) -> list[str]:
        q = _queue()
        if not 0 <= index < len(q):
            raise HTTPException(404, "position hors de la file")
        q.pop(index)
        return _queue_save(q)

    @r.post("/models/from-url")
    async def import_from_url(body: LinkIn) -> dict[str, list[str]]:
        from . import importlink
        try:
            got = await importlink.fetch(body.url)
        except importlink.LinkError as e:
            raise HTTPException(422, str(e)) from None
        except Exception as e:  # network trouble: say it plainly
            raise HTTPException(502, f"Téléchargement impossible : {type(e).__name__}") from None
        names = []
        for name, data in got:
            dest = _new_model_path(name)
            dest.write_bytes(data)
            names.append(dest.name)
        return {"names": names}

    @r.delete("/models/{name}")
    def delete_model(name: str) -> dict[str, bool]:
        library.delete([_model_path(name).name])
        return {"ok": True}

    @r.get("/models/{name}/info")
    def model_info(name: str) -> dict[str, Any]:
        p = _model_path(name)
        if p.suffix.lower() == ".gcode":
            return {"file": p.name, "note": "G-code déjà tranché"}
        try:
            return {**mesh.info(p), "usage": printprep.suggest_usage(p), "retour": library.load_index().get(p.name, {}).get("retour")}
        except Exception as err:
            raise HTTPException(422, str(err)) from err

    @r.get("/slicer")
    def slicer_profiles() -> dict[str, Any]:
        try:
            return {"available": True, "nozzles": slicer.nozzles(), "qualities": slicer.qualities(),
                    "filaments": slicer.filaments(), "default_quality": slicer.DEFAULT_QUALITY,
                    "advanced": settings.spec(),
                    "usages": [{"value": k, "label": u["label"], "hint": u["hint"], "quality": u["quality"]}
                               for k, u in printprep.USAGES.items()]}
        except slicer.SliceError as err:
            return {"available": False, "error": str(err)}

    @r.get("/models/{name}/colors")
    def model_colors(name: str) -> dict[str, Any]:
        try:
            return colors.analyze(_model_path(name))
        except Exception as err:
            raise HTTPException(422, f"analyse des couleurs impossible: {err}") from err

    @r.post("/models/{name}/retouch")
    async def retouch(name: str, body: RetouchIn) -> dict[str, int]:
        """Repaint faces with one of the model's colours, kept beside it (the model file is never changed)."""
        path = _model_path(name)
        if path.suffix.lower() not in colors.MESH_COLOUR_EXT:
            raise HTTPException(400, "retouche possible pour les modèles GLB, OBJ et PLY colorés")
        try:
            return {"retouched": await asyncio.to_thread(colors.save_retouch, path, body.paint, body.erase, body.clear)}
        except (ValueError, OSError) as err:
            raise HTTPException(422, str(err)) from err

    preview_cache: dict[tuple, bytes] = {}

    @r.get("/models/{name}/preview.glb")
    async def model_preview(name: str, request: Request, map: str | None = None, pal: str | None = None) -> Response:
        """Any library model as a GLB coloured by CANVAS slot (``map`` = "colour:slot,...",
        ``pal`` = spool colours "#RRGGBB,,#RRGGBB" to repaint it with)."""
        src = _model_path(name)
        mapping = {int(a): int(b) for a, b in (x.split(":") for x in map.split(",") if x)} if map else None
        palette = _pal(pal.split(",") if pal else None)
        key = (src.name, src.stat().st_mtime, map or "", palette)
        # an AI model's preview weighs several MB: the browser keeps it and only asks whether it changed
        etag = '"' + hashlib.sha1(repr(key).encode()).hexdigest()[:20] + '"'
        cache = {"ETag": etag, "Cache-Control": "private, no-cache"}
        if request.headers.get("if-none-match") == etag:
            return Response(status_code=304, headers=cache)
        if key not in preview_cache:
            try:
                m = await asyncio.to_thread(colors.preview_glb, src, mapping, palette)
            except Exception as err:
                raise HTTPException(422, f"aperçu impossible: {err}") from err
            preview_cache.clear() if len(preview_cache) > 32 else None
            preview_cache[key] = m.export(file_type="glb", include_normals=True)
        return Response(preview_cache[key], media_type="model/gltf-binary", headers=cache)

    # --- first-day setup ------------------------------------------------------------
    @r.get("/setup")
    def setup_state() -> dict[str, Any]:
        cur = config.load().printer
        return {
            "printer": {"host": cur.host, "code_set": bool(cur.access_code), "serial": cur.serial},
            "pc_ip": connexion.resolve_hint(),
            "dowel_play": config.dowel_play(), "plays": calibration.DOWEL_PLAYS,
            "tests": [{"key": t.key, "title": t.title, "purpose": t.purpose, "look_for": t.look_for,
                       "colours": t.colours, "file": t.file} for t in calibration.TESTS],
        }

    @r.post("/setup/check")
    async def setup_check(body: PrinterIn) -> dict[str, Any]:
        return await connexion.check(body.host, body.access_code)

    @r.post("/setup/printer")
    def setup_save_printer(body: PrinterIn) -> dict[str, bool]:
        values = {"host": body.host.strip(), "access_code": body.access_code.strip()}
        if body.serial:
            values["serial"] = body.serial
        config.save("printer", **values)
        return {"ok": True}

    @r.post("/setup/dowel")
    def setup_dowel(play: float = Form(...)) -> dict[str, float]:
        if not 0.0 <= play <= 0.6:
            raise HTTPException(400, "jeu entre 0 et 0,6 mm")
        config.save("assemblage", jeu_mm=round(play, 3))
        return {"dowel_play": config.dowel_play()}

    @r.post("/setup/tests/{key}")
    async def setup_test(key: str, body: TestIn) -> dict[str, Any]:
        test = calibration.BY_KEY.get(key)
        if test is None:
            raise HTTPException(404, f"test inconnu: {key}")

        def work() -> dict[str, Any]:
            src = calibration.ensure(test)
            res = printprep.prepare_and_slice(src, filaments=body.filaments or ["PLA"] * test.colours, **test.slice_opts)
            if test.bands:
                res["bands"] = calibration.tune(config.MODELS_DIR / Path(res["gcode"][0]).name, test)
            return res

        try:
            return await asyncio.to_thread(work)
        except (ValueError, slicer.SliceError) as err:
            raise HTTPException(422, str(err)) from err

    @r.get("/parametric")
    def parametric_catalogue() -> list[dict[str, Any]]:
        return parametric.catalogue()

    @r.post("/models/{name}/texte")
    async def add_text(name: str, body: TextIn) -> dict[str, Any]:
        """A name added to a flat model (second colour, tied to its strokes), as a new 3MF."""
        from . import addtext
        src = _model_path(name)
        try:
            return await asyncio.to_thread(addtext.add, src, body.texte, font=body.police, angle=body.angle,
                                           size_mm=body.taille)
        except (ValueError, OSError) as err:
            raise HTTPException(422, str(err)) from err

    @r.post("/parametric/{key}/preview")
    async def parametric_preview(key: str, values: dict[str, Any]) -> Response:
        """Live preview while the sizes are being set: a coloured GLB, nothing saved."""
        try:
            glb, size = await asyncio.to_thread(parametric.preview, key, values)
        except ValueError as err:
            raise HTTPException(422, str(err)) from err
        return Response(glb, media_type="model/gltf-binary", headers={"X-Size": ",".join(map(str, size))})

    @r.post("/parametric/{key}")
    async def parametric_create(key: str, values: dict[str, Any]) -> dict[str, str]:
        try:
            out = await asyncio.to_thread(parametric.create, key, values)
        except ValueError as err:
            raise HTTPException(422, str(err)) from err
        return {"name": out.name}

    @r.get("/models/{name}/match-spools")
    async def match_spools(name: str, request: Request) -> dict[str, Any]:
        """Pair the model's colours with the spools loaded in the CANVAS right now."""
        src = _model_path(name)
        try:
            canvas = await request.app.state.manager.printer.canvas_status()
        except Exception as err:
            raise HTTPException(503, f"CANVAS illisible (imprimante injoignable ?) : {str(err)[:120]}") from err
        trays = spools.loaded(canvas.raw)
        try:
            a = await asyncio.to_thread(colors.analyze, src)
            if len(a["colours"]) == 1:   # one colour: any loaded spool can print it, no need to slice another tool
                active = canvas.raw.get("canvas_info", canvas.raw).get("active_tray_id")
                res = spools.single(a["colours"][0], trays, coloured=a["source"] != "sans couleur", active=active)
            else:
                res = spools.match(a["colours"], trays)
                # repaint the model with the spools themselves: every face takes the closest spool colour
                palette = tuple(next((t["color"] for t in trays if t["pos"] == k), None) for k in range(4))
                p = await asyncio.to_thread(colors.analyze, src, palette)
                if p["palette"]:
                    far = spools.far_colours(a["colours"], trays)
                    res = spools.match(p["colours"], trays)   # spool colours: each one lands on its own spool
                    res.update(colours=p["colours"], palette=list(palette), warnings=far + res["warnings"])
        except ValueError as err:
            raise HTTPException(422, str(err)) from err
        res["trays"] = [{"slot": t["pos"] + 1, "hex": t["color"], "name": t.get("filament_name") or t.get("type"),
                         "type": t.get("type"), "filament": spools.filament_for(t)} for t in trays]
        return res

    @r.get("/models/{name}/paths")
    async def gcode_paths(name: str) -> dict[str, Any]:
        """Printed paths of a G-code (layer by layer, supports flagged) for the slicing preview."""
        src = _model_path(name)
        if src.suffix.lower() != ".gcode":
            raise HTTPException(400, "seulement pour un G-code")
        return await asyncio.to_thread(gcode_preview.extract, src)

    @r.get("/couleurs")
    async def colour_plan(request: Request) -> dict[str, Any]:
        """The print in progress: the spool engaged now and the next colour changes, with their spools."""
        from . import suivi_couleurs
        mgr = request.app.state.manager
        st = await asyncio.wait_for(mgr.printer.status(), 10)
        name = Path(st.filename or "").name
        src = config.MODELS_DIR / name
        if not name or not src.exists():
            raise HTTPException(404, "impression lancée hors de l'atelier : pas de G-code à lire")
        route = {int(k): int(v) for k, v in (stock.load()["prints"].get(name, {}).get("route") or {}).items()}
        trays, active = {}, None
        with contextlib.suppress(Exception):   # CANVAS unread: the G-code alone says where the print is
            raw = (await asyncio.wait_for(mgr.printer.canvas_status(), 10)).raw
            trays = {t["pos"]: t for t in spools.loaded(raw)}
            tray = raw.get("canvas_info", raw).get("active_tray_id")
            active = next((tool for tool, pos in route.items() if pos == tray), tray if not route else None)
        layer = st.print_info.current_layer if st.print_info else 1
        res = await asyncio.to_thread(suivi_couleurs.plan, src, layer or 1, active)

        def spool(tool: int) -> dict[str, Any]:
            pos = route.get(tool, tool)
            t = trays.get(pos) or {}
            hexa = t.get("color") or (res["colours"][tool] if tool < len(res["colours"]) else "#d7dbe2")
            return {"tool": tool, "bobine": pos + 1, "hex": hexa, "nom": t.get("name") or t.get("filament_name") or f"bobine {pos + 1}"}
        return {"couche": layer, "maintenant": spool(res["tool"]), "restants": res["left"], "total": res["total"],
                "suivants": [{**spool(n["tool"]), "couche": n["layer"], "min": n["min"]} for n in res["next"]]}

    @r.get("/models/{name}/coupe")
    async def gcode_section(name: str, couche: int = 1, face: bool = True) -> dict[str, Any]:
        """For the tablet: the print seen from the front and the layer ``couche`` seen from above, in 2D."""
        from . import coupe
        src = _model_path(name)
        if src.suffix.lower() != ".gcode":
            raise HTTPException(400, "seulement pour un G-code")
        return await asyncio.to_thread(coupe.coupe, src, couche, face)

    cut_cache: dict[tuple, tuple[dict[str, Any], bytes]] = {}

    def _cut(name: str, height: float | None, map: str | None, pal: str | None = None) -> tuple[dict[str, Any], bytes]:
        src = _model_path(name)
        palette = _pal(pal.split(",") if pal else None)
        key = (src.name, src.stat().st_mtime, height, map or "", config.dowel_play(), palette)
        if key not in cut_cache:
            mapping = {int(a): int(b) for a, b in (x.split(":") for x in map.split(",") if x)} if map else None
            summary, view = printprep.cut_preview(src, mapping=mapping, height_mm=height, palette=palette)
            cut_cache.clear() if len(cut_cache) > 8 else None
            cut_cache[key] = (summary, view.export(file_type="glb"))
        return cut_cache[key]

    @r.get("/models/{name}/cut-plan")
    async def cut_plan(name: str, height: float | None = None, map: str | None = None, pal: str | None = None) -> dict[str, Any]:
        try:
            return (await asyncio.to_thread(_cut, name, height, map, pal))[0]
        except ValueError as err:
            raise HTTPException(422, str(err)) from err

    orient_cache: dict[tuple, list[dict[str, Any]]] = {}

    @r.get("/models/{name}/orientations")
    async def orientations(name: str, height: float | None = None, rz: int = 0) -> list[dict[str, Any]]:
        """Six ways to lay the part on the plate, each with a thumbnail; the best one marked."""
        from . import orient
        path = _model_path(name)
        if path.suffix.lower() == ".gcode":
            raise HTTPException(400, "déjà tranché")
        st = path.stat()
        key = (name, st.st_mtime_ns, st.st_size, height, rz % 360)   # ~2 s on an AI model: computed once
        if key not in orient_cache:
            try:
                orient_cache[key] = await asyncio.to_thread(orient.orientations, path, height, rz % 360)
            except (ValueError, OSError) as err:
                raise HTTPException(422, f"positions impossibles à calculer : {err}") from err
            while len(orient_cache) > 32:
                orient_cache.pop(next(iter(orient_cache)))
        return orient_cache[key]

    advice_cache: dict[tuple, dict[str, Any]] = {}

    @r.get("/models/{name}/advice")
    async def advice(name: str, height: float | None = None, rx: float = 0, ry: float = 0, rz: float = 0,
                     supports: bool = False, brim: bool = False, split: bool = False) -> dict[str, Any]:
        """Print advisor: what could go wrong at this size/orientation, with one-click fixes."""
        from . import advisor
        path = _model_path(name)
        st = path.stat()
        key = (name, st.st_mtime_ns, st.st_size, height, rx, ry, rz, supports, brim, split)
        if key not in advice_cache:
            try:
                advice_cache[key] = await asyncio.to_thread(advisor.analyze, path, height_mm=height, rotate=(rx, ry, rz),
                                                            supports=supports, brim=brim, split=split)
            except (ValueError, OSError) as err:
                raise HTTPException(422, f"analyse impossible : {err}") from err
            while len(advice_cache) > 64:
                advice_cache.pop(next(iter(advice_cache)))
        return advice_cache[key]

    @r.get("/bilan/{entry}")
    def print_review_get(entry: str) -> dict[str, Any]:
        """After a print: what to do with the part now, and the defects one can report."""
        from . import aftercare, gallery
        meta = next((m for m in gallery.entries() if m["id"] == entry), None)
        if meta is None:
            raise HTTPException(404, "impression inconnue")
        return {"tips": aftercare.tips(meta), "issues": aftercare.catalogue(), "bilan": meta.get("bilan")}

    @r.post("/bilan/{entry}")
    def print_review_set(entry: str, body: ReviewIn) -> dict[str, Any]:
        """The user's review: kept on the print, its corrections kept on the source model for next time."""
        from . import aftercare, gallery
        meta = next((m for m in gallery.entries() if m["id"] == entry), None)
        if meta is None:
            raise HTTPException(404, "impression inconnue")
        res = aftercare.review(meta, body.issues, body.note)
        gallery.update(entry, bilan={"date": int(time.time()), "issues": res["issues"], "note": body.note[:300],
                                     "titres": [aftercare.ISSUES[k][0] for k in res["issues"]]})
        return res

    # --- the camera, one whole picture at a time (see camfeed) --------------------------------------
    @r.get("/camera")
    async def camera_frame(request: Request, after: int = -1) -> Response:
        """The next picture: newer than ``after`` (the X-Seq of the one the page shows), by default
        newer than the one already there when asked."""
        from . import camfeed
        st = request.app.state
        if getattr(st, "camfeed", None) is None:
            st.camfeed = camfeed.CameraFeed(st.manager.camera)
        got = await st.camfeed.next(st.camfeed.seq if after < 0 else after)
        if not got:
            raise HTTPException(503, "caméra indisponible")
        return Response(got[1], media_type="image/jpeg", headers={"Cache-Control": "no-store", "X-Seq": str(got[0])})

    # --- is the plate empty? the camera compared with a photo of the empty plate ---------------------
    async def _plate_photo(request: Request) -> bytes:
        """A camera photo with the chamber light on (switched on for it, then back as it was)."""
        from . import bedcheck, vision
        mgr = request.app.state.manager
        jpeg = await vision.grab(mgr)
        if not bedcheck.dark(jpeg) or not getattr(mgr, "enable_control", False):
            return jpeg
        await asyncio.wait_for(mgr.printer.set_light(True), 10)
        try:
            await asyncio.sleep(2.5)            # the camera adjusts to the light
            return await vision.grab(mgr)
        finally:
            with contextlib.suppress(Exception):
                await asyncio.wait_for(mgr.printer.set_light(False), 10)

    @r.get("/plateau")
    async def plate_check(request: Request) -> dict[str, Any]:
        """Before a print: "vide", "occupe" or "inconnu", with the photo it is based on."""
        import base64
        from . import bedcheck
        try:
            jpeg = await _plate_photo(request)
        except Exception as err:   # printer or camera away: the check is only advice
            return {"etat": "inconnu", "raison": f"caméra indisponible ({type(err).__name__})"}
        return {**bedcheck.check(jpeg), "photo": "data:image/jpeg;base64," + base64.b64encode(jpeg).decode()}

    @r.post("/plateau/vide")
    async def plate_empty(request: Request) -> dict[str, Any]:
        """The user says the plate is empty: this photo becomes the reference."""
        from . import bedcheck
        try:
            return bedcheck.save_reference(await _plate_photo(request))
        except ValueError as err:
            raise HTTPException(422, str(err)) from err
        except Exception as err:
            raise HTTPException(503, f"caméra indisponible ({type(err).__name__})") from err

    @r.post("/models/{name}/optimize")
    async def optimize_model(name: str, height: float | None = None, rz: int = 0) -> dict[str, Any]:
        """« Optimiser pour la CC2 » : repair, size, best face, then the advisor's fixes; a plan for the page."""
        from . import optimize
        path = _model_path(name)
        if path.suffix.lower() == ".gcode":
            raise HTTPException(400, "déjà tranché")
        try:
            return await asyncio.to_thread(optimize.plan, path, height_mm=height, rz=rz % 360)
        except (ValueError, OSError) as err:
            raise HTTPException(422, str(err)) from err

    @r.post("/models/{name}/repair")
    async def repair_model(name: str) -> dict[str, Any]:
        """Closed copy of an open mesh (colours kept, original untouched)."""
        from . import repair
        path = _model_path(name)
        if path.suffix.lower() not in {".glb", ".gltf", ".obj", ".ply", ".stl"}:
            raise HTTPException(400, "réparation possible pour GLB, OBJ, PLY et STL")
        try:
            return await asyncio.to_thread(repair.repair, path)
        except (ValueError, OSError) as err:
            raise HTTPException(422, str(err)) from err

    defects_cache: dict[tuple, dict[str, Any]] = {}

    @r.get("/models/{name}/defects")
    async def defects(name: str) -> dict[str, Any]:
        """Where a model is open or wrongly shared: counts and line segments to draw on it."""
        from . import repair
        path = _model_path(name)
        if path.suffix.lower() not in {".glb", ".gltf", ".obj", ".ply", ".stl"}:
            raise HTTPException(400, "diagnostic possible pour GLB, OBJ, PLY et STL")
        st = path.stat()
        key = (name, st.st_mtime_ns, st.st_size)
        if key not in defects_cache:
            try:
                defects_cache[key] = await asyncio.to_thread(repair.diagnose, path)
            except (ValueError, OSError) as err:
                raise HTTPException(422, f"diagnostic impossible : {err}") from err
            while len(defects_cache) > 8:
                defects_cache.pop(next(iter(defects_cache)))
        return defects_cache[key]

    @r.get("/models/{name}/cut-preview.glb")
    async def cut_glb(name: str, height: float | None = None, map: str | None = None, pal: str | None = None) -> Response:
        try:
            return Response((await asyncio.to_thread(_cut, name, height, map, pal))[1], media_type="model/gltf-binary")
        except ValueError as err:
            raise HTTPException(422, str(err)) from err

    @r.post("/models/{name}/prepare-print")
    async def prepare_print(name: str, body: PrepareIn) -> dict[str, Any]:
        """One step from any model to G-code: colours -> CANVAS slots, scale, slice."""
        src = _model_path(name)
        if src.suffix.lower() == ".gcode":
            raise HTTPException(400, "déjà tranché: envoie-le directement")
        try:
            res = await asyncio.to_thread(
                printprep.prepare_and_slice, src, mapping=body.mapping, filaments=body.filaments,
                quality=body.quality, infill=body.infill, supports=body.supports, plate_only=body.plate_only,
                height_mm=body.height_mm,
                mode=body.mode, split=body.split, slot_colours=body.slot_colours, plate=body.plate,
                advanced=body.advanced, rotate=tuple(body.rotate), copies=body.copies, orient=body.orient, usage=body.usage,
                palette=_pal(body.palette), pauses_mm=[h for h in body.pauses_mm if h > 0] or None,
                simplify_colours=body.simplify_colours)
        except (ValueError, slicer.SliceError) as err:
            raise HTTPException(422, str(err)) from err
        # grams and cost per spool, remembered for the check before printing and the count at the end
        items = (res["pieces"] + ([res["pins"]] if res.get("pins") else [])) if res.get("split") else [res]
        g = eur = 0.0
        for it in items:
            if it.get("gcode") and it.get("per_filament_m"):
                it["usage"] = stock.record_slice(Path(it["gcode"][0]).name, it["per_filament_m"], it.get("purge_m"))
                g, eur = g + it["usage"]["g"], eur + it["usage"]["eur"]
                library.record(Path(it["gcode"][0]).name, source=name, usage=body.usage, qualite=body.quality.split(" @")[0],
                               temps=it.get("time"), couches=it.get("layers"), g=it["usage"]["g"], eur=it["usage"]["eur"],
                               couleurs=[s["colour"] for s in it.get("slots", []) if s.get("metres", 0) > 0] or None,
                               piece=it.get("name") if res.get("split") else None)
        if res.get("split"):
            res["usage"] = {"g": round(g, 1), "eur": round(eur, 2),
                            "manques": [t for it in items for t in it.get("usage", {}).get("trays", []) if t["manque"]]}
        elif "usage" in res:
            res["usage"]["manques"] = [t for t in res["usage"]["trays"] if t["manque"]]
        return res


    async def _canvas(request: Request) -> dict[str, Any] | None:
        try:
            return (await asyncio.wait_for(request.app.state.manager.printer.canvas_status(), 15)).raw
        except Exception:
            return None

    @r.get("/entretien")
    def entretien() -> list[dict[str, Any]]:
        from . import maintenance
        return maintenance.status()

    @r.post("/entretien/{task}")
    def entretien_fait(task: str) -> list[dict[str, Any]]:
        from . import maintenance
        try:
            return maintenance.done(task)
        except ValueError as err:
            raise HTTPException(404, str(err)) from err

    @r.get("/lancement")
    def launch_options() -> dict[str, Any]:
        return launch.options()

    @r.post("/lancement")
    def launch_options_set(body: LaunchOptionsIn) -> dict[str, Any]:
        try:
            return launch.save_options(**body.model_dump())
        except ValueError as err:
            raise HTTPException(422, str(err)) from err

    @r.get("/print/plan/{name}")
    async def print_plan(name: str, request: Request) -> dict[str, Any]:
        """Start dialog: the file's colours, the loaded spools, the suggested colour -> spool map."""
        path = config.MODELS_DIR / Path(name).name
        out = await asyncio.to_thread(launch.plan, path if path.suffix == ".gcode" else None, await _canvas(request))
        pos = {t["tray_id"]: t.get("pos", t["tray_id"]) for t in out.get("trays", [])}
        out["stock"] = stock.check(Path(name).name, {m["t"]: pos.get(m["tray_id"], m["tray_id"]) for m in out.get("slot_map", [])})
        return out

    @r.post("/print/start")
    async def print_start(body: LaunchIn, request: Request) -> dict[str, Any]:
        """Start a file already on the printer, with the CC2's options and the spool map."""
        if not getattr(request.app.state.manager, "enable_control", False):
            raise HTTPException(403, "lecture seule : relance avec --control")
        from . import alerts
        w = getattr(request.app.state, "watcher", None)
        if w is not None and w.prev is not None and w.prev not in alerts.IDLE:
            raise HTTPException(409, "l'imprimante imprime déjà : ajoute ce fichier à la file d'attente")
        opts = {k: v for k, v in body.model_dump().items() if k in launch.DEFAULTS and v is not None}
        try:
            if body.remember:
                launch.save_options(**opts)
            canvas = await _canvas(request)
            unit = (canvas or {}).get("canvas_info", canvas or {}).get("canvas_list", [{}])
            loaded = {int(t["tray_id"]) for t in spools.loaded(canvas or {})}
            for m in body.slot_map or []:
                if canvas is not None and int(m["tray_id"]) not in loaded:
                    raise ValueError(f"la bobine {m['tray_id']} n'est pas chargée dans le CANVAS")
            payload = launch.params(body.filename, opts, body.slot_map,
                                    canvas_id=int(unit[0].get("canvas_id", 0)) if unit else 0)
        except (ValueError, KeyError, TypeError) as err:
            raise HTTPException(422, str(err)) from err
        from pycentauri.client import PrinterError, RequestTimeoutError
        try:
            await request.app.state.manager.printer._cc2_request(1020, payload, timeout=30)
        except RequestTimeoutError as err:
            raise HTTPException(504, "l'imprimante n'a pas confirmé le lancement : regarde son écran") from err
        except PrinterError as err:   # a refusal carries the printer's error code
            code = re.search(r"error_code=(\d+)", str(err))
            raise HTTPException(409, f"l'imprimante refuse le lancement (code {code.group(1) if code else '?'}) : impression "
                                     "déjà en cours, fichier absent ou bobine choisie vide") from err
        pos = {int(t["tray_id"]): int(t.get("pos", t["tray_id"])) for t in spools.loaded(canvas or {})}
        stock.record_route(Path(body.filename).name,
                           {int(m["t"]): pos.get(int(m["tray_id"]), int(m["tray_id"])) for m in body.slot_map or []})
        return {"ok": True, "sent": payload}


    @r.get("/canvas/bobines")
    async def loaded_spools(request: Request) -> list[dict[str, Any]]:
        """The spools in the CANVAS now, as the workshop sees them (own spools recognised), slot order."""
        return [{"slot": t["pos"] + 1, "hex": t["color"], "name": t.get("filament_name") or t.get("type"),
                 "type": t.get("type"), "filament": spools.filament_for(t)}
                for t in sorted(spools.loaded(await _canvas(request) or {}), key=lambda t: t["pos"])]

    @r.get("/bobines")
    def bobines() -> dict[str, Any]:
        """Stock of each CANVAS spool, prints taken off it, this month's total."""
        return stock.summary()

    @r.post("/bobines/{tray}")
    def bobine_set(tray: int, body: TrayIn) -> dict[str, Any]:
        try:
            return stock.set_tray(tray, restant_g=body.restant_g, poids_g=body.poids_g, prix_kg=body.prix_kg,
                                  nouvelle=body.nouvelle)
        except ValueError as err:
            raise HTTPException(422, str(err)) from err

    @r.get("/bobines/check/{name}")
    def bobines_check(name: str) -> dict[str, Any]:
        """Before printing this file: does every spool hold enough?"""
        return stock.check(Path(name).name) or {"known": False}

    compares: dict[str, dict[str, Any]] = {}

    @r.post("/models/{name}/compare")
    def compare_start(name: str, body: PrepareIn) -> dict[str, Any]:
        """Slice several variants in the background; poll GET /compare/{id}."""
        src = _model_path(name)
        if src.suffix.lower() == ".gcode":
            raise HTTPException(400, "déjà tranché")
        if any(c["state"] == "running" for c in compares.values()):
            raise HTTPException(409, "une comparaison est déjà en cours")
        cid = uuid.uuid4().hex[:10]
        job = compares[cid] = {"id": cid, "state": "running", "rows": [], "model": name}
        base = dict(mapping=body.mapping, filaments=body.filaments, quality=body.quality, infill=body.infill,
                    supports=body.supports, plate_only=body.plate_only, height_mm=body.height_mm, mode=body.mode,
                    slot_colours=body.slot_colours, plate=body.plate, advanced=body.advanced, rotate=tuple(body.rotate),
                    copies=body.copies, orient=body.orient, usage=body.usage, palette=_pal(body.palette))

        def work() -> None:
            try:
                printprep.compare(src, base, on_row=lambda rows: job.update(rows=list(rows)))
                job["state"] = "done"
            except Exception as err:
                job.update(state="error", error=str(err)[:200])
            while len(compares) > 10:
                compares.pop(next(iter(compares)))

        threading.Thread(target=work, daemon=True).start()
        return job

    @r.get("/compare/{cid}")
    def compare_get(cid: str) -> dict[str, Any]:
        if cid not in compares:
            raise HTTPException(404, "comparaison inconnue")
        return compares[cid]

    @r.post("/multicolor")
    async def multicolor(body: MulticolorIn) -> dict[str, Any]:
        stem = "".join(c if c.isalnum() or c in "-_" else "_" for c in Path(body.name).stem) or "multicolore"
        parts = [(_model_path(p.name), p.slot) for p in body.parts]

        def work() -> dict[str, Any]:
            out = config.MODELS_DIR / f"{stem}.3mf"
            n = max(len(body.filaments), max(s for _, s in parts))
            # the spools' own colours (purge sized to each change), else the workshop's fixed palette
            cols = [c.upper() if c and spools.HEX.fullmatch(c) else colorize.PALETTE[i % 4]
                    for i, c in enumerate(((body.colours or []) + [""] * n)[:n])]
            info = colorize.build_3mf(parts, out, filaments=len(body.filaments), name=stem, colours=cols,
                                      flush=colors.flush_matrix(cols) if body.colours else None)
            res = slicer.slice_model(out, config.MODELS_DIR, quality=body.quality,
                                     filament=body.filaments, infill=body.infill, colours=cols)
            return {**res.as_dict(), "project": out.name, "size_mm": info["size_mm"],
                    "load": [f"bobine {i + 1} = {n}" for i, n in enumerate(body.filaments)]}

        try:
            return await asyncio.to_thread(work)
        except (ValueError, slicer.SliceError) as err:
            raise HTTPException(422, str(err)) from err

    @r.get("/comfy")
    def comfy_status() -> dict[str, Any]:
        wf = sorted(p.stem for p in comfy.WORKFLOWS.glob("*.json") if not p.stem.endswith(".map")
                    and (config.hunyuan_allowed() or not p.stem.startswith("hunyuan")))
        try:
            s = comfy.Comfy(cfg.comfyui_url, timeout=3).stats()
            gpus = [d.get("name") for d in s.get("devices", [])]
            return {"url": cfg.comfyui_url, "online": True, "devices": gpus, "workflows": wf}
        except comfy.ComfyError as err:
            return {"url": cfg.comfyui_url, "online": False, "error": str(err), "workflows": wf}

    @r.post("/generate")
    async def generate(
        workflow: str = Form(...),
        prompt: str | None = Form(None),
        image: UploadFile | None = File(None),
    ) -> dict[str, str]:
        tmp: Path | None = None
        if image is not None and image.filename:
            tmp = config.ROOT / "models" / f".upload_{uuid.uuid4().hex}_{Path(image.filename).name}"
            with tmp.open("wb") as out:
                shutil.copyfileobj(image.file, out)
        jid = uuid.uuid4().hex[:8]
        jobs[jid] = {"id": jid, "state": "running", "workflow": workflow, "started": time.time()}
        save_jobs()

        def work() -> None:
            try:
                files = comfy.generate(comfy.Comfy(cfg.comfyui_url), workflow, config.MODELS_DIR,
                                       image=tmp, prompt=prompt or None, on_queued=queued(jid))
                finished(jid, files)
            except Exception as err:  # surfaced to the UI
                jobs[jid].update(state="error", error=str(err))
                save_jobs()
            finally:
                if tmp:
                    tmp.unlink(missing_ok=True)

        asyncio.get_running_loop().run_in_executor(None, work)
        return {"job": jid}

    # generations survive a restart of the workshop: ComfyUI keeps computing, we pick the result up
    def save_jobs() -> None:
        recent = sorted(jobs.values(), key=lambda j: -j["started"])[:30]
        JOBS_FILE.write_text(json.dumps(recent))

    def queued(jid: str) -> Any:
        def mark(workflow: str, pid: str) -> None:
            jobs[jid]["stage"] = {"workflow": workflow, "prompt_id": pid}
            save_jobs()
        return mark

    def finished(jid: str, files: list[Path]) -> None:
        jobs[jid].update(state="done", files=[f.name for f in files if f.parent == config.MODELS_DIR],
                         images=[f.name for f in files if f.parent != config.MODELS_DIR])
        save_jobs()

    def resume_all() -> None:
        try:
            saved = json.loads(JOBS_FILE.read_text()) if JOBS_FILE.exists() else []
        except ValueError:
            saved = []
        for j in saved:
            jobs[j["id"]] = j
            if j.get("state") != "running":
                continue
            stage = j.get("stage")
            if not stage:
                j.update(state="error", error="interrompue avant d'atteindre ComfyUI : relance-la")
                continue

            def work(j: dict = j, stage: dict = stage) -> None:
                try:
                    files = comfy.resume(comfy.Comfy(cfg.comfyui_url), stage["workflow"], stage["prompt_id"],
                                         config.MODELS_DIR, on_queued=queued(j["id"]))
                    finished(j["id"], files)
                except Exception as err:
                    j.update(state="error", error=str(err))
                    save_jobs()

            threading.Thread(target=work, daemon=True, name=f"resume-{j['id']}").start()
        save_jobs()

    resume_all()

    @r.get("/references/{name}")
    def reference(name: str) -> FileResponse:
        p = config.MODELS_DIR / "references" / Path(name).name
        if not p.is_file():
            raise HTTPException(404, "image introuvable")
        return FileResponse(p)

    @r.get("/jobs")
    def list_jobs() -> list[dict[str, Any]]:
        return sorted(jobs.values(), key=lambda j: -j["started"])

    return r


class SameOriginGuard:
    """Refuse state-changing requests that a browser sends on behalf of another site (CSRF).

    Without it any web page open on this PC could upload and start a print, pause or stop it:
    form posts and body-less POSTs are not blocked by the browser's CORS checks. Requests without
    Origin/Referer/Sec-Fetch-Site (CLI, scripts) are not browser-driven and pass.
    """

    SAFE = {"GET", "HEAD", "OPTIONS"}

    def __init__(self, app: Any) -> None:
        self.app = app

    async def __call__(self, scope: dict, receive: Any, send: Any) -> None:
        if scope["type"] == "http" and scope["method"] not in self.SAFE:
            h = {k.decode().lower(): v.decode() for k, v in scope.get("headers", [])}
            host = h.get("host", "")
            site = h.get("sec-fetch-site")
            source = h.get("origin") or h.get("referer") or ""
            foreign = site in ("cross-site", "same-site") or (bool(source) and urlsplit(source).netloc != host)
            if foreign:
                body = json.dumps({"detail": "Requête refusée : elle ne vient pas de l'atelier."}).encode()
                await send({"type": "http.response.start", "status": 403,
                            "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode())]})
                await send({"type": "http.response.body", "body": body})
                return
        await self.app(scope, receive, send)


def _add_alerts(app: FastAPI) -> None:
    """Start the print watcher with the printer connection, and expose its events."""
    from contextlib import asynccontextmanager
    from fastapi.responses import FileResponse
    from sse_starlette.sse import EventSourceResponse
    from . import alerts

    inner = app.router.lifespan_context

    @asynccontextmanager
    async def lifespan(a: FastAPI):
        async with inner(a):
            mgr = a.state.manager
            from . import vision
            w = alerts.Watcher(lambda: mgr.printer.status(), lambda: vision.grab(mgr), lambda: mgr.printer.canvas_status(),
                               lambda: mgr.printer.pause(), lambda: mgr.printer.set_light(True),
                               lambda: mgr.printer.print_history())
            a.state.watcher = w
            task = asyncio.create_task(w.run(), name="cc2-alerts")
            try:
                yield
            finally:
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError, Exception):
                    await task

    app.router.lifespan_context = lifespan

    def watcher(request: Request) -> "alerts.Watcher":
        w = getattr(request.app.state, "watcher", None)
        if w is None:
            raise HTTPException(503, "Suivi pas encore démarré")
        return w

    @app.get("/lab/api/events", include_in_schema=False)
    def events(request: Request) -> list[dict[str, Any]]:
        return list(reversed(watcher(request).events[-50:]))

    @app.get("/lab/api/events/stream", include_in_schema=False)
    async def events_stream(request: Request) -> EventSourceResponse:
        w = watcher(request)

        async def gen():
            async for ev in w.stream():
                if await request.is_disconnected():
                    break
                yield {"event": "alerte", "data": json.dumps(ev, ensure_ascii=False)}

        return EventSourceResponse(gen(), ping=20)

    @app.get("/lab/api/galerie", include_in_schema=False)
    def galerie() -> list[dict[str, Any]]:
        from . import gallery
        lib = {p.name for p in config.MODELS_DIR.glob("*.gcode")}
        return [{**e, "dans_bibliotheque": e.get("fichier") in lib} for e in gallery.entries()]

    @app.get("/lab/api/galerie/{entry}/{name}", include_in_schema=False)
    def galerie_file(entry: str, name: str) -> FileResponse:
        from . import gallery
        try:
            p = gallery.file(entry, name)
        except FileNotFoundError as err:
            raise HTTPException(404, "Introuvable") from err
        return FileResponse(p, media_type="video/mp4" if p.suffix == ".mp4" else "image/jpeg")

    @app.delete("/lab/api/galerie/{entry}", include_in_schema=False)
    def galerie_delete(entry: str) -> dict[str, bool]:
        from . import gallery
        try:
            gallery.delete(entry)
        except FileNotFoundError as err:
            raise HTTPException(404, "Introuvable") from err
        return {"ok": True}


    model_dl: dict[str, Any] = {"state": "idle"}

    @app.get("/lab/api/surveillance", include_in_schema=False)
    def surveillance_get(request: Request) -> dict[str, Any]:
        from . import vision
        w = getattr(request.app.state, "watcher", None)
        live = None
        if w is not None:
            p = w.pred
            live = {"frames": p.frames, "score": round(p.ewm - p.long, 3), "history": p.history[-60:],
                    "etat": "pause" if w.ai_paused else "suspect" if p.failing(w.settings["sensibilite"]) else "ok",
                    "en_cours": w.prev not in alerts.IDLE if w.prev is not None else False}
        return {**alerts.surveillance(), "modele": vision.model_ready(), "telechargement": model_dl, "live": live}

    @app.post("/lab/api/surveillance", include_in_schema=False)
    def surveillance_set(body: SurvIn) -> dict[str, Any]:
        cur = alerts.surveillance()
        vals = {k: v for k, v in body.model_dump().items() if v is not None}
        if "sensibilite" in vals and not 0.5 <= vals["sensibilite"] <= 2:
            raise HTTPException(422, "sensibilité entre 0,5 et 2")
        config.save("surveillance", **{**cur, **vals})
        return alerts.surveillance()

    @app.get("/lab/api/alertes/telephone", include_in_schema=False)
    def phone_alerts_get() -> dict[str, Any]:
        return {"ntfy": alerts.ntfy_url()}

    @app.post("/lab/api/alertes/telephone", include_in_schema=False)
    async def phone_alerts_set(body: PhoneAlertIn) -> dict[str, Any]:
        """Phone alerts that work with the app closed, through the ntfy app (opt-in: leaves the house network).
        "on" makes an unguessable topic: anyone who knows it reads the alerts, so it is never reused."""
        if body.action == "on":
            config.save("alertes", ntfy=f"https://ntfy.sh/cc2-{uuid.uuid4().hex[:20]}")
        elif body.action == "off":
            config.save("alertes", ntfy="")
        elif body.action == "test":
            if not alerts.ntfy_url():
                raise HTTPException(409, "alertes téléphone désactivées")
            ok = await alerts.send_ntfy({"title": "Test de l'atelier", "detail": "Les alertes arrivent bien sur ce téléphone.", "level": "ok"})
            if not ok:
                raise HTTPException(502, "ntfy injoignable : vérifie la connexion internet du PC")
        else:
            raise HTTPException(422, "action inconnue")
        return {"ntfy": alerts.ntfy_url()}

    @app.post("/lab/api/surveillance/modele", include_in_schema=False)
    def surveillance_model() -> dict[str, Any]:
        from . import vision
        if vision.model_ready() or model_dl["state"] == "running":
            return model_dl
        model_dl.update(state="running", done=0, total=0, error=None)

        def work() -> None:
            try:
                vision.download_model(lambda d, t: model_dl.update(done=d, total=t))
                model_dl["state"] = "done"
            except Exception as err:
                model_dl.update(state="error", error=str(err)[:200])

        threading.Thread(target=work, daemon=True).start()
        return model_dl

    @app.get("/lab/api/photos/{name}", include_in_schema=False)
    def photo(name: str) -> FileResponse:
        p = alerts.photos_dir() / Path(name).name
        if not p.is_file() or p.suffix != ".jpg":
            raise HTTPException(404, "Photo introuvable")
        return FileResponse(p, media_type="image/jpeg")

    for _ in range(9):  # ahead of the /lab static mount
        app.router.routes.insert(0, app.router.routes.pop())


def create_app(*, enable_control: bool = False, lan: bool = False, port: int = 0,
               https: bool = False, http_port: int = 0) -> FastAPI:
    cfg = config.load()
    p = cfg.printer
    import pycentauri.server as printer_server
    printer_server.RECONNECT_BACKOFF_MAX = 8.0   # printer switched on: found within seconds, not up to 30 s
    if not p.host or not p.access_code:
        raise SystemExit("Imprimante non configurée: copie config.example.toml en config.toml "
                         "(host + access_code).")
    app = create_printer_app(p.host, enable_control=enable_control,
                             mainboard_id=p.serial, access_code=p.access_code)
    config.MODELS_DIR.mkdir(exist_ok=True)
    from fastapi.middleware.gzip import GZipMiddleware
    app.add_middleware(GZipMiddleware, minimum_size=4096)  # G-code paths and previews compress ~2.5x
    app.add_middleware(SameOriginGuard)
    if lan:
        from . import access
        app.add_middleware(access.Gate, https_port=port if https else 0)  # outermost: nothing runs before the access check
    app.include_router(lab_router(cfg))
    app.mount("/lab", FreshStatic(directory=WEB, html=True), name="lab")

    # a model renamed or deleted while it was being read (the page asks for its colours, positions...
    # on opening it): "not found", not a server error nor "impossible to compute"
    from fastapi.exception_handlers import http_exception_handler
    from starlette.exceptions import HTTPException as StarletteHTTPException

    def _gone(request: Request, err: BaseException) -> bool:
        name = request.path_params.get("name")
        return isinstance(err, FileNotFoundError) and bool(name) and not (config.MODELS_DIR / Path(name).name).exists()

    @app.exception_handler(FileNotFoundError)
    async def model_gone(request: Request, err: FileNotFoundError) -> Response:
        if _gone(request, err):
            return JSONResponse({"detail": f"modèle introuvable: {request.path_params['name']}"}, status_code=404)
        raise err

    @app.exception_handler(StarletteHTTPException)
    async def model_gone_422(request: Request, err: StarletteHTTPException) -> Response:
        if err.status_code == 422 and _gone(request, err.__cause__):
            return JSONResponse({"detail": f"modèle introuvable: {request.path_params['name']}"}, status_code=404)
        return await http_exception_handler(request, err)

    # our shell replaces pycentauri's "/" -> "/ui/" redirect
    @app.get("/", include_in_schema=False)
    def home() -> RedirectResponse:
        return RedirectResponse("/lab/", status_code=307)

    home_route = app.router.routes.pop()
    app.router.routes.insert(0, home_route)

    @app.get("/lab/api/context", include_in_schema=False)
    def context(request: Request) -> dict[str, Any]:
        from .access import is_local
        return {"control": enable_control, "host": p.host, "lan": lan,
                "local": is_local(request.client.host if request.client else None)}

    app.router.routes.insert(0, app.router.routes.pop())
    _add_alerts(app)
    if lan:   # alerts can link back to the workshop (ntfy "Faire le bilan")
        from . import alerts
        alerts.APP.update(https=https, port=port)

    @app.get("/lab/api/phone", include_in_schema=False)
    def phone() -> dict[str, Any]:
        """Address to open on the phone, with a QR code (only when the workshop is open to the network)."""
        if not lan:
            return {"lan": False}
        import io
        import qrcode
        import qrcode.image.svg
        from . import access
        def qr(text: str) -> str:
            buf = io.BytesIO()
            qrcode.make(text, image_factory=qrcode.image.svg.SvgPathImage, border=2).save(buf)
            return buf.getvalue().decode()

        ip = access.lan_ip()
        local = f"{'https' if https else 'http'}://{ip}:{port}/lab/"
        # with Tailscale the phone installs the app from this PC's Tailscale name: the same app at home and away
        ts = access.tailscale()
        host = (ts["name"] or ts["ip"]) if ts else ip
        url = f"{'https' if https else 'http'}://{host}:{port}/lab/"
        out = {"lan": True, "url": url, "qr": qr(url), "https": https, "tailscale": bool(ts), "local_url": local}
        if https:
            out["ca_url"] = f"http://{host}:{http_port}/lab/ca.crt"
            out["ca_qr"] = qr(out["ca_url"])
        return out

    app.router.routes.insert(0, app.router.routes.pop())

    @app.get("/lab/ca.crt", include_in_schema=False)
    def ca_cert() -> Response:
        """Public certificate of the workshop's local authority, to install once on the phone."""
        if not https:
            raise HTTPException(404, "HTTPS non activé")
        from . import certs
        return Response(certs.ca_pem(), media_type="application/x-x509-ca-cert",
                        headers={"Content-Disposition": 'attachment; filename="atelier-cc2.crt"'})

    app.router.routes.insert(0, app.router.routes.pop())
    return app
