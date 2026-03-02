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
│   ├── unreal/
│   └── shared/
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
- Shared logic must NEVER depend on a DCC API.
- UI must live in `/core/ui`.

👉 **This is the most important rule.** 90% of pipelines fail because the **DCC layer is not separated**.
