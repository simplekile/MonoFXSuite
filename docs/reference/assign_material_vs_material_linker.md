# Assign Material LOP vs Material Linker LOP (Houdini Solaris)

So sánh ngắn gọn hai cách gán material trong Solaris/LOPs.

---

## Assign Material LOP (assign thường)

**Cách hoạt động**
- Gán **một hoặc nhiều** material cho prim theo **pattern** (path/collection) bạn nhập tay.
- Mỗi “dòng” = một cặp: **Primitives** (pattern) + **Material Path** (đường dẫn material).
- Có thể dùng **VEXpression** để tính material path hoặc override parameter theo từng prim.

**Ưu điểm**
- Đơn giản, dự đoán được: pattern → material.
- Nhiều assignment trong một node (multiparm).
- Hỗ trợ collection-based binding, geometry subset, override parameter bằng VEX.
- Dễ **script/automate** (set parm `primpattern1`, `matspecpath1`, v.v.).

**Nhược điểm**
- Gán **một material cho nhiều object** phải lặp lại pattern hoặc nhiều dòng; không có UI kéo-thả.
- Không có catalog material, không có UI rule trực quan.

**Khi nào dùng**
- Pipeline đã biết trước: prim nào → material nào (ví dụ `*_grp` ↔ `M_char_*`).
- Cần tạo Assign Material LOP bằng code (như Auto assign trong MonoFXSuite).
- Chỉ cần gán theo path/pattern, không cần chỉnh rule bằng UI.

---

## Material Linker LOP

**Cách hoạt động**
- **Rule-based**, **material-centric**: một material có thể gán cho **nhiều** prim qua các rule (include/exclude).
- Có **UI riêng** (Qt): cây material bên trái, cây model bên phải, giữa là danh sách rule. Kéo material sang prim để tạo rule.
- Mỗi rule có: material (nguồn), **Includes** (prim được gán), **Excludes** (prim loại trừ). Có thể bật/tắt từng rule.
- Hỗ trợ **Material Catalogs** (Houdini catalog, AMD MaterialX Library, USD file…).

**Ưu điểm**
- Gán **một material cho nhiều geometry** rất nhanh qua kéo-thả.
- Quản lý nhiều rule trong một node, bật/tắt từng rule, chỉnh include/exclude trong dialog.
- Phù hợp khi đang “layout” scene, thử material, hoặc làm việc trực tiếp trên stage.

**Nhược điểm**
- UI-driven, ít phù hợp để **tự động hóa bằng script** (số rule, include/exclude phức tạp, không đơn giản như set vài parm).
- Tài liệu Parameters còn “TBD” cho một số mục (References, Type…).

**Khi nào dùng**
- Cần chỉnh nhanh gán material bằng tay (kéo material vào prim).
- Nhiều object dùng chung một material, muốn quản lý theo rule include/exclude.
- Cần dùng Material Catalog hoặc làm việc trực quan trên cây stage.

---

## Bảng so sánh nhanh

| Tiêu chí              | Assign Material (thường)     | Material Linker           |
|-----------------------|------------------------------|----------------------------|
| **Cách chỉ định**     | Pattern (path/collection)   | Rule (include/exclude)     |
| **UI**                | Parameter editor thường     | Custom Qt UI (tree + drag) |
| **Một material → nhiều prim** | Có (nhiều dòng/pattern) | Có, thuận tiện qua rule    |
| **Script / automation** | Rất tốt (parm rõ ràng)    | Khó hơn (rule, list)       |
| **VEX / override**    | Có (VEXpression, CVEX)      | Không nêu trong tài liệu   |
| **Collection-based**  | Có (Method)                 | Có (rule type)             |
| **Material Catalog**  | Không                        | Có                         |
| **Binding trong USD** | Direct hoặc collection-based | Trước đây collection, bản mới dùng direct |

---

## Gợi ý trong pipeline MonoFXSuite

- **Auto assign** (match `*_grp` với `M_char_*`): giữ **Assign Material LOP** là hợp lý vì:
  - Logic cố định: prim pattern + material path.
  - Dễ tạo node và set parm từ code (`create_assign_material` / `create_assign_material_bulk`).
- **Material Linker** nên dùng khi artist muốn chỉnh gán material bằng tay trong Solaris (kéo material, chỉnh include/exclude) hoặc khi cần Material Catalog, không cần automate từ tool.

---

*Tham chiếu: [Assign Material](https://www.sidefx.com/docs/houdini/nodes/lop/assignmaterial.html), [Material Linker](https://www.sidefx.com/docs/houdini/nodes/lop/materiallinker.html).*
