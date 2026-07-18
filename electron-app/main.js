const { app, BrowserWindow, Tray, Menu, nativeImage } = require('electron');
const { spawn } = require('child_process');
const path = require('path');
const fs = require('fs');
const net = require('net');
const http = require('http');

// ─── Single instance ───────────────────────────────────────────────
const gotTheLock = app.requestSingleInstanceLock();
if (!gotTheLock) {
  app.quit();
  process.exit(0);
}

// ─── State ─────────────────────────────────────────────────────────
let dashboardProcess = null;
let mainWindow = null;
let tray = null;
let isQuitting = false;

const DASHBOARD_PORT = parseInt(process.env.CLIPROXYAPI_DASHBOARD_PORT || '8765', 10);
const WINDOW_STATE_FILE = 'window-state.json';

// ─── Paths ─────────────────────────────────────────────────────────
function getResourcesPath() {
  return app.isPackaged
    ? process.resourcesPath
    : path.join(__dirname, 'resources');
}

function getUserDataPath() {
  return app.getPath('userData');
}

function getStoragePath() {
  return path.join(getUserDataPath(), 'storage');
}

function getStateFilePath() {
  return path.join(getStoragePath(), 'runtime', 'state.json');
}

function getWindowStatePath() {
  return path.join(getUserDataPath(), WINDOW_STATE_FILE);
}

function getIconPath(name) {
  return path.join(__dirname, 'assets', name);
}

// ─── App preferences (shared with Dashboard settings) ──────────────
function readAppSettings() {
  const defaults = {
    minimize_tray: true,
  };
  try {
    const statePath = getStateFilePath();
    if (!fs.existsSync(statePath)) return defaults;
    const state = JSON.parse(fs.readFileSync(statePath, 'utf-8'));
    return {
      minimize_tray: state.minimize_tray !== false && state.minimize_tray !== 0 && state.minimize_tray !== '0' && state.minimize_tray !== 'false',
    };
  } catch {
    return defaults;
  }
}

function shouldMinimizeToTray() {
  return !!readAppSettings().minimize_tray;
}

// ─── Window bounds ─────────────────────────────────────────────────
function loadWindowState() {
  try {
    const file = getWindowStatePath();
    if (!fs.existsSync(file)) return null;
    const state = JSON.parse(fs.readFileSync(file, 'utf-8'));
    if (!state || typeof state !== 'object') return null;
    return state;
  } catch {
    return null;
  }
}

function saveWindowState() {
  if (!mainWindow || mainWindow.isDestroyed()) return;
  try {
    const bounds = mainWindow.getBounds();
    const state = {
      x: bounds.x,
      y: bounds.y,
      width: bounds.width,
      height: bounds.height,
      isMaximized: mainWindow.isMaximized(),
    };
    fs.writeFileSync(getWindowStatePath(), JSON.stringify(state), 'utf-8');
  } catch (err) {
    console.error('[Window] Failed to save state:', err.message);
  }
}

// ─── Port helpers ──────────────────────────────────────────────────
function checkPort(port, callback) {
  const server = net.createServer();
  server.once('error', () => callback(false));
  server.once('listening', () => {
    server.close();
    callback(true);
  });
  server.listen(port, '127.0.0.1');
}

function waitForPort(port, timeout = 15000) {
  return new Promise((resolve, reject) => {
    const start = Date.now();
    const check = () => {
      checkPort(port, (available) => {
        // available === false means something is already listening
        if (!available) {
          resolve();
        } else if (Date.now() - start > timeout) {
          reject(new Error(`Port ${port} not ready after ${timeout}ms`));
        } else {
          setTimeout(check, 200);
        }
      });
    };
    check();
  });
}

function waitForHttp(url, timeout = 15000) {
  return new Promise((resolve) => {
    const start = Date.now();
    const tryOnce = () => {
      const req = http.get(url, (res) => {
        res.resume();
        resolve(true);
      });
      req.on('error', () => {
        if (Date.now() - start > timeout) {
          resolve(false);
        } else {
          setTimeout(tryOnce, 250);
        }
      });
      req.setTimeout(1500, () => {
        req.destroy();
      });
    };
    tryOnce();
  });
}

// ─── Storage bootstrap ─────────────────────────────────────────────
function initStorageDir() {
  const storagePath = getStoragePath();
  const dirs = [
    storagePath,
    path.join(storagePath, 'config'),
    path.join(storagePath, 'auth'),
    path.join(storagePath, 'auth', 'archive'),
    path.join(storagePath, 'models'),
    path.join(storagePath, 'runtime'),
    path.join(storagePath, 'runtime', 'active-auth'),
    path.join(storagePath, 'runtime', 'tmp'),
    path.join(storagePath, 'cache'),
    path.join(storagePath, 'logs'),
    path.join(storagePath, 'logs', 'request_logs'),
    path.join(storagePath, 'logs', 'request_archive'),
    path.join(storagePath, 'logs', 'tool_logs'),
    path.join(storagePath, 'backups'),
  ];
  dirs.forEach((dir) => {
    if (!fs.existsSync(dir)) fs.mkdirSync(dir, { recursive: true });
  });

  const configFile = path.join(storagePath, 'config', 'base-config.yaml');
  if (!fs.existsSync(configFile)) {
    const defaultConfig = `host: "127.0.0.1"\nport: 8317\nauth-dir: "${storagePath.replace(/\\/g, '/')}/auth"\napi-keys:\n  - "cliproxyapi"\ndebug: false\n`;
    fs.writeFileSync(configFile, defaultConfig, 'utf-8');
  }

  const sourcesFile = path.join(storagePath, 'config', 'sources.json');
  if (!fs.existsSync(sourcesFile)) {
    fs.writeFileSync(sourcesFile, '{}', 'utf-8');
  }

  const stateFile = path.join(storagePath, 'runtime', 'state.json');
  if (!fs.existsSync(stateFile)) {
    // Default minimize_tray=true so first-run close matches tray-app expectations.
    fs.writeFileSync(stateFile, JSON.stringify({
      autostart: false,
      minimize_tray: true,
      language: 'zh',
      theme: 'light',
      auto_update_check: true,
      update_channel: 'stable',
    }, null, 2), 'utf-8');
  }

  return storagePath;
}

// ─── Child processes ───────────────────────────────────────────────
function startDashboard() {
  const resPath = getResourcesPath();
  const dashboardDir = path.join(resPath, 'dashboard');
  const dashboardExe = path.join(dashboardDir, 'dashboard.exe');
  const accessGatewayBinary = path.join(resPath, 'CLIProxyAPI-AccessGateway', 'cli-access-gateway.exe');

  if (!fs.existsSync(dashboardExe)) {
    console.log('[Dashboard] Binary not found, skipping:', dashboardExe);
    return null;
  }

  const storagePath = initStorageDir();

  console.log('[Dashboard] Starting:', dashboardExe);
  const proc = spawn(dashboardExe, [], {
    cwd: dashboardDir,
    stdio: 'ignore',
    detached: false,
    env: {
      ...process.env,
      CLIPROXYAPI_ROOT: resPath,
      CLIPROXYAPI_STORAGE_DIR: storagePath,
      CLIPROXYAPI_ACCESS_GATEWAY_BINARY: accessGatewayBinary,
      RELAYX_CLI_BINARY: path.join(resPath, 'cli-proxy-api.exe'),
      RELAYX_DASHBOARD_ROOT: dashboardDir,
      CLIPROXYAPI_DASHBOARD_PORT: String(DASHBOARD_PORT),
      CLIPROXYAPI_DASHBOARD_HOST: '127.0.0.1',
      CLIPROXYAPI_AUTO_START: '1',
    },
  });

  proc.on('error', (err) => {
    console.error('[Dashboard] Failed to start:', err.message);
  });

  proc.on('exit', (code) => {
    console.log('[Dashboard] Exited with code:', code);
    dashboardProcess = null;
  });

  return proc;
}

function killProcess(proc, name) {
  if (!proc) return;
  try {
    if (process.platform === 'win32' && proc.pid) {
      // Ensure child tree exits on Windows.
      spawn('taskkill', ['/pid', String(proc.pid), '/t', '/f'], {
        stdio: 'ignore',
        windowsHide: true,
      });
    } else {
      proc.kill();
    }
    console.log(`[${name}] Process killed`);
  } catch (err) {
    console.error(`[${name}] Failed to kill:`, err.message);
  }
}

function killAllServices() {
  killProcess(dashboardProcess, 'Dashboard');
  dashboardProcess = null;
}

// ─── Window / tray ─────────────────────────────────────────────────
function showMainWindow() {
  if (!mainWindow || mainWindow.isDestroyed()) return;
  if (mainWindow.isMinimized()) mainWindow.restore();
  mainWindow.show();
  mainWindow.focus();
}

function hideToTray() {
  if (!mainWindow || mainWindow.isDestroyed()) return;
  saveWindowState();
  mainWindow.hide();
  ensureTray();
}

function quitApp() {
  if (isQuitting) return;
  isQuitting = true;
  saveWindowState();
  killAllServices();
  if (tray) {
    try { tray.destroy(); } catch { /* ignore */ }
    tray = null;
  }
  app.quit();
}

function buildTrayMenu() {
  return Menu.buildFromTemplate([
    {
      label: '显示主窗口',
      click: () => showMainWindow(),
    },
    { type: 'separator' },
    {
      label: '退出',
      click: () => quitApp(),
    },
  ]);
}

function ensureTray() {
  if (tray) return;

  const icoPath = getIconPath('icon.ico');
  const pngPath = getIconPath('icon.png');
  let icon;
  if (fs.existsSync(icoPath)) {
    icon = nativeImage.createFromPath(icoPath);
  } else if (fs.existsSync(pngPath)) {
    icon = nativeImage.createFromPath(pngPath).resize({ width: 16, height: 16 });
  } else {
    icon = nativeImage.createEmpty();
  }

  tray = new Tray(icon);
  tray.setToolTip('CLIProxyAPI Dashboard');
  tray.setContextMenu(buildTrayMenu());

  // Windows: single click restores; other platforms keep double-click.
  const restore = () => showMainWindow();
  if (process.platform === 'win32') {
    tray.on('click', restore);
  }
  tray.on('double-click', restore);
}

function createWindow() {
  const saved = loadWindowState();
  const options = {
    width: saved?.width || 1400,
    height: saved?.height || 900,
    minWidth: 960,
    minHeight: 600,
    title: 'CLIProxyAPI Dashboard',
    icon: fs.existsSync(getIconPath('icon.ico'))
      ? getIconPath('icon.ico')
      : getIconPath('icon.png'),
    show: false,
    backgroundColor: '#0f172a',
    autoHideMenuBar: true,
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      nodeIntegration: false,
      contextIsolation: true,
    },
  };

  if (
    Number.isInteger(saved?.x) &&
    Number.isInteger(saved?.y)
  ) {
    options.x = saved.x;
    options.y = saved.y;
  }

  mainWindow = new BrowserWindow(options);

  if (saved?.isMaximized) {
    mainWindow.maximize();
  }

  mainWindow.loadURL(`http://127.0.0.1:${DASHBOARD_PORT}`);

  mainWindow.once('ready-to-show', () => {
    if (!mainWindow || mainWindow.isDestroyed()) return;
    mainWindow.show();
    mainWindow.focus();
  });

  // Persist size/position while using the app.
  mainWindow.on('resize', () => {
    if (!mainWindow.isMaximized()) saveWindowState();
  });
  mainWindow.on('move', () => {
    if (!mainWindow.isMaximized()) saveWindowState();
  });
  mainWindow.on('maximize', saveWindowState);
  mainWindow.on('unmaximize', saveWindowState);

  // Close (X): tray or quit — controlled by Settings → minimize_tray. No popup.
  mainWindow.on('close', (e) => {
    if (isQuitting) return;
    e.preventDefault();
    if (shouldMinimizeToTray()) {
      hideToTray();
      return;
    }
    quitApp();
  });

  mainWindow.on('closed', () => {
    mainWindow = null;
  });
}

// ─── App lifecycle ─────────────────────────────────────────────────
if (process.platform === 'win32') {
  app.setAppUserModelId('com.cliproxyapi.dashboard');
}

app.on('second-instance', () => {
  showMainWindow();
});

app.whenReady().then(async () => {
  initStorageDir();
  ensureTray();

  // Dashboard auto-starts the proxy stack; Electron only hosts the shell window.
  dashboardProcess = startDashboard();

  await waitForPort(DASHBOARD_PORT, 12000).catch(() => {
    console.log('[Dashboard] Port wait timeout, continuing');
  });
  await waitForHttp(`http://127.0.0.1:${DASHBOARD_PORT}/`, 12000);

  createWindow();
});

app.on('window-all-closed', () => {
  // Tray mode keeps the process alive with a hidden window; otherwise quit.
  if (process.platform === 'darwin') return;
  if (!isQuitting && shouldMinimizeToTray() && tray) return;
  quitApp();
});

app.on('before-quit', () => {
  isQuitting = true;
  saveWindowState();
  killAllServices();
  if (tray) {
    try { tray.destroy(); } catch { /* ignore */ }
    tray = null;
  }
});

app.on('activate', () => {
  // macOS dock click
  if (!mainWindow || mainWindow.isDestroyed()) {
    createWindow();
  } else {
    showMainWindow();
  }
});

process.on('SIGINT', () => quitApp());
process.on('SIGTERM', () => quitApp());
