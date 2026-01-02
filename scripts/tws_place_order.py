#!/usr/bin/env python3
import argparse
import sys
import json
from ib_insync import IB, Option, MarketOrder, Contract

def main():
    parser = argparse.ArgumentParser(description='Place Strangle order in TWS as Combo')
    parser.add_argument('--symbol', required=True)
    parser.add_argument('--expiry', required=True)
    parser.add_argument('--call-strike', type=float, required=True)
    parser.add_argument('--put-strike', type=float, required=True)
    parser.add_argument('--quantity', type=int, default=1)
    parser.add_argument('--port', type=int, default=7497)
    parser.add_argument('--paper-only', action='store_true', help='Only allow orders on paper port 7497')
    
    args = parser.parse_args()

    # Safety check
    if args.paper_only and args.port != 7497:
        print(json.dumps({'success': False, 'error': f'Safety block: Order rejected because port {args.port} is NOT paper port 7497.'}))
        sys.exit(1)

    ib = IB()
    try:
        ib.connect('127.0.0.1', args.port, clientId=120)
        
        # 1. Definujeme jednotlivé nohy (Legs)
        call_leg = Option(args.symbol, args.expiry, args.call_strike, 'C', 'SMART')
        put_leg = Option(args.symbol, args.expiry, args.put_strike, 'P', 'SMART')
        
        # Kvalifikácia kontraktov (získanie conId)
        qualified = ib.qualifyContracts(call_leg, put_leg)
        if len(qualified) < 2:
            print(json.dumps({'success': False, 'error': 'Failed to qualify option contracts.'}))
            return

        # 2. Vytvoríme Combo kontrakt (BAG)
        from ib_insync import ComboLeg
        
        combo = Contract()
        combo.symbol = args.symbol
        combo.secType = 'BAG'
        combo.currency = 'USD'
        combo.exchange = 'SMART'
        
        leg1 = ComboLeg()
        leg1.conId = call_leg.conId
        leg1.ratio = 1
        leg1.action = 'BUY'
        leg1.exchange = 'SMART'
        
        leg2 = ComboLeg()
        leg2.conId = put_leg.conId
        leg2.ratio = 1
        leg2.action = 'BUY'
        leg2.exchange = 'SMART'
        
        combo.comboLegs = [leg1, leg2]
        
        # 3. Odoslanie Combo objednávky
        order = MarketOrder('BUY', args.quantity)
        trade = ib.placeOrder(combo, order)
        
        # Malý počkať na potvrdenie
        ib.sleep(1)
        
        print(json.dumps({
            'success': True, 
            'order_id': trade.order.orderId,
            'description': f'Strangle Combo ({args.call_strike}C + {args.put_strike}P) placed',
            'status': trade.orderStatus.status
        }))
        
    except Exception as e:
        print(json.dumps({'success': False, 'error': str(e)}))
    finally:
        ib.disconnect()

if __name__ == "__main__":
    main()

