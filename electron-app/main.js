const { app, BrowserWindow, dialog, Tray, Menu, nativeImage } = require('electron');
const { spawn } = require('child_process');
const path = require('path');
const fs = require('fs');
const net = require('net');

let dashboardProcess = null;
let proxyProcess = null;
let mainWindow = null;
let tray = null;
let isQuitting = false;

const DASHBOARD_PORT = parseInt(process.env.CLIPROXYAPI_DASHBOARD_PORT || '8765', 10);
const PROXY_PORT = parseInt(process.env.CLIPROXYAPI_PROXY_PORT || '8317', 10);

function getResourcesPath() {
  return app.isPackaged
    ? process.resourcesPath
    : path.join(__dirname, 'resources');
}

function getUserDataPath() {
  return path.join(app.getPath('userData'));
}

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
        if (!available) {
          resolve();
        } else if (Date.now() - start > timeout) {
          reject(new Error(`Port ${port} not available after ${timeout}ms`));
        } else {
          setTimeout(check, 200);
        }
      });
    };
    check();
  });
}

function initStorageDir() {
  const userDataPath = getUserDataPath();
  const storagePath = path.join(userDataPath, 'storage');
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
    fs.writeFileSync(stateFile, '{}', 'utf-8');
  }

  return storagePath;
}

function startProxyServer() {
  const resPath = getResourcesPath();
  const proxyExe = path.join(resPath, 'cli-proxy-api.exe');

  if (!fs.existsSync(proxyExe)) {
    console.log('[Proxy] Binary not found, skipping:', proxyExe);
    return null;
  }

  const storagePath = initStorageDir();

  console.log('[Proxy] Starting:', proxyExe);
  const configFile = path.join(storagePath, 'config', 'base-config.yaml');
  const proc = spawn(proxyExe, ['-config', configFile], {
    cwd: storagePath,
    stdio: 'ignore',
    detached: false,
    env: {
      ...process.env,
      CLIPROXYAPI_STORAGE_DIR: storagePath,
    },
  });

  proc.on('error', (err) => {
    console.error('[Proxy] Failed to start:', err.message);
  });

  proc.on('exit', (code) => {
    console.log('[Proxy] Exited with code:', code);
    proxyProcess = null;
  });

  return proc;
}

function startDashboard() {
  const resPath = getResourcesPath();
  const dashboardDir = path.join(resPath, 'dashboard');
  const dashboardExe = path.join(dashboardDir, 'dashboard.exe');

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
      RELAYX_CLI_BINARY: path.join(resPath, 'cli-proxy-api.exe'),
      RELAYX_DASHBOARD_ROOT: dashboardDir,
      CLIPROXYAPI_DASHBOARD_PORT: String(DASHBOARD_PORT),
      CLIPROXYAPI_DASHBOARD_HOST: '127.0.0.1',
      CLIPROXYAPI_AUTO_START: '0',
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
    proc.kill();
    console.log(`[${name}] Process killed`);
  } catch (err) {
    console.error(`[${name}] Failed to kill:`, err.message);
  }
}

function killAllServices() {
  killProcess(dashboardProcess, 'Dashboard');
  killProcess(proxyProcess, 'Proxy');
  dashboardProcess = null;
  proxyProcess = null;
}

function createWindow() {
  mainWindow = new BrowserWindow({
    width: 1400,
    height: 900,
    minWidth: 960,
    minHeight: 600,
    title: 'CLIProxyAPI Dashboard',
    icon: path.join(__dirname, 'assets', 'icon.png'),
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      nodeIntegration: false,
      contextIsolation: true,
    },
  });

  mainWindow.loadURL(`http://127.0.0.1:${DASHBOARD_PORT}`);

  mainWindow.on('closed', () => {
    mainWindow = null;
    tray = null;
  });

  mainWindow.on('close', (e) => {
    if (isQuitting) return;
    e.preventDefault();
    const choice = dialog.showMessageBoxSync(mainWindow, {
      type: 'question',
      buttons: ['最小化到托盘', '退出程序'],
      defaultId: 0,
      title: '关闭方式',
      message: '请选择关闭方式',
      detail: '最小化到托盘：程序继续在后台运行\n退出程序：完全关闭所有服务',
    });
    if (choice === 0) {
      mainWindow.hide();
      showTray();
    } else {
      isQuitting = true;
      killAllServices();
      app.quit();
    }
  });
}

function showTray() {
  if (tray) return;
  const iconPath = path.join(__dirname, 'assets', 'icon.png');
  let icon;
  if (fs.existsSync(iconPath)) {
    icon = nativeImage.createFromPath(iconPath).resize({ width: 16, height: 16 });
  } else {
    icon = nativeImage.createEmpty();
  }
  tray = new Tray(icon);
  tray.setToolTip('CLIProxyAPI Dashboard');
  tray.setContextMenu(Menu.buildFromTemplate([
    {
      label: '显示窗口', click: () => {
        if (mainWindow) {
          mainWindow.show();
          mainWindow.focus();
        }
      }
    },
    { type: 'separator' },
    {
      label: '退出', click: () => {
        isQuitting = true;
        killAllServices();
        app.quit();
      }
    },
  ]));
  tray.on('double-click', () => {
    if (mainWindow) {
      mainWindow.show();
      mainWindow.focus();
    }
  });
}

app.whenReady().then(async () => {
  proxyProcess = startProxyServer();

  await waitForPort(PROXY_PORT, 5000).catch(() => {
    console.log('[Proxy] Port wait timeout, continuing anyway');
  });

  dashboardProcess = startDashboard();

  await waitForPort(DASHBOARD_PORT, 10000).catch(() => {
    console.log('[Dashboard] Port wait timeout, continuing anyway');
  });

  createWindow();
});

app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') {
    killAllServices();
    app.quit();
  }
});

app.on('before-quit', () => {
  isQuitting = true;
  killAllServices();
  if (tray) {
    tray.destroy();
    tray = null;
  }
});

process.on('SIGINT', () => {
  killAllServices();
  app.quit();
});

process.on('SIGTERM', () => {
  killAllServices();
  app.quit();
});
