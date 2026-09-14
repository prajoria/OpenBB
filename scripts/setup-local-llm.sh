#!/usr/bin/env bash
# Preflight the OpenBB local LLM development environment.
# This initial bootstrap slice is offline-safe: --no-download never installs
# Ollama or a model, making it suitable for CI and capability checks.

set -euo pipefail

profile="nvidia-3080"
no_download=false
verify=false

usage() {
    cat <<'EOF'
Usage: scripts/setup-local-llm.sh [--profile NAME] [--no-download] [--verify]

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
            model="qwen2.5-coder:7b"; quantization="Q5_K_M"; context_tokens=8192; minimum_vram_gb=12; minimum_disk_gb=9 ;;
        nvidia-3090)
            model="qwen2.5-coder:14b"; quantization="Q4_K_M"; context_tokens=16384; minimum_vram_gb=24; minimum_disk_gb=14 ;;
        nvidia-24gb)
            model="qwen2.5-coder:14b"; quantization="Q5_K_M"; context_tokens=16384; minimum_vram_gb=24; minimum_disk_gb=15 ;;
        nvidia-48gb)
            model="qwen2.5-coder:32b"; quantization="Q4_K_M"; context_tokens=32768; minimum_vram_gb=48; minimum_disk_gb=28 ;;
        nvidia-80gb-plus)
            model="qwen2.5-coder:32b"; quantization="BF16"; context_tokens=32768; minimum_vram_gb=80; minimum_disk_gb=72 ;;
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

printf 'Profile: %s\nModel: %s\nQuantization: %s\nContext tokens: %s\nOllama installed: %s\nDownloads skipped: %s\n' \
    "$profile" "$model" "$quantization" "$context_tokens" "$ollama_installed" "$no_download"

if [[ "$no_download" == true ]]; then
    printf 'No-download selected; no runtime or model was installed.\n'
elif [[ "$ollama_installed" == false ]]; then
    printf 'Ollama is not installed. Re-run with --no-download for preflight only.\n' >&2
    exit 1
elif [[ "$verify" == true ]]; then
    printf 'Verification-only mode is not implemented yet.\n'
else
    printf 'Model installation is not implemented yet. Re-run with --no-download for preflight only.\n' >&2
    exit 1
fi