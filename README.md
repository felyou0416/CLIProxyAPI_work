# CLIProxyAPI_work

两个独立子项目放在同一目录下：

```
CLIProxyAPI_work/
├── CLIProxyAPI/              # 代理（Go 源码 + storage）
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
