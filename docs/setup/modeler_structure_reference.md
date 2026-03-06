# Tham khảo cấu trúc plugin Modeler (Houdini)

Cấu trúc plugin Modeler trong user folder được dùng làm mẫu cho MonoFX (toolbar, icons, package).

## Package — `packages/modeler.json`

```json
{
    "enable": true,
    "path": "$HOUDINI_USER_PREF_DIR/modeler",
    "env": [
        {
            "var": "MODELER_PATH",
            "value": "$HOUDINI_USER_PREF_DIR/modeler"
        }
    ]
}
```

- **path**: thư mục gốc plugin được thêm vào HOUDINI_PATH (tương đương `hpath`).
- **env**: biến `MODELER_PATH` trỏ tới cùng thư mục, để script/python dùng.

File này nằm trong `Documents\houdini21.0\packages\` (hoặc `$HOUDINI_USER_PREF_DIR/packages/`). Houdini quét `packages` trong user prefs nên không cần set `HOUDINI_PACKAGE_DIR` cho modeler.

## Cấu trúc thư mục `modeler/`

```
modeler/
├── config/
│   └── Icons/           ← Houdini tìm icon theo tên (config/Icons trên HOUDINI_PATH)
│       ├── MODELER_Fill.svg
│       ├── MODELER_Bridge.svg
│       └── ...
├── toolbar/
│   └── modeler.shelf    ← Shelf tab + tools
├── python3.11libs/
│   └── modeler/         ← Python module
├── viewer_states/       ← Viewer state scripts
└── radialmenu/          ← Radial menu definitions
```

- **config/Icons/** — Icon SVG; trong shelf dùng **chỉ tên** (không path, không .svg), ví dụ `icon="MODELER_Fill"` → file `config/Icons/MODELER_Fill.svg`.
- **toolbar/*.shelf** — Shelf được load từ HOUDINI_TOOLBAR_PATH (mặc định gồm các thư mục trên HOUDINI_PATH + `/toolbar`). Vì `path` trỏ tới `modeler/`, nên `modeler/toolbar/` nằm trên path và được quét.

## Shelf — tham chiếu icon

Trong `modeler.shelf`:

```xml
<tool name="modeler::fill" label="Fill" icon="MODELER_Fill">
```

- **icon**: chỉ tên icon (tương ứng file `config/Icons/MODELER_Fill.svg`), không ghi `config/Icons/...` hay `.svg`.

## Áp dụng cho MonoFX

- **Folder riêng (giống modeler):** Installer tạo `Documents\houdiniXX.X\monofx\` với `monofx/config/Icons/`, `monofx/toolbar/MonoFX.shelf`. File `packages/monofx_shelf.json` có `"hpath": "$HOUDINI_USER_PREF_DIR/monofx"` để Houdini tìm shelf và icon; code vẫn load từ bộ cài qua package chính.
- **Icons**: Trong shelf dùng `icon="info"` (tên file không .svg) → file `config/Icons/info.svg` trong folder `monofx`.
- **Package chính**: MonoFX dùng `HOUDINI_PACKAGE_DIR` + `hpath: "$MONOFX_SUITE"`. Cài toàn bộ kiểu “user prefs” như modeler: copy cả bộ vào `$HOUDINI_USER_PREF_DIR/monofx` và dùng package có `"path": "$HOUDINI_USER_PREF_DIR/monofx"` (xem `docs/setup/monofx_user_prefs_example.json`).
- **Toolbar**: Shelf file trong `toolbar/MonoFX.shelf`; cấu trúc toolshelf/tool giống modeler.
