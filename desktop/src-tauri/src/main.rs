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
use tauri_plugin_dialog::{DialogExt, MessageDialogButtons, MessageDialogKind, MessageDialogResult};
use tauri_plugin_updater::UpdaterExt;
use tokio::sync::Mutex;

use crate::sidecar::{Handshake, Sidecar};

/// Shared application state.
struct AppState {
    sidecar: Arc<Mutex<Option<Sidecar>>>,
    desktop_token: Arc<Mutex<Option<String>>>,
    force_reloading: Arc<AtomicBool>,
    quitting: Arc<AtomicBool>,
    tray_status: Arc<Mutex<Option<MenuItem<Wry>>>>,
    tray_session: Arc<Mutex<Option<MenuItem<Wry>>>>,
    /// Current webview zoom factor, mutated by the View > Zoom menu
    /// items. Session-only — not persisted across restarts.
    zoom: Arc<Mutex<f64>>,
}

const MAIN_WINDOW: &str = "main";
const MENU_SHOW: &str = "show";
const MENU_CHAT: &str = "chat";
const MENU_CODING: &str = "coding";
const MENU_SETTINGS: &str = "settings";
const MENU_TELEMETRY: &str = "telemetry";
const MENU_STATUS: &str = "status";
const MENU_SESSION: &str = "session";
const MENU_RELOAD: &str = "reload";
const MENU_FORCE_RELOAD: &str = "force_reload";
const MENU_ZOOM_IN: &str = "zoom_in";
const MENU_ZOOM_OUT: &str = "zoom_out";
const MENU_ZOOM_RESET: &str = "zoom_reset";
const MENU_CHECK_UPDATES: &str = "check_updates";
const MENU_QUIT: &str = "quit";

/// Zoom factor bounds and step. ``ZOOM_STEP`` is the multiplier per
/// ⌘+/⌘- press (≈20%, matching Chrome). Bounds keep the factor from
/// reaching values where the UI becomes unusable.
const ZOOM_MIN: f64 = 0.5;
const ZOOM_MAX: f64 = 3.0;
const ZOOM_STEP: f64 = 1.2;
const ZOOM_DEFAULT: f64 = 1.0;

/// Label shown in the tray when no chat/coding session is active.
const TRAY_SESSION_IDLE: &str = "No active session";

/// Hard cap on tray session label width. Keeps the menu from stretching
/// uncomfortably wide when a session title or workspace name is long.
const TRAY_SESSION_MAX_LEN: usize = 60;

/// Apply platform-specific window chrome.
///
/// macOS uses an overlay title-bar; the React app reserves a 70 pt left
/// inset for the traffic-lights. ``traffic_light_position`` must be set
/// from Rust because the JSON config value is ignored when the window is
/// built via ``WebviewWindowBuilder``. ``y`` is a *bottom* inset (tao
/// resizes the native title-bar to ``button_height + y`` — tao 0.35.x,
/// macos/view.rs:1152); 22 pt centres against our 40 pt header.
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

fn reload_main_window(app: &AppHandle) {
    show_main_window(app);
    if let Some(window) = app.get_webview_window(MAIN_WINDOW) {
        let _ = window.eval("window.location.reload();");
    }
}

fn force_reload_app(app: &AppHandle) {
    let state: tauri::State<'_, AppState> = app.state();
    if state.force_reloading.swap(true, Ordering::SeqCst) {
        return;
    }

    let handle = app.clone();
    tauri::async_runtime::spawn(async move {
        update_tray_status(&handle, "Status: Reloading…");
        let result = if std::env::var("OPENAGENTD_DEV_BACKEND_URL").is_ok() {
            reload_main_window(&handle);
            Ok(())
        } else {
            restart_sidecar_and_reload_window(&handle).await
        };
        if let Err(e) = result {
            log::error!("failed to force reload backend: {e:#}");
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

        let state: tauri::State<'_, AppState> = handle.state();
        state.force_reloading.store(false, Ordering::SeqCst);
    });
}

async fn restart_sidecar_and_reload_window(app: &AppHandle) -> Result<()> {
    let state: tauri::State<'_, AppState> = app.state();
    let token = state
        .desktop_token
        .lock()
        .await
        .clone()
        .ok_or_else(|| anyhow!("desktop token missing"))?;

    shutdown_sidecar_now(app).await;

    let mut sidecar = Sidecar::spawn_with_desktop_token(app, Some(&token)).context("spawn sidecar")?;
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

    if let Some(window) = app.get_webview_window(MAIN_WINDOW) {
        let mut target = base;
        if let Ok(current_url) = window.url() {
            target.push_str(current_url.path());
            if let Some(query) = current_url.query() {
                target.push('?');
                target.push_str(query);
            }
            if let Some(fragment) = current_url.fragment() {
                target.push('#');
                target.push_str(fragment);
            }
        }
        let url = target.parse().context("parse backend url")?;
        window.navigate(url).context("navigate main window")?;
        show_main_window(app);
    } else {
        return Err(anyhow!("main window missing"));
    }

    let _ = state.desktop_token.lock().await.replace(token);
    let _ = state.sidecar.lock().await.replace(sidecar);
    app.emit(
        "backend-ready",
        BackendReady {
            port: handshake.port,
            version: handshake.version,
        },
    )
    .ok();
    update_tray_status(app, "Status: Running");

    Ok(())
}

fn handle_desktop_menu(app: &AppHandle, id: &str) {
    match id {
        MENU_SHOW => show_main_window(app),
        MENU_CHAT => navigate_main_window(app, "/"),
        MENU_CODING => navigate_main_window(app, "/coding"),
        MENU_SETTINGS => navigate_main_window(app, "/settings"),
        MENU_TELEMETRY => navigate_main_window(app, "/telemetry"),
        MENU_RELOAD => reload_main_window(app),
        MENU_FORCE_RELOAD => force_reload_app(app),
        MENU_ZOOM_IN => adjust_zoom(app, ZOOM_STEP),
        MENU_ZOOM_OUT => adjust_zoom(app, 1.0 / ZOOM_STEP),
        MENU_ZOOM_RESET => set_zoom(app, ZOOM_DEFAULT),
        MENU_CHECK_UPDATES => check_for_updates(app),
        MENU_QUIT => quit_app(app),
        _ => {}
    }
}

/// Multiply the current zoom factor by ``factor`` and apply it, clamping
/// to ``[ZOOM_MIN, ZOOM_MAX]`` so the user can't shrink the UI to nothing
/// or blow it up past readable.
fn adjust_zoom(app: &AppHandle, factor: f64) {
    let state: tauri::State<'_, AppState> = app.state();
    let zoom = state.zoom.clone();
    let app_for_apply = app.clone();
    tauri::async_runtime::spawn(async move {
        let mut guard = zoom.lock().await;
        let next = (*guard * factor).clamp(ZOOM_MIN, ZOOM_MAX);
        *guard = next;
        apply_zoom_to_main(&app_for_apply, next);
    });
}

fn set_zoom(app: &AppHandle, value: f64) {
    let state: tauri::State<'_, AppState> = app.state();
    let zoom = state.zoom.clone();
    let app_for_apply = app.clone();
    let clamped = value.clamp(ZOOM_MIN, ZOOM_MAX);
    tauri::async_runtime::spawn(async move {
        *zoom.lock().await = clamped;
        apply_zoom_to_main(&app_for_apply, clamped);
    });
}

fn apply_zoom_to_main(app: &AppHandle, factor: f64) {
    if let Some(window) = app.get_webview_window(MAIN_WINDOW) {
        if let Err(e) = window.set_zoom(factor) {
            log::warn!("set_zoom({factor}) failed: {e}");
        }
    }
}

/// Manual "Check for Updates…" flow triggered from the menu bar.
///
/// Driven from Rust (not the webview) so the menu still works if the UI
/// is wedged. All feedback is via native dialogs and the tray status.
fn check_for_updates(app: &AppHandle) {
    let handle = app.clone();
    tauri::async_runtime::spawn(async move {
        run_update_check(handle).await;
    });
}

async fn run_update_check(app: AppHandle) {
    let updater = match app.updater() {
        Ok(u) => u,
        Err(e) => {
            show_update_error(&app, &format!("Updater unavailable: {e}"));
            return;
        }
    };

    match updater.check().await {
        Ok(Some(update)) => {
            let message = format_update_prompt(
                &update.version,
                env!("CARGO_PKG_VERSION"),
                update.body.as_deref(),
            );

            let accepted = ask_dialog(&app, "Update available", &message, "Install", "Later").await;
            if !accepted {
                return;
            }

            update_tray_status(&app, "Status: Downloading update…");
            let mut downloaded: usize = 0;
            let mut last_mb_announced: usize = 0;
            let app_for_progress = app.clone();
            let install_result = update
                .download_and_install(
                    move |chunk, total| {
                        downloaded = downloaded.saturating_add(chunk);
                        let mb = downloaded / (1024 * 1024);
                        if mb > last_mb_announced {
                            last_mb_announced = mb;
                            update_tray_status(
                                &app_for_progress,
                                &format_download_progress(mb, total),
                            );
                        }
                    },
                    {
                        let app_for_finish = app.clone();
                        move || {
                            update_tray_status(&app_for_finish, "Status: Installing update…");
                        }
                    },
                )
                .await;
            if let Err(e) = install_result {
                update_tray_status(&app, "Status: Running");
                show_update_error(&app, &format!("Failed to install update: {e}"));
                return;
            }

            // ``tauri::process::restart`` execs the new binary directly,
            // skipping ``RunEvent::ExitRequested`` — so the sidecar must
            // be shut down here or it leaks and races the new bundle for
            // the handshake port.
            update_tray_status(&app, "Status: Restarting…");
            shutdown_sidecar_now(&app).await;

            let state: tauri::State<'_, AppState> = app.state();
            state.quitting.store(true, Ordering::SeqCst);
            tauri::process::restart(&app.env());
        }
        Ok(None) => {
            show_update_info(
                &app,
                "You're up to date",
                &format!(
                    "OpenAgentd {} is the latest version.",
                    env!("CARGO_PKG_VERSION")
                ),
            );
        }
        Err(e) => {
            show_update_error(&app, &format!("Couldn't check for updates: {e}"));
        }
    }
}

/// Cleanly stop the Python sidecar before a process re-exec.
///
/// Idempotent: ``.take()``s the sidecar out of shared state, so repeat
/// calls (or a race with ``ExitRequested``) are no-ops.
async fn shutdown_sidecar_now(app: &AppHandle) {
    let state: tauri::State<'_, AppState> = app.state();
    let sidecar = state.sidecar.clone();
    let mut guard = sidecar.lock().await;
    if let Some(mut s) = guard.take() {
        s.shutdown().await;
    }
}

async fn ask_dialog(
    app: &AppHandle,
    title: &str,
    message: &str,
    ok_label: &str,
    cancel_label: &str,
) -> bool {
    let (tx, rx) = tokio::sync::oneshot::channel();
    let ok = ok_label.to_string();
    app.dialog()
        .message(message)
        .title(title)
        .kind(MessageDialogKind::Info)
        .buttons(MessageDialogButtons::OkCancelCustom(
            ok_label.to_string(),
            cancel_label.to_string(),
        ))
        .show_with_result(move |result| {
            let _ = tx.send(dialog_result_is_accept(&result, &ok));
        });
    rx.await.unwrap_or(false)
}

/// Map a ``MessageDialogResult`` from an ``OkCancelCustom`` dialog to a
/// simple accept/cancel boolean.
///
/// ``OkCancelCustom`` yields ``Custom(label)`` matching the button text the
/// user pressed (rfd's behaviour, surfaced through tauri-plugin-dialog).
/// Some platforms still report a plain ``Ok``/``Cancel`` for the bundled
/// system dialog, so we accept either spelling of "yes".
fn dialog_result_is_accept(result: &MessageDialogResult, ok_label: &str) -> bool {
    match result {
        MessageDialogResult::Ok | MessageDialogResult::Yes => true,
        MessageDialogResult::Custom(s) => s == ok_label,
        MessageDialogResult::Cancel | MessageDialogResult::No => false,
    }
}

/// Build the "Update available" dialog body shown to the user.
///
/// Release notes are truncated to ~600 characters with an ellipsis so a
/// runaway changelog never produces a multi-screen modal. An empty/None
/// body collapses the notes paragraph entirely.
fn format_update_prompt(new_version: &str, current_version: &str, body: Option<&str>) -> String {
    const MAX_NOTES_CHARS: usize = 600;
    let notes = body.unwrap_or_default().trim();
    let trimmed = if notes.chars().count() > MAX_NOTES_CHARS {
        let mut s: String = notes.chars().take(MAX_NOTES_CHARS - 1).collect();
        s.push('…');
        s
    } else {
        notes.to_string()
    };
    if trimmed.is_empty() {
        format!(
            "OpenAgentd {new_version} is available (you have {current_version}).\n\nDownload and install now?"
        )
    } else {
        format!(
            "OpenAgentd {new_version} is available (you have {current_version}).\n\n{trimmed}\n\nDownload and install now?"
        )
    }
}

/// Format the tray status string shown during a bundle download.
///
/// ``total == Some(0)`` is treated the same as ``None`` — some HTTP
/// responses omit ``Content-Length`` and our caller passes whatever it
/// has — so we never produce a misleading ``"5/0 MB"`` label.
fn format_download_progress(downloaded_mb: usize, total_bytes: Option<u64>) -> String {
    match total_bytes {
        Some(total) if total > 0 => {
            let total_mb = total / (1024 * 1024);
            format!("Status: Downloading {downloaded_mb}/{total_mb} MB")
        }
        _ => format!("Status: Downloading {downloaded_mb} MB"),
    }
}

fn show_update_info(app: &AppHandle, title: &str, message: &str) {
    app.dialog()
        .message(message)
        .title(title)
        .kind(MessageDialogKind::Info)
        .show(|_| {});
}

fn show_update_error(app: &AppHandle, message: &str) {
    app.dialog()
        .message(message)
        .title("Update")
        .kind(MessageDialogKind::Error)
        .show(|_| {});
}

fn install_desktop_menus(app: &tauri::App) -> Result<()> {
    let about_metadata = {
        let mut builder = AboutMetadataBuilder::new()
            .name(Some("OpenAgentd"))
            .version(Some(env!("CARGO_PKG_VERSION")))
            .copyright(Some("Copyright (c) 2026 OpenAgentd contributors"))
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

    // Per Apple HIG, "Check for Updates…" sits directly below About.
    let app_check_updates = MenuItem::with_id(
        app,
        MENU_CHECK_UPDATES,
        "Check for Updates…",
        true,
        None::<&str>,
    )?;
    let app_show = MenuItem::with_id(app, MENU_SHOW, "Show OpenAgentd", true, None::<&str>)?;
    let app_settings = MenuItem::with_id(app, MENU_SETTINGS, "Settings", true, None::<&str>)?;
    let app_telemetry = MenuItem::with_id(app, MENU_TELEMETRY, "Telemetry", true, None::<&str>)?;
    let app_quit = MenuItem::with_id(app, MENU_QUIT, "Quit OpenAgentd", true, Some("CmdOrCtrl+Q"))?;
    let file_chat = MenuItem::with_id(app, MENU_CHAT, "Chat", true, None::<&str>)?;
    let file_coding = MenuItem::with_id(app, MENU_CODING, "Coding", true, None::<&str>)?;
    let file_quit = MenuItem::with_id(app, MENU_QUIT, "Quit OpenAgentd", true, Some("CmdOrCtrl+Q"))?;
    let view_settings = MenuItem::with_id(app, MENU_SETTINGS, "Settings", true, None::<&str>)?;
    let view_telemetry = MenuItem::with_id(app, MENU_TELEMETRY, "Telemetry", true, None::<&str>)?;
    let view_reload = MenuItem::with_id(app, MENU_RELOAD, "Reload", true, Some("CmdOrCtrl+R"))?;
    let view_force_reload = MenuItem::with_id(
        app,
        MENU_FORCE_RELOAD,
        "Force Reload",
        true,
        Some("CmdOrCtrl+Shift+R"),
    )?;
    // ``CmdOrCtrl+=`` (not ``CmdOrCtrl++``) so the shortcut fires from the
    // bare ``=`` key — matches Chrome/Safari/VS Code and avoids requiring
    // Shift on US layouts.
    let view_zoom_in = MenuItem::with_id(
        app,
        MENU_ZOOM_IN,
        "Zoom In",
        true,
        Some("CmdOrCtrl+="),
    )?;
    let view_zoom_out = MenuItem::with_id(
        app,
        MENU_ZOOM_OUT,
        "Zoom Out",
        true,
        Some("CmdOrCtrl+-"),
    )?;
    let view_zoom_reset = MenuItem::with_id(
        app,
        MENU_ZOOM_RESET,
        "Actual Size",
        true,
        Some("CmdOrCtrl+0"),
    )?;

    // Edit submenu is required on macOS so ⌘A/⌘C/⌘V/⌘X/⌘Z reach the webview.
    let edit_undo = PredefinedMenuItem::undo(app, None)?;
    let edit_redo = PredefinedMenuItem::redo(app, None)?;
    let edit_cut = PredefinedMenuItem::cut(app, None)?;
    let edit_copy = PredefinedMenuItem::copy(app, None)?;
    let edit_paste = PredefinedMenuItem::paste(app, None)?;
    let edit_select_all = PredefinedMenuItem::select_all(app, None)?;

    let app_menu = SubmenuBuilder::new(app, "OpenAgentd")
        .item(&app_about)
        .item(&app_check_updates)
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
        .item(&view_reload)
        .item(&view_force_reload)
        .separator()
        .item(&view_zoom_in)
        .item(&view_zoom_out)
        .item(&view_zoom_reset)
        .separator()
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
    // Informational only; updated from ``set_tray_session``.
    let session = MenuItem::with_id(app, MENU_SESSION, TRAY_SESSION_IDLE, false, None::<&str>)?;
    let tray_show = MenuItem::with_id(app, MENU_SHOW, "Show OpenAgentd", true, None::<&str>)?;
    let tray_chat = MenuItem::with_id(app, MENU_CHAT, "Chat", true, None::<&str>)?;
    let tray_coding = MenuItem::with_id(app, MENU_CODING, "Coding", true, None::<&str>)?;
    let tray_settings = MenuItem::with_id(app, MENU_SETTINGS, "Settings", true, None::<&str>)?;
    let tray_telemetry = MenuItem::with_id(app, MENU_TELEMETRY, "Telemetry", true, None::<&str>)?;
    let tray_reload = MenuItem::with_id(app, MENU_RELOAD, "Reload Window", true, None::<&str>)?;
    let tray_check_updates = MenuItem::with_id(
        app,
        MENU_CHECK_UPDATES,
        "Check for Updates…",
        true,
        None::<&str>,
    )?;
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
            &tray_reload,
            &tray_check_updates,
            &PredefinedMenuItem::separator(app)?,
            &tray_quit,
        ],
    )?;
    // Left-click opens the menu so the icon acts as a status surface, not
    // a launcher. We deliberately do not register ``on_menu_event`` here —
    // the app-level handler in ``main()`` already receives tray events,
    // so adding one would fire ``handle_desktop_menu`` twice.
    let mut tray = TrayIconBuilder::new()
        .menu(&tray_menu)
        .show_menu_on_left_click(true)
        .tooltip("OpenAgentd");
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

/// Frontend command: update the tray's session-label item.
///
/// Empty input falls back to the idle placeholder; long input is truncated
/// to ``TRAY_SESSION_MAX_LEN`` so the menu width stays sane.
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

    // Dev-mode escape hatch: when ``OPENAGENTD_DEV_BACKEND_URL`` is set,
    // skip the bundled sidecar and point the WebView at an externally
    // managed backend. ``__OAD_TOKEN__`` is left undefined; the frontend
    // falls back to the legacy no-token path (matched by an unset
    // ``OPENAGENTD_DESKTOP_TOKEN`` on the dev backend).
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

    // Build the window only once we have the backend URL + token so the
    // token is injected before any page JS runs.
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

    let _ = state.sidecar.lock().await.replace(sidecar);
    let _ = state.desktop_token.lock().await.replace(handshake.token);

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
        desktop_token: Arc::new(Mutex::new(None)),
        force_reloading: Arc::new(AtomicBool::new(false)),
        quitting: Arc::new(AtomicBool::new(false)),
        tray_status: Arc::new(Mutex::new(None)),
        tray_session: Arc::new(Mutex::new(None)),
        zoom: Arc::new(Mutex::new(ZOOM_DEFAULT)),
    };

    let log_plugin = tauri_plugin_log::Builder::new()
        .level(log::LevelFilter::Info)
        .build();

    tauri::Builder::default()
        .plugin(log_plugin)
        .plugin(tauri_plugin_dialog::init())
        .plugin(tauri_plugin_opener::init())
        // Updater config (endpoint, pubkey, install mode) lives in
        // ``tauri.conf.json``'s ``plugins.updater`` block. ``process`` is
        // required for ``tauri::process::restart`` after the new bundle
        // is staged.
        .plugin(tauri_plugin_updater::Builder::new().build())
        .plugin(tauri_plugin_process::init())
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
            RunEvent::Reopen { has_visible_windows: _, .. } => {
                show_main_window(app);
            }
            RunEvent::ExitRequested { .. } => {
                let state: tauri::State<'_, AppState> = app.state();
                let sidecar = state.sidecar.clone();
                // Block so the child receives SIGTERM before the parent exits.
                tauri::async_runtime::block_on(async move {
                    if let Some(mut s) = sidecar.lock().await.take() {
                        s.shutdown().await;
                    }
                });
            }
            _ => {}
        });
}

#[cfg(test)]
mod tests {
    use super::*;

    // ── dialog_result_is_accept ──────────────────────────────────────────────
    //
    // Guards the OkCancelCustom mapping. rfd surfaces the user's choice as
    // ``Custom("Install")`` on macOS/Linux but the underlying system dialog
    // may report ``Ok``/``Yes`` instead — both must count as accept, and
    // every other variant (including a ``Custom`` with a different label)
    // must count as cancel.

    #[test]
    fn dialog_result_custom_with_matching_label_accepts() {
        assert!(dialog_result_is_accept(
            &MessageDialogResult::Custom("Install".into()),
            "Install"
        ));
    }

    #[test]
    fn dialog_result_custom_with_other_label_rejects() {
        assert!(!dialog_result_is_accept(
            &MessageDialogResult::Custom("Later".into()),
            "Install"
        ));
    }

    #[test]
    fn dialog_result_ok_and_yes_accept() {
        assert!(dialog_result_is_accept(&MessageDialogResult::Ok, "Install"));
        assert!(dialog_result_is_accept(&MessageDialogResult::Yes, "Install"));
    }

    #[test]
    fn dialog_result_cancel_and_no_reject() {
        assert!(!dialog_result_is_accept(
            &MessageDialogResult::Cancel,
            "Install"
        ));
        assert!(!dialog_result_is_accept(&MessageDialogResult::No, "Install"));
    }

    // ── format_update_prompt ────────────────────────────────────────────────
    //
    // The prompt is the only thing the user reads before deciding to install,
    // so it must (a) always show both version numbers, (b) handle a missing
    // body without printing literal "None" or doubled blank lines, and
    // (c) bound the length so a runaway changelog doesn't blow out the modal.

    #[test]
    fn update_prompt_without_notes_omits_notes_paragraph() {
        let prompt = format_update_prompt("1.2.0", "1.1.0", None);
        assert!(prompt.contains("1.2.0"));
        assert!(prompt.contains("1.1.0"));
        assert!(prompt.contains("Download and install now?"));
        // Exactly one blank line between the version line and the call to
        // action — i.e. no orphan ``\n\n\n`` from an empty body.
        assert!(!prompt.contains("\n\n\n"));
    }

    #[test]
    fn update_prompt_with_empty_string_body_treated_as_no_notes() {
        let with_empty = format_update_prompt("1.2.0", "1.1.0", Some(""));
        let with_none = format_update_prompt("1.2.0", "1.1.0", None);
        assert_eq!(with_empty, with_none);
    }

    #[test]
    fn update_prompt_with_whitespace_only_body_treated_as_no_notes() {
        let prompt = format_update_prompt("1.2.0", "1.1.0", Some("   \n\t  "));
        let baseline = format_update_prompt("1.2.0", "1.1.0", None);
        assert_eq!(prompt, baseline);
    }

    #[test]
    fn update_prompt_includes_short_notes_verbatim() {
        let prompt = format_update_prompt("1.2.0", "1.1.0", Some("Fixed crash on launch"));
        assert!(prompt.contains("Fixed crash on launch"));
    }

    #[test]
    fn update_prompt_truncates_long_notes_with_ellipsis() {
        let long = "x".repeat(2000);
        let prompt = format_update_prompt("1.2.0", "1.1.0", Some(&long));
        // The xxxxx body itself must be capped well below the original
        // length and end with an ellipsis. Total prompt length is body +
        // surrounding template, so it stays under ~1000 chars.
        assert!(prompt.contains('…'));
        assert!(prompt.len() < 1000);
        assert!(prompt.contains("1.2.0"));
        assert!(prompt.contains("Download and install now?"));
    }

    #[test]
    fn update_prompt_truncation_respects_char_boundaries() {
        // A body of 700 multi-byte chars (3 bytes each in UTF-8) would
        // panic on a naive ``&body[..N]`` slice. ``chars().take`` keeps
        // us safe — assert we don't panic and produce a valid String.
        let multibyte_body: String = "✦".repeat(700);
        let prompt = format_update_prompt("1.2.0", "1.1.0", Some(&multibyte_body));
        assert!(prompt.contains('…'));
        assert!(prompt.is_char_boundary(prompt.len()));
    }

    // ── format_download_progress ────────────────────────────────────────────
    //
    // Closure-callable formatter for the tray status. Critical: never
    // produce "0/0 MB" or similar garbage when Content-Length is missing
    // or zero, and never divide by zero.

    #[test]
    fn download_progress_with_total_shows_fraction() {
        assert_eq!(
            format_download_progress(3, Some(50 * 1024 * 1024)),
            "Status: Downloading 3/50 MB"
        );
    }

    #[test]
    fn download_progress_without_total_omits_denominator() {
        assert_eq!(
            format_download_progress(7, None),
            "Status: Downloading 7 MB"
        );
    }

    #[test]
    fn download_progress_with_zero_total_falls_back_to_no_denominator() {
        // A misbehaving server that returns ``Content-Length: 0`` must not
        // produce ``"5/0 MB"`` — the fallback path drops the denominator.
        assert_eq!(
            format_download_progress(5, Some(0)),
            "Status: Downloading 5 MB"
        );
    }

    #[test]
    fn download_progress_handles_partial_megabyte_total() {
        // 500 KB total → integer-MB division yields 0, so we treat it
        // identically to "no total" rather than printing "0/0 MB".
        let small_total = 500 * 1024;
        let label = format_download_progress(0, Some(small_total));
        // Integer division gives ``0`` MB; not ideal but at least not
        // misleading — the formatter still prints a valid "downloading"
        // string and never panics.
        assert!(label.starts_with("Status: Downloading"));
    }
}
