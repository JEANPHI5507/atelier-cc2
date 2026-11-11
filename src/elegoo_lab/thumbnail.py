"""Thumbnail shown on the printer screen: a small shaded view of the model, embedded in the G-code.

OrcaSlicer's command line cannot render thumbnails (no OpenGL), although the CC2 profile asks for a
144x144 PNG. We draw it in software and insert it in the standard ``; thumbnail begin`` block.
"""

from __future__ import annotations

import base64
import io
from pathlib import Path

import numpy as np
import trimesh
from PIL import Image, ImageDraw

SIZE = 144
MAX_FACES = 60000  # enough for 144 px; bigger meshes are sampled (largest faces first)


def render(v: np.ndarray, f: np.ndarray, rgb: np.ndarray, size: int = SIZE) -> bytes:
    """PNG of a Z-up mesh seen from the front-left, 30° above; ``rgb`` = one colour per face."""
    # big flat faces (a label's plate) sort badly against small nearby ones (its letters):
    # split them so the far-to-near drawing order stays right
    span = float(np.ptp(v, axis=0).max()) or 1.0
    edges = np.linalg.norm(v[f][:, [1, 2, 0]] - v[f], axis=2).max(axis=1)
    if (edges > span / 25).any() and len(f) < MAX_FACES:
        v, f, idx = trimesh.remesh.subdivide_to_size(v, f, max_edge=span / 25, max_iter=8, return_index=True)
        rgb = rgb[idx]
    if len(f) > MAX_FACES:
        tri = v[f]
        area = np.linalg.norm(np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0]), axis=1)
        keep = np.argsort(-area)[:MAX_FACES]
        f, rgb = f[keep], rgb[keep]
    c = v.mean(axis=0)
    yaw, pitch = np.radians(-35), np.radians(28)
    ry = np.array([[np.cos(yaw), -np.sin(yaw), 0], [np.sin(yaw), np.cos(yaw), 0], [0, 0, 1]])
    rx = np.array([[1, 0, 0], [0, np.cos(pitch), -np.sin(pitch)], [0, np.sin(pitch), np.cos(pitch)]])
    p = (v - c) @ (rx @ ry).T             # x right, y depth (away), z up
    t = p[f]
    n = np.cross(t[:, 1] - t[:, 0], t[:, 2] - t[:, 0])
    n /= np.linalg.norm(n, axis=1, keepdims=True) + 1e-12
    light = np.array([0.35, -0.75, 0.55])
    shade = np.clip(np.abs(n @ (light / np.linalg.norm(light))), 0.35, 1.0)[:, None]
    xy = t[:, :, [0, 2]]
    lo, hi = xy.reshape(-1, 2).min(0), xy.reshape(-1, 2).max(0)
    k = (size * 0.86) / max(hi - lo)
    pts = (xy - (lo + hi) / 2) * k + size / 2
    pts[:, :, 1] = size - pts[:, :, 1]
    img = Image.new("RGB", (size, size), (34, 38, 46))
    draw = ImageDraw.Draw(img)
    colours = np.clip(rgb * shade, 0, 255).astype(int)
    for i in np.argsort(-t[:, :, 1].mean(axis=1)):  # far to near
        draw.polygon([tuple(q) for q in pts[i]], fill=tuple(colours[i]))
    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return buf.getvalue()


def inject(gcode: Path, png: bytes, size: int = SIZE) -> None:
    """Insert (or replace) the thumbnail block right after the G-code header."""
    b64 = base64.b64encode(png).decode()
    lines = [b64[i:i + 78] for i in range(0, len(b64), 78)]
    block = ("\n; THUMBNAIL_BLOCK_START\n;\n"
             f"; thumbnail begin {size}x{size} {len(b64)}\n" + "".join(f"; {ln}\n" for ln in lines)
             + "; thumbnail end\n;\n; THUMBNAIL_BLOCK_END\n")
    text = gcode.read_text(errors="ignore")
    if "; THUMBNAIL_BLOCK_START" in text:
        a = text.index("\n; THUMBNAIL_BLOCK_START")
        b = text.index("; THUMBNAIL_BLOCK_END\n") + len("; THUMBNAIL_BLOCK_END\n")
        text = text[:a] + text[b:]
    marker = "; HEADER_BLOCK_END\n"
    at = text.find(marker)
    at = at + len(marker) if at >= 0 else 0
    gcode.write_text(text[:at] + block + text[at:])
