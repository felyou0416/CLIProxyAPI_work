# AGENTS.md

Core behavioral guidelines. Full version: `skills/karpathy-guidelines/SKILL.md`

1. **Think first** — state assumptions, ask when uncertain, present tradeoffs
2. **Simplicity first** — minimum code, no speculative features, no over-engineering
3. **Surgical changes** — touch only what's needed, match existing style, clean up only your own mess
4. **Goal-driven** — define verifiable success criteria, plan multi-step tasks, loop until verified

**Project layout:**
- `CLIProxyAPI/CLIProxyAPI/` — Go proxy server core
- `CLIProxyAPI-Dashboard/` — Python + web dashboard (PyInstaller + Electron)
- `.github/workflows/build-electron.yml` — CI build & release pipeline
- `VERSION` — current version (e.g. `1.0.1`); release with `git tag v1.0.x && git push origin v1.0.x`
