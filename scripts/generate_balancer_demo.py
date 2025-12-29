#!/usr/bin/env python3
"""Generate Balancer P/L demo plot and save to a file.
Usage: python scripts/generate_balancer_demo.py [--s S0] [--long K] [--opp K] [--out FILE]
"""
import argparse
from datetime import date, timedelta, datetime
import math

try:
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
except Exception as e:
    print('ERROR: matplotlib required:', e)
    raise


def norm_cdf(x):
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def bs_d1(S,K,T,r,sigma):
    return (math.log(S/K) + (r + 0.5*sigma*sigma)*T) / (sigma*math.sqrt(T))


def bs_call_price(S,K,T,r,sigma):
    if T<=0 or sigma<=0:
        return max(S-K,0)
    d1=bs_d1(S,K,T,r,sigma)
    d2=d1 - sigma*math.sqrt(T)
    return S*norm_cdf(d1) - K*math.exp(-r*T)*norm_cdf(d2)


def bs_put_price(S,K,T,r,sigma):
    if T<=0 or sigma<=0:
        return max(K-S,0)
    d1=bs_d1(S,K,T,r,sigma)
    d2=d1 - sigma*math.sqrt(T)
    return K*math.exp(-r*T)*norm_cdf(-d2) - S*norm_cdf(-d1)


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--s', type=float, default=712.0, help='Underlying price S0')
    p.add_argument('--atr', type=float, default=5.0, help='ATR')
    p.add_argument('--atr-mult', type=float, default=1.0, help='ATR multiplier for range')
    p.add_argument('--long-type', choices=['CALL','PUT'], default='CALL')
    p.add_argument('--long-strike', type=float, default=710.0)
    p.add_argument('--opp-type', choices=['CALL','PUT'], default='PUT')
    p.add_argument('--opp-strike', type=float, default=707.5)
    p.add_argument('--iv', type=float, default=0.22)
    p.add_argument('--days', type=int, default=30, help='Days to expiry')
    p.add_argument('--out', type=str, default='app/static/images/balancer_demo_saved.png')
    args = p.parse_args()

    S0 = args.s
    atr = args.atr
    mult = args.atr_mult
    low = max(0.01, S0 - atr*mult)
    high = S0 + atr*mult
    Ss = [low + (high-low)*i/120 for i in range(121)]

    T = max(1, args.days) / 365.0
    r = 0.01

    long_type = args.long_type
    long_strike = args.long_strike
    opp_type = args.opp_type
    opp_strike = args.opp_strike
    iv = args.iv

    pl_vals = []
    for S in Ss:
        if long_type == 'CALL':
            long_price = bs_call_price(S, long_strike, T, r, iv)
        else:
            long_price = bs_put_price(S, long_strike, T, r, iv)

        if opp_type == 'CALL':
            opp_price = bs_call_price(S, opp_strike, T, r, iv)
        else:
            opp_price = bs_put_price(S, opp_strike, T, r, iv)

        pl_vals.append((long_price - opp_price) * 100.0)

    fig, ax = plt.subplots(figsize=(8,4.5))
    ax.plot(Ss, pl_vals, label=f'P/L (LONG {long_type} K={long_strike} - OPP {opp_type} K={opp_strike})')
    ax.axhline(0, color='black', linewidth=0.8, linestyle='--')
    ax.axvline(S0, color='gray', linestyle='--', label='Current S')
    ax.axvline(S0 - atr*mult, color='red', linestyle=':', label=f'-{mult}×ATR')
    ax.axvline(S0 + atr*mult, color='red', linestyle=':', label=f'+{mult}×ATR')

    idx = min(range(len(Ss)), key=lambda i: abs(Ss[i]-S0))
    cur_pl = pl_vals[idx]
    ax.annotate(f'S0 ${S0:.2f}\nP/L ${cur_pl:.2f}', xy=(S0, cur_pl), xytext=(10, 10), textcoords='offset points', bbox=dict(boxstyle='round', fc='w'))

    ax.set_xlabel('Underlying Price')
    ax.set_ylabel('P/L $ per pair')
    ax.grid(True)
    ax.legend()
    fig.tight_layout()

    fig.savefig(args.out, dpi=150)
    print('Saved', args.out)


if __name__ == '__main__':
    main()
