"""
USD export rule parsing and job building — no Maya, no Qt.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, MutableSet, Optional, Tuple


INVALID_FILENAME_CHARS = '<>:"/\\|?*'


@dataclass
class ExportJob:
    rule_id: str
    dag_path: str
    output_basename: str  # without .usd


def sanitize_filename_component(name: str) -> str:
    s = name
    for c in INVALID_FILENAME_CHARS:
        s = s.replace(c, "_")
    s = s.replace("|", "_").replace(":", "_")
    s = s.strip(". ")
    return s or "unnamed"


def load_rules_file(path: str) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
    p = Path(path)
    raw = json.loads(p.read_text(encoding="utf-8"))
    rules = raw.get("rules") or []
    if not isinstance(rules, list):
        raise ValueError("rules must be a list")
    return raw, rules


def _norm_namespace(ns: str) -> str:
    s = ns.strip()
    for old in ("Rig_", "_Publish", "_rig", "_publish"):
        s = s.replace(old, "")
    return sanitize_filename_component(s)


def _leaf_from_long(long_path: str) -> str:
    short = long_path.split("|")[-1]
    return short.split(":")[-1]


def _build_basename(filename_rule: Dict[str, Any], leaf: str, namespace: str) -> str:
    prefix = str(filename_rule.get("prefix") or "")
    name_from = str(filename_rule.get("name_from") or "leaf")
    if name_from == "namespace":
        body = _norm_namespace(namespace)
    else:
        body = sanitize_filename_component(leaf)
    return sanitize_filename_component(prefix + body)


def _alloc_basename(base: str, used: MutableSet[str]) -> str:
    if base not in used:
        used.add(base)
        return base
    i = 2
    while True:
        cand = f"{base}_{i}"
        if cand not in used:
            used.add(cand)
            return cand
        i += 1


def next_version_folder_name(publish_root: str) -> str:
    root = Path(publish_root)
    if not root.is_dir():
        return "v001"
    best = 0
    pat = re.compile(r"^v(\d{3})$", re.I)
    for child in root.iterdir():
        if not child.is_dir():
            continue
        m = pat.match(child.name)
        if m:
            best = max(best, int(m.group(1)))
    return f"v{best + 1:03d}"


def build_export_jobs(
    rules: List[Dict[str, Any]],
    *,
    cameras: List[Dict[str, str]],
    ref_geometry: List[Dict[str, str]],
    transforms_long: List[str],
) -> List[ExportJob]:
    """
    Apply rules in order; each DAG path is consumed by at most one rule.
    """
    consumed: MutableSet[str] = set()
    used_names: MutableSet[str] = set()
    jobs: List[ExportJob] = []

    for rule in rules:
        if not rule.get("enabled", True):
            continue
        rid = str(rule.get("id") or "rule")
        match = rule.get("match") or {}
        mtype = str(match.get("type") or "")
        filename_rule = rule.get("filename") or {}

        if mtype == "camera":
            leaf_rx = match.get("leaf_regex")
            pattern = re.compile(str(leaf_rx)) if leaf_rx else None
            for cam in cameras:
                lp = cam["long_path"]
                if lp in consumed:
                    continue
                leaf = cam["leaf"]
                if pattern and not pattern.match(leaf):
                    continue
                base = _build_basename(filename_rule, leaf, "")
                base = _alloc_basename(base, used_names)
                jobs.append(ExportJob(rule_id=rid, dag_path=lp, output_basename=base))
                consumed.add(lp)

        elif mtype == "ref_geometry":
            for rg in ref_geometry:
                lp = rg["long_path"]
                if lp in consumed:
                    continue
                ns = rg.get("namespace") or ""
                base = _build_basename(
                    filename_rule,
                    leaf=_leaf_from_long(lp),
                    namespace=ns,
                )
                base = _alloc_basename(base, used_names)
                jobs.append(ExportJob(rule_id=rid, dag_path=lp, output_basename=base))
                consumed.add(lp)

        elif mtype == "transform_regex":
            path_rx = match.get("path_regex")
            leaf_rx = match.get("leaf_regex")
            path_pattern = re.compile(str(path_rx)) if path_rx else None
            leaf_pattern = re.compile(str(leaf_rx)) if leaf_rx else None
            if not path_pattern and not leaf_pattern:
                continue
            for lp in transforms_long:
                if lp in consumed:
                    continue
                leaf = _leaf_from_long(lp)
                ok = True
                if path_pattern and not path_pattern.search(lp):
                    ok = False
                if ok and leaf_pattern and not leaf_pattern.match(leaf):
                    ok = False
                if not ok:
                    continue
                base = _build_basename(filename_rule, leaf, "")
                base = _alloc_basename(base, used_names)
                jobs.append(ExportJob(rule_id=rid, dag_path=lp, output_basename=base))
                consumed.add(lp)

    return jobs
