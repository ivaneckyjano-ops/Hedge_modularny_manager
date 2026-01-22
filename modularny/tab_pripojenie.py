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
    
    # Výber profilu
    profile_frame = ttk.Frame(frame)
    profile_frame.pack(fill='x', pady=(0, 10))
    
    ttk.Label(profile_frame, text="Režim aplikácie:").pack(side='left', padx=(0, 10))
    
    profiles = list(state.profiles.get("profiles", {}).keys())
    profile_combo = ttk.Combobox(profile_frame, textvariable=state.current_profile_var, values=profiles, state="readonly", width=15)
    profile_combo.pack(side='left')
    
    # Popis profilu
    desc_label = ttk.Label(profile_frame, text="", font=('Arial', 9, 'italic'))
    desc_label.pack(side='left', padx=10)
    
    def update_profile_desc(*args):
        profile = state.get_current_profile()
        desc = profile.get("description", "")
        mode = profile.get("mode", "TEST")
        color = profile.get("color", "black")
        
        desc_label.config(text=f"{desc} (Port: {profile.get('port')})", foreground=color)
        
        # Aktualizuj status bar
        if hasattr(state, 'update_profile_indicator'):
            state.update_profile_indicator()
            
    state.current_profile_var.trace_add('write', update_profile_desc)
    # Inicializuj popis
    update_profile_desc()
    
    # Info o pripojení
    conn_info_text = tk.Text(frame, height=10, font=('Courier', 11), state='disabled')
    conn_info_text.pack(fill='x', pady=10)
    
    # Ulož referenciu do state pre aktualizáciu
    state.conn_info_text = conn_info_text
    
    # Tlačidlá
    btn_frame = ttk.Frame(frame)
    btn_frame.pack(fill='x', pady=10)
    
    state.btn_test_connection = ttk.Button(btn_frame, text="🔄 Otestovať pripojenie", command=lambda: safe_check_connection(state))
    state.btn_test_connection.pack(side='left', padx=5)
    
    state.btn_load_expiries = ttk.Button(btn_frame, text="📋 Načítať expirácie", command=lambda: safe_load_expiries(state))
    state.btn_load_expiries.pack(side='left', padx=5)

    expiry_note = ttk.Label(btn_frame, textvariable=state.expiry_filter_note_var, font=('Arial', 9, 'italic'), foreground='gray')
    expiry_note.pack(side='left', padx=10)

    # Návod
    help_frame = ttk.LabelFrame(parent, text="Návod", padding=10)
    help_frame.pack(fill='both', expand=True, padx=10, pady=10)
    
    help_text = """
    PRED POUŽITÍM:
    1. Spustite Trader Workstation (TWS) alebo IB Gateway
    2. Povoľte API pripojenie v TWS/Gateway:
       Edit → Global Configuration → API → Settings
       ✓ Enable ActiveX and Socket Clients
       ✓ Read-Only API: Áno (bezpečnejšie)
    
    3. Nastavte správny port:
       • TWS Paper Trading: 7497 (Vyberte profil PAPER)
       • IB Gateway Live:   4001 (Vyberte profil LIVE)
       • TWS Live Trading:  7496 (Vyberte profil LIVE a zmeňte config ak treba)

    4. Uistite sa, že máte OPRA Market Data subscription
       (potrebné pre options greeks - delta, theta)

    TIP: Pre testovanie vždy používajte profil PAPER.
    LIVE profil používajte len s IB Gateway a reálnym účtom.
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
            
            profile = state.get_current_profile()
            
            text = f"""
❌ PRIPOJENIE ZLYHALO
═══════════════════════════════════════════════
   Režim: {profile.get('mode', 'UNKNOWN')} ({profile.get('label', '')})
   Port:  {state.port_var.get()}
   Chyba: {info.get('error', 'Neznáma chyba')}
═══════════════════════════════════════════════
Skontrolujte:
1. Je spustený {profile.get('label', 'TWS/Gateway')}?
2. Je API povolené v nastaveniach?
3. Je v {profile.get('label', 'softvéri')} nastavený port {state.port_var.get()}?
"""
            conn_info_text.insert(tk.END, text)
            conn_info_text.config(state='disabled')
    
    # Nahraď metódu
    state.update_connection_status = update_with_text

def safe_check_connection(state):
    state.btn_test_connection.config(state='disabled')
    state.check_connection()
    # Povolíme tlačidlo až po dokončení (v check_connection callbacku alebo timeout)
    state.root.after(5000, lambda: state.btn_test_connection.config(state='normal'))

def safe_load_expiries(state):
    state.btn_load_expiries.config(state='disabled')
    state.load_expiries()
    # Povolíme tlačidlo až po 10s (load expiries trvá dlhšie)
    state.root.after(10000, lambda: state.btn_load_expiries.config(state='normal'))