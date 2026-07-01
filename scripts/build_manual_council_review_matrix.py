#!/usr/bin/env python3
"""Manual Council Review Matrix v0.1.

Read an existing runtime DuckDB database and write a diagnostic-only Manual
Council Review Matrix for the stable review candidates. For each candidate the
matrix lists the manual review dimensions, the manual review questions the human
/ council must answer, and a runtime evidence hint. Every manual answer starts as
PENDING_MANUAL_REVIEW.

This report is read-only. It does NOT change candidate status, does NOT change
risk policy or thresholds, and does NOT write DuckDB (including
future_position_events). It only structures what a human / council must review
by hand before any future paper-simulation design consideration.
"""

from __future__ import annotations

import argparse
import csv
import sys
from datetime import datetime, timezone
from pathlib import Path


SAFETY_PHASE = "READ_ONLY / RESEARCH_ONLY / SCREENING_ONLY / PAPER_ONLY"
REVIEW_PHRASE = (
    "human/council may review for future paper-simulation design consideration"
)
DUCKDB_MISSING_MSG = (
    "duckdb package is required. Install with: python3 -m pip install duckdb"
)

DEFAULT_DB_PATH = "runtime/dlmm.duckdb"
DEFAULT_OUT_MD = "reports/runtime/manual_council_review_matrix.md"
DEFAULT_OUT_CSV = "reports/runtime/manual_council_review_matrix.csv"
DEFAULT_LIMIT = 20
DEFAULT_MIN_RUNS = 5

DECISION_PAPER_REVIEW = "PAPER_REVIEW_CANDIDATE"
MAX_FUTURE_PAPER_REVIEW = "FUTURE_PAPER_SIMULATION_REVIEW"

EVIDENCE_PRESENT = "EVIDENCE_PRESENT"
NO_RUNTIME_FLAG_FOUND = "NO_RUNTIME_FLAG_FOUND"
MANUAL_ONLY = "MANUAL_ONLY"
NOT_AVAILABLE = "NOT_AVAILABLE"

# Every manual answer starts pending. This report never resolves a manual
# question and never changes candidate status.
PENDING_MANUAL_REVIEW = "PENDING_MANUAL_REVIEW"
NO_CHANGE = "NO_CHANGE"

CANDIDATE_PRIORITY = {
    "USDC-SOL": 0,
    "JUP-SOL": 1,
    "USDC-cbBTC": 2,
    "HYPE-USDC": 3,
    "HYPE-SOL": 4,
    "TRUMP-USDC": 5,
}

# Candidate-specific narrative / event / political-risk question text. Used for
# the NARRATIVE_EVENT_RISK dimension only. All wording stays diagnostic.
CANDIDATE_NARRATIVE = {
    "USDC-SOL": (
        "Benchmark/reference pair: is it still a fair baseline, and are USDC and "
        "SOL identity/depth assumptions still current?"
    ),
    "JUP-SOL": (
        "Solana ecosystem asset: are JUP tokenomics, unlocks, and ecosystem "
        "events understood for this pair?"
    ),
    "USDC-cbBTC": (
        "Wrapped/bridged BTC exposure: are the cbBTC issuer/bridge assumptions, "
        "peg risk, and data source verified?"
    ),
    "HYPE-USDC": (
        "Token identity/pool quality validation required: is the HYPE mint the "
        "intended asset and not a look-alike, and is the pool legitimate?"
    ),
    "HYPE-SOL": (
        "Token identity/pool quality validation required: is the HYPE mint the "
        "intended asset and not a look-alike, and is the pool legitimate?"
    ),
    "TRUMP-USDC": (
        "Highest narrative/meme/political-risk sensitivity: are event risk, "
        "volatility spikes, and liquidity cliffs understood for this pair?"
    ),
}

OPTIONAL_TABLES = (
    "pipeline_runs",
    "strategy_observations",
    "risk_flags",
    "risk_decisions",
    "future_position_events",
)

OHLCV_FLAGS = {"OHLCV_UNAVAILABLE", "LOW_DATA_COMPLETENESS", "DATA_NOT_AVAILABLE"}
LIQUIDITY_FLAGS = {"LOW_LIQUIDITY", "LOW_VOLUME"}
VOLATILITY_FLAGS = {"HIGH_VOLATILITY", "EXTREME_VOLATILITY"}
POOL_QUALITY_FLAGS = {"MALFORMED_PAIR_LABEL", "LOW_LIQUIDITY", "NO_ELIGIBLE_FEE_POOL"}
FEE_POOL_FLAGS = {"NO_ELIGIBLE_FEE_POOL", "FEE_TVL_DISTORTION"}
DATA_QUALITY_FLAGS = {"MALFORMED_PAIR_LABEL", "LOW_DATA_COMPLETENESS", "DATA_NOT_AVAILABLE"}

# The review matrix rows. `flags` is the runtime risk-flag group used only as an
# automated hint; None means the dimension is manual-only (no direct runtime
# signal exists). `question` is the manual review question the council answers.
REVIEW_DIMENSIONS = (
    {
        "key": "TOKEN_IDENTITY",
        "title": "Token identity",
        "question": (
            "Have both token mints in pair_key been positively identified (correct "
            "mint, not a look-alike/spoof) and confirmed legitimate?"
        ),
        "flags": DATA_QUALITY_FLAGS,
    },
    {
        "key": "POOL_LEGITIMACY",
        "title": "Pool legitimacy / depth / fee-tier / bin",
        "question": (
            "Is the pool legitimate with adequate depth, a sane fee tier, and a "
            "reasonable bin configuration (not empty and not a trap)?"
        ),
        "flags": POOL_QUALITY_FLAGS,
    },
    {
        "key": "OHLCV_CONTINUITY",
        "title": "OHLCV continuity / freshness",
        "question": (
            "Is OHLCV data continuous, fresh, and complete enough to trust (no long "
            "gaps and no staleness)?"
        ),
        "flags": OHLCV_FLAGS,
    },
    {
        "key": "LIQUIDITY_VOLUME",
        "title": "Liquidity / volume",
        "question": (
            "Are liquidity and traded volume adequate and sustained across runs "
            "(not a thin or one-off pool)?"
        ),
        "flags": LIQUIDITY_FLAGS,
    },
    {
        "key": "VOLATILITY_REGIME",
        "title": "Volatility regime",
        "question": (
            "Is the volatility regime understood and acceptable for "
            f"{REVIEW_PHRASE}?"
        ),
        "flags": VOLATILITY_FLAGS,
    },
    {
        "key": "FEE_POOL_ELIGIBILITY",
        "title": "Fee-pool eligibility",
        "question": (
            "Is any NO_ELIGIBLE_FEE_POOL condition understood? The council decided "
            "not to loosen this blocker, so it must stay valid unless manual "
            "data-quality review proves otherwise."
        ),
        "flags": FEE_POOL_FLAGS,
    },
    {
        "key": "NARRATIVE_EVENT_RISK",
        "title": "Narrative / event / political risk",
        "question": None,  # candidate-specific; filled from CANDIDATE_NARRATIVE
        "flags": None,
    },
    {
        "key": "SAFETY_BOUNDARY",
        "title": "Safety boundary",
        "question": (
            "Does reviewing this candidate keep the read-only safety boundary "
            "intact (no wallet, no private key, no signing, no swap, no LP "
            "add/remove, no rebalance, no paper position, no future_position_events "
            "writes, no live execution)?"
        ),
        "flags": None,
    },
)

CSV_COLUMNS = (
    "pair_key",
    "pair_label",
    "review_priority",
    "review_dimension",
    "review_dimension_title",
    "review_question",
    "runtime_evidence_status",
    "manual_review_status",
    "council_answer",
    "carried_latest_risk_decision",
    "carried_latest_max_allowed_action",
    "candidate_status_change",
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

DIAGNOSTIC_NOTICE = (
    "This is a diagnostic-only manual council review matrix. It is not paper "
    f"simulation and it changes no candidate status. It means only that {REVIEW_PHRASE}."
)

FORBIDDEN_NOTICE = (
    "This report does not authorize paper trade, open position, signal, wallet "
    "use, signing, swap, LP add/remove, rebalance, or live execution."
)


def require_duckdb():
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


def list_tables(conn) -> set:
    rows = conn.execute(
        "SELECT table_name FROM information_schema.tables WHERE table_schema = 'main'"
    ).fetchall()
    return {row[0] for row in rows}


def table_columns(conn, name: str) -> set:
    return {row[1] for row in conn.execute(f"PRAGMA table_info('{name}')").fetchall()}


def table_count(conn, name: str) -> int:
    return conn.execute(f"SELECT COUNT(*) FROM {name}").fetchone()[0]


def _rows(conn, sql: str, params=None):
    return conn.execute(sql, params or []).fetchall()


def _clean(value) -> str:
    return "" if value is None else str(value).strip()


def gather_observation_rows(conn, present):
    if "strategy_observations" not in present:
        return None
    columns = table_columns(conn, "strategy_observations")
    for col in ("pair_key", "strategy_class_v2", "test_lane"):
        if col not in columns:
            return []
    return _rows(
        conn,
        "SELECT pair_key, pair_label, run_id, strategy_class_v2, test_lane, "
        "CAST(observed_at AS VARCHAR) AS observed_at, observation_id "
        "FROM strategy_observations",
    )


def gather_flag_rows(conn, present):
    if "risk_flags" not in present:
        return None
    columns = table_columns(conn, "risk_flags")
    if not {"pair_key", "risk_flag"}.issubset(columns):
        return []
    return _rows(conn, "SELECT pair_key, risk_flag FROM risk_flags")


def gather_decision_rows(conn, present):
    if "risk_decisions" not in present:
        return None
    columns = table_columns(conn, "risk_decisions")
    required = {"pair_key", "risk_decision", "risk_action", "max_allowed_action"}
    if not required.issubset(columns):
        return []
    select = [
        "pair_key",
        "pair_label" if "pair_label" in columns else "'' AS pair_label",
        "risk_decision",
        "risk_action",
        "max_allowed_action",
        "CAST(imported_at AS VARCHAR) AS imported_at" if "imported_at" in columns else "'' AS imported_at",
        "risk_decision_id" if "risk_decision_id" in columns else "'' AS risk_decision_id",
    ]
    return _rows(conn, "SELECT " + ", ".join(select) + " FROM risk_decisions")


def _new_pair():
    return {"labels": [], "samples": [], "run_ids": [], "flags": [], "decisions": []}


def _latest_decision(rec):
    if not rec["decisions"]:
        return (NOT_AVAILABLE, NOT_AVAILABLE, NOT_AVAILABLE)
    latest = max(rec["decisions"], key=lambda d: d[0])
    return latest[1], latest[2], latest[3]


def _latest_observation(rec):
    if not rec["samples"]:
        return (NOT_AVAILABLE, NOT_AVAILABLE)
    latest = max(rec["samples"], key=lambda s: (_clean(s[0]), _clean(s[1])))
    return _clean(latest[2]) or NOT_AVAILABLE, _clean(latest[3]) or NOT_AVAILABLE


def _is_candidate(rec) -> bool:
    latest_decision, _, latest_max = _latest_decision(rec)
    latest_class, latest_lane = _latest_observation(rec)
    labels = sorted({_clean(x) for x in rec["labels"] if _clean(x)})
    pair_label = labels[0] if labels else ""
    return (
        pair_label in CANDIDATE_PRIORITY
        and latest_decision == DECISION_PAPER_REVIEW
        and latest_max == MAX_FUTURE_PAPER_REVIEW
        and latest_class == "CORE"
        and latest_lane == "CLEAN"
    )


def _status_for_flags(flags, group):
    if flags is None:
        return NOT_AVAILABLE
    return EVIDENCE_PRESENT if any(_clean(f) in group for f in flags) else NO_RUNTIME_FLAG_FOUND


def _dimension_question(dimension, pair_label) -> str:
    if dimension["key"] == "NARRATIVE_EVENT_RISK":
        return CANDIDATE_NARRATIVE.get(
            pair_label,
            "Are the narrative, event, and political risks for this pair understood?",
        )
    return dimension["question"]


def build_candidate_matrix(rec, pair_key, pair_label):
    """Build the per-candidate list of review matrix cells (one per dimension)."""
    latest_decision, _, latest_max = _latest_decision(rec)
    flags = rec["flags"]
    cells = []
    for dimension in REVIEW_DIMENSIONS:
        if dimension["flags"] is None:
            evidence_status = MANUAL_ONLY
        else:
            evidence_status = _status_for_flags(flags, dimension["flags"])
        cells.append(
            {
                "pair_key": pair_key,
                "pair_label": pair_label,
                "review_priority": CANDIDATE_PRIORITY.get(pair_label, 999),
                "review_dimension": dimension["key"],
                "review_dimension_title": dimension["title"],
                "review_question": _dimension_question(dimension, pair_label),
                "runtime_evidence_status": evidence_status,
                "manual_review_status": PENDING_MANUAL_REVIEW,
                "council_answer": PENDING_MANUAL_REVIEW,
                "carried_latest_risk_decision": latest_decision,
                "carried_latest_max_allowed_action": latest_max,
                "candidate_status_change": NO_CHANGE,
            }
        )
    return cells


def aggregate(observation_rows, flag_rows, decision_rows, limit):
    observation_rows = observation_rows or []
    flag_rows = flag_rows or []
    decision_rows = decision_rows or []
    pairs = {}

    def pair(pk):
        return pairs.setdefault(pk, _new_pair())

    for pair_key, pair_label, run_id, cls, lane, observed_at, obs_id in observation_rows:
        pk = _clean(pair_key)
        if not pk:
            continue
        rec = pair(pk)
        rec["labels"].append(pair_label)
        rec["samples"].append((observed_at, obs_id, cls, lane))
        rec["run_ids"].append(run_id)

    for pair_key, risk_flag in flag_rows:
        pk = _clean(pair_key)
        if not pk:
            continue
        pair(pk)["flags"].append(risk_flag)

    for pair_key, pair_label, decision, action, max_action, imported_at, decision_id in decision_rows:
        pk = _clean(pair_key)
        if not pk:
            continue
        rec = pair(pk)
        rec["labels"].append(pair_label)
        sort_key = (_clean(imported_at), _clean(decision_id))
        rec["decisions"].append(
            (
                sort_key,
                _clean(decision) or NOT_AVAILABLE,
                _clean(action) or NOT_AVAILABLE,
                _clean(max_action) or NOT_AVAILABLE,
            )
        )

    candidates = []
    for pair_key, rec in pairs.items():
        if not _is_candidate(rec):
            continue
        labels = sorted({_clean(x) for x in rec["labels"] if _clean(x)})
        pair_label = labels[0] if labels else NOT_AVAILABLE
        candidates.append((pair_key, pair_label, rec))

    candidates.sort(key=lambda c: (CANDIDATE_PRIORITY.get(c[1], 999), c[1], c[0]))
    if limit is not None:
        candidates = candidates[:limit]

    rows = []
    for pair_key, pair_label, rec in candidates:
        rows.extend(build_candidate_matrix(rec, pair_key, pair_label))
    return candidates, rows


def build_diagnostics(conn, present, limit, min_runs) -> dict:
    fpe_present = "future_position_events" in present
    fpe_count = table_count(conn, "future_position_events") if fpe_present else 0
    if fpe_count > 0:
        return {
            "fpe_count": fpe_count,
            "fpe_violation": True,
            "run_count": None,
            "distinct_observed_runs": 0,
            "evidence_sufficient": False,
            "evidence_runs": 0,
            "min_runs": min_runs,
            "candidates": [],
            "rows": [],
            "present": present,
        }

    run_count = table_count(conn, "pipeline_runs") if "pipeline_runs" in present else None
    observation_rows = gather_observation_rows(conn, present)
    flag_rows = gather_flag_rows(conn, present)
    decision_rows = gather_decision_rows(conn, present)
    candidates, rows = aggregate(observation_rows, flag_rows, decision_rows, limit)
    observed_runs = {_clean(row[2]) for row in observation_rows or [] if _clean(row[2])}
    evidence_runs = max(run_count or 0, len(observed_runs))
    return {
        "fpe_count": fpe_count,
        "fpe_violation": False,
        "run_count": run_count,
        "distinct_observed_runs": len(observed_runs),
        "evidence_sufficient": evidence_runs >= min_runs,
        "evidence_runs": evidence_runs,
        "min_runs": min_runs,
        "candidates": candidates,
        "rows": rows,
        "present": present,
    }


def _md_cell(value) -> str:
    return str(value).replace("|", "\\|").replace("\n", " ")


def md_table(headers, rows) -> list:
    if not rows:
        return ["_(no rows)_"]
    lines = ["| " + " | ".join(headers) + " |"]
    lines.append("| " + " | ".join("---" for _ in headers) + " |")
    for row in rows:
        lines.append("| " + " | ".join(_md_cell(c) for c in row) + " |")
    return lines


def section(lines, title: str) -> None:
    lines.append("")
    lines.append(f"## {title}")
    lines.append("")


def render_markdown(diag: dict, db_path: str, limit: int) -> str:
    candidates = diag["candidates"]
    rows = diag["rows"]
    lines = [
        "# Manual Council Review Matrix v0.1",
        "",
        f"- generated_at UTC: {utc_now_iso()}",
        f"- safety phase: {SAFETY_PHASE}",
        f"- database path: {db_path}",
        f"- candidate limit: {limit}",
        f"- min_runs: {diag['min_runs']}",
        "",
        DIAGNOSTIC_NOTICE,
        FORBIDDEN_NOTICE,
    ]

    section(lines, "Safety Boundary")
    for line in SAFETY_BOUNDARY_LINES:
        lines.append(f"- {line}")
    lines.append("- This is not paper simulation and it changes no candidate status.")

    section(lines, "Summary")
    run_count = diag["run_count"] if diag["run_count"] is not None else NOT_AVAILABLE
    lines.append(f"- pipeline run count: {run_count}")
    lines.append(f"- distinct observation run count: {diag['distinct_observed_runs']}")
    lines.append(f"- future_position_events count: {diag['fpe_count']} (expected 0)")
    lines.append(f"- candidate count: {len(candidates)}")
    lines.append(f"- review dimensions per candidate: {len(REVIEW_DIMENSIONS)}")
    lines.append(f"- matrix rows (candidate x dimension): {len(rows)}")
    for table in OPTIONAL_TABLES:
        if table not in diag["present"]:
            lines.append(f"- {table}: table missing; reported honestly as unavailable")
    if diag["evidence_sufficient"]:
        lines.append(
            f"- evidence sufficiency: SUFFICIENT - {diag['evidence_runs']} run(s) "
            f">= min_runs ({diag['min_runs']})"
        )
    else:
        lines.append(
            f"- evidence sufficiency: INSUFFICIENT - {diag['evidence_runs']} run(s) "
            f"< min_runs ({diag['min_runs']})"
        )

    section(lines, "Review Dimensions Legend")
    lines.append(
        "Each candidate is reviewed by hand across the same dimensions. "
        "`runtime_evidence_status` is only an automated hint: EVIDENCE_PRESENT "
        "(a matching runtime risk flag exists), NO_RUNTIME_FLAG_FOUND (no matching "
        "runtime risk flag; manual review still required), MANUAL_ONLY (no runtime "
        "signal exists for this dimension), or NOT_AVAILABLE. Every "
        "`manual_review_status` and `council_answer` starts as PENDING_MANUAL_REVIEW."
    )
    lines.append("")
    for dimension in REVIEW_DIMENSIONS:
        lines.append(f"- {dimension['key']} - {dimension['title']}")

    for pair_key, pair_label, rec in candidates:
        latest_decision, _, latest_max = _latest_decision(rec)
        section(lines, f"Candidate: {pair_label}")
        lines.append(f"- pair_key: {pair_key}")
        lines.append(f"- review_priority: {CANDIDATE_PRIORITY.get(pair_label, 999)}")
        lines.append(f"- carried_latest_risk_decision (read-only echo): {latest_decision}")
        lines.append(f"- carried_latest_max_allowed_action (read-only echo): {latest_max}")
        lines.append(f"- candidate_status_change: {NO_CHANGE}")
        lines.append(f"- review_scope: {REVIEW_PHRASE}.")
        lines.append("")
        cells = build_candidate_matrix(rec, pair_key, pair_label)
        table_rows = [
            (
                cell["review_dimension"],
                cell["review_question"],
                cell["runtime_evidence_status"],
                cell["manual_review_status"],
                cell["council_answer"],
            )
            for cell in cells
        ]
        lines.extend(
            md_table(
                (
                    "review_dimension",
                    "manual_review_question",
                    "runtime_evidence_status",
                    "manual_review_status",
                    "council_answer",
                ),
                table_rows,
            )
        )

    section(lines, "How To Use This Matrix")
    lines.append(
        "- The human / council answers every PENDING_MANUAL_REVIEW cell by hand."
    )
    lines.append(
        "- This report records questions only; it does not answer them and does "
        "not change any candidate status."
    )
    lines.append(
        "- NO_RUNTIME_FLAG_FOUND does not mean pass; it only means no runtime risk "
        "flag was raised. Manual verification is still required."
    )
    lines.append(
        "- A candidate may advance in scope only by explicit council decision "
        "recorded in docs/decision_log.md, never by this report."
    )
    lines.append(f"- Keep scope limited to: {REVIEW_PHRASE}.")

    section(lines, "Final Safety Statement")
    lines.append(
        "This matrix is diagnostic-only and is not paper simulation. It makes no "
        "threshold, risk-policy, candidate-status, or runtime data change, and it "
        "does not write future_position_events."
    )
    lines.append(FORBIDDEN_NOTICE)
    return "\n".join(lines) + "\n"


def write_csv(path: Path, rows) -> None:
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        for row in rows:
            writer.writerow({col: row[col] for col in CSV_COLUMNS})


def print_safety_banner() -> None:
    print("------------------------------------------------------------")
    print("  MANUAL COUNCIL REVIEW MATRIX v0.1")
    print("------------------------------------------------------------")
    print(f"  {SAFETY_PHASE}")
    for line in SAFETY_BOUNDARY_LINES:
        print(f"  {line}")
    print("------------------------------------------------------------")


def run_report(db_path: str, out_md: str, out_csv: str, limit, min_runs: int, dry_run: bool) -> int:
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
        print(f"  would write csv : {out_csv}")
        print(f"  pipeline runs   : {diag['run_count']}")
        print(f"  distinct observation runs: {diag['distinct_observed_runs']}")
        print(f"  future_position_events count: {diag['fpe_count']} (expected 0)")
        print(f"  candidate count : {len(diag['candidates'])}")
        print(f"  matrix rows     : {len(diag['rows'])}")
        print(
            "  evidence sufficiency: "
            + ("SUFFICIENT" if diag["evidence_sufficient"] else "INSUFFICIENT")
        )
        print("DRY RUN COMPLETE - nothing written.")
        return 0

    md_path = Path(out_md)
    csv_path = Path(out_csv)
    md_path.parent.mkdir(parents=True, exist_ok=True)
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    md_path.write_text(render_markdown(diag, db_path, limit), encoding="utf-8")
    write_csv(csv_path, diag["rows"])
    print(f"Wrote Markdown report: {md_path}")
    print(f"Wrote CSV report: {csv_path} ({len(diag['rows'])} rows)")
    print(f"future_position_events count: {diag['fpe_count']} (expected 0)")
    print(DIAGNOSTIC_NOTICE)
    return 0


def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description=(
            "Manual Council Review Matrix v0.1. Read-only diagnostic matrix of "
            "manual review questions per stable candidate; does not write DuckDB, "
            "does not change candidate status, and is not paper simulation."
        )
    )
    parser.add_argument("--db-path", default=DEFAULT_DB_PATH)
    parser.add_argument("--out-md", default=DEFAULT_OUT_MD)
    parser.add_argument("--out-csv", default=DEFAULT_OUT_CSV)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--limit", type=int, default=DEFAULT_LIMIT)
    parser.add_argument("--min-runs", type=int, default=DEFAULT_MIN_RUNS)
    return parser.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)
    print_safety_banner()
    limit = args.limit if args.limit is not None and args.limit >= 0 else None
    return run_report(args.db_path, args.out_md, args.out_csv, limit, args.min_runs, args.dry_run)


if __name__ == "__main__":
    raise SystemExit(main())
