async function exportData() {
  const statusEl = document.getElementById('export-status');
  statusEl.textContent = '正在导出...';
  statusEl.className = 'status-line';
  try {
    const resp = await fetch('/api/data/export');
    const data = await resp.json();
    if (!data.ok) {
      statusEl.textContent = '导出失败: ' + (data.message || '未知错误');
      statusEl.className = 'status-line error';
      return;
    }
    const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    const ts = new Date().toISOString().replace(/[:.]/g, '-').slice(0, 19);
    a.href = url;
    a.download = `cliproxyapi-export-${ts}.json`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
    statusEl.textContent = '导出成功，文件已下载。';
    statusEl.className = 'status-line success';
  } catch (e) {
    statusEl.textContent = '导出失败: ' + e.message;
    statusEl.className = 'status-line error';
  }
}

async function handleImportFile(event) {
  const file = event.target.files[0];
  if (!file) return;
  event.target.value = '';
  const statusEl = document.getElementById('import-status');
  statusEl.textContent = '正在读取文件...';
  statusEl.className = 'status-line';
  try {
    const text = await file.text();
    const payload = JSON.parse(text);
    if (!payload.version) {
      statusEl.textContent = '无效的导出文件格式。';
      statusEl.className = 'status-line error';
      return;
    }
    const mode = document.querySelector('input[name="import-mode"]:checked')?.value || 'merge';
    statusEl.textContent = `正在导入（${mode === 'replace' ? '替换' : '合并'}模式）...`;
    const resp = await fetch('/api/data/import', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ mode, payload }),
    });
    const result = await resp.json();
    if (result.ok) {
      statusEl.textContent = '导入成功: ' + (result.message || '');
      statusEl.className = 'status-line success';
    } else {
      statusEl.textContent = '导入部分失败: ' + (result.message || '');
      statusEl.className = 'status-line error';
    }
  } catch (e) {
    statusEl.textContent = '导入失败: ' + e.message;
    statusEl.className = 'status-line error';
  }
}
