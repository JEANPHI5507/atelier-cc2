"""Lists the French texts the interface can show: HTML text and attributes, JS string literals and templates
(split at HTML tags, ${…} becoming {}), Python strings that reach the user. Output: one JSON list of strings."""

import ast
import json
import re
import sys
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "src/elegoo_lab/web"
FR = re.compile(r"[A-Za-zÀ-ÿ]{2}")
FRENCH_HINT = re.compile(r"[éèêàùçôîâ«»]|\b(le|la|les|des|une?|du|de|et|ou|pas|sur|pour|avec|dans|est|sont|ton|ta|tes)\b", re.I)
out: dict[str, str] = {}   # text -> first source


def add(text: str, src: str) -> None:
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) < 2 or not FR.search(text) or text.startswith(("http", "#", "/", "data:", "rgba", "var(")):
        return
    if re.fullmatch(r"[\w.\-/{}]+", text) and not FRENCH_HINT.search(text):   # identifiers, ids, file names
        return
    out.setdefault(text, src)


class Html(HTMLParser):
    def __init__(self, src):
        super().__init__(); self.src = src; self.skip = 0
    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"): self.skip += 1
        for k, v in attrs:
            if k in ("title", "placeholder", "aria-label", "alt", "data-cap", "label") and v: add(v, self.src)
    def handle_endtag(self, tag):
        if tag in ("script", "style"): self.skip = max(0, self.skip - 1)
    def handle_data(self, data):
        if not self.skip: add(data, self.src)


def html_fragments(text: str, src: str) -> None:
    """A JS string that holds HTML: its text pieces between tags, and its attribute values."""
    for m in re.finditer(r'(?:title|placeholder|aria-label|alt)="([^"]*)"', text):
        add(m.group(1), src)
    for piece in re.split(r"<[^>]*>", text):
        add(piece, src)


for f in sorted(WEB.glob("*.html")):
    if f.name.startswith("_"): continue
    Html(f.name).feed(f.read_text())
    for m in re.finditer(r"<script(?![^>]*src)[^>]*>(.*?)</script>", f.read_text(), re.S):
        pass

JS_STR = re.compile(r"""'((?:[^'\\\n]|\\.)*)'|"((?:[^"\\\n]|\\.)*)"|`((?:[^`\\]|\\.)*)`""", re.S)
for f in sorted((WEB / "js").glob("*.js")):
    src = f"js/{f.name}"
    for m in JS_STR.finditer(f.read_text()):
        s = next(g for g in m.groups() if g is not None)
        s = s.replace("\\'", "'").replace('\\"', '"').replace("\\n", " ")
        if m.group(3) is not None:      # template: ${…} -> {}
            depth, buf, i = 0, [], 0
            while i < len(s):
                if s.startswith("${", i) and depth == 0:
                    j, d = i + 2, 1
                    while j < len(s) and d:
                        d += {"{": 1, "}": -1}.get(s[j], 0); j += 1
                    buf.append("{}"); i = j; continue
                buf.append(s[i]); i += 1
            s = "".join(buf)
        if not FRENCH_HINT.search(s) and not re.search(r"[A-Z][a-zé]+ [a-zé]", s):
            continue
        html_fragments(s, src) if "<" in s else add(s, src)

# Python: strings that reach the page or a notification (not docstrings, not dict keys alone)
for f in sorted((ROOT / "src/elegoo_lab").glob("*.py")):
    tree = ast.parse(f.read_text())
    docs = {id(n.body[0].value) for n in ast.walk(tree) if isinstance(n, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
            and n.body and isinstance(n.body[0], ast.Expr) and isinstance(n.body[0].value, ast.Constant)}
    for n in ast.walk(tree):
        if isinstance(n, ast.JoinedStr):
            s = "".join(v.value if isinstance(v, ast.Constant) else "{}" for v in n.values)
        elif isinstance(n, ast.Constant) and isinstance(n.value, str) and id(n) not in docs:
            s = n.value
        else:
            continue
        if " " in s and FRENCH_HINT.search(s) and not s.lstrip().startswith(("SELECT", ";", "G1", "M")):
            add(s, f"py/{f.name}")

json.dump([[t, s] for t, s in out.items()], sys.stdout, ensure_ascii=False, indent=0)
