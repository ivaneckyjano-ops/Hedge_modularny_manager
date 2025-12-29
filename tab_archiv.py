#!/usr/bin/env python3
"""
Záložka: Archív
Ukladanie a načítavanie stratégií
"""
import tkinter as tk
from tkinter import ttk, messagebox


def archive_refresh_list(state):
    """Obnoví zoznam stratégií v archíve"""
    if not hasattr(state, 'archive_listbox'):
        return
    
    state.archive_listbox.delete(0, tk.END)
    
    for name in sorted(state.saved_strategies.keys()):
        strategy = state.saved_strategies[name]
        symbol = strategy.get('symbol', '?')
        opt_type = strategy.get('option_type', '?')
        short_strike = strategy.get('short_strike', '?')
        state.archive_listbox.insert(tk.END, f"{name} | {symbol} {opt_type} {short_strike}")


def archive_show_details(state):
    """Zobrazí detaily vybranej stratégie"""
    if not hasattr(state, 'archive_listbox') or not hasattr(state, 'archive_details_text'):
        return
    
    selection = state.archive_listbox.curselection()
    if not selection:
        return
    
    item = state.archive_listbox.get(selection[0])
    name = item.split(' | ')[0]
    
    if name not in state.saved_strategies:
        return
    
    strategy = state.saved_strategies[name]
    
    details = f"""STRATÉGIA: {name}
{'='*40}

Symbol:           {strategy.get('symbol', '-')}
Typ:              {strategy.get('option_type', '-')}
Podklad:          ${strategy.get('underlying_price', '-')}

SHORT LEG:
  Strike:         {strategy.get('short_strike', '-')}
  Expirácia:      {strategy.get('short_expiry', '-')}
  Premium:        ${strategy.get('short_premium', '-')}

LONG LEG:
  Strike:         {strategy.get('long_strike', '-')}
  Expirácia:      {strategy.get('long_expiry', '-')}
  Premium:        ${strategy.get('long_premium', '-')}

Broker:           {strategy.get('broker', '-')}
Uložená:          {strategy.get('saved_at', '-')}
"""
    
    state.archive_details_text.config(state='normal')
    state.archive_details_text.delete(1.0, tk.END)
    state.archive_details_text.insert(tk.END, details)
    state.archive_details_text.config(state='disabled')


def archive_load_selected(state):
    """Načíta vybranú stratégiu do kalkulátora"""
    if not hasattr(state, 'archive_listbox'):
        return
    
    selection = state.archive_listbox.curselection()
    if not selection:
        messagebox.showwarning("Chyba", "Vyberte stratégiu zo zoznamu")
        return
    
    item = state.archive_listbox.get(selection[0])
    name = item.split(' | ')[0]
    
    # Použijeme load_strategy z state
    # Musíme vytvoriť dočasný StringVar pre názov
    temp_var = tk.StringVar(value=name)
    state.load_strategy(temp_var)
    messagebox.showinfo("Načítané", f"Stratégia '{name}' bola načítaná do kalkulátora.")


def archive_delete_selected(state):
    """Vymaže vybranú stratégiu"""
    if not hasattr(state, 'archive_listbox'):
        return
    
    selection = state.archive_listbox.curselection()
    if not selection:
        messagebox.showwarning("Chyba", "Vyberte stratégiu na vymazanie")
        return
    
    item = state.archive_listbox.get(selection[0])
    name = item.split(' | ')[0]
    
    confirm = messagebox.askyesno("Potvrdenie", f"Naozaj chcete vymazať stratégiu '{name}'?")
    if confirm:
        if name in state.saved_strategies:
            del state.saved_strategies[name]
            state.save_settings_file()
            archive_refresh_list(state)
            
            # Vyčisti detaily
            if hasattr(state, 'archive_details_text'):
                state.archive_details_text.config(state='normal')
                state.archive_details_text.delete(1.0, tk.END)
                state.archive_details_text.config(state='disabled')
            
            messagebox.showinfo("Vymazané", f"Stratégia '{name}' bola vymazaná.")


def create_archive_tab(parent, state):
    """Záložka pre archív stratégií s prehľadným zoznamom"""
    # Hlavný frame
    main_frame = ttk.Frame(parent, padding=10)
    main_frame.pack(fill='both', expand=True)
    
    # Ľavá strana - zoznam stratégií
    left_frame = ttk.LabelFrame(main_frame, text="📋 Uložené stratégie", padding=5)
    left_frame.pack(side='left', fill='both', expand=True, padx=(0, 5))
    
    # Listbox so scrollbarom
    list_frame = ttk.Frame(left_frame)
    list_frame.pack(fill='both', expand=True)
    
    scrollbar = ttk.Scrollbar(list_frame)
    scrollbar.pack(side='right', fill='y')
    
    archive_listbox = tk.Listbox(list_frame, font=('Courier', 11), 
                                  yscrollcommand=scrollbar.set, selectmode='single')
    archive_listbox.pack(side='left', fill='both', expand=True)
    scrollbar.config(command=archive_listbox.yview)
    
    # Ulož referenciu
    state.archive_listbox = archive_listbox
    
    # Bind double-click pre načítanie
    archive_listbox.bind('<Double-1>', lambda e: archive_load_selected(state))
    archive_listbox.bind('<<ListboxSelect>>', lambda e: archive_show_details(state))
    
    # Tlačidlá pod zoznamom
    btn_frame = ttk.Frame(left_frame)
    btn_frame.pack(fill='x', pady=5)
    
    ttk.Button(btn_frame, text="📂 Načítať", command=lambda: archive_load_selected(state), width=12).pack(side='left', padx=2)
    ttk.Button(btn_frame, text="🗑️ Vymazať", command=lambda: archive_delete_selected(state), width=12).pack(side='left', padx=2)
    ttk.Button(btn_frame, text="🔄 Obnoviť", command=lambda: archive_refresh_list(state), width=12).pack(side='left', padx=2)
    
    # Pravá strana - detaily stratégie
    right_frame = ttk.LabelFrame(main_frame, text="📝 Detaily stratégie", padding=5)
    right_frame.pack(side='right', fill='both', expand=True, padx=(5, 0))
    
    archive_details_text = tk.Text(right_frame, font=('Courier', 11), wrap='word', state='disabled')
    archive_details_text.pack(fill='both', expand=True)
    
    # Ulož referenciu
    state.archive_details_text = archive_details_text
    
    # Načítaj zoznam pri vytvorení
    state.root.after(100, lambda: archive_refresh_list(state))

