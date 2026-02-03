import json
import os
import math


def load_model(model_path):
    if not os.path.exists(model_path):
        return None
    try:
        with open(model_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return None


def predict_prob(summary, model):
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
    zone = (summary.get('zone') or '').lower()
    trend = (summary.get('trend_label') or '').lower()
    score = summary.get('score_pct')
    feat_score = None
    if score is not None:
        try:
            sval = float(score)
            if sval < 40:
                feat_score = "score:<40"
            elif sval < 60:
                feat_score = "score:40-60"
            else:
                feat_score = "score:>=60"
        except Exception:
            pass
    macd_cross = summary.get('macd_cross')
    rvi_gt = summary.get('rvi_gt_sig')
    pdist = summary.get('pivot_dist')
    feat_pdist = None
    if pdist is not None:
        try:
            pval = float(pdist)
            if abs(pval) < 1:
                feat_pdist = "pdist:<1"
            elif abs(pval) < 3:
                feat_pdist = "pdist:1-3"
            else:
                feat_pdist = "pdist:>3"
        except Exception:
            pass

    feats = [pctb_b, rsi_b, sig_b, tf_b]
    if zone:
        feats.append(f"zone:{zone}")
    if trend:
        feats.append(f"trend:{trend}")
    if feat_score:
        feats.append(feat_score)
    if macd_cross:
        feats.append("macd:cross")
    if rvi_gt:
        feats.append("rvi:gt_sig")
    if feat_pdist:
        feats.append(feat_pdist)

    vec = 0.0
    for f in feats:
        idx = vocab.get(f)
        if idx is not None and idx < len(weights):
            vec += weights[idx] * 1.0

    try:
        return 1 / (1 + math.exp(-vec))
    except Exception:
        return None
