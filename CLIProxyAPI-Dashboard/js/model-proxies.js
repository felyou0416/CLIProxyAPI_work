let modelProxySettingsCache = null;
let modelProxyItemsCache = [];
let activeModelProxyStateFilter = 'all';
let modelProxySearchValue = '';

const MODEL_PROXY_SUPPORTED_PROVIDERS = new Set([
  'aihubmix',
  'googleai',
  'groq',
  'glm',
  'hunyuan',
  'longcat',
  'minimax-portal',
  'opencode',
  'openrouter',
  'volcengine',
  'zenmux',
  'zhipu',
]);

const MODEL_PROXY_STATE_OPTIONS = [
  { id: 'all', zh: '全部', en: 'All' },
  { id: 'configured', zh: '已配置', en: 'Configured' },
  { id: 'unconfigured', zh: '未配置', en: 'Unconfigured' },
];

function escapeModelProxyHtml(value) {
  if (typeof escapeProviderHtml === 'function') return escapeProviderHtml(value);
  return String(value ?? '')
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#39;');
}

function modelProxyStateLabel(id) {
  const item = MODEL_PROXY_STATE_OPTIONS.find((option) => option.id === id);
  if (!item) return id;
  return getLanguage() === 'zh' ? item.zh : item.en;
}

function buildProviderProxyRows(items) {
  const rows = [];
  const seen = new Set();
  (items || []).forEach((item) => {
    const provider = String(item?.provider || item?.lookup_provider || '').trim().toLowerCase() || '-';
    if (!MODEL_PROXY_SUPPORTED_PROVIDERS.has(provider)) return;
    if (seen.has(provider)) return;
    seen.add(provider);
    const providerRows = normalizeProviderRows(item);
    const callIds = [];
    const upstreamIds = [];
    providerRows.forEach((row) => {
      const callId = String(row?.call_id || '').trim();
      const upstreamId = String(row?.upstream_id || row?.lookup_upstream_id || '').trim();
      if (callId && !callIds.includes(callId)) callIds.push(callId);
      if (upstreamId && !upstreamIds.includes(upstreamId)) upstreamIds.push(upstreamId);
    });
    rows.push({
      provider,
      model_count: callIds.length || providerRows.length || 0,
      call_ids: callIds,
      upstream_ids: upstreamIds,
    });
  });
  return rows.sort((a, b) => a.provider.localeCompare(b.provider));
}

function getModelProxyRowsWithState(settings, items) {
  const rules = settings?.rules || {};
  return buildProviderProxyRows(items).map((row) => {
    const activeRule = rules[row.provider] || {};
    const presetId = String(activeRule?.preset_id || '').trim();
    return {
      ...row,
      preset_id: presetId,
      configured: Boolean(presetId),
      rule: activeRule,
    };
  });
}

function filterModelProxyRows(rows) {
  const keyword = String(modelProxySearchValue || '').trim().toLowerCase();
  return rows.filter((row) => {
    if (activeModelProxyStateFilter === 'configured' && !row.configured) return false;
    if (activeModelProxyStateFilter === 'unconfigured' && row.configured) return false;
    if (!keyword) return true;
    const haystack = [row.provider, row.call_ids.join(' '), row.upstream_ids.join(' '), row.rule?.label, row.rule?.proxy_name]
      .map((value) => String(value || '').toLowerCase())
      .join(' ');
    return haystack.includes(keyword);
  });
}

function renderModelProxyPresets(settings) {
  const root = document.getElementById('model-proxy-presets');
  if (!root) return;
  const presets = Array.isArray(settings?.presets) ? settings.presets : [];
  const mixedPort = Number(settings?.mixed_port || 0);
  root.innerHTML = presets.map((item) => {
    const proxyUrl = String(item?.proxy_url || '').trim() || '-';
    const proxyName = String(item?.proxy_name || '').trim() || (getLanguage() === 'zh' ? '当前由 Clash 选择' : 'Selected in Clash');
    return `
      <article class="model-proxy-preset">
        <strong>${escapeModelProxyHtml(item?.label || item?.id || '-')}</strong>
        <div class="model-proxy-meta">Preset ID: ${escapeModelProxyHtml(item?.id || '-')}</div>
        <div class="model-proxy-meta">Proxy URL: ${escapeModelProxyHtml(proxyUrl)}</div>
        <div class="model-proxy-meta">Clash Node: ${escapeModelProxyHtml(proxyName)}</div>
        <div class="model-proxy-meta">${mixedPort ? `Mixed Port: ${mixedPort}` : (getLanguage() === 'zh' ? '未检测到 mixed-port' : 'No mixed-port detected')}</div>
      </article>
    `;
  }).join('') || `<div class="auth-empty">${getLanguage() === 'zh' ? '还没有可用的代理预设。' : 'No proxy presets available.'}</div>`;
}

function renderModelProxyFilters(rows) {
  const stateRoot = document.getElementById('model-proxy-state-filters');
  if (stateRoot) {
    const counts = {
      all: rows.length,
      configured: rows.filter((row) => row.configured).length,
      unconfigured: rows.filter((row) => !row.configured).length,
    };
    stateRoot.innerHTML = MODEL_PROXY_STATE_OPTIONS.map((item) => `
      <button
        type="button"
        class="provider-category-btn ${activeModelProxyStateFilter === item.id ? 'is-active' : ''}"
        data-model-proxy-state="${escapeModelProxyHtml(item.id)}"
      >${escapeModelProxyHtml(modelProxyStateLabel(item.id))} <span>${counts[item.id] || 0}</span></button>
    `).join('');
    stateRoot.querySelectorAll('[data-model-proxy-state]').forEach((btn) => {
      btn.onclick = () => {
        activeModelProxyStateFilter = btn.getAttribute('data-model-proxy-state') || 'all';
        renderModelProxyRows(modelProxySettingsCache, modelProxyItemsCache);
      };
    });
  }
}

function renderModelProxyRows(settings, items) {
  const root = document.getElementById('model-proxy-list');
  const summary = document.getElementById('model-proxy-summary');
  if (!root) return;

  modelProxyItemsCache = items || [];
  const presets = Array.isArray(settings?.presets) ? settings.presets : [];
  const allRows = getModelProxyRowsWithState(settings, items);
  const rows = filterModelProxyRows(allRows);
  const optionsHtml = [
    `<option value="">${getLanguage() === 'zh' ? '不设置 / 保持原样' : 'Unset / keep original'}</option>`,
    ...presets.map((item) => `<option value="${escapeModelProxyHtml(item.id)}">${escapeModelProxyHtml(item.label || item.id)}</option>`),
  ].join('');

  renderModelProxyFilters(allRows);
  root.innerHTML = rows.map((row) => {
    const activeRule = row.rule || {};
    const currentPreset = String(activeRule?.preset_id || '').trim();
    const detail = currentPreset
      ? `${activeRule.label || currentPreset}${activeRule.proxy_url ? ` | ${activeRule.proxy_url}` : ''}`
      : (getLanguage() === 'zh' ? '当前未绑定默认代理' : 'No default proxy assigned');
    const modelPreview = row.call_ids.slice(0, 6).join(', ');
    const remainCount = Math.max(0, row.call_ids.length - 6);
    const modelHint = row.call_ids.length
      ? `${modelPreview}${remainCount ? (getLanguage() === 'zh' ? ` 等 ${row.call_ids.length} 个模型` : ` and ${remainCount} more`) : ''}`
      : (getLanguage() === 'zh' ? '未识别到模型列表' : 'No model list detected');
    return `
      <label class="model-proxy-row">
        <div class="model-proxy-main">
          <strong>${escapeModelProxyHtml(row.provider)}</strong>
          <div class="model-proxy-sub">${getLanguage() === 'zh' ? `覆盖 ${row.model_count} 个模型` : `${row.model_count} models covered`}</div>
          <div class="model-proxy-sub">${escapeModelProxyHtml(modelHint)}</div>
          <div class="model-proxy-sub">${escapeModelProxyHtml(detail)}</div>
        </div>
        <select class="model-proxy-select" data-model-proxy-provider="${escapeModelProxyHtml(row.provider)}">
          ${optionsHtml}
        </select>
      </label>
    `;
  }).join('') || `<div class="auth-empty">${getLanguage() === 'zh' ? '当前筛选条件下没有匹配的 provider。' : 'No providers match the current filters.'}</div>`;

  root.querySelectorAll('[data-model-proxy-provider]').forEach((select) => {
    const provider = select.getAttribute('data-model-proxy-provider') || '';
    const activeRule = settings?.rules?.[provider] || {};
    select.value = String(activeRule?.preset_id || '').trim();
  });

  if (summary) {
    const configured = allRows.filter((row) => row.configured).length;
    const totalModels = allRows.reduce((sum, row) => sum + (Number(row.model_count) || 0), 0);
    const shownModels = rows.reduce((sum, row) => sum + (Number(row.model_count) || 0), 0);
    summary.textContent = getLanguage() === 'zh'
      ? `Provider 总数 ${allRows.length}，当前显示 ${rows.length}，已配置 ${configured}，覆盖模型 ${shownModels}/${totalModels}`
      : `${allRows.length} providers, ${rows.length} shown, ${configured} configured, covering ${shownModels}/${totalModels} models`;
  }
}

function setModelProxySearch(value) {
  modelProxySearchValue = String(value || '');
  renderModelProxyRows(modelProxySettingsCache, modelProxyItemsCache);
}

async function loadModelProxyPanel(force = false) {
  const section = document.getElementById('section-model-proxy');
  if (!section) return;
  try {
    const [settingsData, providerItems] = await Promise.all([
      api('/api/model-proxy-settings'),
      (typeof fetchRuntimeProviderModelItems === 'function' ? fetchRuntimeProviderModelItems() : fetchProviderModelItems()),
    ]);
    modelProxySettingsCache = settingsData?.item || {};
    modelProxyItemsCache = providerItems || [];
    renderModelProxyPresets(modelProxySettingsCache);
    renderModelProxyRows(modelProxySettingsCache, modelProxyItemsCache);
  } catch (err) {
    showMessage(err.message, true);
  }
}

async function saveModelProxyPanel() {
  const root = document.getElementById('model-proxy-list');
  if (!root) return;
  const rules = [];
  root.querySelectorAll('[data-model-proxy-provider]').forEach((select) => {
    const provider = String(select.getAttribute('data-model-proxy-provider') || '').trim().toLowerCase();
    const presetId = String(select.value || '').trim();
    if (!provider || !presetId) return;
    rules.push({ provider, preset_id: presetId, enabled: true });
  });
  try {
    const result = await api('/api/model-proxy-settings', 'POST', { rules });
    showMessage(result.message || (getLanguage() === 'zh' ? '模型代理设置已保存。' : 'Model proxy settings saved.'));
    await loadModelProxyPanel(true);
  } catch (err) {
    showMessage(err.message, true);
  }
}
