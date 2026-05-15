"""Tests for app/api/routes/settings.py — sandbox deny-list endpoints."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import Mock, patch

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from httpx import ASGITransport, AsyncClient

from app.agent.sandbox_config import DEFAULT_DENIED_PATTERNS
from app.cli.seed import SeedDownloadError, SeedResult
from app.api.routes import settings as settings_routes
from app.api.routes.settings import router


def _make_app() -> FastAPI:
    app = FastAPI()
    app.include_router(router, prefix="/api/settings")
    return app


class _FakePyPIResponse:
    def __init__(
        self, payload: dict[str, Any], *, json_error: ValueError | None = None
    ) -> None:
        self._payload = payload
        self._json_error = json_error

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict[str, Any]:
        if self._json_error is not None:
            raise self._json_error
        return self._payload


class _FakeAsyncClient:
    def __init__(
        self,
        *,
        response: _FakePyPIResponse | None = None,
        error: httpx.HTTPError | None = None,
    ) -> None:
        self._response = response
        self._error = error

    async def __aenter__(self) -> _FakeAsyncClient:
        return self

    async def __aexit__(self, *_args: object) -> None:
        return None

    async def get(self, _url: str) -> _FakePyPIResponse:
        if self._error is not None:
            raise self._error
        assert self._response is not None
        return self._response


async def _async_client() -> AsyncClient:
    transport = ASGITransport(app=_make_app())
    return AsyncClient(transport=transport, base_url="http://test")


def _mock_pypi(monkeypatch: pytest.MonkeyPatch, payload: dict[str, Any]) -> None:
    monkeypatch.setattr(
        settings_routes.httpx,
        "AsyncClient",
        lambda timeout: _FakeAsyncClient(response=_FakePyPIResponse(payload)),
    )


def _mock_pypi_invalid_json(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        settings_routes.httpx,
        "AsyncClient",
        lambda timeout: _FakeAsyncClient(
            response=_FakePyPIResponse({}, json_error=ValueError("bad json")),
        ),
    )


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


@pytest.mark.asyncio
async def test_get_update_reports_new_version(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings_routes, "VERSION", "0.1.7")
    monkeypatch.setattr(settings_routes.settings, "APP_ENV", "production")
    monkeypatch.setattr(
        settings_routes.shutil, "which", lambda _name: "/usr/bin/openagentd"
    )
    _mock_pypi(monkeypatch, {"info": {"version": "0.1.8"}})

    async with await _async_client() as client:
        response = await client.get("/api/settings/update")

    assert response.status_code == 200
    assert response.json() == {
        "current_version": "0.1.7",
        "latest_version": "0.1.8",
        "update_available": True,
        "can_install": True,
        "install_blocked_reason": None,
    }


@pytest.mark.asyncio
async def test_get_update_blocks_install_without_executable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings_routes, "VERSION", "0.1.7")
    monkeypatch.setattr(settings_routes.settings, "APP_ENV", "production")
    monkeypatch.setattr(settings_routes.shutil, "which", lambda _name: None)
    _mock_pypi(monkeypatch, {"info": {"version": "0.1.7"}})

    async with await _async_client() as client:
        response = await client.get("/api/settings/update")

    body = response.json()
    assert response.status_code == 200
    assert body["update_available"] is False
    assert body["can_install"] is False
    assert "executable" in body["install_blocked_reason"]


@pytest.mark.asyncio
async def test_get_update_returns_502_when_pypi_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        settings_routes.httpx,
        "AsyncClient",
        lambda timeout: _FakeAsyncClient(error=httpx.ConnectError("offline")),
    )

    async with await _async_client() as client:
        response = await client.get("/api/settings/update")

    assert response.status_code == 502
    assert response.json()["detail"] == "Could not check for updates"


@pytest.mark.asyncio
async def test_get_update_returns_502_for_malformed_pypi_payload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _mock_pypi(monkeypatch, {"info": {"version": ""}})

    async with await _async_client() as client:
        response = await client.get("/api/settings/update")

    assert response.status_code == 502
    assert response.json()["detail"] == "PyPI did not return a package version"


@pytest.mark.asyncio
async def test_get_update_returns_502_for_invalid_pypi_json(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _mock_pypi_invalid_json(monkeypatch)

    async with await _async_client() as client:
        response = await client.get("/api/settings/update")

    assert response.status_code == 502
    assert response.json()["detail"] == "PyPI did not return valid JSON"


@pytest.mark.asyncio
async def test_install_update_blocks_development_mode(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    popen = Mock()
    monkeypatch.setattr(settings_routes.settings, "APP_ENV", "development")
    monkeypatch.setattr(settings_routes.subprocess, "Popen", popen)

    async with await _async_client() as client:
        response = await client.post("/api/settings/update/install")

    assert response.status_code == 409
    assert (
        response.json()["detail"]
        == "Automatic install is only available for the installed app."
    )
    popen.assert_not_called()


@pytest.mark.asyncio
async def test_install_update_starts_background_restart(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    popen = Mock()
    self_terminate = Mock()
    monkeypatch.setattr(settings_routes.settings, "APP_ENV", "production")
    monkeypatch.setattr(
        settings_routes.shutil,
        "which",
        lambda _name: "/usr/local/bin/openagentd",
    )
    monkeypatch.setattr(settings_routes.subprocess, "Popen", popen)
    # Replace the BackgroundTasks callable so the test process is not killed.
    monkeypatch.setattr(
        settings_routes,
        "_self_terminate_after_response",
        self_terminate,
    )

    async with await _async_client() as client:
        response = await client.post("/api/settings/update/install")

    assert response.status_code == 200
    assert response.json() == {"status": "started"}

    # Restarter spawned exactly once.
    popen.assert_called_once()
    args, kwargs = popen.call_args

    # POSIX shell, no login flag — `-lc` would source profile files
    # unnecessarily and slowly on macOS.
    assert args[0][0:2] == ["/bin/sh", "-c"]

    script = args[0][2]
    # Polls for parent exit, then runs update + restart unconditionally
    # (no `&&` short-circuit between update and start).
    assert "kill -0" in script
    assert "/usr/local/bin/openagentd update" in script
    assert "exec /usr/local/bin/openagentd >>" in script
    # The buggy `stop` step has been removed entirely; the parent SIGTERMs
    # itself via _self_terminate_after_response and the restarter polls
    # for the PID to disappear.
    assert "/usr/local/bin/openagentd stop" not in script
    # Output is captured to a real log file, not /dev/null.
    assert "self-update.log" in script

    assert kwargs["stdout"] == settings_routes.subprocess.DEVNULL
    assert kwargs["stderr"] == settings_routes.subprocess.DEVNULL
    assert kwargs["start_new_session"] is True

    # The self-terminate hook is registered as a background task and runs
    # *after* the response — at this point the test client has already
    # received the response, so the mock should have been invoked.
    self_terminate.assert_called_once()


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
