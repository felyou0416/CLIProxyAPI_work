# Claude 第三方模型适配设计与实施计划

> **状态**：Phase 0 已完成，Phase 1 独立 adapter 核心已实现并通过 `go test ./...` 与 `go vet ./...`；Dashboard 生命周期接入、灰度验证和发布仍待实施。官方内核未修改。
>
> **基线**：工作区 `1.4.0`，官方内核镜像 `v7.2.128`（见 `UPSTREAM_VERSION`），调查日期 `2026-08-30`。
>
> **目标**：让使用 Anthropic Messages API 的客户端可以稳定调用“模型名像 Claude、但上游并非 Anthropic 官方”的第三方模型；同时保留 CPA 现有的模型别名、认证、重试、日志和 Dashboard 管理能力。

## 1. 结论先行

本次适配采用以下边界和优先级：

- **首选使用 CPA 原生 Claude HTTP 路径**：当前官方内核已经提供 `/v1/messages`、`/v1/messages/count_tokens`，并能把 Claude 请求转换到 `openai-compatibility` 上游；只要客户端 base URL 配置正确，就不需要新增 adapter 进程。
- **Dashboard 只负责控制面**：继续生成 runtime config、管理 core/Gateway/MediaProxy 生命周期和展示日志，不进入业务请求数据面。
- **LocalPlugin 保留轻量内核补丁**：继续处理 Agnes 的 thinking 字段和媒体模型路由；不让 DLL 创建 HTTP listener，也不把完整协议转换塞进现有插件。
- **官方内核保持零修改**：当前修复不改 `CLIProxyAPI/CLIProxyAPI/`，也不把外部 adapter 逻辑写进内核镜像。
- **独立 loopback adapter 延后为后备方案**：仅当第三方上游不是 OpenAI-compatible、需要独立的客户端认证/协议转换，或原生内核转换无法表达其能力时，才新增独立 listener；届时由 adapter 负责 Claude ↔ 目标协议转换，仍由 Dashboard 管理其生命周期。

这不是在现有 LocalPlugin 上增加一个 `/v1/messages` 路由。插件 ABI 的 Management/Resource 路由由内核 HTTP 服务器挂载，不能把 DLL 变成独立 HTTP 服务器；完整的外部协议桥接才需要独立进程和 listener。

## 2. 调查事实与问题定位

### 2.1 当前异常不能仅由“provider 名称”解释

Dashboard 的手工 API 配置会依据 `content.api` 分流：`anthropic-messages` 写入 `claude-api-key`，其他 API 类型写入 `openai-compatibility`，见 `CLIProxyAPI-Dashboard/backend/auth.py:2992-3016`、`4189-4223` 和 `5297-5413`。因此，填写 provider 为 `claude`、模型名为 `claude-*` 并不会自动证明上游真的接受 Anthropic Messages。

官方 Claude handler 在 `CLIProxyAPI/CLIProxyAPI/sdk/api/handlers/claude/code_handlers.go:69-134` 和 `170-210` 负责接收 `/v1/messages`；非流式请求进入 `ExecuteWithAuthManager`，`count_tokens` 进入独立的 `ExecuteCountWithAuthManager`。核心执行层在 `CLIProxyAPI/CLIProxyAPI/sdk/api/handlers/handlers_execution.go:38-167` 明确区分普通执行与计数执行。

因此，历史日志中出现的 `messages`/`count_tokens` 均转发到上游 `/v1/chat/completions` 时，不能直接归因于当前源码。Phase 0 已确认当前监听实例的 exe、命令行和 runtime config 均来自本工作区；历史畸形请求来自客户端将完整 endpoint（`/v1/messages?beta=true`）错误填入 `ANTHROPIC_BASE_URL`，而不是旧 CPA 进程。当前配置已改为 `http://127.0.0.1:8317`，让 Claude 客户端自行追加标准路径并经过 Gateway。

### 2.2 当前 LocalPlugin 的边界

当前 DLL 的入口和生命周期位于 `CLIProxyAPI-LocalPlugin/main.go:110-153`，使用 C-shared ABI 的 `cliproxy_plugin_init`、`call`、`free_buffer` 和 `shutdown`。它目前注册的能力只有 model router、request interceptor 和 management API，见 `main.go:155-200`。

现有实现：

- `main.go:250-270`：把配置的媒体别名路由到内核已有 provider。
- `main.go:272-358`：改写 Agnes thinking 字段。
- `main.go:385-402`：返回插件状态资源。

它没有 `net/http` listener、accept loop、Claude Messages handler 或独立上游连接管理。内核 ABI 虽然定义了 `ProviderExecutor`、`CountTokens`、stream executor、request/response translator 和 host HTTP callback，但这些是**内核执行管线的进程内扩展点**，不是公共 HTTP 服务器，见官方 `sdk/pluginapi/types.go:68-120`、`583-589`、`847-1113`。

### 2.3 Dashboard 的现有生命周期

Dashboard 默认监听 `127.0.0.1:8765`，见 `CLIProxyAPI-Dashboard/backend/server.py:17-24`、`207-239`。它从 sibling 目录发现 CPA、Gateway、MediaProxy 和 LocalPlugin，路径定义在 `backend/paths.py:34-84`；持久化统一使用 `CLIProxyAPI/storage/`，见 `paths.py:90-162`。

`start_proxy()` 在 `backend/processes.py:2628-2774` 生成 runtime config，启动核心 `127.0.0.1:8318`，再启动 AccessGateway `:8317`。`build_runtime_config()` 在 `backend/auth.py:5297-5455` 负责复制认证、生成 `claude-api-key`/`openai-compatibility`、写入插件配置和校验 runtime config。

现有 adoption 只根据固定端口和进程名判断 managed，`processes.py:2572-2582` 没有校验可执行文件绝对路径、命令行或实例标识。adapter 接入时必须新增独立实例身份和更严格的启动/接管判断，不能复用“同名进程即可信”的假设。

## 3. 目标架构

### 3.1 进程和端口

| 端口 | 组件 | 责任 | 默认暴露范围 |
| --- | --- | --- | --- |
| `8317` | AccessGateway | CPA 对外 OpenAI/其他协议入口、模型白名单 | 由 Dashboard 的 bind 设置决定 |
| `8318` | 官方 CPA core | 内核执行、认证选择、provider 路由 | `127.0.0.1` |
| `8319` | **Claude Adapter（新增）** | Anthropic Messages 公共入口和协议桥接 | `127.0.0.1` |
| `8320` | MediaProxy | 图片/视频请求 | `127.0.0.1` |
| `8765` | Dashboard | 配置、进程、日志和状态 | `127.0.0.1` |

`8319` 只是建议默认值，最终必须允许配置覆盖并在启动前检查端口占用。adapter 默认只绑定 loopback；需要远端访问时必须显式建立受控的 portproxy/防火墙规则，不能因为 adapter 存在就把 `8318` 暴露出去。

### 3.2 请求数据流

```text
Claude client
   │  POST /v1/messages 或 /v1/messages/count_tokens
   ▼
Claude Adapter :8319 (loopback)
   │  客户端认证、请求校验、Claude -> OpenAI 转换
   │  count_tokens 在这里结束，不产生 completion 请求
   ▼
AccessGateway :8317
   │  模型别名白名单、内部 API key
   ▼
CPA core :8318
   │  route/retry/auth selection
   ▼
第三方 OpenAI-compatible endpoint

第三方响应
   ▲
CPA core -> Gateway -> Adapter
   │  OpenAI Chat Completions -> Claude Messages/SSE
   ▲
Claude client
```

adapter 向 Gateway 使用单独配置的内部 CPA API key；客户端提交的 `x-api-key` 或 `Authorization` 只用于 adapter 入站认证，不能原样转发给第三方。第三方 API key 仍由 CPA auth/config 管理，避免出现两套凭据生命周期。

### 3.3 单一转换所有权

每个请求必须有一个明确的协议转换所有者：

- adapter 负责 Claude Messages 与 OpenAI Chat Completions 之间的转换；
- CPA core/Gateway 负责模型别名、认证、provider 选择、重试和透传；
- LocalPlugin 只负责已有的字段补丁；
- 第三方网关自己的 fallback 仍由第三方网关负责。

不能同时让 adapter、LocalPlugin 和核心 provider adapter 改写同一组 `messages`、tools 或 SSE 事件，否则会出现 system 重复、工具调用嵌套、事件顺序错误和 usage 丢失。

## 4. 配置契约（设计稿）

以下是 Dashboard 需要生成的逻辑配置，不是当前可直接读取的现有字段；实现时应单独保存为 `storage/runtime/claude-adapter.yaml`，并通过临时文件校验后写入。

```yaml
enabled: false
listen:
  host: 127.0.0.1
  port: 8319
upstream:
  base_url: http://127.0.0.1:8317
  api_key: "<CPA internal client key>"
  connect_timeout_seconds: 10
  request_timeout_seconds: 600
client_auth:
  api_keys: ["<adapter client key>"]
routes:
  - alias: "claude-third-party"
    upstream_model: "claude-third-party"
    upstream_format: openai-chat-completions
features:
  streaming: true
  tools: true
  images: true
  documents: false
  count_tokens:
    mode: local_estimate
thinking:
  unsupported: reject
```

契约要求：

- `alias` 是客户端看到的稳定模型名；adapter 默认将 alias 原样送入 Gateway，由 CPA runtime config 决定真实上游模型。
- `upstream.base_url` 默认只能是 loopback CPA Gateway 地址；禁止默认直接绕过 CPA 连接公网 provider。
- adapter client key 与 CPA upstream key 分离；日志只记录 key 的 fingerprint，不记录原文。
- `upstream_format` 首期固定为 `openai-chat-completions`。`openai-responses` 和直接 Anthropic upstream 作为后续能力，不能通过“猜测 endpoint”自动切换。
- `thinking.unsupported: reject` 是首期默认值。若第三方只接受 `reasoning_effort` 或 `enable_thinking`，必须提供明确的模型级映射；不能静默丢弃用户的 thinking 请求。
- `count_tokens.mode=local_estimate` 必须在响应和 Dashboard 状态中标明 approximate；不能伪装成上游精确 tokenizer 结果。

## 5. 协议转换契约

### 5.1 Claude -> OpenAI 请求

必须保留且测试以下字段：

| Claude 字段 | OpenAI Chat Completions | 策略 |
| --- | --- | --- |
| `model` | `model` | 使用 adapter route alias，不信任客户端自行指定 provider |
| `system` | `messages` 中的 `system` message | 原文、顺序和文本块保持，不注入默认 prompt |
| `messages[].content` text | text content | 保持 Unicode 和块顺序 |
| image source | `image_url` | 支持 URL 与 data URL；上游不支持时明确 400 |
| `max_tokens` | `max_tokens` | 不与 `max_completion_tokens` 重复发送 |
| `stop_sequences` | `stop` | 保持数组语义 |
| `temperature`/`top_p` | 同名字段 | 只发送客户端明确提供的值 |
| `tools` | function tools | 保持 name、description、input schema |
| `tool_choice` | `none`/`auto`/`required`/指定 function | 无法表达时返回可诊断的 400 |
| `tool_result` | tool message | 保持 `tool_use_id` 与 tool call id 的对应关系 |
| thinking blocks | provider-specific field | 有映射才发送，否则按 policy reject/strip |
| `metadata` | 不转换成 prompt | 仅作为内部 request metadata 或安全 header |

首期对 `document`、未知 content block、cache control 和无法表达的 thinking 参数采用显式拒绝，错误必须指出字段路径；不得为了“请求成功”把内容拼接成普通文本而造成语义丢失。

### 5.2 OpenAI -> Claude 非流式响应

adapter 必须构造合法的 Claude message response：

- `role=assistant`、`content` text/tool_use blocks；
- `stop_reason` 从 `stop`、`length`、`tool_calls` 等值确定；
- `stop_sequence` 在上游提供时保留；
- `usage.input_tokens` 和 `output_tokens` 使用可追踪的来源；
- 上游错误转换为 Claude error envelope，并保留 HTTP 状态、request id 和安全的错误文本。

### 5.3 OpenAI SSE -> Claude SSE

必须以显式状态机处理，而不是逐行字符串替换。至少覆盖：

1. `message_start`；
2. `content_block_start`/`content_block_delta`/`content_block_stop`；
3. text delta 的顺序和空 delta；
4. tool call name、arguments 增量和 index；
5. `message_delta` 中的 stop reason/usage；
6. `message_stop`、上游 error 和客户端断连清理。

流式请求的失败规则：在响应 headers 尚未提交前返回 JSON 错误；headers 已提交后发送合法 Claude `event: error`，随后关闭流。adapter 不应在流中途重新发起另一种协议的 completion 请求。

### 5.4 `count_tokens` 独立语义

`POST /v1/messages/count_tokens` 必须在 adapter 内部单独处理：

- 只解析 Claude 请求并计算输入估算值；
- 不调用 `/v1/messages`、`/v1/chat/completions` 或任何生成 endpoint；
- 不因 token 估算失败而 fallback 到普通 completion；
- 响应至少包含 `input_tokens`，并在实现中保留 estimator version；
- 若未来增加上游 tokenizer，必须通过显式 `mode: upstream` 开启，并验证其 endpoint 确实是计数接口。

这条约束直接针对历史日志中 `count_tokens` 走 `/v1/chat/completions` 的异常：验收时必须通过 request log 或 mock upstream 证明计数请求没有生成调用。

## 6. 组件职责

### Claude Adapter（新增）

负责 HTTP listener、入站 auth、请求大小/JSON 校验、协议转换、SSE 状态机、count token、超时、取消、request id 和错误映射。它不读取 OAuth 文件，不选择 provider，不实现 CPA retry，也不管理 Dashboard 状态文件。

### Dashboard

负责：

- 从现有手工 API auth/model 配置生成 adapter route；
- 生成 `claude-adapter.yaml`，隐藏密钥并原子写入；
- 管理 adapter PID、stdout/stderr、健康检查和 restart；
- 在状态页显示 `adapter_running`、PID、监听地址、配置版本、上游健康状态和最近失败原因；
- 在停止/重启时区分 Dashboard-owned 与 adopted 实例。

Dashboard 不应在 `/api/chat` 中复制一套 Claude 转换逻辑。现有 `/api/chat` 仍是控制面模型测试/工具请求路径，不能成为新的公共协议边界。

### LocalPlugin

第一阶段不增加 Claude executor。继续使用现有 `model.route`、`request.intercept_after` 和 management status。只有在 adapter 端到端协议已经稳定、且确实需要内核进程内执行时，才评估官方 ABI 的 `ProviderExecutor`；评估必须覆盖 `Execute`、`ExecuteStream`、`CountTokens`、`HttpRequest` 和 host callback recursion。

### 官方内核

保持 `CLIProxyAPI/CLIProxyAPI/` 不变。若发现必须修改官方 handler 才能满足首期目标，应先退回边界设计，确认是否能在 adapter 或插件外层完成；确实需要的内核能力应单独提交上游，而不是在本仓库打补丁。

## 7. 分阶段实施计划

### Phase 0：运行时证据冻结

1. 已记录 core、AccessGateway、MediaProxy、LocalPlugin DLL 的工作区绝对路径、文件时间和运行实例路径；当前 core PID 为 `22152`，Gateway PID 为 `24076`，MediaProxy PID 为 `17776`，Dashboard PID 为 `8084`。
2. 已确认 `8317`、`8318`、`8320` 监听者均由当前工作区进程持有，core 使用 `storage/runtime/cliproxyapi-active-config.yaml`，并加载 `cliproxy-local`；未发现 `8319` adapter listener。
3. 已从归档日志核对：`count_tokens` 共 1344 条，其中 1307 条存在上游 completion 记录；异常 URI 为 `/v1/messages?beta=true%2Fv1%2Fmessages%2Fcount_tokens%3Fbeta%3Dtrue`。根因是 `ANTHROPIC_BASE_URL` 包含完整 endpoint 和 query。
4. 已将 `C:\Users\youqu\.claude\settings.json` 的 `ANTHROPIC_BASE_URL` 改为 `http://127.0.0.1:8317`，并通过该入口验证 `/v1/models` 返回 200、`/v1/messages/count_tokens` 返回 `{"input_tokens":3}`。该计数请求没有生成模型内容，也未要求新增 adapter。

**完成标准**：能解释历史 `/chat/completions` 记录来自哪个 exe/config/plugin 组合；不能用“当前源码应该如此”替代运行时证据。当前异常已定位为客户端 base URL 配置错误，最小修复已完成。

### Phase 1：实现独立 adapter 核心

建议新建 `CLIProxyAPI-ClaudeAdapter/`，按职责拆分为配置、HTTP server、Anthropic model、OpenAI model、translator、stream state machine、token estimator 和 transport；避免将所有转换堆在一个 `main.go`。

先实现：

- `/v1/messages` 非流式；
- `/v1/messages` SSE；
- `/v1/messages/count_tokens` 本地估算；
- 入站 key、body limit、超时、取消和 request id；
- text、image、tools、tool results、stop reason、usage 和错误映射；
- 不支持字段的结构化 400；
- 只连接 loopback CPA Gateway 的 OpenAI Chat Completions。

**完成标准**：adapter 可在没有 Dashboard 的情况下用固定测试配置启动，单元测试和协议 fixture 全部通过。

### Phase 2：接入 Dashboard 控制面

修改范围预计为：

- `CLIProxyAPI-Dashboard/backend/paths.py`：adapter binary/config/log/status 路径；
- `backend/auth.py`：从现有模型配置生成 adapter routes，避免重复维护模型清单；
- `backend/processes.py`：start/stop/restart/status、PID 绑定和端口健康检查；
- `backend/state.py`：启用开关、端口、认证 key fingerprint 和能力策略；
- 相关 `routes/`、页面和测试：只暴露控制面操作。

启动顺序建议：生成并校验 CPA runtime config -> 启动 core -> 启动 Gateway -> 等待 Gateway ready -> 启动 adapter -> adapter health ready。停止顺序反向执行。任何一步失败都要关闭本次启动所拥有的子进程，并保留日志路径。

adoption 必须至少验证：绝对 exe 路径、预期命令行参数、工作目录、监听地址/端口和 instance marker。仅按进程名接管不符合 adapter 的安全要求。

### Phase 3：LocalPlugin 边界收敛

1. 保持 Agnes thinking/media 行为不变。
2. 如需要让 adapter alias 被 CPA Gateway 白名单识别，只通过 runtime config 的模型 alias 生成完成，不让插件重复改写协议。
3. 增加插件状态中对 adapter URL/config version 的只读诊断（若确有需要），不增加 listener。
4. 暂不声明 `Executor`、`RequestTranslator` 或 `ResponseTranslator` 能力，除非独立 adapter 方案验证后有明确收益和完整 ABI 测试。

### Phase 4：灰度、观测和回滚

- 默认 `enabled: false`，先只对一个测试 alias 开启。
- 旧的 8317 OpenAI/其他协议流量不经过 adapter，确保回归范围可控。
- Dashboard 状态区分 adapter 未启用、配置错误、进程未启动、上游不可达和协议拒绝。
- 回滚只需停止 adapter 并关闭开关；不得删除已有 auth 文件、runtime config 或 LocalPlugin 配置。
- 连续观察非流式、流式、工具调用、图片、计数和取消请求后，再扩展 alias 范围。

## 8. 验收矩阵

| 场景 | 预期 | 必须观察 |
| --- | --- | --- |
| text 非流式 | 合法 Claude message response | system/message 原文不重复、不丢失 |
| text 流式 | 合法 Claude SSE 事件序列 | 事件顺序、终止事件、断连清理 |
| image URL/data URL | 上游支持时正确转换 | 不把二进制内容写入普通文本 |
| tools 请求 | 上游支持时完成双向 tool call | id、index、arguments 增量一致 |
| tool result 回合 | 下轮请求正确关联 | 无重复/错配 tool result |
| thinking | 有明确 mapping 才发送 | 无法映射时返回结构化 400 |
| unsupported document | 明确拒绝或后续能力开启 | 不静默丢弃 |
| `count_tokens` | 只返回 `input_tokens` | upstream 没有 `/chat/completions` 生成请求 |
| 上游 400 | 转换为 Claude invalid request | 不重复生成、不误触发 core retry |
| 上游 408/5xx | 按既定层级处理 | 不产生 adapter/core 双重 retry 风暴 |
| 客户端取消 | 上游 body/stream 及时关闭 | 无 goroutine、连接和 stream registry 泄漏 |
| 错误 key | 401/403 | 第三方 key 不出现在日志 |
| 大请求 | 413 或按配置上限处理 | 不绕过 body limit |
| Dashboard restart | owned adapter 可停止并恢复 | adopted 外部进程不被误杀 |
| 旧流量回归 | 8317 原有协议不变 | Gateway/core 日志无异常转换 |

## 9. 风险与决策记录

- **协议不确定性**：第三方“Claude 模型”可能只在名称上兼容 Claude，真实 endpoint、鉴权和 SSE 事件仍需 Phase 0 的真实响应 fixture；首期不做自动探测。
- **token 精度**：没有第三方 tokenizer 时只能提供近似计数；必须把精度和 estimator version 暴露给 Dashboard/日志，不能声称与供应商精确一致。
- **能力丢失**：system、tools、vision、thinking 任一转换失败都可能改变模型行为。默认采用 reject 优先，新增 strip/map 必须是显式模型级配置。
- **重试边界**：CPA 内核的 400 不重试；adapter 不应把协议错误包装成可重试 5xx。瞬时错误的重试只能由一个层级负责。
- **进程接管**：固定端口和进程名不足以证明实例归属。adapter 必须拥有独立 marker，Dashboard 退出时只清理由它创建或明确确认归属的进程。
- **安全边界**：adapter 和 core 默认 loopback；API key 不进 URL、不进日志、不通过 resource route 暴露。内核 Management/Resource 路由不能替代公共 adapter endpoint。

## 10. Phase 1 完成后的下一步

Phase 1 adapter 核心已实现。进入 Dashboard 接入前，应使用脱敏 fixture 和本机 mock 完成以下验证：

- 非流式成功响应和 usage/stop reason 映射；
- 流式 text、tool call、错误和累计 body limit；
- tool result 回合、图片 URL/data URL 和不支持字段的结构化拒绝；
- 400/401/429/5xx、上游超时和客户端取消；
- `count_tokens` 只走本地估算，不产生 completion 请求；
- 实际传输的模型 alias 不含客户端内部标识（例如 `[1M]`）。

验证通过后实施 Phase 2 Dashboard 控制面：生成配置、管理 adapter start/stop/restart/health、严格区分 owned/adopted 进程，并保持 `enabled: false`、loopback-only 和 API key 不进 URL/日志。后续 Phase 3/4 继续保持任何阶段都不修改 `CLIProxyAPI/CLIProxyAPI/` 官方源码。
