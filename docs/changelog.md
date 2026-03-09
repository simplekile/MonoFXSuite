# Changelog

## [Unreleased]


## [0.1.3] - 2026-03-09

### Installer & MonoStudio integration
- Installer: add **Install location** page â€” Option A (under MonoStudio), Option B (user folder), Option C (standalone). Enables MonoStudio Settings â†’ Updates to detect version and offer Download.
- Installer: include **VERSION** file in app root so MonoStudio can read installed version.
- Docs: `docs/plans/monostudio_extra_tool_feasibility.md` â€” checklist and implementation notes.


## [0.1.2] - 2026-03-07

### Changes
- (describe changes)


## [0.1.1] - 2026-03-07

### Changes
- (describe changes)


## [0.1.0] ÃƒÂ¢Ã¢â€šÂ¬Ã¢â‚¬Â 2025-03-07

### Installer & setup
- Installer tÃƒÂ¡Ã‚ÂºÃ‚Â¡o folder riÃƒÆ’Ã‚Âªng `monofx` trong user Houdini (giÃƒÂ¡Ã‚Â»Ã¢â‚¬Ëœng modeler): `Documents\houdiniXX.X\monofx\` vÃƒÂ¡Ã‚Â»Ã¢â‚¬Âºi `config\Icons\`, `toolbar\MonoFX.shelf`; ghi `packages\monofx_shelf.json` (hpath = `$HOUDINI_USER_PREF_DIR/monofx`).
- ThÃƒÆ’Ã‚Âªm script build: `build/build.ps1`, `build/build.bat` ÃƒÂ¢Ã¢â€šÂ¬Ã¢â‚¬Â chÃƒÂ¡Ã‚ÂºÃ‚Â¡y tÃƒÂ¡Ã‚Â»Ã‚Â« thÃƒâ€ Ã‚Â° mÃƒÂ¡Ã‚Â»Ã‚Â¥c gÃƒÂ¡Ã‚Â»Ã¢â‚¬Ëœc: `.\build\build.ps1` hoÃƒÂ¡Ã‚ÂºÃ‚Â·c `build\build.bat`.
- Output installer: `build/output/MonoFXSuite_Setup.exe` (khÃƒÆ’Ã‚Â´ng version trong tÃƒÆ’Ã‚Âªn file).

### Shelf icons
- Icon shelf cÃƒÆ’Ã‚Â³ nÃƒÂ¡Ã‚Â»Ã‚Ân bo trÃƒÆ’Ã‚Â²n, mÃƒÆ’Ã‚Â u nÃƒÂ¡Ã‚Â»Ã‚Ân khÃƒÆ’Ã‚Â¡c nhau tÃƒÂ¡Ã‚Â»Ã‚Â«ng tool (info: xanh dÃƒâ€ Ã‚Â°Ãƒâ€ Ã‚Â¡ng, layers: xanh lÃƒÆ’Ã‚Â¡, replace: cam, palette: tÃƒÆ’Ã‚Â­m).
- Icon mÃƒÆ’Ã‚Â u trÃƒÂ¡Ã‚ÂºÃ‚Â¯ng, scale 0.65, nÃƒÂ¡Ã‚Â»Ã‚Ân full 24ÃƒÆ’Ã¢â‚¬â€24 ÃƒÂ¢Ã¢â€šÂ¬Ã¢â‚¬Â nÃƒÂ¡Ã‚Â»Ã‚Ân to hÃƒâ€ Ã‚Â¡n icon.
- CÃƒÂ¡Ã‚ÂºÃ‚Â­p nhÃƒÂ¡Ã‚ÂºÃ‚Â­t cÃƒÂ¡Ã‚ÂºÃ‚Â£ `config/Icons/` vÃƒÆ’Ã‚Â  `toolbar/icons/` (Lucide-based SVG).

### Docs
- `docs/setup/inno_build.md`: hÃƒâ€ Ã‚Â°ÃƒÂ¡Ã‚Â»Ã¢â‚¬Âºng dÃƒÂ¡Ã‚ÂºÃ‚Â«n build bÃƒÂ¡Ã‚ÂºÃ‚Â±ng script.
- `docs/setup/modeler_structure_reference.md`: tham khÃƒÂ¡Ã‚ÂºÃ‚Â£o cÃƒÂ¡Ã‚ÂºÃ‚Â¥u trÃƒÆ’Ã‚Âºc plugin modeler.
- `docs/setup/monofx_user_prefs_example.json`: mÃƒÂ¡Ã‚ÂºÃ‚Â«u package cÃƒÆ’Ã‚Â i kiÃƒÂ¡Ã‚Â»Ã†â€™u user prefs.
- `docs/setup/houdini_setup.md`: cÃƒÂ¡Ã‚ÂºÃ‚Â­p nhÃƒÂ¡Ã‚ÂºÃ‚Â­t mÃƒÆ’Ã‚Â´ tÃƒÂ¡Ã‚ÂºÃ‚Â£ folder monofx vÃƒÆ’Ã‚Â  monofx_shelf.json.