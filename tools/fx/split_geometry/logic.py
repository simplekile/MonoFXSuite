"""
Split Geometry logic — DCC-agnostic.
Build report and group stats from attribute value -> prim count.
"""

from __future__ import annotations

from typing import Dict, List


def build_report(groups: Dict[str, List[int]], attribute_name: str) -> str:
    """
    Build a text report: attribute name and each unique value with count.
    groups: value -> list of prim/point indices.
    """
    if not groups:
        return f"No string attribute '{attribute_name}' or no geometry."
    lines = [f"Attribute: {attribute_name}", f"Unique values: {len(groups)}", ""]
    for value, indices in sorted(groups.items(), key=lambda x: -len(x[1])):
        display_val = value if value else "(empty)"
        lines.append(f"  {len(indices):6d}  →  {display_val}")
    return "\n".join(lines)


def build_report_from_counts(counts: Dict[str, int], attribute_name: str) -> str:
    """
    Build report from value -> count dict (from bulk API). Faster for preview.
    """
    if not counts:
        return f"No string attribute '{attribute_name}' or no geometry."
    lines = [f"Attribute: {attribute_name}", f"Unique values: {len(counts)}", ""]
    for value, count in sorted(counts.items(), key=lambda x: -x[1]):
        display_val = value if value else "(empty)"
        lines.append(f"  {count:6d}  →  {display_val}")
    return "\n".join(lines)


def get_sorted_values_by_count(groups: Dict[str, List[int]]) -> List[str]:
    """Return list of attribute values sorted by count descending."""
    return [v for v, _ in sorted(groups.items(), key=lambda x: -len(x[1]))]
