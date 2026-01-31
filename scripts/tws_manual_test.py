#!/usr/bin/env python3
"""Manual test script to verify connection to local TWS using ib_insync.
Enhanced with Black-Scholes fallback and shared IV for missing Greeks.
"""
import os
import random
import sys
import json
import math
import datetime
from pathlib import Path

# Pridanie cesty k venv knižniciam
BASE_DIR = Path(__file__).resolve().parents[1]
venv_site = BASE_DIR / 'venv' / 'lib' / 'python3.12' / 'site-packages'
if venv_site.exists():
    sys.path.insert(0, str(venv_site))

from ib_insync import IB, Option, Contract, Stock

HOST = os.environ.get('TWS_HOST', '127.0.0.1')
PORT = int(os.environ.get('TWS_PORT', 7497))
CLIENT_ID = int(os.environ.get('TWS_CLIENT_ID', random.randint(2000, 3000)))

import argparse

# --- Black-Scholes Functions ---
def _norm_cdf(x):
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))

def _norm_pdf(x):
    return (1.0 / math.sqrt(2 * math.pi)) * math.exp(-0.5 * x * x)

def _bs_common(S, K, T, r, sigma):
    if S <= 0 or K <= 0 or T <= 0 or sigma <= 0:
        return None, None
    d1 = (math.log(S / K) + (r + 0.5 * sigma ** 2) * T) / (sigma * math.sqrt(T))
    d2 = d1 - sigma * math.sqrt(T)
    return d1, d2

def _bs_delta_call(S, K, T, r, sigma):
    d1, _ = _bs_common(S, K, T, r, sigma)
    return _norm_cdf(d1) if d1 is not None else 0

def _bs_delta_put(S, K, T, r, sigma):
    d1, _ = _bs_common(S, K, T, r, sigma)
    return _norm_cdf(d1) - 1 if d1 is not None else 0

def _bs_gamma(S, K, T, r, sigma):
    d1, _ = _bs_common(S, K, T, r, sigma)
    if d1 is None or S <= 0 or sigma <= 0 or T <= 0:
        return 0
    return _norm_pdf(d1) / (S * sigma * math.sqrt(T))

def _bs_theta_call(S, K, T, r, sigma):
    d1, d2 = _bs_common(S, K, T, r, sigma)
    if d1 is None: return 0
    term1 = -(S * _norm_pdf(d1) * sigma) / (2 * math.sqrt(T))
    term2 = -r * K * math.exp(-r * T) * _norm_cdf(d2)
    return (term1 + term2) / 365.0

def _bs_theta_put(S, K, T, r, sigma):
    d1, d2 = _bs_common(S, K, T, r, sigma)
    if d1 is None: return 0
    term1 = -(S * _norm_pdf(d1) * sigma) / (2 * math.sqrt(T))
    term2 = r * K * math.exp(-r * T) * _norm_cdf(-d2)
    return (term1 + term2) / 365.0

# -------------------------------

def main():
    parser = argparse.ArgumentParser(description='TWS manual test')
    parser.add_argument('--mode', choices=('account', 'positions'), default='account')
    args = parser.parse_args()

    ib = IB()
    try:
        ib.connect(HOST, PORT, clientId=CLIENT_ID)
        ib.reqMarketDataType(3) 
        ib.reqMarketDataType(4)
        ib.sleep(0.5)
        
        if args.mode == 'account':
            vals = ib.accountValues()
            out = [{'account': v.account, 'tag': v.tag, 'value': v.value, 'currency': v.currency} for v in vals]
            print(json.dumps({'connected': ib.isConnected(), 'mode': 'account', 'accountValues': out}))
        else:
            out = []
            # Použijeme ib.portfolio() namiesto ib.positions(), pretože obsahuje avgCost a unrealizedPNL
            portfolio_items = ib.portfolio()
            
            # Ak je portfolio prázdne (napr. čerstvý štart), skúsime aspoň positions
            if not portfolio_items:
                positions = ib.positions()
                # Prevedieme positions na pseudo-portfolio formát
                portfolio_items = []
                for p in positions:
                    portfolio_items.append(type('Item', (), {
                        'contract': p.contract,
                        'position': p.position,
                        'marketPrice': 0.0,
                        'averageCost': getattr(p, 'avgCost', 0.0),
                        'marketValue': 0.0,
                        'unrealizedPNL': 0.0,
                        'realizedPNL': 0.0
                    }))

            underlying_prices = {}
            avg_ivs = {}
            unique_symbols = set()
            for p in portfolio_items:
                if p.contract.secType in ('OPT', 'BAG', 'STK'):
                    unique_symbols.add(p.contract.symbol)
            
            # Získanie cien podkladu (kvôli Greeks) - OPTIMALIZOVANÉ PARALELNE
            stk_contracts = []
            for sym in unique_symbols:
                stk = Stock(sym, 'SMART', 'USD')
                stk_contracts.append(stk)
            
            ib.qualifyContracts(*stk_contracts)
            stk_tickers = [ib.reqMktData(stk, '', False, False) for stk in stk_contracts]
            
            # Počkáme na ceny všetkých podkladov naraz
            for _ in range(20):
                ib.sleep(0.1)
                if all(t.last or t.close for t in stk_tickers): break
            
            for t in stk_tickers:
                price = t.last if t.last and not math.isnan(t.last) else \
                        t.close if t.close and not math.isnan(t.close) else 0
                if price > 0: underlying_prices[t.contract.symbol] = price
                ib.cancelMktData(t.contract)

            active_tickers = {}
            opt_contracts = []
            for p in portfolio_items:
                c = p.contract
                if c.secType in ('OPT', 'BAG'):
                    if not c.exchange: c.exchange = 'SMART'
                    opt_contracts.append(c)
            
            # Hromadná kvalifikácia kontraktov
            if opt_contracts:
                ib.qualifyContracts(*opt_contracts)
                for c in opt_contracts:
                    try:
                        active_tickers[c.conId] = ib.reqMktData(c, '106', False, False)
                    except: pass

            iv_values = {sym: [] for sym in unique_symbols}
            # Počkáme na Greeks všetkých opcií naraz
            for _ in range(30):
                ib.sleep(0.2)
                all_have_greeks = True
                for t in active_tickers.values():
                    mg = getattr(t, 'modelGreeks', None) or getattr(t, 'lastGreeks', None)
                    if mg and mg.impliedVol: 
                        iv_values[t.contract.symbol].append(mg.impliedVol)
                    else:
                        all_have_greeks = False
                if all_have_greeks and _ > 10: break # Aspoň 2 sekundy, ale ak sú všetky, končíme skôr
            
            for sym, ivs in iv_values.items():
                avg_ivs[sym] = sum(ivs) / len(ivs) if ivs else 0.30

            for p in portfolio_items:
                c = p.contract
                pos_data = {
                    'symbol': c.symbol, 'secType': c.secType, 'right': getattr(c, 'right', None),
                    'strike': getattr(c, 'strike', None), 'expiry': getattr(c, 'lastTradeDateOrContractMonth', None),
                    'position': float(p.position), 
                    'avgCost': float(p.averageCost),
                    'marketPrice': float(p.marketPrice),
                    'unrealizedPNL': float(p.unrealizedPNL),
                    'delta': None, 'gamma': None, 'theta': None, 'vega': None
                }
                
                ticker = active_tickers.get(c.conId)
                if ticker:
                    mg = getattr(ticker, 'modelGreeks', None) or getattr(ticker, 'lastGreeks', None) or \
                         getattr(ticker, 'bidGreeks', None) or getattr(ticker, 'askGreeks', None)
                    if mg and mg.delta is not None:
                        pos_data['delta'] = mg.delta
                        pos_data['gamma'] = mg.gamma
                        pos_data['theta'] = mg.theta
                        pos_data['vega'] = mg.vega
                
                if pos_data['secType'] == 'OPT' and (pos_data['delta'] is None or pos_data['delta'] == 0.0):
                    S = underlying_prices.get(c.symbol, 0)
                    sigma = avg_ivs.get(c.symbol, 0.30)
                    if S > 0 and c.strike and c.lastTradeDateOrContractMonth:
                        try:
                            exp_str = c.lastTradeDateOrContractMonth
                            exp_date = datetime.datetime.strptime(exp_str, "%Y%m%d").date()
                            T = max((exp_date - datetime.date.today()).days / 365.0, 0.001)
                            r = 0.0525
                            if c.right == 'C':
                                pos_data['delta'] = _bs_delta_call(S, c.strike, T, r, sigma)
                                pos_data['theta'] = _bs_theta_call(S, c.strike, T, r, sigma)
                            else:
                                pos_data['delta'] = _bs_delta_put(S, c.strike, T, r, sigma)
                                pos_data['theta'] = _bs_theta_put(S, c.strike, T, r, sigma)
                            pos_data['gamma'] = _bs_gamma(S, c.strike, T, r, sigma)
                        except: pass

                if pos_data['secType'] == 'STK': pos_data['delta'] = 1.0
                if ticker: ib.cancelMktData(c)
                out.append(pos_data)
            
            print(json.dumps({'connected': ib.isConnected(), 'mode': 'positions', 'positions': out}))
    finally:
        if ib.isConnected(): ib.disconnect()

if __name__ == '__main__': main()
