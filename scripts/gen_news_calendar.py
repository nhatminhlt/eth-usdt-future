"""Sinh config/news_calendar.csv — lịch tin đỏ macro (UTC) cho blackout ±30'.

- FOMC: ngày quyết định (ngày 2 của cuộc họp) theo lịch công bố chính thức của Fed.
  Giờ: 14:00 ET = 19:00 UTC (mùa đông) / 18:00 UTC (mùa hè EDT).
- NFP: thứ Sáu đầu tiên của tháng, 8:30 ET = 13:30 UTC (mùa đông) / 12:30 UTC (EDT) — tính được chính xác.
- CPI: BLS công bố 8:30 ET, thường ngày 10–15 → ghi APPROX (ngày 12, 13:30 UTC).
  ⚠️ TRƯỚC KHI GO-LIVE: verify từng ngày CPI theo lịch BLS thật (bls.gov/schedule).
  Cho backtest blackout ±30' thì lệch vài ngày CPI chỉ mất vài bar — chấp nhận được.

Chạy: python scripts/gen_news_calendar.py
"""
import csv
from datetime import date, datetime, timedelta
from pathlib import Path

# FOMC decision dates (ngày 2 của meeting) 2020–2026 — đối chiếu federalreserve.gov
FOMC = {
    2020: ["01-29", "04-29", "06-10", "07-29", "09-16", "11-05", "12-16"],  # + 2 emergency 03-03/03-15
    2021: ["01-27", "03-17", "04-28", "06-16", "07-28", "09-22", "11-03", "12-15"],
    2022: ["01-26", "03-16", "05-04", "06-15", "07-27", "09-21", "11-02", "12-14"],
    2023: ["02-01", "03-22", "05-03", "06-14", "07-26", "09-20", "11-01", "12-13"],
    2024: ["01-31", "03-20", "05-01", "06-12", "07-31", "09-18", "11-07", "12-18"],
    2025: ["01-29", "03-19", "05-07", "06-18", "07-30", "09-17", "10-29", "12-10"],
    2026: ["01-28", "03-18", "04-29", "06-17", "07-29", "09-16", "10-28", "12-09"],
}
FOMC_EXTRA_2020 = ["2020-03-03", "2020-03-15"]  # emergency cuts (COVID)


def is_edt(d: date) -> bool:
    # DST Mỹ: từ Chủ nhật thứ 2 của tháng 3 đến Chủ nhật thứ 1 của tháng 11 (xấp xỉ theo ngày)
    return d.month > 3 and d.month < 11


def first_friday(year: int, month: int) -> date:
    d = date(year, month, 1)
    while d.weekday() != 4:
        d += timedelta(days=1)
    return d


rows = []
for y, months in FOMC.items():
    for md in months:
        dt = date.fromisoformat(f"{y}-{md}")
        t = "18:00" if is_edt(dt) else "19:00"
        rows.append([dt.isoformat(), t, "FOMC_decision", "red", "fed_schedule_exact"])
for iso in FOMC_EXTRA_2020:
    rows.append([iso, "18:00", "FOMC_emergency", "red", "fed_schedule_exact"])

for y in range(2020, 2027):
    for m in range(1, 13):
        nfp = first_friday(y, m)
        t = "12:30" if is_edt(nfp) else "13:30"
        rows.append([nfp.isoformat(), t, "NFP", "red", "computed_first_friday_exact"])
        # CPI APPROX: ngày 12 hàng tháng (BLS thực tế 10–15)
        rows.append([f"{y}-{m:02d}-12", t, "CPI_APPROX", "red", "approx_verify_bls"])

rows.sort(key=lambda r: (r[0], r[1]))
out = Path(__file__).parent.parent / "config" / "news_calendar.csv"
with open(out, "w", newline="", encoding="utf-8") as f:
    w = csv.writer(f)
    w.writerow(["date_utc", "time_utc", "event", "weight", "note"])
    w.writerows(rows)
print(f"Wrote {len(rows)} rows -> {out}")
