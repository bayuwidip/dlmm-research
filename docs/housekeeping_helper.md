# Housekeeping Helper

`scripts/housekeep_after_merge.py` is a repo-owner tool for updating
`docs/task_queue.md` and `docs/project_checkpoint.md` after a PR has been manually merged.

It is documentation/tooling only. It does not run the pipeline, touch runtime storage,
create positions, or perform market actions.

## What It Does

- Marks exactly one `REVIEW` task as `DONE`.
- Updates the checkpoint `NEXT TASK` line to the first existing `READY` task, or to `NONE`.
- Appends one checkpoint entry documenting the completed task and current next task.
- Validates queue consistency before writing.

This tool cannot add tasks or queue new work. New `docs/task_queue.md` lines are added
only by the repo owner, directly, outside this tool.

The helper refuses to proceed when:

- the requested completed task is not present;
- the requested completed task is not currently `REVIEW`;
- task ids are duplicated;
- more than one `REVIEW` task exists;
- any `BLOCKED` task is present;
- the checkpoint file does not start with a `NEXT TASK` line.

## Dry Run

```bash
python3 scripts/housekeep_after_merge.py \
  --done-task-id scheduled-runner-smoke-test \
  --checkpoint-title "Scheduled Runner Smoke Test Done; Housekeeping Helper Queued" \
  --checkpoint-body "Housekeeping update after the merged PR." \
  --dry-run
```

## Apply

Remove `--dry-run` after reviewing the diff:

```bash
python3 scripts/housekeep_after_merge.py \
  --done-task-id scheduled-runner-smoke-test \
  --checkpoint-title "Scheduled Runner Smoke Test Done; Housekeeping Helper Queued" \
  --checkpoint-body "Housekeeping update after the merged PR."
```

Only the repo owner should add or choose the next task by editing `docs/task_queue.md`
directly outside this helper. Do not use this helper to invent new queue items.
