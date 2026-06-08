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
  return apiKeyIntakePresets.find((item) => String(item.provider || '') === provider) || null;
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
    const note = document.getElementById('api-key-provider-note');
    if (note) note.textContent = '自定义模式会按你填写的 provider 和 Base URL 保存。';
  }
}

function selectApiKeyPreset(provider) {
  const selectedProvider = String(provider || '');
  const preset = apiKeyIntakePresets.find((item) => String(item.provider || '') === selectedProvider);
  const baseInput = document.getElementById('api-key-base-url');
  const secretInput = document.getElementById('api-key-secret');
  const remarkInput = document.getElementById('api-key-remark');
  const note = document.getElementById('api-key-provider-note');
  const providerChanged = apiKeyIntakeSelectedProvider && apiKeyIntakeSelectedProvider !== selectedProvider;
  apiKeyIntakeSelectedProvider = selectedProvider;
  if (preset && baseInput) {
    baseInput.value = preset.base_url || '';
  }
  if (providerChanged) {
    if (secretInput) secretInput.value = '';
    if (remarkInput) remarkInput.value = '';
  }
  if (note) {
    const modelCount = Array.isArray(preset?.models) ? preset.models.length : 0;
    note.textContent = preset
      ? `${preset.provider} · 默认 URL: ${preset.base_url || '-'} · 已有 ${modelCount} 个模型`
      : '选择已有 provider 后会自动填入默认 Base URL。';
  }
}

function fillApiKeyPresetModels() {
  const preset = currentApiKeyPreset();
  const input = document.getElementById('api-key-models');
  if (!preset || !input) return;
  const models = Array.isArray(preset.models) ? preset.models : [];
  input.value = models.join('\n');
  updateApiKeyModelCount();
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
          <span>代理</span>
          <b>${data?.proxy_restart?.ok ? '已重启' : '未重启'}</b>
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
