#!/usr/bin/env python3
"""
Delta to Price Calculator - Prepočíta pri akej cene podkladu dosiahne opcia určitú deltu

Použitie:
  python delta_price_calc.py --symbol SPY --strike 659 --expiry 20260102 --port 7496

Výstup:
  - Pri akej cene SPY bude delta -0.30, -0.40, -0.50
  - Odporúčané stop-loss ceny
"""
import argparse
import json
import sys
import random
import math
from datetime import datetime, date
from scipy.stats import norm
from scipy.optimize import brentq

# ============ BLACK-SCHOLES ============

def black_scholes_delta_put(S, K, T, r, sigma):
    """Vypočíta deltu PUT opcie"""
    if T <= 0:
        return -1.0 if S < K else 0.0
    
    d1 = (math.log(S / K) + (r + 0.5 * sigma ** 2) * T) / (sigma * math.sqrt(T))
    return norm.cdf(d1) - 1  # Put delta


def black_scholes_put_price(S, K, T, r, sigma):
    """Vypočíta cenu PUT opcie"""
    if T <= 0:
        return max(K - S, 0)
    
    d1 = (math.log(S / K) + (r + 0.5 * sigma ** 2) * T) / (sigma * math.sqrt(T))
    d2 = d1 - sigma * math.sqrt(T)
    return K * math.exp(-r * T) * norm.cdf(-d2) - S * norm.cdf(-d1)


def find_underlying_for_delta(target_delta, K, T, r, sigma, S_low, S_high):
    """Nájde cenu podkladu pri ktorej opcia má target_delta"""
    try:
        def delta_diff(S):
            return black_scholes_delta_put(S, K, T, r, sigma) - target_delta
        
        # Brentq hľadá koreň (kde delta_diff = 0)
        S_target = brentq(delta_diff, S_low, S_high)
        return S_target
    except:
        return None


def days_to_expiry(expiry_str):
    """Vypočíta dni do expirácie"""
    expiry = datetime.strptime(expiry_str, '%Y%m%d').date()
    today = date.today()
    return (expiry - today).days


def parse_args():
    p = argparse.ArgumentParser(description='Delta to Price Calculator')
    p.add_argument('--symbol', required=True, help='Symbol (SPY, QQQ...)')
    p.add_argument('--strike', type=float, required=True, help='Strike short PUT')
    p.add_argument('--expiry', required=True, help='Expirácia (YYYYMMDD)')
    p.add_argument('--port', type=int, default=7496, help='TWS port')
    p.add_argument('--rate', type=float, default=0.05, help='Bezriziková sadzba')
    p.add_argument('--out', default='/tmp/delta_price_calc.json', help='Output JSON')
    return p.parse_args()


def get_current_iv(ib, symbol, expiry, strike):
    """Získa aktuálnu IV z opcie"""
    from ib_insync import Option
    
    contract = Option(symbol, expiry, strike, 'P', 'SMART')
    try:
        ib.qualifyContracts(contract)
        ticker = ib.reqMktData(contract, '106', snapshot=False)
        
        for _ in range(40):
            ib.sleep(0.25)
            mg = ticker.modelGreeks
            if mg and mg.impliedVol is not None:
                ib.cancelMktData(contract)
                return mg.impliedVol, mg.delta, mg.optPrice
        ib.cancelMktData(contract)
    except:
        pass
    return 0.18, None, None  # Default IV


def main():
    args = parse_args()
    
    try:
        from ib_insync import IB, Stock
    except ImportError:
        print("Chyba: ib_insync nie je nainštalovaný")
        sys.exit(1)
    
    ib = IB()
    client_id = random.randint(1000, 9999)
    
    try:
        ib.connect('127.0.0.1', args.port, clientId=client_id, readonly=True)
        print(f"Pripojené k TWS", file=sys.stderr)
    except Exception as e:
        print(f"Nepodarilo sa pripojiť: {e}")
        sys.exit(1)
    
    ib.reqMarketDataType(4)
    
    # Získaj aktuálnu cenu
    stock = Stock(args.symbol, 'SMART', 'USD')
    ib.qualifyContracts(stock)
    ticker = ib.reqMktData(stock, '', False, False)
    ib.sleep(2)
    current_price = ticker.last if ticker.last and ticker.last == ticker.last else ticker.close
    ib.cancelMktData(stock)
    
    # Získaj IV a aktuálnu deltu
    iv, current_delta, current_opt_price = get_current_iv(ib, args.symbol, args.expiry, args.strike)
    
    ib.disconnect()
    
    # Parametre
    K = args.strike
    T = days_to_expiry(args.expiry) / 365
    r = args.rate
    sigma = iv
    
    print(f"\n{'='*60}", file=sys.stderr)
    print(f"DELTA → PRICE KALKULÁTOR pre {args.symbol}", file=sys.stderr)
    print(f"{'='*60}", file=sys.stderr)
    print(f"Aktuálna cena {args.symbol}: ${current_price:.2f}", file=sys.stderr)
    print(f"Strike: ${K}", file=sys.stderr)
    print(f"Expirácia: {args.expiry} ({int(T*365)} dní)", file=sys.stderr)
    print(f"IV: {sigma:.1%}", file=sys.stderr)
    if current_delta:
        print(f"Aktuálna delta: {current_delta:.4f}", file=sys.stderr)
    if current_opt_price:
        print(f"Aktuálna cena opcie: ${current_opt_price:.2f}", file=sys.stderr)
    print(f"{'='*60}\n", file=sys.stderr)
    
    # Vypočítaj ceny pre rôzne delty
    delta_targets = [-0.20, -0.25, -0.30, -0.35, -0.40, -0.50]
    results = []
    
    print(f"{'Delta':<10} {'Cena '+args.symbol:<15} {'Cena opcie':<15} {'Akcia'}", file=sys.stderr)
    print("-" * 60, file=sys.stderr)
    
    for target_delta in delta_targets:
        # Nájdi cenu podkladu
        S_target = find_underlying_for_delta(target_delta, K, T, r, sigma, K * 0.7, K * 1.1)
        
        if S_target:
            opt_price = black_scholes_put_price(S_target, K, T, r, sigma)
            
            # Určí akciu
            if target_delta == -0.30:
                action = "🔄 ROLL TRIGGER"
            elif target_delta == -0.50:
                action = "🛑 STOP LOSS"
            elif target_delta == -0.25:
                action = "⚠️  Pozor"
            else:
                action = ""
            
            results.append({
                'targetDelta': target_delta,
                'underlyingPrice': round(S_target, 2),
                'optionPrice': round(opt_price, 2),
                'action': action
            })
            
            print(f"{target_delta:<10.2f} ${S_target:<14.2f} ${opt_price:<14.2f} {action}", file=sys.stderr)
    
    # Výpočet pre konkrétne stop-loss scenáre
    print(f"\n{'='*60}", file=sys.stderr)
    print("ODPORÚČANÉ STOP-LOSS / ALERT ÚROVNE:", file=sys.stderr)
    print(f"{'='*60}", file=sys.stderr)
    
    # Alert keď delta = -0.25
    alert_price = find_underlying_for_delta(-0.25, K, T, r, sigma, K * 0.7, K * 1.1)
    roll_price = find_underlying_for_delta(-0.30, K, T, r, sigma, K * 0.7, K * 1.1)
    stop_price = find_underlying_for_delta(-0.50, K, T, r, sigma, K * 0.7, K * 1.1)
    
    if alert_price:
        print(f"⚠️  ALERT:      {args.symbol} klesne pod ${alert_price:.2f} (delta=-0.25)", file=sys.stderr)
    if roll_price:
        print(f"🔄 ROLL:       {args.symbol} klesne pod ${roll_price:.2f} (delta=-0.30)", file=sys.stderr)
    if stop_price:
        print(f"🛑 STOP LOSS:  {args.symbol} klesne pod ${stop_price:.2f} (delta=-0.50)", file=sys.stderr)
    
    # Breakeven (strike - premium)
    if current_opt_price:
        breakeven = K - current_opt_price
        print(f"📊 BREAKEVEN:  ${breakeven:.2f}", file=sys.stderr)
    
    print(f"{'='*60}\n", file=sys.stderr)
    
    # Výstup pre broker
    print("PRE NASTAVENIE V BROKERI:", file=sys.stderr)
    print("-" * 60, file=sys.stderr)
    if roll_price:
        print(f"Stop Loss na {args.symbol}: ${roll_price:.2f}", file=sys.stderr)
        print(f"   → Keď {args.symbol} klesne pod túto cenu, zatvorte/rollujte pozíciu", file=sys.stderr)
    
    # JSON output
    output = {
        'symbol': args.symbol,
        'strike': K,
        'expiry': args.expiry,
        'currentPrice': current_price,
        'currentDelta': current_delta,
        'currentOptionPrice': current_opt_price,
        'iv': round(sigma, 4),
        'daysToExpiry': int(T * 365),
        'deltaPriceLevels': results,
        'recommendations': {
            'alertPrice': round(alert_price, 2) if alert_price else None,
            'rollPrice': round(roll_price, 2) if roll_price else None,
            'stopLossPrice': round(stop_price, 2) if stop_price else None,
            'breakeven': round(K - (current_opt_price or 0), 2)
        }
    }
    
    with open(args.out, 'w') as f:
        json.dump(output, f, indent=2)
    
    print(json.dumps(output, indent=2))


if __name__ == '__main__':
    main()
