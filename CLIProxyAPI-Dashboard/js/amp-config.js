/* AMP Integration Configuration */

let ampConfigData = {};

function _ae(value) {
  return String(value ?? '')
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#39;');
}

async function loadAmpConfig() {
  const content = document.getElementById('amp-config-content');
  if (!content) return;
  try {
    const data = await api('/api/amp-config');
    ampConfigData = data.item || {};
    renderAmpConfig();
  } catch (e) {
    content.innerHTML = `<div class="metric-empty">${_ae(e.message || 'load failed')}</div>`;
  }
}

function renderAmpConfig() {
  const content = document.getElementById('amp-config-content');
  const d = ampConfigData;
  const mappingsRows = (d.amp_model_mappings || []).map((m, i) =>
    `<tr>
      <td><input id="amp-mapping-from-${i}" value="${_ae(m.from || '')}" placeholder="如: claude-opus-4.5" /></td>
      <td><input id="amp-mapping-to-${i}" value="${_ae(m.to || '')}" placeholder="如: claude-sonnet-4" /></td>
      <td><label><input type="checkbox" id="amp-mapping-regex-${i}" ${m.regex ? 'checked' : ''} /> 正则</label></td>
      <td><button class="secondary" onclick="removeAmpMapping(${i})">删除</button></td>
    </tr>`).join('');

  content.innerHTML = `<div class="config-section">
    <fieldset><legend>上游连接</legend>
      <div class="config-row">
        <label class="config-label">上游 URL</label>
        <input type="text" id="amp-upstream-url" value="${_ae(d.amp_upstream_url || '')}" placeholder="https://amp.example.com" style="width:100%;max-width:400px" />
      </div>
      <div class="config-row">
        <label class="config-label">上游 API Key</label>
        <input type="password" id="amp-upstream-key" placeholder="${d.amp_upstream_api_key_set ? '(已设置，留空保持不变)' : '输入 API Key'}" style="width:100%;max-width:400px" />
      </div>
      <div class="config-row">
        <label class="config-label">
          <input type="checkbox" id="amp-restrict-localhost" ${d.amp_restrict_localhost !== false ? 'checked' : ''} />
          限制管理路由仅本地访问
        </label>
      </div>
      <div class="config-row">
        <label class="config-label">
          <input type="checkbox" id="amp-force-mappings" ${d.amp_force_model_mappings ? 'checked' : ''} />
          强制模型映射（优先于本地 API Key）
        </label>
      </div>
    </fieldset>

    <fieldset><legend>模型映射</legend>
      <table class="metric-table"><thead><tr><th>From（Amp CLI 请求的模型）</th><th>To（本地可用模型）</th><th>正则</th><th></th></tr></thead>
      <tbody id="amp-mappings-tbody">${mappingsRows || '<tr><td colspan="4">暂无映射</td></tr>'}</tbody></table>
      <button class="secondary" onclick="addAmpMapping()" style="margin-top:8px">添加映射</button>
    </fieldset>
  </div>`;
}

async function saveAmpConfig() {
  const mappings = [];
  const rows = document.querySelectorAll('#amp-mappings-tbody tr');
  rows.forEach((row, i) => {
    const from = document.getElementById(`amp-mapping-from-${i}`)?.value?.trim();
    const to = document.getElementById(`amp-mapping-to-${i}`)?.value?.trim();
    if (from && to) {
      mappings.push({
        from, to,
        regex: document.getElementById(`amp-mapping-regex-${i}`)?.checked || false
      });
    }
  });

  const upstreamKey = document.getElementById('amp-upstream-key')?.value?.trim();
  const item = {
    amp_upstream_url: document.getElementById('amp-upstream-url')?.value?.trim() || '',
    amp_restrict_localhost: document.getElementById('amp-restrict-localhost')?.checked !== false,
    amp_force_model_mappings: document.getElementById('amp-force-mappings')?.checked || false,
    amp_model_mappings: mappings,
  };
  if (upstreamKey) item.amp_upstream_api_key = upstreamKey;

  try {
    const result = await api('/api/amp-config', 'POST', { item });
    showMessage(result.message || 'Saved.');
    if (result.restart_required) showMessage('配置已保存，需要重启代理才能生效。', true);
  } catch (e) {
    showMessage(e.message, true);
  }
}

function addAmpMapping() {
  ampConfigData.amp_model_mappings = ampConfigData.amp_model_mappings || [];
  ampConfigData.amp_model_mappings.push({ from: '', to: '', regex: false });
  renderAmpConfig();
}

function removeAmpMapping(index) {
  ampConfigData.amp_model_mappings.splice(index, 1);
  renderAmpConfig();
}
