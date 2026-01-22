#!/usr/bin/env python3
"""
Záložka: Monitor
Monitorovanie celého portfólia z TWS.
"""
import json
import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox
import subprocess
import threading
import os
import sys
from datetime import datetime


def check_position(state, selected_symbols=None):
    """Skontroluje portfólio kompletne alebo iba vybrané symboly
    
    Args:
        state: SharedState objekt
        selected_symbols: List symbolov na monitorovanie (None = všetky)
    """
    if not hasattr(state, 'monitor_result_text'):
        print("Chyba: monitor_result_text nie je inicializovaný")
        return
    
    try:
        state.monitor_result_text.config(state='normal')
        state.monitor_result_text.delete(1.0, tk.END)
        state.monitor_result_text.insert(tk.END, "🚀 Načítavam kompletné portfólio z TWS...\n")
        state.monitor_result_text.config(state='disabled')
    except Exception as e:
        print(f"Chyba pri inicializácii monitor_result_text: {e}")
        return
    
    def run():
        try:
            py = sys.executable
            root = os.path.dirname(os.path.dirname(__file__))
            scr = os.path.join(root, 'scripts', 'tws_manual_test.py')
            env = {**os.environ, 'TWS_PORT': state.port_var.get()}
            
            res = subprocess.run([py, scr, '--mode', 'positions'], capture_output=True, text=True, timeout=20, cwd=root, env=env)
            
            if res.returncode != 0:
                error_msg = res.stderr if res.stderr else "Neznáma chyba"
                # Ak máme funkciu na update statusu, použiť ju
                if 'modularny.tab_gamma_scalper' in sys.modules:
                    from modularny.tab_gamma_scalper import update_gs_status
                    state.root.after(0, lambda: update_gs_status(state, "Chyba", "red"))
                
                state.root.after(0, lambda: [state.monitor_result_text.config(state='normal'), state.monitor_result_text.insert(tk.END, f"\n❌ Chyba pripojenia k TWS.\n{error_msg}\n"), state.monitor_result_text.config(state='disabled')])
                return

            if not res.stdout or not res.stdout.strip():
                state.root.after(0, lambda: [state.monitor_result_text.config(state='normal'), state.monitor_result_text.insert(tk.END, "\n❌ Skript nevrátil žiadne dáta.\n"), state.monitor_result_text.config(state='disabled')])
                return

            # Odstráň varovania zo stdout (ak sú tam)
            stdout_clean = res.stdout.strip()
            # Nájdi JSON objekt (začína { a končí })
            json_start = stdout_clean.find('{')
            json_end = stdout_clean.rfind('}') + 1
            if json_start >= 0 and json_end > json_start:
                stdout_clean = stdout_clean[json_start:json_end]
            
            try:
                data = json.loads(stdout_clean)
            except json.JSONDecodeError as je:
                error_detail = f"Chyba parsovania JSON: {je}\n"
                error_detail += f"Výstup skriptu (prvých 500 znakov):\n{res.stdout[:500]}\n"
                if res.stderr:
                    error_detail += f"Stderr: {res.stderr[:200]}\n"
                state.root.after(0, lambda: [state.monitor_result_text.config(state='normal'), state.monitor_result_text.insert(tk.END, f"\n❌ {error_detail}\n"), state.monitor_result_text.config(state='disabled')])
                return
            
            positions = data.get('positions', [])
            
            # Filtrovať iba vybrané symboly
            if selected_symbols and isinstance(selected_symbols, (list, set)):
                positions = [p for p in positions if p.get('symbol') in selected_symbols]
            
            if not positions:
                msg = "\n⚠️ Žiadne vybrané pozície nenájdené.\n" if selected_symbols else "\n⚠️ Žiadne otvorené pozície nenájdené.\n"
                state.root.after(0, lambda: [state.monitor_result_text.config(state='normal'), state.monitor_result_text.insert(tk.END, msg), state.monitor_result_text.config(state='disabled')])
                return

            # Zoskupenie
            portfolio = {}
            for p in positions:
                if not isinstance(p, dict):
                    continue
                s = p.get('symbol', '???')
                if s and s != '???' and s.strip():
                    portfolio.setdefault(s, []).append(p)

            timestamp = datetime.now().strftime("%H:%M:%S")
            report = [f"📊 KOMPLETNÉ PORTFÓLIO ({timestamp})", "="*60]
            
            for sym in sorted(portfolio.keys()):
                sym_pos = portfolio[sym]
                opt_delta, stk_delta, sym_gamma = 0, 0, 0
                
                report.append(f"\n📦 {sym}:")
                for p in sym_pos:
                    try:
                        pos = float(p.get('position', 0))
                        st = p.get('secType', 'STK')
                        
                        if st == 'OPT':
                            # Bezpečná konverzia None na 0
                            delta_val = p.get('delta')
                            gamma_val = p.get('gamma')
                            d = float(delta_val) if delta_val is not None else 0.0
                            g = float(gamma_val) if gamma_val is not None else 0.0
                            opt_delta += d * pos
                            sym_gamma += g * pos
                            right = p.get('right', '?') or '?'
                            strike = p.get('strike', '?') or '?'
                            expiry = p.get('expiry', '?') or '?'
                            delta_str = f"{d:+.3f}" if delta_val is not None else "N/A"
                            report.append(f"   • {right} {strike} ({expiry}) x{pos:.0f} | Δ {delta_str}")
                        else:
                            stk_delta += pos
                            report.append(f"   • AKCIE x{pos:+.0f} | Δ {pos:+.0f}")
                    except (ValueError, TypeError) as e:
                        report.append(f"   ⚠️ Chyba pri spracovaní pozície: {e}")
                        continue
                
                net_delta = opt_delta + stk_delta
                report.append(f"   👉 NET DELTA: {net_delta:+.3f} | Gamma: {sym_gamma:.5f}")
                
                # Jednoduchá kontrola driftu pre prehľad
                try:
                    if hasattr(state, 'ticker_settings') and sym in state.ticker_settings:
                        ticker_setting = state.ticker_settings[sym]
                        if isinstance(ticker_setting, dict):
                            t = float(ticker_setting.get('drift_tolerance', 0.20))
                        else:
                            t = 0.20
                    else:
                        t = 0.20
                except (ValueError, TypeError, AttributeError):
                    t = 0.20
                if abs(net_delta) > t: report.append(f"   🚨 DRIFT DETEKOVANÝ (>±{t:.2f})")
                report.append("-" * 40)

            final_text = "\n".join(report)
            
            # Update status baru na zelenú pri úspechu
            if 'modularny.tab_gamma_scalper' in sys.modules:
                from modularny.tab_gamma_scalper import update_gs_status
                state.root.after(0, lambda: update_gs_status(state, "OK", "green"))

            state.root.after(0, lambda: [
                state.monitor_result_text.config(state='normal'),
                state.monitor_result_text.delete(1.0, tk.END),
                state.monitor_result_text.insert(tk.END, final_text),
                state.monitor_result_text.config(state='disabled')
            ])

        except Exception as e:
            import traceback
            error_trace = traceback.format_exc()
            error_msg = f"\n❌ Chyba: {e}\n\nDetail:\n{error_trace}\n"
            state.root.after(0, lambda: [state.monitor_result_text.config(state='normal'), state.monitor_result_text.insert(tk.END, error_msg), state.monitor_result_text.config(state='disabled')])
            print(f"Monitor error: {e}")
            print(error_trace)
    
    threading.Thread(target=run, daemon=True).start()


def update_symbol_selection_ui(state, symbols, parent_frame):
    """Aktualizuje zoznam checkboxov pre výber symbolov"""
    # Vyčistiť existujúce checkboxy
    for widget in parent_frame.winfo_children():
        widget.destroy()
    
    if not symbols:
        ttk.Label(parent_frame, text="Žiadne symboly nenájdené. Kliknite na Aktualizovať.").pack()
        return

    # Vytvoriť checkboxy v mriežke (grid)
    cols = 4
    for i, sym in enumerate(sorted(symbols)):
        if sym not in state.monitor_selected_symbols:
            state.monitor_selected_symbols[sym] = tk.BooleanVar(value=True)
        
        cb = ttk.Checkbutton(parent_frame, text=sym, variable=state.monitor_selected_symbols[sym])
        cb.grid(row=i // cols, column=i % cols, sticky='w', padx=10, pady=2)


def select_all_symbols(state, value):
    """Vyberie/zruší výber všetkých symbolov v zozname"""
    for var in state.monitor_selected_symbols.values():
        var.set(value)

def clear_symbol_list(state, ui_frame):
    """Úplne vymaže zoznam symbolov a resetuje nastavenia"""
    if not messagebox.askyesno("Vymazať zoznam", "Naozaj chcete vymazať všetky symboly zo zoznamu pre sledovanie?"):
        return
    
    # Vyčistiť slovník v stave
    state.monitor_selected_symbols = {}
    
    # Vymazať UI prvky
    for widget in ui_frame.winfo_children():
        widget.destroy()
    
    # Uložiť prázdny stav do súboru
    state.save_settings_file()
    
    ttk.Label(ui_frame, text="Zoznam je prázdny. Použite 'Zistiť aktuálne pozície'.").pack(padx=10, pady=10)

def create_monitor_tab(parent, state):
    """Záložka pre monitoring celého portfólia"""
    frame = ttk.Frame(parent, padding=10)
    frame.pack(fill='both', expand=True)
    
    # Horná lišta
    top_bar = ttk.Frame(frame)
    top_bar.pack(fill='x', pady=5)
    
    # Sekcia pre výber symbolov
    selection_frame = ttk.LabelFrame(frame, text="🎯 Symboly na monitorovanie/hedžovanie (označte, ktoré chcete sledovať)", padding=10)
    selection_frame.pack(fill='x', pady=5)
    
    # Scrollovateľný rámik pre checkboxy
    symbols_canvas = tk.Canvas(selection_frame, borderwidth=0, background="#f0f0f0")
    symbols_frame = ttk.Frame(symbols_canvas)
    symbols_vbar = ttk.Scrollbar(selection_frame, orient="vertical", command=symbols_canvas.yview)
    symbols_canvas.configure(yscrollcommand=symbols_vbar.set)

    symbols_vbar.pack(side="right", fill="y")
    symbols_canvas.pack(side="left", fill="both", expand=True)
    
    # DÔLEŽITÉ: Uložiť ID okna pre neskoršiu zmenu šírky
    canvas_window_id = symbols_canvas.create_window((0,0), window=symbols_frame, anchor="nw", 
                                  width=selection_frame.winfo_width(), height=100)
    
    def on_frame_configure(event):
        symbols_canvas.configure(scrollregion=symbols_canvas.bbox("all"))
        # Použiť uložené ID okna
        symbols_canvas.itemconfig(canvas_window_id, width=selection_frame.winfo_width())

    symbols_frame.bind("<Configure>", on_frame_configure)
    selection_frame.bind("<Configure>", lambda e: symbols_canvas.itemconfig(canvas_window_id, width=e.width))

    state.monitor_symbols_frame = symbols_frame # Ulož referenciu pre dynamickú aktualizáciu

    # Inicializuj prázdny zoznam checkboxov
    update_symbol_selection_ui(state, [], state.monitor_symbols_frame)

    # Automaticky načítať symboly pri štarte záložky
    state.root.after(100, lambda: load_portfolio_symbols_and_display_ui(state, state.monitor_symbols_frame))
    
    # Funkcia na získanie vybraných symbolov
    def get_selected_symbols(s):
        return [sym for sym, var in s.monitor_selected_symbols.items() if var.get()]

    # Funkcia na načítanie všetkých symbolov z portfólia a ich zobrazenie
    def load_portfolio_symbols_and_display_ui(s, ui_frame):
        def _run_load_symbols():
            try:
                py = sys.executable
                root = os.path.dirname(os.path.dirname(__file__))
                scr = os.path.join(root, 'scripts', 'tws_manual_test.py')
                env = {**os.environ, 'TWS_PORT': s.port_var.get()}
                
                # Pre zoznam symbolov stačí 60s timeout, ak je portfólio veľké
                res = subprocess.run([py, scr, '--mode', 'positions'], capture_output=True, text=True, timeout=60, cwd=root, env=env)
                
                if res.returncode != 0:
                    error_msg = res.stderr if res.stderr else "Neznáma chyba"
                    s.root.after(0, lambda: messagebox.showerror("Chyba načítania symbolov", f"Nepodarilo sa načítať symboly: {error_msg}"))
                    return

                stdout_clean = res.stdout.strip()
                json_start = stdout_clean.find('{')
                json_end = stdout_clean.rfind('}') + 1
                if json_start >= 0 and json_end > json_start:
                    stdout_clean = stdout_clean[json_start:json_end]
                
                data = json.loads(stdout_clean)
                positions = data.get('positions', [])
                
                unique_symbols = sorted(list(set(p.get('symbol') for p in positions if p.get('symbol'))))
                
                s.root.after(0, lambda: update_symbol_selection_ui(s, unique_symbols, ui_frame))

            except Exception as ex:
                import traceback
                error_trace = traceback.format_exc()
                # Zachytiť hodnoty ex a error_trace pomocou predvolených argumentov v lambde
                s.root.after(0, lambda e=ex, et=error_trace: messagebox.showerror("Chyba načítania symbolov", f"Chyba: {e}\n{et}"))

        threading.Thread(target=_run_load_symbols, daemon=True).start()

    # Tlačidlá - rozdelené do dvoch riadkov pre lepšiu šírku
    btn_row1 = ttk.Frame(selection_frame)
    btn_row1.pack(fill='x', pady=(10, 2))
    
    btn_row2 = ttk.Frame(selection_frame)
    btn_row2.pack(fill='x', pady=(0, 0))
    
    ttk.Button(btn_row1, text="🔍 Zistiť aktuálne pozície", 
               command=lambda: load_portfolio_symbols_and_display_ui(state, state.monitor_symbols_frame))\
              .pack(side='left', padx=5)

    ttk.Button(btn_row1, text="🔄 AKTUALIZOVAŤ VYBRANÉ", 
               command=lambda: check_position(state, get_selected_symbols(state)))\
              .pack(side='left', padx=5)

    ttk.Button(btn_row1, text="🔄 AKTUALIZOVAŤ VŠETKY", 
               command=lambda: check_position(state, None))\
              .pack(side='left', padx=5)
              
    ttk.Button(btn_row2, text="✅ Vybrať všetko", command=lambda: select_all_symbols(state, True)).pack(side='left', padx=5)
    ttk.Button(btn_row2, text="❌ Zrušiť všetko", command=lambda: select_all_symbols(state, False)).pack(side='left', padx=5)
    
    ttk.Button(btn_row2, text="🗑️ VYMAZAŤ ZOZNAM", 
               command=lambda: clear_symbol_list(state, state.monitor_symbols_frame))\
              .pack(side='right', padx=5)

    # Monitor výsledok
    result_frame = ttk.LabelFrame(frame, text="📊 Prehľad vybraných pozícií", padding=10)
    result_frame.pack(fill='both', expand=True, pady=5)
    
    monitor_result_text = scrolledtext.ScrolledText(result_frame, font=('Courier', 11))
    monitor_result_text.pack(fill='both', expand=True)
    state.monitor_result_text = monitor_result_text
    monitor_result_text.config(state='disabled')