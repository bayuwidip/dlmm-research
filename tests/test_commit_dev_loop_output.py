#!/usr/bin/env python3
"""Tests for scripts/commit_dev_loop_output.py."""

import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import commit_dev_loop_output as wrapper  # noqa: E402


class FakeRunner:
    def __init__(self, status_output, failures=None):
        self.status_output = status_output
        self.failures = failures or {}
        self.calls = []

    def __call__(self, argv):
        argv = tuple(argv)
        self.calls.append(argv)
        label = " ".join(argv)
        if argv == ("git", "status", "--porcelain=v1", "-z"):
            return wrapper.CommandResult(argv, 0, self.status_output, "")
        if label in self.failures:
            return wrapper.CommandResult(argv, self.failures[label], "", "failed")
        return wrapper.CommandResult(argv, 0, f"ok {label}\n", "")


class StatusParsingTests(unittest.TestCase):
    def test_parses_modified_added_deleted_and_renamed_paths(self):
        output = " M docs/a.md\0?? scripts/new.py\0D  old.txt\0R  before.py\0after.py\0"
        changes = wrapper.parse_porcelain_z(output)

        self.assertEqual(
            [(change.status, change.path) for change in changes],
            [
                (" M", "docs/a.md"),
                ("??", "scripts/new.py"),
                ("D ", "old.txt"),
                ("R ", "after.py"),
            ],
        )

    def test_refuses_unmerged_status(self):
        with self.assertRaisesRegex(wrapper.CommitWrapperError, "unresolved merge"):
            wrapper.parse_porcelain_z("UU docs/a.md\0")

    def test_refuses_unsafe_paths(self):
        with self.assertRaisesRegex(wrapper.CommitWrapperError, "unsafe path"):
            wrapper.parse_porcelain_z(" M ../outside.txt\0")


class GeneratedArtifactTests(unittest.TestCase):
    def test_identifies_generated_artifacts(self):
        self.assertEqual(wrapper.generated_artifact_reason("runtime/log.txt"), "runtime artifact")
        self.assertEqual(wrapper.generated_artifact_reason("reports/x.md"), "report artifact")
        self.assertEqual(wrapper.generated_artifact_reason("reports/runtime/x.csv"), "report artifact")
        self.assertEqual(wrapper.generated_artifact_reason("data/pair_watchlist.csv"), "generated data CSV")
        self.assertEqual(
            wrapper.generated_artifact_reason("data/observations/strategy_observations.jsonl"),
            "generated observation artifact",
        )
        self.assertIsNone(wrapper.generated_artifact_reason("docs/task_queue.md"))

    def test_refuses_generated_artifacts_by_default(self):
        runner = FakeRunner(" M docs/task_queue.md\0?? reports/new_report.md\0")
        with self.assertRaisesRegex(wrapper.CommitWrapperError, "Generated artifacts"):
            wrapper.commit_and_open_pr(
                task_id="task",
                runner=runner,
                validation_commands=(("python3", "-m", "unittest"),),
            )

    def test_allows_generated_artifacts_when_explicitly_requested(self):
        runner = FakeRunner(" M reports/new_report.md\0")
        message = wrapper.commit_and_open_pr(
            task_id="task",
            runner=runner,
            allow_generated_artifacts=True,
            validation_commands=(("python3", "-m", "unittest"),),
        )

        self.assertIn("Opened PR", message)
        self.assertIn(("git", "add", "--", "reports/new_report.md"), runner.calls)


class CommitFlowTests(unittest.TestCase):
    def test_runs_validation_then_branch_commit_push_and_pr(self):
        runner = FakeRunner(" M docs/task_queue.md\0?? scripts/commit_dev_loop_output.py\0")
        message = wrapper.commit_and_open_pr(
            task_id="dev-loop-host-commit-wrapper",
            runner=runner,
            validation_commands=(("python3", "-m", "unittest"),),
        )

        self.assertEqual(message, "Opened PR for dev-loop-host-commit-wrapper on feature/dev-loop-host-commit-wrapper")
        self.assertEqual(runner.calls[0], ("git", "status", "--porcelain=v1", "-z"))
        self.assertLess(
            runner.calls.index(("python3", "-m", "unittest")),
            runner.calls.index(("git", "checkout", "-B", "feature/dev-loop-host-commit-wrapper")),
        )
        self.assertIn(
            ("git", "commit", "-m", "feat: dev-loop-host-commit-wrapper"),
            runner.calls,
        )
        pr_calls = [call for call in runner.calls if call[:3] == ("gh", "pr", "create")]
        self.assertEqual(len(pr_calls), 1)
        body = pr_calls[0][pr_calls[0].index("--body") + 1]
        self.assertIn("Validation", body)
        self.assertIn("`python3 -m unittest`: PASS", body)
        self.assertIn("Refuses generated runtime/report/data artifacts", body)

    def test_refuses_empty_commit(self):
        runner = FakeRunner("")
        with self.assertRaisesRegex(wrapper.CommitWrapperError, "No changed files"):
            wrapper.commit_and_open_pr(task_id="task", runner=runner)

    def test_stops_when_validation_fails(self):
        runner = FakeRunner(
            " M docs/task_queue.md\0",
            failures={"python3 -m unittest": 1},
        )
        with self.assertRaisesRegex(wrapper.CommitWrapperError, "python3 -m unittest failed"):
            wrapper.commit_and_open_pr(
                task_id="task",
                runner=runner,
                validation_commands=(("python3", "-m", "unittest"),),
            )
        self.assertNotIn(("git", "commit", "-m", "feat: task"), runner.calls)

    def test_dry_run_does_not_create_branch_or_commit(self):
        runner = FakeRunner(" M docs/task_queue.md\0")
        message = wrapper.commit_and_open_pr(
            task_id="task",
            runner=runner,
            validation_commands=(("python3", "-m", "unittest"),),
            dry_run=True,
        )

        self.assertIn("DRY RUN: would create branch feature/task", message)
        self.assertNotIn(("git", "checkout", "-B", "feature/task"), runner.calls)
        self.assertIn(("python3", "-m", "unittest"), runner.calls)

    def test_agent_log_tail_is_included_in_pr_body(self):
        with tempfile.TemporaryDirectory() as tmp:
            log_path = Path(tmp) / "agent.log"
            log_path.write_text("\n".join(f"line {i}" for i in range(35)), encoding="utf-8")
            runner = FakeRunner(" M docs/task_queue.md\0")
            wrapper.commit_and_open_pr(
                task_id="task",
                runner=runner,
                validation_commands=(("python3", "-m", "unittest"),),
                agent_log=str(log_path),
            )

        pr_call = [call for call in runner.calls if call[:3] == ("gh", "pr", "create")][0]
        body = pr_call[pr_call.index("--body") + 1]
        self.assertIn("Agent log tail", body)
        self.assertIn("line 34", body)
        self.assertNotIn("line 0", body)


if __name__ == "__main__":
    unittest.main()
