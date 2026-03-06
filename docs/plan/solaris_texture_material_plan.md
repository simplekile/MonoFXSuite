# Plan: Auto Material Builder — Load texture & tạo Karma Material trong Solaris

## Pipeline Philosophy (rule 10)

| Câu hỏi | Trả lời |
|----------|---------|
| Who uses it? | FX / Lighting artist |
| Which pipeline step? | Lookdev / Material setup |
| Which DCC? | Houdini Solaris (đầu tiên) |
| Can another DCC reuse it? | Logic scan texture: **có** (DCC-agnostic). Material creation: **không** (adapter riêng mỗi DCC). |

---

## 1. Mục tiêu

- Chọn folder texture → tool **auto-detect** naming convention (pipeline hoặc generic) → scan & group thành material sets.
- Tạo Material Library LOP + Karma Material Builder trong Solaris, gắn texture vào đúng slot PBR, sẵn sàng assign.

## 2. Phạm vi chức năng

| Tính năng | Mô tả |
|-----------|--------|
| **Scan** | Scan tất cả image files trong folder + subfolders (recursive). |
| **Auto-detect** | Thử pipeline pattern trước → fail thì fallback generic keyword scan. |
| **Group by prefix** | Mỗi prefix = 1 material candidate. UI preview trước khi tạo. |
| **UDIM** | Detect `.XXXX.ext` → gom thành 1 entry, path dùng `%(UDIM)d` token. |
| **Color space** | Pipeline pattern: đọc từ filename. Generic: gán theo slot (base_color → sRGB, roughness/normal → RAW). |
| **Tạo LOP** | Material Library LOP → Karma Material Builder → MtlX Standard Surface + MtlX Image + MtlX Normal Map. |
| **Assign (optional)** | Assign Material LOP trỏ prim pattern. |
| **Group by subfolder (optional)** | Thay vì group by prefix, mỗi subfolder = 1 material. |

## 3. Naming convention

### 3.1 Pipeline pattern (ưu tiên 1)

```
{prefix}_{Slot}_{ColorSpace}.{UDIM}.{ext}

costume_BaseColor_ACES - ACEScg.1001.exr
costume_Roughness_Utility - Raw.1001.exr
costume_Normal_Utility - Raw.1001.exr
costume_EmissionColor_ACES - ACEScg.1025.exr
```

- **Prefix**: 1 token, viết liền hoặc nối `-`. Không chứa `_`.
- **Slot**: PascalCase, viết liền hoặc nối `-`. Phải match KNOWN_SLOTS.
- **ColorSpace**: phần còn lại sau slot (có thể chứa space, dash).
- **UDIM**: `.XXXX` (4 digits, 1001+) trước extension.
- **Separator**: `_` là boundary duy nhất giữa 3 phần.

Parse: `split("_", maxsplit=2)` sau khi strip ext + UDIM → `[prefix, slot, colorspace]`.

### 3.2 Generic keyword scan (fallback)

```
coast_sand_rocks_02_diff_2k.exr
Bricks076A_2K-JPG_Color.jpg
tezfbhyia_2K_Albedo.jpg
```

- Split tất cả separators (`_`, `-`, `.`).
- Scan tokens từ **phải sang trái**.
- Token match known keyword → slot. Skip resolution tokens (`2k`, `4k`, `1k`).
- Prefix = join tokens trước slot match.
- Keyword phải match **exact token** (không substring) → tránh false positive.

### 3.3 Auto-detect flow

```
file → try_pipeline_parse()
         ├─ ✅ → { prefix, slot, colorspace, udim }
         └─ ❌ → try_generic_parse()
                   ├─ ✅ → { prefix, slot, colorspace=None, udim }
                   └─ ❌ → unmatched (hiện riêng trong UI)

all parsed → group_by_prefix() → dict[prefix, dict[slot, info]]
```

## 4. Known slots & keyword aliases

| Slot (internal) | Pipeline (PascalCase) | Generic aliases | Color space mặc định |
|---|---|---|---|
| `base_color` | `BaseColor` | `diffuse`, `diff`, `albedo`, `color`, `col`, `basecolor` | sRGB / scene-linear |
| `roughness` | `Roughness` | `rough`, `rgh`, `roughness` | RAW |
| `metallic` | `Metallic`, `Metalness` | `metal`, `mtl`, `metallic`, `metalness` | RAW |
| `normal` | `Normal` | `normal`, `nrm`, `norm`, `nor` | RAW |
| `opacity` | `Opacity` | `opacity`, `alpha`, `mask` | RAW |
| `emission_color` | `EmissionColor` | `emissive`, `emission`, `emit` | sRGB / scene-linear |
| `displacement` | `Displacement` | `displacement`, `disp`, `height`, `bump` | RAW |
| `ao` | `AO`, `AmbientOcclusion` | `ao`, `occlusion`, `ambientocclusion` | RAW |
| `specular` | `Specular` | `specular`, `spec`, `refl` | RAW |

Config cho phép mở rộng / override bảng này.

## 5. Cấu trúc tool (rule 03)

```
tools/fx/auto_material/
    __init__.py
    config.py
    logic.py
    ui.py
    controller.py
```

### config.py

- `WINDOW_TITLE`
- `KNOWN_SLOTS`: dict slot → { pipeline_names, generic_aliases, default_colorspace }
- `IMAGE_EXTENSIONS`: `{".exr", ".png", ".jpg", ".jpeg", ".tif", ".tiff", ".rat", ".tex", ".hdr"}`
- `UDIM_PATTERN`: regex `r'\.\d{4}\.'`
- `RESOLUTION_TOKENS`: `{"1k", "2k", "4k", "8k", "16k"}`
- `PUBLISH_TEXTURE_RELATIVE_PATH`: `"../../../03_surfacing/publish"` (relative từ `$HIP`)

### logic.py (DCC-agnostic, no `hou`)

```python
def scan_images(folder: str, recursive: bool = True) -> list[str]
    """Scan folder (+ subfolders) cho image files theo IMAGE_EXTENSIONS."""

def try_pipeline_parse(filepath: str) -> ParseResult | None
    """Parse theo pipeline pattern. None nếu không match."""

def try_generic_parse(filepath: str) -> ParseResult | None
    """Parse theo generic keyword scan. None nếu không match."""

def auto_parse(filepath: str) -> ParseResult | None
    """Pipeline first, generic fallback."""

def group_by_prefix(results: list[ParseResult]) -> dict[str, MaterialGroup]
    """Group parsed results by prefix → material sets."""

def group_by_subfolder(results: list[ParseResult]) -> dict[str, MaterialGroup]
    """(Optional) Group by parent folder thay vì prefix."""
```

`ParseResult`: dataclass `{ filepath, prefix, slot, colorspace, udim, parse_mode }`.  
`MaterialGroup`: dataclass `{ prefix, slots: dict[str, SlotInfo], parse_mode }`.  
`SlotInfo`: dataclass `{ filepath, colorspace, udim }`.

### ui.py (PySide6, dark theme, rule 04)

- **Folder row**:
  - QLineEdit (path) + nút **Browse** (QFileDialog) + nút **Publish** (auto-fill `$HIP/../../../03_surfacing/publish`).
  - Nút Publish: resolve `$HIP` qua adapter → build absolute path → fill vào QLineEdit. Nếu folder không tồn tại → báo lỗi.
- Checkbox: "Recursive scan subfolders".
- Nút: **"Scan"** — trigger scan + parse + group.
- Material list: hiển thị grouped materials (prefix + slot count + badges `pipeline`/`generic`/`UDIM`).
- Slot detail: chọn material → hiện bảng slot → path (editable, browse từng dòng).
- Material name: QLineEdit (default = prefix).
- Unmatched files: section riêng (collapsible).
- Checkbox: "Create Assign Material LOP" + QLineEdit prim pattern.
- Nút: "Create Materials in Solaris".

### controller.py

- Entry point `run()`.
- Import adapter (Solaris).
- Scan → parse → group → show UI → user confirm → tạo LOP.

## 6. Adapter: `apps/houdini/solaris_adapter.py` (tách riêng khỏi adapter.py)

```python
def get_hip_dir() -> str | None
    """Trả về thư mục chứa file .hip hiện tại ($HIP). None nếu chưa save."""

def resolve_publish_texture_folder() -> str | None
    """Resolve $HIP/../../../03_surfacing/publish → absolute path. None nếu không tồn tại."""

def is_lop_context_available() -> bool
def get_stage_context() -> Any
def get_or_create_material_library(parent, name: str) -> Any
def create_karma_material_builder(mat_lib, name: str) -> Any
def create_mtlx_standard_surface(builder) -> Any
def create_mtlx_image(builder, slot: str, filepath: str, colorspace: str | None, udim: bool) -> Any
def create_mtlx_normal_map(builder) -> Any
def connect_slot(surface_node, image_node, slot: str, normal_map_node=None) -> bool
def create_assign_material(parent, material_path: str, prim_pattern: str) -> Any
def layout_nodes(builder) -> None
```

Lưu ý kỹ thuật:
- Tạo Karma Material Builder dùng `voptoolutils._setupMtlXBuilderSubnet` (private API).
- Wrap trong `try/except`, fallback tạo subnet thủ công + set tab filter.
- Ghi rõ Houdini version tối thiểu: H20.0+.

## 7. Node graph chi tiết

Trong Karma Material Builder, tạo VOP network:

```
MtlX Image (base_color)  ──────────────→ base_color input
MtlX Image (roughness, sig=float) ─────→ specular_roughness input
MtlX Image (metallic, sig=float) ──────→ metalness input
MtlX Image (normal) → MtlX Normal Map → normal input
MtlX Image (opacity, sig=float) ───────→ opacity input
MtlX Image (emission) ────────────────→ emission_color input
MtlX Image (displacement, sig=float) ──→ (Collect → displacement output)

                    MtlX Standard Surface
                            │
                         Collect
                            │
                     surface output
```

- Normal map: **bắt buộc** qua `MtlX Normal Map` trước khi nối surface.
- Data textures (roughness, metallic, opacity, displacement): signature `float`, force linear.
- Color textures (base_color, emission): signature `color3`, auto/sRGB.
- Pipeline files: set colorspace từ filename (vd `ACES - ACEScg`, `Utility - Raw`).
- UDIM: path dùng `%(UDIM)d` token trong parm `file`.

## 8. Workflow

1. User mở tool → UI.
2. Chọn folder → "Scan" (auto recursive).
3. Tool parse tất cả image files → group by prefix → UI hiện danh sách materials.
4. User review: check/uncheck material, chỉnh slot/path nếu cần, đặt tên material.
5. User bấm "Create Materials in Solaris":
   - Với mỗi material group đã check:
     - `get_or_create_material_library()`
     - `create_karma_material_builder(name)`
     - Tạo MtlX Standard Surface + MtlX Image per slot + connect.
     - (Optional) Tạo Assign Material LOP.
   - Layout nodes.
   - Thông báo kết quả.

## 9. Edge cases

| Case | Xử lý |
|------|--------|
| Folder rỗng / không có image | Báo lỗi, không tạo. |
| File không match cả 2 parser | Vào "unmatched", hiện riêng. |
| 1 slot có 2+ file cùng prefix | Lấy file đầu, báo conflict trong UI. |
| Không có LOP context | Báo "Mở Solaris / LOP network rồi thử lại". |
| Slot trống (vd chỉ có base_color) | Vẫn tạo material, slot khác để trống. |
| UDIM chỉ có vài tile | Vẫn gom, Houdini/Karma tự xử lý missing tiles. |
| `voptoolutils` thay đổi giữa Houdini versions | try/except + fallback thủ công. |
| Texture path absolute vs relative | Default absolute. Option `$HIP/...` nếu pipeline cần. |

## 10. Dependency (rule 09)

- `pathlib`, `re`, `dataclasses`, `typing` — cho logic.
- `PySide6` — cho UI.
- `hou`, `voptoolutils` — chỉ trong `solaris_adapter.py`.
- Không có external dependency.

## 11. Thứ tự triển khai

| Phase | Nội dung | Ghi chú |
|-------|----------|---------|
| **0** | Prototype trong `notes/` | Test `voptoolutils`, tạo material builder bằng script, xác nhận input names. Rule 08. |
| **1** | `config.py` | Slots, keywords, patterns, image extensions. |
| **2** | `logic.py` — pipeline parse | `try_pipeline_parse`, `scan_images`. |
| **3** | `logic.py` — generic parse | `try_generic_parse`, `auto_parse`, `group_by_prefix`. |
| **4** | `solaris_adapter.py` | `create_karma_material_builder`, `create_mtlx_standard_surface_and_images`. Minimal: base_color + roughness. |
| **5** | `ui.py` | Folder picker, material list, slot table, Create button. |
| **6** | `controller.py` | Nối UI ↔ logic ↔ adapter. |
| **7** | Mở rộng | Assign Material, thêm slots, group by subfolder option, batch. |
| **8** | **Auto assign** | Nút Auto assign: đọc scene graph từ LOP đã chọn, match prim `*_grp`/`*_Grp` với material `M_char_*` trong `/materials`. |

---

## Auto assign (phase 8)

### Mục tiêu

Một nút **Auto assign** cho phép:
- Đọc scene graph từ **node LOP đang chọn** (stage output của node đó).
- Tìm mọi prim có tên dạng `name_grp` hoặc `name_Grp`.
- Match với material trong `/materials` có tên `M_char_<name>` (ví dụ `Body_Grp` → `M_char_Body`).
- Tạo các LOP **Assign Material** tương ứng (prim pattern = path của prim _grp, material = path của material).

### Rule match

| Scene graph prim (tên) | Base name | Material trong `/materials` |
|------------------------|-----------|----------------------------|
| `Body_Grp`             | `Body`    | `M_char_Body`              |
| `Accessory_grp`        | `Accessory` | `M_char_Accessory`       |
| `Costume_Grp`          | `Costume` | `M_char_Costume`           |

- Prim name kết thúc bằng `_grp` hoặc `_Grp` → bỏ 4 ký tự cuối → base name.
- Material name có dạng `M_char_<Name>` → base name = phần sau `M_char_`.
- Match **case-sensitive**: chỉ gán khi base name trùng.

### Luồng xử lý

1. Lấy LOP node đang chọn → `node.stage()` (read-only stage).
2. Duyệt stage: với mỗi prim, nếu `GetName()` kết thúc `_grp` hoặc `_Grp` → lưu `(prim_path, base_name)`.
3. Đọc scope `/materials`: với mỗi child prim có tên `M_char_*` → `base_name = name[7:]`, `material_path = /materials/<name>`.
4. Với mỗi cặp (prim_path, base_name) mà có material tương ứng: tạo Assign Material LOP (prim pattern = prim_path, mat path = material_path), nối input sau node đã chọn (chain các assign).

### Vị trí UI

- Nút **Auto assign** đặt cạnh vùng “Create Assign Material LOP” / prim pattern (bottom row), hoặc trong cùng hàng với **Create Materials in Solaris**.

### Adapter (solaris_adapter.py)

- `get_stage_from_lop_node(lop_node)` → `pxr.Usd.Stage` (hoặc None).
- `find_grp_prim_paths_and_names(stage)` → `list[(prim_path: str, base_name: str)]`.
- `get_material_names_under_scope(stage, scope="/materials")` → `dict[base_name, material_path]`.
- `run_auto_assign(stage_node, selected_lop_node)` → `(created_count: int, message: str)` (tạo và chain các Assign Material LOP).

---

## Tài liệu tham khảo

- [Karma Materials](https://www.sidefx.com/docs/houdini/solaris/kug/materials.html)
- [Karma Textures](https://www.sidefx.com/docs/houdini/solaris/kug/textures.html)
- [SideFX Forum: Create Karma Material Builder with Python](https://www.sidefx.com/forum/post/426754/)
