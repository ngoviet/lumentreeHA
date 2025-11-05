# Hướng dẫn test API bằng Postman - Lấy tableValue từ Server gốc

## API Endpoint để lấy tableValue

### 1. PV Data (Sản lượng điện mặt trời) - GET tableValue
**API Endpoint:**
```
GET http://lesvr.suntcn.com/lesvr/getPVDayData
```

**Query Parameters:**
- `deviceId`: `H240909079` (bắt buộc)
- `queryDate`: `2025-11-01` (bắt buộc, format: YYYY-MM-DD)

**Response chứa `tableValue`:**
```json
{
  "returnValue": 1,
  "data": {
    "pv": {
      "tableValue": 29,        // <-- Đây là giá trị bạn cần (đơn vị: 0.1 kWh)
      "tableValueInfo": [...]  // Mảng 288 giá trị W (5 phút/lần)
    }
  }
}
```

**Giải thích `tableValue`:**
- Là tổng sản lượng PV trong ngày từ server gốc
- Đơn vị: **0.1 kWh** (nên phải chia 10)
- Ví dụ: `tableValue: 29` → `29 / 10 = 2.9 kWh`
- Đây là giá trị tổng do server tính sẵn (có thể không chính xác bằng tổng từ `tableValueInfo`)

### 2. Battery Data (Pin) - GET tableValue
**API Endpoint:**
```
GET http://lesvr.suntcn.com/lesvr/getBatDayData
```

**Query Parameters:**
- `deviceId`: `H240909079`
- `queryDate`: `2025-11-01`

**Response chứa `tableValue`:**
```json
{
  "returnValue": 1,
  "data": {
    "bats": [
      {
        "tableValue": 3,        // Charge (đơn vị: 0.1 kWh)
        "tableValueInfo": [...]
      },
      {
        "tableValue": 0,        // Discharge (đơn vị: 0.1 kWh)
        "tableValueInfo": [...]
      }
    ],
    "tableValueInfo": [...]     // Signed power series (dương = charge, âm = discharge)
  }
}
```

### 3. Other Data (Grid, Load, Essential) - GET tableValue
**API Endpoint:**
```
GET http://lesvr.suntcn.com/lesvr/getOtherDayData
```

**Query Parameters:**
- `deviceId`: `H240909079`
- `queryDate`: `2025-11-01`

**Response chứa `tableValue`:**
```json
{
  "returnValue": 1,
  "data": {
    "grid": {
      "tableValue": 75,        // Grid input (đơn vị: 0.1 kWh)
      "tableValueInfo": [...]
    },
    "homeload": {
      "tableValue": 20,         // Home load (đơn vị: 0.1 kWh)
      "tableValueInfo": [...]
    },
    "essentialLoad": {
      "tableValue": 66,         // Essential load (đơn vị: 0.1 kWh)
      "tableValueInfo": [...]
    }
  }
}
```

## Headers cần thiết

Thêm các headers sau vào Postman request:

| Header Name | Value |
|------------|-------|
| `versionCode` | `1.6.3` |
| `platform` | `2` |
| `wifiStatus` | `1` |
| `User-Agent` | `Mozilla/5.0 (Linux; Android 10; SM-G970F) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.120 Mobile Safari/537.36` |
| `Accept` | `application/json, text/plain, */*` |
| `Accept-Language` | `en-US,en;q=0.9` |
| `Authorization` | `f040282806fa4830b5fdd677f8056d28` (token hiện tại) |

## Cách lấy Token từ Home Assistant

### Option 1: Từ Home Assistant Developer Tools
1. Vào Home Assistant → Developer Tools → States
2. Tìm entity: `sensor.lumentree_config` hoặc tương tự
3. Xem trong attributes có `http_token`

### Option 2: Từ file config (PowerShell)
```powershell
cd "\\192.168.10.15\config\.storage"
$json = Get-Content "core.config_entries" -Raw | ConvertFrom-Json
$lumentree = $json.data.entries | Where-Object { $_.domain -eq "lumentree" } | Select-Object -First 1
$lumentree.data.http_token
```

Token hiện tại: `f040282806fa4830b5fdd677f8056d28`

### Option 3: Từ Home Assistant API
```bash
GET http://192.168.10.15:8123/api/config/config_entries/entry/<entry_id>
Authorization: Bearer <HA_LONG_LIVED_ACCESS_TOKEN>
```

Trong response, tìm `data.http_token`

## Cấu trúc Response đầy đủ từ Server gốc

### Tất cả các API đều trả về format tương tự:
```json
{
  "returnValue": 1,              // 1 = thành công, khác 1 = lỗi
  "msg": "success",              // Thông báo (nếu có lỗi)
  "data": {
    // ... các object chứa tableValue và tableValueInfo
  }
}
```

### Chi tiết về `tableValue`:
- **Vị trí**: Trong `data.pv.tableValue`, `data.bats[].tableValue`, `data.grid.tableValue`, etc.
- **Đơn vị**: **0.1 kWh** (phải chia 10 để có kWh)
- **Ý nghĩa**: Tổng giá trị trong ngày do server tính sẵn
- **Ví dụ**: 
  - `tableValue: 29` → `29 / 10 = 2.9 kWh`
  - `tableValue: 75` → `75 / 10 = 7.5 kWh`

### Chi tiết về `tableValueInfo`:
- **Vị trí**: Trong `data.pv.tableValueInfo`, `data.tableValueInfo` (battery), etc.
- **Đơn vị**: **W (Watts)** - công suất tại thời điểm đó
- **Số lượng**: 288 giá trị (24 giờ × 12 bước/giờ = 288)
- **Khoảng thời gian**: Mỗi 5 phút một giá trị
- **Tính tổng**: Sum(W values) × (5 phút / 60) / 1000 = kWh
- **Độ chính xác**: Thường chính xác hơn `tableValue` vì tính từ dữ liệu chi tiết

## Cấu hình Postman

### Step 1: Tạo Request mới
1. Click **New** → **HTTP Request**
2. Chọn method: **GET**

### Step 2: Nhập URL
```
http://lesvr.suntcn.com/lesvr/getPVDayData
```

### Step 3: Thêm Query Parameters
Vào tab **Params**, thêm:
- Key: `deviceId`, Value: `H240909079`
- Key: `queryDate`, Value: `2025-11-01`

### Step 4: Thêm Headers
Vào tab **Headers**, thêm tất cả headers như bảng trên.

### Step 5: Thêm Token
Copy token: `f040282806fa4830b5fdd677f8056d28` và paste vào header `Authorization`.

### Step 6: Send Request
Click **Send** và xem response.

## So sánh tableValue vs tableValueInfo

Sau khi test API, bạn sẽ thấy 2 cách lấy tổng:

### 1. Từ `tableValue` (Server tính sẵn):
```
tableValue = 29
Daily total = 29 / 10 = 2.9 kWh
```
- ✅ Nhanh, server tính sẵn
- ❌ Có thể không chính xác bằng cách 2

### 2. Từ `tableValueInfo` (Tính từ dữ liệu chi tiết):
```
tableValueInfo = [100, 150, 200, ...] // 288 values (W)
Tổng W = sum([100, 150, 200, ...])
Daily total = Tổng W × (5/60) / 1000 = kWh
```
- ✅ Chính xác hơn (tính từ 288 điểm dữ liệu)
- ❌ Cần tính toán thêm

### Kết luận:
Nếu 2 giá trị khác nhau → Dùng `tableValueInfo` (như code đã fix)
Nếu 2 giá trị giống nhau → Có thể dùng `tableValue` (đơn giản hơn)

## Ví dụ Response

```json
{
  "returnValue": 1,
  "data": {
    "pv": {
      "tableValue": 29,
      "tableValueInfo": [100, 150, 200, 180, ...] // 288 values
    }
  }
}
```

Tính toán:
- `tableValue`: `29 / 10 = 2.9 kWh` ✅ (đúng theo bạn nói)
- Tổng từ `tableValueInfo`: Sum(W values) * (5/60) / 1000 = kWh

Nếu `tableValueInfo` tổng = 2.9 kWh → Code fix đúng, chỉ cần re-fetch cache.

---

# API lấy thông tin cả tháng từ Server gốc

## ⚠️ Lưu ý quan trọng:

**Server Lumentree KHÔNG có API endpoint riêng để lấy data theo tháng/năm.**

Hiện tại chỉ có các endpoint cho **daily data**:
- `/lesvr/getPVDayData`
- `/lesvr/getBatDayData`
- `/lesvr/getOtherDayData`

## Cách lấy thông tin cả tháng:

### Phương án 1: Gọi API daily cho từng ngày trong tháng

**Ví dụ lấy tháng 11/2025:**
```
Ngày 1: GET /lesvr/getPVDayData?deviceId=H240909079&queryDate=2025-11-01
Ngày 2: GET /lesvr/getPVDayData?deviceId=H240909079&queryDate=2025-11-02
...
Ngày 30: GET /lesvr/getPVDayData?deviceId=H240909079&queryDate=2025-11-30
```

**Sau đó tổng hợp:**
- Tổng `tableValue` của 30 ngày = tổng tháng
- Hoặc tổng `tableValueInfo` của 30 ngày = tổng tháng (chính xác hơn)

### Phương án 2: Kiểm tra API response có monthData không

Theo memory, API response **CÓ THỂ** chứa `monthData` và `yearData` trong response:

**Cấu trúc response có thể có:**
```json
{
  "returnValue": 1,
  "data": {
    "pv": {
      "tableValue": 29,
      "tableValueInfo": [...],
      "monthData": [29, 30, 31, ...],  // ← 31 ngày trong tháng (nếu có)
      "yearData": [890, 920, 950, ...]  // ← 12 tháng trong năm (nếu có)
    }
  }
}
```

**⚠️ Cần test thực tế để xác nhận!**

### Cách test:

1. Gọi API daily cho 1 ngày bất kỳ:
   ```
   GET http://lesvr.suntcn.com/lesvr/getPVDayData?deviceId=H240909079&queryDate=2025-11-01
   ```

2. Kiểm tra response có chứa `monthData` hoặc `yearData` không:
   - Nếu có → Dùng trực tiếp `monthData` và `yearData`
   - Nếu không → Dùng Phương án 1 (gọi từng ngày)

## Tóm tắt:

| Cách | Ưu điểm | Nhược điểm |
|------|---------|------------|
| **API daily từng ngày** | Đảm bảo có data | Chậm (30 requests/tháng) |
| **monthData/yearData (nếu có)** | Nhanh, 1 request | Chưa xác nhận có trong API |

**Khuyến nghị:** Test API response trước để xác nhận có `monthData/yearData`, nếu không thì dùng phương án gọi từng ngày.

