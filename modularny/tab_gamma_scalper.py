#!/usr/bin/env python3
"""
Modul: Gamma Scalper Components
Rozdelenie na Vyhľadávač, Archív, Monitor a Semafor.
Zoskupenie podľa dátumov expirácie.
"""
import tkinter as tk
from tkinter import ttk, messagebox, scrolledtext
import subprocess
import threading
import os
import json
import sys
import math
import traceback
import time
from datetime import datetime

from modularny.utils import is_market_stable
from modularny.tab_swing_watcher import update_watcher_tree

# --- POMOCNÉ FUNKCIE ---

def update_gs_status(state, text, color="black"):
    if hasattr(state, 'gs_mon_status'): 
        state.gs_mon_status.config(text=text, foreground=color)
    if hasattr(state, 'monitor_status_var'):
        state.monitor_status_var.set(f"Monitor: {text}")
        if hasattr(state, 'monitor_status_label'):
            state.monitor_status_label.config(fg=color)

def update_gs_analysis_text(state, text, append=False, color=None):
    if not hasattr(state, 'gs_result_text'): return
    state.gs_result_text.config(state='normal')
    if not append: state.gs_result_text.delete(1.0, tk.END)
    start_idx = state.gs_result_text.index(tk.END)
    state.gs_result_text.insert(tk.END, text)
    if color:
        tag_name = f"color_{color.replace('#','')}"
        state.gs_result_text.tag_configure(tag_name, foreground=color, font=('Courier', 11, 'bold'))
        state.gs_result_text.tag_add(tag_name, start_idx, state.gs_result_text.index(tk.END))
    state.gs_result_text.config(state='disabled')
    state.gs_result_text.see(tk.END)

def update_gs_monitor_text(state, text, append=False):
    if not hasattr(state, 'gs_monitor_text'): return
    state.gs_monitor_text.config(state='normal')
    if not append: state.gs_monitor_text.delete(1.0, tk.END)
    state.gs_monitor_text.insert(tk.END, text)
    state.gs_monitor_text.config(state='disabled')
    state.gs_monitor_text.see(tk.END)

def get_semafor_data(state, ratio):
    try:
        sb = float(state.gs_strong_buy_threshold_var.get().replace(',', '.'))
        b = float(state.gs_buy_threshold_var.get().replace(',', '.'))
        n = float(state.gs_neutral_threshold_var.get().replace(',', '.'))
        st = float(state.gs_stop_threshold_var.get().replace(',', '.'))
    except: 
        sb, b, n, st = 6.0, 4.5, 3.0, 1.5
    
    if ratio >= sb: return "Silný nákup", '#006400', "🟢"
    if ratio >= b: return "Nákup", '#228B22', "🟩"
    if ratio >= n: return "Neutrálny", '#DAA520', "🟡"
    if ratio >= st: return "Stop", '#FF4500', "🟠"
    return "Silný stop", '#8B0000', "🔴"

# --- 1. VYHĽADÁVAČ (PLÁN) ---

def create_gs_finder_tab(parent, state):
    frame = ttk.Frame(parent, padding=10); frame.pack(fill='both', expand=True)
    search_frame = ttk.LabelFrame(frame, text="🔍 Parametre hľadania", padding=10); search_frame.pack(fill='x', pady=5)
    r1 = ttk.Frame(search_frame); r1.pack(fill='x', pady=5)
    ttk.Label(r1, text="Symbol:").pack(side='left', padx=5)
    ttk.Entry(r1, textvariable=state.symbol_var, width=10).pack(side='left', padx=5)
    ttk.Label(r1, text="Expirácia:").pack(side='left', padx=10)
    state.gs_expiry_combo = ttk.Combobox(r1, textvariable=state.calc_short_expiry_var, width=12); state.gs_expiry_combo.pack(side='left', padx=5)
    ttk.Label(r1, text="Cieľová Delta (±):").pack(side='left', padx=10)
    ttk.Entry(r1, textvariable=state.gs_target_delta_var, width=6).pack(side='left', padx=5)
    ttk.Button(r1, text="🔄 Načítať Expirácie", command=state.load_expiries).pack(side='left', padx=10)
    
    # NOVÉ: Manuálne striky
    r1b = ttk.Frame(search_frame); r1b.pack(fill='x', pady=2)
    ttk.Label(r1b, text="--- Manuálne Striky (voliteľné) ---", font=('Arial', 8, 'italic'), foreground='gray').pack(side='left', padx=5)
    ttk.Label(r1b, text="Call Strike:").pack(side='left', padx=5)
    ttk.Entry(r1b, textvariable=state.gs_manual_call_strike_var, width=8).pack(side='left', padx=5)
    ttk.Label(r1b, text="Put Strike:").pack(side='left', padx=10)
    ttk.Entry(r1b, textvariable=state.gs_manual_put_strike_var, width=8).pack(side='left', padx=5)
    ttk.Button(r1b, text="❌ Vymazať", command=lambda: [state.gs_manual_call_strike_var.set(""), state.gs_manual_put_strike_var.set("")]).pack(side='left', padx=10)
    
    r2 = ttk.Frame(search_frame); r2.pack(fill='x', pady=5)
    state.btn_find_strangle = ttk.Button(r2, text="🚀 NÁJSŤ OPTIMÁLNY STRANGLE", command=lambda: find_strangle_gs(state), style='Accent.TButton')
    state.btn_find_strangle.pack(side='left', padx=5, fill='x', expand=True)
    ttk.Button(r2, text="🔍 SKENOVAŤ VŠETKY EXPIRÁCIE", command=lambda: scan_all_expiries_gs(state)).pack(side='left', padx=5)
    ttk.Checkbutton(r2, text="Preferovať B-S Model", variable=state.gs_model_priority_var).pack(side='left', padx=15)
    
    # PROGRESS BAR PRE SKENER
    state.gs_scan_progress = ttk.Progressbar(search_frame, orient='horizontal', mode='determinate', length=100)
    state.gs_scan_progress.pack(fill='x', pady=(5, 0))
    state.gs_scan_progress.pack_forget() # Skryť na začiatku

    semafor_panel = tk.Frame(frame, relief='flat', pady=10); semafor_panel.pack(fill='x', pady=5)
    state.gamma_theory_label = tk.Label(semafor_panel, text="Γ/Θ: —", font=('Arial', 26, 'bold'), fg='white', bg='gray', padx=20, pady=5)
    state.gamma_theory_label.pack(expand=True)

    analysis_frame = ttk.LabelFrame(frame, text="📊 Greeks Analýza (Plán)", padding=10); analysis_frame.pack(fill='both', expand=True, pady=5)
    state.gs_result_text = scrolledtext.ScrolledText(analysis_frame, height=12, font=('Courier', 11))
    state.gs_result_text.pack(fill='both', expand=True); state.gs_result_text.config(state='disabled')

    actions_frame = ttk.Frame(frame); actions_frame.pack(fill='x', pady=5)
    save_frame = ttk.LabelFrame(actions_frame, text="💾 Uložiť tento plán", padding=10); save_frame.pack(side='left', fill='x', expand=True, padx=(0, 5))
    r_save1 = ttk.Frame(save_frame); r_save1.pack(fill='x', pady=2)
    ttk.Label(r_save1, text="Názov:").pack(side='left', padx=5)
    ttk.Entry(r_save1, textvariable=state.gs_strategy_name_var, width=20).pack(side='left', padx=5, fill='x', expand=True)
    r_save2 = ttk.Frame(save_frame); r_save2.pack(fill='x', pady=2)
    ttk.Label(r_save2, text="Poznámka:").pack(side='left', padx=5)
    state.gs_quick_note_entry = ttk.Entry(r_save2); state.gs_quick_note_entry.pack(side='left', padx=5, fill='x', expand=True)
    def quick_save():
        try:
            name = state.gs_strategy_name_var.get().strip()
            if not name: 
                messagebox.showwarning("Chyba", "Zadajte názov stratégie pred uložením.")
                return
            
            # Získať poznámku z políčka
            state.current_gs_note = state.gs_quick_note_entry.get().strip()
            
            # Zavolať uloženie
            state.save_gamma_scalper_strategy(state.gs_strategy_name_var)
            
            # Refresh archívu ak je otvorený
            if hasattr(state, 'refresh_gs_archive_tree'): 
                state.refresh_gs_archive_tree()
                
            messagebox.showinfo("Úspech", f"Plán '{name}' bol úspešne uložený do archívu.")
        except Exception as e:
            messagebox.showerror("Chyba", f"Nepodarilo sa uložiť plán: {e}")
            print(f"DEBUG Save Error: {traceback.format_exc()}")
    ttk.Button(save_frame, text="💾 ULOŽIŤ DO ARCHÍVU", command=quick_save).pack(pady=5, fill='x')

    tws_frame = ttk.LabelFrame(actions_frame, text="⚡ TWS Akcie", padding=10); tws_frame.pack(side='right', fill='y', padx=(5, 0))
    ttk.Button(tws_frame, text="🔍 VEĽKÉ OKNO", command=lambda: open_analysis_window(state, theory=True)).pack(pady=2, fill='x')
    state.btn_buy_theory = ttk.Button(tws_frame, text="🛒 KÚPIŤ STRANGLE (PAPER)", command=lambda: place_order_gs(state), style='Accent.TButton')
    state.btn_buy_theory.pack(pady=2, fill='x')

# --- 2. ARCHÍV PLÁNOV ---

def create_gs_archive_tab(parent, state):
    frame = ttk.Frame(parent, padding=10); frame.pack(fill='both', expand=True)
    archive_frame = ttk.LabelFrame(frame, text="🗄️ Uložené stratégie (Teória)", padding=10); archive_frame.pack(fill='both', expand=True, pady=5)
    
    # Pridaný stĺpec 'sel' pre checkbox
    columns = ('sel', 'symbol', 'name', 'delta', 'saved_at')
    state.gs_archive_tree = ttk.Treeview(archive_frame, columns=columns, show='headings', selectmode='browse')
    
    # Nastavenie hlavičiek a šírok
    state.gs_archive_tree.heading('sel', text='✔')
    state.gs_archive_tree.column('sel', width=30, anchor='center')
    for c, n in zip(columns[1:], ['Ticker', 'Názov', 'Δ', 'Uložené']): 
        state.gs_archive_tree.heading(c, text=n)
    
    state.gs_archive_tree.column('delta', width=60, anchor='center')
    state.gs_archive_tree.column('symbol', width=80, anchor='center')
    state.gs_archive_tree.pack(side='left', fill='both', expand=True)
    
    def refresh():
        for i in state.gs_archive_tree.get_children(): state.gs_archive_tree.delete(i)
        for n, d in sorted(state.saved_gamma_scalper_strategies.items()):
            # Každý riadok začína ako neoznačený [ ]
            state.gs_archive_tree.insert('', tk.END, values=('[ ]', d.get('symbol', ''), n, d.get('target_delta', ''), d.get('saved_at', '')))
    
    refresh(); state.refresh_gs_archive_tree = refresh
    
    def on_tree_click(event):
        item_id = state.gs_archive_tree.identify_row(event.y)
        if not item_id: return
        
        # Ak užívateľ klikol na riadok, prepneme stav [ ] / [X]
        vals = list(state.gs_archive_tree.item(item_id, 'values'))
        vals[0] = '[X]' if vals[0] == '[ ]' else '[ ]'
        state.gs_archive_tree.item(item_id, values=vals)
        
        # Zároveň nastavíme názov stratégie pre potreby vymazania/načítania
        state.gs_strategy_name_var.set(vals[2])
        data = state.saved_gamma_scalper_strategies.get(vals[2], {})
        if hasattr(state, 'gs_note_entry_archive'):
            state.gs_note_entry_archive.delete(0, tk.END); state.gs_note_entry_archive.insert(0, data.get('notes', ''))

    state.gs_archive_tree.bind('<ButtonRelease-1>', on_tree_click)
    btns = ttk.Frame(archive_frame); btns.pack(side='right', fill='y', padx=10)
    ttk.Label(btns, text="Poznámka:").pack(pady=(0, 2), anchor='w')
    state.gs_note_entry_archive = ttk.Entry(btns, width=20); state.gs_note_entry_archive.pack(pady=(0, 10), fill='x')
    def load_and_switch():
        name = state.gs_strategy_name_var.get().strip()
        if not name: return messagebox.showwarning("Chyba", "Vyberte stratégiu.")
        state.load_gamma_scalper_strategy(state.gs_strategy_name_var)
        data = state.saved_gamma_scalper_strategies.get(name, {})
        if hasattr(state, 'gs_quick_note_entry'):
            state.gs_quick_note_entry.delete(0, tk.END); state.gs_quick_note_entry.insert(0, data.get('notes', ''))
        state.gs_notebook.select(0); find_strangle_gs(state)
    ttk.Button(btns, text="📂 NAČÍTAŤ & ZOBRAZIŤ", command=load_and_switch).pack(pady=5, fill='x')
    
    def send_to_advisor():
        # Hľadáme všetky riadky označené s [X]
        marked_items = []
        for item_id in state.gs_archive_tree.get_children():
            vals = state.gs_archive_tree.item(item_id, 'values')
            if vals[0] == '[X]':
                marked_items.append(vals[2]) # Názov stratégie je na indexe 2
        
        # Ak nič nie je označené krížikom, vezmeme aspoň aktuálne vybratý riadok
        if not marked_items:
            sel = state.gs_archive_tree.selection()
            if sel:
                marked_items.append(state.gs_archive_tree.item(sel[0], 'values')[2])
        
        if not marked_items:
            return messagebox.showwarning("Chyba", "Označte aspoň jednu stratégiu v tabuľke (kliknutím na riadok).")
        
        user_msg = ""
        ai_msg = ""
        
        if len(marked_items) == 1:
            # Pôvodná logika pre jeden plán
            name = marked_items[0]
            strat = state.saved_gamma_scalper_strategies.get(name)
            if not strat: return
            analysis = strat.get('analysis_text', '')
            user_msg = f"Prosím o odborný pohľad na plán '{name}':\n\n{analysis}"
            ai_msg = "AI ODBORNÝ POHĽAD NA PLÁN:\n"
            # ... (jednoduchá analýza GT a Vol)
            if "POMER Γ/Θ:" in analysis:
                try:
                    gt_val = float(analysis.split("POMER Γ/Θ: ")[1].split(" ")[0])
                    ai_msg += f"- Efektivita (GT): {gt_val:.2f} " + ("(Vynikajúca)" if gt_val > 6 else "(Dobrá)" if gt_val > 3 else "(Slabá)") + "\n"
                except: pass
            if "LACNÉ" in analysis: ai_msg += "- Volatilita je lacná (IV < HV).\n"
        
        else:
            # Logika pre POROVNANIE viacerých plánov
            names = marked_items
            user_msg = "POROVNANIE STRATÉGIÍ:\n" + ", ".join(names) + "\n\n"
            ai_msg = "📊 AI POROVNANIE VYBRANÝCH STRATÉGIÍ:\n" + "="*45 + "\n"
            
            strats_data = []
            for name in names:
                s = state.saved_gamma_scalper_strategies.get(name, {})
                txt = s.get('analysis_text', '')
                try:
                    # Robustnejšie hľadanie hodnôt v texte
                    gt = 0
                    if "POMER Γ/Θ:" in txt:
                        gt = float(txt.split("POMER Γ/Θ:")[1].strip().split(" ")[0])
                    
                    iv_hv = 1.0
                    if "POMER IV/HV:" in txt:
                        iv_hv = float(txt.split("POMER IV/HV:")[1].strip().split(" ")[0])
                    
                    be = "0.00"
                    if "BREAK-EVEN POHYB:" in txt:
                        be = txt.split("BREAK-EVEN POHYB:")[1].strip().split(" ")[0]
                    
                    strats_data.append({'name': name, 'gt': gt, 'iv_hv': iv_hv, 'be': be})
                except Exception as e:
                    print(f"Chyba pri parsovaní {name}: {e}")

            # Vytvorenie porovnávacej tabuľky do AI správy
            ai_msg += f"{'NÁZOV PLÁNU':20} | {'Γ/Θ':6} | {'IV/HV':5} | {'BE'}\n"
            ai_msg += "-"*50 + "\n"
            for d in strats_data:
                ai_msg += f"{d['name'][:20]:20} | {d['gt']:6.2f} | {d['iv_hv']:5.2f} | {d['be']:>7}\n"
            
            ai_msg += "\n💡 VERDIKT AGENTA:\n"
            if strats_data:
                best_gt = max(strats_data, key=lambda x: x['gt'])
                best_vol = min(strats_data, key=lambda x: x['iv_hv'])
                ai_msg += f"- Najvyššiu efektivitu (Γ/Θ) má: {best_gt['name']}\n"
                ai_msg += f"- Najvýhodnejšiu volatilitu (IV/HV) má: {best_vol['name']}\n"
                if best_gt['name'] == best_vol['name']:
                    ai_msg += f"👉 Odporúčam: {best_gt['name']} (je víťazom v oboch kategóriách)."
                else:
                    ai_msg += f"👉 Odporúčam: {best_gt['name']} (ak chcete rýchly scalp) alebo {best_vol['name']} (ak chcete lacný čas)."

        state.save_consultation(user_msg, ai_msg)
        if hasattr(state, 'refresh_advisor_history'): state.refresh_advisor_history()
        state.gs_notebook.select(4)
        messagebox.showinfo("Advisor", "Porovnanie bolo odoslané do denníka Advisor.")

    ttk.Button(btns, text="🧠 KONZULTOVAŤ S AI", command=send_to_advisor).pack(pady=5, fill='x')
    ttk.Button(btns, text="🗑️ VYMAZAŤ", command=lambda: [state.delete_gamma_scalper_strategy(state.gs_strategy_name_var), refresh()]).pack(pady=5, fill='x')

# --- 3. AUTO-MONITOR (REALITA) ---

def create_gs_monitor_tab(parent, state):
    frame = ttk.Frame(parent, padding=10); frame.pack(fill='both', expand=True)
    sel_frame = ttk.LabelFrame(frame, text="🎯 Živé pozície z TWS", padding=10); sel_frame.pack(fill='x', pady=5)
    r = ttk.Frame(sel_frame); r.pack(fill='x')
    ttk.Label(r, text="Symbol:").pack(side='left', padx=5)
    state.gs_active_sym_combo = ttk.Combobox(r, values=[], width=15, state="readonly"); state.gs_active_sym_combo.pack(side='left', padx=5)
    state.gs_active_sym_combo.bind("<<ComboboxSelected>>", lambda e: [check_position_gs(state), update_stats_ui(state, state.gs_active_sym_combo.get().strip() if "VŠETKO" not in state.gs_active_sym_combo.get() else None)])
    def refresh_live():
        update_gs_status(state, "Načítavam...", "blue")
        def run():
            try:
                py = sys.executable; root = os.path.dirname(os.path.dirname(__file__))
                scr = os.path.join(root, 'scripts', 'tws_manual_test.py')
                res = subprocess.run([py, scr, '--mode', 'positions'], env={**os.environ, 'TWS_PORT': str(state.port_var.get())}, capture_output=True, text=True, timeout=60, cwd=root)
                if res.returncode == 0:
                    symbols = sorted(list(set(p['symbol'] for p in json.loads(res.stdout).get('positions', []) if p.get('symbol'))))
                    # Pridať možnosť monitorovať všetko naraz
                    display_symbols = ["--- VŠETKO (MULTI) ---"] + symbols
                    state.root.after(0, lambda: state.gs_active_sym_combo.config(values=display_symbols))
                    update_gs_status(state, f"OK ({len(symbols)})", "green")
            except: update_gs_status(state, "Chyba", "red")
        threading.Thread(target=run, daemon=True).start()
    ttk.Button(r, text="🔄 Obnoviť zoznam", command=refresh_live).pack(side='left', padx=10)
    
    # AUTOMATICKÉ NAČÍTANIE PRI ŠTARTE ZÁLOŽKY
    state.root.after(1000, refresh_live)
    
    # 2. AUTOMATIZÁCIA (PRESUNUTÉ NAHOR)
    bot_frame = ttk.LabelFrame(frame, text="🤖 Globálna Automatizácia & Robot", padding=10); bot_frame.pack(fill='x', pady=5)
    r2 = ttk.Frame(bot_frame); r2.pack(fill='x')
    ttk.Label(r2, text="Základný Drift:").pack(side='left', padx=5); ttk.Entry(r2, textvariable=state.gs_drift_tol, width=6).pack(side='left', padx=5)
    ttk.Label(r2, text="Základná Δ:").pack(side='left', padx=10); ttk.Entry(r2, textvariable=state.gs_target_delta_pos_var, width=6).pack(side='left', padx=5)
    
    ttk.Checkbutton(r2, text="🔄 Auto-Sledovanie", variable=state.gs_auto_monitor_var, command=lambda: toggle_auto_monitor(state)).pack(side='left', padx=15)
    ttk.Checkbutton(r2, text="🤖 FULL AUTO-SCALP", variable=state.gs_auto_scalp_var).pack(side='left', padx=15)
    state.gs_mon_status = ttk.Label(r2, text="Pripravené", font=('Arial', 9, 'bold')); state.gs_mon_status.pack(side='right', padx=10)
    
    ttk.Label(bot_frame, text="💡 Robot prioritne používa nastavenia zo 'Správcu Driftu'. Ak tam ticker chýba, použije hodnoty vyššie.", font=('Arial', 8, 'italic'), foreground='gray').pack(fill='x', pady=(5, 0))

    # 3. LIVE MONITOR (TERAZ DOLE)
    mon_frame = ttk.LabelFrame(frame, text="📊 Live Monitor Portfólia", padding=10); mon_frame.pack(fill='both', expand=True, pady=5)
    
    # Pridáme panel pre štatistiku skalpov (Cost Basis Reduction)
    stats_frame = ttk.Frame(mon_frame); stats_frame.pack(fill='x', pady=(0, 5))
    state.gs_scalp_stats_label = ttk.Label(stats_frame, text="Skalpy: 0 | Cash Flow: $0.00", font=('Arial', 10, 'bold'), foreground='blue')
    state.gs_scalp_stats_label.pack(side='left')
    ttk.Button(stats_frame, text="📋 Denník", command=lambda: show_scalp_log(state)).pack(side='right')

    state.gs_monitor_text = scrolledtext.ScrolledText(mon_frame, font=('Courier', 11))
    state.gs_monitor_text.pack(fill='both', expand=True); state.gs_monitor_text.config(state='disabled')

# --- LOGIKA SKALPOV ---
SCALP_LOG_FILE = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'scalp_log.json')

def load_scalp_log():
    try:
        if os.path.exists(SCALP_LOG_FILE):
            with open(SCALP_LOG_FILE, 'r') as f: 
                log = json.load(f)
                # POISTKA: Ak staršie záznamy nemajú ID, pridáme ho spätne
                updated = False
                for i, e in enumerate(log):
                    if 'id' not in e:
                        e['id'] = f"legacy_{i}_{e['timestamp'].replace(' ','_')}"
                        updated = True
                if updated:
                    with open(SCALP_LOG_FILE, 'w') as f2: json.dump(log, f2, indent=2)
                return log
    except: pass
    return []

def log_scalp_entry(symbol, action, qty, price, note="", commission=0.0):
    log = load_scalp_log()
    import random
    new_id = datetime.now().strftime('%Y%m%d%H%M%S%f') + str(random.randint(100,999))
    log.append({
        'id': new_id,
        'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'symbol': symbol, 'action': action, 'qty': qty, 'price': price, 
        'note': note, 'commission': commission
    })
    try:
        with open(SCALP_LOG_FILE, 'w') as f: json.dump(log, f, indent=2)
    except: pass

def get_scalp_stats(symbol=None):
    log = load_scalp_log()
    count = 0
    cash_flow = 0.0
    for entry in log:
        if symbol and entry.get('symbol') != symbol: continue
        count += 1
        qty = float(entry.get('qty', 0))
        price = float(entry.get('price', 0))
        comm = float(entry.get('commission', 0))
        val = qty * price
        if entry.get('action') == 'BUY': cash_flow -= (val + comm)
        elif entry.get('action') == 'SELL': cash_flow += (val - comm)
    return count, cash_flow

def delete_scalp_entry(log_id, state, win):
    log = load_scalp_log()
    new_log = [e for e in log if str(e.get('id')) != str(log_id)]
    try:
        with open(SCALP_LOG_FILE, 'w') as f: json.dump(new_log, f, indent=2)
    except: pass
    refresh_log_window(state, win)
    if hasattr(state, 'gs_active_sym_combo'):
        sym = state.gs_active_sym_combo.get().strip()
        update_stats_ui(state, sym if "VŠETKO" not in sym else None)

def delete_scalps_by_symbol(symbol, state, win):
    if not messagebox.askyesno("Vymazať", f"Naozaj vymazať celú históriu pre {symbol}?"): return
    log = load_scalp_log()
    new_log = [e for e in log if e.get('symbol') != symbol]
    try:
        with open(SCALP_LOG_FILE, 'w') as f: json.dump(new_log, f, indent=2)
    except: pass
    refresh_log_window(state, win)
    update_stats_ui(state, None)

def update_scalp_note(log_id, new_note, state, win):
    log = load_scalp_log()
    found = False
    for e in log:
        if str(e.get('id')) == str(log_id):
            e['note'] = new_note
            found = True
            break
    if found:
        try:
            with open(SCALP_LOG_FILE, 'w') as f: json.dump(log, f, indent=2)
        except Exception as e:
            print(f"Chyba pri zápise poznámky: {e}")

def refresh_log_window(state, win, f_val=None):
    if f_val is not None:
        state._log_filter = f_val
    for widget in win.winfo_children(): widget.destroy()
    
    # --- SEKCIÁ 1: ÚČTOVNÁ ZHRNUTIE (MAJETOK) ---
    f_sum = ttk.LabelFrame(win, text="📊 Účtovná súvaha skalpovania (Majetok & Inventár)"); f_sum.pack(fill='x', padx=5, pady=5)
    
    sum_cols = ('sym', 'count', 'tws', 'inv', 'avg', 'market', 'real_pl', 'unreal_pl', 'total_pl')
    sum_tree = ttk.Treeview(f_sum, columns=sum_cols, show='headings', height=5)
    sum_tree.heading('sym', text='Symbol'); sum_tree.column('sym', width=65)
    sum_tree.heading('count', text='Drifty'); sum_tree.column('count', width=50)
    sum_tree.heading('tws', text='TWS Poz'); sum_tree.column('tws', width=75)
    sum_tree.heading('inv', text='Skalp Ks'); sum_tree.column('inv', width=75)
    sum_tree.heading('avg', text='Priem. Cena'); sum_tree.column('avg', width=95)
    sum_tree.heading('market', text='Trh. Cena'); sum_tree.column('market', width=95)
    sum_tree.heading('real_pl', text='Realiz. P/L'); sum_tree.column('real_pl', width=105)
    sum_tree.heading('unreal_pl', text='Nerealiz. P/L'); sum_tree.column('unreal_pl', width=115)
    sum_tree.heading('total_pl', text='CELKOM'); sum_tree.column('total_pl', width=115)
    sum_tree.pack(fill='x', padx=5, pady=5)
    
    log = load_scalp_log()
    summary = {}
    
    # Lepšia účtovná logika: separujeme Realizovaný P/L od Aktuálnej pozície
    for e in log:
        sym = e['symbol']
        if sym not in summary:
            summary[sym] = {
                'qty': 0.0, 
                'realized_pl': 0.0, 
                'avg_cost': 0.0, 
                'comm': 0.0,
                'last_p': 0.0,
                'count': 0
            }
        
        s = summary[sym]
        s['count'] += 1
        try:
            q = float(e.get('qty', 0))
            p = float(e.get('price', 0))
            c = float(e.get('commission', 0))
            action = e.get('action', 'BUY')
            
            if not math.isnan(p) and p > 0:
                s['last_p'] = p 
            
            # Poplatky odpočítavame z celkového P/L
            s['comm'] += c
            
            if action == 'BUY':
                if s['qty'] < 0: # Zatváranie shortu
                    closed_q = min(q, abs(s['qty']))
                    # Zisk zo shortu: (Pôvodná Predajná Cena - Táto Nákupná Cena) * Ks
                    s['realized_pl'] += closed_q * (s['avg_cost'] - p)
                    s['qty'] += q
                    if s['qty'] > 0: # Prešli sme do longu
                        s['avg_cost'] = p
                    # Ak s['qty'] <= 0, avg_cost ostáva rovnaký (pôvodný sell price)
                else: # Sme v longe alebo na nule
                    new_qty = s['qty'] + q
                    s['avg_cost'] = (s['qty'] * s['avg_cost'] + q * p) / new_qty if new_qty > 0 else 0
                    s['qty'] = new_qty
            else: # SELL
                if s['qty'] > 0: # Zatváranie longu
                    closed_q = min(q, s['qty'])
                    # Zisk z longu: (Táto Predajná Cena - Pôvodná Nákupná Cena) * Ks
                    s['realized_pl'] += closed_q * (p - s['avg_cost'])
                    s['qty'] -= q
                    if s['qty'] < 0: # Prešli sme do shortu
                        s['avg_cost'] = p
                    # Ak s['qty'] >= 0, avg_cost ostáva rovnaký (pôvodný buy price)
                else: # Sme v shorte alebo na nule
                    new_qty = s['qty'] - q
                    abs_q = abs(s['qty'])
                    s['avg_cost'] = (abs_q * s['avg_cost'] + q * p) / abs(new_qty) if new_qty != 0 else 0
                    s['qty'] = new_qty
        except: pass

    for sym in sorted(summary.keys()):
        s = summary[sym]
        inv = s['qty']
        real_pl = s['realized_pl'] - s['comm']
        avg_p = s['avg_cost']
        
        # Pokúsime sa získať TWS dáta zo stavu (ak existujú)
        market_p = s['last_p']
        tws_pos_str = "—"
        
        if hasattr(state, 'last_portfolio_data') and sym in state.last_portfolio_data:
            p_data = state.last_portfolio_data[sym]
            if isinstance(p_data, dict): # GS format
                stk_info = p_data.get('STK', [])
                if stk_info:
                    t_pos = sum(float(p.get('position', 0)) for p in stk_info)
                    tws_pos_str = f"{t_pos:+.0f}"
                    for p in stk_info:
                        if p.get('lastPrice') and float(p['lastPrice']) > 0:
                            market_p = float(p['lastPrice'])
            else: # Monitor format
                t_pos = 0
                for p in p_data:
                    if p.get('secType') == 'STK':
                        t_pos += float(p.get('position', 0))
                        if p.get('lastPrice') and float(p['lastPrice']) > 0:
                            market_p = float(p['lastPrice'])
                tws_pos_str = f"{t_pos:+.0f}"

        unreal_pl = 0.0
        if abs(inv) > 0.001:
            if inv > 0:
                unreal_pl = inv * (market_p - avg_p)
            else:
                unreal_pl = abs(inv) * (avg_p - market_p)
                
        total_pl = real_pl + unreal_pl
        
        sum_tree.insert('', tk.END, values=(
            sym,
            s['count'],
            tws_pos_str,
            f"{inv:+.0f}",
            f"{avg_p:.2f} $" if avg_p > 0 else "—",
            f"{market_p:.2f} $",
            f"{real_pl:+.2f} $",
            f"{unreal_pl:+.2f} $",
            f"{total_pl:+.2f} $"
        ))
    
    # Farebné tagy pre P/L
    sum_tree.tag_configure('plus', foreground='green')
    sum_tree.tag_configure('minus', foreground='red')
    for item in sum_tree.get_children():
        vals = sum_tree.item(item)['values']
        try:
            # CELKOM (posledný stĺpec - teraz index 8)
            total_v = float(str(vals[8]).replace('$', '').replace(' ', ''))
            if total_v > 0.01: sum_tree.item(item, tags=('plus',))
            elif total_v < -0.01: sum_tree.item(item, tags=('minus',))
        except: pass

    # --- SEKCIÁ 2: DETAILNÝ DENNÍK ---
    ttk.Separator(win, orient='horizontal').pack(fill='x', pady=5)
    f_mid = ttk.Frame(win); f_mid.pack(fill='x', padx=5, pady=5)
    ttk.Label(f_mid, text="🔍 Filter symbolu:").pack(side='left')
    filter_var = tk.StringVar()
    curr_f = getattr(state, '_log_filter', "").upper()
    filter_var.set(curr_f)

    ent = ttk.Entry(f_mid, textvariable=filter_var)
    ent.pack(side='left', padx=5)
    ttk.Button(f_mid, text="Použiť filter", command=lambda: refresh_log_window(state, win, f_val=filter_var.get())).pack(side='left')
    ttk.Button(f_mid, text="❌ Zrušiť filter", command=lambda: refresh_log_window(state, win, f_val="")).pack(side='left', padx=2)

    # Treeview Detailov
    cols = ('time', 'sym', 'act', 'qty', 'price', 'comm', 'total', 'pl', 'note', 'id')
    tree = ttk.Treeview(win, columns=cols, show='headings', selectmode='browse')
    
    tree.heading('time', text='Čas'); tree.column('time', width=140)
    tree.heading('sym', text='Symbol'); tree.column('sym', width=60)
    tree.heading('act', text='Akcia'); tree.column('act', width=50)
    tree.heading('qty', text='Ks'); tree.column('qty', width=50)
    tree.heading('price', text='Cena'); tree.column('price', width=70)
    tree.heading('comm', text='Poplatok'); tree.column('comm', width=70)
    tree.heading('total', text='Celkom ($)'); tree.column('total', width=90)
    tree.heading('pl', text='P/L Skalpu'); tree.column('pl', width=90)
    tree.heading('note', text='Poznámka (klik pre úpravu)'); tree.column('note', width=150)
    tree.heading('id', text='ID'); tree.column('id', width=0, stretch=False)
    
    tree.pack(fill='both', expand=True, padx=5, pady=5)

    # Predvýpočet P/L pre každý jeden skalp (chronologicky)
    pl_map = {}
    temp_summary = {}
    for e in log:
        sym = e['symbol']
        if sym not in temp_summary: temp_summary[sym] = {'qty': 0.0, 'avg_cost': 0.0}
        ts = temp_summary[sym]
        eid = e.get('id')
        try:
            q = float(e.get('qty', 0))
            p = float(e.get('price', 0))
            if math.isnan(p): p = 0.0
            c = float(e.get('commission', 0))
            if math.isnan(c): c = 0.0
            
            action = e.get('action', 'BUY')
            e_pl = 0.0
            
            if action == 'BUY':
                if ts['qty'] < 0: # Zatváranie shortu
                    closed_q = min(q, abs(ts['qty']))
                    e_pl = closed_q * (ts['avg_cost'] - p)
                    ts['qty'] += q
                    if ts['qty'] > 0: ts['avg_cost'] = p
                else: # Otváranie longu
                    new_q = ts['qty'] + q
                    ts['avg_cost'] = (ts['qty'] * ts['avg_cost'] + q * p) / new_q if new_q > 0 else 0
                    ts['qty'] = new_q
            else: # SELL
                if ts['qty'] > 0: # Zatváranie longu
                    closed_q = min(q, ts['qty'])
                    e_pl = closed_q * (p - ts['avg_cost'])
                    ts['qty'] -= q
                    if ts['qty'] < 0: ts['avg_cost'] = p
                else: # Otváranie shortu
                    new_q = ts['qty'] - q
                    ts['avg_cost'] = (abs(ts['qty']) * ts['avg_cost'] + q * p) / abs(new_q) if new_q != 0 else 0
                    ts['qty'] = new_q
            pl_map[eid] = e_pl - c
        except: pl_map[eid] = 0.0
    
    for e in reversed(log):
        if curr_f and curr_f not in e['symbol'].upper(): continue
        try:
            q = float(e.get('qty', 0))
            p = float(e.get('price', 0))
            c = float(e.get('commission', 0))
            if math.isnan(p): p = 0.0
            total = q * p
            e_pl = pl_map.get(e.get('id'), 0.0)
            
            item_id = tree.insert('', tk.END, values=(
                e['timestamp'], e['symbol'], e['action'], f"{q:.0f}", 
                f"{p:.2f}", f"{c:.2f}", f"{total:.2f}", f"{e_pl:+.2f} $", 
                e.get('note', ''), e.get('id', '')
            ))
            
            # Farebné odlíšenie riadku podľa P/L
            if e_pl > 0.01: tree.item(item_id, tags=('plus',))
            elif e_pl < -0.01: tree.item(item_id, tags=('minus',))
            
        except: pass

    # Tagy pre detailný denník
    tree.tag_configure('plus', foreground='green')
    tree.tag_configure('minus', foreground='red')

    # Context Menu a Actions
    f_bot = ttk.Frame(win); f_bot.pack(fill='x', padx=5, pady=5)
    
    def on_delete():
        sel = tree.selection()
        if not sel: return
        item = tree.item(sel[0])
        lid = item['values'][9] # Index 9 je ID
        delete_scalp_entry(lid, state, win)

    def on_delete_sym():
        sel = tree.selection()
        if not sel: 
            sym = filter_var.get().upper()
            if not sym: return messagebox.showwarning("Chyba", "Vyberte riadok alebo zadajte filter pre zmazanie skupiny.")
        else:
            sym = tree.item(sel[0])['values'][1]
        delete_scalps_by_symbol(sym, state, win)
        
    def on_edit_note(event):
        item_id = tree.identify_row(event.y)
        col = tree.identify_column(event.x)
        if not item_id or col != '#9': return # Index 8 (stĺpec #9) je poznámka
        
        curr_vals = tree.item(item_id)['values']
        old_note = curr_vals[8]
        lid = curr_vals[9]
        
        new_note = tk.simpledialog.askstring("Poznámka", "Upraviť poznámku:", initialvalue=old_note, parent=win)
        if new_note is not None:
            update_scalp_note(lid, new_note, state, win)
            new_v = list(curr_vals)
            new_v[8] = new_note
            tree.item(item_id, values=new_v)

    tree.bind('<Double-1>', on_edit_note)
    
    ttk.Button(f_bot, text="🗑️ Vymazať riadok", command=on_delete).pack(side='left', padx=5)
    ttk.Button(f_bot, text="🗑️ Vymazať všetko pre Symbol", command=on_delete_sym).pack(side='left', padx=5)
    ttk.Button(f_bot, text="🔄 Obnoviť", command=lambda: refresh_log_window(state, win)).pack(side='right', padx=5)
    
    # Bind filter refresh
    # filter_var.trace_add('write', lambda *a: ... ) - radšej tlačidlo pre jednoduchosť

def show_scalp_log(state):
    import tkinter.simpledialog # Import tu aby bol dostupný
    win = tk.Toplevel(state.root); win.title("Denník Skalpov"); win.geometry("800x500")
    refresh_log_window(state, win)

# --- LOGIKA ---

def find_strangle_gs(state):
    symbol, expiry, target, port = state.symbol_var.get().strip().upper(), state.calc_short_expiry_var.get(), state.gs_target_delta_var.get(), state.port_var.get()
    if not symbol or not expiry: return messagebox.showwarning("Chyba", "Zadajte dáta.")
    
    # RESET predchádzajúcich výsledkov
    update_gs_analysis_text(state, "Hľadám opcie...\n")
    if hasattr(state, 'gamma_theory_label'):
        state.gamma_theory_label.config(text="Γ/Θ: —", bg="gray")
    
    # Progress Bar pre jeden dátum
    if hasattr(state, 'gs_scan_progress'):
        state.gs_scan_progress.pack_forget()
        state.gs_scan_progress.pack(fill='x', pady=(5, 0))
        state.gs_scan_progress['maximum'] = 100
        state.gs_scan_progress['value'] = 5  # Začni na 5 % nech je vidno pohyb
        state.root.update_idletasks()  # okamžité prekreslenie

        def fake_progress(current=5):
            if state.gs_scan_progress.winfo_ismapped() and current < 95:
                step = max(1, (95 - current) / 20)
                state.gs_scan_progress['value'] = current + step
                state.root.after(200, lambda: fake_progress(current + step))

        state.root.after(200, lambda: fake_progress())

    def run():
        try:
            py = sys.executable; scr = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'scripts', 'tws_strangle_finder.py')
            cmd = [py, scr, '--symbol', symbol, '--expiry', expiry, '--delta-target', target, '--port', str(port)]
            if state.gs_model_priority_var.get(): cmd.append('--model-priority')
            
            # PRIDANÉ: Manuálne striky
            c_strike = state.gs_manual_call_strike_var.get().strip()
            p_strike = state.gs_manual_put_strike_var.get().strip()
            if c_strike: cmd.extend(['--call-strike', c_strike])
            if p_strike: cmd.extend(['--put-strike', p_strike])
            
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=90, cwd=os.getcwd())
            
            # Skryť progress bar po dokončení
            state.root.after(0, lambda: state.gs_scan_progress.pack_forget() if hasattr(state, 'gs_scan_progress') else None)

            if res.returncode == 0 and res.stdout:
                try:
                    data = json.loads(res.stdout.strip())
                    if data.get('success'):
                        candidates = data.get('candidates', [])
                        if not candidates:
                            update_gs_analysis_text(state, f"❌ Chyba: Nenašli sa žiadne vhodné opcie pre túto expiráciu.\n\nSTDERR:\n{res.stderr}")
                            return
                        
                        # LOGIKA VÝBERU: Hľadáme kandidáta, ktorého cieľová delta je najbližšia k tomu, čo zadal užívateľ
                        try:
                            user_target = float(target)
                        except:
                            user_target = 0.30
                            
                        # Zoradíme kandidátov podľa toho, ako blízko sú k užívateľovmu targetu
                        best = sorted(candidates, key=lambda c: abs(c['target'] - user_target))[0]
                        
                        stats = best['stats']; gt = stats['totalGamma']/abs(stats['totalTheta']) if abs(stats['totalTheta'])>0 else 0
                        sent, col, ico = get_semafor_data(state, gt)
                        
                        # VÝPOČET VOLATILITY
                        hv = stats.get('hv20d', 0)
                        iv = stats.get('avgIV', 0)
                        iv_hv_ratio = iv / hv if hv > 0 else 0
                        
                        # VÝPOČET DENNÉHO BREAK-EVEN POHYBU
                        be_move = 0
                        rec_drift = 0.15 # Default
                        if stats['totalGamma'] > 0:
                            be_move = math.sqrt(2 * abs(stats['totalTheta']) / stats['totalGamma'])
                            # Odporúčaný drift tol: koľko delty sa "nazbiera" pri pohybe o break-even cenu
                            rec_drift = be_move * stats['totalGamma']
                            # Zaokrúhliť na "pekné" číslo (0.10, 0.15, 0.20...)
                            rec_drift = round(rec_drift * 20) / 20 
                            if rec_drift < 0.05: rec_drift = 0.10
                            if rec_drift > 0.40: rec_drift = 0.40
                        
                        # KONTROLA EARNINGS
                        earnings_info = ""
                        e_date = state.get_earnings_date(symbol)
                        if e_date:
                            try:
                                # Prevod na date objekt ak je to datetime
                                e_date_only = e_date.date() if hasattr(e_date, 'date') else e_date
                                days_to_e = (e_date_only - datetime.now().date()).days
                                if days_to_e >= 0:
                                    status_e = "⚠️ BLÍZKO" if days_to_e <= 7 else "OK"
                                    earnings_info = f"║  📅 EARNINGS: {e_date_only.strftime('%d.%m.%Y')} ({days_to_e} dní) - {status_e:8}      ║"
                                    
                                    # Kontrola či sú výsledky pred expiráciou
                                    exp_dt = datetime.strptime(expiry, "%Y%m%d")
                                    if e_date_only <= exp_dt.date():
                                        earnings_info = f"║  🚨 RIZIKO: EARNINGS ({e_date_only.strftime('%d.%m')}) SÚ PRED EXPIRÁCIOU! 🚨 ║"
                            except: pass

                        calc_time = datetime.now().strftime("%d.%m.%Y %H:%M:%S")
                        
                        # Nastaviť striky pre objednávkový modul
                        def update_ui_and_vars():
                            state.gamma_theory_label.config(text=f"Γ/Θ: {gt:.4f} | {sent} {ico}", bg=col)
                            state.calc_short_strike_var.set(str(best['callLeg']['strike']))
                            state.calc_long_strike_var.set(str(best['putLeg']['strike']))
                        
                        state.root.after(0, update_ui_and_vars)
                        
                        lines = [
                            "╔" + "═"*66 + "╗",
                            "║               🧘 GAMMA SCALPER SETUP (Long Strangle)             ║",
                            "╠" + "═"*66 + "╣",
                            f"║  Symbol: {symbol:10}    Expiry: {expiry:10}    Cena: ${stats['underlyingPrice']:.2f}     ║",
                            f"║  Vypočítané: {calc_time:40}            ║",
                            "╠" + "═"*66 + "╣"
                        ]
                        if earnings_info:
                            lines.extend([earnings_info, "╠" + "═"*66 + "╣"])
                            
                        lines.extend([
                            f"║  IV (Implikovaná): {iv*100:6.2f}% | HV (Hist. 20d): {hv*100:6.2f}%             ║",
                            f"║  POMER IV/HV:      {iv_hv_ratio:6.2f}  ({'LACNÉ' if iv_hv_ratio < 1 else 'DRAHÉ'})                  ║",
                            "╠" + "═"*66 + "╣",
                            "║  KANDIDÁTI (všetky delty):                                       ║"
                        ])
                        for c in sorted(data['candidates'], key=lambda x: x['target']):
                            r = c['stats']['totalGamma'] / abs(c['stats']['totalTheta']) if abs(c['stats']['totalTheta']) > 0 else 0
                            _, _, ci = get_semafor_data(state, r)
                            lines.append(f"║  Δ~{c['target']:.2f}: C {c['callLeg']['strike']:.1f}  P {c['putLeg']['strike']:.1f}  GT={r:.3f} {ci:2} ║")
                        
                        lines.extend([
                            "╠" + "═"*66 + "╣",
                            f"║  🔥 POMER Γ/Θ: {gt:.4f} ({sent.upper()}) {ico:2}           ║",
                            f"║  📈 DENNÝ BREAK-EVEN POHYB: {be_move:.2f} USD ({((be_move/stats['underlyingPrice'])*100):.2f}%)      ║",
                            f"║  🎯 ODPORÚČANÝ DRIFT TOL:   {rec_drift:.2f} Δ                         ║",
                            "╠" + "═"*66 + "╣",
                            f"║  🟢 CALL: Strike {best['callLeg']['strike']:.1f} | Δ {best['callLeg']['delta']:+.3f} | Θ {best['callLeg'].get('theta', 0):+.3f}     ║",
                            f"║  🟢 PUT:  Strike {best['putLeg']['strike']:.1f} | Δ {best['putLeg']['delta']:+.3f} | Θ {best['putLeg'].get('theta', 0):+.3f}     ║",
                            "╠" + "═"*66 + "╣",
                            f"║  Net Delta:   {stats['netDelta']:+.3f}  | Gamma: {stats['totalGamma']:.5f}           ║",
                            f"║  Total Theta: {stats['totalTheta']:.3f}  | Cost:  ${stats['totalCost']:.2f}           ║",
                            "╚" + "═"*66 + "╝"
                        ])
                        update_gs_analysis_text(state, "\n".join(lines))
                        update_gs_status(state, f"✓ {sent}", col)
                except Exception as e:
                    import traceback
                    err_details = traceback.format_exc()
                    update_gs_analysis_text(state, f"❌ Chyba spracovania dát:\n{e}\n\nDetaily:\n{err_details}")
            else:
                err_msg = res.stderr if res.stderr else "Neznáma chyba (žiaden výstup)."
                update_gs_analysis_text(state, f"❌ Skript zlyhal (kód {res.returncode}):\n\n{err_msg}")
        except Exception as e: 
            state.root.after(0, lambda: state.gs_scan_progress.pack_forget() if hasattr(state, 'gs_scan_progress') else None)
            update_gs_analysis_text(state, f"❌ Výnimka: {e}")
    threading.Thread(target=run, daemon=True).start()

def scan_all_expiries_gs(state):
    symbol, target, port = state.symbol_var.get().strip().upper(), state.gs_target_delta_var.get(), state.port_var.get()
    if not symbol: return messagebox.showwarning("Chyba", "Zadajte symbol.")
    
    # RESET predchádzajúcich výsledkov
    if hasattr(state, 'gamma_theory_label'):
        state.gamma_theory_label.config(text="Γ/Θ: —", bg="gray")
    
    # Získame expirácie z comboboxu (ak sú načítané)
    expiries = list(state.gs_expiry_combo['values'])
    if not expiries: 
        return messagebox.showwarning("Chyba", "Najprv kliknite na 'Načítať Expirácie'.")

    # Obmedzíme na prvých 15 expirácií, aby to netrvalo večne (často ich je 50+)
    # Alebo radšej len tie najbližšie
    expiries = expiries[:12] 
    
    update_gs_analysis_text(state, f"🚀 SKENUJEM {len(expiries)} EXPIRÁCIÍ PRE {symbol}...\n(Môže to trvať 1-2 minúty, prosím čakajte)\n")
    
    # Zobraziť a resetovať progress bar
    if hasattr(state, 'gs_scan_progress'):
        state.gs_scan_progress.pack_forget()
        state.gs_scan_progress.pack(fill='x', pady=(5, 0))
        state.gs_scan_progress['maximum'] = 100
        state.gs_scan_progress['value'] = 5
        state.root.update_idletasks()
        def fake_progress(current=5):
            if state.gs_scan_progress.winfo_ismapped() and current < 95:
                step = max(1, (95 - current) / 15)
                state.gs_scan_progress['value'] = current + step
                state.root.after(400, lambda: fake_progress(current + step))
        state.root.after(200, lambda: fake_progress())
    
    def run():
        try:
            py = sys.executable; root = os.path.dirname(os.path.dirname(__file__))
            scr = os.path.join(root, 'scripts', 'tws_strangle_finder.py')
            exp_str = ",".join(expiries)
            
            cmd = [py, scr, '--symbol', symbol, '--expiry', exp_str, '--delta-target', target, '--port', str(port)]
            if state.gs_model_priority_var.get(): cmd.append('--model-priority')
            
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=420, cwd=root)
            
            # Po dokončení skryť progress bar
            state.root.after(0, lambda: state.gs_scan_progress.pack_forget() if hasattr(state, 'gs_scan_progress') else None)

            if res.returncode == 0:
                data = json.loads(res.stdout)
                if data.get('success'):
                    candidates = data.get('candidates', [])
                    
                    # 1. Zoskupiť kandidátov podľa expirácie a vybrať pre každú expiráciu toho NAJLEPŠIEHO
                    best_by_expiry = {}
                    for c in candidates:
                        exp = c['expiry']
                        stats = c['stats']
                        gt = stats['totalGamma'] / abs(stats['totalTheta']) if abs(stats['totalTheta']) > 0 else 0
                        
                        # Ak už máme kandidáta pre túto expiráciu, porovnáme GT a necháme lepšieho
                        if exp not in best_by_expiry or gt > best_by_expiry[exp]['gt']:
                            best_by_expiry[exp] = {'gt': gt, 'candidate': c}

                    # 2. Vytvoriť zoznam a zoradiť podľa GT ratio (od najlepšieho)
                    results = []
                    for exp, item in best_by_expiry.items():
                        results.append((exp, item['gt'], item['candidate']))
                    
                    results.sort(key=lambda x: x[1], reverse=True)
                    
                    lines = [
                        f"📊 SKENER VÝSLEDKY PRE {symbol} (Zoradené podľa Γ/Θ):",
                        "="*60,
                        f"{'EXPIRÁCIA':12} | {'POMER Γ/Θ':10} | {'STAV':12}",
                        "-"*60
                    ]
                    
                    count_ok = 0
                    for exp, gt, c in results:
                        sent, _, ico = get_semafor_data(state, gt)
                        # FILTER: Zobrazujeme len ak je aspoň 'Stop' (aby sme videli aj tesné), 
                        # ale 'Silný stop' (pod 1.5 alebo 0) môžeme voliteľne skryť.
                        # Užívateľ chcel: "stačí ak to bude len nákup a lepšie" -> Dajme filter na Neutrál (>= 3.0)
                        
                        # Prehľadnosť: Zobrazíme všetko od "Neutrál" vyššie.
                        # Ak je gt < 3.0, nezobrazíme to v hlavnom zozname (alebo len ako info na konci)
                        if gt >= 3.0: 
                             lines.append(f"{exp:12} | {gt:10.4f} | {sent} {ico}")
                             count_ok += 1
                    
                    if count_ok == 0:
                         lines.append("   (Žiadne expirácie nespĺňajú kritérium >= Neutrál 3.0)")
                         # Fallback: zobrazíme aspoň top 3 najlepšie, aj keď sú slabé
                         lines.append("-"*60)
                         lines.append("   Top 3 dostupné (aj keď slabé):")
                         for i in range(min(3, len(results))):
                             exp, gt, c = results[i]
                             sent, _, ico = get_semafor_data(state, gt)
                             lines.append(f"{exp:12} | {gt:10.4f} | {sent} {ico}")

                    lines.append("="*60)
                    lines.append("\n💡 Vyberte najlepšiu expiráciu v menu a kliknite na 'NÁJSŤ OPTIMÁLNY STRANGLE' pre detail.")
                    
                    update_gs_analysis_text(state, "\n".join(lines))
                    update_gs_status(state, f"Sken hotový: {len(results)} exp.")
                else:
                    update_gs_analysis_text(state, f"❌ Sken zlyhal: {data.get('error')}")
            else:
                update_gs_analysis_text(state, f"❌ Skript zlyhal (kód {res.returncode})")
        except Exception as e:
            state.root.after(0, lambda: state.gs_scan_progress.pack_forget() if hasattr(state, 'gs_scan_progress') else None)
            update_gs_analysis_text(state, f"❌ Výnimka pri skenovaní: {e}")
            
    threading.Thread(target=run, daemon=True).start()

def update_stats_ui(state, symbol=None):
    if hasattr(state, 'gs_scalp_stats_label'):
        c, cf = get_scalp_stats(symbol)
        col = "green" if cf > 0 else "red" if cf < 0 else "blue"
        state.gs_scalp_stats_label.config(text=f"Skalpy: {c} | Cash Flow: ${cf:+.2f}", foreground=col)

def check_position_gs(state):
    # Získame vybrané symboly z monitora + automaticky symboly z vlastných párov
    selected_monitor_symbols = [sym for sym, var in state.monitor_selected_symbols.items() if var.get()]
    for pair_data in state.custom_pairs.values():
        pair_syms = pair_data.get('symbols', []) if isinstance(pair_data, dict) else pair_data
        for ps in pair_syms:
            if ps not in selected_monitor_symbols:
                selected_monitor_symbols.append(ps)

    # Ak nie sú vybrané žiadne symboly v monitore ani v pároch, tak monitorujeme všetko
    if not selected_monitor_symbols:
        selection = state.gs_active_sym_combo.get().strip()
        is_multi = selection == "--- VŠETKO (MULTI) ---" or not selection
        active_sym = None if is_multi else selection.upper()
    else:
        # Ak sú vybrané symboly v monitore, tak monitorujeme iba tie
        is_multi = True # V tomto kontexte to bude vždy multi, lebo je to výber viacerých
        active_sym = None

    port = state.port_var.get()
    
    def run():
        watcher_rows = []
        try:
            py = sys.executable; root = os.path.dirname(os.path.dirname(__file__))
            scr = os.path.join(root, 'scripts', 'tws_manual_test.py')
            res = subprocess.run([py, scr, '--mode', 'positions'], env={**os.environ, 'TWS_PORT': str(port)}, capture_output=True, text=True, timeout=60, cwd=root)
            
            if res.returncode == 0:
                pos_data_raw = json.loads(res.stdout).get('positions', [])
                
                # Filter pozícií na základe vybraných symbolov z monitora
                if selected_monitor_symbols:
                    pos_data = [p for p in pos_data_raw if p.get('symbol') in selected_monitor_symbols]
                else:
                    pos_data = pos_data_raw

                portfolio = {}
                
                # Zoskupenie portfólia podľa symbolu a expirácie
                for p in pos_data:
                    sym = p.get('symbol')
                    if not sym: continue
                    exp = p.get('expiry') or "STK"
                    if sym not in portfolio: portfolio[sym] = {}
                    if exp not in portfolio[sym]: portfolio[sym][exp] = []
                    # Ignorovať BAG ak máme jednotlivé nohy (TWS špecifikum)
                    if p.get('secType') == 'BAG' and len(pos_data) > 1: continue 
                    portfolio[sym][exp].append(p)

                # Uložiť pre ostatné moduly
                state.last_portfolio_data = portfolio
                
                # --- PRÍPRAVA DÁT PRE SWING WATCHER ---
                target_opt_pct = 50.0
                target_stk_usd = 12.0
                try:
                    target_opt_pct = float(state.monitor_profit_target_pct.get())
                    target_stk_usd = float(state.monitor_stock_profit_target_usd.get())
                except: pass

                timestamp = datetime.now().strftime("%H:%M:%S")
                final_report = [f"📊 MONITORING PORTFÓLIA ({timestamp})", "="*55]
                
                all_drifts = []
                
                # Spracujeme každý symbol v portfóliu
                for sym in sorted(portfolio.keys()):
                    # Symboly z vlastných párov (cross-hedge)
                    is_in_custom_pair = any(sym in (p.get('symbols', []) if isinstance(p, dict) else p) for p in state.custom_pairs.values())

                    # BEZPEČNOSTNÝ FILTER: Ignorovať symboly bez opcií (čisté akcie),
                    # OKREM tých, ktoré sú súčasťou vlastného páru
                    has_options = any(exp != "STK" for exp in portfolio[sym].keys())
                    if not has_options and not is_in_custom_pair:
                        continue
                        
                    # Ak nie sme v multi režime, spracujeme roboticky len vybraný symbol, 
                    # ale ostatné stále skontrolujeme pre status bar
                    should_display = is_multi or sym == active_sym
                    
                    symbol_net_delta = 0
                    symbol_gamma = 0
                    symbol_theta = 0
                    
                    sym_report = [f"\n📦 SYMBOL: {sym}"]
                    
                    # Prechádzame expirácie pre tento symbol
                    for exp in sorted(portfolio[sym].keys()):
                        e_delta, e_gamma, e_theta = 0, 0, 0
                        
                        for p in portfolio[sym][exp]:
                            pos = float(p.get('position', 0))
                            d = p.get('delta') or 0
                            g = p.get('gamma') or 0
                            t = p.get('theta') or 0
                            
                            # Účtovné dáta pre Watchera
                            unr_pl = float(p.get('unrealizedPNL', 0))
                            avg_cost = float(p.get('avgCost', 0))
                            mkt_price = float(p.get('marketPrice', 0))
                            st = p.get('secType', 'STK')

                            # Výpočet zisku pre Watcher (rovnaká logika ako v Monitore)
                            pl_display = ""
                            is_target = False
                            is_warning = False
                            pl_pct = 0.0 # Inicializácia
                            
                            # KRÍŽOVÁ KONTROLA (Cross-Check) proti TWS
                            is_verified = False
                            calc_pnl = 0.0
                            if st == 'OPT':
                                # TWS avgCost pre opcie už obsahuje multiplikátor 100
                                avg_price_share = avg_cost / 100.0
                                calc_pnl = (mkt_price - avg_price_share) * pos * 100.0
                                
                                if pos < 0 and avg_cost > 0:
                                    # Prijatá prémia (max profit) = abs(pos) * avg_cost
                                    max_profit = abs(pos) * avg_cost
                                    pl_pct = (unr_pl / max_profit) * 100.0 if max_profit > 0 else 0
                                elif pos > 0 and avg_cost > 0:
                                    # Náklady = pos * avg_cost
                                    cost_basis = pos * avg_cost
                                    pl_pct = (unr_pl / cost_basis) * 100.0 if cost_basis > 0 else 0
                                
                                pl_display = f"{pl_pct:.1f} %"
                                target_display = f"{target_opt_pct:.0f} %"
                                is_target = pl_pct >= target_opt_pct
                                is_warning = pl_pct >= float(state.monitor_profit_warning_pct.get())
                                
                                # Overenie (tolerancia 1% alebo 0.50$ kvôli poplatkom)
                                if abs(calc_pnl - unr_pl) < (abs(unr_pl) * 0.01 + 0.50):
                                    is_verified = True
                                
                                # Zobrazenie avg ceny za share pre opcie
                                display_avg = f"{avg_price_share:.2f}"
                            else: # STK
                                calc_pnl = (mkt_price - avg_cost) * pos
                                # Výpočet % aj pre akcie pre kompatibilitu so Swing Watcherom
                                if abs(pos) > 0 and avg_cost > 0:
                                    cost_basis = abs(pos) * avg_cost
                                    pl_pct = (unr_pl / cost_basis) * 100.0

                                pl_display = f"{unr_pl:+.2f} $"
                                target_display = f"{target_stk_usd:+.1f} $"
                                is_target = unr_pl >= target_stk_usd
                                is_warning = unr_pl >= (target_stk_usd * 0.5)
                                
                                if abs(calc_pnl - unr_pl) < (abs(unr_pl) * 0.01 + 0.10):
                                    is_verified = True
                                display_avg = f"{avg_cost:.2f}"

                            if st == 'OPT':
                                exp_raw = str(p.get('expiry', ''))
                                try:
                                    # Prevod YYYYMMDD na "Jun 30"
                                    dt = datetime.strptime(exp_raw, "%Y%m%d")
                                    months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
                                    exp_fmt = f"{months[dt.month-1]} {dt.day:02d}"
                                    desc = f"{exp_fmt} {p.get('right','')}{p.get('strike','')}"
                                except:
                                    desc = f"{exp_raw} {p.get('right','')}{p.get('strike','')}"
                            else:
                                desc = "AKCIE"

                            watcher_rows.append({
                                'sym': sym, 'desc': desc, 'pos': f"{pos:+.0f}",
                                'price': f"{mkt_price:.2f}", 'avg': display_avg,
                                'pl_usd': f"{unr_pl:+.2f} $", 'pl_display': pl_display,
                                'target_display': target_display, 'is_target': is_target,
                                'is_warning': is_warning, 'is_loss': unr_pl < 0,
                                'is_verified': is_verified, 'secType': st,
                                'raw_pl_usd': unr_pl, 'raw_pl_pct': pl_pct
                            })

                            val_d = d * pos if p.get('secType') == 'OPT' else (pos / 100.0)
                            e_delta += val_d
                            e_gamma += (g * pos) if p.get('secType') == 'OPT' else 0
                            e_theta += (t * pos) if p.get('secType') == 'OPT' else 0
                            
                            if should_display and not is_multi:
                                sym_report.append(f" • {p.get('right','STK')} {p.get('strike','')} x{pos:.0f} | Δ {d:+.3f}")
                        
                        symbol_net_delta += e_delta
                        symbol_gamma += e_gamma
                        symbol_theta += e_theta
                    
                    # Výpočet efektivity (len pre opcie)
                    gt = symbol_gamma / abs(symbol_theta) if abs(symbol_theta) > 0 else 0
                    _, _, ico = get_semafor_data(state, gt)
                    
                    # KONTROLA EARNINGS PRE ROBOTA
                    days_to_e = 999
                    e_warning = ""
                    e_date = state.get_earnings_date(sym)
                    if e_date:
                        try:
                            e_date_only = e_date.date() if hasattr(e_date, 'date') else e_date
                            days_to_e = (e_date_only - datetime.now().date()).days
                            if 0 <= days_to_e <= 2:
                                e_warning = f"⚠️ EARNINGS ZA {days_to_e} DNÍ!"
                        except: pass

                    # KONTROLA DIVIDEND (Early Exercise)
                    div_warning = ""
                    div_info = state.get_dividend_info(sym)
                    if div_info and div_info.get('rate', 0) > 0 and div_info.get('ex_date'):
                        try:
                            ex_date = div_info['ex_date']
                            days_to_div = (ex_date - datetime.now().date()).days
                            
                            # Ak je ex-div date dnes alebo zajtra (0 alebo 1 deň)
                            if 0 <= days_to_div <= 1:
                                div_rate = div_info['rate']
                                # Získame cenu podkladu
                                stock_price = 0
                                if 'STK' in portfolio[sym]:
                                    for p in portfolio[sym]['STK']:
                                        if p.get('marketPrice'): stock_price = float(p['marketPrice'])
                                        elif p.get('lastPrice'): stock_price = float(p['lastPrice'])
                                
                                # Prechádzame opcie a hľadáme Long Calls na exercise
                                for exp_key in portfolio[sym]:
                                    if exp_key == "STK": continue
                                    for p in portfolio[sym][exp_key]:
                                        if p.get('right') == 'C' and float(p.get('position', 0)) > 0:
                                            strike = float(p.get('strike', 0))
                                            opt_price = float(p.get('marketPrice') or p.get('lastPrice') or 0)
                                            
                                            if stock_price > 0 and strike > 0 and opt_price > 0:
                                                intrinsic = max(0, stock_price - strike)
                                                extrinsic = opt_price - intrinsic
                                                
                                                # Ak je dividenda väčšia ako časová hodnota -> Exercise!
                                                if div_rate > extrinsic:
                                                    div_warning = f"🎁 DIV ALERT: Exercise {sym} (Div ${div_rate:.2f} > Extr ${extrinsic:.2f})"
                                                    break
                        except Exception as de:
                            print(f"DEBUG: Dividend check error for {sym}: {de}")

                    # Drift Tolerance a Cieľová Delta
                    drift_tol = 0.20
                    target_delta = 0.0
                    try:
                        # Fallback na globálne nastavenia
                        target_delta = float(state.gs_target_delta_pos_var.get().replace(',', '.'))
                        drift_tol = float(state.gs_drift_tol.get().replace(',', '.'))
                        
                        # Priorita: Ticker-specific nastavenia zo Správcu Driftu
                        if sym in state.ticker_settings:
                            drift_tol = float(state.ticker_settings[sym].get('drift_tolerance', drift_tol))
                            target_delta = float(state.ticker_settings[sym].get('target_delta', target_delta))
                    except: pass
                    
                    current_drift = symbol_net_delta - target_delta
                    has_drift = abs(current_drift) >= drift_tol
                    if has_drift:
                        all_drifts.append(sym)
                    
                    # Získame akciovú pozíciu pre výpočet výnosu
                    stk_pos = 0
                    if 'STK' in portfolio[sym]:
                        stk_pos = sum(float(p.get('position', 0)) for p in portfolio[sym]['STK'])

                    # Robotická časť (Auto-Scalp)
                    robot_status = ""
                    if state.gs_auto_scalp_var.get():
                        # 1. KONTROLA STABILITY TRHU (15 min po Open)
                        stable, stable_msg = is_market_stable(buffer_minutes=15)
                        if not stable:
                            robot_status = f"⏳ {stable_msg}"
                            has_drift = False # Robot v tomto cykle nič neurobí
                        
                        # 2. KONTROLA PLATNOSTI DÁT (Proti NaN a 0.0)
                        elif math.isnan(symbol_net_delta) or math.isnan(symbol_gamma) or symbol_gamma == 0:
                            robot_status = "⚠️ Čakám na Greeks z TWS..."
                            has_drift = False

                        # Robot pracuje buď na všetkom (multi), alebo len na aktívnom symbole
                        elif is_multi or sym == active_sym:
                            # AUTOMATICKÁ BRZDA: Ak sú earnings blízko (0-1 deň), robot neobchoduje
                            if 0 <= days_to_e <= 1:
                                robot_status = "🛑 ROBOT STOP (Earnings blízko)"
                            elif has_drift:
                                shares = int(round(-current_drift * 100))
                                
                                # --- KONTROLA MINIMÁLNEHO VÝNOSU (6x poplatok) ---
                                # Ak už máme nejaké akcie (stk_pos != 0), kontrolujeme výnos
                                if stk_pos != 0:
                                    min_yield_threshold = 6.0  # 6x 1 USD poplatok
                                    if abs(symbol_gamma) > 1e-7:
                                        # Odhad pohybu ceny, ktorý spôsobil tento drift: move = drift / gamma
                                        price_move = abs(current_drift) / symbol_gamma
                                        # Odhadovaný výnos (plocha trojuholníka pod gamou): shares * (move / 2)
                                        est_yield = abs(shares) * (price_move / 2.0)
                                        
                                        if est_yield < min_yield_threshold:
                                            robot_status = f"⏳ SKIP: Malý výnos (${est_yield:.2f} < $6)"
                                            has_drift = False  # Zastavíme obchod pre tento cyklus
                                    else:
                                        # Ak nemáme gammu (napr. len akcie bez opcií), nemôžeme scalpovať
                                        robot_status = "⏳ SKIP: Chýba Gamma"
                                        has_drift = False

                                if has_drift and shares != 0:
                                    try:
                                        profile = state.get_current_profile()
                                        is_live = profile.get('mode') == 'LIVE'
                                        
                                        cmd = [py, os.path.join(root, 'scripts', 'tws_rebalance_stock.py'), 
                                               '--symbol', sym, 
                                               '--quantity', str(shares), 
                                               '--port', str(port)]
                                        
                                        if is_live:
                                            cmd.append('--live')
                                            
                                        rb_res = subprocess.run(cmd, capture_output=True, text=True, timeout=20, cwd=root)
                                        if rb_res.returncode == 0:
                                            rb_data = json.loads(rb_res.stdout)
                                            if rb_data.get('success'): 
                                                robot_status = f"✅ ROBOT: Odoslané {shares:+.0f} ks"
                                                # ZAPÍSAŤ DO DENNÍKA
                                                price = rb_data.get('avgPrice', 0.0)
                                                comm = rb_data.get('commission', 0.0)
                                                action = 'BUY' if shares > 0 else 'SELL'
                                                log_scalp_entry(sym, action, abs(shares), price, commission=comm)
                                                # Aktualizovať štatistiku hneď
                                                state.root.after(0, lambda: update_stats_ui(state, sym if not is_multi else None))
                                            elif rb_data.get('already_exists'): 
                                                robot_status = f"⏳ ROBOT: Order existuje"
                                            else: 
                                                robot_status = f"❌ ROBOT CHYBA: {rb_data.get('error')}"
                                        else: 
                                            robot_status = "❌ ROBOT ZLYHAL"
                                    except Exception as e: 
                                        robot_status = f"❌ ROBOT VÝNIMKA: {e}"
                            else:
                                robot_status = "🤖 ROBOT: OK"
                    
                    # Formátovanie reportu pre tento symbol
                    if should_display:
                        if is_multi:
                            # Kompaktný riadok pre MULTI režim
                            line = f"{sym:6} | Δ {symbol_net_delta:+.3f} (Cieľ {target_delta:+.2f}) | Γ {symbol_gamma:.4f} | Γ/Θ {gt:.2f} {ico} | Tol {drift_tol:.2f}"
                            if robot_status: line += f" | {robot_status}"
                            elif has_drift: line += f" | 🚨 DRIFT {current_drift:+.2f}!"
                            if e_warning: line += f" | {e_warning}"
                            if div_warning: line += f" | {div_warning}"
                            final_report.append(line)
                        else:
                            # Detailný report pre JEDEN symbol
                            sym_report.append(f" 👉 Aktuálna Δ: {symbol_net_delta:+.3f} | Cieľová Δ: {target_delta:+.2f}")
                            sym_report.append(f" 👉 Relatívny Drift: {current_drift:+.3f} | Γ/Θ: {gt:.4f} {ico}")
                            if e_warning: sym_report.append(f" {e_warning}")
                            if div_warning: sym_report.append(f" {div_warning}")
                            if has_drift: sym_report.append(f" 🚨 DRIFT DETEKOVANÝ (>±{drift_tol:.2f})")
                            
                            # Pohyb pre drift
                            if abs(symbol_gamma) > 1e-6:
                                mu = (drift_tol - current_drift) / symbol_gamma
                                md = (-drift_tol - current_drift) / symbol_gamma
                                sym_report.append(f" 📈 Pohyb pre Drift: {md:+.2f} ... {mu:+.2f} USD")
                            
                            if robot_status: sym_report.append(f" {robot_status}")
                            final_report.extend(sym_report)
                            final_report.append("-" * 45)

                # Celkový status bar
                if not portfolio:
                    final_report.append("\n⚠️ Žiadne otvorené pozície v TWS nenájdené.")
                    update_gs_status(state, "Monitor: Prázdne", "gray")
                elif not all_drifts and not any(is_multi or sym == active_sym for sym in portfolio.keys()):
                    # Toto nastane ak máme pozície, ale žiadna neprešla filtrom (len akcie)
                    final_report.append("\nℹ️ V portfóliu sú len čisté akcie.\n   (Robot monitoruje len stratégie s opciami)")
                    update_gs_status(state, "Monitor: OK (Len STK)", "gray")
                elif not all_drifts:
                    update_gs_status(state, "Monitor: OK", "green")
                else:
                    update_gs_status(state, f"DRIFT: {', '.join(all_drifts)}", "orange")
                
                # Ak sme prešli filtrom ale final_report má len hlavičku
                if len(final_report) <= 2 and portfolio:
                     final_report.append("\nℹ️ Žiadne Gamma Scalper stratégie (s opciami) nenájdené.")

                update_gs_monitor_text(state, "\n".join(final_report))
                
                # AKTUALIZÁCIA SWING WATCHERA A HUNTERA
                state.root.after(0, lambda: [
                    update_watcher_tree(state, watcher_rows),
                    # Automaticky zaktualizovať aj Huntera, ak máme referencie
                    getattr(sys.modules.get('modularny.tab_swing_hunter'), 'refresh_hunter')(
                        state, state.hunter_tree, state.hunter_rsi_p, state.hunter_rvi_p, state.hunter_tf_v
                    ) if hasattr(state, 'hunter_tree') else None
                ])
                
                # --- HEARTBEAT & ČAS ---
                def pulse():
                    current_h = state.heartbeat_var.get()
                    new_h = "[ • ]" if "OK" in current_h else "[ OK ]"
                    state.heartbeat_var.set(new_h)
                    state.last_update_time_var.set(f"Aktualizované: {timestamp}")
                    # Uložiť timestamp pre watchdog
                    state.last_monitor_success_time = time.time()
                state.root.after(0, pulse)
                
            # Naplánovať ďalšiu kontrolu
            if state.gs_auto_monitor_var.get(): 
                state.root.after(30000, lambda: check_position_gs(state))
                
        except Exception as e:
            print(f"DEBUG Monitor Error: {traceback.format_exc()}")
            if state.gs_auto_monitor_var.get(): 
                state.root.after(30000, lambda: check_position_gs(state))

    threading.Thread(target=run, daemon=True).start()

def toggle_auto_monitor(state):
    if state.gs_auto_monitor_var.get(): check_position_gs(state)
    else: update_gs_status(state, "OFF", "gray")

def open_analysis_window(state, theory=False):
    win = tk.Toplevel(state.root); win.title("Detailná Analýza"); win.geometry("600x400")
    txt = scrolledtext.ScrolledText(win, font=('Courier', 11)); txt.pack(fill='both', expand=True)
    txt.insert(tk.END, state.gs_result_text.get(1.0, tk.END) if theory else state.gs_monitor_text.get(1.0, tk.END)); txt.config(state='disabled')

def place_order_gs(state):
    symbol, expiry = state.symbol_var.get(), state.calc_short_expiry_var.get()
    c_strike, p_strike = state.calc_short_strike_var.get(), state.calc_long_strike_var.get()
    if not all([symbol, expiry, c_strike, p_strike]) or c_strike == "" or p_strike == "": 
        return messagebox.showwarning("Chyba", "Najprv nájdite optimálny strangle (kliknite na tlačidlo NÁJSŤ...).")
    
    if not messagebox.askyesno("Potvrdiť", f"Kúpiť Strangle Combo pre {symbol}?\nStriky: C {c_strike} | P {p_strike}\nExpirácia: {expiry}"): 
                 return
        
    def run():
        try:
            py = sys.executable; root = os.path.dirname(os.path.dirname(__file__))
            profile = state.get_current_profile()
            is_live = profile.get('mode') == 'LIVE'
            port = state.port_var.get()
            
            cmd = [py, os.path.join(root, 'scripts', 'tws_place_order.py'), 
                   '--symbol', symbol, '--expiry', expiry, 
                   '--call-strike', str(c_strike), '--put-strike', str(p_strike), 
                   '--port', str(port)]
            
            if is_live:
                cmd.append('--live')
                
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=30, cwd=root)
            
            if res.returncode == 0:
                try:
                    data = json.loads(res.stdout)
                    if data.get('success'):
                        messagebox.showinfo("Úspech", f"Objednávka na Strangle {symbol} bola odoslaná do TWS.\nStatus: {data.get('status')}")
                    else:
                        messagebox.showerror("Chyba", f"TWS objednávku neprijal:\n{data.get('error')}")
                except:
                    messagebox.showerror("Chyba", f"Neočakávaná odpoveď od skriptu:\n{res.stdout}")
            else:
                messagebox.showerror("Chyba", f"Skript na odoslanie zlyhal:\n{res.stderr}")
        except Exception as e:
            messagebox.showerror("Chyba", f"Výnimka pri odosielaní: {e}")
            
    threading.Thread(target=run, daemon=True).start()

def create_gs_semafor_tab(parent, state):
    frame = ttk.Frame(parent, padding=15); frame.pack(fill='both', expand=True)
    set_frame = ttk.LabelFrame(frame, text="🚦 Prahové hodnoty Γ/Θ", padding=10); set_frame.pack(fill='x', pady=5)
    r1 = ttk.Frame(set_frame); r1.pack(fill='x', pady=5)
    for l, v in [("Silný nákup >=:", state.gs_strong_buy_threshold_var), ("Nákup >=:", state.gs_buy_threshold_var), ("Neutrál >=:", state.gs_neutral_threshold_var), ("Stop >=:", state.gs_stop_threshold_var)]:
        ttk.Label(r1, text=l).pack(side='left', padx=5); ttk.Entry(r1, textvariable=v, width=6).pack(side='left', padx=5)
    r2 = ttk.Frame(set_frame); r2.pack(fill='x', pady=5)
    ttk.Label(r2, text="Názov Konfig:").pack(side='left', padx=5); ttk.Entry(r2, textvariable=state.gs_semafor_config_name_var, width=20).pack(side='left', padx=5)
    ttk.Button(r2, text="💾 Uložiť", command=state.save_gamma_semafor_config).pack(side='left', padx=20)
    ttk.Button(r2, text="🔄 APLIKOVAŤ", command=state.save_settings_file, style='Accent.TButton').pack(side='right', padx=5)
    arch_frame = ttk.LabelFrame(frame, text="📋 Archív konfigurácií", padding=10); arch_frame.pack(fill='both', expand=True, pady=10)
    cols = ('name', 'sb', 'buy', 'neu', 'stop')
    tree = ttk.Treeview(arch_frame, columns=cols, show='headings')
    for c, n in zip(cols, ['Názov', 'SB', 'Buy', 'Neut', 'Stop']): tree.heading(c, text=n); tree.column(c, width=70, anchor='center')
    tree.pack(side='left', fill='both', expand=True)
    def refresh():
        for i in tree.get_children(): tree.delete(i)
        for n, d in sorted(state.saved_gamma_semafor_configs.items()): tree.insert('', tk.END, values=(n, d.get('strong_buy'), d.get('buy'), d.get('neutral'), d.get('stop')))
    tree.bind('<<TreeviewSelect>>', lambda e: state.gs_semafor_config_name_var.set(tree.item(tree.selection()[0])['values'][0]) or state.load_gamma_semafor_config(state.gs_semafor_config_name_var, auto=True))
    refresh(); state.refresh_gs_semafor_tree = refresh
    ttk.Button(frame, text="🗑️ Vymazať", command=lambda: [state.delete_gamma_semafor_config(state.gs_semafor_config_name_var), refresh()]).pack(pady=5)

def check_monitor_watchdog(state):
    """Sleduje, či sa monitor nezasekol (beží každých 5s)"""
    if state.gs_auto_monitor_var.get():
        last_success = getattr(state, 'last_monitor_success_time', 0)
        now = time.time()
        
        # Ak od poslednej aktualizácie prešlo viac ako 65 sekúnd (interval je 30s)
        if last_success > 0 and (now - last_success) > 65:
            update_gs_status(state, "🛑 MONITOR ZASEKNUTÝ!", "red")
            state.heartbeat_var.set("[ !! ]")
        elif last_success == 0 and state.gs_auto_monitor_var.get():
            # Ešte neprebehla ani jedna úspešná aktualizácia
            update_gs_status(state, "⏳ Čakám na prvé dáta...", "orange")
    
    # Naplánovať ďalšiu kontrolu o 5 sekúnd
    state.root.after(5000, lambda: check_monitor_watchdog(state))

def create_gamma_scalper_tab(parent, state):
    state.gs_notebook = ttk.Notebook(parent); state.gs_notebook.pack(fill='both', expand=True)
    t1 = ttk.Frame(state.gs_notebook); state.gs_notebook.add(t1, text="🔍 Vyhľadávač"); create_gs_finder_tab(t1, state)
    t2 = ttk.Frame(state.gs_notebook); state.gs_notebook.add(t2, text="📂 Archív plánov"); create_gs_archive_tab(t2, state)
    t3 = ttk.Frame(state.gs_notebook); state.gs_notebook.add(t3, text="🤖 Auto-Monitor"); create_gs_monitor_tab(t3, state)
    t4 = ttk.Frame(state.gs_notebook); state.gs_notebook.add(t4, text="🚦 Semafor"); create_gs_semafor_tab(t4, state)
    t5 = ttk.Frame(state.gs_notebook); state.gs_notebook.add(t5, text="🧠 AI Advisor"); create_gs_advisor_tab(t5, state)
    
    # Spustiť watchdog
    state.root.after(5000, lambda: check_monitor_watchdog(state))

def create_gs_advisor_tab(parent, state):
    frame = ttk.Frame(parent, padding=15); frame.pack(fill='both', expand=True)
    
    # Horná časť - Nová konzultácia
    input_frame = ttk.LabelFrame(frame, text="💬 Nová konzultácia / Úvaha", padding=10); input_frame.pack(fill='x', pady=5)
    user_text = scrolledtext.ScrolledText(input_frame, height=5, font=('Arial', 11))
    user_text.pack(fill='x', pady=5)
    user_text.insert(tk.END, "Napr: Rozmýšľam nad akumuláciou AAAU so zaistením cez Gamma Scalping...")
    
    def run_consultation():
        text = user_text.get(1.0, tk.END).strip()
        if not text or "Napr:" in text:
            return messagebox.showwarning("Chyba", "Napíšte prosím svoju úvahu alebo otázku.")
        
        # Simulácia "odborného" pohľadu - v realite by tu mohol byť prompt pre LLM
        # Tu vytvoríme záznam do denníka
        analysis_summary = "AI ODBORNÝ POHĽAD:\n"
        if "AAAU" in text.upper() or "ZLATO" in text.upper():
            analysis_summary += "- Strategická akumulácia AAAU je rozumná pri súčasnej HV (~20%).\n"
            analysis_summary += "- Odporúčam využiť akumulačný mód (Cieľová Delta > 0).\n"
            analysis_summary += "- Pozor na nízku likviditu opcií pri vzdialených strikoch."
        else:
            analysis_summary += "Analýza vašej stratégie vyžaduje hlbší pohľad na Greeks a IV/HV pomer v archíve.\n"
            analysis_summary += "Všeobecne platí: Ak je GT > 3.0 a IV/HV < 1.0, setup je priaznivý."
        
        state.save_consultation(text, analysis_summary)
        refresh_history()
        user_text.delete(1.0, tk.END)
        messagebox.showinfo("Konzultácia", "Vaša úvaha bola uložená do denníka s AI komentárom.")

    ttk.Button(input_frame, text="💡 KONZULTOVAŤ S AI A ULOŽIŤ DO DENNÍKA", command=run_consultation, style='Accent.TButton').pack(pady=5)
    
    # Dolná časť - História (Journal)
    history_frame = ttk.LabelFrame(frame, text="📖 Denník konzultácií a úvah", padding=10); history_frame.pack(fill='both', expand=True, pady=10)
    history_display = scrolledtext.ScrolledText(history_frame, font=('Arial', 10), bg='#f8f9fa')
    history_display.pack(fill='both', expand=True)
    history_display.config(state='disabled')
    
    def refresh_history():
        history_display.config(state='normal')
        history_display.delete(1.0, tk.END)
        for entry in reversed(state.consultations):
            history_display.insert(tk.END, f"📅 {entry['timestamp']}\n", "date")
            history_display.insert(tk.END, f"👤 MOJA ÚVAHA:\n{entry['user']}\n", "user")
            history_display.insert(tk.END, f"🤖 AI KOMENTÁR:\n{entry['ai']}\n", "ai")
            history_display.insert(tk.END, "-"*60 + "\n\n")
        
        history_display.tag_configure("date", foreground="gray", font=('Arial', 9, 'italic'))
        history_display.tag_configure("user", foreground="#2c3e50", font=('Arial', 10, 'bold'))
        history_display.tag_configure("ai", foreground="#27ae60", font=('Arial', 10))
        history_display.config(state='disabled')
        history_display.see(1.0)

    refresh_history()
    state.refresh_advisor_history = refresh_history
    ttk.Button(frame, text="🔄 Obnoviť históriu", command=refresh_history).pack(pady=5)
