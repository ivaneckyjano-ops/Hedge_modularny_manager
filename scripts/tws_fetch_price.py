#!/usr/bin/env python3
"""Fetch underlying price from TWS"""
import sys
sys.path.insert(0, '/home/narbon/Aplikácie/tws-webapp/venv/lib/python3.12/site-packages')
from ib_insync import IB, Stock
import random
import math

def main():
    if len(sys.argv) < 3:
        print("ERROR:Usage: tws_fetch_price.py PORT SYMBOL")
        sys.exit(1)
    
    port = int(sys.argv[1])
    symbol = sys.argv[2]
    
    details = []
    price = None
    
    try:
        ib = IB()
        ib.connect('127.0.0.1', port, clientId=random.randint(1000,9999), readonly=True)
        
        stock = Stock(symbol, 'SMART', 'USD')
        ib.qualifyContracts(stock)
        
        for md in [3, 1]:  # Try delayed first, then realtime
            ib.reqMarketDataType(md)
            ticker = ib.reqMktData(stock, '', False, False)
            
            for _ in range(60):  # 6 seconds
                ib.sleep(0.1)
                bid = ticker.bid if ticker.bid and not math.isnan(ticker.bid) and ticker.bid > 0 else 0
                ask = ticker.ask if ticker.ask and not math.isnan(ticker.ask) and ticker.ask > 0 else 0
                last = ticker.last if ticker.last and not math.isnan(ticker.last) and ticker.last > 0 else 0
                close = ticker.close if ticker.close and not math.isnan(ticker.close) and ticker.close > 0 else 0
                
                if bid > 0 or ask > 0 or last > 0 or close > 0:
                    break
            
            ib.cancelMktData(stock)
            details.append("md={} bid={} ask={} last={} close={}".format(md, bid, ask, last, close))
            
            if bid > 0 and ask > 0:
                price = (bid + ask) / 2
                break
            elif last > 0:
                price = last
                break
            elif close > 0:
                price = close
                break
        
        ib.disconnect()
        
        if price:
            print("{:.2f}".format(price))
            print("DEBUG:{}".format(';'.join(details)))
        else:
            print("ERROR:No price data ({})".format(';'.join(details)))
            
    except Exception as e:
        print("ERROR:{}".format(str(e)))
        sys.exit(1)

if __name__ == '__main__':
    main()
