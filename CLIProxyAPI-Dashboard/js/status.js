let refreshStatusPending = false;

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
    setText('selected-auth', selectedAuth, t('common.notSelected', 'Not selected'));
    setText('applied-auth', appliedAuth, t('common.notSelected', 'Not selected'));
    setText('selected-provider', selectedProvider, t('common.notSelected', 'Not selected'));
    setText('applied-provider', appliedProvider, t('common.notSelected', 'Not selected'));
    setText('active-auth-dir', s.active_auth_dir || '', '');
    setText('runtime-config', s.runtime_config || '', '');
    setText('proxy-local-url', s.local_proxy_url || 'http://127.0.0.1:8317', 'http://127.0.0.1:8317');
    setText('proxy-exposure-url', s.exposure_url || '-', '-');
    setText('proxy-api-key', s.api_key || 'cliproxyapi', 'cliproxyapi');
    setText('exposure-mode-status', s.exposure_enabled ? 'Enabled (LAN)' : 'Disabled', 'Disabled');

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

let runtimeActionBusy = false;

function getRuntimeActionButtons() {
  return Array.from(document.querySelectorAll('.runtime-action-btn'));
}

function setRuntimeActionState(button, label) {
  if (!button) return;
  button.dataset.idleHtml = button.innerHTML;
  button.classList.add('is-working');
  button.setAttribute('aria-busy', 'true');
  button.innerHTML = '<span class="runtime-action-spinner" aria-hidden="true"></span><span class="runtime-action-text"></span><span class="runtime-action-progress" aria-hidden="true"></span>';
  const text = button.querySelector('.runtime-action-text');
  if (text) text.textContent = label;
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
  if (runtimeActionBusy) return null;
  runtimeActionBusy = true;
  const buttons = getRuntimeActionButtons();
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
    runtimeActionBusy = false;
  }
}

async function startProxy(button) {
  return withRuntimeAction(button, t('runtime.startingProxy', '启动中...'), async () => {
    try {
      const r = await api('/api/start-project', 'POST');
      showMessage(r.message);
      await refreshStatus();
    } catch (e) {
      showMessage(e.message, true);
    }
  });
}

async function restartProxy(button) {
  return withRuntimeAction(button, t('runtime.restartingProxy', '重启中...'), async () => {
    try {
      const r = await api('/api/restart-proxy', 'POST');
      showMessage(r.message);
      await refreshStatus();
    } catch (e) {
      showMessage(e.message, true);
    }
  });
}

async function stopProxy(button) {
  return withRuntimeAction(button, t('runtime.stoppingProxy', '停止中...'), async () => {
    try {
      const r = await api('/api/stop-proxy', 'POST');
      showMessage(r.message);
      await refreshStatus();
    } catch (e) {
      showMessage(e.message, true);
    }
  });
}

async function startOAuthManager(button) {
  return withRuntimeAction(button, t('runtime.startingOAuthManager', '启动中...'), async () => {
    try {
      const r = await api('/api/start-oauth-manager', 'POST');
      showMessage(r.message);
      await refreshStatus();
    } catch (e) {
      showMessage(e.message, true);
    }
  });
}

async function stopOAuthManager(button) {
  return withRuntimeAction(button, t('runtime.stoppingOAuthManager', '停止中...'), async () => {
    try {
      const r = await api('/api/stop-oauth-manager', 'POST');
      showMessage(r.message);
      await refreshStatus();
    } catch (e) {
      showMessage(e.message, true);
    }
  });
}

async function enableExposureMode(button) {
  return withRuntimeAction(button, t('runtime.enablingExposure', '开启中...'), async () => {
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
  return withRuntimeAction(button, t('runtime.disablingExposure', '关闭中...'), async () => {
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
