#!/usr/bin/env python3
"""
TWS Strangle Finder - finds optimal Long Strangle (Long Call + Long Put) for Gamma Scalping.
"""
import argparse
import json
import sys
from pathlib import Path
import math
from datetime import datetime

# Pridanie cesty k venv knižniciam
BASE_DIR = Path(__file__).resolve().parents[1]
venv_site = BASE_DIR / 'venv' / 'lib' / 'python3.12' / 'site-packages'
if venv_site.exists():
    sys.path.insert(0, str(venv_site))
else:
    fallback = Path('/home/narbon/Aplikácie/Hedge_modularny_manager/venv/lib/python3.12/site-packages')
    if fallback.exists():
        sys.path.insert(0, str(fallback))

from ib_insync import IB, Option, Stock

def parse_args():
    p = argparse.ArgumentParser(description='Find optimal Long Strangle (Call + Put)')
    p.add_argument('--symbol', required=True, help='Stock symbol')
    p.add_argument('--expiry', required=False, help='Expiry YYYYMMDD or list')
    p.add_argument('--delta-target', type=float, default=0.30)
    p.add_argument('--levels', default="0.20,0.30,0.40")
    p.add_argument('--tol', type=float, default=0.05)
    p.add_argument('--iv', type=float, default=0.20)
    p.add_argument('--rate', type=float, default=0.05)
    p.add_argument('--port', type=int, default=7497)
    p.add_argument('--host', default='127.0.0.1')
    p.add_argument('--clientId', type=int, default=110)
    p.add_argument('--out', default='/tmp/strangle_result.json')
    p.add_argument('--model-priority', action='store_true')
    p.add_argument('--call-strike', type=float, help='Manual Call Strike')
    p.add_argument('--put-strike', type=float, help='Manual Put Strike')
    return p.parse_args()

# --- Black-Scholes Math ---
def _bs_common(S, K, T, r, sigma):
    if S <= 0 or K <= 0 or T <= 0 or sigma <= 0: return None, None
    d1 = (math.log(S / K) + (r + 0.5 * sigma ** 2) * T) / (sigma * math.sqrt(T))
    d2 = d1 - sigma * math.sqrt(T)
    return d1, d2

def _norm_cdf(x): return 0.5 * (1 + math.erf(x / math.sqrt(2)))
def _norm_pdf(x): return math.exp(-0.5 * x * x) / math.sqrt(2 * math.pi)

def _bs_delta_call(S, K, T, r, sigma):
    d1, _ = _bs_common(S, K, T, r, sigma)
    return _norm_cdf(d1) if d1 is not None else 0

def _bs_delta_put(S, K, T, r, sigma):
    d1, _ = _bs_common(S, K, T, r, sigma)
    return _norm_cdf(d1) - 1 if d1 is not None else 0

def _bs_gamma(S, K, T, r, sigma):
    d1, _ = _bs_common(S, K, T, r, sigma)
    return _norm_pdf(d1) / (S * sigma * math.sqrt(T)) if d1 is not None else 0

def _bs_theta_call(S, K, T, r, sigma):
    d1, d2 = _bs_common(S, K, T, r, sigma)
    if d1 is None: return 0
    t1 = -(S * _norm_pdf(d1) * sigma) / (2 * math.sqrt(T))
    t2 = -r * K * math.exp(-r * T) * _norm_cdf(d2)
    return (t1 + t2) / 365.0

def _bs_theta_put(S, K, T, r, sigma):
    d1, d2 = _bs_common(S, K, T, r, sigma)
    if d1 is None: return 0
    t1 = -(S * _norm_pdf(d1) * sigma) / (2 * math.sqrt(T))
    t2 = r * K * math.exp(-r * T) * _norm_cdf(-d2)
    return (t1 + t2) / 365.0

def _bs_price_call(S, K, T, r, sigma):
    d1, d2 = _bs_common(S, K, T, r, sigma)
    return S * _norm_cdf(d1) - K * math.exp(-r * T) * _norm_cdf(d2) if d1 is not None else 0

def _bs_price_put(S, K, T, r, sigma):
    d1, d2 = _bs_common(S, K, T, r, sigma)
    return K * math.exp(-r * T) * _norm_cdf(-d2) - S * _norm_cdf(-d1) if d1 is not None else 0

def _fetch_greeks_for_strike(ib, symbol, expiry, strike, right, timeout_sec=5, current_price=1.0, T_years=0.1, r=0.05, iv=0.2):
    ticker = None
    # Skús nájsť v existujúcich (pre-fetched)
    for t in ib.tickers():
        c = t.contract
        if c.symbol == symbol and c.strike == strike and c.right == right and (c.lastTradeDateOrContractMonth == expiry or c.expiry == expiry):
            ticker = t
            break
    
    if not ticker:
        contract = Option(symbol, expiry, strike, right, 'SMART')
        ticker = ib.reqMktData(contract, '106', False, False)
    
    # Skús hneď dáta
    mg = getattr(ticker, 'modelGreeks', None) or getattr(ticker, 'lastGreeks', None)
    if mg and getattr(mg, 'delta', None) is not None:
        return _extract_greeks(ticker, mg, strike)

    # Čakaj
    for _ in range(int(timeout_sec / 0.2)):
        ib.sleep(0.2)
        mg = getattr(ticker, 'modelGreeks', None) or getattr(ticker, 'lastGreeks', None)
        if mg and getattr(mg, 'delta', None) is not None:
            return _extract_greeks(ticker, mg, strike)
            
    # Model fallback
    if right == 'C':
        d, g, t, p = _bs_delta_call(current_price, strike, T_years, r, iv), _bs_gamma(current_price, strike, T_years, r, iv), _bs_theta_call(current_price, strike, T_years, r, iv), _bs_price_call(current_price, strike, T_years, r, iv)
    else:
        d, g, t, p = _bs_delta_put(current_price, strike, T_years, r, iv), _bs_gamma(current_price, strike, T_years, r, iv), _bs_theta_put(current_price, strike, T_years, r, iv), _bs_price_put(current_price, strike, T_years, r, iv)
    
    return {'strike': strike, 'delta': d, 'gamma': g, 'theta': t, 'mid': p, 'iv': iv, 'bid': p, 'ask': p}

def _extract_greeks(ticker, mg, strike):
    bid, ask = getattr(ticker, 'bid', None), getattr(ticker, 'ask', None)
    
    # marketPrice v ib_insync je metóda, ktorú treba zavolať
    m_price = None
    if hasattr(ticker, 'marketPrice'):
        try:
            m_price = ticker.marketPrice()
        except:
            pass
            
    mid = (bid + ask) / 2 if (bid and ask and bid > 0 and ask > 0) else m_price
    if mid is None or not isinstance(mid, (int, float)) or math.isnan(mid):
        mid = 0.0
        
    def _safe_val(v, default=0.0):
        if v is None or not isinstance(v, (int, float)) or math.isnan(v):
            return default
        return v

    return {
        'strike': strike, 
        'delta': _safe_val(mg.delta), 
        'gamma': _safe_val(getattr(mg, 'gamma', None)),
        'vega': _safe_val(getattr(mg, 'vega', None)), 
        'theta': _safe_val(getattr(mg, 'theta', None)),
        'iv': _safe_val(getattr(mg, 'impliedVol', None)), 
        'bid': _safe_val(bid), 
        'ask': _safe_val(ask), 
        'mid': mid
    }

def find_strangle_levels(ib, symbol, expiry, targets, current_price, tol=0.05, rate=0.05, iv=0.20, model_priority=False):
    try:
        details = ib.reqContractDetails(Option(symbol, expiry, 0, 'C', 'SMART'))
        if not details: return None, f"No strikes for {expiry}"
        strikes = sorted({d.contract.strike for d in details})
    except: return None, "Strike fetch fail"

    exp_dt = datetime.strptime(expiry, "%Y%m%d")
    T_years = max(0.001, (exp_dt - datetime.now()).days) / 365.0
    
    # Inteligentný pred-výber kandidátov cez B-S, aby sme nepreťažili TWS
    candidate_strikes = set()
    for tgt in targets:
        # Pre Call
        c_strikes = sorted(strikes, key=lambda s: abs(_bs_delta_call(current_price, s, T_years, rate, iv) - abs(tgt)))
        candidate_strikes.update(c_strikes[:5])
        # Pre Put
        p_strikes = sorted(strikes, key=lambda s: abs(_bs_delta_put(current_price, s, T_years, rate, iv) - (-abs(tgt))))
        candidate_strikes.update(p_strikes[:5])
    
    relevant_strikes = sorted(list(candidate_strikes))

    # Pre-qualify and pre-fetch len pre vybraných kandidátov
    contracts = []
    for s in relevant_strikes:
        contracts.append(Option(symbol, expiry, s, 'C', 'SMART'))
        contracts.append(Option(symbol, expiry, s, 'P', 'SMART'))
    
    ib.qualifyContracts(*contracts)
    
    if not model_priority:
        tickers = []
        for c in contracts:
            tickers.append(ib.reqMktData(c, '106', False, False))
        
        # Čakáme na dáta hromadne
        ib.sleep(3)
        
    candidates = []
    for tgt in targets:
        # Hľadáme najlepšiu nohu z už načítaných relevant_strikes
        c_data = _select_leg_from_list(ib, symbol, expiry, relevant_strikes, abs(tgt), tol, 'C', current_price, model_priority, T_years, rate, iv)
        p_data = _select_leg_from_list(ib, symbol, expiry, relevant_strikes, -abs(tgt), tol, 'P', current_price, model_priority, T_years, rate, iv)
        
        if c_data and p_data:
            stats = {
                'netDelta': round(c_data['delta'] + p_data['delta'], 4),
                'totalGamma': round((c_data['gamma'] or 0) + (p_data['gamma'] or 0), 6),
                'totalTheta': round((c_data['theta'] or 0) + (p_data['theta'] or 0), 4),
                'totalCost': round((c_data['mid'] or 0) + (p_data['mid'] or 0), 2),
                'underlyingPrice': current_price
            }
            candidates.append({
                'target': tgt, 'expiry': expiry,
                'callLeg': {**c_data, 'symbol': symbol, 'right': 'C', 'expiry': expiry},
                'putLeg': {**p_data, 'symbol': symbol, 'right': 'P', 'expiry': expiry},
                'stats': stats
            })
    
    # Upratovanie market dát
    if not model_priority:
        for c in contracts:
            try: ib.cancelMktData(c)
            except: pass
            
    return candidates, None

def _select_leg_from_list(ib, symbol, expiry, strikes, target_delta, tol, right, current_price, model_mode, T_years, r, iv):
    best_data, best_diff = None, float('inf')
    for strike in strikes:
        data = _fetch_greeks_for_strike(ib, symbol, expiry, strike, right, 0.5, current_price, T_years, r, iv)
        # Pridaná kontrola: musí mať nenulové striky a nenulové delty (pre istotu)
        if not data or data['delta'] is None: continue
        
        # Ak máme veľmi malé delty (chyba B-S modelu pre OTM), ignoruj
        if abs(data['delta']) < 0.001 and target_delta > 0.05: continue

        diff = abs(data['delta'] - target_delta)
        if diff < best_diff:
            best_diff, best_data = diff, data
        if diff <= tol: return data
    return best_data

def main():
    args = parse_args()
    ib = IB()
    try:
        ib.connect(args.host, args.port, clientId=args.clientId, readonly=True, timeout=20)
    except Exception as e:
        print(json.dumps({'success': False, 'error': f'Connect fail: {e}'})); return
    
    ib.reqMarketDataType(3)
    
    # Get price ONCE
    stock = Stock(args.symbol, 'SMART', 'USD')
    ib.qualifyContracts(stock)
    t = ib.reqMktData(stock, '', False, False)
    
    # Čakáme dlhšie a aktívne kontrolujeme cenu
    price = 0.0
    for _ in range(20): # 20x 0.2s = 4 sekundy
        ib.sleep(0.2)
        price = getattr(t, 'last', None) or getattr(t, 'close', None) or getattr(t, 'marketPrice', None)
        if hasattr(t, 'marketPrice'):
             try: 
                mp = t.marketPrice()
                if not math.isnan(mp): price = mp
             except: pass
        
        if price and isinstance(price, (int, float)) and price > 0:
            break
            
    ib.cancelMktData(stock)
    
    # Ak stále nemáme cenu, skúsme reqHistoricalData ako poslednú záchranu
    hv_20d = 0.0
    try:
        # Žiadame o 30 dní, aby sme mali aspoň 20 obchodných dní pre HV
        bars = ib.reqHistoricalData(
            stock, endDateTime='', durationStr='30 D',
            barSizeSetting='1 day', whatToShow='TRADES', useRTH=1, formatDate=1, keepUpToDate=False)
        
        if bars:
            if not price or math.isnan(price) or price <= 0:
                price = bars[-1].close
            
            # Výpočet historickej volatility (HV)
            if len(bars) >= 21:
                # Log returns: ln(P_t / P_t-1)
                log_returns = []
                for i in range(1, len(bars)):
                    log_returns.append(math.log(bars[i].close / bars[i-1].close))
                
                # Smerodajná odchýlka log_returns (posledných 20)
                subset = log_returns[-20:]
                mean_r = sum(subset) / len(subset)
                var_r = sum((r - mean_r)**2 for r in subset) / (len(subset) - 1)
                std_r = math.sqrt(var_r)
                
                # Annualized HV = std * sqrt(252)
                hv_20d = std_r * math.sqrt(252)
    except Exception as e:
        print(f"DEBUG: HV/Price fetch failed: {e}", file=sys.stderr)

    if not price or math.isnan(price) or not isinstance(price, (int, float)) or price <= 0: 
        print(json.dumps({'success': False, 'error': f'Could not fetch price for {args.symbol}'})); return
    
    expiries = [e.strip() for e in (args.expiry or "").split(',') if e.strip()]
    
    # Filter minulých expirácií (pre istotu)
    now_date_str = datetime.now().strftime('%Y%m%d')
    valid_expiries = []
    for e in expiries:
        if e >= now_date_str: valid_expiries.append(e)
        
    targets = [float(x.strip()) for x in args.levels.split(',') if x.strip()]
    
    all_results = []
    
    # MANUAL STRIKES LOGIC
    if args.call_strike is not None and args.put_strike is not None:
        for exp in valid_expiries:
            try:
                exp_dt = datetime.strptime(exp, "%Y%m%d")
                T_years = max(0.001, (exp_dt - datetime.now()).days) / 365.0
                
                # Fetch data for specific strikes
                c_data = _fetch_greeks_for_strike(ib, args.symbol, exp, args.call_strike, 'C', 3.0, price, T_years, args.rate, args.iv)
                p_data = _fetch_greeks_for_strike(ib, args.symbol, exp, args.put_strike, 'P', 3.0, price, T_years, args.rate, args.iv)
                
                if c_data and p_data:
                    stats = {
                        'netDelta': round(c_data['delta'] + p_data['delta'], 4),
                        'totalGamma': round((c_data['gamma'] or 0) + (p_data['gamma'] or 0), 6),
                        'totalTheta': round((c_data['theta'] or 0) + (p_data['theta'] or 0), 4),
                        'totalCost': round(c_data['mid'] + p_data['mid'], 2),
                        'underlyingPrice': price,
                        'hv20d': hv_20d,
                        'avgIV': (c_data.get('iv', 0) + p_data.get('iv', 0)) / 2
                    }
                    all_results.append({
                        'target': 0.0, # Manual
                        'expiry': exp,
                        'callLeg': {**c_data, 'symbol': args.symbol, 'right': 'C', 'expiry': exp},
                        'putLeg': {**p_data, 'symbol': args.symbol, 'right': 'P', 'expiry': exp},
                        'stats': stats
                    })
            except Exception as e:
                print(f"DEBUG: Manual strike processing failed for {exp}: {e}", file=sys.stderr)
    else:
        # ORIGINAL SEARCH LOGIC
        for exp in valid_expiries:
            try:
                # Krátka pauza medzi expiráciami pre stabilitu TWS
                if len(expiries) > 1: ib.sleep(0.5)
                
                cands, err = find_strangle_levels(ib, args.symbol, exp, targets, price, args.tol, args.rate, args.iv, args.model_priority)
                if cands: 
                    # Pridáme HV do každého kandidáta
                    for c in cands:
                        c['stats']['hv20d'] = hv_20d
                        # IV je priemer oboch nôh
                        c['stats']['avgIV'] = (c['callLeg'].get('iv', 0) + c['putLeg'].get('iv', 0)) / 2
                    all_results.extend(cands)
                elif err:
                    print(f"DEBUG: Skipping expiry {exp}: {err}", file=sys.stderr)
            except Exception as e:
                print(f"DEBUG: Exception processing expiry {exp}: {e}", file=sys.stderr)
                continue # Pokračuj na ďalšiu expiráciu aj pri chybe

    ib.disconnect()
    
    if not all_results:
        print(json.dumps({'success': False, 'error': 'No candidates found'})); return

    all_results.sort(key=lambda c: (c['stats']['totalGamma']/abs(c['stats']['totalTheta'])) if abs(c['stats']['totalTheta'])>0 else 0, reverse=True)
    res = {'success': True, 'bestCandidate': all_results[0], 'candidates': all_results}
    with open(args.out, 'w') as f: json.dump(res, f, indent=2)
    print(json.dumps(res))

if __name__ == '__main__':
    main()
