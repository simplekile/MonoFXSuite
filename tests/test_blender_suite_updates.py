"""The Blender add-on's update check, without bpy: the suite's version against the latest release, which carries
only MonoFXSuite_Setup.exe (the add-on ZIP is no longer published; bl_info's version never moved, so Blender always
said up to date)."""

from __future__ import annotations

import importlib.util
from pathlib import Path

SUITE = Path(__file__).resolve().parents[1]


def _mod():
    path = SUITE / "tools/fx/monofx_pipeline_blender/monofx_pipeline_blender/suite_updates.py"
    spec = importlib.util.spec_from_file_location("suite_updates", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_versions_and_compare():
    su = _mod()
    assert su.parse_version("v0.1.37") == (0, 1, 37) and su.parse_version("0.1.38\n") == (0, 1, 38)
    assert su.parse_version("latest") is None
    assert su.compare((0, 1, 37), (0, 1, 38)) == "update"
    assert su.compare((0, 1, 38), (0, 1, 38)) == "current"
    assert su.compare((0, 1, 39), (0, 1, 38)) == "ahead"
    assert su.compare(None, (0, 1, 38)) == "unknown"  # copied by hand: the Setup makes it known


def test_installed_version_from_the_stamp_then_monos(tmp_path):
    su = _mod()
    pkg = tmp_path / "addons" / "monofx_pipeline_blender"
    pkg.mkdir(parents=True)
    appdata = tmp_path / "local"
    monos = appdata / "Monos" / "tools" / "MonoFXSuite"
    monos.mkdir(parents=True)
    (monos / "VERSION").write_text("0.1.36", encoding="utf-8")
    files = su.version_files(pkg, str(appdata))
    assert su.installed_suite_version(files) == (0, 1, 36)  # no stamp: the installer's VERSION for Monos
    (pkg / su.SUITE_VERSION_FILE).write_text("0.1.37", encoding="utf-8")
    assert su.installed_suite_version(files) == (0, 1, 37)  # the add-on's own stamp first
    assert su.installed_suite_version(su.version_files(tmp_path / "nowhere", "")) is None


def test_the_release_offers_the_setup():
    su = _mod()
    assets = [{"name": "notes.txt"}, {"name": "MonoFXSuite_Setup.exe", "browser_download_url": "https://x/s.exe"}]
    assert su.pick_setup_asset(assets)["browser_download_url"] == "https://x/s.exe"
    assert su.pick_setup_asset([{"name": "monofx_pipeline_blender_v09146.zip"}]) is None


def test_release_scripts_publish_the_installer_only():
    for name in ("publish_release.ps1", "release.ps1"):
        text = (SUITE / name).read_text(encoding="utf-8")
        assert "monofx_pipeline_blender_v" not in text, name
    build = (SUITE / "build/build.ps1").read_text(encoding="utf-8")
    assert "SUITE_VERSION" in build
