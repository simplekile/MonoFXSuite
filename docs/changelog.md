# Changelog

## [Unreleased]


## [0.1.2] - 2026-03-07

### Changes
- (describe changes)


## [0.1.1] - 2026-03-07

### Changes
- (describe changes)


## [0.1.0] Ã¢â‚¬â€ 2025-03-07

### Installer & setup
- Installer tÃ¡ÂºÂ¡o folder riÃƒÂªng `monofx` trong user Houdini (giÃ¡Â»â€˜ng modeler): `Documents\houdiniXX.X\monofx\` vÃ¡Â»â€ºi `config\Icons\`, `toolbar\MonoFX.shelf`; ghi `packages\monofx_shelf.json` (hpath = `$HOUDINI_USER_PREF_DIR/monofx`).
- ThÃƒÂªm script build: `build/build.ps1`, `build/build.bat` Ã¢â‚¬â€ chÃ¡ÂºÂ¡y tÃ¡Â»Â« thÃ†Â° mÃ¡Â»Â¥c gÃ¡Â»â€˜c: `.\build\build.ps1` hoÃ¡ÂºÂ·c `build\build.bat`.
- Output installer: `build/output/MonoFXSuite_Setup.exe` (khÃƒÂ´ng version trong tÃƒÂªn file).

### Shelf icons
- Icon shelf cÃƒÂ³ nÃ¡Â»Ân bo trÃƒÂ²n, mÃƒÂ u nÃ¡Â»Ân khÃƒÂ¡c nhau tÃ¡Â»Â«ng tool (info: xanh dÃ†Â°Ã†Â¡ng, layers: xanh lÃƒÂ¡, replace: cam, palette: tÃƒÂ­m).
- Icon mÃƒÂ u trÃ¡ÂºÂ¯ng, scale 0.65, nÃ¡Â»Ân full 24Ãƒâ€”24 Ã¢â‚¬â€ nÃ¡Â»Ân to hÃ†Â¡n icon.
- CÃ¡ÂºÂ­p nhÃ¡ÂºÂ­t cÃ¡ÂºÂ£ `config/Icons/` vÃƒÂ  `toolbar/icons/` (Lucide-based SVG).

### Docs
- `docs/setup/inno_build.md`: hÃ†Â°Ã¡Â»â€ºng dÃ¡ÂºÂ«n build bÃ¡ÂºÂ±ng script.
- `docs/setup/modeler_structure_reference.md`: tham khÃ¡ÂºÂ£o cÃ¡ÂºÂ¥u trÃƒÂºc plugin modeler.
- `docs/setup/monofx_user_prefs_example.json`: mÃ¡ÂºÂ«u package cÃƒÂ i kiÃ¡Â»Æ’u user prefs.
- `docs/setup/houdini_setup.md`: cÃ¡ÂºÂ­p nhÃ¡ÂºÂ­t mÃƒÂ´ tÃ¡ÂºÂ£ folder monofx vÃƒÂ  monofx_shelf.json.