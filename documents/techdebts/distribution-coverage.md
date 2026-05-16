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
app — they fall back to the CLI (`brew install lthoangg/tap/openagentd`) and the
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

### Linux AppImage (regression at 1.0.3)

**What's missing:** `.AppImage` is currently disabled in
`release-desktop.yml` because `linuxdeploy` reliably fails on
GitHub-hosted ubuntu-22.04 runners with a bare "failed to run
linuxdeploy" error that Tauri swallows. The `.deb` bundle covers
Debian/Ubuntu users in the meantime.

**Cost to restore:** likely 1–2 hours of debugging. Options:
- Switch the Linux runner to ubuntu-24.04 (linuxdeploy issues are
  partly glibc-version-dependent).
- Run `linuxdeploy` standalone in a verbose step before/after the
  Tauri bundle call so the underlying error surfaces in CI logs.
- Use `mksquashfs --comp xz` directly to assemble the AppImage,
  bypassing the linuxdeploy plugin chain entirely.

**When worth doing:** before the next minor release (1.1) — restoring
AppImage gives us coverage of non-Debian Linux distros (Arch, Fedora,
openSUSE without rpm conversion) that `.deb` doesn't reach.

### Windows sidecar smoke test (regression at 1.0.5)

**What's missing:** `scripts/build_sidecar.py --no-smoke` is forced on
the Windows leg of `release-desktop.yml`. The smoke test spawns the
sidecar and waits for an `OPENAGENTD_HANDSHAKE` line on stdout — on
Windows GHA runners this reliably hangs past 30 minutes despite the
60s deadline, even after switching to a threaded `queue.Queue`-based
stdout drain (so the symptom isn't `readline()` blocking the main
thread — the child process itself appears to never write anything,
or its stdout pipe never flushes through to the parent).

macOS and Linux still run the smoke test, so the bundle layout
invariants (versioned cpython directory, `app/cli/__main__.py` reachable,
handshake protocol, token-gated middleware) remain exercised every
release. The Windows bundle's first real integration test is the Tauri
app launching it.

**Cost to restore:** 1–2 hours. Candidate diagnoses:
- Spawn the sidecar with `--no-buffer` / `PYTHONUNBUFFERED=1` explicitly
  in the smoke test environment (we set it on the parent shell but it
  may not be propagating to the grandchild uvicorn worker).
- Replace the stdout pipe with a temp file the child writes to and the
  parent tails — sidesteps any Windows-specific pipe buffering quirk.
- Run the smoke test in `cmd.exe` rather than `bash` so we use the
  shell Tauri itself will use to spawn the sidecar at runtime.

**When worth doing:** before any change to the handshake protocol,
the sidecar bootstrap, or `app/cli/commands/serve.py`. Today, those
files are stable.

### macOS 26 (Tahoe) traffic-light offset

**What's wrong:** on macOS 26 the OS-drawn traffic-light buttons
render visibly lower than the centre of our 40 pt application
header on the CI-built `.app` bundle, even though
`traffic_light_position.y = 22` centres them perfectly on every
other supported macOS (Big Sur → Sequoia) and on a locally-rebuilt
release bundle on macOS 26.

**Why it happens:** the `y` argument is a *bottom* inset that Tao
applies via NSWindow's title-bar resize at runtime, but the value
AppKit picks for the implicit title-bar height changes based on
the macOS SDK the binary was linked against. Our `release-desktop.yml`
runs `macos-14` (Sonoma SDK) for binary size + cache locality; the
resulting binary picks Sonoma-era title-bar metrics that look
correct on Sonoma/Sequoia but ~6 pt low on Tahoe. A binary built
on Tahoe with the Tahoe SDK reads `y=22` correctly on Tahoe.

**Cost to fix:** the cheapest path is to bump the macOS runner to
`macos-15` (Sequoia) once it's a stable image — that pulls the
linked SDK forward, reducing the offset drift to ~1–2 pt. The full
fix is a `macos-26` runner (GA pending) or building against the
current SDK via `MACOSX_DEPLOYMENT_TARGET` + `SDKROOT` env hints.
Single-value y is fine; we don't need `cfg!(debug_assertions)`
branching because the issue is SDK-linked, not debug-vs-release.

**When worth doing:** when macOS 26 reaches stable + double-digit
adoption (~6 months after GA). Before then, the affected audience
is small (Tahoe beta testers) and the rendering is cosmetic only.

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
