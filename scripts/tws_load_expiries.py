#!/usr/bin/env python3
"""Load option expiries from TWS"""
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[1]
venv_site = BASE_DIR / 'venv' / 'lib' / 'python3.12' / 'site-packages'
if venv_site.exists():
    sys.path.insert(0, str(venv_site))
else:
    fallback = Path('/home/narbon/Aplikácie/tws-webapp/venv/lib/python3.12/site-packages')
    if fallback.exists():
        sys.path.insert(0, str(fallback))

from ib_insync import IB, Option
import random

def main():
    if len(sys.argv) < 4:
        print("ERROR:Usage: tws_load_expiries.py PORT SYMBOL RIGHT", file=sys.stderr)
        sys.exit(1)
    
    port = int(sys.argv[1])
    symbol = sys.argv[2]
    right = sys.argv[3]
    
    print(f"DEBUG: Starting load_expiries: port={port}, symbol={symbol}, right={right}", file=sys.stderr)
    
    try:
        ib = IB()
        print(f"Connecting to TWS on port {port}...", file=sys.stderr)
        sys.stderr.flush()
        
        # Kratší timeout pre pripojenie - ak sa nepripojí do 10s, niečo je zle
        ib.connect('127.0.0.1', port, clientId=random.randint(1000,9999), readonly=True, timeout=10)
        
        print(f"Connected! Setting market data type...", file=sys.stderr)
        sys.stderr.flush()
        
        # Nastav delayed data ak live nie je dostupné
        ib.reqMarketDataType(3)  # Delayed
        
        # Skús najprv rýchlejší prístup cez reqSecDefOptParams
        from ib_insync import Stock
        stock = Stock(symbol, 'SMART', 'USD')
        ib.qualifyContracts(stock)
        
        # Použij priamo reqContractDetails (ib_insync potrebuje event loop v hlavnom threade)
        opt = Option(symbol, '', 0, right, 'SMART')
        
        print(f"Requesting contract details for {symbol} {right}...", file=sys.stderr)
        sys.stderr.flush()
        
        # Volaj priamo - subprocess timeout zabezpečí timeout handling
        details = ib.reqContractDetails(opt)
        
        print(f"DEBUG: Received {len(details) if details else 0} contract details", file=sys.stderr)
        sys.stderr.flush()
        
        if not details:
            print("ERROR:No contract details found", file=sys.stderr)
            ib.disconnect()
            sys.exit(1)
        
        # Získaj expirácie z details
        expiries_raw = []
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
        
        ib.disconnect()
        
        # Vypíš expirácie do stdout (bez DEBUG prefixu)
        print(','.join(expiries))
        sys.stdout.flush()
            
    except Exception as e:
        error_msg = str(e)
        print(f"ERROR:{error_msg}", file=sys.stderr)
        import traceback
        traceback.print_exc(file=sys.stderr)
        sys.exit(1)

if __name__ == '__main__':
    main()
