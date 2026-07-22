let requestEventsLoaded = false;
let requestEventsLastQueryKey = '';
let requestEventsOffset = 0;
let requestEventsServerOffset = 0;
let requestEventsTotal = 0;

let requestEventsPageSize = 50;
let _requestGroupSeq = 0;
let _requestGroupClickInit = false;

function escapeHtml(value) {
  return String(value ?? '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

function formatDashboardTs(ts) {
  const value = Number(ts || 0);
  if (!value) return '-';
  try {
    const date = new Date(value * 1000);
    return {
      day: date.toLocaleDateString(),
      time: date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' }),
    };
  } catch {
    return '-';
  }
}

function formatFreshness(ts) {
  const value = Number(ts || 0);
  if (!value) return typeof getLanguage === 'function' && getLanguage() === 'en' ? 'Not ready' : '未就绪';
  try {
    return new Date(value * 1000).toLocaleString();
  } catch {
    return typeof getLanguage === 'function' && getLanguage() === 'en' ? 'Not ready' : '未就绪';
  }
}

function requestEventsCopy() {
  return typeof getLanguage === 'function' && getLanguage() === 'en'
    ? {
        cache: 'Cached',
        notCached: 'Not cached',
        refreshed: 'Refreshed',
        appended: 'Appended',
        notReady: 'Not ready',
      }
    : {
        cache: '缓存',
        notCached: '未缓存',
        refreshed: '刷新',
        appended: '追加',
        notReady: '未就绪',
    };
}

function getRequestEventModelLabel(item) {
  const candidates = [
    item?.requested_model,
    item?.routed_model,
    item?.actual_model,
    item?.model,
    item?.model_id,
  ];
  for (const value of candidates) {
    const text = String(value || '').trim();
    if (text) return text;
  }
  return '';
}

function getRequestEventRouteSource(item) {
  const value = String(item?.route_source || '').trim().toLowerCase();
  if (!value) return '';
  const labels = {
    'precise-log': getLanguage() === 'zh' ? '精确日志' : 'Precise log',
    'runtime-model-map': getLanguage() === 'zh' ? '运行时映射' : 'Runtime map',
    'registry-model-map': getLanguage() === 'zh' ? '注册表推断' : 'Registry heuristic',
    'aggregate-config': getLanguage() === 'zh' ? '聚合配置' : 'Aggregate config',
    'unknown': getLanguage() === 'zh' ? '未确认来源' : 'Unknown source',
  };
  return labels[value] || value;
}

function getRequestEventRouteConfidence(item) {
  const value = Number(item?.route_confidence || 0);
  if (!Number.isFinite(value) || value <= 0) return '';
  return `${Math.round(value * 100)}%`;
}

function compactRequestPath(path) {
  const value = String(path || '').trim();
  if (!value) return '-';
  const [base, query = ''] = value.split('?');
  if (!query) return base;
  return `${base}?`;
}

function requestStatusLabel(statusCode, success) {
  if (!statusCode) return success ? 'OK' : '-';
  if (success) return `${statusCode}`;
  if (statusCode >= 500) return `${statusCode}`;
  if (statusCode >= 400) return `${statusCode}`;
  return `${statusCode}`;
}

function requestProviderLabel(item) {
  const provider = String(item?.inferred_provider || item?.actual_provider || '').trim();
  if (provider && provider !== '-') return provider;
  return '';
}

function isModelsRequestEvent(item) {
  const path = String(item?.path || '').trim().split('?', 1)[0].replace(/\/+$/, '');
  return path === '/v1/models';
}

function getRequestEventFilters() {
  return {
    ip: document.getElementById('request-filter-ip')?.value?.trim() || '',
    model: document.getElementById('request-filter-model')?.value?.trim() || '',
    provider: document.getElementById('request-filter-provider')?.value?.trim() || '',
    status: document.getElementById('request-filter-status')?.value?.trim() || '',
    success: document.getElementById('request-filter-success')?.value?.trim() || '',
    includeModels: !!document.getElementById('request-include-models')?.checked,
  };
}

function getRequestEventsPageSize() {
  const select = document.getElementById('request-page-size');
  const value = Number(select?.value || requestEventsPageSize || 50);
  if (!Number.isFinite(value)) return 50;
  return Math.max(10, Math.min(500, Math.round(value)));
}

function setRequestEventsMeta(data, shownCount, append, loading = false) {
  const meta = document.getElementById('request-events-meta');
  if (!meta) return;
  if (loading) {
    meta.textContent = typeof getLanguage === 'function' && getLanguage() === 'en'
      ? 'Refreshing…'
      : '刷新中…';
    return;
  }
  const copy = requestEventsCopy();
  const total = Number(data?.total || 0);
  const refreshedAt = Number(data?.refreshed_at || 0);
  const freshness = formatFreshness(refreshedAt);
  const cachedLabel = data?.cached ? copy.cache : copy.notCached;
  const modeLabel = append ? copy.appended : copy.refreshed;
  meta.textContent = `${cachedLabel} · ${modeLabel} · ${shownCount}/${total || shownCount} · ${freshness}`;
}

function setRequestEventsBusy(busy) {
  const buttons = [
    document.querySelector('#section-requests button[data-i18n="btn.refresh"]'),
    document.querySelector('#section-requests button[data-i18n="btn.loadMore"]'),
  ];
  buttons.forEach((btn) => {
    if (!btn) return;
    btn.disabled = !!busy;
  });
}

function getRequestModelPlaceholder(item) {
  const source = String(item?.source || '').trim().toLowerCase();
  const noteText = (item?.notes || []).join(' ').toLowerCase();
  const ageSeconds = Math.max(0, Math.floor(Date.now() / 1000) - Number(item?.timestamp || 0));
  if (source === 'proxy' && ageSeconds <= 90) return '等待详细日志';
  if (source === 'proxy') return '未匹配详情';
  if (source === 'error-log' || noteText.includes('error-')) return '错误日志未记录模型';
  return '未记录模型';
}

function getRequestEventRoutedModelLabel(item) {
  const requested = getRequestEventModelLabel(item);
  return getRequestEventModelLabel({
    requested_model: item?.routed_model,
    routed_model: item?.actual_model,
    actual_model: item?.actual_model,
    model: item?.model,
    model_id: item?.model_id,
  }) || requested;
}

function requestEventFingerprint(item) {
  // Collapse when status + request path + model route match (consecutive).
  // Errors also key on error text so different failures don't merge.
  const path = String(item?.path || '').trim().split('?')[0];
  const status = Number(item?.status_code || 0);
  const success = !!item?.success;
  const requested = getRequestEventModelLabel(item);
  const routed = getRequestEventRoutedModelLabel(item);
  const provider = requestProviderLabel(item);
  const error = success ? '' : String(item?.error_summary || '').trim();
  return [path, status, success ? 1 : 0, requested, routed, provider, error].join('|');
}

function sumRequestGroupUsage(items) {
  let prompt = 0;
  let completion = 0;
  let total = 0;
  let hasTokens = false;
  let latencySum = 0;
  let latencyCount = 0;
  for (const item of items || []) {
    const p = item?.prompt_tokens;
    const c = item?.completion_tokens;
    const t = item?.total_tokens;
    if (p != null || c != null || t != null) {
      hasTokens = true;
      const pv = Number(p || 0);
      const cv = Number(c || 0);
      prompt += Number.isFinite(pv) ? pv : 0;
      completion += Number.isFinite(cv) ? cv : 0;
      if (t != null && Number.isFinite(Number(t))) {
        total += Number(t);
      } else {
        total += (Number.isFinite(pv) ? pv : 0) + (Number.isFinite(cv) ? cv : 0);
      }
    }
    if (item?.latency_ms != null && Number.isFinite(Number(item.latency_ms))) {
      latencySum += Number(item.latency_ms);
      latencyCount += 1;
    }
  }
  return {
    prompt_tokens: hasTokens ? prompt : null,
    completion_tokens: hasTokens ? completion : null,
    total_tokens: hasTokens ? total : null,
    latency_ms: latencyCount ? Math.round(latencySum / latencyCount) : null,
    latency_sum_ms: latencyCount ? Math.round(latencySum) : null,
  };
}

function groupConsecutiveRequestEvents(items) {
  const groups = [];
  for (const item of items) {
    const fp = requestEventFingerprint(item);
    const last = groups[groups.length - 1];
    if (last && last.fingerprint === fp) {
      last.count += 1;
      last.items.push(item);
    } else {
      groups.push({ fingerprint: fp, count: 1, items: [item] });
    }
  }
  return groups;
}

function toggleRequestGroup(gid) {
  const badge = document.querySelector(`.req-dup-badge[data-gid="${gid}"]`);
  const children = document.querySelectorAll(`tr.req-group-child[data-gid="${gid}"]`);
  const expanded = badge?.classList.contains('expanded');
  children.forEach((tr) => { tr.style.display = expanded ? 'none' : ''; });
  if (badge) {
    badge.classList.toggle('expanded', !expanded);
    badge.setAttribute('aria-expanded', expanded ? 'false' : 'true');
  }
}

function initRequestGroupClickHandler() {
  if (_requestGroupClickInit) return;
  _requestGroupClickInit = true;
  document.addEventListener('click', (e) => {
    const badge = e.target.closest('.req-dup-badge');
    if (!badge) return;
    e.stopPropagation();
    toggleRequestGroup(badge.dataset.gid);
  });
  document.addEventListener('keydown', (e) => {
    if (e.key !== 'Enter' && e.key !== ' ') return;
    const badge = e.target.closest?.('.req-dup-badge');
    if (!badge) return;
    e.preventDefault();
    toggleRequestGroup(badge.dataset.gid);
  });
}

function renderRequestEventsItems(items) {
  initRequestGroupClickHandler();
  const groups = groupConsecutiveRequestEvents(items);
  const rows = [];
  for (const group of groups) {
    if (group.count < 2) {
      rows.push(requestEventRowHtml(group.items[0]));
      continue;
    }
    _requestGroupSeq += 1;
    const gid = 'rg' + _requestGroupSeq;
    const aggregateUsage = sumRequestGroupUsage(group.items);
    rows.push(requestEventRowHtml(group.items[0], {
      groupId: gid,
      badgeCount: group.count,
      aggregateUsage,
    }));
    for (let i = 1; i < group.items.length; i++) {
      rows.push(requestEventRowHtml(group.items[i], { groupId: gid, isChild: true }));
    }
  }
  return rows.join('');
}

function requestEventRowHtml(item, opts = {}) {
  const statusCode = Number(item.status_code || 0);
  const success = !!item.success;
  const statusClass = success ? 'ok' : (statusCode >= 500 ? 'warn' : 'off');
  const aggregateUsage = opts.aggregateUsage || null;
  const isAggregated = !!aggregateUsage && Number(opts.badgeCount || 0) >= 2;
  const promptTokens = isAggregated ? aggregateUsage.prompt_tokens : item.prompt_tokens;
  const completionTokens = isAggregated ? aggregateUsage.completion_tokens : item.completion_tokens;
  const totalTokens = isAggregated ? aggregateUsage.total_tokens : item.total_tokens;
  const latencyMs = isAggregated
    ? (aggregateUsage.latency_ms != null ? aggregateUsage.latency_ms : item.latency_ms)
    : item.latency_ms;
  const tokenText = totalTokens != null
    ? (isAggregated ? `Σ ${totalTokens}` : `${totalTokens}`)
    : '-';
  let tokenTitle = '';
  if (totalTokens != null || promptTokens != null || completionTokens != null) {
    const base = `prompt ${promptTokens ?? 0} / completion ${completionTokens ?? 0} / total ${totalTokens ?? 0}`;
    tokenTitle = isAggregated
      ? `${typeof getLanguage === 'function' && getLanguage() === 'en' ? 'Sum of' : '合计'} ${opts.badgeCount} ${typeof getLanguage === 'function' && getLanguage() === 'en' ? 'entries' : '条'}: ${base}`
      : base;
  }
  const routeSource = getRequestEventRouteSource(item);
  const routeConfidence = getRequestEventRouteConfidence(item);
  const requestedModel = getRequestEventModelLabel(item);
  const modelPlaceholder = getRequestModelPlaceholder(item);
  const routedModel = getRequestEventRoutedModelLabel(item);
  const displayTime = formatDashboardTs(item.timestamp);
  const day = typeof displayTime === 'string' ? displayTime : displayTime.day;
  const time = typeof displayTime === 'string' ? '' : displayTime.time;
  const provider = requestProviderLabel(item);
  const pathText = compactRequestPath(item.path);
  const fullPath = String(item.path || '').trim();
  const routeChips = [];
  if (provider) routeChips.push(`<span class="request-chip provider">${escapeHtml(provider)}</span>`);
  if (routeSource && routeSource !== '未确认来源' && routeSource !== 'Unknown source') {
    routeChips.push(`<span class="request-chip route">${escapeHtml(routeSource)}${routeConfidence ? ` ${escapeHtml(routeConfidence)}` : ''}</span>`);
  }
  const hasActualRoute = routedModel && routedModel !== requestedModel;
  const errorText = String(item.error_summary || '').trim();
  const latencyText = latencyMs != null
    ? (isAggregated ? `avg ${latencyMs} ms` : `${latencyMs} ms`)
    : '';
  const groupId = opts.groupId || '';
  const isChild = !!opts.isChild;
  const badgeCount = Number(opts.badgeCount || 0);
  const groupAttr = groupId ? ` data-gid="${groupId}"` : '';
  const childClass = isChild ? ' req-group-child' : '';
  const childStyle = isChild ? ' style="display:none;"' : '';
  const en = typeof getLanguage === 'function' && getLanguage() === 'en';
  const badgeTone = success ? 'is-ok' : 'is-error';
  const badgeHtml = badgeCount >= 2
    ? `<span class="req-dup-badge ${badgeTone}" data-gid="${groupId}" title="${en ? 'Click to expand ' + badgeCount + ' entries' : '点击展开 ' + badgeCount + ' 条'}" role="button" tabindex="0" aria-expanded="false">×${badgeCount}</span>`
    : '';
  return `
    <tr class="request-row ${success ? 'is-ok' : 'is-error'}${childClass}${isAggregated ? ' req-group-head' : ''}"${groupAttr}${childStyle}>
      <td class="request-time-cell">
        <div style="display: flex; align-items: center; gap: 6px;">
          ${badgeHtml}
          <div class="request-time">${escapeHtml(time || day)}</div>
          ${time ? `<span class="request-day" style="font-size: 11px; opacity: 0.6;">${escapeHtml(day)}</span>` : ''}
        </div>
      </td>
      <td>
        <span class="request-status ${statusClass}">${escapeHtml(requestStatusLabel(statusCode, success))}</span>
      </td>
      <td class="request-path-cell">
        <div style="display: flex; align-items: center; gap: 6px;">
          <code title="${escapeHtml(fullPath)}" style="padding: 3px 8px; border-radius: 9px; background: color-mix(in srgb, #dbeafe 42%, var(--panel)); font-size: 11px;">${escapeHtml(pathText)}</code>
        </div>
      </td>
      <td>
        <div style="display: flex; align-items: center; gap: 6px;">
          <code style="font-size: 11px;">${escapeHtml(requestedModel || modelPlaceholder)}</code>
          ${hasActualRoute ? `<span style="color: var(--text-muted); font-size: 11px;">→</span><code style="font-size: 11px;">${escapeHtml(routedModel)}</code>` : ''}
          ${routeChips.length ? `<div style="display: inline-flex; gap: 4px;">${routeChips.join('')}</div>` : ''}
        </div>
      </td>
      <td>
        <div style="display: flex; align-items: center; gap: 6px; font-variant-numeric: tabular-nums;">
          <span title="${escapeHtml(tokenTitle)}" style="font-weight: 800; font-size: 13px;">${escapeHtml(tokenText)}</span>
          ${latencyText ? `<span style="font-size: 11px; color: var(--text-muted);">(${escapeHtml(latencyText)})</span>` : ''}
        </div>
      </td>
      <td class="request-error-cell" title="${escapeHtml(errorText)}">${escapeHtml(errorText || '-')}</td>
    </tr>
  `;
}

function getRequestEventsTable() {
  return document.getElementById('request-events-body');
}

function getRequestEventsQueryUrl(limit, offset, filters, refresh = false) {
  const params = new URLSearchParams();
  params.set('limit', String(limit));
  params.set('offset', String(offset));
  if (refresh) params.set('refresh', '1');
  if (filters.ip) params.set('ip', filters.ip);
  if (filters.model) params.set('model', filters.model);
  if (filters.provider) params.set('provider', filters.provider);
  if (filters.status) params.set('status', filters.status);
  if (filters.includeModels) params.set('include_models', '1');
  if (filters.success === 'true' || filters.success === 'false') {
    params.set('success', filters.success);
  }
  return `/api/request-events?${params.toString()}`;
}

function getRequestEventsQueryKey(filters) {
  return JSON.stringify([
    filters.ip || '',
    filters.model || '',
    filters.provider || '',
    filters.status || '',
    filters.success || '',
    filters.includeModels ? '1' : '0',
  ]);
}

async function loadRequestEventsPanel(force = false, append = false) {
  const table = getRequestEventsTable();
  const filters = getRequestEventFilters();
  const queryKey = getRequestEventsQueryKey(filters);
  requestEventsPageSize = getRequestEventsPageSize();

  if (force) {
    requestEventsOffset = 0;
    requestEventsServerOffset = 0;
  } else if (requestEventsLastQueryKey && requestEventsLastQueryKey !== queryKey) {
    requestEventsOffset = 0;
    requestEventsServerOffset = 0;
  }

  const currentOffset = append ? requestEventsServerOffset : 0;
  if (!force && !append && requestEventsLoaded && requestEventsLastQueryKey === queryKey) return;

  if (table && (!append || currentOffset === 0)) {
    table.innerHTML = '<tr><td colspan="6">loading...</td></tr>';
  }
  if (!append) {
    setRequestEventsBusy(true);
    setRequestEventsMeta(null, 0, false, true);
  }

  try {
    let data = null;
    let nextOffset = currentOffset;
    let hiddenCount = 0;
    const items = [];
    const fetchLimit = filters.includeModels ? requestEventsPageSize : Math.min(500, requestEventsPageSize * 4);
    for (let attempt = 0; attempt < 8 && items.length < requestEventsPageSize; attempt += 1) {
      data = await api(getRequestEventsQueryUrl(fetchLimit, nextOffset, filters, force && !append && attempt === 0));
      const batch = Array.isArray(data.items) ? data.items : [];
      for (const item of batch) {
        if (!filters.includeModels && isModelsRequestEvent(item)) {
          hiddenCount += 1;
          continue;
        }
        if (items.length < requestEventsPageSize) items.push(item);
      }
      nextOffset += batch.length;
      if (batch.length < fetchLimit) break;
    }
    const rawTotal = Number(data?.total || 0);
    const total = filters.includeModels ? rawTotal : Math.max(items.length, rawTotal - hiddenCount);

    if (table) {
      if (!append || currentOffset === 0) {
        table.innerHTML = items.length
          ? renderRequestEventsItems(items)
          : '<tr><td colspan="6">暂无请求记录</td></tr>';
      } else if (items.length) {
        table.insertAdjacentHTML('beforeend', renderRequestEventsItems(items));
      }
    }

    requestEventsLoaded = true;
    requestEventsLastQueryKey = queryKey;
    requestEventsOffset = (append ? requestEventsOffset : 0) + items.length;
    requestEventsServerOffset = nextOffset;
    requestEventsTotal = total;
    setRequestEventsMeta({ ...(data || {}), total }, requestEventsOffset, append);
  } catch (error) {
    if (table && (!append || currentOffset === 0)) {
      table.innerHTML = `<tr><td colspan="6">${escapeHtml(error.message || 'load failed')}</td></tr>`;
    }
    setRequestEventsMeta(null, requestEventsOffset, append);
  } finally {
    if (!append) setRequestEventsBusy(false);
  }
}

async function loadMoreRequestEvents() {
  const filters = getRequestEventFilters();
  const queryKey = getRequestEventsQueryKey(filters);
  if (requestEventsLastQueryKey && requestEventsLastQueryKey !== queryKey) {
    requestEventsLoaded = false;
    requestEventsOffset = 0;
    requestEventsServerOffset = 0;
  }
  if (requestEventsTotal > 0 && requestEventsOffset >= requestEventsTotal) {
    if (typeof showMessage === 'function') {
      showMessage(typeof getLanguage === 'function' && getLanguage() === 'en' ? 'No more request records.' : '没有更多请求记录了。');
    }
    return;
  }
  await loadRequestEventsPanel(false, true);
}

function applyRequestEventFilters() {
  requestEventsLoaded = false;
  requestEventsOffset = 0;
  requestEventsServerOffset = 0;
  requestEventsTotal = 0;
  loadRequestEventsPanel(true);
}

function clearRequestEventFilters() {
  ['request-filter-ip', 'request-filter-model', 'request-filter-provider', 'request-filter-status'].forEach(id => {
    const el = document.getElementById(id);
    if (el) el.value = '';
  });
  const success = document.getElementById('request-filter-success');
  if (success) success.value = '';
  requestEventsLoaded = false;
  requestEventsOffset = 0;
  requestEventsServerOffset = 0;
  requestEventsTotal = 0;
  loadRequestEventsPanel(true);
}

function changeRequestPageSize() {
  requestEventsLoaded = false;
  requestEventsOffset = 0;
  requestEventsServerOffset = 0;
  requestEventsTotal = 0;
  loadRequestEventsPanel(true);
}

function showRequestSettingsModal() {
  document.getElementById('request-settings-modal')?.removeAttribute('hidden');
}

function hideRequestSettingsModal() {
  document.getElementById('request-settings-modal')?.setAttribute('hidden', 'true');
}

function submitRequestSettings() {
  hideRequestSettingsModal();
  applyRequestEventFilters();
}

function resetAndClearRequestSettings() {
  ['request-filter-ip', 'request-filter-model', 'request-filter-provider', 'request-filter-status'].forEach(id => {
    const el = document.getElementById(id);
    if (el) el.value = '';
  });
  const success = document.getElementById('request-filter-success');
  if (success) success.value = '';
  
  const pageSize = document.getElementById('request-page-size');
  if (pageSize) pageSize.value = '50';
  const includeModels = document.getElementById('request-include-models');
  if (includeModels) includeModels.checked = false;

  hideRequestSettingsModal();
  applyRequestEventFilters();
}

function handleRequestFilterKeydown(event) {
  if (!event || event.key !== 'Enter') return;
  event.preventDefault();
  submitRequestSettings();
}
