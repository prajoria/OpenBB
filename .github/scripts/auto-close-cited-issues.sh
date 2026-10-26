#!/usr/bin/env bash
# Cited-issue extraction for
# .github/workflows/portfolio-intel-auto-close-on-merge.yml (#847, #1975).
#
# A push to portfolio closes every issue cited with Closes|Fixes|Resolves in
# the pushed commit messages AND in the body of each merged PR that produced
# those commits. The PR body matters for squash merges: the squash commit keeps
# the branch commits' "Refs #NN" trailers but not the PR body's "Closes #NN".
#
# Source this file; it defines functions only.
# Tests: .github/scripts/test-auto-close-cited-issues.sh

# Read text on stdin; print each cited same-repo issue number once, sorted.
# Grammar mirrors .github/scripts/closes-syntax-check.sh:
#   Closes|Fixes|Resolves #NN            (single)
#   Closes|Fixes|Resolves #NN, #MM, #PP  (comma-separated)
# Cross-repo owner/repo#NN citations are not auto-closed here.
extract_cited_issues() {
  { grep -oiE '(Closes|Fixes|Resolves)[[:space:]]+#[0-9]+([[:space:]]*,[[:space:]]*#[0-9]+)*' || true; } \
    | { grep -oE '#[0-9]+' || true; } \
    | tr -d '#' \
    | sort -un
}

# Print the commit SHAs in a git range (or a single SHA).
range_commits() {
  git rev-list "$1"
}

# Print the first-parent SHAs in a range: the commits that landed on the
# branch itself (squash or merge commits), i.e. the ones a merged PR made.
first_parent_commits() {
  git rev-list --first-parent "$1"
}

# Print one commit's full message.
commit_message() {
  git log -1 --format=%B "$1"
}

# Print the bodies of merged PRs into AUTO_CLOSE_BASE (default portfolio)
# associated with a commit. Non-zero exit when the lookup itself fails.
lookup_merged_pr_bodies() {
  gh api "repos/${GITHUB_REPOSITORY}/commits/$1/pulls" \
    --jq ".[] | select(.merged_at != null and .base.ref == \"${AUTO_CLOSE_BASE:-portfolio}\") | (.body // \"\")"
}

# Print every commit message in the range, then the merged PR bodies of its
# first-parent commits. A failed PR lookup is reported on stderr and never
# hides the commits' own citations.
collect_closing_text() {
  local sha bodies
  for sha in $(range_commits "$1"); do
    commit_message "$sha"
    printf '\n---\n'
  done
  for sha in $(first_parent_commits "$1"); do
    if bodies=$(lookup_merged_pr_bodies "$sha"); then
      printf '%s\n---\n' "$bodies"
    else
      echo "warning: could not look up the merged PR for ${sha}; using its commit message only" >&2
    fi
  done
}
