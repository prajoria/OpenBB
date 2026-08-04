#!/usr/bin/env bash
# Auth-invariant grep guards (#1817).
#
# Codifies ADR 2026-08-04-vscode-terminal-webview-auth.md §5. All four
# greps below MUST return zero matches; any hit is a regression on the
# CSP / auth model and fails CI.

set -u
cd "$(dirname "$0")/.." || exit 2

fail=0
declare -a failures=()

check() {
  local label="$1"
  local pattern="$2"
  shift 2
  # -q would suppress paths; we want the matches for the failure report.
  if grep -rE "$pattern" "$@" > /tmp/verify-auth-$$.out 2>/dev/null; then
    if [ -s /tmp/verify-auth-$$.out ]; then
      failures+=("$label")
      echo "FAIL: $label"
      sed 's/^/  /' /tmp/verify-auth-$$.out
      fail=1
    fi
  fi
  rm -f /tmp/verify-auth-$$.out
}

check "Authorization: Bearer header present"       "Authorization:\s*Bearer"  src/ media/
check "'unsafe-eval' in CSP"                        "'unsafe-eval'"            src/ media/
check "connect-src wildcard"                        "connect-src[^;]*\*"       src/
check "?token= in URL"                              "\?token="                 src/ media/

if [ "$fail" -eq 0 ]; then
  echo "OK: 4/4 auth invariants held."
  exit 0
fi

echo ""
echo "Failed invariants: ${failures[*]}"
exit 1
