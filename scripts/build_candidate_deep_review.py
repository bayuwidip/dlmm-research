#!/usr/bin/env python3
"""Candidate Deep Review Report v0.1.

Purpose:
- Read an EXISTING runtime DuckDB database and write a read-only Markdown + CSV
  report for stable review candidates that may merit human/council review for
  future paper-simulation design consideration.

This is READ-ONLY HISTORICAL REPORTING ONLY. It is a reporting layer over the
runtime history tables and nothing more.

This script:
- Opens an EXISTING database in read-only mode only.
- Does NOT write to the database.
- Does NOT initialize or create the schema.
- Does NOT create the runtime directory or the database file.
- Does NOT run the pipeline, call other report builders, or access the network.
- Reads the future_position_events COUNT only. A non-zero count is a HARD SAFETY
  VIOLATION: the process writes NO report and exits non-zero.

This is NOT and never enables:
- wallet creation / import / management
- private key or seed phrase handling
- transaction signing
- swap execution
- LP add / remove
- rebalance
- live execution
- any LIVE_ELIGIBLE_* capability
- signal generation
- paper position creation
- threshold / risk-policy / candidate-status changes
"""

from __future__ import annotations

import argparse
import csv
import sys
from datetime import datetime, timezone
from pathlib import Path


SAFETY_PHASE = "READ_ONLY / RESEARCH_ONLY / SCREENING_ONLY / PAPER_ONLY"

SAFETY_BANNER = "\n".join(
    [
        "READ_ONLY / RESEARCH_ONLY / SCREENING_ONLY / PAPER_ONLY",
        "No wallet",
        "No private key",
        "No seed phrase",
        "No signing",
        "No swap",
        "No LP add/remove",
        "No rebalance",
        "No live execution",
        "No LIVE_ELIGIBLE_*",
    ]
)

SAFETY_BOUNDARY_LINES = (
    "No wallet",
    "No private key",
    "No seed phrase",
    "No signing",
    "No swap",
    "No LP add/remove",
    "No rebalance",
    "No live execution",
    "No LIVE_ELIGIBLE_*",
    "No signal generation",
    "No paper position creation",
    "No future_position_events writes",
    "No threshold changes",
    "No risk-policy changes",
    "No candidate-status changes",
)

REVIEW_PHRASE = (
    "human/council may review for future paper-simulation design consideration"
)

DIAGNOSTIC_NOTICE = (
    "This is a diagnostic-only report. STABLE_REVIEW_CANDIDATE does not mean "
    "paper entry. It means only that a human/council may review for future "
    "paper-simulation design consideration."
)

FORBIDDEN_NOTICE = (
    "This report does not authorize paper entry, paper trade, open position, "
    "signal, wallet use, signing, swap, LP add/remove, rebalance, or live "
    "execution."
)

DUCKDB_MISSING_MSG = (
    "duckdb package is required. Install with: python3 -m pip install duckdb"
)

DATA_NOT_AVAILABLE = "DATA_NOT_AVAILABLE"

DEFAULT_DB_PATH = "runtime/dlmm.duckdb"
DEFAULT_OUT_MD = "reports/runtime/candidate_deep_review.md"
DEFAULT_OUT_CSV = "reports/runtime/candidate_deep_review.csv"
DEFAULT_LIMIT = 20
DEFAULT_MIN_RUNS = 5

DECISION_PAPER_REVIEW = "PAPER_REVIEW_CANDIDATE"
MAX_FUTURE_PAPER_REVIEW = "FUTURE_PAPER_SIMULATION_REVIEW"

REVIEW_SHORTLIST = "REVIEW_SHORTLIST"
NEEDS_TOKEN_POOL_VALIDATION = "NEEDS_TOKEN_POOL_VALIDATION"
NEEDS_LIQUIDITY_REVIEW = "NEEDS_LIQUIDITY_REVIEW"
NEEDS_VOLATILITY_REVIEW = "NEEDS_VOLATILITY_REVIEW"
NEEDS_DATA_QUALITY_REVIEW = "NEEDS_DATA_QUALITY_REVIEW"
SAFETY_REVIEW_ONLY = "SAFETY_REVIEW_ONLY"

CANDIDATE_PRIORITY = {
    "USDC-SOL": 0,
    "JUP-SOL": 1,
    "USDC-cbBTC": 2,
    "HYPE-USDC": 3,
    "HYPE-SOL": 4,
    "TRUMP-USDC": 5,
}

DEFAULT_NOTES = {
    "USDC-SOL": (
        "Benchmark/reference candidate; still requires human/council review.",
        REVIEW_SHORTLIST,
    ),
    "JUP-SOL": (
        "Solana ecosystem candidate; review liquidity, volatility, and data "
        "consistency.",
        NEEDS_LIQUIDITY_REVIEW,
    ),
    "USDC-cbBTC": (
        "Review wrapped/bridged BTC assumptions, liquidity, data source, and "
        "pool quality.",
        NEEDS_DATA_QUALITY_REVIEW,
    ),
    "HYPE-USDC": (
        "Validate token identity, pool quality, liquidity, and volatility.",
        NEEDS_TOKEN_POOL_VALIDATION,
    ),
    "HYPE-SOL": (
        "Validate token identity, pool quality, liquidity, and volatility.",
        NEEDS_TOKEN_POOL_VALIDATION,
    ),
    "TRUMP-USDC": (
        "Narrative/meme/political-risk sensitive; requires extra volatility "
        "and event-risk review.",
        NEEDS_VOLATILITY_REVIEW,
    ),
}

OPTIONAL_TABLES = (
    "pipeline_runs",
    "strategy_observations",
    "risk_flags",
    "risk_decisions",
    "future_position_events",
)

CSV_COLUMNS = (
    "pair_key",
    "pair_label",
    "observation_count",
    "distinct_run_count",
    "first_seen_at",
    "last_seen_at",
    "strategy_class_history",
    "lane_history",
    "strategy_class_change_count",
    "lane_change_count",
    "latest_strategy_class",
    "latest_lane",
    "latest_risk_decision",
    "latest_risk_action",
    "latest_max_allowed_action",
    "risk_flags",
    "risk_flag_count",
    "blocker_history",
    "blocker_count",
    "ohlcv_data_notes",
    "liquidity_volume_volatility_notes",
    "data_gaps",
    "manual_review_notes",
    "suggested_human_council_questions",
    "diagnostic_status",
)


def require_duckdb():
    """Import and return duckdb, or raise a clear dependency error."""
    try:
        import duckdb  # noqa: PLC0415
    except ImportError as exc:
        raise RuntimeError(DUCKDB_MISSING_MSG) from exc
    return duckdb


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def db_exists(db_path: str) -> bool:
    return Path(db_path).is_file()


def open_readonly(db_path: str):
    duckdb = require_duckdb()
    return duckdb.connect(str(db_path), read_only=True)


def list_tables(conn):
    rows = conn.execute(
        "SELECT table_name FROM information_schema.tables WHERE table_schema = 'main'"
    ).fetchall()
    return {row[0] for row in rows}


def _rows(conn, sql: str, params=None):
    return conn.execute(sql, params or []).fetchall()


def table_count(conn, name: str) -> int:
    return conn.execute(f"SELECT COUNT(*) FROM {name}").fetchone()[0]


def _clean(value) -> str:
    return "" if value is None else str(value).strip()


def _join_or_na(values) -> str:
    cleaned = sorted({v for v in (_clean(x) for x in values) if v})
    return "|".join(cleaned) if cleaned else DATA_NOT_AVAILABLE


def _minmax_or_na(values):
    cleaned = sorted(v for v in (_clean(x) for x in values) if v)
    if not cleaned:
        return DATA_NOT_AVAILABLE, DATA_NOT_AVAILABLE
    return cleaned[0], cleaned[-1]


def _transitions(seq) -> int:
    cleaned = [v for v in (_clean(x) for x in seq) if v]
    return sum(1 for i in range(1, len(cleaned)) if cleaned[i] != cleaned[i - 1])


def gather_observation_rows(conn, present):
    if "strategy_observations" not in present:
        return None
    return _rows(
        conn,
        "SELECT pair_key, pair_label, run_id, strategy_class_v2, test_lane, "
        "observed_at, observation_id FROM strategy_observations",
    )


def gather_flag_rows(conn, present):
    if "risk_flags" not in present:
        return None
    return _rows(
        conn,
        "SELECT pair_key, pair_label, risk_flag, observed_at, flag_id "
        "FROM risk_flags",
    )


def gather_decision_rows(conn, present):
    if "risk_decisions" not in present:
        return None
    return _rows(
        conn,
        "SELECT pair_key, pair_label, risk_decision, risk_action, "
        "max_allowed_action, risk_blockers, risk_warnings, "
        "CAST(imported_at AS VARCHAR) AS imported_at, risk_decision_id "
        "FROM risk_decisions",
    )


def _new_pair():
    return {
        "labels": [],
        "samples": [],
        "run_ids": [],
        "obs_times": [],
        "flags": [],
        "flag_times": [],
        "blockers": [],
        "decisions": [],
        "dec_times": [],
    }


def _latest_decision(rec):
    if not rec["decisions"]:
        return (DATA_NOT_AVAILABLE, DATA_NOT_AVAILABLE, DATA_NOT_AVAILABLE)
    latest = max(rec["decisions"], key=lambda d: d[0])
    return (
        latest[1] or DATA_NOT_AVAILABLE,
        latest[2] or DATA_NOT_AVAILABLE,
        latest[3] or DATA_NOT_AVAILABLE,
    )


def _latest_observation(rec):
    if not rec["samples"]:
        return (DATA_NOT_AVAILABLE, DATA_NOT_AVAILABLE)
    latest = max(rec["samples"], key=lambda s: (_clean(s[0]), _clean(s[1])))
    return (
        _clean(latest[2]) or DATA_NOT_AVAILABLE,
        _clean(latest[3]) or DATA_NOT_AVAILABLE,
    )


def _default_note_and_status(pair_label: str):
    if pair_label in DEFAULT_NOTES:
        return DEFAULT_NOTES[pair_label]
    return (
        "Review token identity, pool quality, liquidity, volatility, and data "
        "consistency before any future design consideration.",
        SAFETY_REVIEW_ONLY,
    )


def _is_candidate(rec) -> bool:
    latest_decision, _, latest_max = _latest_decision(rec)
    if latest_decision != DECISION_PAPER_REVIEW:
        return False
    if latest_max != MAX_FUTURE_PAPER_REVIEW:
        return False

    if not rec["samples"]:
        return True

    ordered = sorted(rec["samples"], key=lambda s: (_clean(s[0]), _clean(s[1])))
    classes = {_clean(s[2]) for s in ordered if _clean(s[2])}
    lanes = {_clean(s[3]) for s in ordered if _clean(s[3])}
    stable_class = _transitions(s[2] for s in ordered) == 0
    stable_lane = _transitions(s[3] for s in ordered) == 0
    return classes == {"CORE"} and lanes == {"CLEAN"} and stable_class and stable_lane


def aggregate_candidates(observation_rows, flag_rows, decision_rows, limit):
    observation_rows = observation_rows or []
    flag_rows = flag_rows or []
    decision_rows = decision_rows or []

    pairs = {}

    def _pair(pk):
        return pairs.setdefault(pk, _new_pair())

    for pair_key, pair_label, run_id, cls, lane, observed_at, obs_id in observation_rows:
        pk = _clean(pair_key)
        if not pk:
            continue
        rec = _pair(pk)
        rec["labels"].append(pair_label)
        rec["samples"].append((observed_at, obs_id, cls, lane))
        rec["run_ids"].append(run_id)
        rec["obs_times"].append(observed_at)

    for pair_key, pair_label, risk_flag, observed_at, flag_id in flag_rows:
        pk = _clean(pair_key)
        if not pk:
            continue
        rec = _pair(pk)
        rec["labels"].append(pair_label)
        rec["flags"].append(risk_flag)
        rec["flag_times"].append(observed_at)

    for (pair_key, pair_label, decision, action, max_action, blockers, warnings,
         imported_at, decision_id) in decision_rows:
        pk = _clean(pair_key)
        if not pk:
            continue
        rec = _pair(pk)
        rec["labels"].append(pair_label)
        rec["dec_times"].append(imported_at)
        sort_key = (_clean(imported_at), _clean(decision_id))
        rec["decisions"].append(
            (sort_key, _clean(decision), _clean(action), _clean(max_action))
        )
        for raw in (_clean(blockers), _clean(warnings)):
            if raw:
                rec["blockers"].extend(x.strip() for x in raw.split("|") if x.strip())

    records = []
    for pk, rec in pairs.items():
        if not _is_candidate(rec):
            continue

        labels = sorted({_clean(x) for x in rec["labels"] if _clean(x)})
        pair_label = labels[0] if labels else DATA_NOT_AVAILABLE
        ordered = sorted(rec["samples"], key=lambda s: (_clean(s[0]), _clean(s[1])))
        latest_class, latest_lane = _latest_observation(rec)
        latest_decision, latest_action, latest_max = _latest_decision(rec)
        run_ids = {_clean(r) for r in rec["run_ids"] if _clean(r)}
        first_seen, last_seen = _minmax_or_na(
            list(rec["obs_times"]) + list(rec["flag_times"]) + list(rec["dec_times"])
        )
        manual_note, status = _default_note_and_status(pair_label)

        data_gaps = []
        if not observation_rows:
            data_gaps.append("strategy_observations table missing or empty")
        if not flag_rows:
            data_gaps.append("risk_flags table missing or empty")
        if not decision_rows:
            data_gaps.append("risk_decisions table missing or empty")

        questions = (
            "Does the source data confirm token identity and pool quality? "
            "Are liquidity, volume, and volatility stable enough for future "
            "paper-simulation design review? Are risk blockers absent or fully "
            "explained?"
        )

        records.append(
            {
                "pair_key": pk,
                "pair_label": pair_label,
                "observation_count": len(rec["samples"]),
                "distinct_run_count": len(run_ids) if run_ids else DATA_NOT_AVAILABLE,
                "first_seen_at": first_seen,
                "last_seen_at": last_seen,
                "strategy_class_history": _join_or_na(s[2] for s in ordered),
                "lane_history": _join_or_na(s[3] for s in ordered),
                "strategy_class_change_count": _transitions(s[2] for s in ordered),
                "lane_change_count": _transitions(s[3] for s in ordered),
                "latest_strategy_class": latest_class,
                "latest_lane": latest_lane,
                "latest_risk_decision": latest_decision,
                "latest_risk_action": latest_action,
                "latest_max_allowed_action": latest_max,
                "risk_flags": _join_or_na(rec["flags"]),
                "risk_flag_count": len(rec["flags"]),
                "blocker_history": _join_or_na(rec["blockers"]),
                "blocker_count": len([b for b in rec["blockers"] if _clean(b)]),
                "ohlcv_data_notes": (
                    "Review OHLCV freshness and continuity from existing history; "
                    "this report performs no data fetch."
                ),
                "liquidity_volume_volatility_notes": (
                    "Review liquidity, volume, volatility, and pool quality by "
                    "hand before any future design consideration."
                ),
                "data_gaps": "; ".join(data_gaps) if data_gaps else "No missing optional history table detected.",
                "manual_review_notes": manual_note,
                "suggested_human_council_questions": questions,
                "diagnostic_status": status,
            }
        )

    records.sort(
        key=lambda r: (
            CANDIDATE_PRIORITY.get(r["pair_label"], 999),
            r["pair_label"],
            r["pair_key"],
        )
    )

    if limit is not None:
        records = records[:limit]

    return records


def build_diagnostics(conn, present, limit: int, min_runs: int) -> dict:
    fpe_present = "future_position_events" in present
    fpe_count = table_count(conn, "future_position_events") if fpe_present else None
    fpe_violation = bool(fpe_present and fpe_count and fpe_count > 0)

    run_present = "pipeline_runs" in present
    run_count = table_count(conn, "pipeline_runs") if run_present else None

    observation_rows = gather_observation_rows(conn, present)
    flag_rows = gather_flag_rows(conn, present)
    decision_rows = gather_decision_rows(conn, present)
    records = aggregate_candidates(observation_rows, flag_rows, decision_rows, limit)

    observed_run_ids = set()
    for row in observation_rows or []:
        rid = _clean(row[2])
        if rid:
            observed_run_ids.add(rid)

    evidence_runs = max(run_count or 0, len(observed_run_ids))

    return {
        "fpe_present": fpe_present,
        "fpe_count": fpe_count,
        "fpe_violation": fpe_violation,
        "run_present": run_present,
        "run_count": run_count,
        "observations_present": observation_rows is not None,
        "flags_present": flag_rows is not None,
        "decisions_present": decision_rows is not None,
        "distinct_observed_runs": len(observed_run_ids),
        "evidence_runs": evidence_runs,
        "evidence_sufficient": evidence_runs >= min_runs,
        "min_runs": min_runs,
        "records": records,
    }


def _md_cell(value) -> str:
    s = "" if value is None else str(value)
    return s.replace("|", "\\|").replace("\n", " ")


def md_table(headers, rows) -> list:
    if not rows:
        return ["_(no rows)_"]
    lines = ["| " + " | ".join(str(h) for h in headers) + " |"]
    lines.append("| " + " | ".join("---" for _ in headers) + " |")
    for row in rows:
        lines.append("| " + " | ".join(_md_cell(c) for c in row) + " |")
    return lines


def section(lines: list, title: str) -> None:
    lines.append("")
    lines.append(f"## {title}")
    lines.append("")


def _present_note(flag) -> str:
    return "" if flag else " _(table missing - reported as no data)_"


def render_markdown(diag: dict, db_path: str, limit: int) -> str:
    records = diag["records"]
    lines = []
    lines.append("# Candidate Deep Review Report v0.1")
    lines.append("")
    lines.append(f"- generated_at (UTC): {utc_now_iso()}")
    lines.append(f"- safety_phase: {SAFETY_PHASE}")
    lines.append(f"- database path: {db_path}")
    lines.append(f"- candidate limit: {limit}")
    lines.append(f"- min_runs (evidence threshold): {diag['min_runs']}")
    lines.append("")
    lines.append(DIAGNOSTIC_NOTICE)
    lines.append(FORBIDDEN_NOTICE)

    section(lines, "Safety Boundary")
    for line in SAFETY_BOUNDARY_LINES:
        lines.append(f"- {line}")
    lines.append("")
    lines.append(
        "The Risk Policy Engine has veto / reporting authority only - no "
        "execution authority."
    )

    section(lines, "Summary")
    run_count = diag["run_count"] if diag["run_present"] else DATA_NOT_AVAILABLE
    fpe_count = diag["fpe_count"] if diag["fpe_present"] else DATA_NOT_AVAILABLE
    lines.append(
        f"- pipeline run count: {run_count}{_present_note(diag['run_present'])}"
    )
    lines.append(
        f"- distinct runs in observation history: {diag['distinct_observed_runs']}"
        f"{_present_note(diag['observations_present'])}"
    )
    lines.append(
        f"- future_position_events count: {fpe_count} (expected 0)"
        f"{_present_note(diag['fpe_present'])}"
    )
    lines.append(f"- candidate count: {len(records)}")
    if not diag["flags_present"]:
        lines.append("- risk_flags: _table missing - flag context reported as no data_")
    if not diag["decisions_present"]:
        lines.append(
            "- risk_decisions: _table missing - decision context reported as no data_"
        )

    if diag["evidence_sufficient"]:
        lines.append(
            f"- evidence sufficiency: SUFFICIENT - {diag['evidence_runs']} run(s) "
            f">= min_runs ({diag['min_runs']})."
        )
    else:
        lines.append(
            f"- evidence sufficiency: INSUFFICIENT - only {diag['evidence_runs']} "
            f"run(s) available, below min_runs ({diag['min_runs']}). This report "
            "remains review-only."
        )

    section(lines, "Candidate Shortlist")
    rows = [
        (
            r["pair_label"],
            r["pair_key"],
            r["observation_count"],
            r["distinct_run_count"],
            r["latest_risk_decision"],
            r["latest_max_allowed_action"],
            r["diagnostic_status"],
            r["manual_review_notes"],
        )
        for r in records
    ]
    lines.extend(
        md_table(
            (
                "pair_label",
                "pair_key",
                "observation_count",
                "distinct_run_count",
                "latest_risk_decision",
                "latest_max_allowed_action",
                "diagnostic_status",
                "manual_review_notes",
            ),
            rows,
        )
    )

    for r in records:
        section(lines, f"Candidate: {r['pair_label']}")
        lines.append(f"- pair_key: {r['pair_key']}")
        lines.append(f"- latest_strategy_class: {r['latest_strategy_class']}")
        lines.append(f"- latest_lane: {r['latest_lane']}")
        lines.append(f"- strategy_class_history: {r['strategy_class_history']}")
        lines.append(f"- lane_history: {r['lane_history']}")
        lines.append(f"- latest_risk_decision: {r['latest_risk_decision']}")
        lines.append(f"- latest_risk_action: {r['latest_risk_action']}")
        lines.append(f"- latest_max_allowed_action: {r['latest_max_allowed_action']}")
        lines.append(f"- risk_flags: {r['risk_flags']}")
        lines.append(f"- blocker_history: {r['blocker_history']}")
        lines.append(f"- ohlcv_data_notes: {r['ohlcv_data_notes']}")
        lines.append(
            "- liquidity_volume_volatility_notes: "
            f"{r['liquidity_volume_volatility_notes']}"
        )
        lines.append(f"- data_gaps: {r['data_gaps']}")
        lines.append(f"- manual_review_notes: {r['manual_review_notes']}")
        lines.append(
            "- suggested_human_council_questions: "
            f"{r['suggested_human_council_questions']}"
        )
        lines.append(f"- diagnostic_status: {r['diagnostic_status']}")
        lines.append(f"- review_scope: {REVIEW_PHRASE}.")

    section(lines, "Risk/Data Quality Summary")
    lines.append(
        "Candidates are included only for diagnostic review from existing "
        "runtime history. Token identity, pool quality, liquidity, volume, "
        "volatility, blockers, warnings, and data gaps must be checked by hand."
    )
    lines.append("No threshold, risk-policy, or candidate-status change is made.")

    section(lines, "Human/Council Review Questions")
    lines.append(
        "- Does the existing history support the stable CORE/CLEAN pattern for "
        "each candidate?"
    )
    lines.append(
        "- Are token identity, pool quality, liquidity, volume, volatility, and "
        "data-source assumptions acceptable for future design review?"
    )
    lines.append(
        "- Are any risk flags, blockers, warnings, or data gaps unresolved?"
    )
    lines.append(f"- Is the candidate still limited to this scope: {REVIEW_PHRASE}?")
    lines.append("")
    lines.append(FORBIDDEN_NOTICE)

    return "\n".join(lines) + "\n"


def write_csv(path: Path, records) -> None:
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(CSV_COLUMNS)
        for r in records:
            writer.writerow([r[col] for col in CSV_COLUMNS])


def print_safety_banner() -> None:
    print("------------------------------------------------------------")
    print("  CANDIDATE DEEP REVIEW REPORT v0.1")
    print("------------------------------------------------------------")
    for line in SAFETY_BANNER.splitlines():
        print(f"  {line}")
    print("------------------------------------------------------------")


def run_report(
    db_path: str,
    out_md: str,
    out_csv: str,
    limit: int,
    min_runs: int,
    dry_run: bool,
) -> int:
    try:
        require_duckdb()
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 3

    if not db_exists(db_path):
        print(
            f"ERROR: Runtime DuckDB not found: {db_path}\n"
            "This report does not create or initialize the database.",
            file=sys.stderr,
        )
        return 2

    conn = open_readonly(db_path)
    try:
        present = list_tables(conn)
        diag = build_diagnostics(conn, present, limit, min_runs)
    finally:
        conn.close()

    if diag["fpe_violation"]:
        print(
            "HARD SAFETY VIOLATION: future_position_events count = "
            f"{diag['fpe_count']} (expected 0). No report written.",
            file=sys.stderr,
        )
        return 4

    if dry_run:
        print("DRY RUN - no Markdown or CSV files will be written.")
        print(f"  database read   : {db_path}")
        print(f"  would write md  : {out_md}")
        print(f"  would write csv : {out_csv} ({len(diag['records'])} rows)")
        print(f"  pipeline runs   : {diag['run_count']}")
        print(
            "  future_position_events count: "
            f"{diag['fpe_count']} (expected 0)"
        )
        print(
            "  evidence          : "
            + ("SUFFICIENT" if diag["evidence_sufficient"] else "INSUFFICIENT")
            + f" ({diag['evidence_runs']} run(s) vs min_runs {diag['min_runs']})"
        )
        print(f"  candidate count  : {len(diag['records'])}")
        print("DRY RUN COMPLETE - nothing written.")
        return 0

    md = render_markdown(diag, db_path, limit)
    md_path = Path(out_md)
    md_path.parent.mkdir(parents=True, exist_ok=True)
    md_path.write_text(md, encoding="utf-8")
    print(f"Wrote Markdown report: {md_path}")

    csv_path = Path(out_csv)
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    write_csv(csv_path, diag["records"])
    print(f"Wrote CSV report: {csv_path} ({len(diag['records'])} rows)")

    print(f"future_position_events count: {diag['fpe_count']} (expected 0)")
    print(DIAGNOSTIC_NOTICE)
    return 0


def parse_args(argv=None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Candidate Deep Review Report v0.1 - read an existing runtime "
            "DuckDB database and write a diagnostic-only Markdown + CSV report "
            "for future paper-simulation design review candidates. Read-only; "
            "never writes the DB, never initializes schema, no pipeline run, no "
            "network, no positions, no wallet/signing/swap/LP/rebalance/live, "
            "no threshold/risk-policy/candidate-status changes."
        )
    )
    parser.add_argument("--db-path", default=DEFAULT_DB_PATH)
    parser.add_argument("--out-md", default=DEFAULT_OUT_MD)
    parser.add_argument("--out-csv", default=DEFAULT_OUT_CSV)
    parser.add_argument("--limit", type=int, default=DEFAULT_LIMIT, metavar="N")
    parser.add_argument("--min-runs", type=int, default=DEFAULT_MIN_RUNS, metavar="N")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate DB and report what would be written; write nothing.",
    )
    return parser.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)
    print_safety_banner()
    limit = args.limit if args.limit is not None and args.limit >= 0 else None
    return run_report(
        db_path=args.db_path,
        out_md=args.out_md,
        out_csv=args.out_csv,
        limit=limit,
        min_runs=args.min_runs,
        dry_run=args.dry_run,
    )


if __name__ == "__main__":
    raise SystemExit(main())
