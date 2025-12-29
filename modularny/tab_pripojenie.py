#!/usr/bin/env python3
"""
Záložka: Pripojenie
Kontrola pripojenia k TWS a načítanie expirácií
"""
import tkinter as tk
from tkinter import ttk


def create_connection_tab(parent, state):
    """Záložka pre kontrolu pripojenia"""
    frame = ttk.LabelFrame(parent, text="Stav pripojenia k TWS", padding=15)
    frame.pack(fill='x', padx=10, pady=10)
    
    # Info o pripojení
    conn_info_text = tk.Text(frame, height=10, font=('Courier', 11), state='disabled')
    conn_info_text.pack(fill='x', pady=10)
    
    # Ulož referenciu do state pre aktualizáciu
    state.conn_info_text = conn_info_text
    
    # Tlačidlá
    btn_frame = ttk.Frame(frame)
    btn_frame.pack(fill='x', pady=10)
    
    ttk.Button(btn_frame, text="🔄 Otestovať pripojenie", command=state.check_connection).pack(side='left', padx=5)
    ttk.Button(btn_frame, text="📋 Načítať expirácie", command=state.load_expiries).pack(side='left', padx=5)
    
    # Návod
    help_frame = ttk.LabelFrame(parent, text="Návod", padding=10)
    help_frame.pack(fill='both', expand=True, padx=10, pady=10)
    
    help_text = """
PRED POUŽITÍM:
1. Spustite Trader Workstation (TWS) alebo IB Gateway
2. Povoľte API pripojenie v TWS:
   Edit → Global Configuration → API → Settings
   ✓ Enable ActiveX and Socket Clients
   ✓ Socket port: 7496 (Live) alebo 7497 (Paper)
   ✓ Read-Only API: Áno (bezpečnejšie)

3. Uistite sa, že máte OPRA Market Data subscription
   (potrebné pre options greeks - delta, theta)

PORTY:
• 7496 - TWS Live Trading
• 7497 - TWS Paper Trading

TIP: Pre testovanie používajte Paper Trading (port 7497)
"""
    help_label = ttk.Label(help_frame, text=help_text, font=('Arial', 10), justify='left')
    help_label.pack(fill='both', expand=True)
    
    # Aktualizuj update_connection_status aby aktualizoval aj tento text widget
    original_update = state.update_connection_status
    
    def update_with_text(info):
        original_update(info)
        if state.connected:
            conn_info_text.config(state='normal')
            conn_info_text.delete(1.0, tk.END)
            text = f"""
✅ PRIPOJENIE ÚSPEŠNÉ
═══════════════════════════════════════════════
   Host:           127.0.0.1
   Port:           {info.get('port', '?')}
   Server Version: {info.get('serverVersion', '?')}
   Účty:           {', '.join(info.get('accounts', []))}
═══════════════════════════════════════════════
Pripravené na použitie!
"""
            conn_info_text.insert(tk.END, text)
            conn_info_text.config(state='disabled')
        else:
            conn_info_text.config(state='normal')
            conn_info_text.delete(1.0, tk.END)
            text = f"""
❌ PRIPOJENIE ZLYHALO
═══════════════════════════════════════════════
   Port:  {state.port_var.get()}
   Chyba: {info.get('error', 'Neznáma chyba')}
═══════════════════════════════════════════════
Skontrolujte:
1. Je TWS spustený?
2. Je API povolené?
3. Je správny port?
"""
            conn_info_text.insert(tk.END, text)
            conn_info_text.config(state='disabled')
    
    # Nahraď metódu
    state.update_connection_status = update_with_text

