---
applicable_to: Release a new version of OpenAgentd
description: Bump the version by PR, then publish the GitHub release.
subtask: false
---

## Steps

1. Version target:

- Read `app/version.txt`.
- Determine the bump from the actual diff content, not the branch name:
  - **Feature or new capability**: bump minor, e.g. `1.0.0` -> `1.1.0`.
  - **Bug fix, maintenance, docs, tests, or internal-only change**: bump patch, e.g. `1.0.0` -> `1.0.1`.
  - **Patch-only releases stay patch-only**: continue incrementing the patch number, e.g. `1.0.5` -> `1.0.6`; do not bump minor just because there have been several patches.
  - **Breaking change**: ask whether a major bump is intended.
- Propose the calculated version and confirm with the user before applying it.
- Branch prefix (`feat/`, `fix/`, `chore/`) is not signal — judge from diff content.

2. Worktree check:

- Stop if dirty.

```bash
git status --short
```

3. Confirm release:

> Ready to release **`<version>`**. Proceed? **(yes / no)**

4. Version PR:

- Reuse the existing feature branch when present; do not spin a fresh `release/` branch on top of it.
- Update `app/version.txt`, `pyproject.toml`, `web/package.json`, `uv.lock`.
- Metadata-only title: `chore: bump version to <version>`.
- User-facing change title: describe change, append range.
- Example: `Fix frontend update restart (v0.3.3 -> v0.3.4)`.

```bash
uv sync
uv run ruff format app/ tests/
uv run ruff format --check app/ tests/
git add app/version.txt pyproject.toml uv.lock web/package.json
git commit -m "<release commit title>"
git push -u origin <branch>
gh pr create --title "<release PR title>" --base main
```

- Wait for CI:

```bash
gh pr checks <pr-number>
```

- Check PR review comments before merging:

```bash
gh pr view <pr-number> --comments --json comments,reviews
gh api repos/lthoangg/openagentd/pulls/<pr-number>/comments \
  --jq '.[] | "FILE: \(.path):\(.line // .original_line)\nAUTHOR: \(.user.login)\n---\n\(.body)\n==="'
```

- Triage each comment: apply valid ones as additional commits on the same branch, defer false-positives with a one-line rationale.
- Re-poll CI after each push.
- Merge PR:
  - Default: `gh pr merge <pr-number> --merge --delete-branch --admin` to preserve the multi-commit history of the feature branch.
  - Use `--squash` only when the branch is a single logical change (e.g. metadata-only bump).
  - `--admin` is required when branch protection blocks solo-author PRs on `REVIEW_REQUIRED`; confirm with the user before using it.

5. Release notes:

- Generate after merge from `main`.

```bash
git checkout main && git pull --ff-only
PREV_TAG=$(git describe --tags --abbrev=0 HEAD^)
git log ${PREV_TAG}..HEAD --oneline --no-merges
```

- Skip commits unrelated to this branch's user-facing work (e.g. earlier docs-only commits that landed on `main` separately).
- Tight, user-facing notes.
- Aim under ~150 words total.
- Skip version-bump commits.
- Treat commit subjects as raw material.
- Paraphrase; do not transcribe.
- Lead with user-visible behavior change.
- Avoid internals unless required to explain a fix.
- Bullet list is fine when the release ships several distinct fixes; otherwise prefer one short paragraph.

Sections:

- `## Breaking Changes`: only if migration required.
- `## What's changed`: main narrative, user-noticeable changes.
- `## Upgrade`: only if users need action; be specific.
- `## Install`: structure by install **surface**, not by chronology. One labelled block per channel — desktop, CLI, Docker — so a reader picks their channel and stops. Confirm against the previous release before publishing:

  ```bash
  gh release view v<prev-version> --repo lthoangg/openagentd
  ```

  **CLI-only block** (patch/minor releases that don't change install surfaces — copy verbatim):

  ````
  ```
  uv tool install openagentd
  # or
  pip install openagentd
  # or
  brew install lthoangg/tap/openagentd
  ```

  `brew install lthoangg/tap/openagentd` installs the base package only; optional extras (e.g. `openagentd[full]`) must be installed via `uv` or `pip`:

  ```
  uv tool install "openagentd[full]"
  # or
  pip install "openagentd[full]"
  ```
  ````

  **Expanded block** (when the release introduces/changes desktop, Homebrew cask, Docker, or install-script surfaces) — drop the channels that aren't relevant, keep the labelling consistent:

  ````
  **Desktop app** — download from the [desktop releases](https://github.com/lthoangg/openagentd/releases?q=desktop) page:

  - macOS Apple Silicon → `brew install --cask lthoangg/tap/openagentd` (recommended — ad-hoc signs automatically), or `OpenAgentd_*_aarch64.dmg` (run bundled `install.sh`, right-click → Open the first time).
  - Windows → `OpenAgentd_*_x64-setup.exe` (More info → Run anyway at SmartScreen).
  - Linux → `OpenAgentd_*_amd64.AppImage` (`chmod +x` and run) or the `.deb`.

  **CLI / API server**

  ```
  uv tool install openagentd
  # or
  pip install openagentd
  # or
  brew install lthoangg/tap/openagentd
  ```

  `brew install lthoangg/tap/openagentd` installs the base package only; optional extras (e.g. `openagentd[full]`) must be installed via `uv` or `pip`:

  ```
  uv tool install "openagentd[full]"
  # or
  pip install "openagentd[full]"
  ```

  **Docker**

  ```
  docker pull ghcr.io/lthoangg/openagentd:<version>
  ```
  ````

- `## Upgrade`: when present, **split by install channel** — never combine channels in one prose paragraph. Each bullet is a copy-pasteable command (or "Settings → … → Install" path). Example shape:

  ````
  - **Desktop app (in-app updater)** — Settings → Application update → Check for updates → Install.
  - **Desktop app via Homebrew** — `brew upgrade --cask openagentd`.
  - **CLI via uv** — `uv tool install --upgrade openagentd`.
  - **CLI via pip** — `pip install --upgrade openagentd`.
  - **CLI via Homebrew** — `brew upgrade openagentd`.
  - **Docker** — `docker compose pull && docker compose up -d`.
  ````

  If a channel has extra requirements (data move, env var rename, config migration), spell it out under the matching bullet — not in a generic preamble.

- End with `**Full changelog:** https://github.com/lthoangg/openagentd/compare/<prev>...<next>`.
- Avoid `## Tests` section.
- Avoid internal file paths.
- Avoid marketing language.
- Avoid restating section headings.

6. Trigger release:

```bash
gh workflow run release.yml --field confirm=release
gh run list --workflow=release.yml --limit=3
```

- Wait for the run to complete (`status=completed conclusion=success`) before editing notes; the workflow creates the tag, release, and uploads the wheel + sdist.

7. GitHub release notes:

- Replace generated notes.

```bash
git fetch --tags
gh release view v<version> --repo lthoangg/openagentd
gh release edit v<version> --repo lthoangg/openagentd --notes "<release notes>"
```

- Verify the patched notes:

```bash
gh release view v<version> --repo lthoangg/openagentd | sed -n '/## Install/,/Full changelog/p'
```
