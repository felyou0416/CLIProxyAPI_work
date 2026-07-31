# AGENTS.md

Core behavioral guidelines. Full version: `skills/karpathy-guidelines/SKILL.md`

1. **Think first** — state assumptions, ask when uncertain, present tradeoffs
2. **Simplicity first** — minimum code, no speculative features, no over-engineering
3. **Surgical changes** — touch only what's needed, match existing style, clean up only your own mess
4. **Goal-driven** — define verifiable success criteria, plan multi-step tasks, loop until verified
5. **Kernel Purity** — 遵循“内核纯粹”原则：保持 Go 原生内核代码 (`CLIProxyAPI/CLIProxyAPI/`) 的独立性与纯粹性，绝不侵入修改内核代码。未来升级上游内核时，直接运行 `.\update-core.ps1` (或 `.\update-core.ps1 -TargetVersion v7.x.x`) 即可一键拉取上游最新 Tag 并同步构建。所有二次开发与面板调度均在面板层 (`CLIProxyAPI-Dashboard`) 或外层插件中进行。

**Project layout:**
- `CLIProxyAPI/CLIProxyAPI/` — Go proxy server core (保持原生纯粹)
- `CLIProxyAPI-Dashboard/` — Python + web dashboard (PyInstaller + Electron)
- `update-core.ps1` — 核心内核升级脚本 (一键拉取上游 Tag 并同步构建)
- `.github/workflows/build-electron.yml` — CI build & release pipeline
- `VERSION` / `UPSTREAM_VERSION` — 当前版本及上游内核版本 (例如 `v7.2.111`)
