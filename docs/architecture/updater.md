# Updater — Architecture

## Purpose

Allow MonoFX Suite to be updated from GitHub from within a script or DCC (e.g. menu “Update from GitHub”), without opening a terminal.

## Location

- **Logic:** `core/pipeline/updater.py`
- **Docs:** `docs/usage/updater.md`, `docs/architecture/updater.md`

## Design

- **DCC-agnostic:** No imports of `maya.cmds`, `hou`, `bpy`, etc. Only stdlib: `subprocess`, `pathlib`, `dataclasses`.
- **Repo discovery:** Walks upward from the module file (or from an optional `repo_root`) until a directory containing `.git` is found.
- **Git only:** Uses `git pull` and `git fetch` via `subprocess`. No GitHub API, no HTTP client.
- **Fail-safe:** If not a git repo, or Git is missing, or network fails, returns structured result with message; no uncaught exceptions for normal failure cases.

## Dependencies

- Python standard library.
- Git on `PATH`.

## Usage flow

1. **Update now:** Script/DCC calls `pull_latest()` → `run_git(repo_root, "pull", "--no-rebase")` → `UpdateResult(success, message, output)`.
2. **Check only:** Script/DCC calls `has_updates()` → `git fetch origin` then `git rev-list --count HEAD..origin/main` → `(bool, str)`.

## Reuse

- Any DCC can add a menu/shelf action that imports `core.pipeline.updater` and calls `pull_latest()` / `has_updates()`.
- Standalone Python launchers can do the same after adding the MonoFX root to `sys.path`.
