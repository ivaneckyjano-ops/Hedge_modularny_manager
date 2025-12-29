#!/usr/bin/env python3
"""
Position Monitor - Sleduje otvorené pozície a upozorní na roll trigger

Použitie:
  python position_monitor.py --symbol SPY --short-strike 659 --short-expiry 20260102 --port 7496

Spustí sa a každých X sekúnd kontroluje deltu.
"""
import argparse
import sys
import random
import time
from datetime import datetime

def parse_args():
    p = argparse.ArgumentParser(description='Monitor pozície - sleduje deltu')
    p.add_argument('--symbol', required=True, help='Symbol (SPY, QQQ...)')
    p.add_argument('--short-strike', type=float, required=True, help='Strike short opcie')
    p.add_argument('--short-expiry', required=True, help='Expirácia short opcie (YYYYMMDD)')
    p.add_argument('--port', type=int, default=7496, help='TWS port')
    p.add_argument('--roll-trigger', type=float, default=-0.30, help='Delta pri ktorej rollovať (default -0.30)')
    p.add_argument('--interval', type=int, default=60, help='Interval kontroly v sekundách (default 60)')
    p.add_argument('--once', action='store_true', help='Skontroluj len raz a skonči')
    return p.parse_args()


def get_option_delta(ib, symbol, expiry, strike, right='P'):
    """Získa aktuálnu deltu opcie"""
    from ib_insync import Option
    
    contract = Option(symbol, expiry, strike, right, 'SMART')
    try:
        ib.qualifyContracts(contract)
        ticker = ib.reqMktData(contract, '106', snapshot=False)
        
        for _ in range(40):  # 10 sekúnd
            ib.sleep(0.25)
            mg = ticker.modelGreeks
            if mg and mg.delta is not None:
                ib.cancelMktData(contract)
                return {
                    'delta': round(mg.delta, 4),
                    'theta': round(mg.theta, 4) if mg.theta else None,
                    'gamma': round(mg.gamma, 6) if mg.gamma else None,
                    'iv': round(mg.impliedVol, 4) if mg.impliedVol else None,
                    'price': round(mg.optPrice, 2) if mg.optPrice else None
                }
        ib.cancelMktData(contract)
    except Exception as e:
        print(f"Chyba: {e}", file=sys.stderr)
    return None


def get_underlying_price(ib, symbol):
    """Získa aktuálnu cenu podkladu"""
    from ib_insync import Stock
    
    stock = Stock(symbol, 'SMART', 'USD')
    ib.qualifyContracts(stock)
    ticker = ib.reqMktData(stock, '', False, False)
    ib.sleep(2)
    price = ticker.last if ticker.last and ticker.last == ticker.last else ticker.close
    ib.cancelMktData(stock)
    return price


def main():
    args = parse_args()
    
    try:
        from ib_insync import IB
    except ImportError:
        print("Chyba: ib_insync nie je nainštalovaný")
        sys.exit(1)
    
    ib = IB()
    client_id = random.randint(1000, 9999)
    
    try:
        ib.connect('127.0.0.1', args.port, clientId=client_id, readonly=True)
        print(f"✅ Pripojené k TWS (port {args.port})")
    except Exception as e:
        print(f"❌ Nepodarilo sa pripojiť: {e}")
        sys.exit(1)
    
    ib.reqMarketDataType(4)
    
    print(f"\n📊 MONITORING: {args.symbol} {args.short_strike}P exp {args.short_expiry}")
    print(f"🔄 Roll trigger: delta >= {args.roll_trigger}")
    print(f"⏱️  Interval: {args.interval}s")
    print("-" * 50)
    
    check_count = 0
    
    try:
        while True:
            check_count += 1
            timestamp = datetime.now().strftime("%H:%M:%S")
            
            # Získaj cenu podkladu
            underlying = get_underlying_price(ib, args.symbol)
            
            # Získaj greeks opcie
            data = get_option_delta(ib, args.symbol, args.short_expiry, args.short_strike, 'P')
            
            if data:
                delta = data['delta']
                theta = data['theta']
                price = data['price']
                
                # Určí status (pre PUT: delta je záporná, -0.30 je horšie ako -0.10)
                # Trigger: abs(delta) >= abs(roll_trigger)
                if abs(delta) >= abs(args.roll_trigger):
                    status = "🚨 ROLL NOW!"
                    alert = True
                elif abs(delta) >= abs(args.roll_trigger) - 0.05:  # 5% pred triggerom
                    status = "⚠️  Blízko triggeru"
                    alert = False
                else:
                    status = "✅ OK"
                    alert = False
                
                print(f"[{timestamp}] #{check_count} | {args.symbol}: ${underlying:.2f} | "
                      f"Delta: {delta:.3f} | Theta: {theta} | Price: ${price} | {status}")
                
                if alert:
                    # Tu by mohlo byť poslanie notifikácie (email, telegram, zvuk...)
                    print("\n" + "!" * 50)
                    print("!!! ROLL TRIGGER DOSIAHNUTÝ !!!")
                    print(f"!!! |Delta| {abs(delta):.3f} >= {abs(args.roll_trigger)}")
                    print("!!! Zvážte rollovanie pozície!")
                    print("!" * 50 + "\n")
            else:
                print(f"[{timestamp}] #{check_count} | Nepodarilo sa získať dáta")
            
            if args.once:
                break
            
            time.sleep(args.interval)
            
    except KeyboardInterrupt:
        print("\n\n🛑 Monitoring ukončený používateľom")
    finally:
        ib.disconnect()
        print("Odpojené od TWS")


if __name__ == '__main__':
    main()
