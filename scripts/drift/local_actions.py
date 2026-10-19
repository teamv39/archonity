"""Локальные действия UI (обработчик события без AJAX) против текстов шагов S0–S7.

python local_actions.py <targets/trainticket> <scenarios dir>
"""
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

root = Path(sys.argv[1]) / "ts-ui-dashboard" / "static"
AJAX = re.compile(r"\$\.ajax|\$\.get\b|\$\.post\b|\$\.getJSON|\$http|axios\.|fetch\(")
FN = re.compile(r"function\s+([A-Za-z_$][\w$]*)\s*\(|([A-Za-z_$][\w$]*)\s*=\s*function\s*\(")
STOP = {"the", "a", "an", "of", "on", "to", "and", "for", "with", "in", "at", "this", "from", "list", "btn", "button",
        "select", "id", "change", "click", "preserve", "show", "get", "set", "init", "div"}

# тела функций активных js (assets/js)
bodies = {}
for js in (root / "assets" / "js").glob("*.js"):
    src = js.read_text(encoding="utf-8", errors="replace")
    starts = [(m.start(), m.group(1) or m.group(2)) for m in FN.finditer(src)]
    for pos, name in starts:
        i = src.find("{", pos)
        depth, j = 0, i
        while j < len(src):
            depth += {"{": 1, "}": -1}.get(src[j], 0)
            if depth == 0:
                break
            j += 1
        bodies.setdefault(name, src[pos:j + 1])


def has_ajax(name, seen=()):
    b = bodies.get(name)
    if b is None or name in seen:
        return False
    if AJAX.search(b):
        return True
    return any(has_ajax(c, seen + (name,)) for c in re.findall(r"\b([A-Za-z_$][\w$]*)\s*\(", b) if c in bodies and c != name)


def words(s):
    s = re.sub(r"([a-z])([A-Z])", r"\1 \2", s)
    return {w for w in re.findall(r"[a-z]+", s.lower()) if w not in STOP and len(w) > 2}


local = []
for html in root.glob("client_*.html"):
    for m in re.finditer(r"<(\w+)([^>]*?)\son(change|click)=\"\s*([A-Za-z_$][\w$]*)\s*\(", html.read_text(encoding="utf-8", errors="replace")):
        attrs, fn = m.group(2), m.group(4)
        if fn in bodies and not has_ajax(fn):
            eid = re.search(r'id="([^"]+)"', attrs)
            local.append((html.name, fn, eid.group(1) if eid else "", words(fn + " " + (eid.group(1) if eid else ""))))
print("локальных действий:", len(local))
for l in local:
    print("  ", l[0], l[1], l[2], sorted(l[3]))
print()
for sc in sorted(Path(sys.argv[2]).glob("S*.json")):
    d = json.loads(sc.read_text(encoding="utf-8"))
    for i, st in enumerate(d["steps"], 1):
        t = st.get("action") if isinstance(st, dict) else st
        w = words(t)
        best = max(local, key=lambda l: len(l[3] & w), default=None)
        if best and len(best[3] & w) >= 2:
            print(f"{sc.stem}.{i:<2} {len(best[3] & w)} {sorted(best[3] & w)} {best[1]}  | {t[:70]}")
