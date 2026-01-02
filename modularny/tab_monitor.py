#!/usr/bin/env python3
"""
Záložka: Monitor
Monitorovanie existujúcich pozícií
"""
import json
import tkinter as tk
from tkinter import ttk, scrolledtext
import subprocess
import threading
import os


def check_position(state):
    """Skontroluje aktuálny stav pozície vrátane Delta Driftu"""
    if not hasattr(state, 'monitor_result_text'):
        return
    
    state.monitor_result_text.delete(1.0, tk.END)
    state.monitor_result_text.insert(tk.END, "Kontrolujem pozíciu a Delta Drift...\n")
    
    def run():
        # Najprv skúsime nájsť otvorené pozície cez tws_manual_test.py --mode positions
        # Toto je hack, lebo position_monitor.py očakáva konkrétny strike, ale my chceme vidieť všetko
        try:
            cmd_pos = ['python3', 'scripts/tws_manual_test.py', '--mode', 'positions']
            # Musíme nastaviť env vars pre skript
            env = os.environ.copy()
            env['TWS_PORT'] = state.port_var.get()
            
            result = subprocess.run(cmd_pos, capture_output=True, text=True, timeout=15, 
                                  cwd='/home/narbon/Aplikácie/tws-webapp', env=env)
            
            positions_data = []
            if result.returncode == 0:
                try:
                    js = json.loads(result.stdout)
                    positions_data = js.get('positions', [])
                except:
                    pass
            
            # Filtruj pozície pre daný symbol
            symbol = state.symbol_var.get()
            my_positions = [p for p in positions_data if p.get('symbol') == symbol]
            
            if not my_positions:
                 state.root.after(0, lambda: state.monitor_result_text.insert(tk.END, f"\n⚠️ Žiadne otvorené pozície pre {symbol} nájdené v TWS.\n"))
                 # Fallback na pôvodný monitor
            else:
                 # Analyzuj Delta Neutral status
                 total_delta = 0
                 output_lines = [f"📊 ANALÝZA POZÍCIE {symbol}:"]
                 output_lines.append(f"{'Kontrakt':<20} {'Pozícia':<8} {'Cena':<8} {'Delta (est)':<10}")
                 output_lines.append("-" * 60)
                 
                 for p in my_positions:
                     pos = float(p.get('position', 0))
                     sec_type = p.get('secType', '?')
                     
                     delta = 0
                     # Tu by sme mali fetchovať reálnu deltu, zatiaľ len odhadneme
                     # TODO: Implementovať fetch_greeks pre existujúce pozície
                     
                     if sec_type == 'STK':
                         delta = 1.0 * pos
                     elif sec_type == 'OPT':
                         # Veľmi hrubý odhad ak nemáme real-time data
                         # V budúcnosti tu zavoláme tws_fetch_option
                         delta = 0.5 * pos # Placeholder
                     
                     total_delta += delta
                     output_lines.append(f"{sec_type} {p.get('currency')} {p.get('exchange') or ''} {pos:>8.0f} {delta:>10.2f} (est)")
                 
                 output_lines.append("-" * 60)
                 output_lines.append(f"NET DELTA: {total_delta:.2f}")
                 
                 # Odporúčanie
                 if abs(total_delta) > 0.2: # Threshold
                     action = "PREDAJ CALL / KÚP PUT" if total_delta > 0 else "PREDAJ PUT / KÚP CALL"
                     output_lines.append(f"\n⚠️ POZOR: Delta Drift detekovaný!")
                     output_lines.append(f"   Odporúčaná akcia: {action} na vyrovnanie.")
                 else:
                     output_lines.append(f"\n✅ Delta je neutrálna (v rámci tolerancie).")
                 
                 final_text = "\n".join(output_lines)
                 state.root.after(0, lambda: state.monitor_result_text.insert(tk.END, "\n" + final_text + "\n"))
                 return

        except Exception as e:
            state.root.after(0, lambda: state.monitor_result_text.insert(tk.END, f"\nChyba pri analýze delty: {e}\n"))

        # Pôvodný beh position_monitor.py (pre backward compatibility)
        cmd = [
            'python3', 'scripts/position_monitor.py',
            '--symbol', state.symbol_var.get(),
            '--short-strike', state.short_strike_var.get(),
            '--short-expiry', state.short_expiry_var.get(),
            '--port', state.port_var.get()
        ]
        
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=60,
                                   cwd='/home/narbon/Aplikácie/tws-webapp')
            
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

