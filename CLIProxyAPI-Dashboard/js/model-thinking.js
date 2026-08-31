let modelThinkingCandidates = [];
let modelThinkingConfigs = {};
let savedModelThinkingConfigs = {};
let modelThinkingSearch = '';
let activeThinkingProvider = 'all';
let selectedThinkingModels = new Set();
let thinkingAdvancedOpen = new Set();
let modelThinkingLoading = false;
let modelThinkingSaving = false;
let modelThinkingAllModels = [];

const MODEL_THINKING_MODES = [
  { id: 'default', label: '使用默认 (透传客户端)' },
  { id: 'force_on', label: '强制启用 (开启思考)' },
  { id: 'force_off', label: '强制禁用 (关闭思考)' },
];

const REASONING_EFFORT_OPTIONS = [
  { id: '', label: '不指定 (跟随请求)' },
  { id: 'minimal', label: 'minimal (极简)' },
  { id: 'low', label: 'low (低)' },
  { id: 'medium', label: 'medium (中)' },
  { id: 'high', label: 'high (高)' },
  { id: 'xhigh', label: 'xhigh (超高)' },
  { id: 'max', label: 'max (最大)' },
];

const THINKING_LEVEL_PRESETS = [
  { id: 'extended_5', label: '扩展 5 级 [low~max] ★', shortLabel: '5级扩展', levels: ['low', 'medium', 'high', 'xhigh', 'max'] },
  { id: 'full_6', label: '全量 6 级 [minimal~max]', shortLabel: '6级全量', levels: ['minimal', 'low', 'medium', 'high', 'xhigh', 'max'] },
  { id: 'standard_3', label: '标准 3 级 [low~high]', shortLabel: '3级标准', levels: ['low', 'medium', 'high'] },
  { id: 'none', label: '核心默认 (未声明扩展)', shortLabel: '核心默认', levels: [] },
  { id: 'custom', label: '自定义等级...', shortLabel: '自定义', levels: [] },
];

const POPULAR_REASONING_MODELS = [
  { id: 'gpt-5.6-sol', provider: 'ung', preset: 'extended_5' },
  { id: 'gpt-5.6-terra', provider: 'ung', preset: 'extended_5' },
  { id: 'gpt-5.6-luna', provider: 'ung', preset: 'extended_5' },
  { id: 'deepseek-r1', provider: 'deepseek', preset: 'extended_5' },
  { id: 'claude-3-7-sonnet', provider: 'anthropic', preset: 'extended_5' },
  { id: 'o3-mini', provider: 'openai', preset: 'extended_5' },
  { id: 'o1', provider: 'openai', preset: 'extended_5' },
  { id: 'o1-mini', provider: 'openai', preset: 'extended_5' },
  { id: 'o3', provider: 'openai', preset: 'extended_5' },
];

function isModelThinkingDirty() {
  const currentEntries = Object.entries(modelThinkingConfigs || {}).filter(([_, v]) => v != null);
  const savedEntries = Object.entries(savedModelThinkingConfigs || {}).filter(([_, v]) => v != null);
  if (currentEntries.length !== savedEntries.length) return true;

  const currentMap = new Map();
  currentEntries.forEach(([k, v]) => currentMap.set(k.toLowerCase(), v));

  for (const [k, sVal] of savedEntries) {
    const cVal = currentMap.get(k.toLowerCase());
    if (!cVal) return true;
    const cClean = {
      mode: cVal.mode || 'default',
      reasoning_effort: cVal.reasoning_effort || null,
      thinking_budget: cVal.thinking_budget != null ? Number(cVal.thinking_budget) : null,
      thinking_levels: Array.isArray(cVal.thinking_levels) ? cVal.thinking_levels.join(',') : '',
    };
    const sClean = {
      mode: sVal.mode || 'default',
      reasoning_effort: sVal.reasoning_effort || null,
      thinking_budget: sVal.thinking_budget != null ? Number(sVal.thinking_budget) : null,
      thinking_levels: Array.isArray(sVal.thinking_levels) ? sVal.thinking_levels.join(',') : '',
    };
    if (JSON.stringify(cClean) !== JSON.stringify(sClean)) return true;
  }
  return false;
}

function updateThinkingSaveButtonState() {
  const saveBtn = document.getElementById('thinking-save-all-btn');
  const badge = document.getElementById('thinking-unsaved-badge');
  const dirty = isModelThinkingDirty();
  if (saveBtn) {
    if (dirty) {
      saveBtn.classList.add('has-unsaved');
    } else {
      saveBtn.classList.remove('has-unsaved');
    }
  }
  if (badge) {
    badge.style.display = dirty ? 'inline-flex' : 'none';
  }
}

function getModelThinkingConfigDirect(modelId, upstreamId = '') {
  if (!modelThinkingConfigs || typeof modelThinkingConfigs !== 'object') return null;
  const mKey = String(modelId || '').trim().toLowerCase();
  const uKey = String(upstreamId || '').trim().toLowerCase();

  if (mKey) {
    for (const [k, v] of Object.entries(modelThinkingConfigs)) {
      if (String(k || '').trim().toLowerCase() === mKey && v && typeof v === 'object') {
        return v;
      }
    }
  }
  if (uKey && uKey !== mKey) {
    for (const [k, v] of Object.entries(modelThinkingConfigs)) {
      if (String(k || '').trim().toLowerCase() === uKey && v && typeof v === 'object') {
        return v;
      }
    }
  }
  return null;
}

function getModelThinkingRowConfig(modelId, upstreamId = '', defaultEffectiveLevels = null) {
  const cfg = getModelThinkingConfigDirect(modelId, upstreamId);
  if (cfg) {
    const configuredLevels = Array.isArray(cfg.thinking_levels) ? [...cfg.thinking_levels] : null;
    return {
      mode: cfg.mode || 'default',
      reasoning_effort: cfg.reasoning_effort || null,
      thinking_budget: (cfg.thinking_budget !== undefined && cfg.thinking_budget !== null && cfg.thinking_budget !== '') ? Number(cfg.thinking_budget) : null,
      thinking_levels: configuredLevels,
      provider: cfg.provider || null,
      upstream_id: cfg.upstream_id || null,
    };
  }

  let effectiveLevels = null;
  if (Array.isArray(defaultEffectiveLevels) && defaultEffectiveLevels.length > 0) {
    effectiveLevels = [...defaultEffectiveLevels];
  }

  return {
    mode: 'default',
    reasoning_effort: null,
    thinking_budget: null,
    thinking_levels: effectiveLevels,
    provider: null,
    upstream_id: upstreamId || null,
  };
}

function getThinkingLevelPreset(levels) {
  if (!levels || !Array.isArray(levels) || levels.length === 0) return 'none';
  const joined = levels.map((l) => String(l).trim().toLowerCase()).join(',');
  if (joined === 'low,medium,high,xhigh,max') return 'extended_5';
  if (joined === 'minimal,low,medium,high,xhigh,max') return 'full_6';
  if (joined === 'low,medium,high') return 'standard_3';
  return 'custom';
}

function hasThinkingAdvancedConfig(cfg) {
  if (!cfg) return false;
  return (
    (cfg.mode && cfg.mode !== 'default') ||
    Boolean(cfg.reasoning_effort) ||
    (cfg.thinking_budget !== null && cfg.thinking_budget !== undefined)
  );
}

function isModelThinkingConfigured(modelId, upstreamId = '') {
  const cfg = getModelThinkingConfigDirect(modelId, upstreamId);
  if (!cfg) return false;
  const hasMode = cfg.mode && cfg.mode !== 'default';
  const hasEffort = Boolean(cfg.reasoning_effort);
  const hasBudget = cfg.thinking_budget !== null && cfg.thinking_budget !== undefined && cfg.thinking_budget !== '';
  const hasLevels = Array.isArray(cfg.thinking_levels) && cfg.thinking_levels.length > 0;
  return Boolean(hasMode || hasEffort || hasBudget || hasLevels);
}

function setModelThinkingSearch(value) {
  modelThinkingSearch = String(value || '').trim().toLowerCase();
  renderModelThinkingPanel();
}

function onModelThinkingSelectModel(value) {
  const input = document.getElementById('model-thinking-add-id');
  if (input && value) {
    input.value = value;
  }
}

function populateModelThinkingSelect() {
  const select = document.getElementById('model-thinking-select-id');
  if (!select) return;
  select.innerHTML = '<option value="">-- 选择已有模型 --</option>';
  modelThinkingAllModels.forEach((modelId) => {
    const opt = document.createElement('option');
    opt.value = modelId;
    opt.textContent = modelId;
    select.appendChild(opt);
  });
}

function inferProviderForModel(modelId, candidates) {
  const mid = String(modelId || '').trim().toLowerCase();
  if (!mid) return 'custom';

  for (const item of candidates) {
    if (item.model_id.toLowerCase() === mid || (item.upstream_id && item.upstream_id.toLowerCase() === mid)) {
      if (item.provider && item.provider !== 'custom' && item.provider !== '其他/自定义') {
        return item.provider;
      }
    }
  }

  const knownProviders = new Set(
    candidates
      .map((c) => String(c.provider || '').toLowerCase())
      .filter((p) => p && p !== 'custom' && p !== '其他/自定义' && p !== '-')
  );

  const prefixMatch = mid.match(/^([a-z0-9._-]+)-/i);
  if (prefixMatch) {
    const candidatePrefix = prefixMatch[1].toLowerCase();
    if (knownProviders.has(candidatePrefix)) {
      return candidatePrefix;
    }
  }

  if (activeThinkingProvider && activeThinkingProvider !== 'all' && activeThinkingProvider !== 'configured') {
    return activeThinkingProvider;
  }

  return 'custom';
}

function mergeModelThinkingCandidates(candidates, configs) {
  const merged = new Map();
  const rawCandidates = Array.isArray(candidates) ? candidates : [];

  rawCandidates.forEach((item) => {
    const modelId = String(item?.model_id || '').trim();
    if (!modelId) return;
    const key = modelId.toLowerCase();
    const existing = merged.get(key);
    const effectiveLevels = Array.isArray(item.effective_levels) && item.effective_levels.length
      ? [...item.effective_levels]
      : (existing && Array.isArray(existing.effective_levels) ? existing.effective_levels : []);
    const sources = Array.from(new Set([
      ...(existing?.sources || []),
      ...(Array.isArray(item.sources) && item.sources.length ? item.sources : ['candidate']),
    ]));
    merged.set(key, {
      model_id: existing?.model_id || modelId,
      provider: item.provider && item.provider !== '-' && item.provider !== '其他/自定义'
        ? item.provider
        : (existing?.provider || 'custom'),
      upstream_id: item.upstream_id || existing?.upstream_id || '',
      sources,
      thinking_hint: Boolean(item.thinking_hint || existing?.thinking_hint),
      effective_levels: effectiveLevels,
    });
  });

  Object.keys(configs || {}).forEach((modelId) => {
    const key = String(modelId || '').trim().toLowerCase();
    if (!key || merged.has(key)) return;
    const cfg = configs[modelId];
    const inferredProvider = (cfg && cfg.provider) || inferProviderForModel(modelId, rawCandidates);
    merged.set(key, {
      model_id: modelId,
      provider: inferredProvider,
      upstream_id: (cfg && cfg.upstream_id) || '',
      sources: ['configs'],
      thinking_hint: true,
      effective_levels: Array.isArray(cfg && cfg.thinking_levels) ? [...cfg.thinking_levels] : [],
    });
  });

  return Array.from(merged.values()).sort((left, right) => {
    const providerCompare = String(left.provider || '').localeCompare(String(right.provider || ''));
    if (providerCompare) return providerCompare;
    return String(left.model_id || '').localeCompare(String(right.model_id || ''));
  });
}

function selectThinkingProviderGroup(providerKey) {
  activeThinkingProvider = providerKey;
  renderModelThinkingPanel();
}

function clearThinkingSelection() {
  selectedThinkingModels.clear();
  renderModelThinkingPanel();
}

function toggleThinkingModelSelection(modelId) {
  if (selectedThinkingModels.has(modelId)) {
    selectedThinkingModels.delete(modelId);
  } else {
    selectedThinkingModels.add(modelId);
  }
  renderModelThinkingPanel();
}

function toggleSelectAllInProvider(providerName) {
  const modelsInProvider = modelThinkingCandidates
    .filter((item) => String(item.provider || 'custom').toLowerCase() === String(providerName || 'custom').toLowerCase())
    .map((item) => item.model_id);
  const allSelected = modelsInProvider.length > 0 && modelsInProvider.every((id) => selectedThinkingModels.has(id));
  if (allSelected) {
    modelsInProvider.forEach((id) => selectedThinkingModels.delete(id));
  } else {
    modelsInProvider.forEach((id) => selectedThinkingModels.add(id));
  }
  renderModelThinkingPanel();
}

function toggleThinkingAdvanced(modelId) {
  if (thinkingAdvancedOpen.has(modelId)) {
    thinkingAdvancedOpen.delete(modelId);
  } else {
    thinkingAdvancedOpen.add(modelId);
  }
  renderModelThinkingPanel();
}

function copyThinkingModelId(modelId) {
  if (!modelId) return;
  if (navigator.clipboard && navigator.clipboard.writeText) {
    navigator.clipboard.writeText(modelId).then(() => {
      showMessage(`已复制模型 ID: ${modelId}`);
    }).catch(() => {
      showMessage(`模型 ID: ${modelId}`);
    });
  } else {
    showMessage(`模型 ID: ${modelId}`);
  }
}

function batchApplyPresetToSelected(presetId) {
  if (!selectedThinkingModels.size) {
    showMessage('请先在下方勾选至少一个模型', true);
    return;
  }
  const preset = THINKING_LEVEL_PRESETS.find((p) => p.id === presetId);
  if (!preset) return;
  const levels = preset.levels.length ? [...preset.levels] : null;

  selectedThinkingModels.forEach((modelId) => {
    const item = modelThinkingCandidates.find((c) => c.model_id === modelId);
    const cfg = getModelThinkingRowConfig(modelId, item ? item.upstream_id : '', item ? item.effective_levels : null);
    cfg.thinking_levels = levels ? [...levels] : null;
    cfg.provider = (item && item.provider) || cfg.provider || 'custom';
    cfg.upstream_id = (item && item.upstream_id) || cfg.upstream_id || '';
    modelThinkingConfigs[modelId] = cfg;
  });

  renderModelThinkingPanel();
  updateThinkingSaveButtonState();
  showMessage(`已将选中的 ${selectedThinkingModels.size} 个模型设为【${preset.label}】，请点击「保存配置」使设置生效。`);
}

function deleteSelectedThinkingModels() {
  if (!selectedThinkingModels.size) {
    showMessage('请先选择要删除/重置的模型', true);
    return;
  }
  const count = selectedThinkingModels.size;
  selectedThinkingModels.forEach((modelId) => {
    delete modelThinkingConfigs[modelId];
    thinkingAdvancedOpen.delete(modelId);
  });
  selectedThinkingModels.clear();
  renderModelThinkingPanel();
  updateThinkingSaveButtonState();
  showMessage(`已重置选中的 ${count} 个模型配置，请点击「保存配置」同步。`);
}

function applyPresetToProvider(providerName, presetId) {
  const preset = THINKING_LEVEL_PRESETS.find((p) => p.id === presetId);
  if (!preset) return;
  const levels = preset.levels.length ? [...preset.levels] : null;

  let count = 0;
  modelThinkingCandidates.forEach((item) => {
    if (String(item.provider || '').toLowerCase() === String(providerName || '').toLowerCase()) {
      const cfg = getModelThinkingRowConfig(item.model_id, item.upstream_id, item.effective_levels);
      cfg.thinking_levels = levels ? [...levels] : null;
      cfg.provider = item.provider;
      cfg.upstream_id = item.upstream_id;
      modelThinkingConfigs[item.model_id] = cfg;
      count++;
    }
  });

  renderModelThinkingPanel();
  updateThinkingSaveButtonState();
  showMessage(`已将 ${providerName} 分组的 ${count} 个模型设为【${preset.label}】，请点击「保存配置」同步。`);
}

function addManualModelThinkingRow() {
  const input = document.getElementById('model-thinking-add-id');
  const presetSelect = document.getElementById('model-thinking-add-preset');
  if (!input) return;
  const modelId = String(input.value || '').trim();
  if (!modelId) {
    showMessage('请输入模型 ID', true);
    return;
  }
  const chosenPreset = presetSelect ? presetSelect.value : 'extended_5';
  let targetLevels = null;
  const matched = THINKING_LEVEL_PRESETS.find((p) => p.id === chosenPreset);
  if (matched && matched.levels.length > 0) {
    targetLevels = [...matched.levels];
  }

  const inferredProvider = inferProviderForModel(modelId, modelThinkingCandidates);
  const existing = modelThinkingCandidates.find((c) => c.model_id.toLowerCase() === modelId.toLowerCase());
  if (!existing) {
    modelThinkingCandidates.push({
      model_id: modelId,
      provider: inferredProvider,
      upstream_id: '',
      sources: ['manual'],
      thinking_hint: false,
      effective_levels: targetLevels || [],
    });
  }

  modelThinkingConfigs[modelId] = {
    mode: 'default',
    reasoning_effort: null,
    thinking_budget: null,
    thinking_levels: targetLevels,
    provider: inferredProvider,
    upstream_id: '',
  };

  input.value = '';
  const select = document.getElementById('model-thinking-select-id');
  if (select) {
    select.value = '';
  }
  renderModelThinkingPanel();
  updateThinkingSaveButtonState();
  showMessage(`已添加模型 ${modelId}（归属于 ${inferredProvider}），配置完成后请点击「保存配置」同步。`);
}

function quickAddPopularModels() {
  let addedCount = 0;
  POPULAR_REASONING_MODELS.forEach((m) => {
    const key = m.id.toLowerCase();
    const existing = modelThinkingCandidates.find((c) => c.model_id.toLowerCase() === key);
    const p = THINKING_LEVEL_PRESETS.find((x) => x.id === m.preset);
    const defaultLevels = p && p.levels.length ? [...p.levels] : ['low', 'medium', 'high', 'xhigh', 'max'];

    if (!existing) {
      modelThinkingCandidates.push({
        model_id: m.id,
        provider: m.provider,
        upstream_id: m.id,
        sources: ['preset'],
        thinking_hint: true,
        effective_levels: defaultLevels,
      });
      addedCount++;
    }
    if (!modelThinkingConfigs[m.id]) {
      modelThinkingConfigs[m.id] = {
        mode: 'default',
        reasoning_effort: null,
        thinking_budget: null,
        thinking_levels: defaultLevels,
        provider: m.provider,
        upstream_id: m.id,
      };
    }
  });
  renderModelThinkingPanel();
  updateThinkingSaveButtonState();
  showMessage(`已快捷引入常用主流推理模型（新增/配置 ${addedCount} 个），点击「保存配置」即可生效。`);
}

function deleteModelThinkingRow(modelId) {
  delete modelThinkingConfigs[modelId];
  selectedThinkingModels.delete(modelId);
  thinkingAdvancedOpen.delete(modelId);
  renderModelThinkingPanel();
  updateThinkingSaveButtonState();
  showMessage(`已重置模型 ${modelId} 的自定义配置，点击「保存配置」同步。`);
}

function onModelThinkingLevelPresetChange(modelId, presetId) {
  const item = modelThinkingCandidates.find((c) => c.model_id === modelId);
  const cfg = getModelThinkingRowConfig(modelId, item ? item.upstream_id : '', item ? item.effective_levels : null);
  const matched = THINKING_LEVEL_PRESETS.find((p) => p.id === presetId);
  if (presetId === 'none') {
    cfg.thinking_levels = [];
  } else if (presetId === 'custom') {
    if (!Array.isArray(cfg.thinking_levels) || cfg.thinking_levels.length === 0) {
      cfg.thinking_levels = ['low', 'medium', 'high', 'xhigh', 'max'];
    }
  } else if (matched && matched.levels.length) {
    cfg.thinking_levels = [...matched.levels];
  }
  cfg.provider = (item && item.provider) || cfg.provider || 'custom';
  cfg.upstream_id = (item && item.upstream_id) || cfg.upstream_id || '';
  modelThinkingConfigs[modelId] = cfg;
  renderModelThinkingPanel();
  updateThinkingSaveButtonState();
}

function onModelThinkingCustomLevelsInput(modelId, value) {
  const item = modelThinkingCandidates.find((c) => c.model_id === modelId);
  const cfg = getModelThinkingRowConfig(modelId, item ? item.upstream_id : '', item ? item.effective_levels : null);
  const tokens = String(value || '')
    .split(',')
    .map((t) => t.trim().toLowerCase())
    .filter(Boolean);
  cfg.thinking_levels = tokens.length ? tokens : [];
  cfg.provider = (item && item.provider) || cfg.provider || 'custom';
  cfg.upstream_id = (item && item.upstream_id) || cfg.upstream_id || '';
  modelThinkingConfigs[modelId] = cfg;
  updateThinkingSaveButtonState();
}

function onModelThinkingCustomLevelsCommit(modelId, value) {
  onModelThinkingCustomLevelsInput(modelId, value);
  renderModelThinkingPanel();
}

function onModelThinkingChange(modelId, field, value) {
  const item = modelThinkingCandidates.find((c) => c.model_id === modelId);
  const cfg = getModelThinkingRowConfig(modelId, item ? item.upstream_id : '', item ? item.effective_levels : null);
  cfg[field] = value;
  if (field === 'mode') {
    if (value === 'force_off') {
      cfg.reasoning_effort = null;
      cfg.thinking_budget = null;
    }
  }
  cfg.provider = (item && item.provider) || cfg.provider || 'custom';
  cfg.upstream_id = (item && item.upstream_id) || cfg.upstream_id || '';
  modelThinkingConfigs[modelId] = cfg;
  renderModelThinkingPanel();
  updateThinkingSaveButtonState();
}

function onModelThinkingBudgetInput(modelId, value) {
  const item = modelThinkingCandidates.find((c) => c.model_id === modelId);
  const cfg = getModelThinkingRowConfig(modelId, item ? item.upstream_id : '', item ? item.effective_levels : null);
  const trimmed = String(value || '').trim();
  cfg.thinking_budget = trimmed === '' ? null : parseInt(trimmed, 10);
  cfg.provider = (item && item.provider) || cfg.provider || 'custom';
  cfg.upstream_id = (item && item.upstream_id) || cfg.upstream_id || '';
  modelThinkingConfigs[modelId] = cfg;
  updateThinkingSaveButtonState();
}

function onModelThinkingBudgetCommit(modelId, value) {
  onModelThinkingBudgetInput(modelId, value);
  renderModelThinkingPanel();
}

function flushActiveThinkingInputs() {
  const activeEl = document.activeElement;
  if (activeEl && activeEl.dataset && activeEl.dataset.modelId) {
    const modelId = activeEl.dataset.modelId;
    const field = activeEl.dataset.field;
    if (field === 'thinking_budget') {
      onModelThinkingBudgetInput(modelId, activeEl.value);
    } else if (field === 'custom_levels') {
      onModelThinkingCustomLevelsInput(modelId, activeEl.value);
    }
  }
}

function escapeModelThinkingHtml(value) {
  return String(value ?? '')
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#39;');
}

function escapeModelThinkingJs(value) {
  return String(value ?? '').replace(/\\/g, '\\\\').replace(/'/g, "\\'");
}

function renderModelThinkingPanel() {
  const groupRoot = document.getElementById('model-thinking-groups');
  const listRoot = document.getElementById('model-thinking-list');
  const summaryEl = document.getElementById('model-thinking-summary');
  const searchInput = document.getElementById('model-thinking-search-input');
  if (!groupRoot || !listRoot) return;

  if (searchInput && document.activeElement !== searchInput && searchInput.value !== modelThinkingSearch) {
    searchInput.value = modelThinkingSearch;
  }

  // 1. Group candidates by provider
  const groupsMap = new Map();
  modelThinkingCandidates.forEach((item) => {
    const provider = item.provider || 'custom';
    if (!groupsMap.has(provider)) {
      groupsMap.set(provider, []);
    }
    groupsMap.get(provider).push(item);
  });

  // Filter candidates by search if needed
  let filteredCandidates = modelThinkingCandidates;
  if (modelThinkingSearch) {
    filteredCandidates = modelThinkingCandidates.filter((item) => {
      const cfg = getModelThinkingRowConfig(item.model_id, item.upstream_id, item.effective_levels);
      const text = [
        item.model_id,
        item.provider,
        item.upstream_id,
        (item.sources || []).join(' '),
        (cfg.thinking_levels || []).join(' '),
        cfg.mode || '',
        cfg.reasoning_effort || '',
      ].join(' ').toLowerCase();
      return text.includes(modelThinkingSearch);
    });
  }

  const configuredTotal = modelThinkingCandidates.filter((item) => isModelThinkingConfigured(item.model_id, item.upstream_id)).length;
  if (summaryEl) {
    const isDirty = isModelThinkingDirty();
    const dirtySuffix = isDirty ? ' <span style="color:var(--accent);font-weight:700;">(● 有未保存修改)</span>' : '';
    summaryEl.innerHTML = `共 ${modelThinkingCandidates.length} 个候选模型，已配置 ${configuredTotal} 个，已勾选 ${selectedThinkingModels.size} 个${dirtySuffix}`;
  }

  // 2. Render Left Sidebar Tabs
  const providersList = Array.from(groupsMap.keys()).sort((a, b) => a.localeCompare(b));
  let tabsHtml = `
    <button type="button" class="provider-map-tab ${activeThinkingProvider === 'all' ? 'is-active' : ''}" onclick="selectThinkingProviderGroup('all')">
      全部 <span class="tab-count">(${modelThinkingCandidates.length})</span>
    </button>
    <button type="button" class="provider-map-tab ${activeThinkingProvider === 'configured' ? 'is-active' : ''}" onclick="selectThinkingProviderGroup('configured')">
      已配置 <span class="tab-count">(${configuredTotal})</span>
    </button>
  `;

  providersList.forEach((provider) => {
    const pCount = (groupsMap.get(provider) || []).length;
    tabsHtml += `
      <button type="button" class="provider-map-tab ${activeThinkingProvider === provider ? 'is-active' : ''}" onclick="selectThinkingProviderGroup('${escapeModelThinkingJs(provider)}')">
        ${escapeModelThinkingHtml(provider)} <span class="tab-count">(${pCount})</span>
      </button>
    `;
  });
  groupRoot.innerHTML = tabsHtml;

  // 3. Render Right Content Cards
  let displayProviders = [];
  if (activeThinkingProvider === 'all' || activeThinkingProvider === 'configured') {
    displayProviders = providersList;
  } else {
    displayProviders = [activeThinkingProvider];
  }

  if (!displayProviders.length || !filteredCandidates.length) {
    listRoot.innerHTML = `<div class="auth-empty" style="text-align:center;padding:32px;color:var(--text-muted);">暂无匹配的模型</div>`;
    updateThinkingSaveButtonState();
    return;
  }

  let cardsHtml = '';
  displayProviders.forEach((provider) => {
    let itemsInGroup = (groupsMap.get(provider) || []);
    if (activeThinkingProvider === 'configured') {
      itemsInGroup = itemsInGroup.filter((item) => isModelThinkingConfigured(item.model_id, item.upstream_id));
    }
    if (modelThinkingSearch) {
      itemsInGroup = itemsInGroup.filter((item) => {
        const cfg = getModelThinkingRowConfig(item.model_id, item.upstream_id, item.effective_levels);
        const text = [
          item.model_id,
          item.provider,
          item.upstream_id,
          (item.sources || []).join(' '),
          (cfg.thinking_levels || []).join(' '),
          cfg.mode || '',
          cfg.reasoning_effort || '',
        ].join(' ').toLowerCase();
        return text.includes(modelThinkingSearch);
      });
    }

    if (!itemsInGroup.length) return;

    const confCountInGroup = itemsInGroup.filter((item) => isModelThinkingConfigured(item.model_id, item.upstream_id)).length;
    const allSelectedInGroup = itemsInGroup.length > 0 && itemsInGroup.every((i) => selectedThinkingModels.has(i.model_id));

    // Build Model Rows inside the Provider Card
    const rowsHtml = itemsInGroup.map((item) => {
      const cfg = getModelThinkingRowConfig(item.model_id, item.upstream_id, item.effective_levels);
      const isSelected = selectedThinkingModels.has(item.model_id);
      const currentPreset = getThinkingLevelPreset(cfg.thinking_levels);
      const isCustom = currentPreset === 'custom';
      const isConfigured = isModelThinkingConfigured(item.model_id, item.upstream_id);
      const isAdvancedOpen = thinkingAdvancedOpen.has(item.model_id);
      const hasAdvanced = hasThinkingAdvancedConfig(cfg);

      const presetOptions = THINKING_LEVEL_PRESETS.map(
        (p) => `<option value="${p.id}" ${currentPreset === p.id ? 'selected' : ''}>${p.label}</option>`
      ).join('');

      const modeOptions = MODEL_THINKING_MODES.map(
        (m) => `<option value="${m.id}" ${cfg.mode === m.id ? 'selected' : ''}>${m.label}</option>`
      ).join('');
      const effortOptions = REASONING_EFFORT_OPTIONS.map(
        (o) => `<option value="${o.id}" ${cfg.reasoning_effort === (o.id || null) ? 'selected' : ''}>${o.label}</option>`
      ).join('');
      const budgetValue = cfg.thinking_budget !== null && cfg.thinking_budget !== undefined ? cfg.thinking_budget : '';
      const effortDisabled = cfg.mode === 'force_off';
      const budgetDisabled = cfg.mode === 'force_off';

      const customLevelsValue = Array.isArray(cfg.thinking_levels) ? cfg.thinking_levels.join(', ') : '';

      let tagsHtml = '';
      if (Array.isArray(cfg.thinking_levels) && cfg.thinking_levels.length > 0) {
        tagsHtml = cfg.thinking_levels
          .map((lvl) => `<span class="model-thinking-tag ${lvl === 'max' || lvl === 'xhigh' ? 'tag-highlight' : ''}">${escapeModelThinkingHtml(lvl)}</span>`)
          .join('');
      } else {
        tagsHtml = `<span class="model-thinking-muted-hint">默认 [low, med, high]</span>`;
      }

      if (cfg.mode && cfg.mode !== 'default') {
        const modeLabel = cfg.mode === 'force_on' ? '强制开启' : '强制禁用';
        const modeColor = cfg.mode === 'force_on' ? '#10b981' : '#ef4444';
        tagsHtml += `<span class="model-thinking-tag" style="background:color-mix(in srgb, ${modeColor} 18%, var(--panel-2)); border-color:color-mix(in srgb, ${modeColor} 35%, transparent); color:${modeColor}; font-weight:700;">${modeLabel}</span>`;
      }
      if (cfg.reasoning_effort) {
        tagsHtml += `<span class="model-thinking-tag" style="background:color-mix(in srgb, var(--accent) 15%, var(--panel-2)); border-color:var(--accent); color:var(--text);">effort: ${escapeModelThinkingHtml(cfg.reasoning_effort)}</span>`;
      }
      if (cfg.thinking_budget) {
        tagsHtml += `<span class="model-thinking-tag" style="background:color-mix(in srgb, var(--accent) 15%, var(--panel-2)); border-color:var(--accent); color:var(--text);">budget: ${escapeModelThinkingHtml(cfg.thinking_budget)}</span>`;
      }

      const presetObj = THINKING_LEVEL_PRESETS.find((p) => p.id === currentPreset);
      const badgeText = presetObj ? presetObj.shortLabel : '默认';

      return `
        <div class="model-thinking-item-row ${isConfigured ? 'is-configured' : ''}">
          <div class="model-thinking-item-main">
            <label class="model-thinking-item-check" title="勾选以批量操作">
              <input type="checkbox" ${isSelected ? 'checked' : ''} onchange="toggleThinkingModelSelection('${escapeModelThinkingJs(item.model_id)}')" />
            </label>
            <div class="model-thinking-item-info">
              <div class="model-thinking-id">
                <span>${escapeModelThinkingHtml(item.model_id)}</span>
                <button type="button" class="model-thinking-copy-btn" onclick="copyThinkingModelId('${escapeModelThinkingJs(item.model_id)}')" title="复制模型 ID">📋</button>
              </div>
              ${item.upstream_id && item.upstream_id !== item.model_id ? `<div class="model-thinking-upstream">上游: ${escapeModelThinkingHtml(item.upstream_id)}</div>` : ''}
            </div>

            <div class="model-thinking-item-levels">
              <select class="model-thinking-select-level" onchange="onModelThinkingLevelPresetChange('${escapeModelThinkingJs(item.model_id)}', this.value)">
                ${presetOptions}
              </select>
              <div class="model-thinking-tags-wrap">
                ${tagsHtml}
              </div>
            </div>

            <div class="model-thinking-item-badge">
              <span class="model-thinking-chip-badge ${isConfigured ? 'badge-configured' : (currentPreset === 'extended_5' || currentPreset === 'full_6' ? 'badge-active' : '')}">${isConfigured ? '● 已自定义' : escapeModelThinkingHtml(badgeText)}</span>
            </div>

            <div class="model-thinking-item-actions">
              <button type="button" class="btn-toggle-advanced ${isAdvancedOpen ? 'is-open' : ''}" onclick="toggleThinkingAdvanced('${escapeModelThinkingJs(item.model_id)}')" title="展开/收起高级微调设置">
                ⚙ 高级 ${hasAdvanced ? '<span class="advanced-active-dot">●</span>' : ''}
              </button>
              <button type="button" class="btn-delete-row" onclick="deleteModelThinkingRow('${escapeModelThinkingJs(item.model_id)}')" title="重置回默认设置">重置</button>
            </div>
          </div>

          <!-- Collapsible Advanced Drawer -->
          ${isAdvancedOpen ? `
            <div class="model-thinking-item-advanced">
              <div class="advanced-field-group">
                <label>思考模式：</label>
                <select class="model-thinking-select-sm" onchange="onModelThinkingChange('${escapeModelThinkingJs(item.model_id)}', 'mode', this.value)">
                  ${modeOptions}
                </select>
              </div>
              <div class="advanced-field-group">
                <label>默认/固定 Effort：</label>
                <select class="model-thinking-select-sm" onchange="onModelThinkingChange('${escapeModelThinkingJs(item.model_id)}', 'reasoning_effort', this.value)" ${effortDisabled ? 'disabled' : ''}>
                  ${effortOptions}
                </select>
              </div>
              <div class="advanced-field-group">
                <label>Token 预算：</label>
                <input class="model-thinking-input-sm" type="number" min="0" placeholder="不指定" value="${escapeModelThinkingHtml(budgetValue)}" ${budgetDisabled ? 'disabled' : ''} data-model-id="${escapeModelThinkingHtml(item.model_id)}" data-field="thinking_budget" oninput="onModelThinkingBudgetInput('${escapeModelThinkingJs(item.model_id)}', this.value)" onchange="onModelThinkingBudgetCommit('${escapeModelThinkingJs(item.model_id)}', this.value)" />
              </div>
              ${isCustom ? `
                <div class="advanced-field-group advanced-field-full">
                  <label>自定义等级：</label>
                  <input class="model-thinking-input-sm" type="text" placeholder="逗号分隔等级, 如: low, medium, high, xhigh, max" value="${escapeModelThinkingHtml(customLevelsValue)}" data-model-id="${escapeModelThinkingHtml(item.model_id)}" data-field="custom_levels" oninput="onModelThinkingCustomLevelsInput('${escapeModelThinkingJs(item.model_id)}', this.value)" onchange="onModelThinkingCustomLevelsCommit('${escapeModelThinkingJs(item.model_id)}', this.value)" />
                </div>
              ` : ''}
            </div>
          ` : ''}
        </div>
      `;
    }).join('');

    cardsHtml += `
      <article class="provider-model-card model-thinking-group-card">
        <div class="provider-model-head">
          <div class="provider-model-name" style="font-size: 15px; font-weight: 800;">${escapeModelThinkingHtml(provider)}</div>
          <div class="provider-model-actions">
            <span class="provider-model-summary">共 ${itemsInGroup.length} 个模型 (已配置 ${confCountInGroup})</span>
            <button type="button" class="secondary provider-aggregate-btn" onclick="toggleSelectAllInProvider('${escapeModelThinkingJs(provider)}')">${allSelectedInGroup ? '取消本组' : '全选本组'}</button>
            <button type="button" class="secondary provider-aggregate-btn" onclick="applyPresetToProvider('${escapeModelThinkingJs(provider)}', 'extended_5')">本组设为 5 级扩展</button>
            <button type="button" class="secondary provider-test-btn" onclick="applyPresetToProvider('${escapeModelThinkingJs(provider)}', 'none')">本组恢复默认</button>
          </div>
        </div>

        <div class="model-thinking-items-list">
          ${rowsHtml}
        </div>
      </article>
    `;
  });

  listRoot.innerHTML = cardsHtml;
  updateThinkingSaveButtonState();
}

async function loadModelThinkingPanel(force = false) {
  if (modelThinkingLoading) return;
  modelThinkingLoading = true;
  try {
    const data = await api('/api/model-thinking-configs', 'GET');
    const returnedConfigs = data.configs && typeof data.configs === 'object' ? data.configs : {};
    modelThinkingConfigs = JSON.parse(JSON.stringify(returnedConfigs));
    savedModelThinkingConfigs = JSON.parse(JSON.stringify(returnedConfigs));

    const backendCandidates = Array.isArray(data.candidates) ? data.candidates : [];
    const allModels = Array.isArray(data.all_models) ? data.all_models : [];

    let providerItems = [];
    try {
      const pData = await api('/api/provider-models?runtime_state=1');
      providerItems = Array.isArray(pData.items) ? pData.items : [];
    } catch {
      try {
        const pData = await api('/api/provider-models');
        providerItems = Array.isArray(pData.items) ? pData.items : [];
      } catch {}
    }

    const candidateMap = new Map();
    backendCandidates.forEach((c) => {
      const key = String(c.model_id || '').trim().toLowerCase();
      if (key) {
        candidateMap.set(key, {
          model_id: c.model_id,
          provider: c.provider || 'custom',
          upstream_id: c.upstream_id || '',
          sources: Array.isArray(c.sources) ? [...c.sources] : ['candidate'],
          thinking_hint: Boolean(c.thinking_hint),
          effective_levels: Array.isArray(c.effective_levels) ? [...c.effective_levels] : [],
        });
      }
    });

    providerItems.forEach((item) => {
      const provider = String(item.provider || item.lookup_provider || '').trim();
      if (!provider) return;
      const rows = Array.isArray(item.rows) ? item.rows : [];
      rows.forEach((row) => {
        const callId = String(row.call_id || '').trim();
        const upstreamId = String(row.upstream_id || '').trim();
        if (!callId) return;
        const key = callId.toLowerCase();
        if (!candidateMap.has(key)) {
          candidateMap.set(key, {
            model_id: callId,
            provider: provider,
            upstream_id: upstreamId,
            sources: ['provider'],
            thinking_hint: false,
            effective_levels: [],
          });
        }
      });
    });

    const allModelsSet = new Set(allModels);
    candidateMap.forEach((item) => allModelsSet.add(item.model_id));
    modelThinkingAllModels = Array.from(allModelsSet).sort((a, b) => a.localeCompare(b));

    modelThinkingCandidates = mergeModelThinkingCandidates(Array.from(candidateMap.values()), modelThinkingConfigs);

    populateModelThinkingSelect();
    renderModelThinkingPanel();
  } catch (err) {
    showMessage(`加载模型 thinking 配置失败: ${err.message}`, true);
  } finally {
    modelThinkingLoading = false;
  }
}

async function saveModelThinkingPanel() {
  if (modelThinkingSaving) return;
  const saveBtn = document.getElementById('thinking-save-all-btn');
  const saveBtnText = document.getElementById('thinking-save-btn-text');

  flushActiveThinkingInputs();

  modelThinkingSaving = true;
  if (saveBtn) {
    saveBtn.disabled = true;
  }
  if (saveBtnText) {
    saveBtnText.textContent = '正在保存...';
  }

  try {
    const payload = {
      configs: {},
    };
    Object.entries(modelThinkingConfigs).forEach(([modelId, cfg]) => {
      const mid = String(modelId || '').trim();
      if (!mid) return;
      const levels = Array.isArray(cfg.thinking_levels) && cfg.thinking_levels.length > 0 ? cfg.thinking_levels : null;
      const clean = {
        mode: cfg.mode || 'default',
        reasoning_effort: cfg.reasoning_effort || null,
        thinking_budget: (cfg.thinking_budget !== null && cfg.thinking_budget !== undefined && cfg.thinking_budget !== '') ? Number(cfg.thinking_budget) : null,
        thinking_levels: levels,
        provider: cfg.provider || null,
        upstream_id: cfg.upstream_id || null,
      };
      if (clean.mode !== 'default' || clean.reasoning_effort || clean.thinking_budget !== null || clean.thinking_levels !== null) {
        payload.configs[mid] = clean;
      }
    });

    const data = await api('/api/model-thinking-configs', 'POST', payload);
    const returnedConfigs = data.configs && typeof data.configs === 'object' ? data.configs : {};
    modelThinkingConfigs = JSON.parse(JSON.stringify(returnedConfigs));
    savedModelThinkingConfigs = JSON.parse(JSON.stringify(returnedConfigs));

    modelThinkingCandidates = mergeModelThinkingCandidates(modelThinkingCandidates, modelThinkingConfigs);

    renderModelThinkingPanel();
    const msg = data.runtime_rebuilt
      ? (data.message || '保存成功，并已同步更新 Go 内核运行时配置。')
      : (data.message || '保存成功。');
    showMessage(msg);
  } catch (err) {
    showMessage(`保存失败: ${err.message}`, true);
  } finally {
    modelThinkingSaving = false;
    if (saveBtn) {
      saveBtn.disabled = false;
    }
    if (saveBtnText) {
      saveBtnText.textContent = '保存配置';
    }
    updateThinkingSaveButtonState();
  }
}
