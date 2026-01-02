#!/usr/bin/env python3
"""
Záložka: Správca Driftu (Ticker Settings)
Správa optimálnych tolerancií a nastavení pre jednotlivé tickery.
"""
import tkinter as tk
from tkinter import ttk, messagebox
from datetime import datetime

def create_drift_manager_tab(parent, state):
    frame = ttk.Frame(parent, padding=15)
    frame.pack(fill='both', expand=True)

    # === 1. FORMULÁR PRE NASTAVENIA TICKERA ===
    edit_frame = ttk.LabelFrame(frame, text="⚙️ Nastavenia pre Ticker", padding=10)
    edit_frame.pack(fill='x', pady=(0, 10))

    row1 = ttk.Frame(edit_frame)
    row1.pack(fill='x', pady=5)

    ttk.Label(row1, text="Symbol:").pack(side='left', padx=5)
    symbol_entry = ttk.Entry(row1, width=10)
    symbol_entry.pack(side='left', padx=5)
    # Defaultne nastavíme aktuálny symbol zo state
    symbol_entry.insert(0, state.symbol_var.get())

    ttk.Label(row1, text="Opt. Drift Tol:").pack(side='left', padx=10)
    drift_tol_entry = ttk.Entry(row1, width=8)
    drift_tol_entry.pack(side='left', padx=5)
    drift_tol_entry.insert(0, "0.15")

    ttk.Label(row1, text="Poznámka:").pack(side='left', padx=10)
    note_entry = ttk.Entry(row1, width=40)
    note_entry.pack(side='left', padx=5)

    def save_ticker_settings():
        sym = symbol_entry.get().strip().upper()
        if not sym:
            messagebox.showwarning("Chyba", "Zadajte symbol.")
            return
        
        try:
            tol = float(drift_tol_entry.get())
            state.ticker_settings[sym] = {
                'drift_tolerance': tol,
                'note': note_entry.get().strip(),
                'updated_at': datetime.now().strftime('%Y-%m-%d %H:%M')
            }
            state.save_settings_file()
            refresh_tree()
            messagebox.showinfo("Uložené", f"Nastavenia pre {sym} boli uložené.")
        except ValueError:
            messagebox.showerror("Chyba", "Tolerancia musí byť číslo.")

    ttk.Button(row1, text="💾 Uložiť", command=save_ticker_settings).pack(side='left', padx=20)

    # === 2. ZOZNAM TICKEROV ===
    tree_frame = ttk.LabelFrame(frame, text="📋 Archív osvedčených nastavení", padding=10)
    tree_frame.pack(fill='both', expand=True)

    columns = ('symbol', 'tol', 'note', 'updated')
    tree = ttk.Treeview(tree_frame, columns=columns, show='headings')
    tree.heading('symbol', text='Ticker')
    tree.heading('tol', text='Opt. Drift')
    tree.heading('note', text='Poznámka')
    tree.heading('updated', text='Aktualizované')

    tree.column('symbol', width=80, anchor='center')
    tree.column('tol', width=100, anchor='center')
    tree.column('note', width=300)
    tree.column('updated', width=150, anchor='center')

    scrollbar = ttk.Scrollbar(tree_frame, orient="vertical", command=tree.yview)
    tree.configure(yscrollcommand=scrollbar.set)
    tree.pack(side='left', fill='both', expand=True)
    scrollbar.pack(side='right', fill='y')

    def refresh_tree():
        for item in tree.get_children():
            tree.delete(item)
        for sym, d in sorted(state.ticker_settings.items()):
            tree.insert('', tk.END, values=(
                sym, 
                f"{d.get('drift_tolerance', 0.15):.2f}",
                d.get('note', ''),
                d.get('updated_at', '')
            ))

    def on_select(event):
        selected = tree.selection()
        if selected:
            vals = tree.item(selected[0])['values']
            symbol_entry.delete(0, tk.END)
            symbol_entry.insert(0, vals[0])
            drift_tol_entry.delete(0, tk.END)
            drift_tol_entry.insert(0, vals[1])
            note_entry.delete(0, tk.END)
            note_entry.insert(0, vals[2])

    tree.bind('<<TreeviewSelect>>', on_select)

    def delete_selected():
        selected = tree.selection()
        if not selected: return
        sym = tree.item(selected[0])['values'][0]
        if messagebox.askyesno("Vymazať", f"Naozaj vymazať nastavenia pre {sym}?"):
            if sym in state.ticker_settings:
                del state.ticker_settings[sym]
                state.save_settings_file()
                refresh_tree()

    ttk.Button(frame, text="🗑️ Vymazať vybrané", command=delete_selected).pack(pady=5)

    refresh_tree()
    # Exponujeme funkciu na refresh pre prípadné volanie odinakiaľ
    state.refresh_drift_manager_tree = refresh_tree

