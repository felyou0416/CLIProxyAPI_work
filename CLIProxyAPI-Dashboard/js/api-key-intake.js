let apiKeyIntakePresets = [];
let apiKeyIntakeMode = 'existing';
let apiKeyIntakeSelectedProvider = '';

function apiKeyIntakeEscape(value) {
  return String(value ?? '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

function parseApiKeyIntakeModels() {
  const input = document.getElementById('api-key-models');
  const seen = new Set();
  const models = [];
  String(input?.value || '')
    .split(/\r?\n|,/)
    .map((item) => item.trim())
    .filter(Boolean)
    .forEach((item) => {
      if (!seen.has(item)) {
        seen.add(item);
        models.push(item);
      }
    });
  return models;
}

function updateApiKeyModelCount() {
  const countEl = document.getElementById('api-key-model-count');
  if (!countEl) return;
  const count = parseApiKeyIntakeModels().length;
  countEl.textContent = `${count} 个模型`;
}

function currentApiKeyPreset() {
  const provider = String(document.getElementById('api-key-provider-select')?.value || '').trim();
  return apiKeyIntakePresets.find((item) => String(item.provider || '').toLowerCase() === provider.toLowerCase()) || null;
}

function apiKeyPresetUrlEntries(preset) {
  const entries = [];
  const seen = new Set();
  const rawEntries = Array.isArray(preset?.url_entries) ? preset.url_entries : [];
  rawEntries.forEach((entry) => {
    const url = String(entry?.base_url || '').trim().replace(/\/+$/, '');
    if (!url || seen.has(url)) return;
    seen.add(url);
    entries.push({
      base_url: url,
      models: Array.isArray(entry?.models) ? entry.models.filter(Boolean) : [],
    });
  });
  if (!entries.length) {
    const values = Array.isArray(preset?.base_urls) ? preset.base_urls : [preset?.base_url];
    values.forEach((value) => {
      const url = String(value || '').trim().replace(/\/+$/, '');
      if (url && !seen.has(url)) {
        seen.add(url);
        entries.push({ base_url: url, models: [] });
      }
    });
  }
  return entries;
}

function apiKeyPresetUrls(preset) {
  return apiKeyPresetUrlEntries(preset).map((entry) => entry.base_url);
}

function apiKeyModelsForUrl(preset, baseUrl) {
  const normalized = String(baseUrl || '').trim().replace(/\/+$/, '');
  const entry = apiKeyPresetUrlEntries(preset).find((item) => item.base_url === normalized);
  return entry?.models?.length ? entry.models : (Array.isArray(preset?.models) ? preset.models : []);
}

function renderApiKeyBaseUrlOptions(preset) {
  const datalist = document.getElementById('api-key-base-url-options');
  if (!datalist) return [];
  const entries = apiKeyPresetUrlEntries(preset);
  datalist.innerHTML = entries.map((entry) => `<option value="${apiKeyIntakeEscape(entry.base_url)}"></option>`).join('');
  return entries.map((entry) => entry.base_url);
}

function fillApiKeyModelsForUrl(preset, baseUrl) {
  const input = document.getElementById('api-key-models');
  if (!input || !preset) return;
  input.value = apiKeyModelsForUrl(preset, baseUrl).join('\n');
  updateApiKeyModelCount();
}

function setApiKeyIntakeMode(mode) {
  apiKeyIntakeMode = mode === 'custom' ? 'custom' : 'existing';
  const existingBtn = document.getElementById('api-key-mode-existing');
  const customBtn = document.getElementById('api-key-mode-custom');
  const select = document.getElementById('api-key-provider-select');
  const custom = document.getElementById('api-key-provider-custom');
  existingBtn?.classList.toggle('is-active', apiKeyIntakeMode === 'existing');
  customBtn?.classList.toggle('is-active', apiKeyIntakeMode === 'custom');
  if (select) select.hidden = apiKeyIntakeMode !== 'existing';
  if (custom) custom.hidden = apiKeyIntakeMode !== 'custom';
  if (apiKeyIntakeMode === 'existing') {
    selectApiKeyPreset(select?.value || '');
  } else {
    const customVal = custom?.value?.trim() || '';
    if (customVal) {
      onApiKeyCustomProviderInput(customVal);
    } else {
      const note = document.getElementById('api-key-provider-note');
      if (note) note.textContent = '自定义模式：可选择或输入已有 Provider 自动填入默认 Base URL，或自行填写新 Base URL。';
    }
  }
}

function selectApiKeyPreset(provider) {
  const selectedProvider = String(provider || '').trim();
  const preset = apiKeyIntakePresets.find((item) => String(item.provider || '').toLowerCase() === selectedProvider.toLowerCase());
  const baseInput = document.getElementById('api-key-base-url');
  const secretInput = document.getElementById('api-key-secret');
  const remarkInput = document.getElementById('api-key-remark');
  const note = document.getElementById('api-key-provider-note');
  const providerChanged = apiKeyIntakeSelectedProvider && apiKeyIntakeSelectedProvider.toLowerCase() !== selectedProvider.toLowerCase();
  apiKeyIntakeSelectedProvider = selectedProvider;
  const urls = renderApiKeyBaseUrlOptions(preset);
  if (preset && baseInput) {
    baseInput.value = urls[0] || '';
    fillApiKeyModelsForUrl(preset, baseInput.value);
  }
  if (providerChanged) {
    if (secretInput) secretInput.value = '';
    if (remarkInput) remarkInput.value = '';
  }
  if (note) {
    const modelCount = preset && baseInput ? apiKeyModelsForUrl(preset, baseInput.value).length : 0;
    note.textContent = preset
      ? `${preset.provider} · 已从认证文件发现 ${urls.length} 个 Base URL，已填入：${urls[0] || '-'} · 当前 URL 有 ${modelCount} 个模型`
      : '选择已有 Provider 后会从认证文件填入可选 Base URL。';
  }
}

function onApiKeyCustomProviderInput(value) {
  const providerName = String(value || '').trim();
  const preset = apiKeyIntakePresets.find((item) => String(item.provider || '').toLowerCase() === providerName.toLowerCase());
  const baseInput = document.getElementById('api-key-base-url');
  const note = document.getElementById('api-key-provider-note');
  const urls = renderApiKeyBaseUrlOptions(preset);
  if (preset && urls.length && baseInput) {
    baseInput.value = urls[0];
    fillApiKeyModelsForUrl(preset, baseInput.value);
    if (note) {
      const modelCount = apiKeyModelsForUrl(preset, baseInput.value).length;
      note.textContent = `匹配到认证文件中的 Provider (${preset.provider}) · 已发现 ${urls.length} 个 Base URL，已填入：${urls[0]} · 当前 URL 有 ${modelCount} 个模型`;
    }
  } else if (note) {
    note.textContent = providerName
      ? '自定义模式：按你填写的 Provider 和 Base URL 保存。'
      : '自定义模式：可选择或输入认证文件中已有的 Provider，也可自行填写新 Base URL。';
  }
}

function onApiKeyBaseUrlInput(value) {
  const preset = apiKeyIntakeMode === 'custom'
    ? apiKeyIntakePresets.find((item) => String(item.provider || '').toLowerCase() === String(document.getElementById('api-key-provider-custom')?.value || '').trim().toLowerCase())
    : currentApiKeyPreset();
  if (!preset) return;
  const normalized = String(value || '').trim().replace(/\/+$/, '');
  const entries = apiKeyPresetUrlEntries(preset);
  const entry = entries.find((item) => item.base_url === normalized);
  if (entry) {
    fillApiKeyModelsForUrl(preset, normalized);
    const note = document.getElementById('api-key-provider-note');
    if (note) note.textContent = `${preset.provider} · 已选择 ${normalized} · 当前 URL 有 ${entry.models.length} 个模型`;
  }
}

function fillApiKeyPresetModels() {
  const preset = currentApiKeyPreset();
  const baseInput = document.getElementById('api-key-base-url');
  if (!preset || !baseInput) return;
  fillApiKeyModelsForUrl(preset, baseInput.value);
}

function toggleApiKeyIntakeSecret() {
  const input = document.getElementById('api-key-secret');
  const btn = document.getElementById('api-key-secret-toggle');
  if (!input) return;
  const nextType = input.type === 'password' ? 'text' : 'password';
  input.type = nextType;
  if (btn) btn.textContent = nextType === 'password' ? '显示' : '隐藏';
}

function renderApiKeyIntakeResult(data) {
  const status = document.getElementById('api-key-intake-status');
  const root = document.getElementById('api-key-intake-result');
  if (!root) return;
  const auth = data?.auth || {};
  const queued = data?.test_result?.queued || [];
  if (status) status.textContent = data?.ok ? '已保存' : '失败';
  root.innerHTML = `
    <div class="api-key-result-card">
      <div class="api-key-result-title">
        <div>
          <strong>${apiKeyIntakeEscape(auth.provider || '-')}</strong>
          <div class="muted">${apiKeyIntakeEscape(auth.name || auth.id || '-')}</div>
        </div>
        <span class="auth-chip active-chip">${data?.ok ? '保存成功' : '保存失败'}</span>
      </div>
      <div class="api-key-result-grid">
        <div class="api-key-result-metric">
          <span>模型</span>
          <b>${apiKeyIntakeEscape(auth.modelCount || queued.length || 0)}</b>
        </div>
        <div class="api-key-result-metric">
          <span>Key 指纹</span>
          <b>${apiKeyIntakeEscape(auth.keyFingerprint || '-')}</b>
        </div>
        <div class="api-key-result-metric">
          <span>Runtime</span>
          <b>${data?.runtime_rebuilt ? '已重建' : '未重建'}</b>
        </div>
        <div class="api-key-result-metric">
          <span>生效方式</span>
          <b>${data?.runtime_hot_reloaded ? '热更新' : (data?.runtime_rebuilt ? '下次启动' : '同步失败')}</b>
        </div>
      </div>
      <div class="api-key-result-queue">检测队列：${queued.length ? apiKeyIntakeEscape(queued.join(', ')) : '未排队'}</div>
    </div>
  `;
}

async function loadApiKeyIntakePanel(force = false) {
  try {
    if (force || !apiKeyIntakePresets.length) {
      const data = await api('/api/manual-provider-presets');
      apiKeyIntakePresets = Array.isArray(data.items) ? data.items : [];
    }
    const select = document.getElementById('api-key-provider-select');
    const datalist = document.getElementById('api-key-provider-presets');
    if (datalist) {
      datalist.innerHTML = apiKeyIntakePresets.map((item) => `
        <option value="${apiKeyIntakeEscape(item.provider)}"></option>
      `).join('');
    }
    if (select) {
      const current = select.value;
      select.innerHTML = apiKeyIntakePresets.map((item) => `
        <option value="${apiKeyIntakeEscape(item.provider)}">${apiKeyIntakeEscape(item.provider)}</option>
      `).join('');
      if (current && apiKeyIntakePresets.some((item) => item.provider === current)) {
        select.value = current;
      }
      selectApiKeyPreset(select.value);
    }
    const modelInput = document.getElementById('api-key-models');
    if (modelInput) modelInput.oninput = updateApiKeyModelCount;
    updateApiKeyModelCount();
  } catch (err) {
    showMessage(err.message || String(err), true);
  }
}

async function submitApiKeyIntake() {
  const submitBtn = document.getElementById('api-key-submit-btn');
  const provider = apiKeyIntakeMode === 'custom'
    ? String(document.getElementById('api-key-provider-custom')?.value || '').trim()
    : String(document.getElementById('api-key-provider-select')?.value || '').trim();
  const baseUrl = String(document.getElementById('api-key-base-url')?.value || '').trim();
  const apiKey = String(document.getElementById('api-key-secret')?.value || '').trim();
  const remark = String(document.getElementById('api-key-remark')?.value || '').trim();
  const models = parseApiKeyIntakeModels();

  if (!provider || !baseUrl || !apiKey || !models.length) {
    showToast('Provider、Base URL、API Key 和模型清单均为必填项。', true);
    return;
  }

  try {
    if (submitBtn) {
      submitBtn.disabled = true;
      submitBtn.textContent = '保存中...';
    }
    const data = await api('/api/create-manual-auth', 'POST', {
      provider,
      base_url: baseUrl,
      api_key: apiKey,
      models,
      remark,
      select_after_create: true,
      test_after_create: true,
    });
    const secret = document.getElementById('api-key-secret');
    if (secret) secret.value = '';
    renderApiKeyIntakeResult(data);
    showToast(data.message || 'API Key 已保存并开始检测。');
    if (typeof loadAuthFiles === 'function') loadAuthFiles(true);
    if (typeof loadProviderModels === 'function') loadProviderModels();
  } catch (err) {
    showToast(err.message || String(err), true);
  } finally {
    if (submitBtn) {
      submitBtn.disabled = false;
      submitBtn.textContent = '保存并检测';
    }
  }
}
