#!/usr/bin/env python3
"""
fetch_ohlcv_top_pairs.py — OHLCV tool-test untuk Top 20 pair candidates.

Status: RESEARCH-FIRST · PAPER-ONLY · read-only GET. Tidak ada wallet, private
key, transaction signing, execution, atau scoring. Ini HANYA validasi data:
apakah OHLCV tersedia per pool, dan seperti apa volatilitas/range-risk-nya.

CATATAN STRUKTUR RESPONSE:
  Skrip ini TIDAK mengasumsikan format secara diam-diam. Ia memeriksa bentuk
  response sebelum parse. Berdasarkan skema datapi terdokumentasi, response
  diharapkan: {"start_time","end_time","timeframe","data":[{timestamp, open,
  high, low, close, volume}, ...]}. Jika bentuk berbeda → MALFORMED_RESPONSE,
  bukan crash, bukan nilai palsu. Beberapa kemungkinan bentuk alternatif
  (list langsung, atau key 'candles') juga dicoba secara defensif.

Sumber: https://dlmm.datapi.meteora.ag/pools/{address}/ohlcv
"""

import csv
import json
import math
import sys
import time
import urllib.request
import urllib.error
from datetime import datetime, timezone
from pathlib import Path

BASE_URL = "https://dlmm.datapi.meteora.ag"
ROOT = Path(__file__).resolve().parent.parent
PAIR_CSV = ROOT / "data" / "pair_watchlist.csv"
OUT_CSV = ROOT / "data" / "ohlcv_top_pairs.csv"
RAW_DIR = ROOT / "data" / "raw"
REPORT_PATH = ROOT / "reports" / "ohlcv_report.md"
LOG_DIR = ROOT / "logs"

NA = "DATA_NOT_AVAILABLE"
TIMEOUT = 30
USER_AGENT = "dlmm-research-ohlcv/0.1 (read-only; research)"
TIMEFRAME = "1h"
LOOKBACK_HOURS = 72
TOP_N = 20

OUT_HEADER = [
    "pair", "representative_pool_address", "representative_pool_source",
    "pair_score_total", "pair_status",
    "ohlcv_status", "candle_count", "first_candle_time_utc", "last_candle_time_utc",
    "data_completeness_pct", "missing_candle_count",
    "first_close", "last_close", "min_low", "max_high",
    "pct_change_over_period", "high_low_range_pct", "realized_volatility_pct",
    "max_drawdown_pct", "max_runup_pct",
    "volatility_bucket", "range_risk_bucket", "trend_direction",
]


def log(msg):
    ts = datetime.now(timezone.utc).isoformat()
    line = f"[{ts}] {msg}"
    print(line)
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    with (LOG_DIR / "ohlcv_collector.log").open("a", encoding="utf-8") as f:
        f.write(line + "\n")


def fetch_json(url):
    req = urllib.request.Request(url, method="GET", headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
        if resp.status != 200:
            raise RuntimeError(f"HTTP {resp.status}")
        return json.loads(resp.read().decode("utf-8"))


def extract_candles(raw):
    """
    Defensif: coba beberapa bentuk response yang mungkin tanpa mengasumsikan satu.
    Mengembalikan (candles_list, None) jika berhasil, atau (None, alasan) jika
    bentuk tak dikenali.
    """
    if raw is None:
        return None, "response None"
    # bentuk 1 (terdokumentasi): {"data": [ {open,high,low,close,...}, ... ]}
    if isinstance(raw, dict):
        for key in ("data", "candles", "ohlcv"):
            if isinstance(raw.get(key), list):
                return raw[key], None
        # bentuk: dict tapi tak ada list candle yang dikenali
        return None, f"dict tanpa key candle dikenal (keys={list(raw.keys())[:6]})"
    # bentuk 2: list langsung
    if isinstance(raw, list):
        return raw, None
    return None, f"tipe tak terduga: {type(raw).__name__}"


def candle_field(c, *names):
    """Ambil field candle dari beberapa kemungkinan nama, sebagai float."""
    if not isinstance(c, dict):
        return None
    for n in names:
        if n in c:
            try:
                return float(c[n])
            except (TypeError, ValueError):
                return None
    return None


def compute_metrics(candles):
    """Hitung metrik volatilitas/range dari list candle. Defensif terhadap field."""
    closes, highs, lows, times = [], [], [], []
    for c in candles:
        cl = candle_field(c, "close", "c")
        hi = candle_field(c, "high", "h")
        lo = candle_field(c, "low", "l")
        ts = None
        if isinstance(c, dict):
            ts = c.get("timestamp") or c.get("time") or c.get("t")
        if cl is None or hi is None or lo is None:
            continue
        closes.append(cl)
        highs.append(hi)
        lows.append(lo)
        times.append(ts)
    if len(closes) < 2:
        return None  # tidak cukup untuk metrik

    first_close = closes[0]
    last_close = closes[-1]
    min_low = min(lows)
    max_high = max(highs)

    pct_change = ((last_close - first_close) / first_close * 100
                  if first_close else None)
    hl_range = ((max_high - min_low) / min_low * 100 if min_low else None)

    # realized volatility: stdev of log returns, dalam persen (per periode total)
    rets = []
    for i in range(1, len(closes)):
        if closes[i - 1] > 0 and closes[i] > 0:
            rets.append(math.log(closes[i] / closes[i - 1]))
    if len(rets) >= 2:
        mean = sum(rets) / len(rets)
        var = sum((r - mean) ** 2 for r in rets) / (len(rets) - 1)
        # volatilitas per-candle dalam %, lalu skalakan ke periode (sqrt n)
        rv = math.sqrt(var) * math.sqrt(len(rets)) * 100
    else:
        rv = None

    # max drawdown & runup atas closes
    peak = closes[0]
    trough = closes[0]
    max_dd = 0.0
    max_ru = 0.0
    for c in closes:
        if c > peak:
            peak = c
        dd = (peak - c) / peak * 100 if peak else 0
        max_dd = max(max_dd, dd)
        if c < trough:
            trough = c
        ru = (c - trough) / trough * 100 if trough else 0
        max_ru = max(max_ru, ru)

    def fmt_time(ts):
        if ts is None:
            return NA
        try:
            # timestamp bisa detik atau milidetik
            t = float(ts)
            if t > 1e12:
                t /= 1000
            return datetime.fromtimestamp(t, timezone.utc).isoformat()
        except (TypeError, ValueError, OSError):
            return str(ts)

    return {
        "candle_count": len(closes),
        "first_candle_time_utc": fmt_time(times[0]),
        "last_candle_time_utc": fmt_time(times[-1]),
        "first_close": round(first_close, 8),
        "last_close": round(last_close, 8),
        "min_low": round(min_low, 8),
        "max_high": round(max_high, 8),
        "pct_change_over_period": round(pct_change, 4) if pct_change is not None else NA,
        "high_low_range_pct": round(hl_range, 4) if hl_range is not None else NA,
        "realized_volatility_pct": round(rv, 4) if rv is not None else NA,
        "max_drawdown_pct": round(max_dd, 4),
        "max_runup_pct": round(max_ru, 4),
    }


def vol_bucket(rv):
    if not isinstance(rv, (int, float)):
        return NA
    if rv < 3:
        return "LOW"
    if rv < 8:
        return "MODERATE"
    if rv < 15:
        return "HIGH"
    return "EXTREME"


def range_bucket(hl):
    if not isinstance(hl, (int, float)):
        return NA
    if hl < 5:
        return "LOW"
    if hl < 15:
        return "MODERATE"
    if hl < 30:
        return "HIGH"
    return "EXTREME"


def trend_dir(pct):
    if not isinstance(pct, (int, float)):
        return NA
    if pct > 5:
        return "UP_STRONG"
    if pct > 1:
        return "UP"
    if -1 <= pct <= 1:
        return "SIDEWAYS"
    if pct < -5:
        return "DOWN_STRONG"
    return "DOWN"


def select_candidates():
    """Pilih Top 20 pair: status PAPER TEST/WATCHLIST, sort by score desc."""
    if not PAIR_CSV.exists():
        return None
    with PAIR_CSV.open(newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    cands = [r for r in rows if r.get("pair_status") in ("PAPER TEST", "WATCHLIST")]

    def score(r):
        try:
            return float(r["pair_score_total"])
        except (TypeError, ValueError, KeyError):
            return -1
    cands.sort(key=score, reverse=True)
    return cands[:TOP_N]


def pick_pool(row):
    """Pilih representative pool: best_eligible dulu, fallback max_tvl."""
    be = row.get("best_eligible_fee_pool_address", "")
    if be and be != NA:
        return be, "best_eligible_fee_pool_address"
    mt = row.get("max_tvl_pool_address", "")
    if mt and mt != NA:
        return mt, "max_tvl_pool_address"
    return NA, NA


def fetch_one(addr):
    """
    Fetch OHLCV satu pool. Mengembalikan (status, candles_or_None, raw).
    status: OK / DATA_NOT_AVAILABLE / MALFORMED_RESPONSE / API_ERROR
    """
    end = int(datetime.now(timezone.utc).timestamp())
    start = end - LOOKBACK_HOURS * 3600
    url = (f"{BASE_URL}/pools/{addr}/ohlcv"
           f"?timeframe={TIMEFRAME}&start_time={start}&end_time={end}")
    try:
        raw = fetch_json(url)
    except (urllib.error.HTTPError, urllib.error.URLError, RuntimeError,
            TimeoutError, OSError) as e:
        log(f"  API_ERROR {addr[:10]}: {type(e).__name__} {str(e)[:60]}")
        return "API_ERROR", None, None
    except json.JSONDecodeError as e:
        log(f"  MALFORMED {addr[:10]}: JSON decode {str(e)[:50]}")
        return "MALFORMED_RESPONSE", None, None

    candles, reason = extract_candles(raw)
    if candles is None:
        log(f"  MALFORMED {addr[:10]}: {reason}")
        return "MALFORMED_RESPONSE", None, raw
    if len(candles) == 0:
        log(f"  DATA_NOT_AVAILABLE {addr[:10]}: 0 candle")
        return "DATA_NOT_AVAILABLE", None, raw
    return "OK", candles, raw


def main():
    log("=== OHLCV tool-test start (read-only, no wallet, no execution) ===")
    cands = select_candidates()
    if cands is None:
        log("FATAL: data/pair_watchlist.csv tidak ada.")
        return 1
    if not cands:
        log("FATAL: tidak ada kandidat valid (PAPER TEST/WATCHLIST) di pair_watchlist.")
        return 1
    log(f"kandidat terpilih: {len(cands)} pasangan (Top {TOP_N})")

    out_rows = []
    raw_store = {}
    expected_candles = LOOKBACK_HOURS  # 1h interval, 72h → ~72 candle

    for row in cands:
        pair = row.get("pair_label", NA)
        addr, source = pick_pool(row)
        base = {
            "pair": pair,
            "representative_pool_address": addr,
            "representative_pool_source": source,
            "pair_score_total": row.get("pair_score_total", NA),
            "pair_status": row.get("pair_status", NA),
            "ohlcv_status": NA, "candle_count": NA,
            "first_candle_time_utc": NA, "last_candle_time_utc": NA,
            "data_completeness_pct": NA, "missing_candle_count": NA,
            "first_close": NA, "last_close": NA, "min_low": NA, "max_high": NA,
            "pct_change_over_period": NA, "high_low_range_pct": NA,
            "realized_volatility_pct": NA, "max_drawdown_pct": NA, "max_runup_pct": NA,
            "volatility_bucket": NA, "range_risk_bucket": NA, "trend_direction": NA,
        }

        if addr == NA:
            base["ohlcv_status"] = "DATA_NOT_AVAILABLE"
            log(f"{pair}: tidak ada representative pool address")
            out_rows.append(base)
            continue

        status, candles, raw = fetch_one(addr)
        base["ohlcv_status"] = status
        if raw is not None:
            raw_store[addr] = raw
        time.sleep(0.4)  # hormati rate limit

        if status != "OK":
            out_rows.append(base)
            continue

        m = compute_metrics(candles)
        if m is None:
            base["ohlcv_status"] = "MALFORMED_RESPONSE"
            base["candle_count"] = len(candles)
            log(f"{pair}: candle ada tapi field tidak cukup untuk metrik")
            out_rows.append(base)
            continue

        base.update(m)
        cc = m["candle_count"]
        missing = max(0, expected_candles - cc)
        base["missing_candle_count"] = missing
        base["data_completeness_pct"] = round(min(100.0, cc / expected_candles * 100), 2)
        base["volatility_bucket"] = vol_bucket(m["realized_volatility_pct"])
        base["range_risk_bucket"] = range_bucket(m["high_low_range_pct"])
        base["trend_direction"] = trend_dir(m["pct_change_over_period"])
        log(f"{pair}: OK {cc} candle, vol={base['volatility_bucket']}, "
            f"range={base['range_risk_bucket']}, trend={base['trend_direction']}")
        out_rows.append(base)

    # tulis CSV
    try:
        OUT_CSV.parent.mkdir(parents=True, exist_ok=True)
        with OUT_CSV.open("w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=OUT_HEADER)
            w.writeheader()
            for r in out_rows:
                w.writerow({k: r.get(k, NA) for k in OUT_HEADER})
    except OSError as e:
        log(f"FATAL: tidak bisa menulis {OUT_CSV.name}: {e}")
        return 1

    # simpan raw
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    raw_payload = json.dumps({
        "fetched_at_utc": datetime.now(timezone.utc).isoformat(),
        "source": f"{BASE_URL}/pools/{{address}}/ohlcv",
        "timeframe": TIMEFRAME, "lookback_hours": LOOKBACK_HOURS,
        "raw_by_pool": raw_store,
    }, indent=2, default=str)
    (RAW_DIR / f"ohlcv_top_pairs_raw_{stamp}.json").write_text(raw_payload, encoding="utf-8")
    (RAW_DIR / "ohlcv_top_pairs_raw_latest.json").write_text(raw_payload, encoding="utf-8")

    write_report(out_rows)
    log(f"OHLCV CSV ditulis: {OUT_CSV.name} ({len(out_rows)} baris)")
    log("=== OHLCV tool-test selesai ===")
    return 0


def write_report(rows):
    from collections import Counter
    status_counts = Counter(r["ohlcv_status"] for r in rows)
    lines = []
    lines.append("# OHLCV Tool-Test Report")
    lines.append("")
    lines.append(f"- Run timestamp (UTC): {datetime.now(timezone.utc).isoformat()}")
    lines.append(f"- Candidate pairs selected: {len(rows)}")
    lines.append(f"- Timeframe: {TIMEFRAME} | Lookback: {LOOKBACK_HOURS}h")
    lines.append("")
    lines.append("## Rows by ohlcv_status")
    for st in ("OK", "DATA_NOT_AVAILABLE", "API_ERROR", "MALFORMED_RESPONSE"):
        lines.append(f"- {st}: {status_counts.get(st, 0)}")
    lines.append("")
    lines.append("## Top 20 OHLCV Tool-Test")
    lines.append("")
    lines.append("| Pair | Score | Pair Status | OHLCV Status | Pool | Candles | %Chg | HL Range% | RV% | Vol | Range | Trend |")
    lines.append("|---|---:|---|---|---|---:|---:|---:|---:|---|---|---|")
    for r in rows:
        addr = r["representative_pool_address"]
        addr_short = addr[:8] + "…" if isinstance(addr, str) and len(addr) > 10 else addr
        lines.append(
            f"| {r['pair']} | {r['pair_score_total']} | {r['pair_status']} "
            f"| {r['ohlcv_status']} "
            f"| {addr_short} | {r['candle_count']} | {r['pct_change_over_period']} "
            f"| {r['high_low_range_pct']} | {r['realized_volatility_pct']} "
            f"| {r['volatility_bucket']} | {r['range_risk_bucket']} | {r['trend_direction']} |"
        )
    lines.append("")
    lines.append("## Data quality notes")
    lines.append("")
    ok = status_counts.get("OK", 0)
    if ok == 0:
        lines.append("- **Tidak ada pool yang mengembalikan OHLCV OK.** Kemungkinan: "
                     "endpoint OHLCV tidak tersedia, format berbeda, atau diblokir di "
                     "lingkungan ini. Periksa logs/ohlcv_collector.log untuk detail. "
                     "Tidak ada nilai yang dipalsukan — baris ditandai status sebenarnya.")
    else:
        lines.append(f"- {ok} pool mengembalikan OHLCV valid. Metrik dihitung dari "
                     "candle nyata.")
    lines.append(f"- Expected candles per pool (1h × 72h): ~{LOOKBACK_HOURS}. "
                 "`data_completeness_pct` mengukur cakupan terhadap angka ini.")
    lines.append("- Jika struktur response berbeda dari skema terdokumentasi, baris "
                 "ditandai MALFORMED_RESPONSE — bukan ditebak.")
    lines.append("")
    lines.append("---")
    lines.append("**OHLCV report is not a live signal. It is a volatility and "
                 "data-quality tool test only. No wallet, no execution, no trading action.**")
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text("\n".join(lines), encoding="utf-8")


if __name__ == "__main__":
    sys.exit(main())
