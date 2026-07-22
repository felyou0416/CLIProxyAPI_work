// =============================================================================
// 控制台配置（唯一「加服务 / 改按钮」入口）
// -----------------------------------------------------------------------------
// 渲染与点击分发：js/control-station.js
// 运行时原语（黄灯、组锁、轮询）：js/status.js
// 特例动作：面板自身 tools.js / 系统代理 overview-panel.js / IP Helper firewall-access.js
//
// 组类型 kind：
//   service      — 标题 + 状态灯 + 启/重/停（或自定义 buttons）
//   status       — 只读状态文案（无按钮）
//   system-proxy — 端口快捷键 + 检测/停用/恢复
//
// 按钮 action（点击时由 control-station.js 分发）：
//   service    → handleActionWithIndicator
//   dashboard  → runDashboardScript / restartDashboardPanel / stopDashboardPanel
//   ip-helper  → setIpHelperService
//   sys-proxy  → runSystemProxyAction
//
// 约束：
// 1) 元素 id 不要随意改 —— refreshStatus、OpenClaw 按钮禁用态、系统代理展示都靠固定 id
// 2) 需要长启动等待时，在 button.wait 里写 field/expect/timeoutMs
// 3) errorState：动作失败时指示灯颜色（常见：启动失败 red，停止失败 green）
// =============================================================================

window.CONTROL_STATION_LAYERS = [
  // 第 1 层：核心代理 / 面板自身 / 媒体代理
  {
    grids: [{
      className: 'control-station-layer-grid',
      groups: [
        {
          kind: 'service',
          id: 'proxy',
          icon: '⚡',
          title: {
            text: '代理服务',
            i18n: 'label.proxyGroup',
            href: 'http://127.0.0.1:8317/',
          },
          indicator: { id: 'proxy-status-indicator', color: 'red' },
          buttons: [
            {
              action: 'service', op: 'start', type: 'proxy',
              label: '启动', i18n: 'btn.startProxy',
              api: '/api/start-project', errorState: 'red',
              // 后端启动仍可能需数秒（配置重建）；API 返回后以 status 绿为准
              wait: {
                field: 'proxy_running', expect: true,
                timeoutMs: 150000, intervalMs: 1500,
                readyMessage: '代理服务已启动并可用。',
                timeoutMessage: '启动命令已发出，但 2.5 分钟内未检测到代理就绪。请查看代理日志后重试。',
              },
            },
            {
              action: 'service', op: 'restart', type: 'proxy',
              label: '重启', i18n: 'btn.restartProxy',
              api: '/api/restart-proxy', className: 'secondary',
              wait: {
                field: 'proxy_running', expect: true,
                timeoutMs: 150000, intervalMs: 1500,
                readyMessage: '代理服务已重启并可用。',
                timeoutMessage: '重启命令已发出，但 2.5 分钟内未检测到代理就绪。请查看代理日志后重试。',
              },
            },
            {
              action: 'service', op: 'stop', type: 'proxy',
              label: '停止', i18n: 'btn.stopProxy',
              api: '/api/stop-proxy', className: 'danger', errorState: 'green',
              wait: {
                field: 'proxy_running', expect: false,
                timeoutMs: 30000, intervalMs: 1000,
                readyMessage: '代理服务已停止。',
              },
            },
          ],
        },
        {
          // 面板进程自己：启停逻辑特殊（确认框 / 整页 reload），不走通用 service API
          kind: 'service',
          id: 'dashboard',
          icon: '📊',
          title: {
            text: '面板服务',
            i18n: 'label.dashboardGroup',
            href: 'http://127.0.0.1:8765/',
          },
          indicator: { id: 'dashboard-status-indicator', color: 'green' },
          buttons: [
            {
              action: 'dashboard', op: 'start', mode: 'ps',
              label: '启动', className: 'secondary',
            },
            {
              action: 'dashboard', op: 'restart',
              label: '重启', className: 'secondary',
            },
            {
              action: 'dashboard', op: 'stop',
              label: '停止', className: 'danger',
            },
          ],
        },
        {
          kind: 'service',
          id: 'media-proxy',
          icon: '🎬',
          title: {
            text: '媒体代理',
            href: 'http://127.0.0.1:8320/',
          },
          indicator: { id: 'media-proxy-status-indicator', color: 'red' },
          buttons: [
            {
              action: 'service', op: 'start', type: 'media-proxy',
              id: 'media-proxy-start-btn', label: '启动',
              api: '/api/media-proxy/start', errorState: 'red',
            },
            {
              action: 'service', op: 'restart', type: 'media-proxy',
              id: 'media-proxy-restart-btn', label: '重启',
              api: '/api/media-proxy/restart', className: 'secondary', errorState: 'red',
            },
            {
              action: 'service', op: 'stop', type: 'media-proxy',
              id: 'media-proxy-stop-btn', label: '停止',
              api: '/api/media-proxy/stop', className: 'danger', errorState: 'green',
            },
          ],
        },
      ],
    }],
  },
  // 第 2 层：OpenClaw / OAuth / create-grok(=grok-register-mint，长启动需 wait 轮询就绪)
  {
    grids: [{
      className: 'control-station-layer-grid',
      groups: [
        {
          kind: 'service',
          id: 'openclaw',
          icon: '🧩',
          // 无外链标题，用 span 渲染
          title: { text: 'OpenClaw' },
          indicator: { id: 'openclaw-status-indicator', color: 'red' },
          buttons: [
            {
              action: 'service', op: 'start', type: 'openclaw',
              id: 'openclaw-start-btn', label: '启动',
              api: '/api/openclaw/start', errorState: 'red',
              // 冷启动可能很慢，成功消息以轮询到 running 为准
              wait: {
                field: 'openclaw_running', expect: true,
                timeoutMs: 180000, intervalMs: 3000,
                readyMessage: 'OpenClaw 已启动并可用。',
                timeoutMessage: 'OpenClaw 启动命令已发出，但 3 分钟内未检测到网关。请查看 OpenClaw 日志。',
              },
            },
            {
              action: 'service', op: 'restart', type: 'openclaw',
              id: 'openclaw-restart-btn', label: '重启',
              api: '/api/openclaw/restart', className: 'secondary', errorState: 'red',
              wait: {
                field: 'openclaw_running', expect: true,
                timeoutMs: 180000, intervalMs: 3000,
                readyMessage: 'OpenClaw 已启动并可用。',
                timeoutMessage: 'OpenClaw 启动命令已发出，但 3 分钟内未检测到网关。请查看 OpenClaw 日志。',
              },
            },
            {
              action: 'service', op: 'stop', type: 'openclaw',
              id: 'openclaw-stop-btn', label: '停止',
              api: '/api/openclaw/stop', className: 'danger', errorState: 'green',
            },
          ],
        },
        {
          kind: 'service',
          id: 'oauth',
          icon: '🔑',
          title: {
            text: 'OAuth',
            i18n: 'label.oauthManagerGroup',
            href: 'http://127.0.0.1:1900/',
          },
          indicator: { id: 'oauth-status-indicator', color: 'red' },
          buttons: [
            {
              action: 'service', op: 'start', type: 'oauth',
              label: '启动', i18n: 'btn.startOAuthManager',
              api: '/api/start-oauth-manager', errorState: 'red',
              wait: {
                field: 'oauth_manager_running', expect: true,
                timeoutMs: 20000, intervalMs: 1000,
                readyMessageKey: 'runtime.oauthManagerReady',
                readyMessage: 'OAuth Manager 已启动。',
                timeoutMessageKey: 'runtime.oauthManagerStartTimeout',
                timeoutMessage: 'OAuth Manager 启动命令已发出，但未检测到服务就绪。请查看 OAuth Manager 日志。',
              },
            },
            {
              action: 'service', op: 'restart', type: 'oauth',
              label: '重启', i18n: 'btn.restartOAuthManager',
              api: '/api/restart-oauth-manager', className: 'secondary', errorState: 'red',
              wait: {
                field: 'oauth_manager_running', expect: true,
                timeoutMs: 25000, intervalMs: 1000,
                readyMessageKey: 'runtime.oauthManagerReady',
                readyMessage: 'OAuth Manager 已启动。',
                timeoutMessageKey: 'runtime.oauthManagerStartTimeout',
                timeoutMessage: 'OAuth Manager 重启命令已发出，但未检测到服务就绪。请查看 OAuth Manager 日志。',
              },
            },
            {
              action: 'service', op: 'stop', type: 'oauth',
              label: '停止', i18n: 'btn.stopOAuthManager',
              api: '/api/stop-oauth-manager', className: 'danger', errorState: 'green',
              wait: {
                field: 'oauth_manager_running', expect: false,
                timeoutMs: 15000, intervalMs: 800,
                readyMessageKey: 'runtime.oauthManagerStopped',
                readyMessage: 'OAuth Manager 已停止。',
              },
            },
          ],
        },
        {
          kind: 'service',
          id: 'create-grok',
          icon: '🧪',
          title: {
            text: 'grok-register-mint',
            href: 'http://127.0.0.1:3780/',
            id: 'create-grok-title-link',
            titleAttr: 'Grok Register Mint 批量注册 / CPA mint 面板',
          },
          indicator: { id: 'create-grok-status-indicator', color: 'red' },
          buttons: [
            {
              action: 'service', op: 'start', type: 'create-grok',
              id: 'create-grok-start-btn', label: '启动',
              api: '/api/create-grok/start', errorState: 'red',
              wait: {
                field: 'create_grok_running', expect: true,
                timeoutMs: 20000, intervalMs: 1000,
                readyMessage: 'grok-register-mint 已启动：http://127.0.0.1:3780/',
                timeoutMessage: 'grok-register-mint 启动命令已发出，但未检测到 :3780 就绪。',
              },
            },
            {
              action: 'service', op: 'restart', type: 'create-grok',
              id: 'create-grok-restart-btn', label: '重启',
              api: '/api/create-grok/restart', className: 'secondary', errorState: 'red',
              wait: {
                field: 'create_grok_running', expect: true,
                timeoutMs: 25000, intervalMs: 1000,
                readyMessage: 'grok-register-mint 已启动：http://127.0.0.1:3780/',
                timeoutMessage: 'grok-register-mint 重启命令已发出，但未检测到 :3780 就绪。',
              },
            },
            {
              action: 'service', op: 'stop', type: 'create-grok',
              id: 'create-grok-stop-btn', label: '停止',
              api: '/api/create-grok/stop', className: 'danger', errorState: 'green',
              wait: {
                field: 'create_grok_running', expect: false,
                timeoutMs: 15000, intervalMs: 800,
                readyMessage: 'grok-register-mint 已停止。',
              },
            },
          ],
        },
        {
          kind: 'service',
          id: '77chat',
          icon: '💬',
          title: {
            text: '77chat',
            id: 'chat77-title-link',
            titleAttr: '77chat 智能对话面板',
            hrefs: [
              { text: '77chat (本地)', href: 'http://127.0.0.1:90/' },
              { text: '77chat (公网)', href: 'https://qiqi.felyou.cc.cd/' },
            ],
          },
          indicator: { id: 'chat77-status-indicator', color: 'red' },
          buttons: [
            {
              action: 'service', op: 'start', type: '77chat',
              id: 'chat77-start-btn', label: '启动',
              api: '/api/77chat/start', errorState: 'red',
              wait: {
                field: 'chat77_running', expect: true,
                timeoutMs: 20000, intervalMs: 1000,
                readyMessage: '77chat 已启动：http://127.0.0.1:90/',
                timeoutMessage: '77chat 启动命令已发出，但未检测到 :90 就绪。',
              },
            },
            {
              action: 'service', op: 'restart', type: '77chat',
              id: 'chat77-restart-btn', label: '重启',
              api: '/api/77chat/restart', className: 'secondary', errorState: 'red',
              wait: {
                field: 'chat77_running', expect: true,
                timeoutMs: 25000, intervalMs: 1000,
                readyMessage: '77chat 已重启：http://127.0.0.1:90/',
                timeoutMessage: '77chat 重启命令已发出，但未检测到 :90 就绪。',
              },
            },
            {
              action: 'service', op: 'stop', type: '77chat',
              id: 'chat77-stop-btn', label: '停止',
              api: '/api/77chat/stop', className: 'danger', errorState: 'green',
              wait: {
                field: 'chat77_running', expect: false,
                timeoutMs: 15000, intervalMs: 800,
                readyMessage: '77chat 已停止。',
              },
            },
          ],
        },
      ],
    }],
  },
  // 第 3 层：Tunnel / IP Helper
  {
    grids: [{
      className: 'control-station-layer-grid',
      groups: [
        {
          kind: 'service',
          id: 'tunnel',
          icon: '☁️',
          title: {
            text: 'Tunnel',
            i18n: 'label.tunnelControlGroup',
            href: 'https://cpa.felyou.cc.cd/',
            id: 'tunnel-title-link',
          },
          indicator: { id: 'tunnel-status-indicator', color: 'red' },
          buttons: [
            {
              action: 'service', op: 'start', type: 'tunnel',
              id: 'tunnel-start-btn', label: '启动', i18n: 'btn.startTunnel',
              api: '/api/tunnel/start', errorState: 'red',
            },
            {
              action: 'service', op: 'restart', type: 'tunnel',
              id: 'tunnel-restart-btn', label: '重启', i18n: 'btn.restartTunnel',
              api: '/api/tunnel/restart', className: 'secondary', errorState: 'red',
            },
            {
              action: 'service', op: 'stop', type: 'tunnel',
              id: 'tunnel-stop-btn', label: '关闭', i18n: 'btn.stopTunnel',
              api: '/api/tunnel/stop', className: 'danger', errorState: 'green',
            },
          ],
        },
        {
          // 标题点进防火墙页；动作走 elevated 的 setIpHelperService
          kind: 'service',
          id: 'ip-helper',
          icon: '🛡️',
          title: {
            text: 'IP Helper',
            href: '#firewall-access',
            section: 'firewall-access',
          },
          indicator: {
            id: 'ip-helper-status-indicator',
            color: 'yellow',
            title: 'IP Helper 未读取',
          },
          buttons: [
            {
              action: 'ip-helper', op: 'start',
              id: 'ip-helper-start-btn', label: '启动',
            },
            {
              action: 'ip-helper', op: 'restart',
              id: 'ip-helper-restart-btn', label: '重启', className: 'secondary',
            },
            {
              action: 'ip-helper', op: 'stop',
              id: 'ip-helper-stop-btn', label: '关闭', className: 'danger',
            },
          ],
        },
      ],
    }],
  },
  // 第 4 层：Grok2API 前后端 + 进程实际代理 + 系统代理
  {
    grids: [
      {
        className: 'control-station-layer-grid',
        groups: [
          {
            // 前后端指示灯独立；busy 锁仍共用 grok2apiActionBusy（见 status.js）
            kind: 'service',
            id: 'grok2api-frontend',
            icon: '🖥️',
            title: {
              text: 'Grok2API 前端',
              i18n: 'label.grok2apiFrontendGroup',
              href: 'http://127.0.0.1:5173/accounts',
              id: 'grok2api-title-link', // refreshStatus 会按实际 URL 改 href
            },
            indicator: {
              id: 'grok2api-frontend-status-indicator',
              color: 'red',
              title: 'Grok2API 前端状态',
            },
            buttons: [
              {
                action: 'service', op: 'start', type: 'grok2api-frontend',
                id: 'grok2api-frontend-start-btn',
                label: '启动', i18n: 'btn.grok2apiStart',
                api: '/api/grok2api/frontend/start', errorState: 'red',
              },
              {
                action: 'service', op: 'restart', type: 'grok2api-frontend',
                id: 'grok2api-frontend-restart-btn',
                label: '重启', i18n: 'btn.grok2apiRestart',
                api: '/api/grok2api/frontend/restart', className: 'secondary', errorState: 'red',
              },
              {
                action: 'service', op: 'stop', type: 'grok2api-frontend',
                id: 'grok2api-frontend-stop-btn',
                label: '关闭', i18n: 'btn.grok2apiStop',
                api: '/api/grok2api/frontend/stop', className: 'danger', errorState: 'red',
              },
            ],
          },
          {
            kind: 'service',
            id: 'grok2api-backend',
            icon: '⚙️',
            title: {
              text: 'Grok2API 后端',
              i18n: 'label.grok2apiBackendGroup',
              href: 'http://127.0.0.1:8000/readyz',
              titleAttr: '查看 Grok2API 后端就绪状态',
            },
            indicator: {
              id: 'grok2api-backend-status-indicator',
              color: 'red',
              title: 'Grok2API 后端状态',
            },
            buttons: [
              {
                action: 'service', op: 'start', type: 'grok2api-backend',
                id: 'grok2api-backend-start-btn',
                label: '启动', i18n: 'btn.grok2apiStart',
                api: '/api/grok2api/backend/start', errorState: 'red',
              },
              {
                action: 'service', op: 'restart', type: 'grok2api-backend',
                id: 'grok2api-backend-restart-btn',
                label: '重启', i18n: 'btn.grok2apiRestart',
                api: '/api/grok2api/backend/restart', className: 'secondary', errorState: 'red',
              },
              {
                action: 'service', op: 'stop', type: 'grok2api-backend',
                id: 'grok2api-backend-stop-btn',
                label: '关闭', i18n: 'btn.grok2apiStop',
                api: '/api/grok2api/backend/stop', className: 'danger', errorState: 'red',
              },
            ],
          },
          {
            // 只读：grok2api 进程自报的代理端口，不是 OS 系统代理设置
            kind: 'status',
            id: 'grok2api-sys-proxy',
            groupId: 'grok2api-sys-proxy-group',
            groupTitle: '读取 grok2api 进程自身上报的系统代理端口（非面板系统代理设置）',
            icon: '🔌',
            title: { text: 'Grok2API 实际代理' },
            indicator: {
              id: 'grok2api-sys-proxy-indicator',
              color: 'red',
              title: '未读取 grok2api',
            },
            statusId: 'grok2api-sys-proxy-port',
            statusText: '读取中...',
            statusTitle: '来自 grok2api 进程上报 · 非系统代理设置本身',
          },
        ],
      },
      {
        // 系统代理占两列宽，状态组一列（见 CSS .control-station-sys-proxy-grid）
        className: 'control-station-layer-grid control-station-sys-proxy-grid',
        groups: [
          {
            kind: 'system-proxy',
            id: 'system-proxy',
            icon: '🌐',
            title: { text: '系统代理' },
            indicator: {
              id: 'system-proxy-status-indicator',
              color: 'red',
              title: '系统代理未读取',
            },
            ports: [
              {
                port: 7890,
                id: 'proxy-port-7890-btn',
                title: '切换系统代理到 127.0.0.1:7890（FlClash 常用）',
              },
              {
                port: 10090,
                id: 'proxy-port-10090-btn',
                title: '切换系统代理到 127.0.0.1:10090（猫猫云常用）',
              },
              {
                port: 7897,
                id: 'proxy-port-7897-btn',
                title: '切换系统代理到 127.0.0.1:7897',
              },
            ],
            buttons: [
              {
                action: 'sys-proxy', op: 'configure',
                id: 'proxy-configure-btn', label: '检测',
                title: '一键检测并配置系统代理',
              },
              {
                action: 'sys-proxy', op: 'toggle',
                id: 'proxy-toggle-btn', label: '停用', className: 'secondary',
                title: '停止或启动系统代理',
              },
              {
                action: 'sys-proxy', op: 'default',
                id: 'proxy-default-btn', label: '恢复', className: 'secondary',
                title: '恢复默认：关闭系统代理并清理环境变量',
              },
            ],
          },
          {
            // 系统代理一句话状态；文案由 updateProxyStatusDisplay 写入
            kind: 'status',
            id: 'proxy-status-group',
            icon: '📡',
            title: { text: '代理状态' },
            statusId: 'proxy-status',
            statusText: '读取中...',
          },
        ],
      },
    ],
  },
];
