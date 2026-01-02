"""Manual test script to verify connection to local TWS using ib_insync.

Usage:
    python3 scripts/tws_manual_test.py

Requires ib_insync installed in the venv.
"""
#!/usr/bin/env python3
import os
import random
import sys
from pathlib import Path

# Pridanie cesty k venv knižniciam
BASE_DIR = Path(__file__).resolve().parents[1]
venv_site = BASE_DIR / 'venv' / 'lib' / 'python3.12' / 'site-packages'
if venv_site.exists():
    sys.path.insert(0, str(venv_site))

from ib_insync import IB

HOST = os.environ.get('TWS_HOST', '127.0.0.1')
PORT = int(os.environ.get('TWS_PORT', 7497))
# Použijeme náhodné clientId, aby sme predišli konfliktom pri monitoringu
CLIENT_ID = int(os.environ.get('TWS_CLIENT_ID', random.randint(2000, 3000)))

import argparse
import json


def main():
    parser = argparse.ArgumentParser(description='TWS manual test')
    parser.add_argument('--mode', choices=('account', 'positions'), default='account')
    args = parser.parse_args()

    ib = IB()
    # print(f"Connecting to TWS at {HOST}:{PORT} clientId={CLIENT_ID}...")
    try:
        ib.connect(HOST, PORT, clientId=CLIENT_ID)
        # Nastavenie typu dát: 3 (delayed) a 4 (frozen) pre maximálnu šancu na získanie Greeks
        ib.reqMarketDataType(3) 
        
        # Return JSON payload depending on mode
        if args.mode == 'account':
            vals = ib.accountValues()
            out = []
            for v in vals:
                out.append({'account': v.account, 'tag': v.tag, 'value': v.value, 'currency': v.currency})
            print(json.dumps({'connected': ib.isConnected(), 'mode': 'account', 'accountValues': out}))
        else:
            out = []
            positions = ib.positions()
            for p in positions:
                try:
                    c = p.contract
                    pos_data = {
                        'symbol': getattr(c, 'symbol', None), 
                        'secType': getattr(c, 'secType', None), 
                        'right': getattr(c, 'right', None),
                        'strike': getattr(c, 'strike', None),
                        'expiry': getattr(c, 'lastTradeDateOrContractMonth', None),
                        'exchange': getattr(c, 'exchange', None), 
                        'currency': getattr(c, 'currency', None), 
                        'position': p.position, 
                        'avgCost': getattr(p, 'avgCost', None),
                        'delta': None,
                        'gamma': None,
                        'theta': None,
                        'vega': None
                    }
                    
                    # Ak je to opcia, skúsime získať greeks
                    if pos_data['secType'] == 'OPT':
                        # Zabezpečíme, aby contract mal exchange nastavenú na SMART
                        if not c.exchange:
                            c.exchange = 'SMART'
                        
                        ib.qualifyContracts(c)
                        ticker = ib.reqMktData(c, '106', False, False)
                        
                        # Čakanie na Greeks v slučke (max 5 sekúnd)
                        for _ in range(25):
                            ib.sleep(0.2)
                            mg = getattr(ticker, 'modelGreeks', None) or getattr(ticker, 'lastGreeks', None)
                            if mg and getattr(mg, 'delta', None) is not None:
                                break
                        
                        if mg:
                            pos_data['delta'] = getattr(mg, 'delta', None)
                            pos_data['gamma'] = getattr(mg, 'gamma', None)
                            pos_data['theta'] = getattr(mg, 'theta', None)
                            pos_data['vega'] = getattr(mg, 'vega', None)
                        
                        ib.cancelMktData(c)
                    
                    out.append(pos_data)
                except Exception as e:
                    out.append({'repr': str(p), 'error': str(e)})
            print(json.dumps({'connected': ib.isConnected(), 'mode': 'positions', 'positions': out}))
    finally:
        if ib.isConnected():
            ib.disconnect()
        # print("Disconnected")


if __name__ == '__main__':
    main()
