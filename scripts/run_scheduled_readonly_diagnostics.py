#!/usr/bin/env python3
"""
Scheduled Read-only Diagnostics Runner v0.1

Purpose:
- Safe VPS automation entrypoint for cron/systemd timers.
- Runs the existing read-only runtime pipeline, then local read-only diagnostic
  report builders, with a separate overlap-prevention lock and local log file.
- Checks future_position_events before and after orchestration.

This is a scheduler-friendly wrapper only. It is not a paper engine, not a live
bot, and not a signal generator.

Hard safety boundary:
- No wallet
- No private key
- No seed phrase
- No signing
- No swap
- No LP add/remove
- No rebalance
- No live execution
- No signal generation
- No paper position creation
- No future_position_events writes
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, List, Optional, Sequence, Tuple


SAFETY_PHASE = "READ_ONLY / RESEARCH_ONLY / SCREENING_ONLY / PAPER_ONLY"

SAFETY_BANNER = "\n".join(
    [
        SAFETY_PHASE,
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
    ]
)

LOCK_FILENAME = "scheduled_readonly_runner.lock"

DEFAULT_DB_PATH = "runtime/dlmm.duckdb"
DEFAULT_LOG_DIR = "runtime/logs"
DEFAULT_LOCK_DIR = "runtime/locks"

FPE_TABLE = "future_position_events"
DB_MISSING_MSG = "DuckDB database not found. Run scripts/init_runtime_db.py first."
DUCKDB_MISSING_MSG = (
    "duckdb package is required. Install with: python3 -m pip install duckdb"
)
FPE_MISSING_MSG = "future_position_events table not found in runtime database"
FPE_NONZERO_MSG = (
    "HARD SAFETY VIOLATION: future_position_events count is non-zero"
)


@dataclass(frozen=True)
class PlannedCommand:
    name: str
    argv: Tuple[str, ...]


@dataclass
class CommandResult:
    name: str
    argv: Tuple[str, ...]
    exit_code: int
    stdout: str
    stderr: str


class LockHeldError(RuntimeError):
    """Raised when another scheduled diagnostics run appears active."""


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def make_run_id(now: datetime) -> str:
    return now.strftime("%Y%m%dT%H%M%S_%f")


def require_duckdb():
    try:
        import duckdb  # noqa: PLC0415
    except ImportError as exc:
        raise RuntimeError(DUCKDB_MISSING_MSG) from exc
    return duckdb


def pid_is_active(pid) -> bool:
    try:
        pid_int = int(pid)
    except (TypeError, ValueError):
        return False
    if pid_int <= 0:
        return False
    try:
        os.kill(pid_int, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def lock_file_path(lock_dir) -> Path:
    return Path(lock_dir) / LOCK_FILENAME


def read_lock(lock_path) -> dict:
    path = Path(lock_path)
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}


def write_lock(lock_path, pid: int, started_at: str, command: str, cwd: str) -> None:
    path = Path(lock_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "pid": pid,
        "started_at": started_at,
        "command": command,
        "cwd": cwd,
    }
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    fd = os.open(str(path), flags, 0o644)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, indent=2)
            fh.write("\n")
    except Exception:
        try:
            path.unlink()
        except OSError:
            pass
        raise


def acquire_lock(lock_path, pid: int, started_at: str, command: str, cwd: str) -> bool:
    """Acquire lock_path.

    Returns True when a stale lock was replaced. Raises LockHeldError for a
    live lock. Uses O_EXCL so two new runners cannot both acquire the lock.
    """
    path = Path(lock_path)
    try:
        write_lock(path, pid, started_at, command, cwd)
        return False
    except FileExistsError:
        existing = read_lock(path)
        existing_pid = existing.get("pid")
        if pid_is_active(existing_pid):
            raise LockHeldError(
                "Scheduled read-only diagnostics runner already active "
                f"(pid={existing_pid}, lock={path}). Refusing overlap."
            )
        try:
            path.unlink()
        except FileNotFoundError:
            pass
        write_lock(path, pid, started_at, command, cwd)
        return True


def release_lock(lock_path) -> None:
    try:
        Path(lock_path).unlink()
    except FileNotFoundError:
        pass


def check_future_position_events_count(db_path: str) -> int:
    """Return future_position_events count, failing if the DB boundary is unsafe."""
    path = Path(db_path)
    if not path.is_file():
        raise RuntimeError(DB_MISSING_MSG)
    duckdb = require_duckdb()
    conn = duckdb.connect(str(path), read_only=True)
    try:
        present = {
            row[0]
            for row in conn.execute(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema = 'main'"
            ).fetchall()
        }
        if FPE_TABLE not in present:
            raise RuntimeError(FPE_MISSING_MSG)
        count = conn.execute(f"SELECT COUNT(*) FROM {FPE_TABLE}").fetchone()[0]
    finally:
        conn.close()
    if count != 0:
        raise RuntimeError(f"{FPE_NONZERO_MSG}: {count} (expected 0)")
    return int(count)


def build_commands(args: argparse.Namespace) -> List[PlannedCommand]:
    py = sys.executable or "python3"
    commands = []
    if not args.skip_pipeline:
        pipeline = [
            py,
            "scripts/run_readonly_pipeline.py",
            "--write-db",
            args.db_path,
            "--import-observations-db",
            "--import-risk-flags",
            "--import-risk-decisions-db",
        ]
        if args.continue_on_ohlcv_error:
            pipeline.append("--continue-on-ohlcv-error")
        commands.append(PlannedCommand("readonly_pipeline", tuple(pipeline)))

    if not args.skip_reports:
        commands.extend(
            [
                PlannedCommand(
                    "runtime_risk_dashboard",
                    (
                        py,
                        "scripts/build_runtime_risk_dashboard.py",
                        "--db-path",
                        args.db_path,
                    ),
                ),
                PlannedCommand(
                    "argus_proposal",
                    (
                        py,
                        "scripts/build_argus_proposal.py",
                        "--db-path",
                        args.db_path,
                    ),
                ),
                PlannedCommand(
                    "fee_pool_diagnostics",
                    (
                        py,
                        "scripts/build_fee_pool_diagnostics.py",
                        "--db-path",
                        args.db_path,
                    ),
                ),
                PlannedCommand(
                    "pair_stability_diagnostics",
                    (
                        py,
                        "scripts/build_pair_stability_diagnostics.py",
                        "--db-path",
                        args.db_path,
                    ),
                ),
                PlannedCommand(
                    "candidate_deep_review",
                    (
                        py,
                        "scripts/build_candidate_deep_review.py",
                        "--db-path",
                        args.db_path,
                    ),
                ),
                PlannedCommand(
                    "candidate_evidence_pack",
                    (
                        py,
                        "scripts/build_candidate_evidence_pack.py",
                        "--db-path",
                        args.db_path,
                    ),
                ),
                PlannedCommand(
                    "manual_council_review_matrix",
                    (
                        py,
                        "scripts/build_manual_council_review_matrix.py",
                        "--db-path",
                        args.db_path,
                    ),
                ),
            ]
        )
    return commands


def run_command(command: PlannedCommand) -> CommandResult:
    completed = subprocess.run(
        list(command.argv),
        check=False,
        capture_output=True,
        text=True,
    )
    return CommandResult(
        name=command.name,
        argv=command.argv,
        exit_code=completed.returncode,
        stdout=completed.stdout,
        stderr=completed.stderr,
    )


def _write_line(log_fh, text: str = "") -> None:
    log_fh.write(text + "\n")
    log_fh.flush()


def print_dry_run(commands: Sequence[PlannedCommand], args: argparse.Namespace) -> None:
    print("DRY RUN - Scheduled Read-only Diagnostics Runner v0.1")
    print()
    print(SAFETY_BANNER)
    print()
    print(f"db-path  : {args.db_path}")
    print(f"log-dir  : {args.log_dir}")
    print(f"lock-dir : {args.lock_dir}")
    print()
    print("Planned commands (sequential, no shell):")
    for i, command in enumerate(commands, start=1):
        print(f"  {i}. {command.name}: {' '.join(command.argv)}")
    print()
    print(
        "Dry run: no runtime directories created, no lock file created, "
        "no child commands executed, no reports written, no database written."
    )


def execute_run(
    args: argparse.Namespace,
    command_runner: Callable[[PlannedCommand], CommandResult] = run_command,
    fpe_checker: Callable[[str], int] = check_future_position_events_count,
    now_fn: Callable[[], datetime] = utc_now,
) -> int:
    commands = build_commands(args)
    if args.dry_run:
        print_dry_run(commands, args)
        return 0

    log_dir = Path(args.log_dir)
    lock_dir = Path(args.lock_dir)
    log_dir.mkdir(parents=True, exist_ok=True)
    lock_dir.mkdir(parents=True, exist_ok=True)

    started_at = now_fn()
    run_id = make_run_id(started_at)
    lock_path = lock_file_path(lock_dir)
    log_path = log_dir / f"scheduled_readonly_runner_{run_id}.log"

    try:
        stale_lock_replaced = acquire_lock(
            lock_path,
            pid=os.getpid(),
            started_at=started_at.isoformat(),
            command=" ".join(sys.argv),
            cwd=os.getcwd(),
        )
    except LockHeldError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    try:
        with log_path.open("w", encoding="utf-8") as log_fh:
            _write_line(log_fh, "Scheduled Read-only Diagnostics Runner v0.1")
            _write_line(log_fh, f"RUN_ID: {run_id}")
            _write_line(log_fh, f"STARTED_AT: {started_at.isoformat()}")
            _write_line(log_fh, "SAFETY BOUNDARY:")
            _write_line(log_fh, SAFETY_BANNER)
            if stale_lock_replaced:
                _write_line(log_fh, "NOTE: stale lock replaced before run.")

            try:
                before_count = fpe_checker(args.db_path)
            except RuntimeError as exc:
                _write_line(log_fh, f"PRECHECK FAILED: {exc}")
                print(f"ERROR: {exc}", file=sys.stderr)
                return 1
            _write_line(
                log_fh,
                f"PRECHECK: future_position_events count = {before_count}",
            )

            for command in commands:
                _write_line(log_fh)
                _write_line(log_fh, f"COMMAND START: {command.name}")
                _write_line(log_fh, "ARGV: " + " ".join(command.argv))
                result = command_runner(command)
                if result.stdout:
                    _write_line(log_fh, "STDOUT:")
                    log_fh.write(result.stdout)
                    if not result.stdout.endswith("\n"):
                        log_fh.write("\n")
                if result.stderr:
                    _write_line(log_fh, "STDERR:")
                    log_fh.write(result.stderr)
                    if not result.stderr.endswith("\n"):
                        log_fh.write("\n")
                _write_line(
                    log_fh,
                    f"COMMAND END: {command.name} exit_code={result.exit_code}",
                )
                if result.exit_code != 0:
                    print(
                        f"ERROR: {command.name} failed with exit code "
                        f"{result.exit_code}. Log: {log_path}",
                        file=sys.stderr,
                    )
                    return 1

            try:
                after_count = fpe_checker(args.db_path)
            except RuntimeError as exc:
                _write_line(log_fh, f"POSTCHECK FAILED: {exc}")
                print(f"ERROR: {exc}", file=sys.stderr)
                return 1
            _write_line(
                log_fh,
                f"POSTCHECK: future_position_events count = {after_count}",
            )
            _write_line(log_fh, "STATUS: SUCCESS")

        print(f"Scheduled read-only diagnostics finished: SUCCESS")
        print(f"Log: {log_path}")
        return 0
    finally:
        release_lock(lock_path)


def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Scheduled Read-only Diagnostics Runner v0.1 for VPS automation. "
            "Read-only diagnostics only; no wallet, signing, swap, LP, rebalance, "
            "live execution, signal generation, paper positions, or "
            "future_position_events writes."
        )
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print planned commands and exit without creating dirs, locks, logs, or reports.",
    )
    parser.add_argument(
        "--db-path",
        default=DEFAULT_DB_PATH,
        help=f"Existing runtime DuckDB path (default: {DEFAULT_DB_PATH}).",
    )
    parser.add_argument(
        "--log-dir",
        default=DEFAULT_LOG_DIR,
        help=f"Directory for local scheduled-run logs (default: {DEFAULT_LOG_DIR}).",
    )
    parser.add_argument(
        "--lock-dir",
        default=DEFAULT_LOCK_DIR,
        help=f"Directory for the scheduled-run lock file (default: {DEFAULT_LOCK_DIR}).",
    )
    parser.add_argument(
        "--continue-on-ohlcv-error",
        action="store_true",
        help="Pass through to scripts/run_readonly_pipeline.py.",
    )
    parser.add_argument(
        "--skip-pipeline",
        action="store_true",
        help="Run only the report diagnostics and future_position_events checks.",
    )
    parser.add_argument(
        "--skip-reports",
        action="store_true",
        help="Run only the read-only pipeline and future_position_events checks.",
    )
    return parser.parse_args(argv)


def main(argv: Optional[List[str]] = None) -> int:
    args = parse_args(argv)
    return execute_run(args)


if __name__ == "__main__":
    raise SystemExit(main())
