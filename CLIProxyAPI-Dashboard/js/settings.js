let settingsLoaded = false;
let currentSettings = {};
let passwordSet = false;

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

    // Load access password status
    await loadAccessPasswordStatus();

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

async function loadAccessPasswordStatus() {
  try {
    const res = await api('/api/auth/check');
    passwordSet = !!res.password_set;
    updatePasswordStatusUI();
  } catch (err) {
    console.error('Failed to load access password status:', err);
  }
}

function updatePasswordStatusUI() {
  const statusEl = document.getElementById('access-password-status');
  const btnEl = document.getElementById('access-password-btn');
  const removeBtn = document.getElementById('remove-password-btn');
  const currentPwRow = document.getElementById('current-password-row');

  if (statusEl) {
    statusEl.textContent = passwordSet ? (t('settings.val.passwordEnabled', 'Enabled') || 'Enabled') : (t('settings.val.passwordDisabled', 'Disabled') || 'Disabled');
    statusEl.style.background = passwordSet ? '#dcfce7' : '#f1f5f9';
    statusEl.style.color = passwordSet ? '#166534' : '#64748b';
  }
  if (btnEl) {
    btnEl.textContent = passwordSet ? (t('settings.btn.changePassword', 'Change') || 'Change') : (t('settings.btn.setPassword', 'Set Password') || 'Set Password');
  }
  if (removeBtn) {
    removeBtn.style.display = passwordSet ? 'inline-block' : 'none';
  }
  if (currentPwRow) {
    currentPwRow.style.display = passwordSet ? 'flex' : 'none';
  }
}

function togglePasswordSetup() {
  const formEl = document.getElementById('access-password-form');
  if (!formEl) return;
  if (formEl.style.display === 'none' || !formEl.style.display) {
    formEl.style.display = 'block';
    const input = passwordSet ? document.getElementById('current-password-input') : document.getElementById('new-password-input');
    if (input) input.focus();
  } else {
    cancelPasswordSetup();
  }
}

function cancelPasswordSetup() {
  const formEl = document.getElementById('access-password-form');
  if (formEl) formEl.style.display = 'none';
  const curPw = document.getElementById('current-password-input');
  const newPw = document.getElementById('new-password-input');
  const confPw = document.getElementById('confirm-password-input');
  if (curPw) curPw.value = '';
  if (newPw) newPw.value = '';
  if (confPw) confPw.value = '';
}

async function saveAccessPassword() {
  const newPw = document.getElementById('new-password-input');
  const confPw = document.getElementById('confirm-password-input');
  const curPw = document.getElementById('current-password-input');
  const newPassword = newPw ? newPw.value : '';
  const confirmPassword = confPw ? confPw.value : '';
  const currentPassword = curPw ? curPw.value : '';

  if (!newPassword) {
    showMessage(t('settings.msg.passwordRequired', 'Please enter a new password') || 'Please enter a new password', true);
    return;
  }
  if (newPassword !== confirmPassword) {
    showMessage(t('settings.msg.passwordMismatch', 'Passwords do not match') || 'Passwords do not match', true);
    return;
  }
  if (passwordSet && !currentPassword) {
    showMessage(t('settings.msg.currentPasswordRequired', 'Please enter the current password') || 'Please enter the current password', true);
    return;
  }

  try {
    const body = { new_password: newPassword };
    if (passwordSet) {
      body.current_password = currentPassword;
    }
    const res = await api('/api/auth/set-password', 'POST', body);
    if (res && res.ok) {
      passwordSet = !!res.password_set;
      updatePasswordStatusUI();
      cancelPasswordSetup();
      showMessage(t('settings.msg.passwordSaved', 'Access password saved successfully') || 'Access password saved successfully');
    }
  } catch (err) {
    showMessage(err.message || (t('settings.msg.passwordSaveFailed', 'Failed to save password') || 'Failed to save password'), true);
  }
}

async function removeAccessPassword() {
  const curPw = document.getElementById('current-password-input');
  const currentPassword = curPw ? curPw.value : '';
  if (passwordSet && !currentPassword) {
    showMessage(t('settings.msg.currentPasswordRequired', 'Please enter the current password') || 'Please enter the current password', true);
    const formEl = document.getElementById('access-password-form');
    if (formEl && formEl.style.display === 'none') {
      formEl.style.display = 'block';
    }
    if (curPw) curPw.focus();
    return;
  }

  try {
    const body = { new_password: '' };
    if (passwordSet) {
      body.current_password = currentPassword;
    }
    const res = await api('/api/auth/set-password', 'POST', body);
    if (res && res.ok) {
      passwordSet = false;
      clearAuthToken();
      updatePasswordStatusUI();
      cancelPasswordSetup();
      showMessage(t('settings.msg.passwordRemoved', 'Access password removed') || 'Access password removed');
    }
  } catch (err) {
    showMessage(err.message || (t('settings.msg.passwordRemoveFailed', 'Failed to remove password') || 'Failed to remove password'), true);
  }
}

async function saveSetting(key, value) {
  try {
    const res = await api('/api/settings', 'POST', { key, value });
    const savedValue = (res && Object.prototype.hasOwnProperty.call(res, 'value')) ? res.value : value;
    currentSettings[key] = savedValue;

    if (key === 'autostart') {
      const autostartEl = document.getElementById('setting-autostart');
      if (autostartEl) autostartEl.checked = !!savedValue;
      showMessage(res?.message || (savedValue
        ? (t('settings.msg.autostartOn', '已开启开机自启动') || '已开启开机自启动')
        : (t('settings.msg.autostartOff', '已关闭开机自启动') || '已关闭开机自启动')));
    } else {
      showMessage(res?.message || `Setting '${key}' saved successfully`);
    }

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
    if (key === 'autostart') {
      const autostartEl = document.getElementById('setting-autostart');
      if (autostartEl) autostartEl.checked = !!currentSettings.autostart;
    }
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
