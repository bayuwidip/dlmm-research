# Task Queue (manually curated -- only the repo owner adds/reorders lines)
#
# Format:
# STATUS | task-id | one-line description + short acceptance criteria
#
# Valid STATUS values:
#   READY    -> ready to be dispatched by run_dev_loop.sh, no branch/PR yet
#   REVIEW   -> already dispatched, PR is open, awaiting manual review
#   BLOCKED  -> loop stops here, needs a decision from the repo owner
#   DONE     -> PR has been manually merged
#
# RULES:
# - Only the repo owner may add new lines or reorder them.
# - Claude Code must NOT add new tasks to this file.
# - Claude Code may ONLY change the STATUS of the line it is working on,
#   from READY -> REVIEW (after opening a PR) or READY -> BLOCKED (if
#   STEP 0 in the task prompt finds an ambiguity). This status change is
#   part of the same PR as the task itself.
# - run_dev_loop.sh stops completely if it finds a new BLOCKED line.

DONE | manual-council-review-matrix | Build a read-only Manual Council Review Matrix for the 6 stable review candidates, per project_checkpoint.md section 3h/3i. Acceptance: report per candidate + manual review questions, does not change candidate status, does not touch future_position_events.
DONE | wire-matrix-into-pipeline | Wire scripts/build_manual_council_review_matrix.py into scripts/run_readonly_pipeline.py as an optional post-pipeline step (same pattern as the other optional builders already wired in). Must be additive only -- do not modify pipeline behavior when the new flag is not passed. Acceptance: new optional CLI flag on the runner, existing default runner behavior and tests unchanged, new test coverage for the flag.
DONE | scheduled-readonly-runner | Build a safe scheduled read-only diagnostics runner for VPS automation. Acceptance: lock file prevents overlapping runs, logs are written locally, pipeline/report commands are orchestrated safely, dry-run writes no reports, future_position_events count is checked, no wallet/live/paper-position capability, tests pass.
DONE | scheduled-runner-smoke-test | Run the scheduled read-only diagnostics runner in dry-run and controlled non-dry-run mode against the existing VPS runtime DB. Acceptance: produce a local smoke-test report documenting command used, log path, DB path, future_position_events count, generated reports, and safety result. No cron/systemd yet, no wallet/live/paper-position capability.
READY | project-housekeeping-helper | Add a repo-owner housekeeping helper for task_queue/checkpoint updates after merged PRs. Acceptance: script marks one REVIEW task as DONE, optionally appends one READY task, appends checkpoint entry, validates queue consistency, documentation included, tests pass, no runtime/trading/wallet behavior.
