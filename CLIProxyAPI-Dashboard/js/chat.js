/* ─── Chat Module ─── */
const CHAT_STORAGE_KEY = 'cliproxyapi_chat_sessions';
const CHAT_ACTIVE_KEY  = 'cliproxyapi_chat_active';
const CHAT_ACTIVE_BY_MODE_KEY = 'cliproxyapi_chat_active_by_mode';
const CHAT_MODE_KEY = 'cliproxyapi_chat_mode';
const MAX_SESSIONS = 20;

let chatContext = [];
let isGenerating = false;
let chatSessions = [];   // [{id, title, model, messages, ts}]
let chatSessionsLoaded = false;
let activeSessionId = null;
let activeSessionIdsByMode = {};
let chatMode = normalizeChatMode(localStorage.getItem(CHAT_MODE_KEY));
let chatRequestSeq = 0;
const chatRequestViews = {};

function normalizeChatMode(mode) {
  return mode === 'image' ? 'image' : mode === 'video' ? 'video' : 'chat';
}

// ─── Persistence helpers ───
function loadChatSessions() {
  if (chatSessionsLoaded) {
    activeSessionId = activeSessionIdsByMode[chatMode] || null;
    return;
  }
  try {
    chatSessions = JSON.parse(localStorage.getItem(CHAT_STORAGE_KEY) || '[]');
  } catch { chatSessions = []; }
  chatSessions = Array.isArray(chatSessions) ? chatSessions : [];
  chatSessions.forEach((session) => {
    session.mode = normalizeChatMode(session.mode);
    session.messages = Array.isArray(session.messages) ? session.messages : [];
    session.ts = Number(session.ts || 0) || Date.now();
    session.status = session.status || 'idle';
    session.pendingRequestId = session.pendingRequestId || '';
    session.pendingMode = session.pendingRequestId ? normalizeChatMode(session.pendingMode || session.mode) : '';
    session.pendingStartedAt = Number(session.pendingStartedAt || 0) || 0;
    session.pendingDraftText = typeof session.pendingDraftText === 'string' ? session.pendingDraftText : '';
    session.pendingError = session.pendingError || '';
  });
  try {
    const stored = JSON.parse(localStorage.getItem(CHAT_ACTIVE_BY_MODE_KEY) || '{}');
    activeSessionIdsByMode = stored && typeof stored === 'object' ? stored : {};
  } catch {
    activeSessionIdsByMode = {};
  }
  const legacyActiveId = localStorage.getItem(CHAT_ACTIVE_KEY) || null;
  const legacySession = legacyActiveId ? chatSessions.find(s => s.id === legacyActiveId) : null;
  if (legacySession && !activeSessionIdsByMode[legacySession.mode]) {
    activeSessionIdsByMode[legacySession.mode] = legacySession.id;
  }
  ['chat', 'image', 'video'].forEach((mode) => {
    const id = activeSessionIdsByMode[mode];
    const found = id ? chatSessions.find(s => s.id === id && normalizeChatMode(s.mode) === mode) : null;
    if (!found) {
      const latest = getModeSessions(mode)[0];
      if (latest) activeSessionIdsByMode[mode] = latest.id;
      else delete activeSessionIdsByMode[mode];
    }
  });
  activeSessionId = activeSessionIdsByMode[chatMode] || null;
  chatSessionsLoaded = true;
}

function saveChatSessions() {
  ['chat', 'image', 'video'].forEach((mode) => {
    const modeSessions = chatSessions
      .filter(s => normalizeChatMode(s.mode) === mode)
      .sort((left, right) => Number(right.ts || 0) - Number(left.ts || 0));
    const keepIds = new Set(modeSessions.slice(0, MAX_SESSIONS).map(s => s.id));
    chatSessions = chatSessions.filter(s => normalizeChatMode(s.mode) !== mode || keepIds.has(s.id));
    if (activeSessionIdsByMode[mode] && !keepIds.has(activeSessionIdsByMode[mode])) {
      const next = modeSessions.find(s => keepIds.has(s.id));
      if (next) activeSessionIdsByMode[mode] = next.id;
      else delete activeSessionIdsByMode[mode];
    }
  });
  activeSessionId = activeSessionIdsByMode[chatMode] || null;
  localStorage.setItem(CHAT_STORAGE_KEY, JSON.stringify(chatSessions));
  localStorage.setItem(CHAT_ACTIVE_KEY, activeSessionId || '');
  localStorage.setItem(CHAT_ACTIVE_BY_MODE_KEY, JSON.stringify(activeSessionIdsByMode));
}

function getActiveSession() {
  const session = chatSessions.find(s => s.id === activeSessionId) || null;
  return session && normalizeChatMode(session.mode) === chatMode ? session : null;
}

function isSessionRunning(session) {
  return !!(session && session.status === 'running' && session.pendingRequestId);
}

function isCurrentSessionRunning() {
  return isSessionRunning(getActiveSession());
}

function getSessionModeLabel(mode) {
  const normalized = normalizeChatMode(mode);
  if (normalized === 'image') return 'Image';
  if (normalized === 'video') return 'Video';
  return 'Assistant';
}

function makeChatRequestId() {
  chatRequestSeq += 1;
  return `r_${Date.now()}_${chatRequestSeq}`;
}

function isSessionVisible(session) {
  return !!(session && session.id === activeSessionId && normalizeChatMode(session.mode) === chatMode);
}

function markSessionRunning(session, mode, requestId) {
  if (!session) return;
  session.status = 'running';
  session.pendingRequestId = requestId;
  session.pendingMode = normalizeChatMode(mode || session.mode);
  session.pendingStartedAt = Date.now();
  session.pendingDraftText = '';
  session.pendingError = '';
  session.ts = Date.now();
  saveChatSessions();
}

function markSessionDraft(session, requestId, draftText, forceSave = false) {
  if (!session || session.pendingRequestId !== requestId) return;
  session.pendingDraftText = draftText || '';
  session.ts = Date.now();
  const view = chatRequestViews[requestId];
  if (view?.contentDiv?.isConnected) {
    if (session.pendingDraftText) updateBotMessageContent(view.contentDiv, session.pendingDraftText, false);
    else view.contentDiv.innerHTML = `<div class="typing-indicator"><span></span><span></span><span></span></div>`;
    if (view.history?.isConnected) {
      requestAnimationFrame(() => view.history.scrollTo({ top: view.history.scrollHeight, behavior: 'smooth' }));
    }
  }
  if (forceSave || !session._lastPendingSaveAt || Date.now() - session._lastPendingSaveAt > 300) {
    Object.defineProperty(session, '_lastPendingSaveAt', {
      value: Date.now(),
      writable: true,
      configurable: true
    });
    saveChatSessions();
  }
}

function clearSessionPending(session) {
  if (!session) return;
  delete session._lastPendingSaveAt;
  session.pendingRequestId = '';
  session.pendingMode = '';
  session.pendingStartedAt = 0;
  session.pendingDraftText = '';
  session.pendingError = '';
}

function finalizeSessionReply(session, requestId, replyText) {
  if (!session || session.pendingRequestId !== requestId) return;
  const content = replyText || session.pendingDraftText || '';
  if (content) session.messages.push({ role: 'assistant', content });
  session.status = 'idle';
  clearSessionPending(session);
  session.ts = Date.now();
  saveChatSessions();
  delete chatRequestViews[requestId];
  if (isSessionVisible(session)) {
    restoreChatSessionView(session);
    renderChatHistoryList();
  }
}

function markSessionFailed(session, requestId, message) {
  if (!session || session.pendingRequestId !== requestId) return;
  session.status = 'error';
  session.pendingError = message || 'Request failed';
  session.ts = Date.now();
  saveChatSessions();
  delete chatRequestViews[requestId];
  if (isSessionVisible(session)) {
    restoreChatSessionView(session);
    renderChatHistoryList();
  }
}

function updateChatGeneratingState() {
  isGenerating = isCurrentSessionRunning();
}

function getModeSessions(mode = chatMode) {
  const normalized = normalizeChatMode(mode);
  return chatSessions
    .filter(s => normalizeChatMode(s.mode) === normalized)
    .sort((left, right) => Number(right.ts || 0) - Number(left.ts || 0));
}

function setActiveSessionForMode(mode, id) {
  const normalized = normalizeChatMode(mode);
  const found = id ? chatSessions.find(s => s.id === id && normalizeChatMode(s.mode) === normalized) : null;
  if (found) {
    activeSessionIdsByMode[normalized] = found.id;
    if (normalized === chatMode) activeSessionId = found.id;
  } else {
    delete activeSessionIdsByMode[normalized];
    if (normalized === chatMode) activeSessionId = null;
  }
}

function generateSessionId() {
  return 's_' + Date.now() + '_' + Math.random().toString(36).slice(2, 8);
}

function deriveTitle(msg) {
  const t = (msg || '').trim().replace(/\n/g, ' ');
  return t.length > 40 ? t.slice(0, 40) + '…' : t || 'New Chat';
}

function isImageMode() {
  return chatMode === 'image';
}

function isVideoMode() {
  return chatMode === 'video';
}

function isMediaMode() {
  return isImageMode() || isVideoMode();
}

function setChatMode(mode) {
  chatMode = normalizeChatMode(mode);
  localStorage.setItem(CHAT_MODE_KEY, chatMode);
  activeSessionId = activeSessionIdsByMode[chatMode] || null;
  const session = getActiveSession();
  if (session) restoreChatSessionView(session);
  else {
    const sp = document.getElementById('chat-system-prompt');
    if (sp) sp.value = '';
    chatContext = [];
    clearChatView();
  }
  saveChatSessions();
  renderChatHistoryList();
  syncChatModeUI();
}

function isImageModelId(model) {
  const m = String(model || '').toLowerCase();
  return m === 'comage' || m === 'image' || m.includes('image');
}

function isVideoModelId(model) {
  const m = String(model || '').toLowerCase();
  return m === 'video' || m.includes('video') || m.startsWith('sora');
}

function imageModelRank(model) {
  const m = String(model || '').toLowerCase();
  if (!isImageModelId(m)) return 100;
  if (m.includes('agnes') && m.includes('image-2.1')) return 0;
  if (m.includes('agnes') && m.includes('image')) return 1;
  if (m === 'gpt-image-2' || m.endsWith('-gpt-image-2')) return 5;
  if (m.includes('gpt-image')) return 6;
  if (m === 'comage' || m === 'image') return 8;
  return 20;
}

function videoModelRank(model) {
  const m = String(model || '').toLowerCase();
  if (!isVideoModelId(m)) return 100;
  if (m.includes('agnes') && m.includes('video-v2.0')) return 0;
  if (m.includes('agnes') && m.includes('video')) return 1;
  if (m.startsWith('sora')) return 5;
  if (m === 'video') return 8;
  return 20;
}

function selectPreferredImageModel() {
  const select = document.getElementById('chat-model-select');
  if (!select || !select.options.length) return;
  const options = Array.from(select.options).filter(option => option.value);
  const imageOptions = options
    .filter(option => isImageModelId(option.value))
    .sort((left, right) => imageModelRank(left.value) - imageModelRank(right.value));
  const match = imageOptions[0];
  if (!match || imageModelRank(select.value) <= imageModelRank(match.value)) return;
  if (match) {
    select.value = match.value;
    const session = getActiveSession();
    if (session) {
      session.model = match.value;
      session.ts = Date.now();
      saveChatSessions();
      renderChatHistoryList();
    }
  }
}

function selectPreferredVideoModel() {
  const select = document.getElementById('chat-model-select');
  if (!select || !select.options.length) return;
  const options = Array.from(select.options).filter(option => option.value);
  const videoOptions = options
    .filter(option => isVideoModelId(option.value))
    .sort((left, right) => videoModelRank(left.value) - videoModelRank(right.value));
  const match = videoOptions[0];
  if (!match || videoModelRank(select.value) <= videoModelRank(match.value)) return;
  select.value = match.value;
  const session = getActiveSession();
  if (session) {
    session.model = match.value;
    session.ts = Date.now();
    saveChatSessions();
    renderChatHistoryList();
  }
}

function syncChatModeUI() {
  document.querySelectorAll('[data-chat-mode]').forEach(btn => {
    btn.classList.toggle('active', btn.dataset.chatMode === chatMode);
  });

  const imageOptions = document.getElementById('chat-image-options');
  if (imageOptions) imageOptions.hidden = !isImageMode();
  const videoOptions = document.getElementById('chat-video-options');
  if (videoOptions) videoOptions.hidden = !isVideoMode();

  const optionsSidebar = document.getElementById('chat-options-sidebar');
  if (optionsSidebar) {
    optionsSidebar.hidden = !isMediaMode();
  }
  const optionsTitle = document.getElementById('options-sidebar-title');
  if (optionsTitle) {
    optionsTitle.textContent = isImageMode() ? '画图参数' : '视频参数';
  }

  const settingsBar = document.getElementById('chat-settings-bar');
  const systemToggle = document.getElementById('chat-system-toggle');
  if (isMediaMode()) {
    if (settingsBar) settingsBar.hidden = true;
    if (systemToggle) {
      systemToggle.hidden = true;
      systemToggle.classList.remove('active');
    }
  } else if (systemToggle) {
    systemToggle.hidden = false;
    if (settingsBar && !settingsBar.hidden) systemToggle.classList.add('active');
  }

  const input = document.getElementById('chat-input');
  if (input) {
    input.placeholder = isImageMode()
      ? '描述要生成的图片...'
      : isVideoMode()
        ? '描述要生成的视频...'
      : '发送消息...';
  }

  const sendBtn = document.querySelector('.chat-send-btn');
  if (sendBtn) {
    sendBtn.title = isImageMode() ? '生成图片 (Enter)' : isVideoMode() ? '生成视频 (Enter)' : '发送 (Enter)';
  }

  if (isImageMode()) selectPreferredImageModel();
  if (isVideoMode()) selectPreferredVideoModel();

  const history = document.getElementById('chat-history');
  if (history && history.querySelector('.chat-welcome')) renderChatWelcome();
  renderChatHistoryList();
  updateChatSendState();
}

function toggleChatSystemPrompt() {
  if (isMediaMode()) return;
  const settingsBar = document.getElementById('chat-settings-bar');
  const systemToggle = document.getElementById('chat-system-toggle');
  if (!settingsBar) return;
  settingsBar.hidden = !settingsBar.hidden;
  if (systemToggle) systemToggle.classList.toggle('active', !settingsBar.hidden);
  if (!settingsBar.hidden) {
    const sp = document.getElementById('chat-system-prompt');
    if (sp) sp.focus();
  }
}

function setImagePreset(button) {
  document.querySelectorAll('[data-image-preset]').forEach(btn => btn.classList.remove('active'));
  button.classList.add('active');
}

function getImagePreset() {
  return document.querySelector('[data-image-preset].active')?.dataset.imagePreset || '';
}

function getImageOptions() {
  const size = document.getElementById('image-size-select')?.value || '1024x1024';
  const quality = document.getElementById('image-quality-select')?.value || 'medium';
  const background = document.getElementById('image-background-select')?.value || 'auto';
  const outputFormat = document.getElementById('image-format-select')?.value || 'png';
  return {
    size,
    quality,
    background,
    output_format: outputFormat,
    response_format: 'url'
  };
}

function getVideoOptions() {
  const numFrames = Number(document.getElementById('video-frames-select')?.value || 81);
  const frameRate = Number(document.getElementById('video-frame-rate-select')?.value || 24);
  const withAudio = Boolean(document.getElementById('video-audio-toggle')?.checked);
  const audioPrompt = (document.getElementById('video-audio-prompt')?.value || '').trim();
  const options = {
    num_frames: numFrames,
    frame_rate: frameRate,
    generate_audio: withAudio,
    with_audio: withAudio,
    extra_body: {
      num_frames: numFrames,
      frame_rate: frameRate
    }
  };
  if (audioPrompt) {
    options.audio_prompt = audioPrompt;
    options.extra_body.audio_prompt = audioPrompt;
  }
  if (withAudio) {
    options.extra_body.generate_audio = true;
    options.extra_body.with_audio = true;
  }
  return {
    ...options
  };
}

function buildImagePrompt(content) {
  const preset = getImagePreset();
  return preset ? `${content}\n\nStyle: ${preset}.` : content;
}

async function chatFetchJson(path, method = 'GET', body) {
  const headers = { 'Content-Type': 'application/json' };
  const token = getAuthToken();
  if (token) {
    headers['Authorization'] = 'Bearer ' + token;
  }
  const res = await fetch(path, {
    method,
    headers,
    body: body ? JSON.stringify(body) : undefined,
  });
  if (res.status === 401) {
    clearAuthToken();
    showLoginScreen();
    throw new Error('Authentication required');
  }
  const text = await res.text();
  let data = null;
  try {
    data = text ? JSON.parse(text) : {};
  } catch {
    const hint = text.trim().startsWith('<')
      ? `${path} returned a page instead of JSON`
      : `${path} returned invalid JSON`;
    throw new Error(hint);
  }
  if (!res.ok) {
    throw new Error(data?.error?.message || data?.message || `Request failed: ${path}`);
  }
  return data;
}

async function chatFetchFirstJson(paths, method = 'GET', body) {
  let lastError = null;
  for (const path of paths) {
    try {
      return await chatFetchJson(path, method, body);
    } catch (err) {
      err.requestPath = path;
      lastError = err;
    }
  }
  throw lastError || new Error('Request failed');
}

function extractVideoResultFromPayload(payload) {
  const root = payload && typeof payload === 'object' ? payload : {};
  const pick = (obj, path) => {
    let current = obj;
    for (const part of path.split('.')) {
      if (!current || typeof current !== 'object' || !(part in current)) return '';
      current = current[part];
    }
    return typeof current === 'string' || typeof current === 'number' ? String(current).trim() : '';
  };
  for (const path of ['video.url', 'video_url', 'url', 'data.url', 'output.video.url']) {
    const url = pick(root, path);
    if (url) return { url, id: '' };
  }
  if (Array.isArray(root.data)) {
    for (const item of root.data) {
      const nested = extractVideoResultFromPayload(item);
      if (nested.url || nested.id) return nested;
    }
  }
  for (const path of ['video_id', 'request_id', 'task_id', 'id', 'data.id']) {
    const id = pick(root, path);
    if (id) return { url: '', id };
  }
  return { url: '', id: '' };
}

function chatCompletionText(response) {
  return response?.choices?.[0]?.message?.content || '';
}

async function requestVideoGenerationFallback(model, prompt, options) {
  const directPayload = {
    model,
    prompt,
    stream: false,
    ...options
  };
  const response = await chatFetchFirstJson(['/api/video-generation', '/v1/videos/generations'], 'POST', directPayload);
  const result = extractVideoResultFromPayload(response);
  if (result.url) return `[video](${result.url})`;
  if (result.id) {
    try {
      const retrieved = await chatFetchJson(`/v1/videos/${encodeURIComponent(result.id)}?model=${encodeURIComponent(model)}`, 'GET');
      const retrievedResult = extractVideoResultFromPayload(retrieved);
      if (retrievedResult.url) return `[video](${retrievedResult.url})`;
    } catch (err) {
      console.warn('Video retrieve fallback failed', err);
    }
    return `Video generation task created: ${result.id}\n\nThe provider returned a task id but no playable URL yet.`;
  }
  throw new Error('Video response did not include a playable URL or task id.');
}

function modelsFromProviderItems(items) {
  const providers = {};
  (items || []).forEach(item => {
    const providerName = item.provider || item.lookup_provider || 'Unknown';
    if (!providers[providerName]) providers[providerName] = [];
    const rows = Array.isArray(item.rows) ? item.rows : [];
    rows.forEach(row => {
      const callId = row.call_id || row.original_id;
      if (callId) providers[providerName].push(callId);
    });
  });
  return providers;
}

function modelsFromOpenAIList(data) {
  const models = Array.isArray(data?.data) ? data.data : [];
  return {
    Proxy: models.map(item => item.id).filter(Boolean)
  };
}

// ─── Session CRUD ───
function createNewSession(silent) {
  const id = generateSessionId();
  const session = {
    id,
    title: 'New Chat',
    model: document.getElementById('chat-model-select')?.value || '',
    mode: chatMode,
    systemPrompt: '',
    messages: [],   // [{role, content}]
    status: 'idle',
    pendingRequestId: '',
    pendingMode: '',
    pendingStartedAt: 0,
    pendingDraftText: '',
    pendingError: '',
    ts: Date.now()
  };
  chatSessions.push(session);
  setActiveSessionForMode(chatMode, id);
  chatContext = [];
  saveChatSessions();
  if (!silent) {
    const sp = document.getElementById('chat-system-prompt');
    if (sp) sp.value = '';
    renderChatHistoryList();
    clearChatView();
  }
  return session;
}

function restoreChatSessionView(session) {
  if (!session) {
    chatContext = [];
    clearChatView();
    return;
  }

  const sel = document.getElementById('chat-model-select');
  if (sel && session.model) sel.value = session.model;

  const sp = document.getElementById('chat-system-prompt');
  if (sp) sp.value = session.systemPrompt || '';

  chatContext = [];
  clearChatView();
  session.messages.forEach(m => {
    appendMessage(m.role, m.content, true);
    if (!isMediaMode()) chatContext.push({ role: m.role, content: m.content });
  });
  if (!isMediaMode() && session.systemPrompt) {
    chatContext.unshift({ role: 'system', content: session.systemPrompt });
  }
  renderPendingSessionState(session);
  updateChatGeneratingState();
  updateChatSendState();
}

function renderPendingSessionState(session) {
  if (!session || (!isSessionRunning(session) && session.status !== 'error')) return;
  const history = document.getElementById('chat-history');
  if (!history) return;
  const welcome = history.querySelector('.chat-welcome');
  if (welcome) welcome.remove();
  const requestId = session.pendingRequestId || `error_${session.id}`;
  const msgDiv = document.createElement('div');
  msgDiv.className = `chat-message ${session.status === 'error' ? 'error' : 'assistant'}`;
  const metaDiv = document.createElement('div');
  metaDiv.className = 'chat-message-meta';
  metaDiv.innerHTML = `${session.status === 'error' ? ICON.error : ICON.assistant}<span>${session.status === 'error' ? 'Error' : getSessionModeLabel(session.pendingMode || session.mode)}</span>`;
  const contentDiv = document.createElement('div');
  contentDiv.className = 'chat-message-content markdown-body';
  if (session.status === 'error') {
    const draft = session.pendingDraftText ? `${session.pendingDraftText}\n\n` : '';
    contentDiv.innerHTML = `<span style="color:var(--danger)">${escapeHtml(draft + (session.pendingError || 'Request failed'))}</span>`;
  } else if (session.pendingDraftText) {
    updateBotMessageContent(contentDiv, session.pendingDraftText, false);
  } else {
    contentDiv.innerHTML = `<div class="typing-indicator"><span></span><span></span><span></span></div>`;
  }
  msgDiv.appendChild(metaDiv);
  msgDiv.appendChild(contentDiv);
  history.appendChild(msgDiv);
  if (isSessionRunning(session)) {
    chatRequestViews[requestId] = { history, msgDiv, contentDiv };
  }
  requestAnimationFrame(() => history.scrollTo({ top: history.scrollHeight, behavior: 'smooth' }));
}

function switchToSession(id) {
  const session = chatSessions.find(s => s.id === id);
  if (!session) return;
  chatMode = normalizeChatMode(session.mode);
  localStorage.setItem(CHAT_MODE_KEY, chatMode);
  setActiveSessionForMode(chatMode, id);
  restoreChatSessionView(session);
  saveChatSessions();

  renderChatHistoryList();
  syncChatModeUI();
}

function deleteSession(id) {
  const deleted = chatSessions.find(s => s.id === id);
  const deletedMode = normalizeChatMode(deleted?.mode || chatMode);
  chatSessions = chatSessions.filter(s => s.id !== id);
  if (activeSessionIdsByMode[deletedMode] === id) {
    const next = getModeSessions(deletedMode)[0];
    if (next) setActiveSessionForMode(deletedMode, next.id);
    else setActiveSessionForMode(deletedMode, null);
  }
  if (chatMode === deletedMode) {
    const nextId = activeSessionIdsByMode[chatMode] || null;
    activeSessionId = nextId;
    const next = getActiveSession();
    if (next) restoreChatSessionView(next);
    else {
      chatContext = [];
      clearChatView();
    }
  }
  saveChatSessions();
  renderChatHistoryList();
  syncChatModeUI();
}

function renameSession(id) {
  const session = chatSessions.find(s => s.id === id);
  if (!session) return;
  const name = prompt('Rename session', session.title);
  if (name && name.trim()) {
    session.title = name.trim();
    saveChatSessions();
    renderChatHistoryList();
  }
}

// ─── Sidebar rendering ───
function renderChatHistoryList() {
  const container = document.getElementById('chat-session-list');
  if (!container) return;
  const modeSessions = getModeSessions(chatMode);
  const countEl = document.getElementById('chat-session-count');
  if (countEl) countEl.textContent = String(modeSessions.length);
  const titleEl = document.getElementById('chat-active-title');
  const activeSession = getActiveSession();
  if (titleEl) titleEl.textContent = activeSession?.title || (isImageMode() ? 'New Image Task' : isVideoMode() ? 'New Video Task' : 'New Chat');
  const subtitleEl = document.getElementById('chat-active-subtitle');
  if (subtitleEl) {
    const model = activeSession?.model || document.getElementById('chat-model-select')?.value || 'No model selected';
    const running = isSessionRunning(activeSession) ? ' · Running' : '';
    subtitleEl.textContent = `${chatMode.toUpperCase()} · ${model}${running}`;
  }
  const modeStatusEl = document.getElementById('chat-mode-status');
  if (modeStatusEl) {
    const unit = chatMode === 'chat' ? '个会话' : '个任务';
    modeStatusEl.textContent = `当前模式 ${modeSessions.length} ${unit}`;
  }

  if (modeSessions.length === 0) {
    const label = isImageMode() ? '图片任务' : isVideoMode() ? '视频任务' : '会话';
    container.innerHTML = `<div class="chat-session-empty">暂无${label}</div>`;
    return;
  }

  // Render in reverse-chronological order
  container.innerHTML = modeSessions.map(s => {
    const active = s.id === activeSessionId ? 'active' : '';
    const msgCount = s.messages.filter(m => m.role !== 'system').length;
    const timeStr = new Date(s.ts).toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' });
    return `<div class="chat-session-item ${active}" data-id="${s.id}" onclick="switchToSession('${s.id}')">
      <div class="chat-session-info">
        <div class="chat-session-title">${escapeHtml(s.title)}${isSessionRunning(s) ? ' · …' : ''}</div>
        <div class="chat-session-meta">${s.model ? escapeHtml(s.model).split('-').slice(0,3).join('-') : 'No model'} · ${msgCount} msg${isSessionRunning(s) ? ' · running' : ''} · ${timeStr}</div>
      </div>
      <div class="chat-session-actions">
        <button class="msg-action-btn" onclick="event.stopPropagation();renameSession('${s.id}')" title="Rename">
          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"></path><path d="M18.5 2.5a2.121 2.121 0 1 1 3 3L12 15l-4 1 1-4 9.5-9.5z"></path></svg>
        </button>
        <button class="msg-action-btn" onclick="event.stopPropagation();deleteSession('${s.id}')" title="Delete">
          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="3 6 5 6 21 6"></polyline><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"></path><line x1="10" y1="11" x2="10" y2="17"></line><line x1="14" y1="11" x2="14" y2="17"></line></svg>
        </button>
      </div>
    </div>`;
  }).join('');
}

function escapeHtml(str) {
  const d = document.createElement('div');
  d.textContent = str;
  return d.innerHTML;
}

// ─── Model Loading ───
async function loadChatPanel() {
  bindChatControls();
  loadChatSessions();
  renderChatHistoryList();

  const select = document.getElementById('chat-model-select');
  if (!select) return;
  select.innerHTML = '<option value="">Loading models...</option>';

  try {
    let providers = {};
    try {
      const runtimeData = await chatFetchJson('/api/provider-models?runtime_state=1');
      if (runtimeData && Array.isArray(runtimeData.items) && runtimeData.items.length > 0) {
        providers = modelsFromProviderItems(runtimeData.items);
      } else {
        const fallbackData = await chatFetchJson('/api/provider-models');
        providers = modelsFromProviderItems(Array.isArray(fallbackData.items) ? fallbackData.items : []);
      }
    } catch {
      const openaiModels = await chatFetchJson('/v1/models');
      providers = modelsFromOpenAIList(openaiModels);
    }

    select.innerHTML = '';
    let modelCount = 0;
    for (const [provider, models] of Object.entries(providers)) {
      if (models.length === 0) continue;
      const uniqueModels = [...new Set(models)];
      const optgroup = document.createElement('optgroup');
      optgroup.label = provider;
      uniqueModels.forEach(model => {
        modelCount++;
        const option = document.createElement('option');
        option.value = model;
        option.textContent = model;
        optgroup.appendChild(option);
      });
      select.appendChild(optgroup);
    }

    if (modelCount === 0) {
      select.innerHTML = '<option value="">No models found in API</option>';
    }

    // Restore active session's model selection
    const session = getActiveSession();
    if (session && session.model) {
      select.value = session.model;
    }
  } catch (err) {
    console.error('Failed to load chat models', err);
    select.innerHTML = '<option value="">Error loading models</option>';
  }

  // Restore active session for the current mode if it exists; otherwise keep a clean view.
  const session = getActiveSession();
  if (session) {
    restoreChatSessionView(session);
  } else {
    clearChatView();
  }
  renderChatHistoryList();
  syncChatModeUI();
  updateChatSendState();
}

// ─── Chat View ───
function renderChatWelcome() {
  const hist = document.getElementById('chat-history');
  if (!hist) return;
  const welcomeText = isImageMode()
    ? '描述你想生成的图片'
    : isVideoMode()
      ? '描述你想生成的视频'
      : '选择模型，开始对话';
  const welcomeHint = isImageMode()
    ? 'Enter 生成 · 在右侧设置尺寸与风格'
    : isVideoMode()
      ? 'Enter 生成 · 视频可能需要一分钟'
      : 'Enter 发送 · Shift+Enter 换行';
  hist.innerHTML = `<div class="chat-welcome">
    <div class="chat-welcome-icon">
      <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"></path></svg>
    </div>
    <div class="chat-welcome-text">${welcomeText}</div>
    <div class="chat-welcome-hint">${welcomeHint}</div>
  </div>`;
}

function clearChatView() {
  const hist = document.getElementById('chat-history');
  if (hist) renderChatWelcome();
  const inp = document.getElementById('chat-input');
  if (inp) { inp.value = ''; inp.style.height = ''; }
  updateChatSendState();
}

function clearChat() {
  if (activeSessionId) {
    const session = getActiveSession();
    if (session) {
      session.messages = [];
      session.title = 'New Chat';
      session.ts = Date.now();
      saveChatSessions();
    }
  }
  chatContext = [];
  clearChatView();
  renderChatHistoryList();
}

// ─── SVG Icons ───
const ICON = {
  user: `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"></path><circle cx="12" cy="7" r="4"></circle></svg>`,
  assistant: `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M12 8V4H8"></path><rect width="16" height="12" x="4" y="8" rx="2"></rect><path d="M2 14h2"></path><path d="M20 14h2"></path><path d="M15 13v2"></path><path d="M9 13v2"></path></svg>`,
  error: `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"></circle><line x1="12" y1="8" x2="12" y2="12"></line><line x1="12" y1="16" x2="12.01" y2="16"></line></svg>`,
  copy: `<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect width="14" height="14" x="8" y="8" rx="2" ry="2"></rect><path d="M4 16c-1.1 0-2-.9-2-2V4c0-1.1.9-2 2-2h10c1.1 0 2 .9 2 2"></path></svg>`,
  send: `<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="22" y1="2" x2="11" y2="13"></line><polygon points="22 2 15 22 11 13 2 9 22 2"></polygon></svg>`,
};

function copyPreCode(btn) {
  const pre = btn.closest('pre');
  const code = pre.querySelector('code');
  if (code) {
    // Exclude header text if any
    const codeText = Array.from(code.childNodes)
      .filter(node => node.className !== 'code-header')
      .map(node => node.textContent)
      .join('');
    navigator.clipboard.writeText(codeText || code.innerText);
    btn.textContent = 'Copied!';
    setTimeout(() => { btn.textContent = 'Copy'; }, 1500);
  }
}

function decorateMediaEmbeds(contentDiv) {
  contentDiv.querySelectorAll('a[href]').forEach(link => {
    const href = link.getAttribute('href') || '';
    const normalized = href.split('?')[0].toLowerCase();
    const label = (link.textContent || '').trim().toLowerCase();
    const looksVideo = normalized.endsWith('.mp4')
      || normalized.endsWith('.webm')
      || normalized.endsWith('.mov')
      || label === 'video'
      || label.includes('video');
    if (!looksVideo) return;
    const video = document.createElement('video');
    video.controls = true;
    video.preload = 'metadata';
    video.src = href;
    video.className = 'chat-generated-video';
    link.replaceWith(video);
  });
}

function updateBotMessageContent(contentDiv, content, isDone) {
  let processedContent = content;
  let thinkContent = '';
  const thinkStartIdx = content.indexOf('<think>');
  if (thinkStartIdx !== -1) {
    const thinkEndIdx = content.indexOf('</think>');
    if (thinkEndIdx !== -1) {
      thinkContent = content.slice(thinkStartIdx + 7, thinkEndIdx).trim();
      processedContent = (content.slice(0, thinkStartIdx) + content.slice(thinkEndIdx + 8)).trim();
    } else {
      thinkContent = content.slice(thinkStartIdx + 7).trim();
      processedContent = content.slice(0, thinkStartIdx).trim();
    }
  }

  let html = '';
  if (thinkContent) {
    const detailsAttr = isDone ? '' : 'open';
    html += `
      <div class="chat-thinking-block">
        <details class="chat-thinking-details" ${detailsAttr}>
          <summary class="chat-thinking-summary">
            <span class="chat-thinking-icon">🧠</span>
            <span class="chat-thinking-title">思考过程</span>
          </summary>
          <div class="chat-thinking-text">${escapeHtml(thinkContent)}</div>
        </details>
      </div>
    `;
  }

  if (processedContent) {
    if (typeof marked !== 'undefined') {
      try {
        if (typeof marked.parse === 'function') {
          html += marked.parse(processedContent);
        } else if (typeof marked === 'function') {
          html += marked(processedContent);
        } else {
          html += escapeHtml(processedContent).replace(/\n/g, '<br>');
        }
      } catch (e) {
        html += escapeHtml(processedContent).replace(/\n/g, '<br>');
      }
    } else {
      html += escapeHtml(processedContent).replace(/\n/g, '<br>');
    }
  }

  contentDiv.innerHTML = html;
  decorateMediaEmbeds(contentDiv);

  // Decorate code blocks
  contentDiv.querySelectorAll('pre').forEach(pre => {
    if (pre.querySelector('.code-header')) return;
    const code = pre.querySelector('code');
    const lang = code ? (code.className.match(/language-(\w+)/)?.[1] || 'code') : 'code';
    
    const header = document.createElement('div');
    header.className = 'code-header';
    header.style = 'display:flex;justify-content:space-between;align-items:center;background:color-mix(in srgb, var(--panel-2) 90%, black 10%);padding:6px 12px;font-size:11px;font-family:var(--font-sans);color:var(--text-muted);border-radius:6px 6px 0 0;border-bottom:1px solid var(--border);';
    header.innerHTML = `
      <span style="text-transform:uppercase;font-weight:700;">${lang}</span>
      <button type="button" style="background:transparent;border:0;color:var(--text-muted);cursor:pointer;font-size:11px;" onclick="copyPreCode(this)">Copy</button>
    `;
    
    pre.style.margin = '10px 0';
    pre.style.borderRadius = '8px';
    pre.style.overflow = 'hidden';
    pre.style.border = '1px solid var(--border)';
    if (code) {
      code.style.display = 'block';
      code.style.padding = '12px';
      code.style.background = 'var(--panel-2)';
      code.style.margin = '0';
    }
    pre.insertBefore(header, pre.firstChild);
  });

  // Highlight syntax
  if (typeof hljs !== 'undefined') {
    contentDiv.querySelectorAll('pre code').forEach(block => {
      try {
        if (typeof hljs.highlightElement === 'function') {
          hljs.highlightElement(block);
        } else if (typeof hljs.highlightBlock === 'function') {
          hljs.highlightBlock(block);
        }
      } catch (e) {}
    });
  }
}

function appendMessage(role, content, quiet) {
  const history = document.getElementById('chat-history');
  if (!history) return;
  const welcome = history.querySelector('.chat-welcome');
  if (welcome) welcome.remove();
  const msgDiv = document.createElement('div');
  msgDiv.className = `chat-message ${role}`;

  const metaDiv = document.createElement('div');
  metaDiv.className = 'chat-message-meta';
  let icon = ICON.assistant, label = 'Assistant';
  if (role === 'user') { icon = ICON.user; label = 'You'; }
  else if (role === 'error') { icon = ICON.error; label = 'Error'; }
  metaDiv.innerHTML = `${icon}<span>${label}</span>`;

  const contentDiv = document.createElement('div');
  contentDiv.className = 'chat-message-content markdown-body';

  if (role !== 'user') {
    updateBotMessageContent(contentDiv, content, true);
  } else {
    contentDiv.innerHTML = escapeHtml(content).replace(/\n/g, '<br>');
  }

  msgDiv.appendChild(metaDiv);
  msgDiv.appendChild(contentDiv);

  // Copy action
  if (role !== 'error') {
    const actionsDiv = document.createElement('div');
    actionsDiv.className = 'message-actions';
    const copyBtn = document.createElement('button');
    copyBtn.className = 'msg-action-btn';
    copyBtn.innerHTML = `${ICON.copy} Copy`;
    copyBtn.onclick = () => {
      navigator.clipboard.writeText(content);
      copyBtn.textContent = '✓ Copied';
      setTimeout(() => { copyBtn.innerHTML = `${ICON.copy} Copy`; }, 1500);
    };
    actionsDiv.appendChild(copyBtn);
    msgDiv.appendChild(actionsDiv);
  }

  history.appendChild(msgDiv);
  requestAnimationFrame(() => {
    history.scrollTo({ top: history.scrollHeight, behavior: 'smooth' });
  });
}

// ─── Input handling ───
function bindChatControls() {
  const chatInput = document.getElementById('chat-input');
  if (chatInput && chatInput.dataset.chatBound !== '1') {
    chatInput.dataset.chatBound = '1';
    chatInput.addEventListener('input', function () {
      this.style.height = 'auto';
      this.style.height = Math.min(this.scrollHeight, 200) + 'px';
      if (!this.value) this.style.height = '';
      updateChatSendState();
    });
  }

  const modelSelect = document.getElementById('chat-model-select');
  if (modelSelect && modelSelect.dataset.chatBound !== '1') {
    modelSelect.dataset.chatBound = '1';
    modelSelect.addEventListener('change', () => {
      const session = getActiveSession();
      if (session) {
        session.model = modelSelect.value;
        session.ts = Date.now();
        saveChatSessions();
        renderChatHistoryList();
      }
      updateChatSendState();
    });
  }

  const systemPrompt = document.getElementById('chat-system-prompt');
  if (systemPrompt && systemPrompt.dataset.chatBound !== '1') {
    systemPrompt.dataset.chatBound = '1';
    systemPrompt.addEventListener('input', () => {
      const session = getActiveSession();
      if (session) {
        session.systemPrompt = systemPrompt.value.trim();
        session.ts = Date.now();
        saveChatSessions();
      }
    });
  }

  syncChatModeUI();
  updateChatSendState();
}

document.addEventListener('DOMContentLoaded', bindChatControls);

function handleChatInputKeydown(e) {
  // Enter = send, Shift+Enter = newline
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault();
    sendChatMessage();
  }
}

function updateChatSendState() {
  const inputEl = document.getElementById('chat-input');
  const selectEl = document.getElementById('chat-model-select');
  const sendBtn = document.querySelector('.chat-send-btn');
  if (!sendBtn) return;
  const hasContent = !!inputEl?.value.trim();
  const hasModel = !!selectEl?.value;
  updateChatGeneratingState();
  sendBtn.disabled = isGenerating || !hasContent || !hasModel;
}

// ─── Send ───
async function sendChatMessage() {
  updateChatGeneratingState();
  if (isGenerating) return;

  const inputEl = document.getElementById('chat-input');
  const selectEl = document.getElementById('chat-model-select');
  if (!inputEl || !selectEl) return;
  const content = inputEl.value.trim();
  const model = selectEl.value;

  if (!content) return;
  if (!model) { alert('Please select a model first'); return; }

  const requestMode = chatMode;
  const requestIsImage = requestMode === 'image';
  const requestIsVideo = requestMode === 'video';
  const requestIsMedia = requestIsImage || requestIsVideo;

  let session = getActiveSession();
  if (!session) {
    session = createNewSession(true);
  } else if (normalizeChatMode(session.mode) !== requestMode) {
    session = createNewSession(true);
  }

  session.model = model;
  session.mode = normalizeChatMode(session.mode || requestMode);
  setActiveSessionForMode(requestMode, session.id);

  let fullContentToSend = content;
  if (chatAttachedFiles.length > 0) {
    chatAttachedFiles.forEach(file => {
      fullContentToSend += `\n\n**[Attached File: ${file.name}]**\n\`\`\`\n${file.content}\n\`\`\``;
    });
  }

  appendMessage('user', fullContentToSend);

  if (requestIsMedia) {
    chatContext = [];
  } else if (chatContext.length === 0) {
    const sysPrompt = document.getElementById('chat-system-prompt')?.value.trim();
    if (sysPrompt) {
      chatContext.push({ role: 'system', content: sysPrompt });
      session.systemPrompt = sysPrompt;
    }
  }
  if (!requestIsMedia) {
    chatContext.push({ role: 'user', content: fullContentToSend });
  }

  session.messages.push({ role: 'user', content: fullContentToSend });
  if (session.messages.filter(m => m.role === 'user').length === 1) {
    session.title = deriveTitle(content);
  }

  const requestId = makeChatRequestId();
  markSessionRunning(session, requestMode, requestId);
  renderChatHistoryList();

  inputEl.value = '';
  inputEl.style.height = '';
  chatAttachedFiles = [];
  renderChatAttachedFiles();

  const history = document.getElementById('chat-history');
  const botMsgDiv = document.createElement('div');
  botMsgDiv.className = 'chat-message assistant';
  botMsgDiv.id = `chat-bot-reply-${requestId}`;
  const botMetaDiv = document.createElement('div');
  botMetaDiv.className = 'chat-message-meta';
  botMetaDiv.innerHTML = `${ICON.assistant}<span>${getSessionModeLabel(requestMode)}</span>`;
  const botContentDiv = document.createElement('div');
  botContentDiv.className = 'chat-message-content markdown-body';
  botMsgDiv.appendChild(botMetaDiv);
  botMsgDiv.appendChild(botContentDiv);
  botContentDiv.innerHTML = `<div class="typing-indicator"><span></span><span></span><span></span></div>`;
  if (history) {
    history.appendChild(botMsgDiv);
    chatRequestViews[requestId] = { history, msgDiv: botMsgDiv, contentDiv: botContentDiv };
    requestAnimationFrame(() => history.scrollTo({ top: history.scrollHeight, behavior: 'smooth' }));
  }

  updateChatGeneratingState();
  updateChatSendState();

  try {
    const videoOptions = requestIsVideo ? getVideoOptions() : null;
    const payload = requestIsImage
      ? {
          model,
          messages: [{ role: 'user', content: buildImagePrompt(content) }],
          max_tokens: 4096,
          stream: false,
          ...getImageOptions()
        }
      : requestIsVideo
        ? {
            model,
            messages: [{ role: 'user', content }],
            max_tokens: 4096,
            stream: false,
            ...videoOptions
          }
        : { model, messages: chatContext.slice(), max_tokens: 4096, stream: true };

    if (requestIsMedia) {
      let reply = '';
      let mediaError = null;
      markSessionDraft(session, requestId, `${getSessionModeLabel(requestMode)} generation is running...`, true);
      try {
        const response = await chatFetchFirstJson(['/api/chat', '/v1/chat/completions'], 'POST', payload);
        reply = chatCompletionText(response);
        if (!reply) {
          throw new Error(response.error?.message || response.message || 'Invalid response format');
        }
      } catch (err) {
        mediaError = err;
        if (requestIsVideo) {
          reply = await requestVideoGenerationFallback(model, content, videoOptions || {});
        } else {
          throw err;
        }
      }
      markSessionDraft(session, requestId, reply, true);
      finalizeSessionReply(session, requestId, reply);
      if (mediaError) {
        console.warn('Primary media chat-completions path failed; video fallback succeeded.', mediaError);
      }
    } else {
      let streamSucceeded = false;
      try {
        const proto = window.location.protocol;
        const host = window.location.hostname;
        const streamUrl = `${proto}//${host}:8317/v1/chat/completions`;
        const apiKeys = await fetch('/api/virtual-keys').then(r => r.json()).catch(() => ({}));
        const api_key = Array.isArray(apiKeys.keys) && apiKeys.keys.length > 0 ? apiKeys.keys[0].key : '';

        const response = await fetch(streamUrl, {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            'Authorization': `Bearer ${api_key || 'dummy-key'}`
          },
          body: JSON.stringify(payload)
        });

        if (!response.ok) {
          throw new Error(`Direct stream request returned status ${response.status}`);
        }

        const reader = response.body.getReader();
        const decoder = new TextDecoder('utf-8');
        let buffer = '';
        let replyText = '';
        markSessionDraft(session, requestId, '', true);

        while (true) {
          const { value, done } = await reader.read();
          if (done) break;
          buffer += decoder.decode(value, { stream: true });
          const lines = buffer.split('\n');
          buffer = lines.pop();

          for (const line of lines) {
            const cleaned = line.trim();
            if (!cleaned) continue;
            if (cleaned === 'data: [DONE]') continue;
            if (cleaned.startsWith('data: ')) {
              try {
                const chunkJson = JSON.parse(cleaned.slice(6));
                const delta = chunkJson.choices?.[0]?.delta?.content || '';
                if (delta) {
                  replyText += delta;
                  markSessionDraft(session, requestId, replyText);
                }
              } catch (e) {
                // Ignore partial JSON parse errors
              }
            }
          }
        }

        markSessionDraft(session, requestId, replyText, true);
        finalizeSessionReply(session, requestId, replyText);
        streamSucceeded = true;
      } catch (streamErr) {
        console.warn('Streaming failed, falling back to standard API', streamErr);
      }

      if (!streamSucceeded) {
        payload.stream = false;
        const response = await chatFetchFirstJson(['/api/chat', '/v1/chat/completions'], 'POST', payload);
        if (response && response.choices && response.choices.length > 0) {
          const reply = response.choices[0].message.content;
          markSessionDraft(session, requestId, reply, true);
          finalizeSessionReply(session, requestId, reply);
        } else {
          throw new Error(response.error?.message || response.message || 'Invalid response format');
        }
      }
    }
  } catch (err) {
    console.error('Chat error:', err);
    const pathHint = err.requestPath ? ` · ${err.requestPath}` : '';
    markSessionFailed(session, requestId, `Error${pathHint} · ${model} · ${err.message || 'Request failed'}`);
  } finally {
    const view = chatRequestViews[requestId];
    if (view?.msgDiv?.isConnected) view.msgDiv.removeAttribute('id');
    delete chatRequestViews[requestId];
    updateChatGeneratingState();
    updateChatSendState();
    renderChatHistoryList();
    if (document.activeElement !== inputEl) return;
    inputEl.focus();
  }
}

// ─── Plus Menu & File/Skill upload ───
let chatAttachedFiles = []; // Array of { name, content }

const CHAT_SKILLS = {
  karpathy: {
    name: 'Karpathy Coding Guidelines',
    prompt: `You are an expert software engineer. Follow these principles strictly:
1. Surgical changes: Touch only what you must. Match existing style.
2. Simplicity: Write the minimum code needed to solve the problem. Avoid overcomplication.
3. Verification: Ensure all code is correct, well-structured, and verifiable. Do not guess.
4. Explanations: Keep explanations brief, concise, and focused on rationales rather than restating code.`
  },
  security: {
    name: 'Security Auditor',
    prompt: `You are a professional security auditor. Review the provided code/instructions for security vulnerabilities, injection risks, authentication issues, and data leakage. Suggest secure, robust remedies and explain the attack vectors clearly.`
  },
  analyst: {
    name: 'Data Analyst',
    prompt: `You are a senior data analyst. Help me parse, organize, and analyze data. Present findings in clear Markdown tables, highlight trends, and provide actionable business recommendations.`
  },
  translator: {
    name: 'Professional Translator',
    prompt: `You are a professional translator specializing in software, localization, and technical documentation. Translate the inputs accurately between English and Chinese, preserving terminology, markdown formatting, and tone.`
  }
};

function toggleChatPlusMenu(e) {
  e.stopPropagation();
  const menu = document.getElementById('chat-plus-menu');
  if (menu) {
    const isHidden = menu.style.display === 'none';
    menu.style.display = isHidden ? 'flex' : 'none';
  }
}

function closeChatPlusMenu() {
  const menu = document.getElementById('chat-plus-menu');
  if (menu) menu.style.display = 'none';
}

document.addEventListener('click', () => {
  closeChatPlusMenu();
});

function triggerChatFileUpload() {
  let fileInp = document.getElementById('chat-file-input');
  if (!fileInp) {
    fileInp = document.createElement('input');
    fileInp.type = 'file';
    fileInp.id = 'chat-file-input';
    fileInp.style.display = 'none';
    fileInp.multiple = true;
    fileInp.onchange = handleChatFilesSelected;
    document.body.appendChild(fileInp);
  }
  fileInp.click();
}

async function handleChatFilesSelected(e) {
  const files = Array.from(e.target.files || []);
  for (const file of files) {
    try {
      const text = await readFileAsText(file);
      chatAttachedFiles.push({ name: file.name, content: text });
    } catch (err) {
      showMessage(`读取文件 ${file.name} 失败: ${err.message}`, true);
    }
  }
  e.target.value = ''; // Reset
  renderChatAttachedFiles();
}

function readFileAsText(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(reader.result);
    reader.onerror = () => reject(reader.error);
    reader.readAsText(file);
  });
}

function renderChatAttachedFiles() {
  const container = document.getElementById('chat-attached-files-container');
  if (!container) return;
  if (chatAttachedFiles.length === 0) {
    container.innerHTML = '';
    container.style.display = 'none';
    return;
  }
  container.style.display = 'flex';
  container.innerHTML = chatAttachedFiles.map((file, idx) => `
    <div class="chat-file-chip">
      <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"></path><polyline points="14 2 14 8 20 8"></polyline><line x1="16" y1="13" x2="8" y2="13"></line><line x1="16" y1="17" x2="8" y2="17"></line><polyline points="10 9 9 9 8 9"></polyline></svg>
      <span class="chat-file-chip-name">${escapeHtml(file.name)}</span>
      <button type="button" class="chat-file-chip-remove" onclick="removeChatAttachedFile(${idx})">&times;</button>
    </div>
  `).join('');
}

function removeChatAttachedFile(idx) {
  chatAttachedFiles.splice(idx, 1);
  renderChatAttachedFiles();
}

function openChatSkillModal() {
  const modal = document.getElementById('chat-skill-modal');
  if (modal) modal.style.display = 'flex';
}

function closeChatSkillModal() {
  const modal = document.getElementById('chat-skill-modal');
  if (modal) modal.style.display = 'none';
}

function applyChatSkill(key) {
  const skill = CHAT_SKILLS[key];
  if (!skill) return;
  const sp = document.getElementById('chat-system-prompt');
  if (sp) {
    sp.value = skill.prompt;
    sp.dispatchEvent(new Event('input'));
  }
  const settingsBar = document.getElementById('chat-settings-bar');
  const systemToggle = document.getElementById('chat-system-toggle');
  if (settingsBar && !isMediaMode()) {
    settingsBar.hidden = false;
    if (systemToggle) systemToggle.classList.add('active');
  }
  closeChatSkillModal();
  showMessage(`已应用 Skill: ${skill.name}`);
}

function triggerChatSkillFileLoad() {
  let skillInp = document.getElementById('chat-skill-file-input');
  if (!skillInp) {
    skillInp = document.createElement('input');
    skillInp.type = 'file';
    skillInp.id = 'chat-skill-file-input';
    skillInp.accept = '.md,.txt';
    skillInp.style.display = 'none';
    skillInp.onchange = handleChatSkillFileSelected;
    document.body.appendChild(skillInp);
  }
  skillInp.click();
}

async function handleChatSkillFileSelected(e) {
  const file = e.target.files?.[0];
  if (!file) return;
  try {
    const text = await readFileAsText(file);
    const sp = document.getElementById('chat-system-prompt');
    if (sp) {
      sp.value = text;
      sp.dispatchEvent(new Event('input'));
    }
    const settingsBar = document.getElementById('chat-settings-bar');
    const systemToggle = document.getElementById('chat-system-toggle');
    if (settingsBar && !isMediaMode()) {
      settingsBar.hidden = false;
      if (systemToggle) systemToggle.classList.add('active');
    }
    closeChatSkillModal();
    showMessage(`已加载自定义 Skill: ${file.name}`);
  } catch (err) {
    showMessage(`读取 Skill 文件失败: ${err.message}`, true);
  }
  e.target.value = ''; // Reset
}
