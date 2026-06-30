#!/usr/bin/env python3
"""
Read-only Runtime Orchestrator v0.1

Purpose:
- Single safe VPS entrypoint that runs the existing read-only DLMM pipeline in
  sequence, with logging, run summaries, and an overlap-preventing lock file.

This component is a Runtime Orchestrator ONLY. It calls the already-working
read-only scripts; it does not modify them and it adds no decision logic.

It IS:
- read-only
- non-custodial
- non-executing

It is NOT:
- Risk Engine
- Signal Engine
- Position Manager
- Telegram Control Room
- Execution Engine
- a scheduler / cron / systemd service

Hard safety boundary (never crossed by this runner):
- No wallet
- No private key
- No signing
- No swap
- No LP add/remove
- No rebalance
- No live execution
- No LIVE_ELIGIBLE_*
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, List, Optional, Tuple


# --------------------------------------------------------------------------- #
# Constants
# --------------------------------------------------------------------------- #

SAFETY_PHASE = "READ_ONLY / RESEARCH_ONLY / SCREENING_ONLY / PAPER_ONLY"

SAFETY_BANNER = (
    "READ_ONLY / RESEARCH_ONLY / SCREENING_ONLY / PAPER_ONLY\n"
    "No wallet\n"
    "No private key\n"
    "No signing\n"
    "No swap\n"
    "No LP\n"
    "No rebalance\n"
    "No live execution\n"
    "No LIVE_ELIGIBLE_*"
)

OHLCV_STEP_NAME = "fetch_ohlcv_top_pairs"
RISK_POLICY_STEP_NAME = "apply_risk_policy"
VALIDATE_STEP_NAME = "validate_watchlist"

LOCK_FILENAME = "pipeline.lock"

DEFAULT_LOG_DIR = "runtime/logs"
DEFAULT_LOCK_DIR = "runtime/locks"
DEFAULT_SUMMARY_DIR = "runtime/run_summaries"

# Optional DuckDB write support (only active when --write-db PATH is provided).
# The runner NEVER creates or initializes the database; it only imports its own
# already-written summary JSON into an EXISTING DB via the run-summary importer.
DB_WRITE_NOT_REQUESTED = "NOT_REQUESTED"
DB_WRITE_PENDING = "PENDING"
DB_WRITE_SUCCESS = "SUCCESS"
DB_WRITE_FAILED = "FAILED"

# Exact message required when --write-db points at a non-existent database.
DB_MISSING_MSG = "DuckDB database not found. Run scripts/init_runtime_db.py first."

# Optional strategy-observation import support (only active when
# --import-observations-db is provided, which itself requires --write-db). The
# runner NEVER creates the DB or the observations JSONL; it only imports an
# already-written observations file into an EXISTING DB via the strategy
# observations importer. DB writes stay limited to strategy_observations and
# (optionally) risk_flags; future_position_events is never written.
OBS_IMPORT_NOT_REQUESTED = "NOT_REQUESTED"
OBS_IMPORT_PENDING = "PENDING"
OBS_IMPORT_SUCCESS = "SUCCESS"
OBS_IMPORT_FAILED = "FAILED"

DEFAULT_OBSERVATIONS_JSONL = "data/observations/strategy_observations.jsonl"

# Exact message required when --import-observations-db is requested without
# --write-db (the importer needs an existing DB to write into).
OBS_REQUIRES_DB_MSG = "--import-observations-db requires --write-db"

# Message when the observations JSONL is missing but its import was requested.
# The runner does not create the observations file; it fails rather than skip.
OBS_MISSING_MSG = "Observations JSONL not found"

# Optional risk-decisions import support (only active when
# --import-risk-decisions-db is provided, which itself requires --write-db). The
# runner NEVER creates the DB or the risk decisions CSV; it only imports an
# already-written data/risk_decisions.csv (produced by apply_risk_policy.py)
# into an EXISTING DB via the risk decisions importer. DB writes stay limited to
# risk_decisions; future_position_events is never written.
RISK_DEC_IMPORT_NOT_REQUESTED = "NOT_REQUESTED"
RISK_DEC_IMPORT_PENDING = "PENDING"
RISK_DEC_IMPORT_SUCCESS = "SUCCESS"
RISK_DEC_IMPORT_FAILED = "FAILED"

DEFAULT_RISK_DECISIONS_CSV = "data/risk_decisions.csv"

# Exact message required when --import-risk-decisions-db is requested without
# --write-db (the importer needs an existing DB to write into).
RISK_DEC_REQUIRES_DB_MSG = "--import-risk-decisions-db requires --write-db"

# Message when the risk decisions CSV is missing but its import was requested.
# The runner does not create the CSV; it fails rather than skip.
RISK_DEC_MISSING_MSG = "Risk decisions CSV not found"


def build_default_steps() -> List[Tuple[str, List[str]]]:
    """Return the ordered pipeline steps as (name, command-list) tuples.

    Uses the running interpreter so the child scripts run under the same
    Python as the orchestrator.
    """
    py = sys.executable or "python3"
    return [
        ("fetch_meteora_pools", [py, "scripts/fetch_meteora_pools.py"]),
        ("build_watchlist", [py, "scripts/build_watchlist.py"]),
        (OHLCV_STEP_NAME, [py, "scripts/fetch_ohlcv_top_pairs.py"]),
        ("classify_strategy", [py, "scripts/classify_strategy.py"]),
        ("observe_strategy", [py, "scripts/observe_strategy.py"]),
        # Risk Policy Engine (read-only, veto/reporting only). Runs AFTER
        # observe_strategy and BEFORE validate_watchlist because the validator
        # now validates data/risk_decisions.csv, so apply_risk_policy.py must
        # produce it first. Never continue-on-error: a risk policy failure fails
        # the runner.
        (RISK_POLICY_STEP_NAME, [py, "scripts/apply_risk_policy.py"]),
        (VALIDATE_STEP_NAME, [py, "scripts/validate_watchlist.py"]),
    ]


# --------------------------------------------------------------------------- #
# Data model
# --------------------------------------------------------------------------- #

@dataclass
class StepResult:
    name: str
    command: str
    started_at: str
    ended_at: str
    duration_seconds: float
    exit_code: int
    status: str

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "command": self.command,
            "started_at": self.started_at,
            "ended_at": self.ended_at,
            "duration_seconds": self.duration_seconds,
            "exit_code": self.exit_code,
            "status": self.status,
        }


@dataclass
class PipelineOutcome:
    steps: List[StepResult] = field(default_factory=list)
    status: str = "SUCCESS"
    ohlcv_error_tolerated: bool = False


class LockHeldError(RuntimeError):
    """Raised when an active lock is already held by a live process."""


# --------------------------------------------------------------------------- #
# Time helpers
# --------------------------------------------------------------------------- #

def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def make_run_id(now: datetime) -> str:
    """Build a filesystem-safe, timestamped run id."""
    return now.strftime("%Y%m%dT%H%M%S_%f")


def status_for_exit(exit_code: int) -> str:
    return "OK" if exit_code == 0 else "FAILED"


# --------------------------------------------------------------------------- #
# Lock file handling
# --------------------------------------------------------------------------- #

def lock_file_path(lock_dir) -> Path:
    """Return the lock file path inside lock_dir (no side effects)."""
    return Path(lock_dir) / LOCK_FILENAME


def pid_is_active(pid) -> bool:
    """Return True if the given PID refers to a currently running process."""
    if pid is None:
        return False
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
        # Process exists but we cannot signal it -> treat as active.
        return True
    except OSError:
        return False
    return True


def read_lock(lock_path) -> dict:
    """Read and parse a lock file; return {} if missing or unparseable."""
    path = Path(lock_path)
    try:
        with path.open("r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def write_lock(lock_path, pid: int, started_at: str, command: str, cwd: str) -> dict:
    """Write a lock file recording pid, started_at, command, and cwd."""
    info = {
        "pid": pid,
        "started_at": started_at,
        "command": command,
        "cwd": cwd,
    }
    path = Path(lock_path)
    with path.open("w", encoding="utf-8") as fh:
        json.dump(info, fh, indent=2)
        fh.write("\n")
    return info


def acquire_lock(lock_path, pid: int, started_at: str, command: str, cwd: str) -> bool:
    """Acquire the run lock.

    Returns True if a stale lock was replaced, False otherwise.
    Raises LockHeldError if an active lock is held by a live process.
    """
    path = Path(lock_path)
    stale_replaced = False
    if path.exists():
        existing = read_lock(path)
        existing_pid = existing.get("pid")
        if pid_is_active(existing_pid):
            raise LockHeldError(
                f"Active run already in progress (pid={existing_pid}, "
                f"lock={path}). Refusing to start an overlapping run."
            )
        # Lock exists but its PID is not active -> stale, safe to replace.
        stale_replaced = True
    write_lock(path, pid, started_at, command, cwd)
    return stale_replaced


def release_lock(lock_path) -> None:
    """Remove the lock file if present. Never raises on missing file."""
    try:
        Path(lock_path).unlink()
    except FileNotFoundError:
        pass


# --------------------------------------------------------------------------- #
# Step execution
# --------------------------------------------------------------------------- #

def default_step_runner(name: str, command: List[str]) -> Tuple[int, str, str]:
    """Run a child script via subprocess, capturing stdout/stderr.

    Returns (exit_code, stdout, stderr).
    """
    proc = subprocess.run(
        command,
        capture_output=True,
        text=True,
    )
    return proc.returncode, proc.stdout, proc.stderr


def run_step(
    name: str,
    command: List[str],
    step_runner: Callable[[str, List[str]], Tuple[int, str, str]],
    now_fn: Callable[[], datetime],
    log_fh=None,
) -> StepResult:
    """Run a single step, timing it and appending captured output to the log."""
    command_str = " ".join(command)
    started = now_fn()
    exit_code, out, err = step_runner(name, command)
    ended = now_fn()
    duration = (ended - started).total_seconds()
    status = status_for_exit(exit_code)

    if log_fh is not None:
        log_fh.write(f"\n{'=' * 70}\n")
        log_fh.write(f"STEP: {name}\n")
        log_fh.write(f"COMMAND: {command_str}\n")
        log_fh.write(f"STARTED_AT: {started.isoformat()}\n")
        log_fh.write(f"ENDED_AT: {ended.isoformat()}\n")
        log_fh.write(f"DURATION_SECONDS: {duration}\n")
        log_fh.write(f"EXIT_CODE: {exit_code} ({status})\n")
        log_fh.write(f"{'-' * 70}\n")
        log_fh.write("STDOUT:\n")
        log_fh.write(out or "")
        if out and not out.endswith("\n"):
            log_fh.write("\n")
        log_fh.write("STDERR:\n")
        log_fh.write(err or "")
        if err and not err.endswith("\n"):
            log_fh.write("\n")
        log_fh.flush()

    return StepResult(
        name=name,
        command=command_str,
        started_at=started.isoformat(),
        ended_at=ended.isoformat(),
        duration_seconds=duration,
        exit_code=exit_code,
        status=status,
    )


def run_pipeline(
    steps: List[Tuple[str, List[str]]],
    step_runner: Callable[[str, List[str]], Tuple[int, str, str]],
    continue_on_ohlcv_error: bool,
    now_fn: Callable[[], datetime] = utc_now,
    log_fh=None,
) -> PipelineOutcome:
    """Run pipeline steps sequentially.

    - Any non-zero exit fails the runner and stops further steps...
    - ...except the OHLCV step when continue_on_ohlcv_error is True, in which
      case the failure is tolerated and remaining steps still run.
    - The validate step is never tolerated; its failure always fails the runner.
    """
    outcome = PipelineOutcome()
    for name, command in steps:
        result = run_step(name, command, step_runner, now_fn, log_fh)
        outcome.steps.append(result)
        if result.exit_code != 0:
            if name == OHLCV_STEP_NAME and continue_on_ohlcv_error:
                outcome.ohlcv_error_tolerated = True
                if log_fh is not None:
                    log_fh.write(
                        f"\nNOTE: {OHLCV_STEP_NAME} failed (exit {result.exit_code}) "
                        f"but --continue-on-ohlcv-error is set; continuing.\n"
                    )
                    log_fh.flush()
                continue
            outcome.status = "FAILED"
            break
    return outcome


# --------------------------------------------------------------------------- #
# Optional DuckDB write support
# --------------------------------------------------------------------------- #

def db_file_present(db_path) -> bool:
    """Return True only if db_path points to an existing regular file.

    Pure filesystem check (stdlib only). It never creates the database file or
    its parent directory — the runner does not auto-create the DB.
    """
    return Path(db_path).is_file()


def observations_file_present(observations_jsonl) -> bool:
    """Return True only if observations_jsonl points to an existing regular file.

    Pure filesystem check (stdlib only). It never creates the observations file
    — the runner does not auto-create it.
    """
    return Path(observations_jsonl).is_file()


def risk_decisions_file_present(risk_decisions_csv) -> bool:
    """Return True only if risk_decisions_csv points to an existing regular file.

    Pure filesystem check (stdlib only). It never creates the risk decisions CSV
    — the runner does not auto-create it (apply_risk_policy.py produces it).
    """
    return Path(risk_decisions_csv).is_file()


def _load_importer():
    """Deferred import of scripts/import_run_summary_to_db.py.

    Imported lazily (only when --write-db is used) so a normal run never depends
    on the importer module or on duckdb. The importer itself defers its own
    duckdb import, so loading this module does not pull in duckdb.
    """
    scripts_dir = str(Path(__file__).resolve().parent)
    if scripts_dir not in sys.path:
        sys.path.insert(0, scripts_dir)
    import import_run_summary_to_db as importer  # noqa: PLC0415
    return importer


def _load_observations_importer():
    """Deferred import of scripts/import_strategy_observations_to_db.py.

    Imported lazily (only when --import-observations-db is used) so a normal run
    never depends on the observations importer module or on duckdb. The importer
    itself defers its own duckdb import, so loading this module does not pull in
    duckdb.
    """
    scripts_dir = str(Path(__file__).resolve().parent)
    if scripts_dir not in sys.path:
        sys.path.insert(0, scripts_dir)
    import import_strategy_observations_to_db as obs_importer  # noqa: PLC0415
    return obs_importer


def _load_risk_decisions_importer():
    """Deferred import of scripts/import_risk_decisions_to_db.py.

    Imported lazily (only when --import-risk-decisions-db is used) so a normal run
    never depends on the risk decisions importer module or on duckdb. The importer
    itself defers its own duckdb import, so loading this module does not pull in
    duckdb.
    """
    scripts_dir = str(Path(__file__).resolve().parent)
    if scripts_dir not in sys.path:
        sys.path.insert(0, scripts_dir)
    import import_risk_decisions_to_db as risk_dec_importer  # noqa: PLC0415
    return risk_dec_importer


def import_run_summary_into_db(db_path, summary_json_path) -> str:
    """Import an already-written run summary JSON into an EXISTING DuckDB.

    Reuses scripts/import_run_summary_to_db.py instead of duplicating SQL, so the
    importer's guarantees hold: it writes ONLY to pipeline_runs and
    pipeline_steps and never to strategy_observations, risk_flags, or
    future_position_events. Imports with upsert=True so re-importing the same
    run_id is idempotent. Never creates or initializes the database.

    Returns DB_WRITE_SUCCESS or DB_WRITE_FAILED. Does not raise.
    """
    try:
        importer = _load_importer()
        rc = importer.run_import(
            db_path=str(db_path),
            summary_json=str(summary_json_path),
            dry_run=False,
            upsert=True,
        )
    except Exception as exc:  # defensive: run_import normally returns a code
        print(f"ERROR: DuckDB import failed: {exc}", file=sys.stderr)
        return DB_WRITE_FAILED
    return DB_WRITE_SUCCESS if rc == 0 else DB_WRITE_FAILED


def import_observations_into_db(db_path, observations_jsonl, import_risk_flags) -> str:
    """Import an EXISTING observations JSONL into an EXISTING DuckDB.

    Reuses scripts/import_strategy_observations_to_db.py instead of duplicating
    SQL, so the importer's guarantees hold: it writes ONLY to
    strategy_observations and (only with import_risk_flags) risk_flags, and never
    to pipeline_runs, pipeline_steps, or future_position_events. Imports with
    upsert=True so re-importing the same observations is idempotent. Never creates
    or initializes the database, and never creates the observations file.

    Returns OBS_IMPORT_SUCCESS or OBS_IMPORT_FAILED. Does not raise.
    """
    try:
        obs_importer = _load_observations_importer()
        rc = obs_importer.run_import(
            db_path=str(db_path),
            observations_jsonl=str(observations_jsonl),
            dry_run=False,
            upsert=True,
            import_risk_flags=import_risk_flags,
        )
    except Exception as exc:  # defensive: run_import normally returns a code
        print(f"ERROR: observation DuckDB import failed: {exc}", file=sys.stderr)
        return OBS_IMPORT_FAILED
    return OBS_IMPORT_SUCCESS if rc == 0 else OBS_IMPORT_FAILED


def import_risk_decisions_into_db(db_path, risk_decisions_csv) -> Tuple[str, Optional[int]]:
    """Import an EXISTING risk decisions CSV into an EXISTING DuckDB.

    Reuses scripts/import_risk_decisions_to_db.py instead of duplicating SQL, so
    the importer's guarantees hold: it writes ONLY to risk_decisions and never to
    pipeline_runs, pipeline_steps, strategy_observations, risk_flags, or
    future_position_events. Imports with upsert=True so repeated runs do not fail
    on duplicate deterministic risk_decision_ids. Never creates or initializes the
    database, and never creates the risk decisions CSV.

    Returns (status, exit_code). status is RISK_DEC_IMPORT_SUCCESS or
    RISK_DEC_IMPORT_FAILED; exit_code is the importer's return code (or None if it
    raised). Does not raise.
    """
    try:
        risk_dec_importer = _load_risk_decisions_importer()
        rc = risk_dec_importer.run_import(
            db_path=str(db_path),
            risk_decisions_csv=str(risk_decisions_csv),
            dry_run=False,
            upsert=True,
        )
    except Exception as exc:  # defensive: run_import normally returns a code
        print(f"ERROR: risk decisions DuckDB import failed: {exc}", file=sys.stderr)
        return RISK_DEC_IMPORT_FAILED, None
    status = RISK_DEC_IMPORT_SUCCESS if rc == 0 else RISK_DEC_IMPORT_FAILED
    return status, rc


# --------------------------------------------------------------------------- #
# Summary generation
# --------------------------------------------------------------------------- #

def build_summary_dict(
    run_id: str,
    started_at: datetime,
    ended_at: datetime,
    outcome: PipelineOutcome,
    continue_on_ohlcv_error: bool,
    stale_lock_replaced: bool,
    log_file: str,
    db_path: Optional[str] = None,
    db_write_status: str = DB_WRITE_NOT_REQUESTED,
    observations_jsonl: Optional[str] = None,
    observation_db_import_status: str = OBS_IMPORT_NOT_REQUESTED,
    import_risk_flags: bool = False,
    import_risk_decisions_db: bool = False,
    risk_decisions_csv: Optional[str] = None,
    risk_decisions_db_import_status: str = RISK_DEC_IMPORT_NOT_REQUESTED,
    risk_decisions_db_exit_code: Optional[int] = None,
    risk_decisions_db_message: Optional[str] = None,
) -> dict:
    return {
        "run_id": run_id,
        "started_at": started_at.isoformat(),
        "ended_at": ended_at.isoformat(),
        "duration_seconds": (ended_at - started_at).total_seconds(),
        "status": outcome.status,
        "safety_phase": SAFETY_PHASE,
        "continue_on_ohlcv_error": continue_on_ohlcv_error,
        "ohlcv_error_tolerated": outcome.ohlcv_error_tolerated,
        "stale_lock_replaced": stale_lock_replaced,
        "log_file": str(log_file),
        "db_path": db_path,
        "db_write_status": db_write_status,
        "observations_jsonl": observations_jsonl,
        "observation_db_import_status": observation_db_import_status,
        "import_risk_flags": import_risk_flags,
        # Flat status fields mirror the observation-import shape for symmetry.
        "risk_decisions_csv": risk_decisions_csv,
        "risk_decisions_db_import_status": risk_decisions_db_import_status,
        # Nested object carries the full requested schema (enabled / attempted /
        # success / paths / exit_code / message) without disturbing older fields.
        "risk_decisions_db_import": {
            "enabled": import_risk_decisions_db,
            "attempted": risk_decisions_db_import_status
            in (RISK_DEC_IMPORT_SUCCESS, RISK_DEC_IMPORT_FAILED),
            "success": risk_decisions_db_import_status == RISK_DEC_IMPORT_SUCCESS,
            "risk_decisions_csv": risk_decisions_csv,
            "db_path": db_path,
            "exit_code": risk_decisions_db_exit_code,
            "message": risk_decisions_db_message,
        },
        "steps": [s.to_dict() for s in outcome.steps],
    }


def build_summary_markdown(summary: dict, summary_json_path: str) -> str:
    lines: List[str] = []
    lines.append("# Read-only Runtime Orchestrator — Run Summary")
    lines.append("")
    lines.append(f"- **Run ID:** `{summary['run_id']}`")
    lines.append(f"- **Status:** {summary['status']}")
    lines.append(f"- **Started:** {summary['started_at']}")
    lines.append(f"- **Ended:** {summary['ended_at']}")
    lines.append(f"- **Duration (s):** {summary['duration_seconds']}")
    lines.append(f"- **continue_on_ohlcv_error:** {summary['continue_on_ohlcv_error']}")
    lines.append(f"- **ohlcv_error_tolerated:** {summary['ohlcv_error_tolerated']}")
    lines.append(f"- **stale_lock_replaced:** {summary['stale_lock_replaced']}")
    lines.append(
        f"- **DB write status:** {summary.get('db_write_status', DB_WRITE_NOT_REQUESTED)}"
    )
    lines.append(f"- **DB path:** {summary.get('db_path')}")
    lines.append("")
    lines.append("## DB Write Status")
    lines.append("")
    lines.append(f"- **DB path:** {summary.get('db_path')}")
    lines.append(
        "- **Run summary DB write status:** "
        f"{summary.get('db_write_status', DB_WRITE_NOT_REQUESTED)}"
    )
    lines.append(
        "- **Observation DB import status:** "
        f"{summary.get('observation_db_import_status', OBS_IMPORT_NOT_REQUESTED)}"
    )
    lines.append(f"- **Observations JSONL:** {summary.get('observations_jsonl')}")
    lines.append(
        f"- **Risk flags imported:** {bool(summary.get('import_risk_flags', False))}"
    )
    lines.append(
        "- **Risk decisions DB import status:** "
        f"{summary.get('risk_decisions_db_import_status', RISK_DEC_IMPORT_NOT_REQUESTED)}"
    )
    lines.append(f"- **Risk decisions CSV:** {summary.get('risk_decisions_csv')}")
    rd = summary.get("risk_decisions_db_import") or {}
    lines.append(
        f"- **Risk decisions DB import exit code:** {rd.get('exit_code')}"
    )
    lines.append("")
    lines.append("## Safety Boundary")
    lines.append("")
    lines.append("```")
    lines.append(SAFETY_BANNER)
    lines.append("```")
    lines.append("")
    lines.append("## Steps")
    lines.append("")
    lines.append("| # | Step | Status | Exit | Duration (s) | Started | Ended |")
    lines.append("|---|------|--------|------|--------------|---------|-------|")
    for i, step in enumerate(summary["steps"], start=1):
        lines.append(
            f"| {i} | `{step['name']}` | {step['status']} | {step['exit_code']} "
            f"| {step['duration_seconds']} | {step['started_at']} | {step['ended_at']} |"
        )
    lines.append("")
    lines.append("## Artifacts")
    lines.append("")
    lines.append(f"- **Log file:** `{summary['log_file']}`")
    lines.append(f"- **Summary JSON:** `{summary_json_path}`")
    lines.append("")
    lines.append("## Authorization Note")
    lines.append("")
    lines.append(
        "This runner does **not** authorize paper, live, or execution actions. "
        "It only orchestrates the existing read-only screening pipeline "
        "(non-custodial, non-executing). No wallet, signing, swap, LP, rebalance, "
        "or live execution is performed or implied."
    )
    lines.append("")
    return "\n".join(lines)


def write_summary_files(summary: dict, summary_json_path, summary_md_path) -> None:
    """Write the run summary JSON and Markdown artifacts to disk.

    Pulled out so the runner can (re-)write both atomically from one place,
    including a second write that records the final DB write status.
    """
    with Path(summary_json_path).open("w", encoding="utf-8") as fh:
        json.dump(summary, fh, indent=2)
        fh.write("\n")

    markdown = build_summary_markdown(summary, str(summary_json_path))
    with Path(summary_md_path).open("w", encoding="utf-8") as fh:
        fh.write(markdown)


# --------------------------------------------------------------------------- #
# CLI / orchestration
# --------------------------------------------------------------------------- #

def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Read-only Runtime Orchestrator v0.1 for the DLMM screening pipeline.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the planned steps and exit without creating dirs, locks, or running scripts.",
    )
    parser.add_argument(
        "--continue-on-ohlcv-error",
        action="store_true",
        help="If the OHLCV step fails, continue the remaining steps instead of failing the run.",
    )
    parser.add_argument(
        "--log-dir",
        default=DEFAULT_LOG_DIR,
        help=f"Directory for timestamped run logs (default: {DEFAULT_LOG_DIR}).",
    )
    parser.add_argument(
        "--lock-dir",
        default=DEFAULT_LOCK_DIR,
        help=f"Directory for the overlap-prevention lock file (default: {DEFAULT_LOCK_DIR}).",
    )
    parser.add_argument(
        "--summary-dir",
        default=DEFAULT_SUMMARY_DIR,
        help=f"Directory for timestamped run summaries (default: {DEFAULT_SUMMARY_DIR}).",
    )
    parser.add_argument(
        "--write-db",
        default=None,
        metavar="PATH",
        help=(
            "After the run, import this run's summary JSON into an EXISTING DuckDB "
            "at PATH (writes only pipeline_runs + pipeline_steps, upsert). The DB "
            "must already exist — run scripts/init_runtime_db.py first; it is never "
            "auto-created, auto-initialized, or written to without this flag."
        ),
    )
    parser.add_argument(
        "--import-observations-db",
        action="store_true",
        help=(
            "After the run, also import the observations JSONL into the EXISTING "
            "DuckDB (strategy_observations only; risk_flags too with "
            "--import-risk-flags). Requires --write-db. Never writes "
            "future_position_events; never creates the DB or the observations file."
        ),
    )
    parser.add_argument(
        "--observations-jsonl",
        default=DEFAULT_OBSERVATIONS_JSONL,
        help=(
            "Path to the observation JSONL imported when --import-observations-db "
            f"is set (default: {DEFAULT_OBSERVATIONS_JSONL})."
        ),
    )
    parser.add_argument(
        "--import-risk-flags",
        action="store_true",
        help=(
            "With --import-observations-db, also derive and import risk_flags rows "
            "from each observation."
        ),
    )
    parser.add_argument(
        "--import-risk-decisions-db",
        action="store_true",
        help=(
            "After the run, also import the risk decisions CSV (produced by "
            "apply_risk_policy.py) into the EXISTING DuckDB (risk_decisions only, "
            "upsert). Requires --write-db. Never writes future_position_events; "
            "never creates the DB or the risk decisions CSV."
        ),
    )
    parser.add_argument(
        "--risk-decisions-csv",
        default=DEFAULT_RISK_DECISIONS_CSV,
        help=(
            "Path to the risk decisions CSV imported when --import-risk-decisions-db "
            f"is set (default: {DEFAULT_RISK_DECISIONS_CSV})."
        ),
    )
    return parser.parse_args(argv)


def print_dry_run(steps: List[Tuple[str, List[str]]], args: argparse.Namespace) -> None:
    print("DRY RUN — Read-only Runtime Orchestrator v0.1")
    print()
    print(SAFETY_BANNER)
    print()
    print("Planned steps (sequential):")
    for i, (name, command) in enumerate(steps, start=1):
        print(f"  {i}. {name}: {' '.join(command)}")
    print()
    write_db = getattr(args, "write_db", None)
    import_obs = getattr(args, "import_observations_db", False)
    observations_jsonl = getattr(args, "observations_jsonl", DEFAULT_OBSERVATIONS_JSONL)
    import_risk_flags = getattr(args, "import_risk_flags", False)
    import_risk_dec = getattr(args, "import_risk_decisions_db", False)
    risk_decisions_csv = getattr(args, "risk_decisions_csv", DEFAULT_RISK_DECISIONS_CSV)
    print(f"continue_on_ohlcv_error  : {args.continue_on_ohlcv_error}")
    print(f"log-dir                  : {args.log_dir}")
    print(f"lock-dir                 : {args.lock_dir}")
    print(f"summary-dir              : {args.summary_dir}")
    print(f"write-db                 : {write_db if write_db else '(disabled)'}")
    print(f"import-observations-db   : {import_obs}")
    print(f"observations-jsonl       : {observations_jsonl}")
    print(f"import-risk-flags        : {import_risk_flags}")
    print(f"import-risk-decisions-db : {import_risk_dec}")
    print(f"risk-decisions-csv       : {risk_decisions_csv}")
    print()
    if write_db:
        print(
            f"DB write is PLANNED but NOT executed in dry run: would import the run "
            f"summary JSON into existing DuckDB '{write_db}' "
            f"(pipeline_runs + pipeline_steps only, upsert). The database is not "
            f"created, initialized, or touched during a dry run."
        )
        print()
    if import_obs:
        print(
            f"Observation import is PLANNED but NOT executed in dry run: would import "
            f"observations JSONL '{observations_jsonl}' into existing DuckDB "
            f"'{write_db}' (strategy_observations"
            + (", risk_flags" if import_risk_flags else "")
            + " only, upsert). Risk flags imported: "
            f"{import_risk_flags}. The database and observations file are not "
            f"created or touched during a dry run; future_position_events is never "
            f"written."
        )
        print()
    if import_risk_dec:
        print(
            f"Risk decisions import is PLANNED but NOT executed in dry run: would "
            f"import risk decisions CSV '{risk_decisions_csv}' into existing DuckDB "
            f"'{write_db}' (risk_decisions only, upsert). The database and risk "
            f"decisions CSV are not created or touched during a dry run; "
            f"future_position_events is never written."
        )
        print()
    print("Dry run: no runtime directories created, no lock file created, "
          "no child scripts executed, no database written, no observations "
          "imported, no risk decisions imported.")


def execute_run(
    args: argparse.Namespace,
    steps: Optional[List[Tuple[str, List[str]]]] = None,
    step_runner: Callable[[str, List[str]], Tuple[int, str, str]] = default_step_runner,
    now_fn: Callable[[], datetime] = utc_now,
) -> int:
    """Execute a real (non-dry-run) pipeline run. Returns a process exit code."""
    if steps is None:
        steps = build_default_steps()

    write_db = getattr(args, "write_db", None)
    import_obs = getattr(args, "import_observations_db", False)
    observations_jsonl = getattr(args, "observations_jsonl", DEFAULT_OBSERVATIONS_JSONL)
    import_risk_flags = getattr(args, "import_risk_flags", False)
    import_risk_dec = getattr(args, "import_risk_decisions_db", False)
    risk_decisions_csv = getattr(args, "risk_decisions_csv", DEFAULT_RISK_DECISIONS_CSV)

    # Pre-flight: --import-observations-db is meaningless without an existing DB
    # to write into, so it requires --write-db. Fail fast before any work.
    if import_obs and not write_db:
        print(f"ERROR: {OBS_REQUIRES_DB_MSG}", file=sys.stderr)
        return 2

    # Pre-flight: --import-risk-decisions-db likewise requires an existing DB, so
    # it requires --write-db. Fail fast before any work.
    if import_risk_dec and not write_db:
        print(f"ERROR: {RISK_DEC_REQUIRES_DB_MSG}", file=sys.stderr)
        return 2

    # Pre-flight: if a DB write was requested, the DB must already exist. We
    # never auto-create or auto-initialize it. Fail fast before doing any work
    # so a missing DB does not waste a full pipeline run or create runtime dirs.
    if write_db and not db_file_present(write_db):
        print(f"ERROR: {DB_MISSING_MSG}", file=sys.stderr)
        return 2

    # Pre-flight: if an observation import was requested, the observations JSONL
    # must already exist. We never auto-create it and never silently skip. Fail
    # fast before any work so a missing file does not waste a full pipeline run
    # or create runtime dirs.
    if import_obs and not observations_file_present(observations_jsonl):
        print(
            f"ERROR: {OBS_MISSING_MSG}: {observations_jsonl}. "
            "This runner does not create the observations file.",
            file=sys.stderr,
        )
        return 2

    # NOTE: there is deliberately NO early existence pre-flight for the risk
    # decisions CSV. apply_risk_policy.py is a runtime pipeline step that PRODUCES
    # data/risk_decisions.csv, so the file is legitimately absent before the
    # pipeline runs. The presence check happens post-pipeline, immediately before
    # the importer is called (see below). The runner still never creates the CSV.

    log_dir = Path(args.log_dir)
    lock_dir = Path(args.lock_dir)
    summary_dir = Path(args.summary_dir)
    for d in (log_dir, lock_dir, summary_dir):
        d.mkdir(parents=True, exist_ok=True)

    started_at = now_fn()
    run_id = make_run_id(started_at)
    log_path = log_dir / f"run_{run_id}.log"
    summary_json_path = summary_dir / f"run_{run_id}.json"
    summary_md_path = summary_dir / f"run_{run_id}.md"
    lock_path = lock_file_path(lock_dir)

    command_str = " ".join(sys.argv)
    try:
        stale_lock_replaced = acquire_lock(
            lock_path,
            pid=os.getpid(),
            started_at=started_at.isoformat(),
            command=command_str,
            cwd=os.getcwd(),
        )
    except LockHeldError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    try:
        with log_path.open("w", encoding="utf-8") as log_fh:
            log_fh.write("Read-only Runtime Orchestrator v0.1 — run log\n")
            log_fh.write(f"RUN_ID: {run_id}\n")
            log_fh.write(f"STARTED_AT: {started_at.isoformat()}\n")
            log_fh.write("SAFETY BOUNDARY:\n")
            log_fh.write(SAFETY_BANNER + "\n")
            if stale_lock_replaced:
                log_fh.write("\nNOTE: a stale lock (dead PID) was detected and replaced.\n")
            log_fh.flush()

            outcome = run_pipeline(
                steps,
                step_runner,
                continue_on_ohlcv_error=args.continue_on_ohlcv_error,
                now_fn=now_fn,
                log_fh=log_fh,
            )

        ended_at = now_fn()
        db_write_status = DB_WRITE_PENDING if write_db else DB_WRITE_NOT_REQUESTED
        observation_db_import_status = (
            OBS_IMPORT_PENDING if import_obs else OBS_IMPORT_NOT_REQUESTED
        )
        risk_decisions_db_import_status = (
            RISK_DEC_IMPORT_PENDING if import_risk_dec else RISK_DEC_IMPORT_NOT_REQUESTED
        )
        summary = build_summary_dict(
            run_id=run_id,
            started_at=started_at,
            ended_at=ended_at,
            outcome=outcome,
            continue_on_ohlcv_error=args.continue_on_ohlcv_error,
            stale_lock_replaced=stale_lock_replaced,
            log_file=str(log_path),
            db_path=write_db,
            db_write_status=db_write_status,
            observations_jsonl=observations_jsonl if import_obs else None,
            observation_db_import_status=observation_db_import_status,
            import_risk_flags=import_risk_flags,
            import_risk_decisions_db=import_risk_dec,
            risk_decisions_csv=risk_decisions_csv if import_risk_dec else None,
            risk_decisions_db_import_status=risk_decisions_db_import_status,
        )

        # Write the summary JSON first; the importer reads this exact file. The
        # summary Markdown is written here too so artifacts exist even if the
        # optional DB import below fails.
        write_summary_files(summary, summary_json_path, summary_md_path)

        # Optional DuckDB write happens only AFTER the summary JSON exists, on
        # both successful and failed pipeline runs. A failed import makes the
        # runner exit non-zero, but never converts a failed pipeline into a pass.
        db_import_failed = False
        if write_db:
            db_write_status = import_run_summary_into_db(write_db, summary_json_path)
            db_import_failed = db_write_status != DB_WRITE_SUCCESS
            summary["db_write_status"] = db_write_status
            # Re-write artifacts with the final DB write status.
            write_summary_files(summary, summary_json_path, summary_md_path)

        # Optional strategy-observation import happens AFTER the run summary
        # import, on both successful and failed pipeline runs (the observations
        # JSONL existence was already pre-flighted above). It writes only to
        # strategy_observations and (with --import-risk-flags) risk_flags, never
        # future_position_events. A failed import makes the runner exit non-zero.
        obs_import_failed = False
        if import_obs:
            observation_db_import_status = import_observations_into_db(
                write_db, observations_jsonl, import_risk_flags
            )
            obs_import_failed = observation_db_import_status != OBS_IMPORT_SUCCESS
            summary["observation_db_import_status"] = observation_db_import_status
            # Re-write artifacts with the final observation import status.
            write_summary_files(summary, summary_json_path, summary_md_path)

        # Optional risk-decisions import happens LAST — after the run summary and
        # observation imports — so it only runs once the earlier DB import flow is
        # safe. It writes only to risk_decisions (upsert), never
        # future_position_events. A failed import makes the runner exit non-zero
        # but never converts a failed pipeline into a pass.
        #
        # The risk decisions CSV is PRODUCED by apply_risk_policy.py during the
        # pipeline, so its existence is checked HERE (post-pipeline), immediately
        # before the importer. If it is still missing the import fails (the runner
        # never creates the CSV and never calls the importer); otherwise it imports
        # with upsert.
        risk_dec_import_failed = False
        if import_risk_dec:
            rd = summary["risk_decisions_db_import"]
            if not risk_decisions_file_present(risk_decisions_csv):
                # CSV absent even after the pipeline ran -> post-pipeline failure.
                risk_decisions_db_import_status = RISK_DEC_IMPORT_FAILED
                risk_dec_import_failed = True
                summary["risk_decisions_db_import_status"] = (
                    risk_decisions_db_import_status
                )
                rd["attempted"] = True
                rd["success"] = False
                rd["exit_code"] = None
                rd["message"] = f"{RISK_DEC_MISSING_MSG}: {risk_decisions_csv}"
                print(
                    f"ERROR: {RISK_DEC_MISSING_MSG}: {risk_decisions_csv}. "
                    "This runner does not create the risk decisions CSV.",
                    file=sys.stderr,
                )
                # Re-write artifacts with the failed status/message; do NOT call
                # the importer and do NOT create the CSV.
                write_summary_files(summary, summary_json_path, summary_md_path)
            else:
                risk_decisions_db_import_status, risk_dec_exit_code = (
                    import_risk_decisions_into_db(write_db, risk_decisions_csv)
                )
                risk_dec_import_failed = (
                    risk_decisions_db_import_status != RISK_DEC_IMPORT_SUCCESS
                )
                summary["risk_decisions_db_import_status"] = (
                    risk_decisions_db_import_status
                )
                rd["attempted"] = True
                rd["success"] = not risk_dec_import_failed
                rd["exit_code"] = risk_dec_exit_code
                rd["message"] = (
                    None
                    if not risk_dec_import_failed
                    else f"risk decisions import failed (exit_code={risk_dec_exit_code})"
                )
                # Re-write artifacts with the final risk decisions import status.
                write_summary_files(summary, summary_json_path, summary_md_path)

        print(f"Run {run_id} finished: {outcome.status}")
        if stale_lock_replaced:
            print("Note: a stale lock was detected and replaced.")
        print(f"Log     : {log_path}")
        print(f"Summary : {summary_json_path}")
        print(f"Markdown: {summary_md_path}")
        if write_db:
            print(f"DB write: {db_write_status} -> {write_db}")
        if import_obs:
            print(
                f"Observation import: {observation_db_import_status} -> {write_db} "
                f"(risk_flags={import_risk_flags})"
            )
        if import_risk_dec:
            print(
                f"Risk decisions import: {risk_decisions_db_import_status} -> "
                f"{write_db} (csv={risk_decisions_csv})"
            )

        if (
            outcome.status != "SUCCESS"
            or db_import_failed
            or obs_import_failed
            or risk_dec_import_failed
        ):
            return 1
        return 0
    finally:
        release_lock(lock_path)


def main(argv: Optional[List[str]] = None) -> int:
    args = parse_args(argv)

    # --import-observations-db requires --write-db. Enforce before any work
    # (including dry-run printing and pipeline execution) so the runner does not
    # run the pipeline when the flag combination is invalid.
    if getattr(args, "import_observations_db", False) and not args.write_db:
        print(f"ERROR: {OBS_REQUIRES_DB_MSG}", file=sys.stderr)
        return 2

    # --import-risk-decisions-db likewise requires --write-db. Enforce before any
    # work (including dry-run printing and pipeline execution).
    if getattr(args, "import_risk_decisions_db", False) and not args.write_db:
        print(f"ERROR: {RISK_DEC_REQUIRES_DB_MSG}", file=sys.stderr)
        return 2

    steps = build_default_steps()
    if args.dry_run:
        print_dry_run(steps, args)
        return 0
    return execute_run(args, steps=steps)


if __name__ == "__main__":
    raise SystemExit(main())
