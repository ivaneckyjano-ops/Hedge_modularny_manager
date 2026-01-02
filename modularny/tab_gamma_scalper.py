#!/usr/bin/env python3
"""
Záložka: Gamma Scalper (Long Strangle Manager)
Prehľadné rozhranie pre Gamma Scalping stratégiu so scrollbarom.
"""
import tkinter as tk
from tkinter import ttk, messagebox, scrolledtext
import subprocess
import threading
import os
import json
import time
import sys
from datetime import datetime

def create_gamma_scalper_tab(parent, state):
    """Vytvorí záložku pre Gamma Scalping so scrollbarom pre malé obrazovky"""
    
    # === SCROLLABLE CONTAINER ===
    canvas = tk.Canvas(parent, highlightthickness=0)
    scrollbar = ttk.Scrollbar(parent, orient="vertical", command=canvas.yview)
    
    scroll_content = ttk.Frame(canvas)
    
    # Zabezpečíme, aby frame vnútri canvasu mal rovnakú šírku ako canvas
    def _on_canvas_configure(event):
        canvas.itemconfig(canvas_window, width=event.width)

    canvas_window = canvas.create_window((0, 0), window=scroll_content, anchor="nw")
    canvas.bind("<Configure>", _on_canvas_configure)
    
    scroll_content.bind(
        "<Configure>",
        lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
    )
    
    canvas.configure(yscrollcommand=scrollbar.set)
    scrollbar.pack(side="right", fill="y")
    canvas.pack(side="left", fill="both", expand=True)

    def _on_mousewheel(event):
        if sys.platform == "linux":
            if event.num == 4: canvas.yview_scroll(-1, "units")
            elif event.num == 5: canvas.yview_scroll(1, "units")
        else:
            canvas.yview_scroll(int(-1*(event.delta/120)), "units")
    
    canvas.bind_all("<Button-4>", _on_mousewheel)
    canvas.bind_all("<Button-5>", _on_mousewheel)
    canvas.bind_all("<MouseWheel>", _on_mousewheel)

    container = scroll_content

    # Pomocná funkcia na bezpečný update textového poľa analýzy
    def update_gs_analysis_text(text):
        if not hasattr(state, 'gs_result_text'): return
        state.gs_result_text.config(state='normal')
        state.gs_result_text.delete(1.0, tk.END)
        state.gs_result_text.insert(tk.END, text)
        state.gs_result_text.config(state='disabled')
        state.gs_result_text.see(tk.END)
    
    state.update_gs_analysis_text = update_gs_analysis_text

    # === 1. PARAMETRE VYHĽADÁVANIA ===
    search_frame = ttk.LabelFrame(container, text="🔍 Vyhľadávač Strangle (Gamma Scalping)", padding=10)
    search_frame.pack(fill='x', padx=10, pady=5)
    
    row1 = ttk.Frame(search_frame)
    row1.pack(fill='x', pady=5)
    
    ttk.Label(row1, text="Symbol:").pack(side='left', padx=5)
    ttk.Entry(row1, textvariable=state.symbol_var, width=10).pack(side='left', padx=5)
    
    ttk.Label(row1, text="Expirácia:").pack(side='left', padx=10)
    expiry_combo = ttk.Combobox(row1, textvariable=state.calc_short_expiry_var, width=12)
    expiry_combo.pack(side='left', padx=5)
    state.gs_expiry_combo = expiry_combo
    
    ttk.Label(row1, text="Cieľová Delta (±):").pack(side='left', padx=10)
    ttk.Entry(row1, textvariable=state.gs_target_delta_var, width=6).pack(side='left', padx=5)
    
    ttk.Button(row1, text="🔄 Načítať Expirácie", command=state.load_expiries).pack(side='left', padx=10)
    
    row2 = ttk.Frame(search_frame)
    row2.pack(fill='x', pady=5)
    
    state.btn_find_strangle = ttk.Button(row2, text="🚀 NÁJSŤ STRANGLE", command=lambda: find_strangle_gs(state), style='Accent.TButton')
    state.btn_find_strangle.pack(side='left', padx=5, fill='x', expand=True)

    state.btn_stop_strangle = ttk.Button(row2, text="🛑 Ukončiť vyhľadávanie", command=state.stop_gamma_scalper_search, style='Waring.TButton', state='disabled')
    state.btn_stop_strangle.pack(side='left', padx=5, fill='x', expand=True)
    
    ttk.Checkbutton(row2, text="Preferovať B-S Model", variable=state.gs_model_priority_var).pack(side='left', padx=15)

    # === 2. ARCHÍV STRATÉGIÍ ===
    archive_frame = ttk.LabelFrame(container, text="🗄️ Archív Stratégií Gamma Scalper", padding=10)
    archive_frame.pack(fill='x', padx=10, pady=5)

    archive_row1 = ttk.Frame(archive_frame)
    archive_row1.pack(fill='x', pady=5)

    ttk.Label(archive_row1, text="Názov:").pack(side='left', padx=5)
    ttk.Entry(archive_row1, textvariable=state.gs_strategy_name_var, width=20).pack(side='left', padx=5)
    
    ttk.Label(archive_row1, text="Poznámka:").pack(side='left', padx=10)
    ttk.Entry(archive_row1, textvariable=state.gs_strategy_notes_var, width=30).pack(side='left', padx=5)

    tree_frame = ttk.Frame(archive_frame)
    tree_frame.pack(fill='x', pady=5)
    
    columns = ('symbol', 'name', 'delta', 'notes', 'saved_at')
    state.gs_archive_tree = ttk.Treeview(tree_frame, columns=columns, show='headings', height=5)
    state.gs_archive_tree.heading('symbol', text='Ticker')
    state.gs_archive_tree.heading('name', text='Názov')
    state.gs_archive_tree.heading('delta', text='Δ')
    state.gs_archive_tree.heading('notes', text='Poznámka')
    state.gs_archive_tree.heading('saved_at', text='Uložené')
    
    state.gs_archive_tree.column('symbol', width=60)
    state.gs_archive_tree.column('name', width=120)
    state.gs_archive_tree.column('delta', width=40, anchor='center')
    state.gs_archive_tree.column('notes', width=200)
    state.gs_archive_tree.column('saved_at', width=120)
    
    tree_scroll = ttk.Scrollbar(tree_frame, orient="vertical", command=state.gs_archive_tree.yview)
    state.gs_archive_tree.configure(yscrollcommand=tree_scroll.set)
    state.gs_archive_tree.pack(side='left', fill='x', expand=True)
    tree_scroll.pack(side='right', fill='y')

    def refresh_gs_tree():
        for item in state.gs_archive_tree.get_children():
            state.gs_archive_tree.delete(item)
        sorted_strategies = sorted(state.saved_gamma_scalper_strategies.items(), key=lambda x: (x[1].get('symbol', ''), x[0]))
        for name, data in sorted_strategies:
            state.gs_archive_tree.insert('', tk.END, values=(
                data.get('symbol', ''),
                name,
                data.get('target_delta', ''),
                data.get('notes', ''),
                data.get('saved_at', '')
            ))

    def on_tree_select(event):
        selected = state.gs_archive_tree.selection()
        if selected:
            vals = state.gs_archive_tree.item(selected[0])['values']
            state.gs_strategy_name_var.set(vals[1])
            state.load_gamma_scalper_strategy(state.gs_strategy_name_var, auto=True)

    state.gs_archive_tree.bind('<<TreeviewSelect>>', on_tree_select)
    refresh_gs_tree()
    state.refresh_gs_archive_tree = refresh_gs_tree

    archive_btns = ttk.Frame(archive_frame)
    archive_btns.pack(fill='x', pady=5)
    ttk.Button(archive_btns, text="💾 Uložiť Stratégiu", command=lambda: [state.save_gamma_scalper_strategy(state.gs_strategy_name_var), refresh_gs_tree()]).pack(side='left', padx=5)
    ttk.Button(archive_btns, text="📂 Načítať Stratégiu", command=lambda: state.load_gamma_scalper_strategy(state.gs_strategy_name_var)).pack(side='left', padx=5)
    ttk.Button(archive_btns, text="🗑️ Vymazať Stratégiu", command=lambda: [state.delete_gamma_scalper_strategy(state.gs_strategy_name_var), refresh_gs_tree()]).pack(side='left', padx=5)

    # === 3. ARCHÍV A NASTAVENIE SEMAFORU ===
    semafor_frame = ttk.LabelFrame(container, text="🚦 Nastavenie & Archív Gamma Semaforu", padding=10)
    semafor_frame.pack(fill='x', padx=10, pady=5)

    edit_row = ttk.Frame(semafor_frame)
    edit_row.pack(fill='x', pady=5)
    
    ttk.Label(edit_row, text="SB >=:").pack(side='left', padx=2)
    ttk.Entry(edit_row, textvariable=state.gs_strong_buy_threshold_var, width=5).pack(side='left', padx=5)
    ttk.Label(edit_row, text="Buy >=:").pack(side='left', padx=2)
    ttk.Entry(edit_row, textvariable=state.gs_buy_threshold_var, width=5).pack(side='left', padx=5)
    ttk.Label(edit_row, text="Neutr >=:").pack(side='left', padx=2)
    ttk.Entry(edit_row, textvariable=state.gs_neutral_threshold_var, width=5).pack(side='left', padx=5)
    ttk.Label(edit_row, text="Stop >=:").pack(side='left', padx=2)
    ttk.Entry(edit_row, textvariable=state.gs_stop_threshold_var, width=5).pack(side='left', padx=5)
    ttk.Label(edit_row, text="Názov Konfig:").pack(side='left', padx=10)
    ttk.Entry(edit_row, textvariable=state.gs_semafor_config_name_var, width=12).pack(side='left', padx=5)
    
    sem_tree_frame = ttk.Frame(semafor_frame)
    sem_tree_frame.pack(fill='x', pady=5)
    
    sem_cols = ('symbol', 'name', 'notes', 'sb', 'buy', 'neu', 'stop')
    state.gs_semafor_archive_tree = ttk.Treeview(sem_tree_frame, columns=sem_cols, show='headings', height=4)
    state.gs_semafor_archive_tree.heading('symbol', text='Ticker')
    state.gs_semafor_archive_tree.heading('name', text='Názov')
    state.gs_semafor_archive_tree.heading('notes', text='Poznámka')
    state.gs_semafor_archive_tree.heading('sb', text='SB')
    state.gs_semafor_archive_tree.heading('buy', text='Buy')
    state.gs_semafor_archive_tree.heading('neu', text='Neut')
    state.gs_semafor_archive_tree.heading('stop', text='Stop')
    
    state.gs_semafor_archive_tree.column('symbol', width=60)
    state.gs_semafor_archive_tree.column('name', width=100)
    state.gs_semafor_archive_tree.column('notes', width=150)
    for c in ('sb', 'buy', 'neu', 'stop'): state.gs_semafor_archive_tree.column(c, width=40, anchor='center')
    
    sem_scroll = ttk.Scrollbar(sem_tree_frame, orient="vertical", command=state.gs_semafor_archive_tree.yview)
    state.gs_semafor_archive_tree.configure(yscrollcommand=sem_scroll.set)
    state.gs_semafor_archive_tree.pack(side='left', fill='x', expand=True)
    sem_scroll.pack(side='right', fill='y')

    def refresh_sem_tree():
        for item in state.gs_semafor_archive_tree.get_children(): state.gs_semafor_archive_tree.delete(item)
        sorted_configs = sorted(state.saved_gamma_semafor_configs.items(), key=lambda x: (x[1].get('symbol', ''), x[0]))
        for name, d in sorted_configs:
            state.gs_semafor_archive_tree.insert('', tk.END, values=(
                d.get('symbol', ''),
                name,
                d.get('notes', ''),
                d.get('strong_buy'),
                d.get('buy'),
                d.get('neutral'),
                d.get('stop')
            ))

    def on_sem_select(event):
        sel = state.gs_semafor_archive_tree.selection()
        if sel:
            name = state.gs_semafor_archive_tree.item(sel[0])['values'][1]
            state.gs_semafor_config_name_var.set(name)
            state.load_gamma_semafor_config(state.gs_semafor_config_name_var, auto=True)

    state.gs_semafor_archive_tree.bind('<<TreeviewSelect>>', on_sem_select)
    state.refresh_gs_semafor_tree = refresh_sem_tree
    refresh_sem_tree()

    sem_btns = ttk.Frame(semafor_frame)
    sem_btns.pack(fill='x', pady=5)
    ttk.Button(sem_btns, text="💾 Uložiť Konfig", command=lambda: [state.save_gamma_semafor_config(), refresh_sem_tree()]).pack(side='left', padx=5)
    ttk.Button(sem_btns, text="🗑️ Vymazať Konfig", command=lambda: [state.delete_gamma_semafor_config(state.gs_semafor_config_name_var), refresh_sem_tree()]).pack(side='left', padx=5)
    ttk.Button(sem_btns, text="🔄 APLIKOVAŤ PRAHY", command=state.save_settings_file).pack(side='right', padx=5)

    # === 4. VIZUÁLNY SEMAFOR ===
    visual_frame = ttk.Frame(container, padding=10)
    visual_frame.pack(fill='x', padx=10)
    
    state.gamma_summary_label = tk.Label(
        visual_frame,
        text="Γ/Θ: —",
        font=('Arial', 24, 'bold'),
        fg='gray'
    )
    state.gamma_summary_label.pack(side='left', padx=10)
    
    def open_analysis_window():
        """Otvorí aktuálnu analýzu v novom veľkom okne"""
        content = state.gs_result_text.get(1.0, tk.END)
        if "GAMMA SCALPER SETUP" not in content:
            messagebox.showwarning("Prázdna analýza", "Najprv vykonajte vyhľadávanie alebo načítajte stratégiu.")
            return
        win = tk.Toplevel(state.root)
        win.title(f"Greeks Analýza - {state.symbol_var.get()}")
        win.geometry("900x700")
        header_text = f"ANALÝZA PRE: {state.symbol_var.get()} | ČAS: {datetime.now().strftime('%H:%M:%S')}\n"
        header_text += "="*60 + "\n\n"
        txt = scrolledtext.ScrolledText(win, font=('Courier', 12))
        txt.pack(fill='both', expand=True, padx=10, pady=10)
        txt.insert(tk.END, header_text + content)
        txt.config(state='disabled')
        ttk.Button(win, text="❌ Zavrieť", command=win.destroy).pack(pady=5)

    def place_order_gs():
        """Odošle Market objednávku pre nájdený Strangle (iba ak je na Paper porte 7497)"""
        symbol = state.symbol_var.get()
        expiry = state.calc_short_expiry_var.get()
        call_strike = state.calc_short_strike_var.get()
        put_strike = state.calc_long_strike_var.get()
        port = state.port_var.get()

        if not all([symbol, expiry, call_strike, put_strike]):
            messagebox.showwarning("Chýbajúce dáta", "Najprv musíte nájsť stratégiu (NÁJSŤ STRANGLE).")
            return

        # Port check
        if str(port) != "7497":
            messagebox.showerror("Bezpečnostná poistka", f"Objednávka zrušená. Port {port} NIE JE paper port 7497. Táto funkcia je v 'ask mode' povolená len pre Paper Trading.")
            return

        if not messagebox.askyesno("Potvrdiť objednávku", f"Naozaj chcete odoslať MARKET objednávku pre {symbol} Strangle?\n\nCALL: {call_strike}\nPUT: {put_strike}\nExpirácia: {expiry}\nPort: {port} (PAPER)"):
            return

        update_gs_status(state, "Odosielam objednávku...", "orange")
        
        def run_order():
            try:
                python_exec = sys.executable
                script_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'scripts', 'tws_place_order.py')
                cmd = [
                    python_exec, script_path, 
                    '--symbol', symbol, 
                    '--expiry', expiry, 
                    '--call-strike', str(call_strike), 
                    '--put-strike', str(put_strike), 
                    '--port', str(port),
                    '--paper-only'
                ]
                result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
                
                if result.returncode == 0:
                    res_data = json.loads(result.stdout)
                    if res_data.get('success'):
                        messagebox.showinfo("Úspech", "Objednávky boli úspešne odoslané do TWS.")
                        update_gs_status(state, "✓ Objednávky odoslané", "green")
                    else:
                        messagebox.showerror("Chyba", f"Chyba pri odosielaní: {res_data.get('error')}")
                        update_gs_status(state, "❌ Chyba objednávky", "red")
                else:
                    messagebox.showerror("Chyba", f"Skript vrátil chybu {result.returncode}:\n{result.stderr}")
                    update_gs_status(state, "❌ Chyba skriptu", "red")
            except Exception as e:
                messagebox.showerror("Výnimka", f"Došlo k chybe: {e}")
                update_gs_status(state, "❌ Výnimka", "red")

        threading.Thread(target=run_order, daemon=True).start()

    btn_row = ttk.Frame(visual_frame)
    btn_row.pack(side='right')

    ttk.Button(btn_row, text="🔍 ANALÝZA V NOVOM OKNE", command=open_analysis_window).pack(side='left', padx=5)
    state.btn_place_order = ttk.Button(btn_row, text="🛒 POSLAŤ OBJEDNÁVKU (PAPER)", command=place_order_gs, style='Accent.TButton')
    state.btn_place_order.pack(side='left', padx=5)

    # === 5. VÝSLEDKY A ANALÝZA ===
    analysis_frame = ttk.LabelFrame(container, text="📊 Analýza & Greeks", padding=10)
    analysis_frame.pack(fill='both', expand=True, padx=10, pady=5)
    
    state.gs_result_text = scrolledtext.ScrolledText(analysis_frame, height=15, font=('Courier', 11))
    state.gs_result_text.pack(fill='both', expand=True, padx=5, pady=5)
    state.gs_result_text.config(state='disabled') # Štartujeme uzamknuté
    
    # === 6. MONITOR POZÍCIÍ ===
    monitor_frame = ttk.LabelFrame(container, text="⚠️ Active Management (Delta Drift)", padding=10)
    monitor_frame.pack(fill='x', padx=10, pady=5)
    row_mon = ttk.Frame(monitor_frame)
    row_mon.pack(fill='x', pady=5)
    ttk.Label(row_mon, text="Tolerancia Driftu:").pack(side='left', padx=5)
    state.gs_drift_tol = tk.StringVar(value="0.20")
    ttk.Entry(row_mon, textvariable=state.gs_drift_tol, width=6).pack(side='left', padx=5)
    
    ttk.Checkbutton(row_mon, text="🔄 Auto-Sledovanie (30s)", variable=state.gs_auto_monitor_var, 
                    command=lambda: toggle_auto_monitor(state)).pack(side='left', padx=10)
    
    state.gs_mon_status = ttk.Label(row_mon, text="Pripravené", foreground="gray")
    state.gs_mon_status.pack(side='left', padx=10)

    if state.available_expiries: expiry_combo['values'] = state.available_expiries

def toggle_auto_monitor(state):
    """Zapne/vypne automatické sledovanie"""
    if state.gs_auto_monitor_var.get():
        update_gs_status(state, "Auto-monitoring ZAPNUTÝ", "green")
        check_position_gs(state) # Spustí prvé kolo
    else:
        update_gs_status(state, "Auto-monitoring VYPNUTÝ", "gray")

def update_gs_status(state, text, color="black"):
    if hasattr(state, 'gs_mon_status'): 
        state.gs_mon_status.config(text=text, foreground=color)
    
    # Aktualizácia globálneho status baru (úplne hore)
    if hasattr(state, 'monitor_status_var'):
        state.monitor_status_var.set(f"Monitor: {text}")
        if hasattr(state, 'monitor_status_label'):
            state.monitor_status_label.config(fg=color)

def find_strangle_gs(state):
    symbol, expiry, target, port = state.symbol_var.get().strip().upper(), state.calc_short_expiry_var.get(), state.gs_target_delta_var.get(), state.port_var.get()
    
    # Automatické načítanie tolerancie driftu z archívu, ak existuje
    if symbol in state.ticker_settings:
        saved_tol = state.ticker_settings[symbol].get('drift_tolerance')
        if saved_tol:
            state.gs_drift_tol.set(str(saved_tol))
            print(f"DEBUG: Automaticky načítaná tolerancia driftu pre {symbol}: {saved_tol}", file=sys.stderr)

    if not symbol or not expiry:
        messagebox.showwarning("Chyba", "Zadajte Symbol a Expiráciu")
        return
    update_gs_status(state, f"Hľadám Strangle pre {symbol}...", "blue")
    state.update_gs_analysis_text("Vyhľadávam optimálne opcie...\n")
    state.btn_find_strangle.config(state='disabled')
    state.btn_stop_strangle.config(state='normal')
    
    def run():
        try:
            python_exec = sys.executable
            script_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'scripts', 'tws_strangle_finder.py')
            cmd = [python_exec, script_path, '--symbol', symbol, '--expiry', expiry, '--delta-target', target, '--port', str(port)]
            if state.gs_model_priority_var.get(): cmd.append('--model-priority')
            proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, cwd='/home/narbon/Aplikácie/tws-webapp', bufsize=1)
            state.gs_search_process = proc
            def stream(p):
                for line in p: print(line.rstrip())
            threading.Thread(target=stream, args=(proc.stderr,), daemon=True).start()
            output, _ = proc.communicate(timeout=90)
            output = output.strip()
            if proc.returncode == 0 and output:
                data = json.loads(output)
                if data.get('success'):
                    candidates = data.get('candidates', [])
                    def ratio(c):
                        t = abs(c['stats'].get('totalTheta') or 0)
                        g = c['stats'].get('totalGamma') or 0
                        return (g / t) if t > 1e-6 else 0
                    cand_sorted = sorted(candidates, key=ratio, reverse=True)
                    best = cand_sorted[0]
                    call, put, stats = best['callLeg'], best['putLeg'], best['stats']
                    gt_ratio = (stats['totalGamma'] / abs(stats['totalTheta'])) if abs(stats['totalTheta']) > 0.0001 else 0
                    sb, b, n, st = float(state.gs_strong_buy_threshold_var.get()), float(state.gs_buy_threshold_var.get()), float(state.gs_neutral_threshold_var.get()), float(state.gs_stop_threshold_var.get())
                    if gt_ratio >= sb: sent, col = "Silný nákup", '#006400'
                    elif gt_ratio >= b: sent, col = "Nákup", '#228B22'
                    elif gt_ratio >= n: sent, col = "Neutrálny", '#DAA520'
                    elif gt_ratio >= st: sent, col = "Stop", '#FF4500'
                    else: sent, col = "Silný stop", '#8B0000'
                    iv_avg = sum([v for v in (call.get('iv'), put.get('iv')) if v])/2 if any((call.get('iv'), put.get('iv'))) else None
                    state.root.after(0, lambda: state.gamma_summary_label.config(text=f"Γ/Θ: {gt_ratio:.2f} | {sent}", fg=col))
                    state.update_gamma_display(gt_ratio, sent, iv_avg, col)
                    state.fetch_vix()
                    lines = [
                        "╔══════════════════════════════════════════════════════════════════╗",
                        "║               🧘 GAMMA SCALPER SETUP (Long Strangle)             ║",
                        "╠══════════════════════════════════════════════════════════════════╣",
                        f"║  Symbol: {symbol:10}    Expiry: {expiry:10}    Cena: ${stats['underlyingPrice']:.2f}     ║",
                        "╠══════════════════════════════════════════════════════════════════╣",
                        "║  KANDIDÁTI (podľa delty)                                         ║"
                    ]
                    for c in cand_sorted:
                        r = ratio(c)
                        if r >= sb: ico = "🟢"
                        elif r >= b: ico = "🟩"
                        elif r >= n: ico = "🟡"
                        elif r >= st: ico = "🟠"
                        else: ico = "🔴"
                        lines.append(f"║  Δ~{c['target']:.2f}: CALL {c['callLeg']['strike']:.1f} Δ{c['callLeg']['delta']:+.3f}  PUT {c['putLeg']['strike']:.1f} Δ{c['putLeg']['delta']:+.3f}  GT={r:.3f} {ico:2} ║")
                    lines.extend([
                        "╠══════════════════════════════════════════════════════════════════╣",
                        "║  VYBRANÝ (najvyšší Gamma/Theta)                                  ║",
                        f"║  🟢 CALL: Strike {call['strike']:.1f}   Delta: {call['delta']:+.3f}   Cena: ${call['mid']:.2f}      ║",
                        f"║  🟢 PUT:  Strike {put['strike']:.1f}   Delta: {put['delta']:+.3f}   Cena: ${put['mid']:.2f}      ║",
                        "╠══════════════════════════════════════════════════════════════════╣",
                        "║  📊 GREEKS & RISK:                                               ║",
                        f"║     Net Delta:   {stats['netDelta']:+.3f}  (Ideál: 0.000)                   ║",
                        f"║     Total Gamma: {stats['totalGamma']:.5f}                             ║",
                        f"║     Total Theta: {stats['totalTheta']:.3f}  (Denný náklad)                  ║",
                        "║     -----------------------------------                          ║",
                        f"║     🔥 GAMMA/THETA RATIO: {gt_ratio:.4f} {sent}                        ║",
                        "║     (Koľko Gammy dostanete za 1 dolár Thety)                     ║",
                        "║     -----------------------------------                          ║",
                        f"║     Total Debit: ${stats['totalCost']:.2f} (Investícia)                     ║",
                        "╚══════════════════════════════════════════════════════════════════╝"
                    ])
                    state.root.after(0, lambda: state.update_gs_analysis_text("\n".join(lines)))
                    update_gs_status(state, "✓ Nájdené", "green")
                    state.root.after(0, lambda: [state.calc_short_strike_var.set(call['strike']), state.calc_short_premium_var.set(call['mid']), state.calc_long_strike_var.set(put['strike']), state.calc_long_premium_var.set(put['mid'])])
                else:
                    state.root.after(0, lambda: state.update_gs_analysis_text(f"❌ Chyba: {data.get('error')}"))
                    update_gs_status(state, "❌ Chyba", "red")
            else:
                state.root.after(0, lambda: state.update_gs_analysis_text(f"❌ Chyba skriptu {proc.returncode}"))
                update_gs_status(state, "❌ Chyba skriptu", "red")
        except Exception as e:
            state.root.after(0, lambda m=str(e): state.update_gs_analysis_text(f"❌ Výnimka: {m}"))
        finally:
            state.root.after(0, lambda: [state.btn_find_strangle.config(state='normal'), state.btn_stop_strangle.config(state='disabled')])
            state.gs_search_process = None
    threading.Thread(target=run, daemon=True).start()

def check_position_gs(state):
    active_symbol, port = state.symbol_var.get().strip().upper(), state.port_var.get()
    update_gs_status(state, f"Monitorujem portfólio...", "blue")
    
    def run():
        try:
            python_exec = sys.executable
            script_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'scripts', 'tws_manual_test.py')
            cmd, env = [python_exec, script_path, '--mode', 'positions'], os.environ.copy()
            env['TWS_PORT'] = str(port)
            project_root = os.path.dirname(os.path.dirname(__file__))
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=15, cwd=project_root, env=env)
            
            if result.returncode != 0:
                err_msg = result.stderr.strip() or "Neznáma chyba"
                state.root.after(0, lambda: update_gs_status(state, f"❌ Chyba pripojenia", "red"))
                return

            pos_data = json.loads(result.stdout).get('positions', [])
            
            # Zoskupenie podľa symbolu a expirácií
            portfolio = {}
            for p in pos_data:
                sym = p.get('symbol')
                if not sym: continue
                if sym not in portfolio: portfolio[sym] = []
                portfolio[sym].append(p)

            timestamp = datetime.now().strftime("%H:%M:%S")
            report_lines = [f"📊 STAV PORTFÓLIA ({timestamp})", "="*40]
            
            has_active = False
            
            # Najprv spracujeme aktívny symbol, potom ostatné
            sorted_symbols = sorted(portfolio.keys())
            if active_symbol in sorted_symbols:
                sorted_symbols.remove(active_symbol)
                sorted_symbols.insert(0, active_symbol)

            overall_status = "✅ Portfólio OK"
            overall_col = "green"
            drift_symbols = []

            for sym in sorted_symbols:
                sym_positions = portfolio[sym]
                sym_delta = 0
                sym_gamma = 0 # Pridané
                sym_lines = []
                
                # Zoskupenie opcií podľa expirácií v rámci symbolu (stratégie)
                expiries_in_sym = {}
                for p in sym_positions:
                    st = p.get('secType')
                    if st == 'OPT':
                        exp = p.get('expiry', 'Unknown')
                        if exp not in expiries_in_sym: expiries_in_sym[exp] = []
                        expiries_in_sym[exp].append(p)
                    else:
                        # Akcie
                        pos = float(p.get('position', 0))
                        sym_delta += pos
                        sym_lines.append(f"   • STK {pos:+.0f} ks | Delta: {pos:+.2f}")

                for exp, opt_list in expiries_in_sym.items():
                    exp_delta = 0
                    exp_gamma = 0
                    report_lines.append(f"📦 STRATÉGIA: {sym} (Exp: {exp})")
                    for o in opt_list:
                        pos = float(o.get('position', 0))
                        right = o.get('right', '')
                        strike = o.get('strike', 0)
                        
                        # Delta
                        real_delta = o.get('delta')
                        if real_delta is not None:
                            ed = real_delta * pos
                            delta_label = f"{real_delta:+.3f}"
                        else:
                            sign = -1 if right == 'P' else 1
                            ed = 0.5 * pos * sign
                            delta_label = f"{0.5*sign:+.2f} (Est.)"
                        
                        exp_delta += ed
                        
                        # Gamma
                        real_gamma = o.get('gamma')
                        if real_gamma is not None:
                            exp_gamma += real_gamma * pos
                        
                        report_lines.append(f"   • {right} {strike} x{pos:.0f} | Delta: {delta_label}")
                    
                    sym_delta += exp_delta
                    sym_gamma += exp_gamma
                    report_lines.append(f"   📉 Net Delta ({exp}): {exp_delta:+.2f}")
                    report_lines.append(f"   ⚛️ Total Gamma ({exp}): {exp_gamma:.5f}")
                    
                    # Výpočet potrebného pohybu pre drift (ak je Gamma > 0)
                    tol = float(state.gs_drift_tol.get())
                    if abs(exp_gamma) > 1e-7:
                        # Potrebný zostávajúci drift k tolerancii
                        drift_to_go_up = tol - exp_delta
                        drift_to_go_down = -tol - exp_delta
                        
                        move_up = drift_to_go_up / exp_gamma if drift_to_go_up > 0 else 0
                        move_down = drift_to_go_down / exp_gamma if drift_to_go_down < 0 else 0
                        
                        if move_up > 0 or move_down < 0:
                            report_lines.append(f"   🎯 Potrebný pohyb pre Drift (±{tol}):")
                            if move_up > 0: report_lines.append(f"      Hore: {move_up:+.2f} $")
                            if move_down < 0: report_lines.append(f"      Dole: {move_down:+.2f} $")

                    report_lines.append("-" * 30)

                # Kontrola driftu pre globálny status
                tol = float(state.gs_drift_tol.get())
                if abs(sym_delta) > tol:
                    drift_symbols.append(sym)
                    overall_status = "🚨 DRIFT ZISTENÝ!"
                    overall_col = "red"
                
                if sym == active_symbol:
                    has_active = True
                    if abs(sym_delta) > tol:
                        report_lines.append(f"🚨 VAROVANIE: Drift na {sym} prevyšuje {tol}!")

            if not portfolio:
                report_lines.append("⚠️ Žiadne otvorené pozície nenájdené.")
                overall_status = "Žiadne pozície"
                overall_col = "orange"
            
            if active_symbol and not has_active:
                report_lines.append(f"\nℹ️ Pre symbol {active_symbol} nie sú otvorené pozície.")

            # Aktualizácia horného baru s celkovým výsledkom
            final_msg = f"{overall_status} ({timestamp})"
            if drift_symbols:
                final_msg = f"🚨 DRIFT: {', '.join(drift_symbols)} ({timestamp})"
            
            state.root.after(0, lambda m=final_msg, c=overall_col: update_gs_status(state, m, c))
            state.root.after(0, lambda: state.update_gs_analysis_text("\n".join(report_lines)))
            
            if state.gs_auto_monitor_var.get():
                state.root.after(30000, lambda: check_position_gs(state))

        except Exception as e:
            state.root.after(0, lambda: state.update_gs_analysis_text(f"❌ Chyba monitora: {e}\n"))
            state.root.after(0, lambda: update_gs_status(state, "Chyba", "red"))
            
    threading.Thread(target=run, daemon=True).start()
