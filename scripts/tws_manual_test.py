"""Manual test script to verify connection to local TWS using ib_insync.

Usage:
    python3 scripts/tws_manual_test.py

Requires ib_insync installed in the venv.
"""
import os
from ib_insync import IB

HOST = os.environ.get('TWS_HOST', '127.0.0.1')
PORT = int(os.environ.get('TWS_PORT', 7497))
CLIENT_ID = int(os.environ.get('TWS_CLIENT_ID', 1))

import argparse
import json


def main():
    parser = argparse.ArgumentParser(description='TWS manual test')
    parser.add_argument('--mode', choices=('account', 'positions'), default='account')
    args = parser.parse_args()

    ib = IB()
    print(f"Connecting to TWS at {HOST}:{PORT} clientId={CLIENT_ID}...")
    try:
        ib.connect(HOST, PORT, clientId=CLIENT_ID)
        # Return JSON payload depending on mode
        if args.mode == 'account':
            vals = ib.accountValues()
            out = []
            for v in vals:
                out.append({'account': v.account, 'tag': v.tag, 'value': v.value, 'currency': v.currency})
            print(json.dumps({'connected': ib.isConnected(), 'mode': 'account', 'accountValues': out}))
        else:
            out = []
            for p in ib.positions():
                try:
                    c = p.contract
                    out.append({'symbol': getattr(c, 'symbol', None), 'secType': getattr(c, 'secType', None), 'exchange': getattr(c, 'exchange', None), 'currency': getattr(c, 'currency', None), 'position': p.position, 'avgCost': getattr(p, 'avgCost', None)})
                except Exception:
                    out.append({'repr': str(p)})
            print(json.dumps({'connected': ib.isConnected(), 'mode': 'positions', 'positions': out}))
    finally:
        if ib.isConnected():
            ib.disconnect()
        print("Disconnected")


if __name__ == '__main__':
    main()
