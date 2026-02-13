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
import sys
import time
from datetime import datetime


class SharedState:
    """Spoločný stav pre všetky záložky"""
    
    def __init__(self, root):
        self.root = root
        
        # Archív nastavení - upravená cesta na aktuálny projekt
        BASE_DIR = os.path.dirname(os.path.dirname(__file__))
        self.settings_file = os.path.join(BASE_DIR, 'settings_archive.json')
        self.profiles_file = os.path.join(BASE_DIR, 'config', 'profiles.json')
        self.saved_strategies = {}
        self.saved_gamma_scalper_strategies = {}
        self.saved_gamma_semafor_configs = {} 
        self.ticker_settings = {} # Archív nastavení pre jednotlivé tickery (drift tol atď.)
        self.custom_pairs = {} # NOVÉ: Definície párov pre Swing Watcher {názov: [sym1, sym2, ...]}
        self.profiles = {}
        
        # Načítaj profily
        self.load_profiles()
        
        # Premenné
        self.symbol_var = tk.StringVar(value="SPY")
        
        # Nastav default profil
        default_profile = self.profiles.get("default_profile", "PAPER")
        if default_profile not in self.profiles.get("profiles", {}):
             default_profile = "PAPER"
             
        self.current_profile_var = tk.StringVar(value=default_profile)
        self.port_var = tk.StringVar(value="7497") # Bude prepísané podľa profilu
        self.current_port = "7497" # Verzia pre background thready
        
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
        self.expiry_filter_note_var = tk.StringVar(value="")
        self.gamma_status_var = tk.StringVar(value="Gamma/Teta: —")
        self.monitor_status_var = tk.StringVar(value="Monitor: —") # Nová premenná pre status bar
        self.heartbeat_var = tk.StringVar(value="[ -- ]") # Vizuálny Heartbeat
        self.last_update_time_var = tk.StringVar(value="Posledná aktualizácia: ---")
        self.tws_watchdog_var = tk.StringVar(value="TWS: --")
        self.vix_value = None
        self._gamma_status_info = {}
        
        # Pre position monitor
        self.monitor_selected_symbols = {} # Slovník {symbol: tk.BooleanVar}
        
        # Pre Margin Optimizer
        self.broker_var = tk.StringVar(value="IBKR")
        self.max_margin_var = tk.StringVar(value="5000")
        self.min_roi_var = tk.StringVar(value="3.0")
        self.dte_offsets_var = tk.StringVar(value="0,7,14,21,30")

        # Pre Gamma Scalper
        self.gs_target_delta_var = tk.StringVar(value="0.30")
        self.gs_strategy_name_var = tk.StringVar()
        self.gs_strategy_notes_var = tk.StringVar() # Nová premenná pre poznámky k stratégii
        self.gs_semafor_config_name_var = tk.StringVar() # Názov pre konfiguráciu Semafora
        self.gs_semafor_config_notes_var = tk.StringVar() # Poznámky pre konfiguráciu Semafora
        self.gs_search_process = None # Pre uloženie referencie na spustený proces vyhľadávania
        self.gs_auto_monitor_var = tk.BooleanVar(value=False) # Automatické sledovanie pozícií
        self.gs_auto_scalp_var = tk.BooleanVar(value=False) # Automatické rebalansovanie akciami (Full Auto)
        self.gs_drift_tol = tk.StringVar(value="0.20") # Tolerancia driftu pre Gamma Scalper
        self.gs_target_delta_pos_var = tk.StringVar(value="0.00") # Cieľová delta pozície (0.0=neutral, >0=long, <0=short)
        self.gs_manual_call_strike_var = tk.StringVar(value="")
        self.gs_manual_put_strike_var = tk.StringVar(value="")

        # Archív konzultácií
        self.consultations_file = os.path.join(BASE_DIR, 'consultations.json')
        self.consultations = []
        self.load_consultations()

        # Gamma Semafor nastavenia (prísne - Exit pod 3.0)
        self.gamma_semafor_thresholds = {
            "strong_buy": 6.00,
            "buy": 4.50,
            "neutral": 3.00,
            "stop": 1.50,
            "strong_stop": 0.00
        }

        # Premenné pre GUI Semaforu
        self.gs_strong_buy_threshold_var = tk.StringVar(value=str(self.gamma_semafor_thresholds["strong_buy"]))
        self.gs_buy_threshold_var = tk.StringVar(value=str(self.gamma_semafor_thresholds["buy"]))
        self.gs_neutral_threshold_var = tk.StringVar(value=str(self.gamma_semafor_thresholds["neutral"]))
        self.gs_stop_threshold_var = tk.StringVar(value=str(self.gamma_semafor_thresholds["stop"]))

        # Pre model-prvý prístup
        self.gs_model_priority_var = tk.BooleanVar(value=False) # True ak preferujeme model pred live datami
        
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
        self.bal_opposite_manual_override = False
        self.bal_opposite_internal_update = False
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
        
        # Monitor - vybrané symboly na hedžovanie
        self.monitor_selected_symbols = {} # Slovník sym -> tk.BooleanVar
        
        # NOVÉ: Swing Hunter - vybrané symboly na lov signálov
        self.hunter_selected_symbols = {} # Slovník sym -> tk.BooleanVar
        self.hunter_custom_tickers = [] # NOVÉ: Vlastné tickery pre Swing Hunter
        self.hunter_pinned_symbols = []
        
        # NOVÉ: PMCC Hunter - vlastné symboly
        self.pmcc_symbols = [] # Zoznam symbolov pre PMCC
        
        # NOVÉ: Swing Profit Watcher nastavenia
        self.monitor_profit_target_pct = tk.StringVar(value="50.0") # Cieľ pre zatvorenie opcií
        self.monitor_profit_warning_pct = tk.StringVar(value="30.0") # Cieľ pre upozornenie opcií
        self.monitor_stock_profit_target_usd = tk.StringVar(value="12.0") # Cieľ pre akcie (12x poplatok)
        self.monitor_auto_close_var = tk.BooleanVar(value=False) # Či má robot sám zatvárať
        self.monitor_auto_restart_var = tk.BooleanVar(value=False) # NOVÉ: Re-entry po zatvorení (Cycle)
        
        # NOVÉ: Trailing Stop nastavenia
        self.monitor_trailing_opt_pct = tk.StringVar(value="5.0") # O koľko % musí klesnúť profit z peaku (Opcie)
        self.monitor_trailing_stk_usd = tk.StringVar(value="2.0") # O koľko $ musí klesnúť profit z peaku (Akcie)
        self.trailing_peaks = {} # Pamäť pre High Water Mark {pos_key: max_pl}
        
        # Automatické ukladanie pri zmene nastavení Swing Watchera
        self.monitor_profit_target_pct.trace_add('write', lambda *args: self.save_settings_file())
        self.monitor_profit_warning_pct.trace_add('write', lambda *args: self.save_settings_file())
        self.monitor_stock_profit_target_usd.trace_add('write', lambda *args: self.save_settings_file())
        self.monitor_auto_close_var.trace_add('write', lambda *args: self.save_settings_file())
        self.monitor_auto_restart_var.trace_add('write', lambda *args: self.save_settings_file())
        self.monitor_trailing_opt_pct.trace_add('write', lambda *args: self.save_settings_file())
        self.monitor_trailing_stk_usd.trace_add('write', lambda *args: self.save_settings_file())
        
        # Status bar widgets (budú nastavené v create_status_bar)
        self.conn_indicator = None
        self.conn_label = None
        
        # Callback pre auto-recalc stoploss (bude nastavený v kalkulátore)
        self._auto_recalc_callback = None
        self._bal_opposite_strike_callback = None
        
        # Cache pre dividendy
        self.dividend_cache = {} 
        self._is_loading = False # Poistka proti prepísaniu pri načítavaní

        # NOVÉ: Symbol Blocks - zoznamy symbolov zoskupené do blokov
        self.symbol_blocks = {} # {názov_bloku: [SYM1, SYM2, ...]}
        
        # Načítaj nastavenia
        self.load_settings_file()
        
        # Inicializuj port podľa profilu
        self.update_port_from_profile()
        
        # Trace pre zmenu profilu
        self.current_profile_var.trace_add('write', lambda *args: self.update_port_from_profile())

    def load_profiles(self):
        """Načíta profily pripojenia"""
        try:
            if os.path.exists(self.profiles_file):
                with open(self.profiles_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    self.profiles = data
            else:
                # Fallback ak súbor neexistuje
                self.profiles = {
                    "profiles": {
                        "PAPER": {"host": "127.0.0.1", "port": 7497, "clientId": 1, "label": "PAPER TRADING (TWS)", "mode": "TEST", "color": "green"},
                        "LIVE": {"host": "127.0.0.1", "port": 4001, "clientId": 0, "label": "LIVE TRADING (IB Gateway)", "mode": "LIVE", "color": "red"}
                    },
                    "default_profile": "PAPER"
                }
        except Exception as e:
            print(f"Chyba pri načítavaní profilov: {e}")
            self.profiles = {}

    def get_current_profile(self):
        """Vráti nastavenia aktuálneho profilu"""
        profile_name = self.current_profile_var.get()
        profiles_dict = self.profiles.get("profiles", {})
        return profiles_dict.get(profile_name, profiles_dict.get("PAPER", {}))

    def update_port_from_profile(self):
        """Aktualizuje port_var podľa vybraného profilu"""
        profile = self.get_current_profile()
        new_port = str(profile.get("port", 7497))
        self.port_var.set(new_port)
        self.current_port = new_port
        
        # Ak sme v LIVE režime, aktualizuj vizuál (ak existuje)
        if hasattr(self, 'update_profile_indicator'):
            self.update_profile_indicator()

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
        # Štýly pre malé tlačidlá
        style = ttk.Style()
        style.configure('Small.TButton', font=('Arial', 7))
        
        status_frame = ttk.Frame(self.root)
        status_frame.pack(fill='x', padx=5, pady=2)
        
        # Indikátor pripojenia
        self.conn_indicator = tk.Label(status_frame, text="●", font=('Arial', 14), fg='gray')
        self.conn_indicator.pack(side='left', padx=2)
        
        self.conn_label = ttk.Label(status_frame, text="Nepripojené", font=('Arial', 9))
        self.conn_label.pack(side='left', padx=5)
        
        # NOVÉ: Heartbeat a čas
        self.heartbeat_label = tk.Label(status_frame, textvariable=self.heartbeat_var, font=('Courier', 10, 'bold'), fg='#2980b9')
        self.heartbeat_label.pack(side='left', padx=10)
        
        self.last_update_label = ttk.Label(status_frame, textvariable=self.last_update_time_var, font=('Arial', 8))
        self.last_update_label.pack(side='left', padx=5)

        self.tws_watchdog_label = tk.Label(status_frame, textvariable=self.tws_watchdog_var, font=('Arial', 9, 'bold'))
        self.tws_watchdog_label.pack(side='left', padx=10)
        
        ttk.Button(status_frame, text="🔄 Test pripojenia", command=self.check_connection).pack(side='left', padx=10)
        
        # Monitor status uprostred
        self.monitor_status_label = tk.Label(status_frame, textvariable=self.monitor_status_var, font=('Arial', 9, 'bold'), fg='#555')
        self.monitor_status_label.pack(side='left', padx=20)
        
        # Pravá strana - Profil
        profiles_dict = self.profiles.get("profiles", {})
        profile_names = list(profiles_dict.keys())
        
        ttk.Label(status_frame, text="Režim:").pack(side='right', padx=2)
        
        # Štýl pre profil label
        self.profile_label = tk.Label(status_frame, text="", font=('Arial', 9, 'bold'), width=15)
        self.profile_label.pack(side='right', padx=5)

        self.gamma_status_label = ttk.Label(status_frame, textvariable=self.gamma_status_var, font=('Arial', 9))
        self.gamma_status_label.pack(side='right', padx=5)
        
        # ⚡ AKTUALIZOVAŤ VŠETKO (Schodišťový vypínač)
        btn_refresh = ttk.Button(status_frame, text="⚡ AKTUALIZOVAŤ VŠETKO", command=self.refresh_all)
        btn_refresh.pack(side='right', padx=10)

        # Inicializuj indikátor
        self.update_profile_indicator()
        self.start_tws_watchdog()

    def refresh_all(self):
        """Globálna aktualizácia všetkých modulov naraz"""
        try:
            from modularny.tab_monitor import check_position
            from modularny.tab_gamma_scalper import check_position_gs
            
            # Získame vybrané symboly
            selected = [sym for sym, var in self.monitor_selected_symbols.items() if var.get()]
            for pair_data in self.custom_pairs.values():
                pair_syms = pair_data.get('symbols', []) if isinstance(pair_data, dict) else pair_data
                for ps in pair_syms:
                    if ps not in selected:
                        selected.append(ps)
            
            # 1. Aktualizovať hlavný monitor
            check_position(self, selected)
            
            # 2. Aktualizovať robotický monitor (Gamma Scalper)
            check_position_gs(self)

            # 3. Aktualizovať Swing Hunter (ak existuje)
            try:
                import modularny.tab_swing_hunter as hunter
                if hasattr(self, 'hunter_tree') and hasattr(self, 'hunter_rsi_p') and hasattr(self, 'hunter_rvi_p') and hasattr(self, 'hunter_tf_v'):
                    # Tu necháme force=False, aby sa využila cache
                    hunter.refresh_hunter(self, self.hunter_tree, self.hunter_rsi_p, self.hunter_rvi_p, self.hunter_tf_v, force=False)
            except: pass
            
            # Reset heartbeat indikátora pre vizuálnu odozvu
            self.heartbeat_var.set("[⚡⚡]")
            self.root.after(1000, lambda: self.heartbeat_var.set("[ OK ]"))
            
            print("🚀 GLOBAL REFRESH: Spustená kompletná aktualizácia.")
        except Exception as e:
            print(f"Chyba pri globálnej aktualizácii: {e}")

    def start_tws_watchdog(self):
        if hasattr(self, '_tws_watchdog_thread') and self._tws_watchdog_thread and self._tws_watchdog_thread.is_alive():
            return
        def run():
            root_dir = os.path.dirname(os.path.dirname(__file__))
            script = os.path.join(root_dir, 'scripts', 'tws_check_connection.py')
            was_connected = None
            alert_shown = False
            while True:
                try:
                    # Kontrola či root ešte existuje (prevencia RuntimeError pri vypínaní)
                    if not self.root or not self.root.winfo_exists():
                        break
                except:
                    break
                    
                port = self.current_port
                cmd = [sys.executable, script, str(port)]
                connected = False
                error_msg = ""
                try:
                    res = subprocess.run(cmd, capture_output=True, text=True, timeout=12)
                    payload = json.loads(res.stdout.strip()) if res.stdout else {'connected': False}
                    connected = payload.get('connected', False)
                    error_msg = payload.get('error', '')
                except Exception as exc:
                    error_msg = str(exc)
                status_text = "TWS: OK" if connected else "TWS: DISCONNECTED"
                fg = '#2e7d32' if connected else '#c62828'
                self.root.after(0, lambda text=status_text, color=fg: [self.tws_watchdog_var.set(text), self.tws_watchdog_label.config(fg=color)])
                if was_connected is None:
                    was_connected = connected
                else:
                    if was_connected and not connected and not alert_shown:
                        msg = error_msg or "API connection lost"
                        self.root.after(0, lambda msg=msg: messagebox.showwarning("TWS Watchdog", f"Stratené spojenie s TWS:\n{msg}"))
                        alert_shown = True
                    elif not was_connected and connected:
                        alert_shown = False
                was_connected = connected
                time.sleep(25)
        self._tws_watchdog_thread = threading.Thread(target=run, daemon=True)
        self._tws_watchdog_thread.start()

    def update_profile_indicator(self):
        """Aktualizuje indikátor profilu v status bare"""
        if hasattr(self, 'profile_label'):
            profile = self.get_current_profile()
            self.profile_label.config(text=profile.get('mode', 'TEST'), fg=profile.get('color', 'black'))

    def update_gamma_display(self, ratio, sentiment, iv_value=None, color='gray'):
        """Aktualizuje text status baru pre Gamma/Teta pomer + IV/VIX"""
        self._gamma_status_info = {
            'ratio': ratio,
            'sentiment': sentiment,
            'iv': iv_value,
            'vix': self.vix_value,
            'color': color
        }
        self._refresh_gamma_status_label()

    def _refresh_gamma_status_label(self):
        info = self._gamma_status_info or {}
        ratio = info.get('ratio')
        sentiment = info.get('sentiment', '')
        iv_value = info.get('iv')
        vix_value = info.get('vix')
        label_color = info.get('color', 'gray')
        if ratio is None:
            text = "Gamma/Teta: —"
        else:
            text = f"Γ/Θ {ratio:.2f} {sentiment}"
        if iv_value:
            text += f" | IV {iv_value:.1%}"
        if vix_value:
            text += f" | VIX {vix_value:.2f}"
        self.gamma_status_var.set(text)
        if hasattr(self, 'gamma_summary_label'):
            self.gamma_summary_label.config(foreground=label_color)

    def fetch_vix(self):
        """Stiahne poslednú hodnotu VIX cez yfinance"""
        def run():
            vix = None
            try:
                import yfinance as yf
                df = yf.download("^VIX", period="2d", interval="5m", progress=False)
                if df is not None and not df.empty:
                    vix = df['Close'].iloc[-1]
            except Exception as e:
                print(f"DEBUG: VIX fetch failed: {e}")
            finally:
                self.vix_value = vix
                self.root.after(0, lambda: self._refresh_gamma_status_label())

        threading.Thread(target=run, daemon=True).start()

    def get_earnings_date(self, symbol):
        """Získa dátum najbližších výsledkov (Earnings) pre daný symbol"""
        try:
            import yfinance as yf
            import logging
            logging.getLogger('yfinance').setLevel(logging.CRITICAL)
            
            # ETFs nemajú earnings a yfinance pre ne hádže 404 chyby do konzoly
            ticker = yf.Ticker(symbol)
            
            # Rýchla kontrola či ide o ETF (ak chýba 'earnings' v info)
            # Alebo jednoducho skúsime calendar a ak zlyhá, sme ticho
            try:
                calendar = ticker.calendar
                if calendar is not None:
                    e_dates = None
                    if isinstance(calendar, dict):
                        e_dates = calendar.get('Earnings Date') or calendar.get('Earnings High')
                    elif hasattr(calendar, 'empty') and not calendar.empty:
                        e_dates = calendar.get('Earnings Date') or calendar.get('Earnings High')
                    
                    if e_dates is not None and isinstance(e_dates, list) and len(e_dates) > 0:
                        return e_dates[0]
                    elif e_dates is not None:
                        return e_dates
            except:
                pass # Tiché zlyhanie pre ETFs
            return None
        except:
            return None
    
    def get_dividend_info(self, symbol):
        """Získa informácie o najbližšej dividende (výška a ex-date)"""
        if symbol in self.dividend_cache:
            # Cache platí 12 hodín
            data, ts = self.dividend_cache[symbol]
            if (datetime.now() - ts).total_seconds() < 43200:
                return data

        try:
            import yfinance as yf
            import pandas as pd
            import logging
            logging.getLogger('yfinance').setLevel(logging.CRITICAL)
            
            ticker = yf.Ticker(symbol)
            
            # 1. Skúsime získať ex-date z kalendára
            ex_date = None
            try:
                cal = ticker.calendar
                if cal is not None:
                    if isinstance(cal, dict):
                        ex_date = cal.get('Ex-Dividend Date') or cal.get('Dividend Date')
                    elif hasattr(cal, 'empty') and not cal.empty:
                        if 'Ex-Dividend Date' in cal.index:
                            ex_date = cal.loc['Ex-Dividend Date'].iloc[0]
                        elif 'Dividend Date' in cal.index:
                            ex_date = cal.loc['Dividend Date'].iloc[0]
            except:
                pass

            # 2. Skúsime získať výšku dividendy (per payment)
            div_rate = 0
            try:
                divs = ticker.dividends
                if divs is not None and len(divs) > 0:
                    div_rate = float(divs.iloc[-1])
                else:
                    # Ak nie je história, skúsime info (iba ak je to akcia)
                    info = ticker.info
                    annual_rate = info.get('dividendRate') or info.get('trailingAnnualDividendRate', 0)
                    div_rate = annual_rate / 4.0 if (annual_rate and annual_rate > 0) else 0
            except:
                pass

            # 3. Ak stále nemáme ex-date, skúsime info
            if not ex_date:
                try:
                    info = ticker.info
                    ex_date_raw = info.get('exDividendDate')
                    if ex_date_raw:
                        from datetime import date
                        if isinstance(ex_date_raw, int):
                            ex_date = date.fromtimestamp(ex_date_raw)
                        else:
                            ex_date = datetime.strptime(str(ex_date_raw), '%Y-%m-%d').date()
                except:
                    pass

            result = {'rate': div_rate, 'ex_date': ex_date}
            self.dividend_cache[symbol] = (result, datetime.now())
            return result
        except Exception as e:
            # DEBUG: Dividend fetch failed for {symbol}: {e}
            return {'rate': 0, 'ex_date': None}
    
    def check_connection(self):
        """Otestuje pripojenie k TWS"""
        if self.conn_indicator:
            self.conn_indicator.config(fg='yellow')
        if self.conn_label:
            self.conn_label.config(text="Testujem...")
        
        port = self.current_port
        def run():
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
            
            # Automaticky načítaj expirácie - VYPNUTÉ pre stabilitu
            # self.load_expiries()
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
            
        # Progress Bar
        if hasattr(self, 'gs_scan_progress'):
            self.gs_scan_progress.pack(fill='x', pady=(5, 0))
            self.gs_scan_progress['maximum'] = 100
            self.gs_scan_progress['value'] = 0
            def fake_progress(current=0):
                if self.gs_scan_progress.winfo_exists() and self.gs_scan_progress.winfo_ismapped():
                    if current < 90:
                        self.gs_scan_progress['value'] = current
                        self.root.after(200, lambda: fake_progress(current + 5))
            fake_progress()

        def run():
            try:
                script_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'scripts', 'tws_load_expiries.py')
                # ...
                result = subprocess.run(
                    ['python3', script_path, str(port), symbol, right], 
                    capture_output=True, text=True, timeout=60,
                    cwd='/home/narbon/Aplikácie/tws-webapp'
                )
                
                # Skryť progress bar
                self.root.after(0, lambda: self.gs_scan_progress.pack_forget() if hasattr(self, 'gs_scan_progress') else None)
                
                print(f"DEBUG: returncode={result.returncode}")
                # ...

                print(f"DEBUG: stdout={result.stdout[:200] if result.stdout else 'None'}")
                print(f"DEBUG: stderr={result.stderr[:200] if result.stderr else 'None'}")
                
                filtered_note = ""
                if result.stderr:
                    for line in result.stderr.splitlines():
                        if "Weekday filtered" in line:
                            filtered_note = line.strip()
                            break
                self.root.after(0, lambda note=filtered_note: self.expiry_filter_note_var.set(note))

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
                    self.root.after(0, lambda: self.expiry_filter_note_var.set(""))
            except subprocess.TimeoutExpired:
                print("DEBUG: Timeout!")
                self.root.after(0, lambda: self.handle_expiry_error("Timeout - TWS neodpovedá (skúste to znova)"))
            except Exception as e:
                self.root.after(0, lambda: self.gs_scan_progress.pack_forget() if hasattr(self, 'gs_scan_progress') else None)
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
            
        # Aktualizuj combobox v Gamma Scalper
        if hasattr(self, 'gs_expiry_combo'):
            self.gs_expiry_combo['values'] = expiries
            if expiries:
                self.gs_expiry_combo.set(expiries[0])
        
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
    
    def load_consultations(self):
        """Načíta históriu konzultácií"""
        try:
            if os.path.exists(self.consultations_file):
                with open(self.consultations_file, 'r', encoding='utf-8') as f:
                    self.consultations = json.load(f)
            else:
                self.consultations = []
        except:
            self.consultations = []

    def save_consultation(self, user_text, ai_response):
        """Uloží novú konzultáciu do histórie"""
        entry = {
            'timestamp': datetime.now().strftime('%d.%m.%Y %H:%M:%S'),
            'user': user_text,
            'ai': ai_response
        }
        self.consultations.append(entry)
        try:
            with open(self.consultations_file, 'w', encoding='utf-8') as f:
                json.dump(self.consultations, f, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"Chyba pri ukladaní konzultácie: {e}")

    def load_settings_file(self):
        """Načíta archív nastavení zo súboru"""
        self._is_loading = True
        try:
            if os.path.exists(self.settings_file):
                with open(self.settings_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    self.saved_strategies = data.get('strategies', {})
                    self.saved_gamma_scalper_strategies = data.get('gamma_scalper_strategies', {})
                    self.saved_gamma_semafor_configs = data.get('gamma_semafor_configs', {})
                    self.ticker_settings = data.get('ticker_settings', {}) # Načítaj nastavenia tickerov
                    self.custom_pairs = data.get('custom_pairs', {}) # Načítaj definície párov
                    
                    # Načítaj globálne nastavenia Gamma Semaforu (len ako fallback, ak nie je vybratá konkrétna stratégia)
                    loaded_thresholds = data.get('gamma_semafor_thresholds', {})
                    self.gamma_semafor_thresholds["strong_buy"] = loaded_thresholds.get("strong_buy", self.gamma_semafor_thresholds["strong_buy"])
                    self.gamma_semafor_thresholds["buy"] = loaded_thresholds.get("buy", self.gamma_semafor_thresholds["buy"])
                    self.gamma_semafor_thresholds["neutral"] = loaded_thresholds.get("neutral", self.gamma_semafor_thresholds["neutral"])
                    self.gamma_semafor_thresholds["stop"] = loaded_thresholds.get("stop", self.gamma_semafor_thresholds["stop"])
                    
                    # Pokús sa načítať poslednú použitú konfiguráciu Semafora
                    if self.saved_gamma_semafor_configs:
                        # Ak existuje default, použi ho
                        default_config_name = data.get('default_gamma_semafor_config', None)
                        if default_config_name and default_config_name in self.saved_gamma_semafor_configs:
                            self.load_gamma_semafor_config_from_data(default_config_name, self.saved_gamma_semafor_configs[default_config_name])
                        else: # Inak načíta prvú
                            first_config_name = list(self.saved_gamma_semafor_configs.keys())[0]
                            self.load_gamma_semafor_config_from_data(first_config_name, self.saved_gamma_semafor_configs[first_config_name])
                    else:
                        # Ak nie sú žiadne uložené konfigurácie, nastav defaultné hodnoty
                        self.gs_strong_buy_threshold_var.set(str(self.gamma_semafor_thresholds["strong_buy"]))
                        self.gs_buy_threshold_var.set(str(self.gamma_semafor_thresholds["buy"]))
                        self.gs_neutral_threshold_var.set(str(self.gamma_semafor_thresholds["neutral"]))
                        self.gs_stop_threshold_var.set(str(self.gamma_semafor_thresholds["stop"]))
                        self.gs_semafor_config_name_var.set("")
                        self.gs_semafor_config_notes_var.set("")

                    self.gs_model_priority_var.set(data.get('gs_model_priority', False))

                    # Načítaj Swing Watcher nastavenia
                    self.monitor_profit_target_pct.set(data.get('monitor_profit_target_pct', "50.0"))
                    self.monitor_profit_warning_pct.set(data.get('monitor_profit_warning_pct', "30.0"))
                    self.monitor_stock_profit_target_usd.set(data.get('monitor_stock_profit_target_usd', "12.0"))
                    self.monitor_auto_close_var.set(data.get('monitor_auto_close_var', False))
                    self.monitor_auto_restart_var.set(data.get('monitor_auto_restart_var', False))
                    self.monitor_trailing_opt_pct.set(data.get('monitor_trailing_opt_pct', "5.0"))
                    self.monitor_trailing_stk_usd.set(data.get('monitor_trailing_stk_usd', "2.0"))

                    # Načítaj uložené vybrané symboly pre monitor
                    loaded_selected_symbols = data.get('monitor_selected_symbols', [])
                    self.monitor_selected_symbols = {}
                    for sym in loaded_selected_symbols:
                        self.monitor_selected_symbols[sym] = tk.BooleanVar(value=True)
                    
                    # Načítaj vlastné tickery pre Hunter
                    self.hunter_custom_tickers = data.get('hunter_custom_tickers', [])
                    self.hunter_pinned_symbols = data.get('hunter_pinned_symbols', [])
                    self.pmcc_symbols = data.get('pmcc_symbols', ["AAPL", "MSFT", "NVDA", "TSLA", "AMD", "META", "GOOGL", "AMZN"])
                    self.symbol_blocks = data.get('symbol_blocks', {})
            else:
                self.saved_strategies = {}
                # Nastav default hodnoty aj pre Semafor a model priority ak súbor neexistuje
                self.gs_strong_buy_threshold_var.set(str(self.gamma_semafor_thresholds["strong_buy"]))
                self.gs_buy_threshold_var.set(str(self.gamma_semafor_thresholds["buy"]))
                self.gs_neutral_threshold_var.set(str(self.gamma_semafor_thresholds["neutral"]))
                self.gs_stop_threshold_var.set(str(self.gamma_semafor_thresholds["stop"]))
                self.gs_model_priority_var.set(False)
                self.hunter_custom_tickers = []
                self.hunter_pinned_symbols = []
                self.pmcc_symbols = ["AAPL", "MSFT", "NVDA", "TSLA", "AMD", "META", "GOOGL", "AMZN"]
                self.symbol_blocks = {}

        except Exception as e:
            print(f"Chyba pri načítavaní nastavení: {e}")
            self.saved_strategies = {}
            # Reset na default v prípade chyby
            self.gs_strong_buy_threshold_var.set(str(self.gamma_semafor_thresholds["strong_buy"]))
            self.gs_buy_threshold_var.set(str(self.gamma_semafor_thresholds["buy"]))
            self.gs_neutral_threshold_var.set(str(self.gamma_semafor_thresholds["neutral"]))
            self.gs_stop_threshold_var.set(str(self.gamma_semafor_thresholds["stop"]))
            self.gs_model_priority_var.set(False)
            self.hunter_custom_tickers = []
            self.hunter_pinned_symbols = []
        finally:
            self._is_loading = False

    def save_settings_file(self):
        """Uloží archív nastavení do súboru"""
        if getattr(self, '_is_loading', False):
            return
        try:
            data = {
                'strategies': self.saved_strategies,
                'gamma_scalper_strategies': self.saved_gamma_scalper_strategies,
                'gamma_semafor_configs': self.saved_gamma_semafor_configs,
                'ticker_settings': self.ticker_settings, # Uložíme nastavenia tickerov
                'custom_pairs': self.custom_pairs, # Uložíme definície párov
                'default_gamma_semafor_config': self.gs_semafor_config_name_var.get(), # Uložíme poslednú použitú
                'gs_model_priority': self.gs_model_priority_var.get(),
                'monitor_profit_target_pct': self.monitor_profit_target_pct.get(),
                'monitor_profit_warning_pct': self.monitor_profit_warning_pct.get(),
                'monitor_stock_profit_target_usd': self.monitor_stock_profit_target_usd.get(),
                'monitor_auto_close_var': self.monitor_auto_close_var.get(),
                'monitor_auto_restart_var': self.monitor_auto_restart_var.get(),
                'monitor_trailing_opt_pct': self.monitor_trailing_opt_pct.get(),
                'monitor_trailing_stk_usd': self.monitor_trailing_stk_usd.get(),
                'monitor_selected_symbols': [sym for sym, var in self.monitor_selected_symbols.items() if var.get()],
                'hunter_custom_tickers': getattr(self, 'hunter_custom_tickers', []),
                'hunter_pinned_symbols': getattr(self, 'hunter_pinned_symbols', []),
                'pmcc_symbols': getattr(self, 'pmcc_symbols', []),
                'symbol_blocks': getattr(self, 'symbol_blocks', {})
            }
            with open(self.settings_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
        except Exception as e:
            messagebox.showerror("Chyba", f"Nepodarilo sa uložiť nastavenia:\n{e}")
    
    def load_gamma_semafor_config_from_data(self, name, data):
        """Načíta konkrétnu konfiguráciu Semafora zo slovníka do premenných GUI."""
        try:
            self.gs_strong_buy_threshold_var.set(str(data.get('strong_buy', self.gamma_semafor_thresholds["strong_buy"])))
            self.gs_buy_threshold_var.set(str(data.get('buy', self.gamma_semafor_thresholds["buy"])))
            self.gs_neutral_threshold_var.set(str(data.get('neutral', self.gamma_semafor_thresholds["neutral"])))
            self.gs_stop_threshold_var.set(str(data.get('stop', self.gamma_semafor_thresholds["stop"])))
            self.gs_semafor_config_name_var.set(name)
            self.gs_semafor_config_notes_var.set(data.get('notes', ''))

            # Aktualizuj interný slovník prahových hodnôt
            self.gamma_semafor_thresholds["strong_buy"] = float(self.gs_strong_buy_threshold_var.get())
            self.gamma_semafor_thresholds["buy"] = float(self.gs_buy_threshold_var.get())
            self.gamma_semafor_thresholds["neutral"] = float(self.gs_neutral_threshold_var.get())
            self.gamma_semafor_thresholds["stop"] = float(self.gs_stop_threshold_var.get())
        except Exception as e:
            messagebox.showerror("Chyba", f"Nepodarilo sa načítať konfiguráciu Semafora '{name}':\n{e}")

    def save_gamma_semafor_config(self):
        """Uloží aktuálne nastavenia Gamma Semafora ako novú konfiguráciu."""
        name = self.gs_semafor_config_name_var.get().strip()
        if not name:
            name = messagebox.askstring("Názov konfigurácie Semafora", "Zadajte názov pre túto konfiguráciu:")
            if not name:
                return
            self.gs_semafor_config_name_var.set(name) # Aktualizujeme, ak bolo zadané cez dialog

        try:
            config = {
                'symbol': self.symbol_var.get(), # Uložíme aj pre aký symbol to je
                'strong_buy': float(self.gs_strong_buy_threshold_var.get()),
                'buy': float(self.gs_buy_threshold_var.get()),
                'neutral': float(self.gs_neutral_threshold_var.get()),
                'stop': float(self.gs_stop_threshold_var.get()),
                'notes': self.gs_semafor_config_notes_var.get(),
                'saved_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            }
            
            self.saved_gamma_semafor_configs[name] = config
            self.save_settings_file()
            if hasattr(self, 'refresh_gs_semafor_tree'):
                self.refresh_gs_semafor_tree()
            messagebox.showinfo("Úspech", f"Konfigurácia Semafora '{name}' bola uložená.")
        except ValueError:
            messagebox.showerror("Chyba", "Neplatné hodnoty prahov. Zadajte prosím čísla.")
        except Exception as e:
            messagebox.showerror("Chyba", f"Nepodarilo sa uložiť konfiguráciu Semafora:\n{e}")

    def load_gamma_semafor_config(self, config_name_var, auto=False):
        """Načíta vybranú konfiguráciu Gamma Semafora."""
        name = config_name_var.get().strip()
        if not name:
            if not auto:
                messagebox.showwarning("Chyba", "Vyberte konfiguráciu Semafora zo zoznamu.")
            return

        if name not in self.saved_gamma_semafor_configs:
            if not auto:
                messagebox.showerror("Chyba", f"Konfigurácia Semafora '{name}' neexistuje.")
            return

        try:
            config = self.saved_gamma_semafor_configs[name]
            self.load_gamma_semafor_config_from_data(name, config) # Použijeme pomocnú metódu
            self.save_settings_file() # Uložíme default config pre ďalší štart

            if not auto:
                saved_at = config.get('saved_at', 'Neznámy dátum')
                messagebox.showinfo("Načítané", f"Konfigurácia Semafora '{name}' bola načítaná.\n\nUložená: {saved_at}")
        except Exception as e:
            messagebox.showerror("Chyba", f"Nepodarilo sa načítať konfiguráciu Semafora:\n{e}")

    def delete_gamma_semafor_config(self, config_name_var):
        """Vymaže vybranú konfiguráciu Gamma Semafora."""
        name = config_name_var.get().strip()
        if not name:
            messagebox.showwarning("Chyba", "Vyberte konfiguráciu na vymazanie.")
            return

        if name not in self.saved_gamma_semafor_configs:
            messagebox.showerror("Chyba", f"Konfigurácia Semafora '{name}' neexistuje.")
            return

        if messagebox.askyesno("Potvrdiť vymazanie", f"Naozaj chcete vymazať konfiguráciu Semafora '{name}'?"):
            try:
                del self.saved_gamma_semafor_configs[name]
                config_name_var.set("") # Vyčisti vybranú konfiguráciu
                self.save_settings_file()
                if hasattr(self, 'refresh_gs_semafor_tree'):
                    self.refresh_gs_semafor_tree()
                messagebox.showinfo("Úspech", f"Konfigurácia Semafora '{name}' bola úspešne vymazaná.")
            except Exception as e:
                messagebox.showerror("Chyba", f"Nepodarilo sa vymazať konfiguráciu Semafora:\n{e}")
    
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

    def save_gamma_scalper_strategy(self, strategy_name_var, strategy_combo=None):
        """Uloží aktuálne nastavenia Gamma Scalper"""
        name = strategy_name_var.get().strip()
        if not name:
            name = messagebox.askstring("Názov stratégie Gamma Scalper", "Zadajte názov pre túto stratégiu:")
            if not name:
                return
            name = name.strip()
        
        # Získame poznámku, ak bola nastavená v GUI (current_gs_note)
        note = getattr(self, 'current_gs_note', self.gs_strategy_notes_var.get())
        
        try:
            strategy = {
                'symbol': self.symbol_var.get(),
                'expiry': self.gs_expiry_combo.get() if hasattr(self, 'gs_expiry_combo') else self.calc_short_expiry_var.get(),
                'target_delta': self.gs_target_delta_var.get(),
                'iv': self.iv_var.get(),
                'rate': self.rate_var.get(),
                'roll_trigger': self.roll_trigger_var.get(),
                'gs_strong_buy_threshold': self.gs_strong_buy_threshold_var.get(),
                'gs_buy_threshold': self.gs_buy_threshold_var.get(),
                'gs_neutral_threshold': self.gs_neutral_threshold_var.get(),
                'gs_stop_threshold': self.gs_stop_threshold_var.get(),
                'gs_model_priority': self.gs_model_priority_var.get(),
                'gs_drift_tolerance': self.gs_drift_tol.get(),
                'notes': note, # Uložíme poznámku
                'analysis_text': self.gs_result_text.get(1.0, tk.END) if hasattr(self, 'gs_result_text') else "",
                'saved_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            }
            
            self.saved_gamma_scalper_strategies[name] = strategy
            strategy_name_var.set(name)
            
            if strategy_combo:
                strategy_names = sorted(self.saved_gamma_scalper_strategies.keys())
                strategy_combo['values'] = strategy_names
            
            self.save_settings_file()
            # Vyčistíme dočasnú poznámku
            self.current_gs_note = ""
            # Odstránené duplicitné messagebox.showinfo, rieši si to volajúca funkcia v GUI
            
        except Exception as e:
            messagebox.showerror("Chyba", f"Nepodarilo sa uložiť stratégiu Gamma Scalper:\n{e}")

    def load_gamma_scalper_strategy(self, strategy_name_var, auto=False):
        """Načíta vybranú stratégiu Gamma Scalper"""
        name = strategy_name_var.get().strip()
        if not name:
            messagebox.showwarning("Chyba", "Vyberte stratégiu Gamma Scalper zo zoznamu")
            return
        
        if name not in self.saved_gamma_scalper_strategies:
            messagebox.showerror("Chyba", f"Stratégia Gamma Scalper '{name}' neexistuje")
            return
        
        try:
            strategy = self.saved_gamma_scalper_strategies[name]
            old_symbol = self.symbol_var.get()
            new_symbol = strategy.get('symbol', 'SPY')
            new_expiry = strategy.get('expiry', '')
            
            # 1. Nastav základné parametre
            self.symbol_var.set(new_symbol)
            self.gs_target_delta_var.set(strategy.get('target_delta', '0.30'))
            self.iv_var.set(strategy.get('iv', '0.18'))
            self.rate_var.set(strategy.get('rate', '0.05'))
            self.roll_trigger_var.set(strategy.get('roll_trigger', '-0.30'))
            self.gs_strategy_notes_var.set(strategy.get('notes', ''))
            
            # 2. Nastav prahy Semafora
            self.gs_strong_buy_threshold_var.set(str(strategy.get('gs_strong_buy_threshold', self.gamma_semafor_thresholds["strong_buy"])))
            self.gs_buy_threshold_var.set(str(strategy.get('gs_buy_threshold', self.gamma_semafor_thresholds["buy"])))
            self.gs_neutral_threshold_var.set(str(strategy.get('gs_neutral_threshold', self.gamma_semafor_thresholds["neutral"])))
            self.gs_stop_threshold_var.set(str(strategy.get('gs_stop_threshold', self.gamma_semafor_thresholds["stop"])))
            
            self.gamma_semafor_thresholds["strong_buy"] = float(self.gs_strong_buy_threshold_var.get())
            self.gamma_semafor_thresholds["buy"] = float(self.gs_buy_threshold_var.get())
            self.gamma_semafor_thresholds["neutral"] = float(self.gs_neutral_threshold_var.get())
            self.gamma_semafor_thresholds["stop"] = float(self.gs_stop_threshold_var.get())

            # 3. Model priority a monitoring
            self.gs_model_priority_var.set(strategy.get('gs_model_priority', False))
            if 'gs_drift_tolerance' in strategy:
                self.gs_drift_tol.set(strategy.get('gs_drift_tolerance', '0.20'))

            # Načítaj text analýzy ak existuje
            if 'analysis_text' in strategy and hasattr(self, 'gs_result_text'):
                saved_text = strategy.get('analysis_text', '')
                if saved_text.strip():
                    self.gs_result_text.config(state='normal') # Povoliť zápis
                    self.gs_result_text.delete(1.0, tk.END)
                    self.gs_result_text.insert(tk.END, saved_text)
                    self.gs_result_text.config(state='disabled') # Znova uzamknúť
                    self.gs_result_text.see(tk.END)

            # 4. Expirácia - kritická časť
            # Nastavíme premennú okamžite
            if new_expiry:
                self.calc_short_expiry_var.set(new_expiry)
            
            # Ak sa zmenil symbol, musíme načítať expirácie pre nový symbol
            if old_symbol != new_symbol:
                # Spustíme load_expiries (asynchrónne)
                self.load_expiries()
                # Počkáme chvíľu a skúsime znova nastaviť expiráciu do comboboxu (ak by ju load_expiries prepísal)
                self.root.after(1500, lambda: self.calc_short_expiry_var.set(new_expiry))
            
            if hasattr(self, 'gs_expiry_combo'):
                self.gs_expiry_combo.set(new_expiry)
            
            self.save_settings_file()
            
            if not auto:
                saved_at = strategy.get('saved_at', 'Neznámy dátum')
                messagebox.showinfo("Načítané", f"Stratégia Gamma Scalper '{name}' bola načítaná.\n\nSymbol: {new_symbol}\nExpirácia: {new_expiry}\nUložená: {saved_at}")
                
        except ValueError:
            messagebox.showerror("Chyba", "Neplatné hodnoty v uloženej stratégii. Skontrolujte archív.")
        except Exception as e:
            messagebox.showerror("Chyba", f"Nepodarilo sa načítať stratégiu Gamma Scalper:\n{e}")

    def delete_gamma_scalper_strategy(self, strategy_name_var, strategy_combo=None):
        """Vymaže vybranú stratégiu Gamma Scalper"""
        name = strategy_name_var.get().strip()
        if not name:
            messagebox.showwarning("Chyba", "Vyberte stratégiu na vymazanie")
            return
        
        if name not in self.saved_gamma_scalper_strategies:
            messagebox.showerror("Chyba", f"Stratégia Gamma Scalper '{name}' neexistuje")
            return
        
        if messagebox.askyesno("Potvrdiť vymazanie", f"Naozaj chcete vymazať stratégiu '{name}'?"):
            try:
                del self.saved_gamma_scalper_strategies[name]
                strategy_name_var.set("") # Vyčisti vybranú stratégiu
                self.save_settings_file()
                
                if strategy_combo:
                    strategy_names = sorted(self.saved_gamma_scalper_strategies.keys())
                    strategy_combo['values'] = strategy_names
                    if strategy_names:
                        strategy_combo.set(strategy_names[0]) # Nastav prvú stratégiu ako predvolenú
                    else:
                        strategy_combo.set("") # Ak nie sú žiadne stratégie, vyčisti combo
                
                messagebox.showinfo("Úspech", f"Stratégia '{name}' bola úspešne vymazaná.")
                
            except Exception as e:
                messagebox.showerror("Chyba", f"Nepodarilo sa vymazať stratégiu:\n{e}")

    def stop_gamma_scalper_search(self):
        """Ukončí bežiaci proces vyhľadávania Gamma Scalper, ak existuje."""
        if self.gs_search_process and self.gs_search_process.poll() is None:
            try:
                self.gs_search_process.terminate()  # Ukončí proces gracefully
                self.gs_search_process.wait(timeout=5) # Počká 5 sekúnd na ukončenie
                messagebox.showinfo("Vyhľadávanie ukončené", "Vyhľadávanie Strangle bolo úspešne ukončené.")
            except subprocess.TimeoutExpired:
                self.gs_search_process.kill() # Ak sa neukončí, zabi ho
                messagebox.showwarning("Vyhľadávanie ukončené (forcene)", "Vyhľadávanie Strangle bolo nútene ukončené.")
            except Exception as e:
                messagebox.showerror("Chyba", f"Chyba pri ukončovaní vyhľadávania: {e}")
            finally:
                self.gs_search_process = None # Vymaž referenciu na proces
        elif self.gs_search_process:
            messagebox.showinfo("Vyhľadávanie už skončilo", "Vyhľadávanie už bolo ukončené alebo skončilo samo.")
        else:
            messagebox.showinfo("Žiadne vyhľadávanie", "Momentálne neprebieha žiadne vyhľadávanie Strangle.")

def open_symbol_block_manager(state, on_close_callback=None):
    """Otvorí dialóg na správu blokov symbolov"""
    win = tk.Toplevel(state.root)
    win.title("📁 Správca blokov symbolov")
    win.geometry("500x450")
    win.transient(state.root)
    win.grab_set()

    main_f = ttk.Frame(win, padding=15)
    main_f.pack(fill='both', expand=True)

    ttk.Label(main_f, text="Vaše bloky symbolov:", font=('Arial', 10, 'bold')).pack(anchor='w')

    list_f = ttk.Frame(main_f)
    list_f.pack(fill='both', expand=True, pady=5)

    block_list = tk.Listbox(list_f, font=('Arial', 10), height=8)
    block_list.pack(side='left', fill='both', expand=True)
    
    sb = ttk.Scrollbar(list_f, command=block_list.yview)
    sb.pack(side='right', fill='y')
    block_list.config(yscrollcommand=sb.set)

    def refresh_list():
        block_list.delete(0, tk.END)
        for name in sorted(state.symbol_blocks.keys()):
            block_list.insert(tk.END, name)

    refresh_list()

    # Detaily vybratého bloku
    detail_f = ttk.LabelFrame(main_f, text="Detaily bloku", padding=10)
    detail_f.pack(fill='x', pady=5)

    ttk.Label(detail_f, text="Názov bloku:").pack(anchor='w')
    name_ent = ttk.Entry(detail_f)
    name_ent.pack(fill='x', pady=(0, 5))

    ttk.Label(detail_f, text="Symboly (oddelené čiarkou):").pack(anchor='w')
    sym_ent = ttk.Entry(detail_f)
    sym_ent.pack(fill='x')

    def on_select(event):
        sel = block_list.curselection()
        if not sel: return
        name = block_list.get(sel[0])
        name_ent.delete(0, tk.END)
        name_ent.insert(0, name)
        syms = state.symbol_blocks.get(name, [])
        sym_ent.delete(0, tk.END)
        sym_ent.insert(0, ", ".join(syms))

    block_list.bind("<<ListboxSelect>>", on_select)

    btn_f = ttk.Frame(main_f)
    btn_f.pack(fill='x', pady=10)

    def save_block():
        name = name_ent.get().strip()
        raw_syms = sym_ent.get().strip().upper()
        if not name or not raw_syms:
            messagebox.showwarning("Chyba", "Zadajte názov bloku aj symboly.")
            return
        
        symbols = [s.strip() for s in raw_syms.replace(',', ' ').split() if s.strip()]
        state.symbol_blocks[name] = symbols
        state.save_settings_file()
        refresh_list()
        messagebox.showinfo("Úspech", f"Blok '{name}' bol uložený.")

    def delete_block():
        sel = block_list.curselection()
        if not sel: return
        name = block_list.get(sel[0])
        if messagebox.askyesno("Vymazať", f"Naozaj chcete vymazať blok '{name}'?"):
            del state.symbol_blocks[name]
            state.save_settings_file()
            name_ent.delete(0, tk.END)
            sym_ent.delete(0, tk.END)
            refresh_list()

    ttk.Button(btn_f, text="💾 Uložiť / Pridať", command=save_block).pack(side='left', padx=5)
    ttk.Button(btn_f, text="🗑️ Vymazať", command=delete_block).pack(side='left', padx=5)
    
    def on_win_close():
        if on_close_callback: on_close_callback()
        win.destroy()

    win.protocol("WM_DELETE_WINDOW", on_win_close)
    ttk.Button(main_f, text="Zatvoriť", command=on_win_close).pack(pady=5)

