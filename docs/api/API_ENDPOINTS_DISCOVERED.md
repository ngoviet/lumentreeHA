# API Discovery — LightEarth 3.2.4 vs. lumentreeHA 5.2.0

> **Trạng thái:** khảo sát (survey) + đính chính lần hai. Chưa implement sensor nào.
> **Phiên bản:** tài liệu này thuộc đợt 5.2.0; `manifest.json` vẫn ghi `5.1.3` cho tới khi release.
> **Nguồn:** `blutter` trên `libapp.so` (Dart 3.9.2, `light_earth` 3.2.4), `web_app.js` (admin console), EMQX exports, và probe read-only có kiểm soát.
> **Ngày:** 2026-09-12 (đính chính lần hai cùng ngày, xem mục 0)

Mục đích của tài liệu này là chốt **bản đồ API thật** trước khi mở rộng integration, và đính chính một số giả định sai đang tồn tại trong repo.

---

## 0. ĐÍNH CHÍNH LẦN HAI — probe đầu tiên gửi sai tên header auth

**Toàn bộ kết quả probe trong bản đầu của tài liệu này là không hợp lệ.** Lý do:

`tools/probe_tier1_readonly.py` gửi token trong header tên `token`:

```python
session.headers["token"] = token      # SAI
```

Nhưng [core/api_client.py](../../core/api_client.py) — code đang chạy thật — gửi `Authorization`:

```python
headers["Authorization"] = self._token
```

Vì header sai tên nên **không request nào thực sự được xác thực**. Những gì bản đầu ghi là `returnValue: 2` (dịch là *"服务器繁忙"* = "server bận") thực chất là **phản hồi của một caller chưa đăng nhập**. Bản đầu đã dựng hẳn một hàng trong bảng mã lỗi để giải thích mã `2`, và kết luận nhiều endpoint Tier-1 "không dùng được" — tất cả đều là hệ quả của lỗi này.

Bằng chứng đối chứng: chạy lại **cùng endpoint, cùng tham số, cùng ngày**, chỉ đổi tên header:

| Endpoint | Header `token` (sai) | Header `Authorization` (đúng) |
|----------|---------------------|------------------------------|
| `getMonthData` | `rv=2` | **`rv=1`**, `data` có `bat/homeload/pv/grid/essentialLoad/batF` |
| `getYearData` | `rv=2` | **`rv=1`**, cùng shape |
| `getHistoryYearData` | `rv=2` | **`rv=1`**, có thêm `firstYear` |
| `getDevice` | `rv=203` | **`rv=1`**, `data.devices` |
| `getUserDevice` | `rv=203` | **`rv=1`**, `data.notices/oldData/devices` |
| `userDeviceList` | `rv=203` | **`rv=1`**, `data.devices/errorNum/onlineNum/offlineNum` |
| `deviceInfo` | `rv=1` | `rv=1` (không đổi — endpoint này không cần auth) |

Kết quả hợp lệ nằm ở [`docs/probe_results_tier1_authed.json`](probe_results_tier1_authed.json). Lần chạy đầu tiên với header đúng — 8 probe, thu hẹp phạm vi để xác nhận nguyên nhân trước khi quét rộng — nằm ở [`docs/probe_results_tier1_corrected.json`](probe_results_tier1_corrected.json). File kết quả cũ [`docs/probe_results_tier1.json`](probe_results_tier1.json) được **giữ lại nhưng đã bị vô hiệu hoá** — nó là bằng chứng cho lỗi này, không phải dữ liệu để trích dẫn.

**Bài học phương pháp:** một probe trả `2`/`203` hàng loạt trên những endpoint mà integration gọi thành công mỗi ngày là dấu hiệu probe sai, không phải server hỏng. Khi mọi thứ đều fail, nghi ngờ harness trước.

---

## 1. Đính chính quan trọng

Ba điều dưới đây trái với giả định đang lưu hành trong repo và trong các lần khảo sát trước. Cần sửa nhận thức trước khi làm bất cứ điều gì khác.

### 1.1. `returnValue: 998` = "KHÔNG TỒN TẠI", không phải "cần auth"

Body thật của 998 là:

```json
{"returnValue": 998, "msg": "您访问对页面不存在"}
```

Dịch: *"trang bạn truy cập không tồn tại"*. Đây là **catch-all 404**.

Bằng chứng đối chiếu từ probe **có xác thực đúng**:

| Mã | Nghĩa thật | Ví dụ đã gặp |
|----|-----------|--------------|
| `1` | Thành công | `/lesvr/deviceInfo` → `{"masterStatus": 0}` |
| `2` | Endpoint thật nhưng request không được xử lý — thấy ở `getDT`, `getVersionInfo`, `checkUpdate` | `/lesvr/getDT` |
| `3` | Sai HTTP method | `/lesvr/checkUpdate` (POST → cần GET) |
| `203` | Sai quyền — tài khoản guest không đủ | `/lesvr/getUserInfo` |
| `210` | Thiếu quan hệ master/slave | `/lesvr/getMasterSlaveInfo` (device này không có slave) |
| `998` | **Không tồn tại** | `/lesvr/v2/getAllDayData`, `/lesvr/userLogin` |
| `20001` | Thiếu tham số | `shareDevices` thiếu `expiredTime` |

**Cảnh báo về mã `2`:** bản đầu của tài liệu này giải thích `2` là "server bận, thử lại sau" và dùng nó để loại nhiều endpoint. Giải thích đó **sai** — nó được rút ra từ probe chưa xác thực (xem mục 0). `2` vẫn chưa được giải mã đầy đủ; chỉ biết nó không phải "thành công" và không phải "không tồn tại".

**Hệ quả:** danh sách "endpoint 998" từ các lần khảo sát trước vẫn đúng ở kết luận (998 = không tồn tại), nhưng **danh sách endpoint bị loại vì `2`/`203` phải được xét lại** — nhiều khả năng chúng thật, chỉ chưa được gọi đúng.

### 1.2. `getServerTime` là legacy; `v2/getAllDayData` **không** phải đường đi đúng

Hai kết luận của bản đầu, cả hai đều cần chỉnh:

**a) `getServerTime` có 0 lần xuất hiện trong `libapp.so` 3.2.4 — nhưng nó vẫn là endpoint dùng được.** Integration gọi nó mỗi lần lấy token và chạy tốt. Đây là endpoint legacy còn sống, không phải endpoint chết.

**b) `v2/getAllDayData` trả `998` (không tồn tại) trên host hiện tại — kể cả khi đã xác thực đúng.** Endpoint gộp thật nằm ở **`/lesvr/getAllDayData`, KHÔNG có tiền tố `v2/`**:

```
/lesvr/v2/getAllDayData   → rv=998  (không tồn tại)
/lesvr/getAllDayData      → rv=1    ✅ data: bat, homeload, grid, pv, essentialLoad, titleParams
```

Tiền tố `v2/` xuất hiện trong `libapp.so` vì app 3.2.4 trỏ vào host **khác** (`lesvrjm.suntcn.com`). Trên host integration đang dùng, đường dẫn không có `v2/`. Bản đầu kết luận "muốn dùng endpoint gộp thì phải chuyển host" — **kết luận đó sai**; không cần chuyển host.

Các endpoint ngày khác (`getPVDayData`, `getBatDayData`, `getOtherDayData`) vẫn chạy. Phép đối chiếu ở mục 7.2 đo được `pv`, `grid`, `homeload`, `essentialLoad` **khớp nhau** trên cả hai đường; phần **pin thì chưa kiểm chứng được** (thiết bị test báo không có pin nên cả hai đường đều ra 0).


### 1.3. `iot_class: cloud_polling` ⇒ chỉ Tier 1

Integration khai báo `cloud_polling`. Do đó **mọi endpoint ghi (Tier 3) và mọi route distributor/admin (Tier 4) đều ngoài phạm vi vĩnh viễn**, kể cả khi chúng dễ implement.

---

## 2. Hạ tầng — có hai host, không phải một

| Host | Giao thức | Vai trò | Trong repo? |
|------|-----------|---------|-------------|
| `lesvr.suntcn.com` | **HTTP thuần** + MQTT `:1886` | Host integration đang dùng | ✅ `const.py:21,41` |
| `lesvrjm.suntcn.com` | **HTTPS** | Host app 3.2.4 dùng (`ServerApi` base URL) | ❌ chưa có |
| `lehtapi.suntcn.com` | HTTPS | API của web admin console | ❌ chưa có |
| `rsdown.suntcn.com` | HTTPS | CDN ảnh/tài liệu | ❌ (không cần) |

Bằng chứng: string duy nhất trong `asm/light_earth/communication/server_api.dart` là `"https://lesvrjm.suntcn.com/"`, dùng làm base URL cho mọi call.

**Đính chính (bản đầu viết sai ở đây):** bản đầu tuyên bố *"`lesvr/v2/getAllDayData` chỉ sống trên host mới"* và suy ra integration phải chuyển host. **Sai.** Endpoint gộp tồn tại trên **host cũ** ở đường dẫn `/lesvr/getAllDayData` — **không có `v2/`**. Tiền tố `v2/` chỉ đúng trên host `lesvrjm`. Integration **không cần đổi host và không cần cơ chế `sign`**.


---

## 3. Cơ chế ký request (chưa có trong integration)

`server_api.dart` định nghĩa `_header()` dựng header map như sau:

```
Authorization : <token>            # lấy qua shareDevices
sign          : MD5_UPPER( <nonce> + "<salt>" )
timestamp     : <epoch millis>
nonce         : <16 ký tự ngẫu nhiên [a-z0-9]>
```

Chuỗi ký ghép theo thứ tự đọc được từ assembly:

| Bước | Nguồn | Giá trị |
|------|-------|---------|
| `nonce` | `_randomAlnumString()` | random, alphabet `abcdefghijklmnopqrstuvwxyz0123456789` |
| `timestamp` | `DateTime.now()` → micros ÷ 1000 | epoch **milliseconds** |
| `<salt>` | hằng số | salt ký — giá trị thật không chép vào repo |

Cộng thêm `_decrypt` dùng một hằng số AES (`svr_aes`) và một key đi kèm; giá trị thật không chép vào repo (nghi vấn — xem mục 8).

**Trạng thái xác minh:** công thức trên **chưa được xác minh live**. Test trên `lesvrjm` trả `returnValue: 2` (*服务器繁忙* = "server bận"), tức server đã nhận và xử lý request nhưng không phân biệt được "sign đúng" với "sign sai" trong phản hồi. Host cũ không dùng cơ chế này.

---

## 4. Endpoint mới — phân tầng

### Tier 1 — Ứng viên implement (read-only, đã probe **có xác thực đúng**)

| Endpoint | Method | Kết quả | Payload thật |
|----------|--------|---------|--------------|
| `lesvr/getAllDayData` | GET | ✅ `1` | **Gộp cả ngày** — `pv`, `bat`, `batF`, `homeload`, `essentialLoad`, `grid`, `titleParams` |
| `lesvr/getHistoryYearData` | GET | ✅ `1` | Thêm `firstYear` so với `getYearData` |
| `lesvr/getMonthData` | GET | ✅ `1` | `deviceId`, `year`, `month` |
| `lesvr/getYearData` | GET | ✅ `1` | `deviceId`, `year` |
| `lesvr/getOnlineStatus` | GET | ✅ `1` | `{"onlineStatus": 0}` |
| `lesvr/deviceInfo` | GET | ✅ `1` | `{"masterStatus": 0}` |
| `lesvr/getDevice` | GET | ✅ `1` | `data.devices` |
| `lesvr/getUserDevice` | GET | ✅ `1` | `data.notices/oldData/devices` |
| `lesvr/userDeviceList` | GET | ✅ `1` | `data.devices/errorNum/onlineNum/offlineNum` |
| `lesvr/getVersion` | GET | ✅ `1` | 4 nhóm firmware: `controller`, `controller2`, `screen`, `liquidCrystal` |
| `app/getAppParam` | GET | ✅ `1` | `maxDiffData`, `userKeepTime`, `snParam`, `deviceTypeImg`, … |
| `device/getTypeList` | GET | ✅ `1` | `deviceTypes[]`: `SUNT-4.0kW-HP`, `SUNT-6.0kW-HT`, … |
| `lesvr/deviceTypeSettingList` | GET | ✅ `1` | Cần `blueTooth` + `version` |
| `lesvr/getMasterSlaveInfo` | GET | ⚠️ `210` | Device này không có slave — chưa kết luận được |
| `lesvr/getDT` | GET | ❌ `2` | Cần tham số đúng, chưa rõ |
| `lesvr/getVersionInfo` | GET | ❌ `2` | Chưa rõ |
| `lesvr/checkUpdate` | GET | ❌ `2` | Từng trả `3` (sai method) trên POST → endpoint thật |
| `lesvr/v2/getAllDayData` | GET | ❌ `998` | **Sai path** — đúng là `/lesvr/getAllDayData` |
| `lesvr/getUserInfo` | GET | ❌ `203` | Tài khoản guest không đủ quyền (không phải lỗi endpoint) |

**Giá trị cao nhất:** `/lesvr/getAllDayData` — gộp PV + battery + load + grid vào **một call duy nhất**, thay cho 3 call riêng (`getPVDayData` + `getBatDayData` + `getOtherDayData`) mà integration đang dùng. Phép đối chiếu ở mục 7.2 đo được `pv`, `grid`, `homeload`, `essentialLoad` **khớp nhau** trên cả hai đường; phần **pin thì chưa kiểm chứng được** (thiết bị test báo không có pin nên cả hai đường đều ra 0).


### Tier 2 — Cần đánh giá thêm

| Endpoint | Ghi chú |
|----------|---------|
| `lesvr/getDT` | Trả `2` — cần tham số đúng, chưa rõ |
| `lesvr/checkUpdate` | Trả `3` (wrong method) trên POST → **endpoint thật, cần GET** |
| `lesvr/getVersionInfo` | Trả `2` |
| `lesvr/getDeviceQuickList` | ⚠️ **KHÔNG phải dữ liệu telemetry** — xem mục 5 |
| `lesvr/permissionCheck` | Cần tài khoản thật |
| `lesvr/login` / `regist` | Cần credential — ngoài phạm vi integration |

### Tier 3 — WRITE. **Không bao giờ implement**

Các endpoint dưới đây thay đổi trạng thái thiết bị/tài khoản phía vendor. Tuyệt đối không gọi, kể cả để test:

`lesvr/delDevice`, `lesvr/delUser`, `lesvr/setRemarkName`, `lesvr/upSnAddress`, `lesvr/v2/bindDevice`, `lesvr/bindDeviceForDistributor`, `lesvr/addMasterSlaveRelation`, `lesvr/delSlaveRelation`, `device/sendMsg`

**Phát hiện đáng chú ý:** `lesvr/getDeviceQuickList` **nằm trong Tier 3 dù tên có vẻ read-only**. Payload thật là một **register map để GHI**:

```json
[{"id": 2, "registerAddress": 240, "registerHex": "20", "registerDesc": "20A电流"},
 {"id": 3, "registerAddress": 99,  "registerHex": "85", "registerDesc": "重启控制板"},
 {"id": 8, "registerAddress": 202, "registerHex": "0",  "registerDesc": "停机按钮"}]
```

`registerDesc` dịch ra là "dòng 20A", "**khởi động lại bảng điều khiển**", "**nút dừng máy**". Đây là bảng lệnh điều khiển thiết bị. **Integration chỉ đọc thì không được chạm vào.**

### Tier 4 — Distributor / admin, ngoài phạm vi

`addDistributorPermission`, `removeDistributorPermission`, `distributorPermissionSetting`, `adminCountryDevice`, `adminDeviceManage`, `adminSearchDevice`, `manageDevice`, `manageDeviceInfo`

### Factory QA — bỏ qua

`getAutoTestPdf`, `getReportAutoTestParam`

---

## 5. MQTT — phát hiện không thể lấy từ APK

Từ EMQX exports (`emqx_subscriptions.json` 13 MB / 100k dòng, `emqx_clients.json` 128 MB):

### 5.1. Sáu namespace, integration chỉ biết hai

| Namespace | Số subscription | Ai subscribe |
|-----------|----------------|--------------|
| `listenServer/{SN}` | 41,306 | thiết bị |
| `listenApp/{SN}` | 40,814 | app — **integration publish vào đây** |
| `listenWeb/{SN}` | 16,705 | web console |
| `reportApp/{SN}` | 1,145 | app — **integration subscribe ở đây** |
| `escalationDevice` | 20 | `javaEscala8604`, `device-upgrade-tool` |
| `reportServer/#` | 10 | `javaServer4413` (bridge phía server) |

Một SN thường subscribe đồng thời cả `listenApp` + `listenServer` + `listenWeb`.

### 5.2. Username MQTT — integration chỉ biết một

| Username | Số client | Ai |
|----------|-----------|-----|
| `wifiuser` | 96,992 | module WiFi trên thiết bị |
| *(masked — xem `const.py`)* | 1,649 | **integration đang dùng** |
| `iaapp25` | 1,339 | **app 3.2.4** — password đọc từ `mqtt.dart`, không chép vào repo |
| `admin` | 20 | server-side tooling |

Client ID của app có dạng `app_{epochMillis}_{random}`.

### 5.3. Fallback HTTP cho MQTT

`mqtt.dart` chứa endpoint `device/sendMsg` — app dùng làm đường dự phòng khi MQTT không kết nối được. Đây là **đường gửi lệnh xuống thiết bị** ⇒ Tier 3.

---

## 6. Web admin console (`lehtapi.suntcn.com`)

`web_app.js` (1 MB) chứa 74 route. Ứng viên read-only đáng chú ý:

| Route | Giá trị |
|-------|---------|
| `/manage/lesvr/getErrorLog` | **Ứng viên duy nhất cho lịch sử lỗi/cảnh báo** |
| `/manage/lesvr/getAllDayData`, `getAllDayPoint` | Chuỗi thời gian dạng điểm |
| `/manage/lesvr/getMonthPoint`, `getYearPoint`, `getHourAdd` | Tổng hợp |
| `/manage/lesvr/pvVoltage`, `batSoc` | Điện áp PV / SOC pin |
| `/manage/lesvr/moduleVersion`, `deviceVersionList` | Firmware |
| `/manage/lesvr/getDeviceTypeImg` | Ảnh theo model |
| `/manage/lesvr/queryOnlineSnByArea` | Tra cứu theo khu vực |
| `/manage/lesvr/getMasterSlaveInfo` | Master/slave |

**Đã probe (1 request, read-only).** `POST https://lehtapi.suntcn.com/manage/lesvr/getErrorLog`
với body rỗng trả:

```json
{"returnValue": 1000, "msg": "需要登录"}
```

Ghi chép thô: [`docs/probe_results_errorlog.json`](probe_results_errorlog.json).

`1000` = *"cần đăng nhập"* — **khác hẳn `998`**, nên endpoint có thật. Nhưng nó không
dùng được với credential mà integration đang có, vì hai lý do độc lập:

1. **Auth khác cơ chế.** Console này đăng nhập qua `POST /security/login` và giữ
   **cookie session** (`withCredentials: true` trong axios config của `web_app.js`).
   App token từ `shareDevices` chỉ hợp lệ với header `Authorization` trên
   `lesvr.suntcn.com`; không có đường nào để BIẾN nó thành cookie của console.
2. **Không có tài khoản.** Đây là khu `/manage/` của **dealer/distributor**. Repo
   không có — và không nên có — credential admin của vendor.

Bằng chứng cùng chiều từ phía app: quét `libapp.so` được **38** chuỗi `lesvr/*`, và
**không có endpoint lỗi/cảnh báo/lịch sử nào**. `getErrorLog` chỉ tồn tại trong bundle
web của vendor. Nghĩa là ngay cả app chính thức cũng không đọc được log lỗi — tính
năng này không thuộc phạm vi một integration `cloud_polling`.

**Kết luận: đóng. Không implement.** Giữ lại ghi chép này để lần sau không ai probe
lại `/manage/*` với cùng kỳ vọng.

---

## 7. Kết quả probe (đã sanitize)

### 7.1. Lần chạy hợp lệ — header `Authorization` đúng

File: [`docs/probe_results_tier1_authed.json`](probe_results_tier1_authed.json)

- 19 endpoint, GET-only, 1 request/endpoint, timeout 10s, tuần tự, không retry, sleep 2s, cap 20.
- **13 endpoint trả `returnValue: 1`**: `getAllDayData`, `getHistoryYearData`, `getMonthData`, `getYearData`, `getOnlineStatus`, `deviceInfo`, `getDevice`, `getUserDevice`, `userDeviceList`, `getVersion`, `app/getAppParam`, `device/getTypeList`, `deviceTypeSettingList`.
- **6 endpoint không trả `1`:** `checkUpdate` (`2`), `v2/getAllDayData` (`998`, sai path), `getDT` (`2`), `getMasterSlaveInfo` (`210`), `getUserInfo` (`203`), `getVersionInfo` (`2`).
- Đã redact `token`, `uid`, `nickname`, `phone` → `<redacted>`.

### 7.2. Đối chiếu `getAllDayData` với 3 endpoint legacy

File: [`docs/probe_compare_day_endpoints.json`](probe_compare_day_endpoints.json)

Cùng thiết bị, cùng `queryDate`, so từng chỉ số:

| Chỉ số | Legacy | `getAllDayData` | Khớp |
|--------|--------|-----------------|------|
| `pv.tableValue` | 60 (`getPVDayData`) | 60 | ✅ |
| `grid.tableValue` | 116 (`getOtherDayData`) | 116 | ✅ |
| `homeload.tableValue` | 170 (`getOtherDayData`) | 170 | ✅ |
| `essentialLoad.tableValue` | 0 (`getOtherDayData`) | 0 | ✅ |
| `bat` (charge) | 0 (`getBatDayData:bats[0]`) | 0 | ✅ |
| `batF` (discharge) | 0 (`getBatDayData:bats[1]`) | `None` | ⚠️ |

**Hai điểm cần lưu khi implement:**

1. **`batF` vắng mặt khi không có phát điện.** Legacy trả `bats[1].tableValue = 0`; `getAllDayData` **bỏ hẳn key `batF`** khỏi `data` (và `titleParams` có `batF` với `tableValueInfo` rỗng). Code đọc `data["batF"]` phải chịu được key vắng, không được `KeyError`.
2. **Pin chưa được chứng minh.** Thiết bị test báo không có pin (`battery_type = No Battery`), nên cả hai đường đều ra 0 và phép so sánh **không kiểm chứng được** phần pin. Mapping PV/grid/load thì đã kiểm chứng thật.

### 7.3. Kết quả CŨ — KHÔNG dùng (header sai tên)

File: [`docs/probe_results_tier1.json`](probe_results_tier1.json) — giữ lại làm bằng chứng cho lỗi ở mục 0, **không trích dẫn số liệu**.

- 19 endpoint, nhưng gửi token trong header tên `token` ⇒ không request nào được xác thực.
- Bản đầu ghi nhận "7 endpoint thành công" — số đó tình cờ đúng với **những endpoint không cần auth**, nên vẫn khớp. Còn mọi kết luận dựa trên `2`/`203` đều sai.

### 7.4. Rate limit của host

Sau ~30 request nhanh, host cũ bắt đầu ngắt kết nối (`RemoteDisconnected`) kể cả với `getServerTime`. Lần chạy hợp lệ dùng `sleep(2)` và không gặp hiện tượng này. **Đây là rate limit thật, cần tôn trọng khi implement polling.**


---

## 8. Câu hỏi mở (cập nhật sau đính chính lần hai)

1. ~~**Host nào là hướng phát triển?**~~ **ĐÃ TRẢ LỜI — không cần chuyển host.** `/lesvr/getAllDayData` (không `v2/`) chạy trên host hiện tại `lesvr.suntcn.com` và trả dữ liệu gộp đầy đủ. Kết luận "phải chuyển sang `lesvrjm`" ở bản đầu là hệ quả của probe sai (mục 0).
2. ~~**Có đáng theo đuổi `sign` scheme không?**~~ **KHÔNG CẦN.** Cơ chế `sign` thuộc host `lesvrjm`, mà host đó không cần thiết để lấy `getAllDayData`. Bỏ qua hoàn toàn.
3. **`device/sendMsg` fallback HTTP** — vẫn là **không** đưa vào doc như đường dùng được; ghi rõ nó là Tier 3 (đường gửi lệnh xuống thiết bị).
4. ~~**`getErrorLog`** (`lehtapi`) — vẫn là tính năng đáng giá (lịch sử lỗi). Cần probe host `lehtapi` riêng; xem task D.~~ **ĐÃ TRẢ LỜI — đóng, không implement.** Endpoint có thật nhưng trả `1000` (cần đăng nhập) và auth của nó là cookie session của console dealer, không phải app token; app chính thức cũng không có endpoint lỗi nào. Chi tiết + bằng chứng ở mục 6.
5. **Key đi kèm `svr_aes`** — không còn cấp thiết: nó gắn với `_decrypt` của host `lesvrjm`, mà hướng đó đã bị loại ở (2). Hạ ưu tiên xuống "chỉ đọc nếu sau này cần host mới". Giá trị thật không chép vào repo.
6. **`getDT`, `getVersionInfo`, `checkUpdate`** trả `2` — chưa rõ nghĩa mã `2` và chưa rõ tham số đúng. Không cấp thiết vì `getVersion` đã trả đủ 4 nhóm firmware.


---

## 9. Ranh giới an toàn (bắt buộc, không thương lượng)

- **Chỉ read-only.** Integration không gọi endpoint Tier 3/4 nào. Ngoại lệ duy nhất từng chạy là **một** probe read-only vào route admin `/manage/lesvr/getErrorLog` (mục 6) — POST body rỗng, không credential, không retry, chỉ để trả lời câu hỏi `getErrorLog`; route đó không đi vào code chạy thật.
- **Không ghi vào hạ tầng vendor**: không register, không bind device, không `upSnAddress`, không `device/sendMsg`.
- `tools/` (gồm `emqx_clients.json` 128 MB có credential admin EMQX) **đã được `.gitignore` chặn** ở Phase 0 — không bao giờ commit.
- **Không** đưa token/uid/nickname/phone thô vào bất kỳ file nào được track. Trong tài liệu này chúng là `<redacted>`.
- Rate-limit: 1 request/endpoint, timeout 10s, tuần tự, không retry, sleep 0.5s, cap 40 probe/lần.

---

## 10. Tài liệu liên quan

- [`docs/api/API_PROTOCOL.md`](API_PROTOCOL.md) — giao thức 8 endpoint hiện hành. Hai đính chính của tài liệu này (mục 1.2 và polarity pin) đã được áp vào chính API_PROTOCOL.md.
- [`docs/api/API_TEST_GUIDE.md`](API_TEST_GUIDE.md)
- [`CLAUDE.md`](../../CLAUDE.md) — hợp đồng MQTT hai topic; xem mục 5.1 ở đây cho sáu namespace thật.
