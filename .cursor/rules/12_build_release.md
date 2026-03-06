# MonoFX Suite — Build & Release

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

- **Nguồn**: File `VERSION` ở repo root (vd. `0.1.0`). Build dùng nó; khi release cập nhật thêm `docs/changelog.md` (section `## [x.y.z] — YYYY-MM-DD`) cho khớp.

## Release lên GitHub

1. Cập nhật `VERSION` và changelog: thêm section `## [x.y.z] — YYYY-MM-DD` trong `docs/changelog.md`, giữ `## [Unreleased]` ở trên.
2. Build: `.\build\build.ps1`.
3. Commit: `git add VERSION docs/changelog.md`, `git commit -m "docs: release vx.y.z"`.
4. Tag: `git tag -a vx.y.z -m "Release vx.y.z"`.
5. Push: `git push origin main`, `git push origin vx.y.z`.
6. Publish release: `.\publish_release.ps1` — cần GitHub CLI (`gh`), đã `gh auth login`. Script đọc `VERSION`, lấy release notes từ changelog, tạo release và đính kèm `build/output/MonoFXSuite_Setup.exe`. Nếu tag chưa có thì báo tạo/push tag trước.

## Checklist khi release

- [ ] `VERSION` và section changelog `[x.y.z]` khớp nhau.
- [ ] Đã build: `.\build\build.ps1`.
- [ ] Đã commit, tag, push.
- [ ] Đã chạy `.\publish_release.ps1` (hoặc tạo Release tay trên GitHub).
