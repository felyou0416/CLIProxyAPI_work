let requestEventsLoaded = false;
let requestEventsLastQueryKey = '';
let requestEventsCurrentPage = 1;
let requestEventsPageSize = 50;
let requestEventsTotal = 0;
let requestEventsTotalPages = 1;

let _requestGroupSeq = 0;
let _requestGroupClickInit = false;
let _requestEventsMap = new Map();
let _currentDetailItem = null;

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

function formatLatency(ms) {
  const val = Number(ms);
  if (!Number.isFinite(val) || val < 0) return '';
  if (val < 1000) return `${Math.round(val)} ms`;
  if (val < 60000) return `${(val / 1000).toFixed(2)} s`;
  return `${(val / 60000).toFixed(1)} min`;
}

function formatClientUA(ua, ip) {
  const text = String(ua || '').trim();
  if (!text) return ip ? (ip === '127.0.0.1' || ip === '::1' ? 'Local' : 'Direct') : 'Direct';
  if (text.includes('claude-cli') || text.includes('Claude Code') || text.includes('local-agent')) return 'Claude Code';
  if (text.includes('Cursor')) return 'Cursor';
  if (text.includes('Python-urllib') || text.includes('python-requests') || text.includes('openai-python')) return 'Python';
  if (text.includes('NextChat') || text.includes('ChatGPT-Next-Web')) return 'NextChat';
  if (text.includes('CherryStudio') || text.includes('Cherry Studio')) return 'Cherry Studio';
  if (text.includes('OpenWebUI') || text.includes('open-webui')) return 'Open WebUI';
  if (text.includes('node-fetch') || text.includes('axios')) return 'Node.js';
  if (text.includes('curl')) return 'cURL';
  if (text.includes('Mozilla') || text.includes('Chrome') || text.includes('Safari')) return 'Browser';
  const first = text.split('/')[0].split(' ')[0];
  return first.length > 14 ? first.slice(0, 13) + '…' : first;
}

function requestEventsCopy() {
  return typeof getLanguage === 'function' && getLanguage() === 'en'
    ? {
        cache: 'Cached',
        notCached: 'Not cached',
        refreshed: 'Refreshed',
        notReady: 'Not ready',
        page: 'Page',
        total: 'Total',
        records: 'records',
      }
    : {
        cache: '缓存',
        notCached: '未缓存',
        refreshed: '已刷新',
        notReady: '未就绪',
        page: '页',
        total: '共',
        records: '条记录',
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
  const isZh = typeof getLanguage === 'function' ? getLanguage() === 'zh' : true;
  const labels = {
    'precise-log': isZh ? '精确日志' : 'Precise log',
    'runtime-model-map': isZh ? '运行时映射' : 'Runtime map',
    'registry-model-map': isZh ? '注册表推断' : 'Registry heuristic',
    'aggregate-config': isZh ? '聚合配置' : 'Aggregate config',
    'unknown': isZh ? '未确认来源' : 'Unknown source',
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
  if (!statusCode) return success ? '200' : '-';
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
  const select = document.getElementById('request-page-size-select') || document.getElementById('request-page-size');
  const value = Number(select?.value || requestEventsPageSize || 50);
  if (!Number.isFinite(value)) return 50;
  return Math.max(10, Math.min(500, Math.round(value)));
}

function setRequestEventsMeta(data, shownCount, loading = false) {
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
  meta.textContent = `${cachedLabel} · ${copy.total} ${total} ${copy.records} · 第 ${requestEventsCurrentPage}/${requestEventsTotalPages} 页 · ${freshness}`;
}

function setRequestEventsBusy(busy) {
  const buttons = [
    document.querySelector('#section-requests button[data-i18n="btn.refresh"]'),
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
  let cached = 0;
  let reasoning = 0;
  let hasTokens = false;
  let latencySum = 0;
  let latencyCount = 0;
  for (const item of items || []) {
    const p = item?.prompt_tokens;
    const c = item?.completion_tokens;
    const t = item?.total_tokens;
    const ca = item?.cached_tokens;
    const re = item?.reasoning_tokens;
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
    if (ca != null && Number.isFinite(Number(ca))) cached += Number(ca);
    if (re != null && Number.isFinite(Number(re))) reasoning += Number(re);
    if (item?.latency_ms != null && Number.isFinite(Number(item.latency_ms))) {
      latencySum += Number(item.latency_ms);
      latencyCount += 1;
    }
  }
  return {
    prompt_tokens: hasTokens ? prompt : null,
    completion_tokens: hasTokens ? completion : null,
    total_tokens: hasTokens ? total : null,
    cached_tokens: cached || null,
    reasoning_tokens: reasoning || null,
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
  const headTr = document.querySelector(`tr.req-group-head[data-gid="${gid}"]`);
  const expanded = badge?.classList.contains('expanded');
  children.forEach((tr) => { tr.style.display = expanded ? 'none' : ''; });
  if (badge) {
    badge.classList.toggle('expanded', !expanded);
    badge.setAttribute('aria-expanded', expanded ? 'false' : 'true');
  }
  if (headTr) {
    headTr.classList.toggle('is-expanded', !expanded);
  }
}

function initRequestGroupClickHandler() {
  if (_requestGroupClickInit) return;
  _requestGroupClickInit = true;
  // 使用捕获阶段（第三参数 true）：徽章是 <tr onclick="showRequestDetailModal(...)"> 的子元素，
  // 点击事件会先向上冒泡经过 <tr>（触发其内联 onclick 打开详情弹窗），再到达 document。
  // 若在冒泡阶段监听，stopPropagation 为时已晚——<tr> 的 onclick 已经先执行了。
  // 改为捕获阶段：事件从 document 向下传递到 target 时先被拦截，可以在到达 <tr> 之前
  // 就 stopPropagation，从根源上阻止 <tr> 的 onclick 触发。
  document.addEventListener('click', (e) => {
    const badge = e.target.closest('.req-dup-badge');
    if (!badge) return;
    e.stopPropagation();
    e.preventDefault();
    toggleRequestGroup(badge.dataset.gid);
  }, true);
  document.addEventListener('keydown', (e) => {
    if (e.key !== 'Enter' && e.key !== ' ') return;
    const badge = e.target.closest?.('.req-dup-badge');
    if (!badge) return;
    e.preventDefault();
    e.stopPropagation();
    toggleRequestGroup(badge.dataset.gid);
  }, true);
}

function renderRequestEventsItems(items) {
  initRequestGroupClickHandler();
  _requestEventsMap.clear();
  for (const item of items || []) {
    const key = item.request_id || String(item.timestamp || '') + '_' + String(item.path || '');
    _requestEventsMap.set(key, item);
  }

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
  const cachedTokens = isAggregated ? aggregateUsage.cached_tokens : item.cached_tokens;
  const reasoningTokens = isAggregated ? aggregateUsage.reasoning_tokens : item.reasoning_tokens;
  const latencyMs = isAggregated
    ? (aggregateUsage.latency_ms != null ? aggregateUsage.latency_ms : item.latency_ms)
    : item.latency_ms;

  const tokenText = totalTokens != null
    ? (isAggregated ? `Σ ${totalTokens.toLocaleString()}` : totalTokens.toLocaleString())
    : '-';

  let tokenTitle = '';
  if (totalTokens != null || promptTokens != null || completionTokens != null) {
    const base = `prompt: ${promptTokens ?? 0} | completion: ${completionTokens ?? 0} | total: ${totalTokens ?? 0}` +
      (cachedTokens ? ` | cached: ${cachedTokens}` : '') +
      (reasoningTokens ? ` | reasoning: ${reasoningTokens}` : '');
    tokenTitle = isAggregated
      ? `${typeof getLanguage === 'function' && getLanguage() === 'en' ? 'Sum of' : '合计'} ${opts.badgeCount} ${typeof getLanguage === 'function' && getLanguage() === 'en' ? 'entries' : '条'}: ${base}`
      : base;
  }

  const routeSource = getRequestEventRouteSource(item);
  const routeConfidence = getRequestEventRouteConfidence(item);
  const authFile = String(item.auth_file || '').trim();
  const displayAccountTag = authFile
    ? authFile
    : (routeSource && routeSource !== '未确认来源' && routeSource !== 'Unknown source'
      ? `${routeSource}${routeConfidence ? ' ' + routeConfidence : ''}`
      : '');
  const requestedModel = getRequestEventModelLabel(item);
  const modelPlaceholder = getRequestModelPlaceholder(item);
  const routedModel = getRequestEventRoutedModelLabel(item);

  const displayTime = formatDashboardTs(item.timestamp);
  const day = typeof displayTime === 'string' ? displayTime : displayTime.day;
  const time = item.request_time ? (item.request_time.split(' ')[1] || item.request_time) : (typeof displayTime === 'string' ? '' : displayTime.time);
  const respTimeShort = item.response_time ? (item.response_time.split(' ')[1] || item.response_time) : '';

  const provider = requestProviderLabel(item);
  const pathText = compactRequestPath(item.path);
  const fullPath = String(item.path || '').trim();

  const authText = item.auth_label
    ? item.auth_label
    : (item.auth_id ? `ID: ${item.auth_id}` : (item.api_key_masked ? `Key: ${item.api_key_masked}` : '-'));

  const hasActualRoute = routedModel && routedModel !== requestedModel;
  const errorText = String(item.error_summary || '').trim();
  const latencyText = latencyMs != null ? (isAggregated ? `avg ${formatLatency(latencyMs)}` : formatLatency(latencyMs)) : '';

  const tps = item.tps || (completionTokens && latencyMs && latencyMs > 0 ? (completionTokens / (latencyMs / 1000)).toFixed(1) : null);
  const tpsText = tps ? `${tps} tok/s` : '';

  const clientUA = formatClientUA(item.user_agent, item.client_ip);
  const reqKey = item.request_id || String(item.timestamp || '') + '_' + String(item.path || '');

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

  const childIndent = isChild ? '<span class="req-child-tree-icon" title="折叠展开项">↳ </span>' : '';

  return `
    <tr class="request-row ${success ? 'is-ok' : 'is-error'}${childClass}${isAggregated ? ' req-group-head' : ''} is-clickable" ${groupAttr}${childStyle} onclick="showRequestDetailModal('${escapeHtml(reqKey)}')">
      <!-- 1. Time & Latency -->
      <td class="req-col-time">
        <div style="display: flex; flex-direction: column; gap: 2px;">
          <div style="display: flex; align-items: center; gap: 5px;">
            ${childIndent}
            ${badgeHtml}
            <span class="request-time font-mono" style="font-weight: 700; font-size: 12px;">${escapeHtml(time || day)}</span>
            ${latencyText ? `<span class="req-latency-pill" title="请求耗时">⏱️ ${escapeHtml(latencyText)}</span>` : ''}
          </div>
          <div style="display: flex; align-items: center; gap: 4px; font-size: 10px; opacity: 0.7;">
            <span>${escapeHtml(day)}</span>
            ${respTimeShort ? `<span title="完成于 ${escapeHtml(item.response_time)}">· 🏁 ${escapeHtml(respTimeShort)}</span>` : ''}
          </div>
        </div>
      </td>

      <!-- 2. Status -->
      <td class="req-col-status" style="text-align: center;">
        <span class="request-status ${statusClass}">${escapeHtml(requestStatusLabel(statusCode, success))}</span>
      </td>

      <!-- 3. Client & IP -->
      <td class="req-col-client">
        <div style="display: flex; flex-direction: column; gap: 2px;">
          <span class="request-chip client-ua" title="${escapeHtml(item.user_agent || 'Client IP: ' + item.client_ip)}">${escapeHtml(clientUA)}</span>
          ${item.client_ip ? `<span style="font-size: 10px; opacity: 0.65; font-family: var(--mono);">${escapeHtml(item.client_ip)}</span>` : ''}
        </div>
      </td>

      <!-- 4. Endpoint & Mode -->
      <td class="req-col-endpoint">
        <div style="display: flex; flex-direction: column; gap: 3px;">
          <code title="${escapeHtml(fullPath)}" class="req-path-code">${escapeHtml(pathText)}</code>
          <div style="display: flex; gap: 4px;">
            ${item.stream ? '<span class="request-chip stream" title="SSE 流式传输">SSE 流式</span>' : '<span class="request-chip block-mode" title="阻塞非流式">阻塞模式</span>'}
          </div>
        </div>
      </td>

      <!-- 5. Model Routing -->
      <td class="req-col-model">
        <div style="display: flex; flex-direction: column; gap: 3px;">
          <div style="display: flex; align-items: center; gap: 5px; flex-wrap: wrap;">
            <code class="req-model-orig">${escapeHtml(requestedModel || modelPlaceholder)}</code>
            ${hasActualRoute ? `<span style="color: var(--text-muted); font-size: 11px;">→</span><code class="req-model-target">${escapeHtml(routedModel)}</code>` : ''}
          </div>
          ${displayAccountTag ? `<div><span class="request-chip route" title="${escapeHtml(authFile ? '账号文件: ' + authFile : displayAccountTag)}" style="max-width: 260px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;">${escapeHtml(displayAccountTag)}</span></div>` : ''}
        </div>
      </td>

      <!-- 6. Provider & Auth Account -->
      <td class="req-col-auth">
        <div style="display: flex; flex-direction: column; gap: 3px;">
          ${provider ? `<span class="request-chip provider">${escapeHtml(provider)}</span>` : '<span style="font-size: 11px; opacity: 0.5;">-</span>'}
          <span class="req-auth-text" title="${escapeHtml(authText)}">${escapeHtml(authText)}</span>
        </div>
      </td>

      <!-- 7. Tokens & Speed -->
      <td class="req-col-usage">
        <div style="display: flex; flex-direction: column; gap: 3px; font-variant-numeric: tabular-nums;">
          <div style="display: flex; align-items: center; gap: 6px;">
            <span title="${escapeHtml(tokenTitle)}" style="font-weight: 800; font-size: 13px;">${escapeHtml(tokenText)}</span>
            ${tpsText ? `<span class="request-chip tps" title="输出生成速率">${escapeHtml(tpsText)}</span>` : ''}
          </div>
          <div style="display: flex; align-items: center; gap: 5px; font-size: 10px; color: var(--text-muted); flex-wrap: wrap;">
            ${reasoningTokens ? `<span class="req-tag thinking" title="深度思考推理 Token">🧠 ${reasoningTokens.toLocaleString()}</span>` : ''}
            ${cachedTokens ? `<span class="req-tag cache" title="提示词缓存命中 Token">⚡ ${cachedTokens.toLocaleString()}</span>` : ''}
          </div>
        </div>
      </td>

      <!-- 8. Action / Detail -->
      <td class="req-col-action" onclick="event.stopPropagation()" style="text-align: center;">
        <div style="display: flex; flex-direction: column; align-items: center; gap: 4px;">
          <button class="secondary detail-pill-btn" type="button" onclick="showRequestDetailModal('${escapeHtml(reqKey)}')" title="查看全链路调用详情">详情</button>
          ${errorText ? `<span class="req-err-snippet" title="${escapeHtml(errorText)}">${escapeHtml(errorText)}</span>` : ''}
        </div>
      </td>
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

async function loadRequestEventsPanel(force = false) {
  const table = getRequestEventsTable();
  const filters = getRequestEventFilters();
  const queryKey = getRequestEventsQueryKey(filters);
  requestEventsPageSize = getRequestEventsPageSize();

  if (requestEventsLastQueryKey && requestEventsLastQueryKey !== queryKey) {
    requestEventsCurrentPage = 1;
  }

  if (table) {
    table.innerHTML = '<tr><td colspan="8" style="text-align: center; padding: 24px; color: var(--text-muted);">正在加载请求记录…</td></tr>';
  }
  setRequestEventsBusy(true);
  setRequestEventsMeta(null, 0, true);

  const offset = (requestEventsCurrentPage - 1) * requestEventsPageSize;

  try {
    const data = await api(getRequestEventsQueryUrl(requestEventsPageSize, offset, filters, force));
    const items = Array.isArray(data?.items) ? data.items : [];
    const total = Number(data?.total || 0);

    requestEventsTotal = total;
    requestEventsTotalPages = Math.max(1, Math.ceil(total / requestEventsPageSize));
    if (requestEventsCurrentPage > requestEventsTotalPages && requestEventsTotalPages > 0) {
      requestEventsCurrentPage = requestEventsTotalPages;
      return loadRequestEventsPanel(false);
    }

    if (table) {
      table.innerHTML = items.length
        ? renderRequestEventsItems(items)
        : '<tr><td colspan="8" style="text-align: center; padding: 30px; color: var(--text-muted);">暂无匹配的请求记录</td></tr>';
    }

    requestEventsLoaded = true;
    requestEventsLastQueryKey = queryKey;
    setRequestEventsMeta({ ...(data || {}), total }, items.length);
    renderRequestPagination();
  } catch (error) {
    if (table) {
      table.innerHTML = `<tr><td colspan="8" style="text-align: center; padding: 24px; color: #ef4444;">${escapeHtml(error.message || '加载请求记录失败')}</td></tr>`;
    }
  } finally {
    setRequestEventsBusy(false);
  }
}

function goToRequestPage(page) {
  const target = Math.max(1, Math.min(requestEventsTotalPages, Number(page) || 1));
  if (target === requestEventsCurrentPage && requestEventsLoaded) return;
  requestEventsCurrentPage = target;
  loadRequestEventsPanel(false);
  
  // Smoothly scroll the table container to top
  const wrap = document.querySelector('.request-table-wrap');
  if (wrap) wrap.scrollTop = 0;
}

function onRequestPageSizeChange(newSize) {
  requestEventsPageSize = Math.max(10, Math.min(500, Number(newSize) || 50));
  requestEventsCurrentPage = 1;
  
  // Sync page size selects
  const p1 = document.getElementById('request-page-size-select');
  if (p1 && p1.value !== String(requestEventsPageSize)) p1.value = String(requestEventsPageSize);
  const p2 = document.getElementById('request-page-size');
  if (p2 && p2.value !== String(requestEventsPageSize)) p2.value = String(requestEventsPageSize);

  loadRequestEventsPanel(true);
}

function handleRequestPageJumpKeydown(event) {
  if (!event || event.key !== 'Enter') return;
  event.preventDefault();
  const input = document.getElementById('req-pag-jump-input');
  const target = Number(input?.value);
  if (Number.isFinite(target) && target >= 1) {
    goToRequestPage(target);
    if (input) input.value = '';
  }
}

function renderRequestPagination() {
  const info = document.getElementById('req-pag-info');
  const btnFirst = document.getElementById('req-pag-first');
  const btnPrev = document.getElementById('req-pag-prev');
  const btnNext = document.getElementById('req-pag-next');
  const btnLast = document.getElementById('req-pag-last');
  const numbersWrap = document.getElementById('req-pag-numbers');
  const sizeSelect = document.getElementById('request-page-size-select');

  if (sizeSelect && sizeSelect.value !== String(requestEventsPageSize)) {
    sizeSelect.value = String(requestEventsPageSize);
  }

  const en = typeof getLanguage === 'function' && getLanguage() === 'en';
  const total = requestEventsTotal || 0;
  const cur = requestEventsCurrentPage || 1;
  const max = requestEventsTotalPages || 1;

  if (info) {
    info.textContent = en
      ? `Total ${total.toLocaleString()} · Page ${cur} / ${max}`
      : `共 ${total.toLocaleString()} 条 · 第 ${cur} / ${max} 页`;
  }

  if (btnFirst) btnFirst.disabled = (cur <= 1);
  if (btnPrev) btnPrev.disabled = (cur <= 1);
  if (btnNext) btnNext.disabled = (cur >= max);
  if (btnLast) btnLast.disabled = (cur >= max);

  if (!numbersWrap) return;

  // Generate page number items: e.g. 1 ... 4 5 6 ... 20
  const pages = [];
  if (max <= 7) {
    for (let i = 1; i <= max; i++) pages.push(i);
  } else {
    pages.push(1);
    let start = Math.max(2, cur - 2);
    let end = Math.min(max - 1, cur + 2);

    if (cur <= 3) {
      end = 5;
    } else if (cur >= max - 2) {
      start = max - 4;
    }

    if (start > 2) pages.push('...');
    for (let i = start; i <= end; i++) pages.push(i);
    if (end < max - 1) pages.push('...');
    pages.push(max);
  }

  const html = pages.map((p) => {
    if (p === '...') {
      return `<span class="req-pag-ellipsis">…</span>`;
    }
    const isActive = (p === cur);
    return `<button class="req-pag-num-btn secondary ${isActive ? 'active' : ''}" type="button" onclick="goToRequestPage(${p})">${p}</button>`;
  }).join('');

  numbersWrap.innerHTML = html;
}

function applyRequestEventFilters() {
  requestEventsCurrentPage = 1;
  loadRequestEventsPanel(true);
}

function clearRequestEventFilters() {
  ['request-filter-ip', 'request-filter-model', 'request-filter-provider', 'request-filter-status'].forEach(id => {
    const el = document.getElementById(id);
    if (el) el.value = '';
  });
  const success = document.getElementById('request-filter-success');
  if (success) success.value = '';
  requestEventsCurrentPage = 1;
  loadRequestEventsPanel(true);
}

function changeRequestPageSize() {
  const val = document.getElementById('request-page-size')?.value;
  if (val) onRequestPageSizeChange(val);
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

  requestEventsPageSize = 50;
  requestEventsCurrentPage = 1;

  hideRequestSettingsModal();
  applyRequestEventFilters();
}

function handleRequestFilterKeydown(event) {
  if (!event || event.key !== 'Enter') return;
  event.preventDefault();
  submitRequestSettings();
}

/* ==========================================================================
   Request Detail Modal Logic
   ========================================================================== */

function safeSetText(id, text) {
  const el = document.getElementById(id);
  if (el) el.textContent = String(text ?? '-');
}

function showRequestDetailModal(reqKey) {
  const item = _requestEventsMap.get(reqKey) || null;
  if (!item) return;
  _currentDetailItem = item;

  const modal = document.getElementById('request-detail-modal');
  if (!modal) return;

  const statusCode = Number(item.status_code || 0);
  const success = !!item.success;
  const statusClass = success ? 'ok' : (statusCode >= 500 ? 'warn' : 'off');
  const statusChip = document.getElementById('req-detail-status-chip');
  if (statusChip) {
    statusChip.className = `request-status ${statusClass}`;
    statusChip.textContent = requestStatusLabel(statusCode, success);
  }

  const idChip = document.getElementById('req-detail-id-chip');
  if (idChip) {
    idChip.textContent = item.request_id ? `ID: ${item.request_id}` : (item.trace_id ? `Trace: ${item.trace_id.slice(-12)}` : '');
  }

  // Set Timings
  const reqTime = item.request_time || (formatDashboardTs(item.timestamp).time + ' ' + formatDashboardTs(item.timestamp).day);
  const respTime = item.response_time || item.upstream_response_time || '-';
  const totalLatency = item.latency_ms != null ? formatLatency(item.latency_ms) : '-';
  const upReqTime = item.upstream_request_time || '-';
  const upRespTime = item.upstream_response_time || '-';

  const upLatency = item.upstream_latency_ms != null ? formatLatency(item.upstream_latency_ms) : (item.latency_ms != null ? formatLatency(item.latency_ms) : '-');
  const gatewayOverhead = item.overhead_ms != null ? `${item.overhead_ms} ms` : '< 5 ms';
  const stageBreakdown = `上游: ${upLatency} · 本地网关: ${gatewayOverhead}`;

  safeSetText('rd-req-time', reqTime);
  safeSetText('rd-resp-time', respTime);
  safeSetText('rd-total-latency', totalLatency);
  safeSetText('rd-up-req-time', upReqTime);
  safeSetText('rd-up-resp-time', upRespTime);
  safeSetText('rd-stage-breakdown', stageBreakdown);

  // Set Model & Route
  const reqModel = item.requested_model || getRequestModelPlaceholder(item);
  const routedModel = item.routed_model || item.actual_model || item.requested_model || '-';
  const provider = item.inferred_provider || item.actual_provider || '-';
  const authText = item.auth_label || (item.auth_id ? `ID: ${item.auth_id}` : (item.api_key_masked ? `Key: ${item.api_key_masked}` : '-'));
  const authFile = item.auth_file || '';
  const upstreamUrl = item.upstream_url || (item.inferred_provider ? `通过 ${item.inferred_provider} 上游分发` : '-');

  safeSetText('rd-req-model', reqModel);
  safeSetText('rd-routed-model', routedModel);
  safeSetText('rd-provider', provider);
  safeSetText('rd-auth', authText);

  const authFileRow = document.getElementById('rd-auth-file-row');
  const authFileEl = document.getElementById('rd-auth-file');
  if (authFileRow && authFileEl) {
    if (authFile) {
      authFileEl.textContent = authFile;
      authFileRow.style.display = '';
    } else {
      authFileRow.style.display = 'none';
    }
  }
  safeSetText('rd-upstream-url', upstreamUrl);

  // Set Tokens & Speed
  const promptTokens = item.prompt_tokens != null ? item.prompt_tokens.toLocaleString() : '-';
  const compTokens = item.completion_tokens != null ? item.completion_tokens.toLocaleString() : '-';
  const totalTokens = item.total_tokens != null ? item.total_tokens.toLocaleString() : '-';
  const tps = item.tps || (item.completion_tokens && item.latency_ms && item.latency_ms > 0 ? (item.completion_tokens / (item.latency_ms / 1000)).toFixed(1) : null);
  const tpsText = tps ? `${tps} tok/s` : '-';
  const cachedTokens = item.cached_tokens != null ? `${item.cached_tokens.toLocaleString()} tok` : '0 tok';
  const reasoningTokens = item.reasoning_tokens != null ? `${item.reasoning_tokens.toLocaleString()} tok` : '0 tok';
  const streamMode = item.stream ? '⚡ SSE 流式传输 (Stream)' : '📦 阻塞/非流式传输';
  const finishReason = item.finish_reason || (item.success ? 'stop' : (item.status_code ? `HTTP ${item.status_code}` : '-'));

  safeSetText('rd-prompt-tokens', promptTokens);
  safeSetText('rd-comp-tokens', compTokens);
  safeSetText('rd-total-tokens', totalTokens);
  safeSetText('rd-tps', tpsText);
  safeSetText('rd-cached-tokens', cachedTokens);
  safeSetText('rd-reasoning-tokens', reasoningTokens);
  safeSetText('rd-stream-mode', streamMode);
  safeSetText('rd-finish-reason', finishReason);

  // Set Client & Traces
  const clientIp = item.client_ip ? `${item.client_ip}${item.client_ip_source ? ' (via ' + item.client_ip_source + ')' : ''}` : '-';
  const userAgent = item.user_agent || (item.session_id ? `Session: ${item.session_id}` : '-');
  const traceId = item.trace_id || '-';
  const upstreamReqId = item.upstream_request_id || '-';

  safeSetText('rd-client-ip', clientIp);
  safeSetText('rd-user-agent', userAgent);
  safeSetText('rd-trace-id', traceId);
  safeSetText('rd-upstream-req-id', upstreamReqId);

  // Set Previews
  safeSetText('rd-prompt-preview-content', item.prompt_preview || '未捕获提示词或非标准格式');
  safeSetText('rd-resp-preview-content', item.response_preview || (item.error_summary ? `❌ 错误: ${item.error_summary}` : '未捕获响应结果预览'));

  // Set Raw Log Meta
  safeSetText('rd-raw-filename', item.log_file ? `日志文件: ${item.log_file}` : '无关联日志文件');
  safeSetText('rd-raw-log-content', '点击切换到原始日志选项卡以加载完整内容…');

  switchRequestDetailTab('overview');
  modal.removeAttribute('hidden');
}

function hideRequestDetailModal() {
  document.getElementById('request-detail-modal')?.setAttribute('hidden', 'true');
  _currentDetailItem = null;
}

function switchRequestDetailTab(tabName) {
  const tabs = ['overview', 'preview', 'raw'];
  for (const t of tabs) {
    const btn = document.getElementById(`req-tab-${t}-btn`);
    const pane = document.getElementById(`req-tab-pane-${t}`);
    if (btn) {
      if (t === tabName) btn.classList.add('active');
      else btn.classList.remove('active');
    }
    if (pane) {
      pane.style.display = (t === tabName) ? 'flex' : 'none';
    }
  }

  if (tabName === 'raw' && _currentDetailItem?.log_file) {
    loadRequestRawLog(_currentDetailItem.log_file);
  }
}

async function loadRequestRawLog(filename) {
  const pre = document.getElementById('rd-raw-log-content');
  if (!pre) return;
  pre.textContent = '正在加载原始日志内容…';
  try {
    const data = await api(`/api/request-log-raw?file=${encodeURIComponent(filename)}`);
    if (data && data.content) {
      pre.textContent = data.content;
    } else {
      pre.textContent = '日志内容为空或未找到。';
    }
  } catch (err) {
    pre.textContent = `加载日志失败: ${err.message || '网络错误'}`;
  }
}

function copyRequestRawLog() {
  const pre = document.getElementById('rd-raw-log-content');
  const text = pre?.textContent || '';
  if (!text || text.startsWith('正在加载') || text.startsWith('点击切换')) {
    if (typeof showMessage === 'function') showMessage('暂无可复制的日志内容');
    return;
  }
  navigator.clipboard.writeText(text).then(() => {
    if (typeof showMessage === 'function') showMessage('已复制完整日志内容到剪贴板！');
  }).catch(() => {
    if (typeof showMessage === 'function') showMessage('复制失败，请手动选择复制');
  });
}

function copyRequestCurlCommand() {
  if (!_currentDetailItem) return;
  const item = _currentDetailItem;
  const path = item.path || '/v1/chat/completions';
  const model = item.requested_model || 'gpt-4o';
  const curl = `curl -X POST "http://127.0.0.1:8000${path}" \\\n` +
    `  -H "Content-Type: application/json" \\\n` +
    `  -H "Authorization: Bearer YOUR_API_KEY" \\\n` +
    `  -d '{\n` +
    `    "model": "${model}",\n` +
    `    "messages": [{"role": "user", "content": "Hello"}],\n` +
    `    "stream": ${item.stream ? 'true' : 'false'}\n` +
    `  }'`;
  navigator.clipboard.writeText(curl).then(() => {
    if (typeof showMessage === 'function') showMessage('已复制 cURL 请求示例到剪贴板！');
  }).catch(() => {
    if (typeof showMessage === 'function') showMessage('复制失败，请手动选择复制');
  });
}
