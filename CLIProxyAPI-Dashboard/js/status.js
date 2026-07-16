let refreshStatusPending = false;
window.tunnelActionBusy = false;
window.proxyActionBusy = false;
window.oauthActionBusy = false;
window.dashboardActionBusy = false;
window.openclawActionBusy = false;
window.mediaProxyActionBusy = false;
// Frontend/backend share one busy flag so concurrent grok2api actions don't race the dots.
window.grok2apiActionBusy = false;

// Traffic-light cache covers every control-station group, including the split Grok2API dots.
// Keys are logical service names; DOM ids are resolved by indicatorElementId().
const INDICATOR_TYPES = [
  'proxy',
  'media-proxy',
  'openclaw',
  'ip-helper',
  'dashboard',
  'oauth',
  'tunnel',
  // Split indicators (new). Kept separate so front/back can show independent colors.
  'grok2api-frontend',
  'grok2api-backend',
  // Legacy combined key from older builds; still read for migration, no longer written.
  'grok2api',
];
const GROK2API_DEFAULT_URL = 'http://127.0.0.1:5173/';
const INDICATOR_CACHE_KEY = 'cli-indicator-states';
// Non-standard element ids (HTML historically used *-dot for Grok2API).
const INDICATOR_ELEMENT_IDS = {
  'grok2api-frontend': 'grok2api-frontend-status-indicator',
  'grok2api-backend': 'grok2api-backend-status-indicator',
  // Older cache entries / callers may still pass "grok2api"; prefer frontend as fallback target.
  'grok2api': 'grok2api-frontend-status-indicator',
};

function indicatorElementId(type) {
  if (INDICATOR_ELEMENT_IDS[type]) return INDICATOR_ELEMENT_IDS[type];
  return `${type}-status-indicator`;
}

// Map logical indicator type -> window.*ActionBusy flag used by refreshStatus.
function indicatorBusyKey(type) {
  if (type === 'media-proxy') return 'mediaProxyActionBusy';
  // Both Grok2API rows share one lock.
  if (type === 'grok2api' || type === 'grok2api-frontend' || type === 'grok2api-backend') {
    return 'grok2apiActionBusy';
  }
  return `${type}ActionBusy`;
}

function loadIndicatorStates() {
  try {
    const raw = localStorage.getItem(INDICATOR_CACHE_KEY);
    if (!raw) return;
    const states = JSON.parse(raw);
    // Restore last known colors before /api/status returns, so new buttons don't flash red.
    for (const [type, color] of Object.entries(states)) {
      if (typeof window.updateIndicator === 'function') {
        window.updateIndicator(type, color, { persist: false });
      }
    }
    // Migrate legacy combined "grok2api" into the split keys when they are missing.
    if (states.grok2api) {
      if (!states['grok2api-frontend']) {
        window.updateIndicator('grok2api-frontend', states.grok2api, { persist: false });
      }
      if (!states['grok2api-backend']) {
        window.updateIndicator('grok2api-backend', states.grok2api, { persist: false });
      }
    }
  } catch (e) { /* ignore */ }
}
window.loadIndicatorStates = loadIndicatorStates;

function saveIndicatorStates() {
  const states = {};
  for (const type of INDICATOR_TYPES) {
    // Skip legacy combined key when writing so cache stays on the split indicators.
    if (type === 'grok2api') continue;
    const el = document.getElementById(indicatorElementId(type));
    if (!el) continue;
    const match = el.className.match(/status-indicator-dot\s+(\w+)/);
    if (match) states[type] = match[1];
  }
  try {
    if (Object.keys(states).length) {
      localStorage.setItem(INDICATOR_CACHE_KEY, JSON.stringify(states));
    }
  } catch (e) { /* ignore */ }
}
window.saveIndicatorStates = saveIndicatorStates;

// options.persist=false is used by load/refresh internals to avoid write thrash.
window.updateIndicator = function(type, state, options = {}) {
  const el = document.getElementById(indicatorElementId(type));
  if (el) {
    el.className = `status-indicator-dot ${state}`;
  }
  if (options.persist !== false) {
    saveIndicatorStates();
  }
};

function setHtml(id, html) {
  const el = document.getElementById(id);
  if (el) el.innerHTML = html;
}

function summarizePool(names, fallback) {
  const list = Array.isArray(names) ? names.filter(Boolean) : [];
  if (!list.length) return fallback;
  if (list.length === 1) return list[0];
  return `${list[0]} +${list.length - 1}`;
}

function summarizeProviders(providers, fallback) {
  const list = Array.isArray(providers) ? [...new Set(providers.filter(Boolean))] : [];
  return list.length ? list.join(', ') : fallback;
}

function updateProxyToolSummary(s) {
  const proxyStateText = statusText(s.proxy_running);
  const selectedAccountText = summarizePool(s.selected_auths, s.selected_auth || t('common.notSelected', 'Not selected'));
  const appliedAccountText = summarizePool(s.applied_auths, s.applied_auth || t('common.notSelected', 'Not selected'));
  const selectedProviderText = summarizeProviders(s.selected_providers, s.selected_provider || t('common.notSelected', 'Not selected'));
  const appliedProviderText = summarizeProviders(s.applied_providers, s.applied_provider || t('common.notSelected', 'Not selected'));
  const proxyLog = document.getElementById('log-proxy-main');
  const proxySummary = [
    `Status: ${proxyStateText}`,
    `Exposure mode: ${s.exposure_enabled ? 'Enabled' : 'Disabled'}`,
    `Enabled files: ${selectedAccountText}`,
    `Enabled providers: ${selectedProviderText}`,
    `Loaded files: ${appliedAccountText}`,
    `Loaded providers: ${appliedProviderText}`,
    s.restart_required ? t('common.restartRequired', 'Restart required to apply runtime setting changes.') : '',
    `Local URL: ${s.local_proxy_url || s.proxy_url || 'http://127.0.0.1:8317'}`,
    `Exposure URL: ${s.exposure_url || '-'}`,
    `API Key: ${s.api_key || 'cliproxyapi'}`,
    '',
    s.proxy_stdout || '',
    s.proxy_stderr ? '\n----- stderr -----\n\n' + s.proxy_stderr : ''
  ].filter(Boolean).join('\n').trim();

  if (proxyLog) {
    proxyLog.textContent = proxySummary || t('common.noLogs', 'No logs yet');
    setLogVisible(proxyLog, true);
  }

  const proxyStatus = document.getElementById('status-proxy-main');
  if (proxyStatus) {
    proxyStatus.textContent = proxyStateText;
    proxyStatus.className = 'tool-status ' + (s.proxy_running ? 'tool-running' : 'tool-stopped');
  }

  setText('status-proxy-main-chip', proxyStateText, 'Not running');
  setText('tools-summary-proxy', proxyStateText, 'Not running');
  const toolsSummaryAuth = selectedAccountText
    ? `${selectedAccountText}${selectedProviderText && selectedProviderText !== t('common.notSelected', 'Not selected') ? ` (${selectedProviderText})` : ''}`
    : t('common.notSelected', 'Not selected');
  setText('tools-summary-auth', toolsSummaryAuth, t('common.notSelected', 'Not selected'));
}

async function refreshStatus() {
  if (document.hidden) return;
  if (refreshStatusPending) return;
  refreshStatusPending = true;
  try {
    const data = await api('/api/status');
    const s = data.status || {};
    const selectedAuth = summarizePool(s.selected_auths, s.selected_auth || t('common.notSelected', 'Not selected'));
    const selectedProvider = summarizeProviders(s.selected_providers, s.selected_provider || t('common.notSelected', 'Not selected'));
    const appliedAuth = summarizePool(s.applied_auths, s.applied_auth || t('common.notSelected', 'Not selected'));
    const appliedProvider = summarizeProviders(s.applied_providers, s.applied_provider || t('common.notSelected', 'Not selected'));
    const authCount = String(s.auth_files_count ?? 0);
    const selectedAuthCount = String(
      (Array.isArray(s.selected_auth_refs) && s.selected_auth_refs.length)
      || (Array.isArray(s.selected_auths) && s.selected_auths.length)
      || (s.selected_auth ? 1 : 0)
    );
    const deviceText = statusText(s.device_login_running);
    const proxyText = statusText(s.proxy_running);

    setHtml('device-running', statusPill(s.device_login_running));
    setHtml('proxy-running', statusPill(s.proxy_running));
    setHtml('media-proxy-running', statusPill(s.media_proxy_running));
    setText('selected-auth', selectedAuth, t('common.notSelected', 'Not selected'));
    setText('applied-auth', appliedAuth, t('common.notSelected', 'Not selected'));
    setText('selected-provider', selectedProvider, t('common.notSelected', 'Not selected'));
    setText('applied-provider', appliedProvider, t('common.notSelected', 'Not selected'));
    setText('active-auth-dir', s.active_auth_dir || '', '');
    setText('runtime-config', s.runtime_config || '', '');
    setText('proxy-local-url', s.local_proxy_url || 'http://127.0.0.1:8317', 'http://127.0.0.1:8317');
    setText('media-proxy-url', s.media_proxy_url || 'http://127.0.0.1:8320', 'http://127.0.0.1:8320');
    const grok2apiUrl = s.grok2api_url || GROK2API_DEFAULT_URL;
    const grok2apiTitle = document.getElementById('grok2api-title-link');
    if (grok2apiTitle) grok2apiTitle.href = grok2apiUrl;
    setText('proxy-exposure-url', s.exposure_url || '-', '-');
    setText('proxy-api-key', s.api_key || 'cliproxyapi', 'cliproxyapi');
    setText('exposure-mode-status', s.exposure_enabled ? 'Enabled (LAN)' : 'Disabled', 'Disabled');

    // Skip live updates while that group is mid-action so yellow "working" is not overwritten.
    if (!window.proxyActionBusy) {
      window.updateIndicator('proxy', s.proxy_running ? 'green' : 'red', { persist: false });
    }
    if (!window.mediaProxyActionBusy) {
      window.updateIndicator('media-proxy', s.media_proxy_running ? 'green' : 'red', { persist: false });
    }
    if (!window.tunnelActionBusy) {
      window.updateIndicator('tunnel', s.tunnel_running ? 'green' : 'red', { persist: false });
    }
    if (!window.oauthActionBusy) {
      window.updateIndicator('oauth', s.oauth_manager_running ? 'green' : 'red', { persist: false });
    }
    if (!window.openclawActionBusy) {
      window.updateIndicator('openclaw', s.openclaw_running ? 'green' : 'red', { persist: false });
    }
    if (!window.dashboardActionBusy) {
      window.updateIndicator('dashboard', 'green', { persist: false });
    }
    // Split Grok2API dots must be cached independently (restart/start buttons are per-row).
    if (!window.grok2apiActionBusy) {
      window.updateIndicator('grok2api-frontend', s.grok2api_frontend_running ? 'green' : 'red', { persist: false });
      window.updateIndicator('grok2api-backend', s.grok2api_backend_running ? 'green' : 'red', { persist: false });
    }

    // One write after batch updates (persist:false above).
    saveIndicatorStates();

    const openClawStartBtn = document.getElementById('openclaw-start-btn');
    const openClawRestartBtn = document.getElementById('openclaw-restart-btn');
    const openClawStopBtn = document.getElementById('openclaw-stop-btn');
    if (openClawStartBtn && openClawRestartBtn && openClawStopBtn) {
      const isRunning = !!s.openclaw_running;
      openClawStartBtn.disabled = isRunning;
      openClawStartBtn.style.opacity = isRunning ? '0.5' : '1';
      openClawRestartBtn.disabled = !isRunning;
      openClawRestartBtn.style.opacity = isRunning ? '1' : '0.5';
      openClawStopBtn.disabled = !isRunning;
      openClawStopBtn.style.opacity = isRunning ? '1' : '0.5';
      if (window.openclawActionBusy) {
        openClawStartBtn.disabled = true;
        openClawRestartBtn.disabled = true;
        openClawStopBtn.disabled = true;
      }
    }

    const mediaProxyStartBtn = document.getElementById('media-proxy-start-btn');
    const mediaProxyRestartBtn = document.getElementById('media-proxy-restart-btn');
    const mediaProxyStopBtn = document.getElementById('media-proxy-stop-btn');
    if (mediaProxyStartBtn && mediaProxyRestartBtn && mediaProxyStopBtn) {
      const isRunning = !!s.media_proxy_running;
      mediaProxyStartBtn.disabled = isRunning;
      mediaProxyStartBtn.style.opacity = isRunning ? '0.5' : '1';
      mediaProxyRestartBtn.disabled = !isRunning;
      mediaProxyRestartBtn.style.opacity = isRunning ? '1' : '0.5';
      mediaProxyStopBtn.disabled = !isRunning;
      mediaProxyStopBtn.style.opacity = isRunning ? '1' : '0.5';
      if (window.mediaProxyActionBusy) {
        mediaProxyStartBtn.disabled = true;
        mediaProxyRestartBtn.disabled = true;
        mediaProxyStopBtn.disabled = true;
      }
    }

    // Button enable/disable only here; colors already went through updateIndicator above.
    const grok2apiControls = [
      { type: 'frontend', running: !!s.grok2api_frontend_running },
      { type: 'backend', running: !!s.grok2api_backend_running },
    ];
    for (const control of grok2apiControls) {
      const startButton = document.getElementById(`grok2api-${control.type}-start-btn`);
      const restartButton = document.getElementById(`grok2api-${control.type}-restart-btn`);
      const stopButton = document.getElementById(`grok2api-${control.type}-stop-btn`);
      if (!startButton || !stopButton) continue;
      startButton.disabled = control.running;
      startButton.style.opacity = control.running ? '0.5' : '1';
      if (restartButton) {
        restartButton.disabled = !control.running;
        restartButton.style.opacity = control.running ? '1' : '0.5';
      }
      stopButton.disabled = !control.running;
      stopButton.style.opacity = control.running ? '1' : '0.5';
      if (window.grok2apiActionBusy) {
        startButton.disabled = true;
        if (restartButton) restartButton.disabled = true;
        stopButton.disabled = true;
      }
    }

    const startBtn = document.getElementById('tunnel-start-btn');
    const restartBtn = document.getElementById('tunnel-restart-btn');
    const stopBtn = document.getElementById('tunnel-stop-btn');
    if (startBtn && stopBtn) {
      const isRunning = !!s.tunnel_running;
      startBtn.disabled = isRunning;
      startBtn.style.opacity = isRunning ? '0.5' : '1';
      if (restartBtn) {
        restartBtn.disabled = !isRunning;
        restartBtn.style.opacity = isRunning ? '1' : '0.5';
      }
      stopBtn.disabled = !isRunning;
      stopBtn.style.opacity = isRunning ? '1' : '0.5';
      if (window.tunnelActionBusy) {
        startBtn.disabled = true;
        if (restartBtn) restartBtn.disabled = true;
        stopBtn.disabled = true;
      }
    }

    setText('summary-selected-auth-count', selectedAuthCount, '0');
    setText('summary-auth-count', authCount, '0');
    setText('auth-count-badge', authCount, '0');
    setText('summary-device-login', deviceText, 'Not running');
    setText('summary-proxy-status', proxyText, 'Not running');

    updateProxyToolSummary(s);
    if (typeof updateToolCommandHints === 'function') {
      updateToolCommandHints(s);
    }
  } catch (err) {
  } finally {
    refreshStatusPending = false;
  }
}

async function startDeviceLogin() {
  try {
    const r = await api('/api/start-device-login', 'POST');
    showMessage(r.message);
    await refreshStatus();
  } catch (e) {
    showMessage(e.message, true);
  }
}

async function stopDeviceLogin() {
  try {
    const r = await api('/api/stop-device-login', 'POST');
    showMessage(r.message);
    await refreshStatus();
  } catch (e) {
    showMessage(e.message, true);
  }
}

function shortRuntimeLabel(label) {
  const raw = String(label || '').trim();
  if (!raw) return '处理';
  // Keep button busy text at 2 Chinese chars / short English word so pills never overflow.
  const compact = raw
    .replace(/\.{2,}$/g, '')
    .replace(/中$/g, '')
    .replace(/(前端|后端|Tunnel|OAuth|Manager|Proxy|服务|代理)/gi, '')
    .trim();
  const map = {
    '启动': '启动',
    '重启': '重启',
    '停止': '停止',
    '关闭': '关闭',
    '开启': '开启',
    '检测': '检测',
    '停用': '停用',
    '恢复': '恢复',
    'Starting': '启动',
    'Restarting': '重启',
    'Stopping': '停止',
    'Disabling': '关闭',
    'Enabling': '开启',
  };
  if (map[compact]) return map[compact];
  if (map[raw]) return map[raw];
  if (/start/i.test(raw)) return '启动';
  if (/restart/i.test(raw)) return '重启';
  if (/stop|close|disable/i.test(raw)) return '停止';
  if (/enable/i.test(raw)) return '开启';
  // Prefer first 2 CJK chars; otherwise leave short English words alone.
  const cjk = raw.match(/[一-鿿]{1,2}/);
  if (cjk) return cjk[0];
  return compact.slice(0, 4) || '处理';
}

function getRuntimeActionGroupButtons(button) {
  if (!button) return [];
  // Only lock siblings in the same control group / pair so other services stay clickable.
  const group = button.closest('.control-group, .control-pair') || button.parentElement;
  if (!group) return [button];
  const buttons = Array.from(group.querySelectorAll('.runtime-action-btn, button'));
  return buttons.length ? buttons : [button];
}

function setRuntimeActionState(button, label) {
  if (!button) return;
  button.dataset.idleHtml = button.innerHTML;
  button.classList.add('is-working');
  button.setAttribute('aria-busy', 'true');
  button.innerHTML = '<span class="runtime-action-spinner" aria-hidden="true"></span><span class="runtime-action-text"></span><span class="runtime-action-progress" aria-hidden="true"></span>';
  const text = button.querySelector('.runtime-action-text');
  if (text) text.textContent = shortRuntimeLabel(label);
}

function clearRuntimeActionState(button) {
  if (!button) return;
  button.classList.remove('is-working');
  button.removeAttribute('aria-busy');
  if (button.dataset.idleHtml) {
    button.innerHTML = button.dataset.idleHtml;
    delete button.dataset.idleHtml;
  }
}

async function withRuntimeAction(button, label, task) {
  if (!button) return task();
  // Prevent double-click on the same group, but never freeze the whole control station.
  if (button.dataset.runtimeBusy === '1' || button.closest('.control-group')?.dataset.runtimeBusy === '1') {
    return null;
  }
  const group = button.closest('.control-group');
  const buttons = getRuntimeActionGroupButtons(button);
  if (group) group.dataset.runtimeBusy = '1';
  button.dataset.runtimeBusy = '1';
  buttons.forEach(btn => {
    btn.dataset.prevDisabled = btn.disabled ? '1' : '0';
    btn.disabled = true;
  });
  setRuntimeActionState(button, label);
  try {
    return await task();
  } finally {
    clearRuntimeActionState(button);
    buttons.forEach(btn => {
      btn.disabled = btn.dataset.prevDisabled === '1';
      delete btn.dataset.prevDisabled;
    });
    delete button.dataset.runtimeBusy;
    if (group) delete group.dataset.runtimeBusy;
  }
}

function sleepRuntime(ms) {
  return new Promise(resolve => setTimeout(resolve, ms));
}

async function waitForRuntimeStatus(predicate, timeoutMs = 150000, intervalMs = 2500) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    try {
      const data = await api('/api/status');
      const status = data.status || {};
      if (predicate(status)) {
        await refreshStatus();
        return status;
      }
    } catch (e) {
      // Keep polling; transient startup timeouts are expected for slow services.
    }
    await sleepRuntime(intervalMs);
  }
  await refreshStatus();
  return null;
}

async function handleActionWithIndicator(type, button, label, actionApiUrl, errorIndicatorState, options = {}) {
  // Resolve busy flag via shared helper so split types (grok2api-*) share one lock.
  const busyKey = indicatorBusyKey(type);
  window[busyKey] = true;
  // Yellow = action in progress; persist so reload mid-action still shows working state briefly.
  if (typeof window.updateIndicator === 'function') {
    window.updateIndicator(type, 'yellow');
  }
  try {
    return await withRuntimeAction(button, label, async () => {
      try {
        const r = await api(actionApiUrl, 'POST');
        showMessage(r.message);
        if (typeof options.waitFor === 'function') {
          const status = await waitForRuntimeStatus(options.waitFor, options.timeoutMs, options.intervalMs);
          if (status) {
            showMessage(options.readyMessage || r.message);
          } else if (options.timeoutMessage) {
            showMessage(options.timeoutMessage, true);
            if (errorIndicatorState && typeof window.updateIndicator === 'function') {
              // updateIndicator persists by default.
              window.updateIndicator(type, errorIndicatorState);
            }
          }
        } else {
          await refreshStatus();
        }
      } catch (e) {
        showMessage(e.message, true);
        if (errorIndicatorState && typeof window.updateIndicator === 'function') {
          window.updateIndicator(type, errorIndicatorState);
        }
      }
    });
  } finally {
    window[busyKey] = false;
  }
}

async function startProxy(button) {
  return handleActionWithIndicator('proxy', button, t('runtime.startingProxy', '启动'), '/api/start-project', 'red');
}

async function restartProxy(button) {
  return handleActionWithIndicator('proxy', button, t('runtime.restartingProxy', '重启'), '/api/restart-proxy');
}

async function stopProxy(button) {
  return handleActionWithIndicator('proxy', button, t('runtime.stoppingProxy', '停止'), '/api/stop-proxy', 'green');
}

async function startOAuthManager(button) {
  return handleActionWithIndicator('oauth', button, t('runtime.startingOAuthManager', '启动'), '/api/start-oauth-manager', 'red', {
    waitFor: status => !!status.oauth_manager_running,
    timeoutMs: 20000,
    intervalMs: 1000,
    readyMessage: t('runtime.oauthManagerReady', 'OAuth Manager 已启动。'),
    timeoutMessage: t('runtime.oauthManagerStartTimeout', 'OAuth Manager 启动命令已发出，但未检测到服务就绪。请查看 OAuth Manager 日志。'),
  });
}

async function stopOAuthManager(button) {
  return handleActionWithIndicator('oauth', button, t('runtime.stoppingOAuthManager', '停止'), '/api/stop-oauth-manager', 'green', {
    waitFor: status => !status.oauth_manager_running,
    timeoutMs: 15000,
    intervalMs: 800,
    readyMessage: t('runtime.oauthManagerStopped', 'OAuth Manager 已停止。'),
  });
}

async function restartOAuthManager(button) {
  return handleActionWithIndicator('oauth', button, t('runtime.restartingOAuthManager', '重启'), '/api/restart-oauth-manager', 'red', {
    waitFor: status => !!status.oauth_manager_running,
    timeoutMs: 25000,
    intervalMs: 1000,
    readyMessage: t('runtime.oauthManagerReady', 'OAuth Manager 已启动。'),
    timeoutMessage: t('runtime.oauthManagerStartTimeout', 'OAuth Manager 重启命令已发出，但未检测到服务就绪。请查看 OAuth Manager 日志。'),
  });
}

async function waitForOpenClawRunning(button, label, actionApiUrl) {
  return handleActionWithIndicator('openclaw', button, label, actionApiUrl, 'red', {
    waitFor: status => !!status.openclaw_running,
    timeoutMs: 180000,
    intervalMs: 3000,
    readyMessage: 'OpenClaw 已启动并可用。',
    timeoutMessage: 'OpenClaw 启动命令已发出，但 3 分钟内未检测到网关。请查看 OpenClaw 日志。',
  });
}

async function startOpenClaw(button) {
  return waitForOpenClawRunning(button, '启动', '/api/openclaw/start');
}

async function restartOpenClaw(button) {
  return waitForOpenClawRunning(button, '重启', '/api/openclaw/restart');
}

async function stopOpenClaw(button) {
  return handleActionWithIndicator('openclaw', button, '停止', '/api/openclaw/stop', 'green');
}

async function startMediaProxy(button) {
  return handleActionWithIndicator('media-proxy', button, '启动', '/api/media-proxy/start', 'red');
}

async function restartMediaProxy(button) {
  return handleActionWithIndicator('media-proxy', button, '重启', '/api/media-proxy/restart', 'red');
}

async function stopMediaProxy(button) {
  return handleActionWithIndicator('media-proxy', button, '停止', '/api/media-proxy/stop', 'green');
}

// type must be 'grok2api-frontend' or 'grok2api-backend' so the correct traffic light is cached.
async function runGrok2ApiServiceAction(type, button, label, endpoint, errorState) {
  const result = await handleActionWithIndicator(type, button, label, endpoint, errorState);
  await refreshStatus();
  return result;
}

async function startGrok2ApiFrontend(button) {
  return runGrok2ApiServiceAction('grok2api-frontend', button, '启动', '/api/grok2api/frontend/start', 'red');
}

async function stopGrok2ApiFrontend(button) {
  return runGrok2ApiServiceAction('grok2api-frontend', button, '关闭', '/api/grok2api/frontend/stop', 'red');
}

async function restartGrok2ApiFrontend(button) {
  return runGrok2ApiServiceAction('grok2api-frontend', button, '重启', '/api/grok2api/frontend/restart', 'red');
}

async function startGrok2ApiBackend(button) {
  return runGrok2ApiServiceAction('grok2api-backend', button, '启动', '/api/grok2api/backend/start', 'red');
}

async function stopGrok2ApiBackend(button) {
  return runGrok2ApiServiceAction('grok2api-backend', button, '关闭', '/api/grok2api/backend/stop', 'red');
}

async function restartGrok2ApiBackend(button) {
  return runGrok2ApiServiceAction('grok2api-backend', button, '重启', '/api/grok2api/backend/restart', 'red');
}

async function enableExposureMode(button) {
  return withRuntimeAction(button, t('runtime.enablingExposure', '开启'), async () => {
    try {
      const r = await api('/api/enable-exposure', 'POST');
      showMessage(r.message);
      await refreshStatus();
      if (typeof loadNetworkAccessPanel === 'function') {
        await loadNetworkAccessPanel(true);
      }
    } catch (e) {
      showMessage(e.message, true);
    }
  });
}

async function disableExposureMode(button) {
  return withRuntimeAction(button, t('runtime.disablingExposure', '关闭'), async () => {
    try {
      const r = await api('/api/disable-exposure', 'POST');
      showMessage(r.message);
      await refreshStatus();
      if (typeof loadNetworkAccessPanel === 'function') {
        await loadNetworkAccessPanel(true);
      }
    } catch (e) {
      showMessage(e.message, true);
    }
  });
}

async function startTunnel(button) {
  return handleActionWithIndicator('tunnel', button, t('runtime.startingTunnel', '启动'), '/api/tunnel/start', 'red');
}

async function stopTunnel(button) {
  return handleActionWithIndicator('tunnel', button, t('runtime.stoppingTunnel', '关闭'), '/api/tunnel/stop', 'green');
}

async function restartTunnel(button) {
  return handleActionWithIndicator('tunnel', button, t('runtime.restartingTunnel', '重启'), '/api/tunnel/restart', 'red');
}
