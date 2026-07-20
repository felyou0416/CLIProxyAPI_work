/* System Center — data import / export (dev + packaged user installs) */

function _dtAuthHeaders() {
  const headers = {};
  const token =
    (typeof getAuthToken === 'function' && getAuthToken()) ||
    localStorage.getItem('dashboard_auth_token') ||
    '';
  if (token) headers.Authorization = 'Bearer ' + token;
  return headers;
}

function _dtEsc(value) {
  return String(value ?? '')
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;');
}

function _dtProfileLabel(profile) {
  if (profile === 'user') return '用户端 / 安装版';
  if (profile === 'dev') return '开发版';
  return profile || '未知';
}

function _dtRenderEnvBanner(env) {
  const el = document.getElementById('data-transfer-env');
  if (!el || !env) return;
  const profile = env.profile || 'unknown';
  el.hidden = false;
  el.innerHTML =
    `<strong>当前环境：</strong>${_dtEsc(_dtProfileLabel(profile))}` +
    ` · storage: <code>${_dtEsc(env.storage_dir || '')}</code>` +
    ` · ${ _dtEsc(env.runtime_variant || '') }` +
    (profile === 'user'
      ? '<div class="dt-hint">安装版数据在用户目录；从开发版导入时会自动改写 auth-dir 等绝对路径。</div>'
      : '<div class="dt-hint">开发版数据在仓库 storage；导出后可迁到安装版，导入时路径会适配目标机。</div>');
}

async function loadDataTransferPanel() {
  const el = document.getElementById('data-transfer-env');
  if (!el) return;
  try {
    let env = null;
    try {
      const res = await api('/api/data/environment');
      env = res?.item || null;
    } catch (_) {
      /* fall through */
    }
    if (!env) {
      try {
        const status = await api('/api/status');
        const item = status?.item || status || {};
        const storage = item.storage_dir || '';
        env = {
          profile:
            /AppData|userData|Application Support/i.test(storage) || item.frozen
              ? 'user'
              : 'dev',
          storage_dir: storage,
          runtime_variant: item.runtime_variant || '',
        };
      } catch (_) {
        env = { profile: 'unknown', storage_dir: '', runtime_variant: '' };
      }
    }
    _dtRenderEnvBanner(env);
  } catch (e) {
    el.hidden = false;
    el.textContent = '环境信息加载失败: ' + (e.message || e);
  }
}

function _dtCountExportItems(items) {
  const counts = [];
  if (!items || typeof items !== 'object') return counts;
  if (Array.isArray(items.auth_entries)) counts.push(`认证文件 ${items.auth_entries.length} 个`);
  if (Array.isArray(items.api_keys)) counts.push(`虚拟 Key ${items.api_keys.length} 个`);
  if (items.base_config) counts.push('基础配置');
  if (items.runtime_config) counts.push('运行时配置');
  if (items.sources_config) counts.push('认证源配置');
  if (items.state) counts.push('面板状态');
  if (items.model_overrides) counts.push('模型覆盖');
  if (items.aggregate_aliases) counts.push('聚合别名');
  if (items.model_proxy_settings) counts.push('代理设置');
  if (items.model_thinking_configs) counts.push('Thinking 配置');
  return counts;
}

async function exportData() {
  const statusEl = document.getElementById('export-status');
  const detailEl = document.getElementById('export-detail');
  const exportBtn = document.getElementById('export-btn');
  if (statusEl) {
    statusEl.textContent = '正在导出...';
    statusEl.className = 'status-line';
  }
  if (detailEl) detailEl.style.display = 'none';
  if (exportBtn) {
    exportBtn.disabled = true;
    exportBtn.textContent = '导出中...';
  }
  try {
    const resp = await fetch('/api/data/export', {
      headers: _dtAuthHeaders(),
    });
    if (!resp.ok) {
      if (statusEl) {
        statusEl.textContent = '导出失败: HTTP ' + resp.status;
        statusEl.className = 'status-line error';
      }
      return;
    }
    const data = await resp.json();
    if (!data.ok) {
      if (statusEl) {
        statusEl.textContent = '导出失败: ' + (data.message || '未知错误');
        statusEl.className = 'status-line error';
      }
      return;
    }

    if (data.environment) _dtRenderEnvBanner(data.environment);

    const items = data.data || data;
    const counts = _dtCountExportItems(items);
    if (detailEl) {
      detailEl.style.display = 'block';
      const envLine = data.environment
        ? `<div class="item-ok">环境: ${_dtEsc(_dtProfileLabel(data.environment.profile))} · v${_dtEsc(data.version)}</div>`
        : '';
      detailEl.innerHTML =
        envLine +
        (counts.length
          ? counts.map(c => '<span class="item-ok">' + _dtEsc(c) + '</span>').join(' · ')
          : '无数据');
    }

    const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    const ts = new Date().toISOString().replace(/[:.]/g, '-').slice(0, 19);
    const profile = (data.environment && data.environment.profile) || 'export';
    a.href = url;
    a.download = `cliproxyapi-export-${profile}-${ts}.json`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
    if (statusEl) {
      statusEl.textContent = '导出成功，文件已下载。';
      statusEl.className = 'status-line success';
    }
  } catch (e) {
    if (statusEl) {
      statusEl.textContent = '导出失败: ' + e.message;
      statusEl.className = 'status-line error';
    }
  } finally {
    if (exportBtn) {
      exportBtn.disabled = false;
      exportBtn.textContent = '导出 JSON';
    }
  }
}

function _dtPreviewCounts(items) {
  const preview = [];
  if (!items || typeof items !== 'object') return preview;
  if (Array.isArray(items.auth_entries)) preview.push(`认证 ${items.auth_entries.length}`);
  if (Array.isArray(items.api_keys)) preview.push(`Key ${items.api_keys.length}`);
  if (items.runtime_config) preview.push('运行时配置');
  if (items.base_config) preview.push('基础配置');
  if (items.state) preview.push('面板状态');
  if (items.model_overrides) preview.push('模型覆盖');
  if (items.aggregate_aliases) preview.push('聚合别名');
  return preview;
}

async function handleImportFile(event) {
  const file = event.target.files && event.target.files[0];
  if (!file) return;
  event.target.value = '';
  const statusEl = document.getElementById('import-status');
  const detailEl = document.getElementById('import-detail');
  const importBtn = document.getElementById('import-btn');
  if (statusEl) {
    statusEl.textContent = '正在读取文件...';
    statusEl.className = 'status-line';
  }
  if (detailEl) detailEl.style.display = 'none';
  try {
    const text = await file.text();
    const payload = JSON.parse(text);
    if (payload.version == null) {
      if (statusEl) {
        statusEl.textContent = '无效的导出文件格式（缺少 version 字段）。';
        statusEl.className = 'status-line error';
      }
      return;
    }

    const items = payload.data || payload;
    const previewCounts = _dtPreviewCounts(items);
    const mode = document.querySelector('input[name="import-mode"]:checked')?.value || 'merge';
    const modeLabel = mode === 'replace' ? '替换' : '合并';
    const srcProfile = payload.environment?.profile
      ? _dtProfileLabel(payload.environment.profile)
      : '未知来源';

    if (mode === 'replace') {
      const ok = window.confirm(
        '替换模式会清空当前可导入数据后再写入。\n' +
          `文件来源环境：${srcProfile}\n` +
          '确定继续？'
      );
      if (!ok) {
        if (statusEl) {
          statusEl.textContent = '已取消导入。';
          statusEl.className = 'status-line';
        }
        return;
      }
    }

    if (importBtn) {
      importBtn.disabled = true;
      importBtn.textContent = '导入中...';
    }
    if (statusEl) {
      statusEl.textContent =
        `正在导入（${modeLabel} · ${srcProfile} · ${previewCounts.length || 0} 类）...`;
    }

    const headers = Object.assign({ 'Content-Type': 'application/json' }, _dtAuthHeaders());
    const resp = await fetch('/api/data/import', {
      method: 'POST',
      headers,
      body: JSON.stringify({ mode, payload }),
    });
    const result = await resp.json().catch(() => ({}));

    const lines = [];
    if (result.target_environment) {
      lines.push(
        `<span class="item-ok">目标: ${_dtEsc(_dtProfileLabel(result.target_environment.profile))}</span>`
      );
    }
    if (Array.isArray(result.imported) && result.imported.length) {
      lines.push(result.imported.map(i => '<span class="item-ok">+ ' + _dtEsc(i) + '</span>').join('<br>'));
    }
    if (Array.isArray(result.skipped) && result.skipped.length) {
      lines.push(result.skipped.map(s => '<span class="item-skip">- ' + _dtEsc(s) + '</span>').join('<br>'));
    }
    if (Array.isArray(result.warnings) && result.warnings.length) {
      lines.push(result.warnings.map(w => '<span class="item-skip">~ ' + _dtEsc(w) + '</span>').join('<br>'));
    }
    if (Array.isArray(result.errors) && result.errors.length) {
      lines.push(result.errors.map(e => '<span class="item-err">! ' + _dtEsc(e) + '</span>').join('<br>'));
    }
    if (result.restart_recommended) {
      lines.push('<span class="item-skip">建议重启代理以使运行时配置生效</span>');
    }
    if (detailEl && lines.length) {
      detailEl.style.display = 'block';
      detailEl.innerHTML = lines.join('<br>');
    }

    if (statusEl) {
      if (result.ok) {
        statusEl.textContent = result.message || '导入成功';
        statusEl.className = 'status-line success';
      } else {
        statusEl.textContent = result.message || '导入部分失败';
        statusEl.className = 'status-line error';
      }
    }
  } catch (e) {
    if (statusEl) {
      statusEl.textContent = '导入失败: ' + e.message;
      statusEl.className = 'status-line error';
    }
  } finally {
    if (importBtn) {
      importBtn.disabled = false;
      importBtn.textContent = '选择文件并导入';
    }
  }
}
