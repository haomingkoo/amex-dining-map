#!/usr/bin/env bash
set -euo pipefail

if [ -z "${REMINDERS_API_BASE:-}" ] || [ -z "${TELEGRAM_REMINDER_DISPATCH_TOKEN:-}" ]; then
  echo "::warning::Telegram reminder dispatch is not configured; skipping."
  echo "Telegram reminder dispatch: skipped because required secrets are missing." >> "$GITHUB_STEP_SUMMARY"
  if [ "${TELEGRAM_REMINDERS_EXPECTED_ENABLED:-}" = "true" ]; then
    exit 1
  fi
  exit 0
fi

for attempt in $(seq 1 25); do
  if response=$(python3 -c 'import json; print(json.dumps({"expected_generated_at": json.load(open("data/table-for-two-slots.json"))["generated_at"]}))' \
    | curl --fail-with-body --silent --show-error \
      --connect-timeout 5 --max-time 30 \
      -H "Content-Type: application/json" \
      -H "X-Telegram-Reminder-Dispatch-Token: $TELEGRAM_REMINDER_DISPATCH_TOKEN" \
      --data-binary @- \
      "$REMINDERS_API_BASE/api/internal/telegram/reminders/dispatch"); then
    curl_status=0
  else
    curl_status=$?
  fi

  bounded_response=$(python3 -c 'import sys; print(sys.stdin.read(4096), end="")' <<< "$response")
  {
    echo "Telegram reminder dispatch ${attempt}:"
    echo '```json'
    printf '%s\n' "$bounded_response"
    echo '```'
  } >> "$GITHUB_STEP_SUMMARY"

  if [ "$curl_status" -ne 0 ]; then
    echo "::error::Telegram reminder dispatch failed; see the workflow summary for its run receipt."
    exit "$curl_status"
  fi

  read -r more unknown dead < <(python3 -c 'import json,sys; body=json.load(sys.stdin); print(str(body.get("more", False)).lower(), int(body.get("unknown", 0)), int(body.get("dead", 0)))' <<< "$response")
  if [ "$unknown" -gt 0 ] || [ "$dead" -gt 0 ]; then
    echo "::warning::Telegram reminder dispatch ended with unknown=${unknown}, dead=${dead}; see run receipt in the workflow summary."
  fi
  if [ "$more" != "true" ]; then
    exit 0
  fi
done

echo "Telegram reminder dispatch still has matched work after 25 bounded calls." >&2
exit 1
