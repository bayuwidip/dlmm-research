#!/usr/bin/env python3
"""
Risk Decisions Importer to DuckDB v0.1

Purpose:
- Import an EXISTING risk decisions CSV (produced by
  scripts/apply_risk_policy.py) into the runtime DuckDB database
  (default: runtime/dlmm.duckdb) as read-only metadata for historical querying.

This is an OFFLINE / IMPORT tool ONLY. It is a bookkeeper that copies the rows
of data/risk_decisions.csv into the risk_decisions table and nothing more. It is
a storage / import layer only.

This script:
- Does NOT run the pipeline.
- Does NOT integrate with the runner (no runner integration here).
- Does NOT spawn child processes.
- Does NOT access the network.
- Does NOT schedule anything (no cron / systemd) and does NOT talk to Telegram.
- Does NOT inspect wallets.
- Does NOT create the database (it requires an existing, initialized DB).
- Does NOT create the risk decisions CSV (it requires an existing CSV).
- Writes ONLY to the risk_decisions table.

It deliberately does NOT:
- create positions
- create paper entries
- generate ENTRY / EXIT / REBALANCE signals
- write pipeline_runs, pipeline_steps, strategy_observations, risk_flags, or
  future_position_events

This is NOT and never enables:
- wallet creation / import / management
- private key handling
- transaction signing
- swap execution
- LP add / remove
- rebalance
- live execution
- any LIVE_ELIGIBLE_* capability
- paper / live / execution instructions of any kind

See docs/target_architecture.md §7 (SSOT / Storage Layer) and
docs/project_checkpoint.md §2 (Hard Safety Boundary).
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import sys
from datetime import datetime, timezone
from pathlib import Path


# ---------------------------------------------------------------------------
# Safety constants
# ---------------------------------------------------------------------------

SAFETY_PHASE = "READ_ONLY / RESEARCH_ONLY / SCREENING_ONLY / PAPER_ONLY"

SAFETY_BANNER = "\n".join(
    [
        "READ_ONLY / RESEARCH_ONLY / SCREENING_ONLY / PAPER_ONLY",
        "No wallet",
        "No private key",
        "No signing",
        "No swap",
        "No LP",
        "No rebalance",
        "No live execution",
        "No LIVE_ELIGIBLE_*",
    ]
)

# Exact message required when the optional duckdb dependency is missing.
DUCKDB_MISSING_MSG = (
    "duckdb package is required. Install with: python3 -m pip install duckdb"
)

DEFAULT_DB_PATH = "runtime/dlmm.duckdb"
DEFAULT_RISK_DECISIONS_CSV = "data/risk_decisions.csv"

# Deterministic id prefix.
RISK_DECISION_ID_PREFIX = "risk_"

# Tables this importer requires to already exist in the target DB.
REQUIRED_SCHEMA_TABLES = (
    "runtime_schema_meta",
    "risk_decisions",
)

# Tables this importer must NEVER write to in this phase.
FORBIDDEN_WRITE_TABLES = (
    "pipeline_runs",
    "pipeline_steps",
    "strategy_observations",
    "risk_flags",
    "future_position_events",
)

# Required columns of the risk decisions CSV (apply_risk_policy.py output).
REQUIRED_CSV_COLUMNS = (
    "pair_key",
    "pair_label",
    "strategy_class_v2",
    "pair_status_v2",
    "test_lane",
    "live_eligibility",
    "required_capability",
    "risk_flag_count",
    "risk_flags",
    "risk_decision",
    "risk_action",
    "max_allowed_action",
    "risk_blockers",
    "risk_warnings",
    "risk_required_next_step",
    "risk_policy_reason",
    "safety_phase",
)

# Allowed enums (the importer refuses to write anything outside these).
ALLOWED_RISK_DECISION = frozenset(
    {"BLOCKED", "OBSERVE_ONLY", "PAPER_REVIEW_CANDIDATE", "NOT_EVALUATED", "REJECTED"}
)
ALLOWED_RISK_ACTION = frozenset(
    {
        "NO_ACTION",
        "CONTINUE_OBSERVATION",
        "REVIEW_FOR_FUTURE_PAPER_SIMULATION",
        "FIX_DATA_OR_CLASSIFICATION",
        "REJECT",
    }
)
ALLOWED_MAX_ALLOWED_ACTION = frozenset(
    {"NONE", "OBSERVE_ONLY", "FUTURE_PAPER_SIMULATION_REVIEW"}
)

# Forbidden execution-authorization tokens. These are uppercase, enum-like
# capability/authorization tokens — NOT lowercase prose. The current safe output
# of apply_risk_policy.py uses explanatory wording like "no execution" and
# "not live readiness"; those lowercase phrases must NOT trip this guard.
#
# LIVE_ELIGIBLE is handled separately via FORBIDDEN_LIVE_PREFIX so that the legit
# negation value 'NOT_LIVE_ELIGIBLE' (which contains the substring LIVE_ELIGIBLE
# but is not a live grant) is accepted.
FORBIDDEN_TOKENS = (
    "LIVE_ENTRY",
    "PAPER_ENTRY",
    "EXECUTE",
    "WALLET",
    "PRIVATE_KEY",
    "SIGNING",
    "SWAP",
    "LP_ACTION",
    "REBALANCE",
)
# LIVE_ELIGIBLE_<grant> (e.g. LIVE_ELIGIBLE_TINY_SIZE) is forbidden everywhere.
# 'NOT_LIVE_ELIGIBLE' has no trailing underscore after LIVE_ELIGIBLE, so it
# passes this check.
FORBIDDEN_LIVE_PREFIX = "LIVE_ELIGIBLE_"


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class RiskDecisionValidationError(ValueError):
    """Raised when the CSV is missing columns or a row is malformed/forbidden."""


class SafetyPhaseError(ValueError):
    """Raised when the DB safety_phase does not match the required phase."""


class DuplicateRiskDecisionError(RuntimeError):
    """Raised when a risk_decision_id already exists and --upsert was not given."""


class SchemaError(RuntimeError):
    """Raised when the target DB is missing one of the required schema tables."""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def utc_now() -> datetime:
    """Return the current UTC time as a timezone-aware datetime."""
    return datetime.now(timezone.utc)


def require_duckdb():
    """Import and return the duckdb module, or raise a clear error.

    Kept as a single chokepoint so the missing-dependency path is testable by
    monkeypatching this function. Dependencies are never auto-installed.
    """
    try:
        import duckdb  # noqa: PLC0415  (deferred import is intentional)
    except ImportError as exc:
        raise RuntimeError(DUCKDB_MISSING_MSG) from exc
    return duckdb


def sha256_id(prefix: str, *parts: str) -> str:
    """Return a deterministic id: prefix + sha256 of the '|'-joined parts."""
    digest = hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()
    return f"{prefix}{digest}"


def contains_forbidden_token(value: str) -> "str | None":
    """Return the first forbidden authorization token found in value, or None.

    Focuses on uppercase enum-like authorization tokens and direct capability
    tokens. Lowercase non-authorization prose (e.g. "no execution") is ignored.
    """
    s = str(value)
    for tok in FORBIDDEN_TOKENS:
        if tok in s:
            return tok
    if FORBIDDEN_LIVE_PREFIX in s:
        return FORBIDDEN_LIVE_PREFIX
    return None


# ---------------------------------------------------------------------------
# File presence + CSV loading
# ---------------------------------------------------------------------------

def db_exists(db_path: str) -> bool:
    """Return True only if db_path points to an existing regular file."""
    return Path(db_path).is_file()


def csv_exists(csv_path: str) -> bool:
    """Return True only if csv_path points to an existing regular file."""
    return Path(csv_path).is_file()


def load_risk_decisions(csv_path: str):
    """Load the risk decisions CSV. Returns (header, rows-as-list-of-dict).

    Raises FileNotFoundError if missing, RiskDecisionValidationError if the
    required columns are absent.
    """
    path = Path(csv_path)
    if not path.is_file():
        raise FileNotFoundError(f"Risk decisions CSV not found: {csv_path}")

    with path.open(newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        header = list(reader.fieldnames or [])
        rows = [dict(row) for row in reader]

    missing = [c for c in REQUIRED_CSV_COLUMNS if c not in header]
    if missing:
        raise RiskDecisionValidationError(
            f"Risk decisions CSV missing required column(s): {missing}"
        )
    return header, rows


# ---------------------------------------------------------------------------
# Record validation + normalization
# ---------------------------------------------------------------------------

def validate_row(row: dict, index: int) -> None:
    """Validate one CSV row. Raises RiskDecisionValidationError on any failure.

    Checks the decision/action/max enums, the exact safety_phase, and refuses
    any row carrying a forbidden execution-authorization token in any field.
    """
    decision = (row.get("risk_decision") or "").strip()
    action = (row.get("risk_action") or "").strip()
    maxa = (row.get("max_allowed_action") or "").strip()
    phase = (row.get("safety_phase") or "").strip()

    if decision not in ALLOWED_RISK_DECISION:
        raise RiskDecisionValidationError(
            f"Row #{index}: risk_decision='{decision}' is not allowed "
            f"(allowed: {sorted(ALLOWED_RISK_DECISION)})."
        )
    if action not in ALLOWED_RISK_ACTION:
        raise RiskDecisionValidationError(
            f"Row #{index}: risk_action='{action}' is not allowed "
            f"(allowed: {sorted(ALLOWED_RISK_ACTION)})."
        )
    if maxa not in ALLOWED_MAX_ALLOWED_ACTION:
        raise RiskDecisionValidationError(
            f"Row #{index}: max_allowed_action='{maxa}' is not allowed "
            f"(allowed: {sorted(ALLOWED_MAX_ALLOWED_ACTION)})."
        )
    if phase != SAFETY_PHASE:
        raise RiskDecisionValidationError(
            f"Row #{index}: safety_phase='{phase}' != required '{SAFETY_PHASE}'."
        )

    # Hard forbidden-token guard across every relevant field.
    for column in REQUIRED_CSV_COLUMNS:
        tok = contains_forbidden_token(row.get(column, ""))
        if tok is not None:
            raise RiskDecisionValidationError(
                f"Row #{index}: forbidden execution-authorization token "
                f"'{tok}' found in column '{column}'. Refusing to import."
            )


def _coerce_optional_int(value):
    """Coerce a value into an int, or None when not convertible/absent."""
    if value is None or str(value).strip() == "":
        return None
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        try:
            return int(float(value))
        except (TypeError, ValueError):
            return None


def compute_risk_decision_id(row: dict) -> str:
    """Return the deterministic risk_decision_id for a row.

    Derived from pair_key + pair_label + strategy_class_v2 + risk_decision +
    risk_action + max_allowed_action + safety_phase, so the same generated file
    re-imports to the same id (no duplication under --upsert).
    """
    return sha256_id(
        RISK_DECISION_ID_PREFIX,
        str(row.get("pair_key", "")),
        str(row.get("pair_label", "")),
        str(row.get("strategy_class_v2", "")),
        str(row.get("risk_decision", "")),
        str(row.get("risk_action", "")),
        str(row.get("max_allowed_action", "")),
        str(row.get("safety_phase", "")),
    )


def build_risk_decision_row(row: dict, source_csv: str, imported_at) -> dict:
    """Build the risk_decisions DB row dict from a validated CSV row."""
    return {
        "risk_decision_id": compute_risk_decision_id(row),
        "imported_at": imported_at,
        "pair_key": str(row.get("pair_key", "")),
        "pair_label": str(row.get("pair_label", "")),
        "strategy_class_v2": str(row.get("strategy_class_v2", "")),
        "pair_status_v2": str(row.get("pair_status_v2", "")),
        "test_lane": str(row.get("test_lane", "")),
        "live_eligibility": str(row.get("live_eligibility", "")),
        "required_capability": str(row.get("required_capability", "")),
        "risk_flag_count": _coerce_optional_int(row.get("risk_flag_count")),
        "risk_flags": str(row.get("risk_flags", "")),
        "risk_decision": str(row.get("risk_decision", "")),
        "risk_action": str(row.get("risk_action", "")),
        "max_allowed_action": str(row.get("max_allowed_action", "")),
        "risk_blockers": str(row.get("risk_blockers", "")),
        "risk_warnings": str(row.get("risk_warnings", "")),
        "risk_required_next_step": str(row.get("risk_required_next_step", "")),
        "risk_policy_reason": str(row.get("risk_policy_reason", "")),
        "safety_phase": str(row.get("safety_phase", "")),
        "source_csv": str(source_csv),
    }


# ---------------------------------------------------------------------------
# Database access
# ---------------------------------------------------------------------------

def connect_db(db_path: str):
    """Open an EXISTING DuckDB database for read/write.

    The caller must ensure the file exists; this function never creates the
    database file or its parent directory.
    """
    duckdb = require_duckdb()
    return duckdb.connect(str(db_path))


def list_tables(conn):
    """Return the set of table names in the main schema of the connection."""
    rows = conn.execute(
        "SELECT table_name FROM information_schema.tables WHERE table_schema = 'main'"
    ).fetchall()
    return {row[0] for row in rows}


def validate_schema_tables(conn) -> None:
    """Verify the required schema tables exist. Raises SchemaError if not."""
    present = list_tables(conn)
    missing = [name for name in REQUIRED_SCHEMA_TABLES if name not in present]
    if missing:
        raise SchemaError(
            "Target DB is missing required table(s): "
            f"{missing}. Run scripts/init_runtime_db.py first."
        )


def get_db_safety_phase(conn):
    """Return the runtime_schema_meta safety_phase, or None when absent."""
    row = conn.execute(
        "SELECT safety_phase FROM runtime_schema_meta ORDER BY schema_name LIMIT 1"
    ).fetchone()
    return row[0] if row else None


def validate_db_safety_phase(conn) -> None:
    """Validate that the DB safety_phase matches the required phase exactly."""
    phase = get_db_safety_phase(conn)
    if phase != SAFETY_PHASE:
        raise SafetyPhaseError(
            f"DB safety_phase '{phase}' != required '{SAFETY_PHASE}'. "
            "Refusing to import."
        )


def risk_decision_exists(conn, risk_decision_id: str) -> bool:
    """Return True if a risk_decisions row exists for risk_decision_id."""
    row = conn.execute(
        "SELECT 1 FROM risk_decisions WHERE risk_decision_id = ? LIMIT 1",
        [risk_decision_id],
    ).fetchone()
    return row is not None


# ---------------------------------------------------------------------------
# Import planning + execution
# ---------------------------------------------------------------------------

def plan_import(rows: list, source_csv: str, imported_at) -> dict:
    """Validate + normalize all CSV rows into a write plan (no DB access).

    Returns a dict with the built risk_decisions rows and an aggregate count.
    Raises RiskDecisionValidationError on the first invalid row.
    """
    out_rows = []
    for index, row in enumerate(rows):
        validate_row(row, index)
        out_rows.append(build_risk_decision_row(row, source_csv, imported_at))
    return {"risk_decision_rows": out_rows, "row_count": len(out_rows)}


_RISK_DECISION_COLUMNS = (
    "risk_decision_id",
    "imported_at",
    "pair_key",
    "pair_label",
    "strategy_class_v2",
    "pair_status_v2",
    "test_lane",
    "live_eligibility",
    "required_capability",
    "risk_flag_count",
    "risk_flags",
    "risk_decision",
    "risk_action",
    "max_allowed_action",
    "risk_blockers",
    "risk_warnings",
    "risk_required_next_step",
    "risk_policy_reason",
    "safety_phase",
    "source_csv",
)


def _insert_risk_decision_row(conn, row: dict) -> None:
    placeholders = ", ".join(["?"] * len(_RISK_DECISION_COLUMNS))
    columns = ", ".join(_RISK_DECISION_COLUMNS)
    conn.execute(
        f"INSERT INTO risk_decisions ({columns}) VALUES ({placeholders})",
        [row[col] for col in _RISK_DECISION_COLUMNS],
    )


def import_risk_decisions(conn, plan: dict, upsert: bool) -> dict:
    """Apply a validated plan to the DB.

    Writes ONLY to risk_decisions. Never touches pipeline_runs, pipeline_steps,
    strategy_observations, risk_flags, or future_position_events.

    Without upsert: raises DuplicateRiskDecisionError if any risk_decision_id
    already exists (in the DB or duplicated within the batch); no writes occur.
    With upsert: replaces ONLY the affected risk_decision_id rows.
    """
    out_rows = plan["risk_decision_rows"]

    if not upsert:
        seen = set()
        for row in out_rows:
            rid = row["risk_decision_id"]
            if rid in seen:
                raise DuplicateRiskDecisionError(
                    f"risk_decision_id '{rid}' is duplicated within the input. "
                    "Re-run with --upsert to replace."
                )
            seen.add(rid)
            if risk_decision_exists(conn, rid):
                raise DuplicateRiskDecisionError(
                    f"risk_decision_id '{rid}' already exists in risk_decisions. "
                    "Re-run with --upsert to replace it."
                )

    written = 0
    replaced = 0
    for row in out_rows:
        rid = row["risk_decision_id"]
        if upsert and risk_decision_exists(conn, rid):
            conn.execute(
                "DELETE FROM risk_decisions WHERE risk_decision_id = ?", [rid]
            )
            replaced += 1
        _insert_risk_decision_row(conn, row)
        written += 1

    return {"rows_written": written, "rows_replaced": replaced}


# ---------------------------------------------------------------------------
# Orchestration (no DB writes happen in dry-run)
# ---------------------------------------------------------------------------

def run_import(
    db_path: str,
    risk_decisions_csv: str,
    dry_run: bool,
    upsert: bool,
) -> int:
    """Top-level flow used by the CLI. Returns a process exit code."""
    # --- File presence checks (never create DB or CSV) ---
    if not db_exists(db_path):
        print(
            "DuckDB database not found. Run scripts/init_runtime_db.py first.\n"
            f"  (looked for: {db_path})",
            file=sys.stderr,
        )
        return 2

    if not csv_exists(risk_decisions_csv):
        print(
            f"ERROR: Risk decisions CSV not found: {risk_decisions_csv}\n"
            "This importer does not create the CSV.",
            file=sys.stderr,
        )
        return 2

    # --- Load + validate rows (no DB access yet) ---
    imported_at = utc_now()
    try:
        _header, rows = load_risk_decisions(risk_decisions_csv)
        if not rows:
            print(
                "ERROR: Risk decisions CSV has no data rows (header only).",
                file=sys.stderr,
            )
            return 1
        plan = plan_import(rows, risk_decisions_csv, imported_at)
    except (RiskDecisionValidationError, FileNotFoundError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    # --- Open DB and validate schema + safety phase ---
    try:
        conn = connect_db(db_path)
    except RuntimeError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 3

    try:
        try:
            validate_schema_tables(conn)
            validate_db_safety_phase(conn)
        except (SchemaError, SafetyPhaseError) as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            return 1

        if dry_run:
            print("DRY RUN — no database writes will be performed.")
            print(f"  risk decisions CSV   : {risk_decisions_csv}")
            print(f"  rows read            : {len(rows)}")
            print(f"  rows to import       : {plan['row_count']}")
            print(f"  upsert               : {upsert}")
            print("  writes only to       : risk_decisions")
            print(f"  never writes to      : {', '.join(FORBIDDEN_WRITE_TABLES)}")
            print("DRY RUN COMPLETE — nothing written.")
            return 0

        try:
            result = import_risk_decisions(conn, plan, upsert=upsert)
        except DuplicateRiskDecisionError as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            return 1

        print(
            f"Imported {result['rows_written']} risk_decisions row(s) "
            f"({result['rows_replaced']} replaced)."
        )
        print("Wrote only to risk_decisions.")
        return 0
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args(argv=None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Risk Decisions Importer to DuckDB v0.1 — import an existing "
            "risk decisions CSV into the runtime DuckDB (risk_decisions only) "
            "as read-only metadata. Offline import only; no pipeline run, no "
            "network, no child processes, no scheduler, no Telegram, no "
            "positions, no signals, no wallet/signing/swap/LP/rebalance/live."
        )
    )
    parser.add_argument(
        "--db-path",
        default=DEFAULT_DB_PATH,
        help=f"Path to the existing DuckDB database file (default: {DEFAULT_DB_PATH}).",
    )
    parser.add_argument(
        "--risk-decisions-csv",
        default=DEFAULT_RISK_DECISIONS_CSV,
        help=(
            "Path to the risk decisions CSV produced by apply_risk_policy.py "
            f"(default: {DEFAULT_RISK_DECISIONS_CSV})."
        ),
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate DB, CSV, and rows; print counts; write nothing.",
    )
    parser.add_argument(
        "--upsert",
        action="store_true",
        help="Idempotently replace existing rows with the same risk_decision_id.",
    )
    return parser.parse_args(argv)


def print_safety_banner() -> None:
    print("------------------------------------------------------------")
    print("  RISK DECISIONS IMPORTER TO DUCKDB v0.1")
    print("------------------------------------------------------------")
    for line in SAFETY_BANNER.splitlines():
        print(f"  {line}")
    print("------------------------------------------------------------")


def main(argv=None) -> int:
    args = parse_args(argv)
    print_safety_banner()
    return run_import(
        db_path=args.db_path,
        risk_decisions_csv=args.risk_decisions_csv,
        dry_run=args.dry_run,
        upsert=args.upsert,
    )


if __name__ == "__main__":
    raise SystemExit(main())
