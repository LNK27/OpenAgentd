---
applicable_to: Release a new version of OpenAgentd
description: Bump the version by PR, then publish the GitHub release.
subtask: false
---

## Steps

1. Read `app/version.txt`, propose a patch bump, and ask if minor/major is preferred.

2. Check worktree. Stop if dirty.

```bash
git status --short
```

3. Ask and wait:

> Ready to release **`<version>`**. Proceed? **(yes / no)**

4. On a PR branch, update `app/version.txt`, `pyproject.toml`, `web/package.json`, and `uv.lock`.

If the PR only bumps release metadata, use `chore: bump version to <version>` for the commit and PR title. If the PR also contains user-facing features, fixes, or behavior changes, use a title that describes those changes and append the version range, e.g. `Fix frontend update restart (v0.3.3 -> v0.3.4)`.

```bash
uv sync
uv run ruff format app/ tests/
uv run ruff format --check app/ tests/
git add app/version.txt pyproject.toml uv.lock web/package.json
git commit -m "<release commit title>"
git push -u origin <branch>
gh pr create --title "<release PR title>" --base main
```

Wait for CI and merge the PR.

5. After merge, generate release notes.

```bash
PREV_TAG=$(git describe --tags --abbrev=0 HEAD^)
git log ${PREV_TAG}..HEAD --oneline --no-merges
```

Write tight, user-facing notes. Aim for **under ~150 words total**. Rules:

- Skip version-bump commits. Treat commit subjects as raw material — paraphrase, do not transcribe.
- Lead with the user-visible behavior change, not internals (no module names, no test counts, no implementation details unless required to explain a fix).
- One short paragraph per section. No bullet lists unless genuinely enumerating multiple distinct items.

Sections (use only the ones that apply, in this order):

1. `## Breaking Changes` — only if migration is required.
2. `## What's changed` — the main narrative. One paragraph. State what users will notice.
3. `## Upgrade` — only when users need to do something. Be specific (e.g. "delete and recreate tasks of type X").
4. `## Install` — always include this fixed block:

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

5. End with `**Full changelog:** https://github.com/lthoangg/openagentd/compare/<prev>...<next>`.

Avoid: a `## Tests` section, internal file paths, marketing language ("we're excited to..."), and restating what the section heading already says.

6. Trigger release.

```bash
gh workflow run release.yml --field confirm=release
gh run list --workflow=release.yml --limit=3
```

7. Replace GitHub release notes:

```bash
gh release edit v<version> --repo lthoangg/openagentd --notes "<release notes>"
```
