#!/usr/bin/env bash
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
QUEUE_FILE="$REPO_DIR/docs/task_queue.md"
LOG_DIR="$REPO_DIR/logs/dev_loop"
MAX_TASKS="${MAX_TASKS:-1}"

mkdir -p "$LOG_DIR"
cd "$REPO_DIR"

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*"; }

processed=0

while [ "$processed" -lt "$MAX_TASKS" ]; do
  task_line=""
  while IFS= read -r line; do
    [[ "$line" =~ ^READY\ \|\ ([a-zA-Z0-9._-]+)\ \|\ (.*)$ ]] || continue
    task_id="${BASH_REMATCH[1]}"
    if git ls-remote --exit-code --heads origin "feature/${task_id}" >/dev/null 2>&1; then
      continue
    fi
    task_line="$line"
    break
  done < "$QUEUE_FILE"

  if [ -z "$task_line" ]; then
    log "No unread dispatched READY task found. Loop stopping."
    break
  fi

  [[ "$task_line" =~ ^READY\ \|\ ([a-zA-Z0-9._-]+)\ \|\ (.*)$ ]]
  task_id="${BASH_REMATCH[1]}"
  task_desc="${BASH_REMATCH[2]}"

  log "=== Processing task: $task_id ==="
  log "Description: $task_desc"

  git checkout main
  git pull

  prompt=$(cat <<EOF
You are Claude Code, working in the dlmm-research repo.

TASK ID: ${task_id}
DESCRIPTION: ${task_desc}
(Task source: docs/task_queue.md -- this line was manually curated by the
repo owner. Do not pick a different task, do not add new tasks to that
file.)

STEP 0 -- CONSISTENCY CHECK (mandatory):
Read CLAUDE.md and docs/project_checkpoint.md. If this task turns out to
already be done/CI-confirmed (check docs/decision_log.md), or the
instructions are ambiguous/contradictory with those documents: DO NOT code.
Change this task's line in docs/task_queue.md from READY to:
BLOCKED | ${task_id} | <short reason for stopping>
then commit only that change to branch feature/${task_id}, push, and STOP.

STEP 1 -- SCOPE LOCK
Work ONLY on this task. Follow CLAUDE.md's Forbidden Actions, File
Modification Policy, and Validator Guardrails sections without exception.
Do not modify existing scripts/*.py unless this task explicitly requires
it. Other ideas found along the way: note them in the final PR report,
do not implement them.

STEP 2 -- BRANCH
git checkout -b feature/${task_id}

STEP 3 -- IMPLEMENT
Write code + tests. Do not commit generated output files (data/*.csv,
reports/*.md, runtime/*) unless this task is specifically about those
files.

STEP 4 -- VALIDATE (must pass before continuing)
python3 -m unittest discover tests
python3 scripts/validate_watchlist.py
Check that no wallet/private_key/sign(/swap(/execute_trade patterns exist
in new files outside of explicit-prohibition context. If anything fails,
fix it and retry.

STEP 5 -- UPDATE QUEUE + PUSH + PR (DO NOT MERGE, DO NOT PUSH TO MAIN)
In docs/task_queue.md, change this task's line from READY to:
REVIEW | ${task_id} | <original description, unchanged>
Commit this together with the code changes in the same PR.
git add <relevant files>
git commit -m "feat: ${task_id}"
git push origin feature/${task_id}
gh pr create --title "${task_id}" --body "<summary, test results, acceptance criteria>"

STEP 6 -- STOP
Do not merge. Do not start another task. Done.
EOF
)

  log_file="$LOG_DIR/$(date +%Y%m%d-%H%M%S)-${task_id}.log"
  log "Running Claude Code headless, log: $log_file"

  if claude -p "$prompt" \
      --allowedTools "Read,Edit,Write,Bash(git:*),Bash(python3:*),Bash(gh:*),Bash(grep:*)" \
      --max-turns 40 \
      --output-format json \
      > "$log_file" 2>&1; then
    log "Task $task_id finished executing (check $log_file for the PR result)."
  else
    log "Task $task_id FAILED (non-zero exit code). Loop stopping. Check $log_file."
    exit 1
  fi

  if grep -q "BLOCKED | ${task_id}" "$log_file" 2>/dev/null; then
    log "Task $task_id was marked BLOCKED. Loop stopping, awaiting your decision."
    exit 1
  fi

  processed=$((processed + 1))
  git checkout main
done

log "Done. $processed task(s) processed in this run."
log "Check open PRs with: gh pr list"
