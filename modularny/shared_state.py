#!/usr/bin/env python3
"""
SharedState - Spoločný stav pre všetky moduly Hedge Manager GUI
"""
import tkinter as tk
from tkinter import ttk, messagebox
import subprocess
import threading
import json
import os
from datetime import datetime


class SharedState:
    """Spoločný stav pre všetky záložky"""
    
    def __init__(self, root):
        self.root = root
        
        # Archív nastavení
        self.settings_file = '/home/narbon/Aplikácie/tws-webapp/settings_archive.json'
        self.saved_strategies = {}
        
        # Premenné
        self.symbol_var = tk.StringVar(value="SPY")
        self.port_var = tk.StringVar(value="7496")
        self.min_premium_var = tk.StringVar(value="0.70")
        self.short_expiry_var = tk.StringVar()
        self.long_expiry_var = tk.StringVar()
        
        # ATR nastavenia
        self.atr_7d = None
        self.atr_last_updated = None
        self.atr_multiplier_var = tk.DoubleVar(value=2.0)
        
        # Stoploss na cenu opcie (násobok pôvodnej ceny)
        self.option_stoploss_mult_var = tk.DoubleVar(value=2.0)
        
        # Pre position monitor
        self.short_strike_var = tk.StringVar()
        self.roll_trigger_var = tk.StringVar(value="-0.30")
        
        # Typ opcie (PUT/CALL)
        self.option_type_var = tk.StringVar(value="PUT")
        
        # Pre výpočty
        self.iv_var = tk.StringVar(value="0.18")
        self.rate_var = tk.StringVar(value="0.05")
        
        # Pre Margin Optimizer
        self.broker_var = tk.StringVar(value="IBKR")
        self.max_margin_var = tk.StringVar(value="5000")
        self.min_roi_var = tk.StringVar(value="3.0")
        self.dte_offsets_var = tk.StringVar(value="0,7,14,21,30")
        
        # Pre Spread Kalkulátor (manuálne zadanie)
        self.calc_short_strike_var = tk.StringVar()
        self.calc_short_expiry_var = tk.StringVar()
        self.calc_short_premium_var = tk.StringVar()
        self.calc_long_strike_var = tk.StringVar()
        self.calc_long_expiry_var = tk.StringVar()
        self.calc_long_premium_var = tk.StringVar()
        self.calc_long_theta_var = tk.StringVar()
        self.calc_long_theta_source_var = tk.StringVar(value="N/A")
        self.calc_long_theta_entry = None
        self.calc_underlying_price_var = tk.StringVar()
        
        # Balancer (samostatné polia)
        self.bal_long_type_var = tk.StringVar(value="CALL")
        self.bal_long_strike_var = tk.StringVar()
        self.bal_long_expiry_var = tk.StringVar()
        self.bal_long_premium_var = tk.StringVar()
        self.bal_long_theta_var = tk.StringVar()
        self.bal_long_strike_entry = None
        self.bal_opposite_strike_entry = None
        self.bal_long_theta_entry = None
        self.bal_opposite_theta_entry = None
        self.bal_underlying_var = tk.StringVar()
        self.bal_iv_var = tk.StringVar(value=self.iv_var.get())
        self.bal_opposite_type_var = tk.StringVar(value="PUT")
        self.bal_opposite_strike_var = tk.StringVar()
        self.bal_opposite_premium_var = tk.StringVar()
        self.bal_opposite_theta_var = tk.StringVar()
        self.bal_last_analysis = None
        self.bal_type_note_var = tk.StringVar(value="")
        # Plotting controls
        self.bal_plot_metric_var = tk.StringVar(value='Price')
        self.bal_plot_atr_mult_var = tk.DoubleVar(value=1.0)
        
        # Trace pre automatické prepočítavanie stoploss
        self.calc_short_strike_var.trace_add('write', lambda *args: self._auto_recalc_stoploss())
        self.calc_short_expiry_var.trace_add('write', lambda *args: self._auto_recalc_stoploss())
        self.iv_var.trace_add('write', lambda *args: self._auto_recalc_stoploss())
        
        # Connection status
        self.connected = False
        self.connection_info = {}
        
        # Výsledky
        self.last_result = None
        self.alternatives = []
        self.scenarios = None
        
        # Stop flag pre optimalizáciu
        self.stop_optimization_flag = False
        self.optimization_process = None
        
        # Pre interaktívny optimizer
        self.available_expiries = []
        
        # Pre Roll Optimizer
        self.roll_current_strike_var = tk.StringVar()
        self.roll_current_expiry_var = tk.StringVar()
        self.roll_current_premium_var = tk.StringVar()
        self.roll_current_dte_var = tk.StringVar()
        self.roll_underlying_var = tk.StringVar()
        self.roll_total_invested_var = tk.StringVar(value="0")
        self.roll_received_credit_var = tk.StringVar(value="0")
        
        # Status bar widgets (budú nastavené v create_status_bar)
        self.conn_indicator = None
        self.conn_label = None
        
        # Callback pre auto-recalc stoploss (bude nastavený v kalkulátore)
        self._auto_recalc_callback = None
        self._bal_opposite_strike_callback = None
        
        # Načítaj nastavenia
        self.load_settings_file()
    
    def set_auto_recalc_callback(self, callback):
        """Nastaví callback pre automatické prepočítavanie stoploss"""
        self._auto_recalc_callback = callback
    
    def set_bal_opposite_strike_callback(self, callback):
        """Nastaví callback pre zmenu bal_opposite_strike"""
        self._bal_opposite_strike_callback = callback
        self.bal_opposite_strike_var.trace_add('write', lambda *args: self._bal_opposite_strike_callback())
    
    def _auto_recalc_stoploss(self):
        """Interná metóda pre trace - volá callback ak je nastavený"""
        if self._auto_recalc_callback:
            self._auto_recalc_callback()
    
    def create_status_bar(self):
        """Vytvorí status bar s indikátorom pripojenia"""
        status_frame = ttk.Frame(self.root)
        status_frame.pack(fill='x', padx=5, pady=2)
        
        # Indikátor pripojenia
        self.conn_indicator = tk.Label(status_frame, text="●", font=('Arial', 14), fg='gray')
        self.conn_indicator.pack(side='left', padx=2)
        
        self.conn_label = ttk.Label(status_frame, text="Nepripojené", font=('Arial', 9))
        self.conn_label.pack(side='left', padx=5)
        
        ttk.Button(status_frame, text="🔄 Test pripojenia", command=self.check_connection).pack(side='left', padx=10)
        
        # Pravá strana - port
        ttk.Label(status_frame, text="Port:").pack(side='right', padx=2)
        port_combo = ttk.Combobox(status_frame, textvariable=self.port_var, values=["7496", "7497"], width=6)
        port_combo.pack(side='right', padx=2)
        port_combo.bind('<<ComboboxSelected>>', lambda e: self.check_connection())
    
    def check_connection(self):
        """Otestuje pripojenie k TWS"""
        if self.conn_indicator:
            self.conn_indicator.config(fg='yellow')
        if self.conn_label:
            self.conn_label.config(text="Testujem...")
        
        def run():
            port = self.port_var.get()
            try:
                script_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'scripts', 'tws_check_connection.py')
                result = subprocess.run(
                    ['python3', script_path, str(port)], 
                    capture_output=True, text=True, timeout=15,
                    cwd='/home/narbon/Aplikácie/tws-webapp'
                )
                
                if result.returncode == 0 and result.stdout.strip():
                    try:
                        info = json.loads(result.stdout.strip())
                        self.root.after(0, lambda: self.update_connection_status(info))
                    except:
                        self.root.after(0, lambda: self.update_connection_status({'connected': False, 'error': result.stdout + result.stderr}))
                else:
                    self.root.after(0, lambda: self.update_connection_status({'connected': False, 'error': result.stderr}))
            except subprocess.TimeoutExpired:
                self.root.after(0, lambda: self.update_connection_status({'connected': False, 'error': 'Timeout - TWS neodpovedá'}))
            except Exception as e:
                self.root.after(0, lambda: self.update_connection_status({'connected': False, 'error': str(e)}))
        
        threading.Thread(target=run, daemon=True).start()
    
    def update_connection_status(self, info):
        """Aktualizuje zobrazenie stavu pripojenia"""
        self.connected = info.get('connected', False)
        self.connection_info = info
        
        if self.connected:
            if self.conn_indicator:
                self.conn_indicator.config(fg='green')
            if self.conn_label:
                self.conn_label.config(text=f"Pripojené k TWS (port {info.get('port', '?')})")
            
            # Automaticky načítaj expirácie
            self.load_expiries()
        else:
            if self.conn_indicator:
                self.conn_indicator.config(fg='red')
            if self.conn_label:
                self.conn_label.config(text="Nepripojené")
    
    def load_expiries(self):
        """Načíta dostupné expirácie z TWS"""
        # Použij správny option type
        right = 'C' if self.option_type_var.get() == 'CALL' else 'P'
        symbol = self.symbol_var.get()
        port = self.port_var.get()
        
        print(f"DEBUG load_expiries: symbol={symbol}, port={port}, right={right}")
        
        # Zobraz status
        if hasattr(self, 'calc_status_label'):
            self.calc_status_label.config(text="Načítavam expirácie z TWS...")
        
        def run():
            try:
                script_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'scripts', 'tws_load_expiries.py')
                print(f"DEBUG: Spúšťam skript: {script_path}")
                print(f"DEBUG: Príkaz: python3 {script_path} {port} {symbol} {right}")
                
                # Timeout 40 sekúnd (25s pre reqContractDetails + 15s pre ostatné operácie)
                result = subprocess.run(
                    ['python3', script_path, str(port), symbol, right], 
                    capture_output=True, text=True, timeout=40,
                    cwd='/home/narbon/Aplikácie/tws-webapp'
                )
                
                print(f"DEBUG: returncode={result.returncode}")
                print(f"DEBUG: stdout={result.stdout[:200] if result.stdout else 'None'}")
                print(f"DEBUG: stderr={result.stderr[:200] if result.stderr else 'None'}")
                
                if result.returncode == 0 and result.stdout.strip():
                    expiries = result.stdout.strip().split(',')
                    # Filtruj prázdne hodnoty
                    expiries = [e.strip() for e in expiries if e.strip()]
                    print(f"DEBUG: Našlo sa {len(expiries)} expirácií: {expiries[:5]}...")
                    if expiries:
                        self.root.after(0, lambda: self.update_expiry_combos(expiries))
                    else:
                        error_msg = "Nenašli sa žiadne expirácie"
                        print(f"DEBUG: {error_msg}")
                        self.root.after(0, lambda: self.handle_expiry_error(error_msg))
                else:
                    # Získaj chybovú správu
                    if result.stderr:
                        error_msg = result.stderr.strip()
                        # Odstráň "ERROR:" prefix ak existuje
                        if error_msg.startswith("ERROR:"):
                            error_msg = error_msg[6:].strip()
                    elif result.stdout:
                        error_msg = result.stdout.strip()
                    else:
                        error_msg = f"Skript skončil s kódom {result.returncode}"
                    print(f"DEBUG: Chyba: {error_msg}")
                    self.root.after(0, lambda: self.handle_expiry_error(error_msg))
            except subprocess.TimeoutExpired:
                print("DEBUG: Timeout!")
                self.root.after(0, lambda: self.handle_expiry_error("Timeout - TWS neodpovedá (skúste to znova)"))
            except Exception as e:
                print(f"DEBUG: Exception: {e}")
                import traceback
                traceback.print_exc()
                self.root.after(0, lambda: self.handle_expiry_error(f"Chyba: {str(e)}"))
        
        threading.Thread(target=run, daemon=True).start()
    
    def handle_expiry_error(self, error_msg):
        """Spracuje chybu pri načítaní expirácií"""
        messagebox.showerror("Chyba načítania expirácií", 
            f"Nepodarilo sa načítať expirácie.\n\n"
            f"Chyba: {error_msg}\n\n"
            f"Skontrolujte:\n"
            f"• Je TWS/IB Gateway spustený?\n"
            f"• Je port {self.port_var.get()} správny? (7496=live, 7497=paper)\n"
            f"• Je povolené API pripojenie v TWS nastaveniach?")
    
    def update_expiry_combos(self, expiries):
        """Aktualizuje combobox s expiráciami"""
        # Uložíme expirácie pre interaktívny optimizer
        self.available_expiries = expiries
        
        # Aktualizuj comboboxy v kalkulátore
        if hasattr(self, 'calc_short_expiry_combo'):
            self.calc_short_expiry_combo['values'] = expiries
        if hasattr(self, 'calc_long_expiry_combo'):
            self.calc_long_expiry_combo['values'] = expiries
        
        # Aktualizuj comboboxy v monitori
        if hasattr(self, 'monitor_expiry_combo'):
            self.monitor_expiry_combo['values'] = expiries
        
        # Aktualizuj comboboxy v Roll Optimizer
        if hasattr(self, 'roll_expiry_combo'):
            self.roll_expiry_combo['values'] = expiries
        
        # Nastav defaultné hodnoty
        if len(expiries) >= 2:
            self.calc_short_expiry_var.set(expiries[0])
        if len(expiries) >= 5:
            self.calc_long_expiry_var.set(expiries[4])
        elif len(expiries) >= 2:
            self.calc_long_expiry_var.set(expiries[-1])
        
        # Aktualizuj status ak existuje
        if hasattr(self, 'calc_status_label'):
            self.calc_status_label.config(text=f"✓ Načítaných {len(expiries)} expirácií")
    
    def load_settings_file(self):
        """Načíta archív nastavení zo súboru"""
        try:
            if os.path.exists(self.settings_file):
                with open(self.settings_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    self.saved_strategies = data.get('strategies', {})
            else:
                self.saved_strategies = {}
        except Exception as e:
            print(f"Chyba pri načítavaní nastavení: {e}")
            self.saved_strategies = {}
    
    def save_settings_file(self):
        """Uloží archív nastavení do súboru"""
        try:
            data = {
                'strategies': self.saved_strategies
            }
            with open(self.settings_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
        except Exception as e:
            messagebox.showerror("Chyba", f"Nepodarilo sa uložiť nastavenia:\n{e}")
    
    def save_strategy(self, strategy_name_var, strategy_combo=None):
        """Uloží aktuálne nastavenia kalkulátora"""
        name = strategy_name_var.get().strip()
        if not name:
            name = messagebox.askstring("Názov stratégie", "Zadajte názov pre túto stratégiu:")
            if not name:
                return
            name = name.strip()
        
        # Zber aktuálne hodnoty z kalkulátora
        try:
            strategy = {
                'symbol': self.symbol_var.get(),
                'option_type': self.option_type_var.get(),
                'underlying_price': self.calc_underlying_price_var.get(),
                'short_strike': self.calc_short_strike_var.get(),
                'short_expiry': self.calc_short_expiry_var.get(),
                'short_premium': self.calc_short_premium_var.get(),
                'long_strike': self.calc_long_strike_var.get(),
                'long_expiry': self.calc_long_expiry_var.get(),
                'long_premium': self.calc_long_premium_var.get(),
                'broker': self.broker_var.get(),
                'saved_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            }
            
            self.saved_strategies[name] = strategy
            strategy_name_var.set(name)
            
            # Aktualizuj dropdown ak existuje
            if strategy_combo:
                strategy_names = sorted(self.saved_strategies.keys())
                strategy_combo['values'] = strategy_names
            
            self.save_settings_file()
            messagebox.showinfo("Úspech", f"Stratégia '{name}' bola uložená.\n\nCelkom stratégií: {len(self.saved_strategies)}")
            
        except Exception as e:
            messagebox.showerror("Chyba", f"Nepodarilo sa uložiť stratégiu:\n{e}")
    
    def load_strategy(self, strategy_name_var, auto=False):
        """Načíta vybranú stratégiu do kalkulátora"""
        name = strategy_name_var.get().strip()
        if not name:
            messagebox.showwarning("Chyba", "Vyberte stratégiu zo zoznamu")
            return
        
        if name not in self.saved_strategies:
            messagebox.showerror("Chyba", f"Stratégia '{name}' neexistuje")
            return
        
        try:
            strategy = self.saved_strategies[name]
            
            # Načítaj hodnoty do kalkulátora
            self.symbol_var.set(strategy.get('symbol', 'SPY'))
            self.option_type_var.set(strategy.get('option_type', 'CALL'))
            self.calc_underlying_price_var.set(strategy.get('underlying_price', ''))
            self.calc_short_strike_var.set(strategy.get('short_strike', ''))
            self.calc_short_expiry_var.set(strategy.get('short_expiry', ''))
            self.calc_short_premium_var.set(strategy.get('short_premium', ''))
            self.calc_long_strike_var.set(strategy.get('long_strike', ''))
            self.calc_long_expiry_var.set(strategy.get('long_expiry', ''))
            self.calc_long_premium_var.set(strategy.get('long_premium', ''))
            self.broker_var.set(strategy.get('broker', 'IBKR'))
            
            self.save_settings_file()
            
            if not auto:
                saved_at = strategy.get('saved_at', 'Neznámy dátum')
                messagebox.showinfo("Načítané", f"Stratégia '{name}' bola načítaná.\n\nUložená: {saved_at}")
                
        except Exception as e:
            messagebox.showerror("Chyba", f"Nepodarilo sa načítať stratégiu:\n{e}")

