"""Forecast Impact v0.1: may the coming rain raise the water level at a station?

Qualitative only. We do NOT have a hydrological model, so this never outputs a
future water level number. It combines:
  - the station's current state (trend, rate of rise, distance to bank)
  - observed rain around the station (gauges, last 24 h)
  - our consensus rain forecast for the nearest forecast point (next 6 / 24 h, with confidence)
and returns one of:
  likely_rise        มีแนวโน้มว่าระดับน้ำจะเพิ่มขึ้น
  possible_rise      ระดับน้ำอาจเพิ่มขึ้น หากฝนตกตามคาดการณ์
  no_signal          ยังไม่พบสัญญาณว่าระดับน้ำจะเพิ่มขึ้นจากฝนในช่วงถัดไป
  insufficient_data  ข้อมูลยังไม่เพียงพอสำหรับคาดการณ์ระดับน้ำ
"""
from __future__ import annotations

LABELS = {
    "likely_rise": "มีแนวโน้มว่าระดับน้ำจะเพิ่มขึ้น",
    "possible_rise": "ระดับน้ำอาจเพิ่มขึ้น หากฝนตกตามคาดการณ์",
    "no_signal": "ยังไม่พบสัญญาณว่าระดับน้ำจะเพิ่มขึ้นจากฝนในช่วงถัดไป",
    "insufficient_data": "ข้อมูลยังไม่เพียงพอสำหรับคาดการณ์ระดับน้ำ",
}
# rain thresholds (mm); 24 h classes follow TMD (moderate 10.1-35, heavy 35.1-90)
LIGHT_6H, MODERATE_6H, HEAVY_6H = 1.0, 5.0, 20.0
MODERATE_24H, HEAVY_24H = 10.0, 35.0
MIN_CONFIDENCE = 0.4
WET_OBSERVED_24H = 10.0
NEAR_BANK_M = 1.0


def assess(state: dict | None, rain_6h: dict | None, rain_24h: dict | None,
           observed_24h_max_mm: float | None, forecast_point: dict | None) -> dict:
    reasons: list[str] = []
    base = {"basis": "qualitative_v0.1 - ไม่มีการพยากรณ์ตัวเลขระดับน้ำ",
            "disclaimer": "การประเมินเบื้องต้นโดยระบบ ไม่ใช่ประกาศทางราชการ", "forecast_point": forecast_point,
            "inputs": {"rain_6h": rain_6h, "rain_24h": rain_24h, "observed_24h_max_mm": observed_24h_max_mm}}
    have_forecast = bool(rain_6h and rain_6h.get("consensus") is not None)
    have_state = bool(state and (state.get("trend") is not None or state.get("distance_to_bank_m") is not None))
    if not have_forecast or not have_state:
        if not have_forecast:
            reasons.append("ยังไม่มีฝนคาดการณ์สำหรับบริเวณสถานีนี้ (ระบบพยากรณ์ครอบคลุมพื้นที่ทดสอบเท่านั้น)")
        if not have_state:
            reasons.append("ข้อมูลแนวโน้มหรือระดับตลิ่งของสถานีไม่พอ")
        return {**base, "outlook": "insufficient_data", "label_th": LABELS["insufficient_data"], "reasons": reasons}

    r6, c6 = rain_6h["consensus"], rain_6h.get("confidence") or 0.0
    r24 = rain_24h.get("consensus") if rain_24h else None
    trusted = c6 >= MIN_CONFIDENCE
    heavy = trusted and (r6 >= HEAVY_6H or (r24 is not None and r24 >= HEAVY_24H))
    moderate = r6 >= MODERATE_6H or (r24 is not None and r24 >= MODERATE_24H)
    rising = state.get("trend") == "rising"
    distance = state.get("distance_to_bank_m")
    near_bank = distance is not None and distance <= NEAR_BANK_M
    wet = observed_24h_max_mm is not None and observed_24h_max_mm >= WET_OBSERVED_24H

    if moderate:
        reasons.append(f"คาดว่าฝน 6 ชม. ข้างหน้าประมาณ {r6:.1f} มม." + (f", 24 ชม. {r24:.1f} มม." if r24 is not None else "")
                       + f" (ความมั่นใจ {c6 * 100:.0f}%)")
    if rising:
        reasons.append(f"ระดับน้ำกำลังเพิ่มขึ้น {state.get('rate_cm_per_h')} ซม./ชม.")
    if near_bank:
        reasons.append(f"ระดับน้ำเหลืออีก {distance * 100:.0f} ซม. ถึงตลิ่ง" if distance > 0
                       else "ระดับน้ำถึงหรือเกินตลิ่งแล้ว")
    if wet:
        reasons.append(f"ฝนตกสะสมรอบสถานีใน 24 ชม. ที่ผ่านมาสูงสุด {observed_24h_max_mm:.1f} มม.")

    some_rain = r6 >= LIGHT_6H
    if (rising and (moderate or wet)) or (heavy and (near_bank or rising)):
        outlook = "likely_rise"
    elif moderate or rising or heavy or (some_rain and (near_bank or wet)):
        outlook = "possible_rise"
        if some_rain and not moderate:
            reasons.append(f"คาดว่ามีฝนเล็กน้อยใน 6 ชม. ข้างหน้า ({r6:.1f} มม.) ขณะที่ระดับน้ำสูงหรือพื้นที่ฝนตกชุก")
    else:
        outlook = "no_signal"
        reasons.append(f"ฝนคาดการณ์ 6 ชม. น้อย ({r6:.1f} มม.) และระดับน้ำ{state.get('trend_label_th', '')}")
    if not trusted and moderate:
        reasons.append("โมเดลพยากรณ์ยังเห็นไม่ตรงกัน ความมั่นใจต่ำ")
    return {**base, "outlook": outlook, "label_th": LABELS[outlook], "reasons": reasons}
