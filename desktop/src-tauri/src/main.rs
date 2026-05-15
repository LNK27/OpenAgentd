// Prevents additional console window on Windows in release.
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

mod sidecar;

use anyhow::{anyhow, Context, Result};
use serde::Serialize;
use std::sync::{atomic::{AtomicBool, Ordering}, Arc};
use std::time::Duration;
use tauri::{
    menu::{AboutMetadataBuilder, Menu, MenuItem, PredefinedMenuItem, SubmenuBuilder},
    tray::TrayIconBuilder,
    AppHandle, Emitter, Manager, RunEvent, WebviewUrl, WebviewWindowBuilder, WindowEvent, Wry,
};
use tokio::sync::Mutex;

use crate::sidecar::{Handshake, Sidecar};

/// Shared application state.
struct AppState {
    sidecar: Arc<Mutex<Option<Sidecar>>>,
    quitting: Arc<AtomicBool>,
    tray_status: Arc<Mutex<Option<MenuItem<Wry>>>>,
    tray_session: Arc<Mutex<Option<MenuItem<Wry>>>>,
}

const MAIN_WINDOW: &str = "main";
const MENU_SHOW: &str = "show";
const MENU_CHAT: &str = "chat";
const MENU_CODING: &str = "coding";
const MENU_SETTINGS: &str = "settings";
const MENU_TELEMETRY: &str = "telemetry";
const MENU_STATUS: &str = "status";
const MENU_SESSION: &str = "session";
const MENU_QUIT: &str = "quit";

/// Label shown in the tray when no chat/coding session is active.
const TRAY_SESSION_IDLE: &str = "No active session";

/// Hard cap on tray session label width. Keeps the menu from stretching
/// uncomfortably wide when a session title or workspace name is long.
const TRAY_SESSION_MAX_LEN: usize = 60;

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

#[tauri::command]
fn open_macos_microphone_settings() -> Result<(), String> {
    #[cfg(target_os = "macos")]
    {
        std::process::Command::new("open")
            .arg("x-apple.systempreferences:com.apple.preference.security?Privacy_Microphone")
            .spawn()
            .map_err(|e| format!("open System Settings: {e}"))?;
        Ok(())
    }

    #[cfg(not(target_os = "macos"))]
    {
        Err("microphone settings shortcut is only available on macOS".into())
    }
}

fn show_main_window(app: &AppHandle) {
    if let Some(window) = app.get_webview_window(MAIN_WINDOW) {
        let _ = window.unminimize();
        let _ = window.show();
        let _ = window.set_focus();
    }
}

fn navigate_main_window(app: &AppHandle, path: &str) {
    show_main_window(app);
    if let Some(window) = app.get_webview_window(MAIN_WINDOW) {
        let path_json = serde_json::to_string(path).unwrap_or_else(|_| "\"/\"".into());
        let _ = window.eval(format!("window.location.assign({path_json});"));
    }
}

fn quit_app(app: &AppHandle) {
    let state: tauri::State<'_, AppState> = app.state();
    state.quitting.store(true, Ordering::SeqCst);
    app.exit(0);
}

fn handle_desktop_menu(app: &AppHandle, id: &str) {
    match id {
        MENU_SHOW => show_main_window(app),
        MENU_CHAT => navigate_main_window(app, "/"),
        MENU_CODING => navigate_main_window(app, "/coding"),
        MENU_SETTINGS => navigate_main_window(app, "/settings"),
        MENU_TELEMETRY => navigate_main_window(app, "/telemetry"),
        MENU_QUIT => quit_app(app),
        _ => {}
    }
}

fn install_desktop_menus(app: &tauri::App) -> Result<()> {
    // About dialog metadata — shows icon, app name, version, and copyright in
    // the native macOS About panel. Icon falls back to ``None`` on Windows
    // (the predefined item ignores it there). Version comes from the crate so
    // it stays in lockstep with ``tauri.conf.json``'s ``version`` field, which
    // is enforced at build time by ``cargo tauri build``.
    let about_metadata = {
        let mut builder = AboutMetadataBuilder::new()
            .name(Some("OpenAgentd"))
            .version(Some(env!("CARGO_PKG_VERSION")))
            .copyright(Some("Copyright (c) 2025 OpenAgentd contributors"))
            .website(Some("https://github.com/lthoangg/openagentd"))
            .website_label(Some("openagentd on GitHub"));
        if let Some(icon) = app.default_window_icon() {
            builder = builder.icon(Some(icon.clone()));
        }
        builder.build()
    };
    let app_about = PredefinedMenuItem::about(
        app,
        Some("About OpenAgentd"),
        Some(about_metadata),
    )?;

    let app_show = MenuItem::with_id(app, MENU_SHOW, "Show OpenAgentd", true, None::<&str>)?;
    let app_settings = MenuItem::with_id(app, MENU_SETTINGS, "Settings", true, None::<&str>)?;
    let app_telemetry = MenuItem::with_id(app, MENU_TELEMETRY, "Telemetry", true, None::<&str>)?;
    let app_quit = MenuItem::with_id(app, MENU_QUIT, "Quit OpenAgentd", true, None::<&str>)?;
    let file_chat = MenuItem::with_id(app, MENU_CHAT, "Chat", true, None::<&str>)?;
    let file_coding = MenuItem::with_id(app, MENU_CODING, "Coding", true, None::<&str>)?;
    let file_quit = MenuItem::with_id(app, MENU_QUIT, "Quit OpenAgentd", true, None::<&str>)?;
    let view_settings = MenuItem::with_id(app, MENU_SETTINGS, "Settings", true, None::<&str>)?;
    let view_telemetry = MenuItem::with_id(app, MENU_TELEMETRY, "Telemetry", true, None::<&str>)?;

    // Edit submenu — required on macOS for native ⌘A/⌘C/⌘V/⌘X/⌘Z to reach the
    // webview's input fields. Without this submenu the webview never receives
    // the corresponding keyboard events. ``undo``/``redo`` are macOS-only and
    // silently no-op on Windows/Linux when invoked; including them keeps the
    // menu uniform across platforms.
    let edit_undo = PredefinedMenuItem::undo(app, None)?;
    let edit_redo = PredefinedMenuItem::redo(app, None)?;
    let edit_cut = PredefinedMenuItem::cut(app, None)?;
    let edit_copy = PredefinedMenuItem::copy(app, None)?;
    let edit_paste = PredefinedMenuItem::paste(app, None)?;
    let edit_select_all = PredefinedMenuItem::select_all(app, None)?;

    let app_menu = SubmenuBuilder::new(app, "OpenAgentd")
        .item(&app_about)
        .separator()
        .item(&app_show)
        .separator()
        .item(&app_settings)
        .item(&app_telemetry)
        .separator()
        .item(&app_quit)
        .build()?;
    let file_menu = SubmenuBuilder::new(app, "File")
        .item(&file_chat)
        .item(&file_coding)
        .separator()
        .item(&file_quit)
        .build()?;
    let edit_menu = SubmenuBuilder::new(app, "Edit")
        .item(&edit_undo)
        .item(&edit_redo)
        .separator()
        .item(&edit_cut)
        .item(&edit_copy)
        .item(&edit_paste)
        .item(&edit_select_all)
        .build()?;
    let view_menu = SubmenuBuilder::new(app, "View")
        .item(&view_settings)
        .item(&view_telemetry)
        .build()?;
    let window_menu = SubmenuBuilder::new(app, "Window")
        .minimize()
        .close_window_with_text("Hide to Tray")
        .build()?;
    let menu = Menu::with_items(
        app,
        &[&app_menu, &file_menu, &edit_menu, &view_menu, &window_menu],
    )?;
    app.set_menu(menu)?;

    let status = MenuItem::with_id(app, MENU_STATUS, "Status: Starting", false, None::<&str>)?;
    // ``session`` is informational only — kept disabled so the user can't
    // click it. Updated by ``update_tray_session`` whenever the frontend
    // reports a new active session/workspace via ``set_tray_session``.
    let session = MenuItem::with_id(app, MENU_SESSION, TRAY_SESSION_IDLE, false, None::<&str>)?;
    let tray_show = MenuItem::with_id(app, MENU_SHOW, "Show OpenAgentd", true, None::<&str>)?;
    let tray_chat = MenuItem::with_id(app, MENU_CHAT, "Chat", true, None::<&str>)?;
    let tray_coding = MenuItem::with_id(app, MENU_CODING, "Coding", true, None::<&str>)?;
    let tray_settings = MenuItem::with_id(app, MENU_SETTINGS, "Settings", true, None::<&str>)?;
    let tray_telemetry = MenuItem::with_id(app, MENU_TELEMETRY, "Telemetry", true, None::<&str>)?;
    let tray_quit = MenuItem::with_id(app, MENU_QUIT, "Quit OpenAgentd", true, None::<&str>)?;
    let tray_menu = Menu::with_items(
        app,
        &[
            &status,
            &session,
            &PredefinedMenuItem::separator(app)?,
            &tray_show,
            &tray_chat,
            &tray_coding,
            &tray_settings,
            &tray_telemetry,
            &PredefinedMenuItem::separator(app)?,
            &tray_quit,
        ],
    )?;
    // Left-click on the tray icon opens the tray menu (showing live status
    // first) instead of summoning the main window. Users summon the window
    // explicitly via the "Show OpenAgentd" menu entry. This mirrors the
    // behaviour of utility menu-bar apps on macOS where the icon is a status
    // surface, not a launcher. ``show_menu_on_left_click(true)`` is the Tauri
    // v2 built-in for this; no custom click handler is needed.
    let mut tray = TrayIconBuilder::new()
        .menu(&tray_menu)
        .show_menu_on_left_click(true)
        .tooltip("OpenAgentd")
        .on_menu_event(|app, event| handle_desktop_menu(app, event.id().as_ref()));
    if let Some(icon) = app.default_window_icon() {
        tray = tray.icon(icon.clone()).icon_as_template(true);
    }
    tray.build(app)?;

    let state: tauri::State<'_, AppState> = app.state();
    tauri::async_runtime::block_on(async {
        state.tray_status.lock().await.replace(status);
        state.tray_session.lock().await.replace(session);
    });
    Ok(())
}

fn update_tray_status(app: &AppHandle, text: &str) {
    let state: tauri::State<'_, AppState> = app.state();
    let text = text.to_string();
    let status = state.tray_status.clone();
    tauri::async_runtime::spawn(async move {
        if let Some(item) = status.lock().await.as_ref() {
            let _ = item.set_text(text);
        }
    });
}

fn update_tray_session(app: &AppHandle, text: &str) {
    let state: tauri::State<'_, AppState> = app.state();
    let text = text.to_string();
    let session = state.tray_session.clone();
    tauri::async_runtime::spawn(async move {
        if let Some(item) = session.lock().await.as_ref() {
            let _ = item.set_text(text);
        }
    });
}

/// Frontend-callable command: updates the tray's session-label item.
///
/// The JS layer derives the label (mode prefix + session title or workspace
/// name) and pushes it here whenever the active session changes. Empty input
/// is normalised to the idle placeholder so the tray never shows a blank row.
/// Input length is hard-capped at ``TRAY_SESSION_MAX_LEN`` characters to keep
/// the menu width sane even if the frontend forgets to truncate.
#[tauri::command]
fn set_tray_session(app: AppHandle, text: String) -> Result<(), String> {
    let trimmed = text.trim();
    let label = if trimmed.is_empty() {
        TRAY_SESSION_IDLE.to_string()
    } else if trimmed.chars().count() > TRAY_SESSION_MAX_LEN {
        let mut s: String = trimmed.chars().take(TRAY_SESSION_MAX_LEN - 1).collect();
        s.push('…');
        s
    } else {
        trimmed.to_string()
    };
    update_tray_session(&app, &label);
    Ok(())
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
        update_tray_status(&app, "Status: Running (dev)");
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
    update_tray_status(&app, "Status: Running");

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
        quitting: Arc::new(AtomicBool::new(false)),
        tray_status: Arc::new(Mutex::new(None)),
        tray_session: Arc::new(Mutex::new(None)),
    };

    let log_plugin = tauri_plugin_log::Builder::new()
        .level(log::LevelFilter::Info)
        .build();

    tauri::Builder::default()
        .plugin(log_plugin)
        .plugin(tauri_plugin_dialog::init())
        .plugin(tauri_plugin_opener::init())
        .manage(state)
        .on_menu_event(|app, event| handle_desktop_menu(app, event.id().as_ref()))
        .invoke_handler(tauri::generate_handler![
            backend_health,
            backend_logs_path,
            open_macos_microphone_settings,
            set_tray_session
        ])
        .setup(|app| {
            install_desktop_menus(app)?;
            let handle = app.handle().clone();
            tauri::async_runtime::spawn(async move {
                if let Err(e) = start_backend_and_window(handle.clone()).await {
                    log::error!("failed to start backend: {e:#}");
                    update_tray_status(&handle, "Status: Error");
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
            RunEvent::WindowEvent {
                label,
                event: WindowEvent::CloseRequested { api, .. },
                ..
            } if label == MAIN_WINDOW => {
                let state: tauri::State<'_, AppState> = app.state();
                if !state.quitting.load(Ordering::SeqCst) {
                    api.prevent_close();
                    if let Some(window) = app.get_webview_window(MAIN_WINDOW) {
                        let _ = window.hide();
                    }
                }
            }
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
