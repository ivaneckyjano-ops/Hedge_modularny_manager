#!/usr/bin/env python3
"""
Záložka: Balancer
Balancer - vybalansovanie pozície (PL1 + PL2 = 0)
"""
import tkinter as tk
from tkinter import ttk, messagebox, scrolledtext
import subprocess
import threading
import os
import math
from datetime import datetime, date

try:
    from scipy.stats import norm
    from scipy.optimize import brentq
    SCIPY_AVAILABLE = True
except ImportError:
    SCIPY_AVAILABLE = False

try:
    import matplotlib
    import matplotlib.pyplot as plt
    from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
    MATPLOTLIB_AVAILABLE = True
except Exception:
    MATPLOTLIB_AVAILABLE = False

from modularny.utils import (
    black_scholes_put_price, black_scholes_call_price,
    black_scholes_delta_put, black_scholes_delta_call,
    get_time_to_expiry_years
)


def calculate_pl_long(option_type, strike, premium_paid, underlying_price, current_option_price=None):
    """Vypočíta P/L pre LONG opciu (kupovaná)
    
    Ak je zadaná current_option_price, použije ju (zahŕňa intrinsic + časovú hodnotu).
    Inak použije len intrinsic hodnotu (pre expirované opcie).
    """
    if current_option_price is not None:
        # Použij aktuálnu cenu opcie (zahŕňa intrinsic + časovú hodnotu)
        return (current_option_price - premium_paid) * 100
    else:
        # Použij len intrinsic hodnotu (pre expirované opcie)
        if option_type == 'CALL':
            intrinsic = max(0, underlying_price - strike)
        else:  # PUT
            intrinsic = max(0, strike - underlying_price)
        return (intrinsic - premium_paid) * 100


def calculate_pl_short(option_type, strike, premium_received, underlying_price, current_option_price=None):
    """Vypočíta P/L pre SHORT opciu (predávaná)
    
    Ak je zadaná current_option_price, použije ju (zahŕňa intrinsic + časovú hodnotu).
    Inak použije len intrinsic hodnotu (pre expirované opcie).
    """
    if current_option_price is not None:
        # Použij aktuálnu cenu opcie (zahŕňa intrinsic + časovú hodnotu)
        return (premium_received - current_option_price) * 100
    else:
        # Použij len intrinsic hodnotu (pre expirované opcie)
        if option_type == 'CALL':
            intrinsic = max(0, underlying_price - strike)
        else:  # PUT
            intrinsic = max(0, strike - underlying_price)
        return (premium_received - intrinsic) * 100


def find_balanced_strike(long_type, long_strike, long_premium, opp_type, expiry, iv, r, underlying):
    """Nájde strike pre druhú LONG opciu v strangle pozícii
    
    Strangle: LONG PUT + LONG CALL (obe OTM)
    Hľadáme strike pre druhú opciu tak, aby pozícia bola vyvážená:
    - Rovnaká pravdepodobnosť zisku v oboch smeroch
    - Alebo rovnaká delta (symetrická pozícia)
    - Alebo rovnaký zisk pri pohybe o X hore/dole
    """
    if not SCIPY_AVAILABLE:
        print("ERROR: scipy nie je dostupné", flush=True)
        return None
    
    T = get_time_to_expiry_years(expiry)
    
    print(f"DEBUG find_balanced_strike: long_type={long_type}, long_strike={long_strike}, long_premium={long_premium}", flush=True)
    print(f"DEBUG: opp_type={opp_type}, underlying={underlying}, T={T:.4f}, iv={iv}, r={r}", flush=True)
    
    # Stratégia: Nájdi strike kde premium je podobné ako LONG premium
    # Pre vyvážený strangle by mali mať obe opcie podobné premium
    
    print(f"DEBUG: Hľadám strike pre {opp_type} s premium ~${long_premium:.2f}", flush=True)
    
    # Rozsah pre hľadanie
    if opp_type == 'CALL':
        # CALL nad underlying
        search_range = range(int(underlying), int(underlying * 1.3), 1)
    else:
        # PUT pod underlying
        search_range = range(int(underlying * 0.7), int(underlying), 1)
    
    best_strike = None
    best_diff = float('inf')
    best_premium = 0
    
    for test_strike in search_range:
        try:
            if opp_type == 'CALL':
                test_premium = black_scholes_call_price(underlying, test_strike, T, r, iv)
            else:
                test_premium = black_scholes_put_price(underlying, test_strike, T, r, iv)
            
            # Hľadáme strike kde premium je najbližšie k long_premium
            diff = abs(test_premium - long_premium)
            if diff < best_diff:
                best_diff = diff
                best_strike = test_strike
                best_premium = test_premium
                
        except Exception:
            continue
    
    if not best_strike:
        # Fallback: symetrický strike
        distance = abs(long_strike - underlying)
        if opp_type == 'CALL':
            best_strike = underlying + distance
        else:
            best_strike = underlying - distance
        
        try:
            if opp_type == 'CALL':
                best_premium = black_scholes_call_price(underlying, best_strike, T, r, iv)
            else:
                best_premium = black_scholes_put_price(underlying, best_strike, T, r, iv)
        except Exception:
            best_premium = long_premium  # Fallback
    
    # Zaokrúhli strike na valídné hodnoty
    # Opcie majú strike v celých číslach alebo v 0.5 krokoch
    # Pre SPY: celé čísla
    best_strike = round(best_strike)  # Zaokrúhli na celé číslo
    
    print(f"DEBUG: Najlepší strike (zaokrúhlený): {best_strike}, premium: ${best_premium:.2f} (diff: ${best_diff:.2f})", flush=True)
    return best_strike


def bal_load_from_calculator(state):
    """Načíta LONG leg z Kalkulátora - používa AKTUÁLNE hodnoty"""
    print("=" * 60, flush=True)
    print("DEBUG bal_load_from_calculator: START", flush=True)
    try:
        # Načítaj AKTUÁLNE hodnoty z kalkulátora (nie z last_calc_result)
        long_strike = state.calc_long_strike_var.get()
        long_expiry = state.calc_long_expiry_var.get()
        long_premium = state.calc_long_premium_var.get()
        underlying = state.calc_underlying_price_var.get()
        option_type = state.option_type_var.get()
        
        print(f"DEBUG: Načítané hodnoty z kalkulátora:", flush=True)
        print(f"  Long Strike: '{long_strike}'", flush=True)
        print(f"  Long Expiry: '{long_expiry}'", flush=True)
        print(f"  Long Premium: '{long_premium}'", flush=True)
        print(f"  Underlying: '{underlying}'", flush=True)
        print(f"  Option Type: '{option_type}'", flush=True)
        
        # Validácia
        if not long_strike or not long_expiry or not long_premium:
            error_msg = f"Vyplňte všetky LONG polia v Kalkulátore:\n"
            error_msg += f"- Long Strike: {long_strike or '(prázdne)'}\n"
            error_msg += f"- Long Expiry: {long_expiry or '(prázdne)'}\n"
            error_msg += f"- Long Premium: {long_premium or '(prázdne)'}"
            print(f"DEBUG: CHYBA - chýbajúce polia:\n{error_msg}", flush=True)
            messagebox.showwarning("Chyba", error_msg)
            return
        
        if not underlying:
            print("DEBUG: CHYBA - chýba underlying", flush=True)
            messagebox.showwarning("Chyba", "Najprv stiahnite cenu podkladu v Kalkulátore")
            return
        
        # Konvertuj na čísla pre validáciu
        try:
            long_strike_float = float(long_strike)
            long_premium_float = float(long_premium)
            underlying_float = float(underlying)
            print(f"DEBUG: Konverzia OK - strike={long_strike_float}, premium={long_premium_float}, underlying={underlying_float}", flush=True)
        except ValueError as e:
            print(f"DEBUG: CHYBA pri konverzii: {e}", flush=True)
            messagebox.showerror("Chyba", f"Neplatné číselné hodnoty: {e}")
            return
        
        # Nastav LONG hodnoty do Balancera
        state.bal_long_strike_var.set(long_strike)
        state.bal_long_expiry_var.set(long_expiry)
        state.bal_long_premium_var.set(long_premium)
        state.bal_underlying_var.set(underlying)
        state.bal_long_type_var.set(option_type)
        
        # Nastav opačný typ
        opp_type = 'CALL' if option_type == 'PUT' else 'PUT'
        state.bal_opposite_type_var.set(opp_type)
        
        # Sync IV
        state.bal_iv_var.set(state.iv_var.get())
        
        if hasattr(state, 'bal_status_label'):
            state.bal_status_label.config(text=f"✓ Načítané: {option_type} {long_strike} @ ${long_premium}")
        
        print(f"DEBUG: Hodnoty nastavené do Balancera", flush=True)
        print(f"  bal_long_strike_var: {state.bal_long_strike_var.get()}", flush=True)
        print(f"  bal_long_premium_var: {state.bal_long_premium_var.get()}", flush=True)
        print(f"  bal_underlying_var: {state.bal_underlying_var.get()}", flush=True)
        print(f"  bal_long_type_var: {state.bal_long_type_var.get()}", flush=True)
        print(f"  bal_opposite_type_var: {state.bal_opposite_type_var.get()}", flush=True)
        
        # Automaticky spusti analýzu
        print("DEBUG: Spúšťam analyze_balancer...", flush=True)
        analyze_balancer(state)
        print("DEBUG bal_load_from_calculator: END", flush=True)
        print("=" * 60, flush=True)
        
    except Exception as e:
        print(f"DEBUG: EXCEPTION v bal_load_from_calculator: {e}", flush=True)
        import traceback
        traceback.print_exc()
        messagebox.showerror("Chyba", f"Nepodarilo sa načítať z Kalkulátora:\n{e}")


def fetch_bal_underlying(state):
    """Stiahne cenu podkladu"""
    def run():
        try:
            script_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'scripts', 'tws_fetch_price.py')
            result = subprocess.run(['python3', script_path, str(state.port_var.get()), state.symbol_var.get()],
                                    capture_output=True, text=True, timeout=20,
                                    cwd='/home/narbon/Aplikácie/tws-webapp')
            out = result.stdout.strip().split('\n')[0] if result.stdout else ''
            if result.returncode == 0 and out and not out.startswith("ERROR:"):
                state.root.after(0, lambda v=out: state.bal_underlying_var.set(v))
                if hasattr(state, 'bal_status_label'):
                    state.root.after(0, lambda: state.bal_status_label.config(text=f"✓ Podklad: ${out}"))
            else:
                if hasattr(state, 'bal_status_label'):
                    state.root.after(0, lambda: state.bal_status_label.config(text="❌ Chyba pri sťahovaní podkladu"))
        except Exception as e:
            if hasattr(state, 'bal_status_label'):
                state.root.after(0, lambda: state.bal_status_label.config(text=f"❌ {str(e)[:30]}"))
    if hasattr(state, 'bal_status_label'):
        state.bal_status_label.config(text="Sťahujem cenu podkladu...")
    threading.Thread(target=run, daemon=True).start()


def analyze_balancer(state):
    """Analyzuje LONG a nájde vybalansovanú opačnú opciu"""
    print("=" * 60, flush=True)
    print("DEBUG analyze_balancer: VSTUP DO FUNKCIE", flush=True)
    print(f"DEBUG: SCIPY_AVAILABLE={SCIPY_AVAILABLE}", flush=True)
    try:
        if not SCIPY_AVAILABLE:
            print("DEBUG: SCIPY nie je dostupné, ukončujem", flush=True)
            messagebox.showerror("Chyba", "Na analýzu je potrebné scipy")
            return
        
        long_type = state.bal_long_type_var.get()
        long_str = state.bal_long_strike_var.get()
        long_prem_str = state.bal_long_premium_var.get()
        expiry = state.bal_long_expiry_var.get()
        underlying_str = state.bal_underlying_var.get()
        iv_str = state.bal_iv_var.get()
        r_str = state.rate_var.get()
        
        if not long_str or not long_prem_str or not expiry or not underlying_str:
            messagebox.showwarning("Chyba", "Vyplňte všetky polia (LONG strike, premium, expiry, underlying)")
            return
        
        try:
            long_strike = float(long_str)
            long_premium = float(long_prem_str)
            underlying = float(underlying_str)
            iv = float(iv_str or 0.20)
            r = float(r_str or 0.0)
        except ValueError as e:
            messagebox.showerror("Chyba", f"Neplatné číselné hodnoty: {e}")
            return
        
        if underlying <= 0:
            messagebox.showwarning("Chyba", "Cena podkladu musí byť > 0")
            return
        
        # Urči opačný typ (pre strangle: PUT + CALL)
        opp_type = 'CALL' if long_type == 'PUT' else 'PUT'
        state.bal_opposite_type_var.set(opp_type)  # Len "CALL" alebo "PUT"
        
        if hasattr(state, 'bal_status_label'):
            state.bal_status_label.config(text="Vypočítavam vybalansovaný strike...")
        
        print(f"DEBUG analyze_balancer: long_type={long_type}, long_strike={long_strike}, long_premium={long_premium}", flush=True)
        print(f"DEBUG: opp_type={opp_type}, expiry={expiry}, underlying={underlying}, iv={iv}, r={r}", flush=True)
        
        # Nájdi vybalansovaný strike
        balanced_strike = find_balanced_strike(
            long_type, long_strike, long_premium,
            opp_type, expiry, iv, r, underlying
        )
        
        print(f"DEBUG: balanced_strike={balanced_strike}", flush=True)
        
        if not balanced_strike or balanced_strike <= 0 or math.isnan(balanced_strike):
            error_msg = "Nepodarilo sa nájsť vybalansovaný strike.\n\n"
            error_msg += f"Skontrolujte:\n"
            error_msg += f"- LONG strike: ${long_strike:.2f}\n"
            error_msg += f"- LONG premium: ${long_premium:.2f}\n"
            error_msg += f"- Underlying: ${underlying:.2f}\n"
            error_msg += f"- IV: {iv:.2%}\n"
            error_msg += f"- Expiry: {expiry}\n"
            if hasattr(state, 'bal_results_text'):
                state.bal_results_text.delete(1.0, tk.END)
                state.bal_results_text.insert(tk.END, error_msg)
            if hasattr(state, 'bal_status_label'):
                state.bal_status_label.config(text="❌ Chyba pri výpočte")
            messagebox.showwarning("Chyba", error_msg)
            return
        
        # Vypočítaj Time to Expiry (potrebné pre Black-Scholes)
        T = get_time_to_expiry_years(expiry)
        print(f"DEBUG: Time to expiry T={T:.4f} rokov ({T*365:.1f} dní)", flush=True)
        
        # Stiahni REÁLNE premium z TWS pre vypočítaný strike
        print(f"DEBUG: Sťahujem reálne premium pre {opp_type} {balanced_strike} z TWS...", flush=True)
        
        opp_premium = None
        try:
            script_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'scripts', 'tws_fetch_option.py')
            right = 'C' if opp_type == 'CALL' else 'P'
            result = subprocess.run(
                ['python3', script_path, str(state.port_var.get()), state.symbol_var.get(), expiry, str(balanced_strike), right],
                capture_output=True, text=True, timeout=15,
                cwd='/home/narbon/Aplikácie/tws-webapp'
            )
            
            output = result.stdout.strip()
            if result.returncode == 0 and output and not output.startswith("ERROR:"):
                opp_premium = float(output)
                print(f"DEBUG: Reálne premium z TWS: ${opp_premium:.2f}", flush=True)
            else:
                print(f"DEBUG: Nepodarilo sa stiahnuť z TWS: {output}", flush=True)
        except Exception as e:
            print(f"DEBUG: Chyba pri sťahovaní z TWS: {e}", flush=True)
        
        # Ak sa nepodarilo stiahnuť z TWS, použijeme Black-Scholes alebo odhad
        if opp_premium is None or opp_premium <= 0:
            if opp_type == 'CALL':
                opp_premium = black_scholes_call_price(underlying, balanced_strike, T, r, iv)
            else:
                opp_premium = black_scholes_put_price(underlying, balanced_strike, T, r, iv)
            
            if opp_premium < 0.05:
                opp_premium = long_premium * 0.9
                print(f"DEBUG: Používam odhadovanú hodnotu: ${opp_premium:.2f} (90% z long premium)", flush=True)
            else:
                print(f"DEBUG: Používam Black-Scholes: ${opp_premium:.2f}", flush=True)
        
        # P/L výpočet pre LONG opcie:
        # P/L = (aktuálna_cena - zaplatené_premium) × 100
        
        # DÔLEŽITÉ: Premium z kalkulátora sú AKTUÁLNE ceny
        # Nie historické ceny pri vstupe!
        # Takže long_premium je vlastne aktuálna hodnota prvej opcie
        
        # Pre prvú LONG opciu: používame zadané premium AKO aktuálnu hodnotu
        long_current_price = long_premium
        
        # P/L = 0 pri aktuálnej cene (lebo premium je aktuálna cena)
        # Ale to nie je správne pre graf...
        
        # Lepšie: vypočítame teoretickú hodnotu pomocou Black-Scholes
        if long_type == 'CALL':
            long_bs_price = black_scholes_call_price(underlying, long_strike, T, r, iv)
        else:
            long_bs_price = black_scholes_put_price(underlying, long_strike, T, r, iv)
        
        # Ak BS vracia 0 ale máme reálne premium, použijeme reálne premium
        if long_bs_price < 0.01 and long_premium > 0.01:
            long_current_price = long_premium
        else:
            long_current_price = long_bs_price
        
        # POZNÁMKA: Ak je long_premium = aktuálna cena pri vstupe,
        # potom pri rovnakej cene underlying by P/L mal byť 0
        # Ale v grafe chceme vidieť, ako sa mení pri rôznych cenách
        
        pl_long = (long_current_price - long_premium) * 100
        
        print(f"DEBUG P/L long: premium_paid={long_premium:.2f}, current_value={long_current_price:.2f}, pl={pl_long:.2f}", flush=True)
        
        # Pre druhú LONG opciu
        opp_current_price = opp_premium
        if opp_current_price < 0.01:
            if opp_type == 'CALL':
                opp_current_price = max(0, underlying - balanced_strike)
            else:
                opp_current_price = max(0, balanced_strike - underlying)
        
        pl_opp = (opp_current_price - opp_premium) * 100
        total_pl = pl_long + pl_opp
        
        print(f"DEBUG P/L: long_current={long_current_price:.2f}, pl_long={pl_long:.2f}", flush=True)
        print(f"DEBUG P/L: opp_current={opp_current_price:.2f}, pl_opp={pl_opp:.2f}, total={total_pl:.2f}", flush=True)
        
        # Celkový náklad strangle
        total_cost = long_premium + opp_premium
        
        # Break-even body
        if long_type == 'PUT':
            # PUT strike - total_cost a CALL strike + total_cost
            be_down = long_strike - total_cost
            be_up = balanced_strike + total_cost
        else:
            # CALL strike + total_cost a PUT strike - total_cost
            be_up = long_strike + total_cost
            be_down = balanced_strike - total_cost
        
        # Zobraz výsledky
        result_text = f"""
╔══════════════════════════════════════════════════════════════════╗
║                    📊 BALANCER ANALÝZA                            ║
╠══════════════════════════════════════════════════════════════════╣
║  Riadok 1: LONG {long_type:4} (z Kalkulátora)                            ║
║  ──────────────────────────────────────────────────────────────── ║
║  Strike:     ${long_strike:>8.2f}                                              ║
║  Premium:    ${long_premium:>8.2f} (zaplatené)                              ║
║  Aktuálna cena: ${long_current_price:>8.2f}                                        ║
║  Expiry:     {expiry:>10}                                              ║
║  P/L @ ${underlying:.2f}:  ${pl_long:>8.2f}  (= ({long_current_price:.2f} - {long_premium:.2f}) × 100)    ║
╠══════════════════════════════════════════════════════════════════╣
║  Riadok 2: LONG {opp_type:4} (vypočítaný pre vyvážený strangle)        ║
║  ──────────────────────────────────────────────────────────────── ║
║  Strike:     ${balanced_strike:>8.2f} (symetricky)                          ║
║  Premium:    ${opp_premium:>8.2f} (odhadovaná)                              ║
║  Aktuálna cena: ${opp_current_price:>8.2f}                                        ║
║  Expiry:     {expiry:>10} (rovnaká)                                    ║
║  P/L @ ${underlying:.2f}:  ${pl_opp:>8.2f}  (= ({opp_current_price:.2f} - {opp_premium:.2f}) × 100)    ║
╠══════════════════════════════════════════════════════════════════╣
║  STRANGLE POZÍCIA:                                               ║
║  ──────────────────────────────────────────────────────────────── ║
║  Celkový náklad:     ${total_cost:>8.2f} (obe LONG opcie)                   ║
║  P/L @ ${underlying:.2f}:     ${total_pl:>8.2f} (pri aktuálnej cene)                ║
║  Break-even hore:    ${be_up:>8.2f}                                         ║
║  Break-even dole:    ${be_down:>8.2f}                                         ║
║  Underlying: ${underlying:>8.2f} | IV: {iv:>6.2%} | DTE: {int(T*365):>3} dní        ║
╚══════════════════════════════════════════════════════════════════╝
"""
        
        if hasattr(state, 'bal_results_text'):
            state.bal_results_text.delete(1.0, tk.END)
            state.bal_results_text.insert(tk.END, result_text)
        
        if hasattr(state, 'bal_status_label'):
            state.bal_status_label.config(text=f"✓ Analýza hotová | Balanced strike: ${balanced_strike:.2f}")
        
        # Ulož výsledky - strike sa automaticky zobrazí v riadku 2 (strangle princíp)
        strike_str = f"{balanced_strike:.2f}"
        premium_str = f"{opp_premium:.2f}"
        print(f"DEBUG: Nastavujem strike={strike_str}, premium={premium_str}", flush=True)
        
        # Nastav hodnoty do StringVar
        state.bal_opposite_strike_var.set(strike_str)
        state.bal_opposite_premium_var.set(premium_str)
        
        # Aktualizuj UI - uisti sa, že strike je viditeľný
        state.root.update_idletasks()
        
        # Overenie - skontroluj, či sa strike správne nastavil
        actual_strike = state.bal_opposite_strike_var.get()
        print(f"DEBUG: Strike po nastavení: '{actual_strike}' (dĺžka: {len(actual_strike) if actual_strike else 0})", flush=True)
        
        # Skontroluj, či Entry widget existuje a má správnu hodnotu
        if hasattr(state, 'bal_opposite_strike_entry'):
            entry_value = state.bal_opposite_strike_entry.get()
            print(f"DEBUG: Entry widget hodnota: '{entry_value}'", flush=True)
            if entry_value != strike_str:
                print(f"WARNING: Entry widget hodnota sa nezhoduje! Očakávané: '{strike_str}', Skutočné: '{entry_value}'", flush=True)
                # Vynúť aktualizáciu
                state.bal_opposite_strike_entry.delete(0, tk.END)
                state.bal_opposite_strike_entry.insert(0, strike_str)
        
        if not actual_strike or actual_strike.strip() == '':
            print(f"ERROR: Strike sa nenastavil! balanced_strike={balanced_strike}, strike_str={strike_str}", flush=True)
        state.bal_last_analysis = {
            'long': {
                'type': long_type,
                'strike': long_strike,
                'premium': long_premium,
                'expiry': expiry
            },
            'opposite': {
                'type': opp_type,
                'strike': balanced_strike,
                'premium': opp_premium,
                'expiry': expiry
            },
            'underlying': underlying,
            'iv': iv,
            'r': r
        }
        
    except Exception as e:
        print(f"DEBUG: EXCEPTION v analyze_balancer: {e}", flush=True)
        import traceback
        traceback.print_exc()
        messagebox.showerror("Chyba", f"Chyba analýzy: {e}")


def fetch_balancer_option_price(state):
    """Stiahne presnú cenu pre opačnú opciu"""
    if not hasattr(state, 'bal_last_analysis') or not state.bal_last_analysis:
        messagebox.showwarning("Chyba", "Najprv spustite analýzu")
        return
    
    opp = state.bal_last_analysis['opposite']
    strike = opp.get('strike')
    try:
        user_val = state.bal_opposite_strike_var.get()
        if user_val:
            strike = float(user_val)
    except Exception:
        pass
    
    expiry = opp['expiry']
    opt_type = opp['type']
    right = 'C' if opt_type == 'CALL' else 'P'
    symbol = state.symbol_var.get()
    port = state.port_var.get()
    
    if hasattr(state, 'bal_status_label'):
        state.bal_status_label.config(text=f"Sťahujem cenu {right} strike {strike}...")
    
    def run():
        try:
            script_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'scripts', 'tws_fetch_option.py')
            result = subprocess.run(
                ['python3', script_path, str(port), symbol, expiry, str(strike), right],
                capture_output=True, text=True, timeout=20,
                cwd='/home/narbon/Aplikácie/tws-webapp'
            )
            output = result.stdout.strip()
            if result.returncode == 0 and output and not output.startswith("ERROR:"):
                price = float(output)
                state.root.after(0, lambda: state.bal_opposite_premium_var.set(f"{price:.2f}"))
                if hasattr(state, 'bal_status_label'):
                    state.root.after(0, lambda: state.bal_status_label.config(text=f"✓ Cena: ${price:.2f}"))
                state.bal_last_analysis['opposite']['price'] = price
                # Prepočítaj graf ak existuje
                state.root.after(100, lambda: show_balancer_plot(state))
            else:
                err = output or result.stderr.strip()
                if hasattr(state, 'bal_status_label'):
                    state.root.after(0, lambda: state.bal_status_label.config(text="❌ Chyba pri stiahnutí"))
                state.root.after(0, lambda: messagebox.showwarning("Chyba", f"Nepodarilo sa stiahnuť cenu:\n{err}"))
        except Exception as e:
            if hasattr(state, 'bal_status_label'):
                state.root.after(0, lambda: state.bal_status_label.config(text=f"❌ {str(e)[:40]}"))
    
    threading.Thread(target=run, daemon=True).start()


def show_balancer_plot(state):
    """Zobrazí graf PL1 + PL2 vs cena podkladu"""
    if not MATPLOTLIB_AVAILABLE:
        messagebox.showerror("Chyba", "Na zobrazenie grafu je potrebný matplotlib")
        return
    
    if not hasattr(state, 'bal_last_analysis') or not state.bal_last_analysis:
        messagebox.showwarning("Chyba", "Najprv spustite analýzu")
        return
    
    try:
        analysis = state.bal_last_analysis
        long_info = analysis['long']
        opp_info = analysis['opposite']
        underlying = analysis['underlying']
        iv = analysis['iv']
        r = analysis['r']
        
        # Parametre
        long_type = long_info['type']
        long_strike = long_info['strike']
        long_premium = long_info['premium']
        
        opp_type = opp_info['type']
        opp_strike = opp_info['strike']
        opp_premium = opp_info.get('premium', 0)
        
        expiry = long_info['expiry']
        T = get_time_to_expiry_years(expiry)
        
        # Rozsah cien podkladu - použijeme ATR
        atr_mult = float(state.bal_plot_atr_mult_var.get() or 2.0)
        atr = state.atr_7d if hasattr(state, 'atr_7d') and state.atr_7d and state.atr_7d > 0 else underlying * 0.05
        
        # Rozsah: underlying ± (ATR × multiplier)
        low = max(0.01, underlying - atr * atr_mult)
        high = underlying + atr * atr_mult
        
        print(f"DEBUG: ATR={atr:.2f}, multiplier={atr_mult}, rozsah=[{low:.2f}, {high:.2f}]")
        
        # Vytvor grid cien podkladu - hustejší grid pre lepšiu presnosť
        n = 501  # Viac bodov pre plynulejší graf
        Ss = [low + (high - low) * i / (n-1) for i in range(n)]
        
        # Vypočítaj PL pre každú cenu podkladu
        pl_long_vals = []
        pl_opp_vals = []
        pl_total_vals = []
        
        for S in Ss:
            # Používame aproximáciu: hodnota opcie sa mení podľa vzdialenosti od strike
            # Pre LONG PUT: hodnota rastie, keď cena klesá pod strike
            # Pre LONG CALL: hodnota rastie, keď cena stúpa nad strike
            
            # LONG PUT: čím nižšie S, tým vyššia hodnota
            if long_type == 'PUT':
                # Pri underlying: hodnota = long_premium
                # Pri strike: hodnota = intrinsic + časová hodnota
                # Aproximácia: lineárna zmena od aktuálnej ceny
                if S >= long_strike:
                    # OTM: len časová hodnota, klesá s rastúcou cenou
                    distance = S - underlying
                    # Časová hodnota klesá približne $0.10 za každý $1 pohyb od strike
                    time_value_change = -0.10 * distance
                    current_value_long = max(0.01, long_premium + time_value_change)
                else:
                    # ITM: intrinsic + časová hodnota
                    intrinsic = long_strike - S
                    # Približná časová hodnota
                    time_value = long_premium if S >= underlying else long_premium * 0.5
                    current_value_long = intrinsic + time_value
            else:  # CALL
                if S <= long_strike:
                    # OTM
                    distance = underlying - S
                    time_value_change = -0.10 * distance
                    current_value_long = max(0.01, long_premium + time_value_change)
                else:
                    # ITM
                    intrinsic = S - long_strike
                    time_value = long_premium if S <= underlying else long_premium * 0.5
                    current_value_long = intrinsic + time_value
            
            pl_long = (current_value_long - long_premium) * 100
            pl_long_vals.append(pl_long)
            
            # LONG opačná opcia
            if opp_type == 'PUT':
                if S >= opp_strike:
                    distance = S - underlying
                    time_value_change = -0.10 * distance
                    current_value_opp = max(0.01, opp_premium + time_value_change)
                else:
                    intrinsic = opp_strike - S
                    time_value = opp_premium if S >= underlying else opp_premium * 0.5
                    current_value_opp = intrinsic + time_value
            else:  # CALL
                if S <= opp_strike:
                    # OTM: časová hodnota klesá, keď sa vzďaľujeme
                    distance = underlying - S
                    time_value_change = -0.10 * distance
                    current_value_opp = max(0.01, opp_premium + time_value_change)
                else:
                    # ITM: intrinsic + časová hodnota
                    intrinsic = S - opp_strike
                    time_value = opp_premium if S <= underlying else opp_premium * 0.5
                    current_value_opp = intrinsic + time_value
            
            pl_opp = (current_value_opp - opp_premium) * 100
            pl_opp_vals.append(pl_opp)
            
            # Celkový P/L
            pl_total = pl_long + pl_opp
            pl_total_vals.append(pl_total)
        
        # Vypočítaj P/L pri pohybe ±$1 od aktuálnej ceny
        idx_current = min(range(len(Ss)), key=lambda i: abs(Ss[i] - underlying))
        
        # Nájdi index pre underlying + 1
        idx_plus1 = min(range(len(Ss)), key=lambda i: abs(Ss[i] - (underlying + 1)))
        idx_minus1 = min(range(len(Ss)), key=lambda i: abs(Ss[i] - (underlying - 1)))
        
        pl_at_current = pl_total_vals[idx_current]
        pl_at_plus1 = pl_total_vals[idx_plus1]
        pl_at_minus1 = pl_total_vals[idx_minus1]
        
        change_plus1 = pl_at_plus1 - pl_at_current
        change_minus1 = pl_at_minus1 - pl_at_current
        
        print(f"DEBUG P/L changes:")
        print(f"  Pri ${underlying:.2f}: P/L = ${pl_at_current:.2f}")
        print(f"  Pri ${underlying+1:.2f}: P/L = ${pl_at_plus1:.2f} (zmena: ${change_plus1:+.2f})")
        print(f"  Pri ${underlying-1:.2f}: P/L = ${pl_at_minus1:.2f} (zmena: ${change_minus1:+.2f})")
        
        # Vytvor graf - len celkový P/L (tvar V)
        win = tk.Toplevel(state.root)
        win.title("Strangle - Celkový P/L vs Cena podkladu")
        win.geometry("1000x700")
        
        fig = plt.Figure(figsize=(12, 8), dpi=100)
        ax = fig.add_subplot(111)
        
        # Hlavná krivka - celkový P/L (tvar V pre strangle)
        ax.plot(Ss, pl_total_vals, label='Celkový P/L (Strangle)', color='blue', linewidth=3)
        
        # Nulová línia
        ax.axhline(0, color='black', linewidth=1, linestyle='-', alpha=0.7)
        
        # Aktuálna cena podkladu
        ax.axvline(underlying, color='purple', linestyle='--', linewidth=2, label=f'Aktuálna cena: ${underlying:.2f}')
        
        # Strike pre PUT a CALL
        if long_type == 'PUT':
            ax.axvline(long_strike, color='red', linestyle=':', linewidth=1.5, alpha=0.7, label=f'PUT Strike: ${long_strike:.0f}')
            ax.axvline(opp_strike, color='green', linestyle=':', linewidth=1.5, alpha=0.7, label=f'CALL Strike: ${opp_strike:.0f}')
        else:
            ax.axvline(long_strike, color='green', linestyle=':', linewidth=1.5, alpha=0.7, label=f'CALL Strike: ${long_strike:.0f}')
            ax.axvline(opp_strike, color='red', linestyle=':', linewidth=1.5, alpha=0.7, label=f'PUT Strike: ${opp_strike:.0f}')
        
        # Break-even body
        total_cost = long_premium + opp_premium
        if long_type == 'PUT':
            be_down = long_strike - total_cost
            be_up = opp_strike + total_cost
        else:
            be_up = long_strike + total_cost
            be_down = opp_strike - total_cost
        
        ax.axvline(be_down, color='orange', linestyle='--', linewidth=1.5, alpha=0.6, label=f'Break-even dole: ${be_down:.2f}')
        ax.axvline(be_up, color='orange', linestyle='--', linewidth=1.5, alpha=0.6, label=f'Break-even hore: ${be_up:.2f}')
        
        # Anotácie pri aktuálnej cene a ±$1
        try:
            # Aktuálna cena
            ax.plot(underlying, pl_at_current, 'ro', markersize=12, zorder=5)
            ax.annotate(
                f'TERAZ: ${underlying:.2f}\nP/L: ${pl_at_current:.0f}',
                xy=(underlying, pl_at_current),
                xytext=(20, -40),
                textcoords='offset points',
                bbox=dict(boxstyle='round', fc='yellow', alpha=0.9),
                fontsize=11,
                fontweight='bold',
                arrowprops=dict(arrowstyle='->', color='red', lw=2)
            )
            
            # +$1
            ax.plot(underlying + 1, pl_at_plus1, 'go', markersize=8, zorder=5)
            ax.annotate(
                f'+$1: ${underlying+1:.2f}\nP/L: ${pl_at_plus1:.0f}\nZmena: ${change_plus1:+.0f}',
                xy=(underlying + 1, pl_at_plus1),
                xytext=(10, 15),
                textcoords='offset points',
                bbox=dict(boxstyle='round', fc='lightgreen', alpha=0.8),
                fontsize=9,
                arrowprops=dict(arrowstyle='->', color='green', lw=1.5)
            )
            
            # -$1
            ax.plot(underlying - 1, pl_at_minus1, 'go', markersize=8, zorder=5)
            ax.annotate(
                f'-$1: ${underlying-1:.2f}\nP/L: ${pl_at_minus1:.0f}\nZmena: ${change_minus1:+.0f}',
                xy=(underlying - 1, pl_at_minus1),
                xytext=(10, 15),
                textcoords='offset points',
                bbox=dict(boxstyle='round', fc='lightgreen', alpha=0.8),
                fontsize=9,
                arrowprops=dict(arrowstyle='->', color='green', lw=1.5)
            )
        except Exception as e:
            print(f"DEBUG: Chyba pri anotáciach: {e}")
        
        # Vyplň oblasti
        # Zisková oblasť (nad 0)
        ax.fill_between(Ss, 0, pl_total_vals, where=[pl > 0 for pl in pl_total_vals], 
                        color='green', alpha=0.2, label='Zisková oblasť')
        # Stratová oblasť (pod 0)
        ax.fill_between(Ss, 0, pl_total_vals, where=[pl < 0 for pl in pl_total_vals], 
                        color='red', alpha=0.2, label='Stratová oblasť')
        
        ax.set_xlabel('Cena podkladu (Underlying Price) $', fontsize=12)
        ax.set_ylabel('Celkový P/L $ (pre jeden kontrakt)', fontsize=12)
        ax.set_title(f'STRANGLE: LONG {long_type} ${long_strike:.0f} @ ${long_premium:.2f} + LONG {opp_type} ${opp_strike:.0f} @ ${opp_premium:.2f}\n(Celkový náklad: ${total_cost:.2f} = ${total_cost*100:.0f} per kontrakt)', 
                    fontsize=13, fontweight='bold')
        ax.grid(True, alpha=0.3)
        ax.legend(loc='best', fontsize=10)
        
        # Pridaj text s kľúčovými informáciami
        info_text = f'Max. strata: ${min(pl_total_vals):.0f}\n'
        info_text += f'Celkový náklad: ${total_cost:.2f} (${total_cost*100:.0f})\n'
        info_text += f'DTE: {int(T*365)} dní | IV: {iv:.1%}\n'
        info_text += f'ATR: ${atr:.2f} (rozsah: ±${atr*atr_mult:.2f})\n\n'
        info_text += f'ZMENA P/L pri pohybe o $1:\n'
        info_text += f'  Hore (+$1): ${change_plus1:+.0f}\n'
        info_text += f'  Dole (-$1): ${change_minus1:+.0f}'
        
        ax.text(0.02, 0.98, info_text, transform=ax.transAxes, 
               fontsize=9, verticalalignment='top',
               bbox=dict(boxstyle='round', facecolor='wheat', alpha=0.8),
               family='monospace')
        
        canvas = FigureCanvasTkAgg(fig, master=win)
        canvas.draw()
        canvas.get_tk_widget().pack(fill='both', expand=True)
        
    except Exception as e:
        messagebox.showerror("Chyba", f"Chyba pri kreslení grafu: {e}")
        import traceback
        traceback.print_exc()


def create_balancer_tab(parent, state):
    """Záložka pre Balancer"""
    
    # === Riadok 1: LONG opcia (z Kalkulátora) ===
    long_frame = ttk.LabelFrame(parent, text="Riadok 1: LONG opcia (z Kalkulátora)", padding=10)
    long_frame.pack(fill='x', padx=10, pady=5)
    
    long_row1 = ttk.Frame(long_frame)
    long_row1.pack(fill='x', pady=3)
    
    ttk.Label(long_row1, text="Typ:").pack(side='left', padx=5)
    ttk.Combobox(long_row1, textvariable=state.bal_long_type_var, values=["CALL", "PUT"], width=6, state='readonly').pack(side='left', padx=5)
    
    ttk.Button(long_row1, text="📥 Načítať z Kalkulátora", command=lambda: bal_load_from_calculator(state)).pack(side='left', padx=10)
    
    ttk.Label(long_row1, text="Strike:").pack(side='left', padx=5)
    ttk.Entry(long_row1, textvariable=state.bal_long_strike_var, width=10, state='readonly').pack(side='left', padx=5)
    
    ttk.Label(long_row1, text="Premium $:").pack(side='left', padx=5)
    ttk.Entry(long_row1, textvariable=state.bal_long_premium_var, width=8, state='readonly').pack(side='left', padx=5)
    
    ttk.Label(long_row1, text="Expiry:").pack(side='left', padx=5)
    ttk.Entry(long_row1, textvariable=state.bal_long_expiry_var, width=12, state='readonly').pack(side='left', padx=5)
    
    # === Riadok 2: Opačná opcia (vypočítaná) ===
    # Strangle princíp: Strike je automaticky vypočítaný pre balancovanie PL_long + PL_opp = 0
    opp_frame = ttk.LabelFrame(parent, text="Riadok 2: Opačná opcia (Strike vypočítaný pre balancovanie - Strangle)", padding=10)
    opp_frame.pack(fill='x', padx=10, pady=5)
    
    opp_row1 = ttk.Frame(opp_frame)
    opp_row1.pack(fill='x', pady=3)
    
    ttk.Label(opp_row1, text="Typ:").pack(side='left', padx=5)
    ttk.Combobox(opp_row1, textvariable=state.bal_opposite_type_var, values=["CALL", "PUT"], width=6, state='readonly').pack(side='left', padx=5)
    ttk.Label(opp_row1, text="(LONG opcia)", foreground='blue').pack(side='left', padx=5)
    
    ttk.Label(opp_row1, text="Strike:").pack(side='left', padx=5)
    strike_entry = ttk.Entry(opp_row1, textvariable=state.bal_opposite_strike_var, width=10, state='readonly')
    strike_entry.pack(side='left', padx=5)
    # Ulož referenciu na Entry widget pre debug
    state.bal_opposite_strike_entry = strike_entry
    ttk.Label(opp_row1, text="(vypočítaný pre balancovanie)", foreground='blue', font=('TkDefaultFont', 9, 'bold')).pack(side='left', padx=2)
    
    ttk.Label(opp_row1, text="Premium $:").pack(side='left', padx=5)
    ttk.Entry(opp_row1, textvariable=state.bal_opposite_premium_var, width=8).pack(side='left', padx=5)
    ttk.Button(opp_row1, text="📥 Stiahnuť presnú cenu", command=lambda: fetch_balancer_option_price(state)).pack(side='left', padx=10)
    
    ttk.Label(opp_row1, text="Expiry:").pack(side='left', padx=5)
    ttk.Label(opp_row1, textvariable=state.bal_long_expiry_var, width=12).pack(side='left', padx=5)
    ttk.Label(opp_row1, text="(rovnaká)", foreground='blue').pack(side='left', padx=2)
    
    # === Parametre ===
    params_frame = ttk.LabelFrame(parent, text="Parametre", padding=10)
    params_frame.pack(fill='x', padx=10, pady=5)
    
    params_row = ttk.Frame(params_frame)
    params_row.pack(fill='x', pady=3)
    
    ttk.Label(params_row, text="Underlying $:").pack(side='left', padx=5)
    ttk.Entry(params_row, textvariable=state.bal_underlying_var, width=10).pack(side='left', padx=5)
    ttk.Button(params_row, text="📥 Stiahnuť", command=lambda: fetch_bal_underlying(state)).pack(side='left', padx=5)
    
    ttk.Label(params_row, text="IV:").pack(side='left', padx=5)
    ttk.Entry(params_row, textvariable=state.bal_iv_var, width=6).pack(side='left', padx=5)
    
    # === Tlačidlá ===
    btn_frame = ttk.Frame(parent)
    btn_frame.pack(fill='x', padx=10, pady=10)
    
    ttk.Button(btn_frame, text="🔍 ANALYZOVAŤ BALANCOVANIE", command=lambda: analyze_balancer(state), 
               style='Accent.TButton').pack(side='left', padx=5)
    
    # Graf
    plot_row = ttk.Frame(btn_frame)
    plot_row.pack(side='left', padx=20)
    ttk.Label(plot_row, text="Rozsah (×ATR):").pack(side='left', padx=5)
    ttk.Entry(plot_row, textvariable=state.bal_plot_atr_mult_var, width=6).pack(side='left', padx=5)
    ttk.Button(plot_row, text="📈 Zobraziť graf PL1+PL2", command=lambda: show_balancer_plot(state)).pack(side='left', padx=5)
    
    # === Výsledky ===
    result_frame = ttk.LabelFrame(parent, text="Výsledok analýzy", padding=10)
    result_frame.pack(fill='both', expand=True, padx=10, pady=10)
    
    bal_results_text = scrolledtext.ScrolledText(result_frame, height=15, font=('Courier', 10))
    bal_results_text.pack(fill='both', expand=True)
    state.bal_results_text = bal_results_text
    
    # Status
    bal_status_label = ttk.Label(parent, text="Pripravené - načítajte LONG z Kalkulátora", font=('Arial', 10))
    bal_status_label.pack(fill='x', padx=10, pady=4)
    state.bal_status_label = bal_status_label
