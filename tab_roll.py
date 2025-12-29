#!/usr/bin/env python3
"""
Záložka: Roll Optimizer
Optimalizácia rolovania LONG legu pri Calendar/Diagonal spreadoch
"""
import tkinter as tk
from tkinter import ttk, messagebox, scrolledtext
import subprocess
import threading
import os
import math
from datetime import datetime, date

try:
    from scipy.stats import norm
    SCIPY_AVAILABLE = True
except ImportError:
    SCIPY_AVAILABLE = False


def roll_fetch_underlying(state):
    """Stiahne cenu podkladu pre Roll Optimizer"""
    def run():
        try:
            script_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'scripts', 'tws_fetch_price.py')
            result = subprocess.run(
                ['python3', script_path, str(state.port_var.get()), state.symbol_var.get()], 
                capture_output=True, text=True, timeout=20,
                cwd='/home/narbon/Aplikácie/tws-webapp'
            )
            output = result.stdout.strip().split('\n')[0]
            if result.returncode == 0 and output and not output.startswith("ERROR:"):
                state.root.after(0, lambda p=output: state.roll_underlying_var.set(p))
                if hasattr(state, 'roll_status_label'):
                    state.root.after(0, lambda: state.roll_status_label.config(text=f"✓ Cena: ${output}"))
            else:
                if hasattr(state, 'roll_status_label'):
                    state.root.after(0, lambda: state.roll_status_label.config(text="❌ Chyba načítania ceny"))
        except Exception as e:
            if hasattr(state, 'roll_status_label'):
                state.root.after(0, lambda: state.roll_status_label.config(text=f"❌ {str(e)[:30]}"))
    
    if hasattr(state, 'roll_status_label'):
        state.roll_status_label.config(text="Sťahujem cenu...")
    threading.Thread(target=run, daemon=True).start()


def roll_fetch_current_premium(state):
    """Stiahne aktuálnu cenu LONG opcie"""
    strike = state.roll_current_strike_var.get()
    expiry = state.roll_current_expiry_var.get()
    
    if not strike or not expiry:
        messagebox.showwarning("Chyba", "Zadajte strike a expiry")
        return
    
    right = 'C' if state.option_type_var.get() == 'CALL' else 'P'
    symbol = state.symbol_var.get()
    port = state.port_var.get()
    
    def run():
        try:
            script_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'scripts', 'tws_fetch_option.py')
            result = subprocess.run(
                ['python3', script_path, str(port), symbol, expiry, str(strike), right], 
                capture_output=True, text=True, timeout=20,
                cwd='/home/narbon/Aplikácie/tws-webapp'
            )
            output = result.stdout.strip()
            if result.returncode == 0 and output and not output.startswith("ERROR:"):
                price = float(output)
                state.root.after(0, lambda: state.roll_current_premium_var.set(f"{price:.2f}"))
                if hasattr(state, 'roll_status_label'):
                    state.root.after(0, lambda: state.roll_status_label.config(text=f"✓ LONG @ ${price:.2f}"))
                state.root.after(0, lambda: roll_update_dte(state))
            else:
                if hasattr(state, 'roll_status_label'):
                    state.root.after(0, lambda: state.roll_status_label.config(text="❌ Chyba načítania premium"))
        except Exception as e:
            if hasattr(state, 'roll_status_label'):
                state.root.after(0, lambda: state.roll_status_label.config(text=f"❌ {str(e)[:30]}"))
    
    if hasattr(state, 'roll_status_label'):
        state.roll_status_label.config(text="Sťahujem premium...")
    threading.Thread(target=run, daemon=True).start()


def roll_update_dte(state):
    """Aktualizuje DTE pre aktuálnu LONG pozíciu"""
    expiry = state.roll_current_expiry_var.get()
    if expiry:
        try:
            exp_date = datetime.strptime(expiry, '%Y%m%d')
            dte = max(0, (exp_date - datetime.now()).days)
            state.roll_current_dte_var.set(str(dte))
        except:
            state.roll_current_dte_var.set("?")


def roll_load_from_calculator(state):
    """Načíta LONG pozíciu z kalkulátora"""
    if not hasattr(state, 'last_calc_result') or not state.last_calc_result:
        messagebox.showwarning("Chyba", "Najprv vypočítajte stratégiu v Kalkulátore")
        return
    
    calc = state.last_calc_result
    
    # Nastav hodnoty
    state.roll_current_strike_var.set(str(calc['longStrike']))
    state.roll_current_expiry_var.set(calc['longExpiry'] or '')
    state.roll_current_premium_var.set(f"{calc['longPremium']:.2f}")
    state.roll_underlying_var.set(f"{calc['underlyingPrice']:.2f}")
    
    # Net debit ako celková investícia
    if not calc['isCredit']:
        net_debit = calc.get('netDebit', 0)
        state.roll_total_invested_var.set(f"{net_debit:.2f}")
    
    roll_update_dte(state)
    if hasattr(state, 'roll_status_label'):
        state.roll_status_label.config(text="✓ Načítané z Kalkulátora")


def calc_be_for_roll(option_type, strike, cost_per_share, underlying):
    """Vypočíta break-even pre roll pozíciu"""
    if option_type == 'PUT':
        return strike - cost_per_share
    else:
        return strike + cost_per_share


def estimate_probability(option_type, underlying, strike, dte):
    """Odhadne pravdepodobnosť profitu"""
    annual_vol = 0.20
    daily_vol = annual_vol / math.sqrt(252)
    period_vol = daily_vol * math.sqrt(dte)
    
    distance_pct = (underlying - strike) / underlying
    
    if period_vol > 0:
        z_score = distance_pct / period_vol
    else:
        z_score = 0
    
    if SCIPY_AVAILABLE:
        if option_type == 'PUT':
            prob = norm.cdf(-z_score) * 100
        else:
            prob = (1 - norm.cdf(-z_score)) * 100
    else:
        prob = max(5, min(95, 50 - z_score * 20))
    
    return round(prob, 1)


def analyze_roll_scenarios(state):
    """Analyzuje možné roll scenáre pre LONG pozíciu"""
    try:
        underlying = float(state.roll_underlying_var.get() or 0)
        current_strike = float(state.roll_current_strike_var.get() or 0)
        current_premium = float(state.roll_current_premium_var.get() or 0)
        current_expiry = state.roll_current_expiry_var.get()
        total_invested = float(state.roll_total_invested_var.get() or 0)
        received_credit = float(state.roll_received_credit_var.get() or 0)
        option_type = state.option_type_var.get()
        
        if not all([underlying, current_strike, current_premium]):
            messagebox.showwarning("Chyba", "Vyplňte všetky povinné polia")
            return
        
        net_position = received_credit - total_invested + (current_premium * 100)
        break_even_needed = total_invested - received_credit
        
        scenarios = []
        
        # 1. DRŽAŤ
        scenarios.append({
            'action': '🔵 DRŽAŤ',
            'new_strike': current_strike,
            'new_expiry': current_expiry,
            'cost': 0,
            'total_cost': total_invested - received_credit,
            'break_even': calc_be_for_roll(option_type, current_strike, break_even_needed / 100, underlying),
            'prob_profit': estimate_probability(option_type, underlying, current_strike, int(state.roll_current_dte_var.get() or 14)),
            'note': f'Aktuálna hodnota LONG: ${current_premium * 100:.2f}'
        })
        
        # 2. PREDAŤ
        realized_pnl = received_credit + (current_premium * 100) - total_invested
        scenarios.append({
            'action': '🔴 PREDAŤ',
            'new_strike': '-',
            'new_expiry': '-',
            'cost': -current_premium * 100,
            'total_cost': 0,
            'break_even': '-',
            'prob_profit': 100 if realized_pnl >= 0 else 0,
            'note': f'Realizovaný P/L: ${realized_pnl:.2f}'
        })
        
        # 3. ROLL NA VYŠŠÍ STRIKE
        if option_type == 'PUT':
            new_strikes = [current_strike + 3, current_strike + 5, current_strike + 7, current_strike + 10]
        else:
            new_strikes = [current_strike - 3, current_strike - 5, current_strike - 7, current_strike - 10]
        
        for new_strike in new_strikes:
            if new_strike <= 0:
                continue
            
            current_distance = abs(underlying - current_strike)
            new_distance = abs(underlying - new_strike)
            
            if new_distance < current_distance:
                price_ratio = 1 + (current_distance - new_distance) / underlying * 10
                estimated_new_premium = current_premium * price_ratio
            else:
                price_ratio = 1 - (new_distance - current_distance) / underlying * 5
                estimated_new_premium = max(0.10, current_premium * price_ratio)
            
            roll_cost = (estimated_new_premium - current_premium) * 100
            new_total_cost = total_invested - received_credit + roll_cost
            new_be = calc_be_for_roll(option_type, new_strike, new_total_cost / 100, underlying)
            dte = int(state.roll_current_dte_var.get() or 14)
            prob = estimate_probability(option_type, underlying, new_strike, dte)
            
            scenarios.append({
                'action': f'🔄 ROLL →${new_strike:.0f}',
                'new_strike': new_strike,
                'new_expiry': current_expiry,
                'cost': roll_cost,
                'total_cost': new_total_cost,
                'break_even': new_be,
                'prob_profit': prob,
                'note': f'Odhadovaná cena novej opcie: ${estimated_new_premium:.2f}'
            })
        
        # 4. ROLL NA DLHŠIU EXPIRÁCIU
        if state.available_expiries:
            current_idx = -1
            if current_expiry in state.available_expiries:
                current_idx = state.available_expiries.index(current_expiry)
            
            for i in range(current_idx + 1, min(current_idx + 4, len(state.available_expiries))):
                new_expiry = state.available_expiries[i]
                try:
                    new_exp_date = datetime.strptime(new_expiry, '%Y%m%d')
                    current_exp_date = datetime.strptime(current_expiry, '%Y%m%d')
                    extra_days = (new_exp_date - current_exp_date).days
                    
                    theta_factor = 1 + (extra_days * 0.007)
                    estimated_new_premium = current_premium * theta_factor
                    
                    roll_cost = (estimated_new_premium - current_premium) * 100
                    new_total_cost = total_invested - received_credit + roll_cost
                    
                    new_dte = max(1, (new_exp_date - datetime.now()).days)
                    prob = estimate_probability(option_type, underlying, current_strike, new_dte)
                    
                    scenarios.append({
                        'action': f'📅 ROLL →{new_expiry}',
                        'new_strike': current_strike,
                        'new_expiry': new_expiry,
                        'cost': roll_cost,
                        'total_cost': new_total_cost,
                        'break_even': calc_be_for_roll(option_type, current_strike, new_total_cost / 100, underlying),
                        'prob_profit': prob,
                        'note': f'+{extra_days} dní, odhad: ${estimated_new_premium:.2f}'
                    })
                except:
                    continue
        
        # Vypočítaj skóre
        for s in scenarios:
            if s['prob_profit'] > 0 and s['break_even'] != '-':
                risk = abs(s['total_cost']) if s['total_cost'] != 0 else 1
                s['score'] = s['prob_profit'] * 100 / max(risk, 1)
            else:
                s['score'] = s['prob_profit']
        
        scenarios.sort(key=lambda x: x['score'], reverse=True)
        
        state.roll_scenarios = scenarios
        display_roll_scenarios(state)
        show_roll_recommendation(state, scenarios, net_position, underlying, option_type)
        
    except Exception as e:
        messagebox.showerror("Chyba", f"Chyba analýzy: {e}")
        import traceback
        traceback.print_exc()


def display_roll_scenarios(state):
    """Zobrazí roll scenáre v tabuľke"""
    if not hasattr(state, 'roll_tree'):
        return
    
    for item in state.roll_tree.get_children():
        state.roll_tree.delete(item)
    
    for s in state.roll_scenarios:
        be_str = f"${s['break_even']:.2f}" if isinstance(s['break_even'], (int, float)) else s['break_even']
        cost_str = f"${s['cost']:.2f}" if s['cost'] >= 0 else f"-${abs(s['cost']):.2f}"
        
        tags = ()
        if s == state.roll_scenarios[0]:
            tags = ('best',)
        
        state.roll_tree.insert('', 'end', values=(
            s['action'],
            f"${s['new_strike']:.0f}" if isinstance(s['new_strike'], (int, float)) else s['new_strike'],
            s['new_expiry'],
            cost_str,
            be_str,
            f"{s['prob_profit']:.1f}%",
            f"{s['score']:.1f} {'★' if s == state.roll_scenarios[0] else ''}"
        ), tags=tags)
    
    state.roll_tree.tag_configure('best', background='#90EE90')


def show_roll_recommendation(state, scenarios, net_position, underlying, option_type):
    """Zobrazí odporúčanie v detail paneli"""
    if not scenarios or not hasattr(state, 'roll_detail_text'):
        return
    
    best = scenarios[0]
    
    recommendation = f"""
╔══════════════════════════════════════════════════════════════════╗
║                    📊 ROLL ANALÝZA                               ║
╠══════════════════════════════════════════════════════════════════╣
║  Aktuálna cena podkladu: ${underlying:,.2f}                       ║
║  Aktuálna hodnota pozície: ${net_position:,.2f}                   ║
║  Trend potrebný pre profit: {'DOLE ↓' if option_type == 'PUT' else 'HORE ↑'}             ║
╠══════════════════════════════════════════════════════════════════╣
║                                                                  ║
║  ⭐ NAJLEPŠÍ SCENÁR: {best['action']:40} ║
║                                                                  ║
║     Doplatok:         ${best['cost']:>10,.2f}                            ║
║     Break-Even:       {'${:.2f}'.format(best['break_even']) if isinstance(best['break_even'], (int, float)) else best['break_even']:>10}                            ║
║     P(Profit):        {best['prob_profit']:>10.1f}%                           ║
║     Skóre:            {best['score']:>10.1f}                              ║
║                                                                  ║
║  📝 Poznámka: {best['note'][:45]:45} ║
╚══════════════════════════════════════════════════════════════════╝

📋 ROZHODOVACÍ STROM:

"""
    
    if best['action'].startswith('🔵'):
        recommendation += """
Ak (cena podkladu sa hýbe správnym smerom) A (DTE > 7):
    → DRŽTE pozíciu
    
Ak (DTE < 7) A (pozícia je v strate):
    → Zvážte PREDAJ alebo ROLL na dlhšiu expiráciu
"""
    elif best['action'].startswith('🔴'):
        recommendation += """
Pozícia má malú šancu na profit.

Odporúčam:
    → PREDAŤ a realizovať zostatok
    → Prípadne počkať na lepší vstup do novej pozície
"""
    elif best['action'].startswith('🔄'):
        recommendation += f"""
Roll na vyšší strike je výhodný ak:
    → Očakávate {'pokles' if option_type == 'PUT' else 'rast'} ceny
    → Chcete zvýšiť pravdepodobnosť profitu
    
POZOR: Roll zvyšuje celkovú investíciu o ${best['cost']:.2f}
"""
    elif best['action'].startswith('📅'):
        recommendation += """
Roll na dlhšiu expiráciu je výhodný ak:
    → Trend je správny, ale potrebujete viac času
    → Theta vám páli aktuálnu pozíciu
    
POZOR: Dlhšia expirácia = vyššia cena opcie
"""
    
    state.roll_detail_text.delete(1.0, tk.END)
    state.roll_detail_text.insert(tk.END, recommendation)


def on_roll_scenario_select(state, event):
    """Handler pre výber roll scenára"""
    if not hasattr(state, 'roll_tree') or not hasattr(state, 'roll_detail_text'):
        return
    
    selection = state.roll_tree.selection()
    if not selection:
        return
    
    item = state.roll_tree.item(selection[0])
    values = item['values']
    
    action = values[0]
    for s in state.roll_scenarios:
        if s['action'] == action:
            detail = f"""
VYBRANÝ SCENÁR: {s['action']}
{'='*50}

Nový Strike:    {s['new_strike']}
Nová Expirácia: {s['new_expiry']}
Doplatok:       ${s['cost']:.2f}
Celkový Cost:   ${s['total_cost']:.2f}
Break-Even:     {f"${s['break_even']:.2f}" if isinstance(s['break_even'], (int, float)) else s['break_even']}
P(Profit):      {s['prob_profit']:.1f}%
Skóre:          {s['score']:.1f}

📝 {s['note']}
"""
            state.roll_detail_text.delete(1.0, tk.END)
            state.roll_detail_text.insert(tk.END, detail)
            break


def create_roll_optimizer_tab(parent, state):
    """Záložka pre optimalizáciu rolovania LONG legu"""
    
    # === Aktuálna pozícia ===
    position_frame = ttk.LabelFrame(parent, text="📋 Aktuálna LONG pozícia", padding=10)
    position_frame.pack(fill='x', padx=10, pady=5)
    
    # Riadok 1: Symbol, Typ, Underlying
    row1 = ttk.Frame(position_frame)
    row1.pack(fill='x', pady=3)
    
    ttk.Label(row1, text="Symbol:").pack(side='left', padx=5)
    ttk.Entry(row1, textvariable=state.symbol_var, width=8).pack(side='left', padx=5)
    
    ttk.Label(row1, text="Typ:").pack(side='left', padx=5)
    ttk.Combobox(row1, textvariable=state.option_type_var, values=["PUT", "CALL"], width=6).pack(side='left', padx=5)
    
    ttk.Label(row1, text="Cena podkladu $:").pack(side='left', padx=5)
    ttk.Entry(row1, textvariable=state.roll_underlying_var, width=10).pack(side='left', padx=5)
    ttk.Button(row1, text="📥", width=3, command=lambda: roll_fetch_underlying(state)).pack(side='left', padx=2)
    
    # Riadok 2: Aktuálny LONG leg
    row2 = ttk.Frame(position_frame)
    row2.pack(fill='x', pady=3)
    
    ttk.Label(row2, text="LONG Strike:").pack(side='left', padx=5)
    ttk.Entry(row2, textvariable=state.roll_current_strike_var, width=10).pack(side='left', padx=5)
    
    ttk.Label(row2, text="Expiry:").pack(side='left', padx=5)
    roll_expiry_combo = ttk.Combobox(row2, textvariable=state.roll_current_expiry_var, width=12)
    roll_expiry_combo.pack(side='left', padx=5)
    state.roll_expiry_combo = roll_expiry_combo
    
    ttk.Label(row2, text="Aktuálna cena $:").pack(side='left', padx=5)
    ttk.Entry(row2, textvariable=state.roll_current_premium_var, width=8).pack(side='left', padx=5)
    ttk.Button(row2, text="📥", width=3, command=lambda: roll_fetch_current_premium(state)).pack(side='left', padx=2)
    
    ttk.Label(row2, text="DTE:").pack(side='left', padx=5)
    ttk.Entry(row2, textvariable=state.roll_current_dte_var, width=5, state='readonly').pack(side='left', padx=2)
    
    # Riadok 3: Investícia a prijatý kredit
    row3 = ttk.Frame(position_frame)
    row3.pack(fill='x', pady=3)
    
    ttk.Label(row3, text="Celková investícia (Net Debit) $:").pack(side='left', padx=5)
    ttk.Entry(row3, textvariable=state.roll_total_invested_var, width=10).pack(side='left', padx=5)
    
    ttk.Label(row3, text="Už prijatý kredit (short exp) $:").pack(side='left', padx=5)
    ttk.Entry(row3, textvariable=state.roll_received_credit_var, width=10).pack(side='left', padx=5)
    
    ttk.Button(row3, text="🔄 Načítať expirácie", command=state.load_expiries).pack(side='left', padx=10)
    ttk.Button(row3, text="📂 Z Kalkulátora", command=lambda: roll_load_from_calculator(state)).pack(side='left', padx=5)
    
    # === Tlačidlo analýzy ===
    btn_frame = ttk.Frame(position_frame)
    btn_frame.pack(fill='x', pady=10)
    
    ttk.Button(btn_frame, text="📊 ANALYZOVAŤ ROLL SCENÁRE", 
               command=lambda: analyze_roll_scenarios(state), style='Accent.TButton').pack(side='left', padx=5)
    
    roll_status_label = ttk.Label(btn_frame, text="Pripravené")
    roll_status_label.pack(side='left', padx=20)
    state.roll_status_label = roll_status_label
    
    # === Tabuľka roll scenárov ===
    table_frame = ttk.LabelFrame(parent, text="📊 Roll scenáre (zoradené podľa skóre)", padding=10)
    table_frame.pack(fill='both', expand=True, padx=10, pady=5)
    
    # Treeview pre roll scenáre
    columns = ('action', 'new_strike', 'new_expiry', 'cost', 'break_even', 'prob_profit', 'score')
    roll_tree = ttk.Treeview(table_frame, columns=columns, show='headings', height=10)
    
    roll_tree.heading('action', text='Akcia')
    roll_tree.heading('new_strike', text='Nový Strike')
    roll_tree.heading('new_expiry', text='Nová Expiry')
    roll_tree.heading('cost', text='Doplatok $')
    roll_tree.heading('break_even', text='Break-Even')
    roll_tree.heading('prob_profit', text='P(Profit)')
    roll_tree.heading('score', text='Skóre ★')
    
    roll_tree.column('action', width=120, anchor='center')
    roll_tree.column('new_strike', width=90, anchor='center')
    roll_tree.column('new_expiry', width=100, anchor='center')
    roll_tree.column('cost', width=90, anchor='center')
    roll_tree.column('break_even', width=90, anchor='center')
    roll_tree.column('prob_profit', width=80, anchor='center')
    roll_tree.column('score', width=80, anchor='center')
    
    # Scrollbar
    scrollbar = ttk.Scrollbar(table_frame, orient="vertical", command=roll_tree.yview)
    roll_tree.configure(yscrollcommand=scrollbar.set)
    
    roll_tree.pack(side='left', fill='both', expand=True)
    scrollbar.pack(side='right', fill='y')
    
    state.roll_tree = roll_tree
    
    # Bind pre výber riadku
    roll_tree.bind('<<TreeviewSelect>>', lambda e: on_roll_scenario_select(state, e))
    
    # === Detaily vybraného scenára ===
    detail_frame = ttk.LabelFrame(parent, text="📝 Detail a odporúčanie", padding=10)
    detail_frame.pack(fill='both', expand=True, padx=10, pady=5)
    
    roll_detail_text = scrolledtext.ScrolledText(detail_frame, height=12, font=('Courier', 10))
    roll_detail_text.pack(fill='both', expand=True)
    state.roll_detail_text = roll_detail_text
    
    # Inicializuj roll_scenarios
    state.roll_scenarios = []
    
    # Aktualizuj expiry combo ak sú dostupné
    if state.available_expiries:
        roll_expiry_combo['values'] = state.available_expiries

