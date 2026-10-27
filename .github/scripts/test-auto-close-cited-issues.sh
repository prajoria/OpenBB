#!/usr/bin/env bash
# Tests for the cited-issue extraction used by
# .github/workflows/portfolio-intel-auto-close-on-merge.yml
#
# Issue: #1975 (auto-close-on-merge workflow doesn't parse Closes clauses
# from PR body). A squash merge keeps the branch commits' "Refs #NN"
# trailers but drops the PR body's "Closes #NN", so the merged PR body
# must be read too.
#
# Usage: bash .github/scripts/test-auto-close-cited-issues.sh

set -u  # NOT set -e: we deliberately let cases fail and count outcomes.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=./auto-close-cited-issues.sh
source "$SCRIPT_DIR/auto-close-cited-issues.sh"

PASS=0
FAIL=0
FAILURES=()

check() {
  local desc=$1 expected=$2 actual=$3
  if [ "$actual" = "$expected" ]; then
    PASS=$((PASS+1))
    printf '  \033[32mok\033[0m   %s\n' "$desc"
  else
    FAIL=$((FAIL+1))
    FAILURES+=("$desc — expected [$expected], got [$actual]")
    printf '  \033[31mFAIL\033[0m %s\n' "$desc"
  fi
}

# Joins extractor output onto one line for easy comparison.
extract() { printf '%s' "$1" | extract_cited_issues | tr '\n' ' ' | sed 's/ $//'; }

echo "=== extract_cited_issues ==="
check "01: Closes #NN"                 "12"       "$(extract 'Closes #12')"
check "02: Refs only cites nothing"    ""         "$(extract 'Refs #12 (parent)')"
check "03: comma-separated list"       "3 4 5"    "$(extract 'Fixes #3, #4, #5')"
check "04: lowercase verb, trailing ." "7"        "$(extract 'resolves #7.')"
check "05: dedupe and numeric sort"    "9 10"     "$(extract $'Closes #10\nCloses #9\nFixes #10')"

# Fake PR lookup: the merged PR for SHA "squash1" has a body citing #2245.
lookup_merged_pr_bodies() {
  case "$1" in
    squash1) printf 'Summary\n\nCloses #2245.\nRefs #2282 (follow-up)\n' ;;
    broken) return 1 ;;
    *) ;;
  esac
}
# Fake commit list/messages so the tests need no git history.
range_commits() { printf '%s\n' $FAKE_SHAS; }
first_parent_commits() { printf '%s\n' $FAKE_SHAS; }
commit_message() { printf '%s' "${FAKE_MSG:-}"; }

echo "=== collect_closing_text (squash merge) ==="
FAKE_SHAS="squash1" FAKE_MSG='build(mcp): lock (#2283)

Refs #2245 (lock graphs)'
out=$(collect_closing_text "a..b" 2>/dev/null | extract_cited_issues | tr '\n' ' ' | sed 's/ $//')
check "06: PR body Closes is found when the commit only says Refs" "2245" "$out"

FAKE_SHAS="squash1" FAKE_MSG='Closes #2245'
out=$(collect_closing_text "a..b" 2>/dev/null | extract_cited_issues | tr '\n' ' ' | sed 's/ $//')
check "07: commit and PR body citing the same issue dedupe" "2245" "$out"

FAKE_SHAS="plain" FAKE_MSG='chore: direct push

Closes #77'
out=$(collect_closing_text "a..b" 2>/dev/null | extract_cited_issues | tr '\n' ' ' | sed 's/ $//')
check "08: direct push without a PR still closes from the message" "77" "$out"

FAKE_SHAS="broken" FAKE_MSG='Closes #88'
err=$(collect_closing_text "a..b" 2>&1 >/dev/null)
out=$(collect_closing_text "a..b" 2>/dev/null | extract_cited_issues | tr '\n' ' ' | sed 's/ $//')
check "09: failed PR lookup keeps commit citations"  "88" "$out"
case "$err" in
  *"could not look up"*) check "10: failed PR lookup warns loudly" "warned" "warned" ;;
  *) check "10: failed PR lookup warns loudly" "warned" "silent: $err" ;;
esac

# GitHub keeps one pending run per concurrency group and cancels older
# pending runs, so a ref-only group drops back-to-back merges (#2292).
group=$(grep -E '^[[:space:]]+group:' "$SCRIPT_DIR/../workflows/portfolio-intel-auto-close-on-merge.yml")
case "$group" in
  *github.sha*) check "11: each push gets its own concurrency group" "per-sha" "per-sha" ;;
  *) check "11: each push gets its own concurrency group" "per-sha" "$group" ;;
esac

echo
echo "Results: $PASS passed, $FAIL failed"
if [ "$FAIL" -gt 0 ]; then
  printf '  - %s\n' "${FAILURES[@]}"
  exit 1
fi
