from __future__ import annotations

import argparse

import pytest

from app.cli.commands.vault import cmd_vault_ingest
from app.services.vault_ingest import IngestResult


def test_cmd_vault_ingest_prints_dry_run_report(
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _fake_ingest_vault(*, apply: bool) -> IngestResult:
        assert apply is False
        return IngestResult(
            scanned=2,
            normalized=1,
            indexed=1,
            stale_removed=1,
            skipped_ok=1,
            skipped_subfolders=1,
            warnings=["20-topics/nested/ — skipped (subfolder not supported in v1)"],
            errors=[],
        )

    monkeypatch.setattr("app.cli.commands.vault.ingest_vault", _fake_ingest_vault)

    cmd_vault_ingest(argparse.Namespace(apply=False))

    out = capsys.readouterr().out
    assert "Vault Ingest Report" in out
    assert "Mode:              dry-run" in out
    assert "Scanned:           2 notes" in out
    assert "Normalized:        1 notes" in out
    assert "Stale removed:     1 links" in out
    assert "Warnings:" in out
    assert "Errors:" in out
    assert "(none)" in out


def test_cmd_vault_ingest_passes_apply_flag(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[bool] = []

    async def _fake_ingest_vault(*, apply: bool) -> IngestResult:
        calls.append(apply)
        return IngestResult()

    monkeypatch.setattr("app.cli.commands.vault.ingest_vault", _fake_ingest_vault)

    cmd_vault_ingest(argparse.Namespace(apply=True))

    assert calls == [True]
