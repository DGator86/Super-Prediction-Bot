"""
Value-based trading strategy using model predictions.
Compares model predictions to market prices to identify trading opportunities.
"""
import logging
from typing import Dict, List, Optional, Any, Callable
from dataclasses import dataclass
from enum import Enum

from connectors.kalshi_rest import KalshiRestClient
from risk.limits import RiskManager


logger = logging.getLogger(__name__)


class TradeSignal(Enum):
    """Trade signal types."""
    BUY_YES = "buy_yes"
    BUY_NO = "buy_no"
    SELL_YES = "sell_yes"
    SELL_NO = "sell_no"
    HOLD = "hold"


@dataclass
class ValueOpportunity:
    """Represents a value trading opportunity."""
    ticker: str
    signal: TradeSignal
    market_price: float
    model_price: float
    edge: float
    confidence: float
    size: int


class ValueModelStrategy:
    """
    Value-based trading strategy using predictive models.
    
    Compares model's probability estimates to market prices
    and trades when edge exceeds threshold.
    """
    
    def __init__(
        self,
        kalshi_client: KalshiRestClient,
        risk_manager: RiskManager,
        model_fn: Callable[[str, Dict], float],
        edge_threshold: float = 0.05,
        min_confidence: float = 0.60,
        max_position_size: int = 100
    ):
        """
        Initialize value model strategy.
        
        Args:
            kalshi_client: Kalshi REST API client
            risk_manager: Risk management system
            model_fn: Function that takes (ticker, market_data) and returns probability
            edge_threshold: Minimum edge required to trade (as decimal)
            min_confidence: Minimum model confidence to trade
            max_position_size: Maximum position size per trade
        """
        self.kalshi = kalshi_client
        self.risk_manager = risk_manager
        self.model_fn = model_fn
        self.edge_threshold = edge_threshold
        self.min_confidence = min_confidence
        self.max_position_size = max_position_size
        self.active_positions: Dict[str, Dict[str, Any]] = {}
    
    def _calculate_edge(
        self,
        model_prob: float,
        market_price: float
    ) -> float:
        """
        Calculate edge (expected value) of a trade.
        
        Args:
            model_prob: Model's probability estimate (0-1)
            market_price: Current market price (0-1)
            
        Returns:
            Edge as decimal (positive = buy opportunity, negative = sell opportunity)
        """
        # Expected value of buying Yes at market_price
        ev = model_prob * (1.0 - market_price) - (1.0 - model_prob) * market_price
        return ev
    
    def _generate_signal(
        self,
        ticker: str,
        market_price: float,
        model_prob: float,
        confidence: float
    ) -> Optional[ValueOpportunity]:
        """
        Generate trading signal based on model vs market.
        
        Args:
            ticker: Market ticker
            market_price: Current market price (0-1)
            model_prob: Model probability estimate (0-1)
            confidence: Model confidence level (0-1)
            
        Returns:
            ValueOpportunity if signal generated, None otherwise
        """
        # Check minimum confidence
        if confidence < self.min_confidence:
            return None
        
        # Calculate edge
        edge = self._calculate_edge(model_prob, market_price)
        
        # Determine signal
        signal = TradeSignal.HOLD
        
        if edge > self.edge_threshold:
            # Model thinks Yes is underpriced - buy Yes
            signal = TradeSignal.BUY_YES
        elif edge < -self.edge_threshold:
            # Model thinks Yes is overpriced - buy No (or sell Yes if we have it)
            signal = TradeSignal.BUY_NO
        else:
            return None
        
        # Calculate position size based on edge and confidence
        # Simplified Kelly-like sizing: position proportional to edge * confidence
        # Note: Not true Kelly criterion (which requires odds and probabilities)
        # This is a conservative proportional sizing approach
        size_factor = min(abs(edge) * confidence, 1.0)
        size = int(self.max_position_size * size_factor)
        size = max(1, size)  # At least 1 contract
        
        return ValueOpportunity(
            ticker=ticker,
            signal=signal,
            market_price=market_price,
            model_price=model_prob,
            edge=edge,
            confidence=confidence,
            size=size
        )
    
    async def analyze_market(
        self,
        market: Dict[str, Any]
    ) -> Optional[ValueOpportunity]:
        """
        Analyze a single market for value opportunities.
        
        Args:
            market: Market data including ticker and orderbook
            
        Returns:
            ValueOpportunity if found, None otherwise
        """
        ticker = market.get('ticker')
        if not ticker:
            return None
        
        # Get market price (mid-price from orderbook)
        orderbook = market.get('orderbook', {})
        yes_book = orderbook.get('yes', {})
        
        yes_bids = yes_book.get('bids', [])
        yes_asks = yes_book.get('asks', [])
        
        if not yes_bids or not yes_asks:
            return None
        
        best_bid = yes_bids[0].get('price', 0) / 100.0
        best_ask = yes_asks[0].get('price', 100) / 100.0
        market_price = (best_bid + best_ask) / 2.0
        
        # Get model prediction
        try:
            model_result = self.model_fn(ticker, market)
            
            # Handle different return types
            if isinstance(model_result, tuple):
                model_prob, confidence = model_result
            elif isinstance(model_result, dict):
                model_prob = model_result.get('probability', 0.5)
                confidence = model_result.get('confidence', 0.0)
            else:
                model_prob = float(model_result)
                confidence = 0.7  # Default confidence
            
        except Exception as e:
            logger.error(f"Model error for {ticker}: {e}")
            return None
        
        # Generate signal
        opportunity = self._generate_signal(
            ticker, market_price, model_prob, confidence
        )
        
        if opportunity:
            logger.info(
                f"Value opportunity: {ticker} - "
                f"Market: {market_price:.2%}, Model: {model_prob:.2%}, "
                f"Edge: {opportunity.edge:.2%}, Signal: {opportunity.signal.value}"
            )
        
        return opportunity
    
    async def execute_trade(self, opportunity: ValueOpportunity) -> bool:
        """
        Execute value trade.
        
        Args:
            opportunity: Trading opportunity to execute
            
        Returns:
            True if execution successful, False otherwise
        """
        ticker = opportunity.ticker
        size = opportunity.size
        
        # Estimate trade cost
        cost = size * opportunity.market_price * 100  # Convert to cents
        
        # Check risk limits
        if not self.risk_manager.can_trade(ticker, cost):
            logger.warning(f"Risk limits prevent trade on {ticker}")
            return False
        
        try:
            # Determine order parameters based on signal
            if opportunity.signal == TradeSignal.BUY_YES:
                action = "buy"
                side = "yes"
                price = int(opportunity.market_price * 100) + 1  # Slight improvement
            elif opportunity.signal == TradeSignal.BUY_NO:
                action = "buy"
                side = "no"
                price = int((1.0 - opportunity.market_price) * 100) + 1
            else:
                logger.warning(f"Unsupported signal: {opportunity.signal}")
                return False
            
            # Place order
            order = await self.kalshi.place_order(
                ticker=ticker,
                action=action,
                side=side,
                count=size,
                type="limit",
                yes_price=price if side == "yes" else None,
                no_price=price if side == "no" else None
            )
            
            # Record position
            self.active_positions[ticker] = {
                'order': order,
                'signal': opportunity.signal,
                'size': size,
                'entry_price': opportunity.market_price,
                'model_price': opportunity.model_price,
                'edge': opportunity.edge
            }
            
            # Update risk manager
            self.risk_manager.record_trade(ticker, cost)
            
            logger.info(
                f"Executed value trade on {ticker}: "
                f"Signal={opportunity.signal.value}, Size={size}, Edge={opportunity.edge:.2%}"
            )
            
            return True
        
        except Exception as e:
            logger.error(f"Failed to execute trade on {ticker}: {e}")
            return False
    
    async def manage_positions(self):
        """
        Monitor and manage active positions.
        
        Check for exit opportunities or stop-loss triggers.
        """
        for ticker, position in list(self.active_positions.items()):
            try:
                # Get current market state
                market = await self.kalshi.get_market(ticker)
                status = market.get('status')
                
                # If market is settled, position is automatically resolved
                if status in ['closed', 'settled']:
                    logger.info(f"Position on {ticker} resolved by settlement")
                    del self.active_positions[ticker]
                    continue
                
                # Get current order status
                order_id = position['order'].get('order_id')
                if order_id:
                    order = await self.kalshi.get_order(order_id)
                    order_status = order.get('status')
                    
                    if order_status == 'filled':
                        logger.info(f"Order filled for {ticker}")
                        # Position is now active, could implement exit logic here
                    elif order_status == 'canceled':
                        logger.info(f"Order canceled for {ticker}")
                        del self.active_positions[ticker]
            
            except Exception as e:
                logger.error(f"Error managing position {ticker}: {e}")
