"""Builds fake project folder trees for the Mono Anim Loader logic tests (empty files, no USD)."""

from __future__ import annotations

import json
from pathlib import Path


def make(root: Path, files: list[str], meta: dict[str, dict] | None = None) -> Path:
    """Create ``root/01_assets``, ``root/02_shots`` and every relative path in ``files`` (empty files).

    ``meta`` maps a version folder (relative) to the publish_meta.json written in it.
    """
    (root / "01_assets").mkdir(parents=True, exist_ok=True)
    (root / "02_shots").mkdir(parents=True, exist_ok=True)
    for rel in files:
        p = root / rel
        if rel.endswith("/"):
            p.mkdir(parents=True, exist_ok=True)
            continue
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"")
    for rel, data in (meta or {}).items():
        d = root / rel
        d.mkdir(parents=True, exist_ok=True)
        (d / "publish_meta.json").write_text(json.dumps(data), encoding="utf-8")
    return root


def frames(folder: str, name: str, numbers, pad: int = 4) -> list[str]:
    """``folder/name.0001.usd`` ... for each frame number."""
    return [f"{folder}/{name}.{n:0{pad}d}.usd" for n in numbers]
