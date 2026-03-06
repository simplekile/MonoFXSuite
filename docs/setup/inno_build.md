# Build installer với Inno Setup

MonoFX Suite sẽ được đóng gói bằng **Inno Setup** (Windows installer).

## Kế hoạch

- **Công cụ:** [Inno Setup](https://jrsoftware.org/isinfo.php) (miễn phí).
- **Output:** `MonoFXSuite_Setup.exe` (hoặc tên tương tự) — cài toolkit vào thư mục do user chọn.
- **Nội dung cài:** apps, core, tools, **packages**, **toolbar**, docs. Sau khi cài, installer tự set biến môi trường user `HOUDINI_PACKAGE_DIR` = `{app}\packages` để Houdini load MonoFX package (và toolbar tab **MonoFX**). Mở lại Houdini để áp dụng.
- **Folder riêng MonoFX (giống modeler):** Installer tạo `Documents\houdiniXX.X\monofx\` chứa `config\Icons\` và `toolbar\MonoFX.shelf`, rồi ghi `packages\monofx_shelf.json` (hpath = `$HOUDINI_USER_PREF_DIR/monofx`) để Houdini load shelf và icon từ folder này. Tab **MonoFX** có Scene Info, Split Geometry, Search & Replace, Auto Material.
- **Phát hiện Houdini:** Installer đọc registry `HKLM\SOFTWARE\Side Effects Software\Houdini` (các subkey = phiên bản) và hiển thị trên trang **Finished** (chỉ thông tin; không cài theo từng version — mọi Houdini dùng chung `HOUDINI_PACKAGE_DIR`).

## Vị trí script và cách build

- Script Inno: `build/installer/MonoFXSuite.iss`
- **Tự build bằng script (khuyến nghị):**
  - **PowerShell** (từ thư mục gốc project): `.\build\build.ps1` — đọc version từ file `VERSION` ở repo root và truyền vào installer.
- **Batch** (từ thư mục gốc): `build\build.bat` — dùng version mặc định trong `.iss`.
- Build tay: mở file `.iss` trong Inno Setup, hoặc dòng lệnh:
  ```text
  "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" build\installer\MonoFXSuite.iss
  ```
- Output: `build/output/MonoFXSuite_Setup.exe`

## Version và publish release

- **VERSION**: Một dòng (vd. `0.1.0`) ở repo root. `build.ps1` dùng nó làm AppVersion trong installer.
- **Publish lên GitHub**: Sau khi build, commit, tag và push, chạy `.\publish_release.ps1` (cần [GitHub CLI](https://cli.github.com/) và `gh auth login`). Script tạo release từ tag, lấy notes từ `docs/changelog.md`, đính kèm file `.exe`.

## Lưu ý khi build

1. **Đường dẫn:** Installer nên cho user chọn thư mục (vd. `C:\Pipeline\MonoFXSuite` hoặc next to DCC).
2. **Environment / PATH:** Nếu cần, có thể thêm bước “Add to PYTHONPATH” hoặc ghi path vào config DCC (tùy pipeline).
3. **Offline:** Toolkit chạy offline; installer không bắt buộc phải có mạng.
4. **Updater:** Nếu cài từ installer (copy files, không clone git), tính năng “Update from GitHub” trong core cần có Git + folder là git repo — có thể ghi chú trong docs hoặc cung cấp bản “portable zip” cho ai muốn dùng updater.

## Trạng thái

- [x] Script Inno tại `build/installer/MonoFXSuite.iss` (package dir, toolbar, HOUDINI_PACKAGE_DIR, phát hiện Houdini).
- [x] Version từ file `VERSION`; script `publish_release.ps1` để tạo GitHub Release.
- [ ] Test cài trên máy sạch.
