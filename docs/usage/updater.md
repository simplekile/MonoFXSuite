# Updater — Update from GitHub via script

MonoFX Suite can be updated from GitHub **from inside a script** (or from any DCC) using the core updater. No need to open a terminal manually.

## Purpose

- Pull latest changes from `origin` (e.g. `https://github.com/simplekile/MonoFXSuite`) when you run a command inside Maya, Houdini, Blender, or a standalone Python script.

## Requirements

- The toolkit must be installed as a **git clone** (has a `.git` folder).
- **Git** must be on `PATH` where the DCC/script runs.
- Network access to GitHub for `git pull` / `git fetch`.

If Git is missing or the folder is not a repo, the updater returns a clear message and does nothing destructive.

## Usage

### 1. Update now (pull latest)

```python
from pathlib import Path

# If MonoFXSuite is on sys.path or you add it:
import sys
sys.path.insert(0, r"e:\00 Project\Pipeline\MonoFXSuite")

from core.pipeline.updater import pull_latest

result = pull_latest()
if result.success:
    print("OK:", result.message)
    print(result.output)
else:
    print("Update failed:", result.message)
    print(result.output)
```

You can pass a custom repo root (e.g. from DCC’s toolkit path):

```python
result = pull_latest(repo_root=Path(r"e:\00 Project\Pipeline\MonoFXSuite"))
```

### 2. Check if updates exist (without pulling)

```python
from core.pipeline.updater import has_updates

has_new, msg = has_updates()
if has_new:
    print("Updates available:", msg)   # e.g. "3 new commit(s) on origin/main."
else:
    print(msg)   # e.g. "Already up to date." or error message
```

Use this for a “Check for updates” button; use `pull_latest()` for “Update now”.

### 3. From a DCC (e.g. Maya)

Ensure the MonoFX root is on `sys.path`, then call the same API:

```python
# In Maya (or other DCC): add toolkit root to path once, then:
from core.pipeline.updater import pull_latest

result = pull_latest()
cmds.confirmDialog(title="MonoFX Update", message=result.message + "\n\n" + result.output)
```

You can wire `pull_latest()` and `has_updates()` to a menu item or shelf button so artists update with one click.

## Behaviour

- **Repo root** is found by walking up from the updater module (or from `repo_root` if you pass it) until a directory containing `.git` is found.
- **Offline / no Git**: `pull_latest()` and `has_updates()` return `success=False` or `has_new=False` with an explanatory message; no exception.
- **Branch**: Update uses the current branch (typically `main`). `has_updates()` compares to `origin/main`.

## Supported DCC

Any. The updater is in `core` and does not import any DCC API. Use it from:

- Maya
- Houdini  
- Blender
- Unreal (Python)
- Standalone Python

## Dependencies

- Python standard library only (`subprocess`, `pathlib`, `dataclasses`).
- Git executable on `PATH`.
