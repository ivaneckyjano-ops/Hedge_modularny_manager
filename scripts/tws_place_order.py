#!/usr/bin/env python3
import argparse
import sys
import json
from ib_insync import IB, Option, MarketOrder

def main():
    parser = argparse.ArgumentParser(description='Place Strangle order in TWS')
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
        
        # Define contracts
        call_contract = Option(args.symbol, args.expiry, args.call_strike, 'C', 'SMART')
        put_contract = Option(args.symbol, args.expiry, args.put_strike, 'P', 'SMART')
        
        ib.qualifyContracts(call_contract, put_contract)
        
        # Place orders
        call_order = MarketOrder('BUY', args.quantity)
        put_order = MarketOrder('BUY', args.quantity)
        
        call_trade = ib.placeOrder(call_contract, call_order)
        put_trade = ib.placeOrder(put_contract, put_order)
        
        # Small wait for status
        ib.sleep(1)
        
        print(json.dumps({
            'success': True, 
            'call_order_id': call_trade.order.orderId,
            'put_order_id': put_trade.order.orderId,
            'status': 'Orders placed'
        }))
        
    except Exception as e:
        print(json.dumps({'success': False, 'error': str(e)}))
    finally:
        ib.disconnect()

if __name__ == "__main__":
    main()

