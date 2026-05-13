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

2. Worktree check:

- Stop if dirty.

```bash
git status --short
```

3. Confirm release:

> Ready to release **`<version>`**. Proceed? **(yes / no)**

4. Version PR:

- Use PR branch.
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

- Wait for CI.
- Merge PR.

5. Release notes:

- Generate after merge.

```bash
PREV_TAG=$(git describe --tags --abbrev=0 HEAD^)
git log ${PREV_TAG}..HEAD --oneline --no-merges
```

- Tight, user-facing notes.
- Aim under ~150 words total.
- Skip version-bump commits.
- Treat commit subjects as raw material.
- Paraphrase; do not transcribe.
- Lead with user-visible behavior change.
- Avoid internals unless required to explain a fix.
- One short paragraph per section.
- No bullet lists unless enumerating distinct items.

Sections:

- `## Breaking Changes`: only if migration required.
- `## What's changed`: main narrative, one paragraph, user-noticeable changes.
- `## Upgrade`: only if users need action; be specific.
- `## Install`: always include fixed block:

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

7. GitHub release notes:

- Replace generated notes.

```bash
gh release edit v<version> --repo lthoangg/openagentd --notes "<release notes>"
```
