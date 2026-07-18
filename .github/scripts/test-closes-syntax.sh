#!/usr/bin/env bash
# Tests for the closes-syntax check function used by
# .github/workflows/portfolio-intel-closes-syntax.yml
#
# Design: docs/superpowers/specs/2026-07-16-gh-826-closes-syntax-design.md
# Issue:  #826
#
# RED phase: run this before implementing check_closes_syntax(); every
# fixture should fail-to-execute because the function doesn't exist yet.
# GREEN phase: fixture 1-12 pass exactly as marked.
#
# Usage: bash .github/scripts/test-closes-syntax.sh

set -u  # NOT set -e: we deliberately let cases fail and count outcomes.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=./closes-syntax-check.sh
source "$SCRIPT_DIR/closes-syntax-check.sh"

PASS=0
FAIL=0
FAILURES=()

expect() {
  local expected=$1     # "PASS" or "FAIL"
  local desc=$2
  local body=$3
  # The function under test: check_closes_syntax reads body from stdin,
  # exits 0 on pass, non-zero on fail. Stderr carries the error message.
  local out rc
  out=$(printf '%s' "$body" | check_closes_syntax 2>&1); rc=$?
  local actual
  if [ $rc -eq 0 ]; then actual=PASS; else actual=FAIL; fi
  if [ "$actual" = "$expected" ]; then
    PASS=$((PASS+1))
    printf '  \033[32mok\033[0m   %s\n' "$desc"
  else
    FAIL=$((FAIL+1))
    FAILURES+=("$desc — expected $expected, got $actual (rc=$rc, out: ${out:0:200})")
    printf '  \033[31mFAIL\033[0m %s (expected %s, got %s)\n' "$desc" "$expected" "$actual"
  fi
}

echo "=== Closes-syntax fixture set ==="
expect PASS "01: bare Closes #NN"                        'Closes #826'
expect PASS "02: Fixes with two issues comma-separated"  'Fixes #826, #827'
expect PASS "03: bulleted list item"                     '- Resolves #826'
expect PASS "04: cross-repo Resolves owner/repo#NN"      'Resolves prajoria/OpenBB#826'
expect FAIL "05: bd-id in backticks (historical drift)"  'Closes `OpenBBTechnical-qy83.1.4`'
expect FAIL "06: bare bd-id"                             'Closes bd-qy83.1.4'
expect FAIL "07: full URL (rejected for readability)"    'Closes https://github.com/prajoria/OpenBB/issues/826'
expect FAIL "08: missing # sigil"                        'Closes 826'
expect FAIL "09: no Closes clause, no noissue marker"    'Just a description of the PR.'
expect PASS "10: no Closes clause, noissue marker set"   $'Some description.\n\nnoissue: docs-only cleanup'
expect PASS "11: lowercase closes"                       'closes #826'
expect PASS "12: trailing period"                        'Closes #826.'
expect PASS "13: multiline body with prose + Closes"     $'## Summary\n\nAdds thing.\n\nCloses #826'
expect FAIL "14: prose 'this closes'"                    'This PR closes the drift bug from PR #467'
expect PASS "15: asterisk bulleted"                      '* Fixes #826'
expect PASS "16: leading spaces"                         '    Closes #826'
expect FAIL "17: mixed valid + invalid on same line"     'Closes #826, bd-qy83.1.4'
expect PASS "18: noissue prose containing verb-word"     $'Some description.\n\nFixes a typo in the roadmap doc.\n\nnoissue: docs-only cleanup'
expect PASS "19: prose 'Fixes a typo' without noissue but with valid Closes" $'## Summary\n\nFixes a typo in the doc.\n\nCloses #826'
# --- issue #851: tighten prose-vs-clause on backticked identifiers ---
expect PASS "20: prose 'Fixes `ClassName`' with valid Closes below" $'Fixes `ModuleNotFoundError` that broke import.\n\nCloses #826'
expect PASS "21: prose 'Resolves `some_func`' with valid Closes"    $'Resolves `some_func` edge case.\n\nCloses #826'
expect PASS "22: prose 'Fixes `kebab-case-thing`' with valid Closes" $'Fixes `some-typo-thing` in docs.\n\nCloses #826'
expect FAIL "23: bd-id in backticks (the historical drift target — must still catch)" 'Closes `bd-qy83.1.4`'
expect FAIL "24: OpenBBTechnical-id in backticks (also historical target)" 'Closes `OpenBBTechnical-qy83.1.4`'
expect FAIL "25: backticked #NN-ish but malformed (starts with #)"  'Closes `#not-a-number`'
expect PASS "26: prose 'Closes `SomeClass`' with noissue marker"    $'Closes `SomeClass` circular ref.\n\nnoissue: refactor-only'

echo
echo "=== Summary ==="
echo "PASS: $PASS  FAIL: $FAIL"
if [ $FAIL -gt 0 ]; then
  echo
  echo "Failures:"
  for f in "${FAILURES[@]}"; do echo "  - $f"; done
  exit 1
fi
exit 0
