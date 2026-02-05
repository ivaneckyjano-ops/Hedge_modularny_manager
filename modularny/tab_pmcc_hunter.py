#!/usr/bin/env python3
"""
Záložka: PMCC Hunter
Vyhľadávač ideálnych PMCC (Poor Man's Covered Call) stratégií.
"""
import tkinter as tk
from tkinter import ttk, messagebox
import threading
import subprocess
import json
import os
import sys
import time
from datetime import datetime

class PMCCHunterTab:
    def __init__(self, parent, state):
        self.parent = parent
        self.state = state
        self.frame = ttk.Frame(parent)
        self.frame.pack(fill='both', expand=True)
        
        self.last_pmcc_data = {} # Symbol -> PMCC data
        self.setup_ui()
        
    def setup_ui(self):
        # --- Ovládací panel ---
        ctrl = ttk.LabelFrame(self.frame, text="⚙️ Parametre PMCC", padding=10)
        ctrl.pack(fill='x', padx=10, pady=5)
        
        # Riadok 1: Filtre
        row1 = ttk.Frame(ctrl)
        row1.pack(fill='x', pady=2)
        
        ttk.Label(row1, text="Min Delta LEAPS:").pack(side='left', padx=5)
        self.min_delta_leaps = tk.StringVar(value="0.75")
        ttk.Entry(row1, textvariable=self.min_delta_leaps, width=6).pack(side='left', padx=2)
        
        ttk.Label(row1, text="Max Delta Short:").pack(side='left', padx=(15, 5))
        self.max_delta_short = tk.StringVar(value="0.30")
        ttk.Entry(row1, textvariable=self.max_delta_short, width=6).pack(side='left', padx=2)
        
        ttk.Label(row1, text="Max Spread LEAPS (%):").pack(side='left', padx=(15, 5))
        self.max_spread = tk.StringVar(value="3.0")
        ttk.Entry(row1, textvariable=self.max_spread, width=6).pack(side='left', padx=2)
        
        # Riadok 2: Tlačidlá
        row2 = ttk.Frame(ctrl)
        row2.pack(fill='x', pady=5)
        
        self.status_var = tk.StringVar(value="Pripravený")
        self.status_lbl = ttk.Label(row2, textvariable=self.status_var, foreground="gray")
        self.status_lbl.pack(side='left', padx=5)
        
        self.scan_session_id = 0
        
        ttk.Button(row2, text="🚀 OTVORIŤ V TRADE PLAN", command=self.open_in_trade_plan).pack(side='right', padx=5)
        ttk.Button(row2, text="🚀 VYHĽADAŤ PMCC PRÍLEŽITOSTI", command=self.run_pmcc_scan).pack(side='right', padx=5)
        ttk.Button(row2, text="⏹️ STOP", command=self.stop_scan).pack(side='right', padx=5)
        ttk.Button(row2, text="🔄 Sync zo Swing Huntera", command=self.sync_from_hunter).pack(side='right', padx=5)

        # --- Tabuľka výsledkov ---
        t_frame = ttk.Frame(self.frame)
        t_frame.pack(fill='both', expand=True, padx=10, pady=5)
        
        cols = ('price', 'debit', 'max_profit', 'be_pct', 'extrinsic', 'iv', 'yield', 'status')
        self.tree = ttk.Treeview(t_frame, columns=cols, show='tree headings')
        
        self.tree.heading('#0', text='Symbol')
        self.tree.heading('price', text='Cena Akcie/Opcie')
        self.tree.heading('debit', text='Net Debit')
        self.tree.heading('max_profit', text='Max Profit')
        self.tree.heading('be_pct', text='Break-even %')
        self.tree.heading('extrinsic', text='Extrinsic %')
        self.tree.heading('iv', text='IV %')
        self.tree.heading('yield', text='Ročný Výnos %')
        self.tree.heading('status', text='Status')
        
        self.tree.column('#0', width=100, anchor='w')
        self.tree.column('price', width=120, anchor='center')
        self.tree.column('debit', width=350, anchor='w')
        for col in cols[2:]:
            self.tree.column(col, width=100, anchor='center')
        self.tree.column('status', width=150)
        
        self.tree.pack(side='left', fill='both', expand=True)
        sb = ttk.Scrollbar(t_frame, command=self.tree.yview); sb.pack(side='right', fill='y'); self.tree.configure(yscrollcommand=sb.set)
        
        # --- Poznámka pre vynechané symboly ---
        self.skipped_frame = ttk.Frame(self.frame, padding=(10, 0))
        self.skipped_frame.pack(fill='x')
        ttk.Label(self.skipped_frame, text="Vynechané symboly (žiadna validná PMCC kombinácia):", font=('Arial', 8, 'bold')).pack(side='left')
        self.skipped_var = tk.StringVar(value="—")
        self.skipped_lbl = ttk.Label(self.skipped_frame, textvariable=self.skipped_var, font=('Arial', 8), foreground="gray", wraplength=800)
        self.skipped_lbl.pack(side='left', padx=5)

        self.tree.tag_configure('ideal', background='#c8e6c9') 
        self.tree.tag_configure('warning', background='#fff9c4') 
        self.tree.tag_configure('child', background='#f5f5f5')

    def open_in_trade_plan(self):
        """Otvorí vybraný PMCC v okne Trade Plan pre odoslanie do TWS"""
        selected = self.tree.selection()
        if not selected:
            messagebox.showwarning("PMCC Hunter", "Vyberte symbol v tabuľke.")
            return
            
        parent_id = selected[0]
        # Ak vybral dieťa, nájdeme rodiča
        if self.tree.parent(parent_id):
            parent_id = self.tree.parent(parent_id)
            
        symbol = self.tree.item(parent_id, 'text')
        # Musíme nájsť pôvodné dáta pre tento symbol
        pmcc_data = self.last_pmcc_data.get(symbol)
        
        try:
            from modularny.tab_swing_hunter import open_trade_plan_window
            # Simulujeme summary pre Trade Plan
            summary = {
                'symbol': symbol,
                'price': float(self.tree.item(parent_id, 'values')[0]),
                'option_strategy': 'PMCC', 
                'strategy_label': 'PMCC (Poor Man\'s Covered Call)',
                'pmcc': pmcc_data # Pridáme kompletné dáta o nohách
            }
            open_trade_plan_window(self.state, summary)
        except Exception as e:
            messagebox.showerror("Chyba", f"Nepodarilo sa otvoriť Trade Plan: {e}")

    def sync_from_hunter(self):
        """Získa symboly zo Swing Huntera, ktoré majú býčí signál"""
        summaries = getattr(self.state, 'hunter_symbol_summaries', {})
        bullish_syms = []
        for sym, data in summaries.items():
            # Filter: Cena > MA200 a RSI nie je prekúpené (pod 70)
            price = data.get('price', 0)
            ma200 = data.get('ma200_value')
            rsi = data.get('rsi', 50)
            
            if ma200 and price > ma200 and rsi < 65:
                bullish_syms.append(sym)
        
        if not bullish_syms:
            messagebox.showinfo("PMCC Hunter", "Žiadne nové býčie signály v Swing Hunteri.")
            return
            
        messagebox.showinfo("PMCC Hunter", f"Nájdených {len(bullish_syms)} býčích symbolov: {', '.join(bullish_syms)}")
        self.run_pmcc_scan(bullish_syms)

    def stop_scan(self):
        """Okamžite zastaví bežiaci sken a procesy"""
        self.scan_session_id += 1
        try:
            subprocess.run(['pkill', '-f', 'tws_fetch_pmcc_options.py'], capture_output=True)
        except: pass
        self.status_var.set("⏹️ ZASTAVENÉ")
        self.status_lbl.config(foreground="red")

    def run_pmcc_scan(self, forced_symbols=None):
        symbols = forced_symbols or [s for s, v in getattr(self.state, 'hunter_selected_symbols', {}).items() if v.get()]
        if not symbols:
            messagebox.showwarning("PMCC Hunter", "Vyberte symboly v Swing Hunteri alebo použite Sync.")
            return
            
        self.scan_session_id += 1
        session_id = self.scan_session_id
        
        self.status_var.set("🔍 SKENUJEM OPCIE...")
        self.status_lbl.config(foreground="blue")
        self.tree.delete(*self.tree.get_children())
        self.skipped_var.set("—")
        self.skipped_list = []
        
        threading.Thread(target=self._scan_thread, args=(symbols, session_id), daemon=True).start()

    def _scan_thread(self, symbols, session_id):
        root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        scr = os.path.join(root_dir, 'scripts', 'tws_fetch_pmcc_options.py')
        port = getattr(self.state, 'current_port', "7497")
        
        try:
            min_delta_l = float(self.min_delta_leaps.get())
            max_delta_s = float(self.max_delta_short.get())
            max_spr = float(self.max_spread.get()) / 100.0
            
            for sym in symbols:
                # Kontrola či už nebeží novšia session
                if self.scan_session_id != session_id:
                    return

                cmd = [sys.executable, scr, port, sym]
                res = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
                
                if res.returncode == 0:
                    try:
                        data = json.loads(res.stdout.strip())
                        if data.get('success'):
                            self.process_symbol_data(sym, data, min_delta_l, max_delta_s, max_spr)
                        else:
                            self.skipped_list.append(f"{sym} ({data.get('error')})")
                    except Exception as e:
                        print(f"Error parsing JSON for {sym}: {e}")
                        self.skipped_list.append(sym)
                else:
                    self.skipped_list.append(sym)
                
                # Aktualizovať zoznam vynechaných v reálnom čase
                self.parent.after(0, lambda: self.skipped_var.set(", ".join(self.skipped_list) if self.skipped_list else "—"))
                time.sleep(0.5)
                
            self.parent.after(0, lambda: self.status_var.set(f"✓ HOTOVO ({datetime.now().strftime('%H:%M')})"))
            self.parent.after(0, lambda: self.status_lbl.config(foreground="green"))
            
        except Exception as e:
            print(f"PMCC Scan Error: {e}")
            self.parent.after(0, lambda: self.status_var.set("❌ CHYBA SKENU"))

    def process_symbol_data(self, symbol, data, min_delta_l, max_delta_s, max_spread):
        leaps = data.get('leaps', [])
        shorts = data.get('short', [])
        price = data.get('underlying_price', 0)
        iv = data.get('iv', 0)
        
        # Získame info zo Swing Huntera
        hunter_data = getattr(self.state, 'hunter_symbol_summaries', {}).get(symbol, {})
        is_buying_zone = hunter_data.get('zone') == 'hunt'
        
        valid_pmccs = []
        
        for l in leaps:
            if l['delta'] < min_delta_l: continue
            if l['spread_pct'] > max_spread: continue
            
            intrinsic = max(0, price - l['strike'])
            extrinsic = l['price'] - intrinsic
            ext_pct = (extrinsic / l['price']) * 100 if l['price'] > 0 else 100
            
            for s in shorts:
                if s['delta'] > max_delta_s: continue
                
                net_debit = l['price'] - s['price']
                if net_debit <= 0: continue
                
                strike_diff = s['strike'] - l['strike']
                if strike_diff <= net_debit: continue
                
                max_profit = (strike_diff - net_debit) * 100
                be_price = l['strike'] + net_debit
                be_pct = ((be_price - price) / price) * 100
                
                score = (100 - ext_pct) + (s['theta'] * -10)
                
                # Ročný výnos (Yield) z Short Call nájomného
                # Formula: (Premium / Debit) * (365 / DTE)
                ann_yield = (s['price'] / net_debit) * (365 / s['dte']) * 100 if net_debit > 0 and s['dte'] > 0 else 0
                
                valid_pmccs.append({
                    'symbol': symbol,
                    'price': f"{price:.2f}",
                    'leaps_price': f"{l['price']:.2f}",
                    'short_price': f"{s['price']:.2f}",
                    'leaps_txt': f"LONG {l['strike']} Call (Δ {l['delta']:.2f}) | {l['expiry']} ({l['dte']}d)",
                    'short_txt': f"SHORT {s['strike']} Call (Δ {s['delta']:.2f}) | {s['expiry']} ({s['dte']}d)",
                    'leaps_data': l,
                    'short_data': s,
                    'debit': f"{net_debit:.2f}",
                    'max_profit': f"${max_profit:.0f}",
                    'be_pct': f"{be_pct:+.1f}%",
                    'extrinsic': f"{ext_pct:.1f}%",
                    'iv': f"{iv*100:.1f}%" if iv > 0 else "—",
                    'yield': f"{ann_yield:.1f}%",
                    'status': "🔥 BUY ZONE" if is_buying_zone else "✅ VALIDNÉ",
                    'score': score
                })
        
        if valid_pmccs:
            # Vyberieme najlepší podľa score
            valid_pmccs.sort(key=lambda x: x['score'], reverse=True)
            best = valid_pmccs[0]
            self.last_pmcc_data[symbol] = best
            self.parent.after(0, lambda: self.add_to_tree(best))
        else:
            self.skipped_list.append(symbol)
            self.parent.after(0, lambda: self.skipped_var.set(", ".join(self.skipped_list)))

    def add_to_tree(self, p):
        tag = None
        try:
            ext = float(p['extrinsic'].replace('%',''))
            be = float(p['be_pct'].replace('%','').replace('+',''))
            if ext < 5.0 and be < 2.0: tag = 'ideal'
            elif "BUY ZONE" in p['status']: tag = 'ideal'
            elif ext > 10.0: tag = 'warning'
        except: pass
        
        # Rodičovský riadok
        parent_id = self.tree.insert('', tk.END, text=p['symbol'], values=(
            p['price'], p['debit'], p['max_profit'], p['be_pct'], p['extrinsic'], p['iv'], p['yield'], p['status']
        ), tags=(tag,) if tag else ())
        
        # Detailné riadky (dieťa)
        self.tree.insert(parent_id, tk.END, text="  Leg 1", values=(
            p['leaps_price'], p['leaps_txt'], "", "", "", "", "", ""
        ), tags=('child',))
        self.tree.insert(parent_id, tk.END, text="  Leg 2", values=(
            p['short_price'], p['short_txt'], "", "", "", "", "", ""
        ), tags=('child',))
        
        # Automaticky otvoriť
        self.tree.item(parent_id, open=True)

def create_pmcc_hunter_tab(parent, state):
    return PMCCHunterTab(parent, state)
