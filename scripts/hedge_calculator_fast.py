#!/usr/bin/env python3
"""
Hedge Calculator FAST - Používa Black-Scholes pre rýchly výpočet
Nepotrebuje market data pre každý strike - počíta lokálne!

Potrebuje z API len:
1. Aktuálnu cenu podkladu
2. IV z jednej referenčnej opcie

Použitie:
  python hedge_calculator_fast.py --symbol SPY --min-premium 0.70 --port 7496
"""
import argparse
import json
import sys
import random
import math
from datetime import datetime, date
from scipy.stats import norm

# ============ BLACK-SCHOLES MODEL ============

def black_scholes_put(S, K, T, r, sigma):
    """
    Vypočíta cenu PUT opcie pomocou Black-Scholes
    S = aktuálna cena podkladu
    K = strike price
    T = čas do expirácie v rokoch
    r = bezriziková úroková sadzba
    sigma = implicitná volatilita
    """
    if T <= 0:
        return max(K - S, 0)
    
    d1 = (math.log(S / K) + (r + 0.5 * sigma ** 2) * T) / (sigma * math.sqrt(T))
    d2 = d1 - sigma * math.sqrt(T)
    
    put_price = K * math.exp(-r * T) * norm.cdf(-d2) - S * norm.cdf(-d1)
    return put_price


def calculate_greeks(S, K, T, r, sigma, option_type='P'):
    """Vypočíta greeks pre opciu"""
    if T <= 0:
        return {'delta': 0, 'gamma': 0, 'theta': 0, 'vega': 0}
    
    d1 = (math.log(S / K) + (r + 0.5 * sigma ** 2) * T) / (sigma * math.sqrt(T))
    d2 = d1 - sigma * math.sqrt(T)
    
    # Delta
    if option_type == 'P':
        delta = norm.cdf(d1) - 1  # Put delta je záporná
    else:
        delta = norm.cdf(d1)
    
    # Gamma (rovnaká pre put aj call)
    gamma = norm.pdf(d1) / (S * sigma * math.sqrt(T))
    
    # Theta (denná)
    theta_annual = -(S * norm.pdf(d1) * sigma) / (2 * math.sqrt(T))
    if option_type == 'P':
        theta_annual += r * K * math.exp(-r * T) * norm.cdf(-d2)
    else:
        theta_annual -= r * K * math.exp(-r * T) * norm.cdf(d2)
    theta_daily = theta_annual / 365
    
    # Vega (na 1% zmenu IV)
    vega = S * math.sqrt(T) * norm.pdf(d1) / 100
    
    return {
        'delta': round(delta, 4),
        'gamma': round(gamma, 6),
        'theta': round(theta_daily, 4),
        'vega': round(vega, 4)
    }


def days_to_expiry(expiry_str):
    """Vypočíta dni do expirácie"""
    expiry = datetime.strptime(expiry_str, '%Y%m%d').date()
    today = date.today()
    return (expiry - today).days


def find_strike_for_premium(S, T, r, sigma, target_premium, min_strike, max_strike):
    """Nájde strike, ktorý má približne target premium (binárne hľadanie)"""
    low, high = min_strike, max_strike
    
    while high - low > 0.5:  # Presnosť $0.50
        mid = (low + high) / 2
        price = black_scholes_put(S, mid, T, r, sigma)
        
        if price < target_premium:
            low = mid
        else:
            high = mid
    
    return round((low + high) / 2)


def get_iv_from_api(ib, symbol, current_price, expiry):
    """Získa IV z jednej referenčnej opcie (ATM)"""
    from ib_insync import Option
    
    # ATM strike (najbližší k aktuálnej cene)
    atm_strike = round(current_price)
    
    contract = Option(symbol, expiry, atm_strike, 'P', 'SMART')
    try:
        ib.qualifyContracts(contract)
        ticker = ib.reqMktData(contract, '106', snapshot=False)
        
        for _ in range(40):  # 10 sekúnd
            ib.sleep(0.25)
            mg = ticker.modelGreeks
            if mg and mg.impliedVol is not None:
                ib.cancelMktData(contract)
                return mg.impliedVol
        
        ib.cancelMktData(contract)
    except Exception as e:
        print(f"  Nepodarilo sa získať IV: {e}", file=sys.stderr)
    
    # Default IV ak nedostaneme z API
    return 0.18  # ~18% je typická pre SPY


def parse_args():
    p = argparse.ArgumentParser(description='Hedge Calculator FAST (Black-Scholes)')
    p.add_argument('--symbol', required=True, help='Symbol (SPY, QQQ...)')
    p.add_argument('--min-premium', type=float, default=0.70, help='Min premium pre short ($)')
    p.add_argument('--short-expiry', help='Short expirácia (YYYYMMDD)')
    p.add_argument('--long-expiry', help='Long expirácia (YYYYMMDD)')
    p.add_argument('--port', type=int, default=7496, help='TWS port')
    p.add_argument('--rate', type=float, default=0.05, help='Bezriziková sadzba (default 5%)')
    p.add_argument('--out', default='/tmp/hedge_calc_result.json', help='Output JSON')
    return p.parse_args()


def main():
    args = parse_args()
    
    try:
        from ib_insync import IB, Stock, Option
    except ImportError:
        print(json.dumps({'success': False, 'error': 'ib_insync not installed'}))
        sys.exit(1)
    
    ib = IB()
    client_id = random.randint(1000, 9999)
    
    try:
        ib.connect('127.0.0.1', args.port, clientId=client_id, readonly=True)
        print(f"Pripojené k TWS (port {args.port})", file=sys.stderr)
    except Exception as e:
        print(json.dumps({'success': False, 'error': f'Cannot connect: {e}'}))
        sys.exit(1)
    
    ib.reqMarketDataType(4)  # Delayed frozen
    
    # 1. Získaj aktuálnu cenu
    stock = Stock(args.symbol, 'SMART', 'USD')
    ib.qualifyContracts(stock)
    ticker = ib.reqMktData(stock, '', False, False)
    ib.sleep(2)
    current_price = ticker.last if ticker.last and ticker.last == ticker.last else ticker.close
    ib.cancelMktData(stock)
    print(f"Aktuálna cena {args.symbol}: ${current_price:.2f}", file=sys.stderr)
    
    # 2. Získaj dostupné expirácie
    opt = Option(args.symbol, '', 0, 'P', 'SMART')
    details = ib.reqContractDetails(opt)
    expiries = sorted(set(d.contract.lastTradeDateOrContractMonth for d in details))
    
    if not args.short_expiry:
        args.short_expiry = expiries[1] if len(expiries) > 1 else expiries[0]
    if not args.long_expiry:
        args.long_expiry = expiries[4] if len(expiries) > 4 else expiries[-1]
    
    print(f"Short expiry: {args.short_expiry}", file=sys.stderr)
    print(f"Long expiry: {args.long_expiry}", file=sys.stderr)
    
    # 3. Získaj IV z ATM opcie
    print("Získavam IV z ATM opcie...", file=sys.stderr)
    iv = get_iv_from_api(ib, args.symbol, current_price, args.short_expiry)
    print(f"Implicitná volatilita: {iv:.1%}", file=sys.stderr)
    
    # 4. LOKÁLNY VÝPOČET - Black-Scholes
    print("\n=== LOKÁLNY VÝPOČET (Black-Scholes) ===", file=sys.stderr)
    
    T_short = days_to_expiry(args.short_expiry) / 365
    T_long = days_to_expiry(args.long_expiry) / 365
    r = args.rate
    
    print(f"Dni do short expiry: {int(T_short * 365)}", file=sys.stderr)
    print(f"Dni do long expiry: {int(T_long * 365)}", file=sys.stderr)
    
    # Nájdi SHORT PUT s premium >= min_premium
    print(f"\nHľadám SHORT PUT s premium >= ${args.min_premium}...", file=sys.stderr)
    
    short_candidates = []
    # Prehľadaj strikes od ATM-2% smerom dole
    for strike in range(int(current_price * 0.98), int(current_price * 0.85), -1):
        price = black_scholes_put(current_price, strike, T_short, r, iv)
        if price >= args.min_premium:
            greeks = calculate_greeks(current_price, strike, T_short, r, iv, 'P')
            short_candidates.append({
                'strike': strike,
                'expiry': args.short_expiry,
                'premium': round(price, 2),
                **greeks
            })
            if len(short_candidates) >= 5:
                break
    
    if not short_candidates:
        ib.disconnect()
        result = {'success': False, 'error': f'Nenašiel som short put s premium >= ${args.min_premium}'}
        print(json.dumps(result))
        sys.exit(1)
    
    # Vyber najlepší short (najvyššia theta)
    short_leg = max(short_candidates, key=lambda x: abs(x['theta']))
    print(f"  ✓ SHORT: Strike {short_leg['strike']}, Premium ${short_leg['premium']:.2f}, " +
          f"Delta={short_leg['delta']:.3f}, Theta={short_leg['theta']:.4f}", file=sys.stderr)
    
    # Nájdi LONG PUT hedge (min theta, min delta)
    print(f"\nHľadám LONG PUT hedge (min theta + delta)...", file=sys.stderr)
    
    long_candidates = []
    # Hľadaj 15-40 bodov pod short (rozumný spread width)
    for strike in range(int(short_leg['strike'] - 40), int(short_leg['strike'] - 15)):
        price = black_scholes_put(current_price, strike, T_long, r, iv)
        greeks = calculate_greeks(current_price, strike, T_long, r, iv, 'P')
        # Len ak má nejakú hodnotu (> $0.10)
        if price >= 0.10:
            long_candidates.append({
                'strike': strike,
                'expiry': args.long_expiry,
                'premium': round(price, 2),
                **greeks
            })
    
    if not long_candidates:
        ib.disconnect()
        result = {'success': False, 'error': 'Nenašiel som vhodný long put hedge'}
        print(json.dumps(result))
        sys.exit(1)
    
    # Vyber s najmenšou theta + delta (score)
    long_leg = min(long_candidates, key=lambda x: abs(x['theta']) + abs(x['delta']))
    print(f"  ✓ LONG: Strike {long_leg['strike']}, Premium ${long_leg['premium']:.2f}, " +
          f"Delta={long_leg['delta']:.3f}, Theta={long_leg['theta']:.4f}", file=sys.stderr)
    
    # 5. Vypočítaj stratégiu
    net_credit = short_leg['premium'] - long_leg['premium']
    spread_width = short_leg['strike'] - long_leg['strike']
    max_profit = net_credit * 100
    max_loss = (spread_width - net_credit) * 100
    breakeven = short_leg['strike'] - net_credit
    
    print(f"\n=== VÝSLEDOK ===", file=sys.stderr)
    print(f"Net Credit: ${net_credit:.2f} (${max_profit:.0f} per contract)", file=sys.stderr)
    print(f"Max Loss: ${max_loss:.0f}", file=sys.stderr)
    print(f"Breakeven: ${breakeven:.2f}", file=sys.stderr)
    print(f"Spread Width: ${spread_width}", file=sys.stderr)
    
    ib.disconnect()
    
    result = {
        'success': True,
        'symbol': args.symbol,
        'currentPrice': current_price,
        'impliedVolatility': round(iv, 4),
        'shortLeg': {
            'action': 'SELL',
            'strike': short_leg['strike'],
            'expiry': args.short_expiry,
            'type': 'PUT',
            'premium': short_leg['premium'],
            'delta': short_leg['delta'],
            'theta': short_leg['theta'],
            'gamma': short_leg['gamma']
        },
        'longLeg': {
            'action': 'BUY',
            'strike': long_leg['strike'],
            'expiry': args.long_expiry,
            'type': 'PUT',
            'premium': long_leg['premium'],
            'delta': long_leg['delta'],
            'theta': long_leg['theta'],
            'gamma': long_leg['gamma']
        },
        'strategy': {
            'netCredit': round(net_credit, 2),
            'maxProfit': round(max_profit, 2),
            'maxLoss': round(max_loss, 2),
            'breakeven': round(breakeven, 2),
            'spreadWidth': spread_width,
            'netDelta': round(short_leg['delta'] + long_leg['delta'], 4),
            'netTheta': round(short_leg['theta'] + long_leg['theta'], 4)
        },
        'exitPlan': {
            'profit50': f"Close pri net debit ${net_credit * 0.5:.2f} (50% profit)",
            'breakeven': f"${breakeven:.2f}",
            'rollTrigger': "Roll ak delta short > -0.30"
        },
        'note': 'Theoretical values (Black-Scholes). Reálne ceny môžu byť mierne odlišné.'
    }
    
    with open(args.out, 'w') as f:
        json.dump(result, f, indent=2)
    
    print(json.dumps(result, indent=2))
    sys.exit(0)


if __name__ == '__main__':
    main()
