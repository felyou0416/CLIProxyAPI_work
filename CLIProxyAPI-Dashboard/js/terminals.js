let terminalPanelLoaded = false;
let terminalItems = [];
let activeTerminalId = '';
let terminalOutputOffset = 0;
let terminalOutputBuffers = {};
let terminalOutputOffsets = {};
let terminalPoller = null;
let terminalPollInFlight = false;
let terminalPollSeq = 0;
let terminalWriteQueue = '';
let terminalWriteScheduled = false;
let terminalResizeTimer = null;
let term = null;
let fitAddon = null;
const TERMINAL_BUFFER_LIMIT = 160000;

function terminalEscape(value) {
  return String(value ?? '')
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#39;');
}

function terminalKindLabel(kind) {
  return String(kind || '').toLowerCase() === 'cmd' ? 'CMD' : 'PowerShell';
}

function setTerminalText(id, text) {
  const el = document.getElementById(id);
  if (el) el.textContent = text;
}

function activeTerminal() {
  return terminalItems.find(item => item.id === activeTerminalId) || null;
}

function isTerminalVisible() {
  const el = document.getElementById('section-terminals');
  return el && !el.hidden && el.classList.contains('active-view');
}

async function resizeActiveTerminal() {
  if (!activeTerminalId || !term || !isTerminalVisible()) return;
  fitActiveTerminal();
  try {
    await api('/api/terminals/resize', 'POST', { id: activeTerminalId, rows: term.rows, cols: term.cols });
  } catch (error) {
    // Ignore resize error
  }
}

function renderTerminalTabs() {
  const root = document.getElementById('terminal-tabs');
  if (!root) return;
  if (!terminalItems.length) {
    root.innerHTML = '<span class="terminal-empty-tab">暂无终端</span>';
    return;
  }
  root.innerHTML = terminalItems.map(item => {
    const label = terminalKindLabel(item.kind);
    return `
      <button type="button" class="terminal-tab ${item.id === activeTerminalId ? 'is-active' : ''}" onclick="selectTerminalPanel('${terminalEscape(item.id)}')">
        <span class="terminal-tab-icon">›_</span>
        <span>${terminalEscape(label)}</span>
        <small>${item.pty ? 'PTY' : 'PIPE'} ${terminalEscape(item.pid || '-')}</small>
      </button>
    `;
  }).join('');
}

function trimTerminalReplayBuffer(text) {
  const value = String(text || '');
  if (value.length <= TERMINAL_BUFFER_LIMIT) return value;
  const cut = value.length - TERMINAL_BUFFER_LIMIT;
  const newline = value.indexOf('\n', cut);
  if (newline >= 0 && newline - cut < 4000) return value.slice(newline + 1);
  return value.slice(cut);
}

function appendTerminalBuffer(id, text) {
  if (!id || !text) return terminalOutputBuffers[id] || '';
  terminalOutputBuffers[id] = trimTerminalReplayBuffer(`${terminalOutputBuffers[id] || ''}${text}`);
  return terminalOutputBuffers[id];
}

function queueTerminalWrite(text) {
  if (!term || !text) return;
  terminalWriteQueue += text;
  if (terminalWriteScheduled) return;
  terminalWriteScheduled = true;
  requestAnimationFrame(() => {
    const chunk = terminalWriteQueue;
    terminalWriteQueue = '';
    terminalWriteScheduled = false;
    if (chunk && term) term.write(chunk);
  });
}

function clearTerminalWriteQueue() {
  terminalWriteQueue = '';
  terminalWriteScheduled = false;
}

function resetTerminalWithReplay(text = '') {
  if (!term) return;
  clearTerminalWriteQueue();
  term.reset();
  if (text) queueTerminalWrite(text);
}

function fitActiveTerminal() {
  if (!term || !fitAddon || !isTerminalVisible()) return false;
  try {
    fitAddon.fit();
    return true;
  } catch {
    return false;
  }
}

function scheduleTerminalResize(delay = 0) {
  if (terminalResizeTimer) clearTimeout(terminalResizeTimer);
  terminalResizeTimer = setTimeout(() => {
    terminalResizeTimer = null;
    requestAnimationFrame(() => { void resizeActiveTerminal(); });
  }, delay);
}

function focusTerminal() {
  if (term) term.focus();
}

function renderTerminalState() {
  renderTerminalTabs();
  const item = activeTerminal();
  const shellLabel = item ? terminalKindLabel(item.kind) : '-';
  setTerminalText('terminal-active-status', item ? (item.pty ? '交互 PTY' : '兼容管道') : '未连接');
  setTerminalText('terminal-shell-label', `Shell: ${shellLabel}`);
  setTerminalText('terminal-pid-label', `PID: ${item?.pid || '-'}`);
  setTerminalText('terminal-cwd-label', item?.cwd || document.getElementById('terminal-cwd-input')?.value || '-');
  if (!item && term) {
    resetTerminalWithReplay('正在准备交互终端...');
  }
}

function stopTerminalPolling() {
  if (terminalPoller) {
    clearInterval(terminalPoller);
    terminalPoller = null;
  }
  terminalPollSeq += 1;
  terminalPollInFlight = false;
}

async function pollTerminalOutput() {
  if (!activeTerminalId || terminalPollInFlight) return;
  const id = activeTerminalId;
  const seq = ++terminalPollSeq;
  terminalPollInFlight = true;
  try {
    const offset = terminalOutputOffsets[id] ?? terminalOutputOffset;
    const data = await api(`/api/terminals/output?id=${encodeURIComponent(id)}&offset=${offset}`);
    if (id !== activeTerminalId || seq !== terminalPollSeq) return;
    terminalOutputOffset = Number(data.offset || terminalOutputOffset || 0);
    terminalOutputOffsets[id] = terminalOutputOffset;

    if (data.output) {
      appendTerminalBuffer(id, data.output);
      if (id === activeTerminalId) {
        queueTerminalWrite(data.output);
      }
    }

    const item = activeTerminal();
    if (item) item.pty = Boolean(data.pty);

    if (!data.running) {
      terminalItems = terminalItems.filter(item => item.id !== id);
      delete terminalOutputBuffers[id];
      delete terminalOutputOffsets[id];
      activeTerminalId = terminalItems[0]?.id || '';
      terminalOutputOffset = terminalOutputOffsets[activeTerminalId] || 0;
      stopTerminalPolling();
      renderTerminalState();
      if (activeTerminalId) {
        resetTerminalWithReplay(terminalOutputBuffers[activeTerminalId] || '');
        startTerminalPolling();
      }
    }
  } catch (error) {
    if (id === activeTerminalId) {
      stopTerminalPolling();
      queueTerminalWrite(`\r\n[读取终端失败: ${error.message || error}]\r\n`);
    }
  } finally {
    if (seq === terminalPollSeq) terminalPollInFlight = false;
  }
}

function startTerminalPolling() {
  stopTerminalPolling();
  terminalPoller = setInterval(pollTerminalOutput, 120);
  void pollTerminalOutput();
}

async function selectTerminalPanel(id) {
  if (!id || id === activeTerminalId) return;
  activeTerminalId = id;
  terminalOutputOffset = terminalOutputOffsets[id] || 0;
  if (term) {
    resetTerminalWithReplay(terminalOutputBuffers[id] || '');
  }
  renderTerminalState();
  startTerminalPolling();
  focusTerminal();
  scheduleTerminalResize();
}

function initXterm() {
  const container = document.getElementById('terminal-output');
  if (!container) return;
  container.innerHTML = '';
  
  term = new Terminal({
    cursorBlink: true,
    theme: {
      background: '#1e1e1e',
      foreground: '#cccccc',
      cursor: '#ffffff',
      selectionBackground: '#264f78',
      black: '#000000',
      red: '#cd3131',
      green: '#0dbc79',
      yellow: '#e5e510',
      blue: '#2472c8',
      magenta: '#bc3fbc',
      cyan: '#11a8cd',
      white: '#e5e5e5',
      brightBlack: '#666666',
      brightRed: '#f14c4c',
      brightGreen: '#23d18b',
      brightYellow: '#f5f543',
      brightBlue: '#3b8eea',
      brightMagenta: '#d670d6',
      brightCyan: '#29b8db',
      brightWhite: '#e5e5e5',
    },
    fontSize: 13,
    fontFamily: 'Consolas, "Cascadia Mono", "Courier New", monospace',
    convertEol: true,
    scrollback: 5000,
  });

  if (window.FitAddon?.FitAddon) {
    fitAddon = new FitAddon.FitAddon();
    term.loadAddon(fitAddon);
  }

  term.open(container);
  scheduleTerminalResize();
  
  term.onData(data => {
    void writeTerminalRaw(data);
  });
}

async function loadTerminalPanel(force = false) {
  if (terminalPanelLoaded && !force) {
    focusTerminal();
    return;
  }
  
  if (!term) {
    initXterm();
  }
  
  loadTerminalPresets();
  renderTerminalPresets();
  renderTerminalCwdHistory();
  
  try {
    const data = await api('/api/terminals');
    terminalItems = Array.isArray(data.items) ? data.items : [];
    if (!terminalItems.length) {
      terminalPanelLoaded = true;
      await openTerminalPanel('powershell');
      return;
    }
    if (!activeTerminalId || !terminalItems.some(item => item.id === activeTerminalId)) {
      activeTerminalId = terminalItems[0]?.id || '';
      terminalOutputOffset = terminalOutputOffsets[activeTerminalId] || 0;
    }
    if (activeTerminalId && term) {
      resetTerminalWithReplay(terminalOutputBuffers[activeTerminalId] || '');
    }
    renderTerminalState();
    if (activeTerminalId) startTerminalPolling();
    focusTerminal();
    scheduleTerminalResize();
    terminalPanelLoaded = true;
  } catch (error) {
    if (term) {
      queueTerminalWrite(`加载终端失败: ${error.message || error}`);
    }
  }
}

async function openTerminalPanel(kind) {
  const cwd = document.getElementById('terminal-cwd-input')?.value?.trim() || '';
  if (cwd) {
    saveTerminalCwdHistory(cwd);
  }
  try {
    const data = await api('/api/terminals/open', 'POST', { kind, cwd });
    terminalItems = Array.isArray(data.items) ? data.items : [];
    activeTerminalId = data.item?.id || terminalItems[0]?.id || '';
    terminalOutputOffset = 0;
    terminalOutputBuffers[activeTerminalId] = '';
    terminalOutputOffsets[activeTerminalId] = 0;
    if (term) {
      resetTerminalWithReplay('');
    }
    renderTerminalState();
    startTerminalPolling();
    focusTerminal();
    scheduleTerminalResize();
  } catch (error) {
    showMessage(error.message || '打开终端失败。', true);
  }
}

async function closeTerminalPanel(id) {
  if (!id) return;
  try {
    const data = await api('/api/terminals/close', 'POST', { id });
    terminalItems = Array.isArray(data.items) ? data.items : [];
    delete terminalOutputBuffers[id];
    delete terminalOutputOffsets[id];
    if (activeTerminalId === id) {
      activeTerminalId = terminalItems[0]?.id || '';
      terminalOutputOffset = terminalOutputOffsets[activeTerminalId] || 0;
      if (term) {
        resetTerminalWithReplay(activeTerminalId ? (terminalOutputBuffers[activeTerminalId] || '') : '');
      }
    }
    renderTerminalState();
    if (activeTerminalId) startTerminalPolling();
    else stopTerminalPolling();
  } catch (error) {
    showMessage(error.message || '关闭终端失败。', true);
  }
}

function closeActiveTerminalPanel() {
  if (!activeTerminalId) return;
  void closeTerminalPanel(activeTerminalId);
}

async function writeTerminalRaw(text) {
  if (!activeTerminalId || !text) return;
  try {
    await api('/api/terminals/input', 'POST', { id: activeTerminalId, text });
  } catch (error) {
    if (term) {
      queueTerminalWrite(`\r\n[写入终端失败: ${error.message || error}]\r\n`);
    }
  }
}

document.addEventListener('click', (event) => {
  if (event.target?.closest?.('.terminal-control-panel')) return;
  if (!event.target?.closest?.('.terminal-output, .terminal-body')) return;
  focusTerminal();
});

window.addEventListener('resize', () => {
  if (isTerminalVisible()) scheduleTerminalResize(120);
});



const DEFAULT_PRESETS = [
  'claude --dangerously-skip-permissions',
  'openclaw gateway',
  'antigravity',
  '自定义命令 1 (点击/右键编辑)',
  '自定义命令 2 (点击/右键编辑)',
  '自定义命令 3 (点击/右键编辑)',
  '自定义命令 4 (点击/右键编辑)',
  '自定义命令 5 (点击/右键编辑)',
  '自定义命令 6 (点击/右键编辑)'
];
let terminalPresets = [];

function loadTerminalPresets() {
  try {
    const saved = localStorage.getItem('cliproxyapi_terminal_presets');
    terminalPresets = saved ? JSON.parse(saved) : [...DEFAULT_PRESETS];
  } catch {
    terminalPresets = [...DEFAULT_PRESETS];
  }
  // Ensure we have at least the default number of slots (e.g. 6)
  while (terminalPresets.length < DEFAULT_PRESETS.length) {
    terminalPresets.push(DEFAULT_PRESETS[terminalPresets.length]);
  }
}

function saveTerminalPresets() {
  localStorage.setItem('cliproxyapi_terminal_presets', JSON.stringify(terminalPresets));
}

function renderTerminalPresets() {
  const list = document.getElementById('preset-commands-list');
  if (!list) return;
  list.innerHTML = terminalPresets.map((cmd, idx) => {
    const isPlaceholder = cmd.includes('(点击/右键编辑)');
    const clickAction = isPlaceholder
      ? `handlePresetContextMenu(event, ${idx})`
      : `writeTerminalRaw(terminalPresets[${idx}] + '\\r'); focusTerminal()`;
    return `
      <button type="button" class="preset-cmd-btn"
        onclick="${clickAction}"
        oncontextmenu="handlePresetContextMenu(event, ${idx})"
        title="右键编辑：${terminalEscape(cmd)}">
        ${terminalEscape(cmd)}
      </button>
    `;
  }).join('');
}

function handlePresetContextMenu(e, idx) {
  e.preventDefault();
  const current = terminalPresets[idx] || '';
  const newVal = prompt("编辑预设命令 / Edit Preset Command:", current);
  if (newVal !== null) {
    const trimmed = newVal.trim();
    if (trimmed) {
      terminalPresets[idx] = trimmed;
      saveTerminalPresets();
      renderTerminalPresets();
    }
  }
}

const DEFAULT_CWD = 'E:\\U_App\\CLIProxyAPI_work\\CLIProxyAPI';

function getTerminalCwdHistory() {
  try {
    const saved = localStorage.getItem('cliproxyapi_terminal_cwd_history');
    const parsed = saved ? JSON.parse(saved) : [];
    if (!parsed.some(path => path.toLowerCase() === DEFAULT_CWD.toLowerCase())) {
      parsed.unshift(DEFAULT_CWD);
    }
    return parsed;
  } catch {
    return [DEFAULT_CWD];
  }
}

function saveTerminalCwdHistory(cwd) {
  if (!cwd) return;
  const history = getTerminalCwdHistory();
  const exists = history.some(path => path.toLowerCase() === cwd.toLowerCase());
  if (!exists) {
    history.push(cwd);
    localStorage.setItem('cliproxyapi_terminal_cwd_history', JSON.stringify(history));
    renderTerminalCwdHistory();
  }
}

function renderTerminalCwdHistory() {
  const datalist = document.getElementById('terminal-cwd-history');
  if (!datalist) return;
  const history = getTerminalCwdHistory();
  datalist.innerHTML = history.map(path => `<option value="${terminalEscape(path)}"></option>`).join('');
}
