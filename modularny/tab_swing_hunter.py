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
import numpy as np
from datetime import datetime
import pandas as pd
import pandas_ta as ta

try:
    import matplotlib.pyplot as plt
    import matplotlib.patches as patches
    from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
    from matplotlib.figure import Figure
    MATPLOTLIB_AVAILABLE = True
except ImportError:
    MATPLOTLIB_AVAILABLE = False

SCORE_FILTER_MAP = {
    "Žiadny filter": 0.0,
    "≥40 %": 40.0,
    "≥50 %": 50.0,
    "≥80 %": 80.0
}

ADX_FILTER_MAP = {
    "Žiadny filter": 0.0,
    "≥20 (Mierny)": 20.0,
    "≥25 (Silný)": 25.0,
    "≥30 (V. silný)": 30.0
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
        reason = "MV zóna"
        if extras:
            reason = f"{reason} ({', '.join(extras)})"
        return "MeanRev", reason

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
        return "Bull put spread", "MV zóna (%B<30)"

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


def load_saved_trade_plans():
    _ensure_trade_plan_file()
    rows = []
    try:
        with open(TRADE_PLAN_FILE, 'r', newline='', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                rows.append(row)
    except Exception:
        pass
    return rows


def apply_saved_plan_to_vars(plan_vars, row):
    if not plan_vars or not row:
        return
    mapping = {
        'entry': 'Entry',
        'sl': 'SL',
        'tp1': 'TP1',
        'tp2': 'TP2',
        'rr': 'R_R',
        'action': 'Action',
        'strategy': 'Strategy',
        'reason': 'Reason',
        'option_strategy': 'OptionStrategy',
        'option_reason': 'OptionReason'
    }
    for key, column in mapping.items():
        val = row.get(column, '') or ''
        plan_vars[key].set(val if val.strip() else "—")
    ml_var = plan_vars.get('ml_prob')
    if ml_var:
        ml_var.set("—")


def open_saved_trade_plan_browser(state, plan_vars):
    existing = getattr(state, 'hunter_saved_plans_window', None)
    if existing and existing.winfo_exists():
        existing.deiconify()
        existing.lift()
        existing.focus_force()
        return

    window = tk.Toplevel(state.root)
    window.title("Uložené trade plány")
    window.geometry("720x360")
    window.transient(state.root)
    state.hunter_saved_plans_window = window

    cols = ('timestamp', 'symbol', 'entry', 'sl', 'tp1', 'tp2', 'rr', 'action', 'strategy', 'reason')
    tree_frame = ttk.Frame(window)
    tree_frame.pack(fill='both', expand=True, padx=10, pady=(10, 0))
    tree = ttk.Treeview(tree_frame, columns=cols, show='headings', height=10)
    labels = ["Čas", "Symbol", "Entry", "SL", "TP1", "TP2", "R:R", "Akcia", "Stratégia", "Dôvod"]
    for col, label in zip(cols, labels):
        tree.heading(col, text=label)
        tree.column(col, anchor='center')
    tree.column('reason', width=260, anchor='w')
    tree.pack(side='left', fill='both', expand=True)
    vsb = ttk.Scrollbar(tree_frame, orient='vertical', command=tree.yview)
    vsb.pack(side='right', fill='y')
    tree.configure(yscrollcommand=vsb.set)

    tree.saved_plan_data = {}

    csv_column_map = {
        'timestamp': 'Timestamp',
        'symbol': 'Symbol',
        'entry': 'Entry',
        'sl': 'SL',
        'tp1': 'TP1',
        'tp2': 'TP2',
        'rr': 'R_R',
        'action': 'Action',
        'strategy': 'Strategy',
        'reason': 'Reason'
    }

    btn_frame = ttk.Frame(window, padding=10)
    btn_frame.pack(fill='x')

    def refresh_saved_plans():
        rows = load_saved_trade_plans()
        tree.delete(*tree.get_children())
        tree.saved_plan_data.clear()
        for idx, row in enumerate(rows):
            iid = f"plan_{idx}"
            tree.saved_plan_data[iid] = row
            values = tuple((row.get(csv_column_map.get(col, col), '') or '—') for col in cols)
            tree.insert('', tk.END, iid=iid, values=values)
        load_btn.config(state='disabled')

    def load_selected_plan():
        sel = tree.selection()
        if not sel:
            return
        row = tree.saved_plan_data.get(sel[0])
        if not row:
            return
        apply_saved_plan_to_vars(plan_vars, row)
        window.focus_force()

    load_btn = ttk.Button(btn_frame, text="Načítať do aktuálneho plánu", command=load_selected_plan, state='disabled')
    load_btn.pack(side='left')
    ttk.Button(btn_frame, text="🔄 Obnoviť", command=refresh_saved_plans).pack(side='left', padx=5)
    ttk.Button(btn_frame, text="Zavrieť", command=window.destroy).pack(side='right')

    def on_selection(evt):
        load_btn.config(state='normal' if tree.selection() else 'disabled')

    tree.bind("<<TreeviewSelect>>", on_selection)
    tree.bind("<Double-1>", lambda e: load_selected_plan())

    def on_close():
        state.hunter_saved_plans_window = None
        window.destroy()

    window.protocol("WM_DELETE_WINDOW", on_close)

    refresh_saved_plans()
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


def calculate_atr(candles, period=14):
    """Vypočíta ATR pre dané sviečky."""
    if len(candles) < period + 1:
        return None
    trs = []
    for i in range(1, len(candles)):
        current = candles[i]
        prev = candles[i - 1]
        high = current['high']
        low = current['low']
        close_prev = prev['close']
        tr = max(
            high - low,
            abs(high - close_prev),
            abs(low - close_prev)
        )
        trs.append(tr)
    if len(trs) < period:
        return None
    atr = sum(trs[-period:]) / period
    return atr

def calculate_adx_dmi(candles, period=14):
    """
    Vypočíta ADX, +DI a -DI (Average Directional Index).
    Standardná perióda je 14.
    """
    if len(candles) < period * 2: # Potrebujeme aspoň 2x periódu pre vyhladenie
        return 0.0, 0.0, 0.0

    trs = []
    p_dms = [] # +DM
    m_dms = [] # -DM

    for i in range(1, len(candles)):
        curr = candles[i]
        prev = candles[i-1]
        
        # TR
        tr = max(curr['high'] - curr['low'], 
                 abs(curr['high'] - prev['close']), 
                 abs(curr['low'] - prev['close']))
        trs.append(tr)
        
        # DM
        move_up = curr['high'] - prev['high']
        move_down = prev['low'] - curr['low']
        
        if move_up > move_down and move_up > 0:
            p_dms.append(move_up)
        else:
            p_dms.append(0)
            
        if move_down > move_up and move_down > 0:
            m_dms.append(move_down)
        else:
            m_dms.append(0)

    # Wilder's Smoothing
    def smooth(data, p):
        if len(data) < p: return []
        smoothed = [sum(data[:p])]
        for i in range(p, len(data)):
            # Wilder's smoothing formula: (prev * (n-1) + curr)
            # Alebo jednoducho EMA s alpha=1/n
            val = smoothed[-1] - (smoothed[-1] / p) + data[i]
            smoothed.append(val)
        return smoothed

    s_tr = smooth(trs, period)
    s_pdm = smooth(p_dms, period)
    s_mdm = smooth(m_dms, period)

    if not s_tr: return 0.0, 0.0, 0.0

    plus_di = []
    minus_di = []
    dx_list = []

    for i in range(len(s_tr)):
        tr_val = s_tr[i]
        p_di = 100 * (s_pdm[i] / tr_val) if tr_val > 0 else 0
        m_di = 100 * (s_mdm[i] / tr_val) if tr_val > 0 else 0
        
        plus_di.append(p_di)
        minus_di.append(m_di)
        
        diff = abs(p_di - m_di)
        total = p_di + m_di
        dx = 100 * (diff / total) if total > 0 else 0
        dx_list.append(dx)

    # ADX je vyhladený priemer DX
    if len(dx_list) < period:
        return plus_di[-1], minus_di[-1], 0.0

    # Prvé ADX je priemer prvých 'period' DX hodnôt
    adx_list = [sum(dx_list[:period]) / period]
    for i in range(period, len(dx_list)):
        val = (adx_list[-1] * (period - 1) + dx_list[i]) / period
        adx_list.append(val)

    return plus_di[-1], minus_di[-1], adx_list[-1]

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

def stop_hunter(state):
    """Okamžite zastaví všetky bežiace skeny"""
    state.hunter_session_id = getattr(state, 'hunter_session_id', 0) + 1
    try:
        subprocess.run(['pkill', '-f', 'tws_fetch_history.py'], capture_output=True)
    except: pass
    if hasattr(state, 'hunter_status_label'):
        state.hunter_status_label.config(text="⏹️ ZASTAVENÉ", foreground="red")
    print("🛑 Hunter: Manuálne zastavené užívateľom.")

def refresh_hunter(state, tree, rsi_p, rvi_p, tf_var, force=False, force_symbol=None):
    # 0. Zastavenie akýchkoľvek visiacich procesov skenovania (prevencia "duchárskeho" testovania)
    try:
        if not force_symbol: # Pri hromadnom skene vyčistíme staré procesy
            subprocess.run(['pkill', '-f', 'tws_fetch_history.py'], capture_output=True)
    except: pass

    # 1. Získať symboly
    symbols = []
    try:
        # Pôvodne zaškrtnuté symboly v Swing Hunterovi
        selected_in_hunter = []
        if hasattr(state, 'hunter_selected_symbols'):
            selected_in_hunter = [s for s, v in state.hunter_selected_symbols.items() if v.get()]
        
        # Symboly z PMCC Huntera (majú prioritu a skenujú sa vždy)
        pmcc_syms = getattr(state, 'pmcc_symbols', [])
        
        # Spojíme ich: PMCC symboly idú prvé (priorita)
        seen = set()
        for s in pmcc_syms:
            if s not in seen:
                symbols.append(s)
                seen.add(s)
        
        for s in sorted(selected_in_hunter):
            if s not in seen:
                symbols.append(s)
                seen.add(s)

    except Exception as e:
        print(f"❌ Hunter: Symbol error: {e}", flush=True)

    # 2. Vyčistiť tabuľku od symbolov, ktoré už nie sú vybraté
    # (Robíme to hneď, aby tabuľka reagovala na odškrtnutie)
    for item_id in tree.get_children():
        sym_text = tree.item(item_id, 'text').strip()
        if sym_text and sym_text not in symbols:
            tree.delete(item_id)

    if not symbols:
        try:
            subprocess.run(['pkill', '-f', 'tws_fetch_history.py'], capture_output=True)
        except: pass
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
    
    adx_filter_threshold = 0.0
    if hasattr(state, 'hunter_adx_filter_var'):
        adx_filter_threshold = ADX_FILTER_MAP.get(state.hunter_adx_filter_var.get(), 0.0)
    
    background_interval = getattr(state, 'hunter_background_refresh_interval', 3600)

    # NOVÉ: Zachytenie hodnôt z Tkinter premenných pred spustením thready (Thread Safety)
    current_tf_val = tf_var.get()
    rsi_p_val = int(rsi_p.get()) if rsi_p.get().isdigit() else 14
    rvi_p_val = int(rvi_p.get()) if rvi_p.get().isdigit() else 10
    port_val = getattr(state, 'current_port', "7497")
    selected_symbols_set = set(symbols)

    selected_tfs = []
    if hasattr(state, 'hunter_tf_vars'):
        selected_tfs = [tf for tf, var in state.hunter_tf_vars.items() if var.get()]
    if current_tf_val not in selected_tfs:
        selected_tfs.insert(0, current_tf_val)
    if "1 day" not in selected_tfs:
        selected_tfs.append("1 day")  # always fetch daily for MA200/pivots
    if not selected_tfs:
        selected_tfs = [current_tf_val]

    # Timeframes na skenovanie
    tfs = selected_tfs

    # Session ID pre zastavenie starých thready
    session_id = getattr(state, 'hunter_session_id', 0) + 1
    state.hunter_session_id = session_id

    def run():
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        py = sys.executable
        scr = os.path.join(root, 'scripts', 'tws_fetch_history.py')
        port = port_val

        for sym in symbols:
            # Ak je vynútený len jeden symbol, ostatné okamžite preskočíme
            if force_symbol and sym != force_symbol:
                continue

            print(f"🔄 Hunter: Spracovávam {sym}...")
            # Vytvoríme/aktualizujeme riadok v tabuľke hneď, aby užívateľ videl, že pracujeme
            def show_loading(s=sym):
                try:
                    parent_id = next((item for item in tree.get_children() if tree.item(item, 'text') == s), None)
                    if not parent_id:
                        tree.insert('', tk.END, text=s, values=("Sťahujem...", "—", "—", "—", "—", "—", "—", "—", "—", "—", "—", "—", "—", "—"))
                    else:
                        tree.item(parent_id, values=("Sťahujem...", "—", "—", "—", "—", "—", "—", "—", "—", "—", "—", "—", "—", "—"))
                except: pass
            state.root.after(0, show_loading)

            try:
                # Kontrola či už nebeží novší sken
                if getattr(state, 'hunter_session_id', 0) != session_id:
                    print(f"🛑 Hunter: Zastavujem starý sken (Session {session_id})")
                    return

                # Väčšia pauza pre stabilitu TWS pri hromadnom skene
                if not force_symbol and len(symbols) > 1:
                    time.sleep(0.8)

                # Kontrola počas behu: Ak už symbol nie je vybratý, preskočíme ho
                if sym not in selected_symbols_set:
                    continue
                
                # Kontrola či root ešte existuje
                if not state.root or not state.root.winfo_exists():
                    return

                next_ts = state.hunter_next_update.get(sym, 0)
                if not force and not force_symbol and time.time() < next_ts:
                    continue

                last_scores = getattr(state, 'hunter_last_scores', {})
                last_updates = getattr(state, 'hunter_last_update', {})
                last_score = last_scores.get(sym)
                last_update = last_updates.get(sym, 0)
                if not (force or force_symbol == sym) and filter_threshold > 0 and last_score is not None and last_score < filter_threshold and (time.time() - last_update) < background_interval:
                    continue

                # --- 1. SŤAHOVANIE DENNÝCH DÁT AKO PRVÉ ---
                pivots = None
                day_candles = None
                ma200_info = None
                is_skipped = False
                
                try:
                    # Skrátené na 60 D pre rýchlosť a spoľahlivosť
                    cmd_d = [py, scr, '--symbol', sym, '--barSize', '1 day', '--duration', '60 D', '--port', port, '--force']
                    print(f"DEBUG: Spúšťam: {' '.join(cmd_d)}")
                    
                    # Použijeme communicate() namiesto run() pre lepšiu kontrolu nad buffermi
                    process = subprocess.Popen(cmd_d, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, cwd=root)
                    try:
                        stdout, stderr = process.communicate(timeout=65)
                        print(f"DEBUG: Skript skončil. Stdout: '{stdout.strip()[:100]}...'")
                        if stderr: print(f"DEBUG STDERR: {stderr}")
                    except subprocess.TimeoutExpired:
                        process.kill()
                        print(f"❌ {sym}: Timeout pri sťahovaní denných dát")
                        state.root.after(0, lambda: tree.item(next(i for i in tree.get_children() if tree.item(i, 'text') == sym), values=("❌ TIMEOUT", "—", "—", "—", "—", "—", "—", "—", "—", "—", "—", "—", "—", "—")))
                        continue

                    if process.returncode == 0:
                        d_data = json.loads(stdout.strip())
                        if d_data.get('success'):
                            day_candles = d_data['candles']
                            if day_candles and len(day_candles) >= 20:
                                # ... existujúca logika ...
                                d_rsi = calculate_rsi(day_candles, 14)
                                d_pdi, d_mdi, d_adx = calculate_adx_dmi(day_candles, 14)
                                d_bb = calculate_bb(day_candles)
                                d_ma20 = d_bb['mid'] if d_bb else None
                                d_close = day_candles[-1]['close']
                                ma200_info = calculate_ma200_metrics(day_candles)
                                d_ma200 = ma200_info.get('value') if ma200_info else None
                                # Ak nemáme MA200 (málo dát), pri single-symbol alebo force-symbol skúsiť natiahnuť dlhšiu históriu
                                if ma200_info is None and day_candles:
                                    try:
                                        ext_cmd = [py, scr, '--symbol', sym, '--barSize', '1 day', '--duration', '252 D', '--port', port, '--force']
                                        print(f"DEBUG: Chýba MA200 pre {sym}, sťahujem dlhšiu históriu: {' '.join(ext_cmd)}")
                                        ext_proc = subprocess.Popen(ext_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, cwd=root)
                                        try:
                                            ext_stdout, ext_stderr = ext_proc.communicate(timeout=95)
                                            if ext_proc.returncode == 0 and ext_stdout.strip():
                                                ext_data = json.loads(ext_stdout.strip())
                                                if ext_data.get('success'):
                                                    ext_candles = ext_data.get('candles', [])
                                                    if ext_candles and len(ext_candles) >= 200:
                                                        ma200_info = calculate_ma200_metrics(ext_candles)
                                                        d_ma200 = ma200_info.get('value') if ma200_info else None
                                                        # replace day_candles with extended for downstream metrics if we have full series
                                                        day_candles = ext_candles
                                            else:
                                                if ext_stderr:
                                                    print(f"DEBUG STDERR (ext fetch): {ext_stderr.strip()}")
                                        except subprocess.TimeoutExpired:
                                            ext_proc.kill()
                                            print(f"❌ {sym}: Timeout pri sťahovaní rozšírenej histórie pre MA200")
                                        except Exception as e:
                                            print(f"❌ {sym}: Chyba pri sťahovaní rozšírenej histórie: {e}")
                                    except Exception as e:
                                        print(f"❌ {sym}: Nepodarilo sa spustiť externý fetch pre MA200: {e}")

                                if not (force or force_symbol):
                                    is_interesting = False
                                    if d_rsi < 40 or d_rsi > 60: is_interesting = True
                                    if d_ma20 and abs((d_close - d_ma20) / d_ma20) < 0.015: is_interesting = True
                                    if d_ma200 and abs((d_close - d_ma200) / d_ma200) < 0.02: is_interesting = True
                                    if not is_interesting: is_skipped = True
                            else:
                                print(f"⚠️ {sym}: Málo denných sviečok z TWS")
                                state.root.after(0, lambda: tree.item(next(i for i in tree.get_children() if tree.item(i, 'text') == sym), values=("⚠️ MÁLO DÁT", "—", "—", "—", "—", "—", "—", "—", "—", "—", "—", "—", "—", "—")))
                        else:
                            err = d_data.get('error', 'Neznáma chyba TWS')
                            print(f"❌ {sym}: TWS chyba denného grafu: {err}")
                            state.root.after(0, lambda: tree.item(next(i for i in tree.get_children() if tree.item(i, 'text') == sym), values=(f"❌ {err[:15]}...", "—", "—", "—", "—", "—", "—", "—", "—", "—", "—", "—", "—", "—")))
                    else:
                        print(f"❌ {sym}: Skript zlyhal (Kód {process.returncode})")
                        if stderr: print(f"   Stderr: {stderr.strip()}")
                        state.root.after(0, lambda: tree.item(next(i for i in tree.get_children() if tree.item(i, 'text') == sym), values=("❌ CHYBA SKRIPTU", "—", "—", "—", "—", "—", "—", "—", "—", "—", "—", "—", "—", "—")))
                except Exception as e:
                    print(f"❌ Smart Filter Error {sym}: {e}")

                # --- 2. ZÍSKANIE PIVOT DATA (Ak treba weekly) ---
                current_tf = current_tf_val
                if not is_skipped and "week" in current_tf:
                    try:
                        cmd_p = [py, scr, '--symbol', sym, '--barSize', '1 week', '--duration', '3 M', '--port', port]
                        res_p = subprocess.run(cmd_p, capture_output=True, text=True, timeout=50, cwd=root)
                        if res_p.returncode == 0:
                            p_data = json.loads(res_p.stdout.strip())
                            if p_data.get('success') and len(p_data['candles']) >= 2:
                                 pivots = calculate_pivots(p_data['candles'][-2])
                    except Exception: pass
                
                # --- 3. SŤAHOVANIE OSTATNÝCH TF ---
                results_tf = {} 
                if day_candles:
                     d_rsi = calculate_rsi(day_candles, rsi_p_val)
                     d_pdi, d_mdi, d_adx = calculate_adx_dmi(day_candles, 14)
                     d_rvi, d_rvi_s = calculate_rvi(day_candles, rvi_p_val)
                     d_bb = calculate_bb(day_candles)
                     d_macd = calculate_macd(day_candles)
                     d_status, d_action, d_tag = "Neutral", "Čakať", ""
                     if is_skipped: d_status, d_tag = "💤 Nudný (Denný)", "zone_neutral"
                     elif d_rsi < 30: d_status, d_tag = "🔥 PREPREDANÉ", "alert"
                     elif d_rsi > 70: d_status, d_tag = "❄️ PREKÚPENÉ", "alert"
                     results_tf['1 day'] = {
                         'rsi': d_rsi, 'rvi': d_rvi, 'rvi_s': d_rvi_s, 
                         'adx': d_adx, 'pdi': d_pdi, 'mdi': d_mdi,
                         'price': day_candles[-1]['close'], 
                         'status': d_status, 'action': d_action, 'tag': d_tag,
                         'bb': d_bb, 'macd': d_macd, 'candles': day_candles
                     }

                if not is_skipped:
                    for tf in tfs:
                        if tf == '1 day': continue
                        dur = "10 D"
                        if "15 mins" in tf: dur = "5 D"
                        elif "1 hour" in tf: dur = "25 D"
                        elif "4 hours" in tf: dur = "60 D"
                        elif "week" in tf: dur = "2 Y"
                        elif "day" in tf: dur = "60 D"

                        try:
                            cmd = [py, scr, '--symbol', sym, '--barSize', tf, '--duration', dur, '--port', port]
                            if force or force_symbol: cmd.append('--force')
                            
                            process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, cwd=root)
                            try:
                                stdout, stderr = process.communicate(timeout=55)
                            except subprocess.TimeoutExpired:
                                process.kill()
                                print(f"❌ {sym} {tf}: Timeout")
                                continue

                            if process.returncode == 0:
                                data = json.loads(stdout.strip())
                                if data.get('success'):
                                    c = data['candles']
                                    if c:
                                        rsi = calculate_rsi(c, rsi_p_val)
                                        pdi, mdi, adx = calculate_adx_dmi(c, 14)
                                        rvi, rvi_s = calculate_rvi(c, rvi_p_val)
                                        bb_data = calculate_bb(c)
                                        macd_data = calculate_macd(c)
                                        tf_status, tf_action, tf_tag = "Neutral", "Čakať", ""
                                        if rsi < 30 and bb_data and c[-1]['close'] <= bb_data['lower']: tf_status, tf_tag = "⚠️ EXTREME OVERWEIGHT", "alert"
                                        elif rsi < 30: tf_status, tf_tag = "🔥 PREPREDANÉ", "alert"
                                        elif rsi > 70: tf_status, tf_tag = "❄️ PREKÚPENÉ", "alert"
                                        if rvi > rvi_s:
                                            if macd_data and macd_data['is_cross']: tf_action, tf_tag = "🚀 CONFIRMED BUY", "buy"
                                            else: tf_action, tf_tag = "✅ BUY", "buy"
                                        elif rsi > 70 and rvi < rvi_s: tf_action, tf_tag = "🔻 SHORT", "short"
                                        results_tf[tf] = {
                                            'rsi': rsi, 'rvi': rvi, 'rvi_s': rvi_s, 
                                            'adx': adx, 'pdi': pdi, 'mdi': mdi,
                                            'price': c[-1]['close'], 
                                            'status': tf_status, 'action': tf_action, 'tag': tf_tag,
                                            'bb': bb_data, 'macd': macd_data, 'candles': c
                                        }
                                    else:
                                        print(f"❌ {sym} {tf}: TWS error: {data.get('error')}")
                                else:
                                    print(f"❌ {sym} {tf}: Fetch script failed (Code {res.returncode})")
                                    if res.stderr: print(f"   Stderr: {res.stderr.strip()}")
                            else:
                                print(f"❌ {sym} {tf}: Subprocess return code {res.returncode}")
                        except Exception as e: print(f"❌ Error fetching {sym} {tf}: {e}")

                if not results_tf:
                    print(f"⚠️ {sym}: Žiadne dáta na zobrazenie.")
                    continue
                
                main_tf = current_tf_val
                if main_tf not in results_tf:
                    main_tf = list(results_tf.keys())[0]
                
                main_data = results_tf[main_tf]
                price = main_data['price']
                if not ma200_info and results_tf.get('1 day'):
                    ma200_info = calculate_ma200_metrics(results_tf['1 day']['candles'])

                ma200_value = ma200_info.get('value') if ma200_info else None
                has_ma = ma200_value is not None and ma200_value > 0
                price_above_ma = price >= ma200_value if has_ma else True
                is_bearish_trend = has_ma and price < ma200_value
                trend_text, trend_tag, trend_label = "—", None, "—"
                if has_ma:
                    dist_pct = ((price - ma200_value) / ma200_value) * 100
                    trend_label = 'Býk' if price_above_ma else 'Bear'
                    trend_text = f"{trend_label} {dist_pct:+.1f}%"
                    trend_tag = 'trend_bear' if is_bearish_trend else ('trend_breakout' if ma200_info.get('cross_up') and price_above_ma else 'trend_bull')
                
                status, action, tag = "Neutral", "Čakať", ""
                rsi_vals = {tf: results_tf.get(tf, {}).get('rsi', 50.0) for tf in ["15 mins", "1 hour", "4 hours", "1 day", "1 week"]}
                align_buy_short = rsi_vals['15 mins'] < 35 and rsi_vals['1 hour'] < 35
                align_buy_long  = rsi_vals['4 hours'] < 40 and rsi_vals['1 day'] < 45
                align_short_short = rsi_vals['15 mins'] > 65 and rsi_vals['1 hour'] > 65
                align_short_long  = rsi_vals['4 hours'] > 60 and rsi_vals['1 day'] > 55

                if align_buy_short and align_buy_long: tag = "align_perfect"
                elif align_buy_long: tag = "align_long"
                elif align_buy_short: tag = "align_short"
                elif align_short_short and align_short_long: tag = "align_perfect_s"
                elif align_short_long: tag = "align_long_s"
                elif align_short_short: tag = "align_short_s"

                p_dist_str, is_near_support = "", False
                if not pivots and '1 day' in results_tf and len(results_tf['1 day']['candles']) >= 2:
                    pivots = calculate_pivots(results_tf['1 day']['candles'][-2])
                
                if pivots:
                    targets = {'P': pivots['P'], 'S1': pivots['S1'], 'S2': pivots['S2']}
                    min_dist_pct, best_level = 999.0, ""
                    for name, val in targets.items():
                        dist_pct = ((price - val) / val) * 100
                        if abs(dist_pct) < abs(min_dist_pct):
                            min_dist_pct = dist_pct
                            best_level = name
                    best_val = targets[best_level]
                    p_dist_str = f"{best_level[0]} {best_val:.2f}/{min_dist_pct:+.2f}%" if best_level else "—"
                    if abs(min_dist_pct) < 0.5: is_near_support = best_level in ('S1', 'S2', 'P')

                is_oversold = any(v < 30 for v in rsi_vals.values())
                is_overbought = any(v > 70 for v in rsi_vals.values())
                main_bb = main_data.get('bb')
                main_macd = main_data.get('macd')
                score_dist, score_level = 99.0, ""
                if pivots:
                    for name, val in {'P': pivots['P'], 'S1': pivots['S1'], 'S2': pivots['S2']}.items():
                        d_pct = ((price - val) / val) * 100
                        if abs(d_pct) < abs(score_dist):
                            score_dist = d_pct
                            score_level = name

                swing_score, breakdown, zone = vypocitaj_swing_skore(main_data['rsi'], price, main_bb, main_data['rvi'], main_data['rvi_s'], main_macd, score_dist, score_level)
                adjusted_score = swing_score
                if has_ma:
                    if is_bearish_trend: adjusted_score *= 0.6
                    elif ma200_info.get('slope_down'): adjusted_score *= 0.9
                adjusted_score = max(0.0, min(10.0, adjusted_score))
                score_pct = score_to_percent(adjusted_score)
                active_key = (sym, main_tf)
                active_signal = state.hunter_active_signals.get(active_key, None)
                pl_signal_value, pl_tag = "", None
                if breakdown:
                    breakdown_percent = {k: v * 10 for k, v in breakdown.items()}
                    breakdown_text = ", ".join(f"{k}:{perc:.0f}%" for k, perc in breakdown_percent.items())
                else: breakdown_text = "Žiadny príspevok"

                if not hasattr(state, 'hunter_last_scores'): state.hunter_last_scores = {}
                if not hasattr(state, 'hunter_last_update'): state.hunter_last_update = {}
                if not hasattr(state, 'hunter_last_breakdown'): state.hunter_last_breakdown = {}
                
                state.hunter_last_scores[sym] = score_pct
                state.hunter_last_update[sym] = time.time()
                state.hunter_last_breakdown[sym] = breakdown_text

                score_tag = 'score_0_19'
                if score_pct >= 80: score_tag = "score_80_100"
                elif score_pct >= 50: score_tag = "score_50_79"
                elif score_pct >= 20: score_tag = "score_20_49"

                score_text = f"Skóre: {score_pct:.0f} %"
                pct_b_value = main_bb['pct_b'] if main_bb else None
                pct_b_text = f"{pct_b_value:.1f}%" if pct_b_value is not None else "—"
                if pct_b_value is None: pctb_tag = 'pctb_none'
                elif pct_b_value < 25: pctb_tag = 'pctb_low'
                elif pct_b_value > 80: pctb_tag = 'pctb_high'
                else: pctb_tag = 'pctb_mid'
                
                pivot_label = p_dist_str if p_dist_str else "—"
                pivot_bb_text = pivot_label
                interval = get_dynamic_interval(score_pct, zone, pct_b_value)
                state.hunter_next_update[sym] = time.time() + interval
                next_update_text = format_mmss(interval)

                strong_macd = bool(main_macd and main_macd.get('is_cross'))
                rvi_bull = main_data['rvi'] > main_data['rvi_s']
                rvi_bear = main_data['rvi'] < main_data['rvi_s']
                macd_falling = bool(main_macd and main_macd.get('macd') < main_macd.get('signal', 0))

                trend_breakout = has_ma and ma200_info and ma200_info.get('cross_up') and price_above_ma
                action = "Neutral"
                if trend_breakout: action = "Trend Breakout"
                elif is_bearish_trend: action = "Bearish Rebound" if score_pct >= 40 else "Sledovať rezistenciu"
                elif zone == 'hunt': action = "🚀 STRONG BUY" if strong_macd or rvi_bull else "⏳ SLEDOVAŤ AKUMULÁCIU"
                elif zone == 'hold': action = "⏳ DRŽAŤ / NEUTRÁL"
                elif zone == 'risk': action = "💰 VÝSTUP / TAKE PROFIT" if (rvi_bear or macd_falling) else "⚠️ RIZIKO / BLOKUJ BUY"
                else:
                    if score_pct >= 80: action = "🚀 RAKETA (Strong Buy)"
                    elif score_pct >= 50: action = "✅ VHODNÝ VSTUP"
                    elif score_pct >= 20: action = "⏳ ČAKAŤ (Sledovať)"
                    else: action = "Neutral"

                if action in {"🚀 STRONG BUY", "✅ VHODNÝ VSTUP", "Trend Breakout"}:
                    if not active_signal:
                        entry_time = log_signal_entry(sym, main_tf, price, main_data['rsi'], pct_b_value, action, zone=zone, trend=trend_label, score_pct=score_pct, macd_cross=strong_macd, rvi_gt_sig=rvi_bull, pivot_dist=score_dist, action_text=action)
                        state.hunter_active_signals[active_key] = {'entry_price': price, 'entry_time': entry_time, 'signal_type': action}
                        active_signal = state.hunter_active_signals[active_key]
                else:
                    if active_signal:
                        final_pl = ((price - active_signal['entry_price']) / active_signal['entry_price']) * 100 if active_signal['entry_price'] else 0.0
                        log_signal_exit(active_signal['entry_time'], price, final_pl)
                        del state.hunter_active_signals[active_key]
                        active_signal = None

                if active_signal and active_signal.get('entry_price'):
                    pl_pct = ((price - active_signal['entry_price']) / active_signal['entry_price']) * 100
                    pl_signal_value, pl_tag = f"{pl_pct:+.2f}%", ('pl_profit' if pl_pct >= 0 else 'pl_loss')

                zone_tag = f"zone_{zone}" if zone else "zone_neutral"
                if zone_tag not in ('zone_hunt', 'zone_hold', 'zone_risk', 'zone_neutral'): zone_tag = 'zone_neutral'

                is_extreme = any(d.get('status') == "⚠️ EXTREME OVERWEIGHT" for d in results_tf.values())
                if is_extreme: status = "⚠️ EXTREME OVERWEIGHT"
                elif is_oversold: status = "🔥 PREPREDANÉ"
                elif is_overbought: status = "❄️ PREKÚPENÉ"
                else: status = "Neutral"

                atr_value = calculate_atr(main_data.get('candles'))
                summary = {
                    'symbol': sym, 'price': price, 'score_pct': score_pct, 'score_level': score_level, 'score_dist': score_dist,
                    'zone': zone, 'action': action, 'status': status, 'trend_text': trend_text, 'trend_label': trend_label,
                    'trend_breakout': trend_breakout, 'has_ma': has_ma, 'ma200_value': ma200_value,
                    'pct_b': main_bb.get('pct_b') if main_bb else None, 'pivot_label': pivot_bb_text, 'pivots': pivots,
                    'main_bb': main_bb, 'macd': main_macd, 'atr': atr_value, 'rsi': main_data['rsi'],
                    'adx': main_data.get('adx', 0.0), 'pdi': main_data.get('pdi', 0.0), 'mdi': main_data.get('mdi', 0.0),
                    'rvi': main_data['rvi'], 'rvi_s': main_data['rvi_s'], 'breakdown': breakdown_text,
                    'next_update': next_update_text, 'zone_tag': zone_tag, 'timeframe': main_tf
                }

                summary['strategy_label'], summary['strategy_reason'] = recommend_strategy(summary)
                summary['option_strategy'], summary['option_reason'] = recommend_option_strategy(summary)
                # Dočasne vypnuté pre diagnostiku zaseknutia
                summary['ml_prob'] = 0.0 # predict_ml_score(summary, getattr(state, 'hunter_model', None))
                state.hunter_symbol_summaries[sym] = summary

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
                              pct_b_value_param=pct_b_value, trend_breakout_flag=trend_breakout,
                              curr_summary=summary):
                    parent_id = next((item for item in tree.get_children() if tree.item(item, 'text') == s), None)
                    ml_p = curr_summary.get('ml_prob')
                    ml_text = f"{ml_p*100:.0f}%" if isinstance(ml_p, (int, float)) else "—"
                    opt_strat = curr_summary.get('option_strategy', '—')
                    parent_action = f"{ac} | {opt_strat}" if opt_strat and opt_strat != '—' else ac

                    vals = (f"{p:.2f}", trend_val, sc_text, f"{main_data_param.get('adx', 0):.1f}", pct_b_cell, next_up, f"{main_data_param['rvi']:.4f}", f"{main_data_param['rvi_s']:.4f}", pivot_bb, st, parent_action, ml_text, bk_text, pl_disc)
                    parent_tags = [score_tag]
                    if pct_tag: parent_tags.append(pct_tag)
                    if z_tag: parent_tags.append(z_tag)
                    if pl_t: parent_tags.append(pl_t)
                    if trend_tag: parent_tags.append(trend_tag)
                    if s in getattr(state, 'hunter_pinned_symbols', []): parent_tags.append('pinned')
                    parent_tags.append('header')
                    if tg: parent_tags.insert(0, tg)

                    if parent_id: tree.item(parent_id, values=vals, tags=parent_tags)
                    else: parent_id = tree.insert('', tk.END, text=s, values=vals, tags=parent_tags, open=False)

                    for child in tree.get_children(parent_id): tree.delete(child)
                    if opt_strat and opt_strat != '—':
                        tree.insert(parent_id, tk.END, text="  🎯 Stratégia", values=("", "", "", "", "", "", "", "", "", opt_strat, curr_summary.get('option_reason', '—'), "", "", ""), tags=('header',))
                    
                    for tf_name in ["15 mins", "1 hour", "4 hours", "1 day", "1 week"]:
                        if tf_name in res_tf:
                            d = res_tf[tf_name]
                            if tf_name in ('1 day', '1 week') and tf_name != current_tf_val:
                                if not state.hunter_tf_vars.get(tf_name).get(): continue
                            bb_val = f"{d['bb']['pct_b']:.1f}%" if d.get('bb') else "—"
                            pctb_child = float(bb_val.replace('%', '')) if bb_val != "—" else None
                            c_action = "⚠️ STOP" if zone_name == 'risk' else ("🚀 STRONG BUY" if zone_name == 'hunt' and pctb_child is not None and pctb_child < 30 and "BUY" in d['action'].upper() else ("Čakať" if "BUY" in d['action'].upper() else d['action']))
                            c_tags = [d['tag'], z_tag]
                            if pctb_child and pctb_child > 100: c_tags.append('pctb_over')
                            tree.insert(parent_id, tk.END, text=f"  {tf_name}", values=("", trend_label if trend_label != "—" else "", f"{d['rsi']:.1f}", f"{d.get('adx', 0):.1f}", bb_val, "", f"{d['rvi']:.4f}", f"{d['rvi_s']:.4f}", p_dist_str, d['status'], c_action, "", "", ""), tags=tuple(c_tags))

                # Vždy zobrazíme symbol v tabuľke, aj keď je "skipped" (nudný), aby užívateľ videl progres
                state.root.after(0, update_ui)
                
                if (filter_threshold <= 0 or score_pct >= filter_threshold) and (adx_filter_threshold <= 0 or adx_v >= adx_filter_threshold):
                    # Tu už len potvrdíme finálny stav, ak prešiel filtrami
                    pass

            except Exception as e:
                print(f"❌ Hunter: Chyba pri spracovaní symbolu {sym}: {e}")
                import traceback
                traceback.print_exc()
        def cleanup_low_symbols():
            if filter_threshold <= 0 and adx_filter_threshold <= 0:
                return
            for item in tree.get_children():
                if tree.parent(item):
                    continue
                
                # Filter Skóre
                if filter_threshold > 0:
                    score_text = tree.set(item, 'rsi_score')
                    if extract_score_value(score_text) < filter_threshold:
                        tree.delete(item)
                        continue
                
                # Filter ADX
                if adx_filter_threshold > 0:
                    adx_text = tree.set(item, 'adx')
                    try:
                        cur_adx = float(adx_text)
                        if cur_adx < adx_filter_threshold:
                            tree.delete(item)
                            continue
                    except:
                        pass

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
        def on_toggle():
            state.save_settings_file() # Uložiť stav checkboxu
            refresh_hunter(state, state.hunter_tree, state.hunter_rsi_p, state.hunter_rvi_p, state.hunter_tf_v)

        cb = ttk.Checkbutton(s_container, text=sym, variable=state.hunter_selected_symbols[sym],
                             command=on_toggle)
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
    
    # NOVÉ: Bloky symbolov
    block_f = ttk.Frame(s_frame); block_f.pack(fill='x', pady=(0, 5))
    ttk.Label(block_f, text="📂 Bloky:").pack(side='left', padx=5)
    block_v = state.hunter_selected_block
    block_combo = ttk.Combobox(block_f, textvariable=block_v, width=20, state='readonly')
    block_combo.pack(side='left', padx=5)
    
    def update_block_combo_hunter():
        current = block_v.get()
        blocks = ["-- Vybrať blok --"] + sorted(state.symbol_blocks.keys())
        block_combo['values'] = blocks
        if current in blocks:
            block_combo.set(current)
        else:
            block_combo.current(0)
    
    update_block_combo_hunter()

    def on_block_selected_hunter(event=None):
        name = block_v.get()
        if name == "-- Vybrať blok --": return
        syms = state.symbol_blocks.get(name, [])
        if syms:
            # Správanie ako v PMCC - nahradíme aktuálne symboly symbolmi z bloku
            state.hunter_custom_tickers = list(syms)
            state.save_settings_file()
            update_hunter_symbols_ui(state, symbols_container)
            refresh_hunter(state, state.hunter_tree, state.hunter_rsi_p, state.hunter_rvi_p, state.hunter_tf_v)

    block_combo.bind("<<ComboboxSelected>>", on_block_selected_hunter)

    def open_manager_hunter():
        from modularny.shared_state import open_symbol_block_manager
        open_symbol_block_manager(state, update_block_combo_hunter)

    ttk.Button(block_f, text="📁 Spravovať bloky", command=open_manager_hunter).pack(side='left', padx=5)

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

    def scan_single_symbol():
        sym = new_sym_ent.get().strip().upper()
        if not sym:
            messagebox.showwarning("Swing Hunter", "Zadajte symbol pre skenovanie.")
            return
        
        # Ak symbol ešte nie je v custom zozname, pridáme ho (bez info okna)
        if not hasattr(state, 'hunter_custom_tickers'): state.hunter_custom_tickers = []
        if sym not in state.hunter_custom_tickers:
            state.hunter_custom_tickers.append(sym)
            if not hasattr(state, 'hunter_selected_symbols'): state.hunter_selected_symbols = {}
            state.hunter_selected_symbols[sym] = tk.BooleanVar(value=True)
            state.save_settings_file()
            update_hunter_symbols_ui(state, symbols_container)
        
        # Vždy vynútime sken len tohto symbolu
        force_refresh_symbol_now(state, sym)

    ttk.Button(add_f, text="➕ Pridať", width=8, command=lambda: add_custom_ticker(state, new_sym_ent, symbols_container)).pack(side='left', padx=5)
    ttk.Button(add_f, text="🔍 Skenovať symbol", width=16, command=scan_single_symbol).pack(side='left', padx=5)
    
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
    state.hunter_rsi_p = rsi_p
    ttk.Label(ctrl, text="RVI:").pack(side='left', padx=(15, 5))
    rvi_p = tk.StringVar(value="10"); ttk.Entry(ctrl, textvariable=rvi_p, width=5).pack(side='left', padx=2)
    state.hunter_rvi_p = rvi_p
    
    # Výber časových rámcov (multi-select by bol fajn, ale zatiaľ skúsime fixné sady alebo prepínač)
    ttk.Label(ctrl, text="Základný TF:").pack(side='left', padx=(15, 5))
    tf_v = tk.StringVar(value="4 hours")
    state.hunter_tf_v = tf_v
    tf_combo = ttk.Combobox(ctrl, textvariable=tf_v, values=["15 mins", "1 hour", "4 hours", "1 day", "1 week"], width=10)
    tf_combo.pack(side='left', padx=5)
    tf_combo.bind("<<ComboboxSelected>>", lambda e: refresh_hunter(state, state.hunter_tree, rsi_p, rvi_p, tf_v))
    
    tf_opts_frame = ttk.Frame(ctrl)
    tf_opts_frame.pack(fill='x', pady=(10, 0))
    ttk.Label(tf_opts_frame, text="TF analýza:").pack(side='left', padx=5)
    state.hunter_tf_vars = {}
    for tf_name in ["15 mins", "1 hour", "4 hours", "1 day", "1 week"]:
        var = tk.BooleanVar(value=True)
        state.hunter_tf_vars[tf_name] = var
        ttk.Checkbutton(tf_opts_frame, text=tf_name, variable=var,
                        command=lambda: refresh_hunter(state, state.hunter_tree, state.hunter_rsi_p, state.hunter_rvi_p, state.hunter_tf_v)).pack(side='left', padx=2)

    state.hunter_score_filter_var = tk.StringVar(value=getattr(state, 'hunter_score_filter_val', list(SCORE_FILTER_MAP.keys())[0]))
    ttk.Label(ctrl, text="Filter skóre:").pack(side='left', padx=(20, 5))
    score_combo = ttk.Combobox(ctrl, textvariable=state.hunter_score_filter_var,
                               values=list(SCORE_FILTER_MAP.keys()), width=10, state='readonly')
    score_combo.pack(side='left')
    score_combo.bind("<<ComboboxSelected>>", lambda e: (state.save_settings_file(), refresh_hunter(state, state.hunter_tree, state.hunter_rsi_p, state.hunter_rvi_p, state.hunter_tf_v)))
    
    state.hunter_adx_filter_var = tk.StringVar(value=getattr(state, 'hunter_adx_filter_val', list(ADX_FILTER_MAP.keys())[0]))
    ttk.Label(ctrl, text="ADX Filter:").pack(side='left', padx=(20, 5))
    adx_combo = ttk.Combobox(ctrl, textvariable=state.hunter_adx_filter_var,
                              values=list(ADX_FILTER_MAP.keys()), width=15, state='readonly')
    adx_combo.pack(side='left')
    adx_combo.bind("<<ComboboxSelected>>", lambda e: (state.save_settings_file(), refresh_hunter(state, state.hunter_tree, state.hunter_rsi_p, state.hunter_rvi_p, state.hunter_tf_v)))
    
    def clear_hunter_results():
        if messagebox.askyesno("Swing Hunter", "Naozaj chcete vymazať všetky výsledky z tabuľky?"):
            for item in tree.get_children():
                tree.delete(item)
            state.hunter_symbol_summaries = {}
            state.hunter_last_scores = {}
            state.hunter_last_update = {}
            state.hunter_status_label.config(text="Výsledky vymazané", foreground="gray")

    ttk.Button(ctrl, text="🗑️ Vymazať výsledky", command=clear_hunter_results).pack(side='left', padx=10)

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
    cols = ('price', 'trend', 'rsi_score', 'adx', 'pct_b', 'next_update', 'rvi', 'rvi_sig', 'p_dist_bb', 'status', 'action', 'ml_prob', 'breakdown', 'pl_signal')
    tree = ttk.Treeview(t_frame, columns=cols, show='tree headings')
    
    tree._sort_states = {'#0': False, 'rsi_score': False, 'adx': False}
    def _on_sort(col):
        reverse = tree._sort_states.get(col, False)
        sort_hunter_tree_parents(tree, col, reverse)
        tree._sort_states[col] = not reverse

    tree.heading('#0', text='Sym/Tim', command=lambda: _on_sort('#0')); tree.column('#0', width=120, anchor='w')
    tree.heading('price', text='Cena'); tree.column('price', width=80, anchor='center')
    tree.heading('trend', text='T(MA200)'); tree.column('trend', width=100, anchor='center')
    tree.heading('rsi_score', text='RSI/SK', command=lambda: _on_sort('rsi_score')); tree.column('rsi_score', width=80, anchor='center')
    tree.heading('adx', text='ADX', command=lambda: _on_sort('adx')); tree.column('adx', width=50, anchor='center')
    tree.heading('pct_b', text='%B'); tree.column('pct_b', width=65, anchor='center')
    tree.heading('next_update', text='Dalšia akt.'); tree.column('next_update', width=75, anchor='center')
    tree.heading('rvi', text='RVI'); tree.column('rvi', width=75, anchor='center')
    tree.heading('rvi_sig', text='RVI Sig'); tree.column('rvi_sig', width=75, anchor='center')
    tree.heading('p_dist_bb', text='Pivot'); tree.column('p_dist_bb', width=100, anchor='center')
    tree.heading('status', text='Stav'); tree.column('status', width=130, anchor='center')
    tree.heading('action', text='Akcia/Stratégia'); tree.column('action', width=220, anchor='center')
    tree.heading('ml_prob', text='ML P(%)'); tree.column('ml_prob', width=65, anchor='center')
    tree.heading('breakdown', text='Rozklad'); tree.column('breakdown', width=180, anchor='w')
    tree.heading('pl_signal', text='P/L Signálu'); tree.column('pl_signal', width=90, anchor='center')

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
        
        def open_tp_from_menu():
            summary = state.hunter_symbol_summaries.get(sym, {'symbol': sym})
            open_trade_plan_window(state, summary)
            
        menu.add_command(label="📝 Trade Plan", command=open_tp_from_menu)
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()

    tree.bind("<Button-3>", show_pin_menu)
    ttk.Button(highlight_frame, text="📋 Výťah", command=open_extract_window).pack(padx=2, pady=2)
    
    # NOVÉ: Skupina tlačidiel pre ovládanie skenu
    scan_ctrl_frame = ttk.Frame(highlight_frame)
    scan_ctrl_frame.pack(padx=2, pady=2)
    
    ttk.Button(scan_ctrl_frame, text="🏹 VYHĽADAŤ", width=12,
               command=lambda: refresh_hunter(state, state.hunter_tree, state.hunter_rsi_p, state.hunter_rvi_p, state.hunter_tf_v, force=True)).pack(side='left', padx=1)
    
    ttk.Button(scan_ctrl_frame, text="⏹️ STOP", width=10,
               command=lambda: stop_hunter(state)).pack(side='left', padx=1)

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
    
    f_ctrl_frame = ttk.Frame(footer)
    f_ctrl_frame.pack(pady=10)
    
    ttk.Button(f_ctrl_frame, text="🏹 VYHĽADAŤ PRÍLEŽITOSTI (Všetky vybrané)", 
               command=lambda: refresh_hunter(state, tree, rsi_p, rvi_p, tf_v, force=True)).pack(side='left', padx=2)
    ttk.Button(f_ctrl_frame, text="⏹️ ZASTAVIŤ SKEN", 
               command=lambda: stop_hunter(state)).pack(side='left', padx=2)
    
    return frame


def refresh_trade_plan_vars(state, window, symbol, summary):
    plan_vars = getattr(window, 'plan_vars', None)
    if not plan_vars:
        return
    data = summary or {}

    def _fmt(val):
        try:
            if val is None or val == "—": return "—"
            return f"{float(val):.2f}"
        except (ValueError, TypeError):
            return str(val) if val is not None else "—"

    entry = data.get('price')
    pivots = data.get('pivots') or {}
    bb = data.get('main_bb') or {}
    atr_value = data.get('atr')
    
    def _to_float(value):
        if isinstance(value, (int, float)):
            return float(value)
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    entry_value = _to_float(entry)
    
    # 1. SL calculation (2xATR or pivot fallback)
    sl = None
    atr_mult = 2.0
    atr_mult_var = getattr(state, 'atr_multiplier_var', None)
    if atr_mult_var:
        try:
            atr_mult = float(atr_mult_var.get())
        except Exception:
            atr_mult = 2.0

    if entry_value is not None:
        if atr_value is not None:
            # Prefer ATR-based SL
            sl = entry_value - (atr_value * atr_mult)
        else:
            # Fallback to pivots
            supports = []
            for k in ('S1', 'S2', 'S3', 'P'):
                v = _to_float(pivots.get(k))
                if v is not None and v < entry_value:
                    supports.append(v)
            if supports:
                sl = max(supports)
            else:
                sl = entry_value * 0.985 # 1.5% stop
    
    # 2. TP1 and TP2 calculation
    tp1 = None
    tp2 = None
    if entry_value is not None:
        # Find closest pivot ABOVE entry
        resistances = []
        for k in ('P', 'R1', 'R2', 'R3'):
            v = _to_float(pivots.get(k))
            if v is not None and v > entry_value:
                resistances.append(v)
        resistances.sort()
        
        if resistances:
            tp1 = resistances[0]
            if len(resistances) > 1:
                tp2 = resistances[1]
        
        # Fallback for TP1 if no pivots above
        if tp1 is None:
            bb_mid = _to_float(bb.get('mid'))
            if bb_mid and bb_mid > entry_value:
                tp1 = bb_mid
            else:
                tp1 = entry_value * 1.015 # 1.5% target
        
        # Fallback for TP2
        if tp2 is None:
            bb_upper = _to_float(bb.get('upper'))
            if bb_upper and bb_upper > (tp1 or entry_value):
                tp2 = bb_upper
            else:
                tp2 = (tp1 or entry_value) * 1.02 # Another 2% above TP1
                
    # 3. R:R calculation
    rr_val = None
    if entry_value and sl and tp1 and entry_value != sl:
        rr_val = (tp1 - entry_value) / abs(entry_value - sl)

    # --- ŠPECIÁLNA LOGIKA PRE PMCC ---
    pmcc = data.get('pmcc')
    if data.get('option_strategy') == 'PMCC' and pmcc:
        # Pre PMCC prepíšeme SL/TP hodnoty na tie, ktoré dávajú zmysel pre opcie
        # SL = Strike dlhej opcie (ak tam akcia klesne, sme hlboko v strate)
        sl = pmcc['leaps_data']['strike']
        # TP1 = Strike krátkej opcie (maximálny zisk stratégie)
        tp1 = pmcc['short_data']['strike']
        # TP2 = Vyšší pivot alebo +5% nad short strike
        tp2 = tp1 * 1.05
        
        # Prepočítať R:R na základe ceny akcie (len orientačne)
        if entry_value and sl and tp1 and entry_value != sl:
            rr_val = (tp1 - entry_value) / abs(entry_value - sl)
            
        plan_vars['option_reason'].set(
            f"Vstup: Debet {pmcc['debit']}$ | "
            f"SL (Akcia): pod {sl}$ (alebo -50% debetu) | "
            f"TP (Akcia): {tp1}$"
        )

    # 4. Set variables
    plan_vars['entry'].set(_fmt(entry))
    plan_vars['sl'].set(_fmt(sl))
    plan_vars['tp1'].set(_fmt(tp1))
    plan_vars['tp2'].set(_fmt(tp2))
    plan_vars['rr'].set(f"{rr_val:.2f}:1" if rr_val else "—")
    plan_vars['action'].set(data.get('action', '—'))
    plan_vars['strategy'].set(data.get('strategy_label', '—'))
    plan_vars['reason'].set(data.get('strategy_reason', '—'))
    plan_vars['option_strategy'].set(data.get('option_strategy', '—'))
    
    # Pre PMCC sme už nastavili option_reason vyššie, nepripisovať ho znova ak už je nastavený
    if not (data.get('option_strategy') == 'PMCC' and pmcc):
        plan_vars['option_reason'].set(data.get('option_reason', data.get('strategy_reason', '—')))
    
    ml_prob = data.get('ml_prob')
    if ml_prob is not None:
        plan_vars['ml_prob'].set(f"{ml_prob*100:.0f}%")
    else:
        plan_vars['ml_prob'].set("—")


def open_tws_execution_window(state, symbol, plan_vars, summary):
    """Okno pre odoslanie objednávky do TWS na základe trade plánu s podporou Combo."""
    window = tk.Toplevel(state.root)
    window.title(f"Odoslať do TWS - {symbol}")
    window.geometry("520x680")
    window.transient(state.root)

    # --- PREMENNÉ ---
    order_type_var = tk.StringVar(value="OPTION")
    
    # Auto-detekcia režimu podľa odporúčanej stratégie
    opt_strat = plan_vars.get('option_strategy', tk.StringVar(value="")).get().upper()
    initial_mode = "SINGLE"
    initial_right = "CALL"
    
    if "PUT" in opt_strat:
        initial_right = "PUT"
    elif "CALL" in opt_strat:
        initial_right = "CALL"
    
    if "SPREAD" in opt_strat:
        initial_mode = "SPREAD"
    elif "CALENDAR" in opt_strat or "DIAGONAL" in opt_strat:
        initial_mode = "ROLL"
    elif "PMCC" in opt_strat:
        initial_mode = "PMCC"

    combo_mode_var = tk.StringVar(value=initial_mode) # SINGLE, SPREAD, ROLL, PMCC
    
    action_raw = plan_vars['action'].get().upper()
    default_action = "BUY"
    if any(x in action_raw for x in ("SELL", "SHORT", "VÝSTUP", "BEAR")):
        default_action = "SELL"
    
    # Leg 1
    l1_action = tk.StringVar(value=default_action)
    l1_qty = tk.StringVar(value="1")
    l1_right = tk.StringVar(value=initial_right)
    l1_expiry = tk.StringVar()
    l1_strike = tk.StringVar()
    l1_greeks = tk.StringVar(value="Cena: — | Δ: — | Θ: —")
    
    # Leg 2
    l2_action = tk.StringVar(value="SELL" if default_action == "BUY" else "BUY")
    l2_qty = tk.StringVar(value="1")
    l2_right = tk.StringVar(value=initial_right)
    l2_expiry = tk.StringVar()
    l2_strike = tk.StringVar()
    l2_greeks = tk.StringVar(value="Cena: — | Δ: — | Θ: —")
    
    net_price_var = tk.StringVar(value="0.00")
    
    # NOVÉ: Targety z plánu
    sl_target = plan_vars['sl'].get()
    tp_target = plan_vars['tp1'].get()
    
    strategy_desc_var = tk.StringVar(value="SINGLE OPTION")

    # --- UI ---
    main_frame = ttk.Frame(window, padding=15)
    main_frame.pack(fill='both', expand=True)

    header_frame = ttk.Frame(main_frame)
    header_frame.pack(fill='x', pady=(0, 10))
    ttk.Label(header_frame, text=f"Symbol: {symbol}", font=('Arial', 11, 'bold')).pack(side='left')
    
    strat_lbl = tk.Label(header_frame, textvariable=strategy_desc_var, font=('Arial', 10, 'bold'), 
                         relief='ridge', padx=10, pady=2)
    strat_lbl.pack(side='right')

    def update_strat_desc(*a):
        m = combo_mode_var.get()
        t = order_type_var.get()
        if t == "STOCK":
            strategy_desc_var.set("STOCK ORDER")
            strat_lbl.config(fg="black", bg="#f0f0f0")
            return
        
        if m == "SINGLE":
            desc = f"LONG {l1_right.get()}" if l1_action.get() == "BUY" else f"SHORT {l1_right.get()}"
            strategy_desc_var.set(desc)
            strat_lbl.config(fg="#2c3e50", bg="#ecf0f1")
            return

        if m == "PMCC":
            strategy_desc_var.set("POOR MAN'S COVERED CALL")
            strat_lbl.config(fg="#2e7d32", bg="#e8f5e9")
            return

        act1, act2 = l1_action.get(), l2_action.get()
        str1, str2 = 0.0, 0.0
        try: 
            str1 = float(l1_strike.get() or 0)
            str2 = float(l2_strike.get() or 0)
        except: pass
        exp1, exp2 = l1_expiry.get(), l2_expiry.get()
        rig1, rig2 = l1_right.get(), l2_right.get()

        desc = "CUSTOM COMBO"
        color = "#2980b9"; bg = "#e1f5fe"

        if exp1 == exp2 and rig1 == rig2:
            if rig1 == "PUT":
                if act1 == "SELL" and act2 == "BUY" and str1 > str2: desc = "BULL PUT SPREAD"; color = "#2e7d32"; bg = "#e8f5e9"
                elif act1 == "BUY" and act2 == "SELL" and str1 < str2: desc = "BULL PUT SPREAD"; color = "#2e7d32"; bg = "#e8f5e9"
                else: desc = "BEAR PUT SPREAD"; color = "#c62828"; bg = "#ffebee"
            else: # CALL
                if act1 == "BUY" and act2 == "SELL" and str1 < str2: desc = "BULL CALL SPREAD"; color = "#2e7d32"; bg = "#e8f5e9"
                elif act1 == "SELL" and act2 == "BUY" and str1 > str2: desc = "BULL CALL SPREAD"; color = "#2e7d32"; bg = "#e8f5e9"
                else: desc = "BEAR CALL SPREAD"; color = "#c62828"; bg = "#ffebee"
        elif exp1 != exp2 and rig1 == rig2:
            desc = "CALENDAR SPREAD" if str1 == str2 else "DIAGONAL SPREAD"
            color = "#673ab7"; bg = "#f3e5f5"
        elif exp1 == exp2 and rig1 != rig2:
            desc = "STRADDLE" if str1 == str2 else "STRANGLE"
            color = "#ff9800"; bg = "#fff3e0"

        if exp1 and exp2 and exp1 < exp2 and act1 == "SELL" and act2 == "BUY":
            desc = f"ROLL OUT ({desc})"

        strategy_desc_var.set(desc)
        strat_lbl.config(fg=color, bg=bg)

    # Typ aktíva
    type_frame = ttk.Frame(main_frame)
    type_frame.pack(fill='x', pady=5)
    ttk.Radiobutton(type_frame, text="Akcie (STK)", variable=order_type_var, value="STOCK").pack(side='left', padx=10)
    ttk.Radiobutton(type_frame, text="Opcia (OPT)", variable=order_type_var, value="OPTION").pack(side='left', padx=10)

    # Combo Mode (len pre OPT)
    combo_frame = ttk.LabelFrame(main_frame, text="Režim stratégie (len pre opcie)", padding=5)
    combo_frame.pack(fill='x', pady=5)
    modes = [("Single Leg", "SINGLE"), ("Vertical Spread", "SPREAD"), ("Roll / Custom", "ROLL"), ("PMCC", "PMCC")]
    for text, val in modes:
        ttk.Radiobutton(combo_frame, text=text, variable=combo_mode_var, value=val).pack(side='left', padx=5)

    # Spoločné parametre
    params_frame = ttk.LabelFrame(main_frame, text="Základné parametre", padding=10)
    params_frame.pack(fill='x', pady=5)
    
    ttk.Label(params_frame, text="Net Limit Cena:").grid(row=0, column=0, sticky='w')
    ttk.Entry(params_frame, textvariable=net_price_var, width=12).grid(row=0, column=1, sticky='w', padx=5)
    ttk.Label(params_frame, text="(Debet/Kredit)", font=('Arial', 8, 'italic')).grid(row=0, column=2, sticky='w')

    # Zobrazenie targetov z plánu pre orientáciu
    target_frame = ttk.Frame(params_frame)
    target_frame.grid(row=1, column=0, columnspan=3, sticky='w', pady=(5,0))
    ttk.Label(target_frame, text=f"Plánované výstupy (Akcia):", font=('Arial', 8, 'bold')).pack(side='left')
    ttk.Label(target_frame, text=f" SL: {sl_target}$ | TP: {tp_target}$", font=('Arial', 8), foreground='#c62828').pack(side='left', padx=5)

    # LEGS container
    legs_canvas = tk.Canvas(main_frame, highlightthickness=0)
    legs_canvas.pack(fill='both', expand=True)
    legs_frame = ttk.Frame(legs_canvas)
    legs_canvas.create_window((0,0), window=legs_frame, anchor='nw')

    def build_leg_ui(parent, title, act_v, qty_v, rig_v, exp_v, str_v, grk_v):
        f = ttk.LabelFrame(parent, text=title, padding=10)
        f.pack(fill='x', pady=5)
        
        # Row 0: Action, Qty, Greeks
        row0 = ttk.Frame(f)
        row0.grid(row=0, column=0, columnspan=4, sticky='w')
        ttk.Label(row0, text="Akcia:").pack(side='left')
        ttk.Combobox(row0, textvariable=act_v, values=["BUY", "SELL"], width=7, state='readonly').pack(side='left', padx=5)
        ttk.Label(row0, text="Množstvo:").pack(side='left', padx=(10,0))
        ttk.Entry(row0, textvariable=qty_v, width=5).pack(side='left', padx=5)
        ttk.Label(row0, textvariable=grk_v, font=('Courier', 9, 'bold'), foreground='#2e7d32').pack(side='left', padx=(20,0))
        
        # Row 1: Type, Strike
        ttk.Label(f, text="Typ:").grid(row=1, column=0, sticky='w', pady=5)
        ttk.Combobox(f, textvariable=rig_v, values=["CALL", "PUT"], width=7, state='readonly').grid(row=1, column=1, padx=5, sticky='w')
        
        ttk.Label(f, text="Strike:").grid(row=1, column=2, sticky='w', padx=(10,0))
        s_combo = ttk.Combobox(f, textvariable=str_v, width=10)
        s_combo.grid(row=1, column=3, padx=5, sticky='w')
        
        # Row 2: Expiry
        ttk.Label(f, text="Expirácia:").grid(row=2, column=0, sticky='w')
        e_combo = ttk.Combobox(f, textvariable=exp_v, width=15)
        e_combo.grid(row=2, column=1, columnspan=2, padx=5, sticky='w')
        
        def load_strikes(*a):
            p = state.port_var.get()
            ex = exp_v.get()
            ri = rig_v.get()
            if not ex: return
            def _run_s():
                try:
                    script = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'scripts', 'tws_fetch_strikes.py')
                    res = subprocess.run([sys.executable, script, p, symbol, ex, ri], capture_output=True, text=True, timeout=30)
                    if res.returncode == 0:
                        data = json.loads(res.stdout)
                        if data.get('success'):
                            stks = [str(s) for s in data['strikes']]
                            window.after(0, lambda: s_combo.config(values=stks))
                except: pass
            threading.Thread(target=_run_s, daemon=True).start()

        def load_greeks(*a):
            p = state.port_var.get()
            ex = exp_v.get()
            ri = rig_v.get()[0] # C or P
            sk = str_v.get()
            if not ex or not sk: return
            grk_v.set("Cena: ... | Δ: ... | Θ: ...")
            def _run_g():
                try:
                    script = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'scripts', 'tws_fetch_option.py')
                    res = subprocess.run([sys.executable, script, p, symbol, ex, sk, ri], capture_output=True, text=True, timeout=30)
                    if res.returncode == 0:
                        data = json.loads(res.stdout)
                        pr = data.get('price', 0)
                        d = data.get('delta', 0)
                        t = data.get('theta', 0)
                        window.after(0, lambda: grk_v.set(f"Cena: {pr:.2f} | Δ: {d:+.2f} | Θ: {t:+.2f}"))
                except: pass
            threading.Thread(target=_run_g, daemon=True).start()

        exp_v.trace_add('write', load_strikes)
        exp_v.trace_add('write', update_strat_desc)
        str_v.trace_add('write', load_greeks)
        str_v.trace_add('write', update_strat_desc)
        rig_v.trace_add('write', load_strikes)
        rig_v.trace_add('write', update_strat_desc)
        act_v.trace_add('write', update_strat_desc)

        def load_exps():
            p = state.port_var.get()
            r = 'C' if rig_v.get() == "CALL" else 'P'
            def _run():
                try:
                    script = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'scripts', 'tws_load_expiries.py')
                    res = subprocess.run([sys.executable, script, p, symbol, r], capture_output=True, text=True, timeout=30)
                    if res.returncode == 0 and res.stdout.strip():
                        exs = res.stdout.strip().split(',')
                        window.after(0, lambda: e_combo.config(values=exs))
                        if exs and not exp_v.get(): window.after(0, lambda: exp_v.set(exs[0]))
                except: pass
            threading.Thread(target=_run, daemon=True).start()
            
        ttk.Button(f, text="🔄", width=3, command=load_exps).grid(row=2, column=3, padx=5)
        return f

    f_l1 = build_leg_ui(legs_frame, "Leg 1 (Hlavná)", l1_action, l1_qty, l1_right, l1_expiry, l1_strike, l1_greeks)
    f_l2 = build_leg_ui(legs_frame, "Leg 2 (Combo)", l2_action, l2_qty, l2_right, l2_expiry, l2_strike, l2_greeks)

    def refresh_visibility(*a):
        m = combo_mode_var.get()
        t = order_type_var.get()
        if t == "STOCK":
            combo_frame.pack_forget()
            f_l2.pack_forget()
            f_l1.config(text="Parametre Akcie")
            # Skryť opčné polia v Leg 1
            for slave in f_l1.grid_slaves():
                info = slave.grid_info()
                if info.get('row') in (1, 2): slave.grid_remove()
        else:
            combo_frame.pack(fill='x', pady=5, before=params_frame)
            f_l1.config(text="Leg 1")
            for slave in f_l1.grid_slaves(): slave.grid_item()
            if m == "SINGLE":
                f_l2.pack_forget()
            else:
                f_l2.pack(fill='x', pady=5)
                if m == "SPREAD":
                    l2_expiry.set(l1_expiry.get()) # Spread máva rovnakú expiráciu
                    l2_right.set(l1_right.get())
                    l2_action.set("SELL" if l1_action.get()=="BUY" else "BUY")
                elif m == "PMCC":
                    # PMCC: Leg 1 je Long (vzdialený), Leg 2 je Short (blízky)
                    l1_action.set("BUY")
                    l2_action.set("SELL")
                    l1_right.set("CALL")
                    l2_right.set("CALL")

    order_type_var.trace_add('write', refresh_visibility)
    order_type_var.trace_add('write', update_strat_desc)
    combo_mode_var.trace_add('write', refresh_visibility)
    combo_mode_var.trace_add('write', update_strat_desc)
    l1_expiry.trace_add('write', lambda *a: l2_expiry.set(l1_expiry.get()) if combo_mode_var.get()=="SPREAD" else None)

    status_var = tk.StringVar(value="Pripravený")
    ttk.Label(main_frame, textvariable=status_var, font=('Arial', 8, 'italic'), foreground='blue').pack(pady=5)

    def execute_order():
        if not state.connected:
            messagebox.showerror("TWS", "Nie ste pripojený k TWS!")
            return
        
        status_var.set("Odosielam do TWS...")
        btn_exec.config(state='disabled')
        
        def _run_exec():
            try:
                root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
                port = state.port_var.get()
                
                if order_type_var.get() == "STOCK":
                    script = os.path.join(root_dir, 'scripts', 'tws_rebalance_stock.py')
                    q = int(l1_qty.get())
                    if l1_action.get() == "SELL": q = -q
                    cmd = [sys.executable, script, '--symbol', symbol, '--quantity', str(q), '--port', port]
                    try:
                        p = float(net_price_var.get())
                        if p > 0: cmd += ['--price', str(p)]
                    except: pass
                else:
                    script = os.path.join(root_dir, 'scripts', 'tws_place_order.py')
                    cmd = [sys.executable, script, '--symbol', symbol, '--qty', l1_qty.get(), '--port', port, '--action', l1_action.get()]
                    cmd += ['--expiry', l1_expiry.get()]
                    if l1_right.get() == "CALL": cmd += ['--call-strike', l1_strike.get()]
                    else: cmd += ['--put-strike', l1_strike.get()]
                    
                    if combo_mode_var.get() != "SINGLE":
                        if l2_right.get() == "CALL": cmd += ['--call-strike-2', l2_strike.get()]
                        else: cmd += ['--put-strike-2', l2_strike.get()]
                        if l2_expiry.get() != l1_expiry.get(): cmd += ['--expiry-2', l2_expiry.get()]
                        cmd += ['--action-2', l2_action.get()]
                    
                    # Vždy poslať zadanú limit cenu
                    try:
                        p_val = float(net_price_var.get())
                        cmd += ['--price', str(p_val)]
                    except: pass

                if port != "7497": cmd.append('--live')
                
                res = subprocess.run(cmd, capture_output=True, text=True, timeout=45)
                out = json.loads(res.stdout) if res.stdout else {}
                if out.get('success'):
                    window.after(0, lambda: [status_var.set("✅ Úspech"), messagebox.showinfo("TWS", out.get('msg', 'Odoslané'))])
                else:
                    window.after(0, lambda: [status_var.set("❌ Chyba"), messagebox.showerror("TWS", out.get('error', 'Chyba'))])
            except Exception as e:
                window.after(0, lambda: messagebox.showerror("TWS", str(e)))
            finally:
                window.after(0, lambda: btn_exec.config(state='normal'))

        threading.Thread(target=_run_exec, daemon=True).start()

    def prepare_exit():
        """Otočí akcie nôh pre okamžitý výstup z pozície"""
        l1_act = l1_action.get()
        l2_act = l2_action.get()
        l1_action.set("SELL" if l1_act == "BUY" else "BUY")
        l2_action.set("BUY" if l2_act == "SELL" else "SELL")
        
        # Zmena vizuálu na EXIT režim
        strategy_desc_var.set(f"EXIT: {strategy_desc_var.get()}")
        strat_lbl.config(fg="white", bg="#c62828")
        btn_exec.config(text="🚨 ODOVZDAŤ EXIT PRÍKAZ")
        status_var.set("⚠️ REŽIM UKONČENIA POZÍCIE (EXIT)")
        messagebox.showinfo("Emergency Exit", "Príkazy nôh boli otočené pre UKONČENIE pozície.\nSkontrolujte Limit Cenu pred odoslaním!")

    # Pridanie Emergency Exit tlačidla pred hlavné odosielacie tlačidlo
    exit_frame = ttk.Frame(main_frame)
    exit_frame.pack(fill='x', pady=(5, 0))
    
    btn_exit = tk.Button(exit_frame, text="🚨 EMERGENCY EXIT (Otočiť na výstup)", 
                         bg="#ffebee", fg="#c62828", font=('Arial', 9, 'bold'),
                         relief='groove', command=prepare_exit)
    btn_exit.pack(fill='x')

    btn_exec = ttk.Button(main_frame, text="🚀 ODOSLAŤ OBJEDNÁVKU", command=execute_order)
    btn_exec.pack(pady=10, fill='x')
    ttk.Button(main_frame, text="Zavrieť", command=window.destroy).pack()

    # Ak máme PMCC dáta v summary, predvyplníme
    pmcc = summary.get('pmcc')
    if pmcc:
        order_type_var.set("OPTION")
        combo_mode_var.set("PMCC")
        l1_action.set("BUY")
        l1_expiry.set(pmcc['leaps_data']['expiry'])
        l1_strike.set(str(pmcc['leaps_data']['strike']))
        l1_right.set("CALL")
        
        l2_action.set("SELL")
        l2_expiry.set(pmcc['short_data']['expiry'])
        l2_strike.set(str(pmcc['short_data']['strike']))
        l2_right.set("CALL")
        
        net_price_var.set(pmcc['debit'])

    refresh_visibility()


def load_cached_candles(symbol, timeframe="1 day"):
    """Načíta sviečky z cache pre potreby grafu."""
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    cache_dir = os.path.join(root, 'cache', 'history')
    timeframe_clean = timeframe.replace(' ', '_')
    
    # 1. Skúsime priamy názov (starý formát)
    filename = f"{symbol}_{timeframe_clean}.json"
    path = os.path.join(cache_dir, filename)
    
    if not os.path.exists(path):
        # 2. Skúsime hľadať súbor s akýmkoľvek duration (nový formát)
        import glob
        pattern = os.path.join(cache_dir, f"{symbol}_{timeframe_clean}_*.json")
        matches = glob.glob(pattern)
        if matches:
            # Zoberieme najnovší (podľa mtime)
            path = max(matches, key=os.path.getmtime)
        else:
            return []

    try:
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
            return data.get('candles', [])
    except Exception:
        return []

def generate_ai_analysis(symbol, summary):
    """Vygeneruje textovú analýzu na základe dát zo Swing Huntera s dôrazom na momentum."""
    price = summary.get('price', 0)
    rsi = summary.get('rsi', 0)
    pct_b = summary.get('pct_b', 0)
    trend = summary.get('trend_label', 'Neutral')
    zone = summary.get('zone', 'neutral')
    macd = summary.get('macd', {})
    ml_prob = summary.get('ml_prob', 0)
    adx = summary.get('adx', 0)
    pdi = summary.get('pdi', 0)
    mdi = summary.get('mdi', 0)
    
    analysis = [f"--- Inteligentná analýza {symbol} ---"]
    
    # 1. Trend a MA200
    trend_txt = "býčom" if trend == "Býk" else "medveďom" if trend == "Bear" else "neutrálnom"
    analysis.append(f"• TREND: Dlhodobo sa nachádzame v {trend_txt} trende (cena {price:.2f}).")

    # 1b. Sila trendu (ADX)
    if adx > 25:
        adx_txt = f"🟢 SILNÝ ({adx:.1f})"
    elif adx > 20:
        adx_txt = f"🟡 MIERNY ({adx:.1f})"
    else:
        adx_txt = f"⚪ SLABÝ / STRANA ({adx:.1f})"
    
    dmi_txt = "Býčie (+DI > -DI)" if pdi > mdi else "Medvedie (-DI > +DI)"
    analysis.append(f"• SILA TRENDU (ADX): {adx_txt}. Smerovanie DMI: {dmi_txt}.")
    
    # 2. Momentum (MACD) - KĽÚČOVÉ ZLEPŠENIE
    macd_val = macd.get('macd', 0)
    sig_val = macd.get('signal', 0)
    is_cross = macd.get('is_cross', False)
    
    if macd_val < sig_val:
        momentum_txt = "🔴 NEGATÍVNE (Bearish)"
        if is_cross:
            momentum_txt += " - ČERSTVÝ PREDPREDAJNÝ SIGNÁL!"
        analysis.append(f"• MOMENTUM (MACD): {momentum_txt}. Cena stráca silu a klesá.")
    else:
        momentum_txt = "🟢 POZITÍVNE (Bullish)"
        if is_cross:
            momentum_txt += " - ČERSTVÝ NÁKUPNÝ SIGNÁL!"
        analysis.append(f"• MOMENTUM (MACD): {momentum_txt}. Sila kupujúcich rastie.")

    # 3. Indikátory a Zóna
    if zone == 'hunt':
        analysis.append("• ZÓNA: Nákupná oblasť (Hunt Zone). Dobré pre Mean Reversion.")
    elif zone == 'risk':
        analysis.append("• ZÓNA: Riziková oblasť (Risk). Hrozí vyčerpanie kupujúcich.")
    
    ind_parts = []
    if rsi > 70: ind_parts.append(f"RSI ({rsi:.1f}) je prekúpené")
    elif rsi < 30: ind_parts.append(f"RSI ({rsi:.1f}) je prepredané")
    else: ind_parts.append(f"RSI ({rsi:.1f}) je v neutrálnom pásme")
    
    if pct_b > 100: ind_parts.append("cena je nad Bollingerovými pásmami")
    elif pct_b < 0: ind_parts.append("cena je pod Bollingerovými pásmami")
    
    analysis.append(f"• INDIKÁTORY: {', '.join(ind_parts)}.")

    # 4. Syntéza a odporúčanie
    analysis.append("\n--- ZÁVER A ODPORÚČANIE ---")
    strat = summary.get('option_strategy', 'žiadna')
    
    # Prísnejšia logika zhody
    dmi_bullish = pdi > mdi
    macd_bullish = macd_val > sig_val
    trend_bullish = trend == "Býk"
    
    # Detekcia konfliktov
    if adx < 20:
        analysis.append(f"⚠️ POZOR: Trh nemá jasnú silu (ADX {adx:.1f} < 20).")
        analysis.append(f"V bočnom trhu sú smerové stratégie ako {strat} riskantné.")
        analysis.append("Odporúčam skôr neutrálne stratégie (napr. Bull Put Spread s veľkým vankúšom).")
    elif trend_bullish and not dmi_bullish:
        analysis.append(f"⚠️ KONFLIKT: Dlhodobý trend je Býčí, ale krátkodobé smerovanie (DMI) je MEDVEDIE.")
        analysis.append(f"Strategia {strat} je momentálne predčasná. Počkajte na +DI > -DI.")
    elif macd_val < sig_val and trend_bullish:
        analysis.append(f"Hoci je trend Býčí, MACD varuje pred poklesom (PULLBACK).")
        analysis.append(f"NAVROHOVANÁ STRATÉGIA ({strat}) JE RIZIKOVÁ. Počkajte na otočenie MACD do zelena.")
    elif macd_bullish and trend_bullish and dmi_bullish:
        if adx > 25:
            analysis.append(f"✅ EXCELENTNÁ ZHODA: Trend, Momentum, Smer (DMI) aj Sila (ADX) sú v súlade.")
            analysis.append(f"Stratégia {strat} má v týchto podmienkach najvyššiu šancu na úspech.")
        else:
            analysis.append(f"Trend, Momentum aj DMI sú v zhode. Sila trendu (ADX) je mierna, ale smer je správny.")
            analysis.append(f"Stratégia {strat} je vhodná.")
    else:
        analysis.append(f"Odporúčaná stratégia: {strat}")
        analysis.append("Podmienky nie sú ideálne, postupujte opatrne.")

    # 5. Konkrétne opčné parametre
    analysis.append("\n--- NÁVRH KONKRÉTNYCH PARAMETROV ---")
    atr = summary.get('atr') or (price * 0.02)
    pivots = summary.get('pivots', {})
    s1 = pivots.get('S1') or (price - (1.5 * atr))
    r1 = pivots.get('R1') or (price + (1.5 * atr))
    
    exp_days = "30-45 dní" if "Spread" in strat else "14-28 dní"
    analysis.append(f"• ODPORÚČANÁ EXPIRÁCIA: cca {exp_days}")

    if "Call debit" in strat:
        l_str = round(price)
        s_str = round(r1)
        if s_str <= l_str: s_str = l_str + 2
        analysis.append(f"• NÁVRH STRIKOV: BUY Call {l_str} / SELL Call {s_str}")
        analysis.append(f"• Cieľ (TP): {s_str} | Max strata (SL): pod {s1:.2f}")

    elif "Bull put" in strat:
        s_str = round(s1)
        l_str = s_str - 2
        analysis.append(f"• NÁVRH STRIKOV: SELL Put {s_str} / BUY Put {l_str}")
        analysis.append(f"• Bezpečný nákupný bod: nad {s_str}")

    elif "Bear call" in strat:
        s_str = round(r1)
        l_str = s_str + 2
        analysis.append(f"• NÁVRH STRIKOV: SELL Call {s_str} / BUY Call {l_str}")
        analysis.append(f"• Hranica rizika: {s_str}")

    if ml_prob:
        analysis.append(f"\nPravdepodobnosť úspechu podľa ML: {ml_prob*100:.0f}%")

    return "\n".join(analysis)

def open_chart_window(state, symbol, summary):
    """Otvorí okno s grafom a pivotmi."""
    if not MATPLOTLIB_AVAILABLE:
        messagebox.showerror("Graf", "Knižnica matplotlib nie je dostupná. Nainštalujte ju pomocou:\npip install matplotlib")
        return

    # Načítanie dát (denné pre pivoty + aktuálne pre detail)
    daily_candles = load_cached_candles(symbol, "1 day")
    current_tf = getattr(state, 'hunter_tf_v', tk.StringVar(value="4 hours")).get()
    detail_candles = load_cached_candles(symbol, current_tf)

    if not daily_candles and not detail_candles:
        messagebox.showwarning("Graf", f"Žiadne historické dáta pre {symbol} v cache.\nSkúste najprv 'VYHĽADAŤ PRÍLEŽITOSTI'.")
        return

    # Ak nemáme detailné, použijeme aspoň denné
    candles = detail_candles if detail_candles else daily_candles
    if len(candles) < 2:
        messagebox.showwarning("Graf", "Nedostatok dát pre vykreslenie grafu.")
        return

    # Pivoty (vždy z denného grafu)
    pivots = summary.get('pivots')
    if not pivots and daily_candles:
        # Skúsime vypočítať z predposlednej dennej sviečky
        if len(daily_candles) >= 2:
            pivots = calculate_pivots(daily_candles[-2])

    win = tk.Toplevel(state.root)
    win.title(f"Graf {symbol} ({current_tf})")
    win.geometry("850x700")

    # --- NOVÉ: Sekcia pre Inteligentnú analýzu (HORE) ---
    analysis_frame = ttk.LabelFrame(win, text="🤖 Inteligentná analýza", padding=10)
    analysis_frame.pack(fill='both', expand=True, side='top', padx=10, pady=10)
    
    analysis_text = tk.Text(analysis_frame, height=15, font=('Arial', 11), wrap='word', bg='#f9f9f9', relief='flat')
    analysis_text.pack(fill='both', side='left', expand=True)
    
    analysis_scroll = ttk.Scrollbar(analysis_frame, command=analysis_text.yview)
    analysis_scroll.pack(side='right', fill='y')
    analysis_text.config(yscrollcommand=analysis_scroll.set)

    def show_analysis():
        report = generate_ai_analysis(symbol, summary)
        analysis_text.config(state='normal')
        analysis_text.delete('1.0', tk.END)
        analysis_text.insert('1.0', report)
        analysis_text.config(state='disabled')

    # Spustiť analýzu automaticky pri otvorení
    show_analysis()

    ttk.Button(analysis_frame, text="🔄 Obnoviť analýzu", command=show_analysis).pack(side='bottom', pady=(5,0))

    # --- GRAF (DOLE A MENŠÍ) ---
    fig = Figure(figsize=(8, 2.0), dpi=100)
    ax = fig.add_subplot(111)

    # Príprava dát pre sviečky
    import numpy as np
    
    # Zoberieme posledných 40 sviečok pre prehľadnosť
    plot_candles = candles[-40:]
    prices = [c['close'] for c in plot_candles]
    highs = [c['high'] for c in plot_candles]
    lows = [c['low'] for c in plot_candles]
    opens = [c['open'] for c in plot_candles]
    x = np.arange(len(plot_candles))

    # Vykreslenie tieňov a tiel sviečok
    for i in range(len(plot_candles)):
        color = 'green' if prices[i] >= opens[i] else 'red'
        ax.plot([i, i], [lows[i], highs[i]], color=color, linewidth=1)
        ax.add_patch(patches.Rectangle((i - 0.3, min(opens[i], prices[i])), 0.6, abs(opens[i] - prices[i]), color=color))

    # Vykreslenie hladín (Pivots)
    if pivots:
        colors = {'P': 'blue', 'S1': 'orange', 'S2': 'red', 'R1': 'orange', 'R2': 'red'}
        for name, val in pivots.items():
            if val and name in colors:
                ax.axhline(y=val, color=colors[name], linestyle='--', alpha=0.6, label=f"{name}: {val:.2f}")
                ax.text(len(plot_candles)-1, val, f" {name}", color=colors[name], va='center', fontweight='bold')

    # Aktuálna cena
    curr_price = summary.get('price')
    if curr_price:
        ax.axhline(y=curr_price, color='black', linestyle=':', alpha=0.8)
        ax.text(0, curr_price, f" Teraz: {curr_price:.2f}", color='black', va='bottom', fontsize=9, bbox=dict(facecolor='white', alpha=0.5))

    ax.set_title(f"{symbol} - {current_tf} (Zmenšený náhľad)", fontsize=10)
    ax.grid(True, alpha=0.3)
    ax.set_ylabel("Cena", fontsize=8)
    
    # Odstránenie X osi (indexy nie sú dôležité)
    ax.set_xticks([])

    canvas = FigureCanvasTkAgg(fig, master=win)
    canvas.draw()
    canvas.get_tk_widget().pack(fill='x', side='bottom', padx=10, pady=(0, 10))

    # Legenda
    if pivots:
        ax.legend(loc='upper left', fontsize='x-small')

def open_trade_plan_window(state, summary):
    symbol = summary.get('symbol')
    if not symbol:
        return
    plan_windows = getattr(state, 'hunter_trade_plan_windows', {})
    existing = plan_windows.get(symbol)
    if existing and existing.winfo_exists():
        existing.lift()
        existing.focus_force()
        refresh_trade_plan_vars(state, existing, symbol, state.hunter_symbol_summaries.get(symbol, summary))
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
        state.root.after(1500, lambda: refresh_trade_plan_vars(state, window, symbol, state.hunter_symbol_summaries.get(symbol, summary)))

    def show_chart():
        open_chart_window(state, symbol, summary)

    ttk.Button(btn_frame, text="📊 Graf", command=show_chart).pack(side='left', padx=5)
    ttk.Button(btn_frame, text="🔄 Force refresh", command=refresh_plan).pack(side='left')
    ttk.Button(btn_frame, text="📂 Uložené plány", command=lambda: open_saved_trade_plan_browser(state, plan_vars)).pack(side='left', padx=5)
    ttk.Button(btn_frame, text="💾 Uložiť plán", command=lambda: save_trade_plan_to_file(symbol, plan_vars)).pack(side='left', padx=5)
    ttk.Button(btn_frame, text="🚀 Odoslať do TWS", command=lambda: open_tws_execution_window(state, symbol, plan_vars, summary)).pack(side='left', padx=5)

    def on_close():
        plan_windows.pop(symbol, None)
        window.destroy()

    ttk.Button(btn_frame, text="Zavrieť", command=on_close).pack(side='right')
    window.protocol("WM_DELETE_WINDOW", on_close)

    refresh_trade_plan_vars(state, window, symbol, state.hunter_symbol_summaries.get(symbol, summary))
