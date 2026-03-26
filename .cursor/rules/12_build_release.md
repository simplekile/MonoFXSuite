# MonoFX Suite — Build & Release

## Khi user nói "release"

- **Tự hiểu**: chạy **toàn bộ quy trình release** — bump version + changelog → build → commit → tag → push → publish.
- **Mặc định bump**: `patch` (nếu user không nói major/minor thì dùng patch).
- **Thứ tự**: `.\bump_version.ps1 patch` (hoặc minor/major) → chỉnh changelog / **RELEASE_NOTES.md** nếu cần → `.\build\build.ps1` → commit VERSION + docs/changelog.md + **RELEASE_NOTES.md** → tag vx.y.z → push main + tag → `.\publish_release.ps1`.

## Khác với MonoStudio

- **Không dùng PyInstaller**: MonoFXSuite là toolkit (Python chạy trong DCC), chỉ đóng gói file nguồn + config bằng Inno Setup.
- **Không** có `build_version.py` hay auto-commit. Version lấy từ file `VERSION` (một nguồn); đồng bộ với `docs/changelog.md` (section `## [x.y.z]`).

## Build installer

- **Script**: `build/build.ps1` hoặc `build/build.bat`. Chạy từ **repo root**: `.\build\build.ps1`.
- **Prerequisite**: Inno Setup 6 (ISCC.exe). Script tìm `C:\Program Files (x86)\Inno Setup 6\ISCC.exe`.
- **Output**: `build/output/MonoFXSuite_Setup.exe`.
- **Version**: `build.ps1` đọc file `VERSION` ở repo root và truyền `/DMyAppVersion=...` cho Inno. File `VERSION` là nguồn version duy nhất cho installer.
- **Inno script**: `build/installer/MonoFXSuite.iss` — fallback `#define MyAppVersion "0.1.0"` khi không truyền từ script.

## Version

- **Format**: `MAJOR.MINOR.PATCH` (vd. `0.1.0`, `1.0.0`). Nguồn: file `VERSION` ở repo root; khi release cập nhật thêm `docs/changelog.md` (section `## [x.y.z] — YYYY-MM-DD`) cho khớp.

### Khi nào bump

- **MAJOR** (x.0.0): Thay đổi breaking — API/config/setup không tương thích ngược; đổi cấu trúc thư mục hoặc cách cài đặt; bỏ/chuyển DCC hoặc tool chính.
- **MINOR** (0.y.0): Tính năng mới tương thích ngược — thêm tool, thêm DCC, cải tiến UI/flow không đổi cách dùng cũ.
- **PATCH** (0.1.z): Sửa lỗi, chỉnh docs, thay đổi nhỏ không ảnh hưởng tính năng — fix bug, cập nhật text/icon, tối ưu nội bộ.

## Bump version và changelog (trước khi release)

- Chạy: `.\bump_version.ps1 <major|minor|patch>` từ repo root.
- Script: tăng `VERSION` theo quy tắc MAJOR.MINOR.PATCH; trong `docs/changelog.md` thêm section `## [x.y.z] — YYYY-MM-DD` ngay dưới `[Unreleased]` và chuyển nội dung đang nằm dưới `[Unreleased]` vào section mới (nếu không có thì để placeholder).
- **Release notes**: Script còn ghi file `RELEASE_NOTES.md` ở repo root (nội dung = section version mới trong changelog). File này dùng làm body cho GitHub Release khi chạy `publish_release.ps1`. Có thể chỉnh `RELEASE_NOTES.md` trước khi publish.
- Sau khi chạy: có thể chỉnh lại changelog hoặc RELEASE_NOTES.md rồi mới build/publish.

## Release lên GitHub

1. Bump: `.\bump_version.ps1 patch` (hoặc minor/major). Chỉnh changelog nếu cần.
2. Build: `.\build\build.ps1`.
3. Commit: `git add VERSION docs/changelog.md RELEASE_NOTES.md`, `git commit -m "docs: release vx.y.z"`.
4. Tag: `git tag -a vx.y.z -m "Release vx.y.z"`.
5. Push: `git push origin main`, `git push origin vx.y.z`.
6. Publish: `.\publish_release.ps1` — cần GitHub CLI (`gh`), đã `gh auth login`. Script đọc `VERSION`, lấy release notes từ **RELEASE_NOTES.md** (nếu có) hoặc từ changelog, tạo release và đính kèm `build/output/MonoFXSuite_Setup.exe`. Nếu tag chưa có thì báo tạo/push tag trước.

## Checklist khi release

- [ ] Đã chạy `.\bump_version.ps1 patch` (hoặc minor/major) và chỉnh changelog / RELEASE_NOTES.md nếu cần.
- [ ] `VERSION` và section changelog `[x.y.z]` khớp nhau.
- [ ] Đã build: `.\build\build.ps1`.
- [ ] Đã commit, tag, push.
- [ ] Đã chạy `.\publish_release.ps1` (hoặc tạo Release tay trên GitHub).
