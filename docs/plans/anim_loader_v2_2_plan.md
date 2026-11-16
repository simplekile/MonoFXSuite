# Mono Anim Loader 2.2 — kế hoạch làm

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** HDA `mono_anim_loader::2.2` dựng từ repo, mỗi node load một instance (anim + lookdev + groom +
cloth) hoặc camera và graft vào `/<instance>`, cùng một cửa sổ PySide6 quản lý mọi loader trong scene.

**Architecture:** `tools/fx/anim_loader/logic.py` (không `hou`, pytest) quyết định mọi đường dẫn và trạng
thái; `apps/houdini/anim_loader_adapter.py` đọc / ghi node; `build_hda.py` dựng HDA mỏng có PythonModule
chỉ import adapter; cửa sổ `controller.py` (không Qt) + `ui.py` (PySide6).

**Tech Stack:** Python 3.11 (Houdini 22.0.466), pxr, PySide6, pytest, hython
(`C:/Program Files/Side Effects Software/Houdini 22.0.466/bin/hython.exe`).

**Spec:** `docs/plans/anim_loader_v2_2.md` (đọc trước task đầu).

## Global Constraints

- Type `mono_anim_loader::2.2`, label "Mono Anim Loader", file `otls/mono_anim_loader.hdalc`, icon `LOP_valueclip`.
- Clone mới: `geo_<asset>_instNN.usd` (NN hai chữ số, từ 02); meta geo: `{"file", "type": "geo", "asset", "instance"}`.
- Tên graft = tên file bỏ `geo_` và đuôi: `geo_char_Helen.usd` → `/char_Helen/Geo/…`, `geo_char_Helen_inst02.usd` → `/char_Helen_inst02`, `geo_char_Helen_2.usd` → `/char_Helen_2`. Camera không graft.
- Groom / cloth: `02_shots/<shot>/02_fx/{groom,cloth}/publish/vNNN/<thư mục>/<shot>_{groom,cloth}.####.usd`; thư mục thử `<asset đầy đủ>[_instNN]` rồi `<tên không loại>[_instNN]`; không bao giờ lấy thư mục khác; file ngay dưới `vNNN` chỉ khi shot có đúng một instance geo.
- Version trên node luôn là `vNNN` cụ thể; chỉ chọn mới nhất lúc tạo node; không gì tự đổi.
- Giữ tên parm 2.1 khi nghĩa không đổi (danh sách ở Task 5).
- Mỗi lệnh ghi scene là một bước undo (`solaris_adapter.undo_group`); node mới đặt bằng `solaris_adapter._place_new`; không dời / nối lại node có sẵn.
- Không hộp thoại modal; kết quả và lỗi ra `mx_status` / dòng dưới cửa sổ / status bar. Chữ người dùng đọc bằng tiếng Anh.
- Trong project thật chỉ ghi cache giả groom / cloth của sh025, đúng chỗ người dùng chỉ (2026-11-17):
  `D:\Dropbox\Job\260826_grn_vp97\02_shots\sh025\02_fx\{groom,cloth}\publish\v900\…`, kèm `_FAKE_README.txt`.
  Dùng `v900` để không chiếm `v001` của bản publish thật đầu tiên; xoá khi có cache thật (hỏi người dùng
  trước). Mọi dữ liệu thử khác ở `E:/01 Dev/sandbox/claude/anim_loader/`.
- Thư viện 2.1 (`D:\Dropbox\Stock\Plugin\HOU\Mono\hda\lop_mono_anim_loader.2.1.hdalc`) không sửa.

## Review Focus

1. Publish cũ không meta, `char_Robot` và `char_Robot_2` cùng có trong `01_assets`, file `geo_char_Robot_2.usd` → "asset?", không lookdev, không groom (Task 1 `test_ambiguous_old_clone`).
2. File anim không mang tên asset (`geo_sh011.usd` có thật trong sh011) → vẫn load anim, lookdev/groom/cloth báo "asset?" chứ không lỗi (Task 1 `test_no_asset_name`).
3. Thư mục `vNNN` viết hoa (`V002`) hoặc thư mục rác (`v002_old`, `tmp`) trong publish → chỉ nhận `[vV]\d+`, sắp theo số (Task 2 `test_versions_case_and_junk`).
4. Sequence groom thiếu frame ở giữa hoặc pad khác nhau (`.0001` vs `.001`) → frame range đúng theo file có thật, pad theo file, báo thiếu frame (Task 2 `test_fx_gaps_and_padding`).
5. Bấm Load shot hai lần, hoặc sau khi người dùng đổi tên node → không tạo trùng (nhận loader bằng user data `monofx_anim_loader` = shot + anim_file, không bằng tên node) (Task 6 `accept_load_shot_twice`).

---

### Task 1: Nhận instance và asset từ output

**Files:**
- Create: `tools/fx/anim_loader/__init__.py`, `tools/fx/anim_loader/config.py`, `tools/fx/anim_loader/logic.py`
- Test: `tests/test_anim_loader_logic.py`

**Interfaces:**
- Produces:
  - `config.ASSET_TYPES = ("char", "prop", "veh", "env", "set", "fx")`, `config.CLONE_RE = r"_inst(\d{2,})$"`
  - `@dataclass(frozen=True) Output(file: str, kind: str, asset: str | None = None, instance: int | None = None)` — `kind` ∈ `"geo"`, `"cam"`
  - `@dataclass(frozen=True) Instance(name: str, anim_file: str, kind: str, asset: str | None, instance: int, guessed: bool, candidates: tuple[str, ...])` — `asset None` = "asset?"
  - `instance_name(anim_file: str) -> str` — bỏ `geo_` / `cam_` và đuôi
  - `resolve_instance(output: Output, asset_names: set[str]) -> Instance`

- [ ] **Step 1: Viết test**

```python
A = {"char_Robot", "char_Robot_2", "prop_CoralSet_001", "char_Helen"}
def test_meta_wins():
    i = resolve_instance(Output("geo_char_Robot_2.usd", "geo", "char_Robot", 2), A)
    assert (i.name, i.asset, i.instance, i.guessed) == ("char_Robot_2", "char_Robot", 2, False)
def test_new_clone_suffix():
    i = resolve_instance(Output("geo_char_Robot_inst02.usd", "geo"), A)
    assert (i.name, i.asset, i.instance) == ("char_Robot_inst02", "char_Robot", 2)
def test_asset_with_digits():
    assert resolve_instance(Output("geo_prop_CoralSet_001.usd", "geo"), A).asset == "prop_CoralSet_001"
def test_old_clone_suffix():
    i = resolve_instance(Output("geo_char_Helen_2.usd", "geo"), A)
    assert (i.asset, i.instance, i.guessed) == ("char_Helen", 2, True)
def test_ambiguous_old_clone():
    i = resolve_instance(Output("geo_char_Robot_2.usd", "geo"), A)
    assert i.asset is None and set(i.candidates) == {"char_Robot", "char_Robot_2"}
def test_no_asset_name():
    i = resolve_instance(Output("geo_sh011.usd", "geo"), A)
    assert i.asset is None and i.candidates == () and i.name == "sh011"
def test_camera():
    i = resolve_instance(Output("cam_sh010.usd", "cam"), A)
    assert (i.kind, i.asset, i.name) == ("cam", None, "sh010")
```

- [ ] **Step 2: Chạy, thấy fail** — `pytest tests/test_anim_loader_logic.py -v` → ImportError.
- [ ] **Step 3: Viết `instance_name`, `resolve_instance`** theo luật mục 3 của spec (meta → `_instNN` → tên khớp
  asset → bỏ `_<số>` → mơ hồ khi cả hai luật khớp hai asset khác nhau). Camera: `asset None`, `candidates ()`.
- [ ] **Step 4: Chạy, thấy pass.**
- [ ] **Step 5: Commit** `feat(anim-loader): resolve shot instances from anim outputs`.

### Task 2: Quét publish trên đĩa

**Files:**
- Modify: `tools/fx/anim_loader/logic.py`, `tools/fx/anim_loader/config.py`
- Create: `tests/anim_loader_tree.py` (dựng cây thư mục giả trong `tmp_path`, file rỗng, không USD; không có tên `test_`)
- Test: `tests/test_anim_loader_logic.py`

**Interfaces:**
- Consumes: `Output`, `Instance`, `resolve_instance` (Task 1)
- Produces:
  - `find_project_root(path: Path) -> Path | None` (thư mục có `01_assets` và `02_shots`), `detect_shot(path: Path) -> str | None` — lấy lại hai hàm của `apps/houdini/hda/anim_loader_simple.py`, giữ hành vi
  - `list_asset_dirs(project_root: Path) -> dict[str, Path]` — `01_assets/_*/<asset>`
  - `list_versions(publish_dir: Path) -> list[str]` — tên thư mục như trên đĩa, sắp theo số
  - `anim_publish_dir(root, shot) -> Path`, `read_outputs(version_dir: Path) -> list[Output]` — `publish_meta.json` `outputs` trước; không có meta thì `geo_*` / `cam_*` `.usd/.usda/.usdc`
  - `read_timeline(version_dir) -> tuple[float, int, int] | None` — fps, start, end từ meta
  - `lookdev_file(asset_dir: Path, version: str) -> Path | None` — `05_lookdev/publish/<version>/<asset>_lookdev_publish.usd*`
  - `@dataclass(frozen=True) FxMatch(folder: Path | None, pattern: str, first: int | None, last: int | None, missing: tuple[int, ...], reason: str)` — `pattern` dùng `$F<pad>`
  - `fx_match(root: Path, shot: str, task: str, version: str, inst: Instance, geo_count: int) -> FxMatch` — `task` ∈ `"groom"`, `"cloth"`

- [ ] **Step 1: Viết test** (cây thư mục dựng bằng `anim_loader_tree.make(tmp_path, spec_dict)`)

```python
def test_versions_case_and_junk(tmp_path):  # v001, V002, v002_old, tmp, v010
    assert list_versions(p) == ["v001", "V002", "v010"]
def test_outputs_from_meta_then_files(tmp_path): ...  # meta có asset/instance; không meta → từ tên file, asset None
def test_fx_exact_folder_only(tmp_path):
    # v001/char_Robot/sh900_groom.0001-0024.usd ; không có thư mục cho char_Robot_inst02
    m = fx_match(root, "sh900", "groom", "v001", robot_inst02, geo_count=3)
    assert m.folder is None and "char_Robot_inst02" in m.reason
def test_fx_old_folder_style(tmp_path):  # thư mục Robot_inst02/ được nhận cho char_Robot_inst02
def test_fx_flat_only_when_single_instance(tmp_path):  # file ngay dưới v001: geo_count=1 nhận, =2 không
def test_fx_gaps_and_padding(tmp_path):  # .0001,.0002,.0004 → first 1, last 4, missing (3,), pattern "…sh900_groom.$F4.usd"
def test_lookdev_by_version(tmp_path):  # v002 có, v003 không → None
```

- [ ] **Step 2: Chạy, thấy fail.**
- [ ] **Step 3: Viết các hàm trên.** Khớp tên shot và `_groom`/`_cloth` không phân biệt hoa thường; pad = số chữ số của file đầu.
- [ ] **Step 4: Chạy, thấy pass** (cả Task 1).
- [ ] **Step 5: Commit** `feat(anim-loader): scan anim, lookdev, groom and cloth publishes`.

### Task 3: Trạng thái node so với đĩa

**Files:** Modify `tools/fx/anim_loader/logic.py`; Test `tests/test_anim_loader_logic.py`

**Interfaces:**
- Consumes: Task 1-2
- Produces:
  - `STATUS_OK, STATUS_NEWER, STATUS_MISSING, STATUS_OFF, STATUS_ASSET = "ok", "newer", "missing", "off", "asset?"`
  - `@dataclass LoaderState(project_root: str, shot: str, anim_version: str, anim_file: str, asset: str | None, instance_name: str, kind: str, enabled: dict[str, bool], versions: dict[str, str])` — khoá `"lookdev"`, `"groom"`, `"cloth"`
  - `@dataclass(frozen=True) Resolved(anim: str, lookdev: str, groom: str, cloth: str, frames: dict[str, tuple[int, int]], notes: tuple[str, ...])` — đường dẫn rỗng khi không có
  - `resolve(state: LoaderState) -> Resolved` — chỉ đọc, cùng state luôn ra cùng kết quả
  - `status(state: LoaderState) -> dict[str, tuple[str, str | None]]` — mỗi phần (anim, lookdev, groom, cloth) → (trạng thái, version mới hơn nếu có)
  - `initial_state(root: Path, shot: str, anim_version: str, output: Output) -> LoaderState` — version mới nhất mỗi phần, một lần
  - `with_latest(state: LoaderState, parts: tuple[str, ...]) -> LoaderState`

- [ ] **Step 1: Viết test:** `test_initial_picks_latest_once` (thêm v003 lookdev sau khi tạo state → `resolve` vẫn ra v002, `status` báo `("newer", "v003")`); `test_off_part`; `test_asset_unknown_parts` (asset None → lookdev/groom/cloth `"asset?"`, anim ok); `test_with_latest_only_named_parts`.
- [ ] **Step 2: Chạy, thấy fail.**
- [ ] **Step 3: Viết.**
- [ ] **Step 4: Chạy, thấy pass.**
- [ ] **Step 5: Commit** `feat(anim-loader): loader state, resolve and status`.

### Task 4: Shot giả và hai phần thử S1 / S2

**Files:**
- Create: `tools/fx/anim_loader/dev/make_fake_shot.py` (hython; `python make_fake_shot.py <out>`), `tools/fx/anim_loader/dev/make_fake_sh025_fx.py` (hython; không đối số, ghi đúng chỗ ở Global Constraints), `tools/fx/anim_loader/dev/spike_s1_s2.py` (hython; ghi `spike.json` + ảnh vào `<out>/spike/`)
- Modify: `docs/plans/anim_loader_v2_2.md` (ghi kết quả S1 / S2 và lựa chọn vào mục 6)

**Interfaces:**
- Produces: project giả ở `E:/01 Dev/sandbox/claude/anim_loader/fake_project/` mà Task 5-6 dùng; `config.FX_MODE` ∈ `"clip"`, `"sublayer"` theo kết quả S1.

Shot giả `sh900`, fps 24, frame 1-24:
- Asset `01_assets/_characters/char_Robot`, `char_Robot_2`, `01_assets/_props/prop_CoralSet_001`; lookdev v001, v002 cho mỗi asset: material ở `/materials/<asset>_mtl` (ngoài `/Geo`), bind vào `/Geo/Base_grp/Body_grp/body`.
- Anim `v001` (kiểu cũ, meta không asset): `geo_char_Robot`, `geo_char_Robot_2`, `geo_prop_CoralSet_001`, `cam_sh900`. `v002` (kiểu mới, meta đủ): `geo_char_Robot`, `geo_char_Robot_inst02`, `geo_char_Robot_2`, `cam_sh900`. Mỗi geo: gốc `/Geo/Base_grp/Body_grp/body` (mesh ~2k điểm, chuyển động khác nhau theo time sample), `/Geo/Groom_grp/HairDriver_grp`, như file thật.
- Groom `v001/char_Robot/` (kiểu tên đầy đủ) và `v001/Robot_inst02/` (kiểu cũ), mỗi frame một file `sh900_groom.0001.usd`: BasisCurves ~20k sợi × 8 điểm dưới `/Geo/Groom_grp/hair`, bám lưới anim của instance đó. Hai biến thể: `v001` có time sample tại frame của file; `v002` chỉ có giá trị mặc định. Cloth `v001/char_Robot_2/sh900_cloth.####.usd` (mesh).

Cache giả trên shot thật **sh025** (anim thật v005: Helen, HelenWhale, Spaceship, camera; 30 fps, frame
0-45), script `tools/fx/anim_loader/dev/make_fake_sh025_fx.py`:
- Groom `02_fx/groom/publish/v900/char_Helen/sh025_groom.0000.usd` … `.0045.usd`: BasisCurves mọc trên
  `/Geo/Groom_grp/HairDriver_grp` của `geo_char_Helen.usd` v005, đọc lưới ở từng frame nên tóc theo nhân
  vật; ~100k sợi × 8 điểm (cỡ Helen thật) để S1 đo được thời gian thật. Có time sample tại frame của file.
- Cloth `02_fx/cloth/publish/v900/char_Helen/sh025_cloth.0000.usd` …: lưới `Outfit_grp` của anim, đẩy
  ra 0.5 cm theo normal.
- `_FAKE_README.txt` trong mỗi `v900`: "Fake cache made by Claude for Mono Anim Loader tests, not a real
  publish." Không ghi gì khác vào sh025.
- S1 đo trên cache sh025 này (cỡ thật); bản chỉ có giá trị mặc định thử trên `sh900`. S2 chạy trên cả hai.

- [ ] **Step 1: Viết `make_fake_shot.py`**, chạy: `hython tools/fx/anim_loader/dev/make_fake_shot.py "E:/01 Dev/sandbox/claude/anim_loader/fake_project"` → in số file; kiểm bằng `logic.read_outputs` và `fx_match` thấy đủ (một lệnh python in ra).
- [ ] **Step 2: S1** — trên `char_Robot` groom v001 và v002: (a) Sublayer `$F4`, (b) Value Clip LOP + manifest sinh một lần. Đo: thời gian mở, đổi 24 frame, husk 1 frame có motion blur (Subframe Samples 2, so ảnh blur với không blur). Ghi `spike.json`.
- [ ] **Step 3: S2** — mạng tay trong hython: mỗi instance anim + lookdev + groom + cloth → Graft Stages dưới `/<instance>`; v002 đủ 3 instance + camera. Kiểm: `/char_Robot/Geo/…` và `/char_Robot_inst02/Geo/…` có điểm khác nhau ở frame 12; binding của mỗi body trỏ tới `/<instance>/materials/…` có thật; groom nằm cạnh body đúng instance; clip của S1 còn chạy sau graft.
- [ ] **Step 4: Ghi kết quả** vào mục 6 của spec (số đo, chọn `FX_MODE`, cách ghép lớp trong HDA); đặt `config.FX_MODE`.
- [ ] **Step 5: Commit** `test(anim-loader): fake shot and S1/S2 spike results`.

### Task 5: Dựng HDA 2.2 và refresh

**Files:**
- Create: `tools/fx/anim_loader/build_hda.py`, `apps/houdini/anim_loader_adapter.py`, `tests/houdini/anim_loader/accept_hda.py`
- Modify: `apps/houdini/hda/__init__.py` (không đổi; chỉ kiểm không import hou)

**Interfaces:**
- Consumes: `LoaderState`, `resolve`, `status`, `initial_state` (Task 3); `config.FX_MODE` (Task 4)
- Produces:
  - `build(out_path: str = DEFAULT_OUT) -> str` — như `tools/fx/grooming/build_hda.py:build`
  - adapter: `read_state(node) -> LoaderState`, `write_state(node, state: LoaderState) -> None`, `refresh(node) -> Resolved` (ghi parm ẩn đường dẫn + `mx_status`), `create_loader(parent: hou.Node, root: str, shot: str, anim_version: str, output: Output) -> hou.Node`, `cb_parm_changed(kwargs)`, `cb_open_manager(kwargs)`, `cb_apply_timeline(kwargs)`
  - Parm giữ của 2.1: `mx_project_root`, `mx_shot`, `mx_anim_publish_parent`, `mx_anim_version`, `mx_anim_usd`, `mx_selected_anim_usd_path`, `mx_geo_cam`, `mx_enable_lookdev`, `mx_lookdev_version`, `mx_selected_lookdev_usd_path`, `mx_enable_groom`, `mx_groom_version`, `mx_groom_asset`, `mx_selected_groom_usd_path`, `mx_enable_cloth`, `mx_cloth_version`, `mx_cloth_asset`, `mx_selected_cloth_usd_path`, `mx_status`, `LOP_scale`, `scale`, `primpattern`, `visibility`, `scale2`, `horizontalAperture`, `xn__houdiniguidescale_s3a`, `clippingRange`, `aspectratio`, `apply_mx_timeline`. Mới: `mx_asset`, `mx_instance_name`, `mx_manager` (nút).
  - User data trên node: `monofx_anim_loader` = JSON `{"shot", "anim_file"}`.

Mạng bên trong theo kết quả S2; bắt buộc: input 0 đi qua; instance graft dưới `/<mx_instance_name>`; camera không graft; giữ các chỉnh scale / visibility / camera của 2.1 (đã dump: `transform2` scale theo `../scale`, `switch2` theo `../LOP_scale`, `camera_edit1` pattern `*_cam`, `transform4` scale 100); groom / cloth theo `FX_MODE`. PythonModule: `from apps.houdini.anim_loader_adapter import *`.

- [ ] **Step 1: Viết `accept_hda.py`** (mẫu `tests/houdini/grooming/accept_lib.py`: ghi `accept.json` từng check): build vào thư mục tạm; trên fake project v002 tạo 3 loader + camera bằng `create_loader`, nối vào một Merge; kiểm prim `/char_Robot/Geo/Base_grp/Body_grp/body`, `/char_Robot_inst02/…`, `/char_Robot_2/…` có, điểm khác nhau ở frame 12; một stage có sẵn ở input 0 vẫn còn ở output; lookdev bind đúng; groom có ở `char_Robot` và `char_Robot_inst02`, cloth ở `char_Robot_2`; đổi `mx_lookdev_version` → refresh ghi đường dẫn mới; thêm `v003` lookdev trên đĩa → đường dẫn không đổi, `mx_status` nói `v003`; lưu hip, mở lại → mọi parm như trước.
- [ ] **Step 2: Chạy, thấy fail:** `hython tests/houdini/anim_loader/accept_hda.py "E:/01 Dev/sandbox/claude/anim_loader/fake_project" <out>`.
- [ ] **Step 3: Viết `build_hda.py` và adapter.**
- [ ] **Step 4: Chạy lại, mọi check pass;** `pytest tests/test_anim_loader_logic.py` vẫn pass.
- [ ] **Step 5: Build vào `otls/`:** `hython tools/fx/anim_loader/build_hda.py` → `built …/otls/mono_anim_loader.hdalc`.
- [ ] **Step 6: Commit** `feat(anim-loader): build mono_anim_loader::2.2 from code`.

### Task 6: Lệnh của cửa sổ (không UI)

**Files:** Modify `apps/houdini/anim_loader_adapter.py`; Create `tests/houdini/anim_loader/accept_commands.py`

**Interfaces:**
- Consumes: Task 5
- Produces:
  - `find_loaders(root: hou.Node | None = None) -> list[hou.Node]` — mọi node type `mono_anim_loader::2.1` và `::2.2` dưới `/stage` (cả trong subnet)
  - `@dataclass LoadResult(created: list[str], kept: list[str], notes: list[str])`
  - `load_shot(parent: hou.Node, root: str, shot: str, anim_version: str) -> LoadResult` — một undo, nhận loader có sẵn bằng user data, tạo Merge của shot (user data `monofx_anim_loader_merge` = shot) nếu chưa có, nối node mới vào
  - `update(nodes: list[hou.Node], parts: tuple[str, ...] = ("anim", "lookdev", "groom", "cloth")) -> list[str]` — một undo
  - `upgrade(nodes: list[hou.Node]) -> list[hou.Node]` — `changeNodeType("mono_anim_loader::2.2", keep_parms=True)` rồi điền `mx_asset`, `mx_instance_name` từ Task 1, refresh; một undo
  - `set_asset(node, asset: str) -> None` — cho dòng "asset?"
  - `apply_timeline(node) -> str`

- [ ] **Step 1: Viết `accept_commands.py`:** `accept_load_shot_twice` (load v002 hai lần, đổi tên một node ở giữa → lần hai `created == []`); `accept_load_ambiguous` (v001: `char_Robot_2` → `mx_status` có "asset?", `set_asset(node, "char_Robot")` → lookdev đúng); `accept_update_one_undo` (update 3 node → một `hou.undos` bước, undo trả về version cũ); `accept_upgrade_21` (cài thư viện 2.1, tạo node 2.1 trỏ v001 `geo_char_Robot`, upgrade → giữ `mx_shot`, `mx_anim_version`, `mx_anim_usd`, gốc mới `/char_Robot`); `accept_no_move` (vị trí node có sẵn không đổi sau load_shot).
- [ ] **Step 2: Chạy, thấy fail.**
- [ ] **Step 3: Viết các lệnh.**
- [ ] **Step 4: Chạy, pass.**
- [ ] **Step 5: Commit** `feat(anim-loader): load shot, update, upgrade commands`.

### Task 7: Mockup cửa sổ (người dùng chọn)

**Files:** Create mockup theo skill `.claude/skills/dcc-panel-design` (2-3 phương án) dựa trên mục 5.5 của spec.

- [ ] **Step 1: Đọc skill, liệt kê việc của artist** (xem shot, thấy cái cũ / thiếu, cập nhật, load shot, sửa "asset?", upgrade 2.1).
- [ ] **Step 2: Làm 2-3 mockup**, gửi người dùng, **chờ chọn**. Không sang Task 8 trước khi người dùng chọn.
- [ ] **Step 3: Ghi phương án được chọn** vào spec mục 5.5; commit `docs(anim-loader): manager layout`.

### Task 8: Controller

**Files:** Create `tools/fx/anim_loader/controller.py`; Test `tests/test_anim_loader_controller.py`

**Interfaces:**
- Consumes: `LoaderState`, `status` (Task 3); hàm lệnh của Task 6 qua một đối tượng `backend` truyền vào (test dùng bản giả)
- Produces: `@dataclass Row(node_path: str, shot: str, instance: str, kind: str, parts: dict[str, tuple[str, str | None]], legacy: bool)`; `class Controller(backend)`: `rows() -> list[Row]` (nhóm theo shot, sắp theo instance), `selection`, `update_selected()`, `update_all()`, `load_shot(shot, version)`, `upgrade_selected()`, `set_asset(path, asset)`, `message -> str`; quét đĩa qua `backend.scan(...)` để chạy được trên worker thread, kết quả cũ bị bỏ khi có lần quét mới.

- [ ] **Step 1: Viết test:** `test_rows_grouped_by_shot`, `test_update_all_counts_only_behind` ("Update all (2)"), `test_stale_scan_dropped`, `test_legacy_rows_offer_upgrade`, `test_message_after_load_shot` ("Created 3, kept 1").
- [ ] **Step 2: Fail → Step 3: Viết → Step 4: Pass.**
- [ ] **Step 5: Commit** `feat(anim-loader): manager controller`.

### Task 9: Cửa sổ PySide6

**Files:** Create `tools/fx/anim_loader/ui.py`; Modify `apps/houdini/anim_loader_adapter.py` (`cb_open_manager` mở một cửa sổ duy nhất); shelf tool theo mẫu shelf của Auto Material; Test `tests/test_anim_loader_ui.py` (offscreen, như `tests/test_auto_material_ui.py`).

- [ ] **Step 1: Viết test offscreen:** cửa sổ dựng với backend giả, đủ dòng, nút "Update all (N)" đúng N, dòng "asset?" có menu chọn asset.
- [ ] **Step 2: Fail → Step 3: Viết theo mockup đã chọn**, dùng palette / role chung (`ui._text`, `STATUS_COLORS` của `tools/fx/auto_material/ui.py`), font px qua `Sz`.
- [ ] **Step 4: Pass;** grab offscreen `scripts/grab_offscreen.py` ở 400 / 760 / 1100 px, scale 1 / 1.5; `scripts/contrast_check.py` pass.
- [ ] **Step 5: Thử trong Houdini thật trên màn phụ** với fake project, chụp, gửi người dùng.
- [ ] **Step 6: Commit** `feat(anim-loader): manager window`.

### Task 10: Add-on Blender đặt tên clone và ghi meta (nhánh riêng)

**Files:**
- Modify: `packages/monofx_pipeline_common/src/monofx_pipeline_common/anim_geo_naming.py` (`alloc_unique_basename`), `tools/fx/monofx_pipeline_blender/monofx_pipeline_blender/anim_usd_cache_exporter.py:1092` (`_write_publish_meta`, nhận `geo_assets: Sequence[tuple[Path, str | None, int]]`)
- Test: `tests/test_anim_geo_naming.py`, test meta mới cạnh test exporter hiện có

- [ ] **Step 1: Sửa test** `test_alloc_unique_basename_for_duplicate_rigs`: lần hai → `geo_char_Tachi_inst02`, lần ba → `_inst03`; thêm test asset `char_Robot_2` không bị nhầm thành clone (`resolve_geo_usd_basename(asset_folder="char_Robot_2")` → `geo_char_Robot_2`).
- [ ] **Step 2: Fail → Step 3: Viết** (đuôi `_inst{n:02d}`; meta thêm `asset`, `instance` từ thư mục asset của job).
- [ ] **Step 4: Pass** cả `pytest tests/test_anim_geo_naming.py tests/test_anim_usd_cache_paths.py`.
- [ ] **Step 5: Commit** trên nhánh riêng `feat(blender): clone suffix _instNN and asset/instance in publish_meta`; ghi changelog `## [Unreleased]`.

### Task 11: Ghi chú và changelog

**Files:** Modify `CLAUDE.md` (mục mới "Mono Anim Loader 2.2": quy ước tên, graft, version không tự đổi, FX_MODE và lý do), `docs/changelog.md` (`## [Unreleased]`).

- [ ] **Step 1: Viết ghi chú** (ngắn, theo giọng các mục khác của `CLAUDE.md`).
- [ ] **Step 2: Chạy toàn bộ** `pytest` và hai script hython của Task 5-6 → pass.
- [ ] **Step 3: Commit** `docs(anim-loader): notes and changelog`.

Trước khi phát hành: chạy lại S1 trên cache groom thật đầu tiên grooming department publish (spec mục 8).
