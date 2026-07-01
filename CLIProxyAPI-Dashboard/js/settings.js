let settingsLoaded = false;
let currentSettings = {};

function switchSettingsTab(tab) {
  document.querySelectorAll('.settings-tab').forEach(t => t.classList.remove('active'));
  document.querySelector(`.settings-tab[data-tab="${tab}"]`).classList.add('active');

  document.querySelectorAll('.settings-panel').forEach(p => p.hidden = true);
  document.getElementById(`settings-${tab}`).hidden = false;
}

async function loadSettings() {
  if (settingsLoaded) return;

  try {
    // Load current settings
    const settings = await api('/api/settings');
    currentSettings = settings.item || {};

    // Apply settings to UI
    const autostartEl = document.getElementById('setting-autostart');
    const minimizeTrayEl = document.getElementById('setting-minimize-tray');
    const languageEl = document.getElementById('setting-language');
    const themeEl = document.getElementById('setting-theme');
    const autoUpdateCheckEl = document.getElementById('setting-auto-update-check');
    const updateChannelEl = document.getElementById('setting-update-channel');

    if (autostartEl) autostartEl.checked = currentSettings.autostart || false;
    if (minimizeTrayEl) minimizeTrayEl.checked = currentSettings.minimize_tray || false;
    if (languageEl) languageEl.value = currentSettings.language || 'zh';
    if (themeEl) themeEl.value = currentSettings.theme || 'light';
    if (autoUpdateCheckEl) autoUpdateCheckEl.checked = currentSettings.auto_update_check !== false;
    if (updateChannelEl) updateChannelEl.value = currentSettings.update_channel || 'stable';

    // Load version info
    const version = await api('/api/version');
    if (version.item) {
      const curVerEl = document.getElementById('current-version');
      const buildDateEl = document.getElementById('build-date');
      const cliVerEl = document.getElementById('cli-version');
      const dashVerEl = document.getElementById('dashboard-version');
      const elecVerEl = document.getElementById('electron-version');
      const lastUpdEl = document.getElementById('last-updated');

      if (curVerEl) curVerEl.textContent = `v${version.item.version}`;
      if (buildDateEl) buildDateEl.textContent = version.item.build_date || '';
      if (cliVerEl) cliVerEl.textContent = version.item.cli_version || '-';
      if (dashVerEl) dashVerEl.textContent = version.item.dashboard_version || '-';
      if (elecVerEl) elecVerEl.textContent = version.item.electron_version || '-';
      if (lastUpdEl) lastUpdEl.textContent = version.item.last_updated || '-';
    }

    settingsLoaded = true;
  } catch (error) {
    console.error('Failed to load settings:', error);
    const statusEl = document.getElementById('update-status');
    if (statusEl) {
      statusEl.innerHTML = `
        <div class="update-status error">
          Failed to load settings: ${error.message}
        </div>
      `;
    }
  }
}

async function saveSetting(key, value) {
  try {
    await api('/api/settings', 'POST', { key, value });
    currentSettings[key] = value;
    showMessage(`Setting '${key}' saved successfully`);
    
    // Apply immediate local changes
    if (key === 'language') {
      localStorage.setItem('dashboard_lang', value);
      applyLanguage();
    } else if (key === 'theme') {
      localStorage.setItem('dashboard_theme', value);
      applyTheme();
    }
  } catch (error) {
    console.error('Failed to save setting:', error);
    showMessage(`Failed to save setting: ${error.message}`, true);
  }
}

function clearLocalStorage() {
  localStorage.clear();
  showMessage(t('settings.msg.cacheCleared', 'Local cache has been successfully cleared! Reloading...'));
  setTimeout(() => {
    window.location.reload();
  }, 1000);
}

async function checkUpdates() {
  const statusEl = document.getElementById('update-status');
  if (!statusEl) return;
  
  statusEl.innerHTML = '<div class="update-status info">Checking for updates...</div>';

  try {
    const result = await api('/api/check-updates');
    if (result.item) {
      if (result.item.update_available) {
        statusEl.innerHTML = `
          <div class="update-status success">
            New version ${result.item.latest_version} is available!<br>
            Current: ${result.item.current_version} | Latest: ${result.item.latest_version}
          </div>
        `;
      } else {
        statusEl.innerHTML = `
          <div class="update-status success">
            You are using the latest version (${result.item.current_version}).
          </div>
        `;
      }
    }
  } catch (error) {
    statusEl.innerHTML = `
      <div class="update-status error">
        Failed to check for updates: ${error.message}
      </div>
    `;
  }
}

async function downloadLatest() {
  try {
    const result = await api('/api/download-update');
    if (result.ok) {
      showMessage('Download started!');
    } else {
      showMessage(result.message || 'Download failed', true);
    }
  } catch (error) {
    showMessage(`Failed to download: ${error.message}`, true);
  }
}

function openReleasePage() {
  window.open('https://github.com/youqu117/CLIProxyAPI_work/releases', '_blank');
}
