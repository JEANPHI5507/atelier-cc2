"""Daily copy of what exists nowhere else: the library (models/: models, gallery, photos, spool stock, history,
maintenance log, own spool profiles), config.toml and the whole git history, to a USB disk (``atelier-cc2/`` on
it) or to another machine over ssh.

Files changed or deleted since the last copy are not lost there: rsync moves their old version to
``anciens/<date>/``, kept 60 days. Run hourly by a systemd timer with ``--si-besoin``: it copies once a day, and catches up as
soon as the disk is plugged in again. The result is kept in models/.sauvegarde.json; the workshop warns
when the last good copy is too old.
"""

from __future__ import annotations

import contextlib
import json
import os
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any

from . import config

DEST = "sauvegardes/atelier-cc2"   # on another machine over ssh, from its home folder
LOCAL_DIR = "atelier-cc2"          # on a USB disk
EVERY_S = 20 * 3600                # --si-besoin: one copy a day is enough
WARN_AFTER_S = 3 * 86400           # no good copy for this long: the workshop says so
KEEP_DAYS = 60                     # old versions in anciens/ are dropped after this


def _file() -> Path:
    return config.MODELS_DIR / ".sauvegarde.json"


def status() -> dict[str, Any]:
    try:
        return json.loads(_file().read_text())
    except (OSError, ValueError):
        return {}


def _record(**values: Any) -> None:
    config.write_atomic(_file(), json.dumps({**status(), **values}, ensure_ascii=False))


def overdue() -> str | None:
    """A sentence for the alert when the last good copy is too old (or none was ever made), else None."""
    s = status()
    last = s.get("ok")
    if last and time.time() - last < WARN_AFTER_S:
        return None
    why = f" Dernier essai : {s['erreur']}." if s.get("erreur") else ""
    if not last:
        return "Aucune sauvegarde de la bibliothèque n'a encore réussi." + why
    return f"Dernière sauvegarde réussie il y a {int((time.time() - last) // 86400)} jours." + why


def _same_disk(a: Path, b: Path) -> bool:
    return a.stat().st_dev == b.stat().st_dev


def usb_disk() -> Path | None:
    """The plugged backup disk: a disk mounted under /media/<user> (or /run/media/<user>), not the system disk.
    One already holding an ``atelier-cc2`` folder wins; otherwise the only plugged disk becomes the backup disk."""
    import getpass
    user = getpass.getuser()
    disks = []
    for root in (Path("/media") / user, Path("/run/media") / user):
        with contextlib.suppress(OSError):
            disks += [d for d in sorted(root.iterdir()) if d.is_dir() and os.path.ismount(d) and not _same_disk(d, config.MODELS_DIR)]
    marked = [d for d in disks if (d / LOCAL_DIR).is_dir()]
    if marked:
        return marked[0]
    return disks[0] if len(disks) == 1 else None   # several unknown disks: don't guess which one to fill


def run(dest: str | None = None, *, if_needed: bool = False) -> str:
    """Copy everything to ``dest``: an ssh name from ~/.ssh/config, a folder on a plugged disk, or (None) the
    plugged USB disk found by ``usb_disk``. Returns what was done; raises on failure."""
    if if_needed and time.time() - status().get("ok", 0) < EVERY_S:
        return "sauvegarde du jour déjà faite"
    ssh = ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10"]
    stamp = time.strftime("%Y-%m-%d_%H%M")

    def sh(cmd: list[str], **kw: Any) -> None:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=3600, **kw)
        if r.returncode:
            raise RuntimeError((r.stderr or r.stdout).strip().splitlines()[-1] if (r.stderr or r.stdout).strip()
                               else f"{cmd[0]} a échoué ({r.returncode})")

    _record(essai=int(time.time()))
    try:
        local = dest is None or dest.startswith("/")
        if local:
            disk = Path(dest) if dest else usb_disk()
            # never write to the PC's own disk when the USB disk is not plugged (its mount folder may still exist)
            if disk is None or not disk.is_dir() or _same_disk(disk, config.MODELS_DIR):
                raise RuntimeError("disque de sauvegarde non branché")
            base = disk / LOCAL_DIR
            (base / "models").mkdir(parents=True, exist_ok=True)
            (base / "anciens").mkdir(exist_ok=True)
            # -rt and a 2 s window: USB disks are often FAT/exFAT (no owners, no permissions, 2 s clock)
            rsync, where, shown = ["rsync", "-rt", "--modify-window=2"], str(base), str(base)
        else:
            sh([*ssh, dest, f"mkdir -p {DEST}/models {DEST}/anciens"])
            rsync, where, shown = ["rsync", "-a", "-e", " ".join(ssh)], f"{dest}:{DEST}", f"{dest}:{DEST}"
        rsync += ["--delete", "--backup", "--exclude", "*.tmp"]
        sh([*rsync, f"--backup-dir=../anciens/{stamp}/models", f"{config.MODELS_DIR}/", f"{where}/models/"])
        if config.CONFIG_FILE.exists():   # printer access code and access-code hash: keep the disk at home
            sh([*rsync, f"--backup-dir=anciens/{stamp}", str(config.CONFIG_FILE), f"{where}/config.toml"])
        if (config.ROOT / ".git").exists() and shutil.which("git"):
            with tempfile.TemporaryDirectory() as tmp:
                bundle = Path(tmp) / "elegoo.bundle"   # the whole history in one file: `git clone elegoo.bundle`
                sh(["git", "-C", str(config.ROOT), "bundle", "create", str(bundle), "--all"])
                sh([*rsync, f"--backup-dir=anciens/{stamp}", str(bundle), f"{where}/elegoo.bundle"])
        if local:
            old = time.time() - KEEP_DAYS * 86400
            for d in (base / "anciens").iterdir():
                if d.is_dir() and d.stat().st_mtime < old:
                    shutil.rmtree(d, ignore_errors=True)
        else:
            sh([*ssh, dest, f"chmod 700 {DEST} && find {DEST}/anciens -mindepth 1 -maxdepth 1 -mtime +{KEEP_DAYS} -exec rm -rf {{}} +"])
    except (OSError, RuntimeError, subprocess.SubprocessError) as e:
        _record(erreur=str(e)[:300])
        raise RuntimeError(str(e)) from None
    _record(ok=int(time.time()), vers=shown, erreur="")
    return f"sauvegarde faite vers {shown}"
