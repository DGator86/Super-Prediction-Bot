"""Tests for arbitrage strategy."""
import pytest
from unittest.mock import AsyncMock, Mock
from strategies.arb_yesno import YesNoArbitrageStrategy, ArbitrageOpportunity
from risk.limits import RiskManager


@pytest.fixture
def mock_kalshi_client():
    """Create mock Kalshi client."""
    client = Mock()
    client.place_order = AsyncMock()
    client.get_market = AsyncMock()
    return client


@pytest.fixture
def risk_manager():
    """Create risk manager."""
    return RiskManager(
        max_position_size=1000.0,
        max_daily_loss=500.0
    )


@pytest.fixture
def arb_strategy(mock_kalshi_client, risk_manager):
    """Create arbitrage strategy."""
    return YesNoArbitrageStrategy(
        kalshi_client=mock_kalshi_client,
        risk_manager=risk_manager,
        min_spread=0.02,
        min_profit=5,
        max_position_size=100
    )


def test_calculate_arbitrage_opportunity(arb_strategy):
    """Test arbitrage calculation with valid opportunity."""
    # Yes ask: 45, No ask: 48, Total: 93 (profit: 7 cents)
    opportunity = arb_strategy._calculate_arbitrage(
        ticker="TEST-MARKET",
        yes_bid=43,
        yes_ask=45,
        no_bid=46,
        no_ask=48
    )
    
    assert opportunity is not None
    assert opportunity.ticker == "TEST-MARKET"
    assert opportunity.yes_price == 0.45
    assert opportunity.no_price == 0.48
    assert opportunity.expected_profit == 0.07


def test_calculate_arbitrage_no_opportunity(arb_strategy):
    """Test no arbitrage when prices sum to 100 or more."""
    # Yes ask: 52, No ask: 50, Total: 102 (no opportunity)
    opportunity = arb_strategy._calculate_arbitrage(
        ticker="TEST-MARKET",
        yes_bid=50,
        yes_ask=52,
        no_bid=48,
        no_ask=50
    )
    
    assert opportunity is None


def test_calculate_arbitrage_below_min_profit(arb_strategy):
    """Test arbitrage rejected when below minimum profit."""
    # Yes ask: 48, No ask: 49, Total: 97 (profit: 3 cents, below min of 5)
    opportunity = arb_strategy._calculate_arbitrage(
        ticker="TEST-MARKET",
        yes_bid=46,
        yes_ask=48,
        no_bid=47,
        no_ask=49
    )
    
    assert opportunity is None


@pytest.mark.asyncio
async def test_scan_markets_finds_opportunity(arb_strategy):
    """Test scanning markets finds valid arbitrage."""
    markets = [
        {
            'ticker': 'ARB-MARKET',
            'orderbook': {
                'yes': {
                    'asks': [{'price': 45}],
                    'bids': [{'price': 43}]
                },
                'no': {
                    'asks': [{'price': 48}],
                    'bids': [{'price': 46}]
                }
            }
        }
    ]
    
    opportunities = await arb_strategy.scan_markets(markets)
    
    assert len(opportunities) == 1
    assert opportunities[0].ticker == 'ARB-MARKET'


@pytest.mark.asyncio
async def test_scan_markets_no_opportunity(arb_strategy):
    """Test scanning markets with no arbitrage."""
    markets = [
        {
            'ticker': 'NO-ARB-MARKET',
            'orderbook': {
                'yes': {
                    'asks': [{'price': 52}],
                    'bids': [{'price': 50}]
                },
                'no': {
                    'asks': [{'price': 50}],
                    'bids': [{'price': 48}]
                }
            }
        }
    ]
    
    opportunities = await arb_strategy.scan_markets(markets)
    
    assert len(opportunities) == 0


@pytest.mark.asyncio
async def test_execute_arbitrage_success(arb_strategy, mock_kalshi_client):
    """Test successful arbitrage execution."""
    mock_kalshi_client.place_order.return_value = {
        'order_id': '123',
        'status': 'placed'
    }
    
    opportunity = ArbitrageOpportunity(
        ticker="TEST-MARKET",
        yes_price=0.45,
        no_price=0.48,
        expected_profit=0.07,
        size=10
    )
    
    result = await arb_strategy.execute_arbitrage(opportunity)
    
    assert result is True
    assert mock_kalshi_client.place_order.call_count == 2
    assert "TEST-MARKET" in arb_strategy.active_positions


@pytest.mark.asyncio
async def test_execute_arbitrage_risk_limit(arb_strategy, risk_manager):
    """Test arbitrage blocked by risk limits."""
    # Exhaust risk limits
    risk_manager.activate_kill_switch()
    
    opportunity = ArbitrageOpportunity(
        ticker="TEST-MARKET",
        yes_price=0.45,
        no_price=0.48,
        expected_profit=0.07,
        size=10
    )
    
    result = await arb_strategy.execute_arbitrage(opportunity)
    
    assert result is False


@pytest.mark.asyncio
async def test_close_position_settled_market(arb_strategy, mock_kalshi_client):
    """Test closing position on settled market."""
    arb_strategy.active_positions["TEST-MARKET"] = {
        'yes_order': {'order_id': '123'},
        'no_order': {'order_id': '456'},
        'size': 10
    }
    
    mock_kalshi_client.get_market.return_value = {
        'ticker': 'TEST-MARKET',
        'status': 'settled'
    }
    
    result = await arb_strategy.close_position("TEST-MARKET")
    
    assert result is True
    assert "TEST-MARKET" not in arb_strategy.active_positions
