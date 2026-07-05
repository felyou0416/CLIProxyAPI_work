let modelsPanelLoaded = false;
let modelStatsPanelLoaded = false;
let modelStatsItems = [];
let modelStatsActiveProvider = '';

function modelStatsEscape(value) {
  return String(value ?? '')
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#39;');
}

function formatModelStatsTime(timestamp) {
  const value = Number(timestamp || 0);
  if (!value) return '-';
  try {
    return new Date(value * 1000).toLocaleString();
  } catch {
    return '-';
  }
}

function modelStatsAvailability(item) {
  if (item.available === true) return '<span class="pill ok">可用</span>';
  if (item.available === false) return `<span class="pill warn">${modelStatsEscape(item.failure_kind || '不可用')}</span>`;
  return '<span class="pill off">未检测</span>';
}

function modelStatsFormatTokens(num) {
  const value = Number(num || 0);
  if (!value) return '0';
  if (value >= 1_000_000) return (value / 1_000_000).toFixed(1) + 'M';
  if (value >= 1_000) return (value / 1_000).toFixed(1) + 'K';
  return value.toLocaleString();
}

function modelStatsTokenTitle(item) {
  const p = Number(item.prompt_tokens || 0).toLocaleString();
  const c = Number(item.completion_tokens || 0).toLocaleString();
  return `Prompt: ${p}\nCompletion: ${c}`;
}

function modelStatsRowHtml(item) {
  const rate = Number(item.success_rate_percent || 0);
  const provider = item.provider || '-';
  const canDelete = Boolean(item.can_delete && item.delete_provider && item.delete_upstream_id);
  const deleteAttrs = canDelete
    ? `data-provider="${modelStatsEscape(item.delete_provider)}" data-upstream="${modelStatsEscape(item.delete_upstream_id)}" data-model="${modelStatsEscape(item.model || '')}"`
    : 'disabled';
  const pt = modelStatsFormatTokens(item.prompt_tokens);
  const ct = modelStatsFormatTokens(item.completion_tokens);
  const tt = modelStatsFormatTokens(item.total_tokens);
  const tokenTitle = modelStatsTokenTitle(item);
  return `
    <tr>
      <td class="model-stats-model">
        <div><code>${modelStatsEscape(item.model || '-')}</code></div>
        <div class="metric-note"><small>实际: ${modelStatsEscape(item.actual_model || item.delete_upstream_id || '-')}</small></div>
      </td>
      <td>${modelStatsEscape(provider)}</td>
      <td class="metric-number" title="${tokenTitle}">${pt}</td>
      <td class="metric-number" title="${tokenTitle}">${ct}</td>
      <td class="metric-number" title="${tokenTitle}"><strong>${tt}</strong></td>
      <td class="metric-number"><strong>${rate.toFixed(2)}%</strong></td>
      <td class="metric-number">${Number(item.success_count || 0)}</td>
      <td class="metric-number">${Number(item.failure_count || 0)}</td>
      <td class="metric-number">${Number(item.total_tests || 0)}</td>
      <td>${modelStatsAvailability(item)}</td>
      <td class="model-stats-actions">
        <button class="secondary danger model-stats-delete" type="button" ${deleteAttrs}>删除</button>
      </td>
    </tr>
  `;
}

function modelStatsProviderCounts(items) {
  const counts = new Map();
  for (const item of items) {
    const provider = String(item.provider || '未识别').trim() || '未识别';
    counts.set(provider, (counts.get(provider) || 0) + 1);
  }
  return Array.from(counts.entries()).sort((a, b) => a[0].localeCompare(b[0]));
}

function renderModelStatsFilters(items) {
  const wrap = document.getElementById('model-test-stats-filters');
  if (!wrap) return;
  const counts = modelStatsProviderCounts(items);
  const providerExists = counts.some(([provider]) => provider === modelStatsActiveProvider);
  if (!providerExists) modelStatsActiveProvider = counts[0]?.[0] || '';
  const buttonHtml = counts.map(([provider, count]) => (
    `<button class="provider-category-btn ${modelStatsActiveProvider === provider ? 'is-active' : ''}" type="button" data-provider="${modelStatsEscape(provider)}">${modelStatsEscape(provider)}<span>${count}</span></button>`
  )).join('');
  wrap.innerHTML = buttonHtml;
  wrap.querySelectorAll('button[data-provider]').forEach((button) => {
    button.addEventListener('click', () => {
      modelStatsActiveProvider = button.dataset.provider || '';
      renderModelStatsPanel();
    });
  });
}

function groupedModelStatsHtml(items) {
  const visibleItems = items.filter((item) => (String(item.provider || '未识别').trim() || '未识别') === modelStatsActiveProvider);
  const groups = new Map();
  for (const item of visibleItems) {
    const provider = String(item.provider || '未识别').trim() || '未识别';
    if (!groups.has(provider)) groups.set(provider, []);
    groups.get(provider).push(item);
  }
  if (!visibleItems.length) return '<div class="metric-empty">当前 Provider 暂无模型测试统计</div>';
  return Array.from(groups.entries()).map(([provider, rows]) => `
    <section class="model-stats-provider-group">
      <div class="model-stats-provider-head">
        <strong>${modelStatsEscape(provider)}</strong>
        <span class="auth-chip">${rows.length} 个</span>
      </div>
      <div class="metric-table-wrap metric-table-wrap-compact">
        <table class="metric-table model-stats-table">
          <thead>
            <tr>
              <th>Model</th>
              <th>Provider</th>
              <th>Prompt Tokens</th>
              <th>Completion Tokens</th>
              <th>Total Tokens</th>
              <th>成功率</th>
              <th>成功</th>
              <th>失败</th>
              <th>总数</th>
              <th>检测可用</th>
              <th></th>
            </tr>
          </thead>
          <tbody>${rows.map(modelStatsRowHtml).join('')}</tbody>
        </table>
      </div>
    </section>
  `).join('');
}

function bindModelStatsDeleteButtons(wrap) {
  wrap.querySelectorAll('.model-stats-delete').forEach((button) => {
    button.addEventListener('click', () => deleteModelStatsModel(button));
  });
}

function renderModelStatsPanel() {
  renderModelStatsFilters(modelStatsItems);
  const wrap = document.getElementById('model-test-stats-body');
  if (!wrap) return;
  wrap.innerHTML = modelStatsItems.length
    ? groupedModelStatsHtml(modelStatsItems)
    : '<div class="metric-empty">暂无模型测试统计</div>';
  bindModelStatsDeleteButtons(wrap);
}

async function deleteModelStatsModel(button) {
  const provider = button?.dataset?.provider || '';
  const upstream = button?.dataset?.upstream || '';
  const model = button?.dataset?.model || upstream;
  if (!provider || !upstream) return;
  const ok = window.confirm(`删除 ${model}？\nProvider: ${provider}\n后台模型列表会同步隐藏并重建配置。`);
  if (!ok) return;
  button.disabled = true;
  button.textContent = '删除中';
  try {
    await api('/api/provider-model-delete', 'POST', {
      provider,
      upstream_id: upstream,
      call_id: model,
    });
    modelStatsPanelLoaded = false;
    await loadModelStatsPanel(true);
  } catch (error) {
    button.disabled = false;
    button.textContent = '删除';
    alert(error.message || '删除失败');
  }
}

async function loadModelStatsPanel(force = false) {
  if (modelStatsPanelLoaded && !force) return;
  const wrap = document.getElementById('model-test-stats-body');
  const meta = document.getElementById('model-test-stats-meta');
  if (wrap) wrap.innerHTML = '<div class="metric-empty">loading...</div>';
  try {
    const data = await api(`/api/model-test-stats?limit=500${force ? '&refresh=1' : ''}`);
    const items = Array.isArray(data.items) ? data.items : [];
    modelStatsItems = items;
    if (meta) {
      const refreshed = data.refreshed_at ? new Date(Number(data.refreshed_at) * 1000).toLocaleTimeString() : '-';
      meta.textContent = `${items.length} 个模型 · 累计 Token · 最近 ${data.limit || 500} 条可用性 · ${refreshed}`;
    }
    renderModelStatsPanel();
    modelStatsPanelLoaded = true;
  } catch (error) {
    if (wrap) wrap.innerHTML = `<div class="metric-empty">${modelStatsEscape(error.message || 'load failed')}</div>`;
  }
}

function modelHealthCardHtml(item) {
  const runtime = item.runtime_registered ? '<span class="pill ok">runtime</span>' : '<span class="pill off">config-only</span>';
  const availability = item.available === true
    ? '<span class="pill ok">available</span>'
    : item.available === false
      ? `<span class="pill warn">${item.failure_kind || 'unavailable'}</span>`
      : '<span class="pill off">untested</span>';
  return `
    <div class="metric-card">
      <div class="metric-card-head">
        <strong>${item.call_id}</strong>
        <span class="auth-chip">${item.provider}</span>
      </div>
      <div class="metric-kv">
        <span>上游</span><code>${item.upstream_id || '-'}</code>
      </div>
      <div class="metric-kv">
        <span>请求数</span><strong>${item.request_count || 0}</strong>
      </div>
      <div class="metric-kv">
        <span>评分</span><strong>${item.capability_score || 0}</strong>
      </div>
      <div class="metric-pills">${runtime}${availability}</div>
      <div class="metric-note">${item.message || '-'}</div>
    </div>
  `;
}

async function loadModelsPanel(force = false) {
  if (modelsPanelLoaded && !force) return;
  const wrap = document.getElementById('model-health-list');
  const meta = document.getElementById('model-health-meta');
  if (wrap) wrap.innerHTML = '<div class="metric-empty">loading...</div>';
  try {
    const data = await api('/api/model-health?runtime=1');
    const items = Array.isArray(data.items) ? data.items : [];
    if (meta) meta.textContent = `${items.length} 个模型`;
    if (wrap) {
      wrap.innerHTML = items.length
        ? items.map(modelHealthCardHtml).join('')
        : '<div class="metric-empty">暂无模型健康数据</div>';
    }
    modelsPanelLoaded = true;
  } catch (error) {
    if (wrap) wrap.innerHTML = `<div class="metric-empty">${error.message || 'load failed'}</div>`;
  }
}
