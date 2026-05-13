---
applicable_to: Release a new version of OpenAgentd
description: Bump the version by PR, then publish the GitHub release.
subtask: false
---

## Steps

1. Version target:

- Read `app/version.txt`.
- Propose patch bump.
- Ask if minor/major preferred.
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
- `## Install`: always include the canonical block verbatim. Confirm against the previous release before publishing:

  ```bash
  gh release view v<prev-version> --repo lthoangg/openagentd
  ```

  Block to copy:

  ````
  ```
  uv tool install openagentd
  # or
  pip install openagentd
  ```

  `brew install openagentd` installs the base package only; optional extras (e.g. `openagentd[voice-local]`) must be installed via `uv` or `pip`:

  ```
  uv tool install "openagentd[voice-local]"
  # or
  pip install "openagentd[voice-local]"
  ```
  ````

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
