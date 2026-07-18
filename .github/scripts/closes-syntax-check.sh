#!/usr/bin/env bash
# check_closes_syntax — validate the "Closes/Fixes/Resolves" grammar in a PR body.
#
# Reads the PR body from stdin, emits diagnostics on stderr, exits:
#   0 = PASS  (body contains at least one well-formed Closes clause, OR contains a noissue marker)
#   1 = FAIL  (missing or malformed)
#
# Design: docs/superpowers/specs/2026-07-16-gh-826-closes-syntax-design.md
# Issue:  #826
# Tests:  .github/scripts/test-closes-syntax.sh
#
# Sourced by:
#   - test-closes-syntax.sh (local TDD)
#   - .github/workflows/portfolio-intel-closes-syntax.yml (CI)

# Grammar rule (from design spec):
#   ^\s*[-*]?\s*(Closes|Fixes|Resolves)\s+ITEM(\s*,\s*ITEM)*\s*\.?\s*$
# where ITEM matches:
#   #<digits>                             (same-repo)
#   [a-zA-Z][\w.-]*\/[\w.-]+#<digits>     (cross-repo)
#
# Case-insensitive match on the verb; anchor to start-of-line to reject
# prose like "This PR closes ...".

check_closes_syntax() {
  local body
  body=$(cat)   # read stdin

  # Item pattern (Bash ERE, no backslash-w — use POSIX classes)
  local ITEM='(#[0-9]+|[[:alpha:]][[:alnum:]._-]*/[[:alnum:]._-]+#[0-9]+)'
  local VERB='(closes|fixes|resolves)'
  # Full line grammar: optional bullet, optional leading whitespace,
  # verb, at least one item, optional additional items, optional trailing period.
  local LINE_RE="^[[:space:]]*[-*]?[[:space:]]*${VERB}[[:space:]]+${ITEM}([[:space:]]*,[[:space:]]*${ITEM})*[[:space:]]*\\.?[[:space:]]*$"

  # Collect verb-bearing lines (case-insensitive), then classify each as
  # valid-line vs invalid-line. A single invalid line is a hard fail.
  local -a valid_lines=()
  local -a invalid_lines=()
  local line lower_line
  # IFS reset + read -r to preserve leading whitespace; process substitution
  # avoids the subshell-scope trap that a plain pipe would create.
  while IFS= read -r line; do
    # Normalize case ONCE per line for the grammar test; we still show the
    # original line in error messages.
    lower_line=$(printf '%s' "$line" | tr '[:upper:]' '[:lower:]')
    # Skip lines that don't contain any of the three verbs at all.
    if ! [[ "$lower_line" =~ (closes|fixes|resolves) ]]; then
      continue
    fi
    # A line that has a verb but is not a well-formed Closes clause is
    # either prose ("this PR closes ...") or a malformed clause
    # ("Closes bd-xxx"). Distinguish by whether the verb appears at
    # start-of-line AND is followed by a token that itself looks
    # issue-referencing:
    #   - starts with `#`  (issue reference candidate)
    #   - starts with a digit (bare number typo — catches `Closes 826`)
    #   - starts with owner/repo shape (cross-repo ref candidate)
    #   - is a bd-id or OpenBBTechnical-id (backticked OR bare — historical
    #     drift target)
    #
    # Issue #851: prose like "Fixes `SomeError`" or "Fixes `some-func`" must
    # NOT classify as intent-to-close. The previous heuristic tripped on
    # backticks unconditionally, misclassifying description prose. We now
    # require the backticked CONTENT (via a second regex on
    # `\`(bd-|openbbtechnical-|#)`) to be issue-shaped before triggering.
    if [[ "$lower_line" =~ ^[[:space:]]*[-*]?[[:space:]]*(closes|fixes|resolves)[[:space:]]+(#|[0-9]|[a-z][[:alnum:]._-]*/|openbbtechnical-|bd-|\`(bd-|openbbtechnical-|#)) ]]; then
      # Line INTENDS to be a Closes clause. Grammar-check strictly.
      if [[ "$lower_line" =~ $LINE_RE ]]; then
        valid_lines+=("$line")
      else
        invalid_lines+=("$line")
      fi
    fi
    # else: prose mention — ignore (fixture 14 case)
  done < <(printf '%s\n' "$body")

  # Rule 1: any invalid line is a hard fail (grammar always enforced).
  if [ ${#invalid_lines[@]} -gt 0 ]; then
    {
      echo "::error title=Malformed Closes clause::"
      echo "The PR body contains ${#invalid_lines[@]} line(s) that look like Closes clauses but"
      echo "do not match the required grammar."
      echo
      echo "Offending line(s):"
      for l in "${invalid_lines[@]}"; do echo "  > $l"; done
      echo
      echo "Required grammar (case-insensitive verb):"
      echo "  Closes|Fixes|Resolves #<digits>"
      echo "  Closes|Fixes|Resolves owner/repo#<digits>"
      echo "  Closes #123, #456        (comma-separated multi)"
      echo "  - Closes #123            (bulleted list item)"
      echo
      echo "Rejected: bd-ids (\`OpenBBTechnical-*\`), backtick-quoted refs, URLs, bare numbers."
      echo "See CLAUDE.md \"Coordination — GitHub Issues only\"."
    } >&2
    return 1
  fi

  # Rule 2: if no valid clauses, allow escape via `noissue:` marker.
  if [ ${#valid_lines[@]} -eq 0 ]; then
    # Case-insensitive scan for a "noissue:" marker anywhere in the body
    # (with a reason after the colon — enforced by trailing pattern).
    if printf '%s' "$body" | grep -qiE '^[[:space:]]*noissue:[[:space:]]*[^[:space:]]'; then
      return 0
    fi
    {
      echo "::error title=Missing Closes clause::"
      echo "portfolio-intel PRs (feat/pi-*, feature/pi-*, pi/*) must either:"
      echo "  (a) contain at least one well-formed \"Closes #NN\" clause in the body, OR"
      echo "  (b) include a \"noissue: <one-line reason>\" marker for docs/chore/dep-bump PRs."
      echo
      echo "Required grammar:  Closes|Fixes|Resolves #<digits>"
      echo "Escape hatch:      noissue: <one-line reason>"
      echo
      echo "See CLAUDE.md \"Coordination — GitHub Issues only\" for the full protocol."
      echo "See #826 for background on why this check exists."
    } >&2
    return 1
  fi

  # All clauses well-formed + at least one present.
  return 0
}
