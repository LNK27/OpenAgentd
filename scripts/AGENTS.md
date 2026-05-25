# scripts/ — Agent Instructions

Maintainer scripts for benchmarks, sidecar packaging, updater keys, and release manifest generation.

## Tech stack

- Python scripts are run with the repo's `uv` environment unless the script explicitly documents otherwise.
- Shell helper: `generate_updater_keys.sh`.

## Scripts

```
build_sidecar.py          Build the desktop Python sidecar bundle
make_updater_manifest.py  Generate updater release manifests
bench_snapshot.py         Snapshot-related benchmark helper
bench_undo_http.py        HTTP undo/redo benchmark helper
bench_undo_redo.py        Undo/redo benchmark helper
bench_undo_redo_layers.py Layered undo/redo benchmark helper
generate_updater_keys.sh  Tauri updater signing key helper
```

## Essential commands

```bash
uv run python scripts/build_sidecar.py --help
uv run python scripts/make_updater_manifest.py --help
make -C desktop sidecar
```

## Conventions

- Keep scripts non-interactive by default and safe to run from the repo root.
- Prefer argparse help text over separate usage comments.
- Do not embed signing keys, tokens, or machine-specific paths.
- Packaging scripts should preserve cross-platform behavior for macOS, Linux, and Windows.

## Checks

Run the script's `--help` and the smallest focused dry-run or target command available. For sidecar changes, also use `make -C desktop sidecar` when feasible.
