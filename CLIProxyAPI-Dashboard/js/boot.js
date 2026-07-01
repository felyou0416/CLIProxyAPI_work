async function boot() {
  applyTheme();
  applyLanguage();
  applySidebarCollapsed();
  applySidebarNavOrder();
  applyNavGroupCollapsed();
  setLanguageToggleLabel();
  const hashSection = String(window.location.hash || '').replace(/^#/, '').trim();
  if (hashSection && document.getElementById('tab-' + hashSection)) {
    showSection(hashSection);
  } else {
    showSection(getActiveSection());
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
  setInterval(refreshStatus, 8000);
  setInterval(() => {
    // Only poll auth data when auth tab is visible
    const active = getActiveSection();
    if (active === 'auths') {
      loadAuthFiles();
    }
  }, 15000);
}

window.addEventListener('hashchange', () => {
  const next = getActiveSection();
  if (document.getElementById('tab-' + next)) showSection(next);
});

boot();
