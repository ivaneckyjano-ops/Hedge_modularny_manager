#!/usr/bin/env python3
"""
Záložka: Swing Hunter
Inteligentné hľadač vstupov pomocou RSI a RVI (Akcie a Opcie).
"""
import tkinter as tk
from tkinter import ttk, messagebox
import threading
import os
import sys
import json
import subprocess
import math
from datetime import datetime

# --- MATEMATIKA INDIKÁTOROV ---

def calculate_rsi(candles, period=14):
    if len(candles) < period + 1: return 50.0
    
    closes = [c['close'] for c in candles]
    deltas = [closes[i+1] - closes[i] for i in range(len(closes)-1)]
    
    gains = [d if d > 0 else 0 for d in deltas]
    losses = [abs(d) if d < 0 else 0 for d in deltas]
    
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period
    
    if avg_loss == 0: return 100.0
    
    for i in range(period, len(deltas)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
        
    rs = avg_gain / avg_loss if avg_loss != 0 else 0
    return 100 - (100 / (1 + rs))

def calculate_rvi(candles, period=10):
    """Relative Vigor Index - Štandardný výpočet so sémantickým vyhladzovaním"""
    if len(candles) < period + 4: return 0.0, 0.0
    
    vals = []
    for c in candles:
        body = c['close'] - c['open']
        range_val = c['high'] - c['low']
        vals.append(body / range_val if range_val > 0 else 0)
    
    smoothed_vals = []
    for i in range(3, len(vals)):
        v = (vals[i] + 2*vals[i-1] + 2*vals[i-2] + vals[i-3]) / 6
        smoothed_vals.append(v)
        
    if len(smoothed_vals) < period: return 0.0, 0.0
    
    rvi_line = sum(smoothed_vals[-period:]) / period
    
    rvi_history = []
    for i in range(period, len(smoothed_vals) + 1):
        rvi_history.append(sum(smoothed_vals[i-period:i]) / period)
    
    if len(rvi_history) < 4: return rvi_line, rvi_line
    
    rvi_signal = (rvi_history[-1] + 2*rvi_history[-2] + 2*rvi_history[-3] + rvi_history[-4]) / 6
    
    return rvi_line, rvi_signal

# --- HLAVNÁ LOGIKA ---

def refresh_hunter(state, tree, rsi_p, rvi_p, tf_var, force=False):
    # Získame symboly špecificky vybrané pre HUNTERA
    symbols = [sym for sym, var in state.hunter_selected_symbols.items() if var.get()]
    if not symbols:
        # Ak nie sú vybrané v Hunterovi, pozrieme sa do Monitora (ako záloha/default)
        symbols = [sym for sym, var in state.monitor_selected_symbols.items() if var.get()]
        if not symbols:
            return 

    # Mapa existujúcich riadkov pre inteligentný update bez blikania
    existing_items = {tree.set(item, 'sym'): item for item in tree.get_children()}
    
    # Ak robíme force refresh (tlačidlom), vyčistíme to, čo už nie je vybrané
    if force:
        for sym, item in list(existing_items.items()):
            if sym not in symbols:
                tree.delete(item)
                del existing_items[sym]

    tf = tf_var.get()
    duration = "10 D"
    if "1 hour" in tf: duration = "25 D"
    elif "4 hours" in tf: duration = "60 D"
    elif "day" in tf: duration = "1 Y"
    elif "15 mins" in tf: duration = "5 D"

    def run():
        py = sys.executable
        root_dir = os.path.dirname(os.path.dirname(__file__))
        scr = os.path.join(root_dir, 'scripts', 'tws_fetch_history.py')
        
        for sym in symbols:
            try:
                cmd = [py, scr, '--symbol', sym, '--barSize', tf, '--duration', duration, '--port', str(state.port_var.get())]
                if force: cmd.append('--force')
                
                res = subprocess.run(cmd, capture_output=True, text=True, timeout=30, cwd=root_dir)
                
                if res.returncode == 0:
                    try:
                        data = json.loads(res.stdout.strip())
                        if data.get('success'):
                            candles = data['candles']
                            rsi = calculate_rsi(candles, int(rsi_p.get()))
                            rvi, rvi_sig = calculate_rvi(candles, int(rvi_p.get()))
                            last_price = candles[-1]['close']
                            
                            is_cached = data.get('from_cache', False)
                            cache_label = " (cache)" if is_cached else ""
                            status = "Neutral" + cache_label
                            action = "Čakať"
                            tag = ""
                            
                            if rsi < 30:
                                status = "🔥 PREPREDANÉ" + cache_label
                                tag = "alert"
                                if rvi > rvi_sig:
                                    action = "✅ VSTUP: CALL / BUY"
                                    tag = "buy"
                            elif rsi > 70:
                                status = "❄️ PREKÚPENÉ" + cache_label
                                tag = "alert"
                                if rvi < rvi_sig:
                                    action = "🔻 VSTUP: PUT / SHORT"
                                    tag = "short"
                            
                            def update_ui(s=sym, p=last_price, r=rsi, rv=rvi, rs=rvi_sig, st=status, ac=action, t=tag):
                                vals = (s, f"{p:.2f}", f"{r:.1f}", f"{rv:.4f}", f"{rs:.4f}", st, ac)
                                if s in existing_items:
                                    tree.item(existing_items[s], values=vals, tags=(t,))
                                else:
                                    new_item = tree.insert('', tk.END, values=vals, tags=(t,))
                                    existing_items[s] = new_item

                            state.root.after(0, update_ui)
                    except: pass
            except Exception as e:
                print(f"Hunter Error for {sym}: {e}")

    threading.Thread(target=run, daemon=True).start()

def update_hunter_symbols_ui(state, frame):
    """Dynamicky vytvorí checkboxy pre symboly v Hunterovi"""
    for widget in frame.winfo_children():
        widget.destroy()

    # Zoznam symbolov berieme z hlavného Monitora
    all_symbols = sorted(list(state.monitor_selected_symbols.keys()))
    
    if not all_symbols:
        ttk.Label(frame, text="Najprv zadajte symboly v Monitore.", foreground='gray').pack(side='left', padx=5)
        return

    for sym in all_symbols:
        if sym not in state.hunter_selected_symbols:
            state.hunter_selected_symbols[sym] = tk.BooleanVar(value=True)
            
        cb = ttk.Checkbutton(frame, text=sym, variable=state.hunter_selected_symbols[sym])
        cb.pack(side='left', padx=10)

def create_swing_hunter_tab(parent, state):
    frame = ttk.Frame(parent, padding=15)
    frame.pack(fill='both', expand=True)
    
    header_frame = ttk.Frame(frame)
    header_frame.pack(fill='x', pady=(0, 10))
    
    header = ttk.Label(header_frame, text="🏹 Swing Hunter (Entry Logic: RSI + RVI)", font=('Arial', 12, 'bold'))
    header.pack(side='left')

    # --- VÝBER SYMBOLOV ---
    selection_frame = ttk.LabelFrame(frame, text="🎯 Symboly na sledovanie signálov (Loviť len tieto)", padding=10)
    selection_frame.pack(fill='x', pady=5)
    
    symbols_container = ttk.Frame(selection_frame)
    symbols_container.pack(fill='x', side='left', expand=True)
    
    btn_sync = ttk.Button(selection_frame, text="🔄 Sync", width=8,
                          command=lambda: update_hunter_symbols_ui(state, symbols_container))
    btn_sync.pack(side='right', padx=5)
    
    update_hunter_symbols_ui(state, symbols_container)
    state.hunter_symbols_container = symbols_container

    # --- NASTAVENIA ---
    ctrl_frame = ttk.LabelFrame(frame, text="⚙️ Nastavenia indikátorov", padding=10)
    ctrl_frame.pack(fill='x', pady=5)
    
    ttk.Label(ctrl_frame, text="RSI Period:").pack(side='left', padx=5)
    rsi_period = tk.StringVar(value="14")
    ttk.Entry(ctrl_frame, textvariable=rsi_period, width=5).pack(side='left', padx=2)

    ttk.Label(ctrl_frame, text="RVI Period:").pack(side='left', padx=(15, 5))
    rvi_period = tk.StringVar(value="10")
    ttk.Entry(ctrl_frame, textvariable=rvi_period, width=5).pack(side='left', padx=2)

    ttk.Label(ctrl_frame, text="Timeframe:").pack(side='left', padx=(15, 5))
    timeframe_var = tk.StringVar(value="1 hour")
    ttk.Combobox(ctrl_frame, textvariable=timeframe_var, values=["15 mins", "1 hour", "4 hours", "1 day"], width=10).pack(side='left', padx=5)

    # --- TABUĽKA SIGNÁLOV ---
    table_label = ttk.Label(frame, text="📊 Live Entry Signals", font=('Arial', 10, 'bold'))
    table_label.pack(fill='x', pady=(15, 0))

    table_frame = ttk.Frame(frame)
    table_frame.pack(fill='both', expand=True, pady=10)
    
    cols = ('sym', 'price', 'rsi', 'rvi', 'rvi_sig', 'status', 'action')
    tree = ttk.Treeview(table_frame, columns=cols, show='headings')
    
    tree.heading('sym', text='Symbol'); tree.column('sym', width=80, anchor='center')
    tree.heading('price', text='Trh. Cena'); tree.column('price', width=100, anchor='center')
    tree.heading('rsi', text='RSI'); tree.column('rsi', width=80, anchor='center')
    tree.heading('rvi', text='RVI'); tree.column('rvi', width=80, anchor='center')
    tree.heading('rvi_sig', text='RVI Signal'); tree.column('rvi_sig', width=100, anchor='center')
    tree.heading('status', text='Stav'); tree.column('status', width=150, anchor='center')
    tree.heading('action', text='Odporúčanie'); tree.column('action', width=180, anchor='center')
    
    tree.pack(side='left', fill='both', expand=True)
    
    sb = ttk.Scrollbar(table_frame, orient="vertical", command=tree.yview)
    sb.pack(side='right', fill='y')
    tree.configure(yscrollcommand=sb.set)
    
    tree.tag_configure('buy', background='#c8e6c9', foreground='black')
    tree.tag_configure('short', background='#ffcdd2', foreground='black')
    tree.tag_configure('alert', background='#fff9c4', foreground='black')

    state.hunter_tree = tree
    state.hunter_rsi_p = rsi_period
    state.hunter_rvi_p = rvi_period
    state.hunter_tf_v = timeframe_var

    btn_refresh = ttk.Button(frame, text="🏹 VYHĽADAŤ PRÍLEŽITOSTI", 
                             command=lambda: refresh_hunter(state, tree, rsi_period, rvi_period, timeframe_var, force=True))
    btn_refresh.pack(pady=10)

    info_label = ttk.Label(frame, text="💡 Tip: Sledujte súlad RSI a RVI pre vstup. Hunter používa Smart Cache pre úsporu API.", 
                           font=('Arial', 8, 'italic'), foreground='gray')
    info_label.pack(fill='x', pady=5)

    return frame
