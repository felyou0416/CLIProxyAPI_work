/* Advanced Configuration */

let advancedConfigData = {};

function meEscape(value) {
  return String(value ?? '')
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#39;');
}

async function loadAdvancedConfig() {
  const content = document.getElementById('advanced-config-content');
  if (!content) return;
  try {
    const data = await api('/api/advanced-config');
    advancedConfigData = data.item || {};
    renderAdvancedConfig();
  } catch (e) {
    content.innerHTML = `<div class="metric-empty">${meEscape(e.message || 'load failed')}</div>`;
  }
}

function _buildSelect(id, value, options) {
  let html = `<select id="${id}" name="${id}" style="width:200px">`;
  for (const [val, label] of Object.entries(options)) {
    html += `<option value="${val}" ${value === val ? 'selected' : ''}>${label}</option>`;
  }
  html += '</select>';
  return html;
}

function renderAdvancedConfig() {
  const content = document.getElementById('advanced-config-content');
  const d = advancedConfigData;
  content.innerHTML = `<div class="config-section">
    <fieldset><legend>图片生成</legend>
      <div class="config-row">
        <label class="config-label">禁用图片生成</label>
        ${_buildSelect('disable-image-generation', d.disable_image_generation || 'off', {
          'off': '不禁止（允许图片生成）',
          'all': '全局禁止',
          'chat': '仅在聊天接口禁止',
        })}
      </div>
    </fieldset>

    <fieldset><legend>Session 亲和路由</legend>
      <div class="config-row">
        <label class="config-label">
          <input type="checkbox" id="session-affinity-enabled" ${d.session_affinity_enabled ? 'checked' : ''} />
          启用 Session 亲和路由
        </label>
        <span class="config-desc">同一会话的请求固定路由到同一凭证，减少上下文丢失。</span>
      </div>
      <div class="config-row">
        <label class="config-label">Session 亲和 TTL</label>
        <input type="text" id="session-affinity-ttl" value="${meEscape(d.session_affinity_ttl || '1h')}" placeholder="如 1h, 30m" style="width:120px" />
        <span class="config-desc">会话绑定关系的有效期。</span>
      </div>
    </fieldset>

    <fieldset><legend>认证与线程</legend>
      <div class="config-row">
        <label class="config-label">OAuth 刷新线程池大小</label>
        <input type="number" id="auth-auto-refresh-workers" value="${d.auth_auto_refresh_workers || 16}" min="1" max="256" style="width:80px" />
        <span class="config-desc">默认 16，范围 1-256。</span>
      </div>
    </fieldset>

    <fieldset><legend>服务开关</legend>
      <div class="config-row">
        <label class="config-label">
          <input type="checkbox" id="ws-auth" ${d.ws_auth ? 'checked' : ''} />
          WebSocket 认证
        </label>
        <span class="config-desc">启用 WebSocket API 的认证检查。</span>
      </div>
      <div class="config-row">
        <label class="config-label">
          <input type="checkbox" id="local-model" ${d.local_model ? 'checked' : ''} />
          仅使用本地模型目录
        </label>
        <span class="config-desc">禁止从远程获取模型列表（--local-model 等效）。</span>
      </div>
      <div class="config-row">
        <label class="config-label">
          <input type="checkbox" id="commercial-mode" ${d.commercial_mode ? 'checked' : ''} />
          商用模式
        </label>
        <span class="config-desc">禁用高开销的 HTTP 中间件，适用于生产环境。</span>
      </div>
    </fieldset>
  </div>`;
}

async function saveAdvancedConfig() {
  const data = {
    disable_image_generation: document.getElementById('disable-image-generation')?.value || 'off',
    session_affinity_enabled: document.getElementById('session-affinity-enabled')?.checked || false,
    session_affinity_ttl: document.getElementById('session-affinity-ttl')?.value?.trim() || '1h',
    auth_auto_refresh_workers: parseInt(document.getElementById('auth-auto-refresh-workers')?.value) || 16,
    ws_auth: document.getElementById('ws-auth')?.checked || false,
    local_model: document.getElementById('local-model')?.checked || false,
    commercial_mode: document.getElementById('commercial-mode')?.checked || false,
  };
  try {
    const result = await api('/api/advanced-config', 'POST', data);
    showMessage(result.message || 'Saved.');
    if (result.restart_required) showMessage('配置已保存，需要重启代理才能生效。', true);
  } catch (e) {
    showMessage(e.message, true);
  }
}
