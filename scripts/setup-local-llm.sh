#!/usr/bin/env bash
# Preflight the OpenBB local LLM development environment.
# This initial bootstrap slice is offline-safe: --no-download never installs
# Ollama or a model, making it suitable for CI and capability checks.

set -euo pipefail

profile="nvidia-3080"
no_download=false
verify=false
what_if=false

usage() {
    cat <<'EOF'
Usage: scripts/setup-local-llm.sh [--profile NAME] [--no-download] [--verify] [--what-if]

Supported profiles:
  nvidia-3080, nvidia-3080-12gb, nvidia-3090, nvidia-24gb,
  nvidia-48gb, nvidia-80gb-plus
EOF
}

resolve_profile() {
    case "$1" in
        nvidia-3080)
            model="qwen2.5-coder:7b"; quantization="Q4_K_M"; context_tokens=8192; minimum_vram_gb=10; minimum_disk_gb=8 ;;
        nvidia-3080-12gb)
            model="qwen2.5-coder:7b"; quantization="Q4_K_M"; context_tokens=8192; minimum_vram_gb=12; minimum_disk_gb=9 ;;
        nvidia-3090)
            model="qwen2.5-coder:14b"; quantization="Q4_K_M"; context_tokens=16384; minimum_vram_gb=24; minimum_disk_gb=14 ;;
        nvidia-24gb)
            model="qwen2.5-coder:14b"; quantization="Q4_K_M"; context_tokens=16384; minimum_vram_gb=24; minimum_disk_gb=15 ;;
        nvidia-48gb)
            model="qwen2.5-coder:32b"; quantization="Q4_K_M"; context_tokens=32768; minimum_vram_gb=48; minimum_disk_gb=28 ;;
        nvidia-80gb-plus)
            model="qwen2.5-coder:32b"; quantization="Q4_K_M"; context_tokens=32768; minimum_vram_gb=80; minimum_disk_gb=72 ;;
        *)
            printf "Unsupported profile '%s'. Supported profiles: nvidia-3080, nvidia-3080-12gb, nvidia-3090, nvidia-24gb, nvidia-48gb, nvidia-80gb-plus.\n" "$1" >&2
            return 1 ;;
    esac
}

while (($# > 0)); do
    case "$1" in
        --profile)
            profile="${2:?--profile requires a value}"
            shift 2 ;;
        --no-download)
            no_download=true
            shift ;;
        --verify)
            verify=true
            shift ;;
        --what-if)
            what_if=true
            shift ;;
        --help|-h)
            usage
            exit 0 ;;
        *)
            printf "Unknown argument: %s\n" "$1" >&2
            usage >&2
            exit 2 ;;
    esac
done

resolve_profile "$profile"

if command -v ollama >/dev/null 2>&1; then
    ollama_installed=true
else
    ollama_installed=false
fi

runtime_command=""
if [[ "$ollama_installed" == false ]]; then
    runtime_command="curl -fsSL https://ollama.com/install.sh | sh"
fi
model_command="ollama pull $model"

if command -v nvidia-smi >/dev/null 2>&1; then
    available_vram_gb="$(nvidia-smi --query-gpu=memory.total --format=csv,noheader,nounits | awk 'BEGIN { max = 0 } { if ($1 > max) max = $1 } END { print int(max / 1024) }')"
else
    available_vram_gb=0
fi
available_disk_gb="$(df -Pk "$HOME" | awk 'NR == 2 { print int($4 / 1024 / 1024) }')"

failure_reasons=()
if (( available_vram_gb < minimum_vram_gb )); then
    failure_reasons+=("requires ${minimum_vram_gb} GB VRAM; detected ${available_vram_gb} GB")
fi
if (( available_disk_gb < minimum_disk_gb )); then
    failure_reasons+=("requires ${minimum_disk_gb} GB free disk; detected ${available_disk_gb} GB")
fi

printf 'Profile: %s\nModel: %s\nQuantization: %s\nContext tokens: %s\nAvailable VRAM: %s GB\nAvailable disk: %s GB\nOllama installed: %s\nDownloads skipped: %s\n' \
    "$profile" "$model" "$quantization" "$context_tokens" "$available_vram_gb" "$available_disk_gb" "$ollama_installed" "$no_download"

if ((${#failure_reasons[@]} > 0)); then
    printf "Profile '%s' is not supported on this machine: %s\n" "$profile" "$(IFS='; '; echo "${failure_reasons[*]}")" >&2
    exit 1
fi

if [[ "$what_if" == true ]]; then
    [[ -z "$runtime_command" ]] || printf 'Would run: %s\n' "$runtime_command"
    printf 'Would run: %s\n' "$model_command"
elif [[ "$verify" == true ]]; then
    if [[ "$ollama_installed" == false ]]; then
        printf 'Ollama is not installed, so verification cannot run.\n' >&2
        exit 1
    fi
    printf 'Verification-only mode is not implemented yet.\n' >&2
    exit 1
elif [[ "$no_download" == true ]]; then
    printf 'No-download selected; no runtime or model was installed.\n'
else
    if [[ -n "$runtime_command" ]]; then
        printf 'Installing Ollama...\n'
        curl -fsSL https://ollama.com/install.sh | sh
    fi
    command -v ollama >/dev/null 2>&1 || { printf 'Ollama was installed but is not available. Restart the shell and re-run this script.\n' >&2; exit 1; }
    printf 'Downloading %s...\n' "$model"
    ollama pull "$model"
    printf 'Local LLM setup complete.\n'
fi
