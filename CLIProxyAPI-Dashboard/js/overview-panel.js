let proxyStatus = { enabled: false, port: null, availablePorts: [] };
// Process-local status reported by grok2api itself (NOT the OS system-proxy panel).
let grok2apiSysProxy = { reachable: false, enabled: false, port: null, proxyUrl: '', message: '' };

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

function formatProxySynchronizationMessage(resp, fallback) {
  const sync = resp?.synchronization;
  if (!sync?.ok) return fallback;
  const details = [];
  if (sync.settings_updated) details.push(`${sync.settings_updated} 项规则`);
  if (sync.pool_nodes_updated) details.push(`${sync.pool_nodes_updated} 个池节点`);
  if (sync.cache_entries_cleared) details.push(`清除 ${sync.cache_entries_cleared} 个缓存`);
  if (resp.runtime_rebuilt) details.push('CPA 配置已重建');
  return details.length ? `${fallback}（${details.join('，')}）` : fallback;
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
      return formatProxySynchronizationMessage(resp, resp.message || `已切换到 ${port}`);
    },
    fail: '切换失败',
  },
  configure: {
    label: '检测',
    path: '/api/system-proxy/configure',
    body: () => ({}),
    onOk: (resp) => formatProxySynchronizationMessage(resp, resp.message || '配置成功'),
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
      return formatProxySynchronizationMessage(resp, resp.message || '操作成功');
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
