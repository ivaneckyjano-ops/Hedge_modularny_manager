#!/usr/bin/env python3
"""
Hedge Calculator - Nájde optimálny hedge pre short option stratégiu

Stratégia:
1. SHORT OPTION: Predaj put/call s premium >= target (napr. $0.70)
2. LONG OPTION: Kúp lacnú opciu ako hedge (min theta, min delta)

Rozšírené funkcie:
- Automatické porovnanie DTE offsetov (0, 7, 14, 21, 30 dní)
- Výpočet margin pre IBKR / Saxo
- Theta-adjusted ROI optimalizácia
- Export výsledkov

Použitie:
  python hedge_calculator.py --symbol SPY --min-premium 0.70 --port 7496
  python hedge_calculator.py --symbol SPY --min-premium 0.70 --option-type CALL --port 7496
  python hedge_calculator.py --symbol SPY --min-premium 0.70 --optimize --broker IBKR --max-margin 3000
"""
import argparse
import json
import sys
import random
from datetime import datetime, date, timedelta

# Import lokálnych modulov
try:
    from margin_calculator import MarginCalculator, ThetaAnalyzer
    MARGIN_CALC_AVAILABLE = True
except ImportError:
    try:
        from scripts.margin_calculator import MarginCalculator, ThetaAnalyzer
        MARGIN_CALC_AVAILABLE = True
    except ImportError:
        MARGIN_CALC_AVAILABLE = False

try:
    from scenario_simulator import ScenarioSimulator
    SCENARIO_SIM_AVAILABLE = True
except ImportError:
    try:
        from scripts.scenario_simulator import ScenarioSimulator
        SCENARIO_SIM_AVAILABLE = True
    except ImportError:
        SCENARIO_SIM_AVAILABLE = False

try:
    from export_utils import export_strategy
    EXPORT_AVAILABLE = True
except ImportError:
    try:
        from scripts.export_utils import export_strategy
        EXPORT_AVAILABLE = True
    except ImportError:
        EXPORT_AVAILABLE = False

def parse_args():
    p = argparse.ArgumentParser(description='Hedge Calculator pre short option stratégiu')
    p.add_argument('--symbol', required=True, help='Symbol (SPY, QQQ...)')
    p.add_argument('--min-premium', type=float, default=0.70, help='Minimálne premium pre short (default $0.70)')
    p.add_argument('--option-type', default='PUT', choices=['PUT', 'CALL'], help='Typ opcie (PUT alebo CALL)')
    p.add_argument('--short-expiry', help='Short expirácia (YYYYMMDD), default: najbližší piatok')
    p.add_argument('--long-expiry', help='Long expirácia (YYYYMMDD), default: +4 týždne')
    p.add_argument('--port', type=int, default=7496, help='TWS port (7496=Live, 7497=Paper)')
    p.add_argument('--out', default='/tmp/hedge_calc_result.json', help='Output JSON')
    
    # Nové argumenty pre margin optimalizáciu
    p.add_argument('--optimize', action='store_true', help='Optimalizovať podľa margin/ROI')
    p.add_argument('--broker', default='IBKR', choices=['IBKR', 'SAXO'], help='Broker pre margin výpočet')
    p.add_argument('--max-margin', type=float, default=0, help='Max margin per contract (0=bez limitu)')
    p.add_argument('--min-roi', type=float, default=0, help='Min weekly ROI %% (0=bez limitu)')
    p.add_argument('--dte-offsets', default='0,7,14,21,30', help='DTE offsety na testovanie (čiarkou oddelené)')
    p.add_argument('--export', action='store_true', help='Exportovať výsledky do CSV/Excel')
    p.add_argument('--export-dir', default='/tmp', help='Adresár pre export')
    
    return p.parse_args()


def get_option_data(ib, symbol, expiry, strike, right, timeout=8):
    """Získaj greeks a ceny pre opciu - čaká na modelGreeks"""
    from ib_insync import Option
    
    try:
        contract = Option(symbol, expiry, strike, right, 'SMART')
        ib.qualifyContracts(contract)
        ticker = ib.reqMktData(contract, '106', snapshot=False)
        
        # Čakaj na greeks (modelGreeks fungujú aj bez plného market data)
        for _ in range(int(timeout / 0.25)):
            ib.sleep(0.25)
            mg = ticker.modelGreeks
            if mg and mg.delta is not None and mg.optPrice is not None:
                # modelGreeks obsahuje theoretical price
                bid = ticker.bid if ticker.bid and ticker.bid == ticker.bid else None
                ask = ticker.ask if ticker.ask and ticker.ask == ticker.ask else None
                # Použi teoretickú cenu ak nie sú bid/ask
                mid = (bid + ask) / 2 if bid and ask else mg.optPrice
                ib.cancelMktData(contract)
                return {
                    'strike': strike,
                    'expiry': expiry,
                    'delta': round(mg.delta, 4),
                    'theta': round(mg.theta, 4) if mg.theta else None,
                    'gamma': round(mg.gamma, 6) if mg.gamma else None,
                    'iv': round(mg.impliedVol, 4) if mg.impliedVol else None,
                    'bid': round(bid, 2) if bid else None,
                    'ask': round(ask, 2) if ask else None,
                    'mid': round(mid, 2) if mid else None,
                    'theorPrice': round(mg.optPrice, 2)
                }
        ib.cancelMktData(contract)
        return None
    except Exception as e:
        print(f"  Error at strike {strike}: {e}", file=sys.stderr)
        return None
        return None


def find_short_put(ib, symbol, expiry, current_price, min_premium):
    """Nájdi short put s premium >= min_premium"""
    return find_short_option(ib, symbol, expiry, current_price, min_premium, 'P')


def find_short_call(ib, symbol, expiry, current_price, min_premium):
    """Nájdi short call s premium >= min_premium"""
    return find_short_option(ib, symbol, expiry, current_price, min_premium, 'C')


def find_short_option(ib, symbol, expiry, current_price, min_premium, right):
    """Nájdi short option (PUT alebo CALL) s premium >= min_premium"""
    from ib_insync import Option
    
    opt_type = 'PUT' if right == 'P' else 'CALL'
    print(f"Hľadám SHORT {opt_type} s premium >= ${min_premium}...", file=sys.stderr)
    print(f"  Aktuálna cena: ${current_price:.2f}, Expiry: {expiry}", file=sys.stderr)
    sys.stderr.flush()
    
    # Získaj strikes
    opt = Option(symbol, expiry, 0, right, 'SMART')
    details = ib.reqContractDetails(opt)
    strikes = sorted([d.contract.strike for d in details])
    
    print(f"  Dostupných strikes: {len(strikes)}", file=sys.stderr)
    
    if right == 'P':
        # PUT: Filtruj OTM puts (pod aktuálnou cenou)
        otm_strikes = [s for s in strikes if s < current_price * 0.98]
        # Zoraď od najbližšieho k najvzdialenejšiemu
        otm_strikes = sorted(otm_strikes, reverse=True)[:30]
    else:
        # CALL: Filtruj OTM calls (nad aktuálnou cenou)
        # Povoľ aj ATM calls (0.5% nad cenou) pre väčšiu flexibilitu
        otm_strikes = [s for s in strikes if s > current_price * 1.005]
        # Zoraď od najbližšieho k najvzdialenejšiemu
        otm_strikes = sorted(otm_strikes)[:30]
    
    print(f"  OTM strikes na analýzu: {len(otm_strikes)}", file=sys.stderr)
    if otm_strikes:
        print(f"  Rozsah: {otm_strikes[0]} - {otm_strikes[-1] if len(otm_strikes) > 1 else otm_strikes[0]}", file=sys.stderr)
    sys.stderr.flush()
    
    candidates = []
    for strike in otm_strikes:
        data = get_option_data(ib, symbol, expiry, strike, right)
        if data:
            price = data['mid'] or data.get('theorPrice', 0)
            if price and price >= min_premium:
                candidates.append(data)
                print(f"  ✓ Strike {strike}: ${price:.2f} (delta={data['delta']:.3f})", file=sys.stderr)
                if len(candidates) >= 5:  # Nájdi max 5 kandidátov
                    break
            elif price:
                print(f"  ✗ Strike {strike}: ${price:.2f} < ${min_premium}", file=sys.stderr)
                # Ak sme pod min_premium, dalšie budú ešte lacnejšie
                if price < min_premium * 0.5:
                    break  # Netreba pokračovať
        else:
            print(f"  ? Strike {strike}: No data", file=sys.stderr)
    sys.stderr.flush()
    
    if not candidates:
        print(f"  ❌ Žiadny {opt_type} nenájdený s premium >= ${min_premium}", file=sys.stderr)
        sys.stderr.flush()
        return None
    
    # Vyber s najlepšou theta (najvyššia absolútna hodnota = najrýchlejší decay)
    best = max(candidates, key=lambda x: abs(x['theta'] or 0))
    print(f"  ✓ Vybraný: Strike {best['strike']} @ ${best['mid']:.2f}", file=sys.stderr)
    sys.stderr.flush()
    return best


def find_long_put_hedge(ib, symbol, expiry, current_price, short_strike):
    """Nájdi lacný long put ako hedge (min theta, min delta)"""
    return find_long_option_hedge(ib, symbol, expiry, current_price, short_strike, 'P')


def find_long_call_hedge(ib, symbol, expiry, current_price, short_strike):
    """Nájdi lacný long call ako hedge (min theta, min delta)"""
    return find_long_option_hedge(ib, symbol, expiry, current_price, short_strike, 'C')


def find_long_option_hedge(ib, symbol, expiry, current_price, short_strike, right):
    """Nájdi lacný long option ako hedge (min theta, min delta)"""
    from ib_insync import Option
    
    opt_type = 'PUT' if right == 'P' else 'CALL'
    print(f"Hľadám LONG {opt_type} hedge (min theta, min delta)...", file=sys.stderr)
    
    # Získaj strikes
    opt = Option(symbol, expiry, 0, right, 'SMART')
    details = ib.reqContractDetails(opt)
    strikes = sorted([d.contract.strike for d in details])
    
    if right == 'P':
        # PUT hedge: ďalej OTM (nižší strike než short)
        target_range_min = min(short_strike - 80, current_price * 0.85)
        target_range_max = short_strike - 15  # Aspoň 15 bodov pod short
        hedge_strikes = [s for s in strikes if target_range_min <= s <= target_range_max]
    else:
        # CALL hedge: ďalej OTM (vyšší strike než short)
        target_range_min = short_strike + 15  # Aspoň 15 bodov nad short
        target_range_max = max(short_strike + 80, current_price * 1.15)
        hedge_strikes = [s for s in strikes if target_range_min <= s <= target_range_max]
    
    # Vyber len niekoľko - každý 5. strike
    hedge_strikes = sorted(hedge_strikes)[::5][:8]  # Každý 5., max 8
    
    print(f"  Testujem strikes: {hedge_strikes}...", file=sys.stderr)
    
    candidates = []
    for strike in hedge_strikes:
        data = get_option_data(ib, symbol, expiry, strike, right)
        if data and data['delta'] is not None:
            price = data['mid'] or data.get('theorPrice', 0)
            candidates.append(data)
            print(f"  Strike {strike}: delta={data['delta']:.4f}, theta={data['theta']}, price=${price:.2f}", file=sys.stderr)
    
    if not candidates:
        return None
    
    # Vyber s najmenšou theta a deltou
    best = min(candidates, key=lambda x: abs(x['theta'] or 0) + abs(x['delta'] or 0))
    return best


def calculate_strategy(short_leg, long_leg, current_price, option_type='PUT'):
    """Vypočítaj parametre stratégie"""
    
    # Net credit (koľko dostaneš)
    short_premium = short_leg['mid'] or 0
    long_cost = long_leg['mid'] or 0
    net_credit = short_premium - long_cost
    
    # Max profit = net credit (ak obe expirujú bezcenné)
    max_profit = net_credit * 100  # Per contract
    
    # Max loss = rozdiel strikes - net credit
    spread_width = abs(short_leg['strike'] - long_leg['strike'])
    max_loss = (spread_width - net_credit) * 100
    
    if option_type == 'PUT':
        # PUT spread: breakeven = short strike - net credit
        breakeven = short_leg['strike'] - net_credit
        # Roll trigger - keď delta dosiahne -0.30 (pre PUT)
        roll_delta_trigger = -0.30
    else:
        # CALL spread: breakeven = short strike + net credit
        breakeven = short_leg['strike'] + net_credit
        # Roll trigger - keď delta dosiahne +0.30 (pre CALL)
        roll_delta_trigger = 0.30
    
    # Net greeks
    net_delta = (short_leg['delta'] or 0) + (long_leg['delta'] or 0)
    net_theta = (short_leg['theta'] or 0) + (long_leg['theta'] or 0)
    
    # === EXIT TARGETS ===
    if option_type == 'PUT':
        # PUT: profit keď cena rastie (nad breakeven)
        profit_50_underlying = short_leg['strike'] - (net_credit * 0.5)
        profit_25_underlying = short_leg['strike'] - (net_credit * 0.75)
    else:
        # CALL: profit keď cena klesá (pod breakeven)
        profit_50_underlying = short_leg['strike'] + (net_credit * 0.5)
        profit_25_underlying = short_leg['strike'] + (net_credit * 0.75)
    
    profit_50_option = net_credit * 0.5  # Kúpiš späť za polovicu
    profit_25_option = net_credit * 0.75
    
    return {
        'netCredit': round(net_credit, 2),
        'maxProfit': round(max_profit, 2),
        'maxLoss': round(max_loss, 2),
        'breakeven': round(breakeven, 2),
        'netDelta': round(net_delta, 4),
        'netTheta': round(net_theta, 4),
        'spreadWidth': spread_width,
        'currentPrice': current_price,
        'marginRequired': round(spread_width * 100, 2),
        'optionType': option_type,
        # Exit targets - underlying prices
        'exit': {
            'profit50': {
                'underlyingAbove' if option_type == 'PUT' else 'underlyingBelow': round(profit_50_underlying, 2),
                'buyBackSpreadAt': round(profit_50_option, 2),
                'profitUSD': round(max_profit * 0.5, 2)
            },
            'profit25': {
                'underlyingAbove' if option_type == 'PUT' else 'underlyingBelow': round(profit_25_underlying, 2),
                'buyBackSpreadAt': round(profit_25_option, 2),
                'profitUSD': round(max_profit * 0.25, 2)
            },
            'breakeven': {
                'underlying': round(breakeven, 2),
                'spreadValue': round(net_credit, 2)
            },
            'maxLoss': {
                'underlyingBelow' if option_type == 'PUT' else 'underlyingAbove': long_leg['strike'],
                'lossUSD': round(max_loss, 2)
            },
            'rollTrigger': {
                'whenDeltaReaches': roll_delta_trigger,
                'currentDelta': round(short_leg['delta'] or 0, 4)
            }
        }
    }


def days_to_expiry(expiry: str) -> int:
    """Vypočíta DTE z dátumu expirácie (YYYYMMDD)"""
    try:
        exp_date = datetime.strptime(expiry, '%Y%m%d').date()
        today = date.today()
        return max(0, (exp_date - today).days)
    except:
        return 7


def find_expiry_by_offset(expiries: list, base_expiry: str, offset_days: int) -> str:
    """
    Nájde expiráciu najbližšiu k base_expiry + offset_days
    
    Args:
        expiries: List dostupných expirácií (YYYYMMDD)
        base_expiry: Základná expirácia (YYYYMMDD)
        offset_days: Počet dní offsetu
        
    Returns:
        Najbližšia expirácia k cieľovému dátumu
    """
    try:
        base_date = datetime.strptime(base_expiry, '%Y%m%d').date()
        target_date = base_date + timedelta(days=offset_days)
        
        # Nájdi najbližšiu expiráciu
        best_expiry = base_expiry
        best_diff = float('inf')
        
        for exp in expiries:
            try:
                exp_date = datetime.strptime(exp, '%Y%m%d').date()
                diff = abs((exp_date - target_date).days)
                if diff < best_diff and exp_date >= base_date:
                    best_diff = diff
                    best_expiry = exp
            except:
                continue
        
        return best_expiry
    except:
        return base_expiry


def find_optimal_strategies(ib, symbol, short_expiry, current_price, short_leg, 
                            expiries, right, broker='IBKR', max_margin=0, 
                            min_roi=0, dte_offsets=None):
    """
    Nájde optimálne stratégie pre rôzne DTE offsety
    
    Args:
        ib: IB connection
        symbol: Symbol
        short_expiry: Short leg expirácia
        current_price: Aktuálna cena podkladu
        short_leg: Dict s short leg údajmi
        expiries: List dostupných expirácií
        right: 'P' alebo 'C'
        broker: 'IBKR' alebo 'SAXO'
        max_margin: Max margin filter (0 = bez limitu)
        min_roi: Min weekly ROI filter (0 = bez limitu)
        dte_offsets: List DTE offsetov na testovanie
        
    Returns:
        List alternatív zoradených podľa theta-adjusted ROI
    """
    if dte_offsets is None:
        dte_offsets = [0, 7, 14, 21, 30]
    
    option_type = 'PUT' if right == 'P' else 'CALL'
    alternatives = []
    
    # Margin calculator
    if MARGIN_CALC_AVAILABLE:
        margin_calc = MarginCalculator(broker)
    else:
        margin_calc = None
    
    short_dte = days_to_expiry(short_expiry)
    
    print(f"[OPT] Hľadám optimálne stratégie pre DTE offsety: {dte_offsets}...", file=sys.stderr)
    print(f"[OPT] Short Strike: {short_leg['strike']}, Short Expiry: {short_expiry}, Short DTE: {short_dte}", file=sys.stderr)
    sys.stderr.flush()
    
    for offset in dte_offsets:
        print(f"[OPT] === Analyzujem DTE offset +{offset} ===", file=sys.stderr)
        sys.stderr.flush()
        
        # Nájdi expiráciu pre tento offset
        if offset == 0:
            long_expiry = short_expiry
        else:
            long_expiry = find_expiry_by_offset(expiries, short_expiry, offset)
        
        print(f"[OPT] DTE +{offset}: Long expiry = {long_expiry}", file=sys.stderr)
        sys.stderr.flush()
        
        # Nájdi long leg pre túto expiráciu
        print(f"[OPT] DTE +{offset}: Hľadám long leg...", file=sys.stderr)
        sys.stderr.flush()
        long_leg = find_long_option_hedge(ib, symbol, long_expiry, current_price, short_leg['strike'], right)
        
        if not long_leg:
            print(f"[OPT] DTE +{offset}: Nenašiel som long leg - SKIP", file=sys.stderr)
            sys.stderr.flush()
            continue
        
        print(f"[OPT] DTE +{offset}: Nájdený long leg strike={long_leg['strike']}, premium=${long_leg['mid']:.2f}", file=sys.stderr)
        sys.stderr.flush()
        
        # Vypočítaj stratégiu
        strategy = calculate_strategy(short_leg, long_leg, current_price, option_type)
        
        # Margin výpočet
        if margin_calc:
            short_leg_dict = {
                'strike': short_leg['strike'],
                'expiry': short_expiry,
                'premium': short_leg['mid'],
            }
            long_leg_dict = {
                'strike': long_leg['strike'],
                'expiry': long_expiry,
                'premium': long_leg['mid'],
            }
            
            margin_info = margin_calc.calculate_margin(
                short_leg_dict, long_leg_dict, current_price, option_type
            )
            margin = margin_info['margin']
            spread_type = margin_info['spreadType']
        else:
            # Fallback - jednoduchý výpočet
            margin = strategy['spreadWidth'] * 100
            spread_type = 'vertical' if offset == 0 else 'diagonal'
        
        # Theta analysis
        long_dte = days_to_expiry(long_expiry)
        
        if MARGIN_CALC_AVAILABLE:
            theta_diff = ThetaAnalyzer.calculate_theta_differential(
                short_leg.get('theta', 0), long_leg.get('theta', 0),
                short_dte, long_dte
            )
            
            roi_info = ThetaAnalyzer.calculate_theta_adjusted_roi(
                strategy['netCredit'], margin, short_dte, theta_diff
            )
            
            weekly_roi = roi_info['weeklyROI']
            theta_adj_roi = roi_info['thetaAdjustedWeeklyROI']
        else:
            weekly_roi = (strategy['netCredit'] * 100 / margin * 100 / short_dte * 7) if margin > 0 and short_dte > 0 else 0
            theta_adj_roi = weekly_roi
            theta_diff = {'netTheta': 0, 'weeklyThetaGainUSD': 0}
        
        # Filter podľa kritérií
        if max_margin > 0 and margin > max_margin:
            print(f"[OPT] DTE +{offset}: Margin ${margin:.0f} > max ${max_margin:.0f} - SKIP", file=sys.stderr)
            sys.stderr.flush()
            continue
        
        if min_roi > 0 and weekly_roi < min_roi:
            print(f"[OPT] DTE +{offset}: ROI {weekly_roi:.2f}% < min {min_roi:.2f}% - SKIP", file=sys.stderr)
            sys.stderr.flush()
            continue
        
        alternative = {
            'dteOffset': offset,
            'longExpiry': long_expiry,
            'longStrike': long_leg['strike'],
            'longPremium': long_leg['mid'],
            'longDelta': long_leg.get('delta'),
            'longTheta': long_leg.get('theta'),
            'shortDTE': short_dte,
            'longDTE': long_dte,
            'spreadType': spread_type,
            'margin': round(margin, 2),
            'netCredit': strategy['netCredit'],
            'maxProfit': strategy['maxProfit'],
            'maxLoss': strategy['maxLoss'],
            'weeklyROI': round(weekly_roi, 2),
            'thetaAdjustedWeeklyROI': round(theta_adj_roi, 2),
            'thetaDifferential': round(theta_diff.get('netTheta', 0), 4),
            'weeklyThetaGainUSD': round(theta_diff.get('weeklyThetaGainUSD', 0), 2),
            'strategy': strategy,
            'longLeg': long_leg,
        }
        
        alternatives.append(alternative)
        print(f"[OPT] DTE +{offset}: ✓ Long {long_leg['strike']} @ ${long_leg['mid']:.2f}, "
              f"Margin ${margin:.0f}, Weekly ROI {weekly_roi:.2f}%", file=sys.stderr)
        sys.stderr.flush()
    
    # Zoraď podľa theta-adjusted ROI (zostupne)
    alternatives.sort(key=lambda x: x['thetaAdjustedWeeklyROI'], reverse=True)
    
    if alternatives:
        print(f"[OPT] === Nájdených {len(alternatives)} alternatív ===", file=sys.stderr)
    else:
        print(f"[OPT] === Žiadne alternatívy nenájdené pre dané kritériá ===", file=sys.stderr)
    sys.stderr.flush()
    
    return alternatives


def main():
    args = parse_args()
    
    try:
        from ib_insync import IB, Stock
    except ImportError:
        print(json.dumps({'success': False, 'error': 'ib_insync not installed'}))
        sys.exit(1)
    
    ib = IB()
    client_id = random.randint(1000, 9999)
    
    try:
        ib.connect('127.0.0.1', args.port, clientId=client_id, readonly=True)
        print(f"Pripojené k TWS (port {args.port})", file=sys.stderr)
    except Exception as e:
        print(json.dumps({'success': False, 'error': f'Cannot connect: {e}'}))
        sys.exit(1)
    
    ib.reqMarketDataType(4)  # Delayed frozen
    
    # Typ opcie
    option_type = args.option_type.upper()
    right = 'P' if option_type == 'PUT' else 'C'
    
    # Získaj aktuálnu cenu
    stock = Stock(args.symbol, 'SMART', 'USD')
    ib.qualifyContracts(stock)
    ticker = ib.reqMktData(stock, '', False, False)
    ib.sleep(2)
    current_price = ticker.last if ticker.last and ticker.last == ticker.last else ticker.close
    ib.cancelMktData(stock)
    print(f"Aktuálna cena {args.symbol}: ${current_price:.2f}", file=sys.stderr)
    
    # Získaj expirácie
    from ib_insync import Option
    opt = Option(args.symbol, '', 0, right, 'SMART')
    details = ib.reqContractDetails(opt)
    expiries = sorted(set(d.contract.lastTradeDateOrContractMonth for d in details))
    
    # Určí expirácie ak nie sú zadané
    if not args.short_expiry:
        # Najbližšia expirácia (tento alebo budúci týždeň)
        args.short_expiry = expiries[1] if len(expiries) > 1 else expiries[0]
    if not args.long_expiry:
        # +4 týždne pre hedge
        args.long_expiry = expiries[4] if len(expiries) > 4 else expiries[-1]
    
    print(f"Option type: {option_type}", file=sys.stderr)
    print(f"Short expiry: {args.short_expiry}", file=sys.stderr)
    print(f"Long expiry: {args.long_expiry}", file=sys.stderr)
    
    # Nájdi short option
    short_leg = find_short_option(ib, args.symbol, args.short_expiry, current_price, args.min_premium, right)
    if not short_leg:
        ib.disconnect()
        result = {'success': False, 'error': f'Nenašiel som short {option_type} s premium >= ${args.min_premium}'}
        with open(args.out, 'w') as f:
            json.dump(result, f, indent=2)
        print(json.dumps(result))
        sys.exit(1)
    
    print(f"SHORT: Strike {short_leg['strike']}, Premium ${short_leg['mid']}", file=sys.stderr)
    
    # === OPTIMALIZÁCIA MODE ===
    if args.optimize and MARGIN_CALC_AVAILABLE:
        # Parse DTE offsets
        dte_offsets = [int(x.strip()) for x in args.dte_offsets.split(',')]
        
        # Nájdi všetky alternatívy
        alternatives = find_optimal_strategies(
            ib, args.symbol, args.short_expiry, current_price, short_leg,
            expiries, right, args.broker, args.max_margin, args.min_roi, dte_offsets
        )
        
        if not alternatives:
            ib.disconnect()
            result = {'success': False, 'error': 'Nenašiel som žiadnu vhodnú stratégiu podľa zadaných kritérií'}
            with open(args.out, 'w') as f:
                json.dump(result, f, indent=2)
            print(json.dumps(result))
            sys.exit(1)
        
        # Najlepšia alternatíva
        best = alternatives[0]
        long_leg = best['longLeg']
        args.long_expiry = best['longExpiry']
        
        # Margin info
        margin_calc = MarginCalculator(args.broker)
        margin_info = margin_calc.calculate_margin(
            {'strike': short_leg['strike'], 'expiry': args.short_expiry, 'premium': short_leg['mid']},
            {'strike': long_leg['strike'], 'expiry': args.long_expiry, 'premium': long_leg['mid']},
            current_price, option_type
        )
        
        # Theta analysis
        short_dte = days_to_expiry(args.short_expiry)
        long_dte = days_to_expiry(args.long_expiry)
        theta_diff = ThetaAnalyzer.calculate_theta_differential(
            short_leg.get('theta', 0), long_leg.get('theta', 0),
            short_dte, long_dte
        )
        roi_info = ThetaAnalyzer.calculate_theta_adjusted_roi(
            best['netCredit'], margin_info['margin'], short_dte, theta_diff
        )
        
        print(f"\n{'='*60}", file=sys.stderr)
        print(f"OPTIMALIZÁCIA DOKONČENÁ - Broker: {args.broker}", file=sys.stderr)
        print(f"{'='*60}", file=sys.stderr)
        print(f"Najlepšia stratégia: DTE offset +{best['dteOffset']}", file=sys.stderr)
        print(f"  Long Strike: {long_leg['strike']}", file=sys.stderr)
        print(f"  Long Expiry: {args.long_expiry}", file=sys.stderr)
        print(f"  Margin: ${margin_info['margin']:.2f}", file=sys.stderr)
        print(f"  Weekly ROI: {roi_info['weeklyROI']:.2f}%", file=sys.stderr)
        print(f"  Theta-Adjusted ROI: {roi_info['thetaAdjustedWeeklyROI']:.2f}%", file=sys.stderr)
        print(f"{'='*60}\n", file=sys.stderr)
        
    else:
        # Štandardný mode - nájdi long option hedge
        long_leg = find_long_option_hedge(ib, args.symbol, args.long_expiry, current_price, short_leg['strike'], right)
        if not long_leg:
            ib.disconnect()
            result = {'success': False, 'error': f'Nenašiel som vhodný long {option_type} hedge'}
            with open(args.out, 'w') as f:
                json.dump(result, f, indent=2)
            print(json.dumps(result))
            sys.exit(1)
        
        alternatives = None
        margin_info = None
        roi_info = None
        theta_diff = None
    
    print(f"LONG: Strike {long_leg['strike']}, Premium ${long_leg['mid']}", file=sys.stderr)
    
    # Vypočítaj stratégiu
    strategy = calculate_strategy(short_leg, long_leg, current_price, option_type)
    
    ib.disconnect()
    
    result = {
        'success': True,
        'symbol': args.symbol,
        'currentPrice': current_price,
        'optionType': option_type,
        'shortLeg': {
            'action': 'SELL',
            'strike': short_leg['strike'],
            'expiry': args.short_expiry,
            'type': option_type,
            'premium': short_leg['mid'],
            'delta': short_leg['delta'],
            'theta': short_leg['theta'],
            'iv': short_leg['iv']
        },
        'longLeg': {
            'action': 'BUY',
            'strike': long_leg['strike'],
            'expiry': args.long_expiry,
            'type': option_type,
            'premium': long_leg['mid'],
            'delta': long_leg['delta'],
            'theta': long_leg['theta'],
            'iv': long_leg['iv']
        },
        'strategy': strategy,
        'exitPlan': {
            'profit50': {
                'description': '50% profit - CLOSE pozíciu',
                'whenUnderlyingAbove' if option_type == 'PUT' else 'whenUnderlyingBelow': strategy['exit']['profit50'].get('underlyingAbove') or strategy['exit']['profit50'].get('underlyingBelow'),
                'buyBackSpreadAt': strategy['exit']['profit50']['buyBackSpreadAt'],
                'profitUSD': strategy['exit']['profit50']['profitUSD']
            },
            'profit25': {
                'description': '25% profit - možnosť CLOSE',
                'whenUnderlyingAbove' if option_type == 'PUT' else 'whenUnderlyingBelow': strategy['exit']['profit25'].get('underlyingAbove') or strategy['exit']['profit25'].get('underlyingBelow'),
                'buyBackSpreadAt': strategy['exit']['profit25']['buyBackSpreadAt'],
                'profitUSD': strategy['exit']['profit25']['profitUSD']
            },
            'breakeven': {
                'underlying': strategy['exit']['breakeven']['underlying'],
                'spreadValue': strategy['exit']['breakeven']['spreadValue']
            },
            'roll': {
                'description': 'ROLL keď delta dosiahne',
                'triggerDelta': strategy['exit']['rollTrigger']['whenDeltaReaches'],
                'currentDelta': strategy['exit']['rollTrigger']['currentDelta']
            },
            'maxLoss': {
                'whenUnderlyingBelow' if option_type == 'PUT' else 'whenUnderlyingAbove': strategy['exit']['maxLoss'].get('underlyingBelow') or strategy['exit']['maxLoss'].get('underlyingAbove'),
                'lossUSD': strategy['exit']['maxLoss']['lossUSD']
            }
        }
    }
    
    # Pridaj margin info ak je dostupné
    if margin_info:
        result['marginInfo'] = {
            'broker': args.broker,
            'brokerName': margin_info.get('brokerName', args.broker),
            'spreadType': margin_info.get('spreadType', 'unknown'),
            'margin': margin_info.get('margin', 0),
            'roiOnMargin': margin_info.get('roiOnMargin', 0),
        }
        if roi_info:
            result['marginInfo']['weeklyROI'] = roi_info.get('weeklyROI', 0)
            result['marginInfo']['thetaAdjustedWeeklyROI'] = roi_info.get('thetaAdjustedWeeklyROI', 0)
            result['marginInfo']['annualizedROI'] = roi_info.get('annualizedROI', 0)
        if theta_diff:
            result['marginInfo']['thetaDifferential'] = theta_diff.get('netTheta', 0)
            result['marginInfo']['weeklyThetaGainUSD'] = theta_diff.get('weeklyThetaGainUSD', 0)
    
    # Pridaj alternatívy ak sú dostupné
    if alternatives:
        # Vyčisti alternatívy (odstráň vnorené objekty pre JSON)
        clean_alternatives = []
        for alt in alternatives:
            clean_alt = {k: v for k, v in alt.items() if k not in ['strategy', 'longLeg']}
            clean_alternatives.append(clean_alt)
        result['alternatives'] = clean_alternatives
    
    # Prehľadný výpis
    print(f"\n{'='*50}", file=sys.stderr)
    print(f"EXIT PLAN pre {args.symbol} {option_type}:", file=sys.stderr)
    print(f"{'='*50}", file=sys.stderr)
    
    # Exit podmienky sa líšia pre PUT vs CALL
    profit_50_price = strategy['exit']['profit50'].get('underlyingAbove') or strategy['exit']['profit50'].get('underlyingBelow')
    profit_25_price = strategy['exit']['profit25'].get('underlyingAbove') or strategy['exit']['profit25'].get('underlyingBelow')
    max_loss_price = strategy['exit']['maxLoss'].get('underlyingBelow') or strategy['exit']['maxLoss'].get('underlyingAbove')
    
    direction = ">" if option_type == 'PUT' else "<"
    loss_direction = "<" if option_type == 'PUT' else ">"
    
    print(f"📈 50% PROFIT: Close keď {args.symbol} {direction} ${profit_50_price:.2f}", file=sys.stderr)
    print(f"   → Kúp späť spread za ${strategy['exit']['profit50']['buyBackSpreadAt']:.2f} (profit ${strategy['exit']['profit50']['profitUSD']:.0f})", file=sys.stderr)
    print(f"📊 25% PROFIT: Close keď {args.symbol} {direction} ${profit_25_price:.2f}", file=sys.stderr)
    print(f"   → Kúp späť spread za ${strategy['exit']['profit25']['buyBackSpreadAt']:.2f} (profit ${strategy['exit']['profit25']['profitUSD']:.0f})", file=sys.stderr)
    print(f"⚖️  BREAKEVEN: {args.symbol} = ${strategy['exit']['breakeven']['underlying']:.2f}", file=sys.stderr)
    print(f"🔄 ROLL: Keď delta short dosiahne {strategy['exit']['rollTrigger']['whenDeltaReaches']} (teraz: {strategy['exit']['rollTrigger']['currentDelta']:.3f})", file=sys.stderr)
    print(f"🛑 MAX LOSS: ${strategy['exit']['maxLoss']['lossUSD']:.0f} ak {args.symbol} {loss_direction} ${max_loss_price}", file=sys.stderr)
    print(f"{'='*50}\n", file=sys.stderr)
    
    # Export ak je požadovaný
    if args.export and EXPORT_AVAILABLE:
        try:
            # Priprav scenáre pre export
            scenarios = None
            if SCENARIO_SIM_AVAILABLE:
                simulator = ScenarioSimulator()
                price_scenarios = simulator.simulate_price_move(result)
                time_scenarios = simulator.simulate_time_decay(result)
                combined = simulator.simulate_combined(result)
                scenarios = {
                    'priceScenarios': price_scenarios.get('scenarios', []),
                    'timeScenarios': time_scenarios.get('scenarios', []),
                    'combinedMatrix': combined,
                }
            
            # Export
            export_result = export_strategy(
                strategy=result,
                scenarios=scenarios,
                alternatives=result.get('alternatives'),
                margin_info=result.get('marginInfo'),
                output_dir=args.export_dir,
                format='both'
            )
            
            if export_result['success']:
                result['export'] = {
                    'success': True,
                    'files': export_result['files'],
                }
                print(f"📁 Exportované do: {', '.join(export_result['files'])}", file=sys.stderr)
            else:
                result['export'] = {
                    'success': False,
                    'error': export_result.get('error', 'Unknown error'),
                }
        except Exception as e:
            result['export'] = {
                'success': False,
                'error': str(e),
            }
            print(f"❌ Chyba exportu: {e}", file=sys.stderr)
    
    with open(args.out, 'w') as f:
        json.dump(result, f, indent=2)
    
    print(json.dumps(result, indent=2))
    sys.exit(0)


if __name__ == '__main__':
    main()
