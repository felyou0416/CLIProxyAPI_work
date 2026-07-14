let aggregateItemsCache = [];
let aggregateProviderItemsCache = [];
let aggregateProviderSummariesCache = [];
const aggregateProviderItemCache = new Map();
let aggregateProviderRowsLoading = false;
let activeAggregateAliasId = '';
let activeAggregateProviderFilter = '';
let activeAggregateTypeFilter = 'all';
let activeAggregateScoreFilter = 'all';
// Reverted to click-to-add directly (removed aggregateSelectedMembers)
let aggregateModelStatuses = {};
let aggregateModelStatusMeta = {};
let aggregateModelsRunningSet = new Set();
let aggregateModelStatePollTimer = null;
let aggregateRoutePreviewCache = {};
let aggregateRouteHealthCache = {};
let aggregateSourceListLoaded = false;
let aggregateSourceListLoading = false;
let aggregateModelsLoaded = false;
let aggregateEditMode = false;
const aggregateEditMembers = new Set();
const aggregateMemberPendingKeys = new Set();
const aggregateAliasPendingIds = new Set();
const aggregateMemberSavingAliases = new Set();
const aggregateMemberSaveChains = new Map();
const aggregateMemberSaveDebounces = new Map();
const aggregateMemberRollbackSnapshots = new Map();
const AGGREGATE_MEMBER_SAVE_DEBOUNCE_MS = 200;
const aggregateMemberMutationVersions = new Map();
let aggregateSortMode = 'name';
let editingAliasId = '';
let viewedAggregateAliasVersion = '1';
let viewedAggregateAliasId = '';
let aggregateRefreshVersion = 0;
let draggedAliasId = null;
let draggedMemberKey = null;

const AGGREGATE_TYPE_OPTIONS = [
  { id: 'all', label: '全部' },
  { id: 'dialog', label: '对话' },
  { id: 'image', label: '图像' },
  { id: 'agent', label: 'Agent' },
  { id: 'coding', label: '编程' },
  { id: 'reasoning', label: '推理' },
];

const AGGREGATE_SCORE_OPTIONS = [
  { id: 'all', label: '全部' },
  { id: '1-20', label: '1-20' },
  { id: '21-40', label: '21-40' },
  { id: '41-60', label: '41-60' },
  { id: '61-80', label: '61-80' },
  { id: '81-100', label: '81-100' },
];

const AGGREGATE_TYPE_MATCHERS = {
  dialog: ['chat', 'instruct', 'llama', 'trinity', 'sonnet', 'opus', 'gpt-', 'kimi-', 'glm-', 'gemini-'],
  image: ['image', 'vision', '-vl', '/vl', 'veo', 'hunyuan-image', 'riverflow'],
  agent: ['agent', 'tool', 'coder', 'coding', 'm2.5', 'qwen3-coder', 'auto'],
  coding: ['coder', 'coding', 'codex', 'kat-coder', 'kimi-for-coding'],
  reasoning: ['thinking', 'reasoning', 'step-3.5', 'opus', 'sonnet', 'm2.5'],
};

function setAggregateText(id, value) {
  const el = document.getElementById(id);
  if (el) el.textContent = String(value ?? '');
}

function escapeAggregateHtml(value) {
  return String(value ?? '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

function aggregateMemberKey(provider, upstreamId) {
  return `${String(provider || '').trim().toLowerCase()}::${String(upstreamId || '').trim()}`;
}

function aggregateLookupText(row) {
  return [
    String(row?.call_id || '').trim().toLowerCase(),
    String(row?.lookup_upstream_id || row?.upstream_id || '').trim().toLowerCase(),
  ].filter(Boolean).join(' ');
}

function aggregateProviderKey(item) {
  return String(item?.lookup_provider || item?.provider || '').trim().toLowerCase();
}

function aggregateProviderNames() {
  const sourceItems = aggregateProviderSummariesCache.length ? aggregateProviderSummariesCache : aggregateProviderItemsCache;
  return sourceItems
    .map(aggregateProviderKey)
    .filter(Boolean)
    .filter((value, index, arr) => arr.indexOf(value) === index);
}

function ensureAggregateProviderFilter() {
  const names = aggregateProviderNames();
  if (!names.length) {
    activeAggregateProviderFilter = '';
    return '';
  }
  if (activeAggregateProviderFilter === 'all') return activeAggregateProviderFilter;
  if (!activeAggregateProviderFilter || !names.includes(activeAggregateProviderFilter)) {
    activeAggregateProviderFilter = names[0];
  }
  return activeAggregateProviderFilter;
}

function deriveAggregateModelTypes(row) {
  const text = aggregateLookupText(row);
  const categories = new Set();
  Object.entries(AGGREGATE_TYPE_MATCHERS).forEach(([typeId, tokens]) => {
    if (tokens.some((token) => text.includes(token))) categories.add(typeId);
  });
  if (!categories.size) categories.add('dialog');
  return [...categories];
}

function aggregateModelRawScore(row) {
  const text = aggregateLookupText(row);
  let score = 48;

  const familyRules = [
    ['gpt-5.4', 97],
    ['gpt-5.3-codex', 95],
    ['gpt-5.2-codex', 92],
    ['gpt-5.2', 90],
    ['gpt-5.1-codex-max', 93],
    ['gpt-5.1-codex-mini', 80],
    ['gpt-5.1-codex', 88],
    ['gpt-5.1', 86],
    ['gpt-5.4-mini', 82],
    ['gpt-5-codex-mini', 78],
    ['gpt-5-codex', 90],
    ['gpt-5', 88],
    ['claude-opus-4-6-thinking', 94],
    ['claude-opus', 92],
    ['claude-sonnet-4-6', 89],
    ['claude-sonnet-4-5-thinking', 88],
    ['claude-sonnet-4-5', 86],
    ['gemini-3.1-pro-high', 87],
    ['gemini-3.1-pro', 84],
    ['gemini-3-pro-high', 82],
    ['gemini-3-pro-low', 75],
    ['gemini-3.1-flash-image', 72],
    ['gemini-3-flash', 74],
    ['gemini-2.5-pro', 80],
    ['gemini-2.5-flash-thinking', 72],
    ['gemini-2.5-flash-lite', 58],
    ['gemini-2.5-flash', 65],
    ['coding-glm-5-turbo', 84],
    ['coding-glm-5', 81],
    ['glm-5-turbo', 82],
    ['glm-5', 79],
    ['glm-4.7-flash', 73],
    ['glm-4.7', 78],
    ['glm-4.6v-flash', 70],
    ['glm-4.6v', 72],
    ['qwen3-coder', 83],
    ['qwen3-next-80b-a3b-instruct', 80],
    ['qwen3-next', 78],
    ['llama-3.3-70b-instruct', 76],
    ['mistral-small-3.1-24b-instruct', 72],
    ['minimax-m2.7', 86],
    ['minimax-m2.5', 82],
    ['minimax-m2.1', 70],
    ['step-3.5-flash', 73],
    ['gpt-4o', 80],
    ['gpt-4.1-mini', 68],
    ['gpt-4.1-nano', 42],
    ['gpt-4.1', 78],
    ['gpt-oss-120b', 71],
    ['kimi-k2.5', 76],
    ['kimi-k2-thinking', 72],
    ['kimi-k2', 68],
    ['hunyuan-image3', 62],
    ['veo-3.1', 66],
    ['glm-image', 64],
    ['riverflow-v2-pro', 60],
    ['riverflow-v2-fast', 54],
    ['mimo-v2-flash', 50],
    ['kat-coder-pro-v1', 66],
    ['free', 52],
    ['auto', 50],
  ];
  for (const [token, value] of familyRules) {
    if (text.includes(token)) {
      score = value;
      break;
    }
  }

  const adjustments = [
    ['codex-max', 3],
    ['thinking', 3],
    ['reasoning', 3],
    ['image', 2],
    ['vision', 2],
    ['coder', 4],
    ['coding', 3],
    ['agent', 2],
    ['tool', 1],
    ['mini', -6],
    ['nano', -16],
    ['flash-lite', -8],
    ['lite', -4],
    ['1.2b', -24],
    ['4b', -18],
    ['12b', -10],
    ['free', -2],
  ];
  adjustments.forEach(([token, value]) => {
    if (text.includes(token)) score += value;
  });

  return Math.max(0, Math.min(100, score));
}

function aggregateMemberScore(member) {
  return Number(aggregateModelRawScore({
    call_id: member?.call_id,
    lookup_upstream_id: member?.runtime_upstream_id || member?.upstream_id,
    upstream_id: member?.runtime_upstream_id || member?.upstream_id,
  }));
}

function aggregateModelStatusLabel(status) {
  if (status === 'ok') return '可用';
  if (status === 'testing') return '检测中';
  if (status === 'bad') return '不可用';
  return '待检测';
}

function aggregateModelStatusClass(status) {
  if (status === 'ok') return 'status-ok';
  if (status === 'testing') return 'status-testing';
  if (status === 'bad') return 'status-bad';
  return 'status-pending';
}

function cloneAggregateItems(items = aggregateItemsCache) {
  return items.map((item) => ({
    ...item,
    members: Array.isArray(item.members) ? item.members.map((member) => ({ ...member })) : [],
  }));
}

function nextAggregateCopyAliasId(aliasId) {
  const baseId = `${String(aliasId || '').trim()}-copy`;
  const existingIds = new Set(aggregateItemsCache.map((item) => String(item.alias_id || '').trim()).filter(Boolean));
  if (!existingIds.has(baseId)) return baseId;
  for (let index = 2; index < 1000; index += 1) {
    const candidate = `${baseId}-${index}`;
    if (!existingIds.has(candidate)) return candidate;
  }
  return `${baseId}-${Date.now()}`;
}

function aggregateMemberPayload(members) {
  return (Array.isArray(members) ? members : []).map((member) => ({
    provider: member.provider,
    upstream_id: member.upstream_id,
  })).filter((member) => member.provider && member.upstream_id);
}

function normalizeAggregateVersion(version) {
  const value = String(version || '1').trim();
  return ['1', '2', '3'].includes(value) ? value : '1';
}

function aggregateActiveVersion(item) {
  return normalizeAggregateVersion(item?.active_version || '1');
}

function getAggregateVersionMembers(item, version = viewedAggregateAliasVersion) {
  if (!item) return [];
  const targetVersion = normalizeAggregateVersion(version);
  const versionMembers = item[`version_${targetVersion}_members`];
  if (Array.isArray(versionMembers)) return versionMembers;
  if (targetVersion === aggregateActiveVersion(item) && Array.isArray(item.members)) return item.members;
  return [];
}

function getActiveAggregateItem() {
  return aggregateItemsCache.find((item) => item.alias_id === activeAggregateAliasId) || null;
}

function syncViewedAggregateVersionForActiveAlias(force = false) {
  const current = getActiveAggregateItem();
  if (!current?.alias_id) {
    viewedAggregateAliasId = '';
    viewedAggregateAliasVersion = '1';
    return;
  }
  const aliasId = String(current.alias_id || '').trim();
  if (force || viewedAggregateAliasId !== aliasId) {
    viewedAggregateAliasId = aliasId;
    viewedAggregateAliasVersion = aggregateActiveVersion(current);
    return;
  }
  viewedAggregateAliasVersion = normalizeAggregateVersion(viewedAggregateAliasVersion);
}

function hasAggregatePendingWork() {
  return aggregateMemberPendingKeys.size > 0
    || aggregateAliasPendingIds.size > 0
    || aggregateMemberSavingAliases.size > 0
    || aggregateMemberSaveDebounces.size > 0
    || aggregateMemberSaveChains.size > 0;
}

function renderAggregateCurrentViews(includeSources = false) {
  renderAggregateAliasList();
  renderAggregateActiveDetails();
  if (includeSources && aggregateSourceListLoaded) renderAggregateProviderSourceList();
}

function updateAggregateMembersInCache(aliasId, members, version = null) {
  const targetId = String(aliasId || '').trim();
  const index = aggregateItemsCache.findIndex((item) => String(item.alias_id || '').trim() === targetId);
  if (index < 0) return false;
  const normalizedMembers = Array.isArray(members) ? members : [];
  const updatedItem = {
    ...aggregateItemsCache[index],
  };
  const targetVersion = normalizeAggregateVersion(version || viewedAggregateAliasVersion);
  updatedItem[`version_${targetVersion}_members`] = normalizedMembers;
  const activeVersion = aggregateActiveVersion(updatedItem);
  if (targetVersion === activeVersion) {
    updatedItem.members = normalizedMembers;
    updatedItem.member_count = normalizedMembers.length;
  }
  aggregateItemsCache[index] = updatedItem;
  return true;
}

function nextAggregateMemberMutationVersion(aliasId) {
  const targetId = String(aliasId || '').trim();
  const nextVersion = (aggregateMemberMutationVersions.get(targetId) || 0) + 1;
  aggregateMemberMutationVersions.set(targetId, nextVersion);
  return nextVersion;
}

async function applyAggregateRuntime(button) {
  const run = async () => {
    try {
      const hasMemberSaveWork = aggregateMemberSavingAliases.size > 0
        || aggregateMemberSaveDebounces.size > 0
        || aggregateMemberSaveChains.size > 0;
      if (hasMemberSaveWork) {
        const saved = await flushPendingAggregateMemberSaves();
        if (!saved) throw new Error(getLanguage() === 'zh' ? '仍有聚合成员修改保存失败，未应用 Runtime。' : 'Some aggregate member changes failed to save; runtime was not applied.');
      }
      if (aggregateAliasPendingIds.size > 0 || aggregateMemberPendingKeys.size > 0) {
        throw new Error(getLanguage() === 'zh' ? '仍有聚合修改正在保存，请稍后再应用 Runtime。' : 'Aggregate changes are still saving; apply runtime again in a moment.');
      }
      const res = await api('/api/aggregate-models/apply-runtime', 'POST');
      showMessage(res.message || (getLanguage() === 'zh' ? '聚合 Runtime 配置已重建。' : 'Aggregate runtime config rebuilt.'));
      if (typeof refreshStatus === 'function') await refreshStatus();
      return res;
    } catch (error) {
      showMessage(error.message, true);
      return null;
    }
  };
  if (typeof withRuntimeAction === 'function') {
    return withRuntimeAction(button, getLanguage() === 'zh' ? '应用中...' : 'Applying...', run);
  }
  if (!button) return run();
  const previousText = button.textContent;
  const previousDisabled = button.disabled;
  button.disabled = true;
  button.textContent = getLanguage() === 'zh' ? '应用中...' : 'Applying...';
  try {
    return await run();
  } catch (error) {
    showMessage(error.message, true);
    return null;
  } finally {
    button.disabled = previousDisabled;
    button.textContent = previousText;
  }
}

function isLatestAggregateMemberMutation(aliasId, version) {
  return aggregateMemberMutationVersions.get(String(aliasId || '').trim()) === version;
}

function hasAggregateMemberSaveWork(aliasId) {
  const targetId = String(aliasId || '').trim();
  return Boolean(targetId) && (
    aggregateMemberSavingAliases.has(targetId)
    || aggregateMemberSaveDebounces.has(targetId)
    || aggregateMemberSaveChains.has(targetId)
  );
}

function flushAggregateMemberSave(targetId, entry) {
  if (aggregateMemberSaveDebounces.get(targetId) === entry) {
    aggregateMemberSaveDebounces.delete(targetId);
  }

  const previous = aggregateMemberSaveChains.get(targetId) || Promise.resolve(true);
  const next = previous.catch(() => false).then(async () => {
    aggregateMemberSavingAliases.add(targetId);
    renderAggregateAliasList();
    try {
      await api('/api/aggregate-models', 'POST', {
        action: 'set_members',
        alias_id: targetId,
        members: entry.payloadMembers,
        skip_restart: entry.skipRestart,
        version: entry.version,
      });
      if (entry.successMessage) showMessage(entry.successMessage);
      return true;
    } catch (err) {
      showMessage(err.message, true);
      return false;
    } finally {
      aggregateMemberSavingAliases.delete(targetId);
      renderAggregateCurrentViews(true);
    }
  });
  const tracked = next.finally(() => {
    if (aggregateMemberSaveChains.get(targetId) === tracked) aggregateMemberSaveChains.delete(targetId);
  });
  aggregateMemberSaveChains.set(targetId, tracked);
  tracked.then(
    (ok) => entry.resolvers.forEach((resolve) => resolve(Boolean(ok))),
    () => entry.resolvers.forEach((resolve) => resolve(false))
  );
  return tracked;
}

async function flushPendingAggregateMemberSaves() {
  const saves = [];
  aggregateMemberSaveDebounces.forEach((entry, targetId) => {
    if (entry.timer) {
      clearTimeout(entry.timer);
      entry.timer = null;
    }
    saves.push(flushAggregateMemberSave(targetId, entry));
  });
  if (saves.length) {
    const results = await Promise.all(saves);
    if (results.some((ok) => !ok)) return false;
  }
  const activeChains = Array.from(aggregateMemberSaveChains.values());
  if (activeChains.length) {
    const results = await Promise.all(activeChains);
    if (results.some((ok) => !ok)) return false;
  }
  await Promise.resolve();
  return true;
}

async function queueAggregateMemberSave(aliasId, members, successMessage = '', skipRestart = true, version = null) {
  const targetId = String(aliasId || '').trim();
  if (!targetId) return false;
  const payloadMembers = aggregateMemberPayload(members);
  renderAggregateCurrentViews(true);

  const targetVersion = normalizeAggregateVersion(version || viewedAggregateAliasVersion);

  return new Promise((resolve) => {
    let entry = aggregateMemberSaveDebounces.get(targetId);
    if (!entry) {
      entry = {
        timer: null,
        payloadMembers,
        successMessage,
        skipRestart: Boolean(skipRestart),
        version: targetVersion,
        resolvers: [],
      };
      aggregateMemberSaveDebounces.set(targetId, entry);
    }

    entry.payloadMembers = payloadMembers;
    entry.successMessage = successMessage;
    entry.skipRestart = Boolean(skipRestart);
    entry.version = targetVersion;
    entry.resolvers.push(resolve);

    if (entry.timer) clearTimeout(entry.timer);
    entry.timer = setTimeout(() => {
      flushAggregateMemberSave(targetId, entry);
    }, AGGREGATE_MEMBER_SAVE_DEBOUNCE_MS);
  });
}

function updateAggregateWorkbenchStats() {
  const selected = aggregateEditMode ? aggregateEditMembers.size : 0;
  setAggregateText('aggregate-selected-count', getLanguage() === 'zh' ? `已选 ${selected}` : `${selected} selected`);
}

async function syncAggregateModelTestState() {
  try {
    const data = await api('/api/provider-model-test-state');
    const results = data.results || {};
    aggregateModelsRunningSet = new Set(Array.isArray(data.running) ? data.running : []);
    aggregateModelStatuses = {};
    aggregateModelStatusMeta = {};
    Object.entries(results).forEach(([modelId, item]) => {
      if (aggregateModelsRunningSet.has(modelId) || item?.status === 'testing') {
        aggregateModelStatuses[modelId] = 'testing';
      } else if (item?.available) {
        aggregateModelStatuses[modelId] = 'ok';
      } else if (item) {
        aggregateModelStatuses[modelId] = 'bad';
      }
      aggregateModelStatusMeta[modelId] = {
        elapsed_ms: item?.elapsed_ms,
        retry_after_seconds: item?.retry_after_seconds,
        tested_at: item?.tested_at,
        status_code: item?.status_code,
        failure_kind: item?.failure_kind,
        message: item?.message,
      };
    });
  } catch {
    aggregateModelsRunningSet = new Set();
  }
}

function matchesAggregateScoreFilter(score, filterId = activeAggregateScoreFilter) {
  const value = Number(score || 0);
  if (filterId === 'all') return true;
  if (filterId === '1-20') return value >= 1 && value <= 20;
  if (filterId === '21-40') return value >= 21 && value <= 40;
  if (filterId === '41-60') return value >= 41 && value <= 60;
  if (filterId === '61-80') return value >= 61 && value <= 80;
  if (filterId === '81-100') return value >= 81 && value <= 100;
  return true;
}

async function fetchAggregateItems() {
  const res = await api('/api/aggregate-models');
  aggregateItemsCache = Array.isArray(res.items) ? res.items : [];
  return aggregateItemsCache;
}

async function fetchAggregateProviderSummaries() {
  const res = await api('/api/provider-models?providers_only=1');
  aggregateProviderSummariesCache = Array.isArray(res.items) ? res.items : [];
  return aggregateProviderSummariesCache;
}

async function fetchAggregateProviderItems(provider) {
  const providerKey = String(provider || '').trim().toLowerCase();
  if (!providerKey) {
    aggregateProviderItemsCache = [];
    return aggregateProviderItemsCache;
  }
  if (providerKey === 'all') {
    const providerNames = aggregateProviderNames();
    const cachedItems = providerNames
      .map((key) => aggregateProviderItemCache.get(key))
      .filter(Boolean);
    if (providerNames.length && cachedItems.length === providerNames.length) {
      aggregateProviderItemsCache = cachedItems;
      return aggregateProviderItemsCache;
    }
    const res = await api('/api/provider-models');
    aggregateProviderItemsCache = Array.isArray(res.items) ? res.items : [];
    aggregateProviderItemsCache.forEach((item) => {
      const key = aggregateProviderKey(item);
      if (key) aggregateProviderItemCache.set(key, item);
    });
    return aggregateProviderItemsCache;
  }
  if (aggregateProviderItemCache.has(providerKey)) {
    aggregateProviderItemsCache = [aggregateProviderItemCache.get(providerKey)];
    return aggregateProviderItemsCache;
  }
  const res = await api(`/api/provider-models?provider=${encodeURIComponent(providerKey)}`);
  const items = Array.isArray(res.items) ? res.items : [];
  items.forEach((item) => {
    const key = aggregateProviderKey(item);
    if (key) aggregateProviderItemCache.set(key, item);
  });
  aggregateProviderItemsCache = items;
  return aggregateProviderItemsCache;
}

async function loadAggregateActiveProviderRows() {
  const provider = ensureAggregateProviderFilter();
  if (!provider) {
    aggregateProviderItemsCache = [];
    return;
  }
  aggregateProviderRowsLoading = true;
  renderAggregateProviderSourceList();
  try {
    await fetchAggregateProviderItems(provider);
  } finally {
    aggregateProviderRowsLoading = false;
  }
}

async function refreshAggregateRoutePreview() {
  const aliasId = String(activeAggregateAliasId || '').trim();
  if (!aliasId) {
    aggregateRoutePreviewCache = {};
    return aggregateRoutePreviewCache;
  }
  try {
    const res = await api(`/api/model-route-preview?model=${encodeURIComponent(aliasId)}`);
    aggregateRoutePreviewCache = res?.item || {};
  } catch {
    aggregateRoutePreviewCache = {};
  }
  return aggregateRoutePreviewCache;
}

async function refreshAggregateRouteHealth() {
  try {
    const res = await api('/api/aggregate-route-health');
    aggregateRouteHealthCache = res || {};
  } catch {
    aggregateRouteHealthCache = {};
  }
  return aggregateRouteHealthCache;
}

function findAggregateMemberRuntimeRow(member) {
  if (!aggregateProviderItemsCache.length) return null;
  const provider = String(member?.provider || '').trim().toLowerCase();
  const upstreamId = String(member?.upstream_id || '').trim();
  const callId = String(member?.call_id || '').trim();
  if (!provider) return null;
  for (const item of aggregateProviderItemsCache) {
    const itemProvider = aggregateProviderKey(item);
    if (itemProvider !== provider) continue;
    for (const row of Array.isArray(item.rows) ? item.rows : []) {
      const rowCallId = String(row.call_id || '').trim();
      const rowUpstream = String(row.lookup_upstream_id || row.upstream_id || '').trim();
      if (callId && rowCallId && rowCallId === callId) return row;
      if (upstreamId && rowUpstream && rowUpstream === upstreamId) return row;
    }
  }
  return null;
}

function aggregateMemberRuntimeState(member) {
  const row = findAggregateMemberRuntimeRow(member);
  return {
    row,
    runtimeRegistered: Boolean(row?.runtime_registered),
  };
}

function renderAggregateAliasList() {
  const root = document.getElementById('aggregate-alias-list');
  const total = document.getElementById('aggregate-total-count');
  if (!root || !total) return;

  total.textContent = String(aggregateItemsCache.length);
  updateAggregateWorkbenchStats();
  if (!aggregateItemsCache.length) {
    root.innerHTML = `<div class="auth-empty">${getLanguage() === 'zh' ? '暂无聚合 ID。' : 'No aggregate IDs yet.'}</div>`;
    return;
  }
  let items = [...aggregateItemsCache];
  if (aggregateSortMode === 'name') {
    items.sort((a, b) => String(a.alias_id || '').localeCompare(String(b.alias_id || '')));
  }

  if (!items.some((item) => item.alias_id === activeAggregateAliasId)) {
    activeAggregateAliasId = String(items[0]?.alias_id || '');
    syncViewedAggregateVersionForActiveAlias(true);
  } else {
    syncViewedAggregateVersionForActiveAlias();
  }

  const isSorted = aggregateSortMode !== 'default';

  root.innerHTML = items.map((item) => {
    const aliasId = String(item.alias_id || '').trim();
    const count = Number(item.member_count || 0);
    const enabled = item.enabled !== false;
    const isActive = aliasId === activeAggregateAliasId;
    const aliasPending = aggregateAliasPendingIds.has(aliasId);
    const controlsDisabled = hasAggregatePendingWork() ? 'disabled' : '';
    const toggleLabel = enabled
      ? (getLanguage() === 'zh' ? '禁用' : 'Disable')
      : (getLanguage() === 'zh' ? '启用' : 'Enable');
    const dragHandleHtml = isSorted
      ? `<div class="aggregate-alias-drag-handle is-disabled" style="opacity: 0.25; cursor: not-allowed;" title="${getLanguage() === 'zh' ? '当前排序模式下不可拖动' : 'Cannot drag in current sort mode'}">☰</div>`
      : `<div class="aggregate-alias-drag-handle" title="${getLanguage() === 'zh' ? '拖动排序' : 'Drag to reorder'}">☰</div>`;

    const isEditing = editingAliasId === aliasId;
    const chipHtml = isEditing
      ? `<input type="text" class="aggregate-alias-rename-input" data-rename-original="${escapeAggregateHtml(aliasId)}" value="${escapeAggregateHtml(aliasId)}" style="flex: 1; height: 32px; padding: 0 10px; border-radius: 6px; border: 1px solid var(--accent); background: var(--panel-2); color: var(--text); font-size: 13px; font-weight: 800; min-width: 0;" />`
      : `<button type="button" class="aggregate-alias-chip ${isActive ? 'is-active' : ''}" data-aggregate-alias="${escapeAggregateHtml(aliasId)}" ${aliasPending ? 'disabled' : ''}>
          <span>${escapeAggregateHtml(aliasId)}</span>
          <strong>${count} ${getLanguage() === 'zh' ? '个' : ''}</strong>
        </button>`;

    const actionsHtml = isEditing
      ? `<button type="button" class="secondary aggregate-alias-action" data-aggregate-alias-save="${escapeAggregateHtml(aliasId)}">${getLanguage() === 'zh' ? '保存' : 'Save'}</button>
         <button type="button" class="secondary aggregate-alias-action" data-aggregate-alias-cancel="${escapeAggregateHtml(aliasId)}">${getLanguage() === 'zh' ? '取消' : 'Cancel'}</button>`
      : `<button type="button" class="secondary aggregate-alias-action aggregate-alias-enable-action" data-aggregate-alias-enabled="${escapeAggregateHtml(aliasId)}" data-enabled="${enabled ? '1' : '0'}" ${controlsDisabled}>${toggleLabel}</button>
         <button type="button" class="secondary aggregate-alias-action" data-aggregate-alias-copy="${escapeAggregateHtml(aliasId)}" ${controlsDisabled}>复制</button>
         <button type="button" class="secondary aggregate-alias-action" data-aggregate-alias-rename="${escapeAggregateHtml(aliasId)}" ${controlsDisabled}>改名</button>
         <button type="button" class="danger aggregate-alias-action" data-aggregate-alias-delete="${escapeAggregateHtml(aliasId)}" ${controlsDisabled}>删除</button>`;

    return `
      <div class="aggregate-alias-row ${isActive ? 'is-active' : ''} ${aliasPending ? 'is-pending' : ''} ${enabled ? '' : 'is-disabled'}" ${isSorted ? '' : 'draggable="true"'} data-alias-id="${escapeAggregateHtml(aliasId)}">
        ${dragHandleHtml}
        ${chipHtml}
        <div class="aggregate-alias-actions">
          ${actionsHtml}
        </div>
      </div>
    `;
  }).join('');
  root.querySelectorAll('[data-aggregate-alias]').forEach((btn) => {
    btn.onclick = () => {
      activeAggregateAliasId = btn.getAttribute('data-aggregate-alias') || '';
      syncViewedAggregateVersionForActiveAlias(true);
      aggregateEditMode = false;
      aggregateEditMembers.clear();
      renderAggregateAliasList();
      renderAggregateActiveDetails();
      renderAggregateProviderSourceList();
      void refreshAggregateRoutePreview().then(() => {
        if (typeof getActiveSection === 'function' && getActiveSection() === 'aggregates') {
          renderAggregateActiveDetails();
        }
      });
    };
  });
  root.querySelectorAll('[data-aggregate-alias-delete]').forEach((btn) => {
    btn.onclick = async (event) => {
      event.stopPropagation();
      await deleteAggregateAlias(btn.getAttribute('data-aggregate-alias-delete') || '');
    };
  });

  root.querySelectorAll('[data-aggregate-alias-rename]').forEach((btn) => {
    btn.onclick = (event) => {
      event.stopPropagation();
      editingAliasId = btn.getAttribute('data-aggregate-alias-rename') || '';
      renderAggregateAliasList();
      setTimeout(() => {
        const input = root.querySelector('.aggregate-alias-rename-input');
        if (input) {
          input.focus();
          input.select();
        }
      }, 50);
    };
  });
  root.querySelectorAll('[data-aggregate-alias-save]').forEach((btn) => {
    btn.onclick = async (event) => {
      event.stopPropagation();
      const originalId = btn.getAttribute('data-aggregate-alias-save');
      const input = root.querySelector(`.aggregate-alias-rename-input[data-rename-original="${escapeAggregateHtml(originalId)}"]`);
      if (input) {
        await renameAggregateAlias(originalId, input.value.trim());
      }
    };
  });
  root.querySelectorAll('[data-aggregate-alias-cancel]').forEach((btn) => {
    btn.onclick = (event) => {
      event.stopPropagation();
      editingAliasId = '';
      renderAggregateAliasList();
    };
  });
  root.querySelectorAll('.aggregate-alias-rename-input').forEach((input) => {
    input.onkeydown = async (e) => {
      if (e.key === 'Enter') {
        const originalId = input.getAttribute('data-rename-original');
        await renameAggregateAlias(originalId, input.value.trim());
      } else if (e.key === 'Escape') {
        editingAliasId = '';
        renderAggregateAliasList();
      }
    };
    input.onclick = (e) => {
      e.stopPropagation();
    };
  });

  root.querySelectorAll('[data-aggregate-alias-copy]').forEach((btn) => {
    btn.onclick = async (event) => {
      event.stopPropagation();
      await copyAggregateAlias(btn.getAttribute('data-aggregate-alias-copy') || '');
    };
  });
  root.querySelectorAll('[data-aggregate-alias-enabled]').forEach((btn) => {
    btn.onclick = async (event) => {
      event.stopPropagation();
      const aliasId = btn.getAttribute('data-aggregate-alias-enabled') || '';
      const nextEnabled = btn.getAttribute('data-enabled') !== '1';
      await toggleAggregateAliasEnabled(aliasId, nextEnabled);
    };
  });

  root.querySelectorAll('.aggregate-alias-row').forEach((row) => {
    row.addEventListener('dragstart', (e) => {
      draggedAliasId = row.getAttribute('data-alias-id');
      row.classList.add('is-dragging');
      e.dataTransfer.effectAllowed = 'move';
    });
    row.addEventListener('dragend', () => {
      draggedAliasId = null;
      row.classList.remove('is-dragging');
      root.querySelectorAll('.aggregate-alias-row').forEach((r) => r.classList.remove('drag-over'));
    });
    row.addEventListener('dragover', (e) => {
      e.preventDefault();
      if (draggedAliasId && draggedAliasId !== row.getAttribute('data-alias-id')) {
        row.classList.add('drag-over');
      }
    });
    row.addEventListener('dragleave', () => {
      row.classList.remove('drag-over');
    });
    row.addEventListener('drop', (e) => {
      e.preventDefault();
      const targetId = row.getAttribute('data-alias-id');
      row.classList.remove('drag-over');
      if (draggedAliasId && targetId && draggedAliasId !== targetId) {
        void reorderAggregateAliases(draggedAliasId, targetId);
      }
    });
  });
}

function changeAggregateSort(mode) {
  aggregateSortMode = mode;
  const btnDefault = document.getElementById('btn-sort-default');
  const btnName = document.getElementById('btn-sort-name');
  if (btnDefault && btnName) {
    btnDefault.classList.toggle('is-active', mode === 'default');
    btnName.classList.toggle('is-active', mode === 'name');
  }
  renderAggregateAliasList();
}

async function reorderAggregateAliases(draggedId, targetId) {
  if (hasAggregatePendingWork() || aggregateAliasPendingIds.has(draggedId) || aggregateAliasPendingIds.has(targetId)) return;

  const currentIndex = aggregateItemsCache.findIndex((item) => String(item.alias_id || '').trim() === draggedId);
  const targetIndex = aggregateItemsCache.findIndex((item) => String(item.alias_id || '').trim() === targetId);
  if (currentIndex < 0 || targetIndex < 0 || currentIndex === targetIndex) return;

  aggregateAliasPendingIds.add(draggedId);
  aggregateAliasPendingIds.add(targetId);

  const previousItems = cloneAggregateItems();
  const reordered = [...aggregateItemsCache];
  const [removed] = reordered.splice(currentIndex, 1);
  reordered.splice(targetIndex, 0, removed);
  aggregateItemsCache = reordered;
  renderAggregateAliasList();

  try {
    const orderedIds = reordered.map((item) => item.alias_id);
    await api('/api/aggregate-models', 'POST', {
      action: 'reorder',
      ordered_ids: orderedIds,
      skip_restart: true,
    });
    showMessage(getLanguage() === 'zh' ? '已保存聚合顺序。' : 'Saved aggregate order.');
  } catch (error) {
    aggregateItemsCache = previousItems;
    showMessage(getLanguage() === 'zh' ? `移动聚合 ID 失败：${error.message}` : `Failed to move aggregate ID: ${error.message}`, true);
  } finally {
    aggregateAliasPendingIds.delete(draggedId);
    aggregateAliasPendingIds.delete(targetId);
    renderAggregateAliasList();
  }
}

async function moveAggregateAlias(aliasId, direction) {
  const targetId = String(aliasId || '').trim();
  if (!targetId) return;
  const currentIndex = aggregateItemsCache.findIndex((item) => String(item.alias_id || '').trim() === targetId);
  if (currentIndex < 0) return;
  const nextIndex = currentIndex + (direction < 0 ? -1 : 1);
  if (nextIndex < 0 || nextIndex >= aggregateItemsCache.length) return;

  if (aggregateAliasPendingIds.has(targetId) || hasAggregatePendingWork()) return;
  aggregateAliasPendingIds.add(targetId);

  const previousItems = cloneAggregateItems();
  const reordered = [...aggregateItemsCache];
  [reordered[currentIndex], reordered[nextIndex]] = [reordered[nextIndex], reordered[currentIndex]];
  aggregateItemsCache = reordered;
  renderAggregateAliasList();

  try {
    await api('/api/aggregate-models', 'POST', {
      action: 'move',
      alias_id: targetId,
      direction,
      skip_restart: true,
    });
    showMessage(getLanguage() === 'zh' ? `已保存聚合顺序：${targetId}。` : `Saved aggregate order: ${targetId}.`);
  } catch (error) {
    aggregateItemsCache = previousItems;
    renderAggregateAliasList();
    showMessage(getLanguage() === 'zh' ? `移动聚合 ID 失败：${error.message}` : `Failed to move aggregate ID: ${error.message}`, true);
  } finally {
    aggregateAliasPendingIds.delete(targetId);
    renderAggregateAliasList();
  }
}

async function deleteAggregateAlias(aliasId) {
  const targetId = String(aliasId || '').trim();
  if (!targetId || aggregateAliasPendingIds.has(targetId) || hasAggregatePendingWork()) return;
  aggregateAliasPendingIds.add(targetId);
  const previousItems = cloneAggregateItems();
  aggregateItemsCache = aggregateItemsCache.filter((item) => String(item.alias_id || '').trim() !== targetId);
  if (activeAggregateAliasId === targetId) {
    activeAggregateAliasId = String(aggregateItemsCache[0]?.alias_id || '');
  }
  renderAggregateCurrentViews(true);

  try {
    await api('/api/aggregate-models', 'POST', {
      action: 'delete',
      alias_id: targetId,
      skip_restart: true,
    });
    showMessage(getLanguage() === 'zh' ? `已删除聚合 ID：${targetId}。` : `Deleted aggregate ID: ${targetId}.`);
  } catch (error) {
    aggregateItemsCache = previousItems;
    if (!activeAggregateAliasId) {
      activeAggregateAliasId = targetId;
    }
    renderAggregateCurrentViews(true);
    showMessage(getLanguage() === 'zh' ? `删除聚合 ID 失败：${error.message}` : `Failed to delete aggregate ID: ${error.message}`, true);
  } finally {
    aggregateAliasPendingIds.delete(targetId);
    renderAggregateCurrentViews(true);
  }
}

async function toggleAggregateAliasEnabled(aliasId, enabled) {
  const targetId = String(aliasId || '').trim();
  if (!targetId || aggregateAliasPendingIds.has(targetId) || hasAggregatePendingWork()) return;
  const previousItems = cloneAggregateItems();
  const index = aggregateItemsCache.findIndex((item) => String(item.alias_id || '').trim() === targetId);
  if (index < 0) return;

  aggregateAliasPendingIds.add(targetId);
  aggregateItemsCache[index] = {
    ...aggregateItemsCache[index],
    enabled: Boolean(enabled),
  };
  renderAggregateCurrentViews(true);

  try {
    const res = await api('/api/aggregate-models', 'POST', {
      action: 'set_enabled',
      alias_id: targetId,
      enabled: Boolean(enabled),
      skip_restart: true,
    });
    showMessage(res.message || (getLanguage() === 'zh'
      ? `${enabled ? '已启用' : '已禁用'}聚合 ID：${targetId}。`
      : `${enabled ? 'Enabled' : 'Disabled'} aggregate ID: ${targetId}.`));
    await loadAggregateModels(true);
    if (typeof loadProviderModels === 'function') void loadProviderModels();
  } catch (error) {
    aggregateItemsCache = previousItems;
    renderAggregateCurrentViews(true);
    showMessage(getLanguage() === 'zh'
      ? `切换聚合 ID 状态失败：${error.message}`
      : `Failed to toggle aggregate ID: ${error.message}`, true);
  } finally {
    aggregateAliasPendingIds.delete(targetId);
    renderAggregateCurrentViews(true);
  }
}

async function copyAggregateAlias(aliasId) {
  const sourceId = String(aliasId || '').trim();
  if (!sourceId || aggregateAliasPendingIds.has(sourceId) || hasAggregatePendingWork()) return;
  const source = aggregateItemsCache.find((item) => String(item.alias_id || '').trim() === sourceId);
  if (!source) {
    showMessage(getLanguage() === 'zh' ? '未找到要复制的聚合 ID。' : 'Aggregate ID not found.', true);
    return;
  }

  const nextId = window.prompt(
    getLanguage() === 'zh' ? '复制为新的聚合 model ID' : 'Copy as new aggregate model ID',
    nextAggregateCopyAliasId(sourceId)
  );
  if (nextId === null) return;
  const normalized = String(nextId || '').trim();
  if (!normalized) return;
  if (aggregateItemsCache.some((item) => String(item.alias_id || '').trim() === normalized)) {
    showMessage(getLanguage() === 'zh' ? `聚合 ID 已存在：${normalized}` : `Aggregate ID already exists: ${normalized}`, true);
    return;
  }

  aggregateAliasPendingIds.add(sourceId);
  aggregateAliasPendingIds.add(normalized);
  renderAggregateAliasList();
  try {
    const res = await api('/api/aggregate-models', 'POST', {
      action: 'copy',
      alias_id: sourceId,
      new_alias_id: normalized,
      skip_restart: true,
    });
    activeAggregateAliasId = normalized;
    aggregateEditMode = false;
    aggregateEditMembers.clear();
    showMessage(res.message || (getLanguage() === 'zh'
      ? `已复制 ${sourceId} 为 ${normalized}，新副本默认禁用。`
      : `Copied ${sourceId} to ${normalized}. The copy is disabled by default.`));
    await loadAggregateModels(true);
  } catch (error) {
    showMessage(getLanguage() === 'zh' ? `复制聚合 ID 失败：${error.message}` : `Failed to copy aggregate ID: ${error.message}`, true);
  } finally {
    aggregateAliasPendingIds.delete(sourceId);
    aggregateAliasPendingIds.delete(normalized);
    renderAggregateAliasList();
  }
}
async function renameAggregateAlias(aliasId, nextId = null) {
  const targetId = String(aliasId || '').trim();
  if (!targetId || aggregateAliasPendingIds.has(targetId) || hasAggregatePendingWork()) return;
  let normalized = '';
  if (nextId === null) {
    const prompted = window.prompt(getLanguage() === 'zh' ? '新的聚合 model ID' : 'New aggregate model ID', targetId);
    if (prompted === null) return;
    normalized = String(prompted || '').trim();
  } else {
    normalized = String(nextId || '').trim();
  }
  if (!normalized || normalized === targetId) {
    editingAliasId = '';
    renderAggregateAliasList();
    return;
  }
  const previousItems = cloneAggregateItems();

  const idx = aggregateItemsCache.findIndex((item) => String(item.alias_id || '').trim() === targetId);
  if (idx >= 0) {
    aggregateItemsCache[idx] = {
      ...aggregateItemsCache[idx],
      alias_id: normalized,
    };
  }
  activeAggregateAliasId = normalized;

  aggregateAliasPendingIds.add(normalized);
  editingAliasId = '';
  renderAggregateAliasList();
  try {
    const res = await api('/api/aggregate-models', 'POST', {
      action: 'rename',
      alias_id: targetId,
      new_alias_id: normalized,
      skip_restart: true,
    });
    activeAggregateAliasId = String(res.item?.alias_id || normalized);
    aggregateEditMode = false;
    aggregateEditMembers.clear();
    aggregateAliasPendingIds.delete(normalized);
    showMessage(res.message || (getLanguage() === 'zh' ? `已改名为：${activeAggregateAliasId}` : `Renamed to: ${activeAggregateAliasId}`));
    await loadAggregateModels(true);
  } catch (error) {
    aggregateItemsCache = previousItems;
    renderAggregateAliasList();
    renderAggregateActiveDetails();
    showMessage(getLanguage() === 'zh' ? `聚合 ID 改名失败：${error.message}` : `Failed to rename aggregate ID: ${error.message}`, true);
  } finally {
    aggregateAliasPendingIds.delete(normalized);
    renderAggregateAliasList();
  }
}
async function startAggregateMemberEdit() {
  syncViewedAggregateVersionForActiveAlias();
  const current = getActiveAggregateItem();
  if (!current?.alias_id) {
    showMessage('Please select an aggregate ID first.', true);
    return;
  }
  aggregateEditMode = true;
  aggregateEditMembers.clear();
  getAggregateVersionMembers(current).forEach((member) => {
    const key = aggregateMemberKey(member.provider, member.upstream_id);
    if (key !== '::') aggregateEditMembers.add(key);
  });
  renderAggregateActiveDetails();
  if (!aggregateSourceListLoaded) {
    await loadAggregateSourceModels();
  } else {
    renderAggregateProviderSourceList();
  }
}

function cancelAggregateMemberEdit() {
  aggregateEditMode = false;
  aggregateEditMembers.clear();
  renderAggregateActiveDetails();
  renderAggregateProviderSourceList();
}

async function saveAggregateMemberEdit() {
  if (!aggregateEditMode) {
    showMessage(getLanguage() === 'zh' ? '请先点击“编辑成员”。' : 'Click "Edit members" first.', true);
    return;
  }
  const current = aggregateItemsCache.find((item) => item.alias_id === activeAggregateAliasId);
  if (!current?.alias_id) {
    showMessage('Please select an aggregate ID first.', true);
    return;
  }
  const members = [...aggregateEditMembers].map((key) => {
    const [provider, ...rest] = String(key).split('::');
    return { provider, upstream_id: rest.join('::') };
  }).filter((member) => member.provider && member.upstream_id);
  const ok = await saveCurrentAggregateMembers(members, getLanguage() === 'zh'
    ? `已保存 ${current.alias_id} 的成员修改。`
    : `Saved member edits for ${current.alias_id}.`, true);
  if (ok) {
    aggregateEditMode = false;
    aggregateEditMembers.clear();
    renderAggregateProviderSourceList();
  }
}

function renderAggregateActiveDetails() {
  const badge = document.getElementById('aggregate-active-name');
  const summary = document.getElementById('aggregate-active-summary');
  const root = document.getElementById('aggregate-member-list');
  const testBtn = document.getElementById('aggregate-test-btn');
  const toggleBtn = document.getElementById('aggregate-member-toggle-btn');
  const versionContainer = document.getElementById('aggregate-version-switch-container');
  if (!badge || !summary || !root) return;
  if (toggleBtn) toggleBtn.style.display = 'none';

  syncViewedAggregateVersionForActiveAlias();
  const current = getActiveAggregateItem();
  if (!current) {
    if (versionContainer) versionContainer.innerHTML = '';
    updateAggregateWorkbenchStats();
    badge.textContent = t('common.notSelected', 'Not selected');
    summary.textContent = t('section.aggregatesDetailEmpty', 'Select an aggregate ID on the left.');
    root.innerHTML = '';
    if (testBtn) {
      testBtn.disabled = true;
      testBtn.classList.remove('is-testing');
      testBtn.textContent = t('btn.testAvailability', 'Test Availability');
    }
    return;
  }

  const viewedVersion = normalizeAggregateVersion(viewedAggregateAliasVersion);
  const members = getAggregateVersionMembers(current, viewedVersion);

  const aliasId = String(current.alias_id || '').trim();
  badge.textContent = current.alias_id || t('common.notSelected', 'Not selected');

  if (versionContainer) {
    const activeVersion = current.active_version || '1';
    const isCurrentActive = viewedVersion === activeVersion;
    const applyButtonHtml = isCurrentActive
      ? `<span class="aggregate-version-active-badge">✓ ${getLanguage() === 'zh' ? '使用中' : 'Active'}</span>`
      : `<button type="button" class="aggregate-version-apply-btn" onclick="applyAggregateAliasVersion('${escapeAggregateHtml(aliasId)}', '${viewedVersion}', this)">${getLanguage() === 'zh' ? '应用此版本' : 'Apply Version'}</button>`;

    versionContainer.innerHTML = `
      <div style="display: flex; align-items: center; gap: 8px;">
        <div class="aggregate-version-group">
          <button type="button" class="aggregate-version-btn ${viewedVersion === '1' ? 'is-active' : ''}" data-version="1">1</button>
          <button type="button" class="aggregate-version-btn ${viewedVersion === '2' ? 'is-active' : ''}" data-version="2">2</button>
          <button type="button" class="aggregate-version-btn ${viewedVersion === '3' ? 'is-active' : ''}" data-version="3">3</button>
        </div>
        ${applyButtonHtml}
      </div>
    `;
    versionContainer.querySelectorAll('.aggregate-version-btn').forEach((btn) => {
      btn.onclick = () => {
        const targetVersion = btn.getAttribute('data-version');
        if (targetVersion === viewedVersion) return;
        viewedAggregateAliasId = aliasId;
        viewedAggregateAliasVersion = normalizeAggregateVersion(targetVersion);
        aggregateEditMode = false;
        aggregateEditMembers.clear();
        renderAggregateActiveDetails();
        renderAggregateProviderSourceList();
      };
    });
  }

  updateAggregateWorkbenchStats();
  const health = Array.isArray(aggregateRouteHealthCache?.items)
    ? aggregateRouteHealthCache.items.find((item) => String(item?.alias_id || '').trim() === aliasId)
    : null;
  summary.innerHTML = aggregateEditMode
    ? `<div class="aggregate-summary-edit">${escapeAggregateHtml(getLanguage() === 'zh' ? `编辑中：已选 ${aggregateEditMembers.size} 个，点击下方模型块可增删，最后点“保存修改”。` : `Editing: ${aggregateEditMembers.size} selected. Click model chips below to add/remove, then save.`)}</div>`
    : '';

  if (testBtn) {
    const hasRunning = members.some((member) => aggregateModelsRunningSet.has(String(member.call_id || '').trim()));
    testBtn.disabled = !members.length || hasRunning;
    testBtn.classList.toggle('is-testing', hasRunning);
    testBtn.textContent = hasRunning ? t('common.testing', 'Testing') : t('btn.testAvailability', 'Test Availability');
  }

  if (!members.length) {
    root.innerHTML = `<div class="auth-empty">${getLanguage() === 'zh' ? '当前聚合 ID 还没有成员。' : 'This aggregate ID has no members yet.'}</div>`;
    return;
  }

  const visibleMembers = members;

  root.innerHTML = visibleMembers.map((member) => {
    const key = aggregateMemberKey(member.provider, member.upstream_id);
    const callId = String(member.call_id || '-').trim();
    const provider = String(member.provider || '-').trim();
    const score = aggregateMemberScore(member);
    const status = aggregateModelStatuses[callId] || 'pending';
    const statusMeta = aggregateModelStatusMeta[callId] || {};
    const statusText = aggregateModelStatusLabel(status, statusMeta);
    const editingPicked = aggregateEditMode && aggregateEditMembers.has(key);
    const memberPending = aggregateMemberPendingKeys.has(key);
    return `
      <div class="aggregate-member-card aggregate-member-card-compact ${editingPicked ? 'is-edit-picked' : ''} ${memberPending ? 'is-pending' : ''}" draggable="true" data-member-key="${escapeAggregateHtml(key)}">
        <div class="aggregate-member-drag-handle" title="${getLanguage() === 'zh' ? '拖动排序' : 'Drag to reorder'}">☰</div>
        <div class="aggregate-member-content-wrapper" onclick="showAggregateMemberPopover(this, event, '${escapeAggregateHtml(key)}')">
          <div class="aggregate-member-row">
            <div class="aggregate-member-main">
              <span class="aggregate-member-score">${score}</span>
              <span class="aggregate-member-state-dot status-${escapeAggregateHtml(status)}" title="${escapeAggregateHtml(statusText)}"></span>
              <strong class="aggregate-member-call-id" title="${escapeAggregateHtml(callId)}">${escapeAggregateHtml(callId)}</strong>
            </div>
            <div style="display: flex; align-items: center; gap: 8px;">
              <span class="auth-chip" style="font-size: 11px; padding: 1px 8px; min-height: 20px; line-height: 1.2;">${escapeAggregateHtml(provider)}</span>
              <span class="aggregate-member-details-trigger" style="font-size: 12px; color: var(--text-muted);" title="${getLanguage() === 'zh' ? '查看详情' : 'View details'}">⋮</span>
            </div>
          </div>
        </div>
        <button type="button" class="aggregate-member-delete-btn" title="${getLanguage() === 'zh' ? '删除成员' : 'Delete member'}" onclick="handleMemberDeleteClick(event, '${escapeAggregateHtml(key)}')">×</button>
      </div>
    `;
  }).join('');

  // Toggle listener loop removed

  root.querySelectorAll('.aggregate-member-card').forEach((card) => {
    card.addEventListener('dragstart', (e) => {
      draggedMemberKey = card.getAttribute('data-member-key');
      card.classList.add('is-dragging');
      e.dataTransfer.effectAllowed = 'move';
    });
    card.addEventListener('dragend', () => {
      draggedMemberKey = null;
      card.classList.remove('is-dragging');
      root.querySelectorAll('.aggregate-member-card').forEach((c) => c.classList.remove('drag-over'));
    });
    card.addEventListener('dragover', (e) => {
      e.preventDefault();
      if (draggedMemberKey && draggedMemberKey !== card.getAttribute('data-member-key')) {
        card.classList.add('drag-over');
      }
    });
    card.addEventListener('dragleave', () => {
      card.classList.remove('drag-over');
    });
    card.addEventListener('drop', (e) => {
      e.preventDefault();
      const targetKey = card.getAttribute('data-member-key');
      card.classList.remove('drag-over');
      if (draggedMemberKey && targetKey && draggedMemberKey !== targetKey) {
        void reorderAggregateMembers(draggedMemberKey, targetKey);
      }
    });
  });
}

async function switchAggregateAliasVersion(aliasId, version, button) {
  const targetId = String(aliasId || '').trim();
  if (!targetId || hasAggregatePendingWork()) return;

  const previousItems = cloneAggregateItems();

  const idx = aggregateItemsCache.findIndex(item => item.alias_id === targetId);
  if (idx >= 0) {
    aggregateItemsCache[idx] = {
      ...aggregateItemsCache[idx],
      active_version: version
    };
    const nextMembersKey = `version_${version}_members`;
    if (Array.isArray(aggregateItemsCache[idx][nextMembersKey])) {
      aggregateItemsCache[idx].members = aggregateItemsCache[idx][nextMembersKey];
    }
  }

  renderAggregateActiveDetails();

  try {
    const res = await api('/api/aggregate-models', 'POST', {
      action: 'set_version',
      alias_id: targetId,
      version: version,
      skip_restart: true,
    });
    showMessage(res.message || (getLanguage() === 'zh'
      ? `已切换到版本 ${version}。`
      : `Switched to version ${version}.`));
    await loadAggregateModels(true);
  } catch (error) {
    aggregateItemsCache = previousItems;
    renderAggregateActiveDetails();
    showMessage(getLanguage() === 'zh' ? `切换版本失败：${error.message}` : `Failed to switch version: ${error.message}`, true);
  }
}

async function applyAggregateAliasVersion(aliasId, version, button) {
  const targetId = String(aliasId || '').trim();
  if (!targetId || hasAggregatePendingWork()) return;

  const previousItems = cloneAggregateItems();

  const prevText = button.textContent;
  button.disabled = true;
  button.innerHTML = `<span class="runtime-action-spinner" style="margin: 0; width: 12px; height: 12px; border-width: 2px;"></span>`;

  try {
    const res = await api('/api/aggregate-models', 'POST', {
      action: 'set_version',
      alias_id: targetId,
      version: version,
      skip_restart: true,
    });
    showMessage(res.message || (getLanguage() === 'zh'
      ? `已成功应用版本 ${version} 到路由。`
      : `Successfully applied version ${version} to routing.`));
    await loadAggregateModels(true);
  } catch (error) {
    aggregateItemsCache = previousItems;
    renderAggregateActiveDetails();
    showMessage(getLanguage() === 'zh' ? `应用版本失败：${error.message}` : `Failed to apply version: ${error.message}`, true);
  } finally {
    button.disabled = false;
    button.textContent = prevText;
  }
}

async function reorderAggregateMembers(draggedKey, targetKey) {
  syncViewedAggregateVersionForActiveAlias();
  const current = getActiveAggregateItem();
  if (!current?.alias_id || aggregateMemberPendingKeys.has(draggedKey) || aggregateMemberPendingKeys.has(targetKey)) {
    return;
  }
  const members = [...getAggregateVersionMembers(current)];
  const draggedIndex = members.findIndex((member) => aggregateMemberKey(member.provider, member.upstream_id) === draggedKey);
  const targetIndex = members.findIndex((member) => aggregateMemberKey(member.provider, member.upstream_id) === targetKey);
  if (draggedIndex < 0 || targetIndex < 0 || draggedIndex === targetIndex) return;

  const reordered = [...members];
  const [removed] = reordered.splice(draggedIndex, 1);
  reordered.splice(targetIndex, 0, removed);

  aggregateMemberPendingKeys.add(draggedKey);
  aggregateMemberPendingKeys.add(targetKey);

  const ok = await saveCurrentAggregateMembers(reordered, getLanguage() === 'zh' ? '已保存成员排序。' : 'Saved member order.', true);

  aggregateMemberPendingKeys.delete(draggedKey);
  aggregateMemberPendingKeys.delete(targetKey);
  renderAggregateCurrentViews(true);
}

function handleMemberDeleteClick(event, key) {
  event.stopPropagation();
  void removeAggregateMember(key);
}
window.handleMemberDeleteClick = handleMemberDeleteClick;

function renderAggregateProviderFilters() {
  const root = document.getElementById('aggregate-provider-filters');
  if (!root) return;
  if (!aggregateSourceListLoaded) {
    root.innerHTML = '';
    return;
  }

  const realProviderNames = aggregateProviderNames();
  const activeProvider = ensureAggregateProviderFilter();
  const providerNames = [...realProviderNames, 'all'];

  root.innerHTML = providerNames.map((provider) => `
    <button type="button" class="provider-map-tab ${provider === activeProvider ? 'is-active' : ''}" data-aggregate-provider-filter="${escapeAggregateHtml(provider)}">
      ${provider === 'all' ? '全部' : escapeAggregateHtml(provider)}
    </button>
  `).join('');

  root.querySelectorAll('[data-aggregate-provider-filter]').forEach((btn) => {
    btn.onclick = async () => {
      activeAggregateProviderFilter = btn.getAttribute('data-aggregate-provider-filter') || '';
      await loadAggregateActiveProviderRows();
      renderAggregateProviderFilters();
      renderAggregateTypeFilters();
      renderAggregateScoreFilters();
      renderAggregateProviderSourceList();
    };
  });
}

function renderAggregateTypeFilters() {
  const root = document.getElementById('aggregate-type-filters');
  if (!root) return;
  if (!aggregateSourceListLoaded) {
    root.innerHTML = '';
    return;
  }

  const counts = new Map(AGGREGATE_TYPE_OPTIONS.map((item) => [item.id, 0]));
  let total = 0;
  ensureAggregateProviderFilter();
  aggregateProviderItemsCache.forEach((item) => {
    const provider = aggregateProviderKey(item);
    if (activeAggregateProviderFilter !== 'all' && provider !== activeAggregateProviderFilter) return;
    (Array.isArray(item.rows) ? item.rows : []).forEach((row) => {
      total += 1;
      deriveAggregateModelTypes(row).forEach((typeId) => {
        counts.set(typeId, (counts.get(typeId) || 0) + 1);
      });
    });
  });
  counts.set('all', total);

  root.innerHTML = AGGREGATE_TYPE_OPTIONS.map((item) => `
    <button type="button" class="provider-category-btn ${item.id === activeAggregateTypeFilter ? 'is-active' : ''}" data-aggregate-type-filter="${item.id}">
      ${item.label} <span>${counts.get(item.id) || 0}</span>
    </button>
  `).join('');

  root.querySelectorAll('[data-aggregate-type-filter]').forEach((btn) => {
    btn.onclick = () => {
      activeAggregateTypeFilter = btn.getAttribute('data-aggregate-type-filter') || 'all';
      renderAggregateTypeFilters();
      renderAggregateScoreFilters();
      renderAggregateProviderSourceList();
    };
  });
}

function renderAggregateScoreFilters() {
  const root = document.getElementById('aggregate-score-filters');
  if (!root) return;
  if (!aggregateSourceListLoaded) {
    root.innerHTML = '';
    return;
  }

  const counts = new Map(AGGREGATE_SCORE_OPTIONS.map((item) => [item.id, 0]));
  let total = 0;
  ensureAggregateProviderFilter();
  aggregateProviderItemsCache.forEach((item) => {
    const provider = aggregateProviderKey(item);
    if (activeAggregateProviderFilter !== 'all' && provider !== activeAggregateProviderFilter) return;
    (Array.isArray(item.rows) ? item.rows : []).forEach((row) => {
      const types = deriveAggregateModelTypes(row);
      if (activeAggregateTypeFilter !== 'all' && !types.includes(activeAggregateTypeFilter)) return;
      const key = aggregateMemberKey(provider, row.lookup_upstream_id || row.upstream_id || '');
      const score = Number(aggregateModelRawScore(row));
      total += 1;
      AGGREGATE_SCORE_OPTIONS.forEach((option) => {
        if (option.id !== 'all' && matchesAggregateScoreFilter(score, option.id)) {
          counts.set(option.id, (counts.get(option.id) || 0) + 1);
        }
      });
    });
  });
  counts.set('all', total);

  root.innerHTML = AGGREGATE_SCORE_OPTIONS.map((item) => `
    <button type="button" class="provider-category-btn ${item.id === activeAggregateScoreFilter ? 'is-active' : ''}" data-aggregate-score-filter="${item.id}">
      ${item.label} <span>${counts.get(item.id) || 0}</span>
    </button>
  `).join('');

  root.querySelectorAll('[data-aggregate-score-filter]').forEach((btn) => {
    btn.onclick = () => {
      activeAggregateScoreFilter = btn.getAttribute('data-aggregate-score-filter') || 'all';
      renderAggregateScoreFilters();
      renderAggregateProviderSourceList();
    };
  });
}

function renderAggregateProviderSourceList() {
  const root = document.getElementById('aggregate-source-model-list');
  if (!root) return;
  updateAggregateWorkbenchStats();

  // Selection buttons display management removed

  const loadBtn = document.getElementById('aggregate-load-source-btn');
  if (loadBtn) {
    if (aggregateSourceListLoaded) {
      loadBtn.style.display = 'none';
    } else {
      loadBtn.style.display = '';
      loadBtn.disabled = aggregateSourceListLoading;
      loadBtn.textContent = aggregateSourceListLoading
        ? (getLanguage() === 'zh' ? '加载中...' : 'Loading...')
        : (getLanguage() === 'zh' ? '加载可选模型' : 'Load Models');
    }
  }

  if (!aggregateSourceListLoaded) {
    root.innerHTML = '';
    return;
  }

  if (aggregateProviderRowsLoading) {
    root.innerHTML = `<div class="auth-empty">${getLanguage() === 'zh' ? '正在加载当前渠道模型...' : 'Loading models for this provider...'}</div>`;
    return;
  }

  syncViewedAggregateVersionForActiveAlias();
  const current = getActiveAggregateItem();
  const existingKeys = new Set(getAggregateVersionMembers(current).map((member) => aggregateMemberKey(member.provider, member.upstream_id)));
  ensureAggregateProviderFilter();
  const visibleItems = aggregateProviderItemsCache
    .map((item) => {
      const provider = aggregateProviderKey(item);
      if (activeAggregateProviderFilter !== 'all' && provider !== activeAggregateProviderFilter) return null;
      const rows = (Array.isArray(item.rows) ? item.rows : []).filter((row) => {
        const types = deriveAggregateModelTypes(row);
        if (activeAggregateTypeFilter !== 'all' && !types.includes(activeAggregateTypeFilter)) return false;
        const key = aggregateMemberKey(provider, row.lookup_upstream_id || row.upstream_id || '');
        const score = Number(aggregateModelRawScore(row));
        return matchesAggregateScoreFilter(score);
      });
      if (!rows.length) return null;
      return { ...item, rows };
    })
    .filter(Boolean);

  if (!visibleItems.length) {
    root.innerHTML = `<div class="auth-empty">${getLanguage() === 'zh' ? '当前筛选条件下没有可选模型。' : 'No models available under the current filters.'}</div>`;
    return;
  }

  root.innerHTML = visibleItems.map((item) => {
    const provider = aggregateProviderKey(item);
    const rows = Array.isArray(item.rows) ? item.rows : [];
    const chips = rows.map((row) => {
      const upstreamId = String(row.lookup_upstream_id || row.upstream_id || '').trim();
      const callId = String(row.call_id || '').trim();
      const key = aggregateMemberKey(provider, upstreamId);
      const selected = aggregateEditMode && aggregateEditMembers.has(key);
      const alreadyInAlias = existingKeys.has(key);
      const isMember = alreadyInAlias && !aggregateEditMode;
      const score = Number(aggregateModelRawScore(row));
      const typeText = deriveAggregateModelTypes(row).join(' / ');
      const status = aggregateModelStatuses[callId] || 'pending';
      const statusMeta = aggregateModelStatusMeta[callId] || {};
      const statusText = aggregateModelStatusLabel(status, statusMeta);
      const pending = aggregateMemberPendingKeys.has(key);
      return `
        <button
          type="button"
          class="provider-model-call-id aggregate-source-chip ${selected ? 'is-selected' : ''} ${isMember ? 'is-member' : ''} ${pending ? 'is-pending' : ''} ${status ? `status-${status}` : ''}"
          data-aggregate-member="${escapeAggregateHtml(key)}"
          ${pending ? 'disabled' : ''}
          title="${escapeAggregateHtml(`Score: ${score}\nType: ${typeText}\nStatus: ${statusText}\n${row.runtime_registered ? 'Runtime: registered' : 'Runtime: config-only'}`)}"
        >
          <span class="provider-model-status-dot ${status ? `status-${status}` : 'status-idle'}"></span>
          <span class="provider-model-chip-text">
            ${escapeAggregateHtml(callId || upstreamId)}
            <span class="aggregate-source-score-badge">${score}</span>
          </span>
          ${row.runtime_registered ? '<span class="provider-model-retry">runtime</span>' : ''}
        </button>
      `;
    }).join('');

    return `
      <div class="provider-group-card">
        <div class="provider-group-head">
          <h3>${escapeAggregateHtml(provider)}</h3>
          <div class="provider-group-actions"><span class="provider-group-summary">${rows.length} 个模型</span></div>
        </div>
        <div class="provider-model-call-list">${chips}</div>
      </div>
    `;
  }).join('');

  root.querySelectorAll('[data-aggregate-member]').forEach((btn) => {
    btn.onclick = () => {
      const key = btn.getAttribute('data-aggregate-member') || '';
      if (!key || btn.disabled) return;
      if (aggregateEditMode) {
        if (aggregateEditMembers.has(key)) aggregateEditMembers.delete(key);
        else aggregateEditMembers.add(key);
        updateAggregateWorkbenchStats();
        renderAggregateProviderSourceList();
        renderAggregateActiveDetails();
      } else {
        if (existingKeys.has(key)) {
          void removeAggregateMember(key);
        } else {
          void addSingleModelToAggregate(key);
        }
      }
    };
  });
}

function aggregateFailureKindLabel(kind) {
  if (kind === 'forbidden') return getLanguage() === 'zh' ? '无访问权限' : 'No access';
  if (kind === 'quota') return getLanguage() === 'zh' ? '额度超限' : 'Quota exceeded';
  if (kind === 'auth') return getLanguage() === 'zh' ? '认证失败' : 'Authentication failed';
  if (kind === 'timeout') return getLanguage() === 'zh' ? '请求超时' : 'Timed out';
  if (kind === 'server') return getLanguage() === 'zh' ? '服务端错误' : 'Server error';
  if (kind === 'client') return getLanguage() === 'zh' ? '客户端错误' : 'Client error';
  return t('common.unavailable', 'Unavailable');
}

function aggregateModelStatusLabel(status, meta = {}) {
  if (status === 'ok') return t('common.available', 'Available');
  if (status === 'testing') return t('common.testing', 'Testing');
  if (status === 'bad') return aggregateFailureKindLabel(meta.failure_kind);
  return t('common.pending', 'Pending');
}
async function loadAggregateModels(force = false, button = null) {
  if (aggregateModelsLoaded && !force) return;
  const refreshVersion = ++aggregateRefreshVersion;

  let previousText = '';
  let previousDisabled = false;
  if (button) {
    previousText = button.innerHTML;
    previousDisabled = button.disabled;
    button.disabled = true;
    button.innerHTML = `<span class="runtime-action-spinner"></span>${getLanguage() === 'zh' ? '刷新中...' : 'Refreshing...'}`;
  }

  try {
    const res = await api('/api/aggregate-models');
    if (refreshVersion !== aggregateRefreshVersion || hasAggregatePendingWork()) return;
    aggregateItemsCache = Array.isArray(res.items) ? res.items : [];
    renderAggregateAliasList();
    renderAggregateActiveDetails();
    renderAggregateProviderFilters();
    renderAggregateTypeFilters();
    renderAggregateScoreFilters();
    renderAggregateProviderSourceList();
    void Promise.all([
      syncAggregateModelTestState(),
      refreshAggregateRoutePreview(),
      refreshAggregateRouteHealth(),
    ]).then(() => {
      if (refreshVersion !== aggregateRefreshVersion || hasAggregatePendingWork()) return;
      if (typeof getActiveSection === 'function' && getActiveSection() === 'aggregates') {
        renderAggregateActiveDetails();
        if (aggregateSourceListLoaded) renderAggregateProviderSourceList();
      }
    });
    if (!aggregateSourceListLoaded) {
      void loadAggregateSourceModels();
    }
    aggregateModelsLoaded = true;
  } catch (err) {
    showMessage(err.message, true);
  } finally {
    if (button) {
      button.disabled = previousDisabled;
      button.innerHTML = previousText;
    }
  }
}

async function loadAggregateSourceModels(button = null) {
  if (aggregateSourceListLoading) return;
  aggregateSourceListLoading = true;

  let previousText = '';
  let previousDisabled = false;
  if (button) {
    previousText = button.innerHTML;
    previousDisabled = button.disabled;
    button.disabled = true;
    button.innerHTML = `<span class="runtime-action-spinner"></span>${getLanguage() === 'zh' ? '加载中...' : 'Loading...'}`;
  }

  renderAggregateProviderSourceList();
  try {
    await Promise.all([fetchAggregateProviderSummaries(), syncAggregateModelTestState()]);
    aggregateSourceListLoaded = true;
    ensureAggregateProviderFilter();
    await loadAggregateActiveProviderRows();
    renderAggregateActiveDetails();
    renderAggregateProviderFilters();
    renderAggregateTypeFilters();
    renderAggregateScoreFilters();
    renderAggregateProviderSourceList();
  } catch (err) {
    showMessage(err.message, true);
  } finally {
    aggregateSourceListLoading = false;
    renderAggregateProviderSourceList();
    if (button) {
      button.disabled = previousDisabled;
      button.innerHTML = previousText;
    }
  }
}

async function createAggregateAlias() {
  const input = document.getElementById('aggregate-create-id');
  const aliasId = String(input?.value || '').trim();
  if (!aliasId) {
    showMessage('Please enter an aggregate ID first.', true);
    return;
  }
  if (aggregateAliasPendingIds.has(aliasId) || hasAggregatePendingWork()) return;
  aggregateAliasPendingIds.add(aliasId);
  renderAggregateAliasList();
  try {
    const res = await api('/api/aggregate-models', 'POST', {
      action: 'create',
      alias_id: aliasId,
      skip_restart: true,
    });
    if (input) input.value = '';
    activeAggregateAliasId = String(res.item?.alias_id || aliasId);
    aggregateAliasPendingIds.delete(aliasId);
    showMessage(`Created aggregate ID: ${activeAggregateAliasId}.`);
    await loadAggregateModels(true);
  } catch (err) {
    showMessage(err.message, true);
  } finally {
    aggregateAliasPendingIds.delete(aliasId);
    renderAggregateAliasList();
  }
}

async function addSingleModelToAggregate(key) {
  syncViewedAggregateVersionForActiveAlias();
  const current = getActiveAggregateItem();
  if (!current?.alias_id) {
    showMessage(getLanguage() === 'zh' ? '请先在左侧选择一个聚合 ID。' : 'Please select an aggregate ID first.', true);
    return;
  }
  const aliasId = String(current.alias_id || '').trim();
  const targetVersion = normalizeAggregateVersion(viewedAggregateAliasVersion);
  if (hasAggregateMemberSaveWork(aliasId)) return;

  const [provider, ...rest] = String(key).split('::');
  const upstreamId = rest.join('::');
  if (!provider || !upstreamId) return;

  aggregateMemberPendingKeys.add(key);
  renderAggregateProviderSourceList();
  try {
    const res = await api('/api/aggregate-models', 'POST', {
      action: 'add_members',
      alias_id: aliasId,
      members: [{ provider, upstream_id: upstreamId }],
      skip_restart: true,
      version: targetVersion,
    });
    const nextMembers = Array.isArray(res.item?.version_members)
      ? res.item.version_members
      : Array.isArray(res.item?.members) && normalizeAggregateVersion(res.item?.target_version) === aggregateActiveVersion(current)
        ? res.item.members
      : [...getAggregateVersionMembers(current, targetVersion), { provider, upstream_id: upstreamId }];
    updateAggregateMembersInCache(aliasId, nextMembers, targetVersion);
    showMessage(res.message || (getLanguage() === 'zh' ? '已添加模型。' : 'Model added.'));
    renderAggregateCurrentViews(true);
    if (typeof loadProviderModels === 'function') void loadProviderModels();
  } catch (err) {
    showMessage(err.message, true);
  } finally {
    aggregateMemberPendingKeys.delete(key);
    renderAggregateCurrentViews(true);
  }
}

async function saveCurrentAggregateMembers(reorderedMembers, successMessage, skipRestart = true) {
  syncViewedAggregateVersionForActiveAlias();
  const current = getActiveAggregateItem();
  if (!current?.alias_id) {
    showMessage('Please select an aggregate ID first.', true);
    return false;
  }
  const aliasId = String(current.alias_id || '').trim();
  const previousItems = cloneAggregateItems();
  if (!aggregateMemberRollbackSnapshots.has(aliasId)) {
    aggregateMemberRollbackSnapshots.set(aliasId, previousItems);
  }
  const mutationVersion = nextAggregateMemberMutationVersion(aliasId);
  const nextMembers = Array.isArray(reorderedMembers) ? reorderedMembers : [];
  const targetVersion = normalizeAggregateVersion(viewedAggregateAliasVersion);
  updateAggregateMembersInCache(aliasId, nextMembers, targetVersion);
  renderAggregateCurrentViews(true);

  const ok = await queueAggregateMemberSave(aliasId, nextMembers, successMessage || `Saved aggregate order: ${aliasId}.`, skipRestart, targetVersion);
  if (!ok && isLatestAggregateMemberMutation(aliasId, mutationVersion)) {
    aggregateItemsCache = aggregateMemberRollbackSnapshots.get(aliasId) || previousItems;
    aggregateMemberRollbackSnapshots.delete(aliasId);
    renderAggregateCurrentViews(true);
  }
  if (ok && isLatestAggregateMemberMutation(aliasId, mutationVersion)) {
    aggregateMemberRollbackSnapshots.delete(aliasId);
  }
  return ok;
}

async function testCurrentAggregateMembers() {
  syncViewedAggregateVersionForActiveAlias();
  const current = getActiveAggregateItem();
  if (!current?.alias_id) {
    showMessage('Please select an aggregate ID first.', true);
    return;
  }
  const members = getAggregateVersionMembers(current);
  const ids = [...new Set(members.map((member) => String(member.call_id || '').trim()).filter(Boolean))];
  if (!ids.length) {
    showMessage('This aggregate has no callable model IDs.', true);
    return;
  }

  try {
    await api('/api/provider-model-tests', 'POST', { model_ids: ids });
  } catch {
    const fallback = await api('/api/test-provider-models', 'POST', { model_ids: ids });
    const items = Array.isArray(fallback.items) ? fallback.items : [];
    items.forEach((item) => {
      const model = String(item.model || '').trim();
      if (!model) return;
      aggregateModelStatuses[model] = item.available ? 'ok' : 'bad';
      aggregateModelStatusMeta[model] = {
        elapsed_ms: item.elapsed_ms,
        retry_after_seconds: item.retry_after_seconds,
        tested_at: item.tested_at,
        status_code: item.status_code,
        failure_kind: item.failure_kind,
        message: item.message,
      };
      aggregateModelsRunningSet.delete(model);
    });
    renderAggregateActiveDetails();
    renderAggregateProviderSourceList();
    showMessage(`Detection done: ${items.filter((item) => item.available).length}/${items.length} available.`);
    return;
  }

  ids.forEach((id) => {
    aggregateModelsRunningSet.add(id);
    aggregateModelStatuses[id] = 'testing';
    aggregateModelStatusMeta[id] = { tested_at: Math.floor(Date.now() / 1000) };
  });
  renderAggregateActiveDetails();
  renderAggregateProviderSourceList();
  showMessage(`Queued detection for ${ids.length} models.`);
}

async function sortCurrentAggregateByScore() {
  syncViewedAggregateVersionForActiveAlias();
  const current = getActiveAggregateItem();
  if (!current?.alias_id) {
    showMessage('Please select an aggregate ID first.', true);
    return;
  }
  const members = [...getAggregateVersionMembers(current)];
  if (!members.length) return;
  const reordered = members
    .map((member, idx) => ({ member, idx, score: aggregateMemberScore(member) }))
    .sort((a, b) => (b.score - a.score) || (a.idx - b.idx))
    .map((item) => item.member);
  await saveCurrentAggregateMembers(reordered, `Sorted by score: ${current.alias_id}.`, true);
}

async function sortCurrentAggregateUnavailableLast() {
  syncViewedAggregateVersionForActiveAlias();
  const current = getActiveAggregateItem();
  if (!current?.alias_id) {
    showMessage('Please select an aggregate ID first.', true);
    return;
  }
  const members = [...getAggregateVersionMembers(current)];
  if (!members.length) return;
  const rankOf = (member) => {
    const status = aggregateModelStatuses[String(member.call_id || '').trim()] || 'pending';
    if (status === 'ok') return 0;
    if (status === 'testing') return 1;
    if (status === 'pending') return 2;
    return 3;
  };
  const reordered = members
    .map((member, idx) => ({ member, idx, rank: rankOf(member) }))
    .sort((a, b) => (a.rank - b.rank) || (a.idx - b.idx))
    .map((item) => item.member);
  await saveCurrentAggregateMembers(reordered, `Moved unavailable models to the end: ${current.alias_id}.`, true);
}

async function moveAggregateMember(key, direction) {
  syncViewedAggregateVersionForActiveAlias();
  const current = getActiveAggregateItem();
  if (!current?.alias_id || aggregateMemberPendingKeys.has(key)) {
    if (!current?.alias_id) showMessage('Please select an aggregate ID first.', true);
    return;
  }
  const members = [...getAggregateVersionMembers(current)];
  const index = members.findIndex((member) => aggregateMemberKey(member.provider, member.upstream_id) === key);
  if (index < 0) return;
  const nextIndex = index + Number(direction || 0);
  if (nextIndex < 0 || nextIndex >= members.length) return;

  const reordered = [...members];
  const nextKey = aggregateMemberKey(reordered[nextIndex].provider, reordered[nextIndex].upstream_id);
  aggregateMemberPendingKeys.add(key);
  aggregateMemberPendingKeys.add(nextKey);
  [reordered[index], reordered[nextIndex]] = [reordered[nextIndex], reordered[index]];
  const ok = await saveCurrentAggregateMembers(reordered, `Saved aggregate order: ${current.alias_id}.`, true);
  aggregateMemberPendingKeys.delete(key);
  aggregateMemberPendingKeys.delete(nextKey);
  renderAggregateCurrentViews(true);
  if (!ok) showMessage(getLanguage() === 'zh' ? '移动成员失败。' : 'Failed to move member.', true);
}

async function removeAggregateMember(key) {
  syncViewedAggregateVersionForActiveAlias();
  const current = getActiveAggregateItem();
  if (!current?.alias_id) {
    showMessage('Please select an aggregate ID first.', true);
    return;
  }
  if (!key || aggregateMemberPendingKeys.has(key)) return;
  const aliasId = String(current.alias_id || '').trim();
  const targetVersion = normalizeAggregateVersion(viewedAggregateAliasVersion);
  const members = [...getAggregateVersionMembers(current, targetVersion)];
  const filtered = members.filter((member) => aggregateMemberKey(member.provider, member.upstream_id) !== key);
  if (filtered.length === members.length) return;

  const previousItems = cloneAggregateItems();
  const mutationVersion = nextAggregateMemberMutationVersion(aliasId);
  if (!aggregateMemberRollbackSnapshots.has(aliasId)) {
    aggregateMemberRollbackSnapshots.set(aliasId, previousItems);
  }
  aggregateMemberPendingKeys.add(key);
  updateAggregateMembersInCache(aliasId, filtered, targetVersion);
  renderAggregateCurrentViews(true);

  const ok = await queueAggregateMemberSave(aliasId, filtered, `Removed model from ${aliasId}.`, true, targetVersion);
  aggregateMemberPendingKeys.delete(key);
  if (!ok && isLatestAggregateMemberMutation(aliasId, mutationVersion)) {
    aggregateItemsCache = aggregateMemberRollbackSnapshots.get(aliasId) || previousItems;
    aggregateMemberRollbackSnapshots.delete(aliasId);
  }
  if (ok && isLatestAggregateMemberMutation(aliasId, mutationVersion)) {
    aggregateMemberRollbackSnapshots.delete(aliasId);
  }
  renderAggregateCurrentViews(true);
}

function ensureAggregateModelStatePoller() {
  if (aggregateModelStatePollTimer) return;
  aggregateModelStatePollTimer = setInterval(async () => {
    if (typeof getActiveSection === 'function' && getActiveSection() !== 'aggregates') return;
    await syncAggregateModelTestState();
    renderAggregateActiveDetails();
    if (aggregateSourceListLoaded) renderAggregateProviderSourceList();
  }, 2500);
}

ensureAggregateModelStatePoller();

function showAggregateMemberPopover(element, event, key) {
  if (!element || !event) return;
  event.stopPropagation();
  
  // Remove any existing popovers
  document.querySelectorAll('.aggregate-member-popover').forEach(el => el.remove());
  
  // Find the member data in aggregateItemsCache
  syncViewedAggregateVersionForActiveAlias();
  const current = getActiveAggregateItem();
  if (!current) return;
  
  const member = getAggregateVersionMembers(current).find(m => aggregateMemberKey(m.provider, m.upstream_id) === key);
  if (!member) return;
  
  const callId = String(member.call_id || '-').trim();
  const provider = String(member.provider || '-').trim();
  const score = aggregateMemberScore(member);
  const status = aggregateModelStatuses[callId] || 'pending';
  const statusMeta = aggregateModelStatusMeta[callId] || {};
  const statusText = aggregateModelStatusLabel(status, statusMeta);
  const runtimeState = aggregateMemberRuntimeState(member);
  
  const health = Array.isArray(aggregateRouteHealthCache?.items)
    ? aggregateRouteHealthCache.items.find(item => String(item?.alias_id || '').trim() === activeAggregateAliasId)
    : null;
  const healthMember = health?.members?.find(item => aggregateMemberKey(item.provider, item.upstream_id) === key) || null;
  const memberPending = aggregateMemberPendingKeys.has(key);
  
  // Build detailed popover markup
  const popover = document.createElement('div');
  popover.className = 'aggregate-member-popover text-popover';
  popover.style.position = 'absolute';
  popover.style.background = 'color-mix(in srgb, var(--panel) 98%, white)';
  popover.style.border = '1px solid var(--border)';
  popover.style.borderRadius = '12px';
  popover.style.padding = '12px';
  popover.style.boxShadow = '0 10px 25px rgba(15, 23, 42, 0.15)';
  popover.style.zIndex = '1000';
  popover.style.width = '260px';
  popover.style.fontSize = '12px';
  popover.style.color = 'var(--text)';
  
  const runtimeText = runtimeState.runtimeRegistered ? 'runtime' : 'config-only';
  const runtimeClass = runtimeState.runtimeRegistered ? 'ok' : 'off';
  
  const issueHtml = healthMember?.issue_code
    ? `<div class="meta-row" style="display: flex; justify-content: space-between; align-items: center; margin-top: 4px;"><span>健康状态</span><span class="pill ${healthMember.issue_code === 'cooldown' ? 'warn' : 'off'}" style="min-height: 18px; padding: 0 6px; font-size: 10px;">${escapeAggregateHtml(healthMember.issue_code)}</span></div>`
    : '';
     
  let detailsHtml = '';
  if (statusMeta.failure_kind || statusMeta.message) {
    detailsHtml = `
      <div class="meta-details" style="margin-top: 6px; padding: 6px; background: var(--panel-2); border: 1px solid var(--border); border-radius: 6px; font-size: 11px; max-height: 80px; overflow-y: auto; color: var(--text-soft); word-break: break-all;">
        <strong>异常原因:</strong> ${escapeAggregateHtml(statusMeta.failure_kind || statusMeta.message)}
      </div>
    `;
  }
  
  popover.innerHTML = `
    <div class="popover-head" style="display: flex; align-items: center; justify-content: space-between; border-bottom: 1px solid var(--border); padding-bottom: 6px; margin-bottom: 8px;">
      <strong style="font-size: 13px; font-weight: 800; max-width: 150px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;" title="${escapeAggregateHtml(callId)}">${escapeAggregateHtml(callId)}</strong>
      <span class="auth-chip" style="font-size: 11px; padding: 1px 8px; min-height: 20px; line-height: 1.2;">${escapeAggregateHtml(provider)}</span>
    </div>
    <div class="popover-meta-grid" style="display: flex; flex-direction: column; gap: 4px;">
      <div class="meta-row" style="display: flex; justify-content: space-between; align-items: center;">
        <span>评分</span><strong style="color: var(--accent);">${score}</strong>
      </div>
      <div class="meta-row" style="display: flex; justify-content: space-between; align-items: center;">
        <span>可用状态</span><span class="aggregate-member-state status-${escapeAggregateHtml(status)}" style="min-width: auto; height: 18px; padding: 0 6px; border: 0; font-size: 10px;">${escapeAggregateHtml(statusText)}</span>
      </div>
      <div class="meta-row" style="display: flex; justify-content: space-between; align-items: center;">
        <span>部署状态</span><span class="pill ${runtimeClass}" style="min-height: 18px; padding: 0 6px; font-size: 10px;">${runtimeText}</span>
      </div>
      ${issueHtml}
      ${detailsHtml}
    </div>
  `;
  
  document.body.appendChild(popover);
  
  // Position popover
  const rect = element.getBoundingClientRect();
  const popoverWidth = popover.offsetWidth;
  const popoverHeight = popover.offsetHeight;
  
  let left = rect.right + window.scrollX + 10;
  if (left + popoverWidth > window.innerWidth - 16) {
    // Flip to the left if it overflows on the right
    left = rect.left + window.scrollX - popoverWidth - 10;
  }
  if (left < 16) left = 16;
  
  let top = rect.top + window.scrollY - 10;
  if (top + popoverHeight > window.innerHeight + window.scrollY - 16) {
    top = window.innerHeight + window.scrollY - popoverHeight - 16;
  }
  if (top < window.scrollY + 16) top = window.scrollY + 16;
  
  popover.style.left = `${left}px`;
  popover.style.top = `${top}px`;
  
  // Add smooth transition animations
  popover.style.transform = 'scale(0.96)';
  popover.style.opacity = '0';
  popover.style.transition = 'all 0.14s cubic-bezier(0.4, 0, 0.2, 1)';
  
  // Force reflow
  popover.offsetHeight;
  
  popover.style.transform = 'scale(1)';
  popover.style.opacity = '1';
  
  // Dismiss popover on click outside
  const dismiss = (e) => {
    if (popover.contains(e.target) || element.contains(e.target)) return;
    popover.style.transform = 'scale(0.96)';
    popover.style.opacity = '0';
    setTimeout(() => popover.remove(), 140);
    document.removeEventListener('pointerdown', dismiss);
  };
  document.addEventListener('pointerdown', dismiss);
}

function triggerMemberAction(key, direction) {
  // Remove popover
  document.querySelectorAll('.aggregate-member-popover').forEach(el => el.remove());
  moveAggregateMember(key, direction);
}

function triggerMemberRemove(key) {
  // Remove popover
  document.querySelectorAll('.aggregate-member-popover').forEach(el => el.remove());
  removeAggregateMember(key);
}

window.showAggregateMemberPopover = showAggregateMemberPopover;
window.triggerMemberAction = triggerMemberAction;
window.triggerMemberRemove = triggerMemberRemove;

function showCreateAggregateModal() {
  const modal = document.getElementById('create-aggregate-modal');
  if (!modal) return;
  modal.style.display = 'flex';
  const inner = modal.querySelector('.modal');
  if (inner) {
    inner.offsetHeight;
    inner.style.transform = 'scale(1)';
    inner.style.opacity = '1';
  }
  const input = document.getElementById('aggregate-create-id');
  if (input) {
    input.value = '';
    setTimeout(() => input.focus(), 80);
  }
}

function hideCreateAggregateModal() {
  const modal = document.getElementById('create-aggregate-modal');
  if (!modal) return;
  const inner = modal.querySelector('.modal');
  if (inner) {
    inner.style.transform = 'scale(0.96)';
    inner.style.opacity = '0';
  }
  setTimeout(() => {
    modal.style.display = 'none';
  }, 150);
}

async function handleCreateAggregateSubmit() {
  const input = document.getElementById('aggregate-create-id');
  const aliasId = String(input?.value || '').trim();
  if (!aliasId) {
    showMessage(getLanguage() === 'zh' ? '请输入聚合 ID。' : 'Please enter an aggregate ID.', true);
    return;
  }
  
  await createAggregateAlias();
  
  if (aggregateItemsCache.some((item) => String(item.alias_id || '').trim() === aliasId) || activeAggregateAliasId === aliasId) {
    hideCreateAggregateModal();
  }
}

document.addEventListener('keydown', (e) => {
  const modal = document.getElementById('create-aggregate-modal');
  if (modal && modal.style.display === 'flex' && e.key === 'Enter') {
    void handleCreateAggregateSubmit();
  }
});

window.applyAggregateRuntime = applyAggregateRuntime;
window.showCreateAggregateModal = showCreateAggregateModal;
window.hideCreateAggregateModal = hideCreateAggregateModal;
window.handleCreateAggregateSubmit = handleCreateAggregateSubmit;
