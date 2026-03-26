# Phương án build & release — MonoFX Suite

## Phương án đang dùng (đã triển khai)

| Nội dung | Chọn |
|----------|------|
| **Build** | Chỉ Inno Setup (pack files), không PyInstaller. |
| **Script** | `build/build.ps1` từ repo root. |
| **Version** | Một nguồn: file `VERSION` ở repo root; `build.ps1` đọc và truyền `/DMyAppVersion=...` cho Inno. Changelog vẫn có section `## [x.y.z]` để khớp. |
| **Release GitHub** | Tag + push; sau đó `publish_release.ps1` (GitHub CLI) tạo release, notes từ changelog, đính kèm `MonoFXSuite_Setup.exe`. |

**Lý do**: Toolkit chạy trong Houdini, không cần exe đóng băng; pipeline đơn giản, một nguồn version, publish một lệnh.

## Đã có trong repo

- **VERSION** — một dòng version (vd. `0.1.0`). Build và publish đều đọc từ đây.
- **bump_version.ps1** — `.\bump_version.ps1 major|minor|patch`: tăng `VERSION`, thêm section trong changelog, và ghi **RELEASE_NOTES.md** (nội dung = release note cho version đó). Chạy trước khi build/publish.
- **RELEASE_NOTES.md** — Release note cho bản sắp phát hành; `bump_version.ps1` tạo/cập nhật, `publish_release.ps1` dùng làm body GitHub Release. Có thể chỉnh tay trước khi publish.
- **build/build.ps1** — đọc `VERSION`, gọi Inno với `/DMyAppVersion=...`; output `build/output/MonoFXSuite_Setup.exe`.
- **build/installer/MonoFXSuite.iss** — `#ifndef MyAppVersion` fallback; version thật lấy từ build script.
- **publish_release.ps1** — đọc `VERSION` → tag `vx.y.z`, trích release notes từ `docs/changelog.md`, `gh release create` + đính kèm exe. Cần `gh auth login`.

## So với MonoStudio (tránh conflict)

- MonoStudio: PyInstaller onedir → Inno, VERSION từ git count, auto-commit, `RELEASE_NOTES.md`.
- MonoFXSuite: chỉ Inno, `VERSION` file tĩnh, không auto-commit; rule build tại `.cursor/rules/12_build_release.md`.
