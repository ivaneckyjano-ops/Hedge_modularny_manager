#!/usr/bin/env python3
"""
TWS Hedge Spread Finder - finds optimal hedge combination (short + long legs).

Usage:
  tws_hedge_finder.py --symbol UNH --expiry-short 20250117 --type-short PUT \
                      --delta-target -0.10 --expiry-long 20250124 --type-long CALL \
                      --port 7497 --out /tmp/hedge_result.json

Outputs JSON with short leg, long leg, and spread stats.
"""
import argparse
import json
import sys
from ib_insync import IB, Option


def parse_args():
    p = argparse.ArgumentParser(description='Find optimal hedge spread (short + long legs)')
    p.add_argument('--symbol', required=True, help='Stock symbol (e.g., UNH)')
    p.add_argument('--expiry-short', required=True, help='Short leg expiry (YYYYMMDD)')
    p.add_argument('--type-short', choices=['C', 'P'], required=True, help='Short leg type (C/P)')
    p.add_argument('--delta-target', type=float, required=True, help='Target delta for short leg')
    p.add_argument('--expiry-long', required=True, help='Long leg expiry (YYYYMMDD)')
    p.add_argument('--type-long', choices=['C', 'P'], required=True, help='Long leg type (C/P)')
    p.add_argument('--tol', type=float, default=0.02, help='Delta tolerance (default 0.02)')
    p.add_argument('--port', type=int, default=7497, help='TWS port (default 7497 for Paper)')
    p.add_argument('--host', default='127.0.0.1')
    p.add_argument('--clientId', type=int, default=100)
    p.add_argument('--out', default='/tmp/hedge_result.json', help='Output JSON file')
    return p.parse_args()


def _fetch_greeks_for_strike(ib, symbol, expiry, strike, right, timeout_sec=2):
    """Fetch market data and return greeks + price for a contract."""
    try:
        contract = Option(symbol, expiry, strike, right, 'SMART')
        ib.qualifyContracts(contract)
        ticker = ib.reqMktData(contract, '106', False, False)
        
        # Wait for data
        for _ in range(int(timeout_sec / 0.2)):
            ib.sleep(0.2)
            mg = getattr(ticker, 'modelGreeks', None) or getattr(ticker, 'lastGreeks', None)
            if mg and getattr(mg, 'delta', None) is not None:
                bid = getattr(ticker, 'bid', None)
                ask = getattr(ticker, 'ask', None)
                mid = (bid + ask) / 2 if bid and ask else None
                ib.cancelMktData(contract)
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
        return None
    except Exception:
        try:
            ib.cancelMktData(contract)
        except Exception:
            pass
        return None


def find_hedge_spread(ib, symbol, expiry_short, type_short, delta_target, 
                      expiry_long, type_long, tol=0.02):
    """
    Find optimal short leg and matching long leg for hedge spread.
    Returns: (short_leg_data, long_leg_data, stats) or (None, None, error_msg)
    """
    
    # 1. Get available strikes for short expiry
    try:
        opt_template_short = Option(symbol, expiry_short, 0, type_short, 'SMART')
        details_short = ib.reqContractDetails(opt_template_short)
        if not details_short:
            return None, None, f"No option details for {symbol} {expiry_short} {type_short}"
        strikes_short = sorted({d.contract.strike for d in details_short})
    except Exception as e:
        return None, None, f"Error fetching short leg strikes: {e}"
    
    # 2. Find short leg with delta closest to target
    best_short = None
    best_short_data = None
    best_short_delta_diff = float('inf')
    
    # Only search strikes within ±20% of current price (if available)
    try:
        from ib_insync import Stock
        stock = Stock(symbol, 'SMART', 'USD')
        ib.qualifyContracts(stock)
        stock_ticker = ib.reqMktData(stock, '', False, False)
        ib.sleep(1)
        current_price = stock_ticker.last if stock_ticker.last else stock_ticker.close
        ib.cancelMktData(stock)
        if current_price and current_price == current_price:
            strikes_short = [s for s in strikes_short if abs(s - current_price) / current_price <= 0.2]
    except Exception:
        pass  # Use all strikes if price fetch fails
    
    for strike in strikes_short:
        data = _fetch_greeks_for_strike(ib, symbol, expiry_short, strike, type_short)
        if data and data['delta'] is not None:
            delta_diff = abs(data['delta'] - delta_target)
            if delta_diff <= tol and delta_diff < best_short_delta_diff:
                best_short_delta_diff = delta_diff
                best_short = strike
                best_short_data = data
    
    if not best_short_data:
        return None, None, f"No short leg found with delta within {tol} of {delta_target}"
    
    # 3. Get available strikes for long expiry
    try:
        opt_template_long = Option(symbol, expiry_long, 0, type_long, 'SMART')
        details_long = ib.reqContractDetails(opt_template_long)
        if not details_long:
            return None, None, f"No option details for {symbol} {expiry_long} {type_long}"
        strikes_long = sorted({d.contract.strike for d in details_long})
    except Exception as e:
        return None, None, f"Error fetching long leg strikes: {e}"
    
    # 4. Find long leg with delta that hedges short leg (opposite sign, same magnitude)
    hedge_delta_target = -best_short_data['delta']  # Opposite sign
    best_long = None
    best_long_data = None
    best_long_delta_diff = float('inf')
    
    strikes_long = [s for s in strikes_long if abs(s - current_price) / current_price <= 0.2] if current_price else strikes_long
    
    for strike in strikes_long:
        data = _fetch_greeks_for_strike(ib, symbol, expiry_long, strike, type_long)
        if data and data['delta'] is not None:
            delta_diff = abs(data['delta'] - hedge_delta_target)
            if delta_diff <= tol and delta_diff < best_long_delta_diff:
                best_long_delta_diff = delta_diff
                best_long = strike
                best_long_data = data
    
    if not best_long_data:
        return None, None, f"No long leg found with delta within {tol} of {hedge_delta_target}"
    
    # 5. Calculate spread stats
    short_leg = {
        'symbol': symbol,
        'strike': best_short_data['strike'],
        'right': type_short,
        'expiry': expiry_short,
        'delta': round(best_short_data['delta'], 4),
        'gamma': round(best_short_data['gamma'], 6) if best_short_data['gamma'] else None,
        'vega': round(best_short_data['vega'], 4) if best_short_data['vega'] else None,
        'theta': round(best_short_data['theta'], 4) if best_short_data['theta'] else None,
        'iv': round(best_short_data['iv'], 4) if best_short_data['iv'] else None,
        'bid': round(best_short_data['bid'], 2) if best_short_data['bid'] else None,
        'ask': round(best_short_data['ask'], 2) if best_short_data['ask'] else None,
        'mid': round(best_short_data['mid'], 2) if best_short_data['mid'] else None
    }
    
    long_leg = {
        'symbol': symbol,
        'strike': best_long_data['strike'],
        'right': type_long,
        'expiry': expiry_long,
        'delta': round(best_long_data['delta'], 4),
        'gamma': round(best_long_data['gamma'], 6) if best_long_data['gamma'] else None,
        'vega': round(best_long_data['vega'], 4) if best_long_data['vega'] else None,
        'theta': round(best_long_data['theta'], 4) if best_long_data['theta'] else None,
        'iv': round(best_long_data['iv'], 4) if best_long_data['iv'] else None,
        'bid': round(best_long_data['bid'], 2) if best_long_data['bid'] else None,
        'ask': round(best_long_data['ask'], 2) if best_long_data['ask'] else None,
        'mid': round(best_long_data['mid'], 2) if best_long_data['mid'] else None
    }
    
    # Spread calculations
    net_delta = short_leg['delta'] + long_leg['delta']
    short_premium = short_leg['mid']
    long_cost = long_leg['mid']
    net_credit = short_premium - long_cost if short_premium and long_cost else None
    
    # For PUT spread: max loss = abs(short_strike - long_strike) - credit
    # For CALL spread: max loss = abs(long_strike - short_strike) - credit
    # For mixed (hedge): depends on direction
    if type_short == 'P' and type_long == 'C':
        # Vertical spread (different rights)
        max_loss = abs(short_leg['strike'] - long_leg['strike']) - (net_credit or 0) if net_credit else None
        max_profit = net_credit
        if type_short == 'P':
            breakeven = short_leg['strike'] - (net_credit or 0) if net_credit else None
        else:
            breakeven = short_leg['strike'] + (net_credit or 0) if net_credit else None
    else:
        # Same type (spread)
        if type_short == 'P':  # PUT spread
            if short_leg['strike'] > long_leg['strike']:  # short higher = put spread
                max_loss = (short_leg['strike'] - long_leg['strike']) - (net_credit or 0) if net_credit else None
                max_profit = net_credit
                breakeven = short_leg['strike'] - (net_credit or 0) if net_credit else None
            else:
                max_loss = None
                max_profit = None
                breakeven = None
        else:  # CALL spread
            if short_leg['strike'] < long_leg['strike']:  # short lower = call spread
                max_loss = (long_leg['strike'] - short_leg['strike']) - (net_credit or 0) if net_credit else None
                max_profit = net_credit
                breakeven = short_leg['strike'] + (net_credit or 0) if net_credit else None
            else:
                max_loss = None
                max_profit = None
                breakeven = None
    
    stats = {
        'netDelta': round(net_delta, 4),
        'netTheta': round((short_leg['theta'] or 0) + (long_leg['theta'] or 0), 4),
        'shortPremium': short_premium,
        'longCost': long_cost,
        'netCredit': round(net_credit, 2) if net_credit else None,
        'maxProfit': round(max_profit, 2) if max_profit else None,
        'maxLoss': round(max_loss, 2) if max_loss else None,
        'breakeven': round(breakeven, 2) if breakeven else None,
        'daysToExpiry': None  # Could calculate if needed
    }
    
    return short_leg, long_leg, stats


def main():
    args = parse_args()
    
    try:
        from ib_insync import IB
    except Exception as e:
        print(json.dumps({'success': False, 'error': f'ib_insync not available: {e}'}))
        sys.exit(2)
    
    ib = IB()
    try:
        ib.connect(args.host, args.port, clientId=args.clientId, readonly=True)
        print(f"Connected to TWS on port {args.port}", file=sys.stderr)
    except Exception as e:
        print(json.dumps({'success': False, 'error': f'Cannot connect to TWS: {e}'}))
        sys.exit(3)
    
    # Request delayed data if available
    ib.reqMarketDataType(3)
    
    # Find spread
    short_leg, long_leg, stats = find_hedge_spread(
        ib, args.symbol, args.expiry_short, args.type_short, args.delta_target,
        args.expiry_long, args.type_long, args.tol
    )
    
    ib.disconnect()
    
    # Output result
    if short_leg is None:
        result = {
            'success': False,
            'error': stats  # stats contains error message in this case
        }
    else:
        result = {
            'success': True,
            'shortLeg': short_leg,
            'longLeg': long_leg,
            'stats': stats
        }
    
    # Write JSON
    with open(args.out, 'w') as f:
        json.dump(result, f, indent=2)
    
    print(json.dumps(result))
    sys.exit(0 if result['success'] else 1)


if __name__ == '__main__':
    main()
