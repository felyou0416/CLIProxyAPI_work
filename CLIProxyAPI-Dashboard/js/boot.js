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
