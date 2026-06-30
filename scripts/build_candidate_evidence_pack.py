#!/usr/bin/env python3
"""Candidate Evidence Pack v0.1.

Read an existing runtime DuckDB database and write a diagnostic-only evidence
pack for stable review candidates. This is read-only reporting for
human/council review before any future paper-simulation design consideration.
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
DEFAULT_OUT_MD = "reports/runtime/candidate_evidence_pack.md"
DEFAULT_OUT_CSV = "reports/runtime/candidate_evidence_pack.csv"
DEFAULT_LIMIT = 20
DEFAULT_MIN_RUNS = 5

DECISION_PAPER_REVIEW = "PAPER_REVIEW_CANDIDATE"
MAX_FUTURE_PAPER_REVIEW = "FUTURE_PAPER_SIMULATION_REVIEW"

EVIDENCE_PRESENT = "EVIDENCE_PRESENT"
NO_RUNTIME_FLAG_FOUND = "NO_RUNTIME_FLAG_FOUND"
NEEDS_MANUAL_REVIEW = "NEEDS_MANUAL_REVIEW"
NEEDS_MORE_DATA = "NEEDS_MORE_DATA"
NOT_AVAILABLE = "NOT_AVAILABLE"

REVIEW_ONLY_PASS = "REVIEW_ONLY_PASS"
REJECT_FOR_NOW = "REJECT_FOR_NOW"

CANDIDATE_PRIORITY = {
    "USDC-SOL": 0,
    "JUP-SOL": 1,
    "USDC-cbBTC": 2,
    "HYPE-USDC": 3,
    "HYPE-SOL": 4,
    "TRUMP-USDC": 5,
}

CANDIDATE_RISKS = {
    "USDC-SOL": (
        "benchmark/reference pair",
        "verify pool depth, fee tiers/bins, and OHLCV continuity",
    ),
    "JUP-SOL": (
        "Solana ecosystem asset",
        "verify liquidity depth, volume quality, and volatility regime",
    ),
    "USDC-cbBTC": (
        "wrapped/bridged BTC exposure",
        "verify wrapped asset identity, issuer/bridge assumptions, liquidity, and data source",
    ),
    "HYPE-USDC": (
        "token identity/pool quality validation required",
        "verify token mint, pool legitimacy, liquidity, and volatility",
    ),
    "HYPE-SOL": (
        "token identity/pool quality validation required",
        "verify token mint, pool legitimacy, liquidity, and volatility",
    ),
    "TRUMP-USDC": (
        "narrative/meme/political-risk sensitive",
        "verify event risk, volatility spikes, liquidity cliffs, and pool stability",
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
    "token_a_mint",
    "token_b_mint",
    "token_identity_status",
    "pool_identity_status",
    "observation_count",
    "distinct_run_count",
    "first_seen_at",
    "last_seen_at",
    "latest_strategy_class",
    "latest_lane",
    "strategy_class_history",
    "lane_history",
    "strategy_class_change_count",
    "lane_change_count",
    "latest_risk_decision",
    "latest_risk_action",
    "latest_max_allowed_action",
    "risk_flag_types",
    "risk_flag_count_total",
    "blocker_count",
    "blocker_history",
    "latest_blocker_reason",
    "ohlcv_evidence_status",
    "liquidity_evidence_status",
    "volatility_evidence_status",
    "pool_quality_evidence_status",
    "fee_pool_evidence_status",
    "data_quality_evidence_status",
    "evidence_gaps",
    "candidate_specific_risks",
    "council_review_questions",
    "suggested_council_verdict",
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
    "This is a diagnostic-only evidence pack. It is not paper simulation. "
    f"It means only that {REVIEW_PHRASE}."
)

FORBIDDEN_NOTICE = (
    "This report does not authorize paper trade, open position, signal, wallet "
    "use, signing, swap, LP add/remove, rebalance, or live execution."
)

OHLCV_FLAGS = {"OHLCV_UNAVAILABLE", "LOW_DATA_COMPLETENESS", "DATA_NOT_AVAILABLE"}
LIQUIDITY_FLAGS = {"LOW_LIQUIDITY", "LOW_VOLUME"}
VOLATILITY_FLAGS = {"HIGH_VOLATILITY", "EXTREME_VOLATILITY"}
POOL_QUALITY_FLAGS = {"MALFORMED_PAIR_LABEL", "LOW_LIQUIDITY", "NO_ELIGIBLE_FEE_POOL"}
FEE_POOL_FLAGS = {"NO_ELIGIBLE_FEE_POOL", "FEE_TVL_DISTORTION"}
DATA_QUALITY_FLAGS = {"MALFORMED_PAIR_LABEL", "LOW_DATA_COMPLETENESS", "DATA_NOT_AVAILABLE"}
BLOCKER_LIKE_REASONS = {
    "NO_ELIGIBLE_FEE_POOL",
    "MALFORMED_PAIR_LABEL",
    "CLASSIFIED_REJECT",
    "TEST_LANE_QUARANTINE",
    "NOT_LIVE_ELIGIBLE",
}


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


def _split_tokens(value) -> list:
    raw = _clean(value)
    if not raw or raw.lower() in {"none", "not_available"}:
        return []
    return [x.strip() for x in raw.replace(",", "|").replace(";", "|").split("|") if x.strip()]


def _join_or_none(values) -> str:
    cleaned = sorted({v for v in (_clean(x) for x in values) if v})
    return "|".join(cleaned) if cleaned else "none"


def _join_history(values) -> str:
    cleaned = [_clean(x) for x in values if _clean(x)]
    return "|".join(cleaned) if cleaned else NOT_AVAILABLE


def _minmax_or_na(values):
    cleaned = sorted(v for v in (_clean(x) for x in values) if v)
    if not cleaned:
        return NOT_AVAILABLE, NOT_AVAILABLE
    return cleaned[0], cleaned[-1]


def _transitions(values) -> int:
    cleaned = [_clean(x) for x in values if _clean(x)]
    return sum(1 for i in range(1, len(cleaned)) if cleaned[i] != cleaned[i - 1])


def gather_observation_rows(conn, present):
    if "strategy_observations" not in present:
        return None
    columns = table_columns(conn, "strategy_observations")
    select = [
        "pair_key",
        "pair_label",
        "run_id",
        "strategy_class_v2",
        "test_lane",
        "CAST(observed_at AS VARCHAR) AS observed_at",
        "observation_id",
    ]
    for col in ("pair_key", "strategy_class_v2", "test_lane"):
        if col not in columns:
            return []
    return _rows(conn, "SELECT " + ", ".join(select) + " FROM strategy_observations")


def gather_flag_rows(conn, present):
    if "risk_flags" not in present:
        return None
    columns = table_columns(conn, "risk_flags")
    if not {"pair_key", "risk_flag"}.issubset(columns):
        return []
    return _rows(
        conn,
        "SELECT pair_key, pair_label, risk_flag, CAST(observed_at AS VARCHAR), flag_id "
        "FROM risk_flags",
    )


def gather_decision_rows(conn, present):
    if "risk_decisions" not in present:
        return None
    columns = table_columns(conn, "risk_decisions")
    required = {"pair_key", "risk_decision", "risk_action", "max_allowed_action"}
    if not required.issubset(columns):
        return []
    optional = {
        "pair_label": "pair_label",
        "risk_blockers": "risk_blockers",
        "risk_warnings": "risk_warnings",
        "risk_policy_reason": "risk_policy_reason",
        "imported_at": "CAST(imported_at AS VARCHAR) AS imported_at",
        "risk_decision_id": "risk_decision_id",
    }
    select = [
        "pair_key",
        optional["pair_label"] if "pair_label" in columns else "'' AS pair_label",
        "risk_decision",
        "risk_action",
        "max_allowed_action",
        optional["risk_blockers"] if "risk_blockers" in columns else "'' AS risk_blockers",
        optional["risk_warnings"] if "risk_warnings" in columns else "'' AS risk_warnings",
        optional["risk_policy_reason"] if "risk_policy_reason" in columns else "'' AS risk_policy_reason",
        optional["imported_at"] if "imported_at" in columns else "'' AS imported_at",
        optional["risk_decision_id"] if "risk_decision_id" in columns else "'' AS risk_decision_id",
    ]
    return _rows(conn, "SELECT " + ", ".join(select) + " FROM risk_decisions")


def _new_pair():
    return {
        "labels": [],
        "samples": [],
        "run_ids": [],
        "times": [],
        "flags": [],
        "decisions": [],
        "blockers": [],
    }


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


def _decision_blockers(decision, blockers, warnings, policy_reason) -> list:
    decision = _clean(decision)
    tokens = []
    for raw in (blockers, warnings, policy_reason):
        tokens.extend(_split_tokens(raw))
    found = []
    for token in tokens:
        if token in BLOCKER_LIKE_REASONS:
            found.append(token)
        else:
            found.extend(reason for reason in BLOCKER_LIKE_REASONS if reason in token)
    if decision in {"BLOCKED", "REJECTED"}:
        return found or [decision]
    return found


def _parse_pair_key(pair_key: str):
    parts = [p.strip() for p in _clean(pair_key).split("|")]
    if len(parts) == 2 and parts[0] and parts[1]:
        return parts[0], parts[1], NEEDS_MANUAL_REVIEW, NEEDS_MANUAL_REVIEW, None
    return "", "", NEEDS_MORE_DATA, NEEDS_MORE_DATA, "malformed pair_key"


def _status_for_flags(flags, group):
    if flags is None:
        return NOT_AVAILABLE
    return EVIDENCE_PRESENT if any(_clean(f) in group for f in flags) else NO_RUNTIME_FLAG_FOUND


def _candidate_risk_text(pair_label: str) -> str:
    risks = CANDIDATE_RISKS.get(pair_label)
    if not risks:
        risks = (
            "manual token/pool validation required",
            "verify identity, liquidity, volatility, and data quality",
        )
    return "; ".join(risks)


def _questions(pair_label: str) -> str:
    return (
        "Has token identity been checked manually? Has pool legitimacy and depth "
        "been checked manually? Are OHLCV continuity, liquidity, volatility, fee "
        f"pool, and data quality adequate for {REVIEW_PHRASE}?"
    )


def _suggested_verdict(pair_label, blocker_count, risk_flag_count, distinct_runs, min_runs):
    if blocker_count > 0:
        return REJECT_FOR_NOW
    if risk_flag_count > 0:
        return NEEDS_MORE_DATA
    if pair_label == "USDC-SOL" and distinct_runs >= min_runs:
        return REVIEW_ONLY_PASS
    return NEEDS_MORE_DATA


def _is_candidate(rec) -> bool:
    latest_decision, _, latest_max = _latest_decision(rec)
    latest_class, latest_lane = _latest_observation(rec)
    labels = sorted({_clean(x) for x in rec["labels"] if _clean(x)})
    pair_label = labels[0] if labels else ""
    return (
        pair_label in CANDIDATE_PRIORITY
        and
        latest_decision == DECISION_PAPER_REVIEW
        and latest_max == MAX_FUTURE_PAPER_REVIEW
        and latest_class == "CORE"
        and latest_lane == "CLEAN"
    )


def aggregate_candidates(observation_rows, flag_rows, decision_rows, limit, min_runs):
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
        rec["times"].append(observed_at)

    for pair_key, pair_label, risk_flag, observed_at, flag_id in flag_rows:
        pk = _clean(pair_key)
        if not pk:
            continue
        rec = pair(pk)
        rec["labels"].append(pair_label)
        rec["flags"].append(risk_flag)
        rec["times"].append(observed_at)

    for (pair_key, pair_label, decision, action, max_action, blockers, warnings,
         policy_reason, imported_at, decision_id) in decision_rows:
        pk = _clean(pair_key)
        if not pk:
            continue
        rec = pair(pk)
        rec["labels"].append(pair_label)
        rec["times"].append(imported_at)
        sort_key = (_clean(imported_at), _clean(decision_id))
        rec["decisions"].append(
            (sort_key, _clean(decision) or NOT_AVAILABLE, _clean(action) or NOT_AVAILABLE,
             _clean(max_action) or NOT_AVAILABLE)
        )
        for reason in _decision_blockers(decision, blockers, warnings, policy_reason):
            rec["blockers"].append((sort_key, reason))

    records = []
    for pair_key, rec in pairs.items():
        if not _is_candidate(rec):
            continue
        labels = sorted({_clean(x) for x in rec["labels"] if _clean(x)})
        pair_label = labels[0] if labels else NOT_AVAILABLE
        ordered = sorted(rec["samples"], key=lambda s: (_clean(s[0]), _clean(s[1])))
        run_ids = {_clean(r) for r in rec["run_ids"] if _clean(r)}
        first_seen, last_seen = _minmax_or_na(rec["times"])
        latest_class, latest_lane = _latest_observation(rec)
        latest_decision, latest_action, latest_max = _latest_decision(rec)
        blockers = sorted(rec["blockers"], key=lambda item: (item[0], _clean(item[1])))
        blocker_reasons = [reason for _, reason in blockers if _clean(reason)]
        blocker_count = len({item[0] for item in blockers})
        token_a, token_b, token_status, pool_status, parse_gap = _parse_pair_key(pair_key)

        gaps = []
        if parse_gap:
            gaps.append(parse_gap)
        if observation_rows is None:
            gaps.append("strategy_observations table missing")
        if flag_rows is None:
            gaps.append("risk_flags table missing")
        if decision_rows is None:
            gaps.append("risk_decisions table missing")
        if not rec["flags"]:
            gaps.append("no runtime risk flags found; manual evidence review still required")

        distinct_runs = len(run_ids)
        flags = rec["flags"]
        risk_count = len(flags)
        records.append(
            {
                "pair_key": pair_key,
                "pair_label": pair_label,
                "token_a_mint": token_a,
                "token_b_mint": token_b,
                "token_identity_status": token_status,
                "pool_identity_status": pool_status,
                "observation_count": len(rec["samples"]),
                "distinct_run_count": distinct_runs,
                "first_seen_at": first_seen,
                "last_seen_at": last_seen,
                "latest_strategy_class": latest_class,
                "latest_lane": latest_lane,
                "strategy_class_history": _join_history(s[2] for s in ordered),
                "lane_history": _join_history(s[3] for s in ordered),
                "strategy_class_change_count": _transitions(s[2] for s in ordered),
                "lane_change_count": _transitions(s[3] for s in ordered),
                "latest_risk_decision": latest_decision,
                "latest_risk_action": latest_action,
                "latest_max_allowed_action": latest_max,
                "risk_flag_types": _join_or_none(flags),
                "risk_flag_count_total": risk_count,
                "blocker_count": blocker_count,
                "blocker_history": _join_or_none(blocker_reasons),
                "latest_blocker_reason": _clean(blockers[-1][1]) if blockers else "none",
                "ohlcv_evidence_status": _status_for_flags(flags, OHLCV_FLAGS),
                "liquidity_evidence_status": _status_for_flags(flags, LIQUIDITY_FLAGS),
                "volatility_evidence_status": _status_for_flags(flags, VOLATILITY_FLAGS),
                "pool_quality_evidence_status": _status_for_flags(flags, POOL_QUALITY_FLAGS),
                "fee_pool_evidence_status": _status_for_flags(flags, FEE_POOL_FLAGS),
                "data_quality_evidence_status": _status_for_flags(flags, DATA_QUALITY_FLAGS),
                "evidence_gaps": "; ".join(gaps) if gaps else "none",
                "candidate_specific_risks": _candidate_risk_text(pair_label),
                "council_review_questions": _questions(pair_label),
                "suggested_council_verdict": _suggested_verdict(
                    pair_label, blocker_count, risk_count, distinct_runs, min_runs
                ),
            }
        )

    records.sort(
        key=lambda r: (
            CANDIDATE_PRIORITY.get(r["pair_label"], 999),
            r["pair_label"],
            r["pair_key"],
        )
    )
    return records[:limit] if limit is not None else records


def build_diagnostics(conn, present, limit: int, min_runs: int) -> dict:
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
            "records": [],
            "present": present,
        }

    run_count = table_count(conn, "pipeline_runs") if "pipeline_runs" in present else None
    observation_rows = gather_observation_rows(conn, present)
    flag_rows = gather_flag_rows(conn, present)
    decision_rows = gather_decision_rows(conn, present)
    records = aggregate_candidates(observation_rows, flag_rows, decision_rows, limit, min_runs)
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
        "records": records,
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
    records = diag["records"]
    lines = [
        "# Candidate Evidence Pack v0.1",
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
    lines.append("- This is not paper simulation.")

    section(lines, "Summary")
    run_count = diag["run_count"] if diag["run_count"] is not None else NOT_AVAILABLE
    lines.append(f"- pipeline run count: {run_count}")
    lines.append(f"- distinct observation run count: {diag['distinct_observed_runs']}")
    lines.append(f"- future_position_events count: {diag['fpe_count']} (expected 0)")
    lines.append(f"- candidate count: {len(records)}")
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

    section(lines, "Candidate Evidence Table")
    table_rows = [
        (
            r["pair_label"],
            r["observation_count"],
            r["distinct_run_count"],
            r["latest_risk_decision"],
            r["risk_flag_count_total"],
            r["blocker_count"],
            r["ohlcv_evidence_status"],
            r["liquidity_evidence_status"],
            r["volatility_evidence_status"],
            r["suggested_council_verdict"],
        )
        for r in records
    ]
    lines.extend(
        md_table(
            (
                "pair_label",
                "observation_count",
                "distinct_run_count",
                "latest_risk_decision",
                "risk_flag_count_total",
                "blocker_count",
                "ohlcv_evidence_status",
                "liquidity_evidence_status",
                "volatility_evidence_status",
                "suggested_council_verdict",
            ),
            table_rows,
        )
    )

    for r in records:
        section(lines, f"Candidate: {r['pair_label']}")
        for col in CSV_COLUMNS:
            lines.append(f"- {col}: {r[col]}")
        lines.append(f"- review_scope: {REVIEW_PHRASE}.")
        lines.append(
            "- verdict_note: REVIEW_ONLY_PASS, when present, only means the "
            "evidence pack may pass to human/council discussion."
        )

    section(lines, "Council Review Checklist")
    lines.append("- Confirm token identity and both mints from pair_key.")
    lines.append("- Confirm pool legitimacy, depth, fee tiers/bins, and stability.")
    lines.append("- Confirm OHLCV continuity, liquidity, volatility, and data quality.")
    lines.append("- Confirm no unresolved blockers, flags, or evidence gaps.")
    lines.append(f"- Keep scope limited to: {REVIEW_PHRASE}.")

    section(lines, "Final Safety Statement")
    lines.append(
        "This evidence pack is diagnostic-only and is not paper simulation. "
        "It makes no threshold, risk-policy, candidate-status, or runtime data change."
    )
    lines.append(FORBIDDEN_NOTICE)
    return "\n".join(lines) + "\n"


def write_csv(path: Path, records) -> None:
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        for record in records:
            writer.writerow({col: record[col] for col in CSV_COLUMNS})


def print_safety_banner() -> None:
    print("------------------------------------------------------------")
    print("  CANDIDATE EVIDENCE PACK v0.1")
    print("------------------------------------------------------------")
    print(f"  {SAFETY_PHASE}")
    for line in SAFETY_BOUNDARY_LINES:
        print(f"  {line}")
    print("------------------------------------------------------------")


def run_report(db_path: str, out_md: str, out_csv: str, limit: int, min_runs: int, dry_run: bool) -> int:
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
        print(f"  candidate count : {len(diag['records'])}")
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
    write_csv(csv_path, diag["records"])
    print(f"Wrote Markdown report: {md_path}")
    print(f"Wrote CSV report: {csv_path} ({len(diag['records'])} rows)")
    print(f"future_position_events count: {diag['fpe_count']} (expected 0)")
    print(DIAGNOSTIC_NOTICE)
    return 0


def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description=(
            "Candidate Evidence Pack v0.1. Read-only diagnostic evidence pack; "
            "does not write DuckDB and is not paper simulation."
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
