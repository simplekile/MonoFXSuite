"""Grab a Qt panel offscreen at several widths and scales, and list its controls, without a DCC.

    python .claude/skills/dcc-panel-design/scripts/grab_offscreen.py --factory my_factory:make \
        --widths 400,760,1100 --height 820 --scales 1,1.5 --out <dir>

`--factory module:callable` names a function `make(scale: float) -> QWidget` that builds the panel with
fake data (a FakeAdapter like the one in tests/test_grooming_controller.py). The module is imported with
the suite root and `tests/` on sys.path. For every width x scale the script writes
`<name>_w<width>_s<scale>.png` and an inventory `<name>_w<width>_s<scale>.txt`: every visible control
(class, objectName, text, tooltip, size) and the ones whose hit target is under --min-hit px (24 x 24 at
scale 1, the WCAG 2.5.8 floor; the host's own buttons are ~28). Exit 1 when a grab has a small target or
a widget wider than its window (an overflow), so a CI run can fail on it.
"""
from __future__ import annotations

import argparse
import importlib
import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
if sys.platform == "win32" and os.path.isdir(r"C:\Windows\Fonts"):
    os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")   # offscreen has no font directory of its own

INTERACTIVE = ("QAbstractButton", "QComboBox", "QSlider", "QLineEdit", "QAbstractSpinBox", "QTabBar",
               "QAbstractItemView")


def _root() -> Path:
    here = Path(__file__).resolve()
    for p in here.parents:
        if (p / "tools").is_dir() and (p / "tests").is_dir():
            return p
    return Path.cwd()


def _is_interactive(w) -> bool:
    return any(w.inherits(cls) for cls in INTERACTIVE)


def inventory(widget, min_hit: int) -> tuple[list[str], list[str], list[str]]:
    """(lines, small hit targets, overflowing widgets) over the visible widgets of `widget`."""
    from PySide6.QtWidgets import QWidget

    lines, small, overflow = [], [], []
    win_w = widget.width()
    for w in widget.findChildren(QWidget):
        if not w.isVisible() or w.width() == 0 or w.height() == 0:
            continue
        text = ""
        for attr in ("text", "placeholderText", "currentText", "windowTitle"):
            f = getattr(w, attr, None)
            if callable(f):
                try:
                    text = str(f())
                except Exception:
                    text = ""
                if text:
                    break
        tip = w.toolTip().replace("\n", " ")
        name = w.objectName()
        label = f"{w.metaObject().className()}" + (f"#{name}" if name else "")
        desc = f"{label:<34} {w.width():>4}x{w.height():<4} {text[:50]!r}" + (f"  tip: {tip[:70]!r}" if tip else "")
        lines.append(desc)
        if _is_interactive(w) and (w.width() < min_hit or w.height() < min_hit):
            small.append(desc)
        pos = w.mapTo(widget, w.rect().topLeft())
        if pos.x() + w.width() > win_w + 1:
            overflow.append(desc)
    return lines, small, overflow


def grab(factory, name: str, widths: list[int], height: int, scales: list[float], out: Path,
         min_hit: int) -> int:
    from PySide6.QtGui import QFont, QFontDatabase
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    families = set(QFontDatabase.families())
    if "Inter" not in families:      # the suite's face; without a substitute the offscreen grab shows boxes
        for fallback in ("Segoe UI", "Helvetica Neue", "DejaVu Sans", "Arial"):
            if fallback in families:
                QFont.insertSubstitution("Inter", fallback)
                print(f"note: Inter is not installed, grabbing with {fallback}")
                break
    out.mkdir(parents=True, exist_ok=True)
    problems = 0
    for scale in scales:
        widget = factory(scale)
        widget.show()
        for width in widths:
            widget.resize(int(width * scale), int(height * scale))
            for _ in range(3):           # let width-dependent layouts (wrap rows, narrow mode) settle
                app.processEvents()
            tag = f"{name}_w{width}_s{scale:g}"
            widget.grab().save(str(out / f"{tag}.png"))
            lines, small, overflow = inventory(widget, int(round(min_hit * scale)))
            report = [f"# {tag}: {widget.width()}x{widget.height()} px, {len(lines)} visible widgets",
                      f"# small hit targets (< {int(round(min_hit * scale))} px): {len(small)}",
                      *(f"  SMALL {s}" for s in small),
                      f"# wider than the window: {len(overflow)}",
                      *(f"  OVERFLOW {s}" for s in overflow), "", *lines]
            (out / f"{tag}.txt").write_text("\n".join(report), encoding="utf-8")
            problems += len(small) + len(overflow)
            print(f"{tag}: {len(lines)} widgets, {len(small)} small targets, {len(overflow)} overflow")
        widget.close()
    return problems


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--factory", required=True, help="module:callable, make(scale) -> QWidget")
    ap.add_argument("--name", default="panel")
    ap.add_argument("--widths", default="400,760,1100")
    ap.add_argument("--height", type=int, default=820)
    ap.add_argument("--scales", default="1,1.5")
    ap.add_argument("--min-hit", type=int, default=24, help="smallest hit target in px at scale 1")
    ap.add_argument("--out", default="grabs")
    args = ap.parse_args(argv)
    root = _root()
    for p in (root, root / "tests"):
        if str(p) not in sys.path:
            sys.path.insert(0, str(p))
    mod_name, _, func_name = args.factory.partition(":")
    try:
        factory = getattr(importlib.import_module(mod_name), func_name or "make")
    except (ImportError, AttributeError) as e:
        print(f"error: cannot load factory {args.factory}: {e}", file=sys.stderr)
        return 2
    widths = [int(w) for w in args.widths.split(",")]
    scales = [float(s) for s in args.scales.split(",")]
    problems = grab(factory, args.name, widths, args.height, scales, Path(args.out), args.min_hit)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
