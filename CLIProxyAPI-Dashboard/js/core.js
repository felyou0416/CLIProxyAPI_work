// I18N translation dictionary has been optimized and moved to js/i18n.js to reduce core.js size.



function getLanguage() {
  return localStorage.getItem('dashboard_lang') || 'zh';
}

function t(key, fallback = '') {
  const lang = getLanguage();
  return (I18N[lang] && I18N[lang][key]) || fallback || key;
}

function setLanguageToggleLabel() {
  const el = document.getElementById('lang-toggle');
  if (!el) return;
  el.textContent = getLanguage() === 'zh' ? 'EN' : '中文';
}

function applyLanguage() {
  document.documentElement.lang = getLanguage() === 'zh' ? 'zh-CN' : 'en';
  document.querySelectorAll('[data-i18n]').forEach(el => {
    const key = el.getAttribute('data-i18n');
    const value = t(key, el.textContent);
    if (el.hasAttribute('data-i18n-html')) el.innerHTML = value;
    else el.textContent = value;
  });
  document.querySelectorAll('[data-i18n-placeholder]').forEach(el => {
    const key = el.getAttribute('data-i18n-placeholder');
    el.setAttribute('placeholder', t(key, el.getAttribute('placeholder') || ''));
  });
  document.querySelectorAll('[data-i18n-title]').forEach(el => {
    const key = el.getAttribute('data-i18n-title');
    el.setAttribute('title', t(key, el.getAttribute('title') || ''));
  });
  setLanguageToggleLabel();
  applyTheme();
}

function toggleLanguage() {
  const nextLang = getLanguage() === 'zh' ? 'en' : 'zh';
  localStorage.setItem('dashboard_lang', nextLang);
  applyLanguage();
  if (typeof refreshStatus === 'function') refreshStatus();
  if (typeof loadAuthFiles === 'function') loadAuthFiles();
  
  // Sync to server settings
  api('/api/settings', 'POST', { key: 'language', value: nextLang }).catch(err => console.error(err));
  
  // Sync UI dropdown
  const langSelect = document.getElementById('setting-language');
  if (langSelect) langSelect.value = nextLang;
}

function getTheme() {
  const theme = localStorage.getItem('dashboard_theme') || 'light';
  if (theme === 'eye' || theme === 'eye-white') return 'light';
  return theme;
}

function getThemeCycle() {
  return ['light', 'dark', 'bright'];
}

function getThemeName(theme, lang) {
  const zh = {
    light: '浅色',
    dark: '暗色',
    bright: '明亮'
  };
  const en = {
    light: 'Light',
    dark: 'Dark',
    bright: 'Bright'
  };
  const map = lang === 'zh' ? zh : en;
  return map[theme] || theme;
}

function themeToggleText(theme, lang) {
  const cycle = getThemeCycle();
  const index = cycle.indexOf(theme);
  const next = cycle[(index + 1 + cycle.length) % cycle.length];
  if (lang === 'zh') return `主题：${getThemeName(next, 'zh')}`;
  return `Theme: ${getThemeName(next, 'en')}`;
}

function applyTheme() {
  const theme = getTheme();
  document.documentElement.setAttribute('data-theme', theme);
  const btn = document.getElementById('theme-toggle');
  if (btn) btn.textContent = themeToggleText(theme, getLanguage());
}

function toggleTheme() {
  const cycle = getThemeCycle();
  const current = getTheme();
  const index = cycle.indexOf(current);
  const next = cycle[(index + 1 + cycle.length) % cycle.length];
  localStorage.setItem('dashboard_theme', next);
  applyTheme();
  
  // Sync to server settings
  api('/api/settings', 'POST', { key: 'theme', value: next }).catch(err => console.error(err));
  
  // Sync UI dropdown
  const themeSelect = document.getElementById('setting-theme');
  if (themeSelect) themeSelect.value = next;
}

const DASHBOARD_SIDEBAR_COLLAPSED_KEY = 'dashboard_sidebar_collapsed_v1';

function isSidebarCollapsed() {
  return localStorage.getItem(DASHBOARD_SIDEBAR_COLLAPSED_KEY) === '1';
}

function applySidebarCollapsed() {
  const sidebar = document.getElementById('app-sidebar');
  const shell = document.querySelector('.app-shell');
  const toggle = document.getElementById('sidebar-collapse-toggle');
  const collapsed = isSidebarCollapsed();

  sidebar?.classList.toggle('sidebar-collapsed', collapsed);
  shell?.classList.toggle('sidebar-is-collapsed', collapsed);

  if (toggle) {
    toggle.setAttribute('aria-expanded', collapsed ? 'false' : 'true');
    toggle.setAttribute('title', collapsed ? '展开侧栏' : '折叠侧栏');
  }

  if (collapsed) {
    document.querySelectorAll('.nav-group').forEach(el => el.classList.add('is-collapsed'));
  } else {
    applyNavGroupCollapsed();
  }
}

function toggleSidebarCollapsed() {
  localStorage.setItem(DASHBOARD_SIDEBAR_COLLAPSED_KEY, isSidebarCollapsed() ? '0' : '1');
  applySidebarCollapsed();
  window.requestAnimationFrame(layoutBubbleNav);
}

function getNavGroups() {
  return {
    runtime: ['account', 'chat', 'requests', 'model-stats', 'clients', 'auth-health', 'settings'],
    config: ['providers', 'media-models', 'aggregates', 'model-map', 'api-key-intake', 'auths'],
    access: ['firewall-access', 'terminals', 'external-access', 'tools', 'virtual-keys', 'doc'],
    system: ['network-access', 'cooldown', 'storage-config', 'home-config', 'docker-deploy', 'advanced-config', 'cloaking-config', 'amp-config', 'model-proxy'],
  };
}

function getSectionGroup(section) {
  const groups = getNavGroups();
  const value = String(section || '').trim();
  for (const [groupKey, items] of Object.entries(groups)) {
    if (items.includes(value)) return groupKey;
  }
  return 'runtime';
}

function getActiveSection() {
  const fromHash = String(window.location.hash || '').replace(/^#/, '').trim();
  if (fromHash) return fromHash;
  return localStorage.getItem('dashboard_active_section') || 'account';
}

function persistActiveSection(name) {
  const value = String(name || '').trim();
  if (!value) return;
  localStorage.setItem('dashboard_active_section', value);
  localStorage.setItem('dashboard_active_group', getSectionGroup(value));
  if (window.location.hash !== `#${value}`) {
    history.replaceState(null, '', `#${value}`);
  }
}

function getActiveGroup() {
  const section = getActiveSection();
  return localStorage.getItem('dashboard_active_group') || getSectionGroup(section);
}

function persistActiveGroup(group) {
  const value = String(group || '').trim() || 'runtime';
  localStorage.setItem('dashboard_active_group', value);
}

function getDefaultSidebarNavOrder() {
  return ['account', 'chat', 'requests', 'model-stats', 'clients', 'auth-health', 'settings', 'providers', 'media-models', 'aggregates', 'model-map', 'api-key-intake', 'auths', 'firewall-access', 'terminals', 'network-access', 'external-access', 'model-proxy', 'doc', 'tools'];
}

function getSidebarNavOrder() {
  try {
    const raw = localStorage.getItem('dashboard_sidebar_nav_order');
    const parsed = raw ? JSON.parse(raw) : [];
    const defaults = getDefaultSidebarNavOrder();
    if (!Array.isArray(parsed) || !parsed.length) return defaults;
    const known = parsed.filter(key => defaults.includes(key));
    defaults.forEach(key => {
      if (!known.includes(key)) known.push(key);
    });
    return known;
  } catch {
    return getDefaultSidebarNavOrder();
  }
}

function persistSidebarNavOrder(order) {
  localStorage.setItem('dashboard_sidebar_nav_order', JSON.stringify(order));
}

const DASHBOARD_BUBBLE_NAV_POSITIONS_KEY = 'dashboard_sidebar_bubble_positions_v1';
const DASHBOARD_BUBBLE_NAV_HEIGHT_KEY = 'dashboard_sidebar_bubble_height_v1';
let dashboardBubbleNavReady = false;
let dashboardBubbleNavDraggedButton = null;

function applySidebarNavOrder() {
  const container = document.getElementById('sidebar-nav-list');
  if (!container) return;
  const order = getSidebarNavOrder();
  order.forEach(key => {
    const item = container.querySelector(`.nav-item[data-nav-key="${key}"]`);
    if (item) container.appendChild(item);
  });
}

function getStoredBubbleNavPositions() {
  try {
    const raw = localStorage.getItem(DASHBOARD_BUBBLE_NAV_POSITIONS_KEY);
    const parsed = raw ? JSON.parse(raw) : {};
    return parsed && typeof parsed === 'object' && !Array.isArray(parsed) ? parsed : {};
  } catch {
    return {};
  }
}

function storeBubbleNavPosition(key, position) {
  if (!key || !position) return;
  const positions = getStoredBubbleNavPositions();
  positions[key] = {
    x: Math.round(Number(position.x) || 0),
    y: Math.round(Number(position.y) || 0),
  };
  localStorage.setItem(DASHBOARD_BUBBLE_NAV_POSITIONS_KEY, JSON.stringify(positions));
}

function defaultBubbleNavPosition(index, container, button) {
  const width = Math.max(1, container.clientWidth || 240);
  const buttonWidth = Math.max(78, button.offsetWidth || 96);
  const maxX = Math.max(0, width - buttonWidth - 2);
  const points = [
    [0.00, 0.05],
    [0.46, 0.00],
    [0.10, 0.34],
    [0.54, 0.34],
    [0.28, 0.68],
  ];
  const [xRatio, yRatio] = points[index % points.length];
  const row = Math.floor(index / points.length);
  return {
    x: Math.min(maxX, Math.round(maxX * xRatio)),
    y: Math.round(6 + (yRatio * 112) + row * 40),
  };
}

function clampBubbleNavPosition(position, container, button) {
  const maxX = Math.max(0, (container.clientWidth || 240) - (button.offsetWidth || 80) - 2);
  const maxY = Math.max(0, (container.clientHeight || 172) - (button.offsetHeight || 34) - 2);
  return {
    x: Math.max(0, Math.min(maxX, Number(position.x) || 0)),
    y: Math.max(0, Math.min(maxY, Number(position.y) || 0)),
  };
}

function bubbleNavRect(position, button, gap = 10) {
  return {
    left: position.x - gap,
    top: position.y - gap,
    right: position.x + (button.offsetWidth || 80) + gap,
    bottom: position.y + (button.offsetHeight || 34) + gap,
  };
}

function bubbleNavRectsOverlap(a, b) {
  return a.left < b.right && a.right > b.left && a.top < b.bottom && a.bottom > b.top;
}

function bubbleNavOverlaps(position, button, placedRects) {
  const rect = bubbleNavRect(position, button);
  return placedRects.some(placed => bubbleNavRectsOverlap(rect, placed));
}

function resolveBubbleNavPosition(base, container, button, placedRects) {
  const desired = clampBubbleNavPosition(base, container, button);
  if (!bubbleNavOverlaps(desired, button, placedRects)) return desired;

  const maxX = Math.max(0, (container.clientWidth || 240) - (button.offsetWidth || 80) - 2);
  const maxY = Math.max(0, (container.clientHeight || 172) - (button.offsetHeight || 34) - 2);
  const step = 8;
  let best = desired;
  let bestScore = Number.POSITIVE_INFINITY;

  for (let y = 0; y <= maxY; y += step) {
    for (let x = 0; x <= maxX; x += step) {
      const candidate = { x, y };
      if (bubbleNavOverlaps(candidate, button, placedRects)) continue;
      const score = Math.abs(candidate.x - desired.x) + Math.abs(candidate.y - desired.y);
      if (score < bestScore) {
        best = candidate;
        bestScore = score;
      }
    }
  }
  return best;
}

function layoutBubbleNav() {
  const container = document.getElementById('top-page-nav-list');
  if (!container || !container.classList.contains('sidebar-bubble-nav')) return;
  applyBubbleNavHeight();
  const positions = getStoredBubbleNavPositions();
  const visibleButtons = Array.from(container.querySelectorAll('.top-nav-btn:not(.nav-hidden)'));
  const placedRects = [];
  visibleButtons.forEach((button, index) => {
    const key = button.id || `bubble-${index}`;
    const saved = positions[key];
    const base = saved || defaultBubbleNavPosition(index, container, button);
    const next = resolveBubbleNavPosition(base, container, button, placedRects);
    button.style.left = `${next.x}px`;
    button.style.top = `${next.y}px`;
    button.style.setProperty('--bubble-delay', `${(index % 5) * -0.8}s`);
    placedRects.push(bubbleNavRect(next, button));
  });
}

function getBubbleNavHeight() {
  const value = Number(localStorage.getItem(DASHBOARD_BUBBLE_NAV_HEIGHT_KEY) || 0);
  return Number.isFinite(value) && value > 0 ? Math.max(138, Math.min(320, value)) : 184;
}

function applyBubbleNavHeight() {
  const container = document.getElementById('top-page-nav-list');
  if (!container || !container.classList.contains('sidebar-bubble-nav')) return;
  container.style.height = `${getBubbleNavHeight()}px`;
}

function initBubbleNavResizeRail() {
  const container = document.getElementById('top-page-nav-list');
  const rail = document.getElementById('bubble-nav-resize-rail');
  if (!container || !rail) return;
  applyBubbleNavHeight();
  rail.addEventListener('pointerdown', (event) => {
    if (event.button !== undefined && event.button !== 0) return;
    const startY = event.clientY;
    const startHeight = getBubbleNavHeight();
    rail.setPointerCapture?.(event.pointerId);
    rail.classList.add('is-dragging');

    const onMove = (moveEvent) => {
      const next = Math.max(138, Math.min(320, startHeight + moveEvent.clientY - startY));
      localStorage.setItem(DASHBOARD_BUBBLE_NAV_HEIGHT_KEY, String(Math.round(next)));
      container.style.height = `${Math.round(next)}px`;
      layoutBubbleNav();
    };

    const onEnd = () => {
      rail.removeEventListener('pointermove', onMove);
      rail.removeEventListener('pointerup', onEnd);
      rail.removeEventListener('pointercancel', onEnd);
      rail.classList.remove('is-dragging');
      layoutBubbleNav();
    };

    rail.addEventListener('pointermove', onMove);
    rail.addEventListener('pointerup', onEnd);
    rail.addEventListener('pointercancel', onEnd);
  });
}

function initBubbleNavDrag() {
  if (dashboardBubbleNavReady) return;
  const container = document.getElementById('top-page-nav-list');
  if (!container || !container.classList.contains('sidebar-bubble-nav')) return;
  dashboardBubbleNavReady = true;
  initBubbleNavResizeRail();

  container.addEventListener('click', (event) => {
    const button = event.target?.closest?.('.top-nav-btn');
    if (!button || button !== dashboardBubbleNavDraggedButton) return;
    event.preventDefault();
    event.stopImmediatePropagation();
    dashboardBubbleNavDraggedButton = null;
  }, true);

  container.querySelectorAll('.top-nav-btn').forEach((button) => {
    button.addEventListener('pointerdown', (event) => {
      if (event.button !== undefined && event.button !== 0) return;
      const rect = button.getBoundingClientRect();
      const containerRect = container.getBoundingClientRect();
      const start = {
        pointerX: event.clientX,
        pointerY: event.clientY,
        x: rect.left - containerRect.left,
        y: rect.top - containerRect.top,
      };
      let moved = false;
      button.setPointerCapture?.(event.pointerId);
      button.classList.add('is-dragging');

      const onMove = (moveEvent) => {
        const dx = moveEvent.clientX - start.pointerX;
        const dy = moveEvent.clientY - start.pointerY;
        if (Math.abs(dx) + Math.abs(dy) > 4) moved = true;
        const next = clampBubbleNavPosition({ x: start.x + dx, y: start.y + dy }, container, button);
        button.style.left = `${next.x}px`;
        button.style.top = `${next.y}px`;
      };

      const onEnd = () => {
        button.removeEventListener('pointermove', onMove);
        button.removeEventListener('pointerup', onEnd);
        button.removeEventListener('pointercancel', onEnd);
        button.classList.remove('is-dragging');
        if (moved) {
          dashboardBubbleNavDraggedButton = button;
          const next = clampBubbleNavPosition({
            x: parseFloat(button.style.left || '0'),
            y: parseFloat(button.style.top || '0'),
          }, container, button);
          storeBubbleNavPosition(button.id, next);
          setTimeout(() => {
            if (dashboardBubbleNavDraggedButton === button) dashboardBubbleNavDraggedButton = null;
          }, 80);
        }
      };

      button.addEventListener('pointermove', onMove);
      button.addEventListener('pointerup', onEnd);
      button.addEventListener('pointercancel', onEnd);
    });
  });

  window.addEventListener('resize', () => {
    window.requestAnimationFrame(layoutBubbleNav);
  });
  window.requestAnimationFrame(layoutBubbleNav);
}

const DASHBOARD_NAV_COLLAPSED_GROUPS_KEY = 'dashboard_nav_collapsed_groups_v1';

function getCollapsedNavGroups() {
  try {
    const raw = localStorage.getItem(DASHBOARD_NAV_COLLAPSED_GROUPS_KEY);
    return raw ? JSON.parse(raw) : [];
  } catch {
    return [];
  }
}

function setCollapsedNavGroups(list) {
  localStorage.setItem(DASHBOARD_NAV_COLLAPSED_GROUPS_KEY, JSON.stringify(list));
}

function toggleNavGroup(group) {
  const el = document.getElementById('navgroup-' + group);
  if (!el) return;
  const collapsed = el.classList.toggle('is-collapsed');
  const list = getCollapsedNavGroups();
  const idx = list.indexOf(group);
  if (collapsed && idx < 0) list.push(group);
  if (!collapsed && idx >= 0) list.splice(idx, 1);
  setCollapsedNavGroups(list);
}

function applyNavGroupCollapsed() {
  const collapsed = getCollapsedNavGroups();
  document.querySelectorAll('.nav-group').forEach(el => {
    const group = el.dataset.group;
    el.classList.toggle('is-collapsed', collapsed.includes(group));
  });
}

function updateGroupNavigation(activeGroup) {
  // In the new grouped sidebar all groups are always visible.
  // Just highlight the active nav button - no hiding needed.
  document.querySelectorAll('.top-nav-btn').forEach(el => {
    el.classList.remove('nav-hidden');
  });
}

function showGroup(group) {
  // No-op in grouped sidebar: all groups are visible simultaneously.
  // Switch to the first section of the group if current section is in a different group.
  const value = String(group || '').trim() || 'runtime';
  persistActiveGroup(value);
  const groups = getNavGroups();
  const activeSection = getActiveSection();
  if (!groups[value] || !groups[value].includes(activeSection)) {
    const nextSection = (groups[value] && groups[value][0]) || 'account';
    showSection(nextSection);
    return;
  }
  showSection(activeSection);
}

function moveSidebarNav(key, direction) {
  const order = getSidebarNavOrder();
  const index = order.indexOf(key);
  if (index < 0) return;
  const nextIndex = index + Number(direction || 0);
  if (nextIndex < 0 || nextIndex >= order.length) return;
  [order[index], order[nextIndex]] = [order[nextIndex], order[index]];
  persistSidebarNavOrder(order);
  applySidebarNavOrder();
  updateGroupNavigation(getActiveGroup());
}

const loadingSections = {};

async function showSection(name) {
  if (!document.getElementById('tab-' + name)) {
    name = 'account';
  }

  if (document.getElementById('section-' + name)?.classList.contains('active-view')) {
    persistActiveSection(name);
    persistActiveGroup(getSectionGroup(name));
    return;
  }

  if (!document.getElementById('section-' + name)) {
    if (loadingSections[name]) return;
    loadingSections[name] = true;
    try {
      const htmlText = await fetch(`/sections/${name}.html`).then(r => {
        if (!r.ok) throw new Error(`HTTP error ${r.status}`);
        return r.text();
      });
      const tempDiv = document.createElement('div');
      tempDiv.innerHTML = htmlText;
      const sectionEl = tempDiv.querySelector('section');
      if (sectionEl) {
        document.getElementById('main-sections').appendChild(sectionEl);
        applyLanguage();
      }
    } catch (err) {
      console.error(`Failed to lazy load section ${name}:`, err);
      showMessage(`加载面板 ${name} 失败: ${err.message}`, true);
      return;
    } finally {
      delete loadingSections[name];
    }
  }

  const activeGroup = getSectionGroup(name);
  document.querySelectorAll('.section-view').forEach(el => el.classList.remove('active-view'));
  document.querySelectorAll('.top-nav-btn').forEach(el => el.classList.remove('active'));
  updateGroupNavigation(activeGroup);
  document.getElementById('section-' + name)?.classList.add('active-view');
  document.getElementById('tab-' + name)?.classList.add('active');
  persistActiveSection(name);
  persistActiveGroup(activeGroup);
  if (name === 'aggregates' && typeof loadAggregateModels === 'function') {
    loadAggregateModels();
  }
  if (name === 'model-proxy' && typeof loadModelProxyPanel === 'function') {
    loadModelProxyPanel();
  }
  if (name === 'providers' && typeof loadProviderModels === 'function') {
    loadProviderModels(false);
  }
  if (name === 'media-models' && typeof loadMediaModels === 'function') {
    loadMediaModels(false);
  }
  if (name === 'model-map' && typeof loadProviderModelMappings === 'function') {
    loadProviderModelMappings();
  }
  if (name === 'api-key-intake' && typeof loadApiKeyIntakePanel === 'function') {
    loadApiKeyIntakePanel();
  }
  if (name === 'auths' && typeof loadAuthFiles === 'function') {
    // Render from cache instantly, then refresh in background
    if (typeof renderAuthUI === 'function' && typeof _cachedAuthItems !== 'undefined' && _cachedAuthItems.length > 0) {
      renderAuthUI();
    } else {
      loadAuthFiles();
    }
  }
  if (name === 'requests' && typeof loadRequestEventsPanel === 'function') {
    loadRequestEventsPanel();
  }
  if (name === 'model-stats' && typeof loadModelStatsPanel === 'function') {
    loadModelStatsPanel();
  }
  if (name === 'clients' && typeof loadClientsPanel === 'function') {
    loadClientsPanel();
  }
  if (name === 'models' && typeof loadModelsPanel === 'function') {
    loadModelsPanel();
  }
  if (name === 'auth-health' && typeof loadAuthHealthPanel === 'function') {
    loadAuthHealthPanel();
  }
  if (name === 'overview' && typeof loadOverviewPanel === 'function') {
    loadOverviewPanel();
  }
  if (name === 'chat' && typeof loadChatPanel === 'function') {
    loadChatPanel();
  }
  if (name === 'network-access' && typeof loadNetworkAccessPanel === 'function') {
    loadNetworkAccessPanel();
  }
  if (name === 'account' && typeof loadIpHelperStatus === 'function') {
    loadIpHelperStatus(true);
  }
  if (name === 'firewall-access' && typeof loadFirewallAccessPanel === 'function') {
    loadFirewallAccessPanel();
  }
  if (name === 'external-access' && typeof loadExternalAccessPanel === 'function') {
    loadExternalAccessPanel();
  }
  if (name === 'cooldown' && typeof loadCooldownPanel === 'function') {
    loadCooldownPanel(true);
  }
  if (name === 'virtual-keys' && typeof loadVirtualKeysPanel === 'function') {
    loadVirtualKeysPanel();
  }
  if (name === 'terminals' && typeof loadTerminalPanel === 'function') {
    loadTerminalPanel();
  }
  if (name === 'advanced-config' && typeof loadAdvancedConfig === 'function') {
    loadAdvancedConfig();
  }
  if (name === 'cloaking-config' && typeof loadCloakingConfig === 'function') {
    loadCloakingConfig();
  }
  if (name === 'amp-config' && typeof loadAmpConfig === 'function') {
    loadAmpConfig();
  }
  if (name === 'storage-config' && typeof loadStorageConfig === 'function') {
    loadStorageConfig();
  }
  if (name === 'home-config' && typeof loadHomeConfig === 'function') {
    loadHomeConfig();
  }
  if (name === 'docker-deploy' && typeof loadDockerDeploy === 'function') {
    loadDockerDeploy();
  }
  if (name === 'settings' && typeof loadSettings === 'function') {
    loadSettings();
  }
  const msg = document.getElementById('message');
  if (msg) msg.className = 'message';
}

function showPage(name) {
  showSection(name);
}

async function api(path, method = 'GET', body) {
  const res = await fetch(path, {
    method,
    headers: { 'Content-Type': 'application/json' },
    body: body ? JSON.stringify(body) : undefined,
  });
  const text = await res.text();
  let data = null;
  try {
    data = text ? JSON.parse(text) : {};
  } catch {
    const hint = text.trim().startsWith('<')
      ? `${path} returned a page instead of JSON.`
      : `${path} returned invalid JSON.`;
    throw new Error(hint);
  }
  if (!res.ok) throw new Error(data.message || t('common.requestFailed', 'Request failed'));
  return data;
}

function setLogVisible(el, visible) {
  if (!el) return;
  el.classList.toggle('is-hidden', !visible);
}

function setText(id, value, fallback = '') {
  const el = document.getElementById(id);
  if (el) el.textContent = value || fallback;
}

let _messageTimer = null;
let _messageHideTimer = null;

function showMessage(text, isError = false) {
  const el = document.getElementById('message');
  if (!el) return;

  // Cancel any pending timers
  if (_messageTimer) { clearTimeout(_messageTimer); _messageTimer = null; }
  if (_messageHideTimer) { clearTimeout(_messageHideTimer); _messageHideTimer = null; }

  // Reset animation by removing and re-adding .show
  el.className = 'message';
  el.textContent = text;

  // Force reflow so animation re-triggers
  void el.offsetWidth;

  el.className = `message show ${isError ? 'error' : 'success'}`;

  // Auto-dismiss: errors stay longer (6s), success 4s
  const delay = isError ? 6000 : 4000;
  _messageTimer = setTimeout(() => {
    el.classList.add('hiding');
    _messageHideTimer = setTimeout(() => {
      el.className = 'message';
      el.textContent = '';
    }, 320);
  }, delay);
}

function statusPill(running) {
  return running
    ? `<span class="pill ok">${t('running', 'Running')}</span>`
    : `<span class="pill off">${t('stopped', 'Not running')}</span>`;
}

function statusText(running) {
  return running ? t('running', 'Running') : t('stopped', 'Not running');
}
