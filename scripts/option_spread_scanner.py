#!/usr/bin/env python3
"""
Simple option spread scanner.
Scans a list of symbols and computes median option spread_pct for near expirations.
Outputs JSON with symbols sorted by median spread (ascending).

Usage:
  ./scripts/option_spread_scanner.py PORT SYMBOL1,SYMBOL2 --expiries 2 --top 20
"""
import sys
import json
import time
import math
import random
from pathlib import Path
from datetime import datetime

BASE_DIR = Path(__file__).resolve().parents[1]
venv_site = BASE_DIR / 'venv' / 'lib' / 'python3.12' / 'site-packages'
if venv_site.exists():
    sys.path.insert(0, str(venv_site))

from ib_insync import IB, Stock, Option

def safe_float(x):
    try:
        if x is None or (isinstance(x, float) and math.isnan(x)): return 0.0
        return float(x)
    except:
        return 0.0

def median(lst):
    if not lst: return None
    s = sorted(lst)
    n = len(s)
    mid = n//2
    if n % 2 == 1:
        return s[mid]
    return (s[mid-1] + s[mid]) / 2.0

def scan_symbols(port, symbols, expiries_count=2, top_n=20):
    ib = IB()
    try:
        ib.connect('127.0.0.1', int(port), clientId=random.randint(900, 999), timeout=15)
        results = []
        for sym in symbols:
            sym = sym.strip().upper()
            if not sym: continue
            try:
                stock = Stock(sym, 'SMART', 'USD')
                print(f"DEBUG: qualifying {sym}", file=sys.stderr)
                ib.qualifyContracts(stock)
                # get option chain metadata
                chains = ib.reqSecDefOptParams(stock.symbol, '', stock.secType, stock.conId)
                if not chains:
                    print(f"DEBUG: no chains for {sym}", file=sys.stderr)
                    continue
                chain = max([c for c in chains if c.multiplier == '100'], key=lambda c: len(c.expirations), default=chains[0])
                expirations = sorted(chain.expirations)
                # pick nearest expiries_count expirations within 1-120 days
                picked = []
                today = datetime.now()
                for e in expirations:
                    try:
                        d = (datetime.strptime(e, '%Y%m%d') - today).days
                        if 1 <= d <= 120:
                            picked.append((e, d))
                    except:
                        continue
                    if len(picked) >= expiries_count:
                        break
                if not picked:
                    # fallback: first expirations
                    picked = [(expirations[0], 0)] if expirations else []
                # gather strikes
                strikes = sorted(chain.strikes)
                
                # get underlying price (robustly)
                price = 0.0
                try:
                    # Try snapshot first
                    tickers = ib.reqTickers(stock)
                    if tickers:
                        t = tickers[0]
                        price = t.marketPrice()
                        if not price or math.isnan(price) or price <= 0:
                            price = t.close
                except:
                    pass

                if not price or price <= 0 or math.isnan(price):
                    # try historical close if market is closed
                    try:
                        bars = ib.reqHistoricalData(stock, endDateTime='', durationStr='5 D', barSizeSetting='1 day', whatToShow='TRADES', useRTH=True)
                        if bars:
                            price = bars[-1].close
                    except:
                        price = 0.0
                
                # Ensure price is not nan for JSON
                if price is None or math.isnan(price):
                    price = 0.0

                low_s = price * 0.7 if price > 0 else None
                high_s = price * 1.3 if price > 0 else None
                candidate_strikes = [s for s in strikes if (low_s is None or (low_s <= s <= high_s))]
                if not candidate_strikes:
                    candidate_strikes = strikes[:40]
                # sample a limited number
                if len(candidate_strikes) > 40:
                    step = max(1, len(candidate_strikes)//40)
                    candidate_strikes = candidate_strikes[::step]

                # build option contracts for picked expiries and candidate strikes (calls and puts not needed, use calls for spreads)
                contracts = []
                for exp, _ in picked:
                    for s in candidate_strikes:
                        contracts.append(Option(sym, exp, s, 'C', 'SMART'))

                qualified = ib.qualifyContracts(*contracts)
                tickers = []
                for i in range(0, len(qualified), 50):
                    tickers.extend(ib.reqTickers(*qualified[i:i+50]))
                    ib.sleep(0.5)

                spreads = []
                for t in tickers:
                    bid = safe_float(getattr(t, 'bid', 0))
                    ask = safe_float(getattr(t, 'ask', 0))
                    last = safe_float(getattr(t, 'last', 0))
                    if bid > 0 and ask > 0:
                        mid = (bid + ask) / 2.0
                        if mid > 0:
                            spread_pct = (ask - bid) / mid
                            spreads.append(spread_pct)
                    elif last > 0:
                        # treat no quotes as high spread
                        spreads.append(1.0)
                med = median(spreads) if spreads else None
                results.append({'symbol': sym, 'median_spread': med if med is not None else 999.0, 'samples': len(spreads), 'price': price})
            except Exception as e:
                print(f"DEBUG: scan error {sym}: {e}", file=sys.stderr)
                continue
        # sort by median_spread ascending
        results = sorted(results, key=lambda x: x['median_spread'])
        return results[:top_n]
    finally:
        if ib.isConnected():
            ib.disconnect()

def main():
    if len(sys.argv) < 3:
        print("Usage: option_spread_scanner.py PORT SYMBOL1,SYMBOL2 [...]", file=sys.stderr)
        sys.exit(1)
    port = sys.argv[1]
    syms_arg = sys.argv[2]
    symbols = syms_arg.split(',') if ',' in syms_arg else [syms_arg]
    expiries = 2
    top_n = 20
    # simple arg parsing
    for i, a in enumerate(sys.argv[3:], start=3):
        if a == '--expiries' and i+1 < len(sys.argv):
            expiries = int(sys.argv[i+1])
        if a == '--top' and i+1 < len(sys.argv):
            top_n = int(sys.argv[i+1])

    out = scan_symbols(port, symbols, expiries_count=expiries, top_n=top_n)
    print(json.dumps({'success': True, 'scanned': len(symbols), 'results': out}, indent=2))

if __name__ == '__main__':
    main()

