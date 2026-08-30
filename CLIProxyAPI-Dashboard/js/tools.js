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
let toolsVersionLoaded = false;

function setToolResultState(id, result, fallback = '') {
  const el = document.getElementById(id);
  if (!el) return;
  const ok = result && result.ok !== false;
  el.classList.toggle('tool-result-ok', ok);
  el.classList.toggle('tool-result-error', !ok);
  const prefix = ok ? '完成' : '失败';
  const message = result?.message || result?.error || fallback;
  el.dataset.resultState = ok ? 'ok' : 'error';
  el.dataset.resultLabel = message ? `${prefix} · ${message}` : prefix;
}

async function loadToolsVersion() {
  if (toolsVersionLoaded) return;
  toolsVersionLoaded = true;
  try {
    const response = await api('/api/version', 'GET');
    const item = response?.item || {};
    const version = item.cli_version || item.version || '未读取';
    const el = document.getElementById('tools-core-version');
    if (el) el.textContent = version;
  } catch (error) {
    const el = document.getElementById('tools-core-version');
    if (el) el.textContent = '读取失败';
    console.warn('Unable to load CPA version:', error);
  }
}

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
    hint.textContent = `${proxyRoot} · ${dashRoot}`;
    hint.title = `代理项目: ${proxyRoot} | 面板项目: ${dashRoot}`;
  }
  loadToolsVersion();
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
    setToolResultState('log-models', r, Array.isArray(r?.data) ? `${r.data.length} 个模型` : '模型目录已返回');
    showMessage(r?.ok === false ? (r.message || '模型目录读取失败') : '模型目录已更新');
  } catch (e) {
    el.textContent = 'Error:' + e.message;
    setToolResultState('log-models', {ok: false, error: e.message});
    showMessage(e.message, true);
  }
}

async function testProxy() {
  const el = document.getElementById('log-test');
  setLogVisible(el, true);
  el.textContent = t('common.sending', 'Sending...');
  try {
    const r = await api('/api/test-proxy', 'GET');
    el.textContent = JSON.stringify(r, null, 2);
    setToolResultState('log-test', r, '代理测试已返回');
    showMessage(r?.ok === false ? (r.message || '代理测试失败') : '代理测试完成');
  } catch (e) {
    el.textContent = 'Error:' + e.message;
    setToolResultState('log-test', {ok: false, error: e.message});
    showMessage(e.message, true);
  }
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

// 面板自身启停：不走通用 /api/*-project，需处理确认框 / reload
// button 可选；控制台会传入，以便 withRuntimeAction 显示组内 spinner
async function runDashboardScript(mode = 'ps', button) {
  const run = async () => {
    // 面板指示灯同样走 cli-indicator-states 缓存
    if (typeof window.updateIndicator === 'function') {
      window.updateIndicator('dashboard', 'yellow');
    }
    window.dashboardActionBusy = true;
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
      if (logEl) await tailToolLogSimple(tool, logEl);
    } catch (err) {
      if (logEl) logEl.textContent = 'Launch failed: ' + err.message;
      showMessage(err.message, true);
    } finally {
      window.dashboardActionBusy = false;
      if (typeof window.updateIndicator === 'function') {
        window.updateIndicator('dashboard', 'green');
      }
    }
  };
  if (button && typeof withRuntimeAction === 'function') {
    return withRuntimeAction(button, '启动', run);
  }
  return run();
}

async function stopDashboardPanel(button) {
  if (!confirm('确定停止 Dashboard 面板？停止后当前页面会断开。')) return;
  const run = async () => {
    const logEl = document.getElementById('dashboard-script-log');
    const statusEl = document.getElementById('status-dashboard-panel');
    if (typeof window.updateIndicator === 'function') {
      window.updateIndicator('dashboard', 'yellow');
    }
    window.dashboardActionBusy = true;
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
      if (typeof window.updateIndicator === 'function') {
        window.updateIndicator('dashboard', 'red');
      }
    } catch (err) {
      if (logEl) logEl.textContent = 'Stop failed: ' + err.message;
      showMessage(err.message || '停止面板失败。', true);
      window.dashboardActionBusy = false;
      if (typeof window.updateIndicator === 'function') {
        window.updateIndicator('dashboard', 'green');
      }
    }
  };
  if (button && typeof withRuntimeAction === 'function') {
    return withRuntimeAction(button, '停止', run);
  }
  return run();
}

const DASHBOARD_RESTART_WAIT_MS = 35000;
const DASHBOARD_RESTART_POLL_MS = 700;
const DASHBOARD_RESTART_PROBE_MS = 1000;

function sleepMs(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

async function waitForDashboardReady(timeoutMs = DASHBOARD_RESTART_WAIT_MS) {
  // Bounded poll: hard deadline + per-probe abort so a hung TCP never freezes UI.
  const started = Date.now();
  const deadline = started + Math.max(3000, Number(timeoutMs) || DASHBOARD_RESTART_WAIT_MS);
  let sawDown = false;
  let attempts = 0;
  const maxAttempts = Math.ceil((deadline - started) / DASHBOARD_RESTART_POLL_MS) + 2;

  while (Date.now() < deadline && attempts < maxAttempts) {
    attempts += 1;
    try {
      const controller = new AbortController();
      const timer = setTimeout(() => controller.abort(), DASHBOARD_RESTART_PROBE_MS);
      const res = await fetch(`/api/auth/check?_=${Date.now()}`, {
        method: 'GET',
        cache: 'no-store',
        signal: controller.signal,
      });
      clearTimeout(timer);
      // Any HTTP answer means the panel is up (401/403 still count).
      if (res && res.status > 0 && res.status < 500) {
        if (sawDown || Date.now() - started > 1200) return true;
      }
    } catch {
      sawDown = true;
    }
    const remaining = deadline - Date.now();
    if (remaining <= 0) break;
    await sleepMs(Math.min(DASHBOARD_RESTART_POLL_MS, remaining));
  }
  return false;
}

async function restartDashboardPanel(button) {
  // Client-side single-flight: ignore double-clicks while a restart is in flight.
  if (window.dashboardRestartInFlight) {
    if (typeof showMessage === 'function') {
      showMessage(typeof getLanguage === 'function' && getLanguage() === 'en'
        ? 'Dashboard restart already in progress.'
        : '面板重启已在进行中。');
    }
    return null;
  }

  const run = async () => {
    const logEl = document.getElementById('dashboard-script-log');
    window.dashboardRestartInFlight = true;
    window.dashboardActionBusy = true;
    if (typeof window.updateIndicator === 'function') {
      window.updateIndicator('dashboard', 'yellow');
    }
    if (logEl) {
      setLogVisible(logEl, true);
      logEl.textContent = 'Restarting dashboard panel...';
    }

    let finished = false;
    const releaseClientGuards = () => {
      if (finished) return;
      finished = true;
      window.dashboardRestartInFlight = false;
      window.dashboardActionBusy = false;
    };

    // Absolute client-side safety net: never leave the UI stuck busy forever.
    const hardTimeout = setTimeout(() => {
      releaseClientGuards();
      if (logEl && /Restarting|Waiting|restarting/i.test(String(logEl.textContent || ''))) {
        logEl.textContent = 'Restart wait timed out on the client. If the panel is still down, run start_dashboard.ps1.';
      }
    }, DASHBOARD_RESTART_WAIT_MS + 5000);

    try {
      const result = await api('/api/dashboard/restart', 'POST', {});
      if (!result || result.ok === false) {
        const msg = result?.message || (typeof getLanguage === 'function' && getLanguage() === 'en'
          ? 'Dashboard restart was rejected.'
          : '面板重启被拒绝。');
        if (logEl) logEl.textContent = msg;
        showMessage(msg, true);
        releaseClientGuards();
        if (typeof window.updateIndicator === 'function') {
          window.updateIndicator('dashboard', 'green');
        }
        return;
      }

      showMessage(result.message || 'Dashboard panel is restarting...');
      if (logEl) logEl.textContent = 'Dashboard panel is restarting. Waiting for it to come back...';

      // One bounded wait only — no nested retries that could loop forever.
      const ready = await waitForDashboardReady(DASHBOARD_RESTART_WAIT_MS);
      if (ready) {
        if (logEl) logEl.textContent = 'Dashboard is back. Reloading...';
        // Keep inFlight true until unload so a second click cannot fire mid-reload.
        window.location.reload();
        return;
      }

      if (logEl) {
        logEl.textContent = 'Restart scheduled, but the panel did not answer in time. Check dashboard.relaunch.log or run start_dashboard.ps1.';
      }
      showMessage(
        typeof getLanguage === 'function' && getLanguage() === 'en'
          ? 'Restart was scheduled, but the panel did not recover in time. Check dashboard.relaunch.log.'
          : '重启已调度，但面板未在时限内恢复。请查看 dashboard.relaunch.log。',
        true,
      );
      releaseClientGuards();
      if (typeof window.updateIndicator === 'function') {
        window.updateIndicator('dashboard', 'red');
      }
    } catch (err) {
      // After the server schedules exit, the socket often dies mid-response —
      // treat network death as "restart likely underway", not a hard failure.
      const msg = String(err?.message || err || '');
      const likelyRestarting = /failed to fetch|networkerror|load failed|aborted|connection/i.test(msg);
      if (likelyRestarting) {
        if (logEl) logEl.textContent = 'Connection dropped (expected during restart). Waiting for panel...';
        const ready = await waitForDashboardReady(DASHBOARD_RESTART_WAIT_MS);
        if (ready) {
          if (logEl) logEl.textContent = 'Dashboard is back. Reloading...';
          window.location.reload();
          return;
        }
      }
      if (logEl) logEl.textContent = 'Restart failed: ' + msg;
      showMessage(msg || (typeof getLanguage === 'function' && getLanguage() === 'en'
        ? 'Failed to restart panel.'
        : '重启面板失败。'), true);
      releaseClientGuards();
      if (typeof window.updateIndicator === 'function') {
        window.updateIndicator('dashboard', likelyRestarting ? 'red' : 'green');
      }
    } finally {
      clearTimeout(hardTimeout);
    }
  };

  if (button && typeof withRuntimeAction === 'function') {
    return withRuntimeAction(button, '重启', run);
  }
  return run();
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
