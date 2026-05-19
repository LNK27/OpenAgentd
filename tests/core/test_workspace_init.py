from __future__ import annotations

from pathlib import Path

from app.cli.seed import SeedResult
from app.cli.seed import _install_from_local
from app.cli.seed import _replace_placeholder_if_needed
from app.core.workspace_init import ensure_workspace_initialized


def test_ensure_workspace_initialized_creates_roots_and_seeds(
    monkeypatch,
    tmp_path: Path,
) -> None:
    import app.core.workspace_init as workspace_init

    config = tmp_path / "config"
    called: list[tuple[Path, str]] = []

    monkeypatch.setattr(
        workspace_init.settings, "OPENAGENTD_DATA_DIR", str(tmp_path / "data")
    )
    monkeypatch.setattr(workspace_init.settings, "OPENAGENTD_CONFIG_DIR", str(config))
    monkeypatch.setattr(
        workspace_init.settings, "OPENAGENTD_STATE_DIR", str(tmp_path / "state")
    )
    monkeypatch.setattr(
        workspace_init.settings, "OPENAGENTD_CACHE_DIR", str(tmp_path / "cache")
    )
    monkeypatch.setattr(
        workspace_init.settings, "OPENAGENTD_WORKSPACE_DIR", str(tmp_path / "workspace")
    )
    monkeypatch.setattr(
        workspace_init.settings, "OPENAGENTD_WIKI_DIR", str(tmp_path / "wiki")
    )
    monkeypatch.setattr(workspace_init.settings, "AGENTS_DIR", str(config / "agents"))
    monkeypatch.setattr(workspace_init.settings, "SKILLS_DIR", str(config / "skills"))
    monkeypatch.setattr(
        workspace_init.settings, "OPENAGENTD_PLUGINS_DIRS", str(config / "plugins")
    )

    def install_seed(config_dir: Path, *, provider_model: str) -> SeedResult:
        called.append((config_dir, provider_model))
        (config_dir / "agents").mkdir(parents=True, exist_ok=True)
        (config_dir / "agents" / "openagentd.md").write_text(
            "---\nmodel: __PROVIDER_MODEL__\n---\n"
        )
        return SeedResult(["openagentd.md"], [], [], "test")

    monkeypatch.setattr("app.cli.seed.install_seed", install_seed)

    ensure_workspace_initialized()

    assert (config / "agents").is_dir()
    assert (config / "skills").is_dir()
    assert (config / "plugins").is_dir()
    assert (tmp_path / "cache").is_dir()
    assert called == [(config, "__PROVIDER_MODEL__")]


def test_ensure_workspace_initialized_skips_seed_when_agents_exist(
    monkeypatch,
    tmp_path: Path,
) -> None:
    import app.core.workspace_init as workspace_init

    config = tmp_path / "config"
    agents = config / "agents"
    agents.mkdir(parents=True)
    (agents / "existing.md").write_text("---\nmodel: openai:gpt-5\n---\n")

    monkeypatch.setattr(
        workspace_init.settings, "OPENAGENTD_DATA_DIR", str(tmp_path / "data")
    )
    monkeypatch.setattr(workspace_init.settings, "OPENAGENTD_CONFIG_DIR", str(config))
    monkeypatch.setattr(
        workspace_init.settings, "OPENAGENTD_STATE_DIR", str(tmp_path / "state")
    )
    monkeypatch.setattr(
        workspace_init.settings, "OPENAGENTD_CACHE_DIR", str(tmp_path / "cache")
    )
    monkeypatch.setattr(
        workspace_init.settings, "OPENAGENTD_WORKSPACE_DIR", str(tmp_path / "workspace")
    )
    monkeypatch.setattr(
        workspace_init.settings, "OPENAGENTD_WIKI_DIR", str(tmp_path / "wiki")
    )
    monkeypatch.setattr(workspace_init.settings, "AGENTS_DIR", str(agents))
    monkeypatch.setattr(workspace_init.settings, "SKILLS_DIR", str(config / "skills"))
    monkeypatch.setattr(
        workspace_init.settings, "OPENAGENTD_PLUGINS_DIRS", str(config / "plugins")
    )
    monkeypatch.setattr(
        "app.cli.seed.install_seed",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("unexpected seed")
        ),
    )

    ensure_workspace_initialized()

    assert (config / "plugins").is_dir()


def test_replace_placeholder_updates_only_seed_model(tmp_path: Path) -> None:
    agent = tmp_path / "agent.md"
    agent.write_text(
        "---\nname: openagentd\nmodel: __PROVIDER_MODEL__\n---\n\nCustom prompt\n",
        encoding="utf-8",
    )

    changed = _replace_placeholder_if_needed(agent, "codex:gpt-5.5")

    assert changed is True
    assert agent.read_text(encoding="utf-8") == (
        "---\nname: openagentd\nmodel: codex:gpt-5.5\n---\n\nCustom prompt\n"
    )


def test_install_seed_writes_runtime_settings_model(tmp_path: Path) -> None:
    seed = tmp_path / "seed"
    seed.mkdir()
    (seed / "agents").mkdir()
    (seed / "skills").mkdir()

    result = _install_from_local(
        seed,
        tmp_path / "config",
        provider_model="codex:gpt-5.5",
    )

    assert result.configs_written == [
        "multimodal.yaml",
        "settings.yaml",
        "speech.yaml",
    ]
    settings = (tmp_path / "config" / "settings.yaml").read_text(encoding="utf-8")
    assert "title_generation:" in settings
    assert "dream:" in settings
    assert "model: codex:gpt-5.5" in settings
