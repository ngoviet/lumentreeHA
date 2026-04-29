"""Common utilities for Lumentree integration."""

from __future__ import annotations

from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo

from .const import DOMAIN


def build_device_info(
    device_sn: str,
    device_name: str,
    device_api_info: dict[str, Any] | None = None,
) -> DeviceInfo:
    """Build DeviceInfo object for a Lumentree device.

    Shared between sensor and binary_sensor platforms.
    """
    if device_api_info is None:
        device_api_info = {}
    return DeviceInfo(
        identifiers={(DOMAIN, device_sn)},
        name=device_name,
        manufacturer="YS Tech (YiShen)",
        model=device_api_info.get("deviceType"),
        sw_version=device_api_info.get("controllerVersion"),
        hw_version=device_api_info.get("liquidCrystalVersion"),
    )
