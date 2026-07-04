# Blender Plugin UI — MonoFX Pipeline

Áp dụng khi làm UI cho `tools/fx/monofx_pipeline_blender/`. Tham chiếu: `ui_style.py`, `rig_ui.py`, `preferences.py`.

**Không áp dụng** cho Maya/Houdini/PySide6 — xem `04_ui_standard.md`.

---

## Chiến lược UI

- **Chỉ dùng UI native Blender** (`Panel`, `Menu`, `Operator`, `UILayout`).
- **Không** GPU overlay, Web/CEF, pie menu tùy chỉnh — trừ khi có yêu cầu rõ ràng và được approve.
- Vị trí chuẩn: `bl_space_type='VIEW_3D'`, `bl_region_type='UI'`, `bl_category='MonoFX'`.

---

## Cấu trúc panel

- Tab workflow: `ui_style.draw_panel_tabs()` + `EnumProperty` trong prefs.
- Nhóm chức năng: `ui_style.section()` — foldout, lưu open/closed trong addon prefs.
- Phần hay dùng: `default_closed=False` (vd. Hierarchy). Phần nâng cao: đóng mặc định.
- **Nút hành động chính** (Publish, Link, Export) đặt **cuối** mỗi box; có thể `scale_y` lớn hơn.
- Icon: enum Blender hợp lệ (Blender 5.x) — không legacy alias. Trạng thái: `status_label()` + `layout.alert`.

---

## Operators & data

- Thao tác sửa scene: `bl_options = {'REGISTER', 'UNDO'}`.
- File I/O (publish USD): `REGISTER` không UNDO — OK, nhưng cần `report()` rõ ràng.
- Property pipeline: `bpy.props` trên `Scene` / addon prefs; logic tách khỏi `draw()`.
- `poll()` trên Panel/Operator khi chỉ hiện trong mode/context phù hợp.

---

## Hiệu suất (bắt buộc)

- **Không** scan filesystem, refresh library, hoặc query `bpy.data` nặng trong `draw()`.
- **Không** gọi `bpy.ops` trong `draw()`.
- Cache + debounce: `bpy.app.timers`, `bpy.msgbus` (pattern: `rig_linking.py`).
- Thumbnail: `bpy.utils.previews` — load một lần, clear khi unregister.

---

## Feedback & discoverability

- Tác vụ >1s (export USD, refresh rig): `wm.progress_begin/update/end` hoặc status trong panel.
- Kết quả: `self.report({'INFO'|'WARNING'|'ERROR'}, ...)`.
- `bl_label`, `bl_description` trên Panel/Operator.
- Context menu cho list phức tạp (pattern: `rig_ui.py`).
- Keymap (addon keyconfig) cho thao tác hay dùng — ưu tiên sau khi UI ổn định.

---

## Theme & i18n

- Không gán màu RGB cứng — dùng theme Blender (`layout.alert`, icon enum).
- Chuỗi UI có thể bọc `bpy.app.translations` + `.po` nếu cần tiếng Việt.

---

## Ưu tiên roadmap UI

| P | Việc |
|---|------|
| P0 | Audit `draw()` — không logic nặng mỗi frame |
| P0 | Progress/status cho Publish & Refresh Rig |
| P1 | Keymap 3–5 thao tác thường dùng |
| P1 | Usability test nội bộ (click count, time-on-task) |
| P2 | i18n |
| P3 | Gizmo/modal/HUD — chỉ khi có tool tương tác viewport |

---

## Anti-patterns

- UI phức tạp kiểu Hard Ops (quá nhiều nút một panel, không foldout).
- Draw handler GPU không cleanup → leak.
- `depsgraph_update_post` gọi logic nặng mỗi frame.
