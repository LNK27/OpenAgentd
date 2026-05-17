from __future__ import annotations

import importlib.util
import json
from pathlib import Path


def _load_manifest_module():
    path = Path(__file__).resolve().parents[2] / "scripts" / "make_updater_manifest.py"
    spec = importlib.util.spec_from_file_location("make_updater_manifest", path)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_default_manifest_urls_point_at_shared_release_tag(tmp_path, monkeypatch):
    module = _load_manifest_module()
    artefact_dir = tmp_path / "artefacts"
    artefact_dir.mkdir()
    (artefact_dir / "OpenAgentd_1.2.0_aarch64.dmg").write_text("dmg")
    out = tmp_path / "latest.json"

    monkeypatch.setattr(
        "sys.argv",
        [
            "make_updater_manifest.py",
            "--version",
            "1.2.0",
            "--artefact-dir",
            str(artefact_dir),
            "--out",
            str(out),
        ],
    )
    monkeypatch.setenv("GITHUB_REPOSITORY", "lthoangg/OpenAgentd")

    assert module.main() == 0

    manifest = json.loads(out.read_text())
    assert manifest["platforms"]["darwin-aarch64"]["url"] == (
        "https://github.com/lthoangg/OpenAgentd/releases/download/"
        "v1.2.0/OpenAgentd_1.2.0_aarch64.dmg"
    )
