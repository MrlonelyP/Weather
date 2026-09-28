const TZ = "Asia/Bangkok";

const dateTimeFmt = new Intl.DateTimeFormat("th-TH", {
  timeZone: TZ, day: "numeric", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit",
});
const timeFmt = new Intl.DateTimeFormat("th-TH", { timeZone: TZ, hour: "2-digit", minute: "2-digit" });
const dayTimeFmt = new Intl.DateTimeFormat("th-TH", {
  timeZone: TZ, day: "numeric", month: "short", hour: "2-digit", minute: "2-digit",
});
const hourFmt = new Intl.DateTimeFormat("en-GB", { timeZone: TZ, hour: "2-digit", hour12: false });

/** 28 ก.ย. 2569 10:30 น. (Asia/Bangkok, Buddhist year) */
export function fmtDateTime(iso: string | null | undefined): string {
  return iso ? `${dateTimeFmt.format(new Date(iso))} น.` : "--";
}
export function fmtTime(iso: string | null | undefined): string {
  return iso ? timeFmt.format(new Date(iso)) : "--";
}
export function fmtDayTime(iso: string | null | undefined): string {
  return iso ? `${dayTimeFmt.format(new Date(iso))} น.` : "--";
}
export function fmtHour(iso: string): string {
  return `${hourFmt.format(new Date(iso))}:00`;
}

export function fmtNum(v: number | null | undefined, digits = 1): string {
  if (v === null || v === undefined || Number.isNaN(v)) return "--";
  return v.toLocaleString("th-TH", { minimumFractionDigits: digits, maximumFractionDigits: digits });
}

export function fmtSigned(v: number | null | undefined, digits = 1): string {
  if (v === null || v === undefined) return "--";
  const s = fmtNum(Math.abs(v), digits);
  return v > 0 ? `+${s}` : v < 0 ? `−${s}` : s;
}

/** metres -> "28 ซม." / "1.20 ม." for distances to bank */
export function fmtDistance(m: number | null | undefined): string {
  if (m === null || m === undefined) return "--";
  const abs = Math.abs(m);
  const txt = abs < 1 ? `${Math.round(abs * 100)} ซม.` : `${fmtNum(abs, 2)} ม.`;
  return m < 0 ? `เกิน ${txt}` : txt;
}

export function fmtAge(minutes: number | null | undefined): string {
  if (minutes === null || minutes === undefined) return "--";
  const m = Math.round(minutes);
  if (m < 60) return `${m} นาที`;
  const h = Math.floor(m / 60);
  if (h < 48) return m % 60 ? `${h} ชม. ${m % 60} นาที` : `${h} ชม.`;
  return `${Math.floor(h / 24)} วัน`;
}

export function minutesSince(iso: string | null | undefined, now = Date.now()): number | null {
  return iso ? (now - new Date(iso).getTime()) / 60000 : null;
}
