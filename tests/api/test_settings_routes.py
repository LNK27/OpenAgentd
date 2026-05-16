"""Tests for app/api/routes/settings.py — sandbox deny-list endpoints."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import Mock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.agent.sandbox_config import DEFAULT_DENIED_PATTERNS
from app.cli.seed import SeedDownloadError, SeedResult
from app.api.routes import settings as settings_routes
from app.api.routes.settings import router


def _make_app() -> FastAPI:
    app = FastAPI()
    app.include_router(router, prefix="/api/settings")
    return app


@pytest.fixture
def isolated_config(tmp_path: Path):
    """Point load_config / save_config at a tmp ``sandbox.yaml``."""
    target = tmp_path / "sandbox.yaml"
    with patch("app.agent.sandbox_config.config_path", return_value=target):
        yield target


def test_get_sandbox_returns_seed_defaults_when_file_missing(
    isolated_config: Path,
) -> None:
    client = TestClient(_make_app())
    response = client.get("/api/settings/sandbox")
    assert response.status_code == 200
    assert response.json() == {"denied_patterns": list(DEFAULT_DENIED_PATTERNS)}
    # GET must not write the file.
    assert not isolated_config.exists()


def test_put_sandbox_persists_patterns(isolated_config: Path) -> None:
    client = TestClient(_make_app())
    body = {"denied_patterns": ["**/.env", "**/secrets/**"]}
    response = client.put("/api/settings/sandbox", json=body)
    assert response.status_code == 200
    assert response.json() == body
    assert isolated_config.exists()

    # Round-trip — GET reflects what was saved.
    again = client.get("/api/settings/sandbox")
    assert again.json() == body


def test_put_sandbox_strips_blank_patterns(isolated_config: Path) -> None:
    client = TestClient(_make_app())
    response = client.put(
        "/api/settings/sandbox",
        json={"denied_patterns": ["**/.env", "", "   ", "bar/*"]},
    )
    assert response.status_code == 200
    assert response.json() == {"denied_patterns": ["**/.env", "bar/*"]}


def test_put_sandbox_rejects_unknown_field(isolated_config: Path) -> None:
    client = TestClient(_make_app())
    response = client.put(
        "/api/settings/sandbox",
        json={"denied_patterns": [], "extra_field": "nope"},
    )
    assert response.status_code == 422


# ── Updates removed ─────────────────────────────────────────────────────────
#
# The PyPI-backed self-update endpoints were removed when the desktop bundle
# switched to ``tauri-plugin-updater`` and CLI users were pointed at
# ``openagentd update`` directly. These tests guard against an accidental
# revert that would re-expose the in-process restart shell script.


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("GET", "/api/settings/update"),
        ("POST", "/api/settings/update/install"),
        # Variants that would exist if someone restored the old code under
        # a slightly different shape — catch the obvious near-misses too.
        ("GET", "/api/settings/updates"),
        ("POST", "/api/settings/updates/install"),
    ],
)
def test_update_endpoints_removed(method: str, path: str) -> None:
    client = TestClient(_make_app())
    response = client.request(method, path)
    assert response.status_code == 404, (
        f"{method} {path} should not exist; got {response.status_code}. "
        "Desktop uses tauri-plugin-updater; CLI uses `openagentd update`."
    )


def test_settings_router_has_no_update_routes() -> None:
    """Inspect registered routes directly so route names also can't drift back."""
    from app.api.routes.settings import router as settings_router

    for route in settings_router.routes:
        path = getattr(route, "path", "")
        assert "update" not in path.lower(), (
            f"Settings router exposes an update-related path: {path}"
        )


def test_update_install_helpers_not_importable() -> None:
    """The shell-spawning restart helpers must not silently come back."""
    from app.api.routes import settings as settings_routes

    for symbol in (
        "_self_terminate_after_response",
        "_install_blocked_reason",
        "_version_key",
        "_PYPI_JSON_URL",
        "install_update",
        "get_update_status",
    ):
        assert not hasattr(settings_routes, symbol), (
            f"`{symbol}` was reintroduced; that path is no longer supported."
        )


# ── Providers (Settings → Providers tab) ────────────────────────────────────


def test_list_providers_returns_catalog(monkeypatch: pytest.MonkeyPatch) -> None:
    """GET /providers returns one entry per catalog row with config state."""
    # Clear any ambient env so the test is deterministic.
    for name in ("GOOGLE_API_KEY", "OPENAI_API_KEY", "OPENROUTER_API_KEY"):
        monkeypatch.delenv(name, raising=False)

    app = _make_app()
    client = TestClient(app)
    response = client.get("/api/settings/providers")
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data["providers"], list)
    assert len(data["providers"]) > 5  # we ship many
    ids = {p["id"] for p in data["providers"]}
    assert {"googlegenai", "openai", "openrouter", "copilot", "codex"} <= ids
    # Nothing in the env → no provider should be flagged as configured.
    assert data["has_any_configured"] is False or any(
        p["kind"] == "local" and p["is_configured"] for p in data["providers"]
    )


def test_list_providers_marks_configured_when_env_var_set(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An env var with a value flips is_configured to True."""
    monkeypatch.setenv("GOOGLE_API_KEY", "test-key-not-real")

    app = _make_app()
    client = TestClient(app)
    response = client.get("/api/settings/providers")
    assert response.status_code == 200
    data = response.json()
    google = next(p for p in data["providers"] if p["id"] == "googlegenai")
    assert google["is_configured"] is True
    assert data["has_any_configured"] is True


def test_list_providers_marks_oauth_file_configured(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """OAuth providers persist token files directly under CACHE_DIR."""
    monkeypatch.setattr(settings_routes.settings, "OPENAGENTD_CACHE_DIR", str(tmp_path))
    (tmp_path / "codex_oauth.json").write_text("{}", encoding="utf-8")

    app = _make_app()
    client = TestClient(app)
    response = client.get("/api/settings/providers")

    assert response.status_code == 200
    data = response.json()
    codex = next(p for p in data["providers"] if p["id"] == "codex")
    copilot = next(p for p in data["providers"] if p["id"] == "copilot")
    assert codex["is_configured"] is True
    assert copilot["is_configured"] is False


def test_test_provider_returns_404_for_unknown(monkeypatch: pytest.MonkeyPatch) -> None:
    app = _make_app()
    client = TestClient(app)
    response = client.post(
        "/api/settings/providers/notreal/test",
        json={"api_key": "x", "model": "y"},
    )
    assert response.status_code == 404


def test_test_provider_reports_failure_without_crashing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Provider chat error → 200 OK with ok=False rather than 500.

    The test endpoint catches every exception so the UI never has to
    distinguish "the test API itself broke" from "your key is wrong."
    """

    # Force a deterministic failure by stubbing build_provider — real
    # provider chat() behaviour varies by SDK version and would make this
    # test flaky against the live network.
    def _explode(*_args: object, **_kwargs: object) -> None:
        raise ValueError("synthetic auth failure")

    monkeypatch.setattr(settings_routes, "build_provider", None, raising=False)
    monkeypatch.setattr(
        "app.agent.providers.factory.build_provider", _explode, raising=True
    )

    app = _make_app()
    client = TestClient(app)
    response = client.post(
        "/api/settings/providers/googlegenai/test",
        json={"api_key": "ignored-because-stub", "model": "gemini-3-flash-preview"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is False
    assert "synthetic auth failure" in (body["error"] or "")


def test_save_provider_writes_env_and_mutates_environ(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """PUT /providers/{id} persists creds and mirrors them into os.environ."""
    # Redirect CONFIG_DIR to a temp dir so the test doesn't touch real config.
    monkeypatch.setattr(
        settings_routes.settings, "OPENAGENTD_CONFIG_DIR", str(tmp_path)
    )
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)

    app = _make_app()
    client = TestClient(app)
    response = client.put(
        "/api/settings/providers/googlegenai",
        json={"api_key": "fresh-key-123", "default_model": "gemini-3-flash-preview"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["saved"] is True
    assert body["is_first_provider"] is True

    # .env should now contain the key.
    env_text = (tmp_path / ".env").read_text(encoding="utf-8")
    assert "GOOGLE_API_KEY=fresh-key-123" in env_text

    # os.environ should be mutated so the next build_provider call works
    # without restarting the server.
    import os

    assert os.environ.get("GOOGLE_API_KEY") == "fresh-key-123"

    # A second save flips is_first_provider to False — the user is past
    # the initial setup so the frontend shouldn't trigger seed install
    # again.
    response2 = client.put(
        "/api/settings/providers/googlegenai",
        json={"api_key": "another-key", "default_model": "gemini-3-flash-preview"},
    )
    assert response2.status_code == 200
    assert response2.json()["is_first_provider"] is False


def test_save_provider_404_for_unknown(monkeypatch: pytest.MonkeyPatch) -> None:
    app = _make_app()
    client = TestClient(app)
    response = client.put(
        "/api/settings/providers/notreal",
        json={"api_key": "x"},
    )
    assert response.status_code == 404


def test_install_seed_defaults_calls_seed_installer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        settings_routes.settings, "OPENAGENTD_CONFIG_DIR", str(tmp_path)
    )
    install_seed = Mock(
        return_value=SeedResult(
            agents_written=["openagentd.md"],
            skills_written=["self-healing"],
            configs_written=["mcp.json"],
            source="local",
        )
    )
    monkeypatch.setattr("app.cli.seed.install_seed", install_seed)

    app = _make_app()
    client = TestClient(app)
    response = client.post(
        "/api/settings/seed",
        json={"provider_model": "googlegenai:gemini-3-flash-preview"},
    )

    assert response.status_code == 200
    assert response.json() == {
        "agents_written": ["openagentd.md"],
        "skills_written": ["self-healing"],
        "configs_written": ["mcp.json"],
        "source": "local",
    }
    install_seed.assert_called_once_with(
        tmp_path, provider_model="googlegenai:gemini-3-flash-preview"
    )


def test_install_seed_defaults_reports_download_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        settings_routes.settings, "OPENAGENTD_CONFIG_DIR", str(tmp_path)
    )

    def _fail(*_args: object, **_kwargs: object) -> None:
        raise SeedDownloadError("offline")

    monkeypatch.setattr("app.cli.seed.install_seed", _fail)

    app = _make_app()
    client = TestClient(app)
    response = client.post(
        "/api/settings/seed",
        json={"provider_model": "googlegenai:gemini-3-flash-preview"},
    )

    assert response.status_code == 502
    assert response.json()["detail"] == "offline"


def test_install_seed_defaults_rejects_blank_model() -> None:
    app = _make_app()
    client = TestClient(app)
    response = client.post("/api/settings/seed", json={"provider_model": ""})

    assert response.status_code == 422
