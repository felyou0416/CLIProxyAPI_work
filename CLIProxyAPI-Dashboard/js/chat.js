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
  resumeRunningMediaTasks();
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
  if (view?.mediaCard) {
    // Media gallery refreshes as a whole when draft/status changes.
    if (isMediaMode() && isSessionVisible(session)) {
      renderMediaWorkspace(session);
    }
  } else if (view?.contentDiv?.isConnected) {
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
  if (normalizeChatMode(session.mode) !== 'chat' && isMediaMode() && normalizeChatMode(session.mode) === chatMode) {
    renderMediaWorkspace(session);
    renderChatHistoryList();
    updateChatGeneratingState();
    updateChatSendState();
    return;
  }
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
  if (normalizeChatMode(session.mode) !== 'chat' && isMediaMode() && normalizeChatMode(session.mode) === chatMode) {
    renderMediaWorkspace(session);
    renderChatHistoryList();
    updateChatGeneratingState();
    updateChatSendState();
    return;
  }
  if (isSessionVisible(session)) {
    restoreChatSessionView(session);
    renderChatHistoryList();
  }
}

function updateChatGeneratingState() {
  // Media mode allows concurrent jobs; only block chat-mode when the active session is running.
  isGenerating = isMediaMode() ? false : isCurrentSessionRunning();
}

function countRunningModeJobs(mode = chatMode) {
  return getModeSessions(mode).filter(isSessionRunning).length;
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
  resumeRunningMediaTasks();
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

function isChatSessionsDrawerLayout() {
  return window.matchMedia('(max-width: 820px)').matches;
}

function isChatOptionsDrawerLayout() {
  return window.matchMedia('(max-width: 1100px)').matches;
}

// 兼容旧调用：会话抽屉断点
function isChatMobileLayout() {
  return isChatSessionsDrawerLayout();
}

function getChatLayoutEl() {
  return document.querySelector('#section-chat .chat-layout') || document.querySelector('.chat-layout');
}

function syncChatDrawerChrome() {
  const layout = getChatLayoutEl();
  const scrim = document.getElementById('chat-drawer-scrim');
  const sessionsToggle = document.getElementById('chat-sessions-toggle');
  const optionsToggle = document.getElementById('chat-options-toggle');
  const sessionsOpen = Boolean(layout?.classList.contains('chat-sessions-open'));
  const optionsOpen = Boolean(layout?.classList.contains('chat-options-open'));
  if (scrim) scrim.hidden = !(sessionsOpen || optionsOpen);
  if (sessionsToggle) {
    sessionsToggle.classList.toggle('active', sessionsOpen);
    sessionsToggle.setAttribute('aria-expanded', sessionsOpen ? 'true' : 'false');
  }
  if (optionsToggle) {
    optionsToggle.classList.toggle('active', optionsOpen);
    optionsToggle.setAttribute('aria-expanded', optionsOpen ? 'true' : 'false');
  }
}

function closeChatDrawers() {
  const layout = getChatLayoutEl();
  if (!layout) return;
  layout.classList.remove('chat-sessions-open', 'chat-options-open');
  closeChatSessionMenus();
  syncChatDrawerChrome();
}

function closeChatSessionMenus(exceptId) {
  document.querySelectorAll('.chat-session-menu-wrap.open').forEach((el) => {
    if (exceptId && el.dataset.sessionId === exceptId) return;
    el.classList.remove('open');
  });
}

function toggleChatSessionMenu(event, id) {
  event.stopPropagation();
  const wrap = event.currentTarget?.closest?.('.chat-session-menu-wrap');
  if (!wrap) return;
  const willOpen = !wrap.classList.contains('open');
  closeChatSessionMenus(willOpen ? id : null);
  wrap.classList.toggle('open', willOpen);
}

function toggleChatSessions() {
  if (!isChatSessionsDrawerLayout()) return;
  const layout = getChatLayoutEl();
  if (!layout) return;
  const next = !layout.classList.contains('chat-sessions-open');
  layout.classList.toggle('chat-sessions-open', next);
  if (next) layout.classList.remove('chat-options-open');
  closeChatSessionMenus();
  syncChatDrawerChrome();
}

function toggleChatOptions() {
  if (!isMediaMode()) return;
  const layout = getChatLayoutEl();
  const optionsSidebar = document.getElementById('chat-options-sidebar');
  if (!layout || !optionsSidebar || optionsSidebar.hidden) return;
  // 宽屏参数侧栏常驻，不必再开抽屉
  if (!isChatOptionsDrawerLayout()) return;
  const next = !layout.classList.contains('chat-options-open');
  layout.classList.toggle('chat-options-open', next);
  if (next) layout.classList.remove('chat-sessions-open');
  closeChatSessionMenus();
  syncChatDrawerChrome();
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
  const optionsToggle = document.getElementById('chat-options-toggle');
  if (optionsToggle) {
    optionsToggle.hidden = !isMediaMode();
    if (!isMediaMode()) optionsToggle.classList.remove('active');
  }
  // 切到非媒体模式时关掉参数抽屉；≤1100 默认收起，点按钮再开
  const layout = getChatLayoutEl();
  if (layout && (!isMediaMode() || !isChatOptionsDrawerLayout())) {
    layout.classList.remove('chat-options-open');
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
  if (isMediaMode()) {
    renderMediaWorkspace(getActiveSession());
  } else if (history) {
    history.classList.remove('media-history');
    if (history.querySelector('.chat-welcome') || history.querySelector('.media-workbench')) {
      const session = getActiveSession();
      if (session) restoreChatSessionView(session);
      else renderChatWelcome();
    }
  }
  renderChatHistoryList();
  updateChatSendState();
  syncChatDrawerChrome();
}

function toggleChatSystemPrompt() {
  if (isMediaMode()) return;
  closeChatDrawers();
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
  const looksUrl = (value) => {
    const text = String(value || '').trim().toLowerCase();
    return text.startsWith('http://') || text.startsWith('https://');
  };
  for (const path of [
    // Agnes completed videos expose the playable file here.
    'metadata.url',
    'metadata.video_url',
    'metadata.video.url',
    'video.url',
    'video_url',
    'url',
    'data.url',
    'data.metadata.url',
    'output.video.url',
    'output.url',
  ]) {
    const url = pick(root, path);
    if (looksUrl(url)) {
      return {
        url,
        id: pick(root, 'id') || pick(root, 'video_id') || pick(root, 'task_id') || '',
        status: String(root.status || '').trim(),
      };
    }
  }
  if (Array.isArray(root.data)) {
    for (const item of root.data) {
      const nested = extractVideoResultFromPayload(item);
      if (nested.url || nested.id) return nested;
    }
  }
  for (const path of ['video_id', 'request_id', 'task_id', 'id', 'data.id']) {
    const id = pick(root, path);
    if (id) return { url: '', id, status: String(root.status || '').trim() };
  }
  return { url: '', id: '', status: String(root.status || '').trim() };
}

function chatCompletionText(response) {
  return response?.choices?.[0]?.message?.content || '';
}

async function pollVideoResult(model, taskId, { attempts = 120, intervalMs = 3000 } = {}) {
  let lastError = null;
  let lastStatus = '';
  for (let i = 0; i < attempts; i += 1) {
    try {
      const retrieved = await chatFetchJson(
        `/v1/videos/${encodeURIComponent(taskId)}`,
        'GET'
      );
      const result = extractVideoResultFromPayload(retrieved);
      const status = String(result.status || retrieved?.status || '').toLowerCase();
      lastStatus = status || lastStatus;
      // Agnes puts the playable URL under metadata.url once status=completed.
      if (result.url) return { ...result, id: result.id || taskId, status: status || result.status || 'completed' };
      if (['failed', 'error', 'cancelled', 'canceled'].includes(status)) {
        throw new Error(retrieved?.error?.message || `Video task ${taskId} ${status || 'failed'}`);
      }
    } catch (err) {
      lastError = err;
    }
    await new Promise((resolve) => setTimeout(resolve, intervalMs));
  }
  if (lastError) throw lastError;
  return { url: '', id: taskId, status: lastStatus || 'timeout' };
}

const activeMediaPollingIds = new Set();

async function requestImageGenerationFallback(model, prompt, options = {}) {
  const imagePrompt = buildImagePrompt(prompt);
  let firstErr = null;
  try {
    const response = await chatFetchFirstJson(['/api/chat', '/v1/chat/completions'], 'POST', {
      model,
      messages: [{ role: 'user', content: imagePrompt }],
      max_tokens: 4096,
      stream: false,
      ...options
    });
    const reply = chatCompletionText(response);
    if (reply) return reply;
  } catch (err) {
    firstErr = err;
    console.warn('Primary image chat-completions path failed, trying /v1/images/generations fallback', err);
  }

  try {
    const directPayload = {
      model,
      prompt: imagePrompt,
      n: 1,
      size: options?.size || '1024x1024',
      response_format: 'url',
      ...options
    };
    const response = await chatFetchFirstJson(
      ['/v1/images/generations', '/api/image-generation'],
      'POST',
      directPayload
    );

    if (response?.data?.[0]?.url) {
      return `![image](${response.data[0].url})`;
    }
    if (response?.data?.[0]?.b64_json) {
      return `![image](data:image/png;base64,${response.data[0].b64_json})`;
    }
    const reply = chatCompletionText(response);
    if (reply) return reply;
  } catch (err) {
    throw firstErr || err;
  }
  throw firstErr || new Error('Image response did not include a valid URL or base64 image data.');
}

function resumeRunningMediaTasks() {
  if (!Array.isArray(chatSessions)) return;
  chatSessions.forEach((session) => {
    if (!session || session.status !== 'running' || !session.pendingRequestId) return;
    if (activeMediaPollingIds.has(session.pendingRequestId)) return;
    const mode = normalizeChatMode(session.pendingMode || session.mode);
    if (mode !== 'video' && mode !== 'image') return;
    activeMediaPollingIds.add(session.pendingRequestId);

    const requestId = session.pendingRequestId;
    const model = session.model || '';
    const lastUserMsg = (session.messages || []).filter(m => m.role === 'user').slice(-1)[0];
    const prompt = lastUserMsg ? lastUserMsg.content : '';

    (async () => {
      try {
        let reply = '';
        if (mode === 'video') {
          reply = await requestVideoGenerationFallback(model, prompt, getVideoOptions());
        } else {
          reply = await requestImageGenerationFallback(model, prompt, getImageOptions());
        }
        markSessionDraft(session, requestId, reply, true);
        finalizeSessionReply(session, requestId, reply);
      } catch (err) {
        console.warn('Resumed background media task failed:', err);
        markSessionFailed(session, requestId, err.message || 'Media task failed');
      } finally {
        activeMediaPollingIds.delete(requestId);
        if (isMediaMode() && normalizeChatMode(session.mode) === chatMode) {
          renderMediaWorkspace(getActiveSession());
        }
      }
    })();
  });
}

function looksLikeEgressFailure(err) {
  const msg = String(err?.message || '').toLowerCase();
  return /econnreset|econnaborted|eof|ssl|timeout|503|auth_unavailable|connect/i.test(msg);
}

function reportVideoEgressFailure(model, err) {
  if (!looksLikeEgressFailure(err)) return;
  try {
    fetch('/api/egress/report-failure', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ provider: 'agnes', base_url: 'https://apihub.agnes-ai.com/v1' }),
    }).catch(() => {});
  } catch {}
}

async function requestVideoGenerationFallback(model, prompt, options) {
  const directPayload = {
    model,
    prompt,
    stream: false,
    ...options
  };
  let lastErr = null;
  for (let attempt = 0; attempt < 2; attempt++) {
    try {
      const response = await chatFetchFirstJson(
        ['/api/video-generation', '/v1/videos', '/v1/videos/generations'],
        'POST',
        directPayload
      );
      const result = extractVideoResultFromPayload(response);
      if (result.url) return `[video](${result.url})`;
      if (result.id) {
        try {
          const polled = await pollVideoResult(model, result.id);
          if (polled.url) return `[video](${polled.url})`;
          if (polled.status && polled.status !== 'timeout') {
            return `Video generation task ${result.id} finished with status \`${polled.status}\`, but no playable URL was returned.`;
          }
        } catch (err) {
          console.warn('Video retrieve fallback failed', err);
          throw err;
        }
        return `Video generation task created: ${result.id}\n\nStill waiting for a playable URL under metadata.url (Agnes) / video.url (xAI).`;
      }
      throw new Error('Video response did not include a playable URL or task id.');
    } catch (err) {
      lastErr = err;
      if (attempt === 0 && looksLikeEgressFailure(err)) {
        reportVideoEgressFailure(model, err);
        continue; // retry once after marking egress as failed
      }
      throw err;
    }
  }
  throw lastErr || new Error('Video generation failed');
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
    title: isImageMode() ? 'New Image Task' : isVideoMode() ? 'New Video Task' : 'New Chat',
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
    closeChatDrawers();
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
  if (isMediaMode()) {
    renderMediaWorkspace(session);
    updateChatGeneratingState();
    updateChatSendState();
    return;
  }

  clearChatView();
  session.messages.forEach(m => {
    appendMessage(m.role, m.content, true);
    chatContext.push({ role: m.role, content: m.content });
  });
  if (session.systemPrompt) {
    chatContext.unshift({ role: 'system', content: session.systemPrompt });
  }
  renderPendingSessionState(session);
  updateChatGeneratingState();
  updateChatSendState();
}

function renderPendingSessionState(session) {
  if (!session || (!isSessionRunning(session) && session.status !== 'error')) return;
  if (isMediaMode()) {
    renderMediaWorkspace(session);
    return;
  }
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
    const running = countRunningModeJobs(chatMode);
    modeStatusEl.textContent = running
      ? `当前模式 ${modeSessions.length} ${unit} · ${running} 运行中`
      : `当前模式 ${modeSessions.length} ${unit}`;
  }

  if (modeSessions.length === 0) {
    const label = isImageMode() ? '图片任务' : isVideoMode() ? '视频任务' : '会话';
    container.innerHTML = `<div class="chat-session-empty">暂无${label}</div>`;
    return;
  }

  // 主行标题 · 次行模型/时间 · 操作收进 ⋯ 菜单
  container.innerHTML = modeSessions.map(s => {
    const active = s.id === activeSessionId ? 'active' : '';
    const timeStr = new Date(s.ts).toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' });
    const modelLabel = s.model ? escapeHtml(s.model).split('-').slice(0, 3).join('-') : 'No model';
    const running = isSessionRunning(s);
    return `<div class="chat-session-item ${active}" data-id="${s.id}" onclick="switchToSession('${s.id}'); closeChatDrawers()">
      <div class="chat-session-info">
        <div class="chat-session-title">${escapeHtml(s.title)}${running ? ' · …' : ''}</div>
        <div class="chat-session-meta">${modelLabel}${running ? ' · running' : ''} · ${timeStr}</div>
      </div>
      <div class="chat-session-menu-wrap" data-session-id="${s.id}">
        <button class="chat-icon-btn chat-session-more" type="button" title="更多" aria-label="更多" onclick="toggleChatSessionMenu(event, '${s.id}')">⋯</button>
        <div class="chat-session-menu" role="menu">
          <button type="button" role="menuitem" onclick="event.stopPropagation(); renameSession('${s.id}'); closeChatSessionMenus()">重命名</button>
          <button type="button" role="menuitem" class="danger" onclick="event.stopPropagation(); deleteSession('${s.id}'); closeChatSessionMenus()">删除</button>
        </div>
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
  if (isMediaMode()) {
    renderMediaWorkspace(getActiveSession());
    return;
  }
  const welcomeText = '选择模型，开始对话';
  const welcomeHint = 'Enter 发送 · Shift+Enter 换行';
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
  if (hist && !isMediaMode()) hist.classList.remove('media-history');
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
      session.title = isMediaMode()
        ? (isImageMode() ? 'New Image Task' : 'New Video Task')
        : 'New Chat';
      session.status = 'idle';
      clearSessionPending(session);
      session.ts = Date.now();
      saveChatSessions();
    }
  }
  chatContext = [];
  clearChatView();
  renderChatHistoryList();
}

function extractMediaAssets(content) {
  const text = String(content || '');
  const assets = [];
  const seen = new Set();

  const pushAsset = (url, kind) => {
    const value = String(url || '').trim();
    if (!value || seen.has(value)) return;
    seen.add(value);
    assets.push({ url: value, kind });
  };

  const mdImageRe = /!\[[^\]]*]\(([^)\s]+)(?:\s+"[^"]*")?\)/g;
  let match;
  while ((match = mdImageRe.exec(text)) !== null) {
    pushAsset(match[1], 'image');
  }

  const mdLinkRe = /\[([^\]]*)\]\(([^)\s]+)(?:\s+"[^"]*")?\)/g;
  while ((match = mdLinkRe.exec(text)) !== null) {
    const label = match[1] || '';
    const href = match[2] || '';
    if (looksLikeVideoUrl(href, label)) pushAsset(href, 'video');
    else if (looksLikeImageUrl(href, label)) pushAsset(href, 'image');
  }

  const bareUrlRe = /(https?:\/\/[^\s<>"']+|\/generated\/(?:images|videos)\/[^\s<>"')]+)/g;
  while ((match = bareUrlRe.exec(text)) !== null) {
    const href = match[1].replace(/[),.;]+$/, '');
    if (looksLikeVideoUrl(href)) pushAsset(href, 'video');
    else if (looksLikeImageUrl(href)) pushAsset(href, 'image');
  }

  // Prefer video assets in video mode, image assets in image mode, but keep mixed results.
  if (isVideoMode()) {
    assets.sort((a, b) => (a.kind === 'video' ? 0 : 1) - (b.kind === 'video' ? 0 : 1));
  } else if (isImageMode()) {
    assets.sort((a, b) => (a.kind === 'image' ? 0 : 1) - (b.kind === 'image' ? 0 : 1));
  }
  return assets;
}

function looksLikeImageUrl(href, label = '') {
  const raw = String(href || '').trim();
  if (!raw) return false;
  if (raw.startsWith('/generated/images/')) return true;
  if (raw.startsWith('data:image/')) return true;
  const lower = raw.toLowerCase();
  const pathOnly = lower.split('?')[0].split('#')[0];
  const labelText = String(label || '').trim().toLowerCase();
  if (/\.(png|jpe?g|webp|gif|bmp|svg)$/i.test(pathOnly)) return true;
  if (labelText === 'image' || labelText.includes('image') || labelText.includes('图片') || labelText.includes('图')) return true;
  if (/\/(images?|img|media|content|download)\b/i.test(pathOnly)) return true;
  return false;
}

function localDownloadUrl(url) {
  const value = String(url || '').trim();
  if (!value) return '';
  if (value.startsWith('/generated/')) {
    return value.includes('?') ? `${value}&download=1` : `${value}?download=1`;
  }
  // Videos stay remote; download streams on demand and does not materialize to disk.
  if (looksLikeVideoUrl(value)) return mediaProxyUrl(value, { mode: 'stream', download: true });
  return value;
}

// Shared disk-media cache so every browser/client can show the same local files.
let diskMediaCache = { image: null, video: null, fetchedAt: 0 };
const DISK_MEDIA_TTL_MS = 15_000;

async function fetchDiskMedia(kind, { force = false } = {}) {
  const key = kind === 'video' ? 'video' : 'image';
  const now = Date.now();
  if (!force && diskMediaCache[key] && (now - diskMediaCache.fetchedAt) < DISK_MEDIA_TTL_MS) {
    return diskMediaCache[key];
  }
  try {
    const response = await fetch(`/api/generated-media?kind=${encodeURIComponent(key)}&limit=200`, {
      credentials: 'same-origin',
    });
    if (!response.ok) throw new Error(`list failed (${response.status})`);
    const data = await response.json();
    const items = Array.isArray(data?.items) ? data.items : [];
    diskMediaCache[key] = items;
    diskMediaCache.fetchedAt = now;
    return items;
  } catch (err) {
    console.warn('Failed to list generated media', err);
    return diskMediaCache[key] || [];
  }
}

function mediaUrlKey(url) {
  const value = String(url || '').trim();
  if (!value) return '';
  try {
    // Normalize /generated/... paths and strip query/hash.
    if (value.startsWith('/generated/')) {
      return value.split('?')[0].split('#')[0];
    }
    const parsed = new URL(value, window.location.origin);
    if (parsed.pathname.startsWith('/generated/')) return parsed.pathname;
    return parsed.href;
  } catch {
    return value.split('?')[0].split('#')[0];
  }
}

function mediaPlayUrl(url, kind) {
  const value = String(url || '').trim();
  if (!value) return '';
  if (isLocalMediaUrl(value)) return value;
  // Remote videos are link-only by default; do not auto-proxy/stream into the gallery.
  if (kind === 'video' || looksLikeVideoUrl(value)) return value;
  return value;
}

async function revealLocalMedia(pathOrUrl, button) {
  const value = String(pathOrUrl || '').trim();
  if (!value) return;
  // Videos are not auto-cached; only reveal paths that already live under /generated/.
  if (!value.startsWith('/generated/') && looksLikeVideoUrl(value)) {
    const msg = '视频仅保存远程链接，未自动下载到本地。请先点「下载视频」。';
    if (typeof showMessage === 'function') showMessage(msg, true);
    else alert(msg);
    return;
  }
  const original = button?.textContent;
  if (button) {
    button.textContent = '定位中…';
    button.setAttribute('aria-busy', 'true');
  }
  try {
    const data = await fetch('/api/reveal-path', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'same-origin',
      body: JSON.stringify({ path: value, url: value }),
    }).then(r => r.json());
    if (!data?.ok) throw new Error(data?.message || '打开本地目录失败');
  } catch (err) {
    console.warn('Reveal media failed', err);
    if (typeof showMessage === 'function') showMessage(err.message || '打开本地目录失败', true);
    else alert(err.message || '打开本地目录失败');
  } finally {
    if (button) {
      button.textContent = original || '打开本地';
      button.removeAttribute('aria-busy');
    }
  }
}

function buildMediaCard({ kind, url, prompt, model, status, error, requestId, jobId }) {
  const card = document.createElement('article');
  const isVideo = kind === 'video' || looksLikeVideoUrl(url);
  card.className = `media-card media-card-${kind || 'image'}${status === 'running' ? ' is-running' : ''}${status === 'error' ? ' is-error' : ''}${isVideo ? ' is-link-only' : ''}`;
  if (requestId) card.dataset.requestId = requestId;
  if (jobId) card.dataset.jobId = jobId;

  const mediaWrap = document.createElement('div');
  mediaWrap.className = 'media-card-preview';

  if (status === 'running') {
    mediaWrap.innerHTML = `<div class="media-card-loading"><div class="typing-indicator"><span></span><span></span><span></span></div><div>生成中…</div></div>`;
  } else if (status === 'error') {
    mediaWrap.innerHTML = `<div class="media-card-error">${escapeHtml(error || '生成失败')}</div>`;
  } else if (url && isVideo) {
    // Link-only video result: no auto-download / no auto-proxy stream.
    const local = url.startsWith('/generated/');
    mediaWrap.innerHTML = `
      <div class="media-card-link-panel">
        <div class="media-card-link-icon" aria-hidden="true">
          <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><polygon points="5 3 19 12 5 21 5 3"></polygon></svg>
        </div>
        <div class="media-card-link-title">视频链接已保存</div>
        <div class="media-card-link-note">${local ? '本地文件' : '未自动下载 · 点下方按钮获取'}</div>
        <div class="media-card-link-url" title="${escapeHtml(url)}">${escapeHtml(url)}</div>
      </div>
    `;
  } else if (url) {
    const img = document.createElement('img');
    img.className = 'media-card-media';
    img.src = mediaPlayUrl(url, 'image');
    img.alt = prompt || 'generated image';
    img.loading = 'lazy';
    mediaWrap.appendChild(img);
  } else {
    mediaWrap.innerHTML = `<div class="media-card-empty">暂无媒体结果</div>`;
  }

  const body = document.createElement('div');
  body.className = 'media-card-body';

  const promptEl = document.createElement('div');
  promptEl.className = 'media-card-prompt';
  promptEl.textContent = prompt || '（无提示词）';
  body.appendChild(promptEl);

  const meta = document.createElement('div');
  meta.className = 'media-card-meta';
  const bits = [];
  if (model) bits.push(model);
  if (status === 'running') bits.push('运行中');
  if (status === 'error') bits.push('失败');
  if (kind) bits.push(kind === 'video' ? '视频' : '图片');
  if (isVideo && url && !url.startsWith('/generated/')) bits.push('仅链接');
  meta.textContent = bits.join(' · ');
  body.appendChild(meta);

  if (isVideo && url && status !== 'running' && status !== 'error') {
    const note = document.createElement('div');
    note.className = 'media-card-note';
    note.textContent = '结果只记录远程链接与提示词，不会自动缓存到本机；需要时再下载。';
    body.appendChild(note);
  }

  const actions = document.createElement('div');
  actions.className = 'media-card-actions';

  if (url && status !== 'running') {
    const downloadBtn = document.createElement('a');
    downloadBtn.className = 'chat-video-action primary';
    downloadBtn.href = localDownloadUrl(url);
    downloadBtn.download = '';
    downloadBtn.textContent = isVideo ? '下载视频' : '下载图片';
    downloadBtn.addEventListener('click', async (event) => {
      if (isLocalMediaUrl(url) && url.startsWith('/generated/')) return;
      event.preventDefault();
      const original = downloadBtn.textContent;
      downloadBtn.textContent = '下载中…';
      downloadBtn.setAttribute('aria-busy', 'true');
      try {
        const response = await fetch(localDownloadUrl(url), { credentials: 'same-origin' });
        if (!response.ok) throw new Error(`Download failed (${response.status})`);
        const blob = await response.blob();
        const objectUrl = URL.createObjectURL(blob);
        const temp = document.createElement('a');
        const ctype = response.headers.get('Content-Type') || '';
        const ext = isVideo
          ? (ctype.includes('webm') ? '.webm' : '.mp4')
          : (ctype.includes('jpeg') || ctype.includes('jpg') ? '.jpg' : ctype.includes('webp') ? '.webp' : '.png');
        temp.href = objectUrl;
        temp.download = `generated-${isVideo ? 'video' : 'image'}-${Date.now()}${ext}`;
        document.body.appendChild(temp);
        temp.click();
        temp.remove();
        setTimeout(() => URL.revokeObjectURL(objectUrl), 30_000);
      } catch (err) {
        console.warn('Media download failed', err);
        window.open(url, '_blank', 'noopener,noreferrer');
      } finally {
        downloadBtn.textContent = original;
        downloadBtn.removeAttribute('aria-busy');
      }
    });
    actions.appendChild(downloadBtn);

    // Local reveal only for files already under /generated/.
    if (url.startsWith('/generated/')) {
      const revealBtn = document.createElement('button');
      revealBtn.type = 'button';
      revealBtn.className = 'chat-video-action';
      revealBtn.textContent = '打开本地';
      revealBtn.addEventListener('click', () => revealLocalMedia(url, revealBtn));
      actions.appendChild(revealBtn);
    }

    const openBtn = document.createElement('a');
    openBtn.className = 'chat-video-action';
    openBtn.href = url;
    openBtn.target = '_blank';
    openBtn.rel = 'noopener noreferrer';
    openBtn.textContent = isVideo ? '打开链接' : '原链';
    actions.appendChild(openBtn);
  }

  body.appendChild(actions);
  card.appendChild(mediaWrap);
  card.appendChild(body);
  return card;
}

function collectMediaJobs(session) {
  const jobs = [];
  const messages = Array.isArray(session?.messages) ? session.messages : [];
  const running = isSessionRunning(session);
  const errored = session?.status === 'error';
  let lastUserIndex = -1;
  for (let i = 0; i < messages.length; i += 1) {
    if (messages[i].role === 'user') lastUserIndex = i;
  }

  for (let i = 0; i < messages.length; i += 1) {
    const msg = messages[i];
    if (msg.role !== 'user') continue;
    const prompt = String(msg.content || '').trim();
    const next = messages[i + 1];
    // Running/error already represent the latest unanswered user turn.
    if ((running || errored) && i === lastUserIndex && !(next && next.role === 'assistant')) {
      continue;
    }
    if (next && next.role === 'assistant') {
      const assets = extractMediaAssets(next.content);
      if (assets.length) {
        assets.forEach((asset, idx) => {
          jobs.push({
            id: `${session.id}_${i}_${idx}`,
            prompt,
            model: session.model || '',
            status: 'done',
            kind: asset.kind,
            url: asset.url,
            content: next.content,
          });
        });
      } else {
        jobs.push({
          id: `${session.id}_${i}_text`,
          prompt,
          model: session.model || '',
          status: 'done',
          kind: isVideoMode() ? 'video' : 'image',
          url: '',
          content: next.content,
          note: next.content,
        });
      }
    }
  }

  if (running) {
    jobs.unshift({
      id: session.pendingRequestId || `${session.id}_running`,
      prompt: session.messages?.filter(m => m.role === 'user').slice(-1)[0]?.content || session.title || '',
      model: session.model || '',
      status: 'running',
      kind: isVideoMode() ? 'video' : 'image',
      url: '',
      requestId: session.pendingRequestId || '',
      draft: session.pendingDraftText || '',
    });
  } else if (errored) {
    jobs.unshift({
      id: `${session.id}_error`,
      prompt: session.messages?.filter(m => m.role === 'user').slice(-1)[0]?.content || session.title || '',
      model: session.model || '',
      status: 'error',
      kind: isVideoMode() ? 'video' : 'image',
      url: '',
      error: session.pendingError || 'Request failed',
    });
  }

  return jobs;
}

function paintMediaWorkspace(history, focusSession, diskItems = []) {
  const modeSessions = getModeSessions(chatMode);
  const runningCount = countRunningModeJobs(chatMode);
  const kindLabel = isVideoMode() ? '视频' : '图片';
  const expectedKind = isVideoMode() ? 'video' : 'image';

  history.innerHTML = '';
  history.classList.add('media-history');

  const shell = document.createElement('div');
  shell.className = 'media-workbench';

  const allJobs = [];
  modeSessions.forEach((session) => {
    collectMediaJobs(session).forEach((job) => {
      allJobs.push({ ...job, sessionId: session.id, sessionTitle: session.title, sessionTs: session.ts, source: 'session' });
    });
  });

  // Images: merge disk files shared across browsers/clients.
  // Videos: link-only — do not surface auto-cached local video files.
  if (expectedKind === 'image') {
    const seenUrls = new Set();
    allJobs.forEach((job) => {
      const key = mediaUrlKey(job.url);
      if (key) seenUrls.add(key);
    });
    (Array.isArray(diskItems) ? diskItems : []).forEach((item) => {
      if (!item || item.kind !== 'image') return;
      const url = String(item.url || '').trim();
      const key = mediaUrlKey(url);
      if (!url || !key || seenUrls.has(key)) return;
      seenUrls.add(key);
      allJobs.push({
        id: `disk_${item.filename || key}`,
        prompt: item.filename || '本地文件',
        model: '',
        status: 'done',
        kind: 'image',
        url,
        sessionId: '',
        sessionTitle: '',
        sessionTs: Number(item.mtime || 0) * 1000,
        source: 'disk',
        bytes: item.bytes || 0,
      });
    });
  }

  // Prefer focused session, then running, then recency.
  allJobs.sort((a, b) => {
    const aFocus = focusSession && a.sessionId === focusSession.id ? 1 : 0;
    const bFocus = focusSession && b.sessionId === focusSession.id ? 1 : 0;
    if (aFocus !== bFocus) return bFocus - aFocus;
    const aRun = a.status === 'running' ? 1 : 0;
    const bRun = b.status === 'running' ? 1 : 0;
    if (aRun !== bRun) return bRun - aRun;
    return Number(b.sessionTs || 0) - Number(a.sessionTs || 0);
  });

  const header = document.createElement('div');
  header.className = 'media-workbench-head';
  const diskCount = allJobs.filter((job) => job.source === 'disk').length;
  const totalDone = allJobs.filter((job) => job.status === 'done' && job.url).length;
  const subtitle = expectedKind === 'video'
    ? `${modeSessions.length} 个任务${runningCount ? ` · ${runningCount} 运行中` : ''} · ${totalDone} 条链接 · 仅保存远程链/说明，不自动下载`
    : `${modeSessions.length} 个任务${runningCount ? ` · ${runningCount} 运行中` : ''} · ${totalDone} 项本地结果${diskCount ? `（含 ${diskCount} 共享文件）` : ''} · 可并发生成`;
  header.innerHTML = `
    <div class="media-workbench-title">
      <strong>${kindLabel}工作台</strong>
      <span>${subtitle}</span>
    </div>
    <div class="media-workbench-actions">
      <button type="button" class="chat-video-action" onclick="createNewSession()">新建任务</button>
      ${expectedKind === 'image'
        ? `<button type="button" class="chat-video-action" onclick="revealLocalMedia('/generated/images/', this)">打开保存目录</button>`
        : ''}
    </div>
  `;
  shell.appendChild(header);

  if (!allJobs.length) {
    const empty = document.createElement('div');
    empty.className = 'media-workbench-empty';
    empty.innerHTML = `
      <div class="chat-welcome-icon">
        <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="3" width="18" height="18" rx="2"></rect><circle cx="8.5" cy="8.5" r="1.5"></circle><path d="M21 15l-5-5L5 21"></path></svg>
      </div>
      <div class="chat-welcome-text">描述你想生成的${kindLabel}</div>
      <div class="chat-welcome-hint">${expectedKind === 'video'
        ? 'Enter 生成 · 多任务并发 · 结果只记链接与提示词 · 需要时再下载'
        : 'Enter 生成 · 支持多任务并发 · 结果可下载/打开本地目录 · 各浏览器共享本地文件'}</div>
    `;
    shell.appendChild(empty);
  } else {
    const cards = document.createElement('div');
    cards.className = 'media-gallery';
    allJobs.forEach((job) => {
      const card = buildMediaCard({
        kind: job.kind,
        url: job.url,
        prompt: job.prompt,
        model: job.model || (job.source === 'disk' ? '本地文件' : ''),
        status: job.status,
        error: job.error || job.note || '',
        requestId: job.requestId || '',
        jobId: job.id,
      });
      if (job.source === 'disk') card.classList.add('is-disk');
      if (job.status === 'running' && job.requestId) {
        chatRequestViews[job.requestId] = {
          history,
          msgDiv: card,
          contentDiv: card.querySelector('.media-card-preview') || card,
          mediaCard: true,
        };
      }
      card.addEventListener('click', (event) => {
        if (event.target.closest('a,button,video,img')) return;
        if (job.sessionId && job.sessionId !== activeSessionId) switchToSession(job.sessionId);
      });
      cards.appendChild(card);
    });
    shell.appendChild(cards);
  }

  history.appendChild(shell);
}

function renderMediaWorkspace(focusSession = null) {
  const history = document.getElementById('chat-history');
  if (!history) return;

  const kind = isVideoMode() ? 'video' : 'image';
  // Videos are link-only (no disk gallery). Images merge shared local files.
  paintMediaWorkspace(history, focusSession, kind === 'image' ? (diskMediaCache.image || []) : []);
  requestAnimationFrame(() => history.scrollTo({ top: 0, behavior: 'smooth' }));

  if (kind !== 'image') return;
  fetchDiskMedia('image').then((items) => {
    if (document.getElementById('chat-history') !== history) return;
    if (!isMediaMode() || isVideoMode()) return;
    paintMediaWorkspace(history, focusSession, items);
  });
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

function looksLikeVideoUrl(href, label = '') {
  const raw = String(href || '').trim();
  if (!raw) return false;
  if (raw.startsWith('/generated/videos/')) return true;
  if (raw.startsWith('/api/media-proxy')) return true;
  const lower = raw.toLowerCase();
  const pathOnly = lower.split('?')[0].split('#')[0];
  const labelText = String(label || '').trim().toLowerCase();
  if (pathOnly.endsWith('.mp4') || pathOnly.endsWith('.webm') || pathOnly.endsWith('.mov') || pathOnly.endsWith('.m4v') || pathOnly.endsWith('.mkv')) {
    return true;
  }
  if (labelText === 'video' || labelText.includes('video') || labelText.includes('视频')) return true;
  // Agnes / CDN links often omit a file extension.
  if (/\/(videos?|media|stream|content|download)\b/i.test(pathOnly)) return true;
  if (/\b(video|mp4|webm)\b/i.test(lower)) return true;
  return false;
}

function mediaProxyUrl(remoteUrl, { download = false, mode = 'stream' } = {}) {
  const params = new URLSearchParams();
  params.set('url', remoteUrl);
  if (mode && mode !== 'stream') params.set('mode', mode);
  if (download) params.set('download', '1');
  return `/api/media-proxy?${params.toString()}`;
}

function isLocalMediaUrl(url) {
  const value = String(url || '').trim();
  return value.startsWith('/generated/') || value.startsWith('/api/media-proxy');
}

function decorateMediaEmbeds(contentDiv) {
  // Promote markdown images into downloadable cards.
  contentDiv.querySelectorAll('img[src]').forEach(img => {
    if (img.closest('.chat-image-card, .media-card, .chat-video-card')) return;
    const src = img.getAttribute('src') || '';
    if (!src || src.startsWith('data:')) return;
    const card = document.createElement('div');
    card.className = 'chat-image-card';
    const preview = img.cloneNode(true);
    preview.className = 'chat-generated-image';
    preview.loading = 'lazy';
    const actions = document.createElement('div');
    actions.className = 'chat-video-actions';
    const downloadBtn = document.createElement('a');
    downloadBtn.className = 'chat-video-action primary';
    downloadBtn.href = localDownloadUrl(src);
    downloadBtn.download = '';
    downloadBtn.textContent = '下载图片';
    const revealBtn = document.createElement('button');
    revealBtn.type = 'button';
    revealBtn.className = 'chat-video-action';
    revealBtn.textContent = '打开本地';
    revealBtn.addEventListener('click', () => revealLocalMedia(src, revealBtn));
    actions.appendChild(downloadBtn);
    if (isLocalMediaUrl(src) || src.startsWith('/generated/')) actions.appendChild(revealBtn);
    card.appendChild(preview);
    card.appendChild(actions);
    img.replaceWith(card);
  });

  contentDiv.querySelectorAll('a[href]').forEach(link => {
    if (link.closest('.chat-video-card, .chat-image-card, .media-card')) return;
    const href = link.getAttribute('href') || '';
    const label = (link.textContent || '').trim();
    if (!looksLikeVideoUrl(href, label)) return;

    const remoteUrl = href;
    const isLocal = remoteUrl.startsWith('/generated/');
    const downloadUrl = localDownloadUrl(remoteUrl);

    const card = document.createElement('div');
    card.className = 'chat-video-card is-link-only';
    card.dataset.remoteUrl = remoteUrl;

    // Link-only panel: keep the remote URL + actions, do not auto-stream/cache video bytes.
    const panel = document.createElement('div');
    panel.className = 'chat-video-link-panel';
    panel.innerHTML = `
      <div class="chat-video-link-title">视频链接已保存</div>
      <div class="chat-video-link-note">${isLocal ? '本地文件' : '未自动下载 · 需要时再下载'}</div>
      <div class="chat-video-link-url" title="${escapeHtml(remoteUrl)}">${escapeHtml(remoteUrl)}</div>
    `;

    const actions = document.createElement('div');
    actions.className = 'chat-video-actions';

    const openBtn = document.createElement('a');
    openBtn.className = 'chat-video-action';
    openBtn.href = remoteUrl;
    openBtn.target = '_blank';
    openBtn.rel = 'noopener noreferrer';
    openBtn.textContent = '打开链接';

    const downloadBtn = document.createElement('a');
    downloadBtn.className = 'chat-video-action primary';
    downloadBtn.href = downloadUrl;
    downloadBtn.download = '';
    downloadBtn.textContent = '下载视频';
    downloadBtn.addEventListener('click', async (event) => {
      if (isLocal) return;
      event.preventDefault();
      const original = downloadBtn.textContent;
      downloadBtn.textContent = '下载中…';
      downloadBtn.setAttribute('aria-busy', 'true');
      try {
        // Stream-only proxy: never materialize into /generated/videos.
        const response = await fetch(mediaProxyUrl(remoteUrl, { mode: 'stream', download: true }), {
          credentials: 'same-origin',
        });
        if (!response.ok) {
          const text = await response.text();
          throw new Error(text || `Download failed (${response.status})`);
        }
        const blob = await response.blob();
        const objectUrl = URL.createObjectURL(blob);
        const temp = document.createElement('a');
        const extMatch = (response.headers.get('Content-Type') || '').includes('webm') ? '.webm' : '.mp4';
        temp.href = objectUrl;
        temp.download = `generated-video-${Date.now()}${extMatch}`;
        document.body.appendChild(temp);
        temp.click();
        temp.remove();
        setTimeout(() => URL.revokeObjectURL(objectUrl), 30_000);
      } catch (err) {
        console.warn('Video download via proxy failed, falling back to direct link.', err);
        window.open(remoteUrl, '_blank', 'noopener,noreferrer');
      } finally {
        downloadBtn.textContent = original;
        downloadBtn.removeAttribute('aria-busy');
      }
    });

    actions.appendChild(downloadBtn);
    if (isLocal) {
      const revealBtn = document.createElement('button');
      revealBtn.type = 'button';
      revealBtn.className = 'chat-video-action';
      revealBtn.textContent = '打开本地';
      revealBtn.addEventListener('click', () => revealLocalMedia(remoteUrl, revealBtn));
      actions.appendChild(revealBtn);
    }
    actions.appendChild(openBtn);

    const caption = document.createElement('div');
    caption.className = 'chat-video-caption';
    caption.textContent = '生成视频 · 仅保存链接，不自动下载';

    card.appendChild(panel);
    card.appendChild(caption);
    card.appendChild(actions);

    // If the proxy stream fails (CORS-free path still bad), fall back to the remote URL.
    video.addEventListener('error', () => {
      if (video.dataset.fallbackApplied === '1') return;
      video.dataset.fallbackApplied = '1';
      if (video.src !== remoteUrl) video.src = remoteUrl;
    }, { once: true });

    link.replaceWith(card);
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

  if (!window.__chatMobileChromeBound) {
    window.__chatMobileChromeBound = true;
    document.addEventListener('keydown', (event) => {
      if (event.key !== 'Escape') return;
      const openMenu = document.querySelector('.chat-session-menu-wrap.open');
      if (openMenu) {
        closeChatSessionMenus();
        return;
      }
      const layout = getChatLayoutEl();
      if (!layout) return;
      if (layout.classList.contains('chat-sessions-open') || layout.classList.contains('chat-options-open')) {
        closeChatDrawers();
      }
    });
    document.addEventListener('click', (event) => {
      if (event.target?.closest?.('.chat-session-menu-wrap')) return;
      closeChatSessionMenus();
    });
    const onDrawerBpChange = () => {
      const layout = getChatLayoutEl();
      if (!layout) return;
      if (!isChatSessionsDrawerLayout()) layout.classList.remove('chat-sessions-open');
      if (!isChatOptionsDrawerLayout()) layout.classList.remove('chat-options-open');
      syncChatDrawerChrome();
    };
    window.matchMedia('(max-width: 820px)').addEventListener('change', onDrawerBpChange);
    window.matchMedia('(max-width: 1100px)').addEventListener('change', onDrawerBpChange);
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

  // Media: each generation is its own concurrent job/session so send is never blocked.
  let session = getActiveSession();
  if (requestIsMedia) {
    if (!session || isSessionRunning(session) || (session.messages || []).length > 0 || normalizeChatMode(session.mode) !== requestMode) {
      session = createNewSession(true);
    }
  } else if (!session) {
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

  if (!requestIsMedia) {
    appendMessage('user', fullContentToSend);
  }

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
  if (requestIsMedia) {
    renderMediaWorkspace(session);
  } else {
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
      if (requestIsImage) {
        reply = await requestImageGenerationFallback(model, content, getImageOptions());
      } else {
        let mediaError = null;
        try {
          const response = await chatFetchFirstJson(['/api/chat', '/v1/chat/completions'], 'POST', payload);
          reply = chatCompletionText(response);
          if (!reply) {
            throw new Error(response.error?.message || response.message || 'Invalid response format');
          }
        } catch (err) {
          mediaError = err;
          reply = await requestVideoGenerationFallback(model, content, videoOptions || {});
        }
        if (mediaError) {
          console.warn('Primary media chat-completions path failed; video fallback succeeded.', mediaError);
        }
      }
      markSessionDraft(session, requestId, reply, true);
      finalizeSessionReply(session, requestId, reply);
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
    if (requestIsMedia && chatMode === requestMode) {
      renderMediaWorkspace(getActiveSession());
    }
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
