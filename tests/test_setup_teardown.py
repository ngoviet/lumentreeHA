"""Tests for setup and teardown of Lumentree integration."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from homeassistant.components.lumentree import DOMAIN
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady

from custom_components.lumentree import async_setup_entry, async_unload_entry
from custom_components.lumentree.core.api_client import LumentreeHttpApiClient
from custom_components.lumentree.core.mqtt_client import LumentreeMqttClient


@pytest.mark.asyncio
async def test_setup_entry_success(mock_hass: HomeAssistant, mock_config_entry: ConfigEntry):
    """Test successful setup of integration."""
    with patch("custom_components.lumentree.async_get_clientsession") as mock_session, \
         patch.object(LumentreeHttpApiClient, "get_device_info", new_callable=AsyncMock) as mock_get_info, \
         patch.object(LumentreeMqttClient, "connect", new_callable=AsyncMock) as mock_connect, \
         patch("custom_components.lumentree.hass.config_entries.async_forward_entry_setups") as mock_forward:
        
        mock_get_info.return_value = {
            "deviceId": "TEST123456",
            "deviceType": "SUNT-4.0KW-H",
            "controllerVersion": "1.0.0",
        }
        mock_forward.return_value = True
        
        result = await async_setup_entry(mock_hass, mock_config_entry)
        
        assert result is True
        assert mock_config_entry.entry_id in mock_hass.data[DOMAIN]
        mock_connect.assert_called_once()
        mock_get_info.assert_called_once()


@pytest.mark.asyncio
async def test_setup_entry_api_error(mock_hass: HomeAssistant, mock_config_entry: ConfigEntry):
    """Test setup failure when API returns error."""
    with patch("custom_components.lumentree.async_get_clientsession"), \
         patch.object(LumentreeHttpApiClient, "get_device_info", new_callable=AsyncMock) as mock_get_info:
        
        mock_get_info.return_value = {"_error": "Device not found"}
        
        with pytest.raises(ConfigEntryNotReady):
            await async_setup_entry(mock_hass, mock_config_entry)


@pytest.mark.asyncio
async def test_unload_entry_success(mock_hass: HomeAssistant, mock_config_entry: ConfigEntry, mock_mqtt_client):
    """Test successful unload of integration."""
    # Setup entry data
    mock_hass.data[DOMAIN][mock_config_entry.entry_id] = {
        "mqtt_client": mock_mqtt_client,
        "remove_nightly": MagicMock(),
    }
    
    with patch("custom_components.lumentree.hass.config_entries.async_unload_platforms") as mock_unload_platforms:
        mock_unload_platforms.return_value = True
        
        result = await async_unload_entry(mock_hass, mock_config_entry)
        
        assert result is True
        mock_mqtt_client.disconnect.assert_called_once()
        assert mock_config_entry.entry_id not in mock_hass.data.get(DOMAIN, {})


@pytest.mark.asyncio
async def test_unload_entry_no_data(mock_hass: HomeAssistant, mock_config_entry: ConfigEntry):
    """Test unload when entry data is missing."""
    with patch("custom_components.lumentree.hass.config_entries.async_unload_platforms") as mock_unload_platforms:
        mock_unload_platforms.return_value = True
        
        result = await async_unload_entry(mock_hass, mock_config_entry)
        
        assert result is True

