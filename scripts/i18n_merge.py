"""Adds translations to src/elegoo_lab/web/i18n/en.json: python scripts/i18n_merge.py extra.json [extra2.json …]."""
import json
import sys
from pathlib import Path

f = Path(__file__).resolve().parents[1] / "src/elegoo_lab/web/i18n/en.json"
d = json.loads(f.read_text())
pats = {p[0]: p[1] for p in d["patterns"]}
for x in sys.argv[1:]:
    e = json.loads(Path(x).read_text())
    d["exact"].update(e.get("exact", {}))
    for fr, en in e.get("patterns", []):
        pats[fr] = en
# most specific first: the more literal text a pattern has, the earlier it is tried
d["patterns"] = sorted(([k, v] for k, v in pats.items()), key=lambda p: (-len(p[0].replace("{}", "")), p[0]))
d["exact"] = dict(sorted(d["exact"].items()))
f.write_text(json.dumps(d, ensure_ascii=False, indent=0))
print(len(d["exact"]), "exacts,", len(d["patterns"]), "motifs")
