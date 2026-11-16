# Mono Anim Loader 2.2 — thiết kế

Ngày: 2026-11-17. Bản đang dùng: `D:\Dropbox\Stock\Plugin\HOU\Mono\hda\lop_mono_anim_loader.2.1.hdalc`
(type `mono_anim_loader::2.1`; cùng file còn chứa `::2`). Python của 2.1 trùng từng dòng với
`apps/houdini/hda/anim_loader_simple.py`.

## 1. Mục đích

Lighting / render dựng shot trong Solaris từ những gì các bộ phận đã publish: anim (Blender), lookdev,
groom và cloth (quy trình cũ của grooming department, **không** dùng MONO Grooming). Mỗi thứ trong shot
(một nhân vật, prop, xe hoặc camera, kể cả clone) là một node loader. Một cửa sổ PySide6, mở từ nút trên
node, cho thấy mọi loader trong scene, bản nào cũ, cái gì thiếu, và cập nhật chúng một lần.

Vì sao làm lại thay vì vá 2.1: code nằm trong HDA, không ở repo, không có test; input của HDA bị bỏ; clone
và asset có số trong tên bị nhận nhầm; lookdev tự đổi sang bản mới nhất mà không báo; Batch Loader bấm
hai lần thì ra gấp đôi.

## 2. Mục tiêu / không làm / không được xảy ra

**Mục tiêu**
- HDA lo việc load một thứ trong shot; mọi quyết định đường dẫn nằm trong code của repo, có test.
- Nhiều nhân vật và clone trong một shot, không đè nhau, không lấy nhầm lookdev / groom / cloth.
- Không gì tự đổi: version nằm trên node; bản mới chỉ được báo, Update mới đổi.
- Cửa sổ quản lý: xem, cập nhật, tạo loader còn thiếu cho cả shot, nâng node 2.1 lên 2.2.
- Groom / cloth (mỗi frame một file) load nhanh và có motion blur.

**Không làm (2.2)**
- Không deform tóc trong Houdini, không dùng `houdinihairprocedural` (đã cân nhắc; quy trình hiện tại
  ghi cache theo shot).
- Không publish, không cache, không sửa file trên đĩa.
- Không dùng chung một cache cho các clone chung animation (để sau).

**Không được xảy ra**
- Lấy groom / lookdev của nhân vật khác mà không báo.
- Scene 2.1 đang làm mở ra bị đổi gì, hay node 2.1 hỏng sau khi cài 2.2.
- Hộp thoại modal (chặn Houdini và cầu MCP); dời node người dùng đã đặt.

## 3. Quy ước dữ liệu (đã chốt)

```
<project>/02_shots/<shot>/01_anim/publish/vNNN/
    geo_<asset>.usd            geo_<asset>_instNN.usd (clone)      cam_<shot>.usd
    publish_meta.json          { fps, playback_range, outputs[] }
<project>/02_shots/<shot>/02_fx/groom/publish/vNNN/<thư mục instance>/<shot>_groom.####.usd
<project>/02_shots/<shot>/02_fx/cloth/publish/vNNN/<thư mục instance>/<shot>_cloth.####.usd
<project>/01_assets/<_group>/<asset>/05_lookdev/publish/vNNN/<asset>_lookdev_publish.usd*
```

- **Instance** = một lần xuất hiện của asset trong shot. Lần đầu là `geo_char_Robot`, clone là
  `geo_char_Robot_inst02`, `_inst03`… (người dùng chốt 2026-11-17). `_2` không còn là đuôi clone: asset
  thật có số trong tên (`prop_CoralSet_001`… `_005`, `prop_Cliff01` trong `260826_grn_vp97`).
- **`publish_meta.json` ghi asset và số instance** cho mỗi output geo:
  `{"file": "geo_char_Robot_inst02.usd", "type": "geo", "asset": "char_Robot", "instance": 2}`.
  Loader tin meta trước tên file. (Thay đổi phía add-on Blender, mục 7.)
- **Publish cũ không có `asset`** — đoán theo thứ tự, dừng ở luật đầu tiên khớp:
  1. tên sau `geo_` (bỏ `_instNN`) là thư mục có trong `01_assets/*/` → asset đó;
  2. bỏ đuôi `_<số>`, phần còn lại là asset có thật → asset đó, instance = số;
  3. khớp cả 1 và 2 với hai asset khác nhau, hoặc không khớp gì → **không đoán**: node báo "asset?",
     cửa sổ cho chọn; lựa chọn lưu trên node.
- **Thư mục groom / cloth của instance**: tìm đúng tên, thử lần lượt `char_Robot_inst02` (tên đầy đủ),
  rồi `Robot_inst02` (kiểu cũ không có loại asset). Không thấy → báo "Groom chưa có cho
  char_Robot_inst02", **không** lấy thư mục khác. File ngay dưới `vNNN` (không thư mục con) chỉ được nhận
  khi shot có đúng một instance geo. *(Thứ tự hai tên: quyết định của Claude.)*
- **Lookdev** của mọi instance là lookdev của asset (instance không có lookdev riêng).

## 4. Các cách làm đã cân nhắc

| Cách | Được | Mất |
|---|---|---|
| A. Vá tại chỗ trong Type Properties của 2.1 | nhanh, không đổi type | code vẫn ngoài repo, không test, nợ cũ giữ nguyên |
| **B. HDA mỏng dựng từ repo + logic có test + cửa sổ quản lý (chọn)** | sửa repo là sửa HDA; test được không cần Houdini; giống cách MONO Grooming và Auto Material đang làm | phải viết script build HDA; type mới `::2.2` |
| C. Bỏ HDA, cửa sổ tự dựng mạng LOP thường (như `usd_batch_loader`) | không có HDA để bảo trì | trái yêu cầu "HDA chịu trách nhiệm load"; artist không có node để cầm, khó sửa tay |

Người dùng chọn hướng B (HDA load, nút mở GUI PySide6, đưa HDA vào repo).

## 5. Thiết kế

### 5.1 Code

```
tools/fx/anim_loader/
    config.py        tên parm, mẫu đường dẫn, loại asset, hằng số
    logic.py         không import hou: quét publish, nhận instance, chọn version, ghép groom/cloth/lookdev,
                     ShotPlan / LoaderState (dataclass), so sánh "trên node" với "trên đĩa"
    controller.py    cửa sổ: trạng thái, lệnh (không Qt trong logic)
    ui.py            PySide6
    build_hda.py     dựng `mono_anim_loader::2.2` vào `otls/mono_anim_loader.hdalc`
apps/houdini/anim_loader_adapter.py   hou: đọc / ghi parm, tạo node, undo, đọc stage
tests/test_anim_loader_logic.py       pytest trên cây thư mục giả (tmp_path)
tests/houdini/…                       hython: build HDA, tạo node, refresh, batch, upgrade
```

PythonModule của HDA chỉ là `from apps.houdini.anim_loader_adapter import *`. `anim_loader_simple.py`
(cho node 2.1) giữ nguyên; phần dùng lại được chuyển vào `logic.py`. `anim_publish_loader.py` và
`usd_batch_loader` không đụng tới trong 2.2.

### 5.2 Một node = một instance hoặc camera

**Parm là nguồn sự thật** (ai sửa tay cũng thấy): `project_root` (mặc định tìm từ `$HIP`; bỏ giá trị
viết cứng `D:\Dropbox\Job`), `shot`, `mode` (geo / cam, theo file), `anim_version`, `anim_file`, `asset`,
`instance`, và cho từng phần lookdev / groom / cloth: `enable`, `version`. Version luôn là `vNNN` cụ thể;
không có "latest" tự trôi. Giữ tên parm của 2.1 khi nghĩa không đổi (`mx_shot`, `mx_anim_version`,
`mx_enable_groom`…) để upgrade giữ được giá trị.

**Đường dẫn đã giải** nằm ở parm ẩn, do `adapter.refresh(node)` ghi lại mỗi khi một parm nguồn đổi
(callback) và khi tạo node. Không giải lúc cook. Giải từ cùng parm luôn ra cùng đường dẫn, nên mở scene
không làm đổi gì. Trạng thái (đủ / thiếu / bản mới) ở `mx_status` và trong cửa sổ.

**Mạng bên trong**
- Input 0 đi qua: stage phía trên + các lớp của node này (2.1 bỏ mất input).
- Mỗi instance nằm dưới prim gốc riêng `/<instance>` (`/char_Robot`, `/char_Robot_inst02`): file anim nào
  cũng có gốc `/Geo` (đã xem `sh010/…/geo_char_Ata.usd`; gốc là tên object gốc trong Blender), nên hai
  nhân vật sublayer chung một stage trộn vào một `/Geo`, còn clone thì đè hẳn lên nhau. Cách người dùng
  đang làm và đã chạy được: mỗi nhân vật một nhánh, cuối nhánh một Null mang tên asset, các nhánh ghép
  bằng **Graft Stages**. Loader 2.2 làm đúng việc đó bên trong: anim + lookdev + groom + cloth ghép thành
  stage riêng của instance, rồi Graft Stages đặt cả stage đó dưới `/<instance>` trên input 0. Vì cả stage
  được ghép, material và binding nằm ngoài `/Geo` cũng đi theo. Đường dẫn ghép theo quy ước người dùng
  đang dùng (2026-11-17): Null tên asset `char_Helen` → `/char_Helen/Geo/…`; clone mang tên như file
  publish, bỏ `geo_`: `geo_char_Helen_inst02.usd` → `/char_Helen_inst02`. Publish cũ có clone `_2` giữ
  đúng tên file (`/char_Helen_2`), không đổi tên.
  Camera giữ đường dẫn của file (một camera một shot, không trùng).
- Giữ các chỉnh của 2.1: scale (LOP / SOP), visibility theo pattern, camera (aperture, clipping, aspect,
  guide scale), scale 100 của camera.
- Groom / cloth: value clip trên các file từng frame thay cho Sublayer `$F4`, nếu spike S1 đạt (mục 6).
  Lý do: Sublayer `$F4` dựng lại stage mỗi frame và không cho frame lân cận, nên không có motion blur.

### 5.3 Version và cập nhật

Tạo node: chọn bản mới nhất mỗi phần **một lần** rồi ghi `vNNN` lên node. Sau đó không gì tự đổi. Cửa sổ
và `mx_status` báo "anim v003 → v004 có", Update ghi version mới và refresh. Mỗi lần Update / Load shot /
Upgrade là một bước undo. Lookdev hết tự lên bản mới khi chạy callback (lỗi của 2.1).

### 5.4 Timeline

Nút Apply timeline giữ như 2.1: fps và playback_range từ `publish_meta.json`; không có meta thì lấy fps
và timeCode của stage (add-on Blender giờ ghi fps vào USD).

### 5.5 Cửa sổ quản lý

Mở từ nút "Manager" trên mọi loader và từ shelf. Một cửa sổ, không modal, không trang con.
- Mọi loader trong scene (2.1 và 2.2), nhóm theo shot. Mỗi dòng: instance, asset, anim / lookdev / groom /
  cloth với version và trạng thái (đủ, có bản mới, thiếu, tắt, asset?), dùng chung màu trạng thái với
  Auto Material.
- Lệnh: Update chọn / tất cả; **Load shot** (tạo loader cho mọi output trong một version anim; loader đã
  có, nhận theo shot + `anim_file`, giữ nguyên; bấm lại không ra gấp đôi); Upgrade 2.1 → 2.2; chọn node;
  Apply timeline; chọn asset cho dòng "asset?".
- Node mới đặt bằng `solaris_adapter._place_new` (không dời node khác) và nối vào một Merge LOP của shot
  do cửa sổ tạo (nhận lại bằng user data); không nối lại node có sẵn. *(Quyết định của Claude.)*
- Đọc đĩa trên worker thread, ghi scene trên main thread (như Auto Material); kết quả và lỗi ở dòng dưới
  cửa sổ.
- Bố cục và màu đi qua skill `dcc-panel-design`: 2-3 mockup để người dùng chọn trước khi code.
- **Bố cục đã chọn (người dùng, 2026-11-17, mockup https://claude.ai/artifact/GEiaL6PUnMXhXukHH2isM1):**
  hai chế độ xem, nút chuyển trên thanh trên: **List** (phương án A: mỗi instance một dòng, cột Anim /
  Lookdev / Groom / Cloth, nhóm theo shot) và **Grid** (phương án C: mỗi instance một thẻ). Cả hai có
  **thumbnail của asset như Monos**: `<asset>/thumbnail.user.png` (ảnh Monos đặt), không có thì
  `.meta/thumb_lookdev.user.png`, rồi ảnh bộ phận `.meta/thumb_<dept>.user.png` mới nhất; camera và dòng
  "asset?" có icon thay ảnh. Chế độ xem là của người xem (`%APPDATA%/MonoFXSuite/anim_loader_prefs.json`),
  không lưu vào scene.

### 5.6 Node 2.1

Thư viện 2.1 vẫn cài, scene cũ mở như trước. Upgrade dùng `changeNodeType` giữ parm cùng tên, rồi
refresh. Một node 2.1 chưa upgrade vẫn ở gốc `/Geo`; cửa sổ báo điều đó.

## 6. Thử trước khi build

- **S1 — groom / cloth bằng value clip.** Trên cache giả (mục 8): Value Clip LOP (cần manifest, sinh một lần) so với Sublayer `$F4`:
  thời gian mở, play, đổi frame, husk có motion blur không. Không đạt → giữ Sublayer `$F4` như 2.1.
- **S2 — Graft Stages bên trong HDA.** Hai instance cùng asset (`/char_X`, `/char_X_inst02`) và hai asset
  khác nhau trên sh012a: binding material đúng, groom / cloth khớp lưới anim, đổi frame và play không chậm
  hơn cách làm tay của người dùng, value clip của S1 còn chạy sau khi ghép.

### Kết quả (2026-11-17, hython 22.0.466; `tools/fx/anim_loader/dev/spike_s1_s2.py`, `spike_s2b_clips_after_graft.py`)

- **S1.** Groom giả sh025 (Helen v005, 20k sợi × 8 điểm, 46 frame): Sublayer `$F4` mở 0.086 s, mỗi frame
  0.004 s, **không blur** (điểm ở 10.5 bằng ở 10); value clip (template `sh025_groom.####.usd`) mở 0.006 s,
  mỗi frame 0.0005 s, **blur đúng** (10.5 nằm giữa 10 và 11), khớp file ở frame 10. Cache chỉ có giá trị
  mặc định (không time sample): clip **không** chạy (USD chỉ đọc time sample trong clip).
- **S2.** Graft Stages với `primpath=/<instance>`, `destpath=""` cho `/char_Robot/Geo/…`,
  `/char_Robot_inst02/Geo/…`, `/char_Robot_2/Geo/…` (`destpath="/"` lồng thêm tên node vào giữa). Hai instance
  chuyển động khác nhau; material của lookdev (ở `/materials`, ngoài `/Geo`) đi theo:
  `/char_Robot_inst02/materials/char_Robot_mtl`.
- **Graft làm phẳng nhánh vào một layer**, nên clip đặt **trong** nhánh bị time sample của frame đầu (lấy
  làm topology) đè: tóc đứng yên sau graft. Cách chạy: clip đặt **sau** graft, ở `/<instance>/Geo/…`,
  trên **layer mới** (Configure Layer `startnewlayer=1` rồi Python LOP); không cần file manifest (USD tự
  sinh). Kết quả: tóc khớp file ở 12, blur ở 10.5, chân tóc nằm trên lưới HairDriver của đúng instance
  (lệch 0.0 m), còn blur sau khi USD ROP ghi stage để render; cloth đè được điểm của anim (cùng layer thì
  anim thắng).
- **Chọn:** mỗi sequence: file đầu có time sample trên `points` → value clip sau graft; không có → Sublayer
  `$F4` (không blur) và node báo "groom: no motion blur (cache has no time samples)". Cần kiểm lại trên cache
  thật đầu tiên (mục 8).

## 7. Phía add-on Blender (và exporter Maya đặt tên giống nó)

- `anim_geo_naming.alloc_unique_basename`: clone thành `_instNN` thay cho `_2`.
- `_write_publish_meta`: thêm `asset` và `instance` cho mỗi output geo (exporter đã biết thư mục asset).
- File đã publish giữ nguyên; loader đọc được cả kiểu cũ (mục 3).
- Làm ở một nhánh riêng, release riêng; loader không chờ nó (đoán được publish cũ).

## 8. Còn chờ người dùng

Không còn câu nào. Người dùng chọn (2026-11-17): S1 / S2 chạy trên cache giả do Claude tạo (mỗi frame một
file, hai kiểu: có time sample ở frame của file, và chỉ có giá trị mặc định), vì chưa có cache thật. Cache
giả cỡ thật ghi vào `D:\Dropbox\Job\260826_grn_vp97\02_shots\sh025\02_fx\` (version `v900`), trên anim
thật của Helen; các trường hợp tên (clone, asset có số) ở shot giả trong sandbox. Khi
grooming department publish cache thật đầu tiên, chạy lại S1 trên nó trước khi phát hành.

## 9. Để người build quyết

Tên parm mới ngoài những tên giữ từ 2.1; bố cục parm của HDA; cách sinh và lưu manifest cho value clip;
thứ tự quét và cache kết quả quét đĩa; nội dung từng test.

## 10. Thứ tự làm

1. `logic.py` + test (naming, instance, đoán asset, groom không lấy thay, version không tự trôi).
2. S1, S2 trên dữ liệu mẫu.
3. `build_hda.py` + adapter + test hython; HDA 2.2 thay được 2.1 trên một shot thật (sh012a: Helen,
   HelenProp, HelenWhale, camera).
4. Mockup cửa sổ → người dùng chọn → `controller.py` / `ui.py` → grab offscreen + kiểm tương phản.
5. Thay đổi add-on Blender (nhánh riêng).
6. Ghi quyết định vào `CLAUDE.md` của suite (mục Anim Loader).
