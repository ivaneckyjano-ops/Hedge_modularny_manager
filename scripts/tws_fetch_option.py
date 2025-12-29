#!/usr/bin/env python3
"""Fetch option premium from TWS"""
import sys
sys.path.insert(0, '/home/narbon/Aplikácie/tws-webapp/venv/lib/python3.12/site-packages')
from ib_insync import IB, Option
import random
import math

def main():
    if len(sys.argv) < 6:
        print("ERROR:Usage: tws_fetch_option.py PORT SYMBOL EXPIRY STRIKE RIGHT")
        sys.exit(1)
    
    port = int(sys.argv[1])
    symbol = sys.argv[2]
    expiry = sys.argv[3]
    strike = float(sys.argv[4])
    right = sys.argv[5]
    
    # Debug output
    print(f"DEBUG: Fetching option: symbol={symbol}, expiry={expiry}, strike={strike}, right={right}", file=sys.stderr)
    sys.stderr.flush()
    
    try:
        ib = IB()
        print(f"DEBUG: Connecting to TWS on port {port}...", file=sys.stderr)
        sys.stderr.flush()
        ib.connect('127.0.0.1', port, clientId=random.randint(1000,9999), readonly=True, timeout=10)
        ib.reqMarketDataType(3)  # Delayed
        
        print(f"DEBUG: Creating Option contract...", file=sys.stderr)
        sys.stderr.flush()
        
        # Normalize expiry format - ensure it's YYYYMMDD
        expiry_normalized = expiry.strip()
        if len(expiry_normalized) == 6:  # YYYYMM
            expiry_normalized = expiry_normalized + "01"
        elif len(expiry_normalized) == 10:  # YYYY-MM-DD or YYYY/MM/DD
            expiry_normalized = expiry_normalized.replace('-', '').replace('/', '')
        
        print(f"DEBUG: Using expiry: {expiry_normalized}", file=sys.stderr)
        sys.stderr.flush()
        
        opt = Option(symbol, expiry_normalized, strike, right, 'SMART')
        print(f"DEBUG: Qualifying contract...", file=sys.stderr)
        sys.stderr.flush()
        qualified = ib.qualifyContracts(opt)
        
        if not qualified:
            print(f"ERROR:Contract not found (symbol={symbol}, expiry={expiry_normalized}, strike={strike}, right={right})", file=sys.stderr)
            print("ERROR:Contract not found")
            ib.disconnect()
            sys.exit(1)
        
        # qualified[0] je Contract objekt, použijeme ho namiesto opt
        contract = qualified[0]
        print(f"DEBUG: Contract qualified: {contract}", file=sys.stderr)
        sys.stderr.flush()
        
        print(f"DEBUG: Requesting market data...", file=sys.stderr)
        sys.stderr.flush()
        ticker = ib.reqMktData(contract, '', True, False)  # snapshot=True, použijeme qualified contract
        ib.sleep(5)
        
        bid = ticker.bid if ticker.bid and not math.isnan(ticker.bid) and ticker.bid > 0 else 0
        ask = ticker.ask if ticker.ask and not math.isnan(ticker.ask) and ticker.ask > 0 else 0
        last = ticker.last if ticker.last and not math.isnan(ticker.last) and ticker.last > 0 else 0
        close = ticker.close if ticker.close and not math.isnan(ticker.close) and ticker.close > 0 else 0
        
        print(f"DEBUG: Market data - bid={bid}, ask={ask}, last={last}, close={close}", file=sys.stderr)
        sys.stderr.flush()
        
        if bid > 0 and ask > 0:
            mid = (bid + ask) / 2
        elif last > 0:
            mid = last
        elif close > 0:
            mid = close
        else:
            mid = 0
        
        ib.cancelMktData(contract)
        ib.disconnect()
        
        if mid > 0:
            print("{:.2f}".format(mid))
        else:
            print("ERROR:No data (bid={}, ask={}, last={}, close={})".format(bid, ask, last, close))
            
    except Exception as e:
        error_msg = str(e)
        print(f"ERROR:{error_msg}", file=sys.stderr)
        import traceback
        traceback.print_exc(file=sys.stderr)
        print("ERROR:{}".format(error_msg))
        sys.exit(1)

if __name__ == '__main__':
    main()
