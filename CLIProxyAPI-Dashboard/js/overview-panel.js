let overviewPanelLoaded = false;
let proxyStatus = { enabled: false, port: null, availablePorts: [] };

function overviewApiWithTimeout(path, timeoutMs = 2500) {
  return Promise.race([
    api(path),
    new Promise((_, reject) => setTimeout(() => reject(new Error(`timeout: ${path}`)), timeoutMs)),
  ]);
}

function summarizeOverviewFailureReason(items) {
  const counts = new Map();
  for (const item of items || []) {
    const reason = String(item.failure_kind || item.recent_failure_reason || '').trim();
    if (!reason) continue;
    counts.set(reason, (counts.get(reason) || 0) + 1);
  }
  let bestReason = '-';
  let bestCount = 0;
  for (const [reason, count] of counts.entries()) {
    if (count > bestCount) {
      bestReason = reason;
      bestCount = count;
    }
  }
  return { reason: bestReason, count: bestCount };
}

function summarizeTopFailures(items, keyName) {
  const counts = new Map();
  for (const item of items || []) {
    const statusCode = Number(item.status_code || 0);
    if (statusCode < 400) continue;
    const key = String(item[keyName] || '').trim() || '-';
    counts.set(key, (counts.get(key) || 0) + 1);
  }
  let bestKey = '-';
  let bestCount = 0;
  for (const [key, count] of counts.entries()) {
    if (count > bestCount) {
      bestKey = key;
      bestCount = count;
    }
  }
  return { key: bestKey, count: bestCount };
}

function countStatuses(items) {
  let success = 0;
  let failure = 0;
  let count429 = 0;
  let count5xx = 0;
  for (const item of items || []) {
    const statusCode = Number(item.status_code || 0);
    if (item.success) success += 1;
    else failure += 1;
    if (statusCode === 429) count429 += 1;
    if (statusCode >= 500) count5xx += 1;
  }
  return { success, failure, count429, count5xx };
}

function overviewCardHtml(label, value, note = '') {
  return `
    <div class="summary-tile small-tile">
      <div class="summary-label">${label}</div>
      <div class="summary-value">${value}</div>
      ${note ? `<div class="tool-desc-zh">${note}</div>` : ''}
    </div>
  `;
}

async function loadOverviewPanel(force = false) {
  if (overviewPanelLoaded && !force) return;
  const wrap = document.getElementById('overview-grid');
  if (wrap) wrap.innerHTML = '<div class="metric-empty">loading...</div>';
  try {
    const [statusRes, requestsRes, clientsRes, authRes, modelRes] = await Promise.allSettled([
      overviewApiWithTimeout('/api/status', 2500),
      overviewApiWithTimeout('/api/request-events?limit=200', 2500),
      overviewApiWithTimeout('/api/request-clients', 2500),
      overviewApiWithTimeout('/api/auth-health', 2500),
      overviewApiWithTimeout('/api/model-health?runtime=0', 2500),
    ]);

    const statusData = statusRes.status === 'fulfilled' ? statusRes.value : { status: {} };
    const requestsData = requestsRes.status === 'fulfilled' ? requestsRes.value : { items: [] };
    const clientsData = clientsRes.status === 'fulfilled' ? clientsRes.value : { items: [] };
    const authData = authRes.status === 'fulfilled' ? authRes.value : { items: [] };
    const modelData = modelRes.status === 'fulfilled' ? modelRes.value : { items: [] };

    const s = statusData.status || {};
    const requestItems = Array.isArray(requestsData.items) ? requestsData.items : [];
    const clientItems = Array.isArray(clientsData.items) ? clientsData.items : [];
    const authItems = Array.isArray(authData.items) ? authData.items : [];
    const modelItems = Array.isArray(modelData.items) ? modelData.items : [];

    const stats = countStatuses(requestItems);
    const providerSet = new Set((authItems || []).map(item => String(item.provider || '').trim()).filter(Boolean));
    const unhealthyModels = modelItems.filter(item => item.available === false);
    const specializedModels = modelItems.filter(item => String(item.failure_kind || '').trim() === 'specialized');
    const failedProvider = summarizeTopFailures(requestItems, 'inferred_provider');
    const failedModel = summarizeTopFailures(requestItems, 'requested_model');
    const failureReason = summarizeOverviewFailureReason([...authItems, ...modelItems]);
    const degraded = [statusRes, requestsRes, clientsRes, authRes, modelRes].some((entry) => entry.status !== 'fulfilled');

    const cards = [
      overviewCardHtml('代理状态', s.proxy_running ? '运行中' : '未运行', s.local_proxy_url || 'http://127.0.0.1:8317'),
      overviewCardHtml('当前选中 Auth', (Array.isArray(s.selected_auth_refs) ? s.selected_auth_refs.length : 0) || 0, s.selected_auth || '-'),
      overviewCardHtml('当前应用 Auth', (Array.isArray(s.applied_auth_refs) ? s.applied_auth_refs.length : 0) || 0, s.applied_auth || '-'),
      overviewCardHtml('启用 Provider 数', providerSet.size || 0, providerSet.size ? Array.from(providerSet).join(', ') : (degraded ? '部分数据不可用' : '-')),
      overviewCardHtml('最近请求数', requestItems.length || 0, `客户端 ${clientItems.length || 0} 个`),
      overviewCardHtml('成功 / 失败', `${stats.success} / ${stats.failure}`, `429: ${stats.count429} · 5xx: ${stats.count5xx}`),
      overviewCardHtml('失败最多 Provider', failedProvider.key, failedProvider.count ? `${failedProvider.count} 次` : '暂无'),
      overviewCardHtml('失败最多模型', failedModel.key, failedModel.count ? `${failedModel.count} 次` : '暂无'),
      overviewCardHtml('失败原因 Top', failureReason.reason, failureReason.count ? `${failureReason.count} 次` : '暂无'),
      overviewCardHtml('异常模型数', unhealthyModels.length || 0, `specialized: ${specializedModels.length || 0}${degraded ? ' · 部分接口超时' : ''}`),
    ].join('');

    if (wrap) wrap.innerHTML = cards;
    overviewPanelLoaded = true;
    loadProxyStatus();
  } catch (error) {
    if (wrap) wrap.innerHTML = `<div class="metric-empty">${error.message || 'load failed'}</div>`;
  }
}

function applyProxyStatus(item = {}) {
  proxyStatus.enabled = !!(item.proxy_enabled);
  proxyStatus.port = item.current_port || item.port || null;
  proxyStatus.availablePorts = Array.isArray(item.available_ports) ? item.available_ports : [];
  updateProxyStatusDisplay();
}

const SYSTEM_PROXY_PORT_BUTTONS = [7890, 10090, 7897];

function updateProxyStatusDisplay() {
  const statusDiv = document.getElementById('proxy-status');
  const toggleBtn = document.getElementById('proxy-toggle-btn');
  const indicator = document.getElementById('system-proxy-status-indicator');
  const currentPort = Number(proxyStatus.port || 0) || null;
  const available = new Set((proxyStatus.availablePorts || []).map((p) => Number(p)));

  if (toggleBtn) {
    if (proxyStatus.enabled) {
      toggleBtn.textContent = '停用';
      toggleBtn.title = '停止系统代理并清除代理环境变量';
      toggleBtn.classList.remove('primary');
      toggleBtn.classList.add('secondary');
    } else {
      toggleBtn.textContent = '启动';
      toggleBtn.title = '检测可用端口并启动系统代理';
      toggleBtn.classList.remove('secondary');
      toggleBtn.classList.add('primary');
    }
  }

  for (const port of SYSTEM_PROXY_PORT_BUTTONS) {
    const btn = document.getElementById(`proxy-port-${port}-btn`);
    if (!btn) continue;
    const isActive = !!(proxyStatus.enabled && currentPort === port);
    const isLive = available.has(port);
    btn.classList.toggle('primary', isActive);
    btn.classList.toggle('secondary', !isActive);
    btn.title = isActive
      ? `当前系统代理: 127.0.0.1:${port}`
      : `切换系统代理到 127.0.0.1:${port}${isLive ? '（端口在线）' : '（端口未监听）'}`;
  }

  if (indicator) {
    indicator.classList.remove('red', 'green', 'yellow');
    if (proxyStatus.enabled) {
      indicator.classList.add('green');
      indicator.title = `系统代理已启用${currentPort ? ` (端口 ${currentPort})` : ''}`;
    } else {
      indicator.classList.add('red');
      indicator.title = '系统代理未启用';
    }
  }

  if (!statusDiv) return;

  let html = proxyStatus.enabled
    ? `代理状态: <span style="color: var(--success, #00aa00);">已启用</span>${currentPort ? ` (端口 ${currentPort})` : ''}`
    : `代理状态: <span style="color: var(--danger, #aa0000);">未启用</span>`;

  if (proxyStatus.availablePorts && proxyStatus.availablePorts.length > 0) {
    html += ` · 可用端口: ${proxyStatus.availablePorts.join(', ')}`;
  }
  statusDiv.innerHTML = html;
}

async function loadProxyStatus() {
  try {
    const resp = await api('/api/system-proxy');
    if (resp && resp.ok) {
      applyProxyStatus(resp.item || resp);
    }
  } catch (e) {
    console.error('Failed to load proxy status:', e);
    const statusDiv = document.getElementById('proxy-status');
    if (statusDiv) statusDiv.textContent = `读取失败: ${e.message || e}`;
  }
}

function setProxyButtonsBusy(busy, activeBtn) {
  const ids = [
    'proxy-configure-btn',
    'proxy-toggle-btn',
    'proxy-default-btn',
    ...SYSTEM_PROXY_PORT_BUTTONS.map((port) => `proxy-port-${port}-btn`),
  ];
  ids.forEach((id) => {
    const btn = document.getElementById(id);
    if (btn) btn.disabled = !!busy;
  });
  if (activeBtn) activeBtn.disabled = !!busy;
}

async function proxySetPort(port, btn) {
  const portNum = Number(port);
  if (!portNum) return;
  setProxyButtonsBusy(true, btn);
  try {
    const resp = await api('/api/system-proxy/set-port', 'POST', { port: portNum });
    if (resp.ok) {
      proxyStatus.enabled = true;
      proxyStatus.port = resp.port || portNum;
      updateProxyStatusDisplay();
      if (typeof showMessage === 'function') showMessage(resp.message || `已切换到 ${portNum}`);
      else alert(resp.message || `已切换到 ${portNum}`);
      await loadProxyStatus();
    } else if (typeof showMessage === 'function') {
      showMessage(resp.message || '切换失败', true);
    } else {
      alert('切换失败: ' + (resp.message || '未知错误'));
    }
  } catch (e) {
    if (typeof showMessage === 'function') showMessage('切换失败: ' + e.message, true);
    else alert('切换失败: ' + e.message);
  } finally {
    setProxyButtonsBusy(false, btn);
  }
}

async function proxyConfigure(btn) {
  if (!confirm('将自动检测可用本地代理端口，并写入系统代理与环境变量。继续？')) return;
  setProxyButtonsBusy(true, btn);
  try {
    const resp = await api('/api/system-proxy/configure', 'POST', {});
    if (resp.ok) {
      if (typeof showMessage === 'function') showMessage(resp.message || '配置成功');
      else alert(resp.message || '配置成功');
      await loadProxyStatus();
    } else {
      if (typeof showMessage === 'function') showMessage(resp.message || '配置失败', true);
      else alert('配置失败: ' + (resp.message || '未知错误'));
    }
  } catch (e) {
    if (typeof showMessage === 'function') showMessage('配置失败: ' + e.message, true);
    else alert('配置失败: ' + e.message);
  } finally {
    setProxyButtonsBusy(false, btn);
  }
}

async function proxyToggle(btn) {
  const stopping = !!proxyStatus.enabled;
  if (stopping && !confirm('确定要停止系统代理并清除代理环境变量吗？')) return;
  setProxyButtonsBusy(true, btn);
  try {
    const resp = await api('/api/system-proxy/toggle', 'POST', {});
    if (resp.ok) {
      proxyStatus.enabled = !!resp.proxy_enabled;
      proxyStatus.port = resp.port || null;
      updateProxyStatusDisplay();
      if (typeof showMessage === 'function') showMessage(resp.message || '操作成功');
      else alert(resp.message || '操作成功');
      await loadProxyStatus();
    } else {
      if (typeof showMessage === 'function') showMessage(resp.message || '操作失败', true);
      else alert('操作失败: ' + (resp.message || '未知错误'));
    }
  } catch (e) {
    if (typeof showMessage === 'function') showMessage('操作失败: ' + e.message, true);
    else alert('操作失败: ' + e.message);
  } finally {
    setProxyButtonsBusy(false, btn);
  }
}

async function proxyDefault(btn) {
  if (!confirm('确定要恢复默认状态吗？\n这将关闭系统代理并清除所有代理环境变量。')) return;
  setProxyButtonsBusy(true, btn);
  try {
    const resp = await api('/api/system-proxy/default', 'POST', {});
    if (resp.ok) {
      proxyStatus.enabled = false;
      proxyStatus.port = null;
      updateProxyStatusDisplay();
      if (typeof showMessage === 'function') showMessage(resp.message || '已恢复默认状态');
      else alert(resp.message || '已恢复默认状态');
      await loadProxyStatus();
    } else {
      if (typeof showMessage === 'function') showMessage(resp.message || '操作失败', true);
      else alert('操作失败: ' + (resp.message || '未知错误'));
    }
  } catch (e) {
    if (typeof showMessage === 'function') showMessage('操作失败: ' + e.message, true);
    else alert('操作失败: ' + e.message);
  } finally {
    setProxyButtonsBusy(false, btn);
  }
}
