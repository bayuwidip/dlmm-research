#!/usr/bin/env python3
"""
test_apply_risk_policy.py — tests for the Risk Policy Engine Skeleton v0.1.

These tests verify the read-only, veto-only risk decision layer. They never
exercise (and the engine never provides) wallet/signing/swap/LP/rebalance/live
execution capability.
"""

import csv
import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MODULE_PATH = ROOT / "scripts" / "apply_risk_policy.py"

# Load the module by path (scripts/ is not a package).
_spec = importlib.util.spec_from_file_location("apply_risk_policy", MODULE_PATH)
arp = importlib.util.module_from_spec(_spec)
sys.modules["apply_risk_policy"] = arp
_spec.loader.exec_module(arp)


# Full set of input columns the engine reads/passes through.
INPUT_COLUMNS = [
    "pair_key", "pair_label", "strategy_class_v2", "pair_status_v2",
    "test_lane", "live_eligibility", "required_capability",
    "risk_flag_count", "risk_flags", "v2_classification_reason",
]


def make_row(**overrides):
    """A neutral input row; override specific fields per test."""
    base = {
        "pair_key": "AAA-BBB",
        "pair_label": "AAA-BBB",
        "strategy_class_v2": "NOT_EVALUATED",
        "pair_status_v2": "NOT_EVALUATED",
        "test_lane": "NOT_EVALUATED",
        "live_eligibility": "NOT_EVALUATED",
        "required_capability": "NONE",
        "risk_flag_count": "0",
        "risk_flags": "none",
        "v2_classification_reason": "test",
    }
    base.update(overrides)
    return base


def write_csv(path, rows, columns=INPUT_COLUMNS):
    with Path(path).open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=columns)
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in columns})


CORE_CLEAN = dict(
    strategy_class_v2="CORE", pair_status_v2="PAPER TEST", test_lane="CLEAN",
    live_eligibility="PAPER_TEST_ALLOWED", required_capability="PAPER_SIM",
    risk_flag_count="0", risk_flags="none",
)
TACTICAL = dict(
    strategy_class_v2="TACTICAL", pair_status_v2="WATCHLIST",
    test_lane="RISKY_BUT_INTERESTING", live_eligibility="OBSERVE_ONLY",
    required_capability="OBSERVE", risk_flag_count="1",
    risk_flags="EXTREME_VOLATILITY",
)
REJECT = dict(
    strategy_class_v2="REJECT", pair_status_v2="REJECT", test_lane="QUARANTINE",
    live_eligibility="NOT_LIVE_ELIGIBLE", required_capability="NONE",
    risk_flag_count="1", risk_flags="LOW_LIQUIDITY",
)


class TestInputValidation(unittest.TestCase):
    def test_missing_input_file_fails(self):
        rc = arp.main(["--input", "/nonexistent/path/strategy.csv"])
        self.assertEqual(rc, 1)

    def test_missing_required_columns_fails(self):
        with tempfile.TemporaryDirectory() as d:
            inp = Path(d) / "in.csv"
            # Drop a required column (strategy_class_v2).
            cols = [c for c in INPUT_COLUMNS if c != "strategy_class_v2"]
            write_csv(inp, [make_row()], columns=cols)
            rc = arp.main(["--input", str(inp),
                           "--output", str(Path(d) / "out.csv"),
                           "--report", str(Path(d) / "rep.md")])
        self.assertEqual(rc, 1)

    def test_empty_data_fails(self):
        with tempfile.TemporaryDirectory() as d:
            inp = Path(d) / "in.csv"
            write_csv(inp, [])  # header only
            rc = arp.main(["--input", str(inp),
                           "--output", str(Path(d) / "out.csv"),
                           "--report", str(Path(d) / "rep.md")])
        self.assertEqual(rc, 1)


class TestDryRun(unittest.TestCase):
    def test_dry_run_writes_no_files(self):
        with tempfile.TemporaryDirectory() as d:
            inp = Path(d) / "in.csv"
            out = Path(d) / "out.csv"
            rep = Path(d) / "rep.md"
            write_csv(inp, [make_row(**CORE_CLEAN)])
            rc = arp.main(["--input", str(inp), "--output", str(out),
                           "--report", str(rep), "--dry-run"])
            self.assertEqual(rc, 0)
            self.assertFalse(out.exists())
            self.assertFalse(rep.exists())


class TestDecisionRules(unittest.TestCase):
    def test_reject_becomes_rejected(self):
        d = arp.decide_row(make_row(**REJECT))
        self.assertEqual(d["risk_decision"], "REJECTED")
        self.assertEqual(d["risk_action"], "REJECT")
        self.assertEqual(d["max_allowed_action"], "NONE")

    def test_malformed_pair_label_hard_blocks(self):
        # NOT_EVALUATED classification but malformed flag -> veto overrides.
        row = make_row(risk_flags="MALFORMED_PAIR_LABEL", risk_flag_count="1")
        d = arp.decide_row(row)
        self.assertEqual(d["risk_decision"], "BLOCKED")
        self.assertEqual(d["risk_action"], "FIX_DATA_OR_CLASSIFICATION")
        self.assertEqual(d["max_allowed_action"], "NONE")
        self.assertIn("MALFORMED_PAIR_LABEL", d["risk_blockers"])

    def test_blacklisted_hard_blocks(self):
        row = make_row(risk_flags="BLACKLISTED", risk_flag_count="1")
        d = arp.decide_row(row)
        self.assertEqual(d["risk_decision"], "BLOCKED")
        self.assertEqual(d["risk_action"], "REJECT")
        self.assertEqual(d["max_allowed_action"], "NONE")
        self.assertIn("BLACKLISTED", d["risk_blockers"])

    def test_not_evaluated_passthrough(self):
        d = arp.decide_row(make_row())  # neutral = NOT_EVALUATED
        self.assertEqual(d["risk_decision"], "NOT_EVALUATED")
        self.assertEqual(d["risk_action"], "NO_ACTION")
        self.assertEqual(d["max_allowed_action"], "NONE")

    def test_tactical_becomes_observe_only(self):
        d = arp.decide_row(make_row(**TACTICAL))
        self.assertEqual(d["risk_decision"], "OBSERVE_ONLY")
        self.assertEqual(d["risk_action"], "CONTINUE_OBSERVATION")
        self.assertEqual(d["max_allowed_action"], "OBSERVE_ONLY")

    def test_core_clean_becomes_paper_review_candidate(self):
        d = arp.decide_row(make_row(**CORE_CLEAN))
        self.assertEqual(d["risk_decision"], "PAPER_REVIEW_CANDIDATE")
        self.assertEqual(d["risk_action"], "REVIEW_FOR_FUTURE_PAPER_SIMULATION")
        self.assertEqual(d["max_allowed_action"], "FUTURE_PAPER_SIMULATION_REVIEW")

    def test_quarantine_blocks(self):
        # Quarantine lane but not classified REJECT -> BLOCKED veto.
        row = make_row(strategy_class_v2="TACTICAL", pair_status_v2="WATCHLIST",
                       test_lane="QUARANTINE", live_eligibility="OBSERVE_ONLY",
                       risk_flag_count="0", risk_flags="none")
        d = arp.decide_row(row)
        self.assertEqual(d["risk_decision"], "BLOCKED")
        self.assertEqual(d["max_allowed_action"], "NONE")

    def test_high_warning_downgrades_paper_to_observe(self):
        # CORE/CLEAN/PAPER_TEST_ALLOWED but a high-warning flag is present.
        row = make_row(**{**CORE_CLEAN, "risk_flags": "LOW_LIQUIDITY",
                          "risk_flag_count": "1"})
        d = arp.decide_row(row)
        self.assertNotEqual(d["risk_decision"], "PAPER_REVIEW_CANDIDATE")
        self.assertEqual(d["risk_decision"], "OBSERVE_ONLY")
        self.assertEqual(d["max_allowed_action"], "OBSERVE_ONLY")
        self.assertIn("LOW_LIQUIDITY", d["risk_warnings"])


class TestOutputSafety(unittest.TestCase):
    def _run_full(self, d, rows):
        inp = Path(d) / "in.csv"
        out = Path(d) / "out.csv"
        rep = Path(d) / "rep.md"
        write_csv(inp, rows)
        rc = arp.main(["--input", str(inp), "--output", str(out),
                       "--report", str(rep)])
        self.assertEqual(rc, 0)
        return out, rep

    def test_output_has_no_forbidden_max_allowed_action(self):
        forbidden = ("PAPER_ENTRY", "LIVE_ENTRY", "LIVE_ELIGIBLE_",
                     "EXECUTE", "SWAP", "REBALANCE")
        rows = [make_row(**CORE_CLEAN), make_row(**TACTICAL), make_row(**REJECT),
                make_row(risk_flags="MALFORMED_PAIR_LABEL", risk_flag_count="1")]
        with tempfile.TemporaryDirectory() as d:
            out, _rep = self._run_full(d, rows)
            with out.open(newline="", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                self.assertIn("max_allowed_action", reader.fieldnames)
                values = set()
                for r in reader:
                    values.add(r["max_allowed_action"])
            for v in values:
                self.assertIn(v, arp.MAX_ALLOWED_ACTIONS)
                for bad in forbidden:
                    self.assertNotIn(bad, v)

    def test_no_signal_or_live_tokens_in_output(self):
        # Signal-engine candidate tokens must never appear anywhere.
        signal_tokens = ("ENTRY_CANDIDATE", "EXIT_CANDIDATE", "REBALANCE_CANDIDATE")
        # Concrete LIVE_ELIGIBLE_* *values* must never appear. (The bare prefix
        # with an asterisk is allowed: the safety banner states the prohibition
        # "No LIVE_ELIGIBLE_*", which is a negation, not a granted value.)
        live_values = ("LIVE_ELIGIBLE_TINY_SIZE", "LIVE_ELIGIBLE_LIMITED",
                       "LIVE_ELIGIBLE_FULL")
        rows = [make_row(**CORE_CLEAN), make_row(**TACTICAL), make_row(**REJECT)]
        with tempfile.TemporaryDirectory() as d:
            out, rep = self._run_full(d, rows)
            csv_text = out.read_text(encoding="utf-8")
            rep_text = rep.read_text(encoding="utf-8")
            for tok in signal_tokens + live_values:
                self.assertNotIn(tok, csv_text)
                self.assertNotIn(tok, rep_text)
            # No CSV cell may be marked live-eligible (strict prefix on cells).
            with out.open(newline="", encoding="utf-8") as f:
                for r in csv.DictReader(f):
                    for v in r.values():
                        self.assertFalse(v.startswith("LIVE_ELIGIBLE_"))

    def test_safety_banner_contains_all_boundary_terms(self):
        for term in [
            "READ_ONLY", "RESEARCH_ONLY", "SCREENING_ONLY", "PAPER_ONLY",
            "No wallet", "No private key", "No signing", "No swap", "No LP",
            "No rebalance", "No live execution", "No LIVE_ELIGIBLE_*",
        ]:
            self.assertIn(term, arp.SAFETY_BANNER)

    def test_report_includes_non_authorization_note(self):
        rows = [make_row(**CORE_CLEAN)]
        with tempfile.TemporaryDirectory() as d:
            _out, rep = self._run_full(d, rows)
            text = rep.read_text(encoding="utf-8")
            self.assertIn("does not authorize", text)
            self.assertIn("# Risk Decisions Report", text)
            self.assertIn(arp.SAFETY_BANNER, text)

    def test_every_decision_action_max_is_allowed_enum(self):
        rows = [make_row(**CORE_CLEAN), make_row(**TACTICAL), make_row(**REJECT),
                make_row(), make_row(risk_flags="BLACKLISTED", risk_flag_count="1")]
        for r in rows:
            d = arp.decide_row(r)
            self.assertIn(d["risk_decision"], arp.RISK_DECISIONS)
            self.assertIn(d["risk_action"], arp.RISK_ACTIONS)
            self.assertIn(d["max_allowed_action"], arp.MAX_ALLOWED_ACTIONS)


if __name__ == "__main__":
    unittest.main()
