"""Client for a (remote) ComfyUI server: run API-format workflows, fetch 3D outputs.

Workflows live in ``workflows/<name>.json`` (exported with ComfyUI's
"Save (API Format)") next to ``workflows/<name>.map.json`` which says which
node inputs to fill::

    {"image": ["12", "image"], "prompt": ["7", "text"], "seed": ["3", "seed"]}

Anything in the workflow can also be overridden via ``overrides``
({"node_id.input": value}).
"""

from __future__ import annotations

import json
import random
import time
from pathlib import Path
from typing import Any, Callable

import httpx

from .config import ROOT

WORKFLOWS = ROOT / "workflows"
MESH_EXT = {".glb", ".gltf", ".obj", ".stl", ".ply", ".3mf"}
IMAGE_EXT = {".png", ".jpg", ".jpeg", ".webp"}  # final images (e.g. the figurine before 3D) go to references/


class ComfyError(RuntimeError):
    pass


class Comfy:
    def __init__(self, url: str, timeout: float = 30.0) -> None:
        self.url = url.rstrip("/")
        self.http = httpx.Client(base_url=self.url, timeout=timeout)

    def stats(self) -> dict[str, Any]:
        try:
            r = self.http.get("/system_stats")
            r.raise_for_status()
            return r.json()
        except httpx.HTTPError as err:
            raise ComfyError(f"ComfyUI injoignable sur {self.url}: {err}") from err

    def known(self, pid: str) -> bool:
        """Is this prompt still queued, running or in the history?"""
        try:
            q = self.http.get("/queue").json()
            if any(item[1] == pid for key in ("queue_running", "queue_pending") for item in q.get(key, [])):
                return True
            return bool(self.http.get(f"/history/{pid}").json().get(pid))
        except (httpx.HTTPError, ValueError, IndexError):
            return False

    def free(self) -> None:
        """Unload models and free VRAM (ComfyUI keeps them loaded between prompts)."""
        try:
            self.http.post("/free", json={"unload_models": True, "free_memory": True})
        except httpx.HTTPError:
            pass

    def upload_image(self, path: Path) -> str:
        with path.open("rb") as f:
            r = self.http.post("/upload/image", files={"image": (path.name, f)}, data={"overwrite": "true"})
        r.raise_for_status()
        return r.json()["name"]

    def queue(self, workflow: dict[str, Any]) -> str:
        r = self.http.post("/prompt", json={"prompt": workflow})
        if r.status_code != 200:
            raise ComfyError(f"workflow refusé ({r.status_code}): {r.text[:500]}")
        return r.json()["prompt_id"]

    def wait(self, prompt_id: str, poll: float = 2.0, timeout: float = 1800.0) -> dict[str, Any]:
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            r = self.http.get(f"/history/{prompt_id}")
            r.raise_for_status()
            entry = r.json().get(prompt_id)
            if entry:
                status = entry.get("status", {})
                if status.get("status_str") == "error":
                    raise ComfyError(f"échec ComfyUI: {json.dumps(status.get('messages', [])[-1:])[:500]}")
                if status.get("completed") or entry.get("outputs"):
                    return entry["outputs"]
            time.sleep(poll)
        raise ComfyError(f"timeout après {timeout:.0f}s")

    def download_outputs(self, outputs: dict[str, Any], dest: Path, prefix: str) -> list[Path]:
        """Download every file output (any node/key) that looks like a mesh."""
        saved: list[Path] = []
        for node in outputs.values():
            for items in node.values():
                for it in items if isinstance(items, list) else []:
                    if not (isinstance(it, dict) and "filename" in it):
                        continue
                    ext = Path(it["filename"]).suffix.lower()
                    is_image = ext in IMAGE_EXT and it.get("type") == "output"  # skip temp previews
                    if ext not in MESH_EXT and not is_image:
                        continue
                    r = self.http.get("/view", params={k: it.get(k, "") for k in ("filename", "subfolder", "type")})
                    r.raise_for_status()
                    folder = dest / "references" if is_image else dest
                    folder.mkdir(exist_ok=True)
                    out = folder / f"{prefix}_{it['filename']}"
                    out.write_bytes(r.content)
                    saved.append(out)
        return saved


def load_workflow(name: str) -> tuple[dict[str, Any], dict[str, list[str]]]:
    wf, mp = WORKFLOWS / f"{name}.json", WORKFLOWS / f"{name}.map.json"
    if not wf.exists() or not mp.exists():
        have = sorted(p.stem for p in WORKFLOWS.glob("*.json") if not p.stem.endswith(".map"))
        raise ComfyError(f"workflow '{name}' introuvable (workflows/{name}.json + .map.json). Disponibles: {have or 'aucun'}")
    return json.loads(wf.read_text()), json.loads(mp.read_text())


def generate(
    comfy: Comfy,
    workflow: str,
    dest: Path,
    *,
    image: Path | None = None,
    prompt: str | None = None,
    seed: int | None = None,
    overrides: dict[str, Any] | None = None,
    on_queued: Callable[[str, str], None] | None = None,
) -> list[Path]:
    wf, mp = load_workflow(workflow)

    def put(key: str, value: Any) -> None:
        if key not in mp:
            raise ComfyError(f"le workflow '{workflow}' n'a pas d'entrée '{key}' dans son .map.json")
        node, field = mp[key]
        wf[node]["inputs"][field] = value

    if image is not None:
        put("image", comfy.upload_image(image))
    if prompt is not None:
        put("prompt", prompt)
    if "seed" in mp:
        put("seed", seed if seed is not None else random.randrange(2**31))
    for path, value in (overrides or {}).items():
        node, field = path.split(".", 1)
        wf[node]["inputs"][field] = value

    pid = comfy.queue(wf)
    if on_queued:
        on_queued(workflow, pid)
    return _finish(comfy, workflow, mp, pid, dest, seed, on_queued)


def _finish(comfy: Comfy, workflow: str, mp: dict[str, Any], pid: str, dest: Path, seed: int | None,
            on_queued: Callable[[str, str], None] | None) -> list[Path]:
    outputs = comfy.wait(pid)
    files = comfy.download_outputs(outputs, dest, time.strftime("%Y%m%d-%H%M%S"))
    if not files:
        raise ComfyError("workflow terminé mais aucun fichier en sortie (vérifie le nœud SaveGLB / SaveImage)")
    nxt = mp.get("next")
    if nxt:
        # chained stage (e.g. figurine image -> TRELLIS.2): free the GPU between both, one graph
        # holding Qwen Image Edit and TRELLIS.2 together does not fit in 16 GB
        images = [f for f in files if f.suffix.lower() in IMAGE_EXT]
        if not images:
            raise ComfyError(f"'{workflow}' n'a pas produit d'image à passer à '{nxt}'")
        comfy.free()
        files += generate(comfy, nxt, dest, image=images[-1], seed=seed, on_queued=on_queued)
    return files


def resume(comfy: Comfy, workflow: str, pid: str, dest: Path, *,
           on_queued: Callable[[str, str], None] | None = None) -> list[Path]:
    """Pick up a generation queued before the workshop restarted."""
    if not comfy.known(pid):
        raise ComfyError("génération introuvable dans ComfyUI (redémarré entre-temps ?) : relance-la")
    _, mp = load_workflow(workflow)
    return _finish(comfy, workflow, mp, pid, dest, None, on_queued)
