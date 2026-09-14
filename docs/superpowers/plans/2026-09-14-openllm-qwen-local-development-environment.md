# Proposal: One-Command OpenLLM/Qwen Local Development Environment

**Tracking issue:** #2088

## Goal

Provide a low-friction, fully local LLM development environment for OpenBB contributors so routine agent-assisted work can run without paid Claude or OpenAI API usage. A developer should be able to run one bootstrap command, choose a hardware profile, and obtain a working local inference runtime plus curated Qwen coding models and OpenBB development integrations.

This is a development-environment bootstrap. It must not call an AI model while installing or require users to write prompts, credentials, or manual configuration files.

## Problem

The current development workflow assumes hosted-agent tooling in places. That creates recurring cost and availability pressure. OpenBB already documents a LiteLLM/Ollama local fallback, but it does not provide a supported, reproducible Windows and Linux setup path for local coding models or integrate that path into the `openbb-dev-cycle` workflow.

## Delivery Plan

### 1. Architecture decision and compatibility matrix

- Use Ollama as the default bootstrap runtime for developer machines. It has the smallest operational surface for a small team, manages model download and lifecycle, and exposes a local API at `127.0.0.1:11434`.
- Keep OpenLLM as an evaluated alternative for future service and deployment use cases; do not make it a bootstrap prerequisite.
- Use LiteLLM only as an adapter where an OpenAI-compatible endpoint is required. It is not the local model runtime.
- Define supported operating systems, GPU backends, CPU-only behavior, minimum RAM, VRAM, disk requirements, model licensing, and revision pinning.
- Select the Qwen2.5-Coder Instruct family for the first supported profiles. The upstream 7B, 14B, and 32B model cards are Apache-2.0 licensed.
- Document expected quality and performance boundaries relative to hosted models.

## Proposed NVIDIA Hardware and Model Grid

The bootstrap must select a profile explicitly or recommend one after detecting VRAM. Estimates include model weights and a modest serving margin, but not unlimited context: the KV cache grows with prompt length and concurrent requests. The launcher must set a conservative default context window and reject a profile when free VRAM or disk is insufficient.

| Hardware profile | Typical GPU | VRAM | Selected model | Quantization | Default context | Approx. model storage | Recommended use | Notes |
|---|---:|---:|---|---|---:|---:|---|---|
| `nvidia-3080` | RTX 3080 | 10 GB | Qwen2.5-Coder-7B-Instruct | GGUF `Q4_K_M` | 8K | 5 GB | Inline coding help, small focused edits, test/debug conversations | Supported baseline. Keep one active request; use `Q4_K_M`, not a larger model. |
| `nvidia-3080-12gb` | RTX 3080 12 GB | 12 GB | Qwen2.5-Coder-7B-Instruct | Ollama `Q4_K_M` | 8K | 5 GB | 7B local coding with extra context headroom | The selected Ollama tag is Q4; Q5 is deferred until a pinned, verified tag is available. |
| `nvidia-3090` | RTX 3090 | 24 GB | Qwen2.5-Coder-14B-Instruct | GGUF `Q4_K_M` | 16K | 10 GB | Default full local development workflow | Recommended first-class profile. 32B `Q4_K_M` may fit only with reduced context and no concurrency, so it is opt-in rather than the default. |
| `nvidia-24gb` | RTX 4090, RTX 5090 24 GB, RTX A5000 | 24 GB | Qwen2.5-Coder-14B-Instruct | Ollama `Q4_K_M` | 16K | 10 GB | Interactive coding and review | Same capacity class as 3090. Prefer 14B quality and context headroom over forcing 32B. |
| `nvidia-48gb` | RTX A6000, RTX 6000 Ada, RTX PRO 6000 | 48 GB+ | Qwen2.5-Coder-32B-Instruct | GGUF `Q4_K_M` | 32K | 20 GB | Complex multi-file changes, planning, and code review | First supported 32B profile. `Q5_K_M` may be selected only after a free-VRAM check. |
| `nvidia-80gb-plus` | A100 80 GB, H100, H200, multi-GPU host | 80 GB+ | Qwen2.5-Coder-32B-Instruct | Ollama `Q4_K_M` | 32K | 20 GB | Shared workstation or high-throughput local service | BF16 and Q8 are deferred until the runtime and immutable artifacts are selected and tested. LAN exposure requires explicit configuration. |

### Model and Quantization Policy

- **Version family:** Qwen2.5-Coder Instruct, initially 7B, 14B, and 32B. Pin each downloaded artifact to a tested Ollama model digest or immutable upstream revision in the local install manifest.
- **License:** Apache License 2.0 for the selected upstream Qwen2.5-Coder model cards. The user guide must link the exact model card and license for every installed model; any community quantization must preserve the upstream license and publish its source/provenance.
- **Default quantization:** Ollama `Q4_K_M`, which provides the baseline balance of quality and memory use for local development. `Q5_K_M`, Q8, and BF16 are deferred until the bootstrap can select pinned, verified artifacts that match their declared quantization.
- **Concurrency:** one active generation is the default for 10-24 GB profiles. The bootstrap must not enable parallel requests by default because concurrent KV caches can exhaust VRAM unpredictably.
- **CPU fallback:** Qwen2.5-Coder-7B-Instruct `Q4_K_M` is supported as a slow, opt-in fallback on systems with at least 16 GB RAM and approximately 8 GB free SSD. It is suitable for setup verification and occasional edits, not interactive agent loops.
- **Storage:** install model files in a configurable local SSD cache outside the repository. Default to a user-writable location; support an explicit shared-SSD path for workstations. Never store weights in Git, a wheel, CI cache, or release artifact.
- **Context guard:** 8K, 16K, and 32K are profile defaults, not model limits. The bootstrap must expose an advanced override but warn that longer context raises KV-cache memory use and may force CPU offload or failure.
- **Hosted-provider compatibility:** GPT-5.6 Terra remains a supported hosted development model through the existing Copilot/OpenAI-compatible provider configuration. It is not downloaded, configured, or selected by the local Qwen/Ollama bootstrap; users select it through their authenticated hosted-agent launcher when local capacity or quality is insufficient.

### 2. Idempotent local bootstrap command

- Add equivalent Windows and Linux entry points: `scripts/setup-local-llm.ps1` and `scripts/setup-local-llm.sh`. Both must resolve the same named hardware profiles and produce equivalent preflight output.
- Detect prerequisites: Python, Git, GPU/runtime support, available disk and RAM, required ports, and an existing OpenLLM installation.
- Install or update pinned runtime dependencies without administrator privileges where feasible.
- Support `-Profile`, `-Runtime`, `-Model`, `-NoDownload`, `-Verify`, `-Uninstall`, and non-interactive flags.
- Download only explicitly selected Qwen models, verify upstream checksums when available, and write the installed-version manifest outside the repository.
- Make repeat runs safe: detect healthy installs, repair partial downloads, prevent duplicate model storage, and never modify tracked source files or global Git configuration.

### 3. Local serving and developer integration

- Add a launcher and health-check command that starts a loopback-only local service and reports its OpenAI-compatible/LiteLLM endpoint.
- Generate gitignored local configuration consumed by supported OpenBB development entry points, without storing tokens or secrets.
- Add an explicit local-model option to developer-agent launchers and documentation while preserving hosted-provider behavior.
- Update `openbb-dev-cycle` startup guidance so it detects local capability, but retains every existing design, test, verification, review, and pull-request gate.

### 4. Verification and operational safety

- Test profile resolution, prerequisite checks, command construction, idempotency, failure cleanup, and secret-free config generation.
- Provide an offline simulated mode so CI never downloads multi-gigabyte models.
- Add a smoke test that checks service readiness, makes a minimal OpenAI-compatible completion request, and confirms the developer-agent integration selects the local endpoint.
- Bind to `127.0.0.1` by default, warn before LAN exposure, redact secrets and sensitive paths from logs, and document stop and uninstall procedures.

### 5. Documentation and staged rollout

- Publish a quick start, troubleshooting guide, hardware/model table, expected disk usage, and model-license notice.
- Pilot the supported profiles on Windows developer machines and measure setup success, cold-start time, prompt latency, and failure modes.
- Mark the bootstrap supported only after every documented profile passes the smoke suite; retain the hosted workflow as a documented fallback.

## Acceptance Criteria

- A fresh supported development machine completes setup through one documented command with no AI interaction.
- Windows PowerShell and Linux Bash bootstrap entry points resolve the same named profiles and have equivalent no-download preflight behavior.
- Setup uses an explicit Qwen profile and rejects unsupported hardware selections with an actionable remedy.
- Re-running setup does not redownload healthy artifacts or modify repository-tracked files.
- The local service binds to `127.0.0.1` by default and passes a deterministic health and completion smoke test.
- OpenBB developer tooling selects the local endpoint through documented gitignored configuration.
- `openbb-dev-cycle` supports the local-model path without weakening any delivery gates.
- CI validates install planning and failure paths without downloading models.
- Documentation covers resource requirements, model licenses, supported platforms, and recovery/uninstall steps.

## Non-Goals

- Replacing every hosted model or guaranteeing frontier-model parity.
- Bundling model weights in Git, CI artifacts, releases, or Python wheels.
- Exposing an inference server on the network by default.
- Changing product-facing OpenBB AI behavior before the contributor development path is proven.

## Decisions Required Before Implementation

1. **Question:** Confirm whether OpenLLM is the long-term runtime versus another OpenAI-compatible local runtime supported by LiteLLM/Ollama.

   **Resolution:** Ollama is the default bootstrap runtime for developer processes. OpenLLM remains an evaluated alternative for project service and deployment paths.

2. **Question:** Select Qwen versions, licenses, quantizations, and supported hardware profiles.

   **Resolution:** Use the Qwen2.5-Coder Instruct 7B, 14B, and 32B Apache-2.0 models with the hardware profiles and quantization policy above.

3. **Question:** Prioritize supported launchers: VS Code agent configuration, Claude proxy tooling, OpenBB Agent, or all of them.

   **Resolution:** Support all of them, delivered behind a common local endpoint/configuration contract.

4. **Question:** Decide whether model storage defaults to a user-local cache with an override for shared workstation drives.

   **Resolution:** Use a configurable local-SSD cache, with a shared local-SSD path supported explicitly for workstation installations.