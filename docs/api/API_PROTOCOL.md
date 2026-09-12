# Lumentree API Protocol Documentation

## Base Configuration

- **Base URL**: `http://lesvr.suntcn.com`
- **Version Code**: `1.6.3`
- **Platform**: `2`
- **Device Type**: `1`
- **Timeout**: 30 seconds (default)

## Authentication Flow

### 1. Get Server Time
- **Endpoint**: `/lesvr/getServerTime`
- **Method**: `GET`
- **Headers**: Required headers (versionCode, deviceType, platform)
- **Response**: Contains `serverTime` and `token`

### 2. Share Devices (Get Token)
- **Endpoint**: `/lesvr/shareDevices`
- **Method**: `POST`
- **Headers**: 
  - `versionCode: 1.6.3`
  - `deviceType: 1`
  - `platform: 2`
  - `source: 2`
  - `Content-Type: application/x-www-form-urlencoded`
- **Body**:
  - `deviceIds: {device_sn}` (e.g., `YOUR_DEVICE_ID`)
  - `serverTime: {serverTime_from_step_1}`
- **Response**: Token in `data.token`
- **Token Expiration**: 10 minutes (cached)

## API Endpoints

> **Endpoint status:** `getAllDayData` is the integration's primary daily path — one
> request returns PV, battery, load and grid for a day. The three per-metric
> endpoints below are its **fallback** and still answer identically. See the
> [endpoint survey](API_ENDPOINTS_DISCOVERED.md) for their legacy status.

### Daily Data APIs

#### Get All Day Data (primary)
- **Endpoint**: `/lesvr/getAllDayData`
- **Method**: `GET`
- **Auth**: Required (`Authorization` header — see the note on 998 below)
- **Params**: `deviceId`, `queryDate` (`yyyy-MM-dd`)
- **Response**: one `data` object carrying every metric — `pv`, `bat` (charge),
  `batF` (discharge), `homeload`, `essentialLoad`, `grid` — each with its own
  `tableValue` / `tableValueInfo` (288 points), plus a `titleParams` array
  listing the same metrics with their display names.
- **Caveat**: `batF` is **omitted entirely** when there was no discharge, where
  `getBatDayData` returns an explicit zero. The client normalises this (charge
  present + `batF` absent ⇒ 0 kWh discharge) so the two sources stay
  interchangeable for callers.
- **Path note**: the APK contains `lesvr/v2/getAllDayData` because app 3.2.4
  targets a different host (`lesvrjm.suntcn.com`), where `v2/` is correct.
  Against `lesvr.suntcn.com` the `v2/` form answers `998` (does not exist) and
  this un-prefixed form answers `1`. An earlier version of this document had
  that backwards.
- **Used by**: [core/api_client.py](../../core/api_client.py) `get_all_day_data()`,
  which `get_daily_stats()` calls first.

#### Get PV Day Data (fallback)
- **Endpoint**: `/lesvr/getPVDayData`
- **Method**: `GET`
- **Auth**: Required (Authorization header)
- **Params**:
  - `deviceId: {device_sn}`
  - `queryDate: {YYYY-MM-DD}` (optional, defaults to today)
- **Response**: 
  - `tableValue`: Total daily value (in 0.1 kWh units)
  - `tableValueInfo`: Array of 288 values (5-minute intervals, 24h × 12 points/hour)

#### Get Battery Day Data (fallback)
- **Endpoint**: `/lesvr/getBatDayData`
- **Method**: `GET`
- **Auth**: Required
- **Params**: Same as PV Day Data
- **Response Structure**:
```json
{
  "returnValue": 1,
  "data": {
    "bats": [
      {
        "tableValue": 290  // Charge total (0.1 kWh units) → 29.0 kWh
      },
      {
        "tableValue": 150  // Discharge total (0.1 kWh units) → 15.0 kWh
      }
    ],
    "tableValueInfo": [
      // 288 values (24 hours × 12 points/hour, 5-minute intervals)
      // Signed power series in Watt (W)
      // NOTE: the sign convention here is the API's, which is REVERSED relative
      // to the labeling the device presents: positive (+) = Discharge,
      // negative (-) = Charge. See core/api_client.py::_fetch_battery_data,
      // which inverts the series before publishing. Do not restate this as
      // "positive = charge".
      500, 500, 450,    // API-positive → discharge
      -200, -300, -400, // API-negative → charge
      0, 0, 0,          // Không hoạt động
      ...
    ]
  }
}
```
- **Note**: 
  - `bats[0]` = Charge total
  - `bats[1]` = Discharge total
  - `tableValueInfo`: Signed power series — see the sign convention note in the sample response above

#### Get Other Day Data (fallback)
- **Endpoint**: `/lesvr/getOtherDayData`
- **Method**: `GET`
- **Auth**: Required
- **Params**: Same as PV Day Data
- **Response**: Load, essential load, grid import/export data

### Monthly Data API

#### Get Month Data
- **Endpoint**: `/lesvr/getMonthData`
- **Method**: `GET`
- **Auth**: Required
- **Params**:
  - `deviceId: {device_sn}`
  - `month: {YYYY-MM}` (e.g., `2025-11`)
  - **Note**: May only accept current month, not historical months
- **Response**:
  - Data for 31 days in the month
  - Multiple metrics: PV, grid, load, battery, etc.

### Yearly Data API

#### Get Year Data
- **Endpoint**: `/lesvr/getYearData`
- **Method**: `GET`
- **Auth**: Required
- **Params**:
  - `deviceId: {device_sn}`
  - `year: {YYYY}` (e.g., `2025`)
  - **Note**: May only accept current year, not historical years
- **Response**:
  - Data for 12 months in the year
  - Multiple metrics: PV, grid, load, battery, etc.

## Response Format

### Success Response
```json
{
  "returnValue": 1,
  "data": {
    "pv": {
      "tableValue": 24791,  // Total (in 0.1 kWh units)
      "tableValueInfo": [2217, 1423, ...]  // Array of values
    },
    "grid": { ... },
    "homeload": { ... },
    "essentialLoad": { ... },
    "bat": { ... },      // Battery charge
    "batF": { ... }      // Battery discharge
  }
}
```

### Error Response
```json
{
  "returnValue": 998,
  "msg": "您访问对页面不存在"
}
```

`998` is a catch-all 404 — the endpoint does not exist. It is **not** an
authentication error. See
[`API_ENDPOINTS_DISCOVERED.md`](API_ENDPOINTS_DISCOVERED.md#11-returnvalue-998--không-tồn-tại-không-phải-cần-auth)
for the probe evidence.

## Data Units

- **Daily totals**: `tableValue` in 0.1 kWh units (divide by 10.0 to get kWh)
- **5-minute series**: `tableValueInfo` array values in 0.1 kWh units
- **Power values**: Convert to Watt by: `(value * 0.1) / (5/60) * 1000` = W
- **Simplified**: `value * 120` for 5-minute kWh → W conversion

## Headers

### Default Headers
```python
{
    "versionCode": "1.6.3",
    "platform": "2",
    "deviceType": "1",
    "wifiStatus": "1",
    "User-Agent": "Mozilla/5.0 (Linux; Android 10; SM-G970F) AppleWebKit/537.36",
    "Accept": "application/json, text/plain, */*"
}
```

### Authentication Header
```python
{
    "Authorization": "{token_from_shareDevices}"
}
```

## Error Handling

### Return Values
- `returnValue: 1` → Success
- `returnValue: 203` → Missing or insufficient permission (auth)
- `returnValue: 998` → Endpoint does not exist (catch-all 404)
- `returnValue: 0` → Other error

### Network Errors
- **Connection errors**: Retry with exponential backoff
- **Timeout**: 30 seconds default
- **Max retries**: 3 attempts

### Retry Strategy
```python
API_MAX_RETRIES = 3
API_RETRY_BASE_DELAY = 1.0  # Start with 1 second
API_RETRY_MAX_DELAY = 10.0  # Cap at 10 seconds
```

## Important Notes

1. **Historical Data Limitation**: 
   - `getYearData` and `getMonthData` may only accept current year/month
   - Historical data should be fetched via daily API or from cache

2. **Token Management**:
   - Tokens expire after ~10 minutes
   - Cache tokens to avoid frequent re-authentication
   - Re-authenticate on `203` (missing/insufficient permission) errors

3. **Data Caching**:
   - API responses should be cached locally
   - Use cache for historical data instead of repeated API calls
   - Daily API is more reliable for historical data than monthly/yearly APIs

4. **Rate Limiting**:
   - Unknown rate limits, but implement reasonable delays between requests
   - Use async/await for concurrent requests when possible

## API Client Implementation

See `custom_components/lumentree/core/api_client.py` for full implementation:
- `LumentreeHttpApiClient` class
- `_request()` method with retry logic
- `get_daily_stats()` method
- `get_month_data()` method
- `get_year_data()` method


