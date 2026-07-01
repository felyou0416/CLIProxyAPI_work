let activeMediaGroup = 'all'; // 'all', 'image', 'video'
let selectedMediaModels = new Set();
let mediaModelsFingerprint = '';

function isImageModelName(modelName) {
  const lower = String(modelName || '').toLowerCase();
  const keywords = [
    "image", "dall-e", "dalle", "stable-diffusion", "flux", "imagine", "midjourney", "sdxl",
    "sd-", "mj-", "dream", "kolors", "cogview", "seedream", "recraft", "playground", "pixelart"
  ];
  return keywords.some(kw => lower.includes(kw));
}

function isVideoModelName(modelName) {
  const lower = String(modelName || '').toLowerCase();
  return lower.includes("video");
}

async function loadMediaModels(includeAvailability = false) {
  const root = document.getElementById('media-model-list');
  if (!root) return;

  try {
    let items = providerModelItemsCache;
    if (!items.length) {
      try {
        items = await fetchRuntimeProviderModelItems();
      } catch {
        items = await fetchProviderModelItems();
      }
      providerModelItemsCache = items;
    }

    if (includeAvailability) {
      await syncProviderModelTestState();
    }

    // Filter items to only show media models
    const filteredItems = items.map(item => {
      const rows = normalizeProviderRows(item).filter(row => {
        const modelId = String(row.call_id || '').trim();
        const isImg = isImageModelName(modelId);
        const isVid = isVideoModelName(modelId);
        if (activeMediaGroup === 'image') return isImg;
        if (activeMediaGroup === 'video') return isVid;
        return isImg || isVid;
      });
      return { ...item, rows };
    }).filter(item => item.rows.length > 0);

    const currentFingerprint = `${activeMediaGroup}:${filteredItems.length}:${filteredItems.map(i => i.provider || i.lookup_provider || '').join(',')}`;
    if (currentFingerprint === mediaModelsFingerprint && root.innerHTML.trim() !== '') {
      updateMediaModelChipStatuses();
      updateMediaDetectionButtons();
      return;
    }
    mediaModelsFingerprint = currentFingerprint;

    const visibleIds = new Set(
      filteredItems.flatMap(item => item.rows.map(row => String(row.call_id || '').trim()).filter(Boolean))
    );
    selectedMediaModels = new Set([...selectedMediaModels].filter(id => visibleIds.has(id)));

    let html = filteredItems.map(item => mediaModelCardHtml(item)).join('');
    root.innerHTML = html
      ? html
      : `<div class="auth-empty">${getLanguage() === 'zh' ? '没有配置该类型的多媒体模型。' : 'No media models of this type configured.'}</div>`;

    bindMediaModelActions(root);
    updateMediaDetectionButtons();
  } catch (err) {
    showMessage(err.message, true);
  }
}

function mediaModelCardHtml(item) {
  const sourceProvider = String(item.lookup_provider || item.provider || '').trim();
  const provider = escapeProviderHtml(item.provider || sourceProvider || '-');
  const providerKey = escapeProviderHtml(sourceProvider || item.provider || '');
  const rows = item.rows;
  if (!rows.length) return '';
  const isTesting = rows.some((row) => providerModelsRunningSet.has(String(row.call_id || '').trim()));

  return `
    <article class="provider-model-card">
      <div class="provider-model-head">
        <div class="provider-model-name">${provider}</div>
        <div class="provider-model-actions">
          <span class="provider-model-summary">${escapeProviderHtml(getProviderStatusSummary(rows))}</span>
          <button type="button" class="secondary provider-test-btn ${isTesting ? 'is-testing' : ''}" data-provider-key="${providerKey}" data-media-provider-test ${isTesting ? 'disabled' : ''}>${isTesting ? '检测中' : '检测本组'}</button>
        </div>
      </div>
      <div class="provider-model-call-list">
        ${rows.map(mediaModelChipHtml).join('')}
      </div>
    </article>`;
}

function mediaModelChipHtml(row) {
  const model = String(row?.call_id || '').trim();
  const status = providerModelStatuses[model] || '';
  const meta = providerModelStatusMeta[model] || {};
  const selected = selectedMediaModels.has(model);
  const statusLabel = modelStatusLabel(status, meta);
  const reasonLabel = meta.failure_kind ? statusKindLabel(meta.failure_kind) : '';
  const typeLabel = isVideoModelName(model) ? (getLanguage() === 'zh' ? '视频生成' : 'Video') : (getLanguage() === 'zh' ? '图像生成' : 'Image');
  const titleLines = [
    `模型：${model}`,
    `类型：${typeLabel}`,
    `状态：${statusLabel}`,
  ];
  if (reasonLabel) titleLines.push(`原因：${reasonLabel}`);
  if (meta.elapsed_ms) titleLines.push(`耗时：${formatElapsedMs(meta.elapsed_ms)}`);
  if (meta.tested_at) titleLines.push(`检测时间：${formatTestedAt(meta.tested_at)}`);
  if (meta.message) titleLines.push(`详细信息：${meta.message}`);

  let badge = '';
  if (status === 'bad' && meta.failure_kind === 'forbidden') badge = '<span class="provider-model-retry">无权限</span>';
  else if (status === 'bad' && meta.failure_kind === 'quota') badge = '<span class="provider-model-retry">额度受限</span>';

  return `
    <button
      type="button"
      class="provider-model-call-id ${selected ? 'is-selected' : ''} ${status ? `status-${status}` : ''}"
      data-media-model-id="${escapeProviderHtml(model)}"
      title="${escapeProviderHtml(titleLines.join('\n'))}"
    >
      <span class="provider-model-status-dot ${status ? `status-${status}` : 'status-idle'}"></span>
      <span class="provider-model-chip-text">${escapeProviderHtml(model)}</span>
      ${badge}
    </button>`;
}

function bindMediaModelActions(root) {
  root.querySelectorAll('[data-media-model-id]').forEach(btn => {
    btn.onclick = () => {
      const model = btn.getAttribute('data-media-model-id');
      if (selectedMediaModels.has(model)) {
        selectedMediaModels.delete(model);
      } else {
        selectedMediaModels.add(model);
      }
      btn.classList.toggle('is-selected', selectedMediaModels.has(model));
      updateMediaDetectionButtons();
    };
  });

  root.querySelectorAll('[data-media-provider-test]').forEach(btn => {
    btn.onclick = async () => {
      const providerKey = btn.getAttribute('data-provider-key');
      const item = providerModelItemsCache.find(
        i => String(i.provider || i.lookup_provider || '').trim() === providerKey
      );
      if (!item) return;
      const ids = normalizeProviderRows(item)
        .map(row => String(row.call_id || '').trim())
        .filter(id => {
          const isImg = isImageModelName(id);
          const isVid = isVideoModelName(id);
          if (activeMediaGroup === 'image') return isImg;
          if (activeMediaGroup === 'video') return isVid;
          return isImg || isVid;
        });
      await runMediaModelDetection(ids);
    };
  });
}

function updateMediaModelChipStatuses() {
  document.querySelectorAll('[data-media-model-id]').forEach(btn => {
    const model = btn.getAttribute('data-media-model-id');
    const status = providerModelStatuses[model] || '';
    const meta = providerModelStatusMeta[model] || {};

    // Remove old status classes
    btn.className = btn.className.replace(/\bstatus-\S+/g, '');
    if (status) btn.classList.add(`status-${status}`);

    const dot = btn.querySelector('.provider-model-status-dot');
    if (dot) {
      dot.className = dot.className.replace(/\bstatus-\S+/g, '');
      dot.classList.add(status ? `status-${status}` : 'status-idle');
    }

    const typeLabel = isVideoModelName(model) ? (getLanguage() === 'zh' ? '视频生成' : 'Video') : (getLanguage() === 'zh' ? '图像生成' : 'Image');
    const statusLabel = modelStatusLabel(status, meta);
    const reasonLabel = meta.failure_kind ? statusKindLabel(meta.failure_kind) : '';
    const titleLines = [
      `模型：${model}`,
      `类型：${typeLabel}`,
      `状态：${statusLabel}`,
    ];
    if (reasonLabel) titleLines.push(`原因：${reasonLabel}`);
    if (meta.elapsed_ms) titleLines.push(`耗时：${formatElapsedMs(meta.elapsed_ms)}`);
    if (meta.tested_at) titleLines.push(`检测时间：${formatTestedAt(meta.tested_at)}`);
    if (meta.message) titleLines.push(`详细信息：${meta.message}`);
    btn.setAttribute('title', titleLines.join('\n'));

    // Update badge
    let badge = btn.querySelector('.provider-model-retry');
    if (badge) badge.remove();

    if (status === 'bad' && meta.failure_kind === 'forbidden') {
      btn.insertAdjacentHTML('beforeend', '<span class="provider-model-retry">无权限</span>');
    } else if (status === 'bad' && meta.failure_kind === 'quota') {
      btn.insertAdjacentHTML('beforeend', '<span class="provider-model-retry">额度受限</span>');
    }
  });

  // Update headers summary
  document.querySelectorAll('.provider-model-card').forEach(card => {
    const providerNameEl = card.querySelector('.provider-model-name');
    if (!providerNameEl) return;
    const providerName = providerNameEl.textContent.trim();
    const item = providerModelItemsCache.find(i => (i.provider || i.lookup_provider || '') === providerName);
    if (!item) return;

    const rows = normalizeProviderRows(item).filter(row => {
      const modelId = String(row.call_id || '').trim();
      const isImg = isImageModelName(modelId);
      const isVid = isVideoModelName(modelId);
      if (activeMediaGroup === 'image') return isImg;
      if (activeMediaGroup === 'video') return isVid;
      return isImg || isVid;
    });

    const summaryEl = card.querySelector('.provider-model-summary');
    if (summaryEl) {
      summaryEl.textContent = getProviderStatusSummary(rows);
    }
  });
}

function updateMediaDetectionButtons() {
  const selectedBtn = document.getElementById('media-test-selected-btn');
  const stopBtn = document.getElementById('media-stop-test-btn');
  const allBtn = document.getElementById('media-test-all-btn');
  const selectedIds = [...selectedMediaModels];
  const hasSelected = selectedIds.length > 0;
  const anySelectedRunning = hasSelected && selectedIds.some((id) => providerModelsRunningSet.has(id));
  const anyRunning = providerModelsRunningSet.size > 0;

  if (selectedBtn) {
    selectedBtn.disabled = !hasSelected || anySelectedRunning;
    selectedBtn.classList.toggle('is-testing', anySelectedRunning);
    selectedBtn.textContent = anySelectedRunning ? '检测中' : '检测选中';
  }
  if (allBtn) {
    allBtn.disabled = anyRunning;
    allBtn.classList.toggle('is-testing', anyRunning);
    allBtn.textContent = anyRunning ? '检测中' : '检测全部';
  }
  if (stopBtn) {
    stopBtn.disabled = !anyRunning;
    stopBtn.classList.toggle('is-testing', anyRunning);
  }
}

function selectMediaGroup(group, btn) {
  activeMediaGroup = group;
  const tabs = document.querySelectorAll('#media-model-groups .provider-map-tab');
  tabs.forEach(t => t.classList.remove('is-active'));
  btn.classList.add('is-active');
  loadMediaModels(false);
}

function clearMediaModelSelection() {
  selectedMediaModels.clear();
  document.querySelectorAll('[data-media-model-id]').forEach(btn => {
    btn.classList.remove('is-selected');
  });
  updateMediaDetectionButtons();
}

async function clearMediaModelTestResults() {
  try {
    await api('/api/provider-model-tests', 'POST', { action: 'clear' });
    providerModelStatuses = {};
    providerModelStatusMeta = {};
    updateMediaModelChipStatuses();
    updateMediaDetectionButtons();
    showMessage(getLanguage() === 'zh' ? '检测结果已清除。' : 'Test results cleared.');
  } catch (err) {
    showMessage(err.message, true);
  }
}

async function runMediaModelDetection(modelIds) {
  const ids = [...new Set((modelIds || []).map((value) => String(value || '').trim()).filter(Boolean))];
  if (!ids.length) {
    showMessage(getLanguage() === 'zh' ? '请先选择至少一个模型。' : 'Please select at least one model first.', true);
    return;
  }

  try {
    try {
      await api('/api/provider-model-tests', 'POST', { action: 'clear', model_ids: ids });
    } catch {}

    ids.forEach((id) => {
      providerModelsRunningSet.delete(id);
      delete providerModelStatuses[id];
      delete providerModelStatusMeta[id];
    });

    try {
      await api('/api/provider-model-tests', 'POST', { model_ids: ids });
    } catch {
      const fallback = await api('/api/test-provider-models', 'POST', { model_ids: ids });
      const items = Array.isArray(fallback.items) ? fallback.items : [];
      items.forEach((item) => {
        providerModelsRunningSet.delete(item.model);
        providerModelStatuses[item.model] = item.available ? 'ok' : 'bad';
        providerModelStatusMeta[item.model] = {
          elapsed_ms: item.elapsed_ms,
          failure_kind: item.failure_kind,
          message: item.message,
        };
      });
    }

    loadMediaModels(true);
    startMediaPollTimer();
  } catch (err) {
    showMessage(err.message, true);
  }
}

async function testSelectedMediaModels() {
  await runMediaModelDetection([...selectedMediaModels]);
}

async function testAllMediaModels() {
  let items = providerModelItemsCache;
  const ids = items.flatMap(item => {
    return normalizeProviderRows(item).map(row => String(row.call_id || '').trim()).filter(id => {
      const isImg = isImageModelName(id);
      const isVid = isVideoModelName(id);
      if (activeMediaGroup === 'image') return isImg;
      if (activeMediaGroup === 'video') return isVid;
      return isImg || isVid;
    });
  });
  await runMediaModelDetection(ids);
}

async function stopMediaModelTests() {
  try {
    await api('/api/provider-model-tests', 'POST', { action: 'stop' });
    if (providerModelStatePollTimer) {
      clearInterval(providerModelStatePollTimer);
      providerModelStatePollTimer = null;
    }
    await loadMediaModels(true);
    showMessage(getLanguage() === 'zh' ? '检测已停止。' : 'Detection stopped.');
  } catch (err) {
    showMessage(err.message, true);
  }
}

function startMediaPollTimer() {
  if (providerModelStatePollTimer) return;
  providerModelStatePollTimer = setInterval(async () => {
    await syncProviderModelTestState();
    updateMediaModelChipStatuses();
    updateMediaDetectionButtons();
    if (providerModelsRunningSet.size === 0) {
      clearInterval(providerModelStatePollTimer);
      providerModelStatePollTimer = null;
    }
  }, 1000);
}
