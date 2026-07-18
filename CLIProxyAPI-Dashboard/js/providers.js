let activeProviderMapping = '';
let activeProviderGroup = 'all';
let providerModelItemsCache = [];
let providerModelMappingItemsCache = [];
let selectedProviderModels = new Set();
let providerModelStatuses = {};
let providerModelStatusMeta = {};
let providerModelsRunningSet = new Set();
let providerModelStatePollTimer = null;
let providerRouteStrategyLoaded = false;
let _cachedProviderFingerprint = '';

const PROVIDER_MODEL_CATEGORY_MATCHERS = {
  dialog: new Set([
    'openrouter/arcee-ai/trinity-large-preview:free',
    'openrouter/arcee-ai/trinity-mini:free',
    'openrouter/liquid/lfm-2.5-1.2b-instruct:free',
    'openrouter/meta-llama/llama-3.3-70b-instruct:free',
    'openrouter/qwen/qwen3-next-80b-a3b-instruct:free',
    'openrouter/mistralai/mistral-small-3.1-24b-instruct:free',
  ]),
  image: new Set([
    'openrouter/nvidia/nemotron-nano-12b-v2-vl:free',
    'openrouter/nvidia/llama-nemotron-embed-vl-1b-v2:free',
    'openrouter/google/gemma-3-27b-it:free',
    'openrouter/google/gemma-3-12b-it:free',
    'openrouter/google/gemma-3-4b-it:free',
    'openrouter/sourceful/riverflow-v2-pro:free',
    'openrouter/sourceful/riverflow-v2-fast:free',
    'google-antigravity/gemini-3-1-flash-image',
    'gemini-3.1-flash-image-preview-free',
  ]),
  agent: new Set([
    'openrouter/minimax/minimax-m2.5:free',
    'openrouter/arcee-ai/trinity-large-preview:free',
    'openrouter/liquid/lfm-2.5-1.2b-thinking:free',
    'openrouter/qwen/qwen3-coder:free',
    'openrouter/nvidia/nemotron-3-super-120b-a12b:free',
    'openrouter/free',
    'minimax-m2.5-free',
  ]),
  coding: new Set([
    'openrouter/qwen/qwen3-coder:free',
    'openrouter/minimax/minimax-m2.5:free',
    'openrouter/nvidia/nemotron-3-super-120b-a12b:free',
    'coding-glm-4.6-free',
    'coding-glm-4.7-free',
    'coding-glm-5-free',
    'coding-glm-5-turbo-free',
    'coding-minimax-m2-free',
    'coding-minimax-m2.1-free',
    'coding-minimax-m2.5-free',
    'coding-minimax-m2.7-free',
    'kimi-for-coding-free',
    'codex-5.5',
    'gpt-5.3-codex',
    'gpt-5.2-codex',
    'gpt-5.1-codex-max',
    'gpt-5.1-codex-mini',
    'gpt-5.1-codex',
    'gpt-5-codex-mini',
    'gpt-5-codex',
  ]),
  reasoning: new Set([
    'openrouter/stepfun/step-3.5-flash:free',
    'openrouter/nvidia/nemotron-3-super-120b-a12b:free',
    'openrouter/liquid/lfm-2.5-1.2b-thinking:free',
    'step-3.5-flash-free',
  ]),
};

function escapeProviderHtml(value) {
  return String(value ?? '')
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#39;');
}

function escapeSelectorValue(value) {
  return CSS.escape(String(value || ''));
}

function normalizeProviderRows(item) {
  return Array.isArray(item?.rows) ? item.rows : [];
}

function normalizeModelKey(value) {
  return String(value || '').trim().toLowerCase();
}

function _providerAvail() {
  return (typeof Availability !== 'undefined' && Availability) ? Availability : null;
}

function formatRetryAfter(seconds) {
  const A = _providerAvail();
  if (A) {
    const text = A.formatRetryAfter(seconds);
    if (text) return text;
    return getLanguage() === 'zh' ? '无需重试' : 'No retry needed';
  }
  const value = Number(seconds || 0);
  if (!value) return getLanguage() === 'zh' ? '无需重试' : 'No retry needed';
  if (value < 60) return getLanguage() === 'zh' ? `${value} 秒后重试` : `Retry in ${value}s`;
  return getLanguage() === 'zh' ? `${Math.ceil(value / 60)} 分钟后重试` : `Retry in ${Math.ceil(value / 60)}m`;
}

function formatElapsedMs(ms) {
  const A = _providerAvail();
  if (A) {
    const text = A.formatElapsed(ms);
    return text || '-';
  }
  const value = Number(ms || 0);
  if (!value) return '-';
  if (value < 1000) return `${value} ms`;
  return getLanguage() === 'zh' ? `${(value / 1000).toFixed(1)} 秒` : `${(value / 1000).toFixed(1)} s`;
}

function formatTestedAt(timestamp) {
  const value = Number(timestamp || 0);
  if (!value) return '';
  try {
    return new Date(value * 1000).toLocaleTimeString();
  } catch {
    return '';
  }
}

function inferRuntimeProvider(model) {
  const id = String(model?.id || '').trim();
  const ownedBy = String(model?.owned_by || '').trim();
  if (ownedBy && !['openai', 'anthropic', 'google'].includes(ownedBy)) return ownedBy;
  const prefixMatch = id.match(/^([a-z0-9._-]+)-/i);
  if (prefixMatch) return prefixMatch[1];
  return ownedBy || 'runtime';
}

function candidateModelKeys(row) {
  return [
    row?.call_id,
    row?.upstream_id,
    row?.lookup_upstream_id,
    row?.target_upstream_id,
  ].map(normalizeModelKey).filter(Boolean);
}

function deriveProviderModelCategories(row) {
  const keys = candidateModelKeys(row);
  const categories = new Set();

  for (const [category, values] of Object.entries(PROVIDER_MODEL_CATEGORY_MATCHERS)) {
    if (keys.some((key) => values.has(key))) categories.add(category);
  }

  if (keys.some((key) => key.includes('image') || key.includes('-vl') || key.includes('/vl') || key.includes('vision') || key.includes('riverflow'))) {
    categories.add('image');
  }
  if (keys.some((key) => key.includes('coder') || key.includes('coding') || key.includes('codex'))) {
    categories.add('coding');
    categories.add('agent');
  }
  if (keys.some((key) => key.includes('thinking') || key.includes('reasoning'))) {
    categories.add('reasoning');
  }
  if (keys.some((key) => key.includes('agent') || key.includes('tool') || key.includes('function') || key.endsWith('/free'))) {
    categories.add('agent');
  }
  if (keys.some((key) => key.includes('chat') || key.includes('instruct') || key.includes('llama') || key.includes('trinity-mini'))) {
    categories.add('dialog');
  }

  if (!categories.size) categories.add('dialog');
  return [...categories];
}


function statusKindLabel(kind) {
  if (kind === 'forbidden') return getLanguage() === 'zh' ? '无访问权限' : 'No access';
  if (kind === 'quota') return getLanguage() === 'zh' ? '额度或频率受限' : 'Quota or rate limited';
  if (kind === 'auth') return getLanguage() === 'zh' ? '认证失败' : 'Authentication failed';
  if (kind === 'timeout') return getLanguage() === 'zh' ? '请求超时' : 'Request timed out';
  if (kind === 'server') return getLanguage() === 'zh' ? '服务端错误' : 'Server error';
  if (kind === 'client') return getLanguage() === 'zh' ? '客户端请求错误' : 'Client request error';
  if (kind === 'specialized') return getLanguage() === 'zh' ? '需用专用接口检测' : 'Requires a specialized endpoint';
  return t('common.unavailable', 'Unavailable');
}

function modelStatusLabel(status, meta = {}) {
  if (status === 'ok') return t('common.available', 'Available');
  if (status === 'testing') return t('common.testing', 'Testing');
  if (status === 'bad') return statusKindLabel(meta.failure_kind);
  return t('common.pending', 'Pending');
}

function providerCategoryLabel(category) {
  const value = String(category || '').trim().toLowerCase();
  if (value === 'dialog') return '对话';
  if (value === 'reasoning') return '推理';
  if (value === 'vision') return '视觉';
  if (value === 'image') return '图像';
  if (value === 'audio') return '音频';
  if (value === 'coder') return '编程';
  if (value === 'agent') return '代理';
  if (value === 'embedding') return '向量';
  if (value === 'safety') return '安全';
  if (value === 'specialized') return '专用';
  if (value === 'chat') return '对话';
  return category || '-';
}

function getProviderStatusSummary(rows) {
  const isZh = getLanguage() === 'zh';
  let ok = 0;
  let bad = 0;
  let testing = 0;
  let forbidden = 0;
  let quota = 0;

  rows.forEach((row) => {
    const status = providerModelStatuses[row.call_id];
    const meta = providerModelStatusMeta[row.call_id] || {};
    if (status === 'ok') ok += 1;
    if (status === 'bad') {
      bad += 1;
      if (meta.failure_kind === 'forbidden') forbidden += 1;
      if (meta.failure_kind === 'quota') quota += 1;
    }
    if (status === 'testing') testing += 1;
  });

  if (testing) return isZh ? `检测中 ${testing}` : `Testing ${testing}`;
  const parts = [];
  if (ok) parts.push(isZh ? `可用 ${ok}` : `Available ${ok}`);
  if (forbidden) parts.push(isZh ? `无权限 ${forbidden}` : `No access ${forbidden}`);
  if (quota) parts.push(isZh ? `额度受限 ${quota}` : `Quota limited ${quota}`);
  if (bad && !forbidden && !quota) parts.push(isZh ? `不可用 ${bad}` : `Unavailable ${bad}`);
  if (!parts.length) parts.push(t('common.pending', isZh ? '待检测' : 'Pending'));
  return parts.join(' / ');
}

function providerModelChipHtml(row) {
  const model = String(row?.call_id || '').trim();
  const status = providerModelStatuses[model] || '';
  const meta = providerModelStatusMeta[model] || {};
  const selected = selectedProviderModels.has(model);
  const categories = row.categories || deriveProviderModelCategories(row);
  const categoryLabels = categories.map(providerCategoryLabel);
  const statusLabel = modelStatusLabel(status, meta);
  const reasonLabel = meta.failure_kind ? statusKindLabel(meta.failure_kind) : '';
  const titleLines = [
    `模型：${model}`,
    `状态：${statusLabel}`,
    `分类：${categoryLabels.join(' / ')}`,
  ];
  if (reasonLabel) titleLines.push(`原因：${reasonLabel}`);
  if (meta.elapsed_ms) titleLines.push(`耗时：${formatElapsedMs(meta.elapsed_ms)}`);
  if (meta.tested_at) titleLines.push(`检测时间：${formatTestedAt(meta.tested_at)}`);
  if (meta.message) titleLines.push(`详细信息：${meta.message}`);

  let badge = '';
  if (status === 'bad' && meta.failure_kind === 'forbidden') badge = '<span class="provider-model-retry">无权限</span>';
  else if (status === 'bad' && meta.failure_kind === 'quota') badge = '<span class="provider-model-retry">额度受限</span>';

  return `
    <button
      type="button"
      class="provider-model-call-id ${selected ? 'is-selected' : ''} ${status ? `status-${status}` : ''}"
      data-provider-model-id="${escapeProviderHtml(model)}"
      data-provider-model-categories="${escapeProviderHtml(categories.join(','))}"
      title="${escapeProviderHtml(titleLines.join('\n'))}"
    >
      <span class="provider-model-status-dot ${status ? `status-${status}` : 'status-idle'}"></span>
      <span class="provider-model-chip-text">${escapeProviderHtml(model)}</span>
      ${badge}
    </button>`;
}

function providerModelCardHtml(item) {
  const sourceProvider = String(item.lookup_provider || item.provider || '').trim();
  const provider = escapeProviderHtml(item.provider || sourceProvider || '-');
  const providerKey = escapeProviderHtml(sourceProvider || item.provider || '');
  const rows = normalizeProviderRows(item).map((row) => ({
    ...row,
    categories: deriveProviderModelCategories(row),
  }));
  if (!rows.length) return '';
  const isTesting = rows.some((row) => providerModelsRunningSet.has(String(row.call_id || '').trim()));

  return `
    <article class="provider-model-card">
      <div class="provider-model-head">
        <div class="provider-model-name">${provider}</div>
        <div class="provider-model-actions">
          <span class="provider-model-summary">${escapeProviderHtml(getProviderStatusSummary(rows))}</span>
          <button type="button" class="secondary provider-aggregate-btn" data-provider-key="${providerKey}" data-provider-create-aggregate>创建聚合</button>
          <button type="button" class="secondary provider-test-btn ${isTesting ? 'is-testing' : ''}" data-provider-key="${providerKey}" data-provider-test ${isTesting ? 'disabled' : ''}>${isTesting ? '检测中' : '检测本组'}</button>
        </div>
      </div>
      <div class="provider-model-call-list">
        ${rows.map(providerModelChipHtml).join('')}
      </div>
    </article>`;
}


function providerGroupTabsHtml(items) {
  const counts = new Map();
  items.forEach((item) => {
    const provider = String(item.provider || item.lookup_provider || '未识别').trim() || '未识别';
    const count = normalizeProviderRows(item).length;
    counts.set(provider, (counts.get(provider) || 0) + count);
  });

  const providers = Array.from(counts.keys()).sort((a, b) => a.localeCompare(b));
  const allLabel = getLanguage() === 'zh' ? '全部' : 'All';
  const allTabHtml = `<button
      type="button"
      class="provider-map-tab ${activeProviderGroup === 'all' ? 'is-active' : ''}"
      data-provider-group="all"
    >${escapeProviderHtml(allLabel)}</button>`;

  const otherTabsHtml = providers.map((provider) => {
    return `<button
        type="button"
        class="provider-map-tab ${provider === activeProviderGroup ? 'is-active' : ''}"
        data-provider-group="${escapeProviderHtml(provider)}"
      >${escapeProviderHtml(provider)}</button>`;
  }).join('');

  return allTabHtml + otherTabsHtml;
}

function invalidateProviderModelCache() {
  providerModelItemsCache = [];
  providerModelMappingItemsCache = [];
  _cachedProviderFingerprint = '';
}

async function fetchProviderModelItems() {
  const runtimeData = await api('/api/provider-models?runtime_state=1');
  const runtimeItems = Array.isArray(runtimeData.items) ? runtimeData.items : [];
  if (runtimeItems.length) return runtimeItems;
  const fallbackData = await api('/api/provider-models');
  return Array.isArray(fallbackData.items) ? fallbackData.items : [];
}

async function fetchRuntimeProviderModelItems() {
  const configuredItems = await fetchProviderModelItems();
  const items = configuredItems
    .map((item) => ({
      ...item,
      rows: normalizeProviderRows(item)
        .map((row) => ({ ...row, call_id: String(row.call_id || '').trim() }))
        .filter((row) => row.call_id)
        .filter((row, index, list) => list.findIndex((entry) => entry.call_id === row.call_id) === index),
    }))
    .filter((item) => item.rows.length)
    .sort((a, b) => String(a.provider || a.lookup_provider || '').localeCompare(String(b.provider || b.lookup_provider || '')));

  if (items.length) return items;

  const runtimeData = await api('/api/query-models');
  const models = Array.isArray(runtimeData.body?.data) ? runtimeData.body.data : [];
  const grouped = new Map();

  models.forEach((model) => {
    const modelId = String(model?.id || '').trim();
    const provider = inferRuntimeProvider(model);
    if (!provider || !modelId) return;
    if (!grouped.has(provider)) grouped.set(provider, []);
    const rows = grouped.get(provider);
    if (!rows.find((row) => row.call_id === modelId)) rows.push({ call_id: modelId, upstream_id: modelId });
  });

  return [...grouped.entries()]
    .map(([provider, rows]) => ({ provider, rows }))
    .sort((a, b) => String(a.provider).localeCompare(String(b.provider)));
}

function providerAggregateAliasId(provider) {
  return String(provider || '').trim().replace(/[^a-zA-Z0-9._-]+/g, '-').replace(/^[-._]+|[-._]+$/g, '').slice(0, 64);
}

function providerAggregateMemberRows(item) {
  const rows = normalizeProviderRows(item)
    .map((row) => {
      const provider = String(row.source_provider || item?.lookup_provider || item?.provider || '').trim().toLowerCase();
      const upstreamId = String(row.lookup_upstream_id || row.upstream_id || '').trim();
      const callId = String(row.call_id || '').trim();
      return { provider, upstream_id: upstreamId, call_id: callId };
    })
    .filter((row) => row.provider && row.upstream_id);

  const testedRows = rows.filter((row) => providerModelStatuses[row.call_id]);
  const availableRows = rows.filter((row) => providerModelStatuses[row.call_id] === 'ok');
  return availableRows.length ? availableRows : (testedRows.length ? [] : rows);
}

function findProviderModelItem(providerKey) {
  const key = String(providerKey || '').trim();
  return providerModelItemsCache.find((entry) =>
    String(entry.lookup_provider || entry.provider || '').trim() === key
  );
}

async function createAggregateForProvider(item, button) {
  const provider = String(item?.lookup_provider || item?.provider || '').trim();
  const aliasId = providerAggregateAliasId(provider);
  if (!provider || !aliasId) {
    showMessage(getLanguage() === 'zh' ? '缺少 provider，无法创建聚合 model。' : 'Provider is missing; cannot create an aggregate model.', true);
    return;
  }

  const memberRows = providerAggregateMemberRows(item);
  if (!memberRows.length) {
    showMessage(getLanguage() === 'zh'
      ? '本组没有检测可用的模型，先检测本组后再创建。'
      : 'No available models in this provider. Test this provider first, then create the aggregate model.', true);
    return;
  }

  try {
    if (button) button.disabled = true;
    const existing = await api('/api/aggregate-models');
    const existingIds = new Set((Array.isArray(existing.items) ? existing.items : [])
      .map((entry) => String(entry.alias_id || '').trim())
      .filter(Boolean));
    if (existingIds.has(aliasId)) {
      showMessage(getLanguage() === 'zh' ? `聚合 model 已存在：${aliasId}` : `Aggregate model already exists: ${aliasId}`, true);
      return;
    }

    const members = memberRows.map((row) => ({ provider: row.provider, upstream_id: row.upstream_id }));
    const res = await api('/api/aggregate-models', 'POST', {
      action: 'set_members',
      alias_id: aliasId,
      members,
    });

    if (typeof aggregateItemsCache !== 'undefined') aggregateItemsCache = [];
    if (typeof aggregateModelsLoaded !== 'undefined') aggregateModelsLoaded = false;
    if (typeof loadAggregateModels === 'function') void loadAggregateModels(true);
    showMessage(res.message || (getLanguage() === 'zh'
      ? `已创建聚合 model：${aliasId}（${members.length} 个模型）`
      : `Created aggregate model: ${aliasId} (${members.length} models)`));
  } catch (err) {
    showMessage(err.message, true);
  } finally {
    if (button) button.disabled = false;
  }
}

function bindProviderModelActions(root) {
  root?.querySelectorAll('[data-provider-model-id]').forEach((btn) => {
    btn.onclick = () => {
      const modelId = btn.getAttribute('data-provider-model-id') || '';
      if (!modelId) return;
      if (selectedProviderModels.has(modelId)) selectedProviderModels.delete(modelId);
      else selectedProviderModels.add(modelId);
      btn.classList.toggle('is-selected', selectedProviderModels.has(modelId));
      updateProviderDetectionButtons();
    };
    btn.ondblclick = (e) => {
      e.preventDefault();
      const modelId = btn.getAttribute('data-provider-model-id') || '';
      if (!modelId) return;
      navigator.clipboard.writeText(modelId).then(() => {
        showMessage(getLanguage() === 'zh' ? `已复制：${modelId}` : `Copied: ${modelId}`);
      }).catch(() => {
        showMessage(getLanguage() === 'zh' ? '复制失败' : 'Copy failed', true);
      });
    };
  });

  root?.querySelectorAll('[data-provider-test]').forEach((btn) => {
    btn.onclick = async () => {
      const item = findProviderModelItem(btn.getAttribute('data-provider-key') || '');
      const modelIds = normalizeProviderRows(item).map((row) => row.call_id).filter(Boolean);
      await runProviderModelDetection(modelIds);
    };
  });

  root?.querySelectorAll('[data-provider-create-aggregate]').forEach((btn) => {
    btn.onclick = async () => {
      const item = findProviderModelItem(btn.getAttribute('data-provider-key') || '');
      await createAggregateForProvider(item, btn);
    };
  });
}

function bindProviderGroupActions(root) {
  root?.querySelectorAll('[data-provider-group]').forEach((btn) => {
    btn.onclick = () => {
      activeProviderGroup = btn.getAttribute('data-provider-group') || '';
      loadProviderModels(false);
    };
  });
}

async function syncProviderModelTestState() {
  try {
    const A = _providerAvail();
    if (A) {
      const state = await A.fetchAvailabilityState();
      providerModelsRunningSet = new Set([...(state.runningSet || []), ...(state.queueSet || [])]);
      providerModelStatuses = { ...(state.statuses || {}) };
      providerModelStatusMeta = { ...(state.meta || {}) };
      return;
    }
    const data = await api('/api/provider-model-test-state');
    const results = data.results || {};
    providerModelsRunningSet = new Set(Array.isArray(data.running) ? data.running : []);
    providerModelStatuses = {};
    providerModelStatusMeta = {};

    Object.entries(results).forEach(([modelId, item]) => {
      if (providerModelsRunningSet.has(modelId) || item?.status === 'testing') {
        providerModelStatuses[modelId] = 'testing';
      } else if (item?.available) {
        providerModelStatuses[modelId] = 'ok';
      } else if (item) {
        providerModelStatuses[modelId] = 'bad';
      }

      providerModelStatusMeta[modelId] = {
        elapsed_ms: item?.elapsed_ms,
        retry_after_seconds: item?.retry_after_seconds,
        tested_at: item?.tested_at,
        status_code: item?.status_code,
        working_path: item?.working_path,
        failure_kind: item?.failure_kind,
        message: item?.message,
      };
    });
  } catch {
    providerModelsRunningSet = new Set();
  }
}

function updateProviderDetectionButtons() {
  const deleteBtn = document.getElementById('provider-delete-selected-btn');
  const selectedBtn = document.getElementById('provider-test-selected-btn');
  const stopBtn = document.getElementById('provider-stop-test-btn');
  const allBtn = document.getElementById('provider-test-all-btn');
  const selectedIds = [...selectedProviderModels];
  const hasSelected = selectedIds.length > 0;
  const anySelectedRunning = hasSelected && selectedIds.some((id) => providerModelsRunningSet.has(id));
  const anyRunning = providerModelsRunningSet.size > 0;

  if (deleteBtn) {
    deleteBtn.disabled = !hasSelected || anySelectedRunning;
  }
  if (selectedBtn) {
    selectedBtn.disabled = !hasSelected || anySelectedRunning;
    selectedBtn.classList.toggle('is-testing', anySelectedRunning);
    selectedBtn.textContent = anySelectedRunning ? '检测中' : '检测选中';
  }
  if (allBtn) {
    allBtn.disabled = anyRunning;
    allBtn.classList.toggle('is-testing', anyRunning);
    allBtn.textContent = anyRunning ? '检测中' : '检测全部';
  }
  if (stopBtn) {
    stopBtn.disabled = !anyRunning;
    stopBtn.classList.toggle('is-testing', anyRunning);
  }

  // Also update per-provider "Test Group" buttons
  document.querySelectorAll('.provider-test-btn').forEach(btn => {
    const provider = btn.dataset.providerTest;
    const item = providerModelItemsCache.find(entry => String(entry.provider || '') === provider);
    if (!item) return;
    const modelIds = normalizeProviderRows(item).map(row => row.call_id).filter(Boolean);
    const isTesting = modelIds.some(id => providerModelsRunningSet.has(id));
    
    btn.disabled = isTesting;
    btn.classList.toggle('is-testing', isTesting);
    btn.textContent = isTesting ? '检测中' : '检测本组';
  });
}

function updateModelChipStatuses() {
  document.querySelectorAll('[data-provider-model-id]').forEach(btn => {
    const modelId = btn.dataset.providerModelId;
    const status = providerModelStatuses[modelId] || '';
    const meta = providerModelStatusMeta[modelId] || {};
    
    // Update classes
    btn.className = `provider-model-call-id ${selectedProviderModels.has(modelId) ? 'is-selected' : ''} ${status ? `status-${status}` : ''}`;
    
    // Update dot
    const dot = btn.querySelector('.provider-model-status-dot');
    if (dot) {
      dot.className = `provider-model-status-dot ${status ? `status-${status}` : 'status-idle'}`;
    }
    
    // Update badge (if any)
    let badge = btn.querySelector('.provider-model-retry');
    if (status === 'bad' && (meta.failure_kind === 'forbidden' || meta.failure_kind === 'quota')) {
      if (!badge) {
        badge = document.createElement('span');
        badge.className = 'provider-model-retry';
        btn.appendChild(badge);
      }
      badge.textContent = meta.failure_kind === 'forbidden' ? '无权限' : '额度受限';
    } else if (badge) {
      badge.remove();
    }
    
    // Update title
    const categories = btn.dataset.providerModelCategories ? btn.dataset.providerModelCategories.split(',') : [];
    const categoryLabels = categories.map(providerCategoryLabel);
    const statusLabel = modelStatusLabel(status, meta);
    const reasonLabel = meta.failure_kind ? statusKindLabel(meta.failure_kind) : '';
    const titleLines = [
      `模型：${modelId}`,
      `状态：${statusLabel}`,
      `分类：${categoryLabels.join(' / ')}`,
    ];
    if (reasonLabel) titleLines.push(`原因：${reasonLabel}`);
    if (meta.elapsed_ms) titleLines.push(`耗时：${formatElapsedMs(meta.elapsed_ms)}`);
    if (meta.tested_at) titleLines.push(`检测时间：${formatTestedAt(meta.tested_at)}`);
    if (meta.message) titleLines.push(`详细信息：${meta.message}`);
    btn.title = titleLines.join('\n');
  });

  // Update provider-level summaries
  document.querySelectorAll('.provider-model-card').forEach(card => {
    const providerName = card.querySelector('.provider-model-name')?.textContent;
    const item = providerModelItemsCache.find(entry => String(entry.provider || '') === providerName);
    if (!item) return;
    const rows = normalizeProviderRows(item).map((row) => ({ ...row, categories: deriveProviderModelCategories(row) }));
    const summaryEl = card.querySelector('.provider-model-summary');
    if (summaryEl) {
      summaryEl.textContent = getProviderStatusSummary(rows);
    }
  });
}

async function loadProviderModels(includeAvailability = false) {
  const root = document.getElementById('provider-model-list');
  const groupRoot = document.getElementById('provider-model-groups');
  if (!root) return;

  try {
    if (!providerRouteStrategyLoaded) {
      await loadRouteStrategySettings();
      providerRouteStrategyLoaded = true;
    }

    let items = providerModelItemsCache;
    const needFullReload = !items.length;

    if (needFullReload) {
      try {
        items = await fetchRuntimeProviderModelItems();
      } catch {
        items = await fetchProviderModelItems();
      }
      providerModelItemsCache = items;
    }

    if (includeAvailability) {
      await syncProviderModelTestState();
    }

    // Ensure activeProviderGroup is valid
    const providerKeys = items.map((item) => String(item.provider || item.lookup_provider || '未识别').trim() || '未识别');
    if (activeProviderGroup !== 'all' && (!activeProviderGroup || !providerKeys.includes(activeProviderGroup))) {
      activeProviderGroup = 'all'; // Default to show all
    }

    const currentFingerprint = `${activeProviderGroup}:${items.length}:${items.map(i => i.provider || i.lookup_provider || '').join(',')}`;

    if (currentFingerprint === _cachedProviderFingerprint && root.innerHTML.trim() !== '') {
      updateModelChipStatuses();
      updateProviderDetectionButtons();
      return;
    }
    _cachedProviderFingerprint = currentFingerprint;

    const visibleIds = new Set(
      items
        .filter((item) => activeProviderGroup === 'all' || String(item.provider || item.lookup_provider || '未识别').trim() === activeProviderGroup)
        .flatMap((item) => normalizeProviderRows(item).map((row) => String(row.call_id || '').trim()).filter(Boolean))
    );
    selectedProviderModels = new Set([...selectedProviderModels].filter((id) => visibleIds.has(id)));

    if (groupRoot) {
      groupRoot.innerHTML = providerGroupTabsHtml(items);
      bindProviderGroupActions(groupRoot);
    }

    let html = '';
    if (activeProviderGroup === 'all') {
      html = items.map((item) => providerModelCardHtml(item)).join('');
    } else {
      const activeItem = items.find((item) => String(item.provider || item.lookup_provider || '未识别').trim() === activeProviderGroup);
      html = activeItem ? providerModelCardHtml(activeItem) : '';
    }
    root.innerHTML = html
      ? html
      : `<div class="auth-empty">${getLanguage() === 'zh' ? '请从左侧选择一个 Provider。' : 'Select a provider from the left.'}</div>`;

    bindProviderModelActions(root);
    updateProviderDetectionButtons();
  } catch (err) {
    showMessage(err.message, true);
  }
}

async function runProviderModelDetection(modelIds) {
  const A = _providerAvail();
  const ids = A
    ? A.normalizeModelIds(modelIds)
    : [...new Set((modelIds || []).map((value) => String(value || '').trim()).filter(Boolean))];
  if (!ids.length) {
    showMessage(getLanguage() === 'zh' ? '请先选择至少一个模型。' : 'Please select at least one model first.', true);
    return;
  }

  try {
    ids.forEach((id) => {
      providerModelsRunningSet.delete(id);
      delete providerModelStatuses[id];
      delete providerModelStatusMeta[id];
    });

    if (A) {
      const queued = await A.queueModelTests(ids, { clearFirst: true });
      if (queued.mode === 'sync' && Array.isArray(queued.items)) {
        queued.items.forEach((item) => {
          providerModelsRunningSet.delete(item.model);
          providerModelStatuses[item.model] = item.available ? 'ok' : 'bad';
          providerModelStatusMeta[item.model] = {
            elapsed_ms: item.elapsed_ms,
            retry_after_seconds: item.retry_after_seconds,
            tested_at: item.tested_at,
            status_code: item.status_code,
            working_path: item.working_path,
            failure_kind: item.failure_kind,
            message: item.message,
          };
        });
        await loadProviderModels(true);
        showMessage(getLanguage() === 'zh'
          ? `检测完成：${queued.items.filter((item) => item.available).length}/${queued.items.length} 可用`
          : `Test completed: ${queued.items.filter((item) => item.available).length}/${queued.items.length} available.`);
        return;
      }
    } else {
      try {
        await api('/api/provider-model-tests', 'POST', { action: 'clear', model_ids: ids });
      } catch {
        // Ignore reset failures and still try to start a fresh detection pass.
      }
      try {
        await api('/api/provider-model-tests', 'POST', { model_ids: ids });
      } catch {
        const fallback = await api('/api/test-provider-models', 'POST', { model_ids: ids });
        const items = Array.isArray(fallback.items) ? fallback.items : [];
        items.forEach((item) => {
          providerModelsRunningSet.delete(item.model);
          providerModelStatuses[item.model] = item.available ? 'ok' : 'bad';
          providerModelStatusMeta[item.model] = {
            elapsed_ms: item.elapsed_ms,
            retry_after_seconds: item.retry_after_seconds,
            tested_at: item.tested_at,
            status_code: item.status_code,
            working_path: item.working_path,
            failure_kind: item.failure_kind,
            message: item.message,
          };
        });
        await loadProviderModels(true);
        showMessage(getLanguage() === 'zh'
          ? `检测完成：${items.filter((item) => item.available).length}/${items.length} 可用`
          : `Test completed: ${items.filter((item) => item.available).length}/${items.length} available.`);
        return;
      }
    }

    ids.forEach((id) => {
      providerModelsRunningSet.add(id);
      providerModelStatuses[id] = 'testing';
      providerModelStatusMeta[id] = { tested_at: Math.floor(Date.now() / 1000) };
    });

    await loadProviderModels(true);
    showMessage(getLanguage() === 'zh'
      ? `已加入后台检测队列：${ids.length} 个模型，刷新页面后会继续检测。`
      : `Queued ${ids.length} models for background testing. Detection will continue after refresh.`);
  } catch (err) {
    showMessage(err.message, true);
  }
}

async function clearProviderModelTestResults() {
  try {
    const A = _providerAvail();
    if (A) await A.clearModelTests();
    else await api('/api/provider-model-tests', 'POST', { action: 'clear' });
    providerModelsRunningSet = new Set();
    providerModelStatuses = {};
    providerModelStatusMeta = {};
    await loadProviderModels(true);
    showMessage(getLanguage() === 'zh' ? '已清除检测结果显示。' : 'Cleared test results display.');
  } catch (err) {
    showMessage(err.message, true);
  }
}

async function stopProviderModelTests() {
  try {
    const A = _providerAvail();
    if (A) await A.stopModelTests();
    else await api('/api/provider-model-tests', 'POST', { action: 'stop' });
    providerModelsRunningSet = new Set();
    providerModelStatuses = {};
    providerModelStatusMeta = {};
    await loadProviderModels(true);
    showMessage(getLanguage() === 'zh' ? '已停止检测任务。' : 'Stopped provider model tests.');
  } catch (err) {
    showMessage(err.message, true);
  }
}

function clearProviderModelSelection() {
  selectedProviderModels.clear();
  loadProviderModels(false);
}

async function deleteSelectedProviderModels() {
  const selectedIds = [...selectedProviderModels]
    .map((value) => String(value || '').trim())
    .filter(Boolean);
  if (!selectedIds.length) {
    showMessage(getLanguage() === 'zh' ? '请先选择要删除的模型。' : 'Please select the models to delete first.', true);
    return;
  }

  const rowsToDelete = [];
  const seen = new Set();
  providerModelItemsCache.forEach((item) => {
    normalizeProviderRows(item).forEach((row) => {
      const callId = String(row.call_id || '').trim();
      const provider = String(row.source_provider || item.lookup_provider || item.provider || '').trim().toLowerCase();
      const upstreamId = String(row.lookup_upstream_id || row.upstream_id || '').trim();
      if (!selectedIds.includes(callId) || !provider || !upstreamId) return;
      const key = `${provider}::${upstreamId}::${callId}`;
      if (seen.has(key)) return;
      seen.add(key);
      rowsToDelete.push({ provider, upstream_id: upstreamId, call_id: callId });
    });
  });

  if (!rowsToDelete.length) {
    showMessage(getLanguage() === 'zh' ? '没有找到可删除的原始模型映射。' : 'No removable original model mappings were found.', true);
    return;
  }

  try {
    await Promise.all(rowsToDelete.map((row) => api('/api/provider-model-delete', 'POST', {
      provider: row.provider,
      upstream_id: row.upstream_id,
      call_id: row.call_id,
    })));
    rowsToDelete.forEach((row) => selectedProviderModels.delete(row.call_id));
    invalidateProviderModelCache();
    await Promise.all([loadProviderModels(false), loadProviderModelMappings()]);
    showMessage(getLanguage() === 'zh' ? `已删除 ${rowsToDelete.length} 个选中模型。` : `Deleted ${rowsToDelete.length} selected models.`);
  } catch (err) {
    showMessage(err.message, true);
  }
}

async function testSelectedProviderModels() {
  await runProviderModelDetection([...selectedProviderModels]);
}

async function testAllProviderModels() {
  const allIds = providerModelItemsCache.flatMap((item) =>
    normalizeProviderRows(item).map((row) => row.call_id).filter(Boolean)
  );
  await runProviderModelDetection(allIds);
}

function ensureProviderModelStatePoller() {
  if (providerModelStatePollTimer) return;
  providerModelStatePollTimer = setInterval(async () => {
    if (typeof getActiveSection === 'function' && getActiveSection() !== 'providers' && !providerModelsRunningSet.size) return;
    await loadProviderModels(true);
  }, 2500);
}

function providerModelMapCardHtml(item) {
  const sourceProviderKey = item.lookup_provider || item.provider || '';
  const lookupProvider = escapeProviderHtml(sourceProviderKey);
  const rows = normalizeProviderRows(item);
  const targetProvider = escapeProviderHtml((rows[0] && rows[0].target_provider) || item.provider || sourceProviderKey || '');

  return `
    <article class="provider-map-card">
      <div class="provider-map-head">
        <div class="provider-model-name">${targetProvider || lookupProvider || '-'}</div>
        <div class="provider-map-head-actions">
          <div class="provider-map-provider-edit">
            <span class="provider-map-label">Provider ID</span>
            <input class="provider-map-input" type="text" value="${targetProvider}" data-current-target-provider="${targetProvider}" data-provider-map-group-provider="${lookupProvider}" />
          </div>
          <button type="button" class="secondary provider-map-add-btn" onclick="showAddMappingModal('${lookupProvider}', '${targetProvider}')" title="新增模型映射">+</button>
        </div>
      </div>
      <div class="provider-map-list">
        ${rows.map((row, index) => {
          const callId = escapeProviderHtml(row.call_id || '');
          const lookupUpstreamId = escapeProviderHtml(row.lookup_upstream_id || row.upstream_id || '-');
          return `
            <div class="provider-map-row">
              <div class="provider-map-col provider-map-edit">
                <span class="provider-map-label">原始 Model ID</span>
                <input class="provider-map-input" type="text" value="${lookupUpstreamId}" data-provider-map-upstream="${lookupProvider}" data-provider-map-row-index="${index}" data-lookup-upstream-id="${lookupUpstreamId}" />
              </div>
                <div class="provider-map-col provider-map-edit">
                  <span class="provider-map-label">本机调用 Model ID</span>
                  <div class="provider-map-actions provider-map-actions-inline">
                    <input class="provider-map-input" type="text" value="${callId}" data-provider-map-input="${lookupProvider}" data-provider-map-row-index="${index}" data-upstream-id="${lookupUpstreamId}" />
                    <div class="provider-map-btns">
                      <button type="button" class="provider-map-save" data-provider-map-save="${lookupProvider}" data-provider-map-row-index="${index}" data-upstream-id="${lookupUpstreamId}" data-original-call-id="${callId}">保存</button>
                      <button type="button" class="provider-map-delete danger" data-provider-map-delete="${lookupProvider}" data-upstream-id="${lookupUpstreamId}" data-call-id="${callId}">删除</button>
                    </div>
                  </div>
                </div>
              </div>`;
        }).join('')}
      </div>
    </article>`;
}

function bindProviderModelMapActions(root) {
  root?.querySelectorAll('[data-provider-map-add]').forEach((btn) => {
    btn.onclick = async () => {
      const provider = btn.getAttribute('data-provider-map-add') || '';
      const providerInput = root.querySelector(`[data-provider-map-group-provider="${escapeSelectorValue(provider)}"]`);
      const upstreamInput = root.querySelector(`[data-provider-map-new-upstream="${escapeSelectorValue(provider)}"]`);
      const callInput = root.querySelector(`[data-provider-map-new-call-id="${escapeSelectorValue(provider)}"]`);
      const targetProvider = providerInput?.value?.trim() || '';
      const targetUpstreamId = upstreamInput?.value?.trim() || '';
      const callId = callInput?.value?.trim() || '';

      if (!targetProvider || !targetUpstreamId || !callId) {
        showMessage('Provider ID、原始 Model ID、本机调用 Model ID 都不能为空。', true);
        return;
      }

      try {
        btn.disabled = true;
        const res = await api('/api/provider-model-override', 'POST', {
          provider,
          target_provider: targetProvider,
          upstream_id: targetUpstreamId,
          target_upstream_id: targetUpstreamId,
          call_id: callId,
        });
        const replacedCount = Number(res?.item?.removed_conflicts_count || 0);
        const replaceText = replacedCount ? `（已替换 ${replacedCount} 个同名映射）` : '';
        showMessage(`已新增映射：${provider} / ${targetUpstreamId}${replaceText}`);
        invalidateProviderModelCache();
        await Promise.all([loadProviderModelMappings(), loadProviderModels(false)]);
      } catch (err) {
        showMessage(err.message, true);
      } finally {
        btn.disabled = false;
      }
    };
  });

  root?.querySelectorAll('[data-provider-map-save]').forEach((btn) => {
    btn.onclick = async () => {
      const provider = btn.getAttribute('data-provider-map-save') || '';
      const upstreamId = btn.getAttribute('data-upstream-id') || '';
      const originalCallId = btn.getAttribute('data-original-call-id') || '';
      const rowIndex = btn.getAttribute('data-provider-map-row-index') || '';
      const providerInput = root.querySelector(`[data-provider-map-group-provider="${escapeSelectorValue(provider)}"]`);
      const upstreamInput = root.querySelector(`[data-provider-map-upstream="${escapeSelectorValue(provider)}"][data-provider-map-row-index="${escapeSelectorValue(rowIndex)}"]`);
      const input = root.querySelector(`[data-provider-map-input="${escapeSelectorValue(provider)}"][data-provider-map-row-index="${escapeSelectorValue(rowIndex)}"]`);
      const targetProvider = providerInput?.value?.trim() || '';
      const previousTargetProvider = providerInput?.getAttribute('data-current-target-provider')?.trim() || provider;
      const targetUpstreamId = upstreamInput?.value?.trim() || '';
      const callId = input?.value?.trim() || '';

      if (!targetProvider || !targetUpstreamId || !callId) {
        showMessage('Provider ID、原始 Model ID、本机调用 Model ID 都不能为空。', true);
        return;
      }

      try {
        btn.disabled = true;
        let replacedCount = 0;
        if (targetProvider !== previousTargetProvider) {
          const rowButtons = Array.from(root.querySelectorAll(`[data-provider-map-save="${escapeSelectorValue(provider)}"]`));
          for (const rowButton of rowButtons) {
            const nextRowIndex = rowButton.getAttribute('data-provider-map-row-index') || '';
            const oldUpstreamId = rowButton.getAttribute('data-upstream-id') || '';
            const oldCallId = rowButton.getAttribute('data-original-call-id') || '';
            const nextUpstreamInput = root.querySelector(`[data-provider-map-upstream="${escapeSelectorValue(provider)}"][data-provider-map-row-index="${escapeSelectorValue(nextRowIndex)}"]`);
            const nextCallInput = root.querySelector(`[data-provider-map-input="${escapeSelectorValue(provider)}"][data-provider-map-row-index="${escapeSelectorValue(nextRowIndex)}"]`);
            const nextUpstreamId = nextUpstreamInput?.value?.trim() || '';
            const nextCallId = nextCallInput?.value?.trim() || '';
            if (!nextUpstreamId || !nextCallId) continue;
            const res = await api('/api/provider-model-override', 'POST', {
              provider,
              target_provider: targetProvider,
              upstream_id: nextUpstreamId,
              target_upstream_id: nextUpstreamId,
              call_id: nextCallId,
            });
            replacedCount += Number(res?.item?.removed_conflicts_count || 0);
            if (oldCallId && (nextUpstreamId !== oldUpstreamId || nextCallId !== oldCallId)) {
              await api('/api/provider-model-delete', 'POST', {
                provider,
                upstream_id: oldUpstreamId,
                call_id: oldCallId,
              });
            }
          }
        } else {
          if (targetUpstreamId !== upstreamId || (originalCallId && callId !== originalCallId)) {
            const res = await api('/api/provider-model-override', 'POST', {
              provider,
              target_provider: targetProvider,
              upstream_id: targetUpstreamId,
              target_upstream_id: targetUpstreamId,
              call_id: callId,
            });
            replacedCount += Number(res?.item?.removed_conflicts_count || 0);
            if (originalCallId) {
              await api('/api/provider-model-delete', 'POST', {
                provider,
                upstream_id: upstreamId,
                call_id: originalCallId,
              });
            }
          } else {
            const res = await api('/api/provider-model-override', 'POST', {
              provider,
              target_provider: targetProvider,
              upstream_id: upstreamId,
              target_upstream_id: targetUpstreamId,
              call_id: callId,
            });
            replacedCount += Number(res?.item?.removed_conflicts_count || 0);
          }
        }
        const replaceText = replacedCount ? `（已替换 ${replacedCount} 个同名映射）` : '';
        showMessage(`已保存映射：${provider} / ${targetUpstreamId}${replaceText}`);
        invalidateProviderModelCache();
        await Promise.all([loadProviderModelMappings(), loadProviderModels(false)]);
      } catch (err) {
        showMessage(err.message, true);
      } finally {
        btn.disabled = false;
      }
    };
  });

  root?.querySelectorAll('[data-provider-map-delete]').forEach((btn) => {
    btn.onclick = async () => {
      const provider = btn.getAttribute('data-provider-map-delete') || '';
      const upstreamId = btn.getAttribute('data-upstream-id') || '';
      const callId = btn.getAttribute('data-call-id') || '';
      if (!provider || !upstreamId) {
        showMessage('缺少 provider 或原始 Model ID。', true);
        return;
      }

      try {
        btn.disabled = true;
        await api('/api/provider-model-delete', 'POST', {
          provider,
          upstream_id: upstreamId,
          call_id: callId,
        });
        showMessage(`已永久删除映射模型：${provider} / ${upstreamId} -> ${callId}`);
        invalidateProviderModelCache();
        await Promise.all([loadProviderModelMappings(), loadProviderModels(false)]);
      } catch (err) {
        showMessage(err.message, true);
      } finally {
        btn.disabled = false;
      }
    };
  });
}

async function loadProviderModelMappings() {
  const tabsRoot = document.getElementById('provider-model-map-tabs');
  const root = document.getElementById('provider-model-map-list');
  if (!root || !tabsRoot) return;

  try {
    if (!providerModelMappingItemsCache.length) {
      providerModelMappingItemsCache = await fetchProviderModelItems();
    }

    const items = providerModelMappingItemsCache;
    if (!items.length) {
      tabsRoot.innerHTML = '';
      root.innerHTML = `<div class="auth-empty">${getLanguage() === 'zh' ? '暂无已配置的 Provider。' : 'No configured providers.'}</div>`;
      return;
    }

    const providerTabs = items
      .map((item) => {
        const key = String(item.lookup_provider || item.provider || '').trim();
        const rows = normalizeProviderRows(item);
        const label = String((rows[0] && rows[0].target_provider) || item.provider || key).trim();
        return key ? { key, label: label || key } : null;
      })
      .filter(Boolean);
    const providerKeys = providerTabs.map((item) => item.key);
    if (!providerKeys.includes(activeProviderMapping)) activeProviderMapping = providerKeys[0] || '';

    tabsRoot.innerHTML = providerTabs.map((provider) => `
      <button type="button" class="provider-map-tab ${provider.key === activeProviderMapping ? 'is-active' : ''}" data-provider-map-tab="${escapeProviderHtml(provider.key)}">${escapeProviderHtml(provider.label)}</button>
    `).join('');

    tabsRoot.querySelectorAll('[data-provider-map-tab]').forEach((btn) => {
      btn.onclick = () => {
        activeProviderMapping = btn.getAttribute('data-provider-map-tab') || '';
        loadProviderModelMappings();
      };
    });

    const currentItem = items.find((item) => String(item.lookup_provider || item.provider || '').trim() === activeProviderMapping) || items[0];
    root.innerHTML = currentItem
      ? providerModelMapCardHtml(currentItem)
      : `<div class="auth-empty">${getLanguage() === 'zh' ? '暂无已配置的 Provider。' : 'No configured providers.'}</div>`;
    bindProviderModelMapActions(root);
  } catch (err) {
    showMessage(err.message, true);
  }
}

function routeStrategyInput(id) {
  return document.getElementById(id);
}

function fillRouteStrategyInputs(item = {}) {
  const enabled = routeStrategyInput('strategy-enabled');
  const aggregateOnly = routeStrategyInput('strategy-aggregate-only');
  const probeParallelism = routeStrategyInput('strategy-probe-parallelism');
  const cooldownDefault = routeStrategyInput('strategy-cooldown-default');
  const cooldownForbidden = routeStrategyInput('strategy-cooldown-forbidden');
  const cooldownQuota = routeStrategyInput('strategy-cooldown-quota');
  const cooldownAuth = routeStrategyInput('strategy-cooldown-auth');
  const cooldownTimeout = routeStrategyInput('strategy-cooldown-timeout');
  const cooldownServer = routeStrategyInput('strategy-cooldown-server');
  const cooldownClient = routeStrategyInput('strategy-cooldown-client');

  if (enabled) enabled.checked = Boolean(item.enabled);
  if (aggregateOnly) aggregateOnly.checked = Boolean(item.aggregate_only);
  if (probeParallelism) probeParallelism.value = Number(item.probe_parallelism || 100);
  if (cooldownDefault) cooldownDefault.value = Number(item.cooldown_default_seconds || 300);
  if (cooldownForbidden) cooldownForbidden.value = Number(item.cooldown_forbidden_seconds || 1800);
  if (cooldownQuota) cooldownQuota.value = Number(item.cooldown_quota_seconds || 900);
  if (cooldownAuth) cooldownAuth.value = Number(item.cooldown_auth_seconds || 900);
  if (cooldownTimeout) cooldownTimeout.value = Number(item.cooldown_timeout_seconds || 240);
  if (cooldownServer) cooldownServer.value = Number(item.cooldown_server_seconds || 240);
  if (cooldownClient) cooldownClient.value = Number(item.cooldown_client_seconds || 300);
}

function collectRouteStrategyInputs() {
  const toInt = (id, fallback) => {
    const value = Number(routeStrategyInput(id)?.value ?? fallback);
    if (!Number.isFinite(value)) return fallback;
    return Math.max(0, Math.min(86400, Math.floor(value)));
  };

  return {
    enabled: Boolean(routeStrategyInput('strategy-enabled')?.checked),
    aggregate_only: Boolean(routeStrategyInput('strategy-aggregate-only')?.checked),
    probe_parallelism: Math.max(1, Math.min(100, toInt('strategy-probe-parallelism', 100))),
    cooldown_default_seconds: toInt('strategy-cooldown-default', 300),
    cooldown_forbidden_seconds: toInt('strategy-cooldown-forbidden', 1800),
    cooldown_quota_seconds: toInt('strategy-cooldown-quota', 900),
    cooldown_auth_seconds: toInt('strategy-cooldown-auth', 900),
    cooldown_timeout_seconds: toInt('strategy-cooldown-timeout', 240),
    cooldown_server_seconds: toInt('strategy-cooldown-server', 240),
    cooldown_client_seconds: toInt('strategy-cooldown-client', 300),
  };
}

async function loadRouteStrategySettings() {
  const panel = document.getElementById('provider-route-strategy-panel');
  if (!panel) return;

  try {
    const data = await api('/api/route-strategy', 'GET');
    fillRouteStrategyInputs(data.item || {});
  } catch (err) {
    showMessage(err.message, true);
  }
}

async function saveRouteStrategySettings() {
  const panel = document.getElementById('provider-route-strategy-panel');
  if (!panel) return;

  try {
    const payload = collectRouteStrategyInputs();
    await api('/api/route-strategy', 'POST', { item: payload });
    showMessage('路由策略已保存。');
  } catch (err) {
    showMessage(err.message, true);
  }
}

ensureProviderModelStatePoller();

function showAddMappingModal(provider, targetProvider) {
  const modal = document.getElementById('add-model-mapping-modal');
  if (!modal) return;
  
  modal.style.display = 'flex';
  const inner = modal.querySelector('.modal');
  if (inner) {
    inner.offsetHeight;
    inner.style.transform = 'scale(1)';
    inner.style.opacity = '1';
  }
  
  const providerInput = document.getElementById('mapping-modal-provider');
  const upstreamInput = document.getElementById('mapping-modal-upstream');
  const callInput = document.getElementById('mapping-modal-call');
  
  if (providerInput) providerInput.value = targetProvider || provider;
  if (upstreamInput) {
    upstreamInput.value = '';
    setTimeout(() => upstreamInput.focus(), 80);
  }
  if (callInput) callInput.value = '';
}

function hideAddMappingModal() {
  const modal = document.getElementById('add-model-mapping-modal');
  if (!modal) return;
  
  const inner = modal.querySelector('.modal');
  if (inner) {
    inner.style.transform = 'scale(0.96)';
    inner.style.opacity = '0';
  }
  setTimeout(() => {
    modal.style.display = 'none';
  }, 150);
}

async function handleAddMappingSubmit() {
  const providerInput = document.getElementById('mapping-modal-provider');
  const upstreamInput = document.getElementById('mapping-modal-upstream');
  const callInput = document.getElementById('mapping-modal-call');
  
  const targetProvider = providerInput?.value?.trim() || '';
  const targetUpstreamId = upstreamInput?.value?.trim() || '';
  const callId = callInput?.value?.trim() || '';
  const provider = activeProviderMapping || targetProvider;

  if (!targetProvider || !targetUpstreamId || !callId) {
    showMessage('Provider ID、原始 Model ID、本机调用 Model ID 都不能为空。', true);
    return;
  }

  try {
    const res = await api('/api/provider-model-override', 'POST', {
      provider,
      target_provider: targetProvider,
      upstream_id: targetUpstreamId,
      target_upstream_id: targetUpstreamId,
      call_id: callId,
    });
    const replacedCount = Number(res?.item?.removed_conflicts_count || 0);
    const replaceText = replacedCount ? `（已替换 ${replacedCount} 个同名映射）` : '';
    showMessage(`已新增映射：${provider} / ${targetUpstreamId}${replaceText}`);
    
    providerModelMappingItemsCache = [];
    await loadProviderModelMappings();
    hideAddMappingModal();
  } catch (err) {
    showMessage(err.message, true);
  }
}

document.addEventListener('keydown', (e) => {
  const modal = document.getElementById('add-model-mapping-modal');
  if (modal && modal.style.display === 'flex' && e.key === 'Enter') {
    void handleAddMappingSubmit();
  }
});

window.showAddMappingModal = showAddMappingModal;
window.hideAddMappingModal = hideAddMappingModal;
window.handleAddMappingSubmit = handleAddMappingSubmit;
