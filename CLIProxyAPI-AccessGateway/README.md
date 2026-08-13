# CLIProxyAPI-AccessGateway

外部客户端的**唯一入口**：模型白名单反向代理，把合法的模型别名请求转发给内部 CLIProxyAPI 内核，屏蔽原始上游模型名。

父目录：`E:\U_App\CLIProxyAPI_work\`

## 职责

- 读取 `cliproxyapi-active-config.yaml` 里所有 `oauth-model-alias`、`openai-compatibility[].models`、`claude-api-key[].models` 等字段中声明的 `alias`，作为请求模型名白名单。
- 收到客户端请求后校验请求体中的 `model` 字段，**不在白名单则拒绝**，在白名单则原样转发给上游内核（`http://127.0.0.1:8318`）。
- 每秒轮询配置文件变化（`watchAllowedModels`），热更新白名单——无需重启即可在面板保存配置后生效。

**不做的事**：不改写请求体，不感知具体厂商协议，不持有任何上游 API Key。

## 端口

| 端口 | 说明 |
| --- | --- |
| `:8317`（监听） | 对外入口，客户端请求打到这里 |
| `:8318`（上游） | 转发目标，内核监听地址（由面板启动时传参 `-upstream http://127.0.0.1:8318`） |

## 构建

```powershell
cd E:\U_App\CLIProxyAPI_work\CLIProxyAPI-AccessGateway
go build -o cli-access-gateway.exe .
```

依赖：`gopkg.in/yaml.v3`（Go 1.22+）。

## 运行

通常由 `CLIProxyAPI-Dashboard` 自动管理启停，不需要手动运行。手动启动格式：

```powershell
.\cli-access-gateway.exe `
  -listen  127.0.0.1:8317 `
  -upstream http://127.0.0.1:8318 `
  -config  E:\U_App\CLIProxyAPI_work\CLIProxyAPI\storage\runtime\cliproxyapi-active-config.yaml
```

## 测试

```powershell
go test ./...
```

`main_test.go` 覆盖了白名单加载、热更新、非法模型拒绝等核心场景。

## 与其他模块的关系

```
客户端  →  AccessGateway(:8317)  →  CLIProxyAPI 内核(:8318)
```

- AccessGateway 不持有配置的写入权限，只读取 `cliproxyapi-active-config.yaml`。
- 配置由 `CLIProxyAPI-Dashboard` 生成并写入；网关在检测到文件变化后自动更新白名单（通常 ≤1 秒）。
- 如果需要对局域网/远端暴露 `8317`，请使用 `PortBindingTools/set-port-bindings.ps1`；**不要暴露 `8318`**。

完整架构图和模块边界说明见 [docs/ARCHITECTURE.md](../docs/ARCHITECTURE.md)。
