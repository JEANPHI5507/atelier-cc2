"""The workshop's texts in English, server side: the same dictionary as the pages (web/i18n/en.json), for what leaves
the page, such as the phone notifications. The language is the last one chosen in the interface ([interface] langue)."""

from __future__ import annotations

import json
import re
from functools import lru_cache
from typing import Any

from . import config

DICT = config.ROOT / "src" / "elegoo_lab" / "web" / "i18n" / "en.json"


def language() -> str:
    if config.CONFIG_FILE.exists():
        import tomllib
        lang = tomllib.loads(config.CONFIG_FILE.read_text()).get("interface", {}).get("langue")
        if lang in ("fr", "en"):
            return lang
    return "fr"


@lru_cache(maxsize=1)
def _load(mtime: float) -> tuple[dict[str, str], list[tuple[re.Pattern, str, str]]]:
    d: dict[str, Any] = json.loads(DICT.read_text())
    pats = [(re.compile("^" + re.escape(fr).replace(r"\{\}", "(.*?)") + "$"), en, fr.replace("{}", ""))
            for fr, en in d.get("patterns", [])]
    return d.get("exact", {}), pats


def _by_pattern(core: str, pats: list[tuple[re.Pattern, str]]) -> str | None:
    for rx, en in pats:
        m = rx.match(core)
        if m:
            groups, seq = m.groups(), iter(m.groups())

            def fill(g: re.Match) -> str:
                v = groups[int(g.group(1)) - 1] if g.group(1) else next(seq, "")
                return tr(v, "en") if v else v
            return re.sub(r"\{(\d*)\}", fill, en)
    return None


def tr(text: str, lang: str | None = None) -> str:
    """``text`` in English when the language is English (same rules as web/js/i18n.js), else unchanged."""
    if (lang or language()) != "en" or not text or not DICT.exists():
        return text
    exact, pats = _load(DICT.stat().st_mtime)
    lead, core, trail = re.match(r"^(\s*)(.*?)(\s*)$", text, re.S).groups()
    core = re.sub(r"\s+", " ", core)
    # patterns are sorted most specific first; the last ones ("{} : {}", "{} · {}") only split a text into pieces
    specific = [p for p in pats if len(p[2]) > 3]
    loose = [p for p in pats if len(p[2]) <= 3]
    hit = exact.get(core) or _by_pattern(core, [(rx, en) for rx, en, _ in specific])
    if hit is None:
        parts = _SENTENCES.split(core)   # an alert chains sentences: translate them one by one
        if len(parts) > 1:
            out = [tr(x, "en") for x in parts]
            if out != parts:
                hit = " ".join(out)
    if hit is None:
        hit = _by_pattern(core, [(rx, en) for rx, en, _ in loose])
    return text if hit is None else lead + hit + trail


_SENTENCES = re.compile(r"(?<=[.!?])\s+(?=[A-ZÀ-Ý])")
