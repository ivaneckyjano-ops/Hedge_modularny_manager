#!/usr/bin/env python3
import sys
import json
import random
import time
import math
import numpy as np
from pathlib import Path
from datetime import datetime, timedelta

# Venv path setup
BASE_DIR = Path(__file__).resolve().parents[1]
venv_site = BASE_DIR / 'venv' / 'lib' / 'python3.12' / 'site-packages'
if venv_site.exists(): sys.path.insert(0, str(venv_site))

from ib_insync import IB, Stock, Option, util

def calculate_historical_volatility(candles):
    if len(candles) < 10: return 0
    # Oprava: BarData objekt používa bodkovú notáciu .close, nie ['close']
    closes = [c.close for c in candles]
    log_returns = np.log(np.array(closes[1:]) / np.array(closes[:-1]))
    vol = np.std(log_returns) * np.sqrt(252) # Annualized
    return float(vol)

def main():
    if len(sys.argv) < 3:
        print(json.dumps({'success': False, 'error': 'Usage: tws_fetch_pmcc_options.py PORT SYMBOL'}))
        sys.exit(1)
    
    port = int(sys.argv[1])
    symbol = sys.argv[2]
    
    ib = IB()
    try:
        ib.connect('127.0.0.1', port, clientId=random.randint(300, 399), readonly=True, timeout=25)
        ib.reqMarketDataType(3) # Delayed
        
        stock = Stock(symbol, 'SMART', 'USD')
        ib.qualifyContracts(stock)
        
        ticker = ib.reqMktData(stock, '106', True, False)
        
        # Sťahujeme históriu aj pre cenu aj pre HV (ak by IV chýbalo)
        bars = ib.reqHistoricalData(
            stock, endDateTime='', durationStr='30 D',
            barSizeSetting='1 day', whatToShow='TRADES', useRTH=True
        )
        
        ib.sleep(2)
        
        price = ticker.marketPrice()
        if not price or price <= 0 or math.isnan(price):
            if bars: price = bars[-1].close
            else:
                print(json.dumps({'success': False, 'error': 'Cena nedostupná'}))
                return

        iv = getattr(ticker, 'impliedVolatility', 0)
        if not iv or math.isnan(iv):
            if bars: iv = calculate_historical_volatility(bars)
            else: iv = 0

        # 2. Get Option Chains
        chains = ib.reqSecDefOptParams(stock.symbol, '', stock.secType, stock.conId)
        if not chains:
            print(json.dumps({'success': False, 'error': f'Bez opcií pre {symbol}'}))
            return
        
        chain = max([c for c in chains if c.multiplier == '100'], key=lambda c: len(c.expirations), default=chains[0])
        expiries = sorted(chain.expirations)
        
        today = datetime.now()
        leaps_expiries = []
        short_expiries = []
        
        for exp_str in expiries:
            try:
                exp_date = datetime.strptime(exp_str, '%Y%m%d')
                dte = (exp_date - today).days
                if 150 <= dte <= 550:
                    leaps_expiries.append((exp_str, dte))
                elif 20 <= dte <= 65:
                    short_expiries.append((exp_str, dte))
            except: continue
        
        if not leaps_expiries or not short_expiries:
            print(json.dumps({'success': False, 'error': 'Chýbajú vhodné expirácie'}))
            return

        leaps_expiries = leaps_expiries[:3] # Trošku viac možností
        short_expiries = short_expiries[:2]
        
        contracts = []
        for exp, dte in leaps_expiries + short_expiries:
            is_leaps = dte > 100
            low_s, high_s = (price * 0.4, price * 0.95) if is_leaps else (price * 1.0, price * 1.4)
            valid_strikes = [s for s in chain.strikes if low_s <= s <= high_s]
            if len(valid_strikes) > 25:
                step = len(valid_strikes) // 25
                valid_strikes = valid_strikes[::step]
            for s in valid_strikes:
                contracts.append(Option(symbol, exp, s, 'C', 'SMART'))
        
        qualified = ib.qualifyContracts(*contracts)
        all_opt_tickers = []
        for i in range(0, len(qualified), 50):
            all_opt_tickers.extend(ib.reqTickers(*qualified[i:i+50]))
            ib.sleep(0.5)
        
        ib.sleep(4)
        
        leaps_list = []
        short_list = []
        for t in all_opt_tickers:
            g = t.modelGreeks
            if not g or g.delta is None: continue
            
            delta = abs(g.delta)
            exp_str = t.contract.lastTradeDateOrContractMonth
            dte = (datetime.strptime(exp_str, '%Y%m%d') - today).days
            
            # --- Robustnejší výber ceny opcie ---
            bid = t.bid if (t.bid > 0 and not math.isnan(t.bid)) else 0
            ask = t.ask if (t.ask > 0 and not math.isnan(t.ask)) else 0
            last = t.last if (t.last > 0 and not math.isnan(t.last)) else 0
            close = t.close if (t.close > 0 and not math.isnan(t.close)) else 0
            model = g.optPrice if (g.optPrice and g.optPrice > 0 and not math.isnan(g.optPrice)) else 0

            # Priorita: 1. Mid (Bid+Ask), 2. Last, 3. Close, 4. Model (Greeks)
            if bid > 0 and ask > 0:
                opt_price = (bid + ask) / 2
            elif last > 0:
                opt_price = last
            elif model > 0:
                opt_price = model # Dôležité pre nelikvidné LEAPS
            else:
                opt_price = close

            if not opt_price or opt_price <= 0 or math.isnan(opt_price):
                continue
            
            data = {
                'strike': t.contract.strike, 'expiry': exp_str, 'dte': dte,
                'delta': delta, 'theta': g.theta or 0, 'price': round(opt_price, 2),
                'bid': bid, 'ask': ask, 'spread_pct': (ask-bid)/opt_price if (opt_price>0 and ask>0 and bid>0) else 0
            }
            
            if dte > 140 and 0.70 <= delta <= 0.92: leaps_list.append(data)
            elif dte < 100 and 0.15 <= delta <= 0.45: short_list.append(data)
        
        print(json.dumps({
            'success': True, 'underlying_price': price, 'iv': iv,
            'leaps': sorted(leaps_list, key=lambda x: abs(x['delta'] - 0.80))[:15],
            'short': sorted(short_list, key=lambda x: abs(x['delta'] - 0.25))[:15]
        }))
        
    except Exception as e:
        print(json.dumps({'success': False, 'error': str(e)}))
    finally:
        if ib.isConnected(): ib.disconnect()

if __name__ == "__main__":
    main()
