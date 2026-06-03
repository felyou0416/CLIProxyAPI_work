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

// Cached data for client-side re-renders (no API calls)
let _cachedAuthItems = [];
let _cachedSelectedIds = [];
let _cachedAppliedIds = [];
let _cachedFingerprint = '';
let authVisibleLimit = 50;
const AUTH_VISIBLE_STEP = 50;

function escapeHtml(value) {
  return String(value ?? '')
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#39;');
}

function formatAuthRetryAfter(seconds) {
  const value = Number(seconds || 0);
  if (!value) return '';
  if (value < 60) return getLanguage() === 'zh' ? `${value} 秒后重试` : `Retry in ${value}s`;
  return getLanguage() === 'zh' ? `${Math.ceil(value / 60)} 分钟后重试` : `Retry in ${Math.ceil(value / 60)}m`;
}

function formatAuthElapsed(ms) {
  const value = Number(ms || 0);
  if (!value) return '';
  if (value < 1000) return `${value} ms`;
  return getLanguage() === 'zh' ? `${(value / 1000).toFixed(1)} 秒` : `${(value / 1000).toFixed(1)} s`;
}

function isAuthExpanded(id) {
  return expandedAuthCards.has(id);
}

function toggleAuthExpanded(id) {
  if (!id) return;
  if (expandedAuthCards.has(id)) expandedAuthCards.delete(id);
  else expandedAuthCards.add(id);
}

function authStatusLabel(status, meta = {}) {
  const isZh = getLanguage() === 'zh';
  if (status === 'ok') {
    return `${t('common.available', 'Available')}${meta.working_model ? ` · ${meta.working_model}` : ''}`;
  }
  if (status === 'bad') {
    return `${t('common.unavailable', 'Unavailable')}${meta.retry_after_seconds ? ` · ${formatAuthRetryAfter(meta.retry_after_seconds)}` : ''}`;
  }
  if (status === 'testing') return t('common.testing', 'Testing');
  return t('common.pending', isZh ? '待检测' : 'Pending');
}

function authStatusTitle(status, meta = {}) {
  const isZh = getLanguage() === 'zh';
  const lines = [
    `${isZh ? '状态' : 'Status'}: ${status === 'ok' ? t('common.available', 'Available') : status === 'bad' ? t('common.unavailable', 'Unavailable') : status === 'testing' ? t('common.testing', 'Testing') : t('common.pending', 'Pending')}`,
  ];
  if (meta.working_path) lines.push(`${isZh ? '路径' : 'Path'}: ${meta.working_path}`);
  if (meta.working_model) lines.push(`${isZh ? '模型' : 'Model'}: ${meta.working_model}`);
  if (meta.elapsed_ms) lines.push(`${isZh ? '耗时' : 'Elapsed'}: ${formatAuthElapsed(meta.elapsed_ms)}`);
  if (meta.retry_after_seconds) lines.push(`${isZh ? '重试' : 'Retry'}: ${formatAuthRetryAfter(meta.retry_after_seconds)}`);
  if (meta.message) lines.push(`${isZh ? '信息' : 'Message'}: ${String(meta.message).slice(0, 180)}`);
  return lines.join('\n');
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
  for (const id of ids) {
    await runAuthEntryDetection(id);
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

async function runAuthEntryDetection(authId, triggerButton) {
  const id = String(authId || '').trim();
  if (!id) return;
  const button = triggerButton || null;
  const originalText = button ? button.textContent : '';
  try {
    authEntryStatuses[id] = 'testing';
    authEntryStatusMeta[id] = {
      tested_at: Math.floor(Date.now() / 1000),
    };
    await loadAuthFiles();

    if (button) {
      button.disabled = true;
      button.textContent = getLanguage() === 'zh' ? '检测中...' : 'Testing...';
    }

    let result;
    try {
      result = await api('/api/test-auth-entry', 'POST', { auth_ref: id });
    } catch (err) {
      if (!/Not found/i.test(String(err.message || ''))) throw err;
      const item = authItemsById[id];
      const provider = String(item?.provider || '').trim();
      const providerData = await api('/api/provider-models?runtime_state=1');
      const groups = Array.isArray(providerData.items) ? providerData.items : [];
      const group = groups.find(entry =>
        String(entry.provider || '').trim() === provider || String(entry.lookup_provider || '').trim() === provider
      );
      const modelIds = Array.isArray(group?.rows)
        ? [...new Set(group.rows.filter(row => row && row.runtime_registered).map(row => String(row.call_id || '').trim()).filter(Boolean))]
        : [];
      if (!modelIds.length) {
        throw new Error(`No runtime model IDs found for provider: ${provider || 'unknown'}`);
      }
      const batch = await api('/api/test-provider-models', 'POST', { model_ids: modelIds });
      const entries = Array.isArray(batch.items) ? batch.items : [];
      const best = entries.find(entry => entry.available) || entries[0];
      result = {
        ok: true,
        auth_ref: id,
        auth_name: item?.name || id,
        available: Boolean(best?.available),
        working_model: best?.model || null,
        working_path: best?.working_path || null,
        status_code: best?.status_code,
        message: best?.message || 'Fallback via provider detection.',
        elapsed_ms: best?.elapsed_ms,
        retry_after_seconds: best?.retry_after_seconds,
        tested_at: best?.tested_at || Math.floor(Date.now() / 1000),
      };
    }
    authEntryStatuses[id] = result.available ? 'ok' : 'bad';
    authEntryStatusMeta[id] = {
      working_model: result.working_model,
      working_path: result.working_path,
      elapsed_ms: result.elapsed_ms,
      retry_after_seconds: result.retry_after_seconds,
      tested_at: result.tested_at,
      status_code: result.status_code,
      message: result.message,
    };
    await loadAuthFiles();

    const suffix = result.available
      ? `${getLanguage() === 'zh' ? '可用' : 'Available'}${result.working_model ? ` · ${result.working_model}` : ''}`
      : `${getLanguage() === 'zh' ? '不可用' : 'Unavailable'}${result.retry_after_seconds ? ` · ${formatAuthRetryAfter(result.retry_after_seconds)}` : ''}`;
    showMessage(`${result.auth_name || id} · ${suffix}`);
  } catch (err) {
    authEntryStatuses[id] = 'bad';
    authEntryStatusMeta[id] = {
      tested_at: Math.floor(Date.now() / 1000),
      retry_after_seconds: 120,
      message: err.message,
    };
    await loadAuthFiles();
    showMessage(err.message, true);
  } finally {
    if (button) {
      button.disabled = false;
      button.textContent = originalText;
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


function authCardHtml(item, options = {}) {
  const { selected = false, applied = false, orderIndex = -1, totalSelected = 0 } = options;
  const authId = item.id || '';
  const id = escapeHtml(authId);
  const name = escapeHtml(item.name || '-');
  const path = escapeHtml(item.path || '');
  const email = escapeHtml(item.email || '-');
  const accountId = escapeHtml(item.accountId || '-');
  const providerValue = String(item.provider || '').trim();
  const provider = escapeHtml(providerValue || '-');
  const modified = item.mtime ? new Date(item.mtime * 1000).toLocaleString() : '-';
  const detectStatus = authEntryStatuses[authId] || '';
  const detectMeta = authEntryStatusMeta[authId] || {};
  const isZh = getLanguage() === 'zh';
  const isExpanded = expandedAuthCards.has(authId);
  const cardPicked = selectedAuthCards.has(authId);

  const statusText = authStatusLabel(detectStatus, detectMeta);
  const statusClass = detectStatus ? `status-${detectStatus}` : 'status-idle';
  
  const poolLabel = isZh ? '已启用' : 'Enabled';
  const appliedLabel = applied ? (isZh ? '已应用' : 'Applied') : '';

  const detailLines = [
    `${isZh ? '路径' : 'Path'}: ${item.path || '-'}`,
    `${isZh ? '邮箱' : 'Email'}: ${item.email || '-'}`,
    `${isZh ? '账号 ID' : 'Account ID'}: ${item.accountId || '-'}`,
    `${isZh ? '提供方' : 'Provider'}: ${item.provider || '-'}`,
    `Source: ${item.sourceId || '-'}`,
    `${isZh ? '文件大小' : 'File size'}: ${item.size} bytes`,
    `${isZh ? '修改时间' : 'Modified'}: ${modified}`,
  ];
  if (detectMeta.working_model) detailLines.push(`${isZh ? '可用模型' : 'Working model'}: ${detectMeta.working_model}`);
  if (detectMeta.working_path) detailLines.push(`${isZh ? '命中路径' : 'Working path'}: ${detectMeta.working_path}`);
  if (detectMeta.message) detailLines.push(`${isZh ? '信息' : 'Message'}: ${String(detectMeta.message).slice(0, 180)}`);

  
  return `
    <article class="auth-strip ${selected ? 'is-selected' : ''} ${cardPicked ? 'is-picked' : ''} ${isExpanded ? 'is-expanded' : ''}" data-auth-id="${id}">
      <div class="auth-strip-summary" data-auth-expand="${id}">
        <div class="auth-strip-toggle ${cardPicked ? 'is-checked' : ''}" data-auth-check="${id}">
          <span class="auth-toggle-indicator"></span>
        </div>
        <div class="auth-strip-main">
          <span class="auth-strip-name">${name}</span>
          <span class="auth-inline-chip provider">${provider}</span>
          <span class="auth-inline-chip email">${email}</span>
        </div>
        <div class="auth-strip-status">
          <div class="auth-test-status ${statusClass}" title="${escapeHtml(statusText)}">
            <span class="auth-test-status-dot ${statusClass}"></span>
            <span class="auth-strip-status-text">${escapeHtml(statusText)}</span>
          </div>
          <span class="auth-inline-chip pool active-chip">${poolLabel}</span>
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
          ${detailLines.map(line => `<div class="auth-detail-line">${escapeHtml(line)}</div>`).join('')}
        </div>
        <div class="auth-strip-actions">
          <button class="secondary" type="button" data-auth-test="${id}">${isZh ? '检测' : 'Test'}</button>
          <button class="secondary" type="button" data-auth-copy="${escapeHtml(item.path || '')}">${isZh ? '复制路径' : 'Copy path'}</button>
          <button class="danger" type="button" data-auth-delete="${id}">${isZh ? '删除' : 'Delete'}</button>
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
function showManualAuthModal() {
  document.getElementById('manual-auth-provider').value = '';
  document.getElementById('manual-auth-base-url').value = '';
  document.getElementById('manual-auth-model').value = '';
  document.getElementById('manual-auth-api-key').value = '';
  document.getElementById('manual-auth-remark').value = '';
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
    showToast('Base URL、Model 和 API Key 均为必填项。', true);
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
      showToast('自定义 API Key 添加成功。');
      hideManualAuthModal();
      loadAuthFiles(true);
    } else {
      showToast(data.message || '添加失败。', true);
    }
  } catch (err) {
    showToast('请求异常: ' + err.message, true);
  }
}
