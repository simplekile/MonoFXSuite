"""WCAG 2.x contrast of a DCC panel palette, stdlib only.

    python .claude/skills/dcc-panel-design/scripts/contrast_check.py --pairs references/palette_pairs.json
    python .claude/skills/dcc-panel-design/scripts/contrast_check.py --fg "#a3a3ae" --bg "#17171b" --kind text

A pair is {"label", "fg", "bg", "kind"}; kind is "text" (4.5:1), "large" (3:1, text of 24px+ or 19px+
semibold) or "ui" (3:1, icons, borders, focus rings, chips, disabled text that still carries meaning).
A colour is "#rrggbb", or {"color": "#rrggbb", "alpha": 0.16, "over": "#rrggbb"} for a translucent fill
composited over a surface (what `_rgba(ACCENT, 0.16)` paints over the pane). With --suggest a failing
foreground is pushed towards white or black until it passes. A pair with "known_fail": "<why>" is a
documented exception: printed as FAIL (known), not counted. Exit 1 when a pair fails, 2 on bad input.
"""
from __future__ import annotations

import argparse
import json
import sys
from typing import Any

NEEDED = {"text": 4.5, "large": 3.0, "ui": 3.0}


def parse_hex(color: str) -> tuple[int, int, int]:
    c = color.strip().lstrip("#")
    if len(c) == 3:
        c = "".join(ch * 2 for ch in c)
    if len(c) != 6 or any(ch not in "0123456789abcdefABCDEF" for ch in c):
        raise ValueError(f"not a #rrggbb colour: {color!r}")
    return int(c[0:2], 16), int(c[2:4], 16), int(c[4:6], 16)


def to_hex(rgb: tuple[int, int, int]) -> str:
    return "#%02x%02x%02x" % tuple(max(0, min(255, round(v))) for v in rgb)


def composite(color: str, alpha: float, over: str) -> tuple[int, int, int]:
    """Colour at `alpha` painted over an opaque surface (plain alpha blend, sRGB values like Qt)."""
    f, b = parse_hex(color), parse_hex(over)
    return tuple(round(fc * alpha + bc * (1 - alpha)) for fc, bc in zip(f, b))  # type: ignore[return-value]


def resolve(spec: Any) -> tuple[int, int, int]:
    if isinstance(spec, str):
        return parse_hex(spec)
    if isinstance(spec, dict) and "color" in spec:
        if "alpha" in spec:
            return composite(spec["color"], float(spec["alpha"]), spec.get("over", "#000000"))
        return parse_hex(spec["color"])
    raise ValueError(f"colour must be '#rrggbb' or {{color, alpha, over}}: {spec!r}")


def luminance(rgb: tuple[int, int, int]) -> float:
    def chan(v: int) -> float:
        s = v / 255.0
        return s / 12.92 if s <= 0.04045 else ((s + 0.055) / 1.055) ** 2.4
    r, g, b = (chan(v) for v in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def ratio(fg: tuple[int, int, int], bg: tuple[int, int, int]) -> float:
    lf, lb = luminance(fg), luminance(bg)
    hi, lo = max(lf, lb), min(lf, lb)
    return (hi + 0.05) / (lo + 0.05)


def suggest(fg: tuple[int, int, int], bg: tuple[int, int, int], needed: float) -> str | None:
    """The nearest foreground that passes: the colour blended towards white (on a dark surface) or
    black (on a light one) in 2 % steps. None when even the extreme does not pass."""
    target = (255, 255, 255) if luminance(bg) < 0.18 else (0, 0, 0)
    for step in range(0, 51):
        t = step / 50.0
        cand = tuple(round(c * (1 - t) + tc * t) for c, tc in zip(fg, target))
        if ratio(cand, bg) >= needed:  # type: ignore[arg-type]
            return to_hex(cand)  # type: ignore[arg-type]
    return None


def check_pairs(pairs: list[dict], want_suggest: bool = False) -> list[dict]:
    rows = []
    for p in pairs:
        kind = p.get("kind", "text")
        if kind not in NEEDED:
            raise ValueError(f"kind must be text, large or ui: {kind!r} ({p.get('label')})")
        fg, bg = resolve(p["fg"]), resolve(p["bg"])
        r = ratio(fg, bg)
        row = {"label": p.get("label", ""), "fg": to_hex(fg), "bg": to_hex(bg), "kind": kind,
               "ratio": round(r, 2), "needed": NEEDED[kind], "pass": r >= NEEDED[kind],
               "known": bool(p.get("known_fail"))}   # a documented exception: reported, not counted
        if want_suggest and not row["pass"]:
            row["suggest"] = suggest(fg, bg, NEEDED[kind])
        rows.append(row)
    return rows


def format_text(rows: list[dict]) -> str:
    width = max([len(r["label"]) for r in rows] + [5])
    lines = [f"{'pair'.ljust(width)}  fg       bg       kind   ratio  need  result"]
    for r in rows:
        res = "PASS" if r["pass"] else ("FAIL (known)" if r["known"] else "FAIL")
        if r.get("suggest"):
            res += f"  -> {r['suggest']}"
        lines.append(f"{r['label'].ljust(width)}  {r['fg']}  {r['bg']}  {r['kind']:<5}  {r['ratio']:>5.2f}"
                     f"  {r['needed']:>4.1f}  {res}")
    failed = sum(1 for r in rows if not r["pass"] and not r["known"])
    known = sum(1 for r in rows if not r["pass"] and r["known"])
    tail = f"{len(rows) - failed - known} of {len(rows)} pass"
    tail += f", {failed} fail" if failed else ""
    tail += f", {known} known" if known else ""
    lines.append(tail)
    return "\n".join(lines)


def failures(rows: list[dict]) -> int:
    return sum(1 for r in rows if not r["pass"] and not r["known"])


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--pairs", help="JSON file: {\"pairs\": [{label, fg, bg, kind}]}")
    ap.add_argument("--fg")
    ap.add_argument("--bg")
    ap.add_argument("--kind", default="text", choices=sorted(NEEDED))
    ap.add_argument("--suggest", action="store_true", help="propose a passing foreground for each failure")
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    args = ap.parse_args(argv)
    try:
        if args.pairs:
            with open(args.pairs, encoding="utf-8") as f:
                data = json.load(f)
            pairs = data["pairs"] if isinstance(data, dict) else data
        elif args.fg and args.bg:
            pairs = [{"label": f"{args.fg} on {args.bg}", "fg": args.fg, "bg": args.bg, "kind": args.kind}]
        else:
            ap.error("give --pairs FILE or --fg and --bg")
        rows = check_pairs(pairs, args.suggest)
    except (OSError, ValueError, KeyError, TypeError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    print(json.dumps(rows, indent=1) if args.json else format_text(rows))
    return 0 if failures(rows) == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
