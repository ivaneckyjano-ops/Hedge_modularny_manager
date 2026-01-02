#!/usr/bin/env python3
"""
TWS Strangle Finder - finds optimal Long Strangle (Long Call + Long Put) for Gamma Scalping.

Usage:
  tws_strangle_finder.py --symbol UNH --expiry 20250117 --delta-target 0.30 \
                         --port 7497 --out /tmp/strangle_result.json

Outputs JSON with call leg, put leg, and strangle stats.
"""
import argparse
import json
import sys
from pathlib import Path
import math
from datetime import datetime

# Pridanie cesty k venv knižniciam (pre prípad, že sa spúšťa cez system python)
BASE_DIR = Path(__file__).resolve().parents[1]
venv_site = BASE_DIR / 'venv' / 'lib' / 'python3.12' / 'site-packages'
if venv_site.exists():
    sys.path.insert(0, str(venv_site))
else:
    fallback = Path('/home/narbon/Aplikácie/Hedge_modularny_manager/venv/lib/python3.12/site-packages')
    if fallback.exists():
        sys.path.insert(0, str(fallback))

from ib_insync import IB, Option

def parse_args():
    p = argparse.ArgumentParser(description='Find optimal Long Strangle (Call + Put)')
    p.add_argument('--symbol', required=True, help='Stock symbol (e.g., SPY)')
    p.add_argument('--expiry', required=True, help='Expiry (YYYYMMDD)')
    p.add_argument('--delta-target', type=float, default=0.30, help='Target delta (center) for legs, e.g. 0.30 -> Call +0.30, Put -0.30')
    p.add_argument('--levels', default="0.20,0.30,0.40", help='Comma-separated target deltas to try (positive values), default 0.20,0.30,0.40')
    p.add_argument('--tol', type=float, default=0.05, help='Delta tolerance (default 0.05); fallback picks nearest if none in tol')
    p.add_argument('--iv', type=float, default=0.20, help='Implied volatility for fallback model (if market data is unavailable)')
    p.add_argument('--rate', type=float, default=0.05, help='Risk-free rate for model greeks')
    p.add_argument('--port', type=int, default=7497, help='TWS port (default 7497 for Paper)')
    p.add_argument('--host', default='127.0.0.1')
    p.add_argument('--clientId', type=int, default=110)
    p.add_argument('--out', default='/tmp/strangle_result.json', help='Output JSON file')
    p.add_argument('--model-priority', action='store_true', help='Prefer Black-Scholes model over live market data when possible.')
    return p.parse_args()


def _fetch_greeks_for_strike(ib, symbol, expiry, strike, right, timeout_sec=5):
    """Fetch market data and return greeks + price for a contract."""
    contract = Option(symbol, expiry, strike, right, 'SMART')
    try:
        # ib.qualifyContracts(contract) # Už by malo byť kvalifikované v find_strangle_levels
        ticker = ib.reqMktData(contract, '106', False, False)
        
        # Wait for data
        for i in range(int(timeout_sec / 0.2)):
            ib.sleep(0.2)
            mg = getattr(ticker, 'modelGreeks', None) or getattr(ticker, 'lastGreeks', None)
            if mg and getattr(mg, 'delta', None) is not None:
                bid = getattr(ticker, 'bid', None)
                ask = getattr(ticker, 'ask', None)
                mid = (bid + ask) / 2 if bid and ask else None
                ib.cancelMktData(contract)
                print("DEBUG:       Live Greeks data received for {} {}. Delta: {:.3f}".format(strike, right, mg.delta), file=sys.stderr)
                return {
                    'strike': strike,
                    'delta': mg.delta,
                    'gamma': getattr(mg, 'gamma', None),
                    'vega': getattr(mg, 'vega', None),
                    'theta': getattr(mg, 'theta', None),
                    'iv': getattr(mg, 'impliedVol', None),
                    'bid': bid,
                    'ask': ask,
                    'mid': mid
                }
        ib.cancelMktData(contract)
        print("DEBUG:       Timeout or no valid Greeks after {}s for {} {}.".format(timeout_sec, strike, right), file=sys.stderr)
        return None
    except Exception as e:
        print("ERROR:     Exception fetching live Greeks for {} {}: {}".format(strike, right, e), file=sys.stderr)
        try:
            ib.cancelMktData(contract)
        except Exception:
            pass
        return None


# --- Model fallback (Black-Scholes) ---
def _bs_common(S, K, T, r, sigma):
    if S <= 0 or K <= 0 or T <= 0 or sigma <= 0:
        return None, None
    d1 = (math.log(S / K) + (r + 0.5 * sigma ** 2) * T) / (sigma * math.sqrt(T))
    d2 = d1 - sigma * math.sqrt(T)
    return d1, d2


def _norm_cdf(x):
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


def _norm_pdf(x):
    return math.exp(-0.5 * x * x) / math.sqrt(2 * math.pi)


def _bs_delta_call(S, K, T, r, sigma):
    d1, d2 = _bs_common(S, K, T, r, sigma)
    if d1 is None:
        return 0
    return _norm_cdf(d1)


def _bs_delta_put(S, K, T, r, sigma):
    d1, d2 = _bs_common(S, K, T, r, sigma)
    if d1 is None:
        return 0
    return _norm_cdf(d1) - 1


def _bs_gamma(S, K, T, r, sigma):
    d1, d2 = _bs_common(S, K, T, r, sigma)
    if d1 is None:
        return 0
    return _norm_pdf(d1) / (S * sigma * math.sqrt(T))


def _bs_theta_call(S, K, T, r, sigma):
    d1, d2 = _bs_common(S, K, T, r, sigma)
    if d1 is None:
        return 0
    term1 = - (S * _norm_pdf(d1) * sigma) / (2 * math.sqrt(T))
    term2 = - r * K * math.exp(-r * T) * _norm_cdf(d2)
    return (term1 + term2) / 365.0  # per day


def _bs_theta_put(S, K, T, r, sigma):
    d1, d2 = _bs_common(S, K, T, r, sigma)
    if d1 is None:
        return 0
    term1 = - (S * _norm_pdf(d1) * sigma) / (2 * math.sqrt(T))
    term2 = r * K * math.exp(-r * T) * _norm_cdf(-d2)
    return (term1 + term2) / 365.0  # per day


def _bs_price_call(S, K, T, r, sigma):
    d1, d2 = _bs_common(S, K, T, r, sigma)
    if d1 is None:
        return 0
    return S * _norm_cdf(d1) - K * math.exp(-r * T) * _norm_cdf(d2)


def _bs_price_put(S, K, T, r, sigma):
    d1, d2 = _bs_common(S, K, T, r, sigma)
    if d1 is None:
        return 0
    return K * math.exp(-r * T) * _norm_cdf(-d2) - S * _norm_cdf(-d1)


def _select_leg(ib, symbol, expiry, strikes, target_delta, tol, right, current_price, model_mode, T_years, r, iv):
        """Vyber leg s deltou čo najbližšie targetu pomocou smerového/bisection hľadania.
           Ak model_mode=True, používa Black-Scholes, inak reqMktData."""
        import bisect
        if not strikes:
            print("DEBUG: _select_leg for {} {} ({}) - No strikes provided.".format(symbol, right, expiry), file=sys.stderr)
            return None
        
        print("DEBUG: _select_leg for {} {} ({}) - Target Delta: {:.3f}, Tol: {:.3f}, Model Mode: {}".format(symbol, right, expiry, target_delta, tol, model_mode), file=sys.stderr)

        if model_mode and (current_price is None or current_price <= 0):
            print("ERROR: Cannot run model mode without a valid current_price. Got {}.".format(current_price), file=sys.stderr)
            return None

        # Cache pre greeks
        cache = {}
        def fetch_idx(idx):
            if idx < 0 or idx >= len(strikes):
                return None
            strike = strikes[idx]
            key = (right, strike)
            if key in cache:
                print("DEBUG:     Cache hit for strike {} {}.".format(strike, right), file=sys.stderr)
                return cache[key]
            
            print("DEBUG:     Fetching Greeks for strike {} {}...".format(strike, right), file=sys.stderr)
            if model_mode:
                # Modelový výpočet bez market data
                if right == 'C':
                    delta = _bs_delta_call(current_price, strike, T_years, r, iv)
                    gamma = _bs_gamma(current_price, strike, T_years, r, iv)
                    theta = _bs_theta_call(current_price, strike, T_years, r, iv)
                    mid = _bs_price_call(current_price, strike, T_years, r, iv)
                else:
                    delta = _bs_delta_put(current_price, strike, T_years, r, iv)
                    gamma = _bs_gamma(current_price, strike, T_years, r, iv)
                    theta = _bs_theta_put(current_price, strike, T_years, r, iv)
                    mid = _bs_price_put(current_price, strike, T_years, r, iv)
                
                data = {
                    'strike': strike,
                    'delta': delta,
                    'gamma': gamma,
                    'vega': None,
                    'theta': theta,
                    'iv': iv,
                    'bid': mid,
                    'ask': mid,
                    'mid': mid # Pre model máme len jednu cenu
                }
                print("DEBUG:     Model Greeks for {} {}: Delta {:.3f}".format(strike, right, delta), file=sys.stderr)
            else:
                data = _fetch_greeks_for_strike(ib, symbol, expiry, strike, right)
                if data and data['delta'] is None:
                    print("DEBUG:     Live Greeks for {} {} returned None Delta. Trying model fallback (current_price={}, T_years={:.3f}, r={}, iv={}).".format(strike, right, current_price, T_years, r, iv), file=sys.stderr)
                    # Fallback to model if live data fails for this specific leg
                    if right == 'C':
                        delta = _bs_delta_call(current_price, strike, T_years, r, iv)
                        gamma = _bs_gamma(current_price, strike, T_years, r, iv)
                        theta = _bs_theta_call(current_price, strike, T_years, r, iv)
                        mid = _bs_price_call(current_price, strike, T_years, r, iv)
                    else:
                        delta = _bs_delta_put(current_price, strike, T_years, r, iv)
                        gamma = _bs_gamma(current_price, strike, T_years, r, iv)
                        theta = _bs_theta_put(current_price, strike, T_years, r, iv)
                        mid = _bs_price_put(current_price, strike, T_years, r, iv)
                    data = {
                        'strike': strike,
                        'delta': delta,
                        'gamma': gamma,
                        'vega': None,
                        'theta': theta,
                        'iv': iv,
                        'bid': mid,
                        'ask': mid,
                        'mid': mid
                    }
                    print("DEBUG:     Model Fallback Greeks for {} {}: Delta {:.3f}".format(strike, right, delta), file=sys.stderr)
                elif data:
                    print("DEBUG:     Live Greeks for {} {}: Delta {:.3f}".format(strike, right, data['delta']), file=sys.stderr)
                else:
                    print("DEBUG:     No data returned for {} {} (live or model fallback).".format(strike, right), file=sys.stderr)

            cache[key] = data
            return data
        
        # Bisection search logic
        low = 0
        high = len(strikes) - 1
        best_data = None
        best_diff = float('inf')
        
        while low <= high:
            mid_idx = (low + high) // 2
            strike = strikes[mid_idx]

            print("DEBUG:   Searching [{}-{}] (idx {}), trying strike {} for {}...".format(low, high, mid_idx, strike, right), file=sys.stderr)
            
            data = fetch_idx(mid_idx) # Fetches Greeks (live or model)
            if not data or data['delta'] is None:
                print("DEBUG:     No valid delta for strike {} {}. Skipping strike.".format(strike, right), file=sys.stderr)
                # If we hit a hole in data, bisection is hard. Let's just try to move towards ATM
                # as data is usually more reliable there.
                if right == 'C':
                    if strike > current_price: high = mid_idx - 1 # Too far OTM? Go lower
                    else: low = mid_idx + 1 # Too far ITM? Go higher
                else:
                    if strike < current_price: low = mid_idx + 1 # Too far OTM? Go higher
                    else: high = mid_idx - 1 # Too far ITM? Go lower
                continue
            
            delta = data['delta']
            diff = abs(delta - target_delta)
            
            if diff < best_diff:
                best_diff = diff
                best_data = data
            
            if diff <= tol: # Found within tolerance
                print("DEBUG: Found delta {:.3f} for strike {} {} (target {:.3f}, diff {:.3f} <= tol {:.3f})".format(delta, strike, right, target_delta, diff, tol), file=sys.stderr)
                return data
            
            # Adjust search range based on delta comparison
            # Note: Both Call and Put deltas are DESCENDING functions of strike
            # Call: ITM (high delta) at low strikes, OTM (low delta) at high strikes
            # Put: OTM (low negative delta) at low strikes, ITM (high negative delta) at high strikes
            # Wait, let's re-verify Put:
            # Underlying 100. Strike 90 P (OTM): Delta -0.1
            # Strike 110 P (ITM): Delta -0.9
            # So as strike increases, Put delta becomes MORE negative (DECREASES).
            # Call: Underlying 100. Strike 90 C (ITM): Delta 0.9
            # Strike 110 C (OTM): Delta 0.1
            # So as strike increases, Call delta DECREASES.
            # Both are descending functions of strike in terms of numerical value.
            
            if delta < target_delta:
                # Current delta is too low (e.g. 0.1 < 0.3 for Call, or -0.9 < -0.3 for Put)
                # We need a LOWER strike to INCREASE the delta
                print("DEBUG:     Delta {:.3f} < Target {:.3f} for {} {}. Going to LOWER strikes.".format(delta, target_delta, strike, right), file=sys.stderr)
                high = mid_idx - 1
            else:
                # Current delta is too high (e.g. 0.8 > 0.3 for Call, or -0.1 > -0.3 for Put)
                # We need a HIGHER strike to DECREASE the delta
                print("DEBUG:     Delta {:.3f} > Target {:.3f} for {} {}. Going to HIGHER strikes.".format(delta, target_delta, strike, right), file=sys.stderr)
                low = mid_idx + 1
        
        if best_data:
            print("DEBUG: No exact match within tolerance. Returning best found delta {:.3f} for strike {} {} (diff {:.3f}).".format(best_data['delta'], best_data['strike'], right, best_diff), file=sys.stderr)
        else:
            print("DEBUG: No suitable leg found at all for {} {} with target delta {:.3f}.".format(symbol, right, target_delta), file=sys.stderr)
        return best_data


def find_strangle_levels(ib, symbol, expiry, targets, tol=0.05, rate=0.05, iv=0.20, model_priority_arg=False, port=7497):
    """
    Vráti zoznam kandidátov pre viaceré delta ciele.
    Každý kandidát: {'target': float, 'callLeg': {...}, 'putLeg': {...}, 'stats': {...}}
    """
    # 1. Get available strikes
    try:
        opt_template = Option(symbol, expiry, 0, 'C', 'SMART')
        details = ib.reqContractDetails(opt_template)
        if not details:
            return None, "No option details for {} {}".format(symbol, expiry)
        strikes = sorted({d.contract.strike for d in details})
    except Exception as e:
        return None, "Error fetching strikes: {}".format(e)

    # Čas do expirácie pre model (presunuté sem, aby bolo definované skôr)
    T_years = 0
    try:
        if expiry and len(expiry) == 8:
            exp_dt = datetime.strptime(expiry, "%Y%m%d")
            # Ensure T_years is always positive, at least 1 day if expiry is today or in the past
            days = max(1, (exp_dt - datetime.now()).days)
            T_years = days / 365.0
            print("DEBUG: Calculated T_years: {:.3f} (days={})".format(T_years, days), file=sys.stderr)
    except Exception as e:
        print("ERROR: Failed to calculate T_years: {}. Defaulting to 1 day (0.003 years).".format(e), file=sys.stderr)
        T_years = 1 / 365.0 # Default to 1 day if calculation fails
    
    # Filter strikes near current price to speed up
    current_price = None
    model_mode = model_priority_arg # Inicializácia na základe argumentu --model-priority
    live_price_fetch_failed = False # Nový príznak
    
    # Pre Paper port 7497 zvýšime trpezlivosť
    price_wait_time = 5 if port == 7497 else 2
    
    print("DEBUG: Attempting to get live underlying price for {} (port {})...".format(symbol, port), file=sys.stderr)
    try:
        from ib_insync import Stock
        stock = Stock(symbol, 'SMART', 'USD')
        ib.qualifyContracts(stock)
        stock_ticker = ib.reqMktData(stock, '', False, False)
        ib.sleep(price_wait_time) # Daj čas na príchod dát
        current_price = getattr(stock_ticker, 'last', None) or getattr(stock_ticker, 'close', None)
        
        # Ak stále nan, skúsme chvíľu počkať na delayed data
        if current_price is None or math.isnan(current_price):
            ib.sleep(2)
            current_price = getattr(stock_ticker, 'last', None) or getattr(stock_ticker, 'close', None) or getattr(stock_ticker, 'marketPrice', None)

        ib.cancelMktData(stock)
        if current_price is not None and not math.isnan(current_price) and current_price > 0:
            print("DEBUG: Live underlying price obtained: {} (Type: {})".format(current_price, type(current_price)), file=sys.stderr)
        else:
            print("DEBUG: Live underlying price not available or invalid ({}). Paper account often needs Model Fallback.".format(current_price), file=sys.stderr)
            live_price_fetch_failed = True
    except Exception as e:
        print("DEBUG: Live price fetch failed: {} (current_price before exception: {})".format(e, current_price), file=sys.stderr)
        live_price_fetch_failed = True # Set flag if live price fetch fails
        pass

    # Ak je current_price stále NaN alebo None, skús historickú close ako fallback
    if (current_price is None or (isinstance(current_price, (float, int)) and (math.isnan(current_price) or current_price <= 0))):
        print("DEBUG: Live price failed or invalid ({}). Attempting historical data fallback for {}...".format(current_price, symbol), file=sys.stderr)
        try:
            from ib_insync import Stock
            stock = Stock(symbol, 'SMART', 'USD')
            ib.qualifyContracts(stock)
            bars = ib.reqHistoricalData(
                stock,
                endDateTime='',
                durationStr='2 D',
                barSizeSetting='1 day',
                whatToShow='TRADES',
                useRTH=True
            )
            if bars:
                current_price = bars[-1].close
                print("DEBUG: Fallback historical close price obtained: {} (Type: {})".format(current_price, type(current_price)), file=sys.stderr)
            else:
                print("DEBUG: Historical data fallback failed: No bars returned. (current_price: {})".format(current_price), file=sys.stderr)
        except Exception as e:
            print("DEBUG: Historical price fetch failed during fallback: {} (current_price before exception: {})".format(e, current_price), file=sys.stderr)
            pass

    # Finálne rozhodnutie o model_mode a current_price
    print("DEBUG: Before final model_mode decision: current_price={}, live_price_fetch_failed={}".format(current_price, live_price_fetch_failed), file=sys.stderr)
    if live_price_fetch_failed or (current_price is None or (isinstance(current_price, (float, int)) and (math.isnan(current_price) or current_price <= 0))):
        print("DEBUG: Underlying price is still invalid ({}) after all attempts or live fetch failed. Switching to MODEL MODE.".format(current_price), file=sys.stderr)
        model_mode = True
        if current_price is None or (isinstance(current_price, (float, int)) and (math.isnan(current_price) or current_price <= 0)):
            current_price = 1.0 # Default value for model calculations if no valid price can be obtained
            print("DEBUG: Setting current_price to default {} for MODEL MODE.".format(current_price), file=sys.stderr)
    else:
        print("DEBUG: Final underlying price for calculations: {} (Type: {})".format(current_price, type(current_price)), file=sys.stderr)

    # Filter strikes near current price if current_price is valid
    if current_price and current_price > 0 and (current_price == current_price): # Check for NaN again
        print("DEBUG: Filtering strikes around current price {}...".format(current_price), file=sys.stderr)
        original_strikes_count = len(strikes)
        # Dynamic window based on current price for better relevance
        strike_filter_range = 0.2 # +/- 20% from current price
        filtered_strikes = [s for s in strikes if abs(s - current_price) / current_price <= strike_filter_range]

        if filtered_strikes:
            import bisect
            # After initial filtering, limit the number of strikes to process for performance
            idx = bisect.bisect_left(filtered_strikes, current_price)
            window_size = 40 # Limit to 40 strikes around the money
            start = max(0, idx - window_size // 2)
            end = min(len(filtered_strikes), start + window_size)
            strikes = filtered_strikes[start:end]
            print("DEBUG: Strikes filtered from {} to {}. Range=({}, {})".format(original_strikes_count, len(strikes), strikes[0], strikes[-1]), file=sys.stderr)
            if not strikes:
                print("DEBUG: No strikes left after windowing. Using original strikes (if any).", file=sys.stderr)
                strikes = sorted({d.contract.strike for d in details}) # Revert to all strikes
        else:
            print("DEBUG: No strikes found after filtering around price. Using all available strikes.", file=sys.stderr)
            # If filtering results in an empty list, revert to original full set of strikes
            strikes = sorted({d.contract.strike for d in details})
    else:
        print("DEBUG: Skipping strike filtering due to invalid or zero current_price ({}). Using all available strikes.".format(current_price), file=sys.stderr)
        # If current_price is invalid, ensure we don't filter strikes based on it, use all.
        strikes = sorted({d.contract.strike for d in details}) # Ensure we always have strikes
        if model_mode and (current_price is None or current_price <= 0 or (current_price != current_price)): # Check for NaN
            current_price = 1.0 # Default value for model calculations if no price can be obtained
            print("DEBUG: Setting current_price to default {} for MODEL MODE.".format(current_price), file=sys.stderr)

    # If still no strikes available, something is critically wrong
    if not strikes:
        return None, "No strikes available after processing."

    # NEW: Qualify all potential option contracts for the given expiry and strikes
    print("DEBUG: Qualifying all {} option contracts for {} {}...".format(len(strikes) * 2, symbol, expiry), file=sys.stderr)
    all_contracts_to_qualify = []
    for strike in strikes:
        all_contracts_to_qualify.append(Option(symbol, expiry, strike, 'C', 'SMART'))
        all_contracts_to_qualify.append(Option(symbol, expiry, strike, 'P', 'SMART'))
    
    try:
        ib.qualifyContracts(*all_contracts_to_qualify)
        print("DEBUG: Successfully qualified all {} option contracts.".format(len(all_contracts_to_qualify)), file=sys.stderr)
    except Exception as e:
        print("ERROR: Failed to qualify all option contracts: {}. Continuing anyway.".format(e), file=sys.stderr)
        # Continue anyway, individual fetches might still work or model fallback will kick in.

    # Rozhodni, či pôjdeme do model_mode (ak nemáme market data na greeks)
    # Heuristika: ak reqMktData na podklad hodilo subscription error (10089), current_price by bol NaN; už sme prešli fallback
    # Ak chceme model force, nastavíme model_mode True, keď greeks budú None v _select_leg (prepne sa tam)
    print("DEBUG: Final model_mode status before searching legs: {}".format(model_mode), file=sys.stderr)
    print("DEBUG: Current price: {}, Model Mode: {}, T_years: {:.3f}, Rate: {}, IV: {}".format(current_price, model_mode, T_years, rate, iv), file=sys.stderr)
    
    def make_leg(data, right):
        return {
            'symbol': symbol,
            'strike': data['strike'],
            'right': right,
            'expiry': expiry,
            'delta': round(data['delta'], 4),
            'gamma': round(data['gamma'], 6) if data['gamma'] else None,
            'vega': round(data['vega'], 4) if data['vega'] else None,
            'theta': round(data['theta'], 4) if data['theta'] else None,
            'iv': round(data['iv'], 4) if data['iv'] else None,
            'mid': round(data['mid'], 2) if data['mid'] else 0.0
        }
    
    candidates = []
    

    for tgt in targets:
        print("DEBUG: Searching target delta ~{}".format(tgt), file=sys.stderr)
        call_data = _select_leg(
            ib=ib, symbol=symbol, expiry=expiry, strikes=strikes, target_delta=abs(tgt), tol=tol,
            right='C', current_price=current_price, model_mode=model_mode, T_years=T_years, r=rate, iv=iv
        )
        put_data = _select_leg(
            ib=ib, symbol=symbol, expiry=expiry, strikes=strikes, target_delta=-abs(tgt), tol=tol,
            right='P', current_price=current_price, model_mode=model_mode, T_years=T_years, r=rate, iv=iv
        )
        
        if not call_data or not put_data:
            print("DEBUG: No legs found for target {}".format(tgt), file=sys.stderr)
            continue
        
        call_leg = make_leg(call_data, 'C')
        put_leg = make_leg(put_data, 'P')
        
        net_delta = call_leg['delta'] + put_leg['delta']
        total_gamma = (call_leg['gamma'] or 0) + (put_leg['gamma'] or 0)
        total_vega = (call_leg['vega'] or 0) + (put_leg['vega'] or 0)
        total_theta = (call_leg['theta'] or 0) + (put_leg['theta'] or 0)
        total_cost = (call_leg['mid'] or 0) + (put_leg['mid'] or 0)
        
        stats = {
            'netDelta': round(net_delta, 4),
            'totalGamma': round(total_gamma, 6),
            'totalVega': round(total_vega, 4),
            'totalTheta': round(total_theta, 4),
            'totalCost': round(total_cost, 2),
            'underlyingPrice': current_price
        }
        
        candidates.append({
            'target': tgt,
            'callLeg': call_leg,
            'putLeg': put_leg,
            'stats': stats
        })
    
    if not candidates:
        return None, "No candidates found for targets {}".format(targets)
    
    return candidates, None


def main():
    args = parse_args()
    
    try:
        from ib_insync import IB
    except Exception as e:
        print(json.dumps({'success': False, 'error': 'ib_insync not available: {}'.format(e)}))
        sys.exit(2)
    
    ib = IB()
    try:
        # Timeout increased for Live Gateway
        ib.connect(args.host, args.port, clientId=args.clientId, readonly=True, timeout=20)
    except Exception as e:
        print(json.dumps({'success': False, 'error': 'Cannot connect to TWS: {}'.format(e)}))
        sys.exit(3)
    
    # Request delayed data if available (MarketDataType 3 or 4)
    ib.reqMarketDataType(3)
    
    # Parse levels
    try:
        targets = [float(x.strip()) for x in args.levels.split(',') if x.strip()]
    except Exception:
        targets = [args.delta_target]
    if not targets:
        targets = [args.delta_target]
    
    candidates, err = find_strangle_levels(
        ib, args.symbol, args.expiry, targets, args.tol, args.rate, args.iv, args.model_priority, args.port
    )
    
    ib.disconnect()
    
    if not candidates:
        result = {
            'success': False,
            'error': err or 'No candidates'
        }
    else:
        # Vyber najlepší kandidát podľa Gamma/Theta ratio
        def ratio(c):
            theta = abs(c['stats'].get('totalTheta') or 0)
            gamma = c['stats'].get('totalGamma') or 0
            return (gamma / theta) if theta > 1e-6 else 0
        
        best = max(candidates, key=ratio)
        result = {
            'success': True,
            'bestCandidate': best,
            'candidates': candidates
        }
    
    with open(args.out, 'w') as f:
        json.dump(result, f, indent=2)
    
    print(json.dumps(result))
    sys.exit(0 if result['success'] else 1)


if __name__ == '__main__':
    main()
