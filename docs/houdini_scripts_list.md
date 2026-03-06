# Danh sách script Houdini cần dùng — MonoFX Suite

Tài liệu liệt kê các script/tool Houdini thực tế cho pipeline, ưu tiên theo phase.

---

## Đã có

| Script / Tool | Mô tả | Vị trí |
|---------------|--------|--------|
| **Scene Info** | Hiển thị đường dẫn .hip và số node đang chọn | `tools/fx/scene_info` |
| **Split Geometry** | Tách geometry theo attribute: path, name, material; báo cáo + tạo Partition SOP | `tools/fx/split_geometry` |
| **Search & Replace** | Tìm/thay thế trong node name và string parms (path, file, …); scope: selected/network; hỗ trợ regex | `tools/fx/search_replace` |
| **Adapter** | Layer duy nhất gọi `hou`; đã mở rộng: geometry, parm, attribute, tạo node | `apps/houdini/adapter.py` |
| **Bootstrap** | Thêm suite vào PYTHONPATH, (sắp tới) shelf/menu | `apps/houdini/bootstrap.py` |
| **123.py** | Mẫu startup script cho Houdini (path suite) | `docs/setup/houdini_123_example.py` |

---

## Work thực tế với file 3D (ưu tiên)

Các script làm việc trực tiếp với dữ liệu 3D / path / name / material:

| Script | Chức năng |
|--------|-----------|
| **Split Geometry** | Tách theo **path** / **name** / **material** (attribute string trên prim/point) → report + nút tạo Partition SOP. |
| **Search & Replace** | Tìm-thay trong **node name**, **string parms** (file path, alembic path, …); scope: selected nodes hoặc cả network; **regex** tùy chọn. |
| (sắp có) **Replace in attributes** | Tìm-thay trong string attribute trên geometry (path, name, material) — dùng Wrangle hoặc node. |

---

## Phase 1 — Cơ bản (làm trước)

| # | Script | Mô tả | Ghi chú |
|---|--------|--------|--------|
| 1 | **Save Version** | Lưu .hip với version (vd. `scene_v002.hip`), không ghi đè bản cũ | Dùng `hou.hipFile.save()`, logic tên file trong core |
| 2 | **Set Project** | Đặt Houdini project (path) từ biến hoặc chọn thư mục | `hou.houdiniPath()`, project path |
| 3 | **Shelf + Menu** | Thêm shelf MonoFX và menu, gọi các tool (Scene Info, Save Version, …) | Gọi từ `bootstrap` hoặc script 456.py |
| 4 | **Scene Validator** | Kiểm tra scene: file chưa save, node lỗi, path export sai | Chỉ đọc qua adapter, báo lỗi trong UI |

---

## Phase 2 — Publish & Export

| # | Script | Mô tả | Ghi chú |
|---|--------|--------|--------|
| 5 | **Publish HIP** | Copy .hip hiện tại sang thư mục publish (có thể đổi tên theo convention) | Đọc path từ core/project config |
| 6 | **Export Geometry (Alembic/FBX)** | Export từ node đang chọn hoặc từ path (vd. SOP) ra file | ROP Alembic / File SOP, path do project quy định |
| 7 | **Export to USD** | Export scene hoặc subnet ra USD | ROP USD, hoặc Solaris |
| 8 | **Flipbook / Preview** | Render viewport hoặc mantra ra image/movie (preview) | `hou.playbar`, ROP, hoặc `hou.node` |

---

## Phase 3 — Import & Reference

| # | Script | Mô tả | Ghi chú |
|---|--------|--------|--------|
| 9 | **Import/Reference Asset** | Đưa asset (Alembic/USD/hip) vào scene theo đường dẫn pipeline | File SOP, LOP, hoặc HDA |
| 10 | **Update References** | Cập nhật path của node reference (File, Alembic, …) theo project mới | Duyệt parm, đổi path |

---

## Phase 4 — Node & Network

| # | Script | Mô tả | Ghi chú |
|---|--------|--------|--------|
| 11 | **Create Node from Template** | Tạo node (vd. ROP, SOP) từ template có sẵn, set parm mặc định | `hou.node.createNode()`, đọc template từ core |
| 12 | **Set ROP Output Path** | Đặt output path của ROP (Mantra, Alembic, …) theo convention project | Parm `sopoutput`, `vm_picture`, … |
| 13 | **Select by Type/Pattern** | Chọn node theo type (vd. all ROP) hoặc theo tên (pattern) | `hou.node.allSubChildren()`, filter |

---

## Phase 5 — Render & Farm (tùy pipeline)

| # | Script | Mô tả | Ghi chú |
|---|--------|--------|--------|
| 14 | **Submit to Farm** | Gửi job render lên farm (Deadline, Tractor, custom) | Gọi API farm từ logic, adapter chỉ lấy ROP/node |
| 15 | **Set FPS / Resolution** | Đặt FPS và resolution từ project/shot | Globals, hoặc driver node |

---

## Cấu trúc mỗi tool (nhắc lại)

- **apps/houdini/adapter.py** — Thêm hàm mới chỉ tại đây (vd. `get_rop_output_parm()`, `save_hip_as()`).
- **tools/fx/\<tool_name\>/** — controller (gọi adapter), logic (không `hou`), ui, config.
- **core/** — Config project, path convention, không import `hou`.

---

## Thứ tự triển khai gợi ý

1. **Adapter**: Bổ sung hàm cần cho Save Version, Set Project, đọc ROP/output path.
2. **Save Version** + **Shelf/Menu**: Dùng ngay được trong production.
3. **Scene Validator**: Hỗ trợ kiểm tra trước khi publish.
4. **Publish HIP** → **Export Geometry/USD** → **Flipbook**.
5. Các script Import/Reference, Node template, Farm khi đã có convention project rõ.

Nếu bạn muốn bắt tay vào script cụ thể trước, nên bắt đầu bằng **Save Version** và **Shelf/Menu** (shelf button gọi `from tools.fx.scene_info import run; run()` và tương tự cho Save Version).
