#!/usr/bin/env python3
"""Bench: for a few real models, the code's own cut plan against the plan chosen with the vision (vibe).

    python scripts/bench_vision.py --hauteur 450 "Cloud Strife.3mf" other.glb ... [--out rapport.md]

Names are looked up in the workshop's library (config MODELS_DIR). Nothing is written to the library and
nothing is sliced; each model costs one vision call (about a minute). The report is Markdown: per model the
planes and pieces of both plans, whether the vision's choice was followed (or why not), its comment, and the
times, so the two can be compared by eye.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path
from typing import Any

from elegoo_lab import config, grandformat


def plans_text(p: dict[str, Any]) -> str:
    return (
        ", ".join(
            f"{x['axe']}={x['mm']:g}"
            + (f" (∠{x['angle']:+g}°→{x['vers']})" if x.get("angle") else "")
            for x in p["plans"]
        )
        or "aucune coupe"
    )


def run_one(src: Path, hauteur: float, biais: bool) -> dict[str, Any]:
    out: dict[str, Any] = {"modele": src.name, "hauteur": hauteur}
    t = time.time()
    try:
        code = grandformat.plan(src, hauteur, biais=biais)
        out["code"] = {
            "plans": plans_text(code),
            "pieces": len(code["pieces"]),
            "ok": code["ok"],
            "alertes": [a["message"] for a in code["alertes"]],
            "s": round(time.time() - t, 1),
        }
        t = time.time()
        vis = grandformat.plan(src, hauteur, biais=biais, vision=True)
        out["vision"] = {
            "plans": plans_text(vis),
            "pieces": len(vis["pieces"]),
            "ok": vis["ok"],
            "alertes": [a["message"] for a in vis["alertes"]],
            "s": round(time.time() - t, 1),
            **vis.get("vision", {}),
        }
    except (ValueError, OSError) as err:
        out["erreur"] = str(err)[:300]
    return out


def report(rows: list[dict[str, Any]]) -> str:
    lines = [
        "# Banc de test : coupes avec le code seul contre code + vision",
        "",
        "| Modèle | Hauteur | Code seul | Code + vision | Avis suivi |",
        "|---|---|---|---|---|",
    ]
    for r in rows:
        if "erreur" in r:
            lines.append(f"| {r['modele']} | {r['hauteur']:g} mm | erreur : {r['erreur']} | | |")
            continue
        c, v = r["code"], r["vision"]
        same = "identique" if c["plans"] == v["plans"] else "différent"
        followed = f"oui ({same})" if v.get("utilisee") else f"non : {v.get('repli', '?')}"
        lines.append(
            f"| {r['modele']} | {r['hauteur']:g} mm | {c['plans']} ({c['pieces']} pièces, {c['s']} s) | {v['plans']} ({v['pieces']} pièces, {v['s']} s) | {followed} |"
        )
    lines += ["", "## Détail"]
    for r in rows:
        if "erreur" in r:
            continue
        v = r["vision"]
        lines += [
            f"### {r['modele']}",
            f"- Ce que l'IA voit : {v.get('modele', '—')}",
            f"- Son conseil : {v.get('commentaire', '—')}",
        ]
        lines += [f"- Refus {x.get('id')} : {x.get('raison')}" for x in v.get("refus", [])]
        lines += [f"- Alerte (code seul) : {a}" for a in r["code"]["alertes"]]
        lines += [f"- Alerte (vision) : {a}" for a in v["alertes"]]
        lines.append("")
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("models", nargs="+", help="file names in the library, or paths")
    ap.add_argument("--hauteur", type=float, default=450.0, help="final height in mm (default 450)")
    ap.add_argument("--sans-biais", action="store_true", help="aligned planes only")
    ap.add_argument("--out", type=Path, help="write the Markdown report here (default: print it)")
    a = ap.parse_args()
    rows = []
    for name in a.models:
        p = Path(name)
        src = p if p.is_file() else config.MODELS_DIR / name
        if not src.is_file():
            rows.append({"modele": name, "hauteur": a.hauteur, "erreur": "fichier introuvable"})
            continue
        print(f"… {src.name}", file=sys.stderr)
        rows.append(run_one(src, a.hauteur, not a.sans_biais))
    text = report(rows)
    if a.out:
        a.out.write_text(text)
        print(f"rapport : {a.out}", file=sys.stderr)
    else:
        print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
