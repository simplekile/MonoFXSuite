"""Ensure repo root and monofx_pipeline_common are on sys.path."""

from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_COMMON_SRC = _ROOT / "packages" / "monofx_pipeline_common" / "src"
for _path in (_COMMON_SRC, _ROOT):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))
