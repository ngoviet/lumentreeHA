"""Pytest configuration and fixtures for Lumentree integration tests."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from homeassistant.components.lumentree import DOMAIN
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from custom_components.lumentree.const import (
    CONF_DEVICE_ID,
    CONF_DEVICE_SN,
    CONF_HTTP_TOKEN,
)


@pytest.fixture
def mock_hass() -> HomeAssistant:
    """Mock Home Assistant instance."""
    hass = MagicMock(spec=HomeAssistant)
    hass.data = {DOMAIN: {}}
    return hass


@pytest.fixture
def mock_config_entry() -> ConfigEntry:
    """Mock config entry."""
    entry = MagicMock(spec=ConfigEntry)
    entry.entry_id = "test_entry_id"
    entry.title = "Test Device"
    entry.data = {
        CONF_DEVICE_SN: "TEST123456",
        CONF_DEVICE_ID: "TEST123456",
        CONF_HTTP_TOKEN: "test_token_12345",
        "device_name": "Test Inverter",
    }
    entry.options = {}
    return entry


@pytest.fixture
def sample_mqtt_payload() -> str:
    """Sample MQTT payload hex string for testing."""
    # This is a simplified example - real payloads would be much longer
    # Format: slave_id + function_code + start_addr + count + data + crc
    return "01030100005f" + "00" * 190 + "abcd"  # 95 registers (190 bytes) + CRC


@pytest.fixture
def sample_stats_hex_streams() -> dict[str, str]:
    """Sample statistics hex streams (8 streams) for testing."""
    return {
        "pv": "01030100005f" + "00" * 190 + "abcd",
        "bat": "01030100005f" + "00" * 190 + "abcd",
        "grid": "01030100005f" + "00" * 190 + "abcd",
        "load": "01030100005f" + "00" * 190 + "abcd",
        "essential": "01030100005f" + "00" * 190 + "abcd",
        "charge": "01030100005f" + "00" * 190 + "abcd",
        "discharge": "01030100005f" + "00" * 190 + "abcd",
        "other": "01030100005f" + "00" * 190 + "abcd",
    }


@pytest.fixture
def mock_mqtt_client():
    """Mock MQTT client."""
    client = MagicMock()
    client.is_connected = True
    client._client_id = "test_client_id"
    client._topic_sub = "reportApp/TEST123456"
    client._topic_pub = "listenApp/TEST123456"
    client._reconnect_attempts = 0
    client._stopping = False
    client.connect = AsyncMock()
    client.disconnect = AsyncMock()
    client.async_request_data = AsyncMock()
    return client


@pytest.fixture
def mock_api_client():
    """Mock HTTP API client."""
    client = MagicMock()
    client.get_device_info = AsyncMock(
        return_value={
            "deviceId": "TEST123456",
            "deviceType": "SUNT-4.0KW-H",
            "controllerVersion": "1.0.0",
            "liquidCrystalVersion": "1.0.0",
        }
    )
    client.get_daily_stats = AsyncMock(return_value={})
    client.set_token = MagicMock()
    return client

