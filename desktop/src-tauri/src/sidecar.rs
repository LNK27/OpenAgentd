//! Python sidecar supervisor.
//!
//! Spawns `python -m app.cli serve --handshake --generate-token
//! --parent-pid <us>`, parses the first JSON handshake line from stdout,
//! and exposes the child for graceful shutdown.
//!
//! Layout expectations (paths relative to the bundled resources dir):
//!
//! - `sidecar/python/bin/python3` (macOS/Linux) or `sidecar\python\python.exe`
//!   (Windows): the bundled CPython interpreter.
//! - `sidecar/site-packages/`: pre-installed openagentd + dependencies.
//! - `sidecar/_web_dist/`: the built React frontend (also embedded in
//!   `site-packages/app/_web_dist/`; either works).
//!
//! On Windows we add the sidecar to a Job Object with
//! `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE` so it dies if Tauri does — the
//! Python `--parent-pid` watch is a backup.

use anyhow::{anyhow, Context, Result};
use serde::Deserialize;
use std::path::{Path, PathBuf};
use std::process::Stdio;
use std::time::Duration;
use tauri::{AppHandle, Manager};
use tokio::io::{AsyncBufReadExt, BufReader};
use tokio::process::{Child, Command};
use tokio::time::timeout;

const HANDSHAKE_PREFIX: &str = "OPENAGENTD_HANDSHAKE ";
const SHUTDOWN_GRACE: Duration = Duration::from_secs(5);

#[derive(Debug, Deserialize, Clone)]
pub struct Handshake {
    pub port: u16,
    pub pid: u32,
    pub version: String,
    pub token: String,
}

pub struct Sidecar {
    child: Child,
    handshake: Option<Handshake>,
    stdout_reader: Option<BufReader<tokio::process::ChildStdout>>,
    log_path: PathBuf,
}

impl Sidecar {
    pub fn spawn(app: &AppHandle) -> Result<Self> {
        let resource_dir = app
            .path()
            .resource_dir()
            .context("locate resource dir")?;
        let sidecar_root = resource_dir.join("sidecar");

        let python_bin = resolve_python_bin(&sidecar_root)
            .with_context(|| format!("locate python binary under {}", sidecar_root.display()))?;

        let log_dir = app
            .path()
            .app_log_dir()
            .context("resolve app log dir")?;
        std::fs::create_dir_all(&log_dir).context("create app log dir")?;
        let log_path = log_dir.join("backend.log");

        let parent_pid = std::process::id();

        log::info!(
            "spawning sidecar: {} (parent_pid={}, log={})",
            python_bin.display(),
            parent_pid,
            log_path.display()
        );

        // Explicit script path (not ``-m app.cli``) so we know exactly
        // which CLI module is invoked. ``-m`` would let Python search
        // ``sys.path`` and could surface a vendored ``app.cli`` from a
        // user-extended directory later.
        let cli_entry = sidecar_root
            .join("site-packages")
            .join("app")
            .join("cli")
            .join("__main__.py");
        if !cli_entry.is_file() {
            return Err(anyhow!(
                "sidecar bundle missing CLI entry at {}",
                cli_entry.display()
            ));
        }

        let mut cmd = Command::new(&python_bin);
        cmd.arg(&cli_entry)
            .arg("serve")
            .arg("--host")
            .arg("127.0.0.1")
            .arg("--port")
            .arg("0")
            .arg("--handshake")
            .arg("--generate-token")
            .arg("--parent-pid")
            .arg(parent_pid.to_string())
            // PYTHONHOME / PYTHONPATH point at the bundle so the
            // interpreter resolves modules from our site-packages, not
            // from any system Python that happens to be on PATH.
            .env("PYTHONHOME", &sidecar_root.join("python"))
            .env(
                "PYTHONPATH",
                sidecar_root.join("site-packages").as_os_str(),
            )
            .env("PYTHONUNBUFFERED", "1")
            .env("APP_ENV", "production")
            .stdin(Stdio::null())
            .stdout(Stdio::piped())
            .stderr(Stdio::piped());

        // Path resolution is delegated to the Python backend
        // (app.core.paths). It already resolves the XDG-spec directories
        // — ~/.config/openagentd, ~/.local/share/openagentd, etc. — that
        // the CLI uses, with $OPENAGENTD_*_DIR env-var overrides for
        // anyone who wants different paths. Setting Tauri's per-app
        // app_data_dir / app_config_dir here would silently bifurcate
        // the desktop from a terminal ``openagentd`` install — same
        // product, different data, different agents, different DB.
        // Keep them unified.

        #[cfg(windows)]
        {
            use std::os::windows::process::CommandExt;
            // CREATE_NO_WINDOW | CREATE_SUSPENDED.
            //
            // ``CREATE_SUSPENDED`` is critical: it lets us attach the child
            // to our Job Object *before* it runs a single instruction. If we
            // skipped this and Tauri died between ``spawn()`` and
            // ``AssignProcessToJobObject``, the sidecar would orphan.
            const CREATE_NO_WINDOW: u32 = 0x0800_0000;
            const CREATE_SUSPENDED: u32 = 0x0000_0004;
            cmd.creation_flags(CREATE_NO_WINDOW | CREATE_SUSPENDED);
        }

        let mut child = cmd.spawn().context("spawn python sidecar")?;

        #[cfg(windows)]
        {
            // Attach to the Job Object (kills the child on Tauri exit),
            // then resume the suspended primary thread. If anything in
            // this sequence fails we kill the child rather than leave a
            // suspended orphan.
            if let Err(e) = attach_to_job_object(&child) {
                let _ = child.start_kill();
                return Err(e.context("attach to job object"));
            }
            if let Err(e) = resume_primary_thread(&child) {
                let _ = child.start_kill();
                return Err(e.context("resume primary thread"));
            }
        }

        let stdout = child
            .stdout
            .take()
            .ok_or_else(|| anyhow!("sidecar stdout missing"))?;
        // Pipe stderr to the log file in the background.
        if let Some(stderr) = child.stderr.take() {
            let log_path_clone = log_path.clone();
            tokio::spawn(async move {
                pipe_to_log(stderr, log_path_clone).await;
            });
        }

        Ok(Sidecar {
            child,
            handshake: None,
            stdout_reader: Some(BufReader::new(stdout)),
            log_path,
        })
    }

    pub async fn read_handshake(&mut self, max_wait: Duration) -> Result<Handshake> {
        let mut reader = self
            .stdout_reader
            .take()
            .ok_or_else(|| anyhow!("stdout already consumed"))?;
        let log_path = self.log_path.clone();

        let parse_task = async {
            let mut line = String::new();
            loop {
                line.clear();
                let n = reader
                    .read_line(&mut line)
                    .await
                    .context("read sidecar stdout")?;
                if n == 0 {
                    return Err(anyhow!("sidecar exited before handshake"));
                }
                let trimmed = line.trim_end();
                // Forward non-handshake lines to the log so we don't lose
                // early startup output.
                if !trimmed.starts_with(HANDSHAKE_PREFIX) {
                    append_log_line(&log_path, trimmed).await;
                    continue;
                }
                let json = trimmed.trim_start_matches(HANDSHAKE_PREFIX);
                let hs: Handshake =
                    serde_json::from_str(json).context("parse handshake JSON")?;
                // After we have the handshake, drain the rest of stdout
                // into the log file in the background.
                let log_path_drain = log_path.clone();
                tokio::spawn(async move {
                    pipe_lines_to_log(reader, log_path_drain).await;
                });
                return Ok(hs);
            }
        };

        let hs = timeout(max_wait, parse_task)
            .await
            .map_err(|_| anyhow!("timed out waiting for handshake"))??;
        self.handshake = Some(hs.clone());
        Ok(hs)
    }

    /// True iff the child process is still running.
    ///
    /// ``Child::id()`` is *not* a liveness check — it returns ``Some``
    /// for the lifetime of the ``Child`` struct, even after the process
    /// has exited. ``try_wait`` is the only correct probe.
    pub fn is_alive(&mut self) -> bool {
        match self.child.try_wait() {
            Ok(None) => true,     // still running
            Ok(Some(_)) => false, // exited (and reaped)
            Err(_) => false,      // can't query — treat as dead
        }
    }

    pub fn log_path(&self) -> &Path {
        &self.log_path
    }

    pub async fn shutdown(&mut self) {
        let Some(pid) = self.child.id() else {
            return;
        };
        log::info!("shutting down sidecar pid={pid}");
        #[cfg(unix)]
        {
            // SIGTERM lets uvicorn drain in-flight requests + run shutdown hooks
            // (mcp.stop(), team.stop(), otel.shutdown(), …).
            use nix::sys::signal::{kill, Signal};
            use nix::unistd::Pid;
            let _ = kill(Pid::from_raw(pid as i32), Signal::SIGTERM);
        }
        #[cfg(windows)]
        {
            // Windows has no SIGTERM equivalent. ``start_kill`` issues a
            // non-blocking ``TerminateProcess`` immediately so we don't sit on
            // a 5-second timeout in the common clean-exit path. The Job
            // Object's ``KILL_ON_JOB_CLOSE`` is still our backstop if Tauri
            // itself dies without running this code.
            let _ = self.child.start_kill();
        }
        match timeout(SHUTDOWN_GRACE, self.child.wait()).await {
            Ok(Ok(status)) => log::info!("sidecar exited: {status}"),
            Ok(Err(e)) => log::warn!("sidecar wait error: {e}"),
            Err(_) => {
                log::warn!("sidecar did not exit in {SHUTDOWN_GRACE:?}; force-killing");
                let _ = self.child.kill().await;
            }
        }
    }
}

fn resolve_python_bin(sidecar_root: &Path) -> Result<PathBuf> {
    #[cfg(target_os = "windows")]
    let candidates = [
        sidecar_root.join("python").join("python.exe"),
        sidecar_root.join("python").join("install").join("python.exe"),
    ];
    #[cfg(not(target_os = "windows"))]
    let candidates = [
        sidecar_root.join("python").join("bin").join("python3"),
        sidecar_root.join("python").join("install").join("bin").join("python3"),
    ];
    for c in candidates.iter() {
        if c.is_file() {
            return Ok(c.clone());
        }
    }
    Err(anyhow!(
        "no python binary found in sidecar bundle (looked in: {:?})",
        candidates.iter().map(|p| p.display().to_string()).collect::<Vec<_>>()
    ))
}

async fn pipe_to_log<R>(stream: R, log_path: PathBuf)
where
    R: tokio::io::AsyncRead + Unpin,
{
    let reader = BufReader::new(stream);
    pipe_lines_to_log(reader, log_path).await;
}

async fn pipe_lines_to_log<R>(mut reader: BufReader<R>, log_path: PathBuf)
where
    R: tokio::io::AsyncRead + Unpin,
{
    use tokio::fs::OpenOptions;
    use tokio::io::AsyncWriteExt;
    let mut line = String::new();
    let Ok(mut file) = OpenOptions::new()
        .create(true)
        .append(true)
        .open(&log_path)
        .await
    else {
        return;
    };
    loop {
        line.clear();
        match reader.read_line(&mut line).await {
            Ok(0) => return,
            Ok(_) => {
                let _ = file.write_all(line.as_bytes()).await;
                let _ = file.flush().await;
            }
            Err(_) => return,
        }
    }
}

async fn append_log_line(log_path: &Path, line: &str) {
    use tokio::fs::OpenOptions;
    use tokio::io::AsyncWriteExt;
    if let Ok(mut f) = OpenOptions::new()
        .create(true)
        .append(true)
        .open(log_path)
        .await
    {
        let _ = f.write_all(line.as_bytes()).await;
        let _ = f.write_all(b"\n").await;
    }
}

#[cfg(windows)]
fn attach_to_job_object(child: &Child) -> Result<()> {
    use once_cell::sync::OnceCell;
    use windows::Win32::Foundation::HANDLE;
    use windows::Win32::System::JobObjects::{
        AssignProcessToJobObject, CreateJobObjectW, SetInformationJobObject,
        JobObjectExtendedLimitInformation, JOBOBJECT_EXTENDED_LIMIT_INFORMATION,
        JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE,
    };
    use windows::Win32::System::Threading::{OpenProcess, PROCESS_SET_QUOTA, PROCESS_TERMINATE};

    // Single process-wide Job Object. ``KILL_ON_JOB_CLOSE`` means every
    // child attached here dies when Tauri exits — even on hard crash —
    // because closing the last handle to the job (which happens at
    // process teardown) terminates all members.
    static JOB: OnceCell<HANDLE> = OnceCell::new();

    let job = JOB.get_or_try_init::<_, anyhow::Error>(|| unsafe {
        let h = CreateJobObjectW(None, None)?;
        let mut info = JOBOBJECT_EXTENDED_LIMIT_INFORMATION::default();
        info.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE;
        SetInformationJobObject(
            h,
            JobObjectExtendedLimitInformation,
            &info as *const _ as *const _,
            std::mem::size_of::<JOBOBJECT_EXTENDED_LIMIT_INFORMATION>() as u32,
        )?;
        Ok(h)
    })?;

    let pid = child.id().ok_or_else(|| anyhow!("child pid missing"))?;
    unsafe {
        let process = OpenProcess(PROCESS_TERMINATE | PROCESS_SET_QUOTA, false, pid)?;
        AssignProcessToJobObject(*job, process)?;
    }
    Ok(())
}

/// Resume the primary thread of a process spawned with ``CREATE_SUSPENDED``.
///
/// We snapshot the system's thread list and find the first thread whose
/// owner PID matches the child. That's deterministically the primary
/// thread because the child hasn't run yet (it's suspended) so it cannot
/// have created any secondary threads.
#[cfg(windows)]
fn resume_primary_thread(child: &Child) -> Result<()> {
    use windows::Win32::Foundation::CloseHandle;
    use windows::Win32::System::Diagnostics::ToolHelp::{
        CreateToolhelp32Snapshot, Thread32First, Thread32Next, TH32CS_SNAPTHREAD, THREADENTRY32,
    };
    use windows::Win32::System::Threading::{OpenThread, ResumeThread, THREAD_SUSPEND_RESUME};

    let pid = child.id().ok_or_else(|| anyhow!("child pid missing"))?;

    unsafe {
        let snap = CreateToolhelp32Snapshot(TH32CS_SNAPTHREAD, 0)
            .context("CreateToolhelp32Snapshot")?;
        let mut entry = THREADENTRY32 {
            dwSize: std::mem::size_of::<THREADENTRY32>() as u32,
            ..Default::default()
        };
        if Thread32First(snap, &mut entry).is_err() {
            let _ = CloseHandle(snap);
            return Err(anyhow!("Thread32First returned no threads"));
        }
        loop {
            if entry.th32OwnerProcessID == pid {
                let thread = OpenThread(THREAD_SUSPEND_RESUME, false, entry.th32ThreadID)
                    .context("OpenThread")?;
                let prev_count = ResumeThread(thread);
                let _ = CloseHandle(thread);
                let _ = CloseHandle(snap);
                if prev_count == u32::MAX {
                    return Err(anyhow!("ResumeThread failed"));
                }
                return Ok(());
            }
            if Thread32Next(snap, &mut entry).is_err() {
                let _ = CloseHandle(snap);
                return Err(anyhow!("no thread found for pid {}", pid));
            }
        }
    }
}
