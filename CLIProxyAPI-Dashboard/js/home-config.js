/* Home Control Plane Configuration */

async function loadHomeConfig() {
  const content = document.getElementById('home-config-content');
  if (!content) return;
  try {
    const data = await api('/api/home-config');
    renderHomeConfig(data.item || {});
  } catch (e) {
    content.innerHTML = `<div class="metric-empty">${(e.message || 'load failed').replaceAll('<', '&lt;')}</div>`;
  }
}

function renderHomeConfig(d) {
  const content = document.getElementById('home-config-content');
  content.innerHTML = `<div class="config-section">
    <fieldset><legend>Home 控制面连接</legend>
      <div class="tool-desc-zh">通过 CLIProxyAPI Home 控制面实现集群管理、远程配置下发和用量聚合。JWT 由 Home 服务器签发 (POST /v0/management/certificates/clients)。</div>
      <div class="config-row">
        <label class="config-label">HOME_JWT</label>
        <textarea id="home-jwt" rows="4" placeholder="${d.home_jwt_set ? '(已设置，留空保持不变)' : '粘贴 Home 控制面签发的 JWT'}" style="width:100%;max-width:500px"></textarea>
      </div>
      <div class="config-row">
        <label class="config-label">
          <input type="checkbox" id="home-disable-cluster" ${d.home_disable_cluster_discovery ? 'checked' : ''} />
          禁用集群发现
        </label>
        <span class="config-desc">禁止 CLUSTER NODES 发现，仅连接 JWT 中配置的地址。</span>
      </div>
    </fieldset>
  </div>`;
}

async function saveHomeConfig() {
  const item = {};
  const jwt = document.getElementById('home-jwt')?.value?.trim();
  if (jwt) item.home_jwt = jwt;
  item.home_disable_cluster_discovery = document.getElementById('home-disable-cluster')?.checked || false;

  try {
    const result = await api('/api/home-config', 'POST', { item });
    showMessage(result.message || 'Saved.');
  } catch (e) {
    showMessage(e.message, true);
  }
}
