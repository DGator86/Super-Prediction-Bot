"""Test configuration file for pytest."""
import pytest


@pytest.fixture(scope="session")
def event_loop_policy():
    """Set event loop policy for asyncio tests."""
    import asyncio
    return asyncio.get_event_loop_policy()
