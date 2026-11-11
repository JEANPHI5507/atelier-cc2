"""Camera-based failure detection, run on this PC.

Uses the open model of Obico (The Spaghetti Detective, AGPL-3.0): a small YOLO network trained on
failed prints (spaghetti, part torn off the plate, blobs). Nothing leaves the house: frames are read
from the printer's camera and analysed here with ONNX Runtime on the CPU (about a second per frame).

Scoring follows Obico's published algorithm: per frame, the sum of the detections' confidences; an
exponentially weighted mean compared with the print's own long-term baseline, so a part that always
"looks a bit like spaghetti" does not keep raising alarms. Two levels: warn, then (stricter) pause.
"""

from __future__ import annotations

import asyncio
import hashlib
import io
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image, ImageDraw

from . import config

MODEL_URL = "https://www.obico.io/static_pub/ml-models/model-weights-5a6b1be1fa.onnx"
MODEL_SHA256 = "0a6ebd8e30dbf6a450c50f9c0a5406f04ba7eb1c99fd5996e888c78bb383b9aa"
BOX_THRESH = 0.08          # a box counts from this confidence (Obico THRESH)
NMS = 0.45
# Obico 2nd-gen hyper-parameters (backend/config/settings.py)
PARAMS = {"EWM_SPAN": 12, "ROLLING_WIN_SHORT": 310, "ROLLING_WIN_LONG": 7200, "THRESHOLD_LOW": 0.38,
          "THRESHOLD_HIGH": 0.78, "INIT_SAFE_FRAME_NUM": 30, "ROLLING_MEAN_SHORT_MULTIPLE": 3.8, "ESCALATING_FACTOR": 1.75}
_net = None
_net_lock = threading.Lock()


def model_path() -> Path:
    return config.ROOT / "tools" / "obico" / "model.onnx"


def model_ready() -> bool:
    return model_path().exists()


def download_model(progress=None) -> Path:
    """Fetch the model once (200 MB) and check it is exactly the published one."""
    import httpx
    p = model_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".part")
    h = hashlib.sha256()
    with httpx.stream("GET", MODEL_URL, follow_redirects=True, timeout=60) as r:
        r.raise_for_status()
        total = int(r.headers.get("content-length", 0))
        done = 0
        with tmp.open("wb") as f:
            for chunk in r.iter_bytes(1 << 20):
                f.write(chunk)
                h.update(chunk)
                done += len(chunk)
                if progress:
                    progress(done, total)
    if h.hexdigest() != MODEL_SHA256:
        tmp.unlink(missing_ok=True)
        raise RuntimeError("modèle téléchargé corrompu (empreinte différente) : réessaie")
    tmp.replace(p)
    return p


def _session():
    global _net
    with _net_lock:
        if _net is None:
            import onnxruntime
            opts = onnxruntime.SessionOptions()
            opts.intra_op_num_threads = 2          # leave the PC usable while printing
            _net = onnxruntime.InferenceSession(str(model_path()), opts, providers=["CPUExecutionProvider"])
        return _net


def _nms(boxes: np.ndarray, confs: np.ndarray) -> list[int]:
    x1, y1, x2, y2 = boxes.T
    areas = (x2 - x1) * (y2 - y1)
    order, keep = confs.argsort()[::-1], []
    while order.size:
        i, rest = order[0], order[1:]
        keep.append(int(i))
        w = np.maximum(0, np.minimum(x2[i], x2[rest]) - np.maximum(x1[i], x1[rest]))
        hh = np.maximum(0, np.minimum(y2[i], y2[rest]) - np.maximum(y1[i], y1[rest]))
        inter = w * hh
        order = rest[inter / (areas[i] + areas[rest] - inter + 1e-9) <= NMS]
    return keep


def detect(jpeg: bytes) -> list[tuple[float, tuple[float, float, float, float]]]:
    """(confidence, box x1,y1,x2,y2 in 0..1) for each suspected failure in this frame."""
    net = _session()
    inp = net.get_inputs()[0]
    h, w = inp.shape[2], inp.shape[3]
    img = Image.open(io.BytesIO(jpeg)).convert("RGB").resize((w, h), Image.BILINEAR)
    x = np.asarray(img, np.float32).transpose(2, 0, 1)[None] / 255.0
    boxes, confs = net.run(None, {inp.name: x})
    boxes, confs = boxes[0, :, 0, :], confs[0].max(axis=1)
    ok = confs > BOX_THRESH
    boxes, confs = boxes[ok], confs[ok]
    return [(float(confs[i]), tuple(float(v) for v in boxes[i])) for i in _nms(boxes, confs)] if len(confs) else []


def annotate(jpeg: bytes, dets: list[tuple[float, tuple[float, float, float, float]]]) -> bytes:
    """The frame with the suspicious areas framed, for the alert."""
    img = Image.open(io.BytesIO(jpeg)).convert("RGB")
    d = ImageDraw.Draw(img)
    W, H = img.size
    for c, (x1, y1, x2, y2) in dets:
        if c < 0.2:
            continue
        d.rectangle([x1 * W, y1 * H, x2 * W, y2 * H], outline=(255, 80, 60), width=3)
        d.text((x1 * W + 4, y1 * H + 2), f"{c:.0%}", fill=(255, 80, 60))
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=85)
    return buf.getvalue()


@dataclass
class Prediction:
    """Obico's per-print state (current print) plus the lifetime baseline."""
    frames: int = 0
    lifetime: int = 0
    ewm: float = 0.0
    short: float = 0.0
    long: float = 0.0
    last_p: float = 0.0
    history: list[float] = field(default_factory=list)

    def new_print(self) -> None:
        self.frames, self.ewm, self.short = 0, 0.0, 0.0

    def update(self, p: float) -> None:
        a = 2 / (PARAMS["EWM_SPAN"] + 1)
        self.last_p = p
        self.frames += 1
        self.lifetime += 1
        self.ewm = p * a + self.ewm * (1 - a)
        self.short += (p - self.short) / min(PARAMS["ROLLING_WIN_SHORT"], self.frames)
        self.long += (p - self.long) / min(PARAMS["ROLLING_WIN_LONG"], self.lifetime)
        self.history = (self.history + [round(p, 3)])[-120:]

    def failing(self, sensitivity: float = 1.0, escalate: bool = False) -> bool:
        if self.frames < PARAMS["INIT_SAFE_FRAME_NUM"]:
            return False
        adj = (self.ewm - self.long) * sensitivity / (PARAMS["ESCALATING_FACTOR"] if escalate else 1)
        if adj < PARAMS["THRESHOLD_LOW"]:
            return False
        if adj > PARAMS["THRESHOLD_HIGH"]:
            return True
        return adj > (self.short - self.long) * PARAMS["ROLLING_MEAN_SHORT_MULTIPLE"]


async def grab(manager: Any, timeout: float = 10.0) -> bytes:
    """One JPEG from the printer camera through pycentauri's shared stream (the CC2's camera
    server starves if every reader opens its own connection)."""
    async def read() -> bytes:
        _, chunks = await manager.camera.subscribe()
        buf = b""
        try:
            async for c in chunks:
                buf += c
                a = buf.find(b"\xff\xd8")
                b = buf.find(b"\xff\xd9", a + 2) if a >= 0 else -1
                if b > 0:
                    return buf[a:b + 2]
                if len(buf) > 8_000_000:
                    buf = buf[-1_000_000:]
        finally:
            await chunks.aclose()
        raise RuntimeError("caméra : flux terminé sans image")
    return await asyncio.wait_for(read(), timeout)
