"""Tests for Kalshi REST client."""
import pytest
from unittest.mock import AsyncMock, Mock, patch, mock_open
from connectors.kalshi_rest import KalshiRestClient


@pytest.fixture
def mock_private_key():
    """Mock private key file."""
    key_content = b"""-----BEGIN RSA PRIVATE KEY-----
MIIEowIBAAKCAQEA1234567890
-----END RSA PRIVATE KEY-----"""
    return key_content


@pytest.fixture
def rest_client(mock_private_key):
    """Create a test REST client."""
    with patch('builtins.open', mock_open(read_data=mock_private_key)):
        with patch('connectors.kalshi_rest.serialization.load_pem_private_key') as mock_load:
            mock_load.return_value = Mock()
            client = KalshiRestClient(
                api_key="test_api_key",
                private_key_path="/fake/path/key.pem",
                base_url="https://api.test.com/v2"
            )
            return client


def test_client_initialization(rest_client):
    """Test client initializes with correct parameters."""
    assert rest_client.api_key == "test_api_key"
    assert rest_client.base_url == "https://api.test.com/v2"
    assert rest_client.private_key is not None


def test_sign_request(rest_client):
    """Test request signing."""
    with patch.object(rest_client.private_key, 'sign') as mock_sign:
        mock_sign.return_value = b'fake_signature'
        
        signature = rest_client._sign_request("GET", "/test", "")
        
        assert mock_sign.called
        assert isinstance(signature, str)


def test_get_headers(rest_client):
    """Test header generation."""
    with patch.object(rest_client, '_sign_request') as mock_sign:
        mock_sign.return_value = "fake_signature"
        
        headers = rest_client._get_headers("GET", "/test")
        
        assert 'Content-Type' in headers
        assert headers['X-KALSHI-API-KEY'] == "test_api_key"
        assert 'X-KALSHI-SIGNATURE' in headers
        assert 'X-KALSHI-TIMESTAMP' in headers


@pytest.mark.asyncio
async def test_place_order(rest_client):
    """Test placing an order."""
    mock_response = {
        "order_id": "12345",
        "ticker": "TEST-MARKET",
        "status": "placed"
    }
    
    # Mock the signing method to return bytes
    with patch.object(rest_client.private_key, 'sign', return_value=b'fake_signature'):
        # Create a proper mock for the request context manager
        mock_resp = AsyncMock()
        mock_resp.json = AsyncMock(return_value=mock_response)
        mock_resp.raise_for_status = Mock()
        
        mock_cm = AsyncMock()
        mock_cm.__aenter__.return_value = mock_resp
        mock_cm.__aexit__.return_value = None
        
        rest_client.session = AsyncMock()
        rest_client.session.request = Mock(return_value=mock_cm)
        
        order = await rest_client.place_order(
            ticker="TEST-MARKET",
            action="buy",
            side="yes",
            count=10,
            yes_price=50
        )
        
        assert order["order_id"] == "12345"
        assert order["ticker"] == "TEST-MARKET"


@pytest.mark.asyncio
async def test_cancel_order(rest_client):
    """Test canceling an order."""
    mock_response = {"status": "canceled"}
    
    # Mock the signing method to return bytes
    with patch.object(rest_client.private_key, 'sign', return_value=b'fake_signature'):
        # Create a proper mock for the request context manager
        mock_resp = AsyncMock()
        mock_resp.json = AsyncMock(return_value=mock_response)
        mock_resp.raise_for_status = Mock()
        
        mock_cm = AsyncMock()
        mock_cm.__aenter__.return_value = mock_resp
        mock_cm.__aexit__.return_value = None
        
        rest_client.session = AsyncMock()
        rest_client.session.request = Mock(return_value=mock_cm)
        
        result = await rest_client.cancel_order("12345")
        
        assert result["status"] == "canceled"


@pytest.mark.asyncio
async def test_list_orders(rest_client):
    """Test listing orders."""
    mock_response = {
        "orders": [
            {"order_id": "1", "ticker": "TEST-1"},
            {"order_id": "2", "ticker": "TEST-2"}
        ]
    }
    
    # Mock the signing method to return bytes
    with patch.object(rest_client.private_key, 'sign', return_value=b'fake_signature'):
        # Create a proper mock for the request context manager
        mock_resp = AsyncMock()
        mock_resp.json = AsyncMock(return_value=mock_response)
        mock_resp.raise_for_status = Mock()
        
        mock_cm = AsyncMock()
        mock_cm.__aenter__.return_value = mock_resp
        mock_cm.__aexit__.return_value = None
        
        rest_client.session = AsyncMock()
        rest_client.session.request = Mock(return_value=mock_cm)
        
        orders = await rest_client.list_orders(status="open")
        
        assert len(orders) == 2
        assert orders[0]["order_id"] == "1"


@pytest.mark.asyncio
async def test_context_manager():
    """Test client works as context manager."""
    with patch('builtins.open', mock_open(read_data=b"fake_key")):
        with patch('connectors.kalshi_rest.serialization.load_pem_private_key'):
            client = KalshiRestClient(
                api_key="test",
                private_key_path="/fake/path"
            )
            
            async with client as c:
                assert c.session is not None
            
            # Session should be closed after exit
            assert client.session is None or client.session.closed
