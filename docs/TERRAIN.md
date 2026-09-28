# Terrain / Elevation Intelligence v0.1

บอกว่า "จุดนี้อยู่ต่ำหรือสูงกว่าพื้นที่รอบ ๆ มีแอ่งไหม ทางน้ำอยู่ใกล้แค่ไหน" จากข้อมูลความสูง (DEM) และทางน้ำ (OSM)
ใช้เป็น**ข้อมูลประกอบ**เท่านั้น ไม่ใช่การประเมินความเสี่ยงน้ำท่วม ไม่ให้คะแนน ไม่มีน้ำหนักคงที่ และไม่ใช้ ML

## 1. แหล่งข้อมูล

| | Copernicus DEM GLO-30 | FABDEM V1-2 | OSM waterways |
|---|---|---|---|
| ชนิด | DSM (รวมอาคาร/ต้นไม้) | DTM (ลบอาคาร/ต้นไม้ออกด้วยการประมาณ) | เส้นทางน้ำ (river/canal/stream/drain/ditch/tidal_channel) |
| ความละเอียด | 1 arc-second (~30 ม.) | 1 arc-second (~30 ม.) | เวกเตอร์ |
| ความสูงอ้างอิง | EGM2008 | EGM2008 | - |
| License | Copernicus DEM licence: ใช้ฟรี ใช้เชิงพาณิชย์ได้ ต้องใส่ attribution | **CC BY-NC-SA 4.0 (ห้ามใช้เชิงพาณิชย์)** | ODbL 1.0 |
| ที่มา | AWS Open Data (COG ทีละ 1°×1°) | University of Bristol (zip 10°×10°) | HOT Export Tool ผ่าน HDX (snapshot 2026-05-05) |
| ขนาดสำหรับประเทศไทย | 77 tiles, 2.97 GB | 77 tiles, 1.61 GB (ดึงเฉพาะ tile ที่ใช้จาก zip ด้วย HTTP range) | zip 19 MB, 53,967 เส้น |

การเลือก tile ใช้ขอบเขตประเทศจาก Natural Earth (public domain) ที่ `app/config/thailand_boundary.geojson`
ขยายออก 0.02° ไฟล์นี้ใช้เลือก tile เท่านั้น ไม่ใช่เขตแดนทางการ

**DEM หลัก** กำหนดด้วย `TERRAIN_PRIMARY_DATASET` ค่าเริ่มต้นคือ `fabdem_v1_2` เพราะในเมืองใกล้พื้นดินจริงกว่า
ถ้านำระบบไปใช้เชิงพาณิชย์ ให้ตั้งเป็น `copernicus_glo30` หรือติดต่อขอ license จาก Fathom
ระบบคำนวณจาก**ทั้งสองชุด**เสมอ แล้วนำผลมาเทียบกัน ถ้าไม่ตรงกันจะลดความน่าเชื่อถือลง

## 2. การเก็บข้อมูล
- **ไฟล์ DEM เก็บเป็น GeoTIFF** ที่ `data/dem/<dataset>/<N13E100>.tif` (docker volume `terrain`) ไม่เก็บใน PostGIS raster
  เพราะงานนี้อ่านเฉพาะหน้าต่างเล็ก ๆ รอบจุด การอ่านจากไฟล์จึงเร็วและง่ายกว่า
- **`dem_tile`** บันทึกทุก tile ว่าดึงจาก URL ไหน (และ member ใน zip) ขนาดไฟล์ sha256 เวลาดึง
  และ GeoTIFF tags ตามต้นฉบับ tile ที่ต้นทางไม่มี (ทะเล) บันทึกเป็น `not_at_source` และไม่มีการเติมค่า
- **`terrain_profile`** เก็บผลที่คำนวณไว้แล้วของสถานีวัดน้ำและจุดพยากรณ์ แยกตาม dataset และ `method_version`
  โดยคอลัมน์ `details` เก็บผลเต็มรวมพารามิเตอร์
- **`waterway`** เก็บเส้นทางน้ำ OSM (MultiLineString, GiST) พร้อม `osm_type` / `osm_id` และ `source_snapshot` (เวลา export ของ extract)

## 3. การคำนวณ (`app/engines/terrain.py`)
การอ่านตาม lat/lon ทำโดยหา cell ที่ใกล้ที่สุดบน grid 1″ ทั่วโลก แล้ว copy หน้าต่าง ±1,150 ม. ด้วย integer offset
tile ทั้งสองชุดเป็น pixel-is-point จึงต่อ tile ข้ามขอบได้โดยไม่ resample ส่วนที่เป็นทะเลหรือ nodata จะเป็น NaN

| ค่า | วิธี |
|---|---|
| `elevation_m` | median ของ 3×3 cell รอบจุด |
| `relative_elevation` (250/500/1000 ม.) | ความสูงของจุด ลบ median ของ cell ในวงกลม (ไม่รวม 3×3 กลาง) พร้อม mean, p10, p90 และ percentile rank |
| `terrain_position` ต่อรัศมี | `LOW_AREA` ถ้า rel ≤ −1 ม. **และ** percentile ≤ 25; `HIGH_AREA` ถ้า rel ≥ +1 ม. **และ** ≥ 75; นอกนั้น `NORMAL`; ถ้าเซลล์ที่ใช้ได้ < 60% เป็น `UNKNOWN` |
| `terrain_position` รวม | LOW/HIGH ถ้าได้อย่างน้อย 2 ใน 3 รัศมี, `MIXED` ถ้ามีทั้ง LOW และ HIGH |
| `slope.at_point` | วิธี Horn (1981) บน DEM ที่ผ่าน 3×3 median |
| `slope.plane_fit` | least-squares plane ในรัศมี 250 ม. ให้ทิศลาดลงทั่วไป ถ้าชันน้อยกว่า 2 ม./กม. จะรายงานว่า "ค่อนข้างราบ" |
| `local_depression` | priority-flood fill (Barnes 2014) ในหน้าต่าง 2×2 กม. บน DEM 3×3 median ถือว่าขอบหน้าต่างเป็นทางออกน้ำ ถ้าความลึกที่จุด ≥ 0.5 ม. และแอ่งมีอย่างน้อย 4 cell จะได้ `possible_local_depression` |
| ไม่คำนวณใน v0.1 | `flow_accumulation` (ต้องประมวลผลทั้งลุ่มน้ำ) และ `terrain_drainage_score` (ยังไม่มีข้อมูลตรวจสอบ) |

พารามิเตอร์ทั้งหมดอยู่ใน `app/config/engines.json` → `terrain` และ `waterway_context`
ค่าเหล่านี้เป็นค่าชั่วคราวที่ตั้งเกณฑ์ไว้เท่ากับระดับความคลาดเคลื่อนของ DEM

**ความน่าเชื่อถือ** มีแค่ `low` / `medium` เพราะยังไม่ได้ตรวจสอบกับข้อมูลสำรวจภาคพื้นดิน
ผลจะเป็น `low` เมื่อเกิดข้อใดข้อหนึ่ง:
- ความต่างระดับอยู่ในช่วงความคลาดเคลื่อน
- DEM สองชุดให้ผลไม่ตรงกัน
- มีผลจาก DEM ชุดเดียว
- ผลหลักมาจาก DSM

## 4. ทางน้ำ
`nearby_waterways` หา OSM waterway ในรัศมี 3 กม. เรียงตามระยะ geography และรวมเส้นที่ชื่อซ้ำกันเป็นรายการเดียว
ทุกผลลัพธ์ระบุ `selection_method: distance_based` เพราะ OSM ไม่ได้บอกว่าถนนหรือบ้านหลังนั้นระบายน้ำลงคลองไหน

สถานีวัดน้ำจะถูกผูกกับทางน้ำเฉพาะเมื่อ**ชื่อตรงกัน** (`selection_method: name_match`) ระยะทางอย่างเดียวไม่พอ

## 5. การนำไปใช้กับ Flood Risk
`app/engines/location_context.py` แปลงผลภูมิประเทศเป็น `terrain_signal` 5 แบบ:
- `may_collect_water` (น้ำอาจไหลมารวม/ขังได้ง่ายกว่ารอบข้าง)
- `neutral` (ภูมิประเทศไม่ได้เพิ่มหรือลดโอกาสอย่างชัดเจน)
- `less_likely_to_collect` (น้ำมีแนวโน้มไหลออกมากกว่าไหลเข้า)
- `uncertain` (ข้อมูลยังไม่ชัดพอ)
- `unknown` (ไม่มีข้อมูล)

ถ้า DEM สองชุดไม่ตรงกัน signal จะเป็น `uncertain`

signal นี้แสดงคู่กับเหตุผลด้านน้ำและฝนใน `flood_context` และ `/api/flood/risk` ระบุไว้ใน `prepared_signals` ว่าเป็น `supporting only, no fixed weight`
ข้อความ `summary_th` สร้างจากค่าที่คำนวณได้เท่านั้น ถ้าไม่มีข้อมูลจะบอกว่าไม่มี ไม่ใส่ตัวเลขขึ้นมาเอง

## 6. API
- `GET /api/location/analyze?lat=&lon=&radius_km=10` ให้ข้อมูลรวมของจุดหนึ่ง:
  - `summary_th`, `terrain` (ทั้งสองชุด + comparison + reliability + limits + tiles provenance), `terrain_signal`
  - `waterways`, สถานีวัดน้ำใกล้เคียง, `rain`, `impact`, `flood_context`, `sources` (attribution)
- `GET /api/terrain?lat=&lon=` ให้เฉพาะผลภูมิประเทศแบบเต็ม
- `GET /api/terrain/datasets` ให้สถานะ tile ของแต่ละ dataset, license และ dataset หลัก

## 7. Performance
- อ่าน DEM 1 ชุดต่อ 1 จุด (77×79 cell) พร้อมคำนวณ ใช้เวลาประมาณ 15–60 ms บนเครื่องทดสอบ
- คิวรี waterway ด้วย GiST และ KNN ใช้เวลาประมาณ 5–50 ms
- ผลของจุดที่ผู้ใช้เลือก cache ในหน่วยความจำ 2,048 จุด โดยปัดพิกัดทีละ ~11 ม.
- จุดที่รู้ล่วงหน้า (809 จุด × 2 ชุด) คำนวณล่วงหน้าลง `terrain_profile` ใช้เวลาประมาณ 45 วินาที

## 8. ข้อจำกัด (แสดงใน API ทุกครั้ง)
- DEM 30 ม. คลาดเคลื่อนแนวดิ่งระดับเมตร พื้นที่ราบอย่างกรุงเทพฯ ความต่างที่น้อยกว่า ~1 ม. อาจเป็นแค่ความคลาดเคลื่อน
- DSM รวมอาคาร ส่วน FABDEM ลบออกด้วยการประมาณ สองชุดจึงอาจต่างกันมาก
  - ตัวอย่างที่อยุธยา: Copernicus ให้ผลว่าเป็นที่ต่ำและมีแอ่ง ขณะที่ FABDEM ให้ผลว่าปกติ
- ความสูงอ้างอิง EGM2008 **ไม่ใช่ ม.รทก.** ของไทย จึงห้ามเทียบกับระดับน้ำหรือระดับตลิ่งของสถานีโดยตรง
- ไม่รวมคันกั้นน้ำ ประตูระบายน้ำ ท่อระบายน้ำ และการสูบน้ำ
- สถานีวัดน้ำตั้งอยู่ในร่องน้ำ จึงมักได้ผลเป็น `LOW_AREA` ซึ่งเป็นลักษณะของร่องน้ำเอง ไม่ได้แปลว่าบริเวณนั้นเสี่ยง
- แอ่งที่ใหญ่กว่าหน้าต่าง 2 กม. จะไม่ถูกตรวจพบ
- ข้อมูล OSM เป็นข้อมูลที่อาสาสมัครร่วมกันสร้าง อาจไม่ครบ

## 9. คำสั่ง
```bash
python -m app.cli terrain-download                 # ทั้งสองชุด ทั้งประเทศ (~4.6 GB), ข้ามไฟล์ที่มีแล้ว
python -m app.cli terrain-download --dataset copernicus_glo30 --tile N13E100
python -m app.cli terrain-status
python -m app.cli waterways-import [--refresh]
python -m app.cli terrain-precompute               # หลังจาก collector ดึงรายชื่อสถานีแล้ว
```

## 10. ยังไม่ทำ
- Terrain map layer (hillshade / relative elevation) ตามลำดับงานข้อ 12
- flow accumulation ระดับลุ่มน้ำ (อาจใช้ MERIT Hydro ซึ่งเป็น license non-commercial)
- ตรวจสอบกับจุดน้ำท่วมจริง (GISTDA flood extent เมื่อได้ API key)
