# Hướng dẫn Test 2 API mới trong Postman

## 2 API đã khám phá:

### 1. `/lesvr/getYearData` - Lấy dữ liệu theo năm (12 tháng)
### 2. `/lesvr/getMonthData` - Lấy dữ liệu theo tháng (31 ngày)

---

## Bước 1: Lấy Server Time và Token

### API 1: Get Server Time
**Method:** `GET`  
**URL:** `http://lesvr.suntcn.com/lesvr/getServerTime`

**Headers:**
```
versionCode: 1.6.3
deviceType: 1
platform: 2
```

**Response:** Lưu lại `serverTime` và `token` từ response

---

### API 2: Share Devices (Lấy Token)
**Method:** `POST`  
**URL:** `http://lesvr.suntcn.com/lesvr/shareDevices`

**Headers:**
```
versionCode: 1.6.3
deviceType: 1
platform: 2
source: 2
Content-Type: application/x-www-form-urlencoded
```

**Body (form-data hoặc x-www-form-urlencoded):**
```
deviceIds: YOUR_DEVICE_ID
serverTime: <serverTime_từ_bước_1>
```

**Response:** Lưu lại `token` từ `data.token` (dùng cho các request sau)

**Lưu ý:** Bạn cần biết `deviceId` trước (ví dụ: `YOUR_DEVICE_ID`). Nếu không biết, có thể dùng account/password để lấy danh sách devices.

---

## Bước 2: Test API getYearData

### API: Get Year Data
**Method:** `GET`  
**URL:** `http://lesvr.suntcn.com/lesvr/getYearData`

**Headers:**
```
versionCode: 1.6.3
deviceType: 1
platform: 2
Authorization: <token_từ_bước_2>
```

**Query Parameters:**
```
deviceId: YOUR_DEVICE_ID
year: 2025
```

**Response Format:**
```json
{
  "returnValue": 1,
  "data": {
    "pv": {
      "tableValue": 24791,  // Tổng năm (0.1 kWh)
      "tableValueInfo": [2217, 1423, 2376, 2357, 3117, 3156, 3495, 3503, 3602, 3088, 119, 0]  // 12 tháng (0.1 kWh)
    },
    "grid": {
      "tableValue": 12406,
      "tableValueInfo": [1228, 1609, 1516, 1372, 1212, 1648, 1314, 716, 802, 1418, 443, 0]
    },
    "homeload": {
      "tableValue": 27694,
      "tableValueInfo": [2787, 2572, 3311, 3184, 3699, 2940, 2339, 2066, 1598, 1588, 150, 0]
    },
    "essentialLoad": {
      "tableValue": ...,
      "tableValueInfo": [...]
    },
    "bat": {  // Battery charge
      "tableValue": ...,
      "tableValueInfo": [...]
    },
    "batF": {  // Battery discharge
      "tableValue": ...,
      "tableValueInfo": [...]
    }
  }
}
```

**Lưu ý:**
- Giá trị trong `tableValueInfo` là **0.1 kWh** (cần chia 10 để ra kWh)
- Ví dụ: `2217` = `221.7 kWh`
- Array có 12 phần tử (1 cho mỗi tháng từ tháng 1-12)

---

## Bước 3: Test API getMonthData

### API: Get Month Data
**Method:** `GET`  
**URL:** `http://lesvr.suntcn.com/lesvr/getMonthData`

**Headers:**
```
versionCode: 1.6.3
deviceType: 1
platform: 2
Authorization: <token_từ_bước_2>
```

**Query Parameters:**
```
deviceId: YOUR_DEVICE_ID
year: 2025
month: 11
```

**Response Format:**
```json
{
  "returnValue": 1,
  "data": {
    "pv": {
      "tableValue": 119,  // Tổng tháng (0.1 kWh)
      "tableValueInfo": [0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 11.4, ...]  // 31 ngày (0.1 kWh)
    },
    "grid": {
      "tableValue": 443,
      "tableValueInfo": [0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 44.3, ...]
    },
    "homeload": {
      "tableValue": 150,
      "tableValueInfo": [0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 15.0, ...]
    },
    "essentialLoad": {
      "tableValue": ...,
      "tableValueInfo": [...]
    },
    "bat": {  // Battery charge
      "tableValue": ...,
      "tableValueInfo": [...]
    }
  }
}
```

**Lưu ý:**
- Giá trị trong `tableValueInfo` là **0.1 kWh** (cần chia 10 để ra kWh)
- Array có tối đa 31 phần tử (1 cho mỗi ngày trong tháng)
- Ngày không có data sẽ là `0`

---

## Mapping Keys:

| API Key | Entity Key | Mô tả |
|---------|-----------|-------|
| `pv` | `pv` | PV Generation |
| `grid` | `grid_in` | Grid Input |
| `homeload` | `load` | AC Out / Load |
| `essentialLoad` | `essential` | Hòa lưới / Essential Load |
| `bat` | `charge` | Battery Charge |
| `batF` | `discharge` | Battery Discharge |

---

## Ví dụ Postman Collection:

### Request 1: Get Server Time
```
GET http://lesvr.suntcn.com/lesvr/getServerTime
Headers:
  versionCode: 1.6.3
  deviceType: 1
  platform: 2
```

### Request 2: Share Devices (Lấy Token)
```
POST http://lesvr.suntcn.com/lesvr/shareDevices
Headers:
  versionCode: 1.6.3
  deviceType: 1
  platform: 2
  source: 2
  Content-Type: application/x-www-form-urlencoded
Body (form-data):
  deviceIds: YOUR_DEVICE_ID
  serverTime: {{serverTime}}
```

### Request 3: Get Year Data
```
GET http://lesvr.suntcn.com/lesvr/getYearData?deviceId=YOUR_DEVICE_ID&year=2025
Headers:
  versionCode: 1.6.3
  deviceType: 1
  platform: 2
  Authorization: {{token}}
```

### Request 4: Get Month Data
```
GET http://lesvr.suntcn.com/lesvr/getMonthData?deviceId=YOUR_DEVICE_ID&year=2025&month=11
Headers:
  versionCode: 1.6.3
  deviceType: 1
  platform: 2
  Authorization: {{token}}
```

---

## ⚠️ QUAN TRỌNG: Kiểm tra tham số API

**CẦN TEST:** API có thể **KHÔNG sử dụng** tham số `year` và `month`!

### Test để xác nhận:
1. Gọi `getYearData` với `year=2024` và `year=2025`, so sánh kết quả
2. Gọi `getMonthData` với `month=9` và `month=11`, so sánh kết quả
3. Nếu kết quả giống nhau → API chỉ trả về năm/tháng **hiện tại**, bất kể tham số

### Chạy script test:
```bash
python test_api_params.py
```

Script sẽ:
- Test `getYearData` với nhiều năm khác nhau
- Test `getMonthData` với nhiều tháng khác nhau
- So sánh kết quả và cảnh báo nếu tham số không có tác dụng

### Nếu API không nhận tham số:
- **getYearData**: Chỉ trả về dữ liệu năm hiện tại
- **getMonthData**: Chỉ trả về dữ liệu tháng hiện tại
- **Giải pháp**: Cần dùng API khác hoặc lấy từ cache để lấy historical data

---

## Tips:

1. **Token có thời hạn:** Token từ `getServerTime` có thể hết hạn, nếu gặp lỗi auth thì gọi lại `getServerTime`
2. **Giá trị:** Nhớ chia 10 để chuyển từ 0.1 kWh sang kWh
3. **Tháng:** `month` là số từ 1-12 (1 = tháng 1, 12 = tháng 12)
4. **Năm:** `year` là số 4 chữ số (ví dụ: 2025)
5. **⚠️ Tham số có thể không hoạt động:** Test kỹ trước khi sử dụng cho historical data

---

## So sánh với API cũ:

| API cũ | API mới | Ưu điểm |
|--------|---------|---------|
| `getPVDayData` (từng ngày) | `getYearData` (12 tháng) | 1 request = 12 tháng, nhanh hơn |
| `getBatDayData` (từng ngày) | `getMonthData` (31 ngày) | 1 request = 1 tháng, nhanh hơn |
| Phải gọi nhiều API | Chỉ cần 2 API | Giảm số lượng request |

