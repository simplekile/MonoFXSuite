# Selectable List Pattern

Rule cho list chọn đơn / chọn nhiều và picker dialog. Áp dụng khi cần list có ID + label, multi-select, hoặc dialog "Add" (chọn nhiều rồi trả về danh sách id).

---

## 1. Hai kiểu list

| Kiểu | Mục đích | Selection (Qt) | ObjectName | Dùng khi |
|------|----------|----------------|------------|----------|
| **Single** | Chọn đúng một mục | `SingleSelection` | `SelectableList` | Nav, filter active (vd: 1 department đang xem). |
| **Multi** | Chọn nhiều mục (bật/tắt) | `MultiSelection` hoặc `ExtendedSelection` | `SelectableListMulti` | Picker dialog, visibility (vd: path/material cần giữ). |

---

## 2. Dữ liệu mỗi item

- **ID**: định danh (string) — so sánh, lưu state, emit.
- **Label**: text hiển thị.
- **Icon** (optional): icon 16px.

Lưu id vào item:

- **Flat list**: `item.setData(Qt.ItemDataRole.UserRole, item_id)` (string).
- **Structured** (section/spacer): row thật dùng dict `{"type": "row", "id": item_id}`; section/spacer không selectable, không có id.

---

## 3. Build list (flat)

```python
for (item_id, label, *rest) in items:  # rest = icon optional
    it = QListWidgetItem(label)
    it.setData(Qt.ItemDataRole.UserRole, item_id)
    if icon: it.setIcon(...)
    list.addItem(it)
    if item_id in selected:
        it.setSelected(True)
```

- `items`: `[(id, label)]` hoặc `[(id, label, icon_name)]`.
- `selected`: `set[str]` id cần pre-select (picker dialog).

---

## 4. Đọc selection

- **Flat** (UserRole = string): duyệt item theo thứ tự, `if item.isSelected(): out.append(item.data(Qt.ItemDataRole.UserRole))`.
- Trả về **list[str]** giữ thứ tự trong list.

```python
def selected_items(self) -> list[str]:
    out = []
    for i in range(self.count()):
        it = self.item(i)
        if it and it.isSelected():
            val = it.data(Qt.ItemDataRole.UserRole)
            if val is not None:
                out.append(str(val))
    return out
```

---

## 5. Cấu hình widget (reference)

- `setObjectName("SelectableListMulti")` (hoặc `SelectableList` cho single).
- `setSelectionMode(QAbstractItemView.MultiSelection)` hoặc `ExtendedSelection`.
- `setFocusPolicy(Qt.FocusPolicy.StrongFocus)`.
- `setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)`.
- `setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)`.
- `setIconSize(QSize(16, 16))`.
- `selectionModel().selectionChanged.connect(sync_hint)` — cập nhật "Selected: N" nếu có.

---

## 6. Style (QSS) — MONOS palette

### SelectableList (single-select)

```css
QListWidget#SelectableList {
    background-color: #0d0d0f;
    border: none;
    outline: none;
    padding: 5px;
}
QListWidget#SelectableList::item {
    background-color: transparent;
    color: #888888;
    padding: 8px 12px;
    margin-bottom: 2px;
    border-radius: 6px;
    font-size: 13px;
    font-weight: 500;
    border-left: 3px solid transparent;
}
QListWidget#SelectableList::item:hover {
    background-color: rgba(255, 255, 255, 0.03);
    color: #eeeeee;
}
QListWidget#SelectableList::item:selected {
    background-color: rgba(37, 99, 235, 0.10);
    color: #2563eb;
    border-left: 3px solid #2563eb;
    font-weight: 700;
}
```

### SelectableListMulti (multi-select)

```css
QListWidget#SelectableListMulti {
    background-color: #0d0d0f;
    border: none;
    outline: none;
    padding: 5px;
}
QListWidget#SelectableListMulti::item {
    background-color: transparent;
    color: #888888;
    padding: 8px 12px;
    margin-bottom: 2px;
    border-radius: 6px;
    font-size: 13px;
    font-weight: 500;
}
QListWidget#SelectableListMulti::item:hover {
    background-color: rgba(255, 255, 255, 0.03);
    color: #eeeeee;
}
QListWidget#SelectableListMulti::item:selected {
    background-color: rgba(37, 99, 235, 0.10);
    color: #2563eb;
    font-weight: 700;
}
```

Key differences vs single: multi **không có border-left** indicator.

---

## 7. Drag (optional) — "tô" theo trạng thái điểm bắt đầu

Khi cần kéo thả để chọn/bỏ chọn cả vùng (không toggle từng item trong vùng):

- **Bắt đầu từ item đang bật** → toàn bộ vùng kéo = **bật** (selection = saved | range_rows).
- **Bắt đầu từ item đang tắt** → toàn bộ vùng kéo = **tắt** (selection = saved - range_rows).
- **Click không kéo** → toggle 1 item (saved ^ {row}).

Luồng:

1. **Press**: lưu `_drag_saved_rows`, `_drag_start_row`, `_drag_paint_on = (start_row in saved)`, `_drag_did_move = False`. Không đổi selection.
2. **Move**: `_drag_did_move = True`; range = start → current row; áp dụng `saved | range` hoặc `saved - range` theo `_drag_paint_on`.
3. **Release**: nếu `not _drag_did_move` → click → áp dụng `saved ^ {start_row}`; xóa state.

Dùng `_apply_selection(rows: set[int])` chung (clear rồi select từng row).

---

## 8. Picker dialog flow (Add)

1. Nút "+" → mở dialog với `items` = full list, `selected` = visible hiện tại.
2. Dialog: `QListWidget` (SelectableListMulti), `build_list(items, selected)`.
3. User chọn/bỏ chọn; hint "Selected N" cập nhật qua `selectionChanged`.
4. Done → `selected_items()` → list id (giữ thứ tự).
5. Caller gán state (visible) từ list đó; nếu "active" không còn trong list → clear active; rebuild UI.

---

## 9. Tóm tắt

- **Data**: UserRole = id (string); label (và optional icon).
- **Build**: `build_list(items, selected)` — flat hoặc structured.
- **Read**: `selected_items() -> list[str]` — duyệt item, selected thì lấy id, giữ thứ tự.
- **Style**: MONOS palette — nền `#0d0d0f`, selected `rgba(37, 99, 235, 0.10)` + text `#2563eb`.
- **Drag** (optional): paint on/off theo item bắt đầu; click = toggle 1.

Reference implementation: `tools/fx/split_geometry/ui.py` — class `SelectableListMulti`.
