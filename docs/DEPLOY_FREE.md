# ติดตั้งแบบฟรี (ไม่ต้องเปิดคอมทิ้งไว้)

ระบบแบ่งเป็น 4 ส่วน แต่ละส่วนใช้บริการฟรีคนละเจ้า:

| ส่วน | ใช้บริการ | ไฟล์ในโปรเจกต์ |
|---|---|---|
| ฐานข้อมูล PostgreSQL + PostGIS | **Neon** (free) | - |
| ดึงข้อมูลทุกชั่วโมง, เก็บ feature, ลบข้อมูลเก่า | **GitHub Actions** (repo public = ใช้ฟรี) | `.github/workflows/collect.yml`, `setup-data.yml` |
| API (FastAPI) | **Render** (free web service) | `render.yaml`, `Dockerfile` |
| หน้าเว็บ (Next.js) | **Vercel** (Hobby) | `frontend/` |

ทุกเจ้าสมัครด้วยบัญชี GitHub ได้ **ถ้าเว็บไหนขอบัตรเครดิต ให้หยุดก่อนแล้วถามก่อน**
เงื่อนไขแพ็กเกจฟรีเปลี่ยนได้ ตัวเลขในหน้านี้อ้างอิงจากข้อมูล ณ ตอนเขียน

## ขั้นตอน
1. **Neon:** สมัครที่ neon.tech แล้วสร้างโปรเจกต์ (เลือก region ใกล้ไทย เช่น Singapore)
   กด **Connect** แล้วคัดลอก connection string ที่ขึ้นต้นด้วย `postgresql://` และมี `sslmode=require`
2. **GitHub:** ไปที่ repo → **Settings → Secrets and variables → Actions → New repository secret**
   - Name: `DATABASE_URL`
   - Secret: วาง connection string จากข้อ 1
3. **GitHub:** ไปที่แท็บ **Actions** แล้วเลือก workflow **setup-data** → **Run workflow**
   - ใช้เวลาประมาณ 20–40 นาที
   - workflow นี้จะสร้างตาราง ดึงรายชื่อสถานี นำเข้าทางน้ำและลุ่มน้ำ คำนวณภูมิประเทศของสถานี และผูกสถานีกับแม่น้ำ
   - พอเสร็จแล้ว workflow **collect** จะรันเองทุกชั่วโมง
4. **Render:** สมัครที่ render.com → **New → Blueprint** → เลือก repo นี้ ระบบจะอ่านไฟล์ `render.yaml` เอง
   - ใส่ `DATABASE_URL` (ค่าเดียวกับข้อ 1) แล้วกด **Apply**
   - รอ build เสร็จ จะได้ URL เช่น `https://thai-flood-api.onrender.com`
   - ลองเปิด `<URL>/health` ถ้าเห็น `"database":"OK"` แปลว่าใช้งานได้
5. **Vercel:** สมัครที่ vercel.com → **Add New → Project** → import repo นี้
   - **Root Directory:** `frontend`
   - **Environment Variables:** `BACKEND_URL` = URL ของ Render จากข้อ 4 (ไม่ต้องมี `/` ท้าย)
   - กด **Deploy** จะได้ลิงก์เว็บ เช่น `https://ชื่อโปรเจกต์.vercel.app` ซึ่งเป็นลิงก์ที่ส่งให้คนอื่นเปิดดูได้
6. **(ไม่บังคับ) กันไม่ให้ API หลับ:** ไปที่ GitHub → Settings → Secrets and variables → Actions → **Variables** → New variable
   - `API_URL` = URL ของ Render
   - workflow **keepalive** จะเรียก API ทุก 10 นาที

## การตั้งค่าที่ใช้ในโหมดฟรี (อยู่ใน `collect.yml`)
ฐานข้อมูลฟรีจุได้ประมาณ 0.5 GB จึงลบข้อมูลเก่าอัตโนมัติ ทั้งระบบใช้พื้นที่ประมาณ 300–350 MB

| ค่า | เก็บไว้ |
|---|---|
| `RETENTION_WATER_LEVEL_DAYS=8` | ระดับน้ำ 8 วัน (กราฟย้อนหลังได้ 7 วัน) |
| `RETENTION_RAIN_GAUGE_DAYS=2` | ฝนจากสถานีวัดฝน 2 วัน |
| `RETENTION_RAW_PAYLOAD_DAYS=1` | response ต้นฉบับ 1 วัน |
| `RETENTION_FORECAST_DAYS=3` | ผลพยากรณ์ 3 วัน |
| `FEATURES_STATION_SCOPE=key`, `FEATURES_HORIZONS=1,3,6` | เก็บชุดข้อมูลฝึก Water Forecast เฉพาะสถานีหลัก (~197 แห่ง) |
| `HYDRO_LEVELS=5,7,12` | ขอบเขตลุ่มน้ำเฉพาะ 3 ระดับที่ใช้จริง |

**ชุดข้อมูลฝึก Water Forecast:**
- ทุกวันเวลา 03:07 น. (ไทย) แถวที่เก่ากว่า 1 วันจะถูก export เป็นไฟล์ `.jsonl.gz` และอัปโหลดไว้ใน GitHub Release ชื่อ **training-data**
- หลังอัปโหลดสำเร็จจึงค่อยลบออกจากฐานข้อมูล ข้อมูลจึงสะสมได้โดยไม่เต็มฐานข้อมูล

## สิ่งที่โหมดฟรีทำไม่ได้
- **ไม่มีไฟล์ DEM บนเซิร์ฟเวอร์ API:** การวิเคราะห์ภูมิประเทศและทิศทางน้ำของจุดที่ผู้ใช้เลือกจะแสดงว่า "เซิร์ฟเวอร์นี้ไม่ได้ติดตั้งไฟล์ DEM"
  - ภูมิประเทศของสถานีวัดน้ำยังมี เพราะคำนวณไว้ล่วงหน้าตอนรัน setup-data
  - พื้นที่รับน้ำ ทางน้ำที่เกี่ยวข้อง และสถานีที่เกี่ยวข้องยังใช้ได้ครบ
- **API ของ Render จะหลับเมื่อไม่มีคนใช้ประมาณ 15 นาที:** คนแรกที่เปิดเว็บอาจต้องรอประมาณ 30–60 วินาที (ขั้นตอนที่ 6 ช่วยลดปัญหานี้)
- **GitHub หยุด workflow ที่ตั้งเวลาไว้** ถ้า repo ไม่มีความเคลื่อนไหว 60 วัน ต้องกดเปิดใหม่ที่แท็บ Actions
- **รอบการดึงข้อมูลไม่ตรงนาที:** GitHub อาจเริ่มรอบรายชั่วโมงช้าไปหลายนาที ข้อมูลจึง "เกือบเรียลไทม์" ช้ากว่าแบบมีเซิร์ฟเวอร์ของตัวเองเล็กน้อย
- **Open-Meteo อาจจำกัดจำนวนครั้ง:** เครื่องของ GitHub ใช้ IP ร่วมกับผู้ใช้อื่น ระบบจะแสดงสถานะ `RATE_LIMITED` ตามจริง ไม่เติมข้อมูลขึ้นเอง
