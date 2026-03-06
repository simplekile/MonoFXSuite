# Plan: Node Preset Library

Tool lưu/load các node đang chọn vào thư viện preset, có thumbnail, category tùy chỉnh, và khả năng copy/import library qua máy khác.

---

## 1. Mục tiêu chức năng

| Yêu cầu | Mô tả |
|--------|--------|
| **Lưu nodes đang chọn** | Chọn một hoặc nhiều node (cùng parent) → Save to Library → đặt tên preset, chọn category → lưu file .hipnc + metadata. |
| **Paste thumbnail** | Trong form tạo/sửa preset: nút "Paste thumbnail" lấy ảnh từ clipboard (Ctrl+V) và lưu thành ảnh thumbnail của preset. |
| **Tự tạo category** | User tạo/đổi tên/xóa category. Category = folder + bản ghi trong index. |
| **Copy library sang máy khác & import** | Library nằm trong một folder (hoặc .zip). Copy folder/zip sang máy khác → trong tool chọn "Import library" → chọn folder/zip → merge hoặc replace. |

---

## 2. Cấu trúc thư mục Library (portable)

```
<library_root>/
├── index.json          # Danh sách categories + presets (id, name, category_id, file, thumbnail, created)
├── categories/
│   ├── <category_id>/   # Mỗi category một folder (slug từ tên)
│   │   ├── preset_<id>.hipnc
│   │   ├── preset_<id>_thumb.png
│   │   └── ...
│   └── ...
└── (optional) export_YYYYMMDD.zip  # Nếu user export ra zip
```

- **index.json** dùng đường dẫn tương đối (relative) so với library root để copy sang máy khác vẫn đúng.
- **category_id**: slug (lowercase, no spaces) để làm tên folder. Tên hiển thị lưu trong index.

---

## 3. Định dạng index.json

```json
{
  "version": 1,
  "categories": [
    { "id": "sop_utils", "name": "SOP Utils", "order": 0 }
  ],
  "presets": [
    {
      "id": "uuid-hoac-slug",
      "name": "My ROP chain",
      "category_id": "sop_utils",
      "file": "categories/sop_utils/preset_abc123.hipnc",
      "thumbnail": "categories/sop_utils/preset_abc123_thumb.png",
      "created": "2025-03-07T12:00:00",
      "node_count": 3
    }
  ]
}
```

- `id` preset: UUID hoặc slug unique.
- `file` / `thumbnail`: path tương đối từ library root; thumbnail có thể null nếu chưa paste.

---

## 4. Luồng nghiệp vụ

### 4.1 Lưu preset (Save to Library)

1. User chọn nodes trong network (cùng một parent).
2. Mở dialog "Save to Library":
   - Name (bắt buộc).
   - Category: dropdown + nút "New category".
   - Thumbnail: nút "Paste thumbnail" (đọc QClipboard image, lưu PNG).
3. Validate: ít nhất 1 node, cùng parent, tên không trống.
4. Ghi file:
   - Parent node gọi `saveItemsToFile(selected_items, path_to_hipnc)` (Houdini API).
   - Tạo/ghi category folder nếu cần.
   - Lưu thumbnail nếu đã paste.
   - Cập nhật index.json (thêm category nếu mới, thêm preset).

### 4.2 Load preset (Insert từ Library)

1. Mở panel Library: list categories bên trái, list presets (có thumbnail) bên phải.
2. User chọn preset → nút "Insert" (hoặc double-click).
3. Lấy context Houdini: network hiện tại (hou.pwd() hoặc node từ network editor).
4. Parent node gọi `loadItemsFromFile(path_to_hipnc)`.
5. (Optional) Houdini có thể select items vừa load; có thể dùng `pasteItemsFromClipboard(position)` nếu ta copy vào clipboard rồi paste tại vị trí con trỏ.

Chú ý: `loadItemsFromFile` load vào parent; không trả về danh sách items. Có thể clear selection, load, rồi dùng `hou.selectedItems()` để lấy items vừa load (theo SideFX forum).

### 4.3 Thumbnail: Paste từ clipboard

- UI: nút "Paste thumbnail" trong form Save/Edit preset.
- PySide6: `QApplication.clipboard().image()` → nếu có image thì save thành PNG vào path `categories/<cat_id>/preset_<id>_thumb.png`, cập nhật field `thumbnail` trong index.

### 4.4 Category: Tạo / Đổi tên / Xóa

- **Tạo**: Dialog nhập tên → slug = id (lowercase, replace spaces by `_`) → tạo folder `categories/<id>`, thêm vào `index.categories`.
- **Đổi tên**: Chỉ đổi `name` trong index (giữ `id` để không phá path).
- **Xóa**: Xóa category khỏi index; presets thuộc category đó: hoặc chuyển sang "Uncategorized" (category_id null hoặc category mặc định) hoặc xóa luôn preset (tùy thiết kế). Nếu xóa category thì có thể xóa folder `categories/<id>` khi không còn preset nào.

### 4.5 Copy library sang máy khác & Import

- **Vị trí library mặc định**: Ví dụ `$HOUDINI_USER_PREF_DIR/monofx_node_preset_library` hoặc trong MonoFXSuite (configurable).
- **Export (copy)**: User mở "Library location" → copy cả folder library (hoặc nén thành .zip) sang máy khác.
- **Import trên máy mới**:
  - Menu "Import library…" → chọn folder (hoặc file .zip).
  - Nếu zip: giải nén vào thư mục tạm, đọc index.json.
  - Merge: giữ library hiện tại, thêm categories/presets từ import (trùng id thì overwrite hoặc rename).
  - Hoặc Replace: xóa nội dung library hiện tại (hoặc backup) rồi copy/merge toàn bộ từ import.
- Sau import, reload index và refresh UI.

---

## 5. Houdini API cần dùng

- **Lấy parent của selection**: `nodes = hou.selectedNodes()` (hoặc `hou.selectedItems()` nếu cần cả sticky notes/boxes). Kiểm tra tất cả cùng parent: `parent = nodes[0].parent()`.
- **Lưu items ra file**: `parent.saveItemsToFile(items, file_path, save_hda_fallbacks=False)`. Items phải là con của `parent` (ví dụ `hou.selectedItems()` lọc theo parent).
- **Load vào network**: Xác định target parent (ví dụ `hou.pwd()` hoặc node từ network editor). `parent.loadItemsFromFile(hipnc_path)`. Sau đó có thể dùng `hou.selectedItems()` nếu Houdini select items vừa load.
- **Vị trí paste**: Nếu cần paste tại vị trí con trỏ, có thể dùng `copyItemsToClipboard` → `pasteItemsFromClipboard(position)`; với file thì load rồi move items bằng script (phức tạp hơn). Giai đoạn 1 có thể chỉ cần load vào parent, chưa cần đặt vị trí.

Tất cả gọi Houdini nên nằm trong **adapter** (ví dụ `apps/houdini/adapter.py` hoặc `apps/houdini/node_preset_adapter.py`) để tools không import `hou` trực tiếp.

---

## 6. Cấu trúc code gợi ý (MonoFXSuite)

```
tools/fx/node_preset_library/
├── __init__.py
├── config.py           # WINDOW_TITLE, LIBRARY_FOLDER_NAME, index version
├── controller.py       # run(), nối UI ↔ logic ↔ adapter
├── logic.py            # Đọc/ghi index.json, tạo category/preset id, path helpers
├── ui.py               # Dialog Save; Panel Library (categories + grid presets, paste thumbnail)
└── icons/              # (optional)
```

- **Adapter** (trong `apps/houdini/`):
  - `get_selected_network_items()` → list items (nodes + boxes + sticky notes) cùng parent.
  - `get_parent_for_items(items)`.
  - `save_items_to_file(parent, items, path)` → gọi `parent.saveItemsToFile(...)`.
  - `load_items_from_file(parent, path)` → gọi `parent.loadItemsFromFile(...)`.
  - `get_current_network_context()` → node dùng làm parent khi insert (ví dụ `hou.pwd()`).

- **Logic** (không import hou):
  - `get_library_root()`: từ config hoặc env.
  - `load_index()`, `save_index()`.
  - `add_category(name)`, `rename_category(id, name)`, `delete_category(id)`.
  - `add_preset(name, category_id, hipnc_relative_path, thumbnail_relative_path, node_count)`, `update_preset_thumbnail(...)`, `delete_preset(id)`.
  - `resolve_path(library_root, relative_path)`.
  - Export/Import: `import_library_from_folder(path)` (merge/replace), `import_library_from_zip(path)`.

---

## 7. UI (tóm tắt)

- **Save to Library**: Dialog có Name, Category (combo + New category), Paste thumbnail, [Save] [Cancel].
- **Library panel**: Sidebar categories (list); Content: grid hoặc list presets (thumbnail + tên); nút Insert, nút Edit (đổi tên/thumbnail/category), nút Delete preset. Toolbar: Import library, Export (mở folder / tạo zip), Settings (library path).
- **Paste thumbnail**: Chỉ hoạt động khi clipboard có ảnh; có thể hiển thị preview nhỏ sau khi paste.

---

## 8. Thứ tự triển khai gợi ý

1. **Config + Logic**: index format, library root, load/save index, add category/preset (file path, thumbnail path).
2. **Adapter**: Houdini calls (selected items, parent, saveItemsToFile, loadItemsFromFile, current network).
3. **UI cơ bản**: Save to Library (name, category, paste thumbnail), lưu .hipnc + index.
4. **UI Library panel**: List categories, list presets với thumbnail, Insert.
5. **Category**: New / Rename / Delete.
6. **Import/Export**: Import from folder (merge/replace), Export folder hoặc zip; copy sang máy khác và import.
7. **Tinh chỉnh**: Edit preset (tên, category, thumbnail), xóa preset, xử lý lỗi (file thiếu, Houdini chưa mở, v.v.).

---

## 9. Lưu ý

- **Cùng parent**: Khi save, bắt buộc mọi item chọn cùng một parent; nếu không thì báo lỗi "Select nodes from the same network".
- **HDA**: `save_hda_fallbacks=True` làm file lớn hơn nhưng load được ở máy chưa có HDA; có thể cho user chọn (checkbox "Embed HDA definitions").
- **Thumbnail**: Chỉ hỗ trợ paste từ clipboard (image). Có thể sau này thêm "Capture from viewport" nếu cần.
- **Conflict id**: Khi import, nếu category hoặc preset trùng id thì merge: overwrite hoặc thêm suffix (tùy product decision).

Khi implement, bắt đầu từ bước 1–3 để có luồng "chọn node → save → có thumbnail → insert lại" end-to-end, rồi mở rộng category và portable library.
