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
- **build/build.ps1** — đọc `VERSION`, gọi Inno với `/DMyAppVersion=...`; output `build/output/MonoFXSuite_Setup.exe`.
- **build/installer/MonoFXSuite.iss** — `#ifndef MyAppVersion` fallback; version thật lấy từ build script.
- **publish_release.ps1** — đọc `VERSION` → tag `vx.y.z`, trích release notes từ `docs/changelog.md`, `gh release create` + đính kèm exe. Cần `gh auth login`.

## So với MonoStudio (tránh conflict)

- MonoStudio: PyInstaller onedir → Inno, VERSION từ git count, auto-commit, `RELEASE_NOTES.md`.
- MonoFXSuite: chỉ Inno, `VERSION` file tĩnh, không auto-commit; rule build tại `.cursor/rules/12_build_release.md`.
