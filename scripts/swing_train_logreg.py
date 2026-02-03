#!/usr/bin/env python3
"""
Offline tréning jednoduchej logistickej regresie pre Swing Hunter.
Zdroj: swing_hunter_log.csv
Výstup: swing_model.json (koeficienty a feature mapping) + metriky (train/val)
"""
import csv
import json
import math
import os
from typing import List, Tuple

LOG_FILE = "swing_hunter_log.csv"
MODEL_FILE = "swing_model.json"
BACKTEST_FILE = "swing_backtest.csv"
PAPER_WEIGHT = 0.5


def bucket_pctb(pctb_str: str) -> str:
    try:
        val = float(pctb_str)
    except Exception:
        return "pctb:n/a"
    if val < 30:
        return "pctb:<30"
    if val < 80:
        return "pctb:30-80"
    if val < 100:
        return "pctb:80-100"
    return "pctb:>100"


def bucket_rsi(rsi_str: str) -> str:
    try:
        val = float(rsi_str)
    except Exception:
        return "rsi:n/a"
    if val < 30:
        return "rsi:<30"
    if val < 50:
        return "rsi:30-50"
    if val < 70:
        return "rsi:50-70"
    return "rsi:>=70"


def bucket_signal(sig: str) -> str:
    s = (sig or "").lower()
    if "strong buy" in s:
        return "sig:strong_buy"
    if "vhodný vstup" in s or "buy" in s:
        return "sig:buy"
    if "risk" in s or "riziko" in s:
        return "sig:risk"
    if "take profit" in s or "exit" in s:
        return "sig:exit"
    return "sig:other"


def load_dataset(path: str, sample_weight=1.0):
    X = []
    y = []
    w = []
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for r in reader:
            pl = r.get("FinalPL", "")
            if not pl:
                continue
            try:
                pl_f = float(pl)
            except Exception:
                continue
            target = 1 if pl_f > 0 else 0
            feats = [
                bucket_pctb(r.get("PercentB", "")),
                bucket_rsi(r.get("RSI", "")),
                bucket_signal(r.get("SignalType", "")),
                f"tf:{(r.get('Timeframe') or '').strip()}",
            ]
            zone = (r.get("Zone") or "").lower()
            if zone:
                feats.append(f"zone:{zone}")
            trend = (r.get("Trend") or "").lower()
            if trend:
                feats.append(f"trend:{trend}")
            score = r.get("ScorePct")
            if score:
                try:
                    sval = float(score)
                    if sval < 40:
                        feats.append("score:<40")
                    elif sval < 60:
                        feats.append("score:40-60")
                    else:
                        feats.append("score:>=60")
                except Exception:
                    pass
            macd = r.get("MACD_Cross")
            if macd in ("1", "True", "true"):
                feats.append("macd:cross")
            rvi_gt = r.get("RVI_gt_Sig")
            if rvi_gt in ("1", "True", "true"):
                feats.append("rvi:gt_sig")
            pdist = r.get("PivotDist")
            if pdist:
                try:
                    pval = float(pdist)
                    if abs(pval) < 1:
                        feats.append("pdist:<1")
                    elif abs(pval) < 3:
                        feats.append("pdist:1-3")
                    else:
                        feats.append("pdist:>3")
                except Exception:
                    pass
            X.append(feats)
            y.append(target)
            w.append(sample_weight)
    return X, y, w


def load_backtest(path: str, sample_weight=PAPER_WEIGHT):
    if not os.path.exists(path):
        return [], [], []
    X = []
    y = []
    w = []
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for r in reader:
            pl = r.get("BT_PL_pct", "")
            status = (r.get("BT_Status") or "").upper()
            if status in ("OPEN", "SKIP") or pl == "":
                continue
            try:
                pl_f = float(pl)
            except Exception:
                continue
            target = 1 if pl_f > 0 else 0
            feats = [
                bucket_pctb(r.get("PercentB", "")),
                bucket_rsi(r.get("RSI", "")),
                bucket_signal(r.get("Action", "")),
                f"tf:{(r.get('Timeframe') or '').strip()}",
            ]
            zone = (r.get("Zone") or "").lower()
            if zone:
                feats.append(f"zone:{zone}")
            trend = (r.get("Trend") or "").lower()
            if trend:
                feats.append(f"trend:{trend}")
            score = r.get("ScorePct")
            if score:
                try:
                    sval = float(score)
                    if sval < 40:
                        feats.append("score:<40")
                    elif sval < 60:
                        feats.append("score:40-60")
                    else:
                        feats.append("score:>=60")
                except Exception:
                    pass
            macd = r.get("MACD_Cross")
            if macd in ("1", "True", "true"):
                feats.append("macd:cross")
            rvi_gt = r.get("RVI_gt_Sig")
            if rvi_gt in ("1", "True", "true"):
                feats.append("rvi:gt_sig")
            pdist = r.get("PivotDist")
            if pdist:
                try:
                    pval = float(pdist)
                    if abs(pval) < 1:
                        feats.append("pdist:<1")
                    elif abs(pval) < 3:
                        feats.append("pdist:1-3")
                    else:
                        feats.append("pdist:>3")
                except Exception:
                    pass
            X.append(feats)
            y.append(target)
            w.append(sample_weight)
    return X, y, w


def build_vocab(X: List[List[str]]) -> Tuple[dict, List[str]]:
    vocab = {}
    for feats in X:
        for f in feats:
            if f not in vocab:
                vocab[f] = len(vocab)
    inv = [None] * len(vocab)
    for k, i in vocab.items():
        inv[i] = k
    return vocab, inv


def featurize(X: List[List[str]], vocab: dict):
    vecs = []
    for feats in X:
        v = [0.0] * len(vocab)
        for f in feats:
            idx = vocab.get(f)
            if idx is not None:
                v[idx] = 1.0
        vecs.append(v)
    return vecs


def sigmoid(z: float) -> float:
    return 1 / (1 + math.exp(-z))


def train_logreg(X, y, sample_w=None, lr=0.1, epochs=500):
    if not X:
        return []
    n = len(X)
    d = len(X[0])
    w = [0.0] * d
    if sample_w is None:
        sample_w = [1.0] * n
    for _ in range(epochs):
        for xi, yi, wi in zip(X, y, sample_w):
            z = sum(wj * xj for wj, xj in zip(w, xi))
            p = sigmoid(z)
            grad = [(p - yi) * xj * wi for xj in xi]
            for j in range(d):
                w[j] -= lr * grad[j]
    return w


def evaluate(X, y, w):
    if not X:
        return {"count": 0}
    tp = tn = fp = fn = 0
    for xi, yi in zip(X, y):
        z = sum(wj * xj for wj, xj in zip(w, xi))
        p = sigmoid(z)
        pred = 1 if p >= 0.5 else 0
        if pred == 1 and yi == 1:
            tp += 1
        elif pred == 0 and yi == 0:
            tn += 1
        elif pred == 1 and yi == 0:
            fp += 1
        else:
            fn += 1
    total = len(X)
    acc = (tp + tn) / total if total else 0
    return {"count": total, "acc": acc, "tp": tp, "tn": tn, "fp": fp, "fn": fn}


def train_val_split(X, y, val_ratio=0.2):
    n = len(X)
    if n < 5:
        return X, y, [], []
    split = int(n * (1 - val_ratio))
    return X[:split], y[:split], X[split:], y[split:]


def main():
    if not os.path.exists(LOG_FILE):
        print("No swing_hunter_log.csv found. Need closed trades to train.")
        return
    X_real, y_real, w_real = load_dataset(LOG_FILE, sample_weight=1.0)
    X_paper, y_paper, w_paper = load_backtest(BACKTEST_FILE, sample_weight=PAPER_WEIGHT)
    X_raw = X_real + X_paper
    y = y_real + y_paper
    w_all = w_real + w_paper
    if not X_raw:
        print("No trades with PL found; cannot train.")
        return
    vocab, inv = build_vocab(X_raw)
    X = featurize(X_raw, vocab)
    X_tr, y_tr, X_val, y_val = train_val_split(X, y, val_ratio=0.2)
    # Align weights with split
    w_tr, w_val = w_all[:len(X_tr)], w_all[len(X_tr):] if X_val else (w_all, [])
    model_w = train_logreg(X_tr, y_tr, sample_w=w_tr)
    metrics_train = evaluate(X_tr, y_tr, model_w)
    metrics_val = evaluate(X_val, y_val, model_w) if X_val else {}
    model = {
        "vocab": vocab,
        "weights": model_w,
        "metrics_train": metrics_train,
        "metrics_val": metrics_val,
        "used_backtest": len(X_paper)
    }
    with open(MODEL_FILE, "w", encoding="utf-8") as f:
        json.dump(model, f, indent=2)
    print(f"Model saved to {MODEL_FILE}. Train: {metrics_train} | Val: {metrics_val} | Paper: {len(X_paper)}")


if __name__ == "__main__":
    main()
#!/usr/bin/env python3
"""
Offline tréning jednoduchej logistickej regresie pre Swing Hunter.
Zdroj: swing_hunter_log.csv
Výstup: swing_model.json (koeficienty a feature mapping) + metriky (train/val)
"""
import csv
import json
import math
import os
from collections import Counter

from typing import List, Tuple

LOG_FILE = "swing_hunter_log.csv"
MODEL_FILE = "swing_model.json"

# --- Feature bucketing helpers ---

def bucket_pctb(pctb_str: str) -> str:
    try:
        val = float(pctb_str)
    except Exception:
        return "pctb:n/a"
    if val < 30:
        return "pctb:<30"
    if val < 80:
        return "pctb:30-80"
    if val < 100:
        return "pctb:80-100"
    return "pctb:>100"


def bucket_rsi(rsi_str: str) -> str:
    try:
        val = float(rsi_str)
    except Exception:
        return "rsi:n/a"
    if val < 30:
        return "rsi:<30"
    if val < 50:
        return "rsi:30-50"
    if val < 70:
        return "rsi:50-70"
    return "rsi:>=70"


def bucket_signal(sig: str) -> str:
    s = (sig or "").lower()
    if "strong buy" in s:
        return "sig:strong_buy"
    if "vhodný vstup" in s or "buy" in s:
        return "sig:buy"
    if "risk" in s or "riziko" in s:
        return "sig:risk"
    if "take profit" in s or "exit" in s:
        return "sig:exit"
    return "sig:other"


def load_dataset(path: str):
    X = []
    y = []
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for r in reader:
            pl = r.get("FinalPL", "")
            if not pl:
                continue  # potrebujeme uzavreté obchody
            try:
                pl_f = float(pl)
            except Exception:
                continue
            target = 1 if pl_f > 0 else 0
            feats = [
                bucket_pctb(r.get("PercentB", "")),
                bucket_rsi(r.get("RSI", "")),
                bucket_signal(r.get("SignalType", "")),
                f"tf:{(r.get('Timeframe') or '').strip()}",
            ]
            zone = (r.get("Zone") or "").lower()
            if zone:
                feats.append(f"zone:{zone}")
            trend = (r.get("Trend") or "").lower()
            if trend:
                feats.append(f"trend:{trend}")
            score = r.get("ScorePct")
            if score:
                try:
                    sval = float(score)
                    if sval < 40:
                        feats.append("score:<40")
                    elif sval < 60:
                        feats.append("score:40-60")
                    else:
                        feats.append("score:>=60")
                except Exception:
                    pass
            macd = r.get("MACD_Cross")
            if macd in ("1", "True", "true"):
                feats.append("macd:cross")
            rvi_gt = r.get("RVI_gt_Sig")
            if rvi_gt in ("1", "True", "true"):
                feats.append("rvi:gt_sig")
            pdist = r.get("PivotDist")
            if pdist:
                try:
                    pval = float(pdist)
                    if abs(pval) < 1:
                        feats.append("pdist:<1")
                    elif abs(pval) < 3:
                        feats.append("pdist:1-3")
                    else:
                        feats.append("pdist:>3")
                except Exception:
                    pass
            X.append(feats)
            y.append(target)
    return X, y


def build_vocab(X: List[List[str]]) -> Tuple[dict, List[str]]:
    vocab = {}
    for feats in X:
        for f in feats:
            if f not in vocab:
                vocab[f] = len(vocab)
    inv = [None] * len(vocab)
    for k, i in vocab.items():
        inv[i] = k
    return vocab, inv


def featurize(X: List[List[str]], vocab: dict):
    vecs = []
    for feats in X:
        v = [0.0] * len(vocab)
        for f in feats:
            idx = vocab.get(f)
            if idx is not None:
                v[idx] = 1.0
        vecs.append(v)
    return vecs


def sigmoid(z: float) -> float:
    return 1 / (1 + math.exp(-z))


def train_logreg(X, y, sample_w=None, lr=0.1, epochs=500):
    if not X:
        return []
    n = len(X)
    d = len(X[0])
    w = [0.0] * d
    if sample_w is None:
        sample_w = [1.0] * n
    for _ in range(epochs):
        for xi, yi, wi in zip(X, y, sample_w):
            z = sum(wj * xj for wj, xj in zip(w, xi))
            p = sigmoid(z)
            grad = [(p - yi) * xj * wi for xj in xi]
            for j in range(d):
                w[j] -= lr * grad[j]
    return w


def evaluate(X, y, w):
    if not X:
        return {"count": 0}
    tp = tn = fp = fn = 0
    for xi, yi in zip(X, y):
        z = sum(wj * xj for wj, xj in zip(w, xi))
        p = sigmoid(z)
        pred = 1 if p >= 0.5 else 0
        if pred == 1 and yi == 1:
            tp += 1
        elif pred == 0 and yi == 0:
            tn += 1
        elif pred == 1 and yi == 0:
            fp += 1
        else:
            fn += 1
    total = len(X)
    acc = (tp + tn) / total if total else 0
    return {"count": total, "acc": acc, "tp": tp, "tn": tn, "fp": fp, "fn": fn}


def train_val_split(X, y, val_ratio=0.2):
    n = len(X)
    if n < 5:
        return X, y, [], []
    split = int(n * (1 - val_ratio))
    return X[:split], y[:split], X[split:], y[split:]


def main():
    if not os.path.exists(LOG_FILE):
        print("No swing_hunter_log.csv found. Need closed trades to train.")
        return
    X_raw, y = load_dataset(LOG_FILE)
    if not X_raw:
        print("No closed trades with PL found; cannot train.")
        return
    vocab, inv = build_vocab(X_raw)
    X = featurize(X_raw, vocab)
    X_tr, y_tr, X_val, y_val = train_val_split(X, y, val_ratio=0.2)
    w = train_logreg(X_tr, y_tr)
    metrics_train = evaluate(X_tr, y_tr, w)
    metrics_val = evaluate(X_val, y_val, w) if X_val else {}
    model = {
        "vocab": vocab,
        "weights": w,
        "metrics_train": metrics_train,
        "metrics_val": metrics_val,
    }
    with open(MODEL_FILE, "w", encoding="utf-8") as f:
        json.dump(model, f, indent=2)
    print(f"Model saved to {MODEL_FILE}. Train: {metrics_train} | Val: {metrics_val}")


if __name__ == "__main__":
    main()
