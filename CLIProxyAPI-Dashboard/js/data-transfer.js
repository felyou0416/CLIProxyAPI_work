async function exportData() {
  const statusEl = document.getElementById('export-status');
  const detailEl = document.getElementById('export-detail');
  const exportBtn = document.getElementById('export-btn');
  statusEl.textContent = '正在导出...';
  statusEl.className = 'status-line';
  detailEl.style.display = 'none';
  if (exportBtn) { exportBtn.disabled = true; exportBtn.textContent = '导出中...'; }
  try {
    const resp = await fetch('/api/data/export');
    if (!resp.ok) {
      statusEl.textContent = '导出失败: HTTP ' + resp.status;
      statusEl.className = 'status-line error';
      return;
    }
    const data = await resp.json();
    if (!data.ok) {
      statusEl.textContent = '导出失败: ' + (data.message || '未知错误');
      statusEl.className = 'status-line error';
      return;
    }

    // Count what was exported
    const items = data.data || data;  // new format: data.data, old format: top-level
    const counts = [];
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

    detailEl.style.display = 'block';
    detailEl.innerHTML = counts.length
      ? counts.map(c => '<span class="item-ok">' + c + '</span>').join(' · ')
      : '无数据';

    const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    const ts = new Date().toISOString().replace(/[:.]/g, '-').slice(0, 19);
    a.href = url;
    a.download = 'cliproxyapi-export-' + ts + '.json';
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
    statusEl.textContent = '导出成功，文件已下载。';
    statusEl.className = 'status-line success';
  } catch (e) {
    statusEl.textContent = '导出失败: ' + e.message;
    statusEl.className = 'status-line error';
  } finally {
    if (exportBtn) { exportBtn.disabled = false; exportBtn.textContent = '导出 JSON'; }
  }
}

async function handleImportFile(event) {
  const file = event.target.files[0];
  if (!file) return;
  event.target.value = '';
  const statusEl = document.getElementById('import-status');
  const detailEl = document.getElementById('import-detail');
  const importBtn = document.getElementById('import-btn');
  statusEl.textContent = '正在读取文件...';
  statusEl.className = 'status-line';
  detailEl.style.display = 'none';
  try {
    const text = await file.text();
    const payload = JSON.parse(text);
    if (!payload.version) {
      statusEl.textContent = '无效的导出文件格式（缺少 version 字段）。';
      statusEl.className = 'status-line error';
      return;
    }

    // Count items in file
    const items = payload.data || payload;
    const previewCounts = [];
    if (Array.isArray(items.auth_entries)) previewCounts.push(previewCounts.length + ' 个认证');
    if (Array.isArray(items.api_keys)) previewCounts.push(previewCounts.length + ' 个 Key');
    if (items.runtime_config) previewCounts.push('运行时配置');
    if (items.base_config) previewCounts.push('基础配置');

    const mode = document.querySelector('input[name="import-mode"]:checked')?.value || 'merge';
    const modeLabel = mode === 'replace' ? '替换' : '合并';

    if (importBtn) { importBtn.disabled = true; importBtn.textContent = '导入中...'; }
    statusEl.textContent = '正在导入（' + modeLabel + '模式，共 ' + previewCounts.length + ' 项）...';

    const resp = await fetch('/api/data/import', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ mode, payload }),
    });
    const result = await resp.json();

    // Build detail display
    const lines = [];
    if (Array.isArray(result.imported) && result.imported.length) {
      lines.push(result.imported.map(i => '<span class="item-ok">+ ' + i + '</span>').join('<br>'));
    }
    if (Array.isArray(result.skipped) && result.skipped.length) {
      lines.push(result.skipped.map(s => '<span class="item-skip">- ' + s + '</span>').join('<br>'));
    }
    if (Array.isArray(result.errors) && result.errors.length) {
      lines.push(result.errors.map(e => '<span class="item-err">! ' + e + '</span>').join('<br>'));
    }
    if (lines.length) {
      detailEl.style.display = 'block';
      detailEl.innerHTML = lines.join('<br>');
    }

    if (result.ok) {
      statusEl.textContent = result.message || '导入成功';
      statusEl.className = 'status-line success';
    } else {
      statusEl.textContent = result.message || '导入部分失败';
      statusEl.className = 'status-line error';
    }
  } catch (e) {
    statusEl.textContent = '导入失败: ' + e.message;
    statusEl.className = 'status-line error';
  } finally {
    if (importBtn) { importBtn.disabled = false; importBtn.textContent = '选择文件并导入'; }
  }
}
