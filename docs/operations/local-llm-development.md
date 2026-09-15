# Local LLM Developer Guide

This guide sets up a local coding model for OpenBB development. The model runs
on your workstation through Ollama; source code, prompts, and model responses
do not need to leave the machine for local inference. Use it for routine code
navigation, drafting, and small development tasks. The OpenBB test, review,
security, and pull-request requirements remain unchanged.

This is contributor tooling. It does not change a product-facing OpenBB model
or add a local model to GitHub Copilot's built-in model picker.

## What You Will Set Up

1. Ollama, a local model runtime bound to your computer.
2. A Qwen2.5-Coder model appropriate for your NVIDIA GPU.
3. A local API at `http://127.0.0.1:11434`.
4. The official Ollama VS Code language-model provider, so the local model
	appears in VS Code's standard model picker.

## Before You Start

You need:

- A clone of this repository and a terminal opened at its root.
- Windows 11 with PowerShell 7, or Linux with Bash.
- NVIDIA drivers and `nvidia-smi` for the profiles below.
- Internet access for the first installation and model download.
- Free local SSD space. Ollama stores model weights outside this repository.

The included setup scripts currently target NVIDIA GPUs. They deliberately
reject a profile that exceeds the detected GPU memory or disk capacity. Do not
work around that check by selecting a larger profile.

## Choose a Profile

Select the smallest profile that meets the quality needed for the task. The
model tag is what you will select later in VS Code.

| Profile | Minimum GPU memory | Model tag | Context | Minimum disk |
|---|---:|---|---:|---:|
| `nvidia-3080` | 10 GB | `qwen2.5-coder:7b` | 8K | 8 GB |
| `nvidia-3080-12gb` | 12 GB | `qwen2.5-coder:7b` | 8K | 9 GB |
| `nvidia-3090` | 24 GB | `qwen2.5-coder:14b` | 16K | 14 GB |
| `nvidia-24gb` | 24 GB | `qwen2.5-coder:14b` | 16K | 15 GB |
| `nvidia-48gb` | 48 GB | `qwen2.5-coder:32b` | 32K | 28 GB |
| `nvidia-80gb-plus` | 80 GB | `qwen2.5-coder:32b` | 32K | 72 GB |

For example, use `nvidia-3090` for a 24 GB card. Use a hosted model when the
local model cannot handle the task reliably; local models are not expected to
match frontier hosted-model quality.

### Optional Models for a 24 GB GPU

The setup script installs the reliable `qwen2.5-coder:14b` baseline. On a 24
GB NVIDIA GPU, install one of these optional models for higher-capability
coding work after completing the baseline setup:

| Model | Download size | Best use | Trade-off |
|---|---:|---|---|
| `qwen3-coder:30b` | 19 GB | Best local choice for code editing and agentic tool use | Use a modest context; its 256K advertised maximum does not fit in 24 GB VRAM with the model. |
| `devstral:24b` | 14 GB | Faster agentic coding and multi-file tasks | Smaller than Qwen3-Coder 30B, but leaves more VRAM headroom. |

Do not attempt to run Qwen3-Coder 480B locally: it requires about 250 GB of
memory. A larger model that spills most layers into system RAM is usually too
slow for interactive agent work.

## Step 1: Open the Repository

Open the OpenBB repository folder in a terminal. All commands in this guide
are relative to that repository root. Check that Git sees the repository
before installing anything:

```powershell
git status --short --branch
```

## Step 2: Run a Safe Hardware Preflight

The preflight does not install Ollama or download a model. Replace the example
profile with the one you selected above.

Windows:

```powershell
.\scripts\setup-local-llm.ps1 -Profile nvidia-3090 -NoDownload
```

Linux:

```bash
./scripts/setup-local-llm.sh --profile nvidia-3090 --no-download
```

Read the `Available VRAM`, `Available disk`, `Model`, and `IsCompatible`
values. Stop here if the profile is incompatible. Choose a smaller supported
profile or free enough disk space before continuing.

To preview the commands that setup would run without changing your machine:

```powershell
.\scripts\setup-local-llm.ps1 -Profile nvidia-3090 -WhatIf
```

```bash
./scripts/setup-local-llm.sh --profile nvidia-3090 --what-if
```

## Step 3: Install Ollama and Download the Model

The setup command installs Ollama only when it is not already present, then
downloads the selected model. The initial download can be 5-20 GB or more.

Windows:

```powershell
.\scripts\setup-local-llm.ps1 -Profile nvidia-3090
```

Linux:

```bash
./scripts/setup-local-llm.sh --profile nvidia-3090
```

On Windows, close and reopen the terminal if setup says Ollama was installed
but cannot be found. Confirm that Ollama's per-user installation directory is
on `PATH` before rerunning the setup command.

## Step 4: Confirm Local Inference Works

List the installed models. The selected model tag must appear in the output:

```powershell
ollama list
```

Run a short prompt, substituting your selected model tag:

```powershell
ollama run qwen2.5-coder:14b "Reply with exactly: OpenBB local LLM ready"
```

Expected response:

```text
OpenBB local LLM ready
```

Confirm the local service is reachable. This endpoint stays on loopback and
is not intended to be exposed to a network:

```powershell
Invoke-RestMethod http://127.0.0.1:11434/api/tags
```

```bash
curl http://127.0.0.1:11434/api/tags
```

If these commands fail, start the Ollama application/service and retry. Do not
put `127.0.0.1:11434` behind a public tunnel or reverse proxy.

## Step 5: Install Higher-Capability Models (Optional)

For a 24 GB GPU, pull either or both optional models listed above. These pulls
do not remove the baseline model:

```powershell
ollama pull qwen3-coder:30b
ollama pull devstral:24b
ollama list
```

Use `qwen3-coder:30b` when quality on complex coding and tool-use tasks is the
priority. Use `devstral:24b` when faster responses and more context headroom
matter. Keep `qwen2.5-coder:14b` for short, lower-latency interactions.

Run a short prompt against each new model before selecting it in VS Code:

```powershell
ollama run qwen3-coder:30b "Reply with exactly: OpenBB local LLM ready"
ollama run devstral:24b "Reply with exactly: OpenBB local LLM ready"
```

## Step 6: Use the Model in VS Code

VS Code supports local models through language-model provider extensions. Use
the official provider published by Ollama; it discovers models from the local
Ollama server automatically.

1. In VS Code, open **Extensions** (`Ctrl+Shift+X`).
2. Search for `Ollama` and install **Ollama** published by **Ollama**. Confirm
	its extension identifier is `Ollama.ollama`.
3. Reload the VS Code window when prompted. You can also run **Developer:
	Reload Window** from the Command Palette.
4. Open the Chat view, then open its model picker and choose **Manage Models**.
5. Enable the **Ollama** provider if it is listed as disabled. Its default URL
	is `http://127.0.0.1:11434`; leave it unchanged for a local installation.
6. Select a model discovered by the provider, such as `qwen3-coder:30b`,
	`devstral:24b`, or `qwen2.5-coder:14b`.
7. In the OpenBB workspace, submit a read-only request such as `Summarize the
	purpose of this file without editing it.`

The Ollama provider exposes every tag returned by `ollama list` unless its
provider configuration restricts the model list. Run **Ollama: Refresh Models**
from the Command Palette after pulling a new model. Run **Ollama: Diagnose
Models** if the picker is empty.

The provider remains local by default: it calls only `http://127.0.0.1:11434`.
GitHub Copilot and Azure BYOK models can stay available in the same VS Code
model picker; select the model appropriate to each task.

## Step 7: Work Safely in This Repository

Local inference is not an exemption from repository rules. Before using the
model to make a change:

1. Work from an issue-specific side branch, never directly on `portfolio`.
2. Keep real brokerage exports, credentials, tokens, and `.env` contents out
	of prompts and attachments.
3. Review every proposed edit before applying it.
4. Run the relevant tests, type checks, and linters yourself.
5. Use the existing issue and pull-request workflow for every change.

The model has access only to context you explicitly provide or allow the VS
Code extension to read. Treat repository instructions, tests, and code review
as the source of truth.

## Daily Use

Ollama normally starts with its desktop installation or service. Before a
development session, verify the model and endpoint:

```powershell
ollama list
Invoke-RestMethod http://127.0.0.1:11434/api/tags
```

Then open the OpenBB workspace in VS Code and select your Ollama model from
Chat's standard model picker. Use `Ctrl+C` to stop an interactive `ollama run`
session. Model files remain in Ollama's user cache, not in this repository.

## Troubleshooting

| Problem | Resolution |
|---|---|
| Profile is rejected | Select a profile whose VRAM and disk requirements pass the preflight. |
| `nvidia-smi` is unavailable | Install or update the NVIDIA driver, then open a new terminal. |
| `ollama` is not recognized after setup | Restart the terminal. On Windows, confirm Ollama's per-user installation directory is on `PATH`. |
| The model download stopped | Rerun the same setup command; Ollama reuses downloaded layers. |
| `api/tags` does not respond | Start Ollama, then retry `http://127.0.0.1:11434/api/tags`. |
| VS Code cannot see the model | Confirm `ollama list` shows the exact tag, run **Ollama: Refresh Models**, and reload the VS Code window. Use **Ollama: Diagnose Models** if it remains missing. |
| Model is slow or runs out of memory | Choose a smaller supported profile or use a hosted model for that task. |
| Need an installation preview | Use `-WhatIf` on Windows or `--what-if` on Linux. |

## Model Storage and Licensing

The scripts use the official Ollama installer. Ollama stores model weights in
its user-managed cache outside the repository. Never copy model weights into
Git, a pull request, a Python wheel, or a CI artifact.

The initial profiles use Qwen2.5-Coder Instruct variants under Apache License
2.0. Review the model card and license before selecting a different model.