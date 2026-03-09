# Review khả thi — MONOSTUDIO_EXTRA_TOOL_SPEC

Đối chiếu spec [MonoStudio26/docs/MONOSTUDIO_EXTRA_TOOL_SPEC.md](../../MonoStudio26/docs/MONOSTUDIO_EXTRA_TOOL_SPEC.md) với MonoFXSuite hiện tại.

---

## Tóm tắt mức độ khả thi

| Yêu cầu | Khả thi | Hiện trạng MonoFXSuite | Công việc |
|--------|---------|-------------------------|-----------|
| **1. Vị trí cài đặt** (Option A/B) | Trung bình | Cài `{autopf}\MonoFXSuite`, không nằm dưới MonoStudio | Đổi default/offer path trong installer |
| **2. File VERSION trong bản cài** | Cao | Có VERSION ở repo, **chưa** đóng gói vào installer | Thêm 1 dòng trong .iss |
| **3. GitHub Release** (tag, asset .exe, notes) | Đạt sẵn | Tag vx.y.z, release + RELEASE_NOTES.md, đính kèm .exe | Không |

**Kết luận:** Khả thi tốt. Phần lớn đã đáp ứng; cần bổ sung VERSION vào installer và (nếu muốn tích hợp đầy đủ) hỗ trợ cài đặt dưới thư mục MonoStudio.

---

## 1. Vị trí cài đặt — Khả thi: Trung bình

**Spec:** Cài vào `{MonoStudio}\tools\MonoFXSuite\` (Option A) hoặc `%LOCALAPPDATA%\MonoStudio\tools\MonoFXSuite\` (Option B).

**Hiện tại:** `DefaultDirName={autopf}\MonoFXSuite` → cài độc lập, MonoStudio sẽ không tìm thấy tool theo spec.

**Cần làm:**
- **Option A:** Trong Inno Setup: đọc registry/đường dẫn cài MonoStudio (nếu có), mặc định `DefaultDirName` = `{path MonoStudio}\tools\MonoFXSuite`; hoặc thêm trang wizard cho user chọn “Cài cùng MonoStudio” vs “Cài riêng”.
- **Option B:** Thêm lựa chọn cài vào `{localappdata}\MonoStudio\tools\MonoFXSuite` (không cần admin).

**Độ phức tạp:** Trung bình (custom page/registry, vẫn dùng Inno Setup). Có thể làm từng bước: trước mắt giữ cài riêng, sau bổ sung “install under MonoStudio” khi MonoStudio ổn định API/đường dẫn.

---

## 2. File VERSION trong bản cài — Khả thi: Cao

**Spec:** Trong thư mục gốc bản cài phải có file `VERSION` (một dòng, semantic version).

**Hiện tại:** Repo có `VERSION`; trong `MonoFXSuite.iss` **chưa** có dòng copy `VERSION` vào `{app}`.

**Cần làm:** Thêm vào `[Files]`:

```iss
Source: "..\..\VERSION"; DestDir: "{app}"; Flags: ignoreversion
```

Sau khi thêm, MonoStudio có thể đọc `{app}\VERSION` nếu user cài vào đúng Option A/B.

**Độ phức tạp:** Rất thấp (một dòng, không đụng logic khác).

---

## 3. GitHub Release — Khả thi: Đạt sẵn

**Spec:** Tag dạng v1.0.2, Release từ tag, asset là file .exe installer, release notes trong body.

**Hiện tại:**
- Tag: `v0.1.x`, format đúng.
- Release: `publish_release.ps1` tạo release từ tag, đính kèm `MonoFXSuite_Setup.exe`.
- Release notes: `RELEASE_NOTES.md` → body của release (đã xử lý hiển thị trên web).

Không cần thay đổi thêm cho spec này.

---

## Checklist thực hiện (đã làm)

1. **VERSION trong installer:** Đã thêm `Source: "..\..\VERSION"; DestDir: "{app}"; Flags: ignoreversion` → đáp ứng mục 2.
2. **GitHub Release:** Giữ nguyên (tag, asset .exe, RELEASE_NOTES.md) → đáp ứng mục 3.
3. **Vị trí cài (Option A/B/C):** Đã thêm trang wizard **Install location** trong `MonoFXSuite.iss`:
   - **Option A (mặc định):** Cài dưới MonoStudio → `{pf}\MonoStudio26\tools\MonoFXSuite` (MonoStudio đọc VERSION, hiển thị version + nút Download).
   - **Option B:** User folder → `%LOCALAPPDATA%\MonoStudio\tools\MonoFXSuite` (MonoStudio vẫn detect).
   - **Option C:** Standalone → `{autopf}\MonoFXSuite` (user có thể đổi trên trang chọn thư mục).

Sau khi cài theo Option A hoặc B, MonoStudio sẽ tìm thấy file VERSION và tích hợp Settings → Updates.
