#!/usr/bin/env python3
import argparse
import sys
import json
import os
import random
from pathlib import Path
from datetime import datetime

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
    parser.add_argument('--force', action='store_true', help='Bypass cache')
    
    args = parser.parse_args()
    client_id = random.randint(100, 900)

    # --- CACHE LOGIKA ---
    cache_dir = BASE_DIR / 'cache' / 'history'
    cache_dir.mkdir(parents=True, exist_ok=True)
    # Pridaná dĺžka (duration) do názvu súboru, aby sa nemiešali krátke a dlhé histórie
    cache_file = cache_dir / f"{args.symbol}_{args.barSize.replace(' ', '_')}_{args.duration.replace(' ', '')}.json"
    
    ttl = 900 
    if "15 mins" in args.barSize: ttl = 300
    elif "1 hour" in args.barSize: ttl = 900
    elif "4 hours" in args.barSize: ttl = 1800
    elif "day" in args.barSize: ttl = 7200

    if not args.force and cache_file.exists():
        import time
        try:
            mtime = os.path.getmtime(cache_file)
            if (time.time() - mtime) < ttl:
                with open(cache_file, 'r') as f:
                    data = json.load(f)
                    data['from_cache'] = True
                    print(json.dumps(data))
                    return
        except: pass

    ib = IB()
    try:
        # Skúsime sa pripojiť
        ib.connect('127.0.0.1', args.port, clientId=client_id, timeout=15)
        
        # Špecifikácia kontraktu (pre ETFs skúsime SMART, ale aj konkrétne burzy ak treba)
        contract = Stock(args.symbol, 'SMART', 'USD')
        qualified = ib.qualifyContracts(contract)
        
        if not qualified:
            print(json.dumps({'success': False, 'error': f'Symbol {args.symbol} nebol v TWS nájdený.'}))
            return

        # Sťahujeme dáta
        bars = ib.reqHistoricalData(
            contract, endDateTime='', durationStr=args.duration,
            barSizeSetting=args.barSize, whatToShow='TRADES', useRTH=True
        )
        
        if not bars:
            print(json.dumps({'success': False, 'error': 'TWS nevrátil žiadne historické sviečky.'}))
            return

        data_list = []
        for b in bars:
            data_list.append({
                'time': str(b.date),
                'open': b.open, 'high': b.high, 'low': b.low, 'close': b.close, 'volume': b.volume
            })
            
        result = {
            'success': True, 
            'symbol': args.symbol,
            'candles': data_list, 
            'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        }
        
        with open(cache_file, 'w') as f:
            json.dump(result, f, indent=2)

        print(json.dumps(result))
        
    except Exception as e:
        print(json.dumps({'success': False, 'error': str(e)}))
    finally:
        ib.disconnect()

if __name__ == "__main__":
    main()
