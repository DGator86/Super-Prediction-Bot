# Super-Prediction-Bot

A Python-based automated trading bot for prediction markets, with primary support for Kalshi and optional Polymarket integration.

## Features

- **Kalshi Integration**: Full REST and WebSocket API support with RSA-PSS authentication
- **Trading Strategies**:
  - **Yes/No Arbitrage**: Exploits pricing inefficiencies between Yes and No sides
  - **Value Model**: Model-based trading using probability predictions
- **Risk Management**:
  - Maximum position size limits per market
  - Maximum total exposure control
  - Daily loss limits with automatic trading halt
  - Kill switch for critical losses
  - Real-time risk monitoring
- **Async Architecture**: Efficient async/await design for concurrent operations
- **WebSocket Support**: Real-time orderbook and trade data streaming

## Project Structure

```
Super-Prediction-Bot/
├── connectors/
│   ├── kalshi_rest.py      # Kalshi REST API with RSA-PSS signing
│   ├── kalshi_ws.py        # Kalshi WebSocket client
│   └── polymarket.py       # Polymarket connector stub (optional)
├── strategies/
│   ├── arb_yesno.py        # Yes/No arbitrage strategy
│   └── value_model.py      # Value-based model trading
├── risk/
│   └── limits.py           # Risk management system
├── tests/
│   └── test_*.py           # Test suite
├── runner.py               # Main bot runner
├── requirements.txt        # Python dependencies
├── .env.example           # Environment variables template
└── README.md              # This file
```

## Installation

### Prerequisites

- Python 3.8 or higher
- Kalshi API account with API key
- RSA private key for Kalshi authentication

### Setup

1. **Clone the repository**:
```bash
git clone https://github.com/DGator86/Super-Prediction-Bot.git
cd Super-Prediction-Bot
```

2. **Create a virtual environment**:
```bash
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

3. **Install dependencies**:
```bash
pip install -r requirements.txt
```

4. **Configure environment variables**:
```bash
cp .env.example .env
```

Edit `.env` with your configuration:
```bash
# Kalshi API Configuration
KALSHI_API_KEY=your_kalshi_api_key_here
KALSHI_PRIVATE_KEY_PATH=path/to/your/private_key.pem
KALSHI_API_BASE=https://api.elections.kalshi.com/trade-api/v2
KALSHI_WS_BASE=wss://api.elections.kalshi.com/trade-api/ws/v2

# Risk Management
MAX_POSITION_SIZE=1000
MAX_DAILY_LOSS=500
KILL_SWITCH_LOSS=1000

# Strategy Configuration
ARB_MIN_SPREAD=0.02
VALUE_MODEL_THRESHOLD=0.05

# Logging
LOG_LEVEL=INFO
```

5. **Generate RSA key pair** (if you don't have one):
```bash
# Generate private key
openssl genrsa -out private_key.pem 2048

# Extract public key
openssl rsa -in private_key.pem -pubout -out public_key.pem
```

Then upload your public key to Kalshi through their API portal.

## Usage

### Running the Bot

```bash
python runner.py
```

The bot will:
1. Initialize connections to Kalshi
2. Start scanning markets for opportunities
3. Execute trades based on configured strategies
4. Monitor risk limits continuously
5. Log all activity to console and `trading_bot.log`

### Graceful Shutdown

Press `Ctrl+C` to initiate graceful shutdown. The bot will:
- Stop accepting new trades
- Cancel pending tasks
- Close WebSocket connections
- Print final P&L and position report

## Connectors

### Kalshi REST Client

The `KalshiRestClient` provides authenticated access to Kalshi's REST API:

```python
from connectors.kalshi_rest import KalshiRestClient

async with KalshiRestClient(
    api_key="your_key",
    private_key_path="path/to/key.pem"
) as client:
    # Place an order
    order = await client.place_order(
        ticker="PRESIDENT-2024",
        action="buy",
        side="yes",
        count=10,
        type="limit",
        yes_price=55
    )
    
    # List orders
    orders = await client.list_orders(status="open")
    
    # Get portfolio
    portfolio = await client.get_portfolio()
```

### Kalshi WebSocket Client

Subscribe to real-time market data:

```python
from connectors.kalshi_ws import KalshiWebSocketClient

ws_client = KalshiWebSocketClient(api_key="your_key")

# Register callbacks
ws_client.on_orderbook(lambda data: print(f"Orderbook: {data}"))
ws_client.on_trades(lambda data: print(f"Trade: {data}"))

# Connect and subscribe
await ws_client.connect()
await ws_client.subscribe_orderbook(["PRESIDENT-2024"])
await ws_client.subscribe_trades(["PRESIDENT-2024"])

# Listen for messages
await ws_client.listen()
```

## Strategies

### Yes/No Arbitrage

Exploits pricing inefficiencies where Yes + No prices don't equal 100 cents:

```python
from strategies.arb_yesno import YesNoArbitrageStrategy

strategy = YesNoArbitrageStrategy(
    kalshi_client=rest_client,
    risk_manager=risk_manager,
    min_spread=0.02,  # Minimum 2% spread
    min_profit=5      # Minimum 5¢ profit per contract
)

# Scan for opportunities
opportunities = await strategy.scan_markets(markets)

# Execute arbitrage
for opp in opportunities:
    await strategy.execute_arbitrage(opp)
```

### Value Model

Trades based on model predictions vs market prices:

```python
from strategies.value_model import ValueModelStrategy

def my_model(ticker: str, market_data: dict) -> float:
    """Return probability estimate [0, 1]"""
    # Your model logic here
    return 0.65

strategy = ValueModelStrategy(
    kalshi_client=rest_client,
    risk_manager=risk_manager,
    model_fn=my_model,
    edge_threshold=0.05  # Minimum 5% edge to trade
)

# Analyze market
opportunity = await strategy.analyze_market(market)
if opportunity:
    await strategy.execute_trade(opportunity)
```

## Risk Management

The `RiskManager` enforces multiple layers of protection:

```python
from risk.limits import RiskManager

risk_manager = RiskManager(
    max_position_size=1000.0,      # Max per market
    max_total_exposure=5000.0,     # Max total
    max_daily_loss=500.0,          # Daily loss limit
    kill_switch_loss=1000.0,       # Emergency shutdown
    max_positions=10               # Max concurrent positions
)

# Check if trade is allowed
if risk_manager.can_trade(ticker="MARKET-A", trade_size=100):
    # Execute trade
    risk_manager.record_trade(ticker="MARKET-A", trade_size=100)

# Record P&L
risk_manager.record_pnl(pnl=-50.0)

# Get risk report
report = risk_manager.get_risk_report()
```

### Risk Limits

- **Position Limits**: Prevents over-concentration in single markets
- **Exposure Limits**: Controls total capital at risk
- **Daily Loss Limit**: Halts trading after reaching daily loss threshold (resets next day)
- **Kill Switch**: Emergency shutdown at critical loss level (requires manual reset)

## Testing

Run the test suite:

```bash
pytest tests/ -v
```

Run specific tests:

```bash
pytest tests/test_kalshi_rest.py -v
pytest tests/test_risk_limits.py -v
```

## Configuration

### Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `KALSHI_API_KEY` | Your Kalshi API key | Required |
| `KALSHI_PRIVATE_KEY_PATH` | Path to RSA private key | Required |
| `KALSHI_API_BASE` | Kalshi REST API base URL | `https://api.elections.kalshi.com/trade-api/v2` |
| `KALSHI_WS_BASE` | Kalshi WebSocket URL | `wss://api.elections.kalshi.com/trade-api/ws/v2` |
| `MAX_POSITION_SIZE` | Maximum position per market | `1000` |
| `MAX_DAILY_LOSS` | Daily loss limit | `500` |
| `KILL_SWITCH_LOSS` | Critical loss threshold | `1000` |
| `ARB_MIN_SPREAD` | Minimum arbitrage spread | `0.02` |
| `VALUE_MODEL_THRESHOLD` | Minimum edge for value trades | `0.05` |
| `LOG_LEVEL` | Logging level | `INFO` |

## Logging

The bot logs to both console and `trading_bot.log`. Log levels:

- **INFO**: Normal operations, trades executed, risk updates
- **WARNING**: Risk limits approached, trading halted
- **ERROR**: API errors, trade failures
- **CRITICAL**: Kill switch activation, fatal errors

## Development

### Adding New Strategies

1. Create a new file in `strategies/` directory
2. Implement your strategy class
3. Integrate with risk manager
4. Add to `runner.py` initialization

### Adding New Connectors

1. Create a new file in `connectors/` directory
2. Implement REST and/or WebSocket clients
3. Follow existing patterns for error handling
4. Add tests in `tests/` directory

## Safety and Disclaimers

⚠️ **Important**: This is trading software that can lose money.

- Always test with small amounts first
- Use paper trading when available
- Monitor the bot regularly
- Understand the strategies before deploying
- Set conservative risk limits
- Never risk more than you can afford to lose

This software is provided as-is with no guarantees. Trading prediction markets involves risk. Past performance does not guarantee future results.

## License

MIT License - See LICENSE file for details

## Contributing

Contributions are welcome! Please:

1. Fork the repository
2. Create a feature branch
3. Add tests for new functionality
4. Submit a pull request

## Support

For issues and questions:
- Open an issue on GitHub
- Check existing documentation
- Review logs for error messages

## Roadmap

- [ ] Backtesting framework
- [ ] More sophisticated models (ML-based)
- [ ] Multi-exchange arbitrage
- [ ] Advanced order types
- [ ] Web dashboard for monitoring
- [ ] Database integration for historical data
- [ ] Performance analytics and reporting