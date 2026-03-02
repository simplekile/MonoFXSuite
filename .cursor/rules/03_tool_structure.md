# Tool Structure Rule

Every tool MUST follow this layout.

```
tool_name/
    __init__.py
    controller.py
    ui.py
    logic.py
    config.py
```

## Responsibilities

| File | Role |
|------|------|
| **controller.py** | Connect UI + logic, DCC entry point |
| **logic.py** | Pure logic, NO UI, NO DCC API |
| **ui.py** | PySide6 only |
| **config.py** | Default settings |

👉 This rule prevents **God Script syndrome**.
