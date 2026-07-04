"""Config for USD Batch Load tool (Solaris / LOP)."""

from __future__ import annotations

WINDOW_TITLE = "USD Batch Load"

MODE_SUBLAYER = "sublayer"
MODE_REFERENCE = "reference"

MODE_OPTIONS: list[tuple[str, str]] = [
    ("Sublayer — compose layers", MODE_SUBLAYER),
    ("Reference — prim per file", MODE_REFERENCE),
]

USD_EXTS = (".usd", ".usda", ".usdc")
