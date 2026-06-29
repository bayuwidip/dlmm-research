#!/usr/bin/env python3
"""
fetch_meteora_pools.py — ONLINE-ONLY data collector untuk DLMM Research.

Status: RESEARCH-FIRST · PAPER-ONLY. Read-only GET dari Meteora public datapi.
TIDAK ada wallet, private key, transaksi, atau execution.

ONLINE-ONLY: tidak ada offline mode, tidak ada synthetic/dummy data, tidak ada
fallback ke sample. Jika API gagal / kosong / format salah -> exit non-zero.

Sumber: https://dlmm.datapi.meteora.ag/pools (rate limit 30 RPS, no credential)

Output:
  data/raw/meteora_pools_raw_<UTC_timestamp>.json   (snapshot ber-timestamp)
  data/raw/meteora_pools_raw_latest.json            (pointer/salinan terbaru)
"""

import json
import sys
import time
import urllib.request
import urllib.error
from datetime import datetime, timezone
from pathlib import Path

BASE_URL = "https://dlmm.datapi.meteora.ag"
ROOT = Path(__file__).resolve().parent.parent
RAW_DIR = ROOT / "data" / "raw"
LOG_DIR = ROOT / "logs"
TIMEOUT = 30
USER_AGENT = "dlmm-research-collector/0.2 (read-only; research; online-only)"


def log(msg: str):
    ts = datetime.now(timezone.utc).isoformat()
    line = f"[{ts}] {msg}"
    print(line)
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    with (LOG_DIR / "collector.log").open("a", encoding="utf-8") as f:
        f.write(line + "\n")


def fetch_json(url: str):
    req = urllib.request.Request(url, method="GET", headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
        if resp.status != 200:
            raise RuntimeError(f"HTTP {resp.status} untuk {url}")
        return json.loads(resp.read().decode("utf-8"))


def fetch_pools(page_size: int = 100, max_pages: int = 3):
    all_pools = []
    for page in range(1, max_pages + 1):
        url = f"{BASE_URL}/pools?page={page}&page_size={page_size}&sort_by=volume_24h:desc"
        data = fetch_json(url)  # exception menggelembung ke main -> exit non-zero
        if not isinstance(data, dict) or "data" not in data:
            raise ValueError(f"Format response tak terduga di halaman {page}: "
                             f"bukan dict ber-key 'data'")
        batch = data.get("data", [])
        if not isinstance(batch, list):
            raise ValueError(f"Field 'data' bukan list di halaman {page}")
        all_pools.extend(batch)
        log(f"halaman {page}: {len(batch)} pool")
        time.sleep(0.5)
        if len(batch) < page_size:
            break
    return all_pools


def main():
    log("=== collector start (ONLINE-ONLY, read-only, no wallet, no execution) ===")
    try:
        pools = fetch_pools()
    except (urllib.error.URLError, urllib.error.HTTPError, RuntimeError,
            ValueError, TimeoutError, OSError) as e:
        log(f"FATAL: fetch gagal: {e}")
        log("Pipeline gagal sesuai desain — TIDAK ada fallback, TIDAK ada dummy data.")
        return 1

    if not pools:
        log("FATAL: API mengembalikan 0 pool. Kosong dianggap kegagalan (online-only).")
        return 1

    RAW_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    snapshot = {
        "fetched_at_utc": datetime.now(timezone.utc).isoformat(),
        "source": f"{BASE_URL}/pools",
        "pool_count": len(pools),
        "note": "raw read-only snapshot dari API live; tidak diolah.",
        "pools": pools,
    }
    payload = json.dumps(snapshot, indent=2)
    ts_path = RAW_DIR / f"meteora_pools_raw_{stamp}.json"
    latest_path = RAW_DIR / "meteora_pools_raw_latest.json"
    ts_path.write_text(payload, encoding="utf-8")
    latest_path.write_text(payload, encoding="utf-8")
    log(f"snapshot ditulis: {ts_path.name} + meteora_pools_raw_latest.json "
        f"({len(pools)} pool)")
    log("=== collector selesai OK ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
