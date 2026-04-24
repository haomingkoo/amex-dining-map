#!/usr/bin/env bash
set -euo pipefail

title="$1"
body_file="$2"
program_label="$3"

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
  gh issue comment "$existing_issue" --body-file "$body_file"
else
  gh issue create \
    --title "$title" \
    --label data-alert \
    --label "$program_label" \
    --body-file "$body_file"
fi
