# 贡献指南

> **文档版本**：对应工作区版本 `1.4.0`，内核版本 `v7.2.128`（`UPSTREAM_VERSION`）。
>
> 面向要往这个仓库提交改动的人（包括未来的自己和协作的 Agent）。行为准则见 [AGENTS.md](../AGENTS.md)，这里补充具体操作流程。

## 目录

- [提交前必读](#提交前必读)
- [改哪里、不改哪里](#改哪里不改哪里)
- [提交规范](#提交规范)
- [版本发布流程](#版本发布流程)
- [测试要求](#测试要求)

## 提交前必读

1. 先读 [AGENTS.md](../AGENTS.md) 的五条准则，尤其是第 5 条"内核纯粹"。
2. 涉及配置改动时，先读 [docs/CONFIGURATION.md](CONFIGURATION.md) 确认改的是哪一层配置文件，不要把面板会覆盖的运行态配置当成长期维护对象。
3. 涉及跨模块改动（比如网关改了转发逻辑）时，先在 [docs/ARCHITECTURE.md](ARCHITECTURE.md) 里确认对应模块的职责边界，不要越界实现。
4. 涉及 Dashboard 或 Tauri 时，先读 [docs/ARCHITECTURE.md](ARCHITECTURE.md) 确认 Dashboard 仍是配置、进程和数据的唯一控制面。

## 改哪里、不改哪里

| 想做的事 | 应该改的位置 | 严禁改动 |
| --- | --- | --- |
| 支持一个上游没有原生支持的请求字段/适配 | `CLIProxyAPI-LocalPlugin/` | `CLIProxyAPI/CLIProxyAPI/` 内核源码 |
| 调整对外暴露哪些模型别名 | 面板 UI 生成的 `cliproxyapi-active-config.yaml`，或面板后端逻辑 | 直接改内核路由代码 |
| 新增一种媒体模型的请求格式 | `CLIProxyAPI-MediaProxy/config.example.json` 里加 `auth_providers` 规则 | 不要在内核里加媒体处理逻辑 |
| 面板功能（UI、进程管理、日志展示） | `CLIProxyAPI-Dashboard/backend/`、`sections/`、`js/` | — |
| 升级官方内核版本 | 运行 `update-core.ps1`，不要手工拷贝文件 | 手工合并内核代码 |

任何一个改动如果发现"必须改 `CLIProxyAPI/CLIProxyAPI/` 才能实现"，先停下来重新想能不能在插件层/网关层做到；如果确实不能，说明这是要提给上游的改动，不属于本仓库范畴。

## 提交规范

Commit message 参考现有历史（`git log --oneline`），采用 `<type>(<scope>): <summary>` 的松散 Conventional Commits 风格，`type` 常见取值：`feat` / `fix` / `docs` / `release` / `merge`。中英文均可，示例：

```
feat(dashboard): support model pool reference presets
fix(chat): keep remote videos as link-only results
docs: 记录内核纯粹原则及一键升级导引指南
```

## 版本发布流程

1. 确认改动已经过 [测试要求](#测试要求) 中对应模块的验证。
2. 更新 `VERSION`（本工作区版本，SemVer）。
3. 在 [CHANGELOG.md](../CHANGELOG.md) 顶部按 [Keep a Changelog](https://keepachangelog.com/en/1.0.0/) 格式添加条目，区分 `Added` / `Changed` / `Fixed`。
4. 如果本次发布同时升级了官方内核版本，确认 `UPSTREAM_VERSION` 已由 `update-core.ps1` 更新，并在 Changelog 里注明对应的上游 Tag。
5. 打 tag、push 到 `origin`（不要 push 到 `upstream-cpa`）。

## 测试要求

各模块自带测试，提交前按改动范围至少跑对应模块的测试：

| 模块 | 测试命令 |
| --- | --- |
| `CLIProxyAPI-AccessGateway/` | `go test ./...`（含 `main_test.go`） |
| `CLIProxyAPI-LocalPlugin/` | `.\build.ps1`（内部会跑 `go test`，除非传 `-SkipTests`） |
| `CLIProxyAPI-MediaProxy/` | `.\build.ps1`（同上） |
| `CLIProxyAPI-Dashboard/` | `CLIProxyAPI-Dashboard/tests/` 下的 pytest 用例 |
| `apps/tauri-gui/` | 在 `src-tauri/` 下运行 `cargo test`，并执行 `npm run build:windows` 验证 Windows 安装包构建 |
| 内核升级 | `update-core.ps1` 会自动依次验证内核、插件、MediaProxy、Dashboard 的构建，全部通过才更新 `UPSTREAM_VERSION` |

改动只涉及文档（`*.md`）时可以跳过上述测试，但要检查文档里引用的路径、命令、字段名与实际代码/配置一致。
