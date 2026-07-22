# CLIProxyAPI_work

官方内核与本地扩展分开维护：

```
CLIProxyAPI_work/
├── CLIProxyAPI/               # 官方 CPA 内核（Go 源码 + storage）
├── CLIProxyAPI-AccessGateway/ # 外部模型白名单网关（独立 EXE）
├── CLIProxyAPI-LocalPlugin/   # 本地动态插件（独立 DLL）
├── CLIProxyAPI-MediaProxy/    # 图片/视频代理（独立 EXE）
├── CLIProxyAPI-Dashboard/    # Web 管理面板
├── update-core.ps1           # 一键更新、构建和回归
├── UPSTREAM_VERSION          # 已验证的官方内核版本
└── README.md                 # 本文件
```

## 更新官方内核

```powershell
# 默认更新到最新 v7 标签
.\update-core.ps1

# 或指定版本
.\update-core.ps1 -TargetVersion v7.2.74
```

脚本只替换 `CLIProxyAPI/CLIProxyAPI`，并依次验证内核、插件、MediaProxy 和
Dashboard。全部通过后才更新 `UPSTREAM_VERSION`；本地功能不再以内核补丁形式维护。

## 启动

```powershell
# 面板（推荐入口）
cd E:\U_App\CLIProxyAPI_work\CLIProxyAPI-Dashboard
copy .env.example .env    # 首次
.\start.ps1

# 仅代理
cd E:\U_App\CLIProxyAPI_work\CLIProxyAPI
.\start.ps1 build
.\start.ps1 dashboard
```

面板通过 `.env` 中的 `CLIPROXYAPI_ROOT` 指向同级目录 `CLIProxyAPI`（默认已配置）。
外部请求继续使用 `8317`；原始模型只在本机 `8318` 的内核侧存在，`8317` 仅公开映射模型和聚合模型。
