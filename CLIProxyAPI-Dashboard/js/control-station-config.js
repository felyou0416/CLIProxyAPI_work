// =============================================================================
// Shared runtime controls
// -----------------------------------------------------------------------------
// Only services shipped with this repository belong here. Per-machine links and
// unrelated local projects are configured in storage/config/local-workspace/dashboard-actions.json and
// rendered by js/local-workspace.js.
// =============================================================================

window.CONTROL_STATION_LAYERS = [
  {
    grids: [{
      className: 'control-station-layer-grid',
      groups: [
        {
          kind: 'service',
          id: 'proxy',
          icon: 'P',
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
              wait: {
                field: 'proxy_running', expect: true,
                timeoutMs: 150000, intervalMs: 1500,
                readyMessage: '代理服务已启动并可用。',
                timeoutMessage: '启动命令已发出，但 2.5 分钟内未检测到代理就绪。请查看代理日志后重试。',
              },
            },
            {
              action: 'service', op: 'reload', type: 'proxy',
              label: '热加载', i18n: 'btn.reloadProxy',
              api: '/api/reload-proxy', className: 'secondary',
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
          kind: 'service',
          id: 'dashboard',
          icon: 'D',
          title: {
            text: '面板服务',
            i18n: 'label.dashboardGroup',
            href: 'http://127.0.0.1:8765/',
          },
          indicator: { id: 'dashboard-status-indicator', color: 'green' },
          buttons: [
            { action: 'dashboard', op: 'start', mode: 'ps', label: '启动', className: 'secondary' },
            { action: 'dashboard', op: 'restart', label: '重启', className: 'secondary' },
            { action: 'dashboard', op: 'stop', label: '停止', className: 'danger' },
          ],
        },
        {
          kind: 'service',
          id: 'media-proxy',
          icon: 'M',
          title: { text: '媒体代理', href: 'http://127.0.0.1:8320/' },
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
        {
          kind: 'service',
          id: 'claude-adapter',
          icon: 'A',
          title: {
            text: 'ClaudeAdapter',
            href: 'http://127.0.0.1:8319/health',
          },
          indicator: {
            id: 'claude-adapter-status-indicator',
            color: 'red',
            title: 'ClaudeAdapter 未运行',
          },
          buttons: [
            {
              action: 'claude-adapter', op: 'start',
              id: 'claude-adapter-start-btn', label: '启动',
            },
            {
              action: 'claude-adapter', op: 'restart',
              id: 'claude-adapter-restart-btn', label: '重启', className: 'secondary',
            },
            {
              action: 'claude-adapter', op: 'stop',
              id: 'claude-adapter-stop-btn', label: '停止', className: 'danger',
            },
          ],
        },
      ],
    }],
  },
  {
    grids: [{
      className: 'control-station-layer-grid',
      groups: [
        {
          kind: 'service',
          id: 'ip-helper',
          icon: 'I',
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
            { action: 'ip-helper', op: 'start', id: 'ip-helper-start-btn', label: '启动' },
            { action: 'ip-helper', op: 'restart', id: 'ip-helper-restart-btn', label: '重启', className: 'secondary' },
            { action: 'ip-helper', op: 'stop', id: 'ip-helper-stop-btn', label: '停止', className: 'danger' },
          ],
        },
        {
          kind: 'system-proxy',
          id: 'system-proxy',
          icon: 'S',
          title: { text: '系统代理' },
          indicator: {
            id: 'system-proxy-status-indicator',
            color: 'red',
            title: '系统代理未读取',
          },
          ports: [
            { port: 7890, id: 'proxy-port-7890-btn', title: '切换到 127.0.0.1:7890' },
            { port: 10090, id: 'proxy-port-10090-btn', title: '切换到 127.0.0.1:10090' },
            { port: 7897, id: 'proxy-port-7897-btn', title: '切换到 127.0.0.1:7897' },
          ],
          buttons: [
            { action: 'sys-proxy', op: 'configure', id: 'proxy-configure-btn', label: '检测' },
            { action: 'sys-proxy', op: 'toggle', id: 'proxy-toggle-btn', label: '停用', className: 'secondary' },
            { action: 'sys-proxy', op: 'default', id: 'proxy-default-btn', label: '恢复', className: 'secondary' },
          ],
        },
        {
          kind: 'status',
          id: 'proxy-status-group',
          icon: 'N',
          title: { text: '代理状态' },
          statusId: 'proxy-status',
          statusText: '读取中...',
        },
      ],
    }],
  },
];
