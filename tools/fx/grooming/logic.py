"""
Pure logic of MONO Grooming (no `hou`): re-import matching, region split, publish paths, naming.

The dataclasses below are the shared contract between the adapter and the panel (spec:
docs/plans/grooming_v0_1.md, "Adapter API"). Functions marked NotImplementedError are the logic
session's job; their signatures are fixed so the other parts can be written against them.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Sequence


@dataclass
class LockInfo:
    """What the cooked geometry says about one lock (measured, not stored in the JSON)."""
    id: int
    name: str
    group: str
    root: tuple[float, float, float]
    length: float
    width: float          # mean measured lock width
    thick: float          # mean measured lock thickness
    twist: float          # total measured twist, radians
    strands: int          # strands generated at full count
    region_area_cm2: float


@dataclass
class MeshPiece:
    """One hair-mesh piece as detection sees it, before it has an id."""
    index: int                         # piece number in the input geometry
    name: str                          # prim `name`, "" when the mesh has none
    root: tuple[float, float, float]   # spine root (closest to the scalp)
    length: float
    direction: tuple[float, float, float]  # unit root -> tip


@dataclass
class Match:
    piece: int            # MeshPiece.index
    lock_id: int          # existing id, or a new one
    status: str           # "ok" | "unsure" | "new"


@dataclass
class DetectReport:
    matches: list[Match] = field(default_factory=list)
    orphaned: list[int] = field(default_factory=list)   # lock ids with no piece any more

    @property
    def counts(self) -> dict[str, int]:
        out = {"ok": 0, "unsure": 0, "new": 0, "orphaned": len(self.orphaned)}
        for m in self.matches:
            out[m.status] += 1
        return out


@dataclass
class PublishResult:
    ok: bool
    path: str
    version: str
    message: str


def match_locks(pieces: Sequence[MeshPiece], locks: Sequence["object"], next_id: int) -> DetectReport:
    """Match hair-mesh pieces to existing locks (model.Lock): by name, then root distance, then shape.

    A match by name with the root still close is "ok"; a match by position or shape only is "unsure";
    a piece matching nothing gets a new id from `next_id` upward. Each lock matches at most one piece.
    """
    raise NotImplementedError


def split_regions(scalp_points: Sequence[tuple[float, float, float]],
                  roots: dict[int, tuple[float, float, float]],
                  groups_of: dict[int, str],
                  point_groups: Sequence[str]) -> list[int]:
    """`lock_owner` per scalp point: the nearest lock root among locks of the point's group (region),
    `config.NO_OWNER` where the group has no lock."""
    raise NotImplementedError


def publish_version(scene_name: str, existing: Sequence[str]) -> tuple[str, str]:
    """Default publish version and a note for the panel.

    `scene_name` like "char_Helen_grooming_v007"; `existing` like ["v001", ..., "v006"].
    Uses the scene's vNNN unless that already exists or is not newer than the newest publish, then the
    next free one, and says why in the note.
    """
    raise NotImplementedError


def publish_paths(hip_dir: str, asset: str, version: str) -> tuple[str, str]:
    """(usd_path, tool_data_dir) for the asset groom publish, found by walking up from the scene's
    folder to the asset folder that holds `04_grooming`."""
    raise NotImplementedError


def lock_name(group_prefix: str, taken: Sequence[str]) -> str:
    """Next free name like "fringe_03" for a group prefix."""
    raise NotImplementedError
