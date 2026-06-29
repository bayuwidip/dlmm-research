#!/usr/bin/env python3
"""
validate_watchlist.py — Validator untuk data/pools_watchlist.csv

Status proyek: RESEARCH-FIRST · PAPER-ONLY.
Skrip ini TIDAK melakukan trading, TIDAK menyentuh wallet, TIDAK butuh credential.
Tugasnya tunggal: memastikan watchlist CSV konsisten dan patuh aturan gate.

Exit code 0 = valid. Exit code 1 = ada error (dipakai GitHub Actions untuk gagal).
"""

import csv
import sys
from pathlib import Path

CSV_PATH = Path(__file__).resolve().parent.parent / "data" / "pools_watchlist.csv"

# Sentinel untuk data yang memang tidak tersedia di sumber (Meteora).
# Wajib ditulis eksplisit, bukan ditebak atau dikosongkan diam-diam.
NA = "DATA_NOT_AVAILABLE"

# Kolom wajib (urutan tidak harus sama; yang dicek keberadaannya).
REQUIRED_COLUMNS = [
    "tanggal", "pool", "pair", "mcap_usd", "holders", "volume_24h_usd",
    "active_tvl_usd", "fees_active_tvl_pct", "volatility_pct", "volatility_bucket",
    "total_lps", "organic_score", "supply_concentration",
    "score_safety", "score_liquidity", "score_fee", "score_volatility",
    "score_lp", "score_data", "score_total", "vol_gate_applied",
    "owner_scope_gate", "validation_gate", "max_allowed_action",
    "status", "alasan", "risiko_utama", "keputusan", "review_date",
]

ALLOWED_VOL_BUCKET = {"low", "moderate", "high", "extreme", NA}
ALLOWED_GATE = {"red", "green"}
LIVE_TOKENS = ("LIVE", "SMALL_LIVE", "SMALL LIVE", "DEPLOY", "EXECUTE")
FORBIDDEN_POOL_MARKERS = ("CONTOH", "SAMPLE", "TEST_FAKE")
STATUS_ORDER = {"REJECT": 0, "WATCHLIST": 1, "TOOL TEST": 1, "PAPER TEST": 2,
                "SMALL LIVE TEST": 3}



def is_number(value: str) -> bool:
    try:
        float(value)
        return True
    except (TypeError, ValueError):
        return False


def is_blank_or_na(value: str) -> bool:
    return value is None or value.strip() == "" or value.strip() == NA


def validate():
    errors = []
    warnings = []

    if not CSV_PATH.exists():
        print(f"FATAL: file tidak ditemukan: {CSV_PATH}")
        return 1

    with CSV_PATH.open(newline="", encoding="utf-8") as f:
        reader = csv.reader(f)
        rows = list(reader)

    if not rows:
        print("FATAL: CSV kosong.")
        return 1

    header = rows[0]
    data_rows = rows[1:]
    ncols = len(header)

    # 1) Kolom wajib tersedia
    missing = [c for c in REQUIRED_COLUMNS if c not in header]
    if missing:
        errors.append(f"Kolom wajib hilang: {missing}")
        # tanpa kolom wajib, pengecekan per-baris tidak andal
        _report(errors, warnings, len(data_rows))
        return 1

    idx = {name: header.index(name) for name in header}

    if not data_rows:
        warnings.append("Tidak ada baris data (hanya header). Belum ada pool dicatat.")
        _report(errors, warnings, 0)
        return 0 if not errors else 1

    for i, row in enumerate(data_rows, start=2):  # baris 2 = baris data pertama
        rid = f"baris {i}"

        # 2) jumlah kolom == header
        if len(row) != ncols:
            errors.append(f"{rid}: jumlah kolom {len(row)} != header {ncols}")
            continue  # baris rusak; skip cek lain agar tidak misleading

        def get(col):
            return row[idx[col]].strip()

        # 3) volatility_pct numerik jika terisi & bukan NA
        vpct = get("volatility_pct")
        if not is_blank_or_na(vpct) and not is_number(vpct):
            errors.append(f"{rid}: volatility_pct '{vpct}' tidak numerik")

        # 4) volatility_bucket dalam set yang diizinkan
        vbucket = get("volatility_bucket")
        if vbucket not in ALLOWED_VOL_BUCKET:
            errors.append(
                f"{rid}: volatility_bucket '{vbucket}' tidak valid "
                f"(boleh: {sorted(ALLOWED_VOL_BUCKET)})"
            )

        # 5) ethics_gate
        eg = get("owner_scope_gate")
        if eg not in ALLOWED_GATE:
            errors.append(f"{rid}: owner_scope_gate '{eg}' tidak valid (boleh: red/green)")

        # 6) validation_gate
        vg = get("validation_gate")
        if vg not in ALLOWED_GATE:
            errors.append(f"{rid}: validation_gate '{vg}' tidak valid (boleh: red/green)")

        # 7) validation_gate=red => max_allowed_action wajib PAPER_ONLY
        maa = get("max_allowed_action")
        if vg == "red" and maa != "PAPER_ONLY":
            errors.append(
                f"{rid}: validation_gate=red tetapi max_allowed_action='{maa}' "
                f"(wajib PAPER_ONLY)"
            )

        # 8) status=TOOL TEST => max_allowed_action tidak boleh mengandung live action
        status = get("status")
        if status == "TOOL TEST":
            maa_up = maa.upper()
            if any(tok in maa_up for tok in LIVE_TOKENS):
                errors.append(
                    f"{rid}: status=TOOL TEST tetapi max_allowed_action='{maa}' "
                    f"mengandung aksi live"
                )

        # 9) score_total numerik jika terisi
        st = get("score_total")
        if not is_blank_or_na(st) and not is_number(st):
            errors.append(f"{rid}: score_total '{st}' tidak numerik")

        # 10) Nama pool tidak boleh mengandung penanda sample/contoh/fake
        pool_name = (get("pool") + " " + get("pair")).upper()
        for marker in FORBIDDEN_POOL_MARKERS:
            if marker in pool_name:
                errors.append(
                    f"{rid}: nama pool mengandung '{marker}' — data contoh/sample "
                    f"tidak boleh ada di CSV produksi (online-only)"
                )

        # 11) Tidak boleh ada status yang mengandung 'LIVE' di fase ini
        if "LIVE" in status.upper():
            errors.append(
                f"{rid}: status '{status}' mengandung LIVE — dilarang di fase "
                f"sekarang (validation_gate=red)"
            )

        # 12) validation_gate=red => status tidak boleh SMALL LIVE TEST
        if vg == "red" and status == "SMALL LIVE TEST":
            errors.append(
                f"{rid}: validation_gate=red tetapi status=SMALL LIVE TEST (dilarang)"
            )

        # 13) volatility cap: bucket NA/high/extreme => status max WATCHLIST
        #     (kecuali REJECT, yang lebih konservatif dan boleh)
        if vbucket in ("DATA_NOT_AVAILABLE", "high", "extreme"):
            srank = STATUS_ORDER.get(status, 99)
            if srank > STATUS_ORDER["WATCHLIST"] and status != "REJECT":
                errors.append(
                    f"{rid}: volatility_bucket='{vbucket}' tetapi status='{status}' "
                    f"melebihi WATCHLIST (veto volatilitas dilanggar)"
                )

        # Cek lunak: owner_scope_gate=red juga sebaiknya PAPER_ONLY (peringatan, bukan error)
        if eg == "red" and maa != "PAPER_ONLY":
            warnings.append(
                f"{rid}: owner_scope_gate=red sebaiknya juga PAPER_ONLY (saat ini '{maa}')"
            )

    # 14) CSV tidak boleh hanya berisi baris contoh: jika SEMUA baris kena marker,
    #     itu sudah tertangkap per-baris di aturan 10. Tapi cek tambahan: CSV
    #     dengan 0 baris data nyata setelah filter contoh = belum ada data produksi.
    real_rows = 0
    for row in data_rows:
        if len(row) == ncols:
            name = (row[idx["pool"]] + " " + row[idx["pair"]]).upper()
            if not any(mk in name for mk in FORBIDDEN_POOL_MARKERS):
                real_rows += 1
    if data_rows and real_rows == 0:
        errors.append(
            "CSV hanya berisi baris contoh/sample — belum ada data pool nyata. "
            "Jalankan fetch + build dengan API live."
        )

    _report(errors, warnings, len(data_rows))
    return 1 if errors else 0


def _report(errors, warnings, n_rows):
    print("=" * 60)
    print("  DLMM WATCHLIST VALIDATION")
    print("=" * 60)
    print(f"  File   : {CSV_PATH}")
    print(f"  Baris  : {n_rows} baris data")
    print("-" * 60)

    if warnings:
        print(f"  PERINGATAN ({len(warnings)}):")
        for w in warnings:
            print(f"    ! {w}")
        print("-" * 60)

    if errors:
        print(f"  GAGAL — {len(errors)} error:")
        for e in errors:
            print(f"    x {e}")
        print("=" * 60)
        print("  HASIL: TIDAK VALID")
        print("=" * 60)
    else:
        print("  Semua pemeriksaan lolos.")
        print("=" * 60)
        print("  HASIL: VALID")
        print("=" * 60)


PAIR_CSV_PATH = Path(__file__).resolve().parent.parent / "data" / "pair_watchlist.csv"

PAIR_REQUIRED_COLUMNS = [
    "pair_label", "pair_key", "pool_count", "total_tvl_usd",
    "total_volume_24h_usd", "total_fees_24h_usd",
    "eligible_fee_pool_count",
    "best_eligible_fee_tvl_pct_24h", "best_eligible_fee_tvl_decimal_24h",
    "best_eligible_fee_pool_address",
    "raw_max_fee_tvl_pct_24h", "raw_max_fee_tvl_decimal_24h",
    "fee_ratio_sanity_flag",
    "max_tvl_pool_address", "available_bin_steps", "min_mcap_usd", "min_holders",
    "verified_token_count", "unique_token_count", "blacklisted_pool_count",
    "score_liquidity", "score_volume", "score_fee", "score_token_quality",
    "score_pool_diversity", "score_data_quality", "pair_score_total", "pair_status",
    "validation_gate", "max_allowed_action",
    "total_lps", "organic_score", "volatility_pct",
]


def validate_pair_csv():
    """Validasi struktur pair_watchlist.csv. Mengembalikan exit code 0/1."""
    print("\n" + "=" * 60)
    print("  PAIR WATCHLIST VALIDATION")
    print("=" * 60)
    if not PAIR_CSV_PATH.exists():
        print(f"  CATATAN: {PAIR_CSV_PATH.name} belum ada (jalankan build dulu).")
        print("  Dilewati — bukan error jika build belum dijalankan.")
        return 0

    errors = []
    with PAIR_CSV_PATH.open(newline="", encoding="utf-8") as f:
        rows = list(csv.reader(f))
    if not rows:
        print("  FATAL: pair CSV kosong.")
        return 1
    header = rows[0]
    data_rows = rows[1:]
    ncols = len(header)

    missing = [c for c in PAIR_REQUIRED_COLUMNS if c not in header]
    if missing:
        errors.append(f"Kolom wajib hilang: {missing}")
        print(f"  GAGAL: {errors[0]}")
        return 1

    idx = {name: header.index(name) for name in header}
    int_cols = ["pool_count", "verified_token_count", "unique_token_count",
                "blacklisted_pool_count", "eligible_fee_pool_count", "score_liquidity", "score_volume",
                "score_fee", "score_token_quality", "score_pool_diversity",
                "score_data_quality"]
    num_or_na = ["total_tvl_usd", "total_volume_24h_usd", "total_fees_24h_usd",
                 "best_eligible_fee_tvl_pct_24h", "best_eligible_fee_tvl_decimal_24h",
                 "raw_max_fee_tvl_pct_24h", "raw_max_fee_tvl_decimal_24h",
                 "min_mcap_usd", "min_holders"]
    must_num = ["pair_score_total"]
    ALLOWED_SANITY = {"ok", "low_tvl_distortion", "no_eligible_fee_pool",
                      "DATA_NOT_AVAILABLE"}
    ALLOWED_PAIR_STATUS = {"REJECT", "WATCHLIST", "PAPER TEST"}

    for i, row in enumerate(data_rows, start=2):
        if len(row) != ncols:
            errors.append(f"baris {i}: jumlah kolom {len(row)} != header {ncols}")
            continue

        def get(col):
            return row[idx[col]].strip()

        for c in int_cols:
            v = get(c)
            if not is_number(v):
                errors.append(f"baris {i}: {c}='{v}' harus numerik")

        for c in num_or_na:
            v = get(c)
            if not is_blank_or_na(v) and not is_number(v):
                errors.append(f"baris {i}: {c}='{v}' harus numerik atau DATA_NOT_AVAILABLE")

        # pool_count minimal 1
        pc = get("pool_count")
        if is_number(pc) and float(pc) < 1:
            errors.append(f"baris {i}: pool_count {pc} < 1 (grup tak mungkin kosong)")

        # blacklisted tidak boleh > pool_count
        bl, pcn = get("blacklisted_pool_count"), get("pool_count")
        if is_number(bl) and is_number(pcn) and float(bl) > float(pcn):
            errors.append(f"baris {i}: blacklisted {bl} > pool_count {pcn} (mustahil)")

        # fee_ratio_sanity_flag harus dari set yang diizinkan
        sf = get("fee_ratio_sanity_flag")
        if sf not in ALLOWED_SANITY:
            errors.append(f"baris {i}: fee_ratio_sanity_flag '{sf}' tidak valid "
                          f"(boleh: {sorted(ALLOWED_SANITY)})")

        # eligible_fee_pool_count tidak boleh > pool_count
        ec = get("eligible_fee_pool_count")
        if is_number(ec) and is_number(pcn) and float(ec) > float(pcn):
            errors.append(f"baris {i}: eligible_fee_pool_count {ec} > pool_count {pcn}")

        # jika no_eligible_fee_pool, best_eligible harus NA & count 0
        if sf == "no_eligible_fee_pool":
            be = get("best_eligible_fee_tvl_pct_24h")
            if be != "DATA_NOT_AVAILABLE":
                errors.append(f"baris {i}: sanity=no_eligible tapi best_eligible_pct='{be}' "
                              f"(harus DATA_NOT_AVAILABLE)")

        # pair_score_total wajib numerik
        for c in must_num:
            v = get(c)
            if not is_number(v):
                errors.append(f"baris {i}: {c}='{v}' harus numerik")

        # pair_status dari set yang diizinkan (tidak ada SMALL LIVE TEST / live)
        ps = get("pair_status")
        if ps not in ALLOWED_PAIR_STATUS:
            errors.append(f"baris {i}: pair_status '{ps}' tidak valid "
                          f"(boleh: {sorted(ALLOWED_PAIR_STATUS)})")
        if "LIVE" in ps.upper():
            errors.append(f"baris {i}: pair_status '{ps}' mengandung LIVE (dilarang)")

        # eligible=0 ATAU sanity=no_eligible → tidak boleh PAPER TEST
        ec_val = get("eligible_fee_pool_count")
        if (is_number(ec_val) and float(ec_val) == 0) or sf == "no_eligible_fee_pool":
            if ps == "PAPER TEST":
                errors.append(f"baris {i}: eligible_fee_pool_count=0/no_eligible "
                              f"tetapi pair_status=PAPER TEST (maksimal WATCHLIST)")

        # blacklisted > 0 → harus REJECT
        if is_number(bl) and float(bl) > 0 and ps != "REJECT":
            errors.append(f"baris {i}: blacklisted>0 tetapi pair_status='{ps}' "
                          f"(harus REJECT)")

        # validation_gate=red → max_allowed_action=PAPER_ONLY
        vgate = get("validation_gate")
        maa = get("max_allowed_action")
        if vgate == "red" and maa != "PAPER_ONLY":
            errors.append(f"baris {i}: validation_gate=red tetapi max_allowed_action='{maa}'")

        # konsistensi pct/decimal: decimal ≈ pct/100 (toleransi)
        for pct_col, dec_col in [
            ("best_eligible_fee_tvl_pct_24h", "best_eligible_fee_tvl_decimal_24h"),
            ("raw_max_fee_tvl_pct_24h", "raw_max_fee_tvl_decimal_24h"),
        ]:
            pv, dv = get(pct_col), get(dec_col)
            if is_number(pv) and is_number(dv):
                expected = float(pv) / 100
                if abs(float(dv) - expected) > max(1e-6, abs(expected) * 1e-4):
                    errors.append(f"baris {i}: {dec_col}={dv} != {pct_col}/100={expected:.8f}")

    print(f"  File  : {PAIR_CSV_PATH.name}")
    print(f"  Baris : {len(data_rows)} pasangan")
    print("-" * 60)
    if errors:
        print(f"  GAGAL — {len(errors)} error:")
        for e in errors[:20]:
            print(f"    x {e}")
        print("  HASIL: TIDAK VALID")
        return 1
    print("  Semua pemeriksaan struktur pair lolos.")
    print("  HASIL: VALID")
    return 0



OHLCV_CSV_PATH = Path(__file__).resolve().parent.parent / "data" / "ohlcv_top_pairs.csv"

OHLCV_REQUIRED = [
    "pair", "representative_pool_address", "representative_pool_source",
    "pair_score_total", "pair_status",
    "ohlcv_status", "candle_count", "first_candle_time_utc", "last_candle_time_utc",
    "data_completeness_pct", "missing_candle_count",
    "first_close", "last_close", "min_low", "max_high",
    "pct_change_over_period", "high_low_range_pct", "realized_volatility_pct",
    "max_drawdown_pct", "max_runup_pct",
    "volatility_bucket", "range_risk_bucket", "trend_direction",
]
OHLCV_ALLOWED = {
    "ohlcv_status": {"OK", "DATA_NOT_AVAILABLE", "MALFORMED_RESPONSE", "API_ERROR"},
    "representative_pool_source": {"best_eligible_fee_pool_address",
                                   "max_tvl_pool_address", "DATA_NOT_AVAILABLE"},
    "volatility_bucket": {"LOW", "MODERATE", "HIGH", "EXTREME", "DATA_NOT_AVAILABLE"},
    "range_risk_bucket": {"LOW", "MODERATE", "HIGH", "EXTREME", "DATA_NOT_AVAILABLE"},
    "trend_direction": {"UP_STRONG", "UP", "SIDEWAYS", "DOWN", "DOWN_STRONG",
                        "DATA_NOT_AVAILABLE"},
}
OHLCV_NUM_OR_NA = [
    "pair_score_total", "candle_count", "data_completeness_pct",
    "missing_candle_count", "first_close", "last_close", "min_low", "max_high",
    "pct_change_over_period", "high_low_range_pct", "realized_volatility_pct",
    "max_drawdown_pct", "max_runup_pct",
]
# Tidak boleh ada field wallet/execution/live di OHLCV CSV
OHLCV_FORBIDDEN_COLS = ("wallet", "private_key", "signature", "execute",
                        "swap", "live")


def validate_ohlcv_csv():
    print("\n" + "=" * 60)
    print("  OHLCV TOP-PAIRS VALIDATION")
    print("=" * 60)
    if not OHLCV_CSV_PATH.exists():
        print(f"  CATATAN: {OHLCV_CSV_PATH.name} belum ada (jalankan OHLCV script).")
        print("  Dilewati — bukan error jika belum dijalankan.")
        return 0
    errors = []
    with OHLCV_CSV_PATH.open(newline="", encoding="utf-8") as f:
        rows = list(csv.reader(f))
    if not rows:
        print("  FATAL: OHLCV CSV kosong.")
        return 1
    header = rows[0]
    data_rows = rows[1:]
    ncols = len(header)

    missing = [c for c in OHLCV_REQUIRED if c not in header]
    if missing:
        print(f"  GAGAL: kolom wajib hilang: {missing}")
        return 1

    # cek tidak ada kolom terlarang
    for col in header:
        for bad in OHLCV_FORBIDDEN_COLS:
            if bad in col.lower():
                errors.append(f"kolom terlarang terdeteksi: '{col}' (mengandung '{bad}')")

    idx = {name: header.index(name) for name in header}
    for i, row in enumerate(data_rows, start=2):
        if len(row) != ncols:
            errors.append(f"baris {i}: jumlah kolom {len(row)} != header {ncols}")
            continue

        def get(col):
            return row[idx[col]].strip()

        for c in OHLCV_NUM_OR_NA:
            v = get(c)
            if not is_blank_or_na(v) and not is_number(v):
                errors.append(f"baris {i}: {c}='{v}' harus numerik atau DATA_NOT_AVAILABLE")

        for col, allowed in OHLCV_ALLOWED.items():
            v = get(col)
            if v not in allowed:
                errors.append(f"baris {i}: {col}='{v}' tidak valid "
                              f"(boleh: {sorted(allowed)})")

    print(f"  File  : {OHLCV_CSV_PATH.name}")
    print(f"  Baris : {len(data_rows)}")
    print("-" * 60)
    if errors:
        print(f"  GAGAL — {len(errors)} error:")
        for e in errors[:20]:
            print(f"    x {e}")
        print("  HASIL: TIDAK VALID")
        return 1
    print("  Semua pemeriksaan OHLCV lolos.")
    print("  HASIL: VALID")
    return 0


STRATEGY_V2_CSV_PATH = (Path(__file__).resolve().parent.parent / "data"
                        / "strategy_classification_v2.csv")

STRATEGY_V2_REQUIRED = [
    "pair_label", "pair_key", "representative_pool_address",
    "ohlcv_status", "ohlcv_volatility_bucket", "pair_score_total_v1",
    "strategy_class_v2", "pair_score_v2_core", "pair_score_v2_tactical",
    "pair_status_v2", "risk_flag_count", "risk_flags", "test_lane",
    "live_eligibility", "minimum_observation_days", "required_capability",
    "v2_classification_reason",
]
STRATEGY_V2_ALLOWED = {
    "strategy_class_v2": {"CORE", "TACTICAL", "REJECT", "NOT_EVALUATED"},
    "test_lane": {"CLEAN", "RISKY_BUT_INTERESTING", "QUARANTINE", "NOT_EVALUATED"},
    "live_eligibility": {"NOT_EVALUATED", "OBSERVE_ONLY", "PAPER_TEST_ALLOWED",
                         "NOT_LIVE_ELIGIBLE"},
    "required_capability": {"NONE", "OBSERVE", "PAPER_SIM"},
    "pair_status_v2": {"REJECT", "WATCHLIST", "PAPER TEST", "NOT_EVALUATED"},
}
# Fase PAPER_ONLY: nilai ini DILARANG muncul di kolom live_eligibility.
STRATEGY_V2_FORBIDDEN_LIVE = ("LIVE_ELIGIBLE_TINY_SIZE", "LIVE_ELIGIBLE_LIMITED",
                              "LIVE_ELIGIBLE_FULL")
# Capability yang dilarang sama sekali di fase ini (tidak ada eksekusi/wallet).
STRATEGY_V2_FORBIDDEN_CAP = ("WALLET", "EXECUTE", "SWAP", "LP", "REBALANCE", "SIGN")
# Flag berat yang membenarkan REJECT (REJECT tak boleh tanpa alasan berat).
STRATEGY_V2_SEVERE_FLAGS = {"BLACKLISTED", "NO_ELIGIBLE_FEE_POOL", "LOW_LIQUIDITY",
                            "LOW_VOLUME", "DATA_QUALITY_NA", "LOW_DATA_COMPLETENESS"}
STRATEGY_V2_NUM_OR_NA = ["pair_score_total_v1", "pair_score_v2_core",
                         "pair_score_v2_tactical"]
# Tidak boleh ada kolom wallet/execution/live di output v0.2.
STRATEGY_V2_FORBIDDEN_COLS = ("wallet", "private_key", "signature", "execute",
                              "swap", "live")


def validate_strategy_v2_csv():
    """Validasi struktur + gate strategy_classification_v2.csv. Exit code 0/1."""
    print("\n" + "=" * 60)
    print("  STRATEGY CLASSIFICATION v0.2 VALIDATION")
    print("=" * 60)
    if not STRATEGY_V2_CSV_PATH.exists():
        print(f"  CATATAN: {STRATEGY_V2_CSV_PATH.name} belum ada "
              f"(jalankan classify_strategy.py).")
        print("  Dilewati — bukan error jika belum dijalankan.")
        return 0

    errors = []
    with STRATEGY_V2_CSV_PATH.open(newline="", encoding="utf-8") as f:
        rows = list(csv.reader(f))
    if not rows:
        print("  FATAL: strategy v2 CSV kosong.")
        return 1
    header = rows[0]
    data_rows = rows[1:]
    ncols = len(header)

    missing = [c for c in STRATEGY_V2_REQUIRED if c not in header]
    if missing:
        print(f"  GAGAL: kolom wajib hilang: {missing}")
        return 1

    # kolom terlarang (wallet/execution/live) tidak boleh ada
    for col in header:
        for bad in STRATEGY_V2_FORBIDDEN_COLS:
            # 'live_eligibility' sah; hanya tandai jika 'live' berdiri sebagai
            # bagian nama kolom data on-chain (bukan substring eligibility).
            if bad == "live" and col == "live_eligibility":
                continue
            if bad in col.lower():
                errors.append(f"kolom terlarang terdeteksi: '{col}' (mengandung '{bad}')")

    idx = {name: header.index(name) for name in header}
    for i, row in enumerate(data_rows, start=2):
        if len(row) != ncols:
            errors.append(f"baris {i}: jumlah kolom {len(row)} != header {ncols}")
            continue

        def get(col):
            return row[idx[col]].strip()

        # 1) enum sah
        for col, allowed in STRATEGY_V2_ALLOWED.items():
            v = get(col)
            if v not in allowed:
                errors.append(f"baris {i}: {col}='{v}' tidak valid "
                              f"(boleh: {sorted(allowed)})")

        # 2) live_eligibility tidak boleh LIVE_ELIGIBLE_* (pengaman fase)
        le = get("live_eligibility")
        if le in STRATEGY_V2_FORBIDDEN_LIVE:
            errors.append(f"baris {i}: live_eligibility='{le}' DILARANG di fase ini")

        # 3) pair_status_v2 tidak boleh mengandung LIVE
        if "LIVE" in get("pair_status_v2").upper():
            errors.append(f"baris {i}: pair_status_v2 '{get('pair_status_v2')}' "
                          f"mengandung LIVE (dilarang)")

        # 4) required_capability tidak boleh kemampuan eksekusi/wallet
        cap = get("required_capability").upper()
        if any(tok in cap for tok in STRATEGY_V2_FORBIDDEN_CAP):
            errors.append(f"baris {i}: required_capability='{cap}' mengandung "
                          f"kemampuan terlarang")

        # 5) skor numerik atau NA
        for c in STRATEGY_V2_NUM_OR_NA:
            v = get(c)
            if not is_blank_or_na(v) and not is_number(v):
                errors.append(f"baris {i}: {c}='{v}' harus numerik atau DATA_NOT_AVAILABLE")

        # 6) minimum_observation_days: integer atau NA
        mod = get("minimum_observation_days")
        if not is_blank_or_na(mod):
            if not is_number(mod) or float(mod) != int(float(mod)):
                errors.append(f"baris {i}: minimum_observation_days='{mod}' "
                              f"harus integer atau DATA_NOT_AVAILABLE")

        # 7) risk_flag_count integer & cocok dengan jumlah token risk_flags
        rfc = get("risk_flag_count")
        flags_str = get("risk_flags")
        if not is_number(rfc) or float(rfc) != int(float(rfc)):
            errors.append(f"baris {i}: risk_flag_count='{rfc}' harus integer")
        else:
            n_tokens = 0 if flags_str in ("none", NA, "") else len(
                [t for t in flags_str.split("|") if t])
            if int(float(rfc)) != n_tokens:
                errors.append(f"baris {i}: risk_flag_count={rfc} != jumlah token "
                              f"risk_flags ({n_tokens})")

        cls = get("strategy_class_v2")

        # 8) NOT_EVALUATED harus konsisten (skor NA, lane/eligibility NOT_EVALUATED)
        if cls == "NOT_EVALUATED":
            if get("pair_score_v2_core") != NA or get("pair_score_v2_tactical") != NA:
                errors.append(f"baris {i}: NOT_EVALUATED tapi skor v2 bukan "
                              f"DATA_NOT_AVAILABLE")
            if get("test_lane") != "NOT_EVALUATED":
                errors.append(f"baris {i}: NOT_EVALUATED tapi test_lane="
                              f"'{get('test_lane')}'")
            if le != "NOT_EVALUATED":
                errors.append(f"baris {i}: NOT_EVALUATED tapi live_eligibility='{le}'")

        # 9) REJECT harus punya >=1 flag berat (REJECT tak boleh tanpa alasan berat)
        if cls == "REJECT":
            tokens = set(t for t in flags_str.split("|") if t)
            if not (tokens & STRATEGY_V2_SEVERE_FLAGS):
                errors.append(f"baris {i}: strategy_class_v2=REJECT tetapi tidak ada "
                              f"flag berat di risk_flags='{flags_str}'")
            if get("test_lane") != "QUARANTINE":
                errors.append(f"baris {i}: REJECT tapi test_lane bukan QUARANTINE")

        # 10) TACTICAL = reporting/watchlist only -> tidak boleh PAPER_TEST_ALLOWED
        if cls == "TACTICAL" and le == "PAPER_TEST_ALLOWED":
            errors.append(f"baris {i}: TACTICAL tidak boleh PAPER_TEST_ALLOWED "
                          f"(reporting/watchlist saja)")

    print(f"  File  : {STRATEGY_V2_CSV_PATH.name}")
    print(f"  Baris : {len(data_rows)}")
    print("-" * 60)
    if errors:
        print(f"  GAGAL — {len(errors)} error:")
        for e in errors[:20]:
            print(f"    x {e}")
        print("  HASIL: TIDAK VALID")
        return 1
    print("  Semua pemeriksaan strategy v0.2 lolos.")
    print("  HASIL: VALID")
    return 0


if __name__ == "__main__":
    rc_pool = validate()
    rc_pair = validate_pair_csv()
    rc_ohlcv = validate_ohlcv_csv()
    rc_strat = validate_strategy_v2_csv()
    sys.exit(rc_pool or rc_pair or rc_ohlcv or rc_strat)
