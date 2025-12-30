#!/usr/bin/env python3
"""
Utility funkcie pre Hedge Manager GUI
- Black-Scholes výpočty
- Formátovanie
- Pomocné funkcie
"""
import math
import json
from datetime import datetime, date

try:
    from scipy.stats import norm
    from scipy.optimize import brentq
    SCIPY_AVAILABLE = True
except ImportError:
    SCIPY_AVAILABLE = False


def black_scholes_put_price(S, K, T, r, sigma):
    """Black-Scholes cena PUT"""
    if T <= 0:
        return max(K - S, 0)
    if not SCIPY_AVAILABLE:
        return max(K - S, 0) * 0.5  # Fallback
    d1 = (math.log(S / K) + (r + 0.5 * sigma ** 2) * T) / (sigma * math.sqrt(T))
    d2 = d1 - sigma * math.sqrt(T)
    return K * math.exp(-r * T) * norm.cdf(-d2) - S * norm.cdf(-d1)


def black_scholes_call_price(S, K, T, r, sigma):
    """Black-Scholes cena CALL"""
    if T <= 0:
        return max(S - K, 0)
    if not SCIPY_AVAILABLE:
        return max(S - K, 0) * 0.5  # Fallback
    d1 = (math.log(S / K) + (r + 0.5 * sigma ** 2) * T) / (sigma * math.sqrt(T))
    d2 = d1 - sigma * math.sqrt(T)
    return S * norm.cdf(d1) - K * math.exp(-r * T) * norm.cdf(d2)


def black_scholes_delta_put(S, K, T, r, sigma):
    """Black-Scholes delta PUT"""
    if T <= 0:
        return -1.0 if S < K else 0.0
    if not SCIPY_AVAILABLE:
        return -0.5 if S < K else -0.1  # Fallback
    d1 = (math.log(S / K) + (r + 0.5 * sigma ** 2) * T) / (sigma * math.sqrt(T))
    return norm.cdf(d1) - 1


def black_scholes_delta_call(S, K, T, r, sigma):
    """Black-Scholes delta CALL"""
    if T <= 0:
        return 1.0 if S > K else 0.0
    if not SCIPY_AVAILABLE:
        return 0.5 if S > K else 0.1  # Fallback
    d1 = (math.log(S / K) + (r + 0.5 * sigma ** 2) * T) / (sigma * math.sqrt(T))
    return norm.cdf(d1)


def black_scholes_theta(S, K, T, r, sigma, option_type='PUT'):
    """Theta per day (Black-Scholes)"""
    if T <= 0 or sigma <= 0:
        return 0.0
    if not SCIPY_AVAILABLE:
        return 0.0
    d1 = (math.log(S / K) + (r + 0.5 * sigma ** 2) * T) / (sigma * math.sqrt(T))
    d2 = d1 - sigma * math.sqrt(T)
    theta_annual = -(S * norm.pdf(d1) * sigma) / (2 * math.sqrt(T))
    if option_type == 'PUT':
        theta_annual += r * K * math.exp(-r * T) * norm.cdf(-d2)
    else:
        theta_annual -= r * K * math.exp(-r * T) * norm.cdf(d2)
    return theta_annual / 365.0


def get_option_price(S, K, T, r, sigma, is_call=False):
    """Vráti cenu opcie podľa typu"""
    if is_call:
        return black_scholes_call_price(S, K, T, r, sigma)
    else:
        return black_scholes_put_price(S, K, T, r, sigma)


def find_underlying_for_delta(target_delta, K, T, r, sigma, is_call=False):
    """Nájde cenu podkladu pre cieľovú deltu"""
    try:
        if is_call:
            def delta_diff(S):
                return black_scholes_delta_call(S, K, T, r, sigma) - target_delta
            if SCIPY_AVAILABLE:
                return brentq(delta_diff, K * 0.9, K * 1.3)
        else:
            def delta_diff(S):
                return black_scholes_delta_put(S, K, T, r, sigma) - target_delta
            if SCIPY_AVAILABLE:
                return brentq(delta_diff, K * 0.7, K * 1.1)
    except:
        pass
    return None


def get_time_to_expiry_years(expiry):
    """Return time to expiry in years (float)."""
    try:
        exp_date = datetime.strptime(expiry, '%Y%m%d').date()
        days = max(0, (exp_date - date.today()).days)
        return max(1/365.0, days / 365.0)
    except Exception:
        return 7/365.0


def find_strike_for_delta(option_type, target_delta, expiry, iv, r, underlying):
    """Hľadá strike tak, aby delta(option, K) == target_delta"""
    try:
        exp_date = datetime.strptime(expiry, '%Y%m%d').date()
        T = max(1, (exp_date - date.today()).days) / 365.0
    except Exception:
        T = 7/365.0
    
    def delta_for_K(K):
        if option_type == 'CALL':
            return black_scholes_delta_call(underlying, K, T, r, iv)
        else:
            return black_scholes_delta_put(underlying, K, T, r, iv)
    
    low = max(0.01, underlying * 0.2)
    high = underlying * 3.0
    
    # Try bracketing + brentq if scipy available
    if SCIPY_AVAILABLE:
        steps = 60
        ks = [low + (high - low) * i / steps for i in range(steps + 1)]
        fvals = [delta_for_K(k) - target_delta for k in ks]
        for i in range(len(ks) - 1):
            if fvals[i] == 0:
                return round(ks[i], 2)
            if fvals[i] * fvals[i + 1] < 0:
                try:
                    root = brentq(lambda K: delta_for_K(K) - target_delta, ks[i], ks[i+1])
                    return round(root, 2)
                except Exception:
                    break
    
    # Fallback: nearest in grid
    best_k = None
    best_diff = float('inf')
    for k in [low + (high-low)*i/200 for i in range(201)]:
        diff = abs(delta_for_K(k) - target_delta)
        if diff < best_diff:
            best_diff = diff
            best_k = k
    
    return round(best_k, 2) if best_k else None


def parse_option_fetch_output(output):
    """Rozparsuje JSON výstup z tws_fetch_option.py (price + theta + zdroj)."""
    if not output:
        raise ValueError("Žiadny výstup z TWS")
    if output.startswith("ERROR:"):
        raise ValueError(output.replace("ERROR:", "").strip())
    try:
        payload = json.loads(output)
        price = float(payload.get('price', 0))
        theta_val = payload.get('theta', 0)
        theta = float(theta_val or 0)
        source = payload.get('thetaSource', '') or 'tws'
        return price, theta, source
    except (json.JSONDecodeError, ValueError):
        return float(output.strip()), 0.0, 'raw'


def format_comparison(orig, new):
    """Formátuje porovnanie pôvodnej a novej stratégie"""
    if not orig:
        # Len nová stratégia
        return format_single_strategy(new, "AKTUÁLNA STRATÉGIA")
    
    # Porovnanie
    def delta_str(new_val, orig_val, fmt=".2f", suffix="", invert=False):
        if new_val == float('inf') or orig_val == float('inf'):
            return "∞"
        diff = new_val - orig_val
        if invert:
            diff = -diff
        sign = "+" if diff >= 0 else ""
        return f"{sign}{diff:{fmt}}{suffix}"
    
    # Použijeme additional margin pre porovnanie
    orig_margin_display = orig.get('additionalMargin', orig['margin'])
    new_margin_display = new.get('additionalMargin', new['margin'])
    
    result = f"""
╔══════════════════════════════════════════════════════════════════════════════╗
║                    📊 POROVNANIE STRATÉGIÍ                                   ║
╠══════════════════════════════════════════════════════════════════════════════╣
║                      PÔVODNÁ              →        UPRAVENÁ         ZMENA    ║
╠══════════════════════════════════════════════════════════════════════════════╣
║  Typ:         {orig['spreadType']:20}    {new['spreadType']:20}          ║
╠══════════════════════════════════════════════════════════════════════════════╣
║  SHORT:       ${orig['shortStrike']:<7.0f} @ ${orig['shortPremium']:<5.2f}      ${new['shortStrike']:<7.0f} @ ${new['shortPremium']:<5.2f}           ║
║  LONG:        ${orig['longStrike']:<7.0f} @ ${orig['longPremium']:<5.2f}      ${new['longStrike']:<7.0f} @ ${new['longPremium']:<5.2f}           ║
╠══════════════════════════════════════════════════════════════════════════════╣
║  Net:         ${orig.get('netCredit', 0) or -orig.get('netDebit', 0):<10.2f}         ${new.get('netCredit', 0) or -new.get('netDebit', 0):<10.2f}    {delta_str((new.get('netCredit', 0) or -new.get('netDebit', 0)), (orig.get('netCredit', 0) or -orig.get('netDebit', 0)))}     ║
║  Dod. Margin: ${orig_margin_display:<10.2f}         ${new_margin_display:<10.2f}    {delta_str(new_margin_display, orig_margin_display, ".2f", "", True)}     ║
║  Weekly ROI:  {orig['weeklyROI']:<10.2f}%        {new['weeklyROI']:<10.2f}%   {delta_str(new['weeklyROI'], orig['weeklyROI'])}%    ║
╠══════════════════════════════════════════════════════════════════════════════╣
║  Break-Even:  ${orig['breakEven']:<10.2f}         ${new['breakEven']:<10.2f}    {delta_str(new['breakEven'], orig['breakEven'])}     ║
╚══════════════════════════════════════════════════════════════════════════════╝
"""
    
    # Hodnotenie
    roi_diff = new['weeklyROI'] - orig['weeklyROI']
    if roi_diff > 0.5:
        result += f"\n✅ LEPŠIE: ROI zvýšené o {roi_diff:.2f}%"
    elif roi_diff < -0.5:
        result += f"\n⚠️ HORŠIE: ROI znížené o {abs(roi_diff):.2f}%"
    else:
        result += f"\n➡️ PODOBNÉ: ROI rozdiel {roi_diff:.2f}%"
    
    return result


def format_single_strategy(calc, title):
    """Formátuje jednu stratégiu"""
    net_str = f"${calc.get('netCredit', 0):.2f}" if calc['isCredit'] else f"-${calc.get('netDebit', 0):.2f}"
    max_profit_str = f"${calc['maxProfit']:.0f}" if calc['maxProfit'] != float('inf') else "∞"
    max_loss_str = f"${calc['maxLoss']:.0f}" if calc['maxLoss'] != float('inf') else "∞"
    
    return f"""
╔══════════════════════════════════════════════════════════════════╗
║  {title:^60}  ║
╠══════════════════════════════════════════════════════════════════╣
║  Typ: {calc['spreadType']:55} ║
║  SHORT: ${calc['shortStrike']:.0f} @ ${calc['shortPremium']:.2f} (DTE: {calc['shortDTE']})                          ║
║  LONG:  ${calc['longStrike']:.0f} @ ${calc['longPremium']:.2f} (DTE: {calc['longDTE']})                          ║
╠══════════════════════════════════════════════════════════════════╣
║  Net:        {net_str:15}    Max Profit: {max_profit_str:12}   ║
║  Margin:     ${calc['margin']:<13.0f}    Max Loss:   {max_loss_str:12}   ║
║  Weekly ROI: {calc['weeklyROI']:<13.2f}%   Break-Even: ${calc['breakEven']:<10.2f}   ║
╚══════════════════════════════════════════════════════════════════╝
"""

