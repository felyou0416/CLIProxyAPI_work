let clientsPanelLoaded = false;
let clientsPanelItems = [];
let selectedClientIP = '';

function formatClientTs(ts) {
  const res = formatDashboardTs(ts);
  if (!res || res === '-') return '-';
  if (typeof res === 'object') return `${res.day} ${res.time}`;
  return res;
}

function formatClientNumber(value) {
  const number = Number(value || 0);
  if (!Number.isFinite(number)) return '0';
  return number.toLocaleString();
}

function formatClientPercent(value) {
  const number = Number(value || 0);
  if (!Number.isFinite(number)) return '0%';
  return `${Math.round(number * 100)}%`;
}

function clientStatusCopy(status) {
  const labels = {
    warning: '需关注',
    notice: '有 4xx',
    healthy: '健康',
  };
  return labels[status] || '未知';
}

function clientTypeCopy(type) {
  const labels = {
    public: '公网',
    private: '内网',
    loopback: '本机',
    unknown: '未知',
  };
  return labels[type] || '未知';
}

function clientTypeHint(item) {
  const source = String(item.client_ip_source || '').trim();
  return source ? `来源：${source}` : '来源：连接地址或旧日志';
}

function showClientTextPopover(element, event) {
  if (!element || !event) return;
  event.stopPropagation();
  const fullText = element.getAttribute('title') || element.textContent;
  if (!fullText || fullText === '-') return;
  document.querySelectorAll('.text-popover').forEach(el => el.remove());
  const popover = document.createElement('div');
  popover.className = 'text-popover';
  popover.textContent = fullText;
  Object.assign(popover.style, {
    position: 'absolute',
    background: 'color-mix(in srgb, var(--panel) 98%, white)',
    border: '1px solid var(--border)',
    borderRadius: '8px',
    padding: '10px 12px',
    boxShadow: '0 10px 25px rgba(15, 23, 42, 0.12)',
    zIndex: '1000',
    maxWidth: '360px',
    maxHeight: '220px',
    overflowY: 'auto',
    fontSize: '11px',
    color: 'var(--text)',
    wordBreak: 'break-all',
    lineHeight: '1.4',
  });
  document.body.appendChild(popover);
  const rect = element.getBoundingClientRect();
  let left = rect.left + window.scrollX;
  if (left + popover.offsetWidth > window.innerWidth - 16) left = window.innerWidth - popover.offsetWidth - 16;
  if (left < 16) left = 16;
  let top = rect.bottom + window.scrollY + 6;
  if (top + popover.offsetHeight > window.innerHeight + window.scrollY - 16) top = rect.top + window.scrollY - popover.offsetHeight - 6;
  popover.style.left = `${left}px`;
  popover.style.top = `${top}px`;
  const dismiss = () => {
    popover.remove();
    document.removeEventListener('click', dismiss);
  };
  popover.addEventListener('click', e => e.stopPropagation());
  setTimeout(() => document.addEventListener('click', dismiss), 10);
}

function clientSummaryHtml(items) {
  const totalClients = items.length;
  const totalRequests = items.reduce((sum, item) => sum + Number(item.total_requests || 0), 0);
  const totalErrors = items.reduce((sum, item) => sum + Number(item.failure_count || 0), 0);
  const totalTokens = items.reduce((sum, item) => sum + Number(item.total_tokens || 0), 0);
  const publicClients = items.filter(item => item.ip_type === 'public').length;
  const weightedSuccess = totalRequests > 0 ? 1 - (totalErrors / totalRequests) : 0;
  const cards = [
    ['客户端数', formatClientNumber(totalClients), `${publicClients} 个公网来源`],
    ['请求总量', formatClientNumber(totalRequests), `错误 ${formatClientNumber(totalErrors)} 次`],
    ['整体成功率', formatClientPercent(weightedSuccess), '按请求数加权'],
    ['Token 消耗', formatClientNumber(totalTokens), '最近观测窗口'],
  ];
  return cards.map(([label, value, hint]) => `
    <div class="clients-summary-card">
      <div class="clients-summary-label">${escapeHtml(label)}</div>
      <div class="clients-summary-value">${escapeHtml(value)}</div>
      <div class="clients-summary-hint">${escapeHtml(hint)}</div>
    </div>
  `).join('');
}

function getFilteredClientItems() {
  const query = String(document.getElementById('clients-search')?.value || '').trim().toLowerCase();
  const status = String(document.getElementById('client-status-filter')?.value || '').trim();
  const type = String(document.getElementById('client-type-filter')?.value || '').trim();
  const [sortKey, sortDir] = String(document.getElementById('client-sort-select')?.value || 'total_requests:desc').split(':');
  const items = clientsPanelItems.filter(item => {
    if (status && item.status !== status) return false;
    if (type && item.ip_type !== type) return false;
    if (!query) return true;
    return [item.ip, item.top_model, item.top_path].some(value => String(value || '').toLowerCase().includes(query));
  });
  items.sort((a, b) => {
    const av = Number(a[sortKey] ?? 0);
    const bv = Number(b[sortKey] ?? 0);
    const result = av === bv ? String(a.ip || '').localeCompare(String(b.ip || '')) : av - bv;
    return sortDir === 'asc' ? result : -result;
  });
  return items;
}

function clientRowHtml(item) {
  const ip = String(item.ip || 'unknown');
  const selected = ip === selectedClientIP ? ' is-selected' : '';
  return `
    <tr class="client-row${selected}" onclick="selectClient('${escapeHtml(ip)}')">
      <td>
        <div class="client-identity">
          <code>${escapeHtml(ip)}</code>
          <span class="client-type-pill ${escapeHtml(item.ip_type || 'unknown')}">${escapeHtml(clientTypeCopy(item.ip_type))}</span>
        </div>
        <div class="client-source">${escapeHtml(clientTypeHint(item))}</div>
      </td>
      <td><span class="client-status-pill ${escapeHtml(item.status || 'unknown')}">${escapeHtml(clientStatusCopy(item.status))}</span></td>
      <td>${formatClientNumber(item.total_requests)}</td>
      <td><span class="client-error-stack"><b>${formatClientNumber(item.failure_count)}</b><small>4xx ${formatClientNumber(item.count_4xx)} / 5xx ${formatClientNumber(item.count_5xx)}</small></span></td>
      <td><div class="client-rate"><span>${formatClientPercent(item.success_rate)}</span><i style="width:${Math.max(0, Math.min(100, Number(item.success_rate || 0) * 100))}%"></i></div></td>
      <td>${item.avg_latency_ms != null ? `${formatClientNumber(item.avg_latency_ms)} ms` : '-'}</td>
      <td>${formatClientNumber(item.total_tokens)}</td>
      <td class="ellipsis-cell path-col" title="${escapeHtml(item.top_path || '')}" onclick="showClientTextPopover(this, event)"><code>${escapeHtml(item.top_path || '-')}</code></td>
      <td class="ellipsis-cell model-col" title="${escapeHtml(item.top_model || '')}" onclick="showClientTextPopover(this, event)"><code>${escapeHtml(item.top_model || '-')}</code></td>
      <td>${escapeHtml(formatClientTs(item.last_seen))}</td>
    </tr>
  `;
}

function renderClientDetail(items) {
  const detail = document.getElementById('client-detail');
  if (!detail) return;
  const item = items.find(entry => String(entry.ip || 'unknown') === selectedClientIP) || items[0];
  if (!item) {
    detail.innerHTML = '<div class="clients-detail-empty">暂无客户端详情</div>';
    return;
  }
  selectedClientIP = String(item.ip || 'unknown');
  detail.innerHTML = `
    <div class="clients-detail-head">
      <span class="client-status-pill ${escapeHtml(item.status || 'unknown')}">${escapeHtml(clientStatusCopy(item.status))}</span>
      <code>${escapeHtml(selectedClientIP)}</code>
      <p>${escapeHtml(clientTypeCopy(item.ip_type))} · ${escapeHtml(clientTypeHint(item))}</p>
    </div>
    <div class="clients-detail-metrics">
      <div><span>请求</span><b>${formatClientNumber(item.total_requests)}</b></div>
      <div><span>成功率</span><b>${formatClientPercent(item.success_rate)}</b></div>
      <div><span>错误</span><b>${formatClientNumber(item.failure_count)}</b></div>
      <div><span>平均延迟</span><b>${item.avg_latency_ms != null ? `${formatClientNumber(item.avg_latency_ms)} ms` : '-'}</b></div>
    </div>
    <div class="clients-detail-section">
      <span>常用路径</span>
      <code>${escapeHtml(item.top_path || '-')}</code>
    </div>
    <div class="clients-detail-section">
      <span>常用模型</span>
      <code>${escapeHtml(item.top_model || '-')}</code>
    </div>
    <div class="clients-detail-section">
      <span>Token</span>
      <p>Prompt ${formatClientNumber(item.prompt_tokens)} / Completion ${formatClientNumber(item.completion_tokens)} / Total ${formatClientNumber(item.total_tokens)}</p>
    </div>
    <div class="clients-detail-section">
      <span>最近访问</span>
      <p>${escapeHtml(formatClientTs(item.last_seen))}</p>
    </div>
  `;
}

function renderClientsPanel() {
  const summary = document.getElementById('clients-summary-grid');
  const body = document.getElementById('request-clients-body');
  const items = getFilteredClientItems();
  if (summary) summary.innerHTML = clientSummaryHtml(clientsPanelItems);
  if (body) {
    body.innerHTML = items.length
      ? items.map(clientRowHtml).join('')
      : '<tr><td colspan="10" class="clients-empty-row">暂无匹配的客户端统计</td></tr>';
  }
  renderClientDetail(items);
}

function selectClient(ip) {
  selectedClientIP = ip;
  renderClientsPanel();
}

async function loadClientsPanel(force = false) {
  if (clientsPanelLoaded && !force) return;
  const body = document.getElementById('request-clients-body');
  const meta = document.getElementById('request-clients-meta');
  const limit = force ? 500 : 100;
  if (body) body.innerHTML = '<tr><td colspan="10" class="clients-empty-row">loading...</td></tr>';
  try {
    const data = await api(`/api/request-clients?limit=${limit}`);
    clientsPanelItems = Array.isArray(data.items) ? data.items : [];
    if (meta) meta.textContent = `${clientsPanelItems.length} 个客户端 · ${formatFreshness(data.refreshed_at)}`;
    if (!clientsPanelItems.some(item => String(item.ip || 'unknown') === selectedClientIP)) {
      selectedClientIP = String(clientsPanelItems[0]?.ip || '');
    }
    clientsPanelLoaded = true;
    renderClientsPanel();
  } catch (error) {
    if (body) body.innerHTML = `<tr><td colspan="10" class="clients-empty-row">${escapeHtml(error.message || 'load failed')}</td></tr>`;
  }
}
