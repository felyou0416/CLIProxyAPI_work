/* CPA runtime configuration managed by Dashboard state. */
let advancedConfigData = {};
let advancedConfigDirty = false;

const advancedConfigDefaults = Object.freeze({
  core_routing_strategy: 'round-robin', session_affinity_enabled: false, session_affinity_ttl: '1h',
  force_model_prefix: false, codex_identity_confuse: false, codex_disable_cloaking: false,
  codex_optimize_multi_agent_v2: false, claude_code_disable_cloaking_model_list: false,
  xai_inject_x_search: false, request_retry: 3,
  max_retry_credentials: 0, max_retry_interval: 30, disable_cooling: false,
  save_cooldown_status: false, transient_error_cooldown_seconds: 0,
  quota_switch_project: true, quota_switch_preview_model: true, quota_antigravity_credits: true,
  auth_auto_refresh_workers: 16, local_model: true, ws_auth: false, commercial_mode: false,
  disable_image_generation: 'off', video_result_auth_cache_ttl: '3h', passthrough_headers: false,
  nonstream_keepalive_interval: 0, streaming_keepalive_seconds: 0, streaming_bootstrap_retries: 0,
  logging_to_file: false, logs_max_total_size_mb: 0, error_logs_max_files: 10,
  usage_statistics_enabled: false, usage_queue_retention_seconds: 60,
});

function acEscape(value) {
  return String(value ?? '').replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;').replaceAll("'", '&#39;');
}

function acToggle(id, label, checked, description) {
  return `<div class="runtime-config-row runtime-toggle-row"><div class="runtime-config-copy"><label for="${id}">${acEscape(label)}</label><span>${acEscape(description)}</span></div><label class="runtime-toggle" title="${acEscape(label)}"><input type="checkbox" id="${id}" ${checked ? 'checked' : ''} /><span aria-hidden="true"></span></label></div>`;
}

function acNumber(id, label, value, min, max, unit, description) {
  return `<div class="runtime-config-row"><div class="runtime-config-copy"><label for="${id}">${acEscape(label)}</label><span>${acEscape(description)}</span></div><div class="runtime-number-control"><input class="form-input" type="number" id="${id}" value="${acEscape(value)}" min="${min}" max="${max}" />${unit ? `<span>${acEscape(unit)}</span>` : ''}</div></div>`;
}

function acText(id, label, value, placeholder, description) {
  return `<div class="runtime-config-row"><div class="runtime-config-copy"><label for="${id}">${acEscape(label)}</label><span>${acEscape(description)}</span></div><input class="form-input runtime-text-control" type="text" id="${id}" value="${acEscape(value)}" placeholder="${acEscape(placeholder)}" /></div>`;
}

function acSelect(id, label, value, options, description) {
  const rows = Object.entries(options).map(([v, text]) => `<option value="${acEscape(v)}" ${value === v ? 'selected' : ''}>${acEscape(text)}</option>`).join('');
  return `<div class="runtime-config-row"><div class="runtime-config-copy"><label for="${id}">${acEscape(label)}</label><span>${acEscape(description)}</span></div><select id="${id}" class="runtime-select-control">${rows}</select></div>`;
}

function acCard(title, eyebrow, content, wide = false) {
  return `<article class="runtime-config-card${wide ? ' runtime-config-card-wide' : ''}"><div class="runtime-config-card-head"><span>${acEscape(eyebrow)}</span><h3>${acEscape(title)}</h3></div><div class="runtime-config-list">${content}</div></article>`;
}

function setAdvancedConfigState(text, kind = '') {
  const el = document.getElementById('runtime-config-state'); if (!el) return; el.textContent = text; el.dataset.kind = kind;
}
function markAdvancedConfigDirty() { advancedConfigDirty = true; setAdvancedConfigState('有未保存更改', 'dirty'); }

async function loadAdvancedConfig(force = false) {
  const content = document.getElementById('advanced-config-content');
  if (!content || (advancedConfigDirty && !force)) return;
  setAdvancedConfigState('正在读取', 'loading');
  try {
    const data = await api('/api/advanced-config');
    advancedConfigData = { ...advancedConfigDefaults, ...(data.item || {}) };
    advancedConfigDirty = false; renderAdvancedConfig(); setAdvancedConfigState('已同步', 'saved');
  } catch (error) {
    content.innerHTML = `<div class="metric-empty">${acEscape(error.message || '读取失败')}</div>`;
    setAdvancedConfigState('读取失败', 'error');
  }
}

function renderAdvancedConfig() {
  const content = document.getElementById('advanced-config-content'); if (!content) return;
  const d = { ...advancedConfigDefaults, ...advancedConfigData };
  const routing = [
    acSelect('core-routing-strategy', '凭据选择策略', d.core_routing_strategy, {'round-robin':'轮询分配','weighted-round-robin':'加权轮询','fill-first':'优先填满'}, '多个可用凭据之间的基础分配方式；加权轮询读取凭据 weight。'),
    acToggle('session-affinity-enabled', 'Session 亲和路由', d.session_affinity_enabled, '同一会话优先固定到同一凭据，失效时自动切换。'),
    acText('session-affinity-ttl', 'Session 绑定时长', d.session_affinity_ttl, '1h', '支持 30s、15m、1h 等 Go duration。'),
    acToggle('force-model-prefix', '强制模型前缀', d.force_model_prefix, '无前缀请求只使用同样未设置前缀的凭据。'),
    acToggle('codex-identity-confuse', 'Codex 身份隔离', d.codex_identity_confuse, '在亲和或优先填满路由下，按凭据隔离缓存与安装标识。'),
  ].join('');
  const retry = [
    acNumber('request-retry','单请求重试次数',d.request_retry,0,20,'次','用于 403、408、500、502、503、504。'),
    acNumber('max-retry-credentials','最多尝试凭据数',d.max_retry_credentials,0,1000,'个','0 表示尝试所有可用凭据。'),
    acNumber('max-retry-interval','冷却等待上限',d.max_retry_interval,0,3600,'秒','等待冷却凭据恢复的最长时间。'),
    acToggle('disable-cooling','禁用全局冷却',d.disable_cooling,'关闭失败后的凭据与模型冷却调度。'),
    acToggle('save-cooldown-status','持久化冷却状态',d.save_cooldown_status,'重启后继续保留冷却状态。'),
    acNumber('transient-error-cooldown-seconds','临时错误冷却',d.transient_error_cooldown_seconds,-1,86400,'秒','0 使用默认 60 秒，-1 禁用。'),
  ].join('');
  const service = [
    acToggle('quota-switch-project','额度耗尽切换项目',d.quota_switch_project,'当前项目无额度时尝试其他项目。'),
    acToggle('quota-switch-preview-model','切换预览模型',d.quota_switch_preview_model,'额度受限时允许切换预览模型。'),
    acToggle('quota-antigravity-credits','Antigravity 额度兜底',d.quota_antigravity_credits,'免费层耗尽时允许 credits 兜底。'),
    acNumber('auth-auto-refresh-workers','OAuth 刷新并发',d.auth_auto_refresh_workers,1,256,'线程','刷新文件型 OAuth 凭据的工作线程数。'),
    acToggle('local-model','仅使用本地模型目录',d.local_model,'跳过远程模型目录刷新。'),
    acToggle('ws-auth','WebSocket 认证',d.ws_auth,'为 /v1/ws 开启 API Key 校验。'),
    acToggle('commercial-mode','商用精简模式',d.commercial_mode,'关闭高开销 HTTP 中间件。'),
  ].join('');
  const response = [
    acSelect('disable-image-generation','图片生成策略',d.disable_image_generation,{'off':'允许并自动处理','chat':'聊天接口禁用','passthrough':'聊天接口原样转发','all':'全部禁用'},'控制图片工具注入及 /v1/images 接口。'),
    acText('video-result-auth-cache-ttl','视频凭据绑定时长',d.video_result_auth_cache_ttl,'3h','视频任务 ID 与创建凭据保持绑定的时长。'),
    acToggle('passthrough-headers','透传上游响应头',d.passthrough_headers,'将过滤后的上游响应头返回客户端。'),
    acNumber('nonstream-keepalive-interval','非流式保活间隔',d.nonstream_keepalive_interval,0,3600,'秒','0 关闭。'),
    acNumber('streaming-keepalive-seconds','SSE 保活间隔',d.streaming_keepalive_seconds,0,3600,'秒','0 关闭。'),
    acNumber('streaming-bootstrap-retries','流式启动重试',d.streaming_bootstrap_retries,0,10,'次','仅在首字节前安全重试。'),
  ].join('');
  const compatibility = [
    acToggle('codex-disable-cloaking','禁用 Codex 标头伪装',d.codex_disable_cloaking,'不再强制官方 Codex User-Agent 与 Originator，仅在上游需要原始标头时开启。'),
    acToggle('codex-optimize-multi-agent-v2','Codex 多代理 v2 优化',d.codex_optimize_multi_agent_v2,'为 Codex Desktop 与 codex-tui 刷新代理模型信息并规范化 agent_message。'),
    acToggle('claude-code-disable-cloaking-model-list','Claude 模型列表使用原名',d.claude_code_disable_cloaking_model_list,'Anthropic 模型列表返回原始模型 ID，不再使用伪装 ID。'),
    acToggle('xai-inject-x-search','自动注入 xAI 搜索',d.xai_inject_x_search,'请求未声明时注入原生 x_search，并同步 allowed_tools。'),
  ].join('');
  const logging = [
    acToggle('logging-to-file','写入轮转日志',d.logging_to_file,'让 CPA 将应用日志写入轮转文件。'),
    acNumber('logs-max-total-size-mb','日志总大小上限',d.logs_max_total_size_mb,0,102400,'MB','0 表示不限制。'),
    acNumber('error-logs-max-files','错误日志保留数',d.error_logs_max_files,0,10000,'份','请求日志关闭时保留的错误日志数量。'),
    acToggle('usage-statistics-enabled','内存用量统计',d.usage_statistics_enabled,'启用内核内存中的请求与 Token 汇总。'),
    acNumber('usage-queue-retention-seconds','用量队列保留',d.usage_queue_retention_seconds,1,3600,'秒','Management API 用量队列保留时间。'),
  ].join('');
  content.innerHTML = [acCard('路由与会话','Routing',routing),acCard('重试与冷却','Reliability',retry),acCard('配额与服务','Service',service),acCard('响应与媒体','Response',response),acCard('协议兼容','Compatibility',compatibility),acCard('日志与统计','Observability',logging,true)].join('');
  content.querySelectorAll('input, select').forEach(el => { el.addEventListener('input', markAdvancedConfigDirty); el.addEventListener('change', markAdvancedConfigDirty); });
}

function resetAdvancedConfigDefaults() { advancedConfigData = { ...advancedConfigDefaults }; renderAdvancedConfig(); markAdvancedConfigDirty(); }
function acInteger(id) { const v=Number.parseInt(document.getElementById(id)?.value,10); return Number.isFinite(v)?v:0; }
function collectAdvancedConfig() {
  const checked=id=>!!document.getElementById(id)?.checked;
  return {
    core_routing_strategy:document.getElementById('core-routing-strategy')?.value||'round-robin', session_affinity_enabled:checked('session-affinity-enabled'), session_affinity_ttl:document.getElementById('session-affinity-ttl')?.value?.trim()||'1h', force_model_prefix:checked('force-model-prefix'), codex_identity_confuse:checked('codex-identity-confuse'), codex_disable_cloaking:checked('codex-disable-cloaking'), codex_optimize_multi_agent_v2:checked('codex-optimize-multi-agent-v2'), claude_code_disable_cloaking_model_list:checked('claude-code-disable-cloaking-model-list'), xai_inject_x_search:checked('xai-inject-x-search'), request_retry:acInteger('request-retry'), max_retry_credentials:acInteger('max-retry-credentials'), max_retry_interval:acInteger('max-retry-interval'), disable_cooling:checked('disable-cooling'), save_cooldown_status:checked('save-cooldown-status'), transient_error_cooldown_seconds:acInteger('transient-error-cooldown-seconds'), quota_switch_project:checked('quota-switch-project'), quota_switch_preview_model:checked('quota-switch-preview-model'), quota_antigravity_credits:checked('quota-antigravity-credits'), auth_auto_refresh_workers:acInteger('auth-auto-refresh-workers'), local_model:checked('local-model'), ws_auth:checked('ws-auth'), commercial_mode:checked('commercial-mode'), disable_image_generation:document.getElementById('disable-image-generation')?.value||'off', video_result_auth_cache_ttl:document.getElementById('video-result-auth-cache-ttl')?.value?.trim()||'3h', passthrough_headers:checked('passthrough-headers'), nonstream_keepalive_interval:acInteger('nonstream-keepalive-interval'), streaming_keepalive_seconds:acInteger('streaming-keepalive-seconds'), streaming_bootstrap_retries:acInteger('streaming-bootstrap-retries'), logging_to_file:checked('logging-to-file'), logs_max_total_size_mb:acInteger('logs-max-total-size-mb'), error_logs_max_files:acInteger('error-logs-max-files'), usage_statistics_enabled:checked('usage-statistics-enabled'), usage_queue_retention_seconds:acInteger('usage-queue-retention-seconds'),
  };
}
function setAdvancedConfigBusy(busy) { ['advanced-config-save','advanced-config-save-restart'].forEach(id=>{const b=document.getElementById(id);if(b)b.disabled=busy;}); }
async function saveAdvancedConfig(restart=false) {
  setAdvancedConfigBusy(true); setAdvancedConfigState('正在保存','loading');
  try {
    const payload=collectAdvancedConfig(); const result=await api('/api/advanced-config','POST',payload); advancedConfigData={...payload}; advancedConfigDirty=false;
    if(restart){ setAdvancedConfigState('正在重启代理','loading'); const rr=await api('/api/restart-proxy','POST',{}); if(rr&&rr.ok===false)throw new Error(rr.message||'代理重启失败'); setAdvancedConfigState('已保存并生效','saved'); showMessage(rr?.message||'配置已保存，代理已重启。'); }
    else { setAdvancedConfigState('已保存，待重启','dirty'); showMessage(result.message||'配置已保存，需要重启代理后生效。'); }
  } catch(error){ setAdvancedConfigState('保存失败','error'); showMessage(error.message||'保存失败',true); } finally { setAdvancedConfigBusy(false); }
}
