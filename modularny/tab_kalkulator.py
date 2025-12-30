#!/usr/bin/env python3
"""
Záložka: Spread Kalkulátor
Manuálny Spread Kalkulátor - bez nutnosti market data
"""
import tkinter as tk
from tkinter import ttk, messagebox, scrolledtext
import subprocess
import threading
import os
import sys
import math
from datetime import datetime

from modularny.utils import get_time_to_expiry_years, parse_option_fetch_output


def update_calc_status(state, text):
    """Bezpečne aktualizuje status label v kalkulátore"""
    if hasattr(state, 'calc_status_label'):
        state.calc_status_label.config(text=text)


def fetch_underlying_price(state):
    """Stiahne aktuálnu cenu podkladového aktíva"""
    def run():
        try:
            script_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'scripts', 'tws_fetch_price.py')
            result = subprocess.run(
                ['python3', script_path, str(state.port_var.get()), state.symbol_var.get()], 
                capture_output=True, text=True, timeout=20,
                cwd='/home/narbon/Aplikácie/tws-webapp'
            )
            
            output = result.stdout.strip()
            stderr = result.stderr.strip()
            
            lines = output.split('\n')
            first_line = lines[0] if lines else ''
            
            if first_line.startswith("ERROR:"):
                error_msg = first_line.replace("ERROR:", "")
                state.root.after(0, lambda msg=error_msg: update_calc_status(state, f"❌ {msg}"))
            elif result.returncode == 0 and first_line:
                try:
                    price = first_line.split('\n')[0]
                    float(price)
                    state.root.after(0, lambda p=price: state.calc_underlying_price_var.set(p))
                    state.root.after(0, lambda p=price, sym=state.symbol_var.get(): update_calc_status(state, f"✓ {sym}: ${p}"))
                    state.root.after(100, lambda: update_recommended_strike(state))
                except ValueError:
                    state.root.after(0, lambda out=first_line: update_calc_status(state, f"❌ Neplatná cena: {out}"))
            elif not output:
                state.root.after(0, lambda err=stderr[:100]: update_calc_status(state, f"❌ TWS: {err}"))
            else:
                state.root.after(0, lambda: update_calc_status(state, f"❌ Nepodarilo sa načítať cenu"))
        except subprocess.TimeoutExpired:
            state.root.after(0, lambda: update_calc_status(state, f"❌ Timeout - TWS neodpovedá"))
        except Exception as e:
            state.root.after(0, lambda err=str(e): update_calc_status(state, f"❌ {err}"))
    
    update_calc_status(state, "Sťahujem cenu z TWS...")
    threading.Thread(target=run, daemon=True).start()


def fetch_option_price(state, leg_type):
    """Stiahne cenu konkrétnej opcie"""
    if leg_type == 'short':
        strike = state.calc_short_strike_var.get()
        expiry = state.calc_short_expiry_var.get()
        premium_var = state.calc_short_premium_var
    else:
        strike = state.calc_long_strike_var.get()
        expiry = state.calc_long_expiry_var.get()
        premium_var = state.calc_long_premium_var

    if not strike or not expiry:
        messagebox.showwarning("Chyba", f"Zadajte strike a expiry")
        return

    right = 'C' if state.option_type_var.get() == 'CALL' else 'P'
    symbol = state.symbol_var.get()
    port = state.port_var.get()

    update_calc_status(state, f"Sťahujem {leg_type} {strike}...")

    def run():
        try:
            script_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'scripts', 'tws_fetch_option.py')
            print(f"DEBUG fetch_option_price: symbol={symbol}, expiry={expiry}, strike={strike}, right={right}, port={port}", file=sys.stderr)
            result = subprocess.run(
                ['python3', script_path, str(port), symbol, expiry, str(strike), right],
                capture_output=True, text=True, timeout=20,
                cwd='/home/narbon/Aplikácie/tws-webapp'
            )

            output = result.stdout.strip()
            stderr = result.stderr.strip()

            print(f"DEBUG fetch_option_price result: returncode={result.returncode}, stdout={output[:200]}, stderr={stderr[:200]}", file=sys.stderr)

            if result.returncode != 0:
                error_display = output or stderr or "TWS vrátil chybu"
                state.root.after(0, lambda err=error_display: update_calc_status(state, f"❌ {leg_type}: {err}"))
                state.root.after(0, lambda err=error_display: messagebox.showwarning("Chyba", f"Nepodarilo sa stiahnuť premium.\n\n{err}"))
                if leg_type == 'long':
                    state.root.after(0, lambda: state.calc_long_theta_var.set(''))
                return

            if not output:
                error_display = stderr[:200] if stderr else "Žiadna odpoveď z TWS"
                state.root.after(0, lambda err=error_display: update_calc_status(state, f"❌ TWS: {err}"))
                state.root.after(0, lambda err=error_display: messagebox.showwarning("Chyba",
                    f"Nepodarilo sa načítať premium.\n\n{err}\n\nSkontrolujte:\n- Pripojenie k TWS\n- Správny formát expirácie\n- Existujúcu opciu"))
                if leg_type == 'long':
                    state.root.after(0, lambda: state.calc_long_theta_var.set(''))
                return

            try:
                price, theta = parse_option_fetch_output(output)
            except ValueError as err:
                msg = str(err)
                state.root.after(0, lambda err=msg, lt=leg_type: update_calc_status(state, f"❌ {lt}: {err}"))
                if leg_type == 'long':
                    state.root.after(0, lambda: state.calc_long_theta_var.set(''))
                return

            if price > 0:
                formatted_price = f"{price:.2f}"
                state.root.after(0, lambda pvar=premium_var, val=formatted_price: pvar.set(val))
                state.root.after(0, lambda lt=leg_type, st=strike, val=formatted_price: update_calc_status(state,
                    f"✓ {lt.upper()} {st} @ ${val}"))
                if leg_type == 'short':
                    state.root.after(100, lambda: update_stoploss_label(state))
                if leg_type == 'long':
                    state.root.after(0, lambda th=theta: state.calc_long_theta_var.set(f"{th:+.4f}"))
            else:
                state.root.after(0, lambda lt=leg_type: update_calc_status(state,
                    f"❌ {lt}: Cena = 0, zadajte manuálne"))
                if leg_type == 'long':
                    state.root.after(0, lambda: state.calc_long_theta_var.set(''))

        except subprocess.TimeoutExpired:
            state.root.after(0, lambda: update_calc_status(state, f"❌ Timeout - TWS neodpovedá"))
            state.root.after(0, lambda: messagebox.showwarning("Timeout",
                "TWS neodpovedá včas.\n\nSkontrolujte pripojenie a skúste to znova."))
        except Exception as e:
            error_msg = str(e)
            print(f"DEBUG fetch_option_price exception: {error_msg}", file=sys.stderr)
            state.root.after(0, lambda err=error_msg: update_calc_status(state, f"❌ {err}"))

    threading.Thread(target=run, daemon=True).start()


def fetch_atr(state):
    """Stiahne 7-denný priemer rozsahu (high-low) cez TWS"""
    def run():
        symbol = state.symbol_var.get()
        port = int(state.port_var.get() or 7496)
        state.root.after(0, lambda: update_calc_status(state, f"Sťahujem 7d range pre {symbol}..."))
        
        try:
            script_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'scripts', 'tws_fetch_atr.py')
            result = subprocess.run(
                ['python3', script_path, str(port), symbol],
                capture_output=True, text=True, timeout=15,
                cwd='/home/narbon/Aplikácie/tws-webapp'
            )
            
            output = result.stdout.strip()
            
            if result.returncode == 0 and output and not output.startswith("ERROR:"):
                avg = float(output)
                updated = datetime.now().strftime('%Y-%m-%d %H:%M')
                state.atr_7d = avg
                state.atr_last_updated = updated
                mult = state.atr_multiplier_var.get()
                if hasattr(state, 'atr_label'):
                    state.root.after(0, lambda: state.atr_label.config(text=f"ATR14: ${avg:.2f} | {mult}x=${avg*mult:.2f}"))
                state.root.after(0, lambda: update_calc_status(state, f"✓ ATR14 ${avg:.2f} (TWS)"))
                state.root.after(100, lambda: update_recommended_strike(state))
                return
            else:
                raise RuntimeError(output if output else "TWS failed")
                
        except Exception as e:
            # Fallback to yfinance
            try:
                import yfinance as yf
                df = yf.download(symbol, period='21d', interval='1d', progress=False)
                if df is None or df.empty or len(df) < 14:
                    raise RuntimeError('Nedostatočné dáta z yfinance')
                prices = df['High'] - df['Low']
                avg = float(prices[-14:].mean())
                updated = datetime.now().strftime('%Y-%m-%d %H:%M')
                state.atr_7d = avg
                state.atr_last_updated = updated
                mult = state.atr_multiplier_var.get()
                if hasattr(state, 'atr_label'):
                    state.root.after(0, lambda: state.atr_label.config(text=f"ATR14: ${avg:.2f} | {mult}x=${avg*mult:.2f}"))
                state.root.after(0, lambda: update_calc_status(state, f"✓ ATR14 ${avg:.2f} (yfinance)"))
                state.root.after(100, lambda: update_recommended_strike(state))
            except Exception as e2:
                error_msg = str(e2)
                state.root.after(0, lambda msg=error_msg: update_calc_status(state, f"❌ ATR: {msg}"))
    
    threading.Thread(target=run, daemon=True).start()


def update_atr_display(state):
    """Aktualizuje ATR label pri zmene multipliera"""
    if hasattr(state, 'atr_7d') and state.atr_7d and state.atr_7d > 0:
        avg = state.atr_7d
        mult = state.atr_multiplier_var.get()
        if hasattr(state, 'atr_label'):
            state.atr_label.config(text=f"ATR14: ${avg:.2f} | {mult}x=${avg*mult:.2f}")
    update_recommended_strike(state)


def update_recommended_strike(state):
    """Aktualizuje odporúčaný strike pre SHORT"""
    try:
        underlying = float(state.calc_underlying_price_var.get() or 0)
        atr = getattr(state, 'atr_7d', 0) or 0
        mult = state.atr_multiplier_var.get()
        option_type = state.option_type_var.get()
        
        if underlying > 0 and atr > 0:
            if option_type == 'CALL':
                rec_strike = underlying + (atr * mult)
            else:
                rec_strike = underlying - (atr * mult)
            
            if underlying > 100:
                rec_strike = round(rec_strike)
            else:
                rec_strike = round(rec_strike, 1)
            
            if hasattr(state, 'short_rec_strike_label'):
                state.short_rec_strike_label.config(text=f"💡 Odpor.: {rec_strike}")
        else:
            if hasattr(state, 'short_rec_strike_label'):
                state.short_rec_strike_label.config(text="")
    except Exception:
        if hasattr(state, 'short_rec_strike_label'):
            state.short_rec_strike_label.config(text="")


def update_stoploss_label(state):
    """Deprecated - use calculate_stoploss_price"""
    pass


def calculate_stoploss_price(state, silent=False):
    """Vypočíta cenu SHORT opcie keď podklad dosiahne short strike"""
    try:
        short_strike = float(state.calc_short_strike_var.get() or 0)
        short_expiry = state.calc_short_expiry_var.get()
        short_premium = float(state.calc_short_premium_var.get() or 0)
        underlying = float(state.calc_underlying_price_var.get() or 0)
        iv = float(state.iv_var.get() or 0.20)
        
        if not short_strike or not short_expiry:
            if not silent:
                messagebox.showwarning("Chyba", "Zadajte short strike a expiry")
            if hasattr(state, 'stoploss_price_label'):
                state.stoploss_price_label.config(text="")
            return
        
        today = datetime.now()
        try:
            exp_date = datetime.strptime(short_expiry, '%Y%m%d')
            dte = max(1, (exp_date - today).days)
        except:
            if hasattr(state, 'stoploss_price_label'):
                state.stoploss_price_label.config(text="")
            return
        
        t_years = dte / 365.0
        atm_price = 0.4 * short_strike * iv * math.sqrt(t_years)
        
        state.calculated_stoploss = atm_price
        
        if hasattr(state, 'stoploss_price_label'):
            state.stoploss_price_label.config(
                text=f"🛑 STOPLOSS: ${atm_price:.2f} (opcia pri strike ${short_strike:.0f}, DTE {dte}, IV {iv:.0%})"
            )
        
        if not silent:
            update_calc_status(state, f"✓ Stoploss vypočítaný: ${atm_price:.2f}")
        
    except Exception as e:
        if not silent:
            messagebox.showerror("Chyba", f"Nepodarilo sa vypočítať stoploss:\n{e}")


def auto_recalc_stoploss(state):
    """Automaticky prepočíta stoploss pri zmene strike, expiry alebo IV"""
    if hasattr(state, '_stoploss_after_id'):
        state.root.after_cancel(state._stoploss_after_id)
    state._stoploss_after_id = state.root.after(300, lambda: calculate_stoploss_price(state, silent=True))


def load_expiries_for_calc(state):
    """Načíta expirácie pre kalkulátor"""
    state.load_expiries()


def update_calc_expiry_combos(state, expiries):
    """Aktualizuje combobox expiracií v kalkulátore"""
    if hasattr(state, 'calc_short_expiry_combo'):
        state.calc_short_expiry_combo['values'] = expiries
    if hasattr(state, 'calc_long_expiry_combo'):
        state.calc_long_expiry_combo['values'] = expiries


def calculate_spread(state):
    """Vypočíta parametre spreadu"""
    try:
        short_strike = float(state.calc_short_strike_var.get() or 0)
        short_premium = float(state.calc_short_premium_var.get() or 0)
        short_expiry = state.calc_short_expiry_var.get()
        
        long_strike = float(state.calc_long_strike_var.get() or 0)
        long_premium = float(state.calc_long_premium_var.get() or 0)
        long_expiry = state.calc_long_expiry_var.get()
        try:
            long_theta = float(state.calc_long_theta_var.get() or 0)
        except ValueError:
            long_theta = 0.0
        
        underlying_price = float(state.calc_underlying_price_var.get() or 0)
        
        option_type = state.option_type_var.get()
        broker = state.broker_var.get()
        
        if not all([short_strike, short_premium, underlying_price]):
            messagebox.showwarning("Chyba", "Vyplňte všetky povinné polia")
            return
        
        spread_width = abs(short_strike - long_strike) if long_strike > 0 else 0
        same_expiry = (short_expiry == long_expiry) or not long_expiry
        
        today = datetime.now()
        if short_expiry:
            short_exp_date = datetime.strptime(short_expiry, '%Y%m%d')
            short_dte = max(1, (short_exp_date - today).days)
        else:
            short_dte = 7
        
        if long_expiry:
            long_exp_date = datetime.strptime(long_expiry, '%Y%m%d')
            long_dte = max(1, (long_exp_date - today).days)
        else:
            long_dte = short_dte
        
        net_amount = short_premium - long_premium
        is_credit = net_amount > 0
        
        if long_strike == 0 or long_premium == 0:
            spread_type = f"Naked {option_type}"
            is_credit = True
            net_amount = short_premium
        elif same_expiry:
            if spread_width == 0:
                spread_type = f"Single {option_type}"
            elif is_credit:
                spread_type = f"Vertical CREDIT Spread ({option_type})"
            else:
                spread_type = f"Vertical DEBIT Spread ({option_type})"
        else:
            if spread_width == 0:
                if is_credit:
                    spread_type = f"Calendar CREDIT Spread ({option_type})"
                else:
                    spread_type = f"Calendar DEBIT Spread ({option_type})"
            else:
                if is_credit:
                    spread_type = f"Diagonal CREDIT Spread"
                else:
                    spread_type = "PMCC" if option_type == 'CALL' else "PMCP"
        
        broker_pct = 0.10 if broker == 'IBKR' else 0.15
        
        if is_credit:
            net_credit = net_amount
            max_profit = net_credit * 100
            max_loss = (spread_width - net_credit) * 100 if spread_width > 0 else float('inf')
            
            if option_type == 'PUT':
                break_even = short_strike - net_credit
            else:
                break_even = short_strike + net_credit
            
            if spread_width > 0 and same_expiry:
                margin = spread_width * 100
            elif spread_width > 0:
                margin = spread_width * 100 * 1.2
            else:
                margin = underlying_price * broker_pct * 100
            
            if margin > 0:
                total_roi = (net_credit * 100 / margin) * 100
                weekly_roi = total_roi / short_dte * 7
                annual_roi = weekly_roi * 52
            else:
                total_roi = weekly_roi = annual_roi = 0
        else:
            net_debit = abs(net_amount)
            max_loss = net_debit * 100
            
            if same_expiry and spread_width > 0:
                max_profit = (spread_width - net_debit) * 100
                additional_margin = 0
            elif spread_width == 0:
                max_profit = float('inf')
                if broker == 'IBKR':
                    additional_margin = long_premium * 100 * 0.15
                else:
                    additional_margin = 0
            else:
                max_profit = float('inf')
                if broker == 'IBKR':
                    additional_margin = max(spread_width * 100, underlying_price * 0.05 * 100)
                else:
                    additional_margin = spread_width * 100 * 1.5
            
            investment = net_debit * 100
            total_capital = investment + additional_margin
            margin = total_capital
            
            break_even = short_strike + net_debit
            
            if margin > 0:
                profit_for_roi = short_premium * 100 if not same_expiry else max_profit
                if profit_for_roi != float('inf'):
                    total_roi = (profit_for_roi / margin) * 100
                    weekly_roi = total_roi / short_dte * 7
                    annual_roi = weekly_roi * 52
                else:
                    weekly_roi = annual_roi = 0
            else:
                total_roi = weekly_roi = annual_roi = 0
        
        max_profit_str = f"${max_profit:,.2f}" if max_profit != float('inf') else "NEOBMEDZENÝ ↑"
        max_loss_str = f"${max_loss:,.2f}" if max_loss != float('inf') else "NEOBMEDZENÁ ↓"
        
        if is_credit:
            credit_debit_label = "Net CREDIT"
            credit_debit_value = f"${net_credit:.2f}"
            credit_debit_total = f"${net_credit*100:.2f}"
            roi_note = "ROI = (Credit / Margin) - zarábate na time decay"
            margin_section = f"║  💼 MARGIN ({broker}):  ${margin:,.2f}                                   ║"
        else:
            credit_debit_label = "Net DEBIT"
            credit_debit_value = f"${net_debit:.2f}"
            credit_debit_total = f"-${net_debit*100:.2f}"
            roi_note = f"ROI = (Short Premium / Celkový kapitál) × 100"
            if not same_expiry:
                if additional_margin > 0:
                    margin_section = f"""║  💼 NÁKLADY ({broker}):                                              ║
║     Investment (Net Debit):   ${investment:,.2f}                        ║
║     Dodatočný Margin:         ${additional_margin:,.2f}                        ║
║     ────────────────────────────────────                         ║
║     CELKOVÝ KAPITÁL:          ${total_capital:,.2f}                        ║"""
                else:
                    margin_section = f"""║  💼 NÁKLADY ({broker}):                                              ║
║     Investment (Net Debit):   ${investment:,.2f}                        ║
║     Dodatočný Margin:         $0.00 (long kryje short)              ║
║     ────────────────────────────────────                         ║
║     CELKOVÝ KAPITÁL:          ${total_capital:,.2f}                        ║"""
            else:
                margin_section = f"║  💼 INVESTMENT ({broker}):  ${margin:,.2f}                              ║"
        
        result = f"""
╔══════════════════════════════════════════════════════════════════╗
║                    📊 SPREAD KALKULÁCIA                          ║
╠══════════════════════════════════════════════════════════════════╣
║  Symbol: {state.symbol_var.get():10}    Typ: {option_type:6}    Broker: {broker:6}     ║
║  Cena podkladu: ${underlying_price:,.2f}                                   ║
╠══════════════════════════════════════════════════════════════════╣
║  🔴 SHORT LEG (predávate):                                       ║
║     Strike: ${short_strike:,.2f}    Premium: ${short_premium:.2f}    DTE: {short_dte:3}        ║
║     Expiry: {short_expiry or 'N/A':10}                                       ║
║                                                                  ║
║  🟢 LONG LEG (kupujete):                                         ║
║     Strike: ${long_strike:,.2f}    Premium: ${long_premium:.2f}    DTE: {long_dte:3}        ║
║     Expiry: {long_expiry or 'N/A':10}                                       ║
║     Theta: {long_theta:+.4f}                                             ║
╠══════════════════════════════════════════════════════════════════╣
║  📐 TYP SPREADU: {spread_type:45}║
║  📏 Šírka spreadu: ${spread_width:,.2f}                                    ║
╠══════════════════════════════════════════════════════════════════╣
║                      💰 VÝPOČTY                                  ║
╠══════════════════════════════════════════════════════════════════╣
║  {credit_debit_label}:     {credit_debit_value} per share ({credit_debit_total} per contract) ║
║  Max Profit:      {max_profit_str:20}                         ║
║  Max Loss:        {max_loss_str:20}                          ║
║  Break-Even:      ${break_even:,.2f}                                       ║
╠══════════════════════════════════════════════════════════════════╣
{margin_section}
╠══════════════════════════════════════════════════════════════════╣
║  📈 ROI ANALÝZA:                                                 ║
║     Total ROI:    {total_roi:6.2f}% (za {short_dte} dní)                       ║
║     Weekly ROI:   {weekly_roi:6.2f}%                                        ║
║     Annual ROI:   {annual_roi:6.2f}% (projected)                           ║
╠══════════════════════════════════════════════════════════════════╣
║  ⚠️  MANAGEMENT (Roll ak):                                       ║
║     Cena podkladu dosiahne short strike: ${short_strike:,.2f}              ║
║     ➡️  Stoploss na cenu opcie: klikni "Prepočítať" vyššie        ║
╚══════════════════════════════════════════════════════════════════╝

📝 POZNÁMKY:
• {credit_debit_label} = Short Premium (${short_premium:.2f}) - Long Premium (${long_premium:.2f})
• {roi_note}
• Hodnoty sú per 1 kontrakt (100 shares)
"""
        
        if not is_credit:
            if not same_expiry and spread_width != 0:
                result += f"""
📋 DIAGONAL DEBIT SPREAD (PMCC/PMCP):
• Net Debit (investícia): ${investment:.2f}
• Margin (short leg):     ${additional_margin:.2f}
• CELKOVÝ KAPITÁL:        ${total_capital:.2f}
• ROI = ${short_premium*100:.2f} / ${total_capital:.2f} × 100 = {total_roi:.2f}%
• Ak short exp OTM: predajte ďalší short, znížte cost basis
• Ak short ITM: roll short alebo close pozíciu
• Break-even: cena musí byť {'nad' if option_type == 'CALL' else 'pod'} ${break_even:.2f}
"""
            elif not same_expiry:
                result += f"""
📋 CALENDAR DEBIT SPREAD:
• Investícia: ${net_debit*100:.2f} (net debit)
• ROI ak short expiruje OTM: {total_roi:.2f}%
• Profitujete z time decay short leg
"""
            else:
                result += f"""
📋 VERTICAL DEBIT SPREAD:
• Investícia: ${net_debit*100:.2f} (max strata)
• Max profit: ${max_profit:.2f} ak cena je {'nad' if option_type == 'CALL' else 'pod'} ${long_strike:.2f}
• Break-even: ${break_even:.2f}
"""
        else:
            t_years = short_dte / 365.0
            iv = float(state.iv_var.get() or 0.20)
            atm_price = 0.4 * short_strike * iv * math.sqrt(t_years)
            result += f"""
📋 CREDIT SPREAD:
• Prijatý kredit: ${net_credit*100:.2f}
• Max strata: ${max_loss:.2f if max_loss != float('inf') else 'NEOBMEDZENÁ'}
• Cieľ: short leg expiruje OTM, ponecháte celý kredit

🛑 STOPLOSS (keď podklad dosiahne short strike ${short_strike:.0f}):
• Odhadovaná cena SHORT opcie pri ATM: ${atm_price:.2f}
• Nastav STOPLOSS order na opciu: BUY @ ${atm_price:.2f} (alebo market)
• IV použitá: {iv:.0%}, DTE: {short_dte}
"""
        
        try:
            if getattr(state, 'atr_7d', None) and state.atr_7d > 0:
                atr = state.atr_7d
                mult = float(state.atr_multiplier_var.get() or 1.0)
                distance = abs(short_strike - underlying_price)
                if distance <= mult * atr:
                    result += f"\n⚠️VAROVANIE: Strike je v rámci {mult:.1f}×ATR (≤ ${mult*atr:.2f}) - zvážte väčšiu vzdialenosť pre DTE-5.\n"
        except Exception:
            pass

        if hasattr(state, 'calc_result_text'):
            state.calc_result_text.delete(1.0, tk.END)
            state.calc_result_text.insert(tk.END, result)
        
        state.last_calc_result = {
            'shortStrike': short_strike,
            'shortPremium': short_premium,
            'shortExpiry': short_expiry,
            'shortDTE': short_dte,
            'longStrike': long_strike,
            'longPremium': long_premium,
            'longTheta': long_theta,
            'longExpiry': long_expiry,
            'longDTE': long_dte,
            'netCredit': net_credit if is_credit else -net_debit,
            'isCredit': is_credit,
            'margin': margin,
            'maxProfit': max_profit,
            'maxLoss': max_loss,
            'breakEven': break_even,
            'weeklyROI': weekly_roi,
            'underlyingPrice': underlying_price,
            'optionType': option_type,
            'spreadType': spread_type,
        }
        
    except ValueError as e:
        messagebox.showerror("Chyba", f"Neplatné hodnoty: {e}")
    except Exception as e:
        messagebox.showerror("Chyba", f"Chyba výpočtu: {e}")


def save_strategy(state):
    """Uloží aktuálne nastavenia kalkulátora"""
    if not hasattr(state, 'strategy_name_var'):
        return
    
    name = state.strategy_name_var.get().strip()
    if not name:
        name = messagebox.askstring("Názov stratégie", "Zadajte názov pre túto stratégiu:")
        if not name:
            return
        name = name.strip()
    
    try:
        strategy = {
            'symbol': state.symbol_var.get(),
            'option_type': state.option_type_var.get(),
            'underlying_price': state.calc_underlying_price_var.get(),
            'short_strike': state.calc_short_strike_var.get(),
            'short_expiry': state.calc_short_expiry_var.get(),
            'short_premium': state.calc_short_premium_var.get(),
            'long_strike': state.calc_long_strike_var.get(),
            'long_expiry': state.calc_long_expiry_var.get(),
            'long_premium': state.calc_long_premium_var.get(),
            'long_theta': state.calc_long_theta_var.get(),
            'broker': state.broker_var.get(),
            'saved_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        }
        
        state.saved_strategies[name] = strategy
        state.strategy_name_var.set(name)
        
        if hasattr(state, 'strategy_combo'):
            strategy_names = sorted(state.saved_strategies.keys())
            state.strategy_combo['values'] = strategy_names
        
        if hasattr(state, 'archive_listbox'):
            from modularny.tab_archiv import archive_refresh_list
            archive_refresh_list(state)
        
        state.save_settings_file()
        update_calc_status(state, f"✓ Stratégia '{name}' uložená")
        messagebox.showinfo("Úspech", f"Stratégia '{name}' bola uložená.\n\nCelkom stratégií: {len(state.saved_strategies)}")
        
    except Exception as e:
        messagebox.showerror("Chyba", f"Nepodarilo sa uložiť stratégiu:\n{e}")


def load_strategy(state, auto=False):
    """Načíta vybranú stratégiu do kalkulátora"""
    if not hasattr(state, 'strategy_name_var'):
        return
    
    name = state.strategy_name_var.get().strip()
    if not name:
        messagebox.showwarning("Chyba", "Vyberte stratégiu zo zoznamu")
        return
    
    if name not in state.saved_strategies:
        messagebox.showerror("Chyba", f"Stratégia '{name}' neexistuje")
        return
    
    try:
        strategy = state.saved_strategies[name]
        
        state.symbol_var.set(strategy.get('symbol', 'SPY'))
        state.option_type_var.set(strategy.get('option_type', 'CALL'))
        state.calc_underlying_price_var.set(strategy.get('underlying_price', ''))
        state.calc_short_strike_var.set(strategy.get('short_strike', ''))
        state.calc_short_expiry_var.set(strategy.get('short_expiry', ''))
        state.calc_short_premium_var.set(strategy.get('short_premium', ''))
        state.calc_long_strike_var.set(strategy.get('long_strike', ''))
        state.calc_long_expiry_var.set(strategy.get('long_expiry', ''))
        state.calc_long_premium_var.set(strategy.get('long_premium', ''))
        state.calc_long_theta_var.set(strategy.get('long_theta', ''))
        state.broker_var.set(strategy.get('broker', 'IBKR'))
        
        state.save_settings_file()
        
        if not auto:
            saved_at = strategy.get('saved_at', 'Neznámy dátum')
            update_calc_status(state, f"✓ Načítaná stratégia '{name}'")
            messagebox.showinfo("Načítané", f"Stratégia '{name}' bola načítaná.\n\nUložená: {saved_at}")
        else:
            update_calc_status(state, f"✓ Auto-načítaná '{name}'")
            
    except Exception as e:
        messagebox.showerror("Chyba", f"Nepodarilo sa načítať stratégiu:\n{e}")


def delete_strategy(state):
    """Vyčistí polia kalkulátora"""
    if not hasattr(state, 'strategy_name_var'):
        return
    
    state.strategy_name_var.set('')
    state.calc_underlying_price_var.set('')
    state.calc_short_strike_var.set('')
    state.calc_short_expiry_var.set('')
    state.calc_short_premium_var.set('')
    state.calc_long_strike_var.set('')
    state.calc_long_expiry_var.set('')
    state.calc_long_premium_var.set('')
    state.calc_long_theta_var.set('')
    
    if hasattr(state, 'calc_result_text'):
        state.calc_result_text.config(state='normal')
        state.calc_result_text.delete(1.0, tk.END)
        state.calc_result_text.config(state='disabled')
    
    update_calc_status(state, "Kalkulátor vyčistený")


def create_spread_calculator_tab(parent, state):
    """Záložka pre manuálny Spread Kalkulátor"""
    
    # === ARCHÍV NASTAVENÍ ===
    archive_frame = ttk.LabelFrame(parent, text="💾 Archív Nastavení", padding=5)
    archive_frame.pack(fill='x', padx=10, pady=5)
    
    archive_row = ttk.Frame(archive_frame)
    archive_row.pack(fill='x', padx=5, pady=5)
    
    ttk.Label(archive_row, text="Stratégia:").pack(side='left', padx=5)
    strategy_name_var = tk.StringVar()
    state.strategy_name_var = strategy_name_var
    strategy_combo = ttk.Combobox(archive_row, textvariable=strategy_name_var, width=35)
    strategy_combo.pack(side='left', padx=5)
    state.strategy_combo = strategy_combo
    
    ttk.Button(archive_row, text="💾 Uložiť", command=lambda: save_strategy(state), width=10).pack(side='left', padx=2)
    ttk.Button(archive_row, text="📂 Načítať", command=lambda: load_strategy(state), width=10).pack(side='left', padx=2)
    ttk.Button(archive_row, text="🧹 Vyčistiť", command=lambda: delete_strategy(state), width=10).pack(side='left', padx=2)
    
    # Načítaj uložené stratégie
    state.load_settings_file()
    if state.saved_strategies:
        strategy_names = sorted(state.saved_strategies.keys())
        strategy_combo['values'] = strategy_names
    
    # === Vstupné parametre ===
    input_frame = ttk.LabelFrame(parent, text="📝 Zadajte parametre spreadu", padding=10)
    input_frame.pack(fill='x', padx=10, pady=10)
    
    # Riadok 0: Symbol, Typ, Underlying Price
    row0 = ttk.Frame(input_frame)
    row0.pack(fill='x', pady=5)
    
    ttk.Label(row0, text="Symbol:").pack(side='left', padx=5)
    ttk.Entry(row0, textvariable=state.symbol_var, width=10).pack(side='left', padx=5)
    
    ttk.Label(row0, text="Typ:").pack(side='left', padx=5)
    ttk.Combobox(row0, textvariable=state.option_type_var, values=["PUT", "CALL"], width=6).pack(side='left', padx=5)
    
    ttk.Label(row0, text="Cena podkladu $:").pack(side='left', padx=5)
    ttk.Entry(row0, textvariable=state.calc_underlying_price_var, width=10).pack(side='left', padx=5)
    
    ttk.Button(row0, text="📥 Stiahnuť cenu", command=lambda: fetch_underlying_price(state)).pack(side='left', padx=10)
    
    # ATR 14d
    ttk.Label(row0, text=" ").pack(side='left', padx=4)
    ttk.Button(row0, text="📈 ATR14", command=lambda: fetch_atr(state), width=10).pack(side='left', padx=2)
    ttk.Label(row0, text="× ATR:").pack(side='left', padx=4)
    atr_spin = tk.Spinbox(row0, from_=1.0, to=3.0, increment=0.2, textvariable=state.atr_multiplier_var, width=4, format="%.1f", command=lambda: update_atr_display(state))
    atr_spin.pack(side='left', padx=2)
    atr_label = ttk.Label(row0, text="ATR14: —")
    atr_label.pack(side='left', padx=6)
    state.atr_spin = atr_spin
    state.atr_label = atr_label
    
    # Riadok 0.5: Stoploss
    row05 = ttk.Frame(input_frame)
    row05.pack(fill='x', pady=3)
    
    ttk.Label(row05, text="🛑 Stoploss - cena opcie keď podklad dosiahne short strike:").pack(side='left', padx=5)
    stoploss_price_label = ttk.Label(row05, text="", foreground="red", font=('TkDefaultFont', 10, 'bold'))
    stoploss_price_label.pack(side='left', padx=10)
    state.stoploss_price_label = stoploss_price_label
    ttk.Button(row05, text="🔄 Prepočítať", command=lambda: calculate_stoploss_price(state), width=12).pack(side='left', padx=5)
    
    # Riadok 1: SHORT LEG
    short_frame = ttk.LabelFrame(input_frame, text="🔴 SHORT LEG (predávaná opcia)", padding=5)
    short_frame.pack(fill='x', pady=5)
    
    short_row = ttk.Frame(short_frame)
    short_row.pack(fill='x', pady=3)
    
    ttk.Label(short_row, text="Strike:").pack(side='left', padx=5)
    ttk.Entry(short_row, textvariable=state.calc_short_strike_var, width=10).pack(side='left', padx=5)
    
    ttk.Label(short_row, text="Expiry (YYYYMMDD):").pack(side='left', padx=5)
    calc_short_expiry_combo = ttk.Combobox(short_row, textvariable=state.calc_short_expiry_var, width=12)
    calc_short_expiry_combo.pack(side='left', padx=5)
    state.calc_short_expiry_combo = calc_short_expiry_combo
    
    ttk.Label(short_row, text="Premium $:").pack(side='left', padx=5)
    ttk.Entry(short_row, textvariable=state.calc_short_premium_var, width=8).pack(side='left', padx=5)
    
    ttk.Button(short_row, text="📥 Stiahnuť", command=lambda: fetch_option_price(state, 'short')).pack(side='left', padx=10)
    
    short_rec_strike_label = ttk.Label(short_row, text="", foreground="blue")
    short_rec_strike_label.pack(side='left', padx=5)
    state.short_rec_strike_label = short_rec_strike_label
    
    # Riadok 2: LONG LEG
    long_frame = ttk.LabelFrame(input_frame, text="🟢 LONG LEG (kupovaná opcia)", padding=5)
    long_frame.pack(fill='x', pady=5)
    
    long_row = ttk.Frame(long_frame)
    long_row.pack(fill='x', pady=3)
    
    ttk.Label(long_row, text="Strike:").pack(side='left', padx=5)
    ttk.Entry(long_row, textvariable=state.calc_long_strike_var, width=10).pack(side='left', padx=5)
    
    ttk.Label(long_row, text="Expiry (YYYYMMDD):").pack(side='left', padx=5)
    calc_long_expiry_combo = ttk.Combobox(long_row, textvariable=state.calc_long_expiry_var, width=12)
    calc_long_expiry_combo.pack(side='left', padx=5)
    state.calc_long_expiry_combo = calc_long_expiry_combo
    
    ttk.Label(long_row, text="Premium $:").pack(side='left', padx=5)
    ttk.Entry(long_row, textvariable=state.calc_long_premium_var, width=8).pack(side='left', padx=5)
    ttk.Label(long_row, text="Theta $:").pack(side='left', padx=5)
    ttk.Entry(long_row, textvariable=state.calc_long_theta_var, width=8, state='readonly').pack(side='left', padx=5)
    
    ttk.Button(long_row, text="📥 Stiahnuť", command=lambda: fetch_option_price(state, 'long')).pack(side='left', padx=10)
    
    # Riadok 3: Broker a tlačidlá
    btn_row = ttk.Frame(input_frame)
    btn_row.pack(fill='x', pady=10)
    
    ttk.Label(btn_row, text="Broker:").pack(side='left', padx=5)
    ttk.Combobox(btn_row, textvariable=state.broker_var, values=["IBKR", "SAXO"], width=8).pack(side='left', padx=5)
    
    ttk.Button(btn_row, text="🔄 Načítať expirácie", command=lambda: load_expiries_for_calc(state)).pack(side='left', padx=10)
    
    ttk.Button(btn_row, text="🧮 VYPOČÍTAŤ", command=lambda: calculate_spread(state), 
               style='Accent.TButton').pack(side='left', padx=20)
    
    calc_status_label = ttk.Label(btn_row, text="Pripravené")
    calc_status_label.pack(side='left', padx=20)
    state.calc_status_label = calc_status_label
    
    # === Výsledky výpočtu ===
    result_frame = ttk.LabelFrame(parent, text="📊 Výsledky kalkulácie", padding=10)
    result_frame.pack(fill='both', expand=True, padx=10, pady=10)
    
    calc_result_text = scrolledtext.ScrolledText(result_frame, height=20, font=('Courier', 10))
    calc_result_text.pack(fill='both', expand=True)
    state.calc_result_text = calc_result_text
    
    # Setup callback pre auto-recalc stoploss
    state.set_auto_recalc_callback(lambda: auto_recalc_stoploss(state))
    
    # Aktualizuj expiry combos ak sú dostupné
    if state.available_expiries:
        update_calc_expiry_combos(state, state.available_expiries)

