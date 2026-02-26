# PromptTool

A desktop prompt engineering toolkit built with Avalonia (.NET) for managing templates, wildcards, history, and image generation workflows.

## Requirements
- .NET SDK 9.x

## Run Locally
```bash
dotnet run --project PromptTool
```

## Publish Binaries
macOS (Apple Silicon):
```bash
dotnet publish PromptTool -c Release -r osx-arm64 --self-contained true -p:PublishSingleFile=true
```

macOS (Intel):
```bash
dotnet publish PromptTool -c Release -r osx-x64 --self-contained true -p:PublishSingleFile=true
```

Windows (x64):
```bash
dotnet publish PromptTool -c Release -r win-x64 --self-contained true -p:PublishSingleFile=true
```

Linux (x64):
```bash
dotnet publish PromptTool -c Release -r linux-x64 --self-contained true -p:PublishSingleFile=true
```

Linux (ARM64):
```bash
dotnet publish PromptTool -c Release -r linux-arm64 --self-contained true -p:PublishSingleFile=true
```

Output path:
`PromptTool/bin/Release/net9.0/<rid>/publish/`

## Data Locations
- App config:
  - macOS: `~/Library/Application Support/PromptTool/`
  - Windows: `%LOCALAPPDATA%\\PromptTool\\`
  - Linux: `~/.local/share/PromptTool/`
- Backups (auto): `backups/` under the app config directory

## Key Features
- Templates and wildcards management
- History and favorites viewers
- Analytics studio
- InvokeAI and Ollama integrations
- Backup/restore tools
- Remote aesthetic scorer deployment

## Troubleshooting
- macOS RenderTimer crash: if Avalonia fails to start with `RenderTimer` errors, try upgrading Avalonia or using a different host machine.
