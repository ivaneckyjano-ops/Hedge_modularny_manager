#!/usr/bin/env python3
"""
Rýchla scorecard pre Swing Hunter:
- načíta swing_hunter_log.csv
- bucketuje podľa zone (odvodené z SignalType/PctB) a trend (nevieme, zatiaľ placeholder '-')
- počíta hit-rate, priemerný PL pre exitované signály
"""
import csv
import sys
from collections import defaultdict

LOG_FILE = "swing_hunter_log.csv"


def bucket_pctb(pctb_str):
    try:
        val = float(pctb_str)
    except Exception:
        return "n/a"
    if val < 30:
        return "<30"
    if val < 80:
        return "30-80"
    if val < 100:
        return "80-100"
    return ">100"


def bucket_rsi(rsi_str):
    try:
        val = float(rsi_str)
    except Exception:
        return "n/a"
    if val < 30:
        return "<30"
    if val < 50:
        return "30-50"
    if val < 70:
        return "50-70"
    return ">=70"


def bucket_signal(sig):
    s = (sig or "").lower()
    if "strong buy" in s:
        return "strong_buy"
    if "vhodný vstup" in s or "buy" in s:
        return "buy"
    if "risk" in s or "riziko" in s:
        return "risk"
    if "take profit" in s or "exit" in s:
        return "exit"
    return "other"


def load_logs(path):
    rows = []
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for r in reader:
            rows.append(r)
    return rows


def main():
    try:
        rows = load_logs(LOG_FILE)
    except FileNotFoundError:
        print("Log file swing_hunter_log.csv not found.")
        sys.exit(1)

    agg = defaultdict(lambda: {"cnt": 0, "closed": 0, "pl_sum": 0.0})
    for r in rows:
        pctb_b = bucket_pctb(r.get("PercentB", ""))
        rsi_b = bucket_rsi(r.get("RSI", ""))
        sig_b = bucket_signal(r.get("SignalType", ""))
        key = (sig_b, pctb_b, rsi_b)
        agg[key]["cnt"] += 1
        final_pl = r.get("FinalPL")
        if final_pl:
            try:
                pl = float(final_pl)
                agg[key]["closed"] += 1
                agg[key]["pl_sum"] += pl
            except:
                pass

    print("sig_bucket,pctB_bucket,RSI_bucket,count,closed,avg_PL")
    for (sig_b, pctb_b, rsi_b), stats in sorted(agg.items()):
        closed = stats["closed"]
        avg_pl = stats["pl_sum"] / closed if closed else 0.0
        print(f"{sig_b},{pctb_b},{rsi_b},{stats['cnt']},{closed},{avg_pl:.2f}")


if __name__ == "__main__":
    main()
