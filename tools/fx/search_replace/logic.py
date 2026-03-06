"""
Search & Replace logic — DCC-agnostic.
Find/replace in strings, optional regex; build preview list.
"""

from __future__ import annotations

import re
from typing import List, Tuple


def replace_in_string(
    text: str,
    find: str,
    replace: str,
    use_regex: bool = False,
) -> Tuple[str, int]:
    """
    Replace find with replace in text. Returns (new_text, replacement_count).
    If use_regex, find is a regex pattern.
    """
    if not find:
        return text, 0
    if use_regex:
        try:
            pattern = re.compile(find)
            new_text, n = pattern.subn(replace, text)
            return new_text, n
        except re.error:
            return text, 0
    n = text.count(find)
    return text.replace(find, replace), n


def build_preview_line(node_path: str, parm_or_name: str, old_val: str, new_val: str) -> str:
    """One line for preview list."""
    loc = f"{node_path} / {parm_or_name}"
    return f"{loc}\n  → {repr(old_val[:60])} → {repr(new_val[:60])}"
