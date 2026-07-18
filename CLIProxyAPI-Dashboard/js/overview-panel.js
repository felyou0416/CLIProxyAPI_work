let overviewPanelLoaded = false;
let proxyStatus = { enabled: false, port: null, availablePorts: [] };
// Process-local status reported by grok2api itself (NOT the OS system-proxy panel).
let grok2apiSysProxy = { reachable: false, enabled: false, port: null, proxyUrl: '', message: '' };

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

function updateGrok2ApiSysProxyDisplay() {
  const portEl = document.getElementById('grok2api-sys-proxy-port');
  const indicator = document.getElementById('grok2api-sys-proxy-indicator');
  const currentPort = Number(grok2apiSysProxy.port || 0) || null;
  const enabled = !!grok2apiSysProxy.enabled;
  const reachable = !!grok2apiSysProxy.reachable;

  if (portEl) {
    if (!reachable) {
      portEl.innerHTML = '<span style="color: var(--danger, #aa0000);">后端未响应</span>';
      portEl.title = grok2apiSysProxy.message || '无法连接 grok2api /system-proxy';
    } else if (enabled && currentPort) {
      portEl.innerHTML = `端口 <span style="color: var(--success, #00aa00);">${currentPort}</span>`;
      portEl.title = `来自 grok2api 进程上报：${grok2apiSysProxy.proxyUrl || ('http://127.0.0.1:' + currentPort)}`;
    } else if (enabled) {
      portEl.innerHTML = '<span style="color: var(--warning, #b8860b);">已启用 · 端口未知</span>';
      portEl.title = 'grok2api 报告系统代理已启用，但未解析到端口';
    } else {
      portEl.innerHTML = '<span style="color: var(--danger, #aa0000);">未启用</span>';
      portEl.title = 'grok2api 报告当前不会重写本机出口端口';
    }
  }

  let sysColor = 'red';
  let sysTitle = 'grok2api 报告系统代理未启用';
  if (!reachable) {
    sysColor = 'red';
    sysTitle = grok2apiSysProxy.message || '无法连接 grok2api';
  } else if (enabled && currentPort) {
    sysColor = 'green';
    sysTitle = `grok2api 实际解析端口 ${currentPort}`;
  } else if (enabled) {
    sysColor = 'yellow';
    sysTitle = 'grok2api 报告已启用但端口未知';
  }
  if (typeof window.updateIndicator === 'function') {
    window.updateIndicator('grok2api-sys-proxy', sysColor);
  }
  if (indicator) {
    indicator.title = sysTitle;
  }
}

async function loadGrok2ApiSysProxyStatus() {
  try {
    const resp = await api('/api/grok2api/system-proxy');
    if (!resp) return;
    grok2apiSysProxy = {
      reachable: !!resp.reachable,
      enabled: !!resp.enabled,
      port: resp.port || null,
      proxyUrl: resp.proxy_url || '',
      message: resp.message || '',
    };
    updateGrok2ApiSysProxyDisplay();
  } catch (e) {
    grok2apiSysProxy = {
      reachable: false,
      enabled: false,
      port: null,
      proxyUrl: '',
      message: e.message || String(e),
    };
    updateGrok2ApiSysProxyDisplay();
  }
}

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

  const systemColor = proxyStatus.enabled ? 'green' : 'red';
  const systemTitle = proxyStatus.enabled
    ? `系统代理已启用${currentPort ? ` (端口 ${currentPort})` : ''}`
    : '系统代理未启用';
  if (typeof window.updateIndicator === 'function') {
    window.updateIndicator('system-proxy', systemColor);
  }
  if (indicator) {
    indicator.title = systemTitle;
  }

  if (!statusDiv) return;

  // Compact one-line status (shown in the system-proxy heading).
  let html = proxyStatus.enabled
    ? `<span style="color: var(--success, #00aa00);">已启用</span>${currentPort ? ` · ${currentPort}` : ''}`
    : `<span style="color: var(--danger, #aa0000);">未启用</span>`;
  if (proxyStatus.availablePorts && proxyStatus.availablePorts.length > 0) {
    html += ` · 可用: ${proxyStatus.availablePorts.join('/')}`;
  }
  statusDiv.innerHTML = html;
  statusDiv.title = proxyStatus.enabled
    ? `系统代理已启用${currentPort ? ` (端口 ${currentPort})` : ''}${proxyStatus.availablePorts?.length ? ` · 可用端口: ${proxyStatus.availablePorts.join(', ')}` : ''}`
    : '系统代理未启用';
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
  // Always refresh process-local status from grok2api itself.
  await loadGrok2ApiSysProxyStatus();
}

// 系统代理组按钮整体禁用（端口 + 检测/停用/恢复），避免并发切换
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

function notifyProxy(message, isError = false) {
  if (typeof showMessage === 'function') showMessage(message, isError);
  else if (isError) alert(message);
  else alert(message);
}

// 系统代理动作表：控制台 sys-proxy 分发与旧 proxySetPort 等 shim 共用
const SYSTEM_PROXY_ACTIONS = {
  'set-port': {
    label: '切换',
    path: '/api/system-proxy/set-port',
    body: ({ port }) => ({ port }),
    onOk: (resp, { port }) => {
      proxyStatus.enabled = true;
      proxyStatus.port = resp.port || port;
      updateProxyStatusDisplay();
      return resp.message || `已切换到 ${port}`;
    },
    fail: '切换失败',
  },
  configure: {
    label: '检测',
    path: '/api/system-proxy/configure',
    body: () => ({}),
    onOk: (resp) => resp.message || '配置成功',
    fail: '配置失败',
  },
  toggle: {
    label: '切换',
    path: '/api/system-proxy/toggle',
    body: () => ({}),
    onOk: (resp) => {
      proxyStatus.enabled = !!resp.proxy_enabled;
      proxyStatus.port = resp.port || null;
      updateProxyStatusDisplay();
      return resp.message || '操作成功';
    },
    fail: '操作失败',
  },
  default: {
    label: '恢复',
    path: '/api/system-proxy/default',
    body: () => ({}),
    onOk: (resp) => {
      proxyStatus.enabled = false;
      proxyStatus.port = null;
      updateProxyStatusDisplay();
      return resp.message || '已恢复默认状态';
    },
    fail: '操作失败',
  },
};

// op: set-port | configure | toggle | default（与 control-station-config 中 sys-proxy 对齐）
async function runSystemProxyAction(op, btn, options = {}) {
  const def = SYSTEM_PROXY_ACTIONS[op];
  if (!def) {
    notifyProxy(`未知系统代理操作: ${op}`, true);
    return;
  }
  if (op === 'set-port') {
    const portNum = Number(options.port);
    if (!portNum) return;
    options = { ...options, port: portNum };
  }

  const run = async () => {
    setProxyButtonsBusy(true, btn);
    try {
      const resp = await api(def.path, 'POST', def.body(options));
      if (resp.ok) {
        notifyProxy(def.onOk(resp, options));
        await loadProxyStatus();
      } else {
        notifyProxy(resp.message || def.fail, true);
      }
    } catch (e) {
      notifyProxy(`${def.fail}: ${e.message}`, true);
    } finally {
      setProxyButtonsBusy(false, btn);
    }
  };

  if (btn && typeof withRuntimeAction === 'function') {
    return withRuntimeAction(btn, def.label, run);
  }
  return run();
}

// 旧入口保留，内部统一走 runSystemProxyAction
async function proxySetPort(port, btn) {
  return runSystemProxyAction('set-port', btn, { port });
}

async function proxyConfigure(btn) {
  return runSystemProxyAction('configure', btn);
}

async function proxyToggle(btn) {
  return runSystemProxyAction('toggle', btn);
}

async function proxyDefault(btn) {
  return runSystemProxyAction('default', btn);
}

window.runSystemProxyAction = runSystemProxyAction;
