// =========================================================================
// ClaudeAdapter + Claude Code 客户端面板 glue
// -------------------------------------------------------------------------
// 提供：
//   window.runClaudeAdapterAction(op, button)  → 控制站派发
//   window.runClaudeCodeAction(op, button)
//   window.waitUntilStatus(fn, { timeoutMs, intervalMs })
// =========================================================================

(function () {
  async function withRuntimeActionSafe(button, label, fn) {
    if (typeof withRuntimeAction === 'function') {
      return await withRuntimeAction(button, label, fn);
    }
    return await fn();
  }

  async function toastResult(r, fallbackOk = '完成', fallbackErr = '操作失败') {
    const message = (r && (r.message || r.error || r.msg)) || (r?.ok ? fallbackOk : fallbackErr);
    if (typeof showMessage === 'function') showMessage(message, !(r?.ok));
    return r;
  }

  async function refresh() {
    if (typeof refreshStatus === 'function') {
      try { await refreshStatus(); } catch { /* noop */ }
    }
  }

  function setIndicator(type, color, { persist = false, title = '' } = {}) {
    if (typeof window.updateIndicator === 'function') {
      window.updateIndicator(type, color, { persist });
    }
    const el = document.getElementById(`${type}-status-indicator`);
    if (el && title) el.title = title;
  }

  async function waitUntil(predicate, { timeoutMs = 15000, intervalMs = 500 } = {}) {
    const deadline = Date.now() + timeoutMs;
    while (Date.now() < deadline) {
      try {
        const resp = await api('/api/status');
        const s = resp?.status || resp || {};
        if (predicate(s)) return s;
      } catch { /* swallow */ }
      await new Promise((res) => setTimeout(res, intervalMs));
    }
    return null;
  }

  // ---------------------------------------------------------------------
  // ClaudeAdapter actions
  // ---------------------------------------------------------------------
  async function runClaudeAdapterAction(op, button) {
    op = String(op || '').trim().toLowerCase();
    const label = button?.textContent?.trim() || op;
    window.claudeAdapterActionBusy = true;
    setIndicator('claude-adapter', 'yellow', { persist: false, title: `ClaudeAdapter ${label} 中...` });
    try {
      return await withRuntimeActionSafe(button, label, async () => {
        let result = null;
        if (op === 'build') {
          result = await api('/api/claude-adapter/build', 'POST', { force: false });
        } else if (op === 'write-config') {
          result = await api('/api/claude-adapter/config', 'POST', { force: false });
        } else if (op === 'start') {
          result = await api('/api/local-workspace/action', 'POST', {
            service_id: 'claude-adapter',
            operation: 'start',
          });
          await waitUntil((s) => !!(s.claude_adapter?.listener_ready || s.claude_adapter?.running), {
            timeoutMs: 25000,
            intervalMs: 400,
          });
        } else if (op === 'restart') {
          result = await api('/api/local-workspace/action', 'POST', {
            service_id: 'claude-adapter',
            operation: 'restart',
          });
          await waitUntil((s) => !!(s.claude_adapter?.listener_ready || s.claude_adapter?.running), {
            timeoutMs: 25000,
            intervalMs: 400,
          });
        } else if (op === 'stop') {
          result = await api('/api/local-workspace/action', 'POST', {
            service_id: 'claude-adapter',
            operation: 'stop',
          });
          await waitUntil((s) => !s.claude_adapter?.listener_ready && !s.claude_adapter?.running, {
            timeoutMs: 6000,
            intervalMs: 300,
          });
        } else {
          return await toastResult({ ok: false, message: `不支持的操作：${op}` });
        }
        await toastResult(result, `${label}成功。`, `${label}失败。`);
        return result;
      });
    } catch (err) {
      await toastResult({ ok: false, message: err?.message || String(err) }, '', '');
      return { ok: false, message: err?.message || String(err) };
    } finally {
      window.claudeAdapterActionBusy = false;
      await refresh();
    }
  }

  // ---------------------------------------------------------------------
  // Claude Code settings.json actions
  // ---------------------------------------------------------------------
  function summarizeCC(cc) {
    const ok = cc && cc.ok !== false;
    const mode = (cc && cc.via_adapter) ? '经 Adapter'
      : (cc && cc.via_core ? '直连核心'
        : ((cc && cc.exists) ? '未配置 URL' : '未安装 Claude Code'));
    const url = cc?.base_url || '';
    const path = cc?.path || '~/.claude/settings.json';
    return `${mode} · ${url || '无 ANTHROPIC_BASE_URL'}\n文件：${path}`;
  }

  async function runClaudeCodeAction(op, button) {
    op = String(op || '').trim().toLowerCase();
    const label = button?.textContent?.trim() || op;
    window.claudeCodeActionBusy = true;
    try {
      return await withRuntimeActionSafe(button, label, async () => {
        let result = null;
        if (op === 'toggle-via-adapter') {
          // 读当前状态（优先按钮缓存），做相反切换
          let currentMode = (button?.dataset?.currentMode || '').trim();
          if (!currentMode) {
            const status = (await api('/api/status'))?.status || {};
            currentMode = (status?.claude_code?.via_adapter) ? 'adapter' : 'core';
          }
          const enable = currentMode !== 'adapter';
          result = await api('/api/claude-code-settings', 'POST', {
            action: 'use_adapter',
            enable,
          });
        } else if (op === 'show-info') {
          result = await api('/api/claude-code-settings', 'POST', { action: 'read' });
          if (result?.ok) {
            const details = summarizeCC(result);
            if (typeof showMessage === 'function') showMessage(details, false);
          }
        } else {
          return await toastResult({ ok: false, message: `不支持的操作：${op}` });
        }
        await toastResult(result, `${label}成功。`, `${label}失败。`);
        return result;
      });
    } catch (err) {
      await toastResult({ ok: false, message: err?.message || String(err) });
      return { ok: false, message: err?.message || String(err) };
    } finally {
      window.claudeCodeActionBusy = false;
      await refresh();
    }
  }

  // ---------------------------------------------------------------------
  // 对外 API（挂载到 window 以便 control-station.js 调用）
  // ---------------------------------------------------------------------
  window.runClaudeAdapterAction = runClaudeAdapterAction;
  window.runClaudeCodeAction = runClaudeCodeAction;
  window.waitUntilStatus = waitUntil;
})();
