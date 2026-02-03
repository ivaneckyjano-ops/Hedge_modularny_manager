#!/usr/bin/env python3
"""
Jednoduchý paper backtest pre swing_trade_plans.csv:
- Načíta trade plany (Timestamp, Symbol, Entry, SL, TP1/TP2)
- Pre každý symbol použije cache/history/{symbol}_1_day.json (ak existuje)
- Simuluje, či by po čase Timestamp bolo zasiahnuté SL alebo TP (priorita: SL, potom TP2, potom TP1)
- Výsledok uloží do swing_backtest.csv

Poznámka: je to hrubý papierový backtest, pracuje len s dennými OHLC v cache.
"""
import csv
import json
import os
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.dirname(__file__))
PLANS_FILE = os.path.join(BASE_DIR, "swing_trade_plans.csv")
BACKTEST_OUT = os.path.join(BASE_DIR, "swing_backtest.csv")
CACHE_DIR = os.path.join(BASE_DIR, "cache", "history")


def load_plans(path):
    plans = []
    if not os.path.exists(path):
        return plans
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for r in reader:
            plans.append(r)
    return plans


def load_candles(symbol):
    fname = os.path.join(CACHE_DIR, f"{symbol}_1_day.json")
    if not os.path.exists(fname):
        return []
    with open(fname, encoding="utf-8") as f:
        data = json.load(f)
        return data.get("candles", [])


def parse_float(x):
    try:
        return float(str(x).replace("%", "").replace(",", "."))
    except Exception:
        return None


def backtest_plan(plan, candles):
    ts = plan.get("Timestamp", "")
    try:
        ts_dt = datetime.fromisoformat(ts)
    except Exception:
        ts_dt = None
    entry = parse_float(plan.get("Entry"))
    sl = parse_float(plan.get("SL"))
    tp1 = parse_float(plan.get("TP1"))
    tp2 = parse_float(plan.get("TP2"))
    if entry is None or sl is None or tp1 is None:
        return {"status": "skip", "reason": "missing prices"}

    def candle_time(c):
        try:
            return datetime.fromisoformat(str(c.get("time")))
        except Exception:
            return None

    future = []
    for c in candles:
        ct = candle_time(c)
        if ts_dt is None or (ct and ct >= ts_dt):
            future.append(c)

    if not future:
        return {"status": "skip", "reason": "no candles after ts"}

    for c in future:
        high = parse_float(c.get("high"))
        low = parse_float(c.get("low"))
        if high is None or low is None:
            continue
        # Priorita: SL -> TP2 -> TP1 (konzervatívne)
        if sl is not None and low <= sl:
            exit_price = sl
            pl_pct = (exit_price - entry) / entry * 100
            return {"status": "SL", "exit": exit_price, "pl_pct": pl_pct}
        if tp2 is not None and high >= tp2:
            exit_price = tp2
            pl_pct = (exit_price - entry) / entry * 100
            return {"status": "TP2", "exit": exit_price, "pl_pct": pl_pct}
        if tp1 is not None and high >= tp1:
            exit_price = tp1
            pl_pct = (exit_price - entry) / entry * 100
            return {"status": "TP1", "exit": exit_price, "pl_pct": pl_pct}

    # Nedosiahnuté
    last = future[-1]
    last_close = parse_float(last.get("close"))
    if last_close is not None:
        pl_pct = (last_close - entry) / entry * 100
        return {"status": "OPEN", "exit": last_close, "pl_pct": pl_pct}
    return {"status": "OPEN", "exit": "", "pl_pct": ""}


def main():
    plans = load_plans(PLANS_FILE)
    if not plans:
        print("No trade plans found.")
        return

    rows = []
    for p in plans:
        sym = p.get("Symbol")
        if not sym:
            continue
        candles = load_candles(sym)
        result = backtest_plan(p, candles)
        row = dict(p)
        row.update({
            "BT_Status": result.get("status"),
            "BT_Exit": result.get("exit"),
            "BT_PL_pct": result.get("pl_pct"),
            "BT_Reason": result.get("reason", "")
        })
        rows.append(row)

    fieldnames = list(rows[0].keys()) if rows else []
    with open(BACKTEST_OUT, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    print(f"Backtest saved to {BACKTEST_OUT}, rows: {len(rows)}")


if __name__ == "__main__":
    main()
