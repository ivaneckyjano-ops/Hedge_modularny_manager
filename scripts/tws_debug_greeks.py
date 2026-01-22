#!/usr/bin/env python3
import sys
import os
import random
from pathlib import Path
from ib_insync import *

# Setup venv path
BASE_DIR = Path(__file__).resolve().parents[1]
venv_site = BASE_DIR / 'venv' / 'lib' / 'python3.12' / 'site-packages'
if venv_site.exists():
    sys.path.insert(0, str(venv_site))

HOST = os.environ.get('TWS_HOST', '127.0.0.1')
PORT = int(os.environ.get('TWS_PORT', 7497))
CLIENT_ID = random.randint(5000, 6000)

def onPendingTickers(tickers):
    for t in tickers:
        print(f"PENDING TICKER: {t}")

def onTickOptionComputation(ticker):
    print(f"TICK OPTION: {ticker}")

def onError(reqId, errorCode, errorString, contract):
    print(f"ERROR: {reqId} {errorCode} {errorString} {contract}")

ib = IB()
ib.pendingTickersEvent += onPendingTickers
ib.errorEvent += onError

print(f"Connecting to {HOST}:{PORT}...")
try:
    ib.connect(HOST, PORT, clientId=CLIENT_ID)
    ib.reqMarketDataType(3) # Delayed
    ib.reqMarketDataType(4) # Frozen
    
    # Get positions
    positions = ib.positions()
    if not positions:
        print("No positions found.")
        sys.exit(0)
    
    # Pick first option
    opt_pos = next((p for p in positions if p.contract.secType == 'OPT'), None)
    if not opt_pos:
        print("No option positions found.")
        sys.exit(0)
    
    c = opt_pos.contract
    print(f"Selected contract from position: {c}")
    
    # Create a clean contract to be sure
    clean_c = Option(
        symbol=c.symbol,
        lastTradeDateOrContractMonth=c.lastTradeDateOrContractMonth,
        strike=c.strike,
        right=c.right,
        exchange='SMART',
        currency='USD'
    )
    
    print(f"Qualifying clean contract: {clean_c}")
    ib.qualifyContracts(clean_c)
    print(f"Qualified: {clean_c}")
    
    print("Requesting Market Data (106)...")
    ticker = ib.reqMktData(clean_c, '106', False, False)
    ticker.updateEvent += onTickOptionComputation
    
    print("Waiting for data (10s)...")
    for i in range(50):
        ib.sleep(0.2)
        if ticker.modelGreeks or ticker.lastGreeks:
            print("GOT GREEKS!")
            print(f"Model: {ticker.modelGreeks}")
            print(f"Last: {ticker.lastGreeks}")
            break
            
    if not (ticker.modelGreeks or ticker.lastGreeks):
        print("TIMED OUT - No Greeks received.")
        print(f"Final Ticker State: {ticker}")

finally:
    ib.disconnect()



