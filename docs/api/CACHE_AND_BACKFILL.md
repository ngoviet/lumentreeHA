# Cache and Backfill Strategy

> **Phạm vi:** tài liệu này giữ *chiến lược* cache/backfill. Cấu trúc file, tên
> hàm và luồng I/O thật thuộc về một owner duy nhất:
> [`services/cache.py`](../../services/cache.py) (định dạng + I/O) và
> [`services/aggregator.py`](../../services/aggregator.py) (điều phối backfill).
> Đọc docstring đầu `services/cache.py` cho layout đầy đủ — **không** chép lại
> ở đây.

## Cache Structure

Cache nằm trong `.storage/lumentree_stats/`, **một file JSON cho mỗi device mỗi
năm** — không phải cây thư mục theo ngày/tháng:

```
.storage/lumentree_stats/{device_id}/{YYYY}.json
```

Một file năm chứa cả `daily` (map ngày → tổng), `monthly` (12 phần tử/metric),
`yearly_total`, và `meta` (coverage, empty_dates, last_backfill_date).

Ghi cache là **atomic** (ghi temp rồi `os.replace`, có lock theo file). Đây là
chi tiết bảo vệ tính toàn vẹn dữ liệu — xem `save_year()` trong
[`services/cache.py`](../../services/cache.py).

### I/O và event loop

Mọi hàm trong `services/cache.py` là **đồng bộ (blocking)**. Chúng **không bao
giờ** được gọi trực tiếp trong async context: caller phải bọc qua
`hass.async_add_executor_job(...)`. `services/aggregator.py` làm đúng như vậy ở
mọi call site.

Đây là ràng buộc bắt buộc, không phải gợi ý — gọi trực tiếp sẽ chặn event loop
của Home Assistant.

## Smart Backfill Strategy

### Principles
1. **Use daily API for historical data**: More reliable than monthly/yearly APIs
2. **Cache-first approach**: Check cache before API calls
3. **Incremental backfill**: Fill gaps chronologically
4. **Respect API limitations**: Don't overload API with requests

### Backfill Algorithm

Luồng backfill thật nằm trong `StatsAggregator`
([`services/aggregator.py`](../../services/aggregator.py)); các entry point được
phơi ra qua HA services trong `services.yaml`:

| Service | Method | Việc nó làm |
|---------|--------|-------------|
| `backfill_now` | `backfill_last_n_days()` | Lấp N ngày gần nhất |
| `backfill_all` | `backfill_all()` | Quét lùi toàn bộ lịch sử |
| `backfill_gaps` | `backfill_gaps()` | Chỉ lấp ngày còn thiếu, giới hạn mỗi lần chạy |
| `backfill_empty_dates` | `backfill_empty_dates()` | Fetch lại các ngày từng bị đánh dấu rỗng |

Mọi biến thể đi theo cùng một hình dạng:

1. **Batch theo năm** — nạp cache của cả năm một lần bằng
   `cache_io.load_year()` (qua executor), giữ trong bộ nhớ, ghi lại một lần bằng
   `cache_io.save_year()` khi kết thúc năm. Không đọc/ghi file mỗi ngày.
2. **Bỏ qua ngày đã có** — `if date_str in cache["daily"]: continue`.
3. **Gọi API** — `fetch_day(date_str)` gọi song song 3 endpoint daily
   (`getPVDayData`, `getBatDayData`, `getOtherDayData`) rồi chuẩn hoá về kWh.
4. **Cập nhật tăng dần** — `cache_io.update_daily(cache, date_str, vals)` cộng
   delta vào bucket tháng và `yearly_total` trong O(1), không dựng lại mảng.
5. **Rate limit** — sleep cơ bản giữa các lần gọi, nhân đôi (cap 5s) khi lỗi.

### Đánh dấu ngày rỗng

Server luôn trả về cùng một cấu trúc (toàn số 0 khi không có dữ liệu), nên
không thể phân biệt "ngày rỗng" với "lỗi" chỉ bằng response. Hai cơ chế:

- `meta.empty_dates` — danh sách ngày được xác nhận rỗng, ghi qua
  `cache_io.mark_empty()`. `daily_coordinator` ghi vào đây khi một ngày trôi qua
  không có dữ liệu; service `mark_empty_dates` ghi thủ công; service
  `backfill_empty_dates` fetch lại toàn bộ danh sách khi logic parse được cải
  thiện.
- `meta.coverage` — khoảng `earliest`/`latest` đã có dữ liệu.

### Xử lý giới hạn của API

`getYearData`/`getMonthData` **chỉ trả về năm/tháng hiện tại** — không lấy được
dữ liệu lịch sử. Vì vậy backfill lịch sử phải đi qua daily API rồi tự tính
aggregate từ cache ngày. Xem
[`API_PROTOCOL.md`](API_PROTOCOL.md#important-notes) cho chi tiết giới hạn này.

## Cache Management

### Recompute aggregates

Nếu mảng `monthly` trông sai (mọi tháng cùng một giá trị), `load_year()` tự
phát hiện qua `_needs_recompute()` và dựng lại từ `daily` bằng
`recompute_aggregates()`. Caller cũng có thể ép recompute qua service
`recompute_month_year`.

### Purge

- `cache_io.purge_year(device_id, year)` — xoá một file năm.
- `cache_io.purge_device(device_id)` — xoá mọi file của một device.

Cả hai chỉ xoá file cache; chúng không phải là API của vendor.

## Data Processing

Việc chuyển đổi series 5 phút sang giờ/Watt và tách charge/discharge được thực
hiện trong `core/api_client.py` và `core/realtime_parser.py` — xem
[`REGISTER_MAP.md`](REGISTER_MAP.md) cho quy ước dấu của pin.

## Best Practices

1. **Luôn cache response API**: giảm số lần gọi vendor.
2. **Batch I/O theo năm**: một lần load/save cho mỗi năm, không phải mỗi ngày.
3. **Không blocking I/O trên event loop**: bọc mọi hàm `services/cache.py` qua
   `async_add_executor_job`.
4. **Dùng daily API cho dữ liệu lịch sử**: monthly/yearly chỉ có kỳ hiện tại.
5. **Tính aggregate từ daily**: đừng tin monthly/yearly API cho lịch sử.
6. **Rate limit**: sleep giữa các request, backoff khi lỗi.

## Troubleshooting

### Issue: Cache Not Updating
- **Check**: quyền ghi thư mục `.storage/lumentree_stats/{device_id}/`
- **Check**: log `Failed to save cache` — lỗi ghi sẽ được raise, không bị nuốt
- **Solution**: xoá file cache của năm đó rồi backfill lại

### Issue: Backfill Too Slow
- **Check**: delay đang tăng do lỗi lặp lại (backoff cap 5s)
- **Solution**: giảm số ngày mỗi lần chạy, chạy nhiều lần

### Issue: Monthly/Yearly Data Incorrect
- **Check**: giới hạn API (chỉ trả về kỳ hiện tại)
- **Solution**: `recompute_month_year` để dựng lại từ daily cache


