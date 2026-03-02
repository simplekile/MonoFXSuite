# Git Workflow Rule

## Branch model

- `main` → stable
- `dev` → integration
- `feature/*` → development

**Never commit directly to main.**

## Commit format

```
[type]: short description
```

**Types:** `feat` | `fix` | `refactor` | `ui` | `pipeline` | `docs`

### Examples

```
feat: add houdini ribbon trail generator
fix: resolve maya docking issue
```
