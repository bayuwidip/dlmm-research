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
DONE | project-housekeeping-helper | Add a repo-owner housekeeping helper for task_queue/checkpoint updates after merged PRs. Acceptance: script marks one REVIEW task as DONE, optionally appends one READY task, appends checkpoint entry, validates queue consistency, documentation included, tests pass, no runtime/trading/wallet behavior.
DONE | dev-loop-host-commit-wrapper | Add a host-side commit/PR wrapper for run_dev_loop outputs when Codex sandbox cannot write .git metadata. Acceptance: detects changed files after a successful agent run, creates a branch on the host, stages allowed files only, commits with a generated message, opens PR with validation summary, refuses generated runtime/report artifacts unless explicitly allowed, tests pass, no runtime/trading/wallet behavior.
DONE | scheduled-runner-cron-dry-run | Add a safe cron/systemd dry-run scheduling guide for the scheduled read-only diagnostics runner. Acceptance: documentation only, includes exact cron/systemd example commands, lock/log paths, disable/remove instructions, and safety checklist. Does not enable scheduling automatically, no wallet/live/paper-position capability.
DONE | add-rtk-agent-guidance | Add optional RTK guidance for Claude/Codex agents to reduce token usage on noisy outputs. Acceptance: update AGENTS.md or docs with RTK as optional only, use RTK for exploration/token saving, keep original commands for final validation evidence, no dependency on RTK, tests/checks pass, no runtime/trading/wallet behavior.
DONE | update-readme-project-status | Update README.md to reflect the current DLMM project status and safe workflow. Acceptance: README explains project purpose, current READ_ONLY/PAPER_ONLY phase, forbidden actions, current pipeline, runtime DB/reporting status, dev loop with Claude/Codex fallback, host-side PR wrapper, scheduled dry-run docs, RTK optional guidance, and next safe milestones. Documentation only, no runtime/trading/wallet behavior.
DONE | paper-simulation-design-v0-1 | Paper Simulation Design v0.1 for USDC-SOL, design + schema only. See spec pasted in session.
READY | calibrate-range-width-v0-1 | Lock the owner-calibrated range_width_pct=0.08 (8%) into docs/paper_simulation_design_v0_1.md section 5 and the matching comment in docs/paper_ledger_schema_v0_1.sql, replacing REQUIRES_MANUAL_CALIBRATION for that one parameter only. fee_decay_window and fee_decay_threshold remain REQUIRES_MANUAL_CALIBRATION (insufficient historical fee/TVL data; pools_watchlist.csv is a single-date snapshot, not a time series). Append one docs/decision_log.md entry recording: calibration date, USDC-SOL realized_volatility_pct=5.4184 (window 2026-06-28 to 2026-07-01, 73 hourly candles), multiplier used (1.5x), resulting range_width_pct=0.08, and explicit note that fee-decay params await accumulated scheduled-runner snapshots before calibration. Docs-only, no code/schema execution changes, no runtime DB writes.
