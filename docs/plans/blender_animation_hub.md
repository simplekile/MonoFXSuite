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

**Hub** = launcher layer — hỗ trợ **3 loại slot**:

```
Pie slot
    ├─ type: operator  → bpy.ops.animatepro.xxx()
    ├─ type: panel     → bpy.ops.wm.call_panel(name="...", keep_open=True)
    └─ type: hub_popup → Hub mở popup chứa layout.popover() / nhiều panel con
```

Không copy logic AniMate / Animation Layers — chỉ **delegate** tới operator hoặc **mở panel gốc** của addon.

### 2.2 UI options — So sánh

| Kiểu UI | Ưu | Nhược | Phù hợp |
|---------|-----|-------|---------|
| **Pie menu** (8 hướng) | Nhanh, một tay, quen với Blender | Giới hạn slot; khó hiện label dài | Hotkey chính khi animate |
| **Popover panel** | Gắn viewport, không chiếm N-tab | Blender popover nhỏ, không “float” tự do | Quick access cạnh 3D view |
| **Popup dialog** | Nhiều nút, scroll, section | Phải mở/đóng mỗi lần | Bộ tool đầy đủ hơn pie |
| **Panel `WINDOW` region** | Gần floating nhất trong Blender | API ít ổn định hơn pie | Tùy chọn nâng cao |

**Khuyến nghị MVP:** Pie menu (hotkey) + Popup hub (phím phụ hoặc nút header) — **không** cố làm true floating window độc lập (Blender hạn chế).

**Khuyến nghị MVP:** Pie menu (hotkey) + Popup hub (phím phụ) + **slot type `panel`** cho Animation Layers / AniMate panels đầy đủ.

### 2.3 Slot types

| Type | Dùng khi | Cơ chế Blender |
|------|----------|----------------|
| **`operator`** | Một thao tác (bake, offset, key…) | `bpy.ops.xxx()` |
| **`panel`** | Cần **cả UI** (slider, list layer, bake options) | `bpy.ops.wm.call_panel(name=bl_idname, keep_open=True)` |
| **`popover`** | Panel nhỏ, mở cạnh nút | `layout.popover(panel=bl_idname)` trong Hub popup |
| **`sub_pie`** | Nhóm nhiều mục (vd. pie “Panels”) | Pie menu con → các slot `panel` |

#### Pie → Animation Layers → hiện panel: **Có, làm được**

Flow user mong muốn:

```
Hotkey → Pie → chọn "Animation Layers"
    → bpy.ops.wm.call_panel(name="ANIMLAYERS_PT_...", keep_open=True)
    → Popup hiện toàn bộ UI Animation Layers (list layer, influence, bake…)
```

Ví dụ code (Hub adapter):

```python
def open_panel_slot(context, panel_idname, keep_open=True):
    panel_cls = getattr(bpy.types, panel_idname, None)
    if panel_cls and hasattr(panel_cls, "poll") and not panel_cls.poll(context):
        return {'CANCELLED'}  # báo: cần armature + pose mode
    return bpy.ops.wm.call_panel(name=panel_idname, keep_open=keep_open)
```

**`keep_open=True`** quan trọng với Animation Layers — user click slider/mute không bị đóng popup ngay.

#### Giới hạn thật (cần set kỳ vọng đúng)

| Mong muốn | Thực tế Blender |
|-----------|-----------------|
| Panel float, **kéo đi đâu cũng được** | ❌ `call_panel` là **popup neo gần vị trí gọi**, không drag tự do |
| Panel **ở lại** khi chỉnh slider | ✅ `keep_open=True` |
| Panel **riêng cửa sổ OS** | ⚠️ `screen.area_dupli` — mở Blender window mới; nặng, ít ai dùng |
| Panel persist như N-tab | ⚠️ Dùng `bl_ui_widgets` + GPU — tự vẽ UI, **không** nhúng panel addon gốc |

**Kết luận UX:** Gọi là **“popup panel”** thay vì “floating draggable” — đủ dùng cho Animation Layers (list + influence + bake).

#### Animation Layers có nhiều sub-panel

Addon thường tách: layer list, layer tools, bake, shapekey layers. Hub có thể:

1. **Một slot = panel chính** (list + influence) — đủ 80%  
2. **Sub-pie “Anim Layers”** → 3 slot: Main / Tools / Bake  
3. **Hub popup** chứa nhiều `layout.popover()` / `layout.panel()` xếp dọc

`bl_idname` từng panel: Right-click header panel Animation Layers → *Edit Source* (addon Edit Operator Source) hoặc search trong addon Python.

### 2.4 User customization

Mỗi **slot** lưu theo `type`:

**Operator slot:**

```json
{
  "id": "slot_01",
  "type": "operator",
  "label": "AnimOffset",
  "operator": "animatepro.anim_offset",
  "operator_props": {},
  "icon": "MOD_OFFSET",
  "invoke": "INVOKE_DEFAULT",
  "source_addon": "AniMate Pro"
}
```

**Panel slot (Animation Layers, AniMate panel, v.v.):**

```json
{
  "id": "slot_02",
  "type": "panel",
  "label": "Animation Layers",
  "panel_idname": "ANIMLAYERS_PT_main",
  "keep_open": true,
  "icon": "ANIM",
  "source_addon": "Animation Layers",
  "poll_hint": "Armature active, Pose Mode"
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

### 3.2 Animation Layers — **ưu tiên slot type `panel`**

| Nhãn user | Slot type | Cơ chế | Ghi chú |
|-----------|-----------|--------|---------|
| **Animation Layers (full UI)** | `panel` | `wm.call_panel` + `keep_open=True` | List layer, influence, mute — **đúng use case user** |
| Layer Tools / Bake | `panel` | panel idname riêng | Sub-pie hoặc popup hub |
| Add layer | `operator` | `anim_layers.*` | Nếu chỉ cần 1 click |
| Mute / Solo / Influence | — | props trên panel | Không tách operator — mở full panel |

Không cố gắng nhét slider influence vào pie wedge — **mở panel** là đúng thiết kế.

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
| 1 | Pie menu 8 slot, hotkey mặc định |
| 2 | Slot types: **`operator`** + **`panel`** (`wm.call_panel`) |
| 3 | Layout JSON + Pick Operator / **Pick Panel** (search `bpy.types` Panel subclasses) |
| 4 | Preset: Animation Layers panel, Native ops |
| 5 | `poll()` check + message (pose mode, armature) |

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
