async function boot() {
  applyTheme();
  applyLanguage();
  applySidebarCollapsed();
  applySidebarNavOrder();
  applyNavGroupCollapsed();
  setLanguageToggleLabel();
  // 在挂载控制台之前先恢复指示灯缓存，避免账号页首屏先红后绿
  if (typeof loadIndicatorStates === 'function') {
    loadIndicatorStates();
  }
  const authOk = await checkAuthStatus();
  if (!authOk) {
    return;
  }
  const hashSection = String(window.location.hash || '').replace(/^#/, '').trim();
  if (hashSection && (typeof isKnownSection !== 'function' || isKnownSection(hashSection))) {
    await showSection(hashSection);
  } else {
    await showSection(getActiveSection());
  }
  if (typeof loadIndicatorStates === 'function') {
    loadIndicatorStates();
  }
  await refreshStatus();
  if (getActiveSection() === 'auths') {
    await loadAuthFiles();
  }
  
  // Check for updates on startup if enabled
  try {
    const settings = await api('/api/settings');
    if (settings && settings.item && settings.item.auto_update_check !== false) {
      const res = await api('/api/check-updates');
      if (res && res.item && res.item.update_available) {
        showMessage(`New version v${res.item.latest_version} is available! Please check the Settings panel.`);
      }
    }
  } catch (err) {
    console.error("Startup update check failed:", err);
  }
  // 账号页轮询：12s 足够，配合 refreshStatus 内“无变化不写 DOM”可明显减卡顿
  setInterval(refreshStatus, 12000);
  setInterval(() => {
    // Only poll auth data when auth tab is visible
    const active = getActiveSection();
    if (active === 'auths') {
      loadAuthFiles();
    }
  }, 15000);
}

async function checkAuthStatus() {
  try {
    const res = await api('/api/auth/check');
    if (res && res.password_set) {
      if (res.authenticated) {
        hideLoginScreen();
        return true;
      }
      showLoginScreen();
      return false;
    }
    hideLoginScreen();
    return true;
  } catch (err) {
    console.error("Auth check failed:", err);
    hideLoginScreen();
    return true;
  }
}

function showLoginScreen() {
  const overlay = document.getElementById('login-overlay');
  if (overlay) {
    overlay.hidden = false;
    setTimeout(() => {
      const input = document.getElementById('login-password');
      if (input) input.focus();
    }, 100);
  }
}

function hideLoginScreen() {
  const overlay = document.getElementById('login-overlay');
  if (overlay) {
    overlay.hidden = true;
  }
  const errorEl = document.getElementById('login-error');
  if (errorEl) {
    errorEl.style.display = 'none';
  }
  const input = document.getElementById('login-password');
  if (input) {
    input.value = '';
  }
}

async function submitLogin() {
  const passwordEl = document.getElementById('login-password');
  const errorEl = document.getElementById('login-error');
  const password = passwordEl ? passwordEl.value : '';
  if (!password) {
    if (errorEl) {
      errorEl.textContent = '请输入访问口令';
      errorEl.style.display = 'block';
    }
    return;
  }
  try {
    const res = await api('/api/auth/login', 'POST', { password });
    if (res && res.token) {
      setAuthToken(res.token);
      hideLoginScreen();
      if (typeof boot === 'function') {
        boot();
      }
    }
  } catch (err) {
    if (errorEl) {
      errorEl.textContent = err.message || '口令错误，请重试';
      errorEl.style.display = 'block';
    }
    if (passwordEl) {
      passwordEl.value = '';
      passwordEl.focus();
    }
  }
}

window.addEventListener('hashchange', () => {
  const next = getActiveSection();
  if (typeof isKnownSection !== 'function' || isKnownSection(next)) showSection(next);
});

boot();
