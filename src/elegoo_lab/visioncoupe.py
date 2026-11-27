"""Where to cut, with a second pair of eyes: the code finds the discreet cut planes and draws them numbered on
two views of the model; the vision model (``vibe -p`` with the images, no API key) chooses and explains; the
code always checks the choice again (right number of cuts per axis, parallel planes, nothing forbidden,
every piece fits the plate) and falls back to its own plan, saying why, when the choice does not hold.
"""

from __future__ import annotations

import json
import subprocess
import tempfile
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from . import config, cut, thumbnail

VIEW_PX = 720
MAX_FACES = 20000
TIMEOUT_S = 180
COLOURS = [
    (229, 57, 53),
    (30, 136, 229),
    (67, 160, 71),
    (253, 216, 53),
    (171, 71, 188),
    (255, 112, 67),
    (0, 172, 193),
    (141, 110, 99),
    (233, 30, 99),
    (63, 81, 181),
    (0, 150, 136),
    (121, 85, 72),
]


@dataclass
class Numbered:
    id: int
    cand: cut.Candidate

    def line(self, origin: np.ndarray) -> str:
        c = self.cand
        return f"{self.id} : {c.plane.label(origin)} — section {c.area:.0f} mm², {c.islands} morceau(x) coupé(s)"


def settings() -> dict[str, Any]:
    """``[vision]`` in config.toml: ``modele`` (the vibe model alias, default: vibe's own) and ``delai_s``."""
    if config.CONFIG_FILE.exists():
        return dict(tomllib.loads(config.CONFIG_FILE.read_text()).get("vision", {}))
    return {}


def number(cands: list[cut.Candidate]) -> list[Numbered]:
    return [Numbered(i + 1, c) for i, c in enumerate(cands)]


def _ortho(
    v: np.ndarray, f: np.ndarray, h: int, w: int, depth: int, near_is_high: bool
) -> tuple[Image.Image, Any]:
    """Shaded orthographic view with horizontal axis ``h`` and vertical axis ``w``; returns the picture and
    the function turning model coordinates (u, w) into pixels."""
    f = thumbnail.largest(v, f, np.zeros((len(f), 3)), MAX_FACES)[0]
    lo, hi = v.min(axis=0), v.max(axis=0)
    pad = 0.06 * float(max(hi[h] - lo[h], hi[w] - lo[w]))
    k = VIEW_PX * 0.86 / (max(hi[h] - lo[h], hi[w] - lo[w]) + 2 * pad)
    mid_u, mid_w = (lo[h] + hi[h]) / 2, (lo[w] + hi[w]) / 2

    def px(u: float, ww: float) -> tuple[float, float]:
        return (u - mid_u) * k + VIEW_PX / 2, VIEW_PX / 2 - (ww - mid_w) * k

    tri = v[f]
    n = np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0])
    n /= np.linalg.norm(n, axis=1, keepdims=True) + 1e-12
    towards = np.zeros(3)
    towards[depth] = 1.0 if near_is_high else -1.0  # the way the viewer sits
    light = towards + np.array([0.0, 0.0, 0.0])
    light[w] += 0.6
    light[h] += -0.4
    shade = np.clip(np.abs(n @ (light / np.linalg.norm(light))), 0.3, 1.0)
    img = Image.new("RGB", (VIEW_PX, VIEW_PX), (245, 245, 247))
    draw = ImageDraw.Draw(img)
    order = np.argsort(tri[:, :, depth].mean(axis=1) * (1 if near_is_high else -1))  # far first
    for i in order:
        pts = [px(p[h], p[w]) for p in tri[i]]
        g = int(215 * shade[i])
        draw.polygon(pts, fill=(g, g, min(255, g + 8)))
    return img, px


def render(v: np.ndarray, f: np.ndarray, numbered: list[Numbered], out_dir: Path) -> list[Path]:
    """Two PNGs (front, side; legends without accents, the default font has none) with every numbered candidate drawn as a coloured line and its number."""
    lo, hi = v.min(axis=0), v.max(axis=0)
    centre = (lo + hi) / 2
    font = ImageFont.load_default(size=20)
    paths = []
    for name, h, w, depth, near_high in (("face", 0, 2, 1, False), ("cote", 1, 2, 0, True)):
        img, px = _ortho(v, f, h, w, depth, near_high)
        draw = ImageDraw.Draw(img)
        u0, u1 = lo[h] - 0.06 * (hi[h] - lo[h]), hi[h] + 0.06 * (hi[h] - lo[h])
        w0, w1 = lo[w] - 0.03 * (hi[w] - lo[w]), hi[w] + 0.03 * (hi[w] - lo[w])
        for nb in numbered:
            n = nb.cand.plane.normal()
            nu, nw = n[h], n[w]
            c = nb.cand.plane.d - n[depth] * centre[depth]
            if abs(nu) < 1e-9 and abs(nw) < 1e-9:
                continue  # edge-on in this view: the other picture shows it
            if abs(nw) >= abs(nu):
                a, b = (u0, (c - nu * u0) / nw), (u1, (c - nu * u1) / nw)
            else:
                a, b = ((c - nw * w0) / nu, w0), ((c - nw * w1) / nu, w1)
            col = COLOURS[(nb.id - 1) % len(COLOURS)]
            pa, pb = px(*a), px(*b)
            draw.line([pa, pb], fill=col, width=4)
            x, y = pa
            x, y = min(max(x, 18), VIEW_PX - 18), min(max(y, 18), VIEW_PX - 18)
            draw.ellipse(
                (x - 15, y - 15, x + 15, y + 15), fill=col, outline=(255, 255, 255), width=2
            )
            draw.text(
                (x, y),
                str(nb.id),
                fill=(255, 255, 255) if sum(col) < 600 else (0, 0, 0),
                font=font,
                anchor="mm",
            )
        draw.text(
            (10, 8),
            "vue de face" if name == "face" else "vue de cote",
            fill=(60, 60, 60),
            font=font,
        )
        p = out_dir / f"coupes_{name}.png"
        img.save(p)
        paths.append(p)
    return paths


def prompt(
    numbered: list[Numbered],
    images: list[Path],
    height_mm: float,
    needs: dict[int, int],
    origin: np.ndarray,
    zones_text: str,
) -> str:
    cuts = (
        ", ".join(f"{n - 1} coupe(s) sur l'axe {'XYZ'[a]}" for a, n in sorted(needs.items()))
        or "aucune"
    )
    return (
        "Tu aides à choisir où découper en pièces un modèle 3D (figurine, objet) qui sera imprimé en grand "
        f"({height_mm:.0f} mm de haut) puis recollé avec des chevilles. Regarde les deux images "
        f"{images[0]} (vue de face) et {images[1]} (vue de côté) : les lignes colorées numérotées sont les "
        "coupes candidates.\n"
        f"Il faut au total : {cuts}.\n"
        "Candidats (axe Z = vertical ; X, Y depuis le centre du modèle ; section = surface coupée) :\n"
        + "\n".join(f"- {n.line(origin)}" for n in numbered)
        + "\n"
        + zones_text
        + "Choisis les coupes les plus discrètes et les moins fragiles : aux jointures naturelles (cou, taille, "
        "poignets, chevilles, base), loin du visage, des mains et des détails fins, là où la section est "
        "petite et où le raccord se verra le moins. Pour un objet mécanique, coupe aux endroits qui gardent "
        "les pièces solides. Plusieurs coupes sur un même axe doivent avoir la même inclinaison.\n"
        "Le code placera les coupes au plus près de tes choix et vérifiera que chaque pièce tient sur le plateau : "
        "ne calcule pas la taille des pièces, donne tes préférences (« choix », au moins le nombre de coupes "
        "demandé) et ce que tu veux éviter (« refus »).\n"
        "Réponds UNIQUEMENT par un objet JSON, sans texte autour :\n"
        '{"modele": "ce que tu vois, en une phrase", "choix": [numéros retenus], '
        '"refus": [{"id": numéro, "raison": "pourquoi pas"}], "commentaire": "ton conseil en une ou deux phrases"}'
    )


def ask(text: str, workdir: Path) -> tuple[dict[str, Any], str]:
    """One headless run of the CLI with only the file reader enabled; returns (reply JSON, error text)."""
    from . import assistant  # lazily: the assistant imports this module's callers

    binary = assistant.cli_bin()
    if not binary:
        return {}, "le CLI vibe est introuvable"
    cfg = settings()
    args = [
        binary,
        "-p",
        text,
        "--output",
        "json",
        "--max-turns",
        "6",
        "--enabled-tools",
        "read_file",
        "--approval-policy",
        "auto-approve",
        "--workdir",
        str(workdir),
    ]
    if cfg.get("modele"):
        args += ["--model", str(cfg["modele"])]
    try:
        sp = subprocess.run(  # noqa: S603 — CLI binary from the user's config
            args,
            capture_output=True,
            text=True,
            timeout=float(cfg.get("delai_s", TIMEOUT_S)),
            cwd=str(workdir),
            env=dict(assistant._CLI_ENV.items()),
        )
    except (subprocess.TimeoutExpired, OSError) as err:
        return {}, f"le CLI n'a pas répondu ({type(err).__name__})"
    reply = assistant._json_only(assistant._cli_message(sp.stdout))
    if not reply:
        return {}, (
            assistant._cli_detail(sp.stderr) if sp.returncode else "réponse sans JSON lisible"
        )
    return reply, ""


def validate(
    reply: dict[str, Any], numbered: list[Numbered]
) -> tuple[list[cut.Plane], list[cut.Plane], str]:
    """The wishes in a reply: (planes preferred, planes to avoid, why unusable). Preferred planes of one axis
    must lean the same way (parallel cuts): the first one decides, the others are dropped."""
    by_id = {n.id: n.cand.plane for n in numbered}
    raw = reply.get("choix")
    if not isinstance(raw, list) or not raw:
        return [], [], "pas de liste « choix » dans la réponse"
    chosen: list[int] = []
    for x in raw:
        try:
            i = int(x)
        except (TypeError, ValueError):
            return [], [], f"numéro de coupe illisible : {x!r}"
        if i not in by_id:
            return [], [], f"la coupe {i} n'existe pas"
        if i not in chosen:
            chosen.append(i)
    prefer: list[cut.Plane] = []
    kind: dict[int, tuple[int, float]] = {}
    for i in chosen:
        p = by_id[i]
        if kind.setdefault(p.axis, (p.lean, p.angle)) == (p.lean, p.angle):
            prefer.append(p)
    avoid: list[cut.Plane] = []
    for r in reply.get("refus") or []:
        try:
            i = int(r.get("id")) if isinstance(r, dict) else int(r)
        except (TypeError, ValueError):
            continue
        if i in by_id and i not in chosen:
            avoid.append(by_id[i])
    return prefer, avoid, ""


def choose(
    v: np.ndarray,
    f: np.ndarray,
    solid_cands: list[cut.Candidate],
    height_mm: float,
    needs: dict[int, int],
    zones_text: str = "",
) -> dict[str, Any]:
    """Ask the vision model about the candidates: ``{"prefer": [...], "avoid": [...], "info": {...}}``
    (both lists empty when there is nothing usable; ``info["repli"]`` then says why)."""
    numbered = number(solid_cands)
    lo, hi = v.min(axis=0), v.max(axis=0)
    origin = np.array([(lo[0] + hi[0]) / 2, (lo[1] + hi[1]) / 2, lo[2]])
    info: dict[str, Any] = {"utilisee": False, "candidats": [n.line(origin) for n in numbered]}
    with tempfile.TemporaryDirectory(prefix="coupes_") as tmp:
        images = render(v, f, numbered, Path(tmp))
        reply, err = ask(prompt(numbered, images, height_mm, needs, origin, zones_text), Path(tmp))
    if err:
        return {"prefer": [], "avoid": [], "info": {**info, "repli": err}}
    info.update(
        modele=str(reply.get("modele", ""))[:300],
        commentaire=str(reply.get("commentaire", ""))[:600],
        refus=[
            {"id": r.get("id"), "raison": str(r.get("raison", ""))[:300]}
            for r in (reply.get("refus") or [])
            if isinstance(r, dict)
        ][:20],
    )
    prefer, avoid, why = validate(reply, numbered)
    if why:
        return {"prefer": [], "avoid": [], "info": {**info, "repli": why}}
    info["choix"] = [n.id for n in numbered if n.cand.plane in prefer]
    return {"prefer": prefer, "avoid": avoid, "info": info}


def dumps(info: dict[str, Any]) -> str:
    return json.dumps(info, ensure_ascii=False)
