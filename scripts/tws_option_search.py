#!/usr/bin/env python3
"""
TWS Option Search - nájde najbližšie ATM opcie a vráti Greeks.
"""
import argparse
import csv
import json
import sys

def main():
    parser = argparse.ArgumentParser(description='Vyhľadaj opcie a získaj Greeks')
    parser.add_argument('--symbol', required=True, help='Symbol podkladu (napr. SPY)')
    parser.add_argument('--expiry', required=True, help='Dátum expirácie YYYYMMDD')
    parser.add_argument('--target', type=float, default=None, help='Target delta (voliteľné)')
    parser.add_argument('--tol', type=float, default=0.02, help='Tolerance pre delta (ak je --target zadané)')
    parser.add_argument('--right', choices=['C', 'P', 'both'], default='both', help='Ktorý typ opcií hľadať (C/P/both)')
    parser.add_argument('--limit', type=int, default=50, help='Max výsledkov pri vyhľadávaní podľa target')
    parser.add_argument('--port', type=int, default=7496, help='TWS port (default 7496 pre Live)')
    parser.add_argument('--out', default='/tmp/options_results.csv', help='Výstupný CSV súbor')
    args = parser.parse_args()

    from ib_insync import IB, Stock, Option

    ib = IB()
    try:
        ib.connect('127.0.0.1', args.port, clientId=50, readonly=True)
        print(f"Pripojený k TWS na porte {args.port}", file=sys.stderr)
    except Exception as e:
        print(f"ERROR: cannot connect to TWS: {e}", file=sys.stderr)
        sys.exit(2)

    # DÔLEŽITÉ: Požiadaj o delayed data ak live nie je dostupné
    # MarketDataType: 1=Live, 2=Frozen, 3=Delayed, 4=Delayed Frozen
    ib.reqMarketDataType(3)
    print("Nastavený Market Data Type: Delayed (3)", file=sys.stderr)

    # 1. Zisti cenu podkladu
    stock = Stock(args.symbol, 'SMART', 'USD')
    ib.qualifyContracts(stock)
    
    ticker = ib.reqMktData(stock, '', False, False)
    ib.sleep(2)
    
    price = ticker.marketPrice()
    if price != price:  # NaN check
        price = getattr(ticker, 'close', None)
    # Ensure price is a numeric value; tests may mock ticker and return MagicMock
    if not isinstance(price, (int, float)):
        price = None
    if price is None:
        if args.target is None:
            print("ERROR: cannot get stock price", file=sys.stderr)
            ib.disconnect()
            sys.exit(3)
        else:
            print("WARNING: cannot get stock price; continuing without price (target mode)", file=sys.stderr)
    
    print(f"Cena {args.symbol}: {price}", file=sys.stderr)
    ib.cancelMktData(stock)

    # 2. Nájdi dostupné strikes pre danú expiráciu
    opt_template = Option(args.symbol, args.expiry, 0, 'C', 'SMART')
    details = ib.reqContractDetails(opt_template)
    
    if not details:
        print("ERROR: no option details found", file=sys.stderr)
        ib.disconnect()
        sys.exit(4)
    
    strikes = sorted({d.contract.strike for d in details})
    print(f"Nájdených {len(strikes)} strikes", file=sys.stderr)

    # Helper: fetch modelGreeks (or lastGreeks) for a contract
    def _fetch_mg(contract, timeout_sec=2):
        """Request market data and return modelGreeks or lastGreeks (or None)."""
        try:
            ticker = ib.reqMktData(contract, '106', False, False)
            # wait for greeks to be available
            for _ in range(int(timeout_sec / 0.2)):
                ib.sleep(0.2)
                mg = getattr(ticker, 'modelGreeks', None) or getattr(ticker, 'lastGreeks', None)
                if mg and getattr(mg, 'delta', None) is not None:
                    ib.cancelMktData(contract)
                    return mg
            ib.cancelMktData(contract)
            return None
        except Exception:
            try:
                ib.cancelMktData(contract)
            except Exception:
                pass
            return None

    results = []

    if args.target is None:
        # 3. Nájdi najbližší strike pod/nad cenou
        put_strike = max([s for s in strikes if s <= price], default=None)
        call_strike = min([s for s in strikes if s >= price], default=None)
        print(f"PUT strike: {put_strike}, CALL strike: {call_strike}", file=sys.stderr)

        # GET Greeks for each (best-effort)
        if put_strike:
            put = Option(args.symbol, args.expiry, put_strike, 'P', 'SMART')
            ib.qualifyContracts(put)
            mg = _fetch_mg(put, timeout_sec=3)
            if mg:
                results.append({
                    'symbol': args.symbol,
                    'expiry': args.expiry,
                    'right': 'P',
                    'strike': put_strike,
                    'delta': round(mg.delta, 4) if mg.delta else None,
                    'gamma': round(mg.gamma, 6) if mg.gamma else None,
                    'vega': round(mg.vega, 4) if mg.vega else None,
                    'theta': round(mg.theta, 4) if mg.theta else None,
                    'impliedVol': round(mg.impliedVol, 4) if mg.impliedVol else None
                })
            else:
                print(f"WARNING: no Greeks for PUT {put_strike}", file=sys.stderr)

        if call_strike:
            call = Option(args.symbol, args.expiry, call_strike, 'C', 'SMART')
            ib.qualifyContracts(call)
            mg = _fetch_mg(call, timeout_sec=3)
            if mg:
                results.append({
                    'symbol': args.symbol,
                    'expiry': args.expiry,
                    'right': 'C',
                    'strike': call_strike,
                    'delta': round(mg.delta, 4) if mg.delta else None,
                    'gamma': round(mg.gamma, 6) if mg.gamma else None,
                    'vega': round(mg.vega, 4) if mg.vega else None,
                    'theta': round(mg.theta, 4) if mg.theta else None,
                    'impliedVol': round(mg.impliedVol, 4) if mg.impliedVol else None
                })
            else:
                print(f"WARNING: no Greeks for CALL {call_strike}", file=sys.stderr)
    else:
        # Search for strikes whose delta is within tolerance of target
        rights = ('C', 'P') if args.right == 'both' else (args.right,)
        # Optionally limit search to strikes within ±20% of price to speed up
        if price:
            strikes = [s for s in strikes if abs(s - price) / price <= 0.2]

        for right in rights:
            for strike in strikes:
                contract = Option(args.symbol, args.expiry, strike, right, 'SMART')
                ib.qualifyContracts(contract)
                mg = _fetch_mg(contract, timeout_sec=1)
                if not mg or getattr(mg, 'delta', None) is None:
                    continue
                delta = mg.delta
                if abs(delta - args.target) <= args.tol:
                    results.append({
                        'symbol': args.symbol,
                        'expiry': args.expiry,
                        'right': right,
                        'strike': strike,
                        'delta': round(delta, 6),
                        'vega': getattr(mg, 'vega', None),
                        'theta': getattr(mg, 'theta', None)
                    })
                    if len(results) >= args.limit:
                        break
            if len(results) >= args.limit:
                break

    ib.disconnect()

    # 6. Ulož výsledky
    if results:
        with open(args.out, 'w', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=['symbol', 'expiry', 'right', 'strike', 'delta', 'gamma', 'vega', 'theta', 'impliedVol'])
            writer.writeheader()
            writer.writerows(results)
        print(json.dumps({"success": True, "file": args.out, "count": len(results)}))
    else:
        print(json.dumps({"success": False, "error": "No Greeks found"}))
        sys.exit(1)

if __name__ == '__main__':
    main()
