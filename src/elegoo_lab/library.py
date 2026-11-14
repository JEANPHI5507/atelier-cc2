"""The library: what each file is, where a G-code comes from, thumbnails, renaming, clean-up.

Slicing records each G-code's facts (source model, usage, quality, time, grams, cost, colours) in
models/.index.json; G-codes made elsewhere are read from OrcaSlicer's own header. Files the workshop
makes along the way (colour conversions, cut pieces, dowel plates) are "technical": hidden unless asked.
"""

from __future__ import annotations

import base64
import hashlib
import json
import re
import threading
import time
from pathlib import Path
from typing import Any

from . import config

MESH_EXT = {".stl", ".3mf", ".obj", ".glb", ".gltf", ".ply"}
ALL_EXT = MESH_EXT | {".gcode"}
TECHNICAL = re.compile(r"(?<!^calibration)(_canvas\.3mf|_partie\d+\.3mf|_chevilles\.stl|_petites_pieces\.3mf|_scaled\.stl)$", re.I)
NAME_OK = re.compile(r"^[^/\\\x00-\x1f<>:\"|?*]{1,120}$")
_lock = threading.Lock()
GCODE_KEEP_DAYS = 30   # a printed G-code goes this long after its last print: its model stays, slicing again takes seconds
_meta_cache: dict[tuple, dict[str, Any]] = {}


def _index_file() -> Path:
    return config.MODELS_DIR / ".index.json"


def _thumbs() -> Path:
    return config.MODELS_DIR / ".thumbs"


def load_index() -> dict[str, dict[str, Any]]:
    try:
        return json.loads(_index_file().read_text())
    except (OSError, ValueError):
        return {}


def _save_index(idx: dict[str, Any]) -> None:
    config.write_atomic(_index_file(), json.dumps(idx, ensure_ascii=False, indent=1))


def record(gcode: str, **facts: Any) -> None:
    """Called after slicing: what this G-code is and where it comes from."""
    with _lock:
        idx = load_index()
        idx[Path(gcode).name] = {**idx.get(Path(gcode).name, {}), **facts, "cree": int(time.time())}
        _save_index(idx)


def annotate(name: str, **facts: Any) -> None:
    """Add facts to a library file (a model's review after printing) without touching the rest."""
    with _lock:
        idx = load_index()
        idx[Path(name).name] = {**idx.get(Path(name).name, {}), **facts}
        _save_index(idx)


def kind(name: str) -> str:
    ext = Path(name).suffix.lower()
    if ext == ".gcode":
        return "gcode"
    return "technique" if TECHNICAL.search(name) or name.startswith(".") else "modele"


def _header_meta(path: Path) -> dict[str, Any]:
    """Facts OrcaSlicer writes in every G-code (for files the workshop did not slice itself)."""
    st = path.stat()
    key = (path.name, st.st_mtime_ns, st.st_size)
    if key in _meta_cache:
        return _meta_cache[key]
    with path.open("rb") as f:
        head = f.read(60_000)
        f.seek(max(0, st.st_size - 120_000))
        tail = f.read()
    text = (head + b"\n" + tail).decode("utf-8", "ignore")

    def one(k: str) -> str | None:
        m = re.search(rf"^; {re.escape(k)} = (.*)$", text, re.M)
        return m.group(1).strip() if m else None
    cols = [c for c in re.split(r"[;,]", one("filament_colour") or "") if re.fullmatch(r"#[0-9A-Fa-f]{6}", c.strip())]
    used = [float(x) for x in re.findall(r"[\d.]+", one("filament used [mm]") or "")]
    if used and len(used) == len(cols):
        cols = [c for c, u in zip(cols, used) if u > 0]
    g = one("total filament used [g]")
    meta = {"temps": one("estimated printing time (normal mode)"), "couches": one("total layer number"),
            "g": float(g) if g and re.fullmatch(r"[\d.]+", g) else None,
            "couleurs": [c.upper() for c in cols][:8], "qualite": re.sub(r"^cc2lab ", "", (one("print_settings_id") or "").split(" @")[0]) or None,
            "vignette": "; thumbnail begin" in text}
    _meta_cache[key] = meta
    while len(_meta_cache) > 500:
        _meta_cache.pop(next(iter(_meta_cache)))
    return meta


def _guess_source(gcode: str, models: list[str]) -> str | None:
    stem = Path(gcode).stem
    cands = [m for m in models if stem.startswith(Path(m).stem + "_") or stem == Path(m).stem]
    return max(cands, key=lambda m: len(Path(m).stem)) if cands else None


def listing() -> list[dict[str, Any]]:
    """Every file with what the library shows about it."""
    config.MODELS_DIR.mkdir(exist_ok=True)
    files = [p for p in config.MODELS_DIR.iterdir() if p.is_file() and p.suffix.lower() in ALL_EXT]
    idx = load_index()
    models = [p.name for p in files if kind(p.name) == "modele"]
    out = []
    for p in sorted(files, key=lambda p: -p.stat().st_mtime):
        st = p.stat()
        e: dict[str, Any] = {"name": p.name, "size": st.st_size, "mtime": st.st_mtime, "ext": p.suffix.lower()[1:],
                             "kind": kind(p.name)}
        if e["kind"] == "gcode":
            rec = idx.get(p.name, {})
            e.update({**_header_meta(p), **{k: v for k, v in rec.items() if v is not None}})
            src = rec.get("source") or _guess_source(p.name, models)
            e["source"] = src if src in models else None
        out.append(e)
    counts: dict[str, int] = {}
    for e in out:
        if e["kind"] == "gcode" and e.get("source"):
            counts[e["source"]] = counts.get(e["source"], 0) + 1
    for e in out:
        if e["kind"] == "modele":
            e["prets"] = counts.get(e["name"], 0)
    return out


def thumbnail(name: str) -> bytes | None:
    """PNG: the one embedded in a G-code, or a render of a model (cached)."""
    p = config.MODELS_DIR / Path(name).name
    if not p.is_file():
        return None
    if p.suffix.lower() == ".gcode":
        with p.open("rb") as f:
            head = f.read(400_000).decode("ascii", "ignore")
        m = re.search(r"; thumbnail begin \d+x\d+ \d+\n(.*?)\n; thumbnail end", head, re.S)
        if not m:            # older or foreign G-code: show the model it was made from
            models = [q.name for q in config.MODELS_DIR.iterdir() if q.is_file() and kind(q.name) == "modele"]
            src = load_index().get(p.name, {}).get("source") or _guess_source(p.name, models)
            return thumbnail(src) if src and (config.MODELS_DIR / src).is_file() else None
        try:
            return base64.b64decode("".join(line.lstrip("; ").strip() for line in m.group(1).splitlines()))
        except ValueError:
            return None
    st = p.stat()
    cache = _thumbs() / (hashlib.sha1(f"{p.name}:{st.st_mtime_ns}:{st.st_size}".encode()).hexdigest()[:20] + ".png")
    if cache.exists():
        return cache.read_bytes()
    import numpy as np
    from . import colors, thumbnail as th
    v, f, slots, slot_hex = colors.solid(p, {})
    rgb = np.array([colors._rgb(slot_hex[int(s) - 1]) for s in slots]) if slot_hex else np.full((len(f), 3), 190.0)
    png = th.render(v, f, rgb, size=144)
    _thumbs().mkdir(exist_ok=True)
    cache.write_bytes(png)
    return png


SIDECARS = (".retouches", ".repairs", ".marques")    # small files kept beside a model, named after it


def rename(old: str, new: str) -> str:
    """Rename a file (extension kept); G-codes made from a renamed model keep pointing at it."""
    src = config.MODELS_DIR / Path(old).name
    if not src.is_file():
        raise FileNotFoundError(old)
    new = new.strip()
    if Path(new).suffix.lower() != src.suffix.lower():
        new += src.suffix
    if not NAME_OK.match(new) or new.startswith("."):
        raise ValueError("nom invalide (pas de / \\ : * ? \" < > |, 120 caractères au plus)")
    dest = config.MODELS_DIR / new
    if dest.exists():
        raise ValueError(f"« {new} » existe déjà")
    with _lock:
        idx = load_index()
        # links guessed from names would break once a name changes: write them down first
        files = [q.name for q in config.MODELS_DIR.iterdir() if q.is_file()]
        models = [n for n in files if kind(n) == "modele"]
        for n in files:
            if kind(n) == "gcode" and not idx.get(n, {}).get("source"):
                guess = _guess_source(n, models)
                if guess:
                    idx.setdefault(n, {})["source"] = guess
        src.rename(dest)
        for folder in SIDECARS:                                   # hand retouching / repair report follow their model
            side = src.parent / folder / (src.name + ".json")
            if side.is_file():
                side.rename(side.with_name(dest.name + ".json"))
        if old in idx:
            idx[new] = idx.pop(old)
        for rec in idx.values():
            if rec.get("source") == old:
                rec["source"] = new
        if src.suffix.lower() == ".gcode":       # keep spool usage known under the new name
            from . import stock
            data = stock.load()
            if old in data["prints"]:
                data["prints"][new] = data["prints"].pop(old)
                stock.save(data)
        _save_index(idx)
    return new


def delete(names: list[str]) -> list[str]:
    done = []
    with _lock:
        idx = load_index()
        for n in names:
            p = config.MODELS_DIR / Path(n).name
            if p.is_file() and p.suffix.lower() in ALL_EXT:
                p.unlink()
                for folder in SIDECARS:
                    (p.parent / folder / (p.name + ".json")).unlink(missing_ok=True)
                idx.pop(p.name, None)
                done.append(p.name)
        _save_index(idx)
    return done


def cleanup() -> list[dict[str, Any]]:
    """What could go: technical files, and G-codes whose model was deleted."""
    out = []
    for e in listing():
        if e["kind"] == "technique":
            out.append({"name": e["name"], "size": e["size"], "raison": "fichier technique (conversion couleur, pièce découpée)"})
        elif e["kind"] == "gcode" and not e.get("source"):
            idx = load_index().get(e["name"], {})
            if idx.get("source"):          # we sliced it, and its model is gone
                out.append({"name": e["name"], "size": e["size"], "raison": "son modèle a été supprimé"})
    return out


def old_gcodes(keep: set[str] | frozenset[str] = frozenset(), days: int = GCODE_KEEP_DAYS) -> list[str]:
    """G-codes printed (gallery) more than ``days`` ago and not sliced again since, whose model is still in the
    library. Never one in ``keep`` (the queue, the print in progress), never one that was not printed yet, never
    one without its model (made elsewhere, or model deleted): there it is the only copy."""
    from . import gallery
    limit = time.time() - days * 86400
    last: dict[str, float] = {}
    for e in gallery.entries():
        f = e.get("fichier")
        if f:
            last[f] = max(last.get(f, 0), float("inf") if e.get("issue") == "en cours" else e.get("debut", 0))
    return [e["name"] for e in listing()
            if e["kind"] == "gcode" and e["name"] not in keep and e.get("source")
            and e["name"] in last and last[e["name"]] < limit and e["mtime"] < limit]

