#!/usr/bin/env python3
"""
Záložka: Interaktívny Optimizer
Interaktívna optimalizácia - tlačidlá +/- pre strike a expiry
"""
import tkinter as tk
from tkinter import ttk, messagebox, scrolledtext
import subprocess
import threading
import os
from datetime import datetime

from modularny.utils import format_comparison, format_single_strategy, parse_option_fetch_output


def load_from_calculator(state):
    """Načíta aktuálnu stratégiu z kalkulátora do optimizera"""
    if not hasattr(state, 'last_calc_result') or not state.last_calc_result:
        messagebox.showwarning("Chyba", "Najprv vypočítajte stratégiu v Kalkulátore")
        return
    
    calc = state.last_calc_result
    
    # Nastav optimizer dáta
    state.opt_data = {
        'short_strike': calc['shortStrike'],
        'short_expiry': calc['shortExpiry'],
        'short_expiry_idx': 0,
        'short_premium': calc['shortPremium'],
        'long_strike': calc['longStrike'],
        'long_expiry': calc['longExpiry'],
        'long_expiry_idx': 0,
        'long_premium': calc['longPremium'],
        'underlying_price': calc['underlyingPrice'],
        'option_type': calc['optionType'],
        'original': calc.copy()
    }
    
    # Nájdi indexy expirácií
    if state.available_expiries:
        if calc['shortExpiry'] in state.available_expiries:
            state.opt_data['short_expiry_idx'] = state.available_expiries.index(calc['shortExpiry'])
        if calc['longExpiry'] in state.available_expiries:
            state.opt_data['long_expiry_idx'] = state.available_expiries.index(calc['longExpiry'])
    
    # Aktualizuj labels
    update_optimizer_labels(state)
    
    # Aktualizuj entry polia
    if hasattr(state, 'opt_short_premium_entry'):
        state.opt_short_premium_entry.delete(0, tk.END)
        state.opt_short_premium_entry.insert(0, f"{calc['shortPremium']:.2f}")
    if hasattr(state, 'opt_long_premium_entry'):
        state.opt_long_premium_entry.delete(0, tk.END)
        state.opt_long_premium_entry.insert(0, f"{calc['longPremium']:.2f}")
    
    # Aktualizuj current label
    if hasattr(state, 'opt_current_label'):
        state.opt_current_label.config(
            text=f"{calc['spreadType']}: Short {calc['shortStrike']} @ ${calc['shortPremium']:.2f} | "
                 f"Long {calc['longStrike']} @ ${calc['longPremium']:.2f} | ROI: {calc['weeklyROI']:.2f}%/týždeň"
        )
    
    recalculate_optimizer(state)


def update_optimizer_labels(state):
    """Aktualizuje labels v optimizer tabe"""
    if not hasattr(state, 'opt_data'):
        return
    
    if hasattr(state, 'opt_short_strike_label'):
        state.opt_short_strike_label.config(text=f"${state.opt_data['short_strike']:.0f}")
    if hasattr(state, 'opt_short_expiry_label'):
        state.opt_short_expiry_label.config(text=state.opt_data['short_expiry'] or "--------")
    if hasattr(state, 'opt_long_strike_label'):
        state.opt_long_strike_label.config(text=f"${state.opt_data['long_strike']:.0f}")
    if hasattr(state, 'opt_long_expiry_label'):
        state.opt_long_expiry_label.config(text=state.opt_data['long_expiry'] or "--------")


def adjust_strike(state, leg, delta):
    """Upraví strike o delta"""
    if not hasattr(state, 'opt_data'):
        return
    
    if leg == 'short':
        state.opt_data['short_strike'] += delta
    else:
        state.opt_data['long_strike'] += delta
    update_optimizer_labels(state)
    # Automaticky stiahni nové premium
    fetch_premium(state, leg)


def adjust_expiry(state, leg, delta):
    """Zmení expiráciu na predchádzajúcu/nasledujúcu"""
    if not hasattr(state, 'opt_data'):
        return
    
    if not state.available_expiries:
        messagebox.showwarning("Chyba", "Najprv načítajte expirácie")
        return
    
    if leg == 'short':
        new_idx = state.opt_data['short_expiry_idx'] + delta
        if 0 <= new_idx < len(state.available_expiries):
            state.opt_data['short_expiry_idx'] = new_idx
            state.opt_data['short_expiry'] = state.available_expiries[new_idx]
    else:
        new_idx = state.opt_data['long_expiry_idx'] + delta
        if 0 <= new_idx < len(state.available_expiries):
            state.opt_data['long_expiry_idx'] = new_idx
            state.opt_data['long_expiry'] = state.available_expiries[new_idx]
    
    update_optimizer_labels(state)
    # Automaticky stiahni nové premium
    fetch_premium(state, leg)


def fetch_premium(state, leg):
    """Stiahne premium pre aktuálny strike/expiry v optimizeri"""
    if not hasattr(state, 'opt_data'):
        return
    
    if leg == 'short':
        strike = state.opt_data['short_strike']
        expiry = state.opt_data['short_expiry']
        entry = state.opt_short_premium_entry
        premium_key = 'short_premium'
    else:
        strike = state.opt_data['long_strike']
        expiry = state.opt_data['long_expiry']
        entry = state.opt_long_premium_entry
        premium_key = 'long_premium'
    
    if not strike or not expiry:
        messagebox.showwarning("Chyba", "Nastavte strike a expiry")
        return
    
    right = 'C' if state.opt_data['option_type'] == 'CALL' else 'P'
    symbol = state.symbol_var.get()
    port = state.port_var.get()
    
    if hasattr(state, 'calc_status_label'):
        state.calc_status_label.config(text=f"Sťahujem {leg} premium...")
    
    def run():
        try:
            script_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'scripts', 'tws_fetch_option.py')
            result = subprocess.run(
                ['python3', script_path, str(port), symbol, expiry, str(strike), right], 
                capture_output=True, text=True, timeout=20,
                cwd='/home/narbon/Aplikácie/tws-webapp'
            )
            
            output = result.stdout.strip()
            stderr = result.stderr.strip()

            if result.returncode != 0:
                err = output or stderr or "TWS vrátil chybu"
                if hasattr(state, 'calc_status_label'):
                    state.root.after(0, lambda msg=err, lt=leg: state.calc_status_label.config(text=f"❌ {lt}: {msg}"))
                return

            if not output:
                err = stderr or "Žiadna odpoveď z TWS"
                if hasattr(state, 'calc_status_label'):
                    state.root.after(0, lambda msg=err, lt=leg: state.calc_status_label.config(text=f"❌ {lt}: {msg}"))
                return

            try:
                price, theta = parse_option_fetch_output(output)
            except ValueError as err:
                msg = str(err)
                if hasattr(state, 'calc_status_label'):
                    state.root.after(0, lambda m=msg, lt=leg: state.calc_status_label.config(text=f"❌ {lt}: {m}"))
                return

            if price > 0:
                formatted_price = f"{price:.2f}"
                state.root.after(0, lambda e=entry, val=formatted_price: _update_premium_entry(e, val))
                state.root.after(0, lambda key=premium_key, val=price: _update_opt_premium(state, key, val))
                if hasattr(state, 'calc_status_label'):
                    state.root.after(0, lambda lt=leg, st=strike, val=formatted_price: state.calc_status_label.config(
                        text=f"✓ {lt.upper()} {st} @ ${val}"))
                state.root.after(100, lambda: recalculate_optimizer(state))
            else:
                if hasattr(state, 'calc_status_label'):
                    state.root.after(0, lambda lt=leg: state.calc_status_label.config(text=f"❌ {lt}: Cena = 0"))
                    
        except subprocess.TimeoutExpired:
            if hasattr(state, 'calc_status_label'):
                state.root.after(0, lambda: state.calc_status_label.config(text=f"❌ Timeout"))
        except Exception as e:
            if hasattr(state, 'calc_status_label'):
                state.root.after(0, lambda err=str(e): state.calc_status_label.config(text=f"❌ {err}"))
    
    threading.Thread(target=run, daemon=True).start()


def _update_premium_entry(entry, value):
    """Helper na aktualizáciu entry poľa"""
    entry.delete(0, tk.END)
    entry.insert(0, value)


def _update_opt_premium(state, key, value):
    """Helper na aktualizáciu opt_data premium"""
    if hasattr(state, 'opt_data'):
        state.opt_data[key] = value


def calculate_spread_internal(state, short_strike, short_premium, short_expiry,
                              long_strike, long_premium, long_expiry,
                              underlying_price, option_type):
    """Interný výpočet spreadu - vracia dict"""
    spread_width = abs(short_strike - long_strike) if long_strike > 0 else 0
    same_expiry = (short_expiry == long_expiry) or not long_expiry
    
    # DTE
    today = datetime.now()
    if short_expiry:
        try:
            short_exp_date = datetime.strptime(short_expiry, '%Y%m%d')
            short_dte = max(1, (short_exp_date - today).days)
        except:
            short_dte = 7
    else:
        short_dte = 7
    
    if long_expiry:
        try:
            long_exp_date = datetime.strptime(long_expiry, '%Y%m%d')
            long_dte = max(1, (long_exp_date - today).days)
        except:
            long_dte = short_dte
    else:
        long_dte = short_dte
    
    # Net credit/debit
    net_amount = short_premium - long_premium
    is_credit = net_amount > 0
    
    # Typ spreadu
    if same_expiry:
        if spread_width == 0:
            spread_type = f"Single {option_type}"
        elif is_credit:
            spread_type = f"Vertical CREDIT ({option_type})"
        else:
            spread_type = f"Vertical DEBIT ({option_type})"
    else:
        if spread_width == 0:
            spread_type = f"Calendar Spread ({option_type})"
        elif is_credit:
            spread_type = f"Diagonal CREDIT"
        else:
            spread_type = f"PMCC" if option_type == 'CALL' else "PMCP"
    
    broker = state.broker_var.get()
    broker_pct = 0.10 if broker == 'IBKR' else 0.15
    
    if is_credit:
        net_credit = net_amount
        max_profit = net_credit * 100
        max_loss = (spread_width - net_credit) * 100 if spread_width > 0 else float('inf')
        
        # Margin pre CREDIT spread
        if spread_width > 0 and same_expiry:
            margin = spread_width * 100
        elif spread_width > 0:
            margin = spread_width * 100 * 1.2
        else:
            margin = underlying_price * broker_pct * 100
        
        if option_type == 'PUT':
            break_even = short_strike - net_credit
        else:
            break_even = short_strike + net_credit
        
        if margin > 0:
            total_roi = (net_credit * 100 / margin) * 100
            weekly_roi = total_roi / short_dte * 7
        else:
            weekly_roi = 0
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
            else:
                weekly_roi = 0
        else:
            weekly_roi = 0
    
    return {
        'shortStrike': short_strike,
        'shortPremium': short_premium,
        'shortExpiry': short_expiry,
        'shortDTE': short_dte,
        'longStrike': long_strike,
        'longPremium': long_premium,
        'longExpiry': long_expiry,
        'longDTE': long_dte,
        'spreadWidth': spread_width,
        'spreadType': spread_type,
        'isCredit': is_credit,
        'netCredit': net_amount if is_credit else 0,
        'netDebit': abs(net_amount) if not is_credit else 0,
        'maxProfit': max_profit,
        'maxLoss': max_loss,
        'margin': margin,
        'breakEven': break_even,
        'weeklyROI': weekly_roi,
        'underlyingPrice': underlying_price,
        'optionType': option_type,
    }


def recalculate_optimizer(state):
    """Prepočíta stratégiu s aktuálnymi hodnotami"""
    if not hasattr(state, 'opt_data'):
        return
    
    # Získaj premium z entry polí
    try:
        if hasattr(state, 'opt_short_premium_entry'):
            state.opt_data['short_premium'] = float(state.opt_short_premium_entry.get() or 0)
        if hasattr(state, 'opt_long_premium_entry'):
            state.opt_data['long_premium'] = float(state.opt_long_premium_entry.get() or 0)
    except ValueError:
        pass
    
    # Vypočítaj novú stratégiu
    new_calc = calculate_spread_internal(
        state,
        state.opt_data['short_strike'],
        state.opt_data['short_premium'],
        state.opt_data['short_expiry'],
        state.opt_data['long_strike'],
        state.opt_data['long_premium'],
        state.opt_data['long_expiry'],
        state.opt_data['underlying_price'],
        state.opt_data['option_type']
    )
    
    # Porovnaj s pôvodnou
    orig = state.opt_data.get('original')
    
    compare_text = format_comparison(orig, new_calc) if orig else format_single_strategy(new_calc, "AKTUÁLNA STRATÉGIA")
    
    if hasattr(state, 'opt_compare_text'):
        state.opt_compare_text.delete(1.0, tk.END)
        state.opt_compare_text.insert(tk.END, compare_text)


def apply_to_calculator(state):
    """Prenesie hodnoty z optimizera do kalkulátora"""
    if not hasattr(state, 'opt_data'):
        messagebox.showwarning("Chyba", "Najprv načítajte stratégiu z Kalkulátora")
        return
    
    state.calc_short_strike_var.set(str(state.opt_data['short_strike']))
    state.calc_short_expiry_var.set(state.opt_data['short_expiry'])
    if hasattr(state, 'opt_short_premium_entry'):
        state.calc_short_premium_var.set(state.opt_short_premium_entry.get())
    
    state.calc_long_strike_var.set(str(state.opt_data['long_strike']))
    state.calc_long_expiry_var.set(state.opt_data['long_expiry'])
    if hasattr(state, 'opt_long_premium_entry'):
        state.calc_long_premium_var.set(state.opt_long_premium_entry.get())
    
    messagebox.showinfo("Hotovo", "Hodnoty prenesené do Kalkulátora")


def create_interactive_optimizer_tab(parent, state):
    """Záložka pre interaktívnu optimalizáciu"""
    
    # === Aktuálna stratégia (z kalkulátora) ===
    current_frame = ttk.LabelFrame(parent, text="📋 Aktuálna stratégia (z Kalkulátora)", padding=10)
    current_frame.pack(fill='x', padx=10, pady=5)
    
    opt_current_label = ttk.Label(current_frame, text="Najprv vypočítajte stratégiu v Kalkulátore", 
                                  font=('Courier', 10))
    opt_current_label.pack(fill='x')
    state.opt_current_label = opt_current_label
    
    ttk.Button(current_frame, text="🔄 Načítať z Kalkulátora", 
               command=lambda: load_from_calculator(state)).pack(pady=5)
    
    # === Optimalizačné ovládače ===
    controls_frame = ttk.LabelFrame(parent, text="🎛️ Úprava parametrov", padding=10)
    controls_frame.pack(fill='x', padx=10, pady=5)
    
    # SHORT LEG ovládače
    short_frame = ttk.LabelFrame(controls_frame, text="🔴 SHORT LEG", padding=5)
    short_frame.pack(fill='x', pady=5)
    
    short_row1 = ttk.Frame(short_frame)
    short_row1.pack(fill='x', pady=3)
    
    ttk.Label(short_row1, text="Strike:").pack(side='left', padx=5)
    ttk.Button(short_row1, text="-5", width=4, command=lambda: adjust_strike(state, 'short', -5)).pack(side='left', padx=2)
    ttk.Button(short_row1, text="-1", width=4, command=lambda: adjust_strike(state, 'short', -1)).pack(side='left', padx=2)
    opt_short_strike_label = ttk.Label(short_row1, text="$---", width=10, font=('Courier', 11, 'bold'))
    opt_short_strike_label.pack(side='left', padx=10)
    state.opt_short_strike_label = opt_short_strike_label
    ttk.Button(short_row1, text="+1", width=4, command=lambda: adjust_strike(state, 'short', 1)).pack(side='left', padx=2)
    ttk.Button(short_row1, text="+5", width=4, command=lambda: adjust_strike(state, 'short', 5)).pack(side='left', padx=2)
    
    short_row2 = ttk.Frame(short_frame)
    short_row2.pack(fill='x', pady=3)
    
    ttk.Label(short_row2, text="Expiry:").pack(side='left', padx=5)
    ttk.Button(short_row2, text="◀ Prev", width=8, command=lambda: adjust_expiry(state, 'short', -1)).pack(side='left', padx=2)
    opt_short_expiry_label = ttk.Label(short_row2, text="--------", width=12, font=('Courier', 11, 'bold'))
    opt_short_expiry_label.pack(side='left', padx=10)
    state.opt_short_expiry_label = opt_short_expiry_label
    ttk.Button(short_row2, text="Next ▶", width=8, command=lambda: adjust_expiry(state, 'short', 1)).pack(side='left', padx=2)
    
    ttk.Label(short_row2, text="Premium:").pack(side='left', padx=15)
    opt_short_premium_entry = ttk.Entry(short_row2, width=8)
    opt_short_premium_entry.pack(side='left', padx=2)
    state.opt_short_premium_entry = opt_short_premium_entry
    ttk.Button(short_row2, text="📥", width=3, command=lambda: fetch_premium(state, 'short')).pack(side='left', padx=2)
    
    # LONG LEG ovládače
    long_frame = ttk.LabelFrame(controls_frame, text="🟢 LONG LEG", padding=5)
    long_frame.pack(fill='x', pady=5)
    
    long_row1 = ttk.Frame(long_frame)
    long_row1.pack(fill='x', pady=3)
    
    ttk.Label(long_row1, text="Strike:").pack(side='left', padx=5)
    ttk.Button(long_row1, text="-5", width=4, command=lambda: adjust_strike(state, 'long', -5)).pack(side='left', padx=2)
    ttk.Button(long_row1, text="-1", width=4, command=lambda: adjust_strike(state, 'long', -1)).pack(side='left', padx=2)
    opt_long_strike_label = ttk.Label(long_row1, text="$---", width=10, font=('Courier', 11, 'bold'))
    opt_long_strike_label.pack(side='left', padx=10)
    state.opt_long_strike_label = opt_long_strike_label
    ttk.Button(long_row1, text="+1", width=4, command=lambda: adjust_strike(state, 'long', 1)).pack(side='left', padx=2)
    ttk.Button(long_row1, text="+5", width=4, command=lambda: adjust_strike(state, 'long', 5)).pack(side='left', padx=2)
    
    long_row2 = ttk.Frame(long_frame)
    long_row2.pack(fill='x', pady=3)
    
    ttk.Label(long_row2, text="Expiry:").pack(side='left', padx=5)
    ttk.Button(long_row2, text="◀ Prev", width=8, command=lambda: adjust_expiry(state, 'long', -1)).pack(side='left', padx=2)
    opt_long_expiry_label = ttk.Label(long_row2, text="--------", width=12, font=('Courier', 11, 'bold'))
    opt_long_expiry_label.pack(side='left', padx=10)
    state.opt_long_expiry_label = opt_long_expiry_label
    ttk.Button(long_row2, text="Next ▶", width=8, command=lambda: adjust_expiry(state, 'long', 1)).pack(side='left', padx=2)
    
    ttk.Label(long_row2, text="Premium:").pack(side='left', padx=15)
    opt_long_premium_entry = ttk.Entry(long_row2, width=8)
    opt_long_premium_entry.pack(side='left', padx=2)
    state.opt_long_premium_entry = opt_long_premium_entry
    ttk.Button(long_row2, text="📥", width=3, command=lambda: fetch_premium(state, 'long')).pack(side='left', padx=2)
    
    # Tlačidlo prepočítať
    btn_frame = ttk.Frame(controls_frame)
    btn_frame.pack(fill='x', pady=10)
    
    ttk.Button(btn_frame, text="🔄 Načítať expirácie", command=state.load_expiries).pack(side='left', padx=5)
    ttk.Button(btn_frame, text="🧮 PREPOČÍTAŤ", command=lambda: recalculate_optimizer(state)).pack(side='left', padx=20)
    ttk.Button(btn_frame, text="📋 Použiť v Kalkulátore", command=lambda: apply_to_calculator(state)).pack(side='right', padx=5)
    
    # === Porovnanie ===
    compare_frame = ttk.LabelFrame(parent, text="📊 Porovnanie (Pôvodná vs Upravená)", padding=10)
    compare_frame.pack(fill='both', expand=True, padx=10, pady=5)
    
    opt_compare_text = scrolledtext.ScrolledText(compare_frame, height=15, font=('Courier', 9))
    opt_compare_text.pack(fill='both', expand=True)
    state.opt_compare_text = opt_compare_text
    
    # Inicializuj optimizer dáta
    if not hasattr(state, 'opt_data'):
        state.opt_data = {
            'short_strike': 0,
            'short_expiry': '',
            'short_expiry_idx': 0,
            'short_premium': 0,
            'long_strike': 0,
            'long_expiry': '',
            'long_expiry_idx': 0,
            'long_premium': 0,
            'underlying_price': 0,
            'option_type': 'CALL',
            'original': None
        }

