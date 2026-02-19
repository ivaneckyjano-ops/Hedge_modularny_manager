#!/usr/bin/env python3
"""
Generate top-N symbols with smallest option spreads.
Uses scripts/option_spread_scanner.py in batches to compute median spreads,
then writes sorted top-N to cache/top_spread_symbols.json.

Usage:
  ./scripts/generate_top_spread_list.py PORT --symbols AAPL,MSFT,... --candidate-limit 1000 --batch-size 25 --top 100
  ./scripts/generate_top_spread_list.py PORT --symbol-file candidates.txt --top 100
"""
import sys
import os
import json
import time
import math
import subprocess
from pathlib import Path
from datetime import datetime

BASE_DIR = Path(__file__).resolve().parents[1]
CACHE_DIR = BASE_DIR / 'cache'
CACHE_DIR.mkdir(parents=True, exist_ok=True)
OUT_PATH = CACHE_DIR / 'top_spread_symbols.json'

DEFAULT_CANDIDATES = [
    "AAPL","MSFT","NVDA","GOOGL","AMZN","META","TSLA","SPY","QQQ","IVV",
    "AMD","BRK.B","JPM","V","UNH","HD","MA","BAC","GS","XOM","CVX","KO","MCD"
]

def load_candidates(args):
    if args.get('--symbols'):
        return [s.strip().upper() for s in args['--symbols'].split(',') if s.strip()]
    if args.get('--symbol-file'):
        p = Path(args['--symbol-file'])
        if p.exists():
            return [l.strip().upper() for l in p.read_text().splitlines() if l.strip()]
    # fallback: previous cache symbols
    if OUT_PATH.exists():
        try:
            data = json.loads(OUT_PATH.read_text())
            return [r['symbol'] for r in data.get('results', [])]
        except:
            pass
    return DEFAULT_CANDIDATES

def parse_args():
    args = {}
    it = iter(sys.argv[1:])
    for a in it:
        if a.startswith('--'):
            args[a] = next(it, None)
        else:
            # positional
            if 'PORT' not in args:
                args['PORT'] = a
            else:
                # ignore
                pass
    return args

def chunked(iterable, n):
    lst = list(iterable)
    for i in range(0, len(lst), n):
        yield lst[i:i+n]

def run_batch(port, symbols_chunk, expiries, top_n):
    cmd = [sys.executable, str(BASE_DIR / 'scripts' / 'option_spread_scanner.py'),
           str(port), ",".join(symbols_chunk), '--expiries', str(expiries), '--top', str(top_n)]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=300, cwd=str(BASE_DIR))
    if proc.returncode != 0:
        raise RuntimeError(f"Scanner failed: {proc.stderr.strip()[:200]}")
    return json.loads(proc.stdout)

def main():
    if len(sys.argv) < 2:
        print("Usage: generate_top_spread_list.py PORT [--symbols A,B,C | --symbol-file path] [--candidate-limit N] [--batch-size N] [--expiries N] [--top N]")
        sys.exit(1)
    args = parse_args()
    port = args.get('PORT')
    candidate_limit = int(args.get('--candidate-limit') or 1000)
    batch_size = int(args.get('--batch-size') or 25)
    expiries = int(args.get('--expiries') or 2)
    top_n = int(args.get('--top') or 100)

    candidates = load_candidates(args)
    if len(candidates) > candidate_limit:
        candidates = candidates[:candidate_limit]

    aggregated = {}
    scanned = 0
    for chunk in chunked(candidates, batch_size):
        try:
            print(f"DEBUG: scanning batch {scanned}..{scanned+len(chunk)-1} ({len(chunk)} symbols)", file=sys.stderr)
            out = run_batch(port, chunk, expiries, top_n)
            for item in out.get('results', []):
                sym = item['symbol']
                aggregated[sym] = {
                    'symbol': sym,
                    'median_spread': item.get('median_spread'),
                    'samples': item.get('samples'),
                    'price': item.get('price'),
                }
            scanned += len(chunk)
        except Exception as e:
            print(f"ERROR: batch failed: {e}", file=sys.stderr)
        time.sleep(0.6)  # pacing

    # sort and pick top_n with valid medians
    valid = [v for v in aggregated.values() if v.get('median_spread') is not None and not (isinstance(v.get('median_spread'), float) and math.isnan(v.get('median_spread')))]
    valid_sorted = sorted(valid, key=lambda x: x['median_spread'])
    top = valid_sorted[:top_n]

    result = {
        'generated_at': datetime.now().isoformat(),
        'source': {
            'candidate_count': len(candidates),
            'batch_size': batch_size,
            'expiries': expiries
        },
        'results': top
    }
    OUT_PATH.write_text(json.dumps(result, indent=2))
    print(json.dumps({'success': True, 'written': str(OUT_PATH), 'count': len(top)}))

if __name__ == '__main__':
    main()

