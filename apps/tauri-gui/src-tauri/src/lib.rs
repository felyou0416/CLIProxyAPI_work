use std::{
    net::TcpStream,
    process::{Child, Command, Stdio},
    sync::Mutex,
    thread,
    time::{Duration, Instant},
};

use tauri::{
    menu::{Menu, MenuItem},
    tray::TrayIconBuilder,
    AppHandle, Manager, RunEvent, WebviewUrl, WebviewWindowBuilder,
};

const DASHBOARD_PORT: u16 = 8765;
const DASHBOARD_URL: &str = "http://127.0.0.1:8765";
const READY_TIMEOUT: Duration = Duration::from_secs(20);

struct DashboardProcess(Mutex<Option<Child>>);

fn resource_root(app: &AppHandle) -> Result<std::path::PathBuf, String> {
    let resource_dir = app
        .path()
        .resource_dir()
        .map_err(|error| error.to_string())?;
    if resource_dir.join("dashboard").is_dir() {
        return Ok(resource_dir);
    }

    let development_resources = resource_dir.join("resources");
    if development_resources.join("dashboard").is_dir() {
        return Ok(development_resources);
    }
    Ok(resource_dir)
}

fn dashboard_binary(app: &AppHandle) -> Result<std::path::PathBuf, String> {
    let filename = if cfg!(target_os = "windows") {
        "dashboard.exe"
    } else {
        "dashboard"
    };
    Ok(resource_root(app)?.join("dashboard").join(filename))
}

fn workspace_storage_dir(resource_dir: &std::path::Path) -> Option<std::path::PathBuf> {
    resource_dir.ancestors().find_map(|ancestor| {
        let storage_dir = ancestor.join("CLIProxyAPI").join("storage");
        storage_dir.is_dir().then_some(storage_dir)
    })
}

fn storage_dir(
    app: &AppHandle,
    resource_dir: &std::path::Path,
) -> Result<std::path::PathBuf, String> {
    if let Some(path) = std::env::var_os("CLIPROXYAPI_STORAGE_DIR") {
        return Ok(std::path::PathBuf::from(path));
    }
    if let Some(path) = workspace_storage_dir(resource_dir) {
        return Ok(path);
    }
    app.path()
        .app_data_dir()
        .map(|path| path.join("storage"))
        .map_err(|error| error.to_string())
}

fn dashboard_ready() -> bool {
    TcpStream::connect_timeout(
        &format!("127.0.0.1:{DASHBOARD_PORT}")
            .parse()
            .expect("valid dashboard address"),
        Duration::from_millis(250),
    )
    .is_ok()
}

fn start_dashboard(app: &AppHandle) -> Result<bool, String> {
    if dashboard_ready() {
        if std::env::var_os("CLIPROXYAPI_REUSE_EXISTING_DASHBOARD").is_some() {
            return Ok(false);
        }
        return Err(format!(
            "A Dashboard is already listening at {DASHBOARD_URL}. Stop it before starting this application, or launch the source workspace with start.ps1."
        ));
    }

    let binary = dashboard_binary(app)?;
    if !binary.is_file() {
        return Err(format!(
            "Dashboard sidecar is missing: {}",
            binary.display()
        ));
    }
    let resource_dir = resource_root(app)?;
    let storage_dir = storage_dir(app, &resource_dir)?;
    std::fs::create_dir_all(&storage_dir).map_err(|error| error.to_string())?;

    let cli_binary = resource_dir.join(if cfg!(target_os = "windows") {
        "cli-proxy-api.exe"
    } else {
        "cli-proxy-api"
    });
    let gateway_binary =
        resource_dir
            .join("CLIProxyAPI-AccessGateway")
            .join(if cfg!(target_os = "windows") {
                "cli-access-gateway.exe"
            } else {
                "cli-access-gateway"
            });
    let media_binary =
        resource_dir
            .join("CLIProxyAPI-MediaProxy")
            .join(if cfg!(target_os = "windows") {
                "cli-media-proxy.exe"
            } else {
                "cli-media-proxy"
            });
    let child = Command::new(binary)
        .current_dir(resource_dir.join("dashboard"))
        .env("CLIPROXYAPI_ROOT", &resource_dir)
        .env("CLIPROXYAPI_STORAGE_DIR", &storage_dir)
        .env("RELAYX_CLI_BINARY", cli_binary)
        .env("CLIPROXYAPI_ACCESS_GATEWAY_BINARY", gateway_binary)
        .env("CLIPROXYAPI_MEDIA_PROXY_BINARY", media_binary)
        .env("CLIPROXYAPI_PLUGIN_DIR", resource_dir.join("plugins"))
        .env("RELAYX_DASHBOARD_ROOT", resource_dir.join("dashboard"))
        .env("CLIPROXYAPI_DASHBOARD_HOST", "127.0.0.1")
        .env("CLIPROXYAPI_DASHBOARD_PORT", DASHBOARD_PORT.to_string())
        .env("CLIPROXYAPI_AUTO_START", "1")
        .stdout(Stdio::null())
        .stderr(Stdio::null())
        .spawn()
        .map_err(|error| format!("Failed to start Dashboard sidecar: {error}"))?;

    app.manage(DashboardProcess(Mutex::new(Some(child))));
    Ok(true)
}

fn wait_for_dashboard() -> Result<(), String> {
    let deadline = Instant::now() + READY_TIMEOUT;
    while Instant::now() < deadline {
        if dashboard_ready() {
            return Ok(());
        }
        thread::sleep(Duration::from_millis(200));
    }
    Err(format!(
        "Dashboard did not become ready at {DASHBOARD_URL} within {} seconds",
        READY_TIMEOUT.as_secs()
    ))
}

fn show_dashboard(app: &AppHandle) -> Result<(), String> {
    if let Some(window) = app.get_webview_window("main") {
        window.show().map_err(|error| error.to_string())?;
        window.set_focus().map_err(|error| error.to_string())?;
        return Ok(());
    }
    WebviewWindowBuilder::new(
        app,
        "main",
        WebviewUrl::External(
            DASHBOARD_URL
                .parse::<tauri::Url>()
                .map_err(|error| error.to_string())?,
        ),
    )
    .title("CLIProxyAPI Dashboard")
    .inner_size(1400.0, 900.0)
    .min_inner_size(960.0, 600.0)
    .build()
    .map_err(|error| error.to_string())?;
    Ok(())
}

fn stop_owned_dashboard(app: &AppHandle) {
    let Some(state) = app.try_state::<DashboardProcess>() else {
        return;
    };
    let Ok(mut child) = state.0.lock() else {
        return;
    };
    if let Some(process) = child.as_mut() {
        let _ = process.kill();
        let _ = process.wait();
    }
    *child = None;
}

#[cfg(test)]
mod tests {
    use super::workspace_storage_dir;

    fn test_root(name: &str) -> std::path::PathBuf {
        std::env::temp_dir().join(format!("cliproxyapi-tauri-{name}-{}", std::process::id()))
    }

    #[test]
    fn finds_workspace_storage_from_release_resources() {
        let root = test_root("workspace-storage");
        let resources = root
            .join("apps")
            .join("tauri-gui")
            .join("target")
            .join("release")
            .join("resources");
        let storage = root.join("CLIProxyAPI").join("storage");
        std::fs::create_dir_all(&resources).unwrap();
        std::fs::create_dir_all(&storage).unwrap();

        assert_eq!(workspace_storage_dir(&resources), Some(storage));
        std::fs::remove_dir_all(root).unwrap();
    }
}

pub fn run() {
    tauri::Builder::default()
        .setup(|app| {
            let handle = app.handle().clone();
            start_dashboard(&handle).map_err(std::io::Error::other)?;
            if let Err(error) = wait_for_dashboard() {
                stop_owned_dashboard(&handle);
                return Err(std::io::Error::other(error).into());
            }
            show_dashboard(&handle).map_err(std::io::Error::other)?;

            let show = MenuItem::with_id(app, "show", "Show Dashboard", true, None::<&str>)?;
            let quit = MenuItem::with_id(app, "quit", "Quit", true, None::<&str>)?;
            let menu = Menu::with_items(app, &[&show, &quit])?;
            TrayIconBuilder::new()
                .menu(&menu)
                .on_menu_event(|app, event| match event.id.as_ref() {
                    "show" => {
                        let _ = show_dashboard(app);
                    }
                    "quit" => app.exit(0),
                    _ => {}
                })
                .on_tray_icon_event(|tray, event| {
                    if let tauri::tray::TrayIconEvent::Click { .. } = event {
                        let _ = show_dashboard(tray.app_handle());
                    }
                })
                .build(app)?;
            Ok(())
        })
        .build(tauri::generate_context!())
        .expect("error while building CLIProxyAPI Tauri shell")
        .run(|app, event| {
            if let RunEvent::ExitRequested { .. } = event {
                stop_owned_dashboard(app);
            }
        });
}
