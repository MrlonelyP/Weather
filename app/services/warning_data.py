"""Official warnings for display: agency, derived display severity, validity and SIGMET area.

Severity is NOT stated by the TMD bulletins we collect; the display category is
derived from the bulletin TYPE and flagged as such (severity_basis).
SIGMETs are aviation warnings - shown as information, not as public flood warnings.
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import OfficialWarning
from app.services.normalizer import utcnow

AGENCIES = {
    "TMD": "กรมอุตุนิยมวิทยา", "DDPM": "กรมป้องกันและบรรเทาสาธารณภัย", "RID": "กรมชลประทาน", "GISTDA": "GISTDA",
}
TYPE_DISPLAY = {
    # type: (severity, Thai label)
    "tropical_cyclone": ("warning", "พายุหมุนเขตร้อน"),
    "tropical_cyclone_advisory": ("warning", "ข่าวพายุหมุนเขตร้อน"),
    "warning": ("watch", "ประกาศเตือนสภาพอากาศ"),
    "warning_other": ("watch", "ประกาศเตือน"),
    "sigmet": ("info", "SIGMET (อากาศการบิน)"),
    "tropical_cyclone_sigmet": ("info", "SIGMET พายุหมุนเขตร้อน (การบิน)"),
    "volcanic_ash_sigmet": ("info", "SIGMET เถ้าภูเขาไฟ (การบิน)"),
    "airmet": ("info", "AIRMET (อากาศการบิน)"),
}
PHENOMENA = [(r"\bEMBD TS\b|\bOBSC TS\b|\bFRQ TS\b|\bSQL TS\b|\bTS\b", "พายุฝนฟ้าคะนอง"),
             (r"\bSEV TURB\b", "ความปั่นป่วนรุนแรง"), (r"\bTC\b", "พายุหมุนเขตร้อน"), (r"\bVA\b", "เถ้าภูเขาไฟ")]
VALID_RE = re.compile(r"VALID\s+(\d{2})(\d{2})(\d{2})/(\d{2})(\d{2})(\d{2})")
COORD_RE = re.compile(r"([NS])(\d{2})(\d{2})\s+([EW])(\d{3})(\d{2})")


def _day_time(ref: datetime, day: int, hour: int, minute: int) -> datetime | None:
    for back in range(0, 2):
        month, year = ref.month - back, ref.year
        if month == 0:
            month, year = 12, year - 1
        try:
            t = datetime(year, month, day, hour, minute, tzinfo=timezone.utc)
        except ValueError:
            continue
        if t <= ref + timedelta(days=2):
            return t
    return None


def parse_sigmet(body: str, issued_at: datetime | None) -> dict:
    out: dict = {"valid_from": None, "valid_to": None, "area": None, "cancelled": bool(re.search(r"\bCNL\b", body))}
    ref = issued_at or utcnow()
    m = VALID_RE.search(body)
    if m:
        d1, h1, n1, d2, h2, n2 = map(int, m.groups())
        out["valid_from"] = _day_time(ref, d1, h1, n1)
        out["valid_to"] = _day_time(ref, d2, h2, n2)
    pts = []
    for ns, lat_d, lat_m, ew, lon_d, lon_m in COORD_RE.findall(body):
        lat = int(lat_d) + int(lat_m) / 60
        lon = int(lon_d) + int(lon_m) / 60
        pts.append([round(-lon if ew == "W" else lon, 4), round(-lat if ns == "S" else lat, 4)])
    if len(pts) >= 3:
        if pts[0] != pts[-1]:
            pts.append(pts[0])
        out["area"] = {"type": "Polygon", "coordinates": [pts]}
    phen = [label for pattern, label in PHENOMENA if re.search(pattern, body)]
    out["phenomenon_th"] = phen[0] if phen else None
    fir = re.search(r"\b([A-Z]+) FIR\b", body)
    out["fir"] = f"{fir.group(1).title()} FIR" if fir else None
    return out


def warning_view(w: OfficialWarning, now: datetime) -> dict:
    severity, type_label = TYPE_DISPLAY.get(w.warning_type or "", ("info", "ประกาศ"))
    body = w.body or ""
    parsed = parse_sigmet(body, w.issued_at) if (w.warning_type or "").endswith("sigmet") else {}
    valid_from = parsed.get("valid_from") or w.effective_from
    valid_to = parsed.get("valid_to") or w.effective_to
    if parsed.get("cancelled"):
        active = False
    elif valid_from and valid_to:
        active = valid_from <= now <= valid_to
    else:
        active = w.issued_at is not None and now - w.issued_at <= timedelta(hours=24)
    title = type_label
    if parsed.get("phenomenon_th"):
        title = f"{parsed['phenomenon_th']} · {type_label}"
    if parsed.get("cancelled"):
        title = f"ยกเลิกประกาศ · {type_label}"
    return {
        "id": w.id, "agency_code": w.agency, "agency_name": AGENCIES.get(w.agency, w.agency),
        "official": True, "type": w.warning_type, "type_label": type_label,
        "severity": severity, "severity_basis": "derived_from_bulletin_type",
        "title": title, "area_text": parsed.get("fir") or w.area_text,
        "area_geojson": parsed.get("area"),
        "issued_at": w.issued_at, "valid_from": valid_from, "valid_to": valid_to, "active": active,
        "bulletin_header": w.bulletin_header, "body": body, "raw_payload_id": w.raw_payload_id,
        "source": w.source, "ingested_at": w.ingested_at,
    }


def recent_warnings(session: Session, hours: int = 48, limit: int = 50, now: datetime | None = None) -> list[dict]:
    now = now or utcnow()
    since = now - timedelta(hours=hours)
    rows = session.execute(
        select(OfficialWarning)
        .where(func.coalesce(OfficialWarning.issued_at, OfficialWarning.ingested_at) >= since)
        .order_by(func.coalesce(OfficialWarning.issued_at, OfficialWarning.ingested_at).desc())
        .limit(limit)).scalars()
    return [warning_view(w, now) for w in rows]
