# Phase 0 – Architecture (Data Collection Platform)

อ้างอิงแผน: `docs/Thailand_Weather_Flood_Data_Plan_v0.1.xlsx` (Overview, Data Sources, Phase 0 Backlog, DB Schema, Flood Engine v0.1)

เป้าหมาย Phase 0: **DATA FIRST** — ดึงข้อมูลจริงจากหลายแหล่งมาเก็บต่อเนื่อง 7–30 วัน โดย
ไม่มี Frontend, ไม่มี ML, ไม่คำนวณ Flood Risk (เตรียมโครงสร้างไว้เท่านั้น)

---

## 1. ภาพรวม Architecture

```
            ┌──────────────── Scheduler (APScheduler, process แยก) ────────────────┐
            │  job ละ 1 ตัว · max_instances=1 · coalesce · thread pool · stagger     │
            └───────┬──────────────┬──────────────┬──────────────┬──────────────────┘
                    ▼              ▼              ▼              ▼
             OpenMeteo x4      TMD x3          RID x2        GISTDA x2      ← collectors/ (แยกไฟล์ต่อแหล่ง)
                    │   HttpFetcher: timeout · retry · exponential backoff+jitter · Retry-After
                    ▼
        ┌─────────────────────────┐        ┌──────────────────────────────────┐
        │ Layer 1: raw_payload    │ ─────► │ Layer 2: normalized tables         │
        │ body ต้นฉบับ + checksum  │ parse  │ UTC · mm · °C · km/h · m · m3/s · MCM│
        └─────────────────────────┘        └──────────────────────────────────┘
                    │                                   │
                    └──── data_source_health / collector_run (ทุก run) ────┐
                                                                            ▼
                                                FastAPI (internal API, read only)
```

หลักการ
- **Collector แยกกันสมบูรณ์**: ไฟล์แยก, job แยก, HTTP client แยก, `run()` ไม่ throw ออกมา
  → API ตัวหนึ่งล่มไม่กระทบตัวอื่น (มี test ยืนยัน)
- **เก็บ 2 ชั้น**: ทุก response (รวม non-2xx) ถูกเก็บใน `raw_payload` ใน transaction ของตัวเอง
  *ก่อน* parse → parser พังก็ไม่เสียข้อมูล และ `python -m app.cli reprocess` parse ใหม่ได้โดยไม่เรียก API ซ้ำ
- **ไม่สร้างข้อมูลเอง**: หน่วยไม่รู้จัก → เก็บ NULL + log, schema ไม่ตรง → สถานะ `REQUIRES_INVESTIGATION`,
  ไม่มี key → `NO_API_KEY`, ไม่มี endpoint → `NOT_CONFIGURED`
- **Traceability**: ทุกแถว normalized มี `source`, `raw_payload_id` (→ endpoint, fetched_at, status, checksum)
  และเวลาของข้อมูล (`observed_at` / `forecast_time` / `issued_at` …) แยกจากเวลาที่ดึง

## 2. Folder Structure

```
app/
  main.py                 FastAPI app
  cli.py                  init-db / collect / backfill / reprocess / health
  config/
    settings.py           .env → Settings (pydantic-settings)
    locations.json        จุดพยากรณ์ 6 จังหวัดทดสอบ (เพิ่มได้ทั้งประเทศ)
    source_catalog.json   18 แหล่งจาก Sheet "Data Sources" + job ที่ implement
    logging.py
  collectors/
    base.py               BaseCollector: fetch→raw, normalize, run lifecycle, health
    http.py               HttpFetcher (timeout/retry/backoff)
    openmeteo.py          WX-01..04
    tmd.py                TMD-01..03
    synop.py              WMO FM-12 SYNOP (AAXX) decoder สำหรับ TMD-01
    rid.py                RID-01..02
    gistda.py             GIS-01..02
    registry.py           สร้าง job ทั้งหมดจาก settings
  services/
    normalizer.py         หน่วย / เวลา / ตัวเลข
    storage.py            raw archive (dedupe checksum) + upsert (ON CONFLICT)
    health.py             source health monitor
    locations.py
    database.py
  models/                 weather.py water.py reservoir.py warning.py flood.py raw.py source.py
  api/routes/             health.py weather.py water.py
  scheduler/              jobs.py, __main__.py (python -m app.scheduler)
migrations/               Alembic (0001 = schema Phase 0)
tests/                    pytest (PostgreSQL+PostGIS จริง, payload ทดสอบเป็น synthetic)
docs/                     เอกสารนี้ + DATA_SOURCES.md + FLOOD_ENGINE_INPUTS.md + Excel แผน
```

## 3. Database Tables

| Table | หน้าที่ | Unique key (กัน duplicate) |
|---|---|---|
| `raw_payload` | response ต้นฉบับ (text), endpoint (ตัด secret), params, fetched_at, status_code, checksum, context, parse_status | – (body ซ้ำกับครั้งก่อนของ request เดียวกัน → ไม่เก็บ body ซ้ำ, ชี้ `same_as_id`) |
| `data_source_health` | สถานะล่าสุดต่อ job: status, last_success, latency, consecutive_failures, last_error | `job` |
| `collector_run` | ประวัติทุกครั้งที่รัน (ใช้วัด uptime / gaps 7–30 วัน) | – |
| `location` | จุดพยากรณ์ (PostGIS point) | `code` |
| `forecast_run` | 1 model run: `model_run_time`, available_at, temporal resolution | `(source, model, model_run_time)` |
| `weather_forecast` | ค่าพยากรณ์รายชั่วโมง, `model_run_time` แยกจาก `forecast_time`, `lead_time_hours` | `(source, model, product, model_run_time, forecast_time, location_id)` NULLS NOT DISTINCT |
| `weather_station` | สถานีตรวจอากาศ (WMO id) | `(source, station_code)` |
| `weather_observation` | ค่าตรวจวัด + `rain_period_hours` + `report_text` ต้นฉบับ | `(source, station_id, observed_at, obs_type)` |
| `water_station` | สถานีน้ำ (river/canal/tide) + ระดับตลิ่ง/เตือน | `(source, station_code)` |
| `water_level_observation` | ระดับน้ำ (m), discharge (m3/s) | `(source, station_id, observed_at)` |
| `reservoir` | ทะเบียนเขื่อน/อ่าง (capacity MCM) | `(source, reservoir_code)` |
| `reservoir_status` | รายวัน: storage MCM/%, usable, inflow/outflow (MCM/day และ m3/s) | `(source, reservoir_id, observed_date)` |
| `official_warning` | ประกาศเตือน (agency, issued_at, severity, area_text, body) | `(source, source_warning_id)` |
| `flood_extent` | polygon น้ำท่วม (PostGIS geometry 4326) + area_sqkm | `(source, source_feature_id)` |
| `flood_point_check` | ผล "จุดนี้อยู่ในพื้นที่น้ำท่วมหรือไม่" ต่อ location | `(source, location_id, checked_at)` |

### ความต่างจาก Sheet "DB Schema" (ตั้งใจ)
- `weather_forecast.source_model` → แยกเป็น `source` + `model`; `run_time` → `model_run_time` (เวลา init ของโมเดล
  จาก metadata ของ Open-Meteo **ไม่ใช่** เวลา ingest); เพิ่ม `forecast_run` เพื่อผูก metadata ของ run
- `lat/lon` เก็บตามแผน + `location_id` (ใช้เป็น unique key แทน float) + `grid_lat/lon` ที่โมเดลใช้จริง
- `wind_kph` → `wind_speed_kmh`, `humidity_pct`, `precip_probability_pct`, `soil_moisture_m3m3` + `soil_moisture_layer`
- Sheet ใช้ `water_station` เป็นตาราง observation → แยกเป็น `water_station` (ทะเบียน) + `water_level_observation`;
  `discharge_cms` → `discharge_m3s`
- `raw_payload.payload` ใช้ `text` แทน `jsonb`: เก็บ byte-exact (jsonb จัดเรียง key ใหม่/ตัด key ซ้ำ ทำให้ checksum
  และการ audit ไม่ตรง) และรองรับ bulletin ที่เป็น text; query JSON ได้ด้วย `payload::jsonb`
- `official_warning.agency`, `issued_at`, `severity`, `area_text` ตามแผน + `source_warning_id` สำหรับกันซ้ำ

## 4. Collectors

| Job | Source ID | ทำอะไร | รอบ |
|---|---|---|---|
| `openmeteo.forecast.{ECMWF,GFS,JMA}` | WX-01..03 | อ่าน meta.json → `model_run_time`; ถ้า run ใหม่ ดึง hourly 16 วัน ทุก location ใน 1 request; อ่าน meta ซ้ำ ถ้า run เปลี่ยนระหว่างดึง → ไม่ normalize (กันผูก run ผิด) | ทุก 30 นาที (ดึงจริงเฉพาะเมื่อมี run ใหม่ ~4 ครั้ง/วัน/โมเดล) |
| `openmeteo.historical_forecast` | WX-04 | ดึงย้อนหลัง N วันทุกโมเดล (`product=historical_forecast`, run time = NULL เพราะ API ไม่ให้) + CLI backfill | ทุกวัน 02:15 UTC |
| `tmd.synoptic` | TMD-01 | ดึง bulletin ตามชั่วโมง synoptic (00,03,…Z) ย้อนหลัง 6 ชม. → decode AAXX → `weather_observation` | ทุก 60 นาที |
| `tmd.warning` | TMD-03 | bulletin เตือนภัย/SIGMET/พายุ → `official_warning` (ต้องมี WMO heading) | ทุก 30 นาที |
| `tmd.metar` | TMD-02 (P1) | เก็บ raw อย่างเดียว (ปิดไว้ default) | 30 นาที |
| `rid.dam` | RID-01 | สถานะเขื่อนใหญ่ วันนี้+เมื่อวาน (Asia/Bangkok), revise ได้ → upsert + CLI backfill ย้อนหลัง | ทุก 3 ชม. |
| `rid.medium_reservoir` | RID-02 (P1) | อ่างขนาดกลาง (ปิดไว้ default) | 3 ชม. |
| `gistda.flood_point_check` | GIS-01 | ถามทีละ location ว่าอยู่ใน flood extent 1 วันหรือไม่ | 6 ชม. |
| `gistda.flood_polygon` | GIS-02 | polygon GeoJSON (paging) → `flood_extent` | 6 ชม. |

ทุก collector: timeout, retry+exponential backoff+jitter, logging, error handling, `last_success`, health status

## 5. Scheduler

- `python -m app.scheduler` (process แยกจาก API) หรือ `RUN_SCHEDULER_IN_API=true` ตอน dev
- 1 collector = 1 APScheduler job; `max_instances=1` (ไม่ซ้อนตัวเอง), `coalesce=True` (หลัง downtime รวมเป็นรอบเดียว),
  ThreadPool 8 workers (source ช้าไม่บล็อก source อื่น), เริ่มแบบเหลื่อมเวลา 7 วินาที/งาน
- job ที่ DISABLED ไม่ถูก schedule; NO_API_KEY / NOT_CONFIGURED ถูกเรียกแต่ไม่ยิง request (health แสดงสถานะชัดเจน)

## 6. Source Health

`OK · DEGRADED · ERROR · UNAVAILABLE (ล้มเหลวติดกัน ≥3) · REQUIRES_INVESTIGATION · NO_API_KEY · NOT_CONFIGURED · DISABLED · STALE (สำเร็จล่าสุดเก่ากว่า interval×3) · NEVER_RUN`
และ `schema_verified` = parser เคยยืนยันกับข้อมูลจริงแล้วหรือยัง (ตอนนี้ false ทั้งหมด — ดู DATA_SOURCES.md)

ดูได้ที่ `GET /health`, `GET /sources`, `GET /sources/{job}/runs`, `python -m app.cli health`

## 7. ความเสี่ยง / สิ่งที่ยังไม่ชัด

ดู `docs/DATA_SOURCES.md` (ต่อแหล่ง) — สรุปสำคัญ:
1. **ยังไม่เคยเรียก API จริงได้จาก environment ที่พัฒนา** (egress ถูกบล็อก) → parser ของ TMD/RID/GISTDA
   เขียนจากเอกสาร/ข้อมูลที่ทราบ, ยืนยัน schema ไม่ได้ → ออกแบบให้ raw ถูกเก็บก่อนเสมอ + reprocess ได้
2. TMD telecom API: ชื่อ/รูปแบบ query param (`date`, `country`, `utc`) และโครง JSON ยังต้องยืนยันจาก api-docs
3. Open-Meteo: model id / meta id (`ecmwf_ifs`, `gfs_global`/`ncep_gfs013`, `jma_gsm`) ต้องยืนยันรอบแรก;
   free API = non-commercial เท่านั้น
4. RID: ชื่อ field, หน่วย (สมมติ MCM, MCM/day ตามแผน — มี sanity check), รูปแบบ URL ย้อนหลัง
5. GISTDA: ต้องสมัคร key; ชื่อ param lat/lon, รูปแบบคำตอบ point-check, endpoint polygon ของ Disaster Platform
6. SYNOP ไม่มีชื่อ/พิกัดสถานี → `weather_station` มีแค่ WMO id จนกว่าจะเติม metadata สถานี
7. JMA GSM / ECMWF ช่วงท้าย เป็น 3–6 ชั่วโมง; Open-Meteo interpolate เป็นรายชั่วโมง → ใช้ `temporal_resolution_seconds`
   ตอนวิเคราะห์ accuracy

## 8. ลำดับการพัฒนา (ที่ทำใน commit นี้)

1. อ่าน Excel ✔ → 2. โครงสร้างโปรเจกต์ ✔ → 3. Schema + Alembic ✔ → 4. Open-Meteo ✔ → 5. TMD ✔ (unverified)
→ 6. RID ✔ (unverified) → 7. GISTDA (อ่าน key จาก .env) ✔ → 8. Scheduler ✔ → 9. Health monitor ✔ → 10. API ✔

ถัดไป (ยังไม่ทำ — อยู่ใน backlog): ยืนยัน schema กับ API จริง, รัน 7 วัน (Backlog #10), Data Quality Report (#11),
สำรวจ BMA / Rain gauge / River / Sea level / DDPM (#5, #6)
