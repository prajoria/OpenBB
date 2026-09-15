# Local LLM Development Setup

OpenBB developers can use Ollama and a Qwen2.5-Coder model locally for routine coding and development tasks. This reduces hosted-model usage while keeping the normal OpenBB test, verification, review, and pull-request requirements unchanged.

## Requirements

- Windows 11 with PowerShell 7, or a supported Linux distribution with Bash.
- NVIDIA drivers and `nvidia-smi` for the GPU profiles below.
- Local SSD capacity for the selected model.
- Internet access for the initial Ollama and model download.

| Profile | GPU memory | Model | Default context | Approximate model storage |
|---|---:|---|---:|---:|
| `nvidia-3080` | 10 GB | Qwen2.5-Coder 7B Q4 | 8K | 5 GB |
| `nvidia-3080-12gb` | 12 GB | Qwen2.5-Coder 7B Q4 | 8K | 5 GB |
| `nvidia-3090` | 24 GB | Qwen2.5-Coder 14B Q4 | 16K | 10 GB |
| `nvidia-24gb` | 24 GB | Qwen2.5-Coder 14B Q4 | 16K | 10 GB |
| `nvidia-48gb` | 48 GB | Qwen2.5-Coder 32B Q4 | 32K | 20 GB |
| `nvidia-80gb-plus` | 80 GB | Qwen2.5-Coder 32B Q4 | 32K | 20 GB |

## Setup

Run a no-side-effect preflight first. It detects NVIDIA VRAM and local free disk, and confirms the selected profile can run on the machine.

Windows:

```powershell
.\scripts\setup-local-llm.ps1 -Profile nvidia-3090 -NoDownload
```

Linux:

```bash
./scripts/setup-local-llm.sh --profile nvidia-3090 --no-download
```

Preview the exact install and model-download commands:

```powershell
.\scripts\setup-local-llm.ps1 -Profile nvidia-3090 -WhatIf
```

```bash
./scripts/setup-local-llm.sh --profile nvidia-3090 --what-if
```

After reviewing the output, run setup. It installs Ollama when absent and downloads the selected model. This can download 5-20 GB or more, depending on the profile.

Windows:

```powershell
.\scripts\setup-local-llm.ps1 -Profile nvidia-3090
```

Linux:

```bash
./scripts/setup-local-llm.sh --profile nvidia-3090
```

Confirm that the downloaded model accepts a local request:

```powershell
ollama list
ollama run qwen2.5-coder:14b "Reply with exactly: OpenBB local LLM ready"
```

On Windows, open a new terminal if `ollama` is not yet on `PATH`; its standard
per-user installation path is `%LOCALAPPDATA%\Programs\Ollama\ollama.exe`.

## Safety and Model Choice

The scripts use the official Ollama installer. Model weights are stored outside the repository by Ollama and must never be committed.

The initial profiles use Qwen2.5-Coder Instruct model variants under Apache License 2.0. The exact local model tag is shown in preflight output.

GPT-5.6 Terra remains available through authenticated hosted-provider tooling. It is not part of this local setup and is appropriate when the local profile cannot provide sufficient quality or capacity.

## Troubleshooting

- **Unsupported profile:** choose one whose minimum VRAM and disk requirements match preflight output.
- **Ollama unavailable after installation:** restart the terminal, then rerun the setup command.
- **Download interrupted:** rerun the same setup command; Ollama reuses available model layers.
- **Need a dry run:** use `-WhatIf` on Windows or `--what-if` on Linux. No runtime or model is installed.