#!/usr/bin/env python3
import sys
import json
import random
from pathlib import Path

# Venv path setup
BASE_DIR = Path(__file__).resolve().parents[1]
venv_site = BASE_DIR / 'venv' / 'lib' / 'python3.12' / 'site-packages'
if venv_site.exists(): sys.path.insert(0, str(venv_site))

from ib_insync import IB, Option

def main():
    if len(sys.argv) < 5:
        print(json.dumps({'success': False, 'error': 'Usage: tws_fetch_strikes.py PORT SYMBOL EXPIRY RIGHT'}))
        sys.exit(1)
    
    port = int(sys.argv[1])
    symbol = sys.argv[2]
    expiry = sys.argv[3].replace('-', '').replace('/', '')
    right = 'C' if sys.argv[4].upper().startswith('C') else 'P'
    
    ib = IB()
    try:
        ib.connect('127.0.0.1', port, clientId=random.randint(200, 299), readonly=True, timeout=15)
        # Use simple filter for strikes
        contract = Option(symbol, expiry, right=right, exchange='SMART')
        details = ib.reqContractDetails(contract)
        
        if not details:
            print(json.dumps({'success': False, 'error': 'No strikes found'}))
            return

        strikes = sorted(list(set(d.contract.strike for d in details)))
        print(json.dumps({'success': True, 'strikes': strikes}))
        
    except Exception as e:
        print(json.dumps({'success': False, 'error': str(e)}))
    finally:
        if ib.isConnected(): ib.disconnect()

if __name__ == "__main__":
    main()
