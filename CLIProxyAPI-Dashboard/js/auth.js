let loadAuthFilesPending = false;
let loadAuthFilesQueued = false;
const expandedAuthCards = new Set();
const selectedAuthCards = new Set();
let selectedAuthProviderFilter = 'codex';
let availableAuthProviderFilter = 'codex';
let authSearchQuery = '';
let authEntryStatuses = {};
let authEntryStatusMeta = {};
let authItemsById = {};
const AUTH_ENTRY_TEST_CONCURRENCY = 2;
const AUTH_INLINE_SAVE_DEBOUNCE_MS = 15_000;
const authInlineSaveTimers = new Map();
const authInlineSaveInFlight = new Map();
const authInlineSavePending = new Map();
const authInlineSaveErrors = new Map();

// Cached data for client-side re-renders (no API calls)
let _cachedAuthItems = [];
let _cachedSelectedIds = [];
let _cachedAppliedIds = [];
let _cachedFingerprint = '';
let authVisibleLimit = 50;
const AUTH_VISIBLE_STEP = 50;

function _avail() {
  return (typeof Availability !== 'undefined' && Availability) ? Availability : null;
}

function escapeHtml(value) {
  return String(value ?? '')
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#39;');
}

function isAuthExpanded(id) {
  return expandedAuthCards.has(id);
}

function toggleAuthExpanded(id) {
  if (!id) return;
  if (expandedAuthCards.has(id)) expandedAuthCards.delete(id);
  else expandedAuthCards.add(id);
}

function updateToggleAllExpandButtonText() {
  const btn = document.getElementById('auth-toggle-all-expand-btn');
  if (!btn) return;
  const isZh = getLanguage() === 'zh';
  const visibleCards = document.querySelectorAll('#auth-selected-list .auth-strip, #auth-available-list .auth-strip');
  if (!visibleCards.length) {
    const textEl = btn.querySelector('.auth-toggle-expand-text');
    const iconEl = btn.querySelector('.auth-toggle-expand-icon');
    if (textEl) textEl.textContent = isZh ? '展开全部' : 'Expand All';
    if (iconEl) iconEl.textContent = '⤢';
    return;
  }
  let allExpanded = true;
  visibleCards.forEach(strip => {
    const id = strip.getAttribute('data-auth-id');
    if (id && !expandedAuthCards.has(id)) {
      allExpanded = false;
    }
  });
  const textEl = btn.querySelector('.auth-toggle-expand-text');
  const iconEl = btn.querySelector('.auth-toggle-expand-icon');
  if (textEl) textEl.textContent = allExpanded ? (isZh ? '收起全部' : 'Collapse All') : (isZh ? '展开全部' : 'Expand All');
  if (iconEl) iconEl.textContent = allExpanded ? '⤡' : '⤢';
}

function toggleAllAuthExpanded() {
  const visibleCards = document.querySelectorAll('#auth-selected-list .auth-strip, #auth-available-list .auth-strip');
  if (!visibleCards.length) return;

  let allExpanded = true;
  visibleCards.forEach(strip => {
    const id = strip.getAttribute('data-auth-id');
    if (id && !expandedAuthCards.has(id)) {
      allExpanded = false;
    }
  });

  const shouldExpand = !allExpanded;
  visibleCards.forEach(strip => {
    const id = strip.getAttribute('data-auth-id');
    if (!id) return;
    if (shouldExpand) {
      expandedAuthCards.add(id);
      strip.classList.add('is-expanded');
      const chevron = strip.querySelector('.auth-strip-chevron');
      if (chevron) chevron.textContent = '▲';
    } else {
      expandedAuthCards.delete(id);
      strip.classList.remove('is-expanded');
      const chevron = strip.querySelector('.auth-strip-chevron');
      if (chevron) chevron.textContent = '▼';
    }
  });
  updateToggleAllExpandButtonText();
}

function authStatusLabel(status, meta = {}) {
  const A = _avail();
  if (A) return A.statusLabel(status, meta);
  if (status === 'ok') return t('common.available', 'Available');
  if (status === 'bad') return t('common.unavailable', 'Unavailable');
  if (status === 'testing') return t('common.testing', 'Testing');
  return t('common.pending', getLanguage() === 'zh' ? '待检测' : 'Pending');
}

// 折叠态三色灯：绿=可用 / 红=不可用 / 黄=检测中或待检测
function authLightClass(status) {
  const A = _avail();
  if (A) return A.lightClass(status);
  if (status === 'ok') return 'is-green';
  if (status === 'bad') return 'is-red';
  if (status === 'testing') return 'is-yellow is-busy';
  return 'is-yellow';
}

function authStatusTitle(status, meta = {}) {
  const A = _avail();
  if (A) return A.statusTitle(status, meta);
  return authStatusLabel(status, meta);
}

function setAuthEntryStatus(id, status, meta = {}) {
  const authId = String(id || '').trim();
  if (!authId) return;
  if (status) authEntryStatuses[authId] = status;
  else delete authEntryStatuses[authId];
  authEntryStatusMeta[authId] = {
    ...(authEntryStatusMeta[authId] || {}),
    ...meta,
  };
}

function authStatusFromProbe(result) {
  return result?.available ? 'ok' : 'bad';
}

function authProbeMeta(result = {}) {
  return {
    available: Boolean(result.available),
    working_model: result.working_model,
    working_path: result.working_path,
    elapsed_ms: result.elapsed_ms,
    retry_after_seconds: result.retry_after_seconds,
    tested_at: result.tested_at || Math.floor(Date.now() / 1000),
    status_code: result.status_code,
    failure_kind: result.failure_kind,
    message: result.message,
  };
}

async function testAuthEntry(authId, force = true) {
  const item = authItemsById[authId];
  if (!item) throw new Error('Auth entry not found.');
  const result = await api('/api/test-auth-entry', 'POST', { auth_ref: item.id, force: Boolean(force) });
  if (!result?.ok) throw new Error(result?.message || 'Auth test failed.');
  return result;
}

async function runWithConcurrency(items, limit, worker) {
  const queue = [...items];
  const workers = Array.from({ length: Math.min(limit, queue.length) }, async () => {
    while (queue.length) {
      const item = queue.shift();
      await worker(item);
    }
  });
  await Promise.all(workers);
}

function toggleAuthCardSelection(id) {
  const authId = String(id || '').trim();
  if (!authId) return;
  if (selectedAuthCards.has(authId)) selectedAuthCards.delete(authId);
  else selectedAuthCards.add(authId);
}

function clearAuthCardSelection() {
  selectedAuthCards.clear();
  loadAuthFiles();
}

function getSelectedAuthCardIds() {
  return [...selectedAuthCards].filter((id) => authItemsById[id]);
}

async function applySelectedAuthPoolAction() {
  showMessage(getLanguage() === 'zh'
    ? '现在 storage/auth 里的账号文件默认全部启用；删除或移出文件即可停用。'
    : 'All files in storage/auth are active now. Delete or move a file out to disable it.');
}

async function testSelectedAuthCards() {
  const ids = getSelectedAuthCardIds();
  if (!ids.length) {
    showMessage(getLanguage() === 'zh' ? '请先选择账号卡片。' : 'Select auth cards first.', true);
    return;
  }
  const bulkBtn = document.getElementById('auth-bulk-test-btn');
  const originalBulkText = bulkBtn ? bulkBtn.textContent : '';
  if (bulkBtn) {
    bulkBtn.disabled = true;
    bulkBtn.textContent = getLanguage() === 'zh' ? '检测中...' : 'Testing...';
  }

  try {
    const now = Math.floor(Date.now() / 1000);
    ids.forEach((id) => {
      setAuthEntryStatus(id, 'testing', {
        tested_at: now,
        message: getLanguage() === 'zh' ? '账号检测进行中…' : 'Auth test running…',
      });
      updateAuthEntryLight(id);
    });

    await runWithConcurrency(ids, AUTH_ENTRY_TEST_CONCURRENCY, async (id) => {
      try {
        const result = await testAuthEntry(id);
        setAuthEntryStatus(id, authStatusFromProbe(result), authProbeMeta(result));
      } catch (err) {
        setAuthEntryStatus(id, 'bad', {
          tested_at: Math.floor(Date.now() / 1000),
          message: err.message,
        });
      }
      updateAuthEntryLight(id);
    });

    const okCount = ids.filter((id) => authEntryStatuses[id] === 'ok').length;
    const badCount = ids.filter((id) => authEntryStatuses[id] === 'bad').length;
    showMessage(
      getLanguage() === 'zh'
        ? `批量检测完成：可用 ${okCount} · 不可用 ${badCount}`
        : `Batch done: available ${okCount} · unavailable ${badCount}`
    );
  } catch (err) {
    showMessage(err.message, true);
  } finally {
    if (bulkBtn) {
      bulkBtn.disabled = false;
      bulkBtn.textContent = originalBulkText || (getLanguage() === 'zh' ? '检测选中' : 'Test selected');
    }
  }
}

async function copySelectedAuthPaths() {
  const ids = getSelectedAuthCardIds();
  if (!ids.length) {
    showMessage(getLanguage() === 'zh' ? '请先选择账号卡片。' : 'Select auth cards first.', true);
    return;
  }
  const paths = ids
    .map((id) => authItemsById[id]?.path || '')
    .filter(Boolean)
    .join('\n');
  try {
    await navigator.clipboard.writeText(paths);
    showMessage(getLanguage() === 'zh' ? '已复制选中路径。' : 'Copied selected paths.');
  } catch {
    showMessage(getLanguage() === 'zh' ? '复制失败，请手动复制。' : 'Copy failed. Please copy manually.', true);
  }
}

async function deleteSelectedAuthCards() {
  const ids = getSelectedAuthCardIds();
  if (!ids.length) {
    showMessage(getLanguage() === 'zh' ? '请先选择账号卡片。' : 'Select auth cards first.', true);
    return;
  }
  const names = ids.map((id) => authItemsById[id]?.name || id).filter(Boolean);
  const confirmed = window.confirm(
    getLanguage() === 'zh'
      ? `确认删除这 ${ids.length} 个账号文件？\n\n${names.join('\n')}`
      : `Delete these ${ids.length} auth files?\n\n${names.join('\n')}`
  );
  if (!confirmed) return;
  try {
    const result = await api('/api/delete-auths', 'POST', { ids });
    selectedAuthCards.clear();
    showMessage(result.message || (getLanguage() === 'zh' ? '已删除选中账号文件。' : 'Deleted selected auth files.'));
    await loadAuthFiles(true);
    await refreshStatus();
  } catch (err) {
    showMessage(err.message, true);
  }
}

async function deleteSingleAuthCard(id) {
  const item = authItemsById[id];
  if (!item) return;
  const name = item.name || id;
  const confirmed = window.confirm(
    getLanguage() === 'zh'
      ? `确认删除此账号文件？\n\n${name}`
      : `Delete this auth file?\n\n${name}`
  );
  if (!confirmed) return;
  try {
    const result = await api('/api/delete-auths', 'POST', { ids: [id] });
    if (selectedAuthCards.has(id)) selectedAuthCards.delete(id);
    if (expandedAuthCards.has(id)) expandedAuthCards.delete(id);
    showMessage(result.message || (getLanguage() === 'zh' ? '已删除账号文件。' : 'Deleted auth file.'));
    await loadAuthFiles(true);
    await refreshStatus();
  } catch (err) {
    showMessage(err.message, true);
  }
}

function updateAuthBulkToolbar(items, selectedPoolIds = []) {
  const countEl = document.getElementById('auth-bulk-selection-count');
  const ids = getSelectedAuthCardIds();
  const allInPool = ids.length > 0 && ids.every((id) => selectedPoolIds.includes(id));
  if (countEl) {
    countEl.textContent = ids.length
      ? `${getLanguage() === 'zh' ? '已选' : 'Selected'} ${ids.length}`
      : (getLanguage() === 'zh' ? '未选择' : 'No selection');
  }
  const poolBtn = document.getElementById('auth-bulk-pool-btn');
  if (poolBtn) {
    poolBtn.hidden = true;
  }
  const testBtn = document.getElementById('auth-bulk-test-btn');
  if (testBtn) testBtn.disabled = !ids.length;
  const copyBtn = document.getElementById('auth-bulk-copy-btn');
  if (copyBtn) copyBtn.disabled = !ids.length;
  const clearBtn = document.getElementById('auth-bulk-clear-btn');
  if (clearBtn) clearBtn.disabled = !ids.length;
  const deleteBtn = document.getElementById('auth-bulk-delete-btn');
  if (deleteBtn) deleteBtn.disabled = !ids.length;
}

async function setAuthPool(ids) {
  const result = await api('/api/select-auths', 'POST', { ids });
  showMessage(result.message || (getLanguage() === 'zh' ? '账号由 storage/auth 文件夹直接控制。' : 'Auth is controlled directly by storage/auth files.'));
  await loadAuthFiles();
  await refreshStatus();
}

async function toggleAuthInPool(id, selectedIds) {
  const nextIds = selectedIds.includes(id)
    ? selectedIds.filter(entry => entry !== id)
    : [...selectedIds, id];
  try {
    await setAuthPool(nextIds);
  } catch (err) {
    showMessage(err.message, true);
  }
}

const authDetectInFlight = new Set();

function paintAuthStatusUI() {
  // 仅状态变化时：fingerprint 不变，loadAuthFiles 会跳过重绘；直接用缓存渲染。
  if (typeof renderAuthUI === 'function' && Array.isArray(_cachedAuthItems) && _cachedAuthItems.length) {
    renderAuthUI();
    return;
  }
  if (typeof loadAuthFiles === 'function') loadAuthFiles(true);
}

// 并发检测时只改灯/按钮，避免整表重绘互相踩踏
function updateAuthEntryLight(id) {
  const authId = String(id || '').trim();
  if (!authId) return;
  const status = authEntryStatuses[authId] || '';
  const meta = authEntryStatusMeta[authId] || {};
  const strip = document.querySelector(`.auth-strip[data-auth-id="${CSS.escape(authId)}"]`);
  if (!strip) return;
  const light = strip.querySelector('.auth-status-light');
  if (light) {
    light.className = `auth-status-light ${authLightClass(status)}`;
    light.title = authStatusTitle(status, meta);
    light.setAttribute('aria-label', authStatusLabel(status, meta));
  }
  const testBtn = strip.querySelector('[data-auth-test]');
  if (testBtn) {
    if (status === 'testing') {
      testBtn.disabled = true;
      testBtn.textContent = getLanguage() === 'zh' ? '检测中...' : 'Testing...';
    } else {
      testBtn.disabled = false;
      testBtn.textContent = getLanguage() === 'zh' ? '检测' : 'Test';
    }
  }
}

async function runAuthEntryDetection(authId, triggerButton, options = {}) {
  const id = String(authId || '').trim();
  if (!id) return;
  if (authDetectInFlight.has(id)) return;
  authDetectInFlight.add(id);

  const silent = Boolean(options.silent);
  const button = triggerButton || null;
  const originalText = button ? button.textContent : '';
  const item = authItemsById[id];
  const authName = item?.name || id;
  try {
    setAuthEntryStatus(id, 'testing', {
      tested_at: Math.floor(Date.now() / 1000),
      message: getLanguage() === 'zh' ? '模型检测进行中…' : 'Model tests running…',
    });
    updateAuthEntryLight(id);

    const busyButton = document.querySelector(`[data-auth-test="${CSS.escape(id)}"]`) || button;
    if (busyButton) {
      busyButton.disabled = true;
      busyButton.textContent = getLanguage() === 'zh' ? '检测中...' : 'Testing...';
    }

    const result = await testAuthEntry(id);
    setAuthEntryStatus(id, authStatusFromProbe(result), authProbeMeta(result));
    updateAuthEntryLight(id);
    if (!silent) {
      const status = authEntryStatuses[id] || '';
      const meta = authEntryStatusMeta[id] || {};
      showMessage(`${authName} · ${authStatusLabel(status, meta)}`);
    }
  } catch (err) {
    setAuthEntryStatus(id, 'bad', {
      tested_at: Math.floor(Date.now() / 1000),
      message: err.message,
    });
    updateAuthEntryLight(id);
    if (!silent) showMessage(err.message, true);
  } finally {
    authDetectInFlight.delete(id);
    updateAuthEntryLight(id);
    const liveButton = document.querySelector(`[data-auth-test="${CSS.escape(id)}"]`) || button;
    if (liveButton && authEntryStatuses[id] !== 'testing') {
      liveButton.disabled = false;
      liveButton.textContent = originalText || (getLanguage() === 'zh' ? '检测' : 'Test');
    }
  }
}

function wireAuthPanelActions(root, selectedIds) {
  root?.querySelectorAll('[data-auth-toggle]').forEach(btn => {
    btn.onclick = async (e) => {
      e.stopPropagation();
      const id = btn.getAttribute('data-auth-toggle');
      if (id) await toggleAuthInPool(id, selectedIds);
    };
  });
  root?.querySelectorAll('[data-auth-copy]').forEach(btn => {
    btn.onclick = async (e) => {
      e.stopPropagation();
      const path = btn.getAttribute('data-auth-copy') || '';
      try {
        await navigator.clipboard.writeText(path);
        showMessage(getLanguage() === 'zh' ? '路径已复制。' : 'Path copied.');
      } catch {
        showMessage(getLanguage() === 'zh' ? '复制失败，请手动复制。' : 'Copy failed. Please copy manually.', true);
      }
    };
  });
  root?.querySelectorAll('[data-auth-test]').forEach(btn => {
    btn.onclick = async (e) => {
      e.stopPropagation();
      const id = btn.getAttribute('data-auth-test') || '';
      if (id) await runAuthEntryDetection(id, btn);
    };
  });
  root?.querySelectorAll('[data-auth-save]').forEach(btn => {
    const id = btn.getAttribute('data-auth-save') || '';
    btn.type = 'button';
    btn.disabled = false;
    btn.title = getLanguage() === 'zh' ? '编辑后自动保存' : 'Changes save automatically';
    btn.setAttribute('aria-label', btn.title);
    btn.onclick = async (e) => {
      e.stopPropagation();
      if (authInlineSaveErrors.has(id)) {
        authInlineSaveErrors.delete(id);
        setInlineAuthSaveState(_inlineAuthCard(id), 'pending');
      }
      await saveInlineEditedAuthCard(id);
    };
    const card = btn.closest('.auth-strip');
    if (card) {
      restoreInlineAuthPendingValues(card, id);
      if (authInlineSaveErrors.has(id)) setInlineAuthSaveState(card, 'error');
      else if (authInlineSavePending.has(id)) setInlineAuthSaveState(card, 'pending');
    }
  });
  root?.querySelectorAll('[data-auth-edit-field]').forEach(field => {
    const eventName = field.tagName === 'SELECT' ? 'change' : 'input';
    field.addEventListener(eventName, () => {
      const id = field.getAttribute('data-auth-id') || field.closest('.auth-strip')?.getAttribute('data-auth-id') || '';
      const fieldName = field.getAttribute('data-auth-edit-field') || '';
      if (!id || !fieldName) return;
      queueInlineAuthFieldChange(id, fieldName, field, AUTH_INLINE_SAVE_DEBOUNCE_MS);
    });
  });
  root?.querySelectorAll('[data-auth-edit]').forEach(btn => {
    btn.onclick = async (e) => {
      e.stopPropagation();
      const id = btn.getAttribute('data-auth-edit') || '';
      if (id) await openAuthFileEditModal(id);
    };
  });
  root?.querySelectorAll('[data-auth-move]').forEach(btn => {
    btn.onclick = async (e) => {
      e.stopPropagation();
      const id = btn.getAttribute('data-auth-id') || '';
      const dirStr = btn.getAttribute('data-auth-move');
      const direction = dirStr === 'up' ? -1 : 1;
      if (id) await moveAuthInPool(id, selectedIds, direction);
    };
  });
  root?.querySelectorAll('[data-auth-delete]').forEach(btn => {
    btn.onclick = async (e) => {
      e.stopPropagation();
      const id = btn.getAttribute('data-auth-delete') || '';
      if (id) await deleteSingleAuthCard(id);
    };
  });
  root?.querySelectorAll('[data-auth-expand]').forEach(el => {
    el.onclick = (e) => {
      if (e.target.closest('button, a, input, select, textarea')) return;
      const id = el.getAttribute('data-auth-expand') || '';
      if (id) {
        toggleAuthExpanded(id);
        const strip = el.closest('.auth-strip');
        if (strip) {
           const isExpanded = expandedAuthCards.has(id);
           strip.classList.toggle('is-expanded', isExpanded);
           const chevron = strip.querySelector('.auth-strip-chevron');
           if (chevron) chevron.textContent = isExpanded ? '▲' : '▼';
        }
        updateToggleAllExpandButtonText();
      }
    };
  });
  root?.querySelectorAll('[data-auth-check]').forEach(cb => {
    cb.onclick = (e) => {
      e.stopPropagation();
      const id = cb.getAttribute('data-auth-check') || '';
      if (!id) return;
      toggleAuthCardSelection(id);
      updateAuthBulkToolbar(authItemsById, selectedIds);
      const isPicked = selectedAuthCards.has(id);
      cb.classList.toggle('is-checked', isPicked);
      const strip = cb.closest('.auth-strip');
      if (strip) {
        strip.classList.toggle('is-picked', isPicked);
      }
    };
  });
  root?.querySelectorAll('[data-auth-load-more]').forEach(btn => {
    btn.onclick = (e) => {
      e.stopPropagation();
      authVisibleLimit += AUTH_VISIBLE_STEP;
      renderAuthUI();
    };
  });
}

function applyAuthProviderFilter(items, providerFilter) {
  if (!providerFilter || providerFilter === '__all__') return items;
  return items.filter(item => String(item.provider || '').trim() === providerFilter);
}

function applyAuthSearchFilter(items, query = authSearchQuery) {
  const token = String(query || '').trim().toLowerCase();
  if (!token) return items;
  return items.filter((item) => {
    const haystack = [
      item?.name,
      item?.email,
      item?.provider,
      item?.path,
      item?.accountId,
      item?.sourceId,
      item?.id,
      item?.baseUrl,
      item?.remark,
      Array.isArray(item?.models) ? item.models.join(' ') : '',
    ].map((value) => String(value || '').toLowerCase()).join(' ');
    return haystack.includes(token);
  });
}

function setAuthSearch(value) {
  authSearchQuery = String(value || '');
  authVisibleLimit = AUTH_VISIBLE_STEP;
  renderAuthUI();
}

function preferredAuthProviderFilter(items, activeFilter) {
  const providers = [...new Set(items.map(item => String(item.provider || '').trim()).filter(Boolean))];
  if (!providers.length) return '';
  if (providers.includes(activeFilter)) return activeFilter;
  if (providers.includes('codex')) return 'codex';
  return providers[0];
}

function renderAuthProviderFilters(root, items, activeFilter, onSelect, activeClass = '') {
  if (!root) return activeFilter;
  const providers = [...new Set(items.map(item => String(item.provider || '').trim()).filter(Boolean))];
  const options = providers;
  const normalizedFilter = preferredAuthProviderFilter(items, activeFilter);
  root.innerHTML = options.map(value => {
    const classes = ['auth-provider-filter-btn'];
    if (value === normalizedFilter) {
      classes.push('is-active');
      if (activeClass) classes.push(activeClass);
    }
    const label = value;
    return `<button type="button" class="${classes.join(' ')}" data-auth-provider-filter="${escapeHtml(value)}">${escapeHtml(label)}</button>`;
  }).join('');
  root.querySelectorAll('[data-auth-provider-filter]').forEach(btn => {
    btn.onclick = () => {
      authVisibleLimit = AUTH_VISIBLE_STEP;
      onSelect(btn.getAttribute('data-auth-provider-filter') || '');
    };
  });
  return normalizedFilter;
}


function _extractHostFromUrl(urlStr) {
  try {
    if (!urlStr) return '';
    const u = new URL(urlStr.startsWith('http') ? urlStr : `http://${urlStr}`);
    return u.host || u.hostname || '';
  } catch {
    return String(urlStr || '').replace(/^https?:\/\//, '').split('/')[0] || '';
  }
}

function authCardHtml(item, options = {}) {
  const { selected = false, applied = false, orderIndex = -1, totalSelected = 0 } = options;
  const authId = item.id || '';
  const id = escapeHtml(authId);
  const name = escapeHtml(item.name || '-');
  const path = escapeHtml(item.path || '');
  const email = escapeHtml(item.email || '');
  const accountId = escapeHtml(item.accountId || '');
  const providerValue = String(item.provider || '').trim();
  const provider = escapeHtml(providerValue || '-');
  const rawBaseUrl = String(item.baseUrl || item.base_url || '').trim();
  const baseUrl = escapeHtml(rawBaseUrl);
  const hostLabel = _extractHostFromUrl(rawBaseUrl);
  const remark = escapeHtml(item.remark || '');
  const maskedKey = escapeHtml(item.apiKeyMasked || '');
  const isDisabled = Boolean(item.disabled);

  const modelsList = Array.isArray(item.models) ? item.models : [];
  const modelsStr = modelsList.length > 0 ? modelsList.join(', ') : (item.defaultModel || '');

  const modified = item.mtime ? new Date(item.mtime * 1000).toLocaleString() : '-';
  const detectStatus = authEntryStatuses[authId] || '';
  const detectMeta = authEntryStatusMeta[authId] || {};
  const isZh = getLanguage() === 'zh';
  const isExpanded = expandedAuthCards.has(authId);
  const cardPicked = selectedAuthCards.has(authId);

  const statusText = authStatusLabel(detectStatus, detectMeta);
  const statusTitle = authStatusTitle(detectStatus, detectMeta);
  const lightClass = authLightClass(detectStatus);

  const poolLabel = isDisabled
    ? (isZh ? '已停用' : 'Disabled')
    : (isZh ? '已启用' : 'Enabled');
  const appliedLabel = applied ? (isZh ? '已应用' : 'Applied') : '';

  // Secondary chip in top row
  let headerMetaChip = '';
  if (email && email !== '-') {
    headerMetaChip = `<span class="auth-inline-chip email" title="${email}">${email}</span>`;
  } else if (hostLabel) {
    headerMetaChip = `<span class="auth-inline-chip host" title="${baseUrl}" style="font-family:monospace;font-size:11px;">${escapeHtml(hostLabel)}</span>`;
  } else if (remark && remark !== '-') {
    headerMetaChip = `<span class="auth-inline-chip remark" title="${remark}">${remark}</span>`;
  }

  // Status badge styling
  const poolChipClass = isDisabled ? 'disabled-chip' : 'pool active-chip';
  const poolChipStyle = isDisabled ? 'background:rgba(239,68,68,0.12);border-color:rgba(239,68,68,0.3);color:#dc2626;' : '';

  // Detail lines: structured, informative, and directly inline-editable
  const detailItems = [];

  // 1. Status
  detailItems.push({
    label: isZh ? '状态' : 'Status',
    value: `<select class="auth-inline-select" data-auth-edit-field="disabled" data-auth-id="${id}" data-original-val="${isDisabled}">
      <option value="false" ${!isDisabled ? 'selected' : ''}>🟢 已启用 (disabled: false)</option>
      <option value="true" ${isDisabled ? 'selected' : ''}>🔴 已停用 (disabled: true)</option>
    </select>`,
    isHtml: true
  });

  // 2. Base URL (接口地址)
  detailItems.push({
    label: isZh ? '接口地址' : 'Base URL',
    value: `<input type="text" class="auth-inline-input font-mono" data-auth-edit-field="base_url" data-auth-id="${id}" value="${escapeHtml(rawBaseUrl)}" data-original-val="${escapeHtml(rawBaseUrl)}" placeholder="https://..." style="min-width: 170px; color: #2563eb; font-weight: 600;" title="点击可直接编辑 接口地址" />`,
    isHtml: true
  });

  // 3. API Key (Key 预览)
  detailItems.push({
    label: isZh ? 'Key 预览' : 'API Key',
    value: `<div style="display:inline-flex;align-items:center;gap:4px;width:100%;"><input type="password" class="auth-inline-input font-mono" data-auth-edit-field="api_key" data-auth-id="${id}" value="" data-original-val="" placeholder="${maskedKey || '输入新 API Key'}" style="flex:1;min-width:140px;color:var(--text-soft);" title="输入新 Key 后自动保存；留空表示不修改" /><button type="button" class="secondary" onclick="toggleInlineCardKeyMask(this)" style="height:22px;padding:0 5px;font-size:11px;font-weight:700;" title="显示/隐藏 Key 密码">👁️</button></div>`,
    isHtml: true
  });

  // 4. Provider & Source
  detailItems.push({
    label: isZh ? '提供方' : 'Provider',
    value: `<div style="display:inline-flex;align-items:center;gap:6px;"><input type="text" class="auth-inline-input" data-auth-edit-field="provider" data-auth-id="${id}" value="${escapeHtml(provider || '')}" data-original-val="${escapeHtml(providerValue || '')}" placeholder="ung" style="width: 100px;" title="点击可直接编辑 提供方" /><span style="color:var(--text-soft);font-size:11px;">· Source: ${escapeHtml(item.sourceId || '-')}</span></div>`,
    isHtml: true
  });

  // 5. File info
  detailItems.push({
    label: isZh ? '文件信息' : 'File info',
    value: `${item.size} bytes · ${modified}`
  });

  // 6. Email
  const emailVal = email && email !== '-' ? email : '';
  detailItems.push({
    label: isZh ? '邮箱' : 'Email',
    value: `<input type="text" class="auth-inline-input" data-auth-edit-field="email" data-auth-id="${id}" value="${escapeHtml(emailVal)}" data-original-val="${escapeHtml(emailVal)}" placeholder="account@qq.com" style="min-width: 180px;" title="点击可直接编辑 邮箱" />`,
    isHtml: true
  });

  // 7. Account ID (if present)
  if (accountId && accountId !== '-') {
    detailItems.push({
      label: isZh ? '账号 ID' : 'Account ID',
      value: accountId
    });
  }

  // 8. Models (Dedicated Full Width Line)
  const modelsVal = modelsList.length > 0 ? modelsList.join(', ') : (modelsStr || '');
  detailItems.push({
    label: isZh ? '包含模型' : 'Models',
    value: `<input type="text" class="auth-inline-input font-mono" data-auth-edit-field="models" data-auth-id="${id}" value="${escapeHtml(modelsVal)}" data-original-val="${escapeHtml(modelsVal)}" placeholder="gpt-5.6-luna, gpt-5.6-terra (多个模型用逗号分隔)" style="width: 100%; box-sizing: border-box; font-size: 11.5px;" title="点击可直接编辑 包含模型列表" />`,
    isHtml: true,
    fullWidth: true
  });

  // 9. Remark (Full Width if long)
  if (remark && remark !== '-' && remark !== email) {
    detailItems.push({
      label: isZh ? '备注' : 'Remark',
      value: remark,
      fullWidth: true
    });
  }

  // 10. File path (Full Width)
  detailItems.push({
    label: isZh ? '文件路径' : 'Path',
    value: item.path || '-',
    fullWidth: true
  });

  // 11. Detection Result (Full Width)
  if (detectStatus === 'ok' || detectMeta.working_model) {
    const elapsedStr = detectMeta.elapsed_ms ? ` (耗时: ${(detectMeta.elapsed_ms / 1000).toFixed(2)}s)` : '';
    detailItems.push({
      label: isZh ? '检测结果' : 'Test Result',
      value: `<span style="color:#22c55e;font-weight:700;">✅ 可用模型: ${escapeHtml(detectMeta.working_model || 'OK')}${elapsedStr} · ${escapeHtml(detectMeta.message || '正常响应')}</span>`,
      isHtml: true,
      fullWidth: true
    });
  } else if (detectStatus === 'bad') {
    const elapsedStr = detectMeta.elapsed_ms ? ` (耗时: ${(detectMeta.elapsed_ms / 1000).toFixed(2)}s)` : '';
    detailItems.push({
      label: isZh ? '检测结果' : 'Test Result',
      value: `<span style="color:#ef4444;font-weight:700;">❌ 不可用: ${escapeHtml(detectMeta.message || '检测未通过')}${elapsedStr}</span>`,
      isHtml: true,
      fullWidth: true
    });
  } else if (detectStatus === 'testing') {
    detailItems.push({
      label: isZh ? '检测结果' : 'Test Result',
      value: `<span style="color:#eab308;font-weight:700;">⏳ ${escapeHtml(detectMeta.message || '模型检测进行中…')}</span>`,
      isHtml: true,
      fullWidth: true
    });
  }

  return `
    <article class="auth-strip ${selected ? 'is-selected' : ''} ${cardPicked ? 'is-picked' : ''} ${isExpanded ? 'is-expanded' : ''}" data-auth-id="${id}">
      <div class="auth-strip-summary" data-auth-expand="${id}">
        <div class="auth-strip-toggle ${cardPicked ? 'is-checked' : ''}" data-auth-check="${id}">
          <span class="auth-toggle-indicator"></span>
        </div>
        <span class="auth-status-light ${lightClass}" title="${escapeHtml(statusTitle)}" aria-label="${escapeHtml(statusText)}"></span>
        <div class="auth-strip-main">
          <span class="auth-strip-name">${name}</span>
          <span class="auth-inline-chip provider">${provider}</span>
          ${headerMetaChip}
        </div>
        <div class="auth-strip-actions">
          <button class="secondary" type="button" data-auth-test="${id}">${isZh ? '检测' : 'Test'}</button>
          <span class="auth-save-status" data-auth-save="${id}" data-auth-save-state="saved" role="status">${isZh ? '自动保存' : 'Auto-save'}</span>
          <button class="secondary" type="button" data-auth-copy="${escapeHtml(item.path || '')}">${isZh ? '复制路径' : 'Copy path'}</button>
          <button class="danger" type="button" data-auth-delete="${id}">${isZh ? '删除' : 'Delete'}</button>
        </div>
        <div class="auth-strip-status">
          <span class="auth-inline-chip ${poolChipClass}" style="${poolChipStyle}">${poolLabel}</span>
          ${applied ? `<span class="auth-inline-chip applied active-chip">${appliedLabel}</span>` : ''}
        </div>
        <div class="auth-order-actions-inline">
          ${selected && totalSelected > 1 && orderIndex > 0 ? `<button class="auth-order-btn" data-auth-move="up" data-auth-id="${id}" aria-label="${isZh ? '上移' : 'Move up'}">↑</button>` : ''}
          ${selected && totalSelected > 1 && orderIndex >= 0 && orderIndex < totalSelected - 1 ? `<button class="auth-order-btn" data-auth-move="down" data-auth-id="${id}" aria-label="${isZh ? '下移' : 'Move down'}">↓</button>` : ''}
        </div>
        <div class="auth-strip-chevron">
          ${isExpanded ? '▲' : '▼'}
        </div>
      </div>

      <div class="auth-strip-details">
        <div class="auth-details-grid">
          ${detailItems.map(it => `
            <div class="auth-detail-line ${it.fullWidth ? 'is-full-width' : ''}" title="${escapeHtml(it.isHtml ? it.value.replace(/<[^>]*>/g, '') : it.value)}">
              <strong>${escapeHtml(it.label)}:</strong> ${it.isHtml ? it.value : escapeHtml(it.value)}
            </div>
          `).join('')}
        </div>
      </div>
    </article>`;
}

async function moveAuthInPool(id, selectedIds, direction) {
  const authId = String(id || '').trim();
  const step = Number(direction || 0);
  if (!authId || ![-1, 1].includes(step)) return;
  try {
    const result = await api('/api/move-auth-in-pool', 'POST', {
      id: authId,
      direction: step,
    });
    showMessage(result.message || 'Auth order updated.');
    await loadAuthFiles();
    await refreshStatus();
  } catch (err) {
    const message = String(err?.message || '');
    if (/not found/i.test(message)) {
      // Fallback for old backend without /api/move-auth-in-pool.
      const currentIds = Array.isArray(selectedIds) ? [...selectedIds] : [];
      const index = currentIds.indexOf(authId);
      const nextIndex = index + step;
      if (index >= 0 && nextIndex >= 0 && nextIndex < currentIds.length) {
        [currentIds[index], currentIds[nextIndex]] = [currentIds[nextIndex], currentIds[index]];
        await setAuthPool(currentIds);
        return;
      }
    }
    showMessage(message || 'Failed to move auth order.', true);
  }
}


// Pure client-side re-render from cached data (no API calls)
function renderAuthUI() {
  const items = _cachedAuthItems;
  const selectedIds = _cachedSelectedIds;
  const appliedIds = _cachedAppliedIds;
  const appliedSet = new Set(appliedIds);

  const selectedList = document.getElementById('auth-selected-list');
  const availableList = document.getElementById('auth-available-list');
  const selectedFilters = document.getElementById('auth-selected-filters');
  const availableFilters = document.getElementById('auth-available-filters');
  const legacyList = document.getElementById('auth-list');

  updateAuthBulkToolbar(authItemsById, selectedIds);

  const selectedItems = items;
  const availableItems = [];

  selectedAuthProviderFilter = preferredAuthProviderFilter(selectedItems, selectedAuthProviderFilter);
  availableAuthProviderFilter = preferredAuthProviderFilter(availableItems, availableAuthProviderFilter);

  selectedAuthProviderFilter = renderAuthProviderFilters(selectedFilters, selectedItems, selectedAuthProviderFilter, (value) => {
    selectedAuthProviderFilter = value;
    renderAuthUI();
  }, 'active-chip');
  availableAuthProviderFilter = renderAuthProviderFilters(availableFilters, availableItems, availableAuthProviderFilter, (value) => {
    availableAuthProviderFilter = value;
    renderAuthUI();
  });

  const filteredSelectedItems = applyAuthSearchFilter(
    applyAuthProviderFilter(selectedItems, selectedAuthProviderFilter),
    authSearchQuery,
  );
  const filteredAvailableItems = applyAuthSearchFilter(
    applyAuthProviderFilter(availableItems, availableAuthProviderFilter),
    authSearchQuery,
  );

  setText('auth-selected-count', filteredSelectedItems.length === selectedItems.length
    ? String(selectedItems.length)
    : `${filteredSelectedItems.length}/${selectedItems.length}`, '0');
  setText('auth-available-count', String(availableItems.length), '0');

  if (selectedList) {
    const visibleSelectedItems = filteredSelectedItems.slice(0, authVisibleLimit);
    const remainingSelectedCount = Math.max(0, filteredSelectedItems.length - visibleSelectedItems.length);
    const loadMoreHtml = remainingSelectedCount
      ? `<button class="secondary auth-load-more-btn" type="button" data-auth-load-more="1">${getLanguage() === 'zh' ? `加载更多 ${remainingSelectedCount}` : `Load ${remainingSelectedCount} more`}</button>`
      : '';
    selectedList.innerHTML = visibleSelectedItems.length
      ? visibleSelectedItems.map(item => authCardHtml(item, {
        selected: true,
        applied: appliedSet.has(item.id),
        orderIndex: selectedIds.indexOf(item.id),
        totalSelected: selectedIds.length,
      })).join('') + loadMoreHtml
      : `<div class="auth-empty">${t('common.noSelectedAccounts', 'No selected accounts yet.')}</div>`;
    wireAuthPanelActions(selectedList, selectedIds);
  }

  if (availableList) {
    const wrap = availableList.closest('.auth-group-wrap');
    if (wrap) wrap.hidden = true;
    availableList.innerHTML = filteredAvailableItems.length
      ? filteredAvailableItems.map(item => authCardHtml(item, { selected: false, applied: appliedSet.has(item.id) })).join('')
      : `<div class="auth-empty">${t('common.noAvailableAccounts', 'No available accounts.')}</div>`;
    wireAuthPanelActions(availableList, selectedIds);
  }

  if (legacyList) {
    const wrap = legacyList.closest('.list-wrap');
    if (wrap) wrap.hidden = true;
    legacyList.innerHTML = '';
  }

  updateToggleAllExpandButtonText();
}

async function loadAuthFiles(force = false) {
  if (loadAuthFilesPending) {
    if (force) loadAuthFilesQueued = true;
    return;
  }
  loadAuthFilesPending = true;
  loadAuthFilesQueued = false;
  try {
    const authData = await api('/api/auth-files');
    let statusData = { status: {} };
    api('/api/status')
      .then(data => {
        statusData = data || { status: {} };
        const appliedIds = Array.isArray(statusData.status?.applied_auth_refs) && statusData.status?.applied_auth_refs.length
          ? statusData.status.applied_auth_refs.filter(Boolean)
          : (statusData.status?.applied_auth_ref ? [statusData.status.applied_auth_ref] : []);
        const nextFingerprint = _cachedAuthItems.map(i => i.id).join(',') + '|' + _cachedSelectedIds.join(',') + '|' + appliedIds.join(',');
        if (appliedIds.join(',') !== _cachedAppliedIds.join(',')) {
          _cachedAppliedIds = appliedIds;
          _cachedFingerprint = nextFingerprint;
          renderAuthUI();
        }
        if (statusData.status?.restart_required) {
          showMessage(t('common.restartRequired', 'Restart required to apply runtime setting changes.'));
        }
      })
      .catch(() => {});
    const items = Array.isArray(authData.items) ? [...authData.items] : [];
    authItemsById = Object.fromEntries(items.filter(item => item?.id).map(item => [item.id, item]));
    // 清理已删除账号的状态，避免脏灯号
    const liveIds = new Set(Object.keys(authItemsById));
    for (const id of Object.keys(authEntryStatuses)) {
      if (!liveIds.has(id)) {
        delete authEntryStatuses[id];
        delete authEntryStatusMeta[id];
      }
    }

    // 恢复后端持久化的检测缓存
    if (authData.test_cache && typeof authData.test_cache === 'object') {
      for (const [id, cachedMeta] of Object.entries(authData.test_cache)) {
        if (id && cachedMeta && typeof cachedMeta === 'object' && liveIds.has(id)) {
          if (!authDetectInFlight.has(id)) {
            authEntryStatuses[id] = cachedMeta.available ? 'ok' : 'bad';
            authEntryStatusMeta[id] = authProbeMeta(cachedMeta);
          }
        }
      }
    }
    const selectedIds = Array.isArray(authData.selected_auth_refs) && authData.selected_auth_refs.length
      ? authData.selected_auth_refs.filter(Boolean)
      : (authData.selected_auth_ref ? [authData.selected_auth_ref] : []);
    const appliedIds = _cachedAppliedIds.filter(Boolean);
    const selectedOrder = new Map(selectedIds.map((id, index) => [id, index]));

    items.sort((a, b) => {
      const aSelected = new Set(selectedIds).has(a.id);
      const bSelected = new Set(selectedIds).has(b.id);
      if (aSelected && bSelected) {
        return (selectedOrder.get(a.id) ?? 10 ** 6) - (selectedOrder.get(b.id) ?? 10 ** 6);
      }
      if (aSelected !== bSelected) return aSelected ? -1 : 1;
      return String(a.name || '').localeCompare(String(b.name || ''));
    });

    // Quick fingerprint to detect actual data changes
    const fingerprint = items.map(i => i.id).join(',') + '|' + selectedIds.join(',') + '|' + appliedIds.join(',');
    const changed = fingerprint !== _cachedFingerprint;

    // Cache data for client-side re-renders
    _cachedAuthItems = items;
    _cachedSelectedIds = selectedIds;
    _cachedAppliedIds = appliedIds;
    _cachedFingerprint = fingerprint;

    setText('summary-auth-count', String(items.length), '0');
    setText('auth-count-badge', String(items.length), '0');

    // Only re-render DOM if data actually changed or forced
    if (changed || force) {
      renderAuthUI();
    }
  } catch (err) {
    if (!String(err.message || '').includes('returned a page instead of JSON')) {
      showMessage(err.message, true);
    }
  } finally {
    loadAuthFilesPending = false;
    if (loadAuthFilesQueued) {
      loadAuthFilesQueued = false;
      loadAuthFiles(true);
    }
  }
}


// Manual Auth Modal Logic
let manualAuthPresets = [];

async function ensureManualAuthPresets() {
  try {
    if (!manualAuthPresets.length) {
      const data = typeof api === 'function' ? await api('/api/manual-provider-presets') : await (await fetch('/api/manual-provider-presets')).json();
      manualAuthPresets = Array.isArray(data.items) ? data.items : [];
    }
    const datalist = document.getElementById('manual-auth-provider-list');
    if (datalist && manualAuthPresets.length) {
      datalist.innerHTML = manualAuthPresets.map((item) => `<option value="${escapeHtml(item.provider)}"></option>`).join('');
    }
  } catch (e) {}
}

function onManualAuthProviderInput(val) {
  const providerName = String(val || '').trim().toLowerCase();
  if (!providerName) return;
  const preset = manualAuthPresets.find((item) => String(item.provider || '').toLowerCase() === providerName);
  const baseInput = document.getElementById('manual-auth-base-url');
  if (preset && preset.base_url && baseInput) {
    baseInput.value = preset.base_url;
  }
}

function showManualAuthModal() {
  document.getElementById('manual-auth-provider').value = '';
  document.getElementById('manual-auth-base-url').value = '';
  document.getElementById('manual-auth-model').value = '';
  document.getElementById('manual-auth-api-key').value = '';
  document.getElementById('manual-auth-remark').value = '';
  ensureManualAuthPresets();
  const modal = document.getElementById('manual-auth-modal');
  if (modal) modal.hidden = false;
}

function hideManualAuthModal() {
  const modal = document.getElementById('manual-auth-modal');
  if (modal) modal.hidden = true;
}

async function submitManualAuth() {
  const provider = document.getElementById('manual-auth-provider').value.trim();
  const baseUrl = document.getElementById('manual-auth-base-url').value.trim();
  const model = document.getElementById('manual-auth-model').value.trim();
  const apiKey = document.getElementById('manual-auth-api-key').value.trim();
  const remark = document.getElementById('manual-auth-remark').value.trim();

  if (!baseUrl || !model || !apiKey) {
    showMessage('Base URL、Model 和 API Key 均为必填项。', true);
    return;
  }

  try {
    const response = await fetch('/api/create-manual-auth', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        base_url: baseUrl,
        model: model,
        api_key: apiKey,
        provider: provider,
        remark: remark
      })
    });
    const data = await response.json();
    if (data.ok) {
      showMessage('自定义 API Key 添加成功。');
      hideManualAuthModal();
      loadAuthFiles(true);
    } else {
      showMessage(data.message || '添加失败。', true);
    }
  } catch (err) {
    showMessage('请求异常: ' + err.message, true);
  }
}

/* ==========================================================================
   Auth File Editor Tool (账号文件配置编辑小工具)
   ========================================================================== */

let _currentEditingAuthId = null;
let _currentEditingAuthData = null;
let _currentAuthEditMode = 'form'; // 'form' or 'raw'

async function openAuthFileEditModal(authId) {
  const id = String(authId || '').trim();
  if (!id) return;

  _currentEditingAuthId = id;
  _currentAuthEditMode = 'form';
  const modal = document.getElementById('auth-file-edit-modal');
  if (!modal) return;

  const msgEl = document.getElementById('afe-msg-alert');
  if (msgEl) { msgEl.style.display = 'none'; msgEl.textContent = ''; }

  try {
    const res = await api(`/api/auth-file/content?id=${encodeURIComponent(id)}`);
    if (!res || !res.ok) {
      showMessage(res?.message || '获取账号文件配置失败。', true);
      return;
    }

    _currentEditingAuthData = res;
    const payload = res.payload || {};
    const name = res.name || id;
    const path = res.path || '-';

    document.getElementById('afe-filename-chip').textContent = name;
    document.getElementById('afe-file-path').textContent = path;

    // Populate Form Fields
    document.getElementById('afe-form-base-url').value = payload.base_url || payload.BaseURL || payload.url || '';
    document.getElementById('afe-form-api-key').value = payload.api_key || payload.api_key_masked || payload.key || '';
    document.getElementById('afe-form-provider').value = payload.provider || payload.type || '';
    document.getElementById('afe-form-email').value = payload.email || payload.account || '';
    document.getElementById('afe-form-disabled').value = payload.disabled ? 'true' : 'false';
    document.getElementById('afe-form-proxy-url').value = payload.proxy_url || payload.proxy || '';
    document.getElementById('afe-form-disable-cooling').checked = !!payload['disable-cooling'];

    // Models field
    let modelsList = [];
    if (Array.isArray(payload.models)) modelsList = payload.models;
    else if (typeof payload.model === 'string') modelsList = [payload.model];
    document.getElementById('afe-form-models').value = modelsList.join(', ');

    // Headers & Model Mapping
    document.getElementById('afe-form-headers').value = payload.headers && typeof payload.headers === 'object' ? JSON.stringify(payload.headers, null, 2) : '';
    document.getElementById('afe-form-model-mapping').value = payload.model_mapping && typeof payload.model_mapping === 'object' ? JSON.stringify(payload.model_mapping, null, 2) : '';

    // Populate Raw JSON
    document.getElementById('afe-raw-json').value = res.raw_json || JSON.stringify(payload, null, 2);
    validateAuthFileRawJsonSyntax();

    switchAuthFileEditMode('form');
    modal.hidden = false;
  } catch (err) {
    showToast('加载账号配置失败: ' + (err.message || err), true);
  }
}

function hideAuthFileEditModal() {
  const modal = document.getElementById('auth-file-edit-modal');
  if (modal) modal.hidden = true;
  _currentEditingAuthId = null;
  _currentEditingAuthData = null;
}

function switchAuthFileEditMode(mode) {
  _currentAuthEditMode = mode;
  const formBtn = document.getElementById('afe-mode-btn-form');
  const rawBtn = document.getElementById('afe-mode-btn-raw');
  const formPane = document.getElementById('afe-pane-form');
  const rawPane = document.getElementById('afe-pane-raw');

  if (mode === 'raw') {
    syncFormToRawJson();
    if (formBtn) formBtn.classList.remove('active');
    if (rawBtn) rawBtn.classList.add('active');
    if (formPane) formPane.style.display = 'none';
    if (rawPane) rawPane.style.display = 'flex';
  } else {
    syncRawJsonToForm();
    if (formBtn) formBtn.classList.add('active');
    if (rawBtn) rawBtn.classList.remove('active');
    if (formPane) formPane.style.display = 'flex';
    if (rawPane) rawPane.style.display = 'none';
  }
}

function toggleAuthEditApiKeyMask() {
  const input = document.getElementById('afe-form-api-key');
  const btn = document.getElementById('afe-eye-btn');
  if (input) {
    if (input.type === 'password') {
      input.type = 'text';
      if (btn) btn.textContent = '🙈';
    } else {
      input.type = 'password';
      if (btn) btn.textContent = '👁️';
    }
  }
}

function syncFormToRawJson() {
  let basePayload = {};
  if (_currentEditingAuthData?.payload && typeof _currentEditingAuthData.payload === 'object') {
    basePayload = JSON.parse(JSON.stringify(_currentEditingAuthData.payload));
  }
  const baseUrl = document.getElementById('afe-form-base-url').value.trim();
  const apiKey = document.getElementById('afe-form-api-key').value.trim();
  const provider = document.getElementById('afe-form-provider').value.trim();
  const email = document.getElementById('afe-form-email').value.trim();
  const disabledStr = document.getElementById('afe-form-disabled').value;
  const proxyUrl = document.getElementById('afe-form-proxy-url').value.trim();
  const disableCooling = document.getElementById('afe-form-disable-cooling').checked;
  const modelsRaw = document.getElementById('afe-form-models').value.trim();
  const headersRaw = document.getElementById('afe-form-headers').value.trim();
  const mappingRaw = document.getElementById('afe-form-model-mapping').value.trim();

  if (baseUrl) basePayload.base_url = baseUrl;
  if (apiKey) basePayload.api_key = apiKey;
  if (provider) basePayload.provider = provider;
  if (email) basePayload.email = email;
  basePayload.disabled = disabledStr === 'true';
  if (proxyUrl) basePayload.proxy_url = proxyUrl;
  else delete basePayload.proxy_url;

  if (disableCooling) basePayload['disable-cooling'] = true;
  else delete basePayload['disable-cooling'];

  if (modelsRaw) {
    const modelsArr = modelsRaw.split(/[\n,]+/).map(s => s.trim()).filter(Boolean);
    basePayload.models = modelsArr;
  }

  if (headersRaw) {
    try { basePayload.headers = JSON.parse(headersRaw); } catch (e) {}
  } else {
    delete basePayload.headers;
  }

  if (mappingRaw) {
    try { basePayload.model_mapping = JSON.parse(mappingRaw); } catch (e) {}
  } else {
    delete basePayload.model_mapping;
  }

  document.getElementById('afe-raw-json').value = JSON.stringify(basePayload, null, 2);
  validateAuthFileRawJsonSyntax();
}

function syncRawJsonToForm() {
  const rawText = document.getElementById('afe-raw-json').value;
  try {
    const payload = JSON.parse(rawText);
    if (payload && typeof payload === 'object') {
      document.getElementById('afe-form-base-url').value = payload.base_url || payload.BaseURL || payload.url || '';
      document.getElementById('afe-form-api-key').value = payload.api_key || payload.key || '';
      document.getElementById('afe-form-provider').value = payload.provider || payload.type || '';
      document.getElementById('afe-form-email').value = payload.email || payload.account || '';
      document.getElementById('afe-form-disabled').value = payload.disabled ? 'true' : 'false';
      document.getElementById('afe-form-proxy-url').value = payload.proxy_url || payload.proxy || '';
      document.getElementById('afe-form-disable-cooling').checked = !!payload['disable-cooling'];

      let modelsList = [];
      if (Array.isArray(payload.models)) modelsList = payload.models;
      else if (typeof payload.model === 'string') modelsList = [payload.model];
      document.getElementById('afe-form-models').value = modelsList.join(', ');

      document.getElementById('afe-form-headers').value = payload.headers && typeof payload.headers === 'object' ? JSON.stringify(payload.headers, null, 2) : '';
      document.getElementById('afe-form-model-mapping').value = payload.model_mapping && typeof payload.model_mapping === 'object' ? JSON.stringify(payload.model_mapping, null, 2) : '';
    }
  } catch (e) {
    // Keep existing form fields if raw JSON is invalid
  }
}

function validateAuthFileRawJsonSyntax() {
  const text = document.getElementById('afe-raw-json').value;
  const statusEl = document.getElementById('afe-json-syntax-status');
  if (!statusEl) return;
  try {
    JSON.parse(text);
    statusEl.style.color = '#10b981';
    statusEl.textContent = '✓ JSON 语法格式正确';
  } catch (err) {
    statusEl.style.color = '#ef4444';
    statusEl.textContent = '❌ JSON 语法错误: ' + err.message;
  }
}

function formatAuthFileRawJson() {
  const textarea = document.getElementById('afe-raw-json');
  if (!textarea) return;
  try {
    const obj = JSON.parse(textarea.value);
    textarea.value = JSON.stringify(obj, null, 2);
    validateAuthFileRawJsonSyntax();
  } catch (err) {
    showMessage('JSON 格式化失败: ' + err.message, true);
  }
}

async function submitAuthFileEdit() {
  if (!_currentEditingAuthId) return;

  const msgEl = document.getElementById('afe-msg-alert');
  if (msgEl) { msgEl.style.display = 'none'; }

  let sendBody = { id: _currentEditingAuthId };
  if (_currentAuthEditMode === 'raw') {
    const rawText = document.getElementById('afe-raw-json').value;
    try {
      JSON.parse(rawText);
    } catch (err) {
      if (msgEl) {
        msgEl.style.display = 'block';
        msgEl.style.color = '#ef4444';
        msgEl.textContent = '❌ JSON 语法错误，请修改后重试: ' + err.message;
      }
      return;
    }
    sendBody.raw_json = rawText;
  } else {
    syncFormToRawJson();
    const rawText = document.getElementById('afe-raw-json').value;
    sendBody.raw_json = rawText;
  }

  try {
    const res = await api('/api/auth-file/update', 'POST', sendBody);
    if (res && res.ok) {
      showMessage(res.message || '账号文件配置保存成功。');
      hideAuthFileEditModal();
      await loadAuthFiles(true);
      await refreshStatus();
    } else {
      if (msgEl) {
        msgEl.style.display = 'block';
        msgEl.style.color = '#ef4444';
        msgEl.textContent = '❌ 保存失败: ' + (res?.message || '未知错误');
      } else {
        showMessage(res?.message || '保存失败。', true);
      }
    }
  } catch (err) {
    if (msgEl) {
      msgEl.style.display = 'block';
      msgEl.style.color = '#ef4444';
      msgEl.textContent = '❌ 保存异常: ' + (err.message || err);
    } else {
      showMessage('保存异常: ' + (err.message || err), true);
    }
  }
}

function toggleInlineCardKeyMask(btn) {
  const input = btn?.previousElementSibling;
  if (input && input.tagName === 'INPUT') {
    if (input.type === 'password') {
      input.type = 'text';
      btn.textContent = '🙈';
    } else {
      input.type = 'password';
      btn.textContent = '👁️';
    }
  }
}

function setInlineAuthSaveState(card, state) {
  const saveBtn = card?.querySelector('[data-auth-save]');
  if (!saveBtn) return;
  const isZh = getLanguage() === 'zh';
  const labels = {
    saving: isZh ? '保存中…' : 'Saving…',
    saved: isZh ? '已自动保存' : 'Auto-saved',
    pending: isZh ? '待自动保存' : 'Pending save',
    error: isZh ? '重试保存' : 'Retry save',
  };
  saveBtn.textContent = labels[state] || labels.pending;
  saveBtn.dataset.authSaveState = state;
  saveBtn.title = state === 'error'
    ? (isZh ? '点击重试保存' : 'Click to retry saving')
    : (isZh ? '编辑后自动保存' : 'Changes save automatically');
  saveBtn.disabled = state === 'saving';
  saveBtn.classList.toggle('is-saving', state === 'saving');
  saveBtn.classList.toggle('is-save-error', state === 'error');
}

function _inlineAuthCard(authId) {
  const id = String(authId || '').trim();
  if (!id) return null;
  const safeId = (window.CSS && CSS.escape) ? CSS.escape(id) : id.replace(/["\\]/g, '\\$&');
  return document.querySelector(`.auth-strip[data-auth-id="${safeId}"]`);
}

function _inlineAuthFieldValue(fieldName, field) {
  const value = String(field?.value ?? '').trim();
  if (fieldName === 'disabled') return value === 'true';
  if (fieldName === 'models') return value.split(/[\n,]+/).map(item => item.trim()).filter(Boolean);
  return value;
}

function restoreInlineAuthPendingValues(card, authId) {
  const pending = authInlineSavePending.get(authId) || {};
  for (const [fieldName, entry] of Object.entries(pending)) {
    const field = card?.querySelector(`[data-auth-edit-field="${fieldName}"]`);
    if (!field) continue;
    field.value = entry.inputValue;
  }
}

function queueInlineAuthFieldChange(authId, fieldName, field, delay = AUTH_INLINE_SAVE_DEBOUNCE_MS) {
  const id = String(authId || '').trim();
  if (!id || !fieldName || !field) return;
  const pending = authInlineSavePending.get(id) || {};
  pending[fieldName] = {
    value: _inlineAuthFieldValue(fieldName, field),
    inputValue: String(field.value ?? '').trim(),
  };
  authInlineSavePending.set(id, pending);
  authInlineSaveErrors.delete(id);
  const card = _inlineAuthCard(id);
  if (card) setInlineAuthSaveState(card, 'pending');

  const oldTimer = authInlineSaveTimers.get(id);
  if (oldTimer) clearTimeout(oldTimer);
  const timer = setTimeout(() => {
    authInlineSaveTimers.delete(id);
    saveInlineEditedAuthCard(id).catch(() => {});
  }, Math.max(0, delay));
  authInlineSaveTimers.set(id, timer);
}

/* Inline Auth Card Edit & Direct Save (field queue + serial requests) */
async function saveInlineEditedAuthCard(authId) {
  const id = String(authId || '').trim();
  if (!id || authInlineSaveInFlight.has(id)) return;

  const card = _inlineAuthCard(id);
  if (!card) return;
  const pending = authInlineSavePending.get(id);
  if (!pending || !Object.keys(pending).length) {
    setInlineAuthSaveState(card, 'saved');
    return;
  }

  // Remove the snapshot before awaiting the request. Edits made while it is
  // in flight are written into a fresh pending snapshot by the input handler.
  authInlineSavePending.delete(id);
  authInlineSaveInFlight.set(id, true);
  const snapshot = Object.fromEntries(
    Object.entries(pending).map(([fieldName, entry]) => [fieldName, { ...entry }]),
  );
  const changes = Object.fromEntries(
    Object.entries(snapshot).map(([fieldName, entry]) => [fieldName, entry.value]),
  );
  let requestSucceeded = false;

  setInlineAuthSaveState(card, 'saving');
  try {
    const updateRes = await api('/api/auth-file/update', 'POST', { id, changes });
    if (!updateRes?.ok) {
      throw new Error(updateRes?.message || (getLanguage() === 'zh' ? '保存失败。' : 'Save failed.'));
    }
    requestSucceeded = true;
    authInlineSaveErrors.delete(id);

    for (const [fieldName, entry] of Object.entries(snapshot)) {
      const field = card.querySelector(`[data-auth-edit-field="${fieldName}"]`);
      if (!field) continue;
      const currentInputValue = String(field.value ?? '').trim();
      if (currentInputValue === entry.inputValue) {
        field.setAttribute('data-original-val', entry.inputValue);
      }
    }

    const item = authItemsById[id];
    if (item) {
      if (Object.prototype.hasOwnProperty.call(changes, 'disabled')) item.disabled = Boolean(changes.disabled);
      if (Object.prototype.hasOwnProperty.call(changes, 'base_url')) item.baseUrl = changes.base_url;
      if (Object.prototype.hasOwnProperty.call(changes, 'api_key')) {
        item.apiKeyMasked = changes.api_key.length > 12
          ? `${changes.api_key.slice(0, 6)}...${changes.api_key.slice(-4)}`
          : changes.api_key;
      }
      if (Object.prototype.hasOwnProperty.call(changes, 'provider')) item.provider = changes.provider;
      if (Object.prototype.hasOwnProperty.call(changes, 'email')) item.email = changes.email;
      if (Object.prototype.hasOwnProperty.call(changes, 'models')) item.models = changes.models;
    }
    await refreshStatus();
  } catch (err) {
    // Put only fields from this failed request back. Newer edits win.
    const newerPending = authInlineSavePending.get(id) || {};
    for (const [fieldName, entry] of Object.entries(snapshot)) {
      if (!Object.prototype.hasOwnProperty.call(newerPending, fieldName)) {
        newerPending[fieldName] = entry;
      }
    }
    authInlineSavePending.set(id, newerPending);
    authInlineSaveErrors.set(id, String(err.message || err));
    setInlineAuthSaveState(card, 'error');
    showMessage((err.message || err) + (getLanguage() === 'zh' ? '，修改仍保留，稍后可重试。' : ' Changes are retained for retry.'), true);
  } finally {
    authInlineSaveInFlight.delete(id);
    const hasPending = Boolean(authInlineSavePending.get(id) && Object.keys(authInlineSavePending.get(id)).length);
    if (requestSucceeded && hasPending) {
      setInlineAuthSaveState(card, 'pending');
      setTimeout(() => saveInlineEditedAuthCard(id).catch(() => {}), 0);
    } else if (requestSucceeded) {
      setInlineAuthSaveState(card, 'saved');
    }
  }
}
