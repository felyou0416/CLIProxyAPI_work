/* Cloaking Configuration */

let cloakingAuthFiles = [];
let cloakingData = {};

function _ce(value) {
  return String(value ?? '')
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#39;');
}

async function loadCloakingConfig() {
  const content = document.getElementById('cloaking-config-content');
  if (!content) return;
  try {
    const data = await api('/api/cloaking-config');
    cloakingAuthFiles = data.auth_files || [];
    cloakingData = data.items || {};
    renderCloakingConfig();
  } catch (e) {
    content.innerHTML = `<div class="metric-empty">${_ce(e.message || 'load failed')}</div>`;
  }
}

function renderCloakingConfig() {
  const content = document.getElementById('cloaking-config-content');
  if (!cloakingAuthFiles.length) {
    content.innerHTML = '<div class="metric-empty">没有可用的认证文件。请先在 OAuth 或 API Key 接入中添加凭证。</div>';
    return;
  }
  const authOptions = cloakingAuthFiles.map(af =>
    `<option value="${_ce(af.id)}">${_ce(af.name)} (${_ce(af.provider || 'unknown')})</option>`
  ).join('');

  const firstId = cloakingAuthFiles[0]?.id || '';
  const d = cloakingData[firstId] || {};

  content.innerHTML = `<div class="config-section">
    <div class="config-row">
      <label class="config-label">选择凭证</label>
      <select id="cloaking-auth-select" onchange="onCloakingAuthChange()" style="width:100%;max-width:400px">${authOptions}</select>
    </div>
    <fieldset id="cloaking-fields" style="margin-top:12px"><legend>伪装配置</legend>
      <div class="config-row">
        <label class="config-label">伪装模式</label>
        <select id="cloak-mode" style="width:200px">
          <option value="auto" ${(d.cloak_mode || 'auto') === 'auto' ? 'selected' : ''}>自动（检测客户端）</option>
          <option value="always" ${d.cloak_mode === 'always' ? 'selected' : ''}>始终伪装</option>
          <option value="never" ${d.cloak_mode === 'never' ? 'selected' : ''}>从不伪装</option>
        </select>
        <span class="config-desc">自动模式会检测请求来源，非 Claude Code 客户端自动伪装。</span>
      </div>
      <div class="config-row">
        <label class="config-label">
          <input type="checkbox" id="cloak-strict" ${d.cloak_strict_mode ? 'checked' : ''} />
          严格模式（剥离用户 System Prompt）
        </label>
      </div>
      <div class="config-row">
        <label class="config-label">敏感词（每行一个）</label>
        <textarea id="cloak-sensitive-words" rows="4" style="width:100%;max-width:400px">${(d.cloak_sensitive_words || []).join('\n')}</textarea>
        <span class="config-desc">请求正文中出现的这些词将被零宽字符混淆。</span>
      </div>
      <div class="config-row">
        <label class="config-label">
          <input type="checkbox" id="cloak-cache-user-id" ${d.cloak_cache_user_id !== false ? 'checked' : ''} />
          缓存 User ID
        </label>
        <span class="config-desc">按 API Key 缓存用户 ID，减少重复计算。</span>
      </div>
      <div class="config-row">
        <label class="config-label">
          <input type="checkbox" id="cloak-cch-signing" ${d.experimental_cch_signing ? 'checked' : ''} />
          实验性 CCH 签名
        </label>
        <span class="config-desc">启用实验性的 Claude Code Header 签名机制。</span>
      </div>
    </fieldset>
  </div>`;
}

function onCloakingAuthChange() {
  const authSelect = document.getElementById('cloaking-auth-select');
  const authRef = authSelect?.value || '';
  const d = cloakingData[authRef] || {};
  const mode = document.getElementById('cloak-mode');
  if (mode) mode.value = d.cloak_mode || 'auto';
  const strict = document.getElementById('cloak-strict');
  if (strict) strict.checked = d.cloak_strict_mode || false;
  const words = document.getElementById('cloak-sensitive-words');
  if (words) words.value = (d.cloak_sensitive_words || []).join('\n');
  const cache = document.getElementById('cloak-cache-user-id');
  if (cache) cache.checked = d.cloak_cache_user_id !== false;
  const cch = document.getElementById('cloak-cch-signing');
  if (cch) cch.checked = d.experimental_cch_signing || false;
}

async function saveCloakingConfig() {
  const authSelect = document.getElementById('cloaking-auth-select');
  const authRef = authSelect?.value || '';
  if (!authRef) { showMessage('请先选择一个凭证。', true); return; }
  const data = {
    auth_ref: authRef,
    cloaking_mode: document.getElementById('cloak-mode')?.value || 'auto',
    cloaking_strict_mode: document.getElementById('cloak-strict')?.checked || false,
    cloaking_sensitive_words: (document.getElementById('cloak-sensitive-words')?.value || '')
      .split('\n').map(s => s.trim()).filter(Boolean),
    cloaking_cache_user_id: document.getElementById('cloak-cache-user-id')?.checked ?? true,
    experimental_cch_signing: document.getElementById('cloak-cch-signing')?.checked || false,
  };
  try {
    const result = await api('/api/cloaking-config', 'POST', data);
    showMessage(result.message || 'Saved.');
    if (result.restart_required) showMessage('配置已保存，需要重启代理才能生效。', true);
  } catch (e) {
    showMessage(e.message, true);
  }
}
