"""Gallery of prints: one folder per print with its timelapse, final photo and facts.

The watcher opens an entry when a print starts, adds one camera frame per layer, and closes it at
the end: the frames become an MP4 (ffmpeg) and are deleted. Kept in models/.galerie/<id>/.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any

from . import config

MAX_FRAMES = 900          # beyond this, every other frame is dropped (a 3000-layer print stays a short video)
FPS = 24
KEEP = 200                # entries


def root() -> Path:
    return config.MODELS_DIR / ".galerie"   # looked up each time: tests swap the library


def _safe(entry_id: str) -> Path:
    p = root() / Path(entry_id).name
    if not p.is_dir():
        raise FileNotFoundError(entry_id)
    return p


class Recorder:
    """The entry of the print in progress."""

    def __init__(self, filename: str, meta: dict[str, Any] | None = None) -> None:
        if meta is None:
            stem = "".join(c if c.isalnum() or c in "-_." else "_" for c in Path(filename).stem)[:60] or "impression"
            meta = {"id": time.strftime("%Y%m%d-%H%M%S") + "_" + stem, "fichier": Path(filename).name,
                    "debut": int(time.time()), "issue": "en cours", "alertes": []}
        self.id = meta["id"]
        self.dir = root() / self.id
        (self.dir / "frames").mkdir(parents=True, exist_ok=True)
        self.frames = len(list((self.dir / "frames").glob("f*.jpg")))
        self.step = 1          # keep 1 frame out of `step`
        self.seen = self.frames
        self.meta = meta
        self.save()

    @classmethod
    def resume(cls, filename: str) -> "Recorder":
        """The workshop restarted mid-print: carry on with that print's open entry (its start time, its frames)."""
        for meta in entries():
            if meta.get("issue") == "en cours" and meta.get("fichier") == Path(filename).name:
                return cls(filename, meta)
        return cls(filename)

    def save(self) -> None:
        config.write_atomic(self.dir / "meta.json", json.dumps(self.meta, ensure_ascii=False, indent=1))

    def add_frame(self, jpeg: bytes) -> None:
        self.seen += 1
        if self.seen % self.step:
            return
        self.frames += 1
        (self.dir / "frames" / f"f{self.frames:05d}.jpg").write_bytes(jpeg)
        if self.frames >= MAX_FRAMES:       # thin out: keep every other frame, then record half as often
            kept = sorted((self.dir / "frames").glob("f*.jpg"))
            for i, f in enumerate(kept):
                if i % 2:
                    f.unlink()
            for i, f in enumerate(sorted((self.dir / "frames").glob("f*.jpg")), 1):
                f.rename(f.with_name(f"f{i:05d}.jpg"))
            self.frames = len(kept[::2])
            self.step *= 2

    def add_image(self, name: str, jpeg: bytes) -> str:
        (self.dir / name).write_bytes(jpeg)
        return name

    def finish(self, issue: str, **facts: Any) -> dict[str, Any]:
        """Close the entry: build the video (blocking: run in a thread)."""
        self.meta.update(issue=issue, fin=int(time.time()))
        self.meta.update(facts)
        self.meta["duree_s"] = self.meta["fin"] - self.meta["debut"]
        frames = self.dir / "frames"
        if self.frames >= 8 and shutil.which("ffmpeg"):
            out = self.dir / "timelapse.mp4"
            r = subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-framerate", str(FPS), "-i", str(frames / "f%05d.jpg"),
                                "-vf", "scale=trunc(iw/2)*2:trunc(ih/2)*2", "-c:v", "libx264", "-pix_fmt", "yuv420p",
                                "-movflags", "+faststart", str(out)], capture_output=True, text=True, timeout=600)
            if r.returncode == 0:
                self.meta["video"] = out.name
        last = sorted(frames.glob("f*.jpg"))
        if last and "photo" not in self.meta:
            shutil.copy(last[-1], self.dir / "photo.jpg")
            self.meta["photo"] = "photo.jpg"
        shutil.rmtree(frames, ignore_errors=True)
        self.save()
        _prune()
        return self.meta


def stale(keep: str | None = None) -> list[str]:
    """Entries left "en cours" by a workshop that stopped mid-print."""
    return [m["id"] for m in entries() if m.get("issue") == "en cours" and m["id"] != keep]


def close_stale(ids: list[str]) -> int:
    """Close these entries as "interrompue" (blocking, may build a video: run in a thread)."""
    n = 0
    for meta in entries():
        if meta["id"] in ids and meta.get("issue") == "en cours":
            d = root() / meta["id"]
            last = max((p.stat().st_mtime for p in d.rglob("*") if p.is_file()), default=meta["debut"])
            rec = Recorder(meta["fichier"], meta)
            rec.finish("interrompue")
            rec.meta.update(fin=int(last), duree_s=int(last) - meta["debut"])   # when it was last seen, not now
            rec.save()
            n += 1
    return n


def _prune() -> None:
    entries = sorted(p for p in root().iterdir() if p.is_dir())
    for p in entries[:-KEEP]:
        shutil.rmtree(p, ignore_errors=True)


def entries() -> list[dict[str, Any]]:
    if not root().exists():
        return []
    out = []
    for p in sorted(root().iterdir(), reverse=True):
        try:
            out.append(json.loads((p / "meta.json").read_text()))
        except (OSError, ValueError):
            continue
    return out


def file(entry_id: str, name: str) -> Path:
    p = _safe(entry_id) / Path(name).name
    if not p.is_file() or p.suffix not in (".jpg", ".mp4"):
        raise FileNotFoundError(name)
    return p


def update(entry_id: str, **values: Any) -> dict[str, Any]:
    d = _safe(entry_id)
    meta = json.loads((d / "meta.json").read_text())
    meta.update(values)
    config.write_atomic(d / "meta.json", json.dumps(meta, ensure_ascii=False, indent=1))
    return meta


def delete(entry_id: str) -> None:
    shutil.rmtree(_safe(entry_id))
