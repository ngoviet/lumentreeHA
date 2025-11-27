"""Diagnostics support for Lumentree integration."""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import DOMAIN, CONF_HTTP_TOKEN, CONF_DEVICE_SN, CONF_DEVICE_ID
from .core.mqtt_client import LumentreeMqttClient

TO_REDACT = {CONF_HTTP_TOKEN, "token", "password", "secret"}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    device_sn = entry.data.get(CONF_DEVICE_SN, "unknown")
    device_id = entry.data.get(CONF_DEVICE_ID, device_sn)
    
    # Get entry data
    entry_data = hass.data.get(DOMAIN, {}).get(entry.entry_id, {})
    
    # Redact sensitive data from entry
    redacted_entry_data = async_redact_data(entry.data, TO_REDACT)
    
    diagnostics_data: dict[str, Any] = {
        "entry": {
            "entry_id": entry.entry_id,
            "title": entry.title,
            "data": redacted_entry_data,
            "options": entry.options,
        },
        "version": "4.0.3",  # From manifest.json
        "device": {
            "device_sn": device_sn,
            "device_id": device_id,
        },
    }
    
    # MQTT client status
    mqtt_client = entry_data.get("mqtt_client")
    if isinstance(mqtt_client, LumentreeMqttClient):
        diagnostics_data["mqtt"] = {
            "connected": mqtt_client.is_connected,
            "client_id": mqtt_client._client_id if hasattr(mqtt_client, "_client_id") else None,
            "topic_sub": mqtt_client._topic_sub if hasattr(mqtt_client, "_topic_sub") else None,
            "topic_pub": mqtt_client._topic_pub if hasattr(mqtt_client, "_topic_pub") else None,
            "reconnect_attempts": getattr(mqtt_client, "_reconnect_attempts", 0),
            "stopping": getattr(mqtt_client, "_stopping", False),
        }
    else:
        diagnostics_data["mqtt"] = {"status": "not_initialized"}
    
    # Device API info (redact sensitive data)
    device_api_info = entry_data.get("device_api_info", {})
    if device_api_info:
        redacted_api_info = async_redact_data(device_api_info, TO_REDACT)
        diagnostics_data["device_api_info"] = redacted_api_info
    
    # Coordinator status
    coordinators_status = {}
    for coord_key in ["daily_coordinator", "monthly_coordinator", "yearly_coordinator", "total_coordinator"]:
        coord = entry_data.get(coord_key)
        if coord:
            coord_status = {
                "last_update_success": getattr(coord, "last_update_success", None),
                "last_update_time": str(getattr(coord, "last_update_time", None)) if hasattr(coord, "last_update_time") else None,
            }
            if hasattr(coord, "update_interval"):
                coord_status["update_interval"] = str(coord.update_interval)
            coordinators_status[coord_key] = coord_status
        else:
            coordinators_status[coord_key] = {"status": "not_available"}
    
    diagnostics_data["coordinators"] = coordinators_status
    
    # Aggregator status (if available)
    aggregator = entry_data.get("aggregator")
    if aggregator:
        diagnostics_data["aggregator"] = {
            "status": "initialized",
            "device_id": getattr(aggregator, "device_id", None),
        }
    else:
        diagnostics_data["aggregator"] = {"status": "not_available"}
    
    return diagnostics_data

