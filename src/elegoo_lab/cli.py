"""`cc2` — one command line for the printer, the dashboard and AI generation.

Printer commands (status, watch, files, print, light, canvas, upload, ...)
come straight from pycentauri's CLI, pre-filled from config.toml. Use
``--control`` to allow writes.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Annotated, Optional

import typer
from pycentauri.cli import app as printer_app

from . import comfy as comfy_mod
from . import colorize, colors, config, mesh, printprep, slicer

app = typer.Typer(help=__doc__, no_args_is_help=True, add_completion=False)


@app.callback()
def main(
    control: Annotated[bool, typer.Option("--control", help="Autoriser les commandes qui modifient l'imprimante.")] = False,
) -> None:
    cfg = config.load()
    p = cfg.printer
    if p.host:
        os.environ["PYCENTAURI_HOST"] = p.host
    if p.access_code:
        os.environ["PYCENTAURI_ACCESS_CODE"] = p.access_code
    if control:
        os.environ["PYCENTAURI_ENABLE_CONTROL"] = "1"


# Flatten pycentauri's commands into ours (host/code/control come from env set above).
app.registered_commands.extend(printer_app.registered_commands)


@app.command("dash")
def dash(
    ctx: typer.Context,
    bind: Annotated[str, typer.Option(help="Interface d'écoute (127.0.0.1 = local seulement).")] = "127.0.0.1",
    port: Annotated[Optional[int], typer.Option()] = None,
    reseau: Annotated[bool, typer.Option("--reseau", help="Ouvre l'atelier au réseau de la maison (téléphone), protégé par un code d'accès.")] = False,
    port_https: Annotated[int, typer.Option(help="Port HTTPS pour le téléphone (avec --reseau).")] = 8443,
    sans_https: Annotated[bool, typer.Option("--sans-https", help="Téléphone en HTTP simple (pas d'installation en appli).")] = False,
) -> None:
    """Lance le tableau de bord web (imprimante + atelier)."""
    import asyncio
    import uvicorn
    from .app import create_app
    control = bool(ctx.parent and ctx.parent.params.get("control"))
    port = port or config.load().dashboard_port
    lan = reseau or bind not in ("127.0.0.1", "localhost", "::1")
    https = lan and not sans_https
    if lan and bind == "127.0.0.1":
        bind = "0.0.0.0"   # with HTTPS, plain HTTP from the network only gives the certificate (then redirects)
    phone_port = port_https if https else port
    # stops here if the printer is not set up
    web = create_app(enable_control=control, lan=lan, port=phone_port, https=https, http_port=port)
    typer.echo(f"Tableau de bord: http://localhost:{port}/"
               f"  [contrôle {'activé' if control else 'lecture seule'}]")
    servers = [uvicorn.Config(web, host=bind, port=port, log_level="warning", timeout_graceful_shutdown=3)]
    if lan:
        from . import access
        import time
        ip = access.lan_ip()
        for _ in range(30):   # started with the PC: the network may come up a few seconds after us
            if ip != "127.0.0.1":
                break
            time.sleep(1)
            ip = access.lan_ip()
        code = access.ensure_code()
        ts = access.tailscale()   # the user's private network: the same workshop from anywhere, nothing opened to the Internet
        if https:
            from . import certs
            crt, key = certs.ensure([ip, *([ts["ip"]] if ts else [])], [ts["name"]] if ts and ts["name"] else None)
            # same app, second door: no second lifespan (one printer connection, one watcher)
            servers.append(uvicorn.Config(web, host="0.0.0.0", port=port_https, ssl_certfile=str(crt), ssl_keyfile=str(key),
                                          lifespan="off", log_level="warning", timeout_graceful_shutdown=3))
        typer.echo(f"Depuis le téléphone (même Wi-Fi): {'https' if https else 'http'}://{ip}:{phone_port}/lab/")
        if ts:
            typer.echo(f"Hors de chez toi (Tailscale): {'https' if https else 'http'}://{ts['name'] or ts['ip']}:{phone_port}/lab/")
        typer.echo(f"Code d'accès: {code}  (note-le, il ne sera plus affiché ; `cc2 code-acces` pour le changer)"
                   if code else "Code d'accès: celui déjà choisi (`cc2 code-acces` pour le changer)")

    async def serve() -> None:
        first = uvicorn.Server(servers[0])
        rest = [uvicorn.Server(c) for c in servers[1:]]
        task = asyncio.create_task(first.serve())
        while not first.started and not task.done():   # the second door opens once the printer side is up
            await asyncio.sleep(0.1)
        await asyncio.gather(task, *(s.serve() for s in rest))

    asyncio.run(serve())


@app.command("simulateur")
def simulateur(
    port: Annotated[int, typer.Option(help="Port du tableau de bord de démonstration.")] = 8788,
    duree: Annotated[float, typer.Option(help="Durée d'une impression simulée, en secondes.")] = 300.0,
) -> None:
    """Essaie l'atelier sans imprimante : une Centauri Carbon 2 simulée (caméra, CANVAS, impressions en accéléré),
    avec sa propre bibliothèque et ses réglages dans demo/ (ta vraie bibliothèque n'est pas touchée)."""
    import asyncio
    import logging
    import uvicorn
    from . import simulateur as sim
    demo = config.ROOT / "demo"
    (demo / "models").mkdir(parents=True, exist_ok=True)
    config.MODELS_DIR, config.CONFIG_FILE = demo / "models", demo / "config.toml"   # before the app module reads them
    os.environ.update(CC2_HOST=sim.SIM_HOST, CC2_ACCESS_CODE=sim.SIM_CODE, CC2_SERIAL=sim.SIM_SERIAL,
                      PYCENTAURI_ENABLE_CONTROL="1")
    sim.patch_pycentauri()
    from .app import create_app
    web = create_app(enable_control=True)
    logging.getLogger("fakeprinter").setLevel(logging.WARNING)
    typer.echo(f"Imprimante simulée prête · atelier de démonstration : http://localhost:{port}/lab/  (Ctrl+C pour arrêter)")

    async def serve() -> None:
        printer = asyncio.create_task(sim.Sim(print_seconds=duree).serve())
        await asyncio.sleep(0.3)   # the broker listens before the workshop connects
        try:
            await uvicorn.Server(uvicorn.Config(web, host="127.0.0.1", port=port, log_level="warning",
                                                timeout_graceful_shutdown=3)).serve()
        finally:
            printer.cancel()

    try:
        asyncio.run(serve())
    except KeyboardInterrupt:   # Ctrl+C: the normal way out of a demo
        typer.echo("Simulateur arrêté.")


@app.command("code-acces")
def code_acces(
    code: Annotated[Optional[str], typer.Argument(help="Nouveau code (4 à 12 chiffres) ; vide = en tirer un au hasard.")] = None,
) -> None:
    """Change le code d'accès depuis le téléphone (les téléphones déjà connectés devront le ressaisir)."""
    import secrets
    from . import access
    code = code or f"{secrets.randbelow(10**6):06d}"
    try:
        access.set_code(code)
    except ValueError as e:
        raise typer.BadParameter(str(e))
    typer.echo(f"Nouveau code d'accès: {code}")


service = typer.Typer(help="Démarrage automatique de l'atelier (au démarrage du PC, relancé en cas de plantage).",
                      no_args_is_help=True)
app.add_typer(service, name="service")
UNIT_DIR = Path.home() / ".config" / "systemd" / "user"
UNITS = ("cc2-atelier",)


def _systemctl(*args: str, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(["systemctl", "--user", *args], capture_output=True, text=True, check=check)


@service.command("installer")
def service_install(
    ctx: typer.Context,
    reseau: Annotated[bool, typer.Option("--reseau/--local", help="Ouvert au téléphone (défaut) ou à ce PC seulement.")] = True,
) -> None:
    """Installe et démarre l'atelier en service : il démarre avec le PC, sans session ouverte.

    Les options générales s'appliquent : `cc2 --control service installer`. Relancer la commande remplace l'ancien réglage.
    """
    import shutil
    top = ctx.find_root().params
    control = bool(top.get("control"))
    exe = Path(sys.executable).parent / "cc2"
    if not exe.exists():
        exe = Path(shutil.which("cc2") or exe)
    p = config.load().printer
    if not p.host or not p.access_code:
        raise typer.BadParameter("imprimante non configurée (config.toml, ou onglet Démarrage).")
    UNIT_DIR.mkdir(parents=True, exist_ok=True)
    common = (f"WorkingDirectory={config.ROOT}\nEnvironment=PYTHONUNBUFFERED=1\n"
              "Restart=always\nRestartSec=5\n")
    flags = "--control" if control else ""
    dep = "After=network-online.target\nWants=network-online.target\n"
    (UNIT_DIR / "cc2-atelier.service").write_text(
        f"[Unit]\nDescription=Atelier CC2 - tableau de bord\n{dep}\n"
        f"[Service]\nExecStart={exe} {flags + ' ' if flags else ''}dash{' --reseau' if reseau else ''}\n{common}"
        # SIGINT ends uvicorn with 130: a normal stop, not a failure
        "KillSignal=SIGINT\nSuccessExitStatus=130\nTimeoutStopSec=15\n\n[Install]\nWantedBy=default.target\n")
    _systemctl("daemon-reload")
    # an old simulator unit from a previous install is no longer wanted
    _systemctl("disable", "--now", "cc2-simulateur.service", check=False)
    (UNIT_DIR / "cc2-simulateur.service").unlink(missing_ok=True)
    _systemctl("daemon-reload")
    for u in UNITS:
        _systemctl("enable", f"{u}.service")
        _systemctl("restart", f"{u}.service")
    linger = subprocess.run(["loginctl", "enable-linger"], capture_output=True, text=True)
    typer.echo(f"Service installé : contrôle {'activé' if control else 'lecture seule'}"
               f", {'ouvert au téléphone' if reseau else 'ce PC seulement'}.")
    typer.echo("Il démarre avec le PC" + ("" if linger.returncode == 0 else
               " dès que tu ouvres ta session (pour démarrer sans session : `sudo loginctl enable-linger $USER`)")
               + " et se relance tout seul s'il s'arrête.")
    typer.echo("Suivi : `cc2 service etat` · journal : `cc2 service journal` · retirer : `cc2 service retirer`")


@service.command("etat")
def service_status() -> None:
    """Dit si l'atelier tourne en service."""
    for u in UNITS:
        if not (UNIT_DIR / f"{u}.service").exists():
            continue
        active = _systemctl("is-active", f"{u}.service", check=False).stdout.strip()
        enabled = _systemctl("is-enabled", f"{u}.service", check=False).stdout.strip()
        label = {"active": "en marche", "activating": "démarre", "failed": "en échec", "inactive": "arrêté"}.get(active, active)
        typer.echo(f"{u}: {label}{'' if enabled == 'enabled' else ' (démarrage auto désactivé)'}")
    if not any((UNIT_DIR / f"{u}.service").exists() for u in UNITS):
        typer.echo("Pas de service installé : `cc2 --control service installer`.")


@service.command("journal")
def service_logs(lignes: Annotated[int, typer.Option(help="Nombre de lignes.")] = 40) -> None:
    """Dernières lignes écrites par l'atelier (pour comprendre un souci)."""
    subprocess.run(["journalctl", "--user", "-u", "cc2-atelier", "-n", str(lignes), "--no-pager",
                    "-o", "short-iso"])


@service.command("retirer")
def service_remove() -> None:
    """Arrête l'atelier en service et supprime le démarrage automatique."""
    for u in ("cc2-simulateur", *UNITS):
        _systemctl("disable", "--now", f"{u}.service", check=False)
        (UNIT_DIR / f"{u}.service").unlink(missing_ok=True)
    _systemctl("daemon-reload")
    typer.echo("Démarrage automatique retiré. `cc2 dash` fonctionne toujours à la main.")


backup = typer.Typer(help="Sauvegarde de la bibliothèque, des réglages et de l'historique git sur un disque USB.",
                     no_args_is_help=True)
app.add_typer(backup, name="sauvegarde")


@backup.command("faire")
def backup_run(
    vers: Annotated[Optional[str], typer.Option(help="Dossier d'un disque branché, ou machine ssh ; vide = le disque USB branché.")] = None,
    si_besoin: Annotated[bool, typer.Option("--si-besoin", help="Seulement si la dernière date de plus de 20 h.")] = False,
) -> None:
    """Copie models/, config.toml et l'historique git dans le dossier atelier-cc2 du disque USB branché."""
    from . import sauvegarde
    try:
        typer.echo(sauvegarde.run(vers, if_needed=si_besoin))
    except RuntimeError as e:
        typer.echo(f"Sauvegarde impossible : {e}", err=True)
        raise typer.Exit(1) from None


@backup.command("installer")
def backup_install(
    vers: Annotated[Optional[str], typer.Option(help="Dossier d'un disque branché, ou machine ssh ; vide = le disque USB branché.")] = None,
) -> None:
    """Sauvegarde automatique : essai toutes les heures, une copie par jour, rattrapée dès que le disque est branché."""
    exe = Path(sys.executable).parent / "cc2"
    UNIT_DIR.mkdir(parents=True, exist_ok=True)
    (UNIT_DIR / "cc2-sauvegarde.service").write_text(
        f"[Unit]\nDescription=Atelier CC2 - sauvegarde vers {vers or 'le disque USB'}\n\n"
        f"[Service]\nType=oneshot\nWorkingDirectory={config.ROOT}\n"
        f"ExecStart={exe} sauvegarde faire{f' --vers {vers}' if vers else ''} --si-besoin\n"
        "SuccessExitStatus=1\n"   # an unplugged disk is not a failure of the service: the status file keeps the reason
        "Nice=10\nIOSchedulingClass=idle\n")
    (UNIT_DIR / "cc2-sauvegarde.timer").write_text(
        "[Unit]\nDescription=Atelier CC2 - sauvegarde toutes les heures si besoin\n\n"
        "[Timer]\nOnBootSec=10min\nOnUnitActiveSec=1h\nPersistent=true\n\n[Install]\nWantedBy=timers.target\n")
    _systemctl("daemon-reload")
    _systemctl("enable", "--now", "cc2-sauvegarde.timer")
    typer.echo(f"Sauvegarde automatique installée vers {vers or 'le disque USB branché (dossier atelier-cc2)'}. "
               "Suivi : `cc2 sauvegarde etat`.")


@backup.command("etat")
def backup_status() -> None:
    """Date de la dernière sauvegarde réussie et dernière erreur."""
    import time
    from . import sauvegarde
    s = sauvegarde.status()
    fmt = lambda t: time.strftime("%d/%m/%Y %H:%M", time.localtime(t))   # noqa: E731
    typer.echo(f"Dernière réussie : {fmt(s['ok']) + ' vers ' + s.get('vers', '?') if s.get('ok') else 'jamais'}")
    if s.get("erreur"):
        typer.echo(f"Dernier essai ({fmt(s['essai'])}) : {s['erreur']}")


models = typer.Typer(help="Bibliothèque de modèles 3D (dossier models/).", no_args_is_help=True)
app.add_typer(models, name="models")


@models.command("list")
def models_list() -> None:
    """Liste les modèles."""
    for p in sorted(config.MODELS_DIR.glob("*")):
        if p.is_file() and not p.name.startswith("."):
            typer.echo(f"{p.name:50} {p.stat().st_size / 1024:9.0f} Ko")


@models.command("info")
def models_info(file: Path) -> None:
    """Dimensions, étanchéité et compatibilité plateau (256 mm) d'un maillage."""
    typer.echo(json.dumps(mesh.info(_resolve(file)), indent=2, ensure_ascii=False))


@models.command("prepare")
def models_prepare(
    file: Path,
    height: Annotated[Optional[float], typer.Option(help="Hauteur finale en mm.")] = None,
    out: Annotated[Optional[Path], typer.Option(help="Sortie (.stl/.3mf).")] = None,
) -> None:
    """Convertit en STL imprimable: repose sur Z=0, centre, répare, met à l'échelle."""
    src = _resolve(file)
    dst = out or config.MODELS_DIR / f"{src.stem}_print.stl"
    typer.echo(json.dumps(mesh.prepare(src, dst, height_mm=height), indent=2, ensure_ascii=False))
    typer.echo(f"→ {dst}")


def _resolve(p: Path) -> Path:
    return p if p.exists() else config.MODELS_DIR / p


@app.command("slice")
def slice_cmd(
    file: Path,
    nozzle: Annotated[str, typer.Option(help="Diamètre de buse (mm).")] = slicer.DEFAULT_NOZZLE,
    quality: Annotated[str, typer.Option(help="Profil de qualité, voir `cc2 slice-profiles`.")] = slicer.DEFAULT_QUALITY,
    filament: Annotated[Optional[list[str]], typer.Option(help="Filament par bobine, dans l'ordre des bobines 1, 2… (répétable).")] = None,
    slot: Annotated[Optional[list[str]], typer.Option(help="Couleur→bobine, ex. --slot 3:1 (voir `cc2 colors`).")] = None,
    height: Annotated[Optional[float], typer.Option(help="Hauteur finale en mm.")] = None,
    infill: Annotated[Optional[int], typer.Option(help="Remplissage en %.")] = None,
    supports: Annotated[str, typer.Option(help="Supports : aucun, arbre, arbre_fin, arbre_solide, colonnes.")] = "aucun",
    plate_only: Annotated[bool, typer.Option("--plateau-seul", help="Supports seulement depuis le plateau.")] = False,
    mode: Annotated[str, typer.Option(help="Multicolore : economie (sans tour d'essuyage), sans_purge, equilibre, qualite.")] = printprep.DEFAULT_MODE,
    split: Annotated[bool, typer.Option("--decouper", help="Découper en pièces avec chevilles si trop grand.")] = False,
    upload: Annotated[bool, typer.Option(help="Envoyer le G-code à l'imprimante (exige --control).")] = False,
    start: Annotated[bool, typer.Option(help="Lancer l'impression après l'envoi (exige --upload).")] = False,
) -> None:
    """Tranche un modèle pour la Centauri Carbon 2. Les modèles déjà colorés (3MF peints, GLB, OBJ+MTL,
    PLY) sont convertis automatiquement pour le CANVAS (4 couleurs max, regroupées au-delà)."""
    src = _resolve(file)
    try:
        mapping = {}
        for item in slot or []:
            c, _, s = item.partition(":")
            mapping[int(c)] = int(s)
        if nozzle != slicer.DEFAULT_NOZZLE:  # non-default nozzle: plain single-colour slicing
            sup_on, sup_ov = printprep.support_overrides(supports, plate_only)
            res = slicer.slice_model(src, config.MODELS_DIR, nozzle=nozzle, quality=quality, filament=filament,
                                     infill=infill, supports=sup_on, overrides=sup_ov).as_dict()
            res["slots"] = []
        else:
            res = printprep.prepare_and_slice(src, mapping=mapping, filaments=filament, quality=quality,
                                              infill=infill, supports=supports, plate_only=plate_only,
                                              height_mm=height, mode=mode, split=split)
    except (ValueError, slicer.SliceError) as err:
        typer.secho(str(err), fg="red", err=True)
        raise typer.Exit(1) from err
    if res.get("split"):
        typer.echo("Découpe : " + ", ".join(f"{p['axis']} = {p['mm']} mm" for p in res["planes"]))
        for p in res["pieces"]:
            typer.echo(f"✔ {p['gcode'][0]}  ({' × '.join(str(x) for x in p['size_mm'])} mm, {p['time']}, {p['total_m']} m)")
        if res["pins"]:
            pn = res["pins"]
            typer.echo(f"✔ {pn['gcode'][0]}  ({pn['count']} chevilles Ø{pn['diameter_mm']:.0f} × {pn['length_mm']:.0f} mm)")
        typer.echo(f"  Total : {res['total_m']} m de filament")
        for w in res["warnings"]:
            typer.secho(f"  ⚠ {w}", fg="yellow")
        return
    for g in res["gcode"]:
        typer.echo(f"✔ {config.MODELS_DIR / g}")
    purge = sum(res.get("purge_m") or [])
    typer.echo(f"  {res['layers']} couches · durée estimée {res['time']} · filament {res.get('total_m', res['filament_m'])} m"
               + (f" (dont purge {purge:.1f} m)" if purge else ""))
    if len(res["slots"]) > 1:
        typer.echo(f"  {res['colour_changes']} changements de couleur")
        typer.echo("  Charger le CANVAS: " + " · ".join(f"{s['tool']} {s['filament']} ({s['colour']}, {s['metres']} m)" for s in res["slots"]))
    for w in res["warnings"]:
        typer.secho(f"  ⚠ {w}", fg="yellow")
    if upload or start:
        if not os.environ.get("PYCENTAURI_ENABLE_CONTROL"):
            typer.secho("--upload/--start modifient l'imprimante: ajoute --control (ex. cc2 --control slice ...).", fg="red", err=True)
            raise typer.Exit(2)
        _send(config.MODELS_DIR / res["gcode"][0], start)


@app.command("colors")
def colors_cmd(file: Path) -> None:
    """Couleurs détectées dans un modèle et bobine CANVAS proposée pour chacune."""
    a = colors.analyze(_resolve(file))
    if a["detected"] > len(a["colours"]):
        typer.echo(f"{a['detected']} teintes regroupées en {len(a['colours'])} couleurs")
    for c in a["colours"]:
        typer.echo(f"  couleur {c['index']}: {c['hex']}  {c['share']:5.1f} %  → bobine {c['slot']}")
    typer.echo("Changer une affectation: cc2 slice FICHIER --slot COULEUR:BOBINE (bobine 1 à 4)")


def _send(path: Path, start: bool) -> None:
    import asyncio

    from pycentauri.connect import connect_auto

    async def go() -> None:
        p = await connect_auto(os.environ["PYCENTAURI_HOST"], enable_control=True,
                               access_code=os.environ.get("PYCENTAURI_ACCESS_CODE"))
        try:
            name = await p.upload_file(path)
            typer.echo(f"✔ envoyé: {name}")
            if start:
                await p.start_print(name)
                typer.echo("✔ impression lancée")
        finally:
            await p.close()

    asyncio.run(go())


@app.command("multicolor")
def multicolor(
    parts: Annotated[list[str], typer.Argument(help="Pièces au format fichier:emplacement, ex. base.stl:1 dessus.stl:2")],
    name: Annotated[str, typer.Option(help="Nom du modèle.")] = "multicolore",
    filament: Annotated[Optional[list[str]], typer.Option(help="Filament par emplacement, dans l'ordre (répétable).")] = None,
    quality: Annotated[str, typer.Option()] = slicer.DEFAULT_QUALITY,
    infill: Annotated[Optional[int], typer.Option()] = None,
    upload: Annotated[bool, typer.Option(help="Envoyer à l'imprimante (exige --control).")] = False,
    start: Annotated[bool, typer.Option(help="Lancer l'impression (exige --upload).")] = False,
) -> None:
    """Assemble des pièces (une par couleur/bobine CANVAS) en un 3MF multicolore et le tranche.

    Les pièces gardent leurs positions relatives (modélise-les dans le même repère) ;
    l'ensemble est posé sur le plateau. Emplacement 1..4 = bobines 1..4 du CANVAS.
    """
    try:
        spec = []
        for item in parts:
            f, _, slot = item.rpartition(":")
            if not f or not slot.isdigit():
                raise ValueError(f"'{item}': format attendu fichier:emplacement (ex. base.stl:1)")
            spec.append((_resolve(Path(f)), int(slot)))
        names = filament or ["PLA"] * max(s for _, s in spec)
        out = config.MODELS_DIR / f"{name}.3mf"
        info = colorize.build_3mf(spec, out, filaments=len(names), name=name)
        typer.echo(f"✔ {out.name}: {len(spec)} pièces, {info['filaments']} filaments, {info['size_mm']} mm")
        res = slicer.slice_model(out, config.MODELS_DIR, quality=quality, filament=names, infill=infill)
    except (ValueError, slicer.SliceError) as err:
        typer.secho(str(err), fg="red", err=True)
        raise typer.Exit(1) from err
    for g in res.gcode:
        typer.echo(f"✔ {g}")
    typer.echo(f"  {res.layers} couches · durée estimée {res.time} · filament {res.filament_m} m (tous filaments)")
    typer.echo("  Chargement CANVAS attendu: " + ", ".join(f"bobine {i + 1} = {n}" for i, n in enumerate(names)))
    if upload or start:
        if not os.environ.get("PYCENTAURI_ENABLE_CONTROL"):
            typer.secho("--upload/--start modifient l'imprimante: ajoute --control.", fg="red", err=True)
            raise typer.Exit(2)
        _send(res.gcode[0], start)


@app.command("slice-profiles")
def slice_profiles(nozzle: str = slicer.DEFAULT_NOZZLE) -> None:
    """Liste buses, qualités et filaments disponibles."""
    try:
        typer.echo(f"Buses: {', '.join(slicer.nozzles())}")
        typer.echo(f"Qualités ({nozzle} mm): {', '.join(slicer.qualities(nozzle))}")
        typer.echo(f"Filaments: {', '.join(slicer.filaments())}")
    except slicer.SliceError as err:
        typer.secho(str(err), fg="red", err=True)
        raise typer.Exit(1) from err


@app.command("gen")
def gen(
    workflow: str,
    image: Annotated[Optional[Path], typer.Option(help="Image source (image→3D).")] = None,
    prompt: Annotated[Optional[str], typer.Option(help="Texte (texte→3D).")] = None,
    seed: Annotated[Optional[int], typer.Option()] = None,
) -> None:
    """Génère un modèle 3D via un workflow ComfyUI (workflows/<nom>.json)."""
    cfg = config.load()
    try:
        files = comfy_mod.generate(comfy_mod.Comfy(cfg.comfyui_url), workflow, config.MODELS_DIR,
                                   image=image, prompt=prompt, seed=seed)
    except comfy_mod.ComfyError as err:
        typer.secho(str(err), fg="red", err=True)
        raise typer.Exit(1) from err
    for f in files:
        typer.echo(f"✔ {f}")
    typer.echo("Étape suivante : cc2 slice <fichier.glb> (taille 60 mm par défaut pour un modèle IA, --height pour changer), "
               "ou l'onglet Atelier.")


@app.command("doctor")
def doctor() -> None:
    """Vérifie la configuration, l'imprimante et ComfyUI."""
    import socket

    cfg = config.load()
    ok = lambda b: typer.style("OK ", fg="green") if b else typer.style("KO ", fg="red")  # noqa: E731
    typer.echo(f"{ok(config.CONFIG_FILE.exists())}config.toml ({config.CONFIG_FILE})")
    if cfg.printer.host:
        try:
            socket.create_connection((cfg.printer.host, 1883), 3).close()
            up = True
        except OSError:
            up = False
        typer.echo(f"{ok(up)}imprimante {cfg.printer.host}:1883 (MQTT) — code d'accès {'défini' if cfg.printer.access_code else 'MANQUANT'}")
        if not up:
            typer.echo("    → imprimante allumée ? même réseau ? mode « LAN Only » activé sur l'écran ?")
    else:
        typer.echo(f"{ok(False)}imprimante non configurée (host vide dans config.toml)")
    try:
        s = comfy_mod.Comfy(cfg.comfyui_url, timeout=3).stats()
        typer.echo(f"{ok(True)}ComfyUI {cfg.comfyui_url} — {[d.get('name') for d in s.get('devices', [])]}")
    except comfy_mod.ComfyError as err:
        typer.echo(f"{ok(False)}{err}")


if __name__ == "__main__":
    app()
