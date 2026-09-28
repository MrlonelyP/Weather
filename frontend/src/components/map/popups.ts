import type { WaterStation } from "@/types/water";
import { fmtDistance, fmtNum, fmtSigned, fmtTime } from "@/utils/format";
import { TREND, trendKey, WATER_STATUS } from "@/utils/status";

/** Popup built with DOM APIs (textContent only - API strings are never parsed as HTML). */
export function buildStationPopup(st: WaterStation, onDetail: () => void): HTMLElement {
  const root = document.createElement("div");
  root.style.cssText = "display:grid;gap:8px;min-width:230px;font-size:13px;line-height:1.45";
  const el = (tag: string, text: string, css = "") => {
    const e = document.createElement(tag);
    e.textContent = text;
    if (css) e.style.cssText = css;
    return e;
  };
  const status = WATER_STATUS[st.status];
  const head = document.createElement("div");
  head.append(el("div", st.name ?? st.station_code, "font-weight:600;font-size:14.5px"));
  head.append(el("div", [st.river, [st.amphoe, st.province].filter(Boolean).join(", ")].filter(Boolean).join(" · "), "color:#8298b0;font-size:12px"));
  root.append(head);
  const badge = el("span", `● ${status.label} (ระบบประเมิน)`, `color:${status.color};font-weight:600;font-size:12px`);
  root.append(badge);

  const grid = document.createElement("div");
  grid.style.cssText = "display:grid;grid-template-columns:auto 1fr;gap:3px 12px";
  const refLabel = st.warning_level_m !== null ? "ระดับเฝ้าระวัง" : "ระดับตลิ่ง";
  const refValue = st.warning_level_m ?? st.bank_m;
  const remaining = st.warning_level_m !== null ? st.distance_to_warning_m : st.distance_to_bank_m;
  const trend = TREND[trendKey(st.trend)];
  const rows: [string, string, string?][] = [
    ["ระดับน้ำ", `${fmtNum(st.current_m, 2)} ม.`],
    [refLabel, refValue === null ? "--" : `${fmtNum(refValue, 2)} ม.`],
    ["เหลือถึงระดับนี้", fmtDistance(remaining)],
    ["แนวโน้ม", trend.label, trend.color],
    ["อัตราเปลี่ยนแปลง", st.rate_cm_per_h === null ? "--" : `${fmtSigned(st.rate_cm_per_h, 1)} ซม./ชม.`],
    ["อัตราการไหล", st.discharge_m3s === null ? "--" : `${fmtNum(st.discharge_m3s, 1)} ลบ.ม./วิ`],
    ["เวลาตรวจวัด", `${fmtTime(st.observed_at)} น.`],
    ["แหล่งข้อมูล", "ThaiWater"],
  ];
  for (const [k, v, color] of rows) {
    grid.append(el("span", k, "color:#8298b0"));
    grid.append(el("span", v, `font-variant-numeric:tabular-nums;${color ? `color:${color};font-weight:600` : ""}`));
  }
  root.append(grid);
  if (st.reference_note) root.append(el("div", st.reference_note, "color:#facc15;font-size:11.5px"));
  if (st.source_assessment?.diff_to_bank_text) {
    root.append(el("div", `ต้นทางระบุ: ${st.source_assessment.diff_to_bank_text} ${fmtNum(st.source_assessment.diff_to_bank_m, 2)}`, "color:#8298b0;font-size:11.5px"));
  }
  const btn = el("button", "ดูกราฟและรายละเอียด",
    "margin-top:2px;background:#3097f3;color:#fff;border:0;border-radius:8px;padding:6px 10px;font-weight:600;cursor:pointer;font-family:inherit");
  btn.addEventListener("click", onDetail);
  root.append(btn);
  return root;
}
