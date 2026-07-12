# Repository Structure Rule

This repository is a multi-DCC pipeline toolkit.

All tools MUST follow the structure below.

```
MonoFX/
│
├── apps/
│   ├── houdini/
│   ├── maya/
│   ├── blender/
│   └── common/          # backward-compat re-exports → monofx_pipeline_common
│
├── packages/
│   └── monofx_pipeline_common/   # DCC-agnostic shared pipeline logic (src layout)
│
├── core/
│   ├── ui/
│   ├── utils/
│   ├── pipeline/
│   └── config/
│
├── tools/
│   ├── animation/
│   ├── fx/
│   ├── layout/
│   └── rendering/
│
├── docs/
│   ├── setup/
│   ├── architecture/
│   └── usage/
│
├── notes/
│
├── tests/
│
├── .cursor/
└── README.md
```

## Rules

- No script is allowed at root level.
- DCC specific code must stay inside `/apps`.
- Shared pipeline logic lives in `packages/monofx_pipeline_common/` (no `hou` / `maya` / `bpy`).
- `apps/common/` re-exports from `monofx_pipeline_common` for backward compatibility.
- UI must live in `/core/ui`.

👉 **This is the most important rule.** 90% of pipelines fail because the **DCC layer is not separated**.
