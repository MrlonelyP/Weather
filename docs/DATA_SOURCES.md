# Data Sources – สถานะการเชื่อมต่อและสิ่งที่ต้องยืนยัน

รายการเต็ม 18 แหล่งอยู่ใน `app/config/source_catalog.json` (ถอดจาก Sheet "Data Sources") และดูสถานะสดได้ที่ `GET /sources`

> **สถานะ ณ วันที่เขียน (2026-09-28):** environment ที่ใช้พัฒนาถูก network policy บล็อกทุกโฮสต์ด้านล่าง
> (proxy ตอบ 403) จึง **ยังไม่มีข้อมูลจริงเข้าฐานข้อมูล** และ `schema_verified=false` ทุก job
> ระบบรายงานสถานะตามจริง (`ERROR`/`UNAVAILABLE`) ไม่มีการสร้างข้อมูลแทน

## ขั้นตอนยืนยันแต่ละแหล่ง (ทำครั้งแรกบนเครื่องที่ออกเน็ตได้)

```bash
python -m app.cli collect <job>                 # ยิงจริง 1 ครั้ง
python -m app.cli health                        # ดูสถานะ
# ถ้า REQUIRES_INVESTIGATION: ดู response ต้นฉบับ
curl 'localhost:8000/raw/<id>?include_payload=true'
# ปรับ parser แล้ว parse ใหม่จาก raw โดยไม่ต้องเรียก API
python -m app.cli reprocess --job <job> --failed-only
```
เมื่อยืนยันกับข้อมูลจริงแล้ว ให้ตั้ง `schema_verified = True` ใน class ของ collector นั้น

---

## WX-01..03 Open-Meteo ECMWF / GFS / JMA — `openmeteo.forecast.*`
- Endpoint: `https://api.open-meteo.com/v1/{ecmwf|gfs|jma}?models=<param>` + model run time จาก
  `https://api.open-meteo.com/data/<meta_id>/static/meta.json` (`last_run_initialisation_time`)
- โครง response เป็นไปตามเอกสาร Open-Meteo (multi-location → JSON array ตามลำดับพิกัด) — ความเสี่ยงต่ำ
- **ต้องยืนยัน**: model id / meta id ค่า default
  | name | param | meta_id |
  |---|---|---|
  | ECMWF | `ecmwf_ifs` (IFS HRES ~9 km ตามแผน) | `ecmwf_ifs` |
  | GFS | `gfs_global` | `ncep_gfs013` |
  | JMA | `jma_gsm` (MSM ไม่ครอบคลุมไทย) | `jma_gsm` |
  ถ้า meta id ผิด job จะเป็น `ERROR` พร้อม HTTP 404 → แก้ `OPENMETEO_MODELS` ใน .env
- ตัวแปร soil moisture ต่างกันต่อโมเดล (`extra_hourly`); ถ้า API ตอบ 400 ระบบ retry โดยตัดตัวแปรเสริมออก (สถานะ `DEGRADED`)
- License: free API = non-commercial; ใช้เชิงพาณิชย์ต้องใส่ `OPENMETEO_API_KEY`

## WX-04 Open-Meteo Historical Forecast — `openmeteo.historical_forecast`
- `https://historical-forecast-api.open-meteo.com/v1/forecast` — series ต่อเนื่องจากหลาย run, ไม่ระบุ run time
  → เก็บ `product=historical_forecast`, `model_run_time=NULL`
- Backfill: `python -m app.cli backfill-openmeteo --start 2026-08-01 --end 2026-09-27`

## TMD-01 Synoptic — `tmd.synoptic`
- `https://telecom.tmd.go.th/api/ftp/synoptic` (Public, JSON, query ตาม date/country/utc) — เอกสาร https://telecom.tmd.go.th/api-docs
- **ต้องยืนยัน**: ชื่อ param + รูปแบบค่า (ตั้งได้ใน .env: `TMD_PARAM_*`, `TMD_DATE_FORMAT`, `TMD_COUNTRY`), โครง JSON
- Parser หา string ที่มี `AAXX` ทุกจุดใน JSON แล้ว decode ตามมาตรฐาน WMO FM-12 (มี unit test)
  → ไม่ขึ้นกับชื่อ field ของ JSON; เก็บเฉพาะสถานี WMO block `48` (ไทย) ปรับได้ `TMD_WMO_PREFIXES`
- ฝน: เก็บพร้อม `rain_period_hours` จากรหัส tR; "trace" ไม่ถูกแปลงเป็นตัวเลข (flag ไว้)
- ยังไม่มีชื่อ/พิกัดสถานี (SYNOP ไม่มี) → ต้องเติม metadata สถานีภายหลัง (เช่น WMO OSCAR / TMD station list)

## TMD-03 Weather Warning — `tmd.warning`
- `https://telecom.tmd.go.th/api/ftp/warning`
- รับเฉพาะรายการที่มี WMO abbreviated heading (เช่น `WSTH31 VTBB 280300`) เพื่อกันข้อความ status/error ของ API
  ไม่ให้กลายเป็น "ประกาศเตือน"; `severity` เก็บเฉพาะเมื่อแหล่งระบุ (ตอนนี้ NULL)
- **ต้องยืนยัน**: โครง JSON และว่า bulletin มี heading หรือไม่

## TMD-02 METAR — `tmd.metar` (P1, ปิดไว้)
- เก็บ raw อย่างเดียว เปิดด้วย `TMD_METAR_ENABLED=true`

## RID-01 เขื่อนขนาดใหญ่ — `rid.dam`
- `https://app.rid.go.th/reservoir/api/dam/public` (+ `/{YYYY-MM-DD}` สำหรับย้อนหลัง — **ต้องยืนยัน** รูปแบบ URL;
  ตั้งได้ `RID_DATE_PATH_FORMAT`) — เอกสาร https://app.rid.go.th/reservoir/api/document/dam
- Parser หา record ที่มี id + name + (storage/%/inflow/outflow) โดยเทียบชื่อ field หลายแบบ (`FIELD_ALIASES` ใน `rid.py`)
- หน่วยตามแผน: MCM, MCM/day → คำนวณ m3/s เพิ่ม; ถ้าค่าใหญ่ผิดปกติ (>50,000) → `REQUIRES_INVESTIGATION` แทนการเดาหน่วย
- Backfill: `python -m app.cli backfill-rid --start 2026-09-01 --end 2026-09-27`

## RID-02 อ่างขนาดกลาง — `rid.medium_reservoir` (P1, ปิดไว้)
- `https://app.rid.go.th/reservoir/api/reservoir/public` เปิดด้วย `RID_MEDIUM_ENABLED=true`

## GIS-01 GISTDA Flood Extent 1 Day (point check) — `gistda.flood_point_check`
- `https://api-gateway.gistda.or.th/api/2.0/resources/gi-service/v1.0/disasters/flood-extent-1day` — ต้องมี API Key
- Key อ่านจาก `GISTDA_API_KEY` ส่งทาง header `GISTDA_API_KEY_HEADER` (default `API-Key`) — **ไม่ถูกบันทึกลง DB**
- ไม่มี key → `NO_API_KEY` (ไม่ยิง request)
- **ต้องยืนยัน**: ชื่อ header, ชื่อ param lat/lon, รูปแบบคำตอบ (รองรับ boolean flag หรือ FeatureCollection)

## GIS-02 GISTDA Disaster Platform Flood — `gistda.flood_polygon`
- endpoint จริงต้องได้จาก https://disaster.gistda.or.th/services/open-api หลังได้ key → ใส่ `GISTDA_FLOOD_POLYGON_URL`
- ยังไม่ใส่ → `NOT_CONFIGURED`; รองรับ GeoJSON FeatureCollection + paging `limit/offset`, เก็บ geometry PostGIS + พื้นที่ km²

## ยังไม่ implement (สำรวจหลังระบบหลักทำงาน — ตาม Backlog #5, #6)
| ID | แหล่ง | สถานะในแผน | หมายเหตุ |
|---|---|---|---|
| BMA-01 | BMA Flood Bangkok | DISCOVER | ต้อง inspect network endpoint |
| BMA-02 | BMA Rain Radar | DISCOVER | nowcast 0–3 ชม. |
| TW-01/02 | ThaiWater Standard Rainfall/Runoff | DISCOVER | เป็นมาตรฐาน ไม่ใช่ endpoint กลาง → ตาราง `water_station`/`water_level_observation` รองรับแล้ว |
| HII-01 | Sea Level / Tide | DISCOVER | ใช้ `water_station.station_kind='tide'` |
| DWR-01 | กรมทรัพยากรน้ำ | DISCOVER | |
| DPM-01 | DDPM / ปภ. | KEY/REQUEST | ใช้ `official_warning.agency='DDPM'` |
