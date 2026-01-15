"""
Kalshi WebSocket connector for real-time orderbook and trade data.
Supports subscribing to orderbook updates and trade feeds.
"""
import asyncio
import json
from typing import Callable, Dict, List, Optional, Set, Any
import logging

import websockets
from websockets.client import WebSocketClientProtocol


logger = logging.getLogger(__name__)


class KalshiWebSocketClient:
    """WebSocket client for Kalshi real-time data streams."""
    
    def __init__(
        self,
        api_key: str,
        ws_url: str = "wss://api.elections.kalshi.com/trade-api/ws/v2"
    ):
        """
        Initialize Kalshi WebSocket client.
        
        Args:
            api_key: Kalshi API key
            ws_url: WebSocket endpoint URL
        """
        self.api_key = api_key
        self.ws_url = ws_url
        self.ws: Optional[WebSocketClientProtocol] = None
        self.running = False
        self.subscriptions: Set[str] = set()
        self.callbacks: Dict[str, List[Callable]] = {
            'orderbook': [],
            'trades': [],
            'ticker': [],
            'error': []
        }
    
    async def connect(self):
        """Establish WebSocket connection."""
        try:
            self.ws = await websockets.connect(
                self.ws_url,
                extra_headers={'X-KALSHI-API-KEY': self.api_key}
            )
            self.running = True
            logger.info(f"Connected to Kalshi WebSocket: {self.ws_url}")
        except Exception as e:
            logger.error(f"Failed to connect to WebSocket: {e}")
            raise
    
    async def disconnect(self):
        """Close WebSocket connection."""
        self.running = False
        if self.ws:
            await self.ws.close()
            logger.info("Disconnected from Kalshi WebSocket")
    
    async def subscribe_orderbook(self, tickers: List[str]):
        """
        Subscribe to orderbook updates for specific tickers.
        
        Args:
            tickers: List of market ticker symbols
        """
        if not self.ws:
            raise RuntimeError("WebSocket not connected")
        
        for ticker in tickers:
            subscription_msg = {
                "type": "subscribe",
                "channel": "orderbook",
                "ticker": ticker
            }
            await self.ws.send(json.dumps(subscription_msg))
            self.subscriptions.add(f"orderbook:{ticker}")
            logger.info(f"Subscribed to orderbook: {ticker}")
    
    async def subscribe_trades(self, tickers: List[str]):
        """
        Subscribe to trade feed for specific tickers.
        
        Args:
            tickers: List of market ticker symbols
        """
        if not self.ws:
            raise RuntimeError("WebSocket not connected")
        
        for ticker in tickers:
            subscription_msg = {
                "type": "subscribe",
                "channel": "trades",
                "ticker": ticker
            }
            await self.ws.send(json.dumps(subscription_msg))
            self.subscriptions.add(f"trades:{ticker}")
            logger.info(f"Subscribed to trades: {ticker}")
    
    async def subscribe_ticker(self, tickers: List[str]):
        """
        Subscribe to ticker updates for specific tickers.
        
        Args:
            tickers: List of market ticker symbols
        """
        if not self.ws:
            raise RuntimeError("WebSocket not connected")
        
        for ticker in tickers:
            subscription_msg = {
                "type": "subscribe",
                "channel": "ticker",
                "ticker": ticker
            }
            await self.ws.send(json.dumps(subscription_msg))
            self.subscriptions.add(f"ticker:{ticker}")
            logger.info(f"Subscribed to ticker: {ticker}")
    
    async def unsubscribe(self, channel: str, ticker: str):
        """
        Unsubscribe from a specific channel and ticker.
        
        Args:
            channel: Channel name ('orderbook', 'trades', or 'ticker')
            ticker: Market ticker symbol
        """
        if not self.ws:
            raise RuntimeError("WebSocket not connected")
        
        unsubscribe_msg = {
            "type": "unsubscribe",
            "channel": channel,
            "ticker": ticker
        }
        await self.ws.send(json.dumps(unsubscribe_msg))
        self.subscriptions.discard(f"{channel}:{ticker}")
        logger.info(f"Unsubscribed from {channel}: {ticker}")
    
    def on_orderbook(self, callback: Callable[[Dict[str, Any]], None]):
        """
        Register callback for orderbook updates.
        
        Args:
            callback: Function to call when orderbook update received
        """
        self.callbacks['orderbook'].append(callback)
    
    def on_trades(self, callback: Callable[[Dict[str, Any]], None]):
        """
        Register callback for trade updates.
        
        Args:
            callback: Function to call when trade received
        """
        self.callbacks['trades'].append(callback)
    
    def on_ticker(self, callback: Callable[[Dict[str, Any]], None]):
        """
        Register callback for ticker updates.
        
        Args:
            callback: Function to call when ticker update received
        """
        self.callbacks['ticker'].append(callback)
    
    def on_error(self, callback: Callable[[Exception], None]):
        """
        Register callback for error handling.
        
        Args:
            callback: Function to call when error occurs
        """
        self.callbacks['error'].append(callback)
    
    async def _handle_message(self, message: Dict[str, Any]):
        """
        Handle incoming WebSocket message.
        
        Args:
            message: Parsed message data
        """
        msg_type = message.get('type')
        channel = message.get('channel')
        
        if msg_type == 'error':
            error_msg = message.get('message', 'Unknown error')
            logger.error(f"WebSocket error: {error_msg}")
            for callback in self.callbacks['error']:
                try:
                    callback(Exception(error_msg))
                except Exception as e:
                    logger.error(f"Error in error callback: {e}")
        
        elif channel == 'orderbook':
            for callback in self.callbacks['orderbook']:
                try:
                    callback(message)
                except Exception as e:
                    logger.error(f"Error in orderbook callback: {e}")
        
        elif channel == 'trades':
            for callback in self.callbacks['trades']:
                try:
                    callback(message)
                except Exception as e:
                    logger.error(f"Error in trades callback: {e}")
        
        elif channel == 'ticker':
            for callback in self.callbacks['ticker']:
                try:
                    callback(message)
                except Exception as e:
                    logger.error(f"Error in ticker callback: {e}")
    
    async def listen(self):
        """
        Listen for incoming WebSocket messages.
        This should be run as a background task.
        """
        if not self.ws:
            raise RuntimeError("WebSocket not connected")
        
        try:
            while self.running:
                try:
                    message_str = await asyncio.wait_for(
                        self.ws.recv(),
                        timeout=30.0
                    )
                    message = json.loads(message_str)
                    await self._handle_message(message)
                
                except asyncio.TimeoutError:
                    # Send ping to keep connection alive
                    if self.ws:
                        await self.ws.ping()
                
                except websockets.exceptions.ConnectionClosed:
                    logger.warning("WebSocket connection closed")
                    break
                
                except Exception as e:
                    logger.error(f"Error processing message: {e}")
                    for callback in self.callbacks['error']:
                        try:
                            callback(e)
                        except Exception as cb_err:
                            logger.error(f"Error in error callback: {cb_err}")
        
        except Exception as e:
            logger.error(f"Fatal error in listen loop: {e}")
            raise
        
        finally:
            self.running = False
    
    async def run(self):
        """
        Connect and start listening for messages.
        Convenience method that combines connect() and listen().
        """
        await self.connect()
        await self.listen()
