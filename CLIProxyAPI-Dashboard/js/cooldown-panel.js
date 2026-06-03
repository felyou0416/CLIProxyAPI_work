/* ── Cooldown Status Panel ─────────────────────────────────────────── */

let cooldownPanelData = [];
let cooldownPanelTimer = null;
let cooldownCountdownTimer = null;
let cooldownFilterProvider = '';

async function loadCooldownPanel(force) {
  const body = document.getElementById('cooldown-body');
  const meta = document.getElementById('cooldown-meta');
  if (!body) return;
  try {
    loadGlobalCoolingState();
    const data = await api('/api/cooldown-status');
    cooldownPanelData = data.items || [];
    renderCooldownFilters();
    renderCooldownTable();
    if (meta) {
      const total = cooldownPanelData.length;
      meta.textContent = getLanguage() === 'zh'
        ? `${total} 条冷却中`
        : `${total} cooling down`;
    }
    startCooldownCountdown();
  } catch (e) {
    if (body) body.innerHTML = `<tr><td colspan="8" style="text-align:center;color:var(--text-muted)">${e.message || t('common.requestFailed')}</td></tr>`;
  }
}

function renderCooldownFilters() {
  const container = document.getElementById('cooldown-provider-filters');
  if (!container) return;
  const providers = new Set();
  for (const item of cooldownPanelData) {
    if (item.provider) providers.add(item.provider);
  }
  const sorted = Array.from(providers).sort();
  let html = `<button class="category-chip${!cooldownFilterProvider ? ' active' : ''}" onclick="setCooldownProviderFilter('')">${t('label.categoryAll')}</button>`;
  for (const p of sorted) {
    html += `<button class="category-chip${cooldownFilterProvider === p ? ' active' : ''}" onclick="setCooldownProviderFilter('${escapeAttr(p)}')">${escapeHtmlCooldown(p)}</button>`;
  }
  container.innerHTML = html;
}

function setCooldownProviderFilter(provider) {
  cooldownFilterProvider = provider;
  renderCooldownFilters();
  renderCooldownTable();
}

function renderCooldownTable() {
  const body = document.getElementById('cooldown-body');
  if (!body) return;
  let items = cooldownPanelData;
  if (cooldownFilterProvider) {
    items = items.filter(item => item.provider === cooldownFilterProvider);
  }
  if (!items.length) {
    body.innerHTML = `<tr><td colspan="8" style="text-align:center;color:var(--text-muted)">${getLanguage() === 'zh' ? '当前没有冷却中的条目' : 'No cooldown entries'}</td></tr>`;
    return;
  }
  let html = '';
  for (const item of items) {
    const remaining = formatCooldownRemaining(item.next_retry_after);
    const reason = formatCooldownReason(item.reason, getLanguage());
    const statusClass = (item.remaining_seconds || 0) > 60 ? 'cooldown-long' : 'cooldown-short';
    html += `<tr class="cooldown-row ${statusClass}" data-retry="${escapeAttr(item.next_retry_after || '')}">
      <td>${escapeHtmlCooldown(item.provider || '-')}</td>
      <td class="cooldown-model-cell">${escapeHtmlCooldown(item.model || item.auth_label || '-')}</td>
      <td>${escapeHtmlCooldown(item.auth_file || item.auth_id || '-')}</td>
      <td>${escapeHtmlCooldown(item.email || '-')}</td>
      <td><span class="cooldown-reason-chip">${reason}</span></td>
      <td class="cooldown-remaining-cell" data-retry-ts="${item.next_retry_ts || 0}">${remaining}</td>
      <td>${item.next_retry_after || '-'}</td>
      <td>
        <button class="secondary cooldown-clear-btn" onclick="clearSingleCooldown('${escapeAttr(item.auth_id)}', '${escapeAttr(item.model || '')}')">${getLanguage() === 'zh' ? '清除' : 'Clear'}</button>
      </td>
    </tr>`;
  }
  body.innerHTML = html;
}

function formatCooldownRemaining(retryAfterStr) {
  if (!retryAfterStr) return '-';
  const target = new Date(retryAfterStr.replace(/-/g, '/')); // Compatibility
  const now = new Date();
  const diffMs = target - now;
  if (diffMs <= 0) return `<span class="cooldown-expired">${getLanguage() === 'zh' ? '已过期' : 'Expired'}</span>`;
  const totalSeconds = Math.ceil(diffMs / 1000);
  if (totalSeconds < 60) return `${totalSeconds}s`;
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = totalSeconds % 60;
  if (minutes < 60) return `${minutes}m ${seconds}s`;
  const hours = Math.floor(minutes / 60);
  const remainMinutes = minutes % 60;
  return `${hours}h ${remainMinutes}m`;
}

function formatCooldownReason(reason, lang) {
  const map = {
    'quota': lang === 'zh' ? '配额超限' : 'Quota Exceeded',
    'rate_limit': lang === 'zh' ? '速率限制' : 'Rate Limit',
    'forbidden': lang === 'zh' ? '403 禁止' : '403 Forbidden',
    'auth': lang === 'zh' ? '认证失败' : 'Auth Failure',
    'timeout': lang === 'zh' ? '超时' : 'Timeout',
    'server': lang === 'zh' ? '服务器错误' : 'Server Error',
    'client': lang === 'zh' ? '客户端错误' : 'Client Error',
    'unavailable': lang === 'zh' ? '不可用' : 'Unavailable',
    'specialized': lang === 'zh' ? '特殊模型' : 'Specialized',
    'unknown': lang === 'zh' ? '未知' : 'Unknown',
  };
  return map[reason] || reason || map['unknown'];
}

function startCooldownCountdown() {
  if (cooldownCountdownTimer) clearInterval(cooldownCountdownTimer);
  cooldownCountdownTimer = setInterval(() => {
    const cells = document.querySelectorAll('.cooldown-remaining-cell[data-retry-ts]');
    for (const cell of cells) {
      const ts = parseFloat(cell.getAttribute('data-retry-ts'));
      if (!ts) continue;
      const now = Date.now() / 1000;
      const diff = ts - now;
      if (diff <= 0) {
        cell.innerHTML = '<span class="cooldown-expired">' + (getLanguage() === 'zh' ? '已过期' : 'Expired') + '</span>';
        continue;
      }
      const totalSeconds = Math.ceil(diff);
      if (totalSeconds < 60) { cell.textContent = `${totalSeconds}s`; continue; }
      const minutes = Math.floor(totalSeconds / 60);
      const seconds = totalSeconds % 60;
      if (minutes < 60) { cell.textContent = `${minutes}m ${seconds}s`; continue; }
      const hours = Math.floor(minutes / 60);
      cell.textContent = `${hours}h ${minutes % 60}m`;
    }
  }, 1000);
}

async function clearSingleCooldown(authId, model) {
  if (!authId) return;
  const lang = getLanguage();
  try {
    const result = await api('/api/clear-cooldown', 'POST', { auth_id: authId, model: model || '' });
    showMessage(result.message || (lang === 'zh' ? '冷却已清除' : 'Cooldown cleared'));
    await loadCooldownPanel(true);
  } catch (e) {
    showMessage(e.message || (lang === 'zh' ? '清除失败' : 'Failed to clear'), true);
  }
}

async function clearAllCooldowns() {
  const lang = getLanguage();
  const items = cooldownFilterProvider
    ? cooldownPanelData.filter(item => item.provider === cooldownFilterProvider)
    : cooldownPanelData;
  if (!items.length) {
    showMessage(lang === 'zh' ? '没有冷却条目需要清除' : 'No cooldown entries to clear');
    return;
  }
  try {
    const ids = items.map(item => ({ auth_id: item.auth_id, model: item.model || '' }));
    const result = await api('/api/clear-cooldown', 'POST', { entries: ids });
    showMessage(result.message || (lang === 'zh' ? '已清除所有冷却' : 'All cooldowns cleared'));
    await loadCooldownPanel(true);
  } catch (e) {
    showMessage(e.message || (lang === 'zh' ? '清除失败' : 'Failed to clear'), true);
  }
}

function escapeHtmlCooldown(value) {
  return String(value ?? '')
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#39;');
}

function escapeAttr(value) {
  return String(value ?? '')
    .replaceAll('&', '&amp;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#39;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;');
}

async function toggleGlobalCooling(disable) {
  try {
    const result = await api('/api/per-auth-cooling', 'POST', {
      action: 'set_global',
      disable_cooling: !!disable,
    });
    showMessage(result.message || 'Updated.');
    if (result.restart_required) showMessage('配置已保存，需要重启代理才能生效。', true);
  } catch (e) {
    showMessage(e.message, true);
  }
}

async function loadGlobalCoolingState() {
  try {
    const data = await api('/api/advanced-config');
    const cb = document.getElementById('global-disable-cooling');
    if (cb) cb.checked = !!(data.item || {}).disable_cooling;
  } catch (e) { /* ignore */ }
}
