/**
 * Model Load Balancer Pool (自动保存极简面板) Frontend Controller
 */

let modelPoolsData = [];
let activeModelPoolId = null;
let autoSaveTimer = null;
let modelPoolSaveInFlight = false;
let modelPoolSavePending = false;

function triggerAutoSave(delayMs = 500) {
  setAutosaveIndicator('saving');
  if (autoSaveTimer) clearTimeout(autoSaveTimer);
  autoSaveTimer = setTimeout(() => {
    saveActiveModelPoolSilently();
  }, delayMs);
}

function setAutosaveIndicator(status) {
  const el = document.getElementById('model-pool-autosave-indicator');
  if (!el) return;
  if (status === 'saving') {
    el.textContent = '⏳ 自动保存中...';
    el.style.color = 'var(--accent, #4f8cff)';
  } else if (status === 'saved') {
    el.textContent = '✓ 已保存，启动后生效';
    el.style.color = 'var(--success, #10b981)';
  } else if (status === 'reloaded') {
    el.textContent = '✓ 已保存并热加载';
    el.style.color = 'var(--success, #10b981)';
  } else if (status === 'error') {
    el.textContent = '✗ 自动保存失败';
    el.style.color = 'var(--danger, #ef4444)';
  }
}

async function loadModelPools(force = false) {
  try {
    const res = await fetch('/api/model-pools').then(r => r.json());
    if (res && res.ok && Array.isArray(res.items)) {
      modelPoolsData = res.items;
    } else {
      modelPoolsData = [];
    }
    renderModelPoolSidebar();

    if (modelPoolsData.length > 0) {
      if (!activeModelPoolId || !modelPoolsData.find(p => p.id === activeModelPoolId)) {
        activeModelPoolId = modelPoolsData[0].id;
      }
      selectModelPool(activeModelPoolId);
    } else {
      activeModelPoolId = null;
      showEmptyModelPoolDetail();
    }
  } catch (err) {
    console.error('Failed to load model pools:', err);
    if (typeof showMessage === 'function') {
      showMessage(`加载模型失败: ${err.message}`, true);
    }
  }
}

function renderModelPoolSidebar() {
  const container = document.getElementById('model-pool-sidebar-list');
  if (!container) return;

  if (modelPoolsData.length === 0) {
    container.innerHTML = `<div style="padding: 16px 8px; text-align: center; color: var(--text-muted); font-size: 12px;">暂无模型</div>`;
    return;
  }

  container.innerHTML = modelPoolsData.map(pool => {
    const isActive = pool.id === activeModelPoolId;
    const activeNodes = (pool.nodes || []).filter(n => n.enabled !== false).length;
    const callId = pool.call_id || '未命名';

    return `
      <div class="provider-tab-item ${isActive ? 'active' : ''}" onclick="selectModelPool('${pool.id}')" style="cursor: pointer; padding: 8px 10px; border-radius: 6px; margin-bottom: 4px; border: 1px solid ${isActive ? 'var(--accent)' : 'transparent'}; background: ${isActive ? 'var(--panel-2)' : 'transparent'}; font-size: 13px; font-weight: 700; display: flex; align-items: center; justify-content: space-between;">
        <span style="overflow: hidden; text-overflow: ellipsis; white-space: nowrap;">${escapeHtml(callId)}</span>
        <span style="font-size: 10px; opacity: 0.7;">${activeNodes} 节点</span>
      </div>
    `;
  }).join('');
}

function showEmptyModelPoolDetail() {
  const emptyState = document.getElementById('model-pool-empty-state');
  const detailForm = document.getElementById('model-pool-detail-form');
  if (emptyState) emptyState.style.display = 'block';
  if (detailForm) detailForm.style.display = 'none';
}

function selectModelPool(id) {
  if (activeModelPoolId && activeModelPoolId !== id) {
    syncActivePoolFromDOM();
  }

  activeModelPoolId = id;
  renderModelPoolSidebar();

  const pool = modelPoolsData.find(p => p.id === id);
  if (!pool) {
    showEmptyModelPoolDetail();
    return;
  }

  const emptyState = document.getElementById('model-pool-empty-state');
  const detailForm = document.getElementById('model-pool-detail-form');
  if (emptyState) emptyState.style.display = 'none';
  if (detailForm) detailForm.style.display = 'flex';

  document.getElementById('pool-input-call-id').value = pool.call_id || '';
  renderModelPoolPresets(pool);
  renderModelPoolNodes(pool.nodes || []);
}

function renderModelPoolPresets(pool) {
  const container = document.getElementById('model-pool-presets-container');
  if (!container) return;
  const presets = Array.isArray(pool.presets) ? pool.presets : [];
  container.innerHTML = presets.length ? presets.map((preset, index) => `
    <div class="model-pool-preset-row" data-preset-index="${index}" style="display:flex;align-items:center;gap:8px;">
      <label style="display:flex;flex-direction:column;gap:3px;flex:1;font-size:11px;color:var(--text-muted);">预设 ID（内部路由标识）
        <input class="preset-input-id" value="${escapeHtml(preset.preset_id || '')}" placeholder="preset_id" style="height:28px;padding:0 8px;">
      </label>
      <label style="display:flex;flex-direction:column;gap:3px;flex:1;font-size:11px;color:var(--text-muted);">额外调用别名
        <input class="preset-input-call-id" value="${escapeHtml(preset.call_id || preset.preset_id || '')}" placeholder="额外调用别名" style="height:28px;padding:0 8px;">
      </label>
      <button type="button" class="secondary" style="align-self:flex-end;padding:2px 7px;color:var(--danger,#ef4444);" onclick="removeModelPoolPreset(${index})">删除</button>
    </div>`).join('') : `<span style="font-size:11px;color:var(--text-muted);">未配置额外别名，当前仅使用对外模型名称。</span>`;
  container.querySelectorAll('.model-pool-preset-row input').forEach(input => input.addEventListener('input', () => {
    syncModelPoolPresetsFromDOM(pool);
    triggerAutoSave();
  }));
}

function syncModelPoolPresetsFromDOM(pool) {
  const rows = document.querySelectorAll('#model-pool-presets-container .model-pool-preset-row');
  pool.presets = Array.from(rows).map((row, index) => {
    const old = (pool.presets || [])[index] || {};
    const presetId = row.querySelector('.preset-input-id').value.trim();
    const callId = row.querySelector('.preset-input-call-id').value.trim() || presetId;
    return { ...old, preset_id: presetId || callId, call_id: callId, enabled: old.enabled !== false, node_refs: old.node_refs || [] };
  }).filter(preset => preset.preset_id);
}

function addModelPoolPreset() {
  const pool = modelPoolsData.find(p => p.id === activeModelPoolId);
  if (!pool) return;
  syncActivePoolFromDOM();
  pool.presets = Array.isArray(pool.presets) ? pool.presets : [];
  const presetId = `${pool.call_id || 'model'}-${pool.presets.length + 1}`;
  const refs = (pool.nodes || []).map(node => ({ node_ref: node.node_ref || node.id, weight: node.weight || 1, enabled: node.enabled !== false, upstream_id: node.upstream_id || '' }));
  pool.presets.push({ preset_id: presetId, call_id: presetId, enabled: true, node_refs: refs });
  renderModelPoolPresets(pool);
  saveActiveModelPoolSilently();
}

function removeModelPoolPreset(index) {
  const pool = modelPoolsData.find(p => p.id === activeModelPoolId);
  if (!pool || !Array.isArray(pool.presets)) return;
  pool.presets.splice(index, 1);
  renderModelPoolPresets(pool);
  saveActiveModelPoolSilently();
}

function syncPoolCallId(val) {
  const pool = modelPoolsData.find(p => p.id === activeModelPoolId);
  if (pool) {
    const callId = String(val || '').trim();
    pool.call_id = callId;
    pool.provider = `pool-${callId || 'custom'}`;
    renderModelPoolSidebar();
    triggerAutoSave(600);
  }
}

function createNewModelPool() {
  syncActivePoolFromDOM();

  const newId = `pool-${Date.now()}`;
  const defaultCallId = `model-${modelPoolsData.length + 1}`;
  const newPool = {
    id: newId,
    provider: `pool-${defaultCallId}`,
    call_id: defaultCallId,
    enabled: true,
    nodes: [
      {
        id: `node-${Date.now()}-1`,
        base_url: 'https://api.openai-proxy.com/v1',
        api_key: '',
        upstream_id: defaultCallId,
        weight: 1,
        proxy_url: '',
        enabled: true
      }
    ]
  };

  modelPoolsData.push(newPool);
  selectModelPool(newId);
  saveActiveModelPoolSilently();
}

function renderModelPoolNodes(nodes) {
  const container = document.getElementById('model-pool-nodes-container');
  if (!container) return;

  if (nodes.length === 0) {
    container.innerHTML = `<div style="text-align: center; padding: 20px 0; border: 1px dashed var(--border); border-radius: 6px; color: var(--text-muted); font-size: 12px;">暂无节点，点击底部“+ 添加上游节点”</div>`;
    return;
  }

  const pool = modelPoolsData.find(p => p.id === activeModelPoolId);
  const currentCallId = pool ? (pool.call_id || '') : '';

  container.innerHTML = nodes.map((node, index) => {
    const isEnabled = node.enabled !== false;
    const upstreamModelId = node.upstream_id || currentCallId;

    return `
      <div class="node-card-item" data-node-index="${index}" style="padding: 10px 12px; border: 1px solid var(--border); border-radius: 8px; background: var(--panel-2); opacity: ${isEnabled ? '1' : '0.5'}; display: flex; flex-direction: column; gap: 8px;">
        <div style="display: flex; align-items: center; justify-content: space-between;">
          <label style="display: flex; align-items: center; gap: 6px; cursor: pointer; font-size: 12px; font-weight: 700;">
            <input class="node-input-enabled" type="checkbox" ${isEnabled ? 'checked' : ''} onchange="updateNodeFieldValue(${index}, 'enabled', this.checked); renderModelPoolNodes(modelPoolsData.find(p=>p.id===activeModelPoolId).nodes); saveActiveModelPoolSilently();" /> 节点 #${index + 1}
          </label>
          <div style="display: flex; align-items: center; gap: 6px;">
            <span id="node-test-result-${index}" style="font-size: 11px; color: var(--text-muted);"></span>
            <button type="button" class="secondary" style="min-height: 22px; padding: 0 6px; font-size: 11px;" onclick="testNodeInActivePool(${index})">测试</button>
            <button type="button" class="secondary" style="min-height: 22px; padding: 0 6px; font-size: 11px; color: var(--danger, #ef4444); border-color: var(--danger, #ef4444);" onclick="removeNodeFromActivePool(${index})">删除</button>
          </div>
        </div>

        <div style="display: grid; grid-template-columns: 2fr 2fr 1.5fr; gap: 8px;">
          <input class="node-input-url" type="text" value="${escapeHtml(node.base_url || '')}" placeholder="Base URL (例如 https://api.xxx.com/v1)" style="height: 30px; padding: 0 8px; border-radius: 4px; border: 1px solid var(--border); background: var(--panel); color: var(--text); font-size: 12px;" oninput="updateNodeFieldValue(${index}, 'base_url', this.value); triggerAutoSave();" />
          <input class="node-input-key" type="password" value="${escapeHtml(node.api_key || '')}" placeholder="API Key (sk-...)" style="height: 30px; padding: 0 8px; border-radius: 4px; border: 1px solid var(--border); background: var(--panel); color: var(--text); font-size: 12px;" oninput="updateNodeFieldValue(${index}, 'api_key', this.value); triggerAutoSave();" />
          <input class="node-input-upstream" type="text" value="${escapeHtml(upstreamModelId)}" placeholder="实际模型名（发送给上游）" style="height: 30px; padding: 0 8px; border-radius: 4px; border: 1px solid var(--border); background: var(--panel); color: var(--text); font-size: 12px;" oninput="updateNodeFieldValue(${index}, 'upstream_id', this.value); triggerAutoSave();" />
        </div>
      </div>
    `;
  }).join('');
}

function updateNodeFieldValue(index, field, value) {
  const pool = modelPoolsData.find(p => p.id === activeModelPoolId);
  if (pool && pool.nodes && pool.nodes[index]) {
    pool.nodes[index][field] = value;
  }
}

function syncActivePoolFromDOM() {
  if (!activeModelPoolId) return;
  const pool = modelPoolsData.find(p => p.id === activeModelPoolId);
  if (!pool) return;

  const callIdEl = document.getElementById('pool-input-call-id');
  if (callIdEl) {
    const callId = callIdEl.value.trim();
    pool.call_id = callId;
    if (!pool.provider) {
      pool.provider = `pool-${callId || 'custom'}`;
    }
  }

  const nodeCards = document.querySelectorAll('#model-pool-nodes-container .node-card-item');
  if (nodeCards && nodeCards.length > 0) {
    const updatedNodes = [];
    nodeCards.forEach((card, idx) => {
      const enabledEl = card.querySelector('.node-input-enabled');
      const urlEl = card.querySelector('.node-input-url');
      const keyEl = card.querySelector('.node-input-key');
      const upstreamEl = card.querySelector('.node-input-upstream');

      const origNode = (pool.nodes && pool.nodes[idx]) || {};
      const modelId = upstreamEl ? upstreamEl.value.trim() : (origNode.upstream_id || pool.call_id || '');
      updatedNodes.push({
        id: origNode.id || `node-${Date.now()}-${idx + 1}`,
        enabled: enabledEl ? enabledEl.checked : true,
        base_url: urlEl ? urlEl.value.trim() : (origNode.base_url || ''),
        api_key: keyEl ? keyEl.value.trim() : (origNode.api_key || ''),
        upstream_id: modelId,
        weight: origNode.weight || 1,
        proxy_url: origNode.proxy_url || '',
      });
    });
    pool.nodes = updatedNodes;
  }
}

function addNodeToActivePool() {
  syncActivePoolFromDOM();

  const pool = modelPoolsData.find(p => p.id === activeModelPoolId);
  if (!pool) return;
  if (!pool.nodes) pool.nodes = [];

  const currentCallId = pool.call_id || '';

  pool.nodes.push({
    id: `node-${Date.now()}-${pool.nodes.length + 1}`,
    base_url: 'https://api.openai-proxy.com/v1',
    api_key: '',
    upstream_id: currentCallId,
    weight: 1,
    proxy_url: '',
    enabled: true
  });

  renderModelPoolNodes(pool.nodes);
  saveActiveModelPoolSilently();
}

function removeNodeFromActivePool(index) {
  syncActivePoolFromDOM();

  const pool = modelPoolsData.find(p => p.id === activeModelPoolId);
  if (!pool || !pool.nodes) return;

  pool.nodes.splice(index, 1);
  renderModelPoolNodes(pool.nodes);
  saveActiveModelPoolSilently();
}

async function saveActiveModelPoolSilently() {
  const pool = modelPoolsData.find(p => p.id === activeModelPoolId);
  if (!pool) return;

  syncActivePoolFromDOM();
  if (!pool.call_id) return;
  if (!pool.provider) pool.provider = `pool-${pool.call_id}`;

  if (modelPoolSaveInFlight) {
    modelPoolSavePending = true;
    return;
  }

  modelPoolSaveInFlight = true;
  modelPoolSavePending = false;
  setAutosaveIndicator('saving');
  try {
    const payload = JSON.parse(JSON.stringify(modelPoolsData));
    const response = await fetch('/api/model-pools', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ pools: payload })
    });
    const res = await response.json();
    if (!response.ok || !res || !res.ok) {
      throw new Error(res && res.message ? res.message : `HTTP ${response.status}`);
    }
    setAutosaveIndicator(res.reload_requested ? 'reloaded' : 'saved');
  } catch (err) {
    console.error('Failed to auto-save model pool:', err);
    setAutosaveIndicator('error');
  } finally {
    modelPoolSaveInFlight = false;
    if (modelPoolSavePending) {
      modelPoolSavePending = false;
      saveActiveModelPoolSilently();
    }
  }
}

async function saveActiveModelPool() {
  await saveActiveModelPoolSilently();
}

async function deleteActiveModelPool() {
  if (!activeModelPoolId) return;
  if (!confirm('确定要删除当前模型轮询配置吗？')) return;

  try {
    const res = await fetch('/api/model-pools/delete', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ id: activeModelPoolId })
    }).then(r => r.json());

    if (res && res.ok) {
      if (typeof showMessage === 'function') {
        showMessage('删除成功');
      }
      activeModelPoolId = null;
      loadModelPools(true);
    } else {
      if (typeof showMessage === 'function') {
        showMessage(`删除失败: ${res ? res.message : '未知错误'}`, true);
      }
    }
  } catch (err) {
    console.error('Failed to delete model pool:', err);
    if (typeof showMessage === 'function') {
      showMessage(`删除异常: ${err.message}`, true);
    }
  }
}

async function testNodeInActivePool(index) {
  syncActivePoolFromDOM();

  const pool = modelPoolsData.find(p => p.id === activeModelPoolId);
  if (!pool || !pool.nodes || !pool.nodes[index]) return;

  const node = pool.nodes[index];
  const labelEl = document.getElementById(`node-test-result-${index}`);
  if (labelEl) labelEl.textContent = '测试中...';

  try {
    const res = await fetch('/api/model-pools/test-node', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        provider: pool ? pool.provider : '',
        base_url: node.base_url,
        api_key: node.api_key,
        proxy_url: node.proxy_url || '',
        model_id: node.upstream_id || (pool ? pool.call_id : '') || ''
      })
    }).then(r => r.json());

    if (labelEl) {
      if (res && res.ok) {
        labelEl.style.color = 'var(--success, #10b981)';
        labelEl.textContent = `✓ ${res.message}`;
      } else {
        labelEl.style.color = 'var(--danger, #ef4444)';
        labelEl.textContent = `✗ ${res ? res.message : '失败'}`;
      }
    }
  } catch (err) {
    if (labelEl) {
      labelEl.style.color = 'var(--danger, #ef4444)';
      labelEl.textContent = `✗ ${err.message}`;
    }
  }
}

function escapeHtml(str) {
  if (!str) return '';
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#039;');
}
