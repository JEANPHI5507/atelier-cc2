"""Print follow-up: watches the printer and turns state changes into alerts.

Runs inside the dashboard, so alerts happen even when no browser is open. Each event is kept in
models/.events.json (last 200), pushed live to open pages (SSE), and optionally sent to the phone
through ntfy (``[alertes] ntfy = "https://ntfy.sh/<topic>"``, opt-in: it leaves the house network).
At the end of a print a camera photo is saved in models/.photos/.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import re
import logging
import time
from typing import Any, AsyncIterator, Callable

from . import config

log = logging.getLogger(__name__)



def events_file():
    return config.MODELS_DIR / ".events.json"   # looked up each time: tests swap the library


def photos_dir():
    return config.MODELS_DIR / ".photos"

KEEP = 200
POLL_S = 5.0
LOST_AFTER_S = 60.0          # a print we cannot see for this long is worth telling
IDLE = {0, 8, 9, 14, 99}   # 99: a machine state pycentauri does not know (seen while the CC2 starts up), not a print
PAUSED = {5, 6}

# kind -> (level, title)
KINDS = {
    "debut": ("info", "Impression lancée"),
    "pause": ("warn", "Impression en pause"),
    "filament": ("bad", "Plus de filament"),
    "reprise": ("info", "Impression reprise"),
    "fin": ("ok", "Impression terminée"),
    "froid": ("ok", "Plateau froid : tu peux retirer la pièce"),
    "arret": ("warn", "Impression arrêtée"),
    "erreur": ("bad", "Erreur de l'imprimante"),
    "perdue": ("bad", "Imprimante injoignable"),
    "retrouvee": ("info", "Imprimante de nouveau joignable"),
    "stock": ("warn", "Bobine presque vide"),
    "bobine": ("info", "Nouvelle bobine détectée"),
    "suspect": ("warn", "Impression suspecte"),
    "anomalie": ("warn", "L'imprimante signale un problème"),
    "camera": ("warn", "Caméra figée"),
    "entretien": ("warn", "Entretien à faire"),
    "rate": ("bad", "Raté détecté : impression mise en pause"),
}
SURVEILLANCE = {"ia": True, "pause_auto": False, "sensibilite": 1.0, "timelapse": True}
AI_EVERY_S = 10.0             # one analysed frame every 10 s, like Obico
SUSPECT_EVERY_S = 600.0       # at most one "suspect" warning per 10 min
COLD_BED_C = 35               # PLA lets go of the PEI plate by itself below this (same figure as the after-print tips)
COLD_WAIT_S = 3 * 3600        # stop waiting after this: the printer was switched off or the part already taken
AI_STOP_PCT = 98              # last moves: the head parks, the finished part's fine details look like spaghetti
                              # (false alert at 99 % on 2026-11-11), and nothing could be saved that late anyway


def surveillance() -> dict[str, Any]:
    """Camera settings from config.toml [surveillance] (AI watch, auto pause, sensitivity, timelapse)."""
    out = dict(SURVEILLANCE)
    if config.CONFIG_FILE.exists():
        import tomllib
        for k, v in tomllib.loads(config.CONFIG_FILE.read_text()).get("surveillance", {}).items():
            if k in out and isinstance(v, type(out[k])) or (k == "sensibilite" and isinstance(v, (int, float))):
                out[k] = v
    out["sensibilite"] = float(min(2.0, max(0.5, out["sensibilite"])))
    return out


def ntfy_url() -> str | None:
    if not config.CONFIG_FILE.exists():
        return None
    import tomllib
    url = tomllib.loads(config.CONFIG_FILE.read_text()).get("alertes", {}).get("ntfy")
    return url if isinstance(url, str) and url.startswith("https://") else None


def _queue_head() -> str | None:
    """First G-code waiting in the print queue (models/.queue.json), if any."""
    try:
        q = json.loads((config.MODELS_DIR / ".queue.json").read_text())
    except (OSError, ValueError):
        return None
    return next((n for n in q if isinstance(n, str) and (config.MODELS_DIR / n).exists()), None)


_GCODE = re.compile(r"\S+?\.gcode\b", re.I)
_SLICED = re.compile(r"^(.*?)(?:_canvas)?_(\d+(?:\.\d+)?)mm_.*\.gcode$", re.I)


def nice(name: str) -> str:
    """A G-code name to read on a phone: the model and the layer height, like the workshop's pages
    ("atelier_couleurs_00015_clean_canvas_0.24mm_PLA_Silk_Noel-….gcode" -> "atelier couleurs 00015 clean · 0,24 mm")."""
    m = _SLICED.match(name)
    base = re.sub(r"^\d{8}-\d{6}_", "", m.group(1) if m else re.sub(r"\.[^.]+$", "", name)).replace("_", " ").strip()
    return (base or name) + (f" · {m.group(2).replace('.', ',')} mm" if m else "")


APP: dict[str, Any] = {}          # set by the app when it is open to the network: {"https": bool, "port": int}
_app_url: list[str | None] = []


def app_url() -> str | None:
    """The workshop's address for the phone (Tailscale name first: it works at home and away), or None."""
    if not APP:
        return None
    if not _app_url:
        from . import access
        ts = access.tailscale()
        host = (ts["name"] or ts["ip"]) if ts else access.lan_ip()
        _app_url.append(f"{'https' if APP.get('https') else 'http'}://{host}:{APP['port']}/lab/" if APP.get("port") else None)
    return _app_url[0]


async def send_ntfy(ev: dict[str, Any]) -> bool:
    """Push one alert to the ntfy topic, if set. Returns whether ntfy accepted it.
    A finished print carries a "Faire le bilan" button that opens the workshop on that print's review."""
    url = ntfy_url()
    if not url:
        return False
    from .i18n import tr   # in the language last chosen in the interface
    extra: dict[str, str] = {}
    if (base := app_url()):
        extra["Click"] = base
        if ev.get("bilan"):
            extra["Actions"] = f"view, {tr('Faire le bilan')}, {base}#bilan={ev['bilan']}, clear=true"
    import httpx
    try:
        async with httpx.AsyncClient(timeout=10) as c:
            # ntfy reads UTF-8 titles from the "Title" header only RFC 2047-encoded: send it as a query param instead
            body = tr(_GCODE.sub(lambda m: nice(m.group(0)), ev["detail"] or ev["title"]))
            r = await c.post(url, params={"title": tr(ev["title"]) or "CC2"}, content=body.encode(),
                             headers={**extra, "Priority": "high" if ev["level"] == "bad" else "default",
                                      "Tags": {"ok": "white_check_mark", "warn": "warning", "bad": "rotating_light"}[ev["level"]]})
            return r.is_success
    except Exception as e:  # never let a phone notification break the watcher
        log.warning("ntfy: %s", e)
        return False


class Watcher:
    def __init__(self, status: Callable[[], Any], snapshot: Callable[[], Any] | None = None,
                 canvas: Callable[[], Any] | None = None, pause: Callable[[], Any] | None = None,
                 light: Callable[[], Any] | None = None, history: Callable[[], Any] | None = None) -> None:
        """Awaitables: ``status`` -> pycentauri Status, ``snapshot`` -> JPEG bytes, ``canvas`` -> CANVAS payload,
        ``pause`` pauses the print (used when the AI is sure the print failed and auto pause is on),
        ``history`` -> the printer's print history (method 1036), which says how a print really ended."""
        from . import vision
        self.status, self.snapshot, self.canvas, self.pause, self.light = status, snapshot, canvas, pause, light
        self.history = history
        self.codes: set[int] = set()       # error codes already reported for this print
        self.cam_fail = 0
        self.cam_same = 0
        self.cam_last: bytes | None = None
        self.cam_warned = False
        self.ticks = 0
        self.rec = None              # gallery entry of the print in progress
        self.pred = vision.Prediction()
        self.layer: int | None = None
        self.last_ai = self.last_suspect = 0.0
        self.ai_paused = False
        self.settings = surveillance()
        self.events: list[dict[str, Any]] = self._load()
        self.subscribers: set[asyncio.Queue] = set()
        self.prev: int | None = None
        self.progress = 0
        self.filename = ""
        self.started = 0.0
        self.last_seen = time.time()
        self.lost = False
        self.cooling: dict[str, Any] | None = None   # finished print waiting for a cold plate: {"name", "since", "bilan"}

    # --- journal -----------------------------------------------------------

    def _load(self) -> list[dict[str, Any]]:
        try:
            return json.loads(events_file().read_text())[-KEEP:]
        except (OSError, ValueError):
            return []

    def _save(self) -> None:
        f = events_file()
        f.parent.mkdir(exist_ok=True)
        tmp = f.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.events[-KEEP:], ensure_ascii=False))
        tmp.replace(f)

    def emit(self, kind: str, detail: str = "", **extra: Any) -> dict[str, Any]:
        level, title = KINDS[kind]
        ev = {"id": f"{time.time():.3f}", "t": int(time.time()), "kind": kind, "level": level,
              "title": title, "detail": detail, **extra}
        self.events.append(ev)
        self.events = self.events[-KEEP:]
        self._save()
        for q in list(self.subscribers):
            with contextlib.suppress(asyncio.QueueFull):
                q.put_nowait(ev)
        if level != "info":
            with contextlib.suppress(RuntimeError):   # no event loop (CLI, tests): no phone push
                asyncio.get_running_loop().create_task(self._ntfy(ev))
        return ev

    async def _ntfy(self, ev: dict[str, Any]) -> None:
        await send_ntfy(ev)

    async def stream(self) -> AsyncIterator[dict[str, Any]]:
        q: asyncio.Queue = asyncio.Queue(maxsize=50)
        self.subscribers.add(q)
        try:
            while True:
                yield await q.get()
        finally:
            self.subscribers.discard(q)

    # --- state machine -----------------------------------------------------

    def observe(self, ps: int, progress: int, filename: str, cc2: dict[str, Any]) -> None:
        """Feed one status reading; emits the events that the change from the previous one implies."""
        prev, self.prev = self.prev, ps
        if prev is None:                      # first reading: learn, don't alert about the past
            if ps not in IDLE:
                self.filename = filename
                self._open(filename, resume=True)   # the workshop restarted mid-print: keep recording from here
                self.started = self.rec.meta["debut"] if self.rec else time.time()
            self._close_stale()
            last = self.events[-1] if self.events else {}
            if ps in IDLE and last.get("kind") == "fin" and time.time() - last["t"] < COLD_WAIT_S:
                # the workshop restarted while the part cooled: still say when it is cold
                self.cooling = {"name": filename, "since": float(last["t"]), **({"bilan": last["bilan"]} if last.get("bilan") else {})}
            self.progress = progress
            return
        was_busy, busy = prev not in IDLE, ps not in IDLE
        name = filename or self.filename
        pre = f"{name} : " if name else ""
        if busy and not was_busy:
            self.cooling = None               # a new print: the last part was taken off
            self.started, self.filename = time.time(), filename
            self.emit("debut", filename)
            self._open(filename)
        elif busy and ps in PAUSED and prev not in PAUSED:
            codes = cc2.get("exception_status") or []
            if cc2.get("filament_detect_enable") and cc2.get("filament_detected") == 0:
                self.emit("filament", f"{pre}recharge une bobine puis reprends l'impression.")
            elif codes:   # the CC2 reports a CANVAS runout or jam here, not on the tray (Elegoo SDK)
                from . import errors
                self.codes |= {int(c) for c in codes if str(c).isdigit()}
                codes = sorted(codes, key=lambda c: not str(c).startswith("12"))   # CANVAS feed problems first
                known = [c for c in codes if str(c).isdigit() and int(c) in errors.CODES]
                self.emit("filament" if not known or str(known[0]).startswith("12") else "anomalie",
                          pre + (errors.sentence(codes) if known else f"pause demandée par l'imprimante (code "
                                 f"{', '.join(map(str, codes))}), souvent une bobine vide. Regarde l'écran, recharge, puis reprends."))
            else:
                self.emit("pause", name)
        elif busy and prev in PAUSED and ps not in PAUSED:
            self.emit("reprise", name)
            if self.ai_paused:                # the user looked and resumed: start judging afresh
                self.ai_paused = False
                self.pred.new_print()
        elif was_busy and not busy:
            mins = round((time.time() - self.started) / 60) if self.started else None
            took = f"terminée en {mins // 60} h {mins % 60:02d}. " if mins and mins >= 60 else (f"terminée en {mins} min. " if mins else "")
            if ps == 14:
                from . import errors
                codes = cc2.get("exception_status") or []
                ev = self.emit("erreur", pre + (errors.sentence(codes) if codes else "arrêt sur erreur. Regarde l'écran de l'imprimante."))
                self._account(name, self.progress / 100, ev["id"])
                self._close("erreur", ev, self.rec, self.progress)
                self.rec = None
            elif ps == 9 or self.progress >= 98:
                self._done(name, took, self.rec)
                self.rec = None
            elif self.history:
                # the real CC2 goes from ~97 % straight to idle, without the "completed" state: ask its history
                rec, self.rec = self.rec, None
                with contextlib.suppress(RuntimeError):
                    asyncio.get_running_loop().create_task(self._settle(name, took, self.progress, self.started, rec))
            else:
                self._stopped(name, self.progress, self.rec)
                self.rec = None
            self.started = 0.0
        if busy and ps not in PAUSED:
            new = [c for c in (cc2.get("exception_status") or []) if str(c).isdigit() and int(c) not in self.codes]
            if new:
                from . import errors
                self.codes |= {int(c) for c in new}
                self.emit("anomalie", pre + errors.sentence(new))
        if busy:
            self.progress = progress
            self.filename = name

    # --- gallery, timelapse and AI watch -----------------------------------

    def _multicolour(self, name: str) -> bool:
        from pathlib import Path
        from . import stock
        rec = stock.load()["prints"].get(Path(name).name) if name else None
        return bool(rec) and sum(1 for m in rec["per_m"] if m > 0) > 1

    def _done(self, name: str, took: str, rec: Any) -> None:
        pre = f"{name} : " if name else ""
        nxt = _queue_head()
        ev = self.emit("fin", f"{pre}{took}Attends que le plateau refroidisse avant de décoller la pièce : "
                       f"je te préviens quand il est sous {COLD_BED_C} °C."
                       + (" Pense à vider le bac de purge." if self._multicolour(name) else "")
                       + (f" Ensuite, lance la suivante de la file : {nxt}." if nxt else ""),
                       **({"bilan": rec.id} if rec else {}))   # the phone and the page offer the review of this print
        self.cooling = {"name": name, "since": time.time(), **({"bilan": rec.id} if rec else {})}
        if self.snapshot:
            with contextlib.suppress(RuntimeError):
                asyncio.get_running_loop().create_task(self._photo(ev))
        self._account(name, 1.0, ev["id"])
        self._close("terminee", ev, rec, 100)

    def cool(self, bed: float | None) -> None:
        """After a finished print, one alert when the plate is cold enough to take the part off."""
        c = self.cooling
        if not c or self.prev not in IDLE:
            return
        if time.time() - c["since"] > COLD_WAIT_S:
            self.cooling = None
        elif bed is not None and bed < COLD_BED_C:
            self.cooling = None
            self.emit("froid", f"{c['name'] + ' : ' if c['name'] else ''}plateau à {round(bed)} °C, la pièce se décolle "
                      "presque seule. Sinon, retire la plaque et plie-la doucement.",
                      **({"bilan": c["bilan"]} if c.get("bilan") else {}))

    def _stopped(self, name: str, progress: int, rec: Any) -> None:
        ev = self.emit("arret", f"{name + ' : ' if name else ''}arrêtée à {progress} %")
        self._account(name, progress / 100, ev["id"])
        self._close("arretee", ev, rec, progress)

    async def _settle(self, name: str, took: str, progress: int, started: float, rec: Any) -> None:
        """task_status 1 = completed, 2 = stopped (seen on the printer, 2026-11-09)."""
        from pathlib import Path
        finished = False
        try:
            h = await asyncio.wait_for(self.history(), timeout=15)
            tasks = [t for t in (h or {}).get("history_task_list", [])
                     if t.get("task_name") == Path(name).name and t.get("end_time", 0) >= started - 120]
            finished = bool(tasks) and max(tasks, key=lambda t: t["end_time"]).get("task_status") == 1
        except Exception as e:
            log.warning("historique: %s", e)
        if finished:
            self._done(name, took, rec)
        else:
            self._stopped(name, progress, rec)

    def _close_stale(self) -> None:
        from . import gallery
        ids = gallery.stale(self.rec.id if self.rec else None)   # listed now: a print opened later is not one of them
        if ids:
            with contextlib.suppress(RuntimeError):
                asyncio.get_running_loop().create_task(asyncio.to_thread(gallery.close_stale, ids))

    def _open(self, filename: str, resume: bool = False) -> None:
        from . import gallery
        self.pred.new_print()
        self.layer, self.ai_paused = None, False
        self.codes, self.cam_fail, self.cam_same, self.cam_last, self.cam_warned = set(), 0, 0, None, False
        cfg = surveillance()
        if self.light and (cfg["ia"] or cfg["timelapse"]):
            # the camera needs light; owners also report the CC2's own AI erroring when the light goes off
            with contextlib.suppress(RuntimeError):
                asyncio.get_running_loop().create_task(self._light_on())
        try:
            self.rec = (gallery.Recorder.resume if resume else gallery.Recorder)(filename or "impression")
        except OSError as e:
            log.warning("galerie: %s", e)
            self.rec = None

    async def _light_on(self) -> None:
        with contextlib.suppress(Exception):
            await asyncio.wait_for(self.light(), timeout=10)

    def _camera_health(self, jpeg: bytes | None) -> None:
        """Firmware 01.03.01.89 and later: the stream may freeze after a few hours (back after a power cycle)."""
        if jpeg is None:
            self.cam_fail += 1
        else:
            self.cam_fail = 0
            self.cam_same = self.cam_same + 1 if jpeg == self.cam_last else 0
            self.cam_last = jpeg
        if not self.cam_warned and (self.cam_fail >= 6 or self.cam_same >= 10):
            self.cam_warned = True
            self.emit("camera", f"{self.filename} : la caméra ne donne plus d'image" + (" nouvelle" if self.cam_same else "")
                      + ". Défaut connu du firmware : elle revient après un arrêt complet de l'imprimante "
                        "(à faire après cette impression). Surveillance IA et timelapse en pause d'ici là.")

    def _close(self, issue: str, ev: dict[str, Any], rec: Any, progress: int) -> None:
        """``rec`` is the gallery entry of the print that ended (taken off ``self.rec`` by the caller)."""
        if rec is None:
            return
        with contextlib.suppress(RuntimeError):
            asyncio.get_running_loop().create_task(self._finish(rec, issue, ev, progress))

    async def _finish(self, rec: Any, issue: str, ev: dict[str, Any], progress: int) -> None:
        from . import stock
        if self.snapshot and rec.frames == 0:   # otherwise the last timelapse frame is the photo
            with contextlib.suppress(Exception):
                rec.meta["photo"] = rec.add_image("photo.jpg", await asyncio.wait_for(self.snapshot(), timeout=15))
        used = next((h for h in stock.load()["history"] if h.get("ref") == ev["id"]), None)
        facts = {"g": used["g"], "eur": used["eur"]} if used else {}
        try:
            meta = await asyncio.to_thread(rec.finish, issue, progression=progress, **facts)
        except Exception as e:
            log.warning("galerie: %s", e)
            return
        from . import maintenance
        with contextlib.suppress(Exception):    # printing hours just grew: announce what became due
            for t in await asyncio.to_thread(maintenance.newly_due):
                self.emit("entretien", f"{t['titre']} ({t['intervalle']}). {t['geste']}")
        for q in list(self.subscribers):   # the gallery shows the new entry without a reload
            with contextlib.suppress(asyncio.QueueFull):
                q.put_nowait({"kind": "galerie", "update": True, "entry": meta["id"]})

    async def _camera(self, layer: int | None) -> None:
        """During a print: one frame per new layer for the timelapse, one every 10 s for the AI."""
        from . import vision
        if self.ticks % 12 == 0:
            self.settings = surveillance()
        cfg = self.settings
        want_tl = cfg["timelapse"] and self.rec is not None and layer and layer != self.layer
        want_ai = (cfg["ia"] and vision.model_ready() and not self.ai_paused and self.prev not in PAUSED
                   and time.time() - self.last_ai >= AI_EVERY_S)
        if not (want_tl or want_ai) or not self.snapshot:
            return
        try:
            jpeg = await asyncio.wait_for(self.snapshot(), timeout=10)
        except Exception:
            self._camera_health(None)
            return
        self._camera_health(jpeg)
        if self.cam_same >= 10:
            return                       # frozen picture: neither a timelapse frame nor something to judge
        if want_tl:
            self.layer = layer
            await asyncio.to_thread(self.rec.add_frame, jpeg)
        if not want_ai or self.progress >= AI_STOP_PCT:
            return
        self.last_ai = time.time()
        try:
            dets = await asyncio.to_thread(vision.detect, jpeg)
        except Exception as e:
            log.warning("vision: %s", e)
            return
        self.pred.update(sum(c for c, _ in dets))
        sure = self.pred.failing(cfg["sensibilite"], escalate=True)
        if sure and cfg["pause_auto"] and self.pause:
            name = await self._alert_image(jpeg, dets)
            with contextlib.suppress(Exception):
                await self.pause()
            self.ai_paused = True
            self.emit("rate", f"{self.filename} : l'IA voit un raté (spaghetti ou pièce décollée). Regarde la photo : "
                              "reprends si tout va bien, sinon arrête.", photo=name)
        elif (sure or self.pred.failing(cfg["sensibilite"])) and time.time() - self.last_suspect > SUSPECT_EVERY_S:
            self.last_suspect = time.time()
            name = await self._alert_image(jpeg, dets)
            self.emit("suspect", f"{self.filename} : l'IA voit peut-être un raté. Jette un œil à la caméra"
                                 + ("." if cfg["pause_auto"] else " (pause automatique désactivée)."), photo=name)

    async def _alert_image(self, jpeg: bytes, dets: list) -> str:
        from . import vision
        img = await asyncio.to_thread(vision.annotate, jpeg, dets)
        photos = photos_dir()
        photos.mkdir(parents=True, exist_ok=True)
        name = time.strftime("%Y%m%d-%H%M%S") + "_ia.jpg"
        (photos / name).write_bytes(img)
        if self.rec is not None:
            self.rec.add_image(name, img)
            self.rec.meta["alertes"].append({"t": int(time.time()), "photo": name, "score": round(self.pred.ewm, 2)})
            self.rec.save()
        return name

    def _account(self, name: str, fraction: float, ref: str) -> None:
        """Take the filament of this print off the spools; warn when one runs low."""
        from pathlib import Path
        from . import stock
        if not name:
            return
        try:
            low = stock.consume(Path(name).name, fraction, ref)
        except Exception as e:  # stock is a bonus: never break the alerts for it
            log.warning("stock: %s", e)
            return
        for t in low:
            self.emit("stock", f"Bobine {t['tray'] + 1} ({t['nom'] or 'sans nom'}) : il reste environ {t['restant_g']:.0f} g. "
                               "Prévois une bobine de rechange.")

    async def _sync_canvas(self) -> None:
        from . import spools, stock
        try:
            raw = (await asyncio.wait_for(self.canvas(), timeout=15)).raw
        except Exception:
            return
        for tray in await asyncio.to_thread(stock.sync, spools.loaded(raw)):
            self.emit("bobine", f"Bobine {tray + 1} : comptée comme une bobine pleine. Corrige le poids dans l'onglet Imprimante si besoin.")

    async def _photo(self, ev: dict[str, Any]) -> None:
        try:
            jpeg = await asyncio.wait_for(self.snapshot(), timeout=15)
        except Exception:
            return  # no camera or it did not answer: the alert stands without a photo
        photos = photos_dir()
        photos.mkdir(parents=True, exist_ok=True)
        name = time.strftime("%Y%m%d-%H%M%S") + ".jpg"
        (photos / name).write_bytes(jpeg)
        for e in self.events:
            if e["id"] == ev["id"]:
                e["photo"] = name
        self._save()
        for q in list(self.subscribers):
            with contextlib.suppress(asyncio.QueueFull):
                q.put_nowait({**ev, "photo": name, "update": True})
        old = sorted(photos.glob("*.jpg"))[:-50]
        for p in old:
            p.unlink(missing_ok=True)

    async def run(self) -> None:
        while True:
            try:
                st = await asyncio.wait_for(self.status(), timeout=15)
                self.last_seen = time.time()
                if self.lost:
                    self.lost = False
                    self.emit("retrouvee")
                self.observe(st.print_status or 0, st.progress or 0, st.filename or "", st.raw.get("_cc2", {}))
                self.cool(st.temp_bed)
                if self.prev not in IDLE:
                    await self._camera(st.print_info.current_layer if st.print_info else None)
                if self.canvas and self.ticks % 12 == 0:   # about once a minute
                    await self._sync_canvas()
                self.ticks += 1
            except asyncio.CancelledError:
                raise
            except Exception:
                if not self.lost and self.prev not in (None, *IDLE) and time.time() - self.last_seen > LOST_AFTER_S:
                    self.lost = True
                    self.emit("perdue", (f"{self.filename} : " if self.filename else "") + "plus de nouvelles depuis 1 min. Vérifie le Wi-Fi et l'alimentation.")
            await asyncio.sleep(POLL_S)
