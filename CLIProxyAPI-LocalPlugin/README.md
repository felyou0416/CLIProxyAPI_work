# CLIProxyAPI Local Plugin

Out-of-tree extensions for the stock CLIProxyAPI kernel.

The plugin currently provides:

- Agnes `chat_template_kwargs.enable_thinking` request adaptation.
- Dashboard per-model thinking overrides.
- Explicit routing of Agnes image/video aliases to the local MediaProxy provider.
- A plugin status resource at `/v0/resource/plugins/cliproxy-local/status`.

## Build

Windows builds use Go c-shared mode with Zig as the C toolchain:

```powershell
winget install --id zig.zig --exact
.\build.ps1
```

The output is `dist/windows-amd64/cliproxy-local.dll`.

## Runtime

The Dashboard writes the required `plugins` block into the generated CPA runtime config. The stock CPA kernel loads the DLL without source patches.
