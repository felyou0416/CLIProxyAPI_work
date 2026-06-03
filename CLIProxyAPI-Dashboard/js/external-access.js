let externalAccessLoaded = false;
let externalAccessLastPorts = [];
let externalAccessStatusCache = null;
let externalAccessStatusSignature = '';

function externalEscape(value) {
  return String(value ?? '')
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#39;');
}

function parseExternalPortInput() {
  const input = document.getElementById('external-port-input');
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

function parseExternalProtocolInput() {
  const input = document.getElementById('external-protocol-input');
  const value = String(input?.value || 'TCP').toUpperCase();
  if (value === 'BOTH') return ['TCP', 'UDP'];
  if (value === 'TCP' || value === 'UDP') return [value];
  throw new Error(`无效协议：${value}`);
}

function parseExternalRemoteInput() {
  const input = document.getElementById('external-remote-input');
  const raw = String(input?.value || '').trim();
  if (!raw) throw new Error('请输入允许来源 IP 或 CIDR。');
  const items = [];
  raw.split(/[\s,;]+/).forEach((part) => {
    const value = String(part || '').trim();
    if (!value) return;
    const lowered = value.toLowerCase();
    if (lowered === 'any' || lowered === 'localsubnet') {
      throw new Error('不能使用 Any 或 LocalSubnet，请填写具体外部 IP 或 CIDR。');
    }
    if (!items.includes(value)) items.push(value);
  });
  if (!items.length) throw new Error('请输入允许来源 IP 或 CIDR。');
  if (items.length > 20) throw new Error('一次最多管理 20 个来源地址。');
  return items;
}

function renderExternalAccessStatus(item) {
  const root = document.getElementById('external-access-status');
  if (!root) return;
  externalAccessStatusCache = item || {};
  const signature = JSON.stringify(item || {});
  if (signature === externalAccessStatusSignature) return;
  externalAccessStatusSignature = signature;
  const rules = Array.isArray(item?.rules) ? item.rules : [];
  if (!rules.length) {
    root.innerHTML = '<div class="auth-empty">输入端口后点击“检查规则”。</div>';
    return;
  }
  root.innerHTML = `
    <div class="external-rule-grid">
      ${rules.map((rule) => {
        const ok = !!rule.ok;
        const exists = !!rule.exists;
        const enabled = !!rule.enabled;
        const stateText = ok ? '已放行' : exists ? (enabled ? '规则需修复' : '规则已禁用') : '未放行';
        const protocol = externalEscape(rule.protocol || 'TCP');
        const profile = exists ? externalEscape(rule.profile || '-') : '-';
        const action = exists ? externalEscape(rule.action || '-') : '-';
        const remote = exists ? externalEscape(rule.remote_address || '-') : '-';
        return `
          <div class="external-rule-card ${ok ? 'is-ok' : 'is-warn'}">
            <div>
              <strong>${externalEscape(rule.display_name || `${protocol} ${rule.port}`)}</strong>
              <div class="external-rule-meta">
                <code>${protocol} ${externalEscape(rule.port || rule.local_port || '-')}</code>
                <span>${profile} · ${action}</span>
                <span>来源 ${remote}</span>
              </div>
            </div>
            <div class="external-card-actions">
              <span class="na-mini-pill ${ok ? 'ok' : 'warn'}">${stateText}</span>
              ${exists ? `<button type="button" class="secondary" onclick="removeExternalAccessRules([${Number(rule.port)}], ['${protocol}'])">关闭</button>` : ''}
            </div>
          </div>
        `;
      }).join('')}
    </div>
  `;
}

async function checkExternalAccessRules() {
  try {
    const ports = parseExternalPortInput();
    if (!ports.length) {
      showMessage('请输入要检查的端口。', true);
      return;
    }
    externalAccessLastPorts = ports;
    const protocols = parseExternalProtocolInput();
    const query = [
      ...ports.map((port) => `ports=${encodeURIComponent(port)}`),
      ...protocols.map((protocol) => `protocols=${encodeURIComponent(protocol)}`),
    ].join('&');
    const res = await api(`/api/external-access?${query}`);
    renderExternalAccessStatus(res.item || {});
  } catch (err) {
    showMessage(err.message || '检查外部 IP 放行失败。', true);
  }
}

async function allowExternalAccessRules() {
  try {
    const ports = parseExternalPortInput();
    if (!ports.length) {
      showMessage('请输入要放行的端口。', true);
      return;
    }
    externalAccessLastPorts = ports;
    const protocols = parseExternalProtocolInput();
    const remote_addresses = parseExternalRemoteInput();
    showMessage('正在请求外部 IP 放行...');
    const res = await api('/api/external-access/allow', 'POST', { ports, protocols, remote_addresses, elevated: true });
    if (res?.message) showMessage(res.message);
    renderExternalAccessStatus(res.firewall || {});
    if (res?.pending_elevation) {
      setTimeout(() => checkExternalAccessRules(), 5000);
    }
  } catch (err) {
    showMessage(err.message || '外部 IP 放行失败。', true);
    if (externalAccessLastPorts.length) {
      await checkExternalAccessRules();
    }
  }
}

async function removeExternalAccessRules(explicitPorts, explicitProtocols) {
  try {
    const ports = Array.isArray(explicitPorts) ? explicitPorts : parseExternalPortInput();
    if (!ports.length) {
      showMessage('请输入要关闭放行的端口。', true);
      return;
    }
    externalAccessLastPorts = ports;
    const protocols = Array.isArray(explicitProtocols) ? explicitProtocols : parseExternalProtocolInput();
    showMessage('正在关闭外部 IP 放行...');
    const res = await api('/api/external-access/remove', 'POST', { ports, protocols, elevated: true });
    if (res?.message) showMessage(res.message);
    renderExternalAccessStatus(res.firewall || {});
    if (res?.pending_elevation) {
      setTimeout(() => checkExternalAccessRules(), 5000);
    }
  } catch (err) {
    showMessage(err.message || '关闭外部 IP 放行失败。', true);
    if (externalAccessLastPorts.length) {
      await checkExternalAccessRules();
    }
  }
}

async function loadExternalAccessPanel(force = false) {
  const root = document.getElementById('external-access-status');
  if (root && !externalAccessStatusCache) {
    root.innerHTML = '<div class="auth-empty">输入端口后点击“检查规则”。</div>';
  }
  if (!force && externalAccessLoaded) {
    if (externalAccessStatusCache) renderExternalAccessStatus(externalAccessStatusCache);
    return;
  }
  externalAccessLoaded = true;
  if (force && externalAccessLastPorts.length) {
    await checkExternalAccessRules();
  }
}
