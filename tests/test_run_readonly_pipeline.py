#!/usr/bin/env python3
"""
test_run_readonly_pipeline.py — unit tests for the Read-only Runtime Orchestrator.

Stdlib-only (unittest). No network. The only filesystem writes go to a temporary
directory created per test. Child pipeline scripts are never executed: a fake,
injected step runner stands in for subprocess so the tests are deterministic and
fast.

Run: python3 -m unittest tests/test_run_readonly_pipeline.py
"""

import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import run_readonly_pipeline as rop  # noqa: E402


# A fixed clock that advances one second on each call, so durations are stable.
class FakeClock:
    def __init__(self, start=None):
        self._t = start or datetime(2026, 6, 30, 12, 0, 0, tzinfo=timezone.utc)

    def __call__(self):
        now = self._t
        self._t = self._t + timedelta(seconds=1)
        return now


def make_args(tmp, **overrides):
    """Build an argparse-like namespace pointing runtime dirs at tmp."""
    import argparse

    ns = argparse.Namespace(
        dry_run=overrides.get("dry_run", False),
        continue_on_ohlcv_error=overrides.get("continue_on_ohlcv_error", False),
        log_dir=str(Path(tmp) / "logs"),
        lock_dir=str(Path(tmp) / "locks"),
        summary_dir=str(Path(tmp) / "summaries"),
    )
    return ns


def fake_runner_factory(exit_codes):
    """Return a step runner that records calls and returns mapped exit codes.

    exit_codes: dict of step_name -> exit_code (default 0). The returned runner
    exposes `.calls` listing the step names it was asked to run.
    """
    calls = []

    def runner(name, command):
        calls.append(name)
        code = exit_codes.get(name, 0)
        return code, f"stdout for {name}\n", "" if code == 0 else f"stderr for {name}\n"

    runner.calls = calls
    return runner


class SafetyBannerTests(unittest.TestCase):
    def test_banner_contains_all_forbidden_terms(self):
        banner = rop.SAFETY_BANNER
        for term in [
            "READ_ONLY / RESEARCH_ONLY / SCREENING_ONLY / PAPER_ONLY",
            "No wallet",
            "No private key",
            "No signing",
            "No swap",
            "No LP",
            "No rebalance",
            "No live execution",
            "No LIVE_ELIGIBLE_*",
        ]:
            self.assertIn(term, banner)


class DryRunTests(unittest.TestCase):
    def test_dry_run_creates_nothing_and_runs_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            # Sentinel runner: if called, the test must fail.
            def boom(name, command):  # pragma: no cover - must never run
                raise AssertionError("child step executed during dry run")

            rc = rop.main(
                [
                    "--dry-run",
                    "--log-dir", str(Path(tmp) / "logs"),
                    "--lock-dir", str(Path(tmp) / "locks"),
                    "--summary-dir", str(Path(tmp) / "summaries"),
                ]
            )
            self.assertEqual(rc, 0)
            # No runtime directories were created.
            self.assertFalse((Path(tmp) / "logs").exists())
            self.assertFalse((Path(tmp) / "locks").exists())
            self.assertFalse((Path(tmp) / "summaries").exists())
            # No lock file anywhere under tmp.
            self.assertEqual(list(Path(tmp).rglob(rop.LOCK_FILENAME)), [])


class LockTests(unittest.TestCase):
    def test_lock_file_path_constructed_safely(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = rop.lock_file_path(tmp)
            self.assertEqual(path, Path(tmp) / rop.LOCK_FILENAME)
            self.assertEqual(path.parent, Path(tmp))

    def test_active_lock_detection_uses_current_pid(self):
        with tempfile.TemporaryDirectory() as tmp:
            lock_path = rop.lock_file_path(tmp)
            # Write a lock owned by the current (definitely alive) process.
            rop.write_lock(lock_path, os.getpid(), "2026-06-30T12:00:00+00:00", "cmd", tmp)
            self.assertTrue(rop.pid_is_active(os.getpid()))
            with self.assertRaises(rop.LockHeldError):
                rop.acquire_lock(lock_path, os.getpid() + 0, "now", "cmd", tmp)

    def test_stale_lock_detection_with_dead_pid(self):
        with tempfile.TemporaryDirectory() as tmp:
            lock_path = rop.lock_file_path(tmp)
            dead_pid = self._find_dead_pid()
            self.assertFalse(rop.pid_is_active(dead_pid))
            rop.write_lock(lock_path, dead_pid, "2026-06-30T12:00:00+00:00", "cmd", tmp)
            stale = rop.acquire_lock(lock_path, os.getpid(), "now", "cmd", tmp)
            self.assertTrue(stale)
            # The lock now records the live pid.
            self.assertEqual(rop.read_lock(lock_path)["pid"], os.getpid())

    def test_release_lock_is_idempotent(self):
        with tempfile.TemporaryDirectory() as tmp:
            lock_path = rop.lock_file_path(tmp)
            rop.write_lock(lock_path, os.getpid(), "now", "cmd", tmp)
            rop.release_lock(lock_path)
            self.assertFalse(Path(lock_path).exists())
            # Second release must not raise.
            rop.release_lock(lock_path)

    @staticmethod
    def _find_dead_pid():
        # Search high PIDs for one with no live process.
        for candidate in range(2 ** 22, 2 ** 22 + 1000):
            if not rop.pid_is_active(candidate):
                return candidate
        raise RuntimeError("could not find a dead pid for test")


class SummaryGenerationTests(unittest.TestCase):
    def _fake_outcome(self, status="SUCCESS", ohlcv_tolerated=False):
        outcome = rop.PipelineOutcome(status=status, ohlcv_error_tolerated=ohlcv_tolerated)
        outcome.steps = [
            rop.StepResult(
                name="fetch_meteora_pools",
                command="python3 scripts/fetch_meteora_pools.py",
                started_at="2026-06-30T12:00:00+00:00",
                ended_at="2026-06-30T12:00:01+00:00",
                duration_seconds=1.0,
                exit_code=0,
                status="OK",
            ),
            rop.StepResult(
                name="validate_watchlist",
                command="python3 scripts/validate_watchlist.py",
                started_at="2026-06-30T12:00:01+00:00",
                ended_at="2026-06-30T12:00:02+00:00",
                duration_seconds=1.0,
                exit_code=0,
                status="OK",
            ),
        ]
        return outcome

    def test_summary_json_dict_has_required_fields(self):
        start = datetime(2026, 6, 30, 12, 0, 0, tzinfo=timezone.utc)
        end = start + timedelta(seconds=2)
        summary = rop.build_summary_dict(
            run_id="20260630T120000_000000",
            started_at=start,
            ended_at=end,
            outcome=self._fake_outcome(),
            continue_on_ohlcv_error=False,
            stale_lock_replaced=True,
            log_file="runtime/logs/run.log",
        )
        for key in [
            "run_id", "started_at", "ended_at", "duration_seconds", "status",
            "safety_phase", "continue_on_ohlcv_error", "stale_lock_replaced",
            "log_file", "steps",
        ]:
            self.assertIn(key, summary)
        self.assertEqual(summary["safety_phase"], rop.SAFETY_PHASE)
        self.assertEqual(summary["stale_lock_replaced"], True)
        self.assertEqual(len(summary["steps"]), 2)
        self.assertEqual(summary["steps"][0]["name"], "fetch_meteora_pools")

    def test_summary_markdown_includes_banner_and_note(self):
        start = datetime(2026, 6, 30, 12, 0, 0, tzinfo=timezone.utc)
        summary = rop.build_summary_dict(
            run_id="rid",
            started_at=start,
            ended_at=start + timedelta(seconds=2),
            outcome=self._fake_outcome(),
            continue_on_ohlcv_error=False,
            stale_lock_replaced=False,
            log_file="runtime/logs/run.log",
        )
        md = rop.build_summary_markdown(summary, "runtime/run_summaries/run.json")
        self.assertIn(rop.SAFETY_BANNER, md)
        self.assertIn("does **not** authorize", md)
        self.assertIn("| `fetch_meteora_pools` |", md)
        self.assertIn("runtime/run_summaries/run.json", md)
        self.assertIn("runtime/logs/run.log", md)


class PipelineBehaviorTests(unittest.TestCase):
    def _steps(self):
        # Mirror real ordering with placeholder commands.
        return [
            ("fetch_meteora_pools", ["python3", "scripts/fetch_meteora_pools.py"]),
            ("build_watchlist", ["python3", "scripts/build_watchlist.py"]),
            (rop.OHLCV_STEP_NAME, ["python3", "scripts/fetch_ohlcv_top_pairs.py"]),
            ("classify_strategy", ["python3", "scripts/classify_strategy.py"]),
            ("observe_strategy", ["python3", "scripts/observe_strategy.py"]),
            (rop.VALIDATE_STEP_NAME, ["python3", "scripts/validate_watchlist.py"]),
        ]

    def test_validation_failure_fails_runner(self):
        runner = fake_runner_factory({rop.VALIDATE_STEP_NAME: 1})
        outcome = rop.run_pipeline(
            self._steps(), runner, continue_on_ohlcv_error=True, now_fn=FakeClock()
        )
        self.assertEqual(outcome.status, "FAILED")
        # Every step up to and including validate ran; validate is last.
        self.assertIn(rop.VALIDATE_STEP_NAME, runner.calls)
        self.assertEqual(outcome.steps[-1].name, rop.VALIDATE_STEP_NAME)
        self.assertEqual(outcome.steps[-1].exit_code, 1)

    def test_ohlcv_failure_continues_when_flag_true(self):
        runner = fake_runner_factory({rop.OHLCV_STEP_NAME: 1})
        outcome = rop.run_pipeline(
            self._steps(), runner, continue_on_ohlcv_error=True, now_fn=FakeClock()
        )
        self.assertEqual(outcome.status, "SUCCESS")
        self.assertTrue(outcome.ohlcv_error_tolerated)
        # Steps after OHLCV still executed.
        self.assertIn("classify_strategy", runner.calls)
        self.assertIn("observe_strategy", runner.calls)
        self.assertIn(rop.VALIDATE_STEP_NAME, runner.calls)

    def test_ohlcv_failure_fails_when_flag_false(self):
        runner = fake_runner_factory({rop.OHLCV_STEP_NAME: 1})
        outcome = rop.run_pipeline(
            self._steps(), runner, continue_on_ohlcv_error=False, now_fn=FakeClock()
        )
        self.assertEqual(outcome.status, "FAILED")
        self.assertFalse(outcome.ohlcv_error_tolerated)
        # Pipeline stopped at OHLCV; later steps did not run.
        self.assertNotIn("classify_strategy", runner.calls)
        self.assertNotIn(rop.VALIDATE_STEP_NAME, runner.calls)

    def test_all_ok_is_success(self):
        runner = fake_runner_factory({})
        outcome = rop.run_pipeline(
            self._steps(), runner, continue_on_ohlcv_error=False, now_fn=FakeClock()
        )
        self.assertEqual(outcome.status, "SUCCESS")
        self.assertEqual(len(outcome.steps), len(self._steps()))


class ExecuteRunIntegrationTests(unittest.TestCase):
    def test_execute_run_writes_artifacts_and_releases_lock(self):
        with tempfile.TemporaryDirectory() as tmp:
            args = make_args(tmp)
            runner = fake_runner_factory({})
            steps = [
                ("fetch_meteora_pools", ["python3", "scripts/fetch_meteora_pools.py"]),
                (rop.VALIDATE_STEP_NAME, ["python3", "scripts/validate_watchlist.py"]),
            ]
            rc = rop.execute_run(args, steps=steps, step_runner=runner, now_fn=FakeClock())
            self.assertEqual(rc, 0)
            # Lock removed on clean exit.
            self.assertFalse(rop.lock_file_path(args.lock_dir).exists())
            # Exactly one log, one json, one md produced.
            logs = list(Path(args.log_dir).glob("run_*.log"))
            jsons = list(Path(args.summary_dir).glob("run_*.json"))
            mds = list(Path(args.summary_dir).glob("run_*.md"))
            self.assertEqual(len(logs), 1)
            self.assertEqual(len(jsons), 1)
            self.assertEqual(len(mds), 1)

    def test_execute_run_returns_2_when_active_lock_held(self):
        with tempfile.TemporaryDirectory() as tmp:
            args = make_args(tmp)
            Path(args.lock_dir).mkdir(parents=True, exist_ok=True)
            rop.write_lock(
                rop.lock_file_path(args.lock_dir),
                os.getpid(), "now", "cmd", tmp,
            )
            runner = fake_runner_factory({})
            rc = rop.execute_run(args, steps=self._noop_steps(), step_runner=runner, now_fn=FakeClock())
            self.assertEqual(rc, 2)
            # The pre-existing active lock must be left intact.
            self.assertEqual(rop.read_lock(rop.lock_file_path(args.lock_dir))["pid"], os.getpid())

    @staticmethod
    def _noop_steps():
        return [("fetch_meteora_pools", ["python3", "scripts/fetch_meteora_pools.py"])]


if __name__ == "__main__":
    unittest.main()
