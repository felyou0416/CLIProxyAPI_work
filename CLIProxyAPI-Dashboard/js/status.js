// =============================================================================
// 运行时状态与控制台原语
// -----------------------------------------------------------------------------
// 账号页按钮 UI 已迁到 control-station-config/js；本文件保留：
//   - 状态轮询 refreshStatus（按固定 element id 更新灯色 / OpenClaw 禁用态）
//   - 指示灯缓存 updateIndicator / loadIndicatorStates
//   - 组锁与 spinner：withRuntimeAction
//   - 通用启停：handleActionWithIndicator
// 控制台外仍可调用的 shim：startProxy / restartProxy / stopProxy（如网络访问页）
// =============================================================================

let refreshStatusPending = false;
window.tunnelActionBusy = false;
window.proxyActionBusy = false;
window.oauthActionBusy = false;
window.dashboardActionBusy = false;
window.openclawActionBusy = false;
window.mediaProxyActionBusy = false;
// create-grok 面板（:3780）busy 锁
window['create-grokActionBusy'] = false;
window['77chatActionBusy'] = false;
// 前后端共用一把锁，避免并发改灯互相覆盖
window.grok2apiActionBusy = false;

// 指示灯逻辑名列表（含拆分后的 grok2api-frontend/backend + 系统代理）
// DOM id 默认 `${type}-status-indicator`，例外见 INDICATOR_ELEMENT_IDS
const INDICATOR_TYPES = [
  'proxy',
  'media-proxy',
  'openclaw',
  'create-grok',
  '77chat',
  'ip-helper',
  'dashboard',
  'oauth',
  'tunnel',
  // 拆分指示灯：前后端独立变色
  'grok2api-frontend',
  'grok2api-backend',
  // 系统代理 / grok2api 进程侧上报
  'system-proxy',
  'grok2api-sys-proxy',
  // 旧版合并键：只读迁移用，不再写入缓存
  'grok2api',
];
const GROK2API_DEFAULT_URL = 'http://127.0.0.1:5173/';
const INDICATOR_CACHE_KEY = 'cli-indicator-states';
// 逻辑名 → 实际 DOM id（与 control-station-config 中 indicator.id 对齐）
const INDICATOR_ELEMENT_IDS = {
  'grok2api-frontend': 'grok2api-frontend-status-indicator',
  'grok2api-backend': 'grok2api-backend-status-indicator',
  'system-proxy': 'system-proxy-status-indicator',
  'grok2api-sys-proxy': 'grok2api-sys-proxy-indicator',
  // 旧缓存/调用方可能仍传 "grok2api"，回退到前端灯
  'grok2api': 'grok2api-frontend-status-indicator',
};
// 内存态：script 加载后立刻 hydrate，渲染控制台时直接用缓存色，避免先红后绿闪一下
const INDICATOR_MEMORY = Object.create(null);
const INDICATOR_VALID_COLORS = new Set(['red', 'green', 'yellow']);

function normalizeIndicatorColor(state, fallback = 'red') {
  const color = String(state || '').trim().toLowerCase();
  return INDICATOR_VALID_COLORS.has(color) ? color : fallback;
}

function indicatorElementId(type) {
  if (INDICATOR_ELEMENT_IDS[type]) return INDICATOR_ELEMENT_IDS[type];
  return `${type}-status-indicator`;
}

function indicatorTypeFromElementId(elementId) {
  const id = String(elementId || '').trim();
  if (!id) return '';
  for (const [type, mappedId] of Object.entries(INDICATOR_ELEMENT_IDS)) {
    if (mappedId === id) return type;
  }
  if (id.endsWith('-status-indicator')) {
    return id.slice(0, -'-status-indicator'.length);
  }
  if (id.endsWith('-indicator')) {
    return id.slice(0, -'-indicator'.length);
  }
  return id;
}

// 逻辑指示灯类型 → window.*ActionBusy；busy 时 refreshStatus 不覆盖黄灯
function indicatorBusyKey(type) {
  if (type === 'media-proxy') return 'mediaProxyActionBusy';
  // Grok2API 前后端共享一把锁
  if (type === 'grok2api' || type === 'grok2api-frontend' || type === 'grok2api-backend') {
    return 'grok2apiActionBusy';
  }
  if (type === 'system-proxy' || type === 'grok2api-sys-proxy') {
    return 'systemProxyActionBusy';
  }
  // create-grok 含连字符，直接用同名 busy key
  if (type === 'create-grok') return 'create-grokActionBusy';
  return `${type}ActionBusy`;
}

function readIndicatorCacheObject() {
  try {
    const raw = localStorage.getItem(INDICATOR_CACHE_KEY);
    if (!raw) return {};
    const states = JSON.parse(raw);
    if (!states || typeof states !== 'object') return {};
    const out = {};
    for (const [type, color] of Object.entries(states)) {
      out[type] = normalizeIndicatorColor(color);
    }
    // 旧合并键迁移到拆分前后端
    if (out.grok2api) {
      if (!out['grok2api-frontend']) out['grok2api-frontend'] = out.grok2api;
      if (!out['grok2api-backend']) out['grok2api-backend'] = out.grok2api;
    }
    return out;
  } catch (e) {
    return {};
  }
}

function hydrateIndicatorMemory() {
  const states = readIndicatorCacheObject();
  for (const [type, color] of Object.entries(states)) {
    if (type === 'grok2api') continue;
    INDICATOR_MEMORY[type] = color;
  }
  return states;
}

let _lastIndicatorCacheJson = '';
let _indicatorCacheDirty = false;
let _lastSysProxyPollAt = 0;
let _lastToolHintFingerprint = '';
let _lastProxySummaryFingerprint = '';

function applyIndicatorDom(type, state) {
  const el = document.getElementById(indicatorElementId(type));
  if (!el) return false;
  const color = normalizeIndicatorColor(state);
  const nextClass = `status-indicator-dot ${color}`;
  if (el.className === nextClass) return false;
  el.className = nextClass;
  return true;
}

function loadIndicatorStates() {
  // 先灌内存，再刷 DOM；控制台尚未挂载时至少保住 memory，供 render 读色
  const states = hydrateIndicatorMemory();
  for (const [type, color] of Object.entries(states)) {
    if (type === 'grok2api') continue;
    applyIndicatorDom(type, color);
  }
}
window.loadIndicatorStates = loadIndicatorStates;

function buildIndicatorCacheObject() {
  const states = {};
  for (const type of INDICATOR_TYPES) {
    if (type === 'grok2api') continue;
    if (INDICATOR_MEMORY[type]) states[type] = normalizeIndicatorColor(INDICATOR_MEMORY[type]);
  }
  return states;
}

function saveIndicatorStates(force = false) {
  const states = buildIndicatorCacheObject();
  const json = JSON.stringify(states);
  if (!force && json === _lastIndicatorCacheJson) {
    _indicatorCacheDirty = false;
    return;
  }
  try {
    if (Object.keys(states).length) {
      localStorage.setItem(INDICATOR_CACHE_KEY, json);
      _lastIndicatorCacheJson = json;
      _indicatorCacheDirty = false;
    }
  } catch (e) { /* ignore */ }
}
window.saveIndicatorStates = saveIndicatorStates;

// 供 control-station 渲染时直接取缓存色，避免 HTML 先写 red 再被改色
window.getCachedIndicatorColor = function(elementIdOrType, fallback = 'red') {
  const raw = String(elementIdOrType || '').trim();
  if (!raw) return normalizeIndicatorColor(fallback);
  if (INDICATOR_MEMORY[raw]) return INDICATOR_MEMORY[raw];
  const type = indicatorTypeFromElementId(raw) || raw;
  if (INDICATOR_MEMORY[type]) return INDICATOR_MEMORY[type];
  return normalizeIndicatorColor(fallback);
};

// options.persist=false is used by load/refresh internals to avoid write thrash.
window.updateIndicator = function(type, state, options = {}) {
  const color = normalizeIndicatorColor(state);
  const key = String(type || '').trim();
  if (!key) return;
  const prev = INDICATOR_MEMORY[key];
  const memoryChanged = prev !== color;
  if (memoryChanged) {
    INDICATOR_MEMORY[key] = color;
    _indicatorCacheDirty = true;
  }
  // 仅当内存变化或 DOM 颜色不一致时写 class，避免 8s 轮询反复触发布局
  applyIndicatorDom(key, color);
  if (options.persist !== false && (memoryChanged || _indicatorCacheDirty)) {
    saveIndicatorStates();
  }
};

// script 一加载就 hydrate，抢在 showSection/mount 之前
(() => {
  const states = hydrateIndicatorMemory();
  _lastIndicatorCacheJson = JSON.stringify(states);
})();

function setHtml(id, html) {
  const el = document.getElementById(id);
  if (!el) return;
  if (el.innerHTML === html) return;
  el.innerHTML = html;
}

function shouldRefreshSysProxySide() {
  try {
    if (typeof getActiveSection === 'function' && getActiveSection() === 'account') return true;
  } catch (e) { /* ignore */ }
  return !!document.getElementById('system-proxy-status-indicator')
    || !!document.getElementById('grok2api-sys-proxy-indicator');
}

function setRuntimeIndicator(type, running, busyFlag) {
  if (busyFlag) return;
  window.updateIndicator(type, running ? 'green' : 'red', { persist: false });
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
  // 工具页日志区不在账号页；元素缺失时直接跳过，避免每 8s 拼大字符串
  const proxyLog = document.getElementById('log-proxy-main');
  const proxyStatus = document.getElementById('status-proxy-main');
  const hasToolsUi = !!(proxyLog || proxyStatus
    || document.getElementById('status-proxy-main-chip')
    || document.getElementById('tools-summary-proxy'));
  if (!hasToolsUi) return;

  const proxyStateText = statusText(s.proxy_running);
  const selectedAccountText = summarizePool(s.selected_auths, s.selected_auth || t('common.notSelected', 'Not selected'));
  const appliedAccountText = summarizePool(s.applied_auths, s.applied_auth || t('common.notSelected', 'Not selected'));
  const selectedProviderText = summarizeProviders(s.selected_providers, s.selected_provider || t('common.notSelected', 'Not selected'));
  const appliedProviderText = summarizeProviders(s.applied_providers, s.applied_provider || t('common.notSelected', 'Not selected'));
  const fingerprint = [
    proxyStateText,
    !!s.exposure_enabled,
    selectedAccountText,
    selectedProviderText,
    appliedAccountText,
    appliedProviderText,
    !!s.restart_required,
    s.local_proxy_url || s.proxy_url || '',
    s.exposure_url || '',
    s.api_key || '',
    s.proxy_stdout || '',
    s.proxy_stderr || '',
  ].join('');
  if (fingerprint === _lastProxySummaryFingerprint) return;
  _lastProxySummaryFingerprint = fingerprint;

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
    const next = proxySummary || t('common.noLogs', 'No logs yet');
    if (proxyLog.textContent !== next) proxyLog.textContent = next;
    setLogVisible(proxyLog, true);
  }

  if (proxyStatus) {
    if (proxyStatus.textContent !== proxyStateText) proxyStatus.textContent = proxyStateText;
    const nextClass = 'tool-status ' + (s.proxy_running ? 'tool-running' : 'tool-stopped');
    if (proxyStatus.className !== nextClass) proxyStatus.className = nextClass;
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
    // 系统代理侧只在账号页需要时刷新，且节流到 20s，避免每 8s 额外 1~2 个请求
    if (shouldRefreshSysProxySide()) {
      const now = Date.now();
      if (now - _lastSysProxyPollAt > 20000) {
        _lastSysProxyPollAt = now;
        if (typeof loadGrok2ApiSysProxyStatus === 'function') {
          loadGrok2ApiSysProxyStatus().catch(() => {});
        } else if (typeof loadProxyStatus === 'function') {
          loadProxyStatus().catch(() => {});
        }
      }
    }
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
    if (grok2apiTitle && grok2apiTitle.href !== grok2apiUrl) grok2apiTitle.href = grok2apiUrl;
    setText('proxy-exposure-url', s.exposure_url || '-', '-');
    setText('proxy-api-key', s.api_key || 'cliproxyapi', 'cliproxyapi');
    setText('exposure-mode-status', s.exposure_enabled ? 'Enabled (LAN)' : 'Disabled', 'Disabled');

    // 灯色无变化时 updateIndicator 会短路；busy 组保持黄灯不被覆盖
    setRuntimeIndicator('proxy', s.proxy_running, window.proxyActionBusy);
    setRuntimeIndicator('media-proxy', s.media_proxy_running, window.mediaProxyActionBusy);
    setRuntimeIndicator('tunnel', s.tunnel_running, window.tunnelActionBusy);
    setRuntimeIndicator('oauth', s.oauth_manager_running, window.oauthActionBusy);
    setRuntimeIndicator('openclaw', s.openclaw_running, window.openclawActionBusy);
    setRuntimeIndicator('create-grok', s.create_grok_running, window['create-grokActionBusy']);
    const createGrokTitle = document.getElementById('create-grok-title-link');
    const createGrokUrl = s.create_grok_url || 'http://127.0.0.1:3780/';
    if (createGrokTitle && createGrokTitle.href !== createGrokUrl) createGrokTitle.href = createGrokUrl;

    setRuntimeIndicator('77chat', s.chat77_running, window['77chatActionBusy']);
    const chat77Title = document.getElementById('chat77-title-link');
    const chat77Url = s.chat77_url || 'http://127.0.0.1:90/';
    if (chat77Title && chat77Title.href !== chat77Url) chat77Title.href = chat77Url;
    if (!window.dashboardActionBusy) {
      window.updateIndicator('dashboard', 'green', { persist: false });
    }
    setRuntimeIndicator('grok2api-frontend', s.grok2api_frontend_running, window.grok2apiActionBusy);
    setRuntimeIndicator('grok2api-backend', s.grok2api_backend_running, window.grok2apiActionBusy);

    // 仅状态真变时写 localStorage
    if (_indicatorCacheDirty) saveIndicatorStates();
    // 按钮始终可点：不按 running 状态置灰/禁用；仅操作中的组锁由 withRuntimeAction 负责。

    setText('summary-selected-auth-count', selectedAuthCount, '0');
    setText('summary-auth-count', authCount, '0');
    setText('auth-count-badge', authCount, '0');
    setText('summary-device-login', deviceText, 'Not running');
    setText('summary-proxy-status', proxyText, 'Not running');

    updateProxyToolSummary(s);
    if (typeof updateToolCommandHints === 'function') {
      const hintFp = `${s.cli_exe || ''}|${s.base_config || ''}|${s.proxy_root || ''}|${s.dashboard_root || ''}`;
      if (hintFp !== _lastToolHintFingerprint) {
        _lastToolHintFingerprint = hintFp;
        updateToolCommandHints(s);
      }
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

async function copyStatusField(btn, elementId) {
  const el = document.getElementById(elementId);
  const text = String(el?.textContent || '').trim();
  if (!text) return;
  if (typeof copyDocText === 'function') {
    return copyDocText(btn, text);
  }
  try {
    await navigator.clipboard.writeText(text);
    if (btn) {
      const original = btn.textContent;
      btn.classList.add('copied');
      btn.textContent = '已复制';
      setTimeout(() => {
        btn.classList.remove('copied');
        btn.textContent = original;
      }, 1500);
    }
  } catch (err) {
    if (typeof showMessage === 'function') {
      showMessage('复制失败，请手动复制。', true);
    }
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

// 只锁同一 control-group 内的兄弟按钮，其它服务组仍可点
function getRuntimeActionGroupButtons(button) {
  if (!button) return [];
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

// 组级互斥 + spinner；整站其它组不受影响
async function withRuntimeAction(button, label, task) {
  if (!button) return task();
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

// 标准服务启停：黄灯 → POST → 可选 waitFor 轮询 → 失败回写 errorIndicatorState
// 控制台 service 按钮最终都落到这里
async function handleActionWithIndicator(type, button, label, actionApiUrl, errorIndicatorState, options = {}) {
  // grok2api-frontend/backend 会解析到同一 busyKey
  const busyKey = indicatorBusyKey(type);
  window[busyKey] = true;
  // 黄灯表示进行中；persist 默认开启，中途刷新也能短暂保留
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

// 兼容旧调用点（控制台外，如 network-access.js 的 onclick="startProxy()"）
// 账号页按钮已改走 control-station 配置分发，不再依赖下列函数名
async function startProxy(button) {
  return handleActionWithIndicator('proxy', button, t('runtime.startingProxy', '启动'), '/api/start-project', 'red');
}

async function restartProxy(button) {
  return handleActionWithIndicator('proxy', button, t('runtime.restartingProxy', '重启'), '/api/restart-proxy');
}

async function stopProxy(button) {
  return handleActionWithIndicator('proxy', button, t('runtime.stoppingProxy', '停止'), '/api/stop-proxy', 'green');
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
