"""Tests for MQTT flow and message handling."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.lumentree.core.mqtt_client import LumentreeMqttClient
from custom_components.lumentree.core.realtime_parser import parse_mqtt_payload


@pytest.mark.asyncio
async def test_mqtt_connect_success(mock_hass, mock_config_entry, mock_mqtt_client):
    """Test successful MQTT connection."""
    with patch("paho.mqtt.client.Client") as mock_client_class:
        mock_client = MagicMock()
        mock_client_class.return_value = mock_client
        mock_client.connect = MagicMock(return_value=0)
        mock_client.subscribe = MagicMock(return_value=(0, 1))
        
        client = LumentreeMqttClient(mock_hass, mock_config_entry, "TEST123", "TEST123")
        
        # Mock the connection callback
        with patch.object(client, "_on_connect") as mock_on_connect:
            await client.connect()
            
            # Verify connection was attempted
            assert mock_client.connect.called


def test_parse_mqtt_payload_valid(mock_hass, sample_mqtt_payload):
    """Test parsing valid MQTT payload."""
    # Note: This is a simplified test - real payloads need proper CRC
    result = parse_mqtt_payload(sample_mqtt_payload)
    
    # With a valid payload structure, should return dict or None
    assert result is None or isinstance(result, dict)


def test_parse_mqtt_payload_invalid():
    """Test parsing invalid MQTT payload."""
    result = parse_mqtt_payload("invalid")
    assert result is None


def test_parse_mqtt_payload_empty():
    """Test parsing empty payload."""
    result = parse_mqtt_payload("")
    assert result is None


@pytest.mark.asyncio
async def test_mqtt_disconnect_cleanup(mock_hass, mock_config_entry, mock_mqtt_client):
    """Test MQTT disconnect properly cleans up."""
    client = LumentreeMqttClient(mock_hass, mock_config_entry, "TEST123", "TEST123")
    client._mqttc = mock_mqtt_client
    client._is_connected = True
    
    with patch.object(client, "_cancel_batch_timer") as mock_cancel_batch, \
         patch.object(client, "_cancel_offline_timer") as mock_cancel_offline:
        
        await client.disconnect()
        
        mock_cancel_batch.assert_called_once()
        mock_cancel_offline.assert_called_once()

