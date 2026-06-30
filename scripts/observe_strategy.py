#!/usr/bin/env python3
"""
Paper Observation Readiness v0.1

Purpose:
- Append strategy classification snapshots into JSONL observation history.
- Summarize cross-run stability by pair_key.
- Mark observation readiness for future paper simulation consideration only.

This is NOT:
- paper trading
- live trading
- wallet integration
- private key handling
- signing
- swap
- LP add/remove
- rebalance
- execution
"""

from __future__ import annotations

import csv
import json
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Iterable, List, Tuple


INPUT_CSV = Path("data/strategy_classification_v2.csv")
OBS_DIR = Path("data/observations")
REPORT_DIR = Path("reports/observations")
OBS_JSONL = OBS_DIR / "strategy_observations.jsonl"
SUMMARY_MD = REPORT_DIR / "observation_summary.md"
SUMMARY_CSV = REPORT_DIR / "observation_summary.csv"

SEVERE_FLAGS = {
    "BLACKLISTED",
    "DATA_QUALITY_NA",
    "LOW_DATA_COMPLETENESS",
    "LOW_LIQUIDITY",
    "LOW_VOLUME",
    "MALFORMED_PAIR_LABEL",
    "NO_ELIGIBLE_FEE_POOL",
}

HARD_BLOCK_FLAGS = {
    "BLACKLISTED",
    "MALFORMED_PAIR_LABEL",
}

ALLOWED_CLASSES = {"CORE", "TACTICAL", "REJECT", "NOT_EVALUATED"}
ALLOWED_LIVE_ELIGIBILITY = {
    "NOT_EVALUATED",
    "OBSERVE_ONLY",
    "PAPER_TEST_ALLOWED",
    "NOT_LIVE_ELIGIBLE",
}

FORBIDDEN_TERMS = {
    "LIVE_ELIGIBLE_TINY_SIZE",
    "LIVE_ELIGIBLE_LIMITED",
    "LIVE_ELIGIBLE_FULL",
}


@dataclass(frozen=True)
class ObservationSummary:
    pair_key: str
    latest_pair_label: str
    latest_pool: str
    latest_class: str
    latest_status: str
    latest_lane: str
    latest_live_eligibility: str
    latest_required_capability: str
    latest_risk_flags: str
    total_records: int
    consecutive_clean_core_runs: int
    consecutive_clean_tactical_runs: int
    hard_block_ever: bool
    severe_flag_ever: bool
    not_evaluated_count: int
    chronic_not_evaluated: bool
    observation_ready: bool
    observation_status: str
    reason: str


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def parse_flags(raw: str | None) -> List[str]:
    if raw is None:
        return []
    s = raw.strip()
    if not s or s.lower() == "none":
        return []
    return [x.strip() for x in s.split("|") if x.strip()]


def is_malformed_pair_label(pair_label: str | None) -> bool:
    if pair_label is None:
        return True
    s = pair_label.strip()
    if not s:
        return True
    if s.startswith("-") or s.endswith("-"):
        return True
    if "--" in s:
        return True
    parts = s.split("-")
    if len(parts) < 2:
        return True
    return any(not p.strip() for p in parts)


def has_forbidden_terms(row: Dict[str, str]) -> Tuple[bool, List[str]]:
    found = []
    combined = " ".join(str(v) for v in row.values())
    for term in FORBIDDEN_TERMS:
        if term in combined:
            found.append(term)
    return bool(found), found


def normalize_row(row: Dict[str, str], run_id: str) -> Dict[str, str]:
    required = [
        "pair_label",
        "pair_key",
        "representative_pool_address",
        "ohlcv_status",
        "ohlcv_volatility_bucket",
        "pair_score_total_v1",
        "strategy_class_v2",
        "pair_score_v2_core",
        "pair_score_v2_tactical",
        "pair_status_v2",
        "risk_flag_count",
        "risk_flags",
        "test_lane",
        "live_eligibility",
        "minimum_observation_days",
        "required_capability",
        "v2_classification_reason",
    ]

    missing = [c for c in required if c not in row]
    if missing:
        raise ValueError(f"Missing required columns: {missing}")

    pair_label = row["pair_label"].strip()
    flags = set(parse_flags(row.get("risk_flags", "")))

    if is_malformed_pair_label(pair_label):
        flags.add("MALFORMED_PAIR_LABEL")

    strategy_class = row["strategy_class_v2"].strip()
    live_eligibility = row["live_eligibility"].strip()

    if strategy_class not in ALLOWED_CLASSES:
        raise ValueError(f"Invalid strategy_class_v2={strategy_class!r} for pair={pair_label}")

    if live_eligibility not in ALLOWED_LIVE_ELIGIBILITY:
        raise ValueError(f"Invalid live_eligibility={live_eligibility!r} for pair={pair_label}")

    forbidden, found = has_forbidden_terms(row)
    if forbidden:
        raise ValueError(f"Forbidden live eligibility term(s) found for pair={pair_label}: {found}")

    out = {
        "run_id": run_id,
        "observed_at_utc": run_id,
        "pair_label": pair_label,
        "pair_key": row["pair_key"].strip(),
        "representative_pool_address": row["representative_pool_address"].strip(),
        "ohlcv_status": row["ohlcv_status"].strip(),
        "ohlcv_volatility_bucket": row["ohlcv_volatility_bucket"].strip(),
        "pair_score_total_v1": row["pair_score_total_v1"].strip(),
        "strategy_class_v2": strategy_class,
        "pair_score_v2_core": row["pair_score_v2_core"].strip(),
        "pair_score_v2_tactical": row["pair_score_v2_tactical"].strip(),
        "pair_status_v2": row["pair_status_v2"].strip(),
        "risk_flag_count": str(len(flags)) if flags else "0",
        "risk_flags": "|".join(sorted(flags)) if flags else "none",
        "test_lane": row["test_lane"].strip(),
        "live_eligibility": live_eligibility,
        "minimum_observation_days": row["minimum_observation_days"].strip(),
        "required_capability": row["required_capability"].strip(),
        "v2_classification_reason": row["v2_classification_reason"].strip(),
    }

    if not out["pair_key"]:
        raise ValueError(f"Blank pair_key for pair={pair_label}")

    return out


def read_strategy_rows(path: Path = INPUT_CSV) -> List[Dict[str, str]]:
    if not path.exists():
        raise FileNotFoundError(f"Strategy classification CSV not found: {path}")

    with path.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def append_observations(rows: Iterable[Dict[str, str]], path: Path = OBS_JSONL) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with path.open("a", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
            count += 1
    return count


def read_observations(path: Path = OBS_JSONL) -> List[Dict[str, str]]:
    if not path.exists():
        return []

    out = []
    with path.open(encoding="utf-8") as f:
        for line_no, line in enumerate(f, start=1):
            s = line.strip()
            if not s:
                continue
            try:
                out.append(json.loads(s))
            except json.JSONDecodeError as exc:
                raise ValueError(f"Invalid JSONL at {path}:{line_no}: {exc}") from exc
    return out


def is_clean_core_record(row: Dict[str, str]) -> bool:
    flags = set(parse_flags(row.get("risk_flags", "")))
    return (
        row.get("strategy_class_v2") == "CORE"
        and row.get("ohlcv_status") == "OK"
        and row.get("test_lane") == "CLEAN"
        and row.get("live_eligibility") == "PAPER_TEST_ALLOWED"
        and not (flags & SEVERE_FLAGS)
    )


def is_clean_tactical_record(row: Dict[str, str]) -> bool:
    flags = set(parse_flags(row.get("risk_flags", "")))
    return (
        row.get("strategy_class_v2") == "TACTICAL"
        and row.get("ohlcv_status") == "OK"
        and row.get("test_lane") in {"RISKY_BUT_INTERESTING", "CLEAN"}
        and row.get("live_eligibility") in {"OBSERVE_ONLY", "PAPER_TEST_ALLOWED"}
        and not (flags & HARD_BLOCK_FLAGS)
        and "MALFORMED_PAIR_LABEL" not in flags
    )


def summarize_observations(rows: List[Dict[str, str]]) -> List[ObservationSummary]:
    grouped: Dict[str, List[Dict[str, str]]] = defaultdict(list)
    for row in rows:
        grouped[row["pair_key"]].append(row)

    summaries: List[ObservationSummary] = []

    for pair_key, items in grouped.items():
        items = sorted(items, key=lambda r: r.get("observed_at_utc", ""))
        latest = items[-1]

        all_flags = set()
        for item in items:
            all_flags.update(parse_flags(item.get("risk_flags", "")))

        hard_block_ever = bool(all_flags & HARD_BLOCK_FLAGS)
        severe_flag_ever = bool(all_flags & SEVERE_FLAGS)
        not_eval_count = sum(1 for item in items if item.get("strategy_class_v2") == "NOT_EVALUATED")
        chronic_not_eval = len(items) >= 3 and not_eval_count >= 3

        core_streak = 0
        for item in reversed(items):
            if is_clean_core_record(item):
                core_streak += 1
            else:
                break

        tactical_streak = 0
        for item in reversed(items):
            if is_clean_tactical_record(item):
                tactical_streak += 1
            else:
                break

        observation_ready = False
        status = "OBSERVE_ONLY"
        reason = "Not enough clean consecutive CORE observations."

        if hard_block_ever:
            status = "BLOCKED"
            reason = "Hard block flag observed historically."
        elif chronic_not_eval:
            status = "BLOCKED"
            reason = "Chronic NOT_EVALUATED observed."
        elif latest.get("strategy_class_v2") == "CORE" and core_streak >= 7:
            observation_ready = True
            status = "OBSERVATION_READY_FOR_FUTURE_PAPER_CONSIDERATION"
            reason = "CORE has at least 7 consecutive clean recorded runs."
        elif latest.get("strategy_class_v2") == "TACTICAL" and tactical_streak >= 30:
            observation_ready = False
            status = "TACTICAL_STABLE_BUT_OBSERVE_ONLY"
            reason = "TACTICAL has 30 clean runs but remains observe-only in this phase."
        elif latest.get("strategy_class_v2") == "REJECT":
            status = "REJECTED"
            reason = "Latest classification is REJECT."
        elif latest.get("strategy_class_v2") == "NOT_EVALUATED":
            status = "NOT_EVALUATED"
            reason = "Latest classification is NOT_EVALUATED."
        elif latest.get("strategy_class_v2") == "TACTICAL":
            status = "TACTICAL_OBSERVE_ONLY"
            reason = "TACTICAL is observe-only; no paper/live action."
        elif latest.get("strategy_class_v2") == "CORE":
            status = "CORE_OBSERVING"
            reason = f"CORE clean streak={core_streak}; needs 7."

        summaries.append(
            ObservationSummary(
                pair_key=pair_key,
                latest_pair_label=latest.get("pair_label", ""),
                latest_pool=latest.get("representative_pool_address", ""),
                latest_class=latest.get("strategy_class_v2", ""),
                latest_status=latest.get("pair_status_v2", ""),
                latest_lane=latest.get("test_lane", ""),
                latest_live_eligibility=latest.get("live_eligibility", ""),
                latest_required_capability=latest.get("required_capability", ""),
                latest_risk_flags=latest.get("risk_flags", "none"),
                total_records=len(items),
                consecutive_clean_core_runs=core_streak,
                consecutive_clean_tactical_runs=tactical_streak,
                hard_block_ever=hard_block_ever,
                severe_flag_ever=severe_flag_ever,
                not_evaluated_count=not_eval_count,
                chronic_not_evaluated=chronic_not_eval,
                observation_ready=observation_ready,
                observation_status=status,
                reason=reason,
            )
        )

    summaries.sort(
        key=lambda s: (
            not s.observation_ready,
            s.observation_status,
            s.latest_pair_label,
            s.pair_key,
        )
    )
    return summaries


def write_summary_csv(summaries: List[ObservationSummary], path: Path = SUMMARY_CSV) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = list(ObservationSummary.__dataclass_fields__.keys())

    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for item in summaries:
            w.writerow({field: getattr(item, field) for field in fields})


def write_summary_md(summaries: List[ObservationSummary], path: Path = SUMMARY_MD) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)

    ready = [s for s in summaries if s.observation_ready]
    blocked = [s for s in summaries if s.observation_status == "BLOCKED"]
    core_observing = [s for s in summaries if s.observation_status == "CORE_OBSERVING"]
    tactical = [s for s in summaries if "TACTICAL" in s.observation_status]

    lines = []
    lines.append("# Paper Observation Readiness v0.1")
    lines.append("")
    lines.append("Status: RESEARCH_ONLY / SCREENING_ONLY / PAPER_ONLY")
    lines.append("")
    lines.append("This report tracks classification stability across recorded runs.")
    lines.append("")
    lines.append("Observation readiness means: stable enough to consider for future paper simulation.")
    lines.append("")
    lines.append("It does **not** mean paper trade ready, live ready, LP ready, or execution allowed.")
    lines.append("")
    lines.append("Forbidden actions remain: wallet, private key, signing, swap, LP add/remove, rebalance, live execution.")
    lines.append("")
    lines.append("## Summary")
    lines.append("")
    lines.append(f"- Total observed pairs: {len(summaries)}")
    lines.append(f"- Observation ready: {len(ready)}")
    lines.append(f"- Core observing: {len(core_observing)}")
    lines.append(f"- Tactical observe-only: {len(tactical)}")
    lines.append(f"- Blocked: {len(blocked)}")
    lines.append("")
    lines.append("## Readiness Rules")
    lines.append("")
    lines.append("- CORE requires 7 consecutive clean recorded runs.")
    lines.append("- TACTICAL requires longer observation and remains observe-only in this phase.")
    lines.append("- MALFORMED_PAIR_LABEL or blacklist observed historically creates a hard block.")
    lines.append("- Chronic NOT_EVALUATED creates a block.")
    lines.append("")
    lines.append("## Top Observation Rows")
    lines.append("")
    lines.append("| Pair | Class | Status | Ready | Core Streak | Tactical Streak | Records | Flags | Reason |")
    lines.append("|---|---|---|---:|---:|---:|---:|---|---|")

    for item in summaries[:50]:
        lines.append(
            "| "
            f"{item.latest_pair_label} | "
            f"{item.latest_class} | "
            f"{item.observation_status} | "
            f"{str(item.observation_ready)} | "
            f"{item.consecutive_clean_core_runs} | "
            f"{item.consecutive_clean_tactical_runs} | "
            f"{item.total_records} | "
            f"{item.latest_risk_flags} | "
            f"{item.reason} |"
        )

    lines.append("")
    lines.append("---")
    lines.append("No wallet · No private key · No signing · No swap · No LP · No rebalance · No live execution.")
    lines.append("Observation only; PAPER_ONLY.")

    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    run_id = utc_now_iso()
    raw_rows = read_strategy_rows(INPUT_CSV)
    normalized = [normalize_row(row, run_id) for row in raw_rows]

    appended = append_observations(normalized, OBS_JSONL)
    all_observations = read_observations(OBS_JSONL)
    summaries = summarize_observations(all_observations)

    write_summary_csv(summaries, SUMMARY_CSV)
    write_summary_md(summaries, SUMMARY_MD)

    print("============================================================")
    print("  PAPER OBSERVATION READINESS v0.1")
    print("============================================================")
    print(f"  Input CSV      : {INPUT_CSV}")
    print(f"  Appended rows  : {appended}")
    print(f"  JSONL history  : {OBS_JSONL}")
    print(f"  Summary MD     : {SUMMARY_MD}")
    print(f"  Summary CSV    : {SUMMARY_CSV}")
    print("------------------------------------------------------------")
    print("  RESULT: OBSERVATION UPDATED")
    print("  NOTE  : Observation readiness is future paper-simulation consideration only.")
    print("          No wallet, no private key, no signing, no swap, no LP, no rebalance, no live execution.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
