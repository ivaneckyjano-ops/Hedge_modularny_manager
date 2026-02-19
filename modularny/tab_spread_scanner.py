#!/usr/bin/env python3
"""
Spread Scanner tab - UI for generating and viewing top‑N symbols with smallest option spreads.
Uses scripts/generate_top_spread_list.py to compute the list and stores results in cache/top_spread_symbols.json.
"""
import tkinter as tk
from tkinter import ttk, messagebox
import threading
import subprocess
import json
import os
import sys
import time

class SpreadScannerTab:
    def __init__(self, parent, state):
        self.parent = parent
        self.state = state
        self.frame = ttk.Frame(parent)
        self.frame.pack(fill='both', expand=True)
        self.cache_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'cache')
        os.makedirs(self.cache_dir, exist_ok=True)
        self.setup_ui()
        self.load_cached_top_list()

    def setup_ui(self):
        top_panel = ttk.Frame(self.frame)
        top_panel.pack(fill='x', padx=10, pady=6)

        left = ttk.LabelFrame(top_panel, text="Zdroj symbolov", padding=8)
        left.pack(side='left', fill='y', padx=(0,8))

        self.src_var = tk.StringVar(value='block')
        ttk.Radiobutton(left, text="Symbol block", variable=self.src_var, value='block').pack(anchor='w')
        ttk.Radiobutton(left, text="Manuálne", variable=self.src_var, value='manual').pack(anchor='w')
        ttk.Radiobutton(left, text="PMCC list", variable=self.src_var, value='pmcc').pack(anchor='w')
        ttk.Radiobutton(left, text="Hunter custom", variable=self.src_var, value='hunter').pack(anchor='w')

        ttk.Button(left, text="📁 Spravovať bloky", command=self.open_block_manager).pack(fill='x', pady=(6,0))
        # Combobox to choose which spread block to use
        ttk.Label(left, text="Vybrať blok:", font=('Arial', 8)).pack(anchor='w', pady=(6,0))
        # initialize selected block var if missing
        if not hasattr(self.state, 'spread_selected_block'):
            try:
                self.state.spread_selected_block = tk.StringVar(value="-- Vybrať blok --")
            except Exception:
                self.state.spread_selected_block = None
        init_val = self.state.spread_selected_block.get() if getattr(self.state, 'spread_selected_block', None) else "-- Vybrať blok --"
        block_names = sorted(list(getattr(self.state, 'spread_symbol_blocks', {}).keys()))
        self.block_combo_var = tk.StringVar(value=init_val)
        self.block_combo = ttk.Combobox(left, textvariable=self.block_combo_var, values=block_names, state='readonly', width=20)
        self.block_combo.pack(fill='x', pady=(2,0))
        self.block_combo.bind("<<ComboboxSelected>>", self._on_block_selected)

        center = ttk.LabelFrame(top_panel, text="Nastavenia", padding=8)
        center.pack(side='left', fill='x', expand=True)
        ttk.Label(center, text="Candidate limit:").grid(row=0, column=0, sticky='w')
        self.candidate_limit = tk.StringVar(value="1000")
        ttk.Entry(center, textvariable=self.candidate_limit, width=8).grid(row=0, column=1, padx=6)
        ttk.Label(center, text="Batch size:").grid(row=0, column=2, sticky='w')
        self.batch_size = tk.StringVar(value="25")
        ttk.Entry(center, textvariable=self.batch_size, width=6).grid(row=0, column=3, padx=6)
        ttk.Label(center, text="Top N:").grid(row=1, column=0, sticky='w', pady=(6,0))
        self.top_n = tk.StringVar(value="100")
        ttk.Entry(center, textvariable=self.top_n, width=8).grid(row=1, column=1, padx=6, pady=(6,0))
        ttk.Label(center, text="Expiries:").grid(row=1, column=2, sticky='w', pady=(6,0))
        self.expiries = tk.StringVar(value="2")
        ttk.Entry(center, textvariable=self.expiries, width=6).grid(row=1, column=3, padx=6, pady=(6,0))

        right = ttk.LabelFrame(top_panel, text="Manuálny vstup / Spread list", padding=8)
        right.pack(side='right', fill='y')
        self.sym_text = tk.Text(right, width=32, height=4, font=('Arial', 9))
        self.sym_text.pack()
        initial = ", ".join(getattr(self.state, 'top_spread_symbols', []))
        self.sym_text.insert('1.0', initial)
        
        btn_grid = ttk.Frame(right)
        btn_grid.pack(fill='x', pady=(4,0))
        ttk.Button(btn_grid, text="🗑 Vymazať plochu", command=self.clear_manual_input).pack(side='left', fill='x', expand=True, padx=(0,2))
        ttk.Button(btn_grid, text="👁 Načítať Spread list", command=self.view_spread_list).pack(side='left', fill='x', expand=True, padx=(2,0))

        btn_panel = ttk.Frame(self.frame)
        btn_panel.pack(fill='x', padx=10, pady=6)
        self.status_var = tk.StringVar(value="Pripravený")
        self.status_lbl = ttk.Label(btn_panel, textvariable=self.status_var, foreground="gray")
        self.status_lbl.pack(side='left', padx=5)

        self.gen_btn = ttk.Button(btn_panel, text="🔄 Generovať top‑list", command=self.on_generate)
        self.gen_btn.pack(side='right', padx=4)
        self.stop_btn = ttk.Button(btn_panel, text="⏹ Zastaviť", command=self.on_stop, state='disabled')
        self.stop_btn.pack(side='right', padx=4)
        
        ttk.Button(btn_panel, text="📥 Načítať cache", command=self.load_cached_top_list).pack(side='right', padx=4)
        ttk.Button(btn_panel, text="📤 Export CSV", command=self.export_csv).pack(side='right', padx=4)
        ttk.Button(btn_panel, text="💾 Uložiť do Spread listu", command=self.save_to_spread_list).pack(side='right', padx=4)
        ttk.Button(btn_panel, text="🧨 Vymazať Spread list", command=self.clear_spread_list).pack(side='right', padx=4)

        # New transfer buttons
        transfer_panel = ttk.Frame(self.frame)
        transfer_panel.pack(fill='x', padx=10, pady=(0, 6))
        ttk.Label(transfer_panel, text="Preniesť výsledky:", font=('Arial', 9, 'bold')).pack(side='left', padx=(5, 10))
        ttk.Button(transfer_panel, text="🎯 Pridať do Huntera", command=self.add_to_hunter).pack(side='left', padx=4)
        ttk.Button(transfer_panel, text="💰 Pridať do PMCC", command=self.add_to_pmcc).pack(side='left', padx=4)

        # results table
        cols = ('symbol', 'median_spread','samples','price')
        self.tree = ttk.Treeview(self.frame, columns=cols, show='headings')
        
        self.tree.heading('symbol', text='Symbol')
        self.tree.column('symbol', width=100, anchor='center')
        
        self.tree.heading('median_spread', text='Median Spread (%)')
        self.tree.column('median_spread', width=150, anchor='center')
        
        self.tree.heading('samples', text='Samples')
        self.tree.column('samples', width=100, anchor='center')
        
        self.tree.heading('price', text='Price')
        self.tree.column('price', width=100, anchor='center')
        
        self.tree.pack(fill='both', expand=True, padx=10, pady=6)

    def open_block_manager(self):
        from modularny.shared_state import open_symbol_block_manager
        open_symbol_block_manager(self.state, self.update_block_combo, 'spread_symbol_blocks')

    def _on_block_selected(self, event=None):
        val = self.block_combo_var.get()
        if hasattr(self.state, 'spread_selected_block') and getattr(self.state, 'spread_selected_block') is not None:
            try:
                self.state.spread_selected_block.set(val)
            except Exception:
                self.state.spread_selected_block = tk.StringVar(value=val)
        else:
            try:
                self.state.spread_selected_block = tk.StringVar(value=val)
            except Exception:
                self.state.spread_selected_block = None

    def update_block_combo(self):
        # Refresh combobox values from state.spread_symbol_blocks
        blocks = getattr(self.state, 'spread_symbol_blocks', {}) or {}
        names = sorted(blocks.keys())
        try:
            self.block_combo['values'] = names
            sel = getattr(self.state, 'spread_selected_block', None)
            if sel and hasattr(sel, 'get'):
                cur = sel.get()
                if cur in names:
                    self.block_combo_var.set(cur)
                elif names:
                    # pick first as default
                    self.block_combo_var.set(names[0])
                    try:
                        self.state.spread_selected_block.set(names[0])
                    except Exception:
                        self.state.spread_selected_block = tk.StringVar(value=names[0])
        except Exception:
            pass

    def on_generate(self):
        src = self.src_var.get()
        if src == 'manual':
            txt = self.sym_text.get('1.0', tk.END).strip()
            symbols = [s.strip().upper() for s in txt.replace(',', ' ').split() if s.strip()]
        elif src == 'pmcc':
            symbols = getattr(self.state, 'pmcc_symbols', []) or []
        elif src == 'hunter':
            symbols = getattr(self.state, 'hunter_custom_tickers', []) or []
        else:
            blk = self.state.spread_selected_block.get() if hasattr(self.state, 'spread_selected_block') else None
            symbols = self.state.spread_symbol_blocks.get(blk, []) if blk and blk in getattr(self.state, 'spread_symbol_blocks', {}) else []

        if not symbols:
            messagebox.showwarning("Spread Scanner", "Žiadne symboly pre skenovanie.")
            return

        # write temp file
        tmpf = os.path.join(self.cache_dir, f"candidates_{int(time.time())}.txt")
        with open(tmpf, 'w', encoding='utf-8') as f:
            f.write("\n".join(symbols))

        self.status_var.set("🔎 Generovanie...")
        self.status_lbl.config(foreground="orange")
        self.gen_btn['state'] = 'disabled'
        self.stop_btn['state'] = 'normal'
        threading.Thread(target=self._run_generate, args=(tmpf,), daemon=True).start()

    def on_stop(self):
        if hasattr(self, 'proc') and self.proc:
            try:
                self.proc.terminate()
                self.status_var.set("⏹ Zastavené")
                self.status_lbl.config(foreground="gray")
            except Exception as e:
                print(f"Chyba pri zastavovaní: {e}")

    def _run_generate(self, symbol_file):
        root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        script = os.path.join(root_dir, 'scripts', 'generate_top_spread_list.py')
        port = getattr(self.state, 'current_port', getattr(self.state, 'port_var', '7497'))
        cmd = [sys.executable, script, str(port), '--symbol-file', symbol_file, '--candidate-limit', self.candidate_limit.get(), '--batch-size', self.batch_size.get(), '--expiries', self.expiries.get(), '--top', self.top_n.get()]
        try:
            self.proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, cwd=root_dir)
            stdout, stderr = self.proc.communicate()
            
            self.state.root.after(0, lambda: self.gen_btn.config(state='normal'))
            self.state.root.after(0, lambda: self.stop_btn.config(state='disabled'))

            if self.proc.returncode != 0:
                # If it was terminated by user, don't show error box
                if self.status_var.get() == "⏹ Zastavené":
                    return
                raise RuntimeError(stderr or stdout)
            
            self.state.root.after(0, self.load_cached_top_list)
            self.state.root.after(0, lambda: self.status_var.set("✅ Hotovo"))
            self.state.root.after(0, lambda: self.status_lbl.config(foreground="green"))
        except Exception as e:
            self.state.root.after(0, lambda: self.gen_btn.config(state='normal'))
            self.state.root.after(0, lambda: self.stop_btn.config(state='disabled'))
            if self.status_var.get() != "⏹ Zastavené":
                self.state.root.after(0, lambda: messagebox.showerror("Chyba", f"Generovanie zlyhalo:\n{e}"))
                self.state.root.after(0, lambda: self.status_var.set("❌ Chyba"))
                self.state.root.after(0, lambda: self.status_lbl.config(foreground="red"))

    def load_cached_top_list(self):
        cache_file = os.path.join(self.cache_dir, 'top_spread_symbols.json')
        if not os.path.exists(cache_file):
            messagebox.showinfo("Info", "Žiadny cache súbor (top_spread_symbols.json). Generujte najprv zoznam.")
            return
        try:
            with open(cache_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
            # populate tree
            for i in self.tree.get_children():
                self.tree.delete(i)
            for r in data.get('results', []):
                sym = r.get('symbol', '???')
                spread = r.get('median_spread', 0)
                samples = r.get('samples', 0)
                price = r.get('price', 0)
                
                # Format spread as percentage for humans (0.0654 -> 6.54%)
                spread_fmt = f"{spread*100:.2f} %" if isinstance(spread, (int, float)) else str(spread)
                price_fmt = f"{price:.2f}" if isinstance(price, (int, float)) and price > 0 else "N/A"
                
                self.tree.insert('', tk.END, values=(sym, spread_fmt, samples, price_fmt))
            # store into state
            self.state.top_spread_symbols = [r.get('symbol') for r in data.get('results', [])]
            if hasattr(self.state, 'save_settings_file'):
                self.state.save_settings_file()
            self.status_var.set("✅ Načítané")
            self.status_lbl.config(foreground="green")
        except Exception as e:
            messagebox.showerror("Chyba", f"Chyba pri načítaní cache: {e}")

    def export_csv(self):
        from tkinter import filedialog
        import csv
        p = filedialog.asksaveasfilename(defaultextension=".csv", filetypes=[("CSV files","*.csv")])
        if not p: return
        try:
            with open(p, 'w', newline='', encoding='utf-8') as f:
                w = csv.writer(f)
                w.writerow(['Symbol','MedianSpread','Samples','Price'])
                for iid in self.tree.get_children():
                    vals = self.tree.item(iid, 'values')
                    sym = self.tree.item(iid, 'text')
                    w.writerow([sym, vals[0], vals[1], vals[2]])
            messagebox.showinfo("Export", f"Uložené do {p}")
        except Exception as e:
            messagebox.showerror("Chyba", str(e))

    def save_to_spread_list(self):
        syms = [self.tree.item(iid, 'values')[0] for iid in self.tree.get_children() if self.tree.item(iid, 'values')]
        if not syms:
            messagebox.showwarning("Uložiť", "Zoznam výsledkov je prázdny.")
            return
        self.state.top_spread_symbols = syms
        if hasattr(self.state, 'save_settings_file'):
            self.state.save_settings_file()
        messagebox.showinfo("Uložené", f"Top {len(syms)} uložených do interného Spread listu.")

    def clear_spread_list(self):
        if messagebox.askyesno("Vymazať", "Naozaj chcete vymazať uložený interný Spread list?"):
            self.state.top_spread_symbols = []
            if hasattr(self.state, 'save_settings_file'):
                self.state.save_settings_file()
            messagebox.showinfo("Hotovo", "Spread list bol vymazaný.")

    def view_spread_list(self):
        syms = getattr(self.state, 'top_spread_symbols', []) or []
        self.sym_text.delete('1.0', tk.END)
        self.sym_text.insert('1.0', ", ".join(syms))

    def clear_manual_input(self):
        self.sym_text.delete('1.0', tk.END)

    def add_to_hunter(self):
        syms = [self.tree.item(iid, 'values')[0] for iid in self.tree.get_children() if self.tree.item(iid, 'values')]
        if not syms:
            messagebox.showwarning("Pridať", "Zoznam výsledkov je prázdny. Najprv vygenerujte zoznam.")
            return
        
        current = list(getattr(self.state, 'hunter_custom_tickers', []) or [])
        initial_count = len(current)
        
        added = []
        for s in syms:
            if s not in current:
                current.append(s)
                added.append(s)
        
        if added:
            self.state.hunter_custom_tickers = current
            if hasattr(self.state, 'save_settings_file'):
                self.state.save_settings_file()
            messagebox.showinfo("Hotovo", f"Pridaných {len(added)} symbolov do Swing Huntera:\n{', '.join(added[:15])}{'...' if len(added)>15 else ''}")
        else:
            messagebox.showinfo("Info", "Všetky symboly už v Hunteri sú.")

    def add_to_pmcc(self):
        syms = [self.tree.item(iid, 'values')[0] for iid in self.tree.get_children() if self.tree.item(iid, 'values')]
        if not syms:
            messagebox.showwarning("Pridať", "Zoznam výsledkov je prázdny. Najprv vygenerujte zoznam.")
            return
        
        current = list(getattr(self.state, 'pmcc_symbols', []) or [])
        initial_count = len(current)
        
        added = []
        for s in syms:
            if s not in current:
                current.append(s)
                added.append(s)
        
        if added:
            self.state.pmcc_symbols = current
            if hasattr(self.state, 'save_settings_file'):
                self.state.save_settings_file()
            messagebox.showinfo("Hotovo", f"Pridaných {len(added)} symbolov do PMCC Huntera:\n{', '.join(added[:15])}{'...' if len(added)>15 else ''}")
        else:
            messagebox.showinfo("Info", "Všetky symboly už v PMCC Hunteri sú.")

def create_spread_scanner_tab(parent, state):
    return SpreadScannerTab(parent, state)

