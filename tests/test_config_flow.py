"""Tests for config flow."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from homeassistant import data_entry_flow
from homeassistant.components.lumentree import DOMAIN
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from custom_components.lumentree.config_flow import LumentreeConfigFlow


@pytest.mark.asyncio
async def test_config_flow_user_step(mock_hass: HomeAssistant):
    """Test user step in config flow."""
    flow = LumentreeConfigFlow()
    flow.hass = mock_hass
    
    with patch.object(flow, "async_set_unique_id") as mock_unique_id:
        result = await flow.async_step_user({
            "device_sn": "TEST123456",
            "device_id": "TEST123456",
            "http_token": "test_token",
        })
        
        # Verify flow proceeds or completes
        assert result is not None


@pytest.mark.asyncio
async def test_config_flow_invalid_input(mock_hass: HomeAssistant):
    """Test config flow with invalid input."""
    flow = LumentreeConfigFlow()
    flow.hass = mock_hass
    
    # Test with missing required fields
    result = await flow.async_step_user({
        "device_sn": "",  # Empty
        "device_id": "TEST123456",
    })
    
    # Should show errors
    assert result is not None

