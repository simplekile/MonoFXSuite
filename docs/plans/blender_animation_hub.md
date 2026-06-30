# Plan: Blender Animation Hub — Floating Panel & Pie Menu

Add-on **không clone tính năng** — gom shortcut tới operators có sẵn từ AniMate Core, Animation Layers, ARP, và Blender native. Giải quyết pain point: **chuyển tab N-panel quá nhiều**.

---

## 1. Bối cảnh user

| Đã có | Pain point |
|-------|------------|
| Auto-Rig Pro | Rig + retarget + export — không cần thay |
| AniMate Core | Tính năng tốt nhưng panel rải nhiều tab/editor |
| Animation Layers | Panel ở Animation tab + có thể ở nhiều editor |

**Mục tiêu:** Một điểm truy cập cố định (floating / pie) — user **tự gắn** operators hay dùng.

---

## 2. Giải pháp: Animation Hub

### 2.1 Khái niệm

**Hub** = launcher layer:

```
User nhấn hotkey / mở floating panel
    → Pie menu hoặc grid nút
        → bpy.ops.<addon>.<operator>()   # gọi operator gốc, không reimplement
```

Không copy logic AniMate / Animation Layers — chỉ **delegate** tới operator đã register.

### 2.2 UI options — So sánh

| Kiểu UI | Ưu | Nhược | Phù hợp |
|---------|-----|-------|---------|
| **Pie menu** (8 hướng) | Nhanh, một tay, quen với Blender | Giới hạn slot; khó hiện label dài | Hotkey chính khi animate |
| **Popover panel** | Gắn viewport, không chiếm N-tab | Blender popover nhỏ, không “float” tự do | Quick access cạnh 3D view |
| **Popup dialog** | Nhiều nút, scroll, section | Phải mở/đóng mỗi lần | Bộ tool đầy đủ hơn pie |
| **Panel `WINDOW` region** | Gần floating nhất trong Blender | API ít ổn định hơn pie | Tùy chọn nâng cao |

**Khuyến nghị MVP:** Pie menu (hotkey) + Popup hub (phím phụ hoặc nút header) — **không** cố làm true floating window độc lập (Blender hạn chế).

### 2.3 User customization

Mỗi **slot** (pie wedge hoặc grid cell) lưu:

```json
{
  "id": "slot_01",
  "label": "AnimOffset",
  "operator": "animatepro.anim_offset",
  "operator_props": {},
  "icon": "MOD_OFFSET",
  "invoke": "INVOKE_DEFAULT",
  "context_override": null,
  "source_addon": "AniMate Pro",
  "enabled": true
}
```

**Workflow gán slot:**

1. Mở Hub Preferences hoặc chế độ **Edit Layout**
2. Click slot trống → **Pick Operator** (search giống F3)
3. Hoặc chọn từ **Preset pack** (AniMate / Anim Layers / ARP / Native)
4. Kéo thả reorder (pie position 1–8, hoặc grid order)

**Nhiều layout:**

| Layout | Ví dụ |
|--------|-------|
| `Blocking` | Key all, mirror pose, constant interp |
| `Polish` | AnimOffset, graph tools, euler filter |
| `Layers` | Add layer, mute, solo, bake, inbetweener |
| `ARP` | FK mode, remap tweak, layer fix |

Chuyển layout: dropdown trên pie / sub-pie (giữa 8 slot).

---

## 3. Preset operators (cần verify khi cài addon)

> Operator `bl_idname` lấy bằng: thao tác trong UI → Info Editor, hoặc Right-click → Assign Shortcut.

### 3.1 AniMate Core (ước lượng — verify trên máy)

| Nhãn user | Operator (placeholder) | Ghi chú |
|-----------|------------------------|---------|
| AnimOffset | `animatepro.*` | Offset có mask |
| TimeWarper / Retimer | `animatepro.*` | Retime segment |
| Motion path | `animatepro.*` | Viewport |
| Graph: lock axis drag | `animatepro.*` | Graph editor context |
| Nudge / Looper | `animatepro.*` | |

### 3.2 Animation Layers

| Nhãn user | Operator (placeholder) | Ghi chú |
|-----------|------------------------|---------|
| Add layer | `anim_layers.*` | |
| Mute / Solo | thường là props, không phải op | Hub có thể embed **mini UI** gọi panel draw |
| Smart bake | `anim_layers.*` | |
| Inbetweener | `anim_layers.*` | |
| Select bones in layer | `anim_layers.*` | |

**Lưu ý:** Một số control Animation Layers là **properties + redraw**, không phải operator đơn. Hub cần hỗ trợ loại **property shortcut** hoặc **menu call** (`layout.menu("ANIMLAYERS_MT_...")`).

### 3.3 Blender native (luôn có)

| Nhãn | Operator |
|------|----------|
| Insert keyframe | `anim.keyframe_insert_button` |
| Delete keyframe | `anim.keyframe_delete` |
| Euler filter | `graph.euler_filter` |
| Bake action | `nla.bake` |
| Copy pose | `pose.copy` / `pose.paste` |

### 3.4 ARP (sidebar — ít dùng khi đang animate)

Chỉ gợi ý preset nhỏ: FK/IK switch nếu expose operator; phần lớn ARP là properties panel — **không ép vào pie** trừ khi user tự gán.

---

## 4. Kiến trúc kỹ thuật

```
tools/animation/hub/
    __init__.py
    config.py          # default layouts, preset packs
    logic.py           # layout JSON load/save, slot validation (pure)
    controller.py      # register operators, pie menus
    ui.py              # preferences, layout editor

apps/blender/
    adapter.py         # bpy glue, operator dispatch
```

### 4.1 Dispatcher operator

```python
# Pseudo — logic thuần ở logic.py, bpy ở adapter
class MONOFX_OT_hub_run(Operator):
    bl_idname = "monofx.hub_run"

    slot_id: StringProperty()

    def execute(self, context):
        slot = get_slot(slot_id)
        op = getattr(bpy.ops, split_op(slot.operator))
        if not op.poll():
            self.report({'WARNING'}, "Operator not available in this context")
            return {'CANCELLED'}
        # context_override nếu cần (graph vs viewport)
        return op('INVOKE_DEFAULT' if slot.invoke else 'EXEC_DEFAULT', **slot.operator_props)
```

### 4.2 Operator discovery

| Cách | Mô tả |
|------|--------|
| **Pick from UI** | User chọn từ F3 search → lưu idname |
| **Scan addon modules** | `dir(bpy.ops.animatepro)` nếu module tồn tại |
| **Preset JSON** | Ship preset packs; user cập nhật khi addon đổi version |

### 4.3 Context override

Một số tool AniMate chỉ `poll()` pass trong Graph Editor. Hub cần:

- Tag slot: `required_area = 'GRAPH' | 'VIEW_3D' | 'DOPESHEET' | 'ANY'`
- Khi gọi từ viewport: `context.temp_override(area=...)` tìm area phù hợp trong screen hiện tại

### 4.4 Lưu layout

- Per-user: `{config}/monofx/animation_hub_layouts.json`
- Export/import JSON để share trong studio

---

## 5. Rủi ro & mitigation

| Rủi ro | Mitigation |
|--------|------------|
| Addon đổi `bl_idname` sau update | Slot hiện “missing”; UI gợi ý re-pick; version tag trên preset pack |
| `poll()` fail (sai editor/mode) | Báo rõ; grey out slot khi poll fail |
| Property UI không gọi bằng operator | Hỗ trợ type `menu` / `panel_popover` ngoài `operator` |
| GPL AniMate / Anim Layers | Hub **không import** code addon — chỉ gọi `bpy.ops` → tương thích license |

---

## 6. MVP scope

### Phase 1 — Ship nhanh

| # | Tính năng |
|---|-----------|
| 1 | Pie menu 8 slot, hotkey mặc định (user đổi được) |
| 2 | Layout JSON: 1 layout user-defined |
| 3 | **Pick operator** (search) gán vào slot |
| 4 | Preset pack mẫu: Native + placeholder AniMate/AnimLayers (user verify idname) |
| 5 | `poll()` check + warning message |

### Phase 2 — Production

| # | Tính năng |
|---|-----------|
| 6 | Nhiều layout (Blocking / Polish / Layers) + chuyển nhanh |
| 7 | Popup hub (grid lớn hơn 8 nút) |
| 8 | Context override (graph tool từ viewport) |
| 9 | Export/import layout |
| 10 | Slot type: operator / menu / custom property toggle |

### Phase 3 — Polish

| # | Tính năng |
|---|-----------|
| 11 | Header button toggle hub |
| 12 | Studio preset repo |
| 13 | Icon picker per slot |

---

## 7. Không làm trong Hub

- Reimplement AnimOffset, layers, graph tools
- Thay AniMate / Animation Layers UI gốc
- ARP rig/retarget panel (quá nặng, ít dùng mid-animate)

---

## 8. Bước tiếp theo

1. Trên máy có AniMate + Anim Layers: dump danh sách `bl_idname` → `docs/setup/blender_hub_operator_presets.json`
2. Spike pie menu 8 slot gọi `anim.keyframe_insert_button`
3. Implement pick-operator UI
4. Test context override Graph ↔ View3D

---

## 9. Liên quan

- [blender_animation_addon_survey.md](./blender_animation_addon_survey.md) — khảo sát tính năng animate (tham chiếu preset gợi ý)
- Workflow user: **ARP + AniMate Core + Animation Layers** → Hub là lớp UX, không thay addon đã mua
