let localWorkspaceLoaded = false;

function localWorkspaceEscape(value) {
  return String(value ?? '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

function localWorkspaceTitle(item) {
  const title = item.url
    ? { text: item.label, href: item.url }
    : { text: item.label };
  if (item.builtin === 'create-grok') title.id = 'create-grok-title-link';
  if (item.builtin === '77chat') title.id = 'chat77-title-link';
  if (item.builtin === 'grok2api-frontend') title.id = 'grok2api-title-link';
  return title;
}

function localWorkspaceButton(item, operation) {
  const label = { start: '启动', restart: '重启', stop: '停止' }[operation] || operation;
  return {
    action: 'local-service',
    op: operation,
    localService: item.id,
    label,
    className: operation === 'stop' ? 'danger' : operation === 'restart' ? 'secondary' : '',
  };
}

function renderLocalWorkspace(item) {
  const root = document.getElementById('local-workspace-root');
  if (!root) return;
  if (item.config_error) {
    root.hidden = false;
    root.innerHTML = `<div class="local-workspace-error">本地配置无效：${localWorkspaceEscape(item.config_error)}</div>`;
    return;
  }
  if (!item.configured) {
    root.hidden = true;
    root.innerHTML = '';
    return;
  }

  const serviceGroups = (item.services || []).map((service) => ({
    kind: 'service',
    id: `local-${service.id}`,
    icon: service.icon || '',
    title: localWorkspaceTitle(service),
    indicator: service.builtin ? {
      id: `${service.builtin === '77chat' ? 'chat77' : service.builtin}-status-indicator`,
      color: 'red',
    } : undefined,
    buttons: (service.actions || []).map((operation) => localWorkspaceButton(service, operation)),
  }));
  const linkGroups = (item.links || []).map((link) => ({
    kind: 'service',
    id: `local-${link.id}`,
    icon: link.icon || '',
    title: localWorkspaceTitle(link),
    buttons: [],
  }));
  const groups = [...serviceGroups, ...linkGroups];
  if (!groups.length) {
    root.hidden = true;
    root.innerHTML = '';
    return;
  }

  if (typeof renderControlStationHtml !== 'function') {
    root.hidden = false;
    root.innerHTML = '<div class="local-workspace-error">本地服务渲染器未就绪。</div>';
    return;
  }
  root.hidden = false;
  root.innerHTML = `<div class="local-workspace-label">本地服务</div>${renderControlStationHtml([{
    grids: [{ className: 'control-station-layer-grid', groups }],
  }])}`;
}

async function runLocalWorkspaceAction(button, serviceId, operation) {
  if (!serviceId || !operation || button.disabled) return;
  const label = button.textContent.trim() || '执行';
  try {
    return await withRuntimeAction(button, label, async () => {
      const result = await api('/api/local-workspace/action', 'POST', {
        service_id: serviceId,
        operation,
      });
      showMessage(result.message || `${label}命令已发出。`);
    });
  } catch (error) {
    showMessage(error.message || `${label}失败。`, true);
  }
}

function bindLocalWorkspace() {
  const root = document.getElementById('local-workspace-root');
  if (!root || root.dataset.csBound === '1') return;
  if (typeof bindControlStation === 'function') {
    bindControlStation(root);
  }
}

async function loadLocalWorkspace(force = false) {
  if (localWorkspaceLoaded && !force) {
    bindLocalWorkspace();
    return;
  }
  try {
    const response = await api('/api/local-workspace');
    renderLocalWorkspace(response.item || {});
    localWorkspaceLoaded = true;
  } catch (error) {
    const root = document.getElementById('local-workspace-root');
    if (root) {
      root.hidden = false;
      root.innerHTML = `<div class="local-workspace-error">本地配置加载失败：${localWorkspaceEscape(error.message || error)}</div>`;
    }
  }
  bindLocalWorkspace();
}

window.loadLocalWorkspace = loadLocalWorkspace;
window.runLocalWorkspaceAction = runLocalWorkspaceAction;
