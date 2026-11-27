"""A flat object (or a drawing) photographed from above becomes a part: the code finds the outline, the
user (or the assistant) gives the real size of its longest side and the thickness, and the outline is
extruded into one closed solid.

Works best with the photo taken straight from above, the object on a plain background that contrasts
with it (a key on white paper, a cut-out on a dark table). The background is what touches the photo's
border; the object is the largest region of the other tone. Inner regions of the background tone (a ring's
hole, a key's eye) become holes. A picture of the outline drawn over the photo comes back with the result,
so a person (or the vision) can check it before printing.
"""

from __future__ import annotations

import io
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, cast

import numpy as np
from PIL import Image, ImageDraw, ImageOps

WORK_PX = 1000  # the photo is reduced to this on its longest side
SIMPLIFY_MM = 0.25  # outline kept within this of the traced edge (finer than a 0.4 mm nozzle shows)
MIN_HOLE_SHARE = 0.002  # holes under this share of the object's area are dust, not holes
MAX_POINTS = 400  # the extrusion tool's limit


PHOTO_EXT = {".jpg", ".jpeg", ".png", ".webp"}
MAX_PHOTO_BYTES = 15_000_000


def photos_dir() -> Path:
    """Where the photos sent to the assistant live: a hidden folder of the library."""
    from . import config

    d = config.MODELS_DIR / ".croquis"
    d.mkdir(parents=True, exist_ok=True)
    return d


def save_photo(data: bytes, filename: str) -> Path:
    """Keep an uploaded photo (re-encoded, turned upright, at most 2000 px) under a fresh name."""
    import time

    if len(data) > MAX_PHOTO_BYTES:
        raise ValueError("photo trop lourde (15 Mo au plus)")
    if Path(filename).suffix.lower() not in PHOTO_EXT:
        raise ValueError(
            "photo en JPEG, PNG ou WebP (une photo HEIC d'iPhone : exporte-la en JPEG)"
        )
    try:
        img = ImageOps.exif_transpose(Image.open(io.BytesIO(data))).convert("RGB")
    except Exception as err:  # noqa: BLE001 — Pillow raises many kinds on a bad file
        raise ValueError("ce fichier n'est pas une image lisible") from err
    img.thumbnail((2000, 2000))
    out = photos_dir() / f"photo_{time.strftime('%Y%m%d-%H%M%S')}.jpg"
    k = 1
    while out.exists():
        k += 1
        out = out.with_name(f"photo_{time.strftime('%Y%m%d-%H%M%S')}_{k}.jpg")
    img.save(out, quality=90)
    return out


@dataclass
class Outline:
    outer: list[list[float]]  # mm, counter-clockwise, X right, Y up
    holes: list[list[list[float]]] = field(default_factory=list)
    size_mm: tuple[float, float] = (0.0, 0.0)
    mm_per_px: float = 0.0
    warnings: list[str] = field(default_factory=list)
    preview: bytes = b""  # PNG: the photo with the outline (red) and holes (blue)


def _load(path: Path) -> np.ndarray:
    img = ImageOps.exif_transpose(Image.open(path)).convert("L")
    img.thumbnail((WORK_PX, WORK_PX))
    return cast("np.ndarray", np.asarray(img, dtype=float) / 255.0)


def _simplify(ring: np.ndarray, tol_px: float) -> np.ndarray:
    from skimage.measure import approximate_polygon

    out = approximate_polygon(ring, tolerance=tol_px)
    while len(out) > MAX_POINTS:  # very jagged outline: loosen until the tool takes it
        tol_px *= 1.5
        out = approximate_polygon(ring, tolerance=tol_px)
    return cast("np.ndarray", out[:-1] if len(out) > 3 and np.allclose(out[0], out[-1]) else out)


def _area(ring: np.ndarray) -> float:
    x, y = ring[:, 0], ring[:, 1]
    return 0.5 * float(np.dot(x, np.roll(y, -1)) - np.dot(y, np.roll(x, -1)))


def extract(
    path: Path, longest_mm: float, *, holes: bool = True, invert: bool | None = None
) -> Outline:
    """The outline of the main object in the photo, scaled so its longest side is ``longest_mm``.
    ``invert``: force which tone is the object (None = the tone the photo's border does not have).
    """
    from scipy import ndimage
    from skimage import filters, measure, morphology

    if not 2 <= longest_mm <= 1500:
        raise ValueError("la taille réelle du plus grand côté est entre 2 et 1500 mm")
    g = filters.gaussian(_load(path), sigma=1.2)
    warnings: list[str] = []
    t = filters.threshold_otsu(g)
    border = np.concatenate([g[0], g[-1], g[:, 0], g[:, -1]])
    dark_object = bool(np.median(border) > t) if invert is None else not invert
    mask = g < t if dark_object else g > t
    gap = abs(float(g[mask].mean() - g[~mask].mean())) if mask.any() and (~mask).any() else 0.0
    if gap < 0.15:
        warnings.append(
            "peu de contraste entre l'objet et le fond : pose-le sur un fond uni bien différent"
        )
    r = max(1, round(min(g.shape) / 400))
    mask = morphology.opening(mask, morphology.disk(r)).astype(bool)
    mask = morphology.closing(mask, morphology.disk(r)).astype(bool)
    labels = measure.label(mask)
    if labels.max() == 0:
        raise ValueError("aucun objet trouvé sur la photo (fond et objet trop proches ?)")
    regions = sorted(measure.regionprops(labels), key=lambda p: -p.area)
    main = regions[0]
    h, w = g.shape
    r0, c0, r1, c1 = main.bbox
    if r0 == 0 or c0 == 0 or r1 == h or c1 == w:
        warnings.append(
            "l'objet touche le bord de la photo : il est peut-être coupé, recule un peu"
        )
    if len(regions) > 1 and regions[1].area > 0.15 * main.area:
        warnings.append(
            "un autre objet ou une ombre forte sur la photo : seul le plus grand est gardé"
        )
    obj = labels == main.label
    solid = ndimage.binary_fill_holes(obj)
    padded = np.pad(solid, 1)
    rings = measure.find_contours(padded.astype(float), 0.5)
    outer = max(rings, key=len) - 1  # (row, col) px
    # the object's own axis (a key photographed at an angle): its length is measured along it, and the
    # part comes out straight on the plate
    xy = np.c_[outer[:, 1], h - outer[:, 0]]  # px, X right, Y up
    centre = xy.mean(axis=0)
    evals, evecs = np.linalg.eigh(np.cov((xy - centre).T))
    axis = evecs[:, int(np.argmax(evals))]
    rot = np.array([[axis[0], axis[1]], [-axis[1], axis[0]]])

    def turn(ring: np.ndarray) -> np.ndarray:  # px (row, col) -> px along the object's axis
        return cast("np.ndarray", (np.c_[ring[:, 1], h - ring[:, 0]] - centre) @ rot.T)

    k = longest_mm / float(np.ptp(turn(outer), axis=0).max())  # mm per px, first guess
    simple_outer = _simplify(outer, SIMPLIFY_MM / k)
    k = longest_mm / float(np.ptp(turn(simple_outer), axis=0).max())  # exact on what is extruded
    outer_mm = turn(simple_outer) * k
    if _area(outer_mm) < 0:
        outer_mm = outer_mm[::-1]
    hole_rings: list[np.ndarray] = []
    hole_px: list[np.ndarray] = []
    if holes:
        inner = solid & ~obj
        inner_labels = measure.label(inner)
        for hp in measure.regionprops(inner_labels):
            if hp.area < MIN_HOLE_SHARE * main.area:
                continue
            hm = np.pad(inner_labels == hp.label, 1)
            ring = max(measure.find_contours(hm.astype(float), 0.5), key=len) - 1
            simple = _simplify(ring, SIMPLIFY_MM / k)
            hr = turn(simple) * k
            if len(hr) >= 3:
                hole_rings.append(hr[::-1] if _area(hr) > 0 else hr)
                hole_px.append(simple)
    lo = outer_mm.min(axis=0)
    out = Outline(
        outer=(outer_mm - lo).round(3).tolist(),
        holes=[(x - lo).round(3).tolist() for x in hole_rings],
        size_mm=tuple(round(float(x), 1) for x in np.ptp(outer_mm, axis=0)),  # type: ignore[arg-type]
        mm_per_px=round(k, 4),
        warnings=warnings,
    )
    out.preview = _preview(path, g.shape, outer, hole_px)
    return out


def _preview(
    path: Path, shape: tuple[int, ...], outer: np.ndarray, holes: list[np.ndarray]
) -> bytes:
    img = ImageOps.exif_transpose(Image.open(path)).convert("RGB")
    img = img.resize((shape[1], shape[0]))
    d = ImageDraw.Draw(img)
    width = max(2, round(min(shape[:2]) / 250))
    d.line(
        [(float(c), float(r)) for r, c in outer] + [(float(outer[0][1]), float(outer[0][0]))],
        fill=(229, 57, 53),
        width=width,
    )
    for ring in holes:
        d.line(
            [(float(c), float(r)) for r, c in ring] + [(float(ring[0][1]), float(ring[0][0]))],
            fill=(30, 136, 229),
            width=width,
        )
    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return buf.getvalue()


def summary(o: Outline) -> dict[str, Any]:
    return {
        "taille_mm": list(o.size_mm),
        "points": len(o.outer),
        "trous": len(o.holes),
        "mm_par_pixel": o.mm_per_px,
        "avertissements": o.warnings,
    }
