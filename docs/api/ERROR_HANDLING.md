# Error Handling Guide

## Exception Types

### AuthException
- **Raised when**: Authentication fails or token is missing
- **Common causes**:
  - Token expired (after ~10 minutes)
  - Invalid device ID
  - Missing Authorization header
- **Handling**: Re-authenticate and retry

### ApiException
- **Raised when**: API request fails (non-auth errors)
- **Common causes**:
  - Network errors
  - Server errors (500, 503, etc.)
  - Invalid parameters
  - Rate limiting
- **Handling**: Retry with exponential backoff

## Retry Strategy

### Configuration
```python
API_MAX_RETRIES = 3
API_RETRY_BASE_DELAY = 1.0  # Start with 1 second
API_RETRY_MAX_DELAY = 10.0  # Cap at 10 seconds
```

### Retry Logic
1. **Network errors** (connection, timeout): Retry with exponential backoff
2. **Auth errors** (998): Re-authenticate first, then retry
3. **Server errors** (5xx): Retry with exponential backoff
4. **Client errors** (4xx): Don't retry (except 401/403 which may need re-auth)

### Exponential Backoff
```python
delay = min(API_RETRY_BASE_DELAY * (2 ** attempt), API_RETRY_MAX_DELAY)
await asyncio.sleep(delay)
```

## Common Error Scenarios

### 1. Token Expired
**Symptoms**:
- `returnValue: 998` in API response
- `AuthException` raised

**Solution**:
```python
# Re-authenticate
server_time = await api_client.get_server_time()
token = await api_client.share_devices(device_id, server_time)
api_client.set_token(token)
# Retry original request
```

### 2. Network Timeout
**Symptoms**:
- `asyncio.TimeoutError`
- `ClientTimeout` exception

**Solution**:
- Increase timeout (default: 30 seconds)
- Retry with exponential backoff
- Check network connectivity

### 3. Invalid Parameters
**Symptoms**:
- `returnValue: 0` or other error code
- Empty or malformed response

**Solution**:
- Validate parameters before API call
- Check device ID format
- Verify date format (YYYY-MM-DD)

### 4. Historical Data Not Available
**Symptoms**:
- API returns current data regardless of year/month parameter
- `getYearData`/`getMonthData` only work for current period

**Solution**:
- Use daily API for historical data
- Check cache first before API call
- Implement smart backfill from daily data

## Error Handling Patterns

### Pattern 1: API Request with Retry
```python
async def fetch_with_retry(api_client, endpoint, params, max_retries=3):
    for attempt in range(max_retries):
        try:
            return await api_client._request("GET", endpoint, params=params)
        except (ClientConnectorError, ServerConnectionError, asyncio.TimeoutError) as e:
            if attempt == max_retries - 1:
                raise
            delay = min(1.0 * (2 ** attempt), 10.0)
            await asyncio.sleep(delay)
        except AuthException:
            # Re-authenticate
            await api_client.authenticate(device_id)
            # Retry once more
            if attempt < max_retries - 1:
                continue
            raise
```

### Pattern 2: Graceful Degradation
```python
async def get_data_with_fallback(api_client, device_id, date):
    try:
        # Try API first
        return await api_client.get_daily_stats(device_id, date)
    except ApiException:
        # Fallback to cache
        cache_data = cache_io.load_day(device_id, date)
        if cache_data:
            return cache_data
        # Fallback to default/empty data
        return get_empty_data()
```

### Pattern 3: Data Validation
```python
def validate_api_response(response):
    """Validate API response structure."""
    if not isinstance(response, dict):
        raise ApiException("Invalid response format")
    
    return_value = response.get("returnValue")
    if return_value != 1:
        if return_value == 998:
            raise AuthException("Authentication failed")
        raise ApiException(f"API error: {return_value}")
    
    data = response.get("data")
    if not isinstance(data, dict):
        raise ApiException("Missing data in response")
    
    return data
```

## Logging Errors

### Error Logging Levels
- **DEBUG**: Detailed request/response information
- **INFO**: Normal operation, successful requests
- **WARNING**: Recoverable errors, fallbacks used
- **ERROR**: Critical errors, exceptions

### Logging Pattern
```python
try:
    result = await api_client.get_data(device_id)
except AuthException as e:
    _LOGGER.warning(f"Auth failed for {device_id}: {e}. Re-authenticating...")
    await api_client.authenticate(device_id)
except ApiException as e:
    _LOGGER.error(f"API error for {device_id}: {e}")
    raise
except Exception as e:
    _LOGGER.exception(f"Unexpected error for {device_id}: {e}")
    raise
```

## Best Practices

1. **Always handle exceptions**: Don't let exceptions bubble up unhandled
2. **Use specific exception types**: Catch `AuthException` and `ApiException` separately
3. **Implement retries**: For transient errors (network, timeout)
4. **Log errors properly**: Include context (device_id, date, etc.)
5. **Validate responses**: Check `returnValue` and data structure
6. **Use fallbacks**: Cache, default values, or previous data
7. **Monitor error rates**: Track failures to detect issues early
8. **Don't retry on client errors**: 4xx errors usually indicate invalid input

## Testing Error Handling

### Test Cases
1. **Token expiration**: Force token expiry, verify re-auth
2. **Network timeout**: Simulate slow network
3. **Server errors**: Mock 500/503 responses
4. **Invalid parameters**: Test with invalid device_id/date
5. **Empty responses**: Handle missing data gracefully

### Mocking
```python
# Mock network error
async def test_network_error():
    with patch('aiohttp.ClientSession.get') as mock_get:
        mock_get.side_effect = ClientConnectorError(...)
        # Test retry logic
```


