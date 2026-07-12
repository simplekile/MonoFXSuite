# DCC Architecture Rule

Each DCC must act as a **thin adapter layer**.

## Allowed dependency direction

```
tools → core → monofx_pipeline_common
apps → tools
apps → core
apps → monofx_pipeline_common
```

## Forbidden

- `monofx_pipeline_common` importing `maya.cmds`
- `monofx_pipeline_common` importing `hou`
- `monofx_pipeline_common` importing `bpy`
- `core` importing `maya.cmds`
- `core` importing `hou`
- `core` importing `bpy`

## Principle

**Core logic MUST be DCC agnostic.**

### Example

**GOOD:**

`core/utils/math.py`

**BAD:**

`core/utils/houdini_math.py`

---

👉 Meaning:

- ❌ tool = houdini script  
- ✅ tool = pipeline tool with Houdini adapter
