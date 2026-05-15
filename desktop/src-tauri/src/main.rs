// Prevents additional console window on Windows in release.
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

mod sidecar;

use anyhow::{anyhow, Context, Result};
use serde::Serialize;
use std::sync::Arc;
use std::time::Duration;
use tauri::{AppHandle, Emitter, Manager, RunEvent, WebviewUrl, WebviewWindowBuilder};
use tokio::sync::Mutex;

use crate::sidecar::{Handshake, Sidecar};

/// Shared application state.
struct AppState {
    sidecar: Arc<Mutex<Option<Sidecar>>>,
}

/// Apply platform-specific window chrome.
///
/// macOS uses the **overlay** title-bar style — the WebView extends
/// under the OS-drawn traffic-lights and the React app reserves a
/// 70 pt left inset for them. ``traffic_light_position`` must be set
/// here because the JSON config value is ignored when the window is
/// built from Rust via ``WebviewWindowBuilder``.
///
/// ``y`` is a *bottom* inset: Tao resizes the native title-bar to
/// ``button_height + y`` (tao 0.35.x, macos/view.rs:1152). Empirical
/// tuning for our 40 pt header: 14 → too high, 22 → centred, 26 →
/// too low.
///
/// Windows and Linux keep their native chrome.
fn configure_window_chrome(builder: WebviewWindowBuilder<'_, tauri::Wry, AppHandle>) -> WebviewWindowBuilder<'_, tauri::Wry, AppHandle> {
    #[cfg(target_os = "macos")]
    {
        use tauri::{LogicalPosition, TitleBarStyle};
        builder
            .title_bar_style(TitleBarStyle::Overlay)
            .hidden_title(true)
            .traffic_light_position(LogicalPosition::new(12.0, 22.0))
    }
    #[cfg(not(target_os = "macos"))]
    {
        builder
    }
}

#[derive(Clone, Serialize)]
struct BackendReady {
    port: u16,
    version: String,
}

#[derive(Clone, Serialize)]
struct BackendError {
    message: String,
}

#[tauri::command]
async fn backend_health(state: tauri::State<'_, AppState>) -> Result<bool, String> {
    let mut guard = state.sidecar.lock().await;
    match guard.as_mut() {
        Some(s) => Ok(s.is_alive()),
        None => Ok(false),
    }
}

#[tauri::command]
async fn backend_logs_path(state: tauri::State<'_, AppState>) -> Result<String, String> {
    let guard = state.sidecar.lock().await;
    match guard.as_ref() {
        Some(s) => Ok(s.log_path().to_string_lossy().into_owned()),
        None => Err("backend not started".into()),
    }
}

async fn wait_for_health(base: &str, attempts: u32, delay: Duration) -> Result<()> {
    let client = reqwest::Client::builder()
        .timeout(Duration::from_secs(2))
        .build()
        .context("build reqwest client")?;
    let url = format!("{base}/api/health/live");
    for i in 0..attempts {
        match client.get(&url).send().await {
            Ok(r) if r.status().is_success() => return Ok(()),
            Ok(r) => log::debug!("health attempt {i} got status {}", r.status()),
            Err(e) => log::debug!("health attempt {i} failed: {e}"),
        }
        tokio::time::sleep(delay).await;
    }
    Err(anyhow!("backend did not become healthy after {attempts} attempts"))
}

async fn start_backend_and_window(app: AppHandle) -> Result<()> {
    let state: tauri::State<'_, AppState> = app.state();

    // ── Dev-mode escape hatch ──────────────────────────────────────────────
    // When ``OPENAGENTD_DEV_BACKEND_URL`` is set we skip the bundled
    // sidecar entirely and point the WebView at an externally-managed
    // backend. This is the realistic inner-loop for ``cargo tauri dev``:
    //
    //     terminal 1: make dev                # FastAPI on :8000 with reload
    //     terminal 2: cd web && bun dev       # Vite on :5173, proxies /api → :8000
    //     terminal 3: OPENAGENTD_DEV_BACKEND_URL=http://localhost:5173 \
    //                 cargo tauri dev
    //
    // In dev mode we have no handshake token, so we leave
    // ``window.__OAD_TOKEN__`` undefined. The frontend's auth
    // interceptor falls back to the legacy no-token path, which works
    // because ``OPENAGENTD_DESKTOP_TOKEN`` is also unset on the dev
    // backend.
    if let Ok(dev_url) = std::env::var("OPENAGENTD_DEV_BACKEND_URL") {
        log::info!("dev-mode: using external backend at {dev_url}");
        let url = WebviewUrl::External(dev_url.parse().context("parse dev backend url")?);
        let builder = WebviewWindowBuilder::new(&app, "main", url)
            .title("OpenAgentd (dev)")
            .inner_size(1280.0, 820.0)
            .min_inner_size(760.0, 560.0)
            .visible(false);
        let builder = configure_window_chrome(builder);
        let win = builder.build().context("build webview window")?;
        win.show().context("show window")?;
        win.set_focus().ok();
        app.emit(
            "backend-ready",
            BackendReady {
                port: 0,
                version: "dev".to_string(),
            },
        )
        .ok();
        return Ok(());
    }

    // ── Production: spawn the bundled Python sidecar ──────────────────────
    let mut sidecar = Sidecar::spawn(&app).context("spawn sidecar")?;
    let handshake: Handshake = sidecar
        .read_handshake(Duration::from_secs(30))
        .await
        .context("read sidecar handshake")?;

    log::info!(
        "sidecar handshake: port={} pid={} version={}",
        handshake.port,
        handshake.pid,
        handshake.version
    );

    let base = format!("http://127.0.0.1:{}", handshake.port);
    wait_for_health(&base, 60, Duration::from_millis(250))
        .await
        .context("wait_for_health")?;

    // Build the window AFTER we know the backend URL and token, so we can
    // inject the token via initialization_script before any page JS runs.
    let token = handshake.token.clone();
    let init_script = format!(
        "Object.defineProperty(window, '__OAD_TOKEN__', {{ value: {token_json}, writable: false, configurable: false }});",
        token_json = serde_json::to_string(&token).unwrap_or_else(|_| "\"\"".into())
    );

    let url = WebviewUrl::External(base.parse().context("parse backend url")?);

    let builder = WebviewWindowBuilder::new(&app, "main", url)
        .title("OpenAgentd")
        .inner_size(1280.0, 820.0)
        .min_inner_size(760.0, 560.0)
        .initialization_script(&init_script)
        .visible(false);
    let builder = configure_window_chrome(builder);
    let win = builder.build().context("build webview window")?;

    win.show().context("show window")?;
    win.set_focus().ok();

    // Stash the sidecar so we can clean it up on exit.
    let _ = state.sidecar.lock().await.replace(sidecar);

    app.emit(
        "backend-ready",
        BackendReady {
            port: handshake.port,
            version: handshake.version,
        },
    )
    .ok();

    Ok(())
}

fn main() {
    let state = AppState {
        sidecar: Arc::new(Mutex::new(None)),
    };

    let log_plugin = tauri_plugin_log::Builder::new()
        .level(log::LevelFilter::Info)
        .build();

    tauri::Builder::default()
        .plugin(log_plugin)
        .plugin(tauri_plugin_dialog::init())
        .plugin(tauri_plugin_opener::init())
        .manage(state)
        .invoke_handler(tauri::generate_handler![backend_health, backend_logs_path])
        .setup(|app| {
            let handle = app.handle().clone();
            tauri::async_runtime::spawn(async move {
                if let Err(e) = start_backend_and_window(handle.clone()).await {
                    log::error!("failed to start backend: {e:#}");
                    handle
                        .emit(
                            "backend-error",
                            BackendError {
                                message: format!("{e:#}"),
                            },
                        )
                        .ok();
                }
            });
            Ok(())
        })
        .build(tauri::generate_context!())
        .expect("error while building tauri application")
        .run(|app, event| match event {
            RunEvent::ExitRequested { .. } => {
                let state: tauri::State<'_, AppState> = app.state();
                let sidecar = state.sidecar.clone();
                // Block on shutdown to avoid the process exiting before
                // the child receives SIGTERM.
                tauri::async_runtime::block_on(async move {
                    if let Some(mut s) = sidecar.lock().await.take() {
                        s.shutdown().await;
                    }
                });
            }
            _ => {}
        });
}
