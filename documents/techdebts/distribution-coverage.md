# Distribution coverage

Tracks package-manager channels we've **deliberately deferred** and the
conditions under which it would be worth revisiting them. The goal is
not to ship to every channel — it's to make the cost/benefit explicit
so the decision can be revisited without re-doing the analysis.

For the channels we **do** ship today, see [`documents/docs/install.md`](../docs/install.md).

## Current coverage

| Channel | Status |
|---|---|
| PyPI (`pip`, `pipx`, `uv tool install`) | Shipped, automated |
| Homebrew **formula** (CLI) | Shipped, automated |
| Homebrew **cask** (macOS app, Apple Silicon) | Shipped, automated |
| Docker / GHCR | Shipped, automated |
| `install.sh` / `install.ps1` (curl-pipe) | Shipped, static |
| Desktop `.dmg` / `.exe` / `.msi` / `.AppImage` / `.deb` | Shipped, automated |

## Deferred

### Intel Mac desktop build

**What's missing:** `.github/workflows/release-desktop.yml` builds
`aarch64-apple-darwin` only. Intel Mac users have no native desktop
app — they fall back to the CLI (`brew install openagentd`) and the
web cockpit.

**Cost to add:** ~10 minutes extra CI per release (one `macos-13`
runner with `x86_64-apple-darwin` target), one extra matrix entry,
update the cask to drop `depends_on arch: :arm64`.

**When worth doing:**
- Any concrete user report ("I have an Intel MacBook and want the
  desktop app"), **or**
- Telemetry showing >10% of CLI installs come from Intel macOS, **or**
- We add a feature that depends on a desktop-only capability the web
  cockpit can't reach.

Until then, the CLI + web cockpit is a sufficient fallback for Intel.

### Scoop bucket (Windows)

**What's missing:** No `scoop install openagentd`. Windows users today
have two paths: `install.ps1` (CLI only) or manual `.msi`/`.exe`
download (desktop, SmartScreen warning).

**Cost to add:** New repo `lthoangg/scoop-bucket`, one JSON manifest
per artefact (CLI and/or desktop), Scoop's `autoupdate` field scrapes
new releases. ~half a day of work, near-zero ongoing maintenance.

**When worth doing:**
- After the Homebrew cask lands and we've validated the unsigned-bundle
  postflight workflow — Scoop bypasses SmartScreen by design so it's
  the cheapest Windows GUI install path.
- Pair with a `documents/docs/install.md` update.

### winget (Windows, Microsoft Store)

**What's missing:** No `winget install openagentd`.

**Cost to add:** Submit a manifest PR to
[`microsoft/winget-pkgs`](https://github.com/microsoft/winget-pkgs)
per release. Reviewers expect Authenticode-signed binaries; unsigned
submissions are accepted but the install UX still shows SmartScreen
warnings.

**When worth doing:**
- Only after we buy an EV Authenticode certificate (~$300+/yr) or a
  cheaper OV cert (~$100/yr with longer SmartScreen reputation ramp).
- Without signing, winget gives us discoverability with no UX
  improvement — Scoop is the better near-term answer.

### AUR (`openagentd-bin`)

**What's missing:** No Arch User Repository package.

**Cost to add:** One `PKGBUILD` that downloads the AppImage (or the
`.deb` extracted), zero CI integration needed — AUR pulls from GitHub
releases directly.

**When worth doing:**
- Wait for a community contributor. Owner-maintained AUR packages are
  a low-leverage commitment; community-maintained ones survive
  longer.
- If we receive a PR or AUR submission request, we should help review
  but not block on it.

### Snap / Flatpak

**Skip.** Both require separate publisher accounts and review queues.
Flatpak's sandbox model conflicts with OpenAgentd's "agent reads/writes
your filesystem" core capability — sandbox-bypassing portals would
need to be requested for every tool, and the install UX would be
worse than the AppImage. Snap is shrinking outside Ubuntu and adds an
auto-update layer we don't control.

The AppImage covers ~all glibc 2.28+ distros with zero packaging cost.

### RPM / COPR / Fedora

**Skip for now.** Tauri can emit `.rpm` and we could add it to the
matrix in `release-desktop.yml`, but proper Fedora integration
requires a COPR or RPM Fusion presence with its own review cadence.
The `.AppImage` already runs on Fedora.

**When worth doing:** Concrete user demand from a Fedora user, or if
we ever want to ship to RHEL/Rocky enterprise environments.

## Re-evaluation cadence

Revisit this list at each minor version bump (1.x → 1.(x+1)) or when
distribution-related GitHub issues accumulate. The decisions above are
defensible **today** — they may not be defensible at 2.0.
