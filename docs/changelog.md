# Changelog

## [Unreleased]


## [0.1.1] - 2026-03-07

### Changes
- (describe changes)


## [0.1.0] â€” 2025-03-07

### Installer & setup
- Installer táº¡o folder riÃªng `monofx` trong user Houdini (giá»‘ng modeler): `Documents\houdiniXX.X\monofx\` vá»›i `config\Icons\`, `toolbar\MonoFX.shelf`; ghi `packages\monofx_shelf.json` (hpath = `$HOUDINI_USER_PREF_DIR/monofx`).
- ThÃªm script build: `build/build.ps1`, `build/build.bat` â€” cháº¡y tá»« thÆ° má»¥c gá»‘c: `.\build\build.ps1` hoáº·c `build\build.bat`.
- Output installer: `build/output/MonoFXSuite_Setup.exe` (khÃ´ng version trong tÃªn file).

### Shelf icons
- Icon shelf cÃ³ ná»n bo trÃ²n, mÃ u ná»n khÃ¡c nhau tá»«ng tool (info: xanh dÆ°Æ¡ng, layers: xanh lÃ¡, replace: cam, palette: tÃ­m).
- Icon mÃ u tráº¯ng, scale 0.65, ná»n full 24Ã—24 â€” ná»n to hÆ¡n icon.
- Cáº­p nháº­t cáº£ `config/Icons/` vÃ  `toolbar/icons/` (Lucide-based SVG).

### Docs
- `docs/setup/inno_build.md`: hÆ°á»›ng dáº«n build báº±ng script.
- `docs/setup/modeler_structure_reference.md`: tham kháº£o cáº¥u trÃºc plugin modeler.
- `docs/setup/monofx_user_prefs_example.json`: máº«u package cÃ i kiá»ƒu user prefs.
- `docs/setup/houdini_setup.md`: cáº­p nháº­t mÃ´ táº£ folder monofx vÃ  monofx_shelf.json.