# Security Policy

> 文档对应工作区版本 `1.4.0`，内核版本 `v7.2.128`。

## 凭据与密钥的存储现状

本项目的以下路径**包含明文 API Key 和 OAuth 凭据**，**不会**被提交到版本控制（已在 `.gitignore` 中排除）：

| 路径 | 内容 |
| --- | --- |
| `CLIProxyAPI/storage/auth/` | OAuth 账号凭据 JSON 文件 |
| `CLIProxyAPI/storage/config/base-config.yaml` | 上游 API Key（`openai-compatibility[].api-key-entries`） |
| `CLIProxyAPI/storage/runtime/cliproxyapi-active-config.yaml` | 面板生成的运行态配置，同样含明文 Key |
| `CLIProxyAPI-MediaProxy/config.json` | MediaProxy 运行配置，含 API Key |
| `.env`（Dashboard 目录下） | Cloudflared Tunnel Token 等环境变量 |

**检查 `.gitignore` 是否生效：**

```powershell
# 任何时候提交前都可以用这条命令确认敏感文件不会被 git 跟踪
git status --short | Select-String "storage/"
# 若有输出，说明有文件脱离了忽略规则，立即检查
```

## 凭据使用规范

- **禁止**把含有真实 API Key 的配置文件、auth JSON 截图或粘贴到 issue、PR、Slack 等任何地方。
- 测试/演示时使用 `sk-test`、`cliproxyapi` 等占位符，或在 `config.example.yaml`/`config.example.json` 里保留的示例格式。
- 本机以外的节点（如多台 LiteLLM 服务器）上的密钥应定期轮换；轮换后重新在面板里添加新条目并删除旧条目，不要保留失效但仍在配置中的 Key（会增加日志泄露风险）。

## 网络暴露边界

默认配置下只有以下端口对外可见：

- `8317`（AccessGateway）：通过 PortBindingTools 显式打开后才对局域网/远端可见；白名单机制保证只有已映射别名可被调用，原始上游模型名不暴露。

以下端口**不应对外暴露**：

- `8318`（内核）：含原始上游模型名和路由信息，仅本机 `127.0.0.1` 监听。
- `8320`（MediaProxy）：同上，仅内部使用。
- `8765`（Dashboard）：如需远端管理，建议通过 Cloudflared Tunnel 或 VPN，不要直接开放到公网。

如果需要开放某端口给特定 IP，**只用** `PortBindingTools/set-port-bindings.ps1 -RemoteAddress <trusted-ip>` 并配合 `-Firewall` 参数限制来源，不要设置 `host: "0.0.0.0"` 让内核直接监听所有接口。

## 漏洞报告

如果你发现了安全问题（如密钥泄露路径、未鉴权接口、依赖漏洞等），请：

1. **不要**通过 GitHub Issue 公开描述漏洞细节。
2. 通过 GitHub 私信或邮件联系维护者，说明影响范围和复现步骤。
3. 维护者会在 72 小时内确认，协商修复时间线后再公开披露（Coordinated Disclosure）。

## 依赖安全

| 组件 | 主要依赖 | 建议 |
| --- | --- | --- |
| `CLIProxyAPI/CLIProxyAPI/`（Go 内核） | 上游官方仓库负责维护 | 跟随 `update-core.ps1` 保持内核为最新 Tag |
| `CLIProxyAPI-AccessGateway/`、`CLIProxyAPI-MediaProxy/`、`CLIProxyAPI-LocalPlugin/`（Go） | `go.sum` 锁定依赖 | 定期 `go mod tidy && go mod verify` |
| `CLIProxyAPI-Dashboard/`（Python） | `pyproject.toml` | 定期 `pip-audit` 或 `safety check` |
| `apps/tauri-gui/`（Node + Rust） | `package-lock.json` + `Cargo.lock` | 定期 `npm audit` 与 `cargo audit` |
