#!/usr/bin/env python3
"""Load option expiries from TWS"""
import sys
from pathlib import Path
from datetime import datetime

BASE_DIR = Path(__file__).resolve().parents[1]
venv_site = BASE_DIR / 'venv' / 'lib' / 'python3.12' / 'site-packages'
if venv_site.exists():
    sys.path.insert(0, str(venv_site))

from ib_insync import IB, Option
import random
import json
import time

WEEKDAY_MAP = {
    # Monday=0 ... Friday=4
    'SPY': set(range(5)),
    'QQQ': set(range(5)),
    'IWM': set(range(5)),
    'UNH': {4},  # only Fridays
    'TQQQ': set(range(5)),
    'XLE': {4},
}

CACHE_DIR = BASE_DIR / "cache" / "expiries"
CACHE_EXPIRY_SECONDS = 3600 * 24 * 14 # 14 dní

def filter_by_weekday(symbol, expiries):
    allowed = WEEKDAY_MAP.get(symbol.upper())
    if not allowed:
        return expiries
    filtered = []
    for expiry in expiries:
        try:
            exp_date = datetime.strptime(expiry, '%Y%m%d')
        except ValueError:
            continue
        if exp_date.weekday() in allowed:
            filtered.append(expiry)
    return filtered

def main():
    if len(sys.argv) < 4:
        print("ERROR:Usage: tws_load_expiries.py PORT SYMBOL RIGHT", file=sys.stderr)
        sys.exit(1)
    
    port = int(sys.argv[1])
    symbol = sys.argv[2]
    right = sys.argv[3]
    
    cache_file = CACHE_DIR / f"{symbol}_{right}_{port}.json"

    # Pokus o načítanie z cache
    if cache_file.exists():
        try:
            with open(cache_file, 'r') as f:
                cache_data = json.load(f)
                timestamp = cache_data.get("timestamp")
                cached_expiries = cache_data.get("expiries")
                
                if timestamp and cached_expiries:
                    if (time.time() - timestamp) < CACHE_EXPIRY_SECONDS:
                        print(f"DEBUG: Loading expiries from cache for {symbol} {right} (port {port})...", file=sys.stderr)
                        # Weekday filter sa aplikuje aj na cache dáta
                        filtered_expiries_from_cache = filter_by_weekday(symbol, cached_expiries)
                        print(f"DEBUG: Returning {len(filtered_expiries_from_cache)} expiries from cache.", file=sys.stderr)
                        print(','.join(filtered_expiries_from_cache))
                        sys.stdout.flush()
                        sys.exit(0)
                    else:
                        print(f"DEBUG: Cache for {symbol} {right} (port {port}) is expired.", file=sys.stderr)
                
        except Exception as e:
            print(f"DEBUG: Error reading cache file: {e}", file=sys.stderr)
    else:
        print(f"DEBUG: No cache file found for {symbol} {right} (port {port}).", file=sys.stderr)

    print(f"DEBUG: Starting load_expiries: port={port}, symbol={symbol}, right={right} (fetching from TWS)", file=sys.stderr)
    
    ib = None
    expiries = []
    try:
        ib = IB()
        print(f"DEBUG: Attempting to connect to TWS on port {port}...", file=sys.stderr)
        sys.stderr.flush()
        
        # Zvýšený timeout pre IB Gateway - 20s
        ib.connect('127.0.0.1', port, clientId=random.randint(1000,9999), readonly=True, timeout=20)
        
        print(f"DEBUG: Successfully connected to TWS. Setting market data type...", file=sys.stderr)
        sys.stderr.flush()
        
        # Nastav delayed data ak live nie je dostupné
        ib.reqMarketDataType(3)  # Delayed
        
        # Skús najprv rýchlejší prístup cez reqSecDefOptParams
        from ib_insync import Stock
        stock = Stock(symbol, 'SMART', 'USD')
        print(f"DEBUG: Qualifying stock contract for {symbol}...", file=sys.stderr)
        ib.qualifyContracts(stock)
        print(f"DEBUG: Stock contract qualified.", file=sys.stderr)
        
        # Použij priamo reqContractDetails (ib_insync potrebuje event loop v hlavnom threade)
        opt = Option(symbol, '', 0, right, 'SMART')
        
        print(f"DEBUG: Requesting contract details for {symbol} {right}...", file=sys.stderr)
        sys.stderr.flush()
        
        # Volaj priamo - subprocess timeout zabezpečí timeout handling
        details = ib.reqContractDetails(opt)
        print(f"DEBUG: Received contract details from TWS.", file=sys.stderr)
        
        print(f"DEBUG: Received {len(details) if details else 0} contract details", file=sys.stderr)
        sys.stderr.flush()
        
        if not details:
            print("ERROR:No contract details found", file=sys.stderr)
            ib.disconnect()
            sys.exit(1)
        
        # Získaj expirácie z details
        expiries_raw = []
        now_date_str = datetime.now().strftime('%Y%m%d')
        
        for d in details:
            expiry = d.contract.lastTradeDateOrContractMonth
            if expiry:
                expiry_str = str(expiry).strip()
                # Konvertuj na formát YYYYMMDD
                if len(expiry_str) == 6:  # YYYYMM
                    expiry_str = expiry_str + "01"
                elif len(expiry_str) == 8:  # YYYYMMDD
                    pass
                elif len(expiry_str) == 10:  # YYYY-MM-DD
                    expiry_str = expiry_str.replace('-', '').replace('/', '')
                    if len(expiry_str) != 8:
                        continue
                else:
                    continue
                
                if expiry_str.isdigit() and len(expiry_str) == 8:
                    # Filter pre minulosť
                    if expiry_str < now_date_str:
                        continue
                        
                    year = int(expiry_str[:4])
                    month = int(expiry_str[4:6])
                    day = int(expiry_str[6:8])
                    if 2020 <= year <= 2030 and 1 <= month <= 12 and 1 <= day <= 31:
                        expiries_raw.append(expiry_str)
        
        if not expiries_raw:
            print("ERROR:No expiries found", file=sys.stderr)
            ib.disconnect()
            sys.exit(1)
        
        # Zoraď a odstráň duplikáty
        expiries = sorted(set(expiries_raw))
        
        print(f"DEBUG: Found {len(expiries_raw)} raw expiries, {len(expiries)} unique", file=sys.stderr)
        filtered_expiries = filter_by_weekday(symbol, expiries)
        if filtered_expiries and len(filtered_expiries) < len(expiries):
            expiries = filtered_expiries
            print(f"DEBUG: Weekday filtered to {len(expiries)} expiries for {symbol}", file=sys.stderr)
        
        # Pre denné opcie (SPY, QQQ) môže byť veľa expirácií - obmedzíme na rozumný počet
        # Zober prvých 30 expirácií (dostatočne pre denné aj týždenné)
        if len(expiries) > 30:
            expiries = expiries[:30]
            print(f"DEBUG: Limited to first 30 expiries", file=sys.stderr)
        
        if not expiries:
            print("ERROR:No expiries found after filtering", file=sys.stderr)
            print(f"DEBUG: Raw expiries were: {expiries_raw[:10]}", file=sys.stderr)
            ib.disconnect()
            sys.exit(1)
        
        print(f"DEBUG: Returning {len(expiries)} expiries: {expiries[:5]}...", file=sys.stderr)
        sys.stderr.flush()

        # Ulož do cache
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        with open(cache_file, 'w') as f:
            json.dump({"timestamp": time.time(), "expiries": expiries}, f)
        print(f"DEBUG: Saved {len(expiries)} expiries to cache.", file=sys.stderr)
        
        ib.disconnect()
        
        # Vypíš expirácie do stdout (bez DEBUG prefixu)
        print(','.join(expiries))
        sys.stdout.flush()
            
    except Exception as e:
        error_msg = str(e)
        print(f"ERROR:{error_msg}", file=sys.stderr)
        import traceback
        traceback.print_exc(file=sys.stderr)
    finally:
        try:
            if ib and ib.isConnected():
                ib.disconnect()
        except:
            pass
            
    if 'error_msg' in locals():
        sys.exit(1)

if __name__ == '__main__':
    main()
