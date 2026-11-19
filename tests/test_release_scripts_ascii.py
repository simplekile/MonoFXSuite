"""Release scripts stay ASCII: Windows PowerShell 5.1 reads a .ps1 without BOM as ANSI, and Vietnamese text inside a
string became quote marks that swallowed the lines setting the release notes (empty GitHub notes v0.1.24-v0.1.31)."""

from __future__ import annotations

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = sorted([*ROOT.glob("*.ps1"), *(ROOT / "build").glob("*.ps1")])


@pytest.mark.parametrize("script", SCRIPTS, ids=lambda p: p.name)
def test_release_script_is_ascii(script: Path) -> None:
    bad = [i for i, line in enumerate(script.read_bytes().splitlines(), 1) if any(b > 127 for b in line)]
    assert not bad, f"{script.name}: non-ASCII on lines {bad} (PowerShell 5.1 reads it as ANSI)"
