#!/usr/bin/env python3
"""
Záložka: Monitor
Monitorovanie existujúcich pozícií
"""
import tkinter as tk
from tkinter import ttk, scrolledtext
import subprocess
import threading
import os


def check_position(state):
    """Skontroluje aktuálny stav pozície"""
    if not hasattr(state, 'monitor_result_text'):
        return
    
    state.monitor_result_text.delete(1.0, tk.END)
    state.monitor_result_text.insert(tk.END, "Kontrolujem pozíciu...\n")
    
    def run():
        cmd = [
            'python', 'scripts/position_monitor.py',
            '--symbol', state.symbol_var.get(),
            '--short-strike', state.short_strike_var.get(),
            '--short-expiry', state.short_expiry_var.get(),
            '--port', state.port_var.get()
        ]
        
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=60,
                                   cwd='/home/narbon/Aplikácie/tws-webapp',
                                   env={**os.environ, 'PATH': '/home/narbon/Aplikácie/tws-webapp/venv/bin:' + os.environ.get('PATH', '')})
            
            output = result.stdout + result.stderr
            state.root.after(0, lambda: state.monitor_result_text.insert(tk.END, output))
        except subprocess.TimeoutExpired:
            state.root.after(0, lambda: state.monitor_result_text.insert(tk.END, "Timeout - skúste znova"))
        except Exception as e:
            state.root.after(0, lambda: state.monitor_result_text.insert(tk.END, f"Chyba: {e}"))
    
    threading.Thread(target=run, daemon=True).start()


def create_monitor_tab(parent, state):
    """Záložka pre monitoring pozície"""
    frame = ttk.LabelFrame(parent, text="Parametre monitoringu", padding=10)
    frame.pack(fill='x', padx=10, pady=10)
    
    row1 = ttk.Frame(frame)
    row1.pack(fill='x', pady=5)
    
    ttk.Label(row1, text="Symbol:").pack(side='left', padx=5)
    ttk.Entry(row1, textvariable=state.symbol_var, width=10).pack(side='left', padx=5)
    
    ttk.Label(row1, text="Short Strike:").pack(side='left', padx=5)
    ttk.Entry(row1, textvariable=state.short_strike_var, width=10).pack(side='left', padx=5)
    
    ttk.Label(row1, text="Expirácia:").pack(side='left', padx=5)
    monitor_expiry_combo = ttk.Combobox(row1, textvariable=state.short_expiry_var, width=12)
    monitor_expiry_combo.pack(side='left', padx=5)
    
    # Ulož referenciu pre aktualizáciu
    state.monitor_expiry_combo = monitor_expiry_combo
    
    # Aktualizuj hodnoty ak sú dostupné
    if state.available_expiries:
        monitor_expiry_combo['values'] = state.available_expiries
    
    ttk.Label(row1, text="Typ:").pack(side='left', padx=5)
    ttk.Combobox(row1, textvariable=state.option_type_var, values=["PUT", "CALL"], width=6).pack(side='left', padx=5)
    
    btn_frame = ttk.Frame(frame)
    btn_frame.pack(fill='x', pady=10)
    
    ttk.Button(btn_frame, text="👁️ SKONTROLOVAŤ TERAZ", command=lambda: check_position(state)).pack(side='left', padx=5)
    
    # Monitor výsledok
    result_frame = ttk.LabelFrame(parent, text="Stav pozície", padding=10)
    result_frame.pack(fill='both', expand=True, padx=10, pady=10)
    
    monitor_result_text = scrolledtext.ScrolledText(result_frame, height=15, font=('Courier', 11))
    monitor_result_text.pack(fill='both', expand=True)
    
    # Ulož referenciu
    state.monitor_result_text = monitor_result_text

