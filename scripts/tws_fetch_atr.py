#!/usr/bin/env python3
"""Fetch ATR (7-day average high-low range) from TWS"""
import sys
sys.path.insert(0, '/home/narbon/Aplikácie/tws-webapp/venv/lib/python3.12/site-packages')
from ib_insync import IB, Stock
import random

def main():
    if len(sys.argv) < 3:
        print("ERROR:Usage: tws_fetch_atr.py PORT SYMBOL")
        sys.exit(1)
    
    port = int(sys.argv[1])
    symbol = sys.argv[2]
    
    try:
        ib = IB()
        ib.connect('127.0.0.1', port, clientId=random.randint(1000,9999), readonly=True)
        
        stock = Stock(symbol, 'SMART', 'USD')
        qualified = ib.qualifyContracts(stock)
        
        if not qualified:
            print("ERROR:Contract not qualified")
            sys.exit(1)
        
        bars = ib.reqHistoricalData(
            stock, 
            endDateTime='', 
            durationStr='21 D', 
            barSizeSetting='1 day', 
            whatToShow='TRADES', 
            useRTH=True
        )
        
        ib.disconnect()
        
        if not bars or len(bars) < 14:
            print("ERROR:Insufficient historical data")
            sys.exit(1)
        
        # Compute average high-low over last 14 bars (standard ATR period)
        last14 = bars[-14:]
        highs_lows = [b.high - b.low for b in last14]
        avg = sum(highs_lows) / len(highs_lows)
        
        print("{:.2f}".format(avg))
            
    except Exception as e:
        print("ERROR:{}".format(str(e)))
        sys.exit(1)

if __name__ == '__main__':
    main()
