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

### Daily Data APIs

#### Get PV Day Data
- **Endpoint**: `/lesvr/getPVDayData`
- **Method**: `GET`
- **Auth**: Required (Authorization header)
- **Params**:
  - `deviceId: {device_sn}`
  - `queryDate: {YYYY-MM-DD}` (optional, defaults to today)
- **Response**: 
  - `tableValue`: Total daily value (in 0.1 kWh units)
  - `tableValueInfo`: Array of 288 values (5-minute intervals, 24h × 12 points/hour)

#### Get Battery Day Data
- **Endpoint**: `/lesvr/getBatDayData`
- **Method**: `GET`
- **Auth**: Required
- **Params**: Same as PV Day Data
- **Response**:
  - Battery arrays with charge/discharge data
  - `tableValueInfo`: Signed power series (positive = charge, negative = discharge)

#### Get Other Day Data
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
  "returnValue": 998,  // Auth error
  "message": "Authentication failed"
}
```

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
- `returnValue: 998` → Authentication error
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
   - Re-authenticate on 998 errors

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


