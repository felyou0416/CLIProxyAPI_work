/**
 * 可用性检测共享层（模型级权威缓存）
 *
 * 分层：
 * 1) 后端探测内核：/api/provider-model-tests + provider_model_test_state.json
 * 2) 本模块：状态词表 / 读缓存 / 入队 / auth 灯号聚合
 * 3) 各页面：providers / auths / aggregates 只负责展示与触发
 *
 * 约定：原子状态是 model_id(call_id)；OAuth 折叠灯由该 provider 下模型结果聚合。
 */
(function (global) {
  'use strict';

  const AVAIL_STATUS = {
    ok: 'ok',
    bad: 'bad',
    testing: 'testing',
    pending: 'pending',
  };

  let _providerModelsCache = null;
  let _providerModelsCacheAt = 0;
  const PROVIDER_MODELS_TTL_MS = 15000;

  function _t(key, fallback) {
    if (typeof t === 'function') return t(key, fallback);
    return fallback;
  }

  function _langZh() {
    return typeof getLanguage === 'function' && getLanguage() === 'zh';
  }

  function _api(path, method, body) {
    if (typeof api !== 'function') {
      return Promise.reject(new Error('api() is not available'));
    }
    return api(path, method, body);
  }

  function normalizeModelIds(modelIds) {
    return [...new Set((modelIds || []).map((v) => String(v || '').trim()).filter(Boolean))];
  }

  function statusFromResult(item, runningSet) {
    const modelId = String(item?.model || '').trim();
    if ((runningSet && runningSet.has(modelId)) || item?.status === 'testing') {
      return AVAIL_STATUS.testing;
    }
    if (!item) return AVAIL_STATUS.pending;
    if (item.available) return AVAIL_STATUS.ok;
    return AVAIL_STATUS.bad;
  }

  function normalizeModelTestState(apiState) {
    const results = (apiState && apiState.results) || {};
    const running = new Set(Array.isArray(apiState?.running) ? apiState.running.map(String) : []);
    const queue = new Set(Array.isArray(apiState?.queue) ? apiState.queue.map(String) : []);
    const statuses = {};
    const meta = {};

    Object.entries(results).forEach(([modelId, item]) => {
      const id = String(modelId || '').trim();
      if (!id) return;
      const row = item && typeof item === 'object' ? { ...item, model: item.model || id } : { model: id };
      const isRunning = running.has(id) || queue.has(id);
      statuses[id] = statusFromResult(row, isRunning ? new Set([id]) : running);
      meta[id] = {
        elapsed_ms: row.elapsed_ms,
        retry_after_seconds: row.retry_after_seconds,
        tested_at: row.tested_at,
        status_code: row.status_code,
        working_path: row.working_path,
        failure_kind: row.failure_kind,
        message: row.message,
        available: row.available,
      };
    });

    // running/queue 里尚未写入 results 的也标 testing
    [...running, ...queue].forEach((id) => {
      if (!statuses[id]) {
        statuses[id] = AVAIL_STATUS.testing;
        meta[id] = meta[id] || { tested_at: Math.floor(Date.now() / 1000) };
      } else if (running.has(id) || queue.has(id)) {
        statuses[id] = AVAIL_STATUS.testing;
      }
    });

    return {
      statuses,
      meta,
      runningSet: running,
      queueSet: queue,
      raw: apiState || {},
    };
  }

  function formatRetryAfter(seconds) {
    const value = Number(seconds || 0);
    if (!value) return '';
    if (value < 60) return _langZh() ? `${value} 秒后重试` : `Retry in ${value}s`;
    return _langZh() ? `${Math.ceil(value / 60)} 分钟后重试` : `Retry in ${Math.ceil(value / 60)}m`;
  }

  function formatElapsed(ms) {
    const value = Number(ms || 0);
    if (!value) return '';
    if (value < 1000) return `${value} ms`;
    return _langZh() ? `${(value / 1000).toFixed(1)} 秒` : `${(value / 1000).toFixed(1)} s`;
  }

  function statusLabel(status, meta = {}) {
    if (status === AVAIL_STATUS.ok) {
      return `${_t('common.available', 'Available')}${meta.working_model ? ` · ${meta.working_model}` : ''}`;
    }
    if (status === AVAIL_STATUS.bad) {
      return `${_t('common.unavailable', 'Unavailable')}${meta.retry_after_seconds ? ` · ${formatRetryAfter(meta.retry_after_seconds)}` : ''}`;
    }
    if (status === AVAIL_STATUS.testing) return _t('common.testing', 'Testing');
    return _t('common.pending', _langZh() ? '待检测' : 'Pending');
  }

  function statusTitle(status, meta = {}) {
    const isZh = _langZh();
    const lines = [
      `${isZh ? '状态' : 'Status'}: ${statusLabel(status, meta)}`,
    ];
    if (meta.working_path) lines.push(`${isZh ? '路径' : 'Path'}: ${meta.working_path}`);
    if (meta.working_model) lines.push(`${isZh ? '模型' : 'Model'}: ${meta.working_model}`);
    if (meta.elapsed_ms) lines.push(`${isZh ? '耗时' : 'Elapsed'}: ${formatElapsed(meta.elapsed_ms)}`);
    if (meta.retry_after_seconds) lines.push(`${isZh ? '重试' : 'Retry'}: ${formatRetryAfter(meta.retry_after_seconds)}`);
    if (meta.status_code) lines.push(`HTTP: ${meta.status_code}`);
    if (meta.failure_kind) lines.push(`${isZh ? '类型' : 'Kind'}: ${meta.failure_kind}`);
    if (meta.message) lines.push(`${isZh ? '信息' : 'Message'}: ${String(meta.message).slice(0, 180)}`);
    if (meta.available_count != null || meta.failed_count != null) {
      lines.push(
        isZh
          ? `模型：可用 ${meta.available_count || 0} / 失败 ${meta.failed_count || 0} / 共 ${meta.total_count || 0}`
          : `Models: ok ${meta.available_count || 0} / bad ${meta.failed_count || 0} / total ${meta.total_count || 0}`
      );
    }
    return lines.join('\n');
  }

  // 折叠态三色灯 class：绿可用 / 红不可用 / 黄检测中或待检测
  function lightClass(status) {
    if (status === AVAIL_STATUS.ok) return 'is-green';
    if (status === AVAIL_STATUS.bad) return 'is-red';
    if (status === AVAIL_STATUS.testing) return 'is-yellow is-busy';
    return 'is-yellow';
  }

  async function fetchAvailabilityState() {
    const data = await _api('/api/provider-model-test-state');
    return normalizeModelTestState(data);
  }

  async function queueModelTests(modelIds, options = {}) {
    const ids = normalizeModelIds(modelIds);
    if (!ids.length) {
      throw new Error(_langZh() ? '没有可检测的模型 ID。' : 'No model IDs to test.');
    }
    const clearFirst = options.clearFirst !== false;

    if (clearFirst) {
      try {
        await _api('/api/provider-model-tests', 'POST', { action: 'clear', model_ids: ids });
      } catch {
        // 忽略清理失败，继续入队
      }
    }

    try {
      const queued = await _api('/api/provider-model-tests', 'POST', { model_ids: ids });
      return {
        mode: 'queue',
        ids,
        response: queued,
        items: null,
      };
    } catch {
      // 旧后端或队列不可用时同步探测
      const fallback = await _api('/api/test-provider-models', 'POST', { model_ids: ids });
      const items = Array.isArray(fallback.items) ? fallback.items : [];
      return {
        mode: 'sync',
        ids,
        response: fallback,
        items,
      };
    }
  }

  async function clearModelTests(modelIds) {
    const ids = normalizeModelIds(modelIds);
    if (ids.length) {
      return _api('/api/provider-model-tests', 'POST', { action: 'clear', model_ids: ids });
    }
    return _api('/api/provider-model-tests', 'POST', { action: 'clear' });
  }

  async function stopModelTests() {
    return _api('/api/provider-model-tests', 'POST', { action: 'stop' });
  }

  /**
   * 从模型状态聚合账号/Provider 灯号。
   * - 无模型 / 全未测 → pending(黄)
   * - 任一 testing → testing(黄 busy)
   * - 至少一个 ok → ok(绿)
   * - 有结果且全 bad → bad(红)
   */
  function aggregateAuthLight(modelIds, state) {
    const ids = normalizeModelIds(modelIds);
    const statuses = state?.statuses || {};
    const metaMap = state?.meta || {};
    const runningSet = state?.runningSet || new Set();
    const queueSet = state?.queueSet || new Set();

    if (!ids.length) {
      return {
        status: AVAIL_STATUS.pending,
        meta: {
          message: _langZh() ? '没有关联的 runtime 模型。' : 'No linked runtime models.',
          total_count: 0,
          available_count: 0,
          failed_count: 0,
        },
      };
    }

    let availableCount = 0;
    let failedCount = 0;
    let pendingCount = 0;
    let testing = false;
    let newestMeta = null;
    let worstMeta = null;

    ids.forEach((id) => {
      const status = statuses[id] || (runningSet.has(id) || queueSet.has(id) ? AVAIL_STATUS.testing : AVAIL_STATUS.pending);
      const meta = metaMap[id] || {};
      if (status === AVAIL_STATUS.testing) testing = true;
      else if (status === AVAIL_STATUS.ok) {
        availableCount += 1;
        if (!newestMeta || Number(meta.tested_at || 0) >= Number(newestMeta.tested_at || 0)) {
          newestMeta = { ...meta, working_model: id };
        }
      } else if (status === AVAIL_STATUS.bad) {
        failedCount += 1;
        if (!worstMeta || Number(meta.tested_at || 0) >= Number(worstMeta.tested_at || 0)) {
          worstMeta = { ...meta, working_model: id };
        }
      } else {
        pendingCount += 1;
      }
    });

    const total = ids.length;
    if (testing) {
      return {
        status: AVAIL_STATUS.testing,
        meta: {
          total_count: total,
          available_count: availableCount,
          failed_count: failedCount,
          tested_at: Math.floor(Date.now() / 1000),
          message: _langZh() ? '模型检测进行中…' : 'Model tests running…',
        },
      };
    }
    if (availableCount > 0) {
      return {
        status: AVAIL_STATUS.ok,
        meta: {
          ...(newestMeta || {}),
          total_count: total,
          available_count: availableCount,
          failed_count: failedCount,
          working_model: newestMeta?.working_model,
          message: newestMeta?.message || (_langZh()
            ? `${availableCount}/${total} 个模型可用`
            : `${availableCount}/${total} models available`),
        },
      };
    }
    if (failedCount > 0 && pendingCount === 0) {
      return {
        status: AVAIL_STATUS.bad,
        meta: {
          ...(worstMeta || {}),
          total_count: total,
          available_count: 0,
          failed_count: failedCount,
          working_model: worstMeta?.working_model,
          message: worstMeta?.message || (_langZh()
            ? `${failedCount}/${total} 个模型不可用`
            : `${failedCount}/${total} models unavailable`),
        },
      };
    }
    return {
      status: AVAIL_STATUS.pending,
      meta: {
        total_count: total,
        available_count: availableCount,
        failed_count: failedCount,
        message: _langZh() ? '待检测' : 'Pending',
      },
    };
  }

  async function fetchProviderModelGroups(force = false) {
    const now = Date.now();
    if (!force && _providerModelsCache && (now - _providerModelsCacheAt) < PROVIDER_MODELS_TTL_MS) {
      return _providerModelsCache;
    }
    let data;
    try {
      data = await _api('/api/provider-models?runtime_state=1');
    } catch {
      data = await _api('/api/provider-models');
    }
    const groups = Array.isArray(data?.items) ? data.items : [];
    _providerModelsCache = groups;
    _providerModelsCacheAt = now;
    return groups;
  }

  function modelIdsForProvider(groups, provider) {
    const providerKey = String(provider || '').trim();
    if (!providerKey) return [];
    const list = Array.isArray(groups) ? groups : [];
    const group = list.find((entry) =>
      String(entry.provider || '').trim() === providerKey
      || String(entry.lookup_provider || '').trim() === providerKey
    );
    if (!group) return [];
    const rows = Array.isArray(group.rows) ? group.rows : [];
    const ids = [];
    rows.forEach((row) => {
      if (!row) return;
      // 优先 runtime 已注册；若接口未带 runtime 标记则全部纳入
      if (Object.prototype.hasOwnProperty.call(row, 'runtime_registered') && !row.runtime_registered) {
        return;
      }
      const callId = String(row.call_id || '').trim();
      if (callId && !ids.includes(callId)) ids.push(callId);
    });
    return ids;
  }

  async function resolveProviderModelIds(provider, force = false) {
    const groups = await fetchProviderModelGroups(force);
    return modelIdsForProvider(groups, provider);
  }

  /**
   * 轻量轮询：关注的 modelIds 仍在 running/queue 时继续。
   * onTick(state) 每次拉到状态后回调；返回 stop()。
   */
  function pollAvailability(modelIds, onTick, options = {}) {
    const ids = new Set(normalizeModelIds(modelIds));
    const intervalMs = Math.max(800, Number(options.intervalMs || 2000));
    const maxMs = Math.max(intervalMs, Number(options.maxMs || 10 * 60 * 1000));
    let stopped = false;
    let timer = null;
    const startedAt = Date.now();

    const tick = async () => {
      if (stopped) return;
      try {
        const state = await fetchAvailabilityState();
        if (typeof onTick === 'function') onTick(state);
        const stillBusy = [...ids].some((id) =>
          state.runningSet.has(id)
          || state.queueSet.has(id)
          || state.statuses[id] === AVAIL_STATUS.testing
        );
        if (!stillBusy || (Date.now() - startedAt) > maxMs) {
          stopped = true;
          return;
        }
      } catch {
        // 网络抖动时继续下一轮
      }
      if (!stopped) timer = setTimeout(tick, intervalMs);
    };

    timer = setTimeout(tick, 200);
    return () => {
      stopped = true;
      if (timer) clearTimeout(timer);
    };
  }

  const apiExport = {
    AVAIL_STATUS,
    normalizeModelIds,
    statusFromResult,
    normalizeModelTestState,
    formatRetryAfter,
    formatElapsed,
    statusLabel,
    statusTitle,
    lightClass,
    fetchAvailabilityState,
    queueModelTests,
    clearModelTests,
    stopModelTests,
    aggregateAuthLight,
    fetchProviderModelGroups,
    modelIdsForProvider,
    resolveProviderModelIds,
    pollAvailability,
  };

  global.Availability = apiExport;
  // 兼容直接全局调用
  Object.keys(apiExport).forEach((key) => {
    if (typeof global[key] === 'undefined') global[key] = apiExport[key];
  });
})(typeof window !== 'undefined' ? window : globalThis);
