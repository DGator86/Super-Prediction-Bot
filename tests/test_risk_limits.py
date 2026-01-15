"""Tests for risk management system."""
import pytest
from datetime import datetime, timedelta
from risk.limits import RiskManager, RiskMetrics


@pytest.fixture
def risk_manager():
    """Create a test risk manager."""
    return RiskManager(
        max_position_size=100.0,
        max_total_exposure=500.0,
        max_daily_loss=50.0,
        kill_switch_loss=100.0,
        max_positions=5
    )


def test_initialization(risk_manager):
    """Test risk manager initializes correctly."""
    assert risk_manager.max_position_size == 100.0
    assert risk_manager.max_total_exposure == 500.0
    assert risk_manager.max_daily_loss == 50.0
    assert risk_manager.kill_switch_loss == 100.0
    assert risk_manager.max_positions == 5
    assert not risk_manager.kill_switch_active
    assert not risk_manager.trading_halted


def test_can_trade_normal(risk_manager):
    """Test can_trade allows normal trades."""
    assert risk_manager.can_trade("MARKET-A", 50.0)


def test_can_trade_position_limit(risk_manager):
    """Test can_trade respects position size limit."""
    assert not risk_manager.can_trade("MARKET-A", 150.0)  # Exceeds max_position_size


def test_can_trade_total_exposure(risk_manager):
    """Test can_trade respects total exposure limit."""
    # Add some positions
    risk_manager.record_trade("MARKET-A", 100.0)
    risk_manager.record_trade("MARKET-B", 100.0)
    risk_manager.record_trade("MARKET-C", 100.0)
    risk_manager.record_trade("MARKET-D", 100.0)
    risk_manager.record_trade("MARKET-E", 100.0)
    
    # Total exposure is now 500, at limit
    assert not risk_manager.can_trade("MARKET-F", 50.0)  # Would exceed total


def test_can_trade_max_positions(risk_manager):
    """Test can_trade respects max positions limit."""
    # Fill up to max positions
    for i in range(5):
        risk_manager.record_trade(f"MARKET-{i}", 10.0)
    
    # Should not allow new position
    assert not risk_manager.can_trade("MARKET-NEW", 10.0)
    
    # But should allow adding to existing position
    assert risk_manager.can_trade("MARKET-0", 10.0)


def test_record_trade(risk_manager):
    """Test recording trades."""
    risk_manager.record_trade("MARKET-A", 50.0)
    
    assert risk_manager.metrics.total_exposure == 50.0
    assert risk_manager.metrics.positions["MARKET-A"] == 50.0
    assert risk_manager.metrics.daily_trades == 1


def test_record_pnl(risk_manager):
    """Test recording P&L."""
    risk_manager.record_pnl(10.0)
    assert risk_manager.metrics.daily_pnl == 10.0
    
    risk_manager.record_pnl(-5.0)
    assert risk_manager.metrics.daily_pnl == 5.0


def test_daily_loss_limit(risk_manager):
    """Test daily loss limit halts trading."""
    risk_manager.record_pnl(-60.0)  # Exceeds max_daily_loss
    
    assert risk_manager.trading_halted
    assert not risk_manager.kill_switch_active


def test_kill_switch_activation(risk_manager):
    """Test kill switch activates on critical loss."""
    risk_manager.record_pnl(-110.0)  # Exceeds kill_switch_loss
    
    assert risk_manager.kill_switch_active
    assert risk_manager.trading_halted


def test_kill_switch_prevents_trading(risk_manager):
    """Test kill switch prevents all trading."""
    risk_manager.activate_kill_switch()
    
    assert not risk_manager.can_trade("MARKET-A", 10.0)


def test_close_position(risk_manager):
    """Test closing positions."""
    risk_manager.record_trade("MARKET-A", 50.0)
    risk_manager.close_position("MARKET-A", 60.0)
    
    assert "MARKET-A" not in risk_manager.metrics.positions
    assert risk_manager.metrics.daily_pnl == 10.0  # Profit of 10
    assert risk_manager.metrics.total_exposure == 0.0


def test_reset_daily_metrics(risk_manager):
    """Test daily metrics reset."""
    risk_manager.record_pnl(-20.0)
    risk_manager.metrics.daily_trades = 5
    
    # Simulate next day
    risk_manager.metrics.last_reset = datetime.now() - timedelta(days=1)
    risk_manager.reset_daily_metrics()
    
    assert risk_manager.metrics.daily_pnl == 0.0
    assert risk_manager.metrics.daily_trades == 0


def test_get_risk_report(risk_manager):
    """Test risk report generation."""
    risk_manager.record_trade("MARKET-A", 100.0)
    risk_manager.record_pnl(-10.0)
    
    report = risk_manager.get_risk_report()
    
    assert report['total_exposure'] == 100.0
    assert report['daily_pnl'] == -10.0
    assert report['active_positions'] == 1
    assert report['max_positions'] == 5
    assert 'positions' in report
    assert not report['kill_switch_active']
    assert not report['trading_halted']


def test_reset_kill_switch(risk_manager):
    """Test manual kill switch reset."""
    risk_manager.activate_kill_switch()
    assert risk_manager.kill_switch_active
    
    risk_manager.reset_kill_switch()
    assert not risk_manager.kill_switch_active
    assert not risk_manager.trading_halted


def test_exposure_percentage(risk_manager):
    """Test exposure percentage calculation."""
    risk_manager.record_trade("MARKET-A", 250.0)  # 50% of max
    
    report = risk_manager.get_risk_report()
    assert report['exposure_pct'] == 50.0
