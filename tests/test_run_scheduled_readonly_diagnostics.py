#!/usr/bin/env python3
"""Tests for scripts/run_scheduled_readonly_diagnostics.py."""

import io
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import run_scheduled_readonly_diagnostics as sched  # noqa: E402


class FakeClock:
    def __init__(self):
        self._t = datetime(2026, 7, 1, 1, 2, 3, tzinfo=timezone.utc)

    def __call__(self):
        now = self._t
        self._t = self._t + timedelta(seconds=1)
        return now


def make_args(tmp, **overrides):
    import argparse

    return argparse.Namespace(
        dry_run=overrides.get("dry_run", False),
        db_path=overrides.get("db_path", str(Path(tmp) / "runtime" / "dlmm.duckdb")),
        log_dir=str(Path(tmp) / "logs"),
        lock_dir=str(Path(tmp) / "locks"),
        continue_on_ohlcv_error=overrides.get("continue_on_ohlcv_error", False),
        skip_pipeline=overrides.get("skip_pipeline", False),
        skip_reports=overrides.get("skip_reports", False),
    )


def runner_factory(exit_codes=None):
    exit_codes = exit_codes or {}
    calls = []

    def run(command):
        calls.append(command)
        code = exit_codes.get(command.name, 0)
        return sched.CommandResult(
            name=command.name,
            argv=command.argv,
            exit_code=code,
            stdout=f"stdout {command.name}\n",
            stderr="" if code == 0 else f"stderr {command.name}\n",
        )

    run.calls = calls
    return run


class PlanTests(unittest.TestCase):
    def test_default_plan_orchestrates_pipeline_then_reports(self):
        with tempfile.TemporaryDirectory() as tmp:
            args = make_args(tmp)
            commands = sched.build_commands(args)
            names = [c.name for c in commands]
            self.assertEqual(names[0], "readonly_pipeline")
            self.assertEqual(
                names[1:],
                [
                    "runtime_risk_dashboard",
                    "argus_proposal",
                    "fee_pool_diagnostics",
                    "pair_stability_diagnostics",
                    "candidate_deep_review",
                    "candidate_evidence_pack",
                    "manual_council_review_matrix",
                ],
            )
            self.assertIn("scripts/run_readonly_pipeline.py", commands[0].argv)
            self.assertIn("--import-risk-decisions-db", commands[0].argv)
            self.assertIn("scripts/build_runtime_risk_dashboard.py", commands[1].argv)

    def test_skip_flags_narrow_the_plan(self):
        with tempfile.TemporaryDirectory() as tmp:
            only_reports = sched.build_commands(make_args(tmp, skip_pipeline=True))
            self.assertNotIn("readonly_pipeline", [c.name for c in only_reports])

            only_pipeline = sched.build_commands(make_args(tmp, skip_reports=True))
            self.assertEqual([c.name for c in only_pipeline], ["readonly_pipeline"])


class DryRunTests(unittest.TestCase):
    def test_dry_run_creates_nothing_and_runs_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            buf = io.StringIO()
            args = make_args(tmp, dry_run=True)
            with redirect_stdout(buf):
                rc = sched.execute_run(
                    args,
                    command_runner=lambda command: (_ for _ in ()).throw(
                        AssertionError("command must not run during dry-run")
                    ),
                    fpe_checker=lambda db: (_ for _ in ()).throw(
                        AssertionError("DB must not be checked during dry-run")
                    ),
                    now_fn=FakeClock(),
                )
            self.assertEqual(rc, 0)
            self.assertIn("DRY RUN", buf.getvalue())
            self.assertIn("no reports written", buf.getvalue())
            self.assertFalse((Path(tmp) / "logs").exists())
            self.assertFalse((Path(tmp) / "locks").exists())
            self.assertEqual(list(Path(tmp).rglob(sched.LOCK_FILENAME)), [])


class LockTests(unittest.TestCase):
    def test_active_lock_prevents_overlapping_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            args = make_args(tmp)
            Path(args.lock_dir).mkdir(parents=True, exist_ok=True)
            lock_path = sched.lock_file_path(args.lock_dir)
            sched.write_lock(lock_path, os.getpid(), "now", "cmd", tmp)

            err = io.StringIO()
            with redirect_stderr(err):
                rc = sched.execute_run(
                    args,
                    command_runner=runner_factory(),
                    fpe_checker=lambda db: 0,
                    now_fn=FakeClock(),
                )

            self.assertEqual(rc, 2)
            self.assertIn("Refusing overlap", err.getvalue())
            self.assertEqual(sched.read_lock(lock_path)["pid"], os.getpid())

    def test_stale_lock_is_replaced_and_released(self):
        with tempfile.TemporaryDirectory() as tmp:
            args = make_args(tmp, skip_pipeline=True, skip_reports=True)
            Path(args.lock_dir).mkdir(parents=True, exist_ok=True)
            lock_path = sched.lock_file_path(args.lock_dir)
            sched.write_lock(lock_path, 2**22, "old", "cmd", tmp)

            rc = sched.execute_run(
                args,
                command_runner=runner_factory(),
                fpe_checker=lambda db: 0,
                now_fn=FakeClock(),
            )

            self.assertEqual(rc, 0)
            self.assertFalse(lock_path.exists())


class ExecutionTests(unittest.TestCase):
    def test_success_logs_commands_and_checks_fpe_before_and_after(self):
        with tempfile.TemporaryDirectory() as tmp:
            args = make_args(tmp)
            runner = runner_factory()
            checks = []

            def check(db):
                checks.append(db)
                return 0

            rc = sched.execute_run(
                args,
                command_runner=runner,
                fpe_checker=check,
                now_fn=FakeClock(),
            )

            self.assertEqual(rc, 0)
            self.assertEqual(len(checks), 2)
            self.assertEqual(len(runner.calls), 8)
            self.assertFalse(sched.lock_file_path(args.lock_dir).exists())
            logs = list(Path(args.log_dir).glob("scheduled_readonly_runner_*.log"))
            self.assertEqual(len(logs), 1)
            text = logs[0].read_text(encoding="utf-8")
            self.assertIn("PRECHECK: future_position_events count = 0", text)
            self.assertIn("POSTCHECK: future_position_events count = 0", text)
            self.assertIn("COMMAND START: readonly_pipeline", text)
            self.assertIn("STATUS: SUCCESS", text)

    def test_nonzero_fpe_precheck_stops_before_commands(self):
        with tempfile.TemporaryDirectory() as tmp:
            args = make_args(tmp)
            runner = runner_factory()
            err = io.StringIO()

            def fail_check(db):
                raise RuntimeError(f"{sched.FPE_NONZERO_MSG}: 1 (expected 0)")

            with redirect_stderr(err):
                rc = sched.execute_run(
                    args,
                    command_runner=runner,
                    fpe_checker=fail_check,
                    now_fn=FakeClock(),
                )

            self.assertEqual(rc, 1)
            self.assertEqual(runner.calls, [])
            self.assertIn(sched.FPE_NONZERO_MSG, err.getvalue())
            self.assertFalse(sched.lock_file_path(args.lock_dir).exists())

    def test_child_failure_stops_later_commands(self):
        with tempfile.TemporaryDirectory() as tmp:
            args = make_args(tmp)
            runner = runner_factory({"fee_pool_diagnostics": 1})
            err = io.StringIO()

            with redirect_stderr(err):
                rc = sched.execute_run(
                    args,
                    command_runner=runner,
                    fpe_checker=lambda db: 0,
                    now_fn=FakeClock(),
                )

            self.assertEqual(rc, 1)
            self.assertIn("fee_pool_diagnostics failed", err.getvalue())
            names = [c.name for c in runner.calls]
            self.assertEqual(
                names,
                [
                    "readonly_pipeline",
                    "runtime_risk_dashboard",
                    "argus_proposal",
                    "fee_pool_diagnostics",
                ],
            )


class SafetyTextTests(unittest.TestCase):
    def test_safety_banner_contains_forbidden_capabilities(self):
        for term in [
            "No wallet",
            "No private key",
            "No seed phrase",
            "No signing",
            "No swap",
            "No LP add/remove",
            "No rebalance",
            "No live execution",
            "No signal generation",
            "No paper position creation",
            "No future_position_events writes",
        ]:
            self.assertIn(term, sched.SAFETY_BANNER)


if __name__ == "__main__":
    unittest.main()
