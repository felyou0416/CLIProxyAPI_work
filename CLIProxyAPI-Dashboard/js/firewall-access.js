let firewallAccessLoaded = false;
let firewallAccessLastPorts = [];
let portBindingLastPorts = [];
const defaultTrustedRemoteAddresses = 'fd7a:115c:a1e0::9e39:c580, 100.89.197.128';
let portBindingStatusSignature = '';
let firewallStatusSignature = '';
let ipHelperStatusSignature = '';
let portBindingStatusCache = null;
let firewallStatusCache = null;
let ipHelperStatusCache = null;

function firewallEscape(value) {
  return String(value ?? '')
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#39;');
}

function parseFirewallPortInput() {
  const input = document.getElementById('firewall-port-input');
  const raw = String(input?.value || '').trim();
  if (!raw) return [];
  const ports = [];
  raw.split(/[\s,;]+/).forEach((part) => {
    if (!part) return;
    const port = Number(part);
    if (!Number.isInteger(port) || port < 1 || port > 65535) {
      throw new Error(`无效端口：${part}`);
    }
    if (!ports.includes(port)) ports.push(port);
  });
  if (ports.length > 20) throw new Error('一次最多管理 20 个端口。');
  return ports;
}

function parseFirewallProtocolInput() {
  const input = document.getElementById('firewall-protocol-input');
  const value = String(input?.value || 'BOTH').toUpperCase();
  if (value === 'BOTH') return ['TCP', 'UDP'];
  if (value === 'TCP' || value === 'UDP') return [value];
  throw new Error(`无效协议：${value}`);
}

function parsePortBindingInput() {
  const input = document.getElementById('port-binding-input');
  const raw = String(input?.value || '').trim();
  if (!raw) return [];
  const ports = [];
  raw.split(/[\s,;]+/).forEach((part) => {
    if (!part) return;
    const port = Number(part);
    if (!Number.isInteger(port) || port < 1 || port > 65535) {
      throw new Error(`无效端口：${part}`);
    }
    if (!ports.includes(port)) ports.push(port);
  });
  if (ports.length > 20) throw new Error('一次最多管理 20 个端口。');
  return ports;
}

function parseRemoteAddressInput(id) {
  const input = document.getElementById(id);
  const raw = String(input?.value || '').trim();
  if (!raw) throw new Error('请输入允许来源 IP 或 CIDR，不能使用 Any。');
  const items = [];
  raw.split(/[\s,;]+/).forEach((part) => {
    const value = String(part || '').trim();
    if (!value) return;
    if (value.toLowerCase() === 'any') throw new Error('不允许使用 Any，请填写具体 IP 或 CIDR。');
    if (!items.includes(value)) items.push(value);
  });
  if (!items.length) throw new Error('请输入允许来源 IP 或 CIDR。');
  if (items.length > 20) throw new Error('一次最多管理 20 个来源地址。');
  return items;
}

function renderPortBindingStatus(item) {
  const root = document.getElementById('port-binding-status');
  if (!root) return;
  portBindingStatusCache = item || {};
  const signature = JSON.stringify(item || {});
  if (signature === portBindingStatusSignature) return;
  portBindingStatusSignature = signature;
  const portproxy = Array.isArray(item?.portproxy) ? item.portproxy : [];
  const listeners = Array.isArray(item?.listeners) ? item.listeners : [];
  const udpEndpoints = Array.isArray(item?.udp_endpoints) ? item.udp_endpoints : [];
  const ports = Array.from(new Set([
    ...portproxy.map((row) => Number(row.listen_port)).filter(Boolean),
  ])).sort((a, b) => a - b);

  if (!ports.length) {
    root.innerHTML = '<div class="auth-empty">还没有本工具创建的 0.0.0.0 端口绑定。</div>';
    return;
  }

  root.innerHTML = `
    <div class="firewall-rule-grid">
      ${ports.map((port) => {
        const proxy = portproxy.find((row) => Number(row.listen_port) === port);
        const portListeners = listeners.filter((row) => Number(row.local_port) === port);
        const udpPortEndpoints = udpEndpoints.filter((row) => Number(row.local_port) === port);
        const backendOk = !!proxy?.backend_ok;
        const source = proxy
          ? `${firewallEscape(proxy.listen_address)}:${firewallEscape(proxy.listen_port)} -> ${firewallEscape(proxy.connect_address)}:${firewallEscape(proxy.connect_port)}`
          : '未创建 portproxy';
        const processText = portListeners.length
          ? portListeners.map((row) => `${firewallEscape(row.local_address)} · ${firewallEscape(row.process_name || row.owning_process || '-')}`).join('<br>')
          : '未检测到 TCP 监听';
        const warningText = backendOk
          ? '127.0.0.1 TCP 后端正常'
          : udpPortEndpoints.length
            ? '检测到 UDP 服务，TCP 绑定不适用'
            : '缺少 127.0.0.1 TCP 后端';
        return `
          <div class="firewall-rule-card ${backendOk ? 'is-ok' : 'is-warn'}">
            <div>
              <strong>TCP ${firewallEscape(port)}</strong>
              <div class="firewall-rule-meta">
                <code>${source}</code>
                <span>${processText}</span>
                <span class="${backendOk ? '' : 'is-warning'}">${warningText}</span>
              </div>
            </div>
            <div class="firewall-card-actions">
              <span class="na-mini-pill ${backendOk ? 'ok' : 'warn'}">${backendOk ? '已绑定' : '不适用'}</span>
              <button type="button" class="secondary" onclick="removePortBindings([${Number(port)}])">关闭</button>
            </div>
          </div>
        `;
      }).join('')}
    </div>
  `;
}

function renderIpHelperStatus(item) {
  ipHelperStatusCache = item || {};
  const signature = JSON.stringify(item || {});
  if (signature === ipHelperStatusSignature) return;
  ipHelperStatusSignature = signature;
  const running = !!item?.running;
  const status = firewallEscape(item?.status || 'Unknown');
  const statusText = `IP Helper ${running ? '运行中' : status}`;
  const root = document.getElementById('ip-helper-status');
  if (root) {
    root.className = `na-mini-pill ${running ? 'ok' : 'warn'}`;
    root.textContent = statusText;
  }
  // Prefer shared traffic-light helper so IP Helper is included in cli-indicator-states cache.
  if (typeof window.updateIndicator === 'function') {
    window.updateIndicator('ip-helper', running ? 'green' : 'red');
  } else {
    const indicator = document.getElementById('ip-helper-status-indicator');
    if (indicator) {
      indicator.className = `status-indicator-dot ${running ? 'green' : 'red'}`;
      indicator.title = statusText;
    }
  }
  const indicator = document.getElementById('ip-helper-status-indicator');
  if (indicator) indicator.title = statusText;
  const startBtn = document.getElementById('ip-helper-start-btn');
  const stopBtn = document.getElementById('ip-helper-stop-btn');
  const restartBtn = document.getElementById('ip-helper-restart-btn');
  if (startBtn && stopBtn) {
    startBtn.disabled = running;
    startBtn.style.opacity = running ? '0.5' : '1';
    stopBtn.disabled = !running;
    stopBtn.style.opacity = running ? '1' : '0.5';
  }
  // Restart only makes sense when the service is currently running.
  if (restartBtn) {
    restartBtn.disabled = !running;
    restartBtn.style.opacity = running ? '1' : '0.5';
  }
}

function renderFirewallAccessStatus(item) {
  const root = document.getElementById('firewall-access-status');
  if (!root) return;
  firewallStatusCache = item || {};
  const signature = JSON.stringify(item || {});
  if (signature === firewallStatusSignature) return;
  firewallStatusSignature = signature;
  const rules = Array.isArray(item?.rules) ? item.rules : [];
  if (!rules.length) {
    root.innerHTML = '<div class="auth-empty">输入端口后点击“检查端口”。</div>';
    return;
  }
  root.innerHTML = `
    <div class="firewall-rule-grid">
      ${rules.map((rule) => {
        const ok = !!rule.ok;
        const exists = !!rule.exists;
        const enabled = !!rule.enabled;
        const stateText = ok ? '已放行' : exists ? (enabled ? '规则需修复' : '规则已禁用') : '未放行';
        const protocol = firewallEscape(rule.protocol || 'TCP');
        const profile = exists ? firewallEscape(rule.profile || '-') : '-';
        const action = exists ? firewallEscape(rule.action || '-') : '-';
        const remote = exists ? firewallEscape(rule.remote_address || '-') : '-';
        return `
          <div class="firewall-rule-card ${ok ? 'is-ok' : 'is-warn'}">
            <div>
              <strong>${firewallEscape(rule.display_name || `${protocol} ${rule.port}`)}</strong>
              <div class="firewall-rule-meta">
                <code>${protocol} ${firewallEscape(rule.port || rule.local_port || '-')}</code>
                <span>${profile} · ${action}</span>
                <span>来源 ${remote}</span>
              </div>
            </div>
            <span class="na-mini-pill ${ok ? 'ok' : 'warn'}">${stateText}</span>
            ${exists ? `<button type="button" class="secondary" onclick="removeCustomFirewallPorts([${Number(rule.port)}], ['${protocol}'])">关闭</button>` : ''}
          </div>
        `;
      }).join('')}
    </div>
  `;
}

async function loadPortBindings(force = false) {
  try {
    if (!force && portBindingStatusCache) {
      renderPortBindingStatus(portBindingStatusCache);
      if (ipHelperStatusCache) renderIpHelperStatus(ipHelperStatusCache);
      return;
    }
    const res = await api('/api/port-bindings');
    renderPortBindingStatus(res.item || {});
    renderIpHelperStatus(res.ip_helper || {});
  } catch (err) {
    showMessage(err.message || '读取端口绑定失败。', true);
  }
}

async function loadIpHelperStatus(force = false) {
  try {
    if (!force && ipHelperStatusCache) {
      renderIpHelperStatus(ipHelperStatusCache);
      return;
    }
    const res = await api('/api/ip-helper');
    renderIpHelperStatus(res.item || {});
  } catch (err) {
    showMessage(err.message || '读取 IP Helper 状态失败。', true);
  }
}

async function setIpHelperService(action, button) {
  const nextAction = String(action || '').toLowerCase();
  if (nextAction !== 'start' && nextAction !== 'stop' && nextAction !== 'restart') {
    showMessage('无效的 IP Helper 操作。', true);
    return null;
  }
  const labelMap = { start: '启动中...', stop: '关闭中...', restart: '重启中...' };
  const titleMap = { start: '正在启动 IP Helper...', stop: '正在关闭 IP Helper...', restart: '正在重启 IP Helper...' };
  const msgMap = { start: '正在启动 IP Helper...', stop: '正在关闭 IP Helper...', restart: '正在重启 IP Helper...' };
  const label = labelMap[nextAction];
  const run = async () => {
    try {
      // Yellow working state goes through the same cache path as other control groups.
      if (typeof window.updateIndicator === 'function') {
        window.updateIndicator('ip-helper', 'yellow');
      }
      const indicator = document.getElementById('ip-helper-status-indicator');
      if (indicator) indicator.title = titleMap[nextAction];
      showMessage(msgMap[nextAction]);
      const res = await api('/api/ip-helper', 'POST', { action: nextAction, elevated: true });
      if (res?.message) showMessage(res.message);
      renderIpHelperStatus(res.ip_helper || {});
      renderPortBindingStatus(res.port_bindings || {});
      setTimeout(() => loadFirewallAccessPanel(true), res?.pending_elevation ? 5000 : 1200);
    } catch (err) {
      showMessage(err.message || '更新 IP Helper 失败。', true);
      setTimeout(() => loadFirewallAccessPanel(true), 1200);
    }
  };
  if (typeof withRuntimeAction === 'function') {
    return withRuntimeAction(button, label, run);
  }
  return run();
}

async function prefillTrustedRemoteAddress() {
  const input = document.getElementById('firewall-remote-input');
  if (input && !String(input.value || '').trim()) input.value = defaultTrustedRemoteAddresses;
}

async function enablePortBindings() {
  try {
    const ports = parsePortBindingInput();
    if (!ports.length) {
      showMessage('请输入要绑定的 TCP 端口。', true);
      return;
    }
    portBindingLastPorts = ports;
    showMessage('正在请求端口绑定...');
    const res = await api('/api/port-bindings/enable', 'POST', { ports, elevated: true });
    if (res?.message) showMessage(res.message);
    renderPortBindingStatus(res.item || {});
    if (res?.pending_elevation) {
      setTimeout(() => loadPortBindings(true), 5000);
    }
  } catch (err) {
    showMessage(err.message || '端口绑定失败。', true);
    if (portBindingLastPorts.length) {
      await loadPortBindings(true);
    }
  }
}

async function removePortBindings(explicitPorts) {
  try {
    const ports = Array.isArray(explicitPorts) ? explicitPorts : parsePortBindingInput();
    if (!ports.length) {
      showMessage('请输入要关闭绑定的 TCP 端口。', true);
      return;
    }
    portBindingLastPorts = ports;
    showMessage('正在关闭端口绑定...');
    const res = await api('/api/port-bindings/remove', 'POST', { ports, elevated: true });
    if (res?.message) showMessage(res.message);
    renderPortBindingStatus(res.item || {});
    if (res?.pending_elevation) {
      setTimeout(() => loadPortBindings(true), 5000);
    }
  } catch (err) {
    showMessage(err.message || '关闭端口绑定失败。', true);
    await loadPortBindings(true);
  }
}

async function checkCustomFirewallPorts() {
  try {
    const ports = parseFirewallPortInput();
    if (!ports.length) {
      showMessage('请输入要检查的端口。', true);
      return;
    }
    firewallAccessLastPorts = ports;
    const protocols = parseFirewallProtocolInput();
    const query = [
      ...ports.map((port) => `ports=${encodeURIComponent(port)}`),
      ...protocols.map((protocol) => `protocols=${encodeURIComponent(protocol)}`),
    ].join('&');
    const res = await api(`/api/firewall-access?${query}`);
    renderFirewallAccessStatus(res.item || {});
  } catch (err) {
    showMessage(err.message || '检查端口失败。', true);
  }
}

async function allowCustomFirewallPorts() {
  try {
    const ports = parseFirewallPortInput();
    if (!ports.length) {
      showMessage('请输入要放行的端口。', true);
      return;
    }
    firewallAccessLastPorts = ports;
    const protocols = parseFirewallProtocolInput();
    const remote_addresses = parseRemoteAddressInput('firewall-remote-input');
    showMessage('正在请求防火墙端口放行...');
    const res = await api('/api/firewall-access/allow', 'POST', { ports, protocols, remote_addresses, elevated: true });
    if (res?.message) showMessage(res.message);
    renderFirewallAccessStatus(res.firewall || {});
    if (res?.pending_elevation) {
      setTimeout(() => checkCustomFirewallPorts(), 5000);
    }
  } catch (err) {
    showMessage(err.message || '端口放行失败。', true);
    if (firewallAccessLastPorts.length) {
      await checkCustomFirewallPorts();
    }
  }
}

async function removeCustomFirewallPorts(explicitPorts, explicitProtocols) {
  try {
    const ports = Array.isArray(explicitPorts) ? explicitPorts : parseFirewallPortInput();
    if (!ports.length) {
      showMessage('请输入要关闭放行的端口。', true);
      return;
    }
    firewallAccessLastPorts = ports;
    const protocols = Array.isArray(explicitProtocols) ? explicitProtocols : parseFirewallProtocolInput();
    showMessage('正在关闭防火墙端口放行...');
    const res = await api('/api/firewall-access/remove', 'POST', { ports, protocols, elevated: true });
    if (res?.message) showMessage(res.message);
    renderFirewallAccessStatus(res.firewall || {});
    if (res?.pending_elevation) {
      setTimeout(() => checkCustomFirewallPorts(), 5000);
    }
  } catch (err) {
    showMessage(err.message || '关闭端口放行失败。', true);
    if (firewallAccessLastPorts.length) {
      await checkCustomFirewallPorts();
    }
  }
}

async function loadFirewallAccessPanel(force = false) {
  if (firewallAccessLoaded && !force) {
    if (portBindingStatusCache) renderPortBindingStatus(portBindingStatusCache);
    if (firewallStatusCache) renderFirewallAccessStatus(firewallStatusCache);
    return;
  }
  const root = document.getElementById('firewall-access-status');
  if (root && !firewallStatusCache) root.innerHTML = '<div class="auth-empty">输入端口后点击“检查端口”。</div>';
  const bindingRoot = document.getElementById('port-binding-status');
  if (bindingRoot && !portBindingStatusCache) bindingRoot.innerHTML = '<div class="auth-empty">点击“刷新”读取本工具创建的端口绑定。</div>';
  firewallAccessLoaded = true;
  await prefillTrustedRemoteAddress();
  if (force) {
    await loadPortBindings(true);
    await loadIpHelperStatus(true);
  } else if (portBindingStatusCache) {
    renderPortBindingStatus(portBindingStatusCache);
    if (ipHelperStatusCache) renderIpHelperStatus(ipHelperStatusCache);
  } else {
    await loadIpHelperStatus(false);
  }
}
