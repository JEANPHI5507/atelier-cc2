"""The workshop's conversational assistant: an LLM brain, acting through the workshop itself.

Two engines behind ``chat()``:
- ``cli``: the local agent CLI (default ``vibe``, already signed in — no API key) runs headless
  (``cmd -p …``) once per round. Its own MCP servers (Blender, …) stay available, so modelling
  can also go through a real 3D app; the workshop's tools still run here, described as a JSON
  protocol the agent answers with.
- ``api``: Mistral's function calling (the original path, kept as fallback).
Each tool edits the model exactly like the page does (repair, resize, turn, drill, slice, best
orientation) and reports back, so the brain answers factually.
"""

from __future__ import annotations

import contextlib
import difflib
import json
import os
import queue
import re
import selectors
import shutil
import subprocess
import tempfile
import threading
import time
import tomllib
import unicodedata
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import httpx
import numpy as np

from . import (
    colors,
    config,
    forme,
    grandformat,
    mesh,
    orient,
    parametric,
    printprep,
    repair,
    slicer,
)

API = "https://api.mistral.ai/v1/chat/completions"
TOOL_ROUNDS = 6  # tool calls before the answer must come out: no runaway loops
CLI_TIMEOUT = 300  # seconds per headless run: a Blender modelling round can be slow


def _conf() -> dict[str, Any]:
    if config.CONFIG_FILE.exists():
        return cast(
            "dict[str, Any]", tomllib.loads(config.CONFIG_FILE.read_text()).get("assistant", {})
        )
    return {}


def api_key() -> str | None:
    """The key from ``[assistant] api_key`` in config.toml, or the MISTRAL_API_KEY environment."""
    k = os.environ.get("MISTRAL_API_KEY") or _conf().get("api_key", "")
    return str(k) if k else None


def model_name() -> str:
    return str(_conf().get("model", "mistral-large-latest"))


def moteur() -> str:
    """Which engine: ``cli`` (default), ``api``, or ``auto``."""
    return str(_conf().get("moteur", "cli"))


def cli_bin() -> str | None:
    """The headless CLI to run, absolute path so a systemd service finds it, None if absent."""
    cmd = str(_conf().get("commande", "vibe"))
    found = shutil.which(cmd)
    if found:
        return found
    guess = Path.home() / ".local" / "bin" / cmd
    return str(guess) if guess.exists() else None


# warm CLI sessions (conversation id → CLI session id) and a lean spawn environment
# (pas de VIBE_ENABLE_TELEMETRY=false ici : sans la télémétrie, le API refuse le modèle
# avec « This model is not available in your subscription tier »)
_CLI_SESSIONS: dict[str, str] = {}
_CLI_ENV = {
    **os.environ,
    "VIBE_ENABLE_UPDATE_CHECKS": "false",
    "VIBE_TYPING_GRACE_PERIOD_MS": "100",
    "LOG_LEVEL": "WARNING",
}


# --- the tools: each one is the workshop doing what the page can already do -----------------------


def _unique(src: Path, tag: str, ext: str | None = None) -> Path:
    out = src.with_name(f"{src.stem}_{tag}{ext or src.suffix}")
    k = 2
    while out.exists():
        out = src.with_name(f"{src.stem}_{tag} ({k}){ext or src.suffix}")
        k += 1
    return out


def _fiche(src: Path) -> dict[str, Any]:
    info = mesh.info(src)
    try:
        cols = [
            {"hex": c["hex"], "part_surface": c["share"]} for c in colors.analyze(src)["colours"]
        ]
    except ValueError:
        cols = []
    return {
        "fichier": src.name,
        "taille_mm": [round(x, 1) for x in info["size_mm"]],
        "volume_cm3": info["volume_cm3"],
        "etanche": info["watertight"],
        "sur_le_plateau": info["fits_bed"],
        "triangles": info["triangles"],
        "couleurs": cols,
        "usage_conseille": printprep.suggest_usage(src),
    }


def _baked(src: Path, rotate=None, scale=None, height=None, tag: str = "modifie") -> dict[str, Any]:
    """A geometric edit written as a new PLY on the bed (colours kept as vertex colours, original untouched)."""
    m = mesh.load(src)
    rot = colors.rotation(tuple(rotate)) if rotate else None
    if rot is not None:
        m4 = np.eye(4)  # colors.rotation gives the 3x3; trimesh wants a 4x4
        m4[:3, :3] = rot
        m.apply_transform(m4)
        m.faces = colors.flip_if_mirrored(rot, m.faces)  # a mirror turns the surface inside out
    if scale:
        if len(scale) != 3:
            raise ValueError("l'échelle a un facteur par axe X, Y, Z (1 = rien)")
        m.apply_scale(list(scale))
    if height:
        if not 5 <= height <= 250:
            raise ValueError("hauteur entre 5 et 250 mm")
        m.apply_scale(height / float(m.extents[2]))
    if rot is None and scale is None and not height:
        raise ValueError("donne un angle, un facteur d'échelle ou une hauteur")
    lo, hi = m.bounds  # posé, centré, comme le reste de l'atelier
    m.apply_translation([-(lo[0] + hi[0]) / 2, -(lo[1] + hi[1]) / 2, -lo[2]])
    # a new PLY, both for the viewer (no Y-up surprise like a GLB rewritten) and the colours (vertex colours kept)
    out = _unique(src, tag, ".ply")
    m.export(out)
    return {
        "fichier": out.name,
        "nouvelle_taille_mm": [round(x, 1) for x in mesh.info(out)["size_mm"]],
    }


def _trancher(src: Path, args: dict[str, Any]) -> dict[str, Any]:
    usage = args.get("usage") or printprep.suggest_usage(src)
    if usage not in printprep.USAGES:
        usage = "decoratif"
    try:
        supports = args.get("supports") or False
        keys = {"aucun", "arbre", "arbre_fin", "arbre_solide", "colonnes"}
        supports = supports if supports in keys or isinstance(supports, bool) else "arbre"
        infill = args.get("remplissage")
        infill = max(0, min(100, int(infill))) if isinstance(infill, (int, float)) else None
        reglages = args.get("reglages") if isinstance(args.get("reglages"), dict) else None
        res = printprep.prepare_and_slice(
            src,
            out_dir=config.MODELS_DIR,
            usage=usage,
            supports=supports,
            quality=args.get("qualite")
            or printprep.USAGES[usage]["quality"]
            or slicer.DEFAULT_QUALITY,
            infill=infill,
            advanced=reglages,
            screen_thumbnail=False,
        )
    except (ValueError, slicer.SliceError) as err:
        return {"erreur": str(err)}
    out: dict[str, Any] = {
        "gcode": res["gcode"],
        "duree": res["time"],
        "filament_g": round(res.get("total_m", 0), 1),
        "usage": usage,
        "avertissements": res["warnings"][:3],
    }
    if res["slots"]:
        out["slots"] = [
            {"bobine": s["slot"], "filament": s["filament"], "metres": s["metres"]}
            for s in res["slots"]
        ]
    if res.get("temps", {}).get("nozzle"):
        out["temperatures"] = (
            f"buse {res['temps']['nozzle'][0]} °C · plateau {res['temps']['bed']} °C"
        )
    return out


FREE_TOOLS = ("catalogue_pieces", "creer_piece")  # tools that need no model open


def _plain(text: str) -> str:
    t = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode().lower()
    return "_".join(w for w in "".join(c if c.isalnum() else " " for c in t).split())


def resolve_piece(key: str) -> tuple[str, str]:
    """The catalogue key meant by ``key`` (a model often writes « boite_couvercle » or « Boîte avec
    couvercle »), and a note when it was not exact; ValueError listing the keys when nothing is close.
    """
    if key in parametric.KINDS:
        return key, ""
    plain = _plain(key)
    titles = {_plain(k.title): k.key for k in parametric.KINDS.values()}
    found = plain if plain in parametric.KINDS else titles.get(plain)
    if not found:
        starts = [k for k in parametric.KINDS if plain.startswith(k)]
        found = max(starts, key=len) if starts else None
    if not found:
        close = difflib.get_close_matches(plain, [*parametric.KINDS, *titles], n=1, cutoff=0.6)
        found = (close[0] if close[0] in parametric.KINDS else titles[close[0]]) if close else None
    if not found:
        raise ValueError(f"pièce inconnue « {key} » (clés : {', '.join(parametric.KINDS)})")
    return found, f"« {key} » compris comme « {found} » ({parametric.KINDS[found].title})"


def catalogue_line() -> str:
    """The catalogue in one line for a prompt: key = title (settings)."""
    return " ; ".join(
        f"{k.key} = {k.title} ({', '.join(p.name for p in k.params if p.kind != 'image')})"
        for k in parametric.KINDS.values()
    )


def _catalogue(args: dict[str, Any]) -> dict[str, Any]:
    """The made-to-measure parts, short; one part in full when asked for."""
    kinds = parametric.catalogue()
    want = args.get("piece")
    if want:
        k = next((x for x in kinds if x["key"] == want), None)
        if k is None:
            raise ValueError(
                f"pièce inconnue « {want} » (clés : {', '.join(x['key'] for x in kinds)})"
            )
        return {
            "piece": k["key"],
            "titre": k["title"],
            "description": k["description"],
            "reglages": [
                {
                    "nom": p["name"],
                    "libelle": p["label"],
                    "defaut": p["default"],
                    **(
                        {"min": p["lo"], "max": p["hi"], "unite": p["unit"]}
                        if p["lo"] is not None
                        else {}
                    ),
                    **({"choix": [o for o, _ in p["options"]]} if p["options"] else {}),
                }
                for p in k["params"]
                if p["kind"] != "image"
            ],
        }
    return {
        "pieces": [
            {
                "piece": k["key"],
                "titre": k["title"],
                "description": k["description"],
                "reglages": [p["name"] for p in k["params"] if p["kind"] != "image"],
            }
            for k in kinds
        ]
    }


def _creer_piece(args: dict[str, Any]) -> dict[str, Any]:
    key = args.get("piece")
    if not isinstance(key, str) or not key:
        raise ValueError("donne la clé de la pièce (catalogue_pieces)")
    key, note = resolve_piece(key)
    values = args.get("valeurs") or {}
    if not isinstance(values, dict):
        raise ValueError("`valeurs` est un objet {réglage: valeur}")
    nom = str(args.get("nom") or "").strip()
    if nom.startswith(key + "_"):  # create() already puts the key first
        nom = nom[len(key) + 1 :]
    known = {p.name for p in parametric.KINDS[key].params}
    unknown = sorted(set(values) - known)
    if unknown:
        raise ValueError(
            f"réglage(s) inconnu(s) pour « {key} » : {', '.join(unknown)} (réglages : {', '.join(sorted(known))})"
        )
    out = parametric.create(key, values, nom[:60] or None)
    parts = [o[0] for o in parametric._build(key, values)[2]]
    return {
        "fichier": out.name,
        "objets": parts,
        "taille_mm": [round(x, 1) for x in mesh.info(out)["size_mm"]],
        "c_est_fait": (
            f"pièce créée : {len(parts)} objet(s) ({', '.join(parts)}) posés côte à côte sur le plateau ; "
            "taille_mm = l'ensemble. Ne la recrée pas : réponds, ou travaille sur ce fichier."
        ),
        **({"note": note} if note else {}),
    }


_FILE_EXT = r"(?:stl|3mf|ply|glb|gltf|obj|off|step|stp|gcode)"
_QUOTED = re.compile(r"[«\"`“]\s*([^«»\"`“”\n]{1,120}?\." + _FILE_EXT + r")\s*[»\"`”]", re.I)
_BARE = re.compile(r"(?<![\w/.-])([\w+().-]{1,120}\." + _FILE_EXT + r")\b", re.I)


def ghost_files(text: str) -> list[str]:
    """File names a reply presents that the library does not hold (a name the brain made up). A bare word
    counts as found when some library file ends with it (names with spaces are only partly matched).
    """
    have = [p.name for p in config.MODELS_DIR.iterdir()] if config.MODELS_DIR.is_dir() else []
    out: list[str] = []
    quoted = [m.strip() for m in _QUOTED.findall(text)]
    for name in quoted + [b for b in _BARE.findall(text) if not any(b in q for q in quoted)]:
        if name not in have and not any(h.endswith(name) for h in have) and name not in out:
            out.append(name)
    return out


NO_MODEL = (
    "Aucun modèle n'est ouvert. Tu peux en créer un : « catalogue_pieces » puis « creer_piece » (pièces "
    "sur mesure à partir de cotes), ou le modéliser dans Blender (skill cc2-blender-cao) et l'exporter dans "
    "la bibliothèque. Dès qu'un outil rend un « fichier », il devient le modèle courant et les autres outils "
    "(fiche, trancher, grand_format…) travaillent dessus."
)


def _plan_for_model(p: dict[str, Any]) -> dict[str, Any]:
    """The plan as the brain reads it back: short, factual."""
    return {
        "taille_finale_mm": p["taille_mm"],
        "plans_de_coupe": p["plans"],
        "pieces": [
            {"nom": x["nom"], "taille_mm": x["taille_mm"], "pose": x["pose"]} for x in p["pieces"]
        ],
        "chevilles": p["chevilles"],
        "alertes": [{"message": a["message"], "bloquante": a["bloquante"]} for a in p["alertes"]],
        "tient_sur_le_plateau": p["ok"],
        **({"vision": p["vision"]} if "vision" in p else {}),
    }


def _couper(src: Path, args: dict[str, Any]) -> dict[str, Any]:
    height = args.get("hauteur") or float(mesh.info(src)["size_mm"][2])
    return _plan_for_model(
        grandformat.plan(
            src,
            float(height),
            args.get("interdites"),
            args.get("biais") is not False,
            bool(args.get("vision")),
        )
    )


def _grand_format(src: Path, args: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(args.get("hauteur"), (int, float)):
        raise ValueError("donne la hauteur finale voulue en mm")
    height = float(args["hauteur"])
    zones = args.get("interdites")
    biais = args.get("biais") is not False
    if not args.get("trancher"):
        return _plan_for_model(
            grandformat.plan(src, height, zones, biais, bool(args.get("vision")))
        )
    usage = args.get("usage") or printprep.suggest_usage(src)
    infill = args.get("remplissage")
    res = grandformat.executer(
        src,
        height,
        zones,
        biais,
        bool(args.get("vision")),
        usage=usage if usage in printprep.USAGES else "decoratif",
        supports=args.get("supports") or False,
        quality=args.get("qualite") or slicer.DEFAULT_QUALITY,
        infill=max(0, min(100, int(infill))) if isinstance(infill, (int, float)) else None,
    )
    return {
        "bilan": res["bilan"],
        "gcode": res["gcode"],
        "alertes": [a["message"] for a in res["alertes"]],
        "avertissements": res["avertissements"][:3],
    }


def _forme(src: Path, args: dict[str, Any]) -> dict[str, Any]:
    try:
        zone = args.get("zone")
        return forme.apply(
            src,
            shape=args["forme"],
            op=args["operation"],
            size=tuple(args["taille"]),
            at=tuple(args.get("position", [0, 0, 0])),
            file_at=(
                (float(zone[0]), float(zone[1]), float(zone[2]))
                if isinstance(zone, (list, tuple)) and len(zone) == 3
                else None
            ),
            colour=int(args.get("couleur", 1)),
        )
    except ValueError as err:
        return {"erreur": str(err)}


# --- the tool table as Mistral sees it ----------------------------------------------------------

SCHEMAS: dict[str, str] = {
    "fiche": "Dimensions, volume, étanchéité, couleurs et usage conseillé du modèle. Toujours gratuit, commence par là.",
    "reparer": "Réparer un maillage ouvert (une copie fermée : couleurs gardées, l'original reste). Rends le nom du nouveau fichier.",
    "redimensionner": "Changer la taille : hauteur finale en mm, ou facteur par axe (miroir si négatif). Nouveau fichier.",
    "faire_pivoter": "Tourner le modèle d'un angle en degrés sur X, Y, Z (multiples de 90). Nouveau fichier.",
    "orienter": "Les poses proposées avec le moins de surplombs, meilleures en premier. Ne change rien.",
    "percer_ou_ajouter": "Percer (trou d'aimant, de vis), ajouter (plot, socle) ou garder l'intersection du modèle avec cylindre, pavé ou boule. taille = [largeur, hauteur, profondeur] mm (pour un cylindre: [diamètre, hauteur, diamètre]), position = décalage en mm depuis le centre du modèle. Si l'utilisateur a CIBLÉ un point, passe ses coordonnées telles quelles dans zone : l'atelier les convertit exactement. Nouveau fichier.",
    "catalogue_pieces": "Les pièces sur mesure que l'atelier sait fabriquer à partir de cotes, sans IA (boîte à couvercle, étiquette, crochet, Gridfinity, support, engrenage, vis et écrous, porte-clés, boule de Noël, lithophanie…). Sans argument : la liste avec les réglages de chacune ; avec `piece` : le détail (défaut, min, max) d'une seule. Ne change rien, ne demande pas de modèle.",
    "creer_piece": "Fabriquer une pièce sur mesure (voir catalogue_pieces) et l'ajouter à la bibliothèque en 3MF, prête à trancher. `piece` = la clé du catalogue ("
    + ", ".join(parametric.KINDS)
    + "), `valeurs` = les réglages à changer (les autres gardent leur défaut ; cotes hors limites refusées avec la limite). Rends le nom du nouveau fichier et sa taille. Ne demande pas de modèle.",
    "couper": "Voir comment le modèle serait découpé en pièces à sa taille actuelle (ou à `hauteur`) : plans de coupe aux endroits discrets (cou, taille), pièces, poses, chevilles, alertes. `interdites` = zones où aucune coupe ne doit passer (visage, mains). Ne change rien et ne tranche rien.",
    "grand_format": "Module grand format : à partir de la hauteur finale voulue, redimensionne, coupe, choisit la meilleure pose de chaque pièce et vérifie que tout tient sur le plateau. Sans `trancher`, rend seulement le plan (pièces, plans, alertes) pour que l'utilisateur le valide sur l'aperçu. Avec trancher=true (SEULEMENT après que l'utilisateur a vu et validé le plan), tranche toutes les pièces et rend le bilan : pièces, durée, grammes, coût, chevilles.",
    "trancher": "Trancher avec OrcaSlicer (profils Elegoo CC2) maintenant : durée, filaments par bobine, températures. Peut prendre une minute. qualite = un profil de couches (ex. « 0.12mm Fine », « 0.20mm Standard »), remplissage = % infill, reglages = dictionnaire des réglages fins du profil (skill cc2-orcaslicer).",
}

PROPS: dict[str, dict[str, Any]] = {
    "fiche": {},
    "reparer": {},
    "redimensionner": {
        "hauteur": {"type": "number", "description": "hauteur finale en mm"},
        "echelle": {
            "type": "array",
            "items": {"type": "number"},
            "description": "[X, Y, Z], 1 = rien",
        },
    },
    "faire_pivoter": {"rx": {"type": "number"}, "ry": {"type": "number"}, "rz": {"type": "number"}},
    "orienter": {},
    "percer_ou_ajouter": {
        "forme": {"type": "string", "enum": ["cylindre", "pave", "boule"]},
        "operation": {"type": "string", "enum": ["percer", "ajouter", "garder"]},
        "taille": {"type": "array", "items": {"type": "number"}},
        "position": {
            "type": "array",
            "items": {"type": "number"},
            "description": "[x, y, z] mm depuis le centre du modèle",
        },
        "zone": {
            "type": "array",
            "items": {"type": "number"},
            "description": "[x, y, z] — les coordonnées du FICHIER reçues dans [ZONE CIBLÉE], à passer TELLES QUELLES quand l'utilisateur a ciblé ; l'atelier convertit",
        },
        "couleur": {
            "type": "integer",
            "description": "pour « ajouter » : 1-4, ou un de plus pour une nouvelle couleur",
        },
    },
    "catalogue_pieces": {
        "piece": {"type": "string", "description": "clé d'une pièce, pour son détail"}
    },
    "creer_piece": {
        "piece": {"type": "string", "description": "clé de la pièce (catalogue_pieces)"},
        "valeurs": {
            "type": "object",
            "description": "réglages à changer, clés du catalogue : {largeur: 80, texte: 'Vis M4'}",
        },
        "nom": {
            "type": "string",
            "description": "nom du fichier sans extension, sinon automatique",
        },
    },
    "couper": {
        "vision": {
            "type": "boolean",
            "description": "faire choisir les coupes par la vision (images numérotées) parmi les candidates ; le code revérifie. Plus lent (~1 min), faux par défaut",
        },
        "biais": {
            "type": "boolean",
            "description": "plans de coupe en biais (15°, 30°) en plus des plans droits, vrai par défaut",
        },
        "hauteur": {
            "type": "number",
            "description": "hauteur finale en mm, sinon la taille actuelle",
        },
        "interdites": {
            "type": "array",
            "items": {"type": "object"},
            "description": "zones interdites à la coupe, repère du modèle (X, Y depuis le centre, Z depuis la base, mm) : {axe: 'Z', de: 150, a: 190} (une bande), {boite: [[x,y,z],[x,y,z]]} ou {point: [x,y,z], rayon: 15}",
        },
    },
    "grand_format": {
        "vision": {
            "type": "boolean",
            "description": "faire choisir les coupes par la vision (images numérotées) parmi les candidates ; le code revérifie. Plus lent (~1 min), faux par défaut",
        },
        "biais": {
            "type": "boolean",
            "description": "plans de coupe en biais (15°, 30°) en plus des plans droits, vrai par défaut",
        },
        "hauteur": {"type": "number", "description": "hauteur finale voulue en mm (20 à 1500)"},
        "interdites": {
            "type": "array",
            "items": {"type": "object"},
            "description": "zones interdites à la coupe, repère du modèle (X, Y depuis le centre, Z depuis la base, mm) : {axe: 'Z', de: 150, a: 190} (une bande), {boite: [[x,y,z],[x,y,z]]} ou {point: [x,y,z], rayon: 15}",
        },
        "trancher": {
            "type": "boolean",
            "description": "true seulement après validation du plan par l'utilisateur",
        },
        "usage": {"type": "string", "enum": list(printprep.USAGES)},
        "supports": {
            "type": "string",
            "enum": ["aucun", "arbre", "arbre_fin", "arbre_solide", "colonnes"],
        },
        "qualite": {
            "type": "string",
            "description": "profil de couches OrcaSlicer, ex. 0.20mm Standard",
        },
        "remplissage": {"type": "integer", "description": "% de remplissage (0-100)"},
    },
    "trancher": {
        "usage": {"type": "string", "enum": list(printprep.USAGES)},
        "supports": {
            "type": "string",
            "enum": ["aucun", "arbre", "arbre_fin", "arbre_solide", "colonnes"],
        },
        "qualite": {
            "type": "string",
            "description": "profil de couches OrcaSlicer : 0.12mm Fine, 0.16mm Optimal, 0.20mm Standard, 0.20mm Strength, 0.24mm Draft, 0.28mm Extra Draft (buse 0.4)",
        },
        "remplissage": {
            "type": "integer",
            "description": "% de remplissage (0-100), sinon celui du profil",
        },
        "reglages": {
            "type": "object",
            "description": "réglages fins du profil OrcaSlicer, clés françaises validées (skill cc2-orcaslicer) : motif, couture, parois, dessus, dessous, bordure, lissage, peau, angle_support, temp_buse, temp_plateau…",
        },
    },
}

TOOL_LIST = [
    {
        "type": "function",
        "function": {
            "name": n,
            "description": d,
            "parameters": {"type": "object", "properties": PROPS[n]},
        },
    }
    for n, d in SCHEMAS.items()
]


def run_tool(tool: str, args: dict[str, Any], name: str) -> dict[str, Any]:
    """One tool call, executed in the workshop itself. Returns what the model will read back."""
    if tool not in SCHEMAS:
        return {"erreur": f"outil inconnu « {tool} »"}
    if tool in FREE_TOOLS:  # no model needed: these make one
        try:
            return _catalogue(args) if tool == "catalogue_pieces" else _creer_piece(args)
        except (ValueError, OSError) as err:
            return {"erreur": str(err)[:300]}
    if not name:
        return {
            "erreur": "aucun modèle ouvert : crée une pièce (creer_piece) ou demande à "
            "l'utilisateur d'en choisir une dans la bibliothèque"
        }
    src = config.MODELS_DIR / name
    if not src.is_file():
        return {"erreur": f"« {name} » n'est plus dans la bibliothèque"}
    try:
        if tool == "fiche":
            return _fiche(src)
        if tool == "reparer":
            return repair.repair(src)
        if tool == "redimensionner":
            return _baked(
                src,
                scale=args.get("echelle"),
                height=args.get("hauteur"),
                tag=f"h{int(args['hauteur'])}mm" if args.get("hauteur") else "taille",
            )
        if tool == "faire_pivoter":
            return _baked(
                src, rotate=(args.get("rx", 0), args.get("ry", 0), args.get("rz", 0)), tag="tourne"
            )
        if tool == "orienter":
            o = orient.orientations(src)  # the six poses, best first, ~2 s once
            return {
                "poses": [
                    {
                        "pose": x["label"],
                        "rotation": x["rotate"],
                        "taille_mm": x["size_mm"],
                        "surplomb_mm2": x["surplomb"],
                        "contact_plaque_mm2": x["contact"],
                        "recommandee": x.get("recommandee", False),
                    }
                    for x in o[:3]
                ]
            }
        if tool == "percer_ou_ajouter":
            return _forme(src, args)
        if tool == "couper":
            return _couper(src, args)
        if tool == "grand_format":
            return _grand_format(src, args)
        return _trancher(src, args)
    except (ValueError, OSError, slicer.SliceError) as err:
        return {"erreur": str(err)[:200]}


# --- the conversation itself ---------------------------------------------------------------------

SYSTEM = (
    "Tu es l'expert de l'Atelier CC2, l'atelier d'impression 3D d'une Elegoo Centauri Carbon 2 "
    "multicolore (plateau 256x256 mm, Z 256, CANVAS 4 bobines, profils Elegoo integraux). Tu es un "
    "imprimeur 3D chevronné ET un designer d'objets : on vient te voir pour ta main (réparer, créer, "
    "modifier, améliorer) autant que pour ton œil.\n"
    "MÉTIER — tu connais l'impression FDM dans le détail et tu l'expliques simplement : orientation "
    "(surplombs au-delà de ~45°, contact plaque, pas besoin de supports intérieurs), supports "
    "(arbre, fin, solide, colonnes), tolérances fonctionnelles (jeu ~0,2 mm par côté pour un assemblage, "
    "trous horizontaux qui cagnent, passe un trou de vis à ~0,1-0,2 mm de plus que la vis), parois jamais "
    "sous ~0,8 mm, pics et pointes à adoucir, ponts courts, couches (0,2 mm standard : une gravure lisible "
    "demande ~1 mm de profondeur ou des bords nets), adhérence (bordure, brim) selon la surface de contact, "
    "les usages de l'atelier (décoratif, solide, détaillé, rapide, turbo) et les températures, calculées "
    "automatiquement d'après le filament de chaque bobine.\n"
    "ŒIL — tu juges et proposes comme un designer : proportions d'ensemble, rayons qui adoucissent les "
    "arêtes vives, biseaux qui lissent, gravures ni trop fines ni trop creuses, couleurs qui contrastent "
    "ou s'accordent (annonce le slot CANVAS qui ira), lisibilité à distance, sens avant-arrière d'une pièce, "
    "sécurité des arêtes qui touchent les mains.\n"
    "FAÇON DE TRAVAILLER — d'abord COMPRENDRE : l'utilisateur écrit en langage familier, parfois "
    "approximatif (« vire ça », « fais plus rond », « plus grand », « comme avant »). Interprète son "
    "INTENTION, pas ses mots littéraux : choisis toi-même les valeurs raisonnables (dimensions, "
    "position, tolérances, orientation) d'après la fiche et l'usage de la pièce, et énonce-les en une "
    "phrase après coup. Ne pose une question QUE si l'action est réellement impossible à deviner sans "
    "elle — au pire UNE seule, en proposant déjà ta réponse préférée. Ensuite AGIR : si le message "
    "demande une action, fais-la DANS cette même réponse en appelant l'outil (ou Blender) — jamais une "
    "fiche seule comme réponse, jamais « veux-tu que je… » : l'utilisateur demande, tu exécutes. Lance "
    "la fiche comme un outil muet quand tu ne connais pas encore le modèle ; elle n'apparaît jamais "
    "seule. Pour un travail en plusieurs étapes : annonce le plan en une phrase, puis enchaîne les "
    "outils. Tu conseilles SPONTANÉMENT l'étape suivante (poser, renforcer, éclaircir, colorier, "
    "trancher) et tu avertis franchement quand une idée imprimera mal — sans la faire quand même si "
    "elle est dangereuse pour la pièce ou la machine. Réponds en français, comme un collègue imprimeur : "
    "concis, concret, jamais plus de 4 phrases hors outils. "
    "EXEMPLES DE LECTURE — « vire la gravure » → Blender : mesure le creux, remplis-le en booléen "
    "au niveau exact de la surface saine, nouveau fichier lisse ; « plus grand » → +15 à 30 % par défaut, "
    "annonce la taille obtenue en mm ; « un trou ici » (zone ciblée) → percer_ou_ajouter cylindre au point "
    "exact, 6 mm de diamètre si rien n'est précisé ; « ça tiendra ? » → juge surplombs et contact plaque, "
    "dis-le franchement et propose la pose ; « fais plus rond » → Blender : congés sur les arêtes visées. "
    "Après un outil qui a créé un fichier, termine "
    "par le nouveau nom entre guillemets pour que l'interface l'affiche."
)


LAPP = (
    "L'APPLICATION QUE TU HABITES (atelier web sur le port 8787, API /lab/api) — comprends-la pour "
    "répondre juste : à gauche la bibliothèque (fichiers, vignettes, ajouts de pièces), au centre la "
    "vue 3D (tourner, mettre à la taille, miroir, déplacer/redimensionner les pièces d'un plateau, "
    "pinceau de couleurs, bouton « Cibler » qui attrape un point précis), à droite la préparation "
    "(poses conseillées, hauteur, réparation, analyse des couleurs et appariement des bobines CANVAS, "
    "réglages fins du tranchage), puis le bilan (temps, grammes, bobines déclarées, visualisation du "
    "G-code couche à couche, envoi à la CC2, suivi de progression, bilan de fin d'impression). tous "
    "ces gestes existent côté atelier : ce qui est dans tes OUTILS, fais-le toi-même sans demander ; "
    "ce qui manque passe par Blender (MCP) ou une phrase de conseil. L'utilisateur peut te CIBLER : "
    "un clic « Cibler » sur la vue 3D t'arrive en fin de message sous la forme [ZONE CIBLÉE …] — "
    "coordonnées du FICHIER en mm (Z = hauteur), avec un rayon : vise ce point exactement et dis ce "
    "que tu y vois et y fais ; avec « percer_ou_ajouter », recopie ces trois nombres telles quelles "
    "dans l'argument « zone », l'atelier fait la conversion au centre. Chaque fichier mesh que tu écris dans la bibliothèque est montré "
    "automatiquement dans la page (la vue 3D se recharge toute seule) : décris ton travail et son nom, "
    "sans demander de recharger. Si l'utilisateur regarde déjà un G-code, propose de revenir au modèle "
    "(l'assistant ne travaille pas sur du G-code)."
)


def chat(
    name: str,
    message: str,
    history: list[dict[str, str]] | None = None,
    conversation: str = "",
    emit=None,
) -> dict[str, Any]:
    """One turn: dispatch to the CLI brain, or to Mistral's API as configured/fallback.
    ``emit`` (a callable taking one dict) receives live activity events while the brain works."""
    if moteur() == "api" or (moteur() == "auto" and not cli_bin()):
        return chat_api(name, message, history, emit)
    return chat_cli(name, message, history, conversation, emit)


def chat_events(
    name: str, message: str, history: list[dict[str, str]] | None = None, conversation: str = ""
):
    """The same turn, as a generator of live events for the page's journal — the brain's own tool
    calls (Blender…), the workshop's tools, then a last ``{"type": "final", …}`` (or
    ``{"type": "erreur", "texte": …}``) carrying the ordinary ``chat()`` result."""
    q: queue.SimpleQueue = queue.SimpleQueue()

    def work() -> None:
        try:
            res = chat(name, message, history, conversation, emit=q.put)
            q.put({"type": "final", **res})
        except Exception as err:  # noqa: BLE001 — — one dict like the page's error shows
            q.put({"type": "erreur", "texte": str(err)})

    th = threading.Thread(target=work, daemon=True)
    th.start()
    while True:
        ev = q.get()
        yield ev
        if ev.get("type") in ("final", "erreur"):
            break
    th.join(timeout=5)


# --- engine 1: the local agent CLI (vibe -p), MCP servers included, no API key ---------------------

PROTO = (
    "PROTOCOLE. Les outils de l'atelier (fiche, creer_piece, trancher, grand_format…) ne sont PAS parmi tes "
    "outils natifs : ni run_typescript, ni une URL, ni le shell ne les atteignent. La SEULE façon de les "
    "faire exécuter est de répondre avec le JSON ci-dessous ; l'atelier les lance et te renvoie le résultat. "
    "Tes outils natifs (Blender par MCP, skills, sous-agents) servent au reste. "
    "Tu réponds UNIQUEMENT avec un objet JSON, sans rien d'autre autour :\n"
    '- pour faire exécuter un ou plusieurs outils de l\'atelier : {"outils": '
    '[{"outil": "<nom>", "arguments": {...}}, …]} (un seul suffit aussi : {"outil": …, "arguments": …})\n'
    '- pour répondre à l\'utilisateur : {"reponse": "<texte>"}'
)

CLISYSTEM = (
    SYSTEM + " " + LAPP + " TES SKILLS (chargées avec l'outil « skill », en silence, dès qu'elles "
    "servent — c'est là que vit ton savoir détaillé) : « cc2-impression3d » (métier FDM : orientation, "
    "supports, tolérances, couches, adhérence), « cc2-design » (l'œil designer : proportions, congés, "
    "couleurs CANVAS), « cc2-blender-cao » (la vraie CAO dans Blender, protocole complet de l'import "
    "à l'export vérifié), « cc2-orcaslicer » (OrcaSlicer : profils machine/qualité/filament CC2, "
    "températures automatiques, les réglages fins de l'outil trancher). TES SOUS-AGENTS (par « agents_spawn », en leur donnant le travail précis + "
    "les chemins dont ils ont besoin) : « blender-cao » (l'ouvrier CAO : il modélise dans Blender et "
    "exporte un PLY dans la bibliothèque — délègue-lui tout travail qui dépasse cylindre/pavé/boule), "
    "« vision » (il regarde la scène Blender ouverte et décrit ce qu'il voit — sers-t'y quand tu dois "
    "vérifier un résultat à l'œil sans polluer ton contexte). Tu disposes aussi des serveurs MCP du "
    "CLI (Blender quand le pont « blender » tourne) : ce que les outils de l'atelier ne savent pas "
    "faire passe par la skill cc2-blender-cao et le sous-agent blender-cao. Un fichier mesh que tu "
    "(ou un sous-agent) écris dans la bibliothèque recharge la vue 3D tout seul. " + PROTO
)


def _cli_detail(stderr: str) -> str:
    """The CLI's stderr as one short human reason: keyring noise dropped, recurring refusals explained
    in plain French with what to do."""
    lines = [line.strip() for line in (stderr or "").strip().splitlines() if line.strip()]
    lines = [line for line in lines if not line.startswith("Reading API keys")]
    txt = " ".join(lines)[-300:]
    low = txt.lower()
    if "subscription" in low or "not available" in low:
        txt = "le modèle demandé n'est pas dans ton offre CLI — vérifie l'offre ou lance « vibe login »"
    elif "login" in low or "unauthorized" in low or "401" in low:
        txt = "le CLI n'est plus connecté — lance « vibe login » dans un terminal"
    return txt or "sortie vide"


def _cli_message(stdout: str | list | None) -> str:
    """The final assistant text inside the transcript entries (the ``--output json`` export, or the
    entries collected line by line in streaming mode)."""
    if isinstance(stdout, str):
        try:
            entries = json.loads(stdout)
        except (ValueError, TypeError):
            return ""
    else:
        entries = stdout or []
    if not isinstance(entries, list):
        return ""
    for e in reversed(entries):
        if isinstance(e, dict) and e.get("role") == "assistant" and e.get("type") == "message":
            return "".join(
                b.get("text", "") for b in (e.get("content") or []) if isinstance(b, dict)
            )
    return ""


def _json_only(text: str) -> dict[str, Any]:
    """The protocol JSON in a reply, lenient around prose or code fences."""
    s = text.strip()
    if s.startswith("```"):
        s = s.strip("`").lstrip("json\n")
    try:
        v = json.loads(s)
        if isinstance(v, dict):
            return v
    except ValueError:
        pass
    i, j = s.find("{"), s.rfind("}")
    if 0 <= i < j:
        try:
            v = json.loads(s[i : j + 1])
            if isinstance(v, dict):
                return v
        except ValueError:
            pass
    return {}


def _scan_meshes() -> dict[str, float]:
    """The library's mesh files (name -> mtime), to spot what a CLI run created or overwrote outside
    the workshop's tools (a Blender export…)."""
    out: dict[str, float] = {}
    try:
        for p in config.MODELS_DIR.iterdir():
            if p.suffix.lower() in mesh.MESH_EXT:
                with contextlib.suppress(OSError):
                    out[p.name] = p.stat().st_mtime
    except OSError:
        pass
    return out


def _sidecar_ply(name: str) -> str | None:
    """A PLY copy with the colours kept, for Blender's native importer (its 3MF one is absent)."""
    try:
        import tempfile as _tf

        d = Path(_tf.gettempdir()) / "cc2-ply"
        d.mkdir(exist_ok=True)
        out = d / f"{Path(name).stem}.ply"
        if out.exists() and out.stat().st_mtime >= config.MODELS_DIR.joinpath(name).stat().st_mtime:
            return str(out)
        mesh.load(config.MODELS_DIR / name).export(out)
        return str(out)
    except (OSError, ValueError, RuntimeError):
        return None


def chat_cli(
    name: str,
    message: str,
    history: list[dict[str, str]] | None = None,
    conversation: str = "",
    emit=None,
) -> dict[str, Any]:
    """One or more headless CLI runs, inside ONE CLI session when ``conversation`` is given (``--resume``):
    the context (fiche, history, previous rounds) stays on the CLI side, each extra round only carries the
    new bit — the main speed lever. Native tools switched off; MCP servers (Blender…) stay approved.
    ``emit``: live activity events (the CLI's own tool calls, the workshop's) for the page's journal.
    """
    bin_path = cli_bin()
    if not bin_path:
        raise ValueError(
            f"le CLI « {_conf().get('commande', 'vibe')} » est introuvable (moteur = cli)"
        )
    cur = name
    outils: list[str] = []
    continued = 0
    checked = False  # one correction round when the reply names a file that does not exist
    session: str = _CLI_SESSIONS.get(conversation, "") if conversation else ""
    base = (
        _scan_meshes()
    )  # what the library held before the turn: the diff shows the agent's own exports
    maj = False

    outils_txt = "".join(f"- {n} — {d}\n" for n, d in SCHEMAS.items())
    props_txt = "".join(
        f"- {n} : arguments {json.dumps(PROPS[n], ensure_ascii=False)}\n"
        for n in SCHEMAS
        if PROPS[n]
    )
    # cold-start prompt: fiche of the current model + tool table; afterwards the session already knows it
    side = _sidecar_ply(cur) if cur else None  # colours kept: Blender's native PLY importer
    head = (
        (
            f"BIBLIOTHÈQUE. Modèle courant : « {cur} », chemin complet {config.MODELS_DIR / cur} "
            "(un fichier « fichier » rendu par un outil est {dossier}/{fichier} ; tout outil qui modifie écrit "
            f"dans le dossier {config.MODELS_DIR}). Sa fiche : {json.dumps(_fiche(config.MODELS_DIR / cur), ensure_ascii=False)}\n"
            if cur
            else f"BIBLIOTHÈQUE : le dossier {config.MODELS_DIR}. {NO_MODEL} "
            f"Catalogue (clé = pièce (réglages)) : {catalogue_line()}. Appelle directement « creer_piece » "
            "avec la clé et les réglages voulus ; « catalogue_pieces » avec `piece` donne les limites.\n"
        )
        + (
            f"Pour l'importer dans Blender, une copie PLY préparée par l'atelier est là : {side}.\n"
            if side
            else ""
        )
        + f"OUTILS DE L'ATELIER :\n{outils_txt}"
        + (f"Détail des arguments :\n{props_txt}" if props_txt else "")
        + "\n"
    )
    with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False) as tf:
        tf.write(CLISYSTEM)
        system_file = tf.name
    talk = "".join(
        f"{'Utilisateur' if h.get('role') == 'user' else 'Toi'}: {str(h.get('content', ''))[:1200]}\n"
        for h in (history or [])[-8:]
        if h.get("role") in ("user", "assistant") and h.get("content")
    )
    talk += f"Utilisateur: {message[:2000]}\n"
    extra = []  # CLI tuning: model alias, thinking level
    if _conf().get("modele_cli"):
        extra += ["--model", str(_conf()["modele_cli"])]
    extra += ["--thinking", str(_conf().get("reflexion", "off"))]

    def _spawn_stream(args: list[str]) -> tuple[list, Any]:
        """The same run as a streaming CLI output: each stdout line is a transcript entry, collected
        here while the CLI's tool calls (Blender…) go out through ``emit`` — nothing blocks on a
        whole capture, and the deadline still kills the run."""
        args = list(args)
        i = args.index("--output")
        args[i + 1] = "streaming"
        with tempfile.TemporaryFile(mode="w+", encoding="utf-8") as ef:
            sp = subprocess.Popen(  # noqa: S603 — CLI binary from the user's config
                args,
                stdout=subprocess.PIPE,
                stderr=ef,
                cwd=str(config.MODELS_DIR.parent),
                env=dict(_CLI_ENV.items()),
            )
            entries: list[dict[str, Any]] = []
            sel = selectors.DefaultSelector()
            sel.register(sp.stdout, selectors.EVENT_READ)
            fd = sp.stdout.fileno()
            deadline = time.monotonic() + CLI_TIMEOUT
            buf = ""
            try:
                while True:
                    remain = deadline - time.monotonic()
                    if remain <= 0:
                        sp.kill()
                        sp.wait(10)
                        raise subprocess.TimeoutExpired(args[0], CLI_TIMEOUT)
                    if not sel.select(min(remain, 2.0)):
                        continue
                    chunk = os.read(fd, 65536)
                    if not chunk:
                        break
                    buf += chunk.decode("utf-8", "replace")
                    while "\n" in buf:
                        line, buf = buf.split("\n", 1)
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            e = json.loads(line)
                        except (ValueError, TypeError):
                            continue
                        if not isinstance(e, dict):
                            continue
                        entries.append(e)
                        if e.get("type") == "effect":  # the CLI calls a tool (Blender…)
                            tgt = str(
                                (e.get("detail") or {}).get("toolName") or e.get("title") or ""
                            )
                            if tgt:
                                emit({"type": "cli", "cible": tgt})
            finally:
                sel.close()
                if sp.poll() is None:
                    sp.kill()
                    sp.wait(10)
            ef.seek(0)
            err = ef.read()
        return entries, SimpleNamespace(stdout="", stderr=err, returncode=sp.returncode)

    def _spawn(prompt: str, with_session: str) -> tuple[list | None, Any]:
        # native tools off (the workshop does the files itself); skills and sub-agents stay available,
        # MCP servers (Blender…) stay approved
        off = [
            x
            for k in (
                "bash",
                "read_file",
                "write_file",
                "edit",
                "sleep",
                "ask_user_question",
                "process_start",
                "process_write",
                "process_stop",
                "process_output",
                "process_list",
            )
            for x in ("--disabled-tools", k)
        ]
        args = [
            bin_path,
            "-p",
            prompt,
            "--output",
            "json",
            "--max-turns",
            "12",
            "--approval-policy",
            "auto-approve",
            *off,
        ]
        if (
            with_session
        ):  # a resumed run keeps its own system prompt, context, model and thinking level
            args += [
                "--resume",
                with_session,
            ]  # (vibe refuses --model/--thinking on a resumed session)
        else:
            args += [*extra, "--system-prompt-file", system_file]
        if emit:  # live mode: one CLI run, events out as they happen
            return _spawn_stream(args)
        sp = subprocess.run(  # noqa: S603 — CLI binary from the user's config
            args,
            capture_output=True,
            text=True,
            timeout=CLI_TIMEOUT,
            cwd=str(config.MODELS_DIR.parent),
            env=dict(_CLI_ENV.items()),
        )
        entries = None
        with contextlib.suppress(ValueError, TypeError):
            entries = json.loads(sp.stdout)
        return entries, sp

    prompt = head + "ÉCHANGE.\n" + talk
    vu: dict[str, str] = (
        {}
    )  # (outil+réglages) -> résultat : le même appel ne tourne jamais deux fois
    try:
        for _ in range(TOOL_ROUNDS * 2):
            if emit:
                emit(
                    {
                        "type": "etape",
                        "texte": (
                            "il reprend la session" if session else "il lit la pièce et réfléchit"
                        ),
                    }
                )
            entries, sp = _spawn(prompt, session)
            if entries is None:
                if session:  # the CLI session is gone: rebuild cold, once
                    session = ""
                    prompt = head + "ÉCHANGE.\n" + talk
                    continue
                raw = ""
            for e in reversed(entries):  # keep the CLI session warm inside this call
                if isinstance(e, dict) and e.get("sessionId"):
                    session = str(e["sessionId"])
                    if conversation:
                        _CLI_SESSIONS[conversation] = session
                        while len(_CLI_SESSIONS) > 50:
                            _CLI_SESSIONS.pop(next(iter(_CLI_SESSIONS)))
                    break
            raw = _cli_message(entries)
            j = _json_only(raw)
            calls = (
                j.get("outils")
                if isinstance(j.get("outils"), list)
                else (
                    [{"outil": j["outil"], "arguments": j.get("arguments", {})}]
                    if "outil" in j
                    else []
                )
            )
            if calls:
                last = ""
                nouveau = False
                for c in calls:
                    if not isinstance(c, dict):
                        continue
                    outil_c = c.get("outil")
                    if isinstance(
                        outil_c, dict
                    ):  # a nested {"outil": {"outil": …}} — read it inside
                        c, outil_c = dict(outil_c), outil_c.get("outil")
                    if not isinstance(outil_c, str) or not outil_c:
                        continue
                    args_c = c.get("arguments") if isinstance(c.get("arguments"), dict) else {}
                    sig = (
                        (
                            "" if outil_c in FREE_TOOLS else cur
                        )  # making a part twice is a repeat too
                        + " | "
                        + outil_c
                        + " "
                        + json.dumps(args_c, sort_keys=True, ensure_ascii=False)
                    )
                    if sig in vu:  # déjà tourné : on rejoue le résultat, sans relancer
                        last = f"l'outil {outil_c} avait déjà tourné et a rendu {vu[sig]}"
                        continue
                    vu[sig] = ""
                    nouveau = True
                    tool = outil_c
                    args = args_c
                    outils.append(tool)
                    if emit:
                        emit({"type": "outil", "outil": tool})
                    out = run_tool(tool, dict(args), cur)
                    vu[sig] = json.dumps(out, ensure_ascii=False)[:2500]
                    fresh = out.get("fichier") or out.get("name")
                    if fresh and fresh != cur and config.MODELS_DIR.joinpath(fresh).exists():
                        cur = fresh  # the conversation follows the new file
                        if emit:
                            emit({"type": "outil_ok", "outil": tool, "fichier": cur})
                    last = f"l'outil {tool} a rendu {vu[sig]}"
                if not nouveau:  # the brain loops on a tool it already ran: force the answer
                    prompt = (
                        "Résultats DEJA obtenus, ne rappelle AUCUN outil : "
                        + last
                        + '. Termine selon le protocole avec une {"reponse": …} qui porte ce résultat.'
                    )
                    continue
                side2 = _sidecar_ply(cur) if cur else None
                prompt = (
                    "Résultat des outils de l'atelier : "
                    + last
                    + (
                        ". Modèle courant : « " + cur + " »"
                        if cur
                        else ". Toujours aucun modèle ouvert"
                    )
                    + (f", copie PLY pour Blender : {side2}." if side2 else "")
                    + " Continue selon le protocole."
                )
                continue
            reply = str(j.get("reponse")) if "reponse" in j else raw
            if reply.strip():
                if "turn_limit" in sp.stderr and continued < 2:
                    # the CLI ran out of inner turns mid-work (Blender keeps its scene): let it resume
                    continued += 1
                    if emit:
                        emit({"type": "etape", "texte": "il continue (limite de tours du CLI)"})
                    prompt = (
                        "Tu as été coupé par la limite de tours en plein travail ("
                        + reply[:600]
                        + "). Continue exactement ce travail, puis réponds selon le protocole."
                    )
                    continue
                # what the agent made OUTSIDE the workshop's tools counts too (Blender's export…):
                # the conversation adopts the newest mesh file it created or overwrote, and the page
                # reloads the 3D view (``recharge``) even when the name stayed the same
                now = _scan_meshes()
                made = [n for n, m in now.items() if base.get(n) != m and n != cur]
                if made:
                    cur = max(made, key=lambda n: now[n])
                    maj = True
                    if emit:
                        emit({"type": "recharge", "fichier": cur})
                elif now.get(cur) != base.get(cur):
                    maj = True
                    if emit:
                        emit({"type": "recharge", "fichier": cur})
                ghosts = ghost_files(reply)
                if ghosts and not checked:
                    checked = True
                    if emit:
                        emit({"type": "etape", "texte": "l'atelier vérifie les fichiers annoncés"})
                    prompt = (
                        "VÉRIFICATION DE L'ATELIER : "
                        + ", ".join(f"« {g} »" for g in ghosts)
                        + f" n'existe pas dans la bibliothèque ({config.MODELS_DIR}) : tu ne l'as PAS créé. "
                        "Crée-le vraiment (creer_piece, ou un export Blender dans ce dossier), ou dis "
                        "honnêtement ce qui n'a pas marché. Réponds selon le protocole."
                    )
                    continue
                if ghosts:
                    reply += (
                        "\n\n⚠ Vérification de l'atelier : "
                        + ", ".join(f"« {g} »" for g in ghosts)
                        + " n'existe pas dans la bibliothèque."
                    )
                return {"reply": reply[:4000], "file": cur, "outils": outils, "maj": maj}
            if session and sp.returncode != 0:  # broken session: restart cold once
                session = ""
                prompt = head + "ÉCHANGE.\n" + talk
                continue
            raise ValueError(f"le moteur CLI n'a pas répondu : {_cli_detail(sp.stderr)}")
        return {
            "reply": "Je me suis arrêté là : la boîte à outils est allée trop loin pour une seule demande. "
            "Reformule plus court, je continue.",
            "file": cur,
            "outils": outils,
        }
    except subprocess.TimeoutExpired as err:
        raise ValueError("le moteur CLI n'a pas répondu dans le délai (5 min par tour)") from err
    finally:
        Path(system_file).unlink(missing_ok=True)


SLICE_BRAIN_TIMEOUT = 120  # seconds for the focused slicer-head run: read, decide, justify


def slice_brain(
    name: str,
    contexte: dict[str, Any],
    qualities: list[str] | None = None,
    spec: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """The brain as the slicer's head: reading the part's sheet and the advisor's analysis, it picks
    quality, infill, supports, fine settings and the pose, and justifies. One focused CLI run with the
    tools switched off — the sheet and the analysis are its eyes on the mesh, no tangent through Blender.
    Returns only validated choices: anything the page would refuse is dropped (the current values stay).
    """
    bin_path = cli_bin()
    if not bin_path:
        raise ValueError(
            f"le CLI « {_conf().get('commande', 'vibe')} » est introuvable (moteur = cli)"
        )
    qualities = qualities or []
    spec = spec or {}
    choix_val = {
        c["name"]: [str(o["value"]) for o in c["options"]] for c in spec.get("choices", [])
    }
    intervalles = {
        str(n["name"]): (float(n["min"]), float(n["max"]))
        for grp in ("numbers", "numbers_fil", "temps")
        for n in spec.get(grp, [])
    }
    system = (
        "TU ES LE TRANCHEUR de l'atelier. Une pièce va être découpée pour une Elegoo Centauri Carbon 2 "
        "(buse 0,4, profils Elegoo, températures automatiques d'après le filament). On te donne la fiche de "
        "la pièce, la matière, l'usage demandé et l'analyse du conseiller (surplombs, adhérence, parois fines).\n"
        "Décide comme un imprimeur expérimenté qui veut LA MEILLEURE pièce du premier coup :\n"
        "- qualite : un profil de couches parmi "
        + (", ".join(qualities) or "le profil par défaut")
        + " — "
        "fin si détails/pentes visibles, épais si forme simple et pièce robuste, intermédiaire sinon ;\n"
        "- remplissage : % entre 0 et 100 — léger (5-15) pour déco/figurine, plus dense (20-40) pour pièce qui force, "
        "plus si la pièce doit être pleine ;\n"
        "- supports : aucun|arbre|arbre_fin|arbre_solide|colonnes — aucun si l'analyse ne signale rien à soutenir ;\n"
        "- reglages : DICT FIN mais parcimonieux — seulement ce qui vaut le coup pour CETTE pièce "
        "(clés valides : "
        + (", ".join(sorted(choix_val) + sorted(intervalles)) or "aucun")
        + ") ; dict vide sinon ;\n"
        "- rotate : [rx, ry, rz] ou null — propose seulement si l'analyse le réclame vivement (multiples de 90) ;\n"
        "- usage : un de "
        + ", ".join(list(printprep.USAGES))
        + " — celui qui colle vraiment à la pièce ;\n"
        "- explication : 1-2 phrases courtes et concrètes en français, pour l'utilisateur.\n"
        'RÉPONDS UNIQUEMENT par le JSON du protocole : {"reponse": {"qualite": …, "remplissage": …, '
        '"supports": …, "reglages": …, "rotate": …, "usage": …, "explication": …}} — aucun outil, aucun texte hors JSON.'
    )
    head = (
        "PIÈCE : "
        + json.dumps(_fiche(config.MODELS_DIR / name), ensure_ascii=False)
        + "\n"
        + "CONTEXTE DU TRANCHAGE : "
        + json.dumps(
            {k: contexte.get(k) for k in ("filaments", "usage", "rotate", "height_mm", "split")},
            ensure_ascii=False,
        )
        + "\n"
        + "CHOIX ACTUELS DANS LE PANNEAU (l'utilisateur a la main dessus ; ne change que ce qui est mieux) : "
        + json.dumps(contexte.get("actuel", {}), ensure_ascii=False)
        + "\n"
        + "ANALYSE DU CONSEILLER : "
        + json.dumps(
            {
                "verdict": contexte.get("verdict"),
                "points": [
                    {"titre": w.get("title"), "grave": w.get("level"), "détail": w.get("detail")}
                    for w in (contexte.get("warnings") or [])[:8]
                ],
            },
            ensure_ascii=False,
        )
    )
    with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False) as tf:
        tf.write(system)
        system_file = tf.name
    off = [
        x
        for k in (
            "bash",
            "read_file",
            "write_file",
            "edit",
            "sleep",
            "ask_user_question",
            "skill",
            "agents_spawn",
            "agents_send",
            "process_start",
            "process_write",
            "process_stop",
            "process_output",
            "process_list",
        )
        for x in ("--disabled-tools", k)
    ]
    extra = []
    if _conf().get("modele_cli"):
        extra += ["--model", str(_conf()["modele_cli"])]
    extra += ["--thinking", str(_conf().get("reflexion", "off"))]
    args = [
        bin_path,
        "-p",
        head + "\nRenvoie maintenant ton JSON.",
        "--output",
        "json",
        "--max-turns",
        "4",
        "--approval-policy",
        "auto-approve",
        *off,
        *extra,
        "--system-prompt-file",
        system_file,
    ]
    try:
        sp = subprocess.run(  # noqa: S603 — CLI binary from the user's config
            args,
            capture_output=True,
            text=True,
            timeout=SLICE_BRAIN_TIMEOUT,
            cwd=str(config.MODELS_DIR.parent),
            env=dict(_CLI_ENV.items()),
        )
    except subprocess.TimeoutExpired as err:
        raise ValueError(
            "le tranchage IA n'a pas répondu à temps, tranche sans IA ou réessaie"
        ) from err
    finally:
        Path(system_file).unlink(missing_ok=True)
    raw = _cli_message(sp.stdout)
    j = _json_only(raw)
    rep = j.get("reponse") if isinstance(j.get("reponse"), dict) else j
    if not rep and sp.returncode != 0:
        raise ValueError(f"le tranchage IA n'a pas répondu : {_cli_detail(sp.stderr)}")
    out: dict[str, Any] = {}

    def _qualite(v: Any) -> None:
        hit = next((q for q in qualities if str(v).strip().lower() == q.lower()), None) or next(
            (q for q in qualities if str(v).strip().lower().startswith(q.split(" ")[0] + "mm")),
            None,
        )
        if hit:
            out["qualite"] = hit

    if isinstance(rep, dict):
        if rep.get("qualite"):
            _qualite(rep["qualite"])
        with contextlib.suppress(TypeError, ValueError):
            out["remplissage"] = max(0, min(100, int(rep.get("remplissage"))))
        if str(rep.get("supports", "")).strip() in (
            "aucun",
            "arbre",
            "arbre_fin",
            "arbre_solide",
            "colonnes",
        ):
            out["supports"] = str(rep["supports"]).strip()
        if rep.get("usage") in printprep.USAGES:
            out["usage"] = rep["usage"]
        reg = rep.get("reglages")
        if isinstance(reg, dict):
            garde: dict[str, Any] = {}
            for k, v in reg.items():
                if k in choix_val and str(v) in choix_val[k]:
                    garde[k] = str(v)
                elif k in intervalles:
                    try:
                        x = float(v)
                    except (TypeError, ValueError):
                        continue
                    lo, hi = intervalles[k]
                    if lo <= x <= hi:
                        garde[k] = x
            if garde:
                out["reglages"] = garde
        rot = rep.get("rotate")
        if isinstance(rot, (list, tuple)) and len(rot) == 3:
            with contextlib.suppress(TypeError, ValueError):
                out["rotate"] = [float(a) for a in rot]
        exp = str(rep.get("explication", "")).strip()
        if exp:
            out["explication"] = exp[:500]
    return out


# --- engine 2: Mistral API (kept as fallback; needs an API key) -------------------------------------

# The app the API brain lives in: the same picture LAPP gives the CLI brain, minus everything only
# the CLI can do (Blender, skills, sub-agents — API Mistral has neither).
APPLI = (
    "L'APPLICATION QUE TU HABITES (atelier web sur le port 8787, API /lab/api) — comprends-la pour "
    "répondre juste : à gauche la bibliothèque (fichiers, vignettes, ajouts de pièces), au centre la "
    "vue 3D (tourner, mettre à la taille, miroir, déplacer/redimensionner les pièces d'un plateau, "
    "pinceau de couleurs, bouton « Cibler » qui attrape un point précis), à droite la préparation "
    "(poses conseillées, hauteur, réparation, analyse des couleurs et appariement des bobines CANVAS, "
    "réglages fins du tranchage), puis le bilan (temps, grammes, bobines déclarées, visualisation du "
    "G-code couche à couche, envoi à la CC2, suivi de progression, bilan de fin d'impression). Tous "
    "ces gestes existent côté atelier : ce qui est dans tes OUTILS, fais-le toi-même sans demander ; "
    "ce qui manque reste une phrase de conseil. L'utilisateur peut te CIBLER : un clic « Cibler » sur "
    "la vue 3D t'arrive en fin de message sous la forme [ZONE CIBLÉE …] — coordonnées du FICHIER en mm "
    "(Z = hauteur), avec un rayon : vise ce point exactement et dis ce que tu y vois et y fais ; avec "
    "« percer_ou_ajouter », recopie ces trois nombres telles quelles dans l'argument « zone », "
    "l'atelier fait la conversion au centre. Chaque fichier mesh qu'un outil écrit dans la bibliothèque "
    "est montré automatiquement dans la page (la vue 3D se recharge toute seule) : décris ton travail "
    "et son nom, sans demander de recharger. Si l'utilisateur regarde déjà un G-code, propose de revenir "
    "au modèle (l'assistant ne travaille pas sur du G-code)."
)


def chat_api(
    name: str, message: str, history: list[dict[str, str]] | None = None, emit=None
) -> dict[str, Any]:
    """One turn with Mistral's function calling: its tool calls run here in the workshop, it answers.
    The Mistral twin of ``chat_cli``, minus Blender: same file following (a later tool of the same round
    works on the new file), same de-dup of an already-run tool, and a forced plain answer when it would
    only repeat tools. ``emit`` receives the same live events as the CLI engine."""
    key = api_key()
    if not key:
        raise ValueError(
            'pas de clé API : ajoute [assistant] api_key = "ta-clé" dans config.toml (moteur : Mistral)'
        )
    cur = name
    outils: list[str] = []
    vu: dict[str, str] = (
        {}
    )  # (fichier|outil+arguments) -> résultat : le même appel ne tourne jamais deux fois
    msgs: list[dict[str, Any]] = [
        {"role": "system", "content": SYSTEM + " " + APPLI},
        {
            "role": "system",
            "content": (
                f"FICHE du modèle courant « {cur} » : "
                + json.dumps(_fiche(config.MODELS_DIR / cur), ensure_ascii=False)
                if cur
                else NO_MODEL
            ),
        },
    ]
    for h in (history or [])[-8:]:
        if h.get("role") in ("user", "assistant") and h.get("content"):
            msgs.append({"role": h["role"], "content": str(h["content"])[:1200]})
    msgs.append({"role": "user", "content": message[:2000]})
    rejoue = False  # a round that only repeated already-run tools (or ran none): next call must answer in words
    nudged = False  # one nudge when the model goes silent after its tools; then a stated fallback
    for _ in range(TOOL_ROUNDS):
        rsp = httpx.post(
            API,
            headers={"Authorization": f"Bearer {key}"},
            timeout=120,
            json={
                "model": model_name(),
                "messages": msgs,
                "tools": TOOL_LIST,
                "tool_choice": "none" if rejoue else "auto",
                "temperature": 0.2,
                "max_tokens": 1200,
            },
        )
        if rsp.status_code != 200:
            raise ValueError(f"Mistral refuse ({rsp.status_code}) : {rsp.text[:150]}")
        r = rsp.json()["choices"][0]["message"]
        rejoue = False
        if not r.get("tool_calls"):
            reply = str(r.get("content") or "").strip()
            if not reply and outils and not nudged:
                nudged = True  # the model shrugs after its tools: one nudge, then speak
                rejoue = True
                msgs.append(
                    {
                        "role": "user",
                        "content": "Les outils ont tourné et leurs résultats sont dans "
                        "l'échange. Termine maintenant par ta réponse en texte à l'utilisateur.",
                    }
                )
                continue
            if not reply:
                reply = (
                    "Fait (" + " · ".join(outils[-2:]) + "), mais je n'ai pas su conclure "
                    "— relance ta demande, je repars des résultats."
                )
            if ghosts := ghost_files(reply):  # never let a made-up file name stand
                reply += (
                    "\n\n⚠ Vérification de l'atelier : "
                    + ", ".join(f"« {g} »" for g in ghosts)
                    + " n'existe pas dans la bibliothèque."
                )
            return {"reply": reply[:4000], "file": cur, "outils": outils}
        msgs.append(r)
        nouveau = False
        for tc in r["tool_calls"]:
            fname = tc["function"]["name"]
            try:
                args_c = json.loads(tc["function"]["arguments"] or "{}")
            except ValueError:
                args_c = {}
            if not isinstance(args_c, dict):
                args_c = {}
            sig = (
                ("" if fname in FREE_TOOLS else cur)
                + " | "
                + fname
                + " "
                + json.dumps(args_c, sort_keys=True, ensure_ascii=False)
            )
            if sig in vu:  # déjà tourné : le résultat est rejoué, rien ne relance
                msgs.append(
                    {
                        "role": "tool",
                        "tool_call_id": tc["id"],
                        "content": "l'outil " + fname + " avait déjà tourné et a rendu " + vu[sig],
                    }
                )
                continue
            nouveau = True
            vu[sig] = ""
            outils.append(fname)
            if emit:
                emit({"type": "outil", "outil": fname})
            out = run_tool(fname, dict(args_c), cur)
            res = json.dumps(out, ensure_ascii=False)[:4000]
            vu[sig] = res
            fresh = out.get("fichier") or out.get("name")
            if fresh and fresh != cur and config.MODELS_DIR.joinpath(fresh).exists():
                cur = fresh  # the next tool of this round works on the new file
                if emit:
                    emit({"type": "outil_ok", "outil": fname, "fichier": cur})
            msgs.append({"role": "tool", "tool_call_id": tc["id"], "content": res})
        if not nouveau:  # Mistral loops on tools it already ran: force the answer
            rejoue = True
    return {
        "reply": "Je me suis arrêté là : la boîte à outils est allée trop loin pour une seule demande. "
        "Reformule plus court, je continue.",
        "file": cur,
        "outils": outils,
    }
