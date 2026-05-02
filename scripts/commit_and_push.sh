#!/usr/bin/env bash
# Stage allowlisted files, commit, and push to main with a robust rebase loop.
#
# Behaviour:
#   - Existing files in MUST_STAGE are added; missing paths are skipped (logged).
#   - If nothing is staged, exits 0 (no-op).
#   - On rebase conflicts confined to KEEP_LOCAL_ON_CONFLICT files, takes ours and
#     continues. Conflicts touching anything else fail loudly.
#   - Up to MAX_ATTEMPTS pull/push cycles, with linear backoff between attempts.
#
# Required env:
#   COMMIT_MESSAGE        - commit message
#   MUST_STAGE            - newline-separated list of paths to git add
# Optional env:
#   KEEP_LOCAL_ON_CONFLICT     - newline-separated list of paths where rebase conflicts
#                           are auto-resolved with `--ours`
#   MAX_ATTEMPTS          - default 3
#   REMOTE                - default origin
#   BRANCH                - default main

set -uo pipefail

REMOTE="${REMOTE:-origin}"
BRANCH="${BRANCH:-main}"
MAX_ATTEMPTS="${MAX_ATTEMPTS:-3}"

if [[ -z "${COMMIT_MESSAGE:-}" ]]; then
  echo "commit_and_push: COMMIT_MESSAGE is required" >&2
  exit 2
fi
if [[ -z "${MUST_STAGE:-}" ]]; then
  echo "commit_and_push: MUST_STAGE is required" >&2
  exit 2
fi

mapfile -t stage_paths < <(printf '%s\n' "$MUST_STAGE" | sed '/^[[:space:]]*$/d')
mapfile -t keep_local < <(printf '%s\n' "${KEEP_LOCAL_ON_CONFLICT:-}" | sed '/^[[:space:]]*$/d')

# Stage existing files only; skip missing.
staged_any=0
for path in "${stage_paths[@]}"; do
  if [[ -e "$path" ]]; then
    git add -- "$path"
    staged_any=1
  else
    echo "commit_and_push: skipping missing path $path"
  fi
done

if [[ "$staged_any" -eq 0 ]]; then
  echo "commit_and_push: no listed paths exist; nothing to do."
  exit 0
fi

if git diff --cached --quiet; then
  echo "commit_and_push: no staged changes; nothing to commit."
  exit 0
fi

git commit -m "$COMMIT_MESSAGE"

is_keep_local() {
  local candidate="$1"
  local p
  for p in "${keep_local[@]}"; do
    if [[ "$candidate" == "$p" ]]; then
      return 0
    fi
  done
  return 1
}

resolve_rebase_conflicts() {
  # Returns 0 if rebase was completed (or already not in progress), 1 if a
  # conflict outside the keep-local allowlist remained.
  if [[ ! -d .git/rebase-merge && ! -d .git/rebase-apply ]]; then
    return 0
  fi
  while true; do
    mapfile -t conflicts < <(git diff --name-only --diff-filter=U)
    if [[ ${#conflicts[@]} -eq 0 ]]; then
      break
    fi
    for f in "${conflicts[@]}"; do
      if is_keep_local "$f"; then
        # During a rebase, --theirs is the branch being rebased (our local
        # commit, i.e. the workflow's freshly-generated content). --ours
        # would pick upstream, which is the opposite of what we want.
        echo "commit_and_push: auto-resolving rebase conflict for $f (keeping workflow output)"
        git checkout --theirs -- "$f"
        git add -- "$f"
      else
        echo "commit_and_push: unresolved conflict in $f; aborting rebase." >&2
        git rebase --abort || true
        return 1
      fi
    done
    if ! git -c core.editor=true rebase --continue; then
      # Another set of conflicts may have surfaced; loop again.
      continue
    fi
    break
  done
  return 0
}

attempt=1
while (( attempt <= MAX_ATTEMPTS )); do
  echo "commit_and_push: attempt ${attempt}/${MAX_ATTEMPTS}: pulling $REMOTE/$BRANCH"
  if ! git pull --rebase "$REMOTE" "$BRANCH"; then
    if ! resolve_rebase_conflicts; then
      exit 1
    fi
  fi

  if git push "$REMOTE" "HEAD:$BRANCH"; then
    echo "commit_and_push: push succeeded on attempt ${attempt}."
    exit 0
  fi

  echo "commit_and_push: push failed on attempt ${attempt}; retrying."
  sleep $(( attempt * 5 ))
  attempt=$(( attempt + 1 ))
done

echo "commit_and_push: exhausted ${MAX_ATTEMPTS} attempts." >&2
exit 1
