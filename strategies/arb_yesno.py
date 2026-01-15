"""
Yes/No arbitrage strategy for Kalshi markets.
Identifies and exploits pricing inefficiencies between Yes and No sides.
"""
import logging
from typing import Dict, List, Optional, Any
from dataclasses import dataclass

from connectors.kalshi_rest import KalshiRestClient
from risk.limits import RiskManager


logger = logging.getLogger(__name__)


@dataclass
class ArbitrageOpportunity:
    """Represents an arbitrage opportunity."""
    ticker: str
    yes_price: float
    no_price: float
    expected_profit: float
    size: int


class YesNoArbitrageStrategy:
    """
    Arbitrage strategy that exploits Yes/No pricing inefficiencies.
    
    In prediction markets, Yes + No prices should equal 100 cents.
    When Yes + No < 100, there's an arbitrage opportunity to buy both sides.
    When Yes + No > 100, theoretical arb exists but requires shorting.
    """
    
    def __init__(
        self,
        kalshi_client: KalshiRestClient,
        risk_manager: RiskManager,
        min_spread: float = 0.02,
        min_profit: int = 5,
        max_position_size: int = 100
    ):
        """
        Initialize arbitrage strategy.
        
        Args:
            kalshi_client: Kalshi REST API client
            risk_manager: Risk management system
            min_spread: Minimum spread to consider (as decimal, e.g., 0.02 = 2%)
            min_profit: Minimum profit in cents per contract
            max_position_size: Maximum position size per trade
        """
        self.kalshi = kalshi_client
        self.risk_manager = risk_manager
        self.min_spread = min_spread
        self.min_profit = min_profit
        self.max_position_size = max_position_size
        self.active_positions: Dict[str, Dict[str, Any]] = {}
    
    def _calculate_arbitrage(
        self,
        ticker: str,
        yes_bid: int,
        yes_ask: int,
        no_bid: int,
        no_ask: int
    ) -> Optional[ArbitrageOpportunity]:
        """
        Calculate arbitrage opportunity from orderbook prices.
        
        Args:
            ticker: Market ticker
            yes_bid: Best bid price for Yes side (cents)
            yes_ask: Best ask price for Yes side (cents)
            no_bid: Best bid price for No side (cents)
            no_ask: Best ask price for No side (cents)
            
        Returns:
            ArbitrageOpportunity if found, None otherwise
        """
        # Buy Yes at ask, Buy No at ask - total cost should be < 100
        total_cost = yes_ask + no_ask
        
        if total_cost >= 100:
            return None
        
        # Calculate expected profit per contract
        expected_profit = 100 - total_cost
        
        # Check if profit meets minimum threshold
        if expected_profit < self.min_profit:
            return None
        
        # Calculate spread percentage
        spread_pct = expected_profit / 100.0
        
        if spread_pct < self.min_spread:
            return None
        
        return ArbitrageOpportunity(
            ticker=ticker,
            yes_price=yes_ask / 100.0,
            no_price=no_ask / 100.0,
            expected_profit=expected_profit / 100.0,
            size=self.max_position_size
        )
    
    async def scan_markets(self, markets: List[Dict[str, Any]]) -> List[ArbitrageOpportunity]:
        """
        Scan markets for arbitrage opportunities.
        
        Args:
            markets: List of market data with orderbook info
            
        Returns:
            List of arbitrage opportunities
        """
        opportunities = []
        
        for market in markets:
            ticker = market.get('ticker')
            if not ticker:
                continue
            
            # Extract orderbook data
            orderbook = market.get('orderbook', {})
            yes_book = orderbook.get('yes', {})
            no_book = orderbook.get('no', {})
            
            yes_asks = yes_book.get('asks', [])
            no_asks = no_book.get('asks', [])
            
            if not yes_asks or not no_asks:
                continue
            
            # Get best ask prices
            yes_ask = yes_asks[0].get('price')
            no_ask = no_asks[0].get('price')
            
            if yes_ask is None or no_ask is None:
                continue
            
            # Get bid prices for reference
            yes_bids = yes_book.get('bids', [])
            no_bids = no_book.get('bids', [])
            
            yes_bid = yes_bids[0].get('price') if yes_bids else 0
            no_bid = no_bids[0].get('price') if no_bids else 0
            
            # Check for arbitrage
            opportunity = self._calculate_arbitrage(
                ticker, yes_bid, yes_ask, no_bid, no_ask
            )
            
            if opportunity:
                opportunities.append(opportunity)
                logger.info(
                    f"Arbitrage found: {ticker} - "
                    f"Yes: {yes_ask}¢, No: {no_ask}¢, "
                    f"Profit: {opportunity.expected_profit:.2%}"
                )
        
        return opportunities
    
    async def execute_arbitrage(self, opportunity: ArbitrageOpportunity) -> bool:
        """
        Execute arbitrage trade by buying both Yes and No sides.
        
        Args:
            opportunity: Arbitrage opportunity to execute
            
        Returns:
            True if execution successful, False otherwise
        """
        ticker = opportunity.ticker
        size = opportunity.size
        
        # Check risk limits
        if not self.risk_manager.can_trade(ticker, size * 100):  # Convert to cents
            logger.warning(f"Risk limits prevent arbitrage on {ticker}")
            return False
        
        try:
            # Place order for Yes side
            yes_order = await self.kalshi.place_order(
                ticker=ticker,
                action="buy",
                side="yes",
                count=size,
                type="limit",
                yes_price=int(opportunity.yes_price * 100)
            )
            
            # Place order for No side
            no_order = await self.kalshi.place_order(
                ticker=ticker,
                action="buy",
                side="no",
                count=size,
                type="limit",
                no_price=int(opportunity.no_price * 100)
            )
            
            # Record position
            self.active_positions[ticker] = {
                'yes_order': yes_order,
                'no_order': no_order,
                'size': size,
                'expected_profit': opportunity.expected_profit
            }
            
            # Update risk manager
            total_cost = size * (opportunity.yes_price + opportunity.no_price) * 100
            self.risk_manager.record_trade(ticker, total_cost)
            
            logger.info(
                f"Executed arbitrage on {ticker}: "
                f"Size={size}, Expected profit={opportunity.expected_profit:.2%}"
            )
            
            return True
        
        except Exception as e:
            logger.error(f"Failed to execute arbitrage on {ticker}: {e}")
            return False
    
    async def close_position(self, ticker: str) -> bool:
        """
        Close an arbitrage position (if market resolution allows).
        
        Args:
            ticker: Market ticker to close
            
        Returns:
            True if successfully closed
        """
        if ticker not in self.active_positions:
            logger.warning(f"No active position for {ticker}")
            return False
        
        position = self.active_positions[ticker]
        
        try:
            # Get current market state
            market = await self.kalshi.get_market(ticker)
            status = market.get('status')
            
            # If market is settled, positions are automatically resolved
            if status in ['closed', 'settled']:
                logger.info(f"Position on {ticker} resolved by market settlement")
                del self.active_positions[ticker]
                return True
            
            # Otherwise, would need to sell positions (not pure arbitrage anymore)
            logger.warning(f"Cannot close arbitrage position on {ticker} - market still active")
            return False
        
        except Exception as e:
            logger.error(f"Failed to close position on {ticker}: {e}")
            return False
