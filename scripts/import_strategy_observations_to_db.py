#!/usr/bin/env python3
"""
Strategy Observations Importer to DuckDB v0.1

Purpose:
- Import EXISTING strategy observation JSONL records (produced by
  scripts/observe_strategy.py) into the runtime DuckDB database
  (default: runtime/dlmm.duckdb).

This is an OFFLINE / IMPORT tool ONLY. It is a bookkeeper that copies observation
records from a JSONL history file into the strategy_observations table, and
(optionally) derives risk_flags rows from those records.

This script:
- Does NOT run the pipeline.
- Does NOT integrate with the runner (no runner integration yet).
- Does NOT spawn child processes.
- Does NOT access the network.
- Does NOT schedule anything (no cron / systemd) and does NOT talk to Telegram.
- Does NOT inspect wallets.
- Does NOT create the database (it requires an existing, initialized DB).
- Does NOT create the observations file (it requires an existing JSONL).
- Writes ONLY to strategy_observations and (only with --import-risk-flags) risk_flags.

It deliberately does NOT write:
- pipeline_runs
- pipeline_steps
- future_position_events

It deliberately does NOT:
- create paper positions
- generate ENTRY / EXIT / REBALANCE signals
- execute anything

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
import hashlib
import json
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
DEFAULT_OBSERVATIONS_JSONL = "data/observations/strategy_observations.jsonl"

# Source tag written into every derived risk_flags row.
RISK_FLAG_SOURCE = "strategy_observations_jsonl"

# Deterministic id prefixes.
OBSERVATION_ID_PREFIX = "obs_"
FLAG_ID_PREFIX = "flag_"

# Tables this importer requires to already exist in the target DB.
REQUIRED_SCHEMA_TABLES = (
    "runtime_schema_meta",
    "strategy_observations",
    "risk_flags",
)

# Tables this importer must NEVER write to in this phase.
FORBIDDEN_WRITE_TABLES = (
    "pipeline_runs",
    "pipeline_steps",
    "future_position_events",
)

# Canonical required fields of an observation record.
#
# observed_at is resolved via OBSERVED_AT_ALIASES below: the legacy
# observe_strategy.py JSONL writes "observed_at_utc", so either key satisfies it.
# observation_ready is treated as semi-optional: legacy snapshot records predate
# the field, so when absent it defaults to False (conservative — a single
# snapshot is never "ready"; readiness is a cross-run summary property). It is
# listed here for documentation of the canonical record shape.
REQUIRED_OBSERVATION_FIELDS = (
    "observed_at",
    "pair_key",
    "pair_label",
    "strategy_class_v2",
    "live_eligibility",
    "observation_ready",
)

# observed_at field name aliases, in priority order.
OBSERVED_AT_ALIASES = ("observed_at", "observed_at_utc")

# Fields that genuinely must be present (or, for observed_at, an alias) for a
# meaningful row. observation_ready is excluded: it is defaulted when absent.
HARD_REQUIRED_FIELDS = (
    "observed_at",
    "pair_key",
    "pair_label",
    "strategy_class_v2",
    "live_eligibility",
)

# Optional fields copied through when present.
OPTIONAL_OBSERVATION_FIELDS = (
    "run_id",
    "representative_pool_address",
    "pair_status_v2",
    "test_lane",
    "required_capability",
    "risk_flag_count",
    "risk_flags",
    "readiness_reason",
)

# Risk-flag severity mapping. Anything not listed maps to INFO.
RISK_FLAG_SEVERITY = {
    "MALFORMED_PAIR_LABEL": "SEVERE",
    "BLACKLISTED": "SEVERE",
    "NO_ELIGIBLE_FEE_POOL": "SEVERE",
    "LOW_LIQUIDITY": "HIGH",
    "LOW_VOLUME": "HIGH",
    "DATA_QUALITY_NA": "HIGH",
    "LOW_DATA_COMPLETENESS": "HIGH",
}
DEFAULT_SEVERITY = "INFO"

# A live_eligibility value must never assert live eligibility.
FORBIDDEN_LIVE_ELIGIBILITY_PREFIX = "LIVE_ELIGIBLE"


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class ObservationValidationError(ValueError):
    """Raised when an observation record is missing required fields/malformed."""


class SafetyPhaseError(ValueError):
    """Raised when the DB safety_phase does not match the required phase."""


class DuplicateObservationError(RuntimeError):
    """Raised when an observation_id already exists and --upsert was not given."""


class SchemaError(RuntimeError):
    """Raised when the target DB is missing one of the required schema tables."""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def utc_now_iso() -> str:
    """Return the current UTC time as an ISO-8601 string."""
    return datetime.now(timezone.utc).isoformat()


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


# ---------------------------------------------------------------------------
# File presence + JSONL loading
# ---------------------------------------------------------------------------

def db_exists(db_path: str) -> bool:
    """Return True only if db_path points to an existing regular file."""
    return Path(db_path).is_file()


def observations_exist(observations_jsonl: str) -> bool:
    """Return True only if observations_jsonl points to an existing file."""
    return Path(observations_jsonl).is_file()


def load_observations(observations_jsonl: str) -> list:
    """Load and parse the observation JSONL file into a list of dicts.

    Raises FileNotFoundError if the file is missing, ObservationValidationError
    if any line is unparseable or is not a JSON object.
    """
    path = Path(observations_jsonl)
    if not path.is_file():
        raise FileNotFoundError(f"Observations JSONL not found: {observations_jsonl}")

    records = []
    with path.open("r", encoding="utf-8") as fh:
        for line_no, line in enumerate(fh, start=1):
            s = line.strip()
            if not s:
                continue
            try:
                obj = json.loads(s)
            except ValueError as exc:
                raise ObservationValidationError(
                    f"Invalid JSON at {observations_jsonl}:{line_no}: {exc}"
                ) from exc
            if not isinstance(obj, dict):
                raise ObservationValidationError(
                    f"Observation at {observations_jsonl}:{line_no} must be a JSON "
                    f"object, got {type(obj).__name__}."
                )
            records.append(obj)
    return records


# ---------------------------------------------------------------------------
# Record validation + normalization
# ---------------------------------------------------------------------------

def resolve_observed_at(record: dict):
    """Return the observed_at value using the supported aliases, or None."""
    for key in OBSERVED_AT_ALIASES:
        value = record.get(key)
        if value not in (None, ""):
            return value
    return None


def validate_observation(record: dict, index: int) -> None:
    """Validate one observation record. Raises ObservationValidationError.

    Hard-required fields must be present and non-empty (observed_at via alias).
    observation_ready is not hard-required; it defaults to False when absent.
    live_eligibility may never assert any LIVE_ELIGIBLE_* capability.
    """
    if resolve_observed_at(record) is None:
        raise ObservationValidationError(
            f"Observation #{index} missing required field 'observed_at' "
            f"(or alias 'observed_at_utc')."
        )

    for field in HARD_REQUIRED_FIELDS:
        if field == "observed_at":
            continue
        value = record.get(field)
        if value is None or (isinstance(value, str) and not value.strip()):
            raise ObservationValidationError(
                f"Observation #{index} missing required field '{field}'."
            )

    live_eligibility = str(record.get("live_eligibility", ""))
    if live_eligibility.strip().upper().startswith(FORBIDDEN_LIVE_ELIGIBILITY_PREFIX):
        raise ObservationValidationError(
            f"Observation #{index} has forbidden live_eligibility "
            f"'{live_eligibility}'. Refusing to import (no LIVE_ELIGIBLE_*)."
        )


def parse_risk_flags(raw) -> list:
    """Parse the risk_flags field into a clean, ordered list of flag tokens.

    Accepts either a list of strings or a '|'-delimited string. The sentinel
    'none' and empty tokens are dropped. Order is preserved with duplicates
    removed.
    """
    if raw is None:
        return []
    if isinstance(raw, (list, tuple)):
        tokens = [str(x) for x in raw]
    else:
        tokens = str(raw).split("|")

    out = []
    seen = set()
    for token in tokens:
        flag = token.strip()
        if not flag or flag.lower() == "none":
            continue
        if flag in seen:
            continue
        seen.add(flag)
        out.append(flag)
    return out


def severity_for(flag: str) -> str:
    """Map a risk flag to its severity (INFO when not explicitly mapped)."""
    return RISK_FLAG_SEVERITY.get(flag, DEFAULT_SEVERITY)


def _coerce_bool(value) -> bool:
    """Coerce a JSON-ish value into a bool (strings like 'true'/'1' -> True)."""
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    if isinstance(value, (int, float)):
        return bool(value)
    return str(value).strip().lower() in {"true", "1", "yes", "y"}


def _coerce_optional_int(value):
    """Coerce a value into an int, or None when not convertible/absent."""
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        try:
            return int(float(value))
        except (TypeError, ValueError):
            return None


def compute_observation_id(record: dict) -> str:
    """Return the observation_id for a record.

    If the record already carries a non-empty observation_id, use it. Otherwise
    generate a deterministic id from observed_at + pair_key + strategy_class_v2 +
    live_eligibility.
    """
    existing = record.get("observation_id")
    if existing not in (None, ""):
        return str(existing)

    observed_at = str(resolve_observed_at(record) or "")
    return sha256_id(
        OBSERVATION_ID_PREFIX,
        observed_at,
        str(record.get("pair_key", "")),
        str(record.get("strategy_class_v2", "")),
        str(record.get("live_eligibility", "")),
    )


def build_observation_row(record: dict, now: str) -> dict:
    """Build the strategy_observations row dict from a validated record."""
    flags = parse_risk_flags(record.get("risk_flags"))
    risk_flag_count = _coerce_optional_int(record.get("risk_flag_count"))
    if risk_flag_count is None and record.get("risk_flags") is not None:
        risk_flag_count = len(flags)

    return {
        "observation_id": compute_observation_id(record),
        "run_id": record.get("run_id"),
        "observed_at": str(resolve_observed_at(record)),
        "pair_key": str(record["pair_key"]).strip(),
        "pair_label": str(record["pair_label"]).strip(),
        "representative_pool_address": record.get("representative_pool_address"),
        "strategy_class_v2": str(record["strategy_class_v2"]).strip(),
        "pair_status_v2": record.get("pair_status_v2"),
        "test_lane": record.get("test_lane"),
        "live_eligibility": str(record["live_eligibility"]).strip(),
        "required_capability": record.get("required_capability"),
        "risk_flag_count": risk_flag_count,
        "risk_flags": "|".join(flags) if flags else "none",
        "observation_ready": _coerce_bool(record.get("observation_ready")),
        "readiness_reason": record.get("readiness_reason"),
        "created_at": now,
    }


def build_risk_flag_rows(obs_row: dict, record: dict, now: str) -> list:
    """Build the risk_flags row dicts for one observation record.

    One row per distinct risk flag. flag_id is deterministic from the
    observation_id + the risk flag token.
    """
    rows = []
    for flag in parse_risk_flags(record.get("risk_flags")):
        rows.append(
            {
                "flag_id": sha256_id(
                    FLAG_ID_PREFIX, obs_row["observation_id"], flag
                ),
                "observed_at": obs_row["observed_at"],
                "pair_key": obs_row["pair_key"],
                "pair_label": obs_row["pair_label"],
                "risk_flag": flag,
                "severity": severity_for(flag),
                "source": RISK_FLAG_SOURCE,
                "created_at": now,
            }
        )
    return rows


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


def observation_exists(conn, observation_id: str) -> bool:
    """Return True if a strategy_observations row exists for observation_id."""
    row = conn.execute(
        "SELECT 1 FROM strategy_observations WHERE observation_id = ? LIMIT 1",
        [observation_id],
    ).fetchone()
    return row is not None


# ---------------------------------------------------------------------------
# Import planning + execution
# ---------------------------------------------------------------------------

def _insert_observation_row(conn, row: dict) -> None:
    conn.execute(
        "INSERT INTO strategy_observations "
        "(observation_id, run_id, observed_at, pair_key, pair_label, "
        "representative_pool_address, strategy_class_v2, pair_status_v2, "
        "test_lane, live_eligibility, required_capability, risk_flag_count, "
        "risk_flags, observation_ready, readiness_reason, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [
            row["observation_id"],
            row["run_id"],
            row["observed_at"],
            row["pair_key"],
            row["pair_label"],
            row["representative_pool_address"],
            row["strategy_class_v2"],
            row["pair_status_v2"],
            row["test_lane"],
            row["live_eligibility"],
            row["required_capability"],
            row["risk_flag_count"],
            row["risk_flags"],
            row["observation_ready"],
            row["readiness_reason"],
            row["created_at"],
        ],
    )


def _insert_risk_flag_row(conn, row: dict) -> None:
    conn.execute(
        "INSERT INTO risk_flags "
        "(flag_id, observed_at, pair_key, pair_label, risk_flag, severity, "
        "source, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        [
            row["flag_id"],
            row["observed_at"],
            row["pair_key"],
            row["pair_label"],
            row["risk_flag"],
            row["severity"],
            row["source"],
            row["created_at"],
        ],
    )


def _delete_risk_flags_for_observation(conn, obs_row: dict) -> None:
    """Delete previously generated risk_flags for one observation record only.

    Scoped by this importer's source plus the observation's (observed_at,
    pair_key) so unrelated records and other sources are never touched.
    """
    conn.execute(
        "DELETE FROM risk_flags "
        "WHERE source = ? AND observed_at = ? AND pair_key = ?",
        [RISK_FLAG_SOURCE, obs_row["observed_at"], obs_row["pair_key"]],
    )


def plan_import(records: list, now: str) -> dict:
    """Validate + normalize all records into a write plan (no DB access).

    Returns a dict with the observation rows, the per-observation risk-flag
    rows, and aggregate counts. Raises ObservationValidationError on the first
    invalid record.
    """
    obs_rows = []
    flag_rows_by_obs = []
    total_flags = 0
    for index, record in enumerate(records):
        validate_observation(record, index)
        obs_row = build_observation_row(record, now)
        flag_rows = build_risk_flag_rows(obs_row, record, now)
        obs_rows.append(obs_row)
        flag_rows_by_obs.append(flag_rows)
        total_flags += len(flag_rows)

    return {
        "observation_rows": obs_rows,
        "flag_rows_by_obs": flag_rows_by_obs,
        "observation_count": len(obs_rows),
        "risk_flag_count": total_flags,
    }


def import_observations(
    conn,
    plan: dict,
    upsert: bool,
    import_risk_flags: bool,
) -> dict:
    """Apply a validated plan to the DB.

    Writes ONLY to strategy_observations and (only with import_risk_flags)
    risk_flags. Never touches pipeline_runs, pipeline_steps, or
    future_position_events.

    Without upsert: raises DuplicateObservationError if any observation_id
    already exists (in the DB or duplicated within the batch); no writes occur.
    With upsert: replaces ONLY the affected observation_id rows (and, with
    import_risk_flags, that observation's generated risk_flags).
    """
    obs_rows = plan["observation_rows"]
    flag_rows_by_obs = plan["flag_rows_by_obs"]

    if not upsert:
        seen = set()
        for row in obs_rows:
            oid = row["observation_id"]
            if oid in seen:
                raise DuplicateObservationError(
                    f"observation_id '{oid}' is duplicated within the input. "
                    "Re-run with --upsert to replace."
                )
            seen.add(oid)
            if observation_exists(conn, oid):
                raise DuplicateObservationError(
                    f"observation_id '{oid}' already exists in "
                    "strategy_observations. Re-run with --upsert to replace it."
                )

    observations_written = 0
    observations_replaced = 0
    risk_flags_written = 0

    for obs_row, flag_rows in zip(obs_rows, flag_rows_by_obs):
        oid = obs_row["observation_id"]
        if upsert and observation_exists(conn, oid):
            conn.execute(
                "DELETE FROM strategy_observations WHERE observation_id = ?", [oid]
            )
            observations_replaced += 1

        _insert_observation_row(conn, obs_row)
        observations_written += 1

        if import_risk_flags:
            if upsert:
                _delete_risk_flags_for_observation(conn, obs_row)
            for flag_row in flag_rows:
                _insert_risk_flag_row(conn, flag_row)
                risk_flags_written += 1

    return {
        "observations_written": observations_written,
        "observations_replaced": observations_replaced,
        "risk_flags_written": risk_flags_written,
    }


# ---------------------------------------------------------------------------
# Orchestration (no DB writes happen in dry-run)
# ---------------------------------------------------------------------------

def run_import(
    db_path: str,
    observations_jsonl: str,
    dry_run: bool,
    upsert: bool,
    import_risk_flags: bool,
) -> int:
    """Top-level flow used by the CLI. Returns a process exit code."""
    # --- File presence checks (never create DB or JSONL) ---
    if not db_exists(db_path):
        print(
            "DuckDB database not found. Run scripts/init_runtime_db.py first.\n"
            f"  (looked for: {db_path})",
            file=sys.stderr,
        )
        return 2

    if not observations_exist(observations_jsonl):
        print(
            f"ERROR: Observations JSONL not found: {observations_jsonl}\n"
            "This importer does not create the observations file.",
            file=sys.stderr,
        )
        return 2

    # --- Load + validate records (no DB access yet) ---
    now = utc_now_iso()
    try:
        records = load_observations(observations_jsonl)
        plan = plan_import(records, now)
    except (ObservationValidationError, FileNotFoundError) as exc:
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
            print(f"  observations file       : {observations_jsonl}")
            print(f"  records read            : {len(records)}")
            print(f"  observations to import  : {plan['observation_count']}")
            print(f"  risk flags parsed       : {plan['risk_flag_count']}")
            if import_risk_flags:
                print(
                    "  risk flags to import    : "
                    f"{plan['risk_flag_count']} (--import-risk-flags set)"
                )
            else:
                print(
                    "  risk flags to import    : 0 "
                    "(--import-risk-flags NOT set)"
                )
            print(f"  upsert                  : {upsert}")
            print("  writes only to          : strategy_observations"
                  + (", risk_flags" if import_risk_flags else ""))
            print(f"  never writes to         : {', '.join(FORBIDDEN_WRITE_TABLES)}")
            print("DRY RUN COMPLETE — nothing written.")
            return 0

        try:
            result = import_observations(
                conn, plan, upsert=upsert, import_risk_flags=import_risk_flags
            )
        except DuplicateObservationError as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            return 1

        print(
            f"Imported {result['observations_written']} strategy_observations "
            f"row(s) ({result['observations_replaced']} replaced)."
        )
        if import_risk_flags:
            print(f"Imported {result['risk_flags_written']} risk_flags row(s).")
            print("Wrote only to strategy_observations and risk_flags.")
        else:
            print("Wrote only to strategy_observations (risk_flags not imported).")
        return 0
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args(argv=None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Strategy Observations Importer to DuckDB v0.1 — import existing "
            "observation JSONL records into the runtime DuckDB "
            "(strategy_observations, and optionally risk_flags). Offline import "
            "only; no pipeline run, no network, no child processes, no "
            "scheduler, no Telegram, no paper positions, no signals, no "
            "wallet/signing/swap/LP/rebalance/live."
        )
    )
    parser.add_argument(
        "--db-path",
        default=DEFAULT_DB_PATH,
        help=f"Path to the existing DuckDB database file (default: {DEFAULT_DB_PATH}).",
    )
    parser.add_argument(
        "--observations-jsonl",
        default=DEFAULT_OBSERVATIONS_JSONL,
        help=(
            "Path to the observation JSONL produced by observe_strategy.py "
            f"(default: {DEFAULT_OBSERVATIONS_JSONL})."
        ),
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate DB, file, and records; print counts; write nothing.",
    )
    parser.add_argument(
        "--upsert",
        action="store_true",
        help="Idempotently replace existing rows with the same observation_id.",
    )
    parser.add_argument(
        "--import-risk-flags",
        action="store_true",
        help="Also derive and import risk_flags rows from each observation.",
    )
    return parser.parse_args(argv)


def print_safety_banner() -> None:
    print("------------------------------------------------------------")
    print("  STRATEGY OBSERVATIONS IMPORTER TO DUCKDB v0.1")
    print("------------------------------------------------------------")
    for line in SAFETY_BANNER.splitlines():
        print(f"  {line}")
    print("------------------------------------------------------------")


def main(argv=None) -> int:
    args = parse_args(argv)
    print_safety_banner()
    return run_import(
        db_path=args.db_path,
        observations_jsonl=args.observations_jsonl,
        dry_run=args.dry_run,
        upsert=args.upsert,
        import_risk_flags=args.import_risk_flags,
    )


if __name__ == "__main__":
    raise SystemExit(main())
