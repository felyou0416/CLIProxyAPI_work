let authHealthPanelLoaded = false;
let authHealthItems = [];
let authHealthFiltered = [];
let authHealthState = 'all';
let authHealthSort = { column: 'name', direction: 'asc' };
let authHealthSearch = '';
let authHealthProvider = '';
let authHealthLimit = 20;

const AUTH_HEALTH_STATE_META = {
  healthy: { className: 'ok', labelKey: 'authHealth.healthy', fallback: '健康' },
  degraded: { className: 'warn', labelKey: 'authHealth.degraded', fallback: '部分异常' },
  failed: { className: 'off', labelKey: 'authHealth.failed', fallback: '不可用' },
  unknown: { className: 'unknown', labelKey: 'authHealth.unknown', fallback: '未检测' },
};

function normalizeAuthHealthState(state) {
  return AUTH_HEALTH_STATE_META[state] ? state : 'unknown';
}

function authHealthStateLabel(state) {
  const meta = AUTH_HEALTH_STATE_META[normalizeAuthHealthState(state)];
  return t(meta.labelKey, meta.fallback);
}

function formatAuthHealthTs(ts) {
  const res = formatDashboardTs(ts);
  if (!res || res === '-') return '-';
  if (typeof res === 'object') {
    return `${res.day} ${res.time}`;
  }
  return res;
}

function authHealthCellTitle(...values) {
  return values
    .map(value => String(value || '').trim())
    .filter(Boolean)
    .join('\n');
}

function authHealthStateDetail(item) {
  const available = parseInt(item.available_models, 10) || 0;
  const failed = parseInt(item.failed_models, 10) || 0;
  if (available && failed) return `${available} ${t('authHealth.availableShort', '可用')} / ${failed} ${t('authHealth.failedShort', '失败')}`;
  if (available) return `${available} ${t('authHealth.modelsAvailable', '个模型可用')}`;
  if (failed) return `${failed} ${t('authHealth.modelsFailed', '个模型失败')}`;
  return t('authHealth.awaitingProbe', '等待模型探测');
}

function authHealthStatusHtml(item) {
  const state = normalizeAuthHealthState(item.state);
  const meta = AUTH_HEALTH_STATE_META[state];
  return `
    <div class="ah-status">
      <span class="ah-status-pill ${meta.className}">
        <span class="ah-status-dot" aria-hidden="true"></span>
        ${escapeHtml(authHealthStateLabel(state))}
      </span>
      <span class="ah-status-detail">${escapeHtml(authHealthStateDetail(item))}</span>
    </div>
  `;
}

function showTextPopover(element, event) {
  if (!element || !event) return;
  event.stopPropagation();
  const fullText = element.getAttribute('title') || element.textContent;
  if (!fullText || fullText === '-') return;

  // Remove any existing popovers first
  document.querySelectorAll('.text-popover').forEach(el => el.remove());

  // Create popover element
  const popover = document.createElement('div');
  popover.className = 'text-popover';
  popover.style.position = 'absolute';
  popover.style.background = 'color-mix(in srgb, var(--panel) 98%, white)';
  popover.style.border = '1px solid var(--border)';
  popover.style.borderRadius = '8px';
  popover.style.padding = '10px 12px';
  popover.style.boxShadow = '0 10px 25px rgba(15, 23, 42, 0.12)';
  popover.style.zIndex = '1000';
  popover.style.maxWidth = '320px';
  popover.style.maxHeight = '200px';
  popover.style.overflowY = 'auto';
  popover.style.fontSize = '11px';
  popover.style.color = 'var(--text)';
  popover.style.wordBreak = 'break-all';
  popover.style.lineHeight = '1.4';

  // Add the text
  popover.textContent = fullText;

  // Append to body to compute correct layout
  document.body.appendChild(popover);

  // Position popover relative to the clicked element
  const rect = element.getBoundingClientRect();
  const popoverWidth = popover.offsetWidth;
  const popoverHeight = popover.offsetHeight;

  // Determine horizontal alignment
  let left = rect.left + window.scrollX;
  if (left + popoverWidth > window.innerWidth - 16) {
    left = window.innerWidth - popoverWidth - 16;
  }
  if (left < 16) left = 16;

  // Determine vertical alignment
  let top = rect.bottom + window.scrollY + 6;
  if (top + popoverHeight > window.innerHeight + window.scrollY - 16) {
    top = rect.top + window.scrollY - popoverHeight - 6;
  }

  popover.style.left = `${left}px`;
  popover.style.top = `${top}px`;

  // Add animation starting state
  popover.style.transform = 'translateY(-4px)';
  popover.style.opacity = '0';
  popover.style.transition = 'all 0.12s cubic-bezier(0.4, 0, 0.2, 1)';

  // Force reflow
  popover.offsetHeight;

  popover.style.transform = 'translateY(0)';
  popover.style.opacity = '1';

  // Dismiss on clicking anywhere else
  const dismiss = () => {
    popover.style.transform = 'translateY(-4px)';
    popover.style.opacity = '0';
    setTimeout(() => popover.remove(), 120);
    document.removeEventListener('click', dismiss);
  };

  popover.addEventListener('click', e => e.stopPropagation());

  setTimeout(() => {
    document.addEventListener('click', dismiss);
  }, 10);
}

function authHealthRowHtml(item) {
  const state = normalizeAuthHealthState(item.state);
  const reasonText = item.recent_failure_reason || '';
  const name = item.name || '-';
  const email = item.email || '';
  const identityTitle = authHealthCellTitle(name, email);
  const modelTitle = authHealthCellTitle(
    `${t('authHealth.availableModels', '可用模型')}: ${item.available_models || 0}`,
    `${t('authHealth.failedModels', '失败模型')}: ${item.failed_models || 0}`
  );
  const usageTitle = authHealthCellTitle(
    `${t('authHealth.requests', '请求数')}: ${(parseInt(item.request_count, 10) || 0).toLocaleString()}`,
    `${t('authHealth.tokens', '总 Token')}: ${(parseInt(item.total_tokens, 10) || 0).toLocaleString()}`
  );
  return `
    <tr data-state="${escapeHtml(state)}">
      <td class="identity-cell" title="${escapeHtml(identityTitle)}" onclick="showTextPopover(this, event)">
        <div class="identity-main">${escapeHtml(name)}</div>
        <div class="identity-sub">${email ? escapeHtml(email) : t('authHealth.noEmail', '无邮箱')}</div>
      </td>
      <td>${escapeHtml(item.provider || '-')}</td>
      <td>${authHealthStatusHtml(item)}</td>
      <td class="metric-stack num" title="${escapeHtml(modelTitle)}">
        <strong>${formatCompactNumber(parseInt(item.available_models, 10) || 0)}</strong>
        <span>${formatCompactNumber(parseInt(item.failed_models, 10) || 0)} ${t('authHealth.failedShort', '失败')}</span>
      </td>
      <td class="metric-stack num" title="${escapeHtml(usageTitle)}">
        <strong>${formatCompactNumber(parseInt(item.request_count, 10) || 0)}</strong>
        <span>${formatCompactNumber(parseInt(item.total_tokens, 10) || 0)} Token</span>
      </td>
      <td class="ellipsis-cell reason-col" title="${escapeHtml(reasonText)}" onclick="showTextPopover(this, event)">${escapeHtml(reasonText || '-')}</td>
      <td>${escapeHtml(formatAuthHealthTs(item.recent_failure_at))}</td>
    </tr>
  `;
}

function formatCompactNumber(n) {
  if (n === 0) return '0';
  if (n >= 1_000_000_000) return (n / 1_000_000_000).toFixed(1).replace(/\.0$/, '') + 'B';
  if (n >= 1_000_000) return (n / 1_000_000).toFixed(1).replace(/\.0$/, '') + 'M';
  if (n >= 1_000) return (n / 1_000).toFixed(1).replace(/\.0$/, '') + 'k';
  return String(n);
}

function computeAuthHealthSummary(items) {
  const total = items.length;
  const healthy = items.filter(i => normalizeAuthHealthState(i.state) === 'healthy').length;
  const degraded = items.filter(i => normalizeAuthHealthState(i.state) === 'degraded').length;
  const failed = items.filter(i => normalizeAuthHealthState(i.state) === 'failed').length;
  const unknown = items.filter(i => normalizeAuthHealthState(i.state) === 'unknown').length;
  const requests = items.reduce((sum, i) => sum + (parseInt(i.request_count, 10) || 0), 0);
  const tokens = items.reduce((sum, i) => sum + (parseInt(i.total_tokens, 10) || 0), 0);
  return { total, healthy, degraded, failed, unknown, requests, tokens };
}

function updateAuthHealthSummary() {
  const summary = computeAuthHealthSummary(authHealthItems);
  const totalEl = document.getElementById('ah-summary-total');
  const healthyEl = document.getElementById('ah-summary-healthy');
  const degradedEl = document.getElementById('ah-summary-degraded');
  const failedEl = document.getElementById('ah-summary-failed');
  const unknownEl = document.getElementById('ah-summary-unknown');
  const requestsEl = document.getElementById('ah-summary-requests');
  const tokensEl = document.getElementById('ah-summary-tokens');

  if (totalEl) totalEl.textContent = formatCompactNumber(summary.total);
  if (healthyEl) healthyEl.textContent = formatCompactNumber(summary.healthy);
  if (degradedEl) degradedEl.textContent = formatCompactNumber(summary.degraded);
  if (failedEl) failedEl.textContent = formatCompactNumber(summary.failed);
  if (unknownEl) unknownEl.textContent = formatCompactNumber(summary.unknown);
  if (requestsEl) requestsEl.textContent = formatCompactNumber(summary.requests);
  if (tokensEl) tokensEl.textContent = formatCompactNumber(summary.tokens);

  // Tooltips with exact numbers
  if (totalEl) totalEl.title = `${t('authHealth.totalItems', '认证项')} ${summary.total.toLocaleString()}`;
  if (healthyEl) healthyEl.title = `${t('authHealth.healthy', '健康')} ${summary.healthy.toLocaleString()}`;
  if (degradedEl) degradedEl.title = `${t('authHealth.degraded', '部分异常')} ${summary.degraded.toLocaleString()}`;
  if (failedEl) failedEl.title = `${t('authHealth.failed', '不可用')} ${summary.failed.toLocaleString()}`;
  if (unknownEl) unknownEl.title = `${t('authHealth.unknown', '未检测')} ${summary.unknown.toLocaleString()}`;
  if (requestsEl) requestsEl.title = `${t('authHealth.requests', '请求数')} ${summary.requests.toLocaleString()}`;
  if (tokensEl) tokensEl.title = `${t('authHealth.tokens', '总 Token')} ${summary.tokens.toLocaleString()}`;
}

function updateAuthHealthStatePills() {
  const all = authHealthItems.length;
  const healthy = authHealthItems.filter(i => normalizeAuthHealthState(i.state) === 'healthy').length;
  const degraded = authHealthItems.filter(i => normalizeAuthHealthState(i.state) === 'degraded').length;
  const failed = authHealthItems.filter(i => normalizeAuthHealthState(i.state) === 'failed').length;
  const unknown = authHealthItems.filter(i => normalizeAuthHealthState(i.state) === 'unknown').length;

  const allCount = document.getElementById('ah-count-all');
  const healthyCount = document.getElementById('ah-count-healthy');
  const degradedCount = document.getElementById('ah-count-degraded');
  const failedCount = document.getElementById('ah-count-failed');
  const unknownCount = document.getElementById('ah-count-unknown');

  if (allCount) allCount.textContent = all;
  if (healthyCount) healthyCount.textContent = healthy;
  if (degradedCount) degradedCount.textContent = degraded;
  if (failedCount) failedCount.textContent = failed;
  if (unknownCount) unknownCount.textContent = unknown;

  document.querySelectorAll('#ah-state-pills .pill').forEach(btn => {
    btn.classList.toggle('active', btn.dataset.state === authHealthState);
  });
}

function updateAuthHealthProviderFilter() {
  const select = document.getElementById('ah-provider-filter');
  if (!select) return;

  const providers = [...new Set(authHealthItems.map(i => i.provider).filter(Boolean))].sort((a, b) => a.localeCompare(b));
  const current = select.value;

  const allOption = select.querySelector('option[value=""]');
  select.innerHTML = '';
  if (allOption) select.appendChild(allOption);
  else select.innerHTML = `<option value="" data-i18n="authHealth.allProviders">${t('authHealth.allProviders', '全部 Provider')}</option>`;

  providers.forEach(p => {
    const option = document.createElement('option');
    option.value = p;
    option.textContent = p;
    select.appendChild(option);
  });

  if (providers.includes(current)) {
    select.value = current;
  } else if (current !== '') {
    authHealthProvider = '';
    select.value = '';
  }
}

function sortAuthHealthItems(items) {
  const { column, direction } = authHealthSort;
  const dir = direction === 'asc' ? 1 : -1;

  const numericCols = ['available_models', 'failed_models', 'request_count', 'total_tokens'];
  const isNumeric = numericCols.includes(column);
  const stateOrder = { failed: 0, degraded: 1, unknown: 2, healthy: 3 };

  return [...items].sort((a, b) => {
    let va = a[column];
    let vb = b[column];

    if (column === 'state') {
      va = stateOrder[normalizeAuthHealthState(va)];
      vb = stateOrder[normalizeAuthHealthState(vb)];
    } else if (isNumeric) {
      va = parseInt(va, 10) || 0;
      vb = parseInt(vb, 10) || 0;
    } else {
      if (va === undefined || va === null) va = '';
      if (vb === undefined || vb === null) vb = '';
      va = String(va);
      vb = String(vb);
    }

    if (va === vb) return 0;
    if (va === '' || va === '-') return 1;
    if (vb === '' || vb === '-') return -1;

    if (typeof va === 'string' && typeof vb === 'string') {
      return va.localeCompare(vb) * dir;
    }
    return (va > vb ? 1 : -1) * dir;
  });
}

function filterAuthHealthItems() {
  let result = [...authHealthItems];

  if (authHealthState !== 'all') {
    result = result.filter(i => normalizeAuthHealthState(i.state) === authHealthState);
  }

  if (authHealthProvider) {
    result = result.filter(i => i.provider === authHealthProvider);
  }

  if (authHealthSearch) {
    const q = authHealthSearch.toLowerCase();
    result = result.filter(i => {
      const name = (i.name || '').toLowerCase();
      const provider = (i.provider || '').toLowerCase();
      const email = (i.email || '').toLowerCase();
      const state = authHealthStateLabel(i.state).toLowerCase();
      const reason = (i.recent_failure_reason || '').toLowerCase();
      return name.includes(q) || provider.includes(q) || email.includes(q) || state.includes(q) || reason.includes(q);
    });
  }

  authHealthFiltered = sortAuthHealthItems(result);
}

function updateSortIndicators() {
  document.querySelectorAll('#section-auth-health .sort-indicator').forEach(el => {
    el.className = 'sort-indicator';
    if (el.dataset.col === authHealthSort.column) {
      el.classList.add(authHealthSort.direction);
    }
  });
}

function renderAuthHealthTable() {
  const body = document.getElementById('auth-health-body');
  if (!body) return;

  if (!authHealthFiltered.length) {
    body.innerHTML = `<tr><td colspan="7"><div class="auth-health-empty"><div class="auth-health-empty-icon">-</div><div>${t('authHealth.noData', '暂无符合条件的认证健康数据')}</div></div></td></tr>`;
    return;
  }

  body.innerHTML = authHealthFiltered.map(authHealthRowHtml).join('');
}

function filterAuthHealth() {
  const searchInput = document.getElementById('ah-search');
  const providerSelect = document.getElementById('ah-provider-filter');

  authHealthSearch = searchInput ? searchInput.value.trim().toLowerCase() : '';
  authHealthProvider = providerSelect ? providerSelect.value : '';

  filterAuthHealthItems();
  renderAuthHealthTable();
}

function setAuthHealthStateFilter(state) {
  authHealthState = state;
  updateAuthHealthStatePills();
  filterAuthHealth();
}

function sortAuthHealth(column) {
  if (authHealthSort.column === column) {
    authHealthSort.direction = authHealthSort.direction === 'asc' ? 'desc' : 'asc';
  } else {
    authHealthSort.column = column;
    authHealthSort.direction = 'asc';
  }
  updateSortIndicators();
  filterAuthHealth();
}

function updateLoadMoreButton() {
  const btn = document.getElementById('auth-health-load-all');
  if (!btn) return;
  const allLoaded = authHealthLimit >= 500;
  btn.textContent = allLoaded ? t('authHealth.allLoaded', '已加载全部') : t('authHealth.loadAll', '加载全部');
  btn.disabled = allLoaded;
}

function updateAuthHealthMeta(data) {
  const meta = document.getElementById('auth-health-meta');
  if (!meta) return;

  const refreshedAt = formatAuthHealthTs(data?.refreshed_at);
  const cacheText = data?.cached ? t('authHealth.cached', '缓存就绪') : t('authHealth.refreshing', '等待刷新');
  const countText = `${authHealthItems.length.toLocaleString()} ${t('authHealth.totalItems', '认证项')}`;
  meta.textContent = `${cacheText} · ${t('authHealth.lastRefresh', '最近刷新')} ${refreshedAt} · ${countText}`;
}

let authHealthResizerInitialized = false;

function applyAuthHealthColumnWidths() {
  const headers = document.querySelectorAll('#section-auth-health .metric-table thead th');
  if (!headers.length) return;

  const defaultWidths = {
    0: '22%',  // 认证标识
    1: '10%',  // Provider
    2: '14%',  // 健康标识
    3: '12%',  // 模型探测
    4: '12%',  // 请求 / Token
    5: '20%',  // 最近失败
    6: '10%'   // 失败时间
  };

  headers.forEach((th, index) => {
    const saved = localStorage.getItem(`auth-health-col-${index + 1}-width`);
    if (saved) {
      th.style.width = `${saved}px`;
    } else {
      th.style.width = defaultWidths[index];
    }
  });
}

function initAuthHealthResizer() {
  applyAuthHealthColumnWidths();

  if (authHealthResizerInitialized) return;

  const headers = document.querySelectorAll('#section-auth-health .metric-table thead th');
  if (!headers.length) return;

  headers.forEach((th, index) => {
    // 在表格头部的右侧边缘（辐条位置）放置手柄。最后一列右边不需要手柄。
    if (index === headers.length - 1) return;

    if (th.querySelector('.resize-handle')) return;

    const handle = document.createElement('div');
    handle.className = 'resize-handle';
    th.appendChild(handle);

    handle.addEventListener('pointerdown', (e) => {
      e.preventDefault();
      e.stopPropagation();

      const nextTh = headers[index + 1];
      if (!nextTh) return;

      const startX = e.clientX;
      const startWidthTh = th.offsetWidth;
      const startWidthNextTh = nextTh.offsetWidth;

      handle.classList.add('is-dragging');
      th.classList.add('is-resizing');

      const onPointerMove = (moveEvent) => {
        const dx = moveEvent.clientX - startX;
        // 限制最小宽度为 50px 防止某列完全消失
        if (startWidthTh + dx > 50 && startWidthNextTh - dx > 50) {
          const newWidthTh = Math.round(startWidthTh + dx);
          const newWidthNextTh = Math.round(startWidthNextTh - dx);

          th.style.width = `${newWidthTh}px`;
          nextTh.style.width = `${newWidthNextTh}px`;

          localStorage.setItem(`auth-health-col-${index + 1}-width`, String(newWidthTh));
          localStorage.setItem(`auth-health-col-${index + 2}-width`, String(newWidthNextTh));
        }
      };

      const onPointerUp = () => {
        handle.classList.remove('is-dragging');
        th.classList.remove('is-resizing');
        document.removeEventListener('pointermove', onPointerMove);
        document.removeEventListener('pointerup', onPointerUp);
      };

      document.addEventListener('pointermove', onPointerMove);
      document.addEventListener('pointerup', onPointerUp);
    });
  });

  authHealthResizerInitialized = true;
}

async function loadAuthHealthPanel(force = false) {
  initAuthHealthResizer();
  if (authHealthPanelLoaded && !force) return;

  const body = document.getElementById('auth-health-body');
  authHealthLimit = force ? 100 : 20;

  if (body) body.innerHTML = `<tr><td colspan="7"><div class="auth-health-loading">${t('common.loading', '加载中...')}</div></td></tr>`;

  try {
    const data = await api(`/api/auth-health?limit=${authHealthLimit}`);
    authHealthItems = Array.isArray(data.items) ? data.items : [];
    authHealthLimit = Math.min(data.limit || authHealthLimit, 500);

    updateAuthHealthSummary();
    updateAuthHealthStatePills();
    updateAuthHealthProviderFilter();
    updateAuthHealthMeta(data);
    filterAuthHealthItems();
    updateSortIndicators();
    renderAuthHealthTable();

    initAuthHealthResizer();
    authHealthPanelLoaded = true;
    updateLoadMoreButton();
  } catch (error) {
    if (body) body.innerHTML = `<tr><td colspan="7"><div class="auth-health-empty"><div class="auth-health-empty-icon">!</div><div>${error.message || t('common.requestFailed', '加载失败')}</div></div></td></tr>`;
  }
}

async function loadAllAuthHealth() {
  const btn = document.getElementById('auth-health-load-all');
  if (btn) btn.disabled = true;

  const body = document.getElementById('auth-health-body');
  if (body) body.innerHTML = `<tr><td colspan="7"><div class="auth-health-loading">${t('authHealth.loadingAll', '加载全部认证项')}</div></td></tr>`;

  try {
    const data = await api('/api/auth-health?limit=500');
    authHealthItems = Array.isArray(data.items) ? data.items : [];
    authHealthLimit = 500;

    updateAuthHealthSummary();
    updateAuthHealthStatePills();
    updateAuthHealthProviderFilter();
    updateAuthHealthMeta(data);
    filterAuthHealthItems();
    updateSortIndicators();
    renderAuthHealthTable();

    initAuthHealthResizer();
    updateLoadMoreButton();
  } catch (error) {
    if (body) body.innerHTML = `<tr><td colspan="7"><div class="auth-health-empty"><div class="auth-health-empty-icon">!</div><div>${error.message || t('common.requestFailed', '加载失败')}</div></div></td></tr>`;
  } finally {
    updateLoadMoreButton();
  }
}
