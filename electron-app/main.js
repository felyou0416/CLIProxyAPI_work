const { app, BrowserWindow } = require('electron');
const { spawn } = require('child_process');
const path = require('path');
const fs = require('fs');
const net = require('net');

let dashboardProcess = null;
let proxyProcess = null;
let mainWindow = null;

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

function startProxyServer() {
  const resPath = getResourcesPath();
  const proxyExe = path.join(resPath, 'cli-proxy-api.exe');

  if (!fs.existsSync(proxyExe)) {
    console.log('[Proxy] Binary not found, skipping:', proxyExe);
    return null;
  }

  const storagePath = path.join(resPath, 'storage');
  if (!fs.existsSync(storagePath)) {
    fs.mkdirSync(storagePath, { recursive: true });
  }

  console.log('[Proxy] Starting:', proxyExe);
  const proc = spawn(proxyExe, [], {
    cwd: resPath,
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

  const storagePath = path.join(resPath, 'storage');
  if (!fs.existsSync(storagePath)) {
    fs.mkdirSync(storagePath, { recursive: true });
  }

  console.log('[Dashboard] Starting:', dashboardExe);
  const proc = spawn(dashboardExe, [], {
    cwd: dashboardDir,
    stdio: 'ignore',
    detached: false,
    env: {
      ...process.env,
      CLIPROXYAPI_ROOT: path.join(resPath),
      RELAYX_CLI_BINARY: path.join(resPath, 'cli-proxy-api.exe'),
      CLIPROXYAPI_DASHBOARD_PORT: String(DASHBOARD_PORT),
      CLIPROXYAPI_DASHBOARD_HOST: '127.0.0.1',
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
  });

  mainWindow.on('close', () => {
    killAllServices();
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
  killAllServices();
  app.quit();
});

app.on('before-quit', () => {
  killAllServices();
});

process.on('SIGINT', () => {
  killAllServices();
  app.quit();
});

process.on('SIGTERM', () => {
  killAllServices();
  app.quit();
});
