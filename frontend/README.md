# Dashboard (Next.js + TypeScript + Tailwind + MapLibre + ECharts)

ศูนย์ตรวจสอบสถานการณ์น้ำ: **WATER FIRST** → weather explains what may happen next → location helps find what matters.

```bash
cp .env.example .env.local     # BACKEND_URL=http://localhost:8000
npm install
npm run dev                    # http://localhost:3000  (backend must be running)
npm run build && npm run start # production
```

## หลักการ
- เบราว์เซอร์เรียก **`/api/*` ของเราเท่านั้น** Next.js ส่งต่อไป FastAPI (`next.config.ts` rewrites) ไม่มีการเรียก API ภายนอก และไม่มี API key ใน frontend
- ไม่มีข้อมูลตัวอย่าง/ข้อมูลแต่งขึ้นใน production data layer ถ้า backend ยังไม่มีข้อมูล จะแสดง `--` หรือ "ยังไม่เชื่อมต่อ" พร้อมเหตุผล
- ทุกส่วนแสดงความสดของข้อมูล (เวลาของข้อมูล / เวลาที่ดึง / อายุ / LIVE–DELAYED–STALE–OFFLINE) การรีเฟรชหน้าจอ (ทุก 60 วิ) ไม่ได้แปลว่าข้อมูลต้นทางใหม่
- สถานะน้ำ (ปกติ/เฝ้าระวัง/เสี่ยงสูง/วิกฤต) และผลของฝนต่อระดับน้ำ = **การประเมินโดยระบบ** ไม่ใช่ประกาศราชการ; ประกาศทางการแสดงหน่วยงานเสมอ และแยกจากข่าว

## โครงสร้าง
```
src/
  app/                 layout, page, globals.css (design tokens)
  components/
    layout/            Sidebar, Header, SearchBox
    dashboard/         SummaryCards, WatchListPanel, WaterStationTable, StationDetailDrawer, AlertPanel,
                       ReservoirPanel, TidePanel, RainPanel, WeatherPanel, FloodRiskPanel, NewsPanel, NearbyPanel
    map/               WeatherMap (shell) + one component per layer: WaterStation, Rain, Dam, FloodExtent,
                       FloodRisk, Warning, WeatherStation, Basemap (rivers/boundaries), UserLocation;
                       MapLayerControl, MapTimeSelector, RainLegend
    charts/            EChart wrapper, WaterLevelChart, RainComparisonChart
    ui/                Panel, StatusBadge, FreshnessTag, EmptyState, Segmented, Drawer
  services/            api.ts (our backend only) + dashboard / water / weather / flood / warning / news / search
  types/               contracts that mirror the FastAPI responses
  hooks/               usePolling (visibility-aware), useGeolocation (optional)
  utils/ config/       formatting (Asia/Bangkok, พ.ศ.), status colours, rain scale, layer registry
```

## หมายเหตุทางเทคนิค
- MapLibre GL v6 ใช้ worker แบบ ES module: `scripts/copy-maplibre-worker.mjs` คัดลอกไฟล์ worker ไป `public/maplibre/` ก่อน dev/build แล้วตั้ง `setWorkerUrl`
- ถ้า basemap โหลดไม่สำเร็จ แผนที่สลับเป็นพื้นหลังเรียบ และยังแสดงข้อมูลสถานีของเราได้
- Basemap เริ่มต้น: CARTO dark-matter (ไม่ต้องใช้ key; เปลี่ยนได้ที่ `NEXT_PUBLIC_MAP_STYLE_URL`)
