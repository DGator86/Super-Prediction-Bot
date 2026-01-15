"""
Risk management system with position limits, loss limits, and kill switch.
Monitors trading activity and enforces risk controls.
"""
import logging
from typing import Dict, Optional
from dataclasses import dataclass, field
from datetime import datetime, timedelta


logger = logging.getLogger(__name__)


@dataclass
class RiskMetrics:
    """Current risk metrics."""
    total_exposure: float = 0.0
    daily_pnl: float = 0.0
    positions: Dict[str, float] = field(default_factory=dict)
    daily_trades: int = 0
    last_reset: datetime = field(default_factory=datetime.now)


class RiskManager:
    """
    Risk management system for trading bot.
    
    Enforces:
    - Maximum position size per market
    - Maximum total exposure
    - Maximum daily loss
    - Kill switch for critical losses
    - Position limits per market
    """
    
    def __init__(
        self,
        max_position_size: float = 1000.0,
        max_total_exposure: float = 5000.0,
        max_daily_loss: float = 500.0,
        kill_switch_loss: float = 1000.0,
        max_positions: int = 10
    ):
        """
        Initialize risk manager.
        
        Args:
            max_position_size: Maximum position size per market (in currency units)
            max_total_exposure: Maximum total exposure across all positions
            max_daily_loss: Maximum acceptable daily loss before halting
            kill_switch_loss: Critical loss level that triggers immediate shutdown
            max_positions: Maximum number of concurrent positions
        """
        self.max_position_size = max_position_size
        self.max_total_exposure = max_total_exposure
        self.max_daily_loss = max_daily_loss
        self.kill_switch_loss = kill_switch_loss
        self.max_positions = max_positions
        
        self.metrics = RiskMetrics()
        self.kill_switch_active = False
        self.trading_halted = False
        
        logger.info(
            f"RiskManager initialized - "
            f"MaxPos: {max_position_size}, "
            f"MaxExposure: {max_total_exposure}, "
            f"MaxLoss: {max_daily_loss}, "
            f"KillSwitch: {kill_switch_loss}"
        )
    
    def reset_daily_metrics(self):
        """Reset daily tracking metrics."""
        now = datetime.now()
        
        # Reset if it's a new day
        if now.date() > self.metrics.last_reset.date():
            logger.info("Resetting daily risk metrics")
            self.metrics.daily_pnl = 0.0
            self.metrics.daily_trades = 0
            self.metrics.last_reset = now
            
            # Reset trading halt if it was due to daily loss
            if self.trading_halted and not self.kill_switch_active:
                self.trading_halted = False
                logger.info("Trading resumed after daily reset")
    
    def can_trade(self, ticker: str, trade_size: float) -> bool:
        """
        Check if a trade is allowed under current risk limits.
        
        Args:
            ticker: Market ticker
            trade_size: Size of proposed trade (in currency units)
            
        Returns:
            True if trade is allowed, False otherwise
        """
        self.reset_daily_metrics()
        
        # Check kill switch
        if self.kill_switch_active:
            logger.error("Kill switch active - no trading allowed")
            return False
        
        # Check trading halt
        if self.trading_halted:
            logger.warning("Trading halted - no new trades allowed")
            return False
        
        # Check position limit
        if len(self.metrics.positions) >= self.max_positions and ticker not in self.metrics.positions:
            logger.warning(f"Maximum positions reached ({self.max_positions})")
            return False
        
        # Check per-market position size
        current_position = self.metrics.positions.get(ticker, 0.0)
        new_position = current_position + trade_size
        
        if new_position > self.max_position_size:
            logger.warning(
                f"Position size limit exceeded for {ticker}: "
                f"{new_position} > {self.max_position_size}"
            )
            return False
        
        # Check total exposure
        new_total_exposure = self.metrics.total_exposure + trade_size
        
        if new_total_exposure > self.max_total_exposure:
            logger.warning(
                f"Total exposure limit exceeded: "
                f"{new_total_exposure} > {self.max_total_exposure}"
            )
            return False
        
        return True
    
    def record_trade(self, ticker: str, trade_size: float):
        """
        Record a trade and update risk metrics.
        
        Args:
            ticker: Market ticker
            trade_size: Size of trade executed (in currency units)
        """
        # Update position
        if ticker in self.metrics.positions:
            self.metrics.positions[ticker] += trade_size
        else:
            self.metrics.positions[ticker] = trade_size
        
        # Update total exposure
        self.metrics.total_exposure += trade_size
        
        # Update daily trades
        self.metrics.daily_trades += 1
        
        logger.info(
            f"Trade recorded: {ticker}, Size: {trade_size:.2f}, "
            f"Total exposure: {self.metrics.total_exposure:.2f}"
        )
    
    def record_pnl(self, pnl: float):
        """
        Record profit/loss and check risk limits.
        
        Args:
            pnl: Profit (positive) or loss (negative) amount
        """
        self.reset_daily_metrics()
        
        self.metrics.daily_pnl += pnl
        
        logger.info(f"P&L recorded: {pnl:.2f}, Daily P&L: {self.metrics.daily_pnl:.2f}")
        
        # Check kill switch threshold
        if self.metrics.daily_pnl <= -self.kill_switch_loss:
            self.activate_kill_switch()
            return
        
        # Check daily loss threshold
        if self.metrics.daily_pnl <= -self.max_daily_loss:
            self.halt_trading()
    
    def activate_kill_switch(self):
        """
        Activate emergency kill switch.
        
        Immediately halts all trading activity.
        Requires manual intervention to reset.
        """
        self.kill_switch_active = True
        self.trading_halted = True
        
        logger.critical(
            f"KILL SWITCH ACTIVATED - Daily loss: {self.metrics.daily_pnl:.2f}"
        )
        logger.critical("Manual intervention required to resume trading")
    
    def halt_trading(self):
        """
        Halt trading due to daily loss limit.
        
        Can be automatically reset on next day.
        """
        self.trading_halted = True
        
        logger.error(
            f"Trading halted - Daily loss limit reached: {self.metrics.daily_pnl:.2f}"
        )
        logger.error("Trading will resume after daily reset")
    
    def reset_kill_switch(self):
        """
        Manually reset kill switch.
        
        Should only be called after reviewing the situation.
        """
        logger.warning("Resetting kill switch - manual override")
        self.kill_switch_active = False
        self.trading_halted = False
    
    def close_position(self, ticker: str, exit_value: float):
        """
        Close a position and realize P&L.
        
        Args:
            ticker: Market ticker
            exit_value: Exit value of position
        """
        if ticker not in self.metrics.positions:
            logger.warning(f"No position found for {ticker}")
            return
        
        entry_value = self.metrics.positions[ticker]
        pnl = exit_value - entry_value
        
        # Update metrics
        self.metrics.total_exposure -= entry_value
        del self.metrics.positions[ticker]
        self.record_pnl(pnl)
        
        logger.info(
            f"Position closed: {ticker}, "
            f"Entry: {entry_value:.2f}, Exit: {exit_value:.2f}, "
            f"P&L: {pnl:.2f}"
        )
    
    def get_risk_report(self) -> Dict:
        """
        Get current risk status report.
        
        Returns:
            Dictionary with risk metrics and status
        """
        self.reset_daily_metrics()
        
        return {
            'kill_switch_active': self.kill_switch_active,
            'trading_halted': self.trading_halted,
            'total_exposure': self.metrics.total_exposure,
            'max_total_exposure': self.max_total_exposure,
            'exposure_pct': self.metrics.total_exposure / self.max_total_exposure * 100,
            'daily_pnl': self.metrics.daily_pnl,
            'max_daily_loss': self.max_daily_loss,
            'kill_switch_loss': self.kill_switch_loss,
            'active_positions': len(self.metrics.positions),
            'max_positions': self.max_positions,
            'daily_trades': self.metrics.daily_trades,
            'positions': dict(self.metrics.positions)
        }
