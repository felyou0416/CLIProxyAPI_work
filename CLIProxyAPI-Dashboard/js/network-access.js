/**
 * Network Access Panel
 *
 * Provides a unified view for sharing the proxy with other computers.
 * Combines exposure mode control, connection info, and config snippets
 * so the admin can quickly share access with external users.
 */

let networkAccessLoaded = false;
let networkAccessData = null;

function naEscape(value) {
  return String(value ?? '')
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#39;');
}

function naCopyToClipboard(text, label) {
  navigator.clipboard.writeText(text).then(
    () => showMessage(`${label || '内容'}已复制到剪贴板`),
    () => showMessage('复制失败，请手动复制', true)
  );
}

function naConfigSnippet(type, baseUrl, apiKey) {
  const safeParse = (url) => {
    try { return new URL(url); } catch { return null; }
  };
  const parsed = safeParse(baseUrl);
  const host = parsed ? parsed.hostname : '127.0.0.1';
  const port = parsed ? parsed.port || '8317' : '8317';

  switch (type) {
    case 'claude-code':
      return `# Claude Code
export OPENAI_API_KEY="${apiKey}"
export OPENAI_BASE_URL="${baseUrl}/v1"

# 或在 Claude Code settings.json 中设置:
# "apiProvider": "custom"
# "apiBaseUrl": "${baseUrl}"
# "apiKey": "${apiKey}"`;

    case 'cursor':
      return `# Cursor Settings → Models → OpenAI API Key
# API Key: ${apiKey}
# Base URL: ${baseUrl}/v1
#
# 然后在模型列表中选择需要使用的模型`;

    case 'openai-python':
      return `from openai import OpenAI

client = OpenAI(
    api_key="${apiKey}",
    base_url="${baseUrl}/v1",
)

response = client.chat.completions.create(
    model="auto",  # 使用聚合模型
    messages=[{"role": "user", "content": "Hello!"}],
)
print(response.choices[0].message.content)`;

    case 'openai-curl':
      return `curl ${baseUrl}/v1/chat/completions \\
  -H "Authorization: Bearer ${apiKey}" \\
  -H "Content-Type: application/json" \\
  -d '{
    "model": "auto",
    "messages": [{"role": "user", "content": "Hello!"}]
  }'`;

    case 'env-vars':
      return `# 环境变量配置 (适用于大多数 OpenAI 兼容客户端)
export OPENAI_API_KEY="${apiKey}"
export OPENAI_BASE_URL="${baseUrl}/v1"

# Windows PowerShell:
$env:OPENAI_API_KEY = "${apiKey}"
$env:OPENAI_BASE_URL = "${baseUrl}/v1"

# Windows CMD:
set OPENAI_API_KEY=${apiKey}
set OPENAI_BASE_URL=${baseUrl}/v1`;

    case 'claude-api':
      return `curl ${baseUrl}/v1/messages?beta=true \\
  -H "x-api-key: ${apiKey}" \\
  -H "Content-Type: application/json" \\
  -H "anthropic-version: 2023-06-01" \\
  -d '{
    "model": "auto",
    "max_tokens": 256,
    "messages": [{"role": "user", "content": "Hello!"}]
  }'`;

    default:
      return '';
  }
}

function naIpKindText(kind) {
  const labels = {
    lan: '校园网 / 局域网',
    tun: 'TUN 虚拟网卡',
    carrier: '运营商内网',
    public: '公网或其他',
  };
  return labels[kind] || '未知网络';
}

function naPickRecommendedIp(d) {
  const recommended = d?.recommended_external_ip || null;
  if (recommended?.ip) return recommended;
  const ips = Array.isArray(d?.network_ips) ? d.network_ips : [];
  return ips.find(item => item?.recommended_for_lan) || ips[0] || (d?.lan_ip ? {
    ip: d.lan_ip,
    kind: String(d.lan_ip).startsWith('198.18.') || String(d.lan_ip).startsWith('198.19.') ? 'tun' : 'lan',
    label: '当前检测地址',
    base_url: `http://${d.lan_ip}:8317`,
    dashboard_url: `http://${d.lan_ip}:8765`,
  } : null);
}

function naRenderIpChoices(d, exposureEnabled) {
  const ips = Array.isArray(d?.network_ips) ? d.network_ips : [];
  const recommended = naPickRecommendedIp(d);
  const rows = ips.length ? ips : (recommended ? [recommended] : []);
  if (!rows.length) {
    return '<div class="na-ip-empty">暂未检测到可用于外部访问的 IPv4 地址。</div>';
  }
  return rows.map(item => {
    const isRecommended = recommended?.ip && item.ip === recommended.ip;
    const isTun = item.kind === 'tun' || item.is_tun;
    const baseUrl = item.base_url || `http://${item.ip}:8317`;
    const desc = isTun
      ? 'TUN/虚拟网络里的人用。同一个校园网的人通常不能直接用这个地址。'
      : '同一个校园网或同一路由器下的设备优先用这个地址。';
    return `
      <div class="na-ip-choice ${isRecommended ? 'recommended' : ''} ${isTun ? 'is-tun' : ''}">
        <div class="na-ip-choice-main">
          <div class="na-ip-choice-top">
            <code>${naEscape(baseUrl)}</code>
            ${isRecommended ? '<span class="na-mini-pill ok">推荐外部使用</span>' : ''}
            ${isTun ? '<span class="na-mini-pill warn">TUN</span>' : '<span class="na-mini-pill">校园网</span>'}
          </div>
          <div class="na-ip-choice-desc">${desc}</div>
        </div>
        <button class="secondary na-copy-btn" onclick="naCopyToClipboard('${baseUrl}', '推荐地址')">复制</button>
      </div>
    `;
  }).join('');
}

function naRenderFirewallPanel(d) {
  const firewall = d?.firewall || {};
  const rules = Array.isArray(firewall.rules) ? firewall.rules : [];
  const supported = firewall.supported !== false;
  const allOk = !!firewall.all_ok;
  const rows = rules.length ? rules : [
    { id: 'dashboard', display_name: 'CLIProxyAPI Dashboard TCP 8765', port: 8765, ok: false },
    { id: 'proxy', display_name: 'CLIProxyAPI Proxy TCP 8317', port: 8317, ok: false },
  ];

  return `
    <div class="na-firewall-panel">
      <div class="na-firewall-head">
        <div>
          <h3 class="na-section-title">防火墙端口放行</h3>
          <p>局域网访问需要 Windows 防火墙允许入站 TCP 端口。这里只管理本项目需要的 <code>8765</code> 和 <code>8317</code>。</p>
        </div>
        <button type="button" class="secondary na-firewall-allow-btn" onclick="allowNetworkFirewallPorts()" ${!supported ? 'disabled' : ''}>
          ${allOk ? '重新检查/修复规则' : '一键放行端口'}
        </button>
      </div>
      <div class="na-firewall-rules">
        ${rows.map(rule => {
          const ok = !!rule.ok;
          const enabled = !!rule.enabled;
          const exists = !!rule.exists;
          const stateText = ok ? '已放行' : exists ? (enabled ? '规则需修复' : '规则已禁用') : '未放行';
          return `
            <div class="na-firewall-rule ${ok ? 'is-ok' : 'is-warn'}">
              <div>
                <strong>${naEscape(rule.display_name || rule.id || 'Firewall rule')}</strong>
                <p>TCP ${naEscape(rule.port || rule.local_port || '-')} · ${naEscape(rule.profile || 'Any')} · ${naEscape(rule.action || 'Allow')}</p>
              </div>
              <span class="na-mini-pill ${ok ? 'ok' : 'warn'}">${stateText}</span>
            </div>
          `;
        }).join('')}
      </div>
      <div class="na-firewall-help">
        ${supported
          ? '如果弹出管理员授权，请确认后再点刷新。长期暴露建议只把代理端口 8317 开给可信网段。'
          : '当前系统不支持从面板管理 Windows 防火墙。'}
      </div>
    </div>
  `;
}

function renderNetworkAccessPanel() {
  const container = document.getElementById('network-access-content');
  if (!container) return;

  const d = networkAccessData;
  if (!d) {
    container.innerHTML = '<div class="metric-empty">加载中...</div>';
    return;
  }

  const exposureEnabled = d.exposure_enabled;
  const proxyRunning = d.proxy_running;
  const lanIp = d.lan_ip;
  const baseUrlLocal = d.base_url_local || 'http://127.0.0.1:8317';
  const baseUrlLan = d.base_url_lan;
  const adminKey = d.admin_api_key || 'cliproxyapi';
  const dashboardUrl = d.dashboard_url;
  const dashboardRemoteAccessible = !!d.dashboard_remote_accessible;
  const dashboardPort = d.dashboard_port || '8765';
  const vkTotal = d.virtual_keys_total || 0;
  const vkActive = d.virtual_keys_active || 0;
  const recommendedIp = naPickRecommendedIp(d);
  const recommendedUrl = recommendedIp?.base_url || baseUrlLan || baseUrlLocal;
  const recommendedKind = recommendedIp?.kind || '';
  const recommendedIsTun = recommendedKind === 'tun';
  const recommendedHint = exposureEnabled && proxyRunning
    ? recommendedIsTun
      ? '当前推荐地址是 TUN 虚拟网卡地址；只有接入同一虚拟网络的人能用。校园网同学应改用真实校园网 IP。'
      : '把这个地址填到对方客户端的 Base URL 里；同校园网设备优先用它。'
    : '当前仅本机可用。开启网络接入并允许防火墙后，面板会推荐外部设备该用的地址。';

  const activeUrl = exposureEnabled && baseUrlLan ? baseUrlLan : baseUrlLocal;
  const shareableUrl = exposureEnabled && baseUrlLan ? baseUrlLan : null;

  const exposureStatusClass = exposureEnabled ? 'na-status-enabled' : 'na-status-disabled';
  const proxyStatusClass = proxyRunning ? 'na-status-enabled' : 'na-status-disabled';

  container.innerHTML = `
    <div class="na-status-banner ${exposureEnabled && proxyRunning ? 'na-banner-active' : 'na-banner-inactive'}">
      <div class="na-banner-icon">${exposureEnabled && proxyRunning ? '🌐' : '🔒'}</div>
      <div class="na-banner-info">
        <div class="na-banner-title">${
          exposureEnabled && proxyRunning
            ? '网络接入已开启'
            : exposureEnabled && !proxyRunning
            ? '暴露模式已开启，但代理未运行'
            : '仅本机访问'
        }</div>
        <div class="na-banner-desc">${
          exposureEnabled && proxyRunning
            ? `外部设备优先使用 <code>${naEscape(recommendedUrl)}</code>；${naEscape(recommendedHint)}`
            : exposureEnabled && !proxyRunning
            ? '请先启动 CLIProxyAPI 代理服务'
            : '当前代理仅绑定 127.0.0.1，只有本机可以访问。开启暴露模式后，局域网内其他设备可通过 LAN IP 连接。'
        }</div>
      </div>
      <div class="na-banner-actions">
        ${!exposureEnabled
          ? '<button onclick="enableExposureMode()" class="na-enable-btn">🌐 开启网络接入</button>'
          : '<button onclick="disableExposureMode()" class="secondary na-disable-btn">🔒 关闭网络接入</button>'
        }
        ${!proxyRunning
          ? '<button onclick="startProxy()" class="secondary">▶ 启动代理</button>'
          : ''
        }
      </div>
    </div>

    <div class="na-info-grid">
      <div class="na-info-card">
        <div class="na-card-icon">📡</div>
        <div class="na-card-label">代理状态</div>
        <div class="na-card-value">
          <span class="na-dot ${proxyStatusClass}"></span>
          ${proxyRunning ? '运行中' : '未运行'}
        </div>
      </div>
      <div class="na-info-card">
        <div class="na-card-icon">🌍</div>
        <div class="na-card-label">暴露模式</div>
        <div class="na-card-value">
          <span class="na-dot ${exposureStatusClass}"></span>
          ${exposureEnabled ? '已开启' : '已关闭'}
        </div>
      </div>
      <div class="na-info-card">
        <div class="na-card-icon">🖧</div>
        <div class="na-card-label">推荐外部 IP</div>
        <div class="na-card-value">${recommendedIp?.ip || lanIp || '未检测到'}</div>
      </div>
      <div class="na-info-card">
        <div class="na-card-icon">🔑</div>
        <div class="na-card-label">虚拟密钥</div>
        <div class="na-card-value">${vkActive} 个活跃 / ${vkTotal} 个总计</div>
      </div>
    </div>

    <div class="na-connection-section">
      <h3 class="na-section-title">📋 连接信息</h3>
      <div class="na-recommend-box ${recommendedIsTun ? 'is-tun' : ''}">
        <div>
          <div class="na-recommend-label">现在外部设备优先填这个</div>
          <code>${naEscape(recommendedUrl)}</code>
          <p>${naEscape(recommendedHint)}</p>
        </div>
        <button class="secondary na-copy-btn" onclick="naCopyToClipboard('${recommendedUrl}', '推荐外部地址')">复制推荐地址</button>
      </div>
      <div class="na-connection-grid">
        <div class="na-conn-row">
          <span class="na-conn-label">本机地址</span>
          <code class="na-conn-value">${naEscape(baseUrlLocal)}</code>
          <button class="secondary na-copy-btn" onclick="naCopyToClipboard('${baseUrlLocal}', '本机地址')">复制</button>
        </div>
        ${baseUrlLan ? `
        <div class="na-conn-row ${exposureEnabled ? 'na-conn-highlight' : ''}">
          <span class="na-conn-label">局域网地址</span>
          <code class="na-conn-value">${naEscape(baseUrlLan)}</code>
          <button class="secondary na-copy-btn" onclick="naCopyToClipboard('${baseUrlLan}', '局域网地址')">复制</button>
        </div>` : ''}
        <div class="na-conn-row">
          <span class="na-conn-label">API Key (管理员)</span>
          <code class="na-conn-value">${naEscape(adminKey)}</code>
          <button class="secondary na-copy-btn" onclick="naCopyToClipboard('${adminKey}', 'API Key')">复制</button>
        </div>
        ${dashboardUrl ? `
        <div class="na-conn-row">
          <span class="na-conn-label">Dashboard 面板</span>
          <code class="na-conn-value">${naEscape(dashboardUrl)}</code>
          <button class="secondary na-copy-btn" onclick="naCopyToClipboard('${dashboardUrl}', 'Dashboard URL')">复制</button>
        </div>` : `
        <div class="na-conn-row">
          <span class="na-conn-label">Dashboard 面板</span>
          <code class="na-conn-value">仅本机可访问 http://127.0.0.1:${naEscape(dashboardPort)}</code>
        </div>`}
      </div>
      ${!dashboardRemoteAccessible ? `
      <div class="na-firewall-note">
        <div class="na-note-icon">⚠️</div>
        <div class="na-note-content">
          <strong>Dashboard 当前没有对局域网开放</strong>
          <p>请用新版启动脚本重启 Dashboard，或设置 <code>CLIPROXYAPI_DASHBOARD_HOST=0.0.0.0</code> 后重新启动。代理地址和 Dashboard 地址是两个不同端口，代理用 <code>8317</code>，面板用 <code>${naEscape(dashboardPort)}</code>。</p>
        </div>
      </div>` : ''}
    </div>

    ${naRenderFirewallPanel(d)}

    <div class="na-guide-section">
      <h3 class="na-section-title">🧭 该用哪个 IP</h3>
      <div class="na-path-grid">
        <div class="na-path-card">
          <div class="na-path-title">自己这台电脑用</div>
          <code>${naEscape(baseUrlLocal)}</code>
          <p>永远用本机地址，最稳，也不会暴露给别人。</p>
        </div>
        <div class="na-path-card">
          <div class="na-path-title">同一个校园网的人用</div>
          <code>${naEscape(recommendedIsTun ? '优先找 10.x / 172.16-31.x / 192.168.x 的地址' : recommendedUrl)}</code>
          <p>需要开启网络接入、防火墙放行 8317，并且校园网没有设备隔离。</p>
        </div>
        <div class="na-path-card">
          <div class="na-path-title">TUN / 虚拟网络的人用</div>
          <code>${naEscape((Array.isArray(d.network_ips) ? d.network_ips.find(item => item.kind === 'tun')?.base_url : '') || '198.18.x.x 地址')}</code>
          <p>只有接入同一虚拟网络的人能用；普通校园网用户一般访问不到。</p>
        </div>
      </div>
      <div class="na-ip-list">
        <div class="na-ip-list-title">实时检测到的可用地址</div>
        ${naRenderIpChoices(d, exposureEnabled)}
      </div>
    </div>

    <div class="na-snippets-section">
      <h3 class="na-section-title">🔧 配置代码片段</h3>
      <p class="na-snippets-desc">选择一种方式，复制配置代码给其他用户使用。${
        exposureEnabled && baseUrlLan
          ? '当前使用局域网地址。'
          : '当前使用本机地址，开启暴露模式后会自动切换为局域网地址。'
      }</p>
      <div class="na-snippet-tabs">
        <button class="na-snippet-tab active" onclick="naShowSnippet('env-vars', this)">环境变量</button>
        <button class="na-snippet-tab" onclick="naShowSnippet('claude-code', this)">Claude Code</button>
        <button class="na-snippet-tab" onclick="naShowSnippet('cursor', this)">Cursor</button>
        <button class="na-snippet-tab" onclick="naShowSnippet('openai-python', this)">Python SDK</button>
        <button class="na-snippet-tab" onclick="naShowSnippet('openai-curl', this)">cURL (OpenAI)</button>
        <button class="na-snippet-tab" onclick="naShowSnippet('claude-api', this)">cURL (Claude)</button>
      </div>
      <div class="na-snippet-content">
        <div class="na-snippet-actions">
          <button class="secondary na-copy-btn" id="na-snippet-copy-btn" onclick="naCopyCurrentSnippet()">📋 复制代码</button>
        </div>
        <pre id="na-snippet-code" class="na-snippet-code">${naEscape(naConfigSnippet('env-vars', activeUrl, adminKey))}</pre>
      </div>
    </div>

    <div class="na-guide-section">
      <h3 class="na-section-title">📖 给别人使用的步骤</h3>
      <div class="na-guide-grid">
        <div class="na-guide-card">
          <div class="na-guide-step">1</div>
          <div class="na-guide-title">开启网络接入</div>
          <div class="na-guide-desc">点击上方按钮后，代理会允许外部设备访问。Windows 弹防火墙时要允许。</div>
        </div>
        <div class="na-guide-card">
          <div class="na-guide-step">2</div>
          <div class="na-guide-title">复制推荐地址</div>
          <div class="na-guide-desc">同校园网的人用“推荐外部地址”；TUN 用户才用 198.18.x.x 这类虚拟网卡地址。</div>
        </div>
        <div class="na-guide-card">
          <div class="na-guide-step">3</div>
          <div class="na-guide-title">给对方密钥</div>
          <div class="na-guide-desc">建议在<a href="#" onclick="showSection('virtual-keys'); loadVirtualKeysPanel(true); return false;">密钥管理</a>里建分发密钥，不要直接给管理员 Key。</div>
        </div>
        <div class="na-guide-card">
          <div class="na-guide-step">4</div>
          <div class="na-guide-title">连不上先查三件事</div>
          <div class="na-guide-desc">确认同网络、校园网没隔离、防火墙放行 8317。再去<a href="#" onclick="showSection('requests'); return false;">日志</a>页看有没有进来。</div>
        </div>
      </div>
    </div>

    ${!exposureEnabled ? `
    <div class="na-firewall-note">
      <div class="na-note-icon">⚠️</div>
      <div class="na-note-content">
        <strong>防火墙提示</strong>
        <p>开启网络接入后，Windows 防火墙可能会弹出确认对话框，请允许 <code>cli-proxy-api.exe</code> 通过防火墙。如果其他设备无法连接，请检查防火墙规则是否放行了端口 <code>8317</code>。</p>
      </div>
    </div>` : ''}
  `;

  // Initialize snippet to env-vars
  currentSnippetType = 'env-vars';
}

let currentSnippetType = 'env-vars';

function naShowSnippet(type, btn) {
  currentSnippetType = type;
  const d = networkAccessData;
  if (!d) return;

  const activeUrl = d.exposure_enabled && d.base_url_lan ? d.base_url_lan : d.base_url_local;
  const adminKey = d.admin_api_key || 'cliproxyapi';
  const code = naConfigSnippet(type, activeUrl, adminKey);

  const codeEl = document.getElementById('na-snippet-code');
  if (codeEl) codeEl.textContent = code;

  document.querySelectorAll('.na-snippet-tab').forEach(t => t.classList.remove('active'));
  if (btn) btn.classList.add('active');
}

function naCopyCurrentSnippet() {
  const codeEl = document.getElementById('na-snippet-code');
  if (codeEl) {
    naCopyToClipboard(codeEl.textContent, '配置代码');
  }
}

async function allowNetworkFirewallPorts() {
  try {
    showMessage('正在请求防火墙端口放行...');
    const result = await api('/api/network-access/firewall/allow', 'POST', { elevated: true });
    if (result?.message) showMessage(result.message);
    await loadNetworkAccessPanel(true);
    if (result?.pending_elevation) {
      setTimeout(() => loadNetworkAccessPanel(true), 5000);
    }
  } catch (err) {
    showMessage(err.message || '防火墙端口放行失败。请用管理员身份运行 Dashboard 后重试。', true);
    await loadNetworkAccessPanel(true);
  }
}
window.allowNetworkFirewallPorts = allowNetworkFirewallPorts;

async function loadNetworkAccessPanel(force = false) {
  if (networkAccessLoaded && !force) return;
  const container = document.getElementById('network-access-content');
  if (container) container.innerHTML = '<div class="metric-empty">加载中...</div>';
  try {
    const data = await api('/api/network-access');
    networkAccessData = data.item || {};
    renderNetworkAccessPanel();
    networkAccessLoaded = true;
  } catch (err) {
    if (container) container.innerHTML = `<div class="metric-empty">${naEscape(err.message || '加载失败')}</div>`;
  }
}
