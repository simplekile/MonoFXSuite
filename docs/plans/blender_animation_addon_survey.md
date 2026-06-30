# Plan: Blender Animation Add-on — Khảo sát & Roadmap

Kế hoạch add-on animation riêng cho Blender trong hệ MonoFX: khảo sát plugin top-tier, đánh giá mức hữu dụng, và ước lượng độ khó khi làm tính năng tương tự.

---

## 1. Bối cảnh & định vị

### 1.1 Vấn đề

Blender có stack animation mạnh (Action, NLA, Graph Editor, Pose Library) nhưng workflow animator chuyên nghiệp vẫn thiếu nhiều tiện ích quen thuộc từ Maya / MotionBuilder / AnimBot. Thị trường add-on animation đã có nhiều sản phẩm trả phí chất lượng cao; clone toàn bộ không khả thi cho một team nhỏ.

### 1.2 Định vị add-on MonoFX Animation

| Trục | Quyết định |
|------|------------|
| **Không làm** | Auto-rig full body, facial rig ARKit, muscle simulation, AI text-to-motion |
| **Ưu tiên** | Hỗ trợ quá trình animate: key/pose, graph polish, overlap, layers, rig navigation |
| **Tích hợp** | Cùng kiến trúc MonoFX: `tools/animation/` (logic thuần) + `apps/blender/` (adapter `bpy`) |
| **Đối tượng** | Animator indie / studio nhỏ dùng Blender 4.2+ (LTS), mở rộng Blender 5.x sau |

### 1.3 Thang đánh giá

**Mức hữu dụng (1–5)**

| Điểm | Ý nghĩa |
|------|---------|
| 5 | Gần như bắt buộc trong pipeline animation chuyên nghiệp |
| 4 | Tiết kiệm đáng kể thời gian, dùng hàng ngày |
| 3 | Hữu ích cho một số workflow cụ thể |
| 2 | Nice-to-have, thay thế được bằng native hoặc add-on free |
| 1 | Niche / hiệu ứng đặc thù, ít dùng |

**Độ khó clone tương tự (1–5)**

| Điểm | Ý nghĩa | Ví dụ kỹ thuật |
|------|---------|----------------|
| 1 | UI wrapper quanh API có sẵn | Bake NLA, filter F-curve |
| 2 | Logic Python + RNA, không cần C/C++ | Key type batch, offset key theo frame |
| 3 | Thuật toán animation + UI phức tạp | AnimOffset có mask, layer influence |
| 4 | Hệ thống lớn, nhiều edge case rig | Retarget bone map, smart bake giữ key distribution |
| 5 | R&D sâu / physics / ML / desktop app riêng | X-Muscle, FaceIt ARKit, Action Library socket bridge |

---

## 2. Tính năng hỗ trợ quá trình animate — Dùng nhiều nhất

Phạm vi: **chỉ tính năng dùng trong lúc đang animate** (blocking → splining → polish → layering). Loại trừ rigging, retarget, export, facial, physics.

Xếp hạng theo **tần suất sử dụng thực tế** (dựa trên workflow animator chuyên nghiệp + add-on bán chạy nhất: AniMate, Animation Layers, Animaide, GraphKit).

### 2.1 Theo giai đoạn pipeline animate

| Giai đoạn | Animator đang làm gì | Tính năng dùng nhiều nhất |
|-----------|----------------------|---------------------------|
| **Setup shot** | Chọn rig, frame range, auto-key | Keying set (Loc/Rot/Scale + custom props), auto-key visual cue, frame scene to action |
| **Blocking** | Đặt pose chính, timing | Pose library apply/blend, key all controls, constant interpolation, mirror pose L/R |
| **Splining** | Chuyển blocking → motion mượt | Đổi interpolation batch (Constant → Bezier), breakdown/inbetween %, tween selected keys |
| **Graph polish** | Sửa arc, ease, overlap | Select keys in range, toggle channel, Euler filter, handle type batch, curve modifiers (noise) |
| **Overlap & secondary** | Tay/chân/đuôi chậm hơn body | **AnimOffset** (offset có mask), shift keyframes theo bone group, nudge/looper |
| **Layering** | Thêm motion trên base (walk + head turn) | Add/mute/solo layer, influence slider, additive/override blend, speed/offset layer |
| **Iteration** | Sửa một phần không phá cả shot | Animation layers non-destructive, copy/paste animation giữa bones, retime segment |
| **Cleanup** | Dọn file trước handoff | Xóa static channels, delete flat keys, bake layer khi xong |

### 2.2 Top 15 tính năng — Xếp theo tần suất dùng

| # | Tính năng | Tần suất | Có trong Blender native? | Add-on tham chiếu | MonoFX ưu tiên |
|---|-----------|----------|---------------------------|-------------------|----------------|
| 1 | **Keying set / key all controls** | Hàng ngày, mỗi pose | Có (Available, Whole Character) — UX kém | AniMate auto-key cues | P1 — preset keying set per rig |
| 2 | **Pose library apply & blend** | Hàng ngày khi blocking | Có (Asset Browser) — thiếu quick panel | GAOLIB, Action Library | P1 — quick pose panel + mirror |
| 3 | **Graph: chọn & sửa key hàng loạt** | Hàng ngày khi polish | Có một phần — chậm | GraphKit, AniMate | P1 — select keys in range, toggle channels |
| 4 | **Đổi interpolation / handle type batch** | Hàng ngày | Có (T, V) — từng lần một | Animaide KeyManager | P1 |
| 5 | **AnimOffset / proportional edit trên timeline** | Rất thường xuyên | Không | Animaide, AniMate | P2 — core differentiator |
| 6 | **Animation layers (mute/solo/influence)** | Rất thường xuyên | NLA có — UX khó | Animation Layers | P2 |
| 7 | **Copy/paste animation giữa bones/objects** | Thường xuyên | Có — awkward | AnimCopy, Transformator | P1 |
| 8 | **Mirror pose / mirror animation** | Thường xuyên khi blocking | Có (chậm, nhiều bước) | Nhiều add-on | P1 |
| 9 | **Rig visibility / bone collection bookmark** | Thường xuyên mỗi shot | Bone collections có — không bookmark | Rig UI Pro, AniMate | P1 |
| 10 | **Motion path / onion skin** | Thường khi polish arc | Motion path có; onion hạn chế | AniMate motion paths | P2 |
| 11 | **Breakdown / inbetweener (% giữa 2 key)** | Thường khi splining | Không trực tiếp | Animation Layers, GraphKit tween | P2 |
| 12 | **Retime / scale keys theo segment** | Thường khi director note | Có (S trong dopesheet) — thiếu UI | AniMate TimeWarper | P2 |
| 13 | **Xóa static / flat channels** | Mỗi shot trước bàn giao | Không | Delete Static Channels | P1 — quick win |
| 14 | **Euler filter / fix rotation flip** | Khi gặp gimbal | Có (Channel → Euler Filter) — ẩn | — | P1 — one-click operator |
| 15 | **Noise / secondary trên layer riêng** | Shot có acting | Curve modifier có — setup lâu | Animation Layers + noise | P3 |

**Chú thích ưu tiên:** P1 = MVP, P2 = ngay sau MVP, P3 = polish.

### 2.3 Nhóm tính năng theo “pain point” animator

#### A. Key & Pose (blocking) — Dùng nhiều nhất

| Tính năng | Mô tả ngắn | Tần suất |
|-----------|------------|----------|
| Key all selected / whole character | Một click key toàn bộ control đang chọn | ⭐⭐⭐⭐⭐ |
| Pose snap từ library | Apply pose đã lưu, blend % bằng drag | ⭐⭐⭐⭐⭐ |
| Mirror pose L/R | Flip pose theo trục nhân vật | ⭐⭐⭐⭐ |
| Jump to prev/next keyframe | Nhảy key trên timeline (J/K style) | ⭐⭐⭐⭐⭐ |
| Auto-key indicator rõ ràng | Biết ngay auto-key đang bật/tắt | ⭐⭐⭐⭐ |

#### B. Graph & Dopesheet (polish) — Thời gian chiếm nhiều nhất

| Tính năng | Mô tả ngắn | Tần suất |
|-----------|------------|----------|
| Select all keys after/before playhead | Chọn key để retime/xóa nửa shot | ⭐⭐⭐⭐⭐ |
| Batch interpolation & handle type | Bezier / linear / stepped hàng loạt | ⭐⭐⭐⭐⭐ |
| Toggle F-curve channel visibility | Ẩn/hiện loc/rot/scale nhanh | ⭐⭐⭐⭐ |
| Tween / push/pull keys | Đẩy key về pose trước/sau | ⭐⭐⭐⭐ |
| Euler filter one-click | Sửa rotation jump | ⭐⭐⭐ |
| Curve noise modifier preset | Secondary motion (breath, sway) | ⭐⭐⭐ |

#### C. Timing & Overlap — Phân biệt amateur vs pro

| Tính năng | Mô tả ngắn | Tần suất |
|-----------|------------|----------|
| **AnimOffset** với mask | Sửa pose tay/đầu, propagate có fade | ⭐⭐⭐⭐⭐ |
| Shift keys theo bone set | Offset overlap thủ công nhanh | ⭐⭐⭐⭐ |
| Retime segment (scale time) | Director bảo "chậm lại 20 frame" | ⭐⭐⭐⭐ |
| Looper / cycle offset | Walk cycle, loopable motion | ⭐⭐⭐ |

#### D. Layers — Dùng nhiều khi có base animation

| Tính năng | Mô tả ngắn | Tần suất |
|-----------|------------|----------|
| Thêm layer additive trên walk/run | Head turn, gesture, noise | ⭐⭐⭐⭐⭐ |
| Mute / solo / influence per layer | Mix layer trực quan | ⭐⭐⭐⭐⭐ |
| Bake layer khi approve | Đóng layer thành action cuối | ⭐⭐⭐⭐ |
| Speed & frame offset per layer | Walk nhanh + upper body chậm | ⭐⭐⭐ |

#### E. Rig navigation — Không phải animate nhưng dùng liên tục

| Tính năng | Mô tả ngắn | Tần suất |
|-----------|------------|----------|
| Bone collection show/hide bookmark | "Chỉ tay", "chỉ face controls" | ⭐⭐⭐⭐⭐ |
| Select all FK / all IK | Chọn nhanh nhóm control | ⭐⭐⭐⭐ |
| Reset control về default | Về bind pose / rest | ⭐⭐⭐⭐ |

### 2.4 Tính năng KHÔNG thuộc quá trình animate (loại khỏi scope)

| Loại | Ví dụ | Lý do loại |
|------|-------|------------|
| Rigging | Auto-Rig Pro, Rigify generate | Làm trước khi animate |
| Retarget / mocap import | ARP Remap, Rokoko | Pre-animate hoặc cleanup ban đầu |
| Export game engine | FBX batch, UE send | Post-animate |
| Facial ARKit | FaceIt | Pipeline riêng |
| Physics / muscle | X-Muscle | Sim, không keyframe |
| Stylization | SMEAR | Post-process render |

### 2.5 MVP MonoFX — Chỉ tính năng animate dùng nhiều nhất

Rút gọn từ Top 15 → **8 tính năng ship đầu tiên**:

| Ưu tiên | Tính năng | Lý do |
|---------|-----------|-------|
| 1 | Keying set preset + key all | Mỗi pose đều cần |
| 2 | Pose quick panel (apply/blend/mirror) | Blocking nhanh gấp 2–3 lần |
| 3 | Graph batch (select range, interpolation, toggle channel) | 60% thời gian polish |
| 4 | Delete static channels + Euler filter | Cleanup mỗi shot |
| 5 | Copy/paste anim giữa bones | Iteration hàng ngày |
| 6 | Rig visibility bookmarks | Navigation liên tục |
| 7 | AnimOffset + mask | Differentiator lớn nhất |
| 8 | Layer helper (add/mute/influence) | Walk + additive motion |

---

## 3. Khảo sát plugin top-tier

Phân loại theo **vai trò pipeline**, không chỉ theo tên sản phẩm.

### 3.1 Animator QoL & Graph / Dopesheet

Các add-on phổ biến nhất trong nhóm này mang workflow Maya/AnimBot vào Blender.

| Plugin | Giá | Tính năng chính | Hữu dụng | Độ khó clone | Ghi chú |
|--------|-----|-----------------|----------|--------------|---------|
| **[AniMate Pro](https://www.animate-pro.org/)** (suite: Pro, Rig UI, Transformator, Outliner Bookmarks) | ~€89/năm (Forge) | Timeline scrub/retimer, Anim Lattice, motion paths, AnimOffset, graph enhancements, transform copy cross-rig | 5 | 3–4 | Phát triển cùng animator studio lớn; benchmark trực tiếp cho QoL pack |
| **[Animaide](https://github.com/aresdevo/animaide)** | Free (GPL) | CurveTools (18+ tools), AnimOffset + mask, KeyManager (type/interpolation batch) | 4 | 3 | Fork **[Retarget](https://extensions.blender.org/add-ons/retarget/)** gộp Animaide cho Blender 5+ |
| **Ultimate Animators Bundle** (GraphKit, Delete Static Channels, Key Selected Objects, AnimCopy, Keys) | Trả phí (bundle) | 14 graph tools, dọn channel tĩnh, key multi-object, copy animation | 4 | 2–3 | Mỗi panel độc lập; dễ làm từng mảnh |
| **GraphKit** (trong bundle) | Riêng lẻ | Select/toggle F-curve, tween, overlap, align keys | 4 | 2 | Nhiều thao tác là batch operator trên `fcurve` |
| **Delete Static Channels** | Riêng lẻ | Xóa channel không đổi giá trị | 3 | 1 | So sánh min/max keyframes per channel |
| **AnimCopy / Keys** | Riêng lẻ | Copy/paste animation giữa object/bone | 3 | 2 | Blender có sẵn một phần; cần UX tốt hơn |

**Tổng hợp nhóm:** Đây là **sweet spot** cho MonoFX — giá trị cao, độ khó vừa phải, không đụng rigging nặng.

---

### 3.2 Animation Layers & Non-destructive Editing

| Plugin | Giá | Tính năng chính | Hữu dụng | Độ khó clone | Ghi chú |
|--------|-----|-----------------|----------|--------------|---------|
| **[Animation Layers](https://superhivemarket.com/products/animation-layers)** | ~$20 | UI layer trên NLA: add/mute/solo/influence, blend modes, speed/offset, smart bake, inbetweener, multikey | 5 | 4 | Chuẩn industry cho mocap + cycle layering; phụ thuộc NLA/action slots Blender 4.x+ |
| **NLA Editor (native)** | Free | Tracks, strips, blend | 3 | — | Đủ mạnh nhưng UX kém; add-on chủ yếu là lớp UI + operators |
| **AniMate Anim Keyposer** (experimental) | Trong AniMate Pro | Key pose + retime trên layer | 3 | 3 | Overlap một phần với Animation Layers |

**Tổng hợp nhóm:** Rất hữu dụng nhưng **smart bake** (giữ phân bố keyframe) và sync custom frame range là phần khó nhất.

---

### 3.3 Rigging & Character Setup

| Plugin | Giá | Tính năng chính | Hữu dụng | Độ khó clone | Ghi chú |
|--------|-----|-----------------|----------|--------------|---------|
| **[Auto-Rig Pro](https://lucky3d.fr/auto-rig-pro/)** | ~$40 | Rig humanoid/creature, remap/retarget, game engine FBX export | 5 | 5 | Standard de-facto cho indie/game; năm phát triển + support |
| **[Rigify](https://docs.blender.org/manual/en/latest/addons/rigging/rigify/index.html)** | Free (built-in) | Metarig → rig, modular | 4 | 4 | Official; nên **tích hợp** thay vì clone |
| **[CloudRig](https://extensions.blender.org/add-ons/cloudrig/)** | Free (Blender Studio) | Metarig components, regenerate rig, animator UI | 4 | 5 | Production-grade; gắn Blender Studio pipeline |
| **[FaceIt](https://superhivemarket.com/products/faceit)** | Trả phí | Facial shape keys ARKit, mocap face, control rig, retarget shape keys | 5 (facial) | 5 | Domain riêng; không nên đụng trong v1 |
| **Rig UI Pro** (AniMate) | Trong suite | Bone collection UI, visibility bookmarks, custom props | 4 | 2–3 | Chủ yếu RNA + UI panel; phù hợp MonoFX |

**Tổng hợp nhóm:** **Không clone ARP/Rigify/FaceIt.** MonoFX nên làm **Rig UI helper** và **export/retarget glue** nếu cần.

---

### 3.4 Retargeting & Motion Capture

| Plugin | Giá | Tính năng chính | Hữu dụng | Độ khó clone | Ghi chú |
|--------|-----|-----------------|----------|--------------|---------|
| **ARP Remap** | Trong ARP | Visual bone map, BVH/FBX retarget | 5 | 5 | |
| **[Rokoko Plugin](https://www.rokoko.com/integrations/blender)** | Free | Live mocap, retarget bridge | 4 | 3–4 | Phụ thuộc hardware/SDK |
| **[Retarget](https://extensions.blender.org/add-ons/retarget/)** (Expy-Kit fork) | Free | Preset Mixamo/UE/VRM/ARP, bake constrained actions, Rigify convert | 4 | 4 | Đã có preset ecosystem |
| **[RealMotion Pro](https://superhivemarket.com/)** | Trả phí | 450+ anim built-in, 1700+ mocap lib, viewport blend/timing | 4 | 4–5 | Asset library + retarget + UX |
| **Mixamo Control Rig add-on** | Free | IK control rig cho chỉnh mocap | 3 | 3 | Bổ trợ chỉnh pose sau retarget |

**Tổng hợp nhóm:** Retarget **preset + bake** có thể làm mức 3 (helper), nhưng chất lượng ARP-level cần effort lớn.

---

### 3.5 Pose / Action Library & Pipeline

| Plugin | Giá | Tính năng chính | Hữu dụng | Độ khó clone | Ghi chú |
|--------|-----|-----------------|----------|--------------|---------|
| **Pose Library (native)** | Free | Pose assets, blend trong viewport, Asset Browser | 4 | — | Blender 3.0+; extend thay vì thay thế |
| **[Action Library](https://github.com/CGstuff/Action-Library)** | Trả phí + desktop app | Socket bridge, versioning, review, 1000+ clips, studio lifecycle | 5 (studio) | 5 | App riêng + SQLite + socket protocol |
| **GAOLIB** (studio) | Varies | Pose/constraint management quy mô studio | 3 | 4 | Ít phổ biến hơn Action Library |

**Tổng hợp nhóm:** MonoFX đã có pattern **Node Preset Library** — có thể áp dụng tương tự cho pose/action với scope nhỏ hơn Action Library (không cần desktop app v1).

---

### 3.6 Shape Keys & Facial-adjacent

| Plugin | Giá | Tính năng chính | Hữu dụng | Độ khó clone | Ghi chú |
|--------|-----|-----------------|----------|--------------|---------|
| **Shape Key Pro** | Trả phí | Reorder, mirror, invert, blend theo vertex group, apply to base | 3 | 2–3 | QoL cho corrective shapes |
| **FaceIt** | Trả phí | (xem 2.3) | 5 (face) | 5 | |

---

### 3.7 Physics, Stylization & AI

| Plugin | Giá | Tính năng chính | Hữu dụng | Độ khó clone | Ghi chú |
|--------|-----|-----------------|----------|--------------|---------|
| **[SMEAR](https://extensions.blender.org/add-ons/smear/)** | Free | Smear frames, motion lines, multiple in-betweens (GeoNodes) | 2 (stylized) | 4 | Siggraph 2024; domain stylized animation |
| **[X-Muscle System](https://k44dev.com/xmuscle-system/)** | Trả phí | Tissue/muscle sim, volume preservation | 3 (realistic) | 5 | Physics + rig integration |
| **Proscenium / Uthana** (AI motion) | Subscription | Text-to-motion, AI assist | 2–3 | 5 | Phụ thuộc model/API bên thứ ba |

**Tổng hợp nhóm:** Ngoài scope MonoFX animation v1 trừ khi có yêu cầu stylized riêng.

---

## 4. Ma trận ưu tiên (Hữu dụng × Khả thi)

```
                    Độ khó clone thấp (1-2)    Độ khó vừa (3)           Độ khó cao (4-5)
Hữu dụng cao (4-5)  GraphKit-like, static      AnimOffset, layers UI,   ARP, FaceIt, Action
                    channel cleanup, key batch   Rig UI, pose library ext Library full
Hữu dụng TB (3)     AnimCopy UX                  Retarget presets         RealMotion lib
Hữu dụng thấp (1-2) —                            SMEAR (nếu stylized)     X-Muscle, AI motion
```

**Kết luận khảo sát:** 80% giá trị animator đến từ **QoL graph/dopesheet**, **layers UI**, **pose/action library mở rộng**, **rig visibility UI** — tất cả nằm trong vùng độ khó 2–4.

---

## 5. Đề xuất phạm vi MonoFX Blender Animation

### 5.1 Tên & module đề xuất

```
tools/animation/
├── graph_tools/          # Curve batch, static channel cleanup
├── anim_offset/          # Offset có mask (tham chiếu Animaide)
├── layer_helper/         # UI + operators trên NLA (không full Animation Layers)
├── pose_preset_library/  # Pattern giống node_preset_library
└── rig_panel/            # Bone collection bookmarks, visibility

apps/blender/
├── adapter.py            # bpy entry, register operators
└── bootstrap.py
```

### 5.2 Roadmap theo phase

#### Phase 0 — Foundation

| Hạng mục | Mô tả | Độ khó |
|----------|--------|--------|
| Blender adapter | `apps/blender/`, register add-on, preferences, MonoFX version | 1 |
| Tool scaffold | `controller/logic/ui/config` per tool | 1 |
| Target Blender | 4.2 LTS trước; test 5.x compatibility | 2 |

#### Phase 1 — MVP Animator QoL (khuyến nghị ship đầu tiên)

| Tính năng | Tham chiếu thị trường | Hữu dụng | Độ khó | Ghi chú |
|-----------|----------------------|----------|--------|---------|
| **KeyManager lite** | Animaide KeyManager | 4 | 2 | Batch key type, interpolation, select handles |
| **Delete static channels** | Ultimate Bundle | 3 | 1 | Quick win |
| **Graph selection tools** | GraphKit subset | 4 | 2 | Toggle channel visibility, select keys in range |
| **AnimCopy improved** | AnimCopy, Transformator lite | 3 | 2 | Copy keys/transform giữa bones/objects cùng action |
| **Rig visibility bookmarks** | Rig UI Pro, Outliner Bookmarks | 4 | 2 | Lưu/khôi phục bone collection visibility |

**Effort ước lượng:** Core team 1 dev — module hóa từng tool, ship incremental.

#### Phase 2 — Layers & Offset

| Tính năng | Tham chiếu | Hữu dụng | Độ khó | Ghi chú |
|-----------|-----------|----------|--------|---------|
| **AnimOffset + mask** | Animaide, AniMate | 5 | 3 | Propagate transform delta qua frame range; mask trong Graph Editor |
| **Layer helper UI** | Animation Layers (subset) | 5 | 4 | Add/mute/solo/influence; chưa cần full inbetweener |
| **Smart bake (basic)** | Animation Layers | 4 | 4 | Bake layer → action, giữ key count gần đúng |

#### Phase 3 — Library & Pipeline glue

| Tính năng | Tham chiếu | Hữu dụng | Độ khó | Ghi chú |
|-----------|-----------|----------|--------|---------|
| **Pose/Action preset library** | Node Preset Library (MonoFX), Pose Library native | 4 | 3 | index.json + thumbnail + import/export folder |
| **Capture action range** | Action Library (subset) | 3 | 2 | Selected bones, frame range → asset |
| **Retarget preset helper** | Retarget add-on | 3 | 4 | Chỉ preset JSON + UI map; không rebuild Expy-Kit |

#### Phase 4 — Không khuyến nghị (trừ budget lớn)

| Tính năng | Lý do trì hoãn |
|-----------|----------------|
| Full auto-rig | ARP/Rigify/CloudRig đã đủ tốt |
| Facial / ARKit | FaceIt domain riêng |
| Desktop library app + socket | Action Library đã làm tốt |
| Muscle sim / AI motion | R&D và maintenance cao |

---

## 6. Kiến trúc kỹ thuật (align MonoFX rules)

### 6.1 Dependency

```
tools/animation/*/logic.py   → pure Python (keyframes math, index JSON)
tools/animation/*/ui.py      → Blender UI descriptors (hoặc shared PySide nếu panel tách app)
apps/blender/adapter.py      → bpy, bmesh, fcurve RNA only
```

- `core` **không** import `bpy`.
- Logic tính offset/mask/bake viết testable không cần Blender headless nếu có thể (mock key data).

### 6.2 Blender API anchors

| Tính năng | API chính |
|-----------|-----------|
| F-curve batch | `action.fcurves`, `keyframe_points`, `graph_editor` context |
| AnimOffset | Pose bone matrices per frame + delta apply |
| Layers | `obj.animation_data.nla_tracks`, strips, `blend_type`, `influence` |
| Pose library | `bpy.ops.pose`, asset marks, `AssetBrowser` |
| Rig UI | `armature.collections`, bone visibility |

### 6.3 Rủi ro kỹ thuật

| Rủi ro | Mức | Mitigation |
|--------|-----|------------|
| Blender 5 RNA/action slots thay đổi | Cao | Pin LTS 4.2; CI smoke test 5.x |
| GPL add-on (Animaide) | Trung bình | Không copy code; chỉ học UX/feature spec |
| NLA edge cases (multiple actions, slots) | Cao | Test matrix: single/multi armature, linked rigs |
| Performance bake lớn | Trung bình | Background operator + progress bar |

---

## 7. Bảng tổng hợp nhanh — Top plugin animation Blender

| # | Plugin | Nhóm | Hữu dụng | Độ khó clone | MonoFX nên |
|---|--------|------|----------|--------------|------------|
| 1 | AniMate Pro | QoL | 5 | 3–4 | Tham chiếu UX; làm subset Phase 1–2 |
| 2 | Animation Layers | Layers | 5 | 4 | Layer helper Phase 2 |
| 3 | Animaide / Retarget | QoL + Retarget | 4 | 3 | KeyManager + AnimOffset Phase 1–2 |
| 4 | Auto-Rig Pro | Rigging | 5 | 5 | Tích hợp export preset, không clone |
| 5 | GraphKit / Animator Bundle | Graph | 4 | 2 | Phase 1 trực tiếp |
| 6 | FaceIt | Facial | 5* | 5 | Bỏ qua |
| 7 | RealMotion Pro | Mocap lib | 4 | 4–5 | Bỏ qua v1 |
| 8 | Action Library | Pipeline | 5** | 5 | Pose preset nhẹ Phase 3 |
| 9 | Rigify / CloudRig | Rigging | 4 | 4–5 | Document compatibility |
| 10 | Rokoko / Retarget | Mocap | 4 | 3–4 | Optional glue |
| 11 | Shape Key Pro | Correctives | 3 | 2–3 | Backlog |
| 12 | SMEAR | Stylized | 2 | 4 | Backlog niche |
| 13 | X-Muscle | Sim | 3 | 5 | Bỏ qua |

\* Hữu dụng cao cho facial workflow, thấp cho body animation general.  
\** Hữu dụng cao cho studio có library lớn.

---

## 8. Tiêu chí Go / No-Go cho từng tính năng

Trước khi implement, mỗi feature cần pass:

1. **Không trùng free tốt sẵn có** — ví dụ Rigify, Pose Library native, Retarget free.
2. **Có user story MonoFX rõ** — ví dụ "offset tay trên walk cycle không phá key gốc".
3. **Logic tách được khỏi `bpy`** — ít nhất 60% code trong `logic.py`.
4. **Độ khó ≤ 3** cho MVP, hoặc có sponsor studio cho Phase 2+.

---

## 9. Bước tiếp theo

1. Chốt **MVP 8 tính năng** (mục 2.5).
2. Tạo `apps/blender/` scaffold + add-on `bl_info` và registration.
3. Spike **AnimOffset** trên armature đơn giản (10 bones) — validate độ khó thực tế.
4. Viết `docs/architecture/blender_animation.md` và `docs/usage/` per tool khi bắt đầu code.
5. So sánh license: add-on MonoFX có thể proprietary; không derive từ GPL Animaide.

---

## 10. Nguồn tham khảo

- [AniMate Pro](https://www.animate-pro.org/)
- [Animation Layers — Superhive](https://superhivemarket.com/products/animation-layers)
- [Animaide GitHub](https://github.com/aresdevo/animaide)
- [Retarget — Blender Extensions](https://extensions.blender.org/add-ons/retarget/)
- [Auto-Rig Pro](https://lucky3d.fr/auto-rig-pro/)
- [FaceIt Documentation](https://faceit-doc.readthedocs.io/en/latest/)
- [Action Library](https://github.com/CGstuff/Action-Library)
- [SMEAR — Blender Extensions](https://extensions.blender.org/add-ons/smear/)
- [CloudRig — Blender Studio](https://studio.blender.org/tools/addons/cloudrig/introduction)
- [Blender Pose Library Manual](https://docs.blender.org/manual/en/latest/animation/armatures/posing/editing/pose_library.html)
- [MoCap Online — Blender Animation Addons Guide](https://mocaponline.com/blogs/mocap-news/blender-animation-addons-guide)
