#!/usr/bin/env python3
import tkinter as tk
from tkinter import ttk, messagebox
import threading
import subprocess
import json
import os
import sys
from datetime import datetime

class TradeManagerTab:
    def __init__(self, parent, state):
        self.parent = parent
        self.state = state
        self.frame = ttk.Frame(parent)
        self.frame.pack(fill='both', expand=True)
        
        self.setup_ui()

    def setup_ui(self):
        # Horný panel
        ctrl = ttk.Frame(self.frame, padding=10)
        ctrl.pack(fill='x')
        
        ttk.Button(ctrl, text="🔄 AKTUALIZOVAŤ VŠETKY POZÍCIE Z TWS", 
                   command=self.refresh_positions).pack(side='left', padx=5)
        
        self.status_var = tk.StringVar(value="Pripravený")
        ttk.Label(ctrl, textvariable=self.status_var, font=('Arial', 9, 'italic')).pack(side='right', padx=10)

        # Tabuľka pozícií
        t_frame = ttk.Frame(self.frame)
        t_frame.pack(fill='both', expand=True, padx=10, pady=5)
        
        cols = ('type', 'qty', 'avg_price', 'mkt_price', 'pnl_pct', 'pnl_usd', 'rec_sl', 'rec_tp', 'status')
        self.tree = ttk.Treeview(t_frame, columns=cols, show='tree headings')
        
        self.tree.heading('#0', text='Symbol/Kontrakt')
        self.tree.heading('type', text='Typ')
        self.tree.heading('qty', text='Ks')
        self.tree.heading('avg_price', text='Nákup (Avg)')
        self.tree.heading('mkt_price', text='Aktuálna')
        self.tree.heading('pnl_pct', text='PnL %')
        self.tree.heading('pnl_usd', text='PnL $')
        self.tree.heading('rec_sl', text='Odporúčaný SL')
        self.tree.heading('rec_tp', text='Odporúčaný TP')
        self.tree.heading('status', text='Status / Akcia')

        # Šírky
        self.tree.column('#0', width=150)
        self.tree.column('type', width=50, anchor='center')
        self.tree.column('qty', width=50, anchor='center')
        self.tree.column('avg_price', width=90, anchor='center')
        self.tree.column('mkt_price', width=90, anchor='center')
        self.tree.column('pnl_pct', width=70, anchor='center')
        self.tree.column('pnl_usd', width=80, anchor='center')
        self.tree.column('rec_sl', width=130, anchor='center')
        self.tree.column('rec_tp', width=130, anchor='center')
        self.tree.column('status', width=180)

        self.tree.pack(side='left', fill='both', expand=True)
        sb = ttk.Scrollbar(t_frame, command=self.tree.yview); sb.pack(side='right', fill='y'); self.tree.configure(yscrollcommand=sb.set)

        # Tagy pre farby
        self.tree.tag_configure('profit', foreground='green')
        self.tree.tag_configure('loss', foreground='red')
        self.tree.tag_configure('warning', background='#fff9c4')
        self.tree.tag_configure('target', background='#c8e6c9')

    def refresh_positions(self):
        port = getattr(self.state, 'current_port', "7497")
        self.status_var.set("⏳ Načítavam dáta z TWS...")
        
        def run():
            try:
                root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
                scr = os.path.join(root, 'scripts', 'tws_manual_test.py')
                res = subprocess.run([sys.executable, scr, '--mode', 'positions'], 
                                     env={**os.environ, 'TWS_PORT': str(port)}, 
                                     capture_output=True, text=True, timeout=60)
                
                if res.returncode == 0:
                    data = json.loads(res.stdout)
                    positions = data.get('positions', [])
                    self.parent.after(0, lambda: self.update_table(positions))
                else:
                    self.parent.after(0, lambda: self.status_var.set("❌ Chyba pripojenia"))
            except Exception as e:
                print(f"TradeManager Error: {e}")
                self.parent.after(0, lambda: self.status_var.set(f"❌ Chyba: {e}"))

        threading.Thread(target=run, daemon=True).start()

    def update_table(self, positions):
        self.tree.delete(*self.tree.get_children())
        
        # Zoskupenie podľa symbolov
        by_sym = {}
        for p in positions:
            by_sym.setdefault(p['symbol'], []).append(p)

        for sym in sorted(by_sym.keys()):
            sym_pos = by_sym[sym]
            
            # --- INTELIGENTNÉ PÁROVANIE STRATÉGIÍ ---
            processed_indices = set()
            strategies = []

            # 1. Hľadanie PMCC (Long ITM Call + Short OTM Call)
            long_calls = [(i, p) for i, p in enumerate(sym_pos) if p.get('secType') == 'OPT' and p.get('right') == 'C' and float(p.get('position', 0)) > 0]
            short_calls = [(i, p) for i, p in enumerate(sym_pos) if p.get('secType') == 'OPT' and p.get('right') == 'C' and float(p.get('position', 0)) < 0]

            for li, lp in long_calls:
                if li in processed_indices: continue
                for si, sp in short_calls:
                    if si in processed_indices: continue
                    
                    # Ak je Long strike nižší ako Short strike -> PMCC
                    if float(lp['strike']) < float(sp['strike']):
                        strategies.append({
                            'name': 'PMCC Strategy',
                            'legs': [lp, sp],
                            'type': 'PMCC'
                        })
                        processed_indices.add(li)
                        processed_indices.add(si)
                        break

            # 2. Hľadanie Vertical Spreadov (rovnaká expirácia, rovnaký typ, opačné akcie)
            opts = [(i, p) for i, p in enumerate(sym_pos) if p.get('secType') == 'OPT' and i not in processed_indices]
            for i in range(len(opts)):
                idx1, p1 = opts[i]
                if idx1 in processed_indices: continue
                for j in range(i + 1, len(opts)):
                    idx2, p2 = opts[j]
                    if idx2 in processed_indices: continue
                    
                    if p1['expiry'] == p2['expiry'] and p1['right'] == p2['right'] and (float(p1['position']) * float(p2['position']) < 0):
                        strategies.append({
                            'name': f'Vertical {p1["right"]} Spread',
                            'legs': [p1, p2],
                            'type': 'SPREAD'
                        })
                        processed_indices.add(idx1)
                        processed_indices.add(idx2)
                        break

            # 3. Zvyšné samostatné pozície
            for i, p in enumerate(sym_pos):
                if i not in processed_indices:
                    strategies.append({
                        'name': 'Single Leg' if p.get('secType') == 'OPT' else 'Stock Position',
                        'legs': [p],
                        'type': 'SINGLE'
                    })

            # --- ZOBRAZENIE DO TABUĽKY ---
            parent_id = self.tree.insert('', tk.END, text=sym, open=True)
            
            for strat in strategies:
                legs = strat['legs']
                
                # Výpočty pre celú stratégiu
                total_unr_pnl = sum(float(l.get('unrealizedPNL', 0)) for l in legs)
                
                if strat['type'] == 'PMCC' or strat['type'] == 'SPREAD':
                    l1, l2 = legs[0], legs[1]
                    # Celkový debit/kredit
                    cost1 = float(l1.get('position', 0)) * float(l1.get('avgCost', 0))
                    cost2 = float(l2.get('position', 0)) * float(l2.get('avgCost', 0))
                    net_cost = cost1 + cost2
                    
                    pnl_pct = (total_unr_pnl / abs(net_cost)) * 100 if net_cost != 0 else 0
                    
                    # Odporúčania pre Combo
                    rec_sl = f"{(net_cost/100 * 0.5):.2f} (-50% Deb)"
                    rec_tp = "Strike Short" if strat['type'] == 'PMCC' else "Max Profit"
                    
                    strat_id = self.tree.insert(parent_id, tk.END, text=f"  {strat['name']}", values=(
                        strat['type'], "", f"Net: {net_cost/100:.2f}", "", 
                        f"{pnl_pct:+.1f}%", f"{total_unr_pnl:+.2f}$", rec_sl, rec_tp, "COMBO"
                    ), tags=('target' if pnl_pct > 20 else 'warning' if pnl_pct < -30 else ''))
                    
                    # Pridať detaily nôh pod stratégiu
                    for l in legs:
                        st = l.get('secType', 'OPT')
                        pos = float(l.get('position', 0))
                        avg = float(l.get('avgCost', 0)) / 100.0 if st == 'OPT' else float(l.get('avgCost', 0))
                        mkt = float(l.get('marketPrice', 0))
                        desc = f"{l.get('expiry','')} {l.get('strike','')} {l.get('right','')}"
                        self.tree.insert(strat_id, tk.END, text=f"    {desc if st=='OPT' else 'Shares'}", values=(
                            st, f"{pos:+.0f}", f"{avg:.2f}", f"{mkt:.2f}", "", f"{float(l.get('unrealizedPNL', 0)):+.2f}$", "", "", ""
                        ))
                
                else:
                    # Spracovanie samostatnej nohy (pôvodná logika)
                    p = legs[0]
                    st = p.get('secType', 'STK')
                    pos = float(p.get('position', 0))
                    avg_cost = float(p.get('avgCost', 0))
                    mkt_price = float(p.get('marketPrice', 0))
                    unr_pnl = float(p.get('unrealizedPNL', 0))
                    
                    pnl_pct = 0
                    if st == 'OPT':
                        cost_basis = abs(pos) * avg_cost
                        if cost_basis > 0: pnl_pct = (unr_pnl / cost_basis) * 100
                        display_avg = avg_cost / 100.0
                    else:
                        if avg_cost > 0: pnl_pct = (unr_pnl / (abs(pos) * avg_cost)) * 100
                        display_avg = avg_cost

                    rec_sl, rec_tp, status = "—", "—", "OK"
                    if st == 'STK':
                        if pos > 0:
                            sl_val, tp_val = display_avg * 0.95, display_avg * 1.10
                            rec_sl, rec_tp = f"{sl_val:.2f} (-5%)", f"{tp_val:.2f} (+10%)"
                        else:
                            sl_val, tp_val = display_avg * 1.05, display_avg * 0.90
                            rec_sl, rec_tp = f"{sl_val:.2f} (+5%)", f"{tp_val:.2f} (-10%)"
                    elif st == 'OPT':
                        if pos > 0:
                            rec_sl, rec_tp = f"{display_avg*0.5:.2f} (-50%)", f"{display_avg*2.0:.2f} (+100%)"
                        else:
                            rec_sl, rec_tp = f"{display_avg*3.0:.2f} (3x)", f"{display_avg*0.2:.2f} (80%Pr)"

                    item_id = self.tree.insert(parent_id, tk.END, text=f"  {p.get('expiry','') if st=='OPT' else 'Shares'}", values=(
                        st, f"{pos:+.0f}", f"{display_avg:.2f}", f"{mkt_price:.2f}", 
                        f"{pnl_pct:+.1f}%", f"{unr_pnl:+.2f}$", rec_sl, rec_tp, status
                    ))
                    if unr_pnl > 0: self.tree.item(item_id, tags=('profit',))
                    elif unr_pnl < 0: self.tree.item(item_id, tags=('loss',))

        self.status_var.set(f"✓ Aktualizované: {datetime.now().strftime('%H:%M:%S')}")

def create_trade_manager_tab(parent, state):
    return TradeManagerTab(parent, state)
