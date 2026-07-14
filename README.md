# CLIProxyAPI_work

两个独立子项目放在同一目录下：

```
CLIProxyAPI_work/
├── CLIProxyAPI/              # 代理（Go 源码 + storage）
├── CLIProxyAPI-AccessGateway/ # 外部模型白名单网关（独立 EXE）
├── CLIProxyAPI-Dashboard/    # Web 管理面板
└── README.md                 # 本文件
```

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
