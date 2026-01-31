#!/usr/bin/env python3
"""
Záložka: Monitor
Monitorovanie celého portfólia z TWS.
"""
import json
import math
import time
import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox
import subprocess
import threading
import os
import sys
from datetime import datetime

from modularny.tab_swing_watcher import update_watcher_tree


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
        import time # Lokálny import pre istotu v lambde
        watcher_rows = [] # Inicializácia hneď na začiatku vlákna
        try:
            py = sys.executable
            root = os.path.dirname(os.path.dirname(__file__))
            scr = os.path.join(root, 'scripts', 'tws_manual_test.py')
            env = {**os.environ, 'TWS_PORT': state.port_var.get()}
            
            res = subprocess.run([py, scr, '--mode', 'positions'], capture_output=True, text=True, timeout=120, cwd=root, env=env)
            
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

            # Uložiť výsledky do stavu pre ostatné moduly
            state.last_portfolio_data = portfolio
            
            timestamp = datetime.now().strftime("%H:%M:%S")
            report = [f"📊 KOMPLETNÉ PORTFÓLIO ({timestamp})", "="*60]
            div_report = [] # NOVÉ: Pre samostatné okno dividend
            
            # Parametre pre Watchera (získame zo stavu)
            target_opt_pct = 50.0
            target_stk_usd = 12.0
            try:
                target_opt_pct = float(state.monitor_profit_target_pct.get())
                target_stk_usd = float(state.monitor_stock_profit_target_usd.get())
            except: pass

            for sym in sorted(portfolio.keys()):
                sym_pos = portfolio[sym]
                opt_delta, stk_delta, sym_gamma = 0, 0, 0
                
                report.append(f"\n📦 {sym}:")
                for p in sym_pos:
                    try:
                        pos = float(p.get('position', 0))
                        st = p.get('secType', 'STK')
                        unr_pl = float(p.get('unrealizedPNL', 0))
                        avg_cost = float(p.get('avgCost', 0))
                        mkt_price = float(p.get('marketPrice', 0))

                        # Logika pre Watchera (rovnaká ako v Gamma Scalper)
                        is_verified = False
                        calc_pnl = 0.0
                        pl_pct = 0.0 # Inicializácia pre oba typy
                        if st == 'OPT':
                            avg_price_share = avg_cost / 100.0
                            calc_pnl = (mkt_price - avg_price_share) * pos * 100.0
                            if pos < 0 and avg_cost > 0:
                                max_profit = abs(pos) * avg_cost
                                pl_pct = (unr_pl / max_profit) * 100.0 if max_profit > 0 else 0
                            elif pos > 0 and avg_cost > 0:
                                cost_basis = pos * avg_cost
                                pl_pct = (unr_pl / cost_basis) * 100.0 if cost_basis > 0 else 0
                            
                            pl_display = f"{pl_pct:.1f} %"
                            target_display = f"{target_opt_pct:.0f} %"
                            is_target = pl_pct >= target_opt_pct
                            is_warning = pl_pct >= float(state.monitor_profit_warning_pct.get())
                            if abs(calc_pnl - unr_pl) < (abs(unr_pl) * 0.01 + 0.50): is_verified = True
                            display_avg = f"{avg_price_share:.2f}"
                        else:
                            calc_pnl = (mkt_price - avg_cost) * pos
                            # Výpočet % aj pre akcie
                            if abs(pos) > 0 and avg_cost > 0:
                                cost_basis = abs(pos) * avg_cost
                                pl_pct = (unr_pl / cost_basis) * 100.0
                            
                            pl_display = f"{unr_pl:+.2f} $"
                            target_display = f"{target_stk_usd:+.1f} $"
                            is_target = unr_pl >= target_stk_usd
                            is_warning = unr_pl >= (target_stk_usd * 0.5)
                            if abs(calc_pnl - unr_pl) < (abs(unr_pl) * 0.01 + 0.10): is_verified = True
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

                # KONTROLA DIVIDEND (Early Exercise)
                div_info = state.get_dividend_info(sym)
                if div_info and div_info.get('rate', 0) > 0 and div_info.get('ex_date'):
                    try:
                        ex_date = div_info['ex_date']
                        days_to_div = (ex_date - datetime.now().date()).days
                        div_rate = div_info['rate']

                        if 0 <= days_to_div <= 2:
                            # Hľadáme Long Calls na exercise
                            stock_price = 0
                            for p in sym_pos:
                                if p.get('secType') == 'STK':
                                    stock_price = float(p.get('marketPrice') or p.get('lastPrice') or 0)
                            
                            has_long_calls = False
                            exercise_recommended = False
                            
                            for p in sym_pos:
                                if p.get('secType') == 'OPT' and p.get('right') == 'C' and float(p.get('position', 0)) > 0:
                                    has_long_calls = True
                                    strike = float(p.get('strike', 0))
                                    opt_price = float(p.get('marketPrice') or p.get('lastPrice') or 0)
                                    if stock_price > 0 and strike > 0 and opt_price > 0:
                                        intrinsic = max(0, stock_price - strike)
                                        extrinsic = opt_price - intrinsic
                                        if div_rate > extrinsic:
                                            msg = f"✅ DOPORUČUJEME EXERCISE: {sym} (Div ${div_rate:.2f} > Extr ${extrinsic:.2f})"
                                            report.append(f"   🎁 {msg}")
                                            div_report.append(msg)
                                            exercise_recommended = True
                                            break
                                        else:
                                            msg = f"❌ NEVÝHODNÝ EXERCISE: {sym} (Div ${div_rate:.2f} < Extr ${extrinsic:.2f})"
                                            div_report.append(msg)
                                            exercise_recommended = True # Nastavíme na true aby sme neposielali "blíži sa" správu
                                            break
                            
                            if not exercise_recommended:
                                div_report.append(f"⏳ BLÍŽI SA DIVIDENDA: {sym} (Ex-date: {ex_date}) - Nemáte vhodnú Long Call.")
                    except: pass

                report.append("-" * 40)

            final_text = "\n".join(report)
            div_final_text = "\n".join(div_report) if div_report else "Žiadne blízke dividendy (0-2 dni) nevyžadujú akciu."
            
            # Update status baru na zelenú pri úspechu
            if 'modularny.tab_gamma_scalper' in sys.modules:
                from modularny.tab_gamma_scalper import update_gs_status
                state.root.after(0, lambda: update_gs_status(state, "OK", "green"))

            state.root.after(0, lambda: [
                state.monitor_result_text.config(state='normal'),
                state.monitor_result_text.delete(1.0, tk.END),
                state.monitor_result_text.insert(tk.END, final_text),
                state.monitor_result_text.config(state='disabled'),
                state.monitor_div_info_text.config(state='normal') if hasattr(state, 'monitor_div_info_text') else None,
                state.monitor_div_info_text.delete(1.0, tk.END) if hasattr(state, 'monitor_div_info_text') else None,
                state.monitor_div_info_text.insert(tk.END, div_final_text) if hasattr(state, 'monitor_div_info_text') else None,
                state.monitor_div_info_text.config(state='disabled') if hasattr(state, 'monitor_div_info_text') else None,
                update_watcher_tree(state, watcher_rows),
                state.last_update_time_var.set(f"Aktualizované: {timestamp}"),
                setattr(state, 'last_monitor_success_time', datetime.now().timestamp())
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
            # Pridať trace pre automatické ukladanie pri zmene
            state.monitor_selected_symbols[sym].trace_add('write', lambda *args: state.save_settings_file())
        
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
    # Zmeníme usporiadanie: vľavo checkboxy, vpravo okno pre dividendy
    selection_top_frame = ttk.Frame(selection_frame)
    selection_top_frame.pack(fill='both', expand=True)

    left_selection = ttk.Frame(selection_top_frame)
    left_selection.pack(side='left', fill='both', expand=True)

    symbols_canvas = tk.Canvas(left_selection, borderwidth=0, background="#f0f0f0", height=120)
    symbols_frame = ttk.Frame(symbols_canvas)
    symbols_vbar = ttk.Scrollbar(left_selection, orient="vertical", command=symbols_canvas.yview)
    symbols_canvas.configure(yscrollcommand=symbols_vbar.set)

    symbols_vbar.pack(side="right", fill="y")
    symbols_canvas.pack(side="left", fill="both", expand=True)
    
    # Okno pre dividendy vpravo (tam kde bolo prázdno)
    right_info = ttk.LabelFrame(selection_top_frame, text="🎁 Dividend & Exercise Info", padding=5)
    right_info.pack(side='right', fill='both', expand=True, padx=(10, 0))
    
    div_info_text = scrolledtext.ScrolledText(right_info, font=('Arial', 9), height=7, width=40)
    div_info_text.pack(fill='both', expand=True)
    div_info_text.insert(tk.END, "Tu sa zobrazia odporúčania pre Exercise...\n")
    div_info_text.config(state='disabled')
    state.monitor_div_info_text = div_info_text # Uložiť do stavu

    # DÔLEŽITÉ: Uložiť ID okna pre neskoršiu zmenu šírky
    canvas_window_id = symbols_canvas.create_window((0,0), window=symbols_frame, anchor="nw", 
                                  width=200, height=100)
    
    def on_frame_configure(event):
        symbols_canvas.configure(scrollregion=symbols_canvas.bbox("all"))

    symbols_frame.bind("<Configure>", on_frame_configure)
    # Zabezpečiť aby sa checkboxy prispôsobili šírke
    left_selection.bind("<Configure>", lambda e: symbols_canvas.itemconfig(canvas_window_id, width=e.width-20))

    state.monitor_symbols_frame = symbols_frame # Ulož referenciu pre dynamickú aktualizáciu

    # Inicializuj prázdny zoznam checkboxov
    update_symbol_selection_ui(state, [], state.monitor_symbols_frame)

    # Automaticky načítať symboly pri štarte záložky
    state.root.after(100, lambda: load_portfolio_symbols_and_display_ui(state, state.monitor_symbols_frame))
    
    # Funkcia na získanie vybraných symbolov
    def get_selected_symbols(s):
        selected = [sym for sym, var in s.monitor_selected_symbols.items() if var.get()]
        # Automaticky pridať symboly z definovaných vlastných párov
        for pair_data in s.custom_pairs.values():
            pair_syms = pair_data.get('symbols', []) if isinstance(pair_data, dict) else pair_data
            for ps in pair_syms:
                if ps not in selected:
                    selected.append(ps)
        return selected

    # Funkcia na načítanie všetkých symbolov z portfólia a ich zobrazenie
    def load_portfolio_symbols_and_display_ui(s, ui_frame):
        def _run_load_symbols():
            try:
                py = sys.executable
                root = os.path.dirname(os.path.dirname(__file__))
                scr = os.path.join(root, 'scripts', 'tws_manual_test.py')
                env = {**os.environ, 'TWS_PORT': s.port_var.get()}
                
                # Pre zoznam symbolov stačí 120s timeout, ak je portfólio veľké (predtým 60s)
                res = subprocess.run([py, scr, '--mode', 'positions'], capture_output=True, text=True, timeout=120, cwd=root, env=env)

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
    result_frame = ttk.LabelFrame(frame, text="📊 Prehľad Delta & Greeks", padding=10)
    result_frame.pack(fill='both', expand=True, pady=5)
    
    monitor_result_text = scrolledtext.ScrolledText(result_frame, font=('Courier', 11))
    monitor_result_text.pack(fill='both', expand=True)
    state.monitor_result_text = monitor_result_text
    monitor_result_text.config(state='disabled')
