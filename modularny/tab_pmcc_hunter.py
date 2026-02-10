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

class ToolTip:
    """Pomocná trieda pre zobrazenie vyskakovacích bublín (tooltips)"""
    def __init__(self, widget, text):
        self.widget = widget
        self.text = text
        self.tip_window = None
        widget.bind("<Enter>", self.show_tip)
        widget.bind("<Leave>", self.hide_tip)

    def show_tip(self, event=None):
        if self.tip_window or not self.text: return
        x, y, _cx, cy = self.widget.bbox("insert")
        x = x + self.widget.winfo_rootx() + 25
        y = y + cy + self.widget.winfo_rooty() + 25
        self.tip_window = tw = tk.Toplevel(self.widget)
        tw.wm_overrideredirect(True)
        tw.wm_geometry(f"+{x}+{y}")
        label = tk.Label(tw, text=self.text, justify=tk.LEFT,
                      background="#ffffe0", relief=tk.SOLID, borderwidth=1,
                      font=("tahoma", "8", "normal"), padx=5, pady=2)
        label.pack(ipadx=1)

    def hide_tip(self, event=None):
        tw = self.tip_window
        self.tip_window = None
        if tw: tw.destroy()

class PMCCHunterTab:
    def __init__(self, parent, state):
        self.parent = parent
        self.state = state
        self.frame = ttk.Frame(parent)
        self.frame.pack(fill='both', expand=True)
        
        self.last_pmcc_data = {} # Symbol -> Aktuálne vybratá PMCC data
        self.all_pmcc_options = {} # Symbol -> Zoznam všetkých validných PMCC kombinácií
        self.cache_file = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'cache', 'pmcc_cache.json')
        self.scan_session_id = 0
        self.skipped_list = []
        
        self.setup_ui()
        self.load_cache()

    def setup_ui(self):
        # --- Horný panel s ovládaním a symbolmi ---
        top_panel = ttk.Frame(self.frame)
        top_panel.pack(fill='x', padx=10, pady=5)
        
        # 1. SEKCIÁ SYMBOLY (vľavo)
        sym_frame = ttk.LabelFrame(top_panel, text="📋 Zoznam symbolov (vlastný)", padding=5)
        sym_frame.pack(side='left', fill='both', expand=True, padx=(0, 5))
        
        ttk.Label(sym_frame, text="Zadajte symboly (oddelené čiarkou, medzerou alebo novým riadkom):", font=('Arial', 7)).pack(anchor='w')
        
        self.sym_text = tk.Text(sym_frame, height=4, width=30, font=('Arial', 9), undo=True)
        self.sym_text.pack(side='left', fill='both', expand=True, pady=2)
        
        sym_sb = ttk.Scrollbar(sym_frame, command=self.sym_text.yview)
        sym_sb.pack(side='right', fill='y')
        self.sym_text.configure(yscrollcommand=sym_sb.set)
        
        initial_syms = ", ".join(getattr(self.state, 'pmcc_symbols', []))
        self.sym_text.insert('1.0', initial_syms)
        self.sym_text.edit_modified(False)
        self.sym_text.bind('<<Modified>>', self.on_symbols_text_changed)

        # 2. SEKCIA PARAMETRE (vpravo)
        ctrl = ttk.LabelFrame(top_panel, text="⚙️ Parametre PMCC", padding=10)
        ctrl.pack(side='right', fill='both', padx=(5, 0))
        
        f_row1 = ttk.Frame(ctrl)
        f_row1.pack(fill='x', pady=1)
        ttk.Label(f_row1, text="Min Δ LEAPS:").pack(side='left')
        self.min_delta_leaps = tk.StringVar(value="0.75")
        ttk.Entry(f_row1, textvariable=self.min_delta_leaps, width=6).pack(side='right')

        f_row2 = ttk.Frame(ctrl)
        f_row2.pack(fill='x', pady=1)
        ttk.Label(f_row2, text="Max Δ Short:").pack(side='left')
        self.max_delta_short = tk.StringVar(value="0.30")
        ttk.Entry(f_row2, textvariable=self.max_delta_short, width=6).pack(side='right')

        f_row3 = ttk.Frame(ctrl)
        f_row3.pack(fill='x', pady=1)
        ttk.Label(f_row3, text="Max Spread %:").pack(side='left')
        self.max_spread = tk.StringVar(value="3.0")
        ttk.Entry(f_row3, textvariable=self.max_spread, width=6).pack(side='right')
        
        # --- Riadok s tlačidlami pod horným panelom ---
        btn_panel = ttk.Frame(self.frame)
        btn_panel.pack(fill='x', padx=10, pady=2)
        
        self.status_var = tk.StringVar(value="Pripravený")
        self.status_lbl = ttk.Label(btn_panel, textvariable=self.status_var, foreground="gray")
        self.status_lbl.pack(side='left', padx=5)
        
        ttk.Button(btn_panel, text="🚀 OTVORIŤ V TRADE PLAN", command=self.open_in_trade_plan).pack(side='right', padx=2)
        ttk.Button(btn_panel, text="🚀 VYHĽADAŤ PMCC", command=self.run_pmcc_scan).pack(side='right', padx=2)
        ttk.Button(btn_panel, text="⏹️ STOP", command=self.stop_scan).pack(side='right', padx=2)
        ttk.Button(btn_panel, text="🔄 Sync zo Swing Huntera", command=self.sync_from_hunter).pack(side='right', padx=2)

        # --- Tabuľka výsledkov ---
        t_frame = ttk.Frame(self.frame)
        t_frame.pack(fill='both', expand=True, padx=10, pady=5)
        
        cols = ('price', 'rsi', 'debit', 'c_pct', 'lev', 'mont', 'max_profit', 'be_pct', 'extrinsic', 'iv', 'yield', 'oi', 'liq', 'status')
        self.tree = ttk.Treeview(t_frame, columns=cols, show='tree headings')
        
        self.tree.heading('#0', text='Symbol', command=lambda: self.treeview_sort_column('#0', False))
        self.tree.heading('price', text='Cena/Opc', command=lambda: self.treeview_sort_column('price', False))
        self.tree.heading('rsi', text='RSI', command=lambda: self.treeview_sort_column('rsi', False))
        self.tree.heading('debit', text='Debit', command=lambda: self.treeview_sort_column('debit', False))
        self.tree.heading('c_pct', text='C %', command=lambda: self.treeview_sort_column('c_pct', False))
        self.tree.heading('lev', text='Lev', command=lambda: self.treeview_sort_column('lev', False))
        self.tree.heading('mont', text='Mont', command=lambda: self.treeview_sort_column('mont', False))
        self.tree.heading('max_profit', text='MP $', command=lambda: self.treeview_sort_column('max_profit', False))
        self.tree.heading('be_pct', text='BE %', command=lambda: self.treeview_sort_column('be_pct', False))
        self.tree.heading('extrinsic', text='Ex %', command=lambda: self.treeview_sort_column('extrinsic', False))
        self.tree.heading('iv', text='IV %', command=lambda: self.treeview_sort_column('iv', False))
        self.tree.heading('yield', text='Yield %', command=lambda: self.treeview_sort_column('yield', False))
        self.tree.heading('oi', text='OI', command=lambda: self.treeview_sort_column('oi', False))
        self.tree.heading('liq', text='Liq', command=lambda: self.treeview_sort_column('liq', False))
        self.tree.heading('status', text='Status', command=lambda: self.treeview_sort_column('status', False))
        
        self.tree.column('#0', width=100, anchor='w')
        self.tree.column('price', width=85, anchor='center')
        self.tree.column('rsi', width=40, anchor='center')
        self.tree.column('debit', width=65, anchor='center')
        self.tree.column('c_pct', width=55, anchor='center')
        self.tree.column('lev', width=50, anchor='center')
        self.tree.column('mont', width=50, anchor='center')
        self.tree.column('max_profit', width=75, anchor='center')
        self.tree.column('be_pct', width=60, anchor='center')
        self.tree.column('extrinsic', width=100, anchor='center')
        self.tree.column('iv', width=75, anchor='center')
        self.tree.column('yield', width=85, anchor='center')
        self.tree.column('oi', width=55, anchor='center')
        self.tree.column('liq', width=45, anchor='center')
        self.tree.column('status', width=400, anchor='w')

        self.tree.bind("<Motion>", self.handle_header_tooltips)
        self.tree.bind("<Button-3>", self.show_context_menu)
        
        self.header_tooltips = {
            'price': "Aktuálna cena akcie (alebo prémia opcie v detaile)",
            'rsi': "Relative Strength Index (z Denného TF). Nad 65 = Prekúpené (Riziko otočenia).",
            'debit': "Net Debit - Celková cena za kombináciu (Leg1 - Leg2)",
            'c_pct': "Cushion % - (Short Premium / Net Debit) * 100. Kolko % nákladov vráti jeden výpis.",
            'lev': "Leverage Quality - (Net Debit / Stock Price). Pomer ceny k akcii. Ideálne 0.4 - 0.6.",
            'mont': "Recovery Months (ERT) - (Extrinsic Long / Short Premium). Kolko mesiacov sa spláca časová hodnota LEAPS.",
            'max_profit': "Max Profit - Maximálny teoretický zisk ak je akcia pri expirácii na strike Short Callu.",
            'be_pct': "Break-Even % - O koľko % sa musí pohnúť akcia, aby bol obchod na nule.",
            'extrinsic': "Extrinsic % - Pomer časovej hodnoty k celkovej pohltenej cene LEAPS opcie.",
            'iv': "Implied Volatility - Očakávaná volatilita trhom.",
            'yield': "Ročný Výnos % - Annualizovaný výnos z pravidelného vypisovania Short Callu.",
            'oi': "Open Interest - Počet otvorených kontraktov. Vyššie = lepšia likvidita.",
            'liq': "Liquidity flag - Rýchla heuristika (OI/Volume/Spread/BidSize) indikujúca obchodovateľnosť.",
            'status': "Aktuálny stav signálu a zóny (HUNT = Touch BB/MA200)"
        }
        
        self.tree.pack(side='left', fill='both', expand=True)
        sb = ttk.Scrollbar(t_frame, command=self.tree.yview); sb.pack(side='right', fill='y'); self.tree.configure(yscrollcommand=sb.set)
        
        self.skipped_frame = ttk.Frame(self.frame, padding=(10, 0))
        self.skipped_frame.pack(fill='x')
        ttk.Label(self.skipped_frame, text="Vynechané symboly (žiadna validná PMCC kombinácia):", font=('Arial', 8, 'bold')).pack(side='left')
        self.skipped_var = tk.StringVar(value="—")
        self.skipped_lbl = ttk.Label(self.skipped_frame, textvariable=self.skipped_var, font=('Arial', 8), foreground="gray", wraplength=800)
        self.skipped_lbl.pack(side='left', padx=5)

        self.tree.tag_configure('ideal', background='#c8e6c9') 
        self.tree.tag_configure('warning', background='#fff9c4') 
        self.tree.tag_configure('danger', background='#ffcdd2')
        self.tree.tag_configure('child', background='#f5f5f5')

    def save_cache(self):
        try:
            cache_dir = os.path.dirname(self.cache_file)
            if not os.path.exists(cache_dir): os.makedirs(cache_dir)
            
            cache_data = {}
            for sym, data in self.last_pmcc_data.items():
                cache_data[sym] = {
                    'data': data,
                    'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                    'all_options': self.all_pmcc_options.get(sym, [])
                }
            
            with open(self.cache_file, 'w', encoding='utf-8') as f:
                json.dump(cache_data, f, indent=4)
        except Exception as e:
            print(f"❌ Chyba pri ukladaní PMCC cache: {e}")

    def load_cache(self):
        if not os.path.exists(self.cache_file): return
        try:
            with open(self.cache_file, 'r', encoding='utf-8') as f:
                cache_data = json.load(f)
                for sym, entry in cache_data.items():
                    data = entry['data']
                    self.last_pmcc_data[sym] = data
                    self.all_pmcc_options[sym] = entry.get('all_options', [])
                    ts = entry.get('timestamp', 'Neznámy čas')
                    # Neupravujeme priamo status v dátach, len v zobrazení
                    display_data = data.copy()
                    display_data['status'] = f"{data['status']} (zo dňa {ts})"
                    self.add_to_tree(display_data)
        except Exception as e:
            print(f"❌ Chyba pri načítaní PMCC cache: {e}")

    def on_symbols_text_changed(self, event=None):
        if not self.sym_text.edit_modified():
            return
            
        raw = self.sym_text.get('1.0', tk.END)
        syms = [s.strip().upper() for s in raw.replace(',', ' ').replace('\n', ' ').split() if s.strip()]
        self.state.pmcc_symbols = syms
        self.sym_text.edit_modified(False)
        
        if not hasattr(self, '_save_timer') or self._save_timer is None:
            self._save_timer = self.parent.after(2000, self._delayed_save)

    def _delayed_save(self):
        self.state.save_settings_file()
        self._save_timer = None

    def run_pmcc_scan(self, forced_symbols=None, full_scan_single=None):
        if full_scan_single:
            symbols = [full_scan_single]
        elif forced_symbols:
            symbols = forced_symbols
        else:
            raw = self.sym_text.get('1.0', tk.END)
            symbols = [s.strip().upper() for s in raw.replace(',', ' ').replace('\n', ' ').split() if s.strip()]
            
        if not symbols:
            messagebox.showwarning("PMCC Hunter", "Zadajte aspoň jeden symbol do poľa 'Zoznam symbolov'.")
            return
            
        self.scan_session_id += 1
        session_id = self.scan_session_id
        
        self.status_var.set(f"🔍 SKENUJEM {'(FULL)' if full_scan_single else ''}...")
        self.status_lbl.config(foreground="blue")
        
        if not full_scan_single:
            self.tree.delete(*self.tree.get_children())
            self.skipped_var.set("—")
            self.skipped_list = []
        
        try:
            from modularny.tab_swing_hunter import refresh_hunter
            self.parent.after(0, lambda: refresh_hunter(
                self.state, 
                getattr(self.state, 'hunter_tree'), 
                getattr(self.state, 'hunter_rsi_p'), 
                getattr(self.state, 'hunter_rvi_p'), 
                getattr(self.state, 'hunter_tf_v')
            ))
        except Exception as e:
            print(f"Nepodarilo sa spustiť prioritný Swing Hunter sken: {e}")

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
                        self.skipped_list.append(sym)
                else:
                    self.skipped_list.append(sym)
                
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
        
        hunter_data = getattr(self.state, 'hunter_symbol_summaries', {}).get(symbol, {})
        is_buying_zone = hunter_data.get('zone') == 'hunt'
        rsi = hunter_data.get('rsi', 0)
        
        status = "✅ VALIDNÉ"
        if is_buying_zone: status = "🔥 BUY ZONE"
        if rsi > 65: status = "⚠️ OVERBOUGHT"
        if rsi > 75: status = "🚫 VYSOKÉ RIZIKO"

        valid_pmccs = []
        skip_reason = "Bez validnej kombinácie"
        
        if not leaps: skip_reason = "Nenašli sa LEAPS"
        elif not shorts: skip_reason = "Nenašli sa Short opcie"

        for l in leaps:
            if l['delta'] < min_delta_l: continue
            if l['bid'] > 0 and l['ask'] > 0 and l['spread_pct'] > max_spread: continue
            
            intrinsic = max(0, price - l['strike'])
            extrinsic = l['price'] - intrinsic
            ext_pct = (extrinsic / l['price']) * 100 if l['price'] > 0 else 100
            
            for s in shorts:
                if s['delta'] > max_delta_s: continue
                
                net_debit = l['price'] - s['price']
                if net_debit <= 0: continue
                
                strike_diff = s['strike'] - l['strike']
                if strike_diff <= net_debit:
                    if not valid_pmccs: skip_reason = "Vysoký debit > Strike Diff"
                    continue
                
                max_profit = (strike_diff - net_debit) * 100
                be_price = l['strike'] + net_debit
                be_pct = ((be_price - price) / price) * 100
                
                score = (100 - ext_pct) + (s['theta'] * -10)
                ann_yield = (s['price'] / net_debit) * (365 / s['dte']) * 100 if net_debit > 0 and s['dte'] > 0 else 0
                cushion = (s['price'] / net_debit) * 100 if net_debit > 0 else 0
                lev_quality = net_debit / price if price > 0 else 0
                recovery = extrinsic / s['price'] if s['price'] > 0 else 0
                
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
                    'c_pct': f"{cushion:.1f}%",
                    'lev': f"{lev_quality:.2f}",
                    'mont': f"{recovery:.1f}{' ⚠️' if recovery > 6 else ''}",
                    'max_profit': f"${max_profit:.0f}",
                    'be_pct': f"{be_pct:+.1f}%",
                    'extrinsic': f"{ext_pct:.1f}%",
                    'iv': f"{iv*100:.1f}%" if iv > 0 else "—",
                    'rsi': f"{rsi:.0f}" if rsi > 0 else "—",
                    'yield': f"{ann_yield:.1f}%",
                    'status': status,
                    'score': score,
                    'is_danger': cushion < 3.0 or rsi > 70,
                    'oi': int(s.get('open_interest', 0) or 0),
                    'liq': bool(l.get('liquidity_flag', False) and s.get('liquidity_flag', False))
                })
        
        if valid_pmccs:
            valid_pmccs.sort(key=lambda x: x['score'], reverse=True)
            self.all_pmcc_options[symbol] = valid_pmccs
            best = valid_pmccs[0]
            self.last_pmcc_data[symbol] = best
            self.parent.after(0, lambda: self.add_to_tree(best))
            self.save_cache()
        else:
            self.skipped_list.append(f"{symbol} ({skip_reason})")
            self.parent.after(0, lambda: self.skipped_var.set(", ".join(self.skipped_list)))

    def add_to_tree(self, p):
        tag = None
        try:
            ext = float(p['extrinsic'].replace('%',''))
            be = float(p['be_pct'].replace('%','').replace('+',''))
            if p.get('is_danger'): tag = 'danger'
            elif ext < 5.0 and be < 2.0: tag = 'ideal'
            elif "BUY ZONE" in p['status']: tag = 'ideal'
            elif ext > 10.0: tag = 'warning'
        except: pass
        
        for item in self.tree.get_children(''):
            if self.tree.item(item, 'text') == p['symbol']:
                self.tree.delete(item)
                break

        parent_id = self.tree.insert('', tk.END, text=p['symbol'], values=(
            p['price'], p['rsi'], p['debit'], p['c_pct'], p['lev'], p['mont'], 
            p['max_profit'], p['be_pct'], p['extrinsic'], p['iv'], p['yield'], p.get('oi','—'), ('✅' if p.get('liq') else '⚠️'), p['status']
        ), tags=(tag,) if tag else ())
        
        l = p.get('leaps_data', {})
        l_bid = f"{l.get('bid', 0):.2f}" if l.get('bid', 0) else "—"
        l_ask = f"{l.get('ask', 0):.2f}" if l.get('ask', 0) else "—"
        l_spread = f"{l.get('spread_pct', 0)*100:.1f}%" if l.get('spread_pct', 0) < 1.0 else "—"
        self.tree.insert(parent_id, tk.END, text="  Leg 1", values=(
            p['leaps_price'], "", "", "", "", "", "", "", f"{l_bid}/{l_ask}", f"{l_spread}", "", 
            str(int(l.get('open_interest', 0) or 0)), ('✅' if l.get('liquidity_flag') else '⚠️'), p['leaps_txt']
        ), tags=('child',))
        
        l_iv = f"{l.get('iv', 0)*100:.1f}%" if l.get('iv', 0) else "—"
        self.tree.insert(parent_id, tk.END, text="    Greeks", values=(
            "", "", "", "", "", "", "", "", "", l_iv, f"Δ {l.get('delta', 0):.2f}", 
            "", "", f"Theta: {l.get('theta', 0):.3f}"
        ), tags=('child',))

        s = p.get('short_data', {})
        s_bid = f"{s.get('bid', 0):.2f}" if s.get('bid', 0) else "—"
        s_ask = f"{s.get('ask', 0):.2f}" if s.get('ask', 0) else "—"
        s_spread = f"{s.get('spread_pct', 0)*100:.1f}%" if s.get('spread_pct', 0) < 1.0 else "—"
        self.tree.insert(parent_id, tk.END, text="  Leg 2", values=(
            p['short_price'], "", "", "", "", "", "", "", f"{s_bid}/{s_ask}", f"{s_spread}", "", 
            str(int(s.get('open_interest', 0) or 0)), ('✅' if s.get('liquidity_flag') else '⚠️'), p['short_txt']
        ), tags=('child',))

        s_iv = f"{s.get('iv', 0)*100:.1f}%" if s.get('iv', 0) else "—"
        self.tree.insert(parent_id, tk.END, text="    Greeks", values=(
            "", "", "", "", "", "", "", "", "", s_iv, f"Δ {s.get('delta', 0):.2f}", 
            "", "", f"Theta: {s.get('theta', 0):.3f}"
        ), tags=('child',))
        
        self.tree.item(parent_id, open=False)

    def treeview_sort_column(self, col, reverse):
        l = []
        for k in self.tree.get_children(''):
            val = self.tree.set(k, col) if col != '#0' else self.tree.item(k, 'text')
            clean_val = val
            if isinstance(val, str):
                clean_val = val.replace('%', '').replace('$', '').replace('+', '').replace('—', '-1').strip()
                try:
                    clean_val = float(clean_val)
                except ValueError:
                    clean_val = val.lower()
            l.append((clean_val, k))
        l.sort(reverse=reverse, key=lambda x: x[0])
        for index, (val, k) in enumerate(l):
            self.tree.move(k, '', index)
        self.tree.heading(col, command=lambda: self.treeview_sort_column(col, not reverse))

    def handle_header_tooltips(self, event):
        region = self.tree.identify_region(event.x, event.y)
        if region == "heading":
            column = self.tree.identify_column(event.x)
            try:
                col_id = self.tree["columns"][int(column[1:]) - 1] if column != '#0' else None
                if col_id and col_id in self.header_tooltips:
                    text = self.header_tooltips[col_id]
                    if not hasattr(self, '_current_tip_text') or self._current_tip_text != text:
                        self._current_tip_text = text
                        self.show_header_tip(event.x_root, event.y_root, text)
                else:
                    self.hide_header_tip()
            except: 
                self.hide_header_tip()
        else:
            self.hide_header_tip()

    def show_header_tip(self, x, y, text):
        self.hide_header_tip()
        self._tip_win = tk.Toplevel()
        self._tip_win.wm_overrideredirect(True)
        self._tip_win.wm_geometry(f"+{x+15}+{y+15}")
        tk.Label(self._tip_win, text=text, background="#ffffca", relief="solid", borderwidth=1, font=("Arial", 9)).pack()

    def hide_header_tip(self):
        if hasattr(self, '_tip_win') and self._tip_win:
            self._tip_win.destroy()
            self._tip_win = None
            self._current_tip_text = None

    def show_context_menu(self, event):
        item = self.tree.identify_row(event.y)
        if item:
            self.tree.selection_set(item)
            menu = tk.Menu(self.parent, tearoff=0)
            menu.add_command(label="🔄 VELKÝ SKEN (Len tento symbol)", command=self.run_single_full_scan)
            menu.add_separator()
            menu.add_command(label="🎯 ZMENIŤ STRIKE (Simulátor)", command=self.open_strike_simulator)
            menu.add_separator()
            menu.add_command(label="🚀 OTVORIŤ V TRADE PLAN", command=self.open_in_trade_plan)
            menu.post(event.x_root, event.y_root)

    def run_single_full_scan(self):
        selected = self.tree.selection()
        if not selected: return
        parent_id = selected[0]
        if self.tree.parent(parent_id): parent_id = self.tree.parent(parent_id)
        symbol = self.tree.item(parent_id, 'text')
        self.run_pmcc_scan(full_scan_single=symbol)

    def open_strike_simulator(self):
        selected = self.tree.selection()
        if not selected: return
        
        parent_id = selected[0]
        if self.tree.parent(parent_id): parent_id = self.tree.parent(parent_id)
        symbol = self.tree.item(parent_id, 'text')
        
        options = self.all_pmcc_options.get(symbol, [])
        if not options:
            messagebox.showinfo("Simulátor", f"Pre {symbol} nie sú k dispozícii iné kombinácie.")
            return

        win = tk.Toplevel(self.parent)
        win.title(f"🎯 Simulátor Striku - {symbol}")
        win.geometry("800x400")
        win.transient(self.parent)
        win.grab_set()

        ttk.Label(win, text=f"Vyberte inú kombináciu pre {symbol}:", font=('Arial', 10, 'bold')).pack(pady=10)

        cols = ('short_exp', 'short_strike', 'premium', 'long_exp', 'long_strike', 'c_pct', 'mont', 'debit', 'profit')
        stree = ttk.Treeview(win, columns=cols, show='headings', height=12)
        
        stree.heading('short_exp', text='Short Exp')
        stree.heading('short_strike', text='Short Strike')
        stree.heading('premium', text='Premium')
        stree.heading('long_exp', text='Long Exp')
        stree.heading('long_strike', text='Long Strike')
        stree.heading('c_pct', text='C %')
        stree.heading('mont', text='Mont')
        stree.heading('debit', text='Net Debit')
        stree.heading('profit', text='Max Profit')
        
        widths = {'short_exp': 100, 'short_strike': 80, 'premium': 70, 'long_exp': 100, 'long_strike': 80, 'c_pct': 50, 'mont': 50, 'debit': 70, 'profit': 80}
        for c, w in widths.items(): 
            stree.column(c, width=w, anchor='center')
        
        stree.pack(fill='both', expand=True, padx=10)

        for i, o in enumerate(options):
            tag = 'danger' if o.get('is_danger') else ''
            s_exp = f"{o['short_data']['expiry']} ({o['short_data']['dte']}d)"
            l_exp = f"{o['leaps_data']['expiry']} ({o['leaps_data']['dte']}d)"
            
            stree.insert('', tk.END, iid=str(i), values=(
                s_exp, o['short_data']['strike'], o['short_price'], l_exp, o['leaps_data']['strike'],
                o['c_pct'], o['mont'], o['debit'], o['max_profit']
            ), tags=(tag,))
        
        stree.tag_configure('danger', foreground='red')

        def select():
            sel = stree.selection()
            if not sel: return
            idx = int(sel[0])
            chosen = options[idx]
            self.last_pmcc_data[symbol] = chosen
            self.add_to_tree(chosen)
            win.destroy()

        ttk.Button(win, text="✅ POUŽIŤ TÚTO KOMBINÁCIU", command=select).pack(pady=10)

    def stop_scan(self):
        self.scan_session_id += 1
        try:
            subprocess.run(['pkill', '-f', 'tws_fetch_pmcc_options.py'], capture_output=True)
        except: pass
        self.status_var.set("⏹️ ZASTAVENÉ")
        self.status_lbl.config(foreground="red")

    def open_in_trade_plan(self):
        selected = self.tree.selection()
        if not selected:
            messagebox.showwarning("PMCC Hunter", "Vyberte symbol v tabuľke.")
            return
            
        parent_id = selected[0]
        if self.tree.parent(parent_id):
            parent_id = self.tree.parent(parent_id)
            
        symbol = self.tree.item(parent_id, 'text')
        pmcc_data = self.last_pmcc_data.get(symbol)
        
        try:
            from modularny.tab_swing_hunter import open_trade_plan_window
            summary = {
                'symbol': symbol,
                'price': float(self.tree.item(parent_id, 'values')[0]),
                'option_strategy': 'PMCC', 
                'strategy_label': 'PMCC (Poor Man\'s Covered Call)',
                'pmcc': pmcc_data
            }
            open_trade_plan_window(self.state, summary)
        except Exception as e:
            messagebox.showerror("Chyba", f"Nepodarilo sa otvoriť Trade Plan: {e}")

    def sync_from_hunter(self):
        summaries = getattr(self.state, 'hunter_symbol_summaries', {})
        bullish_syms = []
        for sym, data in summaries.items():
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

def create_pmcc_hunter_tab(parent, state):
    return PMCCHunterTab(parent, state)
