#!/usr/bin/env python3
import argparse
import sys
import json
import os
import math
import random
import time
from pathlib import Path

# Pridanie cesty k venv knižniciam
BASE_DIR = Path(__file__).resolve().parents[1]
venv_site = BASE_DIR / 'venv' / 'lib' / 'python3.12' / 'site-packages'
if venv_site.exists():
    sys.path.insert(0, str(venv_site))

from ib_insync import IB, Option, Bag, ComboLeg, MarketOrder, LimitOrder

def main():
    parser = argparse.ArgumentParser(description='Place orders in TWS (Single or Combo)')
    parser.add_argument('--symbol', required=True)
    parser.add_argument('--expiry', required=True)
    parser.add_argument('--call-strike', type=float, help='Strike for Call leg')
    parser.add_argument('--put-strike', type=float, help='Strike for Put leg')
    parser.add_argument('--action', choices=['BUY', 'SELL'], default='BUY', help='Action for the order')
    parser.add_argument('--qty', type=int, default=1, help='Quantity')
    parser.add_argument('--port', type=int, default=7497)
    parser.add_argument('--live', action='store_true', help='Enable real orders')
    
    # Pre kompatibilitu so starým volaním v tab_gamma_scalper.py
    parser.add_argument('--quantity', type=int, help='Quantity (alias for --qty)')

    args = parser.parse_args()
    
    # Handle qty alias
    quantity = args.qty
    if args.quantity is not None:
        quantity = args.quantity

    # Bezpečnostná poistka
    if not args.live and args.port != 7497:
        print(json.dumps({'success': False, 'error': 'Bezpečnostná poistka: Pre porty iné ako 7497 (LIVE) musíte použiť --live.'}))
        sys.exit(1)

    ib = IB()
    try:
        client_id = random.randint(140, 199)
        ib.connect('127.0.0.1', args.port, clientId=client_id, timeout=15)
        
        contract = None
        mode = "Unknown"

        # 1. Rozhodnutie o type kontraktu
        if args.call_strike is not None and args.put_strike is not None:
            # STRANGLE COMBO (Dve nohy)
            mode = "Combo"
            c_leg = Option(args.symbol, args.expiry, args.call_strike, 'C', 'SMART', currency='USD')
            p_leg = Option(args.symbol, args.expiry, args.put_strike, 'P', 'SMART', currency='USD')
            
            qualified = ib.qualifyContracts(c_leg, p_leg)
            if len(qualified) < 2:
                print(json.dumps({'success': False, 'error': f'Nepodarilo sa overiť opčné kontrakty pre {args.symbol} {args.expiry}.'}))
                return

            legs = [
                ComboLeg(conId=c_leg.conId, ratio=1, action=args.action, exchange='SMART'),
                ComboLeg(conId=p_leg.conId, ratio=1, action=args.action, exchange='SMART')
            ]
            contract = Bag(symbol=args.symbol, exchange='SMART', currency='USD', comboLegs=legs)
            ib.qualifyContracts(contract)
            
        elif args.call_strike is not None:
            # SINGLE CALL
            mode = "Call"
            contract = Option(args.symbol, args.expiry, args.call_strike, 'C', 'SMART', currency='USD')
            ib.qualifyContracts(contract)
            
        elif args.put_strike is not None:
            # SINGLE PUT
            mode = "Put"
            contract = Option(args.symbol, args.expiry, args.put_strike, 'P', 'SMART', currency='USD')
            ib.qualifyContracts(contract)
        
        if not contract:
            print(json.dumps({'success': False, 'error': 'Musíte zadať aspoň jeden strike (--call-strike alebo --put-strike).'}))
            return

        # 2. Získanie ceny pre Limit Order
        price = 0.0
        source = "None"
        ticker = ib.reqMktData(contract, '106', False, False)
        
        start = time.time()
        while time.time() - start < 4:
            ib.sleep(0.2)
            # Pre BUY chceme Ask, pre SELL chceme Bid
            if args.action == 'BUY':
                if ticker.ask > 0 and not math.isnan(ticker.ask): price = ticker.ask; source="Ask"; break
            else:
                if ticker.bid > 0 and not math.isnan(ticker.bid): price = ticker.bid; source="Bid"; break
            
            if ticker.last > 0 and not math.isnan(ticker.last): price = ticker.last; source="Last"; break
            if ticker.close > 0 and not math.isnan(ticker.close): price = ticker.close; source="Close"; break
            if ticker.modelGreeks and ticker.modelGreeks.optPrice > 0: price = ticker.modelGreeks.optPrice; source="Model"; break
        
        ib.cancelMktData(contract)

        # 3. Vytvorenie objednávky
        if price > 0:
            # Buffer pre Limit: BUY (+5%), SELL (-5%)
            limit_price = round(price * 1.05, 2) if args.action == 'BUY' else round(price * 0.95, 2)
            order = LimitOrder(args.action, quantity, limit_price)
            order_type_msg = f"Limit Order @ {limit_price} (Ref: {price:.2f} {source})"
        else:
            order = MarketOrder(args.action, quantity)
            order_type_msg = "Market Order (No Price Found)"
        
        order.orderRef = 'HedgeManager'
        order.transmit = True 
        order.outsideRth = True

        trade = ib.placeOrder(contract, order)
        
        # Sledovanie stavu
        for _ in range(10):
            ib.sleep(0.5)
            if trade.orderStatus.status in ('Submitted', 'PreSubmitted', 'Filled'): break
            if trade.orderStatus.status in ('Cancelled', 'Inactive', 'Rejected'): break

        if trade.orderStatus.status in ('Cancelled', 'Inactive', 'Rejected'):
             reason = "Neznámy dôvod"
             if trade.log:
                 for entry in reversed(trade.log):
                     if entry.message: reason = entry.message; break
             
             print(json.dumps({'success': False, 'error': f'TWS Error: {trade.orderStatus.status} - {reason}'}))
             return

        print(json.dumps({
            'success': True,
            'symbol': args.symbol,
            'mode': mode,
            'action': args.action,
            'qty': quantity,
            'orderId': trade.order.orderId,
            'status': trade.orderStatus.status,
            'msg': f'{mode} {args.action} ({order_type_msg}) bolo odoslané do TWS.'
        }))
        
    except Exception as e:
        print(json.dumps({'success': False, 'error': str(e)}))
    finally:
        if ib.isConnected(): ib.disconnect()

if __name__ == "__main__":
    main()
