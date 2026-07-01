#!/usr/bin/env python3
"""Tests for scripts/housekeep_after_merge.py."""

import io
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import housekeep_after_merge as hk  # noqa: E402


QUEUE = """# Task Queue (manually curated -- only the repo owner adds/reorders lines)
#
# Format:
# STATUS | task-id | one-line description + short acceptance criteria

DONE | old-task | Already merged.
REVIEW | merged-task | Merged task description unchanged.
"""


CHECKPOINT = """**NEXT TASK ->** merged-task — Merged task description unchanged.

# DLMM Project Checkpoint

Existing checkpoint body.
"""


class QueueUpdateTests(unittest.TestCase):
    def test_marks_one_review_task_done_and_preserves_description(self):
        updated, done_task, next_task = hk.update_queue(QUEUE, "merged-task")

        self.assertIn(
            "DONE | merged-task | Merged task description unchanged.",
            updated,
        )
        self.assertEqual(done_task.description, "Merged task description unchanged.")
        self.assertIsNone(next_task)

    def test_optionally_appends_one_ready_task(self):
        updated, _, next_task = hk.update_queue(
            QUEUE,
            "merged-task",
            next_task_id="next-task",
            next_task_description="Next owner-curated task.",
        )

        self.assertTrue(updated.endswith("READY | next-task | Next owner-curated task.\n"))
        self.assertEqual(next_task.task_id, "next-task")
        self.assertEqual(next_task.status, "READY")

    def test_refuses_to_mark_non_review_task_done(self):
        with self.assertRaisesRegex(hk.HousekeepingError, "must be REVIEW"):
            hk.update_queue(QUEUE, "old-task")

    def test_refuses_duplicate_task_ids(self):
        bad_queue = QUEUE + "READY | merged-task | Duplicate.\n"
        with self.assertRaisesRegex(hk.HousekeepingError, "Duplicate task id"):
            hk.update_queue(bad_queue, "merged-task")

    def test_refuses_more_than_one_review_task(self):
        bad_queue = QUEUE + "REVIEW | second-review | Another task.\n"
        with self.assertRaisesRegex(hk.HousekeepingError, "more than one REVIEW"):
            hk.update_queue(bad_queue, "merged-task")

    def test_refuses_blocked_queue(self):
        bad_queue = QUEUE + "BLOCKED | blocked-task | Needs owner decision.\n"
        with self.assertRaisesRegex(hk.HousekeepingError, "contains BLOCKED"):
            hk.update_queue(bad_queue, "merged-task")

    def test_next_task_args_must_be_paired(self):
        with self.assertRaisesRegex(hk.HousekeepingError, "provided together"):
            hk.update_queue(QUEUE, "merged-task", next_task_id="next-task")


class CheckpointUpdateTests(unittest.TestCase):
    def test_updates_next_task_line_and_appends_checkpoint_entry(self):
        queue_after, done_task, next_task = hk.update_queue(
            QUEUE,
            "merged-task",
            next_task_id="next-task",
            next_task_description="Next owner-curated task.",
        )
        self.assertIn("READY | next-task", queue_after)

        updated = hk.update_checkpoint(
            CHECKPOINT,
            done_task=done_task,
            next_task=next_task,
            entry_title="Merged Task Completed",
            entry_body="No runtime behavior changed.",
            entry_date="2026-07-01",
        )

        self.assertTrue(
            updated.startswith(
                "**NEXT TASK ->** next-task — Next owner-curated task.\n"
            )
        )
        self.assertIn("## Checkpoint: Merged Task Completed", updated)
        self.assertIn("- merged-task", updated)
        self.assertIn("- next-task", updated)
        self.assertIn("No runtime behavior changed.", updated)

    def test_sets_next_task_to_none_when_no_ready_task_exists(self):
        _, done_task, next_task = hk.update_queue(QUEUE, "merged-task")
        updated = hk.update_checkpoint(
            CHECKPOINT,
            done_task=done_task,
            next_task=next_task,
            entry_title="Merged Task Completed",
            entry_body="",
            entry_date="2026-07-01",
        )

        self.assertTrue(updated.startswith(hk.NO_NEXT_TASK_LINE))
        self.assertIn("Current next task:\n- NONE", updated)

    def test_refuses_checkpoint_without_next_task_line(self):
        _, done_task, next_task = hk.update_queue(QUEUE, "merged-task")
        with self.assertRaisesRegex(hk.HousekeepingError, "NEXT TASK"):
            hk.update_checkpoint(
                "# DLMM Project Checkpoint\n",
                done_task=done_task,
                next_task=next_task,
                entry_title="Title",
                entry_body="",
                entry_date="2026-07-01",
            )


class CliTests(unittest.TestCase):
    def test_dry_run_prints_diffs_and_writes_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            queue_path = Path(tmp) / "task_queue.md"
            checkpoint_path = Path(tmp) / "project_checkpoint.md"
            queue_path.write_text(QUEUE, encoding="utf-8")
            checkpoint_path.write_text(CHECKPOINT, encoding="utf-8")

            out = io.StringIO()
            with redirect_stdout(out):
                rc = hk.main(
                    [
                        "--done-task-id",
                        "merged-task",
                        "--next-task-id",
                        "next-task",
                        "--next-task-description",
                        "Next owner-curated task.",
                        "--checkpoint-title",
                        "Merged Task Completed",
                        "--checkpoint-body",
                        "Docs only.",
                        "--date",
                        "2026-07-01",
                        "--task-queue",
                        str(queue_path),
                        "--checkpoint",
                        str(checkpoint_path),
                        "--dry-run",
                    ]
                )

            self.assertEqual(rc, 0)
            self.assertIn("---", out.getvalue())
            self.assertIn("+READY | next-task | Next owner-curated task.", out.getvalue())
            self.assertEqual(queue_path.read_text(encoding="utf-8"), QUEUE)
            self.assertEqual(checkpoint_path.read_text(encoding="utf-8"), CHECKPOINT)

    def test_cli_writes_both_docs(self):
        with tempfile.TemporaryDirectory() as tmp:
            queue_path = Path(tmp) / "task_queue.md"
            checkpoint_path = Path(tmp) / "project_checkpoint.md"
            queue_path.write_text(QUEUE, encoding="utf-8")
            checkpoint_path.write_text(CHECKPOINT, encoding="utf-8")

            out = io.StringIO()
            with redirect_stdout(out):
                rc = hk.main(
                    [
                        "--done-task-id",
                        "merged-task",
                        "--checkpoint-title",
                        "Merged Task Completed",
                        "--date",
                        "2026-07-01",
                        "--task-queue",
                        str(queue_path),
                        "--checkpoint",
                        str(checkpoint_path),
                    ]
                )

            self.assertEqual(rc, 0)
            self.assertIn("Marked DONE: merged-task", out.getvalue())
            self.assertIn("DONE | merged-task", queue_path.read_text(encoding="utf-8"))
            self.assertIn(
                "## Checkpoint: Merged Task Completed",
                checkpoint_path.read_text(encoding="utf-8"),
            )

    def test_cli_reports_validation_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            queue_path = Path(tmp) / "task_queue.md"
            checkpoint_path = Path(tmp) / "project_checkpoint.md"
            queue_path.write_text(QUEUE, encoding="utf-8")
            checkpoint_path.write_text(CHECKPOINT, encoding="utf-8")

            err = io.StringIO()
            with redirect_stderr(err):
                rc = hk.main(
                    [
                        "--done-task-id",
                        "missing-task",
                        "--checkpoint-title",
                        "Title",
                        "--task-queue",
                        str(queue_path),
                        "--checkpoint",
                        str(checkpoint_path),
                    ]
                )

            self.assertEqual(rc, 1)
            self.assertIn("Task not found", err.getvalue())


if __name__ == "__main__":
    unittest.main()
