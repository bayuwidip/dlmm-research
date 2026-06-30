import unittest

from scripts.observe_strategy import (
    HARD_BLOCK_FLAGS,
    is_clean_core_record,
    is_malformed_pair_label,
    normalize_row,
    parse_flags,
    summarize_observations,
)


BASE_ROW = {
    "pair_label": "USDC-SOL",
    "pair_key": "mintA|mintB",
    "representative_pool_address": "pool1",
    "ohlcv_status": "OK",
    "ohlcv_volatility_bucket": "MODERATE",
    "pair_score_total_v1": "94.0",
    "strategy_class_v2": "CORE",
    "pair_score_v2_core": "89.0",
    "pair_score_v2_tactical": "84.0",
    "pair_status_v2": "PAPER TEST",
    "risk_flag_count": "0",
    "risk_flags": "none",
    "test_lane": "CLEAN",
    "live_eligibility": "PAPER_TEST_ALLOWED",
    "minimum_observation_days": "14",
    "required_capability": "PAPER_SIM",
    "v2_classification_reason": "test",
}


class ObserveStrategyTests(unittest.TestCase):
    def test_parse_flags(self):
        self.assertEqual(parse_flags("none"), [])
        self.assertEqual(parse_flags("LOW_VOLUME|OHLCV_UNAVAILABLE"), ["LOW_VOLUME", "OHLCV_UNAVAILABLE"])

    def test_malformed_pair_label(self):
        self.assertTrue(is_malformed_pair_label("-USDT"))
        self.assertTrue(is_malformed_pair_label("USDC-"))
        self.assertTrue(is_malformed_pair_label(""))
        self.assertFalse(is_malformed_pair_label("USDC-SOL"))

    def test_normalize_adds_malformed_flag(self):
        row = dict(BASE_ROW)
        row["pair_label"] = "-USDT"
        row["strategy_class_v2"] = "REJECT"
        row["pair_status_v2"] = "REJECT"
        row["live_eligibility"] = "NOT_LIVE_ELIGIBLE"
        row["test_lane"] = "QUARANTINE"
        out = normalize_row(row, "2026-06-30T00:00:00+00:00")
        self.assertIn("MALFORMED_PAIR_LABEL", out["risk_flags"])

    def test_forbidden_live_eligibility_rejected(self):
        row = dict(BASE_ROW)
        row["live_eligibility"] = "LIVE_ELIGIBLE_FULL"
        with self.assertRaises(ValueError):
            normalize_row(row, "2026-06-30T00:00:00+00:00")

    def test_clean_core_record(self):
        row = normalize_row(BASE_ROW, "2026-06-30T00:00:00+00:00")
        self.assertTrue(is_clean_core_record(row))

    def test_core_ready_after_7_clean_runs(self):
        rows = []
        for i in range(7):
            row = normalize_row(BASE_ROW, f"2026-06-30T00:00:0{i}+00:00")
            rows.append(row)

        summaries = summarize_observations(rows)
        self.assertEqual(len(summaries), 1)
        self.assertTrue(summaries[0].observation_ready)
        self.assertEqual(summaries[0].consecutive_clean_core_runs, 7)

    def test_core_not_ready_before_7_clean_runs(self):
        rows = []
        for i in range(6):
            row = normalize_row(BASE_ROW, f"2026-06-30T00:00:0{i}+00:00")
            rows.append(row)

        summaries = summarize_observations(rows)
        self.assertFalse(summaries[0].observation_ready)
        self.assertEqual(summaries[0].observation_status, "CORE_OBSERVING")

    def test_hard_block_ever_blocks(self):
        rows = []
        for i in range(7):
            row = dict(BASE_ROW)
            if i == 2:
                row["risk_flags"] = "MALFORMED_PAIR_LABEL"
                row["risk_flag_count"] = "1"
                row["strategy_class_v2"] = "REJECT"
                row["pair_status_v2"] = "REJECT"
                row["test_lane"] = "QUARANTINE"
                row["live_eligibility"] = "NOT_LIVE_ELIGIBLE"
            rows.append(normalize_row(row, f"2026-06-30T00:00:0{i}+00:00"))

        summaries = summarize_observations(rows)
        self.assertFalse(summaries[0].observation_ready)
        self.assertEqual(summaries[0].observation_status, "BLOCKED")
        self.assertTrue(summaries[0].hard_block_ever)

    def test_tactical_remains_observe_only(self):
        row = dict(BASE_ROW)
        row["strategy_class_v2"] = "TACTICAL"
        row["pair_status_v2"] = "WATCHLIST"
        row["test_lane"] = "RISKY_BUT_INTERESTING"
        row["live_eligibility"] = "OBSERVE_ONLY"
        row["required_capability"] = "TACTICAL_OBSERVER"

        rows = [normalize_row(row, f"2026-06-30T00:00:{i:02d}+00:00") for i in range(30)]
        summaries = summarize_observations(rows)

        self.assertFalse(summaries[0].observation_ready)
        self.assertEqual(summaries[0].observation_status, "TACTICAL_STABLE_BUT_OBSERVE_ONLY")
        self.assertEqual(summaries[0].consecutive_clean_tactical_runs, 30)


if __name__ == "__main__":
    unittest.main()
