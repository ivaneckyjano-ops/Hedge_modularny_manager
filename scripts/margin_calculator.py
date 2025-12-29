#!/usr/bin/env python3
"""
Margin Calculator - Výpočet maržových požiadaviek pre opčné stratégie

Podporované brokeri:
- Interactive Brokers (IBKR) - Reg-T margin model
- Saxo Bank - Konzervativnejší margin model

Podporované stratégie:
- Vertikálny credit spread (rovnaká expirácia)
- Diagonálny spread (rôzne expirácie)
"""
import math
from datetime import datetime, date
from typing import Dict, Optional, Tuple, List

try:
    from scipy.stats import norm
    SCIPY_AVAILABLE = True
except ImportError:
    SCIPY_AVAILABLE = False


class MarginCalculator:
    """
    Kalkulátor maržových požiadaviek pre rôznych brokerov
    
    IBKR Reg-T model:
        Credit spread: max(spread_width, 10% × short_strike) × 100
        Diagonal spread: naked_margin - long_value
        
    Saxo model (konzervativnejší):
        Credit spread: max(spread_width, 15% × short_strike) × 100
        Diagonal spread: naked_margin - (long_value × 0.7)  # Menší kredit za long
    """
    
    BROKER_MODELS = {
        'IBKR': {
            'name': 'Interactive Brokers',
            'spread_pct': 0.10,      # 10% short strike pre credit spread
            'naked_pct': 0.20,       # 20% short strike pre naked option
            'long_credit': 1.0,      # 100% hodnoty longu ako kredit
            'min_naked': 2.50,       # Min $250 per contract
        },
        'SAXO': {
            'name': 'Saxo Bank',
            'spread_pct': 0.15,      # 15% short strike pre credit spread
            'naked_pct': 0.25,       # 25% short strike pre naked option
            'long_credit': 0.70,     # 70% hodnoty longu ako kredit
            'min_naked': 5.00,       # Min $500 per contract
        }
    }
    
    def __init__(self, broker: str = 'IBKR'):
        """
        Inicializácia margin kalkulátora
        
        Args:
            broker: 'IBKR' alebo 'SAXO'
        """
        self.broker = broker.upper()
        if self.broker not in self.BROKER_MODELS:
            raise ValueError(f"Nepodporovaný broker: {broker}. Použite 'IBKR' alebo 'SAXO'")
        
        self.model = self.BROKER_MODELS[self.broker]
    
    def credit_spread_margin(self, short_strike: float, long_strike: float, 
                              net_credit: float = 0) -> float:
        """
        Margin pre vertikálny credit spread (rovnaká expirácia)
        
        Args:
            short_strike: Strike predanej opcie
            long_strike: Strike kúpenej opcie (ochrana)
            net_credit: Prijatá prémia (zníži margin)
            
        Returns:
            Margin requirement v USD per contract
        """
        spread_width = abs(short_strike - long_strike)
        
        # IBKR/Saxo: max(spread_width, X% × short_strike)
        margin_base = max(spread_width, self.model['spread_pct'] * short_strike)
        
        # Konverzia na per-contract (× 100)
        margin = margin_base * 100
        
        # Net credit znižuje margin (buying power effect)
        margin_after_credit = margin - (net_credit * 100)
        
        return round(max(margin_after_credit, spread_width * 100), 2)
    
    def naked_option_margin(self, strike: float, underlying_price: float,
                            option_price: float = 0, option_type: str = 'PUT') -> float:
        """
        Margin pre naked (nekrytú) opciu
        
        IBKR formula (zjednodušená):
            PUT:  max(20% × underlying - OTM amount, 10% × strike) + premium
            CALL: max(20% × underlying - OTM amount, 10% × underlying) + premium
            
        Args:
            strike: Strike opcie
            underlying_price: Aktuálna cena podkladu
            option_price: Cena opcie (premium)
            option_type: 'PUT' alebo 'CALL'
            
        Returns:
            Margin requirement v USD per contract
        """
        if option_type.upper() == 'PUT':
            otm_amount = max(0, underlying_price - strike)
        else:
            otm_amount = max(0, strike - underlying_price)
        
        # Základný margin
        margin_pct = self.model['naked_pct'] * underlying_price - otm_amount
        margin_min = self.model['min_naked'] * strike
        
        margin_base = max(margin_pct, margin_min)
        
        # Pridaj premium (je to additional collateral)
        margin = (margin_base + option_price) * 100
        
        return round(margin, 2)
    
    def diagonal_spread_margin(self, short_strike: float, long_strike: float,
                                short_expiry: str, long_expiry: str,
                                underlying_price: float, short_premium: float = 0,
                                long_value: float = 0, option_type: str = 'PUT') -> float:
        """
        Margin pre diagonálny spread (rôzne expirácie)
        
        Pri rôznych expiráciách broker typicky počíta:
            margin = naked_short_margin - (long_value × credit_factor)
            
        Args:
            short_strike: Strike predanej opcie
            long_strike: Strike kúpenej opcie
            short_expiry: Expirácia short leg (YYYYMMDD)
            long_expiry: Expirácia long leg (YYYYMMDD)
            underlying_price: Aktuálna cena podkladu
            short_premium: Premium prijatá za short
            long_value: Aktuálna hodnota long opcie
            option_type: 'PUT' alebo 'CALL'
            
        Returns:
            Margin requirement v USD per contract
        """
        # Naked margin pre short leg
        naked_margin = self.naked_option_margin(
            short_strike, underlying_price, short_premium, option_type
        )
        
        # Kredit za long leg (IBKR dáva 100%, Saxo len 70%)
        long_credit = long_value * 100 * self.model['long_credit']
        
        # Diagonálny margin = naked - long_credit
        diagonal_margin = naked_margin - long_credit
        
        # Minimum je spread width (ak by boli rovnaké expirácie)
        spread_width = abs(short_strike - long_strike)
        min_margin = spread_width * 100
        
        return round(max(diagonal_margin, min_margin), 2)
    
    def calculate_margin(self, short_leg: Dict, long_leg: Dict, 
                         underlying_price: float, option_type: str = 'PUT') -> Dict:
        """
        Vypočíta margin podľa typu spreadu
        
        Args:
            short_leg: Dict s 'strike', 'expiry', 'premium'
            long_leg: Dict s 'strike', 'expiry', 'premium'
            underlying_price: Aktuálna cena podkladu
            option_type: 'PUT' alebo 'CALL'
            
        Returns:
            Dict s margin info
        """
        same_expiry = short_leg.get('expiry') == long_leg.get('expiry')
        
        short_premium = short_leg.get('premium', 0) or short_leg.get('mid', 0) or 0
        long_premium = long_leg.get('premium', 0) or long_leg.get('mid', 0) or 0
        net_credit = short_premium - long_premium
        
        spread_width = abs(short_leg['strike'] - long_leg['strike'])
        
        if same_expiry:
            # Vertikálny spread
            margin = self.credit_spread_margin(
                short_leg['strike'], long_leg['strike'], net_credit
            )
            spread_type = 'vertical'
        else:
            # Diagonálny spread
            margin = self.diagonal_spread_margin(
                short_leg['strike'], long_leg['strike'],
                short_leg.get('expiry', ''), long_leg.get('expiry', ''),
                underlying_price, short_premium, long_premium, option_type
            )
            spread_type = 'diagonal'
        
        # ROI výpočty
        max_profit = net_credit * 100
        roi_on_margin = (max_profit / margin * 100) if margin > 0 else 0
        
        return {
            'spreadType': spread_type,
            'broker': self.broker,
            'brokerName': self.model['name'],
            'margin': margin,
            'netCredit': round(net_credit, 2),
            'maxProfit': round(max_profit, 2),
            'spreadWidth': spread_width,
            'roiOnMargin': round(roi_on_margin, 2),  # %
        }


class ThetaAnalyzer:
    """
    Analyzátor theta decay pre optimalizáciu DTE offsetov
    """
    
    @staticmethod
    def days_to_expiry(expiry: str) -> int:
        """Vypočíta DTE z dátumu expirácie (YYYYMMDD)"""
        try:
            exp_date = datetime.strptime(expiry, '%Y%m%d').date()
            today = date.today()
            return (exp_date - today).days
        except:
            return 0
    
    @staticmethod
    def theta_decay_factor(dte: int) -> float:
        """
        Faktor theta decay - čím bližšie k expirácii, tým rýchlejší decay
        
        Theta decay je približne ~ 1/sqrt(DTE)
        Posledných 7 dní je najagresívnejších
        """
        if dte <= 0:
            return 0
        return 1.0 / math.sqrt(dte)
    
    @staticmethod
    def calculate_theta_differential(short_theta: float, long_theta: float,
                                     short_dte: int, long_dte: int) -> Dict:
        """
        Vypočíta theta differential medzi short a long leg
        
        Args:
            short_theta: Theta short leg (záporná hodnota)
            long_theta: Theta long leg (záporná hodnota)
            short_dte: Days to expiry short leg
            long_dte: Days to expiry long leg
            
        Returns:
            Dict s theta analýzou
        """
        # Absolútne hodnoty theta
        abs_short_theta = abs(short_theta or 0)
        abs_long_theta = abs(long_theta or 0)
        
        # Net theta advantage = koľko zarábame denne na rozdiele
        net_theta = abs_short_theta - abs_long_theta
        
        # Decay factors
        short_decay_factor = ThetaAnalyzer.theta_decay_factor(short_dte)
        long_decay_factor = ThetaAnalyzer.theta_decay_factor(long_dte)
        
        # Theta ratio - pomer decay rýchlosti
        theta_ratio = short_decay_factor / long_decay_factor if long_decay_factor > 0 else float('inf')
        
        # Decay efficiency - ako efektívne využívame theta rozdiel
        # Vyššia hodnota = short stráca hodnotu rýchlejšie než long
        decay_efficiency = (abs_short_theta * short_decay_factor) / (abs_long_theta * long_decay_factor) if abs_long_theta > 0 and long_decay_factor > 0 else float('inf')
        
        # Projected theta na týždeň
        weekly_theta_gain = net_theta * 7  # 7 dní
        
        return {
            'shortTheta': round(short_theta or 0, 4),
            'longTheta': round(long_theta or 0, 4),
            'netTheta': round(net_theta, 4),
            'shortDTE': short_dte,
            'longDTE': long_dte,
            'dteOffset': long_dte - short_dte,
            'thetaRatio': round(theta_ratio, 2) if theta_ratio != float('inf') else 999,
            'decayEfficiency': round(decay_efficiency, 2) if decay_efficiency != float('inf') else 999,
            'weeklyThetaGain': round(weekly_theta_gain, 4),
            'weeklyThetaGainUSD': round(weekly_theta_gain * 100, 2),  # Per contract
        }
    
    @staticmethod
    def calculate_theta_adjusted_roi(net_credit: float, margin: float,
                                     short_dte: int, theta_differential: Dict) -> Dict:
        """
        Vypočíta ROI s prihliadnutím na theta decay
        
        Args:
            net_credit: Prijatá prémia
            margin: Margin requirement
            short_dte: DTE short leg (obdobie držania)
            theta_differential: Výstup z calculate_theta_differential
            
        Returns:
            Dict s ROI metrikami
        """
        if margin <= 0 or short_dte <= 0:
            return {
                'rawROI': 0,
                'weeklyROI': 0,
                'annualizedROI': 0,
                'thetaAdjustedWeeklyROI': 0,
            }
        
        max_profit = net_credit * 100
        
        # Raw ROI na margin
        raw_roi = (max_profit / margin) * 100
        
        # Weekly ROI (normalizované na 7 dní)
        weekly_roi = (raw_roi / short_dte) * 7
        
        # Annualized ROI
        annualized_roi = weekly_roi * 52
        
        # Theta-adjusted weekly ROI
        # Zohľadňuje weekly theta gain ako bonus
        weekly_theta_bonus = theta_differential.get('weeklyThetaGainUSD', 0)
        theta_adjusted_weekly_roi = ((max_profit + weekly_theta_bonus) / margin) * 100 / short_dte * 7
        
        return {
            'rawROI': round(raw_roi, 2),
            'weeklyROI': round(weekly_roi, 2),
            'annualizedROI': round(annualized_roi, 2),
            'thetaAdjustedWeeklyROI': round(theta_adjusted_weekly_roi, 2),
        }


def compare_brokers(short_leg: Dict, long_leg: Dict, 
                    underlying_price: float, option_type: str = 'PUT') -> Dict:
    """
    Porovná margin requirements medzi IBKR a Saxo
    
    Returns:
        Dict s porovnaním oboch brokerov
    """
    ibkr_calc = MarginCalculator('IBKR')
    saxo_calc = MarginCalculator('SAXO')
    
    ibkr_margin = ibkr_calc.calculate_margin(short_leg, long_leg, underlying_price, option_type)
    saxo_margin = saxo_calc.calculate_margin(short_leg, long_leg, underlying_price, option_type)
    
    return {
        'IBKR': ibkr_margin,
        'SAXO': saxo_margin,
        'marginDifference': round(saxo_margin['margin'] - ibkr_margin['margin'], 2),
        'marginDifferencePct': round((saxo_margin['margin'] / ibkr_margin['margin'] - 1) * 100, 2) if ibkr_margin['margin'] > 0 else 0,
        'recommendation': 'IBKR' if ibkr_margin['margin'] < saxo_margin['margin'] else 'SAXO',
    }


# === TESTY ===
if __name__ == '__main__':
    # Test credit spread margin
    print("=== TEST MARGIN CALCULATOR ===\n")
    
    # Príklad: SPY PUT credit spread
    short_leg = {'strike': 590, 'expiry': '20250103', 'premium': 0.85}
    long_leg = {'strike': 565, 'expiry': '20250103', 'premium': 0.45}
    underlying_price = 607.50
    
    print("Vertikálny PUT spread:")
    print(f"  Short: {short_leg['strike']} @ ${short_leg['premium']}")
    print(f"  Long:  {long_leg['strike']} @ ${long_leg['premium']}")
    print()
    
    # IBKR
    ibkr = MarginCalculator('IBKR')
    ibkr_result = ibkr.calculate_margin(short_leg, long_leg, underlying_price, 'PUT')
    print(f"IBKR Margin: ${ibkr_result['margin']}")
    print(f"  ROI on Margin: {ibkr_result['roiOnMargin']}%")
    
    # Saxo
    saxo = MarginCalculator('SAXO')
    saxo_result = saxo.calculate_margin(short_leg, long_leg, underlying_price, 'PUT')
    print(f"\nSaxo Margin: ${saxo_result['margin']}")
    print(f"  ROI on Margin: {saxo_result['roiOnMargin']}%")
    
    # Diagonal spread test
    print("\n" + "="*50)
    print("Diagonálny spread (rôzne expirácie):")
    
    short_leg_diag = {'strike': 590, 'expiry': '20250103', 'premium': 0.85, 'theta': -0.0456}
    long_leg_diag = {'strike': 565, 'expiry': '20250117', 'premium': 0.55, 'theta': -0.0234}
    
    print(f"  Short: {short_leg_diag['strike']} exp {short_leg_diag['expiry']} @ ${short_leg_diag['premium']}")
    print(f"  Long:  {long_leg_diag['strike']} exp {long_leg_diag['expiry']} @ ${long_leg_diag['premium']}")
    
    diag_result = ibkr.calculate_margin(short_leg_diag, long_leg_diag, underlying_price, 'PUT')
    print(f"\nIBKR Diagonal Margin: ${diag_result['margin']}")
    print(f"  Spread Type: {diag_result['spreadType']}")
    
    # Theta analysis
    print("\n" + "="*50)
    print("Theta Analysis:")
    
    theta_diff = ThetaAnalyzer.calculate_theta_differential(
        short_leg_diag['theta'], long_leg_diag['theta'],
        ThetaAnalyzer.days_to_expiry(short_leg_diag['expiry']),
        ThetaAnalyzer.days_to_expiry(long_leg_diag['expiry'])
    )
    print(f"  Net Theta: {theta_diff['netTheta']} (daily)")
    print(f"  Weekly Theta Gain: ${theta_diff['weeklyThetaGainUSD']}")
    print(f"  DTE Offset: {theta_diff['dteOffset']} days")
    print(f"  Decay Efficiency: {theta_diff['decayEfficiency']}")
