"""
Main runner for the Kalshi trading bot.
Orchestrates strategy execution with async event loop.
"""
import asyncio
import logging
import os
import signal
import sys
from typing import Optional
from dotenv import load_dotenv

from connectors.kalshi_rest import KalshiRestClient
from connectors.kalshi_ws import KalshiWebSocketClient
from strategies.arb_yesno import YesNoArbitrageStrategy
from strategies.value_model import ValueModelStrategy
from risk.limits import RiskManager


# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler('trading_bot.log')
    ]
)
logger = logging.getLogger(__name__)


class TradingBot:
    """Main trading bot orchestrator."""
    
    def __init__(self):
        """Initialize trading bot with configuration."""
        # Load environment variables
        load_dotenv()
        
        # Get configuration
        self.api_key = os.getenv('KALSHI_API_KEY')
        self.private_key_path = os.getenv('KALSHI_PRIVATE_KEY_PATH')
        self.api_base = os.getenv('KALSHI_API_BASE', 'https://api.elections.kalshi.com/trade-api/v2')
        self.ws_base = os.getenv('KALSHI_WS_BASE', 'wss://api.elections.kalshi.com/trade-api/ws/v2')
        
        # Risk parameters
        self.max_position_size = float(os.getenv('MAX_POSITION_SIZE', '1000'))
        self.max_daily_loss = float(os.getenv('MAX_DAILY_LOSS', '500'))
        self.kill_switch_loss = float(os.getenv('KILL_SWITCH_LOSS', '1000'))
        
        # Strategy parameters
        self.arb_min_spread = float(os.getenv('ARB_MIN_SPREAD', '0.02'))
        self.value_threshold = float(os.getenv('VALUE_MODEL_THRESHOLD', '0.05'))
        
        # Components
        self.rest_client: Optional[KalshiRestClient] = None
        self.ws_client: Optional[KalshiWebSocketClient] = None
        self.risk_manager: Optional[RiskManager] = None
        self.arb_strategy: Optional[YesNoArbitrageStrategy] = None
        self.value_strategy: Optional[ValueModelStrategy] = None
        
        # Control flags
        self.running = False
        self.shutdown_event = asyncio.Event()
    
    def _validate_config(self):
        """Validate required configuration."""
        if not self.api_key:
            raise ValueError("KALSHI_API_KEY not set in environment")
        
        if not self.private_key_path:
            raise ValueError("KALSHI_PRIVATE_KEY_PATH not set in environment")
        
        if not os.path.exists(self.private_key_path):
            raise ValueError(f"Private key file not found: {self.private_key_path}")
        
        logger.info("Configuration validated successfully")
    
    def _setup_signal_handlers(self):
        """Setup graceful shutdown signal handlers."""
        def signal_handler(signum, frame):
            logger.info(f"Received signal {signum}, initiating shutdown...")
            self.shutdown_event.set()
        
        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)
    
    async def initialize(self):
        """Initialize all components."""
        logger.info("Initializing trading bot...")
        
        # Validate configuration
        self._validate_config()
        
        # Initialize risk manager
        self.risk_manager = RiskManager(
            max_position_size=self.max_position_size,
            max_daily_loss=self.max_daily_loss,
            kill_switch_loss=self.kill_switch_loss
        )
        
        # Initialize REST client
        self.rest_client = KalshiRestClient(
            api_key=self.api_key,
            private_key_path=self.private_key_path,
            base_url=self.api_base
        )
        
        # Initialize WebSocket client
        self.ws_client = KalshiWebSocketClient(
            api_key=self.api_key,
            ws_url=self.ws_base
        )
        
        # Initialize strategies
        self.arb_strategy = YesNoArbitrageStrategy(
            kalshi_client=self.rest_client,
            risk_manager=self.risk_manager,
            min_spread=self.arb_min_spread
        )
        
        # Simple model function for value strategy (placeholder)
        def simple_model(ticker: str, market_data: dict) -> float:
            """
            Placeholder model function.
            In production, this would use ML models, fundamental analysis, etc.
            """
            # Default to market price (no edge)
            return 0.5
        
        self.value_strategy = ValueModelStrategy(
            kalshi_client=self.rest_client,
            risk_manager=self.risk_manager,
            model_fn=simple_model,
            edge_threshold=self.value_threshold
        )
        
        # Setup WebSocket callbacks
        self.ws_client.on_orderbook(self._handle_orderbook_update)
        self.ws_client.on_trades(self._handle_trade_update)
        self.ws_client.on_error(self._handle_ws_error)
        
        logger.info("Trading bot initialized successfully")
    
    async def _handle_orderbook_update(self, data: dict):
        """Handle orderbook update from WebSocket."""
        ticker = data.get('ticker')
        logger.debug(f"Orderbook update: {ticker}")
        
        # Could trigger strategy analysis here
        # For now, we scan markets periodically instead
    
    async def _handle_trade_update(self, data: dict):
        """Handle trade update from WebSocket."""
        ticker = data.get('ticker')
        logger.debug(f"Trade update: {ticker}")
    
    async def _handle_ws_error(self, error: Exception):
        """Handle WebSocket error."""
        logger.error(f"WebSocket error: {error}")
    
    async def scan_and_trade(self):
        """Periodic market scanning and trading loop."""
        logger.info("Starting market scanning loop")
        
        while self.running and not self.shutdown_event.is_set():
            try:
                # Check risk status
                risk_report = self.risk_manager.get_risk_report()
                
                if risk_report['kill_switch_active']:
                    logger.critical("Kill switch active - stopping trading")
                    break
                
                if risk_report['trading_halted']:
                    logger.warning("Trading halted - skipping this cycle")
                    await asyncio.sleep(60)
                    continue
                
                # Get active markets
                async with self.rest_client:
                    markets = await self.rest_client.list_markets(
                        status='open',
                        limit=50
                    )
                
                logger.info(f"Scanning {len(markets)} markets")
                
                # Scan for arbitrage opportunities
                arb_opportunities = await self.arb_strategy.scan_markets(markets)
                
                for opportunity in arb_opportunities:
                    if self.shutdown_event.is_set():
                        break
                    
                    success = await self.arb_strategy.execute_arbitrage(opportunity)
                    if success:
                        logger.info(f"Arbitrage executed: {opportunity.ticker}")
                    
                    # Brief pause between trades
                    await asyncio.sleep(1)
                
                # Scan for value opportunities
                for market in markets:
                    if self.shutdown_event.is_set():
                        break
                    
                    opportunity = await self.value_strategy.analyze_market(market)
                    if opportunity:
                        success = await self.value_strategy.execute_trade(opportunity)
                        if success:
                            logger.info(f"Value trade executed: {opportunity.ticker}")
                        
                        # Brief pause between trades
                        await asyncio.sleep(1)
                
                # Manage existing positions
                await self.value_strategy.manage_positions()
                
                # Log risk status
                logger.info(
                    f"Risk status - "
                    f"Exposure: {risk_report['exposure_pct']:.1f}%, "
                    f"P&L: ${risk_report['daily_pnl']:.2f}, "
                    f"Positions: {risk_report['active_positions']}/{risk_report['max_positions']}"
                )
                
                # Wait before next scan
                await asyncio.sleep(30)  # Scan every 30 seconds
            
            except Exception as e:
                logger.error(f"Error in trading loop: {e}", exc_info=True)
                await asyncio.sleep(10)  # Wait before retrying
    
    async def run(self):
        """Run the trading bot."""
        self._setup_signal_handlers()
        
        try:
            await self.initialize()
            
            self.running = True
            logger.info("Trading bot started")
            
            # Start WebSocket listener (optional, for real-time data)
            # ws_task = asyncio.create_task(self.ws_client.run())
            
            # Start trading loop
            scan_task = asyncio.create_task(self.scan_and_trade())
            
            # Wait for shutdown signal
            await self.shutdown_event.wait()
            
            logger.info("Shutdown signal received, cleaning up...")
            
            # Cleanup
            self.running = False
            
            # Cancel tasks
            scan_task.cancel()
            # if ws_task:
            #     ws_task.cancel()
            
            # Wait for tasks to complete
            try:
                await scan_task
            except asyncio.CancelledError:
                pass
            
            # Disconnect WebSocket
            if self.ws_client:
                await self.ws_client.disconnect()
            
            # Print final risk report
            if self.risk_manager:
                final_report = self.risk_manager.get_risk_report()
                logger.info(f"Final P&L: ${final_report['daily_pnl']:.2f}")
                logger.info(f"Final positions: {final_report['active_positions']}")
            
            logger.info("Trading bot shutdown complete")
        
        except Exception as e:
            logger.critical(f"Fatal error in trading bot: {e}", exc_info=True)
            raise


async def main():
    """Main entry point."""
    bot = TradingBot()
    await bot.run()


if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Bot stopped by user")
    except Exception as e:
        logger.critical(f"Bot crashed: {e}", exc_info=True)
        sys.exit(1)
