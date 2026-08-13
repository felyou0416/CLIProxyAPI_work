# 配置参考

> **文档版本**：对应工作区版本 `1.4.0`，内核版本 `v7.2.128`（`UPSTREAM_VERSION`）。字段名称与行为以上游 `config.example.yaml` 为准；内核升级后如字段有变化，请同步更新本文档。
>
> 查具体字段含义、想知道某个错误该改哪个文件时看这里。整体设计动机见 [ARCHITECTURE.md](ARCHITECTURE.md)。

## 目录

- [三层配置文件](#三层配置文件)
- [核心字段](#核心字段)
- [模型别名映射](#模型别名映射)
- [多提供商同名模型（负载均衡场景）](#多提供商同名模型负载均衡场景)
- [端口与网络](#端口与网络)
- [常见报错排查](#常见报错排查)

## 三层配置文件

| 文件 | 谁在用 | 能不能手改 |
| --- | --- | --- |
| `CLIProxyAPI/CLIProxyAPI/config.example.yaml` | 无人直接读取，仅作为上游字段说明模板 | 可以改，但不影响任何运行中的进程 |
| `CLIProxyAPI/storage/config/base-config.yaml` | `start.ps1 codex` / `start.ps1 tui`，绕过网关直连内核调试用 | 可以手改，长期维护 |
| `CLIProxyAPI/storage/runtime/cliproxyapi-active-config.yaml` | `start.ps1 dashboard` 及面板拉起的全部进程（内核 + AccessGateway） | **不要长期手改**——面板每次保存设置都会重写这个文件，手改的内容下次面板保存会被覆盖 |

需要给面板管理的运行态加一个新的上游提供商或模型别名时，优先通过 Dashboard UI 操作；只有面板 UI 覆盖不到的字段才直接改 `cliproxyapi-active-config.yaml`，改完记得同步检查面板里对应设置项显示是否一致。

## 核心字段

以 `cliproxyapi-active-config.yaml` 为例（`base-config.yaml` 结构相同，字段更少）：

```yaml
host: "127.0.0.1"
port: 8317                     # 内核自身监听端口配置项；实际外部入口是 AccessGateway 的 8317，内核真实监听 8318（由面板传参覆盖）
auth-dir: "..."                # OAuth 凭据 JSON 文件目录
api-keys: [...]                # 允许调用本代理的 API Key 列表（客户端侧鉴权，不是上游 Key）
request-log: true              # 记录请求/响应供面板"Requests"页面展示

request-retry: 3                        # 只对 403/408/500/502/503/504 生效，400 不重试
max-retry-credentials: 0                # 0 = 尝试全部可用凭据；>0 限制单次请求最多轮换几个凭据
max-retry-interval: 30                  # 冷却凭据的最长等待秒数
disable-cooling: true                   # true 时全局关闭冷却机制（当前工作区默认关闭）
transient-error-cooldown-seconds: 0     # 0=沿用60秒历史默认；-1=禁用瞬时错误冷却

routing:
  strategy: "round-robin"       # 同一别名映射到多个上游条目时的选择策略
  session-affinity: false       # 是否让同一会话尽量落在同一上游
  session-affinity-ttl: "1h"

quota-exceeded:
  switch-project: true          # 配额超限时是否自动换项目/账号
  switch-preview-model: true    # 是否自动降级到 preview 模型
  antigravity-credits: true     # 是否用积分作为最后兜底
```

> 三个重试/冷却参数不覆盖 400 类错误：这是官方内核硬编码的重试条件（见 [ARCHITECTURE.md#失败处理](ARCHITECTURE.md#失败处理重试冷却与-fallback-的边界)），配置文件里改不出"400 也重试"的效果。

## 模型别名映射

`oauth-model-alias` 和 `openai-compatibility[].models` 两类字段都遵循相同结构：

```yaml
oauth-model-alias:
  <提供商分组名>:
    - name: "<上游真实模型名>"
      alias: "<对外暴露的别名>"
      fork: false
```

`alias` 就是 AccessGateway 白名单里放行的名字；客户端只能用 `alias` 调用，`name` 是转发给上游时真正使用的模型标识。同一个 `alias` 可以被多个 `name` 复用（见下一节），也可以给同一个 `name` 起多个不同用途的别名（比如同时映射成 `claude-opus-4-7` 和某个内部代号）。

`openai-compatibility` 是给非 OAuth、走 API Key 直连的第三方 OpenAI 兼容服务用的，结构是：

```yaml
openai-compatibility:
  - name: "<提供商标识，可以重复出现多次代表多个节点>"
    base-url: "https://.../v1"
    api-key-entries:
      - api-key: "..."
        proxy-url: "http://127.0.0.1:10090"   # 或 "direct"
    models:
      - name: "<上游模型名>"
        alias: "<对外别名>"
```

## 多提供商同名模型（负载均衡场景）

配置里会看到同一个 `name: "zzzz"` 出现多次、`base-url` 各不相同，这不是配置错误，是有意为之：同一别名（比如 `claude-opus-4-8`）被映射到多台后端节点（不同 IP 的 LiteLLM 网关），`routing.strategy: round-robin` 会在这些节点间轮询。

**这种写法的代价**：如果不同节点背后的 LiteLLM 服务本身配置不一致（比如只有部分节点给某个模型配了 `fallbacks`），同一个客户端请求打到不同节点会得到不同结果——这正是"同样的请求，一次失败一次成功"最常见的根因。排查步骤：

1. 打开面板 Requests 页面或直接看请求日志，找到失败请求实际转发到的 `base-url`。
2. 对比该请求成功时转发到的 `base-url`，确认确实是不同节点。
3. 去失败节点对应的 LiteLLM 服务器上检查它的 `config.yaml` 是否给该模型配置了 `fallbacks`。
4. 要治标，可以直接把失败节点在 `models` 列表里去掉该别名映射，让流量只走配好 fallback 的节点。

## 端口与网络

默认全部绑定 `127.0.0.1`，需要局域网或远端访问时用 `PortBindingTools/set-port-bindings.ps1` 加 portproxy + 防火墙规则，而不是把 `host` 改成 `0.0.0.0`（改 `0.0.0.0` 会让内核 8318——本应仅本机可见的原始模型端口——直接暴露到公网）。

## 常见报错排查

| 报错特征 | 常见原因 | 排查方向 |
| --- | --- | --- |
| `BadRequestError ... reasoning_effort ... not supported for <model> in /v1/chat/completions` | 上游服务把新参数（`reasoning_effort`/`tools`）用在了不支持该组合的旧接口上 | 这是上游/LiteLLM 侧的接口兼容问题，不是本代理配置问题；确认该模型是否该走 `/v1/responses` |
| 同一模型同一参数，多次请求偶尔 400 偶尔 200 | 该别名映射到多个上游节点，节点间 fallback 配置不一致 | 见上一节[多提供商同名模型](#多提供商同名模型负载均衡场景) |
| 面板重启后自定义配置消失 | 手改了 `cliproxyapi-active-config.yaml`，面板保存设置时整份重写 | 通过面板 UI 修改，或改完后避免再次经面板保存 |
| `Access gateway did not become ready on ...:8317` | 网关启动超时，通常是内核 8318 没起来或端口被占 | 查看面板日志里 `ACCESS_GATEWAY_STDERR` 对应文件 |
