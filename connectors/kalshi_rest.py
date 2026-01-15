"""
Kalshi REST API connector with RSA-PSS signing for authentication.
Supports placing, canceling, and listing orders.
"""
import base64
import json
import time
from typing import Dict, List, Optional, Any
from pathlib import Path

import aiohttp
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.backends import default_backend


class KalshiRestClient:
    """REST API client for Kalshi trading platform."""
    
    def __init__(
        self,
        api_key: str,
        private_key_path: str,
        base_url: str = "https://api.elections.kalshi.com/trade-api/v2"
    ):
        """
        Initialize Kalshi REST client.
        
        Args:
            api_key: Kalshi API key
            private_key_path: Path to RSA private key file (PEM format)
            base_url: Kalshi API base URL
        """
        self.api_key = api_key
        self.base_url = base_url.rstrip('/')
        self.session: Optional[aiohttp.ClientSession] = None
        
        # Load private key for signing
        with open(private_key_path, 'rb') as key_file:
            self.private_key = serialization.load_pem_private_key(
                key_file.read(),
                password=None,
                backend=default_backend()
            )
    
    async def __aenter__(self):
        """Context manager entry."""
        self.session = aiohttp.ClientSession()
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        if self.session:
            await self.session.close()
    
    def _sign_request(self, method: str, path: str, body: str = "") -> str:
        """
        Sign request using RSA-PSS signature scheme.
        
        Args:
            method: HTTP method (GET, POST, etc.)
            path: API endpoint path
            body: Request body as string
            
        Returns:
            Base64-encoded signature
        """
        timestamp = str(int(time.time() * 1000))
        
        # Create message to sign: timestamp + method + path + body
        message = f"{timestamp}{method}{path}{body}"
        
        # Sign with RSA-PSS
        signature = self.private_key.sign(
            message.encode('utf-8'),
            padding.PSS(
                mgf=padding.MGF1(hashes.SHA256()),
                salt_length=padding.PSS.MAX_LENGTH
            ),
            hashes.SHA256()
        )
        
        # Return base64-encoded signature
        return base64.b64encode(signature).decode('utf-8')
    
    def _get_headers(self, method: str, path: str, body: str = "") -> Dict[str, str]:
        """
        Get headers for authenticated request.
        
        Args:
            method: HTTP method
            path: API endpoint path
            body: Request body as string
            
        Returns:
            Headers dictionary
        """
        timestamp = str(int(time.time() * 1000))
        signature = self._sign_request(method, path, body)
        
        return {
            'Content-Type': 'application/json',
            'X-KALSHI-API-KEY': self.api_key,
            'X-KALSHI-SIGNATURE': signature,
            'X-KALSHI-TIMESTAMP': timestamp
        }
    
    async def _request(
        self,
        method: str,
        path: str,
        params: Optional[Dict] = None,
        json_data: Optional[Dict] = None
    ) -> Dict[str, Any]:
        """
        Make authenticated API request.
        
        Args:
            method: HTTP method
            path: API endpoint path
            params: Query parameters
            json_data: JSON request body
            
        Returns:
            Response data
        """
        if not self.session:
            raise RuntimeError("Client session not initialized. Use 'async with' context manager.")
        
        url = f"{self.base_url}{path}"
        body = json.dumps(json_data) if json_data else ""
        headers = self._get_headers(method, path, body)
        
        async with self.session.request(
            method,
            url,
            headers=headers,
            params=params,
            json=json_data
        ) as response:
            response.raise_for_status()
            return await response.json()
    
    async def place_order(
        self,
        ticker: str,
        action: str,
        side: str,
        count: int,
        type: str = "limit",
        yes_price: Optional[int] = None,
        no_price: Optional[int] = None,
        expiration_ts: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        Place a new order.
        
        Args:
            ticker: Market ticker symbol
            action: 'buy' or 'sell'
            side: 'yes' or 'no'
            count: Number of contracts
            type: Order type ('limit' or 'market')
            yes_price: Limit price for yes side (cents)
            no_price: Limit price for no side (cents)
            expiration_ts: Order expiration timestamp
            
        Returns:
            Order response data
        """
        order_data = {
            "ticker": ticker,
            "action": action,
            "side": side,
            "count": count,
            "type": type
        }
        
        if yes_price is not None:
            order_data["yes_price"] = yes_price
        if no_price is not None:
            order_data["no_price"] = no_price
        if expiration_ts is not None:
            order_data["expiration_ts"] = expiration_ts
        
        return await self._request("POST", "/orders", json_data=order_data)
    
    async def cancel_order(self, order_id: str) -> Dict[str, Any]:
        """
        Cancel an existing order.
        
        Args:
            order_id: Order ID to cancel
            
        Returns:
            Cancellation response
        """
        return await self._request("DELETE", f"/orders/{order_id}")
    
    async def get_order(self, order_id: str) -> Dict[str, Any]:
        """
        Get details of a specific order.
        
        Args:
            order_id: Order ID
            
        Returns:
            Order details
        """
        return await self._request("GET", f"/orders/{order_id}")
    
    async def list_orders(
        self,
        ticker: Optional[str] = None,
        status: Optional[str] = None,
        limit: int = 100
    ) -> List[Dict[str, Any]]:
        """
        List orders with optional filters.
        
        Args:
            ticker: Filter by ticker symbol
            status: Filter by order status ('open', 'filled', 'canceled')
            limit: Maximum number of orders to return
            
        Returns:
            List of orders
        """
        params = {"limit": limit}
        if ticker:
            params["ticker"] = ticker
        if status:
            params["status"] = status
        
        response = await self._request("GET", "/orders", params=params)
        return response.get("orders", [])
    
    async def get_market(self, ticker: str) -> Dict[str, Any]:
        """
        Get market information.
        
        Args:
            ticker: Market ticker symbol
            
        Returns:
            Market details
        """
        return await self._request("GET", f"/markets/{ticker}")
    
    async def list_markets(
        self,
        event_ticker: Optional[str] = None,
        status: Optional[str] = None,
        limit: int = 100
    ) -> List[Dict[str, Any]]:
        """
        List available markets.
        
        Args:
            event_ticker: Filter by event ticker
            status: Filter by market status
            limit: Maximum number of markets to return
            
        Returns:
            List of markets
        """
        params = {"limit": limit}
        if event_ticker:
            params["event_ticker"] = event_ticker
        if status:
            params["status"] = status
        
        response = await self._request("GET", "/markets", params=params)
        return response.get("markets", [])
    
    async def get_portfolio(self) -> Dict[str, Any]:
        """
        Get current portfolio positions.
        
        Returns:
            Portfolio data
        """
        return await self._request("GET", "/portfolio")
    
    async def get_balance(self) -> Dict[str, Any]:
        """
        Get account balance.
        
        Returns:
            Balance information
        """
        return await self._request("GET", "/balance")
