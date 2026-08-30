# CLIProxyAPI Tauri GUI

Tauri is the Windows desktop host for the existing Dashboard Web UI. It starts `resources/dashboard/dashboard.exe`, waits for `127.0.0.1:8765`, then loads the Dashboard in the system WebView. Dashboard remains the sole owner of configuration, storage, Core, AccessGateway and MediaProxy lifecycle.

## Storage rules

Tauri resolves its storage root in this order:

1. `CLIPROXYAPI_STORAGE_DIR`, when explicitly set;
2. `CLIProxyAPI/storage/`, when running from this source workspace;
3. Windows AppData for a normal MSI/NSIS installation.

## Build

From this directory:

```powershell
npm install
npm run build:windows
```

`build:windows` loads the Visual Studio Build Tools MSVC environment. Before it runs, build the Dashboard and service resources, then stage them:

```powershell
.\scripts\stage-windows.ps1
npm run build:windows
```

## Resource staging

`src-tauri/resources/` is build output and is deliberately ignored by Git. `stage-windows.ps1` copies the PyInstaller Dashboard plus compiled Core, AccessGateway, MediaProxy and LocalPlugin artifacts into it.
