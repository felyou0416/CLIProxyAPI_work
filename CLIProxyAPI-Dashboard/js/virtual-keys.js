/**
 * Virtual API Key Management Panel
 *
 * Provides UI for creating, editing, deleting and monitoring
 * virtual API keys that can be distributed to other users.
 */

let virtualKeysLoaded = false;
let virtualKeysItems = [];

function vkEscape(value) {
  return String(value ?? '')
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#39;');
}

function vkFormatTime(timestamp) {
  const value = Number(timestamp || 0);
  if (!value) return '-';
  try {
    return new Date(value * 1000).toLocaleString();
  } catch {
    return '-';
  }
}

function vkFormatTokens(count) {
  const value = Number(count || 0);
  if (!value) return '0';
  if (value >= 1000000) return `${(value / 1000000).toFixed(1)}M`;
  if (value >= 1000) return `${(value / 1000).toFixed(1)}K`;
  return String(value);
}

function vkUsageBar(used, max) {
  if (!max) return '<span class="pill off">无限</span>';
  const percent = Math.min(100, Math.round((used / max) * 100));
  const statusClass = percent >= 90 ? 'warn' : percent >= 60 ? 'ok' : 'ok';
  return `
    <div class="vk-usage-bar">
      <div class="vk-usage-fill ${statusClass}" style="width: ${percent}%"></div>
    </div>
    <small>${vkFormatTokens(used)} / ${vkFormatTokens(max)} (${percent}%)</small>
  `;
}

function vkStatusPill(item) {
  if (item.expired) return '<span class="pill warn">已过期</span>';
  if (!item.enabled) return '<span class="pill off">已禁用</span>';
  return '<span class="pill ok">活跃</span>';
}

function vkKeyRowHtml(item) {
  const modelsText = (item.allowed_models || []).length
    ? item.allowed_models.join(', ')
    : '全部模型';
  const rpmText = item.rate_limit_rpm ? `${item.rate_limit_rpm} RPM` : '无限制';
  const noteTooltip = item.note ? `备注: ${vkEscape(item.note)}` : '暂无备注';

  return `
    <div class="vk-row" data-vk-id="${vkEscape(item.id)}" title="${noteTooltip}">
      <!-- info col -->
      <div class="vk-col-info">
        <div style="display: flex; align-items: center; gap: 8px;">
          <strong style="white-space: nowrap; overflow: hidden; text-overflow: ellipsis; max-width: 140px;" title="${vkEscape(item.name || '未命名')}">${vkEscape(item.name || '未命名')}</strong>
          ${vkStatusPill(item)}
        </div>
        <code style="font-size: 11px; color: var(--accent); margin-top: 2px;">${vkEscape(item.key_masked)}</code>
      </div>

      <!-- stats col -->
      <div class="vk-col-stats">
        <div class="vk-col-stat">
          <span class="vk-col-stat-label">Token 用量</span>
          ${vkUsageBar(item.used_tokens, item.max_tokens)}
        </div>
        <div class="vk-col-stat">
          <span class="vk-col-stat-label">请求次数</span>
          ${vkUsageBar(item.used_requests, item.max_requests)}
        </div>
      </div>

      <!-- limits col -->
      <div class="vk-col-limits">
        <div style="display: flex; align-items: center; gap: 4px;">
          <span style="font-weight: 600; color: var(--text-soft);">RPM:</span>
          <span>${vkEscape(rpmText)}</span>
        </div>
        <div class="vk-models-text" title="${vkEscape(modelsText)}" style="display: flex; align-items: center; gap: 4px;">
          <span style="font-weight: 600; color: var(--text-soft);">模型:</span>
          <span class="vk-models-text-span" style="white-space: nowrap; overflow: hidden; text-overflow: ellipsis; max-width: 120px;">${vkEscape(modelsText)}</span>
        </div>
      </div>

      <!-- meta col -->
      <div class="vk-col-meta">
        <div>创建: ${vkFormatTime(item.created_at)}</div>
        ${item.expires_at ? `<div>过期: ${vkFormatTime(item.expires_at)}</div>` : '<div>过期: 永不过期</div>'}
      </div>

      <!-- actions col -->
      <div class="vk-col-actions">
        <button class="secondary vk-copy-btn" type="button" data-vk-reveal="${vkEscape(item.id)}" title="复制 Key" style="display: inline-flex; align-items: center; gap: 2px;">
          📋 复制
        </button>
        <button class="secondary vk-toggle-btn" type="button" data-vk-toggle="${vkEscape(item.id)}" data-vk-enabled="${item.enabled}">
          ${item.enabled ? '禁用' : '启用'}
        </button>
        <button class="secondary danger vk-delete-btn" type="button" data-vk-delete="${vkEscape(item.id)}" data-vk-name="${vkEscape(item.name)}">
          删除
        </button>
      </div>
    </div>
  `;
}

function renderVirtualKeysPanel() {
  const list = document.getElementById('virtual-keys-list');
  const meta = document.getElementById('virtual-keys-meta');
  if (!list) return;

  if (!virtualKeysItems.length) {
    list.innerHTML = '<div class="metric-empty">暂无虚拟密钥。点击"创建新密钥"开始分发。</div>';
  } else {
    list.innerHTML = virtualKeysItems.map(vkKeyRowHtml).join('');
  }

  if (meta) {
    const active = virtualKeysItems.filter(k => k.enabled && !k.expired).length;
    meta.textContent = `${virtualKeysItems.length} 个密钥 · ${active} 个活跃`;
  }

  bindVirtualKeyActions(list);
}

function bindVirtualKeyActions(root) {
  root.querySelectorAll('[data-vk-reveal]').forEach(btn => {
    btn.onclick = async () => {
      const id = btn.dataset.vkReveal;
      try {
        const data = await api('/api/virtual-keys', 'POST', { action: 'reveal', id });
        const key = data.item?.key;
        if (key) {
          await navigator.clipboard.writeText(key);
          showMessage('Key 已复制到剪贴板。');
        }
      } catch (err) {
        showMessage(err.message, true);
      }
    };
  });

  root.querySelectorAll('[data-vk-toggle]').forEach(btn => {
    btn.onclick = async () => {
      const id = btn.dataset.vkToggle;
      const currentlyEnabled = btn.dataset.vkEnabled === 'true';
      try {
        btn.disabled = true;
        await api('/api/virtual-keys', 'POST', { action: 'update', id, enabled: !currentlyEnabled });
        showMessage(currentlyEnabled ? 'Key 已禁用。' : 'Key 已启用。');
        await loadVirtualKeysPanel(true);
      } catch (err) {
        showMessage(err.message, true);
      } finally {
        btn.disabled = false;
      }
    };
  });

  root.querySelectorAll('[data-vk-delete]').forEach(btn => {
    btn.onclick = async () => {
      const id = btn.dataset.vkDelete;
      const name = btn.dataset.vkName || id;
      if (!confirm(`确认删除密钥 "${name}"？此操作不可撤销。`)) return;
      try {
        btn.disabled = true;
        await api('/api/virtual-keys', 'POST', { action: 'delete', id });
        showMessage('Key 已删除。');
        await loadVirtualKeysPanel(true);
      } catch (err) {
        showMessage(err.message, true);
      } finally {
        btn.disabled = false;
      }
    };
  });
}

async function loadVirtualKeysPanel(force = false) {
  if (virtualKeysLoaded && !force) return;
  const list = document.getElementById('virtual-keys-list');
  if (list) list.innerHTML = '<div class="metric-empty">loading...</div>';
  try {
    const data = await api('/api/virtual-keys');
    virtualKeysItems = Array.isArray(data.items) ? data.items : [];
    renderVirtualKeysPanel();
    virtualKeysLoaded = true;
  } catch (err) {
    if (list) list.innerHTML = `<div class="metric-empty">${vkEscape(err.message || 'load failed')}</div>`;
  }
}

function showCreateVirtualKeyModal() {
  document.getElementById('vk-create-modal')?.removeAttribute('hidden');
}

function hideCreateVirtualKeyModal() {
  document.getElementById('vk-create-modal')?.setAttribute('hidden', '');
}

async function createVirtualKey() {
  const nameInput = document.getElementById('vk-create-name');
  const noteInput = document.getElementById('vk-create-note');
  const modelsInput = document.getElementById('vk-create-models');
  const rpmInput = document.getElementById('vk-create-rpm');
  const maxTokensInput = document.getElementById('vk-create-max-tokens');
  const maxRequestsInput = document.getElementById('vk-create-max-requests');
  const expiresInput = document.getElementById('vk-create-expires');

  const name = (nameInput?.value || '').trim();
  if (!name) {
    showMessage('请输入密钥名称。', true);
    return;
  }

  const modelsRaw = (modelsInput?.value || '').trim();
  const allowedModels = modelsRaw ? modelsRaw.split(',').map(m => m.trim()).filter(Boolean) : [];

  let expiresAt = 0;
  if (expiresInput?.value) {
    try {
      expiresAt = Math.floor(new Date(expiresInput.value).getTime() / 1000);
    } catch {
      expiresAt = 0;
    }
  }

  try {
    const result = await api('/api/virtual-keys', 'POST', {
      action: 'create',
      name,
      note: (noteInput?.value || '').trim(),
      allowed_models: allowedModels,
      rate_limit_rpm: parseInt(rpmInput?.value || '0', 10) || 0,
      max_tokens: parseInt(maxTokensInput?.value || '0', 10) || 0,
      max_requests: parseInt(maxRequestsInput?.value || '0', 10) || 0,
      expires_at: expiresAt,
    });

    const fullKey = result.item?.key;
    if (fullKey) {
      try {
        await navigator.clipboard.writeText(fullKey);
        showMessage(`密钥已创建并复制到剪贴板：${fullKey.substring(0, 20)}...`);
      } catch {
        showMessage(`密钥已创建：${fullKey}\n请手动复制。`);
        prompt('你的新 API Key（复制后关闭此对话框）:', fullKey);
      }
    } else {
      showMessage('密钥已创建。');
    }

    // Clear form
    if (nameInput) nameInput.value = '';
    if (noteInput) noteInput.value = '';
    if (modelsInput) modelsInput.value = '';
    if (rpmInput) rpmInput.value = '';
    if (maxTokensInput) maxTokensInput.value = '';
    if (maxRequestsInput) maxRequestsInput.value = '';
    if (expiresInput) expiresInput.value = '';

    hideCreateVirtualKeyModal();
    await loadVirtualKeysPanel(true);
  } catch (err) {
    showMessage(err.message, true);
  }
}
