# /config/custom_components/lumentree/const.py
# Final version - Read 95 regs, no unavailable MQTT modes

import logging
from typing import Final

DOMAIN: Final = "lumentree"
_LOGGER = logging.getLogger(__package__)

# --- HTTP API Constants ---
BASE_URL: Final = "http://lesvr.suntcn.com"
URL_GET_SERVER_TIME: Final = "/lesvr/getServerTime"
URL_SHARE_DEVICES: Final = "/lesvr/shareDevices"
URL_DEVICE_MANAGE: Final = "/lesvr/deviceManage"
URL_GET_OTHER_DAY_DATA: Final = "/lesvr/getOtherDayData"
URL_GET_PV_DAY_DATA: Final = "/lesvr/getPVDayData"
URL_GET_BAT_DAY_DATA: Final = "/lesvr/getBatDayData"

DEFAULT_HEADERS: Final = {
    "versionCode": "1.6.3",
    "platform": "2",
    "wifiStatus": "1",
    "User-Agent": "Mozilla/5.0 (Linux; Android 10; SM-G970F) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.120 Mobile Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9"
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
DEFAULT_STATS_INTERVAL = 600 # 10 minutes

# New intervals for statistics coordinators
DEFAULT_DAILY_INTERVAL: Final = 600        # 10 minutes
DEFAULT_MONTHLY_INTERVAL: Final = 10800    # 3 hours (configurable 2–6h)
DEFAULT_YEARLY_INTERVAL: Final = 86400     # 24 hours

# --- Savings / Tariffs ---
DEFAULT_TARIFF_VND_PER_KWH: Final = 3000   # Fixed tariff for savings calculation

# --- Backfill Constants ---
BACKFILL_BASE_DELAY: Final = 0.2          # Base delay between API calls (seconds)
BACKFILL_MAX_DELAY: Final = 5.0           # Maximum delay cap for exponential backoff (seconds)
EMPTY_DATA_THRESHOLD: Final = 1e-6        # Threshold to consider data empty (kWh)
MAX_DAYS_PER_YEAR: Final = 366            # Maximum days per year (including leap year)
MAX_YEARS_FOR_TOTAL: Final = 10          # Maximum years to scan for lifetime totals

# --- Data Processing Constants ---
HOURS_PER_DAY: Final = 24                 # Hours in a day
STEPS_PER_HOUR: Final = 12                # 5-minute steps per hour (60/5 = 12)
MONTHS_PER_YEAR: Final = 12               # Months in a year
MINUTES_PER_STEP: Final = 5               # Minutes per 5-minute interval
RESP_TEXT_TRUNCATE_LEN: Final = 300       # Response text truncate length for logging

# --- Dispatcher Signal ---
SIGNAL_UPDATE_FORMAT: Final = f"{DOMAIN}_mqtt_update_{{device_sn}}"
SIGNAL_STATS_UPDATE_FORMAT: Final = f"{DOMAIN}_stats_update_{{device_sn}}"

# --- Register Addresses (MQTT Real-time - Only registers within 0-94 range) ---
REG_ADDR = {
    "DEVICE_MODEL_START": 3,
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
KEY_TOTAL_LOAD_POWER: Final = "total_load_power"
KEY_LAST_RAW_MQTT: Final = "last_raw_mqtt_hex"

# --- Statistics Keys (Daily / Monthly / Yearly) ---
# Daily totals already defined above; extend with essential load
KEY_DAILY_ESSENTIAL_KWH: Final = "essential_today"

# Monthly totals (current year, index 1..12) and yearly totals
KEY_MONTHLY_PV_KWH: Final = "pv_month"
KEY_MONTHLY_GRID_IN_KWH: Final = "grid_in_month"
KEY_MONTHLY_LOAD_KWH: Final = "load_month"
KEY_MONTHLY_ESSENTIAL_KWH: Final = "essential_month"
KEY_MONTHLY_CHARGE_KWH: Final = "charge_month"
KEY_MONTHLY_DISCHARGE_KWH: Final = "discharge_month"

KEY_YEARLY_PV_KWH: Final = "pv_year"
KEY_YEARLY_GRID_IN_KWH: Final = "grid_in_year"
KEY_YEARLY_LOAD_KWH: Final = "load_year"
KEY_YEARLY_ESSENTIAL_KWH: Final = "essential_year"
KEY_YEARLY_CHARGE_KWH: Final = "charge_year"
KEY_YEARLY_DISCHARGE_KWH: Final = "discharge_year"

# Total (lifetime) sensors - from device start to now
KEY_TOTAL_PV_KWH: Final = "pv_total"
KEY_TOTAL_GRID_IN_KWH: Final = "grid_in_total"
KEY_TOTAL_LOAD_KWH: Final = "load_total"
KEY_TOTAL_ESSENTIAL_KWH: Final = "essential_total"
KEY_TOTAL_CHARGE_KWH: Final = "charge_total"
KEY_TOTAL_DISCHARGE_KWH: Final = "discharge_total"

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

# --- Mappings for Modes ---

MAP_BATTERY_TYPE: Final = {2: "No Battery"}

