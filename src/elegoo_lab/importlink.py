"""Add a model to the library from a web link: a direct file, a page that links to one, or a zip of models.

The dashboard fetches the link itself, so it only goes to public https addresses (never the house network:
the printer, the router or the PC itself), follows at most 5 redirects re-checking each host, and stops at
MAX_BYTES. Sites that hand files out only to a logged-in browser (MakerWorld, Thingiverse's API) get a clear
message instead: download the file, then drop it in the library.
"""

from __future__ import annotations

import io
import ipaddress
import re
import socket
import zipfile
from pathlib import Path
from urllib.parse import unquote, urljoin, urlsplit

MAX_BYTES = 300 * 1024 * 1024
MODEL_EXT = (".stl", ".3mf", ".obj", ".glb", ".gltf", ".ply", ".gcode")
_LINK = re.compile(r"""href=["']([^"'#]+?\.(?:stl|3mf|obj|glb|ply|zip)(?:\?[^"']*)?)["']""", re.I)


class LinkError(ValueError):
    pass


def _check_host(url: str) -> None:
    u = urlsplit(url)
    if u.scheme != "https" or not u.hostname:
        raise LinkError("Seuls les liens https:// sont acceptés.")
    try:
        addrs = {a[4][0] for a in socket.getaddrinfo(u.hostname, u.port or 443, proto=socket.IPPROTO_TCP)}
    except OSError:
        raise LinkError(f"Adresse introuvable : {u.hostname}") from None
    for a in addrs:
        ip = ipaddress.ip_address(a.split("%")[0])
        if not ip.is_global:
            raise LinkError("Ce lien pointe vers le réseau local : refusé.")


def _name(url: str, disposition: str | None) -> str:
    m = re.search(r"""filename\*?=(?:UTF-8'')?["']?([^"';]+)""", disposition or "", re.I)
    raw = unquote(m.group(1)) if m else unquote(Path(urlsplit(url).path).name)
    return Path(raw).name.strip() or "modele"


async def _get(client, url: str) -> tuple[str, bytes, str, str | None]:
    """(final url, body, content type, content disposition), with every redirect host checked."""
    for _ in range(6):
        _check_host(url)
        async with client.stream("GET", url) as r:
            if r.is_redirect:
                url = urljoin(url, r.headers["location"])
                continue
            if r.status_code >= 400:
                raise LinkError(f"Le site répond {r.status_code}"
                                + (" : il faut sans doute être connecté. Télécharge le fichier puis dépose-le." if r.status_code in (401, 403) else "."))
            if int(r.headers.get("content-length") or 0) > MAX_BYTES:
                raise LinkError("Fichier trop gros (plus de 300 Mo).")
            buf = bytearray()
            async for chunk in r.aiter_bytes():
                buf += chunk
                if len(buf) > MAX_BYTES:
                    raise LinkError("Fichier trop gros (plus de 300 Mo).")
            return url, bytes(buf), r.headers.get("content-type", ""), r.headers.get("content-disposition")
    raise LinkError("Trop de redirections.")


def _from_zip(data: bytes) -> list[tuple[str, bytes]]:
    out = []
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        for info in z.infolist():
            name = Path(info.filename).name
            if not info.is_dir() and name.lower().endswith(MODEL_EXT) and not name.startswith("."):
                if info.file_size > MAX_BYTES:
                    raise LinkError(f"{name} : trop gros.")
                out.append((name, z.read(info)))
    if not out:
        raise LinkError("L'archive ne contient aucun modèle (STL, 3MF, OBJ…).")
    return out


async def fetch(url: str) -> list[tuple[str, bytes]]:
    """The model files behind ``url``: [(file name, content)]."""
    import httpx
    url = url.strip()
    async with httpx.AsyncClient(timeout=60, follow_redirects=False, headers={"User-Agent": "Atelier-CC2"}) as c:
        final, data, ctype, disp = await _get(c, url)
        name = _name(final, disp)
        if "html" in ctype or data[:15].lstrip().lower().startswith((b"<!doctype", b"<html")):
            links = _LINK.findall(data.decode("utf-8", "ignore"))
            if not links:
                raise LinkError("Cette page ne donne pas le fichier directement (le site demande souvent d'être connecté). "
                                "Télécharge le modèle puis dépose-le dans la bibliothèque.")
            final, data, ctype, disp = await _get(c, urljoin(final, links[0]))
            name = _name(final, disp)
    if name.lower().endswith(".zip") or data[:4] == b"PK\x03\x04" and not name.lower().endswith(".3mf"):
        return _from_zip(data)
    if not name.lower().endswith(MODEL_EXT):
        raise LinkError("Ce lien ne mène pas à un modèle (STL, 3MF, OBJ, GLB, PLY ou G-code).")
    return [(name, data)]
