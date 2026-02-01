#!/usr/bin/env python3
"""
Záložka: Swing Hunter
Inteligentné hľadač vstupov pomocou RSI a RVI.
"""
import re
import time
import tkinter as tk
from tkinter import ttk, messagebox
import threading
import os
import sys
import json
import subprocess
import math
import csv
from datetime import datetime
import pandas as pd
import pandas_ta as ta

SCORE_FILTER_MAP = {
    "Žiadny filter": 0.0,
    "≥40 %": 40.0,
    "≥50 %": 50.0,
    "≥80 %": 80.0
}

LOG_FIELDNAMES = [
    'EntryTime', 'Symbol', 'Timeframe', 'EntryPrice',
    'RSI', 'PercentB', 'SignalType', 'ExitPrice', 'FinalPL'
]
LOG_FILE = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'swing_hunter_log.csv')

def _ensure_log_file():
    if os.path.exists(LOG_FILE):
        return
    try:
        with open(LOG_FILE, 'w', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=LOG_FIELDNAMES)
            writer.writeheader()
    except Exception:
        pass


def log_signal_entry(symbol, timeframe, entry_price, rsi, pct_b, signal_type):
    _ensure_log_file()
    entry = {
        'EntryTime': datetime.now().isoformat(),
        'Symbol': symbol,
        'Timeframe': timeframe,
        'EntryPrice': f"{entry_price:.2f}",
        'RSI': f"{rsi:.2f}",
        'PercentB': f"{pct_b:.1f}" if pct_b is not None else '',
        'SignalType': signal_type,
        'ExitPrice': '',
        'FinalPL': ''
    }
    try:
        with open(LOG_FILE, 'a', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=LOG_FIELDNAMES)
            writer.writerow(entry)
    except Exception:
        pass
    return entry['EntryTime']


def log_signal_exit(entry_time, exit_price, final_pl):
    if not os.path.exists(LOG_FILE):
        return
    updated = False
    rows = []
    try:
        with open(LOG_FILE, 'r', newline='', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            fieldnames = reader.fieldnames or LOG_FIELDNAMES
            for row in reader:
                if row.get('EntryTime') == entry_time and not row.get('ExitPrice'):
                    row['ExitPrice'] = f"{exit_price:.2f}"
                    row['FinalPL'] = f"{final_pl:+.2f}"
                    updated = True
                rows.append(row)
    except Exception:
        return
    if updated:
        try:
            with open(LOG_FILE, 'w', newline='', encoding='utf-8') as f:
                writer = csv.DictWriter(f, fieldnames=fieldnames)
                writer.writeheader()
                writer.writerows(rows)
        except Exception:
            pass

def score_to_percent(score):
    return round(score * 10)

def get_dynamic_interval(score_pct, zone, pct_b):
    if zone == 'risk' or (pct_b is not None and pct_b > 90):
        return 120
    if score_pct > 60:
        return 60
    if 30 <= score_pct <= 60:
        return 600
    return 1800


def format_mmss(seconds):
    m, s = divmod(int(seconds), 60)
    return f"{m:02d}:{s:02d}"


def update_next_update_labels(state):
    tree = getattr(state, 'hunter_tree', None)
    if not tree:
        return
    now = time.time()
    for item in tree.get_children():
        sym = tree.item(item, 'text')
        next_ts = state.hunter_next_update.get(sym)
        if next_ts:
            delta = max(0, int(next_ts - now))
            tree.set(item, 'next_update', format_mmss(delta))
            base_tags = list(state.hunter_base_tags.get(sym, tree.item(item, 'tags')))
            base_tags = [t for t in base_tags if t != 'priority_short']
            if delta < 120:
                base_tags.append('priority_short')
            tree.item(item, tags=tuple(dict.fromkeys(base_tags)))
        else:
            tree.set(item, 'next_update', "--:--")
    state.root.after(1000, lambda: update_next_update_labels(state))

# --- MATEMATIKA INDIKÁTOROV ---

def _find_bb_column(bb, label, period, std_dev):
    """Pomôcka na zistenie správneho názvu stĺpca (%B/Bands)"""
    target = f"{label}_{period}_{float(std_dev)}"
    for col in bb.columns:
        if target in col:
            return col
    for col in bb.columns:
        if col.startswith(label):
            return col
    return None

def calculate_bb(candles, period=20, std_dev=2):
    """Vypočíta Bollinger Bands a %B"""
    if len(candles) < period: return None
    df = pd.DataFrame(candles)
    bb = df.ta.bbands(length=period, std=std_dev)
    if bb is None or bb.empty: return None

    l_col = _find_bb_column(bb, 'BBL', period, std_dev)
    m_col = _find_bb_column(bb, 'BBM', period, std_dev)
    u_col = _find_bb_column(bb, 'BBU', period, std_dev)
    p_col = _find_bb_column(bb, 'BBP', period, std_dev)

    if not all([l_col, m_col, u_col, p_col]):
        return None

    last = bb.iloc[-1]
    return {
        'lower': last[l_col],
        'mid': last[m_col],
        'upper': last[u_col],
        'pct_b': last[p_col] * 100 # Prevod na percentá
    }
def calculate_macd(candles, fast=12, slow=26, signal=9):
    """Vypočíta MACD a zistí crossover"""
    if len(candles) < slow + signal: return None
    df = pd.DataFrame(candles)
    macd = df.ta.macd(fast=fast, slow=slow, signal=signal)
    if macd is None or macd.empty: return None
    
    # MACD_12_26_9, MACDh_12_26_9, MACDs_12_26_9
    m_col = f'MACD_{fast}_{slow}_{signal}'
    s_col = f'MACDs_{fast}_{slow}_{signal}'
    
    last_3 = macd.tail(3)
    # Bullish cross: MACD > Signal teraz, ale MACD <= Signal v predchádzajúcich 3 baroch
    curr_m, curr_s = last_3.iloc[-1][m_col], last_3.iloc[-1][s_col]
    
    is_bullish_cross = False
    for i in range(1, len(last_3)):
        prev_m, prev_s = last_3.iloc[-(i+1)][m_col], last_3.iloc[-(i+1)][s_col]
        if prev_m <= prev_s and curr_m > curr_s:
            is_bullish_cross = True
            break
            
    return {
        'macd': curr_m,
        'signal': curr_s,
        'is_cross': is_bullish_cross
    }

def vypocitaj_swing_skore(rsi, price, bb, rvi, rvi_s, macd_data, p_dist, best_level):
    """Vypočíta celkové Swing Skóre (0-10), rozklad po indikátoroch a aktuálnu zónu"""
    score = 0
    breakdown = {}
    pct_b = bb['pct_b'] if bb else None
    is_macd_bull = bool(macd_data and macd_data.get('is_cross'))
    is_rvi_bull = rvi > rvi_s

    if rsi < 30:
        score += 2
        breakdown['RSI'] = breakdown.get('RSI', 0) + 2

    if bb and price <= bb['lower']:
        score += 2
        breakdown['BB'] = breakdown.get('BB', 0) + 2

    if is_rvi_bull:
        score += 2
        breakdown['RVI'] = breakdown.get('RVI', 0) + 2

    if is_macd_bull:
        score += 2
        breakdown['MACD'] = breakdown.get('MACD', 0) + 2

    if abs(p_dist) < 0.5 and best_level in ('S1', 'S2'):
        score += 2
        breakdown['Pivot'] = breakdown.get('Pivot', 0) + 2

    zone = determine_swing_zone(rsi, pct_b)
    if zone == 'hold':
        score = min(score, 6)
    elif zone == 'risk':
        score = min(score, 4)
    elif zone == 'hunt' and (is_macd_bull or is_rvi_bull):
        score = max(score, 9)

    score = min(max(score, 0), 10)
    return score, breakdown, zone

def determine_swing_zone(rsi, pct_b):
    """Rozlíši trhovú zónu podľa Bollinger %B a RSI"""
    if pct_b is None:
        return 'neutral'
    if pct_b > 80 or rsi > 70:
        return 'risk'
    if pct_b < 25 and rsi < 40:
        return 'hunt'
    if 25 <= pct_b <= 75:
        return 'hold'
    return 'neutral'

def calculate_pivots(candle):
    """Vypočíta Standard Pivot Points z jednej sviečky (HLC)"""
    h, l, c = candle['high'], candle['low'], candle['close']
    p = (h + l + c) / 3
    return {
        'P': p,
        'R1': (2 * p) - l,
        'S1': (2 * p) - h,
        'R2': p + (h - l),
        'S2': p - (h - l)
    }

def calculate_rsi(candles, period=14):
    if len(candles) < period + 1: return 50.0
    closes = [c['close'] for c in candles]
    deltas = [closes[i+1] - closes[i] for i in range(len(closes)-1)]
    gains = [d if d > 0 else 0 for d in deltas]
    losses = [abs(d) if d < 0 else 0 for d in deltas]
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period
    if avg_loss == 0: return 100.0
    for i in range(period, len(deltas)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
    rs = avg_gain / avg_loss if avg_loss != 0 else 0
    return 100 - (100 / (1 + rs))

def calculate_rvi(candles, period=10):
    if len(candles) < period + 4: return 0.0, 0.0
    vals = []
    for c in candles:
        body = c['close'] - c['open']
        r_val = c['high'] - c['low']
        vals.append(body / r_val if r_val > 0 else 0)
    smoothed = []
    for i in range(3, len(vals)):
        v = (vals[i] + 2*vals[i-1] + 2*vals[i-2] + vals[i-3]) / 6
        smoothed.append(v)
    if len(smoothed) < period: return 0.0, 0.0
    rvi_line = sum(smoothed[-period:]) / period
    rvi_hist = []
    for i in range(period, len(smoothed) + 1):
        rvi_hist.append(sum(smoothed[i-period:i]) / period)
    if not rvi_hist or len(rvi_hist) < 4: return rvi_line, rvi_line
    rvi_sig = (rvi_hist[-1] + 2*rvi_hist[-2] + 2*rvi_hist[-3] + rvi_hist[-4]) / 6
    return rvi_line, rvi_sig

# --- PIVOT POINTS ---

def get_pivot_distance(price, pivots):
    """Nájde najbližší pivot/support pod cenou a vypočíta vzdialenosť v %"""
    # Zaujímame sa hlavne o P, S1, S2 (pre nákupné signály)
    targets = [pivots['P'], pivots['S1'], pivots['S2']]
    # Filtrujeme tie, ktoré sú pod aktuálnou cenou (aby sme videli k čomu padáme)
    under = [t for t in targets if t <= price]
    if not under:
        # Ak sme pod S2, najbližší cieľ "pod nami" neexistuje v štandardných PP,
        # vrátime vzdialenosť k S2 (budeme v mínuse)
        dist = ((price / pivots['S2']) - 1) * 100
        return dist, "S2"
    
    closest_target = max(under) # Najbližší pod cenou
    name = "P" if closest_target == pivots['P'] else ("S1" if closest_target == pivots['S1'] else "S2")
    dist = ((price / closest_target) - 1) * 100
    return dist, name


_SCORE_REGEX = re.compile(r"Skóre:\s*([0-9]+(?:\.[0-9]+)?)")

def extract_score_value(text):
    """Z textu 'Skóre: 80 %' alebo 'Skóre: 8/10' vytiahne percento"""
    if not text:
        return 0.0
    if '%' in text:
        percent_match = re.search(r"([0-9]+(?:\.[0-9]+)?)\s*%", text)
        if percent_match:
            try:
                return float(percent_match.group(1))
            except ValueError:
                pass
    match = _SCORE_REGEX.search(text)
    if match:
        try:
            return float(match.group(1)) * 10
        except ValueError:
            pass
    float_match = re.search(r"-?\d+(\.\d+)?", text)
    if float_match:
        try:
            return float(float_match.group()) * (10 if float_match.group().count('/') else 1)
        except ValueError:
            pass
    return 0.0

def sort_hunter_tree_parents(tree, column, reverse=False):
    """Zoradí rodičovské riadky podľa symbolu (#0) alebo skóre"""
    parents = list(tree.get_children(''))

    def sort_key(item_id):
        if column == '#0':
            return tree.item(item_id, 'text').lower()
        val = tree.set(item_id, column)
        if column == 'rsi_score':
            return extract_score_value(val)
        if isinstance(val, str):
            return val.lower()
        return val

    parents.sort(key=sort_key, reverse=reverse)
    for index, item_id in enumerate(parents):
        tree.move(item_id, '', index)

# --- HLAVNÁ LOGIKA ---

def refresh_hunter(state, tree, rsi_p, rvi_p, tf_var, force=False, force_symbol=None):
    # 1. Získať symboly (len tie zaškrtnuté v Hunterovi)
    symbols = []
    try:
        if hasattr(state, 'hunter_selected_symbols'):
            symbols = [s for s, v in state.hunter_selected_symbols.items() if v.get()]
        
        # Unikátne symboly
        symbols = sorted(list(set(symbols)))
    except Exception as e:
        print(f"❌ Hunter: Symbol error: {e}", flush=True)

    # 2. Vyčistiť tabuľku od symbolov, ktoré už nie sú vybraté
    # (Robíme to hneď, aby tabuľka reagovala na odškrtnutie)
    for item_id in tree.get_children():
        sym_text = tree.item(item_id, 'text').strip()
        if sym_text and sym_text not in symbols:
            tree.delete(item_id)

    if not symbols:
        if force: messagebox.showwarning("Swing Hunter", "Vyberte symboly.")
        if hasattr(state, 'hunter_status_label'):
            state.hunter_status_label.config(text="✓ Vyčistené", foreground="gray")
        return 

    if hasattr(state, 'hunter_status_label'):
        state.hunter_status_label.config(text="🔍 ANALYZUJEM...", foreground="blue")

    filter_threshold = 0.0
    if hasattr(state, 'hunter_score_filter_var'):
        filter_threshold = SCORE_FILTER_MAP.get(state.hunter_score_filter_var.get(), 0.0)
    background_interval = getattr(state, 'hunter_background_refresh_interval', 3600)

    selected_tfs = []
    if hasattr(state, 'hunter_tf_vars'):
        selected_tfs = [tf for tf, var in state.hunter_tf_vars.items() if var.get()]
    if tf_var.get() not in selected_tfs:
        selected_tfs.insert(0, tf_var.get())
    if not selected_tfs:
        selected_tfs = [tf_var.get()]

    # Timeframes na skenovanie
    tfs = selected_tfs

    def run():
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        py = os.path.join(root, 'venv', 'bin', 'python3')
        if not os.path.exists(py): py = sys.executable
        scr = os.path.join(root, 'scripts', 'tws_fetch_history.py')
        port = str(state.port_var.get())

        for sym in symbols:
            if force_symbol and sym != force_symbol:
                continue

            # Kontrola počas behu: Ak už symbol nie je vybratý, preskočíme ho
            active_symbols = [s for s, v in state.hunter_selected_symbols.items() if v.get()]
            if sym not in active_symbols:
                continue

            next_ts = state.hunter_next_update.get(sym, 0)
            if not force and not force_symbol and time.time() < next_ts:
                continue

            last_scores = getattr(state, 'hunter_last_scores', {})
            last_updates = getattr(state, 'hunter_last_update', {})
            last_score = last_scores.get(sym)
            last_update = last_updates.get(sym, 0)
            if not (force or force_symbol == sym) and filter_threshold > 0 and last_score is not None and last_score < filter_threshold and (time.time() - last_update) < background_interval:
                continue

            # --- 1. ZÍSKANIE PIVOT DATA (Predchádzajúci deň/týždeň) ---
            pivots = None
            try:
                # Ak sme na dennom grafe, chceme týždenné pivoty, inak denné
                pivot_tf = "1 day" if tf_var.get() != "1 day" else "1 week"
                pivot_dur = "10 D" if pivot_tf == "1 day" else "1 M"
                
                cmd_p = [py, scr, '--symbol', sym, '--barSize', pivot_tf, '--duration', pivot_dur, '--port', port]
                res_p = subprocess.run(cmd_p, capture_output=True, text=True, timeout=50, cwd=root)
                if res_p.returncode == 0:
                    p_data = json.loads(res_p.stdout.strip())
                    if p_data.get('success') and len(p_data['candles']) >= 2:
                        # Posledná sviečka [-1] je dnešná (neúplná), predposledná [-2] je včerajšia (úplná)
                        prev_bar = p_data['candles'][-2]
                        pivots = calculate_pivots(prev_bar)
            except Exception as pe:
                print(f"❌ Pivot fetch error {sym}: {pe}")

            results_tf = {} # tf -> {rsi, rvi, rvi_s, price, status, action, tag}
            
            for tf in tfs:
                dur = "10 D"
                if "1 hour" in tf: dur = "25 D"
                elif "4 hours" in tf: dur = "60 D"
                elif "day" in tf: dur = "1 Y"
                elif "15 mins" in tf: dur = "5 D"

                try:
                    cmd = [py, scr, '--symbol', sym, '--barSize', tf, '--duration', dur, '--port', port]
                    if force or force_symbol:
                        cmd.append('--force')
                    
                    res = subprocess.run(cmd, capture_output=True, text=True, timeout=50, cwd=root)
                    
                    if res.returncode == 0:
                        data = json.loads(res.stdout.strip())
                        if data.get('success'):
                            c = data['candles']
                            if c:
                                try:
                                    r_p = int(rsi_p.get())
                                    rv_p = int(rvi_p.get())
                                except:
                                    r_p, rv_p = 14, 10
                                
                                rsi = calculate_rsi(c, r_p)
                                rvi, rvi_s = calculate_rvi(c, rv_p)
                                
                                # NOVÉ: Bollinger a MACD
                                bb_data = calculate_bb(c)
                                macd_data = calculate_macd(c)
                                
                                tf_status, tf_action, tf_tag = "Neutral", "Čakať", ""
                                
                                # EXTREME OVERWEIGHT logika
                                if rsi < 30 and bb_data and c[-1]['close'] <= bb_data['lower']:
                                    tf_status, tf_tag = "⚠️ EXTREME OVERWEIGHT", "alert"
                                elif rsi < 30: 
                                    tf_status, tf_tag = "🔥 PREPREDANÉ", "alert"
                                elif rsi > 70:
                                    tf_status, tf_tag = "❄️ PREKÚPENÉ", "alert"
                                
                                # CONFIRMED logika
                                if rvi > rvi_s:
                                    if macd_data and macd_data['is_cross']:
                                        tf_action, tf_tag = "🚀 CONFIRMED BUY", "buy"
                                    else:
                                        tf_action, tf_tag = "✅ BUY", "buy"
                                elif rsi > 70 and rvi < rvi_s:
                                    tf_action, tf_tag = "🔻 SHORT", "short"

                                results_tf[tf] = {
                                    'rsi': rsi, 'rvi': rvi, 'rvi_s': rvi_s, 
                                    'price': c[-1]['close'], 
                                    'status': tf_status, 'action': tf_action, 'tag': tf_tag,
                                    'bb': bb_data, 'macd': macd_data,
                                    'candles': c
                                }
                except Exception as e:
                    print(f"❌ Error fetching {sym} {tf}: {e}")

            # Vyhodnotenie po získaní všetkých TF pre daný symbol
            if not results_tf: continue

            main_tf = tf_var.get()
            if main_tf not in results_tf: main_tf = list(results_tf.keys())[0]
            
            main_data = results_tf[main_tf]
            price = main_data['price']
            
            # Logika Súladu a finálneho signálu pre Rodiča
            status, action, tag = "Neutral", "Čakať", ""
            
            rsi_vals = {tf: results_tf.get(tf, {}).get('rsi', 50.0) for tf in ["15 mins", "1 hour", "4 hours", "1 day"]}
            
            align_buy_short = rsi_vals['15 mins'] < 35 and rsi_vals['1 hour'] < 35
            align_buy_long  = rsi_vals['4 hours'] < 40 and rsi_vals['1 day'] < 45
            align_short_short = rsi_vals['15 mins'] > 65 and rsi_vals['1 hour'] > 65
            align_short_long  = rsi_vals['4 hours'] > 60 and rsi_vals['1 day'] > 55

            # Určenie tagu rodiča
            if align_buy_short and align_buy_long: tag = "align_perfect"
            elif align_buy_long: tag = "align_long"
            elif align_buy_short: tag = "align_short"
            elif align_short_short and align_short_long: tag = "align_perfect_s"
            elif align_short_long: tag = "align_long_s"
            elif align_short_short: tag = "align_short_s"

            # Výpočet Pivotov (z denného grafu)
            pivots = None
            p_dist_str = ""
            is_near_support = False
            
            if '1 day' in results_tf and len(results_tf['1 day']['candles']) >= 2:
                # candles[-1] je dnes, candles[-2] je včera (uzavretý deň)
                pivots = calculate_pivots(results_tf['1 day']['candles'][-2])
                
                # Vzdialenosť k najbližšiemu Supportu/Pivotu
                price = main_data['price']
                targets = {'P': pivots['P'], 'S1': pivots['S1'], 'S2': pivots['S2']}
                
                min_dist_pct = 999.0
                best_level = ""
                for name, val in targets.items():
                    dist_pct = ((price - val) / val) * 100
                    if abs(dist_pct) < abs(min_dist_pct):
                        min_dist_pct = dist_pct
                        best_level = name
                
                p_dist_str = f"{best_level} ({min_dist_pct:+.2f}%)"
                if abs(min_dist_pct) < 0.5: # Ak sme bližšie než 0.5% k hladine
                    is_near_support = best_level in ('S1', 'S2', 'P')

            # Signál na rodičovi
            is_oversold = any(v < 30 for v in rsi_vals.values())
            is_overbought = any(v > 70 for v in rsi_vals.values())
            
            # --- VÝPOČET SWING SKÓRE (na hlavnom TF) ---
            main_bb = main_data.get('bb')
            main_macd = main_data.get('macd')
            
            # Získame best_level a min_dist_pct pre skóre
            score_dist = 99.0
            score_level = ""
            if pivots:
                for name, val in {'P': pivots['P'], 'S1': pivots['S1'], 'S2': pivots['S2']}.items():
                    d_pct = ((price - val) / val) * 100
                    if abs(d_pct) < abs(score_dist):
                        score_dist = d_pct
                        score_level = name

            swing_score, breakdown, zone = vypocitaj_swing_skore(
                main_data['rsi'], price, main_bb, 
                main_data['rvi'], main_data['rvi_s'], 
                main_macd, score_dist, score_level
            )
            score_pct = score_to_percent(swing_score)
            active_key = (sym, main_tf)
            active_signal = state.hunter_active_signals.get(active_key, None)
            pl_signal_value = ""
            pl_tag = None
            if breakdown:
                breakdown_percent = {k: v * 10 for k, v in breakdown.items()}
                breakdown_text = ", ".join(f"{k}:{perc:.0f}%" for k, perc in breakdown_percent.items())
            else:
                breakdown_text = "Žiadny príspevok"

            if not hasattr(state, 'hunter_last_scores'):
                state.hunter_last_scores = {}
            if not hasattr(state, 'hunter_last_update'):
                state.hunter_last_update = {}
            if not hasattr(state, 'hunter_last_breakdown'):
                state.hunter_last_breakdown = {}
            state.hunter_last_scores[sym] = score_pct
            state.hunter_last_update[sym] = time.time()
            state.hunter_last_breakdown[sym] = breakdown_text

            score_tag = 'score_0_19'
            if score_pct >= 80:
                score_tag = "score_80_100"
            elif score_pct >= 50:
                score_tag = "score_50_79"
            elif score_pct >= 20:
                score_tag = "score_20_49"

            score_text = f"Skóre: {score_pct:.0f} %"
            pct_b_value = main_bb['pct_b'] if main_bb else None
            pct_b_text = f"{pct_b_value:.1f}%" if pct_b_value is not None else "—"
            if pct_b_value is None:
                pctb_tag = 'pctb_none'
            elif pct_b_value < 25:
                pctb_tag = 'pctb_low'
            elif pct_b_value > 80:
                pctb_tag = 'pctb_high'
            else:
                pctb_tag = 'pctb_mid'
            pivot_label = p_dist_str if p_dist_str else "—"
            pivot_bb_text = f"Pivot: {pivot_label} / %B: {pct_b_text}"
            interval = get_dynamic_interval(score_pct, zone, pct_b_value)
            next_update_time = time.time() + interval
            state.hunter_next_update[sym] = next_update_time
            next_update_text = format_mmss(interval)

            strong_macd = bool(main_macd and main_macd.get('is_cross'))
            rvi_bull = main_data['rvi'] > main_data['rvi_s']
            rvi_bear = main_data['rvi'] < main_data['rvi_s']
            macd_falling = bool(main_macd and main_macd.get('macd') < main_macd.get('signal', 0))

            action = "Neutral"
            if zone == 'hunt':
                action = "🚀 STRONG BUY" if strong_macd or rvi_bull else "⏳ SLEDOVAŤ AKUMULÁCIU"
            elif zone == 'hold':
                action = "⏳ DRŽAŤ / NEUTRÁL"
            elif zone == 'risk':
                action = "💰 VÝSTUP / TAKE PROFIT" if (rvi_bear or macd_falling) else "⚠️ RIZIKO / BLOKUJ BUY"
            else:
                if score_pct >= 80:
                    action = "🚀 RAKETA (Strong Buy)"
                elif score_pct >= 50:
                    action = "✅ VHODNÝ VSTUP"
                elif score_pct >= 20:
                    action = "⏳ ČAKAŤ (Sledovať)"
                else:
                    action = "Neutral"

            entry_actions = {"🚀 STRONG BUY", "✅ VHODNÝ VSTUP"}
            if action in entry_actions:
                if not active_signal:
                    entry_time = log_signal_entry(
                        sym, main_tf, price,
                        main_data['rsi'], pct_b_value,
                        action
                    )
                    state.hunter_active_signals[active_key] = {
                        'entry_price': price,
                        'entry_time': entry_time,
                        'signal_type': action
                    }
                    active_signal = state.hunter_active_signals[active_key]
            else:
                if active_signal:
                    final_pl = ((price - active_signal['entry_price']) / active_signal['entry_price']) * 100 if active_signal['entry_price'] else 0.0
                    log_signal_exit(active_signal['entry_time'], price, final_pl)
                    del state.hunter_active_signals[active_key]
                    active_signal = None

            if active_signal and active_signal.get('entry_price'):
                pl_pct = ((price - active_signal['entry_price']) / active_signal['entry_price']) * 100
                pl_signal_value = f"{pl_pct:+.2f}%"
                pl_tag = 'pl_profit' if pl_pct >= 0 else 'pl_loss'

            zone_tag = f"zone_{zone}" if zone else "zone_neutral"
            if zone_tag not in ('zone_hunt', 'zone_hold', 'zone_risk', 'zone_neutral'):
                zone_tag = 'zone_neutral'

            # Priorita stavu (EXTREME OVERWEIGHT má prednosť pred PREPREDANÉ)
            is_extreme = any(d.get('status') == "⚠️ EXTREME OVERWEIGHT" for d in results_tf.values())
            if is_extreme:
                status = "⚠️ EXTREME OVERWEIGHT"
            elif is_oversold:
                status = "🔥 PREPREDANÉ"
            elif is_overbought:
                status = "❄️ PREKÚPENÉ"

            def update_ui(s=sym, p=price, res_tf=results_tf, st=status, ac=action, tg=tag,
                          pct_b_cell=pct_b_text, pivot_bb=pivot_bb_text, sc_text=score_text,
                          bk_text=breakdown_text, z_tag=zone_tag, pct_tag=pctb_tag,
                          zone_name=zone, pl_disc=pl_signal_value, pl_t=pl_tag,
                          next_up=next_update_text):
                # Nájsť rodičovský riadok
                parent_id = None
                for item in tree.get_children():
                    if tree.item(item, 'text') == s:
                        parent_id = item
                        break
                
                # Zobrazenie skóre v stĺpci RSI rodiča (upravíme Treeview neskôr)
                vals = (
                    f"{p:.2f}",
                    sc_text,
                    pct_b_cell,
                    next_up,
                    f"{main_data['rvi']:.4f}",
                    f"{main_data['rvi_s']:.4f}",
                    pivot_bb,
                    st,
                    ac,
                    pl_disc,
                    bk_text
                )
                
                parent_tags = [score_tag]
                if pct_tag:
                    parent_tags.append(pct_tag)
                if z_tag:
                    parent_tags.append(z_tag)
                if pl_t:
                    parent_tags.append(pl_t)
                parent_tags.append('header')
                state.hunter_base_tags[s] = list(parent_tags)
                if tg:
                    parent_tags.insert(0, tg)

                if parent_id:
                    tree.item(parent_id, values=vals, tags=parent_tags)
                else:
                    parent_id = tree.insert('', tk.END, text=s, values=vals, tags=parent_tags, open=False)

                # Aktualizovať deti (Timeframy)
                for child in tree.get_children(parent_id):
                    tree.delete(child)
                
                for tf_name in ["15 mins", "1 hour", "4 hours", "1 day"]:
                    if tf_name in res_tf:
                        d = res_tf[tf_name]
                        ico = "🔥 " if d['rsi'] < 30 else ("❄️ " if d['rsi'] > 70 else "")
                        bb_value = f"{d['bb']['pct_b']:.1f}%" if d.get('bb') else "—"
                        pivot_bb_child = f"- / {bb_value}"
                        child_action = d['action']
                        pctb_child = None
                        if bb_value != "—":
                            try:
                                pctb_child = float(bb_value.replace('%', ''))
                            except ValueError:
                                pctb_child = None
                        if zone_name == 'risk':
                            child_action = "⚠️ STOP"
                        else:
                            if "BUY" in child_action.upper():
                                child_action = "Čakať"
                            if zone_name == 'hunt' and pctb_child is not None and pctb_child < 30 and ("BUY" in d['action'].upper() or "STRONG" in d['action'].upper()):
                                child_action = "🚀 STRONG BUY"
                        child_tags = [d['tag'], z_tag]
                        if pctb_child and pctb_child > 100:
                            child_tags.append('pctb_over')
                        tree.insert(parent_id, tk.END, text=f"  {tf_name}",
                                    values=(
                                        "",
                                        f"{ico}{d['rsi']:.1f}",
                                        bb_value,
                                        "",
                                        f"{d['rvi']:.4f}",
                                        f"{d['rvi_s']:.4f}",
                                        pivot_bb_child,
                                        d['status'],
                                        child_action,
                                        "",
                                        ""
                                    ),
                                    tags=tuple(child_tags))

            if filter_threshold <= 0 or score_pct >= filter_threshold:
                state.root.after(0, update_ui)

        def cleanup_low_symbols():
            if filter_threshold <= 0:
                return
            for item in tree.get_children():
                if tree.parent(item):
                    continue
                score_text = tree.set(item, 'rsi_score')
                if extract_score_value(score_text) < filter_threshold:
                    tree.delete(item)

        state.root.after(0, cleanup_low_symbols)
        state.root.after(0, lambda: state.hunter_status_label.config(text=f"✓ OK {datetime.now().strftime('%H:%M')}", foreground="green") if hasattr(state, 'hunter_status_label') else None)

    threading.Thread(target=run, daemon=True).start()

def update_hunter_symbols_ui(state, frame):
    for w in frame.winfo_children(): w.destroy()
    
    # 1. Získať všetky unikátne symboly (Monitor + Custom)
    mon_syms = []
    if hasattr(state, 'monitor_selected_symbols'):
        mon_syms = [s for s in state.monitor_selected_symbols.keys()]
    
    custom_syms = getattr(state, 'hunter_custom_tickers', [])
    all_syms = sorted(list(set(mon_syms + custom_syms)))
    
    if not all_syms:
        ttk.Label(frame, text="Zoznam je prázdny. Pridajte ticker.", foreground='gray').pack(side='left', padx=5)
        return

    # Použijeme Flow-like layout (viac riadkov ak treba)
    row_frame = ttk.Frame(frame)
    row_frame.pack(fill='x')
    
    for i, sym in enumerate(all_syms):
        # Ak máme priveľa symbolov, môžeme ich deliť do "riadkov" po 8
        if i > 0 and i % 8 == 0:
            row_frame = ttk.Frame(frame)
            row_frame.pack(fill='x', pady=2)

        s_container = ttk.Frame(row_frame, padding=(2, 0))
        s_container.pack(side='left', padx=5)

        if not hasattr(state, 'hunter_selected_symbols'): state.hunter_selected_symbols = {}
        if sym not in state.hunter_selected_symbols:
            val = True if sym in custom_syms else False
            state.hunter_selected_symbols[sym] = tk.BooleanVar(value=val)
        
        # Checkbox pre aktiváciu skenu
        cb = ttk.Checkbutton(s_container, text=sym, variable=state.hunter_selected_symbols[sym],
                             command=lambda: refresh_hunter(state, state.hunter_tree, state.hunter_rsi_p, state.hunter_rvi_p, state.hunter_tf_v))
        cb.pack(side='left')

        # Tlačidlo na vymazanie (len pre vlastné tickery)
        if sym in custom_syms:
            def make_delete_cmd(s=sym):
                return lambda: delete_single_custom_ticker(state, s, frame)
            
            del_btn = tk.Button(s_container, text="×", command=make_delete_cmd(), 
                               bd=0, fg='red', font=('Arial', 8, 'bold'), cursor='hand2')
            del_btn.pack(side='left', padx=(0, 5))

def delete_single_custom_ticker(state, sym, frame):
    """Odstráni jeden konkrétny vlastný ticker"""
    if hasattr(state, 'hunter_custom_tickers') and sym in state.hunter_custom_tickers:
        state.hunter_custom_tickers.remove(sym)
        # Tiež ho odstránime zo stavu vybraných
        if sym in state.hunter_selected_symbols:
            del state.hunter_selected_symbols[sym]
        state.save_settings_file()
        update_hunter_symbols_ui(state, frame)
        # Okamžitá aktualizácia tabuľky (odstránenie riadku)
        refresh_hunter(state, state.hunter_tree, state.hunter_rsi_p, state.hunter_rvi_p, state.hunter_tf_v)
        print(f"🗑️ Hunter: Symbol {sym} odstránený.")

def add_custom_ticker(state, entry, frame):
    sym = entry.get().strip().upper()
    if not sym: return
    
    if not hasattr(state, 'hunter_custom_tickers'): state.hunter_custom_tickers = []
    
    if sym not in state.hunter_custom_tickers:
        state.hunter_custom_tickers.append(sym)
        # Automaticky ho aktivujeme
        if not hasattr(state, 'hunter_selected_symbols'): state.hunter_selected_symbols = {}
        state.hunter_selected_symbols[sym] = tk.BooleanVar(value=True)
        
        state.save_settings_file()
        update_hunter_symbols_ui(state, frame)
        entry.delete(0, tk.END)
    else:
        messagebox.showinfo("Swing Hunter", f"Symbol {sym} už je v zozname.")

def create_swing_hunter_tab(parent, state):
    frame = ttk.Frame(parent, padding=15); frame.pack(fill='both', expand=True)
    h_frame = ttk.Frame(frame); h_frame.pack(fill='x', pady=(0, 10))
    ttk.Label(h_frame, text="🏹 Swing Hunter", font=('Arial', 12, 'bold')).pack(side='left')
    state.hunter_status_label = ttk.Label(h_frame, text="Pripravený", font=('Arial', 9, 'italic'))
    state.hunter_status_label.pack(side='right', padx=10)

    # Panel pre symboly
    s_frame = ttk.LabelFrame(frame, text="🎯 Sledované symboly", padding=10); s_frame.pack(fill='x', pady=5)
    
    # Pridávanie vlastných tickerov
    add_f = ttk.Frame(s_frame); add_f.pack(fill='x', pady=(0, 5))
    ttk.Label(add_f, text="Pridať vlastný ticker:").pack(side='left', padx=5)
    new_sym_ent = ttk.Entry(add_f, width=12)
    new_sym_ent.pack(side='left', padx=5)

    symbols_container = ttk.Frame(s_frame)
    state.hunter_symbols_visible = False

    def toggle_symbols_container():
        visible = getattr(state, 'hunter_symbols_visible', False)
        if visible:
            symbols_container.pack_forget()
            toggle_btn.config(text="📂 Zobraziť sledované symboly")
        else:
            symbols_container.pack(fill='x', pady=5)
            toggle_btn.config(text="📂 Skryť sledované symboly")
        state.hunter_symbols_visible = not visible

    toggle_btn = ttk.Button(add_f, text="📂 Zobraziť sledované symboly", command=toggle_symbols_container)
    toggle_btn.pack(side='right', padx=5)
    
    # Bindovanie Enter klávesy pre pridanie
    new_sym_ent.bind('<Return>', lambda e: add_custom_ticker(state, new_sym_ent, symbols_container))

    ttk.Button(add_f, text="➕ Pridať", width=8, command=lambda: add_custom_ticker(state, new_sym_ent, symbols_container)).pack(side='left', padx=5)
    
    def toggle_all_symbols(state, value):
        for sym, var in state.hunter_selected_symbols.items():
            var.set(value)
        refresh_hunter(state, state.hunter_tree, state.hunter_rsi_p, state.hunter_rvi_p, state.hunter_tf_v)

    ttk.Button(add_f, text="Označiť všetko", width=14, command=lambda: toggle_all_symbols(state, True)).pack(side='right', padx=5)
    ttk.Button(add_f, text="Odznačiť všetko", width=14, command=lambda: toggle_all_symbols(state, False)).pack(side='right', padx=5)
    
    ttk.Button(add_f, text="🔄 Sync Monitor", width=12, command=lambda: update_hunter_symbols_ui(state, symbols_container)).pack(side='right', padx=5)
    
    # Odstránenie vlastných tickerov
    def clear_custom():
        if messagebox.askyesno("Swing Hunter", "Naozaj vymazať VŠETKY vlastné tickery?"):
            state.hunter_custom_tickers = []
            # Necháme len tie, čo sú v monitore
            state.save_settings_file()
            update_hunter_symbols_ui(state, symbols_container)
            refresh_hunter(state, tree, rsi_p, rvi_p, tf_v)
    
    ttk.Button(add_f, text="🗑️ Vymazať Všetky Vlastné", width=22, command=clear_custom).pack(side='right', padx=5)

    update_hunter_symbols_ui(state, symbols_container)

    ctrl = ttk.LabelFrame(frame, text="⚙️ Nastavenia", padding=10); ctrl.pack(fill='x', pady=5)
    ttk.Label(ctrl, text="RSI:").pack(side='left', padx=5)
    rsi_p = tk.StringVar(value="14"); ttk.Entry(ctrl, textvariable=rsi_p, width=5).pack(side='left', padx=2)
    ttk.Label(ctrl, text="RVI:").pack(side='left', padx=(15, 5))
    rvi_p = tk.StringVar(value="10"); ttk.Entry(ctrl, textvariable=rvi_p, width=5).pack(side='left', padx=2)
    
    # Výber časových rámcov (multi-select by bol fajn, ale zatiaľ skúsime fixné sady alebo prepínač)
    ttk.Label(ctrl, text="Základný TF:").pack(side='left', padx=(15, 5))
    tf_v = tk.StringVar(value="1 hour"); ttk.Combobox(ctrl, textvariable=tf_v, values=["15 mins", "1 hour", "4 hours", "1 day"], width=10).pack(side='left', padx=5)
    
    tf_opts_frame = ttk.Frame(ctrl)
    tf_opts_frame.pack(fill='x', pady=(10, 0))
    ttk.Label(tf_opts_frame, text="TF analýza:").pack(side='left', padx=5)
    state.hunter_tf_vars = {}
    for tf_name in ["15 mins", "1 hour", "4 hours", "1 day"]:
        var = tk.BooleanVar(value=True)
        state.hunter_tf_vars[tf_name] = var
        ttk.Checkbutton(tf_opts_frame, text=tf_name, variable=var,
                        command=lambda: refresh_hunter(state, state.hunter_tree, state.hunter_rsi_p, state.hunter_rvi_p, state.hunter_tf_v)).pack(side='left', padx=2)

    state.hunter_score_filter_var = tk.StringVar(value=list(SCORE_FILTER_MAP.keys())[0])
    ttk.Label(ctrl, text="Filter skóre:").pack(side='left', padx=(20, 5))
    score_combo = ttk.Combobox(ctrl, textvariable=state.hunter_score_filter_var,
                               values=list(SCORE_FILTER_MAP.keys()), width=10, state='readonly')
    score_combo.pack(side='left')
    score_combo.bind("<<ComboboxSelected>>", lambda e: refresh_hunter(state, state.hunter_tree, state.hunter_rsi_p, state.hunter_rvi_p, state.hunter_tf_v))
    highlight_frame = tk.Frame(ctrl, highlightbackground='#2e7d32', highlightthickness=2, bd=0)
    highlight_frame.pack(side='right', padx=10, pady=2)
    ttk.Button(highlight_frame, text="🏹 VYHĽADAŤ PRÍLEŽITOSTI", command=lambda: refresh_hunter(state, state.hunter_tree, state.hunter_rsi_p, state.hunter_rvi_p, state.hunter_tf_v, force=True)).pack(padx=2, pady=2)
    state.hunter_last_scores = {}
    state.hunter_last_update = {}
    state.hunter_background_refresh_interval = 3600
    state.hunter_active_signals = {}
    state.hunter_next_update = {}
    state.hunter_base_tags = {}

    t_frame = ttk.Frame(frame); t_frame.pack(fill='both', expand=True, pady=10)
    # Upravené stĺpce pre Tree structure (Skóre a %B)
    cols = ('price', 'rsi_score', 'pct_b', 'next_update', 'rvi', 'rvi_sig', 'p_dist_bb', 'status', 'action', 'pl_signal', 'breakdown')
    tree = ttk.Treeview(t_frame, columns=cols, show='tree headings')
    
    tree._sort_states = {'#0': False, 'rsi_score': False}
    def _on_sort(col):
        reverse = tree._sort_states.get(col, False)
        sort_hunter_tree_parents(tree, col, reverse)
        tree._sort_states[col] = not reverse

    tree.heading('#0', text='Symbol / Timeframe', command=lambda: _on_sort('#0')); tree.column('#0', width=150, anchor='w')
    tree.heading('price', text='Cena'); tree.column('price', width=90, anchor='center')
    tree.heading('rsi_score', text='RSI / Skóre', command=lambda: _on_sort('rsi_score')); tree.column('rsi_score', width=100, anchor='center')
    tree.heading('pct_b', text='%B'); tree.column('pct_b', width=80, anchor='center')
    tree.heading('next_update', text='Dalšia akt.'); tree.column('next_update', width=80, anchor='center')
    tree.heading('rvi', text='RVI'); tree.column('rvi', width=90, anchor='center')
    tree.heading('rvi_sig', text='RVI Sig'); tree.column('rvi_sig', width=90, anchor='center')
    tree.heading('p_dist_bb', text='Pivot / %B'); tree.column('p_dist_bb', width=150, anchor='center')
    tree.heading('status', text='Stav'); tree.column('status', width=150, anchor='center')
    tree.heading('action', text='Akcia'); tree.column('action', width=180, anchor='center')
    tree.heading('pl_signal', text='P/L Signálu'); tree.column('pl_signal', width=100, anchor='center')
    tree.heading('breakdown', text='Rozklad'); tree.column('breakdown', width=220, anchor='w')

    tree.pack(side='left', fill='both', expand=True)
    sb = ttk.Scrollbar(t_frame, command=tree.yview); sb.pack(side='right', fill='y'); tree.configure(yscrollcommand=sb.set)
    
    tree.tag_configure('header', background='#cfd8dc', font=('Arial', 10, 'bold'))
    
    tree.tag_configure('buy', background='#c8e6c9') # Základný buy
    tree.tag_configure('short', background='#ffcdd2') # Základný short
    tree.tag_configure('alert', background='#fff9c4') # Varovanie
    
    # NOVÉ: Farebné kódovanie skóre (Gradient zelenej)
    tree.tag_configure('score_80_100', foreground='white')
    tree.tag_configure('score_50_79', foreground='#1b5e20')
    tree.tag_configure('score_20_49', foreground='#33691e')
    tree.tag_configure('score_0_19', foreground='#616161')
    tree.tag_configure('pctb_low', background='#1b5e20', foreground='white')
    tree.tag_configure('pctb_mid', background='#eceff1', foreground='#263238')
    tree.tag_configure('pctb_high', background='#b71c1c', foreground='white')
    tree.tag_configure('pctb_none', background='#f5f5f5', foreground='#455a64')
    tree.tag_configure('pctb_over', background='#ffebee', foreground='#b71c1c')
    tree.tag_configure('priority_short', foreground='#ff9800')
    tree.tag_configure('zone_hunt', foreground='#1b5e20')
    tree.tag_configure('zone_hold', foreground='#546e7a')
    tree.tag_configure('zone_risk', background='#ffcdd2', foreground='#b71c1c')
    tree.tag_configure('zone_neutral', foreground='#424242')
    tree.tag_configure('pl_profit', background='#c8e6c9')
    tree.tag_configure('pl_loss', background='#ffcdd2')
    state.hunter_tree, state.hunter_rsi_p, state.hunter_rvi_p, state.hunter_tf_v = tree, rsi_p, rvi_p, tf_v
    state.hunter_multi_tf_var = multi_tf_var
    def _force_refresh(event):
        item = tree.identify_row(event.y)
        if not item:
            return
        parent = tree.parent(item) or item
        sym = tree.item(parent, 'text')
        if not sym:
            return
        state.hunter_next_update[sym] = 0
        refresh_hunter(state, tree, state.hunter_rsi_p, state.hunter_rvi_p, state.hunter_tf_v, force=True, force_symbol=sym)
    tree.bind("<Double-1>", _force_refresh)
    state.root.after(1000, lambda: update_next_update_labels(state))
    
    footer = ttk.Frame(frame)
    footer.pack(fill='x')
    ttk.Button(footer, text="🏹 VYHĽADAŤ PRÍLEŽITOSTI", command=lambda: refresh_hunter(state, tree, rsi_p, rvi_p, tf_v, force=True)).pack(pady=10)
    return frame
