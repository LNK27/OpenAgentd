"""``openagentd vault`` commands."""

from __future__ import annotations

import argparse
import asyncio

from app.services.vault_ingest import IngestResult, ingest_vault


def cmd_vault_ingest(args: argparse.Namespace) -> None:
    """Run human Obsidian vault ingest/reconcile."""
    result = asyncio.run(ingest_vault(apply=args.apply))
    _print_ingest_report(result, apply=args.apply)


def _print_ingest_report(result: IngestResult, *, apply: bool) -> None:
    mode = "apply" if apply else "dry-run"
    print("Vault Ingest Report")
    print("===================")
    print(f"Mode:              {mode}")
    print(f"Scanned:           {result.scanned} notes")
    print(f"Normalized:        {result.normalized} notes")
    print(f"Indexed:           {result.indexed} links")
    print(f"Stale removed:     {result.stale_removed} links")
    print(f"Already OK:        {result.skipped_ok} notes")
    print(f"Skipped subfolders: {result.skipped_subfolders}")
    print()
    print("Warnings:")
    if result.warnings:
        for warning in result.warnings:
            print(f"  - {warning}")
    else:
        print("  (none)")
    print()
    print("Errors:")
    if result.errors:
        for error in result.errors:
            print(f"  - {error}")
    else:
        print("  (none)")
