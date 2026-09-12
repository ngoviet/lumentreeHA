# Modbus register map

How the real-time MQTT register table in [const.py](../../const.py) (`REG_ADDR`)
was established, what each register means, and what is deliberately left out.

## Where the table comes from

The integration subscribes to `reportApp/{serial}` on the vendor broker. The
payload is a raw Modbus-RTU response, so the register indices are fixed by the
device firmware.

The meaning and scale of each register were recovered from the vendor's
LightEarth Android app rather than guessed:

1. The app is Flutter, so it was decompiled with [blutter](https://github.com/worawit/blutter)
   to recover Dart class and method names from `libapp.so`.
2. `DeviceAddrConfig` in the recovered Dart is the app's register table. It binds
   every signal to one address **per wire protocol**; the app's `field_7` is
   protocol 1, `field_b` is protocol 2, `field_f` is protocol 3.
3. Scale factors and signedness come from the app's formatter layer:
   `ui/main/deviceDetail/tools/params_tool.dart` (`DevicePageParams`) and
   `ui/main/deviceSettings/components/*.dart`. The divisor lives in
   `ComponentNumberSettingSpec.field_f`; the divide itself is visible in
   `component_utils.dart` (`transDesFrom`) as a float division of the raw word
   by that field.
4. `_readSignedIntWithConfig` / `_readUnsignedIntWithConfig` in
   `device_protocol_adapter.dart` supply the signedness. Those functions do no
   arithmetic of their own.

### The address law

```
app_addr == 2 * register_index
```

This is what lets an app address be converted into a register index, and it is
verified rather than assumed: the device serial number sits at register index 3
in every captured frame, and the app binds it to address 6.

`const.py` records the app address in a trailing comment on each extended entry
so the mapping stays auditable.

## Frame layout

```
[slave 0x01][fc 0x03][byte count 1B][data ...][CRC16 2B little-endian]
```

Payloads arrive with a literal `++++` separator in front of the frame.

Two consequences shape everything below:

- **The byte count is one byte.** A 302-byte body therefore declares
  `302 & 0xFF` = 46. The parser dispatches on the real byte length, never on the
  declared count; comparing the declared count to 302 can never be true. The
  captured corpus confirms this: all 35 aligned full frames declare 46.
- **A device may answer with fewer registers than were asked for.** The
  integration requests 151 registers, but the common response is 190 bytes
  (95 registers, indices 0..94). Everything at index 95 and above reads `None`
  on those units — the key is simply not set, so the sensor shows `unknown`
  rather than a wrong number.

Observed aligned frame lengths, with counts from the captured corpus:

| Data bytes | Registers | Frames | Meaning |
|---|---|---|---|
| 100 | 50 | — | Battery cell data (`REG_ADDR_CELL_START`/`_COUNT`) |
| 140 | 70 | 7 | Partial main data |
| 189/190 | 94/95 | 101 | Legacy main data — the common case |
| 198 | 99 | — | Legacy main with partial metadata |
| 201/202 | — | 93 | Legacy 95 registers + 12 bytes metadata |
| 301/302 | 150/151 | 36 | Full frame, the only one carrying indices ≥ 95 |

## Scale and signedness

| Register | Index | App addr | Raw → value | Notes |
|---|---|---|---|---|
| `FIRMWARE_VERSION` | 2 | 4 | — | Rendered by the app as a **string**; the integration formats it as `v{n}`. See the caveat below. |
| `DEVICE_MODEL_START` | 3 | 6 | — | First bytes of the device serial; not a number. |
| `CONTROLLER_VERSION` | 8 | 16 | — | See the caveat below. |
| `BATTERY_VOLTAGE` | 11 | 22 | /100 | |
| `BATTERY_CURRENT` | 12 | 24 | /100, signed | Sign is inverted before publication so positive means charging. |
| `AC_OUT_VOLTAGE` | 13 | 26 | /10 | |
| `GRID_VOLTAGE` | 15 | 30 | /10 | |
| `AC_OUT_FREQ` | 16 | 32 | /100 | |
| `AC_IN_FREQ` | 17 | 34 | /100 | |
| `AC_OUT_POWER` | 18 | 36 | raw W | |
| `PV1_VOLTAGE` | 20 | 40 | raw V | |
| `PV1_POWER` | 22 | 44 | raw W | |
| `DEVICE_TEMP` | 24 | 48 | (raw − 1000)/10 | °C |
| `BATTERY_TYPE` | 37 | 74 | enum | |
| `BATTERY_SOC` | 50 | 100 | raw % | |
| `AC_IN_POWER` | 53 | 106 | raw W, signed | **Was divided by 100 — see below.** |
| `AC_OUT_VA` | 58 | 116 | raw VA | |
| `GRID_POWER` | 59 | 118 | raw W, signed | |
| `BATTERY_POWER` | 61 | 122 | raw W, signed | |
| `LOAD_POWER` | 67 | 134 | raw W, signed | **Signedness fixed — see below.** |
| `UPS_MODE` | 68 | 136 | 0/1 | |
| `MASTER_SLAVE_STATUS` | 70 | 140 | raw | |
| `PV2_VOLTAGE` | 72 | 144 | raw V | |
| `PV2_POWER` | 74 | 148 | raw W | |
| `BATTERY_MODE` | 100 | 200 | enum | |
| `WORK_MODE` | 150 | 300 | enum | Beyond the 190-byte frame on most units. |

### Extended range

Recovered from the app register table, these additions span both the common and extended frame ranges.
Availability depends on the register index, not on whether the entity was added in this revision: see [Frame layout](#frame-layout).
The common 190-byte frame includes today's PV yield, AC input/output currents and generator power; higher-index settings require a longer main frame.
The parser's bounds check in [`_read_register`](../../core/realtime_parser.py) omits values outside the available register buffer.

| Register | Index | App addr | Raw → value |
|---|---|---|---|
| `FW_VERSION_CONTROLLER_ADDR` | 9 | 18 | **string** — not published |
| `FW_VERSION_LCD` | 10 | 20 | **string** — not published |
| `SOLAR_SELL_GRAPH` | 19 | 38 | flag values; not a measurement — not published |
| `TODAY_PV_INPUT` | 33 | 66 | /10, signed → kWh |
| `AC_IN_CURRENT` | 54 | 108 | /100, signed → A |
| `AC_OUT_CURRENT` | 62 | 124 | /100, signed → A |
| `GEN_INV_POWER` | 82 | 164 | raw W, signed |
| `DEVICE_IMAGE_FLAG` | 94 | 188 | selects the product image; not published |
| `AI_MODE` | 96 | 192 | enum 0/1/2 |
| `EQUALIZING_CHARGE_VOLTAGE` | 101 | 202 | /100 → V |
| `BOOST_CHARGE_VOLTAGE` | 102 | 204 | /100 → V |
| `FLOAT_CHARGE_VOLTAGE` | 103 | 206 | /100 → V |
| `BATTERY_CAPACITY` | 104 | 208 | raw Ah |
| `BATTERY_MAX_CHARGE_CURRENT` | 106 | 212 | raw A |
| `MAX_DISCHARGE_CURRENT` | 107 | 214 | raw A |
| `LOW_CAPACITY_CUTOFF` | 111 | 222 | raw % |
| `PROTECTING_RECOVERY_POINT` | 112 | 224 | raw % |
| `BATTERY_LOW_VOLTAGE_PROTECTION` | 114 | 228 | /100 → V |
| `BATTERY_RECOVERY_VOLTAGE` | 115 | 230 | /100 → V |
| `CHARGE_FROM_AC` | 120 | 240 | 0/1 |
| `AC_OUT_FREQ_SET` | 123 | 246 | enum, values 0 and 2 |
| `AC_COUPLING` | 124 | 248 | 0/1 |
| `GRID_TYPE` | 125 | 250 | enum 0/2/4 |
| `CT_TRICKLE_FEED` | 147 | 294 | raw W |
| `EQUALIZING_CHARGE_INTERVAL` | 148 | 296 | raw days |
| `EQUALIZING_CHARGE_TIME` | 149 | 298 | raw minutes |

## Discrepancies found and how they were resolved

Each of these was measured against the captured corpus before being changed.
"Aligned" below means a frame that passes five independent sanity checks
(AC output voltage, grid voltage, AC frequency, SOC and battery voltage each
landing in a physically plausible range) — see `tools/check_frame_alignment.py`.

### `AC_IN_POWER` divided by 100 — the divisor was wrong

Across frames scoring 5/5 on the alignment check, register 53 has a maximum of
315 and a median of 18. Read raw that is 18 W / 315 W, which is what an inverter
charging from grid looks like. Divided by 100 it becomes a median of 0.18 W and
a maximum of 3.15 W, which is not.

An independent cross-check agrees: on frames where AC voltage and current are
both readable, the implied power factor only lands in a believable range (about
0.25) when the word is read as watts. Dividing by 100 puts it at 0.0025.

The `/100` came from commit `0a75e07` (the v3.0.0 refactor, then
`core/modbus_parser.py`), whose lineage is the lumentree-dashboard project
rather than the vendor app. It has been removed.

### `LOAD_POWER` read unsigned — now signed

The app reads it through `_readSignedIntWithConfig`. No captured value exceeds
32767, so this only matters for a negative load, but the signedness is now
matched to the app.

### `DEVICE_TEMP` — documented, not changed

The app takes the maximum of three temperature registers (48, 182 and 1082).
Only register 24 is inside the requested frame, so that behaviour cannot be
reproduced here. Signedness is immaterial: the largest raw value observed is
1544, far below the 32768 boundary, giving a range of 33.8–54.4 °C with a
median of 39.4 °C. Left as unsigned with the limitation recorded in the parser.

### `BATTERY_TYPE` (register 37) versus register 100 — inconclusive, unchanged

Both registers returned only the values `{0, 1}` across every aligned frame, so
no evidence distinguishes them. Left as-is rather than changed on a guess: a
sensor carrying the wrong name is worse than no sensor.

### PV voltage protocol conditioning — not applicable

The app conditions some PV voltage readings on the active protocol. This
integration speaks protocol 1 only, so the conditioning is a no-op here and was
not implemented.

### Firmware and controller version registers — reported, not changed

The first bytes of the response are a header (`03 00 | 01 15 | 01 02`) followed
by the serial at bytes 6–15. So register 2 is `0x0102` = **258, constant in 232
of 237 aligned frames** — rendered by this integration as `"v258"` — register 3
holds the leading characters of the serial, and register 8 reads 7.

The app reads its protocol value from address 4. Fixing this would rename
already-running entities, so it is recorded here and left alone pending an
explicit decision.

## Sampling caveat

Statistics quoted in this document come from frames that decode cleanly. The
corpus payloads were round-tripped through a lossy UTF-8 decode, and the bytes
most often lost are exactly the high bytes of large values. **Any "maximum"
quoted here is therefore a lower bound**, and a value that is absent from the
sample is not evidence that it never occurs on a device.

Synthetic frames in [tests/test_realtime_parser.py](../../tests/test_realtime_parser.py)
cover the cases the corpus cannot, including values above the lossy-decode
ceiling and the full 151-register frame.

## Registers deliberately not published

| Signal | Reason |
|---|---|
| Firmware version strings (indices 9, 10) | The app renders them as strings; publishing them as numbers would report a wrong value. |
| `DEVICE_MODEL_START` (index 3) | Device serial prefix, not a measurement. |
| `SOLAR_SELL_GRAPH` (index 19) | Mode flag, not a measurement. |
| `DEVICE_IMAGE_FLAG` (index 94) | Selects which product image the app shows. |
| Battery cell data | Already published separately via `REG_ADDR_CELL_START`. |
