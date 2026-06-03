let overviewPanelLoaded = false;

function overviewApiWithTimeout(path, timeoutMs = 2500) {
  return Promise.race([
    api(path),
    new Promise((_, reject) => setTimeout(() => reject(new Error(`timeout: ${path}`)), timeoutMs)),
  ]);
}

function summarizeOverviewFailureReason(items) {
  const counts = new Map();
  for (const item of items || []) {
    const reason = String(item.failure_kind || item.recent_failure_reason || '').trim();
    if (!reason) continue;
    counts.set(reason, (counts.get(reason) || 0) + 1);
  }
  let bestReason = '-';
  let bestCount = 0;
  for (const [reason, count] of counts.entries()) {
    if (count > bestCount) {
      bestReason = reason;
      bestCount = count;
    }
  }
  return { reason: bestReason, count: bestCount };
}

function summarizeTopFailures(items, keyName) {
  const counts = new Map();
  for (const item of items || []) {
    const statusCode = Number(item.status_code || 0);
    if (statusCode < 400) continue;
    const key = String(item[keyName] || '').trim() || '-';
    counts.set(key, (counts.get(key) || 0) + 1);
  }
  let bestKey = '-';
  let bestCount = 0;
  for (const [key, count] of counts.entries()) {
    if (count > bestCount) {
      bestKey = key;
      bestCount = count;
    }
  }
  return { key: bestKey, count: bestCount };
}

function countStatuses(items) {
  let success = 0;
  let failure = 0;
  let count429 = 0;
  let count5xx = 0;
  for (const item of items || []) {
    const statusCode = Number(item.status_code || 0);
    if (item.success) success += 1;
    else failure += 1;
    if (statusCode === 429) count429 += 1;
    if (statusCode >= 500) count5xx += 1;
  }
  return { success, failure, count429, count5xx };
}

function overviewCardHtml(label, value, note = '') {
  return `
    <div class="summary-tile small-tile">
      <div class="summary-label">${label}</div>
      <div class="summary-value">${value}</div>
      ${note ? `<div class="tool-desc-zh">${note}</div>` : ''}
    </div>
  `;
}

async function loadOverviewPanel(force = false) {
  if (overviewPanelLoaded && !force) return;
  const wrap = document.getElementById('overview-grid');
  if (wrap) wrap.innerHTML = '<div class="metric-empty">loading...</div>';
  try {
    const [statusRes, requestsRes, clientsRes, authRes, modelRes] = await Promise.allSettled([
      overviewApiWithTimeout('/api/status', 2500),
      overviewApiWithTimeout('/api/request-events?limit=200', 2500),
      overviewApiWithTimeout('/api/request-clients', 2500),
      overviewApiWithTimeout('/api/auth-health', 2500),
      overviewApiWithTimeout('/api/model-health?runtime=0', 2500),
    ]);

    const statusData = statusRes.status === 'fulfilled' ? statusRes.value : { status: {} };
    const requestsData = requestsRes.status === 'fulfilled' ? requestsRes.value : { items: [] };
    const clientsData = clientsRes.status === 'fulfilled' ? clientsRes.value : { items: [] };
    const authData = authRes.status === 'fulfilled' ? authRes.value : { items: [] };
    const modelData = modelRes.status === 'fulfilled' ? modelRes.value : { items: [] };

    const s = statusData.status || {};
    const requestItems = Array.isArray(requestsData.items) ? requestsData.items : [];
    const clientItems = Array.isArray(clientsData.items) ? clientsData.items : [];
    const authItems = Array.isArray(authData.items) ? authData.items : [];
    const modelItems = Array.isArray(modelData.items) ? modelData.items : [];

    const stats = countStatuses(requestItems);
    const providerSet = new Set((authItems || []).map(item => String(item.provider || '').trim()).filter(Boolean));
    const unhealthyModels = modelItems.filter(item => item.available === false);
    const specializedModels = modelItems.filter(item => String(item.failure_kind || '').trim() === 'specialized');
    const failedProvider = summarizeTopFailures(requestItems, 'inferred_provider');
    const failedModel = summarizeTopFailures(requestItems, 'requested_model');
    const failureReason = summarizeOverviewFailureReason([...authItems, ...modelItems]);
    const degraded = [statusRes, requestsRes, clientsRes, authRes, modelRes].some((entry) => entry.status !== 'fulfilled');

    const cards = [
      overviewCardHtml('代理状态', s.proxy_running ? '运行中' : '未运行', s.local_proxy_url || 'http://127.0.0.1:8317'),
      overviewCardHtml('当前选中 Auth', (Array.isArray(s.selected_auth_refs) ? s.selected_auth_refs.length : 0) || 0, s.selected_auth || '-'),
      overviewCardHtml('当前应用 Auth', (Array.isArray(s.applied_auth_refs) ? s.applied_auth_refs.length : 0) || 0, s.applied_auth || '-'),
      overviewCardHtml('启用 Provider 数', providerSet.size || 0, providerSet.size ? Array.from(providerSet).join(', ') : (degraded ? '部分数据不可用' : '-')),
      overviewCardHtml('最近请求数', requestItems.length || 0, `客户端 ${clientItems.length || 0} 个`),
      overviewCardHtml('成功 / 失败', `${stats.success} / ${stats.failure}`, `429: ${stats.count429} · 5xx: ${stats.count5xx}`),
      overviewCardHtml('失败最多 Provider', failedProvider.key, failedProvider.count ? `${failedProvider.count} 次` : '暂无'),
      overviewCardHtml('失败最多模型', failedModel.key, failedModel.count ? `${failedModel.count} 次` : '暂无'),
      overviewCardHtml('失败原因 Top', failureReason.reason, failureReason.count ? `${failureReason.count} 次` : '暂无'),
      overviewCardHtml('异常模型数', unhealthyModels.length || 0, `specialized: ${specializedModels.length || 0}${degraded ? ' · 部分接口超时' : ''}`),
    ].join('');

    if (wrap) wrap.innerHTML = cards;
    overviewPanelLoaded = true;
  } catch (error) {
    if (wrap) wrap.innerHTML = `<div class="metric-empty">${error.message || 'load failed'}</div>`;
  }
}
