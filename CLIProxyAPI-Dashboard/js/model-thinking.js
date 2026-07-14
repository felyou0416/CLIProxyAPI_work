let modelThinkingCandidates = [];
let modelThinkingConfigs = {};
let modelThinkingSearch = '';
let modelThinkingOnlyConfigured = false;
let modelThinkingLoading = false;
let modelThinkingAllModels = [];

const MODEL_THINKING_MODES = [
  { id: 'default', label: '使用默认' },
  { id: 'force_on', label: '强制启用' },
  { id: 'force_off', label: '强制禁用' },
];

const REASONING_EFFORT_OPTIONS = [
  { id: '', label: '不指定' },
  { id: 'low', label: 'low' },
  { id: 'medium', label: 'medium' },
  { id: 'high', label: 'high' },
];

function formatModelThinkingMode(mode) {
  const found = MODEL_THINKING_MODES.find((m) => m.id === mode);
  return found ? found.label : mode;
}

function getModelThinkingRowConfig(modelId) {
  return modelThinkingConfigs[modelId] || { mode: 'default', reasoning_effort: null, thinking_budget: null };
}

function isModelThinkingConfigured(modelId) {
  const cfg = getModelThinkingRowConfig(modelId);
  return cfg.mode !== 'default' || cfg.reasoning_effort || cfg.thinking_budget !== null;
}

function setModelThinkingSearch(value) {
  modelThinkingSearch = String(value || '').trim().toLowerCase();
  renderModelThinkingPanel();
}

function onModelThinkingSelectModel(value) {
  const input = document.getElementById('model-thinking-add-id');
  if (input) {
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

function mergeModelThinkingCandidates(candidates, configs) {
  const merged = new Map();
  (Array.isArray(candidates) ? candidates : []).forEach((item) => {
    const modelId = String(item?.model_id || '').trim();
    if (!modelId) return;
    merged.set(modelId.toLowerCase(), {
      model_id: modelId,
      provider: item.provider || '-',
      upstream_id: item.upstream_id || '',
      sources: Array.isArray(item.sources) && item.sources.length ? item.sources : ['candidate'],
    });
  });
  Object.keys(configs || {}).forEach((modelId) => {
    const key = String(modelId || '').trim().toLowerCase();
    if (!key || merged.has(key)) return;
    merged.set(key, {
      model_id: modelId,
      provider: '-',
      upstream_id: '',
      sources: ['configs'],
    });
  });
  return Array.from(merged.values()).sort((left, right) => {
    const providerCompare = String(left.provider || '').localeCompare(String(right.provider || ''));
    if (providerCompare) return providerCompare;
    return String(left.model_id || '').localeCompare(String(right.model_id || ''));
  });
}

function addManualModelThinkingRow() {
  const input = document.getElementById('model-thinking-add-id');
  if (!input) return;
  const modelId = String(input.value || '').trim();
  if (!modelId) {
    showMessage('请输入模型 ID', true);
    return;
  }
  const existing = modelThinkingCandidates.find((c) => c.model_id === modelId);
  if (!existing) {
    modelThinkingCandidates.push({
      model_id: modelId,
      provider: '-',
      upstream_id: '',
      sources: ['manual'],
    });
  }
  if (!modelThinkingConfigs[modelId]) {
    modelThinkingConfigs[modelId] = { mode: 'default', reasoning_effort: null, thinking_budget: null };
  }
  input.value = '';
  const select = document.getElementById('model-thinking-select-id');
  if (select) {
    select.value = '';
  }
  renderModelThinkingPanel();
}

function deleteModelThinkingRow(modelId) {
  modelThinkingCandidates = modelThinkingCandidates.filter((c) => c.model_id !== modelId);
  delete modelThinkingConfigs[modelId];
  renderModelThinkingPanel();
}

function toggleModelThinkingOnlyConfigured() {
  const el = document.getElementById('model-thinking-only-configured');
  modelThinkingOnlyConfigured = el ? Boolean(el.checked) : false;
  renderModelThinkingPanel();
}

function filterModelThinkingCandidates() {
  return modelThinkingCandidates.filter((item) => {
    if (modelThinkingOnlyConfigured && !isModelThinkingConfigured(item.model_id)) {
      return false;
    }
    if (!modelThinkingSearch) return true;
    const text = [
      item.model_id,
      item.provider,
      item.upstream_id,
      (item.sources || []).join(' '),
    ]
      .join(' ')
      .toLowerCase();
    return text.includes(modelThinkingSearch);
  });
}

function renderModelThinkingPanel() {
  const tbody = document.getElementById('model-thinking-body');
  const summary = document.getElementById('model-thinking-summary');
  if (!tbody) return;

  const items = filterModelThinkingCandidates();
  const configuredCount = items.filter((item) => isModelThinkingConfigured(item.model_id)).length;

  if (summary) {
    summary.textContent = `共 ${modelThinkingCandidates.length} 个 thinking/reasoning 候选模型，当前显示 ${items.length} 个，已配置 ${configuredCount} 个`;
  }

  if (!items.length) {
    tbody.innerHTML = `<tr><td colspan="8" style="text-align:center;color:var(--text-muted);padding:24px;">没有匹配的模型</td></tr>`;
    return;
  }

  tbody.innerHTML = items
    .map((item) => {
      const cfg = getModelThinkingRowConfig(item.model_id);
      const isConfigured = cfg.mode !== 'default' || cfg.reasoning_effort || cfg.thinking_budget !== null;
      const modeOptions = MODEL_THINKING_MODES.map(
        (m) => `<option value="${m.id}" ${cfg.mode === m.id ? 'selected' : ''}>${m.label}</option>`
      ).join('');
      const effortOptions = REASONING_EFFORT_OPTIONS.map(
        (o) => `<option value="${o.id}" ${cfg.reasoning_effort === (o.id || null) ? 'selected' : ''}>${o.label}</option>`
      ).join('');
      const budgetValue = cfg.thinking_budget !== null && cfg.thinking_budget !== undefined ? cfg.thinking_budget : '';
      const effortDisabled = cfg.mode === 'force_off';
      const budgetDisabled = cfg.mode === 'force_off';

      return `
        <tr class="${isConfigured ? 'model-thinking-row-configured' : ''}" data-model-id="${escapeModelThinkingHtml(item.model_id)}">
          <td>
            <div class="model-thinking-id">${escapeModelThinkingHtml(item.model_id)}</div>
          </td>
          <td>${escapeModelThinkingHtml(item.provider || '-')}</td>
          <td>
            <div class="model-thinking-upstream">${escapeModelThinkingHtml(item.upstream_id || '-')}</div>
          </td>
          <td>
            <div class="model-thinking-source">${escapeModelThinkingHtml((item.sources || []).join(', '))}</div>
          </td>
          <td>
            <select class="model-thinking-select" data-field="mode" onchange="onModelThinkingChange('${escapeModelThinkingJs(item.model_id)}', 'mode', this.value)">
              ${modeOptions}
            </select>
          </td>
          <td>
            <select class="model-thinking-select" data-field="reasoning_effort" ${effortDisabled ? 'disabled' : ''} onchange="onModelThinkingChange('${escapeModelThinkingJs(item.model_id)}', 'reasoning_effort', this.value)">
              ${effortOptions}
            </select>
          </td>
          <td>
            <input class="model-thinking-input" data-field="thinking_budget" type="number" min="0" step="1" placeholder="不指定" value="${escapeModelThinkingHtml(budgetValue)}" ${budgetDisabled ? 'disabled' : ''} onchange="onModelThinkingBudgetChange('${escapeModelThinkingJs(item.model_id)}', this.value)">
          </td>
          <td>
            <button type="button" class="btn-delete" style="padding: 4px 8px; font-size: 12px; color: var(--danger, #ef4444); background: transparent; border: 1px solid var(--danger, #ef4444); border-radius: 4px; cursor: pointer; transition: all 0.2s;" onmouseover="this.style.background='var(--danger, #ef4444)'; this.style.color='#fff';" onmouseout="this.style.background='transparent'; this.style.color='var(--danger, #ef4444)';" onclick="deleteModelThinkingRow('${escapeModelThinkingJs(item.model_id)}')">删除</button>
          </td>
        </tr>
      `;
    })
    .join('');
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

function onModelThinkingChange(modelId, field, value) {
  const cfg = getModelThinkingRowConfig(modelId);
  cfg[field] = value;
  if (field === 'mode') {
    if (value === 'force_off') {
      cfg.reasoning_effort = null;
      cfg.thinking_budget = null;
    }
  }
  modelThinkingConfigs[modelId] = cfg;
  renderModelThinkingPanel();
}

function onModelThinkingBudgetChange(modelId, value) {
  const cfg = getModelThinkingRowConfig(modelId);
  const trimmed = String(value || '').trim();
  cfg.thinking_budget = trimmed === '' ? null : parseInt(trimmed, 10);
  modelThinkingConfigs[modelId] = cfg;
  renderModelThinkingPanel();
}

async function loadModelThinkingPanel(force = false) {
  if (modelThinkingLoading) return;
  modelThinkingLoading = true;
  try {
    const data = await api('/api/model-thinking-configs', 'GET');
    modelThinkingConfigs = data.configs && typeof data.configs === 'object' ? data.configs : {};
    modelThinkingAllModels = Array.isArray(data.all_models) ? data.all_models : [];
    modelThinkingCandidates = mergeModelThinkingCandidates(data.candidates, modelThinkingConfigs);

    populateModelThinkingSelect();
    renderModelThinkingPanel();
  } catch (err) {
    showMessage(`加载模型 thinking 配置失败: ${err.message}`, true);
  } finally {
    modelThinkingLoading = false;
  }
}

async function saveModelThinkingPanel() {
  try {
    const payload = {
      configs: {},
    };
    Object.entries(modelThinkingConfigs).forEach(([modelId, cfg]) => {
      const clean = {
        mode: cfg.mode || 'default',
        reasoning_effort: cfg.reasoning_effort || null,
        thinking_budget: cfg.thinking_budget !== null && cfg.thinking_budget !== undefined ? cfg.thinking_budget : null,
      };
      if (clean.mode !== 'default' || clean.reasoning_effort || clean.thinking_budget !== null) {
        payload.configs[modelId] = clean;
      }
    });

    const data = await api('/api/model-thinking-configs', 'POST', payload);
    modelThinkingConfigs = data.configs && typeof data.configs === 'object' ? data.configs : {};
    renderModelThinkingPanel();
    showMessage(data.message || '保存成功');
  } catch (err) {
    showMessage(`保存失败: ${err.message}`, true);
  }
}
