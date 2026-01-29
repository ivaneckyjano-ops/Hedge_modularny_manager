#!/usr/bin/env python3
import argparse
import sys
import json
import os
from pathlib import Path

# Pridanie cesty k venv
BASE_DIR = Path(__file__).resolve().parents[1]
venv_site = BASE_DIR / 'venv' / 'lib' / 'python3.12' / 'site-packages'
if venv_site.exists():
    sys.path.insert(0, str(venv_site))

from ib_insync import IB, Stock, util

def main():
    parser = argparse.ArgumentParser(description='Fetch historical candles from TWS')
    parser.add_argument('--symbol', required=True)
    parser.add_argument('--duration', default='2 D', help='Duration (e.g. 2 D, 1 W)')
    parser.add_argument('--barSize', default='1 hour', help='Bar size (e.g. 15 mins, 1 hour)')
    parser.add_argument('--port', type=int, default=7497)
    parser.add_argument('--force', action='store_true', help='Bypass cache and fetch fresh data')
    
    args = parser.parse_args()

    # --- LOGIKA CACHE ---
    cache_dir = BASE_DIR / 'cache' / 'history'
    cache_file = cache_dir / f"{args.symbol}_{args.barSize.replace(' ', '_')}.json"
    
    # Definujeme životnosť cache podľa timeframe (v sekundách)
    ttl = 900 # Default 15 min
    if "15 mins" in args.barSize: ttl = 300
    elif "1 hour" in args.barSize: ttl = 900
    elif "4 hours" in args.barSize: ttl = 1800
    elif "day" in args.barSize: ttl = 7200

    if not args.force and cache_file.exists():
        import time
        mtime = os.path.getmtime(cache_file)
        if (time.time() - mtime) < ttl:
            try:
                with open(cache_file, 'r') as f:
                    cached_data = json.load(f)
                    # Pridáme info, že ide o cache
                    cached_data['from_cache'] = True
                    print(json.dumps(cached_data))
                    return
            except: pass

    ib = IB()
    try:
        ib.connect('127.0.0.1', args.port, clientId=155, timeout=15)
        
        contract = Stock(args.symbol, 'SMART', 'USD')
        ib.qualifyContracts(contract)
        
        bars = ib.reqHistoricalData(
            contract, endDateTime='', durationStr=args.duration,
            barSizeSetting=args.barSize, whatToShow='TRADES', useRTH=True
        )
        
        if not bars:
            print(json.dumps({'success': False, 'error': 'No data returned'}))
            return

        data_list = []
        for b in bars:
            data_list.append({
                'time': str(b.date),
                'open': b.open, 'high': b.high, 'low': b.low, 'close': b.close, 'volume': b.volume
            })
            
        result = {'success': True, 'candles': data_list, 'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
        
        # Uložiť do cache
        try:
            with open(cache_file, 'w') as f:
                json.dump(result, f, indent=2)
        except: pass

        print(json.dumps(result))
        
    except Exception as e:
        print(json.dumps({'success': False, 'error': str(e)}))
    finally:
        ib.disconnect()

if __name__ == "__main__":
    main()
