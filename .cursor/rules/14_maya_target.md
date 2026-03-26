# Maya Target Rule

## Maya version
- Target DCC for Maya tools: `Maya 2025`

## Qt binding (PySide)
- For any code that is intended to run inside Maya (`apps/maya/**`, `tools/**` for Maya), use **PySide6 only**
- Use:
  - `from PySide6 import ...`
  - `from shiboken6 import wrapInstance`
- Do **not** use `PySide2` / `shiboken2` in Maya tool code.

