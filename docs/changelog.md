# Changelog

## [Unreleased]


## [0.1.4] - 2026-03-09

### Installer
- Option A (Under MonoStudio): read `%LOCALAPPDATA%\MonoStudio\install_path.txt`; if valid, pre-fill `{path}\tools\MonoFXSuite`, else `{pf}\MonoStudio26\tools\MonoFXSuite`.


## [0.1.3] - 2026-03-09

### Installer & MonoStudio integration
- Installer: add **Install location** page Ã¢â‚¬â€ Option A (under MonoStudio), Option B (user folder), Option C (standalone). Enables MonoStudio Settings Ã¢â€ â€™ Updates to detect version and offer Download.
- Installer: include **VERSION** file in app root so MonoStudio can read installed version.
- Docs: `docs/plans/monostudio_extra_tool_feasibility.md` Ã¢â‚¬â€ checklist and implementation notes.


## [0.1.2] - 2026-03-07

### Changes
- (describe changes)


## [0.1.1] - 2026-03-07

### Changes
- (describe changes)


## [0.1.0] ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÂ¢Ã¢â€šÂ¬Ã‚Â 2025-03-07

### Installer & setup
- Installer tÃƒÆ’Ã‚Â¡Ãƒâ€šÃ‚ÂºÃƒâ€šÃ‚Â¡o folder riÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Âªng `monofx` trong user Houdini (giÃƒÆ’Ã‚Â¡Ãƒâ€šÃ‚Â»ÃƒÂ¢Ã¢â€šÂ¬Ã‹Å“ng modeler): `Documents\houdiniXX.X\monofx\` vÃƒÆ’Ã‚Â¡Ãƒâ€šÃ‚Â»ÃƒÂ¢Ã¢â€šÂ¬Ã‚Âºi `config\Icons\`, `toolbar\MonoFX.shelf`; ghi `packages\monofx_shelf.json` (hpath = `$HOUDINI_USER_PREF_DIR/monofx`).
- ThÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Âªm script build: `build/build.ps1`, `build/build.bat` ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÂ¢Ã¢â€šÂ¬Ã‚Â chÃƒÆ’Ã‚Â¡Ãƒâ€šÃ‚ÂºÃƒâ€šÃ‚Â¡y tÃƒÆ’Ã‚Â¡Ãƒâ€šÃ‚Â»Ãƒâ€šÃ‚Â« thÃƒÆ’Ã¢â‚¬Â Ãƒâ€šÃ‚Â° mÃƒÆ’Ã‚Â¡Ãƒâ€šÃ‚Â»Ãƒâ€šÃ‚Â¥c gÃƒÆ’Ã‚Â¡Ãƒâ€šÃ‚Â»ÃƒÂ¢Ã¢â€šÂ¬Ã‹Å“c: `.\build\build.ps1` hoÃƒÆ’Ã‚Â¡Ãƒâ€šÃ‚ÂºÃƒâ€šÃ‚Â·c `build\build.bat`.
- Output installer: `build/output/MonoFXSuite_Setup.exe` (khÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â´ng version trong tÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Âªn file).

### Shelf icons
- Icon shelf cÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â³ nÃƒÆ’Ã‚Â¡Ãƒâ€šÃ‚Â»Ãƒâ€šÃ‚Ân bo trÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â²n, mÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â u nÃƒÆ’Ã‚Â¡Ãƒâ€šÃ‚Â»Ãƒâ€šÃ‚Ân khÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¡c nhau tÃƒÆ’Ã‚Â¡Ãƒâ€šÃ‚Â»Ãƒâ€šÃ‚Â«ng tool (info: xanh dÃƒÆ’Ã¢â‚¬Â Ãƒâ€šÃ‚Â°ÃƒÆ’Ã¢â‚¬Â Ãƒâ€šÃ‚Â¡ng, layers: xanh lÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¡, replace: cam, palette: tÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â­m).
- Icon mÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â u trÃƒÆ’Ã‚Â¡Ãƒâ€šÃ‚ÂºÃƒâ€šÃ‚Â¯ng, scale 0.65, nÃƒÆ’Ã‚Â¡Ãƒâ€šÃ‚Â»Ãƒâ€šÃ‚Ân full 24ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã¢â‚¬Â24 ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÂ¢Ã¢â€šÂ¬Ã‚Â nÃƒÆ’Ã‚Â¡Ãƒâ€šÃ‚Â»Ãƒâ€šÃ‚Ân to hÃƒÆ’Ã¢â‚¬Â Ãƒâ€šÃ‚Â¡n icon.
- CÃƒÆ’Ã‚Â¡Ãƒâ€šÃ‚ÂºÃƒâ€šÃ‚Â­p nhÃƒÆ’Ã‚Â¡Ãƒâ€šÃ‚ÂºÃƒâ€šÃ‚Â­t cÃƒÆ’Ã‚Â¡Ãƒâ€šÃ‚ÂºÃƒâ€šÃ‚Â£ `config/Icons/` vÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â  `toolbar/icons/` (Lucide-based SVG).

### Docs
- `docs/setup/inno_build.md`: hÃƒÆ’Ã¢â‚¬Â Ãƒâ€šÃ‚Â°ÃƒÆ’Ã‚Â¡Ãƒâ€šÃ‚Â»ÃƒÂ¢Ã¢â€šÂ¬Ã‚Âºng dÃƒÆ’Ã‚Â¡Ãƒâ€šÃ‚ÂºÃƒâ€šÃ‚Â«n build bÃƒÆ’Ã‚Â¡Ãƒâ€šÃ‚ÂºÃƒâ€šÃ‚Â±ng script.
- `docs/setup/modeler_structure_reference.md`: tham khÃƒÆ’Ã‚Â¡Ãƒâ€šÃ‚ÂºÃƒâ€šÃ‚Â£o cÃƒÆ’Ã‚Â¡Ãƒâ€šÃ‚ÂºÃƒâ€šÃ‚Â¥u trÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Âºc plugin modeler.
- `docs/setup/monofx_user_prefs_example.json`: mÃƒÆ’Ã‚Â¡Ãƒâ€šÃ‚ÂºÃƒâ€šÃ‚Â«u package cÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â i kiÃƒÆ’Ã‚Â¡Ãƒâ€šÃ‚Â»Ãƒâ€ Ã¢â‚¬â„¢u user prefs.
- `docs/setup/houdini_setup.md`: cÃƒÆ’Ã‚Â¡Ãƒâ€šÃ‚ÂºÃƒâ€šÃ‚Â­p nhÃƒÆ’Ã‚Â¡Ãƒâ€šÃ‚ÂºÃƒâ€šÃ‚Â­t mÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â´ tÃƒÆ’Ã‚Â¡Ãƒâ€šÃ‚ÂºÃƒâ€šÃ‚Â£ folder monofx vÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â  monofx_shelf.json.