/* Storage Backend Configuration */

let storageConfigData = {};

function _se(value) {
  return String(value ?? '')
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#39;');
}

async function loadStorageConfig() {
  const content = document.getElementById('storage-config-content');
  if (!content) return;
  try {
    const data = await api('/api/storage-config');
    storageConfigData = data.item || {};
    renderStorageConfig();
  } catch (e) {
    content.innerHTML = `<div class="metric-empty">${_se(e.message || 'load failed')}</div>`;
  }
}

function renderStorageConfig() {
  const content = document.getElementById('storage-config-content');
  const d = storageConfigData;
  content.innerHTML = `<div class="config-section">
    <fieldset><legend>Postgres 存储</legend>
      <div class="tool-desc-zh">设置 PGSTORE_DSN 即激活 Postgres 后端。格式：postgres://user:pass@host:5432/db</div>
      <div class="config-row">
        <label class="config-label">PGSTORE_DSN</label>
        <input type="text" id="pgstore-dsn" placeholder="${d.PGSTORE_DSN_set ? '(已设置)' : 'postgres://user:pass@host:5432/db'}" style="width:100%;max-width:400px" />
      </div>
      <div class="config-row">
        <label class="config-label">PGSTORE_SCHEMA</label>
        <input type="text" id="pgstore-schema" value="${_se(d.PGSTORE_SCHEMA || '')}" placeholder="public" />
      </div>
    </fieldset>

    <fieldset><legend>Git 存储</legend>
      <div class="tool-desc-zh">设置 GITSTORE_GIT_URL 即激活 Git 后端。用于版本化存储配置和认证文件。</div>
      <div class="config-row">
        <label class="config-label">GITSTORE_GIT_URL</label>
        <input type="text" id="gitstore-url" placeholder="${d.GITSTORE_GIT_URL_set ? '(已设置)' : 'https://github.com/user/repo.git'}" style="width:100%;max-width:400px" />
      </div>
      <div class="config-row">
        <label class="config-label">GITSTORE_GIT_USERNAME</label>
        <input type="text" id="gitstore-user" placeholder="${d.GITSTORE_GIT_USERNAME_set ? '(已设置)' : ''}" />
      </div>
      <div class="config-row">
        <label class="config-label">GITSTORE_GIT_TOKEN</label>
        <input type="password" id="gitstore-token" placeholder="${d.GITSTORE_GIT_TOKEN_set ? '(已设置)' : ''}" />
      </div>
      <div class="config-row">
        <label class="config-label">GITSTORE_GIT_BRANCH</label>
        <input type="text" id="gitstore-branch" placeholder="${d.GITSTORE_GIT_BRANCH_set ? '(已设置)' : 'main'}" />
      </div>
    </fieldset>

    <fieldset><legend>对象存储（S3 兼容）</legend>
      <div class="tool-desc-zh">设置 OBJECTSTORE_ENDPOINT 即激活对象存储后端。</div>
      <div class="config-row">
        <label class="config-label">OBJECTSTORE_ENDPOINT</label>
        <input type="text" id="objectstore-endpoint" placeholder="${d.OBJECTSTORE_ENDPOINT_set ? '(已设置)' : 'https://s3.amazonaws.com'}" style="width:100%;max-width:400px" />
      </div>
      <div class="config-row">
        <label class="config-label">OBJECTSTORE_ACCESS_KEY</label>
        <input type="text" id="objectstore-access-key" placeholder="${d.OBJECTSTORE_ACCESS_KEY_set ? '(已设置)' : ''}" />
      </div>
      <div class="config-row">
        <label class="config-label">OBJECTSTORE_SECRET_KEY</label>
        <input type="password" id="objectstore-secret-key" placeholder="${d.OBJECTSTORE_SECRET_KEY_set ? '(已设置)' : ''}" />
      </div>
      <div class="config-row">
        <label class="config-label">OBJECTSTORE_BUCKET</label>
        <input type="text" id="objectstore-bucket" placeholder="${d.OBJECTSTORE_BUCKET_set ? '(已设置)' : ''}" />
      </div>
    </fieldset>
  </div>`;
}

async function saveStorageConfig() {
  const item = {};
  const pgDsn = document.getElementById('pgstore-dsn')?.value?.trim();
  if (pgDsn) item.pgstore_dsn = pgDsn;
  item.pgstore_schema = document.getElementById('pgstore-schema')?.value?.trim() || '';
  const gitUrl = document.getElementById('gitstore-url')?.value?.trim();
  if (gitUrl) item.gitstore_git_url = gitUrl;
  const gitUser = document.getElementById('gitstore-user')?.value?.trim();
  if (gitUser) item.gitstore_git_username = gitUser;
  const gitToken = document.getElementById('gitstore-token')?.value?.trim();
  if (gitToken) item.gitstore_git_token = gitToken;
  const gitBranch = document.getElementById('gitstore-branch')?.value?.trim();
  if (gitBranch) item.gitstore_git_branch = gitBranch;
  const objEp = document.getElementById('objectstore-endpoint')?.value?.trim();
  if (objEp) item.objectstore_endpoint = objEp;
  const objAk = document.getElementById('objectstore-access-key')?.value?.trim();
  if (objAk) item.objectstore_access_key = objAk;
  const objSk = document.getElementById('objectstore-secret-key')?.value?.trim();
  if (objSk) item.objectstore_secret_key = objSk;
  const objBk = document.getElementById('objectstore-bucket')?.value?.trim();
  if (objBk) item.objectstore_bucket = objBk;

  try {
    const result = await api('/api/storage-config', 'POST', { item });
    showMessage(result.message || 'Saved.');
    await loadStorageConfig();
  } catch (e) {
    showMessage(e.message, true);
  }
}
