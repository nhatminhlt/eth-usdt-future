"""Hypothesis ledger (PLAN M2.5) — kỷ luật falsification, chống publication bias với chính mình.

Mỗi giả thuyết: ID + tiêu chí pass/fail VIẾT TRƯỚC khi test + verdict.
Cap số giả thuyết mỗi segment (mỗi giả thuyết thêm = 1 lần xoay bánh multiple-testing).
Ledger ghi CẢ giả thuyết chết. File: data/reports/hypothesis_ledger.jsonl
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from loguru import logger

LEDGER = Path(__file__).resolve().parents[3] / "data" / "reports" / "hypothesis_ledger.jsonl"
MAX_PER_SEGMENT = 25  # cap giả thuyết mỗi segment dữ liệu (mục 12, luật 13)


@dataclass
class Hypothesis:
    hid: str
    name: str
    source: str          # "M2.6 H3", "JOTA 2020", "own observation", ...
    criteria: dict       # {"excess_min_pct": 0.05, "t_min": 2.0, "horizon": "+1h", "keep_direction_val": true}
    segment: str         # "TRAIN_2020-2023" — dữ liệu dùng để test LẦN ĐẦU
    registered_at: str = ""
    verdict: str = "pending"     # pending / pass / kill
    result: dict = field(default_factory=dict)


def _read_all() -> list[dict]:
    if not LEDGER.exists():
        return []
    return [json.loads(l) for l in LEDGER.read_text(encoding="utf-8").splitlines() if l.strip()]


def register(hid: str, name: str, source: str, criteria: dict, segment: str) -> Hypothesis:
    existing = [h for h in _read_all() if h["hid"] == hid]
    if existing:
        return Hypothesis(**existing[0])
    seg_count = len([h for h in _read_all() if h["segment"] == segment])
    if seg_count >= MAX_PER_SEGMENT:
        raise RuntimeError(
            f"Cap {MAX_PER_SEGMENT} giả thuyết/segment đã đạt ({segment}) — thêm giả thuyết mới "
            f"= xoay bánh multiple-testing. Cần segment dữ liệu mới hoặc bỏ giả thuyết cũ.")
    h = Hypothesis(hid=hid, name=name, source=source, criteria=criteria, segment=segment,
                   registered_at=datetime.now(timezone.utc).isoformat())
    LEDGER.parent.mkdir(parents=True, exist_ok=True)
    with open(LEDGER, "a", encoding="utf-8") as f:
        f.write(json.dumps(asdict(h), ensure_ascii=False) + "\n")
    logger.info(f"Registered {hid}: {name}")
    return h


def record_verdict(hid: str, verdict: str, result: dict) -> None:
    assert verdict in ("pass", "kill"), verdict
    rows = _read_all()
    found = False
    for r in rows:
        if r["hid"] == hid:
            if r["verdict"] != "pending":
                logger.warning(f"{hid} đã có verdict '{r['verdict']}' — không đổi (tránh churn)")
                return
            r["verdict"] = verdict
            r["result"] = result
            found = True
    if not found:
        raise KeyError(hid)
    with open(LEDGER, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    logger.info(f"{hid} → {verdict}")


def load_all() -> list[dict]:
    return _read_all()
