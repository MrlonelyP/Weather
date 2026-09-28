/** Map layer registry. `available` reflects whether a real data source exists today. */
export type LayerId =
  | "water"
  | "river"
  | "rain"
  | "dam"
  | "tide"
  | "floodExtent"
  | "floodRisk"
  | "warning"
  | "weatherStations"
  | "boundaries";

export interface LayerDef {
  id: LayerId;
  label: string;
  defaultOn: boolean;
  /** why a layer cannot show data yet (shown in the layer control) */
  unavailableReason?: string;
}

export const LAYERS: LayerDef[] = [
  { id: "water", label: "สถานีวัดระดับน้ำ", defaultOn: true },
  { id: "river", label: "แม่น้ำ / คลอง", defaultOn: true },
  { id: "rain", label: "ฝน (สถานีวัดฝน)", defaultOn: true },
  { id: "dam", label: "เขื่อนและอ่างเก็บน้ำ", defaultOn: true, unavailableReason: "RID ไม่ให้พิกัดเขื่อน" },
  { id: "tide", label: "น้ำทะเล / น้ำหนุน", defaultOn: false, unavailableReason: "ยังไม่มีแหล่งข้อมูล" },
  { id: "floodExtent", label: "พื้นที่น้ำท่วม (ดาวเทียม)", defaultOn: true, unavailableReason: "GISTDA รอ API key" },
  { id: "floodRisk", label: "พื้นที่เสี่ยงน้ำท่วม (ระบบประเมิน)", defaultOn: false, unavailableReason: "ยังไม่เปิดใช้" },
  { id: "warning", label: "ประกาศเตือนภัย (พื้นที่)", defaultOn: true },
  { id: "weatherStations", label: "สถานีตรวจอากาศ", defaultOn: false },
  { id: "boundaries", label: "จังหวัด / อำเภอ", defaultOn: true },
];
