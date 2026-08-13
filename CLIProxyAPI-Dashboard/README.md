# CLIProxyAPI-Dashboard

CLIProxyAPI 工作区的 Web 管理面板：负责生成运行态配置、管理后端进程（内核 + 网关 + 媒体代理）的生命周期、展示请求日志与鉴权状态。

父目录：`E:\U_App\CLIProxyAPI_work\`

## 功能

- **配置生成**：根据 UI 里选中的账号、模型池、路由策略等，动态写出 `CLIProxyAPI/storage/runtime/cliproxyapi-active-config.yaml`，供内核和网关直接读取，无需重启内核。
- **进程管理**：一键启停 CLIProxyAPI 内核（`:8318`）、AccessGateway（`:8317`）、MediaProxy（`:8320`），并监控进程健康状态。
- **请求日志**：解析内核 `request-log` 输出，在 Requests 页面展示每条请求的上游地址、状态、延迟。
- **Auth 管理**：查看、刷新、切换 OAuth 凭据（auth JSON 文件），支持 Codex/Claude/Agnes 等多类账号。
- **Auth 卡片自动保存**：卡片字段在编辑事件发生时进入字段级待保存队列；任一字段最后一次编辑后等待 15 秒再触发保存（继续编辑会重置倒计时）。同一认证文件始终只允许一个更新请求在途，后续编辑不会覆盖或丢失，而是在前一个请求完成后继续提交。
- **网络访问控制**：调用 `PortBindingTools` 脚本管理 portproxy + 防火墙规则，直接在面板里控制哪些端口对哪些 IP 开放。
- **模型池与别名**：在 UI 里配置模型别名映射、模型池轮询权重，变更立即写入运行态配置并通知内核热加载。

## 目录结构

```
CLIProxyAPI-Dashboard/
├── backend/               # Python 后端（HTTP API 服务）
│   ├── server.py          # ThreadingHTTPServer 入口，监听 :8765
│   ├── processes.py       # 进程生命周期管理（start_proxy / stop_proxy）
│   ├── auth.py            # 凭据管理 & build_runtime_config()（核心配置生成逻辑）
│   ├── runtime_env.py     # 环境变量解析、路径解析
│   ├── paths.py           # 所有路径常量（PROXY_ROOT / MEDIA_PROXY_ROOT / ...）
│   ├── model_pool.py      # 模型池配置逻辑
│   ├── model_thinking.py  # 各模型 thinking/effort 参数覆盖
│   └── ...
├── sections/              # 各功能页面 HTML 片段（SPA 片段模式）
├── js/                    # 前端 JS（无构建工具，原生 ES 模块）
├── css/                   # 样式
├── index.html             # 面板 SPA 入口
├── .env.example           # 环境变量模板
├── start.ps1              # 快速启动入口（读取 .env → 调用 start_dashboard.ps1）
├── start_dashboard.ps1    # 完整启动脚本（虚拟环境 / PyInstaller 自动探测）
└── build.spec             # PyInstaller 打包配置
```

## 快速开始

**前提**：Python 3.10+，已安装依赖（`pip install -e .`）。

```powershell
cd E:\U_App\CLIProxyAPI_work\CLIProxyAPI-Dashboard

# 首次：复制环境变量模板
copy .env.example .env
# 按需修改 .env 里的 CLIPROXYAPI_ROOT（默认指向同级 CLIProxyAPI 目录）

# 启动面板
.\start.ps1
```

面板默认在 `http://127.0.0.1:8765` 打开。可用环境变量覆盖：

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `CLIPROXYAPI_ROOT` | `../CLIProxyAPI`（相对面板目录） | CLIProxyAPI 内核项目路径 |
| `CLIPROXYAPI_DASHBOARD_HOST` | `127.0.0.1` | 面板监听地址 |
| `CLIPROXYAPI_DASHBOARD_PORT` | `8765` | 面板监听端口 |
| `CLOUDFLARED_TUNNEL_TOKEN` | —（空） | Cloudflared 隧道 Token，用于远端安全访问 |

## 本地工作台

首页可选显示仅属于当前机器的链接与项目启停按钮。实际配置放在 `.local/dashboard-actions.json`；该目录已被 Git 忽略，不会进入提交或打包模板。先复制 `dashboard-actions.example.json` 再替换其中的示例内容。

`services[].commands` 只能是命令及参数组成的数组，例如 `["powershell", "-NoProfile", "-File", "start.ps1"]`。后端只接受已配置服务的 `start`、`restart`、`stop` 操作，使用 `shell=False` 执行；浏览器请求无法传入或覆写命令、参数或工作目录。

## 依赖

```powershell
pip install -e .        # 安装 Python 依赖（主要是 pywinpty）
```

前端无构建步骤，JS/CSS 直接由面板后端静态托管。

## 配置生成机制

`backend/auth.py` 里的 `build_runtime_config()` 是核心。它读取：

- UI 状态（`backend/state.py` 中的选中账号/模型/路由设置）
- `storage/auth/` 目录下的活跃凭据文件

然后输出 `storage/runtime/cliproxyapi-active-config.yaml`，供内核和 AccessGateway 读取。

> **注意**：每次面板执行"保存/应用"操作都会完整重写该文件，手动对文件的改动会被下次保存覆盖。如有字段需要长期固定，应通过面板 UI 或向面板后端逻辑添加支持，而不是直接改运行态配置文件。

## 打包（Electron 桌面应用）

```powershell
# 1. 用 PyInstaller 打包 Python 后端
cd E:\U_App\CLIProxyAPI_work\CLIProxyAPI-Dashboard
pyinstaller build.spec

# 2. 用 Electron Builder 打包成 .exe 安装包
cd E:\U_App\CLIProxyAPI_work\electron-app
npm install
npm run dist
```

CI（`.github/workflows/build-electron.yml`）会自动完成上述两步并上传 Release 产物。

## 与其他模块的关系

```
Dashboard(:8765)
    ├── 写入 → cliproxyapi-active-config.yaml → 内核(:8318) 读取
    ├── 启停 → CLIProxyAPI-AccessGateway(:8317)
    ├── 启停 → CLIProxyAPI-MediaProxy(:8320)
    └── 展示 → storage/runtime/ 下的请求日志
```

完整架构图和模块边界说明见 [docs/ARCHITECTURE.md](../docs/ARCHITECTURE.md)。
