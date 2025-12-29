#!/usr/bin/env python3
"""
Scenario Simulator - What-if analýza pre opčné stratégie

Simuluje:
1. Pohyb ceny podkladu (±1%, ±2%, ±5%)
2. Časový rozpad (theta decay) za 1, 3, 5, 7 dní
3. Kombinovaná analýza cena × čas
"""
import math
from datetime import datetime, date, timedelta
from typing import Dict, List, Optional, Tuple

try:
    from scipy.stats import norm
    SCIPY_AVAILABLE = True
except ImportError:
    SCIPY_AVAILABLE = False


class BlackScholes:
    """Black-Scholes model pre oceňovanie opcií"""
    
    @staticmethod
    def d1(S: float, K: float, T: float, r: float, sigma: float) -> float:
        """Výpočet d1 parametra"""
        if T <= 0 or sigma <= 0:
            return 0
        return (math.log(S / K) + (r + 0.5 * sigma ** 2) * T) / (sigma * math.sqrt(T))
    
    @staticmethod
    def d2(S: float, K: float, T: float, r: float, sigma: float) -> float:
        """Výpočet d2 parametra"""
        if T <= 0 or sigma <= 0:
            return 0
        return BlackScholes.d1(S, K, T, r, sigma) - sigma * math.sqrt(T)
    
    @staticmethod
    def put_price(S: float, K: float, T: float, r: float, sigma: float) -> float:
        """
        Cena PUT opcie
        
        Args:
            S: Cena podkladu
            K: Strike cena
            T: Čas do expirácie (v rokoch)
            r: Bezriziková úroková sadzba
            sigma: Implicitná volatilita
        """
        if not SCIPY_AVAILABLE:
            # Fallback bez scipy
            return max(0, K - S) * 0.5  # Veľmi zjednodušený odhad
        
        if T <= 0:
            return max(0, K - S)
        
        d1 = BlackScholes.d1(S, K, T, r, sigma)
        d2 = BlackScholes.d2(S, K, T, r, sigma)
        
        return K * math.exp(-r * T) * norm.cdf(-d2) - S * norm.cdf(-d1)
    
    @staticmethod
    def call_price(S: float, K: float, T: float, r: float, sigma: float) -> float:
        """
        Cena CALL opcie
        
        Args:
            S: Cena podkladu
            K: Strike cena
            T: Čas do expirácie (v rokoch)
            r: Bezriziková úroková sadzba
            sigma: Implicitná volatilita
        """
        if not SCIPY_AVAILABLE:
            return max(0, S - K) * 0.5
        
        if T <= 0:
            return max(0, S - K)
        
        d1 = BlackScholes.d1(S, K, T, r, sigma)
        d2 = BlackScholes.d2(S, K, T, r, sigma)
        
        return S * norm.cdf(d1) - K * math.exp(-r * T) * norm.cdf(d2)
    
    @staticmethod
    def delta_put(S: float, K: float, T: float, r: float, sigma: float) -> float:
        """Delta pre PUT opciu"""
        if not SCIPY_AVAILABLE or T <= 0:
            return -0.5 if S < K else -0.1
        
        d1 = BlackScholes.d1(S, K, T, r, sigma)
        return norm.cdf(d1) - 1
    
    @staticmethod
    def delta_call(S: float, K: float, T: float, r: float, sigma: float) -> float:
        """Delta pre CALL opciu"""
        if not SCIPY_AVAILABLE or T <= 0:
            return 0.5 if S > K else 0.1
        
        d1 = BlackScholes.d1(S, K, T, r, sigma)
        return norm.cdf(d1)
    
    @staticmethod
    def option_price(S: float, K: float, T: float, r: float, sigma: float, 
                     option_type: str = 'PUT') -> float:
        """Univerzálna funkcia pre cenu opcie"""
        if option_type.upper() == 'PUT':
            return BlackScholes.put_price(S, K, T, r, sigma)
        else:
            return BlackScholes.call_price(S, K, T, r, sigma)
    
    @staticmethod
    def delta(S: float, K: float, T: float, r: float, sigma: float,
              option_type: str = 'PUT') -> float:
        """Univerzálna funkcia pre delta"""
        if option_type.upper() == 'PUT':
            return BlackScholes.delta_put(S, K, T, r, sigma)
        else:
            return BlackScholes.delta_call(S, K, T, r, sigma)


class ScenarioSimulator:
    """
    Simulátor scenárov pre opčné stratégie
    """
    
    DEFAULT_PRICE_MOVES = [-5, -2, -1, 0, 1, 2, 5]  # Percentá
    DEFAULT_TIME_STEPS = [0, 1, 3, 5, 7]  # Dni
    
    def __init__(self, risk_free_rate: float = 0.05):
        """
        Args:
            risk_free_rate: Bezriziková úroková sadzba (default 5%)
        """
        self.risk_free_rate = risk_free_rate
    
    def _days_to_years(self, days: int) -> float:
        """Konverzia dní na roky"""
        return days / 365.0
    
    def _calculate_spread_value(self, underlying_price: float, 
                                 short_strike: float, long_strike: float,
                                 short_dte: int, long_dte: int,
                                 short_iv: float, long_iv: float,
                                 option_type: str = 'PUT') -> Dict:
        """
        Vypočíta hodnotu spreadu pri daných podmienkach
        """
        T_short = self._days_to_years(short_dte)
        T_long = self._days_to_years(long_dte)
        
        short_price = BlackScholes.option_price(
            underlying_price, short_strike, T_short, 
            self.risk_free_rate, short_iv, option_type
        )
        
        long_price = BlackScholes.option_price(
            underlying_price, long_strike, T_long,
            self.risk_free_rate, long_iv, option_type
        )
        
        short_delta = BlackScholes.delta(
            underlying_price, short_strike, T_short,
            self.risk_free_rate, short_iv, option_type
        )
        
        long_delta = BlackScholes.delta(
            underlying_price, long_strike, T_long,
            self.risk_free_rate, long_iv, option_type
        )
        
        # Spread value = long - short (lebo short sme predali)
        # Ak spread_value < pôvodný net_credit, máme zisk
        spread_value = long_price - short_price
        
        return {
            'shortPrice': round(short_price, 4),
            'longPrice': round(long_price, 4),
            'spreadValue': round(spread_value, 4),
            'shortDelta': round(short_delta, 4),
            'longDelta': round(long_delta, 4),
            'netDelta': round(short_delta + long_delta, 4),
        }
    
    def simulate_price_move(self, strategy: Dict, 
                            price_changes: List[float] = None) -> Dict:
        """
        Simuluje dopad zmeny ceny podkladu na P/L
        
        Args:
            strategy: Dict so stratégiou (short_leg, long_leg, atď.)
            price_changes: List percentuálnych zmien (default: ±1%, ±2%, ±5%)
            
        Returns:
            Dict s výsledkami pre každú zmenu ceny
        """
        if price_changes is None:
            price_changes = self.DEFAULT_PRICE_MOVES
        
        current_price = strategy.get('currentPrice', 0)
        short_leg = strategy.get('shortLeg', {})
        long_leg = strategy.get('longLeg', {})
        option_type = strategy.get('optionType', 'PUT')
        
        # Pôvodný net credit
        original_net_credit = strategy.get('strategy', {}).get('netCredit', 0)
        
        # IV z údajov
        short_iv = short_leg.get('iv', 0.18) or 0.18
        long_iv = long_leg.get('iv', 0.18) or 0.18
        
        # DTE
        short_dte = self._calculate_dte(short_leg.get('expiry', ''))
        long_dte = self._calculate_dte(long_leg.get('expiry', ''))
        
        results = []
        
        for pct_change in price_changes:
            new_price = current_price * (1 + pct_change / 100)
            
            spread_calc = self._calculate_spread_value(
                new_price, short_leg['strike'], long_leg['strike'],
                short_dte, long_dte, short_iv, long_iv, option_type
            )
            
            # P/L = original_credit + spread_value (spread_value je záporný ak profitujeme)
            # Alebo: P/L = original_credit - cost_to_close
            # cost_to_close = -spread_value (kúpiť späť)
            pnl = (original_net_credit + spread_calc['spreadValue']) * 100
            pnl_pct = (pnl / (abs(strategy.get('strategy', {}).get('maxLoss', 1)) or 1)) * 100
            
            results.append({
                'priceChange': pct_change,
                'newPrice': round(new_price, 2),
                'spreadValue': spread_calc['spreadValue'],
                'costToClose': round(-spread_calc['spreadValue'], 4),
                'pnl': round(pnl, 2),
                'pnlPct': round(pnl_pct, 2),
                'shortDelta': spread_calc['shortDelta'],
                'netDelta': spread_calc['netDelta'],
            })
        
        return {
            'originalPrice': current_price,
            'originalNetCredit': original_net_credit,
            'scenarios': results,
        }
    
    def simulate_time_decay(self, strategy: Dict,
                            days_forward: List[int] = None) -> Dict:
        """
        Simuluje dopad času (theta decay) na P/L
        
        Args:
            strategy: Dict so stratégiou
            days_forward: List dní do budúcnosti (default: 0, 1, 3, 5, 7)
            
        Returns:
            Dict s výsledkami pre každý časový krok
        """
        if days_forward is None:
            days_forward = self.DEFAULT_TIME_STEPS
        
        current_price = strategy.get('currentPrice', 0)
        short_leg = strategy.get('shortLeg', {})
        long_leg = strategy.get('longLeg', {})
        option_type = strategy.get('optionType', 'PUT')
        
        original_net_credit = strategy.get('strategy', {}).get('netCredit', 0)
        
        short_iv = short_leg.get('iv', 0.18) or 0.18
        long_iv = long_leg.get('iv', 0.18) or 0.18
        
        short_dte = self._calculate_dte(short_leg.get('expiry', ''))
        long_dte = self._calculate_dte(long_leg.get('expiry', ''))
        
        results = []
        
        for days in days_forward:
            new_short_dte = max(0, short_dte - days)
            new_long_dte = max(0, long_dte - days)
            
            spread_calc = self._calculate_spread_value(
                current_price, short_leg['strike'], long_leg['strike'],
                new_short_dte, new_long_dte, short_iv, long_iv, option_type
            )
            
            pnl = (original_net_credit + spread_calc['spreadValue']) * 100
            
            results.append({
                'daysForward': days,
                'shortDTE': new_short_dte,
                'longDTE': new_long_dte,
                'spreadValue': spread_calc['spreadValue'],
                'costToClose': round(-spread_calc['spreadValue'], 4),
                'pnl': round(pnl, 2),
                'shortPrice': spread_calc['shortPrice'],
                'longPrice': spread_calc['longPrice'],
            })
        
        return {
            'currentPrice': current_price,
            'originalNetCredit': original_net_credit,
            'scenarios': results,
        }
    
    def simulate_combined(self, strategy: Dict,
                          price_changes: List[float] = None,
                          days_forward: List[int] = None) -> Dict:
        """
        Kombinovaná simulácia: matica cena × čas
        
        Returns:
            Dict s maticou P/L pre všetky kombinácie
        """
        if price_changes is None:
            price_changes = self.DEFAULT_PRICE_MOVES
        if days_forward is None:
            days_forward = self.DEFAULT_TIME_STEPS
        
        current_price = strategy.get('currentPrice', 0)
        short_leg = strategy.get('shortLeg', {})
        long_leg = strategy.get('longLeg', {})
        option_type = strategy.get('optionType', 'PUT')
        
        original_net_credit = strategy.get('strategy', {}).get('netCredit', 0)
        max_profit = original_net_credit * 100
        max_loss = strategy.get('strategy', {}).get('maxLoss', 0)
        
        short_iv = short_leg.get('iv', 0.18) or 0.18
        long_iv = long_leg.get('iv', 0.18) or 0.18
        
        short_dte = self._calculate_dte(short_leg.get('expiry', ''))
        long_dte = self._calculate_dte(long_leg.get('expiry', ''))
        
        # Matica výsledkov
        matrix = []
        
        for days in days_forward:
            row = {
                'daysForward': days,
                'shortDTE': max(0, short_dte - days),
                'scenarios': []
            }
            
            new_short_dte = max(0, short_dte - days)
            new_long_dte = max(0, long_dte - days)
            
            for pct_change in price_changes:
                new_price = current_price * (1 + pct_change / 100)
                
                spread_calc = self._calculate_spread_value(
                    new_price, short_leg['strike'], long_leg['strike'],
                    new_short_dte, new_long_dte, short_iv, long_iv, option_type
                )
                
                pnl = (original_net_credit + spread_calc['spreadValue']) * 100
                
                # Určenie zóny
                if pnl >= max_profit * 0.5:
                    zone = 'profit'
                elif pnl <= -max_loss * 0.5:
                    zone = 'loss'
                else:
                    zone = 'neutral'
                
                row['scenarios'].append({
                    'priceChange': pct_change,
                    'newPrice': round(new_price, 2),
                    'pnl': round(pnl, 2),
                    'zone': zone,
                    'netDelta': spread_calc['netDelta'],
                })
            
            matrix.append(row)
        
        return {
            'currentPrice': current_price,
            'originalNetCredit': original_net_credit,
            'maxProfit': max_profit,
            'maxLoss': max_loss,
            'priceChanges': price_changes,
            'daysForward': days_forward,
            'matrix': matrix,
        }
    
    def _calculate_dte(self, expiry: str) -> int:
        """Vypočíta DTE z dátumu expirácie"""
        if not expiry:
            return 7  # Default
        try:
            exp_date = datetime.strptime(expiry, '%Y%m%d').date()
            today = date.today()
            return max(0, (exp_date - today).days)
        except:
            return 7
    
    def generate_pnl_table(self, combined_result: Dict) -> str:
        """
        Generuje textovú tabuľku P/L pre zobrazenie
        
        Args:
            combined_result: Výstup z simulate_combined()
            
        Returns:
            Formátovaná textová tabuľka
        """
        price_changes = combined_result['priceChanges']
        matrix = combined_result['matrix']
        
        # Header
        header = "DTE  |"
        for pct in price_changes:
            header += f" {pct:+.0f}%   |"
        
        lines = [
            "=" * len(header),
            f"P/L Matrix (USD per contract) @ ${combined_result['currentPrice']:.2f}",
            "=" * len(header),
            header,
            "-" * len(header),
        ]
        
        # Rows
        for row in matrix:
            line = f" {row['shortDTE']:2d}  |"
            for scenario in row['scenarios']:
                pnl = scenario['pnl']
                if pnl >= 0:
                    line += f" +{pnl:5.0f} |"
                else:
                    line += f" {pnl:6.0f}|"
            lines.append(line)
        
        lines.append("=" * len(header))
        lines.append(f"Max Profit: ${combined_result['maxProfit']:.0f} | Max Loss: ${combined_result['maxLoss']:.0f}")
        
        return "\n".join(lines)


# === TESTY ===
if __name__ == '__main__':
    print("=== TEST SCENARIO SIMULATOR ===\n")
    
    # Príklad stratégie
    strategy = {
        'symbol': 'SPY',
        'currentPrice': 607.50,
        'optionType': 'PUT',
        'shortLeg': {
            'strike': 590,
            'expiry': '20250103',
            'premium': 0.85,
            'iv': 0.18,
            'delta': -0.0823,
        },
        'longLeg': {
            'strike': 565,
            'expiry': '20250117',
            'premium': 0.45,
            'iv': 0.20,
            'delta': -0.0312,
        },
        'strategy': {
            'netCredit': 0.40,
            'maxProfit': 40.00,
            'maxLoss': 2460.00,
        }
    }
    
    simulator = ScenarioSimulator()
    
    # Test price move simulation
    print("Price Move Simulation:")
    print("-" * 40)
    price_result = simulator.simulate_price_move(strategy)
    for s in price_result['scenarios']:
        print(f"  {s['priceChange']:+.0f}% → ${s['newPrice']:.2f}: P/L ${s['pnl']:+.2f}")
    
    # Test time decay simulation
    print("\nTime Decay Simulation:")
    print("-" * 40)
    time_result = simulator.simulate_time_decay(strategy)
    for s in time_result['scenarios']:
        print(f"  +{s['daysForward']}d (DTE {s['shortDTE']}): P/L ${s['pnl']:+.2f}")
    
    # Test combined simulation
    print("\nCombined P/L Matrix:")
    combined = simulator.simulate_combined(strategy)
    print(simulator.generate_pnl_table(combined))
