#!/usr/bin/env python3
"""
test_run_readonly_pipeline.py — unit tests for the Read-only Runtime Orchestrator.

Stdlib-only (unittest). No network. The only filesystem writes go to a temporary
directory created per test. Child pipeline scripts are never executed: a fake,
injected step runner stands in for subprocess so the tests are deterministic and
fast.

Run: python3 -m unittest tests/test_run_readonly_pipeline.py
"""

import importlib.util
import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import run_readonly_pipeline as rop  # noqa: E402


def _load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# Loaded only to initialize a real DuckDB for the integration tests below.
idb = _load_module("init_runtime_db", REPO_ROOT / "scripts" / "init_runtime_db.py")

try:
    import duckdb  # noqa: F401

    HAS_DUCKDB = True
except ImportError:
    HAS_DUCKDB = False


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
        write_db=overrides.get("write_db", None),
        import_observations_db=overrides.get("import_observations_db", False),
        observations_jsonl=overrides.get(
            "observations_jsonl", rop.DEFAULT_OBSERVATIONS_JSONL
        ),
        import_risk_flags=overrides.get("import_risk_flags", False),
        import_risk_decisions_db=overrides.get("import_risk_decisions_db", False),
        risk_decisions_csv=overrides.get(
            "risk_decisions_csv", rop.DEFAULT_RISK_DECISIONS_CSV
        ),
        build_manual_council_review_matrix=overrides.get(
            "build_manual_council_review_matrix", False
        ),
        manual_council_review_matrix_md=overrides.get(
            "manual_council_review_matrix_md", rop.DEFAULT_MATRIX_OUT_MD
        ),
        manual_council_review_matrix_csv=overrides.get(
            "manual_council_review_matrix_csv", rop.DEFAULT_MATRIX_OUT_CSV
        ),
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
            (rop.RISK_POLICY_STEP_NAME, ["python3", "scripts/apply_risk_policy.py"]),
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
        self.assertIn(rop.RISK_POLICY_STEP_NAME, runner.calls)
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


class DefaultStepsOrderTests(unittest.TestCase):
    """The default pipeline must include apply_risk_policy in the right slot."""

    def test_default_steps_include_risk_policy_in_correct_order(self):
        names = [name for name, _ in rop.build_default_steps()]
        self.assertIn(rop.RISK_POLICY_STEP_NAME, names)
        # apply_risk_policy runs AFTER observe_strategy and BEFORE validate.
        self.assertEqual(
            names,
            [
                "fetch_meteora_pools",
                "build_watchlist",
                rop.OHLCV_STEP_NAME,
                "classify_strategy",
                "observe_strategy",
                rop.RISK_POLICY_STEP_NAME,
                rop.VALIDATE_STEP_NAME,
            ],
        )
        self.assertLess(
            names.index("observe_strategy"), names.index(rop.RISK_POLICY_STEP_NAME)
        )
        self.assertLess(
            names.index(rop.RISK_POLICY_STEP_NAME), names.index(rop.VALIDATE_STEP_NAME)
        )
        # validate_watchlist remains the final step.
        self.assertEqual(names[-1], rop.VALIDATE_STEP_NAME)

    def test_default_risk_policy_step_invokes_apply_risk_policy(self):
        steps = dict(rop.build_default_steps())
        command = steps[rop.RISK_POLICY_STEP_NAME]
        self.assertIn("scripts/apply_risk_policy.py", command)

    def test_dry_run_lists_risk_policy_step_in_order(self):
        with tempfile.TemporaryDirectory() as tmp:
            buf = io.StringIO()
            with redirect_stdout(buf):
                rc = rop.main(
                    [
                        "--dry-run",
                        "--log-dir", str(Path(tmp) / "logs"),
                        "--lock-dir", str(Path(tmp) / "locks"),
                        "--summary-dir", str(Path(tmp) / "summaries"),
                    ]
                )
            self.assertEqual(rc, 0)
            out = buf.getvalue()
            self.assertIn(rop.RISK_POLICY_STEP_NAME, out)
            self.assertIn("scripts/apply_risk_policy.py", out)
            # Order is preserved in the printed plan.
            self.assertLess(
                out.index("observe_strategy"), out.index(rop.RISK_POLICY_STEP_NAME)
            )
            self.assertLess(
                out.index(rop.RISK_POLICY_STEP_NAME),
                out.index(rop.VALIDATE_STEP_NAME),
            )
            # Dry run still creates nothing.
            self.assertFalse((Path(tmp) / "logs").exists())
            self.assertFalse((Path(tmp) / "locks").exists())
            self.assertFalse((Path(tmp) / "summaries").exists())


class RiskPolicyStepFailureTests(unittest.TestCase):
    """apply_risk_policy is never continue-on-error; its failure fails the run."""

    def test_risk_policy_failure_fails_runner_and_stops_validate(self):
        steps = PipelineBehaviorTests._steps(PipelineBehaviorTests())
        runner = fake_runner_factory({rop.RISK_POLICY_STEP_NAME: 1})
        outcome = rop.run_pipeline(
            steps, runner, continue_on_ohlcv_error=False, now_fn=FakeClock()
        )
        self.assertEqual(outcome.status, "FAILED")
        # Risk policy ran and failed; validate never ran (pipeline stopped).
        self.assertIn(rop.RISK_POLICY_STEP_NAME, runner.calls)
        self.assertNotIn(rop.VALIDATE_STEP_NAME, runner.calls)
        self.assertEqual(outcome.steps[-1].name, rop.RISK_POLICY_STEP_NAME)
        self.assertEqual(outcome.steps[-1].exit_code, 1)

    def test_risk_policy_failure_unaffected_by_continue_on_ohlcv_error(self):
        steps = PipelineBehaviorTests._steps(PipelineBehaviorTests())
        runner = fake_runner_factory({rop.RISK_POLICY_STEP_NAME: 1})
        # Even with the OHLCV toleration flag set, the risk policy failure is
        # NOT tolerated: only the OHLCV step is ever continue-on-error.
        outcome = rop.run_pipeline(
            steps, runner, continue_on_ohlcv_error=True, now_fn=FakeClock()
        )
        self.assertEqual(outcome.status, "FAILED")
        self.assertFalse(outcome.ohlcv_error_tolerated)
        self.assertIn(rop.RISK_POLICY_STEP_NAME, runner.calls)
        self.assertNotIn(rop.VALIDATE_STEP_NAME, runner.calls)

    def test_risk_policy_runs_after_observe_and_before_validate(self):
        steps = PipelineBehaviorTests._steps(PipelineBehaviorTests())
        runner = fake_runner_factory({})
        outcome = rop.run_pipeline(
            steps, runner, continue_on_ohlcv_error=False, now_fn=FakeClock()
        )
        self.assertEqual(outcome.status, "SUCCESS")
        self.assertLess(
            runner.calls.index("observe_strategy"),
            runner.calls.index(rop.RISK_POLICY_STEP_NAME),
        )
        self.assertLess(
            runner.calls.index(rop.RISK_POLICY_STEP_NAME),
            runner.calls.index(rop.VALIDATE_STEP_NAME),
        )


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


# --------------------------------------------------------------------------- #
# Optional DuckDB write support (--write-db)
# --------------------------------------------------------------------------- #

def _ok_steps():
    return [
        ("fetch_meteora_pools", ["python3", "scripts/fetch_meteora_pools.py"]),
        (rop.VALIDATE_STEP_NAME, ["python3", "scripts/validate_watchlist.py"]),
    ]


def _read_summary_json(summary_dir):
    jsons = list(Path(summary_dir).glob("run_*.json"))
    assert len(jsons) == 1, f"expected one summary json, found {jsons}"
    with jsons[0].open("r", encoding="utf-8") as fh:
        return json.load(fh)


def _read_summary_md(summary_dir):
    mds = list(Path(summary_dir).glob("run_*.md"))
    assert len(mds) == 1, f"expected one summary md, found {mds}"
    return mds[0].read_text(encoding="utf-8")


class WriteDbDefaultTests(unittest.TestCase):
    """Default behavior: no --write-db means no DB dependency and no DB write."""

    def test_default_run_does_not_import_or_write_db(self):
        with tempfile.TemporaryDirectory() as tmp:
            args = make_args(tmp)  # write_db defaults to None
            runner = fake_runner_factory({})

            # If the importer is reached at all, fail the test.
            def boom(*a, **k):  # pragma: no cover - must never run
                raise AssertionError("DB import must not run without --write-db")

            original = rop.import_run_summary_into_db
            rop.import_run_summary_into_db = boom
            try:
                rc = rop.execute_run(
                    args, steps=_ok_steps(), step_runner=runner, now_fn=FakeClock()
                )
            finally:
                rop.import_run_summary_into_db = original

            self.assertEqual(rc, 0)
            summary = _read_summary_json(args.summary_dir)
            self.assertEqual(summary["db_write_status"], rop.DB_WRITE_NOT_REQUESTED)
            self.assertIsNone(summary["db_path"])

    def test_summary_has_not_requested_status_fields(self):
        with tempfile.TemporaryDirectory() as tmp:
            args = make_args(tmp)
            rop.execute_run(
                args, steps=_ok_steps(), step_runner=fake_runner_factory({}),
                now_fn=FakeClock(),
            )
            summary = _read_summary_json(args.summary_dir)
            self.assertIn("db_write_status", summary)
            self.assertIn("db_path", summary)
            md = _read_summary_md(args.summary_dir)
            self.assertIn("DB write status", md)
            self.assertIn(rop.DB_WRITE_NOT_REQUESTED, md)


class WriteDbDryRunTests(unittest.TestCase):
    def test_dry_run_with_write_db_touches_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "runtime" / "dlmm.duckdb"  # does NOT exist

            def boom(name, command):  # pragma: no cover - must never run
                raise AssertionError("child step executed during dry run")

            buf = io.StringIO()
            with redirect_stdout(buf):
                rc = rop.main(
                    [
                        "--dry-run",
                        "--write-db", str(db_path),
                        "--log-dir", str(Path(tmp) / "logs"),
                        "--lock-dir", str(Path(tmp) / "locks"),
                        "--summary-dir", str(Path(tmp) / "summaries"),
                    ]
                )
            self.assertEqual(rc, 0)
            # No runtime dirs, no DB, no lock created.
            self.assertFalse((Path(tmp) / "logs").exists())
            self.assertFalse((Path(tmp) / "locks").exists())
            self.assertFalse((Path(tmp) / "summaries").exists())
            self.assertFalse(db_path.exists())
            self.assertFalse(db_path.parent.exists())
            # Must announce that a DB write is planned but not executed.
            out = buf.getvalue()
            self.assertIn("PLANNED", out)
            self.assertIn("NOT executed", out)


class WriteDbMissingDbTests(unittest.TestCase):
    def test_missing_db_fails_with_clear_message_and_no_dirs(self):
        with tempfile.TemporaryDirectory() as tmp:
            args = make_args(tmp, write_db=str(Path(tmp) / "runtime" / "dlmm.duckdb"))

            def boom(name, command):  # pragma: no cover - pipeline must not run
                raise AssertionError("pipeline ran despite missing DB")

            err = io.StringIO()
            with redirect_stdout(io.StringIO()), redirect_stderr(err):
                rc = rop.execute_run(
                    args, steps=_ok_steps(), step_runner=boom, now_fn=FakeClock()
                )
            self.assertEqual(rc, 2)
            self.assertEqual(err.getvalue().strip(), f"ERROR: {rop.DB_MISSING_MSG}")
            self.assertEqual(
                err.getvalue().strip(),
                "ERROR: DuckDB database not found. Run scripts/init_runtime_db.py first.",
            )
            # Fail-fast: no runtime dirs and definitely no DB created.
            self.assertFalse((Path(args.log_dir)).exists())
            self.assertFalse((Path(args.lock_dir)).exists())
            self.assertFalse((Path(args.summary_dir)).exists())
            self.assertFalse(Path(args.write_db).exists())
            self.assertFalse(Path(args.write_db).parent.exists())


class WriteDbImportStatusTests(unittest.TestCase):
    """Status plumbing via a fake importer — runs without duckdb installed."""

    def _existing_db_path(self, tmp):
        # A plain file is enough to pass the runner's pre-flight existence check;
        # the importer itself is faked in these tests.
        db_path = Path(tmp) / "runtime" / "dlmm.duckdb"
        db_path.parent.mkdir(parents=True, exist_ok=True)
        db_path.write_text("placeholder")
        return db_path

    def test_success_status_recorded_in_json_and_md(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = self._existing_db_path(tmp)
            args = make_args(tmp, write_db=str(db_path))
            calls = []

            def fake_import(p, s):
                calls.append((str(p), str(s)))
                return rop.DB_WRITE_SUCCESS

            original = rop.import_run_summary_into_db
            rop.import_run_summary_into_db = fake_import
            try:
                rc = rop.execute_run(
                    args, steps=_ok_steps(), step_runner=fake_runner_factory({}),
                    now_fn=FakeClock(),
                )
            finally:
                rop.import_run_summary_into_db = original

            self.assertEqual(rc, 0)
            self.assertEqual(len(calls), 1)
            summary = _read_summary_json(args.summary_dir)
            # Import is called with the summary JSON that exists on disk.
            on_disk = next(Path(args.summary_dir).glob("run_*.json"))
            self.assertEqual(calls[0][1], str(on_disk))
            self.assertEqual(summary["db_write_status"], rop.DB_WRITE_SUCCESS)
            self.assertEqual(summary["db_path"], str(db_path))
            md = _read_summary_md(args.summary_dir)
            self.assertIn("DB write status", md)
            self.assertIn(rop.DB_WRITE_SUCCESS, md)

    def test_import_failure_makes_runner_exit_nonzero(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = self._existing_db_path(tmp)
            args = make_args(tmp, write_db=str(db_path))

            def fake_import(p, s):
                return rop.DB_WRITE_FAILED

            original = rop.import_run_summary_into_db
            rop.import_run_summary_into_db = fake_import
            try:
                rc = rop.execute_run(
                    args, steps=_ok_steps(), step_runner=fake_runner_factory({}),
                    now_fn=FakeClock(),
                )
            finally:
                rop.import_run_summary_into_db = original

            # Pipeline succeeded, but import failed -> non-zero exit.
            self.assertNotEqual(rc, 0)
            summary = _read_summary_json(args.summary_dir)
            self.assertEqual(summary["status"], "SUCCESS")
            self.assertEqual(summary["db_write_status"], rop.DB_WRITE_FAILED)

    def test_failed_pipeline_still_imports_and_still_exits_nonzero(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = self._existing_db_path(tmp)
            args = make_args(tmp, write_db=str(db_path))
            calls = []

            def fake_import(p, s):
                calls.append((str(p), str(s)))
                return rop.DB_WRITE_SUCCESS

            original = rop.import_run_summary_into_db
            rop.import_run_summary_into_db = fake_import
            try:
                # Validation step fails -> pipeline FAILED.
                runner = fake_runner_factory({rop.VALIDATE_STEP_NAME: 1})
                rc = rop.execute_run(
                    args, steps=_ok_steps(), step_runner=runner, now_fn=FakeClock()
                )
            finally:
                rop.import_run_summary_into_db = original

            # Failed run summary was still imported...
            self.assertEqual(len(calls), 1)
            summary = _read_summary_json(args.summary_dir)
            self.assertEqual(summary["status"], "FAILED")
            self.assertEqual(summary["db_write_status"], rop.DB_WRITE_SUCCESS)
            # ...but the runner still exits non-zero because the pipeline failed.
            self.assertNotEqual(rc, 0)


@unittest.skipUnless(HAS_DUCKDB, "duckdb not installed")
class WriteDbRealDuckDbTests(unittest.TestCase):
    """End-to-end against a real initialized DuckDB via the real importer."""

    def _init_db(self, tmp):
        db_path = Path(tmp) / "runtime" / "dlmm.duckdb"
        idb.init_db(str(db_path))
        return db_path

    def _counts(self, db_path):
        conn = duckdb.connect(str(db_path))
        try:
            return {
                "runs": conn.execute("SELECT COUNT(*) FROM pipeline_runs").fetchone()[0],
                "steps": conn.execute("SELECT COUNT(*) FROM pipeline_steps").fetchone()[0],
                "obs": conn.execute(
                    "SELECT COUNT(*) FROM strategy_observations"
                ).fetchone()[0],
                "flags": conn.execute("SELECT COUNT(*) FROM risk_flags").fetchone()[0],
                "fpe": conn.execute(
                    "SELECT COUNT(*) FROM future_position_events"
                ).fetchone()[0],
            }
        finally:
            conn.close()

    def test_successful_run_imports_summary(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = self._init_db(tmp)
            args = make_args(tmp, write_db=str(db_path))
            with redirect_stdout(io.StringIO()):
                rc = rop.execute_run(
                    args, steps=_ok_steps(), step_runner=fake_runner_factory({}),
                    now_fn=FakeClock(),
                )
            self.assertEqual(rc, 0)
            counts = self._counts(db_path)
            self.assertEqual(counts["runs"], 1)
            self.assertEqual(counts["steps"], len(_ok_steps()))
            summary = _read_summary_json(args.summary_dir)
            self.assertEqual(summary["db_write_status"], rop.DB_WRITE_SUCCESS)

    def test_default_steps_import_pipeline_steps_including_risk_policy(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = self._init_db(tmp)
            args = make_args(tmp, write_db=str(db_path))
            steps = rop.build_default_steps()
            with redirect_stdout(io.StringIO()):
                rc = rop.execute_run(
                    args, steps=steps, step_runner=fake_runner_factory({}),
                    now_fn=FakeClock(),
                )
            self.assertEqual(rc, 0)
            counts = self._counts(db_path)
            self.assertEqual(counts["runs"], 1)
            # All 7 default steps recorded, including apply_risk_policy.
            self.assertEqual(counts["steps"], len(steps))
            conn = duckdb.connect(str(db_path))
            try:
                step_names = [
                    r[0]
                    for r in conn.execute(
                        "SELECT step_name FROM pipeline_steps"
                    ).fetchall()
                ]
            finally:
                conn.close()
            self.assertIn(rop.RISK_POLICY_STEP_NAME, step_names)
            self.assertIn(rop.VALIDATE_STEP_NAME, step_names)
            # No execution-layer table is ever written.
            self.assertEqual(counts["fpe"], 0)

    def test_failed_run_imports_summary_but_exits_nonzero(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = self._init_db(tmp)
            args = make_args(tmp, write_db=str(db_path))
            runner = fake_runner_factory({rop.VALIDATE_STEP_NAME: 1})
            with redirect_stdout(io.StringIO()):
                rc = rop.execute_run(
                    args, steps=_ok_steps(), step_runner=runner, now_fn=FakeClock()
                )
            self.assertNotEqual(rc, 0)
            counts = self._counts(db_path)
            self.assertEqual(counts["runs"], 1, "failed run must still be imported")
            row_status = duckdb.connect(str(db_path)).execute(
                "SELECT status FROM pipeline_runs"
            ).fetchone()[0]
            self.assertEqual(row_status, "FAILED")

    def test_write_db_only_touches_runs_and_steps(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = self._init_db(tmp)
            args = make_args(tmp, write_db=str(db_path))
            with redirect_stdout(io.StringIO()):
                rop.execute_run(
                    args, steps=_ok_steps(), step_runner=fake_runner_factory({}),
                    now_fn=FakeClock(),
                )
            counts = self._counts(db_path)
            self.assertEqual(counts["obs"], 0, "must not write strategy_observations")
            self.assertEqual(counts["flags"], 0, "must not write risk_flags")
            self.assertEqual(counts["fpe"], 0, "must not write future_position_events")

    def test_reimport_same_run_id_is_idempotent(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = self._init_db(tmp)
            args = make_args(tmp, write_db=str(db_path))
            clock = FakeClock()
            with redirect_stdout(io.StringIO()):
                rop.execute_run(
                    args, steps=_ok_steps(), step_runner=fake_runner_factory({}),
                    now_fn=clock,
                )
            summary = _read_summary_json(args.summary_dir)
            run_id = summary["run_id"]

            # Re-import the exact same summary JSON directly (upsert path).
            importer = rop._load_importer()
            with redirect_stdout(io.StringIO()):
                rc = importer.run_import(
                    db_path=str(db_path),
                    summary_json=str(next(Path(args.summary_dir).glob("run_*.json"))),
                    dry_run=False,
                    upsert=True,
                )
            self.assertEqual(rc, 0)
            counts = self._counts(db_path)
            self.assertEqual(counts["runs"], 1, "upsert must not duplicate the run")
            only_run_id = duckdb.connect(str(db_path)).execute(
                "SELECT run_id FROM pipeline_runs"
            ).fetchone()[0]
            self.assertEqual(only_run_id, run_id)


# --------------------------------------------------------------------------- #
# Optional strategy-observation import support (--import-observations-db)
# --------------------------------------------------------------------------- #

def _write_observations_jsonl(tmp, records=None, name="strategy_observations.jsonl"):
    """Write a minimal valid observations JSONL and return its path."""
    if records is None:
        records = [
            {
                "observed_at": "2026-06-30T12:00:00+00:00",
                "pair_key": "AAA-BBB",
                "pair_label": "AAA-BBB",
                "strategy_class_v2": "CORE",
                "live_eligibility": "OBSERVE_ONLY",
                "observation_ready": False,
                "risk_flags": ["LOW_LIQUIDITY"],
            }
        ]
    path = Path(tmp) / "data" / "observations" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        for r in records:
            fh.write(json.dumps(r) + "\n")
    return path


def _write_risk_decisions_csv(tmp, rows=None, name="risk_decisions.csv"):
    """Write a minimal valid risk decisions CSV and return its path.

    Column set + enum values match import_risk_decisions_to_db's requirements so
    the real importer accepts it; the forbidden-token guard is satisfied (no
    uppercase execution-authorization tokens; NOT_LIVE_ELIGIBLE is allowed).
    """
    import csv

    columns = [
        "pair_key", "pair_label", "strategy_class_v2", "pair_status_v2",
        "test_lane", "live_eligibility", "required_capability", "risk_flag_count",
        "risk_flags", "risk_decision", "risk_action", "max_allowed_action",
        "risk_blockers", "risk_warnings", "risk_required_next_step",
        "risk_policy_reason", "safety_phase",
    ]
    if rows is None:
        rows = [
            {
                "pair_key": "AAA-BBB",
                "pair_label": "AAA-BBB",
                "strategy_class_v2": "CORE",
                "pair_status_v2": "WATCHLIST",
                "test_lane": "OBSERVE",
                "live_eligibility": "NOT_LIVE_ELIGIBLE",
                "required_capability": "NONE",
                "risk_flag_count": "0",
                "risk_flags": "",
                "risk_decision": "OBSERVE_ONLY",
                "risk_action": "CONTINUE_OBSERVATION",
                "max_allowed_action": "OBSERVE_ONLY",
                "risk_blockers": "",
                "risk_warnings": "",
                "risk_required_next_step": "continue observation",
                "risk_policy_reason": "stable enough for continued observation",
                "safety_phase": rop.SAFETY_PHASE,
            }
        ]
    path = Path(tmp) / "data" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=columns)
        writer.writeheader()
        for r in rows:
            writer.writerow(r)
    return path


class ImportObservationsRequiresWriteDbTests(unittest.TestCase):
    """--import-observations-db requires --write-db, enforced before the run."""

    def test_requires_write_db_fails_before_pipeline(self):
        called = {"execute": False}

        def boom_execute(*a, **k):  # pragma: no cover - must never run
            called["execute"] = True
            raise AssertionError("pipeline ran without --write-db")

        original = rop.execute_run
        rop.execute_run = boom_execute
        err = io.StringIO()
        try:
            with redirect_stdout(io.StringIO()), redirect_stderr(err):
                rc = rop.main(["--import-observations-db"])
        finally:
            rop.execute_run = original

        self.assertEqual(rc, 2)
        self.assertFalse(called["execute"])
        self.assertIn("--import-observations-db requires --write-db", err.getvalue())

    def test_requires_write_db_also_blocks_dry_run(self):
        err = io.StringIO()
        with redirect_stdout(io.StringIO()), redirect_stderr(err):
            rc = rop.main(["--dry-run", "--import-observations-db"])
        self.assertEqual(rc, 2)
        self.assertIn("--import-observations-db requires --write-db", err.getvalue())


class ImportObservationsDryRunTests(unittest.TestCase):
    def test_dry_run_touches_no_db_and_no_dirs(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "runtime" / "dlmm.duckdb"  # does NOT exist
            obs = Path(tmp) / "data" / "observations" / "strategy_observations.jsonl"

            def boom(name, command):  # pragma: no cover - must never run
                raise AssertionError("child step executed during dry run")

            buf = io.StringIO()
            with redirect_stdout(buf):
                rc = rop.main(
                    [
                        "--dry-run",
                        "--write-db", str(db_path),
                        "--import-observations-db",
                        "--import-risk-flags",
                        "--observations-jsonl", str(obs),
                        "--log-dir", str(Path(tmp) / "logs"),
                        "--lock-dir", str(Path(tmp) / "locks"),
                        "--summary-dir", str(Path(tmp) / "summaries"),
                    ]
                )
            self.assertEqual(rc, 0)
            # No runtime dirs, no DB, no observations file created.
            self.assertFalse((Path(tmp) / "logs").exists())
            self.assertFalse((Path(tmp) / "locks").exists())
            self.assertFalse((Path(tmp) / "summaries").exists())
            self.assertFalse(db_path.exists())
            self.assertFalse(db_path.parent.exists())
            self.assertFalse(obs.exists())
            out = buf.getvalue()
            # Plans the run summary write AND the observation import.
            self.assertIn("DB write is PLANNED", out)
            self.assertIn("Observation import is PLANNED", out)
            self.assertIn("NOT executed", out)
            self.assertIn(str(obs), out)
            self.assertIn("Risk flags imported: True", out)


class ImportObservationsMissingFileTests(unittest.TestCase):
    def test_missing_observations_file_fails_before_pipeline(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "runtime" / "dlmm.duckdb"
            db_path.parent.mkdir(parents=True, exist_ok=True)
            db_path.write_text("placeholder")  # passes existence pre-flight
            missing = Path(tmp) / "data" / "observations" / "strategy_observations.jsonl"
            args = make_args(
                tmp,
                write_db=str(db_path),
                import_observations_db=True,
                observations_jsonl=str(missing),
            )

            def boom(name, command):  # pragma: no cover - pipeline must not run
                raise AssertionError("pipeline ran despite missing observations file")

            err = io.StringIO()
            with redirect_stdout(io.StringIO()), redirect_stderr(err):
                rc = rop.execute_run(
                    args, steps=_ok_steps(), step_runner=boom, now_fn=FakeClock()
                )
            self.assertEqual(rc, 2)
            self.assertIn(rop.OBS_MISSING_MSG, err.getvalue())
            self.assertIn(str(missing), err.getvalue())
            # Fail-fast: no runtime dirs created.
            self.assertFalse(Path(args.log_dir).exists())
            self.assertFalse(Path(args.lock_dir).exists())
            self.assertFalse(Path(args.summary_dir).exists())


class ImportObservationsStatusTests(unittest.TestCase):
    """Status plumbing via fake importers — runs without duckdb installed."""

    def _existing_db_path(self, tmp):
        db_path = Path(tmp) / "runtime" / "dlmm.duckdb"
        db_path.parent.mkdir(parents=True, exist_ok=True)
        db_path.write_text("placeholder")
        return db_path

    def test_default_run_does_not_import_observations(self):
        with tempfile.TemporaryDirectory() as tmp:
            args = make_args(tmp)  # no write_db, no import_observations_db

            def boom(*a, **k):  # pragma: no cover - must never run
                raise AssertionError("observation import must not run by default")

            original = rop.import_observations_into_db
            rop.import_observations_into_db = boom
            try:
                rc = rop.execute_run(
                    args, steps=_ok_steps(), step_runner=fake_runner_factory({}),
                    now_fn=FakeClock(),
                )
            finally:
                rop.import_observations_into_db = original

            self.assertEqual(rc, 0)
            summary = _read_summary_json(args.summary_dir)
            self.assertEqual(
                summary["observation_db_import_status"], rop.OBS_IMPORT_NOT_REQUESTED
            )
            self.assertIsNone(summary["observations_jsonl"])
            self.assertEqual(summary["import_risk_flags"], False)

    def test_observations_imported_after_successful_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = self._existing_db_path(tmp)
            obs = _write_observations_jsonl(tmp)
            args = make_args(
                tmp, write_db=str(db_path),
                import_observations_db=True, observations_jsonl=str(obs),
            )
            order = []

            def fake_summary_import(p, s):
                order.append("summary")
                return rop.DB_WRITE_SUCCESS

            obs_calls = []

            def fake_obs_import(p, o, irf):
                order.append("observations")
                obs_calls.append((str(p), str(o), irf))
                return rop.OBS_IMPORT_SUCCESS

            orig_s = rop.import_run_summary_into_db
            orig_o = rop.import_observations_into_db
            rop.import_run_summary_into_db = fake_summary_import
            rop.import_observations_into_db = fake_obs_import
            try:
                rc = rop.execute_run(
                    args, steps=_ok_steps(), step_runner=fake_runner_factory({}),
                    now_fn=FakeClock(),
                )
            finally:
                rop.import_run_summary_into_db = orig_s
                rop.import_observations_into_db = orig_o

            self.assertEqual(rc, 0)
            # Observation import runs AFTER the run summary import.
            self.assertEqual(order, ["summary", "observations"])
            self.assertEqual(len(obs_calls), 1)
            self.assertEqual(obs_calls[0][0], str(db_path))
            self.assertEqual(obs_calls[0][1], str(obs))
            summary = _read_summary_json(args.summary_dir)
            self.assertEqual(
                summary["observation_db_import_status"], rop.OBS_IMPORT_SUCCESS
            )
            self.assertEqual(summary["observations_jsonl"], str(obs))

    def test_import_risk_flags_passed_through(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = self._existing_db_path(tmp)
            obs = _write_observations_jsonl(tmp)
            captured = []

            def fake_obs_import(p, o, irf):
                captured.append(irf)
                return rop.OBS_IMPORT_SUCCESS

            orig_s = rop.import_run_summary_into_db
            orig_o = rop.import_observations_into_db
            rop.import_run_summary_into_db = lambda p, s: rop.DB_WRITE_SUCCESS
            rop.import_observations_into_db = fake_obs_import
            try:
                # With --import-risk-flags -> True passed through.
                args_on = make_args(
                    tmp, write_db=str(db_path), import_observations_db=True,
                    observations_jsonl=str(obs), import_risk_flags=True,
                )
                rop.execute_run(
                    args_on, steps=_ok_steps(),
                    step_runner=fake_runner_factory({}), now_fn=FakeClock(),
                )
                # Without it -> False passed through.
                args_off = make_args(
                    tmp, write_db=str(db_path), import_observations_db=True,
                    observations_jsonl=str(obs), import_risk_flags=False,
                )
                rop.execute_run(
                    args_off, steps=_ok_steps(),
                    step_runner=fake_runner_factory({}), now_fn=FakeClock(),
                )
            finally:
                rop.import_run_summary_into_db = orig_s
                rop.import_observations_into_db = orig_o

            self.assertEqual(captured, [True, False])

    def test_observation_import_failure_exits_nonzero(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = self._existing_db_path(tmp)
            obs = _write_observations_jsonl(tmp)
            args = make_args(
                tmp, write_db=str(db_path),
                import_observations_db=True, observations_jsonl=str(obs),
            )

            orig_s = rop.import_run_summary_into_db
            orig_o = rop.import_observations_into_db
            rop.import_run_summary_into_db = lambda p, s: rop.DB_WRITE_SUCCESS
            rop.import_observations_into_db = lambda p, o, irf: rop.OBS_IMPORT_FAILED
            try:
                rc = rop.execute_run(
                    args, steps=_ok_steps(), step_runner=fake_runner_factory({}),
                    now_fn=FakeClock(),
                )
            finally:
                rop.import_run_summary_into_db = orig_s
                rop.import_observations_into_db = orig_o

            # Pipeline + run summary import succeeded, but obs import failed.
            self.assertNotEqual(rc, 0)
            summary = _read_summary_json(args.summary_dir)
            self.assertEqual(summary["status"], "SUCCESS")
            self.assertEqual(summary["db_write_status"], rop.DB_WRITE_SUCCESS)
            self.assertEqual(
                summary["observation_db_import_status"], rop.OBS_IMPORT_FAILED
            )

    def test_failed_pipeline_still_imports_summary_and_observations(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = self._existing_db_path(tmp)
            obs = _write_observations_jsonl(tmp)
            args = make_args(
                tmp, write_db=str(db_path),
                import_observations_db=True, observations_jsonl=str(obs),
            )
            calls = {"summary": 0, "observations": 0}

            orig_s = rop.import_run_summary_into_db
            orig_o = rop.import_observations_into_db

            def fake_summary_import(p, s):
                calls["summary"] += 1
                return rop.DB_WRITE_SUCCESS

            def fake_obs_import(p, o, irf):
                calls["observations"] += 1
                return rop.OBS_IMPORT_SUCCESS

            rop.import_run_summary_into_db = fake_summary_import
            rop.import_observations_into_db = fake_obs_import
            try:
                runner = fake_runner_factory({rop.VALIDATE_STEP_NAME: 1})
                rc = rop.execute_run(
                    args, steps=_ok_steps(), step_runner=runner, now_fn=FakeClock()
                )
            finally:
                rop.import_run_summary_into_db = orig_s
                rop.import_observations_into_db = orig_o

            # Both imports still happened on a failed pipeline...
            self.assertEqual(calls["summary"], 1)
            self.assertEqual(calls["observations"], 1)
            summary = _read_summary_json(args.summary_dir)
            self.assertEqual(summary["status"], "FAILED")
            self.assertEqual(summary["db_write_status"], rop.DB_WRITE_SUCCESS)
            self.assertEqual(
                summary["observation_db_import_status"], rop.OBS_IMPORT_SUCCESS
            )
            # ...but the runner still exits non-zero because the pipeline failed.
            self.assertNotEqual(rc, 0)

    def test_summary_json_and_md_include_observation_fields(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = self._existing_db_path(tmp)
            obs = _write_observations_jsonl(tmp)
            args = make_args(
                tmp, write_db=str(db_path), import_observations_db=True,
                observations_jsonl=str(obs), import_risk_flags=True,
            )
            orig_s = rop.import_run_summary_into_db
            orig_o = rop.import_observations_into_db
            rop.import_run_summary_into_db = lambda p, s: rop.DB_WRITE_SUCCESS
            rop.import_observations_into_db = lambda p, o, irf: rop.OBS_IMPORT_SUCCESS
            try:
                rop.execute_run(
                    args, steps=_ok_steps(), step_runner=fake_runner_factory({}),
                    now_fn=FakeClock(),
                )
            finally:
                rop.import_run_summary_into_db = orig_s
                rop.import_observations_into_db = orig_o

            summary = _read_summary_json(args.summary_dir)
            for key in (
                "observation_db_import_status",
                "observations_jsonl",
                "import_risk_flags",
            ):
                self.assertIn(key, summary)
            self.assertEqual(summary["import_risk_flags"], True)

            md = _read_summary_md(args.summary_dir)
            self.assertIn("Observation DB import status", md)
            self.assertIn("Observations JSONL", md)
            self.assertIn("Risk flags imported", md)


@unittest.skipUnless(HAS_DUCKDB, "duckdb not installed")
class ImportObservationsRealDuckDbTests(unittest.TestCase):
    """End-to-end against a real initialized DuckDB via the real importers."""

    def _init_db(self, tmp):
        db_path = Path(tmp) / "runtime" / "dlmm.duckdb"
        idb.init_db(str(db_path))
        return db_path

    def _counts(self, db_path):
        conn = duckdb.connect(str(db_path))
        try:
            return {
                "runs": conn.execute("SELECT COUNT(*) FROM pipeline_runs").fetchone()[0],
                "steps": conn.execute(
                    "SELECT COUNT(*) FROM pipeline_steps"
                ).fetchone()[0],
                "obs": conn.execute(
                    "SELECT COUNT(*) FROM strategy_observations"
                ).fetchone()[0],
                "flags": conn.execute("SELECT COUNT(*) FROM risk_flags").fetchone()[0],
                "fpe": conn.execute(
                    "SELECT COUNT(*) FROM future_position_events"
                ).fetchone()[0],
            }
        finally:
            conn.close()

    def test_successful_run_imports_observations_and_risk_flags(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = self._init_db(tmp)
            obs = _write_observations_jsonl(tmp)
            args = make_args(
                tmp, write_db=str(db_path), import_observations_db=True,
                observations_jsonl=str(obs), import_risk_flags=True,
            )
            with redirect_stdout(io.StringIO()):
                rc = rop.execute_run(
                    args, steps=_ok_steps(), step_runner=fake_runner_factory({}),
                    now_fn=FakeClock(),
                )
            self.assertEqual(rc, 0)
            counts = self._counts(db_path)
            self.assertEqual(counts["runs"], 1)
            self.assertEqual(counts["steps"], len(_ok_steps()))
            self.assertEqual(counts["obs"], 1)
            self.assertGreaterEqual(counts["flags"], 1)
            # The hard boundary: future_position_events is NEVER written.
            self.assertEqual(counts["fpe"], 0)
            summary = _read_summary_json(args.summary_dir)
            self.assertEqual(
                summary["observation_db_import_status"], rop.OBS_IMPORT_SUCCESS
            )

    def test_no_future_position_events_write_introduced(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = self._init_db(tmp)
            obs = _write_observations_jsonl(tmp)
            args = make_args(
                tmp, write_db=str(db_path), import_observations_db=True,
                observations_jsonl=str(obs), import_risk_flags=True,
            )
            with redirect_stdout(io.StringIO()):
                rop.execute_run(
                    args, steps=_ok_steps(), step_runner=fake_runner_factory({}),
                    now_fn=FakeClock(),
                )
            self.assertEqual(self._counts(db_path)["fpe"], 0)

    def test_observation_import_works_with_default_seven_step_pipeline(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = self._init_db(tmp)
            obs = _write_observations_jsonl(tmp)
            args = make_args(
                tmp, write_db=str(db_path), import_observations_db=True,
                observations_jsonl=str(obs), import_risk_flags=True,
            )
            steps = rop.build_default_steps()
            with redirect_stdout(io.StringIO()):
                rc = rop.execute_run(
                    args, steps=steps, step_runner=fake_runner_factory({}),
                    now_fn=FakeClock(),
                )
            self.assertEqual(rc, 0)
            counts = self._counts(db_path)
            # Run summary still imports all 7 steps (including apply_risk_policy).
            self.assertEqual(counts["steps"], len(steps))
            # Observation import behavior is unchanged by the added step.
            self.assertEqual(counts["obs"], 1)
            self.assertGreaterEqual(counts["flags"], 1)
            # Hard boundary holds: no execution-layer rows, no risk_decisions
            # import (the runner does not import risk_decisions yet).
            self.assertEqual(counts["fpe"], 0)
            conn = duckdb.connect(str(db_path))
            try:
                step_names = [
                    r[0]
                    for r in conn.execute(
                        "SELECT step_name FROM pipeline_steps"
                    ).fetchall()
                ]
            finally:
                conn.close()
            self.assertIn(rop.RISK_POLICY_STEP_NAME, step_names)

    def test_risk_flags_not_written_without_flag(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = self._init_db(tmp)
            obs = _write_observations_jsonl(tmp)
            args = make_args(
                tmp, write_db=str(db_path), import_observations_db=True,
                observations_jsonl=str(obs), import_risk_flags=False,
            )
            with redirect_stdout(io.StringIO()):
                rc = rop.execute_run(
                    args, steps=_ok_steps(), step_runner=fake_runner_factory({}),
                    now_fn=FakeClock(),
                )
            self.assertEqual(rc, 0)
            counts = self._counts(db_path)
            self.assertEqual(counts["obs"], 1)
            self.assertEqual(counts["flags"], 0)
            self.assertEqual(counts["fpe"], 0)


# --------------------------------------------------------------------------- #
# Optional risk-decisions import support (--import-risk-decisions-db)
# --------------------------------------------------------------------------- #

class ImportRiskDecisionsRequiresWriteDbTests(unittest.TestCase):
    """--import-risk-decisions-db requires --write-db, enforced before the run."""

    def test_requires_write_db_fails_before_pipeline(self):
        called = {"execute": False}

        def boom_execute(*a, **k):  # pragma: no cover - must never run
            called["execute"] = True
            raise AssertionError("pipeline ran without --write-db")

        original = rop.execute_run
        rop.execute_run = boom_execute
        err = io.StringIO()
        try:
            with redirect_stdout(io.StringIO()), redirect_stderr(err):
                rc = rop.main(["--import-risk-decisions-db"])
        finally:
            rop.execute_run = original

        self.assertEqual(rc, 2)
        self.assertFalse(called["execute"])
        self.assertIn("--import-risk-decisions-db requires --write-db", err.getvalue())

    def test_requires_write_db_also_blocks_dry_run(self):
        err = io.StringIO()
        with redirect_stdout(io.StringIO()), redirect_stderr(err):
            rc = rop.main(["--dry-run", "--import-risk-decisions-db"])
        self.assertEqual(rc, 2)
        self.assertIn("--import-risk-decisions-db requires --write-db", err.getvalue())


class ImportRiskDecisionsDryRunTests(unittest.TestCase):
    def test_dry_run_touches_no_db_and_no_dirs(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "runtime" / "dlmm.duckdb"  # does NOT exist
            csv_path = Path(tmp) / "data" / "risk_decisions.csv"  # does NOT exist

            def boom(name, command):  # pragma: no cover - must never run
                raise AssertionError("child step executed during dry run")

            buf = io.StringIO()
            with redirect_stdout(buf):
                rc = rop.main(
                    [
                        "--dry-run",
                        "--write-db", str(db_path),
                        "--import-risk-decisions-db",
                        "--risk-decisions-csv", str(csv_path),
                        "--log-dir", str(Path(tmp) / "logs"),
                        "--lock-dir", str(Path(tmp) / "locks"),
                        "--summary-dir", str(Path(tmp) / "summaries"),
                    ]
                )
            self.assertEqual(rc, 0)
            # No runtime dirs, no DB, no CSV created.
            self.assertFalse((Path(tmp) / "logs").exists())
            self.assertFalse((Path(tmp) / "locks").exists())
            self.assertFalse((Path(tmp) / "summaries").exists())
            self.assertFalse(db_path.exists())
            self.assertFalse(db_path.parent.exists())
            self.assertFalse(csv_path.exists())
            out = buf.getvalue()
            self.assertIn("Risk decisions import is PLANNED", out)
            self.assertIn("NOT executed", out)
            self.assertIn(str(csv_path), out)


class ImportRiskDecisionsMissingFileTests(unittest.TestCase):
    def test_missing_csv_fails_after_pipeline_runs(self):
        # apply_risk_policy.py PRODUCES the risk decisions CSV, so the runner must
        # NOT fail early. The pipeline must run first; only afterwards, if the CSV
        # is still missing, does the import fail post-pipeline.
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "runtime" / "dlmm.duckdb"
            db_path.parent.mkdir(parents=True, exist_ok=True)
            db_path.write_text("placeholder")  # passes existence pre-flight
            missing = Path(tmp) / "data" / "risk_decisions.csv"
            args = make_args(
                tmp,
                write_db=str(db_path),
                import_risk_decisions_db=True,
                risk_decisions_csv=str(missing),
            )

            # Real pipeline steps must execute (recorded via the fake runner).
            runner = fake_runner_factory({})

            # The risk decisions importer must NEVER be called when the CSV is
            # missing post-pipeline.
            def boom_rd(*a, **k):  # pragma: no cover - must never run
                raise AssertionError("importer called despite missing CSV")

            orig_s = rop.import_run_summary_into_db
            orig_r = rop.import_risk_decisions_into_db
            rop.import_run_summary_into_db = lambda p, s: rop.DB_WRITE_SUCCESS
            rop.import_risk_decisions_into_db = boom_rd
            err = io.StringIO()
            try:
                with redirect_stdout(io.StringIO()), redirect_stderr(err):
                    rc = rop.execute_run(
                        args, steps=_ok_steps(), step_runner=runner, now_fn=FakeClock()
                    )
            finally:
                rop.import_run_summary_into_db = orig_s
                rop.import_risk_decisions_into_db = orig_r

            # Pipeline steps ran FIRST (failure is post-pipeline, not early).
            self.assertEqual(runner.calls, [name for name, _ in _ok_steps()])
            # Runner exits non-zero.
            self.assertNotEqual(rc, 0)
            self.assertIn(rop.RISK_DEC_MISSING_MSG, err.getvalue())
            self.assertIn(str(missing), err.getvalue())
            # Summary artifacts were written and record the failed import.
            summary = _read_summary_json(args.summary_dir)
            self.assertEqual(
                summary["risk_decisions_db_import_status"],
                rop.RISK_DEC_IMPORT_FAILED,
            )
            rd = summary["risk_decisions_db_import"]
            self.assertTrue(rd["attempted"])
            self.assertFalse(rd["success"])
            self.assertIsNone(rd["exit_code"])
            self.assertEqual(rd["message"], f"{rop.RISK_DEC_MISSING_MSG}: {missing}")
            # The runner never created the CSV.
            self.assertFalse(missing.exists())
            # Runtime dirs WERE created because the pipeline ran.
            self.assertTrue(Path(args.log_dir).exists())
            self.assertTrue(Path(args.summary_dir).exists())


class ImportRiskDecisionsStatusTests(unittest.TestCase):
    """Status plumbing via fake importers — runs without duckdb installed."""

    def _existing_db_path(self, tmp):
        db_path = Path(tmp) / "runtime" / "dlmm.duckdb"
        db_path.parent.mkdir(parents=True, exist_ok=True)
        db_path.write_text("placeholder")
        return db_path

    def test_default_run_does_not_import_risk_decisions(self):
        with tempfile.TemporaryDirectory() as tmp:
            args = make_args(tmp)  # no write_db, no import_risk_decisions_db

            def boom(*a, **k):  # pragma: no cover - must never run
                raise AssertionError("risk decisions import must not run by default")

            original = rop.import_risk_decisions_into_db
            rop.import_risk_decisions_into_db = boom
            try:
                rc = rop.execute_run(
                    args, steps=_ok_steps(), step_runner=fake_runner_factory({}),
                    now_fn=FakeClock(),
                )
            finally:
                rop.import_risk_decisions_into_db = original

            self.assertEqual(rc, 0)
            summary = _read_summary_json(args.summary_dir)
            self.assertEqual(
                summary["risk_decisions_db_import_status"],
                rop.RISK_DEC_IMPORT_NOT_REQUESTED,
            )
            self.assertIsNone(summary["risk_decisions_csv"])
            self.assertFalse(summary["risk_decisions_db_import"]["enabled"])
            self.assertFalse(summary["risk_decisions_db_import"]["attempted"])

    def test_risk_decisions_imported_after_summary_and_observations(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = self._existing_db_path(tmp)
            obs = _write_observations_jsonl(tmp)
            csv_path = _write_risk_decisions_csv(tmp)
            args = make_args(
                tmp, write_db=str(db_path),
                import_observations_db=True, observations_jsonl=str(obs),
                import_risk_decisions_db=True, risk_decisions_csv=str(csv_path),
            )
            order = []

            def fake_summary_import(p, s):
                order.append("summary")
                return rop.DB_WRITE_SUCCESS

            def fake_obs_import(p, o, irf):
                order.append("observations")
                return rop.OBS_IMPORT_SUCCESS

            rd_calls = []

            def fake_rd_import(p, c):
                order.append("risk_decisions")
                rd_calls.append((str(p), str(c)))
                return rop.RISK_DEC_IMPORT_SUCCESS, 0

            orig_s = rop.import_run_summary_into_db
            orig_o = rop.import_observations_into_db
            orig_r = rop.import_risk_decisions_into_db
            rop.import_run_summary_into_db = fake_summary_import
            rop.import_observations_into_db = fake_obs_import
            rop.import_risk_decisions_into_db = fake_rd_import
            try:
                rc = rop.execute_run(
                    args, steps=_ok_steps(), step_runner=fake_runner_factory({}),
                    now_fn=FakeClock(),
                )
            finally:
                rop.import_run_summary_into_db = orig_s
                rop.import_observations_into_db = orig_o
                rop.import_risk_decisions_into_db = orig_r

            self.assertEqual(rc, 0)
            # Risk decisions import runs AFTER summary AND observations.
            self.assertEqual(order, ["summary", "observations", "risk_decisions"])
            self.assertEqual(len(rd_calls), 1)
            self.assertEqual(rd_calls[0][0], str(db_path))
            self.assertEqual(rd_calls[0][1], str(csv_path))
            summary = _read_summary_json(args.summary_dir)
            self.assertEqual(
                summary["risk_decisions_db_import_status"], rop.RISK_DEC_IMPORT_SUCCESS
            )
            self.assertEqual(summary["risk_decisions_csv"], str(csv_path))
            rd = summary["risk_decisions_db_import"]
            self.assertTrue(rd["enabled"])
            self.assertTrue(rd["attempted"])
            self.assertTrue(rd["success"])
            self.assertEqual(rd["exit_code"], 0)
            self.assertIsNone(rd["message"])

    def test_import_failure_makes_runner_exit_nonzero(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = self._existing_db_path(tmp)
            csv_path = _write_risk_decisions_csv(tmp)
            args = make_args(
                tmp, write_db=str(db_path),
                import_risk_decisions_db=True, risk_decisions_csv=str(csv_path),
            )

            orig_s = rop.import_run_summary_into_db
            orig_r = rop.import_risk_decisions_into_db
            rop.import_run_summary_into_db = lambda p, s: rop.DB_WRITE_SUCCESS
            rop.import_risk_decisions_into_db = (
                lambda p, c: (rop.RISK_DEC_IMPORT_FAILED, 1)
            )
            try:
                rc = rop.execute_run(
                    args, steps=_ok_steps(), step_runner=fake_runner_factory({}),
                    now_fn=FakeClock(),
                )
            finally:
                rop.import_run_summary_into_db = orig_s
                rop.import_risk_decisions_into_db = orig_r

            # Pipeline + summary import succeeded, but risk decisions import failed.
            self.assertNotEqual(rc, 0)
            summary = _read_summary_json(args.summary_dir)
            self.assertEqual(summary["status"], "SUCCESS")
            self.assertEqual(summary["db_write_status"], rop.DB_WRITE_SUCCESS)
            self.assertEqual(
                summary["risk_decisions_db_import_status"], rop.RISK_DEC_IMPORT_FAILED
            )
            rd = summary["risk_decisions_db_import"]
            self.assertTrue(rd["attempted"])
            self.assertFalse(rd["success"])
            self.assertEqual(rd["exit_code"], 1)
            self.assertIsNotNone(rd["message"])

    def test_summary_json_and_md_include_risk_decisions_fields(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = self._existing_db_path(tmp)
            csv_path = _write_risk_decisions_csv(tmp)
            args = make_args(
                tmp, write_db=str(db_path),
                import_risk_decisions_db=True, risk_decisions_csv=str(csv_path),
            )
            orig_s = rop.import_run_summary_into_db
            orig_r = rop.import_risk_decisions_into_db
            rop.import_run_summary_into_db = lambda p, s: rop.DB_WRITE_SUCCESS
            rop.import_risk_decisions_into_db = (
                lambda p, c: (rop.RISK_DEC_IMPORT_SUCCESS, 0)
            )
            try:
                rop.execute_run(
                    args, steps=_ok_steps(), step_runner=fake_runner_factory({}),
                    now_fn=FakeClock(),
                )
            finally:
                rop.import_run_summary_into_db = orig_s
                rop.import_risk_decisions_into_db = orig_r

            summary = _read_summary_json(args.summary_dir)
            for key in (
                "risk_decisions_db_import_status",
                "risk_decisions_csv",
                "risk_decisions_db_import",
            ):
                self.assertIn(key, summary)
            for key in ("enabled", "attempted", "success", "exit_code", "message"):
                self.assertIn(key, summary["risk_decisions_db_import"])

            md = _read_summary_md(args.summary_dir)
            self.assertIn("Risk decisions DB import status", md)
            self.assertIn("Risk decisions CSV", md)


@unittest.skipUnless(HAS_DUCKDB, "duckdb not installed")
class ImportRiskDecisionsRealDuckDbTests(unittest.TestCase):
    """End-to-end against a real initialized DuckDB via the real importer."""

    def _init_db(self, tmp):
        db_path = Path(tmp) / "runtime" / "dlmm.duckdb"
        idb.init_db(str(db_path))
        return db_path

    def _counts(self, db_path):
        conn = duckdb.connect(str(db_path))
        try:
            return {
                "runs": conn.execute("SELECT COUNT(*) FROM pipeline_runs").fetchone()[0],
                "steps": conn.execute(
                    "SELECT COUNT(*) FROM pipeline_steps"
                ).fetchone()[0],
                "obs": conn.execute(
                    "SELECT COUNT(*) FROM strategy_observations"
                ).fetchone()[0],
                "flags": conn.execute("SELECT COUNT(*) FROM risk_flags").fetchone()[0],
                "decisions": conn.execute(
                    "SELECT COUNT(*) FROM risk_decisions"
                ).fetchone()[0],
                "fpe": conn.execute(
                    "SELECT COUNT(*) FROM future_position_events"
                ).fetchone()[0],
            }
        finally:
            conn.close()

    def test_successful_run_imports_risk_decisions_with_upsert(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = self._init_db(tmp)
            csv_path = _write_risk_decisions_csv(tmp)
            args = make_args(
                tmp, write_db=str(db_path),
                import_risk_decisions_db=True, risk_decisions_csv=str(csv_path),
            )
            with redirect_stdout(io.StringIO()):
                rc = rop.execute_run(
                    args, steps=_ok_steps(), step_runner=fake_runner_factory({}),
                    now_fn=FakeClock(),
                )
            self.assertEqual(rc, 0)
            counts = self._counts(db_path)
            self.assertEqual(counts["runs"], 1)
            self.assertEqual(counts["decisions"], 1)
            # Hard boundary: no execution-layer rows ever written.
            self.assertEqual(counts["fpe"], 0)
            # No observation/flag rows when those imports are not requested.
            self.assertEqual(counts["obs"], 0)
            self.assertEqual(counts["flags"], 0)
            summary = _read_summary_json(args.summary_dir)
            self.assertEqual(
                summary["risk_decisions_db_import_status"], rop.RISK_DEC_IMPORT_SUCCESS
            )

    def test_upsert_reruns_do_not_duplicate_or_fail(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = self._init_db(tmp)
            csv_path = _write_risk_decisions_csv(tmp)
            args = make_args(
                tmp, write_db=str(db_path),
                import_risk_decisions_db=True, risk_decisions_csv=str(csv_path),
            )
            for _ in range(2):
                with redirect_stdout(io.StringIO()):
                    rc = rop.execute_run(
                        args, steps=_ok_steps(),
                        step_runner=fake_runner_factory({}), now_fn=FakeClock(),
                    )
                self.assertEqual(rc, 0)
            # Deterministic id + upsert => repeated runs do not duplicate or fail.
            self.assertEqual(self._counts(db_path)["decisions"], 1)

    def test_observation_import_still_works_alongside_risk_decisions(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = self._init_db(tmp)
            obs = _write_observations_jsonl(tmp)
            csv_path = _write_risk_decisions_csv(tmp)
            args = make_args(
                tmp, write_db=str(db_path),
                import_observations_db=True, observations_jsonl=str(obs),
                import_risk_flags=True,
                import_risk_decisions_db=True, risk_decisions_csv=str(csv_path),
            )
            with redirect_stdout(io.StringIO()):
                rc = rop.execute_run(
                    args, steps=_ok_steps(), step_runner=fake_runner_factory({}),
                    now_fn=FakeClock(),
                )
            self.assertEqual(rc, 0)
            counts = self._counts(db_path)
            # Observation + risk flag import behavior unchanged.
            self.assertEqual(counts["obs"], 1)
            self.assertGreaterEqual(counts["flags"], 1)
            # Risk decisions imported too.
            self.assertEqual(counts["decisions"], 1)
            # Hard boundary holds: future_position_events never written.
            self.assertEqual(counts["fpe"], 0)

    def test_no_future_position_events_write_introduced(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = self._init_db(tmp)
            csv_path = _write_risk_decisions_csv(tmp)
            args = make_args(
                tmp, write_db=str(db_path),
                import_risk_decisions_db=True, risk_decisions_csv=str(csv_path),
            )
            with redirect_stdout(io.StringIO()):
                rop.execute_run(
                    args, steps=_ok_steps(), step_runner=fake_runner_factory({}),
                    now_fn=FakeClock(),
                )
            self.assertEqual(self._counts(db_path)["fpe"], 0)


# --------------------------------------------------------------------------- #
# Optional Manual Council Review Matrix support
# (--build-manual-council-review-matrix)
# --------------------------------------------------------------------------- #

class ManualCouncilReviewMatrixRequiresWriteDbTests(unittest.TestCase):
    """--build-manual-council-review-matrix requires --write-db before work."""

    def test_requires_write_db_fails_before_pipeline(self):
        called = {"execute": False}

        def boom_execute(*a, **k):  # pragma: no cover - must never run
            called["execute"] = True
            raise AssertionError("pipeline ran without --write-db")

        original = rop.execute_run
        rop.execute_run = boom_execute
        err = io.StringIO()
        try:
            with redirect_stdout(io.StringIO()), redirect_stderr(err):
                rc = rop.main(["--build-manual-council-review-matrix"])
        finally:
            rop.execute_run = original

        self.assertEqual(rc, 2)
        self.assertFalse(called["execute"])
        self.assertIn(
            "--build-manual-council-review-matrix requires --write-db",
            err.getvalue(),
        )

    def test_requires_write_db_also_blocks_dry_run(self):
        err = io.StringIO()
        with redirect_stdout(io.StringIO()), redirect_stderr(err):
            rc = rop.main(["--dry-run", "--build-manual-council-review-matrix"])
        self.assertEqual(rc, 2)
        self.assertIn(
            "--build-manual-council-review-matrix requires --write-db",
            err.getvalue(),
        )


class ManualCouncilReviewMatrixDryRunTests(unittest.TestCase):
    def test_dry_run_touches_no_db_dirs_or_matrix_outputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "runtime" / "dlmm.duckdb"  # does NOT exist
            out_md = Path(tmp) / "reports" / "matrix.md"
            out_csv = Path(tmp) / "reports" / "matrix.csv"

            buf = io.StringIO()
            with redirect_stdout(buf):
                rc = rop.main(
                    [
                        "--dry-run",
                        "--write-db", str(db_path),
                        "--build-manual-council-review-matrix",
                        "--manual-council-review-matrix-md", str(out_md),
                        "--manual-council-review-matrix-csv", str(out_csv),
                        "--log-dir", str(Path(tmp) / "logs"),
                        "--lock-dir", str(Path(tmp) / "locks"),
                        "--summary-dir", str(Path(tmp) / "summaries"),
                    ]
                )
            self.assertEqual(rc, 0)
            self.assertFalse((Path(tmp) / "logs").exists())
            self.assertFalse((Path(tmp) / "locks").exists())
            self.assertFalse((Path(tmp) / "summaries").exists())
            self.assertFalse(db_path.exists())
            self.assertFalse(out_md.exists())
            self.assertFalse(out_csv.exists())
            out = buf.getvalue()
            self.assertIn("Manual Council Review Matrix build is PLANNED", out)
            self.assertIn("NOT executed", out)
            self.assertIn(str(out_md), out)
            self.assertIn(str(out_csv), out)


class ManualCouncilReviewMatrixStatusTests(unittest.TestCase):
    """Status plumbing via fake builder — runs without duckdb installed."""

    def _existing_db_path(self, tmp):
        db_path = Path(tmp) / "runtime" / "dlmm.duckdb"
        db_path.parent.mkdir(parents=True, exist_ok=True)
        db_path.write_text("placeholder")
        return db_path

    def test_default_run_does_not_build_matrix(self):
        with tempfile.TemporaryDirectory() as tmp:
            args = make_args(tmp)

            def boom(*a, **k):  # pragma: no cover - must never run
                raise AssertionError("matrix builder must not run by default")

            original = rop.build_manual_council_review_matrix
            rop.build_manual_council_review_matrix = boom
            try:
                rc = rop.execute_run(
                    args, steps=_ok_steps(), step_runner=fake_runner_factory({}),
                    now_fn=FakeClock(),
                )
            finally:
                rop.build_manual_council_review_matrix = original

            self.assertEqual(rc, 0)
            summary = _read_summary_json(args.summary_dir)
            matrix = summary["manual_council_review_matrix"]
            self.assertFalse(matrix["enabled"])
            self.assertFalse(matrix["attempted"])
            self.assertEqual(matrix["status"], rop.MATRIX_BUILD_NOT_REQUESTED)
            self.assertIsNone(matrix["out_md"])
            self.assertIsNone(matrix["out_csv"])

    def test_matrix_build_runs_after_existing_optional_imports(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = self._existing_db_path(tmp)
            obs = _write_observations_jsonl(tmp)
            csv_path = _write_risk_decisions_csv(tmp)
            out_md = Path(tmp) / "reports" / "matrix.md"
            out_csv = Path(tmp) / "reports" / "matrix.csv"
            args = make_args(
                tmp,
                write_db=str(db_path),
                import_observations_db=True,
                observations_jsonl=str(obs),
                import_risk_decisions_db=True,
                risk_decisions_csv=str(csv_path),
                build_manual_council_review_matrix=True,
                manual_council_review_matrix_md=str(out_md),
                manual_council_review_matrix_csv=str(out_csv),
            )
            order = []

            def fake_summary_import(p, s):
                order.append("summary")
                return rop.DB_WRITE_SUCCESS

            def fake_obs_import(p, o, irf):
                order.append("observations")
                return rop.OBS_IMPORT_SUCCESS

            def fake_rd_import(p, c):
                order.append("risk_decisions")
                return rop.RISK_DEC_IMPORT_SUCCESS, 0

            matrix_calls = []

            def fake_matrix_build(db, md, csv):
                order.append("matrix")
                matrix_calls.append((str(db), str(md), str(csv)))
                return rop.MATRIX_BUILD_SUCCESS, 0

            orig_s = rop.import_run_summary_into_db
            orig_o = rop.import_observations_into_db
            orig_r = rop.import_risk_decisions_into_db
            orig_m = rop.build_manual_council_review_matrix
            rop.import_run_summary_into_db = fake_summary_import
            rop.import_observations_into_db = fake_obs_import
            rop.import_risk_decisions_into_db = fake_rd_import
            rop.build_manual_council_review_matrix = fake_matrix_build
            try:
                rc = rop.execute_run(
                    args, steps=_ok_steps(), step_runner=fake_runner_factory({}),
                    now_fn=FakeClock(),
                )
            finally:
                rop.import_run_summary_into_db = orig_s
                rop.import_observations_into_db = orig_o
                rop.import_risk_decisions_into_db = orig_r
                rop.build_manual_council_review_matrix = orig_m

            self.assertEqual(rc, 0)
            self.assertEqual(
                order, ["summary", "observations", "risk_decisions", "matrix"]
            )
            self.assertEqual(matrix_calls, [(str(db_path), str(out_md), str(out_csv))])
            summary = _read_summary_json(args.summary_dir)
            matrix = summary["manual_council_review_matrix"]
            self.assertTrue(matrix["enabled"])
            self.assertTrue(matrix["attempted"])
            self.assertTrue(matrix["success"])
            self.assertEqual(matrix["status"], rop.MATRIX_BUILD_SUCCESS)
            self.assertEqual(matrix["exit_code"], 0)
            self.assertIsNone(matrix["message"])

    def test_matrix_build_failure_makes_runner_exit_nonzero(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = self._existing_db_path(tmp)
            args = make_args(
                tmp,
                write_db=str(db_path),
                build_manual_council_review_matrix=True,
            )

            orig_s = rop.import_run_summary_into_db
            orig_m = rop.build_manual_council_review_matrix
            rop.import_run_summary_into_db = lambda p, s: rop.DB_WRITE_SUCCESS
            rop.build_manual_council_review_matrix = (
                lambda db, md, csv: (rop.MATRIX_BUILD_FAILED, 4)
            )
            try:
                rc = rop.execute_run(
                    args, steps=_ok_steps(), step_runner=fake_runner_factory({}),
                    now_fn=FakeClock(),
                )
            finally:
                rop.import_run_summary_into_db = orig_s
                rop.build_manual_council_review_matrix = orig_m

            self.assertNotEqual(rc, 0)
            summary = _read_summary_json(args.summary_dir)
            self.assertEqual(summary["status"], "SUCCESS")
            self.assertEqual(summary["db_write_status"], rop.DB_WRITE_SUCCESS)
            matrix = summary["manual_council_review_matrix"]
            self.assertTrue(matrix["attempted"])
            self.assertFalse(matrix["success"])
            self.assertEqual(matrix["status"], rop.MATRIX_BUILD_FAILED)
            self.assertEqual(matrix["exit_code"], 4)
            self.assertIsNotNone(matrix["message"])

    def test_summary_json_and_md_include_matrix_fields(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = self._existing_db_path(tmp)
            out_md = Path(tmp) / "reports" / "matrix.md"
            out_csv = Path(tmp) / "reports" / "matrix.csv"
            args = make_args(
                tmp,
                write_db=str(db_path),
                build_manual_council_review_matrix=True,
                manual_council_review_matrix_md=str(out_md),
                manual_council_review_matrix_csv=str(out_csv),
            )
            orig_s = rop.import_run_summary_into_db
            orig_m = rop.build_manual_council_review_matrix
            rop.import_run_summary_into_db = lambda p, s: rop.DB_WRITE_SUCCESS
            rop.build_manual_council_review_matrix = (
                lambda db, md, csv: (rop.MATRIX_BUILD_SUCCESS, 0)
            )
            try:
                rop.execute_run(
                    args, steps=_ok_steps(), step_runner=fake_runner_factory({}),
                    now_fn=FakeClock(),
                )
            finally:
                rop.import_run_summary_into_db = orig_s
                rop.build_manual_council_review_matrix = orig_m

            summary = _read_summary_json(args.summary_dir)
            self.assertIn("manual_council_review_matrix", summary)
            matrix = summary["manual_council_review_matrix"]
            for key in (
                "enabled", "attempted", "success", "status", "db_path",
                "out_md", "out_csv", "exit_code", "message",
            ):
                self.assertIn(key, matrix)
            self.assertEqual(matrix["out_md"], str(out_md))
            self.assertEqual(matrix["out_csv"], str(out_csv))

            md = _read_summary_md(args.summary_dir)
            self.assertIn("Manual Council Review Matrix status", md)
            self.assertIn("Manual Council Review Matrix Markdown", md)
            self.assertIn("Manual Council Review Matrix CSV", md)


if __name__ == "__main__":
    unittest.main()
