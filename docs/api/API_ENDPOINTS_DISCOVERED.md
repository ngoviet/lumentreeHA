# API Discovery — LightEarth 3.2.4 vs. lumentreeHA 5.1.3

> **Trạng thái:** khảo sát (survey). Chưa implement sensor nào.
> **Nguồn:** `blutter` trên `libapp.so` (Dart 3.9.2, `light_earth` 3.2.4), `web_app.js` (admin console), EMQX exports, và probe read-only có kiểm soát.
> **Ngày:** 2026-09-12

Mục đích của tài liệu này là chốt **bản đồ API thật** trước khi mở rộng integration, và đính chính một số giả định sai đang tồn tại trong repo.

---

## 1. Đính chính quan trọng

Ba điều dưới đây trái với giả định đang lưu hành trong repo và trong các lần khảo sát trước. Cần sửa nhận thức trước khi làm bất cứ điều gì khác.

### 1.1. `returnValue: 998` = "KHÔNG TỒN TẠI", không phải "cần auth"

Body thật của 998 là:

```json
{"returnValue": 998, "msg": "您访问对页面不存在"}
```

Dịch: *"trang bạn truy cập không tồn tại"*. Đây là **catch-all 404**.

Bằng chứng đối chiếu từ probe (mã thật ≠ 998):

| Mã | Nghĩa thật | Ví dụ đã gặp |
|----|-----------|--------------|
| `1` | Thành công | `/lesvr/deviceInfo` → `{"masterStatus": 0}` |
| `2` | Server bận, thử lại sau | `/lesvr/getMonthData` (POST) |
| `3` | Sai HTTP method | `/lesvr/checkUpdate` (cần GET) |
| `203` | Thiếu/sai quyền | `/lesvr/getUserDevice`, `/lesvr/getUserInfo` |
| `998` | **Không tồn tại** | `/lesvr/userLogin` |
| `20001` | Thiếu tham số | `shareDevices` thiếu `expiredTime` |

**Hệ quả:** toàn bộ danh sách "endpoint 998" từ các lần khảo sát trước (`login`, `profile`, `plantList`, `station`, `myDevices`, `account`, …) là **đường dẫn đoán mò không tồn tại**. Phải loại bỏ, không tốn công "authenticate".

### 1.2. Bốn endpoint integration đang dùng là **alias legacy**

Quét `libapp.so` 3.2.4: `getServerTime`, `getPVDayData`, `getBatDayData`, `getOtherDayData` có **0 lần xuất hiện**. App hiện tại dùng `lesvr/v2/getAllDayData`.

Nghĩa là 4 endpoint đó vẫn chạy phía server (và integration vẫn hoạt động), nhưng đã bị app bỏ. **Không được coi chúng là "endpoint hiện hành" khi viết tài liệu mới.**

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

**Phát hiện then chốt:** `lesvr/v2/getAllDayData` trả `998` (không tồn tại) trên host cũ, và chỉ sống trên host mới. Đây là lý do kỹ thuật khiến integration hiện tại không thể dùng endpoint gộp này.

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

### Tier 1 — Ứng viên implement (read-only, đã probe)

| Endpoint | Method | Probe | Payload thật |
|----------|--------|-------|--------------|
| `lesvr/v2/getAllDayData` | GET | ❌ `998` trên host cũ | `deviceId`, `queryDate` (`yyyy-MM-dd`) |
| `lesvr/getHistoryYearData` | GET | ❌ `2` | `deviceId`, `queryYear` |
| `lesvr/getMonthData` | GET | ❌ `2` | `deviceId`, `year`, `month` (đã dùng) |
| `lesvr/getYearData` | GET | ❌ `2` | `deviceId`, `year` (đã dùng) |
| `lesvr/getOnlineStatus` | GET | ✅ `1` | `{"onlineStatus": 0}` |
| `lesvr/deviceInfo` | GET | ✅ `1` | `{"masterStatus": 0}` |
| `lesvr/getVersion` | GET | ✅ `1` | 4 nhóm firmware: `controller`, `controller2`, `screen`, `liquidCrystal` |
| `app/getAppParam` | GET | ✅ `1` | `maxDiffData`, `userKeepTime`, `snParam`, `deviceTypeImg`, … |
| `device/getTypeList` | GET | ✅ `1` | `deviceTypes[]`: `SUNT-4.0kW-HP`, `SUNT-6.0kW-HT`, … |
| `lesvr/deviceTypeSettingList` | GET | ✅ `1` | Cần `blueTooth` + `version` |
| `lesvr/getMasterSlaveInfo` | GET | ❌ `2` | `deviceId` |
| `lesvr/getDevice` | GET | ❌ `203` | `deviceId` |
| `lesvr/getUserInfo` / `getUserDevice` / `userDeviceList` | GET | ❌ `203` | quyền `userType` |

**Giá trị cao nhất:** `v2/getAllDayData` — gộp PV + battery + load + grid vào **một call duy nhất**, thay cho 3 call riêng (`getPVDayData` + `getBatDayData` + `getOtherDayData`) mà integration đang dùng.

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
| `appuser` | 1,649 | **integration đang dùng** (password nằm trong `const.py`) |
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

**Chưa probe** — cần xác minh host `lehtapi.suntcn.com` có chấp nhận token kiểu shareDevices hay không.

---

## 7. Kết quả probe (đã sanitize)

File: [`docs/probe_results_tier1.json`](probe_results_tier1.json)

- 19 endpoint Tier-1, GET-only, 1 request/endpoint, timeout 10s, tuần tự, không retry, sleep 0.5s.
- **7 endpoint trả `returnValue: 1`** (thành công): `getOnlineStatus`, `deviceInfo`, `getDeviceQuickList`, `getVersion`, `app/getAppParam`, `device/getTypeList`, `deviceTypeSettingList`.
- `lesvrjm.suntcn.com` trả `2` (*server bận*) cho `getServerTime` — **chưa lấy được token trên host mới**.
- Đã redact `token`, `uid`, `nickname`, `phone` → `<redacted>`.

**Hạn chế đã gặp:** sau ~30 request, host cũ bắt đầu ngắt kết nối (`RemoteDisconnected`), kể cả với `getServerTime`. Đã dừng probe theo luật rate-limit trong plan, không retry.

---

## 8. Câu hỏi mở (cần anh quyết)

1. **Host nào là hướng phát triển?** `v2/getAllDayData` chỉ sống trên `lesvrjm.suntcn.com`. Nếu muốn dùng endpoint gộp, integration phải chuyển host — kèm rủi ro vì phải làm chủ cơ chế `sign` (mục 3) chưa xác minh.
2. **Có đáng theo đuổi `sign` scheme không?** Nếu chỉ cần `getAllDayData`, chi phí là: implement MD5 sign + nonce + timestamp, và chấp nhận rằng công thức chưa được xác minh live.
3. **`device/sendMsg` fallback HTTP** — có nên đưa vào doc như một "cửa hậu" tiềm năng không? Em đề xuất **không**, và ghi rõ nó là Tier 3.
4. **`getErrorLog`** (`lehtapi`) — đây là tính năng mới thật sự đáng giá (lịch sử lỗi). Có cần em probe host `lehtapi` riêng không?
5. **Key đi kèm `svr_aes`** — em chưa chứng minh được nó là AES key hay app key; nó nằm cạnh hằng số AES trong `_decrypt`. Giá trị thật không chép vào repo. Cần đọc sâu hơn nếu quyết định làm (`encrypt` package), nhưng chỉ khi hướng "host mới" được duyệt.

---

## 9. Ranh giới an toàn (bắt buộc, không thương lượng)

- **Chỉ read-only.** Không endpoint Tier 3/4 nào bị gọi, kể cả để test.
- **Không ghi vào hạ tầng vendor**: không register, không bind device, không `upSnAddress`, không `device/sendMsg`.
- `tools/` (gồm `emqx_clients.json` 128 MB có credential admin EMQX) **đã được `.gitignore` chặn** ở Phase 0 — không bao giờ commit.
- **Không** đưa token/uid/nickname/phone thô vào bất kỳ file nào được track. Trong tài liệu này chúng là `<redacted>`.
- Rate-limit: 1 request/endpoint, timeout 10s, tuần tự, không retry, sleep 0.5s, cap 40 probe/lần.

---

## 10. Tài liệu liên quan

- [`docs/api/API_PROTOCOL.md`](API_PROTOCOL.md) — giao thức 8 endpoint hiện hành. Hai đính chính của tài liệu này (mục 1.2 và polarity pin) đã được áp vào chính API_PROTOCOL.md.
- [`docs/api/API_TEST_GUIDE.md`](API_TEST_GUIDE.md)
- [`CLAUDE.md`](../../CLAUDE.md) — hợp đồng MQTT hai topic; xem mục 5.1 ở đây cho sáu namespace thật.
