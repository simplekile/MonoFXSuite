# Mono Anim Loader — nguồn Asset (gộp Character Loader) — thiết kế

Ngày: 2026-11-17. Trạng thái: **chờ người dùng duyệt** (mục 8). Nối tiếp `anim_loader_v2_2.md`.

Bản đang dùng song song: `D:\Dropbox\Stock\Plugin\HOU\Mono\hda\lop_mono_character_loader.3.2.hdalc`
(type `mono_character_loader::3.2`, Python trong HDA, không ở repo, không test, không theo installer).

## 1. Mục đích

Một nhân vật được nạp bằng **một node**, dù đang ở shot (anim) hay đứng yên (model của asset). Scene
grooming / lookdev hôm nay phải đặt hai node cạnh nhau, ví dụ `char_Helen_grooming_v008` có
`/obj/Character_Loader` với `mono_character_loader1` → `OUT_CHAR` (model UV v019) và `mono_anim_loader1`
→ `OUT_ANIM` (anim sh025 v005), rồi đổi display qua lại. Sau khi gộp, chỉ cần đổi **Source** trên một
node: đường dẫn prim giữ nguyên, nên groom, material và mọi thứ phía sau không phải nối lại.

Lý do gộp vào Anim Loader 2.2 thay vì sửa 3.2: 2.2 đã có graft dưới `/<asset>`, luật subdivision theo
mesh (chặn lỗi Catmull-Clark mặc định làm viewport vượt 45 GB), version không tự trôi, status, cửa sổ quản
lý và test. Phần lookdev, scale, ẩn `HairDriver_grp` và graft là chung; chỉ có **nơi lấy file** là khác.

## 2. Mục tiêu / không làm / không được xảy ra

**Mục tiêu**
- Parm **Source**: `Shot` (như hiện tại) hoặc `Asset` (model + groom + lookdev đã publish của asset).
- Đổi Source không làm mất gì: setting của bên kia vẫn nằm trên node, đổi lại là về như cũ.
- Cùng đường dẫn prim ở hai Source: `/char_Helen/Geo/...`.
- Node 3.2 trong scene cũ nâng được lên 2.2 Source Asset, giữ lựa chọn (Upgrade trong manager).

**Không làm**
- Không nạp rig, không nạp `06_anim` của asset, không làm clone khi Source là Asset.
- Không dùng MONO Grooming ở đây (groom của asset là `04_grooming/publish` như 3.2 đang đọc).
- Không giữ các phần phụ của 3.2: thumbnail trên network, theo dõi publish theo thời gian thực
  (`watch_publish`), path prefix cho groom (graft đã làm việc đó).

**Không được xảy ra**
- Scene có node 3.2 mở ra bị đổi gì; thư viện 3.2 vẫn cài và chạy như cũ.
- Node 2.2 đã có trong scene thay đổi khi cài bản mới (Source mặc định `Shot`, như hôm nay).
- Source Asset lấy cache của shot, hay Source Shot lấy model của asset, mà không báo.

## 3. Dữ liệu (đã xem trên `260826_grn_vp97`, char_Helen)

```
<project>/01_assets/<_group>/<asset>/
    01_modelling/03_uv/publish/vNNN/<asset>_uv_publish.usd     gốc /Geo (Base_grp, Groom_grp, Outfit_grp, material)
    04_grooming/publish/vNNN/<asset>_groom_publish.usd         gốc /Groom (Hair_Back, Eyelash, ...)
    05_lookdev/publish/VNNN/<asset>_lookdev_publish.usd        sublayer ./stage/..., over trên /Geo
```

- Model UV và anim cùng gốc `/Geo` và cùng các nhóm (`Base_grp`, `Groom_grp`, `Outfit_grp`), nên graft
  dưới `/char_Helen` cho ra cùng đường dẫn ở hai Source. Lookdev là `over` trên `/Geo`, áp được lên cả hai.
- Groom của asset ở gốc `/Groom` → `/char_Helen/Groom/...`. Groom của shot (cache của grooming department)
  nằm trong `/Geo/Groom_grp/...`. **Hai Source khác nhau ở đường dẫn groom**; mục 8, câu 4.
- Version: `vNNN` (UV, groom), lookdev có lúc viết hoa `VNNN` (đã xử lý ở 2.2).

## 4. Các cách đã cân nhắc

1. **Hai node riêng như hiện tại** (đưa 3.2 vào repo). Bỏ: vẫn hai đầu ra, vẫn đổi display, subdivision
   và status phải làm hai lần.
2. **Node mới "Mono Loader" thay cả hai.** Bỏ: phải chuyển mọi scene 2.2 vừa phát hành, không thêm gì so
   với cách 3.
3. **Thêm Source vào 2.2 (chọn).** Node 2.2 cũ không đổi (Source mặc định Shot); thêm parm là tương thích
   với scene đã lưu; dùng lại toàn bộ graft, lookdev, subdivision, status, manager.

## 5. Thiết kế

### 5.1 Parm

- `mx_source` (menu `Shot` / `Asset`) đứng đầu nhóm Source.
- **Shot**: như layout D hiện tại (Shot, Anim Version, Anim File, Asset; Parts: Lookdev, Groom, Cloth).
- **Asset**: Asset (menu các asset của project), **Model** version (UV publish), Parts: Lookdev, Groom
  (của asset). Cloth ẩn. Shot / Anim ẩn nhưng giá trị giữ nguyên trên node.
- Mỗi menu version ghi trạng thái như hiện nay (`v019  latest`, `v018  (v019 available)`); comment của
  node nói cùng điều; Status chỉ hiện khi cần làm gì (`logic.next_step`: chưa có project → chọn asset →
  "char_X chưa có UV publish").
- Apply timeline ẩn khi Source là Asset (model không có time sample).

### 5.2 Khi tạo node

`on_created` nhìn `$HIP`:
- trong `01_assets/<_group>/<asset>/...` → Source **Asset**, asset đó, mỗi phần bản mới nhất (một lần);
- trong `02_shots/<shot>/...` → Source **Shot**, như hiện tại;
- ngoài project → Source Shot, Status chỉ chỗ đặt project (như bản v0.1.31).

### 5.3 Giải đường dẫn và mạng bên trong

- `logic.resolve(state)` thêm nhánh Asset: `anim` được thay bằng model
  (`01_modelling/03_uv/publish/<ver>/<asset>_uv_publish.usd*`), groom từ `04_grooming/publish/<ver>`,
  lookdev như cũ, cloth không có. `LoaderState` thêm `source` và `model_version`; các trường Shot giữ.
- Mạng bên trong không đổi: các layer đi vào cùng sublayer → graft `/<asset>` → render_only (subdivision,
  Show in Viewport) → scale → ẩn → output. Groom asset không có time sample: là một layer thường, không
  value clip.
- **Subdivision**: cùng thứ tự, chữ "anim" thay bằng "model": luật trên node > lookdev > UV publish > none.
  Luật đã đặt trên node áp cho cả hai Source (cùng đường dẫn mesh).
- Instance ở Source Asset luôn là tên asset (`/char_Helen`). Hai node Asset cùng asset trong một stage
  sẽ đè nhau: Status báo.

### 5.4 Đổi Source

Chỉ đổi `mx_source` rồi refresh. Không xoá parm của Source kia, không đổi version nào. Asset, lookdev
version, scale, ẩn, luật subdivision, Show in Viewport dùng chung. Một bước undo.

### 5.5 Cửa sổ quản lý

- Hàng của loader Source Asset ghi "asset" ở chỗ shot, cột Anim thành "Model" (vNNN), Cloth là "–".
  Update, Subdivision, Inspector làm việc như hàng Shot. Load shot và Retarget bỏ qua các node Asset.
- Upgrade nhận thêm node `mono_character_loader::3.2` (mục 5.6).

### 5.6 Node 3.2 → 2.2 Asset

Upgrade đổi type bằng `changeNodeType` không được (khác parm), nên tạo node 2.2 mới cạnh node 3.2, nối
cùng input / output, chép giá trị, rồi xoá node 3.2; một bước undo. Bảng chép:

| 3.2 | 2.2 (Source Asset) |
|---|---|
| `folder_path` + `Model_List` | `mx_project_root` (tìm từ thư mục), `mx_asset` |
| `Version_List` | model version |
| `Enable_Groom`, `Version_Groom_List` | `mx_enable_groom`, groom version |
| `Version_Lookdev_List` | lookdev version (bật) |
| `enableScale`, `scale` | `scale` (tắt → 1) |
| `Enable_Prune`, `primpattern1` | `mx_hide_enable`, `mx_hide_pattern` |
| `EnableModify` (SOP Modify) | không có (mục 8, câu 2) |

Đường dẫn prim đổi từ `/Geo` sang `/<asset>/Geo`: manager báo trước khi Upgrade, như với node 2.1.

## 6. Kiểm tra

- pytest: resolve nhánh Asset, `next_step` cho Asset, chọn Source từ `$HIP`, bảng chép 3.2.
- hython (`accept_hda`): trên `fake_project` thêm `01_assets/_characters/char_Robot/{01_modelling/03_uv,
  04_grooming,05_lookdev}/publish`; đổi Source Shot ↔ Asset giữ đường dẫn mesh và luật subdivision; Upgrade
  một node 3.2 dựng giả; mở lại scene giữ mọi parm.
- Trên scene thật `char_Helen_grooming_v008` (chỉ đọc, không lưu): một node thay được hai node, đường dẫn
  `/char_Helen/Geo/...` giống nhau ở hai Source.

## 7. Thứ tự làm

1. `logic.py` + test (Source, resolve Asset, next_step, chọn từ `$HIP`).
2. `build_hda.py` (parm Source, ẩn/hiện) + adapter + hython.
3. Manager: hàng Asset, Upgrade 3.2.
4. Ghi quyết định vào `CLAUDE.md` (mục Anim Loader) và changelog.

## 8. Còn chờ người dùng

1. **Model lấy từ đâu?** Đề xuất: chỉ UV publish (`01_modelling/03_uv`), như 3.2 đang dùng. Có thể thêm
   menu bước (sculpt / retopo / uv / rig clean_geo) nếu cần.
2. **Enable Modify (SOP Modify) của 3.2** có ai dùng không? Đề xuất: bỏ; ai cần thì đặt SOP Modify sau node.
3. **Tên hiển thị**: giữ type `mono_anim_loader::2.2`, đổi label thành "Mono Loader"? Đề xuất: đổi label,
   giữ type (scene đã lưu không đổi).
4. **Groom khác đường dẫn giữa hai Source** (`/char_Helen/Groom/...` của asset, `/char_Helen/Geo/Groom_grp/...`
   của shot). Chấp nhận, hay cần đặt groom asset vào cùng chỗ với groom shot?
