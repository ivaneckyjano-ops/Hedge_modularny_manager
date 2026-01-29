#!/usr/bin/env python3
import argparse
import sys
import json
import os
from pathlib import Path

# Pridanie cesty k venv knižniciam
BASE_DIR = Path(__file__).resolve().parents[1]
venv_site = BASE_DIR / 'venv' / 'lib' / 'python3.12' / 'site-packages'
if venv_site.exists():
    sys.path.insert(0, str(venv_site))

from ib_insync import IB, Stock, MarketOrder

def main():
    parser = argparse.ArgumentParser(description='Rebalance Delta using stocks (Automated)')
    parser.add_argument('--symbol', required=True)
    parser.add_argument('--quantity', type=int, required=True, help='Number of shares to trade (+ for BUY, - for SELL)')
    parser.add_argument('--port', type=int, default=7497)
    parser.add_argument('--live', action='store_true', help='Povoliť reálne obchody (vypne bezpečnostnú poistku)')
    
    args = parser.parse_args()

    # Bezpečnostná poistka: Ak nie je --live a port nie je 7497 (paper), zablokuj to.
    if not args.live and args.port != 7497:
        print(json.dumps({'success': False, 'error': f'Bezpečnostná poistka: Pre port {args.port} (LIVE) musíte pridať flag --live.'}))
        sys.exit(1)

    if args.quantity == 0:
        print(json.dumps({'success': True, 'msg': 'No rebalance needed.'}))
        return

    ib = IB()
    try:
        #clientId 130 je pevný, zmeníme ho na náhodný pre istotu
        client_id = random.randint(100, 139)
        ib.connect('127.0.0.1', args.port, clientId=client_id, timeout=15)
        ib.reqMarketDataType(3)
        ib.reqMarketDataType(4)
        
        # --- KONTROLA EXISTUJÚCICH OBJEDNÁVOK ---
        open_trades = ib.trades()
        for t in open_trades:
            if t.contract.symbol == args.symbol and not t.isDone() and t.contract.secType == 'STK':
                print(json.dumps({
                    'success': False, 
                    'error': f'Objednávka pre {args.symbol} už v TWS existuje (Status: {t.orderStatus.status}). Čakám na vybavenie.',
                    'already_exists': True
                }))
                return

        contract = Stock(args.symbol, 'SMART', 'USD')
        qualified = ib.qualifyContracts(contract)
        if not qualified:
            print(json.dumps({'success': False, 'error': f'Nepodarilo sa overiť akciu {args.symbol}.'}))
            sys.exit(1)
        
        action = 'BUY' if args.quantity > 0 else 'SELL'
        abs_qty = abs(args.quantity)
        
        order = MarketOrder(action, abs_qty, outsideRth=True)
        order.orderRef = 'HedgeManager'
        trade = ib.placeOrder(contract, order)
        
        # Čakáme na vyplnenie (max 10 sekúnd), aby sme mali cenu a komisie
        fill_price = 0.0
        total_commission = 0.0
        for _ in range(20):
            ib.sleep(0.5)
            if trade.orderStatus.status == 'Filled':
                fill_price = trade.orderStatus.avgFillPrice
                total_commission = sum(f.commissionReport.commission for f in trade.fills if f.commissionReport)
                break
            if trade.orderStatus.status in ('Cancelled', 'Inactive', 'Rejected'):
                break
        
        if trade.orderStatus.status in ('Cancelled', 'Inactive', 'Rejected'):
             reason = "Neznámy dôvod"
             if trade.log:
                 for entry in reversed(trade.log):
                     if entry.message: reason = entry.message; break
             print(json.dumps({'success': False, 'error': f'TWS Error: {trade.orderStatus.status} - {reason}'}))
             sys.exit(1)

        # Ak sa nevyplnilo, skúsime získať aktuálnu cenu
        if fill_price == 0.0:
            ticker = ib.reqMktData(contract, '', False, False)
            ib.sleep(1.0)
            fill_price = ticker.last if ticker.last else (ticker.close if ticker.close else 0.0)
            ib.cancelMktData(contract)
        
        if total_commission == 0.0 and args.port != 7497:
             total_commission = 1.0 # Minimálny odhad pre Live

        print(json.dumps({
            'success': True, 
            'action': action,
            'quantity': abs_qty,
            'symbol': args.symbol,
            'status': trade.orderStatus.status,
            'avgPrice': fill_price,
            'commission': total_commission
        }))
        
    except Exception as e:
        print(json.dumps({'success': False, 'error': str(e)}))
        sys.exit(1)
    finally:
        if ib.isConnected(): ib.disconnect()

if __name__ == "__main__":
    main()
