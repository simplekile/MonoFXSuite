# Changelog

## [Unreleased]

### Installer & setup
- Installer tạo folder riêng `monofx` trong user Houdini (giống modeler): `Documents\houdiniXX.X\monofx\` với `config\Icons\`, `toolbar\MonoFX.shelf`; ghi `packages\monofx_shelf.json` (hpath = `$HOUDINI_USER_PREF_DIR/monofx`).
- Thêm script build: `build/build.ps1`, `build/build.bat` — chạy từ thư mục gốc: `.\build\build.ps1` hoặc `build\build.bat`.
- Output installer: `build/output/MonoFXSuite_Setup.exe` (không version trong tên file).

### Shelf icons
- Icon shelf có nền bo tròn, màu nền khác nhau từng tool (info: xanh dương, layers: xanh lá, replace: cam, palette: tím).
- Icon màu trắng, scale 0.65, nền full 24×24 — nền to hơn icon.
- Cập nhật cả `config/Icons/` và `toolbar/icons/` (Lucide-based SVG).

### Docs
- `docs/setup/inno_build.md`: hướng dẫn build bằng script.
- `docs/setup/modeler_structure_reference.md`: tham khảo cấu trúc plugin modeler.
- `docs/setup/monofx_user_prefs_example.json`: mẫu package cài kiểu user prefs.
- `docs/setup/houdini_setup.md`: cập nhật mô tả folder monofx và monofx_shelf.json.
