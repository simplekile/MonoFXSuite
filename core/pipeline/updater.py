"""
Update MonoFX Suite from GitHub via git pull.

DCC-agnostic: no maya/hou/bpy. Call from any DCC or standalone script.
Uses subprocess + pathlib only. Safe when offline or not a git repo.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


@dataclass
class UpdateResult:
    """Result of an update attempt."""

    success: bool
    message: str
    output: str = ""


def find_repo_root(start: Optional[Path] = None) -> Optional[Path]:
    """
    Find the repository root (directory containing .git) from start path.
    Walks upward until .git is found or root is reached.
    """
    current = Path(start or Path(__file__).resolve())
    if not current.is_dir():
        current = current.parent
    while current != current.parent:
        if (current / ".git").exists():
            return current
        current = current.parent
    if (current / ".git").exists():
        return current
    return None


def run_git(repo_root: Path, *args: str) -> tuple[bool, str]:
    """
    Run a git command in repo_root. Returns (success, stdout+stderr).
    """
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=repo_root,
            capture_output=True,
            text=True,
            timeout=60,
        )
        out = (result.stdout or "").strip() + "\n" + (result.stderr or "").strip()
        return result.returncode == 0, out.strip() or "(no output)"
    except FileNotFoundError:
        return False, "Git not found. Install Git or use PATH that includes git."
    except subprocess.TimeoutExpired:
        return False, "Git command timed out (e.g. network)."
    except Exception as e:
        return False, str(e)


def pull_latest(repo_root: Optional[Path] = None) -> UpdateResult:
    """
    Run `git pull` in the MonoFX repo. Safe to call from any script/DCC.

    - If not a git repo or git missing: returns success=False with message.
    - If offline: returns success=False with message.
    - If pull succeeds: returns success=True and pull output.
    """
    root = find_repo_root(repo_root)
    if not root:
        return UpdateResult(
            success=False,
            message="Not a git repository (no .git found from this path).",
        )

    ok, output = run_git(root, "pull", "--no-rebase")
    if ok:
        return UpdateResult(success=True, message="Updated from GitHub.", output=output)
    return UpdateResult(success=False, message="Git pull failed.", output=output)


def has_updates(repo_root: Optional[Path] = None) -> tuple[bool, str]:
    """
    Fetch and check if origin has new commits. Returns (has_updates, message).
    Use this for a "Check for updates" button without pulling.
    """
    root = find_repo_root(repo_root)
    if not root:
        return False, "Not a git repository."

    ok, _ = run_git(root, "fetch", "origin")
    if not ok:
        return False, "Fetch failed (e.g. offline or no network)."

    ok, out = run_git(root, "rev-list", "--count", "HEAD..origin/main")
    if not ok:
        return False, "Could not compare branches."
    try:
        n = int(out.splitlines()[0].strip())
        return n > 0, f"{n} new commit(s) on origin/main." if n > 0 else "Already up to date."
    except (ValueError, IndexError):
        return False, "Could not parse rev-list output."
