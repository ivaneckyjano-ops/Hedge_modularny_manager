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

# --- Black-Scholes model pre výpočet Greeks a ceny pri zatvorenom trhu ---
def black_scholes_call_info(S, K, T, r, sigma):
    """
    S: Cena podkladu, K: Strike, T: Čas do expirácie (v rokoch), 
    r: Úroková miera (napr. 0.045), sigma: Volatilita (napr. 0.20)
    Vráti (Cena, Delta, Theta)
    """
    if T <= 0 or sigma <= 0: return (max(0.01, S - K), 0.5, 0) # Default ak sú zlé dáta
    
    try:
        d1 = (math.log(S / K) + (r + 0.5 * sigma**2) * T) / (sigma * math.sqrt(T))
        d2 = d1 - sigma * math.sqrt(T)
        
        # Aproximácia kumulatívnej distribučnej funkcie normálneho rozdelenia (norm.cdf)
        def cdf(x):
            return (1.0 + math.erf(x / math.sqrt(2.0))) / 2.0
        
        # Aproximácia hustoty (norm.pdf)
        def pdf(x):
            return math.exp(-0.5 * x**2) / math.sqrt(2.0 * math.pi)

        price = S * cdf(d1) - K * math.exp(-r * T) * cdf(d2)
        delta = cdf(d1)
        # Theta pre Call (zjednodušená na dni)
        theta = -(S * pdf(d1) * sigma / (2 * math.sqrt(T)) + r * K * math.exp(-r * T) * cdf(d2))
        return price, delta, theta / 365.0
    except:
        return (max(0.01, S - K), 0.5, 0)

def calculate_historical_volatility(candles):
    if not candles or len(candles) < 10: return 0.25 # Default 25% ak niet dát
    try:
        closes = [c.close for c in candles]
        log_returns = np.log(np.array(closes[1:]) / np.array(closes[:-1]))
        vol = np.std(log_returns) * np.sqrt(252)
        return float(vol)
    except:
        return 0.25

def main():
    if len(sys.argv) < 3:
        print(json.dumps({'success': False, 'error': 'Usage: tws_fetch_pmcc_options.py PORT SYMBOL'}))
        sys.exit(1)
    
    port = int(sys.argv[1])
    symbol = sys.argv[2]
    
    ib = IB()
    try:
        ib.connect('127.0.0.1', port, clientId=random.randint(300, 399), readonly=True, timeout=25)
        # Typ 3 je Delayed, Typ 4 je Frozen (oboje pre zatvorený trh)
        ib.reqMarketDataType(3) 
        
        stock = Stock(symbol, 'SMART', 'USD')
        ib.qualifyContracts(stock)
        
        # Sťahujeme 106 (IV) a snapshot
        ticker = ib.reqMktData(stock, '106', True, False)
        
        # Sťahujeme históriu pre cenu a výpočet volatility
        bars = ib.reqHistoricalData(
            stock, endDateTime='', durationStr='60 D',
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
        hv = calculate_historical_volatility(bars)
        
        # Ak nemáme IV z trhu (časté pri zatvorenom trhu), použijeme HV
        model_iv = iv if (iv and iv > 0 and not math.isnan(iv)) else hv

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
                if 120 <= dte <= 750: # Rozšírený rozsah pre LEAPS
                    leaps_expiries.append((exp_str, dte))
                elif 10 <= dte <= 90: # Rozšírený rozsah pre Short
                    short_expiries.append((exp_str, dte))
            except: continue
        
        if not leaps_expiries or not short_expiries:
            print(json.dumps({'success': False, 'error': f'Vhodné expirácie nenájdené (DTE LEAPS: {[d for e,d in leaps_expiries]}, Short: {[d for e,d in short_expiries]})'}))
            return

        leaps_expiries = leaps_expiries[:8] # Viac expirácií
        short_expiries = short_expiries[:8]
        
        contracts = []
        for exp, dte in leaps_expiries + short_expiries:
            is_leaps = dte > 100
            # Ešte širší rozsah strikov pre robustnosť
            low_s, high_s = (price * 0.3, price * 1.0) if is_leaps else (price * 0.9, price * 1.5)
            valid_strikes = [s for s in chain.strikes if low_s <= s <= high_s]
            if len(valid_strikes) > 30:
                step = len(valid_strikes) // 30
                valid_strikes = valid_strikes[::step]
            for s in valid_strikes:
                contracts.append(Option(symbol, exp, s, 'C', 'SMART'))
        
        qualified = ib.qualifyContracts(*contracts)
        all_opt_tickers = []
        for i in range(0, len(qualified), 50):
            all_opt_tickers.extend(ib.reqTickers(*qualified[i:i+50]))
            ib.sleep(0.5)
        
        # Dlhší spánok pri zatvorenom trhu, aby sa stihli vypočítať Greeks
        ib.sleep(5)
        
        leaps_list = []
        short_list = []
        interest_rate = 0.045 # Aktuálna bezriziková miera (cca 4.5%)

        for t in all_opt_tickers:
            exp_str = t.contract.lastTradeDateOrContractMonth
            dte = (datetime.strptime(exp_str, '%Y%m%d') - today).days
            T_years = dte / 365.0
            
            g = t.modelGreeks
            
            # --- FALLBACK LOGIKA PRE GREEKS ---
            delta, theta, opt_price_model, opt_iv = 0.5, 0, 0, model_iv
            
            if g is not None:
                delta = abs(getattr(g, 'delta', 0.5) or 0.5)
                theta = getattr(g, 'theta', 0) or 0
                opt_price_model = getattr(g, 'optPrice', 0) or 0
                # Skúsime rôzne názvy pre IV
                opt_iv = getattr(g, 'impliedVol', None) or getattr(g, 'impliedVolatility', None) or model_iv
            
            if delta == 0.5 and theta == 0: # Ak stále nemáme greeks, skúsime Black-Scholes
                opt_price_model, delta, theta = black_scholes_call_info(price, t.contract.strike, T_years, interest_rate, model_iv)

            # --- Robustnejší výber ceny opcie a základné info likvidity ---
            bid = t.bid if (t.bid > 0 and not math.isnan(t.bid)) else 0
            ask = t.ask if (t.ask > 0 and not math.isnan(t.ask)) else 0
            last = t.last if (t.last > 0 and not math.isnan(t.last)) else 0
            close = t.close if (t.close > 0 and not math.isnan(t.close)) else 0

            # Sizes / OI / volume (môžu byť None alebo NaN mimo hodín)
            def safe_int(val):
                try:
                    if val is None or math.isnan(float(val)): return 0
                    return int(val)
                except: return 0

            bid_size = safe_int(getattr(t, 'bidSize', 0))
            ask_size = safe_int(getattr(t, 'askSize', 0))
            oi = safe_int(getattr(t, 'openInterest', 0))
            vol = safe_int(getattr(t, 'volume', 0))

            if bid > 0 and ask > 0:
                opt_price = (bid + ask) / 2
            elif last > 0:
                opt_price = last
            elif close > 0:
                opt_price = close
            elif opt_price_model and opt_price_model > 0:
                opt_price = opt_price_model
            else:
                continue

            if not opt_price or opt_price <= 0 or math.isnan(opt_price):
                continue

            # percentuálny spread (bezpečný default 1.0 ak nie sú quotes)
            spread_pct = (ask - bid) / opt_price if (bid > 0 and ask > 0 and opt_price > 0) else 1.0

            # rychlá likviditná vlajka (pragmatická heuristika)
            desired_contracts = 5
            if dte < 100:
                liquidity_flag = (oi >= 500 or vol >= 50) and (spread_pct < 0.02) and (min(bid_size, ask_size) >= desired_contracts)
            else:
                liquidity_flag = (oi >= 150 or vol >= 5) and (spread_pct < 0.03)

            data = {
                'strike': t.contract.strike, 'expiry': exp_str, 'dte': dte,
                'delta': delta, 'theta': theta, 'price': round(opt_price, 2),
                'iv': opt_iv, 'bid': bid, 'ask': ask, 'bid_size': bid_size, 'ask_size': ask_size,
                'open_interest': oi, 'volume': vol, 'spread_pct': spread_pct,
                'liquidity_flag': bool(liquidity_flag)
            }
            
            if dte > 120 and 0.65 <= delta <= 0.95: leaps_list.append(data)
            elif dte < 100 and 0.10 <= delta <= 0.50: short_list.append(data)
        
        print(json.dumps({
            'success': True, 'underlying_price': price, 'iv': model_iv,
            'leaps': sorted(leaps_list, key=lambda x: abs(x['delta'] - 0.80))[:30],
            'short': sorted(short_list, key=lambda x: abs(x['delta'] - 0.25))[:30]
        }))
        
    except Exception as e:
        print(json.dumps({'success': False, 'error': str(e)}))
    finally:
        if ib.isConnected(): ib.disconnect()

if __name__ == "__main__":
    main()
