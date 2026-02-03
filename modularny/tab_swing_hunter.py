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
    'RSI', 'PercentB', 'SignalType', 'ExitPrice', 'FinalPL',
    'Zone', 'Trend', 'ScorePct', 'MACD_Cross', 'RVI_gt_Sig', 'PivotDist', 'Action'
]
LOG_FILE = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'swing_hunter_log.csv')
TRADE_PLAN_FILE = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'swing_trade_plans.csv')
MODEL_FILE = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'swing_model.json')
TRAIN_SCRIPT = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'scripts', 'swing_train_logreg.py')

def _ensure_log_file():
    if os.path.exists(LOG_FILE):
        return
    try:
        with open(LOG_FILE, 'w', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=LOG_FIELDNAMES)
            writer.writeheader()
    except Exception:
        pass


def _ensure_trade_plan_file():
    if os.path.exists(TRADE_PLAN_FILE):
        return
    try:
        with open(TRADE_PLAN_FILE, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow([
                'Timestamp', 'Symbol', 'Entry', 'SL', 'TP1', 'TP2', 'R_R',
                'Action', 'Strategy', 'Reason', 'OptionStrategy', 'OptionReason'
            ])
    except Exception:
        pass


def log_signal_entry(symbol, timeframe, entry_price, rsi, pct_b, signal_type,
                    zone="", trend="", score_pct=None, macd_cross=False, rvi_gt_sig=False, pivot_dist=None, action_text=""):
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
        'FinalPL': '',
        'Zone': zone,
        'Trend': trend,
        'ScorePct': f"{score_pct:.0f}" if score_pct is not None else '',
        'MACD_Cross': 1 if macd_cross else 0,
        'RVI_gt_Sig': 1 if rvi_gt_sig else 0,
        'PivotDist': f"{pivot_dist:+.2f}" if pivot_dist is not None else '',
        'Action': action_text
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


def recommend_strategy(summary):
    """Vrátane odporúčanej stratégie + dôvodu pre výťah/Trade plan"""
    zone = summary.get('zone', 'neutral')
    action = (summary.get('action') or '').upper()
    pct_b = summary.get('pct_b')
    rvi = summary.get('rvi')
    rvi_s = summary.get('rvi_s')
    macd = summary.get('macd')
    score_pct = summary.get('score_pct') or 0.0
    trend_label = summary.get('trend_label', '')
    trend_breakout = summary.get('trend_breakout', False)

    reason_parts = []
    if zone:
        reason_parts.append(zone.capitalize())
    if trend_label and trend_label != "—":
        reason_parts.append(trend_label)
    if pct_b is not None:
        reason_parts.append(f"%B {pct_b:.0f}%")

    is_risk = zone == 'risk' or "RIZIKO" in action or "VÝSTUP" in action or (pct_b is not None and pct_b > 80)
    if is_risk:
        reason = "Vysoké %B" if pct_b is not None and pct_b > 80 else "Riziková zóna"
        return "Risk/Exit", reason

    if pct_b is not None and pct_b < 30:
        extras = []
        if rvi is not None and rvi_s is not None and rvi > rvi_s:
            extras.append("RVI>Sig")
        if macd and macd.get('is_cross'):
            extras.append("MACD cross")
        reason = "Low %B"
        if extras:
            reason = f"{reason} ({', '.join(extras)})"
        return "Mean Reversion (Hunt)", reason

    if trend_breakout or (trend_label == 'Býk' and score_pct >= 70):
        reason = "MA200 breakout" if trend_breakout else "Bull trend"
        return "Trend Breakout", reason

    if score_pct >= 60:
        label = "Watchlist (high score)"
    else:
        label = "Watch & Wait"
    reason = " • ".join(reason_parts) if reason_parts else "Čakaj na potvrdenie"
    return label, reason


def recommend_option_strategy(summary):
    """Jednoduchý návrh opčnej stratégie podľa zóny/trendu"""
    zone = summary.get('zone', 'neutral')
    trend_label = summary.get('trend_label', '')
    trend_breakout = summary.get('trend_breakout', False)
    pct_b = summary.get('pct_b')
    action = (summary.get('action') or '').upper()

    if zone == 'risk' or "RIZIKO" in action or "VÝSTUP" in action:
        return "Zatvoriť/hedge", "Vyšší %B/exit – covered call alebo collar"

    if trend_breakout or trend_label == 'Býk':
        return "Call debit spread", "Trend BULL / breakout"

    if pct_b is not None and pct_b < 30:
        return "Bull put spread", "Mean reversion zóna (%B<30)"

    if trend_label == 'Bear':
        return "Bear call spread", "BEAR trend – hrať rezistenciu"

    return "Neutral calendar", "Neutrálna zóna – časové rozpady"


def predict_ml_score(summary, model):
    """Spočíta pravdepodobnosť úspechu pomocou uloženého modelu (logreg)."""
    if not model:
        return None
    vocab = model.get('vocab', {})
    weights = model.get('weights', [])
    if not vocab or not weights:
        return None

    def bucket_pctb(val):
        if val is None:
            return "pctb:n/a"
        if val < 30:
            return "pctb:<30"
        if val < 80:
            return "pctb:30-80"
        if val < 100:
            return "pctb:80-100"
        return "pctb:>100"

    def bucket_rsi(val):
        if val is None:
            return "rsi:n/a"
        if val < 30:
            return "rsi:<30"
        if val < 50:
            return "rsi:30-50"
        if val < 70:
            return "rsi:50-70"
        return "rsi:>=70"

    sig = (summary.get('action') or '').lower()
    if "strong buy" in sig:
        sig_b = "sig:strong_buy"
    elif "buy" in sig:
        sig_b = "sig:buy"
    elif "risk" in sig or "riziko" in sig:
        sig_b = "sig:risk"
    elif "take profit" in sig or "exit" in sig:
        sig_b = "sig:exit"
    else:
        sig_b = "sig:other"

    pctb_b = bucket_pctb(summary.get('pct_b'))
    rsi_b = bucket_rsi(summary.get('rsi'))
    tf = summary.get('timeframe', 'n/a')
    tf_b = f"tf:{tf}"

    feats = [pctb_b, rsi_b, sig_b, tf_b]
    vec = 0.0
    for f in feats:
        idx = vocab.get(f)
        if idx is not None and idx < len(weights):
            vec += weights[idx] * 1.0

    try:
        import math
        return 1 / (1 + math.exp(-vec))
    except Exception:
        return None

def save_trade_plan_to_file(symbol, plan_vars):
    _ensure_trade_plan_file()
    ts = datetime.now().isoformat()
    row = [
        ts,
        symbol,
        plan_vars['entry'].get(),
        plan_vars['sl'].get(),
        plan_vars['tp1'].get(),
        plan_vars['tp2'].get(),
        plan_vars['rr'].get(),
        plan_vars['action'].get(),
        plan_vars['strategy'].get(),
        plan_vars['reason'].get(),
        plan_vars.get('option_strategy', tk.StringVar(value="—")).get(),
        plan_vars.get('option_reason', tk.StringVar(value="—")).get()
    ]
    try:
        with open(TRADE_PLAN_FILE, 'a', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow(row)
    except Exception as e:
        messagebox.showerror("Trade plan", f"Nepodarilo sa uložiť plán:\n{e}")


def _load_model_file():
    if not os.path.exists(MODEL_FILE):
        return None
    try:
        with open(MODEL_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        print(f"⚠️ Nepodarilo sa načítať model {MODEL_FILE}: {e}")
        return None


def _train_model_async(state, notify=False, label=None):
    """Spustí tréning modelu v samostatnom vlákne a po úspechu načíta model."""
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    py = os.path.join(root, 'venv', 'bin', 'python3')
    if not os.path.exists(py):
        py = sys.executable

    def run():
        try:
            cmd = [py, TRAIN_SCRIPT]
            res = subprocess.run(cmd, capture_output=True, text=True, cwd=root, timeout=60)
            if res.returncode == 0:
                state.hunter_model = _load_model_file()
                msg = res.stdout.strip() or "ML model bol pretrénovaný."
                if notify:
                    messagebox.showinfo("ML model", msg)
                else:
                    print(msg)
                if label:
                    state.root.after(0, lambda: label.config(text="ML model: OK", foreground="green"))
            else:
                err = res.stderr.strip() or res.stdout.strip()
                if notify:
                    messagebox.showerror("ML model", f"Tréning zlyhal:\n{err}")
                else:
                    print(f"ML tréning zlyhal: {err}")
        except Exception as e:
            if notify:
                messagebox.showerror("ML model", f"Tréning zlyhal:\n{e}")
            else:
                print(f"ML tréning zlyhal: {e}")

    threading.Thread(target=run, daemon=True).start()


def _auto_train_model_if_needed(state):
    """Ak model chýba alebo je starší ako 1 deň a máme log, spustí tréning."""
    if not os.path.exists(LOG_FILE):
        return
    model_missing = not os.path.exists(MODEL_FILE)
    stale = False
    if not model_missing:
        try:
            age = time.time() - os.path.getmtime(MODEL_FILE)
            stale = age > 86400  # 1 deň
        except Exception:
            stale = True
    if model_missing or stale:
        # Pri auto-tréningu nechceme popupy, aby neblokovali štart
        _train_model_async(state, notify=False, label=getattr(state, 'hunter_status_label', None))


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


def _detect_ma200_cross(df, lookback=3):
    """Zistí, či cena prekrížila MA200 smerom nahor v posledných lookback sviečkach"""
    if df is None or df.empty or len(df) < 2:
        return False
    recent = df.tail(lookback + 1)
    if len(recent) < 2:
        return False
    curr = recent.iloc[-1]
    if curr['close'] <= curr['sma200']:
        return False
    prev_candidates = recent.iloc[:-1].iloc[::-1][:lookback]
    for prev in prev_candidates.itertuples():
        if prev.close <= prev.sma200:
            return True
    return False


def calculate_ma200_metrics(candles, length=200):
    """Vypočíta SMA200 a pomocné metriky (smer, cross)"""
    if len(candles) < length:
        return None
    df = pd.DataFrame(candles)
    sma_series = ta.sma(df['close'], length=length)
    if sma_series is None:
        return None
    df['sma200'] = sma_series
    valid = df.dropna(subset=['sma200'])
    if valid.empty:
        return None
    last = valid.iloc[-1]
    slope_down = False
    if len(valid) >= 6:
        slope_down = last['sma200'] < valid.iloc[-6]['sma200']
    cross_up = _detect_ma200_cross(valid, lookback=3)
    return {
        'value': last['sma200'],
        'slope_down': slope_down,
        'cross_up': cross_up,
        'frame': valid
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
        breakdown['Piv'] = breakdown.get('Piv', 0) + 2

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

    if not hasattr(state, 'hunter_symbol_summaries'):
        state.hunter_symbol_summaries = {}

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
    if "1 day" not in selected_tfs:
        selected_tfs.append("1 day")  # always fetch daily for MA200/pivots
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
                current_tf = tf_var.get()
                if "week" in current_tf:
                    pivot_tf = "1 week"
                    pivot_dur = "3 M"
                elif current_tf == "1 day":
                    pivot_tf = "1 week"
                    pivot_dur = "1 M"
                else:
                    pivot_tf = "1 day"
                    pivot_dur = "10 D"
                
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
                if "15 mins" in tf:
                    dur = "5 D"
                elif "1 hour" in tf:
                    dur = "25 D"
                elif "4 hours" in tf:
                    dur = "60 D"
                elif tf == "1 day":
                    dur = "260 D"
                elif "week" in tf:
                    dur = "2 Y"
                elif "day" in tf:
                    dur = "1 Y"

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

            daily_info = results_tf.get('1 day')
            ma200_info = None
            if daily_info and daily_info.get('candles'):
                ma200_info = calculate_ma200_metrics(daily_info['candles'])

            ma200_value = ma200_info.get('value') if ma200_info else None
            has_ma = ma200_value is not None and ma200_value > 0
            price_above_ma = price >= ma200_value if has_ma else True
            is_bearish_trend = has_ma and price < ma200_value
            trend_text = "—"
            trend_tag = None
            trend_label = "—"
            if has_ma:
                dist_pct = ((price - ma200_value) / ma200_value) * 100
                trend_label = 'Býk' if price_above_ma else 'Bear'
                trend_text = f"{trend_label} {dist_pct:+.1f}%"
                if is_bearish_trend:
                    trend_tag = 'trend_bear'
                else:
                    trend_tag = 'trend_breakout' if ma200_info.get('cross_up') and price_above_ma else 'trend_bull'
            
            # Logika Súladu a finálneho signálu pre Rodiča
            status, action, tag = "Neutral", "Čakať", ""
            
            rsi_vals = {tf: results_tf.get(tf, {}).get('rsi', 50.0) for tf in ["15 mins", "1 hour", "4 hours", "1 day", "1 week"]}
            
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
                
                p_dist_str = f"{best_level[0]} ({min_dist_pct:+.2f}%)" if best_level else "—"
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
            adjusted_score = swing_score
            if has_ma:
                if is_bearish_trend:
                    adjusted_score *= 0.6
                elif ma200_info.get('slope_down'):
                    adjusted_score *= 0.9
            adjusted_score = max(0.0, min(10.0, adjusted_score))
            score_pct = score_to_percent(adjusted_score)
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
            pivot_bb_text = pivot_label
            interval = get_dynamic_interval(score_pct, zone, pct_b_value)
            next_update_time = time.time() + interval
            state.hunter_next_update[sym] = next_update_time
            next_update_text = format_mmss(interval)

            strong_macd = bool(main_macd and main_macd.get('is_cross'))
            rvi_bull = main_data['rvi'] > main_data['rvi_s']
            rvi_bear = main_data['rvi'] < main_data['rvi_s']
            macd_falling = bool(main_macd and main_macd.get('macd') < main_macd.get('signal', 0))

            def bearish_label():
                return "Bearish Rebound" if score_pct >= 40 else "Sledovať rezistenciu"

            trend_breakout = has_ma and ma200_info and ma200_info.get('cross_up') and price_above_ma
            action = "Neutral"
            if trend_breakout:
                action = "Trend Breakout"
            elif is_bearish_trend:
                action = bearish_label()
            elif zone == 'hunt':
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

            entry_actions = {"🚀 STRONG BUY", "✅ VHODNÝ VSTUP", "Trend Breakout"}
            if action in entry_actions:
                if not active_signal:
                    entry_time = log_signal_entry(
                        sym, main_tf, price,
                        main_data['rsi'], pct_b_value,
                        action,
                        zone=zone,
                        trend=trend_label,
                        score_pct=score_pct,
                        macd_cross=bool(main_macd and main_macd.get('is_cross')),
                        rvi_gt_sig=rvi_bull,
                        pivot_dist=score_dist,
                        action_text=action
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
                          next_up=next_update_text, trend_val=trend_text,
                          trend_label_val=trend_label, main_data_param=main_data,
                          score_pct_val=score_pct, pivots_param=pivots,
                          main_bb_param=main_bb, macd_param=main_macd,
                          score_level_val=score_level, score_dist_val=score_dist,
                          has_ma_param=has_ma, ma200_value_param=ma200_value,
                          pct_b_value_param=pct_b_value, trend_breakout_flag=trend_breakout):
                # Nájsť rodičovský riadok
                parent_id = None
                for item in tree.get_children():
                    if tree.item(item, 'text') == s:
                        parent_id = item
                        break
                
                # Zobrazenie skóre v stĺpci RSI rodiča (upravíme Treeview neskôr)
                ml_prob = summary.get('ml_prob') if 'summary' in locals() else None
                ml_text = f"{ml_prob*100:.0f}%" if isinstance(ml_prob, (int, float)) else "—"
                vals = (
                    f"{p:.2f}",
                    trend_val,
                    sc_text,
                    pct_b_cell,
                    next_up,
                    f"{main_data_param['rvi']:.4f}",
                    f"{main_data_param['rvi_s']:.4f}",
                    pivot_bb,
                    st,
                    ac,
                    ml_text,
                    bk_text,
                    pl_disc
                )
                
                parent_tags = [score_tag]
                if pct_tag:
                    parent_tags.append(pct_tag)
                if z_tag:
                    parent_tags.append(z_tag)
                if pl_t:
                    parent_tags.append(pl_t)
                if trend_tag:
                    parent_tags.append(trend_tag)
                if s in getattr(state, 'hunter_pinned_symbols', []):
                    parent_tags.append('pinned')
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
                
                for tf_name in ["15 mins", "1 hour", "4 hours", "1 day", "1 week"]:
                    if tf_name in res_tf:
                        d = res_tf[tf_name]
                        if tf_name in ('1 day', '1 week'):
                            tf_checkbox = state.hunter_tf_vars.get(tf_name) if hasattr(state, 'hunter_tf_vars') else None
                            if tf_checkbox and not tf_checkbox.get():
                                continue
                        bb_value = f"{d['bb']['pct_b']:.1f}%" if d.get('bb') else "—"
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
                        pivot_label = "S" if zone_name != 'risk' else "P"
                        trend_letter = trend_label if trend_label != "—" else ""
                        tree.insert(parent_id, tk.END, text=f"  {tf_name}",
                                    values=(
                                        "",
                                        trend_letter,
                                        f"{d['rsi']:.1f}",
                                        bb_value,
                                        "",
                                        f"{d['rvi']:.4f}",
                                        f"{d['rvi_s']:.4f}",
                                        p_dist_str,
                                        d['status'],
                                        child_action,
                                        "",
                                        "",
                                        ""
                                    ),
                                    tags=tuple(child_tags))
                summary = {
                    'symbol': s,
                    'price': p,
                    'score_pct': score_pct_val,
                    'score_level': score_level_val,
                    'score_dist': score_dist_val,
                    'zone': zone_name,
                    'action': ac,
                    'status': st,
                    'trend_text': trend_val,
                    'trend_label': trend_label_val,
                    'trend_breakout': trend_breakout_flag,
                    'has_ma': has_ma_param,
                    'ma200_value': ma200_value_param,
                    'pct_b': pct_b_value_param,
                    'pivot_label': pivot_bb,
                    'pivots': pivots_param,
                    'main_bb': main_bb_param,
                    'macd': macd_param,
                    'rsi': main_data_param['rsi'],
                    'rvi': main_data_param['rvi'],
                    'rvi_s': main_data_param['rvi_s'],
                    'breakdown': bk_text,
                    'next_update': next_up,
                    'zone_tag': z_tag,
                    'timeframe': main_tf
                }
                strategy_label, strategy_reason = recommend_strategy(summary)
                summary['strategy_label'] = strategy_label
                summary['strategy_reason'] = strategy_reason
                opt_label, opt_reason = recommend_option_strategy(summary)
                summary['option_strategy'] = opt_label
                summary['option_reason'] = opt_reason
                ml_prob = predict_ml_score(summary, getattr(state, 'hunter_model', None))
                summary['ml_prob'] = ml_prob
                state.hunter_symbol_summaries[s] = summary

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


def force_refresh_symbol_now(state, symbol):
    if not symbol:
        return
    state.hunter_next_update[symbol] = 0
    refresh_hunter(
        state, getattr(state, 'hunter_tree', None),
        getattr(state, 'hunter_rsi_p', None),
        getattr(state, 'hunter_rvi_p', None),
        getattr(state, 'hunter_tf_v', None),
        force=True, force_symbol=symbol
    )

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
    tf_v = tk.StringVar(value="4 hours"); ttk.Combobox(ctrl, textvariable=tf_v, values=["15 mins", "1 hour", "4 hours", "1 day", "1 week"], width=10).pack(side='left', padx=5)
    
    tf_opts_frame = ttk.Frame(ctrl)
    tf_opts_frame.pack(fill='x', pady=(10, 0))
    ttk.Label(tf_opts_frame, text="TF analýza:").pack(side='left', padx=5)
    state.hunter_tf_vars = {}
    for tf_name in ["15 mins", "1 hour", "4 hours", "1 day", "1 week"]:
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
    state.hunter_last_scores = {}
    state.hunter_last_update = {}
    state.hunter_background_refresh_interval = 3600
    state.hunter_active_signals = {}
    state.hunter_next_update = {}
    state.hunter_base_tags = {}

    t_frame = ttk.Frame(frame); t_frame.pack(fill='both', expand=True, pady=10)
    # Upravené stĺpce pre Tree structure (Skóre a %B)
    cols = ('price', 'trend', 'rsi_score', 'pct_b', 'next_update', 'rvi', 'rvi_sig', 'p_dist_bb', 'status', 'action', 'ml_prob', 'breakdown', 'pl_signal')
    tree = ttk.Treeview(t_frame, columns=cols, show='tree headings')
    
    tree._sort_states = {'#0': False, 'rsi_score': False}
    def _on_sort(col):
        reverse = tree._sort_states.get(col, False)
        sort_hunter_tree_parents(tree, col, reverse)
        tree._sort_states[col] = not reverse

    tree.heading('#0', text='Sym/Tim', command=lambda: _on_sort('#0')); tree.column('#0', width=150, anchor='w')
    tree.heading('price', text='Cena'); tree.column('price', width=90, anchor='center')
    tree.heading('trend', text='T(MA200)'); tree.column('trend', width=140, anchor='center')
    tree.heading('rsi_score', text='RSI/SK', command=lambda: _on_sort('rsi_score')); tree.column('rsi_score', width=100, anchor='center')
    tree.heading('pct_b', text='%B'); tree.column('pct_b', width=80, anchor='center')
    tree.heading('next_update', text='Dalšia akt.'); tree.column('next_update', width=80, anchor='center')
    tree.heading('rvi', text='RVI'); tree.column('rvi', width=90, anchor='center')
    tree.heading('rvi_sig', text='RVI Sig'); tree.column('rvi_sig', width=90, anchor='center')
    tree.heading('p_dist_bb', text='Pivot'); tree.column('p_dist_bb', width=120, anchor='center')
    tree.heading('status', text='Stav'); tree.column('status', width=150, anchor='center')
    tree.heading('action', text='Akcia'); tree.column('action', width=160, anchor='center')
    tree.heading('ml_prob', text='ML P(%)'); tree.column('ml_prob', width=80, anchor='center')
    tree.heading('breakdown', text='Rozklad'); tree.column('breakdown', width=200, anchor='w')
    tree.heading('pl_signal', text='P/L Signálu'); tree.column('pl_signal', width=100, anchor='center')

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
    tree.tag_configure('trend_bull', background='#e8f5e9')
    tree.tag_configure('trend_bear', background='#ffebee')
    tree.tag_configure('trend_breakout', background='#ffe082', foreground='#212121')
    tree.tag_configure('pinned', background='#fff8e1')
    if not hasattr(state, 'hunter_pinned_symbols'):
        state.hunter_pinned_symbols = []
    if not hasattr(state, 'hunter_symbol_summaries'):
        state.hunter_symbol_summaries = {}
    if not hasattr(state, 'hunter_trade_plan_windows'):
        state.hunter_trade_plan_windows = {}
    state.hunter_extract_window = getattr(state, 'hunter_extract_window', None)
    state.hunter_extract_refresh_job = getattr(state, 'hunter_extract_refresh_job', None)
    state.hunter_extract_tree = getattr(state, 'hunter_extract_tree', None)
    state.hunter_extract_show_pin_var = getattr(state, 'hunter_extract_show_pin_var', tk.BooleanVar(value=False))
    state.hunter_model = _load_model_file()
    _auto_train_model_if_needed(state)
    if not hasattr(state, 'hunter_close_hook_set'):
        def _on_close():
            try:
                _train_model_async(state, notify=False, label=getattr(state, 'hunter_status_label', None))
            finally:
                state.root.destroy()
        state.root.protocol("WM_DELETE_WINDOW", _on_close)
        state.hunter_close_hook_set = True

    def build_extract_rows(show_only_pins=False):
        pinned = set(getattr(state, 'hunter_pinned_symbols', []))
        summaries = getattr(state, 'hunter_symbol_summaries', {})
        scores = getattr(state, 'hunter_last_scores', {})
        candidates = set(summaries.keys()) | pinned
        rows = []
        for sym in candidates:
            summary = summaries.get(sym)
            score = summary.get('score_pct') if summary else scores.get(sym)
            if show_only_pins and sym not in pinned:
                continue
            if sym not in pinned and (score is None or score < 60):
                continue
            rows.append((score if score is not None else -1, sym, summary))
        rows.sort(key=lambda t: t[0], reverse=True)
        return rows

    def schedule_extract_refresh():
        window = state.hunter_extract_window
        if not window or not window.winfo_exists() or not window.winfo_viewable():
            return
        if state.hunter_extract_refresh_job:
            try:
                window.after_cancel(state.hunter_extract_refresh_job)
            except Exception:
                pass
        state.hunter_extract_refresh_job = window.after(5000, refresh_extract_tree)

    def refresh_extract_tree(force=False):
        window = state.hunter_extract_window
        tree = state.hunter_extract_tree
        if not window or not window.winfo_exists() or not window.winfo_viewable() or not tree:
            return
        tree.delete(*tree.get_children())
        rows = build_extract_rows(state.hunter_extract_show_pin_var.get())
        if not rows:
            tree.insert('', tk.END, values=('—', '—', '—', '—', '—', '—', '—', '—', '—', '—', '—', 'Čaká na dáta'), tags=('zone_neutral',))
            update_extract_selection_buttons()
            schedule_extract_refresh()
            return
        for _, sym, summary in rows:
            summary = summary or {
                'symbol': sym,
                'score_pct': getattr(state, 'hunter_last_scores', {}).get(sym),
                'zone': 'neutral',
                'action': 'Čaká',
                'strategy_label': '—',
                'strategy_reason': 'Čaká na dáta',
                'option_strategy': '—',
                'option_reason': 'Čaká na dáta',
                'trend_text': '—',
                'pivot_label': '—'
            }
            price = summary.get('price')
            score = summary.get('score_pct')
            pct_b = summary.get('pct_b')
            zone = summary.get('zone', 'neutral')
            tags = []
            if zone == 'risk':
                tags.append('zone_risk')
            elif zone == 'hunt':
                tags.append('zone_hunt')
            elif zone == 'hold':
                tags.append('zone_hold')
            if sym in getattr(state, 'hunter_pinned_symbols', []):
                tags.append('pinned')
            display_price = f"{price:.2f}" if price is not None else "—"
            display_score = f"{score:.0f}%" if score is not None else "—"
            display_pctb = f"{pct_b:.1f}%" if pct_b is not None else "—"
            ml_prob = summary.get('ml_prob')
            ml_text = f"{ml_prob*100:.0f}%" if ml_prob is not None else "—"
            extract_tree_values = (
                sym,
                display_price,
                display_score,
                zone.capitalize(),
                summary.get('trend_text', '—'),
                display_pctb,
                summary.get('pivot_label', '—'),
                summary.get('action', '—'),
                summary.get('strategy_label', '—'),
                summary.get('option_strategy', '—'),
                ml_text,
                summary.get('option_reason', summary.get('strategy_reason', 'Čaká na dáta'))
            )
            tree.insert('', tk.END, iid=sym, values=extract_tree_values, tags=tuple(dict.fromkeys(tags)))
        update_extract_selection_buttons()
        schedule_extract_refresh()
        state.hunter_extract_tree._sort_state = {'col': None, 'reverse': False}

    def update_extract_selection_buttons(event=None):
        tree = state.hunter_extract_tree
        btn = getattr(state, 'hunter_extract_trade_btn', None)
        if not tree or not btn:
            return
        sel = tree.selection()
        btn.config(state='normal' if sel else 'disabled')

    def handle_extract_double_click(event):
        tree = state.hunter_extract_tree
        if not tree:
            return
        item = tree.identify_row(event.y)
        if not item:
            return
        force_refresh_symbol_now(state, item)

    def open_selected_trade_plan():
        tree = state.hunter_extract_tree
        if not tree:
            return
        sel = tree.selection()
        if not sel:
            return
        symbol = sel[0]
        summary = state.hunter_symbol_summaries.get(symbol, {'symbol': symbol})
        open_trade_plan_window(state, summary)

    def open_extract_window():
        existing = state.hunter_extract_window
        if existing and existing.winfo_exists():
            existing.deiconify()
            existing.lift()
            existing.focus_force()
            state.hunter_extract_show_pin_var.set(state.hunter_extract_show_pin_var.get())
            refresh_extract_tree()
            return
        window = tk.Toplevel(state.root)
        window.title("Swing Hunter Výťah")
        window.geometry("960x360")
        state.hunter_extract_window = window
        window.protocol("WM_DELETE_WINDOW", window.withdraw)

        control_frame = ttk.Frame(window, padding=8)
        control_frame.pack(fill='x')
        ttk.Checkbutton(control_frame, text="Zobraziť len pin", variable=state.hunter_extract_show_pin_var,
                        command=lambda: refresh_extract_tree(force=True)).pack(side='left')
        ttk.Button(control_frame, text="🔄 Refresh", command=lambda: refresh_extract_tree(force=True)).pack(side='left', padx=5)
        ttk.Button(control_frame, text="🔄 Pretrénovať ML", command=lambda: _train_model_async(state, notify=True)).pack(side='left', padx=5)
        trade_btn = ttk.Button(control_frame, text="📝 Trade plan", command=open_selected_trade_plan, state='disabled')
        trade_btn.pack(side='right')
        state.hunter_extract_trade_btn = trade_btn

        tree_frame = ttk.Frame(window)
        tree_frame.pack(fill='both', expand=True, padx=5, pady=5)
        extract_cols = ('symbol', 'price', 'score', 'zone', 'trend', 'pct_b', 'pivot', 'action', 'strategy', 'option', 'ml_prob', 'reason')
        extract_tree = ttk.Treeview(tree_frame, columns=extract_cols, show='headings')
        heading_labels = ["Symbol", "Cena", "Skóre", "Zóna", "T(MA200)", "%B", "Pivot", "Akcia", "Stratégia", "Opcie", "ML P(%)", "Dôvod"]
        for col, label in zip(extract_cols, heading_labels):
            extract_tree.heading(col, text=label, command=lambda c=col: sort_extract_tree(c))
            extract_tree.column(col, width=80, anchor='center')
        extract_tree.column('symbol', width=90, anchor='w')
        extract_tree.column('reason', width=240, anchor='w')
        extract_tree.pack(side='left', fill='both', expand=True)
        vsb = ttk.Scrollbar(tree_frame, orient='vertical', command=extract_tree.yview)
        vsb.pack(side='right', fill='y')
        extract_tree.configure(yscrollcommand=vsb.set)
        extract_tree.bind("<<TreeviewSelect>>", update_extract_selection_buttons)
        extract_tree.bind("<Double-1>", handle_extract_double_click)

        state.hunter_extract_tree = extract_tree
        refresh_extract_tree()

    def sort_extract_tree(col):
        tree = state.hunter_extract_tree
        if not tree:
            return
        data = []
        for iid in tree.get_children():
            vals = tree.item(iid, 'values')
            data.append((iid, vals))
        reverse = False
        sort_state = getattr(tree, '_sort_state', {'col': None, 'reverse': False})
        if sort_state.get('col') == col:
            reverse = not sort_state.get('reverse', False)
        tree._sort_state = {'col': col, 'reverse': reverse}

        def parse_val(v, idx):
            if idx in (1, 2, 4, 5, 10):  # numeric columns (price, score, trend?, pct_b, ml_prob)
                try:
                    return float(str(v).replace('%', '').replace('+', '').strip())
                except:
                    return -1e9
            return str(v).lower()

        col_index = extract_cols.index(col)
        data.sort(key=lambda item: parse_val(item[1][col_index], col_index), reverse=reverse)
        for idx, (iid, _) in enumerate(data):
            tree.move(iid, '', idx)

    def toggle_pin_symbol(sym):
        pinned = getattr(state, 'hunter_pinned_symbols', [])
        if sym in pinned:
            pinned = [p for p in pinned if p != sym]
        else:
            pinned = pinned + [sym]
        state.hunter_pinned_symbols = pinned
        state.save_settings_file()
        if state.hunter_extract_window and state.hunter_extract_window.winfo_exists():
            refresh_extract_tree(force=True)
        for item in tree.get_children():
            if tree.item(item, 'text') == sym:
                tags = list(tree.item(item, 'tags'))
                if sym in pinned:
                    if 'pinned' not in tags:
                        tags.append('pinned')
                else:
                    tags = [t for t in tags if t != 'pinned']
                tree.item(item, tags=tuple(dict.fromkeys(tags)))
                break

    def show_pin_menu(event):
        item = tree.identify_row(event.y)
        if not item or tree.parent(item):
            return
        sym = tree.item(item, 'text')
        if not sym:
            return
        pinned = getattr(state, 'hunter_pinned_symbols', [])
        label = "📌 Pin" if sym not in pinned else "📍 Unpin"
        menu = tk.Menu(tree, tearoff=0)
        menu.add_command(label=label, command=lambda sym=sym: toggle_pin_symbol(sym))
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()

    tree.bind("<Button-3>", show_pin_menu)
    ttk.Button(highlight_frame, text="📋 Výťah", command=open_extract_window).pack(padx=2, pady=2)
    ttk.Button(highlight_frame, text="🏹 VYHĽADAŤ PRÍLEŽITOSTI", command=lambda: refresh_hunter(state, state.hunter_tree, state.hunter_rsi_p, state.hunter_rvi_p, state.hunter_tf_v, force=True)).pack(padx=2, pady=2)
    state.hunter_tree, state.hunter_rsi_p, state.hunter_rvi_p, state.hunter_tf_v = tree, rsi_p, rvi_p, tf_v
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


def refresh_trade_plan_vars(window, symbol, summary):
    plan_vars = getattr(window, 'plan_vars', None)
    if not plan_vars:
        return
    data = summary or {}

    def _fmt(val):
        return f"{val:.2f}" if isinstance(val, (int, float)) else ("—" if val is None else str(val))

    entry = data.get('price')
    pivots = data.get('pivots') or {}
    bb = data.get('main_bb') or {}
    sl = pivots.get('S1') or pivots.get('S2') or (entry * 0.985 if entry else None)
    tp1 = pivots.get('P') or bb.get('mid') or entry
    tp2 = bb.get('upper')
    rr_val = None
    if entry and sl and tp1 and entry != sl:
        rr_val = (tp1 - entry) / abs(entry - sl)

    plan_vars['entry'].set(_fmt(entry))
    plan_vars['sl'].set(_fmt(sl))
    plan_vars['tp1'].set(_fmt(tp1))
    plan_vars['tp2'].set(_fmt(tp2))
    plan_vars['rr'].set(f"{rr_val:.2f}:1" if rr_val else "—")
    plan_vars['action'].set(data.get('action', '—'))
    plan_vars['strategy'].set(data.get('strategy_label', '—'))
    plan_vars['reason'].set(data.get('strategy_reason', '—'))
    plan_vars['option_strategy'].set(data.get('option_strategy', '—'))
    plan_vars['option_reason'].set(data.get('option_reason', data.get('strategy_reason', '—')))
    ml_prob = data.get('ml_prob')
    if ml_prob is not None:
        plan_vars['ml_prob'].set(f"{ml_prob*100:.0f}%")
    else:
        plan_vars['ml_prob'].set("—")


def open_trade_plan_window(state, summary):
    symbol = summary.get('symbol')
    if not symbol:
        return
    plan_windows = getattr(state, 'hunter_trade_plan_windows', {})
    existing = plan_windows.get(symbol)
    if existing and existing.winfo_exists():
        existing.lift()
        existing.focus_force()
        refresh_trade_plan_vars(existing, symbol, state.hunter_symbol_summaries.get(symbol, summary))
        return

    window = tk.Toplevel(state.root)
    window.title(f"Trade plan – {symbol}")
    window.geometry("360x320")
    window.transient(state.root)
    state.hunter_trade_plan_windows[symbol] = window

    plan_vars = {
        'entry': tk.StringVar(value="—"),
        'sl': tk.StringVar(value="—"),
        'tp1': tk.StringVar(value="—"),
        'tp2': tk.StringVar(value="—"),
        'rr': tk.StringVar(value="—"),
        'action': tk.StringVar(value="—"),
        'strategy': tk.StringVar(value="—"),
        'reason': tk.StringVar(value="—"),
        'option_strategy': tk.StringVar(value="—"),
        'option_reason': tk.StringVar(value="—"),
        'ml_prob': tk.StringVar(value="—")
    }

    window.plan_vars = plan_vars

    info_frame = ttk.Frame(window, padding=10)
    info_frame.pack(fill='x')
    for idx, (label, key) in enumerate([
        ("Entry:", "entry"),
        ("SL:", "sl"),
        ("TP1:", "tp1"),
        ("TP2:", "tp2"),
        ("R:R:", "rr"),
        ("Akcia:", "action"),
        ("Stratégia:", "strategy")
    ]):
        ttk.Label(info_frame, text=label).grid(row=idx, column=0, sticky='w', pady=2)
        ttk.Label(info_frame, textvariable=plan_vars[key]).grid(row=idx, column=1, sticky='e', padx=(5, 0))

    ttk.Label(window, text="Dôvod:", font=('Arial', 9, 'bold')).pack(anchor='w', padx=10, pady=(10, 0))
    ttk.Label(window, textvariable=plan_vars['reason'], wraplength=320, justify='left').pack(fill='x', padx=10)
    ttk.Label(window, text="ML P(úspech):", font=('Arial', 9, 'bold')).pack(anchor='w', padx=10, pady=(8, 0))
    ttk.Label(window, textvariable=plan_vars['ml_prob']).pack(anchor='w', padx=10)

    btn_frame = ttk.Frame(window, padding=(10, 5))
    btn_frame.pack(fill='x')

    def refresh_plan():
        force_refresh_symbol_now(state, symbol)
        state.root.after(1500, lambda: refresh_trade_plan_vars(window, symbol, state.hunter_symbol_summaries.get(symbol, summary)))

    ttk.Button(btn_frame, text="🔄 Force refresh", command=refresh_plan).pack(side='left')
    ttk.Button(btn_frame, text="💾 Uložiť plán", command=lambda: save_trade_plan_to_file(symbol, plan_vars)).pack(side='left', padx=5)

    def on_close():
        plan_windows.pop(symbol, None)
        window.destroy()

    ttk.Button(btn_frame, text="Zavrieť", command=on_close).pack(side='right')
    window.protocol("WM_DELETE_WINDOW", on_close)

    refresh_trade_plan_vars(window, symbol, state.hunter_symbol_summaries.get(symbol, summary))
