# Houdini setup — MonoFX Suite

> **Lưu ý quan trọng:** Trong Houdini, **Python Shell** chạy **từng dòng** (interactive). Để chạy block nhiều dòng, dùng **Python Source Editor** (Windows → Python Source Editor) — paste code vào rồi bấm **Apply** hoặc **Ctrl+Enter**.

## 1. Add pipeline to Houdini Python path

Choose one: **Packages** (recommended for pipeline) or **123.py** (quick / single machine).

---

### Option 1: Packages (recommended)

Houdini loads a **package** at startup and sets `PYTHONPATH` from one config. No per-user script copy; easy to deploy with one env var.

**Nếu cài bằng installer (MonoFXSuite_Setup.exe):** installer (1) **thêm** thư mục `packages` của MonoFX vào biến `HOUDINI_PACKAGE_DIR` (không ghi đè); (2) tạo **folder riêng** `monofx` trong user Houdini (giống plugin modeler): `Documents\houdiniXX.X\monofx\` chứa `config\Icons\` và `toolbar\MonoFX.shelf`; (3) ghi file `packages\monofx_shelf.json` để thêm `$HOUDINI_USER_PREF_DIR/monofx` vào HOUDINI_PATH (shelf và icon nằm gọn trong một folder). Code (apps, core, tools) vẫn load từ bộ cài qua package chính. Chỉ cần **mở lại Houdini** sau khi cài.

**Cài tay (clone repo / copy files):**

1. Set `HOUDINI_PACKAGE_DIR` **trước khi** mở Houdini, trỏ tới thư mục `packages` của suite:

   - **Windows (user):**  
     `set HOUDINI_PACKAGE_DIR=e:\00 Project\Pipeline\MonoFXSuite\packages`
   - **Windows (system):**  
     System Properties → Environment Variables → New → `HOUDINI_PACKAGE_DIR` = `e:\00 Project\Pipeline\MonoFXSuite\packages`
   - **macOS/Linux:**  
     `export HOUDINI_PACKAGE_DIR=/path/to/MonoFXSuite/packages`

2. Start Houdini. The package `packages/monofx.json` sets `MONOFX_SUITE`, prepends it to `PYTHONPATH`, and adds it to `HOUDINI_PATH` (`hpath`), so `core` and `tools` are importable and the **MonoFX** toolbar tab (from `toolbar/MonoFX.shelf`) is loaded automatically.

**If you copy the package into your user packages folder** (e.g. `Documents/houdiniXX.X/packages/`), use `monofx_standalone.json` instead: copy that file (not `monofx.json`), set `MONOFX_SUITE` to the MonoFXSuite repo root (system env or `houdini.env`), then start Houdini. That package only prepends `$MONOFX_SUITE` to `PYTHONPATH`.

**Nhiều package cùng lúc:** `HOUDINI_PACKAGE_DIR` có thể chứa nhiều thư mục, cách nhau bằng `;` (Windows). Ví dụ: `C:\MonoFXSuite\packages;D:\modeler\packages`. Houdini quét tất cả và load mọi file `.json` trong từng thư mục — không bị loạn, mỗi tool giữ đúng folder của nó. Installer MonoFX chỉ **thêm** path của mình vào biến (append), không xóa path có sẵn; khi gỡ cài chỉ xóa đúng path MonoFX.

**Lỗi "cannot locate suite root" / MONOFX_SUITE trỏ vào Documents\\houdini21.0:** Nếu bạn có file `monofx.json` hoặc `monofx_standalone.json` trong `Documents\houdini21.0\packages\`, Houdini sẽ load nó và set `MONOFX_SUITE` = thư mục user (sai). **Cách xử lý:** Xóa hoặc đổi tên file đó; set `HOUDINI_PACKAGE_DIR` = thư mục `packages` của bộ cài (vd. `C:\Program Files\MonoFXSuite\packages`); thoát Houdini hoàn toàn rồi mở lại. Shelf tool cũng thử tự tìm tại `%ProgramFiles%\MonoFXSuite` nếu env chưa set.

---

### Option 2: `123.py` (simple / dev)

Create or edit `123.py` in your Houdini user script path:

- **Windows:** `Documents\houdiniXX.X\scripts\123.py`
- **macOS/Linux:** `~/houdiniXX.X/scripts/123.py`

```python
# 123.py — runs when Houdini starts
import sys
from pathlib import Path

SUITE_ROOT = Path(r"e:\00 Project\Pipeline\MonoFXSuite")
if SUITE_ROOT.is_dir() and str(SUITE_ROOT) not in sys.path:
    sys.path.insert(0, str(SUITE_ROOT))
```

Each machine/path needs this file updated. Use **Packages** when you want one config and easier deployment.

---

### Run once (nếu chưa dùng Packages / 123.py)

Chạy **từng dòng** trong **Python Shell**, hoặc paste cả block trong **Python Source Editor**:

```python
import sys; from pathlib import Path; sys.path.insert(0, str(Path(r"e:\00 Project\Pipeline\MonoFXSuite")))
```

## 2. Use the Houdini adapter in tools

Only **apps/houdini/** should `import hou`. Tool controllers use the adapter:

```python
# tools/fx/my_tool/controller.py
from apps.houdini import adapter as houdini_adapter

def run():
    if not houdini_adapter.is_available():
        return
    path = houdini_adapter.get_hip_path()
    nodes = houdini_adapter.get_selected_nodes()
    # ... call logic.py (no hou there)
```

## 3. Project layout (reminder)

- **apps/houdini/** — Houdini-only code (bootstrap, adapter).
- **tools/** — Pipeline tools; controller uses adapter, logic is DCC-agnostic.
- **core/** — No `hou`, no DCC APIs.

## 4. Chạy tools

**Nếu gặp lỗi `ModuleNotFoundError: No module named 'tools'`:** Python chưa tìm thấy thư mục MonoFXSuite. Bạn cần **thêm path** trước khi `import tools...`: dùng **Packages** (mục 1) hoặc **123.py**, hoặc chạy dòng `sys.path.insert(...)` trước.

> **Python Shell** = từng dòng. **Python Source Editor** = paste block nhiều dòng.  
> Các ví dụ dưới đây viết cho **Python Source Editor** (paste cả block → Apply).  
> Nếu dùng **Python Shell**, chạy từng dòng một hoặc gộp thành 1 dòng bằng `;`.

### Bước 1: Mở Houdini

Mở **Houdini** (sau khi đã set `HOUDINI_PACKAGE_DIR` hoặc chạy installer, hoặc dùng 123.py). Nếu dùng package: tool shelf sẽ được load, nhưng **có thể chưa hiện tab ngay** vì Houdini đang dùng shelf set khác. Vào **shelf set dropdown** (góc trái của shelf) và chọn **MonoFX Suite** để thấy tab **MonoFX**.

### Bước 2: Thêm path (nếu chưa dùng Packages)

**Python Shell** (1 dòng):

```python
import sys; from pathlib import Path; sys.path.insert(0, str(Path(r"e:\00 Project\Pipeline\MonoFXSuite")))
```

**Python Source Editor** (block):

```python
import sys
from pathlib import Path
SUITE_ROOT = Path(r"e:\00 Project\Pipeline\MonoFXSuite")
if str(SUITE_ROOT) not in sys.path:
    sys.path.insert(0, str(SUITE_ROOT))
```

### Scene Info (test tool)

**Python Shell** (đã có path):

```python
from tools.fx.scene_info import run; run()
```

**Python Source Editor** (full block):

```python
import sys
from pathlib import Path
_root = Path(r"e:\00 Project\Pipeline\MonoFXSuite")
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

from tools.fx.scene_info import run
run()
```

→ Mở cửa sổ hiển thị **đường dẫn .hip hiện tại** và **số node đang chọn**.

### Split Geometry (tách theo path / name / material)

Chọn một SOP node (geometry có string attribute: path, name, shop_materialpath, …).

**Python Shell:**

```python
from tools.fx.split_geometry import run; run()
```

**Python Source Editor:**

```python
import sys
from pathlib import Path
_root = Path(r"e:\00 Project\Pipeline\MonoFXSuite")
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

from tools.fx.split_geometry import run
run()
```

### Search & Replace

**Python Shell:**

```python
from tools.fx.search_replace import run; run()
```

**Python Source Editor:**

```python
import sys
from pathlib import Path
_root = Path(r"e:\00 Project\Pipeline\MonoFXSuite")
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

from tools.fx.search_replace import run
run()
```

### Auto Material Builder (tạo Karma material từ texture)

Mở **Solaris / LOP context** (vd. `/stage`).

**Python Shell:**

```python
from tools.fx.auto_material import run; run()
```

**Python Source Editor:**

```python
import sys
from pathlib import Path
_root = Path(r"e:\00 Project\Pipeline\MonoFXSuite")
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

from tools.fx.auto_material import run
run()
```

Tool mở cửa sổ:
1. Chọn folder texture (hoặc bấm **Publish** để auto-fill `$HIP/../../../03_surfacing/02_texturing/publish`).
2. Bấm **Scan** → tool scan tất cả image files, auto-detect naming (pipeline hoặc generic), group theo prefix.
3. Xem danh sách materials + slots ở bảng bên phải.
4. Bấm **Create Materials in Solaris** → tạo Material Library + Karma Material Builder + MtlX Standard Surface + texture nodes.

## 5. Hot-reload khi đang phát triển

Không cần restart Houdini sau khi sửa code. Mỗi tool có `reload_and_run()` — reload tất cả module rồi chạy lại:

**Python Shell:**

```python
from tools.fx.auto_material import reload_and_run; reload_and_run()
```

Thứ tự reload: `config` → `logic` → `adapter` → `ui` → `controller` → `run()`.

> **Lưu ý:** `reload_and_run()` chỉ dùng khi dev. Production dùng `run()` bình thường.

## 6. Next steps

- **Đã có:** Shelf tab **MonoFX** (tự tạo bởi package qua `toolbar/MonoFX.shelf`) với các nút Scene Info, Split Geometry, Search & Replace, Auto Material. Không cần thêm shelf button thủ công.
- Duplicate `tools/fx/scene_info/` as a template for new tools (controller, logic, ui, config).
