# Housekeeping Helper

`scripts/housekeep_after_merge.py` is a repo-owner tool for updating
`docs/task_queue.md` and `docs/project_checkpoint.md` after a PR has been manually merged.

It is documentation/tooling only. It does not run the pipeline, touch runtime storage,
create positions, or perform market actions.

## What It Does

- Marks exactly one `REVIEW` task as `DONE`.
- Optionally appends exactly one owner-curated `READY` task.
- Updates the checkpoint `NEXT TASK` line to the first `READY` task, or to `NONE`.
- Appends one checkpoint entry documenting the completed task and current next task.
- Validates queue consistency before writing.

The helper refuses to proceed when:

- the requested completed task is not present;
- the requested completed task is not currently `REVIEW`;
- task ids are duplicated;
- more than one `REVIEW` task exists;
- any `BLOCKED` task is present;
- an optional next task id is already present;
- the checkpoint file does not start with a `NEXT TASK` line.

## Dry Run

```bash
python3 scripts/housekeep_after_merge.py \
  --done-task-id scheduled-runner-smoke-test \
  --next-task-id project-housekeeping-helper \
  --next-task-description "Add a repo-owner housekeeping helper for task_queue/checkpoint updates after merged PRs. Acceptance: script marks one REVIEW task as DONE, optionally appends one READY task, appends checkpoint entry, validates queue consistency, documentation included, tests pass, no runtime/trading behavior." \
  --checkpoint-title "Scheduled Runner Smoke Test Done; Housekeeping Helper Queued" \
  --checkpoint-body "Housekeeping update after the merged PR." \
  --dry-run
```

## Apply

Remove `--dry-run` after reviewing the diff:

```bash
python3 scripts/housekeep_after_merge.py \
  --done-task-id scheduled-runner-smoke-test \
  --next-task-id project-housekeeping-helper \
  --next-task-description "Add a repo-owner housekeeping helper for task_queue/checkpoint updates after merged PRs. Acceptance: script marks one REVIEW task as DONE, optionally appends one READY task, appends checkpoint entry, validates queue consistency, documentation included, tests pass, no runtime/trading behavior." \
  --checkpoint-title "Scheduled Runner Smoke Test Done; Housekeeping Helper Queued" \
  --checkpoint-body "Housekeeping update after the merged PR."
```

Only the repo owner should add or choose the next task. Do not use this helper to invent
new queue items.
