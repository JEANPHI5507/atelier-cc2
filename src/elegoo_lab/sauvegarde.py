"""Nightly copy of what exists nowhere else: the library (models/: models, gallery, photos, spool stock, history,
maintenance log, own spool profiles), config.toml and the whole git history, to another machine over ssh.

Files changed or deleted since the last copy are not lost there: rsync moves their old version to
``anciens/<date>/``, kept 60 days. Run hourly by a systemd timer with ``--si-besoin``: it copies once a day, and catches up as
soon as the other machine answers again. The result is kept in models/.sauvegarde.json; the workshop warns
when the last good copy is too old.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any

from . import config

DEST = "sauvegardes/atelier-cc2"   # on the other machine, from its home folder
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
    why = f" Dernière erreur : {s['erreur']}" if s.get("erreur") else ""
    if not last:
        return "Aucune sauvegarde de la bibliothèque n'a encore réussi." + why
    return f"Dernière sauvegarde réussie il y a {int((time.time() - last) // 86400)} jours." + why


def run(host: str, *, if_needed: bool = False) -> str:
    """Copy everything to ``host`` (an ssh name from ~/.ssh/config). Returns what was done; raises on failure."""
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
        sh([*ssh, host, f"mkdir -p {DEST}/models {DEST}/anciens"])
        rsync = ["rsync", "-a", "-e", " ".join(ssh), "--delete", "--backup", "--exclude", "*.tmp"]
        sh([*rsync, f"--backup-dir=../anciens/{stamp}/models", f"{config.MODELS_DIR}/", f"{host}:{DEST}/models/"])
        if config.CONFIG_FILE.exists():   # printer access code and access-code hash: the folder stays private
            sh([*rsync, f"--backup-dir=anciens/{stamp}", str(config.CONFIG_FILE), f"{host}:{DEST}/config.toml"])
        if (config.ROOT / ".git").exists() and shutil.which("git"):
            with tempfile.TemporaryDirectory() as tmp:
                bundle = Path(tmp) / "elegoo.bundle"   # the whole history in one file: `git clone elegoo.bundle`
                sh(["git", "-C", str(config.ROOT), "bundle", "create", str(bundle), "--all"])
                sh([*rsync, f"--backup-dir=anciens/{stamp}", str(bundle), f"{host}:{DEST}/elegoo.bundle"])
        sh([*ssh, host, f"chmod 700 {DEST} && find {DEST}/anciens -mindepth 1 -maxdepth 1 -mtime +{KEEP_DAYS} -exec rm -rf {{}} +"])
    except (OSError, RuntimeError, subprocess.SubprocessError) as e:
        _record(erreur=str(e)[:300])
        raise RuntimeError(str(e)) from None
    _record(ok=int(time.time()), vers=host, erreur="")
    return f"sauvegarde faite vers {host}:{DEST}"
