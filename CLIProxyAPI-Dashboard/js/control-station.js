// =============================================================================
// 控制台渲染 + 点击分发
// -----------------------------------------------------------------------------
// 配置：window.CONTROL_STATION_LAYERS（control-station-config.js）
// 挂载：showSection('account') → mountControlStation()（core.js）
//
// 加载依赖：
//   启动时需要 status.js 原语（handleActionWithIndicator / withRuntimeAction）
//   特例函数在「点击时」从 window 解析，避免 script 顺序把 tools/firewall 绑死
//
// 幂等：同一 root 只渲染一次、只绑一次 click；dataset.mounted / dataset.csBound
// =============================================================================

function escapeHtml(value) {
  return String(value ?? '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

function attr(name, value) {
  if (value === undefined || value === null || value === '') return '';
  return ` ${name}="${escapeHtml(value)}"`;
}

function classAttr(...parts) {
  const value = parts.filter(Boolean).join(' ').trim();
  return value ? ` class="${escapeHtml(value)}"` : '';
}

// 标题：外链 / 站内 section 跳转 / 纯文本
function renderTitle(title = {}) {
  const text = escapeHtml(title.text || '');
  const i18n = attr('data-i18n', title.i18n);
  const id = attr('id', title.id);
  const titleAttr = attr('title', title.titleAttr);

  if (title.section) {
    // 站内导航：阻止默认 hash，改走 showSection
    return `<a href="${escapeHtml(title.href || `#${title.section}`)}" class="control-group-title-link"${id}${i18n}${titleAttr} data-cs-section="${escapeHtml(title.section)}">${text}</a>`;
  }
  if (title.hrefs && Array.isArray(title.hrefs)) {
    return `<div style="display: flex; flex-direction: row; gap: 8px; align-items: center; white-space: nowrap;">` +
      title.hrefs.map((link, idx) => {
        const linkId = idx === 0 ? id : '';
        const linkText = escapeHtml(link.text || '');
        return `<a href="${escapeHtml(link.href)}" target="_blank" class="control-group-title-link"${linkId}${titleAttr}>${linkText}</a>`;
      }).join(' <span style="opacity: 0.3;">/</span> ') + `</div>`;
  }
  if (title.href) {
    return `<a href="${escapeHtml(title.href)}" target="_blank" class="control-group-title-link"${id}${i18n}${titleAttr}>${text}</a>`;
  }
  return `<span class="control-group-title-link"${id}${i18n}${titleAttr}>${text}</span>`;
}

function renderIndicator(indicator) {
  if (!indicator?.id) return '';
  // 优先用 localStorage 缓存色，避免 remount / 刷新时先红后绿闪一下
  const fallback = indicator.color || 'red';
  const color = (typeof window.getCachedIndicatorColor === 'function')
    ? window.getCachedIndicatorColor(indicator.id, fallback)
    : fallback;
  return `<span id="${escapeHtml(indicator.id)}" class="status-indicator-dot ${escapeHtml(color)}"${attr('title', indicator.title)}></span>`;
}

function renderHeading(group) {
  return `
    <div class="control-group-heading">
      <span class="control-group-icon">${escapeHtml(group.icon || '')}</span>
      ${renderTitle(group.title)}
      ${renderIndicator(group.indicator)}
    </div>
  `;
}

// 把配置字段落到 data-cs-*，点击时再读回
function buttonDataAttrs(btn) {
  const parts = [
    attr('data-cs-action', btn.action),
    attr('data-cs-op', btn.op),
    attr('data-cs-type', btn.type),
    attr('data-cs-api', btn.api),
    attr('data-cs-error-state', btn.errorState),
    attr('data-cs-mode', btn.mode),
    attr('data-cs-port', btn.port),
    attr('data-cs-label', btn.label),
  ];
  if (btn.wait) {
    // wait 结构较复杂，序列化后挂属性；分发时 JSON.parse
    parts.push(attr('data-cs-wait', JSON.stringify(btn.wait)));
  }
  return parts.join('');
}

function renderActionButton(btn) {
  const classes = ['runtime-action-btn', btn.className].filter(Boolean).join(' ');
  return `
    <button type="button"${classAttr(classes)}${attr('id', btn.id)}${attr('title', btn.title)}${attr('data-i18n', btn.i18n)}${buttonDataAttrs(btn)}>
      ${escapeHtml(btn.label || '')}
    </button>
  `;
}

function renderServiceGroup(group) {
  const buttons = (group.buttons || []).map(renderActionButton).join('');
  return `
    <div class="control-group"${attr('id', group.groupId)}${attr('title', group.groupTitle)} data-cs-group="${escapeHtml(group.id || '')}">
      ${renderHeading(group)}
      <div class="control-pair">
        ${buttons}
      </div>
    </div>
  `;
}

function renderStatusGroup(group) {
  return `
    <div class="control-group"${attr('id', group.groupId)}${attr('title', group.groupTitle)} data-cs-group="${escapeHtml(group.id || '')}">
      ${renderHeading(group)}
      <div class="control-pair control-pair-status"${attr('title', group.statusTitle)}>
        <span id="${escapeHtml(group.statusId)}" class="control-status-text">${escapeHtml(group.statusText || '')}</span>
      </div>
    </div>
  `;
}

function renderSystemProxyGroup(group) {
  // 端口按钮也走 sys-proxy 分发，op 固定为 set-port
  const portButtons = (group.ports || []).map((item) => renderActionButton({
    action: 'sys-proxy',
    op: 'set-port',
    port: item.port,
    id: item.id || `proxy-port-${item.port}-btn`,
    label: String(item.port),
    className: 'secondary',
    title: item.title,
  })).join('');
  const actionButtons = (group.buttons || []).map(renderActionButton).join('');
  return `
    <div class="control-group"${attr('id', group.groupId)} data-cs-group="${escapeHtml(group.id || '')}">
      ${renderHeading(group)}
      <div class="control-pair">
        ${portButtons}
        ${actionButtons}
      </div>
    </div>
  `;
}

function renderGroup(group) {
  if (group.kind === 'status') return renderStatusGroup(group);
  if (group.kind === 'system-proxy') return renderSystemProxyGroup(group);
  return renderServiceGroup(group);
}

function renderGrid(grid) {
  const groups = (grid.groups || []).map(renderGroup).join('');
  return `<div${classAttr(grid.className || 'control-station-layer-grid')}>${groups}</div>`;
}

function renderLayer(layer) {
  const grids = (layer.grids || []).map(renderGrid).join('');
  return `<section class="control-station-layer">${grids}</section>`;
}

function renderControlStationHtml(layers) {
  return (layers || []).map(renderLayer).join('');
}

// 配置里的 wait → handleActionWithIndicator 的 options
function buildWaitOptions(wait) {
  if (!wait || !wait.field) return {};
  const field = wait.field;
  const expect = wait.expect !== false;
  const readyMessage = wait.readyMessageKey && typeof t === 'function'
    ? t(wait.readyMessageKey, wait.readyMessage || '')
    : (wait.readyMessage || undefined);
  const timeoutMessage = wait.timeoutMessageKey && typeof t === 'function'
    ? t(wait.timeoutMessageKey, wait.timeoutMessage || '')
    : (wait.timeoutMessage || undefined);
  return {
    // 注意运算符优先级：先 !! 再 === expect
    waitFor: (status) => (!!status?.[field]) === expect,
    timeoutMs: wait.timeoutMs,
    intervalMs: wait.intervalMs,
    readyMessage,
    timeoutMessage,
  };
}

function parseWaitAttr(raw) {
  if (!raw) return null;
  try {
    return JSON.parse(raw);
  } catch (e) {
    return null;
  }
}

// 单一分发入口：根据 data-cs-action 路由到对应实现
async function dispatchControlStationClick(button) {
  const action = button.dataset.csAction;
  const op = button.dataset.csOp || '';
  const label = button.dataset.csLabel || button.textContent.trim() || '处理';

  if (action === 'service') {
    if (typeof handleActionWithIndicator !== 'function') {
      showMessage('运行时动作未就绪。', true);
      return;
    }
    const type = button.dataset.csType;
    const apiUrl = button.dataset.csApi;
    if (!type || !apiUrl) return;
    const errorState = button.dataset.csErrorState || undefined;
    const waitOpts = buildWaitOptions(parseWaitAttr(button.dataset.csWait));
    return handleActionWithIndicator(type, button, label, apiUrl, errorState, waitOpts);
  }

  if (action === 'dashboard') {
    // 面板自启停：必须传 button，才能触发组内 spinner / 互斥
    if (op === 'start' && typeof runDashboardScript === 'function') {
      return runDashboardScript(button.dataset.csMode || 'ps', button);
    }
    if (op === 'restart' && typeof restartDashboardPanel === 'function') {
      return restartDashboardPanel(button);
    }
    if (op === 'stop' && typeof stopDashboardPanel === 'function') {
      return stopDashboardPanel(button);
    }
    showMessage('面板控制未就绪。', true);
    return;
  }

  if (action === 'ip-helper') {
    if (typeof setIpHelperService !== 'function') {
      showMessage('IP Helper 未就绪。', true);
      return;
    }
    return setIpHelperService(op, button);
  }

  if (action === 'sys-proxy') {
    if (typeof runSystemProxyAction !== 'function') {
      showMessage('系统代理控制未就绪。', true);
      return;
    }
    const port = button.dataset.csPort ? Number(button.dataset.csPort) : undefined;
    return runSystemProxyAction(op, button, { port });
  }
}

function bindControlStation(root) {
  if (!root || root.dataset.csBound === '1') return;
  root.dataset.csBound = '1';

  root.addEventListener('click', (event) => {
    // 标题站内跳转（如 IP Helper → 防火墙页）
    const sectionLink = event.target.closest('[data-cs-section]');
    if (sectionLink && root.contains(sectionLink)) {
      event.preventDefault();
      const name = sectionLink.getAttribute('data-cs-section');
      if (name && typeof showSection === 'function') showSection(name);
      return;
    }

    const button = event.target.closest('button[data-cs-action]');
    if (!button || !root.contains(button) || button.disabled) return;
    event.preventDefault();
    Promise.resolve(dispatchControlStationClick(button)).catch((err) => {
      if (typeof showMessage === 'function') {
        showMessage(err?.message || String(err), true);
      }
    });
  });
}

// 账号页挂载入口：渲染 HTML + 绑定委托（可重复调用，默认不重复渲染）
function mountControlStation(force = false) {
  const root = document.getElementById('control-station-root');
  if (!root) return false;

  const layers = window.CONTROL_STATION_LAYERS;
  if (!Array.isArray(layers) || !layers.length) {
    console.error('CONTROL_STATION_LAYERS 缺失或为空');
    return false;
  }

  if (force || root.dataset.mounted !== '1') {
    // 渲染前先 hydrate 内存缓存，renderIndicator 才能写出正确颜色
    if (typeof loadIndicatorStates === 'function') loadIndicatorStates();
    root.innerHTML = renderControlStationHtml(layers);
    root.dataset.mounted = '1';
    // 配置里的 data-i18n 需要再刷一遍语言
    if (typeof applyLanguage === 'function') applyLanguage();
    // 再刷一次 DOM（双保险：兼容旧缓存键 / 延迟挂载的 id）
    if (typeof loadIndicatorStates === 'function') loadIndicatorStates();
  }

  bindControlStation(root);
  return true;
}

window.mountControlStation = mountControlStation;
window.renderControlStationHtml = renderControlStationHtml;
window.dispatchControlStationClick = dispatchControlStationClick;
