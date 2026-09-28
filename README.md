# Thailand Weather & Flood Intelligence Platform — Phase 0: Data Collection

Phase 0 ทำหน้าที่ดึงข้อมูลจริงจากหลายหน่วยงานมาเก็บในฐานข้อมูลอย่างต่อเนื่อง (**DATA FIRST**)
เพื่อให้หลังรัน 7–30 วันสามารถวิเคราะห์ Forecast Accuracy, Rainfall Error, Model Bias,
Water Level Trend และความสัมพันธ์ระหว่างฝน ระดับน้ำ และพื้นที่น้ำท่วมได้

ขอบเขต: ยังไม่มี Frontend, ยังไม่มี ML และยังไม่คำนวณ Flood Risk
แผนงานอยู่ที่ `docs/Thailand_Weather_Flood_Data_Plan_v0.1.xlsx`

- สถาปัตยกรรม ตาราง ความเสี่ยง และลำดับงาน → [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)
- สถานะและสิ่งที่ต้องยืนยันของแต่ละแหล่งข้อมูล → [docs/DATA_SOURCES.md](docs/DATA_SOURCES.md)
- ตาราง/คอลัมน์ที่เตรียมไว้ให้ Flood Engine → [docs/FLOOD_ENGINE_INPUTS.md](docs/FLOOD_ENGINE_INPUTS.md)

## แหล่งข้อมูลใน Phase 0

| Job | แหล่ง | สถานะ |
|---|---|---|
| `openmeteo.forecast.ECMWF/GFS/JMA` | Open-Meteo (WX-01..03) | พร้อม |
| `openmeteo.historical_forecast` | Open-Meteo Historical Forecast (WX-04) | พร้อม |
| `tmd.synoptic`, `tmd.warning` | TMD telecom API (TMD-01, 03) | พร้อม (ต้องยืนยัน schema) |
| `tmd.metar` | TMD (TMD-02, P1) | ปิดไว้ |
| `rid.dam` | กรมชลประทาน (RID-01) | พร้อม (ต้องยืนยัน schema) |
| `rid.medium_reservoir` | กรมชลประทาน (RID-02, P1) | ปิดไว้ |
| `gistda.flood_point_check`, `gistda.flood_polygon` | GISTDA (GIS-01, 02) | ต้องใช้ API key |

## เริ่มใช้งาน

### แบบ Docker
```bash
cp .env.example .env          # ใส่ GISTDA_API_KEY ถ้ามี
docker compose up -d --build  # db (PostGIS) + migrate + api + scheduler
curl localhost:8000/health
```

### แบบ Local
ต้องมี Python 3.11+ และ PostgreSQL 16 + PostGIS
```bash
python -m venv .venv && . .venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env                      # แก้ DATABASE_URL
python -m app.cli init-db                 # alembic upgrade + ลงทะเบียน job
python -m app.cli collect all             # ทดลองดึงทุกแหล่ง 1 ครั้ง
python -m app.scheduler                   # รันเก็บข้อมูลต่อเนื่อง (process แยก)
uvicorn app.main:app --port 8000          # API ภายใน
```

### คำสั่ง CLI
```bash
python -m app.cli jobs                                  # รายการ job และสถานะการตั้งค่า
python -m app.cli collect tmd.synoptic                  # รัน job เดียว
python -m app.cli health                                # รายงาน health (STATUS / Last Success / Latency)
python -m app.cli backfill-openmeteo --start 2026-09-01 --end 2026-09-27
python -m app.cli backfill-rid --start 2026-09-01 --end 2026-09-27
python -m app.cli reprocess --job rid.dam --failed-only # parse ใหม่จาก raw_payload ไม่เรียก API ซ้ำ
```

## Dashboard (frontend/)

Next.js + TypeScript + Tailwind + MapLibre + ECharts ออกแบบเป็นศูนย์ตรวจสอบสถานการณ์น้ำ (WATER FIRST) รายละเอียดอยู่ใน [frontend/README.md](frontend/README.md)

```bash
docker compose up -d --build   # db + migrate + api + scheduler + web (http://localhost:3000)
```

## Engines (v0.1, คำนวณจากข้อมูลที่เก็บแล้วเท่านั้น, ยังไม่ใช้ ML)
| Engine | ไฟล์ | ทำอะไร |
|---|---|---|
| Forecast Consensus | `app/engines/forecast_consensus.py` | พยากรณ์ของระบบจาก ECMWF/GFS/JMA: consensus, min/max/median, spread, confidence (coverage × agreement), ฝน 1/3/6/12/24/48 ชม. |
| Derived weather | `app/engines/weather_derived.py` | อุณหภูมิที่รู้สึก (Steadman/BoM), สภาพอากาศ |
| Water calc | `app/engines/water_calc.py` | ระยะถึงตลิ่ง, อัตราการขึ้น (least squares), แนวโน้ม, สถานะที่ระบบคำนวณ แยกจากค่าที่ต้นทางกำหนด |
| Water impact | `app/engines/water_impact.py` | ฝนที่คาดการณ์อาจทำให้น้ำขึ้นไหม (เชิงคุณภาพ ไม่มีตัวเลขระดับน้ำในอนาคต) |

พารามิเตอร์ทั้งหมดอยู่ใน `app/config/engines.json` และเกณฑ์ความสดของข้อมูลรายแหล่งอยู่ใน `app/config/freshness.json`

## Dashboard API (`/api/*`, อ่านจาก DB เท่านั้น, cache 30 วิ)
`/api/dashboard/summary` · `/api/sources/health` · `/api/weather/{locations,current,forecast,consensus,stations}` ·
`/api/rainfall` · `/api/rainfall/{comparison,forecast}` · `/api/water/stations` (filters) · `/api/water/stations/{code}?range=6h|24h|3d|7d` ·
`/api/water/{filters,nearby,trend}` · `/api/search?q=` · `/api/reservoirs` · `/api/warnings` · `/api/tide` · `/api/flood/{extent,risk}` · `/api/news`

## Internal API (Phase 0)
| Method | Path | คำอธิบาย |
|---|---|---|
| GET | `/health` | สถานะ DB และสถานะรายแหล่ง (last success, latency) |
| GET | `/sources` | แหล่งข้อมูลทั้ง 18 แห่งตามแผน พร้อม health ของทุก job |
| GET | `/sources/{job}/runs` | ประวัติการรันของ job |
| GET | `/weather/current?location=bangkok` | ค่าตรวจวัดล่าสุด (แยกจากค่าพยากรณ์ของชั่วโมงปัจจุบัน) |
| GET | `/weather/forecast?location=bangkok&model=ECMWF&run=latest&hours=72` | ค่าพยากรณ์รายชั่วโมง |
| GET | `/weather/runs`, `/weather/locations` | model run ที่เก็บไว้ และจุดพยากรณ์ |
| GET | `/reservoirs?date=YYYY-MM-DD` | สถานะเขื่อน |
| GET | `/warnings?since_hours=72` | ประกาศเตือน |
| GET | `/raw/{id}?include_payload=true` | ย้อนดู response ต้นฉบับของข้อมูลแต่ละแถว |

เอกสาร OpenAPI ดูได้ที่ `/docs`

เวลาใน response มีสองรูปแบบ คือ `<field>` เป็น UTC และ `<field>_local` เป็น Asia/Bangkok
ข้อมูลทุกแถวมี `source` และ `raw_payload_id` สำหรับตรวจย้อนกลับไปยังแหล่งต้นทาง

## หลักการสำคัญ
- **ไม่สร้างข้อมูลขึ้นเอง** ถ้าแหล่งข้อมูลเข้าไม่ได้หรืออ่านไม่ออก ระบบจะรายงานสถานะตามจริง ได้แก่
  `ERROR` / `UNAVAILABLE` / `REQUIRES_INVESTIGATION` / `NO_API_KEY` / `NOT_CONFIGURED`
- **Collector แต่ละตัวแยกขาดจากกัน** ถ้า API หนึ่งล่ม collector อื่นยังทำงานต่อได้
- **เก็บข้อมูล 2 ชั้น** คือ `raw_payload` (ต้นฉบับ) และตาราง normalized
  โดยใช้หน่วยมาตรฐาน UTC, mm, °C, km/h, m, m³/s และ MCM
- **แยกเวลาของข้อมูลพยากรณ์** `model_run_time` แยกจาก `forecast_time` และมี `lead_time_hours`

## Tests
```bash
# ต้องมีฐานข้อมูลทดสอบ (PostGIS): TEST_DATABASE_URL
# ค่าเริ่มต้นคือ postgresql+psycopg://flood:flood@localhost:5432/flood_intel_test
pytest
```
payload ที่ใช้ใน test เป็นข้อมูลสังเคราะห์ที่ใช้ทดสอบ parser/storage เท่านั้น และไม่ถูกเขียนลงฐานข้อมูลจริง
