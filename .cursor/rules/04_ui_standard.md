# UI Standard — MONOS Design System

**Preferred framework:** PySide6  
**Reference implementation:** `MonoStudio/monostudio/ui_qt/style.py`

## Requirements

- Dark theme compatible (MONOS Deep Dark)
- Dockable when DCC supports docking
- No blocking UI
- Separate UI from logic

## UI must follow

- QWidget based
- No global variables
- Signals over direct calls

## Font

- **UI font**: Inter, 13px, Medium weight
- **Mono font**: JetBrains Mono (paths, code values)
- Hinting: `PreferVerticalHinting`
- Strategy: `PreferAntialias`

## Color Palette (Tailwind Zinc + Blue accent)

| Token | Hex | Usage |
|-------|-----|-------|
| `app_bg` | `#09090b` | App background (Zinc-950) |
| `panel` | `#18181b` | Panel / dialog background (Zinc-900) |
| `surface` | `#27272a` | Input / card / elevated surface (Zinc-800) |
| `content_bg` | `#121214` | Content area behind cards/rows |
| `border` | `#27272a` | Default border (Zinc-800) |
| `border_subtle` | `rgba(39, 39, 42, 0.50)` | Subtle border (Zinc-700 50%) |
| `text_primary` | `#fafafa` | Primary text (Zinc-50) |
| `text_label` | `#a1a1aa` | Label text (Zinc-400) |
| `text_meta` | `#71717a` | Meta / muted text (Zinc-500) |
| `placeholder` | `#3f3f46` | Placeholder (Zinc-700) |
| `blue_600` | `#2563eb` | Primary accent / highlight |
| `blue_500` | `#3b82f6` | Accent hover |
| `blue_400` | `#60a5fa` | Selected text / active |
| `emerald_500` | `#10b981` | Success / positive |
| `amber_500` | `#f59e0b` | Warning |
| `red_500` | `#ef4444` | Error / destructive |

## Component Styles

### Buttons

**Primary** (`#DialogPrimaryButton`):
```
background: rgba(37, 99, 235, 0.22);
border: 1px solid rgba(37, 99, 235, 0.70);
color: #fafafa;
border-radius: 8px;
padding: 8px 12px;
hover: background rgba(37, 99, 235, 0.35);
```

**Secondary** (`#DialogSecondaryButton`):
```
background: rgba(24, 24, 27, 0.35);
border: 1px solid rgba(39, 39, 42, 0.50);
color: #a1a1aa;
border-radius: 8px;
padding: 8px 12px;
hover: color #fafafa;
```

**Destructive** (`#DialogDestructiveButton`):
```
background: rgba(239, 68, 68, 0.18);
border: 1px solid rgba(239, 68, 68, 0.60);
color: #fca5a5;
border-radius: 8px;
```

### QToolButton

```
padding: 6px 10px;
border: 1px solid rgba(39, 39, 42, 0.50);
border-radius: 8px;
background: rgba(24, 24, 27, 0.35);
color: #a1a1aa;
hover → background: rgba(255, 255, 255, 0.12), color: #e4e4e7;
checked → background: rgba(59, 130, 246, 0.10), border: rgba(37, 99, 235, 0.50), color: #60a5fa;
```

### QLineEdit

```
padding: 6px 8px;
border: 1px solid rgba(39, 39, 42, 0.50);
border-radius: 6px;
background: #27272a;
focus → border: 1px solid #2563eb;
```

### QTableWidget / QTableView

```
background: #121214;
border: 1px solid #2a2a2c;
gridline-color: #2a2a2c;
color: #eeeeee;
font-size: 12px;
selection-background: rgba(37, 99, 235, 0.15);
selection-color: #2563eb;
header-bg: #0d0d0f;
header-color: #4a4a4c;
header-border-bottom: 2px solid #2a2a2c;
```

### Scrollbar (minimal)

```
width/height: 8px;
background: transparent;
handle: rgba(255, 255, 255, 0.22), border-radius: 4px;
handle:hover: rgba(255, 255, 255, 0.45);
no arrows (add-line/sub-line: 0px);
```

### Tooltip

```
background: #18181b;
color: #fafafa;
border: 1px solid #3f3f46;
border-radius: 8px;
padding: 4px 6px;
font-size: 12px;
```

### Badge (status)

```
font-size: 10px; font-weight: bold;
padding: 2px 8px; border-radius: 4px;
border: 1px solid rgba(color, 50);
background: rgba(color, 100);
color: semantic color (emerald/amber/red/zinc);
```

## Window title

- Dùng **một nguồn**: `config.WINDOW_TITLE` trong controller.
- **Chuẩn** (giống Auto Material Builder): `ui.setWindowTitle(config.WINDOW_TITLE)` — không thêm version hay text phụ vào title.
- Mỗi tool có `config.py` với `WINDOW_TITLE = "Tên Tool"`.

## Naming (objectName)

Widgets phải set `objectName` để QSS target chính xác:

| Widget | objectName pattern |
|--------|-------------------|
| Primary button | `DialogPrimaryButton` |
| Secondary button | `DialogSecondaryButton` |
| Destructive button | `DialogDestructiveButton` |
| Single-select list | `SelectableList` |
| Multi-select list | `SelectableListMulti` |
| Mono-spaced label/input | property `mono="true"` |

## Icons

- Icon luôn lấy từ bộ **Lucide**; thiếu thì tải và lưu theo rule **§13 Icons** (`.cursor/rules/13_icons.md`).

## Principles

- **Minimal text** — icon-first design
- **Consistent radius** — 6px inputs, 8px buttons/cards, 12px dialogs
- **Hover feedback** — subtle `rgba(255, 255, 255, 0.12)` background shift
- **Selection = Blue** — `rgba(37, 99, 235, ...)` tint + `#60a5fa` text
- **No focus rect** — no yellow focus frame

👉 Keep consistency with **MonoStudio (MONOS)**.
