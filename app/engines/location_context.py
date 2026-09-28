"""Location Intelligence v0.1: explain a point in plain Thai from computed data only.

Inputs are results other parts of the system already computed (terrain engine,
nearest OSM waterways, water station states, rain gauges, consensus forecast,
forecast impact). This module only turns them into:
  - terrain_signal: how the ground may affect water at this point (a supporting
    signal for a future Flood Risk engine; descriptive, no weight or score)
  - flood_context: reasons from water / rain / terrain, side by side
  - summary_th: short sentences for the dashboard
Every sentence is built from a value in the inputs; when an input is missing the
text says so instead of guessing.
"""
from __future__ import annotations

SIGNAL_TH = {
    "may_collect_water": "ภูมิประเทศเอื้อให้น้ำไหลมารวมหรือขังได้ง่ายกว่าพื้นที่รอบข้าง",
    "neutral": "ระดับพื้นใกล้เคียงพื้นที่รอบข้าง ภูมิประเทศไม่ได้เพิ่มหรือลดโอกาสน้ำขังอย่างชัดเจน",
    "less_likely_to_collect": "พื้นที่สูงกว่าบริเวณรอบข้าง น้ำมีแนวโน้มไหลออกมากกว่าไหลเข้า",
    "uncertain": "ข้อมูลภูมิประเทศยังไม่ชัดเจนพอจะสรุป",
    "unknown": "ไม่มีข้อมูลภูมิประเทศที่ตำแหน่งนี้",
}
DISCLAIMER = "ข้อมูลประกอบการตัดสินใจที่ระบบคำนวณ ไม่ใช่การประเมินความเสี่ยงน้ำท่วมและไม่ใช่ประกาศทางราชการ"


def _fmt_m(v: float) -> str:
    return f"{abs(v):.1f} ม."


def _area_text(dep: dict) -> str:
    rai = dep.get("area_rai")
    return f" ครอบคลุมประมาณ {rai:,.0f} ไร่" if rai and rai >= 1 else ""


def terrain_signal(terrain: dict) -> dict:
    if not terrain or not terrain.get("available"):
        return {"signal": "unknown", "label_th": SIGNAL_TH["unknown"], "reasons": [], "reliability": "none"}
    primary = terrain["datasets"][terrain["primary_dataset"]]
    cmp_ = terrain.get("comparison", {})
    rel = primary["relative_elevation"]
    dep = primary["local_depression"]
    position = primary["terrain_position"]
    name = primary["dataset"]["name"]
    reasons: list[str] = []
    r500 = rel.get("500", {})
    if r500.get("relative_m") is not None:
        word = "ต่ำกว่า" if r500["relative_m"] < 0 else "สูงกว่า"
        reasons.append(f"จุดนี้{word}ค่ากลางของพื้นที่ในรัศมี 500 ม. ประมาณ {_fmt_m(r500['relative_m'])} "
                       f"(พื้นที่รอบ ๆ {r500['percentile_rank']:.0f}% ต่ำกว่าจุดนี้, {name})")
    if dep.get("possible_local_depression"):
        reasons.append(f"พบลักษณะแอ่งที่อาจกักน้ำ ลึกประมาณ {dep['depth_m']:.1f} ม.{_area_text(dep)}")
    disagree = cmp_.get("position_agree") is False or cmp_.get("depression_agree") is False
    if position == "LOW_AREA" or dep.get("possible_local_depression"):
        signal = "may_collect_water"
    elif position == "HIGH_AREA":
        signal = "less_likely_to_collect"
    elif position == "NORMAL":
        signal = "neutral"
    else:
        signal = "uncertain"
    if disagree:
        reasons.append(cmp_.get("note") or "DEM สองชุดให้ผลไม่ตรงกัน")
        if signal != "neutral":
            signal = "uncertain"
    if r500.get("within_noise") and signal == "neutral":
        reasons.append("ความต่างระดับอยู่ในช่วงความคลาดเคลื่อนของ DEM (~1 ม.)")
    return {"signal": signal, "label_th": SIGNAL_TH[signal], "reasons": reasons,
            "reliability": terrain.get("reliability", {}).get("level"),
            "use": "สัญญาณประกอบสำหรับ Flood Risk เท่านั้น ไม่มีน้ำหนักคงที่และไม่ใช่คะแนน"}


def _water_reasons(stations: list[dict]) -> tuple[list[str], dict | None]:
    measured = [s for s in stations if s.get("current_m") is not None]
    if not measured:
        return (["ไม่มีสถานีวัดระดับน้ำที่มีค่าล่าสุดในรัศมีที่ค้นหา"] if stations is not None else []), None
    order = {"CRITICAL": 0, "WARNING": 1, "WATCH": 2, "NORMAL": 3, "UNKNOWN": 4}
    worst = sorted(measured, key=lambda s: (order.get(s.get("status"), 5), s.get("distance_km") or 99))[0]
    txt = f"สถานีวัดน้ำ {worst.get('name') or worst['station_code']} ห่าง {worst.get('distance_km')} กม.: " \
          f"{worst.get('status_label_th') or worst.get('status')}"
    if worst.get("distance_to_bank_m") is not None:
        d = worst["distance_to_bank_m"]
        txt += f", {'เหลืออีก' if d > 0 else 'เกินตลิ่ง'} {abs(d):.2f} ม. {'ถึงตลิ่ง' if d > 0 else ''}".rstrip()
    if worst.get("trend_label_th"):
        txt += f", แนวโน้ม{worst['trend_label_th']}"
    return [txt], worst


def build(terrain: dict, waterways: dict, stations: list[dict] | None, rain: dict, impact: dict | None) -> dict:
    ts = terrain_signal(terrain)
    water_reasons, focus = _water_reasons(stations or [])
    rain_reasons: list[str] = []
    obs = rain.get("observed_24h_max_mm")
    if obs is not None:
        rain_reasons.append(f"ฝนสะสม 24 ชม. ที่สถานีวัดฝนใกล้เคียงสูงสุด {obs:.1f} มม.")
    else:
        rain_reasons.append("ไม่มีค่าฝนจากสถานีวัดฝนใกล้เคียงในชั่วโมงล่าสุด")
    f6 = (rain.get("forecast") or {}).get("rain_6h")
    if f6 and f6.get("consensus") is not None:
        rain_reasons.append(f"ฝนคาดการณ์ 6 ชม. ข้างหน้า {f6['consensus']:.1f} มม. (ความมั่นใจ {f6.get('confidence', 0) * 100:.0f}%)")
    else:
        rain_reasons.append("ยังไม่มีฝนคาดการณ์ของระบบสำหรับบริเวณนี้")

    summary: list[str] = []
    if terrain.get("available"):
        primary = terrain["datasets"][terrain["primary_dataset"]]
        summary.append(f"ระดับพื้นโดยประมาณ {primary['elevation_m']:.1f} ม. (อ้างอิง EGM2008 จาก {primary['dataset']['name']})")
        summary.append(f"ภูมิประเทศ: {terrain['terrain_position_th']} — {ts['label_th']}")
        summary += ts["reasons"]
        slope = (primary["slope"].get("plane_fit") or {})
        if slope.get("downslope_direction_th"):
            summary.append(f"พื้นลาดลงไปทาง{slope['downslope_direction_th']} ประมาณ {slope['gradient_m_per_km']:.1f} ม. ต่อ กม.")
        elif slope.get("note"):
            summary.append(f"ความลาด: {slope['note']}")
    else:
        summary.append(ts["label_th"])
    if waterways.get("available") and waterways.get("nearest"):
        n = waterways["nearest"]
        label = n["name"] or f"{n['waterway_type_th']}ไม่มีชื่อใน OSM"
        summary.append(f"ทางน้ำที่ใกล้ที่สุด: {label} ({n['waterway_type_th']}) ห่างประมาณ {n['distance_m']:,} ม.")
        named = waterways.get("nearest_named")
        if named and named is not n:
            summary.append(f"ทางน้ำที่มีชื่อใกล้ที่สุด: {named['name']} ห่างประมาณ {named['distance_m']:,} ม.")
        summary.append("(เลือกจากระยะทาง ยังไม่ยืนยันว่าพื้นที่นี้ระบายน้ำลงทางน้ำดังกล่าว)")
    summary += water_reasons
    if impact and impact.get("label_th"):
        summary.append(f"ผลของฝนต่อระดับน้ำ: {impact['label_th']}")

    return {
        "terrain_signal": ts,
        "flood_context": {
            "water": water_reasons, "rain": rain_reasons, "terrain": [ts["label_th"], *ts["reasons"]],
            "impact_outlook": impact.get("outlook") if impact else None,
            "focus_station": focus.get("station_code") if focus else None,
            "disclaimer": DISCLAIMER,
        },
        "summary_th": summary,
    }
