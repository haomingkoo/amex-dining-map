#!/usr/bin/env bash
set -euo pipefail

title="$1"
body_file="$2"
program_label="$3"

marker_prefix="<!-- source-alert-fingerprint:"
# Timestamp lines change every run; every other line is a review signal.
fingerprint="$(grep -v -e '^- Checked at:' -e '^- Source cache time:' "$body_file" | sha256sum | cut -d ' ' -f 1)"
marker="${marker_prefix} ${fingerprint} -->"
posted_body="$(mktemp)"
{ cat "$body_file"; printf '\n%s\n' "$marker"; } > "$posted_body"

gh label create data-alert \
  --color C2410C \
  --description "Official source data changed and needs review" >/dev/null 2>&1 || true
gh label create "$program_label" \
  --color 1D76DB \
  --description "Source alert for ${program_label}" >/dev/null 2>&1 || true

existing_issue="$(
  gh issue list \
    --state open \
    --label data-alert \
    --search "${title} in:title" \
    --json number \
    --jq '.[0].number // empty'
)"

if [[ -n "$existing_issue" ]]; then
  bodies="$(gh issue view "$existing_issue" --json body,comments --jq '.body, .comments[].body')"
  last_marker="$(grep -F "$marker_prefix" <<<"$bodies" | tail -n 1 || true)"
  if [[ "$last_marker" == "$marker" ]]; then
    echo "Issue #${existing_issue} already carries these signals; not commenting."
    exit 0
  fi
  gh issue comment "$existing_issue" --body-file "$posted_body"
else
  gh issue create \
    --title "$title" \
    --label data-alert \
    --label "$program_label" \
    --body-file "$posted_body"
fi
