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
    parser = argparse.ArgumentParser(description='Place a Strangle Combo order in TWS')
    parser.add_argument('--symbol', required=True)
    parser.add_argument('--expiry', required=True)
    parser.add_argument('--call-strike', type=float, required=True)
    parser.add_argument('--put-strike', type=float, required=True)
    parser.add_argument('--quantity', type=int, default=1)
    parser.add_argument('--port', type=int, default=7497)
    parser.add_argument('--live', action='store_true', help='Enable real orders')
    
    args = parser.parse_args()

    # Bezpečnostná poistka
    if not args.live and args.port != 7497:
        print(json.dumps({'success': False, 'error': 'Bezpečnostná poistka: Pre porty iné ako 7497 (LIVE) musíte použiť --live.'}))
        sys.exit(1)

    ib = IB()
    try:
        client_id = random.randint(140, 199)
        ib.connect('127.0.0.1', args.port, clientId=client_id, timeout=15)
        
        # 1. Definícia opčných nôh
        c_leg = Option(args.symbol, args.expiry, args.call_strike, 'C', 'SMART', currency='USD')
        p_leg = Option(args.symbol, args.expiry, args.put_strike, 'P', 'SMART', currency='USD')
        
        # Kvalifikácia kontraktov (získanie conId)
        qualified = ib.qualifyContracts(c_leg, p_leg)
        if len(qualified) < 2:
            print(json.dumps({
                'success': False, 
                'error': f'Nepodarilo sa overiť opčné kontrakty pre {args.symbol} {args.expiry}. Striky {args.call_strike}/{args.put_strike} možno neexistujú.'
            }))
            return

        # 2. Vytvorenie Combo (Bag) kontraktu
        legs = [
            ComboLeg(conId=c_leg.conId, ratio=1, action='BUY', exchange='SMART'),
            ComboLeg(conId=p_leg.conId, ratio=1, action='BUY', exchange='SMART')
        ]
        
        strangle_contract = Bag(
            symbol=args.symbol,
            exchange='SMART',
            currency='USD',
            comboLegs=legs
        )
        
        # Kvalifikácia Combo kontraktu
        qualified_bag = ib.qualifyContracts(strangle_contract)
        
        fallback_mode = False
        if not qualified_bag:
             print(f"DEBUG: Combo kvalifikácia zlyhala pre {args.symbol}. Skúšam zadať ako samostatné nohy.", file=sys.stderr)
             fallback_mode = True
        
        # 3. Získanie ceny
        price = 0.0
        source = "None"
        
        if not fallback_mode:
            # Pôvodná logika pre Combo
            t_combo = ib.reqMktData(strangle_contract, '106', False, False)
            start = time.time()
            while time.time() - start < 4:
                ib.sleep(0.2)
                if t_combo.ask > 0 and not math.isnan(t_combo.ask): price = t_combo.ask; source="Combo Ask"; break
                if t_combo.last > 0 and not math.isnan(t_combo.last): price = t_combo.last; source="Combo Last"; break
                if t_combo.close > 0 and not math.isnan(t_combo.close): price = t_combo.close; source="Combo Close"; break
                if t_combo.modelGreeks and t_combo.modelGreeks.optPrice > 0:
                    price = t_combo.modelGreeks.optPrice; source="Combo Model"; break
        
        # Ak combo zlyhalo alebo sme v fallback móde, musíme získať ceny pre nohy
        p_c = 0.0
        p_p = 0.0
        
        if price <= 0 or fallback_mode:
            t_c = ib.reqMktData(c_leg, '106', False, False)
            t_p = ib.reqMktData(p_leg, '106', False, False)
            
            # Čakáme na dáta
            start = time.time()
            while time.time() - start < 4:
                ib.sleep(0.2)
                # Call
                if p_c <= 0:
                    if t_c.ask > 0 and not math.isnan(t_c.ask): p_c = t_c.ask
                    elif t_c.last > 0 and not math.isnan(t_c.last): p_c = t_c.last
                    elif t_c.close > 0 and not math.isnan(t_c.close): p_c = t_c.close
                    elif t_c.modelGreeks and t_c.modelGreeks.optPrice > 0: p_c = t_c.modelGreeks.optPrice
                # Put
                if p_p <= 0:
                    if t_p.ask > 0 and not math.isnan(t_p.ask): p_p = t_p.ask
                    elif t_p.last > 0 and not math.isnan(t_p.last): p_p = t_p.last
                    elif t_p.close > 0 and not math.isnan(t_p.close): p_p = t_p.close
                    elif t_p.modelGreeks and t_p.modelGreeks.optPrice > 0: p_p = t_p.modelGreeks.optPrice
                
                if p_c > 0 and p_p > 0: break
            
            if p_c > 0 and p_p > 0:
                price = p_c + p_p
                if not fallback_mode: source = "Sum of Legs"

        if fallback_mode:
            # FALLBACK: Odoslanie dvoch samostatných príkazov
            orders_info = []
            
            # Call Leg
            lmt_c = round(p_c * 1.05, 2) if p_c > 0 else 0.0
            ord_c = LimitOrder('BUY', args.quantity, lmt_c) if lmt_c > 0 else MarketOrder('BUY', args.quantity)
            ord_c.transmit = True # Poslať hneď
            ord_c.outsideRth = True
            
            trade_c = ib.placeOrder(c_leg, ord_c)
            orders_info.append(f"Call {lmt_c:.2f}")
            
            # Put Leg
            lmt_p = round(p_p * 1.05, 2) if p_p > 0 else 0.0
            ord_p = LimitOrder('BUY', args.quantity, lmt_p) if lmt_p > 0 else MarketOrder('BUY', args.quantity)
            ord_p.transmit = True
            ord_p.outsideRth = True
            
            trade_p = ib.placeOrder(p_leg, ord_p)
            orders_info.append(f"Put {lmt_p:.2f}")
            
            # Počkáme chvíľu na potvrdenie
            ib.sleep(1.0)
            
            print(json.dumps({
                'success': True,
                'symbol': args.symbol,
                'expiry': args.expiry,
                'strikes': {'call': args.call_strike, 'put': args.put_strike},
                'orderId': f"{trade_c.order.orderId}, {trade_p.order.orderId}",
                'status': "Sent (Fallback)",
                'msg': f'Odoslané ako 2 samostatné príkazy (Combo zlyhalo). Ceny: {", ".join(orders_info)}'
            }))
            return

        # 4. Place Order (Standard Combo)
        if price > 0:
            limit_price = round(price * 1.05, 2) # +5% buffer
            order = LimitOrder('BUY', args.quantity, limit_price)
            order_type_msg = f"Limit Order @ {limit_price} (Ref: {price:.2f} {source})"
        else:
            # Ak nemáme cenu, skúsime MarketOrder ale s poistkou
            order = MarketOrder('BUY', args.quantity)
            order_type_msg = "Market Order (No Price Found)"
        
        # Pridáme dôležité parametre
        order.orderRef = 'GammaScalper'
        order.transmit = True 
        order.outsideRth = True

        trade = ib.placeOrder(strangle_contract, order)
        
        # Sledovanie stavu (pár sekúnd)
        for _ in range(10):
            ib.sleep(0.5)
            if trade.orderStatus.status in ('Submitted', 'PreSubmitted', 'Filled'):
                break
            if trade.orderStatus.status in ('Cancelled', 'Inactive', 'Rejected'):
                break

        if trade.orderStatus.status in ('Cancelled', 'Inactive', 'Rejected'):
             # Skúsime získať dôvod z logu trade
             reason = "Neznámy dôvod"
             if trade.log:
                 # Zoberieme poslednú správu z logu, ktorá obsahuje chybu
                 for entry in reversed(trade.log):
                     if entry.message:
                         reason = entry.message
                         break
             
             print(json.dumps({
                'success': False, 
                'error': f'Objednávka bola zamietnutá alebo zrušená v TWS. Status: {trade.orderStatus.status}\nDôvod: {reason}'
            }))
             return

        print(json.dumps({
            'success': True,
            'symbol': args.symbol,
            'expiry': args.expiry,
            'strikes': {'call': args.call_strike, 'put': args.put_strike},
            'orderId': trade.order.orderId,
            'status': trade.orderStatus.status,
            'msg': f'Strangle combo ({order_type_msg}) bolo odoslané do TWS (Status: {trade.orderStatus.status}).'
        }))
        
    except Exception as e:
        print(json.dumps({'success': False, 'error': str(e)}))
    finally:
        if ib.isConnected():
            ib.disconnect()

if __name__ == "__main__":
    main()
