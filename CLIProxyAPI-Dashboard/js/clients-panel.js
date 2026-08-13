let clientsPanelLoaded = false;
let clientsPanelItems = [];
let selectedClientKey = '';

function formatClientTs(ts) {
  const res = formatDashboardTs(ts);
  if (!res || res === '-') return '-';
  if (typeof res === 'object') return `${res.day} ${res.time}`;
  return res;
}

function formatClientRelativeTime(ts) {
  if (!ts) return '-';
  const now = Math.floor(Date.now() / 1000);
  const diff = now - Number(ts);
  if (diff < 0) return '刚刚';
  if (diff < 60) return `${diff} 秒前`;
  if (diff < 3600) return `${Math.floor(diff / 60)} 分钟前`;
  if (diff < 86400) return `${Math.floor(diff / 3600)} 小时前`;
  if (diff < 2592000) return `${Math.floor(diff / 86400)} 天前`;
  return formatClientTs(ts);
}

function formatClientNumber(value) {
  const number = Number(value || 0);
  if (!Number.isFinite(number)) return '0';
  return number.toLocaleString();
}

function formatCompactNumber(value) {
  const num = Number(value || 0);
  if (!Number.isFinite(num) || num === 0) return '0';
  if (num >= 1000000000) return `${(num / 1000000000).toFixed(2).replace(/\.00$/, '')}B`;
  if (num >= 1000000) return `${(num / 1000000).toFixed(2).replace(/\.00$/, '')}M`;
  if (num >= 10000) return `${(num / 1000).toFixed(1).replace(/\.0$/, '')}K`;
  if (num >= 1000) return num.toLocaleString();
  return String(num);
}

function formatClientPercent(value) {
  const number = Number(value || 0);
  if (!Number.isFinite(number)) return '0%';
  return `${(number * 100).toFixed(1).replace(/\.0$/, '')}%`;
}

function clientStatusCopy(status) {
  const labels = {
    warning: '需关注',
    notice: '有 4xx',
    healthy: '健康',
  };
  return labels[status] || '未知';
}

function copyClientText(text, btnElement, event) {
  if (event) event.stopPropagation();
  if (!text || text === '-') return;
  navigator.clipboard.writeText(String(text)).then(() => {
    if (btnElement) {
      btnElement.classList.add('is-copied');
      setTimeout(() => btnElement.classList.remove('is-copied'), 1200);
    }
  }).catch(() => {});
}

function getFilteredClientItems() {
  const query = String(document.getElementById('clients-search')?.value || '').trim().toLowerCase();
  const status = String(document.getElementById('client-status-filter')?.value || '').trim();
  const type = String(document.getElementById('client-type-filter')?.value || '').trim();
  const [sortKey, sortDir] = String(document.getElementById('client-sort-select')?.value || 'total_requests:desc').split(':');

  const items = clientsPanelItems.filter(item => {
    if (status && item.status !== status) return false;
    if (type === 'apikey' && !item.is_api_key) return false;
    if (type === 'ip' && item.is_api_key) return false;
    if (!query) return true;
    return [item.label, item.key, item.top_model, item.top_path, ...(item.ips || [])]
      .some(value => String(value || '').toLowerCase().includes(query));
  });

  items.sort((a, b) => {
    const av = Number(a[sortKey] ?? 0);
    const bv = Number(b[sortKey] ?? 0);
    const result = av === bv ? String(a.label || '').localeCompare(String(b.label || '')) : av - bv;
    return sortDir === 'asc' ? result : -result;
  });
  return items;
}

function clientRowHtml(item) {
  const clientKey = String(item.key || 'unknown');
  const label = String(item.label || clientKey);
  const selected = clientKey === selectedClientKey ? ' is-selected' : '';
  const typeClass = item.is_api_key ? 'apikey' : 'ip';
  const typeLabel = item.is_api_key ? 'Key' : 'IP';
  const statusClass = item.status || 'unknown';
  const successRate = Number(item.success_rate || 0);

  return `
    <tr class="client-row${selected}" onclick="selectClient('${escapeHtml(clientKey)}')">
      <td>
        <div class="client-identity">
          <span class="client-type-pill ${escapeHtml(typeClass)}">${escapeHtml(typeLabel)}</span>
          <code class="client-name" title="${escapeHtml(clientKey)}">${escapeHtml(label)}</code>
          <button class="client-copy-icon" onclick="copyClientText('${escapeHtml(clientKey)}', this, event)" title="复制 Key">
            <svg viewBox="0 0 16 16" width="11" height="11" fill="none" stroke="currentColor" stroke-width="1.8"><rect x="5" y="5" width="8" height="8" rx="1.5"/><path d="M3 11V3.5A1.5 1.5 0 0 1 4.5 2H11"/></svg>
          </button>
        </div>
      </td>
      <td>
        <span class="client-status-pill ${escapeHtml(statusClass)}">
          <span class="status-dot"></span>
          <span>${escapeHtml(clientStatusCopy(item.status))}</span>
        </span>
      </td>
      <td style="text-align: right;">
        <span class="tabular-stat">${formatClientNumber(item.total_requests)}</span>
        ${item.failure_count > 0 ? `<small class="err-count-sub" title="错误数">${item.failure_count} 错</small>` : ''}
      </td>
      <td style="text-align: right;">
        <span class="tabular-stat ${successRate >= 0.95 ? 'text-healthy' : successRate >= 0.8 ? 'text-notice' : 'text-warning'}">
          ${formatClientPercent(item.success_rate)}
        </span>
      </td>
      <td style="text-align: right;">
        <span class="tabular-stat">${item.avg_latency_ms != null ? `${item.avg_latency_ms}ms` : '-'}</span>
      </td>
      <td style="text-align: right;">
        <span class="tabular-stat token-val" title="${formatClientNumber(item.total_tokens)} Tokens">
          ${formatCompactNumber(item.total_tokens)}
        </span>
      </td>
      <td>
        <span class="model-badge" title="${escapeHtml(item.top_model || '-')}">
          <code>${escapeHtml(item.top_model || '-')}</code>
        </span>
      </td>
      <td>
        <span class="time-cell" title="${escapeHtml(formatClientTs(item.last_seen))}">
          ${escapeHtml(formatClientRelativeTime(item.last_seen))}
        </span>
      </td>
    </tr>
  `;
}

function renderClientDetail(items) {
  const detail = document.getElementById('client-detail');
  if (!detail) return;
  const item = items.find(entry => String(entry.key || 'unknown') === selectedClientKey) || items[0];
  if (!item) {
    detail.innerHTML = '<div class="clients-detail-empty">选择左侧客户端查看明细</div>';
    return;
  }
  selectedClientKey = String(item.key || 'unknown');
  const clientKey = String(item.key || 'unknown');
  const label = String(item.label || clientKey);
  const statusClass = item.status || 'unknown';
  const promptTokens = Number(item.prompt_tokens || 0);
  const completionTokens = Number(item.completion_tokens || 0);
  const totalTokens = Number(item.total_tokens || 0) || (promptTokens + completionTokens);

  detail.innerHTML = `
    <div class="detail-header">
      <div class="detail-header-top">
        <span class="client-status-pill ${escapeHtml(statusClass)}">
          <span class="status-dot"></span>
          <span>${escapeHtml(clientStatusCopy(item.status))}</span>
        </span>
        <span class="detail-type-tag">${item.is_api_key ? 'API Key 客户' : 'IP 直连'}</span>
      </div>
      <div class="detail-key-box">
        <code class="detail-key-text" title="${escapeHtml(clientKey)}">${escapeHtml(label)}</code>
        <button class="detail-copy-btn" onclick="copyClientText('${escapeHtml(clientKey)}', this, event)" title="复制完整 Key">
          <svg viewBox="0 0 16 16" width="12" height="12" fill="none" stroke="currentColor" stroke-width="1.8"><rect x="5" y="5" width="8" height="8" rx="1.5"/><path d="M3 11V3.5A1.5 1.5 0 0 1 4.5 2H11"/></svg>
        </button>
      </div>
    </div>

    <!-- 4 Stats Grid -->
    <div class="detail-stats-grid">
      <div class="detail-stat-item">
        <span class="stat-label">请求数</span>
        <b class="stat-val">${formatClientNumber(item.total_requests)}</b>
      </div>
      <div class="detail-stat-item">
        <span class="stat-label">成功率</span>
        <b class="stat-val ${Number(item.success_rate || 0) >= 0.95 ? 'text-healthy' : 'text-warning'}">${formatClientPercent(item.success_rate)}</b>
      </div>
      <div class="detail-stat-item">
        <span class="stat-label">错误数</span>
        <b class="stat-val ${item.failure_count > 0 ? 'text-warning' : ''}">${formatClientNumber(item.failure_count)}</b>
      </div>
      <div class="detail-stat-item">
        <span class="stat-label">平均延迟</span>
        <b class="stat-val">${item.avg_latency_ms != null ? `${item.avg_latency_ms} ms` : '-'}</b>
      </div>
    </div>

    <!-- Token -->
    <div class="detail-section">
      <div class="detail-section-row">
        <span class="section-title">Token 消耗</span>
        <span class="token-sum">${formatCompactNumber(totalTokens)}</span>
      </div>
      <div class="token-sub-line">
        <span>Prompt: <b>${formatCompactNumber(promptTokens)}</b></span>
        <span>Completion: <b>${formatCompactNumber(completionTokens)}</b></span>
      </div>
    </div>

    <!-- Route & Model -->
    <div class="detail-section">
      <span class="section-title">常用路径</span>
      <code class="detail-mono-val">${escapeHtml(item.top_path || '-')}</code>
    </div>

    <div class="detail-section">
      <span class="section-title">常用模型</span>
      <code class="detail-mono-val">${escapeHtml(item.top_model || '-')}</code>
    </div>

    <div class="detail-section">
      <span class="section-title">最后活跃</span>
      <span class="detail-text-val">${escapeHtml(formatClientTs(item.last_seen))} (${escapeHtml(formatClientRelativeTime(item.last_seen))})</span>
    </div>

    <!-- Action -->
    <div class="detail-action-wrap">
      <button class="detail-jump-btn" type="button" onclick="jumpToClientRequests('${escapeHtml(clientKey)}')">
        查看此客户端请求日志 →
      </button>
    </div>
  `;
}

function jumpToClientRequests(clientKey) {
  if (typeof showSection === 'function') {
    showSection('requests');
    setTimeout(() => {
      const searchBox = document.getElementById('request-search') || document.getElementById('request-filter-ip');
      if (searchBox) {
        searchBox.value = clientKey;
        if (typeof applyRequestFilters === 'function') applyRequestFilters();
      }
    }, 150);
  }
}

function renderClientsPanel() {
  const countBadge = document.getElementById('request-clients-count');
  const body = document.getElementById('request-clients-body');
  const items = getFilteredClientItems();

  if (countBadge) countBadge.textContent = String(clientsPanelItems.length);

  if (body) {
    if (items.length) {
      body.innerHTML = items.map(clientRowHtml).join('');
    } else {
      body.innerHTML = '<tr><td colspan="8" class="clients-empty-row">暂无匹配的客户端记录</td></tr>';
    }
  }
  renderClientDetail(items);
}

function selectClient(key) {
  selectedClientKey = key;
  renderClientsPanel();
}

async function loadClientsPanel(force = false) {
  if (clientsPanelLoaded && !force) return;
  const body = document.getElementById('request-clients-body');
  const meta = document.getElementById('request-clients-meta');
  const countBadge = document.getElementById('request-clients-count');
  const limit = force ? 500 : 100;
  if (body) body.innerHTML = '<tr><td colspan="8" class="clients-empty-row">正在加载客户端指标...</td></tr>';
  try {
    const data = await api(`/api/request-clients?limit=${limit}`);
    clientsPanelItems = Array.isArray(data.items) ? data.items : [];
    if (countBadge) countBadge.textContent = String(clientsPanelItems.length);
    if (meta) meta.textContent = `更新于 ${formatFreshness(data.refreshed_at)}`;
    if (!clientsPanelItems.some(item => String(item.key || 'unknown') === selectedClientKey)) {
      selectedClientKey = String(clientsPanelItems[0]?.key || '');
    }
    clientsPanelLoaded = true;
    renderClientsPanel();
  } catch (error) {
    if (body) body.innerHTML = `<tr><td colspan="8" class="clients-empty-row error">${escapeHtml(error.message || '加载失败')}</td></tr>`;
  }
}
