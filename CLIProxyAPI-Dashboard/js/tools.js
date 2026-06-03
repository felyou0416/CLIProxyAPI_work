const toolNames = {
  'dashboard-script': 'Dashboard PowerShell',
  'dashboard-script-open': 'Dashboard PowerShell + Browser',
  'dashboard-bat': 'Dashboard BAT',
  'dashboard-bat-open': 'Dashboard BAT + Browser',
  'codex-login': 'Codex OAuth Login',
  'codex-device-login': 'Codex Device Login',
  'claude-login': 'Claude OAuth Login',
  'xai-login': 'xAI / Grok OAuth Login',
  'minimax-login-direct': 'MiniMax OAuth Login',
  'login': 'Gemini OAuth Login',
  'antigravity-login': 'Antigravity OAuth Login',
  'kimi-login': 'Kimi OAuth Login',
  'tui': 'TUI Management Interface',
  'help': 'Help',
};

const toolPollers = {};

function updateToolCommandHints(status) {
  if (!status) return;
  const exe = status.cli_exe || 'cli-proxy-api.exe';
  const cfg = status.base_config || '';
  document.querySelectorAll('[data-cli-tool]').forEach((node) => {
    const args = node.getAttribute('data-cli-tool') || '';
    node.textContent = cfg ? `${exe} ${args} -config ${cfg}` : `${exe} ${args}`.trim();
  });
  const hint = document.getElementById('runtime-roots-hint');
  if (hint) {
    const proxyRoot = status.proxy_root || '-';
    const dashRoot = status.dashboard_root || '-';
    hint.textContent = `代理项目: ${proxyRoot}  |  面板项目: ${dashRoot}`;
  }
}

async function runTool(toolId, btn) {
  const logEl = document.getElementById('log-' + toolId);
  const statusEl = document.getElementById('status-' + toolId);
  if (!logEl || !statusEl) { console.error('Missing elements for tool:', toolId); return; }
  if (toolPollers[toolId]) {
    showMessage(`${toolId} is already running`, true);
    return;
  }
  setLogVisible(logEl, true);
  logEl.textContent = t('common.starting', 'Starting...');
  try {
    const r = await api('/api/run-tool', 'POST', { tool: toolId });
    statusEl.textContent = t('running', 'Running');
    statusEl.className = 'tool-status tool-running';
    if (btn) btn.disabled = true;
    toolPollers[toolId] = { cancelled: false };
    tailToolLog(toolId, btn, toolPollers[toolId]);
    showMessage(r.message || `${toolId} started`);
  } catch (e) {
    logEl.textContent = 'Error:' + e.message;
    statusEl.textContent = t('stopped', 'Not running');
    statusEl.className = 'tool-status tool-stopped';
    if (btn) btn.disabled = false;
    delete toolPollers[toolId];
  }
}

async function tailToolLog(toolId, btn, poller) {
  const logEl = document.getElementById('log-' + toolId);
  const statusEl = document.getElementById('status-' + toolId);
  while (!poller.cancelled) {
    await new Promise(r => setTimeout(r, 2000));
    try {
      const r = await api('/api/tool-output', 'GET');
      const out = r.outputs?.[toolId];
      const state = r.states?.[toolId] || {};
      const running = !!state.running;
      if (out !== undefined) {
        logEl.textContent = out || t('common.noOutput', '(no output)');
        setLogVisible(logEl, true);
      }
      if (!running) {
        let summary;
        if (state.error) {
          summary = `Finished (error: ${state.error})`;
        } else if (state.returncode !== undefined && state.returncode !== null) {
          summary = `Finished (exit ${state.returncode})`;
        } else {
          summary = 'Finished';
        }
        statusEl.textContent = summary;
        statusEl.className = 'tool-status tool-stopped';
        if (btn) btn.disabled = false;
        delete toolPollers[toolId];
        break;
      } else {
        statusEl.textContent = t('running', 'Running');
        statusEl.className = 'tool-status tool-running';
      }
    } catch (e) {
      logEl.textContent = 'Polling error: ' + e.message;
      setLogVisible(logEl, true);
    }
  }
}

async function stopTool(toolId, btn) {
  try {
    await api('/api/stop-tool', 'POST', { tool: toolId });
    if (toolPollers[toolId]) {
      toolPollers[toolId].cancelled = true;
      delete toolPollers[toolId];
    }
    const statusEl = document.getElementById('status-' + toolId);
    statusEl.textContent = t('stopped', 'Not running');
    statusEl.className = 'tool-status tool-stopped';
    if (btn) btn.disabled = false;
  } catch (e) { alert(e.message); }
}

async function queryModels() {
  const el = document.getElementById('log-models');
  setLogVisible(el, true);
  el.textContent = t('common.querying', 'Querying...');
  try {
    const r = await api('/api/query-models', 'GET');
    el.textContent = JSON.stringify(r, null, 2);
  } catch (e) { el.textContent = 'Error:' + e.message; }
}

async function testProxy() {
  const el = document.getElementById('log-test');
  setLogVisible(el, true);
  el.textContent = t('common.sending', 'Sending...');
  try {
    const r = await api('/api/test-proxy', 'GET');
    el.textContent = JSON.stringify(r, null, 2);
  } catch (e) { el.textContent = 'Error:' + e.message; }
}

function storageCleanupOptions(apply) {
  return {
    apply: !!apply,
    include_old_auth: !!document.getElementById('cleanup-include-old-auth')?.checked,
    include_archived_error_logs: !!document.getElementById('cleanup-include-archived-error-logs')?.checked,
    include_logs: !!document.getElementById('cleanup-include-logs')?.checked,
    include_backups: !!document.getElementById('cleanup-include-backups')?.checked,
    include_generated_images: !!document.getElementById('cleanup-include-generated-images')?.checked,
  };
}

async function runStorageCleanup(apply = false, btn = null) {
  const el = document.getElementById('log-storage-cleanup');
  if (!el) return;
  const payload = storageCleanupOptions(apply);
  if (apply && !confirm('确定执行清理？当前勾选的候选项会被删除。')) return;
  setLogVisible(el, true);
  el.textContent = apply ? 'Cleaning...' : 'Previewing...';
  if (btn) btn.disabled = true;
  try {
    const result = await api('/api/storage-cleanup', 'POST', payload);
    el.textContent = result.output || result.message || 'Done.';
    showMessage(result.message || (apply ? 'Cleanup completed.' : 'Cleanup preview completed.'));
  } catch (e) {
    el.textContent = 'Error: ' + e.message;
    showMessage(e.message, true);
  } finally {
    if (btn) btn.disabled = false;
  }
}

async function loadRoutePreview() {
  const input = document.getElementById('route-preview-model');
  const el = document.getElementById('log-route-preview');
  const model = String(input?.value || '').trim();
  if (!model) {
    showMessage('请先填写 model ID。', true);
    return;
  }
  setLogVisible(el, true);
  el.textContent = 'Loading...';
  try {
    const r = await api(`/api/model-route-preview?model=${encodeURIComponent(model)}`, 'GET');
    const item = r.item || {};
    const matched = Array.isArray(item.matched_auths) ? item.matched_auths : [];
    const summary = {
      model_id: item.model_id,
      strategy: item.strategy,
      matched_count: item.matched_count,
      explanation: matched.length > 1
        ? 'This model is routed across the matched auth entries in round-robin order.'
        : matched.length === 1
          ? 'This model currently resolves to a single auth entry.'
          : 'No auth entry in the current pool matches this model.',
      matched_auths: matched.map(entry => ({
        name: entry.name,
        provider: entry.provider,
        email: entry.email,
        account_id: entry.account_id,
        manual: entry.manual,
        key_fingerprint: entry.key_fingerprint ? `******${entry.key_fingerprint}` : null,
        upstream_ids: (entry.matches || []).map(match => match.upstream_id),
      })),
    };
    el.textContent = JSON.stringify(summary, null, 2);
  } catch (e) {
    el.textContent = 'Error: ' + e.message;
    showMessage(e.message, true);
  }
}

async function runDashboardScript(mode = 'ps') {
  const logEl = document.getElementById('dashboard-script-log');
  if (logEl) {
    setLogVisible(logEl, true);
    logEl.textContent = 'Running...';
  }
  const toolMap = {
    'ps': 'dashboard-script',
    'ps-open': 'dashboard-script-open',
    'bat': 'dashboard-bat',
    'bat-open': 'dashboard-bat-open',
  };
  const tool = toolMap[mode] || 'dashboard-script';
  try {
    const result = await api('/api/run-tool', 'POST', { tool });
    showMessage(result.message || 'Launch script triggered');
    if (logEl) tailToolLogSimple(tool, logEl);
  } catch (err) {
    if (logEl) logEl.textContent = 'Launch failed: ' + err.message;
    showMessage(err.message, true);
  }
}

async function stopDashboardPanel() {
  const logEl = document.getElementById('dashboard-script-log');
  const statusEl = document.getElementById('status-dashboard-panel');
  if (!confirm('确定停止 Dashboard 面板？停止后当前页面会断开。')) return;
  if (logEl) {
    setLogVisible(logEl, true);
    logEl.textContent = 'Stopping dashboard panel...';
  }
  try {
    const result = await api('/api/dashboard/stop', 'POST', {});
    showMessage(result.message || 'Dashboard panel is stopping.');
    if (statusEl) {
      statusEl.textContent = 'Stopping';
      statusEl.className = 'tool-status tool-stopped';
    }
    if (logEl) logEl.textContent = 'Dashboard panel is stopping. Restart it with start_dashboard.ps1.';
  } catch (err) {
    if (logEl) logEl.textContent = 'Stop failed: ' + err.message;
    showMessage(err.message || '停止面板失败。', true);
  }
}

async function restartDashboardPanel() {
  const logEl = document.getElementById('dashboard-script-log');
  if (!confirm('确定重启 Dashboard 面板？重启期间页面将断开，随后会自动尝试重新连接。')) return;
  if (logEl) {
    setLogVisible(logEl, true);
    logEl.textContent = 'Restarting dashboard panel...';
  }
  try {
    const result = await api('/api/dashboard/restart', 'POST', {});
    showMessage(result.message || 'Dashboard panel is restarting...');
    if (logEl) logEl.textContent = 'Dashboard panel is restarting. Reconnecting in 3 seconds...';
    setTimeout(() => {
      window.location.reload();
    }, 3000);
  } catch (err) {
    if (logEl) logEl.textContent = 'Restart failed: ' + err.message;
    showMessage(err.message || '重启面板失败。', true);
  }
}


async function tailToolLogSimple(toolId, logEl) {
  for (let i = 0; i < 15; i++) {
    await new Promise(r => setTimeout(r, 2000));
    try {
      const r = await api('/api/tool-output', 'GET');
      const out = r.outputs?.[toolId];
      const state = r.states?.[toolId] || {};
      if (out !== undefined) {
        logEl.textContent = out || t('common.noOutput', '(no output)');
        setLogVisible(logEl, true);
      }
      if (!state.running) {
        break;
      }
    } catch (e) {
      logEl.textContent = 'Polling error: ' + e.message;
      setLogVisible(logEl, true);
      break;
    }
  }
}

async function runVertexImport() {
  const fileInput = document.getElementById('vertex-sa-key-file');
  const prefixInput = document.getElementById('vertex-import-prefix');
  const logEl = document.getElementById('log-vertex-import');
  if (!fileInput?.files?.length) {
    showMessage('请先选择 Vertex SA Key JSON 文件。', true);
    return;
  }
  const file = fileInput.files[0];
  try {
    const text = await file.text();
    const result = await api('/api/vertex-import', 'POST', {
      path: file.name,
      prefix: prefixInput?.value?.trim() || '',
      content: text,
    });
    showMessage(result.message || 'Vertex SA key staged.');
    if (logEl) {
      logEl.classList.remove('is-hidden');
      logEl.textContent = result.message || 'Key staged. Run the vertex-import tool to complete.';
    }
    await loadAuthFiles();
  } catch (e) {
    showMessage(e.message, true);
  }
}

async function copyDocText(btn, text) {
  if (!text) return;
  try {
    await navigator.clipboard.writeText(text);
    btn.classList.add('copied');
    const originalText = btn.textContent;
    btn.textContent = '已复制';
    setTimeout(() => {
      btn.classList.remove('copied');
      btn.textContent = originalText;
    }, 1500);
  } catch (err) {
    // Fallback using temp textarea
    const ta = document.createElement('textarea');
    ta.value = text;
    ta.style.position = 'fixed';
    ta.style.opacity = '0';
    document.body.appendChild(ta);
    ta.select();
    try {
      document.execCommand('copy');
      btn.classList.add('copied');
      const originalText = btn.textContent;
      btn.textContent = '已复制';
      setTimeout(() => {
        btn.classList.remove('copied');
        btn.textContent = originalText;
      }, 1500);
    } catch (e) {
      alert('复制失败，请手动复制：' + text);
    }
    document.body.removeChild(ta);
  }
}
