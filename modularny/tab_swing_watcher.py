#!/usr/bin/env python3
"""
Záložka: Swing Watcher
Sledovanie nezrealizovaného zisku a automatické zatváranie pozícií (Profit Guard).
"""
import tkinter as tk
from tkinter import ttk, messagebox
import subprocess
import threading
import os
import sys
import time
from datetime import datetime

def execute_auto_close(state, row_data):
    """Zrealizuje zisk na konkrétnej nohe a (voliteľne) reštartuje cyklus"""
    symbol = row_data['sym']
    desc = row_data['desc']
    if not state.monitor_auto_close_var.get(): return

    # 0. Scalping Guard & Duplicita
    sent_key = f"_auto_close_sent_{symbol}_{desc}"
    if getattr(state, sent_key, False):
        return
    
    # Time Cooldown (Scalping Guard)
    now = time.time()
    cooldown_key = f"_last_exit_time_{symbol}"
    last_time = getattr(state, cooldown_key, 0)
    if (now - last_time) < 300: # 5 minút cooldown
        return
    
    setattr(state, sent_key, True)
    setattr(state, cooldown_key, now)

    # BEZPEČNOSTNÁ POISTKA: Len ak sú dáta overené proti TWS
    if not row_data.get('is_verified', False):
        print(f"⚠️ AUTO-CLOSE SKIP: Dáta pre {symbol} nie sú verifikované proti TWS.")
        setattr(state, sent_key, False)
        return

    # 1. ROZHODNUTIE: Zastaviť hedžovanie alebo len zobrať zisk?
    restart_mode = state.monitor_auto_restart_var.get()
    
    if not restart_mode:
        if symbol in state.monitor_selected_symbols:
            state.monitor_selected_symbols[symbol].set(False)
            print(f"🤖 AUTO-STOP: Hedging disabled for {symbol} to lock profit.")
        # Uložíme nastavenia
        state.save_settings_file()
    else:
        print(f"🤖 AUTO-CYCLE: Banking profit for {symbol} and preparing for re-entry...")

    # 2. Vykonáme samotnú realizáciu zisku (Close Order)
    try:
        py = sys.executable
        root = os.path.dirname(os.path.dirname(__file__))
        
        profile = state.get_current_profile()
        is_live = profile.get('mode') == 'LIVE'
        
        portfolio = getattr(state, 'last_portfolio_data', {})
        target_p = None
        
        if symbol in portfolio:
            items = portfolio[symbol]
            if isinstance(items, dict):
                all_positions = []
                for exp_list in items.values(): all_positions.extend(exp_list)
                items = all_positions
            
            for p in items:
                p_desc = f"{p.get('right','')}{p.get('strike','')}" if p.get('secType') == 'OPT' else "AKCIE"
                if p_desc == row_data['desc']:
                    target_p = p
                    break
        
        if not target_p:
            print(f"❌ AUTO-CLOSE Error: Nenašla sa pozícia {row_data['desc']} pre {symbol}.")
            setattr(state, sent_key, False)
            return

        scr = os.path.join(root, 'scripts', 'tws_place_order.py')
        qty = abs(int(float(target_p.get('position', 0))))
        st = target_p.get('secType')
        
        if st == 'OPT':
            action = "BUY" if float(target_p.get('position', 0)) < 0 else "SELL"
            cmd = [py, scr, '--symbol', symbol, '--expiry', str(target_p.get('expiry', '')),
                   '--action', action, '--qty', str(qty), '--port', str(state.port_var.get())]
            if target_p.get('right') == 'C': cmd.extend(['--call-strike', str(target_p.get('strike'))])
            else: cmd.extend(['--put-strike', str(target_p.get('strike'))])
        else:
            scr_stk = os.path.join(root, 'scripts', 'tws_rebalance_stock.py')
            cmd = [py, scr_stk, '--symbol', symbol, '--quantity', str(-int(float(target_p.get('position', 0)))), '--port', str(state.port_var.get())]

        if is_live: cmd.append('--live')

        print(f"🚀 AUTO-EXIT: Sending order to TWS: {' '.join(cmd)}")
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=30, cwd=root)
        
        if res.returncode == 0:
            print(f"✅ TWS Response: {res.stdout}")
            
            if restart_mode and st == 'OPT':
                open_action = "SELL" if action == "BUY" else "BUY"
                open_cmd = [py, scr, '--symbol', symbol, '--expiry', str(target_p.get('expiry', '')),
                            '--action', open_action, '--qty', str(qty), '--port', str(state.port_var.get())]
                if target_p.get('right') == 'C': open_cmd.extend(['--call-strike', str(target_p.get('strike'))])
                else: open_cmd.extend(['--put-strike', str(target_p.get('strike'))])
                if is_live: open_cmd.append('--live')
                
                print(f"🔄 RE-ENTRY: Opening same position for {symbol} at current price...")
                time.sleep(2)
                subprocess.run(open_cmd, capture_output=True, text=True, timeout=30, cwd=root)

            msg = f"Príkaz na {symbol} {row_data['desc']} bol odoslaný."
            if restart_mode: msg += " (Cyklus reštartovaný)"
            else: msg += " (Hedging vypnutý)"
            
            if not getattr(state, '_silent_auto_close', False):
                state.root.after(0, lambda: messagebox.showinfo("Profit Action", msg))
        else:
            print(f"❌ TWS Order Error: {res.stderr}")
            setattr(state, sent_key, False)

    except Exception as e:
        import traceback
        print(f"❌ Auto-Close Exception: {e}\n{traceback.format_exc()}")
        setattr(state, sent_key, False)

def execute_group_auto_close(state, pair_name, pair_rows):
    """Zatvorí VŠETKY pozície v rámci páru naraz"""
    if not state.monitor_auto_close_var.get(): return
    
    sent_key = f"_group_close_sent_{pair_name}"
    if getattr(state, sent_key, False): return
    setattr(state, sent_key, True)
    
    print(f"🚀 GROUP-EXIT: Target reached for {pair_name}. Closing {len(pair_rows)} positions...")
    
    state._silent_auto_close = True
    try:
        for r in pair_rows:
            execute_auto_close(state, r)
        
        state.root.after(0, lambda: messagebox.showinfo("Group Profit Locked", 
            f"Všetky pozície v páre '{pair_name}' boli uzavreté a hedging zastavený."))
    finally:
        state._silent_auto_close = False

# --- LOGIKA PÁROV ---

def add_custom_pair(state, name_var, symbols_var, target_var, opt_target_var, stk_target_var):
    name = name_var.get().strip()
    symbols_raw = symbols_var.get().strip().upper()
    target_usd = target_var.get().strip()
    opt_target = opt_target_var.get().strip()
    stk_target = stk_target_var.get().strip()
    
    if not name or not symbols_raw:
        return messagebox.showwarning("Chyba", "Zadajte názov páru a aspoň jeden symbol.")
    
    symbols = [s.strip() for s in symbols_raw.split(',') if s.strip()]
    if not symbols:
        return messagebox.showwarning("Chyba", "Zadajte platné symboly oddelené čiarkou.")
    
    try:
        t_val = float(target_usd) if target_usd else 0.0
        opt_t = float(opt_target) if opt_target else 0.0
        stk_t = float(stk_target) if stk_target else 0.0
    except:
        return messagebox.showwarning("Chyba", "Ciele (Target) musia byť čísla.")
    
    state.custom_pairs[name] = {
        'symbols': symbols,
        'target_usd': t_val,
        'opt_target_pct': opt_t,
        'stk_target_usd': stk_t
    }
    state.save_settings_file()
    name_var.set("")
    symbols_var.set("")
    target_var.set("")
    opt_target_var.set("")
    stk_target_var.set("")
    refresh_pairs_listbox(state)
    messagebox.showinfo("Úspech", f"Pár '{name}' bol uložený.")

def delete_custom_pair(state, name):
    if not name: return
    if name in state.custom_pairs:
        if messagebox.askyesno("Potvrdiť", f"Naozaj chcete vymazať pár '{name}'?"):
            del state.custom_pairs[name]
            state.save_settings_file()
            refresh_pairs_listbox(state)

def refresh_pairs_listbox(state):
    if not hasattr(state, 'monitor_pairs_listbox'): return
    lb = state.monitor_pairs_listbox
    lb.delete(0, tk.END)
    for name in sorted(state.custom_pairs.keys()):
        data = state.custom_pairs[name]
        if not isinstance(data, dict):
            lb.insert(tk.END, f"{name} ({', '.join(data)})")
            continue
            
        symbols = data.get('symbols', [])
        target = data.get('target_usd', 0)
        opt_t = data.get('opt_target_pct', 0)
        stk_t = data.get('stk_target_usd', 0)
        
        info = f"{name} ({', '.join(symbols)}) | Net: {target}$"
        if opt_t > 0: info += f" | Opt: {opt_t}%"
        if stk_t > 0: info += f" | Stk: {stk_t}$"
        lb.insert(tk.END, info)

def update_watcher_tree(state, rows):
    """Aktualizuje tabuľku Swing Profit Watcher s rozdelením na Páry a Natural skupiny"""
    if not hasattr(state, 'monitor_watcher_tree'): return
    
    tree = state.monitor_watcher_tree
    
    # 0. Uložiť stav rozbalenia
    expanded_items = set()
    for item in tree.get_children():
        if tree.item(item, 'open'):
            expanded_items.add(tree.item(item, 'text'))
        for child in tree.get_children(item):
            if tree.item(child, 'open'):
                expanded_items.add(tree.item(child, 'text'))

    for item in tree.get_children():
        tree.delete(item)
    
    tree.tag_configure('header', background='#cfd8dc', font=('Arial', 10, 'bold'))
    tree.tag_configure('group', background='#eceff1', font=('Arial', 9, 'bold'))
    tree.tag_configure('target', background='#c8e6c9', foreground='black') 
    tree.tag_configure('trailing', background='#bbdefb', foreground='black') 
    tree.tag_configure('warning', background='#fff9c4', foreground='black') 
    tree.tag_configure('loss', foreground='red')
    tree.tag_configure('unverified', foreground='#9e9e9e')
    
    # 1. Rozdelenie dát
    sym_to_pair = {}
    for pair_name, pair_data in state.custom_pairs.items():
        syms = pair_data['symbols'] if isinstance(pair_data, dict) else pair_data
        for s in syms:
            sym_to_pair[s] = pair_name

    symbol_groups = {}
    for r in rows:
        symbol_groups.setdefault(r['sym'], []).append(r)

    custom_pairs_rows = {}
    natural_groups_rows = {}

    for sym, sym_rows in symbol_groups.items():
        pair_name = sym_to_pair.get(sym)
        if pair_name:
            custom_pairs_rows.setdefault(pair_name, []).extend(sym_rows)
        else:
            natural_groups_rows[sym] = sym_rows

    # --- FUNKCIA NA VLOŽENIE SKUPINY ---
    def insert_group(parent, name, group_rows, is_custom=False):
        stk_pl = 0.0
        opt_pl = 0.0
        is_any_unverified = False
        pair_target = 0.0
        p_opt_target = 0.0
        p_stk_target = 0.0
        
        if is_custom:
            p_config = state.custom_pairs.get(name, {})
            pair_target = p_config.get('target_usd', 0.0) if isinstance(p_config, dict) else 0.0
            p_opt_target = p_config.get('opt_target_pct', 0.0) if isinstance(p_config, dict) else 0.0
            p_stk_target = p_config.get('stk_target_usd', 0.0) if isinstance(p_config, dict) else 0.0

        for pr in group_rows:
            try:
                val = float(pr['pl_usd'].replace('$', '').replace(' ', '').replace('+', ''))
                if pr.get('secType') == 'STK': stk_pl += val
                else: opt_pl += val
            except: pass
            if not pr.get('is_verified'): is_any_unverified = True
        
        total_pl = stk_pl + opt_pl
        pl_summary = f"STK: {stk_pl:+.1f}$ | OPT: {opt_pl:+.1f}$ | NET: {total_pl:+.2f}$"
        
        is_group_target = False
        is_group_trailing = False
        
        if is_custom and pair_target > 0:
            peak_key = f"pair_{name}"
            if total_pl >= pair_target:
                is_group_trailing = True
                current_peak = state.trailing_peaks.get(peak_key, pair_target)
                new_peak = max(current_peak, total_pl)
                state.trailing_peaks[peak_key] = new_peak
                
                trail_dist = float(state.monitor_trailing_stk_usd.get() or 2.0)
                if total_pl <= (new_peak - trail_dist):
                    is_group_target = True
                    del state.trailing_peaks[peak_key]
            else:
                if peak_key in state.trailing_peaks: del state.trailing_peaks[peak_key]

        g_tags = ('group',)
        if is_group_target:
            g_tags = ('group', 'target')
            if state.monitor_auto_close_var.get():
                if is_custom:
                    threading.Thread(target=execute_group_auto_close, args=(state, name, group_rows), daemon=True).start()
        elif is_group_trailing:
            g_tags = ('group', 'trailing')

        target_display = f"{pair_target:.0f} $" if pair_target > 0 else "—"
        if is_group_trailing:
            target_display = f"TRAIL (Max {state.trailing_peaks.get(f'pair_{name}', 0):.1f}$)"

        icon = "🔗 " if is_custom else "📦 "
        node_id = tree.insert(parent, tk.END, text=f"{icon}{name}", values=(
            "", pl_summary, "", "", "", f"{total_pl:+.2f} $", "", target_display
        ), tags=g_tags)
        
        for r in group_rows:
            tags = []
            row_is_target = r['is_target']
            row_target_display = r['target_display']
            
            pos_key = f"{r['sym']}_{r['desc']}"
            is_row_trailing = False
            is_row_triggered = False
            
            eff_target = 0.0
            is_opt = r.get('secType') == 'OPT'
            if is_custom:
                eff_target = p_opt_target if is_opt else p_stk_target
            
            if eff_target == 0:
                eff_target = float(state.monitor_profit_target_pct.get()) if is_opt else float(state.monitor_stock_profit_target_usd.get())

            current_val = r.get('raw_pl_pct', 0) if is_opt else r.get('raw_pl_usd', 0)
            
            if current_val >= eff_target:
                is_row_trailing = True
                cur_peak = state.trailing_peaks.get(pos_key, eff_target)
                new_peak = max(cur_peak, current_val)
                state.trailing_peaks[pos_key] = new_peak
                
                t_dist = float(state.monitor_trailing_opt_pct.get() if is_opt else state.monitor_trailing_stk_usd.get())
                if current_val <= (new_peak - t_dist):
                    is_row_triggered = True
                    del state.trailing_peaks[pos_key]
            else:
                if pos_key in state.trailing_peaks: del state.trailing_peaks[pos_key]

            if not is_group_target:
                if is_row_triggered:
                    tags.append('target')
                    if state.monitor_auto_close_var.get():
                        threading.Thread(target=execute_auto_close, args=(state, r), daemon=True).start()
                elif is_row_trailing:
                    tags.append('trailing')
                    row_target_display = f"TRAIL ({new_peak:.1f}{'%' if is_opt else '$'})"
                elif r['is_warning']: tags.append('warning')
                elif r['is_loss']: tags.append('loss')
            
            if not r.get('is_verified'): tags.append('unverified')
            
            v_ico = "✓ " if r.get('is_verified') else "⚠️ "
            tree.insert(node_id, tk.END, text="", values=(
                f"{v_ico}{r['sym']}", r['desc'], r['pos'], r['price'], r['avg'], 
                r['pl_usd'], r['pl_display'], row_target_display
            ), tags=tags)
            
        if f"{icon}{name}" in expanded_items:
            tree.item(node_id, open=True)

    # 2. VLOŽENIE DO STROMU
    if custom_pairs_rows:
        root_custom = tree.insert('', tk.END, text="🔗 MOJE VLASTNÉ PÁRY (Cross-Hedge)", tags=('header',))
        tree.item(root_custom, open=True)
        for name in sorted(custom_pairs_rows.keys()):
            insert_group(root_custom, name, custom_pairs_rows[name], is_custom=True)

    if natural_groups_rows:
        root_nat = tree.insert('', tk.END, text="📦 JEDNOTLIVÉ SYMBOLY (Natural Hedge)", tags=('header',))
        tree.item(root_nat, open=True)
        for sym in sorted(natural_groups_rows.keys()):
            insert_group(root_nat, sym, natural_groups_rows[sym], is_custom=False)

def create_swing_watcher_tab(parent, state):
    frame = ttk.Frame(parent, padding=15)
    frame.pack(fill='both', expand=True)
    
    header = ttk.Label(frame, text="🚀 Swing Profit Watcher (Profit Realization Guard)", font=('Arial', 12, 'bold'))
    header.pack(fill='x', pady=(0, 10))

    w_ctrl = ttk.LabelFrame(frame, text="⚙️ Nastavenia automatického výstupu", padding=10)
    w_ctrl.pack(fill='x', pady=5)
    
    ttk.Label(w_ctrl, text="🔔 Warning (%):").pack(side='left', padx=5)
    ttk.Entry(w_ctrl, textvariable=state.monitor_profit_warning_pct, width=5).pack(side='left', padx=2)

    ttk.Label(w_ctrl, text="🎯 Option Target (%):").pack(side='left', padx=(15, 5))
    ttk.Entry(w_ctrl, textvariable=state.monitor_profit_target_pct, width=5).pack(side='left', padx=2)

    ttk.Label(w_ctrl, text="💰 Stock Target ($):").pack(side='left', padx=(15, 5))
    ttk.Entry(w_ctrl, textvariable=state.monitor_stock_profit_target_usd, width=6).pack(side='left', padx=2)
    
    ttk.Checkbutton(w_ctrl, text="🤖 AUTO-TAKE PROFIT (Exit + Stop Hedger)", 
                    variable=state.monitor_auto_close_var).pack(side='left', padx=20)
    
    ttk.Checkbutton(w_ctrl, text="🔄 RESTART CYCLE (Re-open after Exit)", 
                    variable=state.monitor_auto_restart_var).pack(side='left', padx=5)

    ttk.Label(w_ctrl, text="📉 Trail OPT (%):").pack(side='left', padx=(15, 5))
    ttk.Entry(w_ctrl, textvariable=state.monitor_trailing_opt_pct, width=4).pack(side='left', padx=2)

    ttk.Label(w_ctrl, text="📉 Trail STK ($):").pack(side='left', padx=(10, 5))
    ttk.Entry(w_ctrl, textvariable=state.monitor_trailing_stk_usd, width=4).pack(side='left', padx=2)

    p_mgr_frame = ttk.PanedWindow(frame, orient='horizontal')
    p_mgr_frame.pack(fill='x', pady=5)

    p_ctrl = ttk.LabelFrame(p_mgr_frame, text="🔗 Definícia nového páru", padding=10)
    p_mgr_frame.add(p_ctrl, weight=1)
    
    add_grid = ttk.Frame(p_ctrl)
    add_grid.pack(fill='x')
    
    ttk.Label(add_grid, text="Názov páru:").grid(row=0, column=0, sticky='w', padx=5, pady=2)
    p_name_var = tk.StringVar()
    ttk.Entry(add_grid, textvariable=p_name_var, width=20).grid(row=0, column=1, sticky='w', padx=5, pady=2)
    
    ttk.Label(add_grid, text="Symboly (AMD,QQQ):").grid(row=1, column=0, sticky='w', padx=5, pady=2)
    p_syms_var = tk.StringVar()
    ttk.Entry(add_grid, textvariable=p_syms_var, width=20).grid(row=1, column=1, sticky='w', padx=5, pady=2)
    
    ttk.Label(add_grid, text="Target Net ($):").grid(row=2, column=0, sticky='w', padx=5, pady=2)
    p_target_var = tk.StringVar()
    ttk.Entry(add_grid, textvariable=p_target_var, width=10).grid(row=2, column=1, sticky='w', padx=5, pady=2)

    ttk.Label(add_grid, text="Option Target (%):").grid(row=3, column=0, sticky='w', padx=5, pady=2)
    p_opt_target_var = tk.StringVar()
    ttk.Entry(add_grid, textvariable=p_opt_target_var, width=10).grid(row=3, column=1, sticky='w', padx=5, pady=2)

    ttk.Label(add_grid, text="Stock Target ($):").grid(row=4, column=0, sticky='w', padx=5, pady=2)
    p_stk_target_var = tk.StringVar()
    ttk.Entry(add_grid, textvariable=p_stk_target_var, width=10).grid(row=4, column=1, sticky='w', padx=5, pady=2)
    
    ttk.Button(add_grid, text="➕ PRIDAŤ / AKTUALIZOVAŤ PÁR", 
               command=lambda: add_custom_pair(state, p_name_var, p_syms_var, p_target_var, p_opt_target_var, p_stk_target_var)).grid(row=5, column=0, columnspan=2, pady=10)

    p_list_frame = ttk.LabelFrame(p_mgr_frame, text="📋 Aktuálne uložené páry", padding=10)
    p_mgr_frame.add(p_list_frame, weight=1)
    
    lb_frame = ttk.Frame(p_list_frame)
    lb_frame.pack(fill='both', expand=True)
    
    state.monitor_pairs_listbox = tk.Listbox(lb_frame, height=5, font=('Arial', 9), borderwidth=0, highlightthickness=0)
    state.monitor_pairs_listbox.pack(side='left', fill='both', expand=True)
    
    lb_sb = ttk.Scrollbar(lb_frame, orient="vertical", command=state.monitor_pairs_listbox.yview)
    lb_sb.pack(side='right', fill='y')
    state.monitor_pairs_listbox.configure(yscrollcommand=lb_sb.set)
    
    refresh_pairs_listbox(state)
    
    btn_p_del = ttk.Button(p_list_frame, text="🗑️ Vymazať vybraný", 
                           command=lambda: [delete_custom_pair(state, state.monitor_pairs_listbox.get(s).split(" (")[0]) if (s:=state.monitor_pairs_listbox.curselection()) else None])
    btn_p_del.pack(pady=(5, 0))

    table_label = ttk.Label(frame, text="📊 Profit Guard Monitoring", font=('Arial', 10, 'bold'))
    table_label.pack(fill='x', pady=(10, 0))

    table_frame = ttk.Frame(frame)
    table_frame.pack(fill='both', expand=True, pady=10)
    
    cols = ('sym', 'desc', 'pos', 'mkt', 'avg', 'pl_usd', 'pl_pct', 'target')
    tree = ttk.Treeview(table_frame, columns=cols, show='tree headings')
    
    tree.heading('#0', text='Pár / Skupina'); tree.column('#0', width=150, anchor='w')
    tree.heading('sym', text='Symbol'); tree.column('sym', width=80, anchor='center')
    tree.heading('desc', text='Popis pozície'); tree.column('desc', width=150, anchor='w')
    tree.heading('pos', text='Ks'); tree.column('pos', width=60, anchor='center')
    tree.heading('mkt', text='Trh. Cena'); tree.column('mkt', width=100, anchor='center')
    tree.heading('avg', text='Nákupná Cena'); tree.column('avg', width=100, anchor='center')
    tree.heading('pl_usd', text='Unr P/L $'); tree.column('pl_usd', width=120, anchor='center')
    tree.heading('pl_pct', text='Aktuálny Zisk'); tree.column('pl_pct', width=120, anchor='center')
    tree.heading('target', text='Cieľ'); tree.column('target', width=100, anchor='center')
    
    tree.pack(side='left', fill='both', expand=True)
    
    sb = ttk.Scrollbar(table_frame, orient="vertical", command=tree.yview)
    sb.pack(side='right', fill='y')
    tree.configure(yscrollcommand=sb.set)
    
    state.monitor_watcher_tree = tree

    info_label = ttk.Label(frame, text="💡 Tip: Robot sleduje zisk z prijatej prémie pri opciách a dolárový zisk pri akciách.", 
                           font=('Arial', 8, 'italic'), foreground='gray')
    info_label.pack(fill='x', pady=5)
