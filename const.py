# /config/custom_components/lumentree/const.py
# Final version - Read 95 regs, no unavailable MQTT modes

from __future__ import annotations

import logging
from typing import Final

from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

DOMAIN: Final = "lumentree"
_LOGGER = logging.getLogger(__package__)


def get_timezone(hass: HomeAssistant):
    """Get the configured Home Assistant timezone (cached per-call but cheap)."""
    return dt_util.get_time_zone(hass.config.time_zone) or dt_util.get_default_time_zone()


# --- HTTP API Constants ---
BASE_URL: Final = "http://lesvr.suntcn.com"
URL_GET_SERVER_TIME: Final = "/lesvr/getServerTime"
URL_SHARE_DEVICES: Final = "/lesvr/shareDevices"
URL_DEVICE_MANAGE: Final = "/lesvr/deviceManage"
URL_GET_OTHER_DAY_DATA: Final = "/lesvr/getOtherDayData"
URL_GET_PV_DAY_DATA: Final = "/lesvr/getPVDayData"
URL_GET_BAT_DAY_DATA: Final = "/lesvr/getBatDayData"
URL_GET_YEAR_DATA: Final = "/lesvr/getYearData"
URL_GET_MONTH_DATA: Final = "/lesvr/getMonthData"

DEFAULT_HEADERS: Final = {
    "versionCode": "1.6.3",
    "platform": "2",
    "wifiStatus": "1",
    "User-Agent": "Mozilla/5.0 (Linux; Android 10; SM-G970F) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.120 Mobile Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
}

# --- MQTT Constants ---
MQTT_BROKER: Final = "lesvr.suntcn.com"
MQTT_PORT: Final = 1886
MQTT_USERNAME: Final = "appuser"
MQTT_PASSWORD: Final = "app666"
MQTT_KEEPALIVE: Final = 20
MQTT_SUB_TOPIC_FORMAT: Final = "reportApp/{device_sn}"
MQTT_PUB_TOPIC_FORMAT: Final = "listenApp/{device_sn}"
MQTT_CLIENT_ID_FORMAT: Final = "android-{device_id}-{timestamp}"

# --- Configuration Keys ---
CONF_DEVICE_ID: Final = "device_id"
CONF_DEVICE_SN: Final = "device_sn"
CONF_DEVICE_NAME: Final = "device_name"
CONF_HTTP_TOKEN: Final = "http_token"

# --- Polling and Timeout ---
DEFAULT_POLLING_INTERVAL = 5

# New intervals for statistics coordinators
DEFAULT_DAILY_INTERVAL: Final = 300  # 5 minutes (server updates every 5 minutes)
DEFAULT_MONTHLY_INTERVAL: Final = 300  # 5 minutes (to match daily update frequency)
DEFAULT_YEARLY_INTERVAL: Final = 300  # 5 minutes (to match daily update frequency)

# --- Savings / Tariffs ---
DEFAULT_TARIFF_VND_PER_KWH: Final = (
    2900  # Fixed tariff for savings calculation (2.9k/kWh - average for ~400 kWh/month)
)

# --- Dispatcher Signal ---
SIGNAL_UPDATE_FORMAT: Final = f"{DOMAIN}_mqtt_update_{{device_sn}}"
SIGNAL_STATS_UPDATE_FORMAT: Final = f"{DOMAIN}_stats_update_{{device_sn}}"

# --- Register Addresses (MQTT Real-time - Only registers within 0-94 range) ---
REG_ADDR = {
    "FIRMWARE_VERSION": 2,
    "DEVICE_MODEL_START": 3,
    "CONTROLLER_VERSION": 8,
    "BATTERY_VOLTAGE": 11,
    "BATTERY_CURRENT": 12,
    "AC_OUT_VOLTAGE": 13,
    "GRID_VOLTAGE": 15,
    "AC_OUT_FREQ": 16,
    "AC_IN_FREQ": 17,
    "AC_OUT_POWER": 18,
    "PV1_VOLTAGE": 20,
    "PV1_POWER": 22,
    "DEVICE_TEMP": 24,
    "BATTERY_TYPE": 37,
    "BATTERY_SOC": 50,
    "AC_IN_POWER": 53,
    "AC_OUT_VA": 58,
    "GRID_POWER": 59,
    "BATTERY_POWER": 61,
    "LOAD_POWER": 67,
    "UPS_MODE": 68,
    "MASTER_SLAVE_STATUS": 70,
    "PV2_VOLTAGE": 72,
    "PV2_POWER": 74,
    # Registers 100+ may only be available if device returns extra data
    "BATTERY_MODE": 100,
    "WORK_MODE": 150,
    # --- Extended range ---------------------------------------------------
    # Recovered from the LightEarth app's DeviceAddrConfig, which binds every
    # signal to one address per wire protocol (protocol_1 is the one this
    # integration speaks).  The address law is app_addr == 2 * register_index,
    # verified against the device serial number, which sits at register 3 in
    # every captured frame while the app binds it to address 6.
    #
    # A device is free to answer with fewer registers than were asked for: the
    # common 190-byte frame carries only indices 0..94, so everything at index
    # 95 and above reads None on those units rather than raising.
    #
    # Scale and signedness come from the app's formatter layer and were
    # cross-checked against captured frames -- see docs/api/REGISTER_MAP.md.
    "FW_VERSION_CONTROLLER_ADDR": 9,  # app addr 18; app renders this as a string
    "FW_VERSION_LCD": 10,  # app addr 20; app renders this as a string
    "SOLAR_SELL_GRAPH": 19,  # app addr 38; flag values only, not a measurement
    "TODAY_PV_INPUT": 33,  # app addr 66; raw/10, signed -> kWh
    "AC_IN_CURRENT": 54,  # app addr 108; raw/100, signed -> A
    "AC_OUT_CURRENT": 62,  # app addr 124; raw/100, signed -> A
    "GEN_INV_POWER": 82,  # app addr 164; raw watts, signed
    "DEVICE_IMAGE_FLAG": 94,  # app addr 188; selects the product image
    "AI_MODE": 96,  # app addr 192; 0/1/2
    "EQUALIZING_CHARGE_VOLTAGE": 101,  # app addr 202; raw/100 -> V
    "BOOST_CHARGE_VOLTAGE": 102,  # app addr 204; raw/100 -> V
    "FLOAT_CHARGE_VOLTAGE": 103,  # app addr 206; raw/100 -> V
    "BATTERY_CAPACITY": 104,  # app addr 208; raw -> Ah
    "BATTERY_MAX_CHARGE_CURRENT": 106,  # app addr 212; raw -> A
    "MAX_DISCHARGE_CURRENT": 107,  # app addr 214; raw -> A
    "LOW_CAPACITY_CUTOFF": 111,  # app addr 222; raw -> %
    "PROTECTING_RECOVERY_POINT": 112,  # app addr 224; raw -> %
    "BATTERY_LOW_VOLTAGE_PROTECTION": 114,  # app addr 228; raw/100 -> V
    "BATTERY_RECOVERY_VOLTAGE": 115,  # app addr 230; raw/100 -> V
    "CHARGE_FROM_AC": 120,  # app addr 240; 0/1
    "AC_OUT_FREQ_SET": 123,  # app addr 246; two options, values 0 and 2
    "AC_COUPLING": 124,  # app addr 248; 0/1
    "GRID_TYPE": 125,  # app addr 250; 0/2/4
    "CT_TRICKLE_FEED": 147,  # app addr 294; raw watts
    "EQUALIZING_CHARGE_INTERVAL": 148,  # app addr 296; raw days
    "EQUALIZING_CHARGE_TIME": 149,  # app addr 298; raw minutes
}
REG_ADDR_CELL_START: Final = 250
REG_ADDR_CELL_COUNT: Final = 50

# --- Entity Keys --- (Removed unavailable mode keys)
KEY_ONLINE_STATUS: Final = "online_status"
KEY_IS_UPS_MODE: Final = "is_ups_mode"
KEY_PV_POWER: Final = "pv_power"
KEY_BATTERY_POWER: Final = "battery_power"
KEY_BATTERY_SOC: Final = "battery_soc"
KEY_GRID_POWER: Final = "grid_power"
KEY_LOAD_POWER: Final = "load_power"
KEY_BATTERY_VOLTAGE: Final = "battery_voltage"
KEY_BATTERY_CURRENT: Final = "battery_current"
KEY_AC_OUT_VOLTAGE: Final = "ac_output_voltage"
KEY_GRID_VOLTAGE: Final = "grid_voltage"
KEY_AC_OUT_FREQ: Final = "ac_output_frequency"
KEY_AC_OUT_POWER: Final = "ac_output_power"
KEY_AC_OUT_VA: Final = "ac_output_va"
KEY_DEVICE_TEMP: Final = "device_temperature"
KEY_PV1_VOLTAGE: Final = "pv1_voltage"
KEY_PV1_POWER: Final = "pv1_power"
KEY_PV2_VOLTAGE: Final = "pv2_voltage"
KEY_PV2_POWER: Final = "pv2_power"
KEY_BATTERY_STATUS: Final = "battery_status"
KEY_GRID_STATUS: Final = "grid_status"
KEY_AC_IN_VOLTAGE: Final = "ac_input_voltage"
KEY_AC_IN_FREQ: Final = "ac_input_frequency"
KEY_AC_IN_POWER: Final = "ac_input_power"
KEY_BATTERY_TYPE: Final = "battery_type"
KEY_MASTER_SLAVE_STATUS: Final = "master_slave_status"
KEY_MQTT_DEVICE_SN: Final = "mqtt_device_sn"
KEY_BATTERY_CELL_INFO: Final = "battery_cell_info"
KEY_DAILY_PV_KWH: Final = "pv_today"
KEY_DAILY_CHARGE_KWH: Final = "charge_today"
KEY_DAILY_DISCHARGE_KWH: Final = "discharge_today"
KEY_DAILY_GRID_IN_KWH: Final = "grid_in_today"
KEY_DAILY_LOAD_KWH: Final = "load_today"
KEY_DAILY_TOTAL_LOAD_KWH: Final = "total_load_today"
KEY_TOTAL_LOAD_POWER: Final = "total_load_power"
KEY_LAST_RAW_MQTT: Final = "last_raw_mqtt_hex"

# --- Statistics Keys (Daily / Monthly / Yearly) ---
# Daily totals already defined above; extend with essential load
KEY_DAILY_ESSENTIAL_KWH: Final = "essential_today"
KEY_DAILY_SAVED_KWH: Final = "saved_today"
KEY_DAILY_SAVINGS_VND: Final = "savings_vnd_today"

# Monthly totals (current year, index 1..12) and yearly totals
KEY_MONTHLY_PV_KWH: Final = "pv_month"
KEY_MONTHLY_GRID_IN_KWH: Final = "grid_in_month"
KEY_MONTHLY_LOAD_KWH: Final = "load_month"
KEY_MONTHLY_ESSENTIAL_KWH: Final = "essential_month"
KEY_MONTHLY_TOTAL_LOAD_KWH: Final = "total_load_month"
KEY_MONTHLY_CHARGE_KWH: Final = "charge_month"
KEY_MONTHLY_DISCHARGE_KWH: Final = "discharge_month"
KEY_MONTHLY_SAVED_KWH: Final = "saved_month"
KEY_MONTHLY_SAVINGS_VND: Final = "savings_vnd_month"

KEY_YEARLY_PV_KWH: Final = "pv_year"
KEY_YEARLY_GRID_IN_KWH: Final = "grid_in_year"
KEY_YEARLY_LOAD_KWH: Final = "load_year"
KEY_YEARLY_ESSENTIAL_KWH: Final = "essential_year"
KEY_YEARLY_TOTAL_LOAD_KWH: Final = "total_load_year"
KEY_YEARLY_CHARGE_KWH: Final = "charge_year"
KEY_YEARLY_DISCHARGE_KWH: Final = "discharge_year"
KEY_YEARLY_SAVED_KWH: Final = "saved_year"
KEY_YEARLY_SAVINGS_VND: Final = "savings_vnd_year"

# Total (lifetime) sensors - from device start to now
KEY_TOTAL_PV_KWH: Final = "pv_total"
KEY_TOTAL_GRID_IN_KWH: Final = "grid_in_total"
KEY_TOTAL_LOAD_KWH: Final = "load_total"
KEY_TOTAL_ESSENTIAL_KWH: Final = "essential_total"
KEY_TOTAL_TOTAL_LOAD_KWH: Final = "total_load_total"
KEY_TOTAL_CHARGE_KWH: Final = "charge_total"
KEY_TOTAL_DISCHARGE_KWH: Final = "discharge_total"
KEY_TOTAL_SAVED_KWH: Final = "saved_total"
KEY_TOTAL_SAVINGS_VND: Final = "savings_vnd_total"

# Attribute names for series/metadata
ATTR_SERIES_5MIN_W: Final = "series_5min_w"
ATTR_SERIES_5MIN_KWH: Final = "series_5min_kwh"
ATTR_SERIES_HOUR_KWH: Final = "series_hour_kwh"
ATTR_DAILY_31_KWH: Final = "daily_31_kwh"
ATTR_MONTHLY_12_KWH: Final = "monthly_12_kwh"
ATTR_SOURCE_DATE: Final = "source_date"
ATTR_SUM_KWH: Final = "sum_kwh"

# Savings attribute keys
ATTR_TOTAL_USAGE_KWH: Final = "total_usage_kwh"
ATTR_GRID_USAGE_KWH: Final = "grid_usage_kwh"
ATTR_SAVED_KWH: Final = "saved_kwh"
ATTR_COST_WITHOUT_PV_VND: Final = "cost_without_pv_vnd"
ATTR_COST_WITH_PV_VND: Final = "cost_with_pv_vnd"
ATTR_SAVINGS_VND: Final = "savings_vnd"

KEY_SELF_CONSUMPTION_RATIO: Final = "self_consumption_ratio"
KEY_WORK_MODE: Final = "work_mode"
KEY_BATTERY_MODE: Final = "battery_mode"
KEY_FW_VERSION: Final = "fw_version"
KEY_CTRL_VERSION: Final = "ctrl_version"

# --- Extended real-time keys (see the extended block in REG_ADDR) ---
# The firmware cells at indices 9 and 10 are deliberately not published: the
# vendor app renders them as strings, so a numeric entity would report a wrong
# value.  See docs/api/REGISTER_MAP.md.
KEY_TODAY_PV_KWH: Final = "pv_today_kwh"  # distinct from the HTTP KEY_DAILY_PV_KWH
KEY_AC_IN_CURRENT: Final = "ac_input_current"
KEY_AC_OUT_CURRENT: Final = "ac_output_current"
KEY_GEN_INV_POWER: Final = "generator_power"
KEY_AI_MODE: Final = "ai_mode"
KEY_EQUALIZING_CHARGE_VOLTAGE: Final = "equalizing_charge_voltage"
KEY_BOOST_CHARGE_VOLTAGE: Final = "boost_charge_voltage"
KEY_FLOAT_CHARGE_VOLTAGE: Final = "float_charge_voltage"
KEY_BATTERY_CAPACITY: Final = "battery_capacity"
KEY_BATTERY_MAX_CHARGE_CURRENT: Final = "battery_max_charge_current"
KEY_MAX_DISCHARGE_CURRENT: Final = "max_discharge_current"
KEY_LOW_CAPACITY_CUTOFF: Final = "low_capacity_cutoff"
KEY_PROTECTING_RECOVERY_POINT: Final = "protecting_recovery_point"
KEY_BATTERY_LOW_VOLTAGE_PROTECTION: Final = "battery_low_voltage_protection"
KEY_BATTERY_RECOVERY_VOLTAGE: Final = "battery_recovery_voltage"
KEY_CHARGE_FROM_AC: Final = "charge_from_ac"
KEY_AC_OUT_FREQ_SET: Final = "ac_output_frequency_set"
KEY_AC_COUPLING: Final = "ac_coupling"
KEY_GRID_TYPE: Final = "grid_type"
KEY_CT_TRICKLE_FEED: Final = "ct_trickle_feed"
KEY_EQUALIZING_CHARGE_INTERVAL: Final = "equalizing_charge_interval"
KEY_EQUALIZING_CHARGE_TIME: Final = "equalizing_charge_time"

# --- Mappings for Modes ---

MAP_BATTERY_TYPE: Final = {2: "No Battery"}

MAP_WORK_MODE: Final = {
    0: "UPS Mode",
    1: "Save Money Mode",
    2: "Sell Mode",
    3: "Smart Meter Mode",
    4: "WIFI CT Mode",
    5: "MESH CT Mode",
}

MAP_BATTERY_MODE: Final = {
    0: "User Defined",
    1: "Special Battery Pack",
    2: "No Battery",
}

# Recovered from the app's device_detail_ai_mode_alert page, which lists the
# three choices in this order; 255 comes from the detail page's "no value"
# default.
MAP_AI_MODE: Final = {
    0: "Sunny",
    1: "Cloudy",
    2: "Rainy",
}

# The app's grid_type page offers three options with values 0, 2 and 4 and
# shows the terminal labels "220V" and "240V".  Only those two labels are
# recoverable from the disassembly; the remaining one is reported numerically
# rather than guessed.
MAP_GRID_TYPE: Final = {
    0: "220V",
    4: "240V",
}

# The app's ac_output_frequency_set page offers exactly two options, with
# values 0 and 2, and never states 50 or 60 as a literal anywhere.  Report the
# raw selection instead of inventing a Hz label.
MAP_AC_OUT_FREQ_SET: Final = {
    0: "Option 0",
    2: "Option 2",
}

MAP_ON_OFF: Final = {
    0: "Off",
    1: "On",
}
