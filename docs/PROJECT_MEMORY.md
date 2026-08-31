# 项目维护记忆

> 这份文件是可提交到 Git 的项目记忆，记录容易在后续修改中丢失的配置事实、边界和验证方法。它不是运行时配置，也不保存 API Key、Cookie 或其他凭据。

## 维护边界

- `CLIProxyAPI/CLIProxyAPI/` 是官方 Go 内核镜像，遵循内核纯粹原则，不在其中加入本地业务补丁。
- 本地二次开发放在 `CLIProxyAPI-Dashboard/`、`CLIProxyAPI-AccessGateway/`、`CLIProxyAPI-LocalPlugin/` 和 `CLIProxyAPI-MediaProxy/`。
- `CLIProxyAPI/storage/` 是本机运行数据目录。它可能包含明文凭据，已被 Git 忽略；文档只记录结构和规则，不记录具体密钥。

## 配置来源与生效顺序

| 层级 | 文件 | 作用 | 维护方式 |
| --- | --- | --- | --- |
| 基础配置 | `CLIProxyAPI/storage/config/base-config.yaml` | Dashboard 生成运行态配置时的模板和手写默认值 | 可长期维护 |
| 生成规则 | `CLIProxyAPI-Dashboard/backend/auth.py` | 根据认证、模型映射和面板状态生成 YAML | 修改代码并补测试 |
| 运行态配置 | `CLIProxyAPI/storage/runtime/cliproxyapi-active-config.yaml` | 当前内核、网关和插件实际读取的配置 | 不要长期手改；由 Dashboard 重建 |
| 插件覆盖 | `CLIProxyAPI/storage/models/model_thinking_configs.json` | LocalPlugin 的模型级请求拦截配置，目前主要用于 Agnes thinking 适配 | 通过 Dashboard 保存 |

运行态配置由 `backend.auth.rebuild_runtime_config_from_state()` 生成。写入后，内核会监视该文件并热加载；如果进程没有运行，则下次启动时读取新文件。

## 推理强度能力声明

### 问题背景

OpenAI-compatible 模型如果没有 `thinking` 节点，内核会使用保守默认能力：

```yaml
thinking:
  levels: ["low", "medium", "high"]
```

请求中的 `xhigh` 或 `max` 不在这个列表时，统一 thinking 校验会把它钳制到最高已知等级 `high`。这会改变实际发往上游的请求，不只是面板显示问题。

静态模型目录可能已经声明更高能力，但选中的 API-key 模型能力快照优先于静态目录。因此，OpenAI-compatible 配置必须在模型条目上显式声明上游实际支持的等级。

### 当前实现

推理能力声明支持 **“UI 可视化配置优先 + 内置白名单兜底”** 双层机制：

1. **Dashboard 系统中心配置**：
   在「系统中心 -> 模型思考/推理配置」页面中，可直观选择或添加特定模型，并配置其推理等级能力声明（如 `扩展 5 级 [low, medium, high, xhigh, max]`、`全量 6 级`、`标准 3 级` 或自定义等级）。
   点击「保存配置」后，后端 `save_model_thinking_configs` 会持久化至 `model_thinking_configs.json`，并自动触发 `rebuild_runtime_config_from_state()` 重新生成运行态 YAML 并由 Go 内核热加载。
2. **内置白名单兜底**：
   `CLIProxyAPI-Dashboard/backend/auth.py` 中的 `_OPENAI_COMPAT_EXTENDED_THINKING_LEVELS` 作为系统内置兜底白名单（包含 `gpt-5.6-sol`、`gpt-5.6-terra`、`gpt-5.6-luna`）。
3. **YAML 运行态生成结果**：

```yaml
openai-compatibility:
  - name: "ung"
    base-url: "https://provider.example/v1"
    models:
      - name: "gpt-5.6-sol"
        alias: "ung-gpt-5.6-sol"
        thinking:
          levels: ["low", "medium", "high", "xhigh", "max"]
```

模型名带 `(max)`、`(xhigh)` 后缀，或带 `openai/` 前缀时，生成器会先归一化底层模型名再匹配能力。未配置且未在白名单中的未知模型不会自动声明扩展等级，避免误报上游能力。

### 新增/优化模型推理等级的操作步骤

**方式一（推荐：面板可视化操作）：**
1. 进入 Dashboard「系统中心」->「思考/推理配置」。
2. 在下拉框选择已有模型或输入模型 ID，选择所需能力声明预设（如「扩展 5 级」）并点击添加。
3. 点击页面右上角「保存配置」，面板会自动保存并同步重建运行时配置，Go 内核立即热加载生效。

**方式二（代码级内置白名单）：**
1. 在 `_OPENAI_COMPAT_EXTENDED_THINKING_LEVELS` 增加规范化后的上游模型 ID。
2. 在 `CLIProxyAPI-Dashboard/tests/test_model_thinking.py` 与 `test_model_pool.py` 补充测试用例。
3. 运行全量测试并应用运行时配置。

### 维护原则

- 不要为了放宽单个 OpenAI-compatible 模型而侵入修改 `CLIProxyAPI/CLIProxyAPI/` 内核默认策略。
- 优先通过 Dashboard 面板对特定模型进行配置与优化，保存时会自动打通内核能力声明。
- 不要把未知模型统一标记为支持 `max`；上游不支持时应让上游明确返回错误，而不是在代理侧伪造能力。

## 请求排查路径

当再次出现“输入是 `max/xhigh`，上游变成 `high`”时，按以下顺序检查：

1. 原始请求日志中的请求体是否包含目标 effort。
2. `cliproxyapi-active-config.yaml` 的目标模型条目是否存在完整 `thinking.levels`。
3. 内核是否已检测到配置文件变化并完成 reload。
4. 同一日志的 `API REQUEST` 上游 Body 是否仍被写成 `reasoning_effort: "high"`。
5. 如果 YAML 已正确，检查是否实际路由到了另一个同名模型节点或另一个 alias；多节点能力必须分别声明并保持一致。

当前执行链的关键位置：

```text
客户端请求
  -> OpenAI/Claude 请求翻译
  -> ApplyRequestThinking
  -> 选中 API-key 模型能力快照
  -> 校验/钳制 effort
  -> OpenAI-compatible 上游请求
```

## 维护检查清单

- [ ] 修改生成规则后同步添加回归测试。
- [ ] 不把运行态文件当作长期源文件提交或手改维护。
- [ ] 不在日志、文档或记忆中记录 API Key、Cookie、Token 或完整 Authorization 值。
- [ ] 内核升级后重新确认模型能力字段和 `thinking.levels` 的 YAML schema。
- [ ] 运行 `git diff --check`，再运行 Dashboard 全量测试。

## 本次修复记录

- 日期：2026-08-31。
- 现象：`ung` OpenAI-compatible 路由的 `gpt-5.6-sol/terra` 请求中，入口 `max/xhigh` 被实际出站请求降为 `high`。
- 根因：生成的模型条目缺少 `thinking.levels`，命中内核默认 `[low, medium, high]`。
- 修复：Dashboard 生成器为 `gpt-5.6-sol/terra/luna` 写入 `[low, medium, high, xhigh, max]`，未知模型保持默认行为。
- 验证：Dashboard 全量单元测试 153 项通过；运行态配置已重建并被内核热加载。
