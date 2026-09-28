# Flood Engine v0.1 – แหล่งข้อมูลของแต่ละ Signal (เตรียมไว้ ยังไม่คำนวณ)

Phase 0 **ไม่คำนวณ risk score** ตารางนี้แสดงว่าแต่ละ signal ใน Sheet "Flood Engine v0.1" จะอ่านจากตารางใด
เพื่อให้ข้อมูลที่เก็บวันนี้ใช้ได้ทันทีเมื่อเริ่ม Phase ถัดไป

| Signal (weight) | ตาราง / คอลัมน์ | สถานะข้อมูลใน Phase 0 |
|---|---|---|
| ฝนสะสมระยะสั้น rain_3h (25) | `weather_observation.rain_mm` + `rain_period_hours` (TMD synoptic); ภายหลัง `water_level_observation.rain_mm` (rain gauge) | collector พร้อม (TMD) / rain gauge = DISCOVER |
| ฝนคาดการณ์ 6 ชม. (20) | `weather_forecast.precipitation_mm` จาก run ล่าสุดของแต่ละโมเดล, sum 6 ชม. ตาม `forecast_time`; consensus/spread ข้าม `model` | collector พร้อม |
| ระดับน้ำ / แนวโน้ม (20) | `water_level_observation.water_level_m` (trend = ส่วนต่างตาม `observed_at`), เทียบ `water_station.bank_level_m/warning_level_m` | ตารางพร้อม, แหล่ง = DISCOVER |
| Discharge | `water_level_observation.discharge_m3s` | ตารางพร้อม |
| เขื่อน / การระบาย (10) | `reservoir_status.storage_pct`, `outflow_m3s`, `inflow_m3s` (เทียบวันก่อนหน้า) | collector พร้อม (RID) |
| น้ำทะเลหนุน (10) | `water_level_observation` ของ `water_station.station_kind='tide'` | ตารางพร้อม, แหล่ง = DISCOVER |
| Flood extent ใกล้เคียง (10) | `flood_extent.geometry` (ST_DWithin กับ `location.geom`), `flood_point_check.is_flooded` | collector พร้อม (ต้องมี key) |
| Official warning (5) | `official_warning` (issued_at, area_text, province_codes) | collector พร้อม (TMD) |

การวิเคราะห์หลังเก็บ 7–30 วัน (ไม่ต้องเปลี่ยน schema):
- **Forecast accuracy / rainfall error / model bias**: join `weather_forecast` (by `model`, `lead_time_hours`) กับ
  `weather_observation` ที่เวลาเดียวกัน (สะสมฝนให้ตรง `rain_period_hours`)
- **ความสัมพันธ์ฝน–ระดับน้ำ**: `weather_observation`/`weather_forecast` × `water_level_observation` ตามเวลา
- **Forecast vs Flood extent**: `weather_forecast` × `flood_extent` (spatial join ผ่าน `location.geom`)
- **ความเสถียรของแหล่ง**: `collector_run` (uptime, latency, gaps)
